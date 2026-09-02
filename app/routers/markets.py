from fastapi import APIRouter, Depends, Query, HTTPException
from typing import List, Optional
from supabase import Client
from app.deps import get_supabase
from app.schemas import MarketResponse
import structlog

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/markets", tags=["Markets"])

@router.get("/", response_model=List[MarketResponse])
def get_markets(
    district: Optional[str] = Query(None, description="Filter by district"),
    active_only: bool = Query(True, description="Only show active markets"),
    supabase: Client = Depends(get_supabase)
):
    """
    List all tracked markets (mandis).
    """
    query = supabase.table("markets").select("*")
    if district:
        query = query.eq("district", district)
    if active_only:
        query = query.eq("is_active", True)
        
    res = query.order("name").execute()
    return res.data or []

@router.get("/nearby")
def get_nearby_markets(
    lat: float = Query(..., ge=-90, le=90, description="Latitude (-90 to 90)"),
    lng: float = Query(..., ge=-180, le=180, description="Longitude (-180 to 180)"),
    radius_km: float = Query(50, gt=0, le=500, description="Search radius in km (max 500)"),
    supabase: Client = Depends(get_supabase)
):
    """
    Find markets near a coordinate using the earthdistance extension via Supabase RPC.
    Returns up to 5 nearest active markets within the given radius.
    """
    try:
        res = supabase.rpc("nearby_markets", {"lat": lat, "lng": lng, "radius_km": radius_km}).execute()
        return res.data
    except Exception as e:
        logger.error("nearby_markets_rpc_error", error=str(e))
        raise HTTPException(status_code=503, detail="Geo lookup temporarily unavailable")
