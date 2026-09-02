import os
import hmac
import hashlib
import secrets
import time
from fastapi import Request, HTTPException
import structlog

logger = structlog.get_logger()


def _load_secret() -> bytes:
    """
    Load the INBOUND_HMAC_SECRET from the environment.

    Production (APP_ENV=production):
      - Secret MUST be set and MUST NOT equal the old hard-coded "demo-secret".
      - Raises RuntimeError at startup if this condition is not met.

    Development / staging:
      - If the secret is missing, a random ephemeral key is generated and
        logged as a WARNING on every instantiation so operators notice.
      - "demo-secret" is explicitly rejected even in dev (it's in git history).
    """
    secret_str = os.environ.get("INBOUND_HMAC_SECRET", "")
    app_env    = os.environ.get("APP_ENV", "development").lower()

    if app_env == "production":
        if not secret_str or secret_str == "demo-secret":
            raise RuntimeError(
                "INBOUND_HMAC_SECRET must be set to a strong secret in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return secret_str.encode("utf-8")

    # Non-production path
    if secret_str and secret_str != "demo-secret":
        return secret_str.encode("utf-8")

    # Missing or the banned default — generate ephemeral key and warn loudly.
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
    Swappable webhook signature verifier.
    Uses HMAC-SHA256 of the raw body against a configured secret.
    Includes a ±5 minute timestamp drift guard to prevent replay attacks.

    Secret loading rules:
      - production: INBOUND_HMAC_SECRET env var required; missing → RuntimeError at startup.
      - development: missing → ephemeral random key (warning logged every instantiation).
      - "demo-secret" is never accepted in any environment.
    """
    def __init__(self):
        self.secret          = _load_secret()
        self.header_name     = os.environ.get("INBOUND_SIG_HEADER", "X-Signature")
        self.ts_header_name  = os.environ.get("INBOUND_TS_HEADER", "X-Timestamp")

    async def verify(self, request: Request):
        signature = request.headers.get(self.header_name)
        timestamp = request.headers.get(self.ts_header_name)

        if not signature or not timestamp:
            logger.warning("webhook_missing_headers")
            raise HTTPException(403, "Missing signature or timestamp")

        # Drift guard: ±5 minutes
        try:
            ts_float = float(timestamp)
            if abs(time.time() - ts_float) > 300:
                logger.warning("webhook_expired", drift=time.time() - ts_float)
                raise HTTPException(403, "Request expired or drift too high")
        except ValueError:
            raise HTTPException(403, "Invalid timestamp format")

        body = await request.body()

        # We sign the body + timestamp to bind them together
        payload_to_sign = body + timestamp.encode("utf-8")
        expected_hmac = hmac.new(self.secret, payload_to_sign, hashlib.sha256).hexdigest()

        if not hmac.compare_digest(expected_hmac, signature):
            logger.warning("webhook_invalid_signature")
            raise HTTPException(403, "Invalid signature")

        return True
