"""Rank verified buyers for a farmer lot (SIH26132 matching)."""
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.deps import get_supabase, get_supabase_as_user
from app.auth import get_current_user

router = APIRouter(prefix="/api/v1/lots", tags=["Matching"])


def _haversine_km(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    from math import radians, sin, cos, sqrt, atan2
    r = 6371.0
    dlat = radians(float(lat2) - float(lat1))
    dlng = radians(float(lng2) - float(lng1))
    a = sin(dlat / 2) ** 2 + cos(radians(float(lat1))) * cos(radians(float(lat2))) * sin(dlng / 2) ** 2
    return round(2 * r * atan2(sqrt(a), sqrt(1 - a)), 1)


@router.get("/{lot_id}/matches")
def match_buyers(
    lot_id: str,
    user_id: str = Depends(get_current_user),
    as_user: Client = Depends(get_supabase_as_user),
    public: Client = Depends(get_supabase),
):
    lot_rows = as_user.table("lots").select("*").eq("id", lot_id).execute().data
    if not lot_rows:
        raise HTTPException(404, "lot not found")
    lot = lot_rows[0]

    profile = (
        as_user.table("user_profiles")
        .select("district, lat, lng")
        .eq("id", user_id)
        .execute()
        .data
        or [{}]
    )[0]
    district = profile.get("district") or "Nashik"

    buyers = (
        public.table("buyers")
        .select("*")
        .eq("verified", True)
        .execute()
        .data
        or []
    )

    ranked = []
    for b in buyers:
        if b.get("commodity_id") and b["commodity_id"] != lot["commodity_id"]:
            continue
        score = 0.0
        reasons = []
        if b.get("verified"):
            score += 20
            reasons.append("verified_buyer")
        if b.get("district") and b["district"] == district:
            score += 30
            reasons.append("same_district")
        asking = lot.get("asking_price")
        max_p = b.get("max_price")
        if asking is not None and max_p is not None:
            if float(max_p) >= float(asking):
                score += 25
                reasons.append("price_covers_ask")
            else:
                score -= 10
                reasons.append("bid_below_ask")
        demand = b.get("demand_qty_qtl")
        qty = lot.get("quantity_qtl")
        if demand is not None and qty is not None and float(demand) >= float(qty):
            score += 15
            reasons.append("volume_fit")
        rel = b.get("payment_reliability")
        if rel == "high":
            score += 10
            reasons.append("reliable_payer")
        elif rel == "low":
            score -= 5
        dist = _haversine_km(profile.get("lat"), profile.get("lng"), b.get("lat"), b.get("lng"))
        if dist is not None:
            if dist <= 25:
                score += 10
                reasons.append("nearby_25km")
            elif dist <= 80:
                score += 5
                reasons.append("within_80km")
        ranked.append({
            "buyer_id": b["id"],
            "buyer_name": b["name"],
            "buyer_type": b["type"],
            "verified": b.get("verified", False),
            "district": b.get("district"),
            "score": round(score, 1),
            "reasons": reasons,
            "max_price": b.get("max_price"),
            "demand_qty_qtl": b.get("demand_qty_qtl"),
            "payment_reliability": b.get("payment_reliability"),
            "quality_requirements": b.get("quality_requirements"),
            "distance_km": dist,
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return {"lot_id": lot_id, "matches": ranked[:10]}
