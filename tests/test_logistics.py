"""Distance and freight economics.

The freight model is where an over-optimistic implementation quietly promises
savings it cannot deliver, so these tests pin down the parts that a demo would
otherwise be tempted to fake: the minimum-freight floor, the FTL/LTL threshold,
and the fact that consolidation genuinely lowers the per-quintal rate.
"""

from __future__ import annotations

import math

import pytest
from direct.logistics import (
    FreightConfig,
    freight_for_lane,
    haversine_km,
    lane_handling_per_qtl,
    road_distance_km,
    with_capacity,
)

# ─────────────────────────────────────────────────────────────────────────────
# Distance
# ─────────────────────────────────────────────────────────────────────────────


def test_haversine_zero_for_identical_points():
    assert haversine_km(20.0, 74.0, 20.0, 74.0) == pytest.approx(0.0, abs=1e-6)


def test_haversine_matches_a_known_great_circle_distance():
    """Lasalgaon (Nashik district) → Mumbai.

    Great-circle is ~192 km. Sanity-checked against a manual spherical
    computation: Δlat 1.044° ≈ 116 km, Δlng 1.460° at 19.6°N ≈ 153 km, so
    sqrt(116² + 153²) ≈ 192 km.
    """
    d = haversine_km(20.1201, 74.3374, 19.0760, 72.8777)
    assert 185.0 < d < 200.0


def test_haversine_one_degree_of_latitude_is_about_111_km():
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, abs=0.5)


def test_haversine_is_symmetric():
    a = haversine_km(20.1201, 74.3374, 19.9975, 73.7898)
    b = haversine_km(19.9975, 73.7898, 20.1201, 74.3374)
    assert a == pytest.approx(b, abs=1e-6)


def test_haversine_returns_none_for_missing_or_bad_coordinates():
    assert haversine_km(None, 74.0, 20.0, 74.0) is None
    assert haversine_km(20.0, None, 20.0, 74.0) is None
    assert haversine_km(20.0, 74.0, None, 74.0) is None
    assert haversine_km(20.0, 74.0, 20.0, None) is None
    # Non-numeric must degrade to None, not raise — a bad row should not 500.
    assert haversine_km("abc", 74.0, 20.0, 74.0) is None


def test_road_distance_applies_circuity():
    straight = haversine_km(20.1201, 74.3374, 19.9975, 73.7898)
    assert road_distance_km(20.1201, 74.3374, 19.9975, 73.7898, 1.25) == pytest.approx(
        straight * 1.25, abs=1e-2
    )
    assert road_distance_km(20.1201, 74.3374, 19.9975, 73.7898, 1.0) == pytest.approx(
        straight, abs=1e-6
    )


def test_road_distance_is_never_shorter_than_great_circle():
    for circ in (1.0, 1.15, 1.25, 1.6):
        assert road_distance_km(20.1, 74.3, 19.9, 73.7, circ) >= haversine_km(
            20.1, 74.3, 19.9, 73.7
        )


def test_circuity_below_one_rejected():
    with pytest.raises(ValueError):
        road_distance_km(20.1, 74.3, 19.9, 73.7, 0.5)


# ─────────────────────────────────────────────────────────────────────────────
# Freight
# ─────────────────────────────────────────────────────────────────────────────


def test_zero_load_costs_nothing_but_still_carries_handling():
    q = freight_for_lane(0.0, 100.0, FreightConfig())
    assert q.freight == 0.0
    assert q.vehicles == 0
    assert q.total_per_qtl == pytest.approx(lane_handling_per_qtl(FreightConfig()))


def test_minimum_freight_floor_dominates_a_tiny_load():
    """A 2-quintal order cannot cost ₹35 — the truck moves or it does not."""
    cfg = FreightConfig()
    q = freight_for_lane(2.0, 60.0, cfg)
    assert q.freight == pytest.approx(cfg.min_freight_per_trip)
    assert q.per_qtl == pytest.approx(cfg.min_freight_per_trip / 2.0)


def test_a_full_truck_earns_the_ftl_rate():
    cfg = FreightConfig()
    q = freight_for_lane(cfg.vehicle_capacity_qtl, 100.0, cfg)
    assert q.rate_basis == "FTL"
    assert q.vehicles == 1
    assert q.fill_pct == pytest.approx(100.0)
    assert q.freight == pytest.approx(cfg.vehicle_capacity_qtl * cfg.ftl_rate_per_qtl_km * 100.0)


def test_a_half_full_truck_is_charged_the_ltl_rate():
    cfg = FreightConfig()
    q = freight_for_lane(cfg.vehicle_capacity_qtl * 0.5, 100.0, cfg)
    assert q.rate_basis == "LTL"
    assert q.fill_pct == pytest.approx(50.0)


def test_consolidation_lowers_the_per_quintal_rate():
    """The economic reason this whole platform exists."""
    cfg = FreightConfig()
    small = freight_for_lane(cfg.vehicle_capacity_qtl * 0.4, 100.0, cfg)
    full = freight_for_lane(cfg.vehicle_capacity_qtl, 100.0, cfg)
    assert full.per_qtl < small.per_qtl
    assert full.rate_basis == "FTL" and small.rate_basis == "LTL"


def test_vehicle_count_rounds_up_and_loads_are_balanced():
    cfg = FreightConfig()
    q = freight_for_lane(cfg.vehicle_capacity_qtl * 2.5, 100.0, cfg)
    assert q.vehicles == 3
    # Balanced across three vehicles → 83.33% fill, just under the FTL threshold.
    assert q.fill_pct == pytest.approx(100.0 * 2.5 / 3.0, abs=1e-3)


def test_exactly_two_truckloads_is_two_vehicles_at_full_rate():
    cfg = FreightConfig()
    q = freight_for_lane(cfg.vehicle_capacity_qtl * 2.0, 100.0, cfg)
    assert q.vehicles == 2
    assert q.rate_basis == "FTL"


def test_freight_grows_with_distance():
    cfg = FreightConfig()
    near = freight_for_lane(80.0, 30.0, cfg)
    far = freight_for_lane(80.0, 120.0, cfg)
    assert far.freight > near.freight


def test_per_quintal_freight_falls_as_the_load_grows():
    """Economies of scale: total freight need NOT rise with volume.

    A 40-quintal part-load is charged the LTL rate (₹0.62/qtl-km) while an
    80-quintal load clears the FTL threshold (₹0.28/qtl-km), so the bigger
    shipment costs LESS in total (₹2240 vs ₹2480 here) and much less per
    quintal. Any assertion of the form "more load → more freight" would be
    wrong, and tests that assume it encode a misunderstanding of how freight
    is actually priced.
    """
    cfg = FreightConfig()
    less = freight_for_lane(40.0, 100.0, cfg)
    more = freight_for_lane(80.0, 100.0, cfg)
    assert less.rate_basis == "LTL"
    assert more.rate_basis == "FTL"
    assert more.per_qtl < less.per_qtl
    assert more.freight < less.freight


def test_zero_distance_still_costs_the_trip_floor():
    cfg = FreightConfig()
    q = freight_for_lane(10.0, 0.0, cfg)
    assert q.freight == pytest.approx(cfg.min_freight_per_trip)


def test_negative_inputs_rejected():
    cfg = FreightConfig()
    with pytest.raises(ValueError):
        freight_for_lane(-1.0, 10.0, cfg)
    with pytest.raises(ValueError):
        freight_for_lane(10.0, -1.0, cfg)


def test_freight_quote_serialises_to_finite_numbers():
    import json

    q = freight_for_lane(120.0, 74.5, FreightConfig())
    payload = json.loads(json.dumps(q.to_dict()))
    assert payload["vehicles"] == 2
    assert all(math.isfinite(v) for v in payload.values() if isinstance(v, (int, float)))


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────


def test_config_rejects_nonsense():
    for kwargs in (
        {"vehicle_capacity_qtl": 0.0},
        {"ftl_rate_per_qtl_km": -1.0},
        {"ltl_rate_per_qtl_km": 0.1},  # below the FTL rate
        {"ftl_fill_threshold": 0.0},
        {"ftl_fill_threshold": 1.5},
        {"min_freight_per_trip": -1.0},
        {"circuity": 0.5},
    ):
        with pytest.raises(ValueError):
            FreightConfig(**kwargs)


def test_config_round_trips_through_dict():
    cfg = FreightConfig(vehicle_capacity_qtl=75.0, circuity=1.4)
    assert FreightConfig.from_dict(cfg.to_dict()) == cfg
    assert FreightConfig.from_dict(None) == FreightConfig()
    # Partial payloads fill the rest from defaults.
    assert FreightConfig.from_dict({"circuity": 1.9}).circuity == 1.9
    assert FreightConfig.from_dict({"bogus": 1}).vehicle_capacity_qtl == 90.0


def test_with_capacity_changes_only_the_vehicle_size():
    cfg = FreightConfig()
    small = with_capacity(cfg, 40.0)
    assert small.vehicle_capacity_qtl == 40.0
    assert small.ftl_rate_per_qtl_km == cfg.ftl_rate_per_qtl_km
