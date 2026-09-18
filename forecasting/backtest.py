"""
forecasting/backtest.py — Walk-forward backtest harness.

Protocol (verbatim, stored in every BacktestReport.protocol):
    "walk-forward, horizon=7, 8 folds of 7 days over the last 56 days,
    expanding train window (everything before each fold start), one winner
    row per day by source precedence"
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

import structlog
import collections
from app.utils.tz import get_ist_today
logger = structlog.get_logger()

# Verbatim protocol string — referenced in tests and FORECASTING.md
BACKTEST_PROTOCOL = (
    "walk-forward, horizon=7, 8 folds of 7 days over the last 56 days, "
    "expanding train window (everything before each fold start), one winner "
    "row per day by source precedence. NOTE: Uses retrospective event filtering "
    "based on current review state."
)

HORIZON = 7
N_FOLDS = 8
FOLD_SIZE = 7  # days per fold
TOTAL_TEST_DAYS = N_FOLDS * FOLD_SIZE  # 56 days


# ---------------------------------------------------------------------------
# Protocol for forecast models
# ---------------------------------------------------------------------------

class ForecastModel(Protocol):
    @property
    def name(self) -> str: ...

    def fit(
        self,
        series: List[Tuple[date, float]],
        features: Optional[Any] = None,
        pair_id: Optional[Tuple[str, str]] = None,
    ) -> None: ...

    def predict(self, horizon: int = HORIZON, forecast_origin: Optional[date] = None) -> List[Tuple[float, float, float]]: ...


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------

class BaselineMA:
    name = "ma"
    def fit(self, series: List[Tuple[date, float]], features=None, pair_id=None) -> None:
        from forecasting.engine import MovingAverageModel
        prices = [p for _, p in series]
        self._model = MovingAverageModel(prices)
        self.sigma = self._model.sigma
    def predict(self, horizon: int = HORIZON, forecast_origin: Optional[date] = None) -> List[Tuple[float, float, float]]:
        from forecasting.engine import apply_postprocessing
        raw = self._model.predict(horizon, forecast_origin)
        return apply_postprocessing(raw, self.sigma, sanity=None)

class BaselineOLS:
    name = "ols"
    def fit(self, series: List[Tuple[date, float]], features=None, pair_id=None) -> None:
        from forecasting.engine import LinearRegressionModel
        prices = [p for _, p in series]
        self._model = LinearRegressionModel(prices)
        self.sigma = self._model.sigma
    def predict(self, horizon: int = HORIZON, forecast_origin: Optional[date] = None) -> List[Tuple[float, float, float]]:
        from forecasting.engine import apply_postprocessing
        raw = self._model.predict(horizon, forecast_origin)
        return apply_postprocessing(raw, self.sigma, sanity=None)

class NaiveLastWeekSameDay:
    name = "naive"
    def fit(self, series: List[Tuple[date, float]], features=None, pair_id=None) -> None:
        self._lookup: Dict[date, float] = {d: p for d, p in series}
        self._last_date = series[-1][0] if series else None
        self.sigma = 0.0
    def predict(self, horizon: int = HORIZON, forecast_origin: Optional[date] = None) -> List[Tuple[float, float, float]]:
        from forecasting.engine import apply_postprocessing
        if not self._last_date:
            return [(float("nan"), float("nan"), float("nan"))] * horizon
            
        origin = forecast_origin or self._last_date
        raw = []
        for i in range(1, horizon + 1):
            target = origin + timedelta(days=i)
            lag = target - timedelta(days=7)
            raw.append(self._lookup.get(lag, float("nan")))
            
        processed = apply_postprocessing(raw, self.sigma, sanity=None)
        final_processed = []
        for r, (p, lo, hi) in zip(raw, processed):
            if math.isnan(r):
                final_processed.append((float('nan'), float('nan'), float('nan')))
            else:
                # Naive does not support intervals, explicitly return NaN bounds
                final_processed.append((p, float('nan'), float('nan')))
        return final_processed

class FeatureOLSAdapter:
    name = "feature_ols"
    def fit(self, series: List[Tuple[date, float]], features=None, pair_id=None) -> None:
        from forecasting.models import FeatureOLSModel
        prices = [p for _, p in series]
        if features is None:
            raise ValueError("FeatureOLS requires features")
        self._model = FeatureOLSModel(prices, features)
        
    def predict(self, horizon: int = HORIZON, forecast_origin: Optional[date] = None) -> List[Tuple[float, float, float]]:
        from forecasting.engine import apply_postprocessing
        raw = self._model.predict(horizon, forecast_origin)
        return apply_postprocessing(raw, self._model.sigma, sanity=None)

class HoltWintersAdapter:
    name = "holt_winters"
    def fit(self, series: List[Tuple[date, float]], features=None, pair_id=None) -> None:
        from forecasting.models import HoltWintersModel
        prices = [p for _, p in series]
        self._model = HoltWintersModel(prices)
        
    def predict(self, horizon: int = HORIZON, forecast_origin: Optional[date] = None) -> List[Tuple[float, float, float]]:
        from forecasting.engine import apply_postprocessing
        raw = self._model.predict(horizon, forecast_origin)
        return apply_postprocessing(raw, self._model.sigma, sanity=None)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

MODEL_REGISTRY: Dict[str, Any] = {
    "ma":           BaselineMA,
    "ols":          BaselineOLS,
    "naive":        NaiveLastWeekSameDay,
    "feature_ols":  FeatureOLSAdapter,
    "holt_winters": HoltWintersAdapter,
    "gbm":          None, # GBM is handled specially via train_global_gbm
}

def get_local_model(name: str) -> ForecastModel:
    if name == "gbm":
        raise ValueError("GBM must be trained globally")
    cls = MODEL_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown model name {name!r}")
    return cls()

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FoldStats:
    requested_calendar_folds: int
    executed_folds: int
    skipped_insufficient_training_folds: int
    folds_with_observed_test_data: int
    folds_considered_for_directional_accuracy: int

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class ModelResult:
    model:               str
    status:              str
    reason:              Optional[str]
    mae:                 Optional[float]
    mape_winsorized:     Optional[float]
    directional_hits:    Optional[int]
    directional_folds:   Optional[int]
    interval_coverage:   Optional[float]
    directional_accuracy:Optional[float] = None
    da_evaluated_samples: List[str] = field(default_factory=list)
    n_attempted_predictions: int = 0
    n_valid_predictions: int = 0
    n_missing_history: int = 0
    n_execution_failure: int = 0
    n_invalid_prediction: int = 0
    n_unscored_target: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class PairResult:
    market_id:    str
    commodity_id: str
    n_obs:        int
    fold_stats:   FoldStats
    models:       List[ModelResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "market_id":    self.market_id,
            "commodity_id": self.commodity_id,
            "n_obs":        self.n_obs,
            "fold_stats":   self.fold_stats.to_dict(),
            "models":       [m.to_dict() for m in self.models],
        }

@dataclass
class BacktestReport:
    generated_at:   str
    protocol:       str
    horizon:        int
    history_days:   int
    evaluation_scope: str
    promotion_eligible: bool
    per_pair:       List[PairResult]
    aggregate:      Dict[str, Any]

    def to_json(self) -> dict:
        return {
            "generated_at":       self.generated_at,
            "protocol":           self.protocol,
            "horizon":            self.horizon,
            "history_days":       self.history_days,
            "evaluation_scope":   self.evaluation_scope,
            "promotion_eligible": self.promotion_eligible,
            "per_pair":           [p.to_dict() for p in self.per_pair],
            "aggregate":          self.aggregate,
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

def run_backtest(
    supabase,
    pairs: List[Tuple[str, str]],
    history_days: int = 365,
    model_names: Optional[List[str]] = None,
    evaluation_scope: str = "official",
) -> BacktestReport:
    """
    Run walk-forward backtest over calendar folds, with global training for GBM.
    """
    from forecasting.engine import build_daily_series
    from forecasting.features import build_feature_matrix
    
    if model_names is None:
        model_names = ["ma", "ols", "naive", "feature_ols", "holt_winters", "gbm"]
        
    for name in model_names:
        if name not in MODEL_REGISTRY:
            raise ValueError(f"Unknown model name {name!r}")
            
    if "naive" not in model_names:
        model_names.append("naive")
        
    cutoff = (get_ist_today() - timedelta(days=history_days)).isoformat()
    
    # 1. Fetch data globally
    raw_history = {}
    weather = []
    events = []
    try:
        weather = supabase.table("weather_daily").select("*").gte("observation_date", cutoff).execute().data or []
        from events.loader import load_published_events
        events = load_published_events(supabase, event_date_from=get_ist_today() - timedelta(days=history_days))
        
        raw_history = collections.defaultdict(list)
        offset = 0
        PAGE_SIZE = 1000
        while True:
            resp = (
                supabase.table("prices")
                .select("market_id, commodity_id, arrival_date, modal_price, arrival_qty, source, variety")
                .gte("arrival_date", cutoff)
                .order("arrival_date", desc=False)
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            if not resp.data:
                break
            for row in resp.data:
                if (row["market_id"], row["commodity_id"]) in pairs:
                    raw_history[(row["market_id"], row["commodity_id"])].append(row)
            if len(resp.data) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    except Exception as e:
        logger.error("backtest_data_fetch_failed", error=str(e))
        return BacktestReport(datetime.now(timezone.utc).isoformat(), BACKTEST_PROTOCOL, HORIZON, history_days, evaluation_scope, False, [], {})

    # Pre-build full series and features for all pairs
    full_series = {}
    full_features = {}
    for (m, c), rows in raw_history.items():
        s = build_daily_series(rows)
        if len(s) == 0:
            continue
            
        from forecasting.engine import build_daily_rows
        winning_rows = [row for _, row in build_daily_rows(rows)]
            
        feat = build_feature_matrix(
            series=winning_rows,
            weather=[w for w in weather if w.get("market_id") == m],
            events=events,
            district_prices=[],
            target_commodity_id=c,
            strict_pit=True
        )
        full_series[(m, c)] = s
        full_features[(m, c)] = feat

    # 2. Determine Calendar Folds
    # Find max date across all series
    max_d = None
    for s in full_series.values():
        if s:
            md = s[-1][0]
            if max_d is None or md > max_d:
                max_d = md
                
    if not max_d:
        return BacktestReport(datetime.now(timezone.utc).isoformat(), BACKTEST_PROTOCOL, HORIZON, history_days, evaluation_scope, False, [], {})
        
    first_fold_start = max_d - timedelta(days=TOTAL_TEST_DAYS) + timedelta(days=1)
    
    # 3. Setup accumulator pool
    pool = {
        name: {
            "actuals": [], "preds": [], "lowers": [], "uppers": [], "last_train_prices": [], 
            "n_missing_history": 0, "n_execution_failure": 0, "n_invalid_prediction": 0, "n_unscored_target": 0, "n_valid_predictions": 0,
            "name": name, "hits": 0, "considered": 0, "incomplete_folds": 0
        } for name in model_names
    }
    
    pair_accumulators = {
        (m, c): {
            name: {"actuals": [], "preds": [], "lowers": [], "uppers": [], "folds": [], 
                   "n_missing_history": 0, "n_execution_failure": 0, "n_invalid_prediction": 0, "n_unscored_target": 0, "n_valid_predictions": 0,
                   "incomplete_folds": 0}
            for name in model_names
        } for (m, c) in full_series.keys()
    }
    
    pair_fold_stats = {
        (m, c): {
            "requested_calendar_folds": N_FOLDS,
            "executed_folds": 0,
            "skipped_insufficient_training_folds": 0,
            "folds_with_observed_test_data": 0,
            "folds_considered_for_directional_accuracy": 0,
        }
        for (m, c) in full_series.keys()
    }

    # 4. Iterate over Folds
    for fold_idx in range(N_FOLDS):
        fold_start = first_fold_start + timedelta(days=fold_idx * FOLD_SIZE)
        fold_end = fold_start + timedelta(days=FOLD_SIZE - 1)
        
        # Train global GBM for this fold
        global_gbm = None
        if "gbm" in model_names:
            # Build training history strictly before fold_start
            train_history = {}
            for (m, c), rows in raw_history.items():
                train_history[(m, c)] = []
                for r in rows:
                    d_str = r["arrival_date"]
                    d = date.fromisoformat(d_str) if isinstance(d_str, str) else d_str
                    if d < fold_start:
                        train_history[(m, c)].append(r)
            try:
                from forecasting.gbm import train_global_gbm
                global_gbm = train_global_gbm(
                    pairs_history=train_history,
                    weather=[w for w in weather if date.fromisoformat(w["observation_date"][:10]) < fold_start],
                    events=[e for e in events if date.fromisoformat(e["event_date"][:10]) < fold_start],
                    district_prices=[],
                    strict_pit=True
                )
            except Exception as e:
                logger.warning("fold_global_gbm_failed", fold=fold_idx, error=str(e))
                global_gbm = None
                
        # Iterate over pairs for local training & prediction
        for (m, c), s in full_series.items():
            train_s = [(d, p) for (d, p) in s if d < fold_start]
            test_s = [(d, p) for (d, p) in s if fold_start <= d <= fold_end]
            
            if not train_s:
                pair_fold_stats[(m, c)]["skipped_insufficient_training_folds"] += 1
                continue
            
            pair_fold_stats[(m, c)]["executed_folds"] += 1
            if test_s:
                pair_fold_stats[(m, c)]["folds_with_observed_test_data"] += 1
                
            last_train_price = train_s[-1][1]
            train_f = [f for (d, p), f in zip(s, full_features[(m, c)]) if d < fold_start]
            
            for name in model_names:
                preds = []
                try:
                    horizon_start = fold_start - timedelta(days=1)
                    if name == "gbm":
                        if global_gbm is None:
                            raise ValueError("GBM model failed to train")
                        model = global_gbm
                        model.fit(train_s, features=train_f, pair_id=(m, c))
                        raw_preds = model.predict(horizon=FOLD_SIZE, forecast_origin=horizon_start)
                        from forecasting.engine import apply_postprocessing
                        preds = apply_postprocessing(raw_preds, model.sigma, sanity=None)
                    else:
                        model = get_local_model(name)
                        model.fit(train_s, features=train_f, pair_id=(m, c))
                        preds = model.predict(horizon=FOLD_SIZE, forecast_origin=horizon_start)
                except Exception as e:
                    logger.warning("fold_model_failed", model=name, fold=fold_idx, pair=(m, c), error=str(e))
                    for i in range(FOLD_SIZE):
                        pred_date = fold_start + timedelta(days=i)
                        actual_match = [p for d, p in test_s if d == pred_date]
                        if not actual_match:
                            pair_accumulators[(m, c)][name]["n_unscored_target"] += 1
                        else:
                            pair_accumulators[(m, c)][name]["actuals"].append(actual_match[0])
                            pair_accumulators[(m, c)][name]["preds"].append(float("nan"))
                            pair_accumulators[(m, c)][name]["lowers"].append(float("nan"))
                            pair_accumulators[(m, c)][name]["uppers"].append(float("nan"))
                            pair_accumulators[(m, c)][name]["n_execution_failure"] += 1
                    pair_accumulators[(m, c)][name]["folds"].append({
                        "last_train_price": last_train_price,
                        "actuals": [a for _, a in test_s],
                        "preds": [float("nan")] * len(test_s),
                        "target_dates": [d.isoformat() if isinstance(d, date) else d for d, _ in test_s]
                    })
                    continue
                    
                fold_actuals = []
                fold_preds = []
                for i in range(FOLD_SIZE):
                    pred_date = fold_start + timedelta(days=i)
                    actual_match = [p for d, p in test_s if d == pred_date]
                    if not actual_match:
                        pair_accumulators[(m, c)][name]["n_unscored_target"] += 1
                        continue # Date not present in test_s, don't score
                        
                    actual = actual_match[0]
                    if i < len(preds):
                        p, lo, hi = preds[i]
                        p_f = _safe_float(p)
                        lo_f = _safe_float(lo)
                        hi_f = _safe_float(hi)
                    else:
                        p_f = lo_f = hi_f = float("nan")
                        
                    is_nan = p_f is None or not math.isfinite(p_f)
                    
                    pair_accumulators[(m, c)][name]["actuals"].append(actual)
                    pair_accumulators[(m, c)][name]["preds"].append(p_f if not is_nan else float("nan"))
                    pair_accumulators[(m, c)][name]["lowers"].append(lo_f if lo_f is not None else float("nan"))
                    pair_accumulators[(m, c)][name]["uppers"].append(hi_f if hi_f is not None else float("nan"))
                    
                    if is_nan:
                        if name == "naive":
                            pair_accumulators[(m, c)][name]["n_missing_history"] += 1
                        else:
                            pair_accumulators[(m, c)][name]["n_invalid_prediction"] += 1
                    else:
                        pair_accumulators[(m, c)][name]["n_valid_predictions"] += 1
                        
                    fold_actuals.append(actual)
                    fold_preds.append(p_f if not is_nan else float("nan"))
                    
                if fold_actuals:
                    pair_accumulators[(m, c)][name]["folds"].append({
                        "last_train_price": last_train_price,
                        "actuals": fold_actuals,
                        "preds": fold_preds,
                        "target_dates": [d.isoformat() if isinstance(d, date) else d for d, _ in test_s]
                    })

    # 5. Build Result objects
    per_pair = []
    for (m, c), acc in pair_accumulators.items():
        n_obs = len(full_series[(m, c)])
        pair_models = []
        for name in model_names:
            actuals = acc[name]["actuals"]
            if not actuals:
                continue
                
            preds = acc[name]["preds"]
            mae_val = mae(actuals, preds)
            mape_val = mape_winsorized(actuals, preds)
            valid_intervals = sum(
                1 for h, l, a in zip(acc[name]["uppers"], acc[name]["lowers"], actuals)
                if h is not None and l is not None and a is not None and math.isfinite(h) and math.isfinite(l) and math.isfinite(a)
            )
            if valid_intervals == 0:
                cov = float('nan')
            else:
                cov = interval_coverage(acc[name]["uppers"], acc[name]["lowers"], actuals)
            
            # Directional accuracy uses all paired instances (weekly means over actual matching dates)
            folds = acc[name]["folds"]
            total_hits, total_considered, incomplete_folds, evaluated_fold_indices = directional_accuracy(
                [f["last_train_price"] for f in folds],
                [f["preds"] for f in folds],
                [f["actuals"] for f in folds]
            )
            
            da_evaluated_samples = []
            for idx in evaluated_fold_indices:
                f = folds[idx]
                for d in f["target_dates"]:
                    da_evaluated_samples.append(f"{m}|{c}|{idx}|{d}")
            
            total_valid = acc[name]["n_valid_predictions"]
            
            if total_valid > 0:
                status = "blocked" if incomplete_folds > 0 else "ok"
                reason = "incomplete_fold_predictions" if incomplete_folds > 0 else None
            else:
                status = "blocked"
                if acc[name]["n_execution_failure"] > 0:
                    reason = "execution_failure"
                elif acc[name]["n_missing_history"] > 0:
                    reason = "missing_history"
                elif acc[name]["n_invalid_prediction"] > 0:
                    reason = "invalid_prediction"
                else:
                    reason = "insufficient_training_or_calibration_history"
                    
            mr = ModelResult(
                model=name,
                status=status,
                reason=reason,
                mae=None if math.isnan(mae_val) or total_valid == 0 else round(mae_val, 4),
                mape_winsorized=None if math.isnan(mape_val) or total_valid == 0 else round(mape_val, 4),
                directional_hits=total_hits if total_valid > 0 else None,
                directional_folds=total_considered if total_valid > 0 else None,
                interval_coverage=None if math.isnan(cov) or total_valid == 0 else round(cov, 4),
                directional_accuracy=round((total_hits / total_considered * 100.0), 2) if total_considered > 0 and total_valid > 0 else None,
                n_attempted_predictions=total_valid + acc[name]["n_missing_history"] + acc[name]["n_execution_failure"] + acc[name]["n_invalid_prediction"],
                n_valid_predictions=total_valid,
                n_missing_history=acc[name]["n_missing_history"],
                n_execution_failure=acc[name]["n_execution_failure"],
                n_invalid_prediction=acc[name]["n_invalid_prediction"],
                n_unscored_target=acc[name]["n_unscored_target"],
                da_evaluated_samples=da_evaluated_samples,
            )
            pair_models.append(mr)
            
            # Pool to global
            pool[name]["actuals"].extend(actuals)
            pool[name]["preds"].extend(preds)
            pool[name]["lowers"].extend(acc[name]["lowers"])
            pool[name]["uppers"].extend(acc[name]["uppers"])
            pool[name]["n_valid_predictions"] += acc[name]["n_valid_predictions"]
            pool[name]["n_missing_history"] += acc[name]["n_missing_history"]
            pool[name]["n_execution_failure"] += acc[name]["n_execution_failure"]
            pool[name]["n_invalid_prediction"] += acc[name]["n_invalid_prediction"]
            pool[name]["n_unscored_target"] += acc[name]["n_unscored_target"]
            pool[name]["hits"] += total_hits
            pool[name]["considered"] += total_considered
            pool[name]["incomplete_folds"] += incomplete_folds
            
        per_pair.append(PairResult(
            market_id=m, 
            commodity_id=c, 
            n_obs=n_obs, 
            fold_stats=FoldStats(**pair_fold_stats[(m, c)]),
            models=pair_models
        ))

    # 6. Aggregate
    aggregate = {}
    for name in model_names:
        p = pool[name]
        actuals = p["actuals"]
        if not actuals:
            continue
        agg_mae = mae(actuals, p["preds"])
        agg_mape = mape_winsorized(actuals, p["preds"])
        valid_intervals = sum(
            1 for h, l, a in zip(p["uppers"], p["lowers"], actuals)
            if h is not None and l is not None and a is not None and math.isfinite(h) and math.isfinite(l) and math.isfinite(a)
        )
        if valid_intervals == 0:
            agg_cov = float('nan')
        else:
            agg_cov = interval_coverage(p["uppers"], p["lowers"], actuals)
        valid = p["n_valid_predictions"]
        total = valid + p["n_missing_history"] + p["n_execution_failure"] + p["n_invalid_prediction"]
        agg_da = (p["hits"] / p["considered"] * 100.0) if p["considered"] > 0 else 0.0
        if valid > 0:
            status = "blocked" if p["incomplete_folds"] > 0 else "ok"
            reason = "incomplete_fold_predictions" if p["incomplete_folds"] > 0 else None
        else:
            status = "blocked"
            if p["n_execution_failure"] > 0:
                reason = "execution_failure"
            elif p["n_missing_history"] > 0:
                reason = "missing_history"
            elif p["n_invalid_prediction"] > 0:
                reason = "invalid_prediction"
            else:
                reason = "insufficient_training_or_calibration_history"

        aggregate[name] = {
            "status": status,
            "reason": reason,
            "mae": None if math.isnan(agg_mae) or valid == 0 else round(agg_mae, 4),
            "mape_winsorized": None if math.isnan(agg_mape) or valid == 0 else round(agg_mape, 4),
            "interval_coverage": None if math.isnan(agg_cov) or valid == 0 else round(agg_cov, 4),
            "directional_accuracy": round(agg_da, 2) if valid > 0 else None,
            "n_attempted_predictions": total,
            "n_valid_predictions": valid,
            "n_missing_history": p["n_missing_history"],
            "n_execution_failure": p["n_execution_failure"],
            "n_invalid_prediction": p["n_invalid_prediction"],
            "n_unscored_target": p["n_unscored_target"]
        }
        if name == "gbm" and global_gbm is not None:
            aggregate[name]["feature_importances"] = global_gbm.get_feature_importances()

    report = BacktestReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        protocol=BACKTEST_PROTOCOL,
        horizon=HORIZON,
        history_days=history_days,
        evaluation_scope=evaluation_scope,
        promotion_eligible=False,
        per_pair=per_pair,
        aggregate=aggregate,
    )

    if evaluation_scope == "official":
        from forecasting.gates import evaluate_gates
        candidate = "gbm" if "gbm" in aggregate else "feature_ols"
        if candidate in aggregate:
            gate_res = evaluate_gates(report, candidate, incumbent_name="blend")
            report.promotion_eligible = gate_res.all_pass

    return report
