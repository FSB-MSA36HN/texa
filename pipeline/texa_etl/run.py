"""ETL steps shared by the Airflow DAGs and the command line.

python -m texa_etl.run <source_id> [step ...]     (steps default to the full pipeline)
"""
import csv
import os
import re
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import psycopg

DSN = os.environ.get("TEXA_DW_DSN", "postgresql://texa:texa@localhost:15432/texa")
LANDING = Path(os.environ.get("TEXA_LANDING_DIR", Path(__file__).resolve().parents[2] / "data" / "landing"))
SQL_DIR = Path(os.environ.get("TEXA_SQL_DIR", Path(__file__).resolve().parents[1] / "sql"))

SOURCES = {
    "cosmetics_shop": {
        "label": "Cosmetics shop",
        "description": "Online cosmetics store event stream (REES46 Open CDP): product views, cart adds/removals and purchases with sessions. Prices in USD. No geography.",
        "currency": "USD",
        "kaggle": "mkechinov/ecommerce-events-history-in-cosmetics-shop",
        # Monthly files land in one raw table.
        "files": lambda: {"events": [f"{m.strip()}.csv" for m in os.environ.get("REES46_MONTHS", "2019-Dec,2020-Jan").split(",")]},
        "events": {"view", "cart", "remove_from_cart", "purchase"},
    },
    "olist_marketplace": {
        "label": "Olist marketplace",
        "description": "Brazilian marketplace orders (Olist): purchases per order item, approval, shipping, delivery, cancellation, payments and reviews. Prices in BRL. Geography by customer state and city.",
        "currency": "BRL",
        "kaggle": "olistbr/brazilian-ecommerce",
        "files": lambda: {
            "customers": ["olist_customers_dataset.csv"],
            "orders": ["olist_orders_dataset.csv"],
            "order_items": ["olist_order_items_dataset.csv"],
            "payments": ["olist_order_payments_dataset.csv"],
            "reviews": ["olist_order_reviews_dataset.csv"],
            "products": ["olist_products_dataset.csv"],
            "sellers": ["olist_sellers_dataset.csv"],
            "category_translation": ["product_category_name_translation.csv"],
        },
        "events": {"order_purchased", "order_approved", "order_shipped", "order_delivered",
                   "order_canceled", "payment_made", "review_submitted"},
    },
}

# Columns that identify rows rather than describe them; never worth a value vocabulary.
HIGH_CARDINALITY = {"item_id", "user_id", "session_id", "ep.order_id", "ep.seller_id", "ep.category_id",
                    "ep.order_item_id", "ep.review_id", "up.customer_zip_prefix"}
VALUE_FIELDS = ["event_name", "platform", "country", "region", "city", "item_category", "item_brand", "currency"]
MAX_VALUES = 5000
OPTIONAL_COLUMNS = ["session_id", "platform", "country", "region", "city", "item_id", "item_category",
                    "item_brand", "item_price", "quantity", "revenue", "revenue_usd"]

# Daily exchange rates (not a store): <quote> per 1 USD from FRED, public CSV, no key. Run before the stores so
# load_mart can fill revenue_usd: python -m texa_etl.run fx_rates
FX_SERIES = {"BRL": "DEXBZUS"}
FX_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd=2015-01-01"


def connect():
    return psycopg.connect(DSN, autocommit=False)


def log(cur, source_id, step, rows_in=None, rows_out=None, note=None):
    dropped = rows_in - rows_out if rows_in is not None and rows_out is not None else None
    cur.execute(
        "INSERT INTO analytics.etl_runs (source_id, step, rows_in, rows_out, rows_dropped, note) VALUES (%s,%s,%s,%s,%s,%s)",
        (source_id, step, rows_in, rows_out, dropped, note),
    )
    print(f"[{source_id}] {step}: in={rows_in} out={rows_out} dropped={dropped} {note or ''}")


def download(source_id):
    src = SOURCES[source_id]
    target = LANDING / source_id
    needed = [f for files in src["files"]().values() for f in files]
    if all((target / f).exists() for f in needed):
        print(f"[{source_id}] landing files present, skip download")
        return
    target.mkdir(parents=True, exist_ok=True)
    # Public Kaggle datasets download without an API key; only the CSVs the pipeline reads are extracted.
    archive = target / "_archive.zip"
    url = f"https://www.kaggle.com/api/v1/datasets/download/{src['kaggle']}"
    print(f"[{source_id}] downloading {url}")
    with urllib.request.urlopen(url, timeout=600) as r, open(archive, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    with zipfile.ZipFile(archive) as z:
        for name in needed:
            with z.open(name) as member, open(target / name, "wb") as out:
                shutil.copyfileobj(member, out, 1 << 20)
    archive.unlink()


def _header(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        # Header names become identifiers, so keep them to [a-z0-9_].
        return [re.sub(r"[^a-z0-9_]", "_", c.strip().lower()) for c in next(csv.reader(f))]


def load_raw(source_id):
    src = SOURCES[source_id]
    with connect() as conn, conn.cursor() as cur:
        for table, files in src["files"]().items():
            name = f"{source_id}__{table}"
            columns = _header(LANDING / source_id / files[0])
            cur.execute(f'DROP TABLE IF EXISTS raw."{name}"')
            cur.execute(f'CREATE TABLE raw."{name}" ({", ".join(f'"{c}" text' for c in columns)})')
            for file in files:
                path = LANDING / source_id / file
                if _header(path) != columns:
                    raise ValueError(f"{path}: header differs from {files[0]}")
                with cur.copy(f'COPY raw."{name}" FROM STDIN WITH (FORMAT csv, HEADER true)') as copy, open(path, "rb") as f:
                    while chunk := f.read(1 << 20):
                        copy.write(chunk)
            cur.execute(f'SELECT count(*) FROM raw."{name}"')
            log(cur, source_id, f"load_raw:{table}", rows_out=cur.fetchone()[0], note=",".join(files))


def _run_sql_files(cur, folder, params=None):
    for path in sorted((SQL_DIR / folder).glob("*.sql")):
        cur.execute(path.read_text(), params)


def stage(source_id):
    with connect() as conn, conn.cursor() as cur:
        _run_sql_files(cur, source_id)
        # Each staging script leaves (table, rows_in, rows_out) in a temp table for the run log.
        cur.execute("SELECT step, rows_in, rows_out, note FROM stage_log")
        for step, rows_in, rows_out, note in cur.fetchall():
            log(cur, source_id, f"stage:{step}", rows_in, rows_out, note)


def load_mart(source_id):
    print(f"[{source_id}] load_mart: rebuilding events (USD conversion included)", flush=True)
    with connect() as conn, conn.cursor() as cur:
        cur.execute((SQL_DIR / "fx" / "00_schema.sql").read_text())
        cur.execute("DELETE FROM analytics.event_activity WHERE source_id = %s", (source_id,))
        cur.execute((SQL_DIR / "mart" / f"{source_id}.sql").read_text())
        cur.execute("SELECT count(*), count(revenue), count(revenue_usd) FROM analytics.event_activity WHERE source_id = %s",
                    (source_id,))
        rows, with_revenue, converted = cur.fetchone()
        note = f"revenue_usd {converted}/{with_revenue}" + ("" if converted == with_revenue else " (missing rates: run fx_rates)")
        log(cur, source_id, "load_mart", rows_out=rows, note=note)
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"ANALYZE analytics.event_activity_{source_id}")


def refresh_revenue_usd(source_id):
    """Recompute USD amounts in place after loading rates, without rebuilding events."""
    print(f"[{source_id}] refresh_revenue_usd: converting revenue", flush=True)
    with connect() as conn, conn.cursor() as cur:
        cur.execute((SQL_DIR / "fx" / "00_schema.sql").read_text())
        cur.execute((SQL_DIR / "fx" / "10_revenue_usd.sql").read_text(), {"source_id": source_id})
        updated = cur.rowcount
        cur.execute("SELECT count(revenue), count(revenue_usd) FROM analytics.event_activity WHERE source_id = %s",
                    (source_id,))
        with_revenue, converted = cur.fetchone()
        note = f"revenue_usd {converted}/{with_revenue}" + ("" if converted == with_revenue else " (missing rates: run fx_rates)")
        log(cur, source_id, "refresh_revenue_usd", rows_out=updated, note=note)


def quality_checks(source_id):
    failures = []
    with connect() as conn, conn.cursor() as cur:
        for path in sorted((SQL_DIR / "quality").glob("*.sql")):
            cur.execute(path.read_text(), {"source_id": source_id})
            rows = cur.fetchall()
            if rows:
                failures.append(f"{path.stem}: {rows[:5]}")
        cur.execute("SELECT DISTINCT event_name FROM analytics.event_activity WHERE source_id = %s", (source_id,))
        unexpected = {r[0] for r in cur.fetchall()} - SOURCES[source_id]["events"]
        if unexpected:
            failures.append(f"unexpected event names: {sorted(unexpected)}")
        log(cur, source_id, "quality_checks", note="ok" if not failures else f"{len(failures)} failed")
    if failures:
        raise RuntimeError(f"{source_id} quality checks failed:\n" + "\n".join(failures))


def refresh_metadata(source_id):
    src = SOURCES[source_id]
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO analytics.source_registry AS r
              (source_id, label, description, currency, min_date, max_date, row_count, user_count, last_loaded_at)
            SELECT %(s)s, %(label)s, %(description)s, %(currency)s, min(event_date), max(event_date),
                   count(*), count(DISTINCT user_id), now()
            FROM analytics.event_activity WHERE source_id = %(s)s
            ON CONFLICT (source_id) DO UPDATE SET label = EXCLUDED.label, description = EXCLUDED.description,
              currency = EXCLUDED.currency, min_date = EXCLUDED.min_date, max_date = EXCLUDED.max_date,
              row_count = EXCLUDED.row_count, user_count = EXCLUDED.user_count, last_loaded_at = EXCLUDED.last_loaded_at
            """,
            {"s": source_id, "label": src["label"], "description": src["description"], "currency": src["currency"]},
        )
        cur.execute("DELETE FROM analytics.vocabulary WHERE source_id = %s", (source_id,))
        for kind, select in (
            ("event_name", "SELECT event_name, count(*), max(event_date) FROM analytics.event_activity WHERE source_id = %(s)s GROUP BY 1"),
            ("ep_key", "SELECT k, count(*), max(event_date) FROM analytics.event_activity, jsonb_object_keys(ep) k WHERE source_id = %(s)s GROUP BY 1"),
            ("up_key", "SELECT k, count(*), max(event_date) FROM analytics.event_activity, jsonb_object_keys(up) k WHERE source_id = %(s)s GROUP BY 1"),
        ):
            field = {"event_name": "event_name", "ep_key": "ep", "up_key": "up"}[kind]
            cur.execute(
                f"INSERT INTO analytics.vocabulary (source_id, kind, field, value, event_count, last_seen) "
                f"SELECT %(s)s, '{kind}', '{field}', v.* FROM ({select}) v",
                {"s": source_id},
            )
        # Optional top-level columns a source actually fills (cosmetics has no geography, olist no brand).
        cur.execute(
            "INSERT INTO analytics.vocabulary (source_id, kind, field, value, event_count, last_seen) "
            "SELECT %(s)s, 'column', 'column', c, n, NULL FROM ("
            + " UNION ALL ".join(
                f"SELECT '{c}' AS c, (SELECT count({c}) FROM analytics.event_activity WHERE source_id = %(s)s) AS n"
                for c in OPTIONAL_COLUMNS)
            + ") t WHERE n > 0",
            {"s": source_id},
        )
        # Values of low-cardinality fields: top-level columns plus every ep/up key not marked high-cardinality.
        cur.execute("SELECT field || '.' || value FROM analytics.vocabulary WHERE source_id = %s AND kind IN ('ep_key','up_key')", (source_id,))
        fields = VALUE_FIELDS + [r[0] for r in cur.fetchall()]
        for field in fields:
            if field in HIGH_CARDINALITY:
                continue
            expr = f"({field.split('.')[0]} ->> '{field.split('.', 1)[1]}')" if "." in field else field
            cur.execute(
                f"""
                WITH v AS (
                  SELECT {expr} AS value, count(*) AS n, max(event_date) AS last_seen
                  FROM analytics.event_activity WHERE source_id = %(s)s AND {expr} IS NOT NULL GROUP BY 1
                )
                INSERT INTO analytics.vocabulary (source_id, kind, field, value, event_count, last_seen)
                SELECT %(s)s, 'value', %(f)s, value, n, last_seen FROM v
                WHERE (SELECT count(*) FROM v) <= {MAX_VALUES}
                """,
                {"s": source_id, "f": field},
            )
        cur.execute("SELECT kind, count(*) FROM analytics.vocabulary WHERE source_id = %s GROUP BY kind ORDER BY kind", (source_id,))
        log(cur, source_id, "refresh_metadata", note=str(dict(cur.fetchall())))


def load_fx_rates(_=None):
    """Download each FX series and upsert it; FRED leaves holidays blank ("" or "."), which are skipped."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute((SQL_DIR / "fx" / "00_schema.sql").read_text())
        for quote, series in FX_SERIES.items():
            url = FX_URL.format(series=series)
            print(f"[fx_rates] downloading {url}")
            with urllib.request.urlopen(url, timeout=120) as r:
                rows = list(csv.reader(r.read().decode("utf-8-sig").splitlines()))
            parsed = [(d, float(v)) for d, v in rows[1:] if v not in ("", ".")]
            if not parsed:
                raise RuntimeError(f"{series}: no rates in the download")
            cur.executemany(
                "INSERT INTO analytics.fx_rates (rate_date, base, quote, rate, source) VALUES (%s, 'USD', %s, %s, %s) "
                "ON CONFLICT (base, quote, rate_date) DO UPDATE SET rate = EXCLUDED.rate, source = EXCLUDED.source",
                [(d, quote, v, f"FRED {series}") for d, v in parsed])
            log(cur, "fx_rates", f"load:{quote}", rows_in=len(rows) - 1, rows_out=len(parsed),
                note=f"{parsed[0][0]}..{parsed[-1][0]}")


STEPS = {f.__name__: f for f in (download, load_raw, stage, load_mart, refresh_revenue_usd, quality_checks, refresh_metadata)}
PIPELINE = ["download", "load_raw", "stage", "load_mart", "refresh_metadata", "quality_checks"]

if __name__ == "__main__":
    source, *steps = sys.argv[1:]
    if source == "fx_rates":
        load_fx_rates()
        sys.exit()
    for step in steps or PIPELINE:
        STEPS[step](source)
