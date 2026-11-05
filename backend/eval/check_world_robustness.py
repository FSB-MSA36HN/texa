"""Check frozen candidate SQL across authored fixture worlds (no model calls)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

try:
    from .benchmark import ROOT, execute_readonly, results_equal, score_business_result
except ImportError:
    from benchmark import ROOT, execute_readonly, results_equal, score_business_result

DATA = ROOT / "data/benchmark/challenge_v1"
WORLDS = ("base", "grain_counterexample", "coverage_edge")


def _identity(dsn: str, *, require_owner: bool) -> tuple[str, int, str, bool]:
    import psycopg
    with psycopg.connect(dsn) as conn:
        db, port, user, superuser = conn.execute(
            "SELECT current_database(), inet_server_port(), current_user, r.rolsuper "
            "FROM pg_roles r WHERE r.rolname=current_user").fetchone()
    if db != "texa_benchmark" or port != 15433:
        raise ValueError("world robustness is restricted to texa_benchmark on isolated port 15433")
    if require_owner and not superuser:
        # Fixture scripts replace only challenge source rows and vocabulary. Require a role
        # authorized to perform that scoped operation, but never require superuser.
        pass
    if not require_owner and superuser:
        raise ValueError("query/reader DSN must use a non-superuser role")
    return db, port, user, superuser


def _apply_world(owner_dsn: str, world_path: Path) -> None:
    import psycopg
    _identity(owner_dsn, require_owner=True)
    script = world_path.read_text(encoding="utf-8")
    if not script.strip() or not re.search(r"DELETE\s+FROM\s+analytics\.event_activity", script, re.I):
        raise ValueError("world fixture lacks the scoped challenge-row replacement")
    if not re.search(r"source_id\s+IN\s*\(\s*'cosmetics_shop'\s*,\s*'olist_marketplace'\s*\)", script, re.I):
        raise ValueError("world fixture replacement is not scoped to the two challenge sources")
    with psycopg.connect(owner_dsn, autocommit=False) as conn:
        with conn.transaction():
            # Whole world SQL is a project-authored fixture, not caller-provided SQL.
            conn.execute(script)


def _candidate_sql(record: dict[str, Any]) -> list[str]:
    found = []
    if isinstance(record.get("sql"), str) and record["sql"].strip():
        found.append(record["sql"])
    for turn in record.get("turns") or []:
        if isinstance(turn.get("sql"), str) and turn["sql"].strip():
            found.append(turn["sql"])
        trace = turn.get("trace") or {}
        sql = trace.get("compiled_sql")
        if isinstance(sql, str) and sql.strip():
            found.append(sql)
    if not found:
        for trace in record.get("interpretation_traces") or []:
            if isinstance(trace.get("compiled_sql"), str) and trace["compiled_sql"].strip():
                found.append(trace["compiled_sql"])
    return found


def _load_cases(path: Path) -> dict[str, dict]:
    rows = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {row["id"]: row for row in rows}


def _load_runs(paths: list[Path]) -> tuple[list[dict], dict[str, dict]]:
    cases = _load_cases(DATA / "cases.yaml")
    runs = []
    for path in paths:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(records) < 3 or records[0].get("type") != "run_manifest" or records[-1].get("type") != "run_complete":
            raise ValueError(f"{path}: incomplete run rejected")
        manifest = records[0]
        if manifest.get("suite") != "single" or manifest.get("split") not in {"dev", "test"}:
            raise ValueError(f"{path}: robustness checker accepts single-suite runs only")
        rows = records[1:-1]
        if any(row.get("type") != "scenario" for row in rows):
            raise ValueError(f"{path}: non-scenario record found before completion")
        ids = [r.get("id") for r in rows]
        expected = manifest.get("expected_ids")
        if not isinstance(expected, list) or not expected or len(expected) != len(set(expected)):
            raise ValueError(f"{path}: invalid expected_ids")
        if len(ids) != len(set(ids)) or set(ids) != set(map(str, expected)):
            raise ValueError(f"{path}: scenario coverage mismatch")
        if records[-1].get("scenarios") != len(rows):
            raise ValueError(f"{path}: completion count mismatch")
        runs.append({"path": path, "manifest": manifest, "rows": rows})
    return runs, cases


def _validate_provenance(runs: list[dict], cases: dict[str, dict]) -> None:
    base = runs[0]["manifest"]
    run_worlds = set()
    world_pools = base.get("world_pool_ids")
    if not isinstance(world_pools, dict) or set(world_pools) != set(WORLDS):
        raise ValueError("run manifest must pin the complete world_pool_ids mapping")
    shared_provenance = {k: v for k, v in (base.get("provenance") or {}).items() if k != "public_context_hash"}
    for run in runs:
        m = run["manifest"]
        if m.get("variant") != base.get("variant") or m.get("split") != base.get("split") or m.get("repeat") != base.get("repeat"):
            raise ValueError("robustness inputs must be one matched variant/split/repeat across all worlds")
        if m.get("model") != base.get("model") or {k: v for k, v in (m.get("provenance") or {}).items()
                if k != "public_context_hash"} != shared_provenance:
            raise ValueError("runs differ in model or frozen implementation/data provenance")
        world = m.get("fixture_world")
        if world not in WORLDS:
            raise ValueError("run manifest has unknown fixture_world")
        if world in run_worlds:
            raise ValueError(f"duplicate source run for fixture world {world}")
        run_worlds.add(world)
        if m.get("world_pool_ids") != world_pools:
            raise ValueError("runs disagree on frozen world_pool_ids")
        expected_ids = set(world_pools.get(world, []))
        if set(map(str, m.get("expected_ids", []))) != expected_ids:
            raise ValueError(f"{world}: run does not match the frozen case pool")
    declared_ids = {cid for world in WORLDS for cid in world_pools.get(world, [])}
    actual_ids = {cid for cid, case in cases.items() if case.get("split") == base["split"]}
    if declared_ids != actual_ids:
        raise ValueError("world_pool_ids do not cover the complete frozen split")
    for world in WORLDS:
        rel = f"worlds/{world}.sql"
        expected_hash = hashlib.sha256((DATA / rel).read_bytes()).hexdigest()
        for run in runs:
            hashes = run["manifest"].get("provenance", {}).get("dataset_hashes", {})
            if hashes.get(rel) != expected_hash:
                raise ValueError(f"{world}: run does not pin the current fixture SQL hash")


def check_worlds(runs: list[dict], cases: dict[str, dict], reader_dsn: str,
                 *, apply_fixtures: bool, owner_dsn: str | None = None,
                 apply_world=_apply_world, execute=execute_readonly) -> dict[str, Any]:
    _validate_provenance(runs, cases)
    _identity(reader_dsn, require_owner=False)
    if not apply_fixtures:
        raise ValueError("cross-world scoring requires explicit --apply-isolated-fixtures confirmation")
    if apply_fixtures:
        if not owner_dsn:
            raise ValueError("--apply-isolated-fixtures requires --owner-dsn")
        _identity(owner_dsn, require_owner=True)
    worlds_to_runs = {r["manifest"]["fixture_world"]: r for r in runs}
    output_rows = []
    observations: dict[str, dict[str, tuple[tuple, list[tuple]] | None]] = {}
    base_run = worlds_to_runs["base"]
    base_records = {r["id"]: r for r in base_run["rows"]}
    candidates = {}
    for run in runs:
        for record in run["rows"]:
            candidates.setdefault(record["id"], record)
    all_ids = sorted(candidates)
    try:
        for world in WORLDS:
            if apply_fixtures:
                world_path = DATA / "worlds" / f"{world}.sql"
                apply_world(owner_dsn, world_path)
            for case_id in all_ids:
                case = cases[case_id]
                record = candidates[case_id]
                sqls = _candidate_sql(record)
                expected = case.get("expected_results_by_world", {}).get(world)
                result_row = {"id": case_id, "world": world, "sql_count": len(sqls),
                              "primary_base_correct": None, "world_correct": False,
                              "accidental_same_result_counts": False}
                if not sqls:
                    result_row.update(status="no_candidate_sql", world_correct=False)
                    output_rows.append(result_row)
                    observations.setdefault(case_id, {})[world] = None
                    continue
                if not isinstance(expected, dict) or "columns" not in expected or "rows" not in expected:
                    raise ValueError(f"{case_id}: missing independent expected_results_by_world[{world}]")
                sql_scores = []
                actual_results = []
                for sql in sqls:
                    try:
                        cols, values = execute(reader_dsn, sql)
                        actual_results.append((tuple(cols), [tuple(row) for row in values]))
                        score = score_business_result(cols, values, expected["columns"], expected["rows"],
                            ordered=bool(case.get("ordered")), contract=case.get("business_contract"))
                        sql_scores.append(bool(score["business_result_correct"]))
                    except Exception as exc:
                        result_row["error_class"] = type(exc).__name__
                        sql_scores.append(False)
                result_row["world_correct"] = all(sql_scores)
                result_row["status"] = "scored" if sql_scores else "execution_error"
                observations.setdefault(case_id, {})[world] = actual_results[0] if actual_results else None
                if world == "base":
                    result_row["primary_base_correct"] = result_row["world_correct"]
                output_rows.append(result_row)
    finally:
        if apply_fixtures and owner_dsn:
            apply_world(owner_dsn, DATA / "worlds/base.sql")
    result_lookup = {(row["id"], row["world"]): row for row in output_rows}
    for case_id, world_values in observations.items():
        case = cases[case_id]
        base_expected = case.get("expected_results_by_world", {}).get("base")
        base_actual = world_values.get("base")
        if not base_expected or not base_actual:
            continue
        for world in WORLDS:
            if world == "base" or world not in world_values or world_values[world] is None:
                continue
            current_expected = case.get("expected_results_by_world", {}).get(world)
            actual = world_values[world]
            if not current_expected:
                continue
            intended_world_change = not score_business_result(base_expected["columns"], base_expected["rows"],
                current_expected["columns"], current_expected["rows"], ordered=bool(case.get("ordered")),
                contract=case.get("business_contract"))["business_result_correct"]
            same_as_base_output = results_equal(actual[0], actual[1], base_actual[0], base_actual[1],
                                                ordered=bool(case.get("ordered")))
            if intended_world_change and same_as_base_output and not result_lookup[(case_id, world)]["world_correct"]:
                result_lookup[(case_id, world)]["accidental_same_result_counts"] = True
    summary = {world: {"cases": sum(r["world"] == world for r in output_rows),
                       "correct": sum(r["world"] == world and r["world_correct"] for r in output_rows),
                       "missing_sql": sum(r["world"] == world and r["status"] == "no_candidate_sql" for r in output_rows)}
               for world in WORLDS}
    return {"type": "world_robustness", "variant": base_run["manifest"]["variant"],
            "split": base_run["manifest"]["split"], "repeat": base_run["manifest"]["repeat"],
            "summary": summary, "cases": output_rows,
            "provenance": {"run_files": [str(r["path"]) for r in runs],
                "world_hashes": {r["manifest"]["fixture_world"]: r["manifest"]["fixture_hash"] for r in runs},
                "case_hash": hashlib.sha256((DATA / "cases.yaml").read_bytes()).hexdigest()}}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--reader-dsn", default=os.environ.get("TEXA_BENCHMARK_DSN"))
    parser.add_argument("--owner-dsn", default=os.environ.get("TEXA_DB_DSN"))
    parser.add_argument("--apply-isolated-fixtures", action="store_true",
                        help="replace only challenge rows in texa_benchmark on isolated port 15433, then restore base")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not args.reader_dsn:
        parser.error("--reader-dsn or TEXA_BENCHMARK_DSN is required")
    try:
        runs, cases = _load_runs([p.resolve() for p in args.runs])
        result = check_worlds(runs, cases, args.reader_dsn, apply_fixtures=args.apply_isolated_fixtures,
                              owner_dsn=args.owner_dsn)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        if args.output:
            path = args.output.resolve(); path.relative_to(ROOT)
            with path.open("x", encoding="utf-8") as handle:
                handle.write(rendered + "\n")
        print(rendered)
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
