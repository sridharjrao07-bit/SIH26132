"""Sale-window recommendation used by the public API and inbound SMS."""
from datetime import date, timedelta
from typing import Optional


def compute_sale_window(supabase, commodity_id: str, market_id: Optional[str] = None) -> Optional[dict]:
    """
    Return a sell / hold / wait recommendation from latest price, forecast, and arrivals.
    Returns None when there is no recent price (caller decides 404 vs silent).
    """
    today = date.today()
    cutoff = (today - timedelta(days=15)).isoformat()

    price_q = (
        supabase.table("prices")
        .select("modal_price, arrival_qty, arrival_date, market_id, markets(name)")
        .eq("commodity_id", commodity_id)
        .gte("arrival_date", cutoff)
        .order("arrival_date", desc=True)
        .limit(30)
    )
    if market_id:
        price_q = price_q.eq("market_id", market_id)
    prices = price_q.execute().data or []
    if not prices:
        return None

    latest = prices[0]
    latest_price = float(latest["modal_price"])
    arrivals = latest.get("arrival_qty")
    arrivals_f = float(arrivals) if arrivals is not None else None

    fc_q = (
        supabase.table("forecasts")
        .select("predicted_price, forecast_date, status")
        .eq("commodity_id", commodity_id)
        .eq("status", "ok")
        .gte("forecast_date", today.isoformat())
        .order("forecast_date")
        .limit(7)
    )
    if market_id:
        fc_q = fc_q.eq("market_id", market_id)
    forecasts = fc_q.execute().data or []
    day1 = (
        float(forecasts[0]["predicted_price"])
        if forecasts and forecasts[0].get("predicted_price") is not None
        else None
    )
    last_fc = (
        float(forecasts[-1]["predicted_price"])
        if forecasts and forecasts[-1].get("predicted_price") is not None
        else None
    )

    trend = None
    if day1 is not None and last_fc is not None:
        if last_fc > day1 * 1.03:
            trend = "up"
        elif last_fc < day1 * 0.97:
            trend = "down"
        else:
            trend = "flat"

    nearby = []
    if market_id:
        others = (
            supabase.table("prices")
            .select("modal_price, market_id, markets(name)")
            .eq("commodity_id", commodity_id)
            .gte("arrival_date", cutoff)
            .order("arrival_date", desc=True)
            .limit(20)
            .execute()
            .data
            or []
        )
        seen = set()
        for row in others:
            mid = row["market_id"]
            if mid in seen or mid == market_id:
                continue
            seen.add(mid)
            nearby.append({
                "market": (row.get("markets") or {}).get("name"),
                "modal_price": row["modal_price"],
            })
            if len(nearby) >= 4:
                break

    recommendation = "wait"
    reason = "Price is near the forecast; no strong signal to rush or hold."
    if day1 is not None:
        if day1 >= latest_price * 1.05 and trend != "down":
            recommendation = "hold"
            reason = (
                f"Forecast ₹{day1:.0f} is above today's ₹{latest_price:.0f}; "
                "a short hold may improve realisation if storage is available."
            )
        elif day1 <= latest_price * 0.97 or trend == "down":
            recommendation = "sell"
            reason = (
                f"Forecast ₹{day1:.0f} is at or below today's ₹{latest_price:.0f}; "
                "selling now reduces the chance of a further fall."
            )
    if arrivals_f is not None and arrivals_f > 1000 and recommendation != "hold":
        recommendation = "sell"
        reason = (
            f"Arrivals are high ({arrivals_f:.0f} qtl) which typically pressures mandi prices. "
            + reason
        )

    return {
        "commodity_id": commodity_id,
        "market_id": market_id,
        "recommendation": recommendation,
        "reason": reason,
        "latest_price": latest_price,
        "forecast_day1": day1,
        "forecast_trend": trend,
        "arrivals_qty": arrivals_f,
        "nearby": nearby,
        "market_name": (latest.get("markets") or {}).get("name"),
    }


def format_sale_sms(lang: str, name: str, price, market: Optional[str], recommendation: str) -> str:
    """Compact UCS-2-safe sale-window SMS (target ≤70 chars for Devanagari)."""
    rec = (recommendation or "wait").lower()
    p = int(round(float(price))) if price is not None else 0
    mkt = (market or "").split()[0] if market else ""
    if lang == "mr":
        verb = {"sell": "आज विका", "hold": "थोडे थांबा"}.get(rec, "थांबा")
        return f"KB: {name} ₹{p}. {verb}."
    if lang == "hi":
        verb = {"sell": "आज बेचें", "hold": "थोड़ा रुकें"}.get(rec, "रुकें")
        return f"KB: {name} ₹{p}. {verb}."
    verb = {"sell": "SELL now", "hold": "HOLD", "wait": "WAIT"}.get(rec, "WAIT")
    if mkt:
        return f"KB: {name} ₹{p} {mkt}. {verb}."
    return f"KB: {name} ₹{p}. {verb}."


def format_alert_sms(lang: str, comm_name: str, price, threshold, scope: str = "") -> str:
    """Vernacular alert copy. MR/HI kept ≤70 Devanagari chars for 1-segment UCS-2."""
    p = int(round(float(price))) if price is not None else 0
    t = int(round(float(threshold))) if threshold is not None else 0
    name = comm_name or "crop"
    if lang == "mr":
        return f"KB: {name} ₹{p}. मर्यादा ₹{t} ओलांडली."
    if lang == "hi":
        return f"KB: {name} ₹{p}. सीमा ₹{t} पार."
    scope_bit = f" ({scope})" if scope else ""
    return f"KrishiBazaar Alert: {name} is ₹{p}{scope_bit}. Threshold ₹{t}."
