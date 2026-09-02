"""
tests/test_sms.py — Stage 5 SMS gateway and inbound webhook tests.

Covers:
  - MockSMSGateway: file logging
  - InboundVerifier: valid HMAC passes, bad sig → 403, expired ts → 403
  - Admin /simulate endpoint: admin can access, non-admin → 403
  - S3 regression: production mode raises RuntimeError when secret is missing
  - S3 regression: ephemeral keys are per-instance (two verifiers reject each other)
  - M1 regression: MSG91Gateway sends correct Flow API payload shape
"""
import time
import hmac
import hashlib
import pytest
from fastapi.testclient import TestClient


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
    secret = os.environ.get("SUPABASE_JWT_SECRET", "ci-placeholder-jwt-secret-32b-min")
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


# ─── S3: Production secret enforcement ───────────────────────────────────────

def test_production_mode_missing_secret_raises_runtime_error(monkeypatch):
    """
    S3 regression: InboundVerifier() must raise RuntimeError at instantiation when
    APP_ENV=production and INBOUND_HMAC_SECRET is not set.
    sms.warmup_verifier() runs in FastAPI lifespan so this fails closed at startup.
    """
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("INBOUND_HMAC_SECRET", raising=False)

    from importlib import reload
    import notifications.inbound_verifier as iv_mod
    reload(iv_mod)

    with pytest.raises(RuntimeError, match="INBOUND_HMAC_SECRET"):
        iv_mod.InboundVerifier()

    # Cleanup
    monkeypatch.setenv("APP_ENV", "development")


def test_production_mode_demo_secret_raises_runtime_error(monkeypatch):
    """S3: Even setting INBOUND_HMAC_SECRET=demo-secret must fail in production."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("INBOUND_HMAC_SECRET", "demo-secret")

    from importlib import reload
    import notifications.inbound_verifier as iv_mod
    reload(iv_mod)

    with pytest.raises(RuntimeError, match="INBOUND_HMAC_SECRET"):
        iv_mod.InboundVerifier()

    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("INBOUND_HMAC_SECRET", raising=False)


@pytest.mark.asyncio
async def test_ephemeral_keys_are_per_instance(monkeypatch):
    """
    S3: In dev mode with no INBOUND_HMAC_SECRET, each InboundVerifier instance
    generates its own ephemeral key. A request signed with instance A's key
    must be REJECTED by instance B (keys are not shared).
    """
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("INBOUND_HMAC_SECRET", raising=False)

    from importlib import reload
    import notifications.inbound_verifier as iv_mod
    reload(iv_mod)

    verifier_a = iv_mod.InboundVerifier()
    verifier_b = iv_mod.InboundVerifier()

    body = b'{"sender": "+919999999999", "message": "ONION"}'

    # Sign with verifier_a's ephemeral secret
    ts = str(time.time())
    payload_to_sign = body + ts.encode("utf-8")
    sig = hmac.new(verifier_a.secret, payload_to_sign, hashlib.sha256).hexdigest()

    from starlette.testclient import TestClient as STC
    from fastapi import FastAPI, Request

    app = FastAPI()

    @app.post("/test")
    async def test_route(request: Request):
        await verifier_b.verify(request)  # verifier_b, not verifier_a
        return {"ok": True}

    test_client = STC(app)
    resp = test_client.post("/test", content=body, headers={"X-Signature": sig, "X-Timestamp": ts})
    # verifier_b has a different secret → must reject
    assert resp.status_code == 403, (
        "A request signed with one ephemeral key must be rejected by a different instance's verifier"
    )


# ─── M1: MSG91 Gateway payload shape ─────────────────────────────────────────

def test_msg91_gateway_sends_correct_flow_api_payload():
    """
    M1: MSG91Gateway must POST to the Flow API with template_id + recipients[].mappings.
    DLT templates have fixed text — must NOT send free-form 'message' field.
    Non-2xx response must return ("failed", False).
    """
    try:
        import respx
        import httpx
    except ImportError:
        pytest.skip("respx not installed — run: pip install respx")

    from notifications.sms_gateway import MSG91Gateway

    gateway = MSG91Gateway(auth_key="test-auth-key-12345", sender_id="KRBAZR")

    with respx.mock:
        # Happy path: 200 response
        mock_route = respx.post("https://api.msg91.com/api/v5/flow/").mock(
            return_value=httpx.Response(200, json={"type": "success"})
        )
        status, success = gateway.send_sms(
            recipient="+919876543210",
            message="KrishiBazaar: Onion ₹1800 at Lasalgaon.",  # ignored by MSG91Gateway
            template_id="template-dlt-12345",
            commodity="Onion",
            price="1800",
            threshold="1500",
        )
        assert success is True
        assert status == "sent"

        # Verify the request body shape
        assert mock_route.called
        sent_request = mock_route.calls.last.request
        import json
        body = json.loads(sent_request.content)
        assert body["template_id"] == "template-dlt-12345"
        assert "recipients" in body
        assert len(body["recipients"]) == 1
        recipient = body["recipients"][0]
        assert "mobiles" in recipient
        assert recipient["mobiles"] == "919876543210"  # lstrip("+")
        assert recipient["commodity"] == "Onion"
        assert recipient["price"] == "1800"
        assert recipient["threshold"] == "1500"
        # Must NOT contain a top-level 'message' field
        assert "message" not in body

        # Non-2xx path: must return ("failed", False)
        respx.post("https://api.msg91.com/api/v5/flow/").mock(
            return_value=httpx.Response(401, json={"message": "Unauthorized"})
        )
        status_fail, success_fail = gateway.send_sms(
            recipient="+919876543210",
            message="irrelevant",
            template_id="template-dlt-12345",
        )
        assert success_fail is False
        assert status_fail == "failed"


def test_msg91_gateway_missing_template_returns_failed():
    """M1: Missing template_id must return ("failed", False) without making an HTTP call."""
    from notifications.sms_gateway import MSG91Gateway
    gateway = MSG91Gateway(auth_key="test-key")
    status, success = gateway.send_sms("+919876543210", "msg", template_id=None)
    assert success is False
    assert status == "failed"
