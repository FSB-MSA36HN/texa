from pathlib import Path

import pytest
import yaml

from texa.catalog import Catalog, Source, nested_field_parts, validate_catalog
from texa.compile import _Builder
from texa.profiler import load_profile


ROOT = Path(__file__).resolve().parents[2]
RAW = yaml.safe_load((ROOT / "catalog" / "ecommerce.yaml").read_text())


def test_nested_paths_are_bounded():
    assert nested_field_parts("ep.order.total") == ("ep", ("order", "total"))
    assert nested_field_parts("up.profile.segment") == ("up", ("profile", "segment"))
    for path in ("ep.foo.bar.baz", "ep.items[0].price", "ep.foo[]", "other.foo", "ep.foo;drop"):
        assert nested_field_parts(path) is None


def test_catalog_accepts_nested_typed_paths_and_rejects_unbounded():
    raw = yaml.safe_load(yaml.safe_dump(RAW))
    raw["dimensions"].append({"id": "order_total", "label": "Order total", "field": "ep.order.total", "cast": "number"})
    cat = validate_catalog(raw)
    assert cat.dims["order_total"].value_type == "number"
    raw["dimensions"][-1]["field"] = "ep.order.total.amount"
    with pytest.raises(ValueError, match="unknown field"):
        validate_catalog(raw)


def test_profile_is_versioned_bounded_and_cached():
    fields = {"ep.order.total": 5, "up.profile.segment": 4, "ep.deep.one.two.three": 1, "ep.items[]": 2}
    a = load_profile("v1", fields)
    b = load_profile("v1", fields)
    c = load_profile("v2", fields)
    assert a is b and c is not a
    assert a.contains("ep.order.total") and not a.contains("ep.deep.one.two.three")


