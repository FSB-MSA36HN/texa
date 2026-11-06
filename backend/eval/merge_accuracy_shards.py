"""Merge only a complete, disjoint shard partition into one auditable accuracy run."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path
from report_accuracy_study import read_run


def merge_shards(paths: list[Path], output: Path) -> dict:
    runs = [read_run(path) for path in paths]
    if not runs: raise ValueError('No shard runs supplied')
    first = runs[0]['manifest']
    count = (first.get('shard') or {}).get('count', 1)
    indices = [(run['manifest'].get('shard') or {}).get('index', 0) for run in runs]
    if len(indices) != count or set(indices) != set(range(count)):
        raise ValueError('Every shard index must be present exactly once')
    ignored = {'expected_ids', 'expected_answer_counts', 'shard'}
    shared = {k:v for k,v in first.items() if k not in ignored}
    rows = {}; counts = {}
    for run in runs:
        manifest = run['manifest']
        if {k:v for k,v in manifest.items() if k not in ignored} != shared:
            raise ValueError('Shard metadata, provenance, or fixture differs')
        if (manifest.get('shard') or {}).get('count', 1) != count:
            raise ValueError('Shard counts differ')
        for row in run['rows']:
            if row['id'] in rows: raise ValueError('Overlapping scenario IDs in shards')
            rows[row['id']] = row
        counts.update(manifest['expected_answer_counts'])
    expected = first['world_pool_ids'][first['fixture_world']]
    if set(rows) != set(expected) or set(counts) != set(expected):
        raise ValueError('Shard union does not exactly cover frozen fixture-world pool')
    manifest = copy.deepcopy(first)
    manifest.pop('shard', None)
    manifest['expected_ids'] = expected
    manifest['expected_answer_counts'] = {key:counts[key] for key in expected}
    manifest['sharding'] = {'count':count, 'sources':[
        {'path':str(path), 'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as handle:
        for record in [manifest, *(rows[key] for key in expected), {'type':'run_complete', 'scenarios':len(rows)}]:
            handle.write(json.dumps(record, ensure_ascii=False, default=str)+'\n')
    read_run(output)
    return {'scenarios':len(rows), 'shards':count}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('inputs', nargs='+', type=Path)
    ap.add_argument('--output', required=True, type=Path)
    args=ap.parse_args()
    print(json.dumps(merge_shards(args.inputs,args.output)))

if __name__=='__main__':main()
