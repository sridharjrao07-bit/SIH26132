from slowapi import Limiter
from fastapi import Request
from app.config import get_settings


def _default_limit() -> str:
    try:
        enabled = get_settings().rate_limit_enabled
    except Exception:
        enabled = True
    return "120/minute" if enabled else "10000/minute"


from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, default_limits=[_default_limit()])


def webhook_limit() -> str:
    try:
        enabled = get_settings().rate_limit_enabled
    except Exception:
        enabled = True
    return "30/minute" if enabled else "10000/minute"
