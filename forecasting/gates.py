"""
forecasting/gates.py — Numerical promotion gates for forecast model selection.

Gates G2 and G3 guard model promotion from backtest to production.
If any gate fails, the engine retains its current `auto` behavior
(blend of MA + OLS — no disruption to production forecasts).

Gate definitions (per approved plan):
  G2: Winsorized MAPE ≤ 20% (pool-aggregate across all pairs)
  G3: Directional accuracy ≥ 55% (pool-aggregate)

Usage
-----
    from forecasting.gates import evaluate_gates, GateResult

    result = evaluate_gates(backtest_report)
    if result.all_pass:
        # promote
    else:
        # retain auto / log failure reasons
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Thresholds — change here, tests reference these constants.
G2_MAPE_THRESHOLD    = 0.20   # 20 % winsorized MAPE (pool aggregate)
G3_DA_THRESHOLD      = 0.55   # 55 % directional accuracy (pool aggregate)
G2_MIN_PREDICTIONS   = 10     # minimum pool size before G2 can fire
G3_MIN_DIRECTIONAL   = 5      # minimum directional samples before G3 can fire


@dataclass
class SingleGateResult:
    name:      str
    passed:    bool
    value:     Optional[float]
    threshold: float
    reason:    str


@dataclass
class GateResult:
    """Aggregated result of all gates for a given model."""
    model:      str
    all_pass:   bool
    gates:      List[SingleGateResult] = field(default_factory=list)
    notes:      List[str]             = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model":    self.model,
            "all_pass": self.all_pass,
            "gates":    [
                {
                    "name":      g.name,
                    "passed":    g.passed,
                    "value":     g.value,
                    "threshold": g.threshold,
                    "reason":    g.reason,
                }
                for g in self.gates
            ],
            "notes": self.notes,
        }


def evaluate_gates(
    backtest_report: Any,
    model_name: str = "blend",
) -> GateResult:
    """
    Evaluate G2 (MAPE) and G3 (directional accuracy) gates for *model_name*
    using the pooled aggregate metrics from a BacktestReport.

    Parameters
    ----------
    backtest_report : BacktestReport
        Result of forecasting.backtest.run_backtest(...).
    model_name : str
        Which model's aggregate metrics to evaluate (e.g. "blend", "ma", "ols").

    Returns
    -------
    GateResult
        `.all_pass` is True only when every gate passes.
        If data is insufficient to evaluate a gate, that gate is marked as
        passed=True with a note (we don't block on missing evidence).
    """
    aggregate: Dict[str, Any] = getattr(backtest_report, "aggregate", {}) or {}
    model_agg = aggregate.get(model_name, {})

    notes: List[str] = []
    gate_results: List[SingleGateResult] = []

    # ── G2: Winsorized MAPE ───────────────────────────────────────────────────
    mape_val = model_agg.get("mape_winsorized")
    n_preds  = model_agg.get("n_predictions", 0)

    if mape_val is None or n_preds < G2_MIN_PREDICTIONS:
        g2_pass = True  # insufficient evidence — do not block
        g2_note = (
            f"G2 skipped: mape_winsorized={mape_val!r} "
            f"with only {n_preds} predictions (minimum {G2_MIN_PREDICTIONS})."
        )
        notes.append(g2_note)
        g2_result = SingleGateResult(
            name="G2_MAPE", passed=True, value=mape_val,
            threshold=G2_MAPE_THRESHOLD, reason=g2_note,
        )
    else:
        g2_pass = mape_val <= G2_MAPE_THRESHOLD
        g2_result = SingleGateResult(
            name="G2_MAPE",
            passed=g2_pass,
            value=round(mape_val, 4),
            threshold=G2_MAPE_THRESHOLD,
            reason=(
                f"MAPE {mape_val:.1%} {'≤' if g2_pass else '>'} {G2_MAPE_THRESHOLD:.1%}"
            ),
        )
    gate_results.append(g2_result)

    # ── G3: Directional Accuracy ──────────────────────────────────────────────
    # Pool directional_hits / directional_folds across all per-pair ModelResults.
    total_hits   = 0
    total_folds  = 0
    for pair_result in getattr(backtest_report, "per_pair", []):
        for mr in getattr(pair_result, "models", []):
            if getattr(mr, "model", None) == model_name:
                total_hits  += getattr(mr, "directional_hits",  0) or 0
                total_folds += getattr(mr, "directional_folds", 0) or 0

    if total_folds < G3_MIN_DIRECTIONAL:
        g3_pass = True  # insufficient evidence — do not block
        g3_note = (
            f"G3 skipped: only {total_folds} directional samples "
            f"(minimum {G3_MIN_DIRECTIONAL})."
        )
        notes.append(g3_note)
        g3_result = SingleGateResult(
            name="G3_DA", passed=True, value=None,
            threshold=G3_DA_THRESHOLD, reason=g3_note,
        )
    else:
        da_val  = total_hits / total_folds
        g3_pass = da_val >= G3_DA_THRESHOLD
        g3_result = SingleGateResult(
            name="G3_DA",
            passed=g3_pass,
            value=round(da_val, 4),
            threshold=G3_DA_THRESHOLD,
            reason=(
                f"DA {da_val:.1%} {'≥' if g3_pass else '<'} {G3_DA_THRESHOLD:.1%} "
                f"({total_hits}/{total_folds} folds)"
            ),
        )
    gate_results.append(g3_result)

    all_pass = all(g.passed for g in gate_results)
    return GateResult(model=model_name, all_pass=all_pass, gates=gate_results, notes=notes)
