from copy import deepcopy
import pytest
from texa import memory, llm
from tests.test_memory import answered


def proposal(target='a', relation='followup', **ops):
    return {'recipe': 'orders', 'metrics': [], 'filters': [], 'selection': ['event_month'],
            'time_range': {'kind': 'none'}, 'shape': 'time_trend', 'top_k': 3,
            'dialogue': {'relation': relation, 'target_id': target,
                         'slots': {k: ops.get(k, 'keep') for k in memory.SLOT_KEYS}}}


def test_reducer_preserves_target_slots_despite_model_overwriting_values():
    prior = answered('a', 'Revenue in December', filters=[{'field': 'category', 'operator': '=', 'values': ['x']}],
                     time_range={'kind': 'between', 'start': '2019-12-01', 'end': '2019-12-31'})
    out, ctx = memory.reduce_candidate(proposal(selection='set', shape='set', top_k='clear'), [prior], 3)
    assert out['recipe'] == 'revenue'
    assert out['filters'][0]['values_mentioned'] == ['x']
    assert out['time_range']['start'] == '2019-12-01'
    assert out['selection'] == ['event_month']
    assert out['top_k'] == 0
    assert ctx['references'] == ['a']


def test_clear_does_not_reintroduce_filters():
    prior = answered('a', 'old', filters=[{'field': 'device', 'values': ['mobile']}])
    out, _ = memory.reduce_candidate(proposal(filters='clear'), [prior], 3)
    assert out['filters'] == []


@pytest.mark.parametrize('history', [[], [answered('a', 'old', contract_version=2)], [answered('other', 'other chat')]])
def test_foreign_or_stale_pointer_cannot_inherit(history):
    _, ctx = memory.reduce_candidate(proposal(), history, 3)
    assert ctx['clarification_needed']
    assert ctx['inherited_slots'] == {}


def test_complete_registry_retains_distant_result_and_server_validates_selection():
    history = [answered(str(i), f'Question {i}') for i in range(14)]
    registry = memory.result_registry(history, 3)
    assert len(registry) == 14 and registry[1]['result_number'] == 2
    _, ctx = memory.reduce_candidate(proposal(target='1'), history, 3)
    assert ctx['references'] == ['1']


def test_independent_query_cannot_keep_old_slots():
    with pytest.raises(llm.LLMError):
        memory.reduce_candidate(proposal(target='', relation='new_topic'), [answered('a', 'old')], 3)


def test_reference_form_includes_complete_compatible_registry():
    from texa.answer import _reference_form
    history = [answered(str(i), f'Q{i}') for i in range(14)]
    form = _reference_form(history, {'references': ['13']})['form']
    assert len(form['fields'][0]['choices']) == 14


def test_followup_lineage_remains_one_topic_with_valid_active_id():
    first = answered('a', 'Revenue')
    second = answered('b', 'By month', selection=['month'])
    third = answered('c', 'Only mobile', selection=['month'], filters=[{'field': 'device', 'values': ['mobile']}])
    state = memory.apply_turn(None, first)
    state = memory.apply_turn(state, second, context={'relation': 'followup', 'references': ['a']})
    state = memory.apply_turn(state, third, context={'relation': 'followup', 'references': ['b']})
    assert len(state['topics']) == 1
    assert state['topics'][0]['result_ref'] == 'c'
    assert state['active_topic_id'] == state['topics'][0]['id']
    assert state['topics'][0]['slots']['recipe']['turn_id'] == 'a'


def test_registry_ordinals_do_not_shift_when_an_old_snapshot_is_ineligible():
    old = answered('old', 'old', contract_version=2)
    noise = {'id': 'noise', 'question': 'thanks', 'status': 'conversation', 'state': {}}
    good = answered('a', 'current')
    registry = memory.result_registry([good], 3, ordinal_history=[old, noise, good])
    assert registry[0]['question_number'] == 3
    assert registry[0]['result_number'] == 2


def test_forced_user_selection_cannot_be_dropped_as_social():
    with pytest.raises(llm.LLMError, match='explicitly selected reference'):
        memory.reduce_candidate(proposal(target='a', relation='social'), [answered('a', 'old')], 3, 'a')


def test_prompt_budget_never_changes_server_eligibility_and_cannot_force_recent_guess():
    history = [answered(str(i), f'Revenue {i} ' + 'x' * 1500) for i in range(50)]
    registry = memory.result_registry(history, 3)
    view, complete = memory.bounded_registry(registry, 800)
    assert not complete and len(view) < len(registry)
    candidate = proposal(target='49') | {'_registry_complete': complete}
    _, ctx = memory.reduce_candidate(candidate, history, 3)
    assert ctx['clarification_needed']
    candidate = proposal(target='', relation='new_topic', **{k: 'set' for k in memory.SLOT_KEYS}) | {'_registry_complete': False}
    _, ctx = memory.reduce_candidate(candidate, history, 3)
    assert ctx['relation'] == 'new_topic' and not ctx['clarification_needed']
    candidate = proposal(target='0') | {'_registry_complete': False}
    _, ctx = memory.reduce_candidate(candidate, history, 3, '0')
    assert ctx['references'] == ['0'] and not ctx['clarification_needed']
