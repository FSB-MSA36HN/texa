"""HTTP API for the chat UI."""
import asyncio
import json
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
def bootstrap():
    """Everything the UI needs on load: stores, what Texa knows, and the model connection (never the key)."""
    sources = catalog.load_sources(max_age=0)
    try:
        cat = catalog.published()
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
        "connection": _public_connection(),
        "providers": [{"id": k, "label": v} for k, v in llm.PROVIDERS.items()],
    }


def _public_connection():
    conn = llm.get_connection()
    if conn is None:
        return None
    return {k: conn.get(k) for k in ("provider", "allowed_models", "default_model", "max_output_tokens",
                                     "daily_token_limit", "answer_language", "from_env")} | {"has_key": True}


# ---- questions ------------------------------------------------------------
class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None
    model: str | None = Field(default=None, max_length=100)
    source_ids: list[str] = Field(default=[], max_length=3)


@app.post("/api/questions")
def post_question(body: AskBody):
    if llm.get_connection() is None:
        raise llm.LLMError("NO_KEY", "No model is connected. Add a Gemini API key in Settings.")
    return answer.ask(body.question, body.conversation_id, body.model, body.source_ids or None)


@app.get("/api/turns/{turn_id}")
def get_turn(turn_id: str):
    return answer.public_turn(answer.load_turn(turn_id))


@app.get("/api/turns/{turn_id}/stream")
async def stream_turn(turn_id: str, request: Request):
    """SSE: `step` events while the run works, then one `result` event with the saved turn."""
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
def post_answer(turn_id: str, body: AnswerBody):
    answer.answer_clarification(turn_id, body.answers)
    return {"ok": True}


@app.post("/api/turns/{turn_id}/retry")
def post_retry(turn_id: str):
    answer.load_turn(turn_id)
    answer.retry(turn_id)
    return {"ok": True}


@app.post("/api/turns/{turn_id}/cancel")
def post_cancel(turn_id: str):
    return {"cancelled": answer.cancel(turn_id)}


class VariantBody(BaseModel):
    metric_id: str = Field(max_length=100)


@app.post("/api/turns/{turn_id}/variant")
def post_variant(turn_id: str, body: VariantBody):
    answer.switch_variant(turn_id, body.metric_id)
    return {"ok": True}


@app.get("/api/turns/{turn_id}/full-result")
def get_full_result(turn_id: str):
    return answer.full_result(turn_id)


class FeedbackBody(BaseModel):
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=1000)


@app.post("/api/turns/{turn_id}/feedback")
def post_feedback(turn_id: str, body: FeedbackBody):
    answer.load_turn(turn_id)
    with db.app_conn() as conn:
        conn.execute("""INSERT INTO app.feedback (turn_id, rating, comment) VALUES (%s,%s,%s)
                        ON CONFLICT (turn_id) DO UPDATE SET rating = EXCLUDED.rating, comment = EXCLUDED.comment, created_at = now()""",
                     (turn_id, body.rating, body.comment or None))
    return {"ok": True}


# ---- conversations ----------------------------------------------------------
@app.get("/api/conversations")
def list_conversations():
    with db.app_conn() as conn:
        rows = conn.execute("SELECT id, title, updated_at FROM app.conversations ORDER BY updated_at DESC LIMIT 200").fetchall()
    return [{"id": str(r["id"]), "title": r["title"], "updated_at": r["updated_at"].isoformat()} for r in rows]


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str):
    with db.app_conn() as conn:
        conv = conn.execute("SELECT id, title FROM app.conversations WHERE id = %s", (conversation_id,)).fetchone()
        if conv is None:
            raise LookupError("conversation not found")
        turns = conn.execute("SELECT * FROM app.turns WHERE conversation_id = %s ORDER BY created_at", (conversation_id,)).fetchall()
    return {"id": str(conv["id"]), "title": conv["title"], "turns": [answer.public_turn(t) for t in turns]}


class TitleBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@app.patch("/api/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, body: TitleBody):
    with db.app_conn() as conn:
        conn.execute("UPDATE app.conversations SET title = %s WHERE id = %s", (body.title, conversation_id))
    return {"ok": True}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str):
    with db.app_conn() as conn:
        conn.execute("DELETE FROM app.conversations WHERE id = %s", (conversation_id,))
    return {"ok": True}


# ---- model connection ---------------------------------------------------------
class ConnectionBody(BaseModel):
    provider: str = "gemini"
    api_key: str | None = Field(default=None, max_length=500)
    allowed_models: list[str] = Field(default=[], max_length=50)
    default_model: str | None = None
    max_output_tokens: int = Field(default=8192, ge=256, le=65536)
    daily_token_limit: int = Field(default=0, ge=0)
    answer_language: Literal["auto", "vi", "en"] = "auto"


@app.get("/api/model-connection")
def get_connection():
    return _public_connection()


@app.put("/api/model-connection")
def put_connection(body: ConnectionBody):
    if body.default_model and body.allowed_models and body.default_model not in body.allowed_models:
        raise SpecError("invalid_connection", "The default model must be one of the allowed models.")
    llm.save_connection(body.provider, body.api_key, body.allowed_models, body.default_model, body.max_output_tokens,
                        body.daily_token_limit, body.answer_language)
    return _public_connection()


@app.delete("/api/model-connection")
def delete_connection():
    llm.delete_connection()
    return {"ok": True}


class DiscoverBody(BaseModel):
    provider: str = "gemini"
    api_key: str | None = Field(default=None, max_length=500)


@app.post("/api/model-connection/discover")
def discover(body: DiscoverBody):
    key = body.api_key or (llm.get_connection(with_key=True) or {}).get("api_key")
    if not key:
        raise llm.LLMError("NO_KEY", "Enter an API key first.")
    return {"models": llm.discover_models(body.provider, key)}


@app.get("/api/usage")
def usage():
    with db.app_conn() as conn:
        rows = conn.execute("""SELECT model, count(*) AS calls, sum(input_tokens) AS input_tokens, sum(cached_tokens) AS cached_tokens,
                                      sum(output_tokens) AS output_tokens FROM app.llm_usage
                               WHERE created_at >= date_trunc('day', now()) GROUP BY model""").fetchall()
    return {"today": rows}
