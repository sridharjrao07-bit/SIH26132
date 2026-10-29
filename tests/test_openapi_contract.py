"""OpenAPI must list the frontend contract paths (development only)."""
from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_is_public():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}




def test_openapi_exposes_core_paths():
    """OpenAPI must expose the retained spine plus the DirectLink surface.

    The SIH26132 endpoints (forecasts, sale-window, offers, payments,
    grievances) retired to legacy/ with the pivot and are no longer required.
    """
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    required = [
        "/health",
        "/api/v1/markets/",
        "/api/v1/commodities/",
        "/api/v1/prices/latest",
        "/api/v1/lots/",
        "/api/v1/me/",
        # DirectLink (SIH26033)
        "/api/v1/direct/config",
        "/api/v1/direct/rupee",
        "/api/v1/direct/fair-price",
        "/api/v1/direct/plan",
        "/api/v1/direct/plans/commit",
        "/api/v1/direct/plans/{plan_id}",
        "/api/v1/direct/group-buy",
        "/api/v1/direct/impact",
        "/api/v1/direct/trace/{token}",
    ]
    missing = [p for p in required if p not in paths]
    assert missing == [], f"OpenAPI missing paths: {missing}"
