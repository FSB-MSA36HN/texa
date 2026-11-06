"""Field-level filter edits preserve memory and remain guarded through binding."""
from copy import deepcopy

import pytest

from texa import answer, llm, memory
from texa.progress import Progress
from tests.test_intent_pipeline import candidate as base_candidate, setup
from tests.test_semantic_repair import _bad_category_candidate, _closed_category_vocab


def _prior(filters=None):
    spec = {
        "contract_version": 1,
        "source_ids": ["cosmetics_shop"],
        "shape": "aggregate",
        "recipe": "revenue",
        "metrics": [],
        "selection": [],
        "time_range": {"kind": "all"},
        "filters": deepcopy(filters if filters is not None else [
            {"field": "device_type", "operator": "=", "values": ["mobile"]},
            {"field": "campaign_channel", "operator": "=", "values": ["paid"]},
        ]),
    }
    return {"id": "prior", "question": "Revenue on mobile from paid campaign", "status": "answered",
            "created_at": "before", "state": {"dataset_version": "snapshot", "query_spec": spec}}


def _continuation(*, proposed_filters=None, edits=None, slots=None, contract_filters=None,
                  source_ids=None, recipe="revenue"):
    proposal = base_candidate(source_ids=source_ids or ["cosmetics_shop"], recipe=recipe,
                              filters=deepcopy(proposed_filters or []))
    operations = {key: "keep" for key in memory.SLOT_KEYS}
    operations["filters"] = "set"
    operations.update(slots or {})
    proposal["dialogue"] = {"relation": "followup", "target_id": "prior", "slots": operations,
                            "filter_edits": deepcopy(edits or [])}
    proposal["_filter_edits_required"] = True
    proposal["intent_contract"].update(
        kind="continuation", metric_ids=[recipe] if recipe else [],
        operation="sum" if recipe == "revenue" else "count",
        grain="purchased_item_line" if recipe == "revenue" else "purchased_item_line",
        source_ids=list(source_ids or ["cosmetics_shop"]), breakdown_ids=[],
        filter_ids=list(contract_filters or ["device_type", "campaign_channel"]))
    return proposal


def _history_and_version(prior=None):
    return [prior or _prior()]


def test_reducer_removes_one_field_and_preserves_omitted_inherited_conditions():
    prior = _prior()
    proposal = _continuation(
        proposed_filters=[{"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]}],
        edits=[{"field": "device_type", "operation": "remove"}],
    )

    reduced, context = memory.reduce_candidate(proposal, [prior], 1)

    assert reduced["filters"] == [{"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]}]
    assert reduced["_reduced_filter_ids"] == ["campaign_channel"]
    assert context["filter_edits"] == [{"field": "device_type", "operation": "remove"}]


def test_set_uses_new_payload_and_preserves_other_omitted_filters():
    prior = _prior()
    proposal = _continuation(
        proposed_filters=[{"field": "device_type", "operator": "=", "values_mentioned": ["desktop"]}],
        edits=[{"field": "device_type", "operation": "set"}],
    )

    reduced, _ = memory.reduce_candidate(proposal, [prior], 1)

    assert reduced["filters"] == [
        {"field": "device_type", "operator": "=", "values_mentioned": ["desktop"]},
        {"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]},
    ]


def test_set_replaces_a_filter_field_condition_group_including_range_bounds():
    prior = _prior([
        {"field": "device_type", "operator": ">=", "values": ["mobile"]},
        {"field": "device_type", "operator": "<=", "values": ["tablet"]},
        {"field": "campaign_channel", "operator": "=", "values": ["paid"]},
    ])
    proposal = _continuation(
        proposed_filters=[
            {"field": "device_type", "operator": ">=", "values_mentioned": ["desktop"]},
            {"field": "device_type", "operator": "<=", "values_mentioned": ["tablet"]},
        ],
        edits=[{"field": "device_type", "operation": "set"}],
    )

    reduced, _ = memory.reduce_candidate(proposal, [prior], 1)

    assert reduced["filters"] == [
        {"field": "device_type", "operator": ">=", "values_mentioned": ["desktop"]},
        {"field": "device_type", "operator": "<=", "values_mentioned": ["tablet"]},
        {"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]},
    ]


@pytest.mark.parametrize("edits,payload", [
    ([{"field": "device_type", "operation": "remove"},
      {"field": "device_type", "operation": "set"}], []),
    ([{"field": "item_category", "operation": "remove"}], []),
    ([{"field": "item_category", "operation": "set"}], []),
    ([{"field": "device_type", "operation": "remove"}],
     [{"field": "campaign_channel", "operator": "=", "values_mentioned": ["email"]}]),
])
def test_reducer_rejects_duplicate_unknown_or_undeclared_filter_changes(edits, payload):
    proposal = _continuation(proposed_filters=payload, edits=edits)
    with pytest.raises(llm.LLMError):
        memory.reduce_candidate(proposal, _history_and_version(), 1)


def test_empty_edits_reject_live_filter_changes_but_allow_identical_noop():
    changed = _continuation(proposed_filters=[
        {"field": "device_type", "operator": "=", "values_mentioned": ["desktop"]},
        {"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]},
    ])
    with pytest.raises(llm.LLMError, match="explicit field edits"):
        memory.reduce_candidate(changed, _history_and_version(), 1)

    identical = _continuation(proposed_filters=[
        {"field": "device_type", "operator": "=", "values_mentioned": ["mobile"]},
        {"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]},
    ])
    reduced, _ = memory.reduce_candidate(identical, _history_and_version(), 1)
    assert reduced["_reduced_filter_ids"] == ["device_type", "campaign_channel"]


def _wire_pipeline(monkeypatch, proposal, *, scope=None):
    prior = _prior()
    turn, cat, sources, compiled = setup(monkeypatch, proposal, question="And remove mobile, keep paid", scope=scope,
                                         history=[prior])
    source = sources["cosmetics_shop"]
    source.ep_keys.add("campaign.channel")
    source.values["ep.campaign.channel"] = {"paid": "paid", "email": "email"}
    return turn, cat, sources, compiled


def test_legacy_full_filter_contract_plus_explicit_remove_compiles_only_paid(monkeypatch):
    proposal = _continuation(
        proposed_filters=[{"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]}],
        edits=[{"field": "device_type", "operation": "remove"}],
        contract_filters=["device_type", "campaign_channel"],
    )
    _, _, _, compiled = _wire_pipeline(monkeypatch, proposal)

    result = answer._question_work("now")(Progress())

    assert result["status"] == "answered"
    assert len(compiled) == 1
    assert compiled[0]["filters"] == [{"field": "campaign_channel", "operator": "=", "values": ["paid"]}]


def test_bound_filter_loss_is_refused_before_sql_execution(monkeypatch):
    proposal = _continuation(
        proposed_filters=[{"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]}],
        edits=[{"field": "device_type", "operation": "remove"}],
    )
    _, _, _, compiled = _wire_pipeline(monkeypatch, proposal)
    original = answer.clarify.advance

    def drop_filter(*args, **kwargs):
        outcome = original(*args, **kwargs)
        if outcome.kind == "spec":
            outcome.spec["filters"] = []
        return outcome

    monkeypatch.setattr(answer.clarify, "advance", drop_filter)
    result = answer._question_work("now")(Progress())

    assert result["status"] == "refused"
    assert result["reason_code"] == "intent_contract_mismatch"
    assert not compiled


@pytest.mark.parametrize("change,expected_status", [("source", "needs_clarification"), ("measure", "refused")])
def test_filter_edit_does_not_authorize_source_or_measure_change(monkeypatch, change, expected_status):
    proposal = _continuation(
        proposed_filters=[{"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]}],
        edits=[{"field": "device_type", "operation": "remove"}],
        source_ids=["olist_marketplace"] if change == "source" else ["cosmetics_shop"],
        recipe="purchases" if change == "measure" else "revenue",
        slots={"source_ids": "set"} if change == "source" else {"recipe": "set", "metrics": "clear"},
    )
    if change == "source":
        proposal["intent_contract"]["source_ids"] = ["olist_marketplace"]
    else:
        proposal["intent_contract"].update(metric_ids=["purchases"], operation="count", grain="purchased_item_line")
    _, _, _, compiled = _wire_pipeline(monkeypatch, proposal,
                                       scope=["cosmetics_shop"] if change == "source" else None)

    result = answer._question_work("now")(Progress())

    assert result["status"] == expected_status
    assert not compiled


@pytest.mark.parametrize("change", ["drop_mobile", "period", "measure", "extra_filter", "extra_condition"])
def test_semantic_repair_cannot_drop_or_change_unrelated_constraints(monkeypatch, change):
    initial = _bad_category_candidate()
    _, _, sources, compiled = setup(monkeypatch, initial, question="Revenue by category, mobile")
    _closed_category_vocab(sources)
    calls = 0

    def interpret(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return deepcopy(initial)
        repaired = base_candidate(selection=["item_category"], filters=[
            {"field": "device_type", "operator": "=", "values_mentioned": ["mobile"]},
        ])
        repaired["intent_contract"].update(breakdown_ids=["item_category"], filter_ids=["device_type"])
        if change == "drop_mobile":
            repaired["filters"] = []
            repaired["intent_contract"]["filter_ids"] = []
        elif change == "period":
            repaired["time_range"] = {"kind": "between", "days": 0, "start": "2025-02-01", "end": "2025-02-28"}
        elif change == "measure":
            repaired["recipe"] = "purchases"
            repaired["intent_contract"].update(metric_ids=["purchases"], operation="count", grain="purchased_item_line")
        elif change == "extra_filter":
            repaired["filters"].append({"field": "campaign_channel", "operator": "=", "values_mentioned": ["paid"]})
            repaired["intent_contract"]["filter_ids"].append("campaign_channel")
        elif change == "extra_condition":
            repaired["filters"].append({"field": "device_type", "operator": "!=", "values_mentioned": ["desktop"]})
        return repaired

    monkeypatch.setattr(answer.interpret, "interpret", interpret)
    result = answer._question_work("now")(Progress())

    assert result["status"] == "refused"
    assert result["reason_code"] in {"semantic_repair_constraint_mismatch", "intent_contract_mismatch"}
    assert calls == 2 and not compiled
