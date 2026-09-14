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
