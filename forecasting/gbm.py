import math
from datetime import date, timedelta
from statistics import pstdev
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger()

class ForecastModelError(Exception):
    pass

class CalibrationError(ForecastModelError):
    pass

class GlobalGBM:
    name = "gbm"

    def __init__(self, model: Any, sigma: float, market_map: Dict[str, int], commodity_map: Dict[str, int], events: List[Dict], strict_pit: bool):
        self.model = model
        self.sigma = sigma
        self.market_map = market_map
        self.commodity_map = commodity_map
        self.events = events
        self.strict_pit = strict_pit
        self.series = []
        self.features = []
        self.market_id = ""
        self.commodity_id = ""

    def get_feature_importances(self) -> List[Dict[str, Any]]:
        if self.model is None:
            return []
        feature_names = [
            "market_id", "commodity_id", "dow", "lag_1", "lag_7", "lag_14",
            "arrivals_7d_avg", "momentum_14d", "rain_7d_cum_mm",
            "district_mean_price", "event_pressure"
        ]
        try:
            # We explicitly ask lightgbm for 'gain'. The sklearn wrapper
            # (LGBMRegressor) has no feature_importance() method; it lives
            # on the underlying Booster, exposed via `booster_`.
            importances = self.model.booster_.feature_importance(importance_type='gain')
            pairs = sorted(zip(feature_names, importances), key=lambda x: x[1], reverse=True)
            return [{"feature": f, "gain": round(float(g), 4)} for f, g in pairs[:10]]
        except Exception:
            return []

    def fit(self, series: List[Tuple[date, float]], features: Optional[List[Any]] = None, pair_id: Optional[Tuple[str, str]] = None) -> None:
        """
        Local fit method for the evaluation interface.
        For GBM, this just sets the local prediction state for recursive inference.
        """
        if features is None or len(features) == 0:
            raise ValueError("GBM requires features")
        self.series = series
        self.features = features
        if pair_id:
            self.market_id, self.commodity_id = pair_id
        else:
            self.market_id, self.commodity_id = "", ""

    def predict(self, horizon: int = 7, forecast_origin: Optional[date] = None) -> List[float]:
        if not self.series:
            return [float('nan')] * horizon

        if forecast_origin is None:
            forecast_origin = self.series[-1][0]

        results = []
        last_feat = self.features[-1]

        m_code = self.market_map.get(self.market_id, len(self.market_map))
        c_code = self.commodity_map.get(self.commodity_id, len(self.commodity_map))

        # Independent recursive state, date-indexed
        sim_prices_by_date = {d: p for d, p in self.series}

        from forecasting.features import _compute_event_pressure

        for i in range(1, horizon + 1):
            target_date = forecast_origin + timedelta(days=i)
            dow = target_date.weekday()

            lag_1 = sim_prices_by_date.get(target_date - timedelta(days=1), float('nan'))
            lag_7 = sim_prices_by_date.get(target_date - timedelta(days=7), float('nan'))
            lag_14 = sim_prices_by_date.get(target_date - timedelta(days=14), float('nan'))
            lag_15 = sim_prices_by_date.get(target_date - timedelta(days=15), float('nan'))

            arrivals = last_feat.arrivals_7d_avg if last_feat.arrivals_7d_avg is not None else float('nan')
            momentum = float('nan')
            if not math.isnan(lag_1) and not math.isnan(lag_15) and lag_15 != 0:
                momentum = (lag_1 - lag_15) / lag_15

            rain = last_feat.rain_7d_cum_mm if last_feat.rain_7d_cum_mm is not None else float('nan')
            dist = last_feat.district_mean_price if last_feat.district_mean_price is not None else float('nan')

            # Recompute event pressure for target_date using events strictly available at forecast_origin
            evt, _ = _compute_event_pressure(
                forecast_origin=forecast_origin,
                events=self.events,
                target_commodity_id=self.commodity_id,
                strict_pit=self.strict_pit,
                target_date=target_date
            )

            feat_vec = [[
                m_code,
                c_code,
                dow,
                lag_1,
                lag_7,
                lag_14,
                arrivals,
                momentum,
                rain,
                dist,
                evt
            ]]
            if self.model is None:
                raise ForecastModelError("Model not trained")

            p = self.model.predict(feat_vec)[0]
            sim_prices_by_date[target_date] = p

            # Use raw point predictions and let the shared post-processing engine handle interval math
            results.append(p)

        return results


def train_global_gbm(
    pairs_history: Dict[Tuple[str, str], List[Dict]],
    weather: List[Dict],
    events: List[Dict],
    district_prices: List[Dict],
    strict_pit: bool = False
) -> GlobalGBM:
    """
    Unified global training function for GBM.
    Builds the feature matrix across all eligible pairs, performs a chronological
    calibration split to estimate sigma, and fits the global predictor.
    """
    try:
        import lightgbm as lgb
    except ImportError:
        raise ForecastModelError("Optional ML dependencies not installed")

    from forecasting.engine import build_daily_rows
    from forecasting.features import build_feature_matrix

    # Find max date across all pairs to define val_cutoff
    max_date = date.min
    for _, rows in pairs_history.items():
        for r in rows:
            d_str = r["arrival_date"]
            d = date.fromisoformat(d_str) if isinstance(d_str, str) else d_str
            if d > max_date:
                max_date = d

    if max_date == date.min:
        raise ForecastModelError("No data available to train global GBM")

    # Calibration split: last 14 days of data across the entire universe
    val_cutoff = max_date - timedelta(days=14)

    # 1. Identify all known markets and commodities for inner-training deterministic encoding
    # Restricted strictly to the pre-cutoff training partition to avoid leakage
    all_markets_inner = set()
    all_commodities_inner = set()
    for (m, c), rows in pairs_history.items():
        for r in rows:
            d_str = r["arrival_date"]
            d = date.fromisoformat(d_str) if isinstance(d_str, str) else d_str
            if d < val_cutoff:
                all_markets_inner.add(m)
                all_commodities_inner.add(c)
                break

    market_map_inner = {m: i for i, m in enumerate(sorted(list(all_markets_inner)))}
    commodity_map_inner = {c: i for i, c in enumerate(sorted(list(all_commodities_inner)))}

    X_all, y_all, dates_all = [], [], []

    # Build dataset
    for (m, c), rows in pairs_history.items():
        # Minimum eligibility for pair inclusion
        if len(rows) < 40:
            continue

        daily_rows = build_daily_rows(rows)
        series = [(d, float(row["modal_price"])) for d, row in daily_rows]

        if len(series) < 40:
            continue

        history_dicts = []
        for d, row in daily_rows:
            qty = row.get("arrival_qty", 0.0)
            history_dicts.append({"arrival_date": d.isoformat(), "modal_price": float(row["modal_price"]), "arrival_qty": qty})

        features = build_feature_matrix(
            series=history_dicts,
            weather=[w for w in weather if w.get("market_id") == m],
            events=events,
            district_prices=[], # district filtering not applied globally here
            target_commodity_id=c,
            strict_pit=strict_pit
        )

        # Use len(map) as the "unknown" code for pairs appearing only in validation
        m_code = market_map_inner.get(m, len(market_map_inner))
        c_code = commodity_map_inner.get(c, len(commodity_map_inner))

        for (d, price), feat in zip(series, features):
            feat_vec = [
                m_code,
                c_code,
                feat.dow,
                feat.lag_1 if feat.lag_1 is not None else float('nan'),
                feat.lag_7 if feat.lag_7 is not None else float('nan'),
                feat.lag_14 if feat.lag_14 is not None else float('nan'),
                feat.arrivals_7d_avg if feat.arrivals_7d_avg is not None else float('nan'),
                feat.momentum_14d if feat.momentum_14d is not None else float('nan'),
                feat.rain_7d_cum_mm if feat.rain_7d_cum_mm is not None else float('nan'),
                feat.district_mean_price if feat.district_mean_price is not None else float('nan'),
                feat.event_pressure
            ]
            X_all.append(feat_vec)
            y_all.append(price)
            dates_all.append(d)

    X_train, y_train = [], []
    X_val, y_val = [], []

    for x, y, d in zip(X_all, y_all, dates_all):
        if d < val_cutoff:
            X_train.append(x)
            y_train.append(y)
        else:
            X_val.append(x)
            y_val.append(y)

    # Minimum inner-training and calibration observations
    if len(X_train) < 10 or len(X_val) < 5:
        raise CalibrationError("Insufficient global data for valid inner-training and calibration split")

    import numpy as np

    # Chronological early stopping: fit on the pre-cutoff partition and use the
    # post-cutoff calibration window as eval set. LightGBM requires array-like
    # eval inputs, so convert to numpy.
    X_train_arr = np.asarray(X_train, dtype=float)
    y_train_arr = np.asarray(y_train, dtype=float)
    X_val_arr = np.asarray(X_val, dtype=float)
    y_val_arr = np.asarray(y_val, dtype=float)

    MAX_ESTIMATORS = 150
    model = lgb.LGBMRegressor(
        n_estimators=MAX_ESTIMATORS,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=5,
        subsample=0.9,
        subsample_freq=1,
        random_state=42,
        verbose=-1
    )
    # lightgbm >= 4.7 deprecates `eval_set` in favour of `eval_X`/`eval_y`;
    # the repo pin (4.6.0) only supports `eval_set`. Detect at runtime so the
    # code is warning-free on new versions and functional on the pin.
    import inspect
    _es_callback = lgb.early_stopping(stopping_rounds=20, verbose=False)
    if "eval_X" in inspect.signature(model.fit).parameters:
        model.fit(
            X_train_arr,
            y_train_arr,
            eval_X=X_val_arr,
            eval_y=y_val_arr,
            callbacks=[_es_callback]
        )
    else:
        model.fit(
            X_train_arr,
            y_train_arr,
            eval_set=[(X_val_arr, y_val_arr)],
            callbacks=[_es_callback]
        )
    # best_iteration_ is 0 when early stopping never engaged; guard the refit.
    best_n = int(model.best_iteration_ or 0) or MAX_ESTIMATORS

    val_preds = model.predict(X_val_arr)
    residuals = [a - p for a, p in zip(y_val, val_preds)]
    sigma = pstdev(residuals) if len(residuals) > 1 else 0.0

    # Final Refit: Rebuild categorical maps using ALL data to not unnecessarily collapse known identities
    all_markets_final = set()
    all_commodities_final = set()
    for (m, c), rows in pairs_history.items():
        if len(rows) >= 40:
            all_markets_final.add(m)
            all_commodities_final.add(c)

    market_map_final = {m: i for i, m in enumerate(sorted(list(all_markets_final)))}
    commodity_map_final = {c: i for i, c in enumerate(sorted(list(all_commodities_final)))}

    # Rebuild the full training matrix with the final categorical maps.
    # X and y are appended in the SAME loop iteration so features and targets
    # can never desynchronize (previously y_all from the first pass was reused,
    # which relied on both loops producing identical row order/counts).
    X_all_final = []
    y_all_final = []
    for (m, c), rows in pairs_history.items():
        if len(rows) < 40:
            continue

        daily_rows = build_daily_rows(rows)
        series = [(d, float(row["modal_price"])) for d, row in daily_rows]

        if len(series) < 40:
            continue

        history_dicts = []
        for d, row in daily_rows:
            qty = row.get("arrival_qty", 0.0)
            history_dicts.append({"arrival_date": d.isoformat(), "modal_price": float(row["modal_price"]), "arrival_qty": qty})

        features = build_feature_matrix(
            series=history_dicts,
            weather=[w for w in weather if w.get("market_id") == m],
            events=events,
            district_prices=[],
            target_commodity_id=c,
            strict_pit=strict_pit
        )

        m_code = market_map_final.get(m, len(market_map_final))
        c_code = commodity_map_final.get(c, len(commodity_map_final))

        for (d, price), feat in zip(series, features):
            feat_vec = [
                m_code,
                c_code,
                feat.dow,
                feat.lag_1 if feat.lag_1 is not None else float('nan'),
                feat.lag_7 if feat.lag_7 is not None else float('nan'),
                feat.lag_14 if feat.lag_14 is not None else float('nan'),
                feat.arrivals_7d_avg if feat.arrivals_7d_avg is not None else float('nan'),
                feat.momentum_14d if feat.momentum_14d is not None else float('nan'),
                feat.rain_7d_cum_mm if feat.rain_7d_cum_mm is not None else float('nan'),
                feat.district_mean_price if feat.district_mean_price is not None else float('nan'),
                feat.event_pressure
            ]
            X_all_final.append(feat_vec)
            y_all_final.append(price)

    # NOTE: The reported sigma above estimates the error for the pre-refit model.
    # It does not directly represent the final refitted model's error.
    # Interval coverage must be explicitly measured out-of-sample in the backtest.
    # Refit on ALL data at the early-stopped iteration count found above.
    model = lgb.LGBMRegressor(
        n_estimators=best_n,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=5,
        subsample=0.9,
        subsample_freq=1,
        random_state=42,
        verbose=-1
    )
    model.fit(np.asarray(X_all_final, dtype=float), np.asarray(y_all_final, dtype=float))

    return GlobalGBM(model=model, sigma=sigma, market_map=market_map_final, commodity_map=commodity_map_final, events=events, strict_pit=strict_pit)
