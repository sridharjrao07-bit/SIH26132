# Krishi Bazaar — web

Farmer-facing PWA for SIH26132: mandi prices, the forecast band, Sell / Hold / Wait advice,
and DirectLink's consumer-rupee breakdown, plus the authenticated marketplace (list produce,
lot advice, buyers, offers, payment status, transport/storage booking, complaints, the lot
ledger, buyer registration and supply, and FPO pooling). Mobile-first at 360px, Marathi by
default, built for weak connections.

## Screens

| Route | Screen | Account? |
| --- | --- | --- |
| `/setup` | Language, crop and mandi (3 taps) | no |
| `/` | Today: price, verdict, forecast band, other mandis | no |
| `/c/$crop/m/$market` | Pair detail with ranges 7d–1y | no |
| `/bhav` | Price board | no |
| `/direct` | Where your consumer rupee goes; direct-trade comparison | no |
| `/sell`, `/sell/new`, `/sell/$lotId` | My lots, list produce, lot detail (advice, buyers, offers, payment, transport/storage, complaints, ledger, withdraw), FPO pooling | yes |
| `/account` | Profile (name, phone, district, SMS language), sign out | yes |

Retired paths such as `/forecasts/about`, `/alerts`, and `/buy` intentionally render
the application's custom not-found page. The active navigation is Today, Prices,
Direct, Sell, and Account.

The design record lives in [`../docs/frontend/`](../docs/frontend/) (`01…05`); backend gap tickets in [`../docs/tickets/`](../docs/tickets/).
The API contract is [`../frontend_handoff/API_CONTRACT.md`](../frontend_handoff/API_CONTRACT.md).
Backend gaps are G5–G7 (plus G12 below). Frontend tickets are G1, G2, G3, G8, G9 and G11.

## Run

For a complete offline demo, use the mock API on port 8000. It now includes the
same pure DirectLink engine as the backend, so prices, marketplace screens, and
the `/direct` rupee breakdown all work without a second service:

```bash
cd web
npm ci
npm run mock          # ../frontend_handoff/mock/mock_api.py on :8000
npm run dev           # http://localhost:5173, with /api proxied to API_TARGET
```

To run the enforced frontend suite against that one mock process:

```bash
REQUIRE_MOCK=1 REQUIRE_DIRECT_API=1 \
DIRECT_API_BASE=http://127.0.0.1:8000 npm test
```

The real backend on port 8001 remains useful for a separate production-contract
check, but it is no longer required to exercise DirectLink locally.

For the live DirectLink surface, run the real FastAPI app on port 8001 as well.
Use `http://localhost:5173` in the browser; the default backend CORS allowlist does
not include the numeric origin `http://127.0.0.1:5173`.

```bash
# terminal 1, from web/
npm run mock

# terminal 2, from the repository root (requires the project .venv)
PORT=8001 bash web/scripts/dev-backend.sh

# terminal 3, from web/
DIRECT_API_BASE=http://127.0.0.1:8001 REQUIRE_MOCK=1 REQUIRE_DIRECT_API=1 npm test
```

On Windows PowerShell, start the backend with the same dummy development values:

```powershell
$env:RUN_SCHEDULER='0'; $env:RATE_LIMIT_ENABLED='0'; $env:APP_ENV='development'
$env:SUPABASE_URL='https://placeholder.supabase.co'
$env:SUPABASE_ANON_KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.abcdefghijklmnopqrstuvwxyz1234567890'
$env:SUPABASE_SERVICE_ROLE_KEY=$env:SUPABASE_ANON_KEY
$env:SUPABASE_JWT_SECRET='ci-placeholder-jwt-secret-32b-min'
$env:DATA_GOV_IN_API_KEY='placeholder-not-a-real-key'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

To point the browser at that backend rather than the mock, set
`VITE_API_BASE_URL=http://127.0.0.1:8001` before starting Vite, or use the
same-origin proxy with `API_TARGET=http://127.0.0.1:8001`. The DirectLink live
tests use `DIRECT_API_BASE` independently of the browser proxy.

The browser only calls `/api/...` on its own origin. Point `API_TARGET` at the real FastAPI for staging.

### Sign-in

- **Real:** set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (see `.env.example`). They must be for the **same Supabase
  project as the backend**, or FastAPI rejects the tokens. Email and password sign-in follows `API_CONTRACT.md` §1.
  supabase-js is lazy-loaded, so the public price flow never downloads it.
- **Mock:** `.env.development` sets `VITE_DEV_AUTH=1`. The sign-in screen then shows Farmer / Buyer / FPO buttons, which mint
  tokens from the mock's `/__dev/token`. The real API never accepts these.
- Authenticated queries (key prefix `auth`) are never written to IndexedDB, and they are wiped on sign-out.

| script | what it does |
| --- | --- |
| `npm test` | vitest: domain rules, trust states, chart ticks/tooltip, DirectLink response contracts and real-backend integration, the full farmer journey (list → offer → accept → pay → sold → ledger), and signed-in screen renders against the mock. Set `REQUIRE_MOCK=1` and `REQUIRE_DIRECT_API=1` so integration tests fail instead of silently skipping. |
| `npm run build` | typecheck and production build (the Lingui vite plugin compiles `.po` on import) |
| `npm run i18n:extract` | refresh the catalogs after changing copy |
| `npm run i18n:check` | fails if any mr/hi string is missing |

## Rules the code enforces (don't "fix" these)

- **Pending is intended behaviour, not a missing feature.** `AccuracyCard` and `ModelChip` render
  "Not measured yet" / "Not published yet" until G6 / G5 ship. They never show invented numbers.
- Thresholds, model labels, coverage ("9 in 10") and accuracy come from the API only. The code never types a "95".
- The verdict comes from `sale-window.action` once. The chip and the card read the same query.
- Prices use Latin digits with `en-IN` grouping in every language. Months are localised via `-u-nu-latn`.
- Only the verdict is coloured (≥ 7:1 contrast). The arrivals strip never gets a labelled y-axis.
- The forecast method is shown as the API's `method`. It is never labelled "GBM" unless `method` says so.
- Other mandis come from `/prices/latest` plus `/markets` coordinates, not `sale_window.nearby` (G11 drift).
- PATCH forms send only the fields the user changed (omitted = unchanged, `null` = clear, §9.8).
- Offers can only be written as `accepted` or `rejected`. The lot flow is forward-only, so no "reopen" button exists.
- A 404 on an owner-only resource renders as "not found", never "permission denied".
- Match reasons, ledger events and statuses are mapped to words. Raw codes are never shown.

## Known gaps

- **G12:** the API has no "my buyer profile" endpoint. `/buyers/register` returns the id, which is stored on the device.
  If a buyer clears the browser, they can't find their profile again. The backend needs `GET /api/v1/buyers/me`.
- **Buyer's own offers:** `GET /offers/` is scoped to the lot owner, so a buyer can't list the bids they made.
- Rendering has been checked in jsdom only (`npm test`). Nobody has yet done a visual pass on a real phone.

## Translations

`scripts/translations.py` holds the draft Marathi and Hindi strings. It checks placeholders and fills the `.po` files.
**These are machine-drafted. A native speaker must review them before any farmer demo.**
