"""Affine value-chain model: farm gate → consumer.

Why an *affine* model
---------------------
Agri price build-up is conventionally drawn as a chain of stages. Each stage
does three things to the value of the produce passing through it:

1. **Physical loss** (``loss_pct``)   — a fraction of the load is spoilt.
   The surviving quantity must carry the cost of the whole load, so the value
   per surviving quintal is *divided* by ``(1 - loss)``.  Multiplicative.
2. **Handling cost** (``cost_per_qtl``) — grading, packing, freight, rent.
   Incurred on the surviving quantity.  Additive.
3. **Margin** (``margin_pct``)        — the intermediary's markup on cost.
   Multiplicative.

Each stage is therefore the affine map ::

    p_out = A_i * p_in + B_i        with  A_i = (1 + m_i) / (1 - l_i)
                                          B_i = (1 + m_i) * c_i

An affine map is **exactly invertible**, and a composition of affine maps is
affine, so the whole chain collapses to two scalars::

    p_retail = A * p_farm + B        A = Π A_i  ( > 0 always )
                                     B = Σ B_i · Π_{j>i} A_j
    p_farm   = (p_retail - B) / A

Two properties fall out for free and both are used by the rest of the engine:

* **Pass-through** — ``d p_farm / d p_retail = 1 / A``.  This is the number the
  problem statement is really about: when the retail price of onion rises by
  ₹100, only ₹100/A reaches the grower.  For a typical five-stage chain
  ``A ≈ 1.9``, so the farmer sees about half.
* **Exact attribution** — because every rupee of the final price is traced
  through the same recurrence, every stage's rupee take is known exactly, and
  the takes sum *by construction* to the total absorption.  There is no
  residual and no fudge factor.

Convention
----------
* ``p_farm``   is ₹ per quintal **at the farm gate**.
* ``p_retail`` is ₹ per quintal **as bought by the consumer**.
* ``w`` (``delivered_ratio``) is the number of consumer quintals produced by one
  farm-gate quintal, i.e. ``Π (1 - loss_i)``.

All rupee aggregates reported by :meth:`ValueChain.forward` are expressed **per
farm-gate quintal** — the unit the farmer actually decides over.  Rupee-per-
consumer-quintal figures are one division away and are provided separately
wherever a consumer-facing number is needed.

Calibration
-----------
Margins are the part of the chain nobody publishes per-market.  Rather than
hard-code a guess, :func:`calibrate_margin_scale` fits a single scalar ``λ``
that scales every stage margin so the model reproduces an *observed*
(mandi price, retail price) pair.  Because ``A`` and ``B`` are both strictly
increasing in ``λ``, the forward price is strictly increasing in ``λ`` and
bisection converges monotonically — see :func:`calibrate_margin_scale`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

# A stage that destroys >= this fraction of the load is almost certainly a data
# entry error (someone typed 90 for 9.0).  Rejecting it loudly is better than
# silently dividing by 0.10 and inventing a 10x price.
MAX_LOSS_PCT = 0.90

_EPS = 1e-12

# ─────────────────────────────────────────────────────────────────────────────
# Stage
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Stage:
    """One link of the chain.

    Attributes
    ----------
    key         Stable identifier used in API payloads and persisted profiles.
    label_en    Human-readable name (``label_mr`` / ``label_hi`` mirror it).
    margin_pct  Markup taken at this stage, as a fraction of accumulated cost.
    cost_per_qtl
                Real resource cost incurred here, ₹ per surviving quintal
                (freight, grading, packing, rent, labour).
    loss_pct    Fraction of the load physically lost at this stage.
    essential   ``True`` when the stage performs a real function that survives
                disintermediation (grading, packing, freight).  ``False`` for
                pure rent-extraction layers.  The direct channel keeps only the
                essential stages — that is the whole point of the exercise.
    kind        Grouping label used by the UI: ``farm`` | ``assembly`` |
                ``intermediary`` | ``logistics`` | ``retail`` | ``platform``.
    """

    key: str
    label_en: str
    margin_pct: float = 0.0
    cost_per_qtl: float = 0.0
    loss_pct: float = 0.0
    essential: bool = False
    kind: str = "intermediary"
    label_mr: str = ""
    label_hi: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("Stage.key must be non-empty")
        if self.margin_pct < 0:
            raise ValueError(f"Stage {self.key!r}: margin_pct must be >= 0, got {self.margin_pct}")
        if self.cost_per_qtl < 0:
            raise ValueError(f"Stage {self.key!r}: cost_per_qtl must be >= 0, got {self.cost_per_qtl}")
        if not (0.0 <= self.loss_pct <= MAX_LOSS_PCT):
            raise ValueError(
                f"Stage {self.key!r}: loss_pct must be within [0, {MAX_LOSS_PCT}], got {self.loss_pct}"
            )

    # -- derived scalars -----------------------------------------------------

    @property
    def A(self) -> float:
        """Multiplicative coefficient of the stage's affine map."""
        return (1.0 + self.margin_pct) / (1.0 - self.loss_pct)

    @property
    def B(self) -> float:
        """Additive coefficient of the stage's affine map."""
        return (1.0 + self.margin_pct) * self.cost_per_qtl

    def scaled(self, factor: float) -> "Stage":
        """Return this stage with its margin multiplied by ``factor``.

        Physical losses and handling costs are *not* scaled — they are real
        resource use, not negotiable rent.
        """
        return replace(self, margin_pct=self.margin_pct * factor)

    def to_dict(self) -> Dict:
        return {
            "key": self.key,
            "label_en": self.label_en,
            "label_mr": self.label_mr,
            "label_hi": self.label_hi,
            "margin_pct": self.margin_pct,
            "cost_per_qtl": self.cost_per_qtl,
            "loss_pct": self.loss_pct,
            "essential": self.essential,
            "kind": self.kind,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, row: Dict) -> "Stage":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in row.items() if k in known and v is not None})


# ─────────────────────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageResult:
    """What one stage did to the value of a single farm-gate quintal."""

    key: str
    label_en: str
    label_mr: str
    label_hi: str
    kind: str
    essential: bool

    price_in: float  # ₹/quintal entering this stage
    price_out: float  # ₹/quintal leaving this stage
    qty_in: float  # quintals alive entering, per farm quintal
    qty_out: float  # quintals alive leaving, per farm quintal
    value_in: float  # ₹ carried in, per farm quintal
    value_out: float  # ₹ carried out, per farm quintal

    cost_take: float  # ₹ absorbed by real handling cost, per farm quintal
    margin_take: float  # ₹ absorbed as margin, per farm quintal
    take: float  # cost_take + margin_take == value_out - value_in

    margin_pct: float
    cost_per_qtl: float
    loss_pct: float
    spoilage_qtl: float  # quintals physically destroyed here, per farm quintal
    note: str = ""

    def to_dict(self) -> Dict:
        return {
            "key": self.key,
            "label_en": self.label_en,
            "label_mr": self.label_mr,
            "label_hi": self.label_hi,
            "kind": self.kind,
            "essential": self.essential,
            "price_in": round(self.price_in, 4),
            "price_out": round(self.price_out, 4),
            "qty_in": round(self.qty_in, 6),
            "qty_out": round(self.qty_out, 6),
            "value_in": round(self.value_in, 4),
            "value_out": round(self.value_out, 4),
            "cost_take": round(self.cost_take, 4),
            "margin_take": round(self.margin_take, 4),
            "take": round(self.take, 4),
            "margin_pct": round(self.margin_pct, 6),
            "cost_per_qtl": round(self.cost_per_qtl, 4),
            "loss_pct": round(self.loss_pct, 6),
            "spoilage_qtl": round(self.spoilage_qtl, 6),
            "note": self.note,
        }

    @property
    def take_pct_of_absorption(self) -> Optional[float]:
        """This stage's take as a share of the rupees it received.

        Undefined (``None``) when nothing of value entered the stage.
        """
        if self.value_in <= _EPS:
            return None
        return 100.0 * self.take / self.value_in


@dataclass(frozen=True)
class ChainResult:
    """Outcome of pushing one farm-gate quintal through a :class:`ValueChain`."""

    chain_name: str
    farm_price: float  # ₹/quintal at the farm gate
    retail_price: float  # ₹/quintal as paid by the consumer
    delivered_ratio: float  # consumer quintals per farm quintal (w)

    # Composite affine coefficients of the whole chain.
    A: float
    B: float

    # ₹ per farm-gate quintal
    consumer_spend: float  # w * retail_price
    absorption: float  # consumer_spend - farm_price
    margin_absorption: float  # portion of `absorption` taken as margin
    cost_absorption: float  # portion of `absorption` spent on real handling

    farmer_share_pct: float  # farm_price / consumer_spend
    price_ratio_pct: float  # farm_price / retail_price — the headline statistic
    absorption_per_delivered_qtl: float  # retail_price - farm_price / w
    pass_through: float  # d farm / d retail == 1 / A
    chain_length: int  # number of stages
    intermediary_count: int  # stages that are not essential
    spoilage_pct: float  # 1 - delivered_ratio

    stages: Tuple[StageResult, ...]

    @property
    def margin_share_pct(self) -> float:
        """Share of the total absorption that is margin rather than real cost."""
        if self.absorption <= _EPS:
            return 0.0
        return 100.0 * self.margin_absorption / self.absorption

    def to_dict(self) -> Dict:
        spend = self.consumer_spend if abs(self.consumer_spend) > _EPS else 1.0
        return {
            "chain_name": self.chain_name,
            "farm_price": round(self.farm_price, 4),
            "retail_price": round(self.retail_price, 4),
            "delivered_ratio": round(self.delivered_ratio, 6),
            "spoilage_pct": round(self.spoilage_pct, 6),
            "A": round(self.A, 6),
            "B": round(self.B, 6),
            "consumer_spend_per_farm_qtl": round(self.consumer_spend, 4),
            "absorption_per_farm_qtl": round(self.absorption, 4),
            "margin_absorption_per_farm_qtl": round(self.margin_absorption, 4),
            "cost_absorption_per_farm_qtl": round(self.cost_absorption, 4),
            "farmer_share_pct": round(self.farmer_share_pct, 4),
            "price_ratio_pct": round(self.price_ratio_pct, 4),
            "absorption_per_delivered_qtl": round(self.absorption_per_delivered_qtl, 4),
            "margin_share_of_absorption_pct": round(self.margin_share_pct, 4),
            "pass_through": round(self.pass_through, 6),
            "chain_length": self.chain_length,
            "intermediary_count": self.intermediary_count,
            "stages": [
                dict(
                    s.to_dict(),
                    take_pct_of_consumer_rupee=round(100.0 * s.take / spend, 4),
                )
                for s in self.stages
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# ValueChain
# ─────────────────────────────────────────────────────────────────────────────


class ValueChain:
    """An ordered sequence of :class:`Stage` objects, composed into ``A`` and ``B``."""

    __slots__ = ("stages", "name", "margin_scale", "platform_fee")

    def __init__(
        self,
        stages: Sequence[Stage],
        name: str = "traditional",
        margin_scale: float = 1.0,
        platform_fee: float = 0.0,
    ) -> None:
        if margin_scale < 0:
            raise ValueError(f"margin_scale must be >= 0, got {margin_scale}")
        seen = set()
        for st in stages:
            if st.key in seen:
                raise ValueError(f"duplicate stage key {st.key!r}")
            seen.add(st.key)
        self.stages: Tuple[Stage, ...] = tuple(stages)
        self.name = name
        self.margin_scale = float(margin_scale)
        # Bookkeeping only: the platform fee is also a normal (essential) stage,
        # so `effective_markup` derives it.  This attribute exists so callers can
        # rebuild an equivalent chain for a different lane without losing it.
        self.platform_fee = float(platform_fee)

    # -- construction --------------------------------------------------------

    @classmethod
    def from_dict(cls, payload: Dict) -> "ValueChain":
        stages = [Stage.from_dict(s) for s in payload.get("stages", [])]
        return cls(
            stages=stages,
            name=payload.get("name", "traditional"),
            margin_scale=float(payload.get("margin_scale", 1.0)),
        )

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "margin_scale": self.margin_scale,
            "stages": [s.to_dict() for s in self.stages],
        }

    def scaled(self, factor: float) -> "ValueChain":
        """Return a copy with every stage margin multiplied by ``factor``.

        Losses and handling costs are untouched: they are physical, not rent.
        """
        return ValueChain(
            self.stages, self.name, self.margin_scale * factor, self.platform_fee
        )

    def essential_only(self) -> "ValueChain":
        """The chain with rent-extraction layers removed.

        This is the structural claim of the whole solution: the produce still
        has to be graded, packed and moved, but it does not have to change
        hands five times.
        """
        return ValueChain(
            [s for s in self.stages if s.essential],
            name=f"{self.name}:direct",
            margin_scale=self.margin_scale,
            platform_fee=self.platform_fee,
        )

    def with_platform_fee(self, platform_fee_pct: float, key: str = "platform_fee") -> "ValueChain":
        """Append the platform's fee as the only margin in the direct channel."""
        fee = Stage(
            key=key,
            label_en="Platform fee",
            label_mr="प्लॅटफॉर्म शुल्क",
            label_hi="प्लेटफ़ॉर्म शुल्क",
            margin_pct=platform_fee_pct,
            kind="platform",
            essential=True,
            note="Replaces the entire margin stack of the traditional chain.",
        )
        return ValueChain(
            list(self.stages) + [fee],
            self.name,
            self.margin_scale,
            platform_fee_pct,
        )

    # -- composite scalars ---------------------------------------------------

    @property
    def A(self) -> float:
        """Composite multiplicative coefficient. Always ``> 0`` because loss < 1."""
        acc = 1.0
        for st in self.stages:
            acc *= st.A if self.margin_scale == 1.0 else st.scaled(self.margin_scale).A
        return acc

    @property
    def B(self) -> float:
        """Composite additive coefficient: ``Σ B_i · Π_{j>i} A_j``."""
        acc = 0.0
        for st in self.stages:
            s = st if self.margin_scale == 1.0 else st.scaled(self.margin_scale)
            acc = acc * s.A + s.B
        return acc

    @property
    def delivered_ratio(self) -> float:
        """Consumer quintals obtained from one farm-gate quintal."""
        w = 1.0
        for st in self.stages:
            w *= 1.0 - st.loss_pct
        return w

    @property
    def effective_markup(self) -> float:
        """``m_eff`` — markup on *farmer revenue per delivered quintal*.

        Derivation: with ``F = p_farm / w`` (farmer revenue per consumer
        quintal) and ``p_retail = A·p_farm + B = A·w·F + B``, the total price the
        consumer pays per consumer quintal is ``(A·w)·F + B``.  So the consumer's
        price is the farmer's revenue grossed up by ``A·w - 1`` plus the additive
        handling cost ``B``.  For a chain with no margins at all, ``A = 1/w`` and
        therefore ``m_eff = 0``: every rupee above the farmer's revenue is a real
        cost, not rent.
        """
        return self.A * self.delivered_ratio - 1.0

    @property
    def intermediary_count(self) -> int:
        return sum(1 for s in self.stages if not s.essential)

    @property
    def pass_through(self) -> float:
        """``d p_farm / d p_retail == 1 / A``.

        The answer to "when the shop price rises ₹1, how much reaches the
        grower?".  A five-stage vegetable chain typically lands near 0.55.
        """
        return 1.0 / self.A

    # -- forward / inverse ---------------------------------------------------

    def forward(self, farm_price: float) -> ChainResult:
        """Push ``farm_price`` through the chain and attribute every rupee.

        Raises
        ------
        ValueError
            if ``farm_price`` is not finite and non-negative.
        """
        if not math.isfinite(farm_price) or farm_price < 0:
            raise ValueError(f"farm_price must be finite and >= 0, got {farm_price}")

        qty = 1.0
        price = float(farm_price)
        results: List[StageResult] = []
        margin_total = 0.0
        cost_total = 0.0

        for st in self.stages:
            s = st if self.margin_scale == 1.0 else st.scaled(self.margin_scale)
            qty_in = qty
            price_in = price
            value_in = qty_in * price_in

            qty_out = qty_in * (1.0 - s.loss_pct)
            # Real handling cost is incurred on the quantity that survives.
            value_after_cost = value_in + qty_out * s.cost_per_qtl
            value_out = value_after_cost * (1.0 + s.margin_pct)

            cost_take = qty_out * s.cost_per_qtl
            margin_take = value_after_cost * s.margin_pct
            price_out = value_out / qty_out if qty_out > _EPS else float("inf")

            results.append(
                StageResult(
                    key=s.key,
                    label_en=s.label_en,
                    label_mr=s.label_mr,
                    label_hi=s.label_hi,
                    kind=s.kind,
                    essential=s.essential,
                    price_in=price_in,
                    price_out=price_out,
                    qty_in=qty_in,
                    qty_out=qty_out,
                    value_in=value_in,
                    value_out=value_out,
                    cost_take=cost_take,
                    margin_take=margin_take,
                    take=value_out - value_in,
                    margin_pct=s.margin_pct,
                    cost_per_qtl=s.cost_per_qtl,
                    loss_pct=s.loss_pct,
                    spoilage_qtl=qty_in - qty_out,
                    note=s.note,
                )
            )
            margin_total += margin_take
            cost_total += cost_take
            qty, price = qty_out, price_out

        retail = price
        consumer_spend = qty * retail
        absorption = consumer_spend - farm_price
        w = qty

        return ChainResult(
            chain_name=self.name,
            farm_price=float(farm_price),
            retail_price=retail,
            delivered_ratio=w,
            A=self.A,
            B=self.B,
            consumer_spend=consumer_spend,
            absorption=absorption,
            margin_absorption=margin_total,
            cost_absorption=cost_total,
            farmer_share_pct=(100.0 * farm_price / consumer_spend) if consumer_spend > _EPS else 0.0,
            price_ratio_pct=(100.0 * farm_price / retail) if retail > _EPS else 0.0,
            # Reported on the consumer's unit too, because "the farmer's price is
            # X% of the shop price" is the statistic everyone quotes and it is a
            # different number from farmer_share_pct (which is quantity-adjusted).
            absorption_per_delivered_qtl=retail - (farm_price / w if w > _EPS else 0.0),
            pass_through=1.0 / self.A,
            chain_length=len(self.stages),
            intermediary_count=self.intermediary_count,
            spoilage_pct=1.0 - w,
            stages=tuple(results),
        )

    def inverse(self, retail_price: float) -> float:
        """Farm-gate price implied by an observed retail price.

        ``p_farm = (p_retail - B) / A``.  May return a negative number when the
        observed retail price cannot even cover the chain's real handling costs
        — that is a genuine market signal (a glut), not a numerical error, so it
        is returned verbatim.  Use :meth:`implied_farm_price` if you want it
        clamped with an explicit flag.
        """
        if not math.isfinite(retail_price):
            raise ValueError(f"retail_price must be finite, got {retail_price}")
        return (retail_price - self.B) / self.A

    def implied_farm_price(self, retail_price: float) -> Tuple[float, str]:
        """Clamped inverse plus a status flag.

        Returns ``(price, status)`` where status is one of
        ``ok`` | ``glut`` (retail cannot cover real costs; clamped to 0).
        """
        raw = self.inverse(retail_price)
        if raw < 0:
            return 0.0, "glut"
        return raw, "ok"

    # -- misc ----------------------------------------------------------------

    def __len__(self) -> int:
        return len(self.stages)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ValueChain(name={self.name!r}, stages={len(self.stages)}, "
            f"A={self.A:.4f}, B={self.B:.2f}, w={self.delivered_ratio:.4f})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ValueChain):
            return NotImplemented
        return (
            self.stages == other.stages
            and self.name == other.name
            and abs(self.margin_scale - other.margin_scale) < 1e-15
        )


# ─────────────────────────────────────────────────────────────────────────────
# Calibration
# ─────────────────────────────────────────────────────────────────────────────

CALIBRATION_OK = "ok"
CALIBRATION_GLUT = "glut"
CALIBRATION_UNREACHABLE = "unreachable"


def calibrate_margin_scale(
    chain: ValueChain,
    farm_price: float,
    retail_price: float,
    lo: float = 0.0,
    hi: float = 25.0,
    tol: float = 1e-7,
    max_iter: int = 200,
) -> Tuple[float, str]:
    """Fit the margin scale ``λ`` so the chain reproduces an observed price pair.

    The *shape* of the margin stack (which layer takes how much relative to the
    others) comes from published value-chain studies; its *level* varies wildly
    by commodity, season and distance.  Rather than pretend otherwise, we keep
    the shape and solve for one scalar.

    **Why bisection is legitimate here.**  For a stage with margin ``m``,

        A_i(λ) = (1 + λ·m) / (1 - l)      increasing in λ
        B_i(λ) = (1 + λ·m) · c            increasing in λ

    for ``λ ≥ 0`` since ``m, c ≥ 0`` and ``l < 1``.  Products and sums of
    non-decreasing non-negative functions are non-decreasing, so
    ``f(λ) = A(λ)·p + B(λ) - p_retail`` is non-decreasing (strictly increasing
    if any stage has ``m > 0`` and ``p > 0``).  A monotone function on a closed
    interval is bracketed by its endpoints and bisection halves the bracket
    every step — it converges to ``tol`` in at most ``ceil(log2((hi-lo)/tol))``
    iterations, which is why ``max_iter=200`` is more than enough for any
    realistic bracket.

    Returns
    -------
    (λ, status)
        ``status`` is one of:

        ``ok``           the bracket contained a root; ``|f(λ)| <= tol``.
        ``glut``         even at ``λ = 0`` the chain's *real* costs exceed the
                         observed retail price.  Nothing is left for the farmer.
                         This is a real and important state (post-harvest gluts
                         really do destroy the entire margin stack) and it is
                         reported rather than hidden.  ``λ`` is returned as 0.
        ``unreachable``  even ``λ = hi`` cannot reach the observed retail price.
                         Returned at the ceiling so callers can widen ``hi``.
    """
    if farm_price < 0 or retail_price < 0:
        raise ValueError("prices must be non-negative")
    if hi <= lo:
        raise ValueError(f"hi must exceed lo (got lo={lo}, hi={hi})")

    def resid(lam: float) -> float:
        return chain.scaled(lam).forward(farm_price).retail_price - retail_price

    f_lo = resid(lo)
    if f_lo >= 0:
        # Zero margins already overshoot: the chain's physical costs alone
        # explain the whole retail price (or more).
        return 0.0, CALIBRATION_GLUT

    f_hi = resid(hi)
    if f_hi <= 0:
        return hi, CALIBRATION_UNREACHABLE

    a, b = lo, hi
    for _ in range(max_iter):
        mid = 0.5 * (a + b)
        if b - a <= tol:
            break
        if resid(mid) < 0:
            a = mid
        else:
            b = mid
    lam = 0.5 * (a + b)
    return lam, CALIBRATION_OK


# ─────────────────────────────────────────────────────────────────────────────
# Reference profiles
# ─────────────────────────────────────────────────────────────────────────────
#
# These are PLANNING ASSUMPTIONS, not measurements.  They encode the structure
# of the Indian horticulture chain that is consistently reported in the
# literature (village aggregator → commission agent → wholesaler → distributor
# → retailer).  Absolute levels vary by crop, season and lane, which is exactly
# why :func:`calibrate_margin_scale` re-fits them against observed mandi and
# retail prices at run time.  Every number below is overridable from the
# ``value_chain_profiles`` table.
# ─────────────────────────────────────────────────────────────────────────────


def _traditional_stages(
    assembly_cost: float,
    mandi_cost: float,
    wholesale_cost: float,
    distribution_cost: float,
    retail_cost: float,
    retail_loss: float,
) -> List[Stage]:
    return [
        Stage(
            key="village_aggregator",
            label_en="Village trader / aggregator",
            label_mr="गाव व्यापारी",
            label_hi="गाँव व्यापारी",
            margin_pct=0.05,
            cost_per_qtl=assembly_cost,
            loss_pct=0.02,
            kind="assembly",
            essential=False,
            note="Buys at the farm gate, assembles lots, extends credit.",
        ),
        Stage(
            key="commission_agent",
            label_en="Commission agent (arhatiya)",
            label_mr="आडत दलाल",
            label_hi="आढ़त दलाल",
            margin_pct=0.06,
            cost_per_qtl=mandi_cost,
            loss_pct=0.015,
            kind="intermediary",
            essential=False,
            note="APMC commission, mandi cess, unloading labour.",
        ),
        Stage(
            key="wholesaler",
            label_en="Wholesaler (mandi → city)",
            label_mr="घाऊक व्यापारी",
            label_hi="थोक व्यापारी",
            margin_pct=0.10,
            cost_per_qtl=wholesale_cost,
            loss_pct=0.03,
            kind="intermediary",
            essential=False,
            note="Long-haul freight to the consumption centre plus price risk.",
        ),
        Stage(
            key="distributor",
            label_en="Distributor / sub-wholesaler",
            label_mr="वितरक",
            label_hi="वितरक",
            margin_pct=0.08,
            cost_per_qtl=distribution_cost,
            loss_pct=0.025,
            kind="intermediary",
            essential=False,
            note="Breaks bulk, delivers to retail outlets.",
        ),
        Stage(
            key="retailer",
            label_en="Retailer",
            label_mr="किरकोळ व्यापारी",
            label_hi="खुदरा व्यापारी",
            margin_pct=0.18,
            cost_per_qtl=retail_cost,
            loss_pct=retail_loss,
            kind="retail",
            essential=False,
            note="Shop rent, labour, packaging, unsold stock.",
        ),
    ]


def _direct_stages(pack_cost: float) -> List[Stage]:
    """The stages a direct channel genuinely cannot avoid.

    Grading and packing at the FPO, then the freight itself.  Both are
    ``essential``: they are physical work, not rent.

    Note on where the loss sits: ALL of the direct channel's in-transit spoilage
    is placed on the freight stage, and that stage's ``cost_per_qtl`` is then
    grossed up by ``1 / (1 - loss)``.  The reason is unit hygiene.  Freight is
    charged on what is *loaded*, but a chain stage's ``cost_per_qtl`` is charged
    per quintal *surviving* that stage.  Without the gross-up the model
    under-charges freight by the spoilage factor and quietly overstates the
    surplus.  With it, the chain's own algebra gives exactly

        w · p_consumer = (1 + m) · (p_farm + T)

    where ``T`` is the total logistics cost per farm-gate quintal — which is
    the identity :mod:`direct.surplus` is written against.
    """
    return [
        Stage(
            key="fpo_grading_packing",
            label_en="FPO grading & packing",
            label_mr="एफपीओ प्रतवारी व पॅकिंग",
            label_hi="एफपीओ ग्रेडिंग व पैकिंग",
            margin_pct=0.0,
            cost_per_qtl=pack_cost,
            loss_pct=0.0,
            kind="assembly",
            essential=True,
            note="Sorting, grading and crating at the collection centre. "
                 "Rejects are sold separately, so no load is lost here.",
        ),
        Stage(
            key="direct_freight",
            label_en="Direct freight & last mile",
            label_mr="थेट वाहतूक",
            label_hi="सीधी ढुलाई",
            margin_pct=0.0,
            cost_per_qtl=0.0,  # filled per-lane, already grossed up for loss
            loss_pct=0.015,
            kind="logistics",
            essential=True,
            note="Farm collection → consumer drop, one leg, no re-handling.",
        ),
    ]


def default_traditional_chain(category: str = "vegetable") -> ValueChain:
    """Reference traditional chain for a commodity category.

    ``vegetable``/``oilseed``/``cereal`` differ mainly in spoilage and in how
    much handling they need.  Perishables rot more and are handled more gently.
    """
    if category == "vegetable":
        stages = _traditional_stages(40.0, 55.0, 130.0, 80.0, 95.0, 0.06)
    elif category == "oilseed":
        stages = _traditional_stages(30.0, 45.0, 110.0, 70.0, 60.0, 0.015)
    elif category == "cereal":
        stages = _traditional_stages(28.0, 42.0, 100.0, 65.0, 55.0, 0.01)
    else:
        stages = _traditional_stages(35.0, 50.0, 115.0, 72.0, 78.0, 0.035)
    return ValueChain(stages, name=f"traditional:{category}")


def default_direct_chain(
    category: str = "vegetable",
    platform_fee_pct: float = 0.03,
    freight_cost_per_qtl: float = 0.0,
) -> ValueChain:
    """Reference direct channel: grading + freight + a single platform fee.

    Parameters
    ----------
    freight_cost_per_qtl
        Freight + handling + last mile, ₹ per quintal **loaded**.  It is
        grossed up by ``1 / (1 - loss)`` inside the freight stage so that the
        chain charges the full cost of moving produce that never arrives.
    """
    pack_cost = {"vegetable": 38.0, "oilseed": 26.0, "cereal": 24.0}.get(category, 30.0)
    stages = _direct_stages(pack_cost)
    freight_stage = stages[-1]
    stages[-1] = replace(
        freight_stage, cost_per_qtl=freight_cost_per_qtl / (1.0 - freight_stage.loss_pct)
    )
    return ValueChain(stages, name=f"direct:{category}").with_platform_fee(platform_fee_pct)


def build_direct_chain(
    category: str = "vegetable",
    platform_fee_pct: float = 0.03,
    freight_cost_per_qtl: float = 0.0,
) -> ValueChain:
    """Alias kept for readability at call sites."""
    return default_direct_chain(category, platform_fee_pct, freight_cost_per_qtl)


# Optional convenience: a chain with no stages at all (identity), used in tests
# to isolate individual behaviours.
IDENTITY_CHAIN = ValueChain([], name="identity")
