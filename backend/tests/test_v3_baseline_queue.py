from pathlib import Path
import subprocess

from eval.run_v3_baseline_queue import (DATA, REPEATS, ROOT, SNAPSHOT_COMMIT, VARIANTS,
                                        case_ids, snapshot_inputs)


def test_v3_queue_selects_exact_historical_single_test_cases():
    ids = case_ids()
    assert len(ids) == 200
    assert len(set(ids)) == 200
    assert all("test" in case_id for case_id in ids)
    assert VARIANTS == ("B0R", "B0G", "B0GR")
    assert REPEATS == (1, 2)


def test_snapshot_uses_committed_old_catalog_and_example_bank(tmp_path):
    catalog, examples = snapshot_inputs(tmp_path)
    expected_catalog = subprocess.check_output(
        ["git", "show", f"{SNAPSHOT_COMMIT}:catalog/product_events.yaml"], cwd=ROOT
    )
    expected_examples = subprocess.check_output(
        ["git", "show", f"{SNAPSHOT_COMMIT}:catalog/verified_examples.yaml"], cwd=ROOT
    )
    assert catalog.read_bytes() == expected_catalog
    assert examples.read_bytes() == expected_examples
