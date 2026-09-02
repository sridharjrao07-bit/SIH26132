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

logger = structlog.get_logger()
settings = get_settings()


def get_supabase_client():
    """
    Service-role client for background jobs — bypasses RLS.
    NEVER share this client with the FastAPI request handlers.
    """
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def _claim(supabase, job_key: str, holder: str = "scheduler", ttl_minutes: int = 45):
    # Default 45 min > worst-case ingest/alert runtime so TTL-steal cannot
    # double-send SMS while the first holder is still in gateway.send_sms.
    return supabase.rpc(
        "claim_job_lock",
        {"p_job_key": job_key, "p_holder": holder, "p_ttl_minutes": ttl_minutes},
    ).execute()


def _release(supabase, job_key: str, holder: str = "scheduler"):
    supabase.rpc("release_job_lock", {"p_job_key": job_key, "p_holder": holder}).execute()


async def run_alert_job():
    from notifications.alert_checker import AlertChecker

    supabase = get_supabase_client()
    lock_res = _claim(supabase, "alert_check")
    if not lock_res.data:
        logger.info("alert_job_locked")
        return {"status": "locked"}

    try:
        checker = AlertChecker(supabase)
        summary = await asyncio.to_thread(checker.run)
        logger.info("alert_job_done", **summary)
        return summary
    finally:
        _release(supabase, "alert_check")


async def run_stale_forecasts_job():
    supabase = get_supabase_client()
    lock_res = _claim(supabase, "mark_stale")
    if not lock_res.data:
        return

    try:
        res = await asyncio.to_thread(
            lambda: supabase.rpc("mark_stale_forecasts").execute()
        )
        logger.info("mark_stale_forecasts_done", count=res.data)
    finally:
        _release(supabase, "mark_stale")


async def run_expire_offers_job():
    """Hourly: pending digital offers older than 48h become expired."""
    from app.marketplace import expire_stale_offers

    supabase = get_supabase_client()
    lock_res = _claim(supabase, "expire_offers")
    if not lock_res.data:
        logger.info("expire_offers_job_locked")
        return {"status": "locked"}
    try:
        summary = await asyncio.to_thread(expire_stale_offers, supabase)
        logger.info("expire_offers_job_done", **{k: v for k, v in summary.items() if k != "offer_ids"})
        return summary
    finally:
        _release(supabase, "expire_offers")


async def run_ingestion_job():
    """Orchestrates one full ingestion run across all configured adapters."""
    logger.info("scheduler_trigger_ingestion")
    supabase = get_supabase_client()

    lock_res = _claim(supabase, "ingestion")
    if not lock_res.data:
        logger.info("ingestion_job_locked")
        return {"status": "locked"}

    try:
        adapters = []

        if settings.data_gov_in_api_key and "your-data-gov-in-key" not in settings.data_gov_in_api_key:
            adapters.append(DataGovInAdapter(api_key=settings.data_gov_in_api_key))
        else:
            logger.warning("data_gov_in_api_key_missing", action="skipping data.gov.in adapter")

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
    finally:
        _release(supabase, "ingestion")


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
        logger.warning("startup_catchup_failed", error=str(e))


def schedule_startup_catchup():
    import asyncio
    asyncio.create_task(_run_catchup_task())


def setup_scheduler() -> Optional[AsyncIOScheduler]:
    if not settings.run_scheduler:
        logger.warning("scheduler_disabled", reason="RUN_SCHEDULER=0 in env")
        return None

    scheduler = AsyncIOScheduler()
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

    scheduler.add_job(
        run_expire_offers_job,
        IntervalTrigger(hours=1, start_date=now + timedelta(minutes=20)),
        id="expire_offers",
        name="Expire Stale Offers",
        replace_existing=True,
    )

    return scheduler
