from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional


class ForecastResponse(BaseModel):
    id:              Optional[str]      = None
    market_id:       str
    commodity_id:    str
    forecast_date:   date
    predicted_price: Optional[float]   = None
    lower_bound:     Optional[float]   = None
    upper_bound:     Optional[float]   = None
    confidence:      Optional[str]     = None
    method:          str
    observations:    Optional[int]     = None
    status:          str
    generated_at:    Optional[datetime] = None

    # Extended fields — populated by /forecasts/summary (joined from markets/commodities)
    market_name:        Optional[str] = None
    district:           Optional[str] = None
    commodity_name_en:  Optional[str] = None
    commodity_name_mr:  Optional[str] = None
    commodity_name_hi:  Optional[str] = None
