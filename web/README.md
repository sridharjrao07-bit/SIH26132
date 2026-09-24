# Krishi Bazaar — web

Farmer-facing PWA for SIH26132: mandi prices, the forecast band, and Sell / Hold / Wait advice.
Mobile-first at 360px, Marathi by default, built for weak connections.

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

| script | what it does |
| --- | --- |
| `npm test` | vitest: domain rules, trust states, chart ticks/tooltip, plus one integration render against the mock (skipped if the mock is down) |
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

## Translations

`scripts/translations.py` holds the draft Marathi and Hindi strings. It checks placeholders and fills the `.po` files.
**These are machine-drafted. A native speaker must review them before any farmer demo.**
