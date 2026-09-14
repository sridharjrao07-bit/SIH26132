import asyncio
import argparse
import sys
import structlog
import time
from datetime import date, timedelta
from app.config import get_settings
from app.deps import get_supabase_service_role
from ingestion.data_gov_in import DataGovInAdapter
from ingestion.runner import _norm_key

logger = structlog.get_logger()

async def backfill(days: int, markets_csv: str, commodities_csv: str, sleep_time: float):
    settings = get_settings()
    if not settings.data_gov_in_api_key or settings.data_gov_in_api_key == "offline":
        logger.error("missing_api_key", msg="DATA_GOV_IN_API_KEY is not set")
        sys.exit(1)
        
    supabase = get_supabase_service_role()
    adapter = DataGovInAdapter(api_key=settings.data_gov_in_api_key)
    
    # Instantiate the runner just to get the metadata fetch and validator logic
    # We will mimic the runner's _log_run and DB paths but control the loop.
    # runner = IngestionRunner(supabase=supabase, adapters=[adapter])
    
    # We need commodity_id_map and sanity_bands for PriceValidator
    try:
        resp = supabase.table("commodity_alias").select("commodity_id, source, source_key").execute()
        commodity_id_map = {f"{r['source']}|{_norm_key(r['source_key'])}": r["commodity_id"] for r in resp.data}
        
        resp = supabase.table("commodities").select("id, name_en, sanity_min, sanity_max").execute()
        sanity_bands = {
            r["id"]: (r["sanity_min"], r["sanity_max"])
            for r in resp.data if r["sanity_min"] is not None and r["sanity_max"] is not None
        }
    except Exception as e:
        logger.error("metadata_fetch_failed", error=str(e))
        sys.exit(1)
        
    from ingestion.validator import PriceValidator
    validator = PriceValidator(commodity_id_map=commodity_id_map, sanity_bands=sanity_bands)
    
    # For markets, we query all or the provided list
    market_names = [m.strip() for m in markets_csv.split(",") if m.strip()]
    commodities = [c.strip() for c in commodities_csv.split(",") if c.strip()]
    
    try:
        if market_names:
            resp = supabase.table("markets").select("id, name, source_code, district").in_("name", market_names).execute()
        else:
            resp = supabase.table("markets").select("id, name, source_code, district").execute()
        
        market_map = {}
        market_list = resp.data
        for row in market_list:
            for key in (row.get("source_code"), row.get("name")):
                k = _norm_key(key)
                if k:
                    market_map[k] = row["id"]
    except Exception as e:
        logger.error("market_fetch_failed", error=str(e))
        sys.exit(1)

    if not market_list:
        logger.error("no_markets_found")
        sys.exit(1)
        
    # Get aliases for the requested commodities
    try:
        resp_aliases = supabase.table("commodity_alias").select("source_key").eq("source", adapter.source_name)
        if commodities:
            resp_aliases = resp_aliases.in_("source_key", commodities)
        resp_aliases = resp_aliases.execute()
        
        fetch_keys = list(set(r["source_key"] for r in resp_aliases.data))
    except Exception as e:
        logger.error("alias_fetch_failed", error=str(e))
        sys.exit(1)
        
    if not fetch_keys:
        logger.error("no_aliases_found")
        sys.exit(1)
        
    # Generate dates
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    dates_to_fetch = [start_date + timedelta(days=i) for i in range(days + 1)]
    
    logger.info("starting_backfill", start_date=start_date.isoformat(), end_date=end_date.isoformat(),
                markets=len(market_list), commodities=len(fetch_keys), days=len(dates_to_fetch))
                
    total_seen = 0
    total_written = 0
    total_rejected = 0
    
    hard_failure = False
    
    for dt in dates_to_fetch:
        seen = 0
        written = 0
        rejected = 0
        
        for market in market_list:
            district = market["district"]
            for commodity in fetch_keys:
                try:
                    raw_records = await adapter.fetch_prices(district=district, commodity=commodity, date=dt)
                    seen += len(raw_records)
                    
                    all_valid = []
                    for raw in raw_records:
                        valid_dict, reason = validator.validate_and_normalize(raw)
                        if valid_dict is None:
                            rejected += 1
                            continue
                            
                        m_id = market_map.get(_norm_key(raw.market_name))
                        if not m_id:
                            rejected += 1
                            continue
                            
                        valid_dict["market_id"] = m_id
                        all_valid.append(valid_dict)
                        
                    if all_valid:
                        conflict = "market_id, commodity_id, arrival_date, variety, grade, source"
                        UPSERT_CHUNK = 200
                        for i in range(0, len(all_valid), UPSERT_CHUNK):
                            chunk = all_valid[i:i+UPSERT_CHUNK]
                            # Run DB call in thread
                            await asyncio.to_thread(
                                lambda c=chunk: supabase.table("prices").upsert(c, on_conflict=conflict).execute()
                            )
                            written += len(chunk)
                except Exception as e:
                    logger.warning("fetch_failed", district=district, commodity=commodity, date=dt.isoformat(), error=str(e))
                    continue
                    
                time.sleep(sleep_time)

        logger.info("date_processed", date=dt.isoformat(), seen=seen, written=written, rejected=rejected)
        total_seen += seen
        total_written += written
        total_rejected += rejected

    logger.info("backfill_complete", dates_written=f"{start_date.isoformat()}..{end_date.isoformat()}",
                seen=total_seen, written=total_written, rejected=total_rejected)
    
    if hard_failure:
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Backfill historical prices")
    parser.add_argument("--days", type=int, required=True, help="Number of days to backfill")
    parser.add_argument("--markets", type=str, default="", help="Comma-separated market names")
    parser.add_argument("--commodities", type=str, default="", help="Comma-separated commodity names")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep time between API calls")
    args = parser.parse_args()
    
    asyncio.run(backfill(args.days, args.markets, args.commodities, args.sleep))

if __name__ == "__main__":
    main()
