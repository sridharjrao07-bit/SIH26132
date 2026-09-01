import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from supabase import create_client

from .config import get_settings
from ingestion.runner import IngestionRunner
from ingestion.data_gov_in import DataGovInAdapter

logger = structlog.get_logger()
settings = get_settings()

def get_supabase_client():
    # Use SERVICE ROLE KEY for background jobs to bypass RLS policies
    # so we can insert into tables like `ingestion_log` that are locked down.
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

async def run_ingestion_job():
    """Wrapper to run the ingestion process."""
    logger.info("scheduler_trigger_ingestion")
    supabase = get_supabase_client()
    
    # Initialize adapters
    # For now, data.gov.in is the primary adapter. 
    adapters = []
    if settings.data_gov_in_api_key and "your-data-gov-in-key" not in settings.data_gov_in_api_key:
        adapters.append(DataGovInAdapter(api_key=settings.data_gov_in_api_key))
    else:
        logger.warning("data_gov_in_api_key_missing", action="skipping data.gov.in adapter")
        
    if not adapters:
        logger.error("no_ingestion_adapters_configured")
        return
        
    runner = IngestionRunner(supabase=supabase, adapters=adapters)
    await runner.run(district=settings.target_district, state=settings.target_state)

def setup_scheduler() -> AsyncIOScheduler:
    """Sets up and returns the APScheduler instance with all background jobs."""
    scheduler = AsyncIOScheduler()
    
    # Ingestion Job
    scheduler.add_job(
        run_ingestion_job,
        trigger=IntervalTrigger(hours=settings.ingestion_interval_hours),
        id="ingestion_job",
        name="Daily Mandi Price Ingestion",
        replace_existing=True,
    )
    
    # Forecast Job (Placeholder for Stage 4)
    # scheduler.add_job(...)
    
    # Alerts Job (Placeholder for Stage 5)
    # scheduler.add_job(...)
    
    return scheduler
