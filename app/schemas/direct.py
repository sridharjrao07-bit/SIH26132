"""Request/response models for the direct-channel (disintermediation) API.

Kept separate from ``app/schemas/marketplace.py`` because the direct channel has
a different trust model: the *planning* endpoints are pure computation and take
their inputs inline, so a caller can price a hypothetical trade without writing
anything to the database.  Persistence is a separate, explicit
``POST /plans/{plan_id}/commit`` step.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

Grade = Literal["General", "FAQ", "Special"]
Category = Literal["vegetable", "oilseed", "cereal", "other"]


# ─────────────────────────────────────────────────────────────────────────────
# Transparency
# ─────────────────────────────────────────────────────────────────────────────


class RupeeRequest(BaseModel):
    """Ask where the consumer's rupee goes."""

    commodity_id: Optional[str] = None
    category: Category = "vegetable"
    farm_price: float = Field(..., gt=0, description="Mandi modal price, Rs/quintal")
    retail_price: Optional[float] = Field(None, gt=0, description="Consumer price, Rs/quintal")
    calibrate: bool = True
    stages: Optional[List[dict]] = Field(
        None, description="Optional override of the whole traditional chain stage list"
    )


class FairPriceRequest(BaseModel):
    """Ask what a direct trade should look like on one lane."""

    commodity_id: Optional[str] = None
    category: Category = "vegetable"
    farm_price: float = Field(..., gt=0, description="Farmer's mandi fallback, Rs/quintal")
    retail_price: Optional[float] = Field(None, gt=0, description="Consumer's shop fallback, Rs/quintal")
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lng: float = Field(..., ge=-180, le=180)
    dest_lat: float = Field(..., ge=-90, le=90)
    dest_lng: float = Field(..., ge=-180, le=180)
    alpha: float = Field(0.5, ge=0.0, le=1.0, description="Nash bargaining weight on the farmer")
    platform_fee_pct: float = Field(0.03, ge=0.0, le=0.5)
    load_qtl: Optional[float] = Field(
        None, gt=0, description="Lane volume, for FTL vs LTL freight pricing"
    )
    circuity: float = Field(1.25, ge=1.0, le=3.0)


# ─────────────────────────────────────────────────────────────────────────────
# Planning
# ─────────────────────────────────────────────────────────────────────────────


class LotIn(BaseModel):
    """One farmer lot offered into the direct channel."""

    id: str
    commodity_id: str
    quantity_qtl: float = Field(..., gt=0)
    mandi_price_per_qtl: float = Field(..., ge=0, description="What the mandi would pay")
    lat: Optional[float] = None
    lng: Optional[float] = None
    category: Category = "vegetable"
    grade: Grade = "General"
    farmer_id: Optional[str] = None
    market_name: str = ""

    @field_validator("lat")
    @classmethod
    def _lat(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-90 <= v <= 90):
            raise ValueError("lat must be within [-90, 90]")
        return v

    @field_validator("lng")
    @classmethod
    def _lng(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-180 <= v <= 180):
            raise ValueError("lng must be within [-180, 180]")
        return v


class DemandIn(BaseModel):
    """One consumer demand node."""

    id: str
    commodity_id: str
    quantity_qtl: float = Field(..., gt=0, description="Quintals the consumer wants to receive")
    retail_price_per_qtl: Optional[float] = Field(None, gt=0, description="What the shop charges")
    lat: Optional[float] = None
    lng: Optional[float] = None
    category: Category = "vegetable"
    kind: Literal[
        "household", "rwa", "hostel", "canteen", "hotel", "retailer", "processor", "institution"
    ] = "household"
    label: str = ""
    min_grade: Grade = "General"

    @field_validator("lat")
    @classmethod
    def _lat(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-90 <= v <= 90):
            raise ValueError("lat must be within [-90, 90]")
        return v

    @field_validator("lng")
    @classmethod
    def _lng(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (-180 <= v <= 180):
            raise ValueError("lng must be within [-180, 180]")
        return v


class FreightCfgIn(BaseModel):
    """Freight rate card override (all fields optional)."""

    vehicle_capacity_qtl: Optional[float] = Field(None, gt=0)
    ftl_rate_per_qtl_km: Optional[float] = Field(None, ge=0)
    ltl_rate_per_qtl_km: Optional[float] = Field(None, ge=0)
    ftl_fill_threshold: Optional[float] = Field(None, gt=0, le=1)
    min_freight_per_trip: Optional[float] = Field(None, ge=0)
    loading_cost_per_qtl: Optional[float] = Field(None, ge=0)
    packaging_cost_per_qtl: Optional[float] = Field(None, ge=0)
    last_mile_per_qtl: Optional[float] = Field(None, ge=0)
    circuity: Optional[float] = Field(None, ge=1, le=3)


class PlanRequest(BaseModel):
    """Full planning request: farmer lots + consumer demand + configuration."""

    lots: List[LotIn] = Field(default_factory=list)
    demands: List[DemandIn] = Field(default_factory=list)
    alpha: float = Field(0.5, ge=0.0, le=1.0)
    platform_fee_pct: float = Field(0.03, ge=0.0, le=0.5)
    max_distance_km: float = Field(250.0, ge=0)
    min_allocation_qtl: float = Field(5.0, ge=0)
    cluster_size_km: float = Field(25.0, gt=0)
    circuity: float = Field(1.25, ge=1.0, le=3.0)
    calibrate: bool = True
    enforce_grade: bool = False
    freight: Optional[FreightCfgIn] = None

    @field_validator("lots", "demands")
    @classmethod
    def _cap_size(cls, v: list) -> list:
        # A planning call is O(lots x demands) on the allocation network; an
        # unbounded request is a trivial DoS, so cap it at the API boundary.
        if len(v) > 500:
            raise ValueError("at most 500 items per list")
        return v


class CommitRequest(BaseModel):
    """Persist a computed plan.  The plan body is recomputed server-side."""

    plan: PlanRequest
    commodity_id: Optional[str] = None
    district: str = "Nashik"


# ─────────────────────────────────────────────────────────────────────────────
# Group buys
# ─────────────────────────────────────────────────────────────────────────────


class GroupOrderIn(BaseModel):
    order_id: str
    qtl: float = Field(..., gt=0)
    lat: Optional[float] = None
    lng: Optional[float] = None
    label: str = ""


class GroupBuyRequest(BaseModel):
    """Pool consumer orders and check whether the pool fills a truck."""

    orders: List[GroupOrderIn] = Field(default_factory=list)
    origin_lat: float = Field(..., ge=-90, le=90)
    origin_lng: float = Field(..., ge=-180, le=180)
    min_load_qtl: float = Field(0.0, ge=0)
    cluster_size_km: float = Field(8.0, gt=0)
    circuity: float = Field(1.25, ge=1.0, le=3.0)
    freight: Optional[FreightCfgIn] = None

    @field_validator("orders")
    @classmethod
    def _cap_size(cls, v: list) -> list:
        if len(v) > 500:
            raise ValueError("at most 500 orders")
        return v
