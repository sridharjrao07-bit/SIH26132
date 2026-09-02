from fastapi import APIRouter, Depends, Query
from typing import List, Optional
from datetime import date, timedelta
from supabase import Client
from app.deps import get_supabase
from app.schemas import PriceResponse

router = APIRouter(prefix="/api/v1/prices", tags=["Prices"])

def _flatten(row: dict) -> dict:
    row = dict(row or {})
    market_data = row.pop("markets", {}) or {}
    commodity_data = row.pop("commodities", {}) or {}
    row["market_name"] = market_data.get("name")
    row["district"] = market_data.get("district")
    row["commodity_name_en"] = commodity_data.get("name_en")
    row["commodity_name_mr"] = commodity_data.get("name_mr")
    row["commodity_name_hi"] = commodity_data.get("name_hi")
    row.setdefault("unit", "quintal")
    row.setdefault("variety", "General")
    row.setdefault("grade", "General")
    return row

@router.get("/latest", response_model=List[PriceResponse])
def get_latest_prices(
    market_id: Optional[str] = Query(None, description="Filter by market ID"),
    commodity_id: Optional[str] = Query(None, description="Filter by commodity ID"),
    limit: int = Query(50, ge=1, le=500, description="Max records to return"),
    supabase: Client = Depends(get_supabase)
):
    """
    Get the latest price records.
    By default, fetches records from the last 7 days to ensure we capture the most recent ones.
    """
    seven_days_ago = (date.today() - timedelta(days=7)).isoformat()

    query = supabase.table("prices").select(
        "*, markets(name, district), commodities(name_en, name_mr, name_hi)"
    ).gte("arrival_date", seven_days_ago)

    if market_id:
        query = query.eq("market_id", market_id)
    if commodity_id:
        query = query.eq("commodity_id", commodity_id)

    res = query.order("arrival_date", desc=True).limit(limit).execute()
    return [_flatten(row) for row in (res.data or [])]


@router.get("/historical", response_model=List[PriceResponse])
def get_historical_prices(
    market_id: str = Query(..., description="Market ID"),
    commodity_id: str = Query(..., description="Commodity ID"),
    days: int = Query(30, ge=1, le=365, description="Number of days of history (1–365)"),
    limit: int = Query(1000, ge=1, le=1000, description="Max records to return"),
    supabase: Client = Depends(get_supabase)
):
    """
    Get historical prices for a specific market and commodity over a period of time.
    """
    start_date = (date.today() - timedelta(days=days)).isoformat()

    res = (supabase.table("prices").select(
        "*, markets(name, district), commodities(name_en, name_mr, name_hi)"
    )
    .eq("market_id", market_id)
    .eq("commodity_id", commodity_id)
    .gte("arrival_date", start_date)
    .order("arrival_date", desc=True)
    .limit(limit)
    .execute())

    return [_flatten(row) for row in (res.data or [])]
