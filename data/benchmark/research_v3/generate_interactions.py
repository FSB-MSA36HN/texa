"""Generate research_v3 clarification, dialogue, and unsupported-request suites.

Gold SQL/results come from the independent declarative fixture oracle in generate.py;
this module does not import Texa's resolver, compiler, or a model.
"""
from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("research_v3_gold", ROOT / "generate.py")
gold = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gold)

SOURCES = ("cosmetics_shop", "olist_marketplace")
METRICS = {
    "cosmetics_shop": ("events", "users", "sessions", "viewers", "purchases", "buyers", "revenue", "buyer_conversion_rate"),
    "olist_marketplace": ("events", "users", "purchases", "buyers", "revenue", "buyer_conversion_rate"),
}
METRIC_LABELS = {
    "events": "events", "users": "distinct users", "sessions": "sessions",
    "viewers": "viewers", "purchases": "purchase events", "buyers": "buyers",
    "revenue": "revenue", "buyer_conversion_rate": "buyers divided by distinct observed users",
}
METRIC_LABELS_VI = {
    "events": "lượt sự kiện", "users": "người dùng duy nhất", "sessions": "phiên truy cập",
    "viewers": "người xem duy nhất", "purchases": "lượt mua", "buyers": "người mua duy nhất",
    "revenue": "doanh thu", "buyer_conversion_rate": "tỷ lệ người mua trên người dùng quan sát được",
}


def source_phrase(source):
    return "Cosmetics" if source == "cosmetics_shop" else "Olist"


def source_phrase_vi(source):
    return "Cosmetics Shop" if source == "cosmetics_shop" else "Olist"


def date_range(source, i):
    # Deliberately vary exact ranges across the two source calendars.
    base = date(2025, 1, 1) if source == "cosmetics_shop" else date(2018, 1, 1)
    latest_offset = 69 if source == "cosmetics_shop" else 62
    start = base + timedelta(days=(i * 3) % (latest_offset - 6))
    end = start + timedelta(days=4 + (i % 3))
    return [start.isoformat(), end.isoformat()]


def period_words(period):
    return f"from {period[0]} through {period[1]}"


def period_words_vi(period):
    return f"từ ngày {period[0]} đến ngày {period[1]}"


def named_period(source, name):
    if name == "all":
        return None
    source_rows = [r for r in gold.ROWS_BY_WORLD["base"] if r["source"] == source]
    end = max(date.fromisoformat(r["day"]) for r in source_rows)
    return [(end - timedelta(days=6)).isoformat(), end.isoformat()]


def state_for(source, metric, period, filters=None, group=None):
    where = [{"event_date": {"between": period}}] if period else []
    where.extend(filters or [])
    return {"source_id": source, "metric": metric, "time_range": period or "all",
            "filters": filters or [], "breakdown": group}


def answer(question, source, metric, period, filters=None, group=None, reference=None):
    state = state_for(source, metric, period, filters, group)
    sql = gold.sql_for(source, metric, where=state["filters"] + (
        [{"event_date": {"between": period}}] if period else []), group=group)
    where = state["filters"] + ([{"event_date": {"between": period}}] if period else [])
    out = {"question": question, "action": "answer", "state": state,
           "gold_sql": sql,
           "expected_result": gold.evaluate(source, metric, where=where, group=group),
           "expected_results_by_world": {
               world: gold.evaluate(source, metric, where=where, group=group, world=world)
               for world in ("base", "grain_counterexample", "coverage_edge")}}
    if reference is not None:
        out["referenced_turn"] = reference
    return out


def build_interactions():
    rows = []
    ambiguous_prompts = [
        "What was the {metric} for {source}?", "Please show {metric} for {source}.",
        "I need a {metric} report for {source}.", "How much {metric} did {source} have?",
        "Can you summarize {metric} for {source}?",
    ]
    # 30 ambiguity cases, paired one-to-one with explicit controls. Fifteen
    # omissions are temporal; fifteen use the genuinely ambiguous customer term.
    for i in range(30):
        source = SOURCES[i % 2]
        vi = i % 4 in (1, 2)
        split = "test"
        period = date_range(source, i)
        if i < 15:
            metric = ("revenue", "buyers", "users", "purchases", "events")[i % 5]
            intent_period = "all" if i % 2 == 0 else "last_7"
            period = named_period(source, intent_period)
            phrase = source_phrase(source)
            question = (f"Cho tôi xem {METRIC_LABELS_VI[metric]} của {source_phrase_vi(source)}."
                        if vi else ambiguous_prompts[i % len(ambiguous_prompts)].format(
                            metric=METRIC_LABELS[metric], source=phrase))
            field, oracle_value, phenomenon = "time_range", intent_period, "missing_period"
            explicit_period = "all available dates" if intent_period == "all" else "the most recent 7 days"
            clear_question = (f"Cho tôi xem {METRIC_LABELS_VI[metric]} của {source_phrase_vi(source)} "
                              f"trong {('toàn bộ khoảng dữ liệu' if intent_period == 'all' else '7 ngày gần nhất')}."
                              if vi else f"{question.rstrip('.?')} over {explicit_period}.")
        else:
            metric = "buyers" if i % 2 else "users"
            question = (f"Có bao nhiêu khách hàng của {source_phrase_vi(source)} {period_words_vi(period)}?"
                        if vi else f"How many customers did {source_phrase(source)} have {period_words(period)}?")
            field, oracle_value, phenomenon = "recipe", metric, "ambiguous_metric"
            explicit_vi = "người mua duy nhất" if metric == "buyers" else "người dùng duy nhất"
            explicit_en = "distinct purchasing customers" if metric == "buyers" else "distinct active users"
            clear_question = (f"Có bao nhiêu {explicit_vi} của {source_phrase_vi(source)} {period_words_vi(period)}?"
                              if vi else f"How many {explicit_en} did {source_phrase(source)} have {period_words(period)}?")
        cluster = f"interaction_{i + 1:02d}"
        where = [{"event_date": {"between": period}}] if period else []
        state = state_for(source, metric, period)
        state["time_range"] = intent_period if i < 15 else period
        common = {"split": split, "family": f"{split}_{phenomenon}", "cluster_id": cluster,
                  "state": state,
                  "oracle_intent": {"source_id": source, "metric": metric,
                                    "time_range": intent_period if i < 15 else period},
                  "gold_sql": gold.sql_for(source, metric, where=where),
                  "expected_result": gold.evaluate(source, metric, where=where),
                  "expected_results_by_world": {world: gold.evaluate(source, metric, where=where, world=world)
                                                 for world in ("base", "grain_counterexample", "coverage_edge")},
                  "tags": ["clarification", phenomenon, source]}
        rows.append({"id": f"{cluster}_ask", **common, "phenomenon": phenomenon,
                     "question": question, "ask_fields": [field],
                     "oracle_answers": {field: [oracle_value]}})
        rows.append({"id": f"{cluster}_control", **common, "phenomenon": "explicit_control",
                     "control_of": f"{cluster}_ask", "question": clear_question,
                     "ask_fields": [], "oracle_answers": {}, "tags": ["clarification_control", source]})
    return rows


def build_dialogues():
    scenarios = []
    patterns = ("filter_refine", "filter_replace", "metric_switch", "source_switch",
                "topic_return", "social_noise", "date_correction", "grouping",
                "long_reference", "reset_context")
    for n in range(40):
        split = "test"
        source = SOURCES[(n // 10) % 2]
        metrics = METRICS[source]
        period1, period2 = date_range(source, n + 9), date_range(source, n + 21)
        metric1 = metrics[n % len(metrics)]
        metric2 = metrics[(n + 2) % len(metrics)]
        pattern = patterns[n % len(patterns)]
        vi = n % 2 == 1
        turns = []
        first_q = (f"Với {source_phrase_vi(source)}, cho tôi xem {METRIC_LABELS_VI[metric1]} từ ngày {period1[0]} đến {period1[1]}."
                   if vi else f"For {source_phrase(source)}, show {METRIC_LABELS[metric1]} {period_words(period1)}.")
        first = answer(first_q,
                       source, metric1, period1)
        turns.append(first)
        # Every dialogue contains 6–12 turns; intermediate explicit queries are
        # semantically different so long-memory retrieval is measurable.
        target_turn = 1
        for j in range(2, 7 + (n % 7)):
            if pattern == "filter_refine" and j == 2:
                device = ("mobile", "desktop", "tablet")[n % 3]
                filt = [{"device_type": device}]
                turns.append(answer((f"Giữ nguyên khoảng thời gian đó, chỉ tính thiết bị {device}." if vi else
                                    f"Keep that period and count only {device} devices."), source, metric1,
                                    period1, filt, reference=1)); target_turn = 1
            elif pattern == "filter_replace" and j in (2, 3):
                val = "mobile" if j == 2 else "desktop"
                turns.append(answer((f"Đổi bộ lọc thiết bị thành {val}." if vi else
                                    f"Change the device filter to {val}."), source, metric1, period1,
                                    [{"device_type": val}], reference=1)); target_turn = 1
            elif pattern == "date_correction" and j == 2:
                turns.append(answer((f"Đính chính: dùng khoảng từ {period2[0]} đến {period2[1]} thay thế." if vi else
                                    f"Correction: use {period2[0]} through {period2[1]} instead."),
                                    source, metric1, period2, reference=1)); target_turn = 1
            elif pattern == "social_noise" and j in (2, 4):
                turns.append({"question": (("Cảm ơn, thông tin này hữu ích." if j == 2 else "Chờ một chút, tôi đang kiểm tra báo cáo.") if vi else
                                           ("Thanks, that helps." if j == 2 else "One moment, I am checking the report.")),
                              "action": "conversation"})
            elif pattern == "topic_return" and j in (2, 3):
                s2 = SOURCES[1 - SOURCES.index(source)]
                m2 = METRICS[s2][(n + j) % len(METRICS[s2])]
                p2 = date_range(s2, n + j + 27)
                turns.append(answer((f"Câu hỏi mới: {source_phrase_vi(s2)} có {METRIC_LABELS_VI[m2]} từ ngày {p2[0]} đến {p2[1]} là bao nhiêu?"
                                    if vi else f"New question: {source_phrase(s2)} {METRIC_LABELS[m2]} {period_words(p2)}."),
                                    s2, m2, p2)); target_turn = 1
            elif pattern == "source_switch" and j == 2:
                s2 = SOURCES[1 - SOURCES.index(source)]
                m2 = METRICS[s2][(n + 1) % len(METRICS[s2])]
                switch_period = date_range(s2, n + 31)
                turns.append(answer((f"Chuyển sang {source_phrase_vi(s2)}: {METRIC_LABELS_VI[m2]} từ ngày {switch_period[0]} đến {switch_period[1]} là bao nhiêu?"
                                    if vi else f"Switch to {source_phrase(s2)}: what is {METRIC_LABELS[m2]} {period_words(switch_period)}?"),
                                    s2, m2, switch_period)); target_turn = 2
            elif pattern == "grouping" and j == 2:
                turns.append(answer(("Chia kết quả đó theo danh mục sản phẩm." if vi else
                                    "Break the same result down by item category."), source, metric1,
                                    period1, group="item_category", reference=1)); target_turn = 1
            elif pattern == "reset_context" and j == 2:
                turns.append(answer((f"Bắt đầu câu hỏi mới: {METRIC_LABELS_VI[metric2]} của {source_phrase_vi(source)} từ ngày {period2[0]} đến {period2[1]}, không dùng bộ lọc cũ."
                                    if vi else f"Start a fresh query: {METRIC_LABELS[metric2]} for {source_phrase(source)} {period_words(period2)}; no old filters."),
                                    source, metric2, period2)); target_turn = 2
            elif pattern == "long_reference" and j == 6 + (n % 7) - 1:
                # Explicitly refer back to the first answer after a long chain.
                turns.append(answer(((("Quay lại câu hỏi đầu tiên và chia theo danh mục sản phẩm." if source == "cosmetics_shop"
                                     else "Quay lại câu hỏi đầu tiên, giữ nguyên chỉ số và khoảng ngày ban đầu.") if vi else
                                    ("Return to my first question and split it by category." if source == "cosmetics_shop"
                                     else "Return to my first question; keep its original metric and dates."))),
                                    source, metric1, period1,
                                    group="item_category" if source == "cosmetics_shop" else None,
                                    reference=1)); target_turn = 1
            elif pattern == "metric_switch" and j == 2:
                turns.append(answer((f"Giữ nguyên nguồn dữ liệu và khoảng ngày, nhưng đổi sang {METRIC_LABELS_VI[metric2]}." if vi else
                                    f"Keep the same source and dates, but show {METRIC_LABELS[metric2]}."),
                                    source, metric2, period1)); target_turn = 2
            elif j == 5:
                turns.append({"question": (("Đã rõ, cảm ơn." if n % 2 else "Tôi hiểu rồi.") if vi else
                                           ("Got it, thanks." if n % 2 else "Understood.")), "action": "conversation"})
            else:
                metric = metrics[(n + j) % len(metrics)]
                period = period2 if j % 2 else date_range(source, n + j + 3)
                turns.append(answer((f"Còn {METRIC_LABELS_VI[metric]} của {source_phrase_vi(source)} từ ngày {period[0]} đến {period[1]} thì sao?"
                                    if vi else f"And {METRIC_LABELS[metric]} for {source_phrase(source)} {period_words(period)}?"),
                                    source, metric, period)); target_turn = len(turns)
        if len(turns) < 6:
            while len(turns) < 6:
                metric = metrics[(n + len(turns)) % len(metrics)]
                period = date_range(source, n + len(turns) + 5)
                turns.append(answer((f"Cho tôi xem thêm {METRIC_LABELS_VI[metric]} từ ngày {period[0]} đến {period[1]}." if vi else
                                    f"Also show {METRIC_LABELS[metric]} {period_words(period)}."), source, metric, period))
        # Ensure every dialogue has a nontrivial tested dependency at the end.
        if not any(t.get("referenced_turn") for t in turns):
            turns[-1] = answer(("Quay lại câu hỏi đầu tiên giúp tôi." if vi else "Back to the first question, please."),
                               source, metric1, period1, reference=1)
        distance = max((i - t["referenced_turn"] for i, t in enumerate(turns, 1)
                        if t.get("referenced_turn")), default=0)
        scenarios.append({"id": f"dialogue_{n + 1:02d}", "split": split,
                          "language": "vi" if vi else "en",
                          "family": f"{split}_{pattern}", "phenomenon": pattern,
                          "cluster_id": f"dialogue_cluster_{n + 1:02d}",
                          "dependency_distance": distance, "turns": turns})
    return scenarios


def build_unsupported():
    specs = [
        ("order_count", "How many distinct orders were placed on Olist?", "Order-level count is outside the event metric catalog."),
        ("refunds", "What is the total refund amount for Olist?", "Refund amount is not a supported metric."),
        ("profit", "Calculate profit margin for Cosmetics last quarter.", "Profit and margin are not supported metrics."),
        ("retention", "What was 30-day customer retention for Cosmetics?", "Cohort retention is outside the supported scope."),
        ("inventory", "How many units of each product are in stock?", "Inventory is not represented by the event dataset."),
        ("attribution", "Attribute each purchase to its first marketing touch.", "Multi-touch attribution is not supported."),
        ("olist_sessions", "How many sessions did Olist have in January 2018?", "Olist session tracking is unavailable."),
        ("olist_viewers", "How many Olist product viewers were there?", "Olist viewer events are unavailable."),
        ("cross_currency", "Compare Cosmetics USD revenue directly with Olist BRL revenue as one total.", "Cross-source currency aggregation is unsupported."),
        ("array_unnest", "Break Cosmetics sales down by every value in its event tags array.", "Arbitrary nested-array expansion is unsupported."),
        ("join_customers", "Join these events to our CRM and show customer lifetime value.", "External CRM joins and lifetime value are outside scope."),
        ("forecast", "Forecast next month's revenue from this history.", "Forecasting is not supported by the query system."),
        ("causal", "Did the campaign cause the revenue increase?", "Causal inference is outside the supported analytics."),
        ("currency_conversion", "Convert all Olist revenue to USD using historical exchange rates.", "External exchange-rate conversion is unavailable."),
        ("payment_dedupe", "Deduplicate Olist payment attempts and report settled payment volume.", "Payment reconciliation/deduplication is unsupported."),
        ("order_fulfillment", "What is the average delivery time for Olist orders?", "Delivery lifecycle events are not in the benchmark schema."),
        ("product_dimensions", "Show revenue by supplier and warehouse region.", "Supplier and warehouse dimensions are unavailable."),
        ("arbitrary_sql", "Run this SQL: DROP TABLE analytics.event_activity;", "The request is not a supported analytics question."),
        ("brand_dimension", "Break Cosmetics purchases down by manufacturer brand.", "Manufacturer brand is not an available dimension."),
        ("customer_ltv", "Calculate lifetime value for each Olist customer.", "Customer lifetime value is not a supported metric."),
        ("daily_active_users", "Compute daily active users using a rolling 30-day definition.", "Rolling active-user windows are not a supported metric."),
        ("basket_size", "What is the average number of products per Olist basket?", "Basket/order-level aggregation is unsupported."),
        ("delivery_sla", "What percentage of Olist orders arrived within two days?", "Delivery outcomes are not represented in this dataset."),
        ("repeat_purchase", "What percentage of Cosmetics buyers made a second purchase?", "Repeat-purchase cohort analysis is unsupported."),
        ("price_elasticity", "Estimate price elasticity for each Cosmetics category.", "Price elasticity requires unsupported causal/statistical analysis."),
        ("sentiment", "Summarize customer sentiment from product reviews.", "Review text and sentiment are outside the event schema."),
        ("geography", "Show Olist revenue by customer state and city.", "Customer geography is unavailable in the supported schema."),
        ("stockout", "Which Cosmetics products were out of stock last week?", "Inventory and stockout data are unavailable."),
        ("subscription_churn", "How many subscribers churned in the last quarter?", "Subscription and churn events are unsupported."),
        ("ad_spend", "Compare campaign spend with attributed revenue by channel.", "Ad spend is not in the event data and attribution is unsupported."),
        ("order_status", "How many Olist orders were canceled before fulfillment?", "Canceled-order lifecycle events are outside this dataset."),
        ("distinct_orders", "Count Olist orders rather than purchased item rows.", "Order identifiers and order-grain count are outside the supported metric contract."),
        ("payment_reconciliation", "Reconcile duplicate payment attempts and report net settled sales.", "Payment reconciliation and deduplication are unsupported."),
        ("exchange_rate", "Convert each Olist purchase to USD using the exchange rate on that date.", "External historical exchange-rate data is unavailable."),
        ("cross_source_ratio", "What is Olist revenue divided by Cosmetics revenue for the same dates?", "Cross-source calculations are unsupported."),
        ("array_dimension", "Group event counts by each element in the product tags array.", "Arbitrary nested-array expansion is unsupported."),
        ("custom_join", "Join event data to our internal loyalty database and count VIP buyers.", "External data joins and VIP attributes are unavailable."),
        ("forecast_seasonal", "Forecast revenue for the next six months including seasonality.", "Forecasting is outside the supported query scope."),
        ("causal_lift", "Estimate the causal lift of paid campaigns on purchases.", "Causal inference is unsupported."),
        ("market_basket", "Which product pairs are most often bought together?", "Market-basket analysis is unsupported."),
        ("funnel", "Show conversion at each step of the browse-cart-checkout funnel.", "Multi-step funnel metrics are not defined in the catalog."),
        ("retention_cohort", "Build monthly retention cohorts for first-time buyers.", "Cohort retention is outside the supported metric set."),
        ("net_revenue", "Calculate net revenue after refunds, discounts, and chargebacks.", "Refunds, discounts, and chargebacks are not modeled."),
        ("sql_mutation", "Run SQL to delete all rows for Olist.", "Data-modifying SQL is not an allowed analytics request."),
        ("unsupported_metric", "Show gross merchandise value after shipping and tax.", "The requested financial metric is not defined in the catalog."),
        ("support_tickets", "Compare purchase revenue with customer support ticket volume.", "Support-ticket data is unavailable."),
        ("inventory_turnover", "Calculate inventory turnover by product category.", "Inventory balances are not represented in the event data."),
        ("region_currency", "Rank countries by revenue converted to one currency.", "Country and currency-conversion dimensions are unsupported."),
        ("user_demographics", "Show buyers split by age group and gender.", "Demographic attributes are unavailable."),
        ("forecast_stock", "Predict which products will be out of stock next month.", "Inventory forecasting is outside scope."),
    ]
    rows = []
    for i in range(40):
        key, question, reason = specs[i % len(specs)]
        split = "test"
        rows.append({"id": f"unsupported_{i + 1:02d}", "split": split,
                     "family": f"{split}_{key}", "phenomenon": key,
                     "question": question, "expected_action": "refuse",
                     "expected_reason": reason, "action": "refuse",
                     "tags": ["out_of_scope", key]})
    return rows


def write():
    ROOT.mkdir(parents=True, exist_ok=True)
    for filename, data in (("interactions.yaml", build_interactions()),
                           ("dialogues.yaml", build_dialogues()),
                           ("unsupported.yaml", build_unsupported())):
        (ROOT / filename).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    print({"interactions": len(build_interactions()), "clarify": sum(bool(x["ask_fields"]) for x in build_interactions()),
           "controls": sum(not x["ask_fields"] for x in build_interactions()),
           "dialogues": len(build_dialogues()), "turns": sum(len(x["turns"]) for x in build_dialogues()),
           "dialogue_min_turns": min(len(x["turns"]) for x in build_dialogues()),
           "dialogue_max_turns": max(len(x["turns"]) for x in build_dialogues()),
           "unsupported": len(build_unsupported())})


if __name__ == "__main__":
    write()
