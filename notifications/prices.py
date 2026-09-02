"""
notifications/prices.py — Shared price resolution helper.

Provides a single authoritative function for resolving the latest market price
for a given commodity + user, reusing the same nearest-market logic as
alert_checker._check_crossing. This prevents the SMS router and alert checker
from having separate implementations that drift over time.
"""
from datetime import date, timedelta
from typing import Optional, Tuple

import structlog

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
      2. If no location or no nearby market found, fall back to district-wide latest
         (picks the row from any active market in the user's district).
      3. Returns (None, None) if no data found in either path.

    Args:
        supabase:      Supabase client (service-role or user-scoped)
        commodity_id:  UUID of the commodity to query
        user:          user_profiles row dict — must include lat, lng, district keys
        history_days:  Look-back window in days (default 15)

    Returns:
        (modal_price, market_name) or (None, None)
    """
    cutoff = (date.today() - timedelta(days=history_days)).isoformat()
    market_id   = None
    market_name = None

    # ── Step 1: Nearest-market resolution ────────────────────────────────────
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

    # ── Step 2: Fetch the latest price for the resolved market (or district) ─
    query = (
        supabase.table("prices")
        .select("modal_price, markets(name)")
        .eq("commodity_id", commodity_id)
        .gte("arrival_date", cutoff)
        .order("arrival_date", desc=True)
        .limit(1)
    )

    if market_id:
        query = query.eq("market_id", market_id)
    else:
        # District-wide fallback
        district = user.get("district", "Nashik")
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

    price_res = query.execute()
    if not price_res.data:
        return (None, None)

    row = price_res.data[0]
    resolved_market_name = market_name or (
        (row.get("markets") or {}).get("name")
    )
    return (row["modal_price"], resolved_market_name)
