# Krishi Bazaar Forecasting Engine

This document details the architecture and operational constraints of the Krishi Bazaar forecasting engine.

## 1. Core Philosophy: The LLM Role

**The LLM never predicts a number.** 

The engine uses classical statistical models and Gradient Boosting Machines (GBMs) for numerical time-series forecasting. The LLM's role is strictly confined to **event extraction**. It reads unstructured text (news articles, government reports) and extracts structured intelligence—specifically, market events like supply gluts or policy changes that may exert upward or downward pressure on prices. These events are transformed into categorical or numerical features (e.g., `event_pressure = -1, 0, or 1`) and fed into the downstream quantitative models.

## 2. Dependencies and Installation

Core dependencies (FastAPI, Supabase) are listed in `requirements.txt`.
Advanced ML forecasting models require optional dependencies. To enable `lightgbm` and `statsmodels` for Gradient Boosting and Holt-Winters forecasting, you must install the ML extensions:

```bash
pip install -r requirements-forecast-ml.txt
```

This separation ensures that environments unable to compile native ML extensions (e.g., specific Windows/ARM architectures or minimal Docker images) can still run the core API and fallback forecasting models.

## 3. Walk-Forward Backtesting and Kill-Gates

Because agricultural data can be sparse or noisy, the engine implements a strict walk-forward backtesting harness to measure real-world out-of-sample accuracy. 

To protect users from spurious predictions driven by insufficient data, the engine enforces progressive "Kill-Gates":

- **G1 (Rule-Based Minimums)**: If a market has fewer than **10** distinct observation days (`MIN_OBSERVATIONS` in `forecasting/engine.py`), no prediction is produced (`status='insufficient_data'`). Between 10–14 observations only the moving-average tier runs (`method='moving_avg'`, `confidence='medium'`); the blend tier requires 15+, and `confidence='high'` requires 20+. Any UI or API surface quoting these thresholds must read them from the forecasting code constants, not hardcode them.
- **G2 (Honest Backtest Existence)**: An honest backtest requires a minimum data length to simulate folds. The threshold is defined as `TOTAL_TEST_DAYS + 1` (currently 57 days). If a market has fewer than 57 days of distinct historical arrival dates, no honest backtest can be constructed. In this scenario, we ship the model but label the accuracy card as **"Backfill pending"**.
- **G3 (Model Performance Guarantee)**: A complex model (like GBM) must demonstrably beat a simpler baseline (like Naive Last-Week-Same-Day) on the backtest harness to be selected for production. If it fails, the system falls back to the simpler model.

## 4. Feature Pressure and Variance Logic

The `FeatureOLS` model builds a wide matrix of signals, including:
- District-level arrival volumes
- Cumulative weather data (7-day rainfall, temperature)
- LLM-extracted market event pressure (`event_pressure`)

Before training, the model strictly enforces variance checks using Gaussian elimination principles. If a feature lacks variance (e.g., 14 days of identical 0.0mm precipitation, or an event whose pressure has decayed uniformly to 0), it is **dynamically dropped** from the training matrix. This prevents singular matrix errors and ensures the model gracefully degrades to relying only on high-variance signals.

## 5. Global GBM Status

The Gradient Boosting model (`GlobalGBM`) has been refactored to remove global state and adhere to strict walk-forward boundaries.
**Current Status**: 
- **Evaluation Status**: `BLOCKED` (Phase 6). The current smoke test database lacks sufficient history (requires 57+ days for training/calibration) to produce valid out-of-sample predictions.
- **Automatic-Selection Status**: **Disabled**. Because the model cannot currently be verified against baseline models in the backtest harness, the engine will safely fall back to baselines (e.g., Naive or Moving Average) and will not automatically promote GBM.
- **Explicit-Selection Availability**: **Available**. Users may explicitly select `gbm`. The engine uses the pretrained global model when available, otherwise records `fallback_from=gbm` and uses `feature_ols` when its features and sample size are sufficient before falling back to the tiered baseline.

## 6. Current Accuracy Card

*Due to the ongoing data.gov.in upstream outage (Incident #DG-2026-09), sufficient multi-month market history is currently unavailable. The metrics below are placeholders pending the resumption of historical data ingestion.*

### Global Metrics (All Markets)
- **Mean Absolute Error (MAE)**: TBD ₹
- **Winsorized MAPE**: TBD %
- **Interval Coverage (1.96σ)**: TBD %
- **Prediction Failure (NaN) Rate**: TBD %
- **Best Performing Model**: TBD

### Model Fallback Ratios
- GBM selected: TBD %
- Feature OLS selected: TBD %
- Holt-Winters selected: TBD %
- Naive Fallback selected: TBD %

## 7. Re-running the Backtest

Once data.gov.in access is restored and the historical backfill is complete, re-run the backtest harness to update the accuracy card with real out-of-sample metrics.

Run the following command from the project root:

```bash
python -m scripts.run_backtest
```

This will run the walk-forward evaluation across all active `(market, commodity)` pairs and output the aggregated metrics.
