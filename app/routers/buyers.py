"""Buyers router — registration via RPC; reads via anon client.

buyers.verified can only be set true via the admin verify endpoint which
calls the buyer_verify RPC (service_role path).  The self-registration
endpoint creates a buyer with verified=False and calls buyer_register RPC.

Since migration 031 revoked direct INSERT on buyers from authenticated,
all writes must go through security-definer RPCs.
"""
from typing import List, Optional

from app.auth import get_current_user, require_role
from app.deps import get_supabase, get_supabase_as_user
from app.errors import json_for_api_error
from app.schemas.marketplace import BuyerRegisterRequest, BuyerResponse, MyBuyerProfile
from app.services.matching_engine import rank_lots_for_buyer
from fastapi import APIRouter, Depends, HTTPException, Query
from postgrest.exceptions import APIError
from supabase import Client

router = APIRouter(prefix="/api/v1/buyers", tags=["Buyers"])


def _call_rpc(supabase: Client, fn: str, params: dict):
    try:
        res = supabase.rpc(fn, params).execute()
        return res.data
    except APIError as exc:
        return json_for_api_error(exc)


@router.post("/register", status_code=201)
def register_buyer(
    req: BuyerRegisterRequest,
    uid: str = Depends(get_current_user),
    user_client: Client = Depends(get_supabase_as_user),
):
    """Self-service buyer registration via buyer_register RPC.

    The RPC (migration 032+) sets owner_user_id = auth.uid() server-side and
    enforces the one-profile-per-user constraint.  verified is always False
    at registration; admin must call /buyers/{id}/verify to flip it.
    """
    params = {
        "p_name": req.name,
        "p_type": req.type,
        "p_phone": req.phone,
        "p_district": req.district,
        "p_commodity_id": req.commodity_id,
        "p_demand_qty_qtl": req.demand_qty_qtl,
        "p_max_price": req.max_price,
        "p_quality_requirements": req.quality_requirements,
        "p_payment_reliability": req.payment_reliability,
        "p_lat": req.lat,
        "p_lng": req.lng,
    }
    return _call_rpc(user_client, "buyer_register", params)


@router.get("/", response_model=List[BuyerResponse])
def list_buyers(
    district: Optional[str] = Query(None),
    commodity_id: Optional[str] = Query(None),
    verified_only: bool = Query(True),
    supabase: Client = Depends(get_supabase),
):
    query = supabase.table("buyers").select("*")
    if verified_only:
        query = query.eq("verified", True)
    if district:
        query = query.eq("district", district)
    if commodity_id:
        query = query.eq("commodity_id", commodity_id)
    res = query.order("name").limit(100).execute()
    return res.data or []


@router.patch("/{buyer_id}/verify", dependencies=[Depends(require_role("admin"))])
def verify_buyer(
    buyer_id: str,
    user_client: Client = Depends(get_supabase_as_user),
):
    """Admin-only: verify a buyer profile via buyer_verify RPC.

    The RPC (service-role path) sets buyers.verified = true.
    The trg_guard_buyer_self_verify trigger (migration 031) prevents this
    from happening via direct UPDATE even with service-role if not via RPC.
    """
    return _call_rpc(user_client, "buyer_verify", {"p_buyer_id": buyer_id})


@router.get("/me", response_model=MyBuyerProfile)
def my_buyer_profile(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """The caller's own buyer profile (ticket G12).

    A buyer who clears their browser loses the id returned by
    ``POST /buyers/register``; this endpoint lets the PWA recover the profile
    from the JWT alone.  Scoping is by ``owner_user_id`` (migration 014), which
    the ``buyer_register`` RPC sets server-side — the client never supplies it.

    404 (not 403) when the caller has no buyer profile, matching the contract
    rule that owner-only resources render as "not found".
    """
    res = (
        supabase.table("buyers")
        .select("*")
        .eq("owner_user_id", user_id)
        .order("submitted_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(404, "no buyer profile for this user")
    return rows[0]


@router.get("/{buyer_id}/supply")
def buyer_supply(
    buyer_id: str,
    supabase: Client = Depends(get_supabase_as_user),
):
    """Open lots that fit this verified buyer's demand (buyer-side aggregation)."""
    rows = (
        supabase.table("buyers")
        .select("*")
        .eq("id", buyer_id)
        .eq("verified", True)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "buyer not found")
    buyer = rows[0]

    rpc_params: dict = {}
    if buyer.get("commodity_id"):
        rpc_params["p_commodity_id"] = str(buyer["commodity_id"])

    rpc_result = supabase.rpc("lots_for_buyer_supply", rpc_params).execute()
    lots = rpc_result.data or []

    markets = {
        m["id"]: m
        for m in (supabase.table("markets").select("id,name,district").execute().data or [])
        if m.get("id")
    }
    ranked = rank_lots_for_buyer(buyer, lots, markets)
    return {
        "buyer_id": buyer_id,
        "buyer_name": buyer.get("name"),
        "lots": ranked,
    }
