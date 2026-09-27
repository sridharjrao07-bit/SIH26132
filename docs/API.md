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

<!-- BEGIN GENERATED: endpoint reference — do not edit; run `make docs` -->

## Endpoints

| Method | Path | Summary |
|---|---|---|
| POST | `/api/v1/admin/alert-check/run` | Trigger Alert Check |
| GET | `/api/v1/admin/buyers` | Admin List Buyers |
| POST | `/api/v1/admin/buyers` | Admin Create Buyer |
| POST | `/api/v1/admin/buyers/rescore` | Admin Rescore Buyers |
| PATCH | `/api/v1/admin/buyers/{buyer_id}/verify` | Admin Verify Buyer |
| GET | `/api/v1/admin/events` | Admin List Events |
| POST | `/api/v1/admin/events/ingest` | Admin Events Ingest |
| POST | `/api/v1/admin/forecast/backtest` | Trigger Forecast Backtest |
| POST | `/api/v1/admin/forecast/run` | Trigger Forecast |
| GET | `/api/v1/admin/grievances` | Admin List Grievances |
| PATCH | `/api/v1/admin/grievances/{grievance_id}` | Admin Update Grievance |
| POST | `/api/v1/admin/offers/expire` | Admin Expire Offers |
| GET | `/api/v1/alerts/` | List Alerts |
| POST | `/api/v1/alerts/` | Create Alert |
| DELETE | `/api/v1/alerts/{alert_id}` | Delete Alert |
| PATCH | `/api/v1/alerts/{alert_id}` | Update Alert |
| GET | `/api/v1/buyers/` | List Buyers |
| POST | `/api/v1/buyers/register` | Register Buyer |
| GET | `/api/v1/buyers/{buyer_id}/supply` | Buyer Supply |
| PATCH | `/api/v1/buyers/{buyer_id}/verify` | Verify Buyer |
| GET | `/api/v1/commodities/` | Get Commodities |
| GET | `/api/v1/direct/config` | Direct Config |
| POST | `/api/v1/direct/fair-price` | Fair Price |
| POST | `/api/v1/direct/group-buy` | Group Buy |
| GET | `/api/v1/direct/impact` | Direct Impact |
| POST | `/api/v1/direct/plan` | Plan Direct |
| POST | `/api/v1/direct/plans/commit` | Commit Plan |
| GET | `/api/v1/direct/plans/{plan_id}` | Get Plan |
| POST | `/api/v1/direct/rupee` | Consumer Rupee |
| GET | `/api/v1/direct/trace/{token}` | Trace Order |
| GET | `/api/v1/forecasts` | Get Forecasts |
| GET | `/api/v1/forecasts/summary` | Get Forecasts Summary |
| GET | `/api/v1/grievances/` | List Grievances |
| POST | `/api/v1/grievances/` | Create Grievance |
| GET | `/api/v1/logistics/` | List Logistics |
| GET | `/api/v1/logistics/bookings` | List Bookings |
| POST | `/api/v1/logistics/bookings` | Create Booking |
| PATCH | `/api/v1/logistics/bookings/{booking_id}` | Update Booking |
| GET | `/api/v1/lots/` | List Lots |
| POST | `/api/v1/lots/` | Create Lot |
| POST | `/api/v1/lots/aggregate` | Aggregate Lots |
| GET | `/api/v1/lots/{lot_id}` | Get Lot |
| GET | `/api/v1/lots/{lot_id}/advice` | Lot Advice |
| PATCH | `/api/v1/lots/{lot_id}/grade` | Grade Lot |
| GET | `/api/v1/lots/{lot_id}/ledger` | Get Lot Ledger |
| GET | `/api/v1/lots/{lot_id}/matches` | Match Buyers |
| PATCH | `/api/v1/lots/{lot_id}/withdraw` | Withdraw Lot |
| GET | `/api/v1/markets/` | Get Markets |
| GET | `/api/v1/markets/nearby` | Get Nearby Markets |
| GET | `/api/v1/me/` | Get Me |
| PATCH | `/api/v1/me/` | Update Me |
| GET | `/api/v1/offers/` | List Offers |
| POST | `/api/v1/offers/` | Create Offer |
| PATCH | `/api/v1/offers/{offer_id}` | Update Offer |
| GET | `/api/v1/payments/` | List Payments |
| POST | `/api/v1/payments/` | Create Payment |
| PATCH | `/api/v1/payments/{payment_id}/disputed` | Mark Disputed |
| PATCH | `/api/v1/payments/{payment_id}/failed` | Mark Failed |
| PATCH | `/api/v1/payments/{payment_id}/paid` | Mark Paid |
| GET | `/api/v1/prices/historical` | Get Historical Prices |
| GET | `/api/v1/prices/latest` | Get Latest Prices |
| GET | `/api/v1/sale-window/` | Sale Window |
| POST | `/api/v1/sms/simulate` | Simulate Inbound |
| POST | `/api/v1/sms/webhook` | Handle Sms Webhook |
| GET | `/api/v1/storage/bookings` | List Bookings |
| POST | `/api/v1/storage/bookings` | Book Storage |
| PATCH | `/api/v1/storage/bookings/{booking_id}` | Update Booking |
| GET | `/api/v1/storage/facilities` | List Facilities |
| GET | `/dashboard` | Get Dashboard |
| GET | `/dashboard/api/forecast-stats` | Get Forecast Stats |
| GET | `/dashboard/api/ingestion-logs` | Get Ingestion Logs |
| DELETE | `/dashboard/session` | Dashboard Logout |
| POST | `/dashboard/session` | Dashboard Session |
| GET | `/health` | Health Check |
| GET | `/metrics` | Metrics |
| GET | `/readyz` | Readyz |

<!-- END GENERATED -->

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

## SMS Webhook & Simulation

The platform supports an inbound SMS webhook (e.g. MSG91) to provide offline farmers with sale-window advice and buyer matching via text.

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/sms/webhook` | Receives inbound SMS. Requires valid HMAC signature (`X-Signature` header matching `INBOUND_HMAC_SECRET`). |
| POST | `/api/v1/sms/simulate` | For judges/testing. Simulates an inbound SMS without HMAC validation. Returns the exact SMS text the farmer would receive. |

**Simulation Body:**
```json
{
  "sender": "919876543210",
  "message": "PYAJ"
}
```
