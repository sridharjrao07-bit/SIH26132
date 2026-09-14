from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from supabase import Client
from app.deps import get_supabase, get_supabase_service_role, get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import BuyerResponse, BuyerRegisterRequest
from app.services.matching_engine import rank_lots_for_buyer

router = APIRouter(prefix="/api/v1/buyers", tags=["Buyers"])


@router.post("/register", response_model=BuyerResponse, status_code=201)
def register_buyer(
    req: BuyerRegisterRequest,
    uid: str = Depends(get_current_user),
    user_client: Client = Depends(get_supabase_as_user),
):
    """
    Self-service registration for a buyer profile.
    Tied to the authenticated user's ID via RLS (owner_user_id = auth.uid()).
    Duplicates per user are rejected by a unique constraint, but we also check here.
    """
    existing = user_client.table("buyers").select("id").eq("owner_user_id", uid).execute()
    if existing.data:
        raise HTTPException(409, "User already has a registered buyer profile")
        
    import uuid
    payload = req.model_dump(exclude_unset=True)
    payload["id"] = str(uuid.uuid4())
    payload["owner_user_id"] = uid
    payload["verification_state"] = "pending"
    payload["verified"] = False
    
    res = user_client.table("buyers").insert(payload).execute()
    if not res.data:
        raise HTTPException(500, "Failed to create buyer profile")
    return res.data[0]



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


@router.get("/{buyer_id}/supply")
def buyer_supply(
    buyer_id: str,
    uid: str = Depends(get_current_user),
    public: Client = Depends(get_supabase_as_user),
    db: Client = Depends(get_supabase_service_role),
):
    """Open lots that fit this verified buyer's demand (buyer-side aggregation)."""
    rows = (
        public.table("buyers")
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
    if buyer.get("owner_user_id") != uid:
        raise HTTPException(403, "Not authorized to view supply for this buyer")
    lots = (
        db.table("lots")
        .select("id,commodity_id,market_id,quantity_qtl,grade,asking_price,status,harvest_date,fpo_id")
        .limit(200)
        .execute()
        .data
        or []
    )
    lots = [l for l in lots if l.get("status") in ("open", "offered")]
    if buyer.get("commodity_id"):
        lots = [l for l in lots if l.get("commodity_id") == buyer["commodity_id"]]
    markets = {
        m["id"]: m
        for m in (public.table("markets").select("id,name,district").execute().data or [])
        if m.get("id")
    }
    ranked = rank_lots_for_buyer(buyer, lots, markets)
    return {
        "buyer_id": buyer_id,
        "buyer_name": buyer.get("name"),
        "lots": ranked,
    }
