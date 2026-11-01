"""Clarification behavior without a model or database."""
from copy import deepcopy

import pytest

from texa import clarify
from texa.spec import SpecError, validate_spec
from tests.test_flow import candidate
from tests.test_units import CAT, SOURCES


def test_ambiguous_variants_are_asked_even_in_the_same_group():
    c = candidate(recipe_alternatives=["buyer_conversion_rate", "view_to_purchase_rate"],
                  source_ids=["cosmetics_shop"], time_range={"kind": "all"})
    out = clarify.advance(c, {}, CAT, SOURCES)
    assert out.kind == "clarify"
    assert {ch["id"] for f in out.form["fields"] if f["id"] == "recipe" for ch in f["choices"]} == set(c["recipe_alternatives"])


def test_model_default_does_not_silence_unstated_metric_ambiguity():
    c = candidate(recipe="buyers", recipe_alternatives=["purchases"], source_ids=["cosmetics_shop"],
                  time_range={"kind": "all"})
    out = clarify.advance(c, {}, CAT, SOURCES)
    assert out.kind == "clarify"
    resolved = clarify.advance(c, {"recipe": ["purchases"]}, CAT, SOURCES)
    assert resolved.kind == "spec" and resolved.spec["recipe"] == "purchases"


def test_single_dataset_policy_does_not_offer_compare_all():
    cat = deepcopy(CAT)
    cat.policy.max_sources = 1
    out = clarify.advance(candidate(recipe="users", time_range={"kind": "all"}), {}, cat, SOURCES)
    assert all(ch["id"] != "__all__" for f in out.form["fields"] for ch in f["choices"])


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_filter_values_are_rejected(value):
    raw = {"source_ids": ["cosmetics_shop"], "contract_version": 1, "shape": "aggregate", "recipe": "users",
           "time_range": {"kind": "all"}, "filters": [{"field": "review_score", "operator": ">", "values": [value]}]}
    with pytest.raises(SpecError, match="needs numbers"):
        validate_spec(raw, CAT, SOURCES)
