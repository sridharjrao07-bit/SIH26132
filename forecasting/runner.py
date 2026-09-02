"""
forecasting/runner.py — Thin async wrapper for ForecastEngine.

The APScheduler job in app/jobs.py imports and schedules run_forecast_job().
This module also allows standalone triggering from admin endpoints or the CLI
without importing the full app stack.

Pattern mirrors ingestion/runner.py.
"""
import structlog
import asyncio
from supabase import create_client

from forecasting.engine import ForecastEngine

logger = structlog.get_logger()


def _get_supabase_client():
    """
    Service-role client for background jobs — bypasses RLS.
    Lazy import of app.config avoids circular imports when this module
    is used from outside the FastAPI app context.
    """
    from app.config import get_settings
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


async def run_forecast_job() -> dict:
    """
    Async entry point called by APScheduler (AsyncIOScheduler).

    ForecastEngine.run() is synchronous — all Supabase calls use the sync
    supabase-py client. To avoid blocking the event loop on the single-worker
    Render instance, we offload the sync run to a thread.
    """
    logger.info("scheduler_trigger_forecast")
    supabase = _get_supabase_client()
    
    lock_res = supabase.rpc("claim_job_lock", {"p_job_key": "forecast", "p_holder": "scheduler"}).execute()
    if not lock_res.data:
        logger.info("forecast_job_locked")
        return {"status": "locked"}
        
    try:
        engine   = ForecastEngine(supabase=supabase)
        summary  = await asyncio.to_thread(engine.run)
        logger.info("forecast_job_done", **summary)
        return summary
    finally:
        supabase.rpc("release_job_lock", {"p_job_key": "forecast", "p_holder": "scheduler"}).execute()
