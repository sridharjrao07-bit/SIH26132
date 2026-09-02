# API contract (frontend team)

This repo is the **backend only**. Serve the UI from another origin and point it at this API.

## Base URL

Local: `http://127.0.0.1:8000`  
Set `CORS_ORIGIN` in `.env` to the frontend origin(s), comma-separated:

```
CORS_ORIGIN=http://localhost:3000,http://localhost:5173
```

Restart uvicorn after changing CORS. Credentials are allowed; send `Authorization` only — do not put JWTs in `localStorage` if you can avoid it (memory or HttpOnly cookie on the frontend host).

OpenAPI (non-production): `http://127.0.0.1:8000/docs`

## Auth

```
Authorization: Bearer <jwt>
```

- Algorithm: HS256, `aud=authenticated`, `sub` = `auth.users` / `user_profiles.id` UUID.
- **Role is not a JWT claim.** FastAPI reads `user_profiles.role` (`farmer` | `fpo` | `admin` | `buyer`).
- Missing/invalid token → `401` `{"detail":"missing bearer token"}` or `"invalid token"`.
- Wrong role → `403`.
- Mint a demo token (prints to stdout — do not commit it):

```bash
python demo/mint_admin_token.py --sub <user_profiles uuid> --hours 2
```

The API verifies that JWT itself. It does **not** forward it to PostgREST (hosted JWT signing keys reject locally minted HS256).

## Public (no token)

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status":"ok"}` |
| GET | `/api/v1/markets/` | `?district=` |
| GET | `/api/v1/markets/nearby?lat=&lng=&radius_km=50` | |
| GET | `/api/v1/commodities/` | no sanity bands |
| GET | `/api/v1/prices/latest?limit=` | `limit` 1–500 |
| GET | `/api/v1/prices/historical?market_id=&commodity_id=&days=30` | `days` 1–365 |
| GET | `/api/v1/forecasts?market_id=&commodity_id=&days=` | future dates only |
| GET | `/api/v1/forecasts/summary` | |
| GET | `/api/v1/sale-window/?commodity_id=&market_id=&lang=mr` | `en` \| `mr` \| `hi`. 404 if no recent price |
| GET | `/api/v1/buyers/` | verified by default |
| GET | `/api/v1/buyers/{id}/supply` | open lots that fit that buyer |
| GET | `/api/v1/logistics/?district=Nashik&kind=` | `kind=storage` \| `transport` |

## Farmer / FPO (Bearer)

| Method | Path |
|---|---|
| GET/PATCH | `/api/v1/me/` |
| POST/GET | `/api/v1/lots/` |
| GET | `/api/v1/lots/{id}` `/lots/{id}/advice` `/lots/{id}/matches` `/lots/{id}/ledger` |
| PATCH | `/api/v1/lots/{id}/grade` `/lots/{id}/withdraw` |
| POST | `/api/v1/lots/aggregate` (role `fpo`) |
| POST/GET/PATCH | `/api/v1/offers/` |
| POST/GET | `/api/v1/payments/` |
| PATCH | `/api/v1/payments/{id}/paid` `/failed` `/disputed` |
| POST/GET | `/api/v1/grievances/` |
| POST/GET/PATCH | `/api/v1/logistics/bookings` |
| CRUD | `/api/v1/alerts/` |

### Lot create body

```json
{
  "commodity_id": "<uuid>",
  "market_id": "<uuid>",
  "quantity_qtl": 20,
  "grade": "General",
  "asking_price": 1600
}
```

`grade` is `FAQ` | `General` | `Special`.

### Profile patch

```json
{ "phone": "9876543210", "preferred_language": "mr", "lat": 20.12, "lng": 74.34, "district": "Nashik" }
```

Phone is normalised to E.164 (`+91…`). Role is not client-writable.

### Sale-window / advice

`action` is `SELL_NOW` | `HOLD` | `WAIT`.  
`action_label` / `reason` follow `lang`.  
`best_buyer` on `/lots/{id}/advice` is the local-first match, not a price list.

## Admin (Bearer, DB role `admin`)

`POST /api/v1/admin/forecast/run`  
`POST /api/v1/admin/alert-check/run`  
`POST /api/v1/admin/buyers` · `PATCH /api/v1/admin/buyers/{id}/verify`  
`GET/PATCH /api/v1/admin/grievances`  
`POST /api/v1/admin/offers/expire`  
`POST /api/v1/admin/buyers/rescore`  
HTML ops shell: `/dashboard` (not the farmer product).

## Errors

Bodies are always `{"detail": ...}` — never a stack, SQL, or PostgREST code.

| HTTP | When |
|---|---|
| 400 | Bad JSON; missing FK (`23503` → `referenced record not found`) |
| 401 | Missing/invalid JWT (`PGRST301` included) |
| 403 | Wrong role; unsigned SMS webhook; privilege (`42501`) |
| 404 | Unknown lot/offer/payment **or** not yours (no leak) |
| 409 | Duplicate (`23505`); illegal state (pay a rejected offer) |
| 422 | Pydantic validation; invalid UUID (`22P02`); bad lot `status` |
| 500 | Unhandled — `Internal server error` only |
| 503 | Data store down; geo RPC; admin job failed |

OpenAPI (non-production): `GET /openapi.json` and `/docs`.

## SMS (not the web UI)

Registered farmer texts `PYAJ` / `कांदा` → modal + Sell Now/Hold + best local buyer if they have an open lot. Unsigned webhook is `403`.
