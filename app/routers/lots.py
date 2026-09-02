import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from supabase import Client
from app.deps import get_supabase_as_user
from app.auth import get_current_user
from app.schemas.marketplace import LotCreate, LotAggregate, LotGradeUpdate
from app.marketplace import lot_ledger

router = APIRouter(prefix="/api/v1/lots", tags=["Lots"])


@router.post("/")
def create_lot(
    body: LotCreate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "fpo_id": body.fpo_id,
        "commodity_id": body.commodity_id,
        "market_id": body.market_id,
        "quantity_qtl": body.quantity_qtl,
        "grade": body.grade or "General",
        "quality_notes": body.quality_notes,
        "harvest_date": body.harvest_date.isoformat() if body.harvest_date else None,
        "asking_price": body.asking_price,
        "status": "open",
    }
    res = supabase.table("lots").insert(row).execute()
    if not res.data:
        raise HTTPException(400, "could not create lot")
    return res.data[0]


@router.post("/aggregate")
def aggregate_lots(
    body: LotAggregate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """FPO rolls member lots into one pooled lot for matching."""
    profile = (
        supabase.table("user_profiles").select("role").eq("id", user_id).execute().data or []
    )
    if not profile or profile[0].get("role") != "fpo":
        raise HTTPException(403, "requires fpo role")

    members = []
    for lid in body.lot_ids:
        rows = supabase.table("lots").select("*").eq("id", lid).execute().data or []
        if not rows:
            raise HTTPException(404, f"lot not found: {lid}")
        lot = rows[0]
        if lot.get("status") != "open":
            raise HTTPException(409, f"lot {lid} is not open")
        members.append(lot)

    commodity_ids = {m["commodity_id"] for m in members}
    if len(commodity_ids) != 1:
        raise HTTPException(400, "all lots must share the same commodity")

    qty = sum(float(m["quantity_qtl"]) for m in members)
    asking = body.asking_price
    if asking is None:
        priced = [float(m["asking_price"]) for m in members if m.get("asking_price") is not None]
        asking = (sum(priced) / len(priced)) if priced else None

    pooled = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "fpo_id": user_id,
        "commodity_id": members[0]["commodity_id"],
        "market_id": body.market_id or members[0].get("market_id"),
        "quantity_qtl": qty,
        "grade": members[0].get("grade") or "General",
        "quality_notes": f"FPO aggregate of {len(members)} lots",
        "asking_price": asking,
        "status": "open",
    }
    res = supabase.table("lots").insert(pooled).execute()
    if not res.data:
        raise HTTPException(400, "could not create pooled lot")
    for m in members:
        supabase.table("lots").update({"status": "matched", "fpo_id": user_id}).eq("id", m["id"]).execute()
    return res.data[0]


@router.get("/")
def list_lots(
    status: Optional[str] = Query(None),
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Own lots plus lots aggregated under this user as an FPO."""
    own_q = supabase.table("lots").select("*").eq("user_id", user_id)
    fpo_q = supabase.table("lots").select("*").eq("fpo_id", user_id)
    if status:
        own_q = own_q.eq("status", status)
        fpo_q = fpo_q.eq("status", status)
    own = own_q.order("created_at", desc=True).limit(100).execute().data or []
    as_fpo = fpo_q.order("created_at", desc=True).limit(100).execute().data or []
    by_id = {}
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
    return res.data[0]


@router.patch("/{lot_id}/grade")
def grade_lot(
    lot_id: str,
    body: LotGradeUpdate,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    """Record FAQ / General / Special after a visual or mandi assay."""
    rows = supabase.table("lots").select("*").eq("id", lot_id).execute().data or []
    if not rows:
        raise HTTPException(404, "lot not found")
    lot = rows[0]
    if lot.get("user_id") != user_id and lot.get("fpo_id") != user_id:
        raise HTTPException(404, "lot not found")
    if lot.get("status") in ("sold", "withdrawn"):
        raise HTTPException(409, "cannot regrade a sold or withdrawn lot")
    payload = {"grade": body.grade}
    if body.quality_notes is not None:
        payload["quality_notes"] = body.quality_notes
    res = supabase.table("lots").update(payload).eq("id", lot_id).execute()
    if not res.data:
        raise HTTPException(404, "lot not found")
    return res.data[0]


@router.patch("/{lot_id}/withdraw")
def withdraw_lot(
    lot_id: str,
    user_id: str = Depends(get_current_user),
    supabase: Client = Depends(get_supabase_as_user),
):
    res = (
        supabase.table("lots")
        .update({"status": "withdrawn"})
        .eq("id", lot_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "lot not found or access denied")
    return res.data[0]
