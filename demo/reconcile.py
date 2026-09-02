#!/usr/bin/env python3
"""
SIH26132 — Pre-event Reconciliation Script (§8)
================================================
Run this BEFORE the hackathon to verify that:
  1. The data.gov.in API actually returns data for Nashik (both spellings)
  2. The exact market strings from the API match your seeded source_code values
  3. The exact commodity strings match your seeded alias source_key values
  4. The idempotency test: running seed twice gives identical counts
  5. The RLS test: anon can read prices but cannot read ingestion_log

Usage:
    python demo/reconcile.py

Requires only stdlib + httpx (already in requirements.txt).
Set DATA_GOV_IN_API_KEY in your .env before running.
"""

import sys
import json
import urllib.request
import urllib.parse
from pathlib import Path

# ── Load .env manually (no dotenv dependency needed) ──────────────────────────
def load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        print("[ERROR] .env file not found. Copy .env.example → .env and fill in keys.")
        sys.exit(1)
    env = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

env = load_env()

API_KEY      = env.get("DATA_GOV_IN_API_KEY", "")
SUPABASE_URL = env.get("SUPABASE_URL", "")
ANON_KEY     = env.get("SUPABASE_ANON_KEY", "")
RESOURCE     = "9ef84268-d588-465a-a308-a864a43d0070"
BASE_URL     = f"https://api.data.gov.in/resource/{RESOURCE}"

SEEDED_SOURCE_CODES = ["Lasalgaon", "Pimpalgaon(Niphad)", "Yeola", "Nashik", "Manmad"]
SEEDED_COMMODITIES  = ["Onion", "Onion(Red)", "Onion (Red)", "Tomato", "Soyabean", "Soybean", "Maize"]

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"
INFO = "[INFO]"


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def fetch_json(url: str, headers: dict = None) -> dict:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

def api_get(params: dict) -> dict:
    qs = urllib.parse.urlencode(params)
    return fetch_json(f"{BASE_URL}?{qs}")

def supabase_get(path: str) -> tuple[int, dict]:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {ANON_KEY}",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}


# ── Test 1: API connectivity & district spelling ──────────────────────────────
def test_api_connectivity():
    print("\n=== Test 1: data.gov.in API + district spelling ===")
    if not API_KEY or "your-data-gov-in-key" in API_KEY:
        print(f"{WARN} DATA_GOV_IN_API_KEY not set — skipping API tests.")
        return []

    found_markets = set()
    for district in ["Nashik", "Nasik"]:
        try:
            data = api_get({
                "api-key": API_KEY,
                "format": "json",
                "filters[state]": "Maharashtra",
                "filters[district]": district,
                "filters[commodity]": "Onion",
                "limit": 50,
            })
            records = data.get("records", [])
            print(f"{PASS if records else WARN} filters[district]={district!r} → {len(records)} records")
            for r in records:
                found_markets.add(r.get("market", "").strip())
        except Exception as e:
            print(f"{FAIL} filters[district]={district!r} → {e}")
    return list(found_markets)


# ── Test 2: Market string reconciliation ─────────────────────────────────────
def test_market_reconciliation(api_markets: list[str]):
    print("\n=== Test 2: Market source_code reconciliation ===")
    if not api_markets:
        print(f"{WARN} No API markets to reconcile (API key missing or returned 0 records).")
        return

    api_set   = {m.strip().lower() for m in api_markets}
    seed_set  = {s.strip().lower() for s in SEEDED_SOURCE_CODES}
    matched   = api_set & seed_set
    unmatched = api_set - seed_set
    missing   = seed_set - api_set

    print(f"{INFO} API returned {len(api_set)} distinct market strings")
    for m in sorted(matched):
        print(f"  {PASS} '{m}' matches seeded source_code")
    for m in sorted(unmatched):
        print(f"  {WARN} '{m}' from API has NO matching source_code in seed — UPDATE 002_seed.sql!")
    for m in sorted(missing):
        print(f"  {WARN} seeded '{m}' not seen in API response — may be wrong spelling or no data today")


# ── Test 3: Commodity string reconciliation ───────────────────────────────────
def test_commodity_reconciliation():
    print("\n=== Test 3: Commodity alias reconciliation ===")
    if not API_KEY or "your-data-gov-in-key" in API_KEY:
        print(f"{WARN} DATA_GOV_IN_API_KEY not set — skipping.")
        return

    try:
        data = api_get({
            "api-key": API_KEY,
            "format": "json",
            "filters[state]": "Maharashtra",
            "filters[district]": "Nashik",
            "limit": 100,
        })
        api_commodities = {
            r.get("commodity", "").strip()
            for r in data.get("records", [])
        }
    except Exception as e:
        print(f"{FAIL} Could not fetch commodity list: {e}")
        return

    seed_set = {s.strip().lower() for s in SEEDED_COMMODITIES}
    for c in sorted(api_commodities):
        status = PASS if c.lower() in seed_set else WARN
        note   = "" if c.lower() in seed_set else " ← ADD to 002_seed.sql commodity_alias!"
        print(f"  {status} API commodity: '{c}'{note}")


# ── Test 4: Supabase RLS ──────────────────────────────────────────────────────
def test_rls():
    print("\n=== Test 4: Supabase RLS (anon key) ===")
    if not SUPABASE_URL or "your-project" in SUPABASE_URL:
        print(f"{WARN} SUPABASE_URL not configured — skipping RLS tests.")
        return

    status, data = supabase_get("prices?select=id&limit=1")
    if status == 200:
        print(f"  {PASS} anon can SELECT prices (expected: public read)")
    else:
        print(f"  {FAIL} anon cannot SELECT prices — HTTP {status} (check RLS policy)")

    status, data = supabase_get("markets?select=id&limit=1")
    if status == 200:
        print(f"  {PASS} anon can SELECT markets (expected: public read)")
    else:
        print(f"  {FAIL} anon cannot SELECT markets — HTTP {status}")

    status, data = supabase_get("ingestion_log?select=id&limit=1")
    if status in (200,) and isinstance(data, list) and len(data) > 0:
        print(f"  {FAIL} anon can read ingestion_log — RLS is NOT blocking! Run 003_security_patch.sql")
    elif status in (401, 403) or (status == 200 and isinstance(data, list) and len(data) == 0):
        print(f"  {PASS} anon blocked from ingestion_log (HTTP {status} or empty — RLS working)")
    else:
        print(f"  {WARN} ingestion_log response HTTP {status} — verify manually")


# ── Test 5: Idempotency reminder ──────────────────────────────────────────────
def test_idempotency_reminder():
    print("\n=== Test 5: Idempotency instructions ===")
    print(f"  {INFO} Run these in the Supabase SQL Editor to verify seed is idempotent:")
    print()
    print("    -- Step 1: Note current counts")
    print("    select 'markets' as tbl, count(*) from public.markets")
    print("    union all select 'commodities', count(*) from public.commodities")
    print("    union all select 'commodity_alias', count(*) from public.commodity_alias;")
    print()
    print("    -- Step 2: Re-run 002_seed.sql (paste it again in SQL editor)")
    print()
    print("    -- Step 3: Run counts again — numbers must be IDENTICAL to Step 1.")
    print("    -- If any count increased, there is a missing ON CONFLICT clause in the seed.")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("SIH26132 Pre-Event Reconciliation Check")
    print("=" * 60)

    api_markets = test_api_connectivity()
    test_market_reconciliation(api_markets)
    test_commodity_reconciliation()
    test_rls()
    test_idempotency_reminder()

    print("\n" + "=" * 60)
    print("Done. Fix any [WARN]/[FAIL] items before demo day.")
    print("=" * 60)
