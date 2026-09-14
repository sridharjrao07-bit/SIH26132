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
    _global_model = None
    _global_sigma = None

    def __init__(self):
        try:
            import lightgbm
            import statsmodels
        except ImportError:
            raise ForecastModelError("Optional ML dependencies not installed")
            
        if GlobalGBM._global_model is None:
            self._train_global()

    @classmethod
    def _train_global(cls):
        from app.services.jobs import get_supabase_client
        from forecasting.features import build_feature_matrix
        import lightgbm as lgb
        
        supabase = get_supabase_client()
        cutoff = (date.today() - timedelta(days=150)).isoformat()
        
        # Paginated fetch for prices
        offset = 0
        all_rows = []
        while True:
            resp = supabase.table("prices").select("*").gte("arrival_date", cutoff).range(offset, offset + 1000).execute()
            if not resp.data:
                break
            all_rows.extend(resp.data)
            if len(resp.data) < 1000:
                break
            offset += 1000
            
        # Group by pair
        pairs = {}
        for r in all_rows:
            key = (r["market_id"], r["commodity_id"])
            pairs.setdefault(key, []).append(r)
            
        # Fetch weather and events
        weather = supabase.table("weather_daily").select("*").gte("observation_date", cutoff).execute().data or []
        events = supabase.table("events").select("*").gte("event_date", cutoff).execute().data or []
        
        X_train, y_train = [], []
        X_val, y_val = [], []
        
        # Determine cutoff based on max date in data
        max_d = None
        for (m, c), rows in pairs.items():
            for r in rows:
                try:
                    d = date.fromisoformat(r["arrival_date"])
                    if max_d is None or d > max_d:
                        max_d = d
                except Exception:
                    pass
        if max_d is None:
            max_d = date.today()
            
        val_cutoff = max_d - timedelta(days=30)
        
        from forecasting.engine import build_daily_series
        
        for (m, c), rows in pairs.items():
            series = build_daily_series(rows)
            if len(series) < 40:
                continue
                
            history_dicts = [{"arrival_date": d.isoformat(), "modal_price": p, "arrival_qty": r.get("arrival_qty", 0.0)} for (d, p), r in zip(series, rows)]
            features = build_feature_matrix(history_dicts, weather=weather, events=events, target_commodity_id=c)
            
            for (d, price), feat in zip(series, features):
                feat_vec = [
                    feat.day_offset,
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
                
                if d < val_cutoff:
                    X_train.append(feat_vec)
                    y_train.append(price)
                else:
                    X_val.append(feat_vec)
                    y_val.append(price)
                    
        if not X_train or not X_val:
            raise ForecastModelError("Degenerate matrix: not enough data to train global GBM")
            
        model = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=50,
            subsample=0.9,
            random_state=42
        )
        model.fit(X_train, y_train)
        
        val_preds = model.predict(X_val)
        residuals = [a - p for a, p in zip(y_val, val_preds)]
        sigma = pstdev(residuals) if len(residuals) > 1 else 0.0
        
        cls._global_model = model
        cls._global_sigma = sigma

    @classmethod
    def get_feature_importances(cls) -> List[Dict[str, Any]]:
        if cls._global_model is None:
            return []
        feature_names = [
            "day_offset", "dow", "lag_1", "lag_7", "lag_14", 
            "arrivals_7d_avg", "momentum_14d", "rain_7d_cum_mm", 
            "district_mean_price", "event_pressure"
        ]
        importances = cls._global_model.feature_importances_
        pairs = sorted(zip(feature_names, importances), key=lambda x: x[1], reverse=True)
        return [{"feature": f, "gain": round(float(g), 4)} for f, g in pairs[:10]]

    def fit(self, series: List[Tuple[date, float]], features: Optional[List[Any]] = None) -> None:
        if features is None or len(features) == 0:
            raise ValueError("GBM requires features")
        self.series = series
        self.features = features
        self.last_price = series[-1][1] if series else float('nan')

    def predict(self, horizon: int = 7) -> List[Tuple[float, float, float]]:
        if not self.series:
            return [(float('nan'), float('nan'), float('nan'))] * horizon
            
        results = []
        last_feat = self.features[-1]
        
        # We need to simulate recursive prediction
        # Store predictions for lag referencing
        sim_prices = [p for _, p in self.series]
        
        for i in range(1, horizon + 1):
            day_offset = last_feat.day_offset + i
            dow = (last_feat.dow + i) % 7
            lag_1 = sim_prices[-1]
            lag_7 = sim_prices[-7] if len(sim_prices) >= 7 else float('nan')
            lag_14 = sim_prices[-14] if len(sim_prices) >= 14 else float('nan')
            
            arrivals = last_feat.arrivals_7d_avg if last_feat.arrivals_7d_avg is not None else float('nan')
            momentum = lag_1 - lag_14 if not math.isnan(lag_14) else float('nan')
            rain = last_feat.rain_7d_cum_mm if last_feat.rain_7d_cum_mm is not None else float('nan')
            dist = last_feat.district_mean_price if last_feat.district_mean_price is not None else float('nan')
            evt = last_feat.event_pressure
            
            feat_vec = [[
                day_offset,
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
            
            p = GlobalGBM._global_model.predict(feat_vec)[0]
            if math.isnan(p):
                print("LGBM returned NaN for:", feat_vec)
            
            sim_prices.append(p)
            
            margin = 1.96 * GlobalGBM._global_sigma * math.sqrt(i)
            lo = max(0.0, p - margin)
            hi = p + margin
            results.append((round(p, 2), round(lo, 2), round(hi, 2)))
            
        return results
