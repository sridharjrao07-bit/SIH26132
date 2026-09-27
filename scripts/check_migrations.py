#!/usr/bin/env python3
"""Static checks on the SQL migrations, runnable without a database.

Why this exists
---------------
Migrations 038-041 have never been applied to a real PostgreSQL instance, which
makes them the largest unverified claim in the project. Much of what can go
wrong is visible without a server:

* a foreign key pointing at a table that is created later, or never;
* an RPC the router calls that no migration defines;
* an RPC whose parameter names do not match what the router sends (PostgREST
  matches by name, so a typo is a runtime failure, not a SQL error);
* an ``ON CONFLICT`` target with no matching unique constraint, which turns an
  idempotent migration into one that duplicates rows on every re-run;
* a migration that would fail to re-run, breaking apply_migrations.py's
  "re-running is always safe" contract;
* ``EXPECTED_MIGRATIONS`` drifting out of step with the files on disk, which
  fails the coverage ratchet in tests.

This script checks those. It is deliberately conservative: it reports a problem
only when confident, because a linter that cries wolf gets ignored, and it only
warns (never errors) where a human needs to make a judgement call.

Usage
-----
    python scripts/check_migrations.py      # exit 0 = clean, 1 = problems
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"
APP = ROOT / "app" / "routers" / "direct.py"
RATCHET = ROOT / "tests" / "test_privileges.py"

MIGRATION_RE = re.compile(r"^(\d{3})([a-z]?)_(.+)\.sql$")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checks = 0

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def ok(self) -> None:
        self.checks += 1


# ─────────────────────────────────────────────────────────────────────────────
# SQL text handling
# ─────────────────────────────────────────────────────────────────────────────


def strip_comments(sql: str) -> str:
    """Remove ``--`` comments, but never inside a quoted string."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = _string_end(sql, i)
            out.append(sql[i:j])
            i = j
        elif sql.startswith("--", i):
            nl = sql.find("\n", i)
            i = n if nl == -1 else nl
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _string_end(sql: str, i: int) -> int:
    """Index just past the single-quoted string starting at ``i``."""
    n = len(sql)
    j = i + 1
    while j < n:
        if sql[j] == "'":
            if j + 1 < n and sql[j + 1] == "'":  # escaped quote
                j += 2
                continue
            return j + 1
        j += 1
    return n


def _dollar_end(sql: str, i: int) -> int:
    """Index just past the dollar-quoted block starting at ``i``."""
    m = re.match(r"\$[a-zA-Z_]*\$", sql[i:])
    if not m:
        return i + 1
    tag = m.group(0)
    end = sql.find(tag, i + len(tag))
    return len(sql) if end == -1 else end + len(tag)


def split_statements(sql: str) -> list[str]:
    """Split on top-level semicolons.

    ``sql.split(";")`` is wrong here for two reasons this project actually hits:
    dollar-quoted function bodies contain semicolons, and JSON literals passed
    to jsonb columns can too. Both would make one statement look like several,
    which is how a linter ends up warning about an "unguarded insert" that is
    perfectly guarded.
    """
    stmts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            j = _string_end(sql, i)
            buf.append(sql[i:j])
            i = j
        elif ch == "$":
            j = _dollar_end(sql, i)
            buf.append(sql[i:j])
            i = j
        elif ch == ";":
            stmts.append("".join(buf))
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    if "".join(buf).strip():
        stmts.append("".join(buf))
    return [s for s in stmts if s.strip()]


def _balanced_group(text: str, open_idx: int) -> str:
    """Contents of the parenthesised group whose ``(`` is at ``open_idx``.

    ``[^)]*`` silently truncates any expression index: 041's unique index is
    over ``coalesce(commodity_id, '000…'::uuid)``, so a naive pattern captured
    only three of its four columns and reported a false mismatch.
    """
    depth, i, n = 0, open_idx, len(text)
    while i < n:
        ch = text[i]
        if ch == "'":
            i = _string_end(text, i)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_idx + 1:i]
        i += 1
    return text[open_idx + 1:]


def in_function_body(sql: str, stmt: str) -> bool:
    """True when ``stmt`` sits inside a ``create [or replace] function`` body.

    Runtime INSERTs — the ones an RPC issues when it runs — are not seed data
    and are not expected to be idempotent. Only top-level seed inserts are.
    """
    pos = sql.find(stmt[:80])
    if pos == -1:
        return False
    before = sql[:pos].lower()
    last = max(
        before.rfind(p)
        for p in (
            "create or replace function",
            "create function",
            "create or replace procedure",
            "create procedure",
        )
    )
    if last == -1:
        return False
    # odd number of dollar-quote delimiters between the CREATE and here means
    # we are inside the body
    return len(re.findall(r"\$[a-zA-Z_]*\$", before[last:])) % 2 == 1


def _norm_cols(text: str) -> str:
    """Normalise a column list to comparable space-separated names."""
    return " ".join(text.replace(",", " ").split())


# ─────────────────────────────────────────────────────────────────────────────
# Unique-constraint collection
# ─────────────────────────────────────────────────────────────────────────────

_CONSTRAINT_KEYWORDS = {
    "unique", "primary", "constraint", "check", "foreign", "key", "exclude",
}


def collect_unique_constraints(stmt: str, out: set[str]) -> None:
    """Record every column set a UNIQUE or PRIMARY KEY makes addressable.

    Handles the five spellings this schema uses:

        id           uuid primary key          -- inline PK
        name_en      text not null unique      -- inline UNIQUE
        unique (source, source_key)            -- table-level UNIQUE
        primary key (a, b)                     -- table-level PK
        create unique index ... on t (a, b)    -- explicit index

    Sets are normalised to space-separated names so they compare against a
    normalised ``ON CONFLICT (a, b)`` target.
    """
    for m in re.finditer(r"\bunique\s*\(", stmt, re.I):
        out.add(_norm_cols(_balanced_group(stmt, m.end() - 1)))
    for m in re.finditer(r"\bprimary\s+key\s*\(", stmt, re.I):
        out.add(_norm_cols(_balanced_group(stmt, m.end() - 1)))
    for m in re.finditer(r"\bon\s+public\.\w+\s*\(", stmt, re.S | re.I):
        out.add(_norm_cols(_balanced_group(stmt, m.end() - 1)))

    # inline column constraints: "<col> <type> ... unique|primary key ..."
    for line in stmt.splitlines():
        m = re.match(r"\s*([a-z_]+)\s+([a-z]+(?:\s*\([^)]*\))?)\s+(.*)$", line)
        if not m:
            continue
        col, rest = m.group(1), m.group(3).lower().rstrip(",")
        if not rest or col in _CONSTRAINT_KEYWORDS:
            continue
        if re.search(r"\bprimary key\b", rest):
            out.add(col)
        elif re.search(r"\bunique\b", rest):
            out.add(col)


# ─────────────────────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────────────────────


def ordered_migrations() -> list[Path]:
    files = [p for p in MIGRATIONS.glob("*.sql") if MIGRATION_RE.match(p.name)]
    return sorted(
        files,
        key=lambda p: (MIGRATION_RE.match(p.name).group(1), MIGRATION_RE.match(p.name).group(2) or ""),
    )


def main() -> int:
    r = Report()
    migrations = ordered_migrations()
    if not migrations:
        r.error("no migrations found")

    texts = {p: strip_comments(p.read_text(encoding="utf-8")) for p in migrations}

    # ── 1. numbering is contiguous and collision-free ───────────────────────
    seen: dict[str, Path] = {}
    for p in migrations:
        m = MIGRATION_RE.match(p.name)
        key = m.group(1) + (m.group(2) or "")
        if key in seen:
            r.error(f"{p.name} collides with {seen[key].name} on number {key}")
        seen[key] = p
    r.ok()

    # ── 2. FK targets exist, and are not created later than their use ───────
    created: dict[str, Path] = {}
    for p in migrations:
        for name in re.findall(r"create table (?:if not exists )?public\.([a-z_]+)", texts[p]):
            created.setdefault(name, p)
    order = {p: i for i, p in enumerate(migrations)}
    for p in migrations:
        for target in re.findall(r"references public\.([a-z_]+)", texts[p]):
            origin = created.get(target)
            if origin is None:
                r.error(f"{p.name}: references public.{target}, which no migration creates")
            elif order[origin] > order[p]:
                r.error(
                    f"{p.name}: references public.{target}, created later in "
                    f"{origin.name} (forward reference)"
                )
    r.ok()

    # ── 3. every RPC the router calls exists, with matching parameters ──────
    defined: dict[str, set[str]] = {}
    for p in migrations:
        for m in re.finditer(
            r"create (?:or replace )?function public\.([a-z_]+)\s*\((.*?)\)\s*returns",
            texts[p],
            re.S,
        ):
            defined.setdefault(m.group(1), set()).update(
                re.findall(r"\b(p_[a-z_]+)\s+[a-z]", m.group(2))
            )
    router = APP.read_text(encoding="utf-8")
    called = set(re.findall(r'_call_rpc\(\s*\n?\s*supabase,\s*\n?\s*"([a-z_]+)"', router))
    called |= set(re.findall(r'\.rpc\("([a-z_]+)"', router))
    for fn in sorted(called):
        params = defined.get(fn)
        if params is None:
            r.error(f"app calls RPC '{fn}' but no migration defines it")
            continue
        call = re.search(rf'"{fn}",\s*\{{(.*?)\}}', router, re.S)
        if not call:
            r.warn(f"could not locate the argument dict for RPC '{fn}' to compare names")
            continue
        sent = set(re.findall(r'"(p_[a-z_]+)"', call.group(1)))
        if sent - params:
            r.error(
                f"app sends {sorted(sent - params)} to RPC '{fn}', which does not "
                f"declare them (declares {sorted(params)})"
            )
        if params - sent:
            r.warn(f"RPC '{fn}' declares {sorted(params - sent)} that the app never sends")
    r.ok()

    # ── 4. ON CONFLICT targets have a matching unique constraint ────────────
    # Cumulative, because migration N may target a constraint created in N-1.
    cumulative: set[str] = set()
    for p in migrations:
        for stmt in split_statements(texts[p]):
            head = stmt.lstrip().lower()
            is_ddl = head.startswith("create table") or (
                head.startswith("create") and "index" in head and "unique" in head
            )
            if is_ddl:
                collect_unique_constraints(stmt, cumulative)

            m = re.search(r"on\s+conflict\s*\(", stmt, re.I)
            if not m:
                continue
            raw = _balanced_group(stmt, m.end() - 1)
            target = _norm_cols(raw)
            # the target keeps its own parentheses when it is an expression
            # index; strip them so both sides compare on equal terms
            if target not in cumulative and target.rstrip(")") not in cumulative:
                r.error(
                    f"{p.name}: ON CONFLICT ({' '.join(raw.split())}) has no matching "
                    "unique constraint in this or any earlier migration"
                )
    r.ok()

    # ── 5. top-level seed INSERTs must be re-runnable ───────────────────────
    for p in migrations:
        for stmt in split_statements(texts[p]):
            m = re.search(r"insert\s+into\s+public\.([a-z_]+)\b(.*)", stmt, re.S | re.I)
            if not m:
                continue
            table, body = m.group(1), m.group(2)
            if "on conflict" in body.lower():
                continue
            if re.search(r"\bselect\b", body, re.I):
                continue  # insert...select is usually idempotent by predicate
            if in_function_body(texts[p], stmt):
                continue
            r.warn(
                f"{p.name}: unguarded top-level INSERT into public.{table}; confirm "
                "it is idempotent (ON CONFLICT, or a WHERE NOT EXISTS guard)"
            )
    r.ok()

    # ── 6. the coverage ratchet must match the files on disk ────────────────
    expected = None
    if RATCHET.exists():
        m = re.search(r"EXPECTED_MIGRATIONS = (\d+)", RATCHET.read_text(encoding="utf-8"))
        if m:
            expected = int(m.group(1))
    if expected is not None and expected != len(migrations):
        r.error(
            f"tests/test_privileges.py EXPECTED_MIGRATIONS = {expected} but there are "
            f"{len(migrations)} migration files; the coverage ratchet will fail"
        )
    r.ok()

    # ── report ──────────────────────────────────────────────────────────────
    print(f"migrations checked : {len(migrations)}")
    print(f"tables created     : {len(created)}")
    print(f"rpc functions      : {len(defined)}")
    print(f"checks run         : {r.checks}")
    for w in r.warnings:
        print(f"  WARN  {w}")
    for e in r.errors:
        print(f"  ERROR {e}")
    if r.errors:
        print(f"\nFAILED: {len(r.errors)} problem(s)")
        return 1
    print("\nOK: no static problems found in the migrations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
