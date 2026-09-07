"""Fail-closed startup checks for Krishi Bazaar.

Called from ``app/main.py`` inside the ``lifespan`` context before the app
begins serving requests.  Any failure here aborts startup with a clear error
message rather than silently running in an unsafe configuration.

Pattern mirrors the inbound HMAC secret check introduced in the security
hardening phase.
"""
import structlog
from app.config import Settings

_log = structlog.get_logger()


def run_startup_checks(settings: Settings) -> None:
    """Run all startup assertions.  Raises ``RuntimeError`` on failure.

    Currently checks:
    - Production + app-mode enforcement without explicit override flag.
    """
    _check_auth_enforcement(settings)
    _log.info("startup_checks_passed", auth_db_enforcement=settings.auth_db_enforcement)


def _check_auth_enforcement(settings: Settings) -> None:
    """Block production startup when running in app-layer enforcement mode.

    When ``AUTH_DB_ENFORCEMENT=app`` the only isolation between tenants is
    the application-level ``.eq("user_id", ...)`` filters.  A single missed
    filter leaks data across all users.  Production must use ``"rls"`` unless
    the operator has read this message and explicitly acknowledged the risk by
    setting ``KB_ALLOW_APP_MODE=1``.
    """
    is_production = settings.app_env.lower() == "production"
    is_app_mode = settings.auth_db_enforcement == "app"

    if is_production and is_app_mode and not settings.kb_allow_app_mode:
        raise RuntimeError(
            "STARTUP REJECTED: AUTH_DB_ENFORCEMENT=app in production environment.\n"
            "Data isolation currently relies solely on application-level filters.\n"
            "Fix: set AUTH_DB_ENFORCEMENT=rls (after aligning token claims) or,\n"
            "     if you know the risk, set KB_ALLOW_APP_MODE=1 to override."
        )

    if is_app_mode:
        _log.warning(
            "auth_enforcement_app_mode",
            app_env=settings.app_env,
            msg=(
                "AUTH_DB_ENFORCEMENT=app: service-role client used for authenticated requests. "
                "Tenant isolation is application-layer only. "
                "Switch to AUTH_DB_ENFORCEMENT=rls after token-claims alignment."
            ),
        )
