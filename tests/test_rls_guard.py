from fastapi.testclient import TestClient
from app.main import app
from tests.conftest import FARMER_USER_ID, ADMIN_USER_ID, FPO_USER_ID, mint_jwt

def test_rls_canary_cross_tenant_isolation(override_supabase, fake_supabase):
    client = TestClient(app)
    
    # Seed a lot belonging to FPO
    fake_supabase.seed("lots", [{
        "id": "lot-cross-tenant-1",
        "user_id": FPO_USER_ID,
        "commodity_id": "cccc-0000-0000-0000",
        "market_id": "aaaa-0000-0000-0000",
        "quantity": 100,
        "status": "closed",
    }])

    # Authenticate as FARMER
    token = mint_jwt(FARMER_USER_ID)
    
    # Try to access the lots. 
    # Our /api/v1/lots/ GET uses the user client, but there is no such endpoint that returns all lots for user_id.
    # Actually, let's use the dashboard offers or grievances.
    fake_supabase.seed("grievances", [{
        "id": "grievance-cross-tenant-1",
        "user_id": FPO_USER_ID,
        "lot_id": "lot-cross-tenant-1",
        "grievance_type": "quality",
        "status": "open",
    }])

    # The grievances endpoint lists grievances for the current user.
    res = client.get("/api/v1/grievances/", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert len(res.json()) == 0, "RLS emulation failed: Farmer saw FPO's grievance"

    # FPO should see it
    token_fpo = mint_jwt(FPO_USER_ID)
    res_fpo = client.get("/api/v1/grievances/", headers={"Authorization": f"Bearer {token_fpo}"})
    assert res_fpo.status_code == 200
    assert len(res_fpo.json()) == 1, "RLS emulation failed: FPO couldn't see own grievance"

    # Admin should see it
    token_admin = mint_jwt(ADMIN_USER_ID)
    # Admin API for grievances
    res_admin = client.get("/api/v1/admin/grievances", headers={"Authorization": f"Bearer {token_admin}"})
    assert res_admin.status_code == 200
    # The admin uses the service_role client usually, but in our case, ADMIN_USER_ID bypasses RlsFakeSupabase filters
    # Let's just check the response
    assert len([g for g in res_admin.json() if g["id"] == "grievance-cross-tenant-1"]) == 1
