from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from supabase import Client
from app.auth import require_role
from app.deps import get_supabase_service_role
from pathlib import Path
from collections import defaultdict

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
    res = supabase.table("ingestion_log").select("*").order("run_at", desc=True).limit(10).execute()
    return res.data


@router.get("/dashboard/api/forecast-stats", dependencies=[Depends(require_role("admin"))])
async def get_forecast_stats(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only API to fetch forecast performance stats (one prices query, not N+1)."""
    forecasts = (
        supabase.table("forecasts")
        .select("*, commodities(name_en), markets(name)")
        .order("forecast_date", desc=True)
        .limit(50)
        .execute()
    )

    price_rows = (
        supabase.table("prices")
        .select("market_id, commodity_id, arrival_date, modal_price")
        .limit(2000)
        .execute()
        .data
        or []
    )
    by_pair = defaultdict(list)
    for p in price_rows:
        by_pair[(p["market_id"], p["commodity_id"])].append(p)
    for key in by_pair:
        by_pair[key].sort(key=lambda r: str(r.get("arrival_date") or ""))

    stats = []
    for f in forecasts.data or []:
        market_id = f["market_id"]
        commodity_id = f["commodity_id"]
        target_date = f["forecast_date"]

        candidates = [
            p for p in by_pair.get((market_id, commodity_id), [])
            if str(p.get("arrival_date") or "") >= str(target_date)
        ]
        actual_price = candidates[0]["modal_price"] if candidates else None

        within_bounds = None
        if actual_price is not None and f["lower_bound"] is not None and f["upper_bound"] is not None:
            within_bounds = (f["lower_bound"] <= actual_price <= f["upper_bound"])

        stats.append({
            "id": f.get("id"),
            "date": target_date,
            "market": (f.get("markets") or {}).get("name"),
            "commodity": (f.get("commodities") or {}).get("name_en"),
            "predicted": f["predicted_price"],
            "lower": f["lower_bound"],
            "upper": f["upper_bound"],
            "confidence": f.get("confidence"),
            "actual": actual_price,
            "hit": within_bounds,
        })

    return stats
