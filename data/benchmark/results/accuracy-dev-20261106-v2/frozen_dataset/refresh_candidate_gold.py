"""Run independently written gold SQL against challenge worlds and store literal result tables."""
import argparse
import csv
import io
import re
import subprocess
from pathlib import Path
import yaml

ROOT=Path(__file__).parent
def scalar(s):
    if s == r'\N': return None
    if re.fullmatch(r'-?\d+',s): return int(s)
    if re.fullmatch(r'-?\d+\.\d+',s): return float(s)
    return s

def psql(dsn,sql):
    return subprocess.run(['psql',dsn,'-X','--csv','-P',r'null=\N','-v','ON_ERROR_STOP=1','-c',sql],check=True,text=True,capture_output=True).stdout

def result(dsn,sql,case_id):
    text=psql(dsn,sql)
    parsed=list(csv.reader(io.StringIO(text)))
    if not parsed: raise ValueError(f"no output for {case_id}")
    return {'columns':parsed[0], 'rows':[[scalar(v) for v in row] for row in parsed[1:]]}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dsn',required=True); ap.add_argument('--write',action='store_true'); args=ap.parse_args()
    cases=yaml.safe_load((ROOT/'cases.yaml').read_text())
    interaction=yaml.safe_load((ROOT/'interactions.yaml').read_text())
    dialogue=yaml.safe_load((ROOT/'dialogues.yaml').read_text())
    worlds=['base','grain_counterexample','coverage_edge']
    world_results={c['id']:{} for c in cases if c.get('gold_sql')}
    for world in worlds:
        group=[c for c in cases if c.get('gold_sql')]
        extra=[]
        if world=='base':
            extra.extend((scenario,'gold_sql') for scenario in interaction if scenario.get('gold_sql'))
            extra.extend((turn,'gold_sql') for scenario in dialogue for turn in scenario.get('turns',[]) if turn.get('gold_sql'))
        if not group and not extra: continue
        subprocess.run(['psql',args.dsn,'-X','-v','ON_ERROR_STOP=1','-f',str(ROOT/'worlds'/f'{world}.sql')],check=True,stdout=subprocess.DEVNULL)
        for c in group:
            world_results[c['id']][world]=result(args.dsn,c['gold_sql'],c['id'])
        for c,key in extra:
            c['expected_result']=result(args.dsn,c[key],c.get('id',c.get('question')))
    for c in cases:
        if not c.get('gold_sql'): continue
        c['expected_results_by_world']=world_results[c['id']]
        c['expected_result']=world_results[c['id']].get(c.get('fixture_world','base'),world_results[c['id']]['base'])
    print(f"Executed {sum(len(x) for x in world_results.values())} handwritten single-case SQL/world pairs")
    if args.write:
        (ROOT/'cases.yaml').write_text(yaml.safe_dump(cases,sort_keys=False,allow_unicode=True,width=110))
        (ROOT/'interactions.yaml').write_text(yaml.safe_dump(interaction,sort_keys=False,allow_unicode=True,width=110))
        (ROOT/'dialogues.yaml').write_text(yaml.safe_dump(dialogue,sort_keys=False,allow_unicode=True,width=110))
if __name__=='__main__': main()
