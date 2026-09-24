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

## Issue 2 — Public forecast accuracy/thresholds endpoint (G6)

There is no public endpoint for forecast accuracy or data-sufficiency
thresholds; `/dashboard/api/forecast-stats` requires an admin session, and the
accuracy card (`docs/accuracy_card.md`) is honestly "backfill pending".

**Change:** add e.g. `GET /api/v1/forecasts/accuracy` (public, cached) returning:

```json
{
  "status": "backfill_pending",
  "thresholds": { "min_forecast_days": 14, "min_backtest_days": 57 },
  "metrics": null,
  "updated_at": "..."
}
```

- `thresholds` becomes the single source of truth for UI copy like
  "Only 9 days of data, forecast needs 14" (do NOT hardcode 14/57 in the
  frontend; gate values are under active change in the forecasting workstream).
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
