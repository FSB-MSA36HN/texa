"""Step progress for a run: each step reports running -> done/failed with its duration and a note."""
import time
from contextlib import contextmanager


class Cancelled(Exception):
    pass


class _Step:
    def __init__(self):
        self.text = None

    def note(self, text):
        self.text = text


class Progress:
    """`emit(event)` receives {"step", "status", "ms", "note"}; `cancelled()` is polled between steps."""

    def __init__(self, emit=lambda event: None, cancelled=lambda: False):
        self.emit, self.cancelled = emit, cancelled

    @contextmanager
    def __call__(self, name):
        if self.cancelled():
            raise Cancelled()
        started = time.monotonic()
        self.emit({"step": name, "status": "running"})
        s = _Step()
        try:
            yield s
        except BaseException:
            self.emit({"step": name, "status": "failed", "ms": int((time.monotonic() - started) * 1000), "note": s.text})
            raise
        self.emit({"step": name, "status": "done", "ms": int((time.monotonic() - started) * 1000), "note": s.text})
