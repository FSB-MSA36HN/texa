"""Load only the pilot source into the isolated texa_benchmark database.

Example: uv run python eval/setup_benchmark.py --dsn 'postgresql://.../texa_benchmark'
The target must already have the TEXA schema initialized (for example from the
project's PostgreSQL bootstrap). This script replaces only event_benchmark rows.
"""
import argparse
from pathlib import Path

import psycopg

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "benchmark" / "fixture.sql"


def setup(dsn: str, initialize: bool = False) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        dbname = conn.execute("SELECT current_database()").fetchone()[0]
        if dbname != "texa_benchmark":
            raise SystemExit("Refusing to modify any database other than texa_benchmark.")
        with conn.transaction():
            if initialize:
                root = FIXTURE.parents[2]
                for path in (root / "pipeline/sql/init/01_init.sql", root / "pipeline/sql/fx/00_schema.sql",
                             root / "backend/texa/schema.sql"):
                    conn.execute(path.read_text(encoding="utf-8"))
            conn.execute(FIXTURE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", required=True)
    parser.add_argument("--initialize", action="store_true", help="Initialize project schemas in the dedicated benchmark database first")
    args = parser.parse_args()
    setup(args.dsn, args.initialize)
