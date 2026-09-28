# Project rules

- Keep all backend, database, forecasting, ingestion, and API-contract files unchanged; frontend redesign work is isolated to `web/` because the supplied backend behavior is production-critical.
- Preserve the Krishi Bazaar project name across the frontend; reusable semantic tokens and shared primitives in `web/src/styles/index.css` must be preferred over page-local visual values.
- Dashboard visualizations use Recharts with existing query responses only, preserving API contracts and keeping all analytics frontend-derived.

## Running locally

- `npm run dev` starts Vite on :5173 and proxies `/api` to `API_TARGET` (default `http://127.0.0.1:8000`).
- To boot the FastAPI backend for that proxy, run `scripts/dev-backend.sh` from this directory. It sets the dummy Supabase values the app requires at startup; the DirectLink rupee breakdown is a pure function, so it needs no database and no credentials.
- `npm run typecheck`, `npm test` and `npm run i18n:check` are all gates. New `<Trans>` strings must be extracted (`npm run i18n:extract`) and translated in `src/i18n/locales/{hi,mr}/messages.po` before `i18n:check` passes — a missing translation silently falls back to English.
