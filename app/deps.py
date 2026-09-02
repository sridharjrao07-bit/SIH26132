from functools import lru_cache
from fastapi import Header, HTTPException
from supabase import create_client, Client
from .config import get_settings

def get_supabase_as_user(authorization: str = Header(None)) -> Client:
    """Authenticated data-plane client (service role).

    FastAPI verifies the JWT (see ``decode_access_token``). We do **not**
    attach that token to PostgREST: hosted Supabase JWT signing keys reject
    locally minted HS256 with ``PGRST301``, which became HTTP 500 on
    ``/me`` and ``/lots``.

    Handlers must scope every query by ``user_id`` from ``get_current_user``.
    The anon client (``get_supabase``) still honours RLS for public reads.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    # Lazy import: auth.py imports this module.
    from app.auth import decode_access_token
    decode_access_token(authorization[7:])
    return get_supabase_service_role()

@lru_cache()
def get_supabase() -> Client:
    """
    Dependency to get a standard (anon) Supabase client.
    This client respects RLS and acts as the public API user.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)

@lru_cache()
def get_supabase_service_role() -> Client:
    """
    Dependency to get a service-role Supabase client.
    Bypasses RLS. Use ONLY for internal endpoints or jobs.
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
