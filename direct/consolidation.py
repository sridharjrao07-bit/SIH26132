"""Consolidation: turning many small flows into full truckloads.

Why this is the make-or-break module
------------------------------------
Freight in India is priced per *trip*, not per kilogram — a truck that leaves
half empty costs almost as much as a full one.  So a single household ordering
30 kg of onion pays, in effect, for a whole vehicle.  Direct farm-to-consumer
trade is therefore only viable when many small demands are pooled.  That pooling
is a bin-packing problem, and it is the reason the platform can quote a price
below retail at all.

Two things get consolidated:

* **Supply side** — several farmers' lots travelling the same lane share a truck
  (:func:`plan_shipments`).
* **Demand side** — several consumers' orders pool into a group buy that reaches
  the minimum viable load (:func:`evaluate_group_buy`).

Algorithm
---------
Both use **First Fit Decreasing (FFD)**: sort items by size descending, then put
each into the first bin that still has room, opening a new bin when none does.

FFD is used because it is simple, deterministic, fast (``O(n log n)``) and has a
known worst-case guarantee::

    FFD(I) <= (11/9)·OPT(I) + 6/9

so it never uses more than about 22% more vehicles than an optimal packing.  The
exact optimum would need branch-and-bound, which is not worth the latency for a
planning call, and the guarantee is tight enough to plan against.  ``plan_lane``
also computes the trivial lower bound ``ceil(total / capacity)`` so callers can
see how much headroom the heuristic left.

Freight allocation
------------------
Once a vehicle's freight is known it is split across the items it carries
**proportionally to quintals**.  That is the only rule that satisfies the two
properties people actually check: it exactly recovers the vehicle cost (no
subsidy, no surplus), and two identical orders are charged identically.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from direct.logistics import FreightConfig, FreightQuote, freight_for_lane, lane_handling_per_qtl

_EPS = 1e-9

_KM_PER_DEG_LAT = 111.32


def cluster_key(lat: Optional[float], lng: Optional[float], size_km: float) -> str:
    """Snap a coordinate to a grid cell of roughly ``size_km``.

    Consolidation only makes sense between points that are genuinely near each
    other; bucketing coordinates into cells is the cheapest way to define
    "near" without a spatial index, and it is stable (the same coordinate always
    lands in the same cell) which keeps plans reproducible.

    Longitude degrees shrink with latitude, so the cell width is divided by
    ``cos(lat)`` to keep cells roughly square in kilometres.
    """
    if lat is None or lng is None or size_km <= 0:
        return "unknown"
    try:
        la, ln = float(lat), float(lng)
    except (TypeError, ValueError):
        return "unknown"
    lat_step = size_km / _KM_PER_DEG_LAT
    cos_lat = max(0.15, abs(math.cos(math.radians(la))))
    lng_step = size_km / (_KM_PER_DEG_LAT * cos_lat)
    return f"{math.floor(la / lat_step)}:{math.floor(ln / lng_step)}"


# ─────────────────────────────────────────────────────────────────────────────
# Bin packing
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Bin:
    """One vehicle's load."""

    index: int
    capacity: float
    items: Tuple[int, ...]  # indices into the input sequence
    load: float

    @property
    def fill_pct(self) -> float:
        return 100.0 * self.load / self.capacity if self.capacity > 0 else 0.0

    @property
    def headroom(self) -> float:
        return max(0.0, self.capacity - self.load)


@dataclass(frozen=True)
class PackingResult:
    bins: Tuple[Bin, ...]
    lower_bound: int  # ceil(total / capacity) — the information-theoretic floor

    @property
    def vehicles(self) -> int:
        return len(self.bins)

    @property
    def load(self) -> float:
        return sum(b.load for b in self.bins)

    @property
    def average_fill_pct(self) -> float:
        if not self.bins:
            return 0.0
        return sum(b.fill_pct for b in self.bins) / len(self.bins)

    @property
    def worst_case_optimal(self) -> float:
        """The FFD guarantee: ``FFD <= 11/9·OPT + 6/9`` rearranged for OPT.

        i.e. given what FFD used, the true optimum is at least
        ``(9·FFD - 6) / 11``.  Reported so a plan can state how much of its
        vehicle count is heuristic slack.
        """
        return max(0.0, (9.0 * len(self.bins) - 6.0) / 11.0)


def pack_lane(sizes: Sequence[float], capacity: float) -> PackingResult:
    """First-Fit-Decreasing bin packing.

    Parameters
    ----------
    sizes
        Item sizes (quintals).  Zero and negative sizes are ignored.
    capacity
        Vehicle payload, quintals.  Items larger than the capacity are placed
        alone in a dedicated bin (and overflow it) rather than being dropped —
        a 120-quintal lot must still be planned even if it needs two trucks.

    Returns
    -------
    PackingResult
        Guaranteed to cover every positive item exactly once.
    """
    if capacity <= 0:
        raise ValueError(f"capacity must be > 0, got {capacity}")

    indexed = sorted(
        ((float(s), i) for i, s in enumerate(sizes) if float(s) > _EPS),
        key=lambda t: (-t[0], t[1]),  # descending size, ties by original order
    )
    total = sum(s for s, _ in indexed)
    lower_bound = int(math.ceil(total / capacity - 1e-9)) if total > 0 else 0

    bins: List[List[Tuple[float, int]]] = []
    remaining: List[float] = []

    for size, idx in indexed:
        placed = False
        for b_i, bin_items in enumerate(bins):
            if remaining[b_i] >= size - 1e-9:
                bin_items.append((size, idx))
                remaining[b_i] -= size
                placed = True
                break
        if not placed:
            bins.append([(size, idx)])
            remaining.append(capacity - size)

    return PackingResult(
        bins=tuple(
            Bin(
                index=i,
                capacity=capacity,
                items=tuple(idx for _, idx in items),
                load=sum(s for s, _ in items),
            )
            for i, items in enumerate(bins)
        ),
        lower_bound=lower_bound,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Shipment planning (supply side)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LaneItem:
    """One (lot → demand) flow that has to be moved."""

    allocation_id: str
    lot_id: str
    demand_id: str
    farm_qtl: float
    distance_km: float
    origin_key: str
    dest_key: str
    origin_lat: Optional[float] = None
    origin_lng: Optional[float] = None
    dest_lat: Optional[float] = None
    dest_lng: Optional[float] = None


@dataclass(frozen=True)
class ShipmentPlan:
    """One lane's set of vehicles after consolidation.

    ``bins`` is the FFD packing — the actual loading manifest, i.e. which
    allocations ride in which vehicle.  ``vehicles``/``fill_pct`` come from the
    freight quote, which prices the lane as an evenly-balanced fleet (what a
    dispatcher aims for, and the cheapest feasible way to move the load).  Both
    are reported: the manifest is operationally useful, the quote is what gets
    charged.
    """

    shipment_id: str
    lane_key: str  # "origin_cluster>dest_cluster"
    distance_km: float
    load_qtl: float
    vehicles: int
    capacity_qtl: float
    fill_pct: float
    quote: FreightQuote
    allocation_ids: Tuple[str, ...]
    load_by_allocation: Dict[str, float]
    freight_by_allocation: Dict[str, float]
    bins: Tuple[Bin, ...] = ()
    packing_lower_bound: int = 0

    @property
    def packing_slack(self) -> int:
        """Extra vehicles FFD used over the trivial lower bound (heuristic slack)."""
        return max(0, len(self.bins) - self.packing_lower_bound)

    def to_dict(self) -> dict:
        return {
            "shipment_id": self.shipment_id,
            "lane_key": self.lane_key,
            "distance_km": round(self.distance_km, 3),
            "load_qtl": round(self.load_qtl, 4),
            "vehicles": self.vehicles,
            "capacity_qtl": round(self.capacity_qtl, 4),
            "fill_pct": round(self.fill_pct, 4),
            "freight": self.quote.to_dict(),
            "allocation_ids": list(self.allocation_ids),
            "load_by_allocation": {k: round(v, 4) for k, v in self.load_by_allocation.items()},
            "freight_by_allocation": {
                k: round(v, 4) for k, v in self.freight_by_allocation.items()
            },
            "manifest": [
                {
                    "vehicle": b.index + 1,
                    "load_qtl": round(b.load, 4),
                    "fill_pct": round(b.fill_pct, 2),
                    "allocation_ids": [self.allocation_ids[k] for k in b.items],
                }
                for b in self.bins
            ],
            "packing_lower_bound": self.packing_lower_bound,
            "packing_slack": self.packing_slack,
        }


def _lane_distance(items: Sequence[LaneItem]) -> float:
    """Representative lane distance: the longest leg in the consolidated lane.

    Using the max rather than the mean is deliberate — the truck has to reach the
    furthest drop on the lane, so charging the average would under-price the
    lane and the plan would promise savings it cannot deliver.
    """
    return max((float(i.distance_km) for i in items), default=0.0)


def plan_shipments(
    items: Sequence[LaneItem],
    cfg: FreightConfig,
    cluster_size_km: float = 25.0,
    prefix: str = "SHP",
) -> List[ShipmentPlan]:
    """Group flows into lanes by geography and pack each lane into vehicles.

    Parameters
    ----------
    items
        Allocated flows to be moved.
    cfg
        Freight rate card.
    cluster_size_km
        Grid resolution used to decide which origins/destinations are "together".
        25 km is roughly one collection round in a Nashik taluka.

    Returns
    -------
    list of :class:`ShipmentPlan`, one per lane, in deterministic order.
    """
    lanes: Dict[str, List[LaneItem]] = defaultdict(list)
    for item in items:
        if item.farm_qtl <= _EPS:
            continue
        key = f"{item.origin_key or 'o'}>{item.dest_key or 'd'}"
        lanes[key].append(item)

    plans: List[ShipmentPlan] = []
    for lane_key in sorted(lanes):
        lane_items = lanes[lane_key]
        distance = _lane_distance(lane_items)
        packing = pack_lane([i.farm_qtl for i in lane_items], cfg.vehicle_capacity_qtl)
        load = sum(i.farm_qtl for i in lane_items)
        quote = freight_for_lane(load, distance, cfg)

        load_by_alloc = {i.allocation_id: float(i.farm_qtl) for i in lane_items}
        freight_by_alloc = allocate_freight(quote.freight, load_by_alloc)

        plans.append(
            ShipmentPlan(
                shipment_id=f"{prefix}-{lane_key}",
                lane_key=lane_key,
                distance_km=distance,
                load_qtl=load,
                vehicles=quote.vehicles,
                capacity_qtl=cfg.vehicle_capacity_qtl,
                fill_pct=quote.fill_pct,
                quote=quote,
                allocation_ids=tuple(i.allocation_id for i in lane_items),
                load_by_allocation=load_by_alloc,
                freight_by_allocation=freight_by_alloc,
                bins=packing.bins,
                packing_lower_bound=packing.lower_bound,
            )
        )
    return plans


def allocate_freight(total_freight: float, load_by_key: Dict[str, float]) -> Dict[str, float]:
    """Split a freight bill across the items that caused it, by quintals.

    Two invariants, both asserted in the tests:

    * **Exact recovery** — the shares sum to the bill to within a rupee-cent.
      The platform neither subsidises nor profits from freight.
    * **Symmetry** — equal loads pay equal amounts.
    """
    total_load = sum(max(0.0, v) for v in load_by_key.values())
    if total_load <= _EPS or abs(total_freight) <= _EPS:
        return {k: 0.0 for k in load_by_key}
    return {
        k: total_freight * (max(0.0, v) / total_load) if v > 0 else 0.0
        for k, v in load_by_key.items()
    }


# ─────────────────────────────────────────────────────────────────────────────
# Group buying (demand side)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GroupOrder:
    """One consumer's committed quantity inside a group buy."""

    order_id: str
    qtl: float
    lat: Optional[float] = None
    lng: Optional[float] = None
    label: str = ""


@dataclass(frozen=True)
class GroupBuyResult:
    """Feasibility and costing of pooling a set of consumer orders."""

    total_qtl: float
    vehicles: int
    capacity_qtl: float
    fill_pct: float
    distance_km: float
    freight_total: float
    handling_total: float
    freight_per_qtl: float
    handling_per_qtl: float
    landed_cost_per_qtl: float  # freight + handling, before the produce price
    freight_by_order: Dict[str, float]
    min_load_qtl: float
    shortfall_qtl: float  # quintals still needed to reach min_load_qtl
    viable: bool
    packing_lower_bound: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "total_qtl": round(self.total_qtl, 4),
            "vehicles": self.vehicles,
            "capacity_qtl": round(self.capacity_qtl, 4),
            "fill_pct": round(self.fill_pct, 4),
            "distance_km": round(self.distance_km, 3),
            "freight_total": round(self.freight_total, 4),
            "handling_total": round(self.handling_total, 4),
            "freight_per_qtl": round(self.freight_per_qtl, 4),
            "handling_per_qtl": round(self.handling_per_qtl, 4),
            "landed_cost_per_qtl": round(self.landed_cost_per_qtl, 4),
            "min_load_qtl": round(self.min_load_qtl, 4),
            "shortfall_qtl": round(self.shortfall_qtl, 4),
            "viable": self.viable,
            "packing_lower_bound": self.packing_lower_bound,
            "reason": self.reason,
            "freight_by_order": {k: round(v, 4) for k, v in self.freight_by_order.items()},
        }


def evaluate_group_buy(
    orders: Sequence[GroupOrder],
    cfg: FreightConfig,
    distance_km: float,
    min_load_qtl: float = 0.0,
    cluster_size_km: float = 8.0,
) -> GroupBuyResult:
    """Pool consumer orders into truckloads and price the pooled freight.

    This is the demand-side counterpart of :func:`plan_shipments`.  It answers
    the question a consumer group actually asks: *"if we order together, does the
    truck fill up enough for direct delivery to beat the shop?"*

    Parameters
    ----------
    orders
        Committed orders.  Orders are packed per destination cluster so that a
        group spanning two neighbourhoods does not pretend to share one truck.
    cfg
        Freight rate card.
    distance_km
        Farm-collection → group drop distance.
    min_load_qtl
        Minimum load for the group buy to be released.  ``0`` disables the check.
    cluster_size_km
        Destination clustering resolution (a few km for a neighbourhood, tens of
        km for a district).

    Returns
    -------
    GroupBuyResult
        Always returns a costing; ``viable`` says whether the pool clears the
        minimum load, and ``shortfall_qtl`` says how much more is needed.
    """
    if distance_km < 0:
        raise ValueError(f"distance_km must be >= 0, got {distance_km}")
    if min_load_qtl < 0:
        raise ValueError(f"min_load_qtl must be >= 0, got {min_load_qtl}")

    total = sum(max(0.0, float(o.qtl)) for o in orders)
    handling = lane_handling_per_qtl(cfg)
    freight_by_order: Dict[str, float] = {o.order_id: 0.0 for o in orders}

    if total <= _EPS:
        return GroupBuyResult(
            total_qtl=0.0,
            vehicles=0,
            capacity_qtl=cfg.vehicle_capacity_qtl,
            fill_pct=0.0,
            distance_km=distance_km,
            freight_total=0.0,
            handling_total=0.0,
            freight_per_qtl=0.0,
            handling_per_qtl=handling,
            landed_cost_per_qtl=handling,
            freight_by_order=freight_by_order,
            min_load_qtl=min_load_qtl,
            shortfall_qtl=max(0.0, min_load_qtl),
            viable=min_load_qtl <= _EPS,
            packing_lower_bound=0,
            reason="No committed quantity yet.",
        )

    # Pack per destination cluster: a group spread across distant neighbourhoods
    # genuinely needs more than one drop, and pretending otherwise would
    # understate freight.
    clusters: Dict[str, List[GroupOrder]] = defaultdict(list)
    for o in orders:
        if float(o.qtl) <= _EPS:
            continue
        clusters[cluster_key(o.lat, o.lng, cluster_size_km)].append(o)

    freight_total = 0.0
    vehicles_total = 0
    lower_bound_total = 0
    weighted_fill = 0.0

    for cell in sorted(clusters):
        cell_orders = clusters[cell]
        cell_qtl = sum(max(0.0, float(o.qtl)) for o in cell_orders)
        packing = pack_lane([o.qtl for o in cell_orders], cfg.vehicle_capacity_qtl)
        quote = freight_for_lane(cell_qtl, distance_km, cfg)
        freight_total += quote.freight
        vehicles_total += max(1, quote.vehicles) if cell_qtl > 0 else 0
        lower_bound_total += packing.lower_bound
        weighted_fill += quote.fill_pct * cell_qtl
        for alloc_id, amount in allocate_freight(
            quote.freight, {o.order_id: float(o.qtl) for o in cell_orders}
        ).items():
            freight_by_order[alloc_id] = freight_by_order.get(alloc_id, 0.0) + amount

    fill_pct = weighted_fill / total if total > _EPS else 0.0
    handling_total = handling * total
    shortfall = max(0.0, min_load_qtl - total)
    viable = shortfall <= _EPS
    if viable and min_load_qtl > _EPS:
        reason = (
            f"Pool of {total:.1f} qtl clears the {min_load_qtl:.1f} qtl minimum in "
            f"{vehicles_total} vehicle(s)."
        )
    elif viable:
        reason = f"Pool of {total:.1f} qtl packed into {vehicles_total} vehicle(s)."
    else:
        reason = (
            f"Pool of {total:.1f} qtl is {shortfall:.1f} qtl short of the "
            f"{min_load_qtl:.1f} qtl minimum; recruit more members or join the next window."
        )

    return GroupBuyResult(
        total_qtl=total,
        vehicles=vehicles_total,
        capacity_qtl=cfg.vehicle_capacity_qtl,
        fill_pct=fill_pct,
        distance_km=distance_km,
        freight_total=freight_total,
        handling_total=handling_total,
        freight_per_qtl=freight_total / total,
        handling_per_qtl=handling,
        landed_cost_per_qtl=freight_total / total + handling,
        freight_by_order=freight_by_order,
        min_load_qtl=min_load_qtl,
        shortfall_qtl=shortfall,
        viable=viable,
        packing_lower_bound=lower_bound_total,
        reason=reason,
    )
