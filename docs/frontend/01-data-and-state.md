# Frontend Design — Phase 1: Data Entities, Gaps & State Map

Status: **APPROVED** (with review corrections folded in).
Scope: price discovery + forecast + sale-window + alerts first; marketplace is a thin, form-driven second phase.
Existing assets: `frontend_handoff/` (mock API, hand-written TS types, API contract) — the FE starts from these.
Primary persona: farmer on a phone, 360px, Marathi-first (`lang=mr` default), low bandwidth, outdoor readability.

---

## 1. Core entities (price/prediction surface)

| Entity | Endpoint | Key fields | Frontend note |
|---|---|---|---|
| Commodity | `GET /api/v1/commodities/` | `id, name_en/mr/hi, category, standard_unit` | Static. Cache for the session. Display `name_{lang}` with `name_en` fallback. |
| Market | `GET /api/v1/markets/`, `/markets/nearby` | `id, name, district, taluka, lat, lng` | Always display `markets.name` from the API (e.g. `Lasalgaon APCM`). Never hardcode names. |
| PriceObservation | `/prices/latest` (7d, ≤500), `/prices/historical` (≤365d, ≤1000) | `arrival_date, min/max/modal_price, arrival_qty?, variety, grade, source` | Newest-first order, multiple rows per day. See G1. |
| Forecast | `GET /api/v1/forecasts?market_id&commodity_id&days≤7` | `forecast_date, predicted_price, lower_bound, upper_bound, confidence, method, observations, status, generated_at` | Returns `status='ok'` only. Horizon is at most 7 days. |
| ForecastSummary | `GET /api/v1/forecasts/summary` | Same shape as Forecast, day-1 row per pair | The cross-pair endpoint. Includes `insufficient_data`. Silently drops pairs with `generated_at` older than 48h. |
| SaleWindow | `GET /api/v1/sale-window/?commodity_id&market_id&lang` | `action, action_label, reason_code, latest_price, forecast_day1, forecast_trend, supply_pressure, arrivals_qty, better_market?` | The headline output. Returns 404 when there are no recent prices, so it needs a designed empty state. |
| UserProfile | `GET/PATCH /api/v1/me/` | `role, preferred_language, district, lat, lng` | Sets the default locale and home district. |
| Alert | `/api/v1/alerts/` CRUD | `commodity_id, market_id?, threshold_price, condition, expires_at` | Delivered by SMS only. The UI manages alerts; it does not deliver them. |

## 2. Gap tickets

Each row is meant to become one ticket. File paths point to the source of truth.

| ID | Owner | Finding | Files | Action |
|---|---|---|---|---|
| **G1** | FE | `/prices/historical` returns newest-first with several rows per day (variety × grade × source). | `app/routers/prices.py`, `forecasting/engine.py::build_daily_rows` | Collapse to one row per day **using the same rule as `build_daily_rows`**: lowest `SOURCE_PRECEDENCE` rank wins, prefer `variety == "General"`, then sort ascending. This keeps charts consistent with the data the forecaster trained on. |
| **G2** | FE | `arrival_qty` can be null. | `app/schemas/price.py` | Render a gap in the arrivals layer, never `0`. |
| **G3** | FE | History and forecasts need an exact market + commodity pair. | `app/routers/prices.py`, `app/routers/forecasts.py` | Build the board from `/forecasts/summary` + `/prices/latest`. Only the compare-markets chart fans out (≤5 calls, well within 120 req/min). |
| **G4** | FE | GBM auto-selection is disabled. `method` can be `moving_avg`, `blend`, `feature_ols`, `holt_winters`, `gbm`, `auto` or `none`. | `docs/FORECASTING.md`, `forecasting/engine.py` | Label every forecast with its actual `method`. Unknown values show the raw string. Never label a chart "GBM prediction". |
| **G5** | BE ✅ approved | `model_version` and `features_used` exist in the DB (migration 019) but `ForecastResponse` drops them. | `app/schemas/forecast.py` | Add both fields as `Optional`. |
| **G6** | BE ✅ approved (contract) | There's no public accuracy endpoint, and gate thresholds are hardcoded in several places. | new route (e.g. `app/routers/forecasts.py`) | See contract §3. **Evidence that we need a single source of truth:** `forecasting/engine.py` has `MIN_OBSERVATIONS = 10`, while `docs/FORECASTING.md` says G1 = 14. |
| **G7** | BE ⏸ deferred | The events feed for chart annotations is admin-only and needs a moderation/publication policy first. | `db/migrations/018_events.sql` | FE builds an empty `annotations` slot in the chart and feeds it nothing for now. |
| **G8** | FE | Error `detail` can be a string or an array. 404 means "not found or not yours". | `app/errors.py` | Use one `normalizeApiError()` for every request. |
| **G10** | BE | `better_market` shape differs: real API `{market, modal_price, premium_rs, arrival_qty}` (5% rule) vs handoff types/mock `{market_id, market, price, delta}` (3% rule). Mock seed markets also differ from `002_seed.sql`. | `notifications/sale_window.py`, `frontend_handoff/` | Backend aligns the shapes. Until then the FE adapter accepts both. |
| **G9** | FE | There's no pagination, search or realtime. Ingestion runs every 6h. | — | Refresh data at most every 5 minutes. Always show "as of". Use filtered views, no infinite scroll. |

## 3. Proposed G6 contract (honest degraded state)

```
GET /api/v1/forecasts/accuracy            (public, no auth)
{
  "status": "backfill_pending",            // backfill_pending | provisional | certified
  "thresholds": { "min_forecast_days": 10, "min_backtest_days": 57 },
  "horizon_days": 7,
  "metrics": null,                          // { mae, wmape, interval_coverage, nan_rate } once certified
  "model_mix": null,                        // { gbm: 0.x, feature_ols: 0.x, ... } once certified
  "as_of": "2026-09-24T06:00:00+05:30"
}
```

- The UI reads `thresholds` for all "Only N days of data, forecast needs M" copy. No thresholds are hardcoded in the frontend.
- The trust card is designed around `backfill_pending` as the **expected long-lived state**. The honest backtest is blocked on the data backfill, not on engineering time. Metrics are an enhancement.
- `/dashboard/api/forecast-stats` stays admin-only.

## 4. State map

```
SERVER STATE (query cache)
  ['commodities']                         cache: whole session
  ['markets', district]                   cache: whole session
  ['prices','latest',{m?,c?}]             refresh: 5 min
  ['prices','history',m,c,days]           refresh: 5 min
  ['forecasts',m,c]                       refresh: 5 min
  ['forecasts','summary']                 refresh: 5 min
  ['forecasts','accuracy']                refresh: 1 h   (G6)
  ['saleWindow',c,m?,lang]                refresh: 5 min; 404 → empty state
  ['me'], ['alerts']                      only after login

URL STATE        /c/:commodity/m/:market?range=90d&compare=m1,m2
GLOBAL CLIENT    locale (me.preferred_language → 'mr'), session + role, home district, display unit
DERIVED          DailyPricePoint, ChartSeries (actual ⊕ forecast), ForecastBand, BoardRow, PairHealth
```

### PairHealth: four inputs, one verdict

| Input | Source |
|---|---|
| Forecast rows present | `/forecasts` (ok-only) |
| Pair status | `/forecasts/summary` (`ok` / `insufficient_data` / absent) |
| Recent price exists | `/sale-window` 200 vs 404, or `/prices/latest` |
| Freshness | `generated_at` age. Older than 24h → `aging`. Pair missing from summary (48h cutoff) while prices exist → treat as `stale`, not "no forecast". |

Verdicts: `ok` · `aging` · `stale` · `insufficient_data` · `no_prices`. Each verdict has a single, specific message. No chart is ever left blank without an explanation.
