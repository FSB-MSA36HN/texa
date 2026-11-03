"""Integrity checks for the paired, synthetic component-ablation suite."""
import importlib
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/benchmark/ablation_v1"


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "backend/eval"))
    return importlib.import_module("validate_dataset")


def test_ablation_suite_has_balanced_memory_scenarios_and_frozen_hashes(validator):
    expected = json.loads((DATA / "validation.json").read_text())
    assert validator.validate_ablation_dataset(DATA) == expected
    assert expected["dialogues"] == 24
    assert expected["dialogue_splits"] == {"dev": 12, "test": 12}
    assert set(expected["phenomena"].values()) == {4}
    assert expected["interactions"] == 40
    assert expected["ambiguous"] == expected["controls"] == 20


def test_memory_suite_covers_long_references_ambiguity_and_fresh_queries():
    dialogues = yaml.safe_load((DATA / "dialogues.yaml").read_text())
    long = [d for d in dialogues if d["phenomenon"] == "long_reference"]
    assert sorted(len(d["turns"]) for d in long) == [8, 10, 12, 12]
    assert max(d["dependency_distance"] for d in long) >= 9
    assert all(any(t.get("referenced_turn") == 1 for t in d["turns"]) for d in long)
    ambiguous = [d for d in dialogues if any(t.get("action") == "clarify" for t in d["turns"])]
    assert len(ambiguous) == 2
    assert all(any(t.get("action") == "clarify" and "context:reference" in t.get("ask_fields", [])
                   for t in d["turns"]) for d in ambiguous)
    assert any(d["phenomenon"] == "ambiguity_and_independence" and
               d["turns"][-1].get("referenced_turn") is None for d in dialogues)
    assert all("expected_result" in turn for d in dialogues for turn in d["turns"]
               if turn["action"] in {"answer", "clarification_answer"})


def test_memory_scenarios_do_not_duplicate_turns_or_full_content_across_splits():
    dialogues = yaml.safe_load((DATA / "dialogues.yaml").read_text())
    turns_by_question = {}
    signatures_by_split = {}
    state_signatures_by_split = {}
    for dialogue in dialogues:
        signature = json.dumps([{key: turn.get(key) for key in
            ("question", "action", "state", "gold_sql", "expected_result", "referenced_turn", "oracle_reference_turn")}
            for turn in dialogue["turns"]], sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
        signatures_by_split.setdefault(signature, set()).add(dialogue["split"])
        state_signature = json.dumps([{key: turn.get(key) for key in
            ("action", "state", "gold_sql", "expected_result", "referenced_turn", "oracle_reference_turn")}
            for turn in dialogue["turns"]], sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
        state_signatures_by_split.setdefault(state_signature, set()).add(dialogue["split"])
        for turn in dialogue["turns"]:
            question = " ".join(turn["question"].lower().split())
            turns_by_question.setdefault(question, set()).add(dialogue["split"])
    assert all(len(splits) == 1 for splits in turns_by_question.values())
    assert all(len(splits) == 1 for splits in signatures_by_split.values())
    assert all(len(splits) == 1 for splits in state_signatures_by_split.values())


def test_period_ambiguities_change_results_and_controls_retain_same_intent():
    spec = importlib.util.spec_from_file_location("ablation_v1_generator", DATA / "generate.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    interactions = yaml.safe_load((DATA / "interactions.yaml").read_text())
    by_id = {item["id"]: item for item in interactions}
    periods = [item for item in interactions if item.get("phenomenon") == "missing_period"]
    assert len(periods) == 16
    for item in periods:
        state = item["state"]
        other_period = "last_7" if state["time_range"] == "all" else "all"
        other = generator.v2.evaluate(generator.rows_for_v1(),
            generator.where_for(state["metric"], other_period))
        assert other != item["expected_result"], item["id"]
        matches = [control for control in interactions if control.get("control_of") == item["id"]]
        assert len(matches) == 1
        assert matches[0]["ask_fields"] == []
        assert matches[0]["expected_result"] == item["expected_result"]
        assert matches[0]["split"] == item["split"]


def test_regeneration_is_deterministic_and_fixture_period_is_fifty_days():
    spec = importlib.util.spec_from_file_location("ablation_v1_generator", DATA / "generate.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    rows = generator.rows_for_v1()
    dates = sorted({row["event_date"] for row in rows})
    assert len(rows) == 96
    assert dates[0] == "2024-12-15"
    assert dates[-1] == "2025-02-02"
    assert generator.rows_for_v1() == rows
    fixture = (DATA / "fixture.sql").read_text()
    assert "Synthetic product events ablation v1" in fixture
    assert "DELETE FROM analytics.event_activity WHERE source_id='event_benchmark'" in fixture


def test_database_preflight_projection_is_canonical_and_matches_manifest():
    manifest = yaml.safe_load((DATA / "manifest.yaml").read_text())
    projection_path = DATA / "fixture_rows.json"
    raw = projection_path.read_bytes()
    expected = json.loads(raw)
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert raw == canonical
    assert hashlib.sha256(raw).hexdigest() == manifest["source_digest"]
    assert expected == sorted(expected, key=lambda row: row["event_id"])
    assert all(row["item_category"] == row["ep"]["product"]["category"] for row in expected)
    assert all("device_type" not in row and "campaign_channel" not in row for row in expected)
    assert any(row["ep"].get("device", {}).get("type") is None for row in expected)
