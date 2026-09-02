import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.deps import get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import PaymentCreate

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])


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

    row = {
        "id": str(uuid.uuid4()),
        "offer_id": body.offer_id,
        "user_id": user_id,
        "amount": body.amount,
        "status": "pending",
        "reference": body.reference,
    }
    res = supabase.table("payments").insert(row).execute()
    if not res.data:
        raise HTTPException(400, "could not create payment")
    return res.data[0]


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
):
    res = (
        supabase.table("payments")
        .update({
            "status": "paid",
            "paid_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", payment_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "payment not found")
    payment = res.data[0]
    offer = supabase.table("offers").select("lot_id").eq("id", payment["offer_id"]).execute().data
    if offer:
        supabase.table("lots").update({"status": "sold"}).eq("id", offer[0]["lot_id"]).execute()
    return payment
