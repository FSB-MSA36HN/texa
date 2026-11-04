"""Offline-testable helpers for the bounded gateway evaluation wrapper."""
from __future__ import annotations

import fcntl
import json
import os
import stat
from pathlib import Path


def validate_credentials_path(path: Path, runtime_dir: Path) -> Path:
    path = path.resolve()
    path.relative_to(runtime_dir.resolve())
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("Credentials must be owner-only (chmod 600)")
    return path


def update_ledger(ledger_path: Path, lock_path: Path, *, model: str, input_price: float,
                  output_price: float, max_usd: float, reserve: float = 0,
                  release: float = 0, actual: float = 0, usage=None) -> dict:
    """Atomically reserve or settle estimated spend under a cross-process lock."""
    for amount in (reserve, release, actual):
        if amount < 0:
            raise ValueError("Budget amounts must be non-negative")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = json.loads(ledger_path.read_text()) if ledger_path.exists() else {
                "model": model, "input_usd_per_token": input_price,
                "output_usd_per_token": output_price, "max_usd": max_usd,
                "spent_estimated_usd": 0, "reserved_usd": 0,
                "calls": 0, "input_tokens": 0, "output_tokens": 0,
            }
            if (data["model"], data["input_usd_per_token"], data["output_usd_per_token"]) != (
                model, input_price, output_price
            ):
                raise ValueError("Ledger model/prices changed; review cost before a new study")
            ceiling = min(float(data["max_usd"]), max_usd)
            # Check the post-operation state, including actual settlement cost.
            post_reserved = data["reserved_usd"] - release + reserve
            post_spent = data["spent_estimated_usd"] + actual
            if release > data["reserved_usd"] or post_spent + post_reserved > ceiling:
                raise RuntimeError("Authorized dollar budget exhausted")
            data["reserved_usd"] = post_reserved
            data["spent_estimated_usd"] = post_spent
            if usage is not None:
                data["calls"] += 1
                data["input_tokens"] += usage[0]
                data["output_tokens"] += usage[2]
            temporary = ledger_path.with_name(ledger_path.name + ".tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, ledger_path)
            return data
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
