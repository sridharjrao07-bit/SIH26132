# Backend tickets from frontend integration review (G5–G7, G10)

Originally drafted on `arena/01a0cef3-sih26132` (d01d1ba). Carried over here with **verification notes** appended after checking the code.
File each section verbatim with `gh issue create --body-file`. The agent sandbox token gets `Resource not accessible by integration` on createIssue.
Frontend-side gaps (G1, G2, G3, G8, G9) belong in the frontend repo tracker. G4 is a chart design rule.

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
**Verification note (frontend design review, 2026-09-24):** also add the two fields to `frontend_handoff/types/api-types.ts` (`Forecast`) and `frontend_handoff/mock/mock_api.py`. Separately, `ForecastMethod` in that types file (`ma | ols | feature_ols | gbm | holt_winters | blend | naive`) is missing values the engine actually writes: `moving_avg`, `auto`, `none` (`forecasting/engine.py`, migration 033).

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
**Verification note (frontend design review, 2026-09-24): the thresholds have already drifted.** `forecasting/engine.py` sets `MIN_OBSERVATIONS = 10` (n < 10 → `insufficient_data`; its docstring describes a `moving_avg` tier at n = 10–14). `docs/FORECASTING.md` says gate G1 = 14. The endpoint should **read the constants from the forecasting module** instead of restating 14 in a new place. Otherwise the UI would show "needs 14" while the engine forecasts at 10. Decide which number is canonical before this ships.

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
**Verification note (frontend design review, 2026-09-24): the premise needs revisiting. Events already reach the public today, unmoderated:**
1. `public.sale_window_headlines` (migration 029) has `GRANT SELECT ... TO anon, authenticated`. It projects `live_events_published`, which filters `review_status NOT IN ('rejected','legacy_reviewed')`, so **`pending` (unreviewed) LLM extractions with confidence ≥ 0.5 are included**.
2. `notifications/sale_window.py` (lines ~311–322) appends up to two of those headlines to the `reason` string of the **public** `GET /api/v1/sale-window/`, and therefore into SMS replies. That is the headline Sell/Hold/Wait widget.

So the moderation decision is not "before exposing events" but "events are already exposed, both in the anon grant and in the reason prose". Suggested minimum: have `sale_window_headlines` require `review_status = 'approved'` (or whatever the approved state in `review_state` is) until a publication policy exists. The frontend will render `reason` as-is and will not parse headlines out of it.

---

## Issue 4 — Contract drift: `better_market` shape and mock seed differ from the real API (G10)

`frontend_handoff/` (types + mock) is what the frontend will build against, but the key upsell field on the headline sale-window widget has a different shape in the real API:

| | Real API (`notifications/sale_window.py` ~L292–303) | `frontend_handoff/types/api-types.ts` + `mock_api.py` ~L295–303 |
|---|---|---|
| Keys | `market`, `modal_price`, `premium_rs`, `arrival_qty` | `market_id`, `market`, `price`, `delta` |
| Trigger | nearby modal ≥ **5%** above | best other market > **3%** above |

A frontend built on the mock would read `better_market.price` / `.delta` and get `undefined` against the real API, right in the demo's core flow.

Also: the mock market set is Lasalgaon, Pimpalgaon, Yeola, **Niphad, Malegaon**, while `db/migrations/002_seed.sql` has Lasalgaon APCM, Pimpalgaon Baswant APCM, Yeola, **Nashik, Manmad**. Mock names also drop the ` APCM` suffix.

**Change:** pick one `better_market` shape (suggest adding `market_id` and keeping the explicit names `modal_price` / `premium_rs`), then make the router, the TS type and the mock agree. Align the mock seed markets with `002_seed.sql`. Consider a contract test that diffs mock responses against the real response models.
