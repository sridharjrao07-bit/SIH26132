# Krishi Bazaar Forecasting Engine Upgrade – Changes Log

This document summarizes all the changes, new files, and code modifications made during the Phase 1 through Phase 6 upgrade of the Krishi Bazaar forecasting engine.

---

## 1. Phase 1: Backtest Harness
**Goal:** Establish an honest walk-forward evaluation harness.

- **`forecasting/evaluation.py`**: Added robust metric calculations including MAE, Winsorized MAPE, Directional Accuracy, and Interval Coverage. 
- **`forecasting/backtest.py`**: Created the core walk-forward cross-validation engine.
- **`app/routers/admin.py`**: Added the `POST /admin/forecast/backtest` endpoint.

**Code Snippet (`forecasting/backtest.py`):**
```python
def run_backtest(
    supabase: Client,
    pairs: List[Tuple[str, str]],
    history_days: int = 365,
    model_names: List[str] = ["ma", "ols"],
    horizon: int = 7,
    folds: int = 5,
    fold_spacing: int = 7,
) -> BacktestReport:
    """Executes a walk-forward backtest for multiple models over a given history."""
    # ... logic for splitting data into walk-forward folds and calculating metrics
```

---

## 2. Phase 2: Data Foundation
**Goal:** Prepare the data layer for features (weather, backfilling).

- **`db/migrations/017_weather_daily.sql`**: Created the schema for storing Open-Meteo weather data.
- **`ingestion/data_gov_in.py`**: Modified the scraper to support `date` filtering.
- **`scripts/backfill_history.py` & `scripts/backfill_weather.py`**: Wrote CLI scripts to backfill data for training ML models.
- **`app/config.py`**: Added settings for `OPEN_METEO_URL` and `EVENT_JOB_ENABLED`.

**Code Snippet (`db/migrations/017_weather_daily.sql`):**
```sql
CREATE TABLE public.weather_daily (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    district text NOT NULL,
    date date NOT NULL,
    rain_mm numeric(6,2) NOT NULL DEFAULT 0,
    temp_min_c numeric(5,2),
    temp_max_c numeric(5,2),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(district, date)
);
```

---

## 3. Phase 3: Feature Models
**Goal:** Enhance simple statistical models into feature-rich models.

- **`forecasting/features.py`**: Implemented `build_feature_matrix` to generate `lag_1`, `lag_7`, `lag_14`, `momentum_14d`, `arrivals_7d_avg`, `rain_7d_cum_mm`, and `event_pressure`.
- **`forecasting/models.py`**: Added `FeatureOLSModel` (multivariate regression) and `HoltWintersModel` (exponential smoothing).
- **`forecasting/engine.py`**: Wired the engine to support `feature_ols` and supply the feature matrix.

**Code Snippet (`forecasting/models.py`):**
```python
class FeatureOLSModel:
    def __init__(self, prices: List[float], features: List[List[float]] = None):
        # Multivariate OLS using the generated feature matrix
        # with fallback to univariate OLS if the matrix is insufficient.
```

---

## 4. Phase 4: Event Intelligence Layer
**Goal:** Extract structured events (floods, strikes, bans) from unstructured news/government text using LLMs.

- **`db/migrations/018_events.sql`**: Created the `events` table to store extracted intelligence.
- **`events/extractor.py`**: Built a Pydantic + Gemini `google-genai` integration to strictly extract typed events without hallucinating numbers.
- **`events/sources.py`**: Wrote scrapers for PIB, Newsfeed, and state bulletins.
- **`events/runner.py`**: Added `run_events_job()` to orchestrate the LLM extraction and deduplication.
- **`app/jobs.py`**: Added the hourly cron task for the event layer.
- **`notifications/sale_window.py`**: Injected active event headlines into the SMS recommendations.

**Code Snippet (`events/extractor.py`):**
```python
class LLMExtractor(BaseExtractor):
    def extract(self, text: str, source: str) -> List[ExtractedEvent]:
        # Uses Gemini 2.5 Flash to extract events matching the ExtractedEvent schema.
        # CRITICAL: The LLM NEVER predicts numbers. It only extracts events.
        prompt = "Extract agriculture market events..."
        response = self.client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=prompt,
            config=GenerateContentConfig(response_mime_type="application/json")
        )
```

---

## 5. Phase 5: Global GBM (LightGBM)
**Goal:** Introduce Gradient Boosting for robust, non-linear, cross-market forecasting.

- **`forecasting/gbm.py`**: Built `GlobalGBM` which dynamically imports `lightgbm`. It aggregates cross-market data, trains a global booster on the feature matrix, and makes predictions.
- **`forecasting/engine.py`**: Added `gbm` to the model registry inside a `try/except` block (so missing `lightgbm` degrades gracefully).

**Code Snippet (`forecasting/gbm.py`):**
```python
class GlobalGBM:
    def __init__(self, all_market_data: List[Tuple[List[float], List[List[float]]]]):
        import lightgbm as lgb
        # Flattens all historical data across all markets into a single global dataset
        self.model = lgb.train(params, train_set)
```

---

## 6. Phase 6: Audit & Documentation
**Goal:** Add inference auditability, write docs, and finalize system integrity.

- **`db/migrations/019_forecast_audit_cols.sql`**: Added `model_version` and `features_used` (JSONB) to the `forecasts` table.
- **`forecasting/engine.py`**: Modified `_make_forecast_rows` to attach audit metadata.
- **`docs/FORECASTING.md`**: Wrote extensive documentation explaining the architecture, the "LLM does not predict numbers" rule, and the models.
- **`demo/forecast_card.py`**: Wrote a script to print the Honest Accuracy Card and stop/report when there is insufficient backtest data (<57 days).
- **`requirements-dev.txt`**: Upgraded `respx` to `0.22.0` to fix tests failing due to an `httpx` `0.28.x` incompatibility.
- **`tests/test_rls_live.py`**: Added live checks for `events` and `weather_daily` boundaries.

**Code Snippet (`forecasting/engine.py`):**
```python
# Audit columns populated on every prediction
features_used = []
if method == "feature_ols":
    features_used = [names[c] for c in getattr(model_inst, "keep_cols", [])]
elif method == "gbm":
    features_used = [f["feature"] for f in getattr(model_cls, "get_feature_importances", lambda: [])()]

rows.append({
    # ... basic forecast details
    "status":          "ok",
    "model_version":   "1.0",
    "features_used":   features_used,
    "generated_at":    datetime.now(timezone.utc).isoformat(),
})
```
