"""Regression seams: real reducer/binder/policy, scripted interpretation, no DB/LLM."""
from copy import deepcopy
import json
from pathlib import Path

import yaml

from texa import answer, catalog, interpret, memory
from texa.progress import Progress
from texa.spec import validate_spec


def setup(monkeypatch, proposal, *, question="Revenue", scope=None, history=()):
    cat = catalog.validate_catalog(yaml.safe_load((Path(__file__).resolve().parents[2] /
                                                   "catalog/product_events.yaml").read_text()))
    cat.contract_version = 1
    sources = {sid: catalog.Source(
        id=sid, label=label, description="", currency=currency,
        min_date=start, max_date=end, row_count=10, user_count=3,
        events=events, columns={"revenue", "item_category", "session_id"},
        ep_keys={"device.type"}, values={"ep.device.type": {"mobile": "mobile"}},
    ) for sid, label, currency, start, end, events in (
        ("cosmetics_shop", "Cosmetics Shop", "USD", "2025-01-01", "2025-03-31", {"view", "purchase"}),
        ("olist_marketplace", "Olist", "BRL", "2018-01-01", "2018-02-28", {"order_purchased"}),
    )}
    turn = {"id": "now", "question": question, "conversation_id": "conversation", "model": "scripted",
            "state": {"scope": scope or []}}
    monkeypatch.setattr(answer, "load_turn", lambda _: turn)
    monkeypatch.setattr(answer, "_history", lambda *_: list(history))
    monkeypatch.setattr(answer, "_snapshot", lambda _: "snapshot")
    monkeypatch.setattr(answer, "_persist_language", lambda *_: None)
    monkeypatch.setattr(answer.catalog_mod, "published", lambda: cat)
    monkeypatch.setattr(answer.catalog_mod, "load_sources", lambda **_: sources)
    monkeypatch.setattr(answer.llm, "get_connection", lambda **_: None)
    monkeypatch.setattr(answer.interpret, "interpret", lambda *a, **k: deepcopy(proposal))
    monkeypatch.setattr(answer.suggestions, "questions", lambda *a, **k: [])
    compiled = []

    def execute(spec, *_args):
        checked = validate_spec(spec | {"contract_version": 1}, cat, sources).model_dump(mode="json")
        compiled.append(checked)
        return {"query_spec": checked}

    monkeypatch.setattr(answer, "run_spec", execute)
    monkeypatch.setattr(answer, "_answered", lambda _q, result, *a, **k: {"status": "answered", **result})
    return turn, cat, sources, compiled


def candidate(**updates):
    result = {"outcome": "query", "reason": "", "reply": "", "suggestions": [],
              "source_ids": ["cosmetics_shop"], "recipe": "revenue", "metrics": [],
              "recipe_alternatives": [], "recipe_stated": True, "shape": "aggregate", "selection": [],
              "filters": [], "top_k": 0, "time_range": {"kind": "all", "days": 0, "start": "", "end": ""},
              "answer_request": {"need": "describe", "ask": ""}, "language": "vi",
              "dialogue": {"relation": "new_topic", "target_id": "",
                           "slots": {key: "set" for key in memory.SLOT_KEYS}},
              "intent_contract": {"kind": "catalog_metric", "metric_ids": ["revenue"],
                  "operation": "sum", "entity": "", "grain": "purchased_item_line",
                  "source_ids": ["cosmetics_shop"], "breakdown_ids": [], "filter_ids": []}}
    return result | updates


def test_supported_false_refusal_reaches_real_binder_before_execution(monkeypatch):
    proposal = candidate(outcome="unsupported", reason="No capability")
    _, _, _, compiled = setup(monkeypatch, proposal)
    result = answer._question_work("now")(Progress())
    assert result["status"] == "answered"
    assert len(compiled) == 1 and compiled[0]["recipe"] == "revenue"


def test_unsupported_order_grain_never_reaches_query_or_writer(monkeypatch):
    proposal = candidate(recipe="", metrics=["revenue", "purchases"],
                         answer_request={"need": "describe", "ask": "Compute an order average"})
    proposal["intent_contract"].update(kind="derived_measure", metric_ids=["revenue", "purchases"],
                                       operation="ratio", grain="order")
    _, _, _, compiled = setup(monkeypatch, proposal)
    result = answer._question_work("now")(Progress())
    assert result["status"] == "refused" and not compiled


def test_source_conflict_cannot_disappear_when_refusal_omits_source_ids(monkeypatch):
    proposal = candidate(outcome="unsupported", source_ids=[], reason="No capability")
    proposal["intent_contract"]["source_ids"] = []
    _, _, _, compiled = setup(monkeypatch, proposal, scope=["cosmetics_shop"],
                              question="Doanh thu Olist trên toàn bộ dữ liệu")
    result = answer._question_work("now")(Progress())
    assert result["status"] == "needs_clarification" and not compiled
    assert result["form"]["fields"][0]["id"] == "context:source"


def test_bound_metric_substitution_is_rejected_even_when_sql_would_be_valid(monkeypatch):
    proposal = candidate()
    turn, cat, sources, compiled = setup(monkeypatch, proposal)
    original = answer.clarify.advance

    def substitute(*args, **kwargs):
        result = original(*args, **kwargs)
        result.spec["recipe"] = "buyers"
        return result

    monkeypatch.setattr(answer.clarify, "advance", substitute)
    result = answer._continue(turn, proposal, {}, Progress(), cat, sources)
    assert result["status"] == "refused" and not compiled
    assert result["reason_code"] == "intent_contract_mismatch"


def test_contract_role_reconciliation_preserves_other_filters_and_group_shape(monkeypatch):
    proposal = candidate(filters=[{"field": "item_category", "operator": "=", "values_mentioned": ["Cosmetics"]},
                                  {"field": "device_type", "operator": "=", "values_mentioned": ["mobile"]}])
    proposal["intent_contract"].update(breakdown_ids=["item_category"], filter_ids=["device_type"])
    _, _, _, compiled = setup(monkeypatch, proposal)
    result = answer._question_work("now")(Progress())
    assert result["status"] == "answered"
    assert compiled[0]["shape"] == "breakdown" and compiled[0]["selection"] == ["item_category"]
    assert compiled[0]["filters"] == [{"field": "device_type", "operator": "=", "values": ["mobile"]}]


def test_supported_refusal_can_resume_after_user_resolves_source_conflict(monkeypatch):
    proposal = candidate(outcome="unsupported", source_ids=["olist_marketplace"])
    proposal["intent_contract"]["source_ids"] = ["olist_marketplace"]
    turn, cat, sources, compiled = setup(monkeypatch, proposal, scope=["cosmetics_shop"],
                                        question="Doanh thu Olist trên toàn bộ dữ liệu")
    pending = answer._question_work("now")(Progress())
    assert pending["status"] == "needs_clarification" and not compiled
    turn["state"].update(pending)
    result = answer._continue(turn, pending["candidate"], {"context:source": ["olist_marketplace"]},
                              Progress(), cat, sources)
    assert result["status"] == "answered"
    assert compiled[0]["source_ids"] == ["olist_marketplace"]


def test_user_metric_choice_binds_ambiguous_contract_before_execution(monkeypatch):
    proposal = candidate(recipe="", recipe_stated=False, recipe_alternatives=["events", "purchases"])
    proposal["intent_contract"].update(kind="ambiguous_metric", metric_ids=["events", "purchases"],
                                       operation="", grain="")
    turn, cat, sources, compiled = setup(monkeypatch, proposal, question="Choose a counting definition")
    pending = answer._question_work("now")(Progress())
    assert pending["status"] == "needs_clarification" and not compiled
    turn["state"].update(pending)
    result = answer._continue(turn, pending["candidate"], {"recipe": ["purchases"]}, Progress(), cat, sources)
    assert result["status"] == "answered" and compiled[0]["recipe"] == "purchases"


def test_source_clarification_keeps_reduced_followup_filters(monkeypatch):
    prior_spec = {"contract_version": 1, "source_ids": ["cosmetics_shop"], "shape": "aggregate",
                  "recipe": "revenue", "metrics": [], "selection": [], "time_range": {"kind": "all"},
                  "filters": [{"field": "device_type", "operator": "=", "values": ["mobile"]}]}
    prior = {"id": "prior", "question": "Mobile revenue", "status": "answered", "created_at": "before",
             "state": {"dataset_version": "snapshot", "query_spec": prior_spec}}
    proposal = candidate(source_ids=["olist_marketplace"])
    proposal["dialogue"] = {"relation": "followup", "target_id": "prior",
                             "slots": {key: "keep" for key in memory.SLOT_KEYS}}
    proposal["dialogue"]["slots"]["source_ids"] = "set"
    proposal["intent_contract"].update(kind="continuation", metric_ids=[], operation="", grain="",
                                       source_ids=["olist_marketplace"])
    turn, cat, sources, compiled = setup(monkeypatch, proposal, question="And Olist?",
                                        scope=["cosmetics_shop"], history=[prior])
    pending = answer._question_work("now")(Progress())
    assert pending["status"] == "needs_clarification" and not compiled
    assert pending["context"]["references"] == ["prior"]
    turn["state"].update(pending)
    result = answer._continue(turn, pending["candidate"], {"context:source": ["olist_marketplace"]},
                              Progress(), cat, sources)
    assert result["status"] == "answered"
    assert compiled[0]["filters"] == prior_spec["filters"]


def test_capability_evidence_tracks_metadata_even_when_source_is_renamed(monkeypatch):
    _, cat, sources, _ = setup(monkeypatch, candidate())
    source = sources["cosmetics_shop"].model_copy(update={"id": "new_store", "label": "New Store"})

    def evidence(current):
        text = interpret.render_catalog(cat, {current.id: current})
        block = text.split("SOURCE CAPABILITIES", 1)[1].split("\nMETRICS", 1)[0]
        return json.loads(next(line for line in block.splitlines() if line.startswith("{")))

    available = evidence(source)
    assert available["source_id"] == "new_store"
    assert "viewers" in available["available_metric_ids"]
    assert available["tracked_event_roles"]["product_view"] == ["view"]
    absent = evidence(source.model_copy(update={"events": {"purchase"}}))
    assert "viewers" not in absent["available_metric_ids"]
    assert "viewers" in absent["unavailable_metric_reasons"]


def test_server_detected_ambiguity_accepts_user_choice_even_if_model_was_confident(monkeypatch):
    proposal = candidate(recipe="buyers")
    proposal["intent_contract"].update(metric_ids=["buyers"], operation="count_users", grain="purchasing_user_period")
    turn, cat, sources, compiled = setup(monkeypatch, proposal, question="Volume")
    cat.metric_ambiguities.append(catalog.MetricAmbiguity(
        id="volume_definition", phrases=["volume"], metric_ids=["buyers", "purchases"]))
    pending = answer._question_work("now")(Progress())
    assert pending["status"] == "needs_clarification" and not compiled
    turn["state"].update(pending)
    result = answer._continue(turn, pending["candidate"], {"recipe": ["purchases"]}, Progress(), cat, sources)
    assert result["status"] == "answered" and compiled[0]["recipe"] == "purchases"
