from datetime import date, timedelta

from forecasting.engine import _make_forecast_rows
from forecasting.features import build_feature_matrix


def _history(n=80):
    start = date(2026, 8, 1)
    rows = [
        {
            "arrival_date": (start + timedelta(days=i)).isoformat(),
            "modal_price": 2000.0 + i * 5.0,
            "arrival_qty": 100.0 + (i % 7) * 10.0,
        }
        for i in range(n)
    ]
    series = [(start + timedelta(days=i), 2000.0 + i * 5.0) for i in range(n)]
    return start, rows, series


def test_gbm_falls_back_to_feature_ols_with_observable_contract(monkeypatch):
    from forecasting import engine

    class Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(engine, "get_settings", lambda: Settings())
    start, history, series = _history()
    rows = _make_forecast_rows(
        "m1",
        "c1",
        series,
        sanity=(100, 8000),
        features=build_feature_matrix(history),
        pretrained_model=None,
        model_registry={"auto": "id-auto", "feature_ols": "id-feature-ols"},
        as_of=start + timedelta(days=len(series) - 1),
    )

    assert len(rows) == 7
    assert {row["method"] for row in rows} == {"feature_ols"}
    assert {row["model_id"] for row in rows} == {"id-feature-ols"}
    assert {row["fallback_from"] for row in rows} == {"gbm"}


def test_gbm_uses_tier_fallback_without_features(monkeypatch):
    from forecasting import engine

    class Settings:
        forecast_model = "gbm"

    monkeypatch.setattr(engine, "get_settings", lambda: Settings())
    start, _, series = _history(30)
    rows = _make_forecast_rows(
        "m1",
        "c1",
        series,
        sanity=(100, 8000),
        features=None,
        pretrained_model=None,
        model_registry={"auto": "id-auto", "feature_ols": "id-feature-ols"},
        as_of=start + timedelta(days=len(series) - 1),
    )

    assert len(rows) == 7
    assert {row["method"] for row in rows} == {"blend"}
    assert {row["model_id"] for row in rows} == {"id-auto"}
    assert {row["fallback_from"] for row in rows} == {"gbm"}


def test_gbm_keeps_gbm_identity_when_pretrained_model_succeeds(monkeypatch):
    from forecasting import engine

    class Settings:
        forecast_model = "gbm"

    class PretrainedGBM:
        sigma = 12.0

        def fit(self, series, features, pair_id=None):
            self.fitted_pair = pair_id

        def predict(self, horizon, forecast_origin):
            return [2200.0] * horizon

    monkeypatch.setattr(engine, "get_settings", lambda: Settings())
    start, history, series = _history()
    rows = _make_forecast_rows(
        "m1",
        "c1",
        series,
        sanity=(100, 8000),
        features=build_feature_matrix(history),
        pretrained_model=PretrainedGBM(),
        model_registry={"auto": "id-auto", "gbm": "id-gbm"},
        as_of=start + timedelta(days=len(series) - 1),
    )

    assert len(rows) == 7
    assert {row["method"] for row in rows} == {"gbm"}
    assert {row["model_id"] for row in rows} == {"id-gbm"}
    assert {row["fallback_from"] for row in rows} == {None}
