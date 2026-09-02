import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from supabase import Client
from app.deps import get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import LotCreate

router = APIRouter(prefix="/api/v1/lots", tags=["Lots"])


@router.post("/")
def create_lot(
    body: LotCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "fpo_id": body.fpo_id,
        "commodity_id": body.commodity_id,
        "market_id": body.market_id,
        "quantity_qtl": body.quantity_qtl,
        "grade": body.grade or "General",
        "quality_notes": body.quality_notes,
        "harvest_date": body.harvest_date.isoformat() if body.harvest_date else None,
        "asking_price": body.asking_price,
        "status": "open",
    }
    res = supabase.table("lots").insert(row).execute()
    if not res.data:
        raise HTTPException(400, "could not create lot")
    return res.data[0]


@router.get("/")
def list_lots(
    status: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    query = supabase.table("lots").select("*").eq("user_id", user_id)
    if status:
        query = query.eq("status", status)
    res = query.order("created_at", desc=True).limit(100).execute()
    return res.data or []


@router.get("/{lot_id}")
def get_lot(
    lot_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = supabase.table("lots").select("*").eq("id", lot_id).execute()
    if not res.data:
        raise HTTPException(404, "lot not found")
    return res.data[0]


@router.patch("/{lot_id}/withdraw")
def withdraw_lot(
    lot_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = (
        supabase.table("lots")
        .update({"status": "withdrawn"})
        .eq("id", lot_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "lot not found or access denied")
    return res.data[0]
