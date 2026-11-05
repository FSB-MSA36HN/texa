import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from eval.accuracy_study import (confirmatory_eligibility, score_scenario, sql_error_diagnostic,
                                validate_coverage)
from eval.report_accuracy_study import compare, read_run, summarize
from eval.run_accuracy_study import RawHistorySession, _question


class AccuracyEvalTests(unittest.TestCase):
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

    def test_raw_history_uses_actual_rows_not_hidden_expected_result(self):
        manifest = {"sources": ["cosmetics_shop"], "metric_policy": "events count rows"}
        with patch("texa.llm.generate_structured", return_value={"action": "sql", "sql": "SELECT 1", "ask_fields": []}) as llm_call, \
             patch("eval.run_accuracy_study.execute_readonly", return_value=(("events",), ((5,),))):
            session = RawHistorySession("model", "dsn")
            got = session.ask("How many events?", manifest)
            self.assertEqual(got["rows"], [[5]])
            prompt = llm_call.call_args.kwargs["prompt"]
            self.assertNotIn("expected_result", prompt)
            self.assertNotIn("gold_sql", prompt)
            self.assertEqual(session.history[0]["result"]["rows"], ((5,),))

    def test_raw_history_sql_retry_gets_error_class_not_db_error_text(self):
        replies = [{"action": "sql", "sql": "SELECT BAD_SECRET", "ask_fields": []},
                   {"action": "sql", "sql": "SELECT 1", "ask_fields": []}]
        with patch("texa.llm.generate_structured", side_effect=replies) as llm_call, \
             patch("eval.run_accuracy_study.execute_readonly", side_effect=[RuntimeError("syntax error SECRET_VALUE"), (("x",), ((1,),))]):
            session = RawHistorySession("model", "dsn")
            got = session.ask("question", {"sources": [], "metric_policy": ""})
            self.assertEqual(got["rows"], [[1]])
            retry_prompt = llm_call.call_args_list[1].kwargs["prompt"]
            self.assertIn("syntax_error", retry_prompt)
            self.assertNotIn("SECRET_VALUE", retry_prompt)

    def test_sql_baseline_gets_public_catalog_and_relative_date_anchor(self):
        prompt = _question({"question": "last 7 days", "ui_scope": ["cosmetics_shop"],
                           "expected_result": {"columns": ["revenue"], "rows": [[20]]}},
                           {"sources": ["cosmetics_shop"], "metric_policy": "public metrics"},
                           "cosmetics_shop 2025-01-01..2025-01-31")
        self.assertIn("max_date", prompt)
        self.assertIn("2025-01-01..2025-01-31", prompt)
        self.assertIn("Explicit user-selected source scope: cosmetics_shop", prompt)
        self.assertIn("Required output column aliases: revenue", prompt)
        self.assertNotIn("rows\": [[20]]", prompt)

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
        with self.assertRaisesRegex(ValueError, "missing fixture world"):
            compare(runs[:-1], iterations=20)
        runs[0]["manifest"]["confirmatory_requested"] = True
        runs[0]["manifest"]["dataset"] = {"dataset_type": "challenge_candidate",
            "status": "candidate_agent_reviewed_not_sealed"}
        with self.assertRaisesRegex(ValueError, "confirmatory comparison refused"):
            compare(runs, iterations=20)


if __name__ == "__main__":
    unittest.main()


def test_complex_diagnostic_rubric_requires_review_not_automatic_pass_or_failure():
    from eval.run_accuracy_study import diagnostic_score
    assert diagnostic_score({'expected_action': 'unsupported'}, 'refuse')['action_correct']
    assert not diagnostic_score({'expected_action': 'unsupported'}, 'sql')['action_correct']
    assert diagnostic_score({'expected_action': 'clarify_source_conflict'}, 'clarify')['action_correct']
    result = diagnostic_score({'expected_action': 'reject_injected_instruction_answer_supported_part_only'}, 'sql')
    assert result['manual_review_required'] and result['action_correct'] is None
