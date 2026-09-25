# QA — Open Items That Need Your Environment (handoff)

Issues/risks found during the QA pass that **cannot be fixed or verified in the
sandbox** (no Postgres/Docker, no live Supabase, no physical device, no native
Marathi/Hindi speaker). Each has a ready-to-paste prompt for your agent or dev.

| # | Item | Area | Severity | Blocked by |
|---|------|------|----------|-----------|
| 1 | Real-Postgres layer unverified (RLS / RPCs / invariants) | Backend | **High** | No Postgres/Docker here |
| 2 | Live demo data stale → sale-window 404 / empty forecast band | Backend/Data | **High** | Needs your live Supabase |
| 3 | `GET /api/v1/buyers/me` missing (G12) | Backend+FE | Medium | Needs a migration on your live DB |
| 4 | Buyer can't list their own offers | Backend+FE | Low-Med | Needs backend + RLS change, verified live |
| 5 | Marathi/Hindi strings are machine-drafted | i18n | **High (Marathi-first demo)** | Needs a native speaker |
| 6 | No real-phone visual/perf pass | Frontend | Medium | Needs a physical device |
| 7 | `@vitest/mocker` dev-only advisory | Tooling | Low (dev-only) | Breaking upgrade; deferred pre-demo |

Already fixed in this repo (for reference): 2 frontend edge bugs (`changePct`
Infinity, `selectLatestRun` timestamp poisoning) + matching-engine/validator/edge
test coverage. Live-auth setup (`VITE_DEV_AUTH` / `.env.development.local`) is an
operational step — see `docs/DEMO_RUNBOOK.md` §2c.

---

## 1 — Verify the real-Postgres layer (RLS / RPCs / invariants) — HIGH
**Why here is impossible:** this sandbox has no Postgres or Docker, so the
`pytest -m db` layer (RLS policies, SECURITY DEFINER RPCs, marketplace atomicity in
migrations 008/012/013/031/032/036) only runs in CI's `test-db` job or against your
live project. A broken RPC/RLS surfaces as a 500 on stage.

**Prompt:**
```
Verify the real-Postgres layer for Krishi Bazaar (the sandbox has no Postgres).
1. Local: start postgres 16, `python scripts/apply_migrations.py` (or `make db-apply`),
   then `RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 pytest -m db -q` and
   `pytest tests/test_privileges.py tests/test_db_rpc.py -q`. Report pass/fail per group.
2. Against the LIVE Supabase project (valid .env): `python scripts/test_db.py` and
   `python demo/reconcile.py`.
3. For any failure, quote the exact assertion/RPC error and the migration file it points
   to. Fix in the migration or the RPC, then RE-RUN the cross-tenant canaries
   (tests/test_rls_guard.py, tests/test_privileges.py) — never weaken RLS to make a
   test pass. Keep `ruff check .` and the offline `pytest -q` green.
Deliverable: green db group + live reconcile, or the minimal fix for the real failure.
```

## 2 — Make live demo data fresh (sale-window + forecast history) — HIGH
**Why here is impossible:** it runs against your live Supabase. The committed
`data/gov_prices.csv` is a fixed snapshot; `sale-window` only serves prices within the
**last 15 days**, so on a later date it 404s. It's also a **single-day** snapshot, so the
7-day forecast band has no history. (Helper `scripts/refresh_seed_dates.py` already
exists in-repo; running it + re-seeding is a live action.)

**Prompt:**
```
Make the live Supabase demo data fresh so the flagship sale-window returns a verdict and
the forecast band has history.
1. From repo root with a valid .env: `python scripts/refresh_seed_dates.py --in-place`
   then `python seed.py` (re-dates the CSV so the newest arrival is today).
2. Build forecast history: run the forecast job (`POST /api/v1/admin/forecast/run` with an
   admin token) or backfill several days, then confirm
   `GET /api/v1/forecasts?commodity_id=<onion>&market_id=<lasalgaon>` returns >=10
   observations for the pair.
3. Verify: `curl ".../api/v1/sale-window/?commodity_id=<onion>&market_id=<lasalgaon>&lang=mr"`
   returns action in {SELL_NOW,HOLD,WAIT} (NOT 404) and the chart draws a band.
Report the final action + forecast method, and any pair still returning 404.
```

## 3 — Implement `GET /api/v1/buyers/me` (G12) — MEDIUM
**Why here is impossible:** needs a migration + RLS policy applied to your live DB and
verified live; I won't ship an untested migration pre-demo. (Not a live-demo blocker —
the buyer only loses their profile if they clear the browser.)

**Prompt:**
```
Implement the missing "my buyer profile" endpoint (frontend gap G12).
Backend: add `GET /api/v1/buyers/me` in app/routers/buyers.py returning the caller's own
buyer profile (resolve by auth.uid()); 404 if none. Add migration `0XX_buyers_me.sql` +
RLS policy ONLY if the current schema can't express it; a buyer must see only its own row.
Mirror the existing RLS test style (tests/test_rls_guard.py) with a cross-tenant canary.
Contract: update frontend_handoff/API_CONTRACT.md and frontend_handoff/mock/mock_api.py.
Frontend: in web/src/features/buy, re-fetch via /buyers/me after register instead of
trusting a device-stored id; add the endpoint to web/src/api.
Gates: `pytest -q`, `ruff check .`, `cd web && npm run typecheck && REQUIRE_MOCK=1 npm test && npm run build` all green.
```

## 4 — Let a buyer list the offers they made — LOW-MED
**Why here is impossible:** backend scoping + RLS change that must be verified against the
real DB.

**Prompt:**
```
Scope GET /api/v1/offers/ so a buyer also sees offers THEY made (today it returns only
lots the caller owns). In app/routers/offers.py, additionally return offers whose buyer_id
resolves to the caller's buyer profile — without leaking other users' rows. Extend RLS if
needed and add a cross-tenant test. Mirror in frontend_handoff/mock/mock_api.py and surface
"my bids" in web/src/features/buy. Keep all gates green.
```

## 5 — Native review of Marathi/Hindi copy — HIGH (Marathi-first demo)
**Why here is impossible:** I'm not a native Marathi/Hindi speaker and can't validate
agricultural terminology or tone. The strings are machine-drafted
(`web/scripts/translations.py` → `web/src/i18n/locales/*/messages.po`), and Marathi is the
default language for the farmer demo.

**Prompt:**
```
Native-speaker review of the Marathi (default) and Hindi UI strings before the farmer demo.
Review every string in web/src/i18n/locales/{mr,hi}/messages.po (source drafts in
web/scripts/translations.py) for: correct mandi/agri terminology (कांदा, गोदाम, खरेदी,
ऑफर, पेमेंट…), a natural farmer-facing tone, and intact placeholders ({price}, {n}, {days}).
Change copy only — no logic. Then `cd web && npm run i18n:check` and commit the compiled
catalogs. Flag any English source string that is itself ambiguous and needs a product decision.
```

## 6 — Real-phone visual + performance pass — MEDIUM
**Why here is impossible:** rendering has only been checked in jsdom; no physical device
or browser here.

**Prompt:**
```
Real-device QA on a mid-range Android at 360px + Chrome.
Walk the journey: /setup, /, /c/$crop/m/$market, /bhav, /sell, /sell/new, /sell/$id,
/alerts, /buy, /account. Check: 48px touch targets, no horizontal scroll, correct Devanagari
rendering, verdict is the ONLY coloured element, skeleton/empty/offline states, and that
motion respects Settings > Remove animations (prefers-reduced-motion). Run against the
offline mock (frontend_handoff/mock/mock_api.py) to confirm the fallback. Report per-screen
screenshots + any layout/motion/perf issue with device + screen.
```

## 7 — `@vitest/mocker` dev-only advisory — LOW (optional, post-demo)
**Fixable here but deferred:** the fix is a breaking `vitest@4→5` bump; not worth the
regression risk before the demo. It's a dev/test dependency only (doesn't ship; CI audits
Python deps, not npm).

**Prompt:**
```
(Optional, post-demo, on a throwaway branch.) Clear the dev-only npm advisory:
`cd web && npm i -D vitest@latest @vitest/*@latest`, fix any test-API changes, then
`npm run typecheck && REQUIRE_MOCK=1 npm test && npm run build`. Merge only if the full
suite + build stay green; otherwise revert. Does not affect the shipped app.
```
