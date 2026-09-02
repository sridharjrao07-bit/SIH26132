from fastapi import APIRouter, Depends, Query
from typing import Optional
from supabase import Client
from app.deps import get_supabase

router = APIRouter(prefix="/api/v1/logistics", tags=["Logistics"])


@router.get("/")
def list_logistics(
    district: Optional[str] = Query(None),
    kind: Optional[str] = Query(None),
    supabase: Client = Depends(get_supabase),
):
    query = supabase.table("logistics_options").select("*").eq("is_active", True)
    if district:
        query = query.eq("district", district)
    if kind:
        query = query.eq("kind", kind)
    res = query.order("name").limit(100).execute()
    return res.data or []
