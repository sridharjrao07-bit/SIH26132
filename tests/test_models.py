import math

from forecasting.engine import LinearRegressionModel as BaselineOLS
from forecasting.engine import MovingAverageModel as BaselineMA
from forecasting.features import FeatureRow
from forecasting.models import FeatureOLSModel, HoltWintersModel


def test_feature_ols_beats_baseline():
    # Signal series: price[t+1] ≈ a − b·arrivals[t] + noise
    # We will just generate prices that perfectly correlate with lag_1
    # Actually, a simple auto-regressive process: price[t] = 100 + 0.5*price[t-1]

    import random

    random.seed(42)
    prices = []
    arrivals = []

    for t in range(100):
        arr = 100.0 + random.uniform(-20, 20)
        arrivals.append(arr)
        # Price is exactly 500 - 2 * arrivals
        prices.append(500.0 - 2.0 * arr)

    features = []
    for i in range(len(prices)):
        features.append(
            FeatureRow(
                day_offset=i,
                dow=i % 7,
                lag_1=prices[i - 1] if i > 0 else None,
                lag_7=None,
                lag_14=None,
                arrivals_7d_avg=arrivals[i],  # Give the model the arrival data
                momentum_14d=None,
                rain_7d_cum_mm=None,
                district_mean_price=None,
                event_pressure=None,
            )
        )

    train_prices = prices[:-7]
    train_features = features[:-7]

    model = FeatureOLSModel(train_prices, train_features)
    assert not model.fallback

    preds = model.predict(7)

    baseline = BaselineOLS(train_prices)
    base_preds = baseline.predict(7)

    # FeatureOLS should perfectly learn the AR(1) relationship,
    # making its MAE smaller than OLS which just fits a straight line over time.
    actuals = prices[-7:]

    mae_feature = sum(abs(p - a) for p, a in zip(preds, actuals)) / 7

    assert mae_feature < 25.0
    # OLS is a simple line fit over a trend, MAE will be huge since the true relation is AR(1)
    mae_base = sum(abs(p - a) for p, a in zip(base_preds, actuals)) / 7
    assert mae_feature < mae_base


def test_feature_ols_drops_none_columns():
    prices = [100.0 + i for i in range(100)]
    features = []
    for i in range(len(prices)):
        # All extra features are None
        features.append(
            FeatureRow(
                day_offset=i,
                dow=i % 7,
                lag_1=None,
                lag_7=None,
                lag_14=None,
                arrivals_7d_avg=None,
                momentum_14d=None,
                rain_7d_cum_mm=None,
                district_mean_price=None,
                event_pressure=0.0,
            )
        )

    model = FeatureOLSModel(prices, features)
    assert not model.fallback
    preds = model.predict(7)

    assert len(preds) == 7
    for p in preds:
        assert math.isfinite(p)


def test_holt_winters_fallback_short_series():
    prices = [100.0] * 25  # n=25 < 30
    model = HoltWintersModel(prices)
    assert model.fallback


def test_holt_winters_weekly_seasonal():
    # Seasonal series: base + 10*sin(2*pi*t/7)
    prices = [100.0 + 10.0 * math.sin(2 * math.pi * i / 7) for i in range(40)]

    train_prices = prices[:-7]
    actuals = prices[-7:]

    model = HoltWintersModel(train_prices)
    if model.fallback:
        # Fallback can happen if statsmodels is not installed, which is fine
        return

    preds = model.predict(7)

    baseline = BaselineMA(train_prices)
    base_preds = baseline.predict(7)

    mae_hw = sum(abs(p - a) for p, a in zip(preds, actuals)) / 7
    mae_base = sum(abs(p - a) for p, a in zip(base_preds, actuals)) / 7

    assert mae_hw < mae_base


def test_band_properties():
    prices = [100.0 + i * 2 for i in range(100)]
    features = []
    for i in range(len(prices)):
        features.append(
            FeatureRow(
                day_offset=i,
                dow=i % 7,
                lag_1=prices[i - 1] if i > 0 else None,
                lag_7=None,
                lag_14=None,
                arrivals_7d_avg=None,
                momentum_14d=None,
                rain_7d_cum_mm=None,
                district_mean_price=None,
                event_pressure=0.0,
            )
        )

    models_to_test = [FeatureOLSModel(prices, features)]

    hw = HoltWintersModel(prices)
    if not hw.fallback:
        models_to_test.append(hw)

    for model in models_to_test:
        raw_preds = model.predict(7)
        from forecasting.engine import apply_postprocessing

        preds = apply_postprocessing(raw_preds, model.sigma, sanity=None)
        # Check lower <= price <= upper
        for p, lo, hi in preds:
            assert lo <= p <= hi

        # Check day-7 width > day-1 width
        width_1 = preds[0][2] - preds[0][1]
        width_7 = preds[-1][2] - preds[-1][1]

        # In FeatureOLS and HoltWinters, we explicitly widened by sqrt(h)
        assert width_7 > width_1 or math.isclose(width_7, width_1, abs_tol=1e-5) and width_1 == 0.0
