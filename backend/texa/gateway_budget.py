"""Runtime-level gateway request accounting and protected configuration."""
from __future__ import annotations

import fcntl
import json
import os
import stat
import uuid
from pathlib import Path


class BudgetExceededError(RuntimeError):
    """No further calls can be admitted under the authorized spending cap."""


def validate_credentials_path(path: Path, runtime_dir: Path) -> Path:
    path = path.resolve()
    path.relative_to(runtime_dir.resolve())
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError("Credentials must be owner-only (chmod 600)")
    return path


def update_ledger(ledger_path: Path, lock_path: Path, *, model: str, input_price: float,
                  output_price: float, max_usd: float, reserve: float = 0,
                  release: float = 0, actual: float = 0, usage=None,
                  reservation_id: str | None = None) -> dict:
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
                "reservations": {}, "legacy_reserved_usd": 0,
            }
            data.setdefault("reservations", {})
            data.setdefault("legacy_reserved_usd", data.get("reserved_usd", 0))
            if (data["model"], data["input_usd_per_token"], data["output_usd_per_token"]) != (
                model, input_price, output_price
            ):
                raise ValueError("Ledger model/prices changed; review cost before a new study")
            ceiling = min(float(data["max_usd"]), max_usd)
            if reservation_id:
                reservations = data["reservations"]
                if reserve:
                    if reservation_id in reservations:
                        raise ValueError("Duplicate budget reservation id")
                    reservations[reservation_id] = reserve
                if release:
                    held = reservations.get(reservation_id)
                    if held is None or release > held:
                        raise RuntimeError("Unknown or insufficient budget reservation")
                    remaining = held - release
                    if remaining:
                        reservations[reservation_id] = remaining
                    else:
                        del reservations[reservation_id]
            post_reserved = data["reserved_usd"] - release + reserve
            post_spent = data["spent_estimated_usd"] + actual
            if release > data["reserved_usd"] or post_spent + post_reserved > ceiling:
                raise BudgetExceededError("Authorized dollar budget exhausted")
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


class GatewayBudgetRequestError(Exception):
    """Sanitized provider failure carrying only its bounded-retry classification."""
    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class GatewayBudgetGuard:
    """Per-logical-call budget guard; uncertain calls retain their reservation."""
    def __init__(self, ledger_path: Path, model: str, input_price: float, output_price: float, max_usd: float):
        self.ledger_path = ledger_path
        self.lock_path = ledger_path.with_suffix('.lock')
        self.model, self.input_price = model, input_price
        self.output_price, self.max_usd = output_price, max_usd

    def _update(self, **kwargs):
        return update_ledger(self.ledger_path, self.lock_path, model=self.model,
                             input_price=self.input_price, output_price=self.output_price,
                             max_usd=self.max_usd, **kwargs)

    def __call__(self, *, model, system, prompt, schema, max_tokens, invoke, **_):
        if model != self.model:
            raise ValueError("Only the authorized model can be used")
        payload = (system + prompt + json.dumps(schema, ensure_ascii=False)).encode("utf-8")
        reservation = 2 * ((len(payload) + 8192) * self.input_price + max_tokens * self.output_price)
        call_id = uuid.uuid4().hex
        self._update(reserve=reservation, reservation_id=call_id)
        try:
            text, usage, finish = invoke()
            if usage[0] is None or usage[2] is None:
                raise ValueError("Provider returned no billable token usage")
            actual = usage[0] * self.input_price + usage[2] * self.output_price
            self._update(release=reservation, actual=actual, usage=usage, reservation_id=call_id)
            return text, usage, finish
        except Exception as original:
            status = getattr(original, "status_code", None)
            transient_status = status in (408, 409, 425, 429, 500, 502, 503, 504)
            error_name = type(original).__name__.lower()
            transient_transport = any(part in error_name for part in ("timeout", "connection", "network", "transport"))
            raise GatewayBudgetRequestError(
                "Gateway request failed; conservative budget reservation retained",
                retryable=transient_status or transient_transport,
            ) from None


def configure_gateway_from_environment(runtime_dir: Path) -> bool:
    """Install the protected gateway guard in app and isolated CLI processes."""
    credentials_key = "TEXA_GATEWAY_BUDGET_CREDENTIALS"
    if not os.environ.get(credentials_key):
        return False
    credential_path = validate_credentials_path(Path(os.environ[credentials_key]), runtime_dir)
    ledger_path = Path(os.environ.get("TEXA_GATEWAY_BUDGET_LEDGER", runtime_dir / "gateway-cost-ledger.json")).resolve()
    ledger_path.relative_to(runtime_dir.resolve())
    secret = json.loads(credential_path.read_text())
    model = secret["model"]
    input_price_env = os.environ.get("TEXA_GATEWAY_INPUT_PRICE")
    output_price_env = os.environ.get("TEXA_GATEWAY_OUTPUT_PRICE")
    if bool(input_price_env) != bool(output_price_env):
        raise ValueError("Both gateway token prices must be configured together")
    if input_price_env:
        prices = (float(input_price_env), float(output_price_env))
    else:
        try:
            import httpx
            base_url = secret["base_url"]
            response = httpx.get(base_url.removesuffix("/v1") + "/model/info",
                headers={"Authorization": "Bearer " + secret["api_key"]}, timeout=20)
            response.raise_for_status()
            info = next(row["model_info"] for row in response.json()["data"] if row["model_name"] == model)
            prices = (float(info["input_cost_per_token"]), float(info["output_cost_per_token"]))
        except Exception:
            raise ValueError("Could not verify protected gateway pricing") from None
    if min(prices) <= 0:
        raise ValueError("Gateway token prices must be positive")
    max_usd = float(os.environ.get("TEXA_GATEWAY_MAX_USD", secret["max_usd"]))
    if max_usd <= 0 or max_usd > float(secret["max_usd"]):
        raise ValueError("Child gateway budget may not exceed protected authorized budget")
    from . import llm
    connection = {"provider": "openai", "api_key": secret["api_key"], "base_url": secret["base_url"],
                  "allowed_models": [model], "default_model": model, "max_output_tokens": 4096,
                  "daily_token_limit": 0, "answer_language": "auto"}
    llm.get_connection = lambda with_key=False: dict(connection) if with_key else {
        k: v for k, v in connection.items() if k != "api_key"}
    llm.REQUEST_GUARD = GatewayBudgetGuard(ledger_path, model, *prices, max_usd)
    return True
