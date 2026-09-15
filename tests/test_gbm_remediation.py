from unittest.mock import patch, MagicMock

from tests.conftest import FakeSupabase, MARKET_ID_LASALGAON, COMMODITY_ID_ONION
from tests.test_backtest import _make_price_rows, _trended_series
from forecasting.backtest import run_backtest
import sys
import math
import os
import pytest

# Create a fake lightgbm module so we can test the real train_global_gbm logic in isolation
mock_lgb = MagicMock()
def _mock_predict(X):
    # X is the feature matrix, return lag_1 (index 3) to prove inputs are isolated
    return [row[3] if not math.isnan(row[3]) else 0.0 for row in X]
mock_lgb.LGBMRegressor.return_value.predict.side_effect = _mock_predict

# Ensure that we only mock lightgbm during the specific mock tests
@patch.dict(sys.modules, {"lightgbm": mock_lgb})
def test_train_global_gbm_isolation_and_sigma():
    from forecasting.gbm import train_global_gbm

    # 1. Deterministic Synthetic Dataset
    # Base series has 100 days
    base_series = _trended_series(100)
    
    # Series 2 starts late, strictly within the validation window (last 10 days)
    # This should be excluded from the categorical encoders since it's >= val_cutoff
    late_series = _trended_series(100)[-10:]
    late_series = [(d, p + 100.0) for d, p in late_series]
    
    pairs_history = {
        ("M1", "C1"): _make_price_rows(base_series),
        ("M2", "C2"): _make_price_rows(late_series)
    }
    
    # 2. Invoke real trainer
    model = train_global_gbm(
        pairs_history=pairs_history,
        weather=[],
        events=[],
        district_prices=[],
        strict_pit=True
    )
    
    # 3. Verify Encoders
    # M1 and C1 should be in the maps
    assert "M1" in model.market_map, "M1 should be in market_map because it occurs before val_cutoff"
    assert "C1" in model.commodity_map, "C1 should be in commodity_map because it occurs before val_cutoff"
    
    # M2 and C2 should NOT be in the maps
    assert "M2" not in model.market_map, "M2 should NOT be in market_map because it only appears after val_cutoff"
    assert "C2" not in model.commodity_map, "C2 should NOT be in commodity_map because it only appears after val_cutoff"
    
    # 4. Verify Sigma
    # Sigma should be > 0 since we have residuals in the validation split
    assert model.sigma > 0, "Sigma should be computed from validation split residuals"
    
    # 5. Verify Predict / Pair-State Isolation
    # We call fit with a specific pair and predict.
    model.fit(base_series[-14:], features=[
        type("Feat", (), {
            "dow": 0, "lag_1": 100, "lag_7": 100, "lag_14": 100,
            "arrivals_7d_avg": 0, "momentum_14d": 0, "rain_7d_cum_mm": 0,
            "district_mean_price": 100, "event_pressure": 0.0, "events_approximate": False
        })()
    ], pair_id=("M1", "C1"))
    
    # Provide explicit forecast_origin for the prediction
    # Assuming forecast origin is max_d (base_series[-1][0])
    preds_m1 = model.predict(horizon=1, forecast_origin=base_series[-1][0])
    assert len(preds_m1) == 1
    
    # Predict for M2 (unknown pair)
    model.fit(late_series[-14:], features=[
        type("Feat", (), {
            "dow": 0, "lag_1": 200, "lag_7": 200, "lag_14": 200,
            "arrivals_7d_avg": 0, "momentum_14d": 0, "rain_7d_cum_mm": 0,
            "district_mean_price": 200, "event_pressure": 0.0, "events_approximate": False
        })()
    ], pair_id=("M2", "C2"))
    
    preds_m2 = model.predict(horizon=1, forecast_origin=late_series[-1][0])
    assert len(preds_m2) == 1
    
    # They should produce different interval bounds due to isolation and different lag values
    assert preds_m1[0] != preds_m2[0], "Pair state should be isolated"


@patch("forecasting.gbm.train_global_gbm")
def test_gbm_requirements(mock_train_gbm):
    # Setup global GBM mock just for the harness integration test
    mock_model = MagicMock()
    mock_model.predict.return_value = [(100.0, 90.0, 110.0)] * 7
    mock_train_gbm.return_value = mock_model
    
    db = FakeSupabase()
    series = _trended_series(100)
    db.seed("prices", _make_price_rows(series))
    
    # Run backtest with gbm
    report = run_backtest(
        db,
        [(MARKET_ID_LASALGAON, COMMODITY_ID_ONION)],
        history_days=365,
        model_names=["gbm"]
    )
    
    assert mock_train_gbm.call_count == 8, "Global pooling & Fit count: must train once per fold globally"
    assert report is not None


def test_train_global_gbm_real():
    # If REQUIRE_ML_DEPS is set (e.g. in ML CI), missing lightgbm should fail the test.
    # Otherwise, in base CI, it can skip.
    if os.environ.get("REQUIRE_ML_DEPS") == "1":
        import lightgbm
    else:
        lightgbm = pytest.importorskip("lightgbm")
        
    # Assert it's the real module, not a MagicMock
    assert not isinstance(lightgbm, MagicMock), "LightGBM must be the real module in this test"
    assert hasattr(lightgbm, "LGBMRegressor"), "LightGBM must have LGBMRegressor"

    from forecasting.gbm import train_global_gbm
    
    base_series = _trended_series(100)
    pairs_history = {
        ("M1", "C1"): _make_price_rows(base_series),
    }
    
    # Invoke real trainer without mock
    model = train_global_gbm(
        pairs_history=pairs_history,
        weather=[],
        events=[],
        district_prices=[],
        strict_pit=True
    )
    
    assert model.sigma > 0
    assert "M1" in model.market_map
    
    model.fit(base_series[-14:], features=[
        type("Feat", (), {
            "dow": 0, "lag_1": 100, "lag_7": 100, "lag_14": 100,
            "arrivals_7d_avg": 0, "momentum_14d": 0, "rain_7d_cum_mm": 0,
            "district_mean_price": 100, "event_pressure": 0.0, "events_approximate": False
        })()
    ], pair_id=("M1", "C1"))
    
    preds_m1 = model.predict(horizon=1, forecast_origin=base_series[-1][0])
    assert len(preds_m1) == 1
    assert preds_m1[0] > 0
