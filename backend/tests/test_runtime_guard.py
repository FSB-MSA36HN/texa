import threading
import time

import pytest

from texa.runtime_guard import AdmissionRejected, BoundedAdmission


def test_admission_caps_active_requests_and_releases_after_failure():
    admission = BoundedAdmission(max_inflight=1, max_waiters=1, wait_timeout_s=1)
    entered = threading.Event()
    release = threading.Event()
    observed = []

    def first():
        try:
            with admission.acquire():
                entered.set()
                release.wait(1)
                raise RuntimeError("injected provider failure")
        except RuntimeError:
            pass

    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(1)
    def queued():
        with admission.acquire() as queue_ms:
            observed.append(queue_ms)
    waiting = threading.Thread(target=queued)
    waiting.start()
    time.sleep(.02)
    with pytest.raises(AdmissionRejected, match="queue is full"):
        with admission.acquire():
            pass
    release.set()
    thread.join(1)
    waiting.join(1)
    assert not thread.is_alive() and not waiting.is_alive()
    assert len(observed) == 1 and observed[0] >= 10


def test_admission_wait_timeout_does_not_leak_waiter_slot():
    admission = BoundedAdmission(max_inflight=1, max_waiters=1, wait_timeout_s=.02)
    with admission.acquire():
        with pytest.raises(AdmissionRejected, match="wait timed out"):
            with admission.acquire():
                pass
    with admission.acquire():
        pass
