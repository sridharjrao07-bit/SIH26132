"""Tests for forecasting.gates — G2 (MAPE) and G3 (directional accuracy) gates."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from forecasting.gates import (
    evaluate_gates,
    G2_MAPE_THRESHOLD,
    G3_DA_THRESHOLD,
    G2_MIN_PREDICTIONS,
    G3_MIN_DIRECTIONAL,
)


# ── Minimal stub types (not the real dataclasses — avoids import chain) ──────

@dataclass
class _ModelResult:
    model:             str
    mae:               Optional[float] = None
    mape_winsorized:   Optional[float] = None
    directional_hits:  Optional[int]   = None
    directional_folds: Optional[int]   = None
    interval_coverage: Optional[float] = None
    nan_rate:          float           = 0.0


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


# ── G2 tests ─────────────────────────────────────────────────────────────────

def test_g2_passes_when_mape_below_threshold():
    report = _BacktestReport(
        aggregate={"blend": {"mape_winsorized": 0.15, "n_predictions": 50}},
    )
    result = evaluate_gates(report, model_name="blend")
    g2 = next(g for g in result.gates if g.name == "G2_MAPE")
    assert g2.passed is True
    assert g2.value == pytest.approx(0.15)


def test_g2_fails_when_mape_above_threshold():
    report = _BacktestReport(
        aggregate={"blend": {"mape_winsorized": 0.25, "n_predictions": 50}},
    )
    result = evaluate_gates(report, model_name="blend")
    g2 = next(g for g in result.gates if g.name == "G2_MAPE")
    assert g2.passed is False
    assert result.all_pass is False


def test_g2_skips_when_n_predictions_below_minimum():
    """Insufficient data must not block — gate passes with a note."""
    report = _BacktestReport(
        aggregate={"blend": {"mape_winsorized": 0.99, "n_predictions": G2_MIN_PREDICTIONS - 1}},
    )
    result = evaluate_gates(report, model_name="blend")
    g2 = next(g for g in result.gates if g.name == "G2_MAPE")
    assert g2.passed is True
    assert result.notes  # at least one note added


def test_g2_skips_when_mape_is_none():
    report = _BacktestReport(
        aggregate={"blend": {"mape_winsorized": None, "n_predictions": 100}},
    )
    result = evaluate_gates(report, model_name="blend")
    g2 = next(g for g in result.gates if g.name == "G2_MAPE")
    assert g2.passed is True  # None → skip, not fail


# ── G3 tests ─────────────────────────────────────────────────────────────────

def _report_with_da(hits: int, folds: int, mape: float = 0.10, n_preds: int = 50):
    pair = _PairResult(
        market_id="m1", commodity_id="c1", n_obs=100,
        models=[_ModelResult(
            model="blend",
            directional_hits=hits,
            directional_folds=folds,
        )],
    )
    return _BacktestReport(
        aggregate={"blend": {"mape_winsorized": mape, "n_predictions": n_preds}},
        per_pair=[pair],
    )


def test_g3_passes_when_da_above_threshold():
    report = _report_with_da(hits=6, folds=10)
    result = evaluate_gates(report, model_name="blend")
    g3 = next(g for g in result.gates if g.name == "G3_DA")
    assert g3.passed is True
    assert g3.value == pytest.approx(0.6)


def test_g3_fails_when_da_below_threshold():
    report = _report_with_da(hits=4, folds=10)
    result = evaluate_gates(report, model_name="blend")
    g3 = next(g for g in result.gates if g.name == "G3_DA")
    assert g3.passed is False
    assert g3.value == pytest.approx(0.4)
    assert result.all_pass is False


def test_g3_skips_when_directional_folds_below_minimum():
    report = _report_with_da(hits=0, folds=G3_MIN_DIRECTIONAL - 1)
    result = evaluate_gates(report, model_name="blend")
    g3 = next(g for g in result.gates if g.name == "G3_DA")
    assert g3.passed is True
    assert result.notes  # note added


# ── Combined gate tests ───────────────────────────────────────────────────────

def test_all_pass_when_both_gates_pass():
    report = _report_with_da(hits=8, folds=10, mape=0.12, n_preds=56)
    result = evaluate_gates(report, model_name="blend")
    assert result.all_pass is True


def test_all_pass_false_when_g2_fails_even_if_g3_passes():
    report = _report_with_da(hits=8, folds=10, mape=0.25, n_preds=56)
    result = evaluate_gates(report, model_name="blend")
    assert result.all_pass is False


def test_all_pass_false_when_g3_fails_even_if_g2_passes():
    report = _report_with_da(hits=3, folds=10, mape=0.12, n_preds=56)
    result = evaluate_gates(report, model_name="blend")
    assert result.all_pass is False


def test_gate_result_to_dict_is_serializable():
    report = _report_with_da(hits=7, folds=10, mape=0.14, n_preds=56)
    result = evaluate_gates(report, model_name="blend")
    d = result.to_dict()
    assert isinstance(d, dict)
    assert "model" in d and "all_pass" in d and "gates" in d
    for g in d["gates"]:
        assert "name" in g and "passed" in g and "threshold" in g


def test_unknown_model_name_returns_skipped_gates():
    """Requesting gates for a model not in aggregate should not raise."""
    report = _BacktestReport(aggregate={"blend": {"mape_winsorized": 0.10, "n_predictions": 50}})
    result = evaluate_gates(report, model_name="nonexistent_model")
    # All gates should be skipped (not raised), result.all_pass=True (no evidence)
    assert result.all_pass is True


def test_threshold_constants_are_sane():
    """Sanity check: thresholds are in plausible ranges."""
    assert 0 < G2_MAPE_THRESHOLD <= 1
    assert 0 < G3_DA_THRESHOLD <= 1
    assert G2_MIN_PREDICTIONS >= 1
    assert G3_MIN_DIRECTIONAL >= 1
