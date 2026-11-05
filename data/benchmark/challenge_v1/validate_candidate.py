"""Structural checks for the candidate bank; does not validate business intent or human review."""
from collections import Counter, defaultdict
from pathlib import Path
import yaml

ROOT=Path(__file__).parent
cases=yaml.safe_load((ROOT/'cases.yaml').read_text())
interactions=yaml.safe_load((ROOT/'interactions.yaml').read_text())
dialogues=yaml.safe_load((ROOT/'dialogues.yaml').read_text())
manifest=yaml.safe_load((ROOT/'manifest.yaml').read_text())
assert manifest['dataset_type']=='challenge_candidate'
assert manifest['status']=='candidate_agent_reviewed_not_sealed'
ids=[x['id'] for x in cases+interactions+dialogues]
assert len(ids)==len(set(ids)), 'duplicate IDs'
answers=[x for x in cases if x.get('gold_sql')]
diagnostics=[x for x in cases if x.get('split')=='diagnostic']
assert len(answers)==manifest['counts']['single_total']==60
assert len(diagnostics)==manifest['counts']['diagnostics']==12
assert sum(x['suite'] if 'suite' in x else 0 for x in [])==0
for item in answers:
    assert item.get('expected_result') is not None, item['id']
    assert item.get('fixture_world','base') in manifest['fixture_worlds'], item['id']
    assert item['source_id'] in manifest['sources']
    assert item.get('stratum') in ('core_control','semantic_data_shape','composed_in_scope')
assert Counter(x['split'] for x in answers)==Counter({'dev':30,'test':30})
assert Counter(x['stratum'] for x in answers)==Counter({'core_control':8,'semantic_data_shape':24,'composed_in_scope':28})
families=defaultdict(set)
for item in answers: families[item['family']].add(item['split'])
assert all(len(s)==1 for s in families.values()), 'single family leakage across splits'
assert len(interactions)==manifest['counts']['clarification_total']
assert len(dialogues)==manifest['counts']['conversation_total']
for scenario in interactions:
    if scenario.get('gold_sql'):
        assert scenario.get('expected_result') is not None
    assert scenario['split'] in ('dev','test')
for dialogue in dialogues:
    assert dialogue['split'] in ('dev','test')
    assert any(t.get('action')=='answer' and t.get('gold_sql') for t in dialogue['turns'])
for world in manifest['fixture_worlds'].values():
    assert (ROOT/world['file']).exists()
print({'singles':len(answers),'diagnostics':len(diagnostics),'clarification':len(interactions),'dialogues':len(dialogues),'families':len(families)})
