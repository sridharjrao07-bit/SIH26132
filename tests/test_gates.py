"""
Tests for forecasting.gates

Covers:
  - GateOutcome semantics (PASS/SKIP/FAIL)
  - G2 and G3 individual gate evaluation
  - select_model() — the enforced selection path
  - Critical contract: SKIP blocks promotion (not a pass)
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


from forecasting.gates import (
    GateOutcome,
    evaluate_gates,
    select_model,
    DEFAULT_MODEL,
    MIN_PREDICTIONS,
)


# ── Minimal stub types ────────────────────────────────────────────────────────

@dataclass
class _ModelResult:
    model:             str
    directional_hits:  Optional[int]   = None
    directional_folds: Optional[int]   = None


@dataclass
class _PairResult:
    market_id:    str
    commodity_id: str
    n_obs:        int
    models:       List[_ModelResult] = field(default_factory=list)


@dataclass
class _BacktestReport:
    aggregate: Dict[str, Any]
    per_pair:  List[_PairResult] = field(default_factory=list)


def _report_for_g2(cand: str, cand_mape: Optional[float], ma_mape: Optional[float], ols_mape: Optional[float], n_preds: int):
    return _BacktestReport(
        aggregate={
            cand: {"mape_winsorized": cand_mape, "n_predictions": n_preds},
            "ma": {"mape_winsorized": ma_mape, "n_predictions": n_preds},
            "ols": {"mape_winsorized": ols_mape, "n_predictions": n_preds},
        }
    )

def _report_for_g3(cand_mape: float, inc_mape: float, cand_hits: int, cand_folds: int, inc_hits: int, inc_folds: int, n_preds: int, incumbent: str = "blend"):
    pair = _PairResult(
        market_id="m1", commodity_id="c1", n_obs=100,
        models=[
            _ModelResult(model="gbm", directional_hits=cand_hits, directional_folds=cand_folds),
            _ModelResult(model=incumbent, directional_hits=inc_hits, directional_folds=inc_folds)
        ],
    )
    return _BacktestReport(
        aggregate={
            "gbm": {"mape_winsorized": cand_mape, "n_predictions": n_preds},
            incumbent: {"mape_winsorized": inc_mape, "n_predictions": n_preds},
        },
        per_pair=[pair]
    )

# ── GateOutcome contract ──────────────────────────────────────────────────────

def test_only_pass_does_not_block_promotion():
    assert not GateOutcome.PASS.blocks_promotion
    assert GateOutcome.SKIP.blocks_promotion
    assert GateOutcome.FAIL.blocks_promotion


# ── G2 Tests ─────────────────────────────────────────────────────────────────

def test_g2_pass():
    report = _report_for_g2("feature_ols", 0.15, 0.20, 0.25, 50)
    res = evaluate_gates(report, "feature_ols")
    assert res.all_pass is True
    assert res.gates[0].outcome == GateOutcome.PASS

def test_g2_fail_one():
    # Beats OLS but not MA
    report = _report_for_g2("feature_ols", 0.22, 0.20, 0.25, 50)
    res = evaluate_gates(report, "feature_ols")
    assert res.all_pass is False
    assert res.gates[0].outcome == GateOutcome.FAIL

def test_g2_skip():
    report = _report_for_g2("feature_ols", 0.15, 0.20, 0.25, MIN_PREDICTIONS - 1)
    res = evaluate_gates(report, "feature_ols")
    assert res.all_pass is False
    assert res.gates[0].outcome == GateOutcome.SKIP

# ── G3 Tests ─────────────────────────────────────────────────────────────────

def test_g3_pass():
    # gbm beats inc MAPE (0.15 < 0.20)
    # gbm DA is 50%, inc DA is 51% (50 >= 51 - 2)
    report = _report_for_g3(0.15, 0.20, 50, 100, 51, 100, 50)
    res = evaluate_gates(report, "gbm")
    assert res.all_pass is True

def test_g3_fail_mape():
    # gbm worse than inc MAPE (0.25 > 0.20)
    # DA passes
    report = _report_for_g3(0.25, 0.20, 50, 100, 51, 100, 50)
    res = evaluate_gates(report, "gbm")
    assert res.all_pass is False
    assert any(g.name == "G3_MAPE" and g.outcome == GateOutcome.FAIL for g in res.gates)

def test_g3_fail_da():
    # gbm beats inc MAPE (0.15 < 0.20)
    # gbm DA is 40%, inc DA is 50% (40 < 50 - 2)
    report = _report_for_g3(0.15, 0.20, 40, 100, 50, 100, 50)
    res = evaluate_gates(report, "gbm")
    assert res.all_pass is False
    assert any(g.name == "G3_DA" and g.outcome == GateOutcome.FAIL for g in res.gates)

def test_g3_skip_da():
    # DA folds too small
    report = _report_for_g3(0.15, 0.20, 2, 4, 3, 4, 50)
    res = evaluate_gates(report, "gbm")
    assert res.all_pass is False
    assert any(g.name == "G3_DA" and g.outcome == GateOutcome.SKIP for g in res.gates)


# ── select_model ──────────────────────────────────────────────────────────────

def test_select_model_promotes_when_all_gates_pass():
    report = _report_for_g2("feature_ols", 0.15, 0.20, 0.25, 50)
    res = evaluate_gates(report, "feature_ols")
    selected = select_model(res, current_model="ma")
    assert selected == "feature_ols"

def test_select_model_retains_current_on_fail():
    report = _report_for_g2("feature_ols", 0.25, 0.20, 0.25, 50)
    res = evaluate_gates(report, "feature_ols")
    selected = select_model(res, current_model="ma")
    assert selected == "ma"

def test_select_model_retains_default():
    report = _report_for_g2("feature_ols", 0.25, 0.20, 0.25, 50)
    res = evaluate_gates(report, "feature_ols")
    selected = select_model(res)
    assert selected == DEFAULT_MODEL
