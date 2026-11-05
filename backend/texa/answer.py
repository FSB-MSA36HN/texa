"""One question = one turn. Runs execute in a background thread and publish step events for the SSE stream."""
import json
import hashlib
import os
import threading
import time
import traceback

from . import ablation, catalog as catalog_mod
from . import clarify, db, insight, interpret, llm, memory, suggestions, locale
from .pipeline import run_spec
from .progress import Cancelled, Progress
from .spec import SpecError
from .runtime_guard import BoundedAdmission, AdmissionRejected

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
        self.started_at = time.monotonic()
        self.first_result_ms = None

    def emit(self, event: dict):
        if event.get("step") == "run_query" and event.get("status") == "done" and self.first_result_ms is None:
            self.first_result_ms = int((time.monotonic() - self.started_at) * 1000)
        with self.lock:
            self.events.append(event)
        if event.get("status") in ("done", "failed"):
            with db.app_conn() as conn:
                conn.execute("INSERT INTO app.run_steps (turn_id, step, status, ms, note) VALUES (%s,%s,%s,%s,%s)",
                             (self.turn_id, event["step"], event["status"], event.get("ms"), event.get("note")))


RUNS: dict[str, Run] = {}  # SSE delivery is process-local; durable turn state is reconciled on startup.
RUN_ADMISSION = BoundedAdmission(max_inflight=int(os.getenv("TEXA_RUN_MAX_INFLIGHT", "4")),
                                 max_waiters=int(os.getenv("TEXA_RUN_MAX_WAITERS", "16")),
                                 wait_timeout_s=float(os.getenv("TEXA_RUN_QUEUE_TIMEOUT_S", "30")))


def _start(turn_id: str, work) -> Run:
    old = RUNS.get(turn_id)
    if old and not old.done:
        raise SpecError("busy", "This question is still running.")
    run = Run(turn_id)
    RUNS[turn_id] = run
    progress = Progress(emit=run.emit, cancelled=lambda: run.cancel)

    def target():
        try:
            with RUN_ADMISSION.acquire() as queue_ms:
                run.emit({"step": "run_queue", "status": "done", "ms": int(queue_ms)})
                with llm.runtime_observer_scope(lambda event: run.emit({"step": event["event"], "status": "done",
                                                               "ms": int(event["duration_ms"]),
                                                               "note": ":".join(str(v) for v in (event.get("call_name"), event.get("outcome")) if v)})):
                    state = work(progress)
        except AdmissionRejected:
            state = {"status": "error", "error": {"code": "QUEUE_FULL", "message": "Request queue is full. Please retry later.", "retryable": True}}
        except Cancelled:
            state = {"status": "cancelled", "message": "Stopped."}
        except llm.LLMError as e:
            state = {"status": "error", "error": {"code": e.code, "message": e.message, "retryable": e.code not in {"BUDGET_EXHAUSTED", "AUTH", "NO_KEY", "BAD_MODEL"}}}
        except SpecError as e:
            state = {"status": "refused", "message": e.message, "code": e.code, "reason_params": getattr(e, "params", {}), "suggestions": []}
        except Exception as e:  # never leave a turn spinning
            traceback.print_exc()
            state = {"status": "error", "error": {"code": "INTERNAL", "message": "Unexpected internal error. Please retry.", "retryable": True}}
        language = state.get("language") or load_turn(turn_id)["state"].get("language", "vi")
        state["language"] = language
        if state.get("error"):
            error = state["error"]
            error["message"] = locale.render(error["code"], error["message"], language)
        if state.get("code") and state.get("message"):
            state["message"] = locale.render(state["code"], state["message"], language, state.pop("reason_params", {}))
        state["timing"] = {"end_to_end_ms": int((time.monotonic() - run.started_at) * 1000),
                           "first_result_ms": run.first_result_ms}
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
        row = conn.execute("SELECT * FROM app.turns WHERE id = %s", (turn_id,)).fetchone()
        old = row["state"]
        conn.execute("SELECT id FROM app.conversations WHERE id = %s FOR UPDATE", (row["conversation_id"],))
        # Keep what earlier runs learned (candidate, answers) unless this run replaced it.
        merged = {k: v for k, v in old.items() if k in ("candidate", "answers", "language", "scope", "context", "dataset_version", "ablation")} | state
        conn.execute("UPDATE app.turns SET state = %s, status = %s, contract_version = %s, updated_at = now() WHERE id = %s",
                     (json.dumps(merged, default=str), merged.get("status", "error"),
                      (merged.get("query_spec") or {}).get("contract_version"), turn_id))
        # Replay makes retries, edits and variant switches idempotent: no duplicate
        # topics and no orphan references to turns removed by a rewind.
        turns = conn.execute("SELECT id, question, status, state, created_at FROM app.turns WHERE conversation_id = %s ORDER BY created_at, id",
                             (row["conversation_id"],)).fetchall()
        committed = {}
        for prior in turns:
            prior_state = prior["state"]
            committed = memory.apply_turn(committed, prior, context=prior_state.get("context"),
                                          dataset_version=prior_state.get("dataset_version"))
        conn.execute("UPDATE app.conversations SET memory = %s, updated_at = now() WHERE id = %s",
                     (json.dumps(committed, default=str), row["conversation_id"]))


def _history(conversation_id, before_turn) -> list[dict]:
    with db.app_conn() as conn:
        rows = conn.execute(
            """SELECT id, question, status, state, created_at FROM app.turns WHERE conversation_id = %s AND created_at <
                 (SELECT created_at FROM app.turns WHERE id = %s)
               ORDER BY created_at, id""", (conversation_id, before_turn)).fetchall()
    return rows


def _earlier_questions(turn_id) -> list[str]:
    """What the user typed earlier in the conversation: numbers they stated there (a rate) may be reused."""
    if turn_id is None:
        return []
    if ablation.memory_disabled():
        return []
    with db.app_conn() as conn:
        row = conn.execute("SELECT conversation_id FROM app.turns WHERE id = %s", (turn_id,)).fetchone()
    return [p["question"] for p in _history(row["conversation_id"], turn_id)] if row else []


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
def _persist_language(turn_id, lang):
    with db.app_conn() as conn:
        conn.execute("UPDATE app.turns SET state = state || %s::jsonb WHERE id = %s",
                     (json.dumps({"language": lang}), turn_id))
        conn.execute("UPDATE app.conversations SET locale=%s WHERE id=(SELECT conversation_id FROM app.turns WHERE id=%s)",
                     (lang, turn_id))


def _lang(candidate: dict | None) -> str:
    forced = (llm.get_connection() or {}).get("answer_language", "auto")
    if forced and forced != "auto":
        return forced
    return ((candidate or {}).get("language") or "en").split("-")[0]


def _answered(question, result, cat, sources, candidate, model, turn_id, progress, variants, notes, earlier_questions=None) -> dict:
    lang = _lang(candidate)
    result["warnings"] = [locale.render(w.get("code"), w.get("message", ""), lang, w.get("params"))
                          for w in result.get("warning_details", [])] or result["warnings"]
    for column in result.get("columns", []):
        entry = cat.mets.get(column["name"]) or cat.dims.get(column["name"])
        if entry:
            column["label"] = catalog_mod.display_label(entry, lang)
    request = (candidate or {}).get("answer_request") or {"need": "describe", "ask": ""}
    text = insight.write(question, result, cat, sources, lang=lang, answer_request=request, model=model,
                         turn_id=turn_id, step=progress, earlier_questions=earlier_questions or [])
    text["follow_ups"] = suggestions.questions(cat, sources, result["sources"], lang)
    return {
        "status": "answered", "language": lang, "insight": text, "variants": variants, "notes": notes,
        "query_spec": result["query_spec"], "compiled_sql": result["compiled_sql"], "columns": result["columns"],
        "rows": result["rows"][:STORED_ROWS], "row_count": result["row_count"], "partial": result["partial"],
        "facts": result["facts"], "model_preview": result["model_preview"], "warnings": result["warnings"],
        "period": result["period"], "sources": result["sources"], "currency_of": result["currency_of"],
        "unavailable_metrics": result["unavailable_metrics"], "message": None, "form": None, "error": None,
        "metric_definitions": [{"id": mid, "label": catalog_mod.display_label(cat.mets[mid], lang), "description": catalog_mod.display_description(cat.mets[mid], lang)}
                               for mid in ([result["query_spec"].get("recipe")] if result["query_spec"].get("recipe") else result["query_spec"].get("metrics", []))],
    }


def _continue(turn: dict, candidate: dict, answers: dict, progress: Progress, cat, sources) -> dict:
    sources = catalog_mod.scoped_sources(cat, sources)
    if turn["state"].get("context", {}).get("catalog_version") not in (None, cat.contract_version):
        raise SpecError("stale_catalog", "The metric definitions changed while waiting for clarification. Ask again.")
    if turn["state"].get("dataset_version") not in (None, _snapshot(sources)):
        raise SpecError("stale_data", "The dataset changed while waiting for clarification. Ask again.")
    lang = _lang(candidate)
    scope = turn["state"].get("scope")
    selected = turn["state"].get("ablation", {}).get("variant") or ablation.variant()
    trace = turn["state"].get("ablation") or ablation.initial_trace(selected)
    named = candidate.get("source_ids") or []
    if any(sid not in sources for sid in named):
        raise llm.LLMError("MODEL_OUTPUT_INVALID", "The interpretation referenced an unavailable source.")
    inherited_source = (candidate.get("dialogue", {}).get("slots", {}).get("source_ids") == "keep")
    model_sources = list(named)
    memory_sources = list(named) if inherited_source else []
    literal_mentions = catalog_mod.mentioned_sources(cat, sources, turn["question"])
    text_sources = literal_mentions or ([] if inherited_source else list(named))
    # A name occurrence is evidence, not an instruction: it may be negated.
    # Never overwrite semantic interpretation with a lexical positive choice.
    mention_uncertain = bool(literal_mentions and set(literal_mentions) != set(named))
    resolved_source = answers.get("context:source")
    if (mention_uncertain or (scope and named and set(named) != set(scope))
            or len(named) > cat.policy.max_sources or len(literal_mentions) > cat.policy.max_sources) and not resolved_source:
        choices = [{"id": sid, "label": sources[sid].label, "description": ""}
                   for sid in dict.fromkeys([*(scope or []), *named, *literal_mentions,
                                            *(sources if mention_uncertain else [])]) if sid in sources]
        return {"status": "needs_clarification", "candidate": candidate, "answers": answers, "language": lang,
                "source_resolution": {"ui": scope or [], "text": text_sources, "memory": memory_sources, "effective": None},
                "form": {"message": ("Chưa xác định chắc nguồn bạn muốn dùng. Chọn nguồn để tiếp tục." if mention_uncertain else
                          "Nguồn đã chọn khác nguồn của kết quả trước. Chọn nguồn để tiếp tục." if inherited_source else
                          "Nguồn đã chọn khác nguồn trong câu hỏi. Chọn nguồn để tiếp tục." if scope else
                          "Mỗi câu hỏi chỉ dùng một nguồn. Chọn nguồn để tiếp tục.") if lang == "vi" else
                         "The chosen source conflicts with the request or referenced result. Choose one to continue.",
                         "fields": [{"id": "context:source", "label": "Nguồn" if lang == "vi" else "Source", "kind": "single_choice",
                                     "required": True, "allow_other": False, "default": [], "choices": choices}]}}
    if resolved_source:
        candidate = candidate | {"source_ids": resolved_source}
        scope = resolved_source
    source_resolution = {"ui": turn["state"].get("scope") or [], "text": text_sources, "memory": memory_sources, "model": model_sources,
                         "resolved_by_user": bool(resolved_source), "effective": resolved_source or named or scope or []}
    with progress("check_interpretation") as s:
        out = clarify.advance(candidate, answers, cat, sources, scope=scope, lang=lang, question=turn["question"])
        if out.kind == "clarify":
            targets = [field for field in (out.form or {}).get("fields", [])
                       if field.get("id") in {"time_range", "recipe"}]
            trace = trace | {"clarification_requested": True, "clarification_eligible": bool(targets)}
        if out.kind == "clarify" and selected == "C0":
            if targets and not trace.get("clarification_invoked"):
                guessed, guess_trace = ablation.resolve_clarification(
                    candidate, out.form, turn["question"], model=turn["model"], turn_id=turn["id"])
                trace = trace | {"clarification_invoked": bool(guess_trace["activated"]),
                                 "clarification_field": guess_trace.get("field"),
                                 "clarification_choice_id": guess_trace.get("choice_id"),
                                 "clarification_choices": guess_trace.get("choices", []),
                                 "clarification_choice_count": guess_trace.get("choice_count", 0),
                                 "clarification_reason": guess_trace["reason"]}
                if guess_trace["reason"] == "selected":
                    # The guess only chooses an offered ID. The normal resolver,
                    # value checks, QuerySpec validation, and compiler still run.
                    answers = answers | guessed
                    out = clarify.advance(candidate, answers, cat, sources, scope=scope, lang=lang, question=turn["question"])
                elif guess_trace["activated"]:
                    s.note("C0 could not safely choose an offered value")
                    return {"status": "refused", "message": "I could not infer a valid option from the question. Please ask again with the missing detail.",
                            "candidate": candidate, "answers": answers, "language": lang,
                            "ablation": trace}
        s.note(out.kind)
    if out.kind == "clarify":
        return {"status": "needs_clarification", "form": out.form, "candidate": candidate, "answers": answers,
                "language": lang, "notes": out.notes, "variants": out.variants, "ablation": trace}
    if out.kind == "refuse":
        return {"status": "refused", "message": out.message, "suggestions": suggestions.questions(cat, sources, scope, lang), "candidate": candidate,
                "answers": answers, "language": lang, "ablation": trace}
    result = run_spec(out.spec, cat, sources, progress)
    state = _answered(turn["question"], result, cat, sources, candidate, turn["model"], turn["id"], progress,
                      out.variants, out.notes, earlier_questions=turn["state"].get("context", {}).get("questions", []))
    return state | {"candidate": candidate, "answers": answers, "ablation": trace, "source_resolution": source_resolution,
                    "filter_binding_trace": _filter_binding_trace(result["query_spec"], candidate, answers, cat, sources)}


def _filter_binding_trace(spec, candidate: dict, answers: dict, cat, sources) -> list[dict]:
    """Record the actual binder boundary, without claiming model intent is certain."""
    inherited = candidate.get("dialogue", {}).get("slots", {}).get("filters") == "keep"
    trace = []
    for f in spec["filters"]:
        field = f["field"]
        inputs = [v for item in candidate.get("filters", []) if item["field"] == field
                  for v in item.get("values_mentioned", [])]
        selected = answers.get(f"filter:{field}")
        trace.append({"field_id": field, "source_ids": spec["source_ids"],
                      "catalog_version": cat.contract_version,
                      "origin": "clarification" if selected else "memory" if inherited else "question_interpretation",
                      "input_values": list(selected or inputs), "bound_values": list(f["values"]),
                      "operator": f["operator"],
                      "vocabulary_status": {sid: sources[sid].value_vocabulary_status(
                          cat.mapped_field(cat.dims[field].field, sid)) for sid in spec["source_ids"]}})
    return trace


def ask(question: str, conversation_id: str | None, model: str | None, scope: list[str] | None,
        owner_hash: str | None = None, language: str | None = None) -> dict:
    question = question.strip()
    if not question or len(question) > 2000:
        raise SpecError("invalid_question", "Ask a question of at most 2000 characters.")
    configured_variant = ablation.variant()
    with db.app_conn() as conn:
        if conversation_id is None:
            language = language or "vi"
            conversation_id = conn.execute("INSERT INTO app.conversations (title, browser_session_hash, locale) VALUES (%s,%s,%s) RETURNING id",
                                           (question[:80], owner_hash, language)).fetchone()["id"]
        elif conn.execute("SELECT 1 FROM app.conversations WHERE id = %s FOR UPDATE", (conversation_id,)).fetchone() is None:
            raise LookupError("conversation not found")
        if not language:
            language = conn.execute("SELECT locale FROM app.conversations WHERE id=%s", (conversation_id,)).fetchone()["locale"]
        if conn.execute("SELECT 1 FROM app.turns WHERE conversation_id = %s AND status = 'running' LIMIT 1",
                        (conversation_id,)).fetchone():
            raise SpecError("busy", "Wait for the current question before asking in this conversation.")
        turn_id = conn.execute(
            "INSERT INTO app.turns (conversation_id, question, model, state) VALUES (%s,%s,%s,%s) RETURNING id",
            (conversation_id, question, model,
             json.dumps({"scope": scope or [], "language": language, "ablation": ablation.initial_trace(configured_variant)}))).fetchone()["id"]
    turn_id = str(turn_id)
    _start(turn_id, _question_work(turn_id))
    return {"turn_id": turn_id, "conversation_id": str(conversation_id)}


def _snapshot(sources: dict) -> str:
    payload = {sid: (src.snapshot_version or f"{src.min_date}:{src.max_date}:{src.row_count}")
               for sid, src in sources.items()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:20]


def _reference_form(previous: list[dict], context: dict, cat=None, sources=None) -> dict:
    lang = context.get("language", "vi")
    choices = []
    for i, prior in enumerate(previous):
        if prior["status"] != "answered":
            continue
        spec = prior["state"].get("query_spec", {})
        metrics = [spec["recipe"]] if spec.get("recipe") else spec.get("metrics", [])
        labels = [catalog_mod.display_label(cat.mets[mid], lang) if cat and mid in cat.mets else mid for mid in metrics]
        stores = [sources[sid].label if sources and sid in sources else sid for sid in spec.get("source_ids", [])]
        period = spec.get("time_range", {})
        dates = (f"{period.get('start')} → {period.get('end')}" if period.get("kind") == "between" else
                 f"{period.get('days')} ngày / days" if period.get("kind") == "last_n_days" else "Toàn bộ / All data")
        filters = [f"{catalog_mod.display_label(cat.dims[f['field']], lang) if cat and f['field'] in cat.dims else f['field']} "
                   f"{f['operator']} {', '.join(f.get('values', []))}" for f in spec.get("filters", [])]
        ordinal = context.get("result_ordinals", {}).get(str(prior["id"]), i + 1)
        choices.append({"id": str(prior["id"]), "label": f"{ordinal}. {prior['question'][:150]}",
                        "description": " · ".join([*stores, *labels, dates, *filters])})
    if not choices:
        raise SpecError("no_result", "There is no compatible earlier result to reference. Ask a complete question.")
    message = "Bạn đang nhắc đến kết quả nào?" if lang == "vi" else "Which earlier result do you mean?"
    unavailable = context.get("unavailable_result_numbers", [])
    if unavailable:
        message += (" Một số kết quả cũ không còn tương thích; danh sách giữ nguyên số thứ tự ban đầu." if lang == "vi" else
                    " Some older results are incompatible; original result numbers are retained.")
    return {"status": "needs_clarification", "context": context, "form": {
        "message": message,
        "fields": [{"id": "context:reference", "label": "Kết quả trước" if lang == "vi" else "Earlier result", "kind": "single_choice",
                    "required": True, "allow_other": False, "default": [], "choices": choices}]}}


def _question_work(turn_id: str, reference_id: str | None = None):
    def work(progress: Progress) -> dict:
        turn = load_turn(turn_id)
        question, conversation_id, model = turn["question"], turn["conversation_id"], turn["model"]
        selected_variant = turn["state"].get("ablation", {}).get("variant") or ablation.variant()
        if selected_variant != ablation.variant():
            raise SpecError("ablation_variant_changed", "The ablation variant changed before this scenario started.")
        variant_trace = turn["state"].get("ablation") or ablation.initial_trace(selected_variant)
        scope = turn["state"].get("scope")
        with progress("read_conversation") as s:
            cat = catalog_mod.published()
            sources = catalog_mod.scoped_sources(cat, catalog_mod.load_sources(max_age=0))
            if scope and (len(scope) > cat.policy.max_sources or any(sid not in sources for sid in scope)):
                raise SpecError("source_scope", "Choose one available source within the product scope.")
            dataset_version = _snapshot(sources)
            if ablation.memory_disabled(selected_variant):
                previous = []
                context = {"turns": [], "relation": "disabled", "references": [],
                           "inherited_slots": {}, "clarification_needed": False}
            else:
                raw_history = _history(conversation_id, turn_id)
                all_previous = [p for p in raw_history
                                if p["state"].get("dataset_version") == dataset_version]
                if ablation.memory_mode(selected_variant) == "window6":
                    # M6 is exactly a six-turn context window, including what
                    # can be explicitly selected in a reference form.
                    previous = all_previous[-6:]
                    context = {"turns": previous, "relation": "window6", "references": [],
                               "inherited_slots": {}, "clarification_needed": False}
                else:
                    previous = all_previous
                    previous = memory.compatible_results(all_previous, cat.contract_version)
                    context = {"turns": [], "relation": "unresolved", "references": [],
                               "inherited_slots": {}, "clarification_needed": False, "structured_memory": True,
                               "registry": memory.result_registry(previous, cat.contract_version, ordinal_history=raw_history)}
            if reference_id:
                if ablation.memory_disabled(selected_variant):
                    raise SpecError("memory_disabled", "Earlier results are unavailable in this ablation run. Ask a complete question.")
                ref = next((p for p in previous if str(p["id"]) == reference_id and p["status"] == "answered"
                            and p["state"].get("query_spec", {}).get("contract_version") == cat.contract_version), None)
                if ref is None:
                    raise SpecError("stale_reference", "The selected result is no longer compatible. Ask again.")
                context.update(turns=[ref], relation="followup", references=[reference_id],
                               inherited_slots=ref["state"]["query_spec"], clarification_needed=False,
                               forced_reference=reference_id)
            context["language"] = turn["state"].get("language", "vi")
            if context.get("registry"):
                context["result_ordinals"] = {r["id"]: r["result_number"] for r in context["registry"]}
                count = sum(p["status"] == "answered" and bool(p["state"].get("query_spec")) for p in raw_history)
                context["unavailable_result_numbers"] = sorted(set(range(1, count + 1)) - set(context["result_ordinals"].values()))
            selected = context.pop("turns")
            context.update(catalog_version=cat.contract_version, questions=[p["question"] for p in selected])
            metadata = {"context": context, "dataset_version": dataset_version, "ablation": variant_trace}
            turn["state"].update(metadata)
            s.note(f"{len(selected)} relevant turns · {context['relation']} · catalog v{cat.contract_version}")
        if context.get("clarification_needed"):
            return _reference_form(previous, context, cat, sources) | metadata
        candidate = interpret.interpret(question, selected, cat, sources, model=model, turn_id=turn_id,
                                        scope=scope, step=progress, context=context)
        if context.get("structured_memory"):
            candidate, resolved = memory.reduce_candidate(candidate, previous, cat.contract_version, reference_id)
            context.update(resolved)
            context["language"] = _lang(candidate)
            context.pop("registry", None)  # durable context stores pointers and provenance, not another history copy
            context["questions"] = [p["question"] for p in previous if str(p["id"]) in context["references"]]
            if context.get("clarification_needed"):
                return _reference_form(previous, context, cat, sources) | metadata | {"candidate": candidate}
        lang = _lang(candidate)
        _persist_language(turn_id, lang)
        if candidate["outcome"] == "conversation":
            return {"status": "conversation", "message": candidate["reply"], "suggestions": suggestions.questions(cat, sources, scope, lang),
                    "candidate": candidate, "language": lang} | metadata
        if candidate["outcome"] == "unsupported":
            return {"status": "refused", "message": candidate["reason"], "suggestions": suggestions.questions(cat, sources, scope, lang),
                    "candidate": candidate, "language": lang} | metadata
        if candidate["outcome"] == "answer_from_previous":
            refs = set(context.get("references", []))
            choices = [p for p in previous if p["status"] == "answered" and str(p["id"]) in refs]
            if ablation.memory_disabled(selected_variant):
                raise SpecError("memory_disabled", "Earlier results are unavailable in this ablation run. Ask a complete question.")
            if ablation.memory_mode(selected_variant) == "window6":
                choices = [p for p in selected if p["status"] == "answered"][-1:]
            if len(choices) != 1:
                return _reference_form(previous, context, cat, sources) | metadata
            prior = choices[0]
            st = prior["state"]
            result = {k: st.get(k) for k in ("query_spec", "compiled_sql", "columns", "rows", "row_count", "partial", "facts",
                                              "model_preview", "warnings", "period", "sources", "currency_of", "unavailable_metrics")}
            text = insight.write(question, result, cat, sources, lang=lang, answer_request=candidate["answer_request"],
                                 model=model, turn_id=turn_id, step=progress, earlier_questions=context["questions"])
            return {"status": "discussed", "insight": text, "based_on": str(prior["id"]), "candidate": candidate,
                    "language": lang, "facts": st.get("facts")} | metadata
        return metadata | _continue(turn, candidate, {}, progress, cat, sources)
    return work


def answer_clarification(turn_id: str, answers: dict[str, list[str]]) -> None:
    turn = load_turn(turn_id)
    if turn["status"] != "needs_clarification":
        raise SpecError("not_waiting", "This question is not waiting for an answer.")
    form_ids = {f["id"]: f for f in turn["state"]["form"]["fields"]}
    selected_variant = turn["state"].get("ablation", {}).get("variant") or ablation.variant()
    if selected_variant != ablation.variant():
        raise SpecError("ablation_variant_changed", "The ablation variant changed while this clarification was pending. Restart the scenario.")
    clean = {}
    for fid, values in answers.items():
        f = form_ids.get(fid)
        if f is None or not isinstance(values, list) or not all(isinstance(v, str) and 0 < len(v) <= 200 for v in values):
            raise SpecError("invalid_answer", f"Unexpected answer for {fid!r}.")
        allowed = {c["id"] for c in f["choices"]}
        if not f["allow_other"] and not set(values) <= allowed:
            raise SpecError("invalid_answer", f"Choose one of the offered options for {f['label']}.")
        if f["kind"] == "single_choice" and len(values) != 1:
            raise SpecError("invalid_answer", f"Choose exactly one value for {f['label']}.")
        clean[fid] = values[:20]
    if "context:reference" in form_ids:
        if ablation.memory_disabled(selected_variant):
            raise SpecError("memory_disabled", "Earlier results are unavailable in this ablation run. Ask a complete question.")
        values = clean.get("context:reference", [])
        if len(values) != 1:
            raise SpecError("invalid_answer", "Choose exactly one earlier result.")
        _set_running(turn_id)
        _start(turn_id, _question_work(turn_id, reference_id=values[0]))
        return
    merged = (turn["state"].get("answers") or {}) | clean
    _set_running(turn_id)
    _start(turn_id, lambda p: _continue(load_turn(turn_id), turn["state"]["candidate"], merged, p,
                                        catalog_mod.published(), catalog_mod.load_sources(max_age=0)))


def retry(turn_id: str) -> None:
    """Run the question again from the start (new model reading, no stored answers)."""
    old_state = load_turn(turn_id)["state"]
    selected_variant = old_state.get("ablation", {}).get("variant") or ablation.variant()
    if selected_variant != ablation.variant():
        raise SpecError("ablation_variant_changed", "The ablation variant changed. Restart the scenario.")
    with db.app_conn() as conn:
        conn.execute("UPDATE app.turns SET state = jsonb_build_object('scope', state->'scope') || %s::jsonb, status = 'running', "
                     "updated_at = now() WHERE id = %s",
                     (json.dumps({"ablation": ablation.initial_trace(selected_variant)}), turn_id))
    _start(turn_id, _question_work(turn_id))


def edit(turn_id: str, question: str) -> list[str]:
    """Rewind: replace this turn's question, drop every later turn of the conversation, and run it again.
    Returns the ids of the dropped turns."""
    question = question.strip()
    if not question or len(question) > 2000:
        raise SpecError("invalid_question", "Ask a question of at most 2000 characters.")
    turn = load_turn(turn_id)
    selected_variant = turn["state"].get("ablation", {}).get("variant") or ablation.variant()
    if selected_variant != ablation.variant():
        raise SpecError("ablation_variant_changed", "The ablation variant changed. Restart the scenario.")
    with db.app_conn() as conn:
        later = [str(r["id"]) for r in conn.execute(
            "SELECT id FROM app.turns WHERE conversation_id = %s AND created_at > %s",
            (turn["conversation_id"], turn["created_at"])).fetchall()]
        if any(RUNS.get(t) and not RUNS[t].done for t in [turn_id, *later]):
            raise SpecError("busy", "Stop the running question before editing.")
        conn.execute("DELETE FROM app.turns WHERE id = ANY(%s::uuid[])", (later,))
        conn.execute("UPDATE app.turns SET question = %s, state = jsonb_build_object('scope', state->'scope') || %s::jsonb, "
                     "status = 'running', updated_at = now() WHERE id = %s",
                     (question, json.dumps({"ablation": ablation.initial_trace(selected_variant)}), turn_id))
        conn.execute("""UPDATE app.conversations SET updated_at = now(),
                        title = CASE WHEN title_manual THEN title ELSE
                        (SELECT left(question,80) FROM app.turns WHERE conversation_id = %s
                         ORDER BY created_at,id LIMIT 1) END WHERE id = %s""",
                     (turn["conversation_id"], turn["conversation_id"]))
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
        cat = catalog_mod.published()
        sources = catalog_mod.scoped_sources(cat, catalog_mod.load_sources(max_age=0))
        if st.get("dataset_version") not in (None, _snapshot(sources)):
            raise SpecError("stale_data", "The dataset changed since this result. Ask the question again.")
        result = run_spec(spec, cat, sources, progress)
        return _answered(turn["question"], result, cat, sources, st.get("candidate"), turn["model"], turn_id, progress,
                         st.get("variants") or [], st.get("notes") or [])
    _start(turn_id, work)


def full_result(turn_id: str) -> dict:
    """Re-run the stored spec for all rows (up to the result limit). Never runs automatically."""
    st = load_turn(turn_id)["state"]
    if not st.get("query_spec"):
        raise SpecError("no_result", "This turn has no query to run.")
    cat = catalog_mod.published()
    sources = catalog_mod.scoped_sources(cat, catalog_mod.load_sources(max_age=0))
    if st.get("dataset_version") not in (None, _snapshot(sources)):
        raise SpecError("stale_data", "The dataset changed since this result. Ask the question again.")
    result = run_spec(dict(st["query_spec"]) | {"limit": db.RESULT_LIMIT}, cat, sources)
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
