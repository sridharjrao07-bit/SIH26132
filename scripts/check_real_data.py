#!/usr/bin/env python3
"""Fail-closed sanity gate for an Agmarknet export.

This is a provenance sanity check, not proof that a CSV came from Agmarknet.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

REQUIRED = {
    "State", "District", "Market", "Commodity", "Arrival_Date",
    "Min_x0020_Price", "Max_x0020_Price", "Modal_x0020_Price",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate an Agmarknet price CSV")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--days", type=int, default=200, help="maximum date span")
    args = parser.parse_args()

    try:
        with args.csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing = REQUIRED - set(reader.fieldnames or ())
            if missing:
                print(f"FAIL: missing columns: {', '.join(sorted(missing))}")
                return 1
            rows = list(reader)
    except OSError as exc:
        print(f"FAIL: cannot read {args.csv_path}: {exc}")
        return 1

    if not rows:
        print("FAIL: CSV contains no data rows")
        return 1

    dates = []
    synthetic_band_rows = 0
    malformed = 0
    for row in rows:
        try:
            dates.append(datetime.strptime(row["Arrival_Date"], "%d/%m/%Y").date())
            minimum = float(row["Min_x0020_Price"])
            maximum = float(row["Max_x0020_Price"])
            modal = float(row["Modal_x0020_Price"])
            if modal <= 0 or minimum <= 0 or maximum <= 0:
                raise ValueError("non-positive price")
            if 0.88 <= minimum / modal <= 0.94 and 1.06 <= maximum / modal <= 1.13:
                synthetic_band_rows += 1
        except (KeyError, TypeError, ValueError):
            malformed += 1

    if malformed:
        print(f"FAIL: {malformed} malformed price/date rows")
        return 1

    span = (max(dates) - min(dates)).days
    synthetic_ratio = synthetic_band_rows / len(rows)
    print(f"rows={len(rows)} dates={min(dates)}..{max(dates)} span_days={span}")
    print(f"synthetic_band_ratio={synthetic_ratio:.3f}")

    if span > args.days:
        print(f"FAIL: date span exceeds --days {args.days}")
        return 1
    if synthetic_ratio >= 0.95:
        print("FAIL: rows match the historical synthetic price-band fingerprint")
        return 1

    print("VERDICT: REAL")
    print("evaluation-ready: yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
