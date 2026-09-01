import httpx
import structlog
from typing import List
from datetime import datetime

from .base import IngestionSourceAdapter, RawPriceRecord

logger = structlog.get_logger()

class DataGovInAdapter(IngestionSourceAdapter):
    """
    Adapter for the official Indian Government data.gov.in API.
    Resource: 9ef84268-d588-465a-a308-a864a43d0070 (Daily Mandi Prices)
    """
    
    BASE_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        
    @property
    def source_name(self) -> str:
        return "data.gov.in"
        
    async def fetch_prices(self, district: str, commodity: str, state: str = "Maharashtra") -> List[RawPriceRecord]:
        """
        Fetches the latest prices for a given district and commodity.
        """
        params = {
            "api-key": self.api_key,
            "format": "json",
            "filters[state.keyword]": state,
            "filters[district.keyword]": district,
            "filters[commodity.keyword]": commodity,
            "limit": 100 # Should be enough for daily updates for a single district/commodity
        }
        
        log = logger.bind(source=self.source_name, district=district, commodity=commodity)
        log.info("fetching_data", url=self.BASE_URL)
        
        records: List[RawPriceRecord] = []
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.BASE_URL, params=params, timeout=10.0)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as e:
                log.error("http_request_failed", error=str(e))
                return records
            except Exception as e:
                log.error("json_parse_failed", error=str(e))
                return records
                
        # Parse the JSON response
        # data.gov.in format: {"records": [ { "state": "...", "district": "...", "market": "...", "commodity": "...", "variety": "...", "grade": "...", "arrival_date": "17/12/2023", "min_price": "2000", "max_price": "2500", "modal_price": "2300" } ]}
        
        raw_records = data.get("records", [])
        log.info("received_records", count=len(raw_records))
        
        for item in raw_records:
            try:
                # Parse arrival date (usually DD/MM/YYYY)
                date_str = item.get("arrival_date", "")
                arrival_date = datetime.strptime(date_str, "%d/%m/%Y").date()
                
                # We need modal price at minimum
                modal_price = float(item.get("modal_price", 0))
                if modal_price <= 0:
                    continue
                    
                min_price = float(item.get("min_price")) if item.get("min_price") else None
                max_price = float(item.get("max_price")) if item.get("max_price") else None
                
                record = RawPriceRecord(
                    market_name=item.get("market", "").strip(),
                    commodity_name=item.get("commodity", "").strip(),
                    arrival_date=arrival_date,
                    min_price=min_price,
                    max_price=max_price,
                    modal_price=modal_price,
                    unit="quintal", # data.gov.in typically reports in Rs/Quintal
                    variety=item.get("variety", "General"),
                    grade=item.get("grade", "General"),
                    source=self.source_name,
                    raw_payload=item
                )
                records.append(record)
            except Exception as e:
                log.warning("failed_to_parse_record", record=item, error=str(e))
                continue
                
        return records
