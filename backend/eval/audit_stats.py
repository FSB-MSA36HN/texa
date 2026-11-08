"""Agreement statistics for the two blind research_v4 audit sheets.

  python backend/eval/audit_stats.py data/benchmark/research_v4/AUDIT_A.csv data/benchmark/research_v4/AUDIT_B.csv

Reports percent agreement, Cohen's kappa over {correct, ambiguous, wrong}, and the share of audited cases that at
least one reviewer did not mark "correct" (a gold-problem rate) with a 95% Wilson interval. Exits non-zero while
either sheet has an empty or invalid verdict.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
import math
from pathlib import Path

LABELS = ("correct", "ambiguous", "wrong")


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, centre - half), min(1.0, centre + half))


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[label] * cb[label] for label in LABELS) / (n * n)
    if expected == 1:
        return None  # both reviewers used one label for everything: kappa is undefined
    return (observed - expected) / (1 - expected)


def load(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        verdicts = {row["id"]: row["verdict"].strip().lower() for row in csv.DictReader(handle)}
    bad = {k: v for k, v in verdicts.items() if v not in LABELS}
    if bad:
        raise ValueError(f"{path.name}: {len(bad)} rows have an empty or invalid verdict, e.g. {dict(list(bad.items())[:3])}")
    return verdicts


def summarize(first: dict[str, str], second: dict[str, str]) -> dict:
    if set(first) != set(second):
        raise ValueError("the two sheets do not cover the same cases")
    ids = sorted(first)
    a, b = [first[i] for i in ids], [second[i] for i in ids]
    flagged = sum(x != "correct" or y != "correct" for x, y in zip(a, b))
    both_wrong = sum(x == "wrong" and y == "wrong" for x, y in zip(a, b))
    low, high = wilson(flagged, len(ids))
    return {"cases": len(ids), "percent_agreement": sum(x == y for x, y in zip(a, b)) / len(ids),
            "cohen_kappa": cohen_kappa(a, b), "flagged_by_either": flagged, "flagged_rate": flagged / len(ids),
            "flagged_rate_wilson95": [low, high], "wrong_by_both": both_wrong,
            "disagreements_to_adjudicate": [i for i, x, y in zip(ids, a, b) if x != y]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sheet_a", type=Path)
    ap.add_argument("sheet_b", type=Path)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    try:
        result = summarize(load(args.sheet_a), load(args.sheet_b))
    except ValueError as exc:
        print(f"not ready: {exc}")
        return 1
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
