"""Test reporting and paired analysis from synthetic JSONL; no model or DB calls."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "backend/eval/report_ablation.py"
SPEC = importlib.util.spec_from_file_location("report_ablation", SCRIPT)
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)


def _write_run(path, variant, repeat, *, suite="memory", split="dev", success=(True, False), changed=False):
    ids = ["s1", "s2"]
    manifest = {"type": "run_manifest", "variant": variant, "suite": suite, "split": split,
                "repeat": repeat, "model": "model-v1", "expected_ids": ids,
                "provenance": {"dataset_hashes": {"suite": "abc"}, "catalog_hash": "c",
                    "prompt_hashes": {"main": "p"}, "source_digest": "db", "effective_model_config": {"temp": 0},
                    "commit": "abc123"}}
    rows = []
    for i, sid in enumerate(ids):
        is_ok = success[i]
        if changed and variant != "F" and i == 1:
            is_ok = True
        rows.append({"type": "scenario", "id": sid, "cluster_id": f"cluster-{i}",
            "group": "long" if i else "short", "success": is_ok, "result_correct": is_ok,
            "answer_count": 2, "answer_correct": 2 if is_ok else 1,
            "latency_ms": 100 + repeat, "usage": {"calls": 2, "input_tokens": 50, "output_tokens": 10},
            "clarification_rounds": int(sid == "s1"), "clarification_counts": {"tp": 1, "fp": 0, "fn": 0}})
    records = [manifest, *rows, {"type": "run_complete", "scenarios": len(rows)}]
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def test_paired_report_averages_repeats_and_bootstraps_scenarios(tmp_path):
    paths = [_write_run(tmp_path / f"{variant}-{repeat}.jsonl", variant, repeat,
                        success=(True, False if variant == "F" else True))
             for variant in ("F", "M6") for repeat in (1, 2)]
    report = reporter.build_report(paths, iterations=100)
    comparison = report["comparisons"][0]
    assert comparison["control_summary"]["repeats"] == 2
    assert comparison["control_summary"]["scenarios"] == 2
    assert comparison["control_summary"]["result_accuracy"] == pytest.approx(.75)
    assert comparison["variant_summary"]["result_accuracy"] == pytest.approx(1.0)
    assert comparison["delta_control_minus_variant_success"]["delta"] == pytest.approx(-.5)
    assert comparison["delta_control_minus_variant_success"]["clusters"] == 2
    assert comparison["variant_summary"]["clarification"]["precision"] == 1
    assert "N/A" in reporter.render_markdown(report) or "F vs M6" in reporter.render_markdown(report)


def test_refuses_incomplete_or_confounded_paired_files(tmp_path):
    f = _write_run(tmp_path / "f.jsonl", "F", 1)
    m = _write_run(tmp_path / "m.jsonl", "M6", 1)
    with pytest.raises(ValueError, match="provenance"):
        altered = json.loads(m.read_text().splitlines()[0])
        altered["provenance"]["source_digest"] = "other-db"
        m.write_text("\n".join([json.dumps(altered), *m.read_text().splitlines()[1:]]) + "\n")
        reporter.build_report([f, m])
    _write_run(m, "M6", 1)
    records = m.read_text().splitlines()[:-1]
    m.write_text("\n".join(records) + "\n")
    with pytest.raises(ValueError, match="run_complete"):
        reporter.build_report([f, m])


def test_repeat_sets_and_scenario_ids_must_match(tmp_path):
    f = _write_run(tmp_path / "f.jsonl", "F", 1)
    m = _write_run(tmp_path / "m.jsonl", "M6", 2)
    with pytest.raises(ValueError, match="repeat numbers"):
        reporter.build_report([f, m])


def test_zero_clarification_denominator_is_reported_as_not_applicable(tmp_path):
    path = _write_run(tmp_path / "f.jsonl", "F", 1, suite="clarification")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    for row in records[1:-1]:
        row["clarification_counts"] = {"tp": 0, "fp": 0, "fn": 0}
        row["clarification_rounds"] = 0
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    summary = reporter._summarize([reporter._read_run(path)], [1], ["s1", "s2"])
    assert summary["clarification"]["precision"] is None
    assert summary["clarification"]["recall"] is None


def test_validates_unpaired_groups_repeats_and_uses_lower_bound_for_failed_usage(tmp_path):
    f1 = _write_run(tmp_path / "f1.jsonl", "F", 1)
    f2 = _write_run(tmp_path / "f2.jsonl", "F", 2)
    records = [json.loads(line) for line in f2.read_text().splitlines()]
    records[1]["cluster_id"] = "different-cluster"
    records[1]["usage_complete"] = False
    f2.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    with pytest.raises(ValueError, match="cluster/group labels"):
        reporter.build_report([f1, f2])  # F-only report must validate repeat comparability too.
    records[1]["cluster_id"] = "cluster-0"
    f2.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    summary = reporter._summarize([reporter._read_run(f1), reporter._read_run(f2)], [1, 2], ["s1", "s2"])
    assert summary["usage_completeness"]["complete"] is False
    assert summary["usage_completeness"]["interpretation"].startswith("lower bound")


def test_rejects_answer_count_or_bad_usage_differences(tmp_path):
    f = _write_run(tmp_path / "f.jsonl", "F", 1)
    m = _write_run(tmp_path / "m.jsonl", "M6", 1)
    records = [json.loads(line) for line in m.read_text().splitlines()]
    records[1]["answer_count"] = 1
    m.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    with pytest.raises(ValueError, match="answer_count"):
        reporter.build_report([f, m])
    records[1]["answer_count"] = 2
    records[1]["usage"]["calls"] = -1
    m.write_text("\n".join(json.dumps(row) for row in records) + "\n")
    with pytest.raises(ValueError, match="non-negative"):
        reporter.build_report([f, m])


def test_component_activation_deduplicates_resumed_turn_traces(tmp_path):
    path = _write_run(tmp_path / 'f-trace.jsonl', 'F', 1)
    records = [json.loads(line) for line in path.read_text().splitlines()]
    records[1]['turns'] = [
        {'trace': {'id': 'same-turn', 'context': {'relation': 'followup'}, 'ablation': {'clarification_requested': True}}},
        {'trace': {'id': 'same-turn', 'context': {'relation': 'followup'},
            'ablation': {'clarification_requested': True, 'clarification_invoked': True, 'clarification_reason': 'selected'}}}]
    path.write_text('\n'.join(json.dumps(row) for row in records) + '\n')
    result = reporter.build_report([path])['summaries']['memory/dev/F']['component_activation']
    assert result['turn_observations'] == 1
    assert result['guess_invoked'] == 1
    assert result['guess_reasons'] == {'selected': 1}


def test_predeclared_unsupported_memory_task_invalidates_comparison_and_reports_coverage(tmp_path):
    f = _write_run(tmp_path / 'f.jsonl', 'F', 1)
    m = _write_run(tmp_path / 'm.jsonl', 'M6', 1)
    for path in (f, m):
        records = [json.loads(line) for line in path.read_text().splitlines()]
        row = next(row for row in records if row.get('id') == 's2')
        row.update(evaluation_status='contains_unsupported_task_kind', expected_answer_count=2,
                   unsupported_answer_count=1, answer_count=1, answer_correct=1)
        path.write_text('\n'.join(json.dumps(row) for row in records) + '\n')
    report = reporter.build_report([f, m], iterations=100)
    comp = report['comparisons'][0]
    assert comp['comparison_status'] == 'invalid_unsupported_task_kind'
    assert comp['unscored_scenarios'] == ['s2']
    assert comp['delta_control_minus_variant_success']['delta'] is None
    summary = comp['control_summary']
    assert summary['answer_coverage']['expected_sql_turns'] == 4
    assert summary['answer_coverage']['unsupported_discussion_turns'] == 1
    assert summary['result_accuracy_partial_coverage'] is True
    assert 'INVALID' in reporter.render_markdown(report)


def test_all_scenarios_unsupported_reports_coverage_without_stdev_crash(tmp_path):
    f = _write_run(tmp_path / 'f.jsonl', 'F', 1)
    m = _write_run(tmp_path / 'm.jsonl', 'M6', 1)
    for path in (f, m):
        records = [json.loads(line) for line in path.read_text().splitlines()]
        for row in records[1:-1]:
            row.update(evaluation_status='contains_unsupported_task_kind', expected_answer_count=1,
                       unsupported_answer_count=1, answer_count=0, answer_correct=0)
        path.write_text('\n'.join(json.dumps(row) for row in records) + '\n')
    report = reporter.build_report([f, m], iterations=10)
    summary = report['summaries']['memory/dev/F']
    assert summary['scenario_success_mean'] is None
    assert summary['repeat_success_sd'] is None
    assert summary['answer_coverage']['sql_gradable_turns'] == 0
