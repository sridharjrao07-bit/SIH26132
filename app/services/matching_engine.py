"""Local-first buyer ranking for a farmer lot.

The score is not “highest bid wins”. SIH26132 is about *linkages*: a verified
buyer close enough to take the lot, who can pay and who actually wants the
volume/grade. Distant high bids still rank, but locality dominates.
"""
from math import atan2, cos, radians, sin, sqrt
from typing import Optional


def haversine_km(lat1, lng1, lat2, lng2) -> Optional[float]:
    if None in (lat1, lng1, lat2, lng2):
        return None
    r = 6371.0
    dlat = radians(float(lat2) - float(lat1))
    dlng = radians(float(lng2) - float(lng1))
    a = sin(dlat / 2) ** 2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(dlng / 2) ** 2
    return round(2 * r * atan2(sqrt(a), sqrt(1 - a)), 1)


def score_buyer(lot: dict, profile: dict, buyer: dict) -> Optional[dict]:
    """Return a ranked match row, or None if the buyer is not a candidate."""
    if not buyer.get("verified"):
        return None
    if buyer.get("commodity_id") and buyer["commodity_id"] != lot.get("commodity_id"):
        return None

    district = (profile or {}).get("district") or "Nashik"
    reasons = []
    score = 0.0

    # Locality — the primary signal ("best *local* buyer")
    if buyer.get("district") and buyer["district"] == district:
        score += 25
        reasons.append("same_district")

    dist = haversine_km(
        (profile or {}).get("lat"),
        (profile or {}).get("lng"),
        buyer.get("lat"),
        buyer.get("lng"),
    )
    if dist is not None:
        if dist <= 100:
            score += round(35.0 * (1.0 - dist / 100.0), 1)
        if dist <= 25:
            reasons.append("nearby_25km")
        elif dist <= 80:
            reasons.append("within_80km")
        elif dist > 100:
            score -= 15
            reasons.append("far_buyer")

    if buyer.get("verified"):
        score += 15
        reasons.append("verified_buyer")

    asking = lot.get("asking_price")
    max_p = buyer.get("max_price")
    if asking is not None and max_p is not None:
        if float(max_p) >= float(asking):
            score += 20
            reasons.append("price_covers_ask")
        else:
            score -= 15
            reasons.append("bid_below_ask")

    demand = buyer.get("demand_qty_qtl")
    qty = lot.get("quantity_qtl")
    if demand is not None and qty is not None and float(demand) >= float(qty):
        score += 15
        reasons.append("volume_fit")

    rel = buyer.get("payment_reliability")
    if rel == "high":
        score += 10
        reasons.append("reliable_payer")
    elif rel == "low":
        score -= 15
        reasons.append("unreliable_payer")

    grade = (lot.get("grade") or "").lower()
    req = (buyer.get("quality_requirements") or "").lower()
    if grade and req and grade in req:
        score += 10
        reasons.append("grade_match")

    return {
        "buyer_id": buyer["id"],
        "buyer_name": buyer.get("name"),
        "buyer_type": buyer.get("type"),
        "verified": True,
        "district": buyer.get("district"),
        "score": round(score, 1),
        "reasons": reasons,
        "max_price": buyer.get("max_price"),
        "demand_qty_qtl": buyer.get("demand_qty_qtl"),
        "payment_reliability": buyer.get("payment_reliability"),
        "quality_requirements": buyer.get("quality_requirements"),
        "distance_km": dist,
        "summary": _summarize(buyer.get("name"), dist, reasons),
    }


def _summarize(name: str, dist: Optional[float], reasons: list) -> str:
    bits = []
    if dist is not None:
        bits.append(f"{dist} km")
    if "same_district" in reasons:
        bits.append("same district")
    if "price_covers_ask" in reasons:
        bits.append("covers your ask")
    elif "bid_below_ask" in reasons:
        bits.append("bid below ask")
    if "reliable_payer" in reasons:
        bits.append("reliable payer")
    if "volume_fit" in reasons:
        bits.append("wants your volume")
    where = ", ".join(bits) if bits else "verified buyer"
    return f"Best local buyer: {name} ({where})." if name else where


def rank_buyers(lot: dict, profile: dict, buyers: list, limit: int = 10) -> list:
    ranked = []
    for b in buyers or []:
        row = score_buyer(lot, profile, b)
        if row is not None:
            ranked.append(row)
    ranked.sort(key=lambda x: (x["score"], -(x["distance_km"] or 10**9)), reverse=True)
    return ranked[:limit]


_LOT_PUBLIC = (
    "id", "commodity_id", "market_id", "quantity_qtl", "grade",
    "asking_price", "status", "harvest_date", "fpo_id",
)


def score_lot_for_buyer(buyer: dict, lot: dict, market: Optional[dict] = None) -> Optional[dict]:
    """Reverse match: does this open lot fit a verified buyer's demand?"""
    if lot.get("status") not in ("open", "offered"):
        return None
    if buyer.get("commodity_id") and lot.get("commodity_id") != buyer["commodity_id"]:
        return None

    reasons = []
    score = 0.0
    market = market or {}
    if buyer.get("district") and market.get("district") == buyer.get("district"):
        score += 25
        reasons.append("same_district")

    asking = lot.get("asking_price")
    max_p = buyer.get("max_price")
    if asking is not None and max_p is not None:
        if float(max_p) >= float(asking):
            score += 20
            reasons.append("price_covers_ask")
        else:
            score -= 15
            reasons.append("bid_below_ask")

    demand = buyer.get("demand_qty_qtl")
    qty = lot.get("quantity_qtl")
    if demand is not None and qty is not None and float(demand) >= float(qty):
        score += 15
        reasons.append("volume_fit")
    elif demand is not None and qty is not None:
        reasons.append("over_demand")

    grade = (lot.get("grade") or "").lower()
    req = (buyer.get("quality_requirements") or "").lower()
    if grade and req and grade in req:
        score += 10
        reasons.append("grade_match")

    row = {k: lot.get(k) for k in _LOT_PUBLIC}
    row.update({
        "score": round(score, 1),
        "reasons": reasons,
        "market_name": market.get("name"),
        "market_district": market.get("district"),
    })
    return row


def rank_lots_for_buyer(buyer: dict, lots: list, markets_by_id: Optional[dict] = None, limit: int = 20) -> list:
    markets_by_id = markets_by_id or {}
    ranked = []
    for lot in lots or []:
        market = markets_by_id.get(lot.get("market_id")) or {}
        row = score_lot_for_buyer(buyer, lot, market)
        if row is not None:
            ranked.append(row)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:limit]
