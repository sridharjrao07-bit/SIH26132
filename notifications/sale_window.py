"""Sale-window recommendation used by the public API and inbound SMS.

Decision is *not* “here is today’s modal”. It is an active Sell Now / Hold call
from current market supply (arrivals) and nearby storage. Forecast is a
tie-breaker: holding through a glut only makes sense if prices are expected
to recover *and* a godown exists.
"""
from datetime import date, timedelta
from statistics import median
from typing import Optional

from app.matching_engine import haversine_km

NEARBY_STORAGE_KM = 40.0
HIGH_ARRIVAL_QTL = 1000.0
HIGH_DISTRICT_ARRIVAL_QTL = 2500.0


def _f(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _supply_pressure(arrivals_f: Optional[float], recent_arrivals: list, district_arrivals: Optional[float]) -> str:
    if arrivals_f is not None and arrivals_f > HIGH_ARRIVAL_QTL:
        return "high"
    if district_arrivals is not None and district_arrivals > HIGH_DISTRICT_ARRIVAL_QTL:
        return "high"
    sample = [a for a in recent_arrivals if a is not None]
    if arrivals_f is not None and len(sample) >= 3:
        mid = median(sample)
        if mid and arrivals_f > 1.3 * mid:
            return "high"
        if arrivals_f < 0.6 * mid:
            return "low"
    if arrivals_f is not None and arrivals_f < 200:
        return "low"
    if arrivals_f is None:
        return "unknown"
    return "normal"


def compute_sale_window(
    supabase,
    commodity_id: str,
    market_id: Optional[str] = None,
    origin_lat=None,
    origin_lng=None,
) -> Optional[dict]:
    """
    Return a sell / hold / wait recommendation from supply + nearby storage.
    Returns None when there is no recent price (caller decides 404 vs silent).
    """
    today = date.today()
    cutoff = (today - timedelta(days=15)).isoformat()

    price_q = (
        supabase.table("prices")
        .select("modal_price, arrival_qty, arrival_date, market_id, markets(name, district, lat, lng)")
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
    nested_market = latest.get("markets") or {}

    market_lat = origin_lat if origin_lat is not None else nested_market.get("lat")
    market_lng = origin_lng if origin_lng is not None else nested_market.get("lng")
    district = nested_market.get("district") or "Nashik"
    if market_id:
        mrows = (
            supabase.table("markets")
            .select("lat,lng,district,name")
            .eq("id", market_id)
            .execute()
            .data
            or []
        )
        if mrows:
            district = mrows[0].get("district") or district
            if origin_lat is None:
                market_lat = mrows[0].get("lat")
                market_lng = mrows[0].get("lng")

    latest_by_market = {}
    for row in prices:
        mid = row.get("market_id")
        if mid and mid not in latest_by_market:
            latest_by_market[mid] = row
    district_arrivals = 0.0
    have_arrivals = False
    for row in latest_by_market.values():
        aq = _f(row.get("arrival_qty"))
        if aq is not None:
            district_arrivals += aq
            have_arrivals = True
    district_arrivals_f = district_arrivals if have_arrivals else None
    recent_arrivals = [_f(r.get("arrival_qty")) for r in prices]
    supply = _supply_pressure(arrivals_f, recent_arrivals, district_arrivals_f)

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
    forecast_up = day1 is not None and day1 >= latest_price * 1.05 and trend != "down"
    forecast_down = day1 is not None and (day1 <= latest_price * 0.97 or trend == "down")

    nearby = []
    others = (
        supabase.table("prices")
        .select("modal_price, arrival_qty, market_id, markets(name)")
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
        if mid in seen or (market_id and mid == market_id):
            continue
        seen.add(mid)
        nearby.append({
            "market": (row.get("markets") or {}).get("name"),
            "modal_price": row["modal_price"],
            "arrival_qty": row.get("arrival_qty"),
        })
        if len(nearby) >= 4:
            break

    storage_rows = (
        supabase.table("logistics_options")
        .select("id, name, capacity_qtl, rate_per_qtl, district, lat, lng")
        .eq("kind", "storage")
        .eq("is_active", True)
        .limit(20)
        .execute()
        .data
        or []
    )
    storage = []
    for s in storage_rows:
        dist = haversine_km(market_lat, market_lng, s.get("lat"), s.get("lng"))
        same_district = (s.get("district") or "") == district
        if dist is not None:
            if dist > NEARBY_STORAGE_KM and not same_district:
                continue
        elif not same_district:
            continue
        item = dict(s)
        item["distance_km"] = dist
        storage.append(item)
    storage.sort(key=lambda s: s["distance_km"] if s.get("distance_km") is not None else 10**9)
    storage = storage[:5]
    storage_available = bool(storage)

    # Supply + nearby storage first; forecast only as tie-breaker.
    if supply == "high" and not storage_available:
        recommendation, reason_code = "sell", "sell_no_storage"
        reason = (
            f"Sell now: arrivals are high ({arrivals_f:.0f} qtl) and no nearby godown "
            "is listed. Holding at the farm gate risks a further fall."
            if arrivals_f is not None
            else "Sell now: market supply is high and no nearby storage is listed."
        )
    elif supply == "high" and storage_available and forecast_up:
        recommendation, reason_code = "hold", "hold"
        names = ", ".join(s.get("name") or "godown" for s in storage[:2])
        reason = (
            f"Hold: arrivals are high but {names} is nearby and the forecast "
            f"₹{day1:.0f} is above today's ₹{latest_price:.0f}."
        )
    elif supply == "high":
        recommendation, reason_code = "sell", "sell_arrivals"
        reason = (
            f"Sell now: arrivals are high ({arrivals_f:.0f} qtl) which typically "
            "pressures mandi prices."
            if arrivals_f is not None
            else "Sell now: current market supply is high."
        )
    elif storage_available and forecast_up:
        recommendation, reason_code = "hold", "hold"
        names = ", ".join(s.get("name") or "godown" for s in storage[:2])
        reason = (
            f"Hold: forecast ₹{day1:.0f} is above today's ₹{latest_price:.0f} "
            f"and nearby storage is listed ({names})."
        )
    elif forecast_down:
        recommendation, reason_code = "sell", "sell_forecast"
        reason = (
            f"Sell now: forecast ₹{day1:.0f} is at or below today's ₹{latest_price:.0f}; "
            "waiting reduces realisation."
        )
    elif not storage_available and forecast_up:
        recommendation, reason_code = "sell", "sell_no_storage"
        reason = (
            "Sell now: forecast is higher but no nearby storage is listed; "
            "do not hold at the farm gate."
        )
    else:
        recommendation, reason_code = "wait", "wait"
        reason = "Wait: supply is not elevated and the forecast is near today's price."

    action = {"sell": "SELL_NOW", "hold": "HOLD", "wait": "WAIT"}[recommendation]
    return {
        "commodity_id": commodity_id,
        "market_id": market_id,
        "recommendation": recommendation,
        "action": action,
        "action_label": {"sell": "Sell Now", "hold": "Hold", "wait": "Wait"}[recommendation],
        "reason": reason,
        "reason_code": reason_code,
        "latest_price": latest_price,
        "forecast_day1": day1,
        "forecast_trend": trend,
        "arrivals_qty": arrivals_f,
        "district_arrivals_qty": district_arrivals_f,
        "supply_pressure": supply,
        "nearby": nearby,
        "market_name": nested_market.get("name"),
        "storage": storage,
        "storage_available": storage_available,
        "district": district,
        "lang": "en",
    }


def apply_sale_language(window: dict, lang: str) -> dict:
    """Localise the farmer-facing reason and action label."""
    if not window:
        return window
    lang = (lang or "en").lower()
    if lang not in ("en", "mr", "hi"):
        lang = "en"
    out = dict(window)
    out["lang"] = lang
    rec = out.get("recommendation") or "wait"
    out["action"] = {"sell": "SELL_NOW", "hold": "HOLD", "wait": "WAIT"}.get(rec, "WAIT")
    labels = {
        "en": {"sell": "Sell Now", "hold": "Hold", "wait": "Wait"},
        "mr": {"sell": "आज विका", "hold": "थोडे थांबा", "wait": "थांबा"},
        "hi": {"sell": "आज बेचें", "hold": "थोड़ा रुकें", "wait": "रुकें"},
    }
    out["action_label"] = labels.get(lang, labels["en"]).get(rec, rec)
    if lang == "en":
        return out
    code = out.get("reason_code") or rec
    price = out.get("latest_price")
    day1 = out.get("forecast_day1")
    arrivals = out.get("arrivals_qty")
    p = int(round(float(price))) if price is not None else 0
    d1 = int(round(float(day1))) if day1 is not None else None
    aq = int(round(float(arrivals))) if arrivals is not None else None
    storage = out.get("storage") or []
    godown = (storage[0].get("name") if storage else None) or "गोदाम"
    if lang == "mr":
        reasons = {
            "wait": "आवक सामान्य; घाई नको.",
            "hold": (
                f"अंदाज ₹{d1} आज ₹{p} पेक्षा जास्त. जवळचे गोदाम: {godown}. थोडे थांबा."
                if d1 is not None else f"जवळचे गोदाम: {godown}. थोडे थांबा."
            ),
            "sell_forecast": (
                f"अंदाज ₹{d1} आज ₹{p} पेक्षा कमी; आज विका."
                if d1 is not None else "आज विका."
            ),
            "sell_arrivals": (
                f"आवक जास्त ({aq} क्विंटल); आज विका." if aq is not None else "आज विका."
            ),
            "sell_no_storage": "आवक/अंदाज जास्त पण जवळ गोदाम नाही; आज विका.",
        }
        out["reason"] = reasons.get(code) or reasons.get(rec) or reasons["wait"]
        return out
    reasons = {
        "wait": "आवक सामान्य; जल्दबाजी न करें.",
        "hold": (
            f"अनुमान ₹{d1} आज ₹{p} से ऊपर. नज़दीकी गोदाम: {godown}. थोड़ा रुकें."
            if d1 is not None else f"नज़दीकी गोदाम: {godown}. थोड़ा रुकें."
        ),
        "sell_forecast": (
            f"अनुमान ₹{d1} आज ₹{p} से कम; आज बेचें."
            if d1 is not None else "आज बेचें."
        ),
        "sell_arrivals": (
            f"आवक ज्यादा ({aq} क्विंटल); आज बेचें." if aq is not None else "आज बेचें."
        ),
        "sell_no_storage": "आवक/अनुमान ऊँचा है पर नज़दीकी गोदाम नहीं; आज बेचें.",
    }
    out["reason"] = reasons.get(code) or reasons.get(rec) or reasons["wait"]
    return out


def format_sale_sms(lang: str, name: str, price, market: Optional[str], recommendation: str) -> str:
    """Compact UCS-2-safe sale-window SMS (target ≤70 chars for Devanagari)."""
    rec = (recommendation or "wait").lower()
    if rec == "sell_now":
        rec = "sell"
    p = int(round(float(price))) if price is not None else 0
    mkt = (market or "").split()[0] if market else ""
    if lang == "mr":
        verb = {"sell": "आज विका", "hold": "थोडे थांबा"}.get(rec, "थांबा")
        return f"KB: {name} ₹{p}. {verb}."
    if lang == "hi":
        verb = {"sell": "आज बेचें", "hold": "थोड़ा रुकें"}.get(rec, "रुकें")
        return f"KB: {name} ₹{p}. {verb}."
    verb = {"sell": "SELL NOW", "hold": "HOLD", "wait": "WAIT"}.get(rec, "WAIT")
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
