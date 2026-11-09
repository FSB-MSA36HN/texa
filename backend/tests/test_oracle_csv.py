"""Tests for the independent raw-CSV oracle behind the research_v4 gold.

Part 1 hand-computes expected answers on a tiny landing directory written here (definitions in
data/benchmark/research_v4/GLOSSARY.md). Part 2 checks metamorphic relations on the real CSV files, and
Part 3 re-checks the structural gates of the frozen research_v4 dataset. Parts 2 and 3 skip when the CSV
files are not on this machine.
"""
from pathlib import Path

import pytest
import yaml

duckdb = pytest.importorskip("duckdb")

from eval.oracle_csv import DEFAULT_LANDING, OracleError, RawOracle  # noqa: E402
from eval.validate_research_v4 import structural_errors  # noqa: E402

V4 = Path(__file__).resolve().parents[2] / "data" / "benchmark" / "research_v4"


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    root = tmp_path_factory.mktemp("landing")
    write(root / "cosmetics_shop/2020-Jan.csv", """
event_time,event_type,product_id,category_id,category_code,brand,price,user_id,user_session
2020-01-01 10:00:00 UTC,view,1,10,skin.cream,b,5.0,u1,s1
2020-01-01 10:00:00 UTC,view,1,10,skin.cream,b,5.0,u1,s1
2020-01-01 11:00:00 UTC,purchase,1,10,skin.cream,b,10.0,u1,s1
2020-01-02 09:00:00 UTC,purchase,2,11,,b,0,u2,s2
2020-01-02 09:30:00 UTC,cart,2,11,hair.oil,b,7.5,u2,s2
2020-01-02 09:31:00 UTC,view,2,11,hair.oil,b,7.5,,s3
""")
    o = root / "olist_marketplace"
    write(o / "olist_customers_dataset.csv", """
"customer_id","customer_unique_id","customer_zip_code_prefix","customer_city","customer_state"
c1,U1,100,sp,SP
c2,U2,200,rio,RJ
""")
    write(o / "olist_orders_dataset.csv", """
"order_id","customer_id","order_status","order_purchase_timestamp","order_approved_at","order_delivered_carrier_date","order_delivered_customer_date","order_estimated_delivery_date"
o1,c1,delivered,2018-01-01 10:00:00,2018-01-01 11:00:00,2018-01-03 09:00:00,2018-01-06 09:00:00,2018-01-10 00:00:00
o2,c2,canceled,2018-01-02 09:00:00,,,,2018-01-12 00:00:00
""")
    write(o / "olist_order_items_dataset.csv", """
"order_id","order_item_id","product_id","seller_id","shipping_limit_date","price","freight_value"
o1,1,p1,s1,2018-01-02 00:00:00,100.00,10.00
o1,2,p2,s1,2018-01-02 00:00:00,50.00,10.00
o2,1,p1,s1,2018-01-03 00:00:00,30.00,5.00
""")
    write(o / "olist_order_payments_dataset.csv", """
order_id,payment_sequential,payment_type,payment_installments,payment_value
o1,1,credit_card,1,150.00
o2,1,boleto,1,30.00
""")
    write(o / "olist_order_reviews_dataset.csv", """
"review_id","order_id","review_score","review_comment_title","review_comment_message","review_creation_date","review_answer_timestamp"
r1,o1,5,,,2018-01-08 00:00:00,2018-01-08 10:00:00
""")
    write(o / "olist_products_dataset.csv", """
"product_id","product_category_name","product_name_lenght"
p1,beleza_saude,10
p2,sem_traducao,10
""")
    (o / "product_category_name_translation.csv").write_bytes(
        "﻿product_category_name,product_category_name_english\nbeleza_saude,health_beauty\n".encode("utf-8"))
    return RawOracle(root)


def value(oracle, source, metric, where=(), **kw):
    result = oracle.evaluate(source, metric, list(where), **kw)
    return result["rows"][0][0] if "group" not in kw else result["rows"]


def test_cosmetics_drops_duplicates_and_rows_without_user_and_ignores_zero_price(tiny):
    c = "cosmetics_shop"
    assert value(tiny, c, "events") == 4           # 6 raw rows - 1 exact duplicate - 1 without user
    assert value(tiny, c, "users") == 2
    assert value(tiny, c, "sessions") == 2
    assert value(tiny, c, "viewers") == 1
    assert value(tiny, c, "purchases") == 2
    assert value(tiny, c, "buyers") == 2
    assert value(tiny, c, "revenue") == 10         # the 0-price purchase counts as a purchase, not as revenue
    assert value(tiny, c, "buyer_conversion_rate") == 1.0


def test_cosmetics_category_is_first_segment_and_missing_is_a_group(tiny):
    rows = value(tiny, "cosmetics_shop", "events", group="item_category")
    assert rows == [["hair", 1], ["skin", 2], [None, 1]]       # NULL group sorts last


def test_olist_event_counts_follow_the_lifecycle_rules(tiny):
    o = "olist_marketplace"
    assert value(tiny, o, "events") == 10          # 3 items + approved + shipped + delivered + canceled + 2 payments + review
    assert value(tiny, o, "purchases") == 3        # item lines, not orders
    assert value(tiny, o, "users") == 2 and value(tiny, o, "buyers") == 2
    assert value(tiny, o, "revenue") == 180        # item prices only: payment values and freight excluded
    breakdown = value(tiny, o, "events", group="event_name")
    assert dict((n, c) for n, c in breakdown) == {
        "order_approved": 1, "order_canceled": 1, "order_delivered": 1, "order_purchased": 3,
        "order_shipped": 1, "payment_made": 2, "review_submitted": 1}


def test_olist_canceled_and_payments_are_dated_at_purchase_and_lifecycle_has_no_category(tiny):
    o = "olist_marketplace"
    day2 = [{"event_date": "2018-01-02"}]
    assert dict(value(tiny, o, "events", day2, group="event_name"))["order_canceled"] == 1
    assert dict(value(tiny, o, "events", day2, group="event_name"))["payment_made"] == 1
    assert value(tiny, o, "events", [{"item_category": {"is_null": True}}]) == 7   # everything but the 3 item rows
    assert dict(value(tiny, o, "purchases", group="item_category")) == {"health_beauty": 2, "sem_traducao": 1}
    assert dict(value(tiny, o, "revenue", group="item_category")) == {"health_beauty": 130, "sem_traducao": 50}


def test_olist_conversion_denominator_includes_non_purchase_events(tiny):
    window = [{"event_date": {"between": ["2018-01-03", "2018-01-08"]}}]
    assert value(tiny, "olist_marketplace", "users", window) == 1       # only shipped/delivered/review rows
    assert value(tiny, "olist_marketplace", "buyer_conversion_rate", window) == 0.0
    assert value(tiny, "olist_marketplace", "buyer_conversion_rate", [{"event_date": "2030-01-01"}]) is None


def test_top_k_orders_by_metric_then_group_with_null_last(tiny):
    rows = value(tiny, "cosmetics_shop", "events", group="item_category", limit=2, order_by="metric_desc")
    assert rows == [["skin", 2], ["hair", 1]]


def test_unsupported_metric_or_field_is_rejected(tiny):
    with pytest.raises(OracleError):
        tiny.evaluate("olist_marketplace", "sessions")
    with pytest.raises(OracleError):
        tiny.evaluate("cosmetics_shop", "events", [{"device_type": "mobile"}])


# --------------------------------------------------------------- real data
needs_csv = pytest.mark.skipif(not (DEFAULT_LANDING / "olist_marketplace").is_dir(), reason="data/landing is not present")


@pytest.fixture(scope="module")
def real():
    return RawOracle()


@needs_csv
@pytest.mark.parametrize("source,lo,mid,hi", [("cosmetics_shop", "2019-12-05", "2019-12-20", "2020-01-10"),
                                               ("olist_marketplace", "2017-03-01", "2017-06-15", "2017-09-30")])
def test_additive_metrics_split_across_adjacent_windows(real, source, lo, mid, hi):
    from datetime import date, timedelta
    after_mid = (date.fromisoformat(mid) + timedelta(days=1)).isoformat()
    for metric in ("events", "purchases", "revenue"):
        whole = value(real, source, metric, [{"event_date": {"between": [lo, hi]}}])
        left = value(real, source, metric, [{"event_date": {"between": [lo, mid]}}])
        right = value(real, source, metric, [{"event_date": {"between": [after_mid, hi]}}])
        assert whole == pytest.approx(left + right)


@needs_csv
@pytest.mark.parametrize("source", ["cosmetics_shop", "olist_marketplace"])
def test_additive_metrics_equal_the_sum_of_their_breakdowns(real, source):
    window = [{"event_date": {"between": ["2019-12-05" if source == "cosmetics_shop" else "2017-03-01",
                                           "2019-12-25" if source == "cosmetics_shop" else "2017-03-31"]}}]
    for metric in ("events", "purchases", "revenue"):
        total = value(real, source, metric, window)
        for group in ("event_date", "item_category", "event_name"):
            parts = real.evaluate(source, metric, window, group=group)["rows"]
            assert sum(r[1] for r in parts) == pytest.approx(total), (metric, group)


@needs_csv
@pytest.mark.parametrize("source", ["cosmetics_shop", "olist_marketplace"])
def test_ordering_and_bounds_between_metrics(real, source):
    window = [{"event_date": {"between": ["2019-12-05" if source == "cosmetics_shop" else "2017-03-01",
                                           "2020-01-05" if source == "cosmetics_shop" else "2017-05-31"]}}]
    events, users = value(real, source, "events", window), value(real, source, "users", window)
    purchases, buyers = value(real, source, "purchases", window), value(real, source, "buyers", window)
    assert buyers <= purchases <= events and buyers <= users <= events
    assert value(real, source, "buyer_conversion_rate", window) == pytest.approx(buyers / users)
    narrower = window + [{"event_name": real.values(source, "event_name")[0]}]
    assert value(real, source, "events", narrower) <= events        # a filter yields a subset


@needs_csv
def test_oracle_matches_published_olist_row_counts(real):
    # Olist ships 112,650 order items; every item has an order and a customer.
    assert value(real, "olist_marketplace", "purchases") == 112650


# --------------------------------------------------------- frozen dataset
needs_v4 = pytest.mark.skipif(not (V4 / "cases.yaml").is_file(), reason="research_v4 has not been generated")


@needs_v4
def test_v4_structure_gates_hold():
    cases = yaml.safe_load((V4 / "cases.yaml").read_text(encoding="utf-8"))
    assert structural_errors(cases) == []
    assert {c["split"] for c in cases} == {"dev", "test"}


@needs_v4
def test_v4_ids_and_alternatives_are_recorded_for_every_case():
    cases = yaml.safe_load((V4 / "cases.yaml").read_text(encoding="utf-8"))
    assert all(c["distinguished_from"] == ["all_time", "sibling_metric"] for c in cases)
    assert all(c["oracle"] == "raw_csv_duckdb" for c in cases)


@needs_v4
def test_v4_stored_answers_still_equal_a_fresh_oracle_run():
    from eval.benchmark import results_equal
    oracle = RawOracle()
    cases = yaml.safe_load((V4 / "cases.yaml").read_text(encoding="utf-8"))
    for case in cases:
        spec = case["spec"]
        fresh = oracle.evaluate(case["source_id"], case["metric"], spec["where"], spec["group"], spec["limit"], spec["order_by"])
        expected = case["expected_result"]
        assert results_equal(fresh["columns"], fresh["rows"], expected["columns"], expected["rows"], ordered=case["ordered"]), case["id"]
