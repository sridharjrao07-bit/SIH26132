import math
from datetime import date
from forecasting.features import _compute_event_pressure

def test_event_pressure_hand_computed():
    # 2 events (up/moderate/0.8/age 0d; down/major/0.6/age 3d) → exact expected value with `exp(−0.9)`
    target_date = date(2026, 9, 14)
    events = [
        {
            "event_date": "2026-09-14",
            "direction": "up",
            "magnitude": "moderate",
            "confidence": 0.8
        },
        {
            "event_date": "2026-09-11",
            "direction": "down",
            "magnitude": "major",
            "confidence": 0.6
        }
    ]
    
    # Event 1: sign(up)=+1, weight(moderate)=1.0, conf=0.8, age=0 -> 1.0 * 1.0 * 0.8 * exp(0) = 0.8
    # Event 2: sign(down)=-1, weight(major)=1.5, conf=0.6, age=3 -> -1.0 * 1.5 * 0.6 * exp(-0.9) = -0.9 * exp(-0.9)
    # Total: 0.8 - 0.9 * exp(-0.9)
    
    expected = 0.8 - 0.9 * math.exp(-0.9)
    pressure = _compute_event_pressure(target_date, events)
    assert pressure == expected

def test_event_pressure_older_than_14d_excluded():
    target_date = date(2026, 9, 14)
    events = [
        {
            "event_date": "2026-08-30", # age 15
            "direction": "up",
            "magnitude": "major",
            "confidence": 1.0
        }
    ]
    assert _compute_event_pressure(target_date, events) == 0.0

def test_event_pressure_commodity_mismatch_excluded():
    target_date = date(2026, 9, 14)
    events = [
        {
            "event_date": "2026-09-14",
            "direction": "up",
            "magnitude": "moderate",
            "confidence": 0.8,
            "commodity_id": "other-uuid"
        },
        {
            "event_date": "2026-09-14",
            "direction": "down",
            "magnitude": "major",
            "confidence": 1.0,
            "commodity_id": None
        }
    ]
    # First is excluded due to mismatch, second is included because it's None.
    # Second: sign(-1) * weight(1.5) * conf(1.0) * exp(0) = -1.5
    assert _compute_event_pressure(target_date, events, "target-uuid") == -1.5

def test_event_pressure_clamped():
    target_date = date(2026, 9, 14)
    events = [
        {
            "event_date": "2026-09-14",
            "direction": "up",
            "magnitude": "major",
            "confidence": 1.0
        },
        {
            "event_date": "2026-09-14",
            "direction": "up",
            "magnitude": "major",
            "confidence": 1.0
        }
    ]
    # Each gives +1.5 -> total +3.0 -> clamped to +2.0
    assert _compute_event_pressure(target_date, events) == 2.0
    
    events_down = [
        {
            "event_date": "2026-09-14",
            "direction": "down",
            "magnitude": "major",
            "confidence": 1.0
        },
        {
            "event_date": "2026-09-14",
            "direction": "down",
            "magnitude": "major",
            "confidence": 1.0
        }
    ]
    # Each gives -1.5 -> total -3.0 -> clamped to -2.0
    assert _compute_event_pressure(target_date, events_down) == -2.0


# ── momentum_14d point-in-time tests ─────────────────────────────────────────

def _make_series(n: int, base_date: date, base_price: float = 1000.0):
    """Build a simple ascending price series with 1 obs per calendar day."""
    from datetime import timedelta
    return [
        {"arrival_date": (base_date + timedelta(days=i)).isoformat(),
         "modal_price": base_price + i,
         "arrival_qty": 100}
        for i in range(n)
    ]


def test_momentum_14d_formula_is_fractional_change():
    """momentum_14d = (price[t-1] - price[t-15]) / price[t-15] (no same-day)."""
    from datetime import timedelta
    from forecasting.features import build_feature_matrix

    base = date(2026, 9, 1)
    series = _make_series(30, base, base_price=1000.0)
    rows = build_feature_matrix(series)

    # For the 16th row (index 15, date = base + 15), we have:
    #   lag_1  = price at (base+14) = 1014
    #   lag_15 = price at (base+0)  = 1000
    # momentum = (1014 - 1000) / 1000 = 0.014
    row_16 = rows[15]  # 0-indexed: date = base + 15
    assert row_16.momentum_14d is not None
    assert abs(row_16.momentum_14d - 0.014) < 1e-9


def test_momentum_14d_is_none_when_lag15_missing():
    """If price[t-15] observation is absent, momentum_14d must be None."""
    from forecasting.features import build_feature_matrix

    base = date(2026, 9, 1)
    # Only 14 days of data — no t-15 is ever available
    series = _make_series(14, base)
    rows = build_feature_matrix(series)
    assert all(r.momentum_14d is None for r in rows)


def test_momentum_14d_is_none_when_denominator_zero():
    """If price[t-15] is zero, momentum_14d must be None (no division by zero)."""
    from datetime import timedelta
    from forecasting.features import build_feature_matrix

    base = date(2026, 9, 1)
    series = [
        {"arrival_date": (base + timedelta(days=i)).isoformat(),
         "modal_price": 0.0 if i == 0 else float(100 + i),
         "arrival_qty": 100}
        for i in range(20)
    ]
    rows = build_feature_matrix(series)
    # Row 16 (index 15): lag_15 = price at day 0 = 0.0 → None
    assert rows[15].momentum_14d is None


def test_district_price_uses_previous_day():
    """district_mean_price must use the previous calendar day to avoid leakage."""
    from datetime import timedelta
    from forecasting.features import build_feature_matrix

    base = date(2026, 9, 5)
    series = _make_series(5, base)
    # District prices indexed at the SAME day as series — they should NOT appear
    # at that row; instead they should appear on the NEXT row as the prev-day value.
    district = [
        {"arrival_date": (base + timedelta(days=i)).isoformat(),
         "mean_price": float(2000 + i)}
        for i in range(5)
    ]
    rows = build_feature_matrix(series, district_prices=district)

    # Row 0 (date = base+0): prev_day = base-1, not in district → None
    assert rows[0].district_mean_price is None
    # Row 1 (date = base+1): prev_day = base+0, district has 2000 → 2000.0
    assert rows[1].district_mean_price == 2000.0
    # Row 2 (date = base+2): prev_day = base+1, district has 2001 → 2001.0
    assert rows[2].district_mean_price == 2001.0


def test_event_pressure_uses_strictly_lagged_events():
    """Events on curr_date must NOT influence that row's event_pressure."""
    from datetime import timedelta
    from forecasting.features import build_feature_matrix

    base = date(2026, 9, 5)
    series = _make_series(3, base)
    # Event dated on base+1 — should NOT appear in row for base+1; only in base+2+
    events = [{
        "event_date": (base + timedelta(days=1)).isoformat(),
        "direction": "up", "magnitude": "major", "confidence": 1.0,
    }]
    rows = build_feature_matrix(series, events=events)
    # Row for base+1 (index 1): event is on same date → must NOT be included
    assert rows[1].event_pressure == 0.0
    # Row for base+2 (index 2): event is 1 day prior → included with age_days=1
    assert rows[2].event_pressure != 0.0
