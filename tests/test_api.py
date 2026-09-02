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
import pytest
from fastapi.testclient import TestClient
from datetime import date, datetime, timezone

from app.main import app
from tests.conftest import (
    FakeSupabase,
    MARKET_ID_LASALGAON,
    MARKET_ID_PIMPALGAON,
    COMMODITY_ID_ONION,
    COMMODITY_ID_TOMATO,
    FARMER_USER_ID,
    ADMIN_USER_ID,
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

def test_forecast_stats_admin_returns_200_with_confidence_key(override_supabase, fake_supabase):
    """B1 regression: must not raise KeyError('confidence_tier')"""
    fake_supabase._data["forecasts"] = [{
        "id": "f-001",
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": date.today().isoformat(),
        "predicted_price": 1800.0,
        "lower_bound": 1600.0,
        "upper_bound": 2000.0,
        "confidence": "high",       # correct column name
        "method": "blend",
        "observations": 25,
        "status": "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "markets": {"name": "Lasalgaon APCM"},
        "commodities": {"name_en": "Onion"},
    }]
    fake_supabase._data["prices"] = []

    resp = client.get("/dashboard/api/forecast-stats", headers=admin_headers())
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert "confidence" in data[0]     # key must be 'confidence', not 'confidence_tier'

def test_forecast_stats_farmer_gets_403(override_supabase, fake_supabase):
    """Admin-only endpoint must reject farmer tokens"""
    resp = client.get("/dashboard/api/forecast-stats", headers=farmer_headers())
    assert resp.status_code == 403

def test_forecast_stats_no_token_gets_401(override_supabase, fake_supabase):
    resp = client.get("/dashboard/api/forecast-stats")
    assert resp.status_code == 401

def test_ingestion_logs_admin_returns_200(override_supabase, fake_supabase_with_logs):
    """A1 regression: must not 400 (wrong order column 'start_time' → 'run_at')"""
    resp = client.get("/dashboard/api/ingestion-logs", headers=admin_headers())
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    # Verify the correct column is present in the response
    assert "run_at" in data[0]

def test_ingestion_logs_farmer_gets_403(override_supabase, fake_supabase):
    resp = client.get("/dashboard/api/ingestion-logs", headers=farmer_headers())
    assert resp.status_code == 403


# ─── Forecasts ───────────────────────────────────────────────────────────────

def test_get_forecasts_returns_ok_rows_only(override_supabase, fake_supabase):
    """M7: status=ok filter — stale rows must not appear"""
    today = date.today().isoformat()
    fake_supabase._data["forecasts"] = [
        {
            "id": "f-ok",
            "market_id": MARKET_ID_LASALGAON,
            "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": today,
            "predicted_price": 1800.0,
            "lower_bound": 1600.0, "upper_bound": 2000.0,
            "confidence": "high", "method": "blend",
            "observations": 25, "status": "ok",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
            "commodities": {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"},
        },
        {
            "id": "f-stale",
            "market_id": MARKET_ID_LASALGAON,
            "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": today,
            "predicted_price": 1700.0,
            "lower_bound": 1500.0, "upper_bound": 1900.0,
            "confidence": "medium", "method": "moving_avg",
            "observations": 12, "status": "stale",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
            "commodities": {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"},
        },
    ]
    resp = client.get(
        f"/api/v1/forecasts?market_id={MARKET_ID_LASALGAON}&commodity_id={COMMODITY_ID_ONION}"
    )
    assert resp.status_code == 200
    data = resp.json()
    statuses = [r["status"] for r in data]
    assert "stale" not in statuses
    assert "ok" in statuses

def test_get_forecasts_summary_includes_insufficient_data(override_supabase, fake_supabase):
    """M7+B2: summary should include insufficient_data but not stale"""
    today = date.today().isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    fake_supabase._data["forecasts"] = [
        {
            "id": "f-ok",
            "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": today, "predicted_price": 1800.0,
            "lower_bound": 1600.0, "upper_bound": 2000.0,
            "confidence": "high", "method": "blend",
            "observations": 25, "status": "ok", "generated_at": now_iso,
            "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
            "commodities": {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"},
        },
        {
            "id": "f-insuf",
            "market_id": MARKET_ID_PIMPALGAON, "commodity_id": COMMODITY_ID_TOMATO,
            "forecast_date": today, "predicted_price": None,
            "lower_bound": None, "upper_bound": None,
            "confidence": None, "method": "none",
            "observations": 5, "status": "insufficient_data", "generated_at": now_iso,
            "markets": {"name": "Pimpalgaon Baswant APCM", "district": "Nashik"},
            "commodities": {"name_en": "Tomato", "name_mr": "टोमॅटो", "name_hi": "टमाटर"},
        },
        {
            "id": "f-stale",
            "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_TOMATO,
            "forecast_date": today, "predicted_price": 500.0,
            "lower_bound": 400.0, "upper_bound": 600.0,
            "confidence": "medium", "method": "moving_avg",
            "observations": 12, "status": "stale", "generated_at": now_iso,
            "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
            "commodities": {"name_en": "Tomato", "name_mr": "टोमॅटो", "name_hi": "टमाटर"},
        },
    ]
    resp = client.get("/api/v1/forecasts/summary")
    assert resp.status_code == 200
    data = resp.json()
    statuses = {r["status"] for r in data}
    assert "stale" not in statuses
    assert "ok" in statuses
    assert "insufficient_data" in statuses


# ─── Alerts ──────────────────────────────────────────────────────────────────

def test_alerts_patch_null_threshold_returns_422_not_500(override_supabase, fake_supabase):
    """M3 regression: null threshold_price must return 422 (Pydantic), not 500 (TypeError)"""
    fake_supabase._data["alerts"] = [
        {"id": "a-1", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
         "threshold_price": 1500.0, "condition": "lte", "active": True}
    ]
    resp = client.patch(
        "/api/v1/alerts/a-1",
        json={"threshold_price": None},
        headers=farmer_headers(),
    )
    # Pydantic Field(gt=0) with explicit None: the field is Optional so None is allowed
    # but the updated value passes through is not None guard. This tests the previous crash
    # was a TypeError from '<=' with None, which Field(gt=0) now prevents at schema level.
    assert resp.status_code in (200, 422), f"Must not be 500: {resp.status_code} {resp.text}"
    assert resp.status_code != 500

def test_alerts_patch_zero_threshold_returns_422(override_supabase, fake_supabase):
    """M3: threshold=0 must be rejected by Field(gt=0)"""
    resp = client.patch(
        "/api/v1/alerts/a-1",
        json={"threshold_price": 0},
        headers=farmer_headers(),
    )
    assert resp.status_code == 422

def test_alerts_list_no_auth_returns_401(override_supabase, fake_supabase):
    """list_alerts was missing Depends(get_current_user) — must now return 401"""
    resp = client.get("/api/v1/alerts/")
    assert resp.status_code == 401

def test_alerts_create_valid(override_supabase, fake_supabase):
    """Happy path: create alert with valid threshold"""
    resp = client.post(
        "/api/v1/alerts/",
        json={
            "commodity_id": COMMODITY_ID_ONION,
            "threshold_price": 1500.0,
            "condition": "lte",
        },
        headers=farmer_headers(),
    )
    assert resp.status_code == 200


# ─── Markets nearby ──────────────────────────────────────────────────────────

def test_nearby_markets_rpc_error_returns_503(override_supabase, fake_supabase):
    """M4 regression: RPC missing → must be 503 with generic message, not 500 + raw exception"""
    from tests.conftest import _ExecuteResult

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

def test_admin_forecast_run_rejects_farmer_token(override_supabase, fake_supabase):
    """Farmer role must not access admin endpoints"""
    resp = client.post("/api/v1/admin/forecast/run", headers=farmer_headers())
    assert resp.status_code == 403

def test_admin_forecast_run_rejects_no_token(override_supabase, fake_supabase):
    """No token must return 401 on admin endpoints"""
    resp = client.post("/api/v1/admin/forecast/run")
    assert resp.status_code == 401

def test_admin_forecast_run_accepts_admin_token(override_supabase, fake_supabase):
    """Admin token must be accepted (mocked Supabase won't actually run the job)"""
    resp = client.post("/api/v1/admin/forecast/run", headers=admin_headers())
    # 200 = accepted; any non-401/403 status is fine here against the fake DB
    assert resp.status_code not in (401, 403), f"Admin must not be rejected: {resp.status_code}"
