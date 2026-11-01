"""Small, frozen Text-to-SQL benchmark utilities.

The benchmark is deliberately independent of Texa's QuerySpec/compiler. Gold SQL
and data are kept under data/benchmark; this module only loads, executes and scores.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "data" / "benchmark" / "manifest.yaml"
CASES_PATH = ROOT / "data" / "benchmark" / "cases.yaml"
FIXTURE_PATH = ROOT / "data" / "benchmark" / "fixture.sql"
ABS_TOL = 1e-6
REL_TOL = 1e-6


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("benchmark cases must be a YAML list")
    ids = [case.get("id") for case in cases]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("benchmark case IDs must be non-empty and unique")
    for case in cases:
        if case.get("split") not in {"dev", "test"}:
            raise ValueError(f"{case['id']}: split must be dev or test")
        if not case.get("family") or not case.get("gold_sql"):
            raise ValueError(f"{case['id']}: family and gold_sql are required")
    return cases


def validate_split_is_family_disjoint(cases: Iterable[dict[str, Any]]) -> None:
    splits: dict[str, set[str]] = {}
    for case in cases:
        splits.setdefault(case["split"], set()).add(case["family"])
    overlap = splits.get("dev", set()) & splits.get("test", set())
    if overlap:
        raise ValueError(f"scenario families cross dev/test: {sorted(overlap)}")


def _same_value(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float, Decimal)) and not isinstance(a, bool) and isinstance(b, (int, float, Decimal)) and not isinstance(b, bool):
        af, bf = float(a), float(b)
        if math.isnan(af) or math.isnan(bf):
            return math.isnan(af) and math.isnan(bf)
        return math.isclose(af, bf, rel_tol=REL_TOL, abs_tol=ABS_TOL)
    if hasattr(a, "isoformat") or hasattr(b, "isoformat"):
        left = a.isoformat() if hasattr(a, "isoformat") else a
        right = b.isoformat() if hasattr(b, "isoformat") else b
        return left == right
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same_value(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same_value(x, y) for x, y in zip(a, b))
    return a == b


def _row_equal(a: tuple[Any, ...], b: tuple[Any, ...]) -> bool:
    return len(a) == len(b) and all(_same_value(x, y) for x, y in zip(a, b))


def results_equal(
    actual_columns: Iterable[str], actual_rows: Iterable[Iterable[Any]],
    expected_columns: Iterable[str], expected_rows: Iterable[Iterable[Any]], *, ordered: bool = False,
) -> bool:
    """Compare complete result sets, retaining duplicate rows and NULLs.

    Column order is significant. Rows are compared as multisets unless the case
    explicitly requires SQL ordering (e.g. top-k/ranking).
    """
    ac, ec = tuple(actual_columns), tuple(expected_columns)
    if ac != ec:
        return False
    ar = [tuple(r) for r in actual_rows]
    er = [tuple(r) for r in expected_rows]
    if len(ar) != len(er):
        return False
    if ordered:
        return all(_row_equal(a, e) for a, e in zip(ar, er))
    unmatched = list(er)
    for row in ar:
        index = next((i for i, expected in enumerate(unmatched) if _row_equal(row, expected)), None)
        if index is None:
            return False
        unmatched.pop(index)
    return not unmatched


def execute_readonly(dsn: str, sql: str, *, timeout_ms: int = 5000, max_rows: int = 10000):
    """Execute one SELECT in a read-only transaction and reject truncated results.

    A dedicated read-only role is required as a second boundary. The evaluator
    refuses non-SELECT top-level statements, sets server limits, and fetches at
    most max_rows+1 so correctness is never scored on a silently truncated set.
    """
    import psycopg
    from psycopg.rows import tuple_row

    stripped = sql.lstrip()
    if not stripped[:6].lower() == "select" and not stripped[:4].lower() == "with":
        raise ValueError("only SELECT or WITH queries are allowed")
    # A single statement only. This lexical guard is defense in depth; the DB
    # read-only role and transaction are the actual write-protection boundary.
    if ";" in stripped.rstrip().rstrip(";"):
        raise ValueError("multiple SQL statements are not allowed")
    with psycopg.connect(dsn, autocommit=False, row_factory=tuple_row) as conn:
        with conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            identity = conn.execute("SELECT current_database(), current_user, r.rolsuper "
                                    "FROM pg_roles r WHERE r.rolname=current_user").fetchone()
            if not identity or identity[0] != "texa_benchmark":
                raise ValueError("benchmark execution is restricted to database texa_benchmark")
            if identity[2]:
                raise ValueError("benchmark query role must not be a PostgreSQL superuser")
            conn.execute("SELECT set_config('statement_timeout', %s, true)", (f"{timeout_ms}ms",))
            conn.execute("SELECT set_config('idle_in_transaction_session_timeout', %s, true)",
                         (f"{timeout_ms + 1000}ms",))
            cur = conn.execute(sql)
            columns = tuple(d.name for d in cur.description or ())
            rows = cur.fetchmany(max_rows + 1)
            if len(rows) > max_rows:
                raise ValueError(f"result exceeds evaluator limit of {max_rows} rows")
            return columns, rows


def score_sql(dsn: str, sql: str, case: dict[str, Any], *, timeout_ms: int = 5000, max_rows: int = 10000) -> dict[str, Any]:
    try:
        actual = execute_readonly(dsn, sql, timeout_ms=timeout_ms, max_rows=max_rows)
        expected = execute_readonly(dsn, case["gold_sql"], timeout_ms=timeout_ms, max_rows=max_rows)
        return {"status": "ok", "result_correct": results_equal(*actual, *expected, ordered=bool(case.get("ordered"))),
                "columns": list(actual[0]), "row_count": len(actual[1])}
    except Exception as exc:
        return {"status": "error", "result_correct": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def score_result(dsn: str, columns: Iterable[str], rows: Iterable[Iterable[Any]], case: dict[str, Any], *,
                 timeout_ms: int = 5000, max_rows: int = 10000) -> dict[str, Any]:
    try:
        actual_columns = tuple(columns)
        actual_rows = [tuple(r) for r in rows]
        if len(actual_rows) > max_rows:
            raise ValueError(f"result exceeds evaluator limit of {max_rows} rows")
        expected_columns, expected_rows = execute_readonly(dsn, case["gold_sql"], timeout_ms=timeout_ms, max_rows=max_rows)
        correct = results_equal(actual_columns, actual_rows, expected_columns, expected_rows, ordered=bool(case.get("ordered")))
        return {"status": "ok", "result_correct": correct, "columns": list(actual_columns), "row_count": len(actual_rows)}
    except Exception as exc:
        return {"status": "error", "result_correct": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def score_expected_result(dsn: str, sql: str, expected: dict[str, Any]) -> dict[str, Any]:
    """Check a frozen gold query against independently annotated pilot rows."""
    try:
        columns, rows = execute_readonly(dsn, sql)
        correct = results_equal(columns, rows, expected["columns"], expected["rows"],
                                ordered=bool(expected.get("ordered")))
        return {"status": "ok", "result_correct": correct, "columns": list(columns), "row_count": len(rows)}
    except Exception as exc:
        return {"status": "error", "result_correct": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}


def paired_delta_bootstrap(left: dict[str, bool], right: dict[str, bool], *, iterations: int = 5000,
                           seed: int = 731904, strata: dict[str, str] | None = None) -> dict[str, float | int]:
    """Paired delta; resample whole labeled scenario-family/dialogue clusters."""
    import random
    if iterations < 1:
        raise ValueError("iterations must be positive")
    if set(left) != set(right):
        raise ValueError("paired results must contain exactly the same case IDs")
    ids = sorted(left)
    if not ids:
        raise ValueError("paired results are empty")
    delta = sum(int(right[i]) - int(left[i]) for i in ids) / len(ids)
    strata = strata or {i: "all" for i in ids}
    if set(strata) != set(ids):
        raise ValueError("bootstrap strata must label every paired case exactly once")
    groups: dict[str, list[str]] = {}
    for case_id in ids:
        groups.setdefault(strata[case_id], []).append(case_id)
    rng = random.Random(seed)
    samples = []
    clusters = list(groups.values())
    for _ in range(iterations):
        sampled = [rng.choice(clusters) for _ in clusters]
        sample = [case_id for cluster in sampled for case_id in cluster]
        samples.append(sum(int(right[i]) - int(left[i]) for i in sample) / len(sample))
    samples.sort()
    return {"n": len(ids), "strata": len(groups), "delta": delta, "ci95_low": samples[int(0.025 * (iterations - 1))],
            "ci95_high": samples[int(0.975 * (iterations - 1))]}


def dialogue_scores(gold: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    """Score annotated dialogue state without conflating missing values and nulls."""
    slots = ("metric", "time_range", "filters", "breakdown", "referenced_turn")
    correct = {slot: actual.get(slot) == gold.get(slot) for slot in slots if slot in gold}
    contaminated = any(
        bool(actual.get(k)) and not bool(gold.get(k))
        for k in ("filters", "breakdown")
    )
    return {"slot_correct": correct, "state_exact": bool(correct) and all(correct.values()),
            "contamination": contaminated}


def write_result(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")


def server_metadata(dsn: str) -> dict[str, str]:
    import psycopg
    with psycopg.connect(dsn, autocommit=True) as conn:
        row = conn.execute("SELECT current_database(), current_user, current_setting('server_version')").fetchone()
    if row[0] != "texa_benchmark":
        raise ValueError("benchmark metadata is restricted to database texa_benchmark")
    return {"database": row[0], "role": row[1], "postgresql_version": row[2]}
