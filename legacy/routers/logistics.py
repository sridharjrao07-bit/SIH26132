"""Logistics router — bookings via the ACID RPCs (migration 036).

Migration 031 revoked direct INSERT/UPDATE on logistics_bookings from API
roles; until 036 no RPC existed, so every booking write failed with 42501,
and the old insert referenced option_name / rate_per_qtl — columns that do
not exist on logistics_bookings (42703) — making POST /bookings doubly dead.

CREATE  → logistics_booking_create  (ownership + lot state + capacity under lock)
UPDATE  → logistics_booking_update  (owner-only state machine, notes persisted)
LIST    → direct SELECT (no write; RLS enforces visibility)
"""
from typing import Optional

from app.auth import get_current_user
from app.deps import get_supabase, get_supabase_as_user
from app.errors import json_for_api_error
from app.schemas.marketplace import LogisticsBookCreate, LogisticsBookUpdate
from fastapi import APIRouter, Depends, Query
from postgrest.exceptions import APIError
from supabase import Client

router = APIRouter(prefix="/api/v1/logistics", tags=["Logistics"])


def _call_rpc(supabase: Client, fn: str, params: dict):
    try:
        res = supabase.rpc(fn, params).execute()
        return res.data
    except APIError as exc:
        return json_for_api_error(exc)


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


@router.post("/bookings")
def create_booking(
    body: LogisticsBookCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Create a logistics booking via the logistics_booking_create RPC.

    The RPC (migration 036) validates lot ownership and state, that the
    option is active, and enforces capacity_qtl under an option row lock —
    the Python check-then-insert this replaces was racy (TOCTOU).
    """
    params = {
        "p_lot_id": body.lot_id,
        "p_logistics_id": body.logistics_id,
        "p_quantity_qtl": body.quantity_qtl,
        "p_scheduled_date": body.scheduled_date.isoformat() if body.scheduled_date else None,
        "p_notes": body.notes,
    }
    return _call_rpc(supabase, "logistics_booking_create", params)


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
):
    """Update a logistics booking via the logistics_booking_update RPC.

    Owner-only state machine: requested→confirmed→completed, cancel from
    requested/confirmed.  Notes are persisted (previously discarded).
    """
    params = {
        "p_booking_id": booking_id,
        "p_new_status": body.status,
        "p_notes": body.notes,
    }
    return _call_rpc(supabase, "logistics_booking_update", params)
