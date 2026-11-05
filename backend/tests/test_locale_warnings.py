from pathlib import Path

import yaml

from texa import catalog, pipeline
from texa.answer import _render_warning
from texa.sanity import check_availability
from texa.spec import validate_spec


ROOT = Path(__file__).resolve().parents[2]


def setup_scope():
    cat = catalog.validate_catalog(yaml.safe_load((ROOT / "catalog/product_events.yaml").read_text()))
    cat.contract_version = 1
    # The product permits one source; widen this unit fixture only so all three
    # cross-source availability warnings can be exercised in one QuerySpec.
    cat.policy.max_sources = 2
    sources = {
        "cosmetics_shop": catalog.Source(
            id="cosmetics_shop", label="Cosmetics shop", description="", currency="USD",
            min_date="2020-01-01", max_date="2020-01-02", row_count=10, user_count=5,
            events={"purchase", "order_purchased"}, columns={"revenue", "item_category"}),
        "olist_marketplace": catalog.Source(
            id="olist_marketplace", label="Olist", description="", currency="BRL",
            min_date="2020-01-01", max_date="2020-01-02", row_count=10, user_count=5,
            events={"order_purchased"}, columns={"revenue"}),
    }
    return cat, sources


def test_availability_warnings_have_typed_codes_and_keep_legacy_messages():
    cat, sources = setup_scope()
    raw = {"source_ids": list(sources), "contract_version": cat.contract_version,
           "shape": "breakdown", "selection": ["item_category"], "recipe": "revenue",
           "time_range": {"kind": "all"}}
    spec = validate_spec(raw, cat, sources)
    av = check_availability(spec, cat, sources)
    by_code = {warning["code"]: warning for warning in av.warning_details}
    assert set(by_code) == {"availability_missing_fields", "availability_duplicate_event_role", "availability_mixed_currencies"}
    assert len(av.warnings) == len(av.warning_details) == 3
    assert by_code["availability_missing_fields"]["params"]["field_ids"] == ["item_category"]
    assert by_code["availability_duplicate_event_role"]["params"]["event_names"] == ["purchase", "order_purchased"]
    assert by_code["availability_mixed_currencies"]["params"]["source_currencies"] == {
        "cosmetics_shop": "USD", "olist_marketplace": "BRL"}


def test_localized_warnings_translate_labels_not_ids_or_raw_values():
    cat, sources = setup_scope()
    missing = {"code": "availability_missing_fields",
               "message": "Olist does not record Product category; its rows show it as empty.",
               "params": {"source_id": "olist_marketplace", "field_ids": ["item_category"]}}
    message_vi = _render_warning(missing, cat, sources, "vi")
    assert "Danh mục sản phẩm" in message_vi
    assert "item_category" not in message_vi
    assert "không" in message_vi
    assert _render_warning(missing, cat, sources, "en") == missing["message"]

    duplicate = {"code": "availability_duplicate_event_role", "message": "old English warning",
                 "params": {"source_id": "cosmetics_shop", "role_id": "purchase",
                            "event_names": ["purchase", "order_purchased"]}}
    message_vi = _render_warning(duplicate, cat, sources, "vi")
    assert "purchase" in message_vi and "order_purchased" in message_vi
    assert "loại sự kiện" in message_vi
    assert _render_warning(duplicate, cat, sources, "en") == duplicate["message"]

    currencies = {"code": "availability_mixed_currencies", "message": "old English currency warning",
                  "params": {"source_currencies": {"cosmetics_shop": "USD", "olist_marketplace": "BRL"}}}
    message_vi = _render_warning(currencies, cat, sources, "vi")
    assert "USD" in message_vi and "BRL" in message_vi
    assert "chưa được quy đổi" in message_vi
    assert _render_warning(currencies, cat, sources, "en") == currencies["message"]


def test_pipeline_carries_availability_warning_details(monkeypatch):
    cat, sources = setup_scope()
    raw = {"source_ids": list(sources), "contract_version": cat.contract_version,
           "shape": "breakdown", "selection": ["item_category"], "recipe": "revenue",
           "time_range": {"kind": "all"}}
    monkeypatch.setattr(pipeline.execute, "display_sql", lambda _: "SELECT scripted")
    monkeypatch.setattr(pipeline.execute, "run", lambda *_: {
        "rows": [{"item_category": "beauty", "revenue": 3.0}], "samples": [],
        "row_count": 1, "partial": False, "ms": 0})
    out = pipeline.run_spec(raw, cat, sources)
    assert {warning["code"] for warning in out["warning_details"]} >= {
        "availability_missing_fields", "availability_duplicate_event_role", "availability_mixed_currencies"}
    assert out["warnings"][:3] == [warning["message"] for warning in out["warning_details"][:3]]
