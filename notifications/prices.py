"""
notifications/prices.py — Shared price resolution helper.

Provides a single authoritative function for resolving the latest market price
for a given commodity + user, reusing the same nearest-market logic and
source-precedence series builder as alert_checker._check_crossing.
"""
from datetime import date, timedelta
from typing import Optional, Tuple

import structlog

from forecasting.engine import build_daily_series, build_district_daily_series

logger = structlog.get_logger()

HISTORY_DAYS = 15
NEAREST_MARKET_RADIUS_KM = 50.0


def latest_price_for_user(
    supabase,
    commodity_id: str,
    user: dict,
    history_days: int = HISTORY_DAYS,
) -> Tuple[Optional[float], Optional[str]]:
    """
    Return (modal_price, market_name) for the most recent day that has data,
    using the same market-resolution logic as alert_checker._check_crossing.

    Resolution order:
      1. If the user has lat/lng, call nearest_market RPC (radius 50 km).
      2. If no location or no nearby market found, fall back to district-wide
         average of source-precedence winners per market.
      3. Returns (None, None) if no data found in either path.
    """
    cutoff = (date.today() - timedelta(days=history_days)).isoformat()
    market_id   = None
    market_name = None

    try:
        lat = user.get("lat")
        lng = user.get("lng")
        if lat is not None and lng is not None:
            rpc_res = supabase.rpc(
                "nearest_market",
                {"lat": float(lat), "lng": float(lng)},
            ).execute()
            if (
                rpc_res.data
                and isinstance(rpc_res.data, list)
                and rpc_res.data[0].get("distance_km", 999) <= NEAREST_MARKET_RADIUS_KM
            ):
                market_id   = rpc_res.data[0]["id"]
                market_name = rpc_res.data[0]["name"]
    except Exception as e:
        logger.warning("nearest_market_rpc_failed", error=str(e))

    query = (
        supabase.table("prices")
        .select("arrival_date, modal_price, source, variety, market_id, markets(name)")
        .eq("commodity_id", commodity_id)
        .gte("arrival_date", cutoff)
        .order("arrival_date", desc=False)
    )

    district = user.get("district", "Nashik")
    if market_id:
        query = query.eq("market_id", market_id)
    else:
        market_rows = (
            supabase.table("markets")
            .select("id")
            .eq("district", district)
            .eq("is_active", True)
            .execute()
        ).data or []

        if not market_rows:
            logger.warning(
                "price_resolution_no_markets",
                commodity_id=commodity_id,
                district=district,
            )
            return (None, None)

        market_ids = [m["id"] for m in market_rows]
        query = query.in_("market_id", market_ids)

    history = (query.execute()).data or []
    if not history:
        return (None, None)

    if market_id:
        series = build_daily_series(history)
        name = market_name or ((history[-1].get("markets") or {}).get("name"))
    else:
        series = build_district_daily_series(history)
        unique_markets = {
            (row.get("markets") or {}).get("name")
            for row in history
            if (row.get("markets") or {}).get("name")
        }
        name = next(iter(unique_markets)) if len(unique_markets) == 1 else f"{district} (avg)"

    if not series:
        return (None, None)
    return (series[-1][1], name)
