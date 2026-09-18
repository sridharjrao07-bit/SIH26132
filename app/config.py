from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, model_validator
"""Runtime configuration (12-factor env vars).

Design rules for this module
----------------------------
1. **No silent fallbacks.** Every enumerated setting is a ``Literal``, so a typo
   such as ``AUTH_DB_ENFORCEMENT=rls2`` or ``AUTH_DB_ENFORECEMENT=rls`` (the
   second is an unknown key and therefore ignored by pydantic-settings) fails
   loudly at import/startup instead of quietly selecting an unsafe default.
   Cross-field production requirements are enforced by ``Settings.check_runtime``
   during startup (``app/startup_checks.py``) so tests and tooling can still
   build a Settings object without a full production environment.

2. **Env names match field names case-insensitively** (``SUPABASE_URL`` →
   ``supabase_url``).  Do not use ``Field(alias=...)``: pydantic-settings then
   stores the env value under the alias and constructor kwargs under the field
   name, so ``.env`` silently wins over constructor defaults in confusing ways.

3. ``env_ignore_empty=False`` means an empty string in the environment is
   treated as a value, not as "not set".  This prevents accidentally overriding
   a required field with an empty CI/CD secret.

4. ``extra="forbid"`` is intentionally NOT set here because ``.env`` files
   frequently contain project-wide keys that don't belong to this service.
   Unknown keys are silently dropped by pydantic-settings before the model
   sees them, so ``extra="forbid"`` would raise on every unrelated .env line.
"""
from typing import List, Literal
from functools import lru_cache


class Settings(BaseSettings):
    """Env names match field names case-insensitively (SUPABASE_URL → supabase_url).

    Do not set Field(alias="ENV_NAME"): pydantic-settings then stores env under the
    alias and constructor kwargs under the field name, so .env silently wins.
    """

    app_env: Literal["development", "staging", "production"] = Field(default="development")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(default="INFO")

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
    sms_gateway: Literal["mock", "msg91"] = Field(default="mock")
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

    # Ingestion constraints
    max_arrival_qty_qtl: float = Field(default=1_000_000.0)

    # CORS — comma-separated origins
    cors_origin: str = Field(default="http://localhost:3000,http://localhost:5173")

    run_scheduler: bool = Field(default=True)
    rate_limit_enabled: bool = Field(default=True)

    # ── Forecasting & Events ──────────────────────────────────────────────────
    forecast_model: Literal["auto", "lgbm", "prophet", "naive"] = Field(default="auto")

    event_job_enabled: bool = Field(default=False)
    event_llm: Literal["off", "openai", "gemini"] = Field(default="off")
    event_llm_provider: str = Field(default="openai")
    event_llm_model: str = Field(default="gpt-4o-mini")
    event_llm_api_key: str = Field(default="")
    event_llm_base_url: str = Field(default="")
    event_sources: str = Field(default="pib,news,bulletin")
    events_source_mode: Literal["off", "live", "mock"] = Field(default="off")
    backfill_days: int = Field(default=730)

    # ── Auth DB enforcement ───────────────────────────────────────────────────
    # "rls"  — per-request user-scoped Supabase client; RLS policies enforce
    #          at the DB boundary.  Requires token-claims alignment (iss, role).
    # "app"  — service-role client (current legacy behaviour); application-level
    #          .eq("user_id", ...) filters are the sole isolation layer.
    #          Startup rejects this in production unless kb_allow_app_mode=True.
    auth_db_enforcement: Literal["rls", "app"] = Field(default="rls")

    # Emergency override: allow app-mode in production (must be explicit).
    kb_allow_app_mode: bool = Field(default=False)

    # Live RLS probe flag (tests/test_rls_live.py).
    kb_live_supabase: bool = Field(default=False)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        env_ignore_empty=False,
    )

    def cors_origins(self) -> List[str]:
        return [o.strip() for o in self.cors_origin.split(",") if o.strip()]

    def check_runtime(self) -> None:
        """Cross-field production invariants.

        Called explicitly from ``app/startup_checks.py`` so tests and tooling
        can still instantiate Settings without a full production environment.
        Raises ``RuntimeError`` on the first violated invariant.
        """
        is_prod = self.app_env == "production"

        if is_prod and not self.supabase_jwt_issuer:
            raise RuntimeError(
                "STARTUP REJECTED: SUPABASE_JWT_ISSUER must be set in production. "
                "Set it to your Supabase project's JWT issuer URL "
                "(e.g. https://<project>.supabase.co/auth/v1)."
            )

        if is_prod and self.auth_db_enforcement == "app" and not self.kb_allow_app_mode:
            raise RuntimeError(
                "STARTUP REJECTED: AUTH_DB_ENFORCEMENT=app in production environment.\n"
                "Data isolation currently relies solely on application-level filters.\n"
                "Fix: set AUTH_DB_ENFORCEMENT=rls (after aligning token claims) or,\n"
                "     if you know the risk, set KB_ALLOW_APP_MODE=1 to override."
            )

        if is_prod and self.sms_gateway == "msg91" and not self.msg91_api_key:
            raise RuntimeError(
                "STARTUP REJECTED: SMS_GATEWAY=msg91 in production but MSG91_API_KEY is empty."
            )

        if is_prod and not self.inbound_hmac_secret:
            raise RuntimeError(
                "STARTUP REJECTED: INBOUND_HMAC_SECRET must be set in production "
                "to protect the /sms/webhook endpoint from unauthenticated callers."
            )


@lru_cache()
def get_settings() -> Settings:
    return Settings()
