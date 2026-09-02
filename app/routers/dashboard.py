from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from supabase import Client
from typing import Dict, Any
from app.auth import get_current_user, require_role
from app.deps import get_supabase_service_role
from pathlib import Path

# Anchored to PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))

router = APIRouter(tags=["dashboard"])

@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Public HTML shell (data is fetched securely via API)"""
    return templates.TemplateResponse(request, "dashboard.html", {"request": request})

@router.get("/dashboard/api/ingestion-logs", dependencies=[Depends(require_role("admin"))])
async def get_ingestion_logs(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only API to fetch recent ingestion logs"""
    res = supabase.table("ingestion_log").select("*").order("start_time", desc=True).limit(10).execute()
    return res.data

@router.get("/dashboard/api/forecast-stats", dependencies=[Depends(require_role("admin"))])
async def get_forecast_stats(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only API to fetch forecast performance stats"""
    # Fetch recent forecasts
    forecasts = supabase.table("forecasts").select("*, commodities(name_en), markets(name)").order("forecast_date", desc=True).limit(50).execute()
    
    # We will fetch prices to evaluate hits
    stats = []
    for f in forecasts.data:
        market_id = f["market_id"]
        commodity_id = f["commodity_id"]
        target_date = f["forecast_date"]
        
        # Check actual price
        price_res = supabase.table("prices").select("modal_price").eq("market_id", market_id).eq("commodity_id", commodity_id).gte("arrival_date", target_date).order("arrival_date", desc=False).limit(1).execute()
        
        actual_price = price_res.data[0]["modal_price"] if price_res.data else None
        within_bounds = None
        
        stats.append({
            "id": f["id"],
            "date": target_date,
            "market": (f.get("markets") or {}).get("name"),
            "commodity": (f.get("commodities") or {}).get("name_en"),
            "predicted": f["predicted_price"],
            "lower": f["lower_bound"],
            "upper": f["upper_bound"],
            "confidence": f["confidence_tier"],
            "actual": actual_price,
            "hit": within_bounds
        })
        
    return stats
