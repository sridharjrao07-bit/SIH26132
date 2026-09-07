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
from app.startup_checks import _check_auth_enforcement
from app.config import Settings
import pytest
from app.deps import get_supabase_as_user
from fastapi import HTTPException

def test_auth_mode_app_startup_rejection_in_prod():
    settings = Settings(app_env="production", auth_db_enforcement="app", kb_allow_app_mode=False)
    with pytest.raises(RuntimeError, match="STARTUP REJECTED"):
        _check_auth_enforcement(settings)

def test_auth_mode_app_startup_allows_dev():
    settings = Settings(app_env="development", auth_db_enforcement="app", kb_allow_app_mode=False)
    _check_auth_enforcement(settings) # Should not raise

def test_auth_mode_app_startup_allows_prod_with_override():
    settings = Settings(app_env="production", auth_db_enforcement="app", kb_allow_app_mode=True)
    _check_auth_enforcement(settings) # Should not raise

def test_deps_get_supabase_as_user_raises_401_no_token():
    with pytest.raises(HTTPException) as exc:
        get_supabase_as_user(None)
    assert exc.value.status_code == 401

def test_deps_get_supabase_as_user_raises_401_bad_token():
    with pytest.raises(HTTPException) as exc:
        get_supabase_as_user("Bearer bad_token")
    assert exc.value.status_code == 401

def test_rls_canary_payment_cross_tenant(override_supabase, fake_supabase):
    client = TestClient(app)
    # Tests that user cannot patch another user's payment
    fake_supabase.seed("payments", [{
        "id": "payment-fpo-1", "user_id": FPO_USER_ID, "amount": 5000, "status": "pending"
    }])
    token = mint_jwt(FARMER_USER_ID)
    res = client.patch("/api/v1/payments/payment-fpo-1/paid", headers={"Authorization": f"Bearer {token}"})
    # Our fake_supabase mock currently just does table updates, so we should test via the client
    assert res.status_code == 404 or res.status_code == 403 or res.status_code == 400

def test_rls_canary_grievance_cross_tenant(override_supabase, fake_supabase):
    client = TestClient(app)
    fake_supabase.seed("grievances", [{
        "id": "grievance-fpo-1", "user_id": FPO_USER_ID, "lot_id": "lot-1", "status": "open"
    }])
    token = mint_jwt(FARMER_USER_ID)
    res = client.patch("/api/v1/grievances/grievance-fpo-1/resolved", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 404 or res.status_code == 403 or res.status_code == 400

def test_rls_fake_direct_query(override_supabase, fake_supabase):
    """
    Directly query the RlsFakeSupabase to prove it filters out cross-tenant rows
    independently of any endpoint-level .eq("user_id", ...) filters.
    """
    from tests.conftest import RlsFakeSupabase

    fake_supabase.seed("offers", [
        {"id": "offer-1", "user_id": FARMER_USER_ID, "price": 100},
        {"id": "offer-2", "user_id": FPO_USER_ID, "price": 200},
    ])
    
    # Raw query without any .eq filters via the RLS fake
    client = RlsFakeSupabase(fake_supabase, uid=FARMER_USER_ID)
    res = client.table("offers").select("*").execute()
    
    assert len(res.data) == 1
    assert res.data[0]["id"] == "offer-1"
