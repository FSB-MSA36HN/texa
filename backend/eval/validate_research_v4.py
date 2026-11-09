"""Validate research_v4 gold three ways, and fail on any disagreement.

1. The stored expected tables equal a fresh computation by the raw-CSV oracle (oracle_csv.py). This catches
   tampering with cases.yaml and drift in the CSV files.
2. The gold SQL run on the ETL-loaded PostgreSQL warehouse returns the oracle's table (benchmark.results_equal,
   ordering only where the case requires it). This checks the ETL mapping and the SQL against the raw data.
3. Structural gates: dev/test families disjoint, ids/questions/SQL/result tables unique, no empty or all-zero gold,
   and metamorphic relations hold on the gold (see backend/tests/test_oracle_csv.py for the oracle-level versions).

The default run only reads. --load-world replays worlds/real.sql into the database first, and is refused unless the
database is named texa_benchmark.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess

import psycopg
import yaml

try:  # imported as a package by the tests, run as a script otherwise
    from .benchmark import results_equal, validate_split_is_family_disjoint
    from .oracle_csv import RawOracle
except ImportError:
    from benchmark import results_equal, validate_split_is_family_disjoint
    from oracle_csv import RawOracle

ROOT = Path(__file__).resolve().parents[2]


def structural_errors(cases):
    errors = []
    try:
        validate_split_is_family_disjoint(cases)
    except ValueError as exc:
        errors.append(str(exc))
    for field in ("id", "question", "gold_sql"):
        dupes = [k for k, n in Counter(c[field] for c in cases).items() if n > 1]
        if dupes:
            errors.append(f"duplicate {field}: {dupes[:3]}")
    tables = Counter(json.dumps([c["expected_result"]["columns"], c["expected_result"]["rows"]], sort_keys=True) for c in cases)
    if any(n > 1 for n in tables.values()):
        errors.append(f"{sum(n > 1 for n in tables.values())} result tables are used by more than one case")
    for c in cases:
        rows = c["expected_result"]["rows"]
        if not rows or all(r[-1] in (0, None) for r in rows):
            errors.append(f"{c['id']}: empty or all-zero gold")
    return errors


def validate_load_target(database_name: str, isolated_run: bool) -> None:
    """Guard the destructive COPY replay to the legacy benchmark DB or explicit run-owned DBs."""
    if database_name == "texa_benchmark" and not isolated_run:
        raise SystemExit("refusing to load a world into the shared legacy database without --isolated-run")
    if not isolated_run and database_name != "texa_benchmark":
        raise SystemExit("refusing to load a world outside texa_benchmark; pass --isolated-run for a dedicated run DB")
    if isolated_run and not database_name.startswith("texa_bench_run_"):
        raise SystemExit("--isolated-run only permits database names beginning texa_bench_run_")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-dir", type=Path, default=ROOT / "data/benchmark/research_v4")
    ap.add_argument("--dsn", default=os.environ.get("TEXA_DB_DSN"), required=not os.environ.get("TEXA_DB_DSN"))
    ap.add_argument("--landing", type=Path, default=ROOT / "data/landing")
    ap.add_argument("--load-world", action="store_true")
    ap.add_argument("--isolated-run", action="store_true",
                    help="allow COPY replay only into a dedicated texa_bench_run_* database")
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    directory = args.dataset_dir.resolve()
    cases = yaml.safe_load((directory / "cases.yaml").read_text(encoding="utf-8"))
    manifest = yaml.safe_load((directory / "manifest.yaml").read_text(encoding="utf-8"))

    oracle = RawOracle(args.landing)
    errors = [{"check": "structure", "error": e} for e in structural_errors(cases)]
    if oracle.raw_file_hashes() != manifest["raw_data_sha256"]:
        errors.append({"check": "raw_data", "error": "CSV files differ from the hashes frozen in manifest.yaml"})

    with psycopg.connect(args.dsn, autocommit=True) as conn:
        if args.load_world:
            validate_load_target(conn.execute("select current_database()").fetchone()[0], args.isolated_run)
            world = directory / manifest["fixture_worlds"]["real"]["file"]
            expected_hash = (world.parent / "real.sha256").read_text().split()[0]
            if hashlib.sha256(world.read_bytes()).hexdigest() != expected_hash:
                raise SystemExit("worlds/real.sql does not match worlds/real.sha256; re-run export_world.py")
            # The world uses COPY ... FROM stdin blocks, which only psql can replay (as run_research_matrix.py does).
            subprocess.run(["psql", args.dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(world)], check=True)
        for case in cases:
            expected = case["expected_result"]
            fresh = oracle.evaluate(case["source_id"], case["metric"], *_spec_of(case))
            if not results_equal(fresh["columns"], fresh["rows"], expected["columns"], expected["rows"], ordered=case["ordered"]):
                errors.append({"check": "stored_vs_oracle", "id": case["id"]})
            try:
                with conn.transaction():
                    conn.execute("SET TRANSACTION READ ONLY")
                    conn.execute("SET LOCAL statement_timeout = '30s'")
                    cur = conn.execute(case["gold_sql"])
                    columns = [d.name for d in cur.description]
                    rows = [list(r) for r in cur.fetchall()]
                if not results_equal(columns, rows, fresh["columns"], fresh["rows"], ordered=case["ordered"]):
                    errors.append({"check": "sql_vs_oracle", "id": case["id"], "question": case["question"],
                                   "sql_rows": rows[:5], "oracle_rows": fresh["rows"][:5]})
            except Exception as exc:  # noqa: BLE001 - report every failing case
                errors.append({"check": "sql_error", "id": case["id"], "error": f"{type(exc).__name__}: {str(exc)[:200]}"})

    result = {"cases": len(cases), "errors": len(errors), "human_review": manifest["human_review"], "sealed": manifest["sealed"]}
    if args.output:
        args.output.write_text(json.dumps({**result, "details": errors}, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({**result, "first_errors": errors[:8]}, ensure_ascii=False, default=str))
    return 1 if errors else 0


def _spec_of(case):
    """Recover (where, group, limit, order_by) from the stored case; they are stored with the generator's spec."""
    return case["spec"]["where"], case["spec"]["group"], case["spec"]["limit"], case["spec"]["order_by"]


if __name__ == "__main__":
    raise SystemExit(main())
