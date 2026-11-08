"""The baseline ladder (B0, B0R, B0G, B0GR) and the research_v4 dataset wiring in the accuracy runner."""
import json
from pathlib import Path

import pytest

from eval.accuracy_study import SUITE_VARIANTS, VARIANTS
from eval.report_accuracy_study import V3_INPUT_POLICIES
from eval.run_accuracy_study import SCHEMA_GLOSSARY_SYSTEM, SCHEMA_ONLY_SYSTEM, load_suite, main

V4 = Path(__file__).resolve().parents[2] / "data" / "benchmark" / "research_v4"
needs_v4 = pytest.mark.skipif(not (V4 / "cases.yaml").is_file(), reason="research_v4 has not been generated")


def test_ladder_variants_are_single_question_only_and_have_distinct_policies():
    for variant in ("B0", "B0R", "B0G", "B0GR"):
        assert variant in VARIANTS and variant in SUITE_VARIANTS["single"]
        assert all(variant not in SUITE_VARIANTS[s] for s in ("clarification", "conversation", "diagnostic"))
    policies = [V3_INPUT_POLICIES[v] for v in ("B0", "B0R", "B0G", "B0GR")]
    assert len(set(policies)) == 4
    assert "catalog_definitions" in V3_INPUT_POLICIES["B0G"] and "one_sql_retry" in V3_INPUT_POLICIES["B0GR"]


def test_schema_only_system_prompt_stays_free_of_definitions_and_glossary_prompt_asks_to_follow_them():
    assert "business definitions" not in SCHEMA_ONLY_SYSTEM.lower()
    assert "follow them" in SCHEMA_GLOSSARY_SYSTEM and "sql" in SCHEMA_GLOSSARY_SYSTEM


@needs_v4
def test_v4_loads_in_runner_and_dry_runs_for_new_baselines(capsys):
    manifest, rows = load_suite(V4, "single", "test", "real")
    assert len(rows) == 200 and manifest["status"] == "agent_authored_unsealed_pending_human_review"
    for variant in ("B0G", "B0GR"):
        assert main(["--dataset-dir", str(V4), "--suite", "single", "--split", "test", "--world", "real",
                     "--variant", variant]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["scenarios"] == 200 and report["model_calls"] == 0 and report["confirmatory_eligible"] is False
