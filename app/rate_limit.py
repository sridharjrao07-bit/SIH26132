from slowapi import Limiter
from fastapi import Request
from app.config import get_settings


def _default_limit() -> str:
    try:
        enabled = get_settings().rate_limit_enabled
    except Exception:
        enabled = True
    return "120/minute" if enabled else "10000/minute"


def get_real_ip(request: Request) -> str:
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


limiter = Limiter(key_func=get_real_ip, default_limits=[_default_limit()])


def webhook_limit() -> str:
    try:
        enabled = get_settings().rate_limit_enabled
    except Exception:
        enabled = True
    return "30/minute" if enabled else "10000/minute"
