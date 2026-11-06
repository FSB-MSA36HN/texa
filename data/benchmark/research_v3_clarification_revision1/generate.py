"""Generate the corrected, append-only clarification revision 1.

Gold logic is the same independent declarative oracle used by research_v3.
The SQL fixtures are copied into this directory so future runs are standalone.
"""
from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("research_v3_revision1_gold", ROOT / "gold_oracle.py")
gold = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(gold)

SOURCES = ("cosmetics_shop", "olist_marketplace")
LABEL = {"cosmetics_shop": "Cosmetics Shop", "olist_marketplace": "Olist"}
METRICS = ("revenue", "purchases")


def period(source: str, i: int) -> list[str]:
    base = date(2025, 1, 1) if source == "cosmetics_shop" else date(2018, 1, 1)
    max_days = 69 if source == "cosmetics_shop" else 62
    start = base + timedelta(days=(i * 3) % (max_days - 6))
    end = start + timedelta(days=4 + i % 3)
    return [start.isoformat(), end.isoformat()]


def date_en(window: list[str]) -> str:
    return f"from {window[0]} through {window[1]}"


def date_vi(window: list[str]) -> str:
    return f"từ ngày {window[0]} đến ngày {window[1]}"


def result(source, metric, window, world="base"):
    where = [{"event_date": {"between": window}}] if window else []
    return gold.evaluate(source, metric, where=where, world=world)


def sql(source, metric, window):
    where = [{"event_date": {"between": window}}] if window else []
    return gold.sql_for(source, metric, where=where)


def build():
    source_rows = yaml.safe_load((ROOT.parent / "research_v3" / "interactions.yaml").read_text(encoding="utf-8"))
    # Preserve the original 15 time-clarification pairs exactly; add only the
    # explicit source scope metadata needed for an apples-to-apples input contract.
    rows = []
    for item in source_rows[:30]:
        row = dict(item)
        source = row["state"]["source_id"]
        question = row["question"]
        row.update({"source_id": source, "language": "vi" if any(ord(c) > 127 for c in question) else "en",
                    "ui_scope": [source]})
        rows.append(row)
    # Replace the invalid old customer-count ambiguity with genuine sales
    # ambiguity: monetary purchase revenue versus purchase-row/event count.
    for i in range(15, 30):
        source = SOURCES[i % 2]
        language = "vi" if i % 4 in (1, 2) else "en"
        vi = language == "vi"
        local = i - 15
        metric = METRICS[local % len(METRICS)]
        window = period(source, i)
        cluster = f"clarify_r1_{local + 16:02d}"
        if vi:
            question = f"Báo cáo doanh số của {LABEL[source]} {date_vi(window)}."
            if metric == "revenue":
                control = f"Cho biết tổng doanh thu từ sản phẩm đã mua của {LABEL[source]} {date_vi(window)}."
            else:
                unit = "dòng sản phẩm đã mua" if source == "olist_marketplace" else "lượt mua"
                control = f"Đếm số {unit} của {LABEL[source]} {date_vi(window)}."
        else:
            question = f"Report sales for {LABEL[source]} {date_en(window)}."
            unit = "purchased item lines" if source == "olist_marketplace" else "purchase events"
            control = (f"Report purchase revenue for {LABEL[source]} {date_en(window)}."
                       if metric == "revenue" else
                       f"Count {unit} for {LABEL[source]} {date_en(window)}.")
        field, oracle, phenomenon = "recipe", metric, "ambiguous_sales"
        state_period = window

        expected = result(source, metric, window)
        expected_by_world = {
            name: result(source, metric, window, name)
            for name in ("base", "grain_counterexample", "coverage_edge")
        }
        state = {"source_id": source, "metric": metric, "time_range": state_period,
                 "filters": [], "breakdown": None}
        common = {
            "split": "test", "family": f"test_{phenomenon}", "cluster_id": cluster,
            "source_id": source, "language": language, "ui_scope": [source],
            "phenomenon": phenomenon, "state": state,
            "oracle_intent": {"source_id": source, "metric": metric, "time_range": state_period},
            "gold_sql": sql(source, metric, window), "expected_result": expected,
            "expected_results_by_world": expected_by_world,
            "tags": ["clarification", phenomenon, source, language],
        }
        rows.append({**common, "id": f"{cluster}_ask", "question": question,
                     "ask_fields": [field], "oracle_answers": {field: [oracle]}})
        rows.append({**common, "id": f"{cluster}_control", "question": control,
                     "phenomenon": "explicit_control", "control_of": f"{cluster}_ask",
                     "ask_fields": [], "oracle_answers": {},
                     "tags": ["clarification_control", source, language]})
    # Materialize one row per controlled SQL fixture world. The matrix runner
    # selects exactly 60 rows per world and compares against that world's gold.
    expanded = []
    for world in ("base",):
        for row in rows:
            clone = dict(row)
            clone["id"] = f"{row['id']}__{world}"
            if clone.get("control_of"):
                clone["control_of"] = f"{clone['control_of']}__{world}"
            clone["fixture_world"] = world
            clone["expected_result"] = clone["expected_results_by_world"][world]
            expanded.append(clone)
    return expanded


def write():
    rows = build()
    (ROOT / "interactions.yaml").write_text(
        yaml.safe_dump(rows, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8")
    base_rows = [row for row in rows if row["fixture_world"] == "base"]
    print({"physical_records": len(rows), "records_per_world": len(base_rows),
           "ambiguous_per_world": sum(bool(row["ask_fields"]) for row in base_rows),
           "controls_per_world": sum(not row["ask_fields"] for row in base_rows),
           "source_counts": {source: sum(row["source_id"] == source and bool(row["ask_fields"]) for row in base_rows)
                             for source in SOURCES},
           "language_counts": {language: sum(row["language"] == language and bool(row["ask_fields"]) for row in base_rows)
                               for language in ("en", "vi")}})


if __name__ == "__main__":
    write()
