"""Independent result oracle: computes gold answers straight from the raw source CSV files with DuckDB.

Definitions live in data/benchmark/research_v4/GLOSSARY.md. This module deliberately imports nothing from `texa`,
does not read the ETL mart or the catalog, and does not share code with data/benchmark/research_v3/generate.py.
A match between this oracle and gold SQL run on the ETL-loaded PostgreSQL warehouse therefore checks the ETL mapping
and the SQL together against the raw data.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LANDING = ROOT / "data" / "landing"

PURCHASE = {"cosmetics_shop": "purchase", "olist_marketplace": "order_purchased"}
SOURCE_METRICS = {
    "cosmetics_shop": ("events", "users", "sessions", "viewers", "purchases", "buyers", "revenue", "buyer_conversion_rate"),
    "olist_marketplace": ("events", "users", "purchases", "buyers", "revenue", "buyer_conversion_rate"),
}
FIELDS = {"event_date": "day", "event_name": "event", "item_category": "category"}


class OracleError(ValueError):
    pass


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class RawOracle:
    def __init__(self, landing: Path = DEFAULT_LANDING):
        self.landing = Path(landing)
        self.db = duckdb.connect(":memory:")
        self._build_cosmetics()
        self._build_olist()

    # ------------------------------------------------------------------ views
    def _csv(self, relative: str) -> str:
        path = self.landing / relative
        return f"read_csv({_q(str(path))}, header=true, all_varchar=true)"

    def _build_cosmetics(self):
        files = sorted((self.landing / "cosmetics_shop").glob("*.csv"))
        if not files:
            raise OracleError(f"no cosmetics CSV files under {self.landing}")
        self.db.execute(f"""
            CREATE TABLE cos AS
            WITH raw AS (SELECT DISTINCT * FROM read_csv({_q(str(self.landing / 'cosmetics_shop' / '*.csv'))},
                                                      header=true, all_varchar=true))
            SELECT 'cosmetics_shop' AS source,
                   CAST(substr(trim(event_time), 1, 10) AS DATE) AS day,
                   trim(event_type) AS event,
                   trim(user_id) AS usr,
                   NULLIF(trim(user_session), '') AS session,
                   NULLIF(split_part(trim(category_code), '.', 1), '') AS category,
                   CASE WHEN trim(event_type) = 'purchase' AND TRY_CAST(price AS DECIMAL(18,2)) > 0
                        THEN CAST(price AS DECIMAL(18,2)) END AS revenue
            FROM raw
            WHERE NULLIF(trim(event_time), '') IS NOT NULL AND NULLIF(trim(user_id), '') IS NOT NULL
              AND NULLIF(trim(event_type), '') IS NOT NULL""")

    def _build_olist(self):
        c = self.db.execute
        c(f"CREATE TABLE o_customers AS SELECT customer_id, customer_unique_id FROM {self._csv('olist_marketplace/olist_customers_dataset.csv')}")
        c(f"CREATE TABLE o_orders AS SELECT * FROM {self._csv('olist_marketplace/olist_orders_dataset.csv')}")
        c(f"CREATE TABLE o_items AS SELECT * FROM {self._csv('olist_marketplace/olist_order_items_dataset.csv')}")
        c(f"CREATE TABLE o_pay AS SELECT * FROM {self._csv('olist_marketplace/olist_order_payments_dataset.csv')}")
        c(f"CREATE TABLE o_rev AS SELECT * FROM {self._csv('olist_marketplace/olist_order_reviews_dataset.csv')}")
        c(f"CREATE TABLE o_prod AS SELECT * FROM {self._csv('olist_marketplace/olist_products_dataset.csv')}")
        c(f"CREATE TABLE o_tr AS SELECT * FROM {self._csv('olist_marketplace/product_category_name_translation.csv')}")
        cols = [r[0] for r in c("DESCRIBE o_tr").fetchall()]
        pt, pe = [x.lstrip("﻿") for x in cols]
        # Identity checks: the glossary assumes one row per key. If the data violated it, fail loudly.
        for table, key in (("o_orders", "order_id"), ("o_customers", "customer_id")):
            n, d = c(f"SELECT count(*), count(DISTINCT {key}) FROM {table}").fetchone()
            if n != d:
                raise OracleError(f"{table}.{key} is not unique ({n} rows, {d} distinct)")
        c(f"""
            CREATE TABLE o_ord AS
            SELECT o.order_id, cu.customer_unique_id AS usr, o.order_status AS status,
                   CAST(substr(o.order_purchase_timestamp, 1, 10) AS DATE) AS purchased,
                   CAST(substr(NULLIF(o.order_approved_at, ''), 1, 10) AS DATE) AS approved,
                   CAST(substr(NULLIF(o.order_delivered_carrier_date, ''), 1, 10) AS DATE) AS shipped,
                   CAST(substr(NULLIF(o.order_delivered_customer_date, ''), 1, 10) AS DATE) AS delivered
            FROM o_orders o JOIN o_customers cu USING (customer_id)
            WHERE NULLIF(o.order_purchase_timestamp, '') IS NOT NULL""")
        c(f"""
            CREATE TABLE oli AS
            SELECT 'olist_marketplace' AS source, purchased AS day, 'order_purchased' AS event, usr,
                   CAST(NULL AS VARCHAR) AS session, category,
                   CASE WHEN price > 0 THEN price END AS revenue
            FROM (
              SELECT o.purchased, o.usr, CAST(i.price AS DECIMAL(18,2)) AS price,
                     COALESCE(NULLIF(t.{pe}, ''), NULLIF(p.product_category_name, '')) AS category
              FROM (SELECT DISTINCT * FROM o_items) i
              JOIN o_ord o USING (order_id)
              LEFT JOIN o_prod p ON p.product_id = i.product_id
              LEFT JOIN o_tr t ON t.{pt} = p.product_category_name)
            UNION ALL SELECT 'olist_marketplace', approved, 'order_approved', usr, NULL, NULL, NULL
              FROM o_ord WHERE approved IS NOT NULL
            UNION ALL SELECT 'olist_marketplace', shipped, 'order_shipped', usr, NULL, NULL, NULL
              FROM o_ord WHERE shipped IS NOT NULL
            UNION ALL SELECT 'olist_marketplace', delivered, 'order_delivered', usr, NULL, NULL, NULL
              FROM o_ord WHERE delivered IS NOT NULL
            UNION ALL SELECT 'olist_marketplace', purchased, 'order_canceled', usr, NULL, NULL, NULL
              FROM o_ord WHERE status = 'canceled'
            UNION ALL SELECT 'olist_marketplace', o.purchased, 'payment_made', o.usr, NULL, NULL,
                   CASE WHEN CAST(p.payment_value AS DECIMAL(18,2)) > 0 THEN CAST(p.payment_value AS DECIMAL(18,2)) END
              FROM (SELECT DISTINCT * FROM o_pay) p JOIN o_ord o USING (order_id)
            UNION ALL SELECT 'olist_marketplace', CAST(substr(r.review_creation_date, 1, 10) AS DATE),
                   'review_submitted', o.usr, NULL, NULL, NULL
              FROM (SELECT DISTINCT review_id, order_id, review_creation_date FROM o_rev
                    WHERE NULLIF(review_id, '') IS NOT NULL AND NULLIF(review_creation_date, '') IS NOT NULL) r
              JOIN o_ord o USING (order_id)""")

    # ----------------------------------------------------------------- queries
    @staticmethod
    def _table(source: str) -> str:
        if source == "cosmetics_shop":
            return "cos"
        if source == "olist_marketplace":
            return "oli"
        raise OracleError(f"unknown source: {source}")

    def _scope_sql(self, where) -> str:
        parts = []
        for condition in where or []:
            (field, value), = condition.items()
            if field not in FIELDS:
                raise OracleError(f"oracle has no real-data field: {field}")
            col = FIELDS[field]
            if isinstance(value, dict) and "between" in value:
                lo, hi = value["between"]
                parts.append(f"{col} BETWEEN CAST({_q(lo)} AS DATE) AND CAST({_q(hi)} AS DATE)")
            elif isinstance(value, dict) and value.get("is_null"):
                parts.append(f"{col} IS NULL")
            elif field == "event_date":
                parts.append(f"{col} = CAST({_q(str(value))} AS DATE)")
            else:
                parts.append(f"{col} = {_q(str(value))}")
        return " AND ".join(parts) or "TRUE"

    def evaluate(self, source: str, metric: str, where=(), group: str | None = None,
                 limit: int | None = None, order_by: str | None = None) -> dict[str, Any]:
        if metric not in SOURCE_METRICS.get(source, ()):
            raise OracleError(f"{metric} is not defined for {source}")
        buy = _q(PURCHASE[source])
        restricted = {"viewers": _q("view"), "purchases": buy, "buyers": buy, "revenue": buy}
        aggregate = {
            "events": "count(*)",
            "users": "count(DISTINCT usr)",
            "sessions": "count(DISTINCT session)",
            "viewers": "count(DISTINCT usr)",
            "purchases": "count(*)",
            "buyers": "count(DISTINCT usr)",
            "revenue": "COALESCE(sum(revenue), 0)",
            "buyer_conversion_rate": f"count(DISTINCT CASE WHEN event = {buy} THEN usr END) * 1.0 / NULLIF(count(DISTINCT usr), 0)",
        }[metric]
        domain = f"AND event = {restricted[metric]}" if metric in restricted else ""
        base = f"FROM {self._table(source)} WHERE {self._scope_sql(where)} {domain}"
        if not group:
            (value,), = self.db.execute(f"SELECT {aggregate} {base}").fetchall()
            return {"columns": [metric], "rows": [[self._plain(value)]]}
        if group not in FIELDS:
            raise OracleError(f"oracle has no real-data field: {group}")
        col = FIELDS[group]
        order = f"{metric} DESC NULLS LAST, g ASC NULLS LAST" if order_by == "metric_desc" else "g ASC NULLS LAST"
        tail = f" LIMIT {int(limit)}" if limit is not None else ""
        rows = self.db.execute(f"SELECT {col} AS g, {aggregate} AS {metric} {base} GROUP BY 1 ORDER BY {order}{tail}").fetchall()
        return {"columns": [group, metric], "rows": [[self._plain(a), self._plain(b)] for a, b in rows]}

    @staticmethod
    def _plain(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, date):
            return value.isoformat()
        return value

    # -------------------------------------------------------------- inspection
    def values(self, source: str, field: str, where=()) -> list[Any]:
        col = FIELDS[field]
        rows = self.db.execute(
            f"SELECT {col}, count(*) n FROM {self._table(source)} WHERE {self._scope_sql(where)} GROUP BY 1 ORDER BY n DESC, 1").fetchall()
        return [self._plain(r[0]) for r in rows]

    def date_range(self, source: str) -> tuple[str, str]:
        lo, hi = self.db.execute(f"SELECT min(day), max(day) FROM {self._table(source)}").fetchone()
        return lo.isoformat(), hi.isoformat()

    def daily_counts(self, source: str) -> dict[str, int]:
        return {d.isoformat(): n for d, n in self.db.execute(
            f"SELECT day, count(*) FROM {self._table(source)} GROUP BY 1 ORDER BY 1").fetchall()}

    def raw_file_hashes(self) -> dict[str, str]:
        out = {}
        for path in sorted(self.landing.rglob("*.csv")):
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
            out[str(path.relative_to(self.landing))] = digest.hexdigest()
        return out
