import uuid
from fastapi import APIRouter, Depends, HTTPException
from supabase import Client
from app.deps import get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import OfferCreate, OfferUpdate

router = APIRouter(prefix="/api/v1/offers", tags=["Offers"])


@router.post("/")
def create_offer(
    body: OfferCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    lot = supabase.table("lots").select("id,user_id,status,quantity_qtl").eq("id", body.lot_id).execute().data
    if not lot or lot[0]["user_id"] != user_id:
        raise HTTPException(404, "lot not found")
    if lot[0]["status"] not in ("open", "offered"):
        raise HTTPException(409, "lot is not open for offers")
    if body.quantity_qtl > float(lot[0]["quantity_qtl"]):
        raise HTTPException(400, "offer quantity exceeds lot quantity")

    row = {
        "id": str(uuid.uuid4()),
        "lot_id": body.lot_id,
        "buyer_id": body.buyer_id,
        "user_id": user_id,
        "price_per_qtl": body.price_per_qtl,
        "quantity_qtl": body.quantity_qtl,
        "status": "pending",
    }
    res = supabase.table("offers").insert(row).execute()
    if not res.data:
        raise HTTPException(400, "could not create offer")
    supabase.table("lots").update({"status": "offered"}).eq("id", body.lot_id).execute()
    return res.data[0]


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
    return res.data or []


@router.patch("/{offer_id}")
def update_offer(
    offer_id: str,
    body: OfferUpdate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
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
    elif body.status == "rejected":
        open_offers = (
            supabase.table("offers")
            .select("id")
            .eq("lot_id", offer["lot_id"])
            .eq("status", "pending")
            .execute()
            .data
        )
        if not open_offers:
            supabase.table("lots").update({"status": "open"}).eq("id", offer["lot_id"]).execute()
    return offer
