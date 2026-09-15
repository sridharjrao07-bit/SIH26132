from datetime import date, timedelta
from statistics import pstdev
from typing import List, Tuple, Optional, Any, Dict
import structlog
import math

logger = structlog.get_logger()

class ForecastModelError(Exception):
    pass

class GlobalGBM:
    name = "gbm"

    def __init__(self, model: Any, sigma: float, market_map: Dict[str, int], commodity_map: Dict[str, int]):
        self.model = model
        self.sigma = sigma
        self.market_map = market_map
        self.commodity_map = commodity_map
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
            importances = self.model.feature_importances_
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

    def predict(self, horizon: int = 7) -> List[Tuple[float, float, float]]:
        if not self.series:
            return [(float('nan'), float('nan'), float('nan'))] * horizon

        results = []
        last_feat = self.features[-1]
        
        m_code = self.market_map.get(self.market_id, len(self.market_map))
        c_code = self.commodity_map.get(self.commodity_id, len(self.commodity_map))

        # Independent recursive state
        sim_prices = [p for _, p in self.series]

        for i in range(1, horizon + 1):
            dow = (last_feat.dow + i) % 7
            lag_1 = sim_prices[-1]
            lag_7 = sim_prices[-7] if len(sim_prices) >= 7 else float('nan')
            lag_14 = sim_prices[-14] if len(sim_prices) >= 14 else float('nan')

            arrivals = last_feat.arrivals_7d_avg if last_feat.arrivals_7d_avg is not None else float('nan')
            momentum = float('nan')
            if not math.isnan(lag_1) and not math.isnan(lag_14) and lag_14 != 0:
                momentum = (lag_1 - lag_14) / lag_14
                
            rain = last_feat.rain_7d_cum_mm if last_feat.rain_7d_cum_mm is not None else float('nan')
            dist = last_feat.district_mean_price if last_feat.district_mean_price is not None else float('nan')
            evt = last_feat.event_pressure

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
            sim_prices.append(p)

            # Standard interval construction
            margin = 1.96 * self.sigma * math.sqrt(i)
            lo = max(0.0, p - margin)
            hi = p + margin
            results.append((round(p, 2), round(lo, 2), round(hi, 2)))

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

    from forecasting.engine import build_daily_series
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

    # Identify all known markets and commodities for deterministic encoding
    # Restricted strictly to the pre-cutoff training partition to avoid leakage
    all_markets = set()
    all_commodities = set()
    for (m, c), rows in pairs_history.items():
        for r in rows:
            d_str = r["arrival_date"]
            d = date.fromisoformat(d_str) if isinstance(d_str, str) else d_str
            if d < val_cutoff:
                all_markets.add(m)
                all_commodities.add(c)
                break
        
    market_map = {m: i for i, m in enumerate(sorted(list(all_markets)))}
    commodity_map = {c: i for i, c in enumerate(sorted(list(all_commodities)))}

    X_all, y_all, dates_all = [], [], []

    # Build dataset
    for (m, c), rows in pairs_history.items():
        series = build_daily_series(rows)
        if len(series) < 10:
            continue

        # Convert series into dicts for build_feature_matrix
        # Re-attach arrival_qty if present in rows for the day.
        # This matches what engine does implicitly.
        by_date = {}
        for r in rows:
            d_str = r["arrival_date"]
            d = date.fromisoformat(d_str) if isinstance(d_str, str) else d_str
            by_date.setdefault(d, []).append(r)
            
        history_dicts = []
        for d, p in series:
            # simple fallback: use the first arrival_qty found on that day
            day_rows = by_date.get(d, [])
            qty = day_rows[0].get("arrival_qty", 0.0) if day_rows else 0.0
            history_dicts.append({"arrival_date": d.isoformat(), "modal_price": p, "arrival_qty": qty})

        features = build_feature_matrix(
            series=history_dicts,
            weather=[w for w in weather if w.get("market_id") == m],
            events=events,
            district_prices=[], # could pass district_prices filter if required
            target_commodity_id=c,
            strict_pit=strict_pit
        )

        # Use len(map) as the "unknown" code for pairs appearing only in validation
        m_code = market_map.get(m, len(market_map))
        c_code = commodity_map.get(c, len(commodity_map))

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

    # val_cutoff is already computed above.

    X_train, y_train = [], []
    X_val, y_val = [], []

    for x, y, d in zip(X_all, y_all, dates_all):
        if d < val_cutoff:
            X_train.append(x)
            y_train.append(y)
        else:
            X_val.append(x)
            y_val.append(y)

    if not X_train:
        # Fallback if too little data: train on all, use arbitrary sigma
        X_train, y_train = X_all, y_all
        sigma = pstdev(y_all) if len(y_all) > 1 else 0.0
    else:
        model = lgb.LGBMRegressor(
            n_estimators=150,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.9,
            random_state=42
        )
        model.fit(X_train, y_train, categorical_feature=[0, 1])
        
        if X_val:
            val_preds = model.predict(X_val)
            residuals = [a - p for a, p in zip(y_val, val_preds)]
            sigma = pstdev(residuals) if len(residuals) > 1 else 0.0
        else:
            sigma = pstdev(y_train) if len(y_train) > 1 else 0.0

        # Refit on all data for the final predictor.
        # NOTE: The reported sigma above estimates the error for the pre-refit model.
        # It does not directly represent the final refitted model's error. 
        # Interval coverage must be explicitly measured out-of-sample in the backtest.
        model = lgb.LGBMRegressor(
            n_estimators=150,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            subsample=0.9,
            random_state=42
        )
        model.fit(X_all, y_all, categorical_feature=[0, 1])

    return GlobalGBM(model=model, sigma=sigma, market_map=market_map, commodity_map=commodity_map)
