"""Generate research_v4 single-question cases against REAL data (data/landing), family-disjoint dev/test.

Expected results come from backend/eval/oracle_csv.py (DuckDB straight on the raw CSV files, definitions in
GLOSSARY.md). The gold SQL text is produced by the declarative writer in research_v3/generate.py and is only
trusted after validate_research_v4.py shows it returns the oracle's table on the ETL-loaded warehouse.

A family is (source, metric, shape). Every family is assigned wholly to dev or to test, so no test case shares a
phenomenon with a development case. Cases that give an empty or all-zero answer, a table already used by another
case, or that cannot be told apart from two plausible wrong readings are rejected.

Usage: python data/benchmark/research_v4/generate.py   (needs duckdb and the CSV files in data/landing)
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys

import yaml

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]
sys.path.insert(0, str(PROJECT / "backend" / "eval"))
from benchmark import results_equal  # noqa: E402
from oracle_csv import PURCHASE, SOURCE_METRICS, RawOracle  # noqa: E402

_spec = importlib.util.spec_from_file_location("research_v3_sql_writer", PROJECT / "data/benchmark/research_v3/generate.py")
_v3 = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(_v3)
sql_for = _v3.sql_for

SEED = 4
WORLD = "real"
SOURCES = ("cosmetics_shop", "olist_marketplace")
LABEL = {"cosmetics_shop": "Cosmetics Shop", "olist_marketplace": "Olist"}
# Olist is sparse before 2017 and after mid-2018; stay in the dense part for windows.
SPAN = {"cosmetics_shop": (date(2019, 12, 1), date(2020, 1, 31)), "olist_marketplace": (date(2017, 2, 1), date(2018, 8, 15))}
METRIC_EN = {"events": "events", "users": "distinct users", "sessions": "sessions", "viewers": "distinct viewers",
             "purchases": "purchased item lines", "buyers": "distinct buyers", "revenue": "purchase revenue",
             "buyer_conversion_rate": "buyer-to-observed-user rate"}
METRIC_VI = {"events": "lượt sự kiện", "users": "người dùng duy nhất", "sessions": "phiên truy cập",
             "viewers": "người xem sản phẩm duy nhất", "purchases": "dòng sản phẩm đã mua",
             "buyers": "người mua duy nhất", "revenue": "doanh thu từ sản phẩm đã mua",
             "buyer_conversion_rate": "tỷ lệ người mua trên người dùng quan sát được"}
DIM_EN = {"event_date": "date", "event_name": "event type", "item_category": "product category"}
DIM_VI = {"event_date": "ngày", "event_name": "loại sự kiện", "item_category": "danh mục sản phẩm"}

# shape -> (stratum, metrics allowed per source (None = all), dev/test quota weight is derived from the strata)
ALL = None
SHAPES = {
    "period_total": ("basic", ALL),
    "single_day": ("basic", ALL),
    "event_filter": ("compositional", {"cosmetics_shop": ("events", "users", "sessions"), "olist_marketplace": ("events", "users")}),
    "category_filter": ("compositional", ALL),
    "daily_breakdown": ("compositional", ALL),
    "category_breakdown": ("compositional", ALL),
    # buyer_conversion_rate by event type is 0/1 for any window, so it cannot tell readings apart: excluded.
    "event_breakdown": ("compositional", {"cosmetics_shop": ("events", "users", "sessions"),
                                          "olist_marketplace": ("events", "users")}),
    "top_categories": ("semantic", ALL),
    # Only Olist has events without a product category (order lifecycle rows); Cosmetics rows all carry one.
    "missing_category": ("semantic", {"cosmetics_shop": (), "olist_marketplace": ("events", "users")}),
}
QUOTAS = {"dev": {"basic": 20, "compositional": 50, "semantic": 30}, "test": {"basic": 40, "compositional": 100, "semantic": 60}}
SIBLING = {"purchases": "buyers", "buyers": "purchases", "users": "events", "events": "users", "revenue": "purchases",
           "sessions": "users", "viewers": "users", "buyer_conversion_rate": "buyers"}


def families():
    out = []
    for source in SOURCES:
        for shape, (stratum, allowed) in SHAPES.items():
            metrics = SOURCE_METRICS[source] if allowed is None else allowed[source]
            for metric in metrics:
                out.append({"source": source, "metric": metric, "shape": shape, "stratum": stratum,
                            "name": f"{source}:{metric}:{shape}"})
    return out


def assign_split(fams):
    """Deterministic family-disjoint split: ~1/3 of each (stratum, source) group goes to dev."""
    split = {}
    for stratum in ("basic", "compositional", "semantic"):
        for source in SOURCES:
            group = sorted((f for f in fams if f["stratum"] == stratum and f["source"] == source),
                           key=lambda f: hashlib.sha256(f"v4|{f['name']}".encode()).hexdigest())
            n_dev = max(1, round(len(group) * QUOTAS["dev"][stratum] / (QUOTAS["dev"][stratum] + QUOTAS["test"][stratum])))
            for i, f in enumerate(group):
                split[f["name"]] = "dev" if i < n_dev else "test"
    return split


def _window(rng, source, lo_days, hi_days):
    lo, hi = SPAN[source]
    days = rng.randint(lo_days, hi_days)
    start = lo + timedelta(days=rng.randrange((hi - lo).days - days))
    return start.isoformat(), (start + timedelta(days=days - 1)).isoformat()


def _question(source, metric, where, group, limit, lang, style):
    m = (METRIC_EN if lang == "en" else METRIC_VI)[metric]
    dims = DIM_EN if lang == "en" else DIM_VI
    parts = []
    for item in where:
        (field, value), = item.items()
        if field == "event_date" and isinstance(value, dict):
            lo, hi = value["between"]
            parts.append(f"from {lo} through {hi}" if lang == "en" else f"từ {lo} đến hết {hi}")
        elif field == "event_date":
            parts.append(f"on {value}" if lang == "en" else f"ngày {value}")
        elif isinstance(value, dict) and value.get("is_null"):
            parts.append(f"with no recorded {dims[field]}" if lang == "en" else f"chưa ghi nhận {dims[field]}")
        else:
            parts.append(f"{dims[field]} '{value}'" if lang == "en" else f"{dims[field]} '{value}'")
    scope = ", ".join(parts)
    label = LABEL[source]
    if group and limit:
        d = dims[group]
        return (f"{label}: rank the top {limit} {d} by {m}, {scope}; break ties by {d} ascending, missing values last."
                if lang == "en" else
                f"{label}: xếp hạng {limit} {d} cao nhất theo {m}, {scope}; nếu bằng nhau thì xếp {d} tăng dần, giá trị thiếu cuối cùng.")
    if group:
        d = dims[group]
        en = [f"{label}: break down {m} by {d}, {scope}.", f"{label}: how do {m} split across {d}, {scope}?",
              f"{label}: show {m} for each {d}, {scope}."]
        vi = [f"{label}: phân tích {m} theo {d}, {scope}.", f"{label}: {m} chia theo {d} như thế nào, {scope}?",
              f"{label}: cho biết {m} ứng với từng {d}, {scope}."]
        return (en if lang == "en" else vi)[style % 3]
    en = [f"{label}: report {m}, {scope}.", f"{label}: what were the {m}, {scope}?", f"{label}: calculate {m}, {scope}."]
    vi = [f"{label}: báo cáo {m}, {scope}.", f"{label}: {m} là bao nhiêu, {scope}?", f"{label}: tính {m}, {scope}."]
    return (en if lang == "en" else vi)[style % 3]


class Builder:
    def __init__(self):
        self.oracle = RawOracle()
        self.rng = random.Random(SEED)
        self.used_tables, self.used_questions, self.used_sql = set(), set(), set()
        self.daily = {s: self.oracle.daily_counts(s) for s in SOURCES}
        self.rejects = Counter()
        self.infeasible = {}

    def _spec(self, fam):
        rng, o, source, metric, shape = self.rng, self.oracle, fam["source"], fam["metric"], fam["shape"]
        lo, hi = _window(rng, source, 7, 31) if source == "olist_marketplace" else _window(rng, source, 5, 21)
        window = {"event_date": {"between": [lo, hi]}}
        if shape == "period_total":
            return [window], None, None, None
        if shape == "single_day":
            span_lo, span_hi = SPAN[source]
            days = [d for d, n in self.daily[source].items() if span_lo.isoformat() <= d <= span_hi.isoformat() and n >= 30]
            return [{"event_date": rng.choice(days)}], None, None, None
        if shape == "event_filter":
            name = rng.choice(o.values(source, "event_name"))
            return [{"event_name": name}, window], None, None, None
        if shape == "category_filter":
            cats = [c for c in o.values(source, "item_category", [window]) if c is not None][:8]
            if not cats:
                return None
            return [{"item_category": rng.choice(cats)}, window], None, None, None
        if shape == "daily_breakdown":
            lo, hi = _window(rng, source, 3, 7)
            return [{"event_date": {"between": [lo, hi]}}], "event_date", None, None
        if shape == "category_breakdown":
            return [window], "item_category", None, None
        if shape == "event_breakdown":
            return [window], "event_name", None, None
        if shape == "top_categories":
            return [window], "item_category", rng.choice([3, 5]), "metric_desc"
        if shape == "missing_category":
            return [{"item_category": {"is_null": True}}, window], None, None, None
        raise ValueError(shape)

    def _trivial(self, result):
        rows = result["rows"]
        if not rows or len(rows) > 100:
            return True
        values = [r[-1] for r in rows]
        return all(v in (0, None) for v in values)

    def _alternatives(self, source, metric, where, group, limit, order_by, gold):
        """Two plausible wrong readings; the gold table must differ from both."""
        sibling = SIBLING[metric] if SIBLING[metric] in SOURCE_METRICS[source] else "users"
        wrong = {"sibling_metric": self.oracle.evaluate(source, sibling, where, group, limit, order_by),
                 "all_time": self.oracle.evaluate(source, metric, [], group, limit, order_by)}
        differs = {}
        for name, result in wrong.items():
            same = results_equal(result["columns"], result["rows"], result["columns"], gold["rows"], ordered=bool(limit))
            differs[name] = not same
        return differs

    def make_case(self, fam, split, index, lang):
        for _ in range(60):
            spec = self._spec(fam)
            if spec is None:
                continue
            where, group, limit, order_by = spec
            source, metric = fam["source"], fam["metric"]
            gold = self.oracle.evaluate(source, metric, where, group, limit, order_by)
            if self._trivial(gold):
                self.rejects["trivial"] += 1
                continue
            key = json.dumps([gold["columns"], gold["rows"]], sort_keys=True)
            question = _question(source, metric, where, group, limit, lang, index)
            sql = sql_for(source, metric, where, group, limit, order_by)
            if key in self.used_tables or question in self.used_questions or sql in self.used_sql:
                self.rejects["duplicate"] += 1
                continue
            alternatives = self._alternatives(source, metric, where, group, limit, order_by, gold)
            if not all(alternatives.values()):
                self.rejects["not_discriminating"] += 1
                continue
            self.used_tables.add(key); self.used_questions.add(question); self.used_sql.add(sql)
            return {"id": f"rv4_{split}_{index:03d}", "split": split, "family": fam["name"], "source_id": source,
                    "ui_scope": [source], "language": lang, "stratum": fam["stratum"], "shape": fam["shape"], "metric": metric,
                    "spec": {"where": where, "group": group, "limit": limit, "order_by": order_by},
                    "question": question, "gold_sql": sql, "expected_result": gold,
                    "expected_results_by_world": {WORLD: gold}, "fixture_world": WORLD, "in_scope": True,
                    "ordered": bool(limit), "intent": fam["stratum"],
                    "difficulty": {"basic": "easy", "compositional": "hard", "semantic": "hard"}[fam["stratum"]],
                    "distinguished_from": sorted(alternatives), "oracle": "raw_csv_duckdb",
                    "tags": [source, fam["stratum"], lang, "real_data"]}
        self.infeasible[fam["name"]] = dict(self.rejects)
        return None


def build():
    builder = Builder()
    fams = families()
    split_of = assign_split(fams)
    cases = []
    counter = 0
    for split in ("dev", "test"):
        for stratum in ("basic", "compositional", "semantic"):
            group = sorted((f for f in fams if f["stratum"] == stratum and split_of[f["name"]] == split),
                           key=lambda f: hashlib.sha256(f"v4|{f['name']}".encode()).hexdigest())
            quota, n = QUOTAS[split][stratum], len(group)
            # Even source balance: allocate the quota per source, then round-robin over that source's feasible
            # families. A family whose data cannot give a discriminating case is dropped and reported.
            for source in SOURCES:
                members = [f for f in group if f["source"] == source]
                dead, made, turn = set(), 0, 0
                while made < quota // 2:
                    live = [f for f in members if f["name"] not in dead]
                    if not live:
                        raise RuntimeError(f"no feasible family left for {split}/{stratum}/{source}")
                    fam = live[turn % len(live)]
                    turn += 1
                    counter += 1
                    case = builder.make_case(fam, split, counter, "en" if counter % 2 else "vi")
                    if case is None:
                        dead.add(fam["name"])
                        counter -= 1
                        continue
                    cases.append(case)
                    made += 1
    return cases, builder, split_of


def stats(cases, builder):
    dev = {c["family"] for c in cases if c["split"] == "dev"}
    test = {c["family"] for c in cases if c["split"] == "test"}
    tables = {json.dumps([c["expected_result"]["columns"], c["expected_result"]["rows"]]) for c in cases}
    return {"cases": len(cases), "dev": sum(c["split"] == "dev" for c in cases), "test": sum(c["split"] == "test" for c in cases),
            "strata_test": dict(Counter(c["stratum"] for c in cases if c["split"] == "test")),
            "strata_dev": dict(Counter(c["stratum"] for c in cases if c["split"] == "dev")),
            "sources_test": dict(Counter(c["source_id"] for c in cases if c["split"] == "test")),
            "dev_families": len(dev), "test_families": len(test), "family_overlap": len(dev & test),
            "distinct_result_tables": len(tables), "single_row_results": sum(len(c["expected_result"]["rows"]) == 1 for c in cases),
            "empty_or_zero_results": 0, "rejected_candidates": dict(builder.rejects),
            "infeasible_families": sorted(builder.infeasible)}


def main():
    cases, builder, split_of = build()
    info = stats(cases, builder)
    assert info["family_overlap"] == 0 and info["distinct_result_tables"] == len(cases)
    (ROOT / "cases.yaml").write_text(yaml.safe_dump(cases, sort_keys=False, allow_unicode=True, width=200), encoding="utf-8")
    manifest = {
        "name": "Texa Research Benchmark v4 candidate (real data, independent oracle)",
        "dataset_type": "research_candidate", "version": 4, "status": "agent_authored_unsealed_pending_human_review",
        "engine": "PostgreSQL 16+", "sources": list(SOURCES),
        "metrics": ["events", "users", "sessions", "viewers", "purchases", "buyers", "revenue", "buyer_conversion_rate"],
        "suites": ["single"], "single_turn_suite": "cases.yaml", "fixture_worlds": {WORLD: {"file": "worlds/real.sql", "generated_by": "export_world.py"}},
        "gold_oracle": {"engine": "duckdb", "module": "backend/eval/oracle_csv.py", "glossary": "GLOSSARY.md",
                        "independence": "reads raw CSV only; shares no code or definitions file with the ETL mart, the catalog or research_v3"},
        "raw_data_sha256": builder.oracle.raw_file_hashes(),
        "split_policy": "Family-disjoint: a family is (source, metric, shape); each family is entirely dev or test. Dev "
                        f"{QUOTAS['dev']}, test {QUOTAS['test']}, evenly split over the two sources.",
        "quality_gates": ["no empty or all-zero gold", "every gold table unique", "gold differs from two plausible wrong readings",
                          "gold SQL on the ETL warehouse equals the raw-CSV oracle (validate_research_v4.py)"],
        "statistics": info, "human_review": "pending two independent reviewers (see AUDIT.csv and REVIEW_GUIDE.md)",
        "sealed": False, "test_labels_exposed_to_author": True,
        "limitations": "Questions are still template-generated (3 phrasings per shape). Real data removes the tiny-fixture and "
                       "circular-oracle weaknesses of v3 but does not replace human review. Cosmetics Shop is small "
                       "(6,200 events). Single-question suite only; clarification, conversation and unsupported suites remain v3.",
    }
    (ROOT / "manifest.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, width=200), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
