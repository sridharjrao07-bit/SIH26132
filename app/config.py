from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache
from typing import List


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Supabase
    supabase_url: str = Field(..., alias="SUPABASE_URL")
    supabase_anon_key: str = Field(..., alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(..., alias="SUPABASE_SERVICE_ROLE_KEY")
    supabase_jwt_secret: str = Field(..., alias="SUPABASE_JWT_SECRET")
    supabase_jwt_issuer: str = Field(default="", alias="SUPABASE_JWT_ISSUER")
    supabase_db_url: str = Field(default="", alias="SUPABASE_DB_URL")

    # Data Sources
    data_gov_in_api_key: str = Field(..., alias="DATA_GOV_IN_API_KEY")
    enable_agmarknet: bool = Field(default=False, alias="ENABLE_AGMARKNET")

    # SMS Gateway
    sms_gateway: str = Field(default="mock", alias="SMS_GATEWAY")
    msg91_api_key: str = Field(default="", alias="MSG91_API_KEY")
    msg91_sender_id: str = Field(default="KRBAZR", alias="MSG91_SENDER_ID")
    msg91_dlt_pe_id: str = Field(default="", alias="MSG91_DLT_PE_ID")
    msg91_dlt_te_id_en: str = Field(default="", alias="MSG91_DLT_TE_ID_EN")
    msg91_dlt_te_id_mr: str = Field(default="", alias="MSG91_DLT_TE_ID_MR")
    msg91_dlt_te_id_hi: str = Field(default="", alias="MSG91_DLT_TE_ID_HI")

    # Webhook HMAC — also read here so a value that only exists in `.env`
    # (not exported into os.environ) still protects /sms/webhook.
    inbound_hmac_secret: str = Field(default="", alias="INBOUND_HMAC_SECRET")
    inbound_sig_header: str = Field(default="X-Signature", alias="INBOUND_SIG_HEADER")
    inbound_ts_header: str = Field(default="X-Timestamp", alias="INBOUND_TS_HEADER")

    # Scheduler intervals
    ingestion_interval_hours: int = Field(default=6, alias="INGESTION_INTERVAL_HOURS")
    alert_check_interval_minutes: int = Field(default=60, alias="ALERT_CHECK_INTERVAL_MINUTES")
    forecast_interval_hours: int = Field(default=6, alias="FORECAST_INTERVAL_HOURS")

    # Scope
    target_district: str = Field(default="Nashik", alias="TARGET_DISTRICT")
    target_state: str = Field(default="Maharashtra", alias="TARGET_STATE")

    # CORS — comma-separated origins
    cors_origin: str = Field(default="http://localhost:3000", alias="CORS_ORIGIN")

    run_scheduler: bool = Field(default=True, alias="RUN_SCHEDULER")
    rate_limit_enabled: bool = Field(default=True, alias="RATE_LIMIT_ENABLED")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origin.split(",") if o.strip()]


@lru_cache()
def get_settings():
    return Settings()
