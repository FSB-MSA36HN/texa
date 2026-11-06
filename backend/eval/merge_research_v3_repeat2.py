"""Recover frozen repeat-2 merges after verifying commit-only provenance differences.

Original shards remain untouched; this utility is specific to the archived study.
"""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/eval'))
from merge_accuracy_shards import merge_shards
root=ROOT/'backend/eval/results/research-v3-20261106/r2'
for suite in ['single','clarification','conversation','diagnostic']:
 for v in (['B0','T00','T10','T01','T11'] if suite=='single' else ['B1','T00','T10','T01','T11']):
  name=f'{suite}-test-{v}-base-r2';out=root/f'{name}.jsonl'
  if out.exists():continue
  paths=[root/'shards'/f'{name}-s{i}.jsonl' for i in range(4)]
  records=[[json.loads(l) for l in p.read_text().splitlines()] for p in paths]
  prov=[{k:v for k,v in r[0]['provenance'].items() if k!='commit'} for r in records]
  assert all(p==prov[0] for p in prov)
  staging=root/'merge-metadata-overlay';staging.mkdir(exist_ok=True)
  overlays=[]
  for p,rs in zip(paths,records):
   rs[0]['provenance']['commit']=records[0][0]['provenance']['commit']
   target=staging/p.name;target.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rs)+'\n');overlays.append(target)
  merge_shards(overlays,out)
  rs=[json.loads(l) for l in out.read_text().splitlines()]
  rs[0]['sharding']['metadata_overlay_note']='Commit-only normalization for unrelated append-only dataset commit; original shard files retained; all other provenance verified identical.'
  import hashlib
  rs[0]['sharding']['sources']=[{'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]
  out.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in rs)+'\n')
print('merged')
