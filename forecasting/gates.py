"""
forecasting/gates.py — Numerical promotion gates for forecast model selection.

Gate outcomes
-------------
Each gate has three mutually exclusive outcomes (GateOutcome enum):

  PASS  — evidence is sufficient AND the metric satisfies the threshold.
          Only this outcome permits promotion.

  SKIP  — evidence is insufficient to evaluate (n < minimum).
          This is NOT a pass. A skipped gate blocks promotion identically
          to a FAIL. "No evidence" does not mean "no problem."

  FAIL  — evidence is sufficient AND the metric violates the threshold.

Promotion contract
------------------
select_model() enforces the contract:

  * Promote the candidate ONLY when all gates are PASS.
  * Retain the current default model on any SKIP or FAIL.
  * Log the reason for every non-PASS gate.

This contract is tested directly in test_gates.py — not via docstring.

Gate definitions (per approved plan):
  G2: Pool-aggregate winsorized MAPE ≤ 20%  (n ≥ G2_MIN_PREDICTIONS)
  G3: Pool-aggregate directional accuracy ≥ 55%  (n ≥ G3_MIN_DIRECTIONAL)
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

# Thresholds — tests import these constants; change only here.
G2_MAPE_THRESHOLD    = 0.20   # 20 % winsorized MAPE (pool aggregate)
G3_DA_THRESHOLD      = 0.55   # 55 % directional accuracy (pool aggregate)
G2_MIN_PREDICTIONS   = 10     # minimum pool size required to evaluate G2
G3_MIN_DIRECTIONAL   = 5      # minimum directional samples required to evaluate G3

# Model name used when no candidate passes gates — the safe default.
DEFAULT_MODEL = "blend"


class GateOutcome(enum.Enum):
    PASS = "pass"   # metric satisfies threshold
    SKIP = "skip"   # insufficient evidence — blocks promotion
    FAIL = "fail"   # metric violates threshold — blocks promotion

    @property
    def blocks_promotion(self) -> bool:
        """Any outcome other than PASS blocks promotion."""
        return self is not GateOutcome.PASS


@dataclass
class SingleGateResult:
    name:      str
    outcome:   GateOutcome
    value:     Optional[float]   # actual metric value; None when skipped
    threshold: float
    reason:    str

    # Convenience alias kept for backward compatibility with callers that
    # checked .passed; now True only when outcome is PASS.
    @property
    def passed(self) -> bool:
        return self.outcome is GateOutcome.PASS


@dataclass
class GateResult:
    """Aggregated result of all gates for a given model."""
    model:    str
    gates:    List[SingleGateResult] = field(default_factory=list)
    notes:    List[str]              = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        """True ONLY when every gate has outcome == PASS (no skips, no fails)."""
        return bool(self.gates) and all(g.outcome is GateOutcome.PASS for g in self.gates)

    @property
    def blocking_gates(self) -> List[SingleGateResult]:
        return [g for g in self.gates if g.outcome.blocks_promotion]

    def to_dict(self) -> dict:
        return {
            "model":    self.model,
            "all_pass": self.all_pass,
            "gates": [
                {
                    "name":      g.name,
                    "outcome":   g.outcome.value,
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
    Evaluate G2 and G3 for *model_name* using pool-aggregate metrics.

    Returns a GateResult whose .all_pass is True ONLY when both gates are
    explicitly PASS (not SKIP, not FAIL). Callers MUST NOT equate SKIP
    with permission to promote — use select_model() to enforce this.
    """
    aggregate: Dict[str, Any] = getattr(backtest_report, "aggregate", {}) or {}
    model_agg = aggregate.get(model_name) or {}

    notes: List[str] = []
    gate_results: List[SingleGateResult] = []

    # ── G2: Winsorized MAPE ───────────────────────────────────────────────────
    mape_val = model_agg.get("mape_winsorized")
    n_preds  = model_agg.get("n_predictions") or 0

    if mape_val is None or n_preds < G2_MIN_PREDICTIONS:
        g2_note = (
            f"G2 SKIP: mape_winsorized={mape_val!r}, "
            f"n_predictions={n_preds} < minimum {G2_MIN_PREDICTIONS}. "
            "Insufficient evidence — promotion blocked."
        )
        notes.append(g2_note)
        g2_result = SingleGateResult(
            name="G2_MAPE",
            outcome=GateOutcome.SKIP,
            value=mape_val,
            threshold=G2_MAPE_THRESHOLD,
            reason=g2_note,
        )
    else:
        outcome = GateOutcome.PASS if mape_val <= G2_MAPE_THRESHOLD else GateOutcome.FAIL
        g2_result = SingleGateResult(
            name="G2_MAPE",
            outcome=outcome,
            value=round(mape_val, 4),
            threshold=G2_MAPE_THRESHOLD,
            reason=(
                f"MAPE {mape_val:.1%} "
                f"{'≤' if outcome is GateOutcome.PASS else '>'} "
                f"{G2_MAPE_THRESHOLD:.1%}"
            ),
        )
    gate_results.append(g2_result)

    # ── G3: Directional Accuracy ──────────────────────────────────────────────
    # Pool hits/folds across all per-pair ModelResults for this model.
    total_hits  = 0
    total_folds = 0
    for pair_result in getattr(backtest_report, "per_pair", []):
        for mr in getattr(pair_result, "models", []):
            if getattr(mr, "model", None) == model_name:
                total_hits  += getattr(mr, "directional_hits",  0) or 0
                total_folds += getattr(mr, "directional_folds", 0) or 0

    if total_folds < G3_MIN_DIRECTIONAL:
        g3_note = (
            f"G3 SKIP: {total_folds} directional samples < minimum {G3_MIN_DIRECTIONAL}. "
            "Insufficient evidence — promotion blocked."
        )
        notes.append(g3_note)
        g3_result = SingleGateResult(
            name="G3_DA",
            outcome=GateOutcome.SKIP,
            value=None,
            threshold=G3_DA_THRESHOLD,
            reason=g3_note,
        )
    else:
        da_val  = total_hits / total_folds
        outcome = GateOutcome.PASS if da_val >= G3_DA_THRESHOLD else GateOutcome.FAIL
        g3_result = SingleGateResult(
            name="G3_DA",
            outcome=outcome,
            value=round(da_val, 4),
            threshold=G3_DA_THRESHOLD,
            reason=(
                f"DA {da_val:.1%} "
                f"{'≥' if outcome is GateOutcome.PASS else '<'} "
                f"{G3_DA_THRESHOLD:.1%} ({total_hits}/{total_folds} folds)"
            ),
        )
    gate_results.append(g3_result)

    result = GateResult(model=model_name, gates=gate_results, notes=notes)

    if not result.all_pass:
        logger.info(
            "gate_evaluation_blocking",
            model=model_name,
            all_pass=False,
            blocking=[g.name for g in result.blocking_gates],
        )

    return result


def select_model(gate_result: GateResult, current_model: str = DEFAULT_MODEL) -> str:
    """
    Enforce the promotion contract: return the model to use in production.

    Returns
    -------
    str
        The candidate model name if ALL gates PASS.
        The current_model (default: DEFAULT_MODEL) on any SKIP or FAIL.

    This function is the ONLY correct way to act on a GateResult.
    Do not read gate_result.all_pass and branch on it independently —
    always call this function so the retention policy is enforced uniformly.
    """
    if gate_result.all_pass:
        logger.info("gate_promotion_approved", model=gate_result.model)
        return gate_result.model

    blocking = gate_result.blocking_gates
    logger.info(
        "gate_promotion_blocked_retaining_current",
        candidate=gate_result.model,
        current=current_model,
        blocking_gates=[
            {"name": g.name, "outcome": g.outcome.value, "reason": g.reason}
            for g in blocking
        ],
    )
    return current_model
