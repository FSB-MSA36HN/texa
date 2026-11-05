from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import yaml

from texa import examples
from texa.catalog import validate_catalog

ROOT = Path(__file__).resolve().parents[2]


def catalog():
    raw = yaml.safe_load((ROOT / "catalog/product_events.yaml").read_text())
    return validate_catalog(raw)


def approved_fixture(tmp_path):
    raw = yaml.safe_load(examples.DEFAULT_BANK_PATH.read_text())
    raw["examples"] = deepcopy(raw["examples"])
    for item in raw["examples"]:
        item["review"].update(review_status="approved", reviewer_id="independent-test-reviewer",
                              evidence="synthetic test fixture", human_reviewed=False)
    path = tmp_path / "approved.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True))
    return examples.load_bank(catalog(), path)


def test_catalog_bank_is_valid_agent_reviewed_pilot_and_not_human_claim():
    cat = catalog()
    raw = yaml.safe_load(examples.DEFAULT_BANK_PATH.read_text())
    assert 32 <= len(raw["examples"]) <= 48
    assert examples.validate_bank(raw, catalog_version=cat.version) == []
    bank = examples.load_bank(cat)
    assert bank.examples == ()  # independent review is still pending
    assert all(x["review"]["review_status"] == "draft" for x in raw["examples"])
    assert all(x["review"]["reviewer_kind"] == "agent" for x in raw["examples"])
    assert all(x["review"]["human_reviewed"] is False for x in raw["examples"])
    assert all(x["reference"]["verification_status"] in {"not_executed", "draft_unexecuted"}
               for x in raw["examples"])
    assert any(x["reference"]["reference_sql"] for x in raw["examples"])
    assert not any(x["reference"]["verification_status"] == "verified" for x in raw["examples"])
    assert {x["language"] for x in raw["examples"]} == {"vi", "en"}


def test_loader_rejects_stale_catalog_or_contract_version():
    try:
        examples.load_bank(SimpleNamespace(version=99, model_dump=catalog().model_dump))
    except examples.ExampleBankError as exc:
        assert "catalog version mismatch" in str(exc)
    else:
        raise AssertionError("stale bank unexpectedly loaded")


def test_retrieval_is_deterministic_relevant_diverse_and_confirmed_source_gated(tmp_path):
    bank = approved_fixture(tmp_path)
    a = examples.retrieve_examples(bank, "Doanh thu theo tháng ở Olist", confirmed_sources=["olist_marketplace"])
    b = examples.retrieve_examples(bank, "Doanh thu theo tháng ở Olist", confirmed_sources=["olist_marketplace"])
    assert a.ids == b.ids
    assert 0 < len(a.ids) <= 3
    assert "revenue_olist_category_en" not in a.ids
    assert all("olist_marketplace" in x["sources"] for x in a.selected)
    assert len({x["family"] for x in a.selected}) == len(a.selected)


def test_retrieval_packs_whole_blocks_under_budget_and_zero_examples_is_supported(tmp_path):
    bank = approved_fixture(tmp_path)
    none = examples.retrieve_examples(bank, "monthly revenue", token_budget=0)
    assert none.ids == () and examples.render_examples(none) == ""
    packed = examples.retrieve_examples(bank, "monthly revenue", token_budget=1200, hard_cap=30)
    assert packed.estimated_tokens <= 30
    assert len(packed.ids) <= 3
    assert examples.render_examples(packed).count("Q: ") == len(packed.ids)


def test_loader_never_retrieves_draft_or_invalid_out_of_scope_example(tmp_path):
    raw = yaml.safe_load(examples.DEFAULT_BANK_PATH.read_text())
    raw["examples"][0]["review"]["review_status"] = "approved"
    # Add another draft with a made-up dimension: contract validation blocks the bank.
    invalid = deepcopy(raw["examples"][0])
    invalid["id"] = "bad_dimension"
    invalid["candidate"]["selection"] = ["orders"]
    raw["examples"].append(invalid)
    path = tmp_path / "bank.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True))
    try:
        examples.load_bank(catalog(), path)
    except examples.ExampleBankError as exc:
        assert "out-of-scope dimension" in str(exc)
    else:
        raise AssertionError("invalid bank unexpectedly loaded")


def test_candidate_is_expanded_to_full_schema_and_source_scope_unknown_is_rejected(tmp_path):
    bank = approved_fixture(tmp_path)
    result = examples.retrieve_examples(bank, "event counts", max_examples=1)
    candidate = result.selected[0]["candidate"]
    assert set(candidate) == {"outcome", "reason", "reply", "suggestions", "source_ids", "shape", "selection",
                              "recipe", "metrics", "recipe_alternatives", "recipe_stated", "filters", "time_range",
                              "answer_request", "language", "top_k"}
    try:
        examples.retrieve_examples(bank, "users", confirmed_sources=["benchmark"])
    except ValueError as exc:
        assert "unknown confirmed source" in str(exc)
    else:
        raise AssertionError("unknown source scope unexpectedly accepted")
