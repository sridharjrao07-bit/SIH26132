#!/usr/bin/env python3
"""Verify the live stack end to end. The credential-gated half of the handoff.

    export SUPABASE_DB_URL="postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres"
    export DATA_GOV_IN_API_KEY="<key>"
    export DCA_RETAIL_RESOURCE_ID="<uuid>"
    python scripts/verify_live_stack.py

Everything here needs credentials the offline suite cannot supply. It exits
non-zero if any step fails, so it can gate a deploy or a pre-demo run, and it
prints one PASS/FAIL line per step with the numbers so a failure is diagnosable
without re-running.

Ten steps, in dependency order:

  1. preflight     HEAD matches the remote tip; the venv exists
  2. sql lint      scripts/check_migrations.py
  3. dry run       apply_migrations --dry-run  (safe on a read-only DB)
  4. apply         apply_migrations
  5. idempotency   apply_migrations again must be a no-op, not an error
  6. seed rows     the two assertions the runbook asks for
  7. write path    scripts/exercise_rpc.py, including the contention check
  8. live retail   origin == 'live'
  9. snapshot fb   with the key removed, origin == 'snapshot' and it must not raise
 10. rehearsal     scripts/rehearse_demo.py --fast

Step 5 is the one most likely to be skipped and most likely to bite: a seed that
is not idempotent passes step 4 once and then fails every deploy after it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

FAILURES: list[str] = []
CHECKS = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    # Driver error messages embed tabs and newlines; flatten them or the
    # one-line-per-check format breaks and the report is unreadable.
    detail = " ".join(str(detail).split())
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not ok:
        FAILURES.append(f"{name}: {detail}")
    return ok


def run(cmd: list[str], env_extra: dict | None = None) -> tuple[int, str]:
    env = {**os.environ, **(env_extra or {})}
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=env)
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    print("=" * 74)
    print("  DIRECTLINK — live stack verification")
    print("=" * 74)

    # ── 1. preflight ────────────────────────────────────────────────────────
    print("\n  preflight\n")
    proc = subprocess.run(
        ["git", "ls-remote", "origin", "refs/heads/arena/01a0e3c9-sih26132"],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    remote = proc.stdout.split("\t")[0].strip() if proc.stdout else ""
    local = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(ROOT)
    ).stdout.strip()
    check("HEAD matches the pushed remote tip", bool(remote) and remote == local,
          f"local={local[:8]} remote={remote[:8]}")
    check("virtualenv present", (ROOT / ".venv" / "bin" / "python").exists())
    check("SUPABASE_DB_URL is set", bool(os.environ.get("SUPABASE_DB_URL")))
    check("DATA_GOV_IN_API_KEY is set", bool(os.environ.get("DATA_GOV_IN_API_KEY")))
    check("DCA_RETAIL_RESOURCE_ID is set", bool(os.environ.get("DCA_RETAIL_RESOURCE_ID")))

    if not os.environ.get("SUPABASE_DB_URL"):
        print("\n  Cannot continue without SUPABASE_DB_URL. Export it and re-run.")
        return 1

    # ── 2. static SQL lint ──────────────────────────────────────────────────
    print("\n  static SQL\n")
    code, out = run([PY, "scripts/check_migrations.py"])
    tail = [l.strip() for l in out.splitlines() if l.strip()]
    check("migrations are statically sound", code == 0, tail[-1] if tail else "no output")

    # ── 3-5. dry run, apply, idempotency ────────────────────────────────────
    print("\n  migrations\n")
    code, out = run([PY, "scripts/apply_migrations.py", "--dry-run"])
    check("--dry-run succeeds", code == 0,
          (out.strip().splitlines() or ["no output"])[-1])

    code, out = run([PY, "scripts/apply_migrations.py"])
    check("migrations apply", code == 0,
          (out.strip().splitlines() or ["no output"])[-1])

    code, out = run([PY, "scripts/apply_migrations.py"])
    noop = "Nothing to apply." in out or code == 0
    check("re-running is a no-op, not an error", noop,
          (out.strip().splitlines() or ["no output"])[-1])

    # ── 6. the two seed assertions ──────────────────────────────────────────
    print("\n  seeded rows\n")
    try:
        sys.path.insert(0, str(ROOT))
        from scripts.apply_migrations import _connect

        conn = _connect(os.environ["SUPABASE_DB_URL"])
        cur = conn.cursor()

        cur.execute(
            "SELECT category, jsonb_array_length(stages), is_active "
            "FROM public.value_chain_profiles ORDER BY category"
        )
        rows = cur.fetchall()
        check(
            "value_chain_profiles has 3 rows with 5 stages each, all active",
            len(rows) == 3
            and all(int(r[1]) == 5 and r[2] for r in rows),
            "; ".join(f"{r[0]}={r[1]}stages" for r in rows) or "no rows",
        )

        cur.execute("SELECT count(*) FROM public.retail_prices")
        n = int(cur.fetchone()[0])
        check("retail_prices is populated", n > 0, f"{n} rows")

        # the anchor the engine actually reads
        cur.execute(
            "SELECT c.name_en, r.retail_price, r.price_date "
            "FROM public.retail_prices r JOIN public.commodities c ON c.id = r.commodity_id "
            "ORDER BY r.price_date DESC LIMIT 1"
        )
        anchor = cur.fetchone()
        check("a retail anchor row is readable", anchor is not None, str(anchor))

        cur.close()
        conn.close()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        check("database assertions ran", False, f"{type(exc).__name__}: {exc}")

    # ── 7. the write path, including contention ─────────────────────────────
    print("\n  write path\n")
    code, out = run([PY, "scripts/exercise_rpc.py"])
    check("exercise_rpc passes every check", code == 0,
          (out.strip().splitlines() or ["no output"])[-1])

    # ── 8-9. the live retail adapter, then the fallback ─────────────────────
    print("\n  retail adapter\n")
    probe = (
        "from ingestion.retail_loader import latest_retail_price;"
        "print(latest_retail_price('Onion','Maharashtra'))"
    )
    code, out = run([PY, "-c", probe])
    live = "'live'" in out or '"live"' in out
    check("live fetch reports origin == 'live'", live, out.strip().splitlines()[-1:] and
          out.strip().splitlines()[-1] or "no output")

    code, out = run(
        [PY, "-c", probe],
        {"DATA_GOV_IN_API_KEY": "", "DCA_RETAIL_RESOURCE_ID": ""},
    )
    snap = "'snapshot'" in out or '"snapshot"' in out
    check("with the key removed it falls back to the snapshot", snap and code == 0,
          out.strip().splitlines()[-1:] and out.strip().splitlines()[-1] or "no output")

    # ── 10. rehearsal ───────────────────────────────────────────────────────
    print("\n  rehearsal\n")
    code, out = run([PY, "scripts/rehearse_demo.py", "--fast"])
    check("offline rehearsal still green", code == 0,
          (out.strip().splitlines() or ["no output"])[-1])

    print()
    print("=" * 74)
    if FAILURES:
        print(f"  FAILED — {len(FAILURES)} of {CHECKS} checks")
        for f in FAILURES:
            print(f"    {f}")
        return 1
    print(f"  OK — all {CHECKS} checks passed")
    print("  The database layer is now verified by execution, not by a double.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
