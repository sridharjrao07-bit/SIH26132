"""Crash-proofing: PostgREST errors, bad JSON, IDOR, bounds — never 500."""
from __future__ import annotations

from postgrest.exceptions import APIError

from fastapi.testclient import TestClient

from app.errors import json_for_api_error
from app.main import app
from tests.conftest import (
    COMMODITY_ID_ONION,
    FARMER_USER_ID,
    MARKET_ID_LASALGAON,
    mint_jwt,
)

client = TestClient(app, raise_server_exceptions=False)


def farmer_headers():
    return {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}


def test_api_error_invalid_uuid_is_422_not_500():
    resp = json_for_api_error(
        APIError({"code": "22P02", "message": "invalid input syntax for type uuid", "hint": "schema cache"})
    )
    assert resp.status_code == 422
    body = resp.body.decode()
    assert "schema" not in body.lower()
    assert "invalid id" in body


def test_api_error_fk_is_400():
    resp = json_for_api_error(APIError({"code": "23503", "message": "foreign key violation"}))
    assert resp.status_code == 400


def test_api_error_unique_is_409():
    resp = json_for_api_error(APIError({"code": "23505", "message": "duplicate key"}))
    assert resp.status_code == 409


def test_api_error_jwt_is_401():
    resp = json_for_api_error(APIError({"code": "PGRST301", "message": "No suitable key or wrong key type"}))
    assert resp.status_code == 401
    assert "PGRST" not in resp.body.decode()


def test_api_error_unknown_is_503():
    resp = json_for_api_error(APIError({"code": "XX000", "message": "password=supersecret"}))
    assert resp.status_code == 503
    assert "supersecret" not in resp.body.decode()
    assert "password" not in resp.body.decode()


def test_postgrest_error_on_markets_is_not_500(override_supabase, fake_supabase):
    def boom(*a, **k):
        raise APIError({"code": "22P02", "message": "invalid input syntax for type uuid"})

    fake_supabase.table = boom
    resp = client.get("/api/v1/markets/")
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid id"


def test_lot_qty_too_large_is_422(override_supabase, fake_supabase):
    resp = client.post(
        "/api/v1/lots/",
        json={
            "commodity_id": COMMODITY_ID_ONION,
            "market_id": MARKET_ID_LASALGAON,
            "quantity_qtl": 9_999_999,
            "grade": "General",
            "asking_price": 1600,
        },
        headers=farmer_headers(),
    )
    assert resp.status_code == 422


def test_list_lots_invalid_status_is_422(override_supabase, fake_supabase):
    resp = client.get("/api/v1/lots/?status=nope", headers=farmer_headers())
    assert resp.status_code == 422


def test_grievance_for_foreign_lot_is_404(override_supabase, fake_supabase):
    fake_supabase.seed(
        "lots",
        [{"id": "lot-x", "user_id": "someone-else", "fpo_id": None, "status": "open"}],
    )
    resp = client.post(
        "/api/v1/grievances/",
        json={"category": "quality", "description": "wet bags at the gate", "lot_id": "lot-x"},
        headers=farmer_headers(),
    )
    assert resp.status_code == 404


def test_sms_webhook_bad_json_after_hmac_is_400(override_supabase, fake_supabase, monkeypatch):
    import hmac
    import hashlib
    import time
    from app.routers import sms as sms_mod

    monkeypatch.setenv("INBOUND_HMAC_SECRET", "harden-secret")
    sms_mod.reset_verifier_for_tests()
    body = b"not-json"
    ts = str(time.time())
    sig = hmac.new(b"harden-secret", body + ts.encode(), hashlib.sha256).hexdigest()
    resp = client.post(
        "/api/v1/sms/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": sig,
            "X-Timestamp": ts,
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid json"
    sms_mod.reset_verifier_for_tests()


def test_empty_post_lots_is_422_not_500(override_supabase, fake_supabase):
    resp = client.post("/api/v1/lots/", json={}, headers=farmer_headers())
    assert resp.status_code == 422
    assert resp.status_code != 500
