from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from functools import lru_cache

class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    
    # Supabase
    supabase_url: str = Field(..., alias="SUPABASE_URL")
    supabase_anon_key: str = Field(..., alias="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(..., alias="SUPABASE_SERVICE_ROLE_KEY")
    supabase_jwt_secret: str = Field(..., alias="SUPABASE_JWT_SECRET")
    supabase_db_url: str = Field(..., alias="SUPABASE_DB_URL")
    
    # Data Sources
    data_gov_in_api_key: str = Field(..., alias="DATA_GOV_IN_API_KEY")
    
    # SMS Gateway
    sms_gateway: str = Field(default="mock", alias="SMS_GATEWAY")
    msg91_api_key: str = Field(default="", alias="MSG91_API_KEY")
    msg91_sender_id: str = Field(default="KRBAZR", alias="MSG91_SENDER_ID")
    msg91_dlt_pe_id: str = Field(default="", alias="MSG91_DLT_PE_ID")
    msg91_dlt_te_id_en: str = Field(default="", alias="MSG91_DLT_TE_ID_EN")
    msg91_dlt_te_id_mr: str = Field(default="", alias="MSG91_DLT_TE_ID_MR")
    msg91_dlt_te_id_hi: str = Field(default="", alias="MSG91_DLT_TE_ID_HI")
    
    # Scheduler intervals
    ingestion_interval_hours: int = Field(default=6, alias="INGESTION_INTERVAL_HOURS")
    alert_check_interval_minutes: int = Field(default=60, alias="ALERT_CHECK_INTERVAL_MINUTES")
    forecast_interval_hours: int = Field(default=6, alias="FORECAST_INTERVAL_HOURS")
    
    # Scope
    target_district: str = Field(default="Nashik", alias="TARGET_DISTRICT")
    target_state: str = Field(default="Maharashtra", alias="TARGET_STATE")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

@lru_cache()
def get_settings():
    return Settings()
