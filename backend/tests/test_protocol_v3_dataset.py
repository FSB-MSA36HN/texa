import hashlib
import importlib
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]
DATA = Path(__file__).resolve().parents[2] / 'data/benchmark/remediation_v3_regression'


def test_v3_is_explicitly_inspected_regression_and_gold_is_copy_preserved():
    manifest = yaml.safe_load((DATA / 'manifest.yaml').read_text())
    assert manifest['dataset_type'] == 'remediation_regression'
    assert manifest['evaluation_purpose'] == 'inspected_regression_unsealed'
    assert manifest['status'] == 'inspected_regression_unsealed'
    new_cases = yaml.safe_load((DATA / 'cases.yaml').read_text())
    old_cases = yaml.safe_load((ROOT / 'data/benchmark/remediation_v2/cases.yaml').read_text())
    assert len(new_cases) == len(old_cases) == 24
    assert [(x['id'], x['gold_sql'], x['expected_result']) for x in new_cases] == [
        (x['id'], x['gold_sql'], x['expected_result']) for x in old_cases]
    assert len(yaml.safe_load((DATA / 'interactions.yaml').read_text())) == 4
    assert len(yaml.safe_load((DATA / 'dialogues.yaml').read_text())) == 4
    validation = json.loads((DATA / 'validation.json').read_text())
    for name, expected in validation['hashes'].items():
        assert hashlib.sha256((DATA / name).read_bytes()).hexdigest() == expected


def test_v3_schema_and_lock_validate_with_generic_dataset_dispatch():
    sys.path.insert(0, str(ROOT / 'backend/eval'))
    from validate_dataset import validate_remediation_regression
    report = validate_remediation_regression(DATA)
    assert report == json.loads((DATA / 'validation.json').read_text())
    assert report['counts'] == {'single_cases': 24, 'clarification_interactions': 4, 'memory_dialogues': 4}
    assert report['intent_label_counts']['single_time_range_all'] == 30
    assert report['predeclared_unsupported_turns'][0]['scoring_kind'] == 'discussion_answer'


def test_cli_routes_each_v3_suite_without_paid_calls(capsys):
    sys.path.insert(0, str(ROOT / 'backend'))
    sys.path.insert(0, str(ROOT / 'backend/eval'))
    import run_ablation
    for suite in ('single', 'clarification', 'memory'):
        assert run_ablation.main(['--dataset-dir', str(DATA), '--suite', suite, '--split', 'dev']) == 0
        output = json.loads(capsys.readouterr().out)
        assert output['mode'] == 'dry_run' and output['model_calls'] == 0
        assert output['scenarios'] > 0


def test_oracle_labels_are_intent_only():
    cases = yaml.safe_load((DATA / 'cases.yaml').read_text())
    for case in cases:
        answers = case.get('oracle_answers', {})
        assert set(answers) <= {'time_range', 'context:source'}
        assert answers.get('context:source') == [case['source_id']]
        if 'time_range' in answers:
            assert answers['time_range'] == ['all']
            assert case['oracle_intent']['time_range'] == 'all'
        assert not set(map(str, case['expected_result'].get('rows', []))) & set(map(str, answers.values()))


def test_diagnostic_candidate_ids_are_redacted_or_allowlisted(monkeypatch):
    backend = Path(__file__).resolve().parents[2] / 'backend'
    project_backend = ROOT / 'backend'
    sys.path[:0] = [str(project_backend), str(project_backend / 'eval'), str(backend / 'eval')]
    runner = importlib.import_module('run_ablation')
    turn = {'status': 'needs_clarification', 'form': {'fields': [
        {'id': 'time_range', 'kind': 'single_choice',
         'choices': [{'id': 'all'}, {'id': 'secret_customer_42'}]}]}}
    rendered = json.dumps(runner.trace(turn))
    assert 'all' in rendered
    assert 'redacted_candidate' in rendered
    assert 'secret_customer_42' not in rendered
