from fastapi import APIRouter, Depends
from supabase import Client
import structlog
import asyncio

from app.auth import require_role
from app.deps import get_supabase_service_role

from forecasting.engine import ForecastEngine
from notifications.alert_checker import AlertChecker

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])

@router.post("/forecast/run", dependencies=[Depends(require_role("admin"))])
async def trigger_forecast(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only on-demand trigger for forecasting (bypasses cron)."""
    
    # Claim lock so we don't race the cron
    lock_res = supabase.rpc("claim_job_lock", {"p_job_key": "forecast", "p_holder": "admin_trigger"}).execute()
    if not lock_res.data:
        return {"status": "locked", "message": "Job is currently running"}
        
    try:
        engine = ForecastEngine(supabase)
        summary = await asyncio.to_thread(engine.run)
        return {"status": "success", "summary": summary}
    finally:
        supabase.rpc("release_job_lock", {"p_job_key": "forecast", "p_holder": "admin_trigger"}).execute()

@router.post("/alert-check/run", dependencies=[Depends(require_role("admin"))])
async def trigger_alert_check(supabase: Client = Depends(get_supabase_service_role)):
    """Admin-only on-demand trigger for alert checker (bypasses cron)."""
    
    lock_res = supabase.rpc("claim_job_lock", {"p_job_key": "alert_check", "p_holder": "admin_trigger"}).execute()
    if not lock_res.data:
        return {"status": "locked", "message": "Job is currently running"}
        
    try:
        checker = AlertChecker(supabase)
        summary = await asyncio.to_thread(checker.run)
        return {"status": "success", "summary": summary}
    finally:
        supabase.rpc("release_job_lock", {"p_job_key": "alert_check", "p_holder": "admin_trigger"}).execute()
