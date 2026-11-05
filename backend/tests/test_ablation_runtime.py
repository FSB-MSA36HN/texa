"""Offline tests for study variants and their actual Texa execution paths."""
import pytest

from texa import ablation, answer, clarify, llm
from texa.progress import Progress
from texa.spec import SpecError
from tests.test_units import CAT, SOURCES


@pytest.mark.parametrize("value", [None, "F"])
def test_default_or_explicit_full_variant_keeps_structured_memory(monkeypatch, value):
    monkeypatch.delenv("TEXA_ABLATION_VARIANT", raising=False)
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    if value:
        monkeypatch.setenv("TEXA_ABLATION_VARIANT", value)
    assert ablation.variant() == "F"
    assert ablation.memory_mode() == "structured"
    assert not ablation.memory_disabled()


def test_legacy_window6_aliases_m6_but_explicit_conflict_is_rejected(monkeypatch):
    monkeypatch.delenv("TEXA_ABLATION_VARIANT", raising=False)
    monkeypatch.setenv("TEXA_MEMORY_MODE", "window6")
    assert ablation.variant() == "M6"
    assert ablation.memory_mode() == "window6"
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "F")
    with pytest.raises(llm.LLMError) as exc:
        ablation.variant()
    assert exc.value.code == "ABLATION_CONFIG_CONFLICT"


@pytest.mark.parametrize("value,code", [("unknown", "BAD_ABLATION_VARIANT"), ("M0", "BAD_LEGACY_MEMORY_MODE")])
def test_invalid_study_configuration_fails_closed(monkeypatch, value, code):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", value)
    if value == "M0":
        monkeypatch.setenv("TEXA_MEMORY_MODE", "nonsense")
    else:
        monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    with pytest.raises(llm.LLMError) as exc:
        ablation.variant()
    assert exc.value.code == code


def _turn(variant="M0"):
    trace = ablation.initial_trace(variant)
    return {"id": "current", "question": "Back to revenue?", "conversation_id": "conversation", "model": "same-model",
            "state": {"scope": [], "ablation": trace}}


def test_m0_uses_no_history_or_hidden_context_and_records_variant(monkeypatch):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "M0")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    monkeypatch.setattr(answer, "_persist_language", lambda *_: None)
    monkeypatch.setattr(answer, "load_turn", lambda _: _turn())
    monkeypatch.setattr(answer.catalog_mod, "published", lambda: CAT)
    monkeypatch.setattr(answer.catalog_mod, "load_sources", lambda **_: SOURCES)
    monkeypatch.setattr(answer.catalog_mod, "scoped_sources", lambda _cat, src: src)
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot")
    monkeypatch.setattr(answer, "_history", lambda *_: pytest.fail("M0 must not read history"))
    monkeypatch.setattr(answer.memory, "select_context", lambda *_a, **_k: pytest.fail("M0 must not select memory"))
    monkeypatch.setattr(answer.llm, "get_connection", lambda **_: {"answer_language": "auto"})
    captured = {}

    def interpret(_q, previous, *_a, context=None, **_k):
        captured.update(previous=previous, context=context)
        return {"outcome": "conversation", "reply": "OK", "suggestions": [], "language": "en"}

    monkeypatch.setattr(answer.interpret, "interpret", interpret)
    work = answer._question_work("current")
    result = work(Progress())
    assert captured["previous"] == []
    assert captured["context"]["relation"] == "disabled"
    assert captured["context"]["references"] == []
    assert result["ablation"]["variant"] == "M0"


def test_m6_passes_exactly_six_most_recent_turns_to_interpretation(monkeypatch):
    monkeypatch.delenv("TEXA_ABLATION_VARIANT", raising=False)
    monkeypatch.setenv("TEXA_MEMORY_MODE", "window6")
    history = [{"id": str(i), "question": f"Question {i}", "status": "answered",
                "state": {"dataset_version": "snapshot"}} for i in range(10)]
    monkeypatch.setattr(answer, "_persist_language", lambda *_: None)
    monkeypatch.setattr(answer, "load_turn", lambda _: {
        "id": "current", "question": "What next?", "conversation_id": "conversation", "model": None,
        "state": {"scope": [], "ablation": ablation.initial_trace("M6")},
    })
    monkeypatch.setattr(answer.catalog_mod, "published", lambda: CAT)
    monkeypatch.setattr(answer.catalog_mod, "load_sources", lambda **_: SOURCES)
    monkeypatch.setattr(answer.catalog_mod, "scoped_sources", lambda _cat, src: src)
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot")
    monkeypatch.setattr(answer, "_history", lambda *_: history)
    monkeypatch.setattr(answer.memory, "select_context", lambda *_a, **_k: pytest.fail("M6 must not retrieve outside its fixed window"))
    monkeypatch.setattr(answer.llm, "get_connection", lambda **_: {"answer_language": "auto"})
    captured = {}

    def interpret(_q, previous, *_a, context=None, **_k):
        captured.update(previous=previous, context=context)
        return {"outcome": "conversation", "reply": "OK", "suggestions": [], "language": "en"}

    monkeypatch.setattr(answer.interpret, "interpret", interpret)
    result = answer._question_work("current")(Progress())
    assert [turn["id"] for turn in captured["previous"]] == [str(i) for i in range(4, 10)]
    assert captured["context"]["relation"] == "window6"
    assert result["ablation"]["variant"] == "M6"


def test_question_work_preserves_updated_c0_trace(monkeypatch):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "C0")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    turn = {"id": "current", "question": "How much revenue?", "conversation_id": "conversation", "model": None,
            "state": {"scope": [], "ablation": ablation.initial_trace("C0")}}
    monkeypatch.setattr(answer, "_persist_language", lambda *_: None)
    monkeypatch.setattr(answer, "load_turn", lambda _: turn)
    monkeypatch.setattr(answer.catalog_mod, "published", lambda: CAT)
    monkeypatch.setattr(answer.catalog_mod, "load_sources", lambda **_: SOURCES)
    monkeypatch.setattr(answer.catalog_mod, "scoped_sources", lambda _cat, src: src)
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot")
    monkeypatch.setattr(answer, "_history", lambda *_: [])
    monkeypatch.setattr(answer.memory, "select_context", lambda *_a, **_k: {"turns": [], "relation": "new_topic", "references": [], "inherited_slots": {}})
    monkeypatch.setattr(answer.llm, "get_connection", lambda **_: {"answer_language": "auto"})
    monkeypatch.setattr(answer.interpret, "interpret", lambda *_a, **_k: {"outcome": "query", "dialogue": {"relation": "new_topic", "target_id": "", "slots": {k: "set" for k in answer.memory.SLOT_KEYS}}})
    updated = ablation.initial_trace("C0") | {"clarification_requested": True, "clarification_eligible": True,
                                               "clarification_invoked": True, "clarification_field": "time_range",
                                               "clarification_choice_id": "all", "clarification_choices": ["all", "last_30"],
                                               "clarification_choice_count": 2, "clarification_reason": "selected"}
    monkeypatch.setattr(answer, "_continue", lambda *_a, **_k: {"status": "answered", "ablation": updated})
    result = answer._question_work("current")(Progress())
    assert result["ablation"] == updated


def test_m0_rejects_stale_explicit_reference_form(monkeypatch):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "M0")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    monkeypatch.setattr(answer, "_persist_language", lambda *_: None)
    monkeypatch.setattr(answer, "load_turn", lambda _: _turn())
    monkeypatch.setattr(answer.catalog_mod, "published", lambda: CAT)
    monkeypatch.setattr(answer.catalog_mod, "scoped_sources", lambda _cat, src: src)
    monkeypatch.setattr(answer.catalog_mod, "load_sources", lambda **_: SOURCES)
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot")
    with pytest.raises(SpecError) as exc:
        answer._question_work("current", reference_id="earlier")(Progress())
    assert exc.value.code == "memory_disabled"


def _ambiguous_time_outcome():
    form = {"fields": [{"id": "time_range", "kind": "single_choice", "allow_other": False,
                        "label": "Which period?", "choices": [{"id": "all", "label": "All data"},
                                                                    {"id": "last_30", "label": "Last 30 days"}]}]}
    return clarify.Outcome("clarify", form=form)


def test_c0_guesses_only_an_offered_choice_then_runs_normal_validation(monkeypatch):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "C0")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    turn = _turn("C0")
    turn["question"] = "How much revenue?"
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot")
    monkeypatch.setattr(answer.catalog_mod, "scoped_sources", lambda _cat, src: src)
    monkeypatch.setattr(answer, "_lang", lambda _: "en")
    monkeypatch.setattr(answer, "run_spec", lambda spec, *_: {"query_spec": {"filters": [], "source_ids": ["cosmetics_shop"]}})
    monkeypatch.setattr(answer, "_answered", lambda *_a, **_k: {"status": "answered"})
    calls = []

    def advance(_candidate, answers, *_a, **_k):
        calls.append(answers)
        return _ambiguous_time_outcome() if not answers else clarify.Outcome("spec", spec={"time_range": answers["time_range"]})

    monkeypatch.setattr(answer.clarify, "advance", advance)
    provider_calls = []

    def choose(**kwargs):
        provider_calls.append(kwargs)
        return {"choice_id": "all"}

    monkeypatch.setattr(ablation.llm, "generate_structured", choose)
    result = answer._continue(turn, {"outcome": "query"}, {}, Progress(), CAT, SOURCES)
    assert calls == [{}, {"time_range": ["all"]}]
    assert len(provider_calls) == 1
    assert provider_calls[0]["model"] == "same-model"
    assert "all" in str(provider_calls[0]["prompt"])
    assert result["ablation"]["clarification_invoked"] is True
    assert result["ablation"]["clarification_choice_id"] == "all"


@pytest.mark.parametrize("response,reason", [({"choice_id": "gold-answer"}, "guess_not_in_offered_choices"),
                                              (None, "guess_call_failed")])
def test_c0_invalid_or_failed_guess_refuses_without_executing(monkeypatch, response, reason):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "C0")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    turn = _turn("C0")
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot")
    monkeypatch.setattr(answer.catalog_mod, "scoped_sources", lambda _cat, src: src)
    monkeypatch.setattr(answer, "_lang", lambda _: "en")
    monkeypatch.setattr(answer.clarify, "advance", lambda *_a, **_k: _ambiguous_time_outcome())
    monkeypatch.setattr(answer, "run_spec", lambda *_: pytest.fail("bad guess must not execute"))

    def choose(**_kwargs):
        if response is None:
            raise llm.LLMError("TIMEOUT", "timed out")
        return response

    monkeypatch.setattr(ablation.llm, "generate_structured", choose)
    result = answer._continue(turn, {"outcome": "query"}, {}, Progress(), CAT, SOURCES)
    assert result["status"] == "refused"
    assert result["ablation"]["clarification_reason"] == reason


def test_c0_preserves_out_of_scope_clarification_without_guess_call(monkeypatch):
    monkeypatch.setenv("TEXA_ABLATION_VARIANT", "C0")
    monkeypatch.delenv("TEXA_MEMORY_MODE", raising=False)
    turn = _turn("C0")
    form = {"fields": [{"id": "filter:item_brand", "kind": "multi_choice", "allow_other": False,
                        "choices": [{"id": "Acme", "label": "Acme"}]}]}
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot")
    monkeypatch.setattr(answer.catalog_mod, "scoped_sources", lambda _cat, src: src)
    monkeypatch.setattr(answer, "_lang", lambda _: "en")
    monkeypatch.setattr(answer.clarify, "advance", lambda *_a, **_k: clarify.Outcome("clarify", form=form))
    monkeypatch.setattr(ablation.llm, "generate_structured", lambda **_: pytest.fail("unsupported form is not guessed"))
    result = answer._continue(turn, {"outcome": "query"}, {}, Progress(), CAT, SOURCES)
    assert result["status"] == "needs_clarification"
    assert result["ablation"]["clarification_requested"] is True
    assert result["ablation"]["clarification_eligible"] is False
    assert result["ablation"]["clarification_invoked"] is False
