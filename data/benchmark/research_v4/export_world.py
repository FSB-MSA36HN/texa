"""Export the ETL-loaded warehouse (both real sources) as worlds/real.sql for the isolated benchmark database.

The world is a deterministic text dump (rows ordered by event_id) of analytics.event_activity plus the metadata the
product reads (source_registry, vocabulary). It is large and fully derived from data/landing + pipeline/, so it is
git-ignored; its SHA-256 is recorded in worlds/real.sha256 and checked by validate_research_v4.py --load-world runs.

Usage:
  python export_world.py --dsn postgresql://.../texa      # a database where the ETL has run for both sources
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent
SOURCES = ("cosmetics_shop", "olist_marketplace")
# Added only by the optional FX step; neither the product catalog nor the benchmark schema uses it.
SKIP_COLUMNS = {"revenue_usd"}
TABLES = (
    ("analytics.event_activity", "source_id", "event_id, event_ts"),
    ("analytics.source_registry", "source_id", "source_id"),
    ("analytics.vocabulary", "source_id", "source_id, kind, field, value"),
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--output", type=Path, default=ROOT / "worlds" / "real.sql")
    args = ap.parse_args()
    args.output.parent.mkdir(exist_ok=True)
    quoted = ",".join(f"'{s}'" for s in SOURCES)
    with psycopg.connect(args.dsn) as conn, args.output.open("w", encoding="utf-8", newline="\n") as out:
        out.write("-- Real-data world: ETL output of data/landing. Apply only in isolated texa_benchmark.\n")
        for table, key, _ in reversed(TABLES):
            out.write(f"DELETE FROM {table} WHERE {key} IN ({quoted});\n")
        for table, key, order in TABLES:
            schema, name = table.split(".")
            columns = [r[0] for r in conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
                (schema, name)) if r[0] not in SKIP_COLUMNS]
            count = conn.execute(f"SELECT count(*) FROM {table} WHERE {key} IN ({quoted})").fetchone()[0]
            if not count:
                raise SystemExit(f"{table} has no rows for {SOURCES}; run the ETL first")
            out.write(f"COPY {table} ({', '.join(columns)}) FROM stdin;\n")
            with conn.cursor() as cur, cur.copy(
                    f"COPY (SELECT {', '.join(columns)} FROM {table} WHERE {key} IN ({quoted}) ORDER BY {order}) TO STDOUT") as copy:
                for chunk in copy:
                    out.write(bytes(chunk).decode("utf-8"))
            out.write("\\.\n")
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    (args.output.parent / "real.sha256").write_text(f"{digest}  real.sql\n")
    print(f"wrote {args.output} ({args.output.stat().st_size // 1_000_000} MB) sha256={digest}")


if __name__ == "__main__":
    main()
