from copy import deepcopy
from texa import answer, suggestions
from texa.progress import Progress
from tests.test_units import CAT, SOURCES


def test_suggestions_are_valid_contracts_and_respect_selected_source():
    items = suggestions.suggestions(CAT, SOURCES, ['cosmetics_shop'], limit=100)
    assert items
    assert all(x['source_id'] == 'cosmetics_shop' for x in items)
    assert all(x['spec']['source_ids'] == ['cosmetics_shop'] for x in items)
    # Coverage must remove Olist-only metrics from cosmetics onboarding.
    assert not any(x['spec']['recipe'] == 'late_delivery_rate' for x in items)


def test_source_conflict_blocks_sql_until_explicit_choice(monkeypatch):
    monkeypatch.setattr(answer.llm, 'get_connection', lambda: {'answer_language': 'auto'})
    monkeypatch.setattr(answer.catalog_mod, 'scoped_sources', lambda _cat, sources: sources)
    monkeypatch.setattr(answer, 'run_spec', lambda *_: (_ for _ in ()).throw(AssertionError('SQL must not run')))
    turn = {'id': 'current', 'question': 'Revenue Cosmetics', 'state': {'scope': ['olist_marketplace']}}
    candidate = {'source_ids': ['cosmetics_shop'], 'language': 'en'}
    result = answer._continue(turn, candidate, {}, Progress(), CAT, SOURCES)
    assert result['status'] == 'needs_clarification'
    assert result['source_resolution']['effective'] is None
    assert {c['id'] for c in result['form']['fields'][0]['choices']} == set(SOURCES)


def test_source_resolution_keeps_ui_text_provenance(monkeypatch):
    monkeypatch.setattr(answer.llm, 'get_connection', lambda: {'answer_language': 'auto'})
    monkeypatch.setattr(answer.catalog_mod, 'scoped_sources', lambda _cat, sources: sources)
    seen = []
    from texa.clarify import Outcome
    def advance(candidate, answers, cat, sources, **kwargs):
        seen.append((candidate, kwargs['scope']))
        return Outcome(kind='refuse', message='fixture')
    monkeypatch.setattr(answer.clarify, 'advance', advance)
    turn = {'id': 'current', 'question': 'Revenue Cosmetics', 'state': {'scope': ['olist_marketplace']}}
    answer._continue(turn, {'source_ids': ['cosmetics_shop'], 'language': 'en'},
                     {'context:source': ['cosmetics_shop']}, Progress(), CAT, SOURCES)
    assert seen[0][0]['source_ids'] == ['cosmetics_shop']
    assert seen[0][1] == ['cosmetics_shop']


def test_ui_scope_conflicting_with_referenced_result_must_not_silently_switch_source(monkeypatch):
    monkeypatch.setattr(answer.llm, 'get_connection', lambda: {'answer_language': 'auto'})
    monkeypatch.setattr(answer.catalog_mod, 'scoped_sources', lambda _cat, sources: sources)
    turn = {'id': 'current', 'question': 'Break down that earlier result', 'state': {'scope': ['olist_marketplace']}}
    candidate = {'source_ids': ['cosmetics_shop'], 'language': 'en', 'dialogue': {'slots': {'source_ids': 'keep'}}}
    result = answer._continue(turn, candidate, {}, Progress(), CAT, SOURCES)
    assert result['status'] == 'needs_clarification'
    assert result['source_resolution'] == {'ui': ['olist_marketplace'], 'text': [],
                                           'memory': ['cosmetics_shop'], 'effective': None}


def test_literal_source_conflict_is_detected_even_when_model_omits_source(monkeypatch):
    monkeypatch.setattr(answer.llm, 'get_connection', lambda: {'answer_language': 'auto'})
    monkeypatch.setattr(answer.catalog_mod, 'scoped_sources', lambda _cat, sources: sources)
    turn = {'id': 'current', 'question': 'Revenue Cosmetics shop', 'state': {'scope': ['olist_marketplace']}}
    result = answer._continue(turn, {'source_ids': [], 'language': 'en'}, {}, Progress(), CAT, SOURCES)
    assert result['status'] == 'needs_clarification'
    assert result['source_resolution']['text'] == ['cosmetics_shop']


def test_multiple_known_mentions_require_a_choice_without_ui_scope(monkeypatch):
    monkeypatch.setattr(answer.llm, 'get_connection', lambda: {'answer_language': 'auto'})
    monkeypatch.setattr(answer.catalog_mod, 'scoped_sources', lambda _cat, sources: sources)
    cat = deepcopy(CAT)
    cat.policy.max_sources = 1
    turn = {'id': 'current', 'question': 'Compare Cosmetics shop and Olist', 'state': {'scope': []}}
    result = answer._continue(turn, {'source_ids': ['cosmetics_shop'], 'language': 'en'}, {}, Progress(), cat, SOURCES)
    assert result['status'] == 'needs_clarification'
    assert result['source_resolution']['effective'] is None
