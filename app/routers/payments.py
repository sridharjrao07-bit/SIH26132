import uuid
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.deps import get_supabase_as_user, get_supabase_service_role
from app.auth import get_current_user
from app.schemas.marketplace import PaymentCreate
from app.services.marketplace import recompute_buyer_reliability

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


def _own_payment(supabase, payment_id: str, user_id: str):
    rows = (
        supabase.table("payments")
        .select("*")
        .eq("id", payment_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "payment not found")
    return rows[0]


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
    offer = supabase.table("offers").select("*").eq("id", body.offer_id).execute().data
    if not offer or offer[0]["user_id"] != user_id:
        raise HTTPException(404, "offer not found")
    if offer[0]["status"] != "accepted":
        raise HTTPException(409, "payments require an accepted offer")

    existing = (
        supabase.table("payments")
        .select("*")
        .eq("offer_id", body.offer_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    for row in existing:
        if row.get("status") not in ("pending", "paid"):
            continue
        if body.reference and row.get("reference") == body.reference:
            return row
        if row.get("status") == "paid":
            raise HTTPException(409, "offer already has a paid payment")
        return row

    row = {
        "id": str(uuid.uuid4()),
        "offer_id": body.offer_id,
        "user_id": user_id,
        "amount": body.amount,
        "status": "pending",
        "reference": body.reference,
    }
    try:
        res = supabase.table("payments").insert(row).execute()
        if not res.data:
            raise HTTPException(400, "could not create payment")
        return res.data[0]
    except Exception as e:
        if "23505" in str(e) or "duplicate key" in str(e).lower():
            re_existing = supabase.table("payments").select("*").eq("offer_id", body.offer_id).eq("user_id", user_id).execute()
            for r in (re_existing.data or []):
                if r.get("status") in ("pending", "paid"):
                    return r
        raise HTTPException(400, f"could not create payment: {e}")


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
    # Belt-and-braces ownership check before calling RPC (gives 404 not 403).
    current = _own_payment(supabase, payment_id, user_id)
    # Ownership-asserting RPC: validates state machine + updates status atomically.
    res = supabase.rpc(
        "transition_payment_status",
        {"p_user_id": user_id, "p_payment_id": payment_id, "p_new_status": "paid"},
    ).execute()
    if not res.data:
        raise HTTPException(404, "payment not found")
    payment = res.data if isinstance(res.data, dict) else res.data[0] if isinstance(res.data, list) else res.data
    offer = supabase.table("offers").select("lot_id").eq("id", payment["offer_id"]).execute().data
    if offer:
        lot_id = offer[0]["lot_id"]
        lot_res = supabase.table("lots").update({"status": "sold"}).eq("id", lot_id).execute()
        if not lot_res.data:
            # Rollback: revert payment status
            supabase.rpc(
                "transition_payment_status",
                {"p_user_id": user_id, "p_payment_id": payment_id,
                 "p_new_status": current.get("status") or "pending"},
            ).execute()
            raise HTTPException(503, "could not close lot; payment not marked paid")
    _rescore_offer_buyer(supabase, service, payment["offer_id"])
    return payment


@router.patch("/{payment_id}/failed")
def mark_failed(
    payment_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
    service: Client = Depends(get_supabase_service_role),
):
    _own_payment(supabase, payment_id, user_id)  # 404 guard
    res = supabase.rpc(
        "transition_payment_status",
        {"p_user_id": user_id, "p_payment_id": payment_id, "p_new_status": "failed"},
    ).execute()
    if not res.data:
        raise HTTPException(404, "payment not found")
    payment = res.data if isinstance(res.data, dict) else res.data[0] if isinstance(res.data, list) else res.data
    _rescore_offer_buyer(supabase, service, payment["offer_id"])
    return payment


@router.patch("/{payment_id}/disputed")
def mark_disputed(
    payment_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
    service: Client = Depends(get_supabase_service_role),
):
    _own_payment(supabase, payment_id, user_id)  # 404 guard
    res = supabase.rpc(
        "transition_payment_status",
        {"p_user_id": user_id, "p_payment_id": payment_id, "p_new_status": "disputed"},
    ).execute()
    if not res.data:
        raise HTTPException(404, "payment not found")
    payment = res.data if isinstance(res.data, dict) else res.data[0] if isinstance(res.data, list) else res.data
    _rescore_offer_buyer(supabase, service, payment["offer_id"])
    return payment
