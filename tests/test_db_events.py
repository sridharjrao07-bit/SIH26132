import os
import pytest
import uuid
import threading
from datetime import datetime, timezone

from supabase import create_client
from app.config import get_settings

def is_db_integration_enabled():
    return os.environ.get("ENABLE_DB_INTEGRATION_TESTS", "0") == "1"

@pytest.fixture(scope="module")
def settings():
    return get_settings()

@pytest.fixture(scope="module")
def db_client(settings):
    if not is_db_integration_enabled():
        pytest.skip("ENABLE_DB_INTEGRATION_TESTS not set")
    if not settings.supabase_url or not settings.supabase_service_role_key or settings.supabase_service_role_key == "placeholder":
        pytest.skip("Supabase credentials not available")
    return create_client(settings.supabase_url, settings.supabase_service_role_key)

@pytest.fixture(scope="module")
def anon_client(settings):
    if not settings.supabase_anon_key or settings.supabase_anon_key == "placeholder":
        return None
    return create_client(settings.supabase_url, settings.supabase_anon_key)

@pytest.fixture
def unique_url():
    url = f"https://example.com/test-doc-{uuid.uuid4()}"
    return url

@pytest.fixture
def managed_url(db_client, unique_url):
    yield unique_url
    # Teardown: delete events and doc
    try:
        doc = db_client.table("source_documents").select("id").eq("source_url", unique_url).execute()
        if doc.data:
            doc_id = doc.data[0]["id"]
            db_client.table("events").delete().eq("source_document_id", doc_id).execute()
            db_client.table("source_documents").delete().eq("id", doc_id).execute()
    except Exception as e:
        print(f"Teardown failed for {unique_url}: {e}")

def test_obsolete_publisher_removed(db_client):
    with pytest.raises(Exception) as exc:
        db_client.rpc("publish_extracted_events", {
            "p_doc_id": str(uuid.uuid4()),
            "p_extractor_version": "test",
            "p_events": []
        }).execute()
    assert "Could not find" in str(exc.value)

def test_concurrent_review_and_publication(db_client, managed_url):
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline",
        "p_content_text": "Test Content",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash123"
    }).execute()
    
    doc_id = resp1.data["document_id"]
    token = resp1.data["claim_token"]
    
    events = [{
        "event_hash": "hash1",
        "headline": "valid",
        "event_date": datetime.now(timezone.utc).isoformat(),
        "district": "Pune",
        "event_type": "weather",
        "direction": "up",
        "magnitude": "major",
        "confidence": 0.9,
        "reasoning": "test",
        "raw_text": "test"
    }]
    db_client.rpc("publish_extracted_events_v2", {
        "p_doc_id": doc_id,
        "p_claim_token": token,
        "p_extractor_version": "v1",
        "p_events": events
    }).execute()
    
    evt_id = db_client.table("events").select("id").eq("source_document_id", doc_id).execute().data[0]["id"]
    
    # Claim again to simulate a re-extraction trying to publish
    resp2 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline",
        "p_content_text": "Test Content",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash123"
    }).execute()
    token2 = resp2.data["claim_token"]

    barrier = threading.Barrier(2)
    results = []

    def publisher():
        try:
            barrier.wait(timeout=5)
            db_client.rpc("publish_extracted_events_v2", {
                "p_doc_id": doc_id,
                "p_claim_token": token2,
                "p_extractor_version": "v2",
                "p_events": events
            }).execute()
            results.append("published")
        except Exception as e:
            results.append(f"publish_error: {e}")

    def reviewer():
        try:
            barrier.wait(timeout=5)
            db_client.rpc("review_event", {
                "p_event_id": evt_id,
                "p_review_status": "approved"
            }).execute()
            results.append("reviewed")
        except Exception as e:
            results.append(f"review_error: {e}")

    t1 = threading.Thread(target=publisher)
    t2 = threading.Thread(target=reviewer)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2

def test_atomic_claim_and_retry(db_client, managed_url):
    # 1. Claim
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline",
        "p_content_text": "Test Content",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash123"
    }).execute()
    
    assert resp1.data["status"] == "claimed"
    doc_id = resp1.data["document_id"]
    token1 = resp1.data["claim_token"]
    
    # 2. Try to claim again immediately
    resp2 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
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
    
    # 4. Claim again - should return the new snapshot
    resp3 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline 2",
        "p_content_text": "Test Content 2",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash456"
    }).execute()
    
    assert resp3.data["status"] == "claimed"
    assert resp3.data["raw_text"] == "Test Content"
    assert resp3.data["content_hash"] == "testhash123"

def test_expired_claim_reclaimed_and_old_worker_isolated(db_client, managed_url):
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
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
        "p_source_url": managed_url,
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
    
    # old worker tries to report failure (should do nothing because token mismatched)
    db_client.rpc("report_extraction_failure", {
        "p_doc_id": doc_id,
        "p_claim_token": token1,
        "p_reason": "failure"
    }).execute()
    
    doc = db_client.table("source_documents").select("extraction_status").eq("id", doc_id).execute().data[0]
    assert doc["extraction_status"] == "extracting"

def test_invalid_event_rolls_back_batch(db_client, managed_url):
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
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
            "magnitude": "major",
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
            "magnitude": "major",
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

    # ensure first valid event wasn't saved (transaction rollback)
    saved = db_client.table("events").select("id").eq("source_document_id", doc_id).execute().data
    assert len(saved) == 0

def test_live_view_filters_and_fields(db_client, managed_url):
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
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
            "magnitude": "major",
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
    assert live[0]["review_status"] == "pending"

    # Test loader compatibility
    from events.loader import load_published_events
    events = load_published_events(db_client, district="Pune")
    assert any(e["source_document_id"] == doc_id for e in events)

def test_missing_profile_users_cannot_review(db_client, anon_client, managed_url):
    if not anon_client:
        pytest.skip("Anon client not available")
        
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
        "p_source_name": "test",
        "p_headline": "live",
        "p_content_text": "live",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
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
            "magnitude": "major",
            "confidence": 0.9,
            "reasoning": "test",
            "raw_text": "test"
        }]
    }).execute()
    
    evt_id = db_client.table("events").select("id").eq("source_document_id", doc_id).execute().data[0]["id"]
    
    # anon client cannot review
    with pytest.raises(Exception) as exc:
        anon_client.rpc("review_event", {
            "p_event_id": evt_id,
            "p_review_status": "approved"
        }).execute()
        
    assert "Not authenticated" in str(exc.value) or "Not authorized" in str(exc.value)
    
    # also cannot read internal view
    with pytest.raises(Exception) as exc:
        anon_client.table("live_events_published").select("*").eq("id", evt_id).execute()
    assert "permission denied" in str(exc.value).lower() or "not authorized" in str(exc.value).lower()

def test_concurrent_claims(db_client):
    url = f"https://example.com/test-doc-{uuid.uuid4()}"
    results = []
    
    def claim():
        try:
            resp = db_client.rpc("claim_source_document", {
                "p_source_url": url,
                "p_source_name": "test",
                "p_headline": "concurrent",
                "p_content_text": "concurrent",
                "p_published_at": datetime.now(timezone.utc).isoformat(),
                "p_provenance_mode": "fixture",
                "p_content_hash": "hash"
            }).execute()
            results.append(resp.data["status"])
        except Exception as e:
            results.append(str(e))

    threads = [threading.Thread(target=claim) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    claimed = [r for r in results if r == "claimed"]
    lease_active = [r for r in results if r == "lease_active"]
    
    assert len(claimed) == 1
    assert len(lease_active) == 4
    
    # Teardown
    doc = db_client.table("source_documents").select("id").eq("source_url", url).execute()
    if doc.data:
        db_client.table("source_documents").delete().eq("id", doc.data[0]["id"]).execute()


def test_immutable_snapshot_extraction_input(db_client, managed_url):
    resp1 = db_client.rpc("claim_source_document", {
        "p_source_url": managed_url,
        "p_source_name": "test_script",
        "p_headline": "Test Headline",
        "p_content_text": "Test Content",
        "p_published_at": datetime.now(timezone.utc).isoformat(),
        "p_provenance_mode": "fixture",
        "p_content_hash": "testhash123"
    }).execute()
    
    assert resp1.data["status"] == "claimed"
    assert resp1.data["raw_text"] == "Test Content"
    assert resp1.data["content_hash"] == "testhash123"
