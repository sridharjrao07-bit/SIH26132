# Krishi Bazaar API — Frontend Contract

Everything you need to build the UI. **No backend repo access required.**

| | |
|---|---|
| **Base URL (dev)** | `http://localhost:8000` — the mock server in `mock/` |
| **Base URL (integration)** | Supplied by the backend owner |
| **API prefix** | `/api/v1` on every business endpoint |
| **Not under the prefix** | `/health`, `/readyz`, `/metrics`, `/dashboard*` |
| **Content type** | `application/json` |
| **Auth** | `Authorization: Bearer <supabase_access_token>` |
| **Types** | `types/api-types.ts` — import it, don't retype |

> Sections **9 (Traps)** and **11 (Checklist)** are the ones that will cost you a day if you skip them.

---

## 1. Auth

The backend **does not issue tokens**. Supabase Auth does. You sign in with the Supabase JS client and forward the access token as a bearer token.

```ts
const { data: { session } } = await supabase.auth.signInWithPassword({ email, password });

fetch(`${API}/api/v1/me/`, {
  headers: { Authorization: `Bearer ${session.access_token}` },
});
```

### Rules

| Rule | Consequence for you |
|---|---|
| Token must carry `exp`, `sub`, `aud` | Missing/malformed → **401** |
| `aud` must be `"authenticated"` | Supabase default — don't hand-roll tokens |
| `iss` must match the backend's project | **You must use the SAME Supabase project as the backend.** A different project's tokens are rejected |
| Algorithm is HS256 (legacy JWT secret) | If the backend project migrates to asymmetric signing keys, tokens break. Flag this early |
| **Role is read from the database, not the token** | You cannot self-elevate. Don't try |
| `sub` = the user id | `session.user.id` is the id everywhere |

### Roles

| Role | How it's assigned | Self-service? |
|---|---|---|
| `farmer` | Automatically on signup | ✅ default |
| `buyer` | `POST /api/v1/buyers/register` → `verified: false` | ✅ but needs admin approval |
| `fpo` | Provisioned by the backend team (SQL) | ❌ **cannot be self-created** |
| `admin` | Provisioned by the backend team (SQL) | ❌ never expose admin UI |

**Your signup flow can only ever produce a farmer.** Buyer onboarding is an explicit second step. Detect `fpo` / `admin` from `GET /api/v1/me/` and show/hide features — never try to create them.

```ts
const me = await api.get<UserProfile>("/api/v1/me/");
const isAdmin = me.role === "admin";
const isFpo = me.role === "fpo";
```

---

## 2. Environments, CORS, and running the mock

### Run the mock (no backend needed)

```bash
cd mock
python3 mock_api.py                # http://localhost:8000
python3 mock_api.py --port 4000
python3 mock_api.py --delay 0.4    # simulate latency
```

It is stateful — create a lot, make an offer, pay for it, and the ledger reflects all of it. See `mock/MOCK.md` for the dev helpers (`/__dev/token`, `/__dev/reset`, `?__status=500` to force errors).

### Switching to the real backend

One environment variable, no code change:

```bash
# .env.local
VITE_API_BASE_URL=http://localhost:8000          # mock
# VITE_API_BASE_URL=https://api.example.gov.in   # real
```

### CORS

- The origin allowlist is **explicit** — wildcards are not used (`allow_credentials=true`).
- Send your dev origin (`http://localhost:3000`, `:5173`, …) to the backend owner to be added.
- A disallowed origin gets **no** `Access-Control-Allow-Origin` header at all. You'll see a generic browser CORS error, not a 4xx. **This is the #1 false alarm** — check the allowlist before debugging your fetch.

### Interactive API docs

`/docs` is enabled in development but **returns 404 when the backend runs in production**. Don't build anything that depends on it.

---

## 3. Endpoint access matrix

Decides your app shell: what works logged-out vs logged-in.

### 🟢 Public — no token

| Method | Path | Query |
|---|---|---|
| GET | `/api/v1/markets/` | `district`, `active_only=true` |
| GET | `/api/v1/markets/nearby` | **required** `lat`, `lng`; `radius_km` (max 500) |
| GET | `/api/v1/commodities/` | — |
| GET | `/api/v1/prices/latest` | `market_id`, `commodity_id`, `limit` (1–500) |
| GET | `/api/v1/prices/historical` | **required** `market_id` + `commodity_id`; `days` (1–365), `limit` (1–1000) |
| GET | `/api/v1/forecasts` | **required** `market_id` + `commodity_id`; `days` (1–7) |
| GET | `/api/v1/forecasts/summary` | — |
| GET | `/api/v1/sale-window/` | **required** `commodity_id`; `market_id`, `lang` |
| GET | `/api/v1/buyers/` | `district`, `commodity_id`, `verified_only=true` |
| GET | `/api/v1/logistics/` | `district`, `kind` |
| GET | `/api/v1/storage/facilities` | `district` |
| GET | `/health`, `/readyz`, `/metrics` | — |

**Build price discovery as a fully public surface.** It's where the demo lands hardest.

### 🔐 Authenticated — bearer token

| Method | Path | Who |
|---|---|---|
| GET · PATCH | `/api/v1/me/` | any user |
| POST · GET | `/api/v1/lots/` | farmer / FPO |
| GET | `/api/v1/lots/{id}` · `/{id}/advice` · `/{id}/matches` · `/{id}/ledger` | **lot owner or its FPO only** |
| PATCH | `/api/v1/lots/{id}/grade` · `/{id}/withdraw` | lot owner |
| POST | `/api/v1/lots/aggregate` | role `fpo` |
| POST · GET | `/api/v1/offers/` · PATCH `/offers/{id}` | participants |
| POST · GET | `/api/v1/payments/` · PATCH `/{id}/paid\|failed\|disputed` | participants |
| POST · GET | `/api/v1/grievances/` | any user |
| POST · GET | `/api/v1/logistics/bookings` · PATCH `/{id}` | booking owner |
| POST · GET · PATCH | `/api/v1/storage/bookings` | booking owner |
| POST · GET · PATCH · DELETE | `/api/v1/alerts/` | alert owner |
| POST | `/api/v1/buyers/register` | any user |
| GET | `/api/v1/buyers/{id}/supply` | authenticated |
| — | `/api/v1/admin/*` | role `admin` |

---

## 4. The five journeys

### 4.1 Farmer: onboard → list → advice → sell

```
1. Sign up (Supabase Auth)            → role=farmer, automatically
2. PATCH /api/v1/me/                  { name, phone, preferred_language, district, lat, lng }
3. POST  /api/v1/lots/                { commodity_id, quantity_qtl, grade, asking_price }
4. GET   /api/v1/lots/{id}/advice     → action + reason + next_step + best_buyer   ← THE PRODUCT
5. GET   /api/v1/lots/{id}/matches    → ranked buyers
6. POST  /api/v1/offers/              48h TTL
7. PATCH /api/v1/offers/{id}          { status: "accepted" | "rejected" }
8. POST  /api/v1/payments/            { offer_id, amount, reference }
9. PATCH /api/v1/payments/{id}/paid   → closes the lot atomically
10. GET  /api/v1/lots/{id}/ledger     → full audit timeline
```

Step 4 is not a price dump. It returns an action, a **localised** reason, a next step, and the best local verified buyer. Design your main farmer screen around it.

### 4.2 Buyer: register → verified → browse supply

```
1. Sign up + PATCH /api/v1/me/
2. POST /api/v1/buyers/register       → verified=false (admin must approve)
3. GET  /api/v1/buyers/{id}/supply    → open lots fitting this buyer's demand
4. POST /api/v1/offers/               → bid on a lot
```

Surface a **"pending verification"** state. Unverified buyers never appear in farmer matching.

### 4.3 Price discovery (public)

```
GET /api/v1/commodities/                                          crop picker (en/mr/hi names)
GET /api/v1/markets/?district=Nashik                              mandi picker
GET /api/v1/prices/historical?market_id=X&commodity_id=Y&days=30  chart
GET /api/v1/prices/latest?commodity_id=Y&limit=50                 today's board
GET /api/v1/forecasts?market_id=X&commodity_id=Y&days=7           7-day forecast
GET /api/v1/sale-window/?commodity_id=Y&lang=mr                   Sell Now / Hold / Wait
```

### 4.4 Logistics & storage

```
GET  /api/v1/logistics/?district=Nashik&kind=transport    capacity_qtl + rate_per_qtl
POST /api/v1/logistics/bookings                           { lot_id, logistics_id, quantity_qtl }
GET  /api/v1/storage/facilities?district=Nashik
POST /api/v1/storage/bookings                             { lot_id, facility_id, quantity_qtl }
PATCH /api/v1/storage/bookings/{id}                        { status: "confirmed" }
```

Capacity is validated server-side. On **409**, render the message — it states available vs used.

### 4.5 Alerts

```
POST   /api/v1/alerts/      { commodity_id, threshold_price, condition: "gte"|"lte", expires_at? }
GET    /api/v1/alerts/      ?limit=50 (max 200)
PATCH  /api/v1/alerts/{id}  partial update
DELETE /api/v1/alerts/{id}
```

`market_id: null` resolves to the **nearest market** at check time. Delivery is **SMS only** — there is no in-app notification feed.

---

## 5. Vocabulary — render these exact values

### Sale action

| `action` | `action_label` (en) | Suggested UI |
|---|---|---|
| `SELL_NOW` | Sell Now | green / primary CTA |
| `HOLD` | Hold | amber |
| `WAIT` | Wait | grey |

`action_label` arrives **already localised** when you pass `?lang=`. Render it directly — do not build your own translation map.

| lang | sell | hold | wait |
|---|---|---|---|
| en | Sell Now | Hold | Wait |
| mr | आज विका | थोडे थांबा | थांबा |
| hi | आज बेचें | थोड़ा रुकें | रुकें |

### `reason_code` — stable, safe to branch on

| code | Meaning |
|---|---|
| `sell_no_storage` | Sell — heavy arrivals, no storage nearby |
| `sell_arrivals` | Sell — arrivals spiking |
| `sell_forecast` | Sell — forecast flat/down |
| `hold` | Hold — better price expected |
| `wait` | Wait — arrivals normal, no urgency |

### State machines

```
Lot       open → offered → matched → sold          (side exit: withdrawn)   BACKWARDS = 409
Offer     pending → accepted | rejected | expired    WRITE only accepted/rejected ("expired" → 422)
Payment   pending → paid | failed | disputed         paid also sets lot → sold, same transaction
Booking   requested → confirmed → completed          (or cancelled)  completed/cancelled are terminal
```

### Other enums

| Field | Values |
|---|---|
| `lots.grade` | `FAQ` · `General` · `Special` |
| `grievances.category` | `payment` · `quality` · `logistics` · `buyer` · `other` |
| `grievances.status` | `open` · `in_progress` · `resolved` · `rejected` |
| `buyers.type` | `trader` · `processor` · `institutional` · `fpo` · `digital` |
| `payment_reliability` | `high` · `medium` · `low` |
| `forecasts.confidence` | `high` · `medium` · `low` |
| `forecasts.status` | `ok` · `insufficient_data` · `stale` |
| `preferred_language` | `en` · `mr` · `hi` |

---

## 6. Errors

Every error is `{"detail": ...}`. Never a stack trace.

| Status | Meaning | UI action |
|---|---|---|
| **400** | Bad input / referenced record missing / booking qty > lot qty | Inline field error |
| **401** | Missing, invalid or expired token | Refresh session, retry once, else re-auth |
| **403** | Authenticated but wrong role | Hide the feature |
| **404** | Not found **or not yours** | Empty state — **not** "permission denied" |
| **409** | Invalid state transition / duplicate / capacity / cross-tenant | Show the message |
| **422** | Validation failed (Pydantic, or an invalid enum/id) | Field-level errors |
| **429** | Rate limited (120 req/min/IP) | Back off |
| **503** | Data store unavailable or a job failed | Retry-able banner |

### ⚠️ `detail` has TWO shapes

**Validation failures** (and some business errors) give an array:

```json
{ "detail": [ { "loc": ["body","quantity_qtl"],
                "msg": "Input should be greater than 0",
                "type": "greater_than" } ] }
```

**Most business errors** give a plain string:

```json
{ "detail": "invalid status" }
```

Your error renderer must handle **both**. `types/api-types.ts` exports `isValidationError()` and `errorMessage()` for exactly this — use them.

---

## 7. Rate limits and data freshness

| Limit | Value |
|---|---|
| Global | **120 requests / minute / IP** |
| `POST /api/v1/sms/webhook` | 30 / minute |

> **Debounce search-as-you-type.** A "type a district" autocomplete firing `/markets/` per keystroke will trip the limit mid-demo.

### Data is not live

No websocket, no SSE, no `ETag`, no `Last-Modified`. Ingestion is scheduled:

| Job | Cadence |
|---|---|
| Mandi prices | ~6 hours |
| Forecasts | ~6 hours |
| Alert checks | ~60 minutes |
| Offer expiry | on demand |

**Poll no faster than every 5 minutes**, and always show an "as of `<generated_at>`" timestamp. A live-ticking price widget is not possible — don't build one.

---

## 8. Response shapes

The full set of typed interfaces is in `types/api-types.ts`. The non-obvious ones:

**`PriceRecord`** — `arrival_qty` **may be null** (source didn't report it). `modal_price` is always Rs/quintal. `unit` is always `"quintal"`. Joined `market_name`, `district`, `commodity_name_{en,mr,hi}` are flattened for you.

**`Forecast`** — render the confidence band (`lower_bound`–`upper_bound`), not a bare line. `GET /forecasts` returns only `status: "ok"`; `GET /forecasts/summary` also returns `insufficient_data` so you can show *"not enough data yet"* instead of an empty screen.

**`SaleWindow`** — 404 when there's no recent price for the commodity. Design a real empty state. `better_market` is non-null only when a nearby mandi's modal price is **≥ 5% above** the local price; its shape is `{market, modal_price, premium_rs, arrival_qty}` (no `market_id` — see `notifications/sale_window.py`).

**`LotAdvice`** — **`next_step` may be null**, **`best_buyer` may be null**, **`sale_window` may be null**. Handle all three. `matches` is capped at 5 here, 10 on `/matches`.

**`LotLedger`** — `events` is a **pre-sorted, merged timeline**. Render it directly as a stepper.

**`MatchItem.reasons`** — machine codes (`same_district`, `price_covers_ask`, `volume_fit`, …). Map them to human labels; never render the raw code.

---

## 9. 🚨 Traps

### 9.1 Don't codegen a client from OpenAPI

Only 11 of 67 operations declare a response schema. Codegen gives you `any` almost everywhere — and the schemas that *do* exist **silently omit fields the API returns**:

| Model | Hides |
|---|---|
| `BuyerResponse` | `created_at`, `updated_at`, `owner_user_id`, `verification_state`, `review_notes` |
| `LotResponse` | `created_at`, `updated_at` |

**Use `types/api-types.ts`.** If you need `verification_state` to render "pending", take it from the admin endpoint — not from the register response.

### 9.2 Progressions are enforced — don't render impossible actions

- **Lot:** `open → offered → matched → sold`. A DB trigger rejects regressions. Never render "reopen".
- **Offer:** `PATCH /offers/{id}` accepts **only** `accepted` / `rejected`. `expired` is a valid *read* status and returns **422** if written.
- **Storage booking:** `PATCH` rejects `requested` and rejects any change from `cancelled`/`completed` (**409**).
- **Logistics booking:** a `completed` booking cannot change status (**409**).

### 9.3 Two different status codes for the same condition

Capacity exceeded returns **409** on `/logistics/bookings` but **400** on `/storage/bookings`. Handle both for "capacity full".

### 9.4 No search, no pagination

- **No free-text search anywhere.** Filter by `district` / `commodity_id` only.
- Lists are hard-capped server-side (lots 100, offers 100, payments 100, grievances 100, buyers 100, prices/latest ≤500, prices/historical ≤1000). There is **no** `offset`, **no** `cursor`, **no** `total`.
- **Do not build infinite scroll or "page 2".** Build filtered views instead.

### 9.5 Historical data needs an exact pair

`market_id` **and** `commodity_id` are both required on `/prices/historical` and `/forecasts`. There is no "all prices for onion" or "all commodities at Lasalgaon" history endpoint. Resolve both ids first from `/commodities/` and `/markets/`. For a top-level board, use `/prices/latest` (filterable by one) or `/forecasts/summary` (everything, deduped).

### 9.6 Advice and matches are owner-only

`/lots/{id}/advice` and `/lots/{id}/matches` return **404** for lots you don't own. A buyer-facing "inspect this lot" screen must use `/api/v1/buyers/{id}/supply` instead. **Build two different detail views** — don't reuse the farmer's lot screen for buyers.

### 9.7 FPO accounts cannot be created from the UI

`role='fpo'` is provisioned by the backend team, and `/lots/aggregate` requires it. Ask for a seeded FPO account if you're demoing pooling. Aggregation also requires **2–50 lots**, all `open`, all the same commodity.

### 9.8 `PATCH` semantics: omission ≠ null

`PATCH /api/v1/me/` and `/api/v1/alerts/{id}` treat an **omitted** field as "leave unchanged". An explicit `null` is a different intent — on `alerts.expires_at` it **clears the expiry**. Build forms that omit untouched fields rather than POSTing a full object full of nulls.

### 9.9 Don't build these — they don't exist

| Tempting feature | Reality |
|---|---|
| Real payment gateway / UPI | Statuses are recorded; settlement is **mocked** |
| Push / in-app notifications | Alerts are **SMS only** |
| Real-time price ticks | Scheduled ingestion, ~6h. No websocket/SSE |
| User avatars / file upload | Storage is for **cold-storage facilities**, not user media |
| Languages beyond en/mr/hi | `preferred_language` is a closed enum |
| Admin user management UI | Role assignment is backend-only, deliberately |
| Farmer ↔ buyer chat | No messaging. Offers + grievances are the channels |
| SMS send UI | `/sms/webhook` is machine-to-machine (HMAC), not for browsers |

---

## 10. Screen → endpoint map

| Screen | Endpoints |
|---|---|
| Public price board | `/commodities/`, `/markets/`, `/prices/latest` |
| Price detail + chart | `/prices/historical`, `/forecasts`, `/sale-window/` |
| Farmer home ("what should I do?") | `/sale-window/?commodity_id=&lang=`, `/lots/` |
| My lot detail | `/lots/{id}`, `/lots/{id}/advice`, `/lots/{id}/ledger` |
| Find buyers | `/lots/{id}/matches`, `/buyers/` |
| Offer inbox | `/offers/` |
| Payment tracking | `/payments/` + `PATCH …/paid\|failed\|disputed` |
| Transparency ledger | `/lots/{id}/ledger` |
| Logistics booking | `/logistics/`, `/logistics/bookings` |
| Cold storage | `/storage/facilities`, `/storage/bookings` |
| Price alerts | `/alerts/` |
| Raise a dispute | `/grievances/` |
| Buyer onboarding | `/buyers/register` |
| Buyer supply discovery | `/buyers/{id}/supply` |
| FPO pooling *(role-gated)* | `/lots/aggregate` |
| Admin console | `/api/v1/admin/*`, `/dashboard` |

### i18n

Three languages, **driven by data not code**: `commodity_name_{en,mr,hi}` on price rows, `action_label` on advice, and `?lang=` on `/sale-window/` and `/lots/{id}/advice`. Default every request's `lang` from `me.preferred_language` (new farmers default to `mr`).

### Token refresh

Tokens expire. Use `supabase.auth.onAuthStateChange` to refresh, and **retry once on 401** before bouncing to login. A silent mid-demo logout is a common self-inflicted wound.

---

## 11. Pre-demo checklist

- [ ] Your origin is in the backend's CORS allowlist
- [ ] You are pointed at the **same** Supabase project as the backend
- [ ] `VITE_API_BASE_URL` flips between mock and real with no code change
- [ ] Types come from `types/api-types.ts`, **not** OpenAPI codegen
- [ ] Error renderer handles `detail` as **both** string and array
- [ ] Empty states exist for: null `arrival_qty`, null `best_buyer`, null `next_step`, null `sale_window`, 404 sale-window, empty `matches`
- [ ] No infinite scroll / paging UI
- [ ] Price widgets show an "as of" timestamp; polling ≥ 5 min
- [ ] Autocomplete is debounced (120 req/min/IP)
- [ ] No "reopen lot" / "re-offer" / "page 2" / "chat" buttons
- [ ] 401 refresh-and-retry works
- [ ] FPO demo account requested from the backend team, if needed
