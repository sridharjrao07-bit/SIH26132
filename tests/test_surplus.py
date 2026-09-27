"""Surplus splitting: the closed-form Nash solution checked against brute force.

The engine does not *search* for the split, it evaluates a closed form:

    p_f* = α·P_max  +  (1 - α)·P      where  P_max = [w·R - (1+m)·T] / (1+m)

That is only safe if it really is the maximiser of the bargaining objective.
These tests verify it two independent ways:

* **Against a numerical optimiser.**  Golden-section search over ``p_f`` finds
  the maximum of ``S_c^(1-α)·S_f^α``; the closed form must land on the same
  point.  If the derivation were wrong, this fails.
* **Against a dense grid sweep.**  Slower, but it cannot get trapped and it
  catches a closed form that is only locally optimal.

Plus the algebraic identities both sides of the trade rely on: the split always
sums to the pie, both parties are always at least as well off as their fallback,
the consumer's rupee reconciles exactly, and the pie shrinks in ``p_f`` at
exactly the rate ``-m``.
"""

from __future__ import annotations

import json
import math

import pytest
from direct.fair_price import leakage_report
from direct.surplus import (
    bargaining_bounds,
    max_surplus_per_farm_qtl,
    nash_farm_price,
    nash_objective,
    split_surplus,
)
from direct.value_chain import Stage, ValueChain, default_traditional_chain

# A representative Nashik onion lane.
R = 4000.0  # retail, ₹ per quintal delivered to the consumer
W = 0.985  # direct delivered ratio (in-transit spoilage only)
T = 100.0  # packing + freight + handling, ₹ per farm-gate quintal
M = 0.03  # platform fee
P = 2200.0  # mandi fallback, ₹ per quintal at the farm gate

GROSS = 1.0 + M


def golden_section_max(f, lo, hi, iters=300):
    """Maximise a unimodal function on [lo, hi] by golden-section search."""
    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c = b - invphi * (b - a)
    d = a + invphi * (b - a)
    for _ in range(iters):
        if f(c) > f(d):
            b, d = d, c
            c = b - invphi * (b - a)
        else:
            a, c = c, d
            d = a + invphi * (b - a)
        if abs(b - a) < 1e-13:
            break
    return 0.5 * (a + b)


# ─────────────────────────────────────────────────────────────────────────────
# The closed form is the true maximiser
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("alpha", [0.05, 0.25, 0.5, 0.75, 0.95])
def test_closed_form_matches_numerical_maximisation(alpha):
    p_star = nash_farm_price(R, W, T, M, P, alpha)
    lo, hi = bargaining_bounds(R, W, T, M, P)

    def objective(pf):
        val = nash_objective(pf, R, W, T, M, P, alpha)
        return -1e18 if val is None else val

    numeric = golden_section_max(objective, lo, hi)
    assert p_star == pytest.approx(numeric, rel=1e-5)


@pytest.mark.parametrize("alpha", [0.0, 0.3, 0.5, 0.7, 1.0])
def test_closed_form_beats_a_dense_grid(alpha):
    """No point on a 4000-point grid may beat the closed form."""
    p_star = nash_farm_price(R, W, T, M, P, alpha)
    lo, hi = bargaining_bounds(R, W, T, M, P)
    best_val, best_p = -1.0, p_star
    for i in range(4001):
        pf = lo + (hi - lo) * i / 4000.0
        val = nash_objective(pf, R, W, T, M, P, alpha)
        if val is not None and val > best_val:
            best_val, best_p = val, pf
    assert nash_objective(p_star, R, W, T, M, P, alpha) >= best_val * (1 - 1e-9)
    assert best_p == pytest.approx(p_star, abs=(hi - lo) / 4000.0 + 1e-6)


def test_symmetric_nash_is_the_midpoint_when_the_platform_fee_is_zero():
    """α=½, m=0 → p_f* is exactly halfway between the fallback and the ceiling."""
    p_star = nash_farm_price(R, W, T, 0.0, P, 0.5)
    lo, hi = bargaining_bounds(R, W, T, 0.0, P)
    assert p_star == pytest.approx(0.5 * (lo + hi))


def test_alpha_one_gives_the_farmer_everything_the_consumer_would_pay():
    p_star = nash_farm_price(R, W, T, M, P, 1.0)
    _, hi = bargaining_bounds(R, W, T, M, P)
    assert p_star == pytest.approx(hi)
    s = split_surplus(R, W, T, M, P, 1.0)
    assert s.consumer_saving_per_farm_qtl == pytest.approx(0.0, abs=1e-6)
    assert s.farmer_gain_per_farm_qtl > 0


def test_alpha_zero_leaves_the_farmer_at_his_mandi_price():
    p_star = nash_farm_price(R, W, T, M, P, 0.0)
    assert p_star == pytest.approx(P)
    s = split_surplus(R, W, T, M, P, 0.0)
    assert s.farm_price_per_qtl == pytest.approx(P)
    assert s.farmer_gain_per_farm_qtl == pytest.approx(0.0, abs=1e-9)
    assert s.consumer_saving_per_farm_qtl > 0  # the consumer takes all of it


@pytest.mark.parametrize("alpha", [0.0, 0.25, 0.5, 0.75, 0.95])
def test_farm_price_increases_with_alpha(alpha):
    """The bargaining weight must move the outcome in its own direction."""
    low = nash_farm_price(R, W, T, M, P, alpha)
    high = nash_farm_price(R, W, T, M, P, min(1.0, alpha + 0.05))
    assert high >= low


# ─────────────────────────────────────────────────────────────────────────────
# Algebraic identities
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("alpha", [0.0, 0.2, 0.5, 0.8, 1.0])
def test_gains_sum_to_the_pie(alpha):
    s = split_surplus(R, W, T, M, P, alpha)
    assert s.farmer_gain_per_farm_qtl + s.consumer_saving_per_farm_qtl == pytest.approx(
        s.total_surplus_per_farm_qtl, abs=1e-6
    )


@pytest.mark.parametrize("alpha", [0.0, 0.2, 0.5, 0.8, 1.0])
def test_neither_side_is_worse_off_than_their_fallback(alpha):
    s = split_surplus(R, W, T, M, P, alpha)
    assert s.farm_price_per_qtl >= P - 1e-9
    assert s.consumer_price_per_delivered_qtl <= R + 1e-9
    assert s.farmer_gain_per_farm_qtl >= -1e-9
    assert s.consumer_saving_per_farm_qtl >= -1e-9


@pytest.mark.parametrize("alpha", [0.2, 0.5, 0.8])
def test_consumer_rupee_is_fully_accounted_for(alpha):
    """Farmer + logistics + platform must reconstruct the consumer's outlay."""
    s = split_surplus(R, W, T, M, P, alpha)
    assert (
        s.farmer_share_rs + s.logistics_share_rs + s.platform_share_rs
        == pytest.approx(s.consumer_outlay_per_farm_qtl, abs=1e-6)
    )


@pytest.mark.parametrize("alpha", [0.2, 0.5, 0.8])
def test_outlay_identity_links_price_quantity_and_cost(alpha):
    """``w · p_c == (1 + m) · (p_f + T)`` — the identity the model is built on."""
    s = split_surplus(R, W, T, M, P, alpha)
    assert s.consumer_outlay_per_farm_qtl == pytest.approx(
        GROSS * (s.farm_price_per_qtl + T), abs=1e-6
    )
    assert s.consumer_outlay_per_farm_qtl == pytest.approx(
        W * s.consumer_price_per_delivered_qtl, abs=1e-6
    )


def test_the_pie_shrinks_in_farm_price_at_exactly_the_fee_rate():
    """dΠ/dp_f = -m. With no platform fee the split is a pure transfer."""

    def pie(pf, m):
        return W * R - (1 + m) * (pf + T) + (pf - P)

    for pf in (P + 100.0, P + 500.0, P + 900.0):
        assert pie(pf + 1, M) - pie(pf, M) == pytest.approx(-M, abs=1e-9)

    # Zero fee: the pie is invariant to the split, which is exactly why a
    # fairness rule is needed rather than an optimiser.
    for pf in (P + 100.0, P + 500.0):
        assert pie(pf, 0.0) == pytest.approx(pie(pf + 250.0, 0.0), abs=1e-6)


def test_max_surplus_is_the_pie_at_the_farmers_fallback():
    expected = W * R - GROSS * (P + T)
    assert max_surplus_per_farm_qtl(R, W, T, M, P) == pytest.approx(expected)

    s = split_surplus(R, W, T, M, P, 0.5)
    uplift = s.farm_price_per_qtl - P
    # Recovering the max pie: add back the fee cost of the farmer's uplift.
    assert s.total_surplus_per_farm_qtl + M * uplift == pytest.approx(expected, abs=1e-6)


def test_surplus_falls_as_logistics_get_more_expensive():
    cheap = max_surplus_per_farm_qtl(R, W, 50.0, M, P)
    dear = max_surplus_per_farm_qtl(R, W, 300.0, M, P)
    assert dear < cheap


def test_surplus_rises_with_the_delivered_ratio():
    """Less spoilage in the direct channel is worth real money."""
    wasteful = max_surplus_per_farm_qtl(R, 0.85, T, M, P)
    careful = max_surplus_per_farm_qtl(R, 0.99, T, M, P)
    assert careful > wasteful


def test_the_farmer_actually_gains_against_his_mandi_alternative():
    s = split_surplus(R, W, T, M, P, 0.5)
    assert s.farm_price_per_qtl > P
    assert s.farmer_gain_pct > 0
    assert s.consumer_saving_pct > 0
    # And the farmer receives the overwhelming majority of the consumer's rupee
    # in a direct trade — the whole point.
    assert s.farmer_share_of_consumer_rupee_pct > 85.0


# ─────────────────────────────────────────────────────────────────────────────
# Viability
# ─────────────────────────────────────────────────────────────────────────────


def test_no_trade_when_the_direct_channel_costs_more_than_the_chain_absorbs():
    s = split_surplus(retail_price=1000.0, delivered_ratio=W,
                      logistics_per_farm_qtl=5000.0, effective_markup=M,
                      farmer_fallback=2200.0, alpha=0.5)
    assert not s.viable
    assert s.farmer_gain_per_farm_qtl == 0.0
    assert s.consumer_saving_per_farm_qtl == 0.0
    assert s.farm_price_per_qtl == pytest.approx(2200.0)
    assert s.consumer_price_per_delivered_qtl == pytest.approx(1000.0)  # status quo
    assert s.reason


def test_viability_threshold_is_exactly_zero_pie():
    """At Π_max == 0 the trade is exactly indifferent — and must be refused."""
    T_edge = (W * R - GROSS * P) / GROSS
    assert max_surplus_per_farm_qtl(R, W, T_edge, M, P) == pytest.approx(0.0, abs=1e-9)
    assert not split_surplus(R, W, T_edge, M, P, 0.5).viable
    # A rupee cheaper and it becomes viable.
    assert split_surplus(R, W, T_edge - 1.0, M, P, 0.5).viable


def test_unviable_result_still_reports_the_status_quo_honestly():
    s = split_surplus(1000.0, W, 5000.0, M, 2000.0, 0.5)
    # Measured against the fallback the caller supplied (2000), not the module P.
    assert s.farmer_share_of_consumer_rupee_pct == pytest.approx(
        100.0 * 2000.0 / (W * 1000.0), abs=1e-3
    )
    assert s.farmer_gain_pct == 0.0
    assert s.consumer_saving_pct == 0.0
    assert s.total_surplus_per_farm_qtl == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Input validation and serialisation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("alpha", [-0.01, 1.01, 2.0])
def test_alpha_out_of_range_rejected(alpha):
    with pytest.raises(ValueError):
        split_surplus(R, W, T, M, P, alpha)


@pytest.mark.parametrize("w", [0.0, -1.0])
def test_non_positive_delivered_ratio_rejected(w):
    with pytest.raises(ValueError):
        split_surplus(R, w, T, M, P, 0.5)


def test_negative_logistics_rejected():
    with pytest.raises(ValueError):
        split_surplus(R, W, -1.0, M, P, 0.5)


def test_effective_markup_below_minus_one_rejected():
    with pytest.raises(ValueError):
        split_surplus(R, W, T, -1.5, P, 0.5)


def test_negative_prices_rejected():
    with pytest.raises(ValueError):
        split_surplus(-1.0, W, T, M, P, 0.5)
    with pytest.raises(ValueError):
        split_surplus(R, W, T, M, -1.0, 0.5)


def test_zero_platform_fee_is_allowed_and_gives_the_symmetric_midpoint():
    s = split_surplus(R, W, T, 0.0, P, 0.5)
    assert s.effective_markup == pytest.approx(0.0)
    assert s.platform_share_rs == pytest.approx(0.0)
    lo, hi = bargaining_bounds(R, W, T, 0.0, P)
    assert s.farm_price_per_qtl == pytest.approx(0.5 * (lo + hi))


def test_zero_logistics_still_produces_a_viable_trade():
    s = split_surplus(R, W, 0.0, M, P, 0.5)
    assert s.viable
    assert s.logistics_share_rs == 0.0


def test_split_serialises_to_json_compatible_numbers():
    import json

    s = split_surplus(R, W, T, M, P, 0.5)
    payload = json.loads(json.dumps(s.to_dict()))
    assert payload["viable"] is True
    for key, value in payload.items():
        if isinstance(value, float):
            assert math.isfinite(value), key


def test_nash_objective_is_none_outside_the_bargaining_set():
    lo, hi = bargaining_bounds(R, W, T, M, P)
    assert nash_objective(lo - 1.0, R, W, T, M, P, 0.5) is None  # farmer loses
    assert nash_objective(hi + 1.0, R, W, T, M, P, 0.5) is None  # consumer loses


def test_symmetric_nash_gives_the_consumer_the_fee_worth_of_extra_gain():
    """At α=½ the gains are equal only up to the platform fee.

    The first-order condition is ``α·S_c = (1-α)·(1+m)·S_f``, so at ``α = ½`` the
    consumer's saving exceeds the farmer's gain by exactly ``(1 + m)``.  That is
    not an asymmetry in the rule — it is the fee: moving a rupee to the farmer
    costs the consumer a rupee *plus* the fee on it, so an even split of utility
    buys the farmer slightly fewer rupees.  With a 3% fee the farmer still takes
    ~49.3% of the pie, so the effect is small, but it is real and this test
    pins it down.
    """
    s = split_surplus(R, W, T, M, P, 0.5)
    ratio = s.consumer_saving_per_farm_qtl / s.farmer_gain_per_farm_qtl
    assert ratio == pytest.approx(GROSS, rel=1e-9)
    farmer_share = s.farmer_gain_per_farm_qtl / s.total_surplus_per_farm_qtl
    assert 0.49 < farmer_share < 0.50


def test_with_no_platform_fee_the_symmetric_split_is_exactly_even():
    s = split_surplus(R, W, T, 0.0, P, 0.5)
    assert s.farmer_gain_per_farm_qtl == pytest.approx(
        s.consumer_saving_per_farm_qtl, abs=1e-6
    )


# ─────────────────────────────────────────────────────────────────────────────
# Leakage report — the honesty guards
# ─────────────────────────────────────────────────────────────────────────────


def test_leakage_splits_the_spread_into_margin_and_work():
    """Avoidable + unavoidable must exhaust the spread, with neither at zero.

    Regression guard.  The first cut summed the take of stages flagged
    `essential = False`, and since every stage of the reference chain is
    non-essential in that sense, it reported 100% of the spread as avoidable —
    an overclaim that would not survive a judge asking "so you can also stop
    paying for transport?".  Avoidable is the margin; unavoidable is the work.
    """
    report = leakage_report(
        default_traditional_chain("vegetable"), 2200.0, 4000.0, commodity="onion"
    )
    absorption = report.chain.absorption
    assert report.avoidable_per_farm_qtl + report.unavoidable_per_farm_qtl == pytest.approx(
        absorption, abs=1e-6
    )
    assert report.avoidable_per_farm_qtl > 0
    assert report.unavoidable_per_farm_qtl > 0
    # The margin is the avoidable part, and the work is the rest.
    assert report.avoidable_per_farm_qtl == pytest.approx(
        report.chain.margin_absorption, abs=1e-6
    )
    assert report.unavoidable_per_farm_qtl == pytest.approx(
        report.chain.cost_absorption, abs=1e-6
    )
    # Sanity: most of a vegetable spread is margin, but nowhere near all of it.
    share = report.avoidable_per_farm_qtl / absorption
    assert 0.5 < share < 0.9, share


def test_verdict_flags_a_chain_that_is_mostly_margin():
    """A chain losing 14% of the crop to 70% margin is not 'healthy'.

    Regression guard.  The verdict used to key off the farmer's share alone, so
    a 64% share produced "healthy share; limited headroom" for a chain the
    engine then improved by +35% for the farmer and -20% for the consumer.
    Headroom is the margin share, not the current split.
    """
    report = leakage_report(
        default_traditional_chain("vegetable"), 2200.0, 4000.0, commodity="onion"
    )
    assert "limited headroom" not in report.verdict.lower()
    assert "heavy intermediary absorption" in report.verdict.lower()
    assert report.chain.margin_share_pct > 65


def test_verdict_calls_a_thin_spread_thin():
    """A chain that only charges for real work leaves nothing to recover."""
    thin = ValueChain(
        name="thin",
        stages=(
            Stage(key="mover", label_en="Mover", margin_pct=0.0,
                  cost_per_qtl=300.0, loss_pct=0.02, essential=True, kind="logistics"),
        ),
    )
    report = leakage_report(thin, 2200.0, 2600.0, commodity="onion")
    assert report.avoidable_per_farm_qtl == pytest.approx(0.0, abs=1e-6)
    assert "thin" in report.verdict.lower() or "little to recover" in report.verdict.lower()


def test_leakage_is_serialisable_and_finite():
    report = leakage_report(
        default_traditional_chain("vegetable"), 2200.0, 4000.0, commodity="onion"
    )
    payload = json.dumps(report.to_dict())
    assert "NaN" not in payload and "Infinity" not in payload
    assert json.loads(payload)["avoidable_per_farm_qtl"] > 0
