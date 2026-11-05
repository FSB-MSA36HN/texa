"""Process-local bounded admission and privacy-safe runtime timing events.

The current launcher runs a single API worker. For multiple workers/hosts,
replace this controller with a shared semaphore (for example Redis/Postgres).
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager


class AdmissionRejected(Exception):
    """No capacity was available within the configured bounded queue."""
    def __init__(self, message: str, wait_ms: float = 0):
        super().__init__(message)
        self.wait_ms = wait_ms


class BoundedAdmission:
    def __init__(self, *, max_inflight: int = 4, max_waiters: int = 16, wait_timeout_s: float = 30):
        if max_inflight < 1 or max_waiters < 0 or wait_timeout_s <= 0:
            raise ValueError("Invalid admission limits")
        self.max_inflight = max_inflight
        self.max_waiters = max_waiters
        self.wait_timeout_s = wait_timeout_s
        self._condition = threading.Condition()
        self._active = 0
        self._waiting = 0

    @contextmanager
    def acquire(self):
        start = time.monotonic()
        with self._condition:
            if self._active >= self.max_inflight:
                if self._waiting >= self.max_waiters:
                    raise AdmissionRejected("Model request queue is full", (time.monotonic() - start) * 1000)
                self._waiting += 1
                try:
                    deadline = start + self.wait_timeout_s
                    while self._active >= self.max_inflight:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise AdmissionRejected("Model request queue wait timed out", (time.monotonic() - start) * 1000)
                        self._condition.wait(remaining)
                finally:
                    self._waiting -= 1
            self._active += 1
        try:
            yield (time.monotonic() - start) * 1000
        finally:
            with self._condition:
                self._active -= 1
                self._condition.notify()


def admission_from_env() -> BoundedAdmission:
    return BoundedAdmission(
        max_inflight=int(os.getenv("TEXA_LLM_MAX_INFLIGHT", "4")),
        max_waiters=int(os.getenv("TEXA_LLM_MAX_WAITERS", "16")),
        wait_timeout_s=float(os.getenv("TEXA_LLM_QUEUE_TIMEOUT_S", "30")),
    )


def event(name: str, *, duration_ms: float, observer=None, **safe_dimensions):
    """Emit only numeric timings and caller-selected safe dimensions (never prompt/key)."""
    record = {"event": name, "duration_ms": round(duration_ms, 2), **safe_dimensions}
    if observer is not None:
        observer(record)
    return record
