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
  G2: A candidate (feature_ols or holt_winters) must beat both MA and OLS 
      on aggregate winsorized MAPE.
  G3: GBM must beat the explicitly identified incumbent on aggregate 
      winsorized MAPE, while its directional accuracy is no more than 
      2 percentage points lower.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

# Minimums — tests import these constants; change only here.
MIN_PREDICTIONS   = 10     # minimum pool size required to evaluate MAPE
MIN_DIRECTIONAL   = 5      # minimum directional samples required to evaluate DA

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
    threshold: Optional[float]
    reason:    str

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


def _get_da(backtest_report: Any, model_name: str) -> Tuple[Optional[float], int, int]:
    total_hits  = 0
    total_folds = 0
    for pair_result in getattr(backtest_report, "per_pair", []):
        for mr in getattr(pair_result, "models", []):
            if getattr(mr, "model", None) == model_name:
                total_hits  += getattr(mr, "directional_hits",  0) or 0
                total_folds += getattr(mr, "directional_folds", 0) or 0
    if total_folds == 0:
        return None, 0, 0
    return total_hits / total_folds, total_hits, total_folds


def evaluate_gates(
    backtest_report: Any,
    candidate_name: str,
    incumbent_name: str = DEFAULT_MODEL,
) -> GateResult:
    """
    Evaluate comparative gates for *candidate_name*.
    Returns a GateResult whose .all_pass is True ONLY when comparative gates PASS.
    """
    aggregate: Dict[str, Any] = getattr(backtest_report, "aggregate", {}) or {}
    cand_agg = aggregate.get(candidate_name) or {}

    notes: List[str] = []
    gate_results: List[SingleGateResult] = []

    cand_mape = cand_agg.get("mape_winsorized")
    cand_preds = cand_agg.get("n_predictions") or 0

    if candidate_name in ("feature_ols", "holt_winters"):
        # G2: Beat MA and OLS on MAPE
        ma_agg = aggregate.get("ma") or {}
        ols_agg = aggregate.get("ols") or {}
        ma_mape = ma_agg.get("mape_winsorized")
        ols_mape = ols_agg.get("mape_winsorized")
        
        if cand_mape is None or ma_mape is None or ols_mape is None or cand_preds < MIN_PREDICTIONS:
            note = f"G2 SKIP: insufficient predictions or missing MAPE (preds={cand_preds})."
            notes.append(note)
            gate_results.append(SingleGateResult("G2", GateOutcome.SKIP, cand_mape, None, note))
        else:
            if cand_mape < ma_mape and cand_mape < ols_mape:
                gate_results.append(SingleGateResult("G2", GateOutcome.PASS, cand_mape, min(ma_mape, ols_mape), "Candidate beats MA and OLS"))
            else:
                gate_results.append(SingleGateResult("G2", GateOutcome.FAIL, cand_mape, min(ma_mape, ols_mape), f"Candidate {cand_mape} did not beat MA ({ma_mape}) and OLS ({ols_mape})"))

    elif candidate_name == "gbm":
        # G3: Beat incumbent on MAPE, DA drop <= 2%
        inc_agg = aggregate.get(incumbent_name) or {}
        inc_mape = inc_agg.get("mape_winsorized")
        
        cand_da, cand_hits, cand_folds = _get_da(backtest_report, candidate_name)
        inc_da, inc_hits, inc_folds = _get_da(backtest_report, incumbent_name)
        
        if cand_mape is None or inc_mape is None or cand_preds < MIN_PREDICTIONS:
            note = f"G3 MAPE SKIP: insufficient predictions or missing MAPE (preds={cand_preds})."
            notes.append(note)
            gate_results.append(SingleGateResult("G3_MAPE", GateOutcome.SKIP, cand_mape, inc_mape, note))
        else:
            if cand_mape < inc_mape:
                gate_results.append(SingleGateResult("G3_MAPE", GateOutcome.PASS, cand_mape, inc_mape, "GBM beats incumbent MAPE"))
            else:
                gate_results.append(SingleGateResult("G3_MAPE", GateOutcome.FAIL, cand_mape, inc_mape, f"GBM {cand_mape} did not beat incumbent {inc_mape}"))
                
        if cand_da is None or inc_da is None or cand_folds < MIN_DIRECTIONAL or inc_folds < MIN_DIRECTIONAL:
            note = f"G3 DA SKIP: insufficient directional samples (cand={cand_folds}, inc={inc_folds})."
            notes.append(note)
            gate_results.append(SingleGateResult("G3_DA", GateOutcome.SKIP, cand_da, None, note))
        else:
            threshold = inc_da - 0.02
            if cand_da >= threshold:
                gate_results.append(SingleGateResult("G3_DA", GateOutcome.PASS, cand_da, threshold, "GBM DA within 2% of incumbent"))
            else:
                gate_results.append(SingleGateResult("G3_DA", GateOutcome.FAIL, cand_da, threshold, f"GBM DA {cand_da:.1%} is lower than incumbent {inc_da:.1%} - 2%"))
    else:
        # Default models or unrecognized models automatically skip (cannot be promoted via G2/G3).
        gate_results.append(SingleGateResult("UNKNOWN", GateOutcome.SKIP, None, None, f"No gate rules defined for {candidate_name}"))

    result = GateResult(model=candidate_name, gates=gate_results, notes=notes)

    if not result.all_pass:
        logger.info(
            "gate_evaluation_blocking",
            model=candidate_name,
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
