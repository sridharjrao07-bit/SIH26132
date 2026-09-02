from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    """Env names match field names case-insensitively (SUPABASE_URL → supabase_url).

    Do not set Field(alias="ENV_NAME"): pydantic-settings then stores env under the
    alias and constructor kwargs under the field name, so .env silently wins.
    """

    app_env: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str
    supabase_jwt_issuer: str = Field(default="")
    supabase_db_url: str = Field(default="")

    # Data Sources
    data_gov_in_api_key: str
    enable_agmarknet: bool = Field(default=False)

    # SMS Gateway
    sms_gateway: str = Field(default="mock")
    msg91_api_key: str = Field(default="")
    msg91_sender_id: str = Field(default="KRBAZR")
    msg91_dlt_pe_id: str = Field(default="")
    msg91_dlt_te_id_en: str = Field(default="")
    msg91_dlt_te_id_mr: str = Field(default="")
    msg91_dlt_te_id_hi: str = Field(default="")

    # Webhook HMAC — also read here so a value that only exists in `.env`
    # (not exported into os.environ) still protects /sms/webhook.
    inbound_hmac_secret: str = Field(default="")
    inbound_sig_header: str = Field(default="X-Signature")
    inbound_ts_header: str = Field(default="X-Timestamp")

    # Scheduler intervals
    ingestion_interval_hours: int = Field(default=6)
    alert_check_interval_minutes: int = Field(default=60)
    forecast_interval_hours: int = Field(default=6)

    # Scope
    target_district: str = Field(default="Nashik")
    target_state: str = Field(default="Maharashtra")

    # CORS — comma-separated origins
    cors_origin: str = Field(default="http://localhost:3000")

    run_scheduler: bool = Field(default=True)
    rate_limit_enabled: bool = Field(default=True)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        env_ignore_empty=True,
    )

    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origin.split(",") if o.strip()]


@lru_cache()
def get_settings():
    return Settings()
