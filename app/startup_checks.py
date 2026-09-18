"""Fail-closed startup checks for Krishi Bazaar.

Called from ``app/main.py`` inside the ``lifespan`` context before the app
begins serving requests.  Any failure here aborts startup with a clear error
message rather than silently running in an unsafe configuration.

Design
------
- ``run_startup_checks`` delegates *production invariants* to
  ``settings.check_runtime()`` (cross-field rules that only apply in production)
  and handles *structural* checks that apply in every environment here.
- Concurrency detection is a warning, not a hard fail — some operators
  intentionally run multiple uvicorn workers behind an external lock store.
"""
import structlog
from app.config import Settings

_log = structlog.get_logger()

# Modules that must be importable for the application to serve requests
# correctly.  Missing here means a dependency is not installed or a module
# has a syntax error.
_REQUIRED_MODULES = [
    "app.routers",
    "app.auth",
    "app.deps",
    "app.errors",
    "app.rate_limit",
    "app.security",
    "app.services.jobs",
    "forecasting",
    "ingestion",
    "notifications",
    "events",
]


def run_startup_checks(settings: Settings) -> None:
    """Run all startup assertions.  Raises ``RuntimeError`` on failure.

    Currently checks:
    - Module importability (all required packages present).
    - Cross-field production invariants via ``settings.check_runtime()``.
    - Concurrency warning (multi-worker breaks in-process scheduler).
    """
    _check_imports()
    settings.check_runtime()
    _check_concurrency()
    _log.info(
        "startup_checks_passed",
        auth_db_enforcement=settings.auth_db_enforcement,
        app_env=settings.app_env,
    )


def _check_imports() -> None:
    """Verify that all required application modules can be imported.

    Catches missing dependencies (e.g. a wheel not installed) or syntax errors
    that would otherwise surface as an opaque 500 on the first request.
    """
    import importlib

    for module in _REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except ImportError as exc:
            raise RuntimeError(
                f"STARTUP REJECTED: Required module '{module}' failed to import: {exc}\n"
                "Run 'pip install -r requirements.txt' to ensure all dependencies are installed."
            ) from exc


def _check_concurrency() -> None:
    import sys
    import os

    workers_str = os.environ.get("WEB_CONCURRENCY", "1")
    try:
        workers = int(workers_str)
    except ValueError:
        workers = 1

    argv_workers = 1
    if "--workers" in sys.argv:
        try:
            idx = sys.argv.index("--workers")
            argv_workers = int(sys.argv[idx + 1])
        except (ValueError, IndexError):
            pass

    if workers > 1 or argv_workers > 1:
        _log.warning(
            "concurrency_warning",
            web_concurrency=workers,
            argv_workers=argv_workers,
            msg=(
                "Running with --workers > 1 detected. "
                "The in-process APScheduler and job_locks table assume a single worker. "
                "Use a dedicated api-worker service with RUN_SCHEDULER=1 and set "
                "RUN_SCHEDULER=0 on the api replica group."
            ),
        )
