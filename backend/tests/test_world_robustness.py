import unittest
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch

from eval.check_world_robustness import DATA, WORLDS, _apply_world, _candidate_sql, _identity, _validate_provenance, check_worlds


def make_runs(cases):
    pools = {"base": [cid for cid in cases], "grain_counterexample": [], "coverage_edge": []}
    ids = pools["base"]
    hashes = {f"worlds/{world}.sql": hashlib.sha256((DATA / "worlds" / f"{world}.sql").read_bytes()).hexdigest()
              for world in WORLDS}
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

    def test_candidate_sql_extraction_and_missing_sql(self):
        self.assertEqual(_candidate_sql({"sql": "SELECT 1", "turns": [{"sql": "SELECT 2"}]}),
                         ["SELECT 1", "SELECT 2"])
        self.assertEqual(_candidate_sql({"turns": [{"trace": {"compiled_sql": "SELECT 3"}}]}), ["SELECT 3"])
        self.assertEqual(_candidate_sql({"turns": []}), [])

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
        self.assertEqual(applied, ["base", "grain_counterexample", "coverage_edge", "base"])

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
