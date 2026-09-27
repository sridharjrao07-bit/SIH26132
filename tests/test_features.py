import math
from datetime import date

from forecasting.features import _compute_event_pressure


# ── Helper: mark an event dict as provenance_mode=live ────────────────────────
# All existing test events are "live" by intent. New tests explicitly set
# fixture/unknown/None to exercise the provenance gate.
def _live(d: dict) -> dict:
    return dict(d, provenance_mode="live")


def test_event_pressure_hand_computed():
    # 2 events (up/moderate/0.8/age 1d; down/major/0.6/age 4d) → exact expected value
    target_date = date(2026, 9, 15)  # 1 day after the event date of 2026-09-14
    events = [
        _live(
            {
                "event_date": "2026-09-14",
                "direction": "up",
                "magnitude": "moderate",
                "confidence": 0.8,
            }
        ),
        _live(
            {
                "event_date": "2026-09-11",
                "direction": "down",
                "magnitude": "major",
                "confidence": 0.6,
            }
        ),
    ]

    # Event 1: sign(up)=+1, weight(moderate)=1.0, conf=0.8, age=1 -> 1.0 * 1.0 * 0.8 * exp(-0.3)
    # Event 2: sign(down)=-1, weight(major)=1.5, conf=0.6, age=4 -> -1.0 * 1.5 * 0.6 * exp(-1.2) = -0.9 * exp(-1.2)
    # Total: 0.8 * exp(-0.3) - 0.9 * exp(-1.2)

    expected = 0.8 * math.exp(-0.3) - 0.9 * math.exp(-1.2)
    pressure, _ = _compute_event_pressure(target_date, events)
    assert abs(pressure - expected) < 1e-9


def test_event_pressure_older_than_14d_excluded():
    target_date = date(2026, 9, 15)
    events = [
        _live(
            {
                "event_date": "2026-08-30",  # age 16 > 14
                "direction": "up",
                "magnitude": "major",
                "confidence": 1.0,
            }
        )
    ]
    pressure, _ = _compute_event_pressure(target_date, events)
    assert pressure == 0.0


def test_event_pressure_commodity_mismatch_excluded():
    target_date = date(2026, 9, 15)
    events = [
        _live(
            {
                "event_date": "2026-09-14",
                "direction": "up",
                "magnitude": "moderate",
                "confidence": 0.8,
                "commodity_id": "other-uuid",
            }
        ),
        _live(
            {
                "event_date": "2026-09-14",
                "direction": "down",
                "magnitude": "major",
                "confidence": 1.0,
                "commodity_id": None,
            }
        ),
    ]
    # First is excluded due to mismatch, second is included because it's None.
    # Second: sign(-1) * weight(1.5) * conf(1.0) * exp(-0.3) = -1.5 * exp(-0.3)
    pressure, _ = _compute_event_pressure(target_date, events, "target-uuid")
    assert abs(pressure - (-1.5 * math.exp(-0.3))) < 1e-9


def test_event_pressure_clamped():
    target_date = date(2026, 9, 15)
    events = [
        _live(
            {"event_date": "2026-09-14", "direction": "up", "magnitude": "major", "confidence": 1.0}
        ),
        _live(
            {"event_date": "2026-09-14", "direction": "up", "magnitude": "major", "confidence": 1.0}
        ),
        _live(
            {"event_date": "2026-09-14", "direction": "up", "magnitude": "major", "confidence": 1.0}
        ),
    ]
    # Each gives 1.5 * exp(-0.3) ~ 1.11, three give ~ 3.33 -> clamped to +2.0
    pressure, _ = _compute_event_pressure(target_date, events)
    assert pressure == 2.0

    events_down = [
        _live(
            {
                "event_date": "2026-09-14",
                "direction": "down",
                "magnitude": "major",
                "confidence": 1.0,
            }
        ),
        _live(
            {
                "event_date": "2026-09-14",
                "direction": "down",
                "magnitude": "major",
                "confidence": 1.0,
            }
        ),
        _live(
            {
                "event_date": "2026-09-14",
                "direction": "down",
                "magnitude": "major",
                "confidence": 1.0,
            }
        ),
    ]
    # Each gives -1.5 * exp(-0.3) ~ -1.11 -> total ~ -3.33 -> clamped to -2.0
    pressure, _ = _compute_event_pressure(target_date, events_down)
    assert pressure == -2.0


def test_event_pressure_publication_date_strict_pit():
    target_date = date(2026, 9, 14)
    events = [
        _live(
            {  # Excluded: publication date >= target_date
                "event_date": "2026-09-10",
                "publication_date": "2026-09-15",
                "direction": "up",
                "magnitude": "major",
                "confidence": 1.0,
            }
        ),
        _live(
            {  # Excluded: publication date is NULL and strict_pit=True
                "event_date": "2026-09-10",
                "direction": "up",
                "magnitude": "major",
                "confidence": 1.0,
            }
        ),
        _live(
            {  # Included: publication date < target_date
                "event_date": "2026-09-10",
                "publication_date": "2026-09-13",
                "direction": "up",
                "magnitude": "major",
                "confidence": 1.0,
            }
        ),
    ]

    # Only the third event is eligible
    # sign(up)=1.0 * weight(major)=1.5 * conf=1.0 * exp(-0.3 * 4)
    expected = 1.5 * math.exp(-0.3 * 4)

    pressure, approx = _compute_event_pressure(target_date, events, strict_pit=True)
    assert abs(pressure - expected) < 1e-9
    assert approx is False


# ── momentum_14d point-in-time tests ─────────────────────────────────────────


def _make_series(n: int, base_date: date, base_price: float = 1000.0):
    """Build a simple ascending price series with 1 obs per calendar day."""
    from datetime import timedelta

    return [
        {
            "arrival_date": (base_date + timedelta(days=i)).isoformat(),
            "modal_price": base_price + i,
            "arrival_qty": 100,
        }
        for i in range(n)
    ]


def test_momentum_14d_formula_is_fractional_change():
    """momentum_14d = (price[t-1] - price[t-15]) / price[t-15] (no same-day)."""
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
        {
            "arrival_date": (base + timedelta(days=i)).isoformat(),
            "modal_price": 0.0 if i == 0 else float(100 + i),
            "arrival_qty": 100,
        }
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
        {"arrival_date": (base + timedelta(days=i)).isoformat(), "mean_price": float(2000 + i)}
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
    events = [
        _live(
            {
                "event_date": (base + timedelta(days=1)).isoformat(),
                "direction": "up",
                "magnitude": "major",
                "confidence": 1.0,
            }
        )
    ]
    rows = build_feature_matrix(series, events=events)
    # Row for base+1 (index 1): event is on same date → must NOT be included
    assert rows[1].event_pressure == 0.0
    # Row for base+2 (index 2): event is 1 day prior → included with age_days=1
    assert rows[2].event_pressure != 0.0


# ── Provenance gate tests ─────────────────────────────────────────────────────


def _base_event(event_date="2026-09-14", direction="up", magnitude="major", confidence=1.0):
    return {
        "event_date": event_date,
        "direction": direction,
        "magnitude": magnitude,
        "confidence": confidence,
    }


def test_fixture_provenance_excluded():
    """Events with provenance_mode='fixture' must produce event_pressure=0.0."""
    target_date = date(2026, 9, 15)
    events = [dict(_base_event(), provenance_mode="fixture")]
    pressure, approx = _compute_event_pressure(target_date, events)
    assert pressure == 0.0
    assert approx is False, (
        "Exclusion by provenance is a deliberate zero (not approximate contamination)"
    )


def test_unknown_provenance_excluded():
    """Events with provenance_mode='unknown' must produce event_pressure=0.0."""
    target_date = date(2026, 9, 15)
    events = [dict(_base_event(), provenance_mode="unknown")]
    pressure, approx = _compute_event_pressure(target_date, events)
    assert pressure == 0.0


def test_absent_provenance_treated_as_unknown():
    """Events with no provenance_mode key (legacy seed data) must be excluded."""
    target_date = date(2026, 9, 15)
    events = [_base_event()]  # no provenance_mode key at all
    pressure, _ = _compute_event_pressure(target_date, events)
    assert pressure == 0.0


def test_none_provenance_treated_as_unknown():
    """Events with provenance_mode=None must be excluded (treated as 'unknown')."""
    target_date = date(2026, 9, 15)
    events = [dict(_base_event(), provenance_mode=None)]
    pressure, _ = _compute_event_pressure(target_date, events)
    assert pressure == 0.0


def test_live_provenance_included():
    """Events with provenance_mode='live' must be included in the score."""
    target_date = date(2026, 9, 15)
    events = [_live(_base_event())]
    pressure, _ = _compute_event_pressure(target_date, events)
    assert pressure != 0.0, "Live events must contribute to event_pressure"


def test_mixed_provenance_only_live_included():
    """
    A mix of live and fixture events: only the live event may contribute.
    The fixture event has a higher confidence and a larger magnitude, but
    must not affect the score.
    """
    target_date = date(2026, 9, 15)
    live_event = _live(_base_event(magnitude="minor", confidence=0.6))
    fixture_event = dict(_base_event(magnitude="major", confidence=1.0), provenance_mode="fixture")
    unknown_event = dict(_base_event(magnitude="major", confidence=1.0), provenance_mode="unknown")

    events = [live_event, fixture_event, unknown_event]
    pressure_mixed, _ = _compute_event_pressure(target_date, events)

    # Compute expected from live only
    pressure_live_only, _ = _compute_event_pressure(target_date, [live_event])

    assert abs(pressure_mixed - pressure_live_only) < 1e-9, (
        "Fixture/unknown events must not contribute to event_pressure even when live events are present"
    )
