from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import yaml
from texa import interpret
from texa.catalog import validate_catalog, Source


def setup():
    cat = validate_catalog(yaml.safe_load((Path(__file__).resolve().parents[2] / 'catalog/product_events.yaml').read_text()))
    src = Source(id='olist_marketplace', label='Olist', description='', currency='BRL',
                 min_date='2020-01-01', max_date='2020-01-10', row_count=2, user_count=1,
                 events={'order_purchased'})
    return cat, {src.id: src}


def test_default_path_makes_one_model_call_and_no_bank_read(monkeypatch):
    monkeypatch.delenv('TEXA_EXAMPLE_RETRIEVAL', raising=False)
    monkeypatch.delenv('TEXA_CONSISTENCY', raising=False)
    calls = []
    monkeypatch.setattr(interpret.llm, 'generate_structured', lambda **kw: calls.append(kw) or {'outcome': 'query'})
    monkeypatch.setattr(interpret.examples, 'load_bank', lambda *a: (_ for _ in ()).throw(AssertionError('off')))
    cat, sources = setup()
    got = interpret.interpret('Revenue at Olist', [], cat, sources, model='model')
    assert len(calls) == 1 and not got['_accuracy']['retrieval']['enabled']


def test_examples_use_remaining_space_and_conflicting_scope_is_not_confirmed(monkeypatch):
    monkeypatch.setenv('TEXA_EXAMPLE_RETRIEVAL', '1')
    monkeypatch.setenv('TEXA_CONSISTENCY', '0')
    bank = SimpleNamespace(version='v1', content_hash='hash')
    seen = []
    monkeypatch.setattr(interpret.examples, 'load_bank', lambda cat: bank)
    def retrieve(bank, question, **kw):
        seen.append(kw)
        return SimpleNamespace(ids=['demo'], scores=[1.0], estimated_tokens=100)
    monkeypatch.setattr(interpret.examples, 'retrieve_examples', retrieve)
    monkeypatch.setattr(interpret.examples, 'render_examples', lambda result: 'DEMONSTRATION')
    calls = []
    monkeypatch.setattr(interpret.llm, 'generate_structured', lambda **kw: calls.append(kw) or {'outcome': 'query'})
    cat, sources = setup()
    got = interpret.interpret('Revenue at Olist', [], cat, sources, model='model', scope=['cosmetics_shop'])
    assert not seen[0]['confirmed_sources']
    assert seen[0]['token_budget'] <= 600
    assert 'DEMONSTRATION' in calls[0]['prompt']
    assert got['_accuracy']['retrieval']['ids'] == ['demo']


def test_consistency_samples_identical_context_and_passes_registry_marker(monkeypatch):
    monkeypatch.setenv('TEXA_EXAMPLE_RETRIEVAL', '0')
    monkeypatch.setenv('TEXA_CONSISTENCY', '1')
    calls = []
    def model(**kw):
        calls.append(kw)
        return {'outcome': 'query', 'language': 'en'}
    monkeypatch.setattr(interpret.llm, 'generate_structured', model)
    def normalize(candidate):
        assert candidate['_registry_complete'] is True
        return {'kind': 'spec', 'spec': {'filters': [{'field': 'a'}, {'field': 'b'}]}}
    cat, sources = setup()
    got = interpret.interpret('Revenue at Olist', [], cat, sources, model='model',
                              context={'structured_memory': True, 'registry': []}, normalize=normalize)
    assert len(calls) == 3 and len({c['prompt'] for c in calls}) == 1
    assert got['_accuracy']['consistency']['vote_counts'] == [3]
