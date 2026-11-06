"""Archive corrected clarification and source shards for the frozen research study."""
from pathlib import Path
import json,sys,shutil
root=Path(__file__).resolve().parents[2];sys.path[:0]=[str(root/'backend/eval'),str(root/'backend')]
from report_accuracy_study import read_run,compare
src=root/'backend/eval/results/research-v3-clarification-revision1';dest=root/'data/benchmark/results/research-v3-20261106'
runs=[]
for p in sorted(src.glob('r[12]/clarification-*.jsonl')):
 run=read_run(p);runs.append(run);target=dest/'clarification-revision1'/p.relative_to(src);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
assert len(runs)==10
result=compare(runs)
result['policy_by_variant']={}
for v in result['variants']:
 rows=[r for run in runs if run['manifest']['variant']==v for r in run['rows']]
 result['policy_by_variant'][v]={'correct':sum(bool(r.get('clarification_policy_correct')) for r in rows),'total':len(rows),'table_correct':sum(r.get('answer_correct',0) for r in rows),'answer_slots':sum(r.get('answer_count',0) for r in rows)}
(dest/'clarification-revision1-summary.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
summary=json.loads((dest/'summary.json').read_text());summary['clarification_revised']=result
b=json.loads((root/'.runtime/gateway-cost-ledger.json').read_text());summary['budget']={k:b[k] for k in ['model','max_usd','spent_estimated_usd','reserved_usd','calls','input_tokens','output_tokens']}
(dest/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
# Preserve complete original shards with byte hashes referenced by merged runs.
for name,source in [('research-v3',root/'backend/eval/results/research-v3-20261106'),('clarification-revision1',src)]:
 for p in source.glob('r[12]/shards/*.jsonl'):
  target=dest/'audit-shards'/name/p.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
print(json.dumps(result['policy_by_variant'],indent=2));print(summary['budget'])
