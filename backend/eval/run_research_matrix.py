"""Run one frozen benchmark repeat on an isolated native PostgreSQL instance.

Uses the protected cumulative gateway budget; stops the database on exit.
Run each repeat with a distinct --output directory and --repeat number.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml
from merge_accuracy_shards import merge_shards

ROOT=Path(__file__).resolve().parents[2]
PYTHON=ROOT/'backend/.venv/bin/python'
PGCTL=ROOT/'.runtime/pgtools/pgserver/pginstall/bin/pg_ctl'
PGDATA=ROOT/'.runtime/pgdata'
DSN='postgresql://postgres@127.0.0.1:15433/texa_benchmark'
DATA=ROOT/'data/benchmark/research_v3'
ap=argparse.ArgumentParser()
ap.add_argument('--output',required=True,type=Path)
ap.add_argument('--dataset-dir',type=Path,default=DATA)
ap.add_argument('--suites',nargs='+',default=['single','clarification','conversation','diagnostic'])
ap.add_argument('--variants',nargs='+',default=['B0','B1','T00','T10','T01','T11'])
ap.add_argument('--split',default='test',choices=['dev','test','diagnostic'])
ap.add_argument('--repeat',type=int,default=1)
ap.add_argument('--workers',type=int,default=8,choices=range(1,25))
ap.add_argument('--shards',type=int,default=4,choices=range(1,17))
a=ap.parse_args()
DATA=a.dataset_dir.resolve();DATA.relative_to(ROOT)
out=a.output.resolve();out.relative_to(ROOT);out.mkdir(parents=True,exist_ok=True)
baseenv=os.environ|{'PYTHONPATH':str(ROOT/'backend'), 'TEXA_DB_DSN':DSN,'TEXA_READER_DSN':'postgresql://texa_reader:texa_reader@127.0.0.1:15433/texa_benchmark','TEXA_BENCHMARK_DSN':'postgresql://texa_reader:texa_reader@127.0.0.1:15433/texa_benchmark','TEXA_LLM_MAX_INFLIGHT':'2'}
def cmd(argv,**kw):
 return subprocess.run([str(x) for x in argv],cwd=ROOT,env=baseenv,check=True,**kw)
if subprocess.run([str(PGCTL),'-D',str(PGDATA),'status'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:
 raise RuntimeError('Native PostgreSQL already owned by another process; leave it untouched')
started=False
try:
 cmd([PGCTL,'-D',PGDATA,'-l',ROOT/'.runtime/pg-study.log','-o',f'-h 127.0.0.1 -p 15433 -k {ROOT}/.runtime -c shared_buffers=64MB -c max_connections=128','start','-w','-t','15'],stdout=subprocess.DEVNULL)
 started=True
 cmd([PYTHON,'-c','from texa import db; db.migrate()'])
 for world in ['base','grain_counterexample','coverage_edge']:
  jobs=[]
  for suite in a.suites:
   filename={'single':'cases.yaml','clarification':'interactions.yaml','conversation':'dialogues.yaml','diagnostic':'cases.yaml'}[suite]
   if suite=='diagnostic' and (DATA/'unsupported.yaml').exists(): filename='unsupported.yaml'
   rows=yaml.safe_load((DATA/filename).read_text())
   if any(x.get('split')==a.split and x.get('fixture_world','base')==world for x in rows):
    for variant in a.variants:
     if suite!='single' and variant in {'B0','B0R'}:continue
     if suite=='single' and variant=='B1':continue
     for shard in range(a.shards):jobs.append((suite,variant,shard))
  if not jobs:continue
  jobs.sort(key=lambda job: {'conversation':0,'single':1,'clarification':2,'diagnostic':3}[job[0]])
  shift=(a.repeat-1)%len(jobs)
  jobs=jobs[shift:]+jobs[:shift]
  cmd(['psql',DSN,'-X','-v','ON_ERROR_STOP=1','-f',DATA/'worlds'/f'{world}.sql'],stdout=subprocess.DEVNULL)
  cmd([PYTHON,'-c','from texa import catalog; print("published", catalog.publish())'])
  def run(job):
   suite,variant,shard=job
   name=f'{suite}-{a.split}-{variant}-{world}-r{a.repeat}'
   target=out/'shards'/f'{name}-s{shard}.jsonl'
   target.parent.mkdir(exist_ok=True)
   if target.exists():
    records=[json.loads(line) for line in target.read_text().splitlines() if line.strip()]
    if records and records[-1].get('type')=='run_complete': return name+' (retained complete)'
    archive=out/'interrupted';archive.mkdir(exist_ok=True)
    target.rename(archive/f'{name}-s{shard}-{time.time_ns()}.partial.jsonl')
   log=ROOT/'.runtime'/f'{out.name}-{name}-s{shard}.log'
   with log.open('w') as h:
    cmd([PYTHON,ROOT/'backend/eval/run_gateway_check.py','--credentials',ROOT/'.runtime/class-demo-gateway.json','--runner','accuracy','--dataset-dir',DATA,'--suite',suite,'--split',a.split,'--variant',variant,'--world',world,'--repeat',a.repeat,'--shard-index',shard,'--shard-count',a.shards,'--execute','--max-model-calls','10000','--output',target],stdout=h,stderr=subprocess.STDOUT)
   return name+f'-s{shard}'
  with ThreadPoolExecutor(max_workers=a.workers) as executor:
   futures=[executor.submit(run,job) for job in jobs]
   for future in as_completed(futures):
    print(json.dumps({'completed':future.result(),'time':time.strftime('%H:%M:%S')}),flush=True)
  for suite,variant in sorted({(j[0],j[1]) for j in jobs}):
   name=f'{suite}-{a.split}-{variant}-{world}-r{a.repeat}'
   target=out/f'{name}.jsonl'
   if not target.exists():
    merge_shards([out/'shards'/f'{name}-s{i}.jsonl' for i in range(a.shards)],target)
 for suite in a.suites:
  paths=sorted(out.glob(f'{suite}-*.jsonl'))
  if paths:
   result=cmd([PYTHON,ROOT/'backend/eval/report_accuracy_study.py','--compare',*paths],capture_output=True,text=True)
   (out/f'{suite}-summary.json').write_text(result.stdout)
finally:
 if started:
  cmd([PGCTL,'-D',PGDATA,'stop','-m','fast','-w','-t','15'],stdout=subprocess.DEVNULL)
  print('Native PostgreSQL stopped',flush=True)
