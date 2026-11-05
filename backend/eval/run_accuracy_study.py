"""Provider-free challenge-study planner and guarded diagnostic runner."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

try:
    from .accuracy_study import SUITE_VARIANTS, confirmatory_eligibility, validate_coverage, sql_error_diagnostic
    from .benchmark import execute_readonly, results_equal, score_business_result, score_expected_result, server_metadata
except ImportError:
    from accuracy_study import SUITE_VARIANTS, confirmatory_eligibility, validate_coverage, sql_error_diagnostic
    from benchmark import execute_readonly, results_equal, score_business_result, score_expected_result, server_metadata

SQL_SCHEMA = {"type": "object", "properties": {"sql": {"type": "string"}},
              "required": ["sql"], "additionalProperties": False}
SYSTEM = ("You are a PostgreSQL analyst. Generate one read-only SELECT query. Use only supplied schema and metric definitions. "
          "Return JSON with exactly one key, sql. No markdown, comments, multiple statements, or writes.")


@contextmanager
def _restore_mapping(mapping, prior):
    try:
        yield
    finally:
        for key, value in prior.items():
            if value is None:
                mapping.pop(key, None)
            else:
                mapping[key] = value

ROOT = Path(__file__).resolve().parents[2]
SUITE_FILES = {"single": "cases.yaml", "clarification": "interactions.yaml", "conversation": "dialogues.yaml"}


def load_suite(directory: Path, suite: str, split: str, world: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = yaml.safe_load((directory / "manifest.yaml").read_text(encoding="utf-8"))
    if manifest.get("dataset_type") != "challenge_candidate" or manifest.get("status") != "candidate_agent_reviewed_not_sealed":
        raise ValueError("challenge runner requires the explicitly diagnostic candidate manifest")
    rows = yaml.safe_load((directory / SUITE_FILES[suite]).read_text(encoding="utf-8"))
    selected = [row for row in rows if row.get("split") == split and row.get("fixture_world", "base") == world]
    if not selected:
        raise ValueError(f"no {suite}/{split} scenarios")
    ids = [row.get("id") for row in selected]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scenario IDs")
    return manifest, selected


def world_pools(directory: Path, suite: str, split: str) -> dict[str, list[str]]:
    all_rows = yaml.safe_load((directory / SUITE_FILES[suite]).read_text(encoding="utf-8"))
    pools = {}
    for row in all_rows:
        if row.get("split") == split:
            pools.setdefault(row.get("fixture_world", "base"), []).append(row["id"])
    return {key: sorted(value) for key, value in pools.items()}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _question(item: dict, manifest: dict, public_context: str = "") -> str:
    scope = ("\nExplicit user-selected source scope: " + ", ".join(item["ui_scope"])) if item.get("ui_scope") else ""
    output_columns = item.get("expected_result", {}).get("columns", [])
    contract = item.get("business_contract")
    return ("Schema: analytics.event_activity(event_id, event_date DATE, event_name, user_id, session_id, "
            "item_category, revenue, ep JSONB, source_id).\n"
            "Source roles: cosmetics_shop is product browsing and purchase events; olist_marketplace is marketplace "
            "item-line purchases plus separate payment events.\n"
            "Raw event values: view, cart, remove_from_cart, purchase, order_purchased, order_approved, "
            "order_shipped, order_delivered, order_canceled, payment_made, review_submitted. Purchase rows are "
            "item lines (not orders); payment rows are not purchase revenue.\nSources: " + ", ".join(manifest["sources"]) +
            ".\nMetric definitions: events=count rows; users/sessions=distinct observed IDs; viewers=distinct users "
            "with view events; purchases=count purchase item-line rows; buyers=distinct users with purchase events; "
            "revenue=sum purchase-row revenue (zero for empty aggregate); buyer_conversion_rate=distinct buyers / "
            "distinct observed users, NULL on zero denominator. Group-domain values are eligible observed events; "
            "for conversion ratios retain rows supported by numerator OR denominator.\n" + manifest["metric_policy"] +
            "\nRelative periods are anchored to the selected source's public max_date shown in CATALOG, not the current date. "
            "Return only a read-only PostgreSQL SELECT. Never invent rows or sources." + scope +
            ("\nRequired output column aliases: " + ", ".join(map(str, output_columns)) if output_columns else "") +
            ("\nBusiness output contract: " + json.dumps(contract, ensure_ascii=False, sort_keys=True) if contract else "") +
            "\n\nPUBLIC CATALOG CONTEXT\n" + public_context + "\nQuestion: " + item["question"])


_ACTIONS = {"type": "object", "additionalProperties": False,
            "required": ["action", "sql", "ask_fields", "reason"], "properties": {
                "action": {"type": "string", "enum": ["sql", "clarify", "refuse", "conversation"]},
                "sql": {"type": "string"}, "ask_fields": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"}}}


class RawHistorySession:
    """B1 oracle with text-only history, no Texa answer/query-spec/compiler path."""
    def __init__(self, model: str, dsn: str, *, correction=True, public_context=""):
        from texa import llm
        self.llm, self.model, self.dsn = llm, model, dsn
        self.history: list[dict] = []
        self.calls: list[str] = []
        self.correction = correction
        self.public_context = public_context

    def ask(self, question: str, manifest: dict, *, choices=None, ui_scope=None) -> dict:
        question = _question({"question": question}, manifest, self.public_context)
        if ui_scope:
            question += "\nExplicit user-selected source scope: " + ", ".join(ui_scope)
        if choices:
            question += "\nUser clarification (only selected offered options): " + json.dumps(choices, ensure_ascii=False)
        prompt = "Prior conversation (user questions and actual returned result summaries only):\n" + json.dumps(self.history, ensure_ascii=False) + "\n\nLatest request:\n" + question
        response = self.llm.generate_structured(model=self.model,
            system="You answer analytics questions directly with SQL. Choose sql, clarify, refuse, or conversation. "
                   "For sql, provide one SELECT only. For clarify, list only missing field IDs from "
                   "recipe (metric), context:source, time_range, context:reference, or filter:<dimension>. "
                   "Return a reason string for any action.",
            prompt=prompt, schema=_ACTIONS, name="accuracy_b1", max_output_tokens=1200)
        self.calls.append("accuracy_b1")
        result = {"action": response.get("action"), "sql": response.get("sql", ""),
                  "ask_fields": response.get("ask_fields", []), "reason": response.get("reason", "")}
        if result["action"] == "sql":
            try:
                cols, rows = execute_readonly(self.dsn, result["sql"])
                result.update(columns=list(cols), rows=[list(row) for row in rows], error_class=None)
                self.history.append({"question": question, "result": {"columns": cols, "rows": rows}})
            except Exception as exc:
                result.update(error_class=sql_error_diagnostic(exc), rows=[], columns=[])
                if self.correction:
                    # One correction only; neither gold SQL nor expected values enter this prompt.
                    retry = self.llm.generate_structured(model=self.model,
                        system="Correct the read-only SQL based only on this error category. Return same action schema.",
                        prompt=f"Question: {question}\nPrevious SQL: {result['sql']}\nError category: {result['error_class']}",
                        schema=_ACTIONS, name="accuracy_b1_correction", max_output_tokens=1200)
                    self.calls.append("accuracy_b1_correction")
                    prior_error = result["error_class"]
                    result = {"action": retry.get("action"), "sql": retry.get("sql", ""),
                              "ask_fields": retry.get("ask_fields", []), "reason": retry.get("reason", ""),
                              "error_class": prior_error, "corrected_after_error": True}
                    if result["action"] == "sql":
                        try:
                            cols, rows = execute_readonly(self.dsn, result["sql"])
                            result.update(columns=list(cols), rows=[list(row) for row in rows], error_class=None)
                            self.history.append({"question": question, "result": {"columns": cols, "rows": rows}})
                        except Exception as retry_exc:
                            result.update(error_class=sql_error_diagnostic(retry_exc), columns=[], rows=[])
        else:
            self.history.append({"question": question, "action": result["action"]})
        return result


class IncompleteAccuracyRun(RuntimeError):
    pass


class AccuracyTexaSession:
    """Use only explicit user-visible scope; never infer it from gold source_id."""
    def __init__(self, model: str, scope: list[str] | None, timeout: int):
        from texa import answer
        self.api, self.model, self.timeout = answer, model, timeout
        self.conversation_id = None
        self.turn_ids: set[str] = set()
        self.scope = scope
        self.observed_turns = []

    def _wait(self, turn_id: str) -> dict:
        try:
            from .run_benchmark import _wait_turn
        except ImportError:
            from run_benchmark import _wait_turn
        try:
            raw = _wait_turn(self.api, turn_id, self.timeout)
        except TimeoutError:
            self.api.cancel(turn_id)
            raise IncompleteAccuracyRun("accuracy run incomplete after turn timeout") from None
        current = {**raw, **raw["state"], "id": str(raw["id"])}
        self.observed_turns.append(current)
        return current

    def ask(self, question: str) -> dict:
        ids = self.api.ask(question, self.conversation_id, self.model, self.scope)
        self.conversation_id = ids["conversation_id"]
        self.turn_ids.add(ids["turn_id"])
        return self._wait(ids["turn_id"])

    def resume(self, turn: dict, choices: dict) -> dict:
        self.api.answer_clarification(turn["id"], choices)
        return self._wait(turn["id"])

    def output(self, turn: dict):
        full = self.api.full_result(turn["id"])
        if full.get("partial"):
            raise ValueError("Truncated result cannot be scored")
        columns = [col["name"] for col in turn.get("columns") or [] if not col["name"].startswith("__")]
        return columns, [[row.get(col) for col in columns] for row in full["rows"]]

    def usage(self) -> dict:
        try:
            from .run_benchmark import _turn_usage
        except ImportError:
            from run_benchmark import _turn_usage
        values = [_turn_usage(turn_id) for turn_id in self.turn_ids]
        return {key: sum(value[key] for value in values) for key in ("calls", "input_tokens", "output_tokens", "model_ms")}

    def close(self):
        from texa import db
        if self.conversation_id:
            with db.app_conn() as conn:
                conn.execute("DELETE FROM app.conversations WHERE id=%s", (self.conversation_id,))
        for turn_id in self.turn_ids:
            self.api.RUNS.pop(turn_id, None)


def _score_rows(record: dict, item: dict) -> dict:
    if record.get("action") != "sql" or record.get("error_class"):
        return {"business_result_correct": False, "result_correct": False, "answer_count": 1, "answer_correct": 0}
    try:
        gold = item["expected_result"]
        metrics = score_business_result(record["columns"], record["rows"], gold["columns"], gold["rows"],
                                        ordered=bool(item.get("ordered")), contract=item.get("business_contract"))
        strict = results_equal(record["columns"], record["rows"], gold["columns"], gold["rows"], ordered=bool(item.get("ordered")))
        return {**metrics, "result_correct": strict, "answer_count": 1,
                "answer_correct": int(bool(metrics.get("business_result_correct")))}
    except Exception:
        return {"business_result_correct": False, "result_correct": False, "answer_count": 1, "answer_correct": 0}


def protocol_item(item):
    """Normalize public clarification-field spelling, without adding oracle facts."""
    aliases = {"metric": "recipe", "source": "context:source", "source_id": "context:source"}
    out = dict(item)
    if "ask_fields" in out:
        out["ask_fields"] = [aliases.get(key, key) for key in out["ask_fields"]]
    if "oracle_answers" in out:
        out["oracle_answers"] = {aliases.get(key, key): values for key, values in out["oracle_answers"].items()}
    if "turns" in out:
        out["turns"] = [protocol_item(turn) for turn in out["turns"]]
    return out


def _run_raw_scenario(item: dict, suite: str, manifest: dict, session: RawHistorySession) -> dict:
    targets = item.get("turns", [item])
    out = []
    for target in targets:
        if target.get("action") == "social":
            got = session.ask(target["question"], manifest, ui_scope=item.get("ui_scope"))
            out.append({"expected_action": "conversation", "actual_action": got["action"], "scorable": False,
                        "unsupported_reason": "social_turn_not_sql_scored"})
            continue
        got = session.ask(target["question"], manifest, ui_scope=item.get("ui_scope"))
        rounds = 0
        while got.get("action") == "clarify" and rounds < 2:
            # Form choices are protocol-derived, never copied from gold result data.
            options = {"context:source": manifest["sources"], "recipe": manifest["metrics"],
                       "time_range": ["all", "last_7", "last_30", "custom"]}
            fields = []
            for field_id in got.get("ask_fields", []):
                key = {"source": "context:source", "source_id": "context:source", "metric": "recipe"}.get(field_id, field_id)
                fields.append({"id": field_id, "choices": [{"id": v} for v in options.get(key, [])]})
            try:
                choices = {}
                oracle = target.get("oracle_answers") or {}
                for field in fields:
                    key = {"source_id": "context:source", "source": "context:source", "metric": "recipe"}.get(field["id"], field["id"])
                    values = list(oracle.get(key, []))
                    allowed = {c["id"] for c in field["choices"]}
                    if not values or any(v not in allowed for v in values):
                        raise ValueError("oracle_mismatch")
                    choices[field["id"]] = values
                got = session.ask(target["question"], manifest, choices=choices, ui_scope=item.get("ui_scope"))
                rounds += 1
            except Exception:
                got["error_class"] = "oracle_mismatch"
                break
        scoring = _score_rows(got, target) if "expected_result" in target else {}
        out.append({"expected_action": target.get("action", "sql"), "actual_action": got.get("action"),
                    "refusal_reason": got.get("reason") if got.get("action") == "refuse" else None,
                    "error_class": got.get("error_class"), "scorable": "expected_result" in target,
                    "sql": got.get("sql"), "clarification_rounds": rounds,
                    **scoring})
    scored = [r for r in out if r.get("scorable")]
    return {"turns": out, "answer_count": sum(r.get("answer_count", 0) for r in scored),
            "answer_correct": sum(r.get("answer_correct", 0) for r in scored),
            "unsupported_turn_count": sum(not r.get("scorable") for r in out),
            "success": bool(scored) and all(r.get("business_result_correct") for r in scored)}


def execute(args, directory: Path, manifest: dict, rows: list[dict]) -> int:
    from texa import llm
    try:
        from .run_benchmark import _call_usage
    except ImportError:
        from run_benchmark import _call_usage
    dsn = os.environ.get("TEXA_BENCHMARK_DSN")
    if not dsn:
        raise ValueError("TEXA_BENCHMARK_DSN is required for read-only evaluation")
    for scenario in rows:
        for target in scenario.get("turns", [scenario]):
            if "gold_sql" not in target:
                continue
            gold_check = score_expected_result(dsn, target["gold_sql"], target["expected_result"])
            if not gold_check.get("result_correct"):
                raise ValueError(f"gold validation failed for {scenario['id']}")
    # Keep the challenge's two product sources only; the legacy event_benchmark
    # source is neither part of the authored scope nor a hidden third option.
    os.environ["TEXA_SOURCE_PROFILE"] = "demo"
    from texa import catalog as catalog_mod
    from texa.interpret import render_catalog
    cat = catalog_mod.published()
    source_map = catalog_mod.scoped_sources(cat, catalog_mod.load_sources(max_age=0))
    if set(manifest["sources"]) - set(source_map):
        raise ValueError("public catalog metadata is missing a challenge source")
    # Texa excludes verified Q->A exemplars on B0/B1; keep this common context
    # metadata-only so baseline variants receive no benchmark training examples.
    public_cat = cat.model_copy(update={"verified_questions": []})
    public_context = render_catalog(public_cat, {sid: source_map[sid] for sid in manifest["sources"]})
    public_context_hash = hashlib.sha256(public_context.encode()).hexdigest()
    bank = None
    if args.variant == "B0R":
        from texa import catalog as catalog_mod
        from texa.examples import ExampleBank, load_bank
        loaded = load_bank(catalog_mod.published(), path=ROOT / "catalog/verified_examples.yaml")
        verified = tuple(ex for ex in loaded.examples
                         if ex.get("reference", {}).get("verification_status") == "verified"
                         and ex.get("reference", {}).get("reference_sql"))
        if not verified:
            raise ValueError("B0R unsupported: example bank has no verified reference SQL; no calls made")
        bank = ExampleBank(loaded.version, loaded.catalog_version, loaded.contract_version, verified, loaded.content_hash)
    # Inputs and exact implementation are hashed in every completed run.
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    implementation_paths = [ROOT / p for p in (
        "backend/eval/accuracy_study.py", "backend/eval/run_accuracy_study.py",
        "backend/eval/report_accuracy_study.py", "backend/eval/benchmark.py",
        "backend/texa/interpret.py", "backend/texa/answer.py", "backend/texa/catalog.py",
        "backend/texa/compile.py", "backend/texa/examples.py", "backend/texa/consistency.py",
        "backend/texa/runtime_guard.py", "catalog/product_events.yaml", "catalog/verified_examples.yaml")
        if (ROOT / p).exists()]
    provenance = {"dataset_hashes": {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                  "catalog_hash": hashlib.sha256((ROOT / "catalog/product_events.yaml").read_bytes()).hexdigest(),
                  "bank_hash": hashlib.sha256((ROOT / "catalog/verified_examples.yaml").read_bytes()).hexdigest(),
        "implementation_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in implementation_paths},
                  "public_context_hash": public_context_hash,
                  "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "example_policy": "sql_verified",
                  "model": args.model, "feature_config": {"example_retrieval": args.variant in {"T10", "T11"},
                  "consistency": args.variant in {"T01", "T11"}}}
    output = args.output.resolve(); output.relative_to(ROOT)
    output.parent.mkdir(parents=True, exist_ok=True)
    env_keys = ("TEXA_SOURCE_PROFILE", "TEXA_ABLATION_VARIANT", "TEXA_MEMORY_MODE",
                "TEXA_EXAMPLE_RETRIEVAL", "TEXA_CONSISTENCY", "TEXA_EXAMPLE_POLICY")
    old_env = {key: os.environ.get(key) for key in env_keys}
    calls = 0
    budget_exhausted = False
    call_lock = threading.Lock()
    call_names = []
    original_generate = llm.generate_structured
    def budgeted_generate(**kwargs):
        nonlocal calls, budget_exhausted
        with call_lock:
            if calls >= args.max_model_calls:
                budget_exhausted = True
                raise RuntimeError("accuracy model-call budget exhausted; run left incomplete")
            calls += 1
            kwargs["name"] = f"accuracy_{args.variant.lower()}_{calls}"
            call_names.append(kwargs["name"])
        return original_generate(**kwargs)
    llm.generate_structured = budgeted_generate
    if args.variant in {"T00", "T01", "T10", "T11"}:
        os.environ["TEXA_ABLATION_VARIANT"] = "F"
        os.environ.pop("TEXA_MEMORY_MODE", None)
    with _restore_mapping(os.environ, old_env), _restore_mapping(llm.__dict__, {"generate_structured": original_generate}), output.open("x", encoding="utf-8") as handle:
        def write(obj):
            handle.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n"); handle.flush()
        write({"type": "run_manifest", "variant": args.variant, "suite": args.suite, "split": args.split,
               "repeat": args.repeat, "model": args.model, "provenance": provenance, "expected_ids": [x["id"] for x in rows],
               "dataset": manifest, "status": "diagnostic_candidate", "fixture_world": args.world,
               "confirmatory_requested": args.confirmatory,
               "fixture_hash": provenance["dataset_hashes"].get(f"worlds/{args.world}.sql"),
               "world_pool_ids": world_pools(directory, args.suite, args.split)})
        for original_item in rows:
            item = protocol_item(original_item)
            started = time.monotonic()
            calls_before = calls
            os.environ["TEXA_EXAMPLE_RETRIEVAL"] = "1" if args.variant in {"T10", "T11"} else "0"
            os.environ["TEXA_CONSISTENCY"] = "1" if args.variant in {"T01", "T11"} else "0"
            os.environ["TEXA_EXAMPLE_POLICY"] = "sql_verified"
            session = None
            try:
                raw_sql = None
                selected_examples = []
                if args.variant in {"B0", "B0R"}:
                    prompt = _question(item, manifest, public_context)
                    if args.variant == "B0R":
                        from texa.examples import retrieve_examples
                        found = retrieve_examples(bank, item["question"], confirmed_sources=item.get("ui_scope", []))
                        demos = []
                        for example in found.selected:
                            reference = example.get("reference", {})
                            sql = reference.get("reference_sql") if reference.get("verification_status") == "verified" else None
                            if sql:
                                selected_examples.append(example["id"])
                                demos.append(f"Question: {example['question']}\nSQL: {sql}")
                        if demos:
                            prompt = "Verified reference examples (demonstrations only):\n" + "\n\n".join(demos) + "\n\n" + prompt
                    response = llm.generate_structured(model=args.model, system=SYSTEM, prompt=prompt,
                                                       schema=SQL_SCHEMA, name="accuracy_b0", max_output_tokens=1200)
                    raw_sql = response["sql"]
                    cols, values = execute_readonly(dsn, raw_sql)
                    result = _score_rows({"action": "sql", "columns": cols, "rows": values}, item)
                    row = {**result, "sql": raw_sql, "retrieved_example_ids": selected_examples,
                           "retrieval_activated": bool(selected_examples), "success": bool(result["business_result_correct"])}
                elif args.variant == "B1":
                    row = _run_raw_scenario(item, args.suite, manifest,
                                            RawHistorySession(args.model, dsn, public_context=public_context))
                else:
                    os.environ["TEXA_ABLATION_VARIANT"] = "F"
                    os.environ.pop("TEXA_MEMORY_MODE", None)
                    try:
                        from .run_ablation import TexaSession
                        from .run_ablation import score_answer, trace
                        from .run_ablation import run_interaction, run_memory
                    except ImportError:
                        from run_ablation import TexaSession, score_answer, trace, run_interaction, run_memory
                    session = AccuracyTexaSession(args.model, item.get("ui_scope"), 480)
                    if args.suite == "single":
                        current = session.ask(item["question"])
                        record = {"result_correct": False, "business_result_correct": False}
                        record.update(score_answer(item, current, session))
                        row = {**record, "answer_count": 1,
                               "answer_correct": int(bool(record.get("business_result_correct"))),
                               "success": bool(record.get("business_result_correct")), "turns": [{"trace": trace(current)}],
                               "texa_accuracy_trace": ((current.get("candidate") or
                                                        (current.get("state") or {}).get("candidate") or {}).get("_accuracy") )}
                    elif args.suite == "clarification":
                        row = run_interaction(item, session)
                        row["unsupported_turn_count"] = 0
                    elif args.suite == "conversation":
                        normalized = {**item, "turns": [{**turn, "action": "conversation" if turn.get("action") == "social" else turn.get("action")}
                                                          for turn in item["turns"]]}
                        row = run_memory(normalized, session)
                        row["unsupported_turn_count"] = row.get("unsupported_answer_count", 0)
                    else:
                        raise ValueError("unsupported suite")
                    if args.suite != "single":
                        trace_rows = [turn.get("trace", {}) for turn in row.get("turns", [])]
                        row["texa_accuracy_trace"] = next((t.get("candidate", {}).get("_accuracy")
                            for t in reversed(trace_rows) if isinstance(t.get("candidate"), dict)), None)
                    row["interpretation_traces"] = [{"turn_id": current.get("id"),
                        "status": current.get("status"), "reason_code": current.get("reason_code") or current.get("code"),
                        "error": current.get("error"), "candidate": current.get("candidate"),
                        "message": current.get("message")} for current in session.observed_turns]
                    row["texa_accuracy_traces"] = [current.get("candidate", {}).get("_accuracy")
                        for current in session.observed_turns if current.get("candidate")]
                    row["texa_accuracy_trace"] = next((x for x in reversed(row["texa_accuracy_traces"]) if x), None)
                    if any((current.get("error") or {}).get("code") == "BUDGET_EXHAUSTED"
                           for current in session.observed_turns):
                        raise IncompleteAccuracyRun("Authorized budget exhausted")
            except RuntimeError as exc:
                if "budget exhausted" in str(exc).lower() or isinstance(exc, IncompleteAccuracyRun):
                    raise
                row = {"success": False, "answer_count": int("expected_result" in item), "answer_correct": 0,
                       "error_class": sql_error_diagnostic(exc), "error_type": type(exc).__name__}
            except Exception as exc:
                row = {"success": False, "answer_count": int("expected_result" in item), "answer_correct": 0,
                       "error_class": sql_error_diagnostic(exc), "error_type": type(exc).__name__, "sql": raw_sql,
                       "retrieved_example_ids": selected_examples, "retrieval_activated": bool(selected_examples)}
            finally:
                if session is not None and all(session.api.RUNS.get(t) is None or session.api.RUNS[t].done for t in session.turn_ids):
                    session.close()
            row.update(type="scenario", id=item["id"], cluster_id=item.get("family", item["id"]),
                       group=item.get("stratum", item.get("family", args.suite)), latency_ms=round((time.monotonic()-started)*1000),
                       usage={k: sum(x[k] for x in (_call_usage(name) for name in call_names[calls_before:calls]))
                              for k in ("calls", "input_tokens", "output_tokens", "model_ms")},
                       model_call_attempts=calls-calls_before, usage_complete=True)
            input_price = float(os.environ.get("TEXA_GATEWAY_INPUT_PRICE", "0") or 0)
            output_price = float(os.environ.get("TEXA_GATEWAY_OUTPUT_PRICE", "0") or 0)
            usage = row["usage"]
            row["cost_estimated_usd"] = (usage["input_tokens"] * input_price +
                                          usage["output_tokens"] * output_price)
            write(row)
            if budget_exhausted:
                raise RuntimeError("accuracy model-call budget exhausted; run left incomplete")
        write({"type": "run_complete", "scenarios": len(rows)})
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=ROOT / "data/benchmark/challenge_v1")
    parser.add_argument("--suite", choices=SUITE_FILES, default="single")
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--world", choices=("base", "grain_counterexample", "coverage_edge"), required=True)
    parser.add_argument("--variant", choices=tuple(sorted({v for values in SUITE_VARIANTS.values() for v in values})), default="B0")
    parser.add_argument("--confirmatory", action="store_true", help="refuse unless a genuinely human-reviewed sealed artifact exists")
    parser.add_argument("--execute", action="store_true", help="live diagnostic execution; requires a supported runner backend")
    parser.add_argument("--model")
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--output", type=Path, default=ROOT / "backend/eval/results" / f"accuracy-{uuid.uuid4().hex}.jsonl")
    args = parser.parse_args(argv)
    try:
        manifest, rows = load_suite(args.dataset_dir.resolve(), args.suite, args.split, args.world)
        validate_coverage([{"id": row["id"]} for row in rows], [row["id"] for row in rows],
                          variant=args.variant, suite=args.suite)
        eligible, reason = confirmatory_eligibility(manifest)
        if args.confirmatory and not eligible:
            raise ValueError(f"confirmatory execution refused: {reason}")
        if args.execute:
            if not args.model or not args.max_model_calls or args.max_model_calls < 1:
                raise ValueError("--execute requires --model, positive --max-model-calls, and --output")
            if args.max_model_calls < 1:
                raise ValueError("--max-model-calls must be positive")
            return execute(args, args.dataset_dir.resolve(), manifest, rows)
        print(json.dumps({"mode": "diagnostic_dry_run", "suite": args.suite, "split": args.split,
                          "variant": args.variant, "scenarios": len(rows), "ids": [r["id"] for r in rows],
                          "confirmatory_eligible": eligible, "confirmatory_status": reason,
                          "model_calls": 0}, indent=2))
        return 0
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
