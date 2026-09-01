import httpx
import structlog
from typing import List
from datetime import datetime

from .base import IngestionSourceAdapter, RawPriceRecord, SourceFetchError

logger = structlog.get_logger()


class DataGovInAdapter(IngestionSourceAdapter):
    """
    Adapter for the official Indian Government data.gov.in API.
    Resource: 9ef84268-d588-465a-a308-a864a43d0070 (Daily Mandi Prices)

    Filter syntax: plain filters[district], NOT filters[district.keyword].
    Verify once with curl before the event — if your resource variant needs
    .keyword, adjust the params dict and document it here.

    Fetch strategy: the runner passes each alias source_key directly so we
    use the exact API spelling ("Soyabean" not "Soybean"), avoiding 0-result
    fetches from a mis-spelled commodity filter.
    """

    BASE_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
    # Fallback district spellings seen in the dataset
    DISTRICT_SPELLINGS = ["Nashik", "Nasik"]

    def __init__(self, api_key: str):
        self.api_key = api_key

    @property
    def source_name(self) -> str:
        # FIX BLOCKER 1: must match commodity_alias.source = 'data_gov_in'
        return "data_gov_in"

    async def fetch_prices(
        self, district: str, commodity: str, state: str = "Maharashtra"
    ) -> List[RawPriceRecord]:
        """
        Raises SourceFetchError on HTTP failure or unexpected response shape.
        """
        log = logger.bind(source=self.source_name, district=district, commodity=commodity)

        # Try primary spelling, then fallbacks (both "Nashik" and "Nasik" exist in dataset)
        spellings = [district] + [s for s in self.DISTRICT_SPELLINGS if s != district]
        data = None

        async with httpx.AsyncClient(timeout=10.0) as client:
            for spelling in spellings:
                params = {
                    "api-key":                   self.api_key,
                    "format":                    "json",
                    "filters[state]":            state,
                    "filters[district]":         spelling,
                    "filters[commodity]":        commodity,
                    "limit":                     100,
                }
                log.info("fetching_data", url=self.BASE_URL, district_spelling=spelling)
                try:
                    response = await client.get(self.BASE_URL, params=params)
                    response.raise_for_status()
                    data = response.json()
                except httpx.HTTPStatusError as e:
                    raise SourceFetchError(
                        f"data.gov.in HTTP {e.response.status_code} for "
                        f"district={spelling}, commodity={commodity}"
                    ) from e
                except httpx.RequestError as e:
                    raise SourceFetchError(f"data.gov.in request failed: {e}") from e

                if data.get("records"):
                    break  # got results with this spelling

        if data is None:
            raise SourceFetchError("data.gov.in: no response obtained")

        if "records" not in data:
            raise SourceFetchError(
                f"data.gov.in: unexpected response shape — keys={list(data.keys())}"
            )

        raw_records = data.get("records", [])
        log.info("received_records", count=len(raw_records))

        records: List[RawPriceRecord] = []
        for item in raw_records:
            try:
                date_str = (item.get("arrival_date") or "").strip()
                if not date_str:
                    continue

                # Try DD/MM/YYYY first, then YYYY-MM-DD as fallback
                arrival_date = None
                for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                    try:
                        arrival_date = datetime.strptime(date_str, fmt).date()
                        break
                    except ValueError:
                        continue
                if arrival_date is None:
                    log.warning("unparseable_date", date_str=date_str)
                    continue

                modal_raw = item.get("modal_price", "") or ""
                modal_price = float(str(modal_raw).strip()) if str(modal_raw).strip() else 0.0
                if modal_price <= 0:
                    continue

                def safe_price(v) -> float | None:
                    """Return float or None; treat 0, '', None as None."""
                    try:
                        f = float(str(v).strip())
                        return f if f > 0 else None
                    except (TypeError, ValueError):
                        return None

                # provenance ref: market|commodity|date|variety
                variety = (item.get("variety") or "General").strip() or "General"
                market  = (item.get("market")    or "").strip()
                source_ref = f"{market}|{commodity}|{date_str}|{variety}"

                record = RawPriceRecord(
                    market_name=market,
                    commodity_name=(item.get("commodity") or "").strip(),
                    arrival_date=arrival_date,
                    min_price=safe_price(item.get("min_price")),
                    max_price=safe_price(item.get("max_price")),
                    modal_price=modal_price,
                    unit="quintal",   # data.gov.in reports in Rs/Quintal
                    variety=variety,
                    grade=(item.get("grade") or "General").strip() or "General",
                    source=self.source_name,
                    source_ref=source_ref,
                    raw_payload=item,
                )
                records.append(record)

            except Exception as e:
                log.warning("failed_to_parse_record", record=item, error=str(e))
                continue

        return records
