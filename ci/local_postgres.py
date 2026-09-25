#!/usr/bin/env python3
"""Throwaway PostgreSQL cluster for running the ``-m db`` integration tests locally.

The CI ``test-db`` job uses a ``postgres:16`` service container.  Docker is not
available everywhere (locked-down sandboxes, bare runners, dev machines without
it), so this helper does the same job with the prebuilt PostgreSQL binaries that
ship with the ``embedded-postgres`` PyPI package:

    pip install embedded-postgres
    python ci/local_postgres.py up          # initdb + start, prints the URL
    export SUPABASE_DB_URL=$(python ci/local_postgres.py uri)
    psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f db/ci_bootstrap.sql
    python scripts/apply_migrations.py
    pytest -m db -q --strict-markers -rs

    python ci/local_postgres.py down        # stop, keep the data dir
    python ci/local_postgres.py reset       # stop and delete the data dir

Everything lives under ``.local-pg/`` (git-ignored) and can be deleted freely.

The cluster listens on a TCP port (default 5433, override with ``LOCAL_PG_PORT``)
and hands out a CI-shaped URL, ``postgresql://postgres:postgres@127.0.0.1:5433/krishi_test``.
That shape matters: ``tests/test_db_marketplace_fixes.py`` derives the admin DSN
with ``url.rsplit("/", 1)[0]``, which corrupts a URL whose host is a filesystem
socket path.  This cluster is local-only and trusts connections, so it is for
throwaway test data — never point real credentials at it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PGDATA = ROOT / ".local-pg" / "pgdata"
RUNDIR = ROOT / ".local-pg" / "run"
LOGFILE = ROOT / ".local-pg" / "postgres.log"

HOST = os.environ.get("LOCAL_PG_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCAL_PG_PORT", "5433"))
SUPERUSER = "postgres"
PASSWORD = "postgres"  # local-only throwaway cluster; matches db/ci_bootstrap.sql
DB_NAME = os.environ.get("LOCAL_PG_DB", "krishi_test")


def _pg_bin() -> Path:
    try:
        from embedded_postgres.postgres_server import POSTGRES_BIN_PATH
    except ImportError:
        sys.exit("embedded-postgres is not installed — run: pip install embedded-postgres")
    if not (POSTGRES_BIN_PATH / "initdb").exists():
        sys.exit(f"no PostgreSQL binaries under {POSTGRES_BIN_PATH}")
    return POSTGRES_BIN_PATH


def _url(database: str = DB_NAME) -> str:
    return f"postgresql://{SUPERUSER}:{PASSWORD}@{HOST}:{PORT}/{database}"


def _psql_admin_sql(sql: str) -> None:
    """Run SQL against the 'postgres' maintenance database via psql."""
    import psycopg2

    conn = psycopg2.connect(_url("postgres"))
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.close()


def _running() -> bool:
    pidfile = PGDATA / "postmaster.pid"
    return pidfile.exists()


def _wait_ready(timeout: int = 60) -> None:
    import psycopg2

    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            psycopg2.connect(_url("postgres"), connect_timeout=3).close()
            return
        except Exception as exc:  # noqa: BLE001 - retry until the deadline
            last = exc
            time.sleep(0.5)
    tail = LOGFILE.read_text(errors="replace")[-1500:] if LOGFILE.exists() else "(no log)"
    sys.exit(f"postgres did not become ready: {last}\n--- {LOGFILE} ---\n{tail}")


def cmd_up() -> int:
    if _running():
        print(f"already running — {_url()}")
        return 0

    bindir = _pg_bin()
    RUNDIR.mkdir(parents=True, exist_ok=True)

    if not (PGDATA / "PG_VERSION").exists():
        PGDATA.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(bindir / "initdb"), "-D", str(PGDATA), "-U", SUPERUSER,
             "--auth=trust", "--encoding=UTF8"],
            check=True, capture_output=True, text=True,
        )
        with (PGDATA / "postgresql.conf").open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n# appended by ci/local_postgres.py\n"
                f"listen_addresses = '{HOST}'\n"
                f"port = {PORT}\n"
                f"unix_socket_directories = '{RUNDIR}'\n"
            )

    subprocess.run(
        [str(bindir / "pg_ctl"), "-D", str(PGDATA), "-l", str(LOGFILE),
         "-w", "-t", "60", "start"],
        check=True, capture_output=True, text=True,
    )
    _wait_ready()

    _psql_admin_sql(f"ALTER ROLE {SUPERUSER} WITH PASSWORD '{PASSWORD}'")
    import psycopg2

    try:
        psycopg2.connect(_url()).close()
    except psycopg2.OperationalError:
        _psql_admin_sql(f'CREATE DATABASE "{DB_NAME}"')

    print(_url())
    return 0


def cmd_uri() -> int:
    if not _running():
        sys.exit("cluster is not running — run: python ci/local_postgres.py up")
    print(_url())
    return 0


def cmd_status() -> int:
    print("running" if _running() else "stopped")
    return 0


def _stop() -> None:
    if not _running():
        return
    bindir = _pg_bin()
    subprocess.run(
        [str(bindir / "pg_ctl"), "-D", str(PGDATA), "-m", "fast", "-w", "stop"],
        check=False, capture_output=True, text=True,
    )


def cmd_down() -> int:
    _stop()
    print(f"stopped (data kept in {PGDATA})")
    return 0


def cmd_reset() -> int:
    _stop()
    shutil.rmtree(ROOT / ".local-pg", ignore_errors=True)
    print("stopped and removed .local-pg/")
    return 0


COMMANDS = {"up": cmd_up, "uri": cmd_uri, "status": cmd_status, "down": cmd_down, "reset": cmd_reset}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "up"
    if cmd not in COMMANDS:
        print(f"unknown command {cmd!r}; expected one of {', '.join(COMMANDS)}", file=sys.stderr)
        return 2
    return COMMANDS[cmd]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
