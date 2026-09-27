"""Rehearse the whole demo in one command.

    python scripts/rehearse_demo.py            # everything
    python scripts/rehearse_demo.py --fast     # skip the test suite

Runs, in order, the four things that must all be green before a demo:

  1. numbers   scripts/audit_numbers.py       — the headline figures reconcile
                                                 independently, and the price
                                                 anchors are plausible
  2. demo      demo/direct_channel_demo.py    — the five acts run end to end and
                                                 print the real numbers
  3. sql       scripts/check_migrations.py    — the migrations are statically
                                                 sound, so 038-041 will apply
  4. tests     pytest tests/                  — nothing regressed
  5. lint      ruff check .                   — the tree is clean

Each step reports pass or fail with the first lines of its output, so a failure
shows the reason rather than just a non-zero exit. Exits non-zero if any step
failed.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# Everything the suite needs to run without a database or scheduler.
ENV = {
    "RUN_SCHEDULER": "0",
    "RATE_LIMIT_ENABLED": "0",
    "PYTHONPATH": ".",
}


def _run(cmd: list[str]) -> tuple[int, str]:
    import os

    env = {**os.environ, **ENV}
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(ROOT), env=env
    )
    return proc.returncode, proc.stdout + proc.stderr


def _progress(out: str) -> str:
    dots = "".join(re.findall(r"[.sFxXE]{10,}", out))
    return (
        f"{dots.count('.')} passed, {dots.count('F')} failed, "
        f"{dots.count('s')} skipped, {dots.count('E')} errors"
    )


def step_numbers() -> tuple[bool, str]:
    code, out = _run([PY, "scripts/audit_numbers.py"])
    detail = ""
    for line in out.splitlines():
        if "reconcile independently" in line:
            detail = line.strip()
            break
    if code != 0:
        detail = next(
            (l.strip() for l in out.splitlines() if "FAILED" in l or "PROBLEM" in l),
            detail,
        )
    return code == 0, detail or out.strip().splitlines()[-1:][0]


def step_demo() -> tuple[bool, str]:
    code, out = _run([PY, "demo/direct_channel_demo.py"])
    if code != 0:
        return False, next(
            (l for l in reversed(out.splitlines()) if l.strip()), "no output"
        )
    clean = re.sub(r"\x1b\[[0-9;]*m", "", out)
    # Act 5's reconciliation lines are the strongest single-line evidence the
    # whole chain is self-consistent, so quote them rather than the last act.
    wanted = [
        "farmer gain + consumer saving == total surplus",
        "4/4 correctness checks",
        "no oversell",
        "verdict",
    ]
    hits = [l.strip() for l in clean.splitlines()
            if any(w in l for w in wanted)]
    return True, " | ".join(hits[:2]) if hits else "ran to completion"


def step_sql() -> tuple[bool, str]:
    code, out = _run([PY, "scripts/check_migrations.py"])
    tail = [l.strip() for l in out.splitlines() if l.strip()]
    detail = tail[-1] if tail else "no output"
    return code == 0, detail


def step_tests() -> tuple[bool, str]:
    code, out = _run(
        [
            PY, "-m", "pytest", "tests/", "-p", "no:randomly", "-p", "no:warnings",
            "--no-header", "--tb=line", "-q",
        ]
    )
    return code == 0, _progress(out)


def step_lint() -> tuple[bool, str]:
    code, out = _run([PY, "-m", "ruff", "check", "."])
    tail = [l.strip() for l in out.splitlines() if l.strip()]
    return code == 0, tail[-1] if tail else "clean"


STEPS = [
    ("numbers", step_numbers, True),
    ("demo", step_demo, True),
    ("sql", step_sql, True),
    ("tests", step_tests, False),  # skipped with --fast
    ("lint", step_lint, True),
]


def main() -> int:
    fast = "--fast" in sys.argv
    print("=" * 72)
    print("  DIRECTLINK — demo rehearsal")
    print("=" * 72)

    failures = []
    for name, fn, run_when_fast in STEPS:
        if fast and not run_when_fast:
            print(f"  {name:<10} SKIP  (--fast)")
            continue
        started = time.time()
        ok, detail = fn()
        elapsed = time.time() - started
        status = "PASS" if ok else "FAIL"
        print(f"  {name:<10} {status}  {elapsed:5.1f}s  {detail}")
        if not ok:
            failures.append(name)

    print("=" * 72)
    if failures:
        print(f"  NOT READY — failed: {', '.join(failures)}")
        return 1
    print("  READY — every step green")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
