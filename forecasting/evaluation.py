"""
forecasting/evaluation.py — Forecast accuracy metrics.

All functions are pure math: no DB, no ML, no network.  They operate on plain
Python lists so they can be called from the backtest harness, unit tests, and
any future evaluation script without side-effects.

Conventions
-----------
* actuals / preds : parallel sequences of floats.  len(actuals) == len(preds).
* Any pair where actuals[i] == 0 is *skipped* for MAPE (division by zero would
  be meaningless and poison the aggregate).
* NaN / None / missing pairs are omitted from every metric (caller may log them
  separately via the NaN-rate column in BacktestReport).
"""
from __future__ import annotations

import math
from typing import Sequence, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_pairs(
    actuals: Sequence[float],
    preds: Sequence[float],
) -> list[tuple[float, float]]:
    """Return (actual, pred) pairs where both values are finite numbers."""
    pairs = []
    for a, p in zip(actuals, preds):
        if a is None or p is None:
            continue
        try:
            af, pf = float(a), float(p)
        except (TypeError, ValueError):
            continue
        if math.isfinite(af) and math.isfinite(pf):
            pairs.append((af, pf))
    return pairs


# ---------------------------------------------------------------------------
# Public metric functions
# ---------------------------------------------------------------------------

def mae(actuals: Sequence[float], preds: Sequence[float]) -> float:
    """
    Mean Absolute Error.

    Returns float('nan') when no valid pairs exist.

    .. math::
        MAE = \\frac{1}{n} \\sum_{i=1}^{n} |a_i - p_i|
    """
    pairs = _valid_pairs(actuals, preds)
    if not pairs:
        return float("nan")
    return sum(abs(a - p) for a, p in pairs) / len(pairs)


def mape_winsorized(
    actuals: Sequence[float],
    preds: Sequence[float],
    cap: float = 100.0,
) -> float:
    """
    Winsorized Mean Absolute Percentage Error.

    Per-observation APE is clipped to ``cap`` (default 100 %) before averaging.
    Observations where ``actual == 0`` are skipped entirely (undefined MAPE).

    This prevents a single absurd outlier (e.g. actual=1, pred=10_000 → raw APE
    9_900%) from dominating the aggregate while still penalising bad forecasts
    hard — any prediction more than 100% off contributes exactly ``cap``.

    Returns float('nan') when no valid non-zero actuals exist.

    .. math::
        MAPE_w = \\frac{1}{n} \\sum_{i: a_i \\neq 0} \\min\\left(
            \\frac{|a_i - p_i|}{|a_i|} \\times 100,\\ cap
        \\right)
    """
    pairs = _valid_pairs(actuals, preds)
    errors = []
    for a, p in pairs:
        if a == 0.0:
            continue  # skip: MAPE undefined
        raw_ape = abs(a - p) / abs(a) * 100.0
        errors.append(min(raw_ape, cap))
    if not errors:
        return float("nan")
    return sum(errors) / len(errors)


def directional_accuracy(
    last_train_price: float,
    fold_preds: Sequence[float],
    fold_actuals: Sequence[float],
    flat_eps: float = 0.01,
) -> Tuple[int, int]:
    """
    Count folds where the *direction* of price movement was correctly predicted.

    A fold contributes to the denominator only if the actual price change
    (actual − last_train_price) is non-trivial, i.e.
    ``|change| / last_train_price > flat_eps``.  Flat folds (< 1% move by
    default) are excluded: there is no signal to evaluate.

    Parameters
    ----------
    last_train_price : float
        The last observed price in the training window (the anchor).
    fold_preds : sequence of float
        One predicted price per fold (day-1 prediction of each fold).
    fold_actuals : sequence of float
        One actual price per fold (day-1 realisation of each fold).
    flat_eps : float
        Fractional threshold below which a fold is considered "flat" and
        excluded from the denominator.  Default 0.01 = 1 %.

    Returns
    -------
    (hits, folds_considered) : tuple[int, int]
        ``folds_considered`` is the number of non-flat folds.
        Directional accuracy = hits / folds_considered (caller computes ratio).
    """
    if last_train_price == 0.0:
        return 0, 0

    hits = 0
    considered = 0
    pairs = _valid_pairs(fold_actuals, fold_preds)  # parallel; NaN already removed
    for actual, pred in pairs:
        actual_change = actual - last_train_price
        if abs(actual_change) / abs(last_train_price) <= flat_eps:
            continue  # flat fold — excluded from denominator
        considered += 1
        pred_change = pred - last_train_price
        # Same sign ↔ correct direction; zero-pred counts as "no prediction" → miss
        if actual_change > 0 and pred_change > 0:
            hits += 1
        elif actual_change < 0 and pred_change < 0:
            hits += 1

    return hits, considered


def interval_coverage(
    uppers: Sequence[float],
    lowers: Sequence[float],
    actuals: Sequence[float],
) -> float:
    """
    Fraction of actuals that fall within the predicted interval [lower, upper].

    Returns 1.0 when the sequences are empty (vacuously true, consistent with
    coverage meaning "no violations").  Returns float('nan') when all triples
    contain non-finite values.

    .. math::
        \\text{coverage} = \\frac{1}{n} \\sum_{i=1}^n
            \\mathbf{1}[lower_i \\le actual_i \\le upper_i]
    """
    covered = 0
    total = 0
    for lo, hi, a in zip(lowers, uppers, actuals):
        if lo is None or hi is None or a is None:
            continue
        try:
            lf, hf, af = float(lo), float(hi), float(a)
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(lf) and math.isfinite(hf) and math.isfinite(af)):
            continue
        total += 1
        if lf <= af <= hf:
            covered += 1

    if total == 0:
        return 1.0  # vacuously covered; caller may treat as N/A
    return covered / total
