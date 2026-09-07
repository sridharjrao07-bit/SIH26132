"""Supabase client dependencies for FastAPI.

Client tiers:
- ``get_supabase``             — anon key, honours RLS (public reads)
- ``get_supabase_as_user``     — authenticated; mode determined by AUTH_DB_ENFORCEMENT:
    "rls"  per-request user-JWT client → PostgREST runs as *authenticated* role,
           existing RLS policies enforce isolation at the DB boundary.
    "app"  service-role client (legacy); app-layer .eq("user_id",...) is sole guard.
           Startup refuses this in production unless KB_ALLOW_APP_MODE=1.
- ``get_supabase_service_role`` — service role, bypasses RLS; jobs/admin only.

IMPORTANT: ``get_supabase_as_user`` is **never** @lru_cached — caching a
user-scoped client is a cross-user data-leak vector.
"""
from fastapi import Header, HTTPException
from supabase import create_client, Client
from functools import lru_cache
from .config import get_settings
import structlog

_log = structlog.get_logger()


def get_supabase_as_user(authorization: str = Header(None)) -> Client:
    """Return a Supabase client scoped to the authenticated caller.

    In "rls" mode a fresh per-request client is created so PostgREST
    executes as the *authenticated* Postgres role and RLS policies apply.
    In "app" mode the cached service-role client is returned with a
    loud warning so the security gap is visible in logs.

    Raises 401 if the Authorization header is missing or the JWT is invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")

    # Validate JWT regardless of mode — lazy import avoids circular dep.
    from app.auth import decode_access_token
    decode_access_token(authorization[7:])

    settings = get_settings()
    if settings.auth_db_enforcement == "rls":
        # Per-request user-scoped client: PostgREST runs as `authenticated`
        # role and RLS policies enforce at the DB boundary.
        # Requires SUPABASE_JWT_ISSUER + legacy JWT secret aligned with project.
        return create_client(settings.supabase_url, authorization[7:])

    # "app" mode — service-role client; app-level filters are the sole guard.
    _log.warning(
        "auth_mode_app",
        msg=(
            "get_supabase_as_user returning service-role client (AUTH_DB_ENFORCEMENT=app). "
            "Data isolation relies solely on application-level .eq('user_id',...) filters. "
            "Set AUTH_DB_ENFORCEMENT=rls in production after token-claims alignment."
        ),
    )
    return get_supabase_service_role()


@lru_cache()
def get_supabase() -> Client:
    """Anon Supabase client — respects RLS; use for public reads."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)


@lru_cache()
def get_supabase_service_role() -> Client:
    """Service-role Supabase client — bypasses RLS.  Use ONLY for jobs / admin."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
