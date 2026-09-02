import os
import hmac
import hashlib
import time
from fastapi import Request, HTTPException
import structlog

logger = structlog.get_logger()

class InboundVerifier:
    """
    Swappable webhook signature verifier.
    Uses HMAC-SHA256 of the raw body against a configured secret.
    Includes a ±5 minute timestamp drift guard to prevent replay attacks.
    """
    def __init__(self):
        self.secret = os.environ.get("INBOUND_HMAC_SECRET", "demo-secret").encode("utf-8")
        self.header_name = os.environ.get("INBOUND_SIG_HEADER", "X-Signature")
        self.ts_header_name = os.environ.get("INBOUND_TS_HEADER", "X-Timestamp")

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
