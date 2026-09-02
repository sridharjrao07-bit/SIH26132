# Krishi Bazaar — SIH26132 (backend)

Market linkage and price discovery API for farmers (Government of Maharashtra / MSInS).

This repository is the **FastAPI + Supabase backend**. The farmer/buyer web or mobile UI lives in a separate frontend repo. Contract: [`docs/API.md`](docs/API.md).

## Problem → API

| SIH expected | This API |
|---|---|
| Aggregate mandi prices, arrivals, demand, logistics | `GET /prices/*` ingest from data.gov.in; `GET /buyers/`; `GET /logistics/` |
| Localised price trends + sale-window | `GET /sale-window/?lang=mr` → **Sell Now / Hold / Wait** |
| Match farmers/FPOs to verified buyers | `GET /lots/{id}/matches` and `/advice` (local-first score) |
| Lots, grading, digital offers, payments | `/lots/` `/offers/` `/payments/` |
| Logistics + disputes | `/logistics/bookings` `/grievances/` |
| Transparent record | `GET /lots/{id}/ledger` |

Demo seed: 5 Nashik APMCs × Onion, Tomato, Soybean, Maize. Expand via [`docs/ONBOARDING.md`](docs/ONBOARDING.md).

## Run (Python 3.14)

```bat
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Fill `.env` (Supabase URL, anon, service role, JWT secret, `DATA_GOV_IN_API_KEY`). Apply SQL `001`–`011` once — [`docs/SQL_APPLY.md`](docs/SQL_APPLY.md).

```bat
set RUN_SCHEDULER=0
set RATE_LIMIT_ENABLED=0
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- Health: `http://127.0.0.1:8000/health`
- OpenAPI: `http://127.0.0.1:8000/docs` (disabled when `APP_ENV=production`)
- Frontend origin: set `CORS_ORIGIN` (comma-separated). Default includes `http://localhost:3000` and `http://localhost:5173`.

Docker (single worker — required for in-process scheduler):

```bash
docker build -t krishi-bazaar .
docker run --env-file .env -p 8000:8000 krishi-bazaar
```

## Tests

```bat
set RUN_SCHEDULER=0
set RATE_LIMIT_ENABLED=0
pytest -q
```

Offline: FakeSupabase, no network. Live checks: `python test_db.py`, `python demo/reconcile.py`, `python demo/live_smoke.py` (uvicorn must be up). Judge script: [`docs/DEMO.md`](docs/DEMO.md).

## Auth (for the frontend)

`Authorization: Bearer <jwt>`. Role comes from `user_profiles`, not the token. Demo mint:

```bat
python demo/mint_admin_token.py --sub <auth.users uuid> --hours 2
```

Farmer vs admin is the DB row. Elevate only in SQL:

```sql
select public.admin_set_role('<uuid>'::uuid, 'admin');
```

## Farmer / FPO sequence

1. `PATCH /api/v1/me/` — phone E.164, `mr|hi|en`, lat/lng, district
2. `POST /api/v1/lots/` — qty, grade (`FAQ|General|Special`), asking price
3. `GET /api/v1/lots/{id}/advice` — Sell Now / Hold + **best local verified buyer**
4. `GET /api/v1/lots/{id}/matches`
5. `POST /api/v1/offers/` (48h TTL) → accept → `POST /api/v1/payments/` → `paid|failed|disputed`
6. `GET /api/v1/lots/{id}/ledger`
7. `POST /api/v1/grievances/` if quality / payment / logistics fails
8. `POST /api/v1/logistics/bookings` against a lot (capacity-checked)
9. FPO: `POST /api/v1/lots/aggregate`

SMS: registered number texts `PYAJ` / `कांदा` → modal + sale-window + buyer. Unknown MSISDNs are ignored.

Admin JWT (DB role `admin`): forecast/alert jobs, buyer verify, `/dashboard`.
