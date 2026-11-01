#!/usr/bin/env python3
"""Collect and ingest the current government price snapshot once per day."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "gov_prices_daily.csv"


def main() -> int:
    fetch = [
        sys.executable, str(ROOT / "scripts" / "fetch_real_prices.py"),
        "--commodity", "Onion", "--days", "0", "--district", "Nashik",
        "--out", str(SNAPSHOT),
    ]
    ingest = [
        sys.executable, str(ROOT / "scripts" / "ingest_csv.py"),
        "--csv", str(SNAPSHOT), "--source", "data_gov_in",
    ]
    try:
        subprocess.run(fetch, cwd=ROOT, check=True)
        subprocess.run(ingest, cwd=ROOT, check=True)
    finally:
        SNAPSHOT.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
