"""
forecasting/features.py — Point-in-time feature matrix construction.

Publication-date / availability contract
-----------------------------------------
Events have two date fields:
  event_date        — when the agricultural event occurred.
  publication_date  — earliest date the event record was available for prediction.
                      NULL means availability is unknown (historical seed data).

When strict_pit=True (used in backtests and any quantitative evaluation):
  This enacts a **publication-time retrospective evaluation**.
  An event is eligible for a forecast at origin T ONLY if:
    publication_date IS NOT NULL AND publication_date < T

  Events with publication_date IS NULL are EXCLUDED entirely.
  This prevents retroactive leakage from articles published after T
  even when the underlying event_date pre-dates T.

  NOTE: This does NOT fully reconstruct actual deployed availability,
  as it lacks protection against retrospective review changes or true
  ingestion delay tracking.

When strict_pit=False (default for production inference):
  Falls back to: event_date < T (same-day excluded).
  This approximation is acceptable for live forecasting where the runner
  populates publication_date = today() at insert time, so newly ingested
  events are always tagged. The only remaining approximation is for seed/
  historical events (publication_date NULL), which are still included with
  an explicit note in the accuracy card.

District price availability
---------------------------
district_mean_price uses the previous calendar day's data to prevent
same-day leakage. winner-row construction is identical to build_daily_series.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FeatureRow:
    """A row in the feature matrix for the forecasting model.

    Point-in-time availability contract
    ------------------------------------
    All features use ONLY data observable at the forecast origin T
    (data available at close-of-day T-1, to predict price at T):

    - lag_1, lag_7, lag_14     : confirmed mandi observations from T-1, T-7, T-14
    - arrivals_7d_avg          : average of T-7..T-1 arrivals (all lagged)
    - momentum_14d             : (price[T-1] - price[T-15]) / price[T-15] — fully lagged
    - rain_7d_cum_mm           : cumulative precipitation T-7..T-1 (lagged; no same-day)
    - district_mean_price      : previous calendar day's district average (T-1), lagged
    - event_pressure           : events with publication_date < T (strict_pit=True)
                                 OR event_date < T (strict_pit=False, approximate).
                                 Value is 0.0 and events_approximate=True when
                                 strict_pit=False is used or unknown-availability
                                 events are the only eligible source.
    - events_approximate       : True when event_pressure may be contaminated by
                                 retroactive information (strict_pit=False or
                                 publication_date=NULL events were included).
    """

    day_offset: int  # Days since the start of the series
    dow: int  # Day of week (0=Monday, 6=Sunday)
    lag_1: Optional[float]  # Price 1 day ago
    lag_7: Optional[float]  # Price 7 days ago
    lag_14: Optional[float]  # Price 14 days ago
    arrivals_7d_avg: Optional[float]  # 7-day average of arrivals (T-7..T-1)
    momentum_14d: Optional[float]  # (price[T-1] - price[T-15]) / price[T-15]
    rain_7d_cum_mm: Optional[float]  # 7-day cumulative rainfall (T-7..T-1)
    district_mean_price: Optional[float]  # Previous-day district average (see contract)
    event_pressure: float  # Computed event pressure score (-2.0 to 2.0)
    events_approximate: bool = False  # True when event_pressure is not PIT-clean
    # NOTE: 0.0 is also returned when all eligible events are excluded by provenance
    # (fixture/unknown). events_approximate remains False in that case — a genuine
    # zero (no signal) is different from an approximate non-zero signal.


def _compute_event_pressure(
    forecast_origin: date,
    events: List[Dict[str, Any]],
    target_commodity_id: Optional[str] = None,
    strict_pit: bool = False,
    target_date: Optional[date] = None,
) -> tuple[float, bool]:
    """
    Compute event pressure score at *forecast_origin* for *target_date*.

    Parameters
    ----------
    forecast_origin : date
        The date at which the forecast is being made (T). Only events
        available strictly before this date are eligible.
    events : list of event dicts
        Each dict may have: event_date, publication_date, commodity_id,
        direction, magnitude, confidence.
        If the dict carries a `provenance_mode` field (from a JOIN to
        source_documents), events whose provenance_mode is NOT 'live' are
        unconditionally excluded. Absent or None provenance_mode is treated
        as 'unknown' and excluded as well. This ensures fixture and legacy
        seed data never influence evaluation or production forecasts.
    target_commodity_id : str or None
        If set, exclude events for other commodities.
    strict_pit : bool
        If True: require publication_date IS NOT NULL AND < forecast_origin.
                 Events with NULL publication_date are excluded entirely.
        If False: require event_date < forecast_origin (approximate).
                  Events with NULL publication_date are included if event_date
                  satisfies the filter.
    target_date : date, optional
        The future date the prediction is for. Determines the age of the event.
        Defaults to forecast_origin if not provided.

    Returns
    -------
    (pressure: float, approximate: bool)
        pressure       : clamped score in [-2.0, 2.0]; 0.0 if no eligible events
        approximate    : True when strict_pit=False or any included event has
                         publication_date=NULL (retroactive leakage is possible)
    """
    pressure = 0.0
    has_live = any((e.get("provenance_mode") or "unknown") == "live" for e in events)
    approximate = (not strict_pit) and has_live
    target_date = target_date or forecast_origin

    for e in events:
        # ── Provenance gate ───────────────────────────────────────────────────
        # Only 'live' provenance events are eligible for evaluation and production
        # forecasts. 'fixture' and 'unknown' (including absent/None) are excluded.
        # This prevents test fixtures and historical seed data from influencing
        # official evaluation metrics or live recommendations.
        provenance = e.get("provenance_mode") or "unknown"
        if provenance != "live":
            continue
        # ─────────────────────────────────────────────────────────────────────

        evt_date_str = e.get("event_date")
        if not evt_date_str:
            continue
        try:
            evt_date = date.fromisoformat(str(evt_date_str))
        except ValueError:
            continue

        pub_date_str = e.get("publication_date")

        if strict_pit:
            # Require an explicit, non-null publication_date.
            if pub_date_str is None:
                continue  # unknown availability — excluded from strict evaluation
            try:
                pub_date = date.fromisoformat(str(pub_date_str))
            except ValueError:
                continue
            if pub_date >= forecast_origin:
                continue  # not yet available at forecast_origin
        else:
            # Approximate: use event_date as proxy for availability.
            if evt_date >= forecast_origin:
                continue  # event itself not yet "known" by event_date filter
            # If publication_date IS set and is AFTER origin, also exclude:
            if pub_date_str is not None:
                try:
                    pub_date = date.fromisoformat(str(pub_date_str))
                    if pub_date >= forecast_origin:
                        continue
                except ValueError:
                    pass
            elif not strict_pit:
                # pub_date is NULL in non-strict mode → mark as approximate
                approximate = True

        # Commodity filter
        evt_commodity_id = e.get("commodity_id")
        if evt_commodity_id is not None and target_commodity_id is not None:
            if str(evt_commodity_id) != str(target_commodity_id):
                continue

        confidence = float(e.get("confidence", 0.0))
        if confidence < 0.5:
            continue  # quarantined confidence

        direction = e.get("direction", "uncertain")
        sign = 1.0 if direction == "up" else -1.0 if direction == "down" else 0.0
        if sign == 0.0:
            continue

        magnitude = e.get("magnitude", "moderate")
        weight = 0.5 if magnitude == "minor" else 1.5 if magnitude == "major" else 1.0

        age_days = (target_date - evt_date).days
        if not (0 <= age_days <= 14):
            continue

        pressure += sign * weight * confidence * math.exp(-0.3 * age_days)

    return max(-2.0, min(2.0, pressure)), approximate


def build_feature_matrix(
    series: List[Dict[str, Any]],
    weather: List[Dict[str, Any]] = None,
    events: List[Dict[str, Any]] = None,
    district_prices: List[Dict[str, Any]] = None,
    target_commodity_id: Optional[str] = None,
    strict_pit: bool = False,
) -> List[FeatureRow]:
    """
    Build the feature matrix for the entire series.

    Parameters
    ----------
    series : list of dicts
        Ordered price observations. Keys: arrival_date, modal_price, arrival_qty.
    weather : list of dicts
        Keys: observation_date, precipitation_sum_mm.
    events : list of dicts
        Keys: event_date, publication_date (may be None), commodity_id,
        direction, magnitude, confidence.
    district_prices : list of dicts
        Keys: arrival_date, mean_price.
    target_commodity_id : str, optional
        Used to filter events by commodity.
    strict_pit : bool
        Passed through to _compute_event_pressure.
        Set True during backtests and quantitative evaluation.
        Set False for production inference (approximation disclosed in FeatureRow).
    """
    if not series:
        return []

    weather = weather or []
    events = events or []
    district_prices = district_prices or []

    # Pre-index auxiliary data
    weather_by_date = {w["observation_date"]: w.get("precipitation_sum_mm", 0.0) for w in weather}
    district_by_date = {d["arrival_date"]: d.get("mean_price") for d in district_prices}

    start_date = date.fromisoformat(series[0]["arrival_date"])

    # Index price series by date for O(1) lag lookups
    series_by_date: Dict[date, Dict] = {}
    for r in series:
        d = date.fromisoformat(r["arrival_date"])
        series_by_date[d] = r

    matrix: List[FeatureRow] = []

    for r in series:
        curr_date = date.fromisoformat(r["arrival_date"])
        day_offset = (curr_date - start_date).days
        dow = curr_date.weekday()

        def get_lag_price(days_back: int) -> Optional[float]:
            d = curr_date - timedelta(days=days_back)
            return series_by_date[d].get("modal_price") if d in series_by_date else None

        lag_1 = get_lag_price(1)
        lag_7 = get_lag_price(7)
        lag_14 = get_lag_price(14)

        # Arrivals: 7-day average, fully lagged (T-7 .. T-1)
        arr_sum, arr_count = 0.0, 0
        for i in range(1, 8):
            d = curr_date - timedelta(days=i)
            if d in series_by_date:
                qty = series_by_date[d].get("arrival_qty")
                if qty is not None:
                    arr_sum += qty
                    arr_count += 1
        arrivals_7d_avg = (arr_sum / arr_count) if arr_count > 0 else None

        # Momentum: (price[T-1] - price[T-15]) / price[T-15]
        momentum_14d = None
        lag_15 = get_lag_price(15)
        if lag_1 is not None and lag_15 is not None and lag_15 != 0:
            momentum_14d = (lag_1 - lag_15) / lag_15

        # Rainfall: 7-day cumulative, lagged (T-7 .. T-1)
        rain_sum, rain_count = 0.0, 0
        for i in range(1, 8):
            d_str = (curr_date - timedelta(days=i)).isoformat()
            if d_str in weather_by_date:
                val = weather_by_date[d_str]
                if val is not None:
                    rain_sum += val
                    rain_count += 1
        rain_7d_cum_mm = rain_sum if rain_count > 0 else None

        # District price: use T-1 to avoid same-day leakage
        prev_day = (curr_date - timedelta(days=1)).isoformat()
        dist_price = district_by_date.get(prev_day)

        # Event pressure: forecast_origin = curr_date (events must be available
        # strictly before curr_date, per publication_date contract)
        pressure, approx = _compute_event_pressure(
            forecast_origin=curr_date,
            events=events,
            target_commodity_id=target_commodity_id,
            strict_pit=strict_pit,
        )

        matrix.append(
            FeatureRow(
                day_offset=day_offset,
                dow=dow,
                lag_1=lag_1,
                lag_7=lag_7,
                lag_14=lag_14,
                arrivals_7d_avg=arrivals_7d_avg,
                momentum_14d=momentum_14d,
                rain_7d_cum_mm=rain_7d_cum_mm,
                district_mean_price=dist_price,
                event_pressure=pressure,
                events_approximate=approx,
            )
        )

    return matrix
