from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional

class PriceResponse(BaseModel):
    id: str
    market_id: str
    commodity_id: str
    arrival_date: date
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    modal_price: float
    unit: str
    arrival_qty: Optional[float] = None
    variety: str
    grade: str
    source: str
    created_at: datetime
    
    # Extended fields (joined from markets/commodities)
    market_name: Optional[str] = None
    commodity_name_en: Optional[str] = None
    commodity_name_mr: Optional[str] = None
    commodity_name_hi: Optional[str] = None
    district: Optional[str] = None
