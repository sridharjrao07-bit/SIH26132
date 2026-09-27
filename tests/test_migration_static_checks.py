"""Run the static migration checks as part of the test suite.

These checks exist because migrations 038-041 have never been applied to a real
PostgreSQL instance, which makes them the largest unverified claim in the
project. They catch the classes of error that would otherwise only surface at
apply time:

* a foreign key pointing at a table created later, or never;
* an RPC the router calls that no migration defines;
* an RPC whose parameter names do not match what the router sends (PostgREST
  matches by name, so a typo is a runtime failure, not a SQL error);
* an ``ON CONFLICT`` target with no matching unique constraint, which turns an
  idempotent migration into one that duplicates rows on every re-run;
* ``EXPECTED_MIGRATIONS`` drifting out of step with the files on disk.

Keeping this in pytest means the checks cannot silently rot the way an untracked
script does.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_migrations.py"


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/check_migrations.py not present")
def test_static_migration_checks_report_no_errors():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(SCRIPT.parent.parent),
    )
    assert result.returncode == 0, (
        "static migration checks failed:\n" + result.stdout + result.stderr
    )
