import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_get_markets_no_auth(override_supabase, fake_supabase):
    response = client.get("/api/v1/markets/")
    assert response.status_code == 200
    assert len(response.json()) == 2   # seeded markets

def test_get_markets_with_filter(override_supabase, fake_supabase):
    response = client.get("/api/v1/markets/?district=Nashik")
    assert response.status_code == 200
    assert len(response.json()) == 2
    
def test_get_markets_with_bad_filter(override_supabase, fake_supabase):
    response = client.get("/api/v1/markets/?district=Nowhere")
    assert response.status_code == 200
    assert len(response.json()) == 0

def test_get_commodities_no_auth(override_supabase, fake_supabase):
    response = client.get("/api/v1/commodities/")
    assert response.status_code == 200
    assert len(response.json()) == 2
    data = response.json()
    # Check trilingual translation fields exist
    assert "name_mr" in data[0]
    assert "name_hi" in data[0]

def test_get_latest_prices_no_auth(override_supabase, fake_supabase):
    # In fake_supabase we don't have prices seeded by default, but it shouldn't 500
    response = client.get("/api/v1/prices/latest?limit=7")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_historical_prices(override_supabase, fake_supabase):
    # Same, it should just return an empty list but the limit and endpoints should parse
    response = client.get("/api/v1/prices/historical?market_id=123&commodity_id=456&limit=100")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_get_latest_prices_seeded(override_supabase, fake_supabase):
    from datetime import datetime, timezone
    
    from datetime import datetime, timezone, date
    
    # Seed a row with today's date so the 7-day gte filter in /latest passes
    today = date.today().isoformat()
    fake_supabase._data["prices"] = [{
        "id": "1111-2222",
        "market_id": "aaaa-0000-0000-0000",
        "commodity_id": "cccc-0000-0000-0000",
        "arrival_date": today,
        "min_price": 1000.0,
        "max_price": 2000.0,
        "modal_price": 1500.0,
        "unit": "quintal",
        "variety": "General",
        "grade": "FAQ",
        "source": "data_gov_in",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "markets": {"name": "Lasalgaon APCM", "district": "Nashik"},
        "commodities": {"name_en": "Onion", "name_mr": "कांदा", "name_hi": "प्याज"}
    }]
    
    response = client.get("/api/v1/prices/latest")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["market_name"] == "Lasalgaon APCM"
    assert data[0]["district"] == "Nashik"
    assert data[0]["commodity_name_en"] == "Onion"
    assert data[0]["modal_price"] == 1500.0
