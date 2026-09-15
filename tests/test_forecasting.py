from datetime import date, timedelta

from forecasting.engine import (
    MovingAverageModel,
    LinearRegressionModel,
    _blend_predictions,
    build_daily_series,
    _make_forecast_rows,
    ForecastEngine
)
from tests.conftest import MARKET_ID_LASALGAON, COMMODITY_ID_ONION


def test_ma_model_basic():
    prices = [1000, 1100, 1200]
    model = MovingAverageModel(prices)
    # mean of [1000, 1100, 1200] = 1100
    assert model.level == 1100.0
    assert model.sigma > 0

    preds = model.predict(horizon=2)
    assert len(preds) == 2
    for p in preds:
        assert p == 1100.0


def test_ma_model_single_obs():
    model = MovingAverageModel([1500])
    assert model.level == 1500.0
    assert model.sigma == 0.0
    preds = model.predict(horizon=1)
    assert preds[0] == 1500.0


def test_lr_model_perfect_line():
    # y = 1000 + 50*x
    prices = [1000, 1050, 1100, 1150, 1200]
    model = LinearRegressionModel(prices)
    assert model.slope == 50.0
    assert model.intercept == 1000.0
    assert model.sigma == 0.0

    # next x=5 -> 1250, x=6 -> 1300
    preds = model.predict(horizon=2)
    assert preds[0] == 1250.0
    assert preds[1] == 1300.0


def test_lr_model_single_obs():
    model = LinearRegressionModel([2000])
    assert model.slope == 0.0
    assert model.intercept == 2000.0
    assert model.sigma == 0.0


def test_blend_predictions():
    # MA level = 1000, LR slope = 100, intercept = 1000
    prices = [1000, 1000, 1000] # MA = 1000, LR slope = 0, int = 1000
    ma = MovingAverageModel(prices)
    lr = LinearRegressionModel(prices)
    preds, blended_sigma = _blend_predictions(ma, lr, horizon=2)
    assert preds[0] == 1000.0


def test_build_daily_series_precedence():
    rows = [
        {"arrival_date": "2024-09-01", "modal_price": 2000, "source": "agmarknet", "variety": "General"},
        {"arrival_date": "2024-09-01", "modal_price": 2100, "source": "data_gov_in", "variety": "Other"},
        {"arrival_date": "2024-09-01", "modal_price": 2200, "source": "data_gov_in", "variety": "General"}, # should win
    ]
    series = build_daily_series(rows)
    assert len(series) == 1
    assert series[0][0] == date(2024, 9, 1)
    assert series[0][1] == 2200.0


def test_build_daily_series_iso_vs_date():
    rows = [
        {"arrival_date": "2024-09-01", "modal_price": 2000, "source": "data_gov_in"},
        {"arrival_date": date(2024, 9, 2), "modal_price": 2100, "source": "data_gov_in"},
    ]
    series = build_daily_series(rows)
    assert len(series) == 2
    assert series[0][0] == date(2024, 9, 1)
    assert series[1][0] == date(2024, 9, 2)


def test_horizon_widens_residual_band():
    """Day-7 interval is wider than day-1 when in-sample σ > 0 (F-031)."""
    series = [(date(2024, 9, 1) + timedelta(days=i), 2000.0 + (i % 3) * 40) for i in range(16)]
    rows = _make_forecast_rows("m1", "c1", series, None)
    assert len(rows) == 7
    w1 = rows[0]["upper_bound"] - rows[0]["lower_bound"]
    w7 = rows[6]["upper_bound"] - rows[6]["lower_bound"]
    assert w1 > 0
    assert w7 > w1 * 2


def test_make_forecast_rows_empty():
    assert _make_forecast_rows("m1", "c1", [], None) == []


def test_make_forecast_rows_insufficient():
    # n < 10 -> 1 row, insufficient_data
    series = [(date(2024, 9, i+1), 2000.0) for i in range(5)]
    rows = _make_forecast_rows("m1", "c1", series, None)
    assert len(rows) == 1
    assert rows[0]["status"] == "insufficient_data"
    assert rows[0]["predicted_price"] is None
    assert rows[0]["method"] == "none"


def test_make_forecast_rows_ma_only():
    # 10 <= n < 15 -> MA only
    series = [(date(2024, 9, i+1), 2000.0) for i in range(12)]
    rows = _make_forecast_rows("m1", "c1", series, sanity=(0, 5000))
    assert len(rows) == 7
    assert rows[0]["status"] == "ok"
    assert rows[0]["method"] == "moving_avg"
    assert rows[0]["confidence"] == "medium"


def test_make_forecast_rows_blend_high():
    # n >= 20 -> Blend + High Confidence
    series = [(date(2024, 9, i+1), 2000.0) for i in range(25)]
    rows = _make_forecast_rows("m1", "c1", series, sanity=(0, 5000))
    assert len(rows) == 7
    assert rows[0]["status"] == "ok"
    assert rows[0]["method"] == "blend"
    assert rows[0]["confidence"] == "high"


def test_engine_run(fake_supabase):
    # We will seed 12 rows so it gives MA medium
    prices_seed = []
    
    # 1. A row that should be ignored by the 60-day cutoff
    prices_seed.append({
        "market_id": MARKET_ID_LASALGAON,
        "commodity_id": COMMODITY_ID_ONION,
        "arrival_date": (date.today() - timedelta(days=65)).isoformat(),
        "modal_price": 1000,
        "source": "data_gov_in"
    })
    
    # 2. 12 rows within the 60-day window
    for i in range(12):
        prices_seed.append({
            "market_id": MARKET_ID_LASALGAON,
            "commodity_id": COMMODITY_ID_ONION,
            "arrival_date": (date.today() - timedelta(days=20 - i)).isoformat(),
            "modal_price": 2000 + i*10,
            "source": "data_gov_in"
        })
    fake_supabase.seed("prices", prices_seed)

    engine = ForecastEngine(fake_supabase)
    summary = engine.run()

    assert summary["pairs_ok"] == 1
    assert summary["pairs_insufficient"] == 0
    assert summary["pairs_skipped"] == 0
    assert summary["rows_written"] == 7
    
    upserts = fake_supabase.upsert_calls()
    assert len(upserts) == 1
    assert len(upserts[0]["payload"]) == 7
    assert upserts[0]["table"] == "forecasts"

def test_reversed_sanity_band(capsys):
    from forecasting.engine import _clamp
    val = _clamp(100.123, 500.0, 10.0)
    assert val == 100.12
    captured = capsys.readouterr()
    assert "reversed_sanity_band" in captured.out or "reversed_sanity_band" in captured.err

def test_reversed_sanity_band_invariant():
    from forecasting.engine import _make_forecast_rows
    from datetime import date
    series = [(date(2024, 9, i+1), 2000.0) for i in range(25)]
    # Reversed sanity band
    rows = _make_forecast_rows('m1', 'c1', series, sanity=(5000, 10))
    for r in rows:
        assert 0 <= r['lower_bound'] <= r['predicted_price'] <= r['upper_bound']


# ─── B2 Regression: generated_at must be present and fresh in all row paths ──

def test_make_forecast_rows_ok_has_generated_at():
    """B2: forecast rows (status=ok) must contain a non-None generated_at timestamp."""
    from datetime import date
    series = [(date(2024, 9, i+1), 2000.0) for i in range(25)]
    rows = _make_forecast_rows('m1', 'c1', series, None)
    assert len(rows) > 0
    for row in rows:
        assert "generated_at" in row, "generated_at key must be present"
        assert row["generated_at"] is not None, "generated_at must not be None"
        assert row["status"] == "ok"


def test_make_forecast_rows_insufficient_data_has_generated_at():
    """B2: insufficient_data rows must also contain a generated_at timestamp."""
    from datetime import date
    # Only 5 observations — below MIN_OBSERVATIONS (10)
    series = [(date(2024, 9, i+1), 2000.0) for i in range(5)]
    rows = _make_forecast_rows('m1', 'c1', series, None)
    assert len(rows) == 1
    assert rows[0]["status"] == "insufficient_data"
    assert "generated_at" in rows[0], "generated_at key must be present on insufficient_data row"
    assert rows[0]["generated_at"] is not None


def test_consecutive_runs_produce_different_generated_at():
    """
    B2 regression test: two separate calls to _make_forecast_rows must produce
    different generated_at values. This would catch a bug where the timestamp was
    hard-coded or computed once at module load (key presence alone wouldn't catch that).
    """
    import time
    from datetime import date
    series = [(date(2024, 9, i+1), 2000.0) for i in range(25)]

    rows1 = _make_forecast_rows('m1', 'c1', series, None)
    time.sleep(0.01)  # ensure wall-clock time has advanced
    rows2 = _make_forecast_rows('m1', 'c1', series, None)

    ts1 = rows1[0]["generated_at"]
    ts2 = rows2[0]["generated_at"]
    assert ts1 != ts2, (
        f"Two consecutive calls produced the same generated_at ({ts1}). "
        "This suggests the timestamp is hard-coded rather than computed at call time."
    )


def test_forecast_engine_upsert_payload_contains_generated_at(fake_supabase):
    """B2: ForecastEngine.run must include generated_at in every upserted row."""
    from datetime import date
    today = date.today().isoformat()

    from datetime import date, timedelta
    today = date.today()

    # Seed 25 price rows within the engine's 60-day lookback window (must be recent)
    fake_supabase._data["prices"] = [
        {
            "market_id":    "m1",
            "commodity_id": "c1",
            "arrival_date": (today - timedelta(days=25 - i)).isoformat(),
            "modal_price":  2000.0,
            "source":       "data_gov_in",
            "variety":      "General",
        }
        for i in range(25)
    ]
    fake_supabase._data["commodities"] = [
        {"id": "c1", "sanity_min": 100.0, "sanity_max": 8000.0}
    ]

    from forecasting.engine import ForecastEngine
    engine = ForecastEngine(fake_supabase)
    engine.run()

    upsert_calls = fake_supabase.upsert_calls()
    assert len(upsert_calls) > 0, "Engine must have upserted at least one batch of rows"

    for call in upsert_calls:
        payload = call["payload"]
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            assert "generated_at" in row, f"upserted row missing generated_at: {row}"
            assert row["generated_at"] is not None

# ── Phase 3: feature_ols and registry ────────────────────────────────────────

def test_engine_run_with_feature_ols(fake_supabase, monkeypatch):
    """FORECAST_MODEL=feature_ols with n≥20 + built feature matrix → rows have method='feature_ols'."""
    import app.config
    
    # Mock settings to use feature_ols
    old_settings = app.config.get_settings()
    class MockSettings:
        def __getattr__(self, name):
            if name == "forecast_model":
                return "feature_ols"
            return getattr(old_settings, name)
            
    monkeypatch.setattr("forecasting.engine.get_settings", MockSettings)
    
    from datetime import date, timedelta
    today = date.today()
    
    prices_seed = []
    # 100 rows, strong signal to ensure it does not fallback due to insufficient rank
    for i in range(100):
        prices_seed.append({
            "market_id": "m1",
            "commodity_id": "c1",
            "arrival_date": (today - timedelta(days=100 - i)).isoformat(),
            "modal_price": 2000.0 + i*10,
            "arrival_qty": 100.0,
            "source": "data_gov_in",
            "variety": "General",
        })
    fake_supabase.seed("prices", prices_seed)
    
    # Need to also seed weather so it doesn't fail entirely, though empty is fine if it handles it
    
    from forecasting.engine import ForecastEngine
    engine = ForecastEngine(fake_supabase)
    summary = engine.run()
    
    assert summary["pairs_ok"] == 1
    
    upserts = fake_supabase.upsert_calls()
    assert len(upserts) == 1
    
    rows = upserts[0]["payload"]
    for row in rows:
        assert row["method"] == "feature_ols"
        assert row["confidence"] == "high"

def test_engine_run_feature_ols_fallback(fake_supabase, monkeypatch):
    """Feature build failure or rank deficient -> existing blend method (assert fallback, not crash)"""
    import app.config
    
    # Mock settings
    old_settings = app.config.get_settings()
    class MockSettings:
        def __getattr__(self, name):
            if name == "forecast_model":
                return "feature_ols"
            return getattr(old_settings, name)
            
    monkeypatch.setattr("forecasting.engine.get_settings", MockSettings)
    
    # To force a fallback, we can provide <10 observations (actually n<20 for blend, but say n=15)
    # wait, if n < 10*p it falls back. If p=8, 10*8 = 80. n=25 < 80!
    # Wait, in the previous test we got feature_ols, how?
    # keep_cols in FeatureOLSModel depends on how many columns are not all None.
    # If weather/events/district aren't there, they drop!
    # If lag1, lag7, lag14, arrival are kept, p=4. 10*4=40. Still n=25 < 40!
    # Let's adjust test_engine_run_with_feature_ols to provide 50 rows.
    # But for this test, we can just provide exactly 25 rows and it WILL fallback!
    from datetime import date, timedelta
    today = date.today()
    
    prices_seed = []
    for i in range(25):
        prices_seed.append({
            "market_id": "m1",
            "commodity_id": "c1",
            "arrival_date": (today - timedelta(days=25 - i)).isoformat(),
            "modal_price": 2000.0 + i * 10, # varies so lag features are kept, raising p
            "source": "data_gov_in"
        })
    fake_supabase.seed("prices", prices_seed)
    
    from forecasting.engine import ForecastEngine
    engine = ForecastEngine(fake_supabase)
    summary = engine.run()
    
    assert summary["pairs_ok"] == 1
    upserts = fake_supabase.upsert_calls()
    rows = upserts[0]["payload"]
    # Should fallback to blend because 25 >= 15
    for row in rows:
        assert row["method"] == "blend"

def test_engine_global_features(fake_supabase, monkeypatch):
    """Regression test for P1: Engine must fetch weather and events once, and pass them."""
    import app.config
    
    # Mock settings to use feature_ols
    old_settings = app.config.get_settings()
    class MockSettings:
        def __getattr__(self, name):
            if name == "forecast_model":
                return "feature_ols"
            return getattr(old_settings, name)
            
    monkeypatch.setattr("forecasting.engine.get_settings", MockSettings)
    
    from datetime import date, timedelta
    today = date.today()
    
    prices_seed = []
    for i in range(100):
        prices_seed.append({
            "market_id": "m1",
            "commodity_id": "c1",
            "arrival_date": (today - timedelta(days=100 - i)).isoformat(),
            "modal_price": 2000.0 + i*10,
            "arrival_qty": 100.0,
            "source": "data_gov_in",
            "variety": "General",
        })
    fake_supabase.seed("prices", prices_seed)
    weather_seed = []
    for i in range(120):
        weather_seed.append({"market_id": "m1", "observation_date": (today - timedelta(days=120 - i)).isoformat(), "precipitation_sum_mm": float(i % 10)})
    fake_supabase.seed("weather_daily", weather_seed)
    fake_supabase.seed("events", [{"event_date": (today - timedelta(days=5)).isoformat(), "event_type": "weather", "direction": "down", "magnitude": "major", "confidence": 1.0}])
    fake_supabase.seed("markets", [{"id": "m1", "district": "Nashik"}])
    
    from forecasting.engine import ForecastEngine
    engine = ForecastEngine(fake_supabase)
    
    # We spy on build_feature_matrix
    original_build = None
    captured_kwargs = {}
    
    def mock_build_feature_matrix(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original_build(*args, **kwargs)
        
    import forecasting.features
    original_build = forecasting.features.build_feature_matrix
    monkeypatch.setattr("forecasting.features.build_feature_matrix", mock_build_feature_matrix)
    
    engine.run()
    
    assert "weather" in captured_kwargs
    assert "events" in captured_kwargs
    assert len(captured_kwargs["weather"]) > 0
    assert len(captured_kwargs["events"]) > 0
    
    upserts = fake_supabase.upsert_calls()
    rows = upserts[0]["payload"]
    features_used = rows[0]["features_used"]
    assert "rain_7d_cum_mm" in features_used
    assert "event_pressure" in features_used

def test_backtest_arrival_qty_winner(fake_supabase, monkeypatch):
    """Regression test for P1: Backtest must assign the winner row's arrival_qty."""
    from datetime import date, timedelta
    today = date.today()
    
    # We want to test that build_feature_matrix receives the correct arrival_qty
    # We need to spy on build_feature_matrix called inside run_backtest
    prices_seed = []
    
    # Let's add 60 rows so run_backtest actually processes it
    for i in range(60):
        d = (today - timedelta(days=60-i)).isoformat()
        if i == 59:
            # For the last day, two rows, one wins (data_gov_in > agmarknet)
            prices_seed.append({
                "market_id": "m1", "commodity_id": "c1", "arrival_date": d,
                "modal_price": 2000, "arrival_qty": 5.0, "source": "agmarknet", "variety": "General"
            })
            prices_seed.append({
                "market_id": "m1", "commodity_id": "c1", "arrival_date": d,
                "modal_price": 2000, "arrival_qty": 99.0, "source": "data_gov_in", "variety": "General"
            })
        else:
            prices_seed.append({
                "market_id": "m1", "commodity_id": "c1", "arrival_date": d,
                "modal_price": 2000, "arrival_qty": 10.0, "source": "data_gov_in", "variety": "General"
            })
            
    fake_supabase.seed("prices", prices_seed)
    
    captured_history = []
    
    import forecasting.features
    original_build = forecasting.features.build_feature_matrix
    def mock_build_feature_matrix(series=None, **kwargs):
        captured_history.extend(series)
        return original_build(series=series, **kwargs)
        
    monkeypatch.setattr("forecasting.features.build_feature_matrix", mock_build_feature_matrix)
    
    from forecasting.backtest import run_backtest
    run_backtest(fake_supabase, pairs=[("m1", "c1")], history_days=100, model_names=["ma"])
    
    assert len(captured_history) > 0
    # The last element should have arrival_qty = 99.0, not 5.0
    last_qty = captured_history[-1]["arrival_qty"]
    assert last_qty == 99.0
