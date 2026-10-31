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
    whole_modal_rows = 0
    malformed = 0
    nonpositive = 0
    for row in rows:
        try:
            parsed_date = datetime.strptime(row["Arrival_Date"], "%d/%m/%Y").date()
            minimum = float(row["Min_x0020_Price"])
            maximum = float(row["Max_x0020_Price"])
            modal = float(row["Modal_x0020_Price"])
            if modal <= 0 or minimum <= 0 or maximum <= 0:
                nonpositive += 1
                continue
            dates.append(parsed_date)
            whole_modal_rows += modal == round(modal)
            if 0.88 <= minimum / modal <= 0.94 and 1.06 <= maximum / modal <= 1.13:
                synthetic_band_rows += 1
        except (KeyError, TypeError, ValueError):
            malformed += 1

    if malformed:
        print(f"FAIL: {malformed} unparseable rows")
        return 1
    if nonpositive / len(rows) > 0.02:
        print(f"FAIL: {nonpositive} non-positive rows ({100 * nonpositive / len(rows):.1f}%)")
        return 1
    if nonpositive:
        print(f"note: dropping {nonpositive} non-positive rows ({100 * nonpositive / len(rows):.2f}%)")

    if not dates:
        print("FAIL: no usable positive-price rows")
        return 1
    usable_rows = len(dates)
    span = (max(dates) - min(dates)).days
    distinct_dates = len(set(dates))
    synthetic_ratio = synthetic_band_rows / usable_rows
    whole_modal_ratio = whole_modal_rows / usable_rows
    print(f"rows={len(rows)} usable_rows={usable_rows} dates={min(dates)}..{max(dates)} span_days={span}")
    print(f"distinct_dates={distinct_dates} whole_modal_ratio={whole_modal_ratio:.3f}")
    print(f"synthetic_band_ratio={synthetic_ratio:.3f}")

    if span > args.days:
        print(f"FAIL: date span exceeds --days {args.days}")
        return 1
    if distinct_dates < 130:
        print(f"FAIL: only {distinct_dates} distinct dates — need 130 for 74+56 walk-forward")
        return 1
    if whole_modal_ratio < 0.85:
        print("FAIL: modal prices are not whole-rupee values — not mandi quotes")
        return 1
    if synthetic_ratio >= 0.95:
        print("FAIL: rows match the historical synthetic price-band fingerprint")
        return 1

    print("VERDICT: REAL")
    print("evaluation-ready: yes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
