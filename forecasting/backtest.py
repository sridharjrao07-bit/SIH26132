"""
forecasting/backtest.py — Walk-forward backtest harness.

Protocol (verbatim, stored in every BacktestReport.protocol):
    "walk-forward, horizon=7, 8 folds of 7 days over the last 56 days,
    expanding train window (everything before each fold start), one winner
    row per day by source precedence"

Design constraints
------------------
* Pure Python — no numpy, no ML deps.
* Any model that raises mid-run produces a NaN row; the run never aborts.
* Models implement ForecastModel protocol: name, fit(series), predict(horizon).
* NaiveLastWeekSameDay is always included as a benchmark.
* Aggregate metrics pool ALL (pred, actual) pairs across ALL pairs for each
  model (not macro-average of pair-level metrics) so small-n pairs don't
  over-influence the aggregate.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol, Tuple

from forecasting.evaluation import (
    mae,
    mape_winsorized,
    directional_accuracy,
    interval_coverage,
)

# Verbatim protocol string — referenced in tests and FORECASTING.md
BACKTEST_PROTOCOL = (
    "walk-forward, horizon=7, 8 folds of 7 days over the last 56 days, "
    "expanding train window (everything before each fold start), one winner "
    "row per day by source precedence"
)

HORIZON = 7
N_FOLDS = 8
FOLD_SIZE = 7  # days per fold
TOTAL_TEST_DAYS = N_FOLDS * FOLD_SIZE  # 56 days


# ---------------------------------------------------------------------------
# Protocol for forecast models (structural subtyping — no base class needed)
# ---------------------------------------------------------------------------

class ForecastModel(Protocol):
    """
    Minimal interface for plugging models into the backtest harness.

    ``fit`` receives the training series as [(date, price), ...] sorted
    ascending.  ``predict`` returns (price, lower, upper) for each horizon day.
    Models may raise any exception; the harness catches it and records NaN.
    """

    @property
    def name(self) -> str: ...

    def fit(
        self,
        series: List[Tuple[date, float]],
        features: Optional[Any] = None,
    ) -> None: ...

    def predict(self, horizon: int = HORIZON) -> List[Tuple[float, float, float]]: ...


# ---------------------------------------------------------------------------
# Adapters wrapping existing engine models
# ---------------------------------------------------------------------------

class BaselineMA:
    """Adapter: wraps MovingAverageModel from forecasting.engine."""

    name = "ma"

    def fit(self, series: List[Tuple[date, float]], features=None) -> None:
        from forecasting.engine import MovingAverageModel
        prices = [p for _, p in series]
        self._model = MovingAverageModel(prices)

    def predict(self, horizon: int = HORIZON) -> List[Tuple[float, float, float]]:
        return self._model.predict(horizon)


class BaselineOLS:
    """Adapter: wraps LinearRegressionModel from forecasting.engine."""

    name = "ols"

    def fit(self, series: List[Tuple[date, float]], features=None) -> None:
        from forecasting.engine import LinearRegressionModel
        prices = [p for _, p in series]
        self._model = LinearRegressionModel(prices)

    def predict(self, horizon: int = HORIZON) -> List[Tuple[float, float, float]]:
        return self._model.predict(horizon)


class NaiveLastWeekSameDay:
    """
    Benchmark: predict price[t] = price[t-7] (same weekday last week).

    No bounds — lower = upper = predicted.  This is intentionally dumb; any
    real model should beat it on a directional-accuracy basis.
    """

    name = "naive"

    def fit(self, series: List[Tuple[date, float]], features=None) -> None:
        # Store the full date→price map so we can look up t-7
        self._lookup: Dict[date, float] = {d: p for d, p in series}
        self._last_date = series[-1][0] if series else None

    def predict(self, horizon: int = HORIZON) -> List[Tuple[float, float, float]]:
        if not self._last_date:
            return [(float("nan"), float("nan"), float("nan"))] * horizon
        results = []
        for i in range(1, horizon + 1):
            target = self._last_date + timedelta(days=i)
            lag = target - timedelta(days=7)
            p = self._lookup.get(lag, float("nan"))
            results.append((p, p, p))
        return results


class FeatureOLSAdapter:
    name = "feature_ols"
    
    def fit(self, series: List[Tuple[date, float]], features=None) -> None:
        from forecasting.models import FeatureOLSModel
        prices = [p for _, p in series]
        if features is None:
            raise ValueError("FeatureOLS requires features")
        self._model = FeatureOLSModel(prices, features)
        
    def predict(self, horizon: int = HORIZON) -> List[Tuple[float, float, float]]:
        return self._model.predict(horizon)

class HoltWintersAdapter:
    name = "holt_winters"
    
    def fit(self, series: List[Tuple[date, float]], features=None) -> None:
        from forecasting.models import HoltWintersModel
        prices = [p for _, p in series]
        self._model = HoltWintersModel(prices)
        
    def predict(self, horizon: int = HORIZON) -> List[Tuple[float, float, float]]:
        return self._model.predict(horizon)


class GlobalGBMAdapter:
    name = "gbm"
    
    def fit(self, series: List[Tuple[date, float]], features=None) -> None:
        from forecasting.gbm import GlobalGBM
        # Instantiating the global model will trigger global training if not done
        self._model = GlobalGBM()
        self._model.fit(series, features)
        
    def predict(self, horizon: int = HORIZON) -> List[Tuple[float, float, float]]:
        return self._model.predict(horizon)


# ---------------------------------------------------------------------------
# Registry (extended in engine.py as models are added)
# ---------------------------------------------------------------------------

MODEL_REGISTRY: Dict[str, Any] = {
    "ma":    BaselineMA,
    "ols":   BaselineOLS,
    "naive": NaiveLastWeekSameDay,
    "feature_ols": FeatureOLSAdapter,
    "holt_winters": HoltWintersAdapter,
    "gbm": GlobalGBMAdapter,
}


def get_model(name: str) -> ForecastModel:
    """Return a fresh model instance by name, or raise ValueError."""
    cls = MODEL_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown model name {name!r}. "
            f"Available: {sorted(MODEL_REGISTRY.keys())}"
        )
    return cls()


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ModelResult:
    """Per-model metrics for one (market, commodity) pair."""
    model:               str
    mae:                 Optional[float]
    mape_winsorized:     Optional[float]
    directional_hits:    Optional[int]
    directional_folds:   Optional[int]
    interval_coverage:   Optional[float]
    nan_rate:            float = 0.0    # fraction of predictions that were NaN

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PairResult:
    """Backtest results for one (market_id, commodity_id) pair."""
    market_id:    str
    commodity_id: str
    n_obs:        int
    models:       List[ModelResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "market_id":    self.market_id,
            "commodity_id": self.commodity_id,
            "n_obs":        self.n_obs,
            "models":       [m.to_dict() for m in self.models],
        }


@dataclass
class BacktestReport:
    """Top-level backtest result."""
    generated_at:   str
    protocol:       str
    horizon:        int
    history_days:   int
    per_pair:       List[PairResult]
    aggregate:      Dict[str, Any]   # model → aggregate metrics across all pairs

    def to_json(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "protocol":     self.protocol,
            "horizon":      self.horizon,
            "history_days": self.history_days,
            "per_pair":     [p.to_dict() for p in self.per_pair],
            "aggregate":    self.aggregate,
        }


# ---------------------------------------------------------------------------
# Walk-forward harness internals
# ---------------------------------------------------------------------------

def _safe_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _run_one_pair(
    series: List[Tuple[date, float]],
    model_names: List[str],
    features: Optional[List[Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Run walk-forward backtest for a single pair.

    Returns:
        {model_name: {"actuals": [...], "preds": [...],
                      "lowers": [...], "uppers": [...],
                      "last_train_prices": [...], "nan_count": int}}
    """
    n = len(series)
    if n < TOTAL_TEST_DAYS + 1:
        return {}  # not enough data for even 1 fold

    # Index of first fold start: n - TOTAL_TEST_DAYS
    first_fold_start = n - TOTAL_TEST_DAYS

    # Accumulate across folds for each model
    results: Dict[str, Dict] = {
        name: {
            "actuals":            [],
            "preds":              [],
            "lowers":             [],
            "uppers":             [],
            "last_train_prices":  [],
            "nan_count":          0,
        }
        for name in model_names
    }

    for fold_idx in range(N_FOLDS):
        fold_start = first_fold_start + fold_idx * FOLD_SIZE
        train_series = series[:fold_start]   # expanding window
        fold_series  = series[fold_start: fold_start + FOLD_SIZE]
        train_features = features[:fold_start] if features else None

        if not train_series or not fold_series:
            continue

        last_train_price = train_series[-1][1]

        for name in model_names:
            try:
                model = get_model(name)
                model.fit(train_series, features=train_features)
                raw_preds = model.predict(horizon=len(fold_series))
            except Exception as e:
                # Model failed this fold — record NaN for every day of the fold
                import traceback
                print(f"Model {name} failed fold: {e}")
                traceback.print_exc()
                for _, actual in fold_series:
                    results[name]["actuals"].append(actual)
                    results[name]["preds"].append(float("nan"))
                    results[name]["lowers"].append(float("nan"))
                    results[name]["uppers"].append(float("nan"))
                    results[name]["last_train_prices"].append(last_train_price)
                    results[name]["nan_count"] += 1
                continue

            for i, (_, actual) in enumerate(fold_series):
                if i < len(raw_preds):
                    pred, lo, hi = raw_preds[i]
                    pred_f = _safe_float(pred)
                    lo_f   = _safe_float(lo)
                    hi_f   = _safe_float(hi)
                else:
                    pred_f = lo_f = hi_f = float("nan")

                is_nan = pred_f is None or not math.isfinite(pred_f)
                results[name]["actuals"].append(actual)
                results[name]["preds"].append(pred_f if not is_nan else float("nan"))
                results[name]["lowers"].append(lo_f if lo_f is not None else float("nan"))
                results[name]["uppers"].append(hi_f if hi_f is not None else float("nan"))
                results[name]["last_train_prices"].append(last_train_price)
                if is_nan:
                    results[name]["nan_count"] += 1

    return results


def _metrics_from_fold_data(
    data: Dict[str, Any],
) -> ModelResult:
    """Compute ModelResult from accumulated fold data for one model."""
    actuals = data["actuals"]
    preds   = data["preds"]
    lowers  = data["lowers"]
    uppers  = data["uppers"]
    last_prices = data["last_train_prices"]
    nan_count   = data["nan_count"]

    total = len(preds)
    nan_rate = nan_count / total if total > 0 else 0.0

    mae_val  = mae(actuals, preds)
    mape_val = mape_winsorized(actuals, preds)

    # Directional accuracy: day-1 of each fold (index 0, FOLD_SIZE, ...)
    day1_actuals = actuals[::FOLD_SIZE]
    day1_preds   = preds[::FOLD_SIZE]
    day1_last    = last_prices[::FOLD_SIZE]

    total_hits = 0
    total_considered = 0
    for anchor, fold_preds_1, fold_actual_1 in zip(day1_last, day1_preds, day1_actuals):
        h, c = directional_accuracy(anchor, [fold_preds_1], [fold_actual_1])
        total_hits      += h
        total_considered += c

    cov = interval_coverage(uppers, lowers, actuals)

    return ModelResult(
        model=data.get("name", "unknown"),
        mae=None if math.isnan(mae_val) else round(mae_val, 4),
        mape_winsorized=None if math.isnan(mape_val) else round(mape_val, 4),
        directional_hits=total_hits,
        directional_folds=total_considered,
        interval_coverage=None if math.isnan(cov) else round(cov, 4),
        nan_rate=round(nan_rate, 4),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_backtest(
    supabase,
    pairs: List[Tuple[str, str]],
    history_days: int = 365,
    model_names: Optional[List[str]] = None,
) -> BacktestReport:
    """
    Run the walk-forward backtest for the given (market_id, commodity_id) pairs.

    Parameters
    ----------
    supabase : Supabase Client or FakeSupabase
        Used only to fetch price history (read-only).
    pairs : list of (market_id, commodity_id)
    history_days : int
        How far back to fetch price history (training + test window).
    model_names : list of str, optional
        Model names from MODEL_REGISTRY to evaluate.  Defaults to
        ["ma", "ols", "naive"].

    Returns
    -------
    BacktestReport
    """
    from forecasting.engine import build_daily_series

    if model_names is None:
        model_names = ["ma", "ols", "naive"]

    # Validate model names up front — unknown name → ValueError (caller → 422)
    for name in model_names:
        if name not in MODEL_REGISTRY:
            raise ValueError(
                f"Unknown model name {name!r}. "
                f"Available: {sorted(MODEL_REGISTRY.keys())}"
            )

    # Ensure naive is always present as benchmark
    if "naive" not in model_names:
        model_names = list(model_names) + ["naive"]

    cutoff = (date.today() - timedelta(days=history_days)).isoformat()

    # Pool: model → list of (actual, pred, lo, hi) for aggregate metrics
    pool: Dict[str, Dict[str, Any]] = {
        name: {
            "actuals": [], "preds": [], "lowers": [], "uppers": [],
            "nan_count": 0, "name": name,
        }
        for name in model_names
    }

    per_pair: List[PairResult] = []

    for market_id, commodity_id in pairs:
        # Fetch full history for this pair
        try:
            resp = (
                supabase.table("prices")
                .select("arrival_date, modal_price, arrival_qty, source, variety")
                .eq("market_id", market_id)
                .eq("commodity_id", commodity_id)
                .gte("arrival_date", cutoff)
                .order("arrival_date", desc=False)
                .execute()
            )
            raw_rows = resp.data or []
        except Exception:
            continue

        series = build_daily_series(raw_rows)
        n_obs  = len(series)

        if n_obs < TOTAL_TEST_DAYS + 1:
            per_pair.append(PairResult(
                market_id=market_id,
                commodity_id=commodity_id,
                n_obs=n_obs,
                models=[],
            ))
            continue
            
        from forecasting.features import build_feature_matrix
        
        # We need the winner row's arrival_qty for each date in series.
        # Use the same precedence rules implicitly by letting the engine map them, or just do it inline here since engine returns (date, price).
        # Actually, build_daily_series already does this. The easiest way to get the winner's arrival_qty is to use the exact same logic.
        from forecasting.engine import _source_rank
        by_date: Dict[date, List[dict]] = {}
        for row in raw_rows:
            d_raw = row["arrival_date"]
            d = date.fromisoformat(d_raw) if isinstance(d_raw, str) else d_raw
            by_date.setdefault(d, []).append(row)
            
        winner_qty = {}
        for d, day_rows in by_date.items():
            best_rank = min(_source_rank(r.get("source", "")) for r in day_rows)
            candidates = [r for r in day_rows if _source_rank(r.get("source", "")) == best_rank]
            general = [r for r in candidates if (r.get("variety") or "General") == "General"]
            chosen = general[0] if general else candidates[0]
            winner_qty[d] = chosen.get("arrival_qty", 0.0)

        history_dicts = [{"arrival_date": d.isoformat(), "modal_price": p, "arrival_qty": winner_qty.get(d, 0.0)} for d, p in series]
        
        # We also need to fetch weather and events for backtest, ideally passing them to build_feature_matrix.
        # But this is just backtest, let's pass them as empty for now or fetch them.
        # To make it accurate, we should fetch them. Let's do it outside the loop once.
        features = build_feature_matrix(history_dicts, target_commodity_id=commodity_id)

        fold_data = _run_one_pair(series, model_names, features=features)
        if not fold_data:
            continue

        # Attach model name to fold_data (needed by _metrics_from_fold_data)
        for name in model_names:
            if name in fold_data:
                fold_data[name]["name"] = name

        pair_models: List[ModelResult] = []
        for name in model_names:
            if name not in fold_data:
                continue
            mr = _metrics_from_fold_data(fold_data[name])
            pair_models.append(mr)
            # Accumulate into global pool
            pool[name]["actuals"].extend(fold_data[name]["actuals"])
            pool[name]["preds"].extend(fold_data[name]["preds"])
            pool[name]["lowers"].extend(fold_data[name]["lowers"])
            pool[name]["uppers"].extend(fold_data[name]["uppers"])
            pool[name]["nan_count"] += fold_data[name]["nan_count"]

        per_pair.append(PairResult(
            market_id=market_id,
            commodity_id=commodity_id,
            n_obs=n_obs,
            models=pair_models,
        ))

    # Build aggregate (pooled across all pairs)
    aggregate: Dict[str, Any] = {}
    for name in model_names:
        p = pool[name]
        agg_mae  = mae(p["actuals"], p["preds"])
        agg_mape = mape_winsorized(p["actuals"], p["preds"])
        agg_cov  = interval_coverage(p["uppers"], p["lowers"], p["actuals"])
        total    = len(p["preds"])
        aggregate[name] = {
            "mae":              None if math.isnan(agg_mae) else round(agg_mae, 4),
            "mape_winsorized":  None if math.isnan(agg_mape) else round(agg_mape, 4),
            "interval_coverage": None if math.isnan(agg_cov) else round(agg_cov, 4),
            "nan_rate":         round(p["nan_count"] / total, 4) if total else None,
            "n_predictions":    total,
        }
        
        if name == "gbm":
            from forecasting.gbm import GlobalGBM
            aggregate[name]["feature_importances"] = GlobalGBM.get_feature_importances()

    return BacktestReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        protocol=BACKTEST_PROTOCOL,
        horizon=HORIZON,
        history_days=history_days,
        per_pair=per_pair,
        aggregate=aggregate,
    )
