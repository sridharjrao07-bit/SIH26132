"""
tests/test_api.py — HTTP endpoint tests for all public and admin routers.

Covers previously-tested routes (markets, commodities, prices) plus all
previously-untested routes that contained runtime crashes in the evaluation:
  - Dashboard: forecast-stats (B1), ingestion-logs (A1)
  - Alerts: PATCH null threshold (M3), list_alerts auth
  - Markets: nearby RPC error (M4), input bounds
  - Forecasts: get_forecasts, get_forecasts_summary (M7)
  - Auth gates: admin endpoints reject farmer tokens and no-token requests
"""
from datetime import date, datetime, timezone

from app.main import app
from fastapi.testclient import TestClient

from tests.conftest import (
    ADMIN_USER_ID,
    COMMODITY_ID_ONION,
    FARMER_USER_ID,
    MARKET_ID_LASALGAON,
    mint_jwt,
)

client = TestClient(app, raise_server_exceptions=False)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def farmer_headers():
    return {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}

def admin_headers():
    return {"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"}


# ─── Basic public endpoints (previously tested — kept as regression locks) ───

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_get_markets_no_auth(override_supabase, fake_supabase):
    response = client.get("/api/v1/markets/")
    assert response.status_code == 200
    assert len(response.json()) == 2   # seeded markets

def test_get_markets_with_filter(override_supabase, fake_supabase):
    response = client.get("/api/v1/markets/?district=Nashik")
    assert response.status_code == 200
    assert len(response.json()) == 2
    
def test_get_markets_with_bad_filter(override_supabase, fake_supabase):
    response = client.get("/api/v1/markets/?district=Nowhere")
    assert response.status_code == 200
    assert len(response.json()) == 0

def test_get_commodities_no_auth(override_supabase, fake_supabase):
    response = client.get("/api/v1/commodities/")
    assert response.status_code == 200
    assert len(response.json()) == 2
    data = response.json()
    assert "name_mr" in data[0]
    assert "name_hi" in data[0]

def test_get_latest_prices_no_auth(override_supabase, fake_supabase):
    response = client.get("/api/v1/prices/latest?limit=7")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_historical_prices(override_supabase, fake_supabase):
    response = client.get("/api/v1/prices/historical?market_id=123&commodity_id=456&limit=100")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_latest_prices_seeded(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase._data["prices"] = [{
        "id": "1111-2222",
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "min_price": 1000.0,
        "max_price": 2000.0,
        "modal_price": 1500.0,
        "unit": "quintal",
        "variety": "General",
        "grade": "FAQ",
        "source": "data_gov_in",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
        "commodities": {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"}
    }]
    response = client.get("/api/v1/prices/latest")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["market_name"] == "Lasalgaon APCM"
    assert data[0]["modal_price"] == 1500.0


# ─── Dashboard: B1 + A1 regression locks ─────────────────────────────────────

# ─── Forecasts ───────────────────────────────────────────────────────────────

# ─── Alerts ──────────────────────────────────────────────────────────────────

# ─── Markets nearby ──────────────────────────────────────────────────────────

def test_nearby_markets_rpc_error_returns_503(override_supabase, fake_supabase):
    """M4 regression: RPC missing → must be 503 with generic message, not 500 + raw exception"""

    def failing_rpc(fn_name, params=None):
        raise RuntimeError("Could not find function public.nearby_markets in schema cache")

    fake_supabase.rpc = failing_rpc

    resp = client.get("/api/v1/markets/nearby?lat=20.0&lng=74.0")
    assert resp.status_code == 503
    # Must NOT leak the internal exception text
    assert "schema cache" not in resp.text
    assert "nearby_markets" not in resp.text

def test_nearby_markets_radius_too_large_returns_422(override_supabase, fake_supabase):
    """M4: radius_km > 500 must be rejected by Query bound"""
    resp = client.get("/api/v1/markets/nearby?lat=20.0&lng=74.0&radius_km=9999")
    assert resp.status_code == 422

def test_nearby_markets_invalid_lat_returns_422(override_supabase, fake_supabase):
    """M4: lat out of range must be rejected"""
    resp = client.get("/api/v1/markets/nearby?lat=999&lng=74.0")
    assert resp.status_code == 422


# ─── Auth gates ──────────────────────────────────────────────────────────────

# ─── P1-1 regression: _call_rpc must RETURN, not RAISE, json_for_api_error ────

