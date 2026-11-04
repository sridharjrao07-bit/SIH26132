#!/usr/bin/env python3
"""Run the paper's interval experiment on real Agmarknet series."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import random
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.getcwd())
from forecasting.engine import (  # noqa: E402
    CONFIDENCE_Z,
    HORIZON_DAYS,
    MA_WINDOW,
    OLS_FIT_WINDOW,
    LinearRegressionModel,
    MovingAverageModel,
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


def conformal(points, alpha=0.05, calibration=60, minimum=20, eval_from=0):
    """Rolling split-conformal intervals over the same paired points."""
    errors = [abs(actual - prediction) for actual, prediction, _ in points]
    result = []
    start = max(calibration, minimum, eval_from)
    for index in range(start, len(points)):
        window = errors[max(0, index - calibration):index]
        ranked = sorted(window)
        q = ranked[min(len(ranked) - 1, int(round((1 - alpha) * len(ranked))) - 1)]
        actual, prediction, _ = points[index]
        result.append((actual, prediction, q))
    return result


def summarize_series(observations, weight):
    points = evaluate(observations, weight)
    conf = conformal(points)
    if not points or not conf:
        return None
    # Compare both interval methods on exactly the conformal arm's origins.
    paired = points[len(points) - len(conf):]
    prices = [value for _, value in observations]
    scale = statistics.median(prices)
    mape = statistics.fmean(abs(actual - prediction) / actual * 100
                            for actual, prediction, _ in paired)
    param_cov = statistics.fmean(abs(actual - prediction) <= margin
                                 for actual, prediction, margin in paired)
    param_width = statistics.fmean(2 * margin for _, _, margin in paired) / scale
    conf_cov = statistics.fmean(abs(actual - prediction) <= q
                                for actual, prediction, q in conf)
    conf_width = statistics.fmean(2 * q for _, _, q in conf) / scale
    return mape, param_cov, param_width, conf_cov, conf_width, len(paired)


def percentile(values, q):
    return sorted(values)[int(q * (len(values) - 1))]


def coverage_sweep(cohort, weight=0.4, windows=(40, 60, 120, 180, 240, 300)):
    """Summarize per-series conformal coverage across calibration windows."""
    evaluated = [evaluate(observations, weight) for _, observations in cohort]
    eval_from = max(windows)
    output = []
    for calibration in windows:
        coverages = []
        for points in evaluated:
            scored = conformal(points, calibration=calibration, eval_from=eval_from)
            if scored:
                coverages.append(statistics.fmean(
                    abs(actual - prediction) <= q
                    for actual, prediction, q in scored
                ))
        if coverages:
            output.append((
                calibration,
                len(coverages),
                statistics.fmean(coverages),
                statistics.median(coverages),
                percentile(coverages, 0.10),
                percentile(coverages, 0.90),
                sum(value < 0.90 for value in coverages) / len(coverages),
            ))
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--commodity")
    parser.add_argument("--min-dates", type=int, default=130)
    parser.add_argument("--top", type=int, default=20, help="deepest-series cohort size")
    parser.add_argument("--random", type=int, default=200, dest="random_count")
    args = parser.parse_args()
    series = load(args.csv_path)
    if args.commodity:
        series = {key: values for key, values in series.items()
                  if str(key[3]).lower() == args.commodity.lower()}
    eligible = [(key, values) for key, values in series.items() if len(values) >= args.min_dates]
    deepest = sorted(eligible, key=lambda item: -len(item[1]))[:args.top]
    rng = random.Random(42)
    random_cohort = rng.sample(eligible, min(args.random_count, len(eligible)))
    print(f"series with >= {args.min_dates} dates: {len(eligible)}")
    if not eligible:
        print("nothing to evaluate")
        return 1

    for cohort_name, cohort in ((f"deepest-{len(deepest)}", deepest),
                                (f"random-{len(random_cohort)}", random_cohort)):
        pooled = defaultdict(list)
        for key, observations in cohort:
            for weight in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
                result = summarize_series(observations, weight)
                if result:
                    pooled[weight].append(result)
            print(f"{key[0]} / {key[2]} / {key[3]} ({len(observations)} dates)")
        print(f"=== {cohort_name} ===")
        for weight in (0.0, 0.2, 0.4, 0.6, 0.8, 1.0):
            values = pooled[weight]
            if not values:
                continue
            mapes = [v[0] for v in values]
            print(f"w={weight:.1f} series={len(values)} n={sum(v[5] for v in values)} "
                  f"MAPE_median={statistics.median(mapes):.4f}% "
                  f"MAPE_IQR={percentile(mapes,.75)-percentile(mapes,.25):.4f} "
                  f"param_cov={statistics.fmean(v[1] for v in values):.4f} "
                  f"param_rel_width={statistics.fmean(v[2] for v in values):.4f} "
                  f"conf_cov={statistics.fmean(v[3] for v in values):.4f} "
                  f"conf_rel_width={statistics.fmean(v[4] for v in values):.4f}")
        print("calibration sweep (w=0.4):")
        for calibration, count, mean, median, p10, p90, below in coverage_sweep(cohort):
            print(f"  calibration={calibration:>3} series={count} mean={mean:.4f} "
                  f"median={median:.4f} p10={p10:.4f} p90={p90:.4f} "
                  f"share_below_90={below:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
