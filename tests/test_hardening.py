"""Crash-proofing: PostgREST errors, bad JSON, IDOR, bounds — never 500."""
from __future__ import annotations

from app.errors import json_for_api_error
from app.main import app
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

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


def test_postgrest_error_on_markets_is_not_500(override_supabase):
    def boom(*a, **k):
        raise APIError({"code": "22P02", "message": "invalid input syntax for type uuid"})

    from app.deps import get_supabase
    from app.main import app

    class BoomSupabase:
        def table(self, *a, **k):
            return boom()

    app.dependency_overrides[get_supabase] = lambda: BoomSupabase()

    try:
        resp = client.get("/api/v1/markets/")
        assert resp.status_code == 422
        assert resp.json()["detail"] == "invalid id"
    finally:
        # restore the previous override by re-running override_supabase? No, dependency_overrides will be cleared.
        pass


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


def test_empty_post_lots_is_422_not_500(override_supabase, fake_supabase):
    resp = client.post("/api/v1/lots/", json={}, headers=farmer_headers())
    assert resp.status_code == 422
    assert resp.status_code != 500
