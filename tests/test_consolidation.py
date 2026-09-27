"""Consolidation: bin packing, lane building, freight allocation, group buys.

Freight is priced per trip, so pooling orders is the only thing that makes small
direct deliveries viable.  These tests cover both the packing itself (against the
known FFD bound and against an exhaustive optimum on small instances) and the
fairness of how the resulting bill is shared out.
"""

from __future__ import annotations

import itertools
import random

import pytest
from direct.consolidation import (
    GroupOrder,
    LaneItem,
    allocate_freight,
    cluster_key,
    evaluate_group_buy,
    pack_lane,
    plan_shipments,
)
from direct.logistics import FreightConfig, lane_handling_per_qtl

CFG = FreightConfig()


# ─────────────────────────────────────────────────────────────────────────────
# Bin packing
# ─────────────────────────────────────────────────────────────────────────────


def exhaustive_min_bins(sizes, capacity):
    """Optimal bin count by brute force (assign each item to one of n bins).

    Only usable for very small instances — enough to validate FFD's output.
    """
    sizes = [s for s in sizes if s > 0]
    if not sizes:
        return 0
    for n_bins in range(1, len(sizes) + 1):
        for assignment in itertools.product(range(n_bins), repeat=len(sizes)):
            loads = [0.0] * n_bins
            for size, b in zip(sizes, assignment):
                loads[b] += size
            if all(load <= capacity + 1e-9 for load in loads):
                return n_bins
    return len(sizes)


def test_pack_lane_covers_every_item_exactly_once():
    sizes = [10.0, 25.0, 30.0, 5.0, 60.0, 12.0]
    result = pack_lane(sizes, 50.0)
    packed = sorted(i for b in result.bins for i in b.items)
    assert packed == sorted(range(len(sizes)))


def test_pack_lane_never_exceeds_capacity_except_for_oversized_items():
    sizes = [10.0, 25.0, 30.0, 5.0, 60.0, 12.0]
    result = pack_lane(sizes, 50.0)
    for b in result.bins:
        # A single item larger than the vehicle is unavoidable; everything else
        # is packed within capacity.
        if len(b.items) > 1:
            assert b.load <= 50.0 + 1e-9


def test_pack_lane_places_an_oversized_item_alone():
    result = pack_lane([120.0, 10.0, 10.0], 90.0)
    assert result.vehicles == 2
    oversized = [b for b in result.bins if len(b.items) == 1 and b.load == 120.0]
    assert len(oversized) == 1


@pytest.mark.parametrize("seed", list(range(25)))
def test_ffd_never_exceeds_its_worst_case_bound(seed):
    """FFD(I) <= 11/9 · OPT(I) + 6/9 — the classical guarantee."""
    rng = random.Random(seed)
    capacity = 90.0
    sizes = [rng.uniform(1, 60) for _ in range(rng.randint(1, 9))]
    result = pack_lane(sizes, capacity)
    opt = exhaustive_min_bins(sizes, capacity)
    assert len(result.bins) <= (11 / 9) * opt + 6 / 9 + 1e-9


@pytest.mark.parametrize("seed", list(range(25)))
def test_ffd_matches_the_optimum_on_small_random_instances(seed):
    """In practice FFD is optimal far more often than its bound suggests."""
    rng = random.Random(seed)
    capacity = 90.0
    sizes = [rng.uniform(1, 60) for _ in range(rng.randint(1, 7))]
    result = pack_lane(sizes, capacity)
    opt = exhaustive_min_bins(sizes, capacity)
    assert len(result.bins) >= opt  # never better than optimal
    assert len(result.bins) <= opt + 1  # and at most one vehicle worse


def test_ffd_is_at_least_the_trivial_lower_bound():
    sizes = [80.0, 80.0, 80.0]
    result = pack_lane(sizes, 90.0)
    assert result.vehicles == 3
    assert result.lower_bound == 3
    assert result.vehicles >= result.lower_bound


def test_ffd_beats_the_trivial_bound_on_fragmented_loads():
    """Three 30-quintal lots fit in one 90-quintal truck."""
    result = pack_lane([30.0, 30.0, 30.0], 90.0)
    assert result.vehicles == 1
    assert result.lower_bound == 1


def test_packing_result_reports_heuristic_slack():
    result = pack_lane([70.0, 70.0, 30.0, 30.0], 90.0)
    assert result.worst_case_optimal <= result.vehicles
    assert result.average_fill_pct > 0


def test_empty_and_zero_items_produce_no_bins():
    assert pack_lane([], 90.0).vehicles == 0
    assert pack_lane([0.0, 0.0], 90.0).vehicles == 0
    assert pack_lane([-5.0], 90.0).vehicles == 0


def test_pack_lane_rejects_non_positive_capacity():
    with pytest.raises(ValueError):
        pack_lane([10.0], 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Clustering
# ─────────────────────────────────────────────────────────────────────────────


def test_cluster_key_is_stable_and_local():
    a = cluster_key(20.1201, 74.3374, 25.0)
    b = cluster_key(20.1201, 74.3374, 25.0)
    assert a == b
    # 5 km away is the same 25 km cell; 500 km away is not.
    assert cluster_key(20.16, 74.36, 25.0) == a
    assert cluster_key(24.0, 78.0, 25.0) != a


def test_cluster_key_handles_missing_coordinates():
    assert cluster_key(None, 74.0, 25.0) == "unknown"
    assert cluster_key(20.0, None, 25.0) == "unknown"
    assert cluster_key(20.0, 74.0, 0.0) == "unknown"
    assert cluster_key("bad", 74.0, 25.0) == "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Freight allocation
# ─────────────────────────────────────────────────────────────────────────────


def test_freight_allocation_recovers_the_bill_exactly():
    """No subsidy and no skim: the shares must sum to the freight charged."""
    loads = {"a": 30.0, "b": 45.0, "c": 15.0}
    shares = allocate_freight(2400.0, loads)
    assert sum(shares.values()) == pytest.approx(2400.0, abs=1e-6)


def test_freight_allocation_is_proportional_and_symmetric():
    loads = {"a": 10.0, "b": 10.0, "c": 20.0}
    shares = allocate_freight(4000.0, loads)
    assert shares["a"] == pytest.approx(shares["b"], abs=1e-9)
    assert shares["c"] == pytest.approx(2 * shares["a"], abs=1e-9)


def test_freight_allocation_handles_zero_loads_and_zero_bills():
    shares = allocate_freight(1000.0, {"a": 0.0, "b": 0.0})
    assert all(v == 0.0 for v in shares.values())
    shares = allocate_freight(0.0, {"a": 10.0})
    assert shares["a"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Shipment planning
# ─────────────────────────────────────────────────────────────────────────────


def _item(alloc, lot, dem, qtl, dist, okey="o", dkey="d"):
    return LaneItem(
        allocation_id=alloc,
        lot_id=lot,
        demand_id=dem,
        farm_qtl=qtl,
        distance_km=dist,
        origin_key=okey,
        dest_key=dkey,
    )


def test_plan_shipments_groups_by_lane_and_prices_each():
    items = [
        _item("a1", "L1", "D1", 40.0, 70.0, "o1", "d1"),
        _item("a2", "L2", "D1", 30.0, 75.0, "o1", "d1"),
        _item("a3", "L3", "D2", 20.0, 200.0, "o2", "d2"),
    ]
    plans = plan_shipments(items, CFG)
    assert len(plans) == 2
    by_lane = {p.lane_key: p for p in plans}
    assert by_lane["o1>d1"].load_qtl == pytest.approx(70.0)
    assert by_lane["o2>d2"].load_qtl == pytest.approx(20.0)


def test_plan_shipments_uses_the_longest_leg_on_a_lane():
    """Charging the average distance would under-price the furthest drop."""
    items = [
        _item("a1", "L1", "D1", 10.0, 50.0, "o1", "d1"),
        _item("a2", "L2", "D1", 10.0, 150.0, "o1", "d1"),
    ]
    plan = plan_shipments(items, CFG)[0]
    assert plan.distance_km == pytest.approx(150.0)


def test_plan_shipments_freight_shares_sum_to_the_lane_total():
    items = [
        _item("a1", "L1", "D1", 40.0, 70.0, "o1", "d1"),
        _item("a2", "L2", "D1", 30.0, 75.0, "o1", "d1"),
    ]
    plan = plan_shipments(items, CFG)[0]
    assert sum(plan.freight_by_allocation.values()) == pytest.approx(plan.quote.freight, abs=1e-6)


def test_plan_shipments_skips_zero_quantity_flows():
    items = [_item("a1", "L1", "D1", 0.0, 70.0, "o1", "d1")]
    assert plan_shipments(items, CFG) == []


def test_plan_shipments_is_deterministic_in_lane_order():
    items = [
        _item("a1", "L1", "D1", 40.0, 70.0, "o2", "d1"),
        _item("a2", "L2", "D1", 30.0, 75.0, "o1", "d1"),
    ]
    first = [p.shipment_id for p in plan_shipments(items, CFG)]
    second = [p.shipment_id for p in plan_shipments(list(reversed(items)), CFG)]
    assert first == second


def test_shipment_manifest_lists_which_allocations_ride_together():
    items = [
        _item("a1", "L1", "D1", 40.0, 70.0, "o1", "d1"),
        _item("a2", "L2", "D1", 30.0, 70.0, "o1", "d1"),
    ]
    plan = plan_shipments(items, CFG)[0]
    payload = plan.to_dict()
    assert payload["manifest"]
    # Both allocations fit in one 90-quintal truck, so one vehicle, two entries.
    assert sum(len(v["allocation_ids"]) for v in payload["manifest"]) == 2


def test_consolidating_a_lane_reduces_the_per_quintal_rate():
    """Two half-empty lanes consolidated into one full truck cost less each."""
    separate = plan_shipments(
        [
            _item("a1", "L1", "D1", 45.0, 70.0, "o1", "d1"),
            _item("a2", "L2", "D2", 45.0, 70.0, "o2", "d2"),
        ],
        CFG,
    )
    together = plan_shipments(
        [
            _item("a1", "L1", "D1", 45.0, 70.0, "o1", "d1"),
            _item("a2", "L2", "D1", 45.0, 70.0, "o1", "d1"),
        ],
        CFG,
    )
    separate_rate = sum(p.quote.freight for p in separate) / 90.0
    together_rate = sum(p.quote.freight for p in together) / 90.0
    assert together_rate < separate_rate
    assert together[0].quote.rate_basis == "FTL"


# ─────────────────────────────────────────────────────────────────────────────
# Group buying
# ─────────────────────────────────────────────────────────────────────────────


def test_group_buy_viable_when_the_pool_clears_the_minimum():
    orders = [GroupOrder(order_id=f"o{i}", qtl=20.0, lat=20.0, lng=74.0) for i in range(5)]
    res = evaluate_group_buy(orders, CFG, distance_km=70.0, min_load_qtl=90.0)
    assert res.total_qtl == pytest.approx(100.0)
    assert res.viable
    assert res.shortfall_qtl == 0.0
    assert res.vehicles == 2  # 100 qtl into 90-qtl trucks


def test_group_buy_reports_the_shortfall_when_below_minimum():
    orders = [GroupOrder(order_id="o1", qtl=10.0, lat=20.0, lng=74.0)]
    res = evaluate_group_buy(orders, CFG, distance_km=70.0, min_load_qtl=90.0)
    assert not res.viable
    assert res.shortfall_qtl == pytest.approx(80.0)
    assert "short" in res.reason.lower()


def test_group_buy_freight_shares_sum_to_the_total():
    orders = [
        GroupOrder(order_id="o1", qtl=30.0, lat=20.0, lng=74.0),
        GroupOrder(order_id="o2", qtl=25.0, lat=20.01, lng=74.01),
        GroupOrder(order_id="o3", qtl=45.0, lat=20.02, lng=74.02),
    ]
    res = evaluate_group_buy(orders, CFG, distance_km=70.0)
    assert sum(res.freight_by_order.values()) == pytest.approx(res.freight_total, abs=1e-6)


def test_group_buy_per_quintal_cost_falls_as_the_pool_grows():
    """The whole point: more members, cheaper logistics per quintal."""
    small = evaluate_group_buy(
        [GroupOrder(order_id="o1", qtl=10.0, lat=20.0, lng=74.0)], CFG, distance_km=70.0
    )
    large = evaluate_group_buy(
        [GroupOrder(order_id=f"o{i}", qtl=10.0, lat=20.0, lng=74.0) for i in range(9)],
        CFG,
        distance_km=70.0,
    )
    assert large.freight_per_qtl < small.freight_per_qtl
    assert large.landed_cost_per_qtl < small.landed_cost_per_qtl


def test_group_buy_empty_pool_is_handled():
    res = evaluate_group_buy([], CFG, distance_km=70.0, min_load_qtl=50.0)
    assert res.total_qtl == 0.0
    assert not res.viable
    assert res.shortfall_qtl == pytest.approx(50.0)


def test_group_buy_zero_minimum_is_always_viable_with_quantity():
    res = evaluate_group_buy(
        [GroupOrder(order_id="o1", qtl=1.0, lat=20.0, lng=74.0)], CFG, distance_km=70.0
    )
    assert res.viable


def test_group_buy_distant_members_need_more_vehicles_than_nearby_ones():
    near = evaluate_group_buy(
        [GroupOrder(order_id=f"o{i}", qtl=45.0, lat=20.0 + 0.001 * i, lng=74.0) for i in range(2)],
        CFG,
        distance_km=70.0,
        cluster_size_km=8.0,
    )
    far = evaluate_group_buy(
        [GroupOrder(order_id=f"o{i}", qtl=45.0, lat=20.0 + 1.0 * i, lng=74.0) for i in range(2)],
        CFG,
        distance_km=70.0,
        cluster_size_km=8.0,
    )
    assert near.vehicles <= far.vehicles


def test_group_buy_rejects_negative_inputs():
    with pytest.raises(ValueError):
        evaluate_group_buy([], CFG, distance_km=-1.0)
    with pytest.raises(ValueError):
        evaluate_group_buy([], CFG, distance_km=10.0, min_load_qtl=-5.0)


def test_group_buy_result_serialises_to_finite_numbers():
    import json
    import math

    res = evaluate_group_buy(
        [GroupOrder(order_id=f"o{i}", qtl=20.0, lat=20.0, lng=74.0) for i in range(4)],
        CFG,
        distance_km=70.0,
        min_load_qtl=50.0,
    )
    payload = json.loads(json.dumps(res.to_dict()))
    for key, value in payload.items():
        if isinstance(value, float):
            assert math.isfinite(value), key


def test_handling_is_charged_once_per_quintal_and_is_freight_independent():
    res = evaluate_group_buy(
        [GroupOrder(order_id="o1", qtl=10.0, lat=20.0, lng=74.0)], CFG, distance_km=0.0
    )
    assert res.handling_per_qtl == pytest.approx(lane_handling_per_qtl(CFG))
    assert res.handling_total == pytest.approx(lane_handling_per_qtl(CFG) * 10.0)
    # At zero distance the only freight is the per-trip floor.
    assert res.freight_total == pytest.approx(CFG.min_freight_per_trip)
