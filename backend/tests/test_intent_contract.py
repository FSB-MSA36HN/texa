from pathlib import Path
import yaml

from texa import catalog, intent
from tests.test_units import SOURCES

ROOT = Path(__file__).resolve().parents[2]
CAT = catalog.validate_catalog(yaml.safe_load((ROOT / "catalog/product_events.yaml").read_text()))


def _contract(kind, metrics, operation, grain, *, breakdowns=(), filters=(), sources=()):
    return {"kind": kind, "metric_ids": list(metrics), "operation": operation, "entity": "",
            "grain": grain, "source_ids": list(sources), "breakdown_ids": list(breakdowns),
            "filter_ids": list(filters)}


def test_catalog_metric_intent_must_match_metric_operation_and_grain():
    candidate = {"outcome": "query", "recipe": "revenue", "metrics": [], "selection": [], "filters": [],
                 "source_ids": ["olist_marketplace"], "intent_contract": _contract(
                     "catalog_metric", ["revenue"], "sum", "purchased_item_line_value",
                     sources=["olist_marketplace"])}
    assert intent.mismatch(candidate, CAT) is None
    candidate["intent_contract"] = _contract("catalog_metric", ["revenue"], "ratio", "order")
    assert intent.mismatch(candidate, CAT) == "intent_operation_mismatch"


def test_aov_style_derived_measure_is_not_promoted_to_component_metrics():
    candidate = {"outcome": "unsupported", "recipe": "", "metrics": ["revenue", "purchases"],
                 "selection": [], "filters": [], "source_ids": ["olist_marketplace"],
                 "intent_contract": _contract("derived_measure", ["revenue", "purchases"], "ratio", "order")}
    assert intent.materialize_catalog_intent(candidate, CAT) is None
    assert intent.mismatch(candidate, CAT) == "non_catalog_measure"


def test_supported_refusal_can_recover_only_when_contract_and_proposal_agree():
    candidate = {"outcome": "unsupported", "recipe": "events", "metrics": [], "selection": [],
                 "filters": [{"field": "event_name", "operator": "=", "values_mentioned": ["purchase"]}],
                 "source_ids": ["cosmetics_shop"], "intent_contract": _contract(
                     "catalog_metric", ["events"], "count_events", "event_row",
                     filters=["event_name"], sources=["cosmetics_shop"])}
    recovered = intent.materialize_catalog_intent(candidate, CAT)
    assert recovered["outcome"] == "unsupported"  # caller alone changes outcome after full resolver checks
    assert intent.mismatch(recovered, CAT) is None
    recovered["intent_contract"] = _contract("catalog_metric", ["revenue"], "sum", "purchased_item_line_value")
    assert intent.materialize_catalog_intent(recovered, CAT) is None


def test_intent_contract_recovers_filter_vs_breakdown_role_from_explicit_contract():
    candidate = {"outcome": "query", "recipe": "revenue", "metrics": [], "selection": [],
                 "filters": [{"field": "item_category", "operator": "=", "values_mentioned": ["Cosmetics"]},
                             {"field": "device_type", "operator": "=", "values_mentioned": ["mobile"]}],
                 "intent_contract": _contract("catalog_metric", ["revenue"], "sum", "purchased_item_line_value",
                                               breakdowns=["item_category"], filters=["device_type"])}
    fixed = intent.reconcile_dimension_roles(candidate)
    assert fixed["selection"] == ["item_category"]
    assert [item["field"] for item in fixed["filters"]] == ["device_type"]
    assert intent.mismatch(fixed, CAT) is None


def test_source_conflict_survives_model_omitting_sources_and_requires_choice():
    assert intent.has_source_conflict(["cosmetics_shop"], [], ["olist_marketplace"], 1)
    assert intent.has_source_conflict([], ["cosmetics_shop", "olist_marketplace"],
                                      ["cosmetics_shop", "olist_marketplace"], 1)
    assert not intent.has_source_conflict(["cosmetics_shop"], ["cosmetics_shop"], ["cosmetics_shop"], 1)


def test_nonmetric_and_continuation_contract_cannot_authorize_new_query():
    candidate = {"outcome": "query", "recipe": "revenue", "metrics": [], "selection": [], "filters": [],
                 "intent_contract": _contract("non_metric", [], "", "")}
    assert intent.mismatch(candidate, CAT) == "non_metric_query"
    candidate["intent_contract"] = _contract("continuation", [], "", "")
    candidate["dialogue"] = {"relation": "new_topic", "target_id": ""}
    assert intent.mismatch(candidate, CAT) == "unbound_continuation"


def test_presentation_arithmetic_preserves_catalog_measure_and_grain():
    candidate = {"outcome": "query", "recipe": "revenue", "metrics": [], "selection": [], "filters": [],
                 "answer_request": {"ask": "Compare this period with the previous one"},
                 "intent_contract": _contract("presentation_arithmetic", ["revenue"],
                                               "presentation_arithmetic", "purchased_item_line_value")}
    assert intent.mismatch(candidate, CAT) is None
    candidate["intent_contract"]["grain"] = "order"
    assert intent.mismatch(candidate, CAT) == "intent_grain_mismatch"


def test_ambiguous_metric_contract_waits_for_user_choice_then_binds_selected_definition():
    candidate = {"outcome": "query", "recipe": "", "metrics": [], "recipe_alternatives": ["users", "viewers"],
                 "selection": [], "filters": [], "source_ids": ["cosmetics_shop"],
                 "intent_contract": _contract("ambiguous_metric", ["users", "viewers"], "", "",
                                               sources=["cosmetics_shop"])}
    assert intent.mismatch(candidate, CAT) is None
    candidate["recipe"] = "users"
    candidate = intent.resolve_ambiguous_contract(candidate, "users", CAT)
    assert candidate["intent_contract"]["metric_ids"] == ["users"]
    assert candidate["intent_contract"]["operation"] == "count_users"
    assert intent.mismatch(candidate, CAT) is None
