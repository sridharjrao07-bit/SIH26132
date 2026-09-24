# Backend tickets from frontend integration review (G5–G7)

File each section below as a GitHub issue on this repo (`gh issue create`).
Frontend-side gaps (G1, G2, G3, G8, G9) are handling patterns and belong in the
frontend repo's tracker, referencing these endpoints. G4 is a design rule for
the chart's method label, not a ticket.

---

## Issue 1 — Expose `model_version` and `features_used` in ForecastResponse (G5)

Migration `db/migrations/019_forecast_audit_cols.sql` adds `model_version TEXT`
and `features_used JSONB` to `forecasts`, but `ForecastResponse` in
`app/schemas/forecast.py` drops both, so the API cannot power any
"why this prediction" UI.

**Change:**
- Add `model_version: Optional[str] = None` and `features_used: Optional[dict] = None`
  to `ForecastResponse`.
- Ensure `app/routers/forecasts.py` selects/flattens the two columns in both
  `GET /forecasts` and `GET /forecasts/summary`.

Low risk: additive, nullable fields only. Frontend will label charts with the
actual `method`/`model_version` instead of implying GBM (not yet certified for
auto-selection per `docs/FORECASTING.md`).

---

## Issue 2 — Public forecast accuracy/thresholds endpoint (G6, extended with F3)

There is no public endpoint for forecast accuracy or data-sufficiency
thresholds; `/dashboard/api/forecast-stats` requires an admin session, and the
accuracy card (`docs/accuracy_card.md`) is honestly "backfill pending".

**Change:** add e.g. `GET /api/v1/forecasts/accuracy` (public, cached) returning:

```json
{
  "status": "backfill_pending",
  "thresholds": { "min_forecast_days": 10, "min_backtest_days": 57 },
  "progress": { "max_pair_days": 23, "required": 57 },
  "metrics": null,
  "updated_at": "..."
}
```

- `thresholds` becomes the single source of truth for UI copy like
  "Only 7 days of data, forecast needs 10" (do NOT hardcode values in the
  frontend). IMPORT the constants — `MIN_OBSERVATIONS` from
  `forecasting/engine.py` (ruling: code is authoritative; docs said 14 and
  were corrected — see docs/FORECASTING.md G1). Do not restate numbers.
- `progress` (added per frontend finding F3): the accuracy card shows a
  "Verified history: N / 57 days" row and needs a data source. Compute as
  `MAX(COUNT(DISTINCT arrival_date))` over (market, commodity) pairs — the
  same coverage query the ML workstream uses for gate classification.
- `metrics` stays `null` until an honest (G2-passing) walk-forward backtest
  certifies real numbers; then it carries MAE / winsorized MAPE / interval
  coverage per the accuracy card.
- Do NOT expose the admin dashboard stats route publicly.

---

## Issue 3 — Public read endpoint for published events (G7) — DEFERRED, decision needed

Chart annotations ("▼ supply glut, 12 Sep") need a public read of the `events`
table (LLM-extracted market events), which is currently admin-only.

**Blocked on policy, not schema:** LLM-extracted events need
moderation/publication semantics before public exposure (an incorrectly
extracted event is potentially market-moving misinformation). Requires:
- a `published`/review flag and who-approves workflow,
- read endpoint filtered to published events only,
- decision on retention/correction handling.

Frontend will design the annotation slot in the chart component but feed it
nothing until this lands. Do not implement without the moderation decision.

---

## Issue 5 — Forecast window off-by-one mixed two model runs (S1) — FIXED on branch arena/01a0cef3-sih26132

Found by frontend service-layer testing. The engine writes forecast rows for
`tomorrow … today+7` (`horizon_start = max(last_date, as_of)`, dates start at
`horizon_start + 1`), but:

- `GET /forecasts` used the window `today … today+days-1`, so day 7 was never
  returnable, and the `today` row could only come from an OLDER generation —
  the per-date dedupe then mixed two runs in one response (visible band jump
  at the join).
- `GET /forecasts/summary` had the same flaw: "earliest forecast_date among
  newest-generation winners" made a superseded run's today-row win as the
  representative day-1 row.

**Fix applied** (`app/routers/forecasts.py`): window is now
`today+1 … today+days` for `GET /forecasts`; summary excludes
`forecast_date <= today`. Mock mirrors the same window. Test fixtures updated
to date rows tomorrow (matching what the engine actually writes).

File this issue only for tracking/changelog; the code change is already on the
branch. Frontend keeps `selectLatestRun()` as defence-in-depth.
