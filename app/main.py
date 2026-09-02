from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import structlog

from app.config import get_settings
from app.routers import (
    markets_router,
    commodities_router,
    prices_router,
    forecasts_router,
    alerts_router,
    sms_router,
    admin_router,
    dashboard_router,
)

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = None
    if settings.run_scheduler:
        from app.jobs import setup_scheduler, schedule_startup_catchup
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
    
    app = FastAPI(
        title="Krishi Bazaar API",
        version="1.0.0",
        description="Agmarknet Data Aggregator & Forecast API (SIH26132)",
        lifespan=lifespan,
    )

    # CORS configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check
    @app.get("/health", tags=["System"])
    def health_check():
        return {"status": "ok", "environment": settings.app_env}

    # Mount API routers
    app.include_router(markets_router)
    app.include_router(commodities_router)
    app.include_router(prices_router)
    app.include_router(forecasts_router)
    app.include_router(alerts_router, prefix="/api/v1")
    app.include_router(sms_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(dashboard_router)

    return app

app = create_app()
