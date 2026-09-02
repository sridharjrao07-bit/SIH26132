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


def test_sms_reply_includes_sale_window(override_supabase, fake_supabase, tmp_path, monkeypatch):
    from notifications.sms_gateway import MockSMSGateway
    from tests.conftest import mint_jwt, ADMIN_USER_ID

    monkeypatch.setattr(
        "app.routers.sms.get_sms_gateway",
        lambda: MockSMSGateway(log_file=str(tmp_path / "sms.log")),
    )
    for row in fake_supabase._data["commodity_alias"]:
        if row.get("source") == "sms":
            row["commodities"] = {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"}
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "modal_price": 2100.0,
        "arrival_qty": 1500,
        "source": "data_gov_in",
        "variety": "General",
        "markets": {"name": "Lasalgaon APCM"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today,
        "predicted_price": 1800.0,
        "status": "ok",
    }])
    fake_supabase.set_rpc(
        "nearest_market",
        [{"id": MARKET_ID_LASALGAON, "name": "Lasalgaon APCM", "distance_km": 3.2}],
    )
    resp = client.post(
        "/api/v1/sms/simulate",
        json={"sender": "9876543210", "message": "PYAJ"},
        headers={"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "replied"
    assert body["recommendation"] == "sell"
    assert "विका" in body["message"] or "SELL" in body["message"] or "बेचें" in body["message"]


def test_fpo_lists_member_lots(override_supabase, fake_supabase):
    from tests.conftest import FPO_USER_ID, mint_jwt
    fake_supabase.seed("lots", [{
        "id": "lot-fpo-1",
        "user_id": FARMER_USER_ID,
        "fpo_id": FPO_USER_ID,
        "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 40,
        "grade": "FAQ",
        "status": "open",
        "created_at": date.today().isoformat(),
    }])
    resp = client.get(
        "/api/v1/lots/",
        headers={"Authorization": f"Bearer {mint_jwt(FPO_USER_ID)}"},
    )
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.json()]
    assert "lot-fpo-1" in ids


def test_format_sale_and_alert_sms_fit_ucs2():
    from notifications.sale_window import format_sale_sms, format_alert_sms
    mr_sale = format_sale_sms("mr", "कांदा", 2100, "Lasalgaon", "sell")
    hi_sale = format_sale_sms("hi", "प्याज", 2100, "Lasalgaon", "hold")
    mr_alert = format_alert_sms("mr", "कांदा", 2300, 2200, "direct")
    hi_alert = format_alert_sms("hi", "प्याज", 2300, 2200, "direct")
    assert "विका" in mr_sale
    assert "रुकें" in hi_sale
    assert len(mr_sale) <= 70
    assert len(hi_sale) <= 70
    assert len(mr_alert) <= 70
    assert len(hi_alert) <= 70
    assert "ओलांडली" in mr_alert
