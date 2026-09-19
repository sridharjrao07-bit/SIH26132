import argparse
import asyncio
import sys

import structlog
from app.config import get_settings
from app.deps import get_supabase_service_role
from ingestion.data_gov_in import DataGovInAdapter
from ingestion.runner import _norm_key

logger = structlog.get_logger()

async def backfill(markets_csv: str, commodities_csv: str, sleep_time: float):
    settings = get_settings()
    if not settings.data_gov_in_api_key or settings.data_gov_in_api_key == "offline":
        logger.error("missing_api_key", msg="DATA_GOV_IN_API_KEY is not set")
        sys.exit(1)
        
    supabase = get_supabase_service_role()
    adapter = DataGovInAdapter(api_key=settings.data_gov_in_api_key)
    
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
        
    logger.info("starting_backfill", markets=len(market_list), commodities=len(fetch_keys))
                
    total_seen = 0
    total_written = 0
    total_rejected = 0
    total_transient_skips = 0
    consecutive_transients = 0
    
    persisted_dates = set()
    hard_failure = False
    
    for market in market_list:
        district = market["district"]
        for commodity in fetch_keys:
            if hard_failure:
                break
                
            try:
                raw_records = await adapter.fetch_prices(district=district, commodity=commodity)
                consecutive_transients = 0  # reset circuit breaker
            except Exception as e:
                import httpx
                from ingestion.base import SourceFetchError
                is_transient = False
                if isinstance(e, SourceFetchError) and getattr(e, "__cause__", None) is not None:
                    cause = e.__cause__
                    if isinstance(cause, httpx.HTTPStatusError):
                        if cause.response.status_code >= 500 or cause.response.status_code == 429:
                            is_transient = True
                    elif isinstance(cause, httpx.RequestError):
                        is_transient = True
                elif type(e).__name__ in ("TimeoutError", "ConnectionError"):
                    is_transient = True

                if not is_transient:
                    logger.error("api_fetch_failed_hard", district=district, commodity=commodity, error=str(e))
                    hard_failure = True
                    break
                    
                logger.warning("api_fetch_failed_transient", district=district, commodity=commodity, error=type(e).__name__)
                total_transient_skips += 1
                consecutive_transients += 1
                
                if consecutive_transients >= 3:
                    logger.error("circuit_breaker_tripped", msg="3 consecutive transient failures. Aborting.")
                    sys.exit(1)
                    
                continue
                
            total_seen += len(raw_records)
            
            all_valid = []
            for raw in raw_records:
                valid_dict, reason = validator.validate_and_normalize(raw)
                if valid_dict is None:
                    logger.debug("rejected_by_validator", reason=reason, raw=raw)
                    total_rejected += 1
                    continue
                    
                m_id = market_map.get(_norm_key(raw.market_name))
                if not m_id:
                    logger.debug("rejected_unknown_market", market_name=raw.market_name)
                    total_rejected += 1
                    continue
                    
                valid_dict["market_id"] = m_id
                all_valid.append(valid_dict)
                
            if all_valid:
                conflict = "market_id, commodity_id, arrival_date, variety, grade, source"
                UPSERT_CHUNK = 200
                for i in range(0, len(all_valid), UPSERT_CHUNK):
                    chunk = all_valid[i:i+UPSERT_CHUNK]
                    try:
                        await asyncio.to_thread(
                            lambda c=chunk: supabase.table("prices").upsert(c, on_conflict=conflict).execute()
                        )
                        total_written += len(chunk)
                        for r in chunk:
                            persisted_dates.add(r["arrival_date"])
                    except Exception as e:
                        logger.error("hard_db_write_failed", error=type(e).__name__)
                        hard_failure = True
                        break
                        
            await asyncio.sleep(sleep_time)
            
        if hard_failure:
            break
            
    if hard_failure:
        logger.error("aborting_due_to_db_failure")
        sys.exit(1)

    persisted_list = sorted(list(persisted_dates))
    if len(persisted_list) > 5:
        dates_out = f"{persisted_list[0]} .. {persisted_list[-1]} ({len(persisted_list)} dates)"
    else:
        dates_out = ",".join(str(d) for d in persisted_list) if persisted_list else "None"
        
    logger.info("backfill_complete", persisted_dates=dates_out,
                seen=total_seen, written=total_written, rejected=total_rejected, transient_skips=total_transient_skips)
    
    if total_written == 0:
        logger.error("zero_ingestion", msg="No records were written. Failing loud.")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Backfill historical prices")
    parser.add_argument("--markets", type=str, default="", help="Comma-separated market names")
    parser.add_argument("--commodities", type=str, default="", help="Comma-separated commodity names")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep time between API calls")
    args = parser.parse_args()
    
    asyncio.run(backfill(args.markets, args.commodities, args.sleep))

if __name__ == "__main__":
    main()
