"""Run compiled SQL as the read-only reader role."""
import datetime as dt
import time
from decimal import Decimal

from psycopg import ClientCursor

from . import db
from .compile import Compiled


def _json_value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def is_public_column(name: str) -> bool:
    """Compiler auxiliary columns are diagnostics, never part of the answer table."""
    return not name.startswith("__")


def display_sql(compiled: Compiled) -> str:
    """The query with parameters inlined, for people to read and copy (never executed)."""
    with db.reader_conn() as conn:
        return ClientCursor(conn).mogrify(compiled.query, compiled.params)


def run(compiled: Compiled, limit: int) -> dict:
    started = time.monotonic()
    with db.reader_conn() as conn:
        rows = conn.execute(compiled.query, compiled.params).fetchall()
    partial = len(rows) > limit
    rows = rows[:limit]
    clean, samples = [], []
    for r in rows:
        clean.append({k: _json_value(v) for k, v in r.items() if is_public_column(k)})
        samples.append({k[len("__sample_"):]: _json_value(v) for k, v in r.items() if k.startswith("__sample_")})
    return {"rows": clean, "samples": samples, "row_count": len(clean), "partial": partial,
            "ms": int((time.monotonic() - started) * 1000)}
