import random
from datetime import date, timedelta

import pytest
from forecasting.backtest import run_backtest

try:
    import lightgbm  # noqa: F401  # availability check
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

# Module-level skip removed to allow import-failure test to run on base environment.

@pytest.fixture(autouse=True)
def reset_global_gbm():
    # Model now uses instance state; no global state to reset
    yield


def test_import_failure_fallback(monkeypatch, mock_supabase):
    """
    Import failure: monkeypatch lightgbm import -> engine falls back to tier behavior, 
    logs warning, writes valid rows
    """
    import builtins
    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == 'lightgbm':
            raise ImportError("Mocked import error")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    # Run actual backtest and verify it degrades gracefully and reports execution failure
    rows, _, builder = _generate_synthetic_data(seed=42, n_days=200, is_noise=True)
    supabase = mock_supabase(builder, rows)
    
    report = run_backtest(supabase, pairs=[("M1", "C1")], history_days=150, model_names=["gbm", "naive"])
    
    # GBM should have failed gracefully and be blocked
    assert "gbm" in report.aggregate
    gbm_agg = report.aggregate["gbm"]
    assert gbm_agg["status"] == "blocked"
    assert gbm_agg["reason"] == "execution_failure"
    assert gbm_agg["n_execution_failure"] > 0
    
    # Naive should have succeeded independently
    assert "naive" in report.aggregate
    assert report.aggregate["naive"]["status"] == "ok"


def _generate_synthetic_data(seed: int, n_days: int = 200, is_noise: bool = False):
    """Generate synthetic prices and features."""
    random.seed(seed)
    
    start_date = date(2026, 1, 1)
    
    rows = []
    prices = []
    
    # We need to simulate the database
    # Let's mock get_supabase_client instead to return this data
    # Actually, to make GlobalGBM train properly, we must mock supabase
    
    # Wait, instead of a full supabase mock, we can monkeypatch GlobalGBM._train_global
    # or just mock get_supabase_client
    
    class MockData:
        def __init__(self, data):
            self.data = data
            
    class MockBuilder:
        def __init__(self, data):
            self.data = data
            
        def select(self, *args, **kwargs): return self
        def gte(self, *args, **kwargs): return self
        def lte(self, *args, **kwargs): return self
        def lt(self, *args, **kwargs): return self
        def eq(self, *args, **kwargs): return self
        def order(self, *args, **kwargs): return self
        def or_(self, *args, **kwargs): return self
        def is_(self, *args, **kwargs): return self
        def range(self, *args, **kwargs): return self
        @property
        def not_(self):
            class _NotHelper:
                def __init__(self, query):
                    self.query = query
                def is_(self, col, val):
                    return self.query
            return _NotHelper(self)
        def execute(self):
            return MockData(self.data)
            
    price = 1000.0
    
    for i in range(n_days):
        d = start_date + timedelta(days=i)
        
        if is_noise:
            price = price + random.uniform(-50, 50)
            price = max(500, min(1500, price))
        else:
            # Signal set: price driven by dow and lag_1
            dow = d.weekday()
            # weekend drop
            if dow >= 5:
                price = price * 0.95 + random.uniform(-10, 10)
            else:
                price = price * 1.02 + random.uniform(-10, 10)
                
            price = max(500, min(1500, price))
            
        prices.append((d, price))
        
        rows.append({
            "market_id": "M1",
            "commodity_id": "C1",
            "arrival_date": d.isoformat(),
            "modal_price": price,
            "arrival_qty": random.uniform(10, 100),
            "source": "manual"
        })
        
    return rows, prices, MockBuilder

@pytest.fixture
def mock_supabase(monkeypatch):
    def patch(builder_cls, rows):
        class MockSupabase:
            def table(self, name):
                if name == "prices":
                    return builder_cls(rows)
                return builder_cls([]) # empty weather/events
        
        monkeypatch.setattr("app.services.jobs.get_supabase_client", lambda: MockSupabase())
        return MockSupabase()
    return patch

@pytest.mark.skipif(not HAS_LIGHTGBM, reason="lightgbm not installed")
def test_noise_set_performance(mock_supabase):
    """Noise set (pure random, seeded): GBM validation MAPE >= naive * 0.95"""
    rows, _, builder = _generate_synthetic_data(seed=42, n_days=200, is_noise=True)
    supabase = mock_supabase(builder, rows)
    
    report = run_backtest(supabase, pairs=[("M1", "C1")], history_days=150, model_names=["gbm", "naive"])
    
    gbm_mape = report.aggregate["gbm"]["mape_winsorized"]
    naive_mape = report.aggregate["naive"]["mape_winsorized"]
    
    assert gbm_mape is not None and naive_mape is not None
    assert gbm_mape >= naive_mape * 0.95, f"GBM MAPE {gbm_mape} is suspiciously good on noise compared to {naive_mape}"

@pytest.mark.skipif(not HAS_LIGHTGBM, reason="lightgbm not installed")
def test_signal_set_performance(mock_supabase):
    """Signal set (price driven by 2 features, seeded): GBM beats BaselineOLS on validation MAE"""
    rows, _, builder = _generate_synthetic_data(seed=42, n_days=200, is_noise=False)
    supabase = mock_supabase(builder, rows)
    
    report = run_backtest(supabase, pairs=[("M1", "C1")], history_days=150, model_names=["gbm", "ols"])
    
    gbm_mae = report.aggregate["gbm"]["mae"]
    ols_mae = report.aggregate["ols"]["mae"]
    
    assert gbm_mae is not None and ols_mae is not None
    assert gbm_mae < ols_mae, f"GBM MAE {gbm_mae} failed to beat OLS MAE {ols_mae} on signal set"
    
@pytest.mark.skipif(not HAS_LIGHTGBM, reason="lightgbm not installed")
def test_feature_importances_nonempty_on_success(mock_supabase):
    """
    Regression guard for Bug 1: when GBM trains successfully, the report MUST
    carry non-empty feature_importances with positive total gain.

    The original bug called `model.feature_importance()` on the sklearn wrapper
    (which only exists on the Booster), raising AttributeError that a bare
    `except` swallowed — so importances were silently [] forever. This test
    fails if that regresses.
    """
    rows, _, builder = _generate_synthetic_data(seed=42, n_days=200, is_noise=False)
    supabase = mock_supabase(builder, rows)

    report = run_backtest(supabase, pairs=[("M1", "C1")], history_days=150, model_names=["gbm"])

    gbm_agg = report.aggregate["gbm"]
    assert gbm_agg["status"] == "ok", f"precondition: GBM should train ok, got {gbm_agg['status']}"

    importances = gbm_agg.get("feature_importances")
    assert importances, "feature_importances must be non-empty when GBM trains successfully"

    # Structural contract: list of {feature: str, gain: float}
    for item in importances:
        assert isinstance(item["feature"], str)
        assert isinstance(item["gain"], float)

    # A trained model must attribute positive gain somewhere.
    total_gain = sum(item["gain"] for item in importances)
    assert total_gain > 0, "total gain must be positive for a fitted model"

    # Signal set is driven by dow + lag_1; lag_1 should carry real gain.
    by_name = {item["feature"]: item["gain"] for item in importances}
    assert by_name.get("lag_1", 0) > 0, "lag_1 must have positive gain on the autoregressive signal set"


@pytest.mark.skipif(not HAS_LIGHTGBM, reason="lightgbm not installed")
def test_backtest_report_format(mock_supabase):
    """Backtest report format: `gbm` exists, lists `feature_importances`, correctly formats nulls."""
    rows, _, builder = _generate_synthetic_data(seed=42, n_days=30, is_noise=True)
    supabase = mock_supabase(builder, rows)
    
    # Intentionally use a short history (30 days) to test the 'blocked' state
    report = run_backtest(supabase, pairs=[("M1", "C1")], history_days=30, model_names=["gbm", "naive"])
    
    assert "gbm" in report.aggregate
    gbm_agg = report.aggregate["gbm"]
    
    # With limited history, GBM will be blocked
    assert gbm_agg["status"] == "blocked"
    assert gbm_agg["mae"] is None
    assert gbm_agg["interval_coverage"] is None
    
    # Naive will have N/A (null) for interval_coverage even if it succeeds
    naive_agg = report.aggregate["naive"]
    assert naive_agg["interval_coverage"] is None


# ─── Regression Fallback Tests for LightGBM ───────────────────────────────────

def test_gbm_fallback_to_feature_ols_when_pretrained_none(monkeypatch):
    """When FORECAST_MODEL=gbm and pretrained_model is None, falls back to feature_ols."""
    from forecasting import engine as eng
    from forecasting.engine import _make_forecast_rows
    from forecasting.features import build_feature_matrix

    class _Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    base = date(2026, 8, 1)
    n = 80
    history = [
        {
            "arrival_date": (base + timedelta(days=i)).isoformat(),
            "modal_price": 2000.0 + i * 5.0,
            "arrival_qty": 100.0 + (i % 7) * 10.0,
        }
        for i in range(n)
    ]
    series = [(base + timedelta(days=i), 2000.0 + i * 5.0) for i in range(n)]
    features = build_feature_matrix(history)
    registry = {"auto": "id-auto", "gbm": "id-gbm", "feature_ols": "id-fols"}

    rows = _make_forecast_rows(
        "m1", "c1", series, sanity=(100, 8000),
        features=features, pretrained_model=None, model_registry=registry,
        as_of=base + timedelta(days=n - 1)
    )

    assert len(rows) == 7
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["method"] == "feature_ols" for r in rows)
    assert all(r["model_id"] == "id-fols" for r in rows)
    assert all(r["confidence"] == "high" for r in rows)
    assert all("lag_1" in r["features_used"] for r in rows)


def test_gbm_fallback_to_linear_regression_when_features_none(monkeypatch):
    """When FORECAST_MODEL=gbm and features=None, falls back to ols."""
    from forecasting import engine as eng
    from forecasting.engine import _make_forecast_rows

    class _Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    base = date(2026, 8, 1)
    n = 30
    series = [(base + timedelta(days=i), 2000.0 + i * 5.0) for i in range(n)]
    registry = {"auto": "id-auto", "gbm": "id-gbm", "feature_ols": "id-fols"}

    rows = _make_forecast_rows(
        "m1", "c1", series, sanity=(100, 8000),
        features=None, pretrained_model=None, model_registry=registry,
        as_of=base + timedelta(days=n - 1)
    )

    assert len(rows) == 7
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["method"] == "ols" for r in rows)
    assert all(r["model_id"] == "id-auto" for r in rows)
    assert all(r["confidence"] == "high" for r in rows)


def test_gbm_fallback_to_linear_regression_when_feature_ols_insufficient_samples(monkeypatch):
    """When feature_ols has insufficient samples (n-1 < 10*p), falls back to ols."""
    from forecasting import engine as eng
    from forecasting.engine import _make_forecast_rows
    from forecasting.features import build_feature_matrix

    class _Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    base = date(2026, 8, 1)
    # 40 observations gives n-1=39 < 10*p (where p >= 4), triggering feature_ols fallback to ols
    n = 40
    history = [
        {
            "arrival_date": (base + timedelta(days=i)).isoformat(),
            "modal_price": 2000.0 + i * 5.0,
            "arrival_qty": 100.0 + (i % 7) * 10.0,
        }
        for i in range(n)
    ]
    series = [(base + timedelta(days=i), 2000.0 + i * 5.0) for i in range(n)]
    features = build_feature_matrix(history)
    registry = {"auto": "id-auto", "gbm": "id-gbm", "feature_ols": "id-fols"}

    rows = _make_forecast_rows(
        "m1", "c1", series, sanity=(100, 8000),
        features=features, pretrained_model=None, model_registry=registry,
        as_of=base + timedelta(days=n - 1)
    )

    assert len(rows) == 7
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["method"] == "ols" for r in rows)
    assert all(r["model_id"] == "id-auto" for r in rows)


def test_gbm_fallback_when_gbm_fit_fails(monkeypatch):
    """When GBM fit raises an exception, falls back gracefully to regression."""
    from unittest.mock import MagicMock

    from forecasting import engine as eng
    from forecasting.engine import _make_forecast_rows
    from forecasting.features import build_feature_matrix

    class _Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    mock_gbm = MagicMock()
    mock_gbm.fit.side_effect = RuntimeError("GBM fit failed")

    base = date(2026, 8, 1)
    n = 80
    history = [
        {
            "arrival_date": (base + timedelta(days=i)).isoformat(),
            "modal_price": 2000.0 + i * 5.0,
            "arrival_qty": 100.0 + (i % 7) * 10.0,
        }
        for i in range(n)
    ]
    series = [(base + timedelta(days=i), 2000.0 + i * 5.0) for i in range(n)]
    features = build_feature_matrix(history)
    registry = {"auto": "id-auto", "gbm": "id-gbm", "feature_ols": "id-fols"}

    rows = _make_forecast_rows(
        "m1", "c1", series, sanity=(100, 8000),
        features=features, pretrained_model=mock_gbm, model_registry=registry,
        as_of=base + timedelta(days=n - 1)
    )

    assert len(rows) == 7
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["method"] == "feature_ols" for r in rows)


def test_gbm_fallback_when_gbm_predict_fails(monkeypatch):
    """When GBM predict raises an exception, falls back gracefully to regression."""
    from unittest.mock import MagicMock

    from forecasting import engine as eng
    from forecasting.engine import _make_forecast_rows
    from forecasting.features import build_feature_matrix

    class _Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    mock_gbm = MagicMock()
    mock_gbm.fit.return_value = None
    mock_gbm.predict.side_effect = RuntimeError("GBM predict failed")
    mock_gbm.fallback = False

    base = date(2026, 8, 1)
    n = 80
    history = [
        {
            "arrival_date": (base + timedelta(days=i)).isoformat(),
            "modal_price": 2000.0 + i * 5.0,
            "arrival_qty": 100.0 + (i % 7) * 10.0,
        }
        for i in range(n)
    ]
    series = [(base + timedelta(days=i), 2000.0 + i * 5.0) for i in range(n)]
    features = build_feature_matrix(history)
    registry = {"auto": "id-auto", "gbm": "id-gbm", "feature_ols": "id-fols"}

    rows = _make_forecast_rows(
        "m1", "c1", series, sanity=(100, 8000),
        features=features, pretrained_model=mock_gbm, model_registry=registry,
        as_of=base + timedelta(days=n - 1)
    )

    assert len(rows) == 7
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["method"] == "feature_ols" for r in rows)


def test_gbm_fallback_when_gbm_has_fallback_flag(monkeypatch):
    """When GBM model instance has fallback=True, falls back to regression."""
    from forecasting import engine as eng
    from forecasting.engine import _make_forecast_rows
    from forecasting.features import build_feature_matrix
    from forecasting.gbm import GlobalGBM

    class _Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    # model=None sets fallback=True
    gbm_model = GlobalGBM(model=None, sigma=0.0, market_map={}, commodity_map={}, events=[], strict_pit=False)

    base = date(2026, 8, 1)
    n = 80
    history = [
        {
            "arrival_date": (base + timedelta(days=i)).isoformat(),
            "modal_price": 2000.0 + i * 5.0,
            "arrival_qty": 100.0 + (i % 7) * 10.0,
        }
        for i in range(n)
    ]
    series = [(base + timedelta(days=i), 2000.0 + i * 5.0) for i in range(n)]
    features = build_feature_matrix(history)
    registry = {"auto": "id-auto", "gbm": "id-gbm", "feature_ols": "id-fols"}

    rows = _make_forecast_rows(
        "m1", "c1", series, sanity=(100, 8000),
        features=features, pretrained_model=gbm_model, model_registry=registry,
        as_of=base + timedelta(days=n - 1)
    )

    assert len(rows) == 7
    assert all(r["status"] == "ok" for r in rows)
    assert all(r["method"] == "feature_ols" for r in rows)


def test_gbm_fallback_preserves_insufficient_data(monkeypatch):
    """When n < 10, GBM fallback correctly emits insufficient_data."""
    from forecasting import engine as eng
    from forecasting.engine import _make_forecast_rows

    class _Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(eng, "get_settings", lambda: _Settings())

    base = date(2026, 8, 1)
    series = [(base + timedelta(days=i), 2000.0) for i in range(5)]
    rows = _make_forecast_rows("m1", "c1", series, sanity=None, pretrained_model=None)
    assert len(rows) == 1
    assert rows[0]["status"] == "insufficient_data"
    assert rows[0]["predicted_price"] is None

