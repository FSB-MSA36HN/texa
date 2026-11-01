"""Validate a frozen dataset's annotations and split integrity without model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import yaml

from benchmark import load_cases, validate_split_is_family_disjoint


def validate_dataset(directory: Path) -> dict:
    cases = load_cases(directory / 'cases.yaml')
    dialogues = yaml.safe_load((directory / 'dialogues.yaml').read_text())
    validate_split_is_family_disjoint(cases)
    ids: set[str] = set()
    questions: set[str] = set()
    queries: dict[str, str] = {}
    actions: dict[str, int] = {}
    answer_turns = 0

    def check_result(item, label):
        result = item.get('expected_result')
        if not item.get('gold_sql') or not isinstance(result, dict):
            raise ValueError(f'{label}: SQL and literal expected_result required')
        columns, rows = result.get('columns'), result.get('rows')
        if not isinstance(columns, list) or not columns or len(set(columns)) != len(columns):
            raise ValueError(f'{label}: invalid columns')
        if not isinstance(rows, list) or any(not isinstance(r, list) or len(r) != len(columns) for r in rows):
            raise ValueError(f'{label}: invalid result rows')

    for case in cases:
        label = case['id']
        if label in ids:
            raise ValueError(f'duplicate ID {label}')
        ids.add(label)
        question = ' '.join(case['question'].lower().split())
        if question in questions:
            raise ValueError(f'{label}: duplicate single-turn question')
        questions.add(question)
        normalized = ' '.join(case['gold_sql'].lower().split()).rstrip(';')
        if normalized in queries and queries[normalized] != case['split']:
            raise ValueError(f'{label}: identical SQL crosses split')
        queries[normalized] = case['split']
        check_result(case, label)

    families: dict[str, str] = {}
    for dialogue in dialogues:
        label = dialogue['id']
        if label in ids or dialogue.get('split') not in {'dev', 'test'}:
            raise ValueError(f'{label}: invalid ID/split')
        ids.add(label)
        family = dialogue.get('family')
        if not family:
            raise ValueError(f'{label}: dialogue family required')
        if family in families and families[family] != dialogue['split']:
            raise ValueError(f'{label}: dialogue family crosses split')
        families[family] = dialogue['split']
        turns = dialogue['turns']
        for number, turn in enumerate(turns, 1):
            action = turn.get('action')
            if action not in {'answer', 'clarify', 'clarification_answer', 'refuse', 'conversation'}:
                raise ValueError(f'{label}/{number}: invalid action')
            actions[action] = actions.get(action, 0) + 1
            reference = turn.get('referenced_turn')
            if reference is not None and (not isinstance(reference, int) or not 1 <= reference < number):
                raise ValueError(f'{label}/{number}: reference must point to earlier turn')
            if action in {'answer', 'clarification_answer'}:
                check_result(turn, f'{label}/{number}')
                answer_turns += 1
            if action == 'clarify' and not turn.get('ask_fields'):
                raise ValueError(f'{label}/{number}: missing ask_fields')
            if action == 'clarification_answer':
                if number == 1 or turns[number - 2]['action'] != 'clarify':
                    raise ValueError(f'{label}/{number}: clarification answer without prior clarify')
                if set(turn.get('oracle_answers', {})) != set(turns[number - 2]['ask_fields']):
                    raise ValueError(f'{label}/{number}: oracle fields mismatch')
    files = ['fixture.sql', 'cases.yaml', 'dialogues.yaml', 'manifest.yaml']
    return {'cases': len(cases), 'splits': {split: sum(c['split'] == split for c in cases) for split in ('dev', 'test')},
            'families': len({c['family'] for c in cases}), 'dialogues': len(dialogues),
            'answer_turns': answer_turns, 'actions': actions,
            'sha256': {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in files}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--write-lock', action='store_true', help='Freeze reviewed file hashes and annotation counts')
    args = parser.parse_args()
    report = validate_dataset(args.directory)
    if args.write_lock:
        (args.directory / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
