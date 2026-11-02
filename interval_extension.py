#!/usr/bin/env python3
"""Extended, reproducible interval evaluation for the Agmarknet panel.

The script deliberately keeps the paper harness' mixed aggregation rules:
coverage is the mean of per-series coverage, relative width is the mean of
per-series relative width, and Winkler is the median of per-series scores.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import math
import os
import random
import statistics
import subprocess
from collections import defaultdict

HORIZON = 7
MA_WINDOW = 7
OLS_WINDOW = 30
CALIBRATION = 60
ALPHA = 0.05
Z = 1.96
T28 = 2.048407
WINDOWS = (40, 60, 120, 180, 240, 300)

DATE_KEYS = ("Arrival_Date", "arrival_date", "price_date", "Price Date", "report_date")
MOD_KEYS = ("Modal_x0020_Price", "modal_price", "Modal_Price", "Modal Price (Rs./Quintal)", "as_on_price")
STATE_KEYS = ("State", "state", "STATE", "state_name", "State Name")
DIST_KEYS = ("District", "district", "DISTRICT", "district_name", "District Name")
MKT_KEYS = ("Market", "market", "MARKET", "market_name", "Market Name")
CMD_KEYS = ("Commodity", "commodity", "COMMODITY", "commodity_name", "Commodity Name")
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
            raw = pick(row, MOD_KEYS)
            try:
                modal = float(str(raw).replace(",", ""))
            except (TypeError, ValueError):
                continue
            if day is None or modal <= 0:
                continue
            key = tuple(pick(row, keys) for keys in (STATE_KEYS, DIST_KEYS, MKT_KEYS, CMD_KEYS))
            if any(v in (None, "") for v in key):
                continue
            series[key][day] = modal
    return {key: sorted(values.items()) for key, values in series.items()}


def pairs(observations, tolerance=2):
    dates = [day for day, _ in observations]
    result = []
    for origin, day in enumerate(dates):
        wanted = day + dt.timedelta(days=HORIZON)
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


def ols_window(values):
    window = values[-OLS_WINDOW:]
    n = len(window)
    xs = list(range(n))
    xbar = statistics.fmean(xs)
    ybar = statistics.fmean(window)
    sxx = sum((x - xbar) ** 2 for x in xs)
    slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, window)) / sxx if sxx else 0.0
    intercept = ybar - slope * xbar
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, window)]
    sse = sum(r * r for r in residuals)
    s = math.sqrt(sse / (n - 2)) if n > 2 else 0.0
    return slope, intercept, n, xbar, sxx, s, residuals


def points_for(observations, weight):
    prices = [value for _, value in observations]
    result = []
    for origin, target in pairs(observations):
        history = prices[:origin + 1]
        if len(history) < OLS_WINDOW:
            continue
        ma_values = history[-MA_WINDOW:]
        ma_level = statistics.fmean(ma_values)
        ma_sigma = statistics.pstdev(ma_values) if len(ma_values) > 1 else 0.0
        slope, intercept, n, xbar, sxx, s, residuals = ols_window(history)
        lr_prediction = intercept + slope * (n + HORIZON - 1)
        lr_sigma = math.sqrt(sum(r * r for r in residuals) / len(residuals)) if residuals else 0.0
        prediction = weight * ma_level + (1 - weight) * lr_prediction
        sigma = max(ma_sigma, lr_sigma)
        margin = Z * sigma * math.sqrt(HORIZON)
        x = n + HORIZON - 1
        leverage = math.sqrt(1 + 1 / n + ((x - xbar) ** 2 / sxx if sxx else 0.0))
        res_margin = T28 * s * leverage * math.sqrt(HORIZON)
        result.append({"origin": origin, "target": target,
                       "origin_date": observations[origin][0],
                       "target_date": observations[target][0],
                       "actual": prices[target],
                       "prediction": prediction, "margin": margin,
                       "res_margin": res_margin, "residual_sigma": s})
    return result


def conf_values(points, calibration=CALIBRATION, eval_from=0):
    out = []
    for i in range(max(20, eval_from), len(points)):
        eligible = [j for j in range(i)
                    if points[j]["target_date"] <= points[i]["origin_date"]]
        eligible = eligible[-calibration:]
        if len(eligible) < 20:
            continue
        window = [abs(points[j]["actual"] - points[j]["prediction"])
                  for j in eligible]
        ranked = sorted(window)
        q = ranked[min(len(ranked) - 1, int(round((1 - ALPHA) * len(ranked))) - 1)]
        out.append((i, q))
    return out


def winkler(actual, prediction, half_width, alpha=ALPHA):
    score = 2 * half_width
    if actual < prediction - half_width:
        score += (2 / alpha) * ((prediction - half_width) - actual)
    elif actual > prediction + half_width:
        score += (2 / alpha) * (actual - (prediction + half_width))
    return score


def percentile(values, q):
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(q * (len(ordered) - 1))))]


def arm_metrics(points, arms, median_price):
    output = {}
    for name, rows in arms.items():
        if not rows:
            print(f"WARNING arm={name} zero_scored_origins")
            continue
        cov = statistics.fmean(abs(r["actual"] - r["prediction"]) <= r["half"] for r in rows)
        width = statistics.fmean(2 * r["half"] / median_price for r in rows)
        wink = statistics.median(winkler(r["actual"], r["prediction"], r["half"]) / median_price for r in rows)
        output[name] = {"coverage": cov, "width": width, "winkler": wink, "n": len(rows)}
    return output


def build_series(observations, weight, eval_from=0):
    points = points_for(observations, weight)
    conf = dict(conf_values(points, eval_from=eval_from))
    scored = [p for i, p in enumerate(points) if i in conf]
    arms = {
        "param": [{**p, "half": p["margin"]} for p in scored],
        "resparam": [{**p, "half": p["res_margin"]} for p in scored],
        "resparam2": [{**p, "half": conf[i]} for i, p in enumerate(points) if i in conf],
        "conf": [{**p, "half": conf[i]} for i, p in enumerate(points) if i in conf],
    }
    # Scaled is conformal on residuals normalised by the parametric margin.
    scaled = []
    for i, p in enumerate(points):
        if i < max(CALIBRATION, 20, eval_from):
            continue
        prior = points[max(0, i - CALIBRATION):i]
        ratios = [abs(x["actual"] - x["prediction"]) / x["margin"] for x in prior if x["margin"] > 0]
        if not ratios:
            continue
        scaled.append({**p, "half": percentile(ratios, 1 - ALPHA) * p["margin"]})
    arms["scaled"] = scaled
    return points, arms


def fit_k(rows, target_coverage):
    """Return the smallest empirical multiplier reaching target coverage."""
    if not rows:
        return float("nan")
    ratios = [abs(r["actual"] - r["prediction"]) / r["half"]
              for r in rows if r["half"] > 0]
    if not ratios:
        return float("nan")
    return percentile(ratios, target_coverage)


def apply_match(rows, target_coverage, fixed_k=None):
    """Scale one arm to a target coverage using a fixed or fitted k."""
    k = fit_k(rows, target_coverage) if fixed_k is None else fixed_k
    if not math.isfinite(k):
        return [], float("nan")
    return [{**r, "half": r["half"] * k} for r in rows], k


def series_record(observations, weight=0.4, eval_from=0, series_key=None):
    points, arms = build_series(observations, weight, eval_from)
    if not points or not arms["conf"]:
        return None
    median_price = statistics.median(v for _, v in observations)
    metrics = arm_metrics(points, arms, median_price)
    conf_cov = metrics["conf"]["coverage"]
    param_match, k = apply_match(arms["param"], conf_cov)
    conf_match, k3 = apply_match(arms["conf"], metrics["param"]["coverage"])
    matched_metrics = arm_metrics(points, {"match": param_match}, median_price)
    widened_metrics = arm_metrics(points, {"conf_match": conf_match}, median_price)
    if "match" in matched_metrics:
        metrics["match"] = matched_metrics["match"]
    if "conf_match" in widened_metrics:
        metrics["conf_match"] = widened_metrics["conf_match"]
    # Fair comparison against the residual-parametric arm.
    res_cov = metrics["resparam"]["coverage"]
    res_match, kres = apply_match(arms["resparam"], conf_cov)
    conf_res_match, kres3 = apply_match(arms["conf"], res_cov)
    res_match_metrics = arm_metrics(points, {"res_match": res_match}, median_price)
    conf_res_metrics = arm_metrics(points, {"conf_res_match": conf_res_match}, median_price)
    if "res_match" in res_match_metrics:
        metrics["res_match"] = res_match_metrics["res_match"]
    if "conf_res_match" in conf_res_metrics:
        metrics["conf_res_match"] = conf_res_metrics["conf_res_match"]
    metrics["k"] = k
    metrics["k3"] = k3
    metrics["k_res"] = kres
    metrics["k_res3"] = kres3
    origins = {k: {r["origin"] for r in v} for k, v in arms.items()}
    origins["match"] = set(origins.get("param", set()))
    origins["conf_match"] = set(origins.get("conf", set()))
    origins["res_match"] = set(origins.get("resparam", set()))
    origins["conf_res_match"] = set(origins.get("conf", set()))
    return {"series_key": series_key, "metrics": metrics, "origins": origins,
            "scale_full": median_price,
            "scale_eval": statistics.median(p["actual"] for p in points),
            "scale_mean": statistics.fmean(v for _, v in observations),
            "points": points, "arms": arms}


def aggregate(records):
    result = {}
    for arm in ("param", "conf", "scaled", "resparam", "resparam2", "match", "conf_match", "res_match", "conf_res_match"):
        values = [r["metrics"][arm] for r in records if arm in r["metrics"]]
        if not values:
            continue
        result[arm] = {"coverage": statistics.fmean(v["coverage"] for v in values),
                       "width": statistics.fmean(v["width"] for v in values),
                       "winkler": statistics.median(v["winkler"] for v in values),
                       "n": len(values)}
    result["k_median"] = statistics.median([r["metrics"]["k"] for r in records if math.isfinite(r["metrics"]["k"])])
    result["k3_median"] = statistics.median([r["metrics"]["k3"] for r in records if math.isfinite(r["metrics"]["k3"])])
    result["k_res_median"] = statistics.median([r["metrics"]["k_res"] for r in records if math.isfinite(r["metrics"]["k_res"])])
    result["k_res3_median"] = statistics.median([r["metrics"]["k_res3"] for r in records if math.isfinite(r["metrics"]["k_res3"])])
    return result


def intersection_records(records):
    """Return per-series records restricted to the common scored origins."""
    output = []
    for record in records:
        # The primary table compares parametric and conformal arms. Do not
        # let the optional scaled arm remove origins from those arms.
        origin_sets = [record["origins"].get(name, set())
                       for name in ("param", "conf", "resparam", "resparam2")]
        common = set.intersection(*origin_sets) if origin_sets else set()
        if not common:
            continue
        arms = {name: [row for row in rows if row["origin"] in common]
                for name, rows in record["arms"].items()}
        metrics = arm_metrics(record["points"], arms, record["scale_full"])
        # Keep matching diagnostics defined on the same common-origin rows.
        if arms.get("param") and arms.get("conf"):
            target = metrics["conf"]["coverage"]
            matched, k = apply_match(arms["param"], target)
            widened, k3 = apply_match(arms["conf"], metrics["param"]["coverage"])
            scale = record["scale_full"]
            match_metrics = arm_metrics(record["points"], {"match": matched}, scale)
            widened_metrics = arm_metrics(record["points"], {"conf_match": widened}, scale)
            if "match" in match_metrics:
                metrics["match"] = match_metrics["match"]
            if "conf_match" in widened_metrics:
                metrics["conf_match"] = widened_metrics["conf_match"]
            res_cov = metrics["resparam"]["coverage"]
            res_match, kres = apply_match(arms["resparam"], target)
            conf_res_match, kres3 = apply_match(arms["conf"], res_cov)
            rm = arm_metrics(record["points"], {"res_match": res_match}, scale)
            crm = arm_metrics(record["points"], {"conf_res_match": conf_res_match}, scale)
            if "res_match" in rm:
                metrics["res_match"] = rm["res_match"]
            if "conf_res_match" in crm:
                metrics["conf_res_match"] = crm["conf_res_match"]
            metrics["k"] = k
            metrics["k3"] = k3
            metrics["k_res"] = kres
            metrics["k_res3"] = kres3
        output.append({"series_key": record.get("series_key"), "metrics": metrics,
                       "origins": {name: common for name in arms},
                       "points": record["points"], "arms": arms,
                       "scale_full": record["scale_full"],
                       "scale_eval": record["scale_eval"],
                       "scale_mean": record["scale_mean"]})
    return output


def bootstrap(records, n=10000, seed=42):
    """Bootstrap series with replacement using fixed full-sample factors.

    All k values are computed once in series_record/aggregate before this
    function is called. Resamples only recompute aggregate widths, coverage,
    and median Winkler values; no matching factor is refit in a resample.
    """
    rng = random.Random(seed)
    out = defaultdict(list)
    if not records:
        return out
    for _ in range(n):
        sample = [records[rng.randrange(len(records))] for _ in records]
        a = aggregate(sample)
        # The quoted estimands are differences of means for width and
        # differences of medians for Winkler. Factors remain fixed because
        # each record already contains its full-sample k values.
        out["conf_minus_param_matched_width"].append(
            a["conf"]["width"] - a["match"]["width"])
        out["conf_widened_minus_param_matched_width"].append(
            a["conf_match"]["width"] - a["match"]["width"])
        out["conf_minus_param_nominal_winkler"].append(
            a["conf"]["winkler"] - a["param"]["winkler"])
        out["conf_minus_param_matched_winkler"].append(
            a["conf"]["winkler"] - a["match"]["winkler"])
    return out


def ci(values):
    return percentile(values, .025), percentile(values, .975)


def print_table(title, agg):
    print(f"TABLE {title}")
    print("arm coverage_base width_base relative_width_stat winkler_base n")
    for arm in ("param", "conf", "scaled", "resparam", "resparam2", "match", "conf_match", "res_match", "conf_res_match"):
        if arm in agg:
            v = agg[arm]
            print(f"{arm} coverage={v['coverage']:.4f} mean_relative_width={v['width']:.4f} "
                  f"median_winkler={v['winkler']:.4f} n={v['n']}")
    print(f"median_k={agg.get('k_median', float('nan')):.4f} "
          f"median_k3={agg.get('k3_median', float('nan')):.4f} "
          f"median_k_res={agg.get('k_res_median', float('nan')):.4f} "
          f"median_k_res3={agg.get('k_res3_median', float('nan')):.4f}")
    previous = {
        "random-200": {"param": (.9664, .7871, .5093), "conf": (.9222, .5198, .3309)},
        "deepest-20": {"param": (.9497, .5922, .4913), "conf": (.9234, .4813, .4917)},
        "top-100": {"param": (.9446, .8829, .7256), "conf": (.9162, .6244, .5630)},
        "random-200:lambda-1.0": {"param": (.9658, .7871, .5064), "conf": (.9191, .4836, .3001)},
        "deepest-20:lambda-1.0": {"param": (.9475, .5922, .4885), "conf": (.9298, .4558, .5269)},
    }.get(title, {})
    for arm, old_values in previous.items():
        if arm not in agg:
            continue
        new_values = (agg[arm]["coverage"], agg[arm]["width"], agg[arm]["winkler"])
        for metric, old, new in zip(("coverage", "width", "winkler"), old_values, new_values):
            if abs(new - old) > .005:
                print(f"WARNING value_changed_gt_0.005 arm={arm} metric={metric} old={old:.6f} new={new:.6f}")


def print_bootstrap(title, agg, boot, prefix="bootstrap_ci", resamples=10000):
    print(f"BOOTSTRAP {title} resamples={resamples} factors=fixed_full_sample")
    estimates = {
        "conf_minus_param_matched_width": agg["conf"]["width"] - agg["match"]["width"],
        "conf_widened_minus_param_matched_width": agg["conf_match"]["width"] - agg["match"]["width"],
        "conf_minus_param_nominal_winkler": agg["conf"]["winkler"] - agg["param"]["winkler"],
        "conf_minus_param_matched_winkler": agg["conf"]["winkler"] - agg["match"]["winkler"],
    }
    for metric, values in boot.items():
        lo, hi = ci(values)
        statistic = ("mean_arm_a_minus_mean_arm_b_relative_width"
                     if "width" in metric else
                     "median_arm_a_minus_median_arm_b_winkler")
        print(f"{prefix} metric={metric} statistic={statistic} "
              f"estimate={estimates[metric]:.4f} lower={lo:.4f} upper={hi:.4f} "
              f"contains_estimate={str(lo <= estimates[metric] <= hi).lower()}")
        if not (lo <= estimates[metric] <= hi):
            raise AssertionError(f"{title} {metric}: CI does not contain full-sample estimate")
        previous = {
            "random-200": {
                "conf_minus_param_matched_width": (-0.0870, 0.0503),
                "conf_widened_minus_param_matched_width": (0.1732, 0.4421),
                "conf_minus_param_nominal_winkler": (-0.4436, -0.1768),
                "conf_minus_param_matched_winkler": (-0.1182, 0.2216),
            },
            "deepest-20": {
                "conf_minus_param_matched_width": (-0.0357, 0.3212),
                "conf_widened_minus_param_matched_width": (0.1260, 0.7214),
                "conf_minus_param_nominal_winkler": (-0.4460, 0.6750),
                "conf_minus_param_matched_winkler": (-0.0510, 2.4819),
            },
        }
        old = previous.get(title, {}).get(metric)
        if old and abs(old[0] - lo) < 1e-10 and abs(old[1] - hi) < 1e-10:
            print(f"WARNING ci_endpoints_unchanged_under_new_estimand cohort={title} metric={metric}")


def print_pair_diagnostics(title, records):
    pairs_to_report = (
        ("conf_minus_param_matched", "conf", "match"),
        ("conf_widened_minus_param_matched", "conf_match", "match"),
        ("conf_minus_param_nominal", "conf", "param"),
        ("conf_minus_resparam_matched", "conf", "res_match"),
        ("conf_widened_minus_resparam", "conf_res_match", "res_match"),
    )
    print(f"PAIR_STATISTIC_DIAGNOSTICS cohort={title}")
    print("pair metric n mean_a mean_b difference_of_means mean_paired_difference "
          "median_a median_b difference_of_medians median_paired_difference")
    for pair_name, arm_a, arm_b in pairs_to_report:
        usable = [r for r in records if arm_a in r["metrics"] and arm_b in r["metrics"]]
        for metric in ("width", "winkler"):
            a = [r["metrics"][arm_a][metric] for r in usable]
            b = [r["metrics"][arm_b][metric] for r in usable]
            paired = [x - y for x, y in zip(a, b)]
            print(f"pair={pair_name} metric={metric} n={len(usable)} "
                  f"mean_a={statistics.fmean(a):.6f} mean_b={statistics.fmean(b):.6f} "
                  f"difference_of_means={statistics.fmean(a)-statistics.fmean(b):.6f} "
                  f"mean_paired_difference={statistics.fmean(paired):.6f} "
                  f"median_a={statistics.median(a):.6f} median_b={statistics.median(b):.6f} "
                  f"difference_of_medians={statistics.median(a)-statistics.median(b):.6f} "
                  f"median_paired_difference={statistics.median(paired):.6f}")


def print_normalizer_audit(title, records):
    print(f"NORMALIZER_AUDIT cohort={title} scale=median_full_series "
          "aggregation=per_series_mean_then_cohort_mean")
    print("scale_definition arm param mean_relative_width")
    for field, label in (("scale_full", "median_full_series"),
                         ("scale_eval", "median_evaluated_window"),
                         ("scale_mean", "mean_full_series")):
        values = []
        for record in records:
            rows = record["arms"].get("param", [])
            if not rows:
                continue
            scale = record[field]
            values.append(statistics.fmean(2 * row["half"] / scale for row in rows))
        print(f"scale_definition={label} arm=param mean_relative_width={statistics.fmean(values):.6f} n={len(values)}")


def print_rescaled_audit(title, records):
    print(f"RESCALED_AUDIT cohort={title}")
    for nominal, rescaled, base in (("param", "match", "parametric"),
                                    ("conf", "conf_match", "conformal"),
                                    ("resparam", "res_match", "resparametric"),
                                    ("conf", "conf_res_match", "conformal_to_resparametric")):
        nominal_records = [r for r in records if nominal in r["metrics"]]
        rescaled_records = [r for r in records if rescaled in r["metrics"]]
        nominal_n = len(nominal_records)
        rescaled_n = len(rescaled_records)
        usable = [r for r in records if nominal in r["metrics"] and rescaled in r["metrics"]]
        nominal_keys = {r.get("series_key") for r in nominal_records}
        rescaled_keys = {r.get("series_key") for r in rescaled_records}
        same_series = nominal_keys == rescaled_keys
        same_origins = all(r["origins"].get(nominal, set()) == r["origins"].get(rescaled, set())
                           for r in usable)
        origins_a_total = sum(len(r["origins"].get(nominal, set())) for r in nominal_records)
        origins_b_total = sum(len(r["origins"].get(rescaled, set())) for r in rescaled_records)
        print(f"rescaled_pair={rescaled}_vs_{nominal} base={base} series_same={str(same_series).lower()} "
              f"nominal_series_n={nominal_n} rescaled_series_n={rescaled_n} "
              f"series_intersection={len(nominal_keys & rescaled_keys)} paired_series_n={len(usable)} "
              f"origins_same={str(same_origins).lower()} origins_a_total={origins_a_total} origins_b_total={origins_b_total}")
        factor_key = {"match": "k", "conf_match": "k3", "res_match": "k_res", "conf_res_match": "k_res3"}[rescaled]
        for record in records:
            a_present = nominal in record["metrics"]
            b_present = rescaled in record["metrics"]
            if a_present != b_present:
                print(f"rescaled_missing_factor series={record.get('series_key')} arm_a={a_present} arm_b={b_present} "
                      f"factor={record['metrics'].get(factor_key, 'undefined')}")
        if not same_series or not same_origins:
            intersection = [r for r in usable if r.get("series_key") in nominal_keys & rescaled_keys]
            print(f"rescaled_intersection pair={rescaled}_vs_{nominal} "
                  f"old_series_n={len(usable)} new_series_n={len(intersection)}")
        old_width = statistics.fmean(r["metrics"][rescaled]["width"] for r in usable)
        old_winkler = statistics.median(r["metrics"][rescaled]["winkler"] for r in usable)
        intersection = [r for r in usable if r.get("series_key") in nominal_keys & rescaled_keys]
        new_width = statistics.fmean(r["metrics"][rescaled]["width"] for r in intersection)
        new_winkler = statistics.median(r["metrics"][rescaled]["winkler"] for r in intersection)
        print(f"rescaled_values pair={rescaled}_vs_{nominal} old_mean_width={old_width:.6f} new_mean_width={new_width:.6f} "
              f"old_median_winkler={old_winkler:.6f} new_median_winkler={new_winkler:.6f}")


def print_reconciliation(title, records):
    pairs_to_report = (
        ("conf_minus_param_matched_width", "conf", "match", "width", "mean"),
        ("conf_widened_minus_param_matched_width", "conf_match", "match", "width", "mean"),
        ("conf_minus_param_nominal_winkler", "conf", "param", "winkler", "median"),
        ("conf_minus_param_matched_winkler", "conf", "match", "winkler", "median"),
    )
    print(f"RECONCILIATION cohort={title}")
    for name, arm_a, arm_b, metric, statistic in pairs_to_report:
        usable = [r for r in records if arm_a in r["metrics"] and arm_b in r["metrics"]]
        a = [r["metrics"][arm_a][metric] for r in usable]
        b = [r["metrics"][arm_b][metric] for r in usable]
        paired = [x - y for x, y in zip(a, b)]
        table_value = (statistics.fmean(a) - statistics.fmean(b)
                       if statistic == "mean" else statistics.median(a) - statistics.median(b))
        paired_value = statistics.fmean(paired) if statistic == "mean" else statistics.median(paired)
        passed = math.isclose(table_value, paired_value, rel_tol=1e-9, abs_tol=1e-9)
        print(f"reconcile metric={name} statistic={statistic}_of_{metric}s n={len(usable)} "
              f"table_value={table_value:.9f} paired_value={paired_value:.9f} status={'PASS' if passed else 'FAIL'}")


def make_records(cohort, weight=0.4):
    records = []
    for key, observations in cohort:
        record = series_record(observations, weight=weight, series_key=key)
        if record is not None:
            records.append(record)
    return records


def width_gap_bootstrap(records, n=10000, seed=42):
    rng = random.Random(seed)
    values = []
    for _ in range(n):
        sample = [records[rng.randrange(len(records))] for _ in records]
        values.append(statistics.fmean(r["metrics"]["param"]["width"] for r in sample)
                      - statistics.fmean(r["metrics"]["conf"]["width"] for r in sample))
    return values


def coverage_gap_bootstrap(records, n=10000, seed=42):
    rng = random.Random(seed)
    values = []
    for _ in range(n):
        sample = [records[rng.randrange(len(records))] for _ in records]
        values.append(statistics.fmean(r["metrics"]["param"]["coverage"] for r in sample)
                      - statistics.fmean(r["metrics"]["conf"]["coverage"] for r in sample))
    return values


def matched_width_bootstrap(records, n=10000, seed=42):
    rng = random.Random(seed)
    values = []
    for _ in range(n):
        sample = [records[rng.randrange(len(records))] for _ in records]
        values.append(statistics.fmean(r["metrics"]["conf"]["width"] for r in sample)
                      - statistics.fmean(r["metrics"]["match"]["width"] for r in sample))
    return values


def matched_winkler_bootstrap(records, n=10000, seed=42):
    rng = random.Random(seed)
    values = []
    for _ in range(n):
        sample = [records[rng.randrange(len(records))] for _ in records]
        values.append(statistics.median(r["metrics"]["conf"]["winkler"] for r in sample)
                      - statistics.median(r["metrics"]["match"]["winkler"] for r in sample))
    return values


def quartiles(values):
    return percentile(values, .25), statistics.median(values), percentile(values, .75)


def matched_rule_results(records):
    """Compare per-series and cohort-level coverage-matching rules."""
    conf_target = statistics.fmean(r["metrics"]["conf"]["coverage"] for r in records)
    rules = {"per_series_target": [], "cohort_target_per_series_k": [],
             "cohort_target_common_k": []}
    all_param_rows = [row for r in records for row in r["arms"].get("param", [])]
    common_k = fit_k(all_param_rows, conf_target)
    for record in records:
        scale = record["scale_full"]
        param_rows = record["arms"].get("param", [])
        for name, target, fixed in (
            ("per_series_target", record["metrics"]["conf"]["coverage"], None),
            ("cohort_target_per_series_k", conf_target, None),
            ("cohort_target_common_k", conf_target, common_k),
        ):
            rows, k = apply_match(param_rows, target, fixed_k=fixed)
            if rows:
                metrics = arm_metrics(record["points"], {name: rows}, scale)[name]
                rules[name].append({"metrics": metrics, "k": k})
    return conf_target, common_k, rules


def print_stability(title, records):
    conf_target, common_k, rules = matched_rule_results(records)
    print(f"MATCH_STABILITY cohort={title} cohort_mean_conf_coverage={conf_target:.6f} common_k={common_k:.6f}")
    print("rule n mean_coverage mean_relative_width median_winkler median_k k_q25 k_q75")
    values = {}
    for name, rows in rules.items():
        values[name] = {
            "coverage": statistics.fmean(x["metrics"]["coverage"] for x in rows),
            "width": statistics.fmean(x["metrics"]["width"] for x in rows),
            "winkler": statistics.median(x["metrics"]["winkler"] for x in rows),
            "k": statistics.median(x["k"] for x in rows),
            "q25": percentile([x["k"] for x in rows], .25),
            "q75": percentile([x["k"] for x in rows], .75),
        }
        v = values[name]
        print(f"rule={name} n={len(rows)} mean_coverage={v['coverage']:.6f} "
              f"mean_relative_width={v['width']:.6f} median_winkler={v['winkler']:.6f} "
              f"median_k={v['k']:.6f} k_q25={v['q25']:.6f} k_q75={v['q75']:.6f}")
        if name == "per_series_target":
            previous_k = {"random-200": 0.64, "deepest-20": 0.71, "top-100": 0.73}.get(title)
            if previous_k is not None and abs(v["k"] - previous_k) > .005:
                print(f"WARNING value_changed_gt_0.005 arm=matched_parametric_median_k "
                      f"old={previous_k:.6f} new={v['k']:.6f}")
    widths = [v["width"] for v in values.values()]
    winklers = [v["winkler"] for v in values.values()]
    width_spread = (max(widths) - min(widths)) / min(widths) if min(widths) else float("inf")
    winkler_spread = (max(winklers) - min(winklers)) / min(winklers) if min(winklers) else float("inf")
    print(f"match_stability_spread cohort={title} width_relative_spread={width_spread:.6f} winkler_relative_spread={winkler_spread:.6f}")
    if max(width_spread, winkler_spread) > .05:
        print(f"WARNING matched_arm_instability cohort={title} spread_gt_5_percent=true recommend_not_point_value_at_n={len(records)}")
    if max(width_spread, winkler_spread) <= .02:
        print(f"MATCH_RULES_AGREE_WITHIN_2_PERCENT cohort={title} true")
    else:
        print(f"MATCH_RULES_AGREE_WITHIN_2_PERCENT cohort={title} false")
    return values


def print_table_viii(title, records):
    conf_target, common_k, rules = matched_rule_results(records)
    conf_width = statistics.fmean(r["metrics"]["conf"]["width"] for r in records)
    conf_winkler = statistics.median(r["metrics"]["conf"]["winkler"] for r in records)
    print(f"TABLE_VIII cohort={title}")
    print("cohort convention target_coverage matched_coverage matched_width matched_winkler "
          "median_k conf_width conf_winkler conf_minus_matched_winkler_pct status")
    for convention in ("per_series_target", "cohort_target_per_series_k", "cohort_target_common_k"):
        # rules stores a list of per-series results; aggregate here.
        rows = rules[convention]
        matched_coverage = statistics.fmean(x["metrics"]["coverage"] for x in rows)
        matched_width = statistics.fmean(x["metrics"]["width"] for x in rows)
        matched_winkler = statistics.median(x["metrics"]["winkler"] for x in rows)
        median_k = statistics.median(x["k"] for x in rows)
        gap_pct = 100 * (conf_winkler - matched_winkler) / matched_winkler
        target = (f"per_series_mean={conf_target:.6f}"
                  if convention == "per_series_target" else f"{conf_target:.6f}")
        print(f"table_viii cohort={title} convention={convention} target_coverage={target} "
              f"matched_coverage={matched_coverage:.6f} matched_width={matched_width:.6f} "
              f"matched_winkler={matched_winkler:.6f} median_k={median_k:.6f} "
              f"conf_width={conf_width:.6f} conf_winkler={conf_winkler:.6f} "
              f"conf_minus_matched_winkler_pct={gap_pct:.6f} status=CONVENTION_DEPENDENT")


def print_decile_convention_sensitivity(title, records):
    conf_target, common_k, rules = matched_rule_results(records)
    conf_winkler = statistics.median(r["metrics"]["conf"]["winkler"] for r in records)
    gaps = {}
    for convention, rows in rules.items():
        matched_winkler = statistics.median(x["metrics"]["winkler"] for x in rows)
        gaps[convention] = 100 * (conf_winkler - matched_winkler) / matched_winkler
    signs = {value > 0 for value in gaps.values() if value != 0}
    print(f"decile_convention_sensitivity cohort={title} "
          f"per_series_target_pct={gaps['per_series_target']:.6f} "
          f"cohort_target_per_series_k_pct={gaps['cohort_target_per_series_k']:.6f} "
          f"cohort_target_common_k_pct={gaps['cohort_target_common_k']:.6f} "
          f"status=CONVENTION_DEPENDENT")
    if len(signs) > 1:
        print(f"WARNING decile_convention_sign_flip cohort={title}")


def print_final_table(final_values, seed):
    with open(__file__, "rb") as handle:
        file_hash = hashlib.sha256(handle.read()).hexdigest()
    try:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", os.path.basename(__file__)],
                                  cwd=os.path.dirname(__file__), capture_output=True,
                                  text=True, check=True).stdout.strip()
        commit = (subprocess.run(["git", "rev-parse", "HEAD"], cwd=os.path.dirname(__file__),
                                 capture_output=True, text=True, check=True).stdout.strip()
                  if tracked else "not_version_controlled")
    except (OSError, subprocess.CalledProcessError):
        commit = "unavailable_not_in_worktree"
    print("FINAL_REPRODUCIBILITY script=interval_extension.py "
          f"file_sha256={file_hash} git_commit={commit} seed={seed} status=FINAL")
    previous_hash = "aaa3668bc48f3b332007444688fa755832298e78998739da7ae34f8985a6c1a1"
    print(f"SCRIPT_IDENTITY previous_sha256={previous_hash} current_sha256={file_hash} "
          f"byte_identical={str(file_hash == previous_hash).lower()} "
          "changed_functions=main")
    print("FINAL_ARM_TABLE cohort arm coverage mean_relative_width median_winkler n status")
    for cohort, aggregate_values in final_values.items():
        for arm in ("param", "conf", "scaled", "resparam", "resparam2", "match", "conf_match", "res_match", "conf_res_match"):
            if arm not in aggregate_values:
                print(f"final cohort={cohort} arm={arm} status=STALE")
                continue
            value = aggregate_values[arm]
            print(f"final cohort={cohort} arm={arm} coverage={value['coverage']:.6f} "
                  f"mean_relative_width={value['width']:.6f} median_winkler={value['winkler']:.6f} "
                  f"n={value['n']} status=FINAL")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bootstrap", type=int, default=10000)
    ap.add_argument("--expected-param", type=float, default=0.9664)
    ap.add_argument("--expected-conf", type=float, default=0.9222)
    ap.add_argument("--expected-mape", type=float, default=6.40)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    series = load(args.csv)
    eligible = [(key, values) for key, values in series.items() if len(values) >= 130]
    by_depth = sorted(eligible, key=lambda kv: -len(kv[1]))
    rng = random.Random(42)
    random_cohort = rng.sample(eligible, min(200, len(eligible)))
    cohorts = [("random-200", random_cohort), ("deepest-20", by_depth[:20]),
               ("top-100", by_depth[:100])]
    final_values = {}
    print(f"DATA rows_series={len(series)} eligible_series={len(eligible)}")
    print(f"ACCEPTANCE_GATE random_200 param_coverage={args.expected_param:.4f} "
          f"conf_coverage={args.expected_conf:.4f} blend_median_mape={args.expected_mape:.2f}")
    gate_records = make_records(random_cohort)
    gate = aggregate(gate_records)
    mape_values = []
    for _, obs in random_cohort:
        pts = gate_records[len(mape_values)]["points"] if len(mape_values) < len(gate_records) else []
        if pts:
            scored = pts[max(CALIBRATION, 20):]
            mape_values.append(statistics.fmean(abs(p["actual"] - p["prediction"]) / p["actual"] * 100 for p in scored))
    # The acceptance MAPE is the established blend median; use the same paired origins.
    blend_mape = statistics.median(mape_values) if mape_values else float("nan")
    print(f"GATE_RESULT random_200 param_coverage={gate['param']['coverage']:.4f} "
          f"conf_coverage={gate['conf']['coverage']:.4f} blend_median_mape={blend_mape:.2f}")
    if abs(gate["param"]["coverage"] - args.expected_param) > .002 or abs(gate["conf"]["coverage"] - args.expected_conf) > .01 or abs(blend_mape - args.expected_mape) > .01:
        print("GATE_FAIL stop_before_new_arms=true")
        return 2
    print("GATE_PASS stop_before_new_arms=false")

    for name, cohort in cohorts:
        records = make_records(cohort)
        print(f"COHORT {name} dropped={len(cohort)-len(records)}/{len(cohort)}")
        aggregate_values = aggregate(records)
        final_values[name] = aggregate_values
        print_table(name, aggregate_values)
        print_normalizer_audit(name, records)
        print_pair_diagnostics(name, records)
        print_rescaled_audit(name, records)
        print_stability(name, records)
        print_table_viii(name, records)
        boot = bootstrap(records, args.bootstrap)
        print_bootstrap(name, aggregate_values, boot, resamples=args.bootstrap)
        if name == "top-100":
            matched_width = aggregate_values["conf"]["width"] - aggregate_values["match"]["width"]
            matched_winkler = aggregate_values["conf"]["winkler"] - aggregate_values["match"]["winkler"]
            width_values = matched_width_bootstrap(records, args.bootstrap)
            winkler_values = matched_winkler_bootstrap(records, args.bootstrap)
            width_lo, width_hi = ci(width_values)
            wink_lo, wink_hi = ci(winkler_values)
            print(f"top100_ci metric=conf_minus_param_matched_width statistic=mean_arm_a_minus_mean_arm_b_relative_width "
                  f"estimate={matched_width:.6f} lower={width_lo:.6f} upper={width_hi:.6f} "
                  f"contains_estimate={str(width_lo <= matched_width <= width_hi).lower()}")
            print(f"top100_ci metric=conf_minus_param_matched_winkler statistic=median_arm_a_minus_median_arm_b_winkler "
                  f"estimate={matched_winkler:.6f} lower={wink_lo:.6f} upper={wink_hi:.6f} "
                  f"contains_estimate={str(wink_lo <= matched_winkler <= wink_hi).lower()}")
        print("PAIRING_AUDIT")
        base = records[0]["origins"] if records else {}
        for arm in ("param", "conf", "scaled", "resparam", "resparam2"):
            origin_sets = [r["origins"].get(arm, set()) for r in records]
            counts = statistics.fmean(len(x) for x in origin_sets) if origin_sets else 0
            diff = sum(len(x ^ y) for x, y in zip(origin_sets, [r["origins"].get("param", set()) for r in records]))
            print(f"origins arm={arm} mean_count={counts:.2f} total_set_difference_vs_param={diff}")
        same = all(r["origins"].get("scaled", set()) == r["origins"].get("conf", set()) for r in records)
        print(f"scaled_and_conf_same_origins={str(same).lower()}")
        if not same:
            intersection = intersection_records(records)
            print(f"INTERSECTION_REScore {name} dropped={len(records)-len(intersection)}/{len(records)}")
            old_aggregate = aggregate(records)
            new_aggregate = aggregate(intersection)
            print_table(f"{name}:common_origin_intersection", new_aggregate)
            print("PAIRING_INTERSECTION_TABLE arm metric old new delta changed_gt_0.005")
            for arm in ("param", "conf", "scaled", "resparam", "resparam2", "match", "conf_match", "res_match", "conf_res_match"):
                if arm not in old_aggregate or arm not in new_aggregate:
                    continue
                for metric in ("coverage", "width", "winkler"):
                    old_value = old_aggregate[arm][metric]
                    new_value = new_aggregate[arm][metric]
                    delta = new_value - old_value
                    print(f"intersection arm={arm} metric={metric} old={old_value:.4f} new={new_value:.4f} "
                          f"delta={delta:.4f} changed_gt_0.005={str(abs(delta) > .005).lower()}")
            for arm in ("param", "conf", "scaled", "resparam", "resparam2"):
                old_n = statistics.fmean(len(r["origins"].get(arm, set())) for r in records)
                new_n = statistics.fmean(len(r["origins"].get(arm, set())) for r in intersection)
                print(f"intersection_origin_count arm={arm} old_mean={old_n:.2f} new_mean={new_n:.2f}")

    # Required second forecaster: lambda=1.0 is the moving-average arm.
    ma_cohort = [("random-200", random_cohort), ("deepest-20", by_depth[:20])]
    for name, cohort in ma_cohort:
        records = make_records(cohort, weight=1.0)
        print(f"MA_ONLY_TABLE {name} lambda=1.0 dropped={len(cohort)-len(records)}/{len(cohort)}")
        aggregate_values = aggregate(records)
        print_table(f"{name}:lambda-1.0", aggregate_values)
        print_normalizer_audit(f"{name}:lambda-1.0", records)
        print_pair_diagnostics(f"{name}:lambda-1.0", records)
        print_rescaled_audit(f"{name}:lambda-1.0", records)
        boot = bootstrap(records, args.bootstrap)
        print_bootstrap(f"{name}:lambda-1.0", aggregate_values, boot,
                        prefix="ma_bootstrap_ci", resamples=args.bootstrap)
        if name == "deepest-20":
            estimate = aggregate_values["conf"]["winkler"] - aggregate_values["match"]["winkler"]
            values = matched_winkler_bootstrap(records, args.bootstrap)
            lo, hi = ci(values)
            print(f"lambda1_ci metric=conf_minus_param_matched_winkler statistic=median_arm_a_minus_median_arm_b_winkler "
                  f"estimate={estimate:.6f} lower={lo:.6f} upper={hi:.6f} "
                  f"contains_estimate={str(lo <= estimate <= hi).lower()}")

    print("DECILE_TABLE_FINAL")
    nominal_stability = []
    decile_size = max(1, len(by_depth) // 10)
    for i in range(10):
        cohort = by_depth[i * decile_size:(i + 1) * decile_size if i < 9 else len(by_depth)]
        records = make_records(cohort)
        a = aggregate(records)
        depths = [len(observations) for _, observations in cohort]
        orientation = "deepest" if i == 0 else ("shallowest" if i == 9 else "intermediate")
        if records:
            width_advantage = 100 * (a["conf"]["width"] - a["param"]["width"]) / a["param"]["width"]
            winkler_advantage = 100 * (a["conf"]["winkler"] - a["param"]["winkler"]) / a["param"]["winkler"]
        else:
            width_advantage = winkler_advantage = float("nan")
        if len(cohort) < 10:
            print(f"WARNING decile={i+1} fewer_than_10_series n={len(cohort)}")
        if records:
            coverage_gaps = coverage_gap_bootstrap(records, args.bootstrap)
            coverage_estimate = a["param"]["coverage"] - a["conf"]["coverage"]
            coverage_lo, coverage_hi = ci(coverage_gaps)
            print(f"decile={i+1} n={len(cohort)} depth_range={min(depths)}-{max(depths)} "
                  f"mean_param_coverage={a['param']['coverage']:.6f} mean_conf_coverage={a['conf']['coverage']:.6f} "
                  f"coverage_gap_param_minus_conf={coverage_estimate:.6f} coverage_gap_ci95=[{coverage_lo:.6f},{coverage_hi:.6f}] "
                  f"conf_minus_param_width_pct={width_advantage:.6f} conf_minus_param_winkler_pct={winkler_advantage:.6f}")
            nominal_stability.append(width_advantage < 0 and winkler_advantage < 0)
        else:
            print(f"decile={i+1} n={len(cohort)} depth_range={min(depths)}-{max(depths)} status=STALE")
    failed_deciles = [index + 1 for index, passed in enumerate(nominal_stability) if not passed]
    print(f"NOMINAL_CLAIM_STABILITY pass={str(not failed_deciles).lower()} "
          f"all_deciles={len(nominal_stability)}")
    if failed_deciles:
        print(f"NOMINAL_CLAIM_FAILURE deciles={','.join(map(str, failed_deciles))} "
              "reason=conformal_not_narrower_or_not_lower_winkler")

    curve_path = os.path.join(args.out, "coverage_width_curve.csv")
    curve_data = defaultdict(lambda: defaultdict(list))
    curve_winkler = defaultdict(lambda: defaultdict(list))
    for label, cohort in (("random-200", random_cohort), ("deepest-20", by_depth[:20])):
        for arm in ("conf", "param"):
            rows = [series_record(v) for _, v in cohort]
            rows = [r for r in rows if r]
            for j in range(25):
                k = .4 + j * (1.6 / 24)
                cov = []
                widths = []
                winklers = []
                for r in rows:
                    source = r["arms"][arm]
                    if not source:
                        continue
                    cov.append(statistics.fmean(abs(x["actual"] - x["prediction"]) <= k * x["half"] for x in source))
                    widths.append(statistics.fmean(2 * k * x["half"] / r["scale_full"] for x in source))
                    winklers.append(statistics.median(
                        winkler(x["actual"], x["prediction"], k * x["half"]) / r["scale_full"]
                        for x in source))
                if cov:
                    coverage = statistics.fmean(cov)
                    width = statistics.fmean(widths)
                    winkler_value = statistics.median(winklers)
                    curve_data[label][arm].append((k, coverage, width))
                    curve_winkler[label][arm].append((k, coverage, winkler_value))
    with open(curve_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("cohort", "arm", "k", "coverage", "width", "width_over_nominal", "winkler"))
        for label, arms in curve_data.items():
            nominal = {arm: next((row[2] for row in rows if abs(row[0] - 1.0) < 1e-9), float("nan"))
                       for arm, rows in arms.items()}
            for arm, rows in arms.items():
                for index, (k, coverage, width) in enumerate(rows):
                    normalized = width / nominal[arm] if nominal[arm] else float("nan")
                    writer.writerow((label, arm, f"{k:.6f}", f"{coverage:.6f}",
                                    f"{width:.6f}", f"{normalized:.6f}",
                                    f"{curve_winkler[label][arm][index][2]:.6f}"))
    print(f"CURVE_OUTPUT path={curve_path}")
    for label, arms in curve_data.items():
        conf_curve = arms.get("conf", [])
        param_curve = arms.get("param", [])
        if conf_curve and param_curve:
            differences = [c[1] - p[1] for c, p in zip(conf_curve, param_curve)]
            crossings = []
            for index in range(len(differences) - 1):
                left, right = differences[index], differences[index + 1]
                if left == 0:
                    crossings.append(conf_curve[index][0])
                elif left * right < 0:
                    k0, k1 = conf_curve[index][0], conf_curve[index + 1][0]
                    crossings.append(k0 + (k1 - k0) * (-left) / (right - left))
            if crossings:
                print(f"CURVE_SUMMARY cohort={label} coverage_curve_cross_k={crossings[0]:.6f} crossing_in_grid=true")
                if label == "deepest-20":
                    nearest_index = min(range(len(conf_curve)), key=lambda i: abs(conf_curve[i][0] - crossings[0]))
                    print("CURVE_NEAREST_DEEPEST_ROWS k conf_coverage conf_mean_relative_width param_coverage param_mean_relative_width")
                    for index in range(max(0, nearest_index - 1), min(len(conf_curve), nearest_index + 2)):
                        k, conf_cov, conf_width = conf_curve[index]
                        _, param_cov, param_width = param_curve[index]
                        print(f"curve_nearest k={k:.6f} conf_coverage={conf_cov:.6f} conf_mean_relative_width={conf_width:.6f} "
                              f"param_coverage={param_cov:.6f} param_mean_relative_width={param_width:.6f}")
            else:
                closest = min(zip(differences, conf_curve), key=lambda pair: abs(pair[0]))[1][0]
                print(f"CURVE_SUMMARY cohort={label} coverage_curve_cross_k=none "
                      f"closest_grid_k={closest:.6f} crossing_in_grid=false")
            for target_k in (.6, .8, 1.0, 1.2, 1.4):
                def interpolate(curve):
                    if target_k <= curve[0][0]:
                        return curve[0][1]
                    if target_k >= curve[-1][0]:
                        return curve[-1][1]
                    for left, right in zip(curve, curve[1:]):
                        if left[0] <= target_k <= right[0]:
                            fraction = (target_k - left[0]) / (right[0] - left[0])
                            return left[1] + fraction * (right[1] - left[1])
                    return curve[-1][1]
                print(f"curve cohort={label} k={target_k:.1f} conf_coverage={interpolate(conf_curve):.4f} "
                      f"param_coverage={interpolate(param_curve):.4f}")
        if conf_curve and param_curve:
            def by_coverage(curve, target):
                if target < curve[0][1] or target > curve[-1][1]:
                    return None
                for left, right in zip(curve, curve[1:]):
                    if left[1] <= target <= right[1]:
                        fraction = (target - left[1]) / (right[1] - left[1]) if right[1] != left[1] else 0.0
                        return left[2] + fraction * (right[2] - left[2])
                return curve[-1][2]
            low = max(conf_curve[0][1], param_curve[0][1])
            high = min(conf_curve[-1][1], param_curve[-1][1])
            if low <= high:
                grid = [low + (high - low) * i / 1000 for i in range(1001)]
                gaps = [(abs(by_coverage(conf_curve, c) - by_coverage(param_curve, c)), c,
                         by_coverage(conf_curve, c) - by_coverage(param_curve, c)) for c in grid]
                _, common_cov, width_gap = min(gaps, key=lambda item: item[0])
                conf_width = by_coverage(conf_curve, common_cov)
                param_width = by_coverage(param_curve, common_cov)
                print(f"CURVE_EQUAL_COVERAGE cohort={label} coverage={common_cov:.6f} "
                      f"conf_width={conf_width:.6f} param_width={param_width:.6f} "
                      f"conf_minus_param_width_pct={100*(conf_width-param_width)/param_width:.6f} "
                      "basis=absolute_width_interpolated_at_common_coverage")
            else:
                print(f"CURVE_EQUAL_COVERAGE cohort={label} status=no_common_coverage_range")
    print("CURVE_DATA_FULL cohort arm k coverage width width_over_nominal winkler")
    for label, arms in curve_data.items():
        nominal = {arm: next((row[2] for row in rows if abs(row[0] - 1.0) < 1e-9), float("nan"))
                   for arm, rows in arms.items()}
        for arm in ("conf", "param"):
            for index, (k, coverage, width) in enumerate(arms.get(arm, [])):
                normalized = width / nominal[arm] if nominal[arm] else float("nan")
                print(f"curve_data cohort={label} arm={arm} k={k:.6f} coverage={coverage:.6f} "
                      f"width={width:.6f} width_over_nominal={normalized:.6f} "
                      f"winkler={curve_winkler[label][arm][index][2]:.6f}")
    print("NOTE residual_parametric_arm_changes_ranking=inspect_table resparam_vs_param")
    print("NOTE pairing_scaled_and_conf_identical=see_pairing_audit")
    print("OLD_HARNESS_USAGE paper_extra_tables.py=none source=interval_extension.py")
    print_final_table(final_values, seed=42)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
