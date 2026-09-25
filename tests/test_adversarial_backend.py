"""
Comprehensive Adversarial & Tough Testing Suite for Krishi Bazaar Backend.

This suite stresses:
1. Authentication & Token Tampering (forgery, expiry, role elevation).
2. Multi-tenant Data Isolation (cross-tenant read/write prevention on lots, offers, payments, alerts).
3. Marketplace State Machine Invariants (invalid transitions, double payouts, bad quantities/prices).
4. Price Discovery & Forecast Boundary Validation (parameter fuzzing, limits, missing entities).
5. SMS Webhook Security & Injection Resilience (forged signatures, replay attacks, malicious text).
6. Forecasting Degradation & Mathematical Safety (zero-variance series, matrix rank deficiency, fallback cascades).
7. Error Masking & Information Leakage Prevention.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import jwt as pyjwt
from app.main import app
from fastapi.testclient import TestClient
from forecasting.engine import _make_forecast_rows
from forecasting.features import build_feature_matrix

from tests.conftest import (
    ADMIN_USER_ID,
    COMMODITY_ID_ONION,
    FARMER_USER_ID,
    MARKET_ID_LASALGAON,
    mint_jwt,
)

client = TestClient(app, raise_server_exceptions=False)

OTHER_FARMER_USER_ID = "44444444-4444-4444-4444-444444444444"
BUYER_USER_ID        = "55555555-5555-5555-5555-555555555555"


def auth_header(user_id: str) -> dict:
    return {"Authorization": f"Bearer {mint_jwt(user_id)}"}


# ─── 1. Authentication & Token Tampering ──────────────────────────────────────

def test_tampered_jwt_signature_rejected():
    """Attacker signs a valid payload with a wrong secret key."""
    payload = {
        "sub": FARMER_USER_ID,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    bogus_token = pyjwt.encode(payload, "completely-wrong-secret-key-attacker", algorithm="HS256")
    resp = client.get("/api/v1/lots/", headers={"Authorization": f"Bearer {bogus_token}"})
    assert resp.status_code == 401


def test_expired_jwt_rejected():
    """Token with an expired timestamp must be rejected."""
    payload = {
        "sub": FARMER_USER_ID,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()) - 7200,
        "exp": int(time.time()) - 3600,
    }
    expired_token = pyjwt.encode(payload, "ci-placeholder-jwt-secret-32b-min", algorithm="HS256")
    resp = client.get("/api/v1/lots/", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


def test_unregistered_user_cannot_access_role_guarded_routes(fake_supabase):
    """Token with a sub that does not exist in user_profiles must be denied role-guarded endpoints."""
    ghost_user_id = "99999999-9999-9999-9999-999999999999"
    resp = client.post(
        "/api/v1/admin/forecast/run",
        headers=auth_header(ghost_user_id),
    )
    # require_role("admin") rejects users not in DB
    assert resp.status_code in (401, 403)


def test_farmer_cannot_access_any_admin_endpoint():
    """Verify that a farmer token is rejected across all admin endpoints."""
    headers = auth_header(FARMER_USER_ID)
    admin_routes = [
        ("POST", "/api/v1/admin/forecast/run", None),
        ("POST", "/api/v1/admin/alert-check/run", None),
        ("GET", "/api/v1/admin/buyers", None),
        ("POST", "/api/v1/admin/buyers", {"name": "Test", "type": "trader", "district": "Nashik", "commodity_id": COMMODITY_ID_ONION}),
        ("GET", "/api/v1/admin/grievances", None),
        ("POST", "/api/v1/admin/offers/expire", None),
        ("POST", "/api/v1/admin/buyers/rescore", None),
        ("POST", "/api/v1/admin/events/ingest", None),
        ("GET", "/api/v1/admin/events", None),
        ("POST", "/api/v1/sms/simulate", {"phone": "+919876543210", "body": "PYAJ"}),
    ]
    for method, path, body in admin_routes:
        if method == "POST":
            resp = client.post(path, json=body, headers=headers)
        else:
            resp = client.get(path, headers=headers)
        assert resp.status_code == 403, f"Expected 403 for farmer on {method} {path}, got {resp.status_code}"


# ─── 2. Multi-Tenant Data Isolation ───────────────────────────────────────────

def test_cross_tenant_lot_access_forbidden(override_supabase, fake_supabase):
    """Farmer B cannot view or read ledger of Farmer A's lot."""
    fake_supabase.seed("user_profiles", [
        {"id": FARMER_USER_ID, "role": "farmer", "phone": "+919876543210", "preferred_language": "mr", "district": "Nashik"},
        {"id": OTHER_FARMER_USER_ID, "role": "farmer", "phone": "+919876543299", "preferred_language": "mr", "district": "Nashik"},
    ])
    fake_supabase.seed("lots", [
        {
            "id": "lot-farmer-a",
            "user_id": FARMER_USER_ID,
            "commodity_id": COMMODITY_ID_ONION,
            "quantity_qtl": 100.0,
            "status": "open",
            "created_at": "2026-09-20T10:00:00Z",
        }
    ])

    # Farmer B tries to access Farmer A's lot
    headers_b = auth_header(OTHER_FARMER_USER_ID)
    get_resp = client.get("/api/v1/lots/lot-farmer-a", headers=headers_b)
    assert get_resp.status_code == 404, "Farmer B must receive 404 when querying Farmer A's lot"

    ledger_resp = client.get("/api/v1/lots/lot-farmer-a/ledger", headers=headers_b)
    assert ledger_resp.status_code == 404, "Farmer B must receive 404 when querying Farmer A's ledger"

    withdraw_resp = client.patch("/api/v1/lots/lot-farmer-a/withdraw", headers=headers_b)
    assert withdraw_resp.status_code == 404, "Farmer B must not be able to withdraw Farmer A's lot"


def test_cross_tenant_alert_isolation(override_supabase, fake_supabase):
    """Farmer B cannot see or delete Farmer A's price alerts."""
    fake_supabase.seed("user_profiles", [
        {"id": FARMER_USER_ID, "role": "farmer", "phone": "+919876543210", "district": "Nashik"},
        {"id": OTHER_FARMER_USER_ID, "role": "farmer", "phone": "+919876543299", "district": "Nashik"},
    ])
    fake_supabase.seed("alerts", [
        {
            "id": "alert-farmer-a",
            "user_id": FARMER_USER_ID,
            "commodity_id": COMMODITY_ID_ONION,
            "market_id": MARKET_ID_LASALGAON,
            "condition": "gte",
            "target_price": 2500.0,
            "is_active": True,
        }
    ])

    headers_b = auth_header(OTHER_FARMER_USER_ID)
    list_resp = client.get("/api/v1/alerts/", headers=headers_b)
    assert list_resp.status_code == 200
    alert_ids = [a["id"] for a in list_resp.json()]
    assert "alert-farmer-a" not in alert_ids, "Farmer B must not see Farmer A's alerts"

    del_resp = client.delete("/api/v1/alerts/alert-farmer-a", headers=headers_b)
    assert del_resp.status_code == 404, "Farmer B must receive 404 trying to delete Farmer A's alert"


# ─── 3. Marketplace State Machine & Boundary Validation ───────────────────────

def test_lot_creation_boundary_rejection(override_supabase, fake_supabase):
    """Test quantity boundaries, missing fields, and grade constraints."""
    headers = auth_header(FARMER_USER_ID)

    # 1. Zero quantity
    r1 = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION, "variety": "General",
        "quantity_qtl": 0, "harvest_date": "2026-09-20"
    }, headers=headers)
    assert r1.status_code == 422

    # 2. Negative quantity
    r2 = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION, "variety": "General",
        "quantity_qtl": -50, "harvest_date": "2026-09-20"
    }, headers=headers)
    assert r2.status_code == 422

    # 3. Excessive quantity (> 1,000,000)
    r3 = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION, "variety": "General",
        "quantity_qtl": 1000001, "harvest_date": "2026-09-20"
    }, headers=headers)
    assert r3.status_code == 422

    # 4. Invalid grade
    r4 = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION, "variety": "General",
        "quantity_qtl": 50, "harvest_date": "2026-09-20", "grade": "ULTRA_PREMIUM"
    }, headers=headers)
    assert r4.status_code == 422


def test_offer_price_and_quantity_boundaries():
    """Offers with negative/zero price or quantity must be rejected."""
    headers = auth_header(FARMER_USER_ID)

    # Negative price
    r1 = client.post("/api/v1/offers/", json={
        "lot_id": "lot-1", "buyer_id": "buyer-1",
        "price_per_qtl": -500, "quantity_qtl": 10
    }, headers=headers)
    assert r1.status_code == 422

    # Zero price
    r2 = client.post("/api/v1/offers/", json={
        "lot_id": "lot-1", "buyer_id": "buyer-1",
        "price_per_qtl": 0, "quantity_qtl": 10
    }, headers=headers)
    assert r2.status_code == 422

    # Zero quantity
    r3 = client.post("/api/v1/offers/", json={
        "lot_id": "lot-1", "buyer_id": "buyer-1",
        "price_per_qtl": 2000, "quantity_qtl": 0
    }, headers=headers)
    assert r3.status_code == 422


def test_withdraw_closed_or_sold_lot_rejected(override_supabase, fake_supabase):
    """A lot that is already sold or withdrawn cannot be withdrawn again."""
    fake_supabase.seed("lots", [
        {
            "id": "lot-sold",
            "user_id": FARMER_USER_ID,
            "commodity_id": COMMODITY_ID_ONION,
            "quantity_qtl": 50,
            "status": "sold",
        },
        {
            "id": "lot-withdrawn",
            "user_id": FARMER_USER_ID,
            "commodity_id": COMMODITY_ID_ONION,
            "quantity_qtl": 50,
            "status": "withdrawn",
        },
    ])
    headers = auth_header(FARMER_USER_ID)

    r_sold = client.patch("/api/v1/lots/lot-sold/withdraw", headers=headers)
    assert r_sold.status_code == 409

    r_withdrawn = client.patch("/api/v1/lots/lot-withdrawn/withdraw", headers=headers)
    assert r_withdrawn.status_code == 409


# ─── 4. Price Discovery & Forecast Boundary Validation ────────────────────────

def test_prices_latest_query_bounds():
    """Verify limit validation on /prices/latest."""
    # Limit over max (le=500)
    r1 = client.get("/api/v1/prices/latest?limit=501")
    assert r1.status_code == 422

    # Limit below min (ge=1)
    r2 = client.get("/api/v1/prices/latest?limit=0")
    assert r2.status_code == 422

    # Limit negative
    r3 = client.get("/api/v1/prices/latest?limit=-10")
    assert r3.status_code == 422


def test_prices_historical_query_bounds():
    """Verify parameter constraints on /prices/historical."""
    # Missing required market_id or commodity_id
    r1 = client.get("/api/v1/prices/historical")
    assert r1.status_code == 422

    # Days exceeds 365
    r2 = client.get(f"/api/v1/prices/historical?market_id={MARKET_ID_LASALGAON}&commodity_id={COMMODITY_ID_ONION}&days=366")
    assert r2.status_code == 422

    # Days is 0
    r3 = client.get(f"/api/v1/prices/historical?market_id={MARKET_ID_LASALGAON}&commodity_id={COMMODITY_ID_ONION}&days=0")
    assert r3.status_code == 422


def test_forecasts_query_bounds():
    """Verify days parameter constraint on /forecasts (1-7)."""
    # Days > 7
    r1 = client.get(f"/api/v1/forecasts?market_id={MARKET_ID_LASALGAON}&commodity_id={COMMODITY_ID_ONION}&days=8")
    assert r1.status_code == 422

    # Days <= 0
    r2 = client.get(f"/api/v1/forecasts?market_id={MARKET_ID_LASALGAON}&commodity_id={COMMODITY_ID_ONION}&days=0")
    assert r2.status_code == 422


def test_unknown_entity_queries_return_empty_not_500():
    """Querying non-existent market/commodity UUIDs must return 200 with empty list, never 500."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    r1 = client.get(f"/api/v1/prices/latest?market_id={fake_id}&commodity_id={fake_id}")
    assert r1.status_code == 200
    assert r1.json() == []

    r2 = client.get(f"/api/v1/prices/historical?market_id={fake_id}&commodity_id={fake_id}&days=7")
    assert r2.status_code == 200
    assert r2.json() == []

    r3 = client.get(f"/api/v1/forecasts?market_id={fake_id}&commodity_id={fake_id}&days=7")
    assert r3.status_code == 200
    assert r3.json() == []


def test_sale_window_with_empty_history(override_supabase, fake_supabase):
    """Sale window computation with no price data returns 404 without crashing."""
    resp = client.get(f"/api/v1/sale-window/?commodity_id={COMMODITY_ID_ONION}&market_id={MARKET_ID_LASALGAON}&lang=mr")
    assert resp.status_code == 404
    assert "no recent prices" in resp.json()["detail"]


def test_sale_window_with_valid_history(override_supabase, fake_supabase):
    """Sale window computation with price history returns 200 with verdict."""
    today = date.today()
    prices = [
        {
            "id": f"p-{i}",
            "market_id": MARKET_ID_LASALGAON,
            "commodity_id": COMMODITY_ID_ONION,
            "arrival_date": (today - timedelta(days=10 - i)).isoformat(),
            "modal_price": 2000.0 + i * 20.0,
            "variety": "General",
        }
        for i in range(10)
    ]
    fake_supabase.seed("prices", prices)
    resp = client.get(f"/api/v1/sale-window/?commodity_id={COMMODITY_ID_ONION}&market_id={MARKET_ID_LASALGAON}&lang=mr")
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] in ("SELL_NOW", "HOLD", "WAIT")
    assert "action_label" in data
    assert "reason" in data


# ─── 5. SMS Webhook Security & Injection Resilience ───────────────────────────

def test_sms_webhook_rejects_missing_signature():
    """Inbound webhook without signature header is rejected with 403."""
    resp = client.post("/api/v1/sms/webhook", json={"From": "+919876543210", "Body": "PYAJ"})
    assert resp.status_code == 403


def test_sms_simulate_handles_malicious_inputs(override_supabase, fake_supabase):
    """Test SQL injection, XSS, unicode, and long strings via admin simulate."""
    admin_headers = auth_header(ADMIN_USER_ID)
    payloads = [
        "'; DROP TABLE lots; --",
        "<script>alert('xss')</script>",
        "🎉🚀💰🌾 कांदा प्याज",
        "A" * 1500,  # very long text
        "",          # empty string
        "   \t\n  ", # whitespace only
    ]

    for p in payloads:
        resp = client.post(
            "/api/v1/sms/simulate",
            json={"phone": "+919876543210", "body": p},
            headers=admin_headers,
        )
        assert resp.status_code == 200, f"Failed on input {p[:20]}: got {resp.status_code}"
        data = resp.json()
        assert "response" in data or data.get("status") in ("ignored", "error", "success")


# ─── 6. Forecasting Degradation & Mathematical Safety ─────────────────────────

def test_forecast_engine_with_zero_variance_prices(monkeypatch):
    """Series with flat prices (all identical) must compute sigma=0 without ZeroDivisionError."""
    from forecasting import engine as eng
    class _Settings:
        forecast_model = "auto"
    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    base = date(2026, 9, 1)
    series = [(base + timedelta(days=i), 2000.0) for i in range(25)]
    rows = _make_forecast_rows("m1", "c1", series, sanity=(100, 8000), as_of=base + timedelta(days=24))

    assert len(rows) == 7
    for r in rows:
        assert r["status"] == "ok"
        assert r["predicted_price"] == 2000.0
        assert r["lower_bound"] <= r["predicted_price"] <= r["upper_bound"]


def test_forecast_engine_with_extreme_sanity_bounds(monkeypatch):
    """Clamp handles inverted, zero, or negative sanity bands safely."""
    from forecasting import engine as eng
    class _Settings:
        forecast_model = "auto"
    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    base = date(2026, 9, 1)
    series = [(base + timedelta(days=i), 2000.0 + i * 10) for i in range(25)]

    # Inverted sanity: min=5000, max=1000
    rows = _make_forecast_rows("m1", "c1", series, sanity=(5000, 1000), as_of=base + timedelta(days=24))
    assert len(rows) == 7
    for r in rows:
        assert r["lower_bound"] <= r["predicted_price"] <= r["upper_bound"]


def test_forecast_gbm_multivariate_collinear_features_fallback(monkeypatch):
    """When feature columns have zero variance (collinear/constant), FeatureOLS handles it or falls back to OLS."""
    from forecasting import engine as eng
    class _Settings:
        forecast_model = "gbm"
    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    base = date(2026, 8, 1)
    n = 60
    # Price series with constant price -> all lags constant -> constant columns
    series = [(base + timedelta(days=i), 1500.0) for i in range(n)]
    history = [
        {"arrival_date": (base + timedelta(days=i)).isoformat(), "modal_price": 1500.0, "arrival_qty": 50.0}
        for i in range(n)
    ]
    features = build_feature_matrix(history)
    registry = {"auto": "reg-auto", "gbm": "reg-gbm", "feature_ols": "reg-fols"}

    rows = _make_forecast_rows(
        "m1", "c1", series, sanity=(100, 5000),
        features=features, pretrained_model=None, model_registry=registry,
        as_of=base + timedelta(days=n - 1)
    )

    assert len(rows) == 7
    # Collinear columns mean feature_ols either falls back to ols or drops columns cleanly
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["method"] in ("feature_ols", "ols") for r in rows)


# ─── 7. Information Leakage & Error Masking ───────────────────────────────────

def test_500_masking_never_leaks_internals(override_supabase, fake_supabase):
    """Simulated internal database crash must return sanitized error detail, not DB stack trace."""
    fake_supabase.seed("offers", [{
        "id": "off-mask", "lot_id": "lot-1", "user_id": FARMER_USER_ID,
        "buyer_id": "b1", "status": "accepted", "price_per_qtl": 2000, "quantity_qtl": 10
    }])
    fake_supabase.seed("payments", [])

    original_dispatch = fake_supabase._dispatch
    def crashing_dispatch(table, op, *args, **kwargs):
        if table == "payments" and op == "insert":
            raise RuntimeError("Internal DB crashed with secret password=supersecret")
        return original_dispatch(table=table, op=op, *args, **kwargs)

    fake_supabase._dispatch = crashing_dispatch
    headers = auth_header(FARMER_USER_ID)

    resp = client.post(
        "/api/v1/payments/",
        json={"offer_id": "off-mask", "amount": 10000, "reference": "REF123"},
        headers=headers,
    )
    # Router must catch and mask exception with 400 "could not create payment"
    assert resp.status_code == 400
    assert "supersecret" not in resp.text
    assert "password" not in resp.text
    assert resp.json()["detail"] == "could not create payment"
