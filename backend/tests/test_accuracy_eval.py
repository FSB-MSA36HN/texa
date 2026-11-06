import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from eval.accuracy_study import (confirmatory_eligibility, score_scenario, sql_error_diagnostic,
                                validate_coverage)
from eval.report_accuracy_study import apply_annotation_erratum, compare, read_run, summarize
from eval.check_world_robustness import C19_CASES_SHA256, C19_ID
from eval.run_accuracy_study import (CHALLENGE_SCHEMA, RawHistorySession, _schema_only_question,
                                     _score_output_table, _rescore_texa_table_scores,
                                     _assert_study_inputs_frozen, diagnostic_score)


FROZEN_DATA = Path(__file__).resolve().parents[2] / 'data/benchmark/results/accuracy-dev-20261106-v2/frozen_dataset'


class AccuracyEvalTests(unittest.TestCase):
    @patch('eval.report_accuracy_study.CHALLENGE_DATA', FROZEN_DATA)
    def test_c19_erratum_is_hash_pinned_and_non_mutating(self):
        def run(variant, rows, cases_hash=C19_CASES_SHA256):
            return {"manifest": {"suite": "single", "split": "dev", "variant": variant,
                    "expected_ids": [row["id"] for row in rows], "provenance": {
                        "dataset_hashes": {"cases.yaml": cases_hash}}}, "rows": rows}

        correct = {"turns": [{"trace": {"status": "answered"}}], "id": C19_ID, "result_correct": True, "business_result_correct": False,
                   "answer_count": 1, "answer_correct": 0, "success": False}
        wrong = {"id": "c01_cosmetics_jan_events", "result_correct": False,
                 "business_result_correct": True, "answer_correct": 1, "success": True}
        raw_false = {"id": C19_ID, "result_correct": False, "business_result_correct": True,
                     "answer_count": 1, "answer_correct": 1, "success": True}
        nested = {"id": C19_ID, "answer_count": 2, "answer_correct": 0,
                  "business_result_correct": False, "success": False,
                  "turns": [{"result_correct": True, "business_result_correct": False},
                            {"result_correct": False, "business_result_correct": False}]}
        runs = [run("T00", [correct, wrong]), run("T01", [raw_false]), run("B1", [nested])]
        originals = json.loads(json.dumps(runs))
        overlays, metadata = apply_annotation_erratum(runs, "c19-prose-contract-v1")
        self.assertEqual(runs, originals)
        self.assertTrue(overlays[0]["rows"][0]["business_result_correct"])
        self.assertEqual(overlays[0]["rows"][0]["answer_correct"], 1)
        self.assertTrue(overlays[0]["rows"][0]["success"])
        self.assertFalse(overlays[1]["rows"][0]["business_result_correct"])
        self.assertEqual(overlays[1]["rows"][0]["answer_correct"], 0)
        self.assertFalse(overlays[1]["rows"][0]["success"])
        self.assertEqual(overlays[0]["rows"][1], wrong)
        self.assertEqual([turn["business_result_correct"] for turn in overlays[2]["rows"][0]["turns"]],
                         [True, False])
        self.assertEqual(overlays[2]["rows"][0]["answer_correct"], 1)
        self.assertFalse(overlays[2]["rows"][0]["business_result_correct"])
        self.assertEqual(metadata["cases_sha256"], C19_CASES_SHA256)
        self.assertEqual(len(metadata["corrections"]), 3)

    @patch('eval.report_accuracy_study.CHALLENGE_DATA', FROZEN_DATA)
    def test_c19_erratum_rejects_bad_hash_and_unknown_case_id(self):
        def run(row, cases_hash=C19_CASES_SHA256):
            return {"manifest": {"suite": "single", "variant": "T00", "provenance": {
                    "dataset_hashes": {"cases.yaml": cases_hash}}}, "rows": [row]}

        with tempfile.TemporaryDirectory() as root:
            Path(root, "cases.yaml").write_text("not-the-frozen-cases\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash does not match"):
                apply_annotation_erratum([run({"id": C19_ID})], "c19-prose-contract-v1",
                                         dataset_dir=Path(root))
        wrong_hash = "0" * 64
        with self.assertRaisesRegex(ValueError, "manifest cases.yaml hash mismatch"):
            apply_annotation_erratum([run({"id": C19_ID}, wrong_hash)], "c19-prose-contract-v1")
        with self.assertRaisesRegex(ValueError, "unknown case ID"):
            apply_annotation_erratum([run({"id": "not-a-frozen-case"})], "c19-prose-contract-v1")

    def test_variant_suite_coverage_is_exact(self):
        validate_coverage([{"id": "a"}], ["a"], variant="T11", suite="single")
        with self.assertRaises(ValueError):
            validate_coverage([{"id": "a"}], ["a"], variant="B0", suite="conversation")
        with self.assertRaises(ValueError):
            validate_coverage([{"id": "a"}], ["a", "b"], variant="T11", suite="single")

    def test_candidate_is_never_confirmatory(self):
        eligible, reason = confirmatory_eligibility({"dataset_type": "challenge_candidate",
            "status": "candidate_agent_reviewed_not_sealed", "review_status": "agent_reviewed"})
        self.assertFalse(eligible)
        self.assertNotEqual(reason, "eligible")

    def test_unsupported_turns_not_in_business_accuracy(self):
        result = score_scenario({"turns": [
            {"scorable": True, "business_result_correct": True},
            {"scorable": False, "business_result_correct": False},
        ]}, "conversation")
        self.assertEqual(result["answer_count"], 1)
        self.assertEqual(result["answer_correct"], 1)
        self.assertEqual(result["unsupported_turn_count"], 1)

    def test_sql_diagnostic_does_not_retain_error_text(self):
        self.assertEqual(sql_error_diagnostic("syntax error near SECRET_SQL"), "syntax_error")
        self.assertNotIn("SECRET_SQL", sql_error_diagnostic("syntax error near SECRET_SQL"))

    def test_report_rejects_incomplete_and_confirmatory_candidate(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "run.jsonl"
            path.write_text(json.dumps({"type": "run_manifest"}) + "\n")
            with self.assertRaises(ValueError):
                read_run(path)
        run = {"manifest": {"suite": "single", "split": "test", "variant": "B0",
                "expected_ids": ["x"], "provenance": {}, "dataset": {"dataset_type": "challenge_candidate"}},
                "rows": [{"id": "x", "answer_count": 1, "answer_correct": 1}]}
        with self.assertRaisesRegex(ValueError, "confirmatory report refused"):
            summarize([run], confirmatory=True)

    def test_v3_input_policy_is_pinned_to_variant_and_legacy_is_unchanged(self):
        from eval.report_accuracy_study import _validate_input_policy
        legacy = {"variant": "B0", "provenance": {}}
        _validate_input_policy(legacy)
        current = {"variant": "B0", "input_policy": "schema_only_direct_sql",
                   "provenance": {"evaluation_protocol": "v3_schema_only_full_table",
                                  "baseline_schema_hash": "a" * 64}}
        _validate_input_policy(current)
        for altered in (
            {**current, "input_policy": "texa_semantic_catalog_and_compiler"},
            {**current, "input_policy": None},
            {**current, "provenance": {"evaluation_protocol": "future_unknown"}},
            {**current, "provenance": {"evaluation_protocol": "v3_schema_only_full_table"}},
        ):
            with self.assertRaises(ValueError):
                _validate_input_policy(altered)

    def test_raw_history_uses_actual_rows_not_hidden_expected_result(self):
        manifest = {"sources": ["cosmetics_shop"], "metric_policy": "events count rows"}
        with patch("texa.llm.generate_structured", return_value={"action": "sql", "sql": "SELECT 1", "ask_fields": []}) as llm_call, \
             patch("eval.run_accuracy_study.execute_readonly", return_value=(("events",), ((5,),))):
            session = RawHistorySession("model", "dsn")
            got = session.ask("How many events?")
            self.assertEqual(got["rows"], [[5]])
            prompt = llm_call.call_args.kwargs["prompt"]
            self.assertNotIn("expected_result", prompt)
            self.assertNotIn("gold_sql", prompt)
            self.assertIn("Database schema:", prompt)
            self.assertNotIn("Metric definitions", prompt)
            self.assertNotIn("public business contract", prompt.lower())
            self.assertEqual(session.history[0]["result"]["rows"], ((5,),))

    def test_raw_history_sql_retry_gets_error_class_not_db_error_text(self):
        replies = [{"action": "sql", "sql": "SELECT BAD_SECRET", "ask_fields": []},
                   {"action": "sql", "sql": "SELECT 1", "ask_fields": []}]
        with patch("texa.llm.generate_structured", side_effect=replies) as llm_call, \
             patch("eval.run_accuracy_study.execute_readonly", side_effect=[RuntimeError("syntax error SECRET_VALUE"), (("x",), ((1,),))]):
            session = RawHistorySession("model", "dsn")
            got = session.ask("question")
            self.assertEqual(got["rows"], [[1]])
            retry_prompt = llm_call.call_args_list[1].kwargs["prompt"]
            self.assertIn("syntax_error", retry_prompt)
            self.assertNotIn("SECRET_VALUE", retry_prompt)

    def test_schema_only_baseline_receives_no_catalog_or_gold_contract(self):
        prompt = _schema_only_question({"question": "revenue last 7 days", "ui_scope": ["cosmetics_shop"],
                                      "expected_result": {"columns": ["revenue"], "rows": [[20]]},
                                      "business_contract": {"gold_alias": "revenue"}})
        self.assertIn(CHALLENGE_SCHEMA, prompt)
        self.assertIn("User-selected source IDs: cosmetics_shop", prompt)
        self.assertIn("revenue last 7 days", prompt)
        self.assertNotIn("Metric definitions", prompt)
        self.assertNotIn("gold_alias", prompt)
        self.assertNotIn("2025-01-01", prompt)
        for physical_column in ("event_ts TIMESTAMPTZ", "platform TEXT", "country TEXT",
                                "item_id TEXT", "item_price NUMERIC(14,2)", "quantity INTEGER",
                                "revenue_usd NUMERIC(14,2)", "up JSONB", "ingested_at TIMESTAMPTZ"):
            self.assertIn(physical_column, CHALLENGE_SCHEMA)

    def test_v3_score_ignores_aliases_but_requires_complete_ordered_projection(self):
        item = {"expected_result": {"columns": ["month", "revenue"],
                                    "rows": [["2025-01", 12], ["2025-02", None]]}}
        scored = _score_output_table(["bucket", "amount"], [["2025-02", None], ["2025-01", 12.0000001]], item)
        self.assertTrue(scored["result_correct"])
        self.assertFalse(scored["strict_result_correct"])
        self.assertFalse(scored["output_contract_compliant"])
        self.assertFalse(_score_output_table(["amount"], [[12]], item)["result_correct"])
        self.assertFalse(_score_output_table(["amount", "bucket"], [[12, "2025-01"], [None, "2025-02"]], item)["result_correct"])
        self.assertFalse(_score_output_table(["bucket", "amount"], [["2025-01", 12], ["2025-01", 12]], item)["result_correct"])

    def test_texa_replay_adapter_uses_same_alias_insensitive_full_table_score(self):
        observed = {"id": "turn-1", "columns": [{"name": "bucket"}, {"name": "amount"}]}
        class FakeSession:
            observed_turns = [observed]
            def output(self, turn):
                return ["bucket", "amount"], [["2025-01", 12]]
        item = {"expected_result": {"columns": ["month", "revenue"], "rows": [["2025-01", 12]]},
                "business_contract": {"columns": []}}
        record = {"turns": [{"index": 1, "trace": {"id": "turn-1"},
                              "result_correct": False, "business_result_correct": False}]}
        second = {"expected_result": {"columns": ["n"], "rows": [[3]]}, "gold_sql": "select 3"}
        got = _rescore_texa_table_scores(record, {"turns": [{**item, "gold_sql": "select 1"}, second]}, FakeSession(), "conversation")
        self.assertTrue(got["turns"][0]["result_correct"])
        self.assertFalse(got["turns"][0]["strict_result_correct"])
        self.assertEqual(got["answer_count"], 2)
        self.assertEqual(got["answer_correct"], 1)
        self.assertFalse(got["result_correct"])

    def test_compare_requires_all_worlds_and_pairs_complete_blocks(self):
        worlds = {"base": ["a"], "grain_counterexample": ["b"], "coverage_edge": ["c"]}
        runs = []
        for variant, correct in (("T00", 0), ("T11", 1)):
            for world, ids in worlds.items():
                rows = [{"id": sid, "cluster_id": sid, "success": bool(correct),
                         "answer_count": 1, "answer_correct": correct, "latency_ms": 10,
                         "usage": {"input_tokens": 2, "output_tokens": 1}}
                        for sid in ids]
                runs.append({"manifest": {"suite": "single", "split": "dev", "variant": variant,
                    "model": "m", "repeat": 1, "fixture_world": world, "fixture_hash": world + "-hash", "world_pool_ids": worlds,
                    "expected_ids": ids, "provenance": {"stable": "same", "feature_config": {"v": variant}}},
                    "rows": rows})
        result = compare(runs, iterations=20)
        self.assertEqual(result["variants"]["T11"]["answer_count"], 3)
        self.assertIn("T00_vs_T11", result["paired_comparisons"])
        runs[0]['manifest']['expected_answer_counts'] = {'a': 2}
        with self.assertRaisesRegex(ValueError, 'answer denominator'):
            compare(runs, iterations=20)
        del runs[0]['manifest']['expected_answer_counts']
        with self.assertRaisesRegex(ValueError, "missing fixture world"):
            compare(runs[:-1], iterations=20)
        runs[0]["manifest"]["confirmatory_requested"] = True
        runs[0]["manifest"]["dataset"] = {"dataset_type": "challenge_candidate",
            "status": "candidate_agent_reviewed_not_sealed"}
        with self.assertRaisesRegex(ValueError, "confirmatory comparison refused"):
            compare(runs, iterations=20)

    def test_compare_aggregates_component_traces_across_turns(self):
        worlds = {"base": ["a", "b", "c"]}
        traces = [
            {"retrieval": {"ids": []}, "consistency": {"scheduled": 1, "completed": 1}},
            {"retrieval": {"ids": ["example-1"]}, "consistency": {"scheduled": 3, "completed": 2}},
        ]
        run = {"manifest": {"suite": "single", "split": "dev", "variant": "T00",
                "model": "m", "repeat": 1, "fixture_world": "base", "fixture_hash": "base-hash",
                "world_pool_ids": worlds, "expected_ids": worlds["base"], "provenance": {}},
            "rows": [{"id": "a", "answer_count": 1, "answer_correct": 1,
                "texa_accuracy_traces": traces,
                # The old singular field must not override the plural traces.
                "texa_accuracy_trace": {"retrieval": {"ids": []}}},
                {"id": "b", "answer_count": 1, "answer_correct": 1,
                 # Legacy singleton is used only when plural is absent.
                 "texa_accuracy_trace": {"retrieval": {"ids": ["legacy"]},
                     "consistency": {"scheduled": 2, "completed": 1}}},
                {"id": "c", "answer_count": 1, "answer_correct": 1,
                 # An explicitly empty plural list takes precedence over singular.
                 "texa_accuracy_traces": [],
                 "texa_accuracy_trace": {"retrieval": {"ids": ["ignored"]}},
                 "retrieval_activated": True}]}
        result = compare([run], iterations=10)["variants"]["T00"]
        self.assertEqual(result["component_decision_count"], 3)
        self.assertEqual(result["retrieval_activated_scenarios"], 3)
        self.assertEqual(result["retrieval_activated_decisions"], 2)
        self.assertEqual(result["consistency_scheduled_samples"], 6)
        self.assertEqual(result["consistency_completed_samples"], 4)
        self.assertEqual(result["consistency_scheduled_decisions"], 2)
        self.assertEqual(result["consistency_completed_decisions"], 1)
        self.assertEqual(result["consistency_scheduled_scenarios"], 2)
        self.assertEqual(result["consistency_completed_scenarios"], 1)


if __name__ == "__main__":
    unittest.main()


def test_complex_diagnostic_rubric_requires_review_not_automatic_pass_or_failure():
    assert diagnostic_score({'expected_action': 'unsupported'}, 'refuse')['action_correct']
    assert diagnostic_score({'expected_action': 'refuse'}, 'refuse')['action_correct']
    assert not diagnostic_score({'expected_action': 'unsupported'}, 'sql')['action_correct']
    assert diagnostic_score({'expected_action': 'clarify_source_conflict'}, 'clarify')['action_correct']
    result = diagnostic_score({'expected_action': 'reject_injected_instruction_answer_supported_part_only'}, 'sql')
    assert result['manual_review_required'] and result['action_correct'] is None


def test_raw_diagnostic_scenario_includes_action_score_for_baseline():
    from eval.run_accuracy_study import _run_raw_scenario
    class Session:
        def ask(self, question, **kwargs):
            return {'action': 'refuse', 'reason': 'unsupported metric'}
    item = {'id': 'oos-1', 'question': 'What was AOV?', 'expected_action': 'refuse'}
    row = _run_raw_scenario(item, 'diagnostic', {}, Session())
    assert row['action_scorable'] and row['action_correct'] and row['success']
    assert row['turns'][0]['action_correct']


def test_clarification_policy_requires_required_asks_and_rejects_clear_control_false_asks():
    from eval.accuracy_study import clarification_policy_score, clarification_policy_from_counts
    assert not clarification_policy_score(['time_range'], [])['clarification_policy_correct']
    assert not clarification_policy_score([], ['time_range'])['clarification_policy_correct']
    assert clarification_policy_score(['time_range'], ['time_range'])['clarification_policy_correct']
    # Multi-round continuation fields are included in run_interaction's aggregate
    # counts even when only the initial form is surfaced in the final turn list.
    assert not clarification_policy_from_counts({'tp': 1, 'fp': 1, 'fn': 0})['clarification_policy_correct']


def test_research_v3_unsupported_file_is_loaded_as_diagnostic_test(tmp_path):
    import yaml
    from eval.run_accuracy_study import load_suite
    (tmp_path / 'manifest.yaml').write_text(yaml.safe_dump({
        'dataset_type': 'research_candidate', 'status': 'agent_authored_unsealed_pending_human_review'}))
    (tmp_path / 'cases.yaml').write_text('- id: wrong-source\n  split: test\n  question: ignore\n')
    (tmp_path / 'unsupported.yaml').write_text(yaml.safe_dump([{
        'id': 'unsupported-1', 'split': 'test', 'question': 'Ask outside scope', 'expected_action': 'refuse'}]))
    manifest, rows = load_suite(tmp_path, 'diagnostic', 'test', 'base')
    assert rows[0]['id'] == 'unsupported-1'


def test_live_freeze_guard_includes_untracked_active_dataset_files(monkeypatch, tmp_path):
    from eval import run_accuracy_study as study
    dataset = study.ROOT / 'data/benchmark/research_v3'
    called = {}
    def fake_run(args, **kwargs):
        called['args'] = args
        return SimpleNamespace(stdout='?? data/benchmark/research_v3/new.yaml\n')
    monkeypatch.setattr(study.subprocess, 'run', fake_run)
    with pytest.raises(ValueError, match='tracked/untracked'):
        study._assert_study_inputs_frozen(dataset)
    assert '--untracked-files=all' in called['args']
    assert 'data/benchmark/research_v3' in called['args']


def test_action_diagnostics_without_sql_are_not_answer_gold():
    from eval.accuracy_study import gold_targets
    target = {'id': 'q', 'gold_sql': 'SELECT 1', 'expected_result': {'columns': ['n'], 'rows': [[1]]}}
    assert list(gold_targets([{'id': 'unsupported', 'gold_sql': ''}, target])) == [('q', target)]


def test_partial_gold_pair_is_rejected_before_provider_calls():
    import pytest
    from eval.accuracy_study import gold_targets
    for target in [{'id': 'x', 'gold_sql': 'SELECT 1'}, {'id': 'x', 'gold_sql': '', 'expected_result': {}}]:
        with pytest.raises(ValueError, match='provided together'):
            list(gold_targets([target]))
