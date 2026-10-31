#!/usr/bin/env python3
"""Reproduce the paper's snapshot, provenance-gate, and calibration results.

R1/R2 require a supplied real snapshot; R3 uses the repository generator:
  python scripts/paper_results.py --real /tmp/real_snapshot.csv
  python scripts/paper_results.py --skip-r1 --skip-r2
"""

from __future__ import annotations

import argparse
import collections
import csv
import math
import os
import random
import statistics
import sys

sys.path.insert(0, os.getcwd())

MA_WINDOW, OLS_WINDOW, HORIZON = 7, 30, 7
N_FOLDS, FOLD_SIZE, TRAIN_DEPTH, CALIB_DEPTH, ALPHA = 8, 7, 130, 60, 0.05


def f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rows(path):
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def quantile(values, q):
    values = sorted(values)
    if not values:
        return 0.0
    pos = q * (len(values) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def r1(path):
    data = rows(path)
    issues = collections.Counter()
    for row in data:
        mn, mx, modal = (f(row[k]) for k in (
            "Min_x0020_Price", "Max_x0020_Price", "Modal_x0020_Price"))
        if None in (mn, mx, modal):
            issues["unparseable"] += 1
            continue
        if mn > mx:
            issues["min_gt_max"] += 1
        if not mn <= modal <= mx:
            issues["modal_outside_range"] += 1
        if mn == mx == modal:
            issues["zero_spread"] += 1
        if modal < 100:
            issues["implausible_below_100"] += 1
    onion = [row for row in data if row["Commodity"] == "Onion"]
    prices = sorted(v for v in (f(r["Modal_x0020_Price"]) for r in onion) if v and v >= 100)
    median = statistics.median(prices)
    mad = statistics.median(abs(v - median) for v in prices)
    states = collections.defaultdict(list)
    for row in onion:
        value = f(row["Modal_x0020_Price"])
        if value and value >= 100:
            states[row["State"]].append(value)
    state_medians = sorted((state, statistics.median(values), len(values))
                           for state, values in states.items() if len(values) >= 5)
    if state_medians:
        lowest = min(state_medians, key=lambda item: item[1])
        highest = max(state_medians, key=lambda item: item[1])
        state_spread = highest[1] / lowest[1]
        state_spread_pair = (lowest[0], lowest[1], highest[0], highest[1])
    else:
        state_spread, state_spread_pair = None, None
    return {
        "rows": len(data), "markets": len({r["Market"] for r in data}),
        "commodities": len({r["Commodity"] for r in data}),
        "states": len({r["State"] for r in data}),
        "dates": sorted({r["Arrival_Date"] for r in data}), "issues": dict(issues),
        "zero_spread_pct": 100 * issues["zero_spread"] / len(data),
        "implausible_pct": 100 * issues["implausible_below_100"] / len(data),
        "onion": {"n": len(prices), "markets": len({r["Market"] for r in onion}),
                  "states": len({r["State"] for r in onion}), "median": median,
                  "mad": mad, "robust_cv": 1.4826 * mad / median,
                  "p10": quantile(prices, .1), "p90": quantile(prices, .9),
                  "p90_over_p10": quantile(prices, .9) / quantile(prices, .1),
                  "trimmed_min": prices[0], "trimmed_max": prices[-1],
                  "trimmed_ratio": prices[-1] / prices[0]},
        "state_medians": state_medians,
        "state_spread": state_spread, "state_spread_pair": state_spread_pair,
    }


def features(data):
    usable = []
    for row in data:
        modal = f(row.get("Modal_x0020_Price"))
        minimum = f(row.get("Min_x0020_Price"))
        maximum = f(row.get("Max_x0020_Price"))
        if modal is not None and modal > 0:
            usable.append((modal, minimum, maximum))
    if not usable:
        return 0.0, 1.0
    whole = sum(modal == round(modal) for modal, _, _ in usable) / len(usable)
    coverage = len(usable) / len(data) if data else 0.0
    if coverage < 0.90:
        return whole, 1.0
    band = sum(
        minimum is not None and maximum is not None
        and .88 <= minimum / modal <= .94
        and 1.06 <= maximum / modal <= 1.13
        for modal, minimum, maximum in usable
    ) / len(usable)
    return whole, band


def r2(real_path, synth_path):
    real, synth = rows(real_path), rows(synth_path)
    result = {}
    for name, data in (("real", real), ("synthetic", synth)):
        whole, band = features(data)
        result[name] = whole, band, whole >= .85 and band < .95
    random.seed(1)
    sweep = []
    for pct in (0, 2, 5, 8, 10, 12, 14, 15, 20, 30, 50, 75, 100):
        count = int(4000 * pct / 100)
        mixed = random.choices(real, k=4000 - count) + random.choices(synth, k=count)
        whole, band = features(mixed)
        sweep.append((pct, whole, band, whole >= .85 and band < .95))
    return result, sweep


def r3(days=400, seed=42):
    from scripts.generate_historical_prices import generate_dataset
    data = generate_dataset(days=days, seed=seed)
    series = [float(r["Modal_x0020_Price"]) for r in sorted(data, key=lambda x: x["Arrival_Date_ISO"])
              if r["Market"] == "Lasalgaon APMC" and r["Commodity"] == "Onion"]
    origins = [len(series) - (N_FOLDS - k) * FOLD_SIZE for k in range(N_FOLDS)]

    def forecast(values, weight):
        ma = values[-MA_WINDOW:]
        level, sigma_ma = sum(ma) / len(ma), statistics.pstdev(ma) if len(ma) > 1 else 0
        lr = values[-OLS_WINDOW:]
        m, sx, sy = len(lr), sum(range(len(lr))), sum(lr)
        den = m * sum(x * x for x in range(m)) - sx * sx
        slope = (m * sum(x * y for x, y in enumerate(lr)) - sx * sy) / den if den else 0
        intercept = (sy - slope * sx) / m
        residuals = [y - (intercept + slope * x) for x, y in enumerate(lr)]
        sigma_lr = statistics.pstdev(residuals) if len(residuals) > 1 else 0
        return [weight * level + (1 - weight) * (intercept + slope * (m + h))
                for h in range(HORIZON)], max(sigma_ma, sigma_lr)

    def evaluate(weight):
        points = []
        for origin in origins:
            if origin < TRAIN_DEPTH or origin >= len(series):
                continue
            preds, sigma = forecast(series[:origin], weight)
            for h, pred in enumerate(preds, 1):
                if origin + h - 1 >= len(series):
                    continue
                pool = []
                for x in range(max(OLS_WINDOW, origin - CALIB_DEPTH), origin):
                    if x + h - 1 < len(series):
                        px, _ = forecast(series[:x], weight)
                        pool.append(abs(series[x + h - 1] - px[h - 1]))
                points.append((series[origin + h - 1], pred, 1.96 * sigma * math.sqrt(h),
                              quantile(pool, 1 - ALPHA)))
        return points

    def summary(points):
        return (statistics.mean(abs(a - p) / a for a, p, _, _ in points) * 100,
                sum(abs(a - p) <= q for a, p, _, q in points) / len(points),
                statistics.mean(2 * q for _, _, _, q in points))

    ablation = [(weight, summary(evaluate(weight))) for weight in [i / 10 for i in range(11)]]
    naive_zero_width_points = sum(
        1 for origin in origins if origin >= TRAIN_DEPTH
        for h in range(1, HORIZON + 1) if origin + h - 1 < len(series)
    )
    mape_spread = max(result[1][0] for result in ablation) - min(result[1][0] for result in ablation)
    return {
        "series": len(series), "production": summary(evaluate(.4)),
        "naive_zero_width_points": naive_zero_width_points,
        "ablation": ablation, "mape_spread": mape_spread,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", default="/tmp/real_snapshot.csv")
    parser.add_argument("--synth", default="data/gov_prices.csv")
    parser.add_argument("--skip-r1", action="store_true")
    parser.add_argument("--skip-r2", action="store_true")
    parser.add_argument("--skip-r3", action="store_true")
    args = parser.parse_args()
    if (not args.skip_r1 or not args.skip_r2) and not os.path.exists(args.real):
        print(f"error: real snapshot not found: {args.real}", file=sys.stderr)
        return 2
    if not args.skip_r1:
        result = r1(args.real)
        print("R1", result)
        print("state_spread      :", result["state_spread"], result["state_spread_pair"])
        print("trimmed_ratio     :", result["onion"]["trimmed_ratio"])
    if not args.skip_r2:
        result, sweep = r2(args.real, args.synth)
        print("R2", result)
        print("R2 contamination_sweep", sweep)
    if not args.skip_r3:
        result = r3()
        print("R3", result)
        print("R3 naive_zero_width_points=", result["naive_zero_width_points"])
        print("R3 mape_spread_across_weights=", result["mape_spread"], "pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
