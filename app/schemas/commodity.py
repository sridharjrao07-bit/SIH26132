from pydantic import BaseModel


class CommodityResponse(BaseModel):
    id: str
    name_en: str
    name_mr: str
    name_hi: str
    category: str
    standard_unit: str
