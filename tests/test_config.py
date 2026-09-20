import pytest
from app.config import Settings


def test_production_rejects_placeholder_supabase_keys():
    # anon key
    s1 = Settings(
        app_env="production",
        supabase_url="https://valid.supabase.co",
        supabase_anon_key="placeholder",
        supabase_service_role_key="valid",
        supabase_jwt_secret="valid",
        supabase_jwt_issuer="https://valid.supabase.co/auth/v1",
        data_gov_in_api_key="valid",
        inbound_hmac_secret="valid",
    )
    with pytest.raises(
        RuntimeError, match="STARTUP REJECTED: SUPABASE_ANON_KEY cannot be a placeholder"
    ):
        s1.check_runtime()

    # service role key
    s2 = Settings(
        app_env="production",
        supabase_url="https://valid.supabase.co",
        supabase_anon_key="valid",
        supabase_service_role_key="placeholder",
        supabase_jwt_secret="valid",
        supabase_jwt_issuer="https://valid.supabase.co/auth/v1",
        data_gov_in_api_key="valid",
        inbound_hmac_secret="valid",
    )
    with pytest.raises(
        RuntimeError, match="STARTUP REJECTED: SUPABASE_SERVICE_ROLE_KEY cannot be a placeholder"
    ):
        s2.check_runtime()


def test_production_accepts_valid_keys_without_ey_prefix():
    s = Settings(
        app_env="production",
        supabase_url="https://valid.supabase.co",
        supabase_anon_key="valid_anon_key_without_ey",
        supabase_service_role_key="valid_sr_key_without_ey",
        supabase_jwt_secret="valid",
        supabase_jwt_issuer="https://valid.supabase.co/auth/v1",
        data_gov_in_api_key="valid",
        inbound_hmac_secret="valid",
    )
    s.check_runtime()  # should not raise
