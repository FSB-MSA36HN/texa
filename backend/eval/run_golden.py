"""Live golden evaluation against the connected model.

uv run python eval/run_golden.py [--runs 3] [--model gemini-...] [--only id1,id2]
Prints per-case pass rates, unstable cases and overall accuracy; exits 1 below --gate (default 0.9).
"""
import argparse
import time
from collections import defaultdict
from pathlib import Path

import yaml

from texa import answer, db

CASES = yaml.safe_load((Path(__file__).with_name("golden.yaml")).read_text(encoding="utf-8"))


def wait(turn_id):
    while not answer.RUNS[turn_id].done:
        time.sleep(0.2)
    return answer.load_turn(turn_id)


def score(case: dict, turn: dict) -> list[str]:
    """Problems with a turn; empty means pass."""
    exp, st = case["expect"], turn["state"]
    spec = st.get("query_spec") or {}
    problems = []
    if exp.get("status") and turn["status"] != exp["status"]:
        problems.append(f"status {turn['status']} != {exp['status']} ({st.get('message') or (st.get('error') or {}).get('message', '')})")
        return problems
    if turn["status"] == "needs_clarification":
        asked = {f["id"] for f in st["form"]["fields"]}
        if exp.get("ask") and not set(exp["ask"]) <= asked:
            problems.append(f"asked {sorted(asked)}, expected {exp['ask']}")
        return problems
    if not spec:
        return problems
    if "recipe" in exp and spec.get("recipe") != exp["recipe"]:
        problems.append(f"recipe {spec.get('recipe')!r} != {exp['recipe']!r}")
    if "recipe_in" in exp and spec.get("recipe") not in exp["recipe_in"]:
        problems.append(f"recipe {spec.get('recipe')!r} not in {exp['recipe_in']}")
    for key in ("metrics", "selection", "source_ids"):
        if key in exp and sorted(spec.get(key) or []) != sorted(exp[key]):
            problems.append(f"{key} {spec.get(key)} != {exp[key]}")
    for f in exp.get("filters", []):
        got = next((g for g in spec.get("filters", []) if g["field"] == f["field"]), None)
        if got is None or sorted(v.lower() for v in got["values"]) != sorted(v.lower() for v in f["values"]):
            problems.append(f"filter {f} not found in {spec.get('filters')}")
    tr = spec.get("time_range") or {}
    for key, field in (("time_kind", "kind"), ("days", "days"), ("start", "start"), ("end", "end")):
        if key in exp and str(tr.get(field)) != str(exp[key]):
            problems.append(f"time_range.{field} {tr.get(field)} != {exp[key]}")
    return problems


def run_case(case: dict, model: str | None) -> list[str]:
    conversation_id = None
    for q in case.get("previous", []):
        ids = answer.ask(q, conversation_id, model, None)
        conversation_id = ids["conversation_id"]
        wait(ids["turn_id"])
    ids = answer.ask(case["question"], conversation_id, model, None)
    turn = wait(ids["turn_id"])
    with db.app_conn() as conn:  # eval conversations are not user history
        conn.execute("DELETE FROM app.conversations WHERE id = %s", (ids["conversation_id"],))
    return score(case, turn)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--model")
    p.add_argument("--only")
    p.add_argument("--gate", type=float, default=0.9)
    args = p.parse_args()
    db.migrate()
    cases = [c for c in CASES if not args.only or c["id"] in args.only.split(",")]
    results = defaultdict(list)
    for r in range(args.runs):
        for case in cases:
            problems = run_case(case, args.model)
            results[case["id"]].append(problems)
            print(f"[run {r + 1}] {'PASS' if not problems else 'FAIL'} {case['id']}" + ("" if not problems else f": {'; '.join(problems)}"))
    total = sum(len(v) for v in results.values())
    passed = sum(1 for v in results.values() for p in v if not p)
    unstable = [cid for cid, v in results.items() if 0 < sum(1 for p in v if not p) < len(v)]
    print(f"\naccuracy {passed}/{total} = {passed / total:.1%}" + (f" · unstable: {', '.join(unstable)}" if unstable else ""))
    raise SystemExit(0 if passed / total >= args.gate else 1)


if __name__ == "__main__":
    main()
