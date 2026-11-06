from __future__ import annotations

import hashlib
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/benchmark/challenge_v1"
CONTROL = ROOT / "data/benchmark/source_scope_control_v1"


def _read_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_source_scope_control_changes_only_explicit_dev_single_input():
    original = _read_yaml(SOURCE / "cases.yaml")
    control = _read_yaml(CONTROL / "cases.yaml")
    assert len(original) == len(control)

    dev_answerable = 0
    for base, scoped in zip(original, control, strict=True):
        expected = dict(base)
        selected_scope = scoped.pop("ui_scope", None)
        assert scoped == expected  # questions, gold SQL/results, and all labels are unchanged
        if base.get("split") == "dev" and "question" in base and "source_id" in base:
            dev_answerable += 1
            assert selected_scope == [base["source_id"]]
        else:
            assert selected_scope is None
    assert dev_answerable == 30

    manifest = _read_yaml(CONTROL / "manifest.yaml")
    protocol = manifest["derived_control"]
    assert manifest["dataset_type"] == "challenge_candidate"
    assert manifest["status"] == "candidate_agent_reviewed_not_sealed"
    assert protocol["holdout_status"] == "exposed_regression_control_not_holdout"
    assert protocol["shared_input_policy"]

    # All copied execution/provenance inputs stay byte-identical to challenge_v1.
    unchanged = ["interactions.yaml", "dialogues.yaml", "worlds/base.sql",
                 "worlds/grain_counterexample.sql", "worlds/coverage_edge.sql"]
    for relative in unchanged:
        source_bytes = (SOURCE / relative).read_bytes()
        control_bytes = (CONTROL / relative).read_bytes()
        assert control_bytes == source_bytes, relative
        assert hashlib.sha256(source_bytes).hexdigest() == protocol["source_provenance_sha256"][relative]
    assert hashlib.sha256((SOURCE / "manifest.yaml").read_bytes()).hexdigest() == protocol["source_provenance_sha256"]["manifest.yaml"]
    assert hashlib.sha256((SOURCE / "cases.yaml").read_bytes()).hexdigest() == protocol["source_provenance_sha256"]["cases.yaml"]
