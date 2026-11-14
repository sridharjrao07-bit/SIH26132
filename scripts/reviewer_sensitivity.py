#!/usr/bin/env python3
"""Reviewer-requested horizon and deployable-interval sensitivity analysis."""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import interval_extension as harness


def q(values, level=0.95):
    values = sorted(v for v in values if math.isfinite(v))
    if not values:
        return float("nan")
    rank = math.ceil((len(values) + 1) * level)
    return values[min(len(values) - 1, rank - 1)]


def metric(actual, prediction, half, scale):
    covered = abs(actual - prediction) <= half
    width = 2 * half / scale
    winkler = harness.winkler(actual, prediction, half) / scale
    return covered, width, winkler


def series_record(observations):
    points = harness.points_for(observations, 0.4)
    prices = [value for _, value in observations]
    scale = statistics.median(prices)
    rows = {name: [] for name in ("parametric", "parametric_calibrated", "conformal", "naive_conformal")}
    relative_errors = {"blend": [], "naive": []}
    for i in range(20, len(points)):
        point = points[i]
        eligible = [j for j in range(i) if points[j]["target_date"] <= point["origin_date"]][-harness.CALIBRATION:]
        if len(eligible) < 20:
            continue
        blend_residuals = [abs(points[j]["actual"] - points[j]["prediction"]) for j in eligible]
        scaled_residuals = [blend_residuals[n] / points[j]["margin"]
                            for n, j in enumerate(eligible) if points[j]["margin"] > 0]
        naive_residuals = [abs(points[j]["actual"] - prices[jj := points[j]["origin"]])
                           for j in eligible]
        naive_prediction = prices[point["origin"]]
        calibrated_half = q(scaled_residuals) * point["margin"]
        conformal_half = q(blend_residuals)
        naive_half = q(naive_residuals)
        arms = {
            "parametric": (point["prediction"], point["margin"]),
            "parametric_calibrated": (point["prediction"], calibrated_half),
            "conformal": (point["prediction"], conformal_half),
            "naive_conformal": (naive_prediction, naive_half),
        }
        for name, (prediction, half) in arms.items():
            if math.isfinite(half):
                rows[name].append(metric(point["actual"], prediction, half, scale))
        relative_errors["blend"].append(abs(point["actual"] - point["prediction"]) / point["actual"])
        relative_errors["naive"].append(abs(point["actual"] - naive_prediction) / point["actual"])
    if not rows["parametric"]:
        return None
    result = {"n": len(rows["parametric"]), "arms": {}}
    for name, values in rows.items():
        result["arms"][name] = {
            "coverage": statistics.fmean(v[0] for v in values),
            "width": statistics.fmean(v[1] for v in values),
            "winkler_mean": statistics.fmean(v[2] for v in values),
            "winkler_median": statistics.median(v[2] for v in values),
        }
    result["relative_mae"] = {name: statistics.fmean(values) for name, values in relative_errors.items()}
    return result


def bootstrap(records, arm, field, n, seed):
    rng = random.Random(seed)
    values = [record["arms"][arm][field] for record in records]
    samples = [statistics.fmean(rng.choice(values) for _ in values) for _ in range(n)]
    return {
        "estimate": statistics.fmean(values),
        "lower": harness.percentile(samples, 0.025),
        "upper": harness.percentile(samples, 0.975),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--horizon-mode", choices=("step", "calendar"), default="calendar")
    parser.add_argument("--random", type=int, default=200)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    harness.HORIZON_MODE = args.horizon_mode
    series = harness.load(args.csv)
    eligible = [(key, values) for key, values in series.items() if len(values) >= 130]
    cohort = random.Random(args.seed).sample(eligible, min(args.random, len(eligible)))
    records = [record for _, observations in cohort if (record := series_record(observations))]
    arms = ("parametric", "parametric_calibrated", "conformal", "naive_conformal")
    output = {
        "script": "scripts/reviewer_sensitivity.py",
        "seed": args.seed,
        "horizon_mode": args.horizon_mode,
        "series": len(records),
        "origins": sum(r["n"] for r in records),
        "bootstrap": args.bootstrap,
        "arms": {},
        "relative_mae": {
            name: {"estimate": statistics.fmean(r["relative_mae"][name] for r in records),
                   "series": len(records)}
            for name in ("blend", "naive")
        },
    }
    for arm in arms:
        output["arms"][arm] = {
            field: bootstrap(records, arm, field, args.bootstrap, args.seed)
            for field in ("coverage", "width", "winkler_mean", "winkler_median")
        }
    Path(args.out).write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    for arm in arms:
        row = output["arms"][arm]
        print(f"{arm} coverage={row['coverage']['estimate']:.4f} "
              f"width={row['width']['estimate']:.4f} "
              f"winkler_mean={row['winkler_mean']['estimate']:.4f} "
              f"coverage_ci95=[{row['coverage']['lower']:.4f},{row['coverage']['upper']:.4f}]")
    print(f"relative_mae blend={output['relative_mae']['blend']['estimate']:.6f} "
          f"naive={output['relative_mae']['naive']['estimate']:.6f} output={args.out}")


if __name__ == "__main__":
    main()
