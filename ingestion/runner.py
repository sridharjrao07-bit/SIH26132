import structlog
import asyncio
from typing import List, Dict, Any
from supabase import create_client, Client
from datetime import datetime, timezone

from .base import IngestionSourceAdapter, RawPriceRecord
from .validator import PriceValidator

logger = structlog.get_logger()

class IngestionRunner:
    def __init__(self, supabase: Client, adapters: List[IngestionSourceAdapter]):
        self.supabase = supabase
        self.adapters = adapters
        
    async def run(self, district: str, state: str = "Maharashtra"):
        """
        Main ingestion orchestrator.
        1. Fetches metadata (commodity aliases, sanity bands, markets).
        2. Polls all adapters for data.
        3. Validates and normalizes records.
        4. Upserts into Supabase.
        5. Logs the run to ingestion_log.
        """
        run_id = f"run_{int(datetime.now(timezone.utc).timestamp())}"
        log = logger.bind(run_id=run_id, district=district)
        log.info("ingestion_started")
        
        try:
            # 1. Fetch aliases to build the commodity mapping
            # (source, source_key) -> internal commodity_id
            resp = self.supabase.table("commodity_alias").select("commodity_id, source, source_key").execute()
            commodity_id_map = {
                f"{row['source']}|{row['source_key']}": row['commodity_id']
                for row in resp.data
            }
            
            # Fetch sanity bands for validation
            resp = self.supabase.table("commodities").select("id, sanity_min_price, sanity_max_price").execute()
            sanity_bands = {
                row['id']: (row['sanity_min_price'], row['sanity_max_price'])
                for row in resp.data
                if row['sanity_min_price'] is not None and row['sanity_max_price'] is not None
            }
            
            # Fetch markets to resolve market_id
            resp = self.supabase.table("markets").select("id, name, district").eq("district", district).execute()
            market_map = {row['name'].lower(): row['id'] for row in resp.data}
            
            validator = PriceValidator(commodity_id_map=commodity_id_map, sanity_bands=sanity_bands)
            
            # Get distinct commodities that are tracked in this district based on our aliases
            # For simplicity, let's just query our commodities table. We want to pull for all active ones.
            resp = self.supabase.table("commodities").select("name_en").execute()
            commodities_to_fetch = [r['name_en'] for r in resp.data]
            
            all_valid_records = []
            
            # 2. Fetch data from adapters
            for adapter in self.adapters:
                for commodity in commodities_to_fetch:
                    raw_records = await adapter.fetch_prices(district=district, commodity=commodity, state=state)
                    
                    for raw in raw_records:
                        # Validate and normalize
                        valid_dict = validator.validate_and_normalize(raw)
                        if not valid_dict:
                            continue
                            
                        # Resolve Market ID
                        market_id = market_map.get(raw.market_name.lower())
                        if not market_id:
                            log.warning("unknown_market", market=raw.market_name)
                            continue
                            
                        valid_dict["market_id"] = market_id
                        all_valid_records.append(valid_dict)
                        
            # 3. Upsert into Supabase
            if all_valid_records:
                # Upsert relies on the unique constraint (market_id, commodity_id, arrival_date)
                self.supabase.table("prices").upsert(all_valid_records, on_conflict="market_id, commodity_id, arrival_date").execute()
                log.info("ingestion_completed", records_inserted=len(all_valid_records))
            else:
                log.info("ingestion_completed", records_inserted=0)
                
            # Log success
            self._log_run(status="SUCCESS", records_fetched=len(all_valid_records), source="data.gov.in")
            
        except Exception as e:
            log.error("ingestion_failed", error=str(e), exc_info=True)
            self._log_run(status="FAILURE", records_fetched=0, source="system", error_message=str(e))
            
    def _log_run(self, status: str, records_fetched: int, source: str, error_message: str = None):
        """Writes to ingestion_log table."""
        try:
            self.supabase.table("ingestion_log").insert({
                "source": source,
                "status": status,
                "records_fetched": records_fetched,
                "error_message": error_message
            }).execute()
        except Exception as e:
            logger.error("failed_to_write_ingestion_log", error=str(e))
