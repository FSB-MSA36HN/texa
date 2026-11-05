"""Prepare/restore the isolated Playwright fixture; refuses all non-15433 DBs."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / ".runtime"
BACKUP = RUNTIME / "playwright-e2e-db-backup.json"
EXPECTED_DSN = "postgresql://postgres@127.0.0.1:15433/texa_benchmark"
READER_DSN = "postgresql://texa_reader:texa_reader@127.0.0.1:15433/texa_benchmark"
SOURCE_IDS = ("event_benchmark", "cosmetics_shop", "olist_marketplace")
TABLES = ("analytics.event_activity", "analytics.source_registry", "analytics.vocabulary")


def connection_dsn() -> str:
    # Never inherit the app's default 15432 connection for this fixture tool.
    dsn = os.environ.get("TEXA_DB_DSN", EXPECTED_DSN)
    with psycopg.connect(dsn, connect_timeout=3) as conn:
        if conn.info.dbname != "texa_benchmark" or conn.info.port != 15433:
            raise RuntimeError("E2E setup refuses any database other than texa_benchmark on port 15433")
    return dsn


def _columns(conn, table: str):
    schema, name = table.split(".")
    return conn.execute("SELECT column_name,data_type FROM information_schema.columns "
                        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                        (schema, name)).fetchall()


def _backup(conn) -> dict:
    source_array = list(SOURCE_IDS)
    data = {}
    for table in TABLES:
        cols = _columns(conn, table)
        rows = conn.execute(f"SELECT * FROM {table} WHERE source_id = ANY(%s)", (source_array,)).fetchall()
        data[table] = {"columns": [c["column_name"] for c in cols], "types": {c["column_name"]: c["data_type"] for c in cols},
                       "rows": rows}
    max_version = conn.execute("SELECT coalesce(max(version),0) AS version FROM app.catalog_versions").fetchone()["version"]
    return {"catalog_version_max": max_version, "tables": data}


def _restore_data(conn, snapshot: dict):
    ids = list(SOURCE_IDS)
    for table in TABLES:
        conn.execute(f"DELETE FROM {table} WHERE source_id = ANY(%s)", (ids,))
        details = snapshot["tables"][table]
        cols, types = details["columns"], details["types"]
        placeholders = []
        for col in cols:
            kind = types[col]
            cast = {"date": "::date", "timestamp with time zone": "::timestamptz",
                    "timestamp without time zone": "::timestamp", "numeric": "::numeric",
                    "jsonb": "::jsonb"}.get(kind, "")
            placeholders.append("%s" + cast)
        sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join(placeholders)})"
        for row in details["rows"]:
            values = []
            for col in cols:
                value, kind = row[col], types[col]
                if value is not None and kind == "jsonb": value = Jsonb(value)
                elif value is not None and kind == "date": value = date.fromisoformat(value)
                elif value is not None and kind == "timestamp with time zone": value = datetime.fromisoformat(value)
                elif value is not None and kind == "timestamp without time zone": value = datetime.fromisoformat(value)
                elif value is not None and kind == "numeric": value = Decimal(str(value))
                values.append(value)
            conn.execute(sql, values)
    conn.execute("DELETE FROM app.catalog_versions WHERE version > %s", (snapshot["catalog_version_max"],))


def restore() -> None:
    if not BACKUP.exists():
        return
    dsn = connection_dsn()
    snapshot = json.loads(BACKUP.read_text())
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        _restore_data(conn, snapshot)
    BACKUP.unlink()
    print("Restored prior isolated E2E source rows and catalog versions", flush=True)


def prepare() -> None:
    if BACKUP.exists():
        raise RuntimeError("An earlier E2E DB backup exists; run e2e_fixture.py restore before another study")
    os.environ["TEXA_DB_DSN"] = connection_dsn()
    os.environ["TEXA_READER_DSN"] = os.environ.get("TEXA_READER_DSN", READER_DSN)
    os.environ["TEXA_SOURCE_PROFILE"] = "evaluation"
    import psycopg
    with psycopg.connect(os.environ["TEXA_DB_DSN"], row_factory=dict_row) as conn:
        conn.execute((ROOT / "pipeline/sql/init/01_init.sql").read_text(), prepare=False)
    from texa import db
    db.migrate()
    with psycopg.connect(os.environ["TEXA_DB_DSN"], row_factory=dict_row) as conn:
        snapshot = _backup(conn)
    RUNTIME.mkdir(exist_ok=True)
    BACKUP.write_text(json.dumps(snapshot, default=str))
    BACKUP.chmod(0o600)
    try:
        with psycopg.connect(os.environ["TEXA_DB_DSN"], row_factory=dict_row) as conn:
            source_counts = conn.execute("SELECT source_id,count(*) AS n FROM analytics.event_activity "
                                         "WHERE source_id = ANY(%s) GROUP BY source_id", [list(SOURCE_IDS)]).fetchall()
            existing = {r["source_id"]: r["n"] for r in source_counts if r["source_id"] != "event_benchmark"}
            registry = {r["source_id"] for r in conn.execute(
                "SELECT source_id FROM analytics.source_registry WHERE source_id = ANY(%s)",
                [list(SOURCE_IDS[1:])]).fetchall()}
            if not existing and not registry:
                conn.execute((ROOT / "data/benchmark/multisource_v1/fixture.sql").read_text(), prepare=False)
            elif set(existing) != {"cosmetics_shop", "olist_marketplace"} or registry != set(existing):
                raise RuntimeError("E2E source diagnostics are partial; refusing to overwrite them")
            conn.execute("DELETE FROM analytics.source_registry WHERE source_id='event_benchmark'")
            conn.execute((ROOT / "data/benchmark/fixture.sql").read_text(), prepare=False)
            conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO texa_reader")
        from texa import catalog
        version = catalog.publish()
        check = db.reader_conn
        with check() as conn:
            result = conn.execute("SELECT count(*) AS n,coalesce(sum(revenue),0) AS revenue FROM analytics.event_activity "
                                  "WHERE source_id='event_benchmark'").fetchone()
            rows, revenue = result["n"], result["revenue"]
        if (rows, revenue) != (12, Decimal("135.00")):
            raise RuntimeError(f"fixture assertion failed: {rows} rows / {revenue} revenue")
        print(f"Prepared isolated evaluation catalog v{version}; 12 event rows, revenue 135", flush=True)
    except Exception:
        restore()
        raise


if __name__ == "__main__":
    if os.environ.get("TEXA_E2E_TEST_DSN") != "1":
        raise SystemExit("Set TEXA_E2E_TEST_DSN=1 to opt in to the isolated fixture helper")
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "restore"}:
        raise SystemExit("Usage: e2e_fixture.py prepare|restore")
    prepare() if sys.argv[1] == "prepare" else restore()
