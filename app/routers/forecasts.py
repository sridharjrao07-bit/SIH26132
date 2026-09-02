from fastapi import APIRouter, Depends, Query, HTTPException
from typing import List, Optional
from datetime import date, timedelta, datetime
from supabase import Client

from app.deps import get_supabase
from app.schemas import ForecastResponse

router = APIRouter(prefix="/api/v1/forecasts", tags=["Forecasts"])


def _flatten_forecast(row: dict) -> dict:
    """Flatten joined markets and commodities fields for the Pydantic schema."""
    market_data = row.pop("markets", {}) or {}
    commodity_data = row.pop("commodities", {}) or {}
    row["market_name"] = market_data.get("name")
    row["district"] = market_data.get("district")
    row["commodity_name_en"] = commodity_data.get("name_en")
    row["commodity_name_mr"] = commodity_data.get("name_mr")
    row["commodity_name_hi"] = commodity_data.get("name_hi")
    return row


@router.get("", response_model=List[ForecastResponse])
def get_forecasts(
    market_id: str = Query(..., description="Filter by market ID"),
    commodity_id: str = Query(..., description="Filter by commodity ID"),
    days: int = Query(7, ge=1, le=7, description="Number of days ahead to fetch"),
    supabase: Client = Depends(get_supabase)
):
    """
    Get the price forecasts for a specific market and commodity pair.
    Returns the next `days` of forward predictions.
    """
    today = date.today().isoformat()
    end_date = (date.today() + timedelta(days=days - 1)).isoformat()

    res = (
        supabase.table("forecasts")
        .select("*, markets(name, district), commodities(name_en, name_mr, name_hi)")
        .eq("market_id", market_id)
        .eq("commodity_id", commodity_id)
        .gte("forecast_date", today)
        .lte("forecast_date", end_date)
        .order("forecast_date", desc=False)
        .execute()
    )

    return [_flatten_forecast(row) for row in res.data]


@router.get("/summary", response_model=List[ForecastResponse])
def get_forecasts_summary(
    supabase: Client = Depends(get_supabase)
):
    """
    Get the latest summary of forecasts for all active market/commodity pairs.
    Deduplicates in Python to show only the most recent generation run per pair.
    """
    # Fetch recent forecasts (2000 is enough to cover all pairs × 7 days for latest run)
    cutoff = (datetime.utcnow() - timedelta(days=2)).isoformat()
    res = (
        supabase.table("forecasts")
        .select("*, markets(name, district), commodities(name_en, name_mr, name_hi)")
        .gte("generated_at", cutoff)
        .order("generated_at", desc=True)
        .limit(2000)
        .execute()
    )

    # Deduplicate in Python (Supabase/PostgREST lacks GROUP BY)
    seen_pairs = set()
    summary = []

    for row in res.data:
        pair_key = (row["market_id"], row["commodity_id"])
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            summary.append(_flatten_forecast(row))

    return summary
