"""Verify independent literal gold against PostgreSQL in the isolated benchmark DB."""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import psycopg
import yaml
from benchmark import results_equal

ROOT = Path(__file__).resolve().parents[2]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dataset-dir', type=Path, default=ROOT/'data/benchmark/research_v3')
    ap.add_argument('--owner-dsn', default=os.environ.get('TEXA_DB_DSN'), required=not os.environ.get('TEXA_DB_DSN'))
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    directory = args.dataset_dir.resolve()
    directory.relative_to(ROOT)
    manifest = yaml.safe_load((directory/'manifest.yaml').read_text())
    files = ['cases.yaml', 'interactions.yaml', 'dialogues.yaml', 'unsupported.yaml']
    suites = {f: yaml.safe_load((directory/f).read_text()) for f in files}
    singles = suites['cases.yaml']
    assert Counter(c['split'] for c in singles) == {'dev':100, 'test':200}
    assert Counter(c['stratum'] for c in singles if c['split']=='test') == {'basic':40, 'compositional':100, 'semantic':60}
    assert len(suites['interactions.yaml']) == 60
    assert Counter(bool(c['ask_fields']) for c in suites['interactions.yaml']) == {True:30, False:30}
    assert len(suites['dialogues.yaml']) == 40
    assert all(6 <= len(c['turns']) <= 12 for c in suites['dialogues.yaml'])
    assert len(suites['unsupported.yaml']) == 40
    all_cases = [c for rows in suites.values() for c in rows]
    assert len({c['id'] for c in all_cases}) == len(all_cases)
    assert len({c['question'] for c in singles}) == 300
    assert len({c['gold_sql'] for c in singles}) == 300
    assert all(c.get('ui_scope') == [c['source_id']] for c in singles)
    targets = [(c['id'], t) for c in all_cases for t in c.get('turns', [c]) if t.get('gold_sql')]
    errors = []; checked = 0
    with psycopg.connect(args.owner_dsn, autocommit=True) as conn:
        if conn.execute('select current_database()').fetchone()[0] != 'texa_benchmark':
            raise ValueError('Refusing fixture writes outside texa_benchmark')
        for world, spec in manifest['fixture_worlds'].items():
            fixture = (directory/spec['file']).resolve()
            fixture.relative_to(directory)
            conn.execute(fixture.read_text())
            for ident, target in targets:
                expected = target.get('expected_results_by_world', {}).get(world)
                if expected is None:
                    raise ValueError(f'{ident}: missing independent gold for {world}')
                try:
                    with conn.transaction():
                        conn.execute('SET TRANSACTION READ ONLY')
                        conn.execute("SET LOCAL statement_timeout = '5s'")
                        cur = conn.execute(target['gold_sql'])
                        columns = [c.name for c in cur.description]
                        rows = [list(row) for row in cur.fetchall()]
                    if not results_equal(columns, rows, expected['columns'], expected['rows'], ordered=bool(target.get('ordered'))):
                        errors.append({'id':ident, 'world':world, 'question':target.get('question'), 'actual':rows, 'expected':expected['rows']})
                except Exception as exc:
                    errors.append({'id':ident, 'world':world, 'error_type':type(exc).__name__, 'error':str(exc)[:200]})
                checked += 1
        conn.execute((directory/manifest['fixture_worlds']['base']['file']).read_text())
    result = {'gold_sql_world_checks':checked, 'errors':errors, 'single_count':len(singles),
              'clarification_count':60, 'conversation_count':40,
              'conversation_turns':sum(len(c['turns']) for c in suites['dialogues.yaml']),
              'conversation_answer_slots':sum('gold_sql' in t for c in suites['dialogues.yaml'] for t in c['turns']),
              'unsupported_count':40, 'human_review':'pending', 'sealed':False}
    if args.output: args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
    print(json.dumps({**result, 'errors':errors[:8]}, ensure_ascii=False,default=str))
    return bool(errors)

if __name__ == '__main__': raise SystemExit(main())
