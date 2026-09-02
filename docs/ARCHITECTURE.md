# Architecture

Layered FastAPI service. Runtime configuration is **12-factor env vars** (`app/config.py` / `.env.example`), not a `config/` tree.

```
HTTP  app/routers/*          FastAPI routes, auth deps, HTTPException
  │
  ├─ schemas  app/schemas/*  request/response models (Pydantic)
  │
  ├─ domain
  │    app/marketplace.py    lots, offers, payments, ledger, reliability
  │    app/matching_engine.py  local-first farmer ↔ verified buyer score
  │    notifications/        sale-window, SMS, alerts
  │    forecasting/          7-day mandi forecast
  │    ingestion/            data.gov.in (+ optional Agmarknet)
  │
  └─ infra
       app/deps.py           anon + service-role Supabase clients
       app/auth.py           HS256 verify; role from user_profiles
       app/errors.py         PostgREST → boring HTTP
       app/jobs.py           APScheduler (single worker)
       db/migrations/        Postgres / RLS (apply in Supabase SQL editor)
```

`app/` is the application package (equivalent to `src/`). Domain packages stay at the repo root so ingest/forecast/SMS jobs can run without the HTTP stack.

## Auth path (do not invert)

1. Client sends `Authorization: Bearer <jwt>`.
2. `decode_access_token` checks HS256, `aud=authenticated`, `exp`, `sub`.
3. Handlers that need a user use `get_supabase_as_user` → **service-role** client after that verify.
4. Every query is scoped by `user_id` (or FPO id). RLS is not the only control here.

Minted tokens must never be passed to PostgREST (`PGRST301` on hosted JWT signing keys).

## Errors

`APIError` from PostgREST is mapped in `app/errors.py`:

| PG / PostgREST | HTTP |
|---|---|
| `PGRST301` / JWT | 401 |
| `22P02` | 422 |
| `23503` | 400 |
| `23505` | 409 |
| `23514` | 422 |
| `42501` | 403 |
| other | 503 |

Unhandled exceptions return `{"detail":"Internal server error"}`. Logs are JSON via structlog.

## Processes

- **API**: `uvicorn app.main:app --workers 1` (scheduler is in-process).
- **Jobs**: ingest, forecast, alert SMS, expire offers, mark stale forecasts.
- **Frontend**: separate origin; CORS via `CORS_ORIGIN`.
