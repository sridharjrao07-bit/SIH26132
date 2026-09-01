import os
import structlog
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from supabase import create_client

from .config import get_settings
from ingestion.runner import IngestionRunner
from ingestion.data_gov_in import DataGovInAdapter

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


async def startup_catchup():
    """
    On boot: if the last successful ingestion run is older than the interval,
    run ingestion immediately rather than waiting for the first scheduled tick.
    10 lines of self-healing — critical for free-tier hosts that restart often.
    """
    try:
        supabase = get_supabase_client()
        resp = supabase.table("ingestion_log").select("run_at").eq(
            "status", "success"
        ).order("run_at", desc=True).limit(1).execute()

        if resp.data:
            last_run = datetime.fromisoformat(resp.data[0]["run_at"])
            cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.ingestion_interval_hours)
            if last_run > cutoff:
                logger.info("startup_catchup_skipped", last_run=str(last_run))
                return

        logger.info("startup_catchup_running", reason="no recent successful ingestion found")
        await run_ingestion_job()
    except Exception as e:
        logger.warning("startup_catchup_failed", error=str(e))


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

    # Ingestion Job — max_instances=1 prevents overlap; coalesce=True collapses
    # misfired ticks into one run; misfire_grace_time gives a 1h window.
    scheduler.add_job(
        run_ingestion_job,
        trigger=IntervalTrigger(hours=settings.ingestion_interval_hours),
        id="ingestion_job",
        name="Daily Mandi Price Ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    # Forecast Job (Stage 4 placeholder)
    # scheduler.add_job(run_forecast_job, ...)

    # Alerts Job (Stage 5 placeholder)
    # scheduler.add_job(run_alert_checker, ...)

    return scheduler
