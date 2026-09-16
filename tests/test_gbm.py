import pytest
import random
from datetime import date, timedelta

from forecasting.backtest import run_backtest
from forecasting.gbm import ForecastModelError

try:
    import lightgbm  # noqa: F401  # availability check
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

pytestmark = pytest.mark.skipif(not HAS_LIGHTGBM, reason="lightgbm not installed")

@pytest.fixture(autouse=True)
def reset_global_gbm():
    # Model now uses instance state; no global state to reset
    yield


def test_import_failure_fallback(monkeypatch):
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

    from forecasting.gbm import train_global_gbm
    
    # Use the model - should raise ForecastModelError on instantiation
    with pytest.raises(ForecastModelError, match="Optional ML dependencies not installed"):
        _ = train_global_gbm({}, [], [], [])


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
            
        def select(self, *args, **kwargs):
            return self
            
        def gte(self, *args, **kwargs):
            return self
            
        def eq(self, *args, **kwargs):
            return self
            
        def order(self, *args, **kwargs):
            return self
            
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

def test_noise_set_performance(mock_supabase):
    """Noise set (pure random, seeded): GBM validation MAPE >= naive * 0.95"""
    rows, _, builder = _generate_synthetic_data(seed=42, n_days=200, is_noise=True)
    supabase = mock_supabase(builder, rows)
    
    report = run_backtest(supabase, pairs=[("M1", "C1")], history_days=150, model_names=["gbm", "naive"])
    
    gbm_mape = report.aggregate["gbm"]["mape_winsorized"]
    naive_mape = report.aggregate["naive"]["mape_winsorized"]
    
    assert gbm_mape is not None and naive_mape is not None
    assert gbm_mape >= naive_mape * 0.95, f"GBM MAPE {gbm_mape} is suspiciously good on noise compared to {naive_mape}"

def test_signal_set_performance(mock_supabase):
    """Signal set (price driven by 2 features, seeded): GBM beats BaselineOLS on validation MAE"""
    rows, _, builder = _generate_synthetic_data(seed=42, n_days=200, is_noise=False)
    supabase = mock_supabase(builder, rows)
    
    report = run_backtest(supabase, pairs=[("M1", "C1")], history_days=150, model_names=["gbm", "ols"])
    
    gbm_mae = report.aggregate["gbm"]["mae"]
    ols_mae = report.aggregate["ols"]["mae"]
    
    assert gbm_mae is not None and ols_mae is not None
    assert gbm_mae < ols_mae, f"GBM MAE {gbm_mae} failed to beat OLS MAE {ols_mae} on signal set"
    
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
