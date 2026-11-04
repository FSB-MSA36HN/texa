"""Exercise failure accounting without providers or PostgreSQL."""
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "eval"))
    return importlib.import_module("run_benchmark")


def test_direct_dialogue_exception_is_a_failed_turn_and_does_not_abort(runner, monkeypatch):
    # Temporary output must remain in the project, as in the production runner.
    output = runner.ROOT / ".runtime" / "test-dialogue-exception.jsonl"
    output.parent.mkdir(exist_ok=True)
    output.unlink(missing_ok=True)
    monkeypatch.setattr(runner.llm, "generate_structured", lambda **kw: (_ for _ in ()).throw(ValueError("scripted failure")))
    monkeypatch.setattr(runner, "_call_usage", lambda _: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "model_ms": 0})
    dialogues = [{"id": "failed", "split": "dev", "turns": [
        {"question": "Q1", "action": "answer", "gold_sql": "SELECT 1"},
        {"question": "Q2", "action": "conversation"}]}]
    try:
        assert runner.run_direct_dialogues(SimpleNamespace(model="scripted", engine={}), "unused", dialogues, output) == 0
        import json
        records = [json.loads(line) for line in output.read_text().splitlines()]
        assert records[0]["dialogue_success"] is False
        assert len(records[0]["turns"]) == 2
        assert all(t["actual_action"] == "error" for t in records[0]["turns"])
    finally:
        output.unlink(missing_ok=True)


def test_direct_dialogue_empty_sql_cannot_pass_as_answer(runner, monkeypatch):
    output = runner.ROOT / ".runtime" / "test-dialogue-empty.jsonl"
    output.parent.mkdir(exist_ok=True)
    output.unlink(missing_ok=True)
    monkeypatch.setattr(runner.llm, "generate_structured", lambda **kw: {
        "action": "answer", "sql": "", "ask_fields": [], "reference_turns": [], "message": ""})
    monkeypatch.setattr(runner, "_call_usage", lambda _: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "model_ms": 0})
    dialogues = [{"id": "empty", "split": "dev", "turns": [{"question": "Q", "action": "answer", "gold_sql": "SELECT 1"}]}]
    try:
        runner.run_direct_dialogues(SimpleNamespace(model="scripted", engine={}), "unused", dialogues, output)
        import json
        record = json.loads(output.read_text().splitlines()[0])
        assert record["turns"][0]["result_correct"] is False
        assert record["dialogue_success"] is False
    finally:
        output.unlink(missing_ok=True)


def test_dialogue_gold_requires_independent_reference_rows(runner, monkeypatch):
    records = []
    monkeypatch.setattr(runner, 'write_result', lambda _, row: records.append(row))
    monkeypatch.setattr(runner, 'score_expected_result', lambda *a: {'status': 'ok', 'result_correct': True})
    dialogues = [{'id': 'missing', 'turns': [
        {'action': 'conversation'}, {'action': 'answer', 'gold_sql': 'SELECT 1'}]}]
    args = SimpleNamespace()
    assert runner.validate_dialogue_gold(args, 'unused', dialogues, Path('unused')) == 1
    assert records[-1]['answer_turns'] == 1
    assert records[-1]['actions_validated'] is False
    dialogues[0]['turns'][1]['expected_result'] = {'columns': ['value'], 'rows': [[1]]}
    assert runner.validate_dialogue_gold(args, 'unused', dialogues, Path('unused')) == 0


def test_dialogue_turn_output_keeps_safe_runtime_diagnostics(runner):
    turn = {
        "status": "error",
        "error": {"code": "INTERNAL", "message": "Could not resolve requested metric.", "retryable": True},
        "form": {"fields": [{"id": "time_range"}, {"id": "source"}]},
    }
    scored = runner._score_dialogue_turn({"action": "answer"}, turn, "answer", "unused")
    assert scored["system_status"] == "error"
    assert scored["system_error"] == turn["error"]
    assert scored["system_code"] == "INTERNAL"
    assert scored["system_message"] == "Could not resolve requested metric."
    assert scored["form_field_ids"] == ["source", "time_range"]
    assert "prompt" not in scored and "provider_response" not in scored


def test_dataset_directory_selects_manifest_as_well_as_cases(runner):
    args = SimpleNamespace(dataset_dir=str(runner.ROOT / 'data/benchmark/v2'))
    assert runner.dataset_path(args, 'manifest.yaml') == runner.ROOT / 'data/benchmark/v2/manifest.yaml'
    assert runner.dataset_path(SimpleNamespace(), 'cases.yaml') == runner.CASES_PATH


def test_dialogue_comparison_resamples_individual_dialogues(runner):
    import json
    paths = [runner.ROOT / '.runtime' / f'test-dialogue-paired-{side}.jsonl' for side in ('left', 'right')]
    try:
        for path, successes in zip(paths, [(False, True), (True, True)]):
            path.write_text('\n'.join(json.dumps({'type': 'dialogue', 'id': key, 'dialogue_success': success})
                                      for key, success in zip(('d1', 'd2'), successes)))
        result = runner.compare_results_files(*(str(path) for path in paths))
        assert result['strata'] == 2
        assert result['ci95_low'] < result['ci95_high']
    finally:
        for path in paths:
            path.unlink(missing_ok=True)
