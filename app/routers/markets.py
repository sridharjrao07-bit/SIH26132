from fastapi import APIRouter, Depends, Query, HTTPException
from typing import List, Optional
from supabase import Client
from app.deps import get_supabase
from app.schemas import MarketResponse

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
    return res.data

@router.get("/nearby")
def get_nearby_markets(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
    radius_km: float = Query(50, description="Radius in km"),
    supabase: Client = Depends(get_supabase)
):
    """
    Find markets near a coordinate using PostGIS/earthdistance via Supabase RPC.
    """
    try:
        res = supabase.rpc("nearby_markets", {"lat": lat, "lng": lng, "radius_km": radius_km}).execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
