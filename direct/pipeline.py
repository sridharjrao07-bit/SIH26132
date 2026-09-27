"""End-to-end planning: farmer lots + consumer demand → auditable direct plan.

This is the module the API calls.  It is deliberately a thin, readable
orchestration over the primitives in the rest of the package, because the
interesting mathematics lives in :mod:`direct.value_chain`,
:mod:`direct.surplus` and :mod:`direct.allocation`.

Pipeline
--------
1.  **Calibrate.**  For each commodity, fit the traditional chain's margin scale
    so the model reproduces the observed (mandi, retail) pair.  One scalar per
    commodity, fitted by monotone bisection.
2.  **Build lanes.**  For every (lot, demand) pair compute the direct chain for
    that lane (freight is distance-dependent), then the maximum surplus per
    quintal.  Drop lanes that are unreachable, out of grade, or simply not worth
    it (``Π_max <= 0``).
3.  **Allocate.**  Solve the transportation problem with min-cost flow, so the
    *total* surplus is maximised rather than greedily per-lane.
4.  **Re-plan for viability.**  A plan that sends 0.4 quintals down a lane is
    not operable.  Lanes below ``min_allocation_qtl`` are removed and the flow
    re-solved, iterating until stable (or the iteration cap is hit).
5.  **Consolidate.**  Group the resulting flows into lanes, pack them into
    trucks, and re-price freight with the *consolidated* load — which is usually
    cheaper per quintal than the per-lane estimate used in step 2, so the
    realised numbers are recomputed, not re-used.
6.  **Split.**  Apply Nash bargaining per lane with the consolidated cost, so
    farmer and consumer both see a number that survives contact with the truck.
7.  **Roll up.**  Aggregate impact: rupees moved from intermediaries to the two
    ends, percentage farmer gain, percentage consumer saving, chain length
    before and after.

Everything is deterministic: the same inputs always produce the same plan, which
is what makes the output auditable and the tests meaningful.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from direct.allocation import solve_transportation
from direct.consolidation import LaneItem, ShipmentPlan, cluster_key, plan_shipments
from direct.logistics import FreightConfig, road_distance_km
from direct.surplus import Split, max_surplus_per_farm_qtl, split_surplus
from direct.value_chain import (
    ValueChain,
    calibrate_margin_scale,
    default_direct_chain,
    default_traditional_chain,
)

_EPS = 1e-9

# Viability iteration cap.  Each pass only removes edges, so the sequence of
# lane sets is strictly decreasing and must terminate well within this bound;
# the cap exists so a pathological input cannot spin.
MAX_VIABILITY_PASSES = 6

# Freight-rate fixed-point iteration cap.  See plan_direct_channel step 3.
MAX_FREIGHT_PASSES = 4
# Two passes agree when per-lane planning rates move less than this (₹/quintal).
RATE_CONVERGENCE_RSQTL = 0.50


def planning_rate_per_qtl(
    distance_km: float,
    freight: "FreightConfig",
    expected_load_qtl: Optional[float] = None,
) -> float:
    """Freight rate used when *deciding* whether a lane is worth using.

    This is the chicken-and-egg problem at the heart of consolidation: a single
    quintal moved alone costs a whole truck (₹1800 minimum freight), so pricing
    lanes one quintal at a time makes every lane look hopeless — even though
    pooling ten of them fills the truck and costs ₹21/quintal.

    Two regimes:

    * ``expected_load_qtl is None`` (first pass) — assume the lane participates
      in a full consolidation.  The rate is the FTL rate, floored by the
      per-trip minimum spread over a full vehicle, i.e. the best rate the
      platform could achieve if the truck fills.  Optimistic by design: the
      first pass exists to discover volume.
    * ``expected_load_qtl`` given (later passes) — price the actual pooled load
      through the real rate card, so the plan converges on achievable rates.
    """
    if expected_load_qtl is None:
        optimistic = freight.ftl_rate_per_qtl_km * distance_km
        floor = freight.min_freight_per_trip / freight.vehicle_capacity_qtl
        return max(optimistic, floor)
    from direct.logistics import freight_for_lane

    return freight_for_lane(expected_load_qtl, distance_km, freight).per_qtl


# ─────────────────────────────────────────────────────────────────────────────
# Inputs / config
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SupplyLot:
    """A farmer's (or FPO's) offer, in quintals at the farm gate."""

    id: str
    commodity_id: str
    quantity_qtl: float
    mandi_price_per_qtl: float  # fallback: what the mandi would pay, ₹/quintal
    lat: Optional[float] = None
    lng: Optional[float] = None
    category: str = "vegetable"
    grade: str = "General"
    farmer_id: Optional[str] = None
    market_name: str = ""

    def __post_init__(self) -> None:
        if self.quantity_qtl <= 0:
            raise ValueError(f"lot {self.id}: quantity_qtl must be > 0")
        if self.mandi_price_per_qtl < 0:
            raise ValueError(f"lot {self.id}: mandi_price_per_qtl must be >= 0")


@dataclass(frozen=True)
class DemandNode:
    """A consumer, household group or institution that wants produce."""

    id: str
    commodity_id: str
    quantity_qtl: float  # quintals the consumer wants to *receive*
    retail_price_per_qtl: float  # fallback: what the shop charges, ₹/quintal
    lat: Optional[float] = None
    lng: Optional[float] = None
    category: str = "vegetable"
    kind: str = "household"  # household | rwa | hostel | canteen | hotel | retailer | processor
    label: str = ""
    min_grade: str = "General"

    def __post_init__(self) -> None:
        if self.quantity_qtl <= 0:
            raise ValueError(f"demand {self.id}: quantity_qtl must be > 0")
        if self.retail_price_per_qtl < 0:
            raise ValueError(f"demand {self.id}: retail_price_per_qtl must be >= 0")


@dataclass(frozen=True)
class DirectConfig:
    """Knobs for :func:`plan_direct_channel`.  Every one has a defensible default."""

    alpha: float = 0.5  # Nash bargaining weight on the farmer
    platform_fee_pct: float = 0.03  # only margin in the direct channel
    max_distance_km: float = 250.0  # beyond this, freight eats the pie
    min_allocation_qtl: float = 5.0  # smallest operable lane shipment
    cluster_size_km: float = 25.0  # consolidation grid
    circuity: float = 1.25
    calibrate: bool = True
    freight: FreightConfig = field(default_factory=FreightConfig)
    traditional_chains: Optional[Dict[str, ValueChain]] = None  # by commodity_id
    enforce_grade: bool = False

    def __post_init__(self) -> None:
        if not (0.0 <= self.alpha <= 1.0):
            raise ValueError(f"alpha must be within [0, 1], got {self.alpha}")
        if self.platform_fee_pct < 0:
            raise ValueError("platform_fee_pct must be >= 0")
        if self.max_distance_km < 0:
            raise ValueError("max_distance_km must be >= 0")
        if self.min_allocation_qtl < 0:
            raise ValueError("min_allocation_qtl must be >= 0")
        if self.cluster_size_km <= 0:
            raise ValueError("cluster_size_km must be > 0")
        if self.circuity < 1.0:
            raise ValueError("circuity must be >= 1.0")

    def freight_cfg(self) -> FreightConfig:
        if abs(self.freight.circuity - self.circuity) < 1e-12:
            return self.freight
        return FreightConfig(**{**self.freight.to_dict(), "circuity": self.circuity})

    def traditional_chain_for(self, commodity_id: str, category: str) -> ValueChain:
        if self.traditional_chains and commodity_id in self.traditional_chains:
            return self.traditional_chains[commodity_id]
        return default_traditional_chain(category)


# ─────────────────────────────────────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Allocation:
    """One lane in the finished plan."""

    allocation_id: str
    lot_id: str
    demand_id: str
    farmer_id: Optional[str]
    farm_qtl: float
    delivered_qtl: float
    distance_km: float
    split: Split
    freight_rs: float
    freight_per_qtl: float
    shipment_id: str
    lane_key: str

    # Totals for this lane.
    farmer_gain_rs: float
    consumer_saving_rs: float
    surplus_rs: float

    @property
    def farmer_realisation_rs(self) -> float:
        return self.split.farm_price_per_qtl * self.farm_qtl

    @property
    def mandi_realisation_rs(self) -> float:
        return self.split.farmer_fallback * self.farm_qtl

    @property
    def consumer_payment_rs(self) -> float:
        return self.split.consumer_price_per_delivered_qtl * self.delivered_qtl

    @property
    def retail_payment_rs(self) -> float:
        return self.split.retail_price * self.delivered_qtl

    def to_dict(self) -> dict:
        return {
            "allocation_id": self.allocation_id,
            "lot_id": self.lot_id,
            "demand_id": self.demand_id,
            "farmer_id": self.farmer_id,
            "farm_qtl": round(self.farm_qtl, 4),
            "delivered_qtl": round(self.delivered_qtl, 4),
            "distance_km": round(self.distance_km, 3),
            "shipment_id": self.shipment_id,
            "lane_key": self.lane_key,
            "freight_rs": round(self.freight_rs, 4),
            "freight_per_qtl": round(self.freight_per_qtl, 4),
            "farmer_realisation_rs": round(self.farmer_realisation_rs, 4),
            "mandi_realisation_rs": round(self.mandi_realisation_rs, 4),
            "farmer_gain_rs": round(self.farmer_gain_rs, 4),
            "consumer_payment_rs": round(self.consumer_payment_rs, 4),
            "retail_payment_rs": round(self.retail_payment_rs, 4),
            "consumer_saving_rs": round(self.consumer_saving_rs, 4),
            "surplus_rs": round(self.surplus_rs, 4),
            "split": self.split.to_dict(),
        }


@dataclass(frozen=True)
class ImpactSummary:
    """Aggregate effect of the plan — the numbers the problem statement asks for."""

    lots_engaged: int
    demands_served: int
    farm_qtl_moved: float
    delivered_qtl: float

    farmer_realisation_rs: float
    mandi_realisation_rs: float
    farmer_gain_rs: float
    farmer_gain_pct: float

    consumer_payment_rs: float
    retail_payment_rs: float
    consumer_saving_rs: float
    consumer_saving_pct: float

    surplus_rs: float
    freight_rs: float
    platform_fee_rs: float

    chain_length_before: int
    chain_length_after: int
    intermediaries_displaced: int

    allocation_optimal: bool

    def to_dict(self) -> dict:
        return {
            "lots_engaged": self.lots_engaged,
            "demands_served": self.demands_served,
            "farm_qtl_moved": round(self.farm_qtl_moved, 4),
            "delivered_qtl": round(self.delivered_qtl, 4),
            "farmer_realisation_rs": round(self.farmer_realisation_rs, 2),
            "mandi_realisation_rs": round(self.mandi_realisation_rs, 2),
            "farmer_gain_rs": round(self.farmer_gain_rs, 2),
            "farmer_gain_pct": round(self.farmer_gain_pct, 4),
            "consumer_payment_rs": round(self.consumer_payment_rs, 2),
            "retail_payment_rs": round(self.retail_payment_rs, 2),
            "consumer_saving_rs": round(self.consumer_saving_rs, 2),
            "consumer_saving_pct": round(self.consumer_saving_pct, 4),
            "surplus_rs": round(self.surplus_rs, 2),
            "freight_rs": round(self.freight_rs, 2),
            "platform_fee_rs": round(self.platform_fee_rs, 2),
            "chain_length_before": self.chain_length_before,
            "chain_length_after": self.chain_length_after,
            "intermediaries_displaced": self.intermediaries_displaced,
            "allocation_optimal": self.allocation_optimal,
        }


@dataclass(frozen=True)
class DirectPlan:
    """The full plan: allocations, shipments, impact and the audit trail."""

    plan_id: str
    allocations: Tuple[Allocation, ...]
    shipments: Tuple[ShipmentPlan, ...]
    impact: ImpactSummary
    unserved_lots: Tuple[dict, ...]
    unserved_demands: Tuple[dict, ...]
    calibrations: Dict[str, dict]
    config: dict
    notes: Tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "impact": self.impact.to_dict(),
            "allocations": [a.to_dict() for a in self.allocations],
            "shipments": [
                s.to_dict() for s in self.shipments  # type: ignore[attr-defined]
            ],
            "unserved_lots": list(self.unserved_lots),
            "unserved_demands": list(self.unserved_demands),
            "calibrations": self.calibrations,
            "config": self.config,
            "notes": list(self.notes),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Reference profiles (exported so the API can publish them)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CHAIN_PROFILES: Dict[str, Dict[str, object]] = {
    "vegetable": {
        "category": "vegetable",
        "traditional": default_traditional_chain("vegetable"),
        "direct": default_direct_chain("vegetable"),
    },
    "oilseed": {
        "category": "oilseed",
        "traditional": default_traditional_chain("oilseed"),
        "direct": default_direct_chain("oilseed"),
    },
    "cereal": {
        "category": "cereal",
        "traditional": default_traditional_chain("cereal"),
        "direct": default_direct_chain("cereal"),
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class _Lane:
    lot_idx: int
    demand_idx: int
    distance_km: float
    direct_chain: ValueChain
    w_direct: float
    w_trad: float  # retained for diagnostics (leakage attribution), not for the split
    logistics_per_farm_qtl: float  # T, ₹ per farm quintal (pre-consolidation)
    effective_markup: float
    farmer_fallback: float  # P, ₹ per quintal at the farm gate
    retail_price: float
    mandi_price: float
    value_per_farm_qtl: float  # objective coefficient
    blocked: bool = False


def _distance(cfg: DirectConfig, lot: SupplyLot, demand: DemandNode) -> Optional[float]:
    if lot.lat is None or lot.lng is None or demand.lat is None or demand.lng is None:
        return None
    return road_distance_km(lot.lat, lot.lng, demand.lat, demand.lng, cfg.circuity)


def _grading_allowed(cfg: DirectConfig, lot: SupplyLot, demand: DemandNode) -> bool:
    if not cfg.enforce_grade:
        return True
    order = ["General", "FAQ", "Special"]
    try:
        return order.index(lot.grade) >= order.index(demand.min_grade)
    except ValueError:
        return True


def _build_lanes(
    cfg: DirectConfig,
    lots: Sequence[SupplyLot],
    demands: Sequence[DemandNode],
    calibrated: Dict[str, ValueChain],
    freight: FreightConfig,
    planning_rates: Optional[Dict[Tuple[int, int], float]] = None,
) -> Tuple[List[_Lane], List[str]]:
    """Compute every feasible lane's economics.  Returns (lanes, notes).

    ``planning_rates`` maps ``(lot_idx, demand_idx)`` → ₹/quintal to *assume*
    when sizing the lane.  Lanes without an entry (first pass, or new lanes
    discovered later) are priced optimistically, i.e. as if they will be
    consolidated — see :func:`planning_rate_per_qtl`.
    """
    lanes: List[_Lane] = []
    notes: List[str] = []

    for i, lot in enumerate(lots):
        for j, demand in enumerate(demands):
            if lot.commodity_id != demand.commodity_id:
                continue
            if not _grading_allowed(cfg, lot, demand):
                continue

            dist = _distance(cfg, lot, demand)
            if dist is None:
                continue
            if dist > cfg.max_distance_km:
                continue

            trad_chain = calibrated.get(lot.commodity_id)
            if trad_chain is None:
                trad_chain = cfg.traditional_chain_for(lot.commodity_id, lot.category)

            # Freight for lane sizing.  With no history for this lane we assume
            # it will be consolidated (optimistic); on later passes we use the
            # rate the previous pass actually achieved.
            known = planning_rates.get((i, j)) if planning_rates else None
            freight_per_qtl = (
                float(known)
                if known is not None
                else planning_rate_per_qtl(dist, freight)
            )
            handling = (
                freight.loading_cost_per_qtl
                + freight.packaging_cost_per_qtl
                + freight.last_mile_per_qtl
            )

            direct_chain = default_direct_chain(
                category=lot.category,
                platform_fee_pct=cfg.platform_fee_pct,
                freight_cost_per_qtl=freight_per_qtl + handling,
            )

            w_direct = direct_chain.delivered_ratio
            w_trad = trad_chain.delivered_ratio
            if w_direct <= _EPS or w_trad <= _EPS:
                continue

            # Both freight and handling are incurred on what is LOADED, i.e. per
            # farm-gate quintal, so they add directly.  The chain grosses the
            # total up for in-transit spoilage internally.
            logistics_per_farm_qtl = freight_per_qtl + handling
            farmer_fallback = lot.mandi_price_per_qtl
            m_eff = direct_chain.effective_markup

            # Pie per farm-gate quintal — exactly the unit the min-cost flow
            # supply constraints are written in.
            value_per_farm_qtl = max_surplus_per_farm_qtl(
                retail_price=demand.retail_price_per_qtl,
                delivered_ratio=w_direct,
                logistics_per_farm_qtl=logistics_per_farm_qtl,
                effective_markup=m_eff,
                farmer_fallback=farmer_fallback,
            )

            lanes.append(
                _Lane(
                    lot_idx=i,
                    demand_idx=j,
                    distance_km=dist,
                    direct_chain=direct_chain,
                    w_direct=w_direct,
                    w_trad=w_trad,
                    logistics_per_farm_qtl=logistics_per_farm_qtl,
                    effective_markup=m_eff,
                    farmer_fallback=farmer_fallback,
                    retail_price=demand.retail_price_per_qtl,
                    mandi_price=lot.mandi_price_per_qtl,
                    value_per_farm_qtl=value_per_farm_qtl,
                )
            )

    if not lanes:
        notes.append(
            "No feasible lane: check commodity matching, coordinates and max_distance_km."
        )
    return lanes, notes


def plan_direct_channel(
    lots: Sequence[SupplyLot],
    demands: Sequence[DemandNode],
    cfg: Optional[DirectConfig] = None,
) -> DirectPlan:
    """Plan a direct farm-to-consumer allocation.

    See the module docstring for the seven stages.  The function is pure: no I/O,
    no clock, no randomness beyond the plan id (which is deterministic given the
    inputs — see :func:`_plan_id`).
    """
    cfg = cfg or DirectConfig()
    freight = cfg.freight_cfg()
    notes: List[str] = []
    calibrations: Dict[str, dict] = {}

    if not lots or not demands:
        return DirectPlan(
            plan_id=_plan_id(lots, demands, cfg),
            allocations=(),
            shipments=(),
            impact=ImpactSummary(
                lots_engaged=0,
                demands_served=0,
                farm_qtl_moved=0.0,
                delivered_qtl=0.0,
                farmer_realisation_rs=0.0,
                mandi_realisation_rs=0.0,
                farmer_gain_rs=0.0,
                farmer_gain_pct=0.0,
                consumer_payment_rs=0.0,
                retail_payment_rs=0.0,
                consumer_saving_rs=0.0,
                consumer_saving_pct=0.0,
                surplus_rs=0.0,
                freight_rs=0.0,
                platform_fee_rs=0.0,
                chain_length_before=0,
                chain_length_after=0,
                intermediaries_displaced=0,
                allocation_optimal=True,
            ),
            unserved_lots=tuple({"lot_id": l.id, "reason": "no demand supplied"} for l in lots),
            unserved_demands=tuple({"demand_id": d.id, "reason": "no supply"} for d in demands),
            calibrations={},
            config=_config_snapshot(cfg),
            notes=("Empty input: nothing to plan.",),
        )

    # ── 1. Calibrate one margin scale per commodity ──────────────────────────
    calibrated: Dict[str, ValueChain] = {}
    commodities = {l.commodity_id for l in lots} | {d.commodity_id for d in demands}
    for commodity_id in sorted(commodities):
        cat = next(
            (l.category for l in lots if l.commodity_id == commodity_id),
            next((d.category for d in demands if d.commodity_id == commodity_id), "vegetable"),
        )
        base = cfg.traditional_chain_for(commodity_id, cat)

        # Representative observed pair for the commodity: quantity-weighted
        # average mandi price and average retail price across the markets in play.
        lot_prices = [l.mandi_price_per_qtl for l in lots if l.commodity_id == commodity_id]
        dem_prices = [d.retail_price_per_qtl for d in demands if d.commodity_id == commodity_id]
        if not lot_prices or not dem_prices:
            calibrated[commodity_id] = base
            calibrations[commodity_id] = {
                "status": "skipped",
                "margin_scale": base.margin_scale,
                "note": "commodity present on only one side of the market",
            }
            continue

        mandi_ref = sum(lot_prices) / len(lot_prices)
        retail_ref = sum(dem_prices) / len(dem_prices)

        if cfg.calibrate and mandi_ref > _EPS and retail_ref > _EPS:
            lam, status = calibrate_margin_scale(base, mandi_ref, retail_ref)
            calibrated[commodity_id] = base.scaled(lam)
            calibrations[commodity_id] = {
                "status": status,
                "margin_scale": round(lam, 6),
                "mandi_reference": round(mandi_ref, 2),
                "retail_reference": round(retail_ref, 2),
                "farmer_share_pct": round(
                    calibrated[commodity_id].forward(mandi_ref).farmer_share_pct, 4
                ),
            }
            if status == "glut":
                notes.append(
                    f"{commodity_id}: observed retail price cannot cover the chain's real "
                    "costs — the traditional margin stack is already fully squeezed."
                )
            elif status == "unreachable":
                notes.append(
                    f"{commodity_id}: observed retail price is far above what the reference "
                    "margin structure can explain; profile may need a wider calibration range."
                )
        else:
            calibrated[commodity_id] = base
            calibrations[commodity_id] = {"status": "given", "margin_scale": base.margin_scale}

    # ── 2..6. Rate-fixed-point: build → allocate → consolidate → re-price ───
    #
    # A lane priced in isolation is never viable (one quintal costs a whole
    # truck), but a lane priced as part of a consolidated load usually is.  That
    # circularity is resolved by iterating: plan with the best rate the lane
    # could hope for, see what volume actually shows up, price that volume
    # honestly, and go round again.  Rates only ever improve as volume is
    # discovered, so the sequence of plans is monotone improving and the loop
    # converges in two or three passes; the cap is a safety net.
    # Unit reconciliation.  Supply is naturally counted at the farm gate; demand
    # is naturally counted at the consumer's door.  The flow network needs one
    # unit, so demand capacity is converted into farm-gate quintals by dividing
    # by the direct channel's delivered ratio.  The ratio depends only on the
    # commodity category (the freight stage changes cost, not loss), so this
    # conversion is exact rather than an approximation.
    supply = [float(l.quantity_qtl) for l in lots]
    demand_qty = [_demand_capacity_in_farm_qtl(d, lots, cfg) for d in demands]

    planning_rates: Dict[Tuple[int, int], float] = {}
    best: Optional[Tuple[List[Allocation], Tuple, bool]] = None

    for _pass in range(MAX_FREIGHT_PASSES):
        lanes, lane_notes = _build_lanes(cfg, lots, demands, calibrated, freight, planning_rates)
        if lane_notes and _pass == 0:
            notes.extend(lane_notes)
        if not lanes:
            break

        solution, optimal = _allocate_with_viability(lanes, supply, demand_qty, cfg)
        if not solution.flows:
            if _pass == 0:
                notes.append("Allocation found no profitable lane.")
            break

        lane_index = {(ln.lot_idx, ln.demand_idx): ln for ln in lanes}
        items: List[LaneItem] = []
        for (i, j), farm_qtl in sorted(solution.flows.items()):
            ln = lane_index[(i, j)]
            lot = lots[i]
            demand = demands[j]
            items.append(
                LaneItem(
                    allocation_id=f"A{i}-{j}",
                    lot_id=lot.id,
                    demand_id=demand.id,
                    farm_qtl=farm_qtl,
                    distance_km=ln.distance_km,
                    origin_key=cluster_key(lot.lat, lot.lng, cfg.cluster_size_km),
                    dest_key=cluster_key(demand.lat, demand.lng, cfg.cluster_size_km),
                    origin_lat=lot.lat,
                    origin_lng=lot.lng,
                    dest_lat=demand.lat,
                    dest_lng=demand.lng,
                )
            )

        shipments = plan_shipments(items, freight, cfg.cluster_size_km)
        freight_by_alloc: Dict[str, float] = {}
        for shp in shipments:
            freight_by_alloc.update(shp.freight_by_allocation)

        allocations = _split_allocations(
            items, lane_index, lots, demands, freight_by_alloc, freight, cfg, shipments
        )
        if not allocations:
            if _pass == 0:
                notes.append(
                    "Every allocated lane became unviable once consolidated freight was applied."
                )
            break

        if best is None or _total_surplus(allocations) > _total_surplus(best[0]):
            best = (allocations, tuple(shipments), optimal)

        # Feed realised rates back in and stop when they stop moving.
        realised: Dict[Tuple[int, int], float] = {}
        for item in items:
            i = int(item.allocation_id[1:].split("-")[0])
            j = int(item.allocation_id[1:].split("-")[1])
            if item.farm_qtl > _EPS:
                realised[(i, j)] = freight_by_alloc.get(item.allocation_id, 0.0) / item.farm_qtl

        if _rates_converged(planning_rates, realised):
            break
        planning_rates = realised

    if best is None:
        return _empty_plan(lots, demands, cfg, calibrations, notes)

    allocations, shipments, optimal = best

    # ── 7. Roll up ───────────────────────────────────────────────────────────
    allocated_by_lot: Dict[str, float] = {}
    allocated_by_demand: Dict[str, float] = {}
    for a in allocations:
        allocated_by_lot[a.lot_id] = allocated_by_lot.get(a.lot_id, 0.0) + a.farm_qtl
        allocated_by_demand[a.demand_id] = allocated_by_demand.get(a.demand_id, 0.0) + (
            a.delivered_qtl
        )

    unserved_lots = []
    for lot in lots:
        moved = allocated_by_lot.get(lot.id, 0.0)
        if moved + _EPS < lot.quantity_qtl:
            unserved_lots.append(
                {
                    "lot_id": lot.id,
                    "allocated_qtl": round(moved, 4),
                    "remaining_qtl": round(lot.quantity_qtl - moved, 4),
                    "reason": "no profitable lane cleared the minimum allocation",
                }
            )
    unserved_demands = []
    for demand in demands:
        got = allocated_by_demand.get(demand.id, 0.0)
        if got + _EPS < demand.quantity_qtl:
            unserved_demands.append(
                {
                    "demand_id": demand.id,
                    "served_qtl": round(got, 4),
                    "shortfall_qtl": round(demand.quantity_qtl - got, 4),
                    "reason": "supply exhausted or lane unprofitable",
                }
            )

    sample_lot_id = allocations[0].lot_id
    sample_lot = next(l for l in lots if l.id == sample_lot_id)
    trad_chain = calibrated.get(sample_lot.commodity_id) or cfg.traditional_chain_for(
        sample_lot.commodity_id, sample_lot.category
    )
    dir_chain = default_direct_chain(sample_lot.category, cfg.platform_fee_pct)

    impact = _impact(allocations, trad_chain, dir_chain, optimal)

    return DirectPlan(
        plan_id=_plan_id(lots, demands, cfg),
        allocations=tuple(allocations),
        shipments=shipments,
        impact=impact,
        unserved_lots=tuple(unserved_lots),
        unserved_demands=tuple(unserved_demands),
        calibrations=calibrations,
        config=_config_snapshot(cfg),
        notes=tuple(notes),
    )


def _demand_capacity_in_farm_qtl(
    demand: "DemandNode",
    lots: Sequence["SupplyLot"],
    cfg: "DirectConfig",
) -> float:
    """Convert a consumer's ordered quintals into quintals to load at the farm.

    The consumer asks for ``quantity_qtl`` quintals *on their doorstep*.  To
    deliver that, more has to be loaded, because a small share spoils in
    transit.  Dividing by the direct channel's delivered ratio makes the flow
    network's farm-quintal supply and demand constraints commensurable, so the
    plan actually meets the order instead of falling ~3% short.
    """
    ratios = [
        default_direct_chain(l.category, cfg.platform_fee_pct).delivered_ratio
        for l in lots
        if l.commodity_id == demand.commodity_id
    ]
    w = (sum(ratios) / len(ratios)) if ratios else default_direct_chain(
        demand.category, cfg.platform_fee_pct
    ).delivered_ratio
    if w <= _EPS:
        return float(demand.quantity_qtl)
    return float(demand.quantity_qtl) / w


def _allocate_with_viability(
    lanes: List[_Lane],
    supply: Sequence[float],
    demand_qty: Sequence[float],
    cfg: DirectConfig,
) -> Tuple[object, bool]:
    """Solve the transportation problem, pruning lanes too small to operate.

    A plan that sends 0.4 quintals down a lane is not operable, so after every
    solve the lanes carrying less than ``min_allocation_qtl`` are removed and the
    flow is re-solved.  Each pass strictly shrinks the lane set, so this
    terminates; the cap is a safety net against pathological inputs.
    """
    solution = None
    optimal = True
    for _ in range(MAX_VIABILITY_PASSES):
        active = [ln for ln in lanes if not ln.blocked]
        if not active:
            break
        value = [[0.0] * len(demand_qty) for _ in supply]
        for ln in active:
            value[ln.lot_idx][ln.demand_idx] = ln.value_per_farm_qtl
        solution = solve_transportation(supply, demand_qty, value)
        optimal = solution.optimal

        small = {
            (i, j) for (i, j), f in solution.flows.items() if f < cfg.min_allocation_qtl - _EPS
        }
        if not small:
            break
        for ln in active:
            if (ln.lot_idx, ln.demand_idx) in small:
                ln.blocked = True
    if solution is None:
        from direct.allocation import TransportationSolution

        solution = TransportationSolution({}, 0.0, 0.0, 0, True)
    return solution, optimal


def _split_allocations(
    items: List[LaneItem],
    lane_index: Dict[Tuple[int, int], _Lane],
    lots: Sequence[SupplyLot],
    demands: Sequence[DemandNode],
    freight_by_alloc: Dict[str, float],
    freight: FreightConfig,
    cfg: DirectConfig,
    shipments: Sequence[object],
) -> List[Allocation]:
    """Price every allocated lane with its *consolidated* freight and split the pie."""
    allocations: List[Allocation] = []
    for item in items:
        i = int(item.allocation_id[1:].split("-")[0])
        j = int(item.allocation_id[1:].split("-")[1])
        ln = lane_index[(i, j)]
        lot = lots[i]
        demand = demands[j]

        freight_rs = freight_by_alloc.get(item.allocation_id, 0.0)
        freight_per_farm_qtl = freight_rs / item.farm_qtl if item.farm_qtl > _EPS else 0.0
        handling = (
            freight.loading_cost_per_qtl
            + freight.packaging_cost_per_qtl
            + freight.last_mile_per_qtl
        )

        consolidated_chain = default_direct_chain(
            category=lot.category,
            platform_fee_pct=cfg.platform_fee_pct,
            freight_cost_per_qtl=freight_per_farm_qtl + handling,
        )
        w_direct = consolidated_chain.delivered_ratio
        logistics_per_farm_qtl = freight_per_farm_qtl + handling

        split = split_surplus(
            retail_price=demand.retail_price_per_qtl,
            delivered_ratio=w_direct,
            logistics_per_farm_qtl=logistics_per_farm_qtl,
            effective_markup=consolidated_chain.effective_markup,
            farmer_fallback=ln.farmer_fallback,
            alpha=cfg.alpha,
        )
        if not split.viable:
            continue

        delivered_qtl = item.farm_qtl * w_direct
        shipment_id = ""
        for shp in shipments:
            if item.allocation_id in getattr(shp, "allocation_ids", ()):  # type: ignore[attr-defined]
                shipment_id = shp.shipment_id  # type: ignore[attr-defined]
                break

        allocations.append(
            Allocation(
                allocation_id=item.allocation_id,
                lot_id=lot.id,
                demand_id=demand.id,
                farmer_id=lot.farmer_id,
                farm_qtl=item.farm_qtl,
                delivered_qtl=delivered_qtl,
                distance_km=ln.distance_km,
                split=split,
                freight_rs=freight_rs,
                freight_per_qtl=freight_per_farm_qtl,
                shipment_id=shipment_id,
                lane_key=f"{item.origin_key}>{item.dest_key}",
                farmer_gain_rs=split.farmer_gain_per_farm_qtl * item.farm_qtl,
                consumer_saving_rs=split.consumer_saving_per_farm_qtl * item.farm_qtl,
                surplus_rs=split.total_surplus_per_farm_qtl * item.farm_qtl,
            )
        )
    return allocations


def _total_surplus(allocations: Sequence[Allocation]) -> float:
    return sum(a.surplus_rs for a in allocations)


def _rates_converged(
    previous: Dict[Tuple[int, int], float],
    realised: Dict[Tuple[int, int], float],
) -> bool:
    """True when per-lane planning rates have stopped moving.

    A lane that appeared for the first time in this pass has no history, so by
    definition the rates have not converged and one more pass is warranted.
    """
    if not previous:
        return False
    keys = set(realised)
    if not keys.issubset(set(previous)):
        return False
    return all(abs(previous[k] - realised[k]) <= RATE_CONVERGENCE_RSQTL for k in keys)


def _impact(
    allocations: Sequence[Allocation],
    traditional_chain: ValueChain,
    direct_chain: ValueChain,
    optimal: bool,
) -> ImpactSummary:
    farmer_real = sum(a.farmer_realisation_rs for a in allocations)
    mandi_real = sum(a.mandi_realisation_rs for a in allocations)
    consumer_pay = sum(a.consumer_payment_rs for a in allocations)
    retail_pay = sum(a.retail_payment_rs for a in allocations)
    freight = sum(a.freight_rs for a in allocations)
    platform_fee = sum(a.split.platform_share_rs * a.delivered_qtl for a in allocations)

    return ImpactSummary(
        lots_engaged=len({a.lot_id for a in allocations}),
        demands_served=len({a.demand_id for a in allocations}),
        farm_qtl_moved=sum(a.farm_qtl for a in allocations),
        delivered_qtl=sum(a.delivered_qtl for a in allocations),
        farmer_realisation_rs=farmer_real,
        mandi_realisation_rs=mandi_real,
        farmer_gain_rs=farmer_real - mandi_real,
        farmer_gain_pct=(
            100.0 * (farmer_real / mandi_real - 1.0) if mandi_real > _EPS else 0.0
        ),
        consumer_payment_rs=consumer_pay,
        retail_payment_rs=retail_pay,
        consumer_saving_rs=retail_pay - consumer_pay,
        consumer_saving_pct=(
            100.0 * (1.0 - consumer_pay / retail_pay) if retail_pay > _EPS else 0.0
        ),
        surplus_rs=sum(a.surplus_rs for a in allocations),
        freight_rs=freight,
        platform_fee_rs=platform_fee,
        chain_length_before=len(traditional_chain),
        chain_length_after=len(direct_chain),
        intermediaries_displaced=traditional_chain.intermediary_count,
        allocation_optimal=optimal,
    )


def _empty_plan(
    lots: Sequence[SupplyLot],
    demands: Sequence[DemandNode],
    cfg: DirectConfig,
    calibrations: Dict[str, dict],
    notes: List[str],
) -> DirectPlan:
    return DirectPlan(
        plan_id=_plan_id(lots, demands, cfg),
        allocations=(),
        shipments=(),
        impact=ImpactSummary(
            lots_engaged=0,
            demands_served=0,
            farm_qtl_moved=0.0,
            delivered_qtl=0.0,
            farmer_realisation_rs=0.0,
            mandi_realisation_rs=0.0,
            farmer_gain_rs=0.0,
            farmer_gain_pct=0.0,
            consumer_payment_rs=0.0,
            retail_payment_rs=0.0,
            consumer_saving_rs=0.0,
            consumer_saving_pct=0.0,
            surplus_rs=0.0,
            freight_rs=0.0,
            platform_fee_rs=0.0,
            chain_length_before=0,
            chain_length_after=0,
            intermediaries_displaced=0,
            allocation_optimal=True,
        ),
        unserved_lots=tuple(
            {"lot_id": l.id, "reason": "no profitable lane"} for l in lots
        ),
        unserved_demands=tuple(
            {"demand_id": d.id, "reason": "no profitable lane"} for d in demands
        ),
        calibrations=calibrations,
        config=_config_snapshot(cfg),
        notes=tuple(notes),
    )


def _config_snapshot(cfg: DirectConfig) -> dict:
    return {
        "alpha": cfg.alpha,
        "platform_fee_pct": cfg.platform_fee_pct,
        "max_distance_km": cfg.max_distance_km,
        "min_allocation_qtl": cfg.min_allocation_qtl,
        "cluster_size_km": cfg.cluster_size_km,
        "circuity": cfg.circuity,
        "calibrate": cfg.calibrate,
        "freight": cfg.freight_cfg().to_dict(),
    }


def _plan_id(
    lots: Sequence[SupplyLot],
    demands: Sequence[DemandNode],
    cfg: DirectConfig,
) -> str:
    """Deterministic plan id.

    Same inputs → same id, which makes plans cacheable and makes a demo
    reproducible.  A random suffix is appended only when the caller supplies no
    usable inputs at all, so the "empty plan" case still gets a unique handle.
    """
    digest = hashlib.sha256()
    for lot in lots:
        digest.update(
            f"{lot.id}|{lot.commodity_id}|{lot.quantity_qtl}|{lot.mandi_price_per_qtl}|"
            f"{lot.lat}|{lot.lng}|{lot.grade}".encode()
        )
    for demand in demands:
        digest.update(
            f"{demand.id}|{demand.commodity_id}|{demand.quantity_qtl}|"
            f"{demand.retail_price_per_qtl}|{demand.lat}|{demand.lng}".encode()
        )
    digest.update(
        f"{cfg.alpha}|{cfg.platform_fee_pct}|{cfg.max_distance_km}|"
        f"{cfg.min_allocation_qtl}|{cfg.cluster_size_km}|{cfg.circuity}".encode()
    )
    suffix = "" if (lots and demands) else f"-{uuid.uuid4().hex[:6]}"
    return f"DP-{digest.hexdigest()[:16]}{suffix}"
