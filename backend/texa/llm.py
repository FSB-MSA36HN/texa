"""LLM provider layer. One function for every model call: structured JSON in, validated JSON out.
Gemini only for now; another provider is one more branch in `_call`."""
import json
import os
import time
from pathlib import Path

import jsonschema
from cryptography.fernet import Fernet, InvalidToken

from . import db

PROVIDERS = {"gemini": "Google Gemini"}
TIMEOUT_S = 90


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


def get_connection(with_key: bool = False) -> dict | None:
    with db.app_conn() as conn:
        row = conn.execute("SELECT * FROM app.model_connection WHERE id = 1").fetchone()
    if row is None:
        if os.environ.get("GEMINI_API_KEY"):
            row = {"provider": "gemini", "allowed_models": [], "default_model": os.environ.get("TEXA_DEFAULT_MODEL"),
                   "max_output_tokens": 8192, "daily_token_limit": 0, "answer_language": "auto", "from_env": True}
            if with_key:
                row["api_key"] = os.environ["GEMINI_API_KEY"]
            return row
        return None
    row = dict(row)
    encrypted = row.pop("encrypted_api_key")
    if with_key:
        try:
            row["api_key"] = _fernet().decrypt(encrypted.encode()).decode()
        except InvalidToken:
            raise LLMError("NO_KEY", "The saved API key cannot be decrypted (TEXA_SECRET_KEY changed). Enter the key again.")
    return row


def save_connection(provider: str, api_key: str | None, allowed_models: list[str], default_model: str | None,
                    max_output_tokens: int, daily_token_limit: int, answer_language: str) -> None:
    if provider not in PROVIDERS:
        raise LLMError("BAD_PROVIDER", f"Unsupported provider {provider!r}.")
    with db.app_conn() as conn:
        existing = conn.execute("SELECT encrypted_api_key FROM app.model_connection WHERE id = 1").fetchone()
        if api_key:
            encrypted = _fernet().encrypt(api_key.encode()).decode()
        elif existing:
            encrypted = existing["encrypted_api_key"]
        else:
            raise LLMError("NO_KEY", "An API key is required.")
        conn.execute(
            """INSERT INTO app.model_connection (id, provider, encrypted_api_key, allowed_models, default_model,
                 max_output_tokens, daily_token_limit, answer_language, updated_at)
               VALUES (1, %s, %s, %s, %s, %s, %s, %s, now())
               ON CONFLICT (id) DO UPDATE SET provider = EXCLUDED.provider, encrypted_api_key = EXCLUDED.encrypted_api_key,
                 allowed_models = EXCLUDED.allowed_models, default_model = EXCLUDED.default_model,
                 max_output_tokens = EXCLUDED.max_output_tokens, daily_token_limit = EXCLUDED.daily_token_limit,
                 answer_language = EXCLUDED.answer_language, updated_at = now()""",
            (provider, encrypted, json.dumps(allowed_models), default_model, max_output_tokens, daily_token_limit, answer_language),
        )


def delete_connection() -> None:
    with db.app_conn() as conn:
        conn.execute("DELETE FROM app.model_connection WHERE id = 1")


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
def _client(api_key: str):
    from google import genai
    from google.genai import types
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000))


def _map_error(e: Exception) -> LLMError:
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
    return LLMError("PROVIDER_ERROR", f"The model call failed: {text[:300]}")


def discover_models(provider: str, api_key: str) -> list[dict]:
    """Text-generation models the key can use, newest-looking first."""
    if provider != "gemini":
        raise LLMError("BAD_PROVIDER", f"Unsupported provider {provider!r}.")
    try:
        client = _client(api_key)  # keep a reference: the pager reuses the client lazily
        models = list(client.models.list())
    except Exception as e:
        raise _map_error(e)
    out = []
    for m in models:
        actions = m.supported_actions or []
        name = (m.name or "").removeprefix("models/")
        if "generateContent" not in actions or not name.startswith("gemini") or any(
                x in name for x in ("embedding", "image", "tts", "audio", "live", "veo", "imagen")):
            continue
        out.append({"id": name, "label": m.display_name or name, "input_token_limit": m.input_token_limit,
                    "output_token_limit": m.output_token_limit})
    return sorted(out, key=lambda m: m["id"], reverse=True)


def _gemini_schema(schema):
    """Gemini accepts JSON Schema but not every keyword; bounds are enforced locally afterwards."""
    if isinstance(schema, dict):
        return {k: _gemini_schema(v) for k, v in schema.items() if k not in ("maxItems", "minItems", "maxLength")}
    if isinstance(schema, list):
        return [_gemini_schema(s) for s in schema]
    return schema


def _today_tokens() -> int:
    with db.app_conn() as conn:
        row = conn.execute("SELECT coalesce(sum(coalesce(input_tokens,0) + coalesce(output_tokens,0)), 0) AS n "
                           "FROM app.llm_usage WHERE created_at >= date_trunc('day', now())").fetchone()
    return int(row["n"])


def generate_structured(*, model: str | None, system: str, prompt: str, schema: dict, name: str,
                        turn_id=None, max_output_tokens: int | None = None) -> dict:
    conn = get_connection(with_key=True)
    if conn is None:
        raise LLMError("NO_KEY", "No model is connected. Add a Gemini API key in Settings.")
    model = model or conn.get("default_model")
    if not model:
        raise LLMError("BAD_MODEL", "No model selected. Pick a default model in Settings.")
    allowed = conn.get("allowed_models") or []
    if allowed and model not in allowed:
        raise LLMError("BAD_MODEL", f"Model {model} is not allowed. Choose one of: {', '.join(allowed)}.")
    if conn.get("daily_token_limit") and _today_tokens() >= conn["daily_token_limit"]:
        raise LLMError("DAILY_LIMIT", "Today's token budget is used up. Raise it in Settings or try tomorrow.")

    from google.genai import types
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=0,
        max_output_tokens=max_output_tokens or conn.get("max_output_tokens") or 8192,
        response_mime_type="application/json",
        response_json_schema=_gemini_schema(schema),
    )
    started = time.monotonic()
    try:
        client = _client(conn["api_key"])
        resp = client.models.generate_content(model=model, contents=prompt, config=config)
    except Exception as e:
        raise _map_error(e)
    ms = int((time.monotonic() - started) * 1000)
    usage = resp.usage_metadata
    with db.app_conn() as c:
        c.execute(
            "INSERT INTO app.llm_usage (turn_id, call_name, model, input_tokens, cached_tokens, output_tokens, ms) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (turn_id, name, model, getattr(usage, "prompt_token_count", None), getattr(usage, "cached_content_token_count", None),
             (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0), ms),
        )
    candidate = (resp.candidates or [None])[0]
    finish = str(getattr(candidate, "finish_reason", "") or "")
    text = resp.text or ""
    if "MAX_TOKENS" in finish:
        raise LLMError("MODEL_OUTPUT_TRUNCATED", "The model's answer was cut off. Try a simpler question or raise the output limit.")
    if "SAFETY" in finish or "PROHIBITED" in finish:
        raise LLMError("MODEL_REFUSED", "The model declined to answer.")
    try:
        data = json.loads(text)
        jsonschema.validate(data, schema)
    except (json.JSONDecodeError, jsonschema.ValidationError) as e:
        raise LLMError("MODEL_OUTPUT_INVALID", f"The model returned an unusable answer ({str(e)[:160]}). Retry or rephrase.")
    return data
