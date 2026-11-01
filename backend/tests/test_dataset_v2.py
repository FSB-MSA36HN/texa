"""Frozen benchmark integrity, separate from measured model accuracy."""
import importlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data/benchmark/v2'


@pytest.fixture
def validator(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'backend/eval'))
    return importlib.import_module('validate_dataset')


def test_frozen_dataset_matches_reviewed_annotation_counts_and_hashes(validator):
    expected = json.loads((DATA / 'validation.json').read_text())
    assert validator.validate_dataset(DATA) == expected
    assert expected['cases'] >= 100
    assert expected['dialogues'] >= 12


def test_every_catalog_metric_and_required_edge_are_represented():
    cases = yaml.safe_load((DATA / 'cases.yaml').read_text())
    columns = {col for c in cases for col in c['expected_result']['columns']}
    assert {'events', 'users', 'sessions', 'viewers', 'buyers', 'purchases', 'revenue', 'buyer_conversion_rate'} <= columns
    assert any(c['expected_result'] == {'columns': ['buyer_conversion_rate'], 'rows': [[None]]} for c in cases)
    assert any(len(row) > 1 and row[0] is None for c in cases for row in c['expected_result']['rows'])
    assert any(c.get('ordered') for c in cases)
    dialogues = yaml.safe_load((DATA / 'dialogues.yaml').read_text())
    assert max(len(d['turns']) for d in dialogues) >= 10
    assert any(t.get('referenced_turn') and i-t['referenced_turn'] >= 7
               for d in dialogues for i,t in enumerate(d['turns'], 1))
    assert {'clarify', 'refuse', 'conversation'} <= {t['action'] for d in dialogues for t in d['turns']}


def test_reference_flattened_dimensions_match_the_actual_json():
    spec = importlib.util.spec_from_file_location('generate_v2', DATA / 'generate.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.make_rows()
    assert rows == module.make_rows()
    catalog = yaml.safe_load((ROOT / 'catalog/product_events.yaml').read_text())
    allowed = set(next(role['events'] for role in catalog['event_roles'] if role['id'] == 'any_event'))
    assert {row['event_name'] for row in rows} <= allowed
    assert any(row['revenue'] == 0 and row['event_name'] == 'purchase' for row in rows)
    assert not any(row['event_name'] == 'purchase' for row in rows if row['item_category'] == 'clearance')
    for row in rows:
        assert row['device_type'] == row['ep'].get('device', {}).get('type')
        assert row['campaign_channel'] == row['ep'].get('campaign', {}).get('channel')
        assert row['item_category'] == row['ep']['product']['category']
    with pytest.raises(ValueError):
        module.evaluate(rows, ('events', ["typo='mobile'"], None))
