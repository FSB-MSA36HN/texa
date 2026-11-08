import csv

import pytest

from eval.audit_stats import cohen_kappa, load, summarize, wilson


def test_kappa_matches_hand_computation():
    # 10 cases; observed agreement 0.8; marginals give expected agreement 0.5 -> kappa 0.6
    a = ["correct"] * 5 + ["wrong"] * 5
    b = ["correct"] * 4 + ["wrong"] + ["wrong"] * 4 + ["correct"]
    assert cohen_kappa(a, b) == pytest.approx(0.6)


def test_kappa_is_undefined_when_both_use_one_label():
    assert cohen_kappa(["correct"] * 4, ["correct"] * 4) is None


def test_wilson_interval_known_values():
    low, high = wilson(0, 60)
    assert low == 0.0 and high == pytest.approx(0.0600, abs=1e-3)       # zero flagged in 60 still allows ~6%
    low, high = wilson(30, 60)
    assert (low, high) == pytest.approx((0.3774, 0.6226), abs=1e-3)


def test_summary_flags_any_non_correct_and_lists_disagreements():
    first = {"x1": "correct", "x2": "ambiguous", "x3": "wrong", "x4": "correct"}
    second = {"x1": "correct", "x2": "correct", "x3": "wrong", "x4": "correct"}
    result = summarize(first, second)
    assert result["percent_agreement"] == 0.75
    assert result["flagged_by_either"] == 2 and result["wrong_by_both"] == 1
    assert result["disagreements_to_adjudicate"] == ["x2"]


def test_incomplete_sheet_is_refused(tmp_path):
    path = tmp_path / "sheet.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "verdict"])
        writer.writeheader(); writer.writerow({"id": "a", "verdict": "correct"}); writer.writerow({"id": "b", "verdict": ""})
    with pytest.raises(ValueError):
        load(path)
