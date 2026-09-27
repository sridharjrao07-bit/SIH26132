"""Value-chain model: affine composition, exact attribution, invertible inverse.

The claims under test are the ones the rest of the engine is built on:

1. A stage is the affine map ``p_out = A·p_in + B`` and the chain composes to one.
2. ``forward`` then ``inverse`` round-trips exactly.
3. Stage takes sum to the total absorption **exactly** (no residual, no fudge).
4. Each stage's take splits exactly into real handling cost + margin.
5. The forward map is strictly increasing in the margin scale, which is what
   makes bisection calibration legitimate.
6. The pass-through derivative ``1/A`` matches a finite-difference measurement.
"""

from __future__ import annotations

import math

import pytest
from direct.value_chain import (
    CALIBRATION_GLUT,
    CALIBRATION_OK,
    CALIBRATION_UNREACHABLE,
    IDENTITY_CHAIN,
    Stage,
    ValueChain,
    calibrate_margin_scale,
    default_direct_chain,
    default_traditional_chain,
)

# ─────────────────────────────────────────────────────────────────────────────
# Stage validation
# ─────────────────────────────────────────────────────────────────────────────


def test_stage_scalars_match_the_affine_definition():
    st = Stage(key="s", label_en="s", margin_pct=0.10, cost_per_qtl=50.0, loss_pct=0.20)
    # A = (1 + m) / (1 - l);  B = (1 + m) * c
    assert st.A == pytest.approx(1.10 / 0.80)
    assert st.B == pytest.approx(1.10 * 50.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"margin_pct": -0.1},
        {"cost_per_qtl": -1.0},
        {"loss_pct": -0.01},
        {"loss_pct": 1.0},  # 100% loss is degenerate — must be rejected
        {"loss_pct": 0.99},  # over the MAX_LOSS_PCT guard
        {"key": ""},
    ],
)
def test_stage_rejects_nonsense(kwargs):
    with pytest.raises(ValueError):
        Stage(key=kwargs.pop("key", "s"), label_en="s", **kwargs)


def test_stage_scaled_only_touches_margin():
    st = Stage(key="s", label_en="s", margin_pct=0.10, cost_per_qtl=50.0, loss_pct=0.20)
    half = st.scaled(0.5)
    assert half.margin_pct == pytest.approx(0.05)
    # Physical losses and handling costs are real resource use, not rent.
    assert half.cost_per_qtl == st.cost_per_qtl
    assert half.loss_pct == st.loss_pct


def test_duplicate_stage_keys_rejected():
    st = Stage(key="dup", label_en="d")
    with pytest.raises(ValueError, match="duplicate stage key"):
        ValueChain([st, st])


# ─────────────────────────────────────────────────────────────────────────────
# Composition
# ─────────────────────────────────────────────────────────────────────────────


def test_two_stage_composition_is_the_expected_affine_map():
    s1 = Stage(key="a", label_en="a", margin_pct=0.10, cost_per_qtl=10.0, loss_pct=0.10)
    s2 = Stage(key="b", label_en="b", margin_pct=0.20, cost_per_qtl=20.0, loss_pct=0.00)
    chain = ValueChain([s1, s2])

    # By hand: p1 = A1*p0 + B1; p2 = A2*p1 + B2 = A2*A1*p0 + A2*B1 + B2
    expected_A = s1.A * s2.A
    expected_B = s2.A * s1.B + s2.B

    assert chain.A == pytest.approx(expected_A)
    assert chain.B == pytest.approx(expected_B)

    p0 = 137.0
    assert chain.forward(p0).retail_price == pytest.approx(expected_A * p0 + expected_B)


def test_identity_chain_is_the_identity():
    assert IDENTITY_CHAIN.A == pytest.approx(1.0)
    assert IDENTITY_CHAIN.B == pytest.approx(0.0)
    res = IDENTITY_CHAIN.forward(1234.0)
    assert res.retail_price == pytest.approx(1234.0)
    assert res.absorption == pytest.approx(0.0)
    assert res.farmer_share_pct == pytest.approx(100.0)
    assert IDENTITY_CHAIN.delivered_ratio == pytest.approx(1.0)


def test_delivered_ratio_is_the_product_of_survival_fractions():
    stages = [
        Stage(key="a", label_en="a", loss_pct=0.10),
        Stage(key="b", label_en="b", loss_pct=0.20),
        Stage(key="c", label_en="c", loss_pct=0.00),
    ]
    assert ValueChain(stages).delivered_ratio == pytest.approx(0.9 * 0.8 * 1.0)


def test_effective_markup_is_zero_when_there_are_no_margins():
    """Losses and costs alone must not create a markup.

    This is the property the whole surplus algebra leans on: with no rent in the
    direct channel, every rupee above the farmer's revenue is a real cost.
    """
    chain = ValueChain(
        [
            Stage(key="pack", label_en="pack", cost_per_qtl=30.0, loss_pct=0.02),
            Stage(key="move", label_en="move", cost_per_qtl=90.0, loss_pct=0.02),
        ]
    )
    assert chain.effective_markup == pytest.approx(0.0, abs=1e-12)


def test_effective_markup_equals_the_platform_fee_for_a_fee_only_chain():
    chain = default_direct_chain("vegetable", platform_fee_pct=0.04, freight_cost_per_qtl=77.0)
    assert chain.effective_markup == pytest.approx(0.04, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Invertibility
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("farm_price", [0.0, 1.0, 500.0, 2200.0, 99999.0])
def test_forward_then_inverse_round_trips(farm_price):
    chain = default_traditional_chain("vegetable")
    retail = chain.forward(farm_price).retail_price
    assert chain.inverse(retail) == pytest.approx(farm_price, rel=1e-9, abs=1e-6)


def test_inverse_returns_negative_in_a_glut_rather_than_lying():
    """Retail below the chain's real cost is a signal, not a numerical error."""
    chain = default_traditional_chain("vegetable").scaled(0.0)  # zero margins
    floor_retail = chain.forward(0.0).retail_price
    price, status = chain.implied_farm_price(floor_retail - 500.0)
    assert status == "glut"
    assert price == 0.0
    assert chain.inverse(floor_retail - 500.0) < 0


def test_forward_rejects_negative_or_non_finite_prices():
    chain = default_traditional_chain("vegetable")
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            chain.forward(bad)


# ─────────────────────────────────────────────────────────────────────────────
# Exact attribution
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("category", ["vegetable", "oilseed", "cereal"])
def test_stage_takes_sum_exactly_to_total_absorption(category):
    chain = default_traditional_chain(category)
    res = chain.forward(2200.0)
    total_take = sum(s.take for s in res.stages)
    assert total_take == pytest.approx(res.absorption, rel=1e-9, abs=1e-6)


@pytest.mark.parametrize("category", ["vegetable", "oilseed", "cereal"])
def test_margin_and_cost_takes_split_each_stage_exactly(category):
    chain = default_traditional_chain(category)
    res = chain.forward(2200.0)
    for s in res.stages:
        assert s.cost_take + s.margin_take == pytest.approx(s.take, rel=1e-9, abs=1e-9)
    assert sum(s.margin_take for s in res.stages) == pytest.approx(res.margin_absorption, abs=1e-6)
    assert sum(s.cost_take for s in res.stages) == pytest.approx(res.cost_absorption, abs=1e-6)
    assert res.margin_absorption + res.cost_absorption == pytest.approx(res.absorption, abs=1e-6)


def test_quantity_is_conserved_through_the_chain():
    """qty_out(i) must equal qty_in(i+1) — no produce is invented or lost twice."""
    res = default_traditional_chain("vegetable").forward(2200.0)
    stages = res.stages
    for a, b in zip(stages, stages[1:]):
        assert a.qty_out == pytest.approx(b.qty_in, rel=1e-12)
    assert stages[0].qty_in == pytest.approx(1.0)
    assert stages[-1].qty_out == pytest.approx(res.delivered_ratio)


def test_value_is_carried_not_created_by_loss():
    """Spoilage concentrates value, it does not create it."""
    st = Stage(key="rot", label_en="rot", loss_pct=0.50)
    res = ValueChain([st]).forward(1000.0)
    # 1 quintal worth ₹1000 becomes 0.5 quintal worth ₹1000 → ₹2000/quintal.
    assert res.stages[0].value_out == pytest.approx(1000.0)
    assert res.stages[0].price_out == pytest.approx(2000.0)
    assert res.stages[0].take == pytest.approx(0.0)
    assert res.stages[0].spoilage_qtl == pytest.approx(0.5)


def test_farmer_share_and_price_ratio_are_related_by_the_delivered_ratio():
    res = default_traditional_chain("vegetable").forward(2200.0)
    # farmer_share is quantity-adjusted; price_ratio is the naive per-kg figure.
    assert res.price_ratio_pct == pytest.approx(100.0 * 2200.0 / res.retail_price)
    assert res.farmer_share_pct == pytest.approx(res.price_ratio_pct / res.delivered_ratio)


def test_pass_through_matches_a_finite_difference():
    chain = default_traditional_chain("vegetable")
    farm = 2200.0
    base = chain.forward(farm).retail_price
    bumped = chain.forward(farm + 1.0).retail_price
    measured = 1.0 / (bumped - base)  # d farm / d retail
    assert measured == pytest.approx(chain.pass_through, rel=1e-6)
    assert chain.pass_through == pytest.approx(1.0 / chain.A)


def test_pass_through_is_below_one_for_a_multi_stage_chain():
    # The headline complaint: a ₹1 rise at retail does not reach the farmer.
    assert default_traditional_chain("vegetable").pass_through < 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Essential-only reduction
# ─────────────────────────────────────────────────────────────────────────────


def test_essential_only_removes_every_rent_layer():
    chain = default_traditional_chain("vegetable")
    direct = chain.essential_only()
    assert direct.intermediary_count == 0
    assert len(direct) <= len(chain)
    # Nothing in the reference traditional chain is essential: it is all
    # trade layers. The direct channel is built separately by
    # default_direct_chain, which is why this reduction is a no-op here — the
    # assertion that matters is that no rent survives.
    assert all(s.essential for s in direct.stages)


def test_platform_fee_is_the_only_margin_in_the_direct_chain():
    direct = default_direct_chain("vegetable", platform_fee_pct=0.03, freight_cost_per_qtl=100.0)
    margins = [s for s in direct.stages if s.margin_pct > 0]
    assert len(margins) == 1
    assert margins[0].key == "platform_fee"
    assert direct.effective_markup == pytest.approx(0.03, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Calibration
# ─────────────────────────────────────────────────────────────────────────────


def test_calibration_reproduces_the_observed_pair():
    chain = default_traditional_chain("vegetable")
    farm, retail = 2200.0, 4000.0
    lam, status = calibrate_margin_scale(chain, farm, retail)
    assert status == CALIBRATION_OK
    assert chain.scaled(lam).forward(farm).retail_price == pytest.approx(retail, abs=1e-4)


@pytest.mark.parametrize(
    "farm,retail",
    [(2200.0, 4000.0), (1900.0, 3600.0), (4500.0, 6200.0), (2150.0, 3100.0)],
)
def test_calibration_round_trips_over_a_plausible_price_range(farm, retail):
    for category in ("vegetable", "oilseed", "cereal"):
        chain = default_traditional_chain(category)
        lam, status = calibrate_margin_scale(chain, farm, retail)
        if status == CALIBRATION_OK:
            assert chain.scaled(lam).forward(farm).retail_price == pytest.approx(retail, abs=1e-3)


def test_calibration_reports_a_glut_instead_of_inventing_margins():
    chain = default_traditional_chain("vegetable").scaled(0.0)
    floor_retail = chain.forward(0.0).retail_price  # real costs, zero margin
    lam, status = calibrate_margin_scale(chain, 100.0, floor_retail - 1.0)
    assert status == CALIBRATION_GLUT
    assert lam == 0.0


def test_calibration_reports_unreachable_at_the_ceiling():
    chain = default_traditional_chain("vegetable")
    lam, status = calibrate_margin_scale(chain, 2200.0, 10_000_000.0, hi=2.0)
    assert status == CALIBRATION_UNREACHABLE
    assert lam == pytest.approx(2.0)


def test_forward_is_monotone_in_margin_scale():
    """Bisection is only valid because the map is monotone. Prove it empirically."""
    chain = default_traditional_chain("vegetable")
    prices = [chain.scaled(lam).forward(2200.0).retail_price for lam in (0.0, 0.25, 0.5, 1.0, 2.0)]
    assert prices == sorted(prices)
    assert len(set(round(p, 6) for p in prices)) == len(prices)  # strictly increasing


def test_calibration_is_bracketing_independent():
    """Different brackets must converge to the same root."""
    chain = default_traditional_chain("vegetable")
    a, _ = calibrate_margin_scale(chain, 2200.0, 4000.0, hi=25.0)
    b, _ = calibrate_margin_scale(chain, 2200.0, 4000.0, hi=100.0)
    assert a == pytest.approx(b, rel=1e-6)


def test_calibration_rejects_negative_prices():
    chain = default_traditional_chain("vegetable")
    with pytest.raises(ValueError):
        calibrate_margin_scale(chain, -1.0, 4000.0)


# ─────────────────────────────────────────────────────────────────────────────
# Serialisation
# ─────────────────────────────────────────────────────────────────────────────


def test_chain_round_trips_through_dict():
    chain = default_traditional_chain("vegetable").scaled(0.7)
    rebuilt = ValueChain.from_dict(chain.to_dict())
    assert rebuilt == chain
    assert rebuilt.forward(2200.0).retail_price == pytest.approx(
        chain.forward(2200.0).retail_price
    )


def test_stage_from_dict_ignores_unknown_keys():
    st = Stage.from_dict(
        {"key": "x", "label_en": "X", "margin_pct": 0.1, "bogus_field": "ignore me"}
    )
    assert st.key == "x"
    assert st.margin_pct == pytest.approx(0.1)


def test_chain_result_serialises_without_error_and_is_json_compatible():
    import json

    res = default_traditional_chain("vegetable").forward(2200.0)
    payload = json.loads(json.dumps(res.to_dict()))
    assert payload["chain_length"] == len(res.stages)
    assert len(payload["stages"]) == len(res.stages)
    assert all(math.isfinite(v) for v in payload.values() if isinstance(v, (int, float)))


def test_repr_is_informative():
    text = repr(default_traditional_chain("vegetable"))
    assert "ValueChain" in text and "traditional" in text
