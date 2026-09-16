import pytest
from datetime import datetime, timezone

from supabase import create_client
from app.config import get_settings

@pytest.fixture(scope="module")
def db_client():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key or settings.supabase_service_role_key == "placeholder":
        pytest.skip("Supabase credentials not available")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

def test_atomic_claim_and_retry(db_client):
    """
    Test that claim_source_document produces a claim_token, prevents double-claim,
    and handles retries if unfulfilled.
    """
    url = f"https://example.com/test-doc-{int(datetime.now(timezone.utc).timestamp())}"
    
    # 1. Claim
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": url,
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
        "p_source_url": url,
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
    
    # Verify status is failed
    doc = db_client.table("source_documents").select("extraction_status").eq("id", doc_id).execute().data[0]
    assert doc["extraction_status"] == "failed"
    
    # 4. Claim again (should succeed since it failed)
    resp3 = db_client.rpc("claim_source_document", {
        "p_source_url": url,
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

def test_publication_and_view_filtration(db_client):
    """
    Test that publish_extracted_events_v2 succeeds, creates events, 
    and that the live_events_published view correctly filters out fixtures.
    """
    url = f"https://example.com/test-doc-pub-{int(datetime.now(timezone.utc).timestamp())}"
    
    # 1. Claim as fixture
    resp = db_client.rpc("claim_source_document", {
        "p_source_url": url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline Pub",
        "p_content_text": "Test Content Pub",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash_pub"
    }).execute()
    
    doc_id = resp.data["document_id"]
    token = resp.data["claim_token"]
    
    # 2. Publish
    events_payload = [{
        "event_hash": "hash_evt_1",
        "headline": "Test Headline Pub",
        "event_date": datetime.now(timezone.utc).isoformat(),
        "district": "Pune",
        "event_type": "weather",
        "direction": "up",
        "magnitude": "high",
        "confidence": 0.9,
        "reasoning": "test reasoning",
        "raw_text": "Test Content Pub"
    }]
    
    pub_resp = db_client.rpc("publish_extracted_events_v2", {
        "p_doc_id": doc_id,
        "p_claim_token": token,
        "p_extractor_version": "test_ext_1",
        "p_events": events_payload
    }).execute()
    
    assert pub_resp.data["status"] == "complete"
    assert pub_resp.data["written"] == 1
    
    # 3. Verify in raw table
    raw = db_client.table("events").select("id").eq("source_document_id", doc_id).execute().data
    assert len(raw) == 1
    
    # 4. Verify NOT in live view (since it's a fixture)
    live = db_client.table("live_events_published").select("id").eq("source_document_id", doc_id).execute().data
    assert len(live) == 0
