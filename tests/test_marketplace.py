"""Marketplace / market-linkage API tests (SIH26132 expected solution)."""
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import (
    MARKET_ID_LASALGAON,
    MARKET_ID_PIMPALGAON,
    COMMODITY_ID_ONION,
    COMMODITY_ID_TOMATO,
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


def test_sale_window_hold_without_storage_becomes_sell(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "modal_price": 2000.0,
        "arrival_qty": 50,
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today,
        "predicted_price": 2200.0,
        "status": "ok",
    }])
    fake_supabase.seed("logistics_options", [])
    resp = client.get(
        f"/api/v1/sale-window/?commodity_id={COMMODITY_ID_ONION}&market_id={MARKET_ID_LASALGAON}"
    )
    assert resp.status_code == 200
    assert resp.json()["recommendation"] == "sell"
    assert "storage" in resp.json()["reason"].lower()


def test_sale_window_hold_when_storage_listed(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "modal_price": 2000.0,
        "arrival_qty": 50,
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today,
        "predicted_price": 2200.0,
        "status": "ok",
    }])
    fake_supabase.seed("logistics_options", [{
        "id": "st-1", "district": "Nashik", "kind": "storage",
        "name": "MSWC Lasalgaon Godown", "is_active": True, "capacity_qtl": 5000,
    }])
    resp = client.get(
        f"/api/v1/sale-window/?commodity_id={COMMODITY_ID_ONION}&market_id={MARKET_ID_LASALGAON}"
    )
    assert resp.status_code == 200
    assert resp.json()["recommendation"] == "hold"
    assert resp.json()["storage"]


def test_lot_rejects_unknown_grade(override_supabase, fake_supabase):
    resp = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 10,
        "grade": "Reject",
    }, headers=farmer_headers())
    assert resp.status_code == 422


def test_lot_grade_patch_records_assay(override_supabase, fake_supabase):
    fake_supabase.seed("lots", [{
        "id": "lot-g", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 20, "grade": "General", "status": "open",
    }])
    resp = client.patch("/api/v1/lots/lot-g/grade", json={
        "grade": "FAQ",
        "quality_notes": "Dry, 50kg bags, visual FAQ",
    }, headers=farmer_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["grade"] == "FAQ"
    sold = client.patch("/api/v1/lots/lot-g/grade", json={"grade": "Special"}, headers=farmer_headers())
    # still open — allowed
    assert sold.status_code == 200
    fake_supabase._data["lots"][0]["status"] = "sold"
    blocked = client.patch("/api/v1/lots/lot-g/grade", json={"grade": "FAQ"}, headers=farmer_headers())
    assert blocked.status_code == 409


def test_farmer_cannot_verify_buyer(override_supabase, fake_supabase):
    resp = client.patch("/api/v1/admin/buyers/buyer-1/verify", headers=farmer_headers())
    assert resp.status_code == 403


def test_admin_verify_buyer_and_resolve_grievance(override_supabase, fake_supabase):
    from tests.conftest import ADMIN_USER_ID
    fake_supabase.seed("buyers", [{
        "id": "buyer-new", "name": "New Desk", "type": "trader",
        "verified": False, "district": "Nashik",
    }])
    fake_supabase.seed("grievances", [{
        "id": "g-1", "user_id": FARMER_USER_ID, "category": "payment",
        "description": "Payment delayed", "status": "open",
        "created_at": date.today().isoformat(),
    }])
    headers = {"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"}
    v = client.patch("/api/v1/admin/buyers/buyer-new/verify", headers=headers)
    assert v.status_code == 200, v.text
    assert v.json()["verified"] is True
    listed = client.get("/api/v1/admin/grievances", headers=headers)
    assert listed.status_code == 200
    resolved = client.patch(
        "/api/v1/admin/grievances/g-1",
        json={"status": "resolved"},
        headers=headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_fpo_aggregate_lots(override_supabase, fake_supabase):
    from tests.conftest import FPO_USER_ID
    fake_supabase.seed("lots", [
        {
            "id": "m1", "user_id": FARMER_USER_ID, "fpo_id": FPO_USER_ID,
            "commodity_id": COMMODITY_ID_ONION, "quantity_qtl": 10,
            "grade": "FAQ", "status": "open", "asking_price": 2000,
        },
        {
            "id": "m2", "user_id": FARMER_USER_ID, "fpo_id": FPO_USER_ID,
            "commodity_id": COMMODITY_ID_ONION, "quantity_qtl": 15,
            "grade": "FAQ", "status": "open", "asking_price": 2100,
        },
    ])
    resp = client.post(
        "/api/v1/lots/aggregate",
        json={"lot_ids": ["m1", "m2"], "asking_price": 2050},
        headers={"Authorization": f"Bearer {mint_jwt(FPO_USER_ID)}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["quantity_qtl"] == 25
    assert resp.json()["fpo_id"] == FPO_USER_ID
    farmer_blocked = client.post(
        "/api/v1/lots/aggregate",
        json={"lot_ids": ["m1", "m2"]},
        headers=farmer_headers(),
    )
    assert farmer_blocked.status_code == 403


def test_stale_offer_expires_and_cannot_be_accepted(override_supabase, fake_supabase):
    from datetime import timedelta
    from tests.conftest import ADMIN_USER_ID
    past = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    fake_supabase.seed("lots", [{
        "id": "lot-old", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 20, "grade": "FAQ", "status": "offered",
    }])
    fake_supabase.seed("offers", [{
        "id": "off-old", "lot_id": "lot-old", "buyer_id": "buyer-1",
        "user_id": FARMER_USER_ID, "price_per_qtl": 2000, "quantity_qtl": 20,
        "status": "pending", "created_at": past,
    }])
    admin = {"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"}
    expired = client.post("/api/v1/admin/offers/expire", headers=admin)
    assert expired.status_code == 200, expired.text
    assert expired.json()["expired"] == 1
    lot = next(r for r in fake_supabase._data["lots"] if r["id"] == "lot-old")
    assert lot["status"] == "open"
    acc = client.patch(
        "/api/v1/offers/off-old",
        json={"status": "accepted"},
        headers=farmer_headers(),
    )
    assert acc.status_code == 409


def test_fresh_offer_includes_expires_at(override_supabase, fake_supabase):
    fake_supabase.seed("lots", [{
        "id": "lot-new", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 10, "grade": "General", "status": "open",
    }])
    fake_supabase.seed("buyers", [{
        "id": "buyer-1", "name": "Desk", "type": "trader", "verified": True,
    }])
    resp = client.post("/api/v1/offers/", json={
        "lot_id": "lot-new",
        "buyer_id": "buyer-1",
        "price_per_qtl": 1900,
        "quantity_qtl": 10,
    }, headers=farmer_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["expires_at"]
    assert resp.json()["status"] == "pending"


def test_disputed_payment_lowers_buyer_reliability(override_supabase, fake_supabase):
    fake_supabase.seed("buyers", [{
        "id": "buyer-1", "name": "Desk", "type": "trader",
        "verified": True, "payment_reliability": "high",
    }])
    fake_supabase.seed("lots", [{
        "id": "lot-p", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 10, "status": "matched",
    }])
    fake_supabase.seed("offers", [{
        "id": "off-p", "lot_id": "lot-p", "buyer_id": "buyer-1",
        "user_id": FARMER_USER_ID, "status": "accepted", "price_per_qtl": 2000,
        "quantity_qtl": 10,
    }])
    fake_supabase.seed("payments", [{
        "id": "pay-1", "offer_id": "off-p", "user_id": FARMER_USER_ID,
        "amount": 20000, "status": "pending",
    }])
    disp = client.patch("/api/v1/payments/pay-1/disputed", headers=farmer_headers())
    assert disp.status_code == 200, disp.text
    assert disp.json()["status"] == "disputed"
    buyer = next(b for b in fake_supabase._data["buyers"] if b["id"] == "buyer-1")
    assert buyer["payment_reliability"] == "low"


def test_two_paid_settlements_mark_buyer_high(override_supabase, fake_supabase):
    fake_supabase.seed("buyers", [{
        "id": "buyer-1", "name": "Desk", "type": "trader",
        "verified": True, "payment_reliability": "medium",
    }])
    fake_supabase.seed("offers", [
        {"id": "o1", "buyer_id": "buyer-1", "user_id": FARMER_USER_ID, "status": "accepted", "lot_id": "l1"},
        {"id": "o2", "buyer_id": "buyer-1", "user_id": FARMER_USER_ID, "status": "accepted", "lot_id": "l2"},
    ])
    fake_supabase.seed("lots", [
        {"id": "l1", "user_id": FARMER_USER_ID, "status": "matched", "commodity_id": COMMODITY_ID_ONION, "quantity_qtl": 1},
        {"id": "l2", "user_id": FARMER_USER_ID, "status": "matched", "commodity_id": COMMODITY_ID_ONION, "quantity_qtl": 1},
    ])
    fake_supabase.seed("payments", [
        {"id": "p1", "offer_id": "o1", "user_id": FARMER_USER_ID, "amount": 100, "status": "pending"},
        {"id": "p2", "offer_id": "o2", "user_id": FARMER_USER_ID, "amount": 100, "status": "pending"},
    ])
    assert client.patch("/api/v1/payments/p1/paid", headers=farmer_headers()).status_code == 200
    assert client.patch("/api/v1/payments/p2/paid", headers=farmer_headers()).status_code == 200
    buyer = next(b for b in fake_supabase._data["buyers"] if b["id"] == "buyer-1")
    assert buyer["payment_reliability"] == "high"


def test_sale_window_marathi_and_hindi(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "modal_price": 2000.0,
        "arrival_qty": 1500,
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today,
        "predicted_price": 1800.0,
        "status": "ok",
    }])
    mr = client.get(
        f"/api/v1/sale-window/?commodity_id={COMMODITY_ID_ONION}&market_id={MARKET_ID_LASALGAON}&lang=mr"
    )
    hi = client.get(
        f"/api/v1/sale-window/?commodity_id={COMMODITY_ID_ONION}&market_id={MARKET_ID_LASALGAON}&lang=hi"
    )
    assert mr.status_code == 200
    assert hi.status_code == 200
    assert mr.json()["recommendation"] == "sell"
    assert mr.json()["lang"] == "mr"
    assert "विका" in mr.json()["reason"]
    assert "बेचें" in hi.json()["reason"]


def test_reliability_scoring_unit():
    from app.services.marketplace import score_payment_reliability
    assert score_payment_reliability(0, 0, 0, 0) is None
    assert score_payment_reliability(2, 0, 0, 0) == "high"
    assert score_payment_reliability(1, 0, 0, 0) == "medium"
    assert score_payment_reliability(0, 0, 1, 0) == "low"
    assert score_payment_reliability(0, 2, 0, 0) == "low"


def test_local_buyer_outranks_distant_high_bid(override_supabase, fake_supabase):
    fake_supabase.seed("buyers", [
        {
            "id": "local",
            "name": "Lasalgaon Onion Traders",
            "type": "trader",
            "verified": True,
            "district": "Nashik",
            "commodity_id": COMMODITY_ID_ONION,
            "demand_qty_qtl": 80,
            "max_price": 2050,
            "payment_reliability": "medium",
            "lat": 20.12,
            "lng": 74.33,
        },
        {
            "id": "pune",
            "name": "Pune Export Desk",
            "type": "processor",
            "verified": True,
            "district": "Pune",
            "commodity_id": COMMODITY_ID_ONION,
            "demand_qty_qtl": 5000,
            "max_price": 3500,
            "payment_reliability": "high",
            "lat": 18.52,
            "lng": 73.85,
        },
    ])
    lot_resp = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION,
        "market_id": MARKET_ID_LASALGAON,
        "quantity_qtl": 50,
        "grade": "FAQ",
        "asking_price": 2000,
    }, headers=farmer_headers())
    lot_id = lot_resp.json()["id"]
    matches = client.get(f"/api/v1/lots/{lot_id}/matches", headers=farmer_headers())
    assert matches.status_code == 200, matches.text
    body = matches.json()
    assert body["best_buyer"]["buyer_id"] == "local"
    assert body["matches"][0]["buyer_id"] == "local"
    assert body["matches"][1]["buyer_id"] == "pune"
    assert "local" in body["advice"].lower() or "Lasalgaon" in body["advice"]


def test_lot_advice_sell_now_names_best_local_buyer(override_supabase, fake_supabase):
    today = date.today().isoformat()
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
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "modal_price": 2000.0,
        "arrival_qty": 1500,
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today,
        "predicted_price": 1800.0,
        "status": "ok",
    }])
    fake_supabase.seed("logistics_options", [])
    lot_resp = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION,
        "market_id": MARKET_ID_LASALGAON,
        "quantity_qtl": 50,
        "grade": "FAQ",
        "asking_price": 2000,
    }, headers=farmer_headers())
    lot_id = lot_resp.json()["id"]
    advice = client.get(f"/api/v1/lots/{lot_id}/advice", headers=farmer_headers())
    assert advice.status_code == 200, advice.text
    body = advice.json()
    assert body["action"] == "SELL_NOW"
    assert body["best_buyer"]["buyer_id"] == "buyer-1"
    assert body["sale_window"]["supply_pressure"] == "high"
    assert body["sale_window"]["storage_available"] is False


def test_sale_window_hold_through_glut_when_storage_nearby(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "modal_price": 2000.0,
        "arrival_qty": 1500,
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today,
        "predicted_price": 2200.0,
        "status": "ok",
    }])
    fake_supabase.seed("logistics_options", [{
        "id": "st-1", "district": "Nashik", "kind": "storage",
        "name": "MSWC Lasalgaon Godown", "is_active": True,
        "capacity_qtl": 5000, "lat": 20.12, "lng": 74.33,
    }])
    resp = client.get(
        f"/api/v1/sale-window/?commodity_id={COMMODITY_ID_ONION}&market_id={MARKET_ID_LASALGAON}"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["action"] == "HOLD"
    assert body["supply_pressure"] == "high"
    assert body["storage_available"] is True


def test_sale_window_exposes_sell_now_action(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today,
        "modal_price": 2000.0,
        "arrival_qty": 1500,
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
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
    assert resp.json()["action"] == "SELL_NOW"
    assert resp.json()["action_label"] == "Sell Now"


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
    with_buyer = format_sale_sms("mr", "कांदा", 2100, "Lasalgaon", "sell", buyer="Lasalgaon Onion Traders")
    assert "Lasalgaon" in with_buyer
    assert len(with_buyer) <= 70


def test_sale_window_flags_better_nearby_mandi(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed("prices", [
        {
            "market_id": MARKET_ID_LASALGAON,
            "commodity_id": COMMODITY_ID_ONION,
            "arrival_date": today,
            "modal_price": 2000.0,
            "arrival_qty": 1500,
            "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
        },
        {
            "market_id": MARKET_ID_PIMPALGAON,
            "commodity_id": COMMODITY_ID_ONION,
            "arrival_date": today,
            "modal_price": 2300.0,
            "arrival_qty": 400,
            "markets": {"name": "Pimpalgaon Baswant APCM", "district": "Nashik"},
        },
    ])
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
    better = resp.json()["better_market"]
    assert better["market"] == "Pimpalgaon Baswant APCM"
    assert better["premium_rs"] == 300
    assert "Pimpalgaon" in resp.json()["reason"]


def test_buyer_supply_lists_fitting_open_lots(override_supabase, fake_supabase):
    fake_supabase.seed("buyers", [{
        "id": "buyer-1",
        "name": "Lasalgaon Onion Traders",
        "type": "trader",
        "verified": True,
        "district": "Nashik",
        "commodity_id": COMMODITY_ID_ONION,
        "demand_qty_qtl": 80,
        "max_price": 2200,
        "quality_requirements": "FAQ / General",
    }])
    fake_supabase.seed("lots", [
        {
            "id": "fit", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
            "market_id": MARKET_ID_LASALGAON, "quantity_qtl": 40, "grade": "FAQ",
            "asking_price": 2000, "status": "open",
        },
        {
            "id": "tomato", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_TOMATO,
            "market_id": MARKET_ID_LASALGAON, "quantity_qtl": 10, "grade": "General",
            "asking_price": 1500, "status": "open",
        },
        {
            "id": "sold", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
            "market_id": MARKET_ID_LASALGAON, "quantity_qtl": 10, "grade": "FAQ",
            "asking_price": 2000, "status": "sold",
        },
    ])
    resp = client.get("/api/v1/buyers/buyer-1/supply")
    assert resp.status_code == 200, resp.text
    ids = [l["id"] for l in resp.json()["lots"]]
    assert ids == ["fit"]
    assert "same_district" in resp.json()["lots"][0]["reasons"]
    missing = client.get("/api/v1/buyers/nope/supply")
    assert missing.status_code == 404


def test_lot_ledger_is_a_transaction_trail(override_supabase, fake_supabase):
    fake_supabase.seed("lots", [{
        "id": "lot-led", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 20, "grade": "FAQ", "status": "sold", "asking_price": 2000,
        "created_at": "2026-09-01T10:00:00+00:00",
    }])
    fake_supabase.seed("offers", [{
        "id": "off-led", "lot_id": "lot-led", "buyer_id": "buyer-1",
        "user_id": FARMER_USER_ID, "status": "accepted", "price_per_qtl": 2050,
        "quantity_qtl": 20, "created_at": "2026-09-01T11:00:00+00:00",
    }])
    fake_supabase.seed("payments", [{
        "id": "pay-led", "offer_id": "off-led", "user_id": FARMER_USER_ID,
        "amount": 41000, "status": "paid", "reference": "UPI-1",
        "paid_at": "2026-09-01T12:00:00+00:00",
    }])
    fake_supabase.seed("grievances", [{
        "id": "g-led", "lot_id": "lot-led", "user_id": FARMER_USER_ID,
        "category": "quality", "description": "Bags were wet on arrival",
        "status": "open", "created_at": "2026-09-01T13:00:00+00:00",
    }])
    resp = client.get("/api/v1/lots/lot-led/ledger", headers=farmer_headers())
    assert resp.status_code == 200, resp.text
    types = [e["type"] for e in resp.json()["events"]]
    assert "lot_created" in types
    assert "offer_accepted" in types
    assert "payment_paid" in types
    assert "grievance_open" in types
    assert resp.json()["payments"][0]["amount"] == 41000


def test_sms_names_best_local_buyer_when_lot_open(override_supabase, fake_supabase, tmp_path, monkeypatch):
    from notifications.sms_gateway import MockSMSGateway
    from tests.conftest import ADMIN_USER_ID
    monkeypatch.setattr(
        "app.routers.sms.get_sms_gateway",
        lambda: MockSMSGateway(log_file=str(tmp_path / "sms.log")),
    )
    for row in fake_supabase._data["commodity_alias"]:
        if row.get("source") == "sms":
            row["commodities"] = {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"}
    today = date.today().isoformat()
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today, "modal_price": 2100.0, "arrival_qty": 1500,
        "source": "data_gov_in", "variety": "General",
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today, "predicted_price": 1800.0, "status": "ok",
    }])
    fake_supabase.seed("buyers", [{
        "id": "buyer-1", "name": "Lasalgaon Onion Traders", "type": "trader",
        "verified": True, "district": "Nashik", "commodity_id": COMMODITY_ID_ONION,
        "demand_qty_qtl": 800, "max_price": 2400, "lat": 20.12, "lng": 74.33,
    }])
    fake_supabase.seed("lots", [{
        "id": "lot-sms", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 40, "grade": "FAQ", "asking_price": 2000, "status": "open",
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
    assert resp.json()["status"] == "replied"
    assert "Lasalgaon" in resp.json()["message"]
    assert "विका" in resp.json()["message"] or "SELL" in resp.json()["message"]


def test_book_storage_and_confirm(override_supabase, fake_supabase):
    fake_supabase.seed("logistics_options", [{
        "id": "st-1", "district": "Nashik", "kind": "storage",
        "name": "MSWC Lasalgaon Godown", "is_active": True, "capacity_qtl": 5000,
        "rate_per_qtl": 8,
    }])
    fake_supabase.seed("lots", [{
        "id": "lot-bk", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 40, "grade": "FAQ", "status": "open",
    }])
    fake_supabase.seed("logistics_bookings", [])
    booked = client.post("/api/v1/logistics/bookings", json={
        "lot_id": "lot-bk",
        "logistics_id": "st-1",
        "quantity_qtl": 40,
    }, headers=farmer_headers())
    assert booked.status_code == 200, booked.text
    assert booked.json()["status"] == "requested"
    assert booked.json()["kind"] == "storage"
    bid = booked.json()["id"]
    confirmed = client.patch(
        f"/api/v1/logistics/bookings/{bid}",
        json={"status": "confirmed"},
        headers=farmer_headers(),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
    listed = client.get("/api/v1/logistics/bookings?lot_id=lot-bk", headers=farmer_headers())
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == bid


def test_booking_rejected_when_capacity_exceeded(override_supabase, fake_supabase):
    fake_supabase.seed("logistics_options", [{
        "id": "st-small", "district": "Nashik", "kind": "storage",
        "name": "Tiny Godown", "is_active": True, "capacity_qtl": 50,
    }])
    fake_supabase.seed("lots", [{
        "id": "lot-cap", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 80, "grade": "FAQ", "status": "open",
    }])
    fake_supabase.seed("logistics_bookings", [{
        "id": "existing", "user_id": FARMER_USER_ID, "lot_id": "other",
        "logistics_id": "st-small", "kind": "storage", "quantity_qtl": 40,
        "status": "confirmed",
    }])
    resp = client.post("/api/v1/logistics/bookings", json={
        "lot_id": "lot-cap",
        "logistics_id": "st-small",
        "quantity_qtl": 20,
    }, headers=farmer_headers())
    assert resp.status_code == 409


def test_cannot_book_sold_lot(override_supabase, fake_supabase):
    fake_supabase.seed("logistics_options", [{
        "id": "tr-1", "district": "Nashik", "kind": "transport",
        "name": "Niphad Mandi Tempo Pool", "is_active": True, "capacity_qtl": 200,
    }])
    fake_supabase.seed("lots", [{
        "id": "lot-sold", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 10, "status": "sold",
    }])
    resp = client.post("/api/v1/logistics/bookings", json={
        "lot_id": "lot-sold",
        "logistics_id": "tr-1",
    }, headers=farmer_headers())
    assert resp.status_code == 409


def test_lot_advice_next_step_is_book_transport_on_sell_now(override_supabase, fake_supabase):
    today = date.today().isoformat()
    fake_supabase.seed("buyers", [{
        "id": "buyer-1", "name": "Lasalgaon Onion Traders", "type": "trader",
        "verified": True, "district": "Nashik", "commodity_id": COMMODITY_ID_ONION,
        "demand_qty_qtl": 800, "max_price": 2400, "lat": 20.12, "lng": 74.33,
    }])
    fake_supabase.seed("prices", [{
        "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": today, "modal_price": 2000.0, "arrival_qty": 1500,
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
    }])
    fake_supabase.seed("forecasts", [{
        "market_id": MARKET_ID_LASALGAON, "commodity_id": COMMODITY_ID_ONION,
        "forecast_date": today, "predicted_price": 1800.0, "status": "ok",
    }])
    fake_supabase.seed("logistics_options", [{
        "id": "tr-1", "district": "Nashik", "kind": "transport",
        "name": "Niphad Mandi Tempo Pool", "is_active": True, "capacity_qtl": 200,
    }])
    fake_supabase.seed("logistics_bookings", [])
    lot_resp = client.post("/api/v1/lots/", json={
        "commodity_id": COMMODITY_ID_ONION,
        "market_id": MARKET_ID_LASALGAON,
        "quantity_qtl": 20,
        "grade": "FAQ",
        "asking_price": 2000,
    }, headers=farmer_headers())
    lot_id = lot_resp.json()["id"]
    advice = client.get(f"/api/v1/lots/{lot_id}/advice", headers=farmer_headers())
    assert advice.status_code == 200, advice.text
    assert advice.json()["action"] == "SELL_NOW"
    assert "Niphad" in (advice.json()["next_step"] or "")


def test_ledger_includes_logistics_booking(override_supabase, fake_supabase):
    fake_supabase.seed("lots", [{
        "id": "lot-led2", "user_id": FARMER_USER_ID, "commodity_id": COMMODITY_ID_ONION,
        "quantity_qtl": 20, "grade": "FAQ", "status": "open",
        "created_at": "2026-09-01T10:00:00+00:00",
    }])
    fake_supabase.seed("offers", [])
    fake_supabase.seed("payments", [])
    fake_supabase.seed("grievances", [])
    fake_supabase.seed("logistics_bookings", [{
        "id": "bk-1", "lot_id": "lot-led2", "user_id": FARMER_USER_ID,
        "logistics_id": "st-1", "kind": "storage", "quantity_qtl": 20,
        "status": "confirmed", "created_at": "2026-09-01T11:00:00+00:00",
    }])
    resp = client.get("/api/v1/lots/lot-led2/ledger", headers=farmer_headers())
    assert resp.status_code == 200, resp.text
    types = [e["type"] for e in resp.json()["events"]]
    assert "booking_confirmed" in types
    assert resp.json()["bookings"][0]["id"] == "bk-1"
