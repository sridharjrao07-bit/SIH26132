from datetime import date
from ingestion.base import RawPriceRecord
from ingestion.validator import PriceValidator
from app.config import get_settings
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_arrival_qty_validation(validator: PriceValidator):
    """
    Test that arrival quantity is validated correctly:
    - Accepted when valid
    - Rejected when negative
    - Rejected when insanely large (overflow prevention)
    """
    base_record = RawPriceRecord(
        market_name="Lasalgaon APCM",
        commodity_name="Onion",
        arrival_date=date(2023, 10, 1),
        min_price=1500,
        max_price=2500,
        modal_price=2000,
        unit="quintal",
        source="data_gov_in",
        raw_payload={}
    )

    # 1. Valid arrival_qty
    base_record.arrival_qty = 500.0
    res, err = validator.validate_and_normalize(base_record)
    assert err is None
    assert res["arrival_qty"] == 500.0

    # 2. Null arrival_qty
    base_record.arrival_qty = None
    res, err = validator.validate_and_normalize(base_record)
    assert err is None
    assert res["arrival_qty"] is None

    # 3. Negative arrival_qty
    base_record.arrival_qty = -10.0
    res, err = validator.validate_and_normalize(base_record)
    assert res is None
    assert "invalid_quantity:arrival_qty(-10.0) < 0" in err

    # 4. Overflow arrival_qty
    max_qty = get_settings().max_arrival_qty_qtl
    base_record.arrival_qty = max_qty + 1
    res, err = validator.validate_and_normalize(base_record)
    assert res is None
    assert f"invalid_quantity:arrival_qty({max_qty + 1.0}) > MAX" in err

def test_arrival_qty_api_surfacing(override_supabase, fake_supabase):
    """
    Test that arrival_qty is correctly surfaced in the prices API.
    """
    fake_supabase.seed("prices", [{
        "id": "price-1",
        "market_id": "aaaa-0000-0000-0000",
        "commodity_id": "cccc-0000-0000-0000",
        "arrival_date": date.today().isoformat(),
        "min_price": 1000,
        "max_price": 2000,
        "modal_price": 1500,
        "arrival_qty": 750.5,
        "variety": "General",
        "grade": "General",
        "source": "data_gov_in"
    }])
    
    resp = client.get("/api/v1/prices/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["arrival_qty"] == 750.5
