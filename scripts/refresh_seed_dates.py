#!/usr/bin/env python3
"""Re-date the seed price CSV so the newest arrival is TODAY.

Why this exists
---------------
``seed.py`` -> ``scripts/ingest_csv.py`` loads ``data/gov_prices.csv`` as-is.
The committed snapshot is a fixed date, but the flagship sale-window
(``notifications/sale_window.py``) only serves prices within the last 15 days
and returns **404** otherwise. A demo run days or weeks after the snapshot date
would silently show "no price" for Sell/Hold/Wait — the single most important
screen. This script shifts every ``Arrival_Date`` so the latest row lands on
today (IST), preserving the full history shape, so the demo works on any date.

Usage
-----
    python scripts/refresh_seed_dates.py --dry-run        # preview the shift
    python scripts/refresh_seed_dates.py --in-place       # overwrite the CSV seed.py reads
    git checkout -- data/gov_prices.csv                   # restore the original snapshot

Everything except ``Arrival_Date`` is preserved byte-for-byte (same columns,
same quoting). Dates are parsed/written as DD/MM/YYYY, matching ingest_csv.py.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DATE_COL = "Arrival_Date"
DATE_FMT = "%d/%m/%Y"
DEFAULT_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gov_prices.csv")


def ist_today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=DEFAULT_CSV, help="path to gov_prices.csv")
    ap.add_argument("--end", default=None, help="target latest date YYYY-MM-DD (default: today IST)")
    ap.add_argument("--out", default=None, help="write here instead of the input (default: <csv>.recent)")
    ap.add_argument("--in-place", action="store_true", help="overwrite --csv in place (what seed.py reads)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args()

    target_end = datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else ist_today()

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        print("empty CSV", file=sys.stderr)
        return 1
    header = rows[0]
    if DATE_COL not in header:
        print(f"no {DATE_COL!r} column in header: {header}", file=sys.stderr)
        return 1
    di = header.index(DATE_COL)

    dates = []
    for r in rows[1:]:
        if len(r) <= di or not r[di].strip():
            continue
        try:
            dates.append(datetime.strptime(r[di].strip(), DATE_FMT).date())
        except ValueError:
            print(f"unparseable date {r[di]!r}", file=sys.stderr)
            return 1
    if not dates:
        print("no dated rows found", file=sys.stderr)
        return 1

    cur_max, cur_min = max(dates), min(dates)
    shift = (target_end - cur_max).days
    print(f"rows={len(dates)}  current range {cur_min:%Y-%m-%d} .. {cur_max:%Y-%m-%d}")
    print(f"shift by {shift:+d} days -> latest becomes {target_end:%Y-%m-%d}")
    if shift < 0:
        print(f"note: shifting backwards; earliest becomes {cur_min + timedelta(days=shift):%Y-%m-%d}")

    if args.dry_run:
        return 0

    for r in rows[1:]:
        if len(r) > di and r[di].strip():
            d = datetime.strptime(r[di].strip(), DATE_FMT).date() + timedelta(days=shift)
            r[di] = d.strftime(DATE_FMT)

    if args.in_place:
        out_path = args.csv
    else:
        out_path = args.out or (args.csv + ".recent")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)
    print(f"wrote {out_path}")
    if not args.in_place:
        print(f"seed.py reads {args.csv}; run with --in-place to update it, or:")
        print(f"  cp {out_path} {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
