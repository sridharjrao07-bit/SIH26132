# Project rules

- Keep all backend, database, forecasting, ingestion, and API-contract files unchanged; frontend redesign work is isolated to `web/` because the supplied backend behavior is production-critical.
- Preserve the Krishi Bazaar project name across the frontend; reusable semantic tokens and shared primitives in `web/src/styles/index.css` must be preferred over page-local visual values.
- Dashboard visualizations use Recharts with existing query responses only, preserving API contracts and keeping all analytics frontend-derived.

## Running locally

- `npm run dev` starts Vite on :5173 and proxies `/api` to `API_TARGET` (default `http://127.0.0.1:8000`).
- To boot the FastAPI backend for that proxy, run `scripts/dev-backend.sh` from this directory. It sets the dummy Supabase values the app requires at startup; the DirectLink rupee breakdown is a pure function, so it needs no database and no credentials.
- `npm run typecheck`, `npm test` and `npm run i18n:check` are all gates. New `<Trans>` strings must be extracted (`npm run i18n:extract`) and translated in `src/i18n/locales/{hi,mr}/messages.po` before `i18n:check` passes — a missing translation silently falls back to English.

### The two-port convention

Two different servers both want port 8000, and they are not interchangeable:

| Port | Server | Who needs it |
|---|---|---|
| 8000 | `npm run mock` — the mock API | `marketplace` and `pairView` integration tests |
| 8001 | `PORT=8001 bash scripts/dev-backend.sh` — the real FastAPI app | `directLive.integration.test.tsx` |

Run **both** to get the whole suite green:

```
npm run mock &                                   # 8000
DIRECT_API_BASE=http://127.0.0.1:8001 PORT=8001 bash scripts/dev-backend.sh &
REQUIRE_DIRECT_API=1 npm test                    # 57 passed, 0 skipped
```

With neither running the suite still passes (45 passed, 12 skipped) — the integration tests skip rather than fail. Set `REQUIRE_DIRECT_API=1` to turn the real-backend tests into a hard failure in CI.

`API_TARGET` decides which server the dev preview proxies to, so point it at whichever one you want to look at. `directLive.integration.test.tsx` uses its own `DIRECT_API_BASE` client rather than the shared one, so it never depends on `API_TARGET`.

### Use `localhost:5173` in the browser, not `127.0.0.1:5173`

The backend's CORS allowlist defaults to `http://localhost:3000,http://localhost:5173`
(`app/config.py`, overridable with `CORS_ORIGIN`). `127.0.0.1:5173` is **not** in
it, so a browser opened on `http://127.0.0.1:5173` gets its `/api` calls rejected
by CORS even though the server is healthy and `curl` to the same address works.
Open `http://localhost:5173/direct` instead.

`curl` is unaffected — it sends no `Origin` header — which is exactly why this is
easy to miss: the endpoint works from the shell and fails from the browser.

### Why `directLive.integration.test.tsx` exists

The unit tests in `direct.test.tsx` stub `fetch`, so they can only assert the shape the client *sends*. They cannot catch a field the backend *requires* but the client never sends — a stub accepts anything. That is exactly how `/plan` and `/group-buy` shipped broken: the client sent `lots[].lot_id`, `demand` (singular), and `commodity`/`window`/`target_qtl`, none of which the backend accepts, and every unit test still passed. Only a real request surfaces a 422.

The schemas in `api/schemasDirect.ts` were likewise derived from captured responses, not from `frontend_handoff/API_CONTRACT.md` — that document is out of date for `/plan`, `/plans/commit` and `/group-buy`. When they disagree, the backend wins.
