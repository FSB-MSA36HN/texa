"""One question = one turn. Runs execute in a background thread and publish step events for the SSE stream."""
import json
import threading
import traceback

from . import catalog as catalog_mod
from . import clarify, db, insight, interpret, llm
from .pipeline import run_spec
from .progress import Cancelled, Progress
from .spec import SpecError

HISTORY_TURNS = 6
STORED_ROWS = 100


# ---------------------------------------------------------------------------
# Run registry (in-process; one API worker)
# ---------------------------------------------------------------------------
class Run:
    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.events: list[dict] = []
        self.done = False
        self.cancel = False
        self.lock = threading.Lock()

    def emit(self, event: dict):
        with self.lock:
            self.events.append(event)
        if event.get("status") in ("done", "failed"):
            with db.app_conn() as conn:
                conn.execute("INSERT INTO app.run_steps (turn_id, step, status, ms, note) VALUES (%s,%s,%s,%s,%s)",
                             (self.turn_id, event["step"], event["status"], event.get("ms"), event.get("note")))


RUNS: dict[str, Run] = {}  # ponytail: in-memory, single worker; move to Redis pub/sub if the API scales out


def _start(turn_id: str, work) -> Run:
    old = RUNS.get(turn_id)
    if old and not old.done:
        raise SpecError("busy", "This question is still running.")
    run = Run(turn_id)
    RUNS[turn_id] = run
    progress = Progress(emit=run.emit, cancelled=lambda: run.cancel)

    def target():
        try:
            state = work(progress)
        except Cancelled:
            state = {"status": "cancelled", "message": "Stopped."}
        except llm.LLMError as e:
            state = {"status": "error", "error": {"code": e.code, "message": e.message, "retryable": True}}
        except SpecError as e:
            state = {"status": "refused", "message": e.message, "code": e.code, "suggestions": e.suggestions}
        except Exception as e:  # never leave a turn spinning
            traceback.print_exc()
            state = {"status": "error", "error": {"code": "INTERNAL", "message": f"Unexpected error: {e}", "retryable": True}}
        _save(turn_id, state)
        run.emit({"step": "result", "status": "done", "result": public_turn(load_turn(turn_id))})
        run.done = True

    threading.Thread(target=target, daemon=True).start()
    return run


def cancel(turn_id: str) -> bool:
    run = RUNS.get(turn_id)
    if run and not run.done:
        run.cancel = True
        return True
    return False


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def load_turn(turn_id: str) -> dict:
    with db.app_conn() as conn:
        row = conn.execute("SELECT * FROM app.turns WHERE id = %s", (turn_id,)).fetchone()
    if row is None:
        raise LookupError("turn not found")
    return row


def _save(turn_id: str, state: dict):
    with db.app_conn() as conn:
        old = conn.execute("SELECT state FROM app.turns WHERE id = %s", (turn_id,)).fetchone()["state"]
        # Keep what earlier runs learned (candidate, answers) unless this run replaced it.
        merged = {k: v for k, v in old.items() if k in ("candidate", "answers", "language", "scope")} | state
        conn.execute("UPDATE app.turns SET state = %s, status = %s, contract_version = %s, updated_at = now() WHERE id = %s",
                     (json.dumps(merged, default=str), merged.get("status", "error"),
                      (merged.get("query_spec") or {}).get("contract_version"), turn_id))
        conn.execute("UPDATE app.conversations SET updated_at = now() WHERE id = (SELECT conversation_id FROM app.turns WHERE id = %s)", (turn_id,))


def _history(conversation_id, before_turn) -> list[dict]:
    with db.app_conn() as conn:
        rows = conn.execute(
            """SELECT id, question, status, state FROM app.turns WHERE conversation_id = %s AND created_at <
                 (SELECT created_at FROM app.turns WHERE id = %s) AND status NOT IN ('running', 'error', 'cancelled')
               ORDER BY created_at DESC LIMIT %s""", (conversation_id, before_turn, HISTORY_TURNS)).fetchall()
    return list(reversed(rows))


def public_turn(row: dict) -> dict:
    st = dict(row["state"])
    st.pop("candidate", None)
    st.pop("model_preview", None)
    with db.app_conn() as conn:
        fb = conn.execute("SELECT rating, comment FROM app.feedback WHERE turn_id = %s", (row["id"],)).fetchone()
    return {"id": str(row["id"]), "conversation_id": str(row["conversation_id"]), "question": row["question"],
            "status": row["status"], "model": row["model"], "created_at": row["created_at"].isoformat(),
            "feedback": fb, **st}


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------
def _lang(candidate: dict | None) -> str:
    forced = (llm.get_connection() or {}).get("answer_language", "auto")
    if forced and forced != "auto":
        return forced
    return ((candidate or {}).get("language") or "en").split("-")[0]


def _answered(question, result, cat, sources, candidate, model, turn_id, progress, variants, notes) -> dict:
    lang = _lang(candidate)
    request = (candidate or {}).get("answer_request") or {"need": "describe", "ask": ""}
    text = insight.write(question, result, cat, sources, lang=lang, answer_request=request, model=model,
                         turn_id=turn_id, step=progress)
    return {
        "status": "answered", "language": lang, "insight": text, "variants": variants, "notes": notes,
        "query_spec": result["query_spec"], "compiled_sql": result["compiled_sql"], "columns": result["columns"],
        "rows": result["rows"][:STORED_ROWS], "row_count": result["row_count"], "partial": result["partial"],
        "facts": result["facts"], "model_preview": result["model_preview"], "warnings": result["warnings"],
        "period": result["period"], "sources": result["sources"], "currency_of": result["currency_of"],
        "unavailable_metrics": result["unavailable_metrics"], "message": None, "form": None, "error": None,
    }


def _continue(turn: dict, candidate: dict, answers: dict, progress: Progress, cat, sources) -> dict:
    lang = _lang(candidate)
    scope = turn["state"].get("scope")
    with progress("check_interpretation") as s:
        out = clarify.advance(candidate, answers, cat, sources, scope=scope, lang=lang)
        s.note(out.kind)
    if out.kind == "clarify":
        return {"status": "needs_clarification", "form": out.form, "candidate": candidate, "answers": answers,
                "language": lang, "notes": out.notes, "variants": out.variants}
    if out.kind == "refuse":
        return {"status": "refused", "message": out.message, "suggestions": out.suggestions, "candidate": candidate,
                "answers": answers, "language": lang}
    result = run_spec(out.spec, cat, sources, progress)
    state = _answered(turn["question"], result, cat, sources, candidate, turn["model"], turn["id"], progress,
                      out.variants, out.notes)
    return state | {"candidate": candidate, "answers": answers}


def ask(question: str, conversation_id: str | None, model: str | None, scope: list[str] | None) -> dict:
    question = question.strip()
    if not question or len(question) > 2000:
        raise SpecError("invalid_question", "Ask a question of at most 2000 characters.")
    with db.app_conn() as conn:
        if conversation_id is None:
            conversation_id = conn.execute("INSERT INTO app.conversations (title) VALUES (%s) RETURNING id",
                                           (question[:80],)).fetchone()["id"]
        elif conn.execute("SELECT 1 FROM app.conversations WHERE id = %s", (conversation_id,)).fetchone() is None:
            raise LookupError("conversation not found")
        turn_id = conn.execute(
            "INSERT INTO app.turns (conversation_id, question, model, state) VALUES (%s,%s,%s,%s) RETURNING id",
            (conversation_id, question, model, json.dumps({"scope": scope or []}))).fetchone()["id"]
    turn_id = str(turn_id)
    _start(turn_id, _question_work(turn_id))
    return {"turn_id": turn_id, "conversation_id": str(conversation_id)}


def _question_work(turn_id: str):
    def work(progress: Progress) -> dict:
        turn = load_turn(turn_id)
        question, conversation_id, model = turn["question"], turn["conversation_id"], turn["model"]
        scope = turn["state"].get("scope")
        with progress("read_conversation") as s:
            previous = _history(conversation_id, turn_id)
            cat = catalog_mod.published()
            sources = catalog_mod.load_sources()
            s.note(f"{len(previous)} earlier turn(s) · catalog v{cat.contract_version}")
        candidate = interpret.interpret(question, previous, cat, sources, model=model, turn_id=turn_id,
                                        scope=scope, step=progress)
        lang = _lang(candidate)
        if candidate["outcome"] == "conversation":
            return {"status": "conversation", "message": candidate["reply"], "suggestions": candidate["suggestions"],
                    "candidate": candidate, "language": lang}
        if candidate["outcome"] == "unsupported":
            return {"status": "refused", "message": candidate["reason"], "suggestions": candidate["suggestions"],
                    "candidate": candidate, "language": lang}
        if candidate["outcome"] == "answer_from_previous":
            prior = next((p for p in reversed(previous) if p["status"] == "answered"), None)
            if prior is None:
                return {"status": "refused", "message": "There is no earlier result in this conversation to discuss yet.",
                        "suggestions": [q.question for q in cat.verified_questions[:3]], "candidate": candidate, "language": lang}
            st = prior["state"]
            result = {k: st.get(k) for k in ("query_spec", "compiled_sql", "columns", "rows", "row_count", "partial", "facts",
                                              "model_preview", "warnings", "period", "sources", "currency_of", "unavailable_metrics")}
            text = insight.write(question, result, cat, sources, lang=lang, answer_request=candidate["answer_request"],
                                 model=model, turn_id=turn_id, step=progress)
            return {"status": "discussed", "insight": text, "based_on": str(prior["id"]), "candidate": candidate,
                    "language": lang, "facts": st.get("facts")}
        return _continue(turn, candidate, {}, progress, cat, sources)
    return work


def answer_clarification(turn_id: str, answers: dict[str, list[str]]) -> None:
    turn = load_turn(turn_id)
    if turn["status"] != "needs_clarification":
        raise SpecError("not_waiting", "This question is not waiting for an answer.")
    form_ids = {f["id"]: f for f in turn["state"]["form"]["fields"]}
    clean = {}
    for fid, values in answers.items():
        f = form_ids.get(fid)
        if f is None or not isinstance(values, list) or not all(isinstance(v, str) and 0 < len(v) <= 200 for v in values):
            raise SpecError("invalid_answer", f"Unexpected answer for {fid!r}.")
        allowed = {c["id"] for c in f["choices"]}
        if not f["allow_other"] and not set(values) <= allowed:
            raise SpecError("invalid_answer", f"Choose one of the offered options for {f['label']}.")
        clean[fid] = values[:20]
    merged = (turn["state"].get("answers") or {}) | clean
    _set_running(turn_id)
    _start(turn_id, lambda p: _continue(load_turn(turn_id), turn["state"]["candidate"], merged, p,
                                        catalog_mod.published(), catalog_mod.load_sources()))


def retry(turn_id: str) -> None:
    """Run the question again from the start (new model reading, no stored answers)."""
    with db.app_conn() as conn:
        conn.execute("UPDATE app.turns SET state = jsonb_build_object('scope', state->'scope'), status = 'running', "
                     "updated_at = now() WHERE id = %s", (turn_id,))
    _start(turn_id, _question_work(turn_id))


def edit(turn_id: str, question: str) -> list[str]:
    """Rewind: replace this turn's question, drop every later turn of the conversation, and run it again.
    Returns the ids of the dropped turns."""
    question = question.strip()
    if not question or len(question) > 2000:
        raise SpecError("invalid_question", "Ask a question of at most 2000 characters.")
    turn = load_turn(turn_id)
    with db.app_conn() as conn:
        later = [str(r["id"]) for r in conn.execute(
            "SELECT id FROM app.turns WHERE conversation_id = %s AND created_at > %s",
            (turn["conversation_id"], turn["created_at"])).fetchall()]
        if any(RUNS.get(t) and not RUNS[t].done for t in [turn_id, *later]):
            raise SpecError("busy", "Stop the running question before editing.")
        conn.execute("DELETE FROM app.turns WHERE id = ANY(%s::uuid[])", (later,))
        conn.execute("UPDATE app.turns SET question = %s, state = jsonb_build_object('scope', state->'scope'), "
                     "status = 'running', updated_at = now() WHERE id = %s", (question, turn_id))
        conn.execute("UPDATE app.conversations SET updated_at = now() WHERE id = %s", (turn["conversation_id"],))
    _start(turn_id, _question_work(turn_id))
    return later


def switch_variant(turn_id: str, metric_id: str) -> None:
    turn = load_turn(turn_id)
    st = turn["state"]
    if metric_id not in {v["id"] for v in st.get("variants") or []}:
        raise SpecError("invalid_variant", "That is not a way of counting this metric.")
    spec = dict(st["query_spec"]) | {"recipe": metric_id, "metrics": []}
    _set_running(turn_id)

    def work(progress):
        cat, sources = catalog_mod.published(), catalog_mod.load_sources()
        result = run_spec(spec, cat, sources, progress)
        return _answered(turn["question"], result, cat, sources, st.get("candidate"), turn["model"], turn_id, progress,
                         st.get("variants") or [], st.get("notes") or [])
    _start(turn_id, work)


def full_result(turn_id: str) -> dict:
    """Re-run the stored spec for all rows (up to the result limit). Never runs automatically."""
    st = load_turn(turn_id)["state"]
    if not st.get("query_spec"):
        raise SpecError("no_result", "This turn has no query to run.")
    result = run_spec(dict(st["query_spec"]) | {"limit": db.RESULT_LIMIT})
    return {"columns": result["columns"], "rows": result["rows"], "row_count": result["row_count"], "partial": result["partial"]}


def _set_running(turn_id: str):
    with db.app_conn() as conn:
        conn.execute("UPDATE app.turns SET status = 'running', updated_at = now() WHERE id = %s", (turn_id,))


def ask_cli(question: str, model: str | None = None, answers: dict | None = None) -> dict:
    """Synchronous helper for the command line and the golden eval."""
    import time

    def wait(turn_id):
        while not RUNS[turn_id].done:
            time.sleep(0.2)
        return public_turn(load_turn(turn_id))

    ids = ask(question, None, model, None)
    out = wait(ids["turn_id"])
    if answers and out["status"] == "needs_clarification":
        answer_clarification(ids["turn_id"], {k: v for k, v in answers.items() if k in {f["id"] for f in out["form"]["fields"]}})
        out = wait(ids["turn_id"])
    return out
