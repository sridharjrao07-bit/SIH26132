import structlog
import asyncio
from typing import Optional
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from supabase import create_client

from .config import get_settings
from ingestion.runner import IngestionRunner
from ingestion.data_gov_in import DataGovInAdapter
from forecasting.runner import run_forecast_job

# We need a dedicated wrapper for alerts just like forecasting
async def run_alert_job():
    from app.config import get_settings
    from supabase import create_client
    import asyncio
    from notifications.alert_checker import AlertChecker
    
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)
    
    lock_res = supabase.rpc("claim_job_lock", {"p_job_key": "alert_check", "p_holder": "scheduler"}).execute()
    if not lock_res.data:
        logger.info("alert_job_locked")
        return {"status": "locked"}
        
    try:
        checker = AlertChecker(supabase)
        summary = await asyncio.to_thread(checker.run)
        logger.info("alert_job_done", **summary)
        return summary
    finally:
        supabase.rpc("release_job_lock", {"p_job_key": "alert_check", "p_holder": "scheduler"}).execute()

async def run_stale_forecasts_job():
    from app.config import get_settings
    from supabase import create_client
    import asyncio
    
    settings = get_settings()
    supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)
    
    lock_res = supabase.rpc("claim_job_lock", {"p_job_key": "mark_stale", "p_holder": "scheduler"}).execute()
    if not lock_res.data:
        return
        
    try:
        # Mark stale forecasts
        res = await asyncio.to_thread(supabase.rpc("mark_stale_forecasts").execute)
        logger.info("mark_stale_forecasts_done", count=res.data)
    finally:
        supabase.rpc("release_job_lock", {"p_job_key": "mark_stale", "p_holder": "scheduler"}).execute()


logger = structlog.get_logger()
settings = get_settings()


def get_supabase_client():
    """
    Service-role client for background jobs — bypasses RLS.
    NEVER share this client with the FastAPI request handlers.
    """
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


async def run_ingestion_job():
    """Orchestrates one full ingestion run across all configured adapters."""
    logger.info("scheduler_trigger_ingestion")
    supabase = get_supabase_client()

    adapters = []

    # Primary: data.gov.in
    if settings.data_gov_in_api_key and "your-data-gov-in-key" not in settings.data_gov_in_api_key:
        adapters.append(DataGovInAdapter(api_key=settings.data_gov_in_api_key))
    else:
        logger.warning("data_gov_in_api_key_missing", action="skipping data.gov.in adapter")

    # Optional fallback: Agmarknet (Selenium) — requires Chrome + chromedriver
    # Disabled by default; set ENABLE_AGMARKNET=1 in .env to activate.
    if settings.enable_agmarknet:
        try:
            from ingestion.agmarknet import AgmarknetAdapter
            adapters.append(AgmarknetAdapter())
            logger.info("agmarknet_adapter_enabled")
        except ImportError as e:
            logger.warning("agmarknet_import_failed", error=str(e))

    if not adapters:
        logger.error("no_ingestion_adapters_configured")
        return

    runner = IngestionRunner(supabase=supabase, adapters=adapters)
    await runner.run(district=settings.target_district, state=settings.target_state)


async def _run_catchup_task():
    """
    Internal coroutine: checks whether ingestion is stale and fires a catch-up run.
    Called exclusively via asyncio.create_task — never awaited directly at startup
    so it does NOT block the API from becoming ready.
    """
    try:
        supabase = get_supabase_client()
        resp = supabase.table("ingestion_log").select("run_at").eq(
            "status", "success"
        ).order("run_at", desc=True).limit(1).execute()

        if resp.data:
            last_run_str = resp.data[0]["run_at"]
            # Supabase returns UTC ISO strings; normalize to aware datetime
            last_run = datetime.fromisoformat(
                last_run_str.replace("Z", "+00:00")
            )
            cutoff = datetime.now(timezone.utc) - timedelta(
                hours=settings.ingestion_interval_hours
            )
            if last_run > cutoff:
                logger.info("startup_catchup_skipped", last_run=str(last_run))
                return

        logger.info("startup_catchup_running",
                    reason="no recent successful ingestion found")
        await run_ingestion_job()
        await run_forecast_job()

    except Exception as e:
        # Catch-up is best-effort: log and continue. API is already serving.
        logger.warning("startup_catchup_failed", error=str(e))


def schedule_startup_catchup():
    """
    Schedule the catch-up check as a fire-and-forget background task.
    Call this from main.py's lifespan handler AFTER the scheduler has started:

        asyncio.create_task is used internally so the API starts immediately
        without waiting for the first ingestion run to complete.

    Race condition note: if the host restarts exactly when the interval fires,
    the scheduled job and the catch-up task could both run.  The upsert ON
    CONFLICT clause makes a double-fetch harmless for data correctness, but it
    does burn API quota.  For Stage 5 (alerts), we will add a pg_try_advisory_lock
    to prevent the alert-checker from firing twice.
    """
    import asyncio
    asyncio.create_task(_run_catchup_task())


def setup_scheduler() -> AsyncIOScheduler:
    """
    Sets up and returns the APScheduler instance.

    SCHEDULER GUARD: uvicorn --reload spawns a reloader process + a worker;
    both call this function → 2 schedulers → double ingestion + double SMS.
    We check RUN_SCHEDULER (mapped from settings) to prevent this.
    In production, start with:  uvicorn app.main:app --workers 1
    In dev, set RUN_SCHEDULER=0 in .env when using --reload.
    """
    if not settings.run_scheduler:
        logger.warning("scheduler_disabled", reason="RUN_SCHEDULER=0 in env")
        return None

    scheduler = AsyncIOScheduler()

    # Jobs run at configurable intervals, staggered so the cascade completes
    # before the next stage reads:
    #   T+0  : Ingestion  (runs every ingestion_interval_hours)
    #   T+5m : Forecast   (runs after ingestion settles)
    #   T+10m: Alerts     (runs after fresh prices are in)
    #   T+15m: Stale mark (housekeeping, same cadence as forecast)
    # Job-lock TTL (15 min) handles overlap if a run exceeds its interval.
    now = datetime.now(timezone.utc)

    scheduler.add_job(
        run_ingestion_job,
        IntervalTrigger(
            hours=settings.ingestion_interval_hours,
            start_date=now,
        ),
        id="ingestion",
        name="Source Data Ingestion",
        replace_existing=True,
    )

    scheduler.add_job(
        run_forecast_job,
        IntervalTrigger(
            hours=settings.forecast_interval_hours,
            start_date=now + timedelta(minutes=5),
        ),
        id="forecast",
        name="Forecast Generation",
        replace_existing=True,
    )

    scheduler.add_job(
        run_alert_job,
        IntervalTrigger(
            minutes=settings.alert_check_interval_minutes,
            start_date=now + timedelta(minutes=10),
        ),
        id="alerts",
        name="Alert SMS Dispatch",
        replace_existing=True,
    )

    scheduler.add_job(
        run_stale_forecasts_job,
        IntervalTrigger(
            hours=settings.forecast_interval_hours,
            start_date=now + timedelta(minutes=15),
        ),
        id="stale_forecasts",
        name="Mark Stale Forecasts",
        replace_existing=True,
    )

    return scheduler
