# Architecture

Layered FastAPI service. Runtime configuration is **12-factor env vars** (`app/config.py` / `.env.example`), not a `config/` tree.

```
HTTP  app/routers/*          FastAPI routes, auth deps, HTTPException
  │
  ├─ schemas  app/schemas/*  request/response models (Pydantic)
  │
  ├─ domain
  │    app/services/marketplace.py lots, offers, payments, ledger, reliability
  │    app/matching_engine.py      local-first farmer ↔ verified buyer score
  │    notifications/              sale-window, SMS, alerts
  │    forecasting/                7-day mandi forecast
  │    ingestion/                  data.gov.in (+ optional Agmarknet)
  │
  └─ infra
       app/deps.py           anon + service-role Supabase clients
       app/auth.py           HS256 verify; role from user_profiles
       app/errors.py         PostgREST → boring HTTP
       app/startup_checks.py APScheduler (single worker)
       db/migrations/        Postgres / RLS (apply in Supabase SQL editor)
```

`app/` is the application package (equivalent to `src/`). Domain packages stay at the repo root so ingest/forecast/SMS jobs can run without the HTTP stack.

## Security Model (4-Layer)

Please see [`SECURITY_MODEL.md`](SECURITY_MODEL.md) for the exhaustive design. Key points:
1. **Authentication**: `decode_access_token` checks HS256, `aud=authenticated`, `exp`, `sub`, and `iss`.
2. **Per-Request User Client**: `get_supabase_as_user` creates an un-cached, user-scoped client per request.
3. **RLS Enforcement**: The user client passes the JWT to Supabase. Postgres RLS acts as a hard boundary.
4. **Belt-and-Braces RPCs**: State mutations are routed through `SECURITY DEFINER` RPCs to enforce ownership and valid state transitions before applying updates.

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
