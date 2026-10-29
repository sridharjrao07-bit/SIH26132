"""Live retail-price adapter — the right-hand anchor of the consumer rupee.

Source
------
**Ministry of Consumer Affairs, Food & Public Distribution — Department of
Consumer Affairs**, "Essential Commodity: State-wise Daily Wholesale and Retail
Price of <commodity>". Published daily at ``fcainfoweb.nic.in`` and mirrored on
data.gov.in. Separate resources per commodity (Onion, Potato, Tomato, Sugar…);
each carries a ``market`` column whose value is literally ``Retail`` or
``Wholesale``, and a ``unit`` column of ``price in rupees per kilogram`` or
``price in rupees per quintal``.

This is the data that turns "the consumer pays ₹X" from an assumption into a
measurement. Without it the entire consumer-rupee analysis is anchored on a
number somebody typed, which is the weakest link in the argument.

Why the resource id is configurable
-----------------------------------
data.gov.in issues a UUID per resource and re-issues them when a dataset is
re-published, so hard-coding one is a bet that it will not move. The id
therefore comes from ``DCA_RETAIL_RESOURCE_ID`` (per-commodity override via
``DCA_RETAIL_RESOURCE_IDS`` as ``onion=<uuid>,tomato=<uuid>``).

Find the current id by opening the dataset page on data.gov.in and clicking
**API** — the UUID in the shown URL is the resource id. If it is unset, this
adapter raises :class:`SourceFetchError` rather than silently returning no
rows, so the ingestion log records 'failed' instead of a misleading 'success'
with zero records.

Graceful degradation
--------------------
A live feed is a liability at demo time: no network, an expired key, or a
rotated resource id would take the headline number down with it. So the caller
(:func:`load_retail_prices`) falls back to the committed snapshot in
``data/gov_retail_prices.csv`` — which is itself a real export of this same
dataset, dated and cited. The engine is never blocked on the network.

Units
-----
The dataset mixes kg and quintal in the same column. Everything is normalised
to ₹ per quintal (×100 for kg) before it leaves this module, because mixing
units is the single most common way to be wrong by a factor of 100.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime
from typing import Dict, List, Optional

import httpx
import structlog
from pydantic import BaseModel, Field
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger()
RETRY_LOGGER = logging.getLogger("tenacity.retry")

API_BASE = "https://api.data.gov.in/resource"
PAGE_SIZE = 100
MAX_RECORDS = 5000  # safety cap; one commodity/state is far below this

# Fail fast, then fall back to the snapshot. A slow or unreachable data.gov.in
# must never hold up planning: the retail anchor is the right-hand side of every
# consumer-rupee figure, but the engine can run on the committed snapshot while
# the live feed is down. The old 30 s read timeout combined with tenacity's
# backoff meant one unreachable host cost ~65 s per page, and the pagination
# loop below runs several pages -- which reads to a caller as a hang. Both
# bounds are configurable, because a government API on a bad day is slower than
# a private one.
def _env_float(name: str, default: float) -> float:
    """Read a positive float from the environment, falling back on garbage.

    Resolved per call rather than at import so an operator can tune the bound
    without restarting the process, and so a bad value degrades to the safe
    default instead of raising at import time and taking the app down.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 3.0
MAX_RETRY_WAIT_SECONDS = 10.0

# The DCA dataset spells the market column exactly this way.
MARKET_RETAIL = "Retail"
MARKET_WHOLESALE = "Wholesale"

UNIT_KG = "price in rupees per kilogram"
UNIT_QTL = "price in rupees per quintal"


class RetailPriceRecord(BaseModel):
    """One normalised retail observation, always ₹ per quintal."""

    commodity: str
    state: str
    market_area: str = ""  # city/market within the state; "" = state-wide
    price_date: date
    retail_price_per_qtl: float = Field(gt=0)
    wholesale_price_per_qtl: Optional[float] = Field(default=None, gt=0)
    unit: str = "quintal"
    source: str = "data_gov_in"
    source_ref: Optional[str] = None
    raw_payload: Dict = Field(default_factory=dict)


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        # 429 = rate limited, 5xx = their problem. 4xx = ours, fail fast.
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


def _safe_price(v) -> Optional[float]:
    try:
        f = float(str(v).strip())
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _to_per_quintal(price: Optional[float], unit: str) -> Optional[float]:
    """Normalise to ₹/quintal. The dataset mixes kg and quintal rows."""
    if price is None:
        return None
    if unit == UNIT_KG:
        return price * 100.0
    return price


def _parse_date(v) -> Optional[date]:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    s = str(v or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def resource_id_for(commodity: str) -> Optional[str]:
    """Resolve the resource id for a commodity.

    Order: per-commodity override, then the single global id, then nothing.
    """
    overrides = os.getenv("DCA_RETAIL_RESOURCE_IDS", "")
    for pair in overrides.split(","):
        if "=" in pair:
            key, _, value = pair.partition("=")
            if key.strip().lower() == commodity.strip().lower():
                return value.strip() or None
    return os.getenv("DCA_RETAIL_RESOURCE_ID", "").strip() or None


class DcaRetailAdapter:
    """Fetch state-wise daily retail prices from the Consumer Affairs dataset.

    Deliberately not an :class:`~ingestion.base.IngestionSourceAdapter`: that
    interface is shaped around mandi (farm-gate) rows with arrival quantities,
    and retail observations have neither. Forcing it would mean inventing
    arrival_qty and market_name values that do not exist in the source.
    """

    def __init__(
        self,
        api_key: str,
        timeout: Optional[float] = None,
        connect_timeout: Optional[float] = None,
    ):
        timeout = _env_float("DCA_RETAIL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS) \
            if timeout is None else timeout
        connect_timeout = _env_float(
            "DCA_RETAIL_CONNECT_TIMEOUT_SECONDS", DEFAULT_CONNECT_TIMEOUT_SECONDS
        ) if connect_timeout is None else connect_timeout
        self.api_key = api_key
        # Separate connect/read bounds: an unreachable host fails on connect in
        # a couple of seconds, while a reachable-but-slow API is allowed the
        # full read budget. Using one number for both meant a dead host burned
        # the whole read timeout instead of failing fast.
        self.timeout = httpx.Timeout(timeout, connect=connect_timeout)

    @property
    def source_name(self) -> str:
        return "data_gov_in"

    @retry(stop=stop_after_attempt(2),
           wait=wait_exponential(multiplier=1, min=1,
                                 max=_env_float("DCA_RETAIL_MAX_RETRY_WAIT_SECONDS",
                                                MAX_RETRY_WAIT_SECONDS)),
           retry=retry_if_exception(_is_transient), reraise=True,
           before_sleep=before_sleep_log(RETRY_LOGGER, logging.INFO))
    async def _get_json(self, client: httpx.AsyncClient, resource_id: str, params: dict):
        resp = await client.get(f"{API_BASE}/{resource_id}", params=params,
                                timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    async def fetch_retail(
        self,
        commodity: str = "Onion",
        state: str = "Maharashtra",
        since: Optional[date] = None,
        deadline_seconds: Optional[float] = None,
    ) -> List[RetailPriceRecord]:
        """Return retail observations, newest first.

        ``deadline_seconds`` bounds the *whole* paginated fetch, not just one
        request. Per-request timeouts alone are not enough: the loop below walks
        several pages, so three slow pages can still cost a minute. When the
        deadline passes the fetch stops and raises, and the caller falls back to
        the committed snapshot.

        Raises ``SourceFetchError`` on any failure — including a missing
        resource id or missing API key — so the caller can distinguish 'source
        down' from 'source returned nothing'.
        """
        from ingestion.base import SourceFetchError

        resource_id = resource_id_for(commodity)
        if not resource_id:
            raise SourceFetchError(
                "DCA_RETAIL_RESOURCE_ID is not configured; cannot fetch retail "
                "prices. Set it to the data.gov.in resource id for the "
                f"'{commodity}' essential-commodity dataset."
            )
        if not self.api_key:
            raise SourceFetchError("DATA_GOV_IN_API_KEY is not configured")

        if deadline_seconds is None:
            deadline_seconds = _env_float("DCA_RETAIL_DEADLINE_SECONDS", 20.0)
        started = time.monotonic()

        params = {
            "api-key": self.api_key,
            "format": "json",
            "limit": PAGE_SIZE,
            "offset": 0,
            "filters[state]": state,
            "filters[commodity]": commodity,
        }

        rows: List[dict] = []
        async with httpx.AsyncClient() as client:
            while len(rows) < MAX_RECORDS:
                if time.monotonic() - started > deadline_seconds:
                    raise SourceFetchError(
                        f"DCA retail fetch exceeded {deadline_seconds:.0f}s budget "
                        f"after {len(rows)} rows; falling back to the snapshot"
                    )
                params["offset"] = len(rows)
                try:
                    payload = await self._get_json(client, resource_id, params)
                except httpx.HTTPStatusError as exc:
                    raise SourceFetchError(
                        f"DCA retail API returned {exc.response.status_code}"
                    ) from exc
                except httpx.HTTPError as exc:
                    raise SourceFetchError(f"DCA retail API unreachable: {exc}") from exc

                if payload.get("status") != "ok":
                    raise SourceFetchError(
                        f"DCA retail API error: {payload.get('message', 'unknown')}"
                    )
                batch = payload.get("records") or []
                rows.extend(batch)
                total = int(payload.get("total") or 0)
                if not batch or len(rows) >= total:
                    break

        logger.info("dca_retail_fetched", rows=len(rows), commodity=commodity, state=state)
        return self._normalise(rows, commodity, state, since)

    def _normalise(
        self, rows: List[dict], commodity: str, state: str, since: Optional[date]
    ) -> List[RetailPriceRecord]:
        """Pair each date's Retail row with its Wholesale row when present.

        The dataset is long-format: one row per (date, state, market). Keeping
        retail and wholesale side by side is what lets the chain model be
        calibrated against two observed anchors from the same source on the
        same day, rather than one anchor and one assumption.
        """
        # Keyed by (state, date) — NOT date alone.  The dataset is long-format
        # across 35 states, so a date-only key lets one state's wholesale row
        # overwrite another's on the same day and silently attribute Punjab's
        # price to Assam.
        grouped: Dict[tuple, Dict[str, float]] = {}
        raw: Dict[tuple, Dict[str, dict]] = {}
        for row in rows:
            d = _parse_date(row.get("date") or row.get("Date"))
            if d is None:
                continue
            st = str(row.get("state") or row.get("State") or state).strip()
            market = str(row.get("market") or row.get("Market") or "").strip()
            unit = str(row.get("unit") or row.get("Unit") or "").strip()
            price = _to_per_quintal(_safe_price(row.get("price") or row.get("Price")), unit)
            if price is None or market not in (MARKET_RETAIL, MARKET_WHOLESALE):
                continue
            key = (st, d)
            grouped.setdefault(key, {})[market] = price
            raw.setdefault(key, {})[market] = row

        out: List[RetailPriceRecord] = []
        for (st, d), prices in grouped.items():
            retail = prices.get(MARKET_RETAIL)
            if retail is None:
                continue
            if since is not None and d < since:
                continue
            payload = raw.get((st, d), {}).get(MARKET_RETAIL, {})
            out.append(
                RetailPriceRecord(
                    commodity=commodity,
                    state=st,
                    market_area=str(payload.get("market_area") or ""),
                    price_date=d,
                    retail_price_per_qtl=retail,
                    wholesale_price_per_qtl=prices.get(MARKET_WHOLESALE),
                    unit="quintal",
                    source=self.source_name,
                    source_ref=f"dca/{resource_id_for(commodity)}/{st}/{d.isoformat()}",
                    raw_payload=dict(payload),
                )
            )
        out.sort(key=lambda r: r.price_date, reverse=True)
        return out
