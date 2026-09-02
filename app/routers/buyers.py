from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from supabase import Client
from app.deps import get_supabase
from app.schemas.marketplace import BuyerResponse

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
