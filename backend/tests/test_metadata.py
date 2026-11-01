import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("texa_etl_run", ROOT / "pipeline" / "texa_etl" / "run.py")
etl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(etl)


def test_nested_scalar_paths_are_bounded_and_skip_arrays_objects_null():
    rows = [
        {"device": {"type": "mobile", "attrs": {"os": "ios", "version": "17", "deep": {"x": 1}},
                    "items": ["one"], "empty": None},
         "campaign": {"channel": "search"}, "bad-key": {"ignored": "x"}},
        {"device": {"type": "desktop", "attrs": {"os": "linux"}}},
    ]
    assert etl.nested_scalar_paths(rows) == ["campaign.channel", "device.type"]


def test_nested_path_expression_rejects_unsafe_or_deep_paths():
    for side, path in (("bad", "x"), ("ep", "a.b.c"), ("ep", "x; drop"), ("up", "a[0]")):
        with pytest.raises(ValueError):
            etl._nested_path_expr(side, path)


def test_nested_path_expression_uses_json_literals():
    q = etl._nested_path_expr("ep", "device.type")
    rendered = q.as_string(None)
    assert 'e."ep"' in rendered
    assert "'device'" in rendered and "'type'" in rendered


def test_high_cardinality_nested_leaves_are_suppressed():
    assert etl._high_cardinality("ep.order.order_id")
    assert etl._high_cardinality("up.profile.user_id")
    assert not etl._high_cardinality("ep.device.type")


@pytest.mark.skipif(not os.environ.get("TEXA_METADATA_TEST_DSN"), reason="dedicated metadata integration DSN not configured")
def test_refresh_metadata_persists_nested_path_contract(monkeypatch):
    dsn = os.environ["TEXA_METADATA_TEST_DSN"]
    source_id = "event_benchmark"
    import psycopg
    with psycopg.connect(dsn) as check:
        row = check.execute(
            "SELECT 1 FROM analytics.event_activity WHERE source_id=%s AND ep #> '{device,type}' IS NOT NULL LIMIT 1",
            (source_id,),
        ).fetchone()
    if row is None:
        pytest.skip("dedicated benchmark database has no event_benchmark nested fixture rows")
    etl.SOURCES[source_id] = {"label": "Fixture", "description": "metadata test", "currency": "USD", "events": {"test_event"}}

    conn = psycopg.connect(dsn)
    class BorrowedConnectionContext:
        def __enter__(self):
            return conn

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(etl, "connect", BorrowedConnectionContext)
    try:
        conn.execute("DELETE FROM analytics.vocabulary WHERE source_id=%s AND kind IN ('ep_key','up_key','value')", (source_id,))
        etl.refresh_metadata(source_id)
        rows = conn.execute(
            "SELECT field, value FROM analytics.vocabulary WHERE source_id=%s AND kind='ep_key' ORDER BY value",
            (source_id,),
        ).fetchall()
        parents = conn.execute(
            "SELECT value FROM analytics.vocabulary WHERE source_id=%s AND kind='ep_key' AND value IN ('device','campaign','product','checkout')",
            (source_id,),
        ).fetchall()
    finally:
        conn.rollback()
        conn.close()
    assert rows == [("ep", "campaign.channel"), ("ep", "checkout.amount"),
                    ("ep", "device.type"), ("ep", "product.category")]
    assert parents == []
