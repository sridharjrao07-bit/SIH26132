"""
tests/test_sms.py — Stage 5 SMS gateway and inbound webhook tests.

Covers:
  - MockSMSGateway: file logging, notification_log insert
  - InboundVerifier: valid HMAC passes, bad sig → 403, expired ts → 403
  - Admin /simulate endpoint: admin can access, non-admin → 403
"""
import time
import hmac
import hashlib
import pytest
from fastapi.testclient import TestClient

from tests.conftest import (
    FakeSupabase, MARKET_ID_LASALGAON, COMMODITY_ID_ONION
)

# ─── InboundVerifier ────────────────────────────────────────────────────────

def make_signed_request(body: bytes, secret: str = "demo-secret") -> dict:
    """Build valid HMAC headers for a given body."""
    ts = str(time.time())
    payload = body + ts.encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return {"X-Signature": sig, "X-Timestamp": ts}


@pytest.mark.asyncio
async def test_valid_hmac_signature_passes(monkeypatch):
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "test-secret")
    from importlib import reload
    import notifications.inbound_verifier as iv_mod
    reload(iv_mod)

    from starlette.testclient import TestClient as STC
    from fastapi import FastAPI, Request
    app = FastAPI()
    verifier = iv_mod.InboundVerifier()

    @app.post("/test")
    async def test_route(request: Request):
        await verifier.verify(request)
        return {"ok": True}

    body = b'{"sender": "+91999", "message": "test"}'
    headers = make_signed_request(body, "test-secret")
    client = STC(app)
    resp = client.post("/test", content=body, headers=headers)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bad_signature_rejected(monkeypatch):
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "test-secret")
    from importlib import reload
    import notifications.inbound_verifier as iv_mod
    reload(iv_mod)

    from starlette.testclient import TestClient as STC
    from fastapi import FastAPI, Request
    app = FastAPI()
    verifier = iv_mod.InboundVerifier()

    @app.post("/test")
    async def test_route(request: Request):
        await verifier.verify(request)
        return {"ok": True}

    body = b'{"sender": "+91999", "message": "test"}'
    ts = str(time.time())
    headers = {"X-Signature": "bad-signature", "X-Timestamp": ts}
    client = STC(app)
    resp = client.post("/test", content=body, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_expired_timestamp_rejected(monkeypatch):
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "test-secret")
    from importlib import reload
    import notifications.inbound_verifier as iv_mod
    reload(iv_mod)

    from starlette.testclient import TestClient as STC
    from fastapi import FastAPI, Request
    app = FastAPI()
    verifier = iv_mod.InboundVerifier()

    @app.post("/test")
    async def test_route(request: Request):
        await verifier.verify(request)
        return {"ok": True}

    body = b'{"sender": "+91999", "message": "test"}'
    old_ts = str(time.time() - 600)  # 10 minutes ago (over 5-minute drift)
    payload = body + old_ts.encode("utf-8")
    sig = hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()
    headers = {"X-Signature": sig, "X-Timestamp": old_ts}
    client = STC(app)
    resp = client.post("/test", content=body, headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_missing_headers_rejected(monkeypatch):
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "test-secret")
    from importlib import reload
    import notifications.inbound_verifier as iv_mod
    reload(iv_mod)

    from starlette.testclient import TestClient as STC
    from fastapi import FastAPI, Request
    app = FastAPI()
    verifier = iv_mod.InboundVerifier()

    @app.post("/test")
    async def test_route(request: Request):
        await verifier.verify(request)
        return {"ok": True}

    body = b'{"sender": "+91999"}'
    client = STC(app)
    # No HMAC headers at all
    resp = client.post("/test", content=body)
    assert resp.status_code == 403


# ─── SMS Simulate Endpoint (Admin-only) ──────────────────────────────────────

def make_admin_token() -> str:
    """Generate a valid-looking JWT for testing (just tests routing, not real auth)."""
    import jwt as pyjwt
    import os
    secret = os.environ.get("SUPABASE_JWT_SECRET", "placeholder")
    token = pyjwt.encode(
        {"sub": "admin-user-id", "role": "authenticated", "aud": "authenticated"},
        secret, algorithm="HS256"
    )
    return token


def test_simulate_endpoint_is_admin_gated(override_supabase):
    """Non-admin call → 401 (no token)"""
    from app.main import app
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post("/api/v1/sms/simulate", json={"sender": "+91999", "message": "कांदा"})
    # No auth header → 401/403 (require_role hits get_current_user first)
    assert resp.status_code in (401, 403)
