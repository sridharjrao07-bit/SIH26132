#!/usr/bin/env python3
"""Compare realised relative-error tails with a Gaussian reference.

The observed errors are the seven-day blend errors from interval_extension.py.
The reference draws iid standard-normal errors, so scale cancels in the
95th-percentile/median absolute-error ratio.  Each simulation preserves the
length of every qualifying series and uses seed 42.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from interval_extension import load, percentile, points_for


def ratio(values: list[float]) -> float:
    absolute = [abs(value) for value in values if math.isfinite(value)]
    if not absolute or percentile(absolute, 0.5) == 0:
        return float("nan")
    return percentile(absolute, 0.95) / percentile(absolute, 0.5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", required=True)
    parser.add_argument("--out", default="tail_gaussian_results.json")
    parser.add_argument("--min-observations", type=int, default=130)
    parser.add_argument("--min-origins", type=int, default=60)
    parser.add_argument("--random", type=int, default=200, help="seeded eligible-series cohort size")
    parser.add_argument("--simulations", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    series = load(args.csv)
    eligible = [(key, values) for key, values in series.items() if len(values) >= args.min_observations]
    cohort = random.Random(args.seed).sample(eligible, min(args.random, len(eligible)))
    observed = []
    standardized = []
    lengths = []
    for key, observations in cohort:
        points = points_for(observations, weight=0.4)
        errors = [
            (point["actual"] - point["prediction"]) / point["actual"]
            for point in points
            if point["actual"] > 0
        ]
        sigma_errors = [
            abs(point["actual"] - point["prediction"]) /
            (point["margin"] / (1.96 * math.sqrt(7)))
            for point in points
            if point["margin"] > 0
        ]
        if len(errors) >= args.min_origins:
            value = ratio(errors)
            if math.isfinite(value):
                observed.append({"series": list(key), "origins": len(errors), "ratio": value})
                standardized.append(ratio(sigma_errors))
                lengths.append(len(errors))

    if not observed:
        raise SystemExit("No qualifying series found for the tail benchmark.")

    rng = random.Random(args.seed)
    gaussian_medians = []
    for _ in range(args.simulations):
        ratios = [ratio([rng.gauss(0.0, 1.0) for _ in range(length)]) for length in lengths]
        gaussian_medians.append(statistics.median(ratios))

    result = {
        "script": "scripts/tail_gaussian_benchmark.py",
        "seed": args.seed,
        "simulations": args.simulations,
        "selection": {
            "min_observations": args.min_observations,
            "min_scored_origins": args.min_origins,
            "cohort": f"seed-{args.seed} random-{args.random}",
        },
        "observed": {
            "series": len(observed),
            "origins": sum(row["origins"] for row in observed),
            "median_ratio": statistics.median(row["ratio"] for row in observed),
            "per_series": observed,
            "median_standardized_ratio": statistics.median(standardized),
        },
        "gaussian_reference": {
            "median_of_simulation_medians": statistics.median(gaussian_medians),
            "simulation_medians": gaussian_medians,
            "simulation_p05": percentile(gaussian_medians, 0.05),
            "simulation_p95": percentile(gaussian_medians, 0.95),
        },
    }
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(
        f"TAIL_RESULT series={result['observed']['series']} "
        f"origins={result['observed']['origins']} "
        f"observed_ratio={result['observed']['median_ratio']:.4f} "
        f"standardized_ratio={result['observed']['median_standardized_ratio']:.4f} "
        f"gaussian_ratio={result['gaussian_reference']['median_of_simulation_medians']:.4f} "
        f"simulations={args.simulations} output={args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
