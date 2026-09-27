#!/usr/bin/env python3
"""
Generate 45+ days (default: 60 days) of realistic agricultural market data.

Why this exists:
----------------
The core forecasting models (GBM, FeatureOLS, Holt-Winters) and walk-forward
backtest engine require at least 45 to 56 distinct daily observations.
The default snapshot in `data/gov_prices.csv` contains only 1 date, and
`002_seed.sql` contains only 30 days for 1 pair.

This script generates high-fidelity, statistically sound historical prices,
arrival quantities, and spreads for all core Nashik mandis and commodities
up to today (IST).

Outputs:
  1. CSV mode: Generates a CSV formatted for `scripts/ingest_csv.py` and `seed.py`.
  2. Direct DB mode (optional): Upserts directly to Supabase if credentials exist.

Usage:
  # Generate 60 days of data and write to data/gov_prices_60days.csv:
  python scripts/generate_historical_prices.py --days 60 --out data/gov_prices_60days.csv

  # Overwrite data/gov_prices.csv directly so `python seed.py` picks it up:
  python scripts/generate_historical_prices.py --days 60 --in-place

  # Direct upsert into live Supabase database (if .env is configured):
  python scripts/generate_historical_prices.py --days 60 --direct-db
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import random
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Core reference commodities with baseline prices and plausible price ranges
COMMODITIES = {
    "Onion": {
        "base_price": 2200.0,
        "daily_volatility": 45.0,
        "min_bound": 800.0,
        "max_bound": 5500.0,
        "base_arrival": 650.0,
        "variety": "Red",
        "grade": "FAQ",
    },
    "Tomato": {
        "base_price": 1850.0,
        "daily_volatility": 65.0,
        "min_bound": 600.0,
        "max_bound": 6000.0,
        "base_arrival": 400.0,
        "variety": "Hybrid",
        "grade": "Grade A",
    },
    "Soybean": {
        "base_price": 4450.0,
        "daily_volatility": 25.0,
        "min_bound": 3200.0,
        "max_bound": 6500.0,
        "base_arrival": 300.0,
        "variety": "Yellow",
        "grade": "FAQ",
    },
    "Maize": {
        "base_price": 2150.0,
        "daily_volatility": 20.0,
        "min_bound": 1400.0,
        "max_bound": 2900.0,
        "base_arrival": 450.0,
        "variety": "Hybrid",
        "grade": "General",
    },
}

# Core Nashik APMC markets with location and regional price deltas
MARKETS = [
    {
        "name": "Lasalgaon",
        "full_name": "Lasalgaon APMC",
        "district": "Nashik",
        "state": "Maharashtra",
        "price_multiplier": 1.00,  # Benchmark hub
    },
    {
        "name": "Pimpalgaon(Niphad)",
        "full_name": "Pimpalgaon Baswant APMC",
        "district": "Nashik",
        "state": "Maharashtra",
        "price_multiplier": 1.02,  # Premium hub
    },
    {
        "name": "Yeola",
        "full_name": "Yeola APMC",
        "district": "Nashik",
        "state": "Maharashtra",
        "price_multiplier": 0.98,
    },
    {
        "name": "Nashik",
        "full_name": "Nashik APMC",
        "district": "Nashik",
        "state": "Maharashtra",
        "price_multiplier": 1.03,  # Urban premium
    },
    {
        "name": "Manmad",
        "full_name": "Manmad APMC",
        "district": "Nashik",
        "state": "Maharashtra",
        "price_multiplier": 0.97,
    },
]


def ist_today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def generate_dataset(days: int = 60, seed: int = 42) -> list[dict]:
    """Generate realistic daily market observations over the requested number of days."""
    rng = random.Random(seed)
    end_date = ist_today()
    start_date = end_date - timedelta(days=days - 1)

    records = []

    # Pre-generate commodity macro paths to maintain price continuity
    macro_paths = {}
    for c_name, c_meta in COMMODITIES.items():
        base = c_meta["base_price"]
        vol = c_meta["daily_volatility"]
        path = []
        curr = base
        for day_idx in range(days):
            # 14-day sinusoidal oscillation + trend drift + daily shock
            sine_wave = math.sin(day_idx * (2 * math.pi / 21)) * (vol * 2.0)
            drift = (day_idx / float(days)) * (vol * 1.5)
            shock = rng.gauss(0, vol * 0.7)
            price = max(c_meta["min_bound"], min(c_meta["max_bound"], curr + sine_wave * 0.15 + drift * 0.1 + shock))
            path.append(price)
            curr = 0.85 * curr + 0.15 * price  # mean reversion dampening
        macro_paths[c_name] = path

    for day_idx in range(days):
        current_date = start_date + timedelta(days=day_idx)

        # Mandi trading schedule: Mandis are closed on Sundays (weekday() == 6)
        if current_date.weekday() == 6:
            continue

        for m in MARKETS:
            # Random holiday / local strike gap ~3%
            if rng.random() < 0.03:
                continue

            for c_name, c_meta in COMMODITIES.items():
                macro_price = macro_paths[c_name][day_idx]
                market_factor = m["price_multiplier"] * rng.uniform(0.985, 1.015)
                modal = round(macro_price * market_factor, 2)

                # Realistic price spread
                min_price = round(modal * rng.uniform(0.88, 0.94), 2)
                max_price = round(modal * rng.uniform(1.06, 1.13), 2)

                # Inverse volume correlation: higher arrivals exert downward price pressure
                volume_mult = 1.0 + (c_meta["base_price"] - modal) / c_meta["base_price"] * 0.6
                arrival_qty = round(max(30.0, c_meta["base_arrival"] * volume_mult * rng.uniform(0.7, 1.3)), 2)

                records.append({
                    "State": m["state"],
                    "District": m["district"],
                    "Market": m["full_name"],
                    "Market_Short": m["name"],
                    "Commodity": c_name,
                    "Variety": c_meta["variety"],
                    "Grade": c_meta["grade"],
                    "Arrival_Date": current_date.strftime("%d/%m/%Y"),
                    "Arrival_Date_ISO": current_date.isoformat(),
                    "Min_x0020_Price": f"{min_price:.2f}",
                    "Max_x0020_Price": f"{max_price:.2f}",
                    "Modal_x0020_Price": f"{modal:.2f}",
                    "Arrival_Qty": f"{arrival_qty:.2f}",
                })

    return records


def write_csv(records: list[dict], filepath: str) -> None:
    """Write records to CSV formatted identically to data/gov_prices.csv."""
    fieldnames = [
        "State",
        "District",
        "Market",
        "Commodity",
        "Variety",
        "Grade",
        "Arrival_Date",
        "Min_x0020_Price",
        "Max_x0020_Price",
        "Modal_x0020_Price",
    ]
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
    print(f"Successfully wrote {len(records)} price rows across {filepath}")


async def upsert_to_supabase(records: list[dict]) -> int:
    """Directly upsert generated rows into Supabase prices table."""
    from dotenv import load_dotenv
    load_dotenv()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env for direct DB write.")
        return 0

    from supabase import create_client
    supabase = create_client(supabase_url, supabase_key)

    # Resolve Commodity and Market IDs
    c_res = supabase.table("commodities").select("id, name_en").execute()
    commodity_map = {r["name_en"]: r["id"] for r in (c_res.data or [])}

    m_res = supabase.table("markets").select("id, name, source_code").execute()
    market_map = {}
    for r in (m_res.data or []):
        if r.get("name"):
            market_map[r["name"]] = r["id"]
        if r.get("source_code"):
            market_map[r["source_code"]] = r["id"]

    db_rows = []
    for r in records:
        c_id = commodity_map.get(r["Commodity"])
        m_id = market_map.get(r["Market"]) or market_map.get(r["Market_Short"])
        if not c_id or not m_id:
            continue

        db_rows.append({
            "market_id": m_id,
            "commodity_id": c_id,
            "arrival_date": r["Arrival_Date_ISO"],
            "min_price": float(r["Min_x0020_Price"]),
            "max_price": float(r["Max_x0020_Price"]),
            "modal_price": float(r["Modal_x0020_Price"]),
            "unit": "quintal",
            "arrival_qty": float(r["Arrival_Qty"]),
            "variety": r["Variety"],
            "grade": r["Grade"],
            "source": "demo_seed",
            "source_ref": f"history_gen|{r['Market_Short']}|{r['Commodity']}|{r['Arrival_Date_ISO']}",
        })

    if not db_rows:
        print("Warning: No matching market/commodity UUIDs found in database.")
        return 0

    print(f"Upserting {len(db_rows)} records into database table 'prices' in batches of 200...")
    conflict = "market_id, commodity_id, arrival_date, variety, grade, source"
    written = 0
    for i in range(0, len(db_rows), 200):
        chunk = db_rows[i:i + 200]
        supabase.table("prices").upsert(chunk, on_conflict=conflict).execute()
        written += len(chunk)

    print(f"Database upsert complete: {written} rows persisted.")
    return written


def main():
    parser = argparse.ArgumentParser(description="Generate 45+ days of agricultural price history")
    parser.add_argument("--days", type=int, default=60, help="Number of historical days (default: 60)")
    parser.add_argument("--out", type=str, default=None, help="Output CSV path (e.g. data/gov_prices_60days.csv)")
    parser.add_argument("--in-place", action="store_true", help="Overwrite data/gov_prices.csv directly")
    parser.add_argument("--direct-db", action="store_true", help="Directly upsert into live Supabase database")
    args = parser.parse_args()

    if args.days < 45:
        print(f"Warning: {args.days} days requested. The forecasting engine & walk-forward backtest require >= 45 days.")

    print(f"Generating {args.days} days of historical market data up to {ist_today()} (IST)...")
    records = generate_dataset(days=args.days)

    default_csv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "gov_prices.csv")
    out_path = default_csv if args.in_place else (args.out or os.path.join(os.path.dirname(default_csv), f"gov_prices_{args.days}days.csv"))

    write_csv(records, out_path)

    if args.direct_db:
        import asyncio
        asyncio.run(upsert_to_supabase(records))


if __name__ == "__main__":
    main()
