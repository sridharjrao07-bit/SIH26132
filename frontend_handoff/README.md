# Krishi Bazaar — Frontend Handoff

Everything the frontend team needs to build against the API **without access to the backend repository**.

```
frontend_handoff/
├── README.md              ← you are here
├── API_CONTRACT.md        ← the full API contract (read after this)
├── run.sh                 ← one command to start the mock API
├── mock/
│   ├── mock_api.py        ← zero-dependency stateful fake of the real API
│   └── MOCK.md            ← mock dev helpers and how to switch to the real API
├── types/
│   └── api-types.ts       ← hand-written TypeScript types (import these)
└── examples/
    └── curl-walkthrough.sh ← copy-paste smoke test of every journey
```

---

## 1. Start here — 60 seconds

You need **Python 3** (any version ≥ 3.8). Nothing else. No `pip install`, no Docker, no database, no API keys.

```bash
cd mock
python3 mock_api.py
```

Then open a second terminal:

```bash
curl "http://localhost:8000/api/v1/sale-window/?commodity_id=22222222-2222-2222-2222-222222222201&lang=mr"
```

You'll get a real recommendation with Marathi text. That is the shape and behaviour of the production API.

### Point your app at it

```bash
# .env.local
VITE_API_BASE_URL=http://localhost:8000
```

```ts
const API = import.meta.env.VITE_API_BASE_URL;
await fetch(`${API}/api/v1/markets/?district=Nashik`);
```

Switching to the real backend later is **one environment variable**. No code change.

---

## 2. What the mock gives you

It is a **stateful** fake of the real API, not a static fixture dump.

| You can | Because |
|---|---|
| Build a chart | 120 days of seeded price history per market × commodity (stable across restarts) |
| Show forecasts | 7-day forward predictions with confidence bands |
| Run the whole farmer journey | Create a lot → get advice → make an offer → accept it → pay → read the ledger. State persists for the session |
| Test error states | `?__status=500` forces any status. Real 400/401/403/404/409/422 come from real validation |
| Test auth flows | `/__dev/token?role=admin` mints a JWT-shaped token you can paste in |
| Test slow networks | `python3 mock_api.py --delay 0.4` |
| Test on your phone | Binds `0.0.0.0` — use your laptop's LAN IP |

### Faithful vs. fake

**Faithful** — every URL, query param, body field, response field name; all status codes and the `{"detail": ...}` error shape; the lot/offer/payment/booking state machines; every enum; the 48h offer TTL and `expires_at`.

**Fake** — prices are a seeded random walk, auth is not actually verified, and data resets on restart.

### Seed IDs you can hardcode

```ts
// Markets (all Nashik)
const LASALGAON  = "11111111-1111-1111-1111-111111111101";
const PIMPALGAON = "11111111-1111-1111-1111-111111111102";
const YEOLA      = "11111111-1111-1111-1111-111111111103";
const NASHIK     = "11111111-1111-1111-1111-111111111104"; // Nashik APCM
const MANMAD     = "11111111-1111-1111-1111-111111111105"; // Manmad APCM

// Commodities
const ONION   = "22222222-2222-2222-2222-222222222201";
const TOMATO  = "22222222-2222-2222-2222-222222222202";
const SOYBEAN = "22222222-2222-2222-2222-222222222203";
const MAIZE   = "22222222-2222-2222-2222-222222222204";

// Verified buyers
const AGRO_TRADERS = "66666666-6666-6666-6666-666666666601"; // scores 65
const SAHYADRI_FPO = "66666666-6666-6666-6666-666666666602"; // scores 80 (best)
const GODAVARI     = "66666666-6666-6666-6666-666666666603"; // tomato only
const RETAIL_CHAIN = "66666666-6666-6666-6666-666666666604"; // scores 20
const UNVERIFIED   = "66666666-6666-6666-6666-666666666605"; // hidden by default
```

The buyer list is deliberately **score-differentiated** (80 / 65 / 20) so you can verify your ranking and sort UI actually works.

### Auth in the mock

Any `Authorization: Bearer ...` is accepted. Two ways to pick a role:

```bash
# Simplest — dev headers (mock only)
curl -H "X-Dev-Role: admin" http://localhost:8000/api/v1/admin/buyers

# More realistic — mint a JWT-shaped token
curl "http://localhost:8000/__dev/token?role=farmer"
# → {"authorization_header": "Bearer eyJ...", ...}
```

Defaults to `user-farmer-0001` (role `farmer`, language `mr`) when nothing is sent.

---

## 3. Read these next, in order

| # | File | Why |
|---|---|---|
| 1 | **`API_CONTRACT.md` §3** | Public vs authenticated matrix — decides your app shell |
| 2 | **`API_CONTRACT.md` §4** | The five journeys as literal endpoint sequences |
| 3 | **`API_CONTRACT.md` §5** | The exact enum strings for every badge and colour |
| 4 | **`API_CONTRACT.md` §9** | 🚨 The traps. This section saves you a day |
| 5 | **`types/api-types.ts`** | Import it and delete any `any` you were about to write |
| 6 | **`API_CONTRACT.md` §6 + §8** | Error handling and the real response shapes |

---

## 4. The five things that matter most

### 4.1 Don't codegen from OpenAPI

Only **11 of 67** operations declare a response schema. `openapi-typescript` / `orval` will type almost everything `any` — and the few schemas that *do* exist silently omit fields the API returns (e.g. `BuyerResponse` hides `verification_state`, `owner_user_id`, `created_at`, `updated_at`).

**Use `types/api-types.ts`.** It's written from the real payloads.

### 4.2 Build price discovery as a public surface

12 endpoints need no token: `/markets/`, `/commodities/`, `/prices/*`, `/forecasts*`, `/sale-window/`, `/buyers/`, `/logistics/`, `/storage/facilities`. That's a logged-out landing page for free.

### 4.3 The product is `/lots/{id}/advice`, not the price chart

One call returns the action (`SELL_NOW` / `HOLD` / `WAIT`), a localised reason, a next step, and the best local verified buyer. Design the main farmer screen around it.

**Render `action_label` directly.** The backend already localises it into Marathi and Hindi. If you build your own translation map you will ship worse Marathi than the API already returns.

### 4.4 Don't build progressions the database rejects

Lot status is monotonic (`open → offered → matched → sold`); a trigger rejects backwards moves. A "reopen lot" button can only ever produce a 409. Same for writing `expired` to an offer (valid to *read*, 422 to *write*).

### 4.5 Handle null everywhere

`arrival_qty`, `best_buyer`, `next_step`, `sale_window`, and `expires_at` can all be `null`, and `/sale-window/` returns **404** when a commodity has no recent price. Empty states are not optional here — they're the difference between a demo that looks unfinished and one that looks considered.

---

## 5. Contract stability

This bundle describes the API as of the current backend build. Two defects have been fixed in the backend source, and **neither is a frontend concern** — but if your integration target is an older deployment, you may still see the old behaviour. The symptoms are listed so you can tell a stale backend apart from a genuine bug in your own code:

1. **`POST /api/v1/sms/webhook`** — older builds returned HTTP 500 on every valid request. It is a machine-to-machine endpoint protected by HMAC — **never call it from a browser**, fixed or not. For an SMS demo, ask the backend team about the admin `/api/v1/sms/simulate` endpoint.
2. **`POST /api/v1/buyers/register`** — older builds returned 201 while silently discarding 7 of the 11 fields (`commodity_id`, `demand_qty_qtl`, `max_price`, `quality_requirements`, `payment_reliability`, `lat`, `lng`). Build the form normally; if buyer↔lot matching looks weak on your target, this is the reason, not your payload.

Both are covered by regression tests now, so they cannot silently return. If you hit either symptom, do not work around it in the client — report it.

### Questions to send the backend team

- Your exact backend base URL for integration
- Confirmation your dev origin is in their CORS allowlist
- Confirmation you're on the **same Supabase project** (token issuer must match)
- A seeded **FPO** account, if you're demoing lot pooling
- Which backend build your integration target is running, so we know whether the two issues above apply

---

## 6. Bundle contents

| Path | What it is |
|---|---|
| `API_CONTRACT.md` | The contract: auth, endpoints, journeys, vocabulary, errors, traps, screen map |
| `mock/mock_api.py` | Runnable mock. 62 routes, stateful, zero dependencies |
| `mock/MOCK.md` | Dev helpers, CLI flags, how to point at the real API |
| `types/api-types.ts` | All request/response types + error helpers + optional typed fetch client |
| `examples/curl-walkthrough.sh` | Executable smoke test of every journey — run it to see real payloads |
| `run.sh` | Convenience launcher for the mock |
