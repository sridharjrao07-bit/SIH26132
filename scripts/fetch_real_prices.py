#!/usr/bin/env python3
"""Fetch bounded data.gov.in price slices through curl.

The API is queried once per calendar date so each response stays small and
failures are isolated. The output uses the canonical CSV schema consumed by
``scripts/ingest_csv.py``.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

API_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
MARKETS = {
    "lasalgaon": "Lasalgaon APCM",
    "pimpalgaon": "Pimpalgaon Baswant APCM",
    "yeola": "Yeola APCM",
    "nashik": "Nashik APCM",
    "manmad": "Manmad APCM",
}
FIELDS = [
    "State", "District", "Market", "Commodity", "Variety", "Grade",
    "Arrival_Date", "Min_x0020_Price", "Max_x0020_Price", "Modal_x0020_Price",
]


def market_name(raw: str) -> str | None:
    value = " ".join((raw or "").lower().split())
    for needle, canonical in MARKETS.items():
        if needle in value:
            return canonical
    return None


def fetch(api_key: str, commodity: str, district: str, day: date) -> list[dict]:
    params = {
        "api-key": api_key,
        "format": "json",
        "filters[state]": "Maharashtra",
        "filters[district]": district,
        "filters[commodity]": commodity,
        "filters[arrival_date]": day.strftime("%d/%m/%Y"),
        "limit": "100",
        "offset": "0",
    }
    url = f"{API_URL}?{urlencode(params)}"
    for attempt in range(1, 4):
        result = subprocess.run(
            ["curl.exe", "-sS", "--http1.1", "-m", "90", url],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
                return payload.get("records", [])
            except json.JSONDecodeError:
                pass
        if attempt < 3:
            time.sleep(attempt * 2)
    print(f"warning: no response for {day.isoformat()}", file=sys.stderr)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch real data.gov.in prices")
    parser.add_argument("--commodity", required=True)
    parser.add_argument("--days", type=int, default=200)
    parser.add_argument("--district", default="Nashik")
    parser.add_argument("--out", type=Path, default=Path("data/gov_prices_real.csv"))
    args = parser.parse_args()

    api_key = os.environ.get("DATA_GOV_IN_API_KEY")
    if not api_key or api_key == "offline":
        print("DATA_GOV_IN_API_KEY is missing or offline", file=sys.stderr)
        return 2

    end = date.today()
    start = end - timedelta(days=args.days)
    rows: dict[tuple[str, str], dict] = {}
    queried = 0
    dates_with_data: set[date] = set()
    current = start
    while current <= end:
        queried += 1
        records = fetch(api_key, args.commodity, args.district, current)
        for item in records:
            canonical_market = market_name(item.get("market", ""))
            if not canonical_market:
                continue
            modal = item.get("modal_price")
            if modal in (None, ""):
                continue
            try:
                modal_f = float(modal)
                min_f = float(item.get("min_price") or modal_f)
                max_f = float(item.get("max_price") or modal_f)
            except (TypeError, ValueError):
                continue
            arrival = item.get("arrival_date") or current.strftime("%d/%m/%Y")
            try:
                returned_day = datetime.strptime(arrival, "%d/%m/%Y").date()
            except ValueError:
                continue
            # The resource is commonly a current snapshot and may silently
            # ignore filters[arrival_date]. Never mislabel today's row as a
            # historical observation for the date we queried.
            if returned_day != current:
                continue
            key = (canonical_market, arrival)
            rows[key] = {
                "State": "Maharashtra",
                "District": args.district,
                "Market": canonical_market,
                "Commodity": item.get("commodity") or args.commodity,
                "Variety": item.get("variety") or "General",
                "Grade": item.get("grade") or "General",
                "Arrival_Date": arrival,
                "Min_x0020_Price": f"{min_f:.2f}",
                "Max_x0020_Price": f"{max_f:.2f}",
                "Modal_x0020_Price": f"{modal_f:.2f}",
            }
            dates_with_data.add(returned_day)
        current += timedelta(days=1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows.values(), key=lambda row: (row["Arrival_Date"], row["Market"])))
    print(f"dates queried: {queried}, dates with data: {len(dates_with_data)}, rows: {len(rows)}")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
