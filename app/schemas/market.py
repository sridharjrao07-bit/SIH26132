from typing import Optional

from pydantic import BaseModel


class MarketResponse(BaseModel):
    id: str
    name: str
    district: str
    state: str
    taluka: Optional[str] = None
    lat: float
    lng: float
    is_active: bool
