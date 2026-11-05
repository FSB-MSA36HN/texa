import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from eval.gateway_budget import (GatewayBudgetGuard, configure_gateway_from_environment,
                                 update_ledger, validate_credentials_path)


def ledger(path: Path, **kwargs):
    return update_ledger(path, path.with_suffix('.lock'), model='m1', input_price=0.001,
                         output_price=0.002, max_usd=kwargs.pop('max_usd', 1.0), **kwargs)


def test_reservation_settlement_and_budget_refusal(tmp_path):
    path = tmp_path / 'ledger.json'
    reserved = ledger(path, reserve=0.4)
    assert reserved['reserved_usd'] == pytest.approx(0.4)
    settled = ledger(path, release=0.4, actual=0.3, usage=(10, 0, 5))
    assert settled['reserved_usd'] == pytest.approx(0)
    assert settled['spent_estimated_usd'] == pytest.approx(0.3)
    assert (settled['calls'], settled['input_tokens'], settled['output_tokens']) == (1, 10, 5)
    with pytest.raises(RuntimeError, match='budget exhausted'):
        ledger(path, reserve=0.6, release=0, actual=0.2)
    assert json.loads(path.read_text())['spent_estimated_usd'] == pytest.approx(0.3)


def test_concurrent_reservations_are_serialized(tmp_path):
    path = tmp_path / 'ledger.json'

    def reserve_one(_):
        try:
            ledger(path, max_usd=1.0, reserve=0.2)
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        outcomes = list(pool.map(reserve_one, range(12)))
    data = json.loads(path.read_text())
    assert sum(outcomes) == 5
    assert data['reserved_usd'] == pytest.approx(1.0)


def test_unknown_usage_keeps_reservation(tmp_path):
    path = tmp_path / 'ledger.json'
    ledger(path, reserve=0.7)
    # No settlement call is made when the provider outcome/usage is unknown.
    data = json.loads(path.read_text())
    assert data['reserved_usd'] == pytest.approx(0.7)
    assert data['spent_estimated_usd'] == 0


def test_actual_cost_is_included_in_ceiling(tmp_path):
    path = tmp_path / 'ledger.json'
    ledger(path, reserve=0.8)
    with pytest.raises(RuntimeError, match='budget exhausted'):
        ledger(path, release=0.8, actual=1.01)
    assert json.loads(path.read_text())['reserved_usd'] == pytest.approx(0.8)


def test_credentials_path_and_mode_bounds(tmp_path):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    private = runtime / 'private.json'
    private.write_text('{}')
    private.chmod(0o600)
    assert validate_credentials_path(private, runtime) == private.resolve()
    private.chmod(0o640)
    with pytest.raises(ValueError, match='owner-only'):
        validate_credentials_path(private, runtime)
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    with pytest.raises(ValueError):
        validate_credentials_path(outside, runtime)


def test_reservation_ids_are_process_safe_and_settle_once(tmp_path):
    path = tmp_path / 'ledger.json'
    ledger(path, reserve=0.25, reservation_id='call-1')
    with pytest.raises(ValueError, match='Duplicate'):
        ledger(path, reserve=0.25, reservation_id='call-1')
    ledger(path, release=0.25, actual=0.1, usage=(10, 0, 5), reservation_id='call-1')
    with pytest.raises(RuntimeError, match='Unknown'):
        ledger(path, release=0.25, actual=0.1, reservation_id='call-1')


def test_guard_settles_usage_and_retains_unknown_charge(tmp_path):
    path = tmp_path / 'ledger.json'
    guard = GatewayBudgetGuard(path, 'm1', .000001, .000002, 1)
    result = guard(model='m1', system='s', prompt='p', schema={}, max_tokens=20,
                   invoke=lambda: ('{}', (10, 0, 5), 'ok'))
    assert result[1] == (10, 0, 5)
    data = json.loads(path.read_text())
    assert data['calls'] == 1 and data['reserved_usd'] == 0
    with pytest.raises(Exception, match='conservative budget reservation retained'):
        guard(model='m1', system='s', prompt='p', schema={}, max_tokens=20,
              invoke=lambda: (_ for _ in ()).throw(TimeoutError()))
    data = json.loads(path.read_text())
    assert data['reserved_usd'] > 0


def test_child_environment_installs_same_guard_without_environment_key(tmp_path, monkeypatch):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    credentials = runtime / 'credentials.json'
    credentials.write_text(json.dumps({"model": "m1", "base_url": "https://gateway.invalid/v1",
                                       "api_key": "never-copy-this", "max_usd": 1}))
    credentials.chmod(0o600)
    ledger_path = runtime / 'ledger.json'
    for key, value in {
        'TEXA_GATEWAY_BUDGET_CREDENTIALS': str(credentials),
        'TEXA_GATEWAY_BUDGET_LEDGER': str(ledger_path),
        'TEXA_GATEWAY_INPUT_PRICE': '.001', 'TEXA_GATEWAY_OUTPUT_PRICE': '.002',
        'TEXA_GATEWAY_MAX_USD': '1',
    }.items():
        monkeypatch.setenv(key, value)
    from texa import llm
    prior_guard = llm.REQUEST_GUARD
    prior_connection = llm.get_connection
    try:
        assert configure_gateway_from_environment(runtime)
        assert llm.REQUEST_GUARD is not None
        assert all('never-copy-this' not in value for value in __import__('os').environ.values())
        monkeypatch.setenv('TEXA_GATEWAY_BUDGET_LEDGER', str(tmp_path / 'outside.json'))
        with pytest.raises(ValueError):
            configure_gateway_from_environment(runtime)
    finally:
        llm.REQUEST_GUARD = prior_guard
        llm.get_connection = prior_connection


def test_runtime_configuration_fetches_pricing_without_exposing_key(tmp_path, monkeypatch):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    credentials = runtime / 'credentials.json'
    credentials.write_text(json.dumps({"model": "m1", "base_url": "https://gateway.invalid/v1",
                                       "api_key": "protected-value", "max_usd": 1}))
    credentials.chmod(0o600)
    monkeypatch.setenv('TEXA_GATEWAY_BUDGET_CREDENTIALS', str(credentials))
    monkeypatch.setenv('TEXA_GATEWAY_BUDGET_LEDGER', str(runtime / 'ledger.json'))
    monkeypatch.delenv('TEXA_GATEWAY_INPUT_PRICE', raising=False)
    monkeypatch.delenv('TEXA_GATEWAY_OUTPUT_PRICE', raising=False)
    import httpx
    seen = {}
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"data": [{"model_name": "m1", "model_info": {
                "input_cost_per_token": .000001, "output_cost_per_token": .000002}}]}
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs: seen.update(url=url, **kwargs) or Response())
    from texa import llm
    prior_guard = llm.REQUEST_GUARD
    prior_connection = llm.get_connection
    try:
        assert configure_gateway_from_environment(runtime)
        assert seen['url'] == 'https://gateway.invalid/model/info'
        assert seen['headers']['Authorization'] == 'Bearer protected-value'
        assert all('protected-value' not in value for value in __import__('os').environ.values())
    finally:
        llm.REQUEST_GUARD = prior_guard
        llm.get_connection = prior_connection


def test_each_retry_is_reserved_separately_and_unknown_attempt_stays_held(tmp_path, monkeypatch):
    from texa import llm
    path = tmp_path / 'ledger.json'
    guard = GatewayBudgetGuard(path, 'm1', .000001, .000002, 1)
    calls = []
    def provider(*_):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError('injected transport fault')
        return '{}', (10, 0, 5), 'ok'
    monkeypatch.setitem(llm._CALLS, 'openai', provider)
    monkeypatch.setattr(llm.time, 'sleep', lambda _: None)
    result = llm._provider_request('openai', {}, 'm1', 's', 'p', {}, 'n', 20, guard)
    data = json.loads(path.read_text())
    assert result[2] == 'ok' and len(calls) == 2
    assert data['calls'] == 1 and data['reserved_usd'] > 0
    assert len(data['reservations']) == 1  # first timeout remains uncharged/unknown


def test_independent_processes_cannot_over_reserve_shared_budget(tmp_path):
    import subprocess
    import sys
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    backend = Path(__file__).resolve().parents[1]
    path = tmp_path / 'shared.json'
    script = '''
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from texa.gateway_budget import update_ledger
p=Path(sys.argv[2])
try:
    update_ledger(p,p.with_suffix('.lock'),model='m',input_price=.001,output_price=.002,
                  max_usd=1,reserve=.11,reservation_id=sys.argv[3])
except RuntimeError:
    sys.exit(3)
'''
    def reserve(i):
        return subprocess.run([sys.executable, '-c', script, str(backend), str(path), str(i)],
                              capture_output=True, check=False).returncode
    with ThreadPoolExecutor(max_workers=12) as executor:
        codes = list(executor.map(reserve, range(12)))
    data = json.loads(path.read_text())
    assert codes.count(0) == 9 and codes.count(3) == 3
    assert data['reserved_usd'] == pytest.approx(.99)
    assert len(data['reservations']) == 9
