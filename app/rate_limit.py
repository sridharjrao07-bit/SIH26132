from app.config import get_settings
from fastapi import Request
from slowapi import Limiter


def _default_limit() -> str:
    try:
        enabled = get_settings().rate_limit_enabled
    except Exception:
        enabled = True
    return "120/minute" if enabled else "10000/minute"


def get_real_ip(request: Request) -> str:
    """
    Returns the IP address for the current request.
    Relies on request.client.host, which is securely populated by Uvicorn
    ONLY if the request originated from a trusted proxy configured via
    --forwarded-allow-ips (or FORWARDED_ALLOW_IPS).
    We do NOT blindly trust X-Forwarded-For headers.
    """
    if not request.client or not request.client.host:
        return "127.0.0.1"
    return request.client.host


limiter = Limiter(key_func=get_real_ip, default_limits=[_default_limit()])


def webhook_limit() -> str:
    try:
        enabled = get_settings().rate_limit_enabled
    except Exception:
        enabled = True
    return "30/minute" if enabled else "10000/minute"
