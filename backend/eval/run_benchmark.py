"""Run the frozen direct-LLM-to-SQL baseline against the pilot benchmark.

Usage: TEXA_BENCHMARK_DSN=... uv run python eval/run_benchmark.py --split dev --model MODEL
The DSN must connect to the isolated `texa_benchmark` database using a read-only role.
This intentionally makes live calls only when explicitly invoked.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
import uuid
from pathlib import Path

from benchmark import (CASES_PATH, MANIFEST_PATH, ROOT, execute_readonly, load_cases, paired_delta_bootstrap,
                       dialogue_outcome_score, score_expected_result, score_result, score_sql, server_metadata,
                       validate_split_is_family_disjoint, write_result)
from texa import llm
import yaml

SYSTEM = "You are a PostgreSQL analyst. Generate one read-only SQL SELECT query for the user's question. " \
         "Use only the supplied schema and metric definitions. Return JSON with exactly one key, sql. " \
         "Use the exact output column aliases specified in the metric/dimension contract. " \
         "Do not use markdown, comments, multiple statements, DDL, DML, or functions that modify data."
DIALOGUE_SYSTEM = ("You are a conversational data assistant using PostgreSQL. For every turn, choose whether to answer, "
                   "clarify, refuse, or respond conversationally. If answering, generate one read-only SELECT query. "
                   "Use labeled prior turns only when the latest message refers to them. Return JSON matching the supplied schema.")
SQL_SCHEMA = {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"], "additionalProperties": False}
DIALOGUE_SCHEMA = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["answer", "clarify", "refuse", "conversation"]},
    "sql": {"type": "string"}, "ask_fields": {"type": "array", "items": {"type": "string"}},
    "reference_turns": {"type": "array", "items": {"type": "integer"}},
    "message": {"type": "string"}}, "required": ["action", "sql", "ask_fields", "reference_turns", "message"],
    "additionalProperties": False}


def prompt_for(case: dict, manifest: dict) -> str:
    contract = ("\nBusiness result columns (pre-registered; include every listed ID):\n" +
                yaml.safe_dump(case["business_contract"], sort_keys=True, allow_unicode=True)
                if case.get("business_contract") else "")
    return ("Schema and grain:\n" + manifest["schema"] + "\n\nMetric definitions:\n" +
            manifest["metric_definitions"] + "\n\nOutput aliases (required):\n" +
            yaml.safe_dump(manifest["output_aliases"], sort_keys=True, allow_unicode=True) +
            contract + "\nQuestion:\n" + case["question"])


def dataset_path(args, name: str) -> Path:
    directory = getattr(args, "dataset_dir", None)
    return (_project_path(directory) if directory else MANIFEST_PATH.parent) / name


def validate_dialogue_gold(args, dsn: str, dialogues: list[dict], output: Path) -> int:
    """Validate SQL/reference tables only; this does not score memory or actions."""
    results = []
    for dialogue in dialogues:
        for number, turn in enumerate(dialogue["turns"], 1):
            if turn["action"] not in {"answer", "clarification_answer"}:
                continue
            if not turn.get("gold_sql") or "expected_result" not in turn:
                result = {"status": "missing_gold", "result_correct": False}
            else:
                result = score_expected_result(dsn, turn["gold_sql"],
                    turn["expected_result"] | {"ordered": turn.get("ordered", False)})
            result.update(dialogue_id=dialogue["id"], turn=number, method="gold")
            results.append(result)
            write_result(output, result)
    passed = sum(bool(r["result_correct"]) for r in results)
    write_result(output, {"type": "dialogue_gold_summary", "answer_turns": len(results), "correct": passed,
                          "actions_validated": False})
    print(f"dialogue gold SQL/reference tables: {passed}/{len(results)}; raw: {output}")
    return int(not results or passed != len(results))


def run(args) -> int:
    if args.compare_results:
        compare_results_files(*args.compare_results)
        return 0
    # Pin the evaluation catalog before any Texa request; do not inherit demo scope.
    os.environ["TEXA_SOURCE_PROFILE"] = "evaluation"
    dsn = os.environ.get("TEXA_BENCHMARK_DSN")
    if not dsn:
        raise SystemExit("Set TEXA_BENCHMARK_DSN to the isolated texa_benchmark database (read-only role).")
    if args.method != "gold" and not args.model:
        raise SystemExit("--model is required for direct and texa provider runs.")
    if args.method == "texa" and not args.memory_mode:
        os.environ["TEXA_MEMORY_MODE"] = "structured"
    args.engine = server_metadata(dsn)
    manifest = yaml.safe_load(dataset_path(args, "manifest.yaml").read_text(encoding="utf-8"))
    fixture_path = _project_path(str(dataset_path(args, manifest.get("fixture", "fixture.sql"))))
    args.engine["benchmark"] = {
        "name": manifest.get("name"), "version": manifest.get("version"),
        "sha256": {"manifest.yaml": hashlib.sha256(dataset_path(args, "manifest.yaml").read_bytes()).hexdigest(),
                   "fixture.sql": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
                   **{name: hashlib.sha256(dataset_path(args, name).read_bytes()).hexdigest()
                      for name in ("cases.yaml", "dialogues.yaml")}}}
    if args.memory_mode:
        os.environ["TEXA_MEMORY_MODE"] = args.memory_mode
    if args.dialogues:
        return run_dialogues(args, dsn)
    cases = load_cases(_project_path(args.cases) if args.cases else dataset_path(args, "cases.yaml"))
    validate_split_is_family_disjoint(cases)
    cases = [c for c in cases if c["split"] == args.split]
    if not cases:
        raise SystemExit(f"No cases in split {args.split!r}.")
    output = _project_path(args.output)
    passed = 0
    results = []
    for case in cases:
        try:
            started = time.monotonic()
            call_name = f"bench_{uuid.uuid4().hex[:20]}"
            if args.method == "gold":
                result = score_expected_result(dsn, case["gold_sql"],
                                               case["expected_result"] | {"ordered": case.get("ordered", False)},
                                               contract=case.get("business_contract"))
            elif args.method == "direct":
                response = llm.generate_structured(model=args.model, system=SYSTEM, prompt=prompt_for(case, manifest),
                                                   schema=SQL_SCHEMA, name=call_name, max_output_tokens=1200)
                result = score_sql(dsn, response["sql"], case)
                result["sql"] = response["sql"]
            else:
                from texa import answer
                turn = answer.ask_cli(case["question"], model=args.model)
                if turn.get("status") == "answered":
                    full = answer.full_result(turn["id"])
                    if full.get("partial"):
                        raise ValueError("Texa full_result was truncated; refusing to score partial output")
                    cols = [c["name"] for c in turn.get("columns", []) if not c["name"].startswith("__")]
                    rows = [tuple(row.get(c) for c in cols) for row in full.get("rows", [])]
                    result = score_result(dsn, cols, rows, case)
                    result.update(system_status=turn["status"], sql=turn.get("compiled_sql"))
                else:
                    result = {"status": "not_answered", "result_correct": False,
                              "business_result_correct": False, "output_contract_compliant": False,
                              "system_status": turn.get("status"), "error": turn.get("message") or turn.get("error")}
            result.update(case_id=case["id"], split=case["split"], family=case["family"], engine=args.engine)
            result["latency_ms"] = round((time.monotonic() - started) * 1000)
            if args.method == "direct":
                result["usage"] = _call_usage(call_name)
            elif args.method == "texa":
                result["usage"] = _turn_usage(str(turn["id"]))
        except Exception as exc:
            result = {"case_id": case["id"], "split": case["split"], "family": case["family"],
                      "status": "error", "result_correct": False, "business_result_correct": False,
                      "output_contract_compliant": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        result["primary_correct"] = bool(result.get("business_result_correct", result.get("result_correct")))
        passed += result["primary_correct"]
        result.update(method=args.method, model=args.model, in_scope=case.get("in_scope", True),
                      source_id=case.get("source_id"), language=case.get("language"), intent=case.get("family"))
        results.append(result)
        write_result(output, result)
        print(f"{'PASS' if result['primary_correct'] else 'FAIL'} {case['id']} ({result['status']})")
    print(f"business result accuracy: {passed}/{len(cases)} = {passed / len(cases):.1%}; raw: {output}")
    scoped = [r for r in results if r["in_scope"]]
    def slice_accuracy(key):
        sliced = {}
        for result in results:
            label = result.get(key)
            if label:
                acc = sliced.setdefault(label, {"correct": 0, "cases": 0})
                acc["correct"] += int(bool(result.get("primary_correct")))
                acc["cases"] += 1
        return {label: {**counts, "accuracy": counts["correct"] / counts["cases"]}
                for label, counts in sorted(sliced.items())}
    latencies = sorted(r["latency_ms"] for r in results if "latency_ms" in r)
    write_result(output, {"type": "single_turn_summary", "method": args.method, "model": args.model,
                          "engine": args.engine, "cases": len(results), "correct": passed,
                          "in_scope_cases": len(scoped), "in_scope_correct": sum(bool(r.get("primary_correct")) for r in scoped),
                          "strict_correct": sum(bool(r.get("result_correct")) for r in results),
                          "strict_accuracy": sum(bool(r.get("result_correct")) for r in results) / len(results),
                          "business_accuracy_by_source": slice_accuracy("source_id"),
                          "business_accuracy_by_language": slice_accuracy("language"),
                          "executable": sum(r.get("status") == "ok" for r in results),
                          "p50_ms": latencies[len(latencies)//2] if latencies else None,
                          "p95_ms": latencies[min(len(latencies)-1, int(len(latencies)*0.95))] if latencies else None})
    return int(args.method == "gold" and passed != len(cases))


def _wait_turn(answer_module, turn_id: str, timeout_s: int) -> dict:
    deadline = time.monotonic() + timeout_s
    run = answer_module.RUNS.get(turn_id)
    while run is not None and not run.done and time.monotonic() < deadline:
        time.sleep(0.1)
    if run is None or not run.done:
        raise TimeoutError(f"turn {turn_id} did not finish within {timeout_s}s")
    return answer_module.load_turn(turn_id)


def _project_path(value: str) -> Path:
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError(f"benchmark input/output paths must stay under {ROOT}") from exc
    return path


def compare_results_files(left_path: str, right_path: str) -> dict:
    import json

    def read(path: str) -> tuple[dict[str, bool], dict[str, str], str]:
        resolved = _project_path(path)
        rows = [json.loads(line) for line in resolved.read_text(encoding="utf-8").splitlines() if line.strip()]
        entries: dict[str, bool] = {}
        strata: dict[str, str] = {}
        score_field = "dialogue_success"
        for row in rows:
            if row.get("type") == "dialogue":
                key, value = row.get("id"), row.get("dialogue_success")
                family = str(key)
            elif row.get("type") == "single_turn_summary":
                continue
            else:
                key = row.get("case_id")
                field = "business_result_correct" if "business_result_correct" in row else "result_correct"
                if score_field not in {"dialogue_success", field} and entries:
                    raise ValueError(f"{resolved}: mixed score fields in result file")
                score_field = field
                value = row.get(field)
                family = row.get("family", "unlabeled")
            if key is not None:
                if str(key) in entries:
                    raise ValueError(f"{resolved}: duplicate case/scenario ID {key}; use one run per file")
                entries[str(key)] = bool(value)
                strata[str(key)] = str(family)
        return entries, strata, score_field

    left, left_strata, left_field = read(left_path)
    right, right_strata, right_field = read(right_path)
    if left_field != right_field:
        raise ValueError("paired result files must use the same scoring protocol/field")
    if left_strata != right_strata:
        raise ValueError("paired result files must use the same family/dialogue labels")
    result = paired_delta_bootstrap(left, right, strata=left_strata)
    result["left_accuracy"] = sum(left.values()) / len(left)
    result["right_accuracy"] = sum(right.values()) / len(right)
    result["score_field"] = left_field
    result["left_file"] = str(_project_path(left_path).relative_to(ROOT))
    result["right_file"] = str(_project_path(right_path).relative_to(ROOT))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _actual_action(turn: dict) -> str:
    return {"answered": "answer", "needs_clarification": "clarify", "refused": "refuse",
            "conversation": "conversation", "discussed": "answer"}.get(turn.get("status"), "error")


def _check_dialogue_state(expected: dict, turn: dict) -> dict[str, bool]:
    spec = turn.get("query_spec") or {}
    checks: dict[str, bool] = {}
    if "metric" in expected:
        choices = [spec.get("recipe")] + (spec.get("metrics") or [])
        checks["metric"] = expected["metric"] in choices
    if "breakdown" in expected:
        checks["breakdown"] = (expected["breakdown"] in (spec.get("selection") or [])) if expected["breakdown"] else not (spec.get("selection") or [])
    if "filters" in expected:
        actual_filters = {}
        for item in spec.get("filters") or []:
            actual_filters[item.get("field")] = sorted(item.get("values") or [])
        expected_filters = {field: sorted(value if isinstance(value, list) else [value])
                            for item in expected["filters"] for field, value in item.items()}
        checks["filters"] = actual_filters == expected_filters
    if "time_range" in expected:
        actual = spec.get("time_range") or {}
        value = expected["time_range"]
        if value == "all":
            checks["time_range"] = actual.get("kind") == "all"
        elif isinstance(value, str):
            checks["time_range"] = actual.get("kind") == "between" and str(actual.get("start")) == value and str(actual.get("end")) == value
        else:
            checks["time_range"] = actual == value
    if "ask_fields" in expected:
        asked = {f["id"] for f in (turn.get("form") or {}).get("fields", [])}
        requested = set(expected["ask_fields"])
        checks["ask_fields"] = asked == requested
    return checks


def _turn_usage(turn_id: str) -> dict[str, int]:
    from texa import db
    with db.app_conn() as conn:
        row = conn.execute("SELECT count(*) AS calls, coalesce(sum(input_tokens),0) AS input_tokens, "
                           "coalesce(sum(output_tokens),0) AS output_tokens, coalesce(sum(ms),0) AS model_ms "
                           "FROM app.llm_usage WHERE turn_id=%s", (turn_id,)).fetchone()
    return {k: int(row[k] or 0) for k in ("calls", "input_tokens", "output_tokens", "model_ms")}


def _call_usage(call_name: str) -> dict[str, int]:
    from texa import db
    with db.app_conn() as conn:
        row = conn.execute("SELECT count(*) AS calls, coalesce(sum(input_tokens),0) AS input_tokens, "
                           "coalesce(sum(output_tokens),0) AS output_tokens, coalesce(sum(ms),0) AS model_ms "
                           "FROM app.llm_usage WHERE call_name=%s", (call_name,)).fetchone()
    return {k: int(row[k] or 0) for k in ("calls", "input_tokens", "output_tokens", "model_ms")}


def _score_dialogue_turn(expected: dict, turn: dict, expected_action: str, dsn: str) -> dict:
    actual_action = _actual_action(turn)
    checks = _check_dialogue_state(expected.get("state") or {}, turn)
    out = {"expected_action": expected_action, "actual_action": actual_action,
           "action_correct": expected_action == actual_action, "slot_correct": checks,
           "slots_exact": bool(checks) and all(checks.values()) if checks else None}
    # Preserve concise runtime diagnostics in the evaluation artifact. Do not log
    # prompts or provider response bodies; public_turn exposes only normalized state.
    error = turn.get("error")
    out.update(system_status=turn.get("status"), system_error=error,
               system_code=(error.get("code") if isinstance(error, dict) else None) or turn.get("code"),
               system_message=(error.get("message") if isinstance(error, dict) else None) or turn.get("message"),
               form_field_ids=sorted(f.get("id") for f in (turn.get("form") or {}).get("fields", []) if f.get("id")))
    gold_sql = expected.get("gold_sql")
    if gold_sql and actual_action == "answer":
        full = None
        try:
            from texa import answer
            full = answer.full_result(turn["id"])
            cols = [c["name"] for c in turn.get("columns", []) if not c["name"].startswith("__")]
            if full.get("partial"):
                raise ValueError("full_result is partial; cannot score truncated rows")
            rows = [tuple(row.get(c) for c in cols) for row in full.get("rows", [])]
            scored = score_result(dsn, cols, rows, {"gold_sql": gold_sql, "ordered": expected.get("ordered", False)})
            out.update({key: scored[key] for key in ("result_correct", "business_result_correct",
                                                      "output_contract_compliant", "metric_protocol") if key in scored})
        except Exception as exc:
            out["result_correct"] = False
            out["result_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    context = turn.get("context") or {}
    if "referenced_turn" in expected:
        out["reference_expected"] = expected["referenced_turn"]
        out["reference_actual"] = context.get("references") or []
        out["reference_correct"] = None  # filled by caller after label IDs are mapped
    if "ask_fields" in expected:
        asked = {f["id"] for f in (turn.get("form") or {}).get("fields", [])}
        requested = set(expected["ask_fields"])
        out["clarification_precision"] = len(asked & requested) / len(asked) if asked else 1.0
        out["clarification_recall"] = len(asked & requested) / len(requested) if requested else 1.0
    return out


def run_dialogues(args, dsn: str) -> int:
    os.environ["TEXA_SOURCE_PROFILE"] = "evaluation"
    import yaml
    from texa import answer, db

    dialogues_path = _project_path(args.dialogues) if isinstance(args.dialogues, str) else dataset_path(args, "dialogues.yaml")
    dialogues = yaml.safe_load(dialogues_path.read_text(encoding="utf-8"))
    if args.split:
        dialogues = [d for d in dialogues if d["split"] == args.split]
    if not dialogues:
        raise SystemExit("No dialogue scenarios match the selected split.")
    output = _project_path(args.output)
    if args.method == "gold":
        return validate_dialogue_gold(args, dsn, dialogues, output)
    if args.method == "direct":
        return run_direct_dialogues(args, dsn, dialogues, output)
    successes = 0
    action_confusion: dict[str, dict[str, int]] = {}
    clarify_tp = clarify_fp = clarify_fn = 0
    for dialogue in dialogues:
        conversation_id = None
        labels: dict[int, str] = {}
        rows = []
        pending_turn = None
        usage_seen: dict[str, dict[str, int]] = {}
        for turn_index, item in enumerate(dialogue["turns"], start=1):
            started = time.monotonic()
            expected_action = item["action"]
            if expected_action == "clarification_answer":
                if pending_turn is None:
                    check = {"dialogue_id": dialogue["id"], "turn_index": turn_index,
                             "question": item["question"], "expected_action": "answer",
                             "actual_action": "error", "action_correct": False,
                             "slots_exact": False, "result_correct": False,
                             "oracle_answer_valid": False,
                             "error": "oracle answer has no preceding clarification"}
                    rows.append(check)
                    print(f"FAIL {dialogue['id']} turn {turn_index} (missing pending clarification)")
                    continue
                asked = {f["id"] for f in (pending_turn.get("form") or {}).get("fields", [])}
                oracle = item.get("oracle_answers") or {}
                if not oracle or set(oracle) != asked:
                    rows.append({"expected_action": "answer", "actual_action": "error", "action_correct": False,
                                 "slots_exact": False, "result_correct": False, "oracle_answer_valid": False,
                                 "error": "oracle fields do not match the actual clarification fields"})
                    pending_turn = None
                    continue
                try:
                    answer.answer_clarification(str(pending_turn["id"]), oracle)
                    actual = _wait_turn(answer, str(pending_turn["id"]), args.turn_timeout)
                    actual = answer.public_turn(actual)
                except Exception as exc:
                    rows.append({"dialogue_id": dialogue["id"], "turn_index": turn_index,
                                 "question": item["question"], "expected_action": "answer",
                                 "actual_action": "error", "action_correct": False,
                                 "slots_exact": False, "result_correct": False,
                                 "oracle_answer_valid": False,
                                 "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                    pending_turn = None
                    print(f"FAIL {dialogue['id']} turn {turn_index} ({type(exc).__name__})")
                    continue
                scoring_action = "answer"
            else:
                try:
                    ids = answer.ask(item["question"], conversation_id, args.model, None)
                    conversation_id = ids["conversation_id"]
                    actual = answer.public_turn(_wait_turn(answer, ids["turn_id"], args.turn_timeout))
                except Exception as exc:
                    rows.append({"dialogue_id": dialogue["id"], "turn_index": turn_index,
                                 "question": item["question"], "expected_action": expected_action,
                                 "actual_action": "error", "action_correct": False,
                                 "slots_exact": False, "result_correct": False,
                                 "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                    pending_turn = None
                    print(f"FAIL {dialogue['id']} turn {turn_index} ({type(exc).__name__})")
                    continue
                labels[turn_index] = str(actual["id"])
                scoring_action = expected_action
                pending_turn = actual if actual["status"] == "needs_clarification" else None
            check = _score_dialogue_turn(item, actual, scoring_action, dsn)
            elapsed = round((time.monotonic() - started) * 1000)
            turn_id = str(actual["id"])
            cumulative = _turn_usage(turn_id)
            previous = usage_seen.get(turn_id, {k: 0 for k in cumulative})
            usage_seen[turn_id] = cumulative
            usage = {k: cumulative[k] - previous[k] for k in cumulative}
            check.update(dialogue_id=dialogue["id"], turn_index=turn_index, question=item["question"],
                         latency_ms=elapsed, usage=usage)
            if "referenced_turn" in item:
                target = labels.get(int(item["referenced_turn"]))
                references = set((actual.get("context") or {}).get("references") or [])
                # A single explicit result target must resolve to its annotated turn.
                check["reference_correct"] = (str(target) in references) if target is not None else False
                check["reference_expected_turn_id"] = target
            asked = {f["id"] for f in (actual.get("form") or {}).get("fields", [])} if _actual_action(actual) == 'clarify' else set()
            expected_asked = set(item.get("ask_fields", []))
            clarify_tp += len(asked & expected_asked)
            clarify_fp += len(asked - expected_asked)
            clarify_fn += len(expected_asked - asked)
            action_confusion.setdefault(check["expected_action"], {})[check["actual_action"]] = \
                action_confusion.setdefault(check["expected_action"], {}).get(check["actual_action"], 0) + 1
            check["memory_context"] = actual.get("context")
            check.update(dialogue_outcome_score(
                expected_action=check["expected_action"], actual_action=check["actual_action"],
                result_correct=check.get("result_correct"), expected_fields=expected_asked,
                actual_fields=asked, reference_expected=check.get("reference_correct"),
                oracle_answer_valid=check.get("oracle_answer_valid", True),
                context_contamination=check.get("context_contamination", False)))
            rows.append(check)
            print(f"{'PASS' if check['observable_success'] else 'FAIL'} {dialogue['id']} turn {turn_index}")
        required = rows
        # Internal QuerySpec/slot scores are diagnostics, not part of cross-system parity.
        dialogue_ok = all(r.get("observable_success", False) for r in required)
        successes += int(dialogue_ok)
        payload = {"type": "dialogue", "id": dialogue["id"], "split": dialogue["split"],
                   "dependency_distance": dialogue.get("dependency_distance"), "memory_mode": args.memory_mode or "structured",
                   "dialogue_success": dialogue_ok, "engine": args.engine, "turns": rows}
        write_result(output, payload)
        if conversation_id:
            with db.app_conn() as conn:
                conn.execute("DELETE FROM app.conversations WHERE id=%s", (conversation_id,))
    print(f"dialogue success: {successes}/{len(dialogues)} = {successes / len(dialogues):.1%}; raw: {output}")
    precision = clarify_tp / (clarify_tp + clarify_fp) if clarify_tp + clarify_fp else None
    recall = clarify_tp / (clarify_tp + clarify_fn) if clarify_tp + clarify_fn else None
    write_result(output, {"type": "dialogue_summary", "method": "texa", "memory_mode": args.memory_mode or "structured",
                          "action_confusion": action_confusion, "clarification_precision": precision,
                          "clarification_recall": recall, "dialogues": len(dialogues), "dialogue_successes": successes})
    p_text = f"{precision:.1%}" if precision is not None else "N/A"
    r_text = f"{recall:.1%}" if recall is not None else "N/A"
    print(f"action confusion: {action_confusion}; clarification P/R: {p_text}/{r_text}")
    return 0


def run_direct_dialogues(args, dsn: str, dialogues: list[dict], output: Path) -> int:
    """B1 baseline: raw last-six user/assistant messages, no structured state."""
    import yaml

    manifest = yaml.safe_load(dataset_path(args, "manifest.yaml").read_text(encoding="utf-8"))
    passed = 0
    usage_by_dialogue = []
    for dialogue in dialogues:
        call_name = f"dlg_{uuid.uuid4().hex[:16]}"
        history: list[str] = []
        rows = []
        pending_fields: list[str] = []
        for turn_index, item in enumerate(dialogue["turns"], start=1):
            question = item["question"]
            prior = "\n".join(history[-12:])
            prompt = (f"DATABASE CONTEXT\n{manifest['schema']}\n\nMETRIC DEFINITIONS\n{manifest['metric_definitions']}\n\n"
                      f"OUTPUT ALIASES (use exact aliases)\n{yaml.safe_dump(manifest['output_aliases'], sort_keys=True, allow_unicode=True)}\n\n"
                      f"INTERACTION POLICY\n{manifest.get('interaction_policy', '')}\n\n"
                      f"DIALOGUE (oldest first, at most six prior turns)\n{prior}\n\nLATEST USER MESSAGE\n{question}")
            started = time.monotonic()
            try:
                response = llm.generate_structured(model=args.model, system=DIALOGUE_SYSTEM +
                " For ambiguity, return action clarify and list only missing field names in ask_fields. "
                "For references, use prior user-turn numbers from the labeled dialogue history in reference_turns. "
                "For out-of-scope questions, return refuse. For social turns, return conversation.",
                prompt=prompt, schema=DIALOGUE_SCHEMA, name=call_name, max_output_tokens=1200)
            except Exception as exc:
                row = {"dialogue_id": dialogue["id"], "turn_index": turn_index, "question": question,
                       "expected_action": "answer" if item["action"] == "clarification_answer" else item["action"],
                       "actual_action": "error", "action_correct": False, "result_correct": False,
                       "error": f"{type(exc).__name__}: {str(exc)[:200]}", "oracle_answer_valid": False}
                rows.append(row)
                history.extend([f"Turn {turn_index} User: {question}", "Turn failed; no state is available to reuse."])
                pending_fields = []
                continue
            actual_action = response["action"]
            expected_action = "answer" if item["action"] == "clarification_answer" else item["action"]
            row = {"dialogue_id": dialogue["id"], "turn_index": turn_index, "question": item["question"],
                   "expected_action": expected_action, "actual_action": actual_action,
                   "action_correct": expected_action == actual_action,
                   "latency_ms": round((time.monotonic() - started) * 1000),
                   "ask_fields": response["ask_fields"], "reference_turns": response["reference_turns"]}
            if expected_action == "clarify":
                expected_fields = set(item.get("ask_fields") or [])
                asked = set(response["ask_fields"])
                row["clarification_precision"] = len(asked & expected_fields) / len(asked) if asked else 1.0
                row["clarification_recall"] = len(asked & expected_fields) / len(expected_fields) if expected_fields else 1.0
                pending_fields = response["ask_fields"]
            if expected_action == "answer" and (actual_action != "answer" or not response["sql"].strip()):
                row["result_correct"] = False
            if actual_action == "answer" and response["sql"].strip():
                gold_sql = item.get("gold_sql")
                if gold_sql:
                    row["result_correct"] = score_sql(dsn, response["sql"], {"gold_sql": gold_sql,
                        "ordered": item.get("ordered", False)})["result_correct"]
                row["sql"] = response["sql"]
                try:
                    out_columns, out_rows = execute_readonly(dsn, response["sql"])
                    row["result_preview"] = {"columns": list(out_columns), "rows": [list(r) for r in out_rows]}
                except Exception as exc:
                    row["result_preview_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            expected_ref = item.get("referenced_turn")
            actual_refs = response["reference_turns"]
            row["reference_correct"] = (actual_refs == [expected_ref]) if expected_ref is not None else not actual_refs
            if expected_ref is None:
                row["context_contamination"] = bool(actual_refs)
            oracle = item.get("oracle_answers") or {}
            if item["action"] == "clarification_answer" and (
                    not oracle or set(oracle) != set(pending_fields)):
                row["oracle_answer_valid"] = False
            else:
                row["oracle_answer_valid"] = True
            row.update(dialogue_outcome_score(
                expected_action=expected_action, actual_action=actual_action,
                result_correct=row.get("result_correct"), expected_fields=item.get("ask_fields") or [],
                actual_fields=response.get("ask_fields") or [], reference_expected=row.get("reference_correct"),
                oracle_answer_valid=row.get("oracle_answer_valid", True),
                context_contamination=row.get("context_contamination", False)))
            rows.append(row)
            answer_text = f"Assistant: {actual_action}; asked={response['ask_fields']}; {response['message']}"
            if row.get("result_preview"):
                answer_text += f"; result={row['result_preview']}"
            history.extend([f"Turn {turn_index} User: {question}", f"Turn {turn_index} {answer_text}"])
        dialogue_ok = all(r.get("observable_success", False) for r in rows)
        passed += int(dialogue_ok)
        usage_by_dialogue.append(_call_usage(call_name))
        write_result(output, {"type": "dialogue", "id": dialogue["id"], "split": dialogue["split"],
                             "baseline": "direct_llm_raw_last6", "dependency_distance": dialogue.get("dependency_distance"),
                             "dialogue_success": dialogue_ok, "usage": _call_usage(call_name), "turns": rows})
    print(f"dialogue success: {passed}/{len(dialogues)} = {passed / len(dialogues):.1%}; raw: {output}")
    write_result(output, {"type": "dialogue_summary", "method": "direct_llm_raw_last6", "dialogues": len(dialogues),
                          "dialogue_successes": passed, "usage": {k: sum(x[k] for x in usage_by_dialogue)
                          for k in ("calls", "input_tokens", "output_tokens", "model_ms")}})
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "test"))
    parser.add_argument("--model")
    parser.add_argument("--method", choices=("direct", "texa", "gold"), default="direct",
                        help="direct is raw LLM-to-SQL; texa runs the current system; gold validates frozen SQL/results.")
    parser.add_argument("--dataset-dir", help="Directory containing manifest/cases/dialogues YAML (default: pilot)")
    parser.add_argument("--cases", help="Optional case YAML path")
    parser.add_argument("--output", default=str(ROOT / "backend" / "eval" / "results" / f"run-{time.time_ns()}-{uuid.uuid4().hex[:12]}.jsonl"))
    parser.add_argument("--dialogues", nargs="?", const=True, default=False,
                        help="Run annotated dialogue rollouts instead of single-turn cases.")
    parser.add_argument("--turn-timeout", type=int, default=150)
    parser.add_argument("--memory-mode", choices=("structured", "window6"),
                        help="Texa history strategy; run each mode in a separate process for paired ablation.")
    parser.add_argument("--compare-results", nargs=2, metavar=("LEFT_JSONL", "RIGHT_JSONL"),
                        help="Compare paired case/dialogue results with a scenario-level bootstrap interval.")
    sys.exit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
