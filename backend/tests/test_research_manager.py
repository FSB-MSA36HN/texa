import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from eval import run_research_manager as manager
from eval.validate_research_v4 import validate_load_target
from eval.run_research_manager import case_ids, valid_case_output


def test_research_v4_manager_selects_exact_test_partition():
    ids = case_ids()
    assert len(ids) == 200
    assert len(set(ids)) == 200
    assert all(case_id.startswith("rv4_test_") for case_id in ids)


def test_valid_case_output_requires_complete_matching_case(tmp_path):
    path = tmp_path / "case.jsonl"
    records = [
        {"type": "run_manifest", "variant": "B0", "expected_ids": ["rv4_test_101"]},
        {"type": "scenario", "id": "rv4_test_101", "success": True},
        {"type": "run_complete", "scenarios": 1},
    ]
    path.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
    assert valid_case_output(path, "rv4_test_101")["row"]["success"] is True
    assert valid_case_output(path, "rv4_test_102") is None

    path.write_text("\n".join(json.dumps(row) for row in records[:-1]) + "\n", encoding="utf-8")
    assert valid_case_output(path, "rv4_test_101") is None


def _fake_run_config():
    return {"dataset_manifest_sha256": "m", "cases_sha256": "c", "world_sha256": "w",
            "git_commit": "commit", "frozen_inputs_sha256": {}, "variants": ["B0"],
            "expected_cases": 1, "expected_jobs": 1, "model": "test-model",
            "base_url": "https://gateway.invalid/v1", "authorized_max_usd": 10,
            "credentials_fingerprint": "fingerprint"}


def _install_one_job_run(monkeypatch, tmp_path, *, completed=False):
    monkeypatch.setattr(manager, "ROOT", tmp_path)
    monkeypatch.setattr(manager, "VARIANTS", ("B0",))
    monkeypatch.setattr(manager, "case_ids", lambda: ["case_1"])
    monkeypatch.setattr(manager, "frozen_config", lambda workers, attempts: _fake_run_config())
    run_dir = tmp_path / "runs" / "offline"
    run_dir.mkdir(parents=True)
    config = _fake_run_config()
    config["database_name"] = manager.database_name_for_run(run_dir)
    (run_dir / "run-config.json").write_text(json.dumps(config), encoding="utf-8")
    db_path = run_dir / "run-state.sqlite3"
    db = manager.connect(db_path)
    db.execute("INSERT INTO jobs(variant,case_id,status,attempts,updated_at) VALUES(?,?,?,?,?)",
               ("B0", "case_1", "completed" if completed else "pending", 1 if completed else 0, "now"))
    db.commit()
    db.close()
    return run_dir, db_path


def _write_case_artifact(path, case_id="case_1", *, success=True, error_type=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"type": "scenario", "id": case_id, "success": success}
    if error_type:
        row["error_type"] = error_type
    records = [{"type": "run_manifest", "variant": "B0", "suite": "single"},
               row, {"type": "run_complete", "scenarios": 1}]
    path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")


def test_resume_reconciles_final_artifact_before_sqlite_checkpoint(monkeypatch, tmp_path):
    run_dir, db_path = _install_one_job_run(monkeypatch, tmp_path)
    final = run_dir / "cases/B0/case_1-attempt-final.jsonl"
    _write_case_artifact(final)
    aggregate = Mock()
    gateway = Mock(side_effect=AssertionError("no gateway process should start for a reconciled job"))
    monkeypatch.setattr(manager, "combine_variant", aggregate)
    monkeypatch.setattr(manager, "run_one", gateway)

    assert manager.main(["--run-dir", str(run_dir), "--resume"]) == 0

    with sqlite3.connect(db_path) as db:
        row = db.execute("SELECT status, output_path FROM jobs WHERE variant='B0' AND case_id='case_1'").fetchone()
    assert row == ("completed", str(final))
    aggregate.assert_called_once_with(run_dir, "B0", ["case_1"])
    gateway.assert_not_called()


def test_postgres_running_check_precedes_start_and_any_model_work(monkeypatch, tmp_path):
    run_dir, _ = _install_one_job_run(monkeypatch, tmp_path)
    status_check = Mock(return_value=subprocess.CompletedProcess(args=[], returncode=0))
    shell = Mock(side_effect=AssertionError("must not start or migrate an already-running database"))
    run_one = Mock(side_effect=AssertionError("must not make a model request"))
    monkeypatch.setattr(manager.subprocess, "run", status_check)
    monkeypatch.setattr(manager, "shell", shell)
    monkeypatch.setattr(manager, "run_one", run_one)

    with pytest.raises(RuntimeError, match="already running"):
        manager.main(["--run-dir", str(run_dir), "--resume"])

    status_check.assert_called_once()
    shell.assert_not_called()
    run_one.assert_not_called()


def test_preflight_failure_stops_before_gateway_and_stops_started_postgres(monkeypatch, tmp_path):
    run_dir, _ = _install_one_job_run(monkeypatch, tmp_path)
    monkeypatch.setattr(manager.subprocess, "run",
                        Mock(return_value=subprocess.CompletedProcess(args=[], returncode=1)))
    monkeypatch.setattr(manager.socket, "create_connection", Mock(side_effect=OSError("port closed")))
    commands = []

    def shell(argv, env, *, capture=False):
        commands.append([str(arg) for arg in argv])
        if "validate_research_v4.py" in " ".join(map(str, argv)):
            raise RuntimeError("oracle preflight failed")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="")

    paid_runner = Mock(side_effect=AssertionError("preflight must block all model work"))
    monkeypatch.setattr(manager, "shell", shell)
    monkeypatch.setattr(manager, "run_one", paid_runner)
    with pytest.raises(RuntimeError, match="oracle preflight failed"):
        manager.main(["--run-dir", str(run_dir), "--resume"])

    assert "initdb" in commands[0][0]
    assert "start" in commands[1]
    assert "createdb" in commands[3][0]
    assert "01_init.sql" in " ".join(commands[4])
    assert "db.migrate()" in " ".join(commands[5])
    assert "validate_research_v4.py" in " ".join(commands[6])
    assert "stop" in commands[-1]
    paid_runner.assert_not_called()


def test_validator_load_target_only_allows_named_isolated_run_database():
    validate_load_target("texa_bench_run_123456789abc", isolated_run=True)
    with pytest.raises(SystemExit, match="without --isolated-run"):
        validate_load_target("texa_benchmark", isolated_run=False)
    with pytest.raises(SystemExit, match="texa_bench_run_"):
        validate_load_target("texa_benchmark", isolated_run=True)
    with pytest.raises(SystemExit, match="pass --isolated-run"):
        validate_load_target("some_other_db", isolated_run=False)


@pytest.mark.parametrize(
    ("log_text", "expected_status"),
    [("gateway budget exhausted", "stop"), ("AuthenticationError: unauthorized", "stop")],
)
def test_gateway_budget_and_authentication_errors_halt_without_retry(monkeypatch, tmp_path, log_text, expected_status):
    run_dir = tmp_path / "run"
    real_run = manager.subprocess.run

    def fake_process(argv, **kwargs):
        kwargs["stdout"].write(log_text)
        return subprocess.CompletedProcess(args=argv, returncode=1)

    monkeypatch.setattr(manager.subprocess, "run", fake_process)
    status, _, message = manager.run_one("B0", "case_1", 1, run_dir, {}, 100)
    assert status == expected_status
    assert message and ("budget exhausted" in message or "authentication failed" in message)
    monkeypatch.setattr(manager.subprocess, "run", real_run)


def test_wrong_model_answer_is_a_completed_measurement_not_infrastructure_retry(monkeypatch, tmp_path):
    run_dir = tmp_path / "run"

    def fake_process(argv, **kwargs):
        output_arg = Path(argv[argv.index("--output") + 1])
        _write_case_artifact(output_arg, success=False)
        return subprocess.CompletedProcess(args=argv, returncode=0)

    monkeypatch.setattr(manager.subprocess, "run", fake_process)
    status, _, error = manager.run_one("B0", "case_1", 1, run_dir, {}, 100)
    assert (status, error) == ("completed", None)
