#!/usr/bin/env python3
"""Run the paper's interval experiment on real Agmarknet series."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.getcwd())
from forecasting.engine import (  # noqa: E402
    CONFIDENCE_Z, HORIZON_DAYS, MA_WINDOW, OLS_FIT_WINDOW,
    LinearRegressionModel, MovingAverageModel,
)

DATE_KEYS = ("Arrival_Date", "arrival_date", "price_date", "Price Date", "report_date")
MOD_KEYS = ("Modal_x0020_Price", "modal_price", "Modal_Price", "Modal Price (Rs./Quintal)", "as_on_price")
DATE_FORMATS = ("%d/%m/%Y", "%d-%b-%Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%y %H:%M")


def pick(row, keys):
    return next((row[k] for k in keys if k in row and row[k] not in (None, "")), None)


def parse_date(value):
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(value.strip(), fmt).date()
        except (AttributeError, ValueError):
            pass
    return None


def load(path):
    series = defaultdict(dict)
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            day = parse_date(pick(row, DATE_KEYS) or "")
            raw_modal = pick(row, MOD_KEYS)
            try:
                modal = float(str(raw_modal).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if day is None or modal <= 0:
                continue
            key = (row.get("State") or row.get("state"),
                   row.get("District") or row.get("district") or row.get("district_name") or row.get("District Name"),
                   row.get("Market") or row.get("market_name") or row.get("Market Name"),
                   row.get("Commodity") or row.get("commodity"))
            series[key][day] = modal
    return {key: sorted(values.items()) for key, values in series.items()}


def pairs(observations, tolerance=2):
    dates = [day for day, _ in observations]
    result = []
    for origin, day in enumerate(dates):
        wanted = day + dt.timedelta(days=HORIZON_DAYS)
        best = None
        best_gap = None
        for target in range(origin + 1, len(dates)):
            gap = abs((dates[target] - wanted).days)
            if gap <= tolerance and (best_gap is None or gap < best_gap):
                best, best_gap = target, gap
            if (dates[target] - wanted).days > tolerance:
                break
        if best is not None:
            result.append((origin, best))
    return result


def evaluate(observations, weight):
    prices = [value for _, value in observations]
    results = []
    for origin, target in pairs(observations):
        history = prices[:origin + 1]
        if len(history) < max(MA_WINDOW, OLS_FIT_WINDOW):
            continue
        actual = prices[target]
        ma, lr = MovingAverageModel(history), LinearRegressionModel(history)
        prediction = weight * ma.level + (1 - weight) * (lr.intercept + lr.slope * (lr._n + HORIZON_DAYS - 1))
        sigma = max(ma.sigma, lr.sigma)
        margin = CONFIDENCE_Z * sigma * (HORIZON_DAYS ** 0.5)
        results.append((actual, prediction, margin))
    return results


def conformal(points, alpha=0.05, calibration=60, minimum=20):
    """Rolling split-conformal intervals over the same paired points."""
    errors = [abs(actual - prediction) for actual, prediction, _ in points]
    result = []
    for index, (actual, prediction, _) in enumerate(points):
        window = errors[max(0, index - calibration):index]
        if len(window) < minimum:
            continue
        ranked = sorted(window)
        q = ranked[min(len(ranked) - 1, int(round((1 - alpha) * len(ranked))) - 1)]
        result.append((actual, prediction, q))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--commodity")
    parser.add_argument("--min-dates", type=int, default=130)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    series = load(args.csv_path)
    if args.commodity:
        series = {key: values for key, values in series.items()
                  if str(key[3]).lower() == args.commodity.lower()}
    deep = sorted(((key, values) for key, values in series.items()
                   if len(values) >= args.min_dates), key=lambda item: -len(item[1]))[:args.top]
    print(f"series with >= {args.min_dates} dates: {len(deep)}")
    if not deep:
        print("nothing to evaluate")
        return 1
    pooled = defaultdict(list)
    for key, observations in deep:
        for weight in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            points = evaluate(observations, weight)
            if not points:
                continue
            actual = [a for a, _, _ in points]
            mape = statistics.fmean(abs(a - p) / a * 100 for a, p, _ in points)
            coverage = statistics.fmean(abs(a - p) <= margin for a, p, margin in points)
            width = statistics.fmean(2 * margin for _, _, margin in points)
            conf = conformal(points)
            conf_coverage = statistics.fmean(abs(a - p) <= q for a, p, q in conf) if conf else None
            conf_width = statistics.fmean(2 * q for _, _, q in conf) if conf else None
            pooled[weight].append((mape, coverage, width, len(points), conf_coverage, conf_width))
        print(f"{key[0]} / {key[2]} / {key[3]} ({len(observations)} dates)")
    print("=== pooled over series ===")
    for weight in sorted(pooled):
        values = pooled[weight]
        conformal_values = [v for v in values if v[4] is not None]
        conformal_text = (f"conf_cov={statistics.fmean(v[4] for v in conformal_values):.4f} "
                          f"conf_width={statistics.fmean(v[5] for v in conformal_values):.2f}"
                          if conformal_values else "conf=insufficient-calibration")
        print(f"w={weight:.1f} series={len(values)} MAPE={statistics.fmean(v[0] for v in values):.4f}% "
              f"param_cov={statistics.fmean(v[1] for v in values):.4f} width={statistics.fmean(v[2] for v in values):.2f} "
              f"{conformal_text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
