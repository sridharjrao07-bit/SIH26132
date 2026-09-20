import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Request
from jwt import InvalidTokenError

from .config import get_settings
from .deps import get_supabase_service_role

ADMIN_COOKIE = "kb_admin"

# ── Role cache ────────────────────────────────────────────────────────────────
# require_role() makes a synchronous DB round-trip on every call which adds
# ~20-50 ms of latency to every authenticated admin endpoint.  We cache the
# (user_id → role) mapping in-process with a short TTL so that role changes
# propagate within 60 seconds while avoiding per-request DB hits.
#
# Thread-safety: the dict is protected by a Lock.  Cache entries are
# (role: str, expires_at: datetime).  Expired entries are evicted lazily.

_role_cache: dict[str, tuple[str, datetime]] = {}
_role_cache_lock = threading.Lock()
# Accepted, documented staleness window: a role change (a demotion via the
# admin_set_role RPC, or direct SQL) reaches already-cached sessions only once
# this TTL elapses.  There is deliberately no invalidation hook: no in-app
# endpoint mutates roles, so a hook would have no caller and would rot.
# See docs/SECURITY_MODEL.md, "Role-Cache Propagation Window".
_ROLE_CACHE_TTL = timedelta(seconds=60)


def _get_cached_role(user_id: str) -> Optional[str]:
    """Return cached role if present and not expired, else None."""
    with _role_cache_lock:
        entry = _role_cache.get(user_id)
        if entry is None:
            return None
        role, expires_at = entry
        if datetime.now(tz=timezone.utc) >= expires_at:
            del _role_cache[user_id]
            return None
        return role


def _set_cached_role(user_id: str, role: str) -> None:
    expires_at = datetime.now(tz=timezone.utc) + _ROLE_CACHE_TTL
    with _role_cache_lock:
        _role_cache[user_id] = (role, expires_at)


def decode_access_token(token: str) -> str:
    """Verify HS256 Supabase JWT and return `sub`."""
    settings = get_settings()
    options = {"require": ["exp", "sub", "aud"]}
    kwargs = dict(
        algorithms=["HS256"],
        audience="authenticated",
        leeway=30,
        options=options,
    )
    if settings.supabase_jwt_issuer:
        kwargs["issuer"] = settings.supabase_jwt_issuer
    try:
        claims = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            **kwargs,
        )
    except InvalidTokenError:
        raise HTTPException(401, "invalid token")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, "token missing subject")
    return user_id


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> str:
    """Bearer token, or HttpOnly dashboard cookie `kb_admin`."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
    elif request.cookies.get(ADMIN_COOKIE):
        token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise HTTPException(401, "missing bearer token")
    return decode_access_token(token)


def require_role(*roles: str):
    """Dependency that checks the authenticated user has one of the given roles.

    Uses a 60-second in-process cache to avoid a DB round-trip on every
    authenticated request.  Role changes propagate within one TTL window.
    """
    allowed = tuple(roles)

    def dep(supabase=Depends(get_supabase_service_role), user_id=Depends(get_current_user)):
        # Fast path: check cache first.
        cached = _get_cached_role(user_id)
        if cached is not None:
            if cached not in allowed:
                raise HTTPException(403, f"requires role in {list(allowed)}")
            return

        # Slow path: hit the DB and populate the cache.
        row = supabase.table("user_profiles").select("role").eq("id", user_id).execute().data
        if not row:
            raise HTTPException(403, f"requires role in {list(allowed)}")
        role = row[0]["role"]
        _set_cached_role(user_id, role)
        if role not in allowed:
            raise HTTPException(403, f"requires role in {list(allowed)}")

    return dep
