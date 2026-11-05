from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
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
    assert len(bank.examples) == 42  # semantic reviewed; only 7 have executable reference SQL
    assert sum(x["review"]["review_status"] == "draft" for x in raw["examples"]) == 3
    assert all(x["review"]["reviewer_kind"] == "agent" for x in raw["examples"])
    assert all(x["review"]["human_reviewed"] is False for x in raw["examples"])
    assert all(x["reference"]["verification_status"] in {"not_executed", "draft_unexecuted", "verified"}
               for x in raw["examples"])
    assert any(x["reference"]["reference_sql"] for x in raw["examples"])
    assert sum(x["reference"]["verification_status"] == "verified" for x in raw["examples"]) == 7
    assert all(x["review"]["human_reviewed"] is False for x in bank.examples)
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
    assert packed.packed_utf8_bytes <= 30
    assert len(packed.ids) <= 3
    assert examples.render_examples(packed).count("Q: ") == len(packed.ids)


def test_live_token_pack_tracks_approximate_tokens_and_hard_rendered_byte_cap(tmp_path):
    bank = approved_fixture(tmp_path)
    result = examples.retrieve_examples(bank, "Doanh thu theo tháng của Olist", confirmed_sources=["olist_marketplace"])
    rendered = examples.render_examples(result, structured=True)
    assert result.ids
    assert result.estimated_tokens <= 600
    assert result.token_estimate_method == "utf8_bytes_div_2_heuristic"
    assert result.packed_utf8_bytes == len(rendered.encode("utf-8"))
    assert result.packed_utf8_bytes <= examples.HARD_TOKEN_CAP


def test_multi_example_packing_counts_header_and_separators_in_actual_rendered_cap():
    bank = examples.ExampleBank("test", 1, 1, tuple({
        "id": f"ex_{i}", "family": f"family_{i}", "language": "en",
        "sources": ["cosmetics_shop"], "question": "event count", "business_note": "",
        "tags": [], "candidate": {"outcome": "query", "recipe": "events"}}
        for i in range(3)), "hash")
    result = examples.retrieve_examples(bank, "event count", token_budget=600, hard_cap=1200)
    rendered = examples.render_examples(result, structured=True)
    assert len(result.ids) >= 2
    assert result.packed_utf8_bytes == len(rendered.encode("utf-8"))
    assert result.packed_utf8_bytes <= 1200


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
                              "answer_request", "language", "top_k", "dialogue"}
    from texa.prompts import CANDIDATE_SCHEMA, structured_candidate_schema
    from jsonschema import Draft202012Validator
    Draft202012Validator(CANDIDATE_SCHEMA).validate({k: v for k, v in candidate.items() if k != "dialogue"})
    Draft202012Validator(structured_candidate_schema()).validate(candidate)
    assert candidate["dialogue"]["relation"] == "new_topic"
    assert candidate["dialogue"]["target_id"] == ""
    assert all(value in {"set", "clear"} for value in candidate["dialogue"]["slots"].values())
    try:
        examples.retrieve_examples(bank, "users", confirmed_sources=["benchmark"])
    except ValueError as exc:
        assert "unknown confirmed source" in str(exc)
    else:
        raise AssertionError("unknown source scope unexpectedly accepted")


def test_rendered_candidate_matches_active_output_contract(tmp_path):
    from jsonschema import Draft202012Validator
    from texa.prompts import CANDIDATE_SCHEMA, structured_candidate_schema

    bank = approved_fixture(tmp_path)
    result = examples.retrieve_examples(bank, "Doanh thu theo tháng của Olist", max_examples=1)
    structured_json = examples.render_examples(result, structured=True).split("A: ", 1)[1]
    structured = json.loads(structured_json)["expected_candidate"]
    Draft202012Validator(structured_candidate_schema()).validate(structured)
    legacy_json = examples.render_examples(result, structured=False).split("A: ", 1)[1]
    legacy = json.loads(legacy_json)["expected_candidate"]
    Draft202012Validator(CANDIDATE_SCHEMA).validate(legacy)


def test_verified_reference_sql_matches_handwritten_expected_rows_in_isolated_postgres():
    dsn = os.getenv("TEXA_EXAMPLE_REVIEW_DSN")
    if not dsn:
        pytest.skip("set TEXA_EXAMPLE_REVIEW_DSN to run SQL reference fixture validation")
    psycopg = pytest.importorskip("psycopg")
    raw = yaml.safe_load(examples.DEFAULT_BANK_PATH.read_text())
    verified = [item for item in raw["examples"]
                if item["reference"].get("verification_status") == "verified"]
    assert len(verified) == 7
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT current_database()").fetchone()[0] == "texa_benchmark"
        conn.execute("BEGIN")
        try:
            conn.execute((ROOT / "catalog/example_bank_fixture.sql").read_text())
            for item in verified:
                reference = item["reference"]
                sql = reference["reference_sql"].replace(
                    "analytics.event_activity", "example_review.event_activity")
                assert sql != reference["reference_sql"]
                actual = conn.execute(sql).fetchall()
                def normalize(value):
                    if value is None:
                        return "NULL"
                    if hasattr(value, "isoformat"):
                        return value.isoformat()
                    if hasattr(value, "as_tuple"):
                        return float(value)
                    return value
                actual_rows = sorted(tuple(normalize(v) for v in row) for row in actual)
                expected_rows = sorted(tuple(row) for row in reference["expected_rows"])
                assert actual_rows == expected_rows, item["id"]
        finally:
            conn.rollback()
