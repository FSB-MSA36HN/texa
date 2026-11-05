"""Provider-free structural and fairness checks for challenge_v1 design artifacts."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DESIGN_PATH = ROOT / "data/benchmark/challenge_v1/design.yaml"
CATALOG_PATH = ROOT / "catalog/product_events.yaml"
BLUEPRINT_PATH = ROOT / "data/benchmark/challenge_v1/scenario_blueprints.yaml"
SUITES = {"single", "clarification", "conversation"}
BLUEPRINT_SUITES = SUITES | {"unsupported_or_adversarial"}
BASELINE_SUITES = {
    "B0": {"single"}, "B0R": {"single"},
    "B1": SUITES, "T00": SUITES, "T10": SUITES, "T01": SUITES, "T11": SUITES,
}


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def validate_design(design: dict[str, Any], catalog: dict[str, Any], blueprints: Any = None,
                    require_ready: bool = False) -> list[str]:
    errors: list[str] = []
    scope = design.get("scope", {})
    catalog_sources = set(catalog.get("allowed_sources", []))
    catalog_metrics = {entry.get("id") for entry in catalog.get("metrics", [])}
    if design.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if scope.get("engine") != "PostgreSQL" or set(scope.get("languages", [])) != {"vi", "en"}:
        errors.append("challenge engine/languages must remain PostgreSQL and vi/en")
    if set(scope.get("sources", [])) != catalog_sources:
        errors.append("scope.sources must exactly match catalog allowed_sources")
    if len(scope.get("metrics", [])) != 8 or len(set(scope.get("metrics", []))) != 8 or not set(scope.get("metrics", [])) <= catalog_metrics:
        errors.append("scope.metrics must be eight unique metrics declared in the current catalog")
    declared_paths = {item.get("field") for item in catalog.get("dimensions", []) if item.get("field", "").startswith("ep.")}
    if set(scope.get("nested_paths", [])) != declared_paths:
        errors.append("scope.nested_paths must exactly match catalog-declared nested scalar paths")
    if scope.get("max_sources_per_query") != 1 or scope.get("max_metrics_per_query") != 1:
        errors.append("challenge scope must remain single-source and single-metric")

    strata = design.get("single_strata", {})
    invalid_targets = False
    if set(strata) != {"core_control", "semantic_data_shape", "composed_in_scope"}:
        errors.append("single_strata must contain all three registered strata")
        invalid_targets = True
    for label, target in {**strata, **design.get("interactive_targets", {})}.items():
        if (not isinstance(target, dict) or any(type(target.get(split)) is not int or target[split] <= 0
                                                for split in ("dev", "test"))):
            errors.append(f"{label}: dev/test targets must be positive integers")
            invalid_targets = True
    if invalid_targets:
        return errors
    tests = {key: value.get("test", 0) for key, value in strata.items() if isinstance(value, dict)}
    planned = sum(tests.values())
    source_quotas = design.get("source_test_quota", {})
    for source, quota in source_quotas.items():
        if source not in catalog_sources:
            errors.append(f"source_test_quota contains out-of-scope source: {source}")
    if sum(q.get("single_min", 0) for q in source_quotas.values()) > planned:
        errors.append("source single_min quotas exceed planned single test cases")
    if sum(q.get("single_min", 0) for q in design.get("language_test_quota", {}).values()) > planned:
        errors.append("language single_min quotas exceed planned single test cases")
    for suite in ("clarification", "conversation"):
        target = design.get("interactive_targets", {}).get(suite, {}).get("test", 0)
        if sum(q.get(f"{suite}_min", 0) for q in source_quotas.values()) > target:
            errors.append(f"source {suite}_min quotas exceed planned {suite} test target")

    weights = design.get("metrics", {}).get("stratum_weights", {})
    if set(weights) != set(tests) or any(not isinstance(v, (int, float)) or v < 0 for v in weights.values()) or abs(sum(weights.values()) - 1) > 1e-9:
        errors.append("fixed stratum weights must be nonnegative, cover all single strata, and sum to 1")
    if planned and set(tests) == set(weights):
        observed = {key: value / planned for key, value in tests.items()}
        if any(abs(observed[key] - weights[key]) > 1e-9 for key in weights):
            errors.append("single test counts do not form the declared fixed-weight mixture")

    baselines = design.get("baselines", {})
    if set(baselines) != set(BASELINE_SUITES):
        errors.append("baselines must configure exactly B0, B0R, B1, T00, T10, T01, and T11")
    for name, suites in BASELINE_SUITES.items():
        if name in baselines and set(baselines[name].get("suites", [])) != suites:
            errors.append(f"{name} must run suites {sorted(suites)}")
    for name in ("B0", "B0R"):
        if name in baselines and set(baselines[name].get("suites", [])) != {"single"}:
            errors.append(f"{name} is single-only")

    gates = design.get("quality_gates", {})
    if gates.get("baseline_score_target") is not None:
        errors.append("baseline_score_target must be null; do not threshold baselines")
    if gates.get("drop_cases_based_on_winner") is not False:
        errors.append("drop_cases_based_on_winner must be false")
    for gate in ("family_disjoint_bank_dev_test", "shared_definitions_and_source_information", "authored_sql_independent_of_compiler", "counterexample_fixture_required_for_noncore", "test_labels_exposed_to_implementer", "raw_failures_and_timeouts_retained", "freeze_code_data_bank_scorer_protocol"):
        expected = gate != "test_labels_exposed_to_implementer"
        if gates.get(gate) is not expected:
            errors.append(f"quality gate {gate} must be {str(expected).lower()}")
    if gates.get("human_reviewers_required", 0) < 2:
        errors.append("at least two human reviewers are required")

    execution = design.get("execution", {})
    reserve = execution.get("reserve_usd_within_shared_ledger")
    if type(reserve) not in (int, float) or not 0 < reserve <= 10:
        errors.append("execution reserve must fit the shared positive USD 10 budget")
    buckets = design.get("memory_distance", {}).get("test_buckets", [])
    planned_dialogues = design.get("interactive_targets", {}).get("conversation", {}).get("test", 0)
    if sum(bucket.get("min_dialogues", 0) for bucket in buckets) != planned_dialogues:
        errors.append("memory-distance bucket quotas must equal the planned conversation test dialogues")
    next_distance = 0
    for index, bucket in enumerate(buckets):
        low, high = bucket.get("min"), bucket.get("max")
        if (type(low) is not int or low != next_distance
                or type(bucket.get("min_dialogues")) is not int or bucket["min_dialogues"] <= 0
                or (high is None and index != len(buckets) - 1)
                or (high is not None and (type(high) is not int or high < low))):
            errors.append("memory-distance buckets must be positive, contiguous and nonoverlapping")
            break
        next_distance = high + 1 if high is not None else None
    if not buckets or buckets[-1].get("max") is not None:
        errors.append("memory-distance buckets must include an open-ended final range")
    if design.get("memory_distance", {}).get("unit") != "intervening_successful_results":
        errors.append("memory-distance unit must count intervening successful results")

    if blueprints is not None:
        entries = blueprints.get("scenarios", blueprints) if isinstance(blueprints, dict) else blueprints
        if not isinstance(entries, list):
            errors.append("scenario blueprints must be a list or contain a scenarios list")
        else:
            metadata = blueprints.get("metadata", {}) if isinstance(blueprints, dict) else {}
            if isinstance(blueprints, dict):
                if metadata.get("status") != "design_draft_not_executable" or metadata.get("review_status") != "agent_drafted" or metadata.get("executable_dataset") is not False:
                    errors.append("scenario blueprint bank metadata must remain agent-drafted and not executable")
                if set(metadata.get("sources", [])) != catalog_sources:
                    errors.append("scenario blueprint metadata sources must match catalog sources")
                if set(metadata.get("metric_ids", [])) != set(scope.get("metrics", [])):
                    errors.append("scenario blueprint metadata metrics must match design scope")
                if set(metadata.get("nested_paths", [])) != declared_paths:
                    errors.append("scenario blueprint metadata nested paths must match catalog declarations")
            ids: set[str] = set()
            phenomenon_ids = set(design.get("phenomena", []))
            for i, item in enumerate(entries):
                label = f"scenario[{i}]"
                if not isinstance(item, dict):
                    errors.append(f"{label} must be a mapping")
                    continue
                sid = item.get("id")
                if not sid or sid in ids:
                    errors.append(f"{label} must have a unique nonempty id")
                ids.add(sid)
                if item.get("suite") not in BLUEPRINT_SUITES:
                    errors.append(f"{label} has unknown suite")
                if item.get("suite") == "single" and item.get("stratum") not in {"core_control", "semantic_data_shape", "composed_in_scope"}:
                    errors.append(f"{label} has unknown single stratum")
                if item.get("difficulty") not in {"easy", "medium", "hard"}:
                    errors.append(f"{label} has unknown difficulty")
                if not isinstance(item.get("template_family"), str) or not item["template_family"].strip():
                    errors.append(f"{label} needs a nonempty template_family")
                if not isinstance(item.get("expected_behavior"), str) or not item["expected_behavior"].strip():
                    errors.append(f"{label} needs an expected_behavior")
                if item.get("suite") == "conversation":
                    turns = item.get("turns")
                    if not isinstance(turns, list) or len(turns) < 2 or any(not isinstance(t, str) or not t.strip() for t in turns):
                        errors.append(f"{label} needs at least two nonempty conversational turns")
                elif not isinstance(item.get("question"), str) or not item["question"].strip():
                    errors.append(f"{label} needs a nonempty question")
                phenomena = item.get("phenomena", [])
                if not isinstance(phenomena, list) or not phenomena or not set(phenomena) <= phenomenon_ids:
                    errors.append(f"{label} has unknown or missing phenomena")
                source = item.get("source_id")
                if "source_id" not in item or (source is not None and source not in catalog_sources):
                    errors.append(f"{label} has missing or unsupported source_id")
                if source is None and item.get("suite") != "clarification":
                    errors.append(f"{label} may omit source_id only for clarification")
                if item.get("language") not in {"vi", "en"}:
                    errors.append(f"{label} has unsupported language")
                required = item.get("required_capabilities", {})
                if not isinstance(required, dict):
                    errors.append(f"{label} required_capabilities must map catalog categories to IDs")
                else:
                    for category in ("metrics", "dimensions"):
                        capability_ids = required.get(category, [])
                        category_ids = {entry.get("id") for entry in catalog.get(category, [])}
                        if not isinstance(capability_ids, list) or not set(capability_ids) <= category_ids:
                            errors.append(f"{label} requires {category} IDs absent from the catalog")
                    if set(required) - {"metrics", "dimensions"}:
                        errors.append(f"{label} uses unknown required_capabilities category")
                    if item.get("suite") == "single" and len(required.get("metrics", [])) != 1:
                        errors.append(f"{label}: answerable single query must require exactly one metric")
                if item.get("review_status") != "agent_drafted":
                    errors.append(f"{label} must remain marked agent_drafted")
            by_id = {item["id"]: item for item in entries if isinstance(item, dict) and item.get("id")}
            for item in by_id.values():
                partner_id = item.get("counterfactual_pair_id")
                if partner_id:
                    partner = by_id.get(partner_id, {})
                    if (partner_id == item["id"] or partner.get("counterfactual_pair_id") != item["id"]
                            or partner.get("template_family") != item.get("template_family")):
                        errors.append(f"{item['id']}: counterfactual pair must be reciprocal and share one family")
    if require_ready:
        if design.get("status") == "design_draft_not_executable" or execution.get("currently_runnable") is not True:
            errors.append("--require-ready: design is draft or not executable")
        if not blueprints:
            errors.append("--require-ready: no human-reviewed executable scenario bank is available")
        else:
            entries = blueprints.get("scenarios", blueprints) if isinstance(blueprints, dict) else blueprints
            metadata = blueprints.get("metadata", {}) if isinstance(blueprints, dict) else {}
            if (not isinstance(entries, list) or not entries or metadata.get("status") != "human_reviewed_executable"
                    or metadata.get("executable_dataset") is not True
                    or any(x.get("review_status") != "human_reviewed_executable" for x in entries if isinstance(x, dict))):
                errors.append("--require-ready: scenario bank lacks human-reviewed executable cases")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-ready", action="store_true", help="also require a human-reviewed executable case bank")
    parser.add_argument("--design", type=Path, default=DESIGN_PATH)
    parser.add_argument("--catalog", type=Path, default=CATALOG_PATH)
    parser.add_argument("--blueprints", type=Path, default=BLUEPRINT_PATH)
    args = parser.parse_args(argv)
    try:
        design, catalog = _load(args.design), _load(args.catalog)
        blueprints = _load(args.blueprints) if args.blueprints.exists() else None
        errors = validate_design(design, catalog, blueprints, args.require_ready)
    except (OSError, yaml.YAMLError) as exc:
        print(f"invalid input: {exc}", file=sys.stderr)
        return 2
    count = len(blueprints.get("scenarios", blueprints) if isinstance(blueprints, dict) else blueprints) if blueprints else 0
    print(f"scenario blueprints: {count} (draft entries only; not executable/complete holdout)")
    if errors:
        print("validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("design validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
