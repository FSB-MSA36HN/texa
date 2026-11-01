"""Settings and database access. Two connections: the app owner (writes app.*) and the read-only reader
that runs compiled SQL against analytics.*."""
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DB_DSN = os.environ.get("TEXA_DB_DSN", "postgresql://texa:texa@localhost:15432/texa")
READER_DSN = os.environ.get("TEXA_READER_DSN", "postgresql://texa_reader:texa_reader@localhost:15432/texa")
CATALOG_PATH = Path(os.environ.get("TEXA_CATALOG", Path(__file__).resolve().parents[2] / "catalog" / "product_events.yaml"))
CONTEXT_BUDGET_TOKENS = int(os.environ.get("TEXA_CONTEXT_BUDGET", "32000"))
RESULT_LIMIT = 2000
PREVIEW_ROWS = 100

_pools: dict[str, ConnectionPool] = {}


def _pool(dsn: str) -> ConnectionPool:
    if dsn not in _pools:
        _pools[dsn] = ConnectionPool(dsn, min_size=1, max_size=8, kwargs={"row_factory": dict_row}, open=True)
    return _pools[dsn]


@contextmanager
def app_conn():
    with _pool(DB_DSN).connection() as conn:
        yield conn


@contextmanager
def reader_conn():
    with _pool(READER_DSN).connection() as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '30s'")
        yield conn


SCHEMA_SQL = (Path(__file__).with_name("schema.sql")).read_text()


def migrate():
    with psycopg.connect(DB_DSN, autocommit=True) as conn:
        conn.execute(SCHEMA_SQL)
