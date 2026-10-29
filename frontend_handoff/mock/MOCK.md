# Mock API

A single-file, zero-dependency, **stateful** fake of the Krishi Bazaar API, so you can build the frontend without a backend.

## Run it

```bash
python3 mock_api.py                  # http://localhost:8000
```

### Flags

| Flag | Default | Purpose |
|---|---|---|
| `--port N` | `8000` | Port to listen on |
| `--host H` | `0.0.0.0` | `0.0.0.0` lets you test from a phone on the same Wi-Fi |
| `--delay S` | `0` | Artificial latency added to every response (e.g. `--delay 0.4`) |
| `--quiet` | off | Suppress per-request logging |

You need **Python 3.8+**. No `pip install`. The standard library is all it uses.

---

## How faithful is it?

### Faithful to the real API
- Every URL, query param, request body field and response field name
- Status codes: 400 / 401 / 403 / 404 / 409 / 422 / 500
- The `{"detail": ...}` error shape — **including the two different forms** (array for validation, string for business errors)
- State machines: lot status monotonicity, offer TTL, payment → lot `sold`, booking transitions
- Enums: grades, actions, statuses, categories, languages
- `expires_at` computed as `created_at + 48h`
- 404 (not 403) when you request a lot you don't own
- Capacity validation on logistics (409) and storage (400) — **deliberately different, like the real API**

### Fake
- Prices and forecasts are a seeded random walk. Deterministic across restarts.
- DirectLink economics reuse the repository's pure `direct/` engine, so rupee,
  fair-price, planning, and group-buy numbers are not hand-written fixtures.
- Auth is not verified. See below.
- Everything is in memory and resets when you restart.

### DirectLink routes

The mock implements the full `/api/v1/direct/*` surface. The pure calculation
routes (`config`, `rupee`, `fair-price`, `plan`, and `group-buy`) execute the same
standard-library engine as the real backend. Commit/read-back uses an in-memory
store and requires a mock bearer token; unknown trace tokens return 404 and the
impact route returns the current in-memory aggregate.

---

## Dev helpers (mock only — not in the real API)

| Endpoint | Purpose |
|---|---|
| `GET /__dev/token?role=farmer&sub=<id>` | Mint a JWT-shaped token. Returns `authorization_header` ready to paste |
| `GET /__dev/reset` | Reset all in-memory state to the seeded baseline |
| `GET /__dev/routes` | List every implemented route (62) |

### Dev query params (any request)

| Param | Effect |
|---|---|
| `?__status=500` | Force that HTTP status — **use this to build your error states** |
| `?__delay=1.5` | Sleep this many seconds before responding |

```bash
# Force a 503 to see your retry banner
curl "http://localhost:8000/api/v1/markets/?__status=503"
```

---

## Auth

Any `Authorization: Bearer <anything>` is accepted. Pick a role two ways:

```bash
# 1. Dev header (simplest)
curl -H "X-Dev-Role: admin" -H "X-Dev-User: me" http://localhost:8000/api/v1/admin/buyers

# 2. JWT-shaped token (closer to production)
TOKEN=$(curl -s "http://localhost:8000/__dev/token?role=farmer" | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/me/
```

Defaults to `user-farmer-0001` (role `farmer`, `preferred_language: "mr"`) when nothing is sent.

### Roles you can assume

| Role | Token | Can access |
|---|---|---|
| `farmer` | default | lots, offers, payments, grievances, bookings, alerts, `/me/` |
| `fpo` | `?role=fpo` | the above + `POST /lots/aggregate` |
| `admin` | `?role=admin` | everything, including `/api/v1/admin/*` and `/dashboard/api/*` |

A `farmer` token hitting an admin route correctly returns **403**.

---

## Switching to the real backend

Change one environment variable — no code change:

```bash
# .env.local
VITE_API_BASE_URL=http://localhost:8000          # mock
# VITE_API_BASE_URL=https://<real-backend-url>   # integration
```

Then check:

1. Your origin is in the backend's CORS allowlist (it's an explicit list, not `*`).
2. You're signed in against the **same Supabase project** as the backend — the token issuer must match.
3. `/docs` may be disabled on the real backend in production. Don't depend on it.

---

## Extending the seed data

All fixtures live in the top of `mock_api.py`:

- `MARKETS` — 5 Nashik APMCs
- `COMMODITIES` — Onion, Tomato, Soybean, Maize (with `name_en` / `name_mr` / `name_hi`)
- `seed_store()` — generates 120 days of prices + 7 days of forecasts + buyers, facilities, logistics options

State lives in the `STORE` dict. Add to it in `seed_store()` and it's immediately available at the endpoints.

---

## Known differences from production

| | Mock | Real |
|---|---|---|
| Price data | seeded random walk | government mandi feed, ~6h cadence |
| Token verification | none | HS256 JWT, issuer + audience checked |
| Persistence | in-memory | Supabase Postgres with row-level security |
| `/api/v1/sms/webhook` | not implemented (returns 404) | HMAC-protected machine endpoint |
