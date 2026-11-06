import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'eval'))
from merge_accuracy_shards import merge_shards


def make_shard(tmp_path,index,ids=('a','b'),count=2,provenance=None):
    path=tmp_path/f'shard-{index}.jsonl'
    selected=list(ids)[index::count]
    manifest={'type':'run_manifest','variant':'T11','suite':'single','split':'test','repeat':1,
              'model':'test','fixture_world':'base','world_pool_ids':{'base':list(ids)},
              'expected_ids':selected,'expected_answer_counts':{key:1 for key in selected},
              'provenance':provenance or {'commit':'frozen'},'shard':{'index':index,'count':count}}
    rows=[manifest,*({'type':'scenario','id':key,'answer_count':1,'answer_correct':1} for key in selected),
          {'type':'run_complete','scenarios':len(selected)}]
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    return path


def test_merge_complete_partition_preserves_coverage_and_audit(tmp_path):
    paths=[make_shard(tmp_path,i) for i in range(2)]
    output=tmp_path/'merged.jsonl'
    assert merge_shards(paths,output)=={'scenarios':2,'shards':2}
    rows=[json.loads(line) for line in output.read_text().splitlines()]
    assert rows[0]['expected_ids']==['a','b']
    assert len(rows[0]['sharding']['sources'])==2
    assert [r['id'] for r in rows[1:-1]]==['a','b']


def test_merge_rejects_missing_or_duplicate_shard(tmp_path):
    path=make_shard(tmp_path,0)
    for paths in [[path],[path,path]]:
        with pytest.raises(ValueError,match='Every shard'):merge_shards(paths,tmp_path/'bad.jsonl')


def test_merge_rejects_provenance_drift(tmp_path):
    paths=[make_shard(tmp_path,0),make_shard(tmp_path,1,provenance={'commit':'changed'})]
    with pytest.raises(ValueError,match='provenance'):merge_shards(paths,tmp_path/'bad.jsonl')


def test_merge_rejects_overlapping_ids(tmp_path):
    paths=[make_shard(tmp_path,i) for i in range(2)]
    rows=[json.loads(line) for line in paths[1].read_text().splitlines()]
    rows[0]['expected_ids']=['a'];rows[0]['expected_answer_counts']={'a':1};rows[1]['id']='a'
    paths[1].write_text(''.join(json.dumps(row)+'\n' for row in rows))
    with pytest.raises(ValueError,match='Overlapping'):merge_shards(paths,tmp_path/'bad.jsonl')
