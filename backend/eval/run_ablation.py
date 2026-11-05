"""Controlled offline component study. Default invocation is a provider-free dry run.

Use --gold for PostgreSQL/reference checks. Live execution additionally requires
--execute, an explicit model and a per-process model-call budget. --matrix runs
isolated subprocesses in rotated variant order; report_ablation.py summarizes logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from benchmark import (ROOT, dialogue_outcome_score, execute_readonly, load_cases, results_equal, score_business_result,
                       score_expected_result, server_metadata)
from gateway_budget import configure_gateway_from_environment
from run_benchmark import SYSTEM, SQL_SCHEMA, _call_usage, _project_path, _turn_usage, _wait_turn, prompt_for

SUITES = {'memory': ('F', 'M6', 'M0'), 'clarification': ('F', 'C0'), 'single': ('F', 'B0')}
FILES = {'memory': 'dialogues.yaml', 'clarification': 'interactions.yaml', 'single': 'cases.yaml'}
USAGE_KEYS = ('calls', 'input_tokens', 'output_tokens', 'model_ms')


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def canonical_source_metadata(source) -> dict[str, Any]:
    """Serialize source provenance deterministically, including every set field."""
    metadata = source.model_dump(mode='json')
    metadata.pop('snapshot_version', None)
    for name in source.__class__.model_fields:
        value = getattr(source, name, None)
        if isinstance(value, set):
            metadata[name] = sorted(value)
    return metadata


def load_suite(directory: Path, suite: str, split: str) -> list[dict]:
    path = directory / FILES[suite]
    rows = load_cases(path) if suite == 'single' else yaml.safe_load(path.read_text())
    selected = [row for row in rows if row['split'] == split]
    if not selected:
        raise ValueError(f'No {suite}/{split} scenarios in {directory}; use v2 directory for single-turn baseline')
    ids = [row['id'] for row in selected]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate scenario IDs')
    return selected


def normalize_time(value: Any) -> Any:
    if value == 'all' or value == {'kind': 'all'}:
        return {'kind': 'all'}
    if isinstance(value, str):
        if value.startswith('last_'):
            return {'kind': 'last_n_days', 'days': int(value[5:])}
        return {'kind': 'between', 'start': value, 'end': value}
    return {key: str(value[key]) if key in {'start', 'end'} else value[key]
            for key in ('kind', 'start', 'end', 'days') if key in (value or {})}


def slot_checks(expected: dict, turn: dict) -> dict[str, bool]:
    spec = turn.get('query_spec') or {}
    checks = {}
    if 'metric' in expected:
        metrics = ([spec['recipe']] if spec.get('recipe') else spec.get('metrics', []))
        checks['metric'] = metrics == [expected['metric']]
    if 'breakdown' in expected:
        wanted = [expected['breakdown']] if expected['breakdown'] else []
        checks['breakdown'] = sorted(spec.get('selection') or []) == sorted(wanted)
    if 'time_range' in expected:
        checks['time_range'] = normalize_time(spec.get('time_range')) == normalize_time(expected['time_range'])
    if 'filters' in expected:
        actual = sorted((f['field'], 'IN' if f.get('operator', '=') in {'=', 'IN'} else f['operator'],
                         tuple(sorted(map(str, f.get('values') or [])))) for f in spec.get('filters') or [])
        target = sorted((field, 'IN', tuple(sorted(map(str, value if isinstance(value, list) else [value]))))
                        for f in expected['filters'] for field, value in f.items())
        checks['filters'] = actual == target
    return checks


def action(turn: dict) -> str:
    return {'answered': 'answer', 'discussed': 'answer', 'needs_clarification': 'clarify',
            'refused': 'refuse', 'conversation': 'conversation'}.get(turn.get('status'), 'error')


def clarification_counts(wanted, actual) -> dict[str, int]:
    wanted, actual = set(wanted), set(actual)
    return {'tp': len(wanted & actual), 'fp': len(actual-wanted), 'fn': len(wanted-actual)}


def form_fields(turn: dict) -> set[str]:
    return {f['id'] for f in (turn.get('form') or {}).get('fields', [])} if action(turn) == 'clarify' else set()


def oracle_for(item: dict, turn: dict, labels: dict[int, str]) -> dict:
    """Read hidden choices only at an actual, exactly matching clarification form."""
    fields = (turn.get('form') or {}).get('fields', [])
    wanted = item.get('oracle_answers') or {}
    if not fields or set(wanted) != {f['id'] for f in fields}:
        raise ValueError('Oracle fields do not match actual clarification')
    selected = {}
    for field in fields:
        key = field['id']
        values = list(wanted[key])
        if key == 'context:reference':
            target = item.get('oracle_reference_turn')
            if target not in labels:
                raise ValueError('Oracle reference points to unavailable turn')
            values = [labels[target]]
        allowed = {str(choice['id']) for choice in field.get('choices') or []}
        if not values or any(value not in allowed for value in values):
            raise ValueError('Oracle chose a value not offered by the system')
        selected[key] = values
    return selected


class TexaSession:
    """One scenario, one conversation; all resumes count toward the same turn usage."""
    def __init__(self, model: str, source_id: str, timeout: int):
        from texa import answer
        self.api, self.model, self.source_id, self.timeout = answer, model, source_id, timeout
        self.conversation_id = None
        self.turn_ids: set[str] = set()

    def _wait(self, turn_id: str) -> dict:
        try:
            raw = _wait_turn(self.api, turn_id, self.timeout)
        except TimeoutError:
            self.api.cancel(turn_id)
            # A background provider call may still be running. Stop the process
            # without marking the run complete, rather than undercount its usage.
            raise IncompleteRun('Timed out; run is incomplete and must be rerun as a block') from None
        return {**raw, **raw['state'], 'id': str(raw['id'])}

    def ask(self, question: str) -> dict:
        ids = self.api.ask(question, self.conversation_id, self.model, [self.source_id])
        self.conversation_id = ids['conversation_id']
        self.turn_ids.add(ids['turn_id'])
        return self._wait(ids['turn_id'])

    def resume(self, turn: dict, choices: dict) -> dict:
        self.api.answer_clarification(turn['id'], choices)
        return self._wait(turn['id'])

    def output(self, turn: dict):
        full = self.api.full_result(turn['id'])
        if full.get('partial'):
            raise ValueError('Truncated result cannot be scored')
        columns = [col['name'] for col in turn.get('columns') or [] if not col['name'].startswith('__')]
        return columns, [[row.get(col) for col in columns] for row in full['rows']]

    def usage(self) -> dict:
        values = [_turn_usage(turn_id) for turn_id in self.turn_ids]
        return {key: sum(value[key] for value in values) for key in USAGE_KEYS}

    def close(self):
        from texa import db
        if self.conversation_id:
            with db.app_conn() as conn:
                conn.execute('DELETE FROM app.conversations WHERE id=%s', (self.conversation_id,))
        for turn_id in self.turn_ids:
            self.api.RUNS.pop(turn_id, None)


class IncompleteRun(RuntimeError):
    pass


def score_answer(item: dict, turn: dict, session) -> dict:
    result = {'result_correct': False, 'strict_result_correct': False, 'business_result_correct': False,
              'output_contract_compliant': False, 'slot_checks': slot_checks(item.get('state') or {}, turn)}
    if action(turn) != 'answer':
        return result
    try:
        columns, rows = session.output(turn)
        expected = item['expected_result']
        scores = score_business_result(columns, rows, expected['columns'], expected['rows'],
                                       ordered=bool(item.get('ordered')),
                                       contract=item.get('business_contract'))
        strict = results_equal(columns, rows, expected['columns'], expected['rows'], ordered=bool(item.get('ordered')))
        result.update(scores, result_correct=strict, strict_result_correct=strict)
        result.update(columns=columns, row_count=len(rows))
    except Exception as exc:
        result['result_error'] = type(exc).__name__
    return result


def trace(turn: dict) -> dict:
    return {key: turn.get(key) for key in ('id', 'status', 'query_spec', 'compiled_sql', 'ablation', 'context', 'dataset_version')}


def run_memory(item: dict, session) -> dict:
    rows, labels, pending = [], {}, None
    for index, expected in enumerate(item['turns'], 1):
        is_resume = expected['action'] == 'clarification_answer'
        wanted = 'answer' if is_resume else expected['action']
        row = {'index': index, 'expected_action': wanted}
        try:
            if is_resume:
                if pending is None:
                    raise ValueError('No pending clarification; oracle not delivered')
                choices = oracle_for(expected, pending, labels)
                current = session.resume(pending, choices)
                row['oracle_delivered_fields'] = sorted(choices)
            else:
                current = session.ask(expected['question'])
                labels[index] = current['id']
            row.update(actual_action=action(current), action_correct=action(current) == wanted, trace=trace(current))
            if expected.get('gold_sql'):
                row.update(score_answer(expected, current, session))
            expected_fields = expected.get('ask_fields', [])
            row['clarification_counts'] = clarification_counts(expected_fields, form_fields(current)) if not is_resume else {'tp': 0, 'fp': len(form_fields(current)), 'fn': 0}
            if wanted == 'clarify':
                row['action_correct'] &= form_fields(current) == set(expected_fields)
            # References are diagnostic only. Neither M6 nor M0 is required to
            # materialize the structured strategy's private reference metadata.
            if 'referenced_turn' in expected:
                row['reference_diagnostic'] = labels.get(expected['referenced_turn']) in (current.get('context') or {}).get('references', [])
            pending = current if action(current) == 'clarify' else None
            context_refs = (current.get('context') or {}).get('references') or []
            row.update(dialogue_outcome_score(
                expected_action=wanted, actual_action=row['actual_action'],
                result_correct=row.get('business_result_correct'),
                expected_fields=expected.get('ask_fields') or [], actual_fields=form_fields(current),
                # Structured reference metadata is diagnostic: an M6/raw-history
                # system may resolve the same ordinal reference without exposing
                # Texa's internal reference list. The public result is scored.
                reference_expected=None,
                context_contamination=not expected.get('referenced_turn') and bool(context_refs)))
        except IncompleteRun:
            raise
        except Exception as exc:
            row.update(actual_action='error', action_correct=False, error=type(exc).__name__,
                       clarification_counts=clarification_counts(expected.get('ask_fields', []), []))
            if expected.get('gold_sql'):
                row['result_correct'] = False
                row['strict_result_correct'] = False
                row['business_result_correct'] = False
                row['output_contract_compliant'] = False
            pending = None
        rows.append(row)
    answers = [row for row in rows if 'result_correct' in row]
    # Slot fidelity is reported, but cannot override a correct final SQL result
    # simply because a strategy's internal representation differs.
    aggregate_correct = all(row['result_correct'] for row in answers) if answers else None
    business_answers = [row for row in answers if row.get('business_result_correct') is not None]
    business_correct = (all(row['business_result_correct'] for row in business_answers)
                        if business_answers else None)
    return {'turns': rows, 'success': all(row.get('observable_success', False) for row in rows),
            'result_correct': aggregate_correct, 'strict_result_correct': aggregate_correct,
            'business_result_correct': business_correct,
            'answer_count': len(business_answers), 'answer_correct': sum(row['business_result_correct'] for row in business_answers),
            'clarification_rounds': sum(row.get('actual_action') == 'clarify' for row in rows),
            'clarification_counts': {key: sum(row['clarification_counts'][key] for row in rows) for key in ('tp', 'fp', 'fn')}}


def run_interaction(item: dict, session, max_rounds: int = 2) -> dict:
    rows, counts, rounds = [], {'tp': 0, 'fp': 0, 'fn': 0}, 0
    current = session.ask(item['question'])
    seen_fields: set[str] = set()
    oracle_error = None
    while True:
        asked = form_fields(current)
        seen_fields |= asked
        rows.append({'trace': trace(current), 'actual_action': action(current), 'asked': sorted(asked)})
        if action(current) != 'clarify':
            break
        rounds += 1
        if rounds > max_rounds:
            oracle_error = 'clarification_limit'
            break
        try:
            choices = oracle_for(item, current, {})
        except ValueError:
            oracle_error = 'oracle_mismatch'
            break
        rows[-1]['oracle_delivered_fields'] = sorted(choices)
        current = session.resume(current, choices)
    counts = clarification_counts(item.get('ask_fields', []), seen_fields)
    result = score_answer(item, current, session)
    # C0 is not failed merely for skipping an expected question; final SQL is
    # judged against exactly the same hidden user intent as F.
    business_correct = bool(result.get('business_result_correct', result['result_correct']))
    return {**result, 'success': business_correct and oracle_error is None,
            'strict_result_correct': result.get('result_correct'),
            'answer_count': 1, 'answer_correct': int(business_correct),
            'clarification_counts': counts, 'clarification_rounds': rounds,
            'oracle_error': oracle_error, 'turns': rows,
            'trigger_observed': bool(seen_fields) or any((row['trace'].get('ablation') or {}).get('clarification_invoked') for row in rows)}


def source_digest(dsn: str, source: str) -> str:
    # Canonical semantic projection shared with fixture_rows.json. Revenue in
    # this fixture is integral, but preserve numeric fractions in other suites.
    columns, rows = execute_readonly(dsn,
        "SELECT event_id,event_date::text,event_name,user_id,session_id,item_category,revenue,ep "
        "FROM analytics.event_activity WHERE source_id='" + source.replace("'", "''") + "' ORDER BY event_id")
    canonical = []
    for values in rows:
        row = dict(zip(columns, values))
        if row['revenue'] is not None:
            value = row['revenue']
            row['revenue'] = int(value) if value == int(value) else float(value)
        canonical.append(row)
    return digest(canonical)


def owner_digest(dsn: str, source: str) -> str:
    """App owner may be superuser locally; still require the isolated DB name."""
    import psycopg
    with psycopg.connect(dsn) as conn:
        conn.execute('SET TRANSACTION READ ONLY')
        if conn.execute('SELECT current_database()').fetchone()[0] != 'texa_benchmark':
            raise ValueError('All evaluation connections must target texa_benchmark')
        rows = conn.execute("SELECT event_id,event_date::text,event_name,user_id,session_id,item_category,revenue,ep "
                            "FROM analytics.event_activity WHERE source_id=%s ORDER BY event_id", (source,)).fetchall()
        columns = ('event_id', 'event_date', 'event_name', 'user_id', 'session_id', 'item_category', 'revenue', 'ep')
        canonical = []
        for values in rows:
            row = dict(zip(columns, values))
            if row['revenue'] is not None:
                value = row['revenue']; row['revenue'] = int(value) if value == int(value) else float(value)
            canonical.append(row)
        return digest(canonical)


def preflight(args, directory: Path, rows: list[dict]) -> dict:
    os.environ['TEXA_SOURCE_PROFILE'] = 'evaluation'
    from texa import catalog, db, llm
    dsn = os.environ.get('TEXA_BENCHMARK_DSN')
    if not dsn:
        raise ValueError('Set TEXA_BENCHMARK_DSN to the isolated read-only benchmark role')
    manifest = yaml.safe_load((directory / 'manifest.yaml').read_text())
    selected_sources = manifest.get('sources') or [manifest.get('source_id', 'event_benchmark')]
    observed_sources = {source: source_digest(dsn, source) for source in selected_sources}
    expected_sources = manifest.get('source_digests') or {}
    if len(selected_sources) == 1 and manifest.get('source_digest'):
        expected_sources = {selected_sources[0]: manifest['source_digest']}
    for source, observed in observed_sources.items():
        if expected_sources.get(source) and observed != expected_sources[source]:
            raise ValueError(f'Loaded database differs from frozen fixture for {source}; reload the selected dataset')
        if source_digest(db.READER_DSN, source) != observed:
            raise ValueError(f'Texa reader and evaluator differ for {source}')
        if owner_digest(db.DB_DSN, source) != observed:
            raise ValueError(f'Texa app and evaluator differ for {source}')
    cat = catalog.published()
    sources = catalog.scoped_sources(cat, catalog.load_sources(max_age=0))
    if set(selected_sources) - set(sources):
        raise ValueError(f'Selected source metadata is missing: {sorted(set(selected_sources)-set(sources))}')
    metadata = {}
    for source in selected_sources:
        src = sources[source]
        _, stats = execute_readonly(dsn, "SELECT min(event_date)::text,max(event_date)::text,count(*),count(DISTINCT user_id) FROM analytics.event_activity WHERE source_id='" + source.replace("'", "''") + "'")
        if tuple(stats[0]) != (src.min_date, src.max_date, src.row_count, src.user_count):
            raise ValueError(f'Source registry metadata is stale relative to fixture: {source}')
        metadata[source] = src
    if set(selected_sources) - set(cat.sources_for_profile('evaluation')) or cat.policy.max_sources != 1:
        raise ValueError('Publish the bounded product catalog before running the study')
    effective = llm.get_connection(with_key=False)
    if not effective:
        raise ValueError('Configure an LLM connection before live execution')
    config = {key: effective.get(key) for key in ('provider', 'max_output_tokens', 'answer_language')}
    config.update(model=args.model, context_budget=db.CONTEXT_BUDGET_TOKENS,
                  seed='not set; provider dependent', temperature='0 for Gemini; provider default for OpenAI/Anthropic',
                  http_timeout_s=llm.TIMEOUT_S, stage_output_caps={'B0': 1200, 'C0_guess': 120, 'Texa_other_stages': 'code/default'},
                  retry_policy={'max_provider_attempts': llm.MAX_PROVIDER_ATTEMPTS,
                                'sdk_max_retries': 0,
                                'retryable_failures_only': True,
                                'backoff_s': 'min(0.25 * 2^attempt + uniform(0,0.1), 1.0)'},
                  admission={'max_inflight': llm.ADMISSION.max_inflight,
                             'max_waiters': llm.ADMISSION.max_waiters,
                             'wait_timeout_s': llm.ADMISSION.wait_timeout_s},
                  max_clarification_rounds=args.max_clarification_rounds, max_model_calls=args.max_model_calls,
                  turn_timeout_s=args.turn_timeout, max_rounds_protocol='exact fields; no unsolicited oracle')
    # Keep credentials/DSNs/keys out of output; hash provider route if customized.
    config['endpoint_hash'] = digest(effective.get('base_url') or 'provider default')
    inputs = [p for p in directory.iterdir() if p.is_file() and p.suffix in {'.yaml', '.sql', '.json', '.py'}]
    prompt_files = [ROOT / f for f in (
        'backend/texa/prompts.py', 'backend/texa/interpret.py', 'backend/texa/ablation.py',
        'backend/texa/memory.py', 'backend/texa/catalog.py', 'backend/texa/spec.py',
        'backend/texa/compile.py', 'backend/texa/profiler.py', 'backend/texa/clarify.py',
        'backend/texa/answer.py', 'backend/texa/llm.py',
        'backend/texa/runtime_guard.py', 'backend/texa/schema.sql',
        'backend/texa/main.py', 'backend/texa/pipeline.py', 'backend/texa/sanity.py',
        'backend/texa/suggestions.py', 'backend/texa/locale.py', 'backend/texa/execute.py',
        'backend/texa/db.py', 'backend/texa/insight.py', 'backend/texa/facts.py',
        'backend/texa/gateway_budget.py',
        'backend/eval/gateway_budget.py', 'backend/eval/validate_dataset.py',
        'backend/eval/benchmark.py', 'backend/eval/run_benchmark.py',
        'backend/eval/run_ablation.py', 'backend/eval/report_ablation.py',
    )]
    hashes = lambda paths: {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()
    if dirty:
        raise ValueError('Commit tracked implementation changes before collecting live experiment results')
    source_metadata = {}
    for source, src in metadata.items():
        source_metadata[source] = canonical_source_metadata(src)
    # Full gold validation before a paid run prevents accidental scoring against
    # a fixture that merely happens to share the source name.
    for row in rows:
        targets = row.get('turns', [row])
        for target in targets:
            if 'gold_sql' in target:
                result = score_expected_result(dsn, target['gold_sql'], target['expected_result'] | {'ordered': target.get('ordered', False)})
                if not result['result_correct']:
                    raise ValueError(f"Gold validation failed for {row['id']}")
    return {'dataset_hashes': hashes(inputs), 'catalog_hash': digest(cat.model_dump(mode='json')),
            'prompt_hashes': hashes(prompt_files), 'implementation_hashes': hashes(prompt_files),
            'source_profile': 'evaluation', 'source_digests': observed_sources,
            'source_digest': digest(observed_sources), 'effective_model_config': config,
            'commit': commit, 'postgresql': server_metadata(dsn),
            'source_metadata_hash': digest(source_metadata)}


def scenario_base(item: dict) -> dict:
    return {'type': 'scenario', 'id': item['id'], 'cluster_id': item.get('cluster_id', item.get('family', item['id'])),
            'group': item.get('phenomenon', item.get('family', 'unlabeled')), 'tags': item.get('tags', []),
            'source_id': item.get('source_id'), 'language': item.get('language'),
            'intent': item.get('family')}


def gold_run(args, directory: Path, scenarios: list[dict]) -> int:
    dsn = os.environ.get('TEXA_BENCHMARK_DSN')
    if not dsn:
        raise ValueError('Set TEXA_BENCHMARK_DSN for gold validation')
    manifest = yaml.safe_load((directory / 'manifest.yaml').read_text())
    if manifest.get('source_digest') and source_digest(dsn, manifest.get('source_id', 'event_benchmark')) != manifest['source_digest']:
        raise ValueError('Gold database differs from selected frozen fixture')
    total = correct = 0
    for item in scenarios:
        for target in item.get('turns', [item]):
            if 'gold_sql' not in target:
                continue
            result = score_expected_result(dsn, target['gold_sql'], target['expected_result'] | {'ordered': target.get('ordered', False)})
            total += 1; correct += bool(result['result_correct'])
            if not result['result_correct']:
                print(json.dumps({'id': item['id'], **result}))
    print(json.dumps({'mode': 'gold', 'suite': args.suite, 'split': args.split, 'correct': correct, 'total': total,
                      'model_calls': 0}))
    return int(not total or correct != total)


def protocol(args, provenance: dict) -> dict:
    return {'suite': args.suite, 'model': args.model, 'provenance': provenance}


def check_protocol(args, provenance: dict) -> None:
    if args.protocol:
        locked = json.loads(_project_path(args.protocol).read_text())
        if locked != protocol(args, provenance):
            raise ValueError('Study inputs differ from the frozen protocol; do not retune after test')
    elif args.split == 'test':
        raise ValueError('Live test requires --protocol frozen on dev before inspecting test outcomes')


def execute(args, directory: Path, scenarios: list[dict]) -> int:
    os.environ['TEXA_SOURCE_PROFILE'] = 'evaluation'
    from texa import ablation, llm
    os.environ.pop('TEXA_MEMORY_MODE', None)
    os.environ['TEXA_ABLATION_VARIANT'] = 'F' if args.variant == 'B0' else args.variant
    ablation.variant()
    provenance = preflight(args, directory, scenarios)
    check_protocol(args, provenance)
    output = _project_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Never append multiple repeats or overwrite a prior result accidentally.
    with output.open('x', encoding='utf-8') as handle:
        def write(row):
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + '\n'); handle.flush()
        write({'type': 'run_manifest', 'variant': args.variant, 'suite': args.suite, 'split': args.split,
               'repeat': args.repeat, 'model': args.model, 'provenance': provenance,
               'expected_ids': [row['id'] for row in scenarios]})
        remaining_calls = args.max_model_calls
        budget_exhausted = False
        attempted_calls = 0
        prompt_traces = []
        original_generate = llm.generate_structured
        def budgeted_generate(**kwargs):
            nonlocal remaining_calls, budget_exhausted, attempted_calls
            if remaining_calls <= 0:
                budget_exhausted = True
                raise llm.LLMError('STUDY_BUDGET', 'Study model-call budget exhausted')
            remaining_calls -= 1
            attempted_calls += 1
            prompt_traces.append({'name': kwargs.get('name'), 'system_hash': digest(kwargs.get('system')),
                'prompt_hash': digest(kwargs.get('prompt')), 'schema_hash': digest(kwargs.get('schema')),
                'max_output_tokens': kwargs.get('max_output_tokens'), 'model': kwargs.get('model')})
            return original_generate(**kwargs)
        llm.generate_structured = budgeted_generate
        try:
            manifest = yaml.safe_load((directory / 'manifest.yaml').read_text())
            for item in scenarios:
                started = time.monotonic()
                session = None
                call_name = None
                attempts_before = attempted_calls
                try:
                    if args.variant == 'B0':
                        call_name = f'ablation_{uuid.uuid4().hex[:20]}'
                        response = llm.generate_structured(model=args.model, system=SYSTEM, prompt=prompt_for(item, manifest),
                                                           schema=SQL_SCHEMA, name=call_name, max_output_tokens=1200)
                        measured = score_expected_result(os.environ['TEXA_BENCHMARK_DSN'], response['sql'],
                                                        item['expected_result'] | {'ordered': item.get('ordered', False)},
                                                        contract=item.get('business_contract'))
                        business_ok = bool(measured.get('business_result_correct', measured['result_correct']))
                        record = {'success': business_ok, 'result_correct': measured['result_correct'],
                                  'strict_result_correct': measured.get('strict_result_correct', measured['result_correct']),
                                  'business_result_correct': business_ok,
                                  'output_contract_compliant': measured.get('output_contract_compliant'),
                                  'answer_count': 1, 'answer_correct': int(business_ok),
                                  'sql': response['sql'], 'usage': _call_usage(call_name)}
                    else:
                        session = TexaSession(args.model, item.get('source_id', manifest.get('source_id', 'event_benchmark')),
                                              args.turn_timeout)
                        if args.suite == 'memory':
                            record = run_memory(item, session)
                        elif args.suite == 'clarification':
                            record = run_interaction(item, session, args.max_clarification_rounds)
                        else:
                            current = session.ask(item['question'])
                            record = score_answer(item, current, session)
                            business_ok = bool(record.get('business_result_correct', record['result_correct']))
                            record.update(success=business_ok, answer_count=1,
                                          answer_correct=int(business_ok), turns=[{'trace': trace(current)}])
                        record['usage'] = session.usage()
                except IncompleteRun:
                    raise
                except Exception as exc:
                    count = sum('gold_sql' in t for t in item.get('turns', [item]))
                    record = {'success': False, 'result_correct': False, 'business_result_correct': False,
                              'output_contract_compliant': False, 'answer_count': count, 'answer_correct': 0,
                              'error': type(exc).__name__, 'usage': session.usage() if session else (_call_usage(call_name) if call_name else {k: 0 for k in USAGE_KEYS})}
                finally:
                    if session and not any(not run.done for key, run in session.api.RUNS.items() if key in session.turn_ids):
                        session.close()
                record.update(scenario_base(item), latency_ms=round((time.monotonic()-started)*1000),
                              model_call_attempts=attempted_calls-attempts_before)
                record['usage_complete'] = record['usage']['calls'] == record['model_call_attempts']
                record['prompt_traces'] = prompt_traces[attempts_before:]
                write(record)
                print(f"{args.variant} {item['id']}: {'PASS' if record['success'] else 'FAIL'}", flush=True)
                if budget_exhausted:
                    raise IncompleteRun('Model-call budget exhausted; result file deliberately lacks run_complete')
            write({'type': 'run_complete', 'scenarios': len(scenarios)})
        finally:
            llm.generate_structured = original_generate
    return 0


def matrix(args, directory: Path):
    variants = list(SUITES[args.suite])
    schedule = []
    for repeat in range(1, args.repeats+1):
        shift = (repeat-1) % len(variants)
        for variant in variants[shift:]+variants[:shift]:
            output = _project_path(args.output_dir) / f'{args.suite}-{args.split}-{variant}-r{repeat}.jsonl'
            command = [sys.executable, str(Path(__file__).resolve()), '--dataset-dir', str(directory), '--suite', args.suite,
                       '--split', args.split, '--variant', variant, '--repeat', str(repeat), '--output', str(output),
                       '--model', args.model or 'MODEL', '--max-model-calls', str(args.max_model_calls or 0),
                       '--max-clarification-rounds', str(args.max_clarification_rounds), '--turn-timeout', str(args.turn_timeout), '--execute']
            if args.protocol:
                command.extend(['--protocol', str(_project_path(args.protocol))])
            schedule.append({'variant': variant, 'repeat': repeat, 'output': str(output), 'command': command})
    if not args.execute:
        print(json.dumps({'mode': 'dry_run', 'suite': args.suite, 'runs': schedule, 'model_calls': 0}, indent=2))
        return 0
    if args.split == 'test' and not args.protocol:
        raise ValueError('Live test matrix requires a frozen --protocol')
    # All outputs checked before any paid call; reruns should use a fresh directory.
    if any(Path(row['output']).exists() for row in schedule):
        raise ValueError('Matrix output exists; use a fresh output directory for a complete block')
    for row in schedule:
        env = os.environ.copy(); env.pop('TEXA_MEMORY_MODE', None); env.pop('TEXA_ABLATION_VARIANT', None)
        subprocess.run(row['command'], cwd=ROOT, env=env, check=True)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset-dir', default=str(ROOT / 'data/benchmark/ablation_v1'))
    parser.add_argument('--suite', choices=SUITES, default='memory')
    parser.add_argument('--split', choices=('dev', 'test'), default='dev')
    parser.add_argument('--variant', choices=('F', 'M6', 'M0', 'C0', 'B0'), default='F')
    parser.add_argument('--model')
    parser.add_argument('--protocol', help='Frozen study configuration JSON; mandatory for live test')
    parser.add_argument('--freeze-protocol', help='Write selected inputs/config after dev is finalized; no provider calls')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--matrix', action='store_true')
    parser.add_argument('--execute', action='store_true', help='Make paid provider calls; requires model and call budget')
    parser.add_argument('--gold', action='store_true', help='Only check SQL/reference tables, no provider calls')
    parser.add_argument('--max-model-calls', type=int)
    parser.add_argument('--max-clarification-rounds', type=int, default=2)
    parser.add_argument('--turn-timeout', type=int, default=150)
    parser.add_argument('--output', default=str(ROOT / 'backend/eval/results' / f'ablation-{uuid.uuid4().hex}.jsonl'))
    parser.add_argument('--output-dir', default=str(ROOT / 'backend/eval/results' / f'study-{uuid.uuid4().hex[:12]}'))
    args = parser.parse_args(argv)
    os.environ['TEXA_SOURCE_PROFILE'] = 'evaluation'
    configure_gateway_from_environment(ROOT / '.runtime')
    directory = _project_path(args.dataset_dir)
    from validate_dataset import validate_ablation_dataset, validate_dataset, validate_remediation_ablation
    if (directory / 'interactions.yaml').exists():
        if yaml.safe_load((directory / 'manifest.yaml').read_text()).get('status') == 'candidate_not_sealed':
            validate_remediation_ablation(directory)
        else:
            validate_ablation_dataset(directory)
    else:
        annotated = validate_dataset(directory)
        lock = directory / 'validation.json'
        if lock.exists() and json.loads(lock.read_text()) != annotated:
            raise ValueError('Dataset validation lock does not match inputs')
    if min(args.repeat, args.repeats, args.turn_timeout, args.max_clarification_rounds) < 1:
        parser.error('repeat/time/clarification limits must be positive')
    if args.variant not in SUITES[args.suite]:
        parser.error('variant does not belong to this suite')
    if args.freeze_protocol and (args.execute or args.gold or args.matrix or args.split != 'dev'):
        parser.error('--freeze-protocol is a provider-free dev-only operation')
    if args.gold and (args.execute or args.matrix):
        parser.error('--gold cannot be combined with --execute or --matrix')
    if (args.execute or args.freeze_protocol) and (not args.model or not args.max_model_calls or args.max_model_calls < 1):
        parser.error('live runs require --model and a positive --max-model-calls budget per process')
    scenarios = load_suite(directory, args.suite, args.split)
    if args.freeze_protocol:
        frozen = protocol(args, preflight(args, directory, scenarios))
        path = _project_path(args.freeze_protocol)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as handle:
            json.dump(frozen, handle, ensure_ascii=False, indent=2)
        print(json.dumps({'mode': 'freeze_protocol', 'path': str(path), 'model_calls': 0}))
        return 0
    if args.gold:
        return gold_run(args, directory, scenarios)
    if args.matrix:
        return matrix(args, directory)
    if not args.execute:
        print(json.dumps({'mode': 'dry_run', 'suite': args.suite, 'variant': args.variant, 'split': args.split,
                          'scenarios': len(scenarios), 'ids': [row['id'] for row in scenarios], 'model_calls': 0}, indent=2))
        return 0
    return execute(args, directory, scenarios)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, IncompleteRun) as exc:
        sys.exit(str(exc))
