# Frontend Design — Phase 2: Stack (APPROVED 2026-09-24)

| Layer | Decision |
|---|---|
| App | **Vite + React 18 + TypeScript (strict)**, a static single-page app. No Next.js. |
| Offline | `vite-plugin-pwa` (installable, service worker) + TanStack Query cache saved to IndexedDB. Reference data (`commodities`, `markets`) is cached aggressively. |
| Server state | TanStack Query. Data refreshes after 5 min. Reference data is cached for the session. |
| URL state | TanStack Router with typed search params. |
| Client state | Zustand: locale, prefs, session. |
| Charts | **Recharts** (`ComposedChart` + range `Area` band + `Bar` with null gaps + `ReferenceLine`/`ReferenceDot` for the annotation slot). Custom SVG only for the actual→forecast join and tabular-figure axes. Switch to visx **only if a named team member has shipped D3-scale work**. Test with Devanagari tick labels early. |
| Styling | Tailwind v4 with our own tokens only (default palette off) + Radix primitives. No shadcn kit. |
| Fonts | IBM Plex Sans + IBM Plex Sans Devanagari, self-hosted and trimmed. Tabular figures. |
| Numbers | **Latin digits for all prices, `en-IN` grouping (₹1,00,000) in every locale.** Never `toLocaleString('mr-IN')` on numbers. One `formatINR()` in `domain/format.ts`. |
| i18n | Lingui catalogs for en/mr/hi, only the active one loaded. Default `mr`. |
| API types | Start from `frontend_handoff/types/api-types.ts` (hand-written), validated with Valibot at the boundary. **Normalize G10 drift in the adapter.** |
| Mock | `frontend_handoff/mock/mock_api.py` for local dev and MSW fixtures. Beware G10 (seed markets and `better_market` shape differ from the real API). |
| Auth | supabase-js loaded only on auth routes. |
| Hosting | Static CDN with `/api/*` forwarded to FastAPI (same origin). In dev, Vite forwards `/api` to `:8000`. |
| Tests | Vitest, Testing Library, MSW, Playwright at 360px, Storybook for chart health states. |
| Budget | ≤150 KB gzip JS on public routes. Largest content visible <2.5 s on slow 4G. The Sell/Hold/Wait card renders before the chart code loads. |

Tickets: G5–G7 and G10 are backend issues (`docs/tickets/backend_gaps_G5-G7.md`). G1, G2, G3, G8 and G9 go in the frontend repo tracker. G4 is part of the chart component spec.
