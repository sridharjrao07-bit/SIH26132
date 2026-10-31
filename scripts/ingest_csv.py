import asyncio
import argparse
import csv
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from supabase import Client, create_client

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ingestion.base import RawPriceRecord
from ingestion.validator import PriceValidator

load_dotenv()

async def main():
    parser = argparse.ArgumentParser(description="Validate and ingest a government price CSV")
    parser.add_argument(
        "--csv",
        dest="csv_file",
        default=None,
        help="CSV file to ingest (default: data/gov_prices.csv)",
    )
    parser.add_argument(
        "--source",
        choices=("csv", "agmarknet", "data_gov_in"),
        default="csv",
        help="provenance to persist for these rows (default: csv)",
    )
    args = parser.parse_args()

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        print("Missing Supabase credentials in .env")
        sys.exit(1)

    supabase: Client = create_client(supabase_url, supabase_key)
    csv_path = args.csv_file or os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "gov_prices.csv")
    if not os.path.isabs(csv_path):
        csv_path = os.path.join(os.getcwd(), csv_path)
    
    if not os.path.exists(csv_path):
        print(f"CSV not found at {csv_path}")
        sys.exit(1)

    print("Fetching metadata...")
    resp = supabase.table("commodity_alias").select("commodity_id, source, source_key").execute()
    commodity_id_map = {}
    for row in resp.data:
        norm_key = " ".join((row["source_key"] or "").strip().lower().split())
        commodity_id_map[f"csv|{norm_key}"] = row["commodity_id"]
        commodity_id_map[f"{row['source']}|{norm_key}"] = row["commodity_id"]

    resp = supabase.table("commodities").select("id, name_en, sanity_min, sanity_max").execute()
    sanity_bands = {
        row["id"]: (row["sanity_min"], row["sanity_max"])
        for row in resp.data
        if row["sanity_min"] is not None and row["sanity_max"] is not None
    }
    
    resp = supabase.table("markets").select("id, name, source_code").execute()
    market_map = {}
    for row in resp.data:
        for k in (row.get("source_code"), row.get("name")):
            if k:
                norm_k = " ".join(k.strip().lower().split())
                market_map[norm_k] = row["id"]

    validator = PriceValidator(commodity_id_map, sanity_bands)
    
    print("Parsing CSV...")
    valid_records = []
    rejected_count = 0
    parse_errors: list[str] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                dt = datetime.strptime(row["Arrival_Date"], "%d/%m/%Y").date()
                min_p = float(row["Min_x0020_Price"]) if row.get("Min_x0020_Price") else None
                max_p = float(row["Max_x0020_Price"]) if row.get("Max_x0020_Price") else None
                modal_p = float(row["Modal_x0020_Price"]) if row.get("Modal_x0020_Price") else 0.0

                raw = RawPriceRecord(
                    market_name=row["Market"],
                    commodity_name=row["Commodity"],
                    arrival_date=dt,
                    min_price=min_p,
                    max_price=max_p,
                    modal_price=modal_p,
                    unit="quintal",
                    variety=row.get("Variety", "General"),
                    grade=row.get("Grade", "General"),
                    source=args.source,
                    raw_payload=row
                )
                
                valid_dict, reason = validator.validate_and_normalize(raw)
                if not valid_dict:
                    rejected_count += 1
                    continue
                
                market_key = " ".join(row["Market"].strip().lower().split())
                market_id = market_map.get(market_key)
                if not market_id:
                    alt_key = market_key.replace(" apmc", "").replace(" market", "").strip()
                    market_id = market_map.get(alt_key)
                    
                if not market_id:
                    rejected_count += 1
                    continue
                    
                valid_dict["market_id"] = market_id
                valid_records.append(valid_dict)
            except Exception as e:
                rejected_count += 1
                if len(parse_errors) < 5:
                    parse_errors.append(f"{type(e).__name__}: {e}")

    print(f"Parsed {len(valid_records)} valid records. Rejected {rejected_count} records.")
    for err in parse_errors:
        print(f"  malformed row example: {err}")
    
    if valid_records:
        print("Upserting to DB...")
        chunk_size = 200
        conflict = "market_id, commodity_id, arrival_date, variety, grade, source"
        written = 0
        for i in range(0, len(valid_records), chunk_size):
            chunk = valid_records[i:i+chunk_size]
            try:
                supabase.table("prices").upsert(chunk, on_conflict=conflict).execute()
                written += len(chunk)
            except Exception as e:
                print(f"Error upserting chunk: {e}")
        print(f"Upserted {written} records.")

if __name__ == "__main__":
    asyncio.run(main())
