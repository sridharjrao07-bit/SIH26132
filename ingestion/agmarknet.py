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

# Seeded Nashik APMC source_code values (002_seed.sql). The scraper dropdown
# typically uses the short market name; we try each mandi independently.
NASHIK_MARKETS = ["Lasalgaon", "Pimpalgaon", "Yeola", "Nashik", "Manmad"]


class AgmarknetAdapter(IngestionSourceAdapter):
    """
    Adapter for Agmarknet using the cloned selenium scraper (Prajwal-Shrimali/agmarknetAPI).
    This acts as a fallback source if data.gov.in is missing data.
    """

    @property
    def source_name(self) -> str:
        return "agmarknet"

    def _markets_for(self, district: str) -> List[str]:
        if district.lower() in ("nashik", "nasik"):
            return list(NASHIK_MARKETS)
        return [district]

    async def fetch_prices(self, district: str, commodity: str, state: str = "Maharashtra") -> List[RawPriceRecord]:
        log = logger.bind(source=self.source_name, district=district, commodity=commodity)
        records: List[RawPriceRecord] = []

        try:
            from APIwebScraping import script
        except ImportError as e:
            log.error("agmarknet_scraper_import_failed", reason="Is selenium installed and agmarknetAPI cloned?")
            raise SourceFetchError("agmarknetAPI script import failed") from e

        last_err = None
        for market_to_query in self._markets_for(district):
            log.info("fetching_data_via_selenium", market=market_to_query)
            try:
                raw_data = await asyncio.wait_for(
                    asyncio.to_thread(script, state, commodity, market_to_query),
                    timeout=90,
                )
            except Exception as e:
                last_err = e
                log.warning("selenium_market_failed", market=market_to_query, error=str(e))
                continue

            for item in raw_data or []:
                try:
                    date_str = item.get("Date", "").strip()
                    if not date_str:
                        continue

                    arrival_date = datetime.strptime(date_str, "%d %b %Y").date()

                    modal_price = float(item.get("Model Prize", 0))
                    if modal_price <= 0:
                        continue

                    min_price = float(item.get("Min Prize", 0)) if item.get("Min Prize") else None
                    max_price = float(item.get("Max Prize", 0)) if item.get("Max Prize") else None

                    arrival_qty = None
                    for qty_key in ("Arrival (Tonnes)", "Arrival (Tonnes) ", "Arrivals", "Arrival"):
                        raw_qty = item.get(qty_key)
                        if raw_qty in (None, ""):
                            continue
                        try:
                            # Usually scraped values could have commas or text
                            clean_qty = str(raw_qty).replace(",", "").strip()
                            q = float(clean_qty)
                            if q >= 0:
                                # If the key explicitly mentions Tonnes, multiply by 10 for Quintals
                                if "Tonnes" in qty_key:
                                    arrival_qty = q * 10
                                else:
                                    arrival_qty = q
                                break
                        except (TypeError, ValueError):
                            continue

                    record = RawPriceRecord(
                        market_name=item.get("City", "").strip() or market_to_query,
                        commodity_name=item.get("Commodity", "").strip(),
                        arrival_date=arrival_date,
                        min_price=min_price,
                        max_price=max_price,
                        modal_price=modal_price,
                        unit="quintal",
                        arrival_qty=arrival_qty,
                        variety="General",
                        grade="General",
                        source=self.source_name,
                        raw_payload=item,
                    )
                    records.append(record)
                except Exception as e:
                    log.warning("failed_to_parse_record", record=item, error=str(e))
                    continue

        if not records:
            raise SourceFetchError(f"agmarknet scraper failed: {last_err}") from last_err

        return records
