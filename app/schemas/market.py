from pydantic import BaseModel
from typing import Optional

class MarketResponse(BaseModel):
    id: str
    name: str
    district: str
    state: str
    taluka: Optional[str] = None
    lat: float
    lng: float
    is_active: bool
