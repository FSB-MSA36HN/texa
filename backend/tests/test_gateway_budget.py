import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from eval.gateway_budget import update_ledger, validate_credentials_path


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
