"""Joint surplus and its division between farmer and consumer.

This module is the economic core of SIH26033.  Everything else in the package
exists to compute, allocate or deliver the numbers defined here.

The problem
-----------
A farmer can sell at the mandi for ``P`` (₹/quintal at the farm gate).  A
consumer can buy at retail for ``R`` (₹/quintal at the shop).  Between those two
prices sits a chain that absorbs rupees without adding value.  If produce moves
directly, only genuinely physical costs have to be paid — grading, packing,
freight, last mile, a platform fee.  Call the remainder the **pie**.

The pie has to be *split*, and how it is split is a real design decision: give it
all to the farmer and the consumer has no reason to switch; give it all to the
consumer and the farmer has no reason to switch.

Unit convention
---------------
Everything here is per **farm-gate quintal** — the unit the farmer decides over.
This matters more than it sounds.  An earlier formulation worked per *consumer*
quintal and measured the farmer's fallback as ``P / w_trad`` (mandi revenue per
quintal that reaches a shop through the traditional chain).  That is the right
number for a *chain* comparison, but the wrong one for the farmer's actual
choice: he sells the same physical quintals either way and is paid for all of
them at the mandi, so his disagreement payoff is simply ``P``.  Conflating the
two made the per-lane gains disagree with the rolled-up impact totals.
Per-farm-quintal accounting avoids the whole class of bug.

The model
---------
* ``w``  — direct-channel delivered ratio (consumer quintals per farm quintal).
* ``p_f``— farm-gate price, ₹/quintal.  This is the bargaining variable.
* ``T``  — direct logistics cost, ₹ per farm quintal (packing + freight +
  handling + last mile).
* ``m``  — platform fee, charged on (farm price + logistics).
* ``p_c``— consumer price, ₹ per quintal **delivered**.

The direct channel's cost structure gives the consumer's total outlay per
farm-gate quintal as::

    w·p_c = (1 + m)·(p_f + T)

i.e. the farmer's price plus the real cost, grossed up by the fee.  Solving for
the consumer's per-quintal price::

    p_c = (1 + m)·(p_f + T) / w

Gains relative to the status quo (per farm-gate quintal)::

    S_farmer(p_f)   = p_f - P                        farmer beats the mandi
    S_consumer(p_f) = w·R - (1 + m)·(p_f + T)        consumer beats the shop

Total pie::

    Π(p_f) = S_farmer + S_consumer = w·R - (1 + m)·T - (1 + m)·P - m·(p_f - P)

Note ``dΠ/dp_f = -m <= 0``: with a *proportional* fee, moving rupees from the
consumer to the farmer costs only the fee on those rupees.  With no fee at all
the split is a pure transfer and the pie is constant — which is exactly why
"maximise the pie" is the wrong objective and a fairness rule is required.

The split rule: asymmetric Nash bargaining
------------------------------------------
Maximise ``S_consumer^(1-α) · S_farmer^α`` over ``p_f``, where ``α ∈ [0, 1]`` is
the weight on the farmer.  Both gains are affine in ``p_f`` with slopes
``-(1+m)`` and ``+1`` respectively, so the first-order condition is::

    α·S_consumer = (1 - α)·(1 + m)·S_farmer
    ⇒  p_f* = α·P_max  +  (1 - α)·P

where ``P_max = [w·R - (1+m)·T] / (1+m)`` is the price at which the consumer's
saving falls to zero.

A closed form — no solver, no iteration, no convergence risk.  Sanity checks:

* ``α = ½`` and ``m = 0`` → ``p_f*`` is exactly the midpoint of the farmer's
  fallback and the consumer's ceiling.  The classic symmetric Nash outcome.
* ``α = 1`` → ``p_f* = P_max``, consumer saving is zero, the farmer takes
  everything the consumer was willing to pay.
* ``α = 0`` → ``p_f* = P``, the farmer gains nothing and the consumer takes all.

The objective is a concave quadratic in ``p_f`` (a product of two affine terms,
one increasing and one decreasing), so the stationary point is the **unique
global maximum** on the feasible interval.  That is asserted in the tests
against both golden-section search and a dense grid sweep, not just claimed here.

Feasibility
-----------
A trade only exists if both sides can gain.  At the farmer's fallback the pie is::

    Π_max = w·R - (1 + m)·(P + T)

``Π_max > 0`` is necessary and sufficient for a strictly positive surplus.  When
it is not, the honest answer is "no direct trade beats the status quo for this
pair" — and the engine returns that rather than a fabricated saving.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

_EPS = 1e-9


@dataclass(frozen=True)
class Split:
    """The outcome of splitting one lane's pie.  All ₹ figures per farm quintal
    unless the field name says otherwise."""

    # Inputs echoed back so the result is self-auditing.
    retail_price: float  # R — consumer's shop fallback, ₹/delivered quintal
    farmer_fallback: float  # P — farmer's mandi fallback, ₹/farm quintal
    delivered_ratio: float  # w
    logistics_per_farm_qtl: float  # T
    effective_markup: float  # m — platform fee
    alpha: float

    # The agreed prices.
    farm_price_per_qtl: float  # p_f, ₹/farm quintal — what the farmer is paid
    consumer_price_per_delivered_qtl: float  # p_c, ₹/delivered quintal

    # Gains vs. the status quo, ₹ per farm quintal.
    farmer_gain_per_farm_qtl: float  # S_f
    consumer_saving_per_farm_qtl: float  # S_c
    total_surplus_per_farm_qtl: float  # Π == S_f + S_c

    # Where the consumer's money goes, ₹ per farm quintal.
    farmer_share_rs: float  # p_f
    logistics_share_rs: float  # T
    platform_share_rs: float  # m·(p_f + T)

    consumer_outlay_per_farm_qtl: float  # (1+m)·(p_f + T) == w·p_c

    # Percentages for the UI.
    farmer_gain_pct: float  # (p_f / P - 1)·100
    consumer_saving_pct: float  # (1 - p_c / R)·100
    farmer_share_of_consumer_rupee_pct: float

    viable: bool
    reason: str

    def to_dict(self) -> dict:
        return {
            "retail_price": round(self.retail_price, 4),
            "farmer_fallback_per_qtl": round(self.farmer_fallback, 4),
            "delivered_ratio": round(self.delivered_ratio, 6),
            "logistics_per_farm_qtl": round(self.logistics_per_farm_qtl, 4),
            "effective_markup": round(self.effective_markup, 6),
            "alpha": round(self.alpha, 6),
            "farm_price_per_qtl": round(self.farm_price_per_qtl, 4),
            "mandi_price_per_qtl": round(self.farmer_fallback, 4),
            "consumer_price_per_delivered_qtl": round(self.consumer_price_per_delivered_qtl, 4),
            "farmer_gain_per_farm_qtl": round(self.farmer_gain_per_farm_qtl, 4),
            "consumer_saving_per_farm_qtl": round(self.consumer_saving_per_farm_qtl, 4),
            "total_surplus_per_farm_qtl": round(self.total_surplus_per_farm_qtl, 4),
            "farmer_share_rs": round(self.farmer_share_rs, 4),
            "logistics_share_rs": round(self.logistics_share_rs, 4),
            "platform_share_rs": round(self.platform_share_rs, 4),
            "consumer_outlay_per_farm_qtl": round(self.consumer_outlay_per_farm_qtl, 4),
            "farmer_gain_pct": round(self.farmer_gain_pct, 4),
            "consumer_saving_pct": round(self.consumer_saving_pct, 4),
            "farmer_share_of_consumer_rupee_pct": round(
                self.farmer_share_of_consumer_rupee_pct, 4
            ),
            "viable": self.viable,
            "reason": self.reason,
        }


def max_surplus_per_farm_qtl(
    retail_price: float,
    delivered_ratio: float,
    logistics_per_farm_qtl: float,
    effective_markup: float,
    farmer_fallback: float,
) -> float:
    """Largest pie obtainable on a lane, ₹ per farm-gate quintal.

    ``Π_max = w·R - (1 + m)·(P + T)`` — the pie measured at the farmer's
    disagreement point, where his gain is zero and the consumer takes all.

    A lane is worth routing produce through **iff** this is positive.  That is
    the edge-selection test used by the allocation layer.
    """
    gross = 1.0 + effective_markup
    return (
        delivered_ratio * retail_price
        - gross * farmer_fallback
        - gross * logistics_per_farm_qtl
    )


def nash_farm_price(
    retail_price: float,
    delivered_ratio: float,
    logistics_per_farm_qtl: float,
    effective_markup: float,
    farmer_fallback: float,
    alpha: float = 0.5,
) -> float:
    """Closed-form asymmetric-Nash-bargaining farm price ``p_f*``.

    ``p_f* = α·P_max + (1 - α)·P`` where ``P_max = [w·R - (1+m)·T] / (1+m)``.

    The unique maximiser of ``S_consumer^(1-α)·S_farmer^α`` on ``[P, P_max]``;
    see the module docstring for the derivation.
    """
    gross = 1.0 + effective_markup
    ceiling = (delivered_ratio * retail_price - gross * logistics_per_farm_qtl) / gross
    return alpha * ceiling + (1.0 - alpha) * farmer_fallback


def split_surplus(
    retail_price: float,
    delivered_ratio: float,
    logistics_per_farm_qtl: float,
    effective_markup: float,
    farmer_fallback: float,
    alpha: float = 0.5,
) -> Split:
    """Split one lane's pie between the farmer and the consumer.

    Parameters
    ----------
    retail_price
        ``R`` — what the consumer would otherwise pay, ₹ per quintal delivered.
    delivered_ratio
        ``w`` — consumer quintals obtained per farm-gate quintal.
    logistics_per_farm_qtl
        ``T`` — packing + freight + handling + last mile, ₹ per farm quintal.
        This is the lane-specific term: it carries the freight.
    effective_markup
        ``m`` — the platform fee, applied to (farm price + logistics).
    farmer_fallback
        ``P`` — the mandi price, ₹ per quintal at the farm gate.
    alpha
        Bargaining weight on the farmer.  ``0.5`` is the symmetric Nash split.
    """
    if not (0.0 <= alpha <= 1.0):
        raise ValueError(f"alpha must be within [0, 1], got {alpha}")
    if delivered_ratio <= 0:
        raise ValueError(f"delivered_ratio must be > 0, got {delivered_ratio}")
    if logistics_per_farm_qtl < 0:
        raise ValueError(
            f"logistics_per_farm_qtl must be >= 0, got {logistics_per_farm_qtl}"
        )
    if effective_markup < -1.0:
        raise ValueError(f"effective_markup must be >= -1, got {effective_markup}")
    if retail_price < 0 or farmer_fallback < 0:
        raise ValueError("prices must be non-negative")

    gross = 1.0 + effective_markup
    w = float(delivered_ratio)
    T = float(logistics_per_farm_qtl)
    P = max(0.0, float(farmer_fallback))
    R = float(retail_price)

    ceiling = (w * R - gross * T) / gross
    total = max_surplus_per_farm_qtl(R, w, T, effective_markup, P)

    if total <= _EPS:
        # No pie.  Report the status quo honestly rather than inventing a gain.
        return Split(
            retail_price=R,
            farmer_fallback=P,
            delivered_ratio=w,
            logistics_per_farm_qtl=T,
            effective_markup=effective_markup,
            alpha=alpha,
            farm_price_per_qtl=P,
            consumer_price_per_delivered_qtl=R,
            farmer_gain_per_farm_qtl=0.0,
            consumer_saving_per_farm_qtl=0.0,
            total_surplus_per_farm_qtl=max(0.0, total),
            farmer_share_rs=P,
            logistics_share_rs=0.0,
            platform_share_rs=0.0,
            consumer_outlay_per_farm_qtl=w * R,
            farmer_gain_pct=0.0,
            consumer_saving_pct=0.0,
            farmer_share_of_consumer_rupee_pct=(
                100.0 * P / (w * R) if w * R > _EPS else 0.0
            ),
            viable=False,
            reason=(
                "Direct delivery costs more than the traditional chain absorbs on this "
                "lane; a direct trade would not improve on the status quo."
            ),
        )

    p_f = nash_farm_price(R, w, T, effective_markup, P, alpha)
    # Numerical hygiene: keep the agreed point inside the bargaining set.
    p_f = min(max(p_f, P), ceiling)
    if p_f < 0:
        p_f = 0.0

    outlay = gross * (p_f + T)
    p_c = outlay / w
    farmer_gain = p_f - P
    consumer_saving = w * R - outlay
    platform_rs = effective_markup * (p_f + T)

    return Split(
        retail_price=R,
        farmer_fallback=P,
        delivered_ratio=w,
        logistics_per_farm_qtl=T,
        effective_markup=effective_markup,
        alpha=alpha,
        farm_price_per_qtl=p_f,
        consumer_price_per_delivered_qtl=p_c,
        farmer_gain_per_farm_qtl=farmer_gain,
        consumer_saving_per_farm_qtl=consumer_saving,
        total_surplus_per_farm_qtl=farmer_gain + consumer_saving,
        farmer_share_rs=p_f,
        logistics_share_rs=T,
        platform_share_rs=platform_rs,
        consumer_outlay_per_farm_qtl=outlay,
        farmer_gain_pct=(100.0 * (p_f / P - 1.0) if P > _EPS else 0.0),
        consumer_saving_pct=(100.0 * (1.0 - p_c / R) if R > _EPS else 0.0),
        farmer_share_of_consumer_rupee_pct=(100.0 * p_f / outlay if outlay > _EPS else 0.0),
        viable=True,
        reason="",
    )


def nash_objective(
    p_f: float,
    retail_price: float,
    delivered_ratio: float,
    logistics_per_farm_qtl: float,
    effective_markup: float,
    farmer_fallback: float,
    alpha: float,
) -> Optional[float]:
    """``S_consumer^(1-α) · S_farmer^α`` — exposed for optimality testing.

    Returns ``None`` outside the bargaining set (where one side would lose), so
    tests can assert both that the closed form maximises it *and* that the
    maximiser is interior.

    Boundary convention: ``x**0 == 1`` for every ``x``, including ``x == 0``
    (the combinatorial convention for ``0**0``).  Without it the endpoint cases
    collapse wrongly — at ``α = 0`` the objective is just ``S_consumer``, and
    evaluating it at ``p_f = P`` (where ``S_farmer = 0``) must give
    ``S_consumer``, not zero.
    """
    gross = 1.0 + effective_markup
    s_f = p_f - farmer_fallback
    s_c = delivered_ratio * retail_price - gross * (p_f + logistics_per_farm_qtl)
    if s_f < -_EPS or s_c < -_EPS:
        return None
    s_f = max(s_f, 0.0)
    s_c = max(s_c, 0.0)

    if s_c > 0.0:
        term_c = s_c ** (1.0 - alpha)
    else:
        term_c = 1.0 if alpha >= 1.0 - _EPS else 0.0

    if s_f > 0.0:
        term_f = s_f**alpha
    else:
        term_f = 1.0 if alpha <= _EPS else 0.0

    return term_c * term_f


def bargaining_bounds(
    retail_price: float,
    delivered_ratio: float,
    logistics_per_farm_qtl: float,
    effective_markup: float,
    farmer_fallback: float,
) -> tuple:
    """The bargaining set ``[P, P_max]`` in farm-price terms."""
    gross = 1.0 + effective_markup
    ceiling = (delivered_ratio * retail_price - gross * logistics_per_farm_qtl) / gross
    return farmer_fallback, ceiling
