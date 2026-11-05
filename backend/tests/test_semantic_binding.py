from pathlib import Path

import pytest
import yaml

from texa.catalog import Catalog, SemanticValue, Source, mentioned_sources, validate_catalog
from texa.sanity import match_values
from texa.spec import SpecError, validate_spec


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cat():
    raw = yaml.safe_load((ROOT / "catalog/product_events.yaml").read_text())
    return validate_catalog(raw)


def source(source_id, events, values=None, complete=()):
    return Source(id=source_id, label=source_id, description="fixture", currency="USD",
                  min_date="2020-01-01", max_date="2020-01-02", row_count=2, user_count=2,
                  events=set(events), columns={"event_name", "revenue", "item_category"},
                  values=values or {}, value_vocab_fields=set(complete))


def test_semantic_display_label_binds_to_source_specific_physical_event(cat):
    cosmetics = source("cosmetics_shop", ["purchase"])
    olist = source("olist_marketplace", ["order_purchased"])
    assert match_values(cat, "event_name", ["MUA HÀNG"], [cosmetics]) == (["purchase"], {})
    assert match_values(cat, "event_name", ["mua hàng"], [olist]) == (["order_purchased"], {})


def test_closed_vocabulary_rejects_unknown_but_open_field_passes_literal(cat):
    closed = source("cosmetics_shop", ["purchase", "view"],
                    values={"item_category": {"makeup": "Makeup", "skin": "Skin"}},
                    complete={"item_category"})
    open_source = source("cosmetics_shop", ["purchase"])
    assert match_values(cat, "item_category", ["not-a-category"], [closed])[1]
    assert match_values(cat, "item_category", ["SKU-324"], [open_source]) == (["SKU-324"], {})


def test_spec_entrypoint_binds_alias_and_rejects_unknown_closed_event(cat):
    src = source("olist_marketplace", ["order_purchased", "order_delivered"])
    raw = {"source_ids": [src.id], "contract_version": cat.contract_version, "shape": "aggregate",
           "recipe": "revenue", "time_range": {"kind": "all"},
           "filters": [{"field": "event_name", "operator": "=", "values": ["mua hàng"]}]}
    spec = validate_spec(raw, cat, {src.id: src})
    assert spec.filters[0].values == ["order_purchased"]

    raw["filters"][0]["values"] = ["localized-but-unmapped-event"]
    with pytest.raises(SpecError) as err:
        validate_spec(raw, cat, {src.id: src})
    assert err.value.code == "value_not_found"
    assert err.value.params["source_ids"] == [src.id]


def test_source_profiles_hide_evaluation_fixture_by_default(cat, monkeypatch):
    monkeypatch.delenv("TEXA_SOURCE_PROFILE", raising=False)
    assert cat.sources_for_profile() == ["cosmetics_shop", "olist_marketplace"]
    monkeypatch.setenv("TEXA_SOURCE_PROFILE", "evaluation")
    assert cat.sources_for_profile() == ["cosmetics_shop", "olist_marketplace", "event_benchmark"]


def test_source_mention_binder_matches_catalog_aliases_and_returns_all_matches(cat):
    cosmetics = source("cosmetics_shop", ["purchase"])
    cosmetics.label = "Cosmetics shop"
    olist = source("olist_marketplace", ["order_purchased"])
    olist.label = "Olist marketplace"
    sources = {cosmetics.id: cosmetics, olist.id: olist}
    assert mentioned_sources(cat, sources, "Doanh thu ở CỬA HÀNG MỸ PHẨM") == ["cosmetics_shop"]
    assert mentioned_sources(cat, sources, "So sánh cosmetics và Olist") == ["cosmetics_shop", "olist_marketplace"]
    # Negation is deliberately not guessed: caller must ask if it changes the source set.
    assert mentioned_sources(cat, sources, "Không dùng Olist") == ["olist_marketplace"]


def test_exact_alias_expanding_to_multiple_physical_values_uses_in_operator(cat):
    cat.semantic_values.append(SemanticValue(id="purchase_alias_test", field="event_name", label="purchase action",
                                             synonyms=["mua theo nhiều loại"],
                                             source_values={"cosmetics_shop": ["purchase", "order_purchased"]}))
    src = source("cosmetics_shop", ["purchase", "order_purchased"])
    raw = {"source_ids": [src.id], "contract_version": cat.contract_version, "shape": "aggregate",
           "recipe": "revenue", "time_range": {"kind": "all"},
           "filters": [{"field": "event_name", "operator": "=", "values": ["mua theo nhiều loại"]}]}
    spec = validate_spec(raw, cat, {src.id: src})
    assert spec.filters[0].operator == "IN"
    assert set(spec.filters[0].values) == {"purchase", "order_purchased"}


def test_contains_filter_is_not_rewritten_to_closed_enum(cat):
    src = source("cosmetics_shop", ["purchase"],
                 values={"item_category": {"beauty": "Beauty", "skin": "Skin"}},
                 complete={"item_category"})
    raw = {"source_ids": [src.id], "contract_version": cat.contract_version, "shape": "aggregate",
           "recipe": "revenue", "time_range": {"kind": "all"},
           "filters": [{"field": "item_category", "operator": "CONTAINS", "values": ["bea"]}]}
    spec = validate_spec(raw, cat, {src.id: src})
    assert spec.filters[0].values == ["bea"]


def test_catalog_policy_for_ambiguous_phrase_overrides_model_default(cat):
    from texa import clarify
    from tests.test_flow import candidate

    src = source("cosmetics_shop", ["purchase"])
    c = candidate(recipe="revenue", recipe_stated=True, source_ids=[src.id], time_range={"kind": "all"})
    out = clarify.advance(c, {}, cat, {src.id: src}, question="sales")
    assert out.kind == "clarify"
    assert {choice["id"] for field in out.form["fields"] if field["id"] == "recipe"
            for choice in field["choices"]} == {"revenue", "purchases"}
    answered = clarify.advance(c, {}, cat, {src.id: src}, question="sales revenue")
    assert answered.kind == "spec" and answered.spec["recipe"] == "revenue"


def test_clarification_preserves_contains_substring(cat):
    from texa import clarify
    from tests.test_flow import candidate
    src = source('cosmetics_shop', ['purchase'], values={'item_category': {'beauty': 'Beauty'}}, complete={'item_category'})
    c = candidate(recipe='revenue', source_ids=[src.id], time_range={'kind': 'all'},
                  filters=[{'field': 'item_category', 'operator': 'CONTAINS', 'values_mentioned': ['bea']}])
    out = clarify.advance(c, {}, cat, {src.id: src})
    assert out.kind == 'spec'
    assert out.spec['filters'] == [{'field': 'item_category', 'operator': 'CONTAINS', 'values': ['bea']}]


def test_publish_checks_only_installed_sources_in_active_profile(cat):
    from texa.catalog import check_against_sources
    cosmetics = source('cosmetics_shop', ['purchase', 'view'])
    # A demo must not require installation of the isolated evaluation fixture.
    assert check_against_sources(cat, {cosmetics.id: cosmetics}) == []
