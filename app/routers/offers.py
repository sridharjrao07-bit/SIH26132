"""Offers router — all mutations via ACID RPCs (migration 032).

CREATE  → offer_create  (locks lot, validates qty, marks lot='offered')
DECIDE  → offer_decide  (accept/reject atomically, handles sibling offers + lot status)
LIST    → direct SELECT (no write; RLS enforces visibility)
"""
from app.auth import get_current_user
from app.deps import get_supabase_as_user
from app.errors import json_for_api_error
from app.schemas.marketplace import OfferCreate, OfferUpdate
from app.services.marketplace import with_expiry
from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError
from supabase import Client

router = APIRouter(prefix="/api/v1/offers", tags=["Offers"])


def _call_rpc(supabase: Client, fn: str, params: dict):
    try:
        res = supabase.rpc(fn, params).execute()
        return res.data
    except APIError as exc:
        return json_for_api_error(exc)


@router.post("/")
def create_offer(
    body: OfferCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Create an offer via the offer_create RPC.

    The RPC uses FOR UPDATE on the lot row to prevent concurrent double-offers
    and atomically marks the lot as 'offered' if it was still 'open'.
    """
    params = {
        "p_lot_id":        body.lot_id,
        "p_buyer_id":      body.buyer_id,
        "p_price_per_qtl": body.price_per_qtl,
        "p_quantity_qtl":  body.quantity_qtl,
    }
    data = _call_rpc(supabase, "offer_create", params)
    return with_expiry(data) if isinstance(data, dict) else data


@router.get("/")
def list_offers(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = (
        supabase.table("offers")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return [with_expiry(row) for row in (res.data or [])]


@router.patch("/{offer_id}")
def update_offer(
    offer_id: str,
    body: OfferUpdate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Accept or reject an offer via the offer_decide RPC.

    The RPC handles the full decision atomically:
      - accept: rejects all sibling pending offers, advances lot to 'matched'
      - reject: reverts lot to 'open' if no other pending offers remain

    The expiry check (offer_is_stale) is no longer done here — the RPC's
    FOR UPDATE + status != 'pending' guard is the authoritative check.
    """
    if body.status not in ("accepted", "rejected"):
        raise HTTPException(422, f"status must be accepted or rejected, got {body.status!r}")

    data = _call_rpc(supabase, "offer_decide", {
        "p_offer_id": offer_id,
        "p_decision": body.status,
    })
    return with_expiry(data) if isinstance(data, dict) else data
