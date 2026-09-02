from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import date, datetime


class BuyerResponse(BaseModel):
    id: str
    name: str
    type: str
    verified: bool
    phone: Optional[str] = None
    district: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    commodity_id: Optional[str] = None
    demand_qty_qtl: Optional[float] = None
    max_price: Optional[float] = None
    quality_requirements: Optional[str] = None
    payment_reliability: Optional[str] = None


class LotCreate(BaseModel):
    commodity_id: str
    market_id: Optional[str] = None
    quantity_qtl: float = Field(gt=0, le=1_000_000)
    grade: Literal["FAQ", "General", "Special"] = "General"
    quality_notes: Optional[str] = None
    harvest_date: Optional[date] = None
    asking_price: Optional[float] = Field(default=None, gt=0, le=10_000_000)
    fpo_id: Optional[str] = None


class LotGradeUpdate(BaseModel):
    grade: Literal["FAQ", "General", "Special"]
    quality_notes: Optional[str] = Field(default=None, max_length=2000)


class LotAggregate(BaseModel):
    lot_ids: List[str] = Field(min_length=2, max_length=50)
    asking_price: Optional[float] = Field(default=None, gt=0)
    market_id: Optional[str] = None


class BuyerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    type: Literal["trader", "processor", "institutional", "fpo", "digital"]
    district: Optional[str] = "Nashik"
    phone: Optional[str] = None
    commodity_id: Optional[str] = None
    demand_qty_qtl: Optional[float] = Field(default=None, gt=0)
    max_price: Optional[float] = Field(default=None, gt=0)
    quality_requirements: Optional[str] = None
    payment_reliability: Optional[Literal["high", "medium", "low"]] = "medium"
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    verified: bool = False


class GrievanceUpdate(BaseModel):
    status: Literal["open", "in_progress", "resolved", "rejected"]


class LotResponse(BaseModel):
    id: str
    user_id: str
    commodity_id: str
    market_id: Optional[str] = None
    quantity_qtl: float
    grade: str
    quality_notes: Optional[str] = None
    harvest_date: Optional[date] = None
    asking_price: Optional[float] = None
    status: str
    fpo_id: Optional[str] = None


class OfferCreate(BaseModel):
    lot_id: str
    buyer_id: str
    price_per_qtl: float = Field(gt=0, le=10_000_000)
    quantity_qtl: float = Field(gt=0, le=1_000_000)


class OfferUpdate(BaseModel):
    status: Literal["pending", "accepted", "rejected", "expired"]


class PaymentCreate(BaseModel):
    offer_id: str
    amount: float = Field(gt=0, le=10_000_000)
    reference: Optional[str] = None


class GrievanceCreate(BaseModel):
    category: Literal["payment", "quality", "logistics", "buyer", "other"]
    description: str = Field(min_length=5, max_length=2000)
    offer_id: Optional[str] = None
    lot_id: Optional[str] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    preferred_language: Optional[Literal["en", "mr", "hi"]] = None
    district: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


class MatchItem(BaseModel):
    buyer_id: str
    buyer_name: str
    buyer_type: str
    verified: bool
    district: Optional[str] = None
    score: float
    reasons: List[str]
    max_price: Optional[float] = None
    demand_qty_qtl: Optional[float] = None
    payment_reliability: Optional[str] = None
    distance_km: Optional[float] = None


class LogisticsBookCreate(BaseModel):
    lot_id: str
    logistics_id: str
    quantity_qtl: Optional[float] = Field(default=None, gt=0)
    scheduled_date: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=500)


class LogisticsBookUpdate(BaseModel):
    status: Literal["requested", "confirmed", "cancelled", "completed"]


class SaleWindowResponse(BaseModel):
    commodity_id: str
    market_id: Optional[str] = None
    recommendation: Literal["sell", "hold", "wait"]
    action: Optional[Literal["SELL_NOW", "HOLD", "WAIT"]] = None
    action_label: Optional[str] = None
    reason: str
    reason_code: Optional[str] = None
    lang: Optional[str] = "en"
    latest_price: Optional[float] = None
    forecast_day1: Optional[float] = None
    forecast_trend: Optional[str] = None
    arrivals_qty: Optional[float] = None
    supply_pressure: Optional[str] = None
    nearby: Optional[list] = None
    storage: Optional[list] = None
    storage_available: Optional[bool] = None
    better_market: Optional[dict] = None
