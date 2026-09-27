"""Transparency: the consumer rupee, and the fair farm-gate price.

Two outputs, both aimed at the problem statement's core complaint.

1. :func:`leakage_report` — *where does the consumer's rupee go?*  Pushes a
   farm-gate price through the traditional chain and attributes every rupee of
   absorption to a named stage, split into real handling cost and margin.

2. :func:`direct_quote` — *what should this trade look like?*  Builds the direct
   channel for a specific lane (distance-dependent freight), splits the pie via
   Nash bargaining, and returns both sides' price.

The second is the number the platform actually shows a farmer and a consumer.
The first is the number that convinces a judge the second is worth building.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from direct.logistics import FreightConfig, lane_handling_per_qtl, road_distance_km
from direct.surplus import Split, split_surplus
from direct.value_chain import ChainResult, ValueChain, calibrate_margin_scale

_EPS = 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# Leakage
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LeakageReport:
    """Where the consumer's rupee goes, and how much of it is avoidable."""

    commodity: str
    farm_price: float  # ₹/quintal at the farm gate (mandi modal)
    retail_price: float  # ₹/quintal at the shop
    chain: ChainResult
    avoidable_per_farm_qtl: float  # ₹ taken by non-essential stages
    unavoidable_per_farm_qtl: float  # ₹ spent on essential work
    farmer_share_pct: float
    calibration_status: str
    calibrated_margin_scale: float
    verdict: str

    def to_dict(self) -> dict:
        chain = self.chain.to_dict()
        chain["avoidable_per_farm_qtl"] = round(self.avoidable_per_farm_qtl, 4)
        chain["unavoidable_per_farm_qtl"] = round(self.unavoidable_per_farm_qtl, 4)
        chain["verdict"] = self.verdict
        return {
            "commodity": self.commodity,
            "farm_price": round(self.farm_price, 4),
            "retail_price": round(self.retail_price, 4),
            "calibration_status": self.calibration_status,
            "calibrated_margin_scale": round(self.calibrated_margin_scale, 6),
            "farmer_share_pct": round(self.farmer_share_pct, 4),
            "avoidable_per_farm_qtl": round(self.avoidable_per_farm_qtl, 4),
            "unavoidable_per_farm_qtl": round(self.unavoidable_per_farm_qtl, 4),
            "verdict": self.verdict,
            "chain": chain,
        }


def _verdict(farmer_share_pct: float) -> str:
    if farmer_share_pct >= 60:
        return "Farmer retains a healthy share; limited headroom for direct trade."
    if farmer_share_pct >= 45:
        return "Typical horticulture spread: meaningful headroom for direct trade."
    if farmer_share_pct >= 30:
        return "Heavy intermediary absorption: direct trade would materially help the farmer."
    return "Severe absorption: the farmer sees very little of the consumer rupee."


def leakage_report(
    traditional_chain: ValueChain,
    farm_price: float,
    retail_price: float,
    commodity: str = "",
    calibrate: bool = True,
    calibration_hi: float = 25.0,
) -> LeakageReport:
    """Attribute the gap between the mandi price and the shop price.

    Parameters
    ----------
    traditional_chain
        The chain model for this commodity.  Its *shape* (relative margins,
        physical losses, handling costs) is taken as given.
    farm_price
        Observed mandi modal price, ₹/quintal.
    retail_price
        Observed consumer price, ₹/quintal.
    calibrate
        When ``True`` (default) the chain's overall margin level is re-fitted so
        the model reproduces this exact ``(farm, retail)`` pair before the
        attribution is computed.  Without calibration the report describes a
        hypothetical chain; with it, it describes *this* market on *this* day.
    """
    if farm_price < 0 or retail_price < 0:
        raise ValueError("prices must be non-negative")

    scale = traditional_chain.margin_scale
    status = "given"
    if calibrate and farm_price > _EPS and retail_price > _EPS:
        lam, st = calibrate_margin_scale(
            traditional_chain, farm_price, retail_price, hi=calibration_hi
        )
        scale = lam
        status = st
        traditional_chain = traditional_chain.scaled(lam)

    chain_result = traditional_chain.forward(farm_price)

    avoidable = sum(s.take for s in chain_result.stages if not s.essential)
    unavoidable = sum(s.take for s in chain_result.stages if s.essential)

    return LeakageReport(
        commodity=commodity,
        farm_price=float(farm_price),
        retail_price=float(retail_price),
        chain=chain_result,
        avoidable_per_farm_qtl=avoidable,
        unavoidable_per_farm_qtl=unavoidable,
        farmer_share_pct=chain_result.farmer_share_pct,
        calibration_status=status,
        calibrated_margin_scale=scale,
        verdict=_verdict(chain_result.farmer_share_pct),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Direct quote
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DirectQuote:
    """A priced direct trade for one lane, plus its provenance."""

    split: Split
    distance_km: float
    freight_per_qtl: float
    handling_per_qtl: float
    freight_basis: str  # how the freight figure was derived
    direct_chain: ValueChain
    traditional_chain: ValueChain
    leakage: Optional[LeakageReport]

    @property
    def viable(self) -> bool:
        return self.split.viable

    def to_dict(self) -> dict:
        return {
            "viable": self.viable,
            "distance_km": round(self.distance_km, 3),
            "freight_per_qtl": round(self.freight_per_qtl, 4),
            "handling_per_qtl": round(self.handling_per_qtl, 4),
            "freight_basis": self.freight_basis,
            "split": self.split.to_dict(),
            "direct_chain": self.direct_chain.to_dict(),
            "consumer_rupee": self.leakage.to_dict() if self.leakage else None,
        }


def direct_quote(
    traditional_chain: ValueChain,
    direct_chain: ValueChain,
    farm_price: float,
    retail_price: float,
    distance_km: float,
    freight_cfg: FreightConfig,
    alpha: float = 0.5,
    quantity_qtl: Optional[float] = None,
    commodity: str = "",
    include_leakage: bool = True,
) -> DirectQuote:
    """Price one direct trade on one lane.

    The lane's freight is computed from the actual distance, folded into the
    direct chain's freight stage, and then the pie is split by Nash bargaining.

    Parameters
    ----------
    farm_price
        Farmer's fallback (mandi modal), ₹/quintal at the farm gate.
    retail_price
        Consumer's fallback (shop price), ₹/quintal at the shop.
    distance_km
        Road distance, farm collection → consumer drop.
    alpha
        Bargaining weight on the farmer (0.5 = symmetric Nash).
    quantity_qtl
        Only used to pick the freight rate basis (FTL vs LTL) for a whole-lane
        quote.  ``None`` prices the lane per quintal.

    The direct chain's logistics cost ``T`` is the freight from the rate card
    (which is lane- and volume-dependent) plus packing/handling/last mile, all
    expressed ₹ per quintal loaded at the farm.  The chain grosses that up for
    in-transit spoilage, so :func:`~direct.surplus.split_surplus` can work
    entirely in farm-gate quintals.

    **Freight basis.**  Priced in isolation, one quintal costs a whole truck
    (the per-trip minimum), which would make every lane look hopeless.  So:

    * with ``quantity_qtl`` the lane is priced through the real rate card, so
      the quote reflects that exact volume;
    * without it the quote uses :func:`~direct.pipeline.planning_rate_per_qtl`,
      i.e. it assumes this lane joins a consolidated load.  ``freight_basis``
      in the response says which was used, so the caller is never misled.
    """
    from direct.logistics import freight_for_lane
    from direct.pipeline import planning_rate_per_qtl
    from direct.value_chain import default_direct_chain

    if quantity_qtl is not None:
        quote = freight_for_lane(quantity_qtl, distance_km, freight_cfg)
        freight_per_loaded_qtl = quote.per_qtl
        freight_basis = f"rate_card@{quantity_qtl:g}qtl"
    else:
        freight_per_loaded_qtl = planning_rate_per_qtl(distance_km, freight_cfg)
        freight_basis = "consolidated_assumption"
    handling = lane_handling_per_qtl(freight_cfg)

    # Rebuild the chain for THIS lane: freight is distance- and volume-specific.
    category = _category_of(direct_chain)
    lane_chain = default_direct_chain(
        category=category,
        platform_fee_pct=direct_chain.platform_fee,
        freight_cost_per_qtl=freight_per_loaded_qtl + handling,
    )

    w_direct = lane_chain.delivered_ratio
    if w_direct <= _EPS:
        raise ValueError("direct chain delivered ratio must be > 0")

    logistics_per_farm_qtl = freight_per_loaded_qtl + handling

    split = split_surplus(
        retail_price=retail_price,
        delivered_ratio=w_direct,
        logistics_per_farm_qtl=logistics_per_farm_qtl,
        effective_markup=lane_chain.effective_markup,
        farmer_fallback=farm_price,  # the mandi price, ₹/quintal at the farm gate
        alpha=alpha,
    )
    direct_chain = lane_chain

    leakage = None
    if include_leakage:
        leakage = leakage_report(
            traditional_chain, farm_price, retail_price, commodity=commodity, calibrate=True
        )

    return DirectQuote(
        split=split,
        distance_km=distance_km,
        freight_per_qtl=freight_per_loaded_qtl,
        handling_per_qtl=handling,
        freight_basis=freight_basis,
        direct_chain=direct_chain,
        traditional_chain=traditional_chain,
        leakage=leakage,
    )


def _category_of(chain) -> str:
    """Recover the commodity category from a chain's name (``direct:vegetable``)."""
    name = getattr(chain, "name", "") or ""
    if ":" in name:
        tail = name.rsplit(":", 1)[-1]
        if tail in {"vegetable", "oilseed", "cereal", "other"}:
            return tail
    return "vegetable"


def distance_between(
    origin: tuple,
    destination: tuple,
    cfg: FreightConfig,
) -> Optional[float]:
    """Road distance helper used by callers that hold ``(lat, lng)`` tuples."""
    if not origin or not destination:
        return None
    return road_distance_km(origin[0], origin[1], destination[0], destination[1], cfg.circuity)
