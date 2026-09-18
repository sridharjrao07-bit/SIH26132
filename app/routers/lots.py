"""Lots router — all mutations via ACID RPCs (migration 032).

READ operations still use the Supabase table API (SELECT is not revoked).
WRITE operations (create, withdraw, grade) call security-definer RPCs that
own the write privilege and enforce ownership + state-machine in one transaction.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from supabase import Client
from app.deps import get_supabase_as_user
from app.auth import get_current_user
from app.errors import json_for_api_error
from app.schemas.marketplace import LotCreate, LotAggregate, LotGradeUpdate
from app.services.marketplace import lot_ledger
from postgrest.exceptions import APIError

router = APIRouter(prefix="/api/v1/lots", tags=["Lots"])


def _call_rpc(supabase: Client, fn: str, params: dict):
    """Call a Postgres RPC and surface any PostgREST error as HTTP."""
    try:
        res = supabase.rpc(fn, params).execute()
        return res.data
    except APIError as exc:
        raise json_for_api_error(exc) from exc


@router.post("/")
def create_lot(
    body: LotCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Create a lot via the lot_create RPC (user_id = auth.uid() server-side)."""
    params = {
        "p_commodity_id": body.commodity_id,
        "p_quantity_qtl": body.quantity_qtl,
        "p_grade": body.grade or "General",
        "p_quality_notes": body.quality_notes,
        "p_harvest_date": body.harvest_date.isoformat() if body.harvest_date else None,
        "p_asking_price": body.asking_price,
        "p_market_id": body.market_id,
        "p_fpo_id": body.fpo_id,
    }
    return _call_rpc(supabase, "lot_create", params)


@router.post("/aggregate")
def aggregate_lots(
    body: LotAggregate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """FPO pools member lots into one via the fpo_aggregate_lots RPC.

    The RPC validates the caller has the 'fpo' role and that all lots are open
    and share a commodity — no application-layer role check needed here.
    """
    params = {
        "p_lot_ids": body.lot_ids,
        "p_market_id": body.market_id,
        "p_asking_price": body.asking_price,
    }
    return _call_rpc(supabase, "fpo_aggregate_lots", params)


@router.get("/")
def list_lots(
    status: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Own lots plus lots aggregated under this user as an FPO."""
    allowed = {"open", "offered", "matched", "sold", "withdrawn"}
    if status and status not in allowed:
        raise HTTPException(422, "invalid status")

    own_q = supabase.table("lots").select("*").eq("user_id", user_id)
    fpo_q = supabase.table("lots").select("*").eq("fpo_id", user_id)
    if status:
        own_q = own_q.eq("status", status)
        fpo_q = fpo_q.eq("status", status)

    own = own_q.order("created_at", desc=True).limit(100).execute().data or []
    as_fpo = fpo_q.order("created_at", desc=True).limit(100).execute().data or []
    by_id: dict = {}
    for row in own + as_fpo:
        by_id[row.get("id")] = row
    return list(by_id.values())[:100]


@router.get("/{lot_id}/ledger")
def get_lot_ledger(
    lot_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Transparent transaction record for a lot (SIH outcome)."""
    res = supabase.table("lots").select("*").eq("id", lot_id).execute()
    if not res.data:
        raise HTTPException(404, "lot not found")
    lot = res.data[0]
    if lot.get("user_id") != user_id and lot.get("fpo_id") != user_id:
        raise HTTPException(404, "lot not found")
    return lot_ledger(supabase, lot)


@router.get("/{lot_id}")
def get_lot(
    lot_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = supabase.table("lots").select("*").eq("id", lot_id).execute()
    if not res.data:
        raise HTTPException(404, "lot not found")
    lot = res.data[0]
    if lot.get("user_id") != user_id and lot.get("fpo_id") != user_id:
        raise HTTPException(404, "lot not found")
    return lot


@router.patch("/{lot_id}/grade")
def grade_lot(
    lot_id: str,
    body: LotGradeUpdate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Grade a lot via the lot_grade_update RPC."""
    params = {
        "p_lot_id": lot_id,
        "p_grade": body.grade,
        "p_quality_notes": body.quality_notes,
    }
    return _call_rpc(supabase, "lot_grade_update", params)


@router.patch("/{lot_id}/withdraw")
def withdraw_lot(
    lot_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Withdraw a lot via the lot_withdraw RPC."""
    return _call_rpc(supabase, "lot_withdraw", {"p_lot_id": lot_id})
