from datetime import date, timedelta
from tests.conftest import FakeSupabase
from notifications.sale_window import compute_sale_window

def test_seeded_headline_appears_in_sale_window(monkeypatch):
    """Verify that seeded headlines correctly appear in compute_sale_window output."""
    fake_supabase = FakeSupabase()
    
    today = date.today()
    
    # Seed prices so compute_sale_window doesn't return None
    fake_supabase.seed("prices", [{
        "commodity_id": "c1",
        "market_id": "m1",
        "arrival_date": today.isoformat(),
        "modal_price": 2000,
        "arrival_qty": 100,
        "markets": {"name": "Nashik Market", "district": "Nashik", "lat": 19.9, "lng": 73.7}
    }])
    
    # Seed events
    fake_supabase.seed("events", [{
        "headline": "Onion export ban lifted by government",
        "event_date": (today - timedelta(days=2)).isoformat(),
        "commodity_id": "c1",
        "district": "Nashik",
        "confidence": 0.9,
        "event_type": "policy"
    }])
    
    result = compute_sale_window(
        supabase=fake_supabase,
        commodity_id="c1",
        market_id="m1"
    )
    
    assert result is not None
    assert "Onion export ban lifted by government" in result["reason"]
