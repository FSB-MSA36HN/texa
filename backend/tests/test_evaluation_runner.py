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
