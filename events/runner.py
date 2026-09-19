import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict

import structlog
from app.config import get_settings
from app.utils.tz import get_ist_today

from .base import EventSourceError
from .extractor import LLMEventExtractor, MockEventExtractor
from .sources import NewsFeedSource, PIBSource, SourceMode, StateBulletinsSource

logger = structlog.get_logger()

# Documents stuck in 'extracting' for longer than this are considered abandoned
# and eligible for retry.
EXTRACTING_STALE_MINUTES = 30


def _canonical_event_hash(comm_id, district, event_type: str, occurrence_date: date) -> str:
    """
    Deterministic, delimiter-safe hash for event identity within a source document.

    Identity fields:
      - commodity_id: UUID string or None
      - district: stripped and lowercased string or None
      - event_type: stripped and lowercased string
      - event_date: ISO date string (occurrence, not publication)

    Confidence, direction, and magnitude are NOT part of identity — they may be
    updated without creating a new event record.

    Two events from different source documents that share all identity fields
    are NOT considered the same event by this hash: uniqueness is enforced at
    the (source_document_id, event_hash) level, so each document retains its
    own independent provenance record.
    """
    identity = json.dumps({
        "commodity_id": str(comm_id) if comm_id else None,
        "district": (district or "").strip().lower() or None,
        "event_type": event_type.strip().lower(),
        "event_date": occurrence_date.isoformat(),
    }, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(identity.encode()).hexdigest()


async def run(supabase, since_days: int = 2) -> Dict[str, Any]:
    settings = get_settings()
    since_date = get_ist_today() - timedelta(days=since_days)

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

    # This determines provenance_mode written to source_documents.
    source_mode_str = settings.events_source_mode.lower()
    if source_mode_str == "fixture":
        mode = SourceMode.FIXTURE
    elif source_mode_str == "live":
        mode = SourceMode.LIVE
    else:
        mode = SourceMode.OFF

    provenance_mode = "fixture" if mode == SourceMode.FIXTURE else "live"

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
            for hl in headlines:
                all_headlines.append((source_name, hl))
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

    # 2. Pre-deduplicate: skip 'complete' documents. Re-queue 'failed' and
    #    stale 'extracting' documents (older than EXTRACTING_STALE_MINUTES).
    source_urls = [h.source_url for _, h in all_headlines]
    skip_urls: set = set()

    for i in range(0, len(source_urls), 100):
        chunk = source_urls[i:i + 100]
        try:
            resp = supabase.table("source_documents").select(
                "source_url, extraction_status, lease_expires_at"
            ).in_("source_url", chunk).execute()
            for row in resp.data:
                status = row.get("extraction_status")
                lease_str = row.get("lease_expires_at")
                if status == "complete":
                    skip_urls.add(row["source_url"])
                elif status == "extracting" and lease_str:
                    try:
                        lease_time = datetime.fromisoformat(lease_str.replace("Z", "+00:00"))
                        if lease_time > datetime.now(timezone.utc):
                            skip_urls.add(row["source_url"])
                    except ValueError:
                        pass
        except Exception as e:
            logger.error("event_runner_dedupe_error", error=str(e))

    new_headlines = [(src, h) for src, h in all_headlines if h.source_url not in skip_urls]

    # 3. Extract and Write (transactionally via RPC)
    new_written = 0
    quarantined = 0
    failed_docs = 0

    for source_name, headline in new_headlines:
        doc_id = None
        claim_token = None
        try:
            # Atomic Claim
            content_hash = hashlib.sha256((headline.headline + headline.raw_text).encode()).hexdigest()
            claim_resp = supabase.rpc("claim_source_document", {
                "p_source_url": headline.source_url,
                "p_source_name": source_name,
                "p_headline": headline.headline,
                "p_content_text": headline.raw_text,
                "p_published_at": headline.published_date.isoformat(),
                "p_provenance_mode": provenance_mode,
                "p_content_hash": content_hash
            }).execute()

            claim_data = claim_resp.data
            if not claim_data or claim_data.get("status") in ["already_complete", "lease_active"]:
                continue
                
            if claim_data.get("status") != "claimed":
                raise Exception(f"Unexpected claim status: {claim_data.get('status')}")

            doc_id = claim_data["document_id"]
            claim_token = claim_data["claim_token"]

            # Enforce immutable extraction snapshot
            snapshot_headline = claim_data.get("headline")
            snapshot_raw_text = claim_data.get("raw_text")
            snapshot_published_date = claim_data.get("publication_date")
            snapshot_content_hash = claim_data.get("content_hash")

            if snapshot_headline is None or snapshot_raw_text is None or snapshot_published_date is None or snapshot_content_hash is None:
                raise Exception("claim_source_document returned an incomplete snapshot")

            headline.headline = snapshot_headline
            headline.raw_text = snapshot_raw_text
            
            # publication_date comes as ISO string
            pub_dt = datetime.fromisoformat(snapshot_published_date.replace("Z", "+00:00"))
            headline.published_date = pub_dt.date() if hasattr(pub_dt, "date") else pub_dt

            events = await extractor.extract(headline)

            events_payload = []
            for evt in events:
                comm_id = None
                if evt.commodity_name:
                    comm_id = commodity_map.get(evt.commodity_name.lower())
                    if comm_id is None:
                        logger.warning(
                            "event_runner_unmapped_commodity",
                            commodity_name=evt.commodity_name,
                            source_url=headline.source_url,
                        )
                        quarantined += 1
                        continue

                occurrence_date = evt.event_date
                if occurrence_date is None:
                    logger.warning(
                        "event_runner_no_occurrence_date",
                        source_url=headline.source_url,
                        event_type=evt.event_type,
                        fallback="publication_date",
                    )
                    occurrence_date = headline.published_date

                event_hash = _canonical_event_hash(
                    comm_id=comm_id,
                    district=evt.district,
                    event_type=evt.event_type,
                    occurrence_date=occurrence_date,
                )

                events_payload.append({
                    "event_hash": event_hash,
                    "headline": headline.headline,
                    "event_date": occurrence_date.isoformat(),
                    "commodity_id": str(comm_id) if comm_id else None,
                    "district": evt.district,
                    "event_type": evt.event_type,
                    "direction": evt.direction,
                    "magnitude": evt.magnitude,
                    "confidence": float(evt.confidence),
                    "reasoning": evt.reasoning,
                    "raw_text": headline.raw_text,
                })

                if evt.confidence < 0.5:
                    quarantined += 1

            rpc_resp = supabase.rpc("publish_extracted_events_v2", {
                "p_doc_id": doc_id,
                "p_claim_token": claim_token,
                "p_extractor_version": extractor_name,
                "p_events": events_payload,
            }).execute()

            result_data = rpc_resp.data
            if not isinstance(result_data, dict):
                raise Exception("publish_extracted_events_v2 returned non-dictionary response")
                
            rpc_status = result_data.get("status")
            if rpc_status == "failed":
                logger.error("event_runner_publish_failed", doc_id=doc_id, reason=result_data.get("reason"))
                failed_docs += 1
                continue
            elif rpc_status != "complete":
                raise Exception(f"Publish RPC returned invalid status: {rpc_status}")
                
            written_count = result_data.get("written", 0)
            new_written += written_count
            logger.info("event_runner_doc_published", doc_id=doc_id, status=rpc_status, written=written_count)

        except Exception as e:
            failed_docs += 1
            logger.error("event_runner_extract_write_error", url=headline.source_url, error=str(e))
            if doc_id and claim_token:
                try:
                    supabase.rpc("report_extraction_failure", {
                        "p_doc_id": doc_id,
                        "p_claim_token": claim_token,
                        "p_reason": str(e)[:250]
                    }).execute()
                except Exception as ex:
                    logger.error("event_runner_report_failure_error", doc_id=doc_id, original_error=str(e), reporting_error=str(ex))

    return {
        "seen": seen,
        "new_written": new_written,
        "failed_docs": failed_docs,
        "quarantined": quarantined,
        "failed_sources": failed_sources,
        "extractor": extractor_name
    }
