from datetime import date

from app.main import app
from fastapi.testclient import TestClient

from tests.conftest import FARMER_USER_ID, mint_jwt

OTHER_FARMER_USER_ID = "farmer-uuid-0002-0000-000000000000"

client = TestClient(app)

def test_list_storage_facilities(override_supabase, fake_supabase):
    fake_supabase.seed("storage_facilities", [
        {
            "id": "fac-1",
            "district": "Pune",
            "name": "Pune Godown",
            "capacity_qtl": 1000,
            "rate_per_qtl": 10,
            "is_active": True,
            "created_at": date.today().isoformat()
        }
    ])
    
    resp = client.get("/api/v1/storage/facilities?district=Pune")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Pune Godown"


def test_book_storage_success(override_supabase, fake_supabase):
    fake_supabase.seed("storage_facilities", [{
        "id": "fac-2",
        "district": "Nashik",
        "name": "Nashik Godown",
        "capacity_qtl": 100,
        "rate_per_qtl": 10,
        "is_active": True,
    }])
    fake_supabase.seed("lots", [{
        "id": "lot-2",
        "user_id": FARMER_USER_ID,
        "quantity_qtl": 50,
        "status": "open"
    }])
    
    token = mint_jwt(FARMER_USER_ID)
    resp = client.post("/api/v1/storage/bookings", json={
        "lot_id": "lot-2",
        "facility_id": "fac-2",
        "quantity_qtl": 50,
        "notes": "Need space for onion"
    }, headers={"Authorization": f"Bearer {token}"})
    
    assert resp.status_code == 201
    assert resp.json()["status"] == "requested"


def test_book_storage_capacity_exceeded(override_supabase, fake_supabase):
    fake_supabase.seed("storage_facilities", [{
        "id": "fac-3",
        "district": "Nashik",
        "name": "Small Godown",
        "capacity_qtl": 40,
        "rate_per_qtl": 10,
        "is_active": True,
    }])
    fake_supabase.seed("lots", [{
        "id": "lot-3",
        "user_id": FARMER_USER_ID,
        "quantity_qtl": 50,
        "status": "open"
    }])
    
    token = mint_jwt(FARMER_USER_ID)
    resp = client.post("/api/v1/storage/bookings", json={
        "lot_id": "lot-3",
        "facility_id": "fac-3",
        "quantity_qtl": 50
    }, headers={"Authorization": f"Bearer {token}"})
    
    # Migration 036 contract: capacity is enforced inside storage_booking_create
    # under a facility row lock. The RPC raises P0001, which json_for_api_error
    # maps to 409 with an opaque detail by design (the old app-side check was
    # a racy 400 that could not stop concurrent oversubscription).
    assert resp.status_code == 409


def test_update_storage_booking_state_machine(override_supabase, fake_supabase):
    fake_supabase.seed("storage_facilities", [{
        "id": "fac-4",
        "district": "Nashik",
        "name": "Test Godown",
        "capacity_qtl": 100,
        "rate_per_qtl": 10,
        "is_active": True,
    }])
    fake_supabase.seed("storage_bookings", [{
        "id": "book-1",
        "user_id": FARMER_USER_ID,
        "lot_id": "lot-4",
        "facility_id": "fac-4",
        "quantity_qtl": 20,
        "status": "requested",
        "created_at": date.today().isoformat(),
        "updated_at": date.today().isoformat()
    }])
    
    token = mint_jwt(FARMER_USER_ID)
    # Confirm
    resp = client.patch("/api/v1/storage/bookings/book-1", json={"status": "confirmed"}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"
    
    # Cannot go back to requested
    resp2 = client.patch("/api/v1/storage/bookings/book-1", json={"status": "requested"}, headers={"Authorization": f"Bearer {token}"})
    assert resp2.status_code == 422
    
    # Complete
    resp3 = client.patch("/api/v1/storage/bookings/book-1", json={"status": "completed"}, headers={"Authorization": f"Bearer {token}"})
    assert resp3.status_code == 200
    assert resp3.json()["status"] == "completed"
    
    # Cannot transition from completed
    resp4 = client.patch("/api/v1/storage/bookings/book-1", json={"status": "cancelled"}, headers={"Authorization": f"Bearer {token}"})
    assert resp4.status_code == 409


def test_cross_tenant_isolation_storage_bookings(override_supabase, fake_supabase):
    fake_supabase.seed("storage_bookings", [{
        "id": "book-2",
        "user_id": FARMER_USER_ID,
        "lot_id": "lot-5",
        "facility_id": "fac-5",
        "quantity_qtl": 20,
        "status": "requested",
        "created_at": date.today().isoformat(),
        "updated_at": date.today().isoformat()
    }])
    
    token_other = mint_jwt(OTHER_FARMER_USER_ID)
    
    # List should be empty
    resp = client.get("/api/v1/storage/bookings", headers={"Authorization": f"Bearer {token_other}"})
    assert resp.status_code == 200
    assert len(resp.json()) == 0
    
    # Patch should be 404
    resp2 = client.patch("/api/v1/storage/bookings/book-2", json={"status": "cancelled"}, headers={"Authorization": f"Bearer {token_other}"})
    assert resp2.status_code == 404
