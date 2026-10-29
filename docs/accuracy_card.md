# Forecasting Model Accuracy Card

**Status:** `BLOCKED` (Phase 6)
**Reason:** `insufficient_training_or_calibration_history`
**Evaluation Scope:** `smoke`

## Executive Summary

The newly implemented LightGBM global forecasting model is currently **blocked** from automated promotion. While the data pipelines, walk-forward evaluation harness, and promotion gates are fully wired and functional, the model cannot be certified for live production use because there is currently insufficient live history in the primary pairs to support valid training and calibration splits.

As a result, no accuracy card can be definitively established for the GBM model at this time. **Automatic Selection (promotion)** is safely disabled, and the engine will fall back to baselines (Naive, Moving Average). **Explicit Selection** is still available (users can request the `gbm` model via the API), but its predictions are unverified.

## Evaluation Results (Smoke Test)

The following metrics were derived using a 120-day legacy history scope (`smoke` profile) on Lasalgaon Onion. Because the GBM model demands a strict pre-fold chronological split to determine early-stopping iterations (calibration), it yields 0 valid predictions in this limited historical window.

### Baseline Benchmarks

| Model | Status | MAPE (Winsorized) | Directional Accuracy | Interval Coverage | Valid Predictions |
|-------|--------|-------------------|----------------------|-------------------|-------------------|
| **Naive (Lag 7)** | `ok` | 12.23% | 33.33% | 0.00% | 23 / 28 |
| **Moving Average** | `ok` | 11.53% | 33.33% | 35.71% | 28 / 28 |
| **OLS** | `ok` | 13.41% | 33.33% | 14.29% | 28 / 28 |
| **LightGBM** | `blocked` | N/A | N/A | N/A | 0 / 28 |

### Fold Execution Statistics
- **Requested Calendar Folds:** 8
- **Folds Skipped (Insufficient Training):** 4
- **Executed Folds:** 4
- **Folds with Observed Test Data:** 4
- **Folds Considered for Directional Accuracy:** 3

## Next Steps to Unblock (Phase 7 Certification)

To certify this forecasting upgrade and establish the final accuracy card, the following requirements remain open:

1. **Backfill Extension:** Historical pricing data must be backfilled to at least 1-2 years to allow the global GBM model to satisfy its structural data requirements.
2. **Clean ML CI Run:** Real-ML tests and baseline verification must execute completely cleanly in CI without warnings, or with all warnings strictly classified.
3. **Full Scale Evaluation:** A full walk-forward execution over the expanded history must produce valid predictions where the LightGBM model beats the baselines and satisfies Gates G2 and G3.

Until these conditions are met, the engine will safely fallback to the baselines (or Naive) without propagating errors.
