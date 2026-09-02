from functools import lru_cache
from fastapi import Header
from supabase import create_client, Client
from .config import get_settings

def get_supabase_as_user(authorization: str = Header(None)) -> Client:
    """
    Dependency to get an anon Supabase client with the user's JWT attached.
    This enables Row Level Security (RLS) enforcement per request.
    """
    settings = get_settings()
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    if authorization and authorization.startswith("Bearer "):
        client.postgrest.auth(authorization[7:])
    return client

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
