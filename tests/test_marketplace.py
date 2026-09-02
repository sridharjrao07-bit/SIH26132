"""Marketplace / market-linkage API tests (SIH26132 expected solution)."""
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import (
    MARKET_ID_LASALGAON,
    COMMODITY_ID_ONION,
    FARMER_USER_ID,
    mint_jwt,
)

client = TestClient(app, raise_server_exceptions=False)


def farmer_headers():
    return {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}


def test_list_buyers_public(override_supabase, fake_supabase):
    fake_supabase.seed("buyers", [
        {
            "id": "buyer-1",
            "name": "Lasalgaon Onion Traders",
            "type": "trader",
            "verified": True,
            "district": "Nashik",
            "commodity_id": COMMODITY_ID_ONION,
            "demand_qty_qtl": 800,
            "max_price": 2400,
            "payment_reliability": "high",
        },
        {
            "id": "buyer-unv",
            "name": "Unverified Desk",
            "type": "trader",
            "verified": False,
            "district": "Nashik",
            "commodity_id": COMMODITY_ID_ONION,
        },
    ])
    resp = client.get("/api/v1/buyers/")
    assert resp.status_code == 200
    names = [b["name"] for b in resp.json()]
    assert "Lasalgaon Onion Traders" in names
    assert "Unverified Desk" not in names


def test_lot_requires_auth():
    resp = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 10,
    })
    assert resp.status_code == 401


def test_lot_offer_payment_grievance_flow(override_supabase, fake_supabase):
    fake_supabase.seed("buyers", [{
        "id": "buyer-1",
        "name": "Lasalgaon Onion Traders",
        "type": "trader",
        "verified": True,
        "district": "Nashik",
        "commodity_id": COMMODITY_ID_ONION,
        "demand_qty_qtl": 800,
        "max_price": 2400,
        "payment_reliability": "high",
        "lat": 20.12,
        "lng": 74.33,
    }])
    fake_supabase.seed("lots", [])
    fake_supabase.seed("offers", [])
    fake_supabase.seed("payments", [])
    fake_supabase.seed("grievances", [])

    lot_resp = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION,
        "market_id": MARKET_ID_LASALGAON,
        "quantity_qtl": 50,
        "grade": "FAQ",
        "asking_price": 2000,
    }, headers=farmer_headers())
    assert lot_resp.status_code == 200, lot_resp.text
    lot_id = lot_resp.json()["id"]

    matches = client.get(f"/api/v1/lots/{lot_id}/matches", headers=farmer_headers())
    assert matches.status_code == 200
    assert matches.json()["matches"]
    assert matches.json()["matches"][0]["buyer_id"] == "buyer-1"

    offer_resp = client.post("/api/v1/offers/", json={
        "lot_id": lot_id,
        "buyer_id": "buyer-1",
        "price_per_qtl": 2050,
        "quantity_qtl": 50,
    }, headers=farmer_headers())
    assert offer_resp.status_code == 200, offer_resp.text
    offer_id = offer_resp.json()["id"]

    acc = client.patch(f"/api/v1/offers/{offer_id}", json={"status": "accepted"},
                       headers=farmer_headers())
    assert acc.status_code == 200
    assert acc.json()["status"] == "accepted"

    pay = client.post("/api/v1/payments/", json={
        "offer_id": offer_id,
        "amount": 102500,
        "reference": "UPI-DEMO-1",
    }, headers=farmer_headers())
    assert pay.status_code == 200
    payment_id = pay.json()["id"]

    paid = client.patch(f"/api/v1/payments/{payment_id}/paid", headers=farmer_headers())
    assert paid.status_code == 200
    assert paid.json()["status"] == "paid"

    grief = client.post("/api/v1/grievances/", json={
        "category": "quality",
        "description": "Bags were wet on arrival",
        "offer_id": offer_id,
        "lot_id": lot_id,
    }, headers=farmer_headers())
    assert grief.status_code == 200
    assert grief.json()["status"] == "open"


def test_profile_get_and_patch(override_supabase, fake_supabase):
    me = client.get("/api/v1/me/", headers=farmer_headers())
    assert me.status_code == 200
    assert me.json()["id"] == FARMER_USER_ID

    patched = client.patch("/api/v1/me/", json={"phone": "9123456789", "preferred_language": "hi"},
                           headers=farmer_headers())
    assert patched.status_code == 200
    assert patched.json()["phone"] == "+919123456789"
    assert patched.json()["preferred_language"] == "hi"


def test_sale_window(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "modal_price": 2000.0,
        "arrival_qty": 1500,
        "markets": {"name": "Lasalgaon APCM"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today,
        "predicted_price": 1800.0,
        "status": "ok",
    }])
    resp = client.get(
        f"/api/v1/sale-window/?commodity_id={COMMODITY_ID_ONION}&market_id={MARKET_ID_LASALGAON}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommendation"] in ("sell", "hold", "wait")
    assert body["latest_price"] == 2000.0


def test_logistics_list(override_supabase, fake_supabase):
    fake_supabase.seed("logistics_options", [{
        "id": "log-1",
        "district": "Nashik",
        "kind": "storage",
        "name": "MSWC Lasalgaon Godown",
        "capacity_qtl": 5000,
        "rate_per_qtl": 8,
        "is_active": True,
    }])
    resp = client.get("/api/v1/logistics/?district=Nashik")
    assert resp.status_code == 200
    assert resp.json()[0]["name"] == "MSWC Lasalgaon Godown"


def test_docs_available_in_development():
    resp = client.get("/docs")
    assert resp.status_code == 200
