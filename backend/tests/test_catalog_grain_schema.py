from copy import deepcopy
from pathlib import Path

import yaml

from texa import catalog, interpret
from texa.prompts import CANDIDATE_SCHEMA


def test_grain_identifiers_follow_catalog_without_mutating_global_schema():
    root = Path(__file__).resolve().parents[2]
    cat = catalog.validate_catalog(yaml.safe_load((root / "catalog/product_events.yaml").read_text()))
    original = deepcopy(CANDIDATE_SCHEMA)
    # Counts and monetary sums can share entity grain while retaining different units.
    assert cat.mets["revenue"].intent_grain == cat.mets["purchases"].intent_grain
    assert cat.mets["revenue"].unit != cat.mets["purchases"].unit
    cat.mets["revenue"].intent_grain = "renamed_entity_grain"
    for structured in (True, False):
        schema = interpret.candidate_schema(cat, structured=structured)
        grains = schema["properties"]["intent_contract"]["properties"]["grain"]["enum"]
        assert "renamed_entity_grain" in grains
        assert "uncatalogued" in grains
        assert "purchased_item_line_value" not in grains
        assert "sum" in schema["properties"]["intent_contract"]["properties"]["operation"]["enum"]
    assert CANDIDATE_SCHEMA == original
