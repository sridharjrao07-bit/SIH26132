#!/usr/bin/env python3
"""Apply numbered SQL migrations to a Postgres database in order.

Usage
-----
    python scripts/apply_migrations.py [--dry-run] [--from N]

Environment
-----------
    SUPABASE_DB_URL — postgres://... connection string (required)

Strategy
--------
Migrations in ``db/migrations/`` are named ``NNN_description.sql`` where
``NNN`` is a zero-padded integer.  This script:

1. Creates a ``schema_migrations`` table if it does not exist.
2. Reads the table to find the highest applied migration number.
3. Applies all migrations with a number strictly greater than the highest
   applied, in ascending order, inside individual transactions.
4. Records each applied migration in ``schema_migrations``.

Each migration is applied in its own transaction so a failure on migration N
does not leave N+1..M partially applied.  The ``schema_migrations`` table
itself acts as the ledger — re-running the script is always safe.

Why not Alembic?
----------------
The project targets Supabase/PostgREST which already owns the schema lifecycle.
A lightweight numbered-file runner avoids introducing a second migration tool
that must be kept in sync with Supabase's own migration system.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("ERROR: psycopg2 is not installed.  Run: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(1)

MIGRATIONS_DIR = Path(__file__).parent.parent / "db" / "migrations"
MIGRATION_PATTERN = re.compile(r"^(\d{3})_.*\.sql$")

CREATE_LEDGER_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id          SERIAL PRIMARY KEY,
    version     INTEGER NOT NULL UNIQUE,
    filename    TEXT    NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def get_migration_files() -> list[tuple[int, Path]]:
    """Return (version, path) pairs sorted by version ascending."""
    files = []
    for f in MIGRATIONS_DIR.iterdir():
        m = MIGRATION_PATTERN.match(f.name)
        if m:
            files.append((int(m.group(1)), f))
    files.sort(key=lambda x: x[0])
    return files


def apply_migrations(db_url: str, dry_run: bool = False, from_version: int = 0) -> None:
    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_LEDGER_SQL)
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
            (max_applied,) = cur.fetchone()
            conn.commit()

        migrations = get_migration_files()
        pending = [
            (v, p) for v, p in migrations if v > max_applied and v >= from_version
        ]

        if not pending:
            print(f"Nothing to apply (highest applied: {max_applied}).")
            return

        for version, path in pending:
            sql = path.read_text(encoding="utf-8")
            if dry_run:
                print(f"[DRY RUN] Would apply: {path.name}")
                continue

            print(f"Applying: {path.name} ... ", end="", flush=True)
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version, filename) VALUES (%s, %s)",
                    (version, path.name),
                )
            conn.commit()
            print("OK")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply SQL migrations to Postgres.")
    parser.add_argument("--dry-run", action="store_true", help="Print migrations without applying")
    parser.add_argument("--from", dest="from_version", type=int, default=0,
                        help="Start applying from this migration number (inclusive)")
    args = parser.parse_args()

    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        print("ERROR: SUPABASE_DB_URL environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    try:
        apply_migrations(db_url, dry_run=args.dry_run, from_version=args.from_version)
    except Exception as exc:
        print(f"FATAL: Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
