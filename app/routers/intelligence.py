"""Sale-window recommendation — localised hold/sell advice (SIH26132)."""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, Literal
from supabase import Client
from app.deps import get_supabase, get_supabase_service_role
from notifications.sale_window import compute_sale_window, apply_sale_language
from datetime import date, timedelta

router = APIRouter(prefix="/api/v1/sale-window", tags=["Intelligence"])


@router.get("/")
def sale_window(
    commodity_id: str = Query(...),
    market_id: Optional[str] = Query(None),
    lang: Literal["en", "mr", "hi"] = Query("en"),
    supabase: Client = Depends(get_supabase),
    supabase_admin: Client = Depends(get_supabase_service_role),
):
    today = date.today()
    evt_resp = (
        supabase_admin.table("events")
        .select("headline, event_date, commodity_id, district")
        .gte("confidence", 0.5)
        .gte("event_date", (today - timedelta(days=7)).isoformat())
        .order("event_date", desc=True)
        .limit(20)
        .execute()
    )
    result = compute_sale_window(supabase, commodity_id, market_id, recent_events=evt_resp.data or [])
    if not result:
        raise HTTPException(404, "no recent prices for this commodity")
    return apply_sale_language(result, lang)
