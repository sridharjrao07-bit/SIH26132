"""
Tests for forecasting.gates

Covers:
  - GateOutcome semantics (PASS/SKIP/FAIL)
  - G2 and G3 individual gate evaluation
  - select_model() — the enforced selection path
  - Critical contract: SKIP blocks promotion (not a pass)
  - Serialization
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


from forecasting.gates import (
    GateOutcome,
    evaluate_gates,
    select_model,
    DEFAULT_MODEL,
    G2_MAPE_THRESHOLD,
    G3_DA_THRESHOLD,
    G2_MIN_PREDICTIONS,
    G3_MIN_DIRECTIONAL,
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


def _report(mape: Optional[float], n_preds: int, hits: int, folds: int):
    """Build a minimal BacktestReport stub for testing."""
    pair = _PairResult(
        market_id="m1", commodity_id="c1", n_obs=100,
        models=[_ModelResult(model="blend", directional_hits=hits,
                             directional_folds=folds)],
    )
    return _BacktestReport(
        aggregate={"blend": {"mape_winsorized": mape, "n_predictions": n_preds}},
        per_pair=[pair],
    )


# ── GateOutcome contract ──────────────────────────────────────────────────────

def test_only_pass_does_not_block_promotion():
    assert not GateOutcome.PASS.blocks_promotion
    assert GateOutcome.SKIP.blocks_promotion
    assert GateOutcome.FAIL.blocks_promotion


# ── CRITICAL: SKIP must block promotion ──────────────────────────────────────

def test_skip_on_insufficient_g2_blocks_select_model():
    """SKIP is not a pass — select_model must retain the current model."""
    report = _report(mape=0.99, n_preds=G2_MIN_PREDICTIONS - 1,
                     hits=8, folds=10)
    result = evaluate_gates(report, model_name="blend")

    g2 = next(g for g in result.gates if g.name == "G2_MAPE")
    assert g2.outcome is GateOutcome.SKIP
    assert g2.passed is False          # .passed property reflects outcome
    assert result.all_pass is False    # all_pass requires all PASS, not just not-FAIL

    selected = select_model(result, current_model="blend")
    assert selected == "blend"         # retained, not promoted


def test_skip_on_insufficient_g3_blocks_select_model():
    """Insufficient directional samples → SKIP → retention."""
    report = _report(mape=0.10, n_preds=50,
                     hits=0, folds=G3_MIN_DIRECTIONAL - 1)
    result = evaluate_gates(report, model_name="blend")

    g3 = next(g for g in result.gates if g.name == "G3_DA")
    assert g3.outcome is GateOutcome.SKIP
    assert result.all_pass is False

    selected = select_model(result, current_model="ma")
    assert selected == "ma"            # current model retained


def test_both_skipped_all_pass_is_false():
    """If no gates can be evaluated, all_pass must be False."""
    report = _report(mape=None, n_preds=0, hits=0, folds=0)
    result = evaluate_gates(report, model_name="blend")
    assert result.all_pass is False


# ── G2 pass/fail ─────────────────────────────────────────────────────────────

def test_g2_pass_when_mape_at_threshold():
    report = _report(mape=G2_MAPE_THRESHOLD, n_preds=50, hits=8, folds=10)
    result = evaluate_gates(report, model_name="blend")
    g2 = next(g for g in result.gates if g.name == "G2_MAPE")
    assert g2.outcome is GateOutcome.PASS


def test_g2_fail_when_mape_above_threshold():
    report = _report(mape=G2_MAPE_THRESHOLD + 0.01, n_preds=50, hits=8, folds=10)
    result = evaluate_gates(report, model_name="blend")
    g2 = next(g for g in result.gates if g.name == "G2_MAPE")
    assert g2.outcome is GateOutcome.FAIL
    assert result.all_pass is False


# ── G3 pass/fail ─────────────────────────────────────────────────────────────

def test_g3_pass_when_da_at_threshold():
    # Exactly at threshold: 55/100
    hits = round(G3_DA_THRESHOLD * 100)
    report = _report(mape=0.15, n_preds=50, hits=hits, folds=100)
    result = evaluate_gates(report, model_name="blend")
    g3 = next(g for g in result.gates if g.name == "G3_DA")
    assert g3.outcome is GateOutcome.PASS


def test_g3_fail_when_da_below_threshold():
    # One short: 54/100
    hits = round(G3_DA_THRESHOLD * 100) - 1
    report = _report(mape=0.15, n_preds=50, hits=hits, folds=100)
    result = evaluate_gates(report, model_name="blend")
    g3 = next(g for g in result.gates if g.name == "G3_DA")
    assert g3.outcome is GateOutcome.FAIL
    assert result.all_pass is False


# ── select_model — the enforced selection path ────────────────────────────────

def test_select_model_promotes_when_all_gates_pass():
    report = _report(mape=0.15, n_preds=50, hits=8, folds=10)
    result = evaluate_gates(report, model_name="blend")
    assert result.all_pass is True
    selected = select_model(result, current_model="ma")
    assert selected == "blend"         # candidate promoted


def test_select_model_retains_current_on_g2_fail():
    report = _report(mape=0.25, n_preds=50, hits=8, folds=10)
    result = evaluate_gates(report, model_name="blend")
    selected = select_model(result, current_model="ma")
    assert selected == "ma"


def test_select_model_retains_current_on_g3_fail():
    report = _report(mape=0.15, n_preds=50, hits=3, folds=10)
    result = evaluate_gates(report, model_name="blend")
    selected = select_model(result, current_model="ma")
    assert selected == "ma"


def test_select_model_retains_default_when_no_current_specified():
    """When current_model is omitted, DEFAULT_MODEL is retained."""
    report = _report(mape=0.25, n_preds=50, hits=3, folds=10)
    result = evaluate_gates(report, model_name="blend")
    selected = select_model(result)
    assert selected == DEFAULT_MODEL


def test_select_model_retains_on_one_skip_one_pass():
    """One gate SKIP + one gate PASS → retention (not promotion)."""
    report = _report(
        mape=0.15, n_preds=50,          # G2 would PASS
        hits=0, folds=G3_MIN_DIRECTIONAL - 1,  # G3 is SKIP
    )
    result = evaluate_gates(report, model_name="blend")
    assert result.all_pass is False
    selected = select_model(result, current_model="ma")
    assert selected == "ma"


# ── blocking_gates property ───────────────────────────────────────────────────

def test_blocking_gates_lists_only_skip_and_fail():
    report = _report(mape=0.25, n_preds=50, hits=8, folds=10)
    result = evaluate_gates(report, model_name="blend")
    blocking = result.blocking_gates
    assert all(g.outcome.blocks_promotion for g in blocking)
    assert any(g.name == "G2_MAPE" for g in blocking)


# ── GateResult.to_dict — serialization ───────────────────────────────────────

def test_to_dict_outcome_values_are_strings():
    report = _report(mape=0.25, n_preds=50, hits=3, folds=10)
    result = evaluate_gates(report, model_name="blend")
    d = result.to_dict()
    assert isinstance(d, dict)
    assert "all_pass" in d
    for g in d["gates"]:
        assert g["outcome"] in ("pass", "skip", "fail")
        assert isinstance(g["passed"], bool)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_unknown_model_name_skips_all_gates_blocks_promotion():
    report = _BacktestReport(
        aggregate={"blend": {"mape_winsorized": 0.10, "n_predictions": 50}}
    )
    result = evaluate_gates(report, model_name="nonexistent_model")
    assert result.all_pass is False    # no evidence → all SKIP → blocks
    selected = select_model(result, current_model="blend")
    assert selected == "blend"


def test_threshold_constants_are_sane():
    assert 0 < G2_MAPE_THRESHOLD <= 1
    assert 0 < G3_DA_THRESHOLD <= 1
    assert G2_MIN_PREDICTIONS >= 1
    assert G3_MIN_DIRECTIONAL >= 1
