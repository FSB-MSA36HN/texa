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
    from .accuracy_study import SUITE_VARIANTS, confirmatory_eligibility, validate_coverage, sql_error_diagnostic, expected_answer_count, gold_targets, clarification_policy_score, clarification_policy_from_counts
    from .benchmark import execute_readonly, results_equal, score_business_result, score_expected_result, server_metadata, validate_business_contract
except ImportError:
    from accuracy_study import SUITE_VARIANTS, confirmatory_eligibility, validate_coverage, sql_error_diagnostic, expected_answer_count, gold_targets, clarification_policy_score, clarification_policy_from_counts
    from benchmark import execute_readonly, results_equal, score_business_result, score_expected_result, server_metadata, validate_business_contract

SQL_SCHEMA = {"type": "object", "properties": {"sql": {"type": "string"}},
              "required": ["sql"], "additionalProperties": False}
SCHEMA_ONLY_SYSTEM = ("You are a PostgreSQL analyst. Generate one read-only SELECT query from the user's request and the supplied database schema. "
                      "Do not assume undocumented business meanings. If the request cannot be determined from the schema and question, make the best direct SQL interpretation. "
                      "Return JSON with exactly one key, sql. No markdown, comments, multiple statements, or writes.")
CHALLENGE_SCHEMA = """CREATE TABLE analytics.event_activity (
    event_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    event_ts TIMESTAMPTZ NOT NULL,
    event_date DATE NOT NULL,
    event_name TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT,
    first_seen_date DATE NOT NULL,
    platform TEXT,
    country TEXT,
    region TEXT,
    city TEXT,
    item_id TEXT,
    item_category TEXT,
    item_brand TEXT,
    item_price NUMERIC(14,2),
    quantity INTEGER,
    revenue NUMERIC(14,2),
    revenue_usd NUMERIC(14,2),
    currency TEXT,
    ep JSONB NOT NULL,
    up JSONB NOT NULL,
    src_table TEXT,
    ingested_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source_id, event_id)
);

CREATE TABLE analytics.source_registry (
    source_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    currency TEXT,
    min_date DATE,
    max_date DATE,
    row_count BIGINT,
    user_count BIGINT,
    last_loaded_at TIMESTAMPTZ
);"""


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
SUITE_FILES = {"single": "cases.yaml", "clarification": "interactions.yaml", "conversation": "dialogues.yaml", "diagnostic": "cases.yaml"}


def load_suite(directory: Path, suite: str, split: str, world: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = yaml.safe_load((directory / "manifest.yaml").read_text(encoding="utf-8"))
    candidate_states = {("challenge_candidate", "candidate_agent_reviewed_not_sealed"),
                        ("research_candidate", "agent_authored_unsealed_pending_human_review")}
    if (manifest.get("dataset_type"), manifest.get("status")) not in candidate_states:
        raise ValueError("runner requires an explicitly unsealed challenge/research candidate manifest")
    suite_file = "unsupported.yaml" if suite == "diagnostic" and (directory / "unsupported.yaml").is_file() else SUITE_FILES[suite]
    rows = yaml.safe_load((directory / suite_file).read_text(encoding="utf-8"))
    selected = [row for row in rows if row.get("split") == split and row.get("fixture_world", "base") == world]
    if not selected:
        raise ValueError(f"no {suite}/{split} scenarios")
    ids = [row.get("id") for row in selected]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate scenario IDs")
    for row in selected:
        for target in row.get("turns", [row]):
            if "expected_result" in target:
                validate_business_contract(
                    target.get("business_contract"),
                    (target.get("expected_result") or {}).get("columns", []),
                    context=f"{row.get('id')}:{target.get('id', 'turn')}",
                )
    return manifest, selected


def world_pools(directory: Path, suite: str, split: str) -> dict[str, list[str]]:
    suite_file = "unsupported.yaml" if suite == "diagnostic" and (directory / "unsupported.yaml").is_file() else SUITE_FILES[suite]
    all_rows = yaml.safe_load((directory / suite_file).read_text(encoding="utf-8"))
    pools = {}
    for row in all_rows:
        if row.get("split") == split:
            pools.setdefault(row.get("fixture_world", "base"), []).append(row["id"])
    return {key: sorted(value) for key, value in pools.items()}


def select_shard(rows: list[dict[str, Any]], shard_index: int = 0, shard_count: int = 1) -> list[dict[str, Any]]:
    """Select a deterministic round-robin slice after the complete cohort is loaded."""
    if shard_count < 1:
        raise ValueError("--shard-count must be at least 1")
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError("--shard-index must be in [0, shard-count)")
    selected = rows[shard_index::shard_count]
    if not selected:
        raise ValueError("shard selects no scenarios; reduce --shard-count")
    return selected


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _assert_study_inputs_frozen(dataset_dir: Path) -> None:
    """Refuse live runs when code/catalog/active dataset has tracked or untracked edits."""
    try:
        active_dataset = dataset_dir.resolve().relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError("active evaluation dataset must be inside the project root") from exc
    source_paths = ["backend/texa", "backend/eval", "catalog", active_dataset]
    status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=all", "--", *source_paths],
                            cwd=ROOT, capture_output=True, text=True, check=True).stdout
    if status.strip():
        raise ValueError("Freeze and commit tracked/untracked study inputs before live execution")


def _schema_only_question(item: dict) -> str:
    """Direct-SQL baseline input: physical query schema plus user-authored inputs only.

    Do not pass catalog definitions, metric policies, gold-derived aliases/contracts,
    fixture values, or inferred source descriptions into the schema-only baseline.
    An explicit UI source selection is an observed user input shared with Texa.
    """
    scope = item.get("ui_scope") or []
    scope_text = ("\nUser-selected source IDs: " + ", ".join(map(str, scope))) if scope else ""
    return ("Database schema:\n" + CHALLENGE_SCHEMA + scope_text +
            "\n\nUser question:\n" + str(item["question"]))


def _score_output_table(columns, rows, item: dict) -> dict[str, Any]:
    """Score complete SQL output by position, independently of output aliases.

    Width and requested column order remain significant; rows are a multiset unless
    the case explicitly requests ordering. This prevents gold aliases from leaking
    into baseline prompts while retaining full-table execution correctness.
    """
    gold = item["expected_result"]
    strict = results_equal(columns, rows, gold["columns"], gold["rows"],
                           ordered=bool(item.get("ordered")))
    values_match = (len(columns) == len(gold["columns"]) and
                    results_equal(tuple(range(len(columns))), rows,
                                  tuple(range(len(gold["columns"]))), gold["rows"],
                                  ordered=bool(item.get("ordered"))))
    contract = score_business_result(columns, rows, gold["columns"], gold["rows"],
                                     ordered=bool(item.get("ordered")),
                                     contract=item.get("business_contract"))
    return {"result_correct": values_match,
            "alias_insensitive_result_correct": values_match,
            "strict_result_correct": strict,
            "business_result_correct": values_match,
            "business_contract_result_correct": contract["business_result_correct"],
            "output_contract_compliant": contract["output_contract_compliant"],
            "metric_protocol": "v3_schema_only_full_table",
            "answer_count": 1, "answer_correct": int(values_match)}


_ACTIONS = {"type": "object", "additionalProperties": False,
            "required": ["action", "sql", "ask_fields", "reason"], "properties": {
                "action": {"type": "string", "enum": ["sql", "clarify", "refuse", "conversation"]},
                "sql": {"type": "string"}, "ask_fields": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"}}}


class RawHistorySession:
    """B1 oracle with text-only history, no Texa answer/query-spec/compiler path."""
    def __init__(self, model: str, dsn: str, *, correction=True):
        from texa import llm
        self.llm, self.model, self.dsn = llm, model, dsn
        self.history: list[dict] = []
        self.calls: list[str] = []
        self.correction = correction

    def ask(self, question: str, *, choices=None, ui_scope=None) -> dict:
        public_item = {"question": question, "ui_scope": ui_scope or []}
        # Conversation/clarification controls must not see gold output aliases:
        # an alias such as revenue would disclose the unresolved metric intent.
        question = _schema_only_question(public_item)
        if choices:
            question += "\nUser clarification (only selected offered options): " + json.dumps(choices, ensure_ascii=False)
        prompt = "Prior conversation (user questions and actual returned result summaries only):\n" + json.dumps(self.history, ensure_ascii=False, default=str) + "\n\nLatest request:\n" + question
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
        return _score_output_table(record["columns"], record["rows"], item)
    except Exception:
        return {"business_result_correct": False, "result_correct": False, "answer_count": 1, "answer_correct": 0}


def _rescore_texa_table_scores(record: dict, item: dict, session, suite: str) -> dict:
    """Replace legacy alias-sensitive scores with this run's declared v3 score."""
    observed = {str(turn.get("id")): turn for turn in session.observed_turns if turn.get("id")}

    def score_turn(turn_row: dict, target: dict) -> None:
        trace = turn_row.get("trace") or {}
        observed_turn = observed.get(str(trace.get("id")))
        if observed_turn is None or "expected_result" not in target:
            return
        try:
            columns, rows = session.output(observed_turn)
            turn_row.update(_score_output_table(columns, rows, target))
            turn_row["columns"] = columns
            turn_row["row_count"] = len(rows)
        except Exception as exc:
            turn_row.update(result_correct=False, alias_insensitive_result_correct=False,
                            strict_result_correct=False, business_result_correct=False,
                            answer_count=1, answer_correct=0,
                            result_error=type(exc).__name__)

    if suite == "conversation":
        targets = item.get("turns", [])
        scored = []
        for turn_row in record.get("turns", []):
            index = int(turn_row.get("index", 0)) - 1
            if 0 <= index < len(targets):
                target = targets[index]
                if target.get("gold_sql") and target.get("scoring_kind") != "discussion_answer":
                    score_turn(turn_row, target)
                    if "result_correct" in turn_row:
                        scored.append(turn_row)
        record["answer_count"] = expected_answer_count(item)
        record["answer_correct"] = sum(bool(turn.get("result_correct")) for turn in scored)
        record["result_correct"] = (record["answer_count"] > 0
                                     and record["answer_correct"] == record["answer_count"])
        record["strict_result_correct"] = (record["answer_count"] > 0 and
            sum(bool(turn.get("strict_result_correct")) for turn in scored) == record["answer_count"])
        record["business_result_correct"] = record["result_correct"]
    elif suite == "clarification":
        turns = record.get("turns", [])
        if turns:
            score_turn(turns[-1], item)
            if "result_correct" in turns[-1]:
                record.update({key: turns[-1][key] for key in (
                    "result_correct", "alias_insensitive_result_correct", "strict_result_correct",
                    "business_result_correct", "business_contract_result_correct",
                    "output_contract_compliant", "metric_protocol") if key in turns[-1]})
                record["answer_count"] = 1
                record["answer_correct"] = int(bool(turns[-1]["result_correct"]))
                record["success"] = bool(turns[-1]["result_correct"]) and not record.get("oracle_error")
    return record


def diagnostic_score(item, actual):
    expected = item.get("expected_action")
    allowed = {"unsupported": {"refuse"}, "refuse": {"refuse"}, "clarify_source_conflict": {"clarify"},
               "clarify_or_explain_unsupported": {"clarify", "refuse"}}.get(expected)
    if allowed is None and isinstance(item.get("expected_actions"), list):
        allowed = set(item["expected_actions"])
    correct = actual in allowed if allowed is not None else None
    return {"answer_count": 0, "answer_correct": 0, "expected_action": expected,
            "actual_action": actual, "action_correct": correct, "action_scorable": allowed is not None,
            "success": correct, "manual_review_required": allowed is None, "unsupported_turn_count": 1}


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
            got = session.ask(target["question"], ui_scope=item.get("ui_scope"))
            out.append({"expected_action": "conversation", "actual_action": got["action"], "scorable": False,
                        "unsupported_reason": "social_turn_not_sql_scored"})
            continue
        got = session.ask(target["question"], ui_scope=item.get("ui_scope"))
        rounds = 0
        requested_fields = []
        if suite == "diagnostic":
            scored_action = diagnostic_score(target, got.get("action"))
            out.append({**scored_action, "expected_action": target.get("expected_action"),
                        "actual_action": got.get("action"), "refusal_reason": got.get("reason"),
                        "error_class": got.get("error_class"), "sql": got.get("sql"),
                        "scorable": False})
            continue
        while got.get("action") == "clarify" and rounds < 2:
            requested_fields.extend(got.get("ask_fields", []))
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
                got = session.ask(target["question"], choices=choices, ui_scope=item.get("ui_scope"))
                rounds += 1
            except Exception:
                got["error_class"] = "oracle_mismatch"
                break
        scoring = _score_rows(got, target) if "expected_result" in target else {}
        policy = clarification_policy_score(target.get("ask_fields", []), requested_fields) if suite == "clarification" else {}
        if policy and scoring:
            scoring["success"] = bool(scoring.get("business_result_correct", False) and policy["clarification_policy_correct"])
        out.append({"expected_action": target.get("action", "sql"), "actual_action": got.get("action"),
                    "refusal_reason": got.get("reason") if got.get("action") == "refuse" else None,
                    "error_class": got.get("error_class"), "scorable": "expected_result" in target,
                    "sql": got.get("sql"), "clarification_rounds": rounds,
                    "requested_clarification_fields": requested_fields,
                    **policy, **scoring})
    scored = [r for r in out if r.get("scorable")]
    if suite == "diagnostic":
        action_rows = [r for r in out if r.get("action_scorable")]
        correct = sum(bool(r.get("action_correct")) for r in action_rows)
        return {"turns": out, "answer_count": 0, "answer_correct": 0,
                "expected_action": targets[0].get("expected_action") if len(targets) == 1 else None,
                "actual_action": out[0].get("actual_action") if len(out) == 1 else None,
                "action_correct": (correct == len(action_rows)) if action_rows else None,
                "action_scorable": bool(action_rows), "success": bool(action_rows) and correct == len(action_rows),
                "manual_review_required": any(r.get("manual_review_required") for r in out),
                "unsupported_turn_count": len(out)}
    policy_rows = [r for r in out if "clarification_policy_correct" in r]
    policy_counts = {key: sum(r["clarification_counts"][key] for r in policy_rows)
                     for key in ("tp", "fp", "fn")}
    return {"turns": out, "answer_count": sum(r.get("answer_count", 0) for r in scored),
            "answer_correct": sum(r.get("answer_correct", 0) for r in scored),
            "unsupported_turn_count": sum(not r.get("scorable") for r in out),
            "clarification_counts": policy_counts,
            "clarification_policy_correct": all(r["clarification_policy_correct"] for r in policy_rows) if policy_rows else None,
            "success": bool(scored) and all(r.get("success", r.get("business_result_correct")) for r in scored)}


def execute(args, directory: Path, manifest: dict, rows: list[dict]) -> int:
    from texa import llm
    _assert_study_inputs_frozen(directory)
    try:
        from .run_benchmark import _call_usage
    except ImportError:
        from run_benchmark import _call_usage
    dsn = os.environ.get("TEXA_BENCHMARK_DSN")
    if not dsn:
        raise ValueError("TEXA_BENCHMARK_DSN is required for read-only evaluation")
    for scenario_id, target in gold_targets(rows):
        gold_check = score_expected_result(dsn, target["gold_sql"], target["expected_result"])
        if not gold_check.get("result_correct"):
            raise ValueError(f"gold validation failed for {scenario_id}")
    # Keep the challenge's two product sources only; the legacy event_benchmark
    # source is neither part of the authored scope nor a hidden third option.
    os.environ["TEXA_SOURCE_PROFILE"] = "demo"
    from texa import catalog as catalog_mod
    from texa.interpret import render_catalog
    cat = catalog_mod.published()
    source_map = catalog_mod.scoped_sources(cat, catalog_mod.load_sources(max_age=0))
    if set(manifest["sources"]) - set(source_map):
        raise ValueError("public catalog metadata is missing a challenge source")
    # Texa sees the published semantic catalog; schema-only direct baselines below
    # intentionally do not receive this context or any gold-derived output contract.
    public_cat = cat.model_copy(update={"verified_questions": []})
    public_context = render_catalog(public_cat, {sid: source_map[sid] for sid in manifest["sources"]})
    public_context += "\nPHYSICAL METRIC DEFINITIONS (public business contract, no examples)\n" + json.dumps(
        public_cat.model_dump(mode="json", include={"event_roles", "field_mappings", "semantic_values", "metrics"}),
        ensure_ascii=False, sort_keys=True)
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
        "backend/texa/intent.py", "backend/texa/prompts.py", "backend/texa/clarify.py", "backend/texa/memory.py",
        "backend/texa/compile.py", "backend/texa/examples.py", "backend/texa/consistency.py",
        "backend/texa/runtime_guard.py", "catalog/product_events.yaml", "catalog/verified_examples.yaml")
        if (ROOT / p).exists()]
    provenance = {"dataset_hashes": {str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                  "catalog_hash": hashlib.sha256((ROOT / "catalog/product_events.yaml").read_bytes()).hexdigest(),
                  "bank_hash": hashlib.sha256((ROOT / "catalog/verified_examples.yaml").read_bytes()).hexdigest(),
        "implementation_hashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                             for p in implementation_paths},
                  # This is Texa's catalog snapshot fingerprint, never a direct-baseline prompt input.
                  # Keep the established key because paired reports validate it per fixture world.
                  "public_context_hash": public_context_hash,
                  "evaluation_protocol": "v3_schema_only_full_table",
                  "baseline_input_policy": "schema_only_v1",
                  "baseline_schema_hash": hashlib.sha256(CHALLENGE_SCHEMA.encode()).hexdigest(),
                  "baseline_source_scope_policy": "explicit_ui_selection_only",
                  "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                  "example_policy": "sql_verified",
                  "usage_policy": "known completed logical calls; unresolved provider attempt reservations remain in the cumulative gateway ledger",
                  "sampling_policy": "identical prompts with provider defaults, no assumed diversity",
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
    call_prefix = uuid.uuid4().hex
    original_generate = llm.generate_structured
    def budgeted_generate(**kwargs):
        nonlocal calls, budget_exhausted
        with call_lock:
            if calls >= args.max_model_calls:
                budget_exhausted = True
                raise RuntimeError("accuracy model-call budget exhausted; run left incomplete")
            calls += 1
            kwargs["name"] = f"accuracy_{args.variant.lower()}_{call_prefix}_{calls}"
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
               "expected_scenario_count": len(rows),
               "shard": {"index": args.shard_index, "count": args.shard_count},
               "dataset": manifest, "status": "diagnostic_candidate", "fixture_world": args.world,
               "input_policy": ({"B0": "schema_only_direct_sql", "B0R": "schema_plus_verified_retrieved_examples",
                                 "B1": "schema_only_raw_history_clarification_and_one_sql_retry"}.get(
                                     args.variant, "texa_semantic_catalog_and_compiler")),
               "confirmatory_requested": args.confirmatory,
               "expected_answer_counts": {item["id"]: expected_answer_count(item) for item in rows},
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
                    prompt = _schema_only_question(item)
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
                    response = llm.generate_structured(model=args.model, system=SCHEMA_ONLY_SYSTEM, prompt=prompt,
                                                       schema=SQL_SCHEMA, name="accuracy_b0", max_output_tokens=1200)
                    raw_sql = response["sql"]
                    cols, values = execute_readonly(dsn, raw_sql)
                    result = _score_rows({"action": "sql", "columns": cols, "rows": values}, item)
                    row = {**result, "sql": raw_sql, "retrieved_example_ids": selected_examples,
                           "retrieval_activated": bool(selected_examples), "success": bool(result["business_result_correct"])}
                elif args.variant == "B1":
                    raw_session = RawHistorySession(args.model, dsn)
                    if args.suite == "diagnostic":
                        row = _run_raw_scenario(item, args.suite, manifest, raw_session)
                    else:
                        row = _run_raw_scenario(item, args.suite, manifest, raw_session)
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
                        try:
                            cols, values = session.output(current)
                            record.update(_score_output_table(cols, values, item))
                        except Exception as scoring_error:
                            record.update(result_correct=False, alias_insensitive_result_correct=False,
                                          business_result_correct=False, answer_count=1, answer_correct=0,
                                          result_error=type(scoring_error).__name__)
                        row = {**record, "answer_count": 1,
                               "answer_correct": int(bool(record.get("business_result_correct"))),
                               "success": bool(record.get("business_result_correct")), "turns": [{"trace": trace(current)}],
                               "texa_accuracy_trace": ((current.get("candidate") or
                                                        (current.get("state") or {}).get("candidate") or {}).get("_accuracy") )}
                    elif args.suite == "diagnostic":
                        current = session.ask(item["question"])
                        actual = {"answered": "sql", "discussed": "sql", "refused": "refuse",
                                  "conversation": "conversation", "needs_clarification": "clarify"}.get(current["status"], "error")
                        row = diagnostic_score(item, actual)
                        row["turns"] = [{"trace": trace(current)}]
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
                        row = _rescore_texa_table_scores(row, item, session, args.suite)
                    if args.suite == "clarification":
                        counts = row.get("clarification_counts")
                        if isinstance(counts, dict):
                            row.update(clarification_policy_from_counts(counts))
                        else:
                            actual_fields = []
                            for turn in row.get("turns", []):
                                actual_fields.extend(turn.get("asked", turn.get("requested_clarification_fields", [])))
                            row.update(clarification_policy_score(item.get("ask_fields", []), actual_fields))
                        row["success"] = bool(row.get("business_result_correct", row.get("result_correct"))
                                              and row["clarification_policy_correct"] and not row.get("oracle_error"))
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
                row = {"success": False, "answer_count": expected_answer_count(item), "answer_correct": 0,
                       "error_class": sql_error_diagnostic(exc), "error_type": type(exc).__name__}
            except Exception as exc:
                row = {"success": False, "answer_count": expected_answer_count(item), "answer_correct": 0,
                       "error_class": sql_error_diagnostic(exc), "error_type": type(exc).__name__, "sql": raw_sql,
                       "retrieved_example_ids": selected_examples, "retrieval_activated": bool(selected_examples)}
            finally:
                if session is not None and all(session.api.RUNS.get(t) is None or session.api.RUNS[t].done for t in session.turn_ids):
                    session.close()
            row.update(type="scenario", id=item["id"], cluster_id=item.get("cluster_id", item.get("family", item["id"])),
                       group=item.get("stratum", item.get("family", args.suite)), latency_ms=round((time.monotonic()-started)*1000),
                       usage={k: sum(x[k] for x in (_call_usage(name) for name in call_names[calls_before:calls]))
                              for k in ("calls", "input_tokens", "output_tokens", "model_ms")},
                       model_call_attempts=calls-calls_before, usage_complete=True)
            input_price = float(os.environ.get("TEXA_GATEWAY_INPUT_PRICE", "0") or 0)
            output_price = float(os.environ.get("TEXA_GATEWAY_OUTPUT_PRICE", "0") or 0)
            usage = row["usage"]
            row["usage_complete"] = usage["calls"] == row["model_call_attempts"]
            row["cost_basis"] = "known token usage only; gateway ledger retains uncertain attempt reservations"
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
    parser.add_argument("--split", choices=("dev", "test", "diagnostic"), default="dev")
    parser.add_argument("--world", choices=("base", "grain_counterexample", "coverage_edge"), required=True)
    parser.add_argument("--variant", choices=tuple(sorted({v for values in SUITE_VARIANTS.values() for v in values})), default="B0")
    parser.add_argument("--confirmatory", action="store_true", help="refuse unless a genuinely human-reviewed sealed artifact exists")
    parser.add_argument("--execute", action="store_true", help="live diagnostic execution; requires a supported runner backend")
    parser.add_argument("--model")
    parser.add_argument("--max-model-calls", type=int)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0, help="zero-based shard index")
    parser.add_argument("--shard-count", type=int, default=1, help="number of round-robin shards")
    parser.add_argument("--output", type=Path, default=ROOT / "backend/eval/results" / f"accuracy-{uuid.uuid4().hex}.jsonl")
    args = parser.parse_args(argv)
    try:
        if args.repeat < 1:
            raise ValueError("--repeat must be a positive run index")
        if (args.suite == "diagnostic" and args.split not in {"diagnostic", "test"}) or (args.suite != "diagnostic" and args.split not in {"dev", "test"}):
            raise ValueError("diagnostic suite requires --split diagnostic or test; answer suites require dev/test")
        manifest, rows = load_suite(args.dataset_dir.resolve(), args.suite, args.split, args.world)
        rows = select_shard(rows, args.shard_index, args.shard_count)
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
