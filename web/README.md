# Krishi Bazaar — web

Farmer-facing PWA for SIH26132: mandi prices, the forecast band, and Sell / Hold / Wait advice,
plus SMS price alerts and a form-driven marketplace (list produce, lot advice, buyers, offers,
payment status, transport/storage booking, complaints, the lot ledger, buyer registration and
supply, FPO pooling). Mobile-first at 360px, Marathi by default, built for weak connections.

## Screens

| Route | Screen | Account? |
| --- | --- | --- |
| `/setup` | Language, crop and mandi (3 taps) | no |
| `/` | Today: price, verdict, forecast band, other mandis | no |
| `/c/$crop/m/$market` | Pair detail with ranges 7d–1y | no |
| `/bhav` | Price board | no |
| `/forecasts/about` | How forecasts work, accuracy (pending until G6) | no |
| `/alerts` | Create, pause and delete SMS alerts | yes |
| `/sell`, `/sell/new`, `/sell/$lotId` | My lots, list produce, lot detail (advice, buyers, offers, payment, transport/storage, complaints, ledger, withdraw), FPO pooling | yes |
| `/buy` | Buyer registration, "waiting for verification", supply + make offer | yes |
| `/account` | Profile (name, phone, district, SMS language), sign out | yes |

The design record lives in the backend repo under `docs/frontend/01…05` (branch `arena/01a0d307-sih26132`).
Backend gaps are tracked there as G5–G7. Frontend tickets are G1, G2, G3, G8, G9 and G11.

## Run

```bash
npm ci
cp /path/to/SIH26132/frontend_handoff/mock/mock_api.py .mock/   # or set MOCK_API=/path/to/mock_api.py
npm run mock          # FastAPI-shaped mock on :8000
npm run dev           # http://localhost:5173, with /api proxied to API_TARGET (default :8000)
```

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
| `npm test` | vitest: domain rules, trust states, chart ticks/tooltip, the full farmer journey (list → offer → accept → pay → sold → ledger), alerts, and a render of every signed-in screen against the mock (integration tests are skipped if the mock is down) |
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
