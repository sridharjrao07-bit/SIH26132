"""
Backend audit tests — characterization + contract coverage for SIH26132.

These tests exist to:
  1. Exercise previously untested API / domain paths.
  2. Pin current behaviour that the evaluation report cites as findings.
  3. Guard security gates (authz, JWT, webhook HMAC).

They do not require a live Supabase instance (FakeSupabase via conftest).
"""
from __future__ import annotations

import inspect
from datetime import date, timedelta
from pathlib import Path

import pytest
from app.main import app
from fastapi.testclient import TestClient
from forecasting.engine import _make_forecast_rows
from ingestion.data_gov_in import DataGovInAdapter
from notifications.alert_checker import normalize_phone
from notifications.prices import latest_price_for_user
from notifications.sms_gateway import MockSMSGateway, MSG91Gateway, get_sms_gateway

from tests.conftest import (
    ADMIN_USER_ID,
    COMMODITY_ID_ONION,
    FARMER_USER_ID,
    MARKET_ID_LASALGAON,
    mint_jwt,
)

client = TestClient(app, raise_server_exceptions=False)


def farmer_headers():
    return {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}


def admin_headers():
    return {"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"}


# ── Auth / JWT ────────────────────────────────────────────────────────────────

# ── Public API contracts ──────────────────────────────────────────────────────

def test_health_does_not_expose_environment():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok"}
    assert "environment" not in body


def test_historical_days_over_max_rejected():
    resp = client.get(
        f"/api/v1/prices/historical?market_id={MARKET_ID_LASALGAON}"
        f"&commodity_id={COMMODITY_ID_ONION}&days=999999"
    )
    assert resp.status_code == 422


def test_latest_prices_limit_over_max_rejected():
    resp = client.get("/api/v1/prices/latest?limit=501")
    assert resp.status_code == 422


def test_unknown_path_is_404_not_500():
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404


def test_commodities_response_hides_sanity_bands():
    resp = client.get("/api/v1/commodities/")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert "sanity_min" not in row and "sanity_max" not in row
    assert "name_en" in row


def test_nearby_invalid_lng_rejected():
    resp = client.get("/api/v1/markets/nearby?lat=20&lng=999")
    assert resp.status_code == 422


def test_nearby_zero_radius_rejected():
    resp = client.get("/api/v1/markets/nearby?lat=20&lng=74&radius_km=0")
    assert resp.status_code == 422


# ── Alerts CRUD ───────────────────────────────────────────────────────────────

def test_user_client_does_not_forward_jwt_to_postgrest():
    src = _read("app/deps.py")
    assert "postgrest.auth" not in src
    assert "get_supabase_service_role" in src


# ── SMS webhook / inbound ─────────────────────────────────────────────────────

# ── Phone normalization ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("9876543210", "+919876543210"),
        ("09876543210", "+919876543210"),
        ("919876543210", "+919876543210"),
        ("+919876543210", "+919876543210"),
        ("123", None),
        (None, None),
        ("", None),
        ("abcdefghij", None),
        ("+1-555-000-0000", None),  # not a 10-digit IN number
    ],
)
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


# ── Forecasting correctness ───────────────────────────────────────────────────

def test_forecast_horizon_is_anchored_to_today():
    last = date.today() - timedelta(days=20)
    series = [(last - timedelta(days=24 - i), 1800.0 + i) for i in range(25)]
    assert series[-1][0] == last
    rows = _make_forecast_rows("m1", "c1", series, sanity=(100, 8000))
    assert len(rows) == 7
    assert all(r["forecast_date"] > date.today().isoformat() for r in rows)


def test_district_fallback_averages_across_markets():
    from forecasting.engine import build_district_daily_series
    rows = [
        {"arrival_date": "2026-08-01", "modal_price": 1000, "source": "data_gov_in",
         "variety": "General", "market_id": "m1"},
        {"arrival_date": "2026-08-01", "modal_price": 5000, "source": "data_gov_in",
         "variety": "General", "market_id": "m2"},
    ]
    series = build_district_daily_series(rows)
    assert len(series) == 1
    assert series[0][1] == 3000.0


def test_blend_tier_medium_for_15_to_19_obs():
    series = [(date(2026, 1, 1) + timedelta(days=i), 2000.0) for i in range(16)]
    rows = _make_forecast_rows("m", "c", series, None)
    assert rows[0]["method"] == "blend"
    assert rows[0]["confidence"] == "medium"


# ── Ingestion / adapter ───────────────────────────────────────────────────────

def test_data_gov_in_adapter_parses_arrival_qty():
    src = inspect.getsource(DataGovInAdapter.fetch_prices)
    assert "arrival_qty" in src
    assert "arrivals" in src


def test_ingestion_job_takes_distributed_lock():
    from app.services.jobs import _claim, run_alert_job, run_ingestion_job
    assert "_claim" in inspect.getsource(run_ingestion_job)
    assert "_claim" in inspect.getsource(run_alert_job)
    assert "claim_job_lock" in inspect.getsource(_claim)


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_slowapi_is_wired_into_the_app():
    assert hasattr(app.state, "limiter")
    src = _read("app/main.py")
    assert "SlowAPIMiddleware" in src
    assert "Limiter" in _read("app/rate_limit.py")


def test_settings_constructor_accepts_field_names():
    from app.config import Settings
    s = Settings(msg91_dlt_te_id_mr="tmpl_mr")
    assert s.msg91_dlt_te_id_mr == "tmpl_mr"


# ── Alert checker behaviour ───────────────────────────────────────────────────

def test_sustained_gte_breach_does_not_fire_without_fresh_cross(fake_supabase, tmp_path):
    from tests.test_alerts import make_alert, make_checker, make_prices, make_profile
    fake_supabase.seed("user_profiles", [make_profile()])
    fake_supabase.seed("alerts", [make_alert(threshold=2200.0, condition="gte", last_notified_at=None)])
    fake_supabase.seed(
        "prices",
        make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2300, 1: 2400}),
    )
    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0


def test_invalid_phone_skips_sms(fake_supabase):
    from tests.test_alerts import make_alert, make_checker, make_prices, make_profile
    fake_supabase.seed("user_profiles", [make_profile(phone="123")])
    fake_supabase.seed("alerts", [make_alert()])
    fake_supabase.seed(
        "prices",
        make_prices(MARKET_ID_LASALGAON, COMMODITY_ID_ONION, {2: 2100, 1: 2300}),
    )
    checker = make_checker(fake_supabase)
    result = checker.run()
    assert result["fired"] == 0


def test_latest_price_for_user_district_fallback(fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed(
        "prices",
        [{"market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
          "arrival_date": today, "modal_price": 1750.0, "source": "data_gov_in",
          "markets": {"name": "Lasalgaon APCM"}}],
    )
    price, market = latest_price_for_user(
        fake_supabase, COMMODITY_ID_ONION, {"lat": None, "lng": None, "district": "Nashik"}
    )
    assert price == 1750.0
    assert market == "Lasalgaon APCM"


def test_msg91_non_200_is_failed():
    gw = MSG91Gateway(auth_key="k")
    status, ok = gw.send_sms("+919876543210", "x", template_id=None)
    assert (status, ok) == ("failed", False)


def test_get_sms_gateway_defaults_to_mock():
    gw = get_sms_gateway()
    assert isinstance(gw, MockSMSGateway)


def test_exception_handler_does_not_leak_internal_message(override_supabase, fake_supabase):
    """Nearby already maps RPC errors to generic 503; confirm no traceback in body."""
    def boom(fn_name, params=None):
        raise RuntimeError("password=supersecret schema cache")

    fake_supabase.rpc = boom
    resp = client.get("/api/v1/markets/nearby?lat=20&lng=74")
    assert resp.status_code == 503
    assert "supersecret" not in resp.text
    assert "password" not in resp.text


def test_cors_header_reflects_configured_origin():
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_allows_vite_dev_origin():
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_disallows_unknown_origin():
    resp = client.get("/health", headers={"Origin": "https://evil.example"})
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"


def test_handle_new_user_does_not_trust_client_role():
    src = _read("db/migrations/001_schema.sql")
    assert "raw_user_meta_data ->> 'role'" not in src
    assert "'farmer'" in src


def test_admin_set_role_not_granted_to_authenticated():
    needle = "grant execute on function public.admin_set_role(uuid, text) to authenticated"
    for path in (
        "db/migrations/003b_admin_set_role_grants.sql",
        "db/migrations/008_marketplace.sql",
        "db/migrations/011_ops_hardening.sql",
    ):
        src = _read(path).lower()
        assert needle not in src
        assert "to service_role" in src
