# `legacy/` — retired SIH26132 feature code

This directory holds the code from the **previous problem statement, SIH26132**
(market linkage and price discovery). The project has pivoted to **SIH26033**
(farmer-to-consumer disintermediation), implemented as **DirectLink** in
`direct/`.

**Nothing here is deleted.** Everything was moved with `git mv`, so history is
preserved and any file can be restored with a single command.

## What is here

| Path | Contents |
|---|---|
| `routers/` | `admin`, `alerts`, `buyers`, `dashboard`, `forecasts`, `grievances`, `intelligence`, `logistics`, `matching`, `offers`, `payments`, `sms`, `storage` |
| `schemas/` | `forecast.py` |
| `notifications/` | `inbound_verifier.py` |
| `services/` | — |
| `demo/` | `forecast_card.py`, `journey_rehearsal.py`, `live_smoke.py`, `reconcile.py`, `seed_demo.py` |
| `tests/` | the test files covering the above |

## What is *not* here, and why

These stayed in the active tree because the new work depends on them:

| Kept | Reason |
|---|---|
| `app/routers/{markets,commodities,prices,lots,profile}.py` | retained spine; `direct_*` tables FK into `commodities`, `lots`, `user_profiles` |
| `app/schemas/marketplace.py` | `lots.py` and `profile.py` import from it |
| `notifications/{alert_checker,prices,sale_window}.py` | `profile.py` and the scheduler import them |
| `notifications/sms_gateway.py` | `alert_checker` calls it at runtime |
| `app/services/{marketplace,jobs}.py` | `lots.py` and startup import them |
| `ingestion/data_gov_in.py`, `ingestion/retail_loader.py` | the two real price anchors |

The dependency direction was checked, not assumed: every foreign key runs
**new → old**, and no table created by migrations 001–037 references anything
created by 038–040. The old schema is inert with respect to the new one.

## Restoring a file

```bash
git mv legacy/routers/forecasts.py app/routers/forecasts.py
```

Then re-add it to `app/routers/__init__.py` and `app/main.py`, and move its
tests back from `legacy/tests/`. Three guards will need updating in step:

1. `tests/test_api_docs_sync.py` — `docs/API.md` is generated from the live
   routes; re-run `PYTHONPATH=. python scripts/generate_api_docs.py`.
2. `tests/test_api_docs_sync.py::test_api_contract_paths` — the contract at
   `frontend_handoff/API_CONTRACT.md` must document every served endpoint.
3. `tests/test_openapi_contract.py::test_openapi_exposes_core_paths` — add the
   restored path back to `required`.

`legacy/` is excluded from linting (see `pyproject.toml`). If you restore code
into the active tree, lint it.

## Database

The corresponding **tables were not dropped** — see the "Supabase: what to keep,
what to add, what to retire" section of `docs/HANDOFF_NEXT_STEPS.md`. Dropping
is irreversible and, worse, not persistent: `scripts/apply_migrations.py`
replays migrations 001–037 on any fresh database, so a dropped table simply
reappears. Migrations 038–040 are additive and never touched the old schema.
