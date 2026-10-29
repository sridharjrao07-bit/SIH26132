# Phase 1 architecture map

## Official SIH problem statement and scope

**Ministry of Consumer Affairs, Food & Public Distribution — Agriculture, FoodTech
& Rural Development — Software:**

> Multiple intermediaries reduce farmers earnings and increase consumer prices.

The requested demo entry point is the public PWA landing flow, with the flagship
demo path beginning at `/direct` and ending at the rendered consumer-rupee
breakdown and direct-trade comparison. The repository also contains the older
price-discovery and authenticated marketplace journeys, which remain in scope for
the later end-to-end audit. The acceptance test for every later phase is whether
the product demonstrably reduces intermediary absorption while improving the
farmer and consumer outcomes, without inventing unsupported accuracy or savings.

## Repository map

| Area | Location | Responsibility |
|---|---|---|
| FastAPI application | `app/main.py` | App construction, middleware, health/readiness/metrics, routers, exception handling |
| HTTP routes | `app/routers/` | Markets, commodities, prices, lots, profile, and DirectLink APIs |
| Request/response schemas | `app/schemas/` | Pydantic validation for market, price, marketplace, profile, and DirectLink payloads |
| Domain engines | `direct/`, `app/services/`, `forecasting/`, `notifications/`, `events/` | Pure DirectLink arithmetic, matching/marketplace logic, forecasts, sale-window/SMS jobs, event extraction |
| Database | `db/migrations/` | Supabase PostgreSQL schema, RLS policies, state-machine triggers, RPCs, DirectLink persistence |
| Ingestion | `ingestion/` | data.gov.in, Agmarknet, DCA retail, validation, and scheduled ingestion |
| PWA | `web/src/` | Vite/React/TanStack Router/React Query/Lingui UI and typed API client |
| Mock API | `frontend_handoff/mock/mock_api.py` | Stateful local API for legacy marketplace/price frontend tests on port 8000 |
| Demo assets | `data/`, `demo/`, `scripts/`, `docs/DEMO_RUNBOOK_DIRECTLINK.md` | Government snapshots, offline DirectLink demo, rehearsal/audit scripts, presentation runbook |
| Deployment | `Dockerfile`, `docker-compose.yml`, `vercel.json` | Single-worker FastAPI container and frontend deployment configuration |

## Entry points

- Backend: `app.main:app`; local command is `uvicorn app.main:app`.
- Frontend development: `web/package.json` → `npm run dev` → Vite on port 5173.
- Frontend production: `npm run build` → `web/dist/`.
- Mock backend: `npm run mock` → `frontend_handoff/mock/mock_api.py` on port 8000.
- DirectLink backend helper: `web/scripts/dev-backend.sh`, which starts FastAPI with
  valid JWT-shaped dummy Supabase values; the Windows README equivalent is a
  PowerShell environment setup plus `uvicorn`.
- Offline flagship demo: `demo/direct_channel_demo.py`; it imports the pure
  `direct/` engine and does not need Supabase, network, or API keys.

## Main demo data flow

```text
Browser /direct
  → TanStack Router → DirectPage
  → React Query rupeeQuery
  → web/src/api/endpoints/direct.ts
  → POST /api/v1/direct/rupee
  → app/routers/direct.py
  → direct/fair_price.py + direct/value_chain.py
  → calibrated chain stages
  → schemasDirect.ts validation
  → DirectPage + RupeeChainChart
  → farmer share, avoidable margin, real work, and direct-trade surplus
```

Default demo inputs are the published Lasalgaon onion anchors: farm ₹2,226/qtl
and retail ₹5,392/qtl. The direct screen also calls fair-price for the lane; plan,
group-buy, commit, trace, and impact are separate DirectLink capabilities exposed
by the backend and client service layer.

## Public price-discovery flow

```text
Browser /setup or /
  → language → crop → mandi preference
  → TodayPage / PairDetailPage / BoardPage
  → /commodities, /markets, /prices/latest, /prices/historical,
    /forecasts, /forecasts/summary, /sale-window
  → React Query cache + IndexedDB persistence for public price data
  → price cards, chart, forecast band, Sell/Hold/Wait advice
```

## Authenticated marketplace flow

```text
Supabase session/token
  → RequireAuth / auth/session.ts
  → /sell, /sell/new, /sell/$lotId, /account
  → profile, lots, advice/matches, offers, payments, logistics/storage,
    grievances, ledger, buyer registration/supply, FPO aggregation
  → Supabase RLS + RPC state transitions
```

## API surface

The active FastAPI router set is:

- `/api/v1/markets/` and `/api/v1/markets/nearby`
- `/api/v1/commodities/`
- `/api/v1/prices/latest` and `/api/v1/prices/historical`
- `/api/v1/lots/`, `/api/v1/lots/{id}`, advice, ledger, grade, withdraw, aggregate
- `/api/v1/me/`
- `/api/v1/direct/{rupee,fair-price,config,plan,group-buy,plans/commit,plans/{id},trace/{token},impact}`

## External services and persistence

- Supabase PostgreSQL/PostgREST/Auth: primary database, JWT verification, RLS,
  RPCs, profile and marketplace state.
- data.gov.in: mandi price/arrival source.
- Agmarknet: secondary mandi adapter.
- Department of Consumer Affairs/DCA: retail price anchor.
- Optional LLM/event sources: configured through event settings; event mode is
  off by default.
- SMS gateway: mock or Msg91 configuration; SMS webhook is machine-to-machine.

## Model and data posture

The forecasting path is runtime Python forecasting, not a committed serialized
model artifact. It includes moving average, OLS/feature OLS, Holt-Winters, and a
delisted GBM implementation with walk-forward backtesting and promotion gates.
Source snapshots include `data/gov_prices_60days.csv`, `data/gov_prices.csv`, and
`data/gov_retail_prices.csv`. The published accuracy card is intentionally blocked
until sufficient live history and evaluation evidence exist; Phase 4 must not turn
that into an invented accuracy claim.

## Dependency inventory

- Python runtime/dependencies: `requirements.txt`, `requirements-dev.txt`,
  `requirements-forecast-ml.txt`, `.python-version`, `pyproject.toml`.
- JavaScript runtime/dependencies: `web/package.json`, `web/package-lock.json`,
  and `web/bun.lock`.
- Current installed frontend tree resolves cleanly via `npm ls --depth=0`.
- Current Python environment has dependency conflicts: Supabase/PostgREST/storage
  require `httpx<0.28` while `httpx 0.28.1` is installed; realtime requires
  `websockets<13` while `websockets 16.1.1` is installed. This is a Phase 2
  high-risk item even though the current test suite passes.
- `pip-audit` could not complete in this sandbox: its temporary pip self-upgrade
  failed, and the no-deps retry did not return before cancellation. Vulnerability
  status remains open pending a networked clean environment.

## Phase 1 conclusion

The flagship DirectLink arithmetic is pure and demoable offline, while the live
PWA requires FastAPI and the frontend must use an allowlisted `localhost` origin.
The largest unresolved demo risks are dependency incompatibility, the lack of a
committed/evaluated ML artifact or held-out accuracy report, stale handoff contract
documentation, and the need to validate all authenticated DB/RPC flows against a
real Supabase project.
