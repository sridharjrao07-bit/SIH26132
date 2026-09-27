# Scripts

Operator helpers. Not imported by the API.

## Before the demo

| Script | Purpose |
|---|---|
| `rehearse_demo.py` | **Run this first.** Runs the audit, the five-act demo, the migration linter, the test suite and ruff, then prints one PASS/FAIL line per step. `--fast` skips the suite. ~7 s. |
| `verify_live_stack.py` | The credential-gated half: migrations, idempotency, seeded rows, the write-path RPCs, the live retail adapter. Needs `SUPABASE_DB_URL`, `DATA_GOV_IN_API_KEY`, `DCA_RETAIL_RESOURCE_ID`. See `docs/AGENT_LOOP_PROMPT.md`. |
| `audit_numbers.py` | Re-derives every headline number from `data/` without importing the engine, and requires the two to reconcile. Also rejects implausible price anchors. `--data-dir` to point it at a copy. |
| `check_migrations.py` | Static SQL linter over `db/migrations/`. Numbering, FK forward-references, `ON CONFLICT` targets vs cumulative unique constraints, `p_*` param parity vs `app/routers/direct.py`, re-runnable seeds. |

`audit_numbers.py` checks the *derivations*, not the anchors: the engine calibrates to whatever (farm, retail) pair it is given, so a plausible-but-wrong price still reconciles. It catches impossible anchors only. `tests/test_retail_anchor.py` covers the plausibility band separately.

## Database

| Script | Purpose |
|---|---|
| `apply_migrations.py` | Applies `db/migrations/` in order. `--dry-run` to list. Needs `SUPABASE_DB_URL`. |
| `test_db.py` | Live PostgREST read of `public.markets`. Prints no secrets. |
| `exercise_rpc.py` | Exercises the direct RPCs (`direct_plan_commit`, `direct_impact`, `direct_order_trace`) against a live DB. |
| `seed_csv_reference_data.py`, `seed_demo_history.py`, `ingest_csv.py` | Reference and demo data loading. |
| `backfill_history.py`, `backfill_weather.py`, `generate_historical_prices.py` | Historical data loading. |
| `refresh_seed_dates.py` | Re-dates seed fixtures. |

## Data and docs

| Script | Purpose |
|---|---|
| `generate_api_docs.py` | Regenerates `docs/API.md` from the FastAPI app. Needs `PYTHONPATH=.`. |
| `generate_summary.py` | Markdown project summary for a handout. |
| `run_smoke_backtest.py`, `demo_flow.py` | Backtest and API-sequence smoke runs. |
| `scrape_agmarknet_direct.py` | Mandi price scraper. |

## Demo scripts

Live in `demo/`:

- `direct_channel_demo.py` — the five-act narrative. No database, no network; reads both price anchors from `data/` (retail goes live when `DATA_GOV_IN_API_KEY` is set).
- `mint_admin_token.py` — mints a service-role JWT for the admin endpoints.

Scripts in `scripts/demo/` (`quick_forecast_onion.py`, `run_forecast.py`, `test_sale_window.py`) are forecast experiments from the original SIH26132 concept, kept for reference.
