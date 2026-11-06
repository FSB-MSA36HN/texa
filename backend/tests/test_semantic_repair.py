"""Bounded semantic re-resolution for closed-vocabulary filter binding."""
from copy import deepcopy

import pytest

from texa import answer, llm
from texa.progress import Cancelled, Progress
from tests.test_intent_pipeline import candidate, setup


def _closed_category_vocab(sources):
    source = sources["cosmetics_shop"]
    source.value_vocab_fields.add("item_category")
    source.values["item_category"] = {"skin": "skin", "hair": "hair"}


def _bad_category_candidate():
    proposal = candidate(filters=[
        {"field": "item_category", "operator": "=", "values_mentioned": ["Cosmetics"]},
        {"field": "device_type", "operator": "=", "values_mentioned": ["mobile"]},
    ])
    proposal["intent_contract"].update(filter_ids=["item_category", "device_type"], breakdown_ids=[])
    return proposal


def _repaired_breakdown_candidate():
    proposal = candidate(selection=["item_category"], filters=[
        {"field": "device_type", "operator": "=", "values_mentioned": ["mobile"]},
    ])
    proposal["intent_contract"].update(filter_ids=["device_type"], breakdown_ids=["item_category"])
    return proposal


def test_unknown_category_is_reinterpreted_as_breakdown_and_keeps_mobile_filter(monkeypatch):
    initial, repaired = _bad_category_candidate(), _repaired_breakdown_candidate()
    _, _, sources, compiled = setup(monkeypatch, initial, question="Revenue by category on mobile")
    _closed_category_vocab(sources)
    calls = []

    def interpret(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return deepcopy(initial)
        assert kwargs["normalize"] is None  # one bounded retry; no second normalization/consistency pass
        feedback = kwargs["context"]["validation_feedback"]
        assert feedback["code"] == "unknown_filter_value"
        assert feedback["params"]["value"] == "Cosmetics"
        return deepcopy(repaired)

    monkeypatch.setattr(answer.interpret, "interpret", interpret)
    result = answer._question_work("now")(Progress())

    assert result["status"] == "answered"
    assert result["semantic_repair"]["attempts"] == 1
    assert len(calls) == 2
    assert len(compiled) == 1
    assert compiled[0]["shape"] == "breakdown"
    assert compiled[0]["selection"] == ["item_category"]
    assert compiled[0]["filters"] == [{"field": "device_type", "operator": "=", "values": ["mobile"]}]


def test_unavailable_category_literal_still_refuses_after_single_retry(monkeypatch):
    initial = _bad_category_candidate()
    _, _, sources, compiled = setup(monkeypatch, initial)
    _closed_category_vocab(sources)
    calls = []

    def interpret(*args, **kwargs):
        calls.append(kwargs)
        return deepcopy(initial)

    monkeypatch.setattr(answer.interpret, "interpret", interpret)
    result = answer._question_work("now")(Progress())

    assert result["status"] == "refused"
    assert result["semantic_repair"]["attempts"] == 1
    assert len(calls) == 2 and calls[1]["normalize"] is None
    assert not compiled


@pytest.mark.parametrize("case", ["derived_measure", "source_conflict"])
def test_derived_measure_and_source_conflict_are_not_retried(monkeypatch, case):
    proposal = _bad_category_candidate()
    question = "Revenue by category on mobile"
    if case == "derived_measure":
        proposal["intent_contract"].update(kind="derived_measure", operation="ratio", grain="order")
    else:
        question = "Doanh thu Olist theo danh mục"
    _, _, sources, compiled = setup(monkeypatch, proposal, question=question,
                                    scope=["cosmetics_shop"] if case == "source_conflict" else None)
    _closed_category_vocab(sources)
    calls = []
    monkeypatch.setattr(answer.interpret, "interpret", lambda *a, **kw: calls.append(kw) or deepcopy(proposal))

    result = answer._question_work("now")(Progress())

    assert result["status"] in ({"refused"} if case == "derived_measure" else {"needs_clarification"})
    assert len(calls) == 1
    assert not compiled


def test_retry_model_error_propagates(monkeypatch):
    initial = _bad_category_candidate()
    _, _, sources, compiled = setup(monkeypatch, initial)
    _closed_category_vocab(sources)
    calls = 0

    def interpret(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return deepcopy(initial)
        raise llm.LLMError("GATEWAY_UNAVAILABLE", "retry failed")

    monkeypatch.setattr(answer.interpret, "interpret", interpret)
    with pytest.raises(llm.LLMError, match="retry failed"):
        answer._question_work("now")(Progress())
    assert calls == 2 and not compiled


def test_cancellation_during_retry_propagates_without_second_model_call(monkeypatch):
    initial = _bad_category_candidate()
    _, _, sources, compiled = setup(monkeypatch, initial)
    _closed_category_vocab(sources)
    calls = 0
    cancelled = False

    def interpret(*args, **kwargs):
        nonlocal calls, cancelled
        calls += 1
        cancelled = True
        return deepcopy(initial)

    monkeypatch.setattr(answer.interpret, "interpret", interpret)
    progress = Progress(cancelled=lambda: cancelled)
    with pytest.raises(Cancelled):
        answer._question_work("now")(progress)
    assert calls == 1 and not compiled
