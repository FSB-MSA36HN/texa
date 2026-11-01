import json
import importlib.util
import subprocess
import sys

import pytest

from eval.benchmark import (CASES_PATH, dialogue_scores, load_cases, results_equal,
                            paired_delta_bootstrap, validate_split_is_family_disjoint)


def test_pilot_size_and_family_disjoint_splits():
    cases = load_cases()
    assert len(cases) == 24
    assert sum(case["split"] == "dev" for case in cases) == 12
    assert sum(case["split"] == "test" for case in cases) == 12
    validate_split_is_family_disjoint(cases)
    assert all("expected_result" in case for case in cases)


def test_paired_delta_bootstrap_is_reproducible_and_paired_by_case():
    left = {"a": False, "b": True, "c": False}
    right = {"a": True, "b": True, "c": False}
    result = paired_delta_bootstrap(left, right, iterations=250)
    assert result["n"] == 3 and result["delta"] == pytest.approx(1 / 3)
    assert result == paired_delta_bootstrap(left, right, iterations=250)
    assert paired_delta_bootstrap(left, right, iterations=250, strata={"a": "x", "b": "x", "c": "y"})["strata"] == 2
    with pytest.raises(ValueError):
        paired_delta_bootstrap(left, {"a": True}, iterations=10)


def test_dialogue_pilot_has_long_turns_and_gold_for_answer_actions():
    import yaml
    dialogues = yaml.safe_load((CASES_PATH.parent.parent.parent / "data" / "benchmark" / "dialogues.yaml").read_text())
    assert len(dialogues) == 6
    assert max(len(d["turns"]) for d in dialogues) >= 10
    answer_turns = [t for d in dialogues for t in d["turns"] if t["action"] in {"answer", "clarification_answer"}]
    assert all(t.get("gold_sql") for t in answer_turns)


def test_cli_compares_paired_result_files_with_family_bootstrap():
    backend = CASES_PATH.parents[2] / "backend"
    proc = subprocess.run([sys.executable, "eval/run_benchmark.py", "--compare-results",
                           "tests/fixtures/eval_left.jsonl", "tests/fixtures/eval_right.jsonl"],
                          cwd=backend, capture_output=True, text=True, check=True)
    summary = json.loads(proc.stdout)
    assert summary["n"] == 3
    assert summary["strata"] == 2
    assert summary["delta"] == pytest.approx(1 / 3)


def test_dialogue_rollout_modes_smoke_with_mocked_model_no_provider_calls(monkeypatch):
    backend = CASES_PATH.parents[2] / "backend"
    eval_dir = backend / "eval"
    monkeypatch.syspath_prepend(str(eval_dir))
    spec = importlib.util.spec_from_file_location("run_benchmark_smoke", eval_dir / "run_benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = backend / "tests" / "fixtures" / "dialogue_rollout.yaml"
    output_rows = []
    monkeypatch.setattr(module, "write_result", lambda _path, result: output_rows.append(result))
    monkeypatch.setattr(module, "score_sql", lambda *_a, **_k: {"result_correct": True, "status": "ok"})
    monkeypatch.setattr(module, "score_result", lambda *_a, **_k: {"result_correct": True, "status": "ok"})
    monkeypatch.setattr(module, "execute_readonly", lambda *_a, **_k: (("events",), ((12,),)))
    monkeypatch.setattr(module, "_call_usage", lambda _name: {"calls": 1, "input_tokens": 10, "output_tokens": 2, "model_ms": 5})
    responses = iter([
        {"action": "clarify", "sql": "", "ask_fields": ["time_range"], "reference_turns": [], "message": "Which period?"},
        {"action": "answer", "sql": "SELECT 1", "ask_fields": [], "reference_turns": [], "message": "Done"},
        {"action": "answer", "sql": "SELECT 2", "ask_fields": [], "reference_turns": [1], "message": "Done"},
    ])
    monkeypatch.setattr(module.llm, "generate_structured", lambda **_kw: next(responses))
    args = type("Args", (), {"model": "mock", "memory_mode": None})()
    assert module.run_direct_dialogues(args, "unused", __import__("yaml").safe_load(fixture.read_text()), fixture) == 0
    summary = output_rows[-1]
    assert summary["dialogue_successes"] == 1
    assert output_rows[0]["turns"][1]["oracle_answer_valid"]
    assert output_rows[0]["turns"][2]["reference_correct"]
    assert "{'time_range': ['all']}" not in output_rows[0]["turns"][1]["question"]


def test_result_comparator_keeps_duplicates_and_nulls_but_ignores_row_order():
    assert results_equal(["n", "v"], [(1, None), (1, 2)], ["n", "v"], [(1, 2.0000001), (1, None)])
    assert not results_equal(["n"], [(1,), (1,)], ["n"], [(1,)])
    assert not results_equal(["n"], [(1,)], ["n"], [(None,)])


def test_ordered_results_check_requested_rank_order():
    assert results_equal(["k"], [("a",), ("b",)], ["k"], [("a",), ("b",)], ordered=True)
    assert not results_equal(["k"], [("b",), ("a",)], ["k"], [("a",), ("b",)], ordered=True)


def test_datetime_values_and_column_order_are_checked():
    from datetime import date
    assert results_equal(["day", "count"], [(date(2025, 1, 1), 2)], ["day", "count"], [("2025-01-01", 2)])
    assert not results_equal(["count", "day"], [(date(2025, 1, 1), 2)], ["day", "count"], [("2025-01-01", 2)])


def test_dialogue_score_reports_slot_errors_and_context_contamination():
    gold = {"metric": "buyers", "filters": [], "breakdown": None}
    actual = {"metric": "revenue", "filters": [{"device": "mobile"}], "breakdown": None}
    score = dialogue_scores(gold, actual)
    assert not score["state_exact"]
    assert score["slot_correct"] == {"metric": False, "filters": False, "breakdown": True}
    assert score["contamination"] is True
    assert dialogue_scores({"filters": None}, {"filters": [{"device": "mobile"}]} )["contamination"]


def test_fixture_and_case_files_exist_with_sql_gold_independent_of_compiler():
    root = CASES_PATH.parents[2]
    fixture = (root / "data" / "benchmark" / "fixture.sql").read_text(encoding="utf-8")
    assert "analytics.event_activity" in fixture
    assert "event_benchmark" in fixture
    assert len(load_cases()) == 24
    assert all("gold_sql" in case for case in load_cases())
