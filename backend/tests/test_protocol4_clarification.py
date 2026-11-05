"""Provider-free tests for the separate clarification-only protocol-v4 regression."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / 'data/benchmark/remediation_v3_regression'
V4 = ROOT / 'data/benchmark/remediation_v4_clarification'
sys.path.insert(0, str(ROOT / 'backend/eval'))
sys.path.insert(0, str(ROOT / 'backend'))

from validate_dataset import validate_remediation_regression
import run_ablation


def test_protocol4_sequential_source_then_period_answers_only_requested_fields():
    item = next(row for row in yaml.safe_load((V4 / 'interactions.yaml').read_text())
                if row['id'] == 'rv2clar_test_source_conflict')
    source_form = {'status': 'needs_clarification', 'form': {'fields': [{
        'id': 'context:source', 'kind': 'single_choice',
        'choices': [{'id': 'cosmetics_shop'}, {'id': 'olist_marketplace'}]}]}}
    period_form = {'status': 'needs_clarification', 'form': {'fields': [{
        'id': 'time_range', 'kind': 'single_choice',
        'choices': [{'id': 'all'}, {'id': 'last_7'}, {'id': 'last_30'}]}]}}
    assert run_ablation.oracle_for(item, source_form, {}) == {'context:source': ['cosmetics_shop']}
    assert run_ablation.oracle_for(item, period_form, {}) == {'time_range': ['all']}


def test_protocol4_never_delivers_unsolicited_intent_fields():
    item = next(row for row in yaml.safe_load((V4 / 'interactions.yaml').read_text())
                if row['id'] == 'rv2clar_test_source_conflict')
    period_form = {'status': 'needs_clarification', 'form': {'fields': [{
        'id': 'time_range', 'kind': 'single_choice', 'choices': [{'id': 'all'}]}]}}
    reply = run_ablation.oracle_for(item, period_form, {})
    assert reply == {'time_range': ['all']}
    assert not set(reply) & {'source', 'context:source', 'recipe'}


def test_protocol4_validator_rejects_oracle_intent_mismatch():
    with tempfile.TemporaryDirectory(prefix='protocol4-test-', dir=ROOT / '.runtime') as temporary:
        copy = Path(temporary) / 'dataset'
        shutil.copytree(V4, copy)
        path = copy / 'interactions.yaml'
        interactions = yaml.safe_load(path.read_text())
        item = next(row for row in interactions if row['id'] == 'rv2clar_test_source_conflict')
        item['oracle_answers']['time_range'] = ['last_7']
        path.write_text(yaml.safe_dump(interactions, allow_unicode=True, sort_keys=False))
        with pytest.raises(ValueError, match='oracle answer differs from declared'):
            validate_remediation_regression(copy, check_lock=False)


def test_protocol4_validator_requires_a_well_formed_oracle_field_list():
    with tempfile.TemporaryDirectory(prefix='protocol4-test-', dir=ROOT / '.runtime') as temporary:
        copy = Path(temporary) / 'dataset'
        shutil.copytree(V4, copy)
        path = copy / 'manifest.yaml'
        manifest = yaml.safe_load(path.read_text())
        manifest['oracle_field_ids'] = 'recipe'
        path.write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False))
        with pytest.raises(ValueError, match='unsupported interaction oracle field declaration'):
            validate_remediation_regression(copy, check_lock=False)


def test_legacy_v3_dataset_lock_remains_valid():
    report = validate_remediation_regression(V3)
    assert report == json.loads((V3 / 'validation.json').read_text())
    assert report['counts'] == {'single_cases': 24, 'clarification_interactions': 4, 'memory_dialogues': 4}


def test_protocol4_preserves_all_questions_and_gold_from_v3():
    old = yaml.safe_load((V3 / 'interactions.yaml').read_text())
    new = yaml.safe_load((V4 / 'interactions.yaml').read_text())
    fields = ('question', 'gold_sql', 'expected_result')
    old_by_id, new_by_id = ({row['id']: row for row in rows} for rows in (old, new))
    assert old_by_id.keys() == new_by_id.keys()
    for key in old_by_id:
        assert {field: old_by_id[key][field] for field in fields} == {
            field: new_by_id[key][field] for field in fields}
