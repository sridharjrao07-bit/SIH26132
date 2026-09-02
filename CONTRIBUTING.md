# Contributing (backend)

This repository is the **FastAPI + Supabase API** for SIH26132. The farmer/buyer UI is a **separate frontend repo**. Do not add HTML farmer screens or an `ui` router here.

## Branching

- Do not commit to `main`.
- Open a branch from the current integration branch, push that branch, open a pull request.
- Conventional Commits on every commit:

  `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`, `sec:`

  Example: `fix: map PostgREST 22P02 to HTTP 422`

## Python

**3.14 only.** Do not introduce 3.12 pins or Windows MSVC workarounds.

```bat
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```

Never commit `.env`.

## Checks before a PR

```bat
set RUN_SCHEDULER=0
set RATE_LIMIT_ENABLED=0
ruff check app ingestion forecasting notifications tests demo scripts
pytest -q
```

Optional: `pre-commit install` then `pre-commit run --all-files`.

## Architecture rules (do not break)

1. FastAPI verifies JWTs. **Never** attach a minted HS256 token to PostgREST (`client.postgrest.auth`). Hosted signing keys reject it (`PGRST301` → 500). Authenticated handlers use the service-role client and **must** filter by `user_id`.
2. Role lives in `user_profiles`, not in the JWT.
3. Secrets only via environment variables (see `.env.example`).
4. Public errors are boring JSON (`detail`). No stack traces, no SQL, no PostgREST codes.
5. New tables/RPCs go in the next `db/migrations/NNN_*.sql` file. Document skip-vs-apply in `docs/SQL_APPLY.md`. Do not re-run a file that already succeeded on a live project.
6. Business logic stays out of routers when it is more than a thin CRUD: matching, sale-window, ingest, forecast engines already live in `app/matching_engine.py`, `app/marketplace.py`, `ingestion/`, `forecasting/`, `notifications/`.

## Docs that must stay in sync

| Change | Update |
|---|---|
| New/changed HTTP route | `docs/API.md` (and OpenAPI via FastAPI) |
| New env var | `.env.example` and README env table |
| New SQL | `docs/SQL_APPLY.md` |
| Demo / judge path | `docs/DEMO.md` |

## Review bar

A PR is not ready if tests were not run, if a JWT is pasted in the description, or if it adds farmer UI to this repo.
