from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "benchmark" / "multisource_v1"


def test_multisource_diagnostic_integrity():
    cases = yaml.safe_load((DATA / "cases.yaml").read_text())
    dialogues = yaml.safe_load((DATA / "dialogues.yaml").read_text())
    manifest = yaml.safe_load((DATA / "manifest.yaml").read_text())
    assert 24 <= len(cases) <= 32
    assert len(dialogues) <= 6
    assert all(case["split"] == "dev" for case in cases)
    assert "test" not in {case["split"] for case in cases}
    assert manifest["case_counts"]["test"] == 0
    assert manifest["case_counts"]["single_turn_total"] == len(cases)
    assert all(case["expected_result"]["columns"] for case in cases)
    assert all(case["gold_sql"] and "source_id='" in case["gold_sql"] for case in cases)
    assert all("payment_made" not in case["gold_sql"] for case in cases if "revenue" in case["gold_sql"])
    assert "synthetic" in manifest["schema"].lower()
    assert "not real warehouses" in manifest["schema"]
    assert "no held-out/test split" in manifest["interaction_policy"]
    assert len({case["id"] for case in cases} | {dialogue["id"] for dialogue in dialogues}) == len(cases) + len(dialogues)
    fixture = (DATA / "fixture.sql").read_text()
    assert "current_database() <> 'texa_benchmark'" in fixture
    assert "refusing existing cosmetics/olist rows" in fixture
    assert "DELETE FROM" not in fixture.upper()
    assert "INSERT INTO analytics.source_registry" in fixture
    assert "INSERT INTO analytics.vocabulary" in fixture
    assert "msv1_" in fixture


def test_dialogue_diagnostics_cover_boundaries():
    dialogues = yaml.safe_load((DATA / "dialogues.yaml").read_text())
    actions = {turn["action"] for dialogue in dialogues for turn in dialogue["turns"]}
    questions = " ".join(turn["question"].lower() for dialogue in dialogues for turn in dialogue["turns"])
    assert {"clarify", "clarification_answer", "refuse", "answer"} <= actions
    assert "compare revenue" in questions
    assert "sessions" in questions and "array" in questions and "payment value" in questions
    assert "olist_marketplace" in questions and "cosmetics_shop" in questions
