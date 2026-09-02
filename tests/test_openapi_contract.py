"""OpenAPI must list the frontend contract paths (development only)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_openapi_exposes_core_paths():
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    required = [
        "/health",
        "/api/v1/markets/",
        "/api/v1/commodities/",
        "/api/v1/prices/latest",
        "/api/v1/forecasts",
        "/api/v1/forecasts/summary",
        "/api/v1/sale-window/",
        "/api/v1/lots/",
        "/api/v1/offers/",
        "/api/v1/payments/",
        "/api/v1/grievances/",
        "/api/v1/me/",
    ]
    missing = [p for p in required if p not in paths]
    assert missing == [], f"OpenAPI missing paths: {missing}"


def test_health_is_public():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
