# Krishi Bazaar Forecasting Engine

This document details the architecture and operational constraints of the Krishi Bazaar forecasting engine.

## 1. Core Philosophy: The LLM Role

**The LLM never predicts a number.** 

The engine uses classical statistical models and Gradient Boosting Machines (GBMs) for numerical time-series forecasting. The LLM's role is strictly confined to **event extraction**. It reads unstructured text (news articles, government reports) and extracts structured intelligence—specifically, market events like supply gluts or policy changes that may exert upward or downward pressure on prices. These events are transformed into categorical or numerical features (e.g., `event_pressure = -1, 0, or 1`) and fed into the downstream quantitative models.

## 2. Walk-Forward Backtesting and Kill-Gates

Because agricultural data can be sparse or noisy, the engine implements a strict walk-forward backtesting harness to measure real-world out-of-sample accuracy. 

To protect users from spurious predictions driven by insufficient data, the engine enforces progressive "Kill-Gates":

- **G1 (Rule-Based Minimums)**: If a market has fewer than 14 historical data points, forecasting is disabled completely for that commodity.
- **G2 (Honest Backtest Existence)**: An honest backtest requires a minimum data length to simulate folds. The threshold is defined as `TOTAL_TEST_DAYS + 1` (currently 57 days). If a market has fewer than 57 days of distinct historical arrival dates, no honest backtest can be constructed. In this scenario, we ship the model but label the accuracy card as **"Backfill pending"**.
- **G3 (Model Performance Guarantee)**: A complex model (like GBM) must demonstrably beat a simpler baseline (like Naive Last-Week-Same-Day) on the backtest harness to be selected for production. If it fails, the system falls back to the simpler model.

## 3. Current Accuracy Card

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

## 4. Re-running the Backtest

Once data.gov.in access is restored and the historical backfill is complete, re-run the backtest harness to update the accuracy card with real out-of-sample metrics.

Run the following command from the project root:

```bash
python -m scripts.run_backtest
```

This will run the walk-forward evaluation across all active `(market, commodity)` pairs and output the aggregated metrics.
