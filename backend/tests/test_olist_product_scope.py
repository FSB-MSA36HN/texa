"""Mocked contract tests for the Olist product catalog; no database is required."""
from pathlib import Path
import os

import pytest
import yaml

from texa import catalog, db, pipeline, interpret
from texa.compile import compile_spec
from texa.sanity import check_availability
from texa.spec import SpecError, validate_spec


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def product():
    raw = yaml.safe_load((ROOT / "catalog" / "product_events.yaml").read_text())
    cat = catalog.validate_catalog(raw)
    events = {"order_purchased", "order_approved", "order_shipped", "order_delivered",
              "order_canceled", "payment_made", "review_submitted"}
    src = catalog.Source(id="olist_marketplace", label="Olist", description="", currency="BRL",
                         min_date="2025-01-01", max_date="2025-01-03", row_count=7, user_count=2,
                         events=events, columns={"revenue"})
    return cat, {src.id: src}


def _spec(cat, source="olist_marketplace", metric="users"):
    return {"source_ids": [source], "contract_version": cat.contract_version, "shape": "aggregate",
            "recipe": metric, "time_range": {"kind": "all"}}


def test_product_allowlist_and_one_source_scope(product):
    cat, sources = product
    assert "olist_marketplace" in cat.allowed_sources
    any_event = next(role for role in cat.event_roles if role.id == "any_event")
    assert sources["olist_marketplace"].events <= set(any_event.events)
    assert catalog.scoped_sources(cat, {**sources, "not_allowed": sources["olist_marketplace"]}).keys() == sources.keys()
    assert cat.policy.max_sources == 1
    spec = _spec(cat)
    spec["source_ids"] = ["olist_marketplace", "cosmetics_shop"]
    with pytest.raises(SpecError, match="at most 1 dataset"):
        validate_spec(spec, cat, sources)


def test_olist_coverage_and_purchase_sql_excludes_payment(product):
    cat, sources = product
    coverage = catalog.coverage(cat, sources)["olist_marketplace"]
    assert set(coverage["metrics_ok"]) == {"users", "events", "purchases", "buyers", "buyer_conversion_rate", "revenue"}
    assert {"sessions", "viewers"} <= set(coverage["metrics_missing"])
    for metric in ("revenue", "purchases"):
        spec = validate_spec(_spec(cat, metric=metric), cat, sources)
        av = check_availability(spec, cat, sources)
        compiled = compile_spec(spec, cat, av)
        query = compiled.query.as_string(None)
        role_events = [value for value in compiled.params.values() if isinstance(value, list)]
        assert any("order_purchased" in values and "purchase" in values for values in role_events)
        assert all("payment_made" not in values for values in role_events)
        assert "event_name = ANY" in query


def test_unrelated_delivery_event_does_not_satisfy_purchase(product):
    cat, sources = product
    sources["olist_marketplace"].events = {"order_delivered"}
    spec = validate_spec(_spec(cat, metric="revenue"), cat, sources)
    with pytest.raises(SpecError, match="cannot be answered"):
        check_availability(spec, cat, sources)


def test_source_limitations_reach_prompt_and_results(product, monkeypatch):
    cat, sources = product
    assert "SOURCE LIMITATIONS" in interpret.render_catalog(cat, sources)
    monkeypatch.setattr(pipeline.execute, "display_sql", lambda _: "SELECT scripted")
    monkeypatch.setattr(pipeline.execute, "run", lambda *_: {
        "rows": [{"buyer_conversion_rate": 1.0}], "samples": [], "row_count": 1,
        "partial": False, "ms": 0})
    out = pipeline.run_spec(_spec(cat, metric="buyer_conversion_rate"), cat, sources)
    assert any("not visitor conversion" in warning for warning in out["warnings"])
    assert any("không phải tỷ lệ chuyển đổi" in warning["params"].get("localized", {}).get("vi", "")
               for warning in out["warning_details"])
    for metric in ("sessions", "viewers"):
        with pytest.raises(SpecError, match="cannot be answered"):
            check_availability(validate_spec(_spec(cat, metric=metric), cat, sources), cat, sources)
    with pytest.raises(SpecError):
        validate_spec(_spec(cat, metric="late_delivery_rate"), cat, sources)


@pytest.mark.skipif(not os.getenv("TEXA_PRODUCT_TEST_DSN"), reason="isolated product fixture DB not configured")
def test_olist_item_revenue_and_counts_on_postgresql(product):
    cat, sources = product
    # Writes are rolled back, including the registry row needed by compiled SQL.
    # Refuse real warehouses before entering the write transaction.
    for dsn in (db.DB_DSN, db.READER_DSN):
        assert dsn.endswith("/texa_benchmark")
    with db.app_conn() as conn:
        with conn.transaction(force_rollback=True):
            assert conn.execute("SELECT current_database() AS name").fetchone()["name"] == "texa_benchmark"
            assert conn.execute("SELECT 1 FROM analytics.event_activity WHERE source_id='olist_marketplace' LIMIT 1").fetchone() is None
            conn.execute("""INSERT INTO analytics.source_registry
                (source_id,label,description,currency,min_date,max_date,row_count,user_count)
                VALUES ('olist_marketplace','Olist test','','BRL','2025-01-01','2025-01-03',4,2)
                ON CONFLICT (source_id) DO NOTHING""")
            for event_id, event, user, revenue in (
                ('test-item1','order_purchased','buyer',40), ('test-item2','order_purchased','buyer',60),
                ('test-payment','payment_made','buyer',150), ('test-review','review_submitted','reviewer',None)):
                conn.execute("""INSERT INTO analytics.event_activity
                    (event_id,source_id,event_ts,event_date,event_name,user_id,first_seen_date,currency,revenue,ep)
                    VALUES (%s,'olist_marketplace','2025-01-01','2025-01-01',%s,%s,'2025-01-01','BRL',%s,'{"order_id":"one-order"}')""",
                    (event_id,event,user,revenue))
            for metric, expected in {"revenue":100,"purchases":2,"buyers":1,"users":2,"events":4}.items():
                spec = validate_spec(_spec(cat, metric=metric), cat, sources)
                compiled = compile_spec(spec, cat, check_availability(spec, cat, sources))
                row = conn.execute(compiled.query, compiled.params).fetchone()
                assert row[metric] == expected
