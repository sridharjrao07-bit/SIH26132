"""
forecasting/engine.py — Stage 4 pure-Python price forecasting engine.

Design rationale:
  Every line of the model is explainable to a judge; zero ML dependencies;
  lean image; no build risk on hackathon machines.

Models:
  MovingAverageModel   — last min(7, n) values held flat; σ = pstdev of window.
  LinearRegressionModel — OLS on day-indices x=0..n-1 (NOT calendar dates —
      market holiday gaps would skew the slope); fit on last min(30, n) obs.
  _blend_predictions   — 0.4·MA + 0.6·LR with conservative σ = max(σ_MA, σ_LR).

Tier logic by n = distinct observation days:
  n = 0          → skip (no rows written)
  n = 1–9        → 1 row, status='insufficient_data', predicted_price=None
  n = 10–14      → 7 rows, method='moving_avg', confidence='medium'
  n = 15–19      → 7 rows, method='blend',       confidence='medium'
  n ≥ 20         → 7 rows, method='blend',       confidence='high'

confidence='low' is reserved in the DB schema but never emitted: n<10 produces
no prediction rather than a low-confidence one (honesty over fabrication).

PostgREST 1,000-row cap avoided by:
  (a) paginated distinct-pairs query (PAGE_SIZE=500),
  (b) per-pair history fetch (bounded by HISTORY_DAYS × ~3 rows ≈ 180 rows).
"""
import structlog
import time
from datetime import date, timedelta
from statistics import pstdev
from typing import Dict, List, Optional, Tuple

from supabase import Client

logger = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

SOURCE_PRECEDENCE: Dict[str, int] = {
    "data_gov_in":  1,   # government API — primary provenance
    "agmarknet":    2,   # selenium scrape — secondary
    "manual":       3,   # manual entry
    "manual_seed":  4,   # seed data
}

MIN_OBSERVATIONS          = 10   # n <  10 → insufficient_data
BLEND_THRESHOLD           = 15   # n ≥  15 → blend (else MA-only)
HIGH_CONFIDENCE_THRESHOLD = 20   # n ≥  20 → high confidence
MA_WINDOW                 = 7    # look-back window for Moving Average
OLS_FIT_WINDOW            = 30   # max observations for OLS regression fit
HORIZON_DAYS              = 7    # calendar days ahead to predict
CONFIDENCE_Z              = 1.96 # 95% confidence interval multiplier


# ── Series builder ─────────────────────────────────────────────────────────────

def _source_rank(source: str) -> int:
    """Lower = higher priority. Unknown sources rank last."""
    return SOURCE_PRECEDENCE.get(source, 99)


def build_daily_series(rows: List[dict]) -> List[Tuple[date, float]]:
    """
    Collapse multiple price rows per (market, commodity, date) into one point.

    The prices table has a UNIQUE key on (market_id, commodity_id, arrival_date,
    variety, grade, source), so a single day may have 2–4 rows. Averaging them
    would produce a price that never existed at the mandi.

    Aggregation rules (applied in order):
    1. Group by arrival_date.
       PostgREST returns date columns as ISO-8601 strings — coerce to date.
    2. Source precedence: data_gov_in > agmarknet > manual > manual_seed.
       If any government-source row exists, it wins (provenance story for judges).
    3. Within the winning source, prefer variety='General'.
       A red-onion modal price ≠ the general onion price.
    4. Never average across varieties/sources.

    Returns: sorted [(date, modal_price), ...] ascending by date.
    """
    by_date: Dict[date, List[dict]] = {}
    for row in rows:
        raw = row["arrival_date"]
        # Defensive coerce: PostgREST returns ISO strings; direct date objects
        # also accepted (e.g., from tests that pass date objects).
        d = date.fromisoformat(raw) if isinstance(raw, str) else raw
        by_date.setdefault(d, []).append(row)

    series: List[Tuple[date, float]] = []
    for d, day_rows in by_date.items():
        # Pick best source
        best_rank   = min(_source_rank(r.get("source", "")) for r in day_rows)
        candidates  = [r for r in day_rows if _source_rank(r.get("source", "")) == best_rank]
        # Within best source, prefer variety='General'
        general     = [r for r in candidates if (r.get("variety") or "General") == "General"]
        chosen      = general[0] if general else candidates[0]
        series.append((d, float(chosen["modal_price"])))

    series.sort(key=lambda t: t[0])
    return series


# ── Models ─────────────────────────────────────────────────────────────────────

class MovingAverageModel:
    """
    Simple Moving Average — extrapolates a flat level (not a trend).

    Window: last min(MA_WINDOW, n) values.
    σ: population stdev of the window (pstdev).
       A single-observation window gives σ=0 (honest: no variance data).
    """

    def __init__(self, prices: List[float]):
        window      = prices[-MA_WINDOW:] if len(prices) >= MA_WINDOW else prices[:]
        self.level  = sum(window) / len(window)
        self.sigma  = pstdev(window) if len(window) > 1 else 0.0

    def predict(self, horizon: int = HORIZON_DAYS) -> List[Tuple[float, float, float]]:
        """Returns [(predicted, lower, upper), ...] for each day ahead."""
        margin  = CONFIDENCE_Z * self.sigma
        results = []
        for _ in range(horizon):
            lo = round(max(0.0, self.level - margin), 2)
            hi = round(self.level + margin, 2)
            results.append((round(self.level, 2), lo, hi))
        return results


class LinearRegressionModel:
    """
    Ordinary Least Squares on day-index x = 0 .. n−1.

    Calendar dates are NOT used as x — market holidays create irregular gaps
    that would artificially inflate the slope. Day indices keep it clean.

    Fit window: last min(OLS_FIT_WINDOW, n) observations.
    Projects from x = n .. n + horizon − 1.

    Formula (judge-friendly):
        slope     = (n·Σxy  −  Σx·Σy)  /  (n·Σx²  −  (Σx)²)
        intercept = (Σy  −  slope·Σx)  /  n
    σ: population stdev of residuals (actual − fitted).
    Perfect-line σ = 0 → zero-width bounds (tested).
    """

    def __init__(self, prices: List[float]):
        window  = prices[-OLS_FIT_WINDOW:] if len(prices) >= OLS_FIT_WINDOW else prices[:]
        n       = len(window)
        xs      = list(range(n))

        sum_x   = sum(xs)
        sum_y   = sum(window)
        sum_xy  = sum(x * y for x, y in zip(xs, window))
        sum_x2  = sum(x * x for x in xs)

        denom   = n * sum_x2 - sum_x ** 2
        if denom == 0:
            self.slope     = 0.0
            self.intercept = sum_y / n if n else 0.0
        else:
            self.slope     = (n * sum_xy  - sum_x * sum_y) / denom
            self.intercept = (sum_y - self.slope * sum_x) / n

        fitted    = [self.intercept + self.slope * x for x in xs]
        residuals = [a - f for a, f in zip(window, fitted)]
        self.sigma = pstdev(residuals) if len(residuals) > 1 else 0.0
        self._n    = n   # next x index for projection

    def predict(self, horizon: int = HORIZON_DAYS) -> List[Tuple[float, float, float]]:
        """Returns [(predicted, lower, upper), ...] for each day ahead."""
        margin  = CONFIDENCE_Z * self.sigma
        results = []
        for i in range(horizon):
            x  = self._n + i
            p  = self.intercept + self.slope * x
            lo = round(max(0.0, p - margin), 2)
            hi = round(p + margin, 2)
            results.append((round(p, 2), lo, hi))
        return results


def _blend_predictions(
    ma: MovingAverageModel,
    lr: LinearRegressionModel,
    horizon: int = HORIZON_DAYS,
) -> List[Tuple[float, float, float]]:
    """
    Blend MA and LR: 0.4·MA + 0.6·LR.

    Bounds use conservative σ = max(σ_MA, σ_LR) around the blended centre.
    MA is flat (same level every day); LR projects forward along the fitted slope.
    """
    sigma  = max(ma.sigma, lr.sigma)
    margin = CONFIDENCE_Z * sigma
    results = []
    for i in range(horizon):
        ma_p = ma.level                                    # flat extrapolation
        lr_p = lr.intercept + lr.slope * (lr._n + i)      # forward projection
        p    = round(0.4 * ma_p + 0.6 * lr_p, 2)
        lo   = round(max(0.0, p - margin), 2)
        hi   = round(p + margin, 2)
        results.append((p, lo, hi))
    return results


# ── Forecast row builder (module-level for unit-testability) ───────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    if lo > hi:
        logger.warning("reversed_sanity_band", lo=lo, hi=hi, action="skipping_clamp")
        return round(value, 2)
    return round(max(lo, min(hi, value)), 2)


def _make_forecast_rows(
    market_id:    str,
    commodity_id: str,
    series:       List[Tuple[date, float]],
    sanity:       Optional[Tuple[float, float]],
) -> List[dict]:
    """
    Build forecast dicts for one (market, commodity) pair.

    predicted_price is clamped to [sanity_min, sanity_max] when a band is given.
    lower_bound is always floored at 0 (prices cannot be negative).
    """
    n         = len(series)
    last_date = series[-1][0] if series else None

    # n = 0: skip entirely — no data at all
    if n == 0 or last_date is None:
        return []

    # n = 1–9: insufficient data — 1 honest row, no prediction fabricated
    if n < MIN_OBSERVATIONS:
        return [{
            "market_id":       market_id,
            "commodity_id":    commodity_id,
            "forecast_date":   (last_date + timedelta(days=1)).isoformat(),
            "predicted_price": None,
            "lower_bound":     None,
            "upper_bound":     None,
            "confidence":      None,
            "method":          "none",
            "observations":    n,
            "status":          "insufficient_data",
        }]

    prices = [p for _, p in series]

    # Choose tier
    if n >= BLEND_THRESHOLD:
        ma_model   = MovingAverageModel(prices)
        lr_model   = LinearRegressionModel(prices)
        preds      = _blend_predictions(ma_model, lr_model)
        method     = "blend"
        confidence = "high" if n >= HIGH_CONFIDENCE_THRESHOLD else "medium"
    else:
        # 10 ≤ n ≤ 14 — MA only
        ma_model   = MovingAverageModel(prices)
        preds      = ma_model.predict()
        method     = "moving_avg"
        confidence = "medium"

    rows = []
    for i, (predicted, lower, upper) in enumerate(preds):
        fdate = (last_date + timedelta(days=i + 1)).isoformat()
        if sanity is not None:
            margin = upper - predicted                      # keep the model's width
            predicted = _clamp(predicted, sanity[0], sanity[1])
            lower = max(0.0, predicted - margin)
            upper = predicted + margin
        lower = round(max(0.0, lower), 2)
        upper = round(upper, 2)
        rows.append({
            "market_id":       market_id,
            "commodity_id":    commodity_id,
            "forecast_date":   fdate,
            "predicted_price": predicted,
            "lower_bound":     lower,
            "upper_bound":     upper,
            "confidence":      confidence,
            "method":          method,
            "observations":    n,
            "status":          "ok",
        })
    return rows


# ── Engine ─────────────────────────────────────────────────────────────────────

class ForecastEngine:
    """
    Orchestrates 7-day price forecasting for all active (market, commodity) pairs.

    Run flow:
    1. Load commodity sanity bands (one query).
    2. Paginate distinct (market_id, commodity_id) pairs from prices table
       — avoids the PostgREST 1,000-row silent cap.
    3. Per pair: fetch 60-day history → build_daily_series → _make_forecast_rows.
    4. Upsert results; UNIQUE constraint makes re-runs idempotent.
    5. Return summary dict for the scheduler log.
    """

    PAGE_SIZE    = 500
    HISTORY_DAYS = 60

    def __init__(self, supabase: Client):
        self.supabase = supabase

    # ── Private helpers ────────────────────────────────────────────────────────

    def _load_sanity_bands(self) -> Dict[str, Tuple[float, float]]:
        resp = self.supabase.table("commodities").select("id, sanity_min, sanity_max").execute()
        return {
            row["id"]: (float(row["sanity_min"]), float(row["sanity_max"]))
            for row in resp.data
            if row.get("sanity_min") is not None and row.get("sanity_max") is not None
        }

    def _distinct_pairs(self) -> List[Tuple[str, str]]:
        """
        Paginated fetch of distinct (market_id, commodity_id) pairs.

        PostgREST caps any single response at 1,000 rows. At demo scale
        (5 mandis × 4 crops × 60 days × 2 varieties ≈ 2,400 rows) a single
        query silently drops pairs. PAGE_SIZE=500 + loop keeps each page safe.
        """
        pairs:  set = set()
        offset: int = 0
        cutoff = (date.today() - timedelta(days=self.HISTORY_DAYS)).isoformat()
        while True:
            resp = (
                self.supabase.table("prices")
                .select("market_id, commodity_id")
                .gte("arrival_date", cutoff)
                .range(offset, offset + self.PAGE_SIZE - 1)
                .execute()
            )
            if not resp.data:
                break
            for row in resp.data:
                pairs.add((row["market_id"], row["commodity_id"]))
            if len(resp.data) < self.PAGE_SIZE:
                break
            offset += self.PAGE_SIZE
        return list(pairs)

    def _fetch_history(self, market_id: str, commodity_id: str) -> List[dict]:
        cutoff = (date.today() - timedelta(days=self.HISTORY_DAYS)).isoformat()
        resp = (
            self.supabase.table("prices")
            .select("arrival_date, modal_price, source, variety")
            .eq("market_id",    market_id)
            .eq("commodity_id", commodity_id)
            .gte("arrival_date", cutoff)
            .order("arrival_date", desc=False)
            .execute()
        )
        return resp.data or []

    # ── Public entry point ─────────────────────────────────────────────────────

    def run(self) -> dict:
        """
        Run forecasting for all (market, commodity) pairs.
        Returns a summary dict with counts and wall-clock timing.
        """
        start = time.monotonic()
        log   = logger.bind(job="forecast_engine")
        log.info("forecast_run_started")

        sanity_bands = self._load_sanity_bands()
        pairs        = self._distinct_pairs()
        log.info("pairs_found", count=len(pairs))

        pairs_ok = pairs_insufficient = pairs_skipped = 0
        total_rows = 0

        for market_id, commodity_id in pairs:
            try:
                history = self._fetch_history(market_id, commodity_id)
                series  = build_daily_series(history)
                sanity  = sanity_bands.get(commodity_id)
                rows    = _make_forecast_rows(market_id, commodity_id, series, sanity)

                if not rows:
                    pairs_skipped += 1
                    continue

                self.supabase.table("forecasts").upsert(
                    rows,
                    on_conflict="market_id, commodity_id, forecast_date",
                ).execute()
                total_rows += len(rows)

                if rows[0]["status"] == "insufficient_data":
                    pairs_insufficient += 1
                else:
                    pairs_ok += 1

            except Exception as exc:
                log.error(
                    "pair_forecast_failed",
                    market_id=market_id,
                    commodity_id=commodity_id,
                    error=str(exc),
                )
                pairs_skipped += 1

        duration_ms = int((time.monotonic() - start) * 1000)
        summary = {
            "pairs_ok":           pairs_ok,
            "pairs_insufficient": pairs_insufficient,
            "pairs_skipped":      pairs_skipped,
            "rows_written":       total_rows,
            "duration_ms":        duration_ms,
        }
        log.info("forecast_run_complete", **summary)
        return summary
