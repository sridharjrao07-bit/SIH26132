import uuid
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.deps import get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import GrievanceCreate

router = APIRouter(prefix="/api/v1/grievances", tags=["Grievances"])


@router.post("/")
def create_grievance(
    body: GrievanceCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "offer_id": body.offer_id,
        "lot_id": body.lot_id,
        "category": body.category,
        "description": body.description,
        "status": "open",
    }
    res = supabase.table("grievances").insert(row).execute()
    if not res.data:
        raise HTTPException(400, "could not create grievance")
    return res.data[0]


@router.get("/")
def list_grievances(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = (
        supabase.table("grievances")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return res.data or []
