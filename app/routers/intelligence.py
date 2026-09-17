"""Sale-window recommendation — localised hold/sell advice (SIH26132)."""
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, Literal
from supabase import Client
from app.deps import get_supabase
from notifications.sale_window import compute_sale_window, apply_sale_language

router = APIRouter(prefix="/api/v1/sale-window", tags=["Intelligence"])


@router.get("/")
def sale_window(
    commodity_id: str = Query(...),
    market_id: Optional[str] = Query(None),
    lang: Literal["en", "mr", "hi"] = Query("en"),
    supabase: Client = Depends(get_supabase),
):
    result = compute_sale_window(supabase, commodity_id, market_id)
    if not result:
        raise HTTPException(404, "no recent prices for this commodity")
    return apply_sale_language(result, lang)
