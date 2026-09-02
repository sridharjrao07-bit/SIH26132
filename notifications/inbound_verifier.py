import os
import hmac
import hashlib
import secrets
import time
import threading
from fastapi import Request, HTTPException
import structlog

logger = structlog.get_logger()

# Replay cache: signature -> expiry epoch. Single-worker in-memory is enough
# alongside the job-lock assumption (uvicorn --workers 1).
_REPLAY_LOCK = threading.Lock()
_SEEN_SIGNATURES: dict = {}
_REPLAY_TTL_SEC = 330  # slightly longer than the ±5 min drift window


def _purge_expired(now: float) -> None:
    expired = [k for k, exp in _SEEN_SIGNATURES.items() if exp <= now]
    for k in expired:
        _SEEN_SIGNATURES.pop(k, None)


def _load_secret() -> bytes:
    """
    Load the inbound HMAC secret.

    Preference:
      1. os.environ (process env / test monkeypatch)
      2. pydantic Settings (values loaded from `.env` even if not exported)

    Production (APP_ENV=production):
      - Secret MUST be set and MUST NOT equal the old hard-coded "demo-secret".
      - Raises RuntimeError at startup if this condition is not met.

    Development / staging:
      - Missing secret → ephemeral random key + warning.
      - "demo-secret" is rejected in every environment.
    """
    settings = None
    try:
        from app.config import get_settings
        settings = get_settings()
    except Exception:
        settings = None

    secret_str = os.environ.get("INBOUND_HMAC_SECRET")
    if secret_str is None or secret_str == "":
        secret_str = (settings.inbound_hmac_secret if settings else "") or ""

    app_env = os.environ.get("APP_ENV")
    if not app_env:
        app_env = settings.app_env if settings else "development"
    app_env = (app_env or "development").lower()

    if app_env == "production":
        if not secret_str or secret_str == "demo-secret":
            raise RuntimeError(
                "INBOUND_HMAC_SECRET must be set to a strong secret in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return secret_str.encode("utf-8")

    if secret_str and secret_str != "demo-secret":
        return secret_str.encode("utf-8")

    ephemeral = secrets.token_hex(32)
    logger.warning(
        "inbound_hmac_ephemeral_key",
        reason="INBOUND_HMAC_SECRET not set (or was 'demo-secret'). "
               "Using a randomly generated ephemeral key — webhook signatures "
               "will not survive a restart. Set INBOUND_HMAC_SECRET in .env for stability.",
    )
    return ephemeral.encode("utf-8")


class InboundVerifier:
    """
    HMAC-SHA256 of raw body + timestamp, ±5 minute drift, replay nonce.
    """

    def __init__(self):
        self.secret = _load_secret()
        try:
            from app.config import get_settings
            s = get_settings()
            self.header_name = os.environ.get("INBOUND_SIG_HEADER") or s.inbound_sig_header
            self.ts_header_name = os.environ.get("INBOUND_TS_HEADER") or s.inbound_ts_header
        except Exception:
            self.header_name = os.environ.get("INBOUND_SIG_HEADER", "X-Signature")
            self.ts_header_name = os.environ.get("INBOUND_TS_HEADER", "X-Timestamp")

    async def verify(self, request: Request):
        signature = request.headers.get(self.header_name)
        timestamp = request.headers.get(self.ts_header_name)

        if not signature or not timestamp:
            logger.warning("webhook_missing_headers")
            raise HTTPException(403, "Missing signature or timestamp")

        try:
            ts_float = float(timestamp)
            if abs(time.time() - ts_float) > 300:
                logger.warning("webhook_expired", drift=time.time() - ts_float)
                raise HTTPException(403, "Request expired or drift too high")
        except ValueError:
            raise HTTPException(403, "Invalid timestamp format")

        body = await request.body()

        payload_to_sign = body + timestamp.encode("utf-8")
        expected_hmac = hmac.new(self.secret, payload_to_sign, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected_hmac, signature):
            logger.warning("webhook_invalid_signature")
            raise HTTPException(403, "Invalid signature")

        now = time.time()
        with _REPLAY_LOCK:
            _purge_expired(now)
            if signature in _SEEN_SIGNATURES:
                logger.warning("webhook_replay_rejected")
                raise HTTPException(403, "Replay detected")
            _SEEN_SIGNATURES[signature] = now + _REPLAY_TTL_SEC

        return True
