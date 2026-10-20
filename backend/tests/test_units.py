"""Pure unit tests: catalog validation, validator rules, facts, insight placeholders, prompt hygiene. No database."""
from pathlib import Path

import pytest
import yaml

from texa import catalog as c
from texa.compile import Column
from texa.facts import compute_facts, format_value, preview_for_model
from texa.insight import render
from texa.prompts import INTERPRET_INSTRUCTION
from texa.spec import SpecError, validate_spec

ROOT = Path(__file__).resolve().parents[2]
RAW = yaml.safe_load((ROOT / "catalog" / "ecommerce.yaml").read_text(encoding="utf-8"))
CAT = c.validate_catalog(RAW)
CAT.contract_version = 1
SOURCES = {
    "cosmetics_shop": c.Source(id="cosmetics_shop", label="Cosmetics shop", description="", currency="USD", min_date="2019-12-01",
                               max_date="2020-01-31", row_count=1, user_count=1, events={"view", "cart", "remove_from_cart", "purchase"}),
    "olist_marketplace": c.Source(id="olist_marketplace", label="Olist", description="", currency="BRL", min_date="2016-09-04",
                                  max_date="2018-10-17", row_count=1, user_count=1, events={"order_purchased", "review_submitted"}),
}


def spec(**over):
    return {"source_ids": ["cosmetics_shop"], "contract_version": 1, "shape": "aggregate", "recipe": "revenue",
            "time_range": {"kind": "all"}} | over


def test_catalog_cross_references_are_checked():
    bad = yaml.safe_load(yaml.safe_dump(RAW))
    bad["metrics"].append({"id": "broken", "label": "x", "unit": "percent", "type": "ratio", "ratio": {"numerator": "nope", "denominator": "aov"}})
    with pytest.raises(ValueError) as e:
        c.validate_catalog(bad)
    assert "unknown metric 'nope'" in str(e.value) and "ratio parts must be simple" in str(e.value)


def test_valid_spec_passes_and_time_field_is_implied():
    s = validate_spec(spec(recipe="retention_d7"), CAT, SOURCES)
    assert s.time_range.field == "first_seen_date"


@pytest.mark.parametrize("over,code", [
    ({"contract_version": 2}, "stale_catalog"),
    ({"source_ids": ["nope"]}, "unknown_source"),
    ({"recipe": "profit"}, "unknown_metric"),
    ({"recipe": "revenue", "metrics": ["aov", "orders"]}, "invalid_spec"),
    ({"recipe": "", "metrics": ["revenue", "aov", "orders", "buyers", "users"]}, "too_many_metrics"),
    ({"shape": "breakdown"}, "invalid_spec"),
    ({"shape": "time_trend", "selection": ["item_category"]}, "invalid_spec"),
    ({"recipe": "", "metrics": ["revenue", "retention_d7"]}, "mixed_periods"),
    ({"shape": "breakdown", "selection": ["item_category"], "recipe": "retention_d7"}, "unsupported_combination"),
    ({"time_range": {"kind": "last_n_days", "days": 400}}, "invalid_time_range"),
    ({"time_range": {"kind": "between", "start": "2019-01-01", "end": "2020-06-01"}}, "invalid_time_range"),
    ({"filters": [{"field": "item_category", "operator": ">", "values": ["a"]}]}, "invalid_filter"),
    ({"filters": [{"field": "review_score", "operator": "=", "values": ["five"]}]}, "invalid_filter"),
    ({"filters": [{"field": "item_brand", "operator": "=", "values": ["a", "b"]}]}, "invalid_filter"),
    ({"bogus": 1}, "invalid_spec"),
])
def test_validator_rejects(over, code):
    with pytest.raises(SpecError) as e:
        validate_spec(spec(**over), CAT, SOURCES)
    assert e.value.code == code


def test_facts_total_only_when_additive_and_complete():
    cols = [Column("item_category", "Category", "dimension"), Column("revenue", "Revenue", "metric", "currency", True, "number"),
            Column("aov", "AOV", "metric", "currency", False, "number")]
    rows = [{"item_category": "a", "revenue": 30.0, "aov": 3.0}, {"item_category": "b", "revenue": 10.0, "aov": 5.0}]
    facts = {f["id"]: f for f in compute_facts(rows, cols, "breakdown", False, {"cosmetics_shop": "USD"})}
    assert facts["f_total_revenue"]["value"] == 40 and facts["f_max_revenue_share"]["value"] == 0.75
    assert "f_total_aov" not in facts and facts["f_max_aov_at"]["value"] == "b"
    partial = {f["id"] for f in compute_facts(rows, cols, "breakdown", True, {"cosmetics_shop": "USD"})}
    assert "f_total_revenue" not in partial


def test_time_trend_change_facts():
    cols = [Column("event_month", "Month", "dimension", value_type="date"), Column("buyers", "Buyers", "metric", "count", False, "number")]
    rows = [{"event_month": "2019-12-01", "buyers": 100}, {"event_month": "2020-01-01", "buyers": 80}]
    facts = {f["id"]: f["value"] for f in compute_facts(rows, cols, "time_trend", False, {})}
    assert facts["f_change_buyers"] == -20 and facts["f_change_buyers_pct"] == pytest.approx(-0.2)


def test_preview_keeps_top_and_others():
    cols = [Column("item_id", "Product", "dimension"), Column("purchases", "P", "metric", "count", True, "number")]
    rows = [{"item_id": str(i), "purchases": i} for i in range(250)]
    preview, grouped = preview_for_model(rows, cols, "breakdown")
    assert grouped and len(preview) == 100 and preview[0]["purchases"] == 249
    assert preview[-1]["item_id"].startswith("Others (151") and preview[-1]["purchases"] == sum(range(151))


def test_insight_placeholders_and_unknown_facts():
    facts = [{"id": "f_total_revenue", "label": "", "value": 1234.5, "unit": "currency", "currency": "USD"},
             {"id": "f_max_revenue_at", "label": "", "value": "apparel", "unit": "text"}]
    out, dropped = render({"headline": "Revenue reached [[f_total_revenue]], led by [[f_max_revenue_at]].",
                           "body": ["Made up [[f_nope]].", "Fine."], "caveats": [], "follow_ups": []}, facts, "vi")
    assert out["headline"] == "Revenue reached 1.234,50 USD, led by apparel."
    assert out["body"] == ["Fine."] and dropped == 1
    assert out["cited"] == ["1.234,50 USD"]  # numbers only; text facts are not marked as SQL values


def test_insight_drops_unit_repeated_after_placeholder():
    facts = [{"id": "f_r", "label": "", "value": 13591643.7, "unit": "currency", "currency": "BRL"},
             {"id": "f_p", "label": "", "value": 0.488, "unit": "percent"}]
    out, _ = render({"headline": "Peak [[f_r]] BRL, or [[f_r]] (BRL); share [[f_p]] % and [[f_p]] of all.",
                     "body": [], "caveats": [], "follow_ups": []}, facts, "vi")
    assert out["headline"] == "Peak 13.591.643,70 BRL, or 13.591.643,70 BRL; share 48,8% and 48,8% of all."


def test_format_percent_and_counts():
    assert format_value(0.1234, "percent") == "12.3%"
    assert format_value(1234567, "count", lang="vi") == "1.234.567"


def test_interpret_instruction_has_no_business_vocabulary():
    import re
    words = ({m.id for m in CAT.metrics} | {d.id for d in CAT.dimensions} | {"revenue", "orders", "purchase", "cart", "olist", "cosmetics"}) - {"source"}
    text = INTERPRET_INSTRUCTION.lower()
    assert not [w for w in words if re.search(rf"\b{re.escape(w)}\b", text)]


def test_golden_cases_use_catalog_ids():
    cases = yaml.safe_load((ROOT / "backend" / "eval" / "golden.yaml").read_text(encoding="utf-8"))
    for case in cases:
        e = case["expect"]
        for m in [e.get("recipe"), *e.get("metrics", []), *e.get("recipe_in", [])]:
            assert m is None or m in CAT.mets, (case["id"], m)
        for d in [*e.get("selection", []), *(f["field"] for f in e.get("filters", []))]:
            assert d in CAT.dims, (case["id"], d)
    assert len(cases) >= 50 and len({c["id"] for c in cases}) == len(cases)


def test_insight_calculations_use_user_values_only():
    facts = [{"id": "f_olist", "label": "Olist peak month", "value": 1000.0, "unit": "currency", "currency": "BRL"},
             {"id": "f_shop", "label": "Shop peak month", "value": 300.0, "unit": "currency", "currency": "USD"}]
    raw = {"assumptions": [{"id": "u_brl_per_usd", "label": "BRL per USD (given)", "value": 5.0, "unit": "number", "currency": ""},
                           {"id": "u_invented", "label": "rate from memory", "value": 4.1, "unit": "number", "currency": ""}],
           "calculations": [{"id": "c_olist_usd", "label": "Olist in USD", "expr": "f_olist / u_brl_per_usd", "unit": "currency", "currency": "USD"},
                            {"id": "c_gap", "label": "Olist minus shop (USD)", "expr": "c_olist_usd - f_shop", "unit": "currency", "currency": "USD"},
                            {"id": "c_bad", "label": "x", "expr": "f_olist / u_invented", "unit": "currency", "currency": "USD"}],
           "headline": "Olist peaked at [[c_olist_usd]], [[c_gap]] above the shop.",
           "body": ["Using a rate from memory gives [[c_bad]]."], "caveats": [], "follow_ups": []}
    out, dropped = render(raw, facts, "en", user_text="convert at 5 BRL per USD")
    assert out["headline"] == "Olist peaked at 200.00 USD, -100.00 USD above the shop."
    assert out["body"] == [] and dropped == 1  # the invented rate is rejected, so its sentence goes
    kinds = {m["text"]: m["kind"] for m in out["marks"]}
    assert kinds == {"200.00 USD": "calculation", "-100.00 USD": "calculation"}
    assert "Olist peak month (1,000.00 BRL)" in out["marks"][0]["formula"] or "Olist peak month" in out["marks"][1]["formula"]


def test_converted_metric_compares_across_currencies():
    rows = [{"source": "olist_marketplace", "revenue_usd": 300.0}, {"source": "cosmetics_shop", "revenue_usd": 100.0}]
    cols = [Column("source", "Store", "dimension"), Column("revenue_usd", "Revenue in USD", "metric", "currency", True, "number", "USD")]
    facts = {f["id"]: f for f in compute_facts(rows, cols, "breakdown", False, {"olist_marketplace": "BRL", "cosmetics_shop": "USD"})}
    assert facts["f_total_revenue_usd"]["value"] == 400 and facts["f_total_revenue_usd"]["currency"] == "USD"
    assert facts["f_diff_revenue_usd"]["value"] == 200 and facts["f_max_revenue_usd"]["currency"] == "USD"
    # The store-currency metric still refuses to add BRL to USD.
    raw = [{"source": "olist_marketplace", "revenue": 300.0}, {"source": "cosmetics_shop", "revenue": 100.0}]
    plain = {f["id"] for f in compute_facts(raw, [cols[0], Column("revenue", "Revenue", "metric", "currency", True, "number")],
                                           "breakdown", False, {"olist_marketplace": "BRL", "cosmetics_shop": "USD"})}
    assert "f_total_revenue" not in plain and "f_diff_revenue" not in plain


def test_money_ratio_must_match_its_parts_currency():
    bad = yaml.safe_load(yaml.safe_dump(RAW))
    for m in bad["metrics"]:
        if m["id"] == "aov_usd":
            m["ratio"]["numerator"] = "revenue"  # store currency, but the ratio claims USD
    with pytest.raises(ValueError, match="aov_usd: currency USD differs"):
        c.validate_catalog(bad)
