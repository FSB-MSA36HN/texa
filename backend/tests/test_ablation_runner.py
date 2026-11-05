"""Provider-free checks of the study protocol, not measurements of Texa quality."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    project = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(project / 'backend'))
    monkeypatch.syspath_prepend(str(project / 'backend/eval'))
    return importlib.import_module('run_ablation')


def result_turn(value=7, *, references=None):
    return {'id': 't1', 'status': 'answered', 'value': value,
            'query_spec': {'recipe': 'events', 'filters': [], 'selection': [], 'time_range': {'kind': 'all'}},
            'context': {'references': references or []}}


def clarify_turn(field='time_range', choices=('all', 'last_7')):
    return {'id': 't1', 'status': 'needs_clarification', 'form': {'fields': [
        {'id': field, 'kind': 'single_choice', 'choices': [{'id': value} for value in choices]}]}}


def expected(value=7):
    return {'question': 'How many events?', 'gold_sql': 'SELECT 7 AS events',
            'expected_result': {'columns': ['events'], 'rows': [[value]]},
            'state': {'metric': 'events', 'time_range': 'all', 'filters': [], 'breakdown': None}}


class ScriptedSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.questions, self.oracles = [], []

    def ask(self, question):
        self.questions.append(question)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value

    def resume(self, turn, oracle):
        self.oracles.append(oracle)
        return next(self.responses)

    def output(self, turn):
        return ['events'], [[turn['value']]]


def test_interaction_delivers_oracle_only_after_actual_matching_form(runner):
    item = expected() | {'ask_fields': ['time_range'], 'oracle_answers': {'time_range': ['all']}}
    full = ScriptedSession([clarify_turn(), result_turn()])
    score = runner.run_interaction(item, full)
    assert score['success'] and score['answer_count'] == 1
    assert full.oracles == [{'time_range': ['all']}]
    guess = ScriptedSession([result_turn()])
    guessed = runner.run_interaction(item, guess)
    assert guessed['success']  # no penalty merely for not asking
    assert guess.oracles == []
    assert guessed['clarification_counts'] == {'tp': 0, 'fp': 0, 'fn': 1}


def test_wrong_guess_uses_hidden_intent_only_for_scoring(runner):
    item = expected(10) | {'ask_fields': ['time_range'], 'oracle_answers': {'time_range': ['all']}}
    session = ScriptedSession([result_turn(7)])
    score = runner.run_interaction(item, session)
    assert not score['success'] and score['answer_correct'] == 0
    assert session.oracles == []
    assert session.questions == [item['question']]


@pytest.mark.parametrize('field,choices', [('recipe', ('events',)), ('time_range', ('last_30',))])
def test_oracle_wrong_field_or_unoffered_choice_is_not_sent(runner, field, choices):
    item = expected() | {'ask_fields': ['time_range'], 'oracle_answers': {'time_range': ['all']}}
    session = ScriptedSession([clarify_turn(field, choices)])
    score = runner.run_interaction(item, session)
    assert score['oracle_error'] == 'oracle_mismatch'
    assert session.oracles == [] and not score['success']


def test_oracle_delivers_requested_subset_across_multiple_forms(runner):
    item = expected() | {'ask_fields': ['time_range', 'recipe'],
        'oracle_answers': {'time_range': ['all'], 'recipe': ['events']}}
    first = clarify_turn('time_range', ('all', 'last_7'))
    second = clarify_turn('recipe', ('events', 'users'))
    session = ScriptedSession([first, second, result_turn()])
    score = runner.run_interaction(item, session, max_rounds=2)
    assert score['success']
    assert session.oracles == [{'time_range': ['all']}, {'recipe': ['events']}]
    assert score['clarification_rounds'] == 2


def test_memory_continuation_honors_configured_round_limit(runner):
    answer = expected() | {'action': 'answer', 'oracle_answers': {'time_range': ['all']}}
    session = ScriptedSession([clarify_turn(), clarify_turn()])
    score = runner.run_memory({'turns': [answer]}, session, max_rounds=1)
    assert score['turns'][0]['oracle_error'] == 'clarification_limit'
    assert len(session.oracles) == 1


def test_duplicate_form_field_ids_are_rejected(runner):
    item = expected() | {'oracle_answers': {'time_range': ['all']}}
    duplicate = clarify_turn()
    duplicate['form']['fields'].append(duplicate['form']['fields'][0])
    with pytest.raises(ValueError, match='duplicate'):
        runner.oracle_for(item, duplicate, {})


def test_unsupported_requested_field_is_not_answered_or_leaked(runner):
    item = expected() | {'ask_fields': ['time_range'], 'oracle_answers': {'time_range': ['all']}}
    session = ScriptedSession([clarify_turn('private_customer_id', ('x',)), result_turn(7)])
    score = runner.run_interaction(item, session)
    assert score['oracle_error'] == 'oracle_mismatch'
    assert session.oracles == []
    assert score['turns'][0]['oracle_continuation'][0]['reason'] == 'oracle_field_or_choice_mismatch'
    assert 'private_customer_id' not in json.dumps(score)


def test_explicit_control_counts_unnecessary_clarification(runner):
    item = expected() | {'ask_fields': [], 'oracle_answers': {}}
    session = ScriptedSession([clarify_turn()])
    score = runner.run_interaction(item, session)
    assert not score['success']
    assert score['clarification_counts']['fp'] == 1
    assert session.oracles == []


def test_memory_six_not_failed_for_private_reference_metadata(runner):
    answer = expected() | {'action': 'answer'}
    followup = answer | {'question': 'And by old context?', 'referenced_turn': 1}
    # Window6 has no structured context.references. Correct output still passes.
    score = runner.run_memory({'turns': [answer, followup]}, ScriptedSession([result_turn(), result_turn()]))
    assert score['success'] and score['answer_count'] == 2
    assert score['turns'][1]['reference_diagnostic'] is False


def test_memory_oracle_reference_resolves_label_without_sending_gold(runner):
    start = expected() | {'action': 'answer'}
    pending = {'question': 'Which one?', 'action': 'clarify', 'ask_fields': ['context:reference']}
    resume = expected() | {'action': 'clarification_answer', 'question': 'The first result',
        'oracle_answers': {'context:reference': ['oracle:turn:1']}, 'oracle_reference_turn': 1}
    session = ScriptedSession([result_turn(), clarify_turn('context:reference', ('t1',)), result_turn()])
    score = runner.run_memory({'turns': [start, pending, resume]}, session)
    assert score['success']
    assert session.oracles == [{'context:reference': ['t1']}]
    assert len(session.questions) == 2


def test_memory_answer_turn_can_legitimately_clarify_and_continue(runner):
    answer = expected() | {'action': 'answer', 'oracle_answers': {'time_range': ['all']}}
    session = ScriptedSession([clarify_turn(), result_turn(7)])
    score = runner.run_memory({'max_clarification_rounds': 2, 'turns': [answer]}, session)
    assert score['success'] and score['answer_correct'] == 1
    assert session.oracles == [{'time_range': ['all']}]
    assert score['turns'][0]['oracle_rounds'] == 1


def test_predeclared_discussion_turn_is_retained_but_not_sql_result_scored(runner):
    first = expected() | {'action': 'answer'}
    discussion = expected() | {'action': 'answer', 'scoring_kind': 'discussion_answer',
                               'question': 'How much revenue did the second category have?',
                               'referenced_turn': 1}
    discussed = {'id': 't2', 'status': 'discussed', 'insight': {'headline': 'Revenue was 20'}}
    class Session(ScriptedSession):
        def output(self, turn):
            if turn.get('status') == 'discussed':
                raise AssertionError('discussion must not call full_result')
            return super().output(turn)
    score = runner.run_memory({'turns': [first, discussion]}, Session([result_turn(), discussed]))
    assert score['expected_answer_count'] == 2
    assert score['answer_count'] == 1
    assert score['unsupported_answer_count'] == 1
    assert score['evaluation_status'] == 'contains_unsupported_task_kind'
    assert score['turns'][1]['evaluation_contract_error'] == 'discussion_answer_has_no_sql_result_contract'


@pytest.mark.parametrize('record,wanted', [
    ({'business_result_correct': True, 'output_contract_compliant': True}, 'correct'),
    ({'business_result_correct': True, 'output_contract_compliant': False}, 'output_contract_only'),
    ({'business_result_correct': False, 'answer_count': 1}, 'wrong_business_result'),
    ({'turns': [{'actual_action': 'clarify', 'expected_action': 'answer'}]}, 'unresolved_clarification'),
    ({'turns': [{'actual_action': 'refuse'}]}, 'refused'),
    ({'error': 'ProviderError'}, 'provider_or_runtime_error'),
    ({'evaluation_status': 'contains_unsupported_task_kind'}, 'evaluation_contract_error'),
])
def test_outcome_taxonomy_is_observable_and_nonsemantic(runner, record, wanted):
    assert runner.outcome_category(record) == wanted


def test_failed_memory_turn_remains_in_denominator_and_batch_continues(runner):
    item = expected() | {'action': 'answer'}
    score = runner.run_memory({'turns': [item, item]}, ScriptedSession([ValueError('failure'), result_turn()]))
    assert score['answer_count'] == 2 and score['answer_correct'] == 1
    assert not score['success']


def test_clarification_round_limit_does_not_loop_forever(runner):
    item = expected() | {'ask_fields': ['time_range'], 'oracle_answers': {'time_range': ['all']}}
    session = ScriptedSession([clarify_turn(), clarify_turn()])
    score = runner.run_interaction(item, session, max_rounds=1)
    assert score['oracle_error'] == 'clarification_limit' and len(session.oracles) == 1


def test_normalize_slots_equivalent_time_and_equality_operator(runner):
    turn = result_turn()
    turn['query_spec'].update(time_range={'kind': 'last_n_days', 'days': 7}, filters=[
        {'field': 'device_type', 'operator': '=', 'values': ['mobile']}])
    slots = runner.slot_checks({'time_range': 'last_7', 'filters': [{'device_type': 'mobile'}]}, turn)
    assert all(slots.values())
    turn['query_spec']['filters'][0]['operator'] = '!='
    assert not runner.slot_checks({'filters': [{'device_type': 'mobile'}]}, turn)['filters']


def test_default_and_matrix_are_provider_free_and_rotated(runner, monkeypatch, capsys):
    from texa import llm
    monkeypatch.setattr(llm, 'generate_structured', lambda **_: pytest.fail('dry-run made a provider call'))
    assert runner.main(['--matrix']) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['model_calls'] == 0
    assert [run['variant'] for run in plan['runs']] == ['F', 'M6', 'M0', 'M6', 'M0', 'F', 'M0', 'F', 'M6']


def test_invalid_suite_variant_or_missing_paid_config_rejected(runner):
    with pytest.raises(SystemExit):
        runner.main(['--suite', 'memory', '--variant', 'C0'])
    with pytest.raises(SystemExit):
        runner.main(['--execute', '--model', 'same-model'])


def test_frozen_protocol_rejects_changed_inputs_and_is_required_on_test(runner, tmp_path, monkeypatch):
    args = SimpleNamespace(suite='memory', model='same-model', split='test', protocol=None)
    with pytest.raises(ValueError, match='requires'):
        runner.check_protocol(args, {'hash': 'one'})
    # Input helper is normally workspace-restricted; this test exercises protocol
    # comparison only, with a temporary already-authorized path.
    path = tmp_path / 'protocol.json'
    monkeypatch.setattr(runner, '_project_path', lambda _: path)
    path.write_text(json.dumps(runner.protocol(args, {'hash': 'one'})))
    args.protocol = str(path)
    runner.check_protocol(args, {'hash': 'one'})
    with pytest.raises(ValueError, match='differ'):
        runner.check_protocol(args, {'hash': 'changed'})


def test_execute_writes_reportable_complete_records_and_does_not_overwrite(runner, monkeypatch):
    from texa import llm
    output = Path(__file__).resolve().parents[2] / 'test-ablation-execute.jsonl'
    output.unlink(missing_ok=True)
    args = SimpleNamespace(variant='F', suite='single', split='dev', model='same-model', repeat=1,
        output=str(output), protocol=None, max_model_calls=4, turn_timeout=1, max_clarification_rounds=2)
    provenance = {'dataset_hashes': {'cases': 'hash'}, 'catalog_hash': 'cat', 'prompt_hashes': {'shared': 'p'},
        'source_digest': 'fixture', 'effective_model_config': {'model': 'same-model'}, 'commit': 'revision'}
    monkeypatch.setattr(runner, 'preflight', lambda *a: provenance)
    monkeypatch.setenv('TEXA_ABLATION_VARIANT', 'F')
    monkeypatch.setattr(llm, 'generate_structured', lambda **_: {})
    class Session(ScriptedSession):
        def __init__(self, *a):
            super().__init__([result_turn()])
            self.api = SimpleNamespace(RUNS={})
            self.turn_ids = set()
        def ask(self, question):
            llm.generate_structured(model='same-model', prompt=question, system='S', schema={}, name='scripted')
            return super().ask(question)
        def usage(self):
            return {'calls': 1, 'input_tokens': 10, 'output_tokens': 2, 'model_ms': 5}
        def close(self):
            pass
    monkeypatch.setattr(runner, 'TexaSession', Session)
    item = expected() | {'id': 'q1', 'family': 'family'}
    try:
        assert runner.execute(args, runner.ROOT / 'data/benchmark/v2', [item]) == 0
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert rows[-1] == {'type': 'run_complete', 'scenarios': 1}
        assert rows[1]['success'] and rows[1]['usage_complete']
        assert rows[1]['prompt_traces'][0]['model'] == 'same-model'
        reporter = importlib.import_module('report_ablation')
        report = reporter.build_report([output], iterations=50)
        assert report['summaries']['single/dev/F']['result_accuracy'] == 1.0
        with pytest.raises(FileExistsError):
            runner.execute(args, runner.ROOT / 'data/benchmark/v2', [item])
    finally:
        output.unlink(missing_ok=True)


def test_model_budget_stops_block_without_completing_log(runner, monkeypatch):
    from texa import llm
    output = Path(__file__).resolve().parents[2] / 'test-ablation-budget.jsonl'
    output.unlink(missing_ok=True)
    args = SimpleNamespace(variant='F', suite='single', split='dev', model='scripted', repeat=1,
        output=str(output), protocol=None, max_model_calls=1, turn_timeout=1, max_clarification_rounds=2)
    monkeypatch.setattr(runner, 'preflight', lambda *a: {})
    monkeypatch.setenv('TEXA_ABLATION_VARIANT', 'F')
    monkeypatch.setattr(llm, 'generate_structured', lambda **_: {})
    class Session(ScriptedSession):
        def __init__(self, *a):
            super().__init__([])
            self.api, self.turn_ids = SimpleNamespace(RUNS={}), set()
        def ask(self, question):
            for _ in range(2):
                llm.generate_structured(model='scripted', name='scripted', prompt=question)
        def usage(self):
            return {'calls': 1, 'input_tokens': 1, 'output_tokens': 1, 'model_ms': 1}
        def close(self):
            pass
    monkeypatch.setattr(runner, 'TexaSession', Session)
    try:
        with pytest.raises(runner.IncompleteRun):
            runner.execute(args, runner.ROOT / 'data/benchmark/v2', [expected() | {'id': 'q1'}])
        records = [json.loads(line) for line in output.read_text().splitlines()]
        assert records[-1]['type'] == 'scenario' and not records[-1]['success']
        assert records[-1]['answer_count'] == 1
        assert records[-1]['model_call_attempts'] == 1
    finally:
        output.unlink(missing_ok=True)


def test_source_metadata_hash_is_stable_across_python_hash_seeds(runner):
    backend = Path(__file__).resolve().parents[2] / 'backend'
    code = """import sys
sys.path.insert(0, 'eval')
from run_ablation import canonical_source_metadata, digest
from texa.catalog import Source
s=Source(id='x',label='x',description='',currency=None,min_date=None,max_date=None,row_count=0,user_count=0,
 events={'purchase','view','cart'},ep_keys={'device.type','campaign.channel'},up_keys={'region'},
 columns={'event_date','event_name','item_category'},value_vocab_fields={'item_category','device_type','region'})
print(digest(canonical_source_metadata(s)))
"""
    hashes = []
    for seed in ('3', '47', '811'):
        env = os.environ.copy()
        env['PYTHONHASHSEED'] = seed
        run = subprocess.run([sys.executable, '-c', code], cwd=backend, env=env,
                             capture_output=True, text=True, check=True)
        hashes.append(run.stdout.strip())
    assert len(set(hashes)) == 1
