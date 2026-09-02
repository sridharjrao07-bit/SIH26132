import structlog
import asyncio
import sys
import os
from typing import List
from datetime import datetime
from .base import IngestionSourceAdapter, RawPriceRecord, SourceFetchError

logger = structlog.get_logger()

# Add the cloned repo to sys.path so we can import its script
repo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "agmarknetAPI"))
if repo_path not in sys.path:
    sys.path.append(repo_path)

class AgmarknetAdapter(IngestionSourceAdapter):
    """
    Adapter for Agmarknet using the cloned selenium scraper (Prajwal-Shrimali/agmarknetAPI).
    This acts as a fallback source if data.gov.in is missing data.
    """
    
    @property
    def source_name(self) -> str:
        return "agmarknet"
        
    async def fetch_prices(self, district: str, commodity: str, state: str = "Maharashtra") -> List[RawPriceRecord]:
        log = logger.bind(source=self.source_name, district=district, commodity=commodity)
        records: List[RawPriceRecord] = []
        
        try:
            # We must import inside the method or safely at top to avoid crashing 
            # the whole app if selenium is missing.
            from APIwebScraping import script
        except ImportError as e:
            log.error("agmarknet_scraper_import_failed", reason="Is selenium installed and agmarknetAPI cloned?")
            raise SourceFetchError("agmarknetAPI script import failed") from e
            
        log.info("fetching_data_via_selenium")
        
        # The cloned script requires the exact market name. For this adapter, 
        # we will use the district name as the market name for the dropdown, 
        # or a known default mandi if district fails (like Lasalgaon for Nashik).
        # In a robust implementation, we'd loop through all mandis in the district.
        market_to_query = "Lasalgaon" if district.lower() == "nashik" else district
        
        try:
            # Run the synchronous selenium script in a thread pool so we don't block the async event loop
            raw_data = await asyncio.wait_for(asyncio.to_thread(script, state, commodity, market_to_query), timeout=120)
            
            log.info("received_records", count=len(raw_data))
            
            for item in raw_data:
                # Expected dict: {"S.No": "...", "City": "...", "Commodity": "...", "Min Prize": "...", "Max Prize": "...", "Model Prize": "...", "Date": "..."}
                try:
                    date_str = item.get("Date", "").strip()
                    if not date_str:
                        continue
                        
                    # Format in script is usually DD MMM YYYY (e.g. 17 Dec 2023)
                    arrival_date = datetime.strptime(date_str, "%d %b %Y").date()
                    
                    modal_price = float(item.get("Model Prize", 0))
                    if modal_price <= 0:
                        continue
                        
                    min_price = float(item.get("Min Prize", 0)) if item.get("Min Prize") else None
                    max_price = float(item.get("Max Prize", 0)) if item.get("Max Prize") else None
                    
                    record = RawPriceRecord(
                        market_name=item.get("City", "").strip(),
                        commodity_name=item.get("Commodity", "").strip(),
                        arrival_date=arrival_date,
                        min_price=min_price,
                        max_price=max_price,
                        modal_price=modal_price,
                        unit="quintal", # Agmarknet uses Rs/Quintal
                        variety="General",
                        grade="General",
                        source=self.source_name,
                        raw_payload=item
                    )
                    records.append(record)
                except Exception as e:
                    log.warning("failed_to_parse_record", record=item, error=str(e))
                    continue
                    
        except Exception as e:
            log.error("selenium_scraper_failed", error=str(e))
            raise SourceFetchError(f"agmarknet scraper failed: {e}") from e
            
        return records
