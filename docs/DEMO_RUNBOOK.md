# Demo Runbook — Krishi Bazaar (judge demo)

One page to run the demo without surprises. Read the **TL;DR**, do the **pre-flight**
the night before, then follow **Plan A (live)** or **Plan B (mock fallback)**.

- Anticipated judge questions: [`JUDGE_QA.md`](JUDGE_QA.md)
- Honest accuracy status: [`accuracy_card.md`](accuracy_card.md)
- Architecture / security model: [`ARCHITECTURE.md`](ARCHITECTURE.md), [`SECURITY_MODEL.md`](SECURITY_MODEL.md)
- Backend smoke (public endpoints): [`DEMO.md`](DEMO.md)

---

## 0. TL;DR — the 3-minute story

**"A farmer in Nashik opens the app in Marathi, sees today's onion price and a clear
Sell / Hold / Wait call, lists their produce, and gets matched to a verified local
buyer — offer, payment, and a transparent ledger — with an SMS price alert on the side."**

Click path (PWA, Marathi default):

1. `/setup` — pick language (मराठी), crop (Onion / कांदा), mandi (Lasalgaon). 3 taps.
2. `/` (Today) — modal price, **verdict** (थांबा / विका …) with a one-line reason,
   the 7-day forecast band, and other mandis' prices.
3. `/c/onion/m/lasalgaon` — pair detail: ranges 7d–1y, forecast method label.
4. Sign in → `/sell/new` — list 20 qtl → `/sell/$lotId` — **advice** (verdict + best
   verified buyer) → **matches** → make an offer → accept → **payment** → **ledger**.
5. `/alerts` — set an SMS price alert ("text me when onion ≥ ₹2400").
6. Buyer side: `/buy` — register → admin verifies → supply + offer.
7. SMS: admin simulates an inbound **"PYAJ"** → reply with modal price + verdict.

Then hand the mic to the architecture story (RLS, LLM-never-predicts-a-number,
honest accuracy card). See §5 for one-liners per screen.

---

## 1. Pre-flight (do this the night before, re-run T-30 min)

- [ ] **CI is green** — `git pull`, then confirm the base suite is clean:
      ```bash
      python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
      RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 pytest -q          # expect: all pass (db/live tests skip)
      ruff check .
      ```
- [ ] **Frontend builds** — `cd web && npm ci && npm run typecheck && npm test && npm run build`
- [ ] **Rehearse the journey** (see §3c / §4). Fix anything red **before** demo day.
- [ ] **Charge the phone / have a second device** — the PWA is mobile-first at 360px.
- [ ] **Warm the Supabase project** (first cold query can be slow) — hit `/health` and one read.

---

## 2. Plan A — Live Supabase (the real thing)

### 2a. Backend

```bash
cp .env.example .env         # fill the REQUIRED keys below; never commit .env
python scripts/apply_migrations.py      # or: make db-apply   (applies 001..037)
```

Required `.env` keys (the app **fails closed** at startup if any are missing):

| Key | Notes |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | your project |
| `SUPABASE_JWT_SECRET` | project JWT secret — must match or **every** authed call 401s |
| `SUPABASE_JWT_ISSUER` | `https://<ref>.supabase.co/auth/v1`. Set it to match, or leave empty (issuer not checked). A wrong value 401s everything. |
| `DATA_GOV_IN_API_KEY` | mandi ingest |

Seed + boot:

```bash
python seed.py                                   # loads data/gov_prices.csv
python scripts/refresh_seed_dates.py --in-place  # see §2b — makes the data "recent"
python seed.py                                   # re-seed with today's dates
RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 APP_ENV=development \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> `APP_ENV=development` keeps `/docs` on and skips the production-only startup
> invariants (issuer/RLS/HMAC). Fine for a demo; do **not** ship this way.

### 2b. Freshness gotcha — the CSV snapshot is stale (flagship feature 404s)

`sale-window` (Sell/Hold/Wait) only serves prices from the **last 15 days**
(`notifications/sale_window.py`), else **404**. The committed `data/gov_prices.csv`
is a fixed snapshot; days/weeks later it is outside that window and the most
important screen shows nothing.

```bash
python scripts/refresh_seed_dates.py --dry-run    # preview the shift
python scripts/refresh_seed_dates.py --in-place   # re-date to today, then re-run seed.py
git checkout -- data/gov_prices.csv               # restore the original snapshot anytime
```

> **Caveat — forecast band needs history.** The CSV is a *single-day* snapshot
> (all rows share one date), so it gives sale-window a price but **no multi-day
> history** for the 7-day forecast band. If you want the band live, run the
> forecast/backfill job against real history (`POST /api/v1/admin/forecast/run`,
> see [`FORECASTING.md`](FORECASTING.md)), ingest several days, **or** demo the band
> from the mock (Plan B), which ships 120 days of history + 7-day forecasts.

### 2c. Frontend — live auth (THE gotcha, verified)

`web/.env.development` ships `VITE_DEV_AUTH=1` → the sign-in screen shows mock
"Farmer / Buyer / FPO" buttons whose tokens the **real backend rejects (401)**.

> **Verified with Vite's own `loadEnv`:** `.env.development` **wins over**
> `.env.local`. Creating `.env.local` does **not** switch to live auth. You must
> create **`web/.env.development.local`** (it is gitignored via `*.local`).

```bash
cd web
cat > .env.development.local <<'EOF'
VITE_DEV_AUTH=0
VITE_SUPABASE_URL=https://<your-project-ref>.supabase.co
VITE_SUPABASE_ANON_KEY=<anon key>
EOF
API_TARGET=http://127.0.0.1:8000 npm run dev      # http://localhost:5173
```

Same Supabase project as the backend, or FastAPI rejects the tokens.

### 2d. Verify before you present

```bash
# mint a real farmer JWT (see README "Auth"), then:
python demo/journey_rehearsal.py --token <FARMER_JWT>     # walks the whole flow; exit 0 == good
python demo/live_smoke.py                                 # public endpoints health
```

---

## 3. Plan B — Offline mock fallback (guaranteed to work)

If the live backend or network is flaky, the PWA runs against a stateful,
zero-dependency mock with 120 days of history, forecasts, buyers, and dev tokens.
**One variable switches targets — no code change.**

```bash
# terminal 1 — mock API on :8000
python3 frontend_handoff/mock/mock_api.py --port 8000

# terminal 2 — frontend; make sure the live-auth override is ABSENT
rm -f web/.env.development.local          # so .env.development VITE_DEV_AUTH=1 applies
cd web && API_TARGET=http://127.0.0.1:8000 npm run dev
```

Sign in with the on-screen **Farmer / Buyer / FPO** buttons (mock dev tokens).
Verify first:

```bash
python demo/journey_rehearsal.py           # auto-mints dev tokens against the mock
```

Mock truth table for judges: [`frontend_handoff/mock/MOCK.md`](../frontend_handoff/mock/MOCK.md).

---

## 4. The demo script — screen by screen (what to say)

| # | Screen | Say this |
|---|---|---|
| 1 | `/setup` | "Three taps: language, crop, mandi. Marathi first — this is for the farmer, not the office." |
| 2 | `/` Today | "Today's modal price and a plain call — **Hold**, with the reason and the forecast band. Same data an SMS can carry." |
| 3 | Pair detail | "Ranges from a week to a year. The forecast **method** is labelled honestly from the API — we never print a made-up number." |
| 4 | `/sell/new` | "List 20 quintals. The advice names the **best verified local buyer** and the next step (book transport / storage)." |
| 5 | Matches → offer | "Buyers ranked by fit. Make an offer, accept it — the lot moves open → offered → matched, forward-only." |
| 6 | Payment → ledger | "Record the payment, then the **ledger**: every step is a transparent, append-only record — the SIH 'trust' outcome." |
| 7 | `/alerts` | "An SMS price alert. Set a threshold; the farmer just texts back." |
| 8 | `/buy` + admin | "A buyer registers and waits for verification — an admin approves. Verified buyers only." |
| 9 | SMS `PYAJ` | "Admin simulates an inbound 'PYAJ' → reply with modal price + verdict. A farmer gets this on a ₹2000 phone." |
| 10 | Architecture | "RLS at the DB boundary, ACID RPCs for writes, rate limiting, HMAC webhooks. **The LLM never predicts a number** — it only extracts structured events fed to classical models." |

Keep it to the screens that matter; do not click around live. If a screen is slow,
**switch to Plan B and keep talking** — the story is identical.

---

## 5. If it breaks — recovery

| Symptom | Likely cause | Fix |
|---|---|---|
| PWA sign-in shows Farmer/Buyer/FPO buttons on live | `VITE_DEV_AUTH=1` still active | create `web/.env.development.local` with `VITE_DEV_AUTH=0` (§2c) |
| Every authed call → **401 invalid token** | JWT secret/issuer mismatch, or wrong Supabase project | check `SUPABASE_JWT_SECRET`; set `SUPABASE_JWT_ISSUER` to the project URL or leave empty; frontend must use the same project |
| `sale-window` → **404** | no price in last 15 days | `refresh_seed_dates.py --in-place` + `seed.py`, or run ingestion (§2b) |
| Forecast band empty / method `none` | <1 day of history for the pair | run forecast job / ingest history, or demo the band from the mock (§2b caveat) |
| `500` on any call | see backend logs (structlog JSON on stdout) | read the `unhandled_exception`/`postgrest_error` line; usually missing RPC/migration |
| `429` mid-demo | rate limiting on | it's `RATE_LIMIT_ENABLED=1`; back off, or restart with `RATE_LIMIT_ENABLED=0` |
| App won't start | missing required `.env` key | startup fails closed with the exact key name — fill it |
| Live is flaky | network / cold Supabase | **switch to Plan B** and continue |

---

## 6. Things to have ready (not on screen, but judges ask)

- Why Supabase, why not custom → [`JUDGE_QA.md`](JUDGE_QA.md) §1
- "Is your accuracy real?" → the walk-forward backtest harness + the honest
  [`accuracy_card.md`](accuracy_card.md) ("not measured yet" — we refuse to invent a number)
- "What stops scraping farmers?" → RLS isolation + cross-tenant canary tests (§5)
- "How does this scale?" → single-worker by design today; Redis for job locks to
  go multi-replica (§6)
- Known limitations → README "Known Limitations" + [`SCALING.md`](SCALING.md)
