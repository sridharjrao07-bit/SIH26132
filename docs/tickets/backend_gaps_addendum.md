# Addendum to backend_gaps_G5-G7.md (frontend design review)

This is a separate file so that `backend_gaps_G5-G7.md` stays byte-identical to
`arena/01a0cef3-sih26132` @ 6ae008b and the two branches merge without conflict.

## Issue 4 — Contract drift: `better_market` shape and mock seed (G10) — FIXED on `arena/01a0cef3-sih26132` (c23f30a)

The real API returns `{market, modal_price, premium_rs, arrival_qty}` (5% rule). The handoff types/mock returned `{market_id, market, price, delta}` (3% rule), and the mock markets (Niphad, Malegaon) differed from `002_seed.sql` (Nashik APCM, Manmad APCM). The types, mock and names are now aligned. Track only, or skip filing.

## Small leftovers — CLOSED on `arena/01a0cef3-sih26132` (e94809f)

Resolution note: item 2 was corrected during the fix. `auto` is a `model_id` registry key, never a `method` value. `naive` exists only in `forecasting/backtest.py` and was removed from the type. The final `ForecastMethod` is `none | moving_avg | blend | ma | ols | feature_ols | holt_winters | gbm`.


1. `frontend_handoff/README.md` ~L81–82 still names IDs `…104` / `…105` as `NIPHAD` / `MALEGAON`. The mock now serves them as **Nashik APCM** / **Manmad APCM**. Rename the constants.
2. `frontend_handoff/types/api-types.ts` L50: `ForecastMethod` = `ma | ols | feature_ols | gbm | holt_winters | blend | naive` is missing values the engine writes: **`moving_avg`**, **`none`** (and `auto` from the model registry). Add them, and keep the `| string` escape on `Forecast.method`.
3. Same file L48: `ForecastConfidence` includes `"low"`, which the engine never emits (F5). Keep it, since the schema allows it, but add a `/** dormant */` comment so QA doesn't try to trigger it.
