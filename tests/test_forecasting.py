import pytest
from datetime import date, timedelta
from typing import List, Tuple

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
    for (p, lo, hi) in preds:
        assert p == 1100.0
        assert lo < p < hi


def test_ma_model_single_obs():
    model = MovingAverageModel([1500])
    assert model.level == 1500.0
    assert model.sigma == 0.0
    preds = model.predict(horizon=1)
    assert preds[0] == (1500.0, 1500.0, 1500.0)


def test_lr_model_perfect_line():
    # y = 1000 + 50*x
    prices = [1000, 1050, 1100, 1150, 1200]
    model = LinearRegressionModel(prices)
    assert model.slope == 50.0
    assert model.intercept == 1000.0
    assert model.sigma == 0.0

    # next x=5 -> 1250, x=6 -> 1300
    preds = model.predict(horizon=2)
    assert preds[0] == (1250.0, 1250.0, 1250.0)
    assert preds[1] == (1300.0, 1300.0, 1300.0)


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
    preds = _blend_predictions(ma, lr, horizon=2)
    assert preds[0] == (1000.0, 1000.0, 1000.0)


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
