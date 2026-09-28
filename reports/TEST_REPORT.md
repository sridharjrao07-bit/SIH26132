# SIH demo-readiness test report

Date: 2026-09-28  
Branch: `demo-readiness`  
Scope: public PWA entry point `/direct`, its FastAPI DirectLink API, the pure rupee/value-chain engine, supporting public routes, and the forecasting evidence used by the wider application.

## Results

| Area | Result | Evidence |
|---|---|---|
| Backend regression suite | PASS | 730 passed, 44 skipped, 0 failed |
| Backend lint | PASS | Ruff clean |
| Backend coverage | PASS with gaps | 5,507 statements, 84% total; coverage JSON/HTML in this directory |
| System endpoints | PASS | `/health`, `/readyz`, `/metrics`, `/openapi.json` returned 200 |
| DirectLink validation | PASS | Valid requests 200; empty, malformed JSON, missing coordinates and empty plan/group-buy inputs 422 |
| DirectLink load smoke | PASS | 40 concurrent pure rupee requests, ~117 requests/sec, all 200 |
| Frontend typecheck/build | PASS | `npm run typecheck` and `npm run build` |
| Frontend translations | PASS | 353 source messages, 0 missing in hi/mr |
| Frontend tests | PASS | 58/58 with mock API and real DirectLink API enforced |
| Browser demo | PASS | `http://localhost:5173/direct` rendered live values; custom 404 verified |
| Unified offline mock | PASS | One mock on `:8000` served marketplace plus DirectLink; 8 files / 58 tests / 0 skipped |
| Browser console/network | PASS in the exercised flow | No visible runtime error; CORS requires `localhost`, not `127.0.0.1` |

## API matrix

The existing route tests cover valid, invalid, empty, oversized, wrong-type, authentication-gated, and database-error behavior across the public and DirectLink routers. The focused smoke added during this audit verified:

- liveness/readiness/metrics/OpenAPI;
- `/rupee` valid, empty, malformed JSON;
- `/fair-price` valid and missing required coordinates;
- `/config` valid;
- `/plan` empty input;
- `/group-buy` missing required fields.

Persistence and impact routes are covered against the repository's fake Supabase contract emulator. A real Supabase/Postgres integration run was not possible with dummy local credentials; that limitation is recorded as P3-001.

The mock API now reuses the pure `direct/` engine for DirectLink `config`, `rupee`, `fair-price`, `plan`, and `group-buy`, with in-memory commit/read-back and the expected 404 behavior for unknown trace tokens. This removes the previous need to run a second backend for offline frontend testing.

## Browser observations

The live page opens on the audited Lasalgaon lane and displays the real engine result: farmer share 48.1155%, avoidable margin ₹2,032.2147, real work ₹368.5753, five stages, ₹3,637 direct farmer receipt (63.4% more), and ₹3,917 consumer price (27.4% less). `/direct/rupee` shows the custom 404 page and active route links. The browser sends the exact snapshot farm input of ₹2,226.39 and the backend's `load_qtl` field, so these values are reproducible against both the mock and FastAPI services.

## Remaining test limitations

- The workstation is Python 3.14.6 / Node 24.12.0; CI and Docker pin Python 3.12 and Node 22. Use those runtimes for the final venue image.
- Only the Codex in-app browser was available for this run; a second desktop browser was not available through the connected browser surface.
- Database-backed persistence, external ingestion, SMS, and external LLM/API failure modes need credentials or staging infrastructure.
