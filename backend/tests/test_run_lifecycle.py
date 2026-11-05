"""Lifecycle checks for run.sh using isolated fake executables (never Docker/app)."""
import os
import shutil
import signal
import subprocess
import time
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lifecycle_tmp():
    with tempfile.TemporaryDirectory(prefix="run-lifecycle-", dir=ROOT / ".runtime") as directory:
        yield Path(directory)


def harness(lifecycle_tmp, *, uv_body="exit 0"):
    root = lifecycle_tmp / "texa"
    root.mkdir()
    shutil.copy(ROOT / "run.sh", root / "run.sh")
    (root / ".env.example").write_text("TEST_ENV=1\n")
    for name in ("backend", "web"):
        (root / name).mkdir()
    (root / "web" / "node_modules").mkdir()
    bindir = lifecycle_tmp / "bin"
    bindir.mkdir()
    log = lifecycle_tmp / "mock.log"
    (bindir / "docker").write_text(
        '#!/bin/bash\necho "docker $*" >> "$MOCK_LOG"\n'
        'if [[ "$1 $2" == "info"* ]]; then exit ${MOCK_DOCKER_DOWN:-0}; fi\n'
        'if [[ "$*" == *"ps --all --quiet"* ]]; then echo "c1 c2"; fi\n'
        'exit 0\n'
    )
    (bindir / "uv").write_text("#!/bin/bash\necho \"uv $*\" >> \"$MOCK_LOG\"\n" + uv_body + "\n")
    (bindir / "npm").write_text('#!/bin/bash\necho "npm $*" >> "$MOCK_LOG"\nexit 0\n')
    (bindir / "open").write_text('#!/bin/bash\necho "open $*" >> "$MOCK_LOG"\nexit 0\n')
    (bindir / "sleep").write_text('#!/bin/bash\n"$REAL_SLEEP" "$@"\n')
    for exe in bindir.iterdir():
        exe.chmod(0o755)
    env = os.environ.copy()
    env.update(PATH=f"{bindir}:{env['PATH']}", MOCK_LOG=str(log), REAL_SLEEP=shutil.which("sleep"), PYTHONUNBUFFERED="1")
    return root, log, env


def run(root, env, *args, **kwargs):
    return subprocess.run(["bash", str(root / "run.sh"), *args], cwd=root, env=env,
                          text=True, capture_output=True, timeout=20, **kwargs)


def test_stop_stops_every_compose_service_without_deleting_or_starting(lifecycle_tmp):
    root, log, env = harness(lifecycle_tmp)
    result = run(root, env, "stop")
    calls = log.read_text().splitlines()
    assert result.returncode == 0, result.stderr
    assert any(c.endswith("stop --timeout 10") for c in calls)
    assert any(c.endswith("ps --all --quiet") for c in calls)
    assert any(c == "docker stop --time 10 c1 c2" for c in calls)
    assert not any(token in " ".join(calls) for token in (" up ", " down", " rm ", "prune", "volume", "image"))
    assert not any(c.startswith(("open ", "uv ", "npm ")) for c in calls)


def test_stop_does_not_claim_success_or_open_docker_when_engine_unreachable(lifecycle_tmp):
    root, log, env = harness(lifecycle_tmp)
    env["MOCK_DOCKER_DOWN"] = "1"
    result = run(root, env, "stop")
    assert result.returncode != 0
    assert "Docker" in result.stderr
    assert log.read_text().splitlines() == ["docker info"]


@pytest.mark.skipif(not shutil.which("lsof"), reason="process ownership check uses lsof")
def test_stale_pid_does_not_stop_another_projects_run_script(lifecycle_tmp):
    root, log, env = harness(lifecycle_tmp)
    other = lifecycle_tmp / "other"
    other.mkdir()
    script = other / "run.sh"
    # Keep bash in argv so it still resembles a run.sh manager to the PID guard.
    script.write_text('#!/bin/bash\nwhile :; do "$REAL_SLEEP" 1; done\n')
    proc = subprocess.Popen(["bash", str(script)], cwd=other, start_new_session=True)
    try:
        (root / ".run.pid").write_text(str(proc.pid))
        result = run(root, env, "stop")
        assert result.returncode == 0, result.stderr
        assert proc.poll() is None, "another project's process was signalled"
        assert any(c.endswith("stop --timeout 10") for c in log.read_text().splitlines())
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=5)


def test_stop_command_terminates_live_app_and_child_process_groups(lifecycle_tmp):
    body = ('if [[ "$*" != *uvicorn* ]]; then exit 0; fi\n'
            'echo $$ > "$API_PID"\nwhile :; do "$REAL_SLEEP" 1; done')
    root, log, env = harness(lifecycle_tmp, uv_body=body)
    env.update(API_PID=str(lifecycle_tmp / "api.pid"), WEB_PID=str(lifecycle_tmp / "web.pid"))
    npm = lifecycle_tmp / "bin/npm"
    npm.write_text('#!/bin/bash\necho $$ > "$WEB_PID"\nwhile :; do "$REAL_SLEEP" 1; done\n')
    proc = subprocess.Popen(["bash", str(root / "run.sh")], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stopper = None
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not all(Path(env[k]).exists() for k in ("API_PID", "WEB_PID")):
            if proc.poll() is not None:
                out, err = proc.communicate()
                pytest.fail(f"app exited before fake servers started: {out}\n{err}")
            time.sleep(.05)
        assert all(Path(env[k]).exists() for k in ("API_PID", "WEB_PID"))
        children = [int(Path(env[k]).read_text()) for k in ("API_PID", "WEB_PID")]
        stopper = subprocess.Popen(["bash", str(root / "run.sh"), "stop"], cwd=root, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        main_out, main_err = proc.communicate(timeout=15)  # Reap so stop_existing sees it has exited.
        out, err = stopper.communicate(timeout=15)
        assert stopper.returncode == 0, (out, err, main_out, main_err)
        assert not (root / ".run.pid").exists()
        for child in children:
            with pytest.raises(ProcessLookupError):
                os.kill(child, 0)
        assert any(c.endswith("stop --timeout 10") for c in log.read_text().splitlines())
    finally:
        for process in (proc, stopper):
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.communicate(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_signal_during_startup_exits_and_cleans_processes_and_containers(lifecycle_tmp, sig):
    body = 'touch "$STARTED"\nwhile :; do "$REAL_SLEEP" 1; done'
    root, log, env = harness(lifecycle_tmp, uv_body=body)
    env["STARTED"] = str(lifecycle_tmp / "started")
    proc = subprocess.Popen(["bash", str(root / "run.sh")], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 8
        while not Path(env["STARTED"]).exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert Path(env["STARTED"]).exists(), "startup never reached fake uv"
        proc.send_signal(sig)
        out, err = proc.communicate(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    calls = log.read_text().splitlines()
    assert proc.returncode != 0, (out, err)
    assert any(c.endswith("stop --timeout 10") for c in calls)
    assert not (root / ".run.pid").exists()


def test_startup_command_failure_runs_cleanup(lifecycle_tmp):
    root, log, env = harness(lifecycle_tmp, uv_body="exit 23")
    result = run(root, env)
    calls = log.read_text().splitlines()
    assert result.returncode != 0
    assert any(c.endswith("stop --timeout 10") for c in calls)
    assert not (root / ".run.pid").exists()


def test_cleanup_kills_grandchild_in_startup_process_group(lifecycle_tmp):
    childfile = lifecycle_tmp / "child.pid"
    body = ('/bin/bash -c \'trap "" TERM; while :; do "$REAL_SLEEP" 1; done\' &\n'
            'echo $! > "$CHILD_PID"\ntouch "$STARTED"\nwait')
    root, log, env = harness(lifecycle_tmp, uv_body=body)
    env.update(STARTED=str(lifecycle_tmp / "started"), CHILD_PID=str(childfile))
    proc = subprocess.Popen(["bash", str(root / "run.sh")], cwd=root, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 8
        while (not childfile.exists() or not Path(env["STARTED"]).exists()) and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(.05)
        assert childfile.exists(), "fake npm-like grandchild did not start"
        child = int(childfile.read_text())
        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=15)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(.05)
        else:
            pytest.fail("startup grandchild survived process-group cleanup")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
