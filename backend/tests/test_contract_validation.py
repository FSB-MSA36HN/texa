import pytest

from eval.benchmark import validate_business_contract
from eval.run_accuracy_study import load_suite


GOLD = ["event_date", "events"]
VALID = {"columns": [
    {"id": "date_dimension", "actual_alias": "day", "gold_alias": "event_date"},
    {"id": "event_count", "actual_alias": "n", "gold_alias": "events"},
]}


def test_optional_contract_and_full_gold_coverage():
    assert validate_business_contract(None, GOLD) is None
    assert validate_business_contract(VALID, GOLD) is None
    quoted = {"columns": [{"id": "semantic-id", "actual_alias": "day of week",
                            "gold_alias": "event_date"},
                           {"id": "event-count", "actual_alias": "total events",
                            "gold_alias": "events"}]}
    assert validate_business_contract(quoted, GOLD) is None


@pytest.mark.parametrize(("contract", "message"), [
    ("not-a-mapping", "must be a mapping"),
    ({}, "columns must be a list"),
    ({"columns": []}, "must not be empty"),
    ({"columns": ["event_date"]}, "must be a mapping"),
    ({"columns": [{"id": " ", "actual_alias": "x", "gold_alias": "event_date"}]}, "non-empty string"),
    ({"columns": [{"id": "x", "actual_alias": "x", "gold_alias": "event_date"}]}, "cover every gold"),
    ({"columns": [
        {"id": "x", "actual_alias": "x", "gold_alias": "event_date"},
        {"id": "x", "actual_alias": "y", "gold_alias": "events"},
    ]}, "ids must be unique"),
    ({"columns": [
        {"id": "x", "actual_alias": "x", "gold_alias": "event_date"},
        {"id": "y", "actual_alias": "x", "gold_alias": "events"},
    ]}, "actual_alias values must be unique"),
])
def test_invalid_contracts_fail_clearly(contract, message):
    with pytest.raises(ValueError, match=message):
        validate_business_contract(contract, GOLD, context="case-1")


def test_load_suite_preflights_only_selected_scored_turns(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "dataset_type: challenge_candidate\nstatus: candidate_agent_reviewed_not_sealed\n"
    )
    (tmp_path / "cases.yaml").write_text("""\
- id: selected
  split: dev
  expected_result: {columns: [events], rows: [[1]]}
  business_contract: "malformed"
- id: other-split
  split: test
  expected_result: {columns: [events], rows: [[1]]}
  business_contract: "malformed"
""")
    with pytest.raises(ValueError, match="selected:selected.*must be a mapping"):
        load_suite(tmp_path, "single", "dev", "base")


def test_load_suite_preflights_nested_scored_turns(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "dataset_type: challenge_candidate\nstatus: candidate_agent_reviewed_not_sealed\n"
    )
    (tmp_path / "dialogues.yaml").write_text("""\
- id: dialogue
  split: dev
  turns:
    - id: first
      action: clarify
    - id: second
      action: answer
      expected_result: {columns: [events], rows: [[1]]}
      business_contract: {columns: []}
""")
    with pytest.raises(ValueError, match="dialogue:second.*must not be empty"):
        load_suite(tmp_path, "conversation", "dev", "base")


def test_load_suite_accepts_missing_contract(tmp_path):
    (tmp_path / "manifest.yaml").write_text(
        "dataset_type: challenge_candidate\nstatus: candidate_agent_reviewed_not_sealed\n"
    )
    (tmp_path / "cases.yaml").write_text(
        "- id: selected\n  split: dev\n  expected_result: {columns: [events], rows: [[1]]}\n"
        "- id: unselected\n  split: test\n  expected_result: {columns: [events], rows: [[1]]}\n"
        "  business_contract: malformed\n"
    )
    _manifest, rows = load_suite(tmp_path, "single", "dev", "base")
    assert [row["id"] for row in rows] == ["selected"]
