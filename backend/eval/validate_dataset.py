"""Validate a frozen dataset's annotations and split integrity without model calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import importlib.util
from pathlib import Path

import yaml

from benchmark import ROOT, load_cases, validate_split_is_family_disjoint


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
    manifest = yaml.safe_load((directory / 'manifest.yaml').read_text())
    fixture = (directory / manifest.get('fixture', 'fixture.sql')).resolve()
    if not fixture.is_relative_to(ROOT):
        raise ValueError('fixture path must remain inside the project')
    files = {'fixture.sql': fixture, 'cases.yaml': directory / 'cases.yaml',
             'dialogues.yaml': directory / 'dialogues.yaml', 'manifest.yaml': directory / 'manifest.yaml'}
    return {'cases': len(cases), 'splits': {split: sum(c['split'] == split for c in cases) for split in ('dev', 'test')},
            'families': len({c['family'] for c in cases}), 'dialogues': len(dialogues),
            'answer_turns': answer_turns, 'actions': actions,
            'sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}}


def validate_remediation_ablation(directory: Path, *, check_lock: bool = True) -> dict:
    """Validate the small cross-source candidate dialogue/clarification suite."""
    manifest = yaml.safe_load((directory / 'manifest.yaml').read_text())
    dialogues = yaml.safe_load((directory / 'dialogues.yaml').read_text())
    interactions = yaml.safe_load((directory / 'interactions.yaml').read_text())
    cases = yaml.safe_load((directory / 'cases.yaml').read_text())
    if manifest.get('status') != 'candidate_not_sealed' or cases != []:
        raise ValueError('remediation ablation manifest must be candidate_not_sealed with empty cases.yaml')
    if not isinstance(dialogues, list) or not isinstance(interactions, list):
        raise ValueError('dialogues.yaml and interactions.yaml must be lists')
    sources, languages = set(manifest.get('sources', [])), set(manifest.get('languages', []))
    ids: set[str] = set()
    dialogue_families: dict[str, str] = {}
    interaction_families: dict[str, str] = {}
    answer_turns = 0

    def check_item(item, label):
        if not item.get('gold_sql'):
            raise ValueError(f'{label}: missing gold SQL')
        result = item.get('expected_result')
        if (not isinstance(result, dict) or not isinstance(result.get('columns'), list)
                or not result['columns'] or len(set(result['columns'])) != len(result['columns'])
                or not isinstance(result.get('rows'), list)
                or any(not isinstance(row, list) or len(row) != len(result['columns']) for row in result['rows'])):
            raise ValueError(f'{label}: invalid expected result')

    for dialogue in dialogues:
        did = dialogue.get('id')
        if not did or did in ids or dialogue.get('split') not in {'dev', 'test'}:
            raise ValueError(f'{did}: duplicate ID or invalid split')
        ids.add(did)
        family = dialogue.get('family')
        if not family or family in dialogue_families and dialogue_families[family] != dialogue['split']:
            raise ValueError(f'{did}: missing family or family crosses split')
        dialogue_families[family] = dialogue['split']
        if dialogue.get('source_id') not in sources or dialogue.get('language') not in languages:
            raise ValueError(f'{did}: source/language is outside declared dataset')
        turns = dialogue.get('turns')
        if not isinstance(turns, list) or not turns:
            raise ValueError(f'{did}: missing turns')
        for number, turn in enumerate(turns, 1):
            if turn.get('action') not in {'answer', 'clarification_answer', 'clarify', 'refuse', 'conversation'}:
                raise ValueError(f'{did}/{number}: invalid action')
            if turn['action'] in {'answer', 'clarification_answer'}:
                check_item(turn, f'{did}/{number}')
                answer_turns += 1
            ref = turn.get('referenced_turn')
            if ref is not None and (not isinstance(ref, int) or not 1 <= ref < number):
                raise ValueError(f'{did}/{number}: reference must point to an earlier turn')
    interaction_ids: dict[str, dict] = {}
    for item in interactions:
        iid = item.get('id')
        if not iid or iid in ids or item.get('split') not in {'dev', 'test'}:
            raise ValueError(f'{iid}: duplicate ID or invalid split')
        ids.add(iid)
        family = item.get('family')
        if not family or family in interaction_families and interaction_families[family] != item['split']:
            raise ValueError(f'{iid}: missing family or family crosses split')
        interaction_families[family] = item['split']
        if item.get('source_id') not in sources or item.get('language') not in languages:
            raise ValueError(f'{iid}: source/language is outside declared dataset')
        if not isinstance(item.get('ask_fields'), list):
            raise ValueError(f'{iid}: ask_fields annotation required')
        if item['ask_fields'] and set(item.get('oracle_answers', {})) != set(item['ask_fields']):
            raise ValueError(f'{iid}: oracle keys must exactly match ask_fields')
        check_item(item, iid)
        interaction_ids[iid] = item
    for item in interactions:
        control = item.get('control_of')
        if control:
            target = interaction_ids.get(control)
            if (target is None or item['ask_fields'] or not target['ask_fields']
                    or item['family'] != target['family'] or item['split'] != target['split']
                    or item['expected_result'] != target['expected_result']):
                raise ValueError(f"{item['id']}: control does not pair with the same intended ambiguous case")
    fixture = (directory / manifest.get('fixture', 'fixture.sql')).resolve()
    if not fixture.is_relative_to(ROOT):
        raise ValueError('fixture path must remain inside project')
    files = {'manifest.yaml': directory / 'manifest.yaml', 'cases.yaml': directory / 'cases.yaml',
             'dialogues.yaml': directory / 'dialogues.yaml', 'interactions.yaml': directory / 'interactions.yaml',
             'fixture.sql': fixture}
    report = {'status': 'candidate_not_sealed', 'dialogues': len(dialogues), 'dialogue_families': len(dialogue_families),
              'interactions': len(interactions), 'interaction_families': len(interaction_families),
              'answer_turns': answer_turns,
              'splits': {name: {'dialogues': sum(d['split'] == name for d in dialogues),
                                'interactions': sum(i['split'] == name for i in interactions)}
                         for name in ('dev', 'test')},
              'sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}}
    lock = directory / 'validation.json'
    if check_lock and lock.exists() and json.loads(lock.read_text()) != report:
        raise ValueError('remediation ablation lock does not match files or annotations')
    return report


def validate_remediation_regression(directory: Path, *, check_lock: bool = True) -> dict:
    """Validate a versioned, already-inspected remediation regression suite."""
    manifest_path = directory / 'manifest.yaml'
    manifest = yaml.safe_load(manifest_path.read_text())
    if (manifest.get('dataset_type') != 'remediation_regression'
            or manifest.get('evaluation_purpose') != 'inspected_regression_unsealed'
            or manifest.get('protocol_version') != 3
            or manifest.get('status') != 'inspected_regression_unsealed'):
        raise ValueError('remediation regression requires its declared dataset type and inspected purpose')
    cases = load_cases(directory / 'cases.yaml')
    interactions = yaml.safe_load((directory / 'interactions.yaml').read_text())
    dialogues = yaml.safe_load((directory / 'dialogues.yaml').read_text())
    if not all(isinstance(value, list) for value in (cases, interactions, dialogues)):
        raise ValueError('cases, interactions and dialogues must be YAML lists')
    expected_counts = manifest.get('expected_counts') or {}
    observed_counts = {'single_cases': len(cases), 'clarification_interactions': len(interactions),
                       'memory_dialogues': len(dialogues)}
    if expected_counts != observed_counts:
        raise ValueError(f'dataset counts differ from manifest: {observed_counts}')

    sources, languages = set(manifest.get('sources', [])), set(manifest.get('languages', []))
    ids: set[str] = set()
    unsupported = []
    expected_time_labels = 0
    expected_source_labels = 0

    def check_identity(item: dict, label: str) -> None:
        if not isinstance(item.get('id'), str) or not item['id'] or item['id'] in ids:
            raise ValueError(f'{label}: missing or duplicate scenario ID')
        ids.add(item['id'])
        if item.get('split') not in {'dev', 'test'}:
            raise ValueError(f'{label}: invalid split')
        if item.get('source_id') not in sources or item.get('language') not in languages:
            raise ValueError(f'{label}: source or language is outside manifest scope')
        if not isinstance(item.get('question'), str) or not item['question'].strip():
            raise ValueError(f'{label}: missing question')

    def check_result(item: dict, label: str) -> None:
        result = item.get('expected_result')
        if not item.get('gold_sql') or not isinstance(result, dict):
            raise ValueError(f'{label}: gold SQL and expected result are required')
        columns, rows = result.get('columns'), result.get('rows')
        if (not isinstance(columns, list) or not columns or len(set(columns)) != len(columns)
                or not isinstance(rows, list)
                or any(not isinstance(row, list) or len(row) != len(columns) for row in rows)):
            raise ValueError(f'{label}: expected result shape is invalid')

    def check_oracle(oracle: dict, label: str, allowed_fields: set[str]) -> None:
        if not isinstance(oracle, dict) or set(oracle) - allowed_fields:
            raise ValueError(f'{label}: unsupported oracle field')
        for key, values in oracle.items():
            if not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values):
                raise ValueError(f'{label}: oracle values must be non-empty string lists')

    for case in cases:
        check_identity(case, case.get('id', 'case'))
        check_result(case, case['id'])
        check_oracle(case.get('oracle_answers') or {}, case['id'], {'time_range', 'context:source'})
        oracle = case.get('oracle_answers') or {}
        intent = case.get('oracle_intent') or {}
        if intent.get('source_id') != case['source_id'] or oracle.get('context:source') != [case['source_id']]:
            raise ValueError(f"{case['id']}: source oracle does not match scenario source")
        if 'time_range' in intent:
            if oracle.get('time_range') != [intent['time_range']] or intent['time_range'] not in {'all', 'last_7', 'last_30'}:
                raise ValueError(f"{case['id']}: period oracle conflicts with declared user intent")
        elif 'time_range' in oracle:
            raise ValueError(f"{case['id']}: period oracle exists without declared user intent")
        expected_time_labels += int('time_range' in intent)
        expected_source_labels += 1
        if case.get('ordered') and not isinstance(case.get('ordering_intent'), str):
            raise ValueError(f"{case['id']}: ordered=true requires a reviewed ordering_intent annotation")

    for item in interactions:
        check_identity(item, item.get('id', 'interaction'))
        check_result(item, item['id'])
        ask_fields = item.get('ask_fields')
        if not isinstance(ask_fields, list) or len(ask_fields) != len(set(ask_fields)):
            raise ValueError(f"{item['id']}: ask_fields must be a unique list")
        check_oracle(item.get('oracle_answers') or {}, item['id'], set(ask_fields))
        if set(item.get('oracle_answers') or {}) != set(ask_fields):
            raise ValueError(f"{item['id']}: clarification oracle labels must exactly match requested fields")
        oracle = item.get('oracle_answers') or {}
        if 'context:source' in oracle and not set(oracle['context:source']) <= sources:
            raise ValueError(f"{item['id']}: source oracle value is outside manifest scope")
        if 'time_range' in oracle and not set(oracle['time_range']) <= {'all', 'last_7', 'last_30'}:
            raise ValueError(f"{item['id']}: unsupported time-range oracle value")
        if 'recipe' in oracle and not set(oracle['recipe']) <= set((manifest.get('output_aliases') or {}).get('metrics', {})):
            raise ValueError(f"{item['id']}: metric oracle value is not in the declared metric scope")

    for dialogue in dialogues:
        if not isinstance(dialogue.get('turns'), list) or not dialogue['turns']:
            raise ValueError(f"{dialogue['id']}: turns are required")
        check_identity(dialogue | {'question': dialogue['turns'][0].get('question')}, dialogue.get('id', 'dialogue'))
        for number, turn in enumerate(dialogue['turns'], 1):
            label = f"{dialogue['id']}/{number}"
            if turn.get('action') not in {'answer', 'clarify', 'clarification_answer', 'refuse', 'conversation'}:
                raise ValueError(f'{label}: invalid action')
            if turn.get('action') in {'answer', 'clarification_answer'}:
                check_result(turn, label)
            if turn.get('scoring_kind'):
                if turn['scoring_kind'] != 'discussion_answer':
                    raise ValueError(f'{label}: unknown scoring kind')
                unsupported.append({'dialogue_id': dialogue['id'], 'turn': number,
                                    'scoring_kind': turn['scoring_kind']})
            oracle = turn.get('oracle_answers') or {}
            check_oracle(oracle, label, {'time_range', 'context:source', 'recipe'})
            intent = turn.get('oracle_intent') or {}
            if intent and intent.get('source_id') != dialogue['source_id']:
                raise ValueError(f'{label}: source oracle conflicts with declared user intent')
            if 'context:source' in oracle and oracle['context:source'] != [dialogue['source_id']]:
                raise ValueError(f'{label}: source oracle does not match dialogue source')
            if 'time_range' in oracle:
                if oracle['time_range'] != [intent.get('time_range')]:
                    raise ValueError(f'{label}: memory period oracle conflicts with declared user intent')
                if oracle['time_range'][0] not in {'all', 'last_7', 'last_30'}:
                    raise ValueError(f'{label}: unsupported memory period oracle value')
                expected_time_labels += 1
            elif 'time_range' in intent:
                raise ValueError(f'{label}: declared memory period intent has no matching oracle answer')
            if 'context:source' in oracle:
                expected_source_labels += 1

    declared_unsupported = manifest.get('unsupported_task_kinds', [])
    if declared_unsupported != unsupported:
        raise ValueError('unsupported task-kind declarations differ from dialogue annotations')
    fixture = (directory / manifest.get('fixture', 'fixture.sql')).resolve()
    if not fixture.is_relative_to(ROOT) or not fixture.is_file():
        raise ValueError('fixture path must be an existing project-local file')
    all_gold = {
        'cases': [(item['id'], item['gold_sql'], item['expected_result']) for item in cases],
        'interactions': [(item['id'], item['gold_sql'], item['expected_result']) for item in interactions],
        'dialogues': [(dialogue['id'], [(turn.get('question'), turn.get('action'), turn.get('gold_sql'),
                                       turn.get('expected_result')) for turn in dialogue['turns']])
                      for dialogue in dialogues],
    }
    gold_digest = hashlib.sha256(json.dumps(all_gold, ensure_ascii=False, sort_keys=True,
                                            separators=(',', ':')).encode()).hexdigest()
    input_files = sorted(path for path in directory.iterdir()
                         if path.is_file() and path.suffix in {'.yaml', '.sql'} and path.name != 'validation.json')
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in input_files}
    report = {'dataset': manifest['name'], 'dataset_type': manifest['dataset_type'],
              'evaluation_purpose': manifest['evaluation_purpose'], 'not_fresh_holdout': True,
              'gold_sql_and_expected_result_digest': gold_digest,
              'counts': observed_counts,
              'intent_label_counts': {'single_time_range_all': expected_time_labels,
                                      'single_source_context': expected_source_labels},
              'predeclared_unsupported_turns': unsupported, 'hashes': hashes}
    lock = directory / 'validation.json'
    if check_lock and (not lock.exists() or json.loads(lock.read_text()) != report):
        raise ValueError('remediation regression validation lock does not match annotations and inputs')
    return report


def validate_ablation_dataset(directory: Path, *, check_lock: bool = True) -> dict:
    """Validate the paired memory/clarification suite; does not execute SQL."""
    manifest = yaml.safe_load((directory / "manifest.yaml").read_text())
    dialogues = yaml.safe_load((directory / "dialogues.yaml").read_text())
    interactions = yaml.safe_load((directory / "interactions.yaml").read_text())
    cases = yaml.safe_load((directory / "cases.yaml").read_text())
    if cases != []:
        raise ValueError("ablation v1 cases.yaml must remain empty; use the pinned v2 case suite")
    if manifest.get("metrics_reference") != "../v2/manifest.yaml" or manifest.get("single_turn_suite") != "../v2/cases.yaml":
        raise ValueError("ablation manifest must point to the frozen v2 metric and single-turn contracts")

    ids: set[str] = set()
    counts: dict[str, int] = {}
    splits: dict[str, int] = {"dev": 0, "test": 0}
    answer_turns = 0
    question_splits: dict[str, str] = {}
    scenario_signatures: dict[str, tuple[str, str]] = {}
    state_gold_signatures: dict[str, tuple[str, str]] = {}

    def result_shape(item: dict, label: str) -> None:
        if not item.get("gold_sql"):
            raise ValueError(f"{label}: missing gold SQL")
        result = item.get("expected_result")
        if not isinstance(result, dict) or not isinstance(result.get("columns"), list) or not result["columns"]:
            raise ValueError(f"{label}: missing expected result columns")
        if not isinstance(result.get("rows"), list) or any(not isinstance(r, list) or len(r) != len(result["columns"])
                                                              for r in result["rows"]):
            raise ValueError(f"{label}: invalid expected result rows")

    if not isinstance(dialogues, list) or not isinstance(interactions, list):
        raise ValueError("dialogues.yaml and interactions.yaml must be lists")
    for dialogue in dialogues:
        did = dialogue.get("id")
        if not did or did in ids or dialogue.get("split") not in splits:
            raise ValueError(f"{did}: missing/duplicate ID or invalid split")
        ids.add(did)
        splits[dialogue["split"]] += 1
        phenomenon = dialogue.get("phenomenon")
        if not phenomenon or not dialogue.get("cluster_id"):
            raise ValueError(f"{did}: missing phenomenon or cluster_id")
        counts[phenomenon] = counts.get(phenomenon, 0) + 1
        turns = dialogue.get("turns")
        if not isinstance(turns, list) or not turns:
            raise ValueError(f"{did}: missing turns")
        for number, turn in enumerate(turns, 1):
            normalized_question = " ".join(turn.get("question", "").lower().split())
            if not normalized_question:
                raise ValueError(f"{did}/{number}: missing question")
            previous_split = question_splits.get(normalized_question)
            if previous_split is not None and previous_split != dialogue["split"]:
                raise ValueError(f"{did}/{number}: identical turn question crosses dev/test")
            question_splits[normalized_question] = dialogue["split"]
            action = turn.get("action")
            if action not in {"answer", "clarify", "clarification_answer", "refuse", "conversation"}:
                raise ValueError(f"{did}/{number}: invalid action")
            if action in {"answer", "clarification_answer"}:
                result_shape(turn, f"{did}/{number}")
                answer_turns += 1
            if action == "clarify":
                if not turn.get("ask_fields"):
                    raise ValueError(f"{did}/{number}: clarification must name ask_fields")
                if number == len(turns) or turns[number].get("action") != "clarification_answer":
                    raise ValueError(f"{did}/{number}: clarification must be followed by oracle reply")
            if action == "clarification_answer":
                if number == 1 or turns[number - 2].get("action") != "clarify":
                    raise ValueError(f"{did}/{number}: no preceding clarification")
                oracle = turn.get("oracle_answers", {})
                required = set(turns[number - 2].get("ask_fields", []))
                if set(oracle) != required:
                    raise ValueError(f"{did}/{number}: oracle fields do not match requested fields")
                target = turn.get("oracle_reference_turn")
                if target is not None:
                    if not isinstance(target, int) or not 1 <= target < number - 1:
                        raise ValueError(f"{did}/{number}: oracle_reference_turn must identify an earlier answer turn")
                    if oracle.get("context:reference") != [f"oracle:turn:{target}"]:
                        raise ValueError(f"{did}/{number}: reference oracle marker does not match target turn")
            reference = turn.get("referenced_turn")
            if reference is not None and (not isinstance(reference, int) or not 1 <= reference < number):
                raise ValueError(f"{did}/{number}: invalid earlier-turn reference")
        computed = max((i - t["referenced_turn"] for i, t in enumerate(turns, 1)
                        if t.get("referenced_turn")), default=0)
        if dialogue.get("dependency_distance") != computed:
            raise ValueError(f"{did}: dependency_distance is not reproducible")
        signature = json.dumps([{key: turn.get(key) for key in
            ("question", "action", "state", "gold_sql", "expected_result", "referenced_turn", "oracle_reference_turn")}
            for turn in turns], sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
        previous = scenario_signatures.get(signature)
        if previous is not None and previous[0] != dialogue["split"]:
            raise ValueError(f"{did}: identical scenario content crosses dev/test from {previous[1]}")
        scenario_signatures[signature] = (dialogue["split"], did)
        state_signature = json.dumps([{key: turn.get(key) for key in
            ("action", "state", "gold_sql", "expected_result", "referenced_turn", "oracle_reference_turn")}
            for turn in turns], sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
        previous = state_gold_signatures.get(state_signature)
        if previous is not None and previous[0] != dialogue["split"]:
            raise ValueError(f"{did}: identical action/state/gold-result sequence crosses dev/test from {previous[1]}")
        state_gold_signatures[state_signature] = (dialogue["split"], did)

    by_id: dict[str, dict] = {}
    ambiguous_count = control_count = 0
    for item in interactions:
        iid = item.get("id")
        if not iid or iid in ids or item.get("split") not in splits:
            raise ValueError(f"{iid}: missing/duplicate ID or invalid split")
        ids.add(iid)
        by_id[iid] = item
        splits[item["split"]] += 1
        if not item.get("family") or not item.get("cluster_id"):
            raise ValueError(f"{iid}: missing family or cluster_id")
        if not item.get("question") or not isinstance(item.get("ask_fields"), list):
            raise ValueError(f"{iid}: missing question or ask_fields annotation")
        result_shape(item, iid)
        if item["ask_fields"]:
            ambiguous_count += 1
            if set(item.get("oracle_answers", {})) != set(item["ask_fields"]):
                raise ValueError(f"{iid}: oracle keys must exactly match ask_fields")
            if item.get("phenomenon") == "missing_period":
                if item["ask_fields"] != ["time_range"] or item["oracle_answers"]["time_range"][0] not in {"all", "last_7"}:
                    raise ValueError(f"{iid}: unsupported period ambiguity annotation")
            elif item.get("phenomenon") == "ambiguous_metric":
                if item["ask_fields"] != ["recipe"] or item["oracle_answers"]["recipe"][0] not in {"users", "buyers"}:
                    raise ValueError(f"{iid}: unsupported metric ambiguity annotation")
            else:
                raise ValueError(f"{iid}: unknown clarification phenomenon")
        else:
            control_count += 1
            if item.get("oracle_answers"):
                raise ValueError(f"{iid}: explicit control must not contain hidden oracle answers")

    for item in interactions:
        control_of = item.get("control_of")
        if control_of is None:
            continue
        original = by_id.get(control_of)
        if original is None or not original.get("ask_fields") or item["ask_fields"]:
            raise ValueError(f"{item['id']}: control_of must target an ambiguous interaction")
        if (item["cluster_id"] != original["cluster_id"] or item["split"] != original["split"]
                or item["expected_result"] != original["expected_result"]):
            raise ValueError(f"{item['id']}: paired control must keep split, cluster and intended result")

    if len(dialogues) != 24 or splits["dev"] < 12 or splits["test"] < 12:
        raise ValueError(f"expected 24 dialogue scenarios and at least 12 per split; got {splits}")
    if set(counts.values()) != {4} or len(counts) != 6:
        raise ValueError(f"expected six balanced memory phenomena (four each), got {counts}")
    if max(len(d["turns"]) for d in dialogues) < 12:
        raise ValueError("memory suite must include a 12-turn scenario")
    if ambiguous_count != 20 or control_count != 20:
        raise ValueError(f"expected 20 ambiguous interactions and 20 controls; got {ambiguous_count}/{control_count}")

    # Recompute literal outputs independently and confirm the choices used for
    # clarification are observationally distinguishable on this fixture.
    generator_path = directory / "generate.py"
    spec = importlib.util.spec_from_file_location("ablation_v1_generator", generator_path)
    generator = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(generator)
    rows = generator.rows_for_v1()
    projection = [{key: row[key] for key in ("event_id", "event_date", "event_name", "user_id",
                  "session_id", "item_category", "revenue", "ep")}
                  for row in sorted(rows, key=lambda item: item["event_id"])]
    canonical_source = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    projection_path = directory / "fixture_rows.json"
    projection_bytes = projection_path.read_bytes()
    if projection_bytes.decode("utf-8") != canonical_source:
        raise ValueError("fixture_rows.json does not match the deterministic source event projection")
    source_digest = hashlib.sha256(projection_bytes).hexdigest()
    if manifest.get("source_digest") != source_digest:
        raise ValueError("manifest source_digest does not match canonical fixture_rows.json")
    for item in interactions:
        if item.get("control_of"):
            continue
        state = item["state"]
        chosen = (state["metric"], generator.where_for(state["metric"], state["time_range"])[1], state.get("breakdown"))
        computed = generator.v2.evaluate(rows, chosen)
        if computed != item["expected_result"]:
            raise ValueError(f"{item['id']}: literal result differs from independent reference aggregation")
        if item["phenomenon"] == "missing_period":
            alternative = "last_7" if state["time_range"] == "all" else "all"
            other = generator.v2.evaluate(rows, (state["metric"], generator.where_for(state["metric"], alternative)[1], None))
            if other == item["expected_result"]:
                raise ValueError(f"{item['id']}: period choices do not produce distinguishable results")

    files = ["manifest.yaml", "fixture.sql", "fixture_rows.json", "cases.yaml", "dialogues.yaml", "interactions.yaml", "generate.py"]
    report = {"dialogues": len(dialogues), "dialogue_splits": {"dev": sum(d["split"] == "dev" for d in dialogues),
        "test": sum(d["split"] == "test" for d in dialogues)}, "answer_turns": answer_turns,
        "phenomena": counts, "interactions": len(interactions), "ambiguous": ambiguous_count,
        "controls": control_count, "interaction_splits": {"dev": sum(i["split"] == "dev" for i in interactions),
        "test": sum(i["split"] == "test" for i in interactions)},
        "source_digest": source_digest,
        "sha256": {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in files}}
    lock_path = directory / "validation.json"
    if check_lock and lock_path.exists() and json.loads(lock_path.read_text()) != report:
        raise ValueError("ablation validation lock does not match files or annotations")
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--write-lock', action='store_true', help='Freeze reviewed file hashes and annotation counts')
    parser.add_argument('--ablation', action='store_true', help='Validate the versioned ablation study suite')
    args = parser.parse_args()
    if args.ablation:
        manifest = yaml.safe_load((args.directory / 'manifest.yaml').read_text())
        validator = validate_remediation_ablation if manifest.get('status') == 'candidate_not_sealed' else validate_ablation_dataset
        report = validator(args.directory, check_lock=not args.write_lock)
    else:
        report = validate_dataset(args.directory)
    if args.write_lock:
        (args.directory / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
