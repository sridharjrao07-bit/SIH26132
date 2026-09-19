"""Payments router — all mutations via ACID RPCs (migrations 013 and 032).

CREATE  → payment_create     (idempotent; amount validated by DB trigger)
PAID    → payment_mark_paid  (closes lot atomically)
FAILED  → transition_payment_status (existing RPC from migration 013)
DISPUTED→ transition_payment_status (existing RPC from migration 013)
LIST    → direct SELECT (no write; RLS enforces visibility)
"""
from app.auth import get_current_user
from app.deps import get_supabase_as_user, get_supabase_service_role
from app.errors import json_for_api_error
from app.schemas.marketplace import PaymentCreate
from app.services.marketplace import recompute_buyer_reliability
from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError
from supabase import Client

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


def _call_rpc(supabase: Client, fn: str, params: dict):
    try:
        res = supabase.rpc(fn, params).execute()
        return res.data
    except APIError as exc:
        raise json_for_api_error(exc) from exc


def _rescore_offer_buyer(user_db: Client, service_db: Client, offer_id: str) -> None:
    offers = user_db.table("offers").select("buyer_id").eq("id", offer_id).execute().data or []
    if not offers:
        return
    buyer_id = offers[0].get("buyer_id")
    if buyer_id:
        recompute_buyer_reliability(service_db, buyer_id)


@router.post("/")
def create_payment(
    body: PaymentCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Create a payment via the payment_create RPC.

    The RPC is idempotent — if a pending/paid payment already exists for the
    offer it returns that row instead of inserting a duplicate.  The DB trigger
    trg_check_payment_amount (migration 031) validates amount at the boundary.
    """
    try:
        return _call_rpc(supabase, "payment_create", {
            "p_offer_id":  body.offer_id,
            "p_amount":    body.amount,
            "p_reference": body.reference,
        })
    except HTTPException:
        raise
    except Exception:
        # Mask all other exceptions — never leak DB internals to the client.
        raise HTTPException(400, "could not create payment")


@router.get("/")
def list_payments(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = (
        supabase.table("payments")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return res.data or []


@router.patch("/{payment_id}/paid")
def mark_paid(
    payment_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
    service: Client = Depends(get_supabase_service_role),
):
    """Mark payment as paid AND close the lot via payment_mark_paid RPC.

    The RPC is atomic: lot status advances to 'sold' in the same transaction
    as the payment status change.  No multi-step rollback needed.
    """
    payment = _call_rpc(supabase, "payment_mark_paid", {"p_payment_id": payment_id})
    if isinstance(payment, dict):
        _rescore_offer_buyer(supabase, service, payment.get("offer_id", ""))
    return payment


@router.patch("/{payment_id}/failed")
def mark_failed(
    payment_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
    service: Client = Depends(get_supabase_service_role),
):
    payment = _call_rpc(supabase, "transition_payment_status", {
        "p_user_id":    user_id,
        "p_payment_id": payment_id,
        "p_new_status": "failed",
    })
    if isinstance(payment, dict):
        _rescore_offer_buyer(supabase, service, payment.get("offer_id", ""))
    return payment


@router.patch("/{payment_id}/disputed")
def mark_disputed(
    payment_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
    service: Client = Depends(get_supabase_service_role),
):
    payment = _call_rpc(supabase, "transition_payment_status", {
        "p_user_id":    user_id,
        "p_payment_id": payment_id,
        "p_new_status": "disputed",
    })
    if isinstance(payment, dict):
        _rescore_offer_buyer(supabase, service, payment.get("offer_id", ""))
    return payment
