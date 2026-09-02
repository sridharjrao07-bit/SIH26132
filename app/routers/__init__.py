from .markets import router as markets_router
from .commodities import router as commodities_router
from .prices import router as prices_router
from .forecasts import router as forecasts_router
from .alerts import router as alerts_router
from .sms import router as sms_router
from .admin import router as admin_router
from .dashboard import router as dashboard_router

__all__ = [
    "markets_router",
    "commodities_router",
    "prices_router",
    "forecasts_router",
    "alerts_router",
    "sms_router",
    "admin_router",
    "dashboard_router",
]
