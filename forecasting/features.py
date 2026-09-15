import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Dict, Optional, Any


@dataclass(frozen=True)
class FeatureRow:
    """A row in the feature matrix for the forecasting model.

    Point-in-time availability contract
    ------------------------------------
    All features use ONLY data that would be observable at the forecast origin
    (i.e., data available at close-of-day t-1, to predict price at t):

    - lag_1, lag_7, lag_14     : confirmed market observations from t-1, t-7, t-14
    - arrivals_7d_avg          : average of t-7..t-1 arrivals (all lagged)
    - momentum_14d             : (price[t-1] - price[t-15]) / price[t-15] — fully lagged
    - rain_7d_cum_mm           : cumulative precipitation t-7..t-1 (lagged; no same-day)
    - district_mean_price      : CAUTION — built from mandi data for date t, which would
                                 NOT be available until t+1. For production inference this
                                 must use the previous day's district average.
    - event_pressure           : computed only from events with event_date <= t-1.
                                 Events extracted retroactively (publication_date unknown)
                                 are approximate; flagged in evaluation reports.
    """
    day_offset: int          # Days since the start of the series
    dow: int                 # Day of week (0=Monday, 6=Sunday)
    lag_1: Optional[float]   # Price 1 day ago
    lag_7: Optional[float]   # Price 7 days ago
    lag_14: Optional[float]  # Price 14 days ago
    arrivals_7d_avg: Optional[float]  # 7-day average of arrivals (t-7..t-1)
    momentum_14d: Optional[float]     # (price[t-1] - price[t-15]) / price[t-15]
    rain_7d_cum_mm: Optional[float]   # 7-day cumulative rainfall (t-7..t-1)
    district_mean_price: Optional[float] # Mean price for the same commodity in the district (see caution above)
    event_pressure: float             # Computed event pressure score (-2.0 to 2.0)


def _compute_event_pressure(
    target_date: date,
    events: List[Dict[str, Any]],
    target_commodity_id: Optional[str] = None
) -> float:
    """
    Computes the event pressure score for a given target date based on the formula:
      sign(e) = +1/−1/0 for up/down/uncertain
      weight = 0.5/1.0/1.5 for minor/moderate/major
      eligible: event_date >= t−14d AND (commodity_id NULL OR == target)
      pressure = clamp(Σ sign·weight·confidence·exp(−0.3·age_days), −2.0, +2.0)
    """
    pressure = 0.0
    for e in events:
        evt_date_str = e.get("event_date")
        if not evt_date_str:
            continue
        try:
            evt_date = date.fromisoformat(evt_date_str)
        except ValueError:
            continue
            
        age_days = (target_date - evt_date).days
        
        # Must be in the last 14 days (and not in the future relative to target_date)
        if not (0 <= age_days <= 14):
            continue
            
        evt_commodity_id = e.get("commodity_id")
        if evt_commodity_id is not None and target_commodity_id is not None:
            if evt_commodity_id != target_commodity_id:
                continue
                
        confidence = e.get("confidence", 0.0)
        if confidence < 0.5:
            continue  # Quarantined events are excluded
            
        direction = e.get("direction", "uncertain")
        sign = 1.0 if direction == "up" else -1.0 if direction == "down" else 0.0
        if sign == 0.0:
            continue
            
        magnitude = e.get("magnitude", "moderate")
        weight = 0.5 if magnitude == "minor" else 1.5 if magnitude == "major" else 1.0
        
        pressure += sign * weight * confidence * math.exp(-0.3 * age_days)

    return max(-2.0, min(2.0, pressure))


def build_feature_matrix(
    series: List[Dict[str, Any]], 
    weather: List[Dict[str, Any]] = None, 
    events: List[Dict[str, Any]] = None,
    district_prices: List[Dict[str, Any]] = None,
    target_commodity_id: Optional[str] = None
) -> List[FeatureRow]:
    """
    Builds the feature matrix for the entire series.
    series: ordered list of dicts with 'arrival_date', 'modal_price', 'arrival_qty'
    weather: list of dicts with 'observation_date', 'precipitation_sum_mm'
    events: list of dicts with 'event_date', 'commodity_id', 'direction', 'magnitude', 'confidence'
    district_prices: list of dicts with 'arrival_date', 'mean_price'
    """
    if not series:
        return []
        
    weather = weather or []
    events = events or []
    district_prices = district_prices or []
    
    # Pre-index auxiliary data for fast lookups
    weather_by_date = {w["observation_date"]: w.get("precipitation_sum_mm", 0.0) for w in weather}
    district_by_date = {d["arrival_date"]: d.get("mean_price") for d in district_prices}
    
    start_date = date.fromisoformat(series[0]["arrival_date"])
    
    matrix = []
    
    # Create an index for price and arrivals lookup by date
    # Some dates might be missing in the input series
    series_by_date = {}
    for r in series:
        d = date.fromisoformat(r["arrival_date"])
        series_by_date[d] = r

    # We iterate over the series dates
    for r in series:
        curr_date = date.fromisoformat(r["arrival_date"])
        
        day_offset = (curr_date - start_date).days
        dow = curr_date.weekday()
        

        def get_lag_price(days_back):
            d = curr_date - timedelta(days=days_back)
            return series_by_date[d].get("modal_price") if d in series_by_date else None
            
        lag_1 = get_lag_price(1)
        lag_7 = get_lag_price(7)
        lag_14 = get_lag_price(14)
        
        # 7-day arrivals avg
        arr_sum = 0.0
        arr_count = 0
        for i in range(1, 8):
            d = curr_date - timedelta(days=i)
            if d in series_by_date:
                qty = series_by_date[d].get("arrival_qty")
                if qty is not None:
                    arr_sum += qty
                    arr_count += 1
        arrivals_7d_avg = (arr_sum / arr_count) if arr_count > 0 else None
        
        # Momentum: fractional change from t-15 to t-1 (no same-day data used).
        # This is strictly lagged: both observations must pre-date the forecast origin.
        # Returns None if either calendar-date observation is missing or denominator == 0.
        momentum_14d = None
        lag_15 = get_lag_price(15)
        if lag_1 is not None and lag_15 is not None and lag_15 != 0:
            momentum_14d = (lag_1 - lag_15) / lag_15
            
        # Rain 7d
        rain_sum = 0.0
        rain_count = 0
        for i in range(1, 8):
            d_str = (curr_date - timedelta(days=i)).isoformat()
            if d_str in weather_by_date:
                val = weather_by_date[d_str]
                if val is not None:
                    rain_sum += val
                    rain_count += 1
        # Only assign if we have at least some data in the last 7 days
        rain_7d_cum_mm = rain_sum if rain_count > 0 else None
        
        # District price: use the PREVIOUS day's average to avoid same-day leakage.
        # At forecast time for date t, the mandi data for t is not yet published.
        prev_day = (curr_date - timedelta(days=1)).isoformat()
        dist_price = district_by_date.get(prev_day)
        
        # Event pressure: only events with event_date < curr_date (strictly before).
        # Events on curr_date are not available until after market close.
        pressure = _compute_event_pressure(curr_date - timedelta(days=1), events, target_commodity_id)
        
        matrix.append(FeatureRow(
            day_offset=day_offset,
            dow=dow,
            lag_1=lag_1,
            lag_7=lag_7,
            lag_14=lag_14,
            arrivals_7d_avg=arrivals_7d_avg,
            momentum_14d=momentum_14d,
            rain_7d_cum_mm=rain_7d_cum_mm,
            district_mean_price=dist_price,
            event_pressure=pressure
        ))
        
    return matrix
