from json import JSONDecodeError

from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import structlog
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from slowapi.middleware import SlowAPIMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from postgrest.exceptions import APIError

from app.errors import json_for_api_error

from app.config import get_settings
from app.rate_limit import limiter
from app.security import SecurityHeadersMiddleware
from app.routers import (
    markets_router,
    commodities_router,
    prices_router,
    forecasts_router,
    alerts_router,
    sms_router,
    admin_router,
    dashboard_router,
    buyers_router,
    lots_router,
    offers_router,
    payments_router,
    grievances_router,
    logistics_router,
    matching_router,
    profile_router,
    intelligence_router,
)

logger = structlog.get_logger()


def _configure_logging(log_level: str) -> None:
    import logging
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    _configure_logging(settings.log_level)
    from app.routers.sms import warmup_verifier
    warmup_verifier()
    scheduler = None
    if settings.run_scheduler:
        from app.services.jobs import setup_scheduler, schedule_startup_catchup
        scheduler = setup_scheduler()
        if scheduler:
            scheduler.start()
        schedule_startup_catchup()
    else:
        logger.info("startup", msg="Scheduler disabled by RUN_SCHEDULER=0")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    settings = get_settings()
    production = settings.app_env.lower() == "production"

    app = FastAPI(
        title="Krishi Bazaar API",
        version="2.0.0",
        description=(
            "Market linkage and price discovery API (SIH26132). "
            "Mandi prices, forecasts, sale-window advice, lots, buyer matching, "
            "offers, payments and grievances."
        ),
        lifespan=lifespan,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Signature", "X-Timestamp"],
    )

    @app.get("/health", tags=["System"])
    def health_check():
        return {"status": "ok"}

    @app.get("/metrics", tags=["System"])
    def metrics():
        """Process liveness in Prometheus text. No secrets. Does not probe Supabase."""
        from fastapi.responses import PlainTextResponse
        body = (
            "# HELP kb_up 1 if this process is serving HTTP\n"
            "# TYPE kb_up gauge\n"
            "kb_up 1\n"
        )
        return PlainTextResponse(body, media_type="text/plain; version=0.0.4")

    @app.exception_handler(APIError)
    async def postgrest_exception_handler(request: Request, exc: APIError):
        logger.warning(
            "postgrest_error",
            path=str(request.url.path),
            method=request.method,
            code=getattr(exc, "code", None),
        )
        return json_for_api_error(exc)

    @app.exception_handler(JSONDecodeError)
    async def json_decode_handler(request: Request, exc: JSONDecodeError):
        return JSONResponse(status_code=400, content={"detail": "invalid json"})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        if isinstance(exc, (HTTPException, StarletteHTTPException, RequestValidationError, APIError)):
            raise exc
        logger.error(
            "unhandled_exception",
            path=str(request.url.path),
            method=request.method,
            error=str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    app.include_router(markets_router)
    app.include_router(commodities_router)
    app.include_router(prices_router)
    app.include_router(forecasts_router)
    app.include_router(alerts_router, prefix="/api/v1")
    app.include_router(sms_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(dashboard_router)
    app.include_router(buyers_router)
    app.include_router(lots_router)
    app.include_router(offers_router)
    app.include_router(payments_router)
    app.include_router(grievances_router)
    app.include_router(logistics_router)
    app.include_router(matching_router)
    app.include_router(profile_router)
    app.include_router(intelligence_router)

    return app


app = create_app()
