"""Judge-facing walkthrough tests — appended by audit HIGH patch."""
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import FARMER_USER_ID, mint_jwt

client = TestClient(app, raise_server_exceptions=False)


def farmer():
    return {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}


def test_judge_payment_create_is_idempotent(override_supabase, fake_supabase):
    fake_supabase.seed(
        "lots",
        [{"id": "lot-idemp", "user_id": FARMER_USER_ID, "status": "matched", "quantity_qtl": 10}],
    )
    fake_supabase.seed(
        "offers",
        [{
            "id": "off-idemp",
            "lot_id": "lot-idemp",
            "buyer_id": "b1",
            "user_id": FARMER_USER_ID,
            "status": "accepted",
            "quantity_qtl": 10,
        }],
    )
    fake_supabase.seed("payments", [])
    body = {"offer_id": "off-idemp", "amount": 20000, "reference": "UPI-1"}
    a = client.post("/api/v1/payments/", json=body, headers=farmer())
    b = client.post("/api/v1/payments/", json=body, headers=farmer())
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json()["id"] == b.json()["id"]
    pending = [p for p in fake_supabase._data["payments"] if p.get("status") == "pending"]
    assert len(pending) == 1


def test_judge_metrics_is_public_and_secretless():
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "kb_up 1" in r.text
    assert "service_role" not in r.text.lower()
    assert "jwt" not in r.text.lower()
