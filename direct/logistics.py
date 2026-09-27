"""Road distance and freight economics.

Why this module has to exist
----------------------------
The whole premise of disintermediation is that you can remove five margins but
you cannot remove the truck.  If freight is modelled badly the engine will cheerfully
promise a farmer a 60% gain on a lane where the truck eats all of it.  So the
rate card here is deliberately conservative and shaped the way real Indian
aggregators price:

* **FTL vs LTL.**  A full truckload costs far less per quintal-km than a
  part-load, because the driver, the diesel and the tolls are paid either way.
* **A minimum freight per trip.**  Nobody moves 4 quintals 60 km for ₹67, so
  every vehicle has a floor charge.  This single rule is what makes
  consolidation valuable and is the reason :mod:`direct.consolidation` exists.
* **Circuity.**  Straight-line distance is not road distance.  Rural Indian
  lane geometry typically runs 20–35% over the great-circle figure.

Everything is ₹ per quintal (the unit the rest of the engine uses) and the
outputs are per-lane, which is what consolidation and allocation consume.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Optional

# Earth radius, km (mean).
_EARTH_R_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> Optional[float]:
    """Great-circle distance in km, rounded to 3 decimals.

    Returns ``None`` when any coordinate is missing — callers decide whether an
    unknown distance is fatal or merely unhelpful, and a silent ``0.0`` would
    make an unknown lane look like a free one.
    """
    if None in (lat1, lng1, lat2, lng2):
        return None
    try:
        la1, ln1, la2, ln2 = float(lat1), float(lng1), float(lat2), float(lng2)
    except (TypeError, ValueError):
        return None
    p1, p2 = math.radians(la1), math.radians(la2)
    dp = p2 - p1
    dl = math.radians(ln2 - ln1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    # Clamp guards against a = 1.0000000002 from floating point at antipodes.
    a = min(1.0, max(0.0, a))
    return round(2.0 * _EARTH_R_KM * math.asin(math.sqrt(a)), 3)


def road_distance_km(
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
    circuity: float = 1.25,
) -> Optional[float]:
    """Road distance approximated as great-circle × circuity.

    ``circuity = 1.25`` is a common planning factor for Indian rural/state-highway
    lanes.  Override with a real routing API when one is available; the call site
    (``DirectConfig.circuity``) is the single place to do it.
    """
    straight = haversine_km(lat1, lng1, lat2, lng2)
    if straight is None:
        return None
    if circuity < 1.0:
        raise ValueError(f"circuity must be >= 1.0, got {circuity}")
    return round(straight * circuity, 3)


@dataclass(frozen=True)
class FreightConfig:
    """Rate card.  Defaults are realistic planning figures for Maharashtra lanes.

    Attributes
    ----------
    vehicle_capacity_qtl
        Payload of the standard vehicle used for consolidation (a 9-tonne
        truck ≈ 90 quintals, net of tare).
    ftl_rate_per_qtl_km
        ₹ per quintal-km when the vehicle is effectively full.
    ltl_rate_per_qtl_km
        ₹ per quintal-km for a part-load.  Roughly 2× FTL, reflecting that the
        fixed trip cost is spread over less cargo.
    ftl_fill_threshold
        Fill fraction at or above which the FTL rate applies.
    min_freight_per_trip
        Floor charge per vehicle (₹).  This is what makes small orders expensive
        and consolidation valuable.
    loading_cost_per_qtl
        Loading + unloading labour, ₹/quintal.
    packaging_cost_per_qtl
        Crates / bags for direct delivery, ₹/quintal.  Direct channels spend
        *more* here than bulk mandi handling and less on everything else.
    last_mile_per_qtl
        Final-mile distribution inside the destination, ₹/quintal.
    circuity
        Road distance ÷ great-circle distance.
    """

    vehicle_capacity_qtl: float = 90.0
    ftl_rate_per_qtl_km: float = 0.28
    ltl_rate_per_qtl_km: float = 0.62
    ftl_fill_threshold: float = 0.85
    min_freight_per_trip: float = 1800.0
    loading_cost_per_qtl: float = 12.0
    packaging_cost_per_qtl: float = 16.0
    last_mile_per_qtl: float = 9.0
    circuity: float = 1.25

    def __post_init__(self) -> None:
        for name in (
            "vehicle_capacity_qtl",
            "ftl_rate_per_qtl_km",
            "ltl_rate_per_qtl_km",
            "min_freight_per_trip",
            "loading_cost_per_qtl",
            "packaging_cost_per_qtl",
            "last_mile_per_qtl",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0, got {getattr(self, name)}")
        if self.vehicle_capacity_qtl <= 0:
            raise ValueError("vehicle_capacity_qtl must be > 0")
        if not (0.0 < self.ftl_fill_threshold <= 1.0):
            raise ValueError("ftl_fill_threshold must be within (0, 1]")
        if self.ltl_rate_per_qtl_km < self.ftl_rate_per_qtl_km:
            raise ValueError("ltl_rate_per_qtl_km must be >= ftl_rate_per_qtl_km")
        if self.circuity < 1.0:
            raise ValueError("circuity must be >= 1.0")

    def to_dict(self) -> dict:
        return {
            "vehicle_capacity_qtl": self.vehicle_capacity_qtl,
            "ftl_rate_per_qtl_km": self.ftl_rate_per_qtl_km,
            "ltl_rate_per_qtl_km": self.ltl_rate_per_qtl_km,
            "ftl_fill_threshold": self.ftl_fill_threshold,
            "min_freight_per_trip": self.min_freight_per_trip,
            "loading_cost_per_qtl": self.loading_cost_per_qtl,
            "packaging_cost_per_qtl": self.packaging_cost_per_qtl,
            "last_mile_per_qtl": self.last_mile_per_qtl,
            "circuity": self.circuity,
        }

    @classmethod
    def from_dict(cls, payload: Optional[dict]) -> "FreightConfig":
        if not payload:
            return cls()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known and v is not None})


@dataclass(frozen=True)
class FreightQuote:
    """Result of pricing one lane's consolidated load."""

    load_qtl: float
    distance_km: float
    vehicles: int
    fill_pct: float
    rate_basis: str  # 'FTL' | 'LTL'
    variable_freight: float  # ₹ before the minimum-freight floor
    freight: float  # ₹ actually charged
    per_qtl: float  # ₹/quintal actually charged
    handling_per_qtl: float  # loading + packing + last mile, ₹/quintal
    total_per_qtl: float  # freight + handling, ₹/quintal

    def to_dict(self) -> dict:
        return {
            "load_qtl": round(self.load_qtl, 4),
            "distance_km": round(self.distance_km, 3),
            "vehicles": self.vehicles,
            "fill_pct": round(self.fill_pct, 4),
            "rate_basis": self.rate_basis,
            "variable_freight": round(self.variable_freight, 4),
            "freight": round(self.freight, 4),
            "per_qtl": round(self.per_qtl, 4),
            "handling_per_qtl": round(self.handling_per_qtl, 4),
            "total_per_qtl": round(self.total_per_qtl, 4),
        }


def freight_for_lane(load_qtl: float, distance_km: float, cfg: FreightConfig) -> FreightQuote:
    """Price a consolidated lane load.

    The load is spread evenly across ``ceil(load / capacity)`` vehicles — that is
    what a dispatcher does, and it is also the best case for fill, so the quote
    is not pessimistic.  The per-trip minimum is then applied per vehicle.

    Notes
    -----
    ``load_qtl`` is **farm-gate** quintals.  Freight is incurred on what is
    loaded, not on what survives the journey, so no delivered-ratio adjustment is
    applied here.
    """
    if load_qtl < 0:
        raise ValueError(f"load_qtl must be >= 0, got {load_qtl}")
    if distance_km < 0:
        raise ValueError(f"distance_km must be >= 0, got {distance_km}")

    handling = cfg.loading_cost_per_qtl + cfg.packaging_cost_per_qtl + cfg.last_mile_per_qtl

    if load_qtl <= 0:
        return FreightQuote(
            load_qtl=0.0,
            distance_km=distance_km,
            vehicles=0,
            fill_pct=0.0,
            rate_basis="LTL",
            variable_freight=0.0,
            freight=0.0,
            per_qtl=0.0,
            handling_per_qtl=handling,
            total_per_qtl=handling,
        )

    vehicles = max(1, math.ceil(load_qtl / cfg.vehicle_capacity_qtl - 1e-9))
    per_vehicle = load_qtl / vehicles
    fill = per_vehicle / cfg.vehicle_capacity_qtl
    rate_basis = "FTL" if fill >= cfg.ftl_fill_threshold - 1e-12 else "LTL"
    rate = cfg.ftl_rate_per_qtl_km if rate_basis == "FTL" else cfg.ltl_rate_per_qtl_km

    variable = load_qtl * rate * distance_km
    floor = vehicles * cfg.min_freight_per_trip
    freight = max(variable, floor)

    return FreightQuote(
        load_qtl=load_qtl,
        distance_km=distance_km,
        vehicles=vehicles,
        fill_pct=round(100.0 * fill, 4),
        rate_basis=rate_basis,
        variable_freight=variable,
        freight=freight,
        per_qtl=freight / load_qtl,
        handling_per_qtl=handling,
        total_per_qtl=freight / load_qtl + handling,
    )


def lane_handling_per_qtl(cfg: FreightConfig) -> float:
    """Non-freight handling cost, ₹/quintal (loading + packing + last mile)."""
    return cfg.loading_cost_per_qtl + cfg.packaging_cost_per_qtl + cfg.last_mile_per_qtl


def with_capacity(cfg: FreightConfig, capacity_qtl: float) -> FreightConfig:
    """Return ``cfg`` with a different vehicle size (used by group-buy sizing)."""
    return replace(cfg, vehicle_capacity_qtl=capacity_qtl)
