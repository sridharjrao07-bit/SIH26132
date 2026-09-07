import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional, List
from supabase import Client
from app.deps import get_supabase, get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import StorageFacilityResponse, StorageBookCreate, StorageBookUpdate, StorageBookingResponse

router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])

ACTIVE_BOOKING_STATUSES = ("requested", "confirmed")

def booked_storage_quantity(supabase: Client, facility_id: str, exclude_id: Optional[str] = None) -> float:
    """Sum of quantity_qtl for active bookings for a facility."""
    query = supabase.table("storage_bookings").select("quantity_qtl").eq("facility_id", facility_id).in_("status", ACTIVE_BOOKING_STATUSES)
    if exclude_id:
        query = query.neq("id", exclude_id)
    res = query.execute()
    return sum(float(r["quantity_qtl"]) for r in res.data) if res.data else 0.0

@router.get("/facilities", response_model=List[StorageFacilityResponse])
def list_facilities(
    district: Optional[str] = Query(None),
    supabase: Client = Depends(get_supabase),
):
    query = supabase.table("storage_facilities").select("*").eq("is_active", True)
    if district:
        query = query.eq("district", district)
    res = query.order("name").limit(100).execute()
    return res.data or []

def _own_lot(supabase, lot_id: str, user_id: str) -> dict:
    rows = supabase.table("lots").select("*").eq("id", lot_id).execute().data or []
    if not rows:
        raise HTTPException(404, "lot not found")
    lot = rows[0]
    if lot.get("user_id") != user_id and lot.get("fpo_id") != user_id:
        raise HTTPException(404, "lot not found")
    if lot.get("status") in ("withdrawn", "sold"):
        raise HTTPException(409, "cannot book storage for a sold or withdrawn lot")
    return lot

def _active_facility(supabase, facility_id: str) -> dict:
    rows = (
        supabase.table("storage_facilities")
        .select("*")
        .eq("id", facility_id)
        .eq("is_active", True)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "storage facility not found")
    return rows[0]

def _assert_capacity(supabase, facility: dict, extra_qty: float, exclude_id: Optional[str] = None):
    cap = facility.get("capacity_qtl")
    if cap is None:
        return
    used = booked_storage_quantity(supabase, facility["id"], exclude_id=exclude_id)
    if (used + extra_qty) > float(cap):
        raise HTTPException(400, f"facility capacity exceeded. Available: {float(cap) - used}")

@router.post("/bookings", response_model=StorageBookingResponse, status_code=201)
def book_storage(
    req: StorageBookCreate,
    user_id: str = Depends(get_current_user),
    user_client: Client = Depends(get_supabase_as_user),
):
    _own_lot(user_client, req.lot_id, user_id)
    facility = _active_facility(user_client, req.facility_id)
    _assert_capacity(user_client, facility, req.quantity_qtl)

    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "lot_id": req.lot_id,
        "facility_id": req.facility_id,
        "quantity_qtl": req.quantity_qtl,
        "status": "requested",
        "created_at": now,
        "updated_at": now,
    }
    if req.storage_start_date:
        payload["storage_start_date"] = req.storage_start_date.isoformat()
    if req.storage_end_date:
        payload["storage_end_date"] = req.storage_end_date.isoformat()
    if req.notes:
        payload["notes"] = req.notes

    res = user_client.table("storage_bookings").insert(payload).execute()
    if not res.data:
        raise HTTPException(500, "failed to create booking")
    return res.data[0]

@router.get("/bookings", response_model=List[StorageBookingResponse])
def list_bookings(
    lot_id: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
    user_client: Client = Depends(get_supabase_as_user),
):
    query = user_client.table("storage_bookings").select("*").eq("user_id", user_id)
    if lot_id:
        query = query.eq("lot_id", lot_id)
    res = query.order("created_at", desc=True).limit(50).execute()
    return res.data or []

@router.patch("/bookings/{booking_id}", response_model=StorageBookingResponse)
def update_booking(
    booking_id: str,
    req: StorageBookUpdate,
    user_id: str = Depends(get_current_user),
    user_client: Client = Depends(get_supabase_as_user),
):
    rows = user_client.table("storage_bookings").select("*").eq("id", booking_id).execute().data or []
    if not rows:
        raise HTTPException(404, "booking not found")
    b = rows[0]

    if b.get("status") in ("cancelled", "completed"):
        raise HTTPException(409, f"cannot transition from {b.get('status')}")
    if req.status == "requested":
        raise HTTPException(400, "cannot transition back to requested")

    if req.status == "confirmed":
        facility = _active_facility(user_client, b["facility_id"])
        _assert_capacity(user_client, facility, b["quantity_qtl"], exclude_id=booking_id)

    now = datetime.now(timezone.utc).isoformat()
    payload = {"status": req.status, "updated_at": now}
    if req.notes:
        payload["notes"] = req.notes

    res = user_client.table("storage_bookings").update(payload).eq("id", booking_id).execute()
    return res.data[0]
