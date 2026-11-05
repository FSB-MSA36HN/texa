"""LLM provider layer. One function for every model call: structured JSON in, validated JSON out.
Providers: Gemini, Anthropic, OpenAI. Each takes an optional base_url, so an organisation gateway that speaks
one of these APIs (LiteLLM, OpenRouter, Azure, an internal proxy...) is just that provider with another URL."""
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import jsonschema
from cryptography.fernet import Fernet, InvalidToken

from . import db
from .runtime_guard import AdmissionRejected, admission_from_env, event

PROVIDERS = {"gemini": "Google Gemini", "anthropic": "Anthropic Claude", "openai": "OpenAI (hoặc gateway tương thích OpenAI)"}
ENV_KEYS = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
TIMEOUT_S = 90
MAX_PROVIDER_ATTEMPTS = 2

# Optional process-local policy hook. The gateway evaluation runner installs a
# durable budget adapter here; normal app calls use the same guarded request
# path without a spend ledger.
REQUEST_GUARD = None
ADMISSION = admission_from_env()
_runtime_observer = ContextVar("texa_runtime_observer", default=None)


@contextmanager
def runtime_observer_scope(observer):
    """Bind runtime timing events to the current request/thread without global races."""
    token = _runtime_observer.set(observer)
    try:
        yield
    finally:
        _runtime_observer.reset(token)


def _emit_runtime_event(name, *, duration_ms, **dimensions):
    event(name, duration_ms=duration_ms, observer=_runtime_observer.get(), **dimensions)


class LLMError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


# ---------------------------------------------------------------------------
# API key storage (Fernet; key from TEXA_SECRET_KEY or a local file created once)
# ---------------------------------------------------------------------------
def _fernet() -> Fernet:
    key = os.environ.get("TEXA_SECRET_KEY")
    if not key:
        path = Path(os.environ.get("TEXA_SECRET_FILE", Path(__file__).resolve().parents[1] / ".secret_key"))
        if not path.exists():
            path.write_text(Fernet.generate_key().decode())
            path.chmod(0o600)
        key = path.read_text().strip()
    return Fernet(key.encode())


def _env_connection(with_key: bool) -> dict | None:
    """First provider with a key in the environment; its SDK also reads <PROVIDER>_BASE_URL itself."""
    for provider, var in ENV_KEYS.items():
        if os.environ.get(var):
            row = {"provider": provider, "base_url": os.environ.get("TEXA_BASE_URL"), "allowed_models": [],
                   "default_model": os.environ.get("TEXA_DEFAULT_MODEL"), "max_output_tokens": 8192,
                   "daily_token_limit": 0, "answer_language": "auto", "from_env": True}
            if with_key:
                row["api_key"] = os.environ[var]
            return row
    return None


def get_connection(with_key: bool = False) -> dict | None:
    with db.app_conn() as conn:
        row = conn.execute("SELECT * FROM app.model_connection WHERE id = 1").fetchone()
    if row is None:
        return _env_connection(with_key)
    row = dict(row)
    encrypted = row.pop("encrypted_api_key")
    if with_key:
        try:
            row["api_key"] = _fernet().decrypt(encrypted.encode()).decode()
        except InvalidToken:
            raise LLMError("NO_KEY", "The saved API key cannot be decrypted (TEXA_SECRET_KEY changed). Enter the key again.")
    return row


def save_connection(provider: str, api_key: str | None, base_url: str | None, allowed_models: list[str],
                    default_model: str | None, max_output_tokens: int, daily_token_limit: int, answer_language: str) -> None:
    if provider not in PROVIDERS:
        raise LLMError("BAD_PROVIDER", f"Unsupported provider {provider!r}.")
    with db.app_conn() as conn:
        existing = conn.execute("SELECT provider, encrypted_api_key FROM app.model_connection WHERE id = 1").fetchone()
        if api_key:
            encrypted = _fernet().encrypt(api_key.encode()).decode()
        elif existing and existing["provider"] == provider:
            encrypted = existing["encrypted_api_key"]
        else:
            raise LLMError("NO_KEY", "An API key is required.")
        conn.execute(
            """INSERT INTO app.model_connection (id, provider, encrypted_api_key, base_url, allowed_models, default_model,
                 max_output_tokens, daily_token_limit, answer_language, updated_at)
               VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, now())
               ON CONFLICT (id) DO UPDATE SET provider = EXCLUDED.provider, encrypted_api_key = EXCLUDED.encrypted_api_key,
                 base_url = EXCLUDED.base_url, allowed_models = EXCLUDED.allowed_models, default_model = EXCLUDED.default_model,
                 max_output_tokens = EXCLUDED.max_output_tokens, daily_token_limit = EXCLUDED.daily_token_limit,
                 answer_language = EXCLUDED.answer_language, updated_at = now()""",
            (provider, encrypted, base_url or None, json.dumps(allowed_models), default_model, max_output_tokens,
             daily_token_limit, answer_language),
        )


def delete_connection() -> None:
    with db.app_conn() as conn:
        conn.execute("DELETE FROM app.model_connection WHERE id = 1")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _map_error(e: Exception) -> LLMError:
    # Gemini errors carry `code`; the Anthropic and OpenAI SDK errors carry `status_code`.
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    text = str(e)
    if code in (401, 403) or "API_KEY_INVALID" in text or "PERMISSION_DENIED" in text:
        return LLMError("AUTH", "The provider rejected the API key.")
    if code == 429 or "RESOURCE_EXHAUSTED" in text:
        return LLMError("QUOTA", "The provider's rate limit or quota was reached. Try again shortly.")
    if code == 404:
        return LLMError("BAD_MODEL", "This model is not available for the API key.")
    if "timed out" in text.lower() or "timeout" in text.lower():
        return LLMError("TIMEOUT", "The model took too long to answer.")
    from .gateway_budget import BudgetExceededError
    if isinstance(e, BudgetExceededError):
        return LLMError("BUDGET_EXHAUSTED", "The authorized model budget is exhausted; pending charges remain reserved.")
    return LLMError("PROVIDER_ERROR", "The model provider could not complete the request. Please retry later.")


def _api_schema(schema):
    """Providers accept JSON Schema but not every keyword; bounds are enforced locally afterwards."""
    if isinstance(schema, dict):
        return {k: _api_schema(v) for k, v in schema.items() if k not in ("maxItems", "minItems", "maxLength")}
    if isinstance(schema, list):
        return [_api_schema(s) for s in schema]
    return schema


# Each provider: _call_<p>(conn, model, system, prompt, schema, name, max_tokens) -> (text, usage, finish)
# usage = (input_tokens, cached_tokens, output_tokens); finish in {"ok", "truncated", "refused"}.

# ---- Gemini ----------------------------------------------------------------
def _gemini_client(api_key: str, base_url: str | None):
    from google import genai
    from google.genai import types
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000, base_url=base_url))


def _gemini_models(api_key, base_url):
    client = _gemini_client(api_key, base_url)  # keep a reference: the pager reuses the client lazily
    out = []
    for m in client.models.list():
        actions = m.supported_actions or []
        name = (m.name or "").removeprefix("models/")
        if "generateContent" not in actions or not name.startswith("gemini") or any(
                x in name for x in ("embedding", "image", "tts", "audio", "live", "veo", "imagen")):
            continue
        out.append({"id": name, "label": m.display_name or name})
    return out


def _call_gemini(conn, model, system, prompt, schema, name, max_tokens):
    from google.genai import types
    config = types.GenerateContentConfig(system_instruction=system, temperature=0, max_output_tokens=max_tokens,
                                         response_mime_type="application/json", response_json_schema=_api_schema(schema))
    resp = _gemini_client(conn["api_key"], conn.get("base_url")).models.generate_content(
        model=model, contents=prompt, config=config)
    u = resp.usage_metadata
    usage = (getattr(u, "prompt_token_count", None), getattr(u, "cached_content_token_count", None),
             (getattr(u, "candidates_token_count", 0) or 0) + (getattr(u, "thoughts_token_count", 0) or 0))
    finish = str(getattr((resp.candidates or [None])[0], "finish_reason", "") or "")
    status = "truncated" if "MAX_TOKENS" in finish else "refused" if ("SAFETY" in finish or "PROHIBITED" in finish) else "ok"
    return resp.text or "", usage, status


# ---- Anthropic -------------------------------------------------------------
def _anthropic_client(api_key: str, base_url: str | None):
    import anthropic
    return anthropic.Anthropic(api_key=api_key, base_url=base_url or None, timeout=TIMEOUT_S, max_retries=0)


def _anthropic_models(api_key, base_url):
    return [{"id": m.id, "label": m.display_name or m.id} for m in _anthropic_client(api_key, base_url).models.list()]


def _call_anthropic(conn, model, system, prompt, schema, name, max_tokens):
    # No temperature: current Claude models reject sampling parameters.
    resp = _anthropic_client(conn["api_key"], conn.get("base_url")).messages.create(
        model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": _api_schema(schema)}})
    u = resp.usage
    usage = (u.input_tokens, getattr(u, "cache_read_input_tokens", None), u.output_tokens)
    text = next((b.text for b in resp.content if b.type == "text"), "")
    status = {"max_tokens": "truncated", "refusal": "refused"}.get(resp.stop_reason, "ok")
    return text, usage, status


# ---- OpenAI and OpenAI-compatible gateways -----------------------------------
def _openai_client(api_key: str, base_url: str | None):
    import openai
    return openai.OpenAI(api_key=api_key, base_url=base_url or None, timeout=TIMEOUT_S, max_retries=0)


def _openai_models(api_key, base_url):
    skip = ("embedding", "tts", "whisper", "dall-e", "moderation", "image", "audio", "realtime", "transcribe", "babbage", "davinci")
    return [{"id": m.id, "label": m.id} for m in _openai_client(api_key, base_url).models.list()
            if not any(x in m.id for x in skip)]


def _call_openai(conn, model, system, prompt, schema, name, max_tokens):
    import openai
    client = _openai_client(conn["api_key"], conn.get("base_url"))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    # No temperature: reasoning models (o-series, gpt-5) only accept the default.
    try:
        resp = client.chat.completions.create(
            model=model, messages=messages, max_completion_tokens=max_tokens,
            response_format={"type": "json_schema", "json_schema": {"name": name, "schema": _api_schema(schema), "strict": True}})
    except openai.BadRequestError as exc:
        detail = str(exc).lower()
        if not (("json_schema" in detail or "response_format" in detail)
                and any(word in detail for word in ("not support", "unsupported", "not available"))):
            raise
        # Explicit capability negotiation only; other 400 errors must not be retried.
        # ponytail: gateway/model without json_schema support → plain JSON mode + schema in the prompt; validated locally.
        messages[0]["content"] = f"{system}\n\nReturn only a JSON object matching this JSON Schema:\n{json.dumps(schema)}"
        resp = client.chat.completions.create(model=model, messages=messages, max_completion_tokens=max_tokens,
                                              response_format={"type": "json_object"})
    choice = resp.choices[0]
    u = resp.usage
    details = getattr(u, "prompt_tokens_details", None) if u else None
    usage = (getattr(u, "prompt_tokens", None), getattr(details, "cached_tokens", None), getattr(u, "completion_tokens", None))
    status = ("refused" if getattr(choice.message, "refusal", None) or choice.finish_reason == "content_filter"
              else "truncated" if choice.finish_reason == "length" else "ok")
    return choice.message.content or "", usage, status


_MODELS = {"gemini": _gemini_models, "anthropic": _anthropic_models, "openai": _openai_models}
_CALLS = {"gemini": _call_gemini, "anthropic": _call_anthropic, "openai": _call_openai}


# Configure the ordinary application/CLI path from an owner-only file path.
# No key is accepted from environment, and absence of the variable is a no-op.
if os.environ.get("TEXA_GATEWAY_BUDGET_CREDENTIALS"):
    from .gateway_budget import configure_gateway_from_environment
    configure_gateway_from_environment(Path(__file__).resolve().parents[2] / ".runtime")


def _transient_provider_error(exc: Exception) -> bool:
    """Retry only transport/server failures; never retry auth, quota or bad requests."""
    if getattr(exc, "retryable", False):
        return True
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status in (408, 409, 425, 429, 500, 502, 503, 504)
    name = type(exc).__name__.lower()
    return any(part in name for part in ("timeout", "connection", "network", "transport"))


def _provider_request(provider, conn, model, system, prompt, schema, name, max_tokens, request_guard=None):
    """One logical request with bounded retries; SDK-level retries are disabled."""
    import random
    for attempt in range(MAX_PROVIDER_ATTEMPTS):
        try:
            invoke = lambda: _CALLS[provider](conn, model, system, prompt, schema, name, max_tokens)
            if request_guard is None:
                return invoke()
            return request_guard(provider=provider, model=model, system=system, prompt=prompt,
                                 schema=schema, name=name, max_tokens=max_tokens,
                                 attempt=attempt + 1, invoke=invoke)
        except Exception as exc:
            if attempt + 1 >= MAX_PROVIDER_ATTEMPTS or not _transient_provider_error(exc):
                raise
            time.sleep(min(0.25 * (2 ** attempt) + random.random() * 0.1, 1.0))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def discover_models(provider: str, api_key: str, base_url: str | None = None) -> list[dict]:
    """Text-generation models the key can use, newest-looking first."""
    if provider not in PROVIDERS:
        raise LLMError("BAD_PROVIDER", f"Unsupported provider {provider!r}.")
    try:
        models = _MODELS[provider](api_key, base_url or None)
    except Exception as e:
        raise _map_error(e)
    return sorted(models, key=lambda m: m["id"], reverse=True)


def _today_tokens() -> int:
    with db.app_conn() as conn:
        row = conn.execute("SELECT coalesce(sum(coalesce(input_tokens,0) + coalesce(output_tokens,0)), 0) AS n "
                           "FROM app.llm_usage WHERE created_at >= date_trunc('day', now())").fetchone()
    return int(row["n"])


def generate_structured(*, model: str | None, system: str, prompt: str, schema: dict, name: str,
                        turn_id=None, max_output_tokens: int | None = None) -> dict:
    conn = get_connection(with_key=True)
    if conn is None:
        raise LLMError("NO_KEY", "No model is connected. Add an API key in Settings.")
    model = model or conn.get("default_model")
    if not model:
        raise LLMError("BAD_MODEL", "No model selected. Pick a default model in Settings.")
    allowed = conn.get("allowed_models") or []
    if allowed and model not in allowed:
        raise LLMError("BAD_MODEL", f"Model {model} is not allowed. Choose one of: {', '.join(allowed)}.")
    if conn.get("daily_token_limit") and _today_tokens() >= conn["daily_token_limit"]:
        raise LLMError("DAILY_LIMIT", "Today's token budget is used up. Raise it in Settings or try tomorrow.")

    started = time.monotonic()
    try:
        max_tokens = max_output_tokens or conn.get("max_output_tokens") or 8192
        invoke = lambda: _provider_request(conn["provider"], conn, model, system, prompt, schema, name,
                                           max_tokens, REQUEST_GUARD)
        provider_started = None
        with ADMISSION.acquire() as queue_ms:
            _emit_runtime_event("llm_queue_wait", duration_ms=queue_ms, call_name=name)
            provider_started = time.monotonic()
            text, (tokens_in, tokens_cached, tokens_out), status = invoke()
            provider_ms = (time.monotonic() - provider_started) * 1000
    except AdmissionRejected as e:
        _emit_runtime_event("llm_queue_wait", duration_ms=e.wait_ms, call_name=name, outcome="rejected")
        raise LLMError("OVERLOADED", str(e)) from None
    except LLMError:
        if provider_started is not None:
            _emit_runtime_event("llm_provider_total", duration_ms=(time.monotonic() - provider_started) * 1000,
                                call_name=name, model=model, outcome="failed")
        raise
    except Exception as e:
        if provider_started is not None:
            _emit_runtime_event("llm_provider_total", duration_ms=(time.monotonic() - provider_started) * 1000,
                                call_name=name, model=model, outcome="failed")
        raise _map_error(e)
    ms = int((time.monotonic() - started) * 1000)
    _emit_runtime_event("llm_provider_total", duration_ms=provider_ms, call_name=name,
                        model=model, input_tokens=tokens_in, output_tokens=tokens_out, outcome="success")
    with db.app_conn() as c:
        c.execute(
            "INSERT INTO app.llm_usage (turn_id, call_name, model, input_tokens, cached_tokens, output_tokens, ms) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (turn_id, name, model, tokens_in, tokens_cached, tokens_out, ms),
        )
    if status == "truncated":
        raise LLMError("MODEL_OUTPUT_TRUNCATED", "The model's answer was cut off. Try a simpler question or raise the output limit.")
    if status == "refused":
        raise LLMError("MODEL_REFUSED", "The model declined to answer.")
    try:
        data = json.loads(text)
        jsonschema.validate(data, schema)
    except (json.JSONDecodeError, jsonschema.ValidationError) as e:
        raise LLMError("MODEL_OUTPUT_INVALID", f"The model returned an unusable answer ({str(e)[:160]}). Retry or rephrase.")
    return data
