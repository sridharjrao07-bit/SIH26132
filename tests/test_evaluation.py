"""
tests/test_evaluation.py — Unit tests for forecasting/evaluation.py.

All tests use hand-computed expected values so failures are immediately
diagnosable without running the production engine.
"""
from __future__ import annotations

import math

import pytest
from forecasting.evaluation import (
    directional_accuracy,
    interval_coverage,
    mae,
    mape_winsorized,
)

# ---------------------------------------------------------------------------
# mae
# ---------------------------------------------------------------------------

class TestMAE:
    def test_perfect_prediction(self):
        assert mae([100, 200, 300], [100, 200, 300]) == 0.0

    def test_constant_error(self):
        # |100-110| + |200-210| + |300-310| = 10+10+10 = 30 → MAE=10
        assert mae([100, 200, 300], [110, 210, 310]) == pytest.approx(10.0)

    def test_single_point(self):
        assert mae([500.0], [450.0]) == pytest.approx(50.0)

    def test_empty_returns_nan(self):
        assert math.isnan(mae([], []))

    def test_none_values_skipped(self):
        # Only (100, 110) is valid; (None, 200) skipped → MAE = 10
        result = mae([None, 100], [200, 110])
        assert result == pytest.approx(10.0)

    def test_all_none_returns_nan(self):
        assert math.isnan(mae([None, None], [None, None]))


# ---------------------------------------------------------------------------
# mape_winsorized
# ---------------------------------------------------------------------------

class TestMAPEWinsorized:
    def test_zero_error(self):
        assert mape_winsorized([100, 200], [100, 200]) == pytest.approx(0.0)

    def test_basic(self):
        # actual=100, pred=110 → APE = |100-110|/100*100 = 10%
        assert mape_winsorized([100.0], [110.0]) == pytest.approx(10.0)

    def test_winsorization_at_100(self):
        # actual=100, pred=1000 → raw APE = 900%, clipped to 100
        result = mape_winsorized([100.0], [1000.0])
        assert result == pytest.approx(100.0), (
            "A prediction 10× the actual must be penalised at exactly 100 (the cap), "
            "not the raw 900%."
        )

    def test_winsorization_does_not_exceed_cap(self):
        # Even a wildly wrong prediction should be capped at 100
        assert mape_winsorized([1.0], [1_000_000.0]) == pytest.approx(100.0)

    def test_zero_actual_skipped(self):
        # actual=0 is undefined MAPE → skip; only (200, 220) contributes
        # APE for (200, 220) = |200-220|/200*100 = 10%
        result = mape_winsorized([0.0, 200.0], [999.0, 220.0])
        assert result == pytest.approx(10.0), (
            "Pair with actual=0 must be skipped entirely; "
            "only the non-zero actual contributes."
        )

    def test_all_zero_actuals_returns_nan(self):
        assert math.isnan(mape_winsorized([0.0, 0.0], [1.0, 2.0]))

    def test_empty_returns_nan(self):
        assert math.isnan(mape_winsorized([], []))

    def test_average_of_multiple(self):
        # APE(100, 110) = 10;  APE(200, 220) = 10 → MAPE = 10
        assert mape_winsorized([100, 200], [110, 220]) == pytest.approx(10.0)

    def test_mixed_capped_and_normal(self):
        # APE(100, 1000)=900→cap=100; APE(200, 220)=10 → avg = (100+10)/2 = 55
        assert mape_winsorized([100, 200], [1000, 220]) == pytest.approx(55.0)


# ---------------------------------------------------------------------------
# directional_accuracy
# ---------------------------------------------------------------------------

class TestDirectionalAccuracy:
    def test_correct_up(self):
        # anchor=100, preds mean=110(up), actuals mean=120(up) → 1 hit out of 1
        h, c, inc, idx = directional_accuracy([100.0], [[105.0, 115.0]], [[115.0, 125.0]])
        assert h == 1
        assert c == 1

    def test_correct_down(self):
        h, c, inc, idx = directional_accuracy([100.0], [[90.0]], [[80.0]])
        assert h == 1
        assert c == 1

    def test_wrong_direction(self):
        # pred up, actual down
        h, c, inc, idx = directional_accuracy([100.0], [[110.0]], [[80.0]])
        assert h == 0
        assert c == 1

    def test_flat_fold_excluded(self):
        # mean actual = 100.5, change=0.5, |change|/anchor = 0.005 < 0.01 → excluded
        h, c, inc, idx = directional_accuracy([100.0], [[101.0, 101.0]], [[100.0, 101.0]])
        assert c == 0  # flat fold excluded from denominator
        assert h == 0

    def test_flat_eps_boundary(self):
        # exactly at eps: |100.9 - 100| / 100 = 0.009 < 0.01 → excluded
        _, c, _, _ = directional_accuracy([100.0], [[101.0]], [[100.9]])
        assert c == 0

    def test_multiple_folds_mixed(self):
        # fold 1: anchor=1000, pred mean=1100(up), actual mean=900(down) → miss, considered=1
        # fold 2: anchor=1000, pred mean=900(down), actual mean=800(down) → hit, considered=1
        # fold 3: anchor=1000, pred mean=1005(up), actual mean=1003(up) → flat(0.3%<1%) → excluded
        h, c, inc, idx = directional_accuracy(
            [1000.0, 1000.0, 1000.0],
            [[1100.0], [900.0], [1005.0]],
            [[900.0],  [800.0], [1003.0]],
        )
        assert c == 2
        assert h == 1

    def test_zero_anchor_returns_zero(self):
        h, c, inc, idx = directional_accuracy([0.0], [[10.0]], [[20.0]])
        assert h == 0
        assert c == 0

    def test_empty_sequences(self):
        h, c, inc, idx = directional_accuracy([], [], [])
        assert h == 0
        assert c == 0


# ---------------------------------------------------------------------------
# interval_coverage
# ---------------------------------------------------------------------------

class TestIntervalCoverage:
    def test_fully_covered(self):
        # actual 10, lo=9, hi=11 → covered
        assert interval_coverage([11.0], [9.0], [10.0]) == pytest.approx(1.0)

    def test_exactly_at_lower_bound(self):
        assert interval_coverage([11.0], [10.0], [10.0]) == pytest.approx(1.0)

    def test_exactly_at_upper_bound(self):
        assert interval_coverage([10.0], [9.0], [10.0]) == pytest.approx(1.0)

    def test_below_lower_bound(self):
        # actual=5 < lo=9 → not covered
        assert interval_coverage([11.0], [9.0], [5.0]) == pytest.approx(0.0)

    def test_above_upper_bound(self):
        # actual=15 > hi=11 → not covered
        assert interval_coverage([11.0], [9.0], [15.0]) == pytest.approx(0.0)

    def test_partial_coverage(self):
        # 2 covered out of 3
        lowers  = [90.0,  90.0, 90.0]
        uppers  = [110.0, 110.0, 110.0]
        actuals = [100.0, 95.0, 200.0]  # 200 not covered
        assert interval_coverage(uppers, lowers, actuals) == pytest.approx(2 / 3)

    def test_empty_returns_one(self):
        # Vacuously covered — no violations
        assert interval_coverage([], [], []) == pytest.approx(1.0)

    def test_none_values_skipped(self):
        # Only (lo=9, hi=11, actual=10) is valid → 1/1 = 1.0
        result = interval_coverage([11.0, None], [9.0, None], [10.0, 99.0])
        assert result == pytest.approx(1.0)
