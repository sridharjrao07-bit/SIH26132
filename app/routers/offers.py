import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.deps import get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import OfferCreate, OfferUpdate
from app.services.marketplace import (
    offer_is_stale,
    with_expiry,
    _reopen_lot_if_idle,
)

router = APIRouter(prefix="/api/v1/offers", tags=["Offers"])


@router.post("/")
def create_offer(
    body: OfferCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    # Farmer (lot owner) creates a digital offer *to* a verified buyer.
    # Buyers do not POST here; matching is local-first then the farmer confirms.
    lot = supabase.table("lots").select("id,user_id,status,quantity_qtl").eq("id", body.lot_id).execute().data
    if not lot or lot[0]["user_id"] != user_id:
        raise HTTPException(404, "lot not found")
    if lot[0]["status"] not in ("open", "offered"):
        raise HTTPException(409, "lot is not open for offers")
    if body.quantity_qtl > float(lot[0]["quantity_qtl"]):
        raise HTTPException(400, "offer quantity exceeds lot quantity")

    now = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid.uuid4()),
        "lot_id": body.lot_id,
        "buyer_id": body.buyer_id,
        "user_id": user_id,
        "price_per_qtl": body.price_per_qtl,
        "quantity_qtl": body.quantity_qtl,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    res = supabase.table("offers").insert(row).execute()
    if not res.data:
        raise HTTPException(400, "could not create offer")
    supabase.table("lots").update({"status": "offered"}).eq("id", body.lot_id).execute()
    return with_expiry(res.data[0])


@router.get("/")
def list_offers(
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = (
        supabase.table("offers")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return [with_expiry(row) for row in (res.data or [])]


@router.patch("/{offer_id}")
def update_offer(
    offer_id: str,
    body: OfferUpdate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    rows = (
        supabase.table("offers")
        .select("*")
        .eq("id", offer_id)
        .eq("user_id", user_id)
        .execute()
        .data
        or []
    )
    if not rows:
        raise HTTPException(404, "offer not found or access denied")
    current = rows[0]

    if current.get("status") == "pending" and offer_is_stale(current):
        supabase.table("offers").update({"status": "expired"}).eq("id", offer_id).execute()
        _reopen_lot_if_idle(supabase, current.get("lot_id"))
        raise HTTPException(409, "offer expired")

    if body.status == "accepted" and current.get("status") != "pending":
        raise HTTPException(409, f"cannot accept a {current.get('status')} offer")

    res = (
        supabase.table("offers")
        .update({"status": body.status})
        .eq("id", offer_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "offer not found or access denied")
    offer = res.data[0]
    if body.status == "accepted":
        supabase.table("lots").update({"status": "matched"}).eq("id", offer["lot_id"]).execute()
    elif body.status in ("rejected", "expired"):
        _reopen_lot_if_idle(supabase, offer["lot_id"])
    return with_expiry(offer)
