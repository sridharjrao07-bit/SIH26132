import structlog
from datetime import date, timedelta
from typing import Dict, Any

from app.config import get_settings
from .base import EventSourceError
from .sources import PIBSource, NewsFeedSource, StateBulletinsSource, SourceMode
from .extractor import MockEventExtractor, LLMEventExtractor

logger = structlog.get_logger()

async def run(supabase, since_days: int = 2) -> Dict[str, Any]:
    settings = get_settings()
    since_date = date.today() - timedelta(days=since_days)
    
    # Fetch all commodities once to map names to UUIDs and configure extractors
    try:
        comm_resp = supabase.table("commodities").select("id, name_en").execute()
        commodity_map = {c["name_en"].lower(): c["id"] for c in comm_resp.data if c.get("name_en")}
    except Exception as e:
        logger.error("event_runner_commodity_fetch_error", error=str(e))
        commodity_map = {}
        
    valid_commodities = list(commodity_map.keys())
    
    # Initialize Extractor
    if settings.event_llm.lower() == "off" or not settings.event_llm_api_key:
        extractor = MockEventExtractor(valid_commodities=valid_commodities)
        extractor_name = "mock"
    else:
        extractor = LLMEventExtractor(
            api_key=settings.event_llm_api_key,
            base_url=settings.event_llm_base_url,
            model=settings.event_llm_model
        )
        extractor_name = f"llm:{settings.event_llm_provider}"
        
    logger.info("event_runner_starting", extractor=extractor_name, since_days=since_days)
    
    # Use FIXTURE mode for testing, OFF if events disabled, LIVE for prod
    if settings.app_env == "test":
        mode = SourceMode.FIXTURE
    elif not settings.event_job_enabled:
        mode = SourceMode.OFF
    else:
        mode = SourceMode.LIVE
        
    sources = [
        ("pib", PIBSource(mode=mode)),
        ("news", NewsFeedSource(mode=mode)),
        ("state_bulletins", StateBulletinsSource(mode=mode))
    ]
    
    failed_sources = []
    all_headlines = []
    
    # 1. Fetch Headlines
    for source_name, source_obj in sources:
        try:
            headlines = await source_obj.fetch_headlines(since_date)
            all_headlines.extend(headlines)
        except EventSourceError as e:
            logger.warning("event_source_failed", source=source_name, error=str(e))
            failed_sources.append(source_name)
        except Exception as e:
            logger.exception("event_source_unhandled_error", source=source_name, error=str(e))
            failed_sources.append(source_name)
            
    seen = len(all_headlines)
    if not all_headlines:
        return {
            "seen": 0,
            "new_written": 0,
            "quarantined": 0,
            "failed_sources": failed_sources,
            "extractor": extractor_name
        }
        
    # 2. Pre-deduplicate
    source_urls = [h.source_url for h in all_headlines]
    
    # Split into chunks of 100 to avoid giant IN clauses
    existing_urls = set()
    for i in range(0, len(source_urls), 100):
        chunk = source_urls[i:i+100]
        try:
            resp = supabase.table("events").select("source_url").in_("source_url", chunk).execute()
            for row in resp.data:
                existing_urls.add(row["source_url"])
        except Exception as e:
            logger.error("event_runner_dedupe_error", error=str(e))
            
    new_headlines = [h for h in all_headlines if h.source_url not in existing_urls]
    
    # 3. Extract and Write
    new_written = 0
    quarantined = 0
    
    # Extraction and write loop
        
    for headline in new_headlines:
        try:
            events = await extractor.extract(headline)
            for evt in events:
                comm_id = None
                if evt.commodity_name:
                    # A name was extracted — it must map to a known commodity.
                    # If it doesn't, the event is quarantined (not written as global).
                    comm_id = commodity_map.get(evt.commodity_name.lower())
                    if comm_id is None:
                        logger.warning(
                            "event_runner_unmapped_commodity",
                            commodity_name=evt.commodity_name,
                            source_url=headline.source_url,
                        )
                        quarantined += 1
                        continue
                # evt.commodity_name is None → genuinely global event; commodity_id stays NULL.

                row = {
                    "source_url": headline.source_url,
                    "headline": headline.headline,
                    "event_date": headline.published_date.isoformat(),
                    "commodity_id": comm_id,
                    "district": evt.district,
                    "event_type": evt.event_type,
                    "direction": evt.direction,
                    "magnitude": evt.magnitude,
                    "confidence": evt.confidence,
                    "reasoning": evt.reasoning,
                    "raw_text": headline.raw_text
                }

                # Write to database
                supabase.table("events").insert(row).execute()
                new_written += 1
                if evt.confidence < 0.5:
                    quarantined += 1
                    
        except Exception as e:
            logger.error("event_runner_extract_write_error", url=headline.source_url, error=str(e))

    return {
        "seen": seen,
        "new_written": new_written,
        "quarantined": quarantined,
        "failed_sources": failed_sources,
        "extractor": extractor_name
    }
