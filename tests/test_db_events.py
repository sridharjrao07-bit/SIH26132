import os
import pytest
import uuid
from datetime import datetime, timezone

from supabase import create_client
from app.config import get_settings

def is_db_integration_enabled():
    return os.environ.get("ENABLE_DB_INTEGRATION_TESTS", "0") == "1"

@pytest.fixture(scope="module")
def db_client():
    if not is_db_integration_enabled():
        pytest.skip("ENABLE_DB_INTEGRATION_TESTS not set")
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key or settings.supabase_service_role_key == "placeholder":
        pytest.skip("Supabase credentials not available")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

@pytest.fixture
def unique_url():
    return f"https://example.com/test-doc-{uuid.uuid4()}"

def test_obsolete_publisher_removed(db_client):
    with pytest.raises(Exception) as exc:
        db_client.rpc("publish_extracted_events", {
            "document_id": str(uuid.uuid4()),
            "events_json": "[]",
            "metadata": {}
        }).execute()
    assert "Could not find" in str(exc.value)

def test_atomic_claim_and_retry(db_client, unique_url):
    # 1. Claim
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": unique_url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline",
        "p_content_text": "Test Content",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash123"
    }).execute()
    
    assert resp1.data
    assert resp1.data["status"] == "claimed"
    doc_id = resp1.data["document_id"]
    token1 = resp1.data["claim_token"]
    
    # 2. Try to claim again immediately
    resp2 = db_client.rpc("claim_source_document", {
        "p_source_url": unique_url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline",
        "p_content_text": "Test Content",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash123"
    }).execute()
    
    assert resp2.data["status"] == "lease_active"
    
    # 3. Report failure
    db_client.rpc("report_extraction_failure", {
        "p_doc_id": doc_id,
        "p_claim_token": token1,
        "p_reason": "test error"
    }).execute()
    
    doc = db_client.table("source_documents").select("extraction_status").eq("id", doc_id).execute().data[0]
    assert doc["extraction_status"] == "failed"
    
    # 4. Claim again
    resp3 = db_client.rpc("claim_source_document", {
        "p_source_url": unique_url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline",
        "p_content_text": "Test Content",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash123"
    }).execute()
    
    assert resp3.data["status"] == "claimed"
    token3 = resp3.data["claim_token"]
    assert token1 != token3

def test_expired_claim_reclaimed_and_old_worker_isolated(db_client, unique_url):
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": unique_url,
        "p_source_name": "test_script",
        "p_headline": "Test",
        "p_content_text": "Test",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "hash"
    }).execute()
    doc_id = resp1.data["document_id"]
    token1 = resp1.data["claim_token"]

    # manually expire lease
    db_client.table("source_documents").update({"lease_expires_at": "2020-01-01T00:00:00Z"}).eq("id", doc_id).execute()

    # new worker claims
    resp2 = db_client.rpc("claim_source_document", {
        "p_source_url": unique_url,
        "p_source_name": "test_script",
        "p_headline": "Test",
        "p_content_text": "Test",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "hash"
    }).execute()
    assert resp2.data["status"] == "claimed"
    
    # old worker tries to publish
    with pytest.raises(Exception) as exc:
        db_client.rpc("publish_extracted_events_v2", {
            "p_doc_id": doc_id,
            "p_claim_token": token1,
            "p_extractor_version": "v1",
            "p_events": []
        }).execute()
    assert "invalid claim token" in str(exc.value)

def test_invalid_event_rolls_back_batch(db_client, unique_url):
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": unique_url,
        "p_source_name": "test",
        "p_headline": "test",
        "p_content_text": "test",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "hash"
    }).execute()
    doc_id = resp1.data["document_id"]
    token = resp1.data["claim_token"]

    events = [
        {
            "event_hash": "hash1",
            "headline": "valid",
            "event_date": datetime.now(timezone.utc).isoformat(),
            "district": "Pune",
            "event_type": "weather",
            "direction": "up",
            "magnitude": "high",
            "confidence": 0.9,
            "reasoning": "test",
            "raw_text": "test"
        },
        {
            "event_hash": "hash2",
            "headline": "invalid_date",
            "event_date": "not-a-date",
            "district": "Pune",
            "event_type": "weather",
            "direction": "up",
            "magnitude": "high",
            "confidence": 0.9,
            "reasoning": "test",
            "raw_text": "test"
        }
    ]

    with pytest.raises(Exception):
        db_client.rpc("publish_extracted_events_v2", {
            "p_doc_id": doc_id,
            "p_claim_token": token,
            "p_extractor_version": "v1",
            "p_events": events
        }).execute()

    # ensure first event wasn't saved (rollback)
    saved = db_client.table("events").select("id").eq("source_document_id", doc_id).execute().data
    assert len(saved) == 0

def test_live_view_filters_and_fields(db_client, unique_url):
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": unique_url,
        "p_source_name": "test",
        "p_headline": "live",
        "p_content_text": "live",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "live",
        "p_content_hash": "hash_live"
    }).execute()
    doc_id = resp1.data["document_id"]
    token = resp1.data["claim_token"]

    db_client.rpc("publish_extracted_events_v2", {
        "p_doc_id": doc_id,
        "p_claim_token": token,
        "p_extractor_version": "v1",
        "p_events": [{
            "event_hash": "hash1",
            "headline": "valid",
            "event_date": datetime.now(timezone.utc).isoformat(),
            "district": "Pune",
            "event_type": "weather",
            "direction": "up",
            "magnitude": "high",
            "confidence": 0.9,
            "reasoning": "test",
            "raw_text": "test"
        }]
    }).execute()

    # Check live_events_published
    live = db_client.table("live_events_published").select("*").eq("source_document_id", doc_id).execute().data
    assert len(live) == 1
    assert live[0]["provenance_mode"] == "live"
    assert live[0]["extraction_status"] == "complete"
    assert "publication_date" in live[0]

    # Test loader compatibility
    from events.loader import load_published_events
    events = load_published_events(db_client, district="Pune")
    assert any(e["source_document_id"] == doc_id for e in events)

    # Check sale_window_headlines view (as anon using a different client or just checking if it exists)
    sw = db_client.table("sale_window_headlines").select("*").eq("district", "Pune").execute().data
    assert len(sw) > 0
