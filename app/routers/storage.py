"""Storage router — bookings via the ACID RPCs (migration 036).

Migration 031 revoked direct INSERT/UPDATE on storage_bookings from API roles;
until 036 no RPC existed, so every booking write failed with 42501 and the
Python-side capacity check was a check-then-insert race (TOCTOU).

CREATE  → storage_booking_create  (ownership + lot state + capacity under lock)
UPDATE  → storage_booking_update  (owner-only state machine, notes persisted)
LIST    → direct SELECT (no write; RLS enforces visibility)
"""
from typing import List, Optional

from app.auth import get_current_user
from app.deps import get_supabase, get_supabase_as_user
from app.errors import json_for_api_error
from app.schemas.marketplace import (
    StorageBookCreate,
    StorageBookingResponse,
    StorageBookUpdate,
    StorageFacilityResponse,
)
from fastapi import APIRouter, Depends, Query
from postgrest.exceptions import APIError
from supabase import Client

router = APIRouter(prefix="/api/v1/storage", tags=["Storage"])


def _call_rpc(supabase: Client, fn: str, params: dict):
    try:
        res = supabase.rpc(fn, params).execute()
        return res.data
    except APIError as exc:
        return json_for_api_error(exc)


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


@router.post("/bookings", response_model=StorageBookingResponse, status_code=201)
def book_storage(
    req: StorageBookCreate,
    user_id: str = Depends(get_current_user),
    user_client: Client = Depends(get_supabase_as_user),
):
    """Book storage via the storage_booking_create RPC.

    The RPC (migration 036) validates lot ownership and state, that the
    facility is active, and enforces capacity under a facility row lock —
    concurrent bookings can never oversubscribe a godown.
    """
    params = {
        "p_lot_id": req.lot_id,
        "p_facility_id": req.facility_id,
        "p_quantity_qtl": req.quantity_qtl,
        "p_storage_start_date": req.storage_start_date.isoformat() if req.storage_start_date else None,
        "p_storage_end_date": req.storage_end_date.isoformat() if req.storage_end_date else None,
        "p_notes": req.notes,
    }
    return _call_rpc(user_client, "storage_booking_create", params)


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
    """Update a storage booking via the storage_booking_update RPC.

    Owner-only state machine: requested→confirmed→completed, cancel from
    requested/confirmed.  Notes are persisted (previously discarded).
    """
    params = {
        "p_booking_id": booking_id,
        "p_new_status": req.status,
        "p_notes": req.notes,
    }
    return _call_rpc(user_client, "storage_booking_update", params)
