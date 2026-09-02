import httpx
import logging
import structlog
from typing import List
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception, before_sleep_log

from .base import IngestionSourceAdapter, RawPriceRecord, SourceFetchError

logger = structlog.get_logger()
RETRY_LOGGER = logging.getLogger("tenacity.retry")

PAGE_SIZE = 100


def _safe_price(v) -> "float | None":
    """Return float or None; treat 0, '', None as None (0-price is invalid data)."""
    try:
        f = float(str(v).strip())
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None

def _is_transient(exc: BaseException) -> bool:
    # network errors, rate limits, 5xx → retry; 4xx (bad key/bad params) → fail fast
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


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

    Pagination: reads total from the first response and fetches subsequent
    pages with &offset= until all records are collected.
    """

    BASE_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
    # Fallback district spellings keyed by the requested district
    DISTRICT_SPELLINGS = {
        "Nashik": ["Nasik"],
        "Nasik": ["Nashik"],
    }

    def __init__(self, api_key: str):
        self.api_key = api_key

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=5, min=5, max=45),
           retry=retry_if_exception(_is_transient), reraise=True,
           before_sleep=before_sleep_log(RETRY_LOGGER, logging.INFO))
    async def _get_json(self, client: httpx.AsyncClient, params: dict):
        resp = await client.get(self.BASE_URL, params=params, timeout=15.0)
        resp.raise_for_status()
        return resp.json()

    @property
    def source_name(self) -> str:
        # Must match commodity_alias.source = 'data_gov_in' (no dot)
        return "data_gov_in"

    async def fetch_prices(
        self, district: str, commodity: str, state: str = "Maharashtra"
    ) -> List[RawPriceRecord]:
        """
        Fetches all pages of price records for a given district/commodity.
        Raises SourceFetchError on HTTP failure or unexpected response shape.
        """
        log = logger.bind(source=self.source_name, district=district, commodity=commodity)

        # ── 1. Try district spellings until we get records ────────────────────
        spellings = [district] + [s for s in self.DISTRICT_SPELLINGS if s != district]
        first_data = None
        used_spelling = district

        async with httpx.AsyncClient(timeout=10.0) as client:
            for spelling in spellings:
                params = {
                    "api-key":            self.api_key,
                    "format":             "json",
                    "filters[state]":     state,
                    "filters[district]":  spelling,
                    "filters[commodity]": commodity,
                    "limit":              PAGE_SIZE,
                    "offset":             0,
                }
                log.info("fetching_page_1", district_spelling=spelling)
                try:
                    first_data = await self._get_json(client, params)
                except httpx.HTTPStatusError as e:
                    raise SourceFetchError(
                        f"data.gov.in HTTP {e.response.status_code} for "
                        f"district={spelling}, commodity={commodity}"
                    ) from e
                except httpx.RequestError as e:
                    raise SourceFetchError(f"data.gov.in request failed: {e}") from e

                if first_data.get("records"):
                    used_spelling = spelling
                    break  # got results with this spelling

        if first_data is None:
            raise SourceFetchError("data.gov.in: no response obtained")

        if "records" not in first_data:
            raise SourceFetchError(
                f"data.gov.in: unexpected response shape — keys={list(first_data.keys())}"
            )

        # ── 2. Pagination ─────────────────────────────────────────────────────
        # API returns {"total": N, "count": N, "records": [...]}.
        # Collect subsequent pages until offset >= total.
        all_raw: list = list(first_data.get("records", []))
        total = int(first_data.get("total", len(all_raw)))
        offset = len(all_raw)

        async with httpx.AsyncClient(timeout=10.0) as page_client:
            while offset < total:
                page_params = {
                    "api-key":            self.api_key,
                    "format":             "json",
                    "filters[state]":     state,
                    "filters[district]":  used_spelling,
                    "filters[commodity]": commodity,
                    "limit":              PAGE_SIZE,
                    "offset":             offset,
                }
                try:
                    page_data = await self._get_json(page_client, page_params)
                    page_records = page_data.get("records", [])
                    if not page_records:
                        break  # API said there's more but sent nothing — stop
                    all_raw.extend(page_records)
                    offset += len(page_records)
                except Exception as e:
                    log.warning("pagination_page_failed", offset=offset, error=str(e))
                    break  # partial data is better than none

        log.info("received_records", count=len(all_raw), total=total)

        # ── 3. Parse records ──────────────────────────────────────────────────
        records: List[RawPriceRecord] = []
        for item in all_raw:
            try:
                date_str = (item.get("arrival_date") or "").strip()
                if not date_str:
                    continue

                # Try DD/MM/YYYY first, then ISO and dash variants
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
                modal_str = str(modal_raw).strip()
                modal_price = float(modal_str) if modal_str else 0.0
                if modal_price <= 0:
                    continue

                variety    = (item.get("variety") or "General").strip() or "General"
                market     = (item.get("market")  or "").strip()
                source_ref = f"{market}|{commodity}|{date_str}|{variety}"

                arrival_qty = None
                for qty_key in ("arrivals", "arrival", "arrival_quantity", "qty"):
                    raw_qty = item.get(qty_key)
                    if raw_qty in (None, ""):
                        continue
                    try:
                        q = float(str(raw_qty).strip())
                    except (TypeError, ValueError):
                        continue
                    if q >= 0:
                        arrival_qty = q
                        break

                record = RawPriceRecord(
                    market_name=market,
                    commodity_name=(item.get("commodity") or "").strip(),
                    arrival_date=arrival_date,
                    min_price=_safe_price(item.get("min_price")),
                    max_price=_safe_price(item.get("max_price")),
                    modal_price=modal_price,
                    unit="quintal",   # data.gov.in reports in Rs/Quintal
                    arrival_qty=arrival_qty,
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
