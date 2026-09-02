import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from supabase import Client
from app.deps import get_supabase, get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import LogisticsBookCreate, LogisticsBookUpdate
from app.marketplace import booked_quantity, ACTIVE_BOOKING_STATUSES

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


def _own_lot(supabase, lot_id: str, user_id: str) -> dict:
    rows = supabase.table("lots").select("*").eq("id", lot_id).execute().data or []
    if not rows:
        raise HTTPException(404, "lot not found")
    lot = rows[0]
    if lot.get("user_id") != user_id and lot.get("fpo_id") != user_id:
        raise HTTPException(404, "lot not found")
    if lot.get("status") in ("withdrawn", "sold"):
        raise HTTPException(409, "cannot book logistics for a sold or withdrawn lot")
    return lot


def _active_option(supabase, logistics_id: str) -> dict:
    rows = (
        supabase.table("logistics_options")
        .select("*")
        .eq("id", logistics_id)
        .eq("is_active", True)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "logistics option not found")
    return rows[0]


def _assert_capacity(supabase, option: dict, extra_qty: float, exclude_id: Optional[str] = None):
    cap = option.get("capacity_qtl")
    if cap is None:
        return
    used = booked_quantity(supabase, option["id"], exclude_id=exclude_id)
    if used + extra_qty > float(cap) + 1e-9:
        raise HTTPException(
            409,
            f"not enough capacity at {option.get('name')}: "
            f"{used:.0f}/{float(cap):.0f} qtl already booked",
        )


@router.post("/bookings")
def create_booking(
    body: LogisticsBookCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
    public: Client = Depends(get_supabase),
):
    lot = _own_lot(supabase, body.lot_id, user_id)
    option = _active_option(public, body.logistics_id)
    qty = float(body.quantity_qtl) if body.quantity_qtl is not None else float(lot["quantity_qtl"])
    if qty > float(lot["quantity_qtl"]) + 1e-9:
        raise HTTPException(400, "booking quantity exceeds lot quantity")
    _assert_capacity(supabase, option, qty)
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "lot_id": body.lot_id,
        "logistics_id": body.logistics_id,
        "kind": option.get("kind"),
        "quantity_qtl": qty,
        "status": "requested",
        "scheduled_date": body.scheduled_date.isoformat() if body.scheduled_date else None,
        "notes": body.notes,
        "created_at": now,
        "updated_at": now,
        "option_name": option.get("name"),
        "rate_per_qtl": option.get("rate_per_qtl"),
    }
    res = supabase.table("logistics_bookings").insert(row).execute()
    if not res.data:
        raise HTTPException(400, "could not create booking")
    return res.data[0]


@router.get("/bookings")
def list_bookings(
    lot_id: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    q = supabase.table("logistics_bookings").select("*").eq("user_id", user_id)
    if lot_id:
        q = q.eq("lot_id", lot_id)
    res = q.order("created_at", desc=True).limit(100).execute()
    return res.data or []


@router.patch("/bookings/{booking_id}")
def update_booking(
    booking_id: str,
    body: LogisticsBookUpdate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
    public: Client = Depends(get_supabase),
):
    rows = (
        supabase.table("logistics_bookings")
        .select("*")
        .eq("id", booking_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "booking not found")
    current = rows[0]
    if current.get("status") == "completed" and body.status != "completed":
        raise HTTPException(409, "completed booking cannot change status")
    if body.status in ACTIVE_BOOKING_STATUSES:
        option = _active_option(public, current["logistics_id"])
        _assert_capacity(supabase, option, float(current["quantity_qtl"]), exclude_id=booking_id)
    res = (
        supabase.table("logistics_bookings")
        .update({"status": body.status})
        .eq("id", booking_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "booking not found")
    return res.data[0]
