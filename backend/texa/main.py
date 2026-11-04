"""HTTP API for the chat UI."""
import asyncio
import hashlib
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import answer, catalog, db, llm
from .spec import SpecError


@asynccontextmanager
async def lifespan(app):
    _validate_shared_demo_config()
    db.migrate()
    with db.app_conn() as conn:
        # Runs live in this process; anything still "running" was cut off by a restart.
        conn.execute("""UPDATE app.turns SET status = 'error', state = state || '{"status": "error", "error":
                        {"code": "INTERRUPTED", "message": "The server restarted while this was running.", "retryable": true}}'::jsonb
                        WHERE status = 'running'""")
        published = conn.execute("SELECT 1 FROM app.catalog_versions LIMIT 1").fetchone()
    if not published:
        try:
            catalog.publish()
        except Exception as e:  # the warehouse may not be loaded yet; /api/bootstrap reports it
            print(f"catalog not published: {e}")
    yield


app = FastAPI(title="Texa", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:15173", "http://127.0.0.1:15173"],
                   allow_methods=["*"], allow_headers=["*"])


def _shared_demo() -> bool:
    return os.getenv("TEXA_SHARED_DEMO", "").lower() in {"1", "true", "yes"}


def _admin_token() -> str:
    return os.getenv("TEXA_ADMIN_TOKEN", "")


def _validate_shared_demo_config():
    if _shared_demo() and len(_admin_token()) < 24:
        raise RuntimeError("TEXA_SHARED_DEMO requires a TEXA_ADMIN_TOKEN of at least 24 characters")


@app.middleware("http")
async def _browser_session(request: Request, call_next):
    """Give each shared-demo browser a stable, HttpOnly identity without exposing it to JS."""
    session_id = request.cookies.get("texa_session")
    new_session = not session_id or len(session_id) < 40
    if new_session:
        session_id = secrets.token_urlsafe(32)
    request.state.browser_session_hash = hashlib.sha256(session_id.encode()).hexdigest()
    response = await call_next(request)
    if new_session:
        response.set_cookie("texa_session", session_id, httponly=True, secure=os.getenv("TEXA_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
                            samesite="lax", max_age=60 * 60 * 24 * 30, path="/")
    return response


def _session_hash(request: Request) -> str | None:
    return request.state.browser_session_hash if _shared_demo() else None


def _require_admin(request: Request):
    if _shared_demo():
        supplied = request.headers.get("authorization", "")
        expected = f"Bearer {_admin_token()}"
        if not secrets.compare_digest(supplied, expected):
            raise HTTPException(status_code=403, detail="Admin authorization required")


def _require_turn_owner(turn_id: str, request: Request):
    owner = _session_hash(request)
    if owner is None:
        return
    try:
        turn_id = str(uuid.UUID(turn_id))
    except (ValueError, TypeError, AttributeError):
        raise LookupError("turn not found") from None
    with db.app_conn() as conn:
        row = conn.execute("""SELECT 1 FROM app.turns t JOIN app.conversations c ON c.id=t.conversation_id
                             WHERE t.id=%s AND c.browser_session_hash=%s""", (turn_id, owner)).fetchone()
    if row is None:
        raise LookupError("turn not found")


def _require_conversation_owner(conversation_id: str, request: Request):
    owner = _session_hash(request)
    if owner is None:
        return
    try:
        conversation_id = str(uuid.UUID(conversation_id))
    except (ValueError, TypeError, AttributeError):
        raise LookupError("conversation not found") from None
    with db.app_conn() as conn:
        row = conn.execute("SELECT 1 FROM app.conversations WHERE id=%s AND browser_session_hash=%s", (conversation_id, owner)).fetchone()
    if row is None:
        raise LookupError("conversation not found")


@app.exception_handler(SpecError)
async def _spec_error(_, e: SpecError):
    return JSONResponse({"code": e.code, "message": e.message, "suggestions": e.suggestions}, status_code=409)


@app.exception_handler(llm.LLMError)
async def _llm_error(_, e: llm.LLMError):
    return JSONResponse({"code": e.code, "message": e.message}, status_code=400)


@app.exception_handler(LookupError)
async def _not_found(_, e: LookupError):
    return JSONResponse({"code": "not_found", "message": str(e)}, status_code=404)


# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/bootstrap")
def bootstrap(request: Request):
    """Everything the UI needs on load: stores, what Texa knows, and the model connection (never the key)."""
    sources = catalog.load_sources(max_age=0)
    try:
        cat = catalog.published()
        sources = catalog.scoped_sources(cat, sources)
        cat_info = {
            "version": cat.contract_version,
            "metrics": [{"id": m.id, "label": m.label, "description": m.description, "unit": m.unit, "synonyms": m.synonyms}
                        for m in cat.metrics],
            "dimensions": [{"id": d.id, "label": d.label, "description": d.description, "synonyms": d.synonyms}
                           for d in cat.dimensions],
            "examples": [q.question for q in cat.verified_questions],
            "coverage": {sid: {"metrics_missing": list(c["metrics_missing"]), "dimensions_missing": c["dimensions_missing"]}
                         for sid, c in catalog.coverage(cat, sources).items()},
        }
    except LookupError as e:
        cat_info = {"error": str(e)}
    return {
        "sources": [s.model_dump(include={"id", "label", "description", "currency", "min_date", "max_date", "row_count", "user_count"})
                    for s in sources.values()],
        "catalog": cat_info,
        "connection": _bootstrap_connection(),
        "providers": [{"id": k, "label": v} for k, v in llm.PROVIDERS.items()],
        "shared_demo": _shared_demo(),
        "read_only_settings": _shared_demo(),
    }


def _public_connection():
    conn = llm.get_connection()
    if conn is None:
        return None
    return {k: conn.get(k) for k in ("provider", "base_url", "allowed_models", "default_model", "max_output_tokens",
                                     "daily_token_limit", "answer_language", "from_env")} | {"has_key": True}


def _bootstrap_connection():
    connection = _public_connection()
    if _shared_demo() and connection:
        connection = dict(connection)
        connection.pop("base_url", None)
    return connection


# ---- questions ------------------------------------------------------------
class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    model: str | None = Field(default=None, max_length=100)
    source_ids: list[str] = Field(default=[], max_length=3)


@app.post("/api/questions")
def post_question(body: AskBody, request: Request):
    owner = _session_hash(request)
    if body.conversation_id and owner:
        _require_conversation_owner(body.conversation_id, request)
    connection = llm.get_connection()
    if connection is None:
        raise llm.LLMError("NO_KEY", "No model is connected. Add an API key in Settings.")
    if owner is None:
        return answer.ask(body.question, body.conversation_id, body.model, body.source_ids or None)
    selected_model = connection.get("default_model")
    if not selected_model or (body.model and body.model != selected_model):
        raise llm.LLMError("BAD_MODEL", "Shared demo uses the model selected by the organizer.")
    return answer.ask(body.question, body.conversation_id, selected_model, body.source_ids or None, owner_hash=owner)


@app.get("/api/turns/{turn_id}")
def get_turn(turn_id: str, request: Request):
    _require_turn_owner(turn_id, request)
    return answer.public_turn(answer.load_turn(turn_id))


@app.get("/api/turns/{turn_id}/stream")
async def stream_turn(turn_id: str, request: Request):
    """SSE: `step` events while the run works, then one `result` event with the saved turn."""
    _require_turn_owner(turn_id, request)
    answer.load_turn(turn_id)

    async def events():
        sent = 0
        while True:
            run = answer.RUNS.get(turn_id)
            if run is None:  # finished before this process started, or never ran here
                yield f"event: result\ndata: {json.dumps(answer.public_turn(answer.load_turn(turn_id)), default=str)}\n\n"
                return
            with run.lock:
                new = run.events[sent:]
            sent += len(new)
            for e in new:
                kind = "result" if e["step"] == "result" else "step"
                yield f"event: {kind}\ndata: {json.dumps(e.get('result', e), default=str)}\n\n"
                if kind == "result":
                    return
            if await request.is_disconnected():
                return
            if not new:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class AnswerBody(BaseModel):
    answers: dict[str, list[str]]


@app.post("/api/turns/{turn_id}/answer")
def post_answer(turn_id: str, body: AnswerBody, request: Request):
    _require_turn_owner(turn_id, request)
    answer.answer_clarification(turn_id, body.answers)
    return {"ok": True}


@app.post("/api/turns/{turn_id}/retry")
def post_retry(turn_id: str, request: Request):
    _require_turn_owner(turn_id, request)
    answer.load_turn(turn_id)
    answer.retry(turn_id)
    return {"ok": True}


class EditBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.post("/api/turns/{turn_id}/edit")
def post_edit(turn_id: str, body: EditBody, request: Request):
    _require_turn_owner(turn_id, request)
    return {"dropped": answer.edit(turn_id, body.question)}


@app.post("/api/turns/{turn_id}/cancel")
def post_cancel(turn_id: str, request: Request):
    _require_turn_owner(turn_id, request)
    return {"cancelled": answer.cancel(turn_id)}


class VariantBody(BaseModel):
    metric_id: str = Field(max_length=100)


@app.post("/api/turns/{turn_id}/variant")
def post_variant(turn_id: str, body: VariantBody, request: Request):
    _require_turn_owner(turn_id, request)
    answer.switch_variant(turn_id, body.metric_id)
    return {"ok": True}


@app.get("/api/turns/{turn_id}/full-result")
def get_full_result(turn_id: str, request: Request):
    _require_turn_owner(turn_id, request)
    return answer.full_result(turn_id)


class FeedbackBody(BaseModel):
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=1000)


@app.post("/api/turns/{turn_id}/feedback")
def post_feedback(turn_id: str, body: FeedbackBody, request: Request):
    _require_turn_owner(turn_id, request)
    answer.load_turn(turn_id)
    with db.app_conn() as conn:
        conn.execute("""INSERT INTO app.feedback (turn_id, rating, comment) VALUES (%s,%s,%s)
                        ON CONFLICT (turn_id) DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment, created_at = now()""",
                     (turn_id, body.rating, body.comment or None))
    return {"ok": True}


# ---- conversations ----------------------------------------------------------
@app.get("/api/conversations")
def list_conversations(request: Request):
    owner = _session_hash(request)
    with db.app_conn() as conn:
        if owner:
            rows = conn.execute("SELECT id, title, updated_at FROM app.conversations WHERE browser_session_hash=%s ORDER BY updated_at DESC LIMIT 200", (owner,)).fetchall()
        else:
            rows = conn.execute("SELECT id, title, updated_at FROM app.conversations ORDER BY updated_at DESC LIMIT 200").fetchall()
    return [{"id": str(r["id"]), "title": r["title"], "updated_at": r["updated_at"].isoformat()} for r in rows]


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request):
    _require_conversation_owner(conversation_id, request)
    with db.app_conn() as conn:
        conv = conn.execute("SELECT id, title FROM app.conversations WHERE id = %s", (conversation_id,)).fetchone()
        if conv is None:
            raise LookupError("conversation not found")
        turns = conn.execute("SELECT * FROM app.turns WHERE conversation_id = %s ORDER BY created_at", (conversation_id,)).fetchall()
    return {"id": str(conv["id"]), "title": conv["title"], "turns": [answer.public_turn(t) for t in turns]}


class TitleBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, body: TitleBody, request: Request):
    _require_conversation_owner(conversation_id, request)
    with db.app_conn() as conn:
        conn.execute("UPDATE app.conversations SET title = %s WHERE id = %s", (body.title, conversation_id))
    return {"ok": True}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, request: Request):
    _require_conversation_owner(conversation_id, request)
    with db.app_conn() as conn:
        conn.execute("DELETE FROM app.conversations WHERE id = %s", (conversation_id,))
    return {"ok": True}


# ---- model connection ---------------------------------------------------------
class ConnectionBody(BaseModel):
    provider: str = "gemini"
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500, pattern=r"^(https?://\S+)?$")
    allowed_models: list[str] = Field(default=[], max_length=50)
    default_model: str | None = None
    max_output_tokens: int = Field(default=8192, ge=256, le=65536)
    daily_token_limit: int = Field(default=0, ge=0)
    answer_language: Literal["auto", "vi", "en"] = "auto"


@app.get("/api/model-connection")
def get_connection(request: Request):
    _require_admin(request)
    return _public_connection()


@app.put("/api/model-connection")
def put_connection(body: ConnectionBody, request: Request):
    _require_admin(request)
    if body.default_model and body.allowed_models and body.default_model not in body.allowed_models:
        raise SpecError("invalid_connection", "The default model must be one of the allowed models.")
    llm.save_connection(body.provider, body.api_key, body.base_url, body.allowed_models, body.default_model, body.max_output_tokens,
                        body.daily_token_limit, body.answer_language)
    return _public_connection()


@app.delete("/api/model-connection")
def delete_connection(request: Request):
    _require_admin(request)
    llm.delete_connection()
    return {"ok": True}


class DiscoverBody(BaseModel):
    provider: str = "gemini"
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500, pattern=r"^(https?://\S+)?$")


@app.post("/api/model-connection/discover")
def discover(body: DiscoverBody, request: Request):
    _require_admin(request)
    saved = llm.get_connection(with_key=True) or {}
    # A saved key is only reused for the provider it was saved for.
    key = body.api_key or (saved.get("api_key") if saved.get("provider") == body.provider else None)
    if not key:
        raise llm.LLMError("NO_KEY", "Enter an API key first.")
    return {"models": llm.discover_models(body.provider, key, body.base_url)}


@app.get("/api/usage")
def usage(request: Request):
    _require_admin(request)
    with db.app_conn() as conn:
        rows = conn.execute("""SELECT model, count(*) AS calls, sum(input_tokens) AS input_tokens, sum(cached_tokens) AS cached_tokens,
                                      sum(output_tokens) AS output_tokens FROM app.llm_usage
                               WHERE created_at >= date_trunc('day', now()) GROUP BY model""").fetchall()
    return {"today": rows}
