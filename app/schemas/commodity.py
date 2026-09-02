from pydantic import BaseModel
from typing import Optional

class CommodityResponse(BaseModel):
    id: str
    name_en: str
    name_mr: str
    name_hi: str
    category: str
    standard_unit: str
    sanity_min: float
    sanity_max: float
