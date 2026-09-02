from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from supabase import Client
from app.deps import get_supabase, get_supabase_service_role
from app.schemas.marketplace import BuyerResponse
from app.matching_engine import rank_lots_for_buyer

router = APIRouter(prefix="/api/v1/buyers", tags=["Buyers"])


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
    public: Client = Depends(get_supabase),
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
