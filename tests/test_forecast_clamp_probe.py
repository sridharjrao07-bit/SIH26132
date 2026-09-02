from datetime import date, timedelta
from forecasting.engine import _make_forecast_rows

def test_clamped_center_keeps_bounds_sane():
    series = [(date(2025, 1, 1) + timedelta(days=i), 5000 - 800 * i) for i in range(20)]
    rows = _make_forecast_rows("m1", "c1", series, sanity=(100.0, 8000.0))
    for r in rows:
        p, lo, hi = r["predicted_price"], r["lower_bound"], r["upper_bound"]
        assert p >= 100.0
        assert lo <= p <= hi, f"bounds inverted: lo={lo} p={p} hi={hi}"
        assert hi >= 0.0
        assert lo >= 100.0
        assert hi <= 8000.0
