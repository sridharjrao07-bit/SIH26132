"""
Backend audit tests — characterization + contract coverage for SIH26132.

These tests exist to:
  1. Exercise previously untested API / domain paths.
  2. Pin current behaviour that the evaluation report cites as findings.
  3. Guard security gates (authz, JWT, webhook HMAC).

They do not require a live Supabase instance (FakeSupabase via conftest).
"""
from __future__ import annotations

import hmac
import hashlib
import inspect
import time
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
import jwt

from app.main import app
from notifications.alert_checker import normalize_phone, AlertChecker
from notifications.prices import latest_price_for_user
from notifications.sms_gateway import get_sms_gateway, MockSMSGateway, MSG91Gateway
from forecasting.engine import _make_forecast_rows, build_daily_series
from ingestion.data_gov_in import DataGovInAdapter
from tests.conftest import (
    MARKET_ID_LASALGAON,
    MARKET_ID_PIMPALGAON,
    COMMODITY_ID_ONION,
    COMMODITY_ID_TOMATO,
    FARMER_USER_ID,
    ADMIN_USER_ID,
    mint_jwt,
)

client = TestClient(app, raise_server_exceptions=False)


def farmer_headers():
    return {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}


def admin_headers():
    return {"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"}


# ── Auth / JWT ────────────────────────────────────────────────────────────────

def test_expired_jwt_is_rejected():
    secret = "placeholder"
    token = jwt.encode(
        {
            "sub": FARMER_USER_ID,
            "aud": "authenticated",
            "role": "authenticated",
            "exp": int(time.time()) - 120,
            "iat": int(time.time()) - 200,
        },
        secret,
        algorithm="HS256",
    )
    resp = client.get("/api/v1/alerts/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_wrong_audience_jwt_is_rejected():
    secret = "placeholder"
    token = jwt.encode(
        {
            "sub": FARMER_USER_ID,
            "aud": "anon",
            "role": "authenticated",
            "exp": int(time.time()) + 3600,
        },
        secret,
        algorithm="HS256",
    )
    resp = client.get("/api/v1/alerts/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_malformed_bearer_is_rejected():
    resp = client.get("/api/v1/alerts/", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_jwt_missing_sub_is_rejected():
    secret = "placeholder"
    token = jwt.encode(
        {"aud": "authenticated", "role": "authenticated", "exp": int(time.time()) + 3600},
        secret,
        algorithm="HS256",
    )
    resp = client.get("/api/v1/alerts/", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_farmer_cannot_run_admin_alert_check():
    resp = client.post("/api/v1/admin/alert-check/run", headers=farmer_headers())
    assert resp.status_code == 403


def test_sms_simulate_rejects_farmer():
    resp = client.post(
        "/api/v1/sms/simulate",
        json={"sender": "+919876543210", "message": "ONION"},
        headers=farmer_headers(),
    )
    assert resp.status_code == 403


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


def test_forecast_days_over_seven_rejected():
    resp = client.get(
        f"/api/v1/forecasts?market_id={MARKET_ID_LASALGAON}"
        f"&commodity_id={COMMODITY_ID_ONION}&days=8"
    )
    assert resp.status_code == 422


def test_unknown_path_is_404_not_500():
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404


def test_dashboard_html_is_public():
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Admin Dashboard" in resp.text


def test_dashboard_html_does_not_use_innerhtml():
    resp = client.get("/dashboard")
    assert "innerHTML" not in resp.text
    assert "textContent" in resp.text
    assert "createElement" in resp.text
    assert "localStorage" not in resp.text
    assert "sessionStorage" not in resp.text
    assert "/dashboard/session" in resp.text


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

def test_create_alert_rejects_negative_threshold():
    resp = client.post(
        "/api/v1/alerts/",
        json={"commodity_id": COMMODITY_ID_ONION, "threshold_price": -1, "condition": "gte"},
        headers=farmer_headers(),
    )
    assert resp.status_code == 422


def test_create_alert_rejects_invalid_condition():
    resp = client.post(
        "/api/v1/alerts/",
        json={"commodity_id": COMMODITY_ID_ONION, "threshold_price": 1500, "condition": "eq"},
        headers=farmer_headers(),
    )
    assert resp.status_code == 422


def test_create_alert_requires_auth():
    resp = client.post(
        "/api/v1/alerts/",
        json={"commodity_id": COMMODITY_ID_ONION, "threshold_price": 1500, "condition": "gte"},
    )
    assert resp.status_code == 401


def test_delete_alert_404_when_missing(override_supabase, fake_supabase):
    fake_supabase.seed("alerts", [])
    resp = client.delete("/api/v1/alerts/does-not-exist", headers=farmer_headers())
    assert resp.status_code == 404


def test_delete_alert_ok(override_supabase, fake_supabase):
    fake_supabase.seed(
        "alerts",
        [{"id": "a-del-1", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
          "threshold_price": 1500.0, "condition": "lte", "active": True}],
    )
    resp = client.delete("/api/v1/alerts/a-del-1", headers=farmer_headers())
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


def test_user_client_does_not_forward_jwt_to_postgrest():
    src = _read("app/deps.py")
    assert "postgrest.auth" not in src
    assert "get_supabase_service_role" in src


def test_list_alerts_hides_other_users_rows(override_supabase, fake_supabase):
    fake_supabase.seed(
        "alerts",
        [
            {"id": "a-mine", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
             "threshold_price": 1500.0, "condition": "lte", "active": True,
             "created_at": datetime.now(timezone.utc).isoformat(),
             "markets": {"name": "Lasalgaon APCM"},
             "commodities": {"name_en": "Onion", "name_mr": "कांदा"}},
            {"id": "a-theirs", "user_id": ADMIN_USER_ID, "commodity_id": COMMODITY_ID_ONION,
             "threshold_price": 9999.0, "condition": "gte", "active": True,
             "created_at": datetime.now(timezone.utc).isoformat(),
             "markets": {"name": "Lasalgaon APCM"},
             "commodities": {"name_en": "Onion", "name_mr": "कांदा"}},
        ],
    )
    resp = client.get("/api/v1/alerts/", headers=farmer_headers())
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert ids == {"a-mine"}


def test_list_alerts_with_farmer_token(override_supabase, fake_supabase):
    fake_supabase.seed(
        "alerts",
        [{"id": "a-list-1", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
          "threshold_price": 1500.0, "condition": "lte", "active": True,
          "created_at": datetime.now(timezone.utc).isoformat(),
          "markets": {"name": "Lasalgaon APCM"},
          "commodities": {"name_en": "Onion", "name_mr": "कांदा"}}],
    )
    resp = client.get("/api/v1/alerts/", headers=farmer_headers())
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_patch_alert_happy_path(override_supabase, fake_supabase):
    fake_supabase.seed(
        "alerts",
        [{"id": "a-patch-1", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
          "threshold_price": 1500.0, "condition": "lte", "active": True}],
    )
    resp = client.patch(
        "/api/v1/alerts/a-patch-1",
        json={"active": False, "threshold_price": 1800},
        headers=farmer_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["active"] is False
    assert resp.json()["threshold_price"] == 1800


# ── SMS webhook / inbound ─────────────────────────────────────────────────────

def test_sms_webhook_unsigned_is_403():
    resp = client.post("/api/v1/sms/webhook", json={"sender": "+919876543210", "message": "ONION"})
    assert resp.status_code == 403


def test_sms_simulate_unknown_keyword_sends_help(override_supabase, fake_supabase, tmp_path, monkeypatch):
    from app.routers import sms as sms_mod
    sms_mod.get_sms_gateway = lambda: MockSMSGateway(log_file=str(tmp_path / "sms.log"))
    # Patch the name used inside _process_inbound via module
    monkeypatch.setattr("app.routers.sms.get_sms_gateway", lambda: MockSMSGateway(log_file=str(tmp_path / "sms.log")))
    resp = client.post(
        "/api/v1/sms/simulate",
        json={"sender": "9876543210", "message": "POTATO"},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "help_sent"


def test_sms_simulate_known_keyword_replies(override_supabase, fake_supabase, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.routers.sms.get_sms_gateway",
        lambda: MockSMSGateway(log_file=str(tmp_path / "sms.log")),
    )
    for row in fake_supabase._data["commodity_alias"]:
        if row.get("source") == "sms":
            row["commodities"] = {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"}
    today = date.today().isoformat()
    fake_supabase.seed(
        "prices",
        [{"market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
          "arrival_date": today, "modal_price": 2100.0, "source": "data_gov_in",
          "variety": "General", "markets": {"name": "Lasalgaon APCM"}}],
    )
    fake_supabase.set_rpc("nearest_market", [{"id": MARKET_ID_LASALGAON, "name": "Lasalgaon APCM", "distance_km": 3.2}])
    resp = client.post(
        "/api/v1/sms/simulate",
        json={"sender": "9876543210", "message": "PYAJ"},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in ("replied", "no_data")
    if resp.json()["status"] == "replied":
        assert "recommendation" in resp.json()


def test_sms_simulate_first_token_keyword_replies(override_supabase, fake_supabase, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.routers.sms.get_sms_gateway",
        lambda: MockSMSGateway(log_file=str(tmp_path / "sms.log")),
    )
    for row in fake_supabase._data["commodity_alias"]:
        if row.get("source") == "sms":
            row["commodities"] = {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"}
    today = date.today().isoformat()
    fake_supabase.seed(
        "prices",
        [{"market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
          "arrival_date": today, "modal_price": 2100.0, "source": "data_gov_in",
          "variety": "General", "markets": {"name": "Lasalgaon APCM"}}],
    )
    fake_supabase.set_rpc("nearest_market", [{"id": MARKET_ID_LASALGAON, "name": "Lasalgaon APCM", "distance_km": 3.2}])
    resp = client.post(
        "/api/v1/sms/simulate",
        json={"sender": "9876543210", "message": "PYAJ LASALGAON"},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "replied"


def test_sms_simulate_unknown_unregistered_ignored(override_supabase, fake_supabase):
    resp = client.post(
        "/api/v1/sms/simulate",
        json={"sender": "9000000000", "message": "POTATO"},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_sms_simulate_empty_payload_ignored(override_supabase, fake_supabase):
    resp = client.post(
        "/api/v1/sms/simulate",
        json={"sender": "", "message": ""},
        headers=admin_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_replay_within_window_is_rejected(monkeypatch):
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "audit-secret")
    from importlib import reload
    from fastapi import HTTPException
    import notifications.inbound_verifier as iv_mod
    reload(iv_mod)

    verifier = iv_mod.InboundVerifier()
    body = b'{"sender":"+919876543210","message":"ONION"}'
    ts = str(time.time())
    sig = hmac.new(b"audit-secret", body + ts.encode(), hashlib.sha256).hexdigest()

    class _Req:
        def __init__(self):
            self.headers = {"X-Signature": sig, "X-Timestamp": ts}

        async def body(self):
            return body

    assert await verifier.verify(_Req()) is True
    with pytest.raises(HTTPException) as ei:
        await verifier.verify(_Req())
    assert ei.value.status_code == 403


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


def test_forecast_public_api_hides_past_dated_rows(override_supabase, fake_supabase):
    past = (date.today() - timedelta(days=3)).isoformat()
    fake_supabase.seed(
        "forecasts",
        [{
            "id": "f-past",
            "market_id": MARKET_ID_LASALGAON,
            "commodity_id": COMMODITY_ID_ONION,
            "forecast_date": past,
            "predicted_price": 1800.0,
            "lower_bound": 1600.0, "upper_bound": 2000.0,
            "confidence": "high", "method": "blend",
            "observations": 25, "status": "ok",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
            "commodities": {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"},
        }],
    )
    resp = client.get(
        f"/api/v1/forecasts?market_id={MARKET_ID_LASALGAON}&commodity_id={COMMODITY_ID_ONION}"
    )
    assert resp.status_code == 200
    assert resp.json() == []


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
    from app.jobs import run_ingestion_job, run_alert_job, _claim
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


def test_inbound_verifier_uses_settings_when_env_empty(monkeypatch):
    monkeypatch.delenv("INBOUND_HMAC_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    from types import SimpleNamespace
    from importlib import reload
    import notifications.inbound_verifier as iv_mod
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(
            inbound_hmac_secret="settings-only-secret",
            app_env="development",
            inbound_sig_header="X-Signature",
            inbound_ts_header="X-Timestamp",
        ),
    )
    reload(iv_mod)
    v = iv_mod.InboundVerifier()
    assert v.secret == b"settings-only-secret"


# ── Alert checker behaviour ───────────────────────────────────────────────────

def test_sustained_gte_breach_does_not_fire_without_fresh_cross(fake_supabase, tmp_path):
    from tests.test_alerts import make_profile, make_alert, make_prices, make_checker
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
    from tests.test_alerts import make_profile, make_alert, make_prices, make_checker
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


def test_admin_forecast_locked_returns_locked(override_supabase, fake_supabase):
    fake_supabase.set_rpc("claim_job_lock", False)  # lock not acquired
    resp = client.post("/api/v1/admin/forecast/run", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.json()["status"] == "locked"


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


def test_sms_inbound_uses_phone_rpc_not_profiles_table():
    src = _read("app/routers/sms.py")
    assert "lookup_profile_by_phone" in src
    assert "open_lots_for_user" in src
    assert '.table("user_profiles")' not in src
    assert "get_verifier" in src


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


def test_sms_outbound_cap(override_supabase, fake_supabase, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.routers.sms.get_sms_gateway",
        lambda: MockSMSGateway(log_file=str(tmp_path / "sms.log")),
    )
    from app.routers import sms as sms_mod
    sms_mod.reset_outbound_cap()
    sms_mod._OUTBOUND_MAX = 2
    for row in fake_supabase._data["commodity_alias"]:
        if row.get("source") == "sms":
            row["commodities"] = {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"}
    today = date.today().isoformat()
    fake_supabase.seed(
        "prices",
        [{"market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
          "arrival_date": today, "modal_price": 2100.0, "source": "data_gov_in",
          "variety": "General", "markets": {"name": "Lasalgaon APCM"}}],
    )
    statuses = []
    for _ in range(3):
        resp = client.post(
            "/api/v1/sms/simulate",
            json={"sender": "9876543210", "message": "PYAJ"},
            headers=admin_headers(),
        )
        assert resp.status_code == 200
        statuses.append(resp.json()["status"])
    sms_mod._OUTBOUND_MAX = 5
    sms_mod.reset_outbound_cap()
    assert "rate_limited" in statuses
    assert statuses.count("replied") == 2


def test_dashboard_session_cookie(override_supabase, fake_supabase):
    token = mint_jwt(ADMIN_USER_ID)
    try:
        resp = client.post("/dashboard/session", json={"token": token})
        assert resp.status_code == 200
        assert "kb_admin" in resp.cookies
        logs = client.get("/dashboard/api/ingestion-logs")
        assert logs.status_code == 200
        client.delete("/dashboard/session")
        after = client.get("/dashboard/api/ingestion-logs")
        assert after.status_code in (401, 403)
    finally:
        client.cookies.clear()


def test_dashboard_session_rejects_farmer(override_supabase, fake_supabase):
    resp = client.post("/dashboard/session", json={"token": mint_jwt(FARMER_USER_ID)})
    assert resp.status_code == 403


def test_marketplace_routes_exist():
    # Probe HTTP, not app.routes: middleware wrappers hide mounted paths on some stacks.
    assert client.get("/api/v1/buyers/").status_code != 404
    assert client.get("/api/v1/logistics/").status_code != 404
    assert client.get("/api/v1/sale-window/").status_code != 404
    for path in (
        "/api/v1/lots/",
        "/api/v1/offers/",
        "/api/v1/payments/",
        "/api/v1/grievances/",
    ):
        assert client.get(path).status_code != 404, path
    resp = client.get("/health")
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
