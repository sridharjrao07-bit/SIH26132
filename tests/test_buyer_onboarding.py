from app.main import app
from fastapi.testclient import TestClient

from tests.conftest import ADMIN_USER_ID, FARMER_USER_ID, mint_jwt

client = TestClient(app)


def test_buyer_registration(override_supabase):
    """A regular user can register as a buyer."""
    token = mint_jwt(FARMER_USER_ID)

    # 1. Register with all 11 fields
    payload = {
        "name": "Acme Traders",
        "type": "trader",
        "district": "Nashik",
        "phone": "9999988888",
        "commodity_id": "cccc-0000-0000-0000",
        "demand_qty_qtl": 100.0,
        "max_price": 2500.0,
        "quality_requirements": "Grade A only",
        "payment_reliability": "high",
        "lat": 19.99,
        "lng": 73.78,
    }
    resp = client.post(
        "/api/v1/buyers/register", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Acme Traders"
    assert data["type"] == "trader"
    assert data["district"] == "Nashik"
    assert data["phone"] == "9999988888"
    assert data["commodity_id"] == "cccc-0000-0000-0000"
    assert data["demand_qty_qtl"] == 100.0
    assert data["max_price"] == 2500.0
    assert data["quality_requirements"] == "Grade A only"
    assert data["payment_reliability"] == "high"
    assert data["lat"] == 19.99
    assert data["lng"] == 73.78
    assert data["verified"] is False
    # The schema might not expose owner_user_id or verification_state, but DB has it.

    # 2. Cannot register twice
    resp2 = client.post(
        "/api/v1/buyers/register", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp2.status_code == 409
    assert "already has a registered buyer profile" in resp2.json()["detail"]


def test_public_cannot_see_pending_buyers(override_supabase):
    """Pending buyers should not appear in the public list."""
    token = mint_jwt(FARMER_USER_ID)
    payload = {
        "name": "Secret Pending Buyer",
        "type": "trader",
        "district": "Pune",
        "phone": "9999988888",
    }
    resp = client.post(
        "/api/v1/buyers/register", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 201

    # Public list
    list_resp = client.get("/api/v1/buyers/?district=Pune")
    assert list_resp.status_code == 200
    names = [b["name"] for b in list_resp.json()]
    assert "Secret Pending Buyer" not in names


def test_admin_verification_workflow(override_supabase):
    """Admin can list pending buyers and approve/reject them."""
    user_token = mint_jwt(FARMER_USER_ID)
    admin_token = mint_jwt(ADMIN_USER_ID)

    # 1. User registers
    resp = client.post(
        "/api/v1/buyers/register",
        json={
            "name": "To Be Verified",
            "type": "processor",
            "district": "Nagpur",
            "phone": "1111122222",
        },
        headers={"Authorization": f"Bearer {user_token}"},
    )
    assert resp.status_code == 201
    buyer_id = resp.json()["id"]

    # 2. Admin lists pending
    list_resp = client.get(
        "/api/v1/admin/buyers?status=pending", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert list_resp.status_code == 200
    pending_ids = [b["id"] for b in list_resp.json()]
    assert buyer_id in pending_ids

    # 3. Admin approves
    approve_resp = client.patch(
        f"/api/v1/admin/buyers/{buyer_id}/verify",
        json={"verification_state": "approved", "review_notes": "Looks good"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert approve_resp.status_code == 200

    # 4. Buyer is now public
    pub_resp = client.get("/api/v1/buyers/?district=Nagpur")
    assert pub_resp.status_code == 200
    assert any(b["id"] == buyer_id for b in pub_resp.json())


def test_cross_tenant_isolation_for_pending_buyers(override_supabase, fake_supabase):
    """A user cannot read another user's pending buyer profile."""
    from tests.conftest import FARMER_USER_ID, FPO_USER_ID, RlsFakeSupabase

    # 1. Seed buyers directly
    fake_supabase.seed(
        "buyers",
        [
            {
                "id": "buyer-1",
                "owner_user_id": FARMER_USER_ID,
                "name": "Pending Farmer Buyer",
                "verified": False,
            },
            {
                "id": "buyer-2",
                "owner_user_id": FPO_USER_ID,
                "name": "Verified FPO Buyer",
                "verified": True,
            },
        ],
    )

    # 2. FARMER queries buyers via user client
    farmer_client = RlsFakeSupabase(fake_supabase, uid=FARMER_USER_ID)
    farmer_res = farmer_client.table("buyers").select("*").execute()

    # FARMER sees their own pending buyer + all verified buyers
    farmer_ids = [b["id"] for b in farmer_res.data]
    assert "buyer-1" in farmer_ids, "Owner must see their own pending profile"
    assert "buyer-2" in farmer_ids, "Public verified profiles must be visible"

    # 3. FPO queries buyers via user client
    fpo_client = RlsFakeSupabase(fake_supabase, uid=FPO_USER_ID)
    fpo_res = fpo_client.table("buyers").select("*").execute()

    # FPO sees their own verified buyer, but NOT FARMER's pending buyer
    fpo_ids = [b["id"] for b in fpo_res.data]
    assert "buyer-2" in fpo_ids
    assert "buyer-1" not in fpo_ids, "Users must not see other users' pending profiles"

    # 4. Anon queries buyers
    anon_client = RlsFakeSupabase(fake_supabase, uid=None)
    anon_res = anon_client.table("buyers").select("*").execute()
    anon_ids = [b["id"] for b in anon_res.data]
    assert "buyer-2" in anon_ids
    assert "buyer-1" not in anon_ids, "Anon must not see pending profiles"
