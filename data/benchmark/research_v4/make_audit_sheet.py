"""Write blind audit sheets for two independent human reviewers (AUDIT_A.csv, AUDIT_B.csv).

Draws a seeded stratified sample of TEST cases (about 30%: 12 basic, 30 compositional, 18 semantic) and always
includes every sampled-stratum case whose gold has a NULL group or a top-k ranking, because those encode the
conventions most likely to be disputed. Each reviewer gets the same cases in a different order with the verdict
columns empty. Nothing here is a review result: backend/eval/audit_stats.py reads the filled sheets.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import random

import yaml

ROOT = Path(__file__).resolve().parent
SAMPLE = {"basic": 12, "compositional": 30, "semantic": 18}
COLUMNS = ["id", "stratum", "source", "language", "flags", "question", "gold_sql", "gold_columns", "gold_rows",
           "verdict", "notes"]
# verdict: correct | ambiguous | wrong
#   correct   = the question has one reasonable reading and the gold table answers it
#   ambiguous = a reasonable reader could expect a different table (explain in notes)
#   wrong     = the gold table does not answer the question


def flags(case):
    rows = case["expected_result"]["rows"]
    out = []
    if any(r[0] is None for r in rows) and len(case["expected_result"]["columns"]) == 2:
        out.append("null_group")
    if case["spec"]["limit"]:
        out.append("top_k")
    if len(rows) == 1:
        out.append("single_row")
    return ",".join(out)


def main():
    cases = [c for c in yaml.safe_load((ROOT / "cases.yaml").read_text(encoding="utf-8")) if c["split"] == "test"]
    rng = random.Random(44)
    chosen = []
    for stratum, n in SAMPLE.items():
        pool = [c for c in cases if c["stratum"] == stratum]
        risky = [c for c in pool if "null_group" in flags(c) or "top_k" in flags(c)]
        rng.shuffle(risky)
        picked = risky[: n // 2]
        rest = [c for c in pool if c not in picked]
        rng.shuffle(rest)
        chosen += picked + rest[: n - len(picked)]
    for reviewer in ("A", "B"):
        order = chosen[:]
        random.Random(reviewer).shuffle(order)
        with (ROOT / f"AUDIT_{reviewer}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            for c in order:
                result = c["expected_result"]
                writer.writerow({"id": c["id"], "stratum": c["stratum"], "source": c["source_id"], "language": c["language"],
                                 "flags": flags(c), "question": c["question"], "gold_sql": c["gold_sql"],
                                 "gold_columns": json.dumps(result["columns"]),
                                 "gold_rows": json.dumps(result["rows"][:12], ensure_ascii=False)
                                              + (f" ... ({len(result['rows'])} rows)" if len(result["rows"]) > 12 else ""),
                                 "verdict": "", "notes": ""})
    print(f"{len(chosen)} cases sampled; flagged: {sum(bool(flags(c)) for c in chosen)}")


if __name__ == "__main__":
    main()
