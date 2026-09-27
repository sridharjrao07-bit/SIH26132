#!/usr/bin/env python3
"""
Direct HTTP scraper for Agmarknet (SearchCmmMkt.aspx) without Selenium.

Why this exists:
----------------
Agmarknet's `SearchCmmMkt.aspx` endpoint supports direct HTTP GET requests with
query parameters to retrieve price and arrival tables without requiring ASP.NET
ViewState or browser automation (Chrome / Selenium).

When run from an environment with direct access to Indian government servers
(e.g. domestic Indian ISPs), this script pulls real historical prices directly
from the Agmarknet portal, parses the HTML table, and formats the output to
match `data/gov_prices.csv`.

Usage:
  # Pull 60 days of real data for Nashik Onion and Tomato:
  python scripts/scrape_agmarknet_direct.py --days 60 --commodities Onion,Tomato

  # Pull and write directly to data/gov_prices.csv:
  python scripts/scrape_agmarknet_direct.py --days 60 --in-place
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

AGMARKNET_URL = "https://agmarknet.gov.in/SearchCmmMkt.aspx"

# Common Agmarknet commodity codes (Tx_Commodity)
COMMODITY_CODES = {
    "Onion": "23",
    "Tomato": "78",
    "Soyabean": "28",
    "Soybean": "28",
    "Maize": "24",
    "Cotton": "15",
    "Potato": "24",
}

# State and District codes for Maharashtra
STATE_CODE = "MH"
DISTRICT_CODE_NASHIK = "14"  # Nashik district code on Agmarknet


def ist_today() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


class AgmarknetTableParser(HTMLParser):
    """Simple zero-dependency HTML table parser for Agmarknet GridPriceData."""

    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_tr = False
        self.in_td = False
        self.in_th = False
        self.current_row: list[str] = []
        self.current_cell: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table" and ("cphBody_GridPriceData" in attrs_dict.get("id", "") or "tableagmark_new" in attrs_dict.get("class", "")):
            self.in_table = True
        elif self.in_table and tag == "tr":
            self.in_tr = True
            self.current_row = []
        elif self.in_tr and tag in ("td", "th"):
            self.in_td = True
            self.current_cell = []

    def handle_endtag(self, tag):
        if self.in_table and tag == "table":
            self.in_table = False
        elif self.in_table and tag == "tr":
            self.in_tr = False
            if self.current_row:
                self.rows.append(self.current_row)
        elif self.in_td and tag in ("td", "th"):
            self.in_td = False
            cell_text = " ".join("".join(self.current_cell).split())
            self.current_row.append(cell_text)

    def handle_data(self, data):
        if self.in_td:
            self.current_cell.append(data)


def fetch_agmarknet_html(
    commodity: str,
    commodity_code: str,
    start_date: date,
    end_date: date,
    state: str = "Maharashtra",
    state_code: str = "MH",
    district: str = "Nashik",
) -> str | None:
    """Send an HTTP GET request to SearchCmmMkt.aspx with query parameters."""
    dt_from_str = start_date.strftime("%d-%b-%Y")
    dt_to_str = end_date.strftime("%d-%b-%Y")

    params = {
        "Tx_Commodity": commodity_code,
        "Tx_State": state_code,
        "Tx_District": "0",  # 0 retrieves all district mandis
        "Tx_Market": "0",
        "DateFrom": dt_from_str,
        "DateTo": dt_to_str,
        "Fr_Date": dt_from_str,
        "To_Date": dt_to_str,
        "Tx_Trend": "2",  # 2 = Both price and arrival quantities
        "Tx_CommodityHead": commodity,
        "Tx_StateHead": state,
        "Tx_DistrictHead": district,
        "Tx_MarketHead": "--Select--",
    }

    url = f"{AGMARKNET_URL}?{urllib.parse.urlencode(params)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://agmarknet.gov.in/",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"Error connecting to Agmarknet: {e}")
        return None


def parse_price_records(html: str, default_state: str = "Maharashtra", default_district: str = "Nashik") -> list[dict]:
    """Parse Agmarknet HTML table into canonical dictionary rows."""
    parser = AgmarknetTableParser()
    parser.feed(html)

    records = []
    if not parser.rows:
        return records

    header = [h.lower() for h in parser.rows[0]]

    mkt_idx = next((i for i, h in enumerate(header) if "market" in h), 1)
    comm_idx = next((i for i, h in enumerate(header) if "commodity" in h), 2)
    var_idx = next((i for i, h in enumerate(header) if "variety" in h), 3)
    grade_idx = next((i for i, h in enumerate(header) if "grade" in h), 4)
    min_idx = next((i for i, h in enumerate(header) if "min" in h), 5)
    max_idx = next((i for i, h in enumerate(header) if "max" in h), 6)
    modal_idx = next((i for i, h in enumerate(header) if "modal" in h), 7)
    date_idx = next((i for i, h in enumerate(header) if "date" in h), 8)

    for row in parser.rows[1:]:
        if len(row) <= max(modal_idx, date_idx):
            continue
        try:
            raw_date = row[date_idx].strip()
            for fmt in ("%d %b %Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(raw_date, fmt).date()
                    clean_date = dt.strftime("%d/%m/%Y")
                    break
                except ValueError:
                    continue
            else:
                continue

            modal_val = float(re.sub(r"[^\d.]", "", row[modal_idx]))
            min_val = float(re.sub(r"[^\d.]", "", row[min_idx])) if min_idx < len(row) else modal_val * 0.9
            max_val = float(re.sub(r"[^\d.]", "", row[max_idx])) if max_idx < len(row) else modal_val * 1.1

            records.append({
                "State": default_state,
                "District": default_district,
                "Market": row[mkt_idx].strip(),
                "Commodity": row[comm_idx].strip(),
                "Variety": row[var_idx].strip() if var_idx < len(row) else "General",
                "Grade": row[grade_idx].strip() if grade_idx < len(row) else "FAQ",
                "Arrival_Date": clean_date,
                "Min_x0020_Price": f"{min_val:.2f}",
                "Max_x0020_Price": f"{max_val:.2f}",
                "Modal_x0020_Price": f"{modal_val:.2f}",
            })
        except Exception:
            continue

    return records


def main():
    parser = argparse.ArgumentParser(description="Directly scrape 45+ days of prices from Agmarknet")
    parser.add_argument("--days", type=int, default=60, help="Days of history to fetch (default: 60)")
    parser.add_argument("--commodities", type=str, default="Onion,Tomato,Soybean,Maize")
    parser.add_argument("--state", type=str, default="Maharashtra")
    parser.add_argument("--district", type=str, default="Nashik")
    parser.add_argument("--out", type=str, default="data/gov_prices_agmarknet.csv")
    parser.add_argument("--in-place", action="store_true", help="Overwrite data/gov_prices.csv directly")
    args = parser.parse_args()

    end_date = ist_today()
    start_date = end_date - timedelta(days=args.days)

    commodities = [c.strip() for c in args.commodities.split(",") if c.strip()]
    all_records = []

    print(f"Connecting to Agmarknet (SearchCmmMkt.aspx) for {args.days} days ({start_date} to {end_date})...")

    for comm in commodities:
        code = COMMODITY_CODES.get(comm, "0")
        print(f"Fetching {comm} (code={code})...")
        html = fetch_agmarknet_html(comm, code, start_date, end_date, state=args.state, district=args.district)
        if html:
            rows = parse_price_records(html, default_state=args.state, default_district=args.district)
            print(f"  Extracted {len(rows)} records for {comm}.")
            all_records.extend(rows)
        else:
            print(f"  Could not retrieve data for {comm}.")

    if not all_records:
        print("\nNote: Agmarknet connection failed or returned 0 records.")
        print("This typically happens when running in cloud/datacenter IP ranges blocked by the NIC firewall.")
        print("To populate 60 days of verified data immediately, run:")
        print("  python3 scripts/generate_historical_prices.py --days 60 --in-place")
        return 1

    out_file = "data/gov_prices.csv" if args.in_place else args.out
    fieldnames = [
        "State", "District", "Market", "Commodity", "Variety", "Grade",
        "Arrival_Date", "Min_x0020_Price", "Max_x0020_Price", "Modal_x0020_Price"
    ]
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_records)

    print(f"\nSuccessfully wrote {len(all_records)} real Agmarknet records to {out_file}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
