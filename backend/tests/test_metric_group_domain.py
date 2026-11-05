"""Metric group domains: compare compiled PostgreSQL with independent business SQL.

The opt-in integration uses only transaction-local temporary tables; no fixture
or demo warehouse is mutated and Docker is not needed.
"""
import os
from pathlib import Path

import psycopg
import pytest
import yaml
from psycopg.rows import dict_row

from texa import catalog
from texa.compile import compile_spec
from texa.sanity import check_availability
from texa.spec import validate_spec

ROOT = Path(__file__).resolve().parents[2]


def product():
    cat = catalog.validate_catalog(yaml.safe_load((ROOT / 'catalog/product_events.yaml').read_text()))
    source = catalog.Source(id='olist_marketplace', label='Olist fixture', description='', currency='BRL',
        min_date='2025-01-01', max_date='2025-01-06', row_count=8, user_count=5,
        events={'order_purchased', 'payment_made', 'order_approved'}, columns={'revenue', 'item_category'})
    return cat, {source.id: source}


def compiled(cat, sources, metric, *, selection=None, time_range=None):
    spec = validate_spec({'source_ids': ['olist_marketplace'], 'contract_version': cat.contract_version,
        'recipe': metric, 'shape': ('time_trend' if selection and selection[0] in {'event_date', 'event_week', 'event_month'} else 'breakdown') if selection else 'aggregate', 'selection': selection or [],
        'time_range': time_range or {'kind': 'all'}}, cat, sources)
    return compile_spec(spec, cat, check_availability(spec, cat, sources))


def test_domain_is_catalog_owned_and_legacy_default_is_preserved():
    cat, sources = product()
    assert all(m.group_domain == 'metric_support' for m in cat.metrics)
    raw = cat.model_dump()
    for m in raw['metrics']:
        del m['group_domain']
    legacy = catalog.validate_catalog(raw)
    assert all(m.group_domain == 'filtered_events' for m in legacy.metrics)
    query = compiled(cat, sources, 'revenue', selection=['item_category']).query.as_string(None)
    old_query = compiled(legacy, sources, 'revenue', selection=['item_category']).query.as_string(None)
    assert 'AND (' in query.split(' GROUP BY')[0].split(' WHERE ')[-1]
    assert query != old_query
    with pytest.raises(ValueError):
        catalog.Metric.model_validate({**cat.mets['revenue'].model_dump(), 'group_domain': 'drop_zero_groups'})


@pytest.fixture
def conn():
    dsn = os.environ.get('TEXA_COMPILER_TEST_DSN')
    if not dsn:
        pytest.skip('set TEXA_COMPILER_TEST_DSN for isolated PostgreSQL business-number checks')
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        assert connection.execute('SELECT current_database() AS db').fetchone()['db'] == 'texa_benchmark'
        connection.execute('CREATE TEMP TABLE activity (source_id text, event_date date, event_name text, user_id text, item_category text, revenue numeric)')
        connection.execute('CREATE TEMP TABLE registry (source_id text, max_date date)')
        connection.execute("INSERT INTO registry VALUES ('olist_marketplace','2025-01-06')")
        for day, event, user, category, revenue in [
            ('01', 'order_purchased', 'A', 'skin', 10),
            ('01', 'order_purchased', 'A', 'skin', 0),
            ('02', 'payment_made', 'A', 'payment_only', 500),
            ('03', 'order_purchased', 'B', None, 0),
            ('04', 'order_approved', 'C', 'browsing', None),
            ('05', 'order_purchased', 'D', 'hair', -10),
            ('05', 'order_purchased', 'E', 'hair', 10),
            ('06', 'order_purchased', None, 'unknown_user', 10),
        ]:
            connection.execute('INSERT INTO activity VALUES (%s,%s,%s,%s,%s,%s)',
                ('olist_marketplace', f'2025-01-{day}', event, user, category, revenue))
        yield connection
        connection.rollback()


def execute(connection, query):
    # Only redirect the compiler's two physical tables to session-private test
    # relations. Aggregation, predicates and parameters remain exactly compiled.
    text = query.query.as_string(connection).replace('analytics.event_activity', 'pg_temp.activity').replace(
        'analytics.source_registry', 'pg_temp.registry')
    return connection.execute(text, query.params).fetchall()


def test_revenue_groups_exclude_payment_only_but_keep_real_zero_and_null(conn):
    cat, sources = product()
    actual = execute(conn, compiled(cat, sources, 'revenue', selection=['item_category']))
    expected = conn.execute("SELECT item_category, sum(revenue) AS revenue FROM activity WHERE event_name='order_purchased' GROUP BY item_category").fetchall()
    assert {r['item_category']: r['revenue'] for r in actual} == {r['item_category']: r['revenue'] for r in expected}
    assert {r['item_category']: r['revenue'] for r in actual}['hair'] == 0
    assert {r['item_category']: r['revenue'] for r in actual}[None] == 0
    daily = execute(conn, compiled(cat, sources, 'revenue', selection=['event_date']))
    assert [r['event_date'].day for r in daily] == [1, 3, 5, 6]


def test_buyers_use_purchase_row_domain_not_nonzero_result_filter(conn):
    cat, sources = product()
    actual = execute(conn, compiled(cat, sources, 'buyers', selection=['item_category']))
    expected = conn.execute("SELECT item_category, count(DISTINCT user_id) AS buyers FROM activity WHERE event_name='order_purchased' GROUP BY item_category").fetchall()
    assert {r['item_category']: r['buyers'] for r in actual} == {r['item_category']: r['buyers'] for r in expected}
    assert next(r for r in actual if r['item_category'] == 'unknown_user')['buyers'] == 0


def test_ratio_preserves_denominator_only_groups_and_zero_denominator(conn):
    cat, sources = product()
    actual = execute(conn, compiled(cat, sources, 'buyer_conversion_rate', selection=['item_category']))
    values = {r['item_category']: r['buyer_conversion_rate'] for r in actual}
    assert values['browsing'] == 0
    assert values['payment_only'] == 0
    assert values['unknown_user'] is None
    assert values['skin'] == values['hair'] == values[None] == 1
    total = execute(conn, compiled(cat, sources, 'buyer_conversion_rate'))
    assert float(total[0]['buyer_conversion_rate']) == pytest.approx(4 / 5)


def test_empty_period_aggregate_zero_but_no_invented_groups(conn):
    cat, sources = product()
    period = {'kind': 'between', 'start': '2025-02-01', 'end': '2025-02-01'}
    assert execute(conn, compiled(cat, sources, 'revenue', time_range=period))[0]['revenue'] == 0
    assert execute(conn, compiled(cat, sources, 'buyers', selection=['item_category'], time_range=period)) == []
