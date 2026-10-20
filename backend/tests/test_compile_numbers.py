"""Compiler numbers vs hand-written SQL on the loaded warehouse (skipped when the warehouse is empty)."""
import pytest

from texa import catalog, db
from texa.pipeline import run_spec
from texa.spec import SpecError


def _warehouse_ready():
    try:
        return set(catalog.load_sources(max_age=0)) >= {"cosmetics_shop", "olist_marketplace"}
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _warehouse_ready(), reason="warehouse not loaded")


def hand(query, params=None):
    with db.reader_conn() as conn:
        return conn.execute(query, params).fetchall()


def one(spec):
    return run_spec(spec)["rows"]


def approx(a, b):
    return a == pytest.approx(b, rel=1e-9, abs=1e-9)


ALL = {"kind": "all"}
OLIST = ["olist_marketplace"]
COSM = ["cosmetics_shop"]


def test_revenue_by_month_cosmetics():
    rows = one({"source_ids": COSM, "shape": "time_trend", "selection": ["event_month"], "recipe": "revenue", "time_range": ALL})
    expected = hand("""SELECT date_trunc('month', event_date)::date m, sum(revenue) r FROM analytics.event_activity
                       WHERE source_id='cosmetics_shop' AND event_name='purchase' GROUP BY 1 ORDER BY 1""")
    assert [r["event_month"] for r in rows] == [e["m"].isoformat() for e in expected]
    assert all(approx(r["revenue"], float(e["r"])) for r, e in zip(rows, expected))


def test_orders_map_to_sessions_for_cosmetics():
    rows = one({"source_ids": COSM, "shape": "aggregate", "recipe": "orders", "time_range": ALL})
    expected = hand("SELECT count(DISTINCT session_id) n FROM analytics.event_activity WHERE source_id='cosmetics_shop' AND event_name='purchase'")
    assert rows[0]["orders"] == expected[0]["n"]


def test_cart_to_purchase_rate():
    rows = one({"source_ids": COSM, "shape": "aggregate", "recipe": "cart_to_purchase_rate", "time_range": ALL})
    e = hand("""SELECT count(DISTINCT user_id) FILTER (WHERE event_name='purchase')::numeric
                     / count(DISTINCT user_id) FILTER (WHERE event_name='cart') r
                FROM analytics.event_activity WHERE source_id='cosmetics_shop'""")[0]
    assert approx(rows[0]["cart_to_purchase_rate"], float(e["r"]))


def test_cancel_and_late_delivery_rates():
    rows = one({"source_ids": OLIST, "shape": "aggregate", "metrics": ["cancel_rate", "late_delivery_rate"], "time_range": ALL})
    e = hand("""SELECT
        count(DISTINCT ep->>'order_id') FILTER (WHERE event_name='order_canceled')::numeric
          / count(DISTINCT ep->>'order_id') FILTER (WHERE event_name='order_purchased') cancel,
        count(DISTINCT ep->>'order_id') FILTER (WHERE event_name='order_delivered' AND ep->>'is_late'='true')::numeric
          / count(DISTINCT ep->>'order_id') FILTER (WHERE event_name='order_delivered') late
        FROM analytics.event_activity WHERE source_id='olist_marketplace'""")[0]
    assert approx(rows[0]["cancel_rate"], float(e["cancel"]))
    assert approx(rows[0]["late_delivery_rate"], float(e["late"]))


def test_review_score_by_state_filtered():
    rows = one({"source_ids": OLIST, "shape": "breakdown", "selection": ["region"], "recipe": "avg_review_score",
                "filters": [{"field": "region", "operator": "IN", "values": ["SP", "RJ"]}], "time_range": ALL})
    e = {r["region"]: float(r["s"]) for r in hand("""SELECT region, avg((ep->>'review_score')::numeric) s FROM analytics.event_activity
           WHERE source_id='olist_marketplace' AND event_name='review_submitted' AND region IN ('SP','RJ') GROUP BY 1""")}
    assert {r["region"] for r in rows} == {"SP", "RJ"}
    assert all(approx(r["avg_review_score"], e[r["region"]]) for r in rows)


def test_last_n_days_ends_at_latest_data_day():
    rows = one({"source_ids": COSM, "shape": "aggregate", "recipe": "buyers", "time_range": {"kind": "last_n_days", "days": 7}})
    e = hand("""SELECT count(DISTINCT user_id) n FROM analytics.event_activity e WHERE source_id='cosmetics_shop' AND event_name='purchase'
                AND event_date > (SELECT max_date FROM analytics.source_registry WHERE source_id='cosmetics_shop') - 7""")[0]
    assert rows[0]["buyers"] == e["n"] > 0


def test_avg_daily_users():
    rows = one({"source_ids": OLIST, "shape": "aggregate", "recipe": "avg_daily_users",
                "time_range": {"kind": "between", "start": "2018-01-01", "end": "2018-01-31"}})
    e = hand("""SELECT avg(n) a FROM (SELECT event_date, count(DISTINCT user_id) n FROM analytics.event_activity
                WHERE source_id='olist_marketplace' AND event_date BETWEEN '2018-01-01' AND '2018-01-31' GROUP BY 1) d""")[0]
    assert approx(rows[0]["avg_daily_users"], float(e["a"]))


def test_retention_d7_excludes_incomplete_cohorts():
    rows = one({"source_ids": COSM, "shape": "aggregate", "recipe": "retention_d7", "time_range": ALL})
    e = hand("""WITH c AS (SELECT DISTINCT user_id FROM analytics.event_activity WHERE source_id='cosmetics_shop'
                  AND first_seen_date <= (SELECT max_date FROM analytics.source_registry WHERE source_id='cosmetics_shop') - 7),
                r AS (SELECT DISTINCT user_id FROM analytics.event_activity WHERE source_id='cosmetics_shop'
                  AND event_date - first_seen_date BETWEEN 1 AND 7)
                SELECT count(r.user_id)::numeric / count(*) v FROM c LEFT JOIN r USING (user_id)""")[0]
    assert approx(rows[0]["retention_d7"], float(e["v"]))


def test_two_sources_add_store_breakdown_and_keep_nulls():
    out = run_spec({"source_ids": COSM + OLIST, "shape": "aggregate", "metrics": ["revenue", "add_to_carts"], "time_range": ALL})
    by_source = {r["source"]: r for r in out["rows"]}
    assert set(by_source) == {"cosmetics_shop", "olist_marketplace"}
    assert by_source["olist_marketplace"]["add_to_carts"] is None  # not 0: Olist never logs carts
    assert by_source["cosmetics_shop"]["add_to_carts"] > 0
    assert "add_to_carts" in out["unavailable_metrics"]
    assert any("currencies" in w for w in out["warnings"])


def test_refuses_metric_the_store_never_logs():
    with pytest.raises(SpecError) as e:
        run_spec({"source_ids": OLIST, "shape": "aggregate", "recipe": "add_to_carts", "time_range": ALL})
    assert e.value.code == "not_tracked"


def test_price_range_buckets_are_ordered():
    rows = one({"source_ids": COSM, "shape": "breakdown", "selection": ["price_range"], "recipe": "purchases", "time_range": ALL})
    labels = [r["price_range"] for r in rows if r["price_range"]]
    assert labels[0].startswith("<") and labels[-1].startswith("≥")
    total = hand("SELECT count(*) n FROM analytics.event_activity WHERE source_id='cosmetics_shop' AND event_name='purchase'")[0]["n"]
    assert sum(r["purchases"] for r in rows) == total


def test_distinct_events():
    rows = one({"source_ids": OLIST, "shape": "distinct_values", "selection": ["event_name"], "time_range": ALL})
    assert {r["event_name"] for r in rows} == catalog.load_sources()["olist_marketplace"].events
