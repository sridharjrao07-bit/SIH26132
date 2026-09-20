# Frontend Integration Guide — Krishi Bazaar API

**Audience:** frontend engineers building the farmer / buyer / FPO UI against this backend.
**Scope:** the HTTP contract, the domain vocabulary, and the traps. No UI/UX art direction here.
**Base path:** every business endpoint is under `/api/v1`. System endpoints (`/health`, `/readyz`, `/metrics`) and the ops dashboard (`/dashboard*`) are not.

> **Read section 9 before you write any data layer.** 56 of 67 operations have **no response schema** in OpenAPI, and two endpoints currently have live bugs. If you codegen a typed client from `/openapi.json` you will get `any` for almost everything and you will hit a 500 and a silent data-drop.

---

## 1. Auth: how identity actually works

The backend does **not** issue tokens. Supabase Auth does. You use the Supabase JS client to sign in, then forward the access token.

```js
// Frontend: sign in with Supabase, then forward the token
const { data: { session } } = await supabase.auth.signInWithPassword({ email, password });

fetch(`${API}/api/v1/me/`, {
  headers: { Authorization: `Bearer ${session.access_token}` }
});
```

### Rules the backend enforces

| Rule | Detail | What it means for you |
|---|---|---|
| Header format | `Authorization: Bearer <jwt>` | Missing/malformed → **401** `{"detail":"missing bearer token"}` |
| Required claims | `exp`, `sub`, `aud` | Token without `aud: "authenticated"` → **401** `invalid token` |
| Issuer | If `SUPABASE_JWT_ISSUER` is set (always in prod), `iss` must match | You **must** use the same Supabase project as the backend |
| Algorithm | HS256 with the project's legacy JWT secret | If your Supabase project has migrated to signing keys / asymmetric JWTs, tokens will be rejected → every authenticated call fails |
| **Role** | Read from the `user_profiles` table — **never** from the token | You cannot self-elevate by editing token claims. Don't try |
| `sub` | Equals `user_profiles.id` (FK to `auth.users`) | `session.user.id` is the user id everywhere |

### Roles and how an account gets one

| Role | Assigned by | Self-service? |
|---|---|---|
| `farmer` | DB trigger on signup (`handle_new_user`) | ✅ default for every new signup |
| `buyer` | `POST /api/v1/buyers/register` creates a `buyers` row with `verified=false` | ✅ but needs admin approval to appear in matching |
| `fpo` | SQL only (`admin_set_role`) | ❌ **Cannot be self-created.** See trap 9.3 |
| `admin` | SQL only | ❌ never expose admin UI to normal users |

**Implication:** your signup flow only ever produces a farmer. Buyer onboarding is a second, explicit step. FPO and admin accounts are provisioned out-of-band — build the UI to *detect* those roles from `GET /api/v1/me/` and show/hide features, not to create them.

### Role gating in the UI

```js
const me = await api.get('/api/v1/me/');   // { id, name, role, preferred_language, district, lat, lng, ... }
const isAdmin = me.role === 'admin';
const isFpo   = me.role === 'fpo';
```

Endpoint-level enforcement is server-side; your gating is cosmetic. A farmer calling an admin route gets **403**.

---

## 2. CORS and environments

- `CORS_ORIGIN` is a **comma-separated allowlist**. Default: `http://localhost:3000,http://localhost:5173`.
- `allow_credentials=true`, so **wildcards are not used**. Send your dev origin to the backend owner to be added.
- A disallowed origin receives **no** `Access-Control-Allow-Origin` header (not a wildcard) — the browser blocks it and you'll see a generic CORS error, not a 4xx.
- Allowed request headers: `Authorization`, `Content-Type`, `X-Signature`, `X-Timestamp`.

| Env | `/docs`, `/redoc`, `/openapi.json` |
|---|---|
| development / staging | enabled |
| production (`APP_ENV=production`) | **disabled (404)** |

If you rely on `/docs` for manual testing, that's a dev-only convenience. Pin `/openapi.json` locally if you want it.

---

## 3. Which endpoints need a login

This is the single most useful table for deciding your app shell.

### 🟢 Public — no token (safe for logged-out landing pages)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/markets/` | `?district=&active_only=true` |
| GET | `/api/v1/markets/nearby` | `?lat=&lng=&radius_km=50` — **required** lat/lng |
| GET | `/api/v1/commodities/` | name_en / name_mr / name_hi |
| GET | `/api/v1/prices/latest` | `?market_id=&commodity_id=&limit=50` (max 500), last 7 days |
| GET | `/api/v1/prices/historical` | **requires** `market_id` + `commodity_id`, `?days=30&limit=`
| GET | `/api/v1/forecasts` | **requires** `market_id` + `commodity_id`, `?days=7` |
| GET | `/api/v1/forecasts/summary` | all pairs, no params |
| GET | `/api/v1/sale-window/` | `?commodity_id=&market_id=&lang=mr` — the headline widget |
| GET | `/api/v1/buyers/` | `?district=&commodity_id=&verified_only=true` |
| GET | `/api/v1/logistics/` | `?district=&kind=storage\|transport` |
| GET | `/api/v1/storage/facilities` | `?district=` |
| GET | `/health`, `/readyz`, `/metrics` | liveness/readiness/Prometheus |

**Build the price-discovery experience as a public, unauthenticated surface.** That is where the demo lands hardest.

### 🔐 Authenticated — `Authorization: Bearer …`

| Method | Path | Who |
|---|---|---|
| GET/PATCH | `/api/v1/me/` | any user |
| POST/GET | `/api/v1/lots/` | farmer/FPO |
| GET | `/api/v1/lots/{id}` · `/{id}/advice` · `/{id}/matches` · `/{id}/ledger` | **lot owner or its FPO only** |
| PATCH | `/api/v1/lots/{id}/grade` · `/{id}/withdraw` | lot owner |
| POST | `/api/v1/lots/aggregate` | role `fpo` |
| POST/GET | `/api/v1/offers/` · PATCH `/offers/{id}` | participants |
| POST/GET | `/api/v1/payments/` · PATCH `/{id}/paid|failed|disputed` | participants |
| POST/GET | `/api/v1/grievances/` | any user |
| POST/GET | `/api/v1/logistics/bookings` · PATCH `/{id}` | booking owner |
| POST/GET/PATCH | `/api/v1/storage/bookings` | booking owner |
| POST/GET/PATCH/DELETE | `/api/v1/alerts/` | alert owner |
| POST | `/api/v1/buyers/register` | any authenticated user |
| GET | `/api/v1/buyers/{id}/supply` | authenticated |
| — | all `/api/v1/admin/*` | role `admin` |

---

## 4. The five user journeys you should build

### 4.1 Farmer: onboard → list a lot → get advice → sell

```
1. Sign up (Supabase Auth)              → trigger creates user_profiles, role=farmer
2. PATCH /api/v1/me/                    → { name, phone, preferred_language, district, lat, lng }
3. POST  /api/v1/lots/                  → { commodity_id, quantity_qtl, grade, asking_price, ... }
4. GET   /api/v1/lots/{id}/advice       → action: SELL_NOW|HOLD|WAIT + best_buyer + next_step
5. GET   /api/v1/lots/{id}/matches      → ranked buyer list
6. POST  /api/v1/offers/  (buyer side)  → 48h TTL
7. PATCH /api/v1/offers/{id}            → { status: "accepted" | "rejected" }
8. POST  /api/v1/payments/              → { offer_id, amount, reference }
9. PATCH /api/v1/payments/{id}/paid     → closes lot atomically
10. GET  /api/v1/lots/{id}/ledger       → full audit timeline
```

**Step 4 is the product.** `advice` is not a price dump — it returns an action, a localised reason, a next step, and the best local verified buyer. Design your main farmer screen around it.

### 4.2 Buyer: register → get verified → browse supply

```
1. Sign up + PATCH /api/v1/me/
2. POST /api/v1/buyers/register         → verified=false  (admin must approve)
3. GET  /api/v1/buyers/{id}/supply      → open lots that fit your demand
4. POST /api/v1/offers/                 → bid on a lot
```

Show a **"pending verification"** state prominently — unverified buyers do not surface in farmer matching.

### 4.3 Price discovery (public)

```
GET /api/v1/commodities/                → build the crop picker (name_en/mr/hi)
GET /api/v1/markets/?district=Nashik     → build the mandi picker
GET /api/v1/prices/historical?market_id=&commodity_id=&days=30   → chart
GET /api/v1/prices/latest?commodity_id=&limit=50                 → today's board
GET /api/v1/forecasts?market_id=&commodity_id=&days=7            → 7-day forecast
GET /api/v1/sale-window/?commodity_id=&lang=mr                   → Sell Now / Hold / Wait
```

### 4.4 Logistics and storage

```
GET  /api/v1/logistics/?district=Nashik&kind=transport   → options with capacity_qtl & rate_per_qtl
POST /api/v1/logistics/bookings                          → { lot_id, logistics_id, quantity_qtl }
GET  /api/v1/storage/facilities?district=Nashik
POST /api/v1/storage/bookings                            → { lot_id, facility_id, quantity_qtl }
PATCH /api/v1/storage/bookings/{id}                       → { status: "confirmed" }
```

Capacity is validated server-side. On `409`, render the message — it includes available/used quantities.

### 4.5 Alerts (price thresholds)

```
POST   /api/v1/alerts/     → { commodity_id, threshold_price, condition: "gte"|"lte", expires_at? }
GET    /api/v1/alerts/     → ?limit=50 (max 200)
PATCH  /api/v1/alerts/{id} → { threshold_price?, condition?, active?, expires_at? }
DELETE /api/v1/alerts/{id}
```

An alert with `market_id: null` resolves to the **nearest market** at check time. Alerts are delivered by SMS, not push — there is no in-app notification feed endpoint.

---

## 5. Domain vocabulary — render these exact strings

Get these wrong and your badges/colors break.

### Sale-window action (the headline recommendation)

| `action` | `recommendation` | `action_label` (en) | Suggested UI |
|---|---|---|---|
| `SELL_NOW` | `sell` | Sell Now | green / primary CTA |
| `HOLD` | `hold` | Hold | amber |
| `WAIT` | `wait` | Wait | grey |

`action_label` is **already localised** when you pass `?lang=mr|hi`:

| lang | sell | hold | wait |
|---|---|---|---|
| en | Sell Now | Hold | Wait |
| mr | आज विका | थोडे थांबा | थांबा |
| hi | आज बेचें | थोड़ा रुकें | रुकें |

Render `action_label` directly — **do not** build your own translation map.

**`reason_code`** is stable and safe to branch on for icons/tooltips (the `reason` prose is localised and may be reworded):

| `reason_code` | Meaning |
|---|---|
| `sell_no_storage` | Sell — no storage available nearby |
| `sell_arrivals` | Sell — arrivals spiking |
| `sell_forecast` | Sell — forecast is flat/down |
| `hold` | Hold — better price expected |
| `wait` | Wait — arrivals normal, no urgency |

### Lot lifecycle (`lots.status`)

`open` → `offered` → `matched` → `sold`
Side exits: `withdrawn`

The backend **rejects backwards transitions** (a DB trigger enforces monotonicity). Reflect that in your UI: don't render a "reopen" button.

### Grade (`lots.grade`) — closed enum

`FAQ` · `General` · `Special`  (default `General`)

### Offer (`offers.status`)

`pending` → `accepted` | `rejected` | `expired`

Offers have a **48-hour TTL**. The API adds a computed `expires_at` on create/list/decide — use it to render a countdown. Don't compute it yourself from `created_at`.

### Payment (`payments.status`)

`pending` · `paid` · `failed` · `disputed`

`PATCH /payments/{id}/paid` also advances the lot to `sold` **in the same transaction** — don't issue a separate lot update.

### Booking (logistics & storage)

`requested` → `confirmed` → `completed`  (or `cancelled`)

Active statuses = `requested`, `confirmed`. `completed`/`cancelled` are terminal — you cannot transition back.

### Grievance (`grievances.status` / `.category`)

- status: `open` · `in_progress` · `resolved` · `rejected`
- category: `payment` · `quality` · `logistics` · `buyer` · `other`

### Buyer type

`trader` · `processor` · `institutional` · `fpo` · `digital`

### buyer verification

`verification_state`: `pending` (default) · `approved` · `rejected` (admin-only field)

---

## 6. Error contract — one handler to rule them all

Every error is `{"detail": "<lowercase human string>"}`. Never a stack trace. Map by status:

| Status | Meaning | UI action |
|---|---|---|
| **400** | Bad input / referenced record missing / booking qty > lot qty | Inline field error |
| **401** | Missing/invalid/expired token | Re-auth, refresh session |
| **403** | Authenticated but wrong role (admin route as farmer) | Hide the feature |
| **404** | Not found **or not yours** | Show empty state |
| **409** | Conflict — invalid state transition, duplicate, capacity exceeded, cross-tenant | Show the message; the DB told us the real reason |
| **422** | Validation failed (Pydantic, **or** invalid enum/id) | Field-level errors |
| **503** | Data store unavailable, or a job failed | Retry-able banner |

### Two patterns to internalise

**1. Validation errors (422) are FastAPI-standard and include field detail:**

```json
{ "detail": [ { "loc": ["body","quantity_qtl"], "msg": "Input should be greater than 0", "type": "greater_than" } ] }
```

But a 422 raised *by the backend for an invalid enum/id* is a plain string:

```json
{ "detail": "invalid status" }
```

So your error renderer must handle **both** `detail: string` and `detail: array`. This will bite you if you assume one shape.

**2. `404` deliberately means "not found OR not yours".** The backend returns 404 (not 403) when you request another farmer's lot, to avoid leaking existence. Don't show "permission denied" — show a not-found/empty state.

---

## 7. Rate limits and data freshness

| Limit | Value |
|---|---|
| Global default | **120 requests / minute / IP** |
| `POST /api/v1/sms/webhook` | **30 / minute** |

The limiter keys on the connection IP; behind a proxy it relies on `--forwarded-allow-ips` being configured. On exceed → `429`. Debounce search-as-you-type; a naive "type a district" autocomplete hitting `/markets/` per keystroke will trip this during your demo.

### How stale is the data?

The backend ingests on a schedule, not in real time. There is **no websocket, no SSE, no ETag, no `Last-Modified`**.

| Job | Default cadence |
|---|---|
| Mandi price ingestion | every **6 hours** |
| Forecast generation | every **6 hours** (after ingestion) |
| Alert checks | every **60 minutes** |
| Offer expiry sweep | on demand / admin |

**Poll at most every 5 minutes**, and show an explicit "as of `<generated_at>`" timestamp. There is no point building a live-ticking price widget — it cannot update faster than the ingestion job.

---

## 8. Response shapes (required reading — OpenAPI won't help you)

Most endpoints return **raw PostgREST rows**. Field names below are the real column names.

### `GET /api/v1/me/` → user profile row

```json
{ "id": "<uuid>", "name": "Ramesh", "phone": "+919812345678",
  "role": "farmer", "preferred_language": "mr",
  "district": "Nashik", "lat": 19.99, "lng": 73.79,
  "created_at": "...", "updated_at": "..." }
```

- `role`: `farmer` | `buyer` | `fpo` | `admin`
- `preferred_language`: `en` | `mr` | `hi` — **drive your whole i18n default from this**
- `PATCH` accepts only: `name`, `phone`, `preferred_language`, `district`, `lat`, `lng`. **`role` is not writable** — it is silently dropped.
- `phone` must be a 10-digit Indian mobile (normalised to E.164 server-side) or you get 400.

### `GET /api/v1/prices/latest` · `/historical` → array of flattened rows

```json
{ "id": "...", "market_id": "...", "commodity_id": "...",
  "arrival_date": "2026-09-17", "min_price": 1400.0, "max_price": 2100.0,
  "modal_price": 1800.0, "unit": "quintal", "arrival_qty": 350.0,
  "variety": "General", "grade": "General", "source": "data_gov_in",
  "market_name": "Lasalgaon", "district": "Nashik",
  "commodity_name_en": "Onion", "commodity_name_mr": "कांदा", "commodity_name_hi": "प्याज" }
```

The joined `market_name`, `district`, and `commodity_name_*` are **flattened for you** — this is one of the few endpoints with a typed `response_model`. Use `commodity_name_{lang}` for display and fall back to `_en`.

`arrival_qty` **may be `null`** (source didn't report it). Handle it — it powers the "arrivals up → price falls" narrative, so grey the widget rather than showing `0`.

### `GET /api/v1/forecasts` → array

```json
{ "id": "...", "market_id": "...", "commodity_id": "...",
  "forecast_date": "2026-09-19", "predicted_price": 1850.0,
  "lower_bound": 1700.0, "upper_bound": 2000.0,
  "confidence": "medium", "method": "feature_ols", "observations": 42,
  "status": "ok", "generated_at": "...",
  "market_name": "Lasalgaon", "district": "Nashik", "commodity_name_en": "Onion" }
```

- `confidence`: `high` | `medium` | `low`
- `status`: `ok` | `insufficient_data` | `stale`
- `/forecasts` returns **only `status='ok'`** — render the confidence band (`lower_bound`–`upper_bound`), not a bare line.
- `/forecasts/summary` also returns `insufficient_data` so you can show *"not enough data yet"* instead of an empty screen. It excludes `stale`.

### `GET /api/v1/lots/{id}/advice` → the composite object

```json
{ "lot_id": "...", "action": "SELL_NOW", "action_label": "आज विका",
  "reason": "…localised prose…", "next_step": "Book transport (…) and offer to the best local buyer.",
  "sale_window": { /* full sale-window object, see below */ },
  "best_buyer": { "buyer_id","buyer_name","buyer_type","verified","district",
                  "score","reasons","max_price","demand_qty_qtl",
                  "payment_reliability","distance_km" },
  "matches": [ /* up to 5, same shape as best_buyer */ ],
  "bookings": [ /* existing logistics bookings for this lot */ ],
  "suggested_transport": [ /* up to 3 options */ ] }
```

- `next_step` may be **`null`** — render nothing rather than an empty card.
- `best_buyer` may be **`null`** — handle "no verified local buyer yet".
- `matches` here is capped at 5; `/matches` gives up to 10.

### `GET /api/v1/sale-window/` → sale-window object

```json
{ "commodity_id": "...", "market_id": "...", "recommendation": "sell",
  "action": "SELL_NOW", "action_label": "Sell Now", "reason": "...",
  "reason_code": "sell_arrivals", "lang": "en",
  "latest_price": 1800.0, "forecast_day1": 1850.0, "forecast_trend": "up",
  "arrivals_qty": 350.0, "district_arrivals_qty": 1200.0,
  "supply_pressure": "high", "nearby": [...], "market_name": "Lasalgaon",
  "storage": [...], "storage_available": true,
  "district": "Nashik", "better_market": { ... } | null }
```

- Returns **404** when there is no recent price for that commodity — design a real empty state.
- `better_market` is non-null when a neighbouring mandi pays better; that's a strong upsell card.

### `GET /api/v1/lots/{id}/ledger` → transparency timeline

```json
{ "lot": {...}, "offers": [...], "payments": [...], "grievances": [...],
  "bookings": [...],
  "events": [ { "at": "...", "type": "lot_created", "detail": {...} } ] }
```

`events` is a **pre-sorted, merged timeline** — render it directly as a vertical stepper. `type` values: `lot_created`, `offer_pending|accepted|rejected|expired`, `payment_pending|paid|failed|disputed`, `grievance_open|...`, `booking_requested|confirmed|...`.

This is the "transparent record" the problem statement asks for. Give it a dedicated screen.

### `GET /api/v1/lots/{id}/matches`

```json
{ "lot_id": "...", "best_buyer": {...} | null, "matches": [ /* up to 10 */ ],
  "advice": "No verified local buyer fits this lot yet. Keep the lot open or pool it via an FPO." }
```

### `GET /api/v1/buyers/` → array

```json
{ "id","name","type","verified","phone","district","lat","lng",
  "commodity_id","demand_qty_qtl","max_price",
  "quality_requirements","payment_reliability" }
```

`verified_only=true` is the **default** — you must explicitly pass `false` to see unverified buyers.

### `GET /api/v1/sale-window/` and matching score

`score` is a float; `reasons` is a string array of machine codes: `same_district`, `price_covers_ask`, `volume_fit`, `bid_below_ask`, `verified`, `reliability_high`, … Render badges from `reasons`, and **don't** render the raw code — give each a human label.

---

## 9. Traps — read before coding

### 9.1 🔴 `POST /api/v1/sms/webhook` returns **HTTP 500** on every valid request

A missing `import asyncio` in `app/routers/sms.py` makes the only `async def` route in the codebase throw `NameError` **after** HMAC verification passes. Fixed in Phase 0 — **confirm the fix has landed** before building anything on it.

- Do **not** build an SMS-send UI against this from the browser. It is a *machine* endpoint for an SMS provider, protected by HMAC (`X-Signature`, `X-Timestamp`), not a bearer token.
- For demos there is `POST /api/v1/sms/simulate` (admin-only, no HMAC) — use that for a "simulate an inbound SMS" demo button.
- Signature scheme if you ever need it: `HMAC-SHA256(secret, raw_body + timestamp)`, ±5 min drift, replay-protected.

### 9.2 🔴 `POST /api/v1/buyers/register` silently drops 7 of 11 fields

Currently forwards only `name`, `type`, `phone`, `district` to the RPC. It returns **201 Created** while discarding:

`commodity_id` · `demand_qty_qtl` · `max_price` · `quality_requirements` · `payment_reliability` · `lat` · `lng`

**Impact on UI:** any buyer profile created this way has no commodity, no volume, no max price, and no coordinates — so buyer↔lot matching degrades to district-only. Build the registration form, but **verify this is fixed** before demonstrating matching. Until then, expect `supply`/`matches` to return weak results.

### 9.3 FPO accounts cannot be created by the frontend

`role='fpo'` is only assignable via SQL (`admin_set_role`). The `POST /api/v1/lots/aggregate` endpoint requires it. Either seed an FPO account for the demo or hide the FPO feature behind a role check. Also note aggregation requires **2–50 lots** that all share one commodity and are all `open`.

### 9.4 Do not codegen a client from OpenAPI

**11 of 67 operations have a response schema; 56 do not.** The rest serialize as `{}`. `openapi-typescript` / `orval` will type almost everything `any`, and — worse — the schemas that *do* exist can silently drop fields:

| Model | Fields it hides |
|---|---|
| `BuyerResponse` | `created_at`, `updated_at`, `owner_user_id`, `verification_state`, `review_notes` |
| `LotResponse` | `created_at`, `updated_at` |

**Hand-write your response types from section 8.** If you want to show "pending verification", read `verification_state` from the **admin** endpoint, not from `POST /buyers/register`.

### 9.5 `/lots/{id}/advice` and `/matches` are owner-only

They return **404** for any lot you don't own (or aren't the FPO for). For a buyer-facing "inspect this lot" screen, you need `/api/v1/buyers/{id}/supply` instead. Build two different detail views — do not reuse the farmer's lot screen for buyers.

### 9.6 Forecasts and historical prices need an **exact pair**

`market_id` **and** `commodity_id` are both required on `/prices/historical` and `/forecasts`. There is **no** "give me all prices for onion" or "all commodities at Lasalgaon" endpoint for history. To build a chart you must resolve both ids first (`/commodities/`, `/markets/`). For a top-level board, use `/prices/latest` (filterable by just one) or `/forecasts/summary` (returns everything, deduped).

### 9.7 Progressions are DB-enforced — don't offer impossible actions

- **Lot:** `open → offered → matched → sold`. A trigger rejects regressions. Never render "reopen".
- **Offer:** only `accepted` / `rejected` are accepted by `PATCH /offers/{id}`. Sending `expired` (which is a valid *read* status) returns **422**.
- **Storage booking:** `PATCH` rejects `requested` ("cannot transition back to requested") and rejects any change from `cancelled`/`completed` with **409**.
- **Logistics booking:** a `completed` booking cannot change status (**409**).

### 9.8 Capacity errors are 409 everywhere

Exceeding capacity returns **409** (opaque detail) on both `/storage/bookings` and `/logistics/bookings`. Since migration 036 the check runs inside the `storage_booking_create` / `logistics_booking_create` SECURITY DEFINER RPCs under a facility/option row lock, so concurrent requests can never oversubscribe a godown or truck. (Previously the two routes disagreed: 409 vs 400, with a racy Python-side check.)

### 9.9 No search, no pagination cursors

- There is **no** free-text search anywhere. Filter by `district` / `commodity_id` only.
- Lists are hard-capped server-side (`lots` 100, `offers` 100, `payments` 100, `grievances` 100, `markets` unbounded, `buyers` 100, `prices/latest` ≤500, `prices/historical` ≤1000). There is no `offset`/`cursor` and no `total`. **Do not build infinite scroll or "page 2"** — build filtered views instead.
- `/forecasts/summary` dedupes in Python and is capped at 2000 rows; it can silently under-report if the dataset grows. Fine for a demo, don't promise "all pairs".

### 9.10 Don't build these — they don't exist

| Tempting feature | Reality |
|---|---|
| Real payment gateway / UPI | Payment statuses are recorded; settlement is **mocked**. `eNAM` integration is explicitly out of scope |
| Push / in-app notification feed | Alerts are delivered as **SMS** only |
| Real-time price ticks | Scheduled ingestion, ~6h cadence. No websocket/SSE |
| User profile avatars / file upload | Storage is for **cold-storage facilities**, not user media |
| Multi-language beyond en/mr/hi | `preferred_language` is a closed enum of exactly those three |
| Admin user management UI | `admin_set_role` is SQL-only, deliberately not exposed |
| Chat between farmer and buyer | No messaging endpoint; offers + grievances are the channels |

### 9.11 `PATCH` semantics: omission ≠ null

`PATCH /api/v1/me/` and `/api/v1/alerts/{id}` use `exclude_unset=True` — **you must omit** a field to leave it unchanged. Sending `null` explicitly is a different intent (for `alerts.expires_at`, `null` **clears** the expiry). Build your forms to omit untouched fields rather than sending a full object with nulls.

---

## 10. Suggested screen → endpoint map

| Screen | Endpoints |
|---|---|
| **Public price board** | `/commodities/`, `/markets/`, `/prices/latest` |
| **Price detail + chart** | `/prices/historical`, `/forecasts`, `/sale-window/` |
| **Farmer home ("what should I do?")** | `/sale-window/?commodity_id=&lang=`, `/lots/` |
| **My lot detail** | `/lots/{id}`, `/lots/{id}/advice`, `/lots/{id}/ledger` |
| **Find buyers** | `/lots/{id}/matches`, `/buyers/` |
| **Offer inbox** | `/offers/` (farmer: `user_id` replies; buyer: own bids) |
| **Payment tracking** | `/payments/` + `PATCH …/paid|failed|disputed` |
| **Transparency / ledger** | `/lots/{id}/ledger` |
| **Logistics booking** | `/logistics/`, `/logistics/bookings` |
| **Cold storage booking** | `/storage/facilities`, `/storage/bookings` |
| **Price alerts** | `/alerts/` |
| **Raise a dispute** | `/grievances/` |
| **Buyer onboarding** | `/buyers/register` |
| **Buyer supply discovery** | `/buyers/{id}/supply` |
| **FPO pooling** (role-gated) | `/lots/aggregate` |
| **Admin console** | `/api/v1/admin/*`, `/dashboard` |

### i18n

Three languages, driven by data, not code: `commodity_name_en|mr|hi` on price rows, `action_label` on advice, and `?lang=en|mr|hi` on `/sale-window/` and `/lots/{id}/advice`. Default every request's `lang` from `me.preferred_language` (which defaults to `mr` for new farmers).

### Auth token refresh

`decode_access_token` requires `exp`. Supabase access tokens are short-lived — use `supabase.auth.onAuthStateChange` to refresh, and retry once on **401** before bouncing to login. A 401 mid-demo because the token expired silently is a common self-inflicted wound.

---

## 11. Pre-demo checklist

- [ ] Your origin is in `CORS_ORIGIN` and you are calling the right base URL
- [ ] You use the **same** Supabase project as the backend (issuer must match)
- [ ] `import asyncio` fix is live (9.1) if you touch SMS
- [ ] `buyer_register` field fix is live (9.2) if you demo buyer matching
- [ ] An FPO account is seeded via SQL (9.3) if you demo pooling
- [ ] Response types are hand-written from section 8 — no OpenAPI codegen (9.4)
- [ ] Error renderer handles `detail` as **both** string and array (section 6)
- [ ] Empty states exist for: null `arrival_qty`, null `best_buyer`, null `next_step`, 404 sale-window, empty `matches`
- [ ] No infinite scroll / paging UI (9.9)
- [ ] Chart/price widgets show an "as of" timestamp and poll no faster than every 5 min
- [ ] Debounced autocomplete — the global limit is 120 req/min/IP (section 7)
