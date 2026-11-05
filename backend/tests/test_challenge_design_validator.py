import yaml

from eval.validate_challenge_design import BLUEPRINT_PATH, CATALOG_PATH, DESIGN_PATH, validate_design


def inputs():
    return yaml.safe_load(DESIGN_PATH.read_text()), yaml.safe_load(CATALOG_PATH.read_text())


def test_current_design_passes_structural_and_fairness_validation():
    design, catalog = inputs()
    assert validate_design(design, catalog) == []


def test_rejects_score_rigging_threshold_and_winner_case_drops():
    design, catalog = inputs()
    design["quality_gates"]["baseline_score_target"] = 0.8
    design["quality_gates"]["drop_cases_based_on_winner"] = True
    errors = validate_design(design, catalog)
    assert any("baseline_score_target" in error for error in errors)
    assert any("drop_cases_based_on_winner" in error for error in errors)


def test_rejects_weight_quota_inconsistency():
    design, catalog = inputs()
    design["metrics"]["stratum_weights"]["core_control"] = 0.5
    design["source_test_quota"]["cosmetics_shop"]["single_min"] = 121
    errors = validate_design(design, catalog)
    assert any("weights" in error for error in errors)
    assert any("quotas exceed" in error for error in errors)


def test_rejects_expanded_metric_scope_and_draft_ready_request():
    design, catalog = inputs()
    design["scope"]["metrics"].append("orders")
    errors = validate_design(design, catalog, require_ready=True)
    assert any("scope.metrics" in error for error in errors)
    assert any("draft or not executable" in error for error in errors)
    assert any("human-reviewed executable" in error for error in errors)


def test_blueprints_are_checked_but_remain_drafts():
    design, catalog = inputs()
    blueprints = {"metadata": {"status": "design_draft_not_executable", "review_status": "agent_drafted",
                   "executable_dataset": False, "sources": ["cosmetics_shop", "olist_marketplace"],
                   "metric_ids": ["events", "users", "sessions", "viewers", "purchases", "buyers", "revenue", "buyer_conversion_rate"],
                   "nested_paths": ["ep.device.type", "ep.campaign.channel"]}, "scenarios": [{"id": "a", "suite": "single", "stratum": "core_control", "difficulty": "easy",
                   "phenomena": ["distinct_user_vs_event_count"], "source_id": "cosmetics_shop",
                   "template_family": "unique_users_period", "question": "Count users in January 2020.",
                   "expected_behavior": "Count distinct observed users over the specified month.",
                   "language": "vi", "required_capabilities": {"metrics": ["users"], "dimensions": ["device_type"]},
                   "review_status": "agent_drafted"}]}
    assert validate_design(design, catalog, blueprints) == []
    design["status"] = "candidate"
    design["execution"]["currently_runnable"] = True
    blueprints["metadata"]["status"] = "human_reviewed_executable"
    blueprints["metadata"]["executable_dataset"] = True
    errors = validate_design(design, catalog, blueprints, require_ready=True)
    assert any("human-reviewed executable" in error for error in errors)
    blueprints["scenarios"][0]["required_capabilities"] = {"metrics": ["made_up_metric"]}
    assert any("catalog" in error for error in validate_design(design, catalog, blueprints))


def test_real_blueprint_bank_is_valid_draft_not_ready():
    design, catalog = inputs()
    blueprints = yaml.safe_load(BLUEPRINT_PATH.read_text())
    assert len(blueprints["scenarios"]) == 24
    assert validate_design(design, catalog, blueprints) == []
    assert any("human-reviewed executable" in error for error in
               validate_design(design, catalog, blueprints, require_ready=True))


def test_rejects_overlapping_memory_ranges_and_overallocated_dialogues():
    design, catalog = inputs()
    design["memory_distance"]["test_buckets"][1]["min"] = 2
    design["memory_distance"]["test_buckets"][0]["min_dialogues"] += 1
    errors = validate_design(design, catalog)
    assert any("nonoverlapping" in error for error in errors)
    assert any("quotas must equal" in error for error in errors)


def test_rejects_missing_pair_member_and_unlabelled_family():
    design, catalog = inputs()
    blueprints = yaml.safe_load(BLUEPRINT_PATH.read_text())
    pair = next(item for item in blueprints["scenarios"] if item.get("counterfactual_pair_id"))
    pair["counterfactual_pair_id"] = "absent_partner"
    del pair["template_family"]
    errors = validate_design(design, catalog, blueprints)
    assert any("template_family" in error for error in errors)
    assert any("reciprocal" in error for error in errors)


def test_answerable_single_cannot_silently_expand_to_multiple_metrics():
    design, catalog = inputs()
    blueprints = yaml.safe_load(BLUEPRINT_PATH.read_text())
    case = next(item for item in blueprints["scenarios"] if item["suite"] == "single")
    case["required_capabilities"]["metrics"] = ["revenue", "buyers"]
    assert any("exactly one metric" in error for error in validate_design(design, catalog, blueprints))


def test_rejects_invalid_target_counts_without_crashing():
    design, catalog = inputs()
    design["single_strata"]["core_control"]["test"] = -1
    assert any("positive integers" in error for error in validate_design(design, catalog))
