"""Resumable v3 reruns for the three new direct-LLM baselines only.

The run is pinned to the catalog/example-bank files at commit 8fbdcefc, matching
the context used by the historical Texa scores. Each answer case and repeat is
checkpointed independently. This script never starts model calls unless the v3
fixture SQL validates against all stored expected tables first.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

import psycopg
import yaml

try:
    from .run_research_manager import (ROOT, PYTHON, PSQL, ensure_isolated_database, shell,
                                      valid_case_output, RETRYABLE, HALT_ERRORS)
except ImportError:
    from run_research_manager import (ROOT, PYTHON, PSQL, ensure_isolated_database, shell,
                                     valid_case_output, RETRYABLE, HALT_ERRORS)

DATA = ROOT / "data/benchmark/research_v3"
SNAPSHOT_COMMIT = "8fbdcefc"
VARIANTS = ("B0R", "B0G", "B0GR")
REPEATS = (1, 2)
MAX_ATTEMPTS = 3


def case_ids():
    rows = yaml.safe_load((DATA / "cases.yaml").read_text(encoding="utf-8"))
    ids = [row["id"] for row in rows if row.get("split") == "test" and row.get("fixture_world", "base") == "base"]
    if len(ids) != 200 or len(set(ids)) != 200:
        raise RuntimeError(f"expected 200 unique v3 base-world test cases; got {len(ids)}")
    return ids


def snapshot_inputs(run_dir: Path):
    snapshot = run_dir / "reference-inputs"
    snapshot.mkdir(parents=True, exist_ok=True)
    for rel in ("catalog/product_events.yaml", "catalog/verified_examples.yaml"):
        target = snapshot / Path(rel).name
        content = subprocess.check_output(["git", "show", f"{SNAPSHOT_COMMIT}:{rel}"], cwd=ROOT)
        target.write_bytes(content)
    return snapshot / "product_events.yaml", snapshot / "verified_examples.yaml"


def run_config(run_dir: Path, workers: int, catalogs):
    credentials = json.loads((ROOT / ".runtime/class-demo-gateway.json").read_text(encoding="utf-8"))
    if not all(credentials.get(k) for k in ("model", "base_url", "api_key", "max_usd")):
        raise RuntimeError("protected gateway credentials are incomplete")
    return {
        "suite": "single", "split": "test", "world": "base", "repeats": list(REPEATS),
        "variants": list(VARIANTS), "case_count": 200, "job_count": 1200,
        "dataset_sha256": hashlib.sha256((DATA / "cases.yaml").read_bytes()).hexdigest(),
        "historical_snapshot_commit": SNAPSHOT_COMMIT,
        "catalog_sha256": hashlib.sha256(catalogs[0].read_bytes()).hexdigest(),
        "examples_sha256": hashlib.sha256(catalogs[1].read_bytes()).hexdigest(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "accuracy_runner_sha256": hashlib.sha256((ROOT / "backend/eval/run_accuracy_study.py").read_bytes()).hexdigest(),
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "model": credentials["model"], "base_url": credentials["base_url"],
        "authorized_budget_usd": float(credentials["max_usd"]),
        "credential_fingerprint": hashlib.sha256(credentials["api_key"].encode()).hexdigest(),
        "workers": workers,
    }


def validate_v3_worlds(dsn: str, env: dict[str, str]):
    cases = yaml.safe_load((DATA / "cases.yaml").read_text(encoding="utf-8"))
    checks = 0
    with psycopg.connect(dsn, autocommit=True) as conn:
        for world in ("base", "grain_counterexample", "coverage_edge"):
            fixture = DATA / "worlds" / f"{world}.sql"
            shell([PSQL, dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", fixture], env)
            for case in cases:
                if case.get("split") != "test":
                    continue
                expected = case.get("expected_results_by_world", {}).get(world)
                if expected is None:
                    raise RuntimeError(f"{case['id']} lacks gold for {world}")
                try:
                    with conn.transaction():
                        conn.execute("SET TRANSACTION READ ONLY")
                        conn.execute("SET LOCAL statement_timeout = '10s'")
                        cur = conn.execute(case["gold_sql"])
                        actual = {"columns": [c.name for c in cur.description], "rows": [list(r) for r in cur.fetchall()]}
                    sys.path.insert(0, str(ROOT / "backend/eval"))
                    from benchmark import results_equal
                    if not results_equal(actual["columns"], actual["rows"], expected["columns"], expected["rows"], ordered=bool(case.get("ordered"))):
                        raise RuntimeError(f"v3 gold mismatch: {case['id']} on {world}")
                except Exception as exc:
                    raise RuntimeError(f"v3 gold validation failed: {case['id']} on {world} ({type(exc).__name__})") from None
                checks += 1
        shell([PSQL, dsn, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", DATA / "worlds/base.sql"], env)
    return checks


def init_state(path: Path):
    db = sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS jobs (
        variant TEXT, repeat INTEGER, case_id TEXT, status TEXT, attempts INTEGER DEFAULT 0,
        output_path TEXT, error TEXT, updated_at TEXT, PRIMARY KEY(variant,repeat,case_id))""")
    db.commit()
    return db


def update_v3_job(path: Path, variant: str, repeat: int, case_id: str, status: str,
                  attempts: int, output: str | None, error: str | None):
    with sqlite3.connect(path, timeout=30) as db:
        db.execute("UPDATE jobs SET status=?, attempts=?, output_path=?, error=?, updated_at=? WHERE variant=? AND repeat=? AND case_id=?",
                   (status, attempts, output, error, time.strftime("%Y-%m-%dT%H:%M:%S%z"), variant, repeat, case_id))
        db.commit()


def run_case(run_dir, variant, repeat, case_id, attempt, env):
    out = run_dir / "cases" / variant / f"r{repeat}-{case_id}-a{attempt}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    log = run_dir / "logs" / variant / f"r{repeat}-{case_id}-a{attempt}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [PYTHON, ROOT / "backend/eval/run_gateway_check.py", "--credentials",
               ROOT / ".runtime/class-demo-gateway.json", "--runner", "accuracy", "--dataset-dir", DATA,
               "--suite", "single", "--split", "test", "--variant", variant, "--world", "base",
               "--repeat", str(repeat), "--case-id", case_id, "--execute", "--max-model-calls", "100",
               "--output", out]
    with log.open("w", encoding="utf-8") as handle:
        proc = subprocess.run([str(x) for x in command], cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
    text = log.read_text(encoding="utf-8", errors="replace").lower()
    if "budget exhausted" in text or "cumulative gateway budget" in text:
        return "stop", str(out), "budget exhausted"
    if any(x in text for x in ("authenticationerror", "permissiondeniederror", "invalid api key", "unauthorized")):
        return "stop", str(out), "gateway authentication/configuration error"
    data = valid_case_output(out, case_id)
    if proc.returncode == 0 and data:
        error = data["row"].get("error_type")
        if error in HALT_ERRORS:
            return "stop", str(out), error
        if error in RETRYABLE:
            return "retry", str(out), error
        return "completed", str(out), None
    return "retry", str(out), f"child exited {proc.returncode} or incomplete artifact"


def combine(run_dir, variant, repeat, ids):
    rows, manifests = [], []
    for cid in ids:
        valid = valid_case_output(run_dir / "cases" / variant / f"r{repeat}-{cid}-final.jsonl", cid)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if valid is None:
                valid = valid_case_output(run_dir / "cases" / variant / f"r{repeat}-{cid}-a{attempt}.jsonl", cid)
            if valid is not None:
                break
        if not valid:
            raise RuntimeError(f"missing finished artifact: {variant}/r{repeat}/{cid}")
        rows.append(valid["row"]); manifests.append(valid["manifest"])
    manifest = manifests[0]
    for m in manifests[1:]:
        for key in ("variant", "suite", "split", "repeat", "model", "provenance", "dataset", "fixture_world", "input_policy"):
            if m.get(key) != manifest.get(key):
                raise RuntimeError(f"provenance mismatch in {variant} repeat {repeat}: {key}")
    manifest.update(expected_ids=ids, expected_scenario_count=len(ids), expected_answer_counts={cid: 1 for cid in ids}, shard={"index": 0, "count": 1})
    target = run_dir / f"single-test-{variant}-base-r{repeat}.jsonl"
    tmp = target.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for record in [manifest, *rows, {"type": "run_complete", "scenarios": len(rows)}]:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        f.flush(); os.fsync(f.fileno())
    tmp.replace(target)
    sys.path.insert(0, str(ROOT / "backend/eval"))
    from report_accuracy_study import read_run
    read_run(target)
    return target


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--preflight-only", action="store_true",
                    help="validate historical snapshots and all v3 gold worlds, then stop without model calls")
    ap.add_argument("--workers", type=int, default=2, choices=range(1, 5))
    args = ap.parse_args(argv)
    if not args.preflight_only:
        from run_accuracy_study import _assert_study_inputs_frozen
        _assert_study_inputs_frozen(DATA)
    run_dir = args.run_dir.resolve(); run_dir.relative_to(ROOT); run_dir.mkdir(parents=True, exist_ok=True)
    ids = case_ids(); config_path = run_dir / "run-config.json"; state_path = run_dir / "run-state.sqlite3"
    catalogs = snapshot_inputs(run_dir)
    frozen = run_config(run_dir, args.workers, catalogs)
    if args.resume:
        previous = json.loads(config_path.read_text())
        if any(previous.get(k) != v for k, v in frozen.items() if k != "workers"):
            ap.error("frozen v3 inputs differ; use a new run directory")
    elif config_path.exists() or state_path.exists():
        ap.error("run directory exists; pass --resume")
    else:
        config_path.write_text(json.dumps(frozen, indent=2) + "\n"); config_path.chmod(0o600)
    state = init_state(state_path)
    jobs = [(v, r, cid) for v in VARIANTS for r in REPEATS for cid in ids]
    state.executemany("INSERT OR IGNORE INTO jobs(variant,repeat,case_id,status,updated_at) VALUES(?,?,?,?,?)",
                       [(v,r,c,"pending",time.strftime("%Y-%m-%dT%H:%M:%S%z")) for v,r,c in jobs]); state.commit()
    done = set()
    for v,r,c in jobs:
        final = run_dir / "cases" / v / f"r{r}-{c}-final.jsonl"
        if valid_case_output(final,c):
            state.execute("UPDATE jobs SET status='completed',output_path=? WHERE variant=? AND repeat=? AND case_id=?",(str(final),v,r,c)); done.add((v,r,c))
    state.commit()
    pending = [j for j in jobs if j not in done]
    print(json.dumps({"total":len(jobs),"done":len(done),"pending":len(pending),"workers":args.workers}),flush=True)
    if not pending:
        for v in VARIANTS:
            for r in REPEATS: combine(run_dir,v,r,ids)
        return 0
    lock_file = (run_dir / "run.lock").open("a+")
    import fcntl
    try: fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: ap.error("manager already running")
    env = os.environ | {"PYTHONPATH":str(ROOT/"backend"), "TEXA_LLM_MAX_INFLIGHT":"1",
                        "TEXA_CATALOG":str(catalogs[0]), "TEXA_EXAMPLE_BANK":str(catalogs[1]),
                        "TEXA_SOURCE_PROFILE":"evaluation"}
    pgdata = None
    try:
        pgdata, dsn, reader = ensure_isolated_database(run_dir, env)
        env.update(TEXA_DB_DSN=dsn,TEXA_READER_DSN=reader,TEXA_BENCHMARK_DSN=reader)
        shell([PSQL,dsn,"-X","-v","ON_ERROR_STOP=1","-f",ROOT/"pipeline/sql/init/01_init.sql"],env)
        shell([PYTHON,"-c","from texa import db; db.migrate()"],env,capture=True)
        shell([PSQL,dsn,"-X","-q","-v","ON_ERROR_STOP=1","-f",DATA/"worlds/base.sql"],env)
        checks=validate_v3_worlds(dsn,env)
        shell([PYTHON,"-c","from texa import catalog; print(catalog.publish())"],env,capture=True)
        if args.preflight_only:
            print(json.dumps({"status":"preflight_passed","gold_checks":checks,"paid_model_calls":0,
                              "catalog_sha256":frozen["catalog_sha256"],"examples_sha256":frozen["examples_sha256"]}),flush=True)
            return 0
        print(json.dumps({"gold_checks":checks,"paid_calls_starting":True}),flush=True)
        halt=threading.Event(); guard=threading.Lock(); failures=[]
        def work(job):
            v,r,c=job
            with sqlite3.connect(state_path, timeout=30) as state_db:
                attempts=state_db.execute("SELECT attempts FROM jobs WHERE variant=? AND repeat=? AND case_id=?",job).fetchone()[0]
            for prior in (run_dir/"cases"/v).glob(f"r{r}-{c}-a*.jsonl"):
                try: attempts=max(attempts,int(prior.stem.split("-a")[-1]))
                except ValueError: pass
            for attempt in range(attempts+1,MAX_ATTEMPTS+1):
                if halt.is_set(): return
                status,path,error=run_case(run_dir,v,r,c,attempt,env)
                if status=="completed":
                    final=run_dir/"cases"/v/f"r{r}-{c}-final.jsonl"; Path(path).replace(final)
                    update_v3_job(state_path,v,r,c,"completed",attempt,str(final),None)
                    with sqlite3.connect(state_path, timeout=30) as state_db:
                        total_done=state_db.execute("SELECT count(*) FROM jobs WHERE status='completed'").fetchone()[0]
                    with guard: print(json.dumps({"done":total_done,"total":len(jobs),"variant":v,"repeat":r,"case":c}),flush=True)
                    return
                update_v3_job(state_path,v,r,c,"failed" if status=="stop" else "retrying",attempt,path,error)
                if status=="stop":
                    halt.set(); failures.append((v,r,c,error)); return
                time.sleep(min(2**(attempt-1),8))
            failures.append((v,r,c,"attempt limit"))
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(work,j) for j in pending]
            for f in as_completed(futures):
                try:f.result()
                except Exception as exc: halt.set(); failures.append(("manager",0,"worker",type(exc).__name__))
        for v in VARIANTS:
            for r in REPEATS:
                if state.execute("SELECT count(*) FROM jobs WHERE variant=? AND repeat=? AND status='completed'",(v,r)).fetchone()[0]==len(ids): combine(run_dir,v,r,ids)
        return 2 if failures else 0
    finally:
        if pgdata and (pgdata/"PG_VERSION").exists():
            subprocess.run([str(Path(".runtime/pgtools/pgserver/pginstall/bin/pg_ctl")),"-D",str(pgdata),"stop","-m","fast","-w","-t","15"],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        lock_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
