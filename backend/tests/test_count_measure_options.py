from copy import deepcopy
from pathlib import Path

import yaml

from texa import catalog, interpret

ROOT = Path(__file__).resolve().parents[2]
RAW = yaml.safe_load((ROOT / "catalog/product_events.yaml").read_text())


def _source(source_id, events):
    return catalog.Source(id=source_id, label=source_id, description="", currency="USD",
                          min_date=None, max_date=None, row_count=1, user_count=1,
                          events=set(events), columns={"user_id", "event_name"})


def _role_option(options, role, operation):
    return next(o for o in options if o["event_role_id"] == role and o["operation"] == operation)


def test_options_derive_from_renamed_source_role_and_metric_without_mutation():
    raw = deepcopy(RAW)
    for role in raw["event_roles"]:
        if role["id"] == "product_view":
            role["id"] = "item_opening"
            role["events"] = ["item_opened"]
        elif role["id"] == "any_event":
            role["id"] = "all_activity"
            role["events"] = ["item_opened" if e == "view" else e for e in role["events"]]
    for metric in raw["metrics"]:
        if metric["id"] == "events":
            metric["id"] = "row_total"
        elif metric["id"] == "viewers":
            metric["id"] = "unique_openers"
            metric["simple"]["event_role"] = "item_opening"
        if metric.get("simple", {}).get("event_role") == "any_event":
            metric["simple"]["event_role"] = "all_activity"
    cat = catalog.validate_catalog(raw)
    src = _source("renamed_store", {"item_opened"})
    metrics_before = deepcopy(cat.metrics)
    events_before = set(src.events)

    options = interpret.count_measure_options(cat, src)
    row_option = _role_option(options, "item_opening", "count_events")
    user_option = _role_option(options, "item_opening", "count_users")
    assert row_option["base_metric_id"] == "row_total"
    assert row_option["counting_entity"] == "event_occurrences"
    assert row_option["required_filters"] == [
        {"field_id": "event_name", "operator": "IN", "values": ["item_opened"]}]
    assert user_option["base_metric_id"] == "unique_openers"
    assert user_option["counting_entity"] == "distinct_users"
    assert user_option["required_filters"] == []
    assert cat.metrics == metrics_before
    assert src.id == "renamed_store" and src.events == events_before


def test_exact_aggregation_and_role_metric_is_preferred_to_composition():
    raw = deepcopy(RAW)
    raw["metrics"].append({
        "id": "item_view_rows", "label": "Item view rows", "unit": "count", "type": "simple",
        "intent_grain": "event_row", "group_domain": "metric_support",
        "simple": {"aggregation": "count_events", "event_role": "product_view"},
    })
    cat = catalog.validate_catalog(raw)
    src = _source("store", {"view"})
    option = _role_option(interpret.count_measure_options(cat, src), "product_view", "count_events")
    assert option["base_metric_id"] == "item_view_rows"
    assert option["required_filters"] == []


def test_source_without_tracked_view_role_gets_no_view_count_options():
    cat = catalog.validate_catalog(deepcopy(RAW))
    src = _source("olist_renamed", {"order_purchased"})
    options = interpret.count_measure_options(cat, src)
    assert not any(o["event_role_id"] == "product_view" for o in options)


def test_shortlist_renders_relevant_compositions_and_base_metric_once_per_source():
    cat = catalog.validate_catalog(deepcopy(RAW))
    src = _source("store", {"view", "purchase"})
    text = interpret.render_catalog(cat, {src.id: src}, ids={"viewers"})
    capability = text.split("SOURCE CAPABILITIES", 1)[1].split("\nMETRICS", 1)[0]
    import json
    rows = [json.loads(line) for line in capability.splitlines() if line.startswith("{")]
    assert len(rows) == 1
    option = _role_option(rows[0]["count_measure_options"], "product_view", "count_events")
    assert option["base_metric_id"] == "events"
    assert "events" in text.split("\nDIMENSIONS", 1)[0]
