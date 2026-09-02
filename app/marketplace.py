"""Shared marketplace helpers: offer TTL and buyer payment-reliability."""
from datetime import datetime, timedelta, timezone
from typing import Optional

OFFER_TTL_HOURS = 48


def _parse_dt(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def offer_expires_at(offer: dict, ttl_hours: int = OFFER_TTL_HOURS) -> Optional[str]:
    created = _parse_dt(offer.get("created_at"))
    if created is None:
        return None
    return (created + timedelta(hours=ttl_hours)).isoformat()


def offer_is_stale(offer: dict, now: Optional[datetime] = None, ttl_hours: int = OFFER_TTL_HOURS) -> bool:
    if offer.get("status") != "pending":
        return False
    created = _parse_dt(offer.get("created_at"))
    if created is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - created > timedelta(hours=ttl_hours)


def with_expiry(offer: dict, ttl_hours: int = OFFER_TTL_HOURS) -> dict:
    row = dict(offer)
    row["expires_at"] = offer_expires_at(row, ttl_hours=ttl_hours)
    return row


def _reopen_lot_if_idle(supabase, lot_id: str) -> bool:
    pending = (
        supabase.table("offers")
        .select("id")
        .eq("lot_id", lot_id)
        .eq("status", "pending")
        .execute()
        .data
        or []
    )
    if pending:
        return False
    lot_rows = supabase.table("lots").select("id,status").eq("id", lot_id).execute().data or []
    if not lot_rows or lot_rows[0].get("status") != "offered":
        return False
    supabase.table("lots").update({"status": "open"}).eq("id", lot_id).execute()
    return True


def expire_stale_offers(supabase, ttl_hours: int = OFFER_TTL_HOURS, now: Optional[datetime] = None) -> dict:
    """Mark pending offers older than TTL as expired and reopen idle lots."""
    now = now or datetime.now(timezone.utc)
    pending = (
        supabase.table("offers")
        .select("*")
        .eq("status", "pending")
        .limit(500)
        .execute()
        .data
        or []
    )
    expired_ids = []
    lots_reopened = 0
    for offer in pending:
        if not offer_is_stale(offer, now=now, ttl_hours=ttl_hours):
            continue
        supabase.table("offers").update({"status": "expired"}).eq("id", offer["id"]).execute()
        expired_ids.append(offer["id"])
        if _reopen_lot_if_idle(supabase, offer.get("lot_id")):
            lots_reopened += 1
    return {"expired": len(expired_ids), "lots_reopened": lots_reopened, "offer_ids": expired_ids}


def score_payment_reliability(paid: int, failed: int, disputed: int, open_payment_grievances: int) -> Optional[str]:
    """
    Map observed settlement history to high / medium / low.

    Returns None when there is no evidence so callers keep the seeded value.
    """
    paid = int(paid or 0)
    failed = int(failed or 0)
    disputed = int(disputed or 0)
    grief = int(open_payment_grievances or 0)
    if paid + failed + disputed + grief == 0:
        return None
    score = 50 + 15 * paid - 20 * failed - 30 * disputed - 15 * grief
    if score >= 70:
        return "high"
    if score >= 40:
        return "medium"
    return "low"


def recompute_buyer_reliability(supabase, buyer_id: str) -> Optional[str]:
    """Recompute and persist buyers.payment_reliability from offers/payments/grievances."""
    if not buyer_id:
        return None
    offers = (
        supabase.table("offers")
        .select("id")
        .eq("buyer_id", buyer_id)
        .execute()
        .data
        or []
    )
    offer_ids = [o["id"] for o in offers if o.get("id")]
    paid = failed = disputed = grief = 0
    if offer_ids:
        payments = (
            supabase.table("payments")
            .select("status,offer_id")
            .in_("offer_id", offer_ids)
            .execute()
            .data
            or []
        )
        for p in payments:
            st = p.get("status")
            if st == "paid":
                paid += 1
            elif st == "failed":
                failed += 1
            elif st == "disputed":
                disputed += 1
        grievances = (
            supabase.table("grievances")
            .select("id,status,category,offer_id")
            .in_("offer_id", offer_ids)
            .eq("category", "payment")
            .execute()
            .data
            or []
        )
        grief = sum(1 for g in grievances if g.get("status") in ("open", "in_progress"))
    grade = score_payment_reliability(paid, failed, disputed, grief)
    if grade is None:
        return None
    supabase.table("buyers").update({"payment_reliability": grade}).eq("id", buyer_id).execute()
    return grade
