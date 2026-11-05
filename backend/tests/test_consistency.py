from contextvars import ContextVar
from copy import deepcopy
import threading

import pytest
from texa import consistency, llm
from texa.progress import Cancelled


def proposal(value=1):
    return {"value": value, "language": "en"}


def normalize(p):
    if p['value'] == 'bad':
        raise llm.LLMError('MODEL_OUTPUT_INVALID', 'bad')
    return {"kind": "spec", "spec": {"recipe": "revenue", "selection": ["event_month"],
            "filters": [{"field": "a", "values": [p['value']]}, {"field": "b", "values": [2]}]}}


def test_two_independent_valid_votes_select_whole_proposal_and_propagate_context():
    observer = ContextVar('test_observer', default=None)
    observer.set('bound')
    lock = threading.Lock()
    seen = []
    def sample():
        with lock:
            seen.append(observer.get())
        return proposal(2)
    original = proposal(1)
    selected, trace = consistency.select(original, sample, normalize)
    assert selected == proposal(2) and original == proposal(1)
    assert trace['scheduled'] == 3 and trace['vote_counts'] == [2, 1]
    assert seen == ['bound', 'bound']


def test_one_valid_and_two_invalid_is_not_majority():
    selected, trace = consistency.select(proposal(), lambda: proposal('bad'), normalize)
    assert selected['outcome'] == 'unsupported'
    assert trace['selected'] is None and trace['errors'] == 2


def test_missing_information_never_triggers_extra_samples():
    def forbidden():
        pytest.fail('Must not sample missing user information')
    selected, trace = consistency.select(proposal(), forbidden, lambda p: {'kind': 'clarify'})
    assert selected == proposal() and trace['scheduled'] == 1


def test_cancelled_request_cannot_select_candidate():
    with pytest.raises(Cancelled):
        consistency.select(proposal(), lambda: proposal(), normalize, cancelled=lambda: True)


def test_fingerprint_preserves_types_null_dimension_order_and_slot_operations():
    a = normalize(proposal())
    b = deepcopy(a)
    b['spec']['filters'].reverse()
    assert consistency.fingerprint(a) == consistency.fingerprint(b)
    b['spec']['filters'][1]['values'] = ['1']
    assert consistency.fingerprint(a) != consistency.fingerprint(b)
    b = deepcopy(a); b['dialogue'] = {'slots': {'filters': 'clear'}}
    assert consistency.fingerprint(a) != consistency.fingerprint(b)
    b = deepcopy(a); b['spec']['filters'][0]['values'] = [None]
    assert consistency.fingerprint(a) != consistency.fingerprint(b)


def test_expansion_capacity_returns_primary_without_extra_calls():
    assert consistency._EXPANSION.acquire(blocking=False)
    try:
        result, trace = consistency.select(proposal(), lambda: pytest.fail('busy'), normalize)
        assert result == proposal() and trace['fallback'] == 'sampling_capacity'
    finally:
        consistency._EXPANSION.release()


def test_timeout_keeps_sampling_lease_until_late_calls_exit_and_does_not_select():
    release = threading.Event()
    entered = threading.Event()
    exited = threading.Event()
    def slow():
        entered.set()
        release.wait(2)
        return proposal(2)
    selected, trace = consistency.select(proposal(), slow, normalize, timeout=0.02)
    assert entered.is_set() and trace['fallback'] == 'no_semantic_majority'
    assert not consistency._EXPANSION.acquire(blocking=False)
    release.set()
    # Queue a barrier after both worker calls; polling checks only local completion.
    consistency._POOL.submit(lambda: exited.set()).result(timeout=2)
    import time
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if consistency._EXPANSION.acquire(blocking=False):
            consistency._EXPANSION.release()
            break
        time.sleep(0.001)
    else:
        pytest.fail('Sampling lease leaked after late requests settled')


def test_budget_failure_is_propagated_and_not_disguised_as_disagreement():
    def exhausted():
        raise llm.LLMError('BUDGET_EXHAUSTED', 'Budget exhausted')
    with pytest.raises(llm.LLMError, match='Budget exhausted'):
        consistency.select(proposal(), exhausted, normalize)
    assert consistency._EXPANSION.acquire(blocking=False)
    consistency._EXPANSION.release()


def test_invalid_primary_still_requires_two_valid_agreeing_replacements():
    selected, trace = consistency.select({'language': 'en'}, lambda: proposal(2), normalize,
                                         primary_error='MODEL_OUTPUT_INVALID')
    assert selected == proposal(2) and trace['vote_counts'] == [2] and trace['errors'] == 1


def test_supported_refusal_is_not_counted_as_query_vote():
    def resolve(p):
        if p.get('outcome') == 'unsupported':
            return {'kind': 'unsupported', 'supported_proposal': normalize(proposal(2))}
        return normalize(p)
    selected, trace = consistency.select({'outcome': 'unsupported'}, lambda: proposal(2), resolve)
    assert selected == proposal(2)
    assert trace['trigger'] == 'catalog_supported_refusal' and trace['vote_counts'] == [2]
