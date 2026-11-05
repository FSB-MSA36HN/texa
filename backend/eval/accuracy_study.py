"""Provider-free validation helpers for the accuracy benchmark.

The executable candidate bank is deliberately diagnostic: agent review is not
human sealing.  This module keeps that distinction explicit and provides the
shared coverage/scoring gates used by the runner and report.
"""
from __future__ import annotations

from typing import Any

VARIANTS = ("B0", "B0R", "B1", "T00", "T10", "T01", "T11")


def expected_answer_count(item: dict[str, Any]) -> int:
    """Count authored answer slots even when execution fails before any turn returns."""
    return sum("expected_result" in target for target in item.get("turns", [item]))


def gold_targets(rows: list[dict[str, Any]]):
    """Action diagnostics may declare no SQL; scored answers require a gold pair."""
    for scenario in rows:
        for target in scenario.get('turns', [scenario]):
            sql = target.get('gold_sql')
            if not sql and 'expected_result' not in target:
                continue
            if not isinstance(sql, str) or not sql.strip() or 'expected_result' not in target:
                raise ValueError(f"{scenario['id']}: gold SQL and expected_result must be provided together")
            yield scenario['id'], target
SUITE_VARIANTS = {
    "single": set(VARIANTS),
    "clarification": {"B1", "T00", "T10", "T01", "T11"},
    "conversation": {"B1", "T00", "T10", "T01", "T11"},
    "diagnostic": {"B1", "T00", "T10", "T01", "T11"},
}


def validate_coverage(rows: list[dict[str, Any]], expected_ids: list[str], *,
                      variant: str, suite: str) -> None:
    """Require exact scenario coverage and reject variant/suite substitutions."""
    if variant not in SUITE_VARIANTS.get(suite, set()):
        raise ValueError(f"variant {variant!r} is not valid for suite {suite!r}")
    if not isinstance(expected_ids, list) or not expected_ids or len(expected_ids) != len(set(expected_ids)):
        raise ValueError("expected_ids must be a non-empty unique list")
    ids = [str(row.get("id", "")) for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(map(str, expected_ids)):
        raise ValueError("scenario IDs do not exactly match expected_ids")


def confirmatory_eligibility(manifest: dict[str, Any]) -> tuple[bool, str]:
    """Only sealed artifacts with actual human review qualify for inference."""
    if manifest.get("status") != "sealed":
        return False, "dataset_not_sealed"
    if manifest.get("dataset_type") != "challenge" or manifest.get("review_status") != "human_reviewed_sealed":
        return False, "human_review_and_sealed_artifact_required"
    reviewers = manifest.get("human_reviewers")
    if not isinstance(reviewers, list) or len(set(reviewers)) < 2:
        return False, "two_distinct_human_reviewers_required"
    return True, "eligible"


def score_scenario(record: dict[str, Any], suite: str) -> dict[str, Any]:
    """Return business-answer score; unsupported turns remain diagnostics."""
    turns = record.get("turns") or []
    if suite == "single":
        answers = [record] if record.get("scorable", True) else []
    else:
        answers = [turn for turn in turns if turn.get("scorable", "business_result_correct" in turn)]
    unsupported = sum(not turn.get("scorable", "business_result_correct" in turn) for turn in turns)
    correct = sum(bool(row.get("business_result_correct")) for row in answers)
    return {"answer_count": len(answers), "answer_correct": correct,
            "business_result_correct": (correct == len(answers)) if answers else None,
            "unsupported_turn_count": unsupported}


def sql_error_diagnostic(error: Any) -> str:
    """Keep only safe structural SQL error categories, never SQL/text/parameters."""
    text = str(error).lower()
    if any(word in text for word in ("syntax", "parse", "invalid input syntax")):
        return "syntax_error"
    if any(word in text for word in ("column", "relation", "table", "does not exist")):
        return "schema_error"
    if any(word in text for word in ("timeout", "canceling statement")):
        return "execution_timeout"
    return "execution_error"
