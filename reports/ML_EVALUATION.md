# ML / forecasting evaluation

## Scope and conclusion

The repository does not contain a serialized production model artifact. Forecasting is runtime Python code with walk-forward gates. The committed snapshot is `data/gov_prices_60days.csv`, which contains 980 rows across 20 market/commodity series but covers only August 2026 and has irregular per-series observation counts (48–50). This is insufficient evidence for a production accuracy claim.

On a final seven-observation holdout per series, the simple linear-trend baseline had the lowest mean-of-series MAE/RMSE, but every mean-of-series R² was negative. Metrics are averaged per series, not pooled across all observations. The correct SIH claim is therefore that the system has a tested forecasting framework, not that the forecast is already validated for deployment.

## Aggregate metrics

| Model | MAE (₹/qtl) | RMSE (₹/qtl) | R² |
|---|---:|---:|---:|
| Naive last value | 42.22 | 48.82 | -2.15 |
| Training mean | 38.63 | 46.36 | -1.28 |
| Linear trend | 29.60 | 37.23 | -0.50 |

The detailed per-series calculations and source inventory are in `ml_evaluation_metrics.json`. The JSON records the aggregation method explicitly. `holdout_error.svg` is a compact visual summary for the judge folder. No classification metrics, confusion matrix, or ROC curve are applicable: the current task is continuous price forecasting.

## Data quality

- 980 rows; 20 market/commodity series; no missing fields or exact duplicates found in the Phase 1 inventory.
- Date range is 01/08/2026–31/08/2026 despite the filename `60days`.
- There is no independently held-out production period beyond this snapshot and no committed trained artifact to compare with the runtime implementation.

## Demo decision

Forecasting is not the headline demo path. The DirectLink rupee breakdown is deterministic, explainable, and independently tested. Before presenting forecast accuracy to judges, refresh history, freeze a time-based test split, run the existing backtest/gates, and publish model-load provenance.
