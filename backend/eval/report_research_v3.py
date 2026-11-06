"""Summarize the frozen 2026-11-06 research study without altering raw traces."""
from pathlib import Path
from collections import Counter, defaultdict
import hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'backend'),str(ROOT/'backend/eval')]
from report_accuracy_study import read_run, compare
import yaml
source=ROOT/'backend/eval/results/research-v3-20261106'
dest=ROOT/'data/benchmark/results/research-v3-20261106'
dest.mkdir(parents=True,exist_ok=True)
data=ROOT/'data/benchmark/research_v3'
cases={c['id']:c for c in yaml.safe_load((data/'cases.yaml').read_text())}
summary={}; incomplete=[]
for suite in ['single','clarification','conversation','diagnostic']:
    runs=[]
    for p in sorted(source.glob(f'r[123]/{suite}-*.jsonl')):
        try:run=read_run(p)
        except ValueError:incomplete.append(str(p.relative_to(ROOT)));continue
        runs.append(run)
        target=dest/p.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    if not runs:continue
    # Only unrelated append-only dataset commits changed HEAD during execution.
    # Pin comparison commit after asserting all actual study-input hashes identical.
    shared_inputs=[{k:v for k,v in run['manifest']['provenance'].items() if k not in {'commit','feature_config','public_context_hash'}} for run in runs]
    if any(x!=shared_inputs[0] for x in shared_inputs): raise ValueError('Actual frozen study input changed')
    original_commits=sorted({run['manifest']['provenance']['commit'] for run in runs})
    for run in runs: run['manifest']['provenance']['commit']='8fbdcef-study-input-hashes-verified'
    result=compare(runs)
    result['commit_metadata_overlay']={'original_commits':original_commits,'reason':'Unrelated append-only clarification dataset commit changed HEAD; all runtime/evaluator/catalog/bank/active-dataset hashes verified identical. Raw records unchanged.'}
    result['detail_by_variant']={}
    for variant in sorted({r['manifest']['variant'] for r in runs}):
        vs=[r for r in runs if r['manifest']['variant']==variant]
        rows=[row for run in vs for row in run['rows']]
        counts=Counter(); by_group=defaultdict(lambda:Counter()); by_source=defaultdict(lambda:Counter())
        for row in rows:
            counts['scenarios']+=1;counts['legacy_scenario_success']+=bool(row.get('success'))
            if suite=='conversation':
                counts['all_answer_tables_correct']+=row.get('answer_count',0)>0 and row.get('answer_count')==row.get('answer_correct')
                turns=row.get('turns',[])
                action_ok=all(t.get('actual_action') in ({'answer','sql'} if t.get('expected_action') in {'answer','sql',None} else {'conversation'} if t.get('expected_action') in {'social','conversation'} else {t.get('expected_action')}) for t in turns)
                counts['observable_table_and_action_success']+=bool(action_ok and row.get('answer_count',0)>0 and row.get('answer_count')==row.get('answer_correct'))
            counts['answer_slots']+=row.get('answer_count',0);counts['answers_correct']+=row.get('answer_correct',0)
            counts['policy_scorable']+=row.get('clarification_policy_correct') is not None
            counts['policy_correct']+=bool(row.get('clarification_policy_correct'))
            for k,v in row.get('clarification_counts',{}).items():counts['clarification_'+k]+=v
            if suite=='single':
                c=cases[row['id']]
                for out,key in [(by_group,c['stratum']),(by_source,c['source_id'])]:
                    out[key]['total']+=1;out[key]['correct']+=bool(row.get('business_result_correct'))
        result['detail_by_variant'][variant]={'completed_repeats':sorted({r['manifest']['repeat'] for r in vs}),
            'counts':dict(counts),'by_stratum':dict(by_group),'by_source':dict(by_source),
            'failed_scenario_ids':sorted({r['id'] for r in rows if not r.get('success')})}
    (dest/f'{suite}-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
    summary[suite]=result
budget=json.loads((ROOT/'.runtime/gateway-cost-ledger.json').read_text())
summary['budget']={k:budget[k] for k in ['model','max_usd','spent_estimated_usd','reserved_usd','calls','input_tokens','output_tokens']}
summary['incomplete_runs_excluded']=incomplete
summary['clarification_annotation_issue']='Original metric-ambiguity customer cases conflict with the users synonym contract; do not headline original 60-case clarification accuracy. Replacement is independently frozen and rerun in research_v3_clarification_revision1.'
summary['dataset_commit']='83d008d'
summary['execution_commit']='8fbdcef'
summary['conversation_rubric_note']='Observable table-and-action success recomputed from immutable traces; legacy success additionally penalizes implicit references missing authored reference labels and is reported separately.'
summary['review_status']='agent-authored synthetic candidate; human review pending; shared dev/test families'
(dest/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str)+'\n')
print(json.dumps({s:{v:d['counts'] for v,d in report.get('detail_by_variant',{}).items()} for s,report in summary.items() if isinstance(report,dict) and 'detail_by_variant'in report},indent=2))
