import unittest
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from eval.check_world_robustness import C19_CASES_SHA256, DATA, WORLDS, _apply_world, _candidate_sql, _effective_contract, _identity, _validate_provenance, check_worlds, _values_equal


def make_runs(cases):
    pools = {"base": [cid for cid in cases], "grain_counterexample": [], "coverage_edge": []}
    ids = pools["base"]
    hashes = {f"worlds/{world}.sql": hashlib.sha256((DATA / "worlds" / f"{world}.sql").read_bytes()).hexdigest()
              for world in WORLDS}
    hashes["cases.yaml"] = hashlib.sha256((DATA / "cases.yaml").read_bytes()).hexdigest()
    rows = [{"id": sid, "sql": "SELECT 1", "business_result_correct": True} for sid in ids]
    return [{"path": Path("base.jsonl"), "manifest": {"suite": "single", "split": "dev",
        "variant": "B0", "repeat": 1, "model": "model", "provenance": {"hash": "frozen", "dataset_hashes": hashes},
        "fixture_world": "base", "fixture_hash": hashes["worlds/base.sql"],
        "world_pool_ids": pools, "expected_ids": ids}, "rows": rows}]


class WorldRobustnessTests(unittest.TestCase):
    def setUp(self):
        self.cases = {"a": {"id": "a", "split": "dev", "fixture_world": "base",
                            "expected_results_by_world": {w: {"columns": ["n"], "rows": [[1 if w == "base" else 2]]}
                                                           for w in WORLDS}},
                      "b": {"id": "b", "split": "dev", "fixture_world": "grain_counterexample",
                            "expected_results_by_world": {w: {"columns": ["n"], "rows": [[1 if w == "base" else 2]]}
                                                           for w in WORLDS}},
                      "c": {"id": "c", "split": "dev", "fixture_world": "coverage_edge",
                            "expected_results_by_world": {w: {"columns": ["n"], "rows": [[1 if w == "base" else 2]]}
                                                           for w in WORLDS}}}
        self.runs = make_runs(self.cases)

    def test_incomplete_world_or_case_coverage_rejected(self):
        with self.assertRaisesRegex(ValueError, "world_pool_ids"):
            self.runs[0]["manifest"].pop("world_pool_ids")
            _validate_provenance(self.runs, self.cases)
        self.runs = make_runs(self.cases)
        self.runs[0]["manifest"]["expected_ids"] = []
        with self.assertRaisesRegex(ValueError, "frozen case pool"):
            _validate_provenance(self.runs, self.cases)

    def test_candidate_sql_selects_final_answer_only(self):
        self.assertEqual(_candidate_sql({"sql": "SELECT 1", "turns": [{"sql": "SELECT 2"}]}), ["SELECT 1"])
        self.assertEqual(_candidate_sql({"turns": [{"sql": "SELECT old"}, {"action": "refuse"}],
                                         "interpretation_traces": [{"compiled_sql": "SELECT stale"}]}), [])
        self.assertEqual(_candidate_sql({"turns": [{"sql": "SELECT old"},
            {"trace": {"compiled_sql": "SELECT final"}}]}), ["SELECT final"])
        self.assertEqual(_candidate_sql({"interpretation_traces": [{"compiled_sql": "SELECT 3"}]}), ["SELECT 3"])
        self.assertEqual(_candidate_sql({"turns": []}), [])

    def test_values_comparison_ignores_aliases_but_not_shape_or_order(self):
        self.assertTrue(_values_equal(["events"], [[18]], ["purchases"], [[18]]))
        self.assertFalse(_values_equal(["a", "b"], [[1, 2]], ["b", "a"], [[2, 1]]))
        self.assertFalse(_values_equal(["a"], [[1]], ["a", "b"], [[1, 2]]))

    def test_case_hash_and_erratum_guards(self):
        _validate_provenance(self.runs, self.cases)
        self.runs[0]["manifest"]["provenance"]["dataset_hashes"]["cases.yaml"] = "wrong"
        with self.assertRaisesRegex(ValueError, "cases.yaml hash"):
            _validate_provenance(self.runs, self.cases)
        case = {"business_contract": "Count the literal source event payment_made, not a payment method dimension."}
        digest = C19_CASES_SHA256
        self.assertIsNone(_effective_contract("c19_olist_payment_records", case,
            erratum="c19-prose-contract-v1", case_hash=digest))
        for cid, erratum, altered, bad_hash in [
            ("c19_olist_payment_records", None, case, digest),
            ("other", "c19-prose-contract-v1", case, digest),
            ("c19_olist_payment_records", "unknown", case, digest),
            ("c19_olist_payment_records", "c19-prose-contract-v1", {"business_contract": "mutated"}, digest),
            ("c19_olist_payment_records", "c19-prose-contract-v1", case, "bad"),
        ]:
            with self.assertRaisesRegex(ValueError, "malformed business_contract"):
                _effective_contract(cid, altered, erratum=erratum, case_hash=bad_hash)

    def test_v3_protocol_makes_full_table_values_primary_and_reports_alias_scores_separately(self):
        runs = make_runs(self.cases)
        runs[0]["manifest"]["provenance"]["evaluation_protocol"] = "v3_schema_only_full_table"
        def execute(dsn, sql):
            return ("alias_from_sql",), ((1,),)
        with patch("eval.check_world_robustness._identity"):
            result = check_worlds(runs, self.cases, "reader", apply_fixtures=True,
                                  owner_dsn="owner", apply_world=lambda *args: None, execute=execute)
        self.assertEqual(result["primary_metric"], "alias_insensitive_full_table_values")
        self.assertEqual(result["summary"]["base"]["correct"], 3)
        self.assertEqual(result["summary"]["base"]["business_contract_correct"], 0)
        self.assertFalse(any(row["strict_alias_result_correct"] for row in result["cases"]))
        self.assertEqual(result["all_world_case_counts"]["a"]["primary_correct_worlds"], 1)
        self.assertEqual(result["all_world_case_counts"]["a"]["strict_correct_worlds"], 0)
        self.assertEqual(result["all_world_case_counts"]["a"]["values_correct_worlds"], 1)

    def test_cross_world_protocol_mixing_is_rejected(self):
        changed = make_runs(self.cases)
        other = {**changed[0], "manifest": {**changed[0]["manifest"], "fixture_world": "grain_counterexample",
            "provenance": {**changed[0]["manifest"]["provenance"], "evaluation_protocol": "v3_schema_only_full_table"},
            "fixture_hash": changed[0]["manifest"]["provenance"]["dataset_hashes"]["worlds/grain_counterexample.sql"],
            "expected_ids": []}}
        changed[0]["manifest"]["world_pool_ids"] = {"base": ["a", "b", "c"],
            "grain_counterexample": [], "coverage_edge": []}
        changed[0]["manifest"]["expected_ids"] = ["a", "b", "c"]
        with self.assertRaisesRegex(ValueError, "frozen implementation/data provenance"):
            _validate_provenance([changed[0], other], self.cases)

    def test_cross_world_scoring_uses_candidate_sql_not_gold_sql(self):
        calls = []
        def execute(dsn, sql):
            calls.append(sql)
            return ("n",), ((1,),)  # candidate query is rerun unchanged on each world
        applied = []
        def apply(owner_dsn, path):
            applied.append(path.stem)
        with patch("eval.check_world_robustness._identity"):
            result = check_worlds(self.runs, self.cases, "reader", apply_fixtures=True,
                                  owner_dsn="owner", apply_world=apply, execute=execute)
        self.assertEqual(set(calls), {"SELECT 1"})
        self.assertEqual(len(calls), len(self.cases) * len(WORLDS))
        self.assertEqual(result["summary"]["base"]["correct"], 3)
        self.assertEqual(result["summary"]["grain_counterexample"]["correct"], 0)
        self.assertEqual(result["all_world_case_counts"]["a"]["primary_correct_worlds"], 1)
        self.assertEqual(result["all_world_case_counts"]["a"]["strict_correct_worlds"], 1)
        self.assertEqual(applied, ["base", "grain_counterexample", "coverage_edge", "base"])

    def test_replay_retains_product_public_output_boundary_for_ratio_samples(self):
        def execute(dsn, sql):
            return ('__sample_ratio', 'n'), ((15, 1),)
        with patch('eval.check_world_robustness._identity'):
            self.runs[0]['manifest']['variant'] = 'T00'
            product = check_worlds(self.runs, self.cases, 'reader', apply_fixtures=True,
                owner_dsn='owner', apply_world=lambda *args: None, execute=execute)
            self.runs[0]['manifest']['variant'] = 'B0'
            baseline = check_worlds(self.runs, self.cases, 'reader', apply_fixtures=True,
                owner_dsn='owner', apply_world=lambda *args: None, execute=execute)
        self.assertEqual(product['summary']['base']['correct'], 3)
        self.assertEqual(baseline['summary']['base']['correct'], 0)

    def test_fixture_apply_requires_owner_and_is_explicit(self):
        with patch("eval.check_world_robustness._identity") as identity:
            with self.assertRaisesRegex(ValueError, "requires --owner-dsn"):
                check_worlds(self.runs, self.cases, "reader", apply_fixtures=True)
            identity.assert_called_once_with("reader", require_owner=False)

    def test_database_and_port_guard(self):
        class Conn:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, query): return self
            def fetchone(self): return ("texa_benchmark", 5432, "reader", False)
        with patch("psycopg.connect", return_value=Conn()):
            with self.assertRaisesRegex(ValueError, "port 15433"):
                _identity("dsn", require_owner=False)

    def test_world_fixture_must_have_narrow_source_replacement(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "fixture.sql"
            path.write_text("DELETE FROM analytics.event_activity WHERE source_id='event_benchmark';")
            with patch("eval.check_world_robustness._identity"):
                with patch("psycopg.connect"):
                    with self.assertRaisesRegex(ValueError, "challenge sources"):
                        _apply_world("owner", path)


if __name__ == "__main__":
    unittest.main()
