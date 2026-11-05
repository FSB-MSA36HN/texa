"""Playwright-only API entry point: real app/DB, scripted provider responses.

Never imported by texa.main or production Docker entrypoints. Requires explicit
opt-in and the isolated benchmark database. This module does not read .env or use
any saved/API credentials, and all outbound provider entry points are blocked.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import asynccontextmanager

import psycopg

if os.environ.get('TEXA_E2E_TEST_DSN') != '1':
    raise RuntimeError('E2E server requires TEXA_E2E_TEST_DSN=1')

from texa import db, llm  # noqa: E402

for dsn in (db.DB_DSN, db.READER_DSN):
    with psycopg.connect(dsn) as conn:
        if conn.execute('SELECT current_database()').fetchone()[0] != 'texa_benchmark':
            raise RuntimeError('E2E server must use the isolated texa_benchmark database')
        if conn.info.port != 15433:
            raise RuntimeError('E2E server refuses database ports other than isolated port 15433')
with psycopg.connect(db.DB_DSN) as conn:
    rows, revenue = conn.execute(
        "SELECT count(*), coalesce(sum(revenue), 0) FROM analytics.event_activity WHERE source_id='event_benchmark'"
    ).fetchone()
    if rows != 12 or revenue != 135:
        raise RuntimeError(f'E2E fixture mismatch: expected 12 events and revenue 135, got {rows} and {revenue}')

# Evaluation switches must not accidentally alter the product behavior under test.
for name in ('TEXA_ABLATION_VARIANT', 'TEXA_MEMORY_MODE'):
    os.environ.pop(name, None)

os.environ['TEXA_SOURCE_PROFILE'] = 'evaluation'

MODEL = 'e2e-scripted-model'
_connection = {'provider': 'openai', 'base_url': None, 'allowed_models': [MODEL], 'default_model': MODEL,
               'max_output_tokens': 8192, 'daily_token_limit': 0, 'answer_language': 'vi'}
_errors: set[str] = set()
_lock = threading.Lock()


def connection(with_key=False):
    # Tests use fake credentials only; a real connection is never accessed.
    return dict(_connection, **({'api_key': 'e2e-fake-key'} if with_key else {}))


def blocked(*args, **kwargs):
    raise AssertionError('Outbound provider calls are disabled in E2E')


llm.get_connection = connection
llm.discover_models = lambda *a, **k: [{'id': MODEL, 'label': MODEL}]
for provider in list(llm._CALLS):
    llm._CALLS[provider] = blocked


def candidate(**changes):
    base = {'outcome': 'query', 'reason': '', 'reply': '', 'suggestions': [], 'source_ids': ['event_benchmark'],
            'shape': 'aggregate', 'selection': [], 'recipe': 'revenue', 'metrics': [], 'recipe_alternatives': [],
            'recipe_stated': True, 'filters': [], 'top_k': 0,
            'time_range': {'kind': 'all', 'days': 0, 'start': '', 'end': ''},
            'answer_request': {'need': 'describe', 'ask': ''}, 'language': 'vi'}
    from texa.memory import SLOT_KEYS
    base['dialogue'] = {'relation': 'social' if changes.get('outcome') == 'conversation' else 'new_topic',
                        'target_id': '', 'slots': {k: 'set' for k in SLOT_KEYS}}
    return base | changes


def generate(*, name, prompt, turn_id=None, model=None, **kwargs):
    if name == 'interpret':
        question = prompt.rsplit('QUESTION\n', 1)[-1].strip()
        if question == 'Gây lỗi model':
            with _lock:
                if turn_id not in _errors:
                    _errors.add(turn_id)
                    raise llm.LLMError('TIMEOUT', 'Lỗi model mô phỏng; có thể hỏi lại.')
        if question == 'Chạy chậm':
            # Wait in a cancellable way; no long provider sleep or real call.
            from texa import answer
            for _ in range(100):
                if turn_id in answer.RUNS and answer.RUNS[turn_id].cancel:
                    break
                time.sleep(.05)
        if question == 'Ngoài phạm vi':
            return candidate(outcome='unsupported', reason='Yêu cầu ngoài phạm vi e-commerce.', suggestions=[])
        if question == 'Xung đột nguồn':
            return candidate(source_ids=['olist_marketplace'])
        if question in ('Cảm ơn', 'Xin chào'):
            return candidate(outcome='conversation', reply='Rất vui được hỗ trợ bạn.', suggestions=[])
        if question == 'Doanh thu':
            return candidate(time_range={'kind': 'none', 'days': 0, 'start': '', 'end': ''})
        if question in ('Chia theo thiết bị', 'Chia kết quả đó theo thiết bị') or 'kết quả đầu tiên chia theo thiết bị' in question.lower():
            # The provider fixture selects an actual server-supplied pointer;
            # only the reducer is allowed to inherit its slots.
            registry = json.JSONDecoder().raw_decode(prompt.split('RESULT REGISTRY\n', 1)[1])[0]
            target = registry[0] if 'kết quả đầu tiên' in question.lower() else registry[-1] if registry else None
            if not target or target['reading']['recipe'] != 'revenue':
                raise llm.LLMError('E2E_NO_HISTORY', 'Không tìm thấy ngữ cảnh trước.')
            from texa.memory import SLOT_KEYS
            operations = {k: 'keep' for k in SLOT_KEYS}
            operations.update(selection='set', shape='set', top_k='clear')
            return candidate(shape='breakdown', selection=['device_type'],
                             dialogue={'relation': 'followup', 'target_id': target['id'], 'slots': operations})
        if question == 'Số người dùng toàn bộ dữ liệu':
            return candidate(recipe='users')
        return candidate()
    if name == 'insight':
        payload = json.loads(prompt)
        facts = [fact for fact in payload['facts'] if fact['id'] != 'f_rows' and fact['id'].startswith('f_')]
        fact = next((fact for fact in facts if 'revenue' in fact['id']), facts[0] if facts else None)
        headline = f"Kết quả kiểm thử: [[{fact['id']}]]" if fact else 'Kết quả kiểm thử đã sẵn sàng.'
        return {'headline': headline, 'body': [], 'caveats': [], 'follow_ups': [], 'assumptions': [], 'calculations': []}
    raise llm.LLMError('E2E_UNSCRIPTED', f'Unexpected scripted model stage: {name}')


llm.generate_structured = generate

from texa.main import app, lifespan as production_lifespan  # noqa: E402


@asynccontextmanager
async def e2e_lifespan(application):
    async with production_lifespan(application):
        yield
    # This test server owns only its dedicated E2E-created conversations.
    with db.app_conn() as conn:
        ids = conn.execute("SELECT DISTINCT conversation_id FROM app.turns WHERE model=%s", (MODEL,)).fetchall()
        for row in ids:
            conn.execute('DELETE FROM app.conversations WHERE id=%s', (row['conversation_id'],))


app.router.lifespan_context = e2e_lifespan
