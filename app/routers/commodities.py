from fastapi import APIRouter, Depends
from typing import List
from supabase import Client
from app.deps import get_supabase
from app.schemas import CommodityResponse

router = APIRouter(prefix="/api/v1/commodities", tags=["Commodities"])

@router.get("/", response_model=List[CommodityResponse])
def get_commodities(supabase: Client = Depends(get_supabase)):
    """
    List all tracked commodities.
    """
    res = supabase.table("commodities").select("*").order("name_en").execute()
    return res.data
