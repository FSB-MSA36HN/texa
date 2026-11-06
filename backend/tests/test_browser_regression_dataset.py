import hashlib
import json
from decimal import Decimal
from pathlib import Path

import yaml

from eval.accuracy_study import gold_targets
from eval.run_accuracy_study import load_suite


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data/benchmark/browser_regression_v1"
ARTIFACT = ROOT / "data/benchmark/results/accuracy-browser-20261106/browser-check.json"


def _result(columns, rows):
    def value(cell):
        if isinstance(cell, (int, float)):
            return Decimal(str(cell))
        if isinstance(cell, str):
            try:
                return Decimal(cell)
            except Exception:
                return cell
        return cell
    return {"columns": columns, "rows": [[value(cell) for cell in row] for row in rows]}


def _assert_copied(target, source):
    assert target["question"] == source["question"]
    assert target["gold_sql"].strip() == source["reference_sql"].strip()
    assert _result(target["expected_result"]["columns"], target["expected_result"]["rows"]) == _result(
        source["expected_columns"], source["expected_rows"])
    for private_key in ("spec", "context", "source_resolution", "state", "query_spec"):
        assert private_key not in target


def test_browser_regression_provenance_and_exact_question_coverage():
    manifest = yaml.safe_load((DATASET / "manifest.yaml").read_text())
    raw = ARTIFACT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["provenance"]["source_sha256"]
    artifact = json.loads(raw)
    cases = yaml.safe_load((DATASET / "cases.yaml").read_text())
    dialogues = yaml.safe_load((DATASET / "dialogues.yaml").read_text())

    answer_cases = cases[:15]
    assert len(answer_cases) == 15
    for index, case in enumerate(answer_cases):
        _assert_copied(case, artifact["records"][index])

    long_dialogue, filter_dialogue = dialogues
    assert len(long_dialogue["turns"]) == 17
    assert long_dialogue["provenance_records"] == list(range(17))
    for turn_index, turn in enumerate(long_dialogue["turns"]):
        source = artifact["records"][turn_index]
        if source["status"] == "conversation":
            assert turn["question"] == source["question"]
            assert turn["action"] == "social"
            assert "gold_sql" not in turn and "expected_result" not in turn
        else:
            _assert_copied(turn, source)

    assert len(filter_dialogue["turns"]) == 3
    assert filter_dialogue["provenance_records"] == [20, 21, 22]
    for turn, source_index in zip(filter_dialogue["turns"], [20, 21, 22]):
        _assert_copied(turn, artifact["records"][source_index])

    diagnostics = cases[15:]
    assert [item["expected_action"] for item in diagnostics] == ["unsupported", "clarify_source_conflict"]
    assert diagnostics[0]["question"] == artifact["records"][19]["question"]
    assert diagnostics[1]["question"] == artifact["records"][17]["question"]
    assert diagnostics[1]["ui_scope"] == artifact["records"][17]["source_resolution"]["ui"]
    assert diagnostics[1]["source_id"] == artifact["records"][17]["spec"]["source_ids"][0]

    for suite, split in (("single", "dev"), ("diagnostic", "diagnostic"), ("conversation", "dev")):
        _, loaded = load_suite(DATASET, suite, split, "base")
        assert loaded
    assert len(list(gold_targets(answer_cases))) == 15
    assert len(list(gold_targets([long_dialogue]))) == 16
