import asyncio
import csv
import os
import sys

from dotenv import load_dotenv
from supabase import Client, create_client

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

async def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        print("Missing Supabase credentials in .env")
        return

    supabase: Client = create_client(supabase_url, supabase_key)
    csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "gov_prices.csv")
    
    unique_markets = {}
    unique_commodities = set()
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            market = row["Market"].strip()
            state = row["State"].strip()
            district = row["District"].strip()
            commodity = row["Commodity"].strip()
            unique_markets[market] = (district, state)
            unique_commodities.add(commodity)
            
    print(f"Found {len(unique_markets)} unique markets and {len(unique_commodities)} unique commodities.")
    
    # 1. Insert Commodities
    print("Fetching existing commodities...")
    resp = supabase.table("commodities").select("name_en").execute()
    existing_commodities = {r["name_en"] for r in resp.data}
    
    new_commodities = []
    for c in unique_commodities:
        if c not in existing_commodities:
            new_commodities.append({
                "name_en": c,
                "name_mr": c,
                "name_hi": c,
                "category": "other",
                "standard_unit": "quintal",
                "sanity_min": 1,
                "sanity_max": 999999
            })
            existing_commodities.add(c)
            
    if new_commodities:
        print(f"Inserting {len(new_commodities)} new commodities...")
        for i in range(0, len(new_commodities), 200):
            supabase.table("commodities").upsert(new_commodities[i:i+200], on_conflict="name_en").execute()
            
    # Fetch mapping
    resp = supabase.table("commodities").select("id, name_en").execute()
    commodity_ids = {r["name_en"]: r["id"] for r in resp.data}
    
    # 2. Insert Aliases
    resp = supabase.table("commodity_alias").select("source_key").eq("source", "csv").execute()
    existing_aliases = {r["source_key"] for r in resp.data}
    
    new_aliases = []
    for c in unique_commodities:
        norm_key = " ".join(c.strip().lower().split())
        if norm_key not in existing_aliases:
            new_aliases.append({
                "source": "csv",
                "source_key": c,  # The original case for alias
                "commodity_id": commodity_ids[c]
            })
            existing_aliases.add(norm_key)
            
    if new_aliases:
        print(f"Inserting {len(new_aliases)} new aliases...")
        for i in range(0, len(new_aliases), 200):
            supabase.table("commodity_alias").upsert(new_aliases[i:i+200], on_conflict="source,source_key").execute()

    # 3. Insert Markets
    print("Fetching existing markets...")
    resp = supabase.table("markets").select("source_code").execute()
    existing_markets = {r["source_code"] for r in resp.data if r.get("source_code")}
    
    new_markets = []
    for m, (d, s) in unique_markets.items():
        if m not in existing_markets:
            new_markets.append({
                "name": f"{m} APMC",
                "district": d,
                "state": s,
                "taluka": d,
                "lat": 20.0,  # Dummy coords
                "lng": 73.0,
                "source_code": m,
                "is_active": True
            })
            existing_markets.add(m)
            
    if new_markets:
        print(f"Inserting {len(new_markets)} new markets...")
        # Since markets table might not have unique on source_code, we just insert
        for i in range(0, len(new_markets), 200):
            supabase.table("markets").insert(new_markets[i:i+200]).execute()

    print("Seeding complete! You can now run ingest_csv.py")

if __name__ == "__main__":
    asyncio.run(main())
