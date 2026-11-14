#!/usr/bin/env python3
"""Leakage-safe price-history-only LightGBM benchmark for the Kaggle archive."""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path
import sys

import lightgbm as lgb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from interval_extension import HORIZON, load, ols_window, pairs, points_for


def rows_for_series(key, observations):
    dates = [day for day, _ in observations]
    prices = [value for _, value in observations]
    rows = []
    for origin, target in pairs(observations):
        if origin < 14:
            continue
        history = prices[: origin + 1]
        rows.append({
            "state": key[0], "district": key[1], "market": key[2], "commodity": key[3],
            "origin_date": dates[origin], "target_date": dates[target],
            "target": prices[target], "lag1": history[-1],
            "lag7": history[-7], "lag14": history[-14],
            "momentum14": history[-1] / history[-14] - 1.0 if history[-14] else 0.0,
            "dow": dates[origin].weekday(),
            "time_index": origin,
        })
    return rows


def add_codes(frame, mappings=None):
    mappings = mappings or {}
    for column in ("state", "district", "market", "commodity"):
        if column not in mappings:
            values = sorted(frame[column].unique())
            mappings[column] = {value: index for index, value in enumerate(values)}
        frame[column + "_id"] = frame[column].map(mappings[column]).astype("int32")
    return mappings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out", default="gbm_kaggle_results.json")
    parser.add_argument("--random", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    series = load(args.csv)
    eligible = [(key, values) for key, values in series.items() if len(values) >= 130]
    if not eligible:
        raise SystemExit("No eligible series found: requires at least 130 dated observations.")
    eligible = sorted(eligible, key=lambda item: item[0])
    import random
    cohort = random.Random(args.seed).sample(eligible, min(args.random, len(eligible)))
    rows = [row for key, values in cohort for row in rows_for_series(key, values)]
    frame = pd.DataFrame(rows)
    mappings = add_codes(frame)
    feature_columns = [
        "state_id", "district_id", "market_id", "commodity_id", "dow",
        "lag1", "lag7", "lag14", "momentum14", "time_index",
    ]
    predictions = []
    for origin_date, group in frame.groupby("origin_date", sort=True):
        train = frame[frame["target_date"] <= origin_date]
        if len(train) < 10:
            continue
        model = lgb.LGBMRegressor(
            objective="regression",
            learning_rate=0.05,
            n_estimators=50,
            num_leaves=15,
            min_child_samples=10,
            subsample=0.9,
            random_state=args.seed,
            verbosity=-1,
        )
        model.fit(train[feature_columns], train["target"])
        group = group.copy()
        group["prediction"] = model.predict(group[feature_columns])
        predictions.append(group)
    scored = pd.concat(predictions, ignore_index=True) if predictions else pd.DataFrame()
    if scored.empty:
        raise SystemExit("No scored origins produced.")

    by_series = []
    for key, group in scored.groupby(["state", "district", "market", "commodity"]):
        errors = (group["target"] - group["prediction"]).abs()
        naive = (group["target"] - group["lag1"]).abs()
        by_series.append({
            "series": list(key), "origins": len(group),
            "mape_pct": float((errors / group["target"]).mean() * 100),
            "mae": float(errors.mean()),
            "naive_mae": float(naive.mean()),
        })
    median_mae = statistics.median(row["mae"] for row in by_series)
    median_naive = statistics.median(row["naive_mae"] for row in by_series)
    result = {
        "script": "gbm_kaggle_eval.py", "seed": args.seed, "horizon_days": HORIZON,
        "cohort_series": len(cohort), "scored_origins": len(scored),
        "mape_pct_median": statistics.median(row["mape_pct"] for row in by_series),
        "mae_median": median_mae,
        "skill_vs_naive": 1 - median_mae / median_naive,
        "series_results": by_series,
        "features": feature_columns,
        "training_rule": "for each origin date, train only rows with target_date <= origin_date",
        "model": {"lightgbm": lgb.__version__, "learning_rate": 0.05, "n_estimators": 50,
                  "num_leaves": 15, "min_child_samples": 10, "subsample": 0.9},
    }
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(f"GBM_RESULT series={len(cohort)} origins={len(scored)} "
          f"mape_median={result['mape_pct_median']:.3f} "
          f"mae_median={median_mae:.3f} skill={result['skill_vs_naive']:.4f} output={args.out}")


if __name__ == "__main__":
    main()
