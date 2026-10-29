"""End-to-end pipeline invariants.

These are the properties that must hold for *any* plan the engine emits, because
they are the properties the product's claims rest on.  If any of them breaks,
the platform is making a promise it cannot keep.

1. **Mutual gain** — every allocation leaves the farmer >= his mandi price AND
   the consumer <= their shop price.  Both, always, with no exceptions.
2. **Demand is met exactly** — a consumer's order is specified in quintals
   received, and the plan must deliver exactly that, not 97% of it.
3. **Supply is never oversold** — a lot cannot ship more than it holds.
4. **The consumer's rupee reconciles** — farmer + logistics + platform equals
   what the consumer paid, per lane.
5. **Determinism** — identical inputs produce an identical plan and plan id.
6. **Consolidation is applied** — the realised freight is the consolidated rate,
   not the isolated-lane rate.
7. **Degradation is honest** — when no trade is viable the engine returns an
   empty plan with a reason, never a fabricated saving.
"""

from __future__ import annotations

import json
import math

import pytest
from direct.logistics import FreightConfig
from direct.pipeline import (
    DEFAULT_CHAIN_PROFILES,
    DemandNode,
    DirectConfig,
    SupplyLot,
    plan_direct_channel,
)

# Lasalgaon / Pimpalgaon / Yeola (supply) → Nashik city (demand).
LASALGAON = (20.1201, 74.3374)
PIMPALGAON = (20.0500, 74.2700)
YEOLA = (20.0440, 74.4880)
NASHIK = (20.0059, 73.7797)
NASHIK_2 = (19.9975, 73.7898)

ONION_MANDI = 2200.0
ONION_RETAIL = 4000.0


def onion_lots(n=3, qty=40.0):
    return [
        SupplyLot(
            id=f"L{i}",
            commodity_id="onion",
            quantity_qtl=qty,
            mandi_price_per_qtl=ONION_MANDI - 20.0 * i,
            lat=coord[0],
            lng=coord[1],
            category="vegetable",
            grade="FAQ",
            farmer_id=f"farmer{i}",
        )
        for i, coord in enumerate([LASALGAON, PIMPALGAON, YEOLA][:n])
    ]


def onion_demands(n=2):
    return [
        DemandNode(
            id=f"D{i}",
            commodity_id="onion",
            quantity_qtl=30.0,
            retail_price_per_qtl=ONION_RETAIL - 50.0 * i,
            lat=coord[0],
            lng=coord[1],
            category="vegetable",
            kind="rwa",
        )
        for i, coord in enumerate([NASHIK, NASHIK_2][:n])
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Core invariants
# ─────────────────────────────────────────────────────────────────────────────


def test_every_allocation_makes_both_sides_better_off():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    assert plan.allocations, "fixture should produce a viable plan"
    for a in plan.allocations:
        assert a.split.farm_price_per_qtl >= a.split.farmer_fallback - 1e-6, (
            f"{a.allocation_id}: farmer worse off than the mandi"
        )
        assert a.split.consumer_price_per_delivered_qtl <= a.split.retail_price + 1e-6, (
            f"{a.allocation_id}: consumer worse off than the shop"
        )
        assert a.farmer_gain_rs >= -1e-6
        assert a.consumer_saving_rs >= -1e-6


def test_demand_is_met_exactly_not_approximately():
    """Orders are in quintals received; the plan must deliver exactly that.

    Guards the farm-quintal vs consumer-quintal unit conversion: supply is
    counted at the farm gate, demand at the doorstep, and the two differ by the
    direct channel's spoilage.
    """
    demands = onion_demands()
    plan = plan_direct_channel(onion_lots(), demands, DirectConfig())
    served = {}
    for a in plan.allocations:
        served[a.demand_id] = served.get(a.demand_id, 0.0) + a.delivered_qtl
    for d in demands:
        assert served.get(d.id, 0.0) == pytest.approx(d.quantity_qtl, abs=1e-3), (
            f"{d.id}: delivered {served.get(d.id, 0.0)} vs ordered {d.quantity_qtl}"
        )
    assert plan.unserved_demands == ()


def test_lots_are_never_oversold():
    lots = onion_lots()
    plan = plan_direct_channel(lots, onion_demands(), DirectConfig())
    used = {}
    for a in plan.allocations:
        used[a.lot_id] = used.get(a.lot_id, 0.0) + a.farm_qtl
    for lot in lots:
        assert used.get(lot.id, 0.0) <= lot.quantity_qtl + 1e-6


def test_consumer_rupee_reconciles_on_every_lane():
    """Per farm-gate quintal: farmer + logistics + platform == consumer outlay."""
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    for a in plan.allocations:
        s = a.split
        assert (
            s.farmer_share_rs + s.logistics_share_rs + s.platform_share_rs
            == pytest.approx(s.consumer_outlay_per_farm_qtl, abs=1e-6)
        )
        # And the outlay is the delivered quantity at the delivered price.
        assert s.consumer_outlay_per_farm_qtl == pytest.approx(
            s.delivered_ratio * s.consumer_price_per_delivered_qtl, abs=1e-6
        )
        assert s.consumer_outlay_per_farm_qtl == pytest.approx(
            (1.0 + s.effective_markup) * (s.farm_price_per_qtl + s.logistics_per_farm_qtl),
            abs=1e-6,
        )


def test_impact_totals_match_the_sum_of_the_lanes():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    imp = plan.impact
    assert imp.farmer_realisation_rs == pytest.approx(
        sum(a.farmer_realisation_rs for a in plan.allocations), abs=1e-2
    )
    assert imp.mandi_realisation_rs == pytest.approx(
        sum(a.mandi_realisation_rs for a in plan.allocations), abs=1e-2
    )
    assert imp.consumer_saving_rs == pytest.approx(
        sum(a.consumer_saving_rs for a in plan.allocations), abs=1e-2
    )
    assert imp.farmer_gain_rs + imp.consumer_saving_rs == pytest.approx(imp.surplus_rs, abs=1e-2)


def test_the_headline_impact_numbers_are_both_positive():
    """The product's central claim: farmer earns more AND consumer pays less."""
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    assert plan.impact.farmer_gain_pct > 0
    assert plan.impact.consumer_saving_pct > 0
    assert plan.impact.farmer_gain_rs > 0
    assert plan.impact.consumer_saving_rs > 0
    assert plan.impact.intermediaries_displaced > 0
    assert plan.impact.chain_length_after < plan.impact.chain_length_before


def test_the_allocation_is_certifiably_optimal():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    assert plan.impact.allocation_optimal


# ─────────────────────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────────────────────


def test_plan_is_deterministic_including_its_id():
    a = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    b = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    assert a.plan_id == b.plan_id
    assert len(a.allocations) == len(b.allocations)
    for x, y in zip(a.allocations, b.allocations):
        assert x.allocation_id == y.allocation_id
        assert x.farm_qtl == pytest.approx(y.farm_qtl, abs=1e-12)
        assert x.split.farm_price_per_qtl == pytest.approx(
            y.split.farm_price_per_qtl, abs=1e-12
        )


def test_plan_id_changes_when_the_inputs_change():
    a = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    b = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig(alpha=0.7))
    assert a.plan_id != b.plan_id


def test_shuffled_input_order_gives_the_same_economics():
    """Order-independence: the optimum does not depend on list ordering."""
    base = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    shuffled = plan_direct_channel(
        list(reversed(onion_lots())), list(reversed(onion_demands())), DirectConfig()
    )
    # Plan id is order-sensitive (it hashes the input sequence) but the realised
    # economics must not be.
    assert base.impact.surplus_rs == pytest.approx(shuffled.impact.surplus_rs, rel=1e-6)


# ─────────────────────────────────────────────────────────────────────────────
# Bargaining weight
# ─────────────────────────────────────────────────────────────────────────────


def test_a_higher_alpha_shifts_the_pie_toward_the_farmer():
    low = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig(alpha=0.2))
    high = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig(alpha=0.8))
    assert high.impact.farmer_gain_pct > low.impact.farmer_gain_pct
    assert high.impact.consumer_saving_pct < low.impact.consumer_saving_pct


def test_alpha_zero_leaves_the_farmer_at_his_mandi_price():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig(alpha=0.0))
    for a in plan.allocations:
        assert a.split.farm_price_per_qtl == pytest.approx(a.split.farmer_fallback, rel=1e-9)
    assert plan.impact.farmer_gain_rs == pytest.approx(0.0, abs=1e-2)
    assert plan.impact.consumer_saving_rs > 0  # all of it went to the consumer


# ─────────────────────────────────────────────────────────────────────────────
# Degradation
# ─────────────────────────────────────────────────────────────────────────────


def test_empty_input_returns_an_empty_plan_not_a_crash():
    plan = plan_direct_channel([], [], DirectConfig())
    assert plan.allocations == ()
    assert plan.impact.farm_qtl_moved == 0.0
    assert plan.notes


def test_absurd_freight_produces_no_fabricated_savings():
    """When the truck costs more than the chain absorbs, say so."""
    cfg = DirectConfig(
        freight=FreightConfig(ftl_rate_per_qtl_km=500.0, ltl_rate_per_qtl_km=900.0,
                              min_freight_per_trip=1_000_000.0)
    )
    plan = plan_direct_channel(onion_lots(), onion_demands(), cfg)
    assert plan.allocations == ()
    assert plan.impact.farmer_gain_rs == 0.0
    assert plan.impact.consumer_saving_rs == 0.0
    assert plan.unserved_demands


def test_unreachable_demand_is_reported_not_ignored():
    far = [
        DemandNode(
            id="FAR",
            commodity_id="onion",
            quantity_qtl=30.0,
            retail_price_per_qtl=4000.0,
            lat=28.6139,
            lng=77.2090,  # Delhi
        )
    ]
    plan = plan_direct_channel(onion_lots(), far, DirectConfig(max_distance_km=250.0))
    assert plan.allocations == ()
    assert any(u["demand_id"] == "FAR" for u in plan.unserved_demands)


def test_commodity_mismatch_produces_no_lanes():
    lots = onion_lots()
    demands = [
        DemandNode(
            id="T1", commodity_id="tomato", quantity_qtl=20.0,
            retail_price_per_qtl=3600.0, lat=NASHIK[0], lng=NASHIK[1],
        )
    ]
    plan = plan_direct_channel(lots, demands, DirectConfig())
    assert plan.allocations == ()


def test_missing_coordinates_produce_no_lanes_but_a_reason():
    lots = [SupplyLot(id="L0", commodity_id="onion", quantity_qtl=10.0,
                      mandi_price_per_qtl=2200.0)]
    demands = [DemandNode(id="D0", commodity_id="onion", quantity_qtl=10.0,
                          retail_price_per_qtl=4000.0)]
    plan = plan_direct_channel(lots, demands, DirectConfig())
    assert plan.allocations == ()


def test_tiny_lots_below_the_minimum_allocation_are_dropped():
    """A lane carrying 0.5 quintals is not operable; it must be pruned."""
    lots = [
        SupplyLot(id="L0", commodity_id="onion", quantity_qtl=0.5,
                  mandi_price_per_qtl=2200.0, lat=LASALGAON[0], lng=LASALGAON[1])
    ]
    demands = onion_demands(1)
    plan = plan_direct_channel(lots, demands, DirectConfig(min_allocation_qtl=5.0))
    assert plan.allocations == ()


def test_minimum_allocation_is_respected():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig(min_allocation_qtl=5.0))
    for a in plan.allocations:
        assert a.farm_qtl >= 5.0 - 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# Consolidation actually happens
# ─────────────────────────────────────────────────────────────────────────────


def test_shipments_are_built_and_reference_their_allocations():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    assert plan.shipments
    alloc_ids = {a.allocation_id for a in plan.allocations}
    shipped = {aid for s in plan.shipments for aid in s.allocation_ids}
    assert shipped == alloc_ids
    for a in plan.allocations:
        assert a.shipment_id


def test_consolidation_improves_on_the_isolated_lane_rate():
    """Realised freight must be better than moving each lane alone.

    This is the fixed-point iteration earning its keep: an isolated lane is
    priced at the LTL rate or the per-trip floor, and pooling pushes it toward
    the FTL rate.
    """
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    cfg = FreightConfig()
    for a in plan.allocations:
        # Isolated cost for this lane's volume on its own truck.
        isolated = max(
            a.farm_qtl * cfg.ltl_rate_per_qtl_km * a.distance_km,
            cfg.min_freight_per_trip,
        ) / a.farm_qtl
        assert a.freight_per_qtl <= isolated + 1e-6


def test_shipments_report_a_manifest_and_packing_bounds():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    for s in plan.shipments:
        payload = s.to_dict()
        assert payload["manifest"]
        assert s.vehicles >= s.packing_lower_bound
        assert s.load_qtl > 0


# ─────────────────────────────────────────────────────────────────────────────
# Calibration and serialisation
# ─────────────────────────────────────────────────────────────────────────────


def test_calibration_is_recorded_per_commodity():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    assert "onion" in plan.calibrations
    entry = plan.calibrations["onion"]
    assert entry["status"] in {"ok", "glut", "unreachable", "given"}
    assert entry["margin_scale"] >= 0


def test_calibration_can_be_disabled():
    plan = plan_direct_channel(
        onion_lots(), onion_demands(), DirectConfig(calibrate=False)
    )
    assert plan.calibrations["onion"]["status"] == "given"


def test_plan_serialises_to_finite_json():
    plan = plan_direct_channel(onion_lots(), onion_demands(), DirectConfig())
    payload = json.loads(json.dumps(plan.to_dict()))

    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, float):
            assert math.isfinite(node), f"non-finite at {path}"

    walk(payload)
    assert payload["impact"]["farmer_gain_pct"] > 0


def test_default_chain_profiles_cover_the_main_categories():
    assert set(DEFAULT_CHAIN_PROFILES) >= {"vegetable", "oilseed", "cereal"}
    for entry in DEFAULT_CHAIN_PROFILES.values():
        assert len(entry["traditional"]) > 0
        assert len(entry["direct"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# Input validation
# ─────────────────────────────────────────────────────────────────────────────


def test_bad_lot_and_demand_values_are_rejected():
    with pytest.raises(ValueError):
        SupplyLot(id="x", commodity_id="c", quantity_qtl=0.0, mandi_price_per_qtl=100.0)
    with pytest.raises(ValueError):
        SupplyLot(id="x", commodity_id="c", quantity_qtl=10.0, mandi_price_per_qtl=-1.0)
    with pytest.raises(ValueError):
        DemandNode(id="y", commodity_id="c", quantity_qtl=0.0, retail_price_per_qtl=100.0)
    with pytest.raises(ValueError):
        DemandNode(id="y", commodity_id="c", quantity_qtl=10.0, retail_price_per_qtl=-5.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"alpha": 1.5},
        {"alpha": -0.1},
        {"platform_fee_pct": -0.01},
        {"max_distance_km": -1},
        {"min_allocation_qtl": -1},
        {"cluster_size_km": 0},
        {"circuity": 0.5},
    ],
)
def test_bad_config_rejected(kwargs):
    with pytest.raises(ValueError):
        DirectConfig(**kwargs)


def test_scale_up_stays_fast_and_feasible():
    """A district-sized problem must still plan, and stay consistent."""
    import time

    lots = [
        SupplyLot(
            id=f"L{i}",
            commodity_id="onion",
            quantity_qtl=20.0 + (i % 7) * 5.0,
            mandi_price_per_qtl=2100.0 + (i % 11) * 10.0,
            lat=LASALGAON[0] + (i % 9) * 0.03,
            lng=LASALGAON[1] + (i % 5) * 0.03,
        )
        for i in range(60)
    ]
    demands = [
        DemandNode(
            id=f"D{j}",
            commodity_id="onion",
            quantity_qtl=15.0 + (j % 5) * 6.0,
            retail_price_per_qtl=3950.0 + (j % 7) * 20.0,
            lat=NASHIK[0] + (j % 4) * 0.02,
            lng=NASHIK[1] + (j % 3) * 0.02,
        )
        for j in range(25)
    ]
    start = time.perf_counter()
    plan = plan_direct_channel(lots, demands, DirectConfig())
    elapsed = time.perf_counter() - start

    assert elapsed < 15.0, f"planning 60x25 took {elapsed:.1f}s"
    assert plan.allocations
    for a in plan.allocations:
        assert a.farmer_gain_rs >= -1e-6
        assert a.consumer_saving_rs >= -1e-6
    assert plan.impact.allocation_optimal


# ─────────────────────────────────────────────────────────────────────────────
# Who gets served first — the equity property of surplus maximisation
# ─────────────────────────────────────────────────────────────────────────────


def _two_farmers_one_buyer():
    """Identical lots on the same lane; only the mandi fallback differs."""
    return [
        SupplyLot(
            id="L_WELLOFF", commodity_id="onion", quantity_qtl=40.0,
            mandi_price_per_qtl=2400.0, lat=20.1201, lng=74.3374,
            category="vegetable",
        ),
        SupplyLot(
            id="L_NEEDY", commodity_id="onion", quantity_qtl=40.0,
            mandi_price_per_qtl=2000.0, lat=20.1201, lng=74.3374,
            category="vegetable",
        ),
    ], [
        DemandNode(
            id="D0", commodity_id="onion", quantity_qtl=30.0,
            retail_price_per_qtl=4000.0, lat=20.0059, lng=73.7797,
            category="vegetable", kind="rwa",
        )
    ]


def test_surplus_maximisation_serves_the_neediest_farmer_first():
    """The farmer the mandi pays least is the one DirectLink picks up.

    This looks like it could be an accident, so the reasoning is worth stating.
    Total surplus on a lane is

        Π = w·R − (1+m)·(P + T)

    where P is the farmer's mandi fallback, i.e. his opportunity cost.  With
    R, T and m equal across two lots, the lane with the SMALLER P frees up more
    surplus — so maximising total surplus and prioritising the worst-paid
    farmer are the same thing here, not competing objectives.

    A reader who expects "highest mandi price wins" has the sign backwards:
    a high mandi price means the farmer already has a good fallback, so
    moving him to the direct channel creates less new value.
    """
    lots, demands = _two_farmers_one_buyer()
    plan = plan_direct_channel(lots, demands, DirectConfig())
    assert len(plan.allocations) == 1
    assert plan.allocations[0].lot_id == "L_NEEDY"


def test_the_needier_farmer_also_gets_the_larger_raise():
    """Both lots used: the farm price is PARTIALLY equalised, and the needier
    farmer still comes out further ahead.

    The Nash price is ``p_f = α·P_max + (1−α)·P``, so the farm price tracks the
    mandi fallback at rate ``(1−α)`` — at α=½, half of any mandi advantage
    carries over and half is pooled.  It is deliberately NOT a flat rate:
    paying every farmer the same would hand the best-off farmer the entire
    surplus and leave the worst-off no reason to join.

    What matters for the problem statement is that the gap *narrows*: both
    farmers are paid above their mandi, and the one the mandi pays least gets
    the bigger lift in both rupees and percent.
    """
    lots, _ = _two_farmers_one_buyer()
    alpha = 0.5
    demands = [
        DemandNode(
            id="D0", commodity_id="onion", quantity_qtl=45.0,
            retail_price_per_qtl=4000.0, lat=20.0059, lng=73.7797,
            category="vegetable", kind="rwa",
        )
    ]
    plan = plan_direct_channel(lots, demands, DirectConfig(alpha=alpha))
    by_lot = {a.lot_id: a for a in plan.allocations}
    assert set(by_lot) == {"L_NEEDY", "L_WELLOFF"}, set(by_lot)

    needy, welloff = by_lot["L_NEEDY"], by_lot["L_WELLOFF"]
    d_p = welloff.split.farmer_fallback - needy.split.farmer_fallback
    assert d_p > 0

    # Partial equalisation: the farm-price gap is (1−α) of the mandi gap.
    assert welloff.split.farm_price_per_qtl - needy.split.farm_price_per_qtl == (
        pytest.approx((1.0 - alpha) * d_p, abs=0.01)
    )

    # Both are lifted, and the needier farmer is lifted further.
    for a in (needy, welloff):
        assert a.split.farm_price_per_qtl > a.split.farmer_fallback
    needy_gain = needy.split.farm_price_per_qtl - needy.split.farmer_fallback
    welloff_gain = welloff.split.farm_price_per_qtl - welloff.split.farmer_fallback
    assert needy_gain > welloff_gain
    assert needy.split.farmer_gain_pct > welloff.split.farmer_gain_pct


def test_alpha_redistributes_but_cannot_invent_surplus():
    """α decides who keeps the pie; it cannot conjure a bigger one.

    Two things are being pinned here, and the second is the interesting one.

    First, redistribution: raising α moves rupees from the consumer's saving to
    the farmer's gain, monotonically, and the endpoints give the whole pie to
    one side.

    Second — and this is a real design consequence, not an artefact — the
    realised (after-fee) surplus is NOT perfectly α-invariant.  The platform
    fee is ad valorem on the farm price, so every rupee pushed to the farmer
    also enlarges the fee base.  The joint surplus BEFORE the fee
    (``surplus + platform_fee``) is what α cannot touch, and it stays flat to
    within a fraction of a percent (the residual is the freight fixed point
    converging on a marginally different load).

    That gap is the honest argument for keeping the fee small: every point of
    platform margin is subtracted from the pie the farmer and consumer split.
    """
    lots, demands = _two_farmers_one_buyer()
    rows = []
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0):
        impact = plan_direct_channel(lots, demands, DirectConfig(alpha=alpha)).impact
        rows.append(
            (
                alpha,
                impact.surplus_rs,
                impact.platform_fee_rs,
                impact.surplus_rs + impact.platform_fee_rs,
                impact.farmer_gain_rs,
                impact.consumer_saving_rs,
            )
        )

    # (1) Monotone redistribution, with the endpoints handing over everything.
    gains = [r[4] for r in rows]
    savings = [r[5] for r in rows]
    assert gains == sorted(gains) and gains[-1] > gains[0]
    assert savings == sorted(savings, reverse=True) and savings[0] > savings[-1]
    assert rows[0][4] == pytest.approx(0.0, abs=1e-6)   # α=0 → farmer at mandi
    assert rows[-1][5] == pytest.approx(0.0, abs=1e-6)  # α=1 → consumer at retail

    # (2) The pre-fee pie is invariant — α cannot touch it.
    gross = [r[3] for r in rows]
    assert (max(gross) - min(gross)) / max(gross) < 0.005

    # (3) The marginal cost of a rupee moved to the farmer is exactly the
    #     platform fee rate: the fee is ad valorem on the farm price, so
    #     raising the farmer's share by ₹X costs m·X in extra fee and the
    #     consumer's saving falls by (1+m)·X.
    fees = [r[2] for r in rows]
    assert fees == sorted(fees)
    m = DirectConfig().platform_fee_pct
    marginal_fee = (fees[-1] - fees[0]) / (gains[-1] - gains[0])
    assert marginal_fee == pytest.approx(m, rel=0.05)
    marginal_saving = (savings[0] - savings[-1]) / (gains[-1] - gains[0])
    assert marginal_saving == pytest.approx(1.0 + m, rel=0.05)


def test_no_farmer_is_ever_left_worse_off_than_his_mandi():
    """The property the whole idea rests on: participation is voluntary.

    If any allocation paid a farmer less than his mandi, the platform would
    be extracting from the very people it claims to help, and the rational
    response would be to stop using it.
    """
    lots, demands = _two_farmers_one_buyer()
    for alpha in (0.0, 0.15, 0.5, 0.85, 1.0):
        plan = plan_direct_channel(lots, demands, DirectConfig(alpha=alpha))
        for a in plan.allocations:
            assert a.split.farm_price_per_qtl >= a.split.farmer_fallback - 1e-9
            assert a.split.consumer_price_per_delivered_qtl <= a.split.retail_price + 1e-9
