"""Rank verified buyers for a farmer lot (SIH26132 matching)."""
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from supabase import Client
from app.deps import get_supabase, get_supabase_as_user
from app.auth import get_current_user
from app.matching_engine import rank_buyers
from app.marketplace import logistics_next_step
from notifications.sale_window import compute_sale_window, apply_sale_language

router = APIRouter(prefix="/api/v1/lots", tags=["Matching"])


def _load_lot_and_profile(as_user: Client, lot_id: str, user_id: str):
    lot_rows = as_user.table("lots").select("*").eq("id", lot_id).execute().data
    if not lot_rows:
        raise HTTPException(404, "lot not found")
    lot = lot_rows[0]
    profile = (
        as_user.table("user_profiles")
        .select("district, lat, lng, preferred_language")
        .eq("id", user_id)
        .execute()
        .data
        or [{}]
    )[0]
    return lot, profile


def _verified_buyers(public: Client) -> list:
    return public.table("buyers").select("*").eq("verified", True).execute().data or []


@router.get("/{lot_id}/matches")
def match_buyers(
    lot_id: str,
    user_id: str = Depends(get_current_user),
    as_user: Client = Depends(get_supabase_as_user),
    public: Client = Depends(get_supabase),
):
    lot, profile = _load_lot_and_profile(as_user, lot_id, user_id)
    ranked = rank_buyers(lot, profile, _verified_buyers(public))
    best = ranked[0] if ranked else None
    return {
        "lot_id": lot_id,
        "best_buyer": best,
        "matches": ranked[:10],
        "advice": (
            best["summary"]
            if best
            else "No verified local buyer fits this lot yet. Keep the lot open or pool it via an FPO."
        ),
    }


@router.get("/{lot_id}/advice")
def lot_advice(
    lot_id: str,
    lang: Optional[Literal["en", "mr", "hi"]] = Query(None),
    user_id: str = Depends(get_current_user),
    as_user: Client = Depends(get_supabase_as_user),
    public: Client = Depends(get_supabase),
):
    """Sell Now / Hold plus the best local buyer — not a price dump."""
    lot, profile = _load_lot_and_profile(as_user, lot_id, user_id)
    lang = lang or profile.get("preferred_language") or "en"
    window = compute_sale_window(
        public,
        lot["commodity_id"],
        lot.get("market_id"),
        origin_lat=profile.get("lat"),
        origin_lng=profile.get("lng"),
    )
    if window:
        window = apply_sale_language(window, lang)
    ranked = rank_buyers(lot, profile, _verified_buyers(public))
    best = ranked[0] if ranked else None
    action = (window or {}).get("action") or "WAIT"
    reason = (window or {}).get("reason") or "No recent mandi price; wait for today's arrival."
    if action == "SELL_NOW" and best:
        reason = f"{reason} {best['summary']}"
    bookings = (
        as_user.table("logistics_bookings")
        .select("*")
        .eq("lot_id", lot_id)
        .execute()
        .data
        or []
    )
    district = profile.get("district") or (window or {}).get("district") or "Nashik"
    transport_q = (
        public.table("logistics_options")
        .select("*")
        .eq("kind", "transport")
        .eq("is_active", True)
        .eq("district", district)
        .limit(5)
    )
    transport = transport_q.execute().data or []
    next_step = logistics_next_step(action, window, bookings, transport)
    return {
        "lot_id": lot_id,
        "action": action,
        "action_label": (window or {}).get("action_label") or "Wait",
        "reason": reason,
        "next_step": next_step,
        "sale_window": window,
        "best_buyer": best,
        "matches": ranked[:5],
        "bookings": bookings,
        "suggested_transport": transport[:3],
    }
