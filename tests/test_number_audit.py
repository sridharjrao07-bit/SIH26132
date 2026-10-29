"""Independently re-derive the headline numbers and require them to reconcile.

The test suite proves the engine is *self-consistent*: invariants hold, splits
conserve value, the allocation is optimal. It does not prove the engine is
*correct* — a chain whose stage parameters are wrong would satisfy every
invariant while describing a market that does not exist.

``scripts/audit_numbers.py`` recomputes each headline figure by a different
route, straight from the committed data. Running it here means a regression in
either the anchors or the derivation fails CI rather than surfacing in front of
a judge.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "audit_numbers.py"
DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/audit_numbers.py not present")
def test_headline_numbers_reconcile_independently():
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(SCRIPT.parent.parent),
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/audit_numbers.py not present")
def test_the_audit_is_not_vacuous():
    """The audit must fail when an anchor is implausible.

    Note what this does and does not prove. The engine calibrates to whatever
    (farm, retail) pair it is given, so corrupting the anchor to another
    *plausible* number does NOT break the audit -- every derived figure simply
    re-reconciles against the new pair. That is a real limitation, stated in the
    audit's own docstring. What the audit does catch is an anchor that is
    impossible on its face, which is the failure mode that would actually
    embarrass a demo.
    """
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "data"
        shutil.copytree(DATA, data)
        target = data / "gov_retail_prices.csv"
        text = target.read_text(encoding="utf-8")
        assert "5392" in text, "expected the real retail anchor in the snapshot"
        # below the plausible band for a quintal of onion
        target.write_text(text.replace("5392", "12"))

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--data-dir", str(data)],
            capture_output=True,
            text=True,
            cwd=str(SCRIPT.parent.parent),
        )
        assert result.returncode != 0, (
            "the audit passed against a corrupted retail price, so it is not "
            "actually checking anything:\n" + result.stdout
        )
