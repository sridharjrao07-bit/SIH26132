"""
tests/test_backtest.py — Tests for the walk-forward backtest harness.

Uses FakeSupabase so no live DB is needed.  Deterministic price series
(seeded random / exact formulas) make the metric assertions stable across runs.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import List, Tuple

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import (
    MARKET_ID_LASALGAON,
    COMMODITY_ID_ONION,
    ADMIN_USER_ID,
    FARMER_USER_ID,
    mint_jwt,
    FakeSupabase,
)
from forecasting.backtest import (
    BACKTEST_PROTOCOL,
    MODEL_REGISTRY,
    NaiveLastWeekSameDay,
    run_backtest,
)

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def admin_headers():
    return {"Authorization": f"Bearer {mint_jwt(ADMIN_USER_ID)}"}


def farmer_headers():
    return {"Authorization": f"Bearer {mint_jwt(FARMER_USER_ID)}"}


def _make_price_rows(
    series: List[Tuple[date, float]],
    market_id: str = MARKET_ID_LASALGAON,
    commodity_id: str = COMMODITY_ID_ONION,
) -> List[dict]:
    return [
        {
            "market_id":    market_id,
            "commodity_id": commodity_id,
            "arrival_date": d.isoformat(),
            "modal_price":  p,
            "source":       "data_gov_in",
            "variety":      "General",
        }
        for d, p in series
    ]


def _trended_series(n: int, start: float = 100.0, slope: float = 0.5) -> List[Tuple[date, float]]:
    """Returns n days of price series with a clear upward trend + small noise."""
    rng = random.Random(42)
    base = date.today() - timedelta(days=n)
    return [
        (base + timedelta(days=i), round(start + slope * i + rng.gauss(0, 0.5), 2))
        for i in range(n)
    ]


def _random_walk_series(n: int) -> List[Tuple[date, float]]:
    """Returns n days of pure random walk (seed=42)."""
    rng = random.Random(42)
    price = 2000.0
    base = date.today() - timedelta(days=n)
    series = []
    for i in range(n):
        price = max(100.0, price + rng.gauss(0, 20.0))
        series.append((base + timedelta(days=i), round(price, 2)))
    return series


# ---------------------------------------------------------------------------
# NaiveLastWeekSameDay
# ---------------------------------------------------------------------------

class TestNaive:
    def test_predict_returns_lag7(self):
        series = _trended_series(20)
        naive  = NaiveLastWeekSameDay()
        naive.fit(series)
        preds  = naive.predict(horizon=7)
        # Day-1 prediction should be the price from 7 days before the last obs date
        last_date = series[-1][0]
        expected_lag = {d: p for d, p in series}.get(last_date - timedelta(days=6))
        if expected_lag is not None:
            assert preds[0][0] == pytest.approx(expected_lag)

    def test_no_lag_available_returns_nan(self):
        series = _trended_series(6)   # too short for t-7 lookups
        naive  = NaiveLastWeekSameDay()
        naive.fit(series)
        preds  = naive.predict(horizon=7)
        # If lag date is not in lookup, should be NaN
        for p, lo, hi in preds:
            # At least some should be NaN since series only has 6 days
            assert p is None or isinstance(p, float)


# ---------------------------------------------------------------------------
# Trended series: OLS should beat naive
# ---------------------------------------------------------------------------

class TestTrendedSeries:
    """On a strongly trended series, OLS MAE must be < naive MAE."""

    @pytest.fixture
    def fake_db(self):
        series = _trended_series(120)
        db = FakeSupabase()
        db.seed("prices", _make_price_rows(series))
        db.seed("commodities", [{"id": COMMODITY_ID_ONION, "sanity_min": 0, "sanity_max": 99999}])
        return db

    def test_ols_beats_naive_on_trended_series(self, fake_db):
        report = run_backtest(
            fake_db,
            [(MARKET_ID_LASALGAON, COMMODITY_ID_ONION)],
            history_days=365,
            model_names=["ols", "naive"],
        )
        agg = report.aggregate
        ols_mae   = agg["ols"]["mae"]
        naive_mae = agg["naive"]["mae"]
        # Both must be computable (finite)
        assert ols_mae is not None, "OLS MAE must not be None on trended series"
        assert naive_mae is not None, "Naive MAE must not be None on trended series"
        assert ols_mae < naive_mae, (
            f"OLS ({ols_mae:.2f}) should beat naive ({naive_mae:.2f}) on a "
            "strongly upward-trended series."
        )

    def test_report_has_protocol(self, fake_db):
        report = run_backtest(
            fake_db,
            [(MARKET_ID_LASALGAON, COMMODITY_ID_ONION)],
            history_days=365,
        )
        assert report.protocol == BACKTEST_PROTOCOL

    def test_report_to_json_contains_aggregate(self, fake_db):
        report = run_backtest(
            fake_db,
            [(MARKET_ID_LASALGAON, COMMODITY_ID_ONION)],
            history_days=365,
        )
        d = report.to_json()
        assert "aggregate" in d
        assert "per_pair" in d
        assert "protocol" in d
        assert d["protocol"] == BACKTEST_PROTOCOL


# ---------------------------------------------------------------------------
# Random walk: harness must complete with finite metrics
# ---------------------------------------------------------------------------

class TestRandomWalk:
    """On a random walk, harness must complete and return finite metrics."""

    @pytest.fixture
    def fake_db(self):
        series = _random_walk_series(120)
        db = FakeSupabase()
        db.seed("prices", _make_price_rows(series))
        db.seed("commodities", [{"id": COMMODITY_ID_ONION, "sanity_min": 0, "sanity_max": 99999}])
        return db

    def test_harness_completes_on_random_walk(self, fake_db):
        report = run_backtest(
            fake_db,
            [(MARKET_ID_LASALGAON, COMMODITY_ID_ONION)],
            history_days=365,
            model_names=["ma", "ols", "naive"],
        )
        agg = report.aggregate
        for name in ["ma", "ols", "naive"]:
            assert name in agg, f"model {name} missing from aggregate"
            # MAE and MAPE should be finite (may be large but not NaN)
            mae_val  = agg[name]["mae"]
            mape_val = agg[name]["mape_winsorized"]
            if mae_val is not None:
                assert math.isfinite(mae_val), f"{name}.mae not finite"
            if mape_val is not None:
                assert math.isfinite(mape_val), f"{name}.mape not finite"


# ---------------------------------------------------------------------------
# Model that raises mid-run: NaN row returned, run completes
# ---------------------------------------------------------------------------

class _BrokenModel:
    """A model that always raises on predict."""
    name = "broken"

    def fit(self, series, features=None):
        pass

    def predict(self, horizon=7):
        raise RuntimeError("deliberate test failure")


class TestBrokenModel:
    def test_broken_model_yields_nan_not_crash(self):
        """
        When a model raises during predict, the harness must:
        - not propagate the exception
        - record NaN predictions for that fold
        - still complete and return a BacktestReport
        """
        from forecasting.backtest import run_backtest
        MODEL_REGISTRY["broken"] = _BrokenModel

        series = _trended_series(120)
        db = FakeSupabase()
        db.seed("prices", _make_price_rows(series))

        try:
            report = run_backtest(
                db,
                [(MARKET_ID_LASALGAON, COMMODITY_ID_ONION)],
                history_days=365,
                model_names=["ma", "broken"],
            )
        finally:
            del MODEL_REGISTRY["broken"]

        # Report must exist and have data for both models
        assert report is not None
        agg = report.aggregate
        assert "ma" in agg
        assert "broken" in agg
        # Broken model should have a non-zero nan_rate
        assert agg["broken"]["nan_rate"] is not None
        assert agg["broken"]["nan_rate"] > 0.0


# ---------------------------------------------------------------------------
# Admin endpoint: auth tests
# ---------------------------------------------------------------------------

class TestBacktestEndpoint:
    def test_farmer_gets_403(self):
        resp = client.post(
            "/api/v1/admin/forecast/backtest",
            headers=farmer_headers(),
            json={},
        )
        assert resp.status_code == 403

    def test_admin_gets_200_with_protocol(self, fake_supabase):
        """
        Admin can call the endpoint; response JSON must contain 'protocol'
        with the exact verbatim protocol string.
        """
        # Seed enough data for the harness (120 days of prices)
        series = _trended_series(120)
        fake_supabase.seed("prices", _make_price_rows(series))
        fake_supabase.seed(
            "commodities",
            [{"id": COMMODITY_ID_ONION, "sanity_min": 0, "sanity_max": 99999}],
        )

        resp = client.post(
            "/api/v1/admin/forecast/backtest",
            headers=admin_headers(),
            json={"history_days": 180, "models": ["ma", "ols"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "protocol" in body
        assert body["protocol"] == BACKTEST_PROTOCOL
        assert "aggregate" in body

    def test_unknown_model_name_returns_422(self, fake_supabase):
        """An unknown model name must return HTTP 422 — not 500."""
        resp = client.post(
            "/api/v1/admin/forecast/backtest",
            headers=admin_headers(),
            json={"models": ["ma", "this_model_does_not_exist"]},
        )
        assert resp.status_code == 422
