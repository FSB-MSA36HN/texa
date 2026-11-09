"""Resumable, globally bounded runner for the eight research_v4 single-test variants.

The manager checkpoints one case at a time in SQLite. Each attempt is an isolated evaluator process
and JSONL artifact; completed cases survive interruption and are never silently rerun. Credentials and
gateway accounting remain delegated to run_gateway_check.py.

Example:
  python backend/eval/run_research_manager.py --run-dir backend/eval/results/v4-2026-11-09 --workers 2
  python backend/eval/run_research_manager.py --run-dir backend/eval/results/v4-2026-11-09 --resume --workers 2
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import socket
import threading
import time
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/benchmark/research_v4"
PYTHON = ROOT / "backend/.venv/bin/python"
PGCTL = ROOT / ".runtime/pgtools/pgserver/pginstall/bin/pg_ctl"
PG_BIN = PGCTL.parent
INITDB = PG_BIN / "initdb"
PSQL = PG_BIN / "psql"
CREATEDB = PG_BIN / "createdb"
PGPORT = 15433
VARIANTS = ("B0", "B0R", "B0G", "B0GR", "T00", "T10", "T01", "T11")
RETRYABLE = {"APIConnectionError", "APITimeoutError", "RateLimitError", "InternalServerError",
             "GatewayBudgetRequestError", "TimeoutException", "ConnectError", "ReadTimeout"}
HALT_ERRORS = {"AuthenticationError", "PermissionDeniedError", "BadRequestError", "GatewayBudgetRequestError"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shell(argv: list[Any], env: dict[str, str], *, capture=False):
    return subprocess.run([str(x) for x in argv], cwd=ROOT, env=env, check=True,
                          capture_output=capture, text=capture)


def case_ids() -> list[str]:
    cases = yaml.safe_load((DATA / "cases.yaml").read_text(encoding="utf-8"))
    ids = [row["id"] for row in cases if row.get("split") == "test" and row.get("fixture_world", "base") == "real"]
    if len(ids) != 200 or len(set(ids)) != 200:
        raise RuntimeError(f"expected 200 unique v4 test cases, found {len(ids)}")
    return ids


def frozen_config(workers: int, max_attempts: int) -> dict[str, Any]:
    manifest = yaml.safe_load((DATA / "manifest.yaml").read_text(encoding="utf-8"))
    if manifest.get("version") != 4 or manifest.get("sealed") is not False:
        raise RuntimeError("manager is restricted to the current unsealed research_v4 candidate")
    world = DATA / manifest["fixture_worlds"]["real"]["file"]
    digest_file = world.parent / "real.sha256"
    if not world.is_file() or not digest_file.is_file():
        raise RuntimeError("research_v4/worlds/real.sql is missing; run ETL and export_world.py first")
    expected_hash = digest_file.read_text().split()[0]
    if sha256(world) != expected_hash:
        raise RuntimeError("research_v4 real.sql hash does not match real.sha256")
    frozen_inputs = ["backend/eval/run_research_manager.py", "backend/eval/run_accuracy_study.py",
                     "backend/eval/run_gateway_check.py", "backend/eval/report_accuracy_study.py",
                     "backend/eval/benchmark.py", "backend/texa/llm.py", "backend/texa/interpret.py",
                     "backend/texa/answer.py", "backend/texa/compile.py", "backend/texa/examples.py",
                     "backend/texa/consistency.py", "catalog/product_events.yaml",
                     "catalog/verified_examples.yaml", "data/benchmark/research_v4/manifest.yaml",
                     "data/benchmark/research_v4/cases.yaml", "data/benchmark/research_v4/GLOSSARY.md"]
    credentials_path = ROOT / ".runtime/class-demo-gateway.json"
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    if not all(credentials.get(key) for key in ("model", "base_url", "api_key", "max_usd")):
        raise RuntimeError("protected gateway credentials lack required model, endpoint, key, or budget fields")
    return {
        "dataset": str(DATA.relative_to(ROOT)), "dataset_manifest_sha256": sha256(DATA / "manifest.yaml"),
        "cases_sha256": sha256(DATA / "cases.yaml"), "world_sha256": expected_hash,
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "frozen_inputs_sha256": {path: sha256(ROOT / path) for path in frozen_inputs},
        "suite": "single", "split": "test", "world": "real", "repeat": 1,
        "variants": list(VARIANTS), "expected_cases": 200, "expected_jobs": 1600,
        "global_workers": workers, "max_attempts": max_attempts,
        "model": credentials["model"], "base_url": credentials["base_url"],
        "authorized_max_usd": float(credentials["max_usd"]),
        "credentials_fingerprint": hashlib.sha256(credentials["api_key"].encode()).hexdigest(),
    }


def connect(db_path: Path):
    db = sqlite3.connect(db_path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS jobs (
        variant TEXT NOT NULL, case_id TEXT NOT NULL, status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, output_path TEXT, error TEXT, updated_at TEXT NOT NULL,
        PRIMARY KEY (variant, case_id))""")
    db.commit()
    return db


def valid_case_output(path: Path, case_id: str) -> dict[str, Any] | None:
    try:
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len(records) != 3 or records[0].get("type") != "run_manifest" or records[-1].get("type") != "run_complete":
            return None
        row = records[1]
        if row.get("type") != "scenario" or row.get("id") != case_id or records[-1].get("scenarios") != 1:
            return None
        return {"manifest": records[0], "row": row}
    except (OSError, ValueError, IndexError):
        return None


def prepare_db(env: dict[str, str]) -> None:
    dsn = env["TEXA_DB_DSN"]
    shell([PSQL, dsn, "-X", "-v", "ON_ERROR_STOP=1", "-f", ROOT / "pipeline/sql/init/01_init.sql"], env)
    shell([PYTHON, "-c", "from texa import db; db.migrate()"], env, capture=True)
    # Validation replays the frozen real world into texa_benchmark and checks every gold against
    # both a fresh CSV oracle and PostgreSQL before any paid model request is allowed.
    shell([PYTHON, ROOT / "backend/eval/validate_research_v4.py", "--dsn", dsn,
           "--load-world", "--isolated-run"], env)
    shell([PYTHON, "-c", "from texa import catalog; print(catalog.publish())"], env, capture=True)


def database_name_for_run(run_dir: Path) -> str:
    relative = str(run_dir.resolve().relative_to(ROOT))
    suffix = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]
    return f"texa_bench_run_{suffix}"


def ensure_isolated_database(run_dir: Path, env: dict[str, str]) -> tuple[Path, str, str]:
    """Create/reuse this run's private Postgres cluster and database; never touch the shared cluster."""
    pgdata = run_dir / ".postgres-data"
    status = subprocess.run([str(PGCTL), "-D", str(pgdata), "status"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if status.returncode == 0:
        raise RuntimeError("this run's PostgreSQL is already running; leaving it untouched")
    try:
        with socket.create_connection(("127.0.0.1", PGPORT), timeout=0.5):
            raise RuntimeError(f"benchmark port {PGPORT} is already in use; refusing to connect to another service")
    except OSError:
        pass
    if not (pgdata / "PG_VERSION").is_file():
        if pgdata.exists() and any(pgdata.iterdir()):
            raise RuntimeError("run-specific PostgreSQL directory exists but is not an initialized cluster")
        pgdata.parent.mkdir(parents=True, exist_ok=True)
        shell([INITDB, "-D", pgdata, "-U", "postgres", "--auth-local=trust", "--auth-host=trust"], env, capture=True)
    socket_dir = run_dir / ".postgres-socket"
    socket_dir.mkdir(exist_ok=True)
    shell([PGCTL, "-D", pgdata, "-l", run_dir / "postgres.log", "-o",
           f"-h 127.0.0.1 -p {PGPORT} -k {socket_dir} -c shared_buffers=64MB -c max_connections=64",
           "start", "-w", "-t", "15"], env, capture=True)
    db_name = database_name_for_run(run_dir)
    admin_dsn = f"postgresql://postgres@127.0.0.1:{PGPORT}/postgres"
    try:
        exists = shell([PSQL, admin_dsn, "-X", "-tA", "-c",
                        f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"], env, capture=True).stdout.strip()
        if exists != "1":
            shell([CREATEDB, "-h", "127.0.0.1", "-p", str(PGPORT), "-U", "postgres", db_name], env, capture=True)
    except BaseException:
        shell([PGCTL, "-D", pgdata, "stop", "-m", "fast", "-w", "-t", "15"], env, capture=True)
        raise
    dsn = f"postgresql://postgres@127.0.0.1:{PGPORT}/{db_name}"
    reader_dsn = f"postgresql://texa_reader:texa_reader@127.0.0.1:{PGPORT}/{db_name}"
    return pgdata, dsn, reader_dsn


def run_one(variant: str, case_id: str, attempt: int, run_dir: Path, env: dict[str, str],
            max_calls: int) -> tuple[str, str, str | None]:
    output = run_dir / "cases" / variant / f"{case_id}-attempt-{attempt}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    log = run_dir / "logs" / variant / f"{case_id}-attempt-{attempt}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [PYTHON, ROOT / "backend/eval/run_gateway_check.py", "--credentials",
            ROOT / ".runtime/class-demo-gateway.json", "--runner", "accuracy", "--dataset-dir", DATA,
            "--suite", "single", "--split", "test", "--variant", variant, "--world", "real",
            "--repeat", "1", "--case-id", case_id, "--execute", "--max-model-calls", str(max_calls),
            "--output", output]
    with log.open("w", encoding="utf-8") as handle:
        proc = subprocess.run([str(x) for x in argv], cwd=ROOT, env=env, stdout=handle,
                              stderr=subprocess.STDOUT, text=True)
    log_text = log.read_text(encoding="utf-8", errors="replace").lower()
    if any(term in log_text for term in ("budget exhausted", "cumulative gateway budget")):
        return "stop", str(output), "gateway budget exhausted; run paused without further retries"
    if any(term in log_text for term in ("authenticationerror", "permissiondeniederror", "invalid api key", "unauthorized")):
        return "stop", str(output), "gateway authentication failed; run paused without further requests"
    parsed = valid_case_output(output, case_id)
    if proc.returncode == 0 and parsed:
        row = parsed["row"]
        error = row.get("error_type")
        if error in HALT_ERRORS:
            return "stop", str(output), f"non-retryable gateway/configuration error: {error}"
        if error in RETRYABLE:
            return "retry", str(output), f"transient provider error: {error}"
        return "completed", str(output), None
    # Never echo subprocess logs: they may include user data or provider diagnostics.
    return "retry", str(output), f"child exited {proc.returncode}; output incomplete or invalid"


def update_job(db_path: Path, variant: str, case_id: str, status: str, attempts: int,
               output: str | None, error: str | None):
    with sqlite3.connect(db_path, timeout=30) as db:
        db.execute("UPDATE jobs SET status=?, attempts=?, output_path=?, error=?, updated_at=? WHERE variant=? AND case_id=?",
                   (status, attempts, output, error, time.strftime("%Y-%m-%dT%H:%M:%S%z"), variant, case_id))
        db.commit()


def combine_variant(run_dir: Path, variant: str, ids: list[str]):
    outputs = []
    manifests = []
    for case_id in ids:
        path = run_dir / "cases" / variant / f"{case_id}-attempt-final.jsonl"
        data = valid_case_output(path, case_id)
        if data is None:
            raise RuntimeError(f"missing or invalid final artifact for {variant}/{case_id}")
        outputs.append(data["row"])
        manifests.append(data["manifest"])
    first = manifests[0]
    for manifest in manifests[1:]:
        for key in ("variant", "suite", "split", "repeat", "model", "provenance", "dataset", "fixture_world", "input_policy"):
            if manifest.get(key) != first.get(key):
                raise RuntimeError(f"provenance mismatch for {variant}: {key}")
    first["expected_ids"] = ids
    first["expected_scenario_count"] = len(ids)
    first["expected_answer_counts"] = {row["id"]: 1 for row in outputs}
    first["shard"] = {"index": 0, "count": 1}
    target = run_dir / f"single-test-{variant}-real-r1.jsonl"
    temporary = target.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for obj in [first, *outputs, {"type": "run_complete", "scenarios": len(outputs)}]:
            handle.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    # Use the official reader to enforce complete ID coverage and protocol metadata.
    sys.path.insert(0, str(ROOT / "backend/eval"))
    from report_accuracy_study import read_run
    read_run(target)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--workers", type=int, default=2, choices=range(1, 9),
                        help="global maximum concurrent model-evaluation child processes")
    parser.add_argument("--max-attempts", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--max-model-calls-per-case", type=int, default=100)
    args = parser.parse_args(argv)
    if args.max_model_calls_per_case < 1:
        parser.error("--max-model-calls-per-case must be positive")
    run_dir = args.run_dir.resolve()
    run_dir.relative_to(ROOT)
    run_dir.mkdir(parents=True, exist_ok=True)
    config = frozen_config(args.workers, args.max_attempts)
    config["database_name"] = database_name_for_run(run_dir)
    config_path = run_dir / "run-config.json"
    db_path = run_dir / "run-state.sqlite3"
    if args.resume:
        if not config_path.is_file() or not db_path.is_file():
            parser.error("--resume requires an existing run-config.json and run-state.sqlite3")
        existing = json.loads(config_path.read_text(encoding="utf-8"))
        for key in ("dataset_manifest_sha256", "cases_sha256", "world_sha256", "git_commit", "frozen_inputs_sha256", "variants", "expected_cases", "database_name"):
            if existing.get(key) != config.get(key):
                parser.error(f"cannot resume: frozen {key} changed; use a new run directory")
        # Worker count and retry count can be changed safely on resume.
        for key in ("model", "base_url", "authorized_max_usd", "credentials_fingerprint"):
            if existing.get(key) != config.get(key):
                parser.error(f"cannot resume: gateway {key} changed; use a new run directory")
    else:
        if config_path.exists() or db_path.exists():
            parser.error("run directory already initialized; pass --resume or choose a new directory")
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        config_path.chmod(0o600)
    ids = case_ids()
    db = connect(db_path)
    db.executemany("INSERT OR IGNORE INTO jobs(variant,case_id,status,updated_at) VALUES(?,?,?,?)",
                   [(variant, case_id, "pending", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
                    for variant in VARIANTS for case_id in ids])
    db.commit()
    # Reconcile checkpoint with durable artifacts, so a crash between writing output and SQLite commit is safe.
    for variant in VARIANTS:
        for case_id in ids:
            row = db.execute("SELECT status, attempts FROM jobs WHERE variant=? AND case_id=?", (variant, case_id)).fetchone()
            final = run_dir / "cases" / variant / f"{case_id}-attempt-final.jsonl"
            # Reconcile both sides of the rename/checkpoint boundary. If the process died after
            # atomically installing a validated final artifact but before SQLite commit, accept it
            # as complete and avoid spending for the same logical case again.
            if valid_case_output(final, case_id) is not None:
                db.execute("UPDATE jobs SET status='completed', output_path=?, error=NULL, updated_at=? WHERE variant=? AND case_id=?",
                           (str(final), time.strftime("%Y-%m-%dT%H:%M:%S%z"), variant, case_id))
            elif row and row[0] == "completed":
                db.execute("UPDATE jobs SET status='pending', output_path=NULL WHERE variant=? AND case_id=?", (variant, case_id))
    db.commit()
    pending = [(v, case) for v, case, status in db.execute("SELECT variant,case_id,status FROM jobs ORDER BY variant,case_id")
               if status != "completed"]
    print(json.dumps({"run_dir": str(run_dir), "variants": len(VARIANTS), "cases_per_variant": len(ids),
                      "jobs_total": len(VARIANTS) * len(ids), "jobs_completed": len(VARIANTS)*len(ids)-len(pending),
                      "jobs_pending": len(pending), "workers": args.workers, "resume": args.resume}), flush=True)
    if not pending:
        for variant in VARIANTS:
            combine_variant(run_dir, variant, ids)
        print(json.dumps({"status": "complete", "aggregates": len(VARIANTS), "model_calls": 0}), flush=True)
        return 0
    lock_handle = (run_dir / "run.lock").open("a+")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("another manager is already using this run directory")
    env = os.environ | {"PYTHONPATH": str(ROOT / "backend"), "TEXA_LLM_MAX_INFLIGHT": "1"}
    started_pg = False
    pgdata = run_dir / ".postgres-data"
    try:
        pgdata, dsn, reader_dsn = ensure_isolated_database(run_dir, env)
        started_pg = True
        env.update({"TEXA_DB_DSN": dsn, "TEXA_READER_DSN": reader_dsn,
                    "TEXA_BENCHMARK_DSN": reader_dsn})
        prepare_db(env)
        stop_event = threading.Event()
        lock = threading.Lock()
        failures: list[tuple[str, str, str]] = []
        completed_count = len(VARIANTS) * len(ids) - len(pending)

        def process(job):
            nonlocal completed_count
            variant, case_id = job
            with sqlite3.connect(db_path, timeout=30) as state_db:
                row = state_db.execute("SELECT attempts FROM jobs WHERE variant=? AND case_id=?", (variant, case_id)).fetchone()
            attempts = row[0] if row else 0
            # If the process died after creating an attempt file but before checkpointing SQLite,
            # advance to a fresh attempt number rather than overwriting or colliding with evidence.
            existing = list((run_dir / "cases" / variant).glob(f"{case_id}-attempt-*.jsonl"))
            for path in existing:
                try:
                    attempts = max(attempts, int(path.stem.rsplit("-", 1)[1]))
                except (ValueError, IndexError):
                    pass
            last_path = None
            last_error = None
            while attempts < args.max_attempts and not stop_event.is_set():
                attempts += 1
                status, output, error = run_one(variant, case_id, attempts, run_dir, env, args.max_model_calls_per_case)
                last_path, last_error = output, error
                if status == "completed":
                    final = run_dir / "cases" / variant / f"{case_id}-attempt-final.jsonl"
                    Path(output).replace(final)
                    update_job(db_path, variant, case_id, "completed", attempts, str(final), None)
                    with lock:
                        completed_count += 1
                        print(json.dumps({"done": completed_count, "total": len(VARIANTS)*len(ids), "variant": variant,
                                          "case": case_id, "time": time.strftime("%H:%M:%S")}), flush=True)
                    return
                if status == "stop":
                    stop_event.set()
                    update_job(db_path, variant, case_id, "failed", attempts, output, error)
                    with lock:
                        failures.append((variant, case_id, error or "run stopped"))
                    return
                update_job(db_path, variant, case_id, "retrying", attempts, output, error)
                # Avoid hammering a rate-limited provider; only bounded backoff.
                time.sleep(min(2 ** (attempts - 1), 8))
            if not stop_event.is_set():
                update_job(db_path, variant, case_id, "failed", attempts, last_path, last_error)
                with lock:
                    failures.append((variant, case_id, last_error or "unknown"))

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(process, job) for job in pending]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    stop_event.set()
                    failures.append(("manager", "worker", type(exc).__name__))
        for variant in VARIANTS:
            complete = db.execute("SELECT count(*) FROM jobs WHERE variant=? AND status='completed'", (variant,)).fetchone()[0]
            if complete == len(ids):
                combine_variant(run_dir, variant, ids)
        print(json.dumps({"finished": completed_count, "total": len(VARIANTS)*len(ids),
                          "failed_jobs": len(failures), "status": "complete" if not failures and completed_count == len(VARIANTS)*len(ids) else "needs_resume"}), flush=True)
        if failures:
            print(json.dumps({"failure_samples": failures[:10]}), flush=True)
        return 0 if not failures and completed_count == len(VARIANTS)*len(ids) else 2
    finally:
        if started_pg:
            shell([PGCTL, "-D", pgdata, "stop", "-m", "fast", "-w", "-t", "15"], env, capture=True)
            print("Benchmark PostgreSQL stopped", flush=True)
        lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
