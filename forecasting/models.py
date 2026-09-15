import structlog
from statistics import pstdev
from datetime import date
from typing import List, Optional
from forecasting.features import FeatureRow

logger = structlog.get_logger()
CONFIDENCE_Z = 1.96

def gaussian_elimination(A: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """Solve Ax = b using Gaussian elimination with partial pivoting."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    
    for i in range(n):
        max_el = abs(M[i][i])
        max_row = i
        for k in range(i + 1, n):
            if abs(M[k][i]) > max_el:
                max_el = abs(M[k][i])
                max_row = k
                
        if max_el < 1e-10:
            return None
            
        M[i], M[max_row] = M[max_row], M[i]
        
        for k in range(i + 1, n):
            c = -M[k][i] / M[i][i]
            for j in range(i, n + 1):
                if i == j:
                    M[k][j] = 0
                else:
                    M[k][j] += c * M[i][j]
                    
    x = [0.0 for _ in range(n)]
    for i in range(n - 1, -1, -1):
        if abs(M[i][i]) < 1e-10:
            return None
        x[i] = M[i][n] / M[i][i]
        for k in range(i - 1, -1, -1):
            M[k][n] -= M[k][i] * x[i]
            
    return x

class FeatureOLSModel:
    def __init__(self, prices: List[float], features: List[FeatureRow]):
        self.prices = prices
        self.features = features
        self.fallback = False
        self.beta = None
        self.sigma = 0.0
        self.valid_cols = []
        
        # We need y_t = beta^T X_{t-1}
        # Train on i = 0 to n-2 (X) and i = 1 to n-1 (y)
        n = len(prices)
        if n < 2 or len(features) != n:
            self.fallback = True
            return
            
        X_raw = []
        for i in range(n - 1):
            f = features[i]
            row = [
                1.0, 
                f.lag_1, f.lag_7, f.lag_14, 
                f.arrivals_7d_avg, f.momentum_14d, 
                f.rain_7d_cum_mm, f.district_mean_price, 
                f.event_pressure
            ]
            X_raw.append(row)
            
        y_train = prices[1:]
        
        # Mean imputation and column dropping
        num_cols = len(X_raw[0])
        col_means = []
        keep_cols = []
        
        for c in range(num_cols):
            vals = [X_raw[r][c] for r in range(n - 1) if X_raw[r][c] is not None]
            if not vals:
                col_means.append(None)
            else:
                mean_val = sum(vals) / len(vals)
                col_means.append(mean_val)
                # Keep bias (c==0) or columns that vary
                if c == 0:
                    keep_cols.append(c)
                else:
                    variance = sum((v - mean_val)**2 for v in vals) / len(vals)
                    if variance > 1e-10:
                        keep_cols.append(c)
                
        self.keep_cols = keep_cols
        self.col_means = col_means
        
        p = len(keep_cols)
        if p == 0 or (n - 1) < 10 * p:
            logger.warning("feature_ols_fallback", reason="insufficient_data", n=n-1, p=p)
            self.fallback = True
            return
            
        # Impute and build final X
        X = []
        for r in range(n - 1):
            row = []
            for c in keep_cols:
                val = X_raw[r][c]
                if val is None:
                    row.append(col_means[c])
                else:
                    row.append(val)
            X.append(row)
            
        # Normal equations: X^T X beta = X^T y
        Xt = list(zip(*X))
        XtX = [[sum(a * b for a, b in zip(Xt_row, Xt_col)) for Xt_col in Xt] for Xt_row in Xt]
        Xty = [sum(a * b for a, b in zip(Xt_row, y_train)) for Xt_row in Xt]
        
        beta = gaussian_elimination(XtX, Xty)
        if beta is None:
            logger.warning("feature_ols_fallback", reason="rank_deficient")
            self.fallback = True
            return
            
        self.beta = beta
        
        # Calculate sigma
        fitted = [sum(b * x for b, x in zip(self.beta, X[r])) for r in range(n - 1)]
        residuals = [y - f for y, f in zip(y_train, fitted)]
        self.sigma = pstdev(residuals) if len(residuals) > 1 else 0.0

    def _get_feature_vector(self, f: FeatureRow) -> List[float]:
        raw = [
            1.0, 
            f.lag_1, f.lag_7, f.lag_14, 
            f.arrivals_7d_avg, f.momentum_14d, 
            f.rain_7d_cum_mm, f.district_mean_price, 
            f.event_pressure
        ]
        vec = []
        for c in self.keep_cols:
            val = raw[c] if raw[c] is not None else self.col_means[c]
            vec.append(val)
        return vec

    def predict(self, horizon: int = 7, forecast_origin: Optional[date] = None) -> List[float]:
        if self.fallback:
            # We defer to the engine's fallback logic
            raise RuntimeError("predict called on fallback model")
            
        preds = []
        
        # We start forecasting using features[-1] to get pred_1
        # Then we dynamically update lag_1, lag_7, lag_14, momentum_14d
        current_f = self.features[-1]
        sim_prices = self.prices[:]
        
        for h in range(horizon):
            # Compute momentum
            lag_14_idx = len(sim_prices) - 14
            momentum = None
            if lag_14_idx >= 0:
                momentum = sim_prices[-1] - sim_prices[lag_14_idx]
                
            # Create a virtual feature row for this step
            vf = FeatureRow(
                day_offset=current_f.day_offset + h,
                dow=(current_f.dow + h) % 7,
                lag_1=sim_prices[-1],
                lag_7=sim_prices[-7] if len(sim_prices) >= 7 else current_f.lag_7,
                lag_14=sim_prices[-14] if len(sim_prices) >= 14 else current_f.lag_14,
                arrivals_7d_avg=current_f.arrivals_7d_avg, # Forward fill
                momentum_14d=momentum if momentum is not None else current_f.momentum_14d,
                rain_7d_cum_mm=current_f.rain_7d_cum_mm, # Forward fill
                district_mean_price=current_f.district_mean_price, # Forward fill
                event_pressure=current_f.event_pressure # Forward fill
            )
            
            vec = self._get_feature_vector(vf)
            pred = sum(b * x for b, x in zip(self.beta, vec))
            sim_prices.append(pred)
            preds.append(pred)
            
        return preds


class HoltWintersModel:
    def __init__(self, prices: List[float]):
        self.prices = prices
        self.fallback = False
        self.model_fit = None
        
        if len(prices) < 30:
            self.fallback = True
            return
            
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
        except ImportError:
            self.fallback = True
            return
            
        # Try full model
        try:
            # We must use list(prices) because sometimes prices is a tuple or similar in tests
            self.model_fit = ExponentialSmoothing(
                list(prices), 
                trend="add", 
                damped_trend=True, 
                seasonal="add", 
                seasonal_periods=7
            ).fit(optimized=True)
        except Exception:
            # Convergence failure -> retry without seasonal
            try:
                self.model_fit = ExponentialSmoothing(
                    list(prices), 
                    trend="add", 
                    damped_trend=True, 
                    seasonal=None
                ).fit(optimized=True)
            except Exception:
                self.fallback = True

    def predict(self, horizon: int = 7, forecast_origin: Optional[date] = None) -> List[float]:
        if self.fallback:
            raise RuntimeError("predict called on fallback model")
            
        forecasts = self.model_fit.forecast(horizon)
        
        # Calculate sigma from in-sample residuals if not already done
        if not hasattr(self, 'sigma'):
            residuals = self.model_fit.resid
            self.sigma = pstdev(residuals) if len(residuals) > 1 else 0.0
        
        return list(forecasts)
