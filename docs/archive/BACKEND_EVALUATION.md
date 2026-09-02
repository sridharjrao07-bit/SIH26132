# SIH26132 — Krishi Bazaar Backend Evaluation

**Role:** Senior backend engineer (35+ years)  
**Date:** 2026-09-02  
**Branch reviewed:** `arena/01a061ca-sih26132` (from `c22518b`)  
**Scope:** FastAPI application, ingestion, forecasting, notifications/SMS, PostgreSQL/Supabase schema + RLS, jobs/scheduler, tests. Frontend-beyond-`templates/dashboard.html` is out of scope except where it is served by this backend.

**Verdict:** The backend is a competent **mandi-price aggregator + 7-day statistical forecast + SMS alert** service for four Nashik commodities. It is **not** the market-linkage and transaction-enablement platform that SIH26132 asks for. Internally, several security, correctness, and operability defects remain. It is demo-capable for price visibility; it is not production-ready and it does not satisfy the problem statement’s expected solution.

---

## 1. Problem statement (source of truth)

**PS Number:** SIH26132  
**Title:** Strengthening market linkages and price discovery for farmers  
**Organization:** Government of Maharashtra  
**Department:** Maharashtra State Innovation Society, Department of Skills, Employment, Entrepreneurship and Innovation  
**Category:** Software  
**Theme:** Agriculture, FoodTech & Rural Development  
**Deadline:** 20 September 2026  

### Problem description

Many farmers, especially smallholders and producer groups, have limited visibility of current and expected prices across nearby markets, processors, institutional buyers and digital trading channels. Information on quality specifications, demand, logistics, storage, payment reliability and buyer credentials may be fragmented. Farmers may sell immediately after harvest because of liquidity or storage constraints and may have weak bargaining power. Buyers, meanwhile, may struggle to aggregate consistent volumes and verify quality. The challenge is to improve transparent price discovery and create reliable, efficient linkages from farm gate to suitable buyers.

### Expected solution / outcome

A market-intelligence **and transaction enablement** solution that:

1. Aggregates mandi prices, buyer demand, quality requirements, arrival volumes, transport and storage options.
2. Provides localised price trends and sale-window recommendations.
3. Matches farmers/FPOs with verified buyers.
4. Enables lot creation, quality grading, digital offers, logistics coordination and payment tracking.
5. Supports dispute or grievance processes.

Expected outcomes: improved farmer price realisation, reduced information asymmetry, lower transaction cost, stronger FPO aggregation, reduced post-harvest loss, more reliable buyer sourcing, transparent transaction records.

---

## 2. What this backend actually is

| Layer | Implementation |
|---|---|
| API | FastAPI 0.111, single worker assumed, APScheduler in-process |
| Auth | Supabase JWT (HS256) verified in FastAPI; roles in `user_profiles` |
| Data | Supabase PostgREST (`supabase-py`), no SQLAlchemy |
| Ingest | `data.gov.in` adapter (primary); optional Agmarknet Selenium |
| Forecast | Pure-Python MA / OLS / 0.4·MA+0.6·LR blend, 7-day horizon |
| Alerts | Threshold crossing + 24h cooldown + mock/MSG91 SMS |
| Geo | `earthdistance` RPCs `nearby_markets` / `nearest_market` |
| Scope | 5 Nashik APMCs, 4 crops (Onion, Tomato, Soybean, Maize), EN/MR/HI labels |

Public routes: `/health`, `/api/v1/markets[/nearby]`, `/commodities`, `/prices/{latest,historical}`, `/forecasts[/summary]`.  
Authenticated: `/api/v1/alerts` CRUD.  
Admin: `/api/v1/admin/{forecast,alert-check}/run`, `/dashboard/api/*`.  
Public webhook: `/api/v1/sms/webhook` (HMAC). Admin simulate: `/api/v1/sms/simulate`.

There are **no** routes for buyers, lots, offers, payments, grievances, FPOs, logistics, or storage (`tests/test_backend_audit.py::test_no_buyer_or_lot_or_payment_routes_exist`).

---

## 3. Coverage vs SIH26132 expected solution

| Expected capability | Status | Notes |
|---|---|---|
| Aggregate mandi prices | **Partial** | 5 Nashik mandis, 4 commodities. No processors, institutional buyers, or digital trading channels. |
| Buyer demand | **Missing** | No tables, ingest, or APIs. |
| Quality requirements | **Missing** | `variety`/`grade` columns exist on `prices`; no grading workflow or buyer spec matching. |
| Arrival volumes | **Schema only** | `prices.arrival_qty` exists; `DataGovInAdapter` never parses arrivals (`test_data_gov_in_adapter_does_not_parse_arrival_qty`). |
| Transport / storage options | **Missing** | |
| Localised price trends | **Partial** | `/prices/historical` + `/markets/nearby`. Historical `days` unbounded (overflow → 500). |
| Sale-window recommendations | **Missing** | Forecast is a weak proxy and is anchored to last observation date, not today — stale data yields past-dated forecasts the public API then hides. |
| Match farmers/FPOs ↔ verified buyers | **Missing** | `role='buyer'` exists in CHECK constraint; no buyer APIs, no FPO entity, no matching. |
| Lot creation | **Missing** | |
| Quality grading | **Missing** | |
| Digital offers | **Missing** | |
| Logistics coordination | **Missing** | |
| Payment tracking | **Missing** | |
| Dispute / grievance | **Missing** | |
| Transparent transaction records | **Missing** | Only `notification_log` / `ingestion_log`. |

**SIH outcome mapping:** information-asymmetry on **mandi modal prices** is partially addressed. Price realisation, FPO aggregation, post-harvest loss, buyer sourcing, and transaction records are not.

This is the dominant finding. The rest of this report evaluates the system **as a price-intelligence backend**, then lists every defect found.

---

## 4. Architecture assessment (what is sound)

These choices are defensible for a hackathon price-intel slice:

- Adapter pattern (`IngestionSourceAdapter`) with `SourceFetchError` so a dead source is logged as `failed`, not silent success.
- Alias table for source spellings (Onion vs Soyabean vs कांदा) instead of hard-coded maps.
- Sanity bands + unit conversion that **rejects unknown units** rather than guessing quintal.
- Upsert on the full 6-column unique key `(market_id, commodity_id, arrival_date, variety, grade, source)`.
- RLS as a second control plane; `handle_new_user` patched in 003 to ignore client-supplied `role`.
- `guard_profile_role` + `admin_set_role` for elevation; EXECUTE revoked from `anon`.
- Job locks (`claim_job_lock`) for forecast/alert/stale (ingestion omitted — see F-024).
- Forecast honesty: `n < 10` → `insufficient_data` rather than fabricating a number.
- Source precedence in `build_daily_series` (do not average government + scrape).
- SMS claim-then-send with rollback of `last_notified_at` on gateway failure.
- Webhook HMAC-SHA256 + ±5 min drift; `demo-secret` banned; production missing-secret raises.
- Generic 500 handler does not leak exception text (nearby RPC → 503 without schema-cache text).
- i18n labels in DB (`name_en/mr/hi`).
- `RUN_SCHEDULER` guard against uvicorn `--reload` double-scheduling.

The codebase also shows evidence of a prior remediation pass (migrations 003–007, comments labelled BLOCKER / M7 / B2). Several of those fixes are real. Several new and residual defects remain.

---

## 5. Findings catalog

Severity: **P0** blocker (security or PS outcome) · **P1** high · **P2** medium · **P3** low · **P4** nit.

Evidence tags refer to files in this repo and tests that were executed on 2026-09-02 (165 passed).

---

### 5.1 Problem-statement / product gaps

#### F-001 — P0 — Backend does not implement the expected solution
**Where:** entire API surface (`app/main.py` routes).  
**Evidence:** `test_no_buyer_or_lot_or_payment_routes_exist`. No tables for buyers, lots, offers, payments, grievances, logistics, storage, FPOs.  
**Impact:** A judge scoring against SIH26132 expected outcomes will treat this as a different product (mandi ticker + SMS), not market linkage.  
**Rec:** Either (a) add a minimal transaction slice (verified buyer registry, lot + offer + payment status + grievance ticket) on top of prices, or (b) explicitly reposition the idea as “price discovery only” and accept the coverage gap.

#### F-002 — P1 — Arrival volumes never ingested
**Where:** `ingestion/data_gov_in.py` `fetch_prices`.  
**Evidence:** `test_data_gov_in_adapter_does_not_parse_arrival_qty`. Schema comment in `001_schema.sql` calls arrivals “the most explainable insight”. Seed fakes `arrival_qty`; live ingest does not.  
**Impact:** Cannot support “arrivals up ⇒ price falls” or sale-window advice.  
**Rec:** Map `arrivals` / `arrival` from the resource payload into `RawPriceRecord.arrival_qty`.

#### F-003 — P1 — Buyer role is dead schema
**Where:** `user_profiles.role CHECK (farmer|admin|buyer)`.  
**Impact:** Suggests a marketplace that does not exist; confuses RLS design.  
**Rec:** Implement buyer flows or remove the role until needed.

#### F-004 — P1 — Geographic / commodity scope too narrow for “nearby markets … processors … digital channels”
**Where:** `002_seed.sql`, `TARGET_DISTRICT=Nashik`.  
**Impact:** Demo story is Lasalgaon onion only. Expanding district without alias/market coverage silently drops records (`unknown_market`).  
**Rec:** Treat seed as a fixture; add a documented onboarding path for new mandis/aliases.

#### F-005 — P2 — Agmarknet fallback only scrapes Lasalgaon for all of Nashik
**Where:** `ingestion/agmarknet.py` `market_to_query = "Lasalgaon" if district.lower() == "nashik"`.  
**Impact:** Fallback cannot cover Pimpalgaon / Yeola / Manmad. Optional (`ENABLE_AGMARKNET=0`) and Selenium-hostile on free PaaS.  
**Rec:** Iterate seeded `source_code` values; keep disabled in production until then.

---

### 5.2 Security

#### F-006 — P0 — Webhook HMAC secret is not loaded from Settings / `.env`
**Where:** `notifications/inbound_verifier.py` `_load_secret()` uses `os.environ.get("INBOUND_HMAC_SECRET")` and `os.environ.get("APP_ENV")`. `app/config.py` has **no** `inbound_hmac_secret` field. FastAPI does **not** call `load_dotenv()`. Pydantic Settings reads `.env` into the Settings object only.  
**Evidence:** `test_inbound_verifier_reads_os_environ_not_settings`.  
**Impact:**  
- `APP_ENV=production` and `INBOUND_HMAC_SECRET=...` in `.env` alone do **not** protect the webhook.  
- Verifier thinks it is development, generates an ephemeral key, logs a warning, and **rejects every correctly signed request** (or accepts none from the operator).  
- Production RuntimeError guard never fires.  
**Rec:** Put `inbound_hmac_secret` and `app_env` on `Settings`; load the verifier from `get_settings()`. Fail closed if production and secret empty.

#### F-007 — P0 — SMS webhook is a service-role SMS amplifier with no replay nonce and no rate limit
**Where:** `app/routers/sms.py` `Depends(get_supabase_service_role)`; `InboundVerifier` (body+timestamp HMAC, ±300s, no nonce); `slowapi` unused.  
**Evidence:** `test_webhook_replay_within_window_is_not_rejected`, `test_slowapi_is_not_wired_into_the_app`, `test_sms_webhook_unsigned_is_403`.  
**Impact:** Anyone who obtains the HMAC secret (or who can hit `/simulate` as admin) can: (1) replay the same inbound SMS for 5 minutes; (2) trigger outbound SMS to arbitrary numbers (help text or price reply); (3) read/write any table via the service-role client if they also find an injection path. Combined with F-006 this is worse.  
**Rec:** Bind HMAC to Settings; add nonce/jti cache; rate-limit `/sms/webhook`; run inbound processing with a constrained DB role, not service_role; cap outbound SMS per sender per hour.

#### F-008 — P1 — `slowapi` is a listed dependency and is never mounted
**Where:** `requirements.txt` vs `app/main.py`.  
**Evidence:** `test_slowapi_is_not_wired_into_the_app`.  
**Impact:** Public price/forecast/nearby and the webhook have no application-level rate limit. Nearby does a sequential `earth_distance` scan (fine at 5 rows, not at scale).  
**Rec:** Mount SlowAPI (or gateway limits) on public + webhook routes.

#### F-009 — P1 — Dashboard XSS sink + JWT in `localStorage`
**Where:** `templates/dashboard.html` `tbody.innerHTML = logs.map(l => \`<tr><td>${l.id}</td>...\`)`. Token saved via `localStorage.setItem("admin_jwt", token)`.  
**Evidence:** `test_dashboard_html_uses_unsanitized_innerhtml`, `test_dashboard_html_is_public`.  
**Impact:** HTML shell is public. If an ingestion_log/forecast field is attacker-controlled (source name, error_message), stored XSS steals the admin JWT.  
**Rec:** `textContent` / templating; HttpOnly cookie or memory-only token; CSP.

#### F-010 — P1 — `python-jose` is unmaintained
**Where:** `app/auth.py`, `requirements.txt` `python-jose[cryptography]==3.3.0`.  
**Impact:** Known advisory history (e.g. algorithm confusion / incomplete verification in older jose). Project already has PyJWT available in tests (`test_sms.py` imports `jwt`).  
**Rec:** Switch verification to PyJWT; pin algorithms strictly; add small clock leeway.

#### F-011 — P1 — `/health` leaks environment to the anonymous internet
**Where:** `app/main.py` `{"status":"ok","environment": settings.app_env}`.  
**Evidence:** `test_health_exposes_environment`.  
**Rec:** Return `{"status":"ok"}` publicly; put env on an admin diagnostic.

#### F-012 — P1 — OpenAPI /docs /redoc are unauthenticated
**Where:** FastAPI defaults.  
**Impact:** Full API map including admin and webhook in production.  
**Rec:** Disable docs when `APP_ENV=production` or protect them.

#### F-013 — P1 — `user_profiles.phone` is not unique and is not normalised
**Where:** `001_schema.sql`; inbound lookup `.eq("phone", sender)` after `normalize_phone`.  
**Impact:** Two farmers with the same number → first row wins. Number stored as `9876543210` will not match inbound `+919876543210`. SMS simply no-ops or hits the wrong user.  
**Rec:** Unique index on normalised E.164; write-path normalisation; lookup by digits.

#### F-014 — P1 — Migration 001 still trusts client `role` at signup
**Where:** `001_schema.sql` `coalesce(new.raw_user_meta_data ->> 'role', 'farmer')`. Fixed in `003_security_patch.sql`.  
**Impact:** Any environment that applied 001 but not 003 is privilege-escalation-complete (`{"role":"admin"}` in signup metadata).  
**Rec:** Make 003 mandatory in runbooks; add a CI check that `handle_new_user` body contains `'farmer'` literal.

#### F-015 — P2 — `003b` re-grants `admin_set_role` to `authenticated`
**Where:** `003` REVOKEs from `anon, authenticated`; `003b` GRANTs back to `authenticated` + `service_role`. Function body checks `has_role('admin')`.  
**Impact:** Defense in depth is weaker than 003’s comment claims. A future body bug becomes HTTP-callable.  
**Rec:** Keep EXECUTE on `service_role` only; admin elevation via SQL editor / one-shot script.

#### F-016 — P2 — JWT verification is HS256 + `aud=authenticated` only
**Where:** `app/auth.py`. No `iss`, no leeway, no `aal`/session checks.  
**Evidence:** `test_expired_jwt_is_rejected`, `test_wrong_audience_jwt_is_rejected`, `test_jwt_missing_sub_is_rejected`.  
**Impact:** Clock skew → random 401s; leaked JWT secret mints any `sub`. `demo/mint_admin_token.py` puts `user_metadata.role=admin` but `require_role` reads **DB**, so a minted token for a non-existent `sub` is 403 — the demo script is misleading (F-048).  
**Rec:** Verify issuer; 30s leeway; stop implying JWT carries application role.

#### F-017 — P2 — `require_role` uses the service-role client
**Where:** `app/auth.py` `get_supabase_service_role` to read `user_profiles.role`.  
**Impact:** Every authenticated request to an admin route bypasses RLS for that lookup (necessary), but the same client is then injected into admin handlers that run forecast/alert jobs. A bug in an admin handler is full-DB.  
**Rec:** Split “role lookup” from “job runner” clients; consider a SECURITY DEFINER `current_user_role()` RPC.

#### F-018 — P2 — No security headers
**Where:** `app/main.py` middleware stack is CORS only.  
**Impact:** No HSTS, CSP, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`. Dashboard clickjacking / MIME sniffing.  
**Rec:** Add `Secure` headers middleware.

#### F-019 — P2 — Mock SMS writes PII to a cwd log file
**Where:** `notifications/sms_gateway.py` `demo_sms.log`. Not in a secrets store; `.gitignore` has `*.log` (good) but production misconfig `SMS_GATEWAY=mock` dumps farmer phones + messages on disk.  
**Rec:** Structured log with redaction; never default to a world-readable file.

#### F-020 — P2 — CORS is a single origin string
**Where:** `CORS_ORIGIN=http://localhost:3000`, `allow_credentials=True`, `allow_methods=["*"]`.  
**Evidence:** `test_cors_header_reflects_configured_origin`, `test_cors_disallows_unknown_origin`.  
**Impact:** Cannot list preview + prod origins without a parser. `allow_methods=["*"]` with credentials is unnecessarily wide.  
**Rec:** Split CORS_ORIGIN on comma; enumerate methods.

#### F-021 — P3 — `has_role` is SECURITY DEFINER
**Where:** `001_schema.sql`. Needed so RLS can read `user_profiles`. `search_path = public` is set (good).  
**Impact:** Standard Supabase pattern; still a privilege concentration. Keep grants tight (already SQL).

#### F-022 — P3 — Public read of prices/forecasts/aliases
**Where:** RLS `using (true)` on those tables.  
**Impact:** Intentional for a public-good mandi ticker. Combined with no rate limit (F-008) it is a scrape target. Commodity payload also returns `sanity_min/max` (F-041).

---

### 5.3 Correctness / data integrity

#### F-023 — P1 — Forecast horizon is anchored to last observation, not today
**Where:** `forecasting/engine.py` `_make_forecast_rows`: `fdate = last_date + timedelta(days=i+1)`. Public GET `/forecasts` filters `forecast_date >= today`.  
**Evidence:** `test_forecast_horizon_is_anchored_to_last_observation_not_today`, `test_forecast_public_api_hides_past_dated_rows`.  
**Impact:** If Lasalgaon has not reported for 8+ days, the engine writes seven **past** dates, the farmer API returns `[]`, and the UI looks “down”. `mark_stale_forecasts` keys off `generated_at`, not “last price age”, so a fresh run of old data still produces `status=ok` past rows.  
**Rec:** Anchor to `date.today()`; if last observation is older than N days, emit `stale` / `insufficient_data` and do not upsert past dates.

#### F-024 — P1 — Ingestion job has no distributed lock
**Where:** `app/jobs.py` `run_ingestion_job` vs `run_forecast_job` / `run_alert_job`. Startup catchup `_run_catchup_task` also unlocked.  
**Evidence:** `test_ingestion_job_does_not_take_distributed_lock`.  
**Impact:** Two workers, reload, or overlap with catchup → double fetch, quota burn on data.gov.in, duplicate work. Upsert is idempotent for data, not for quota or `ingestion_log` volume.  
**Rec:** `claim_job_lock('ingestion', ...)` around the runner; catchup should use the same lock.

#### F-025 — P1 — `/prices/historical?days=` is unbounded and overflows to HTTP 500
**Where:** `app/routers/prices.py` `days: int = Query(30)` — no `ge`/`le`. `date.today() - timedelta(days=999999)` raises `OverflowError`, caught by the generic handler.  
**Evidence:** `test_historical_days_unbounded_overflows_to_500`.  
**Impact:** Trivial unauthenticated DoS / 500.  
**Rec:** `Query(30, ge=1, le=365)`.

#### F-026 — P1 — “district_avg” is not an average
**Where:** `notifications/alert_checker.py` `_check_crossing` sets `scope_note = "district_avg"` then `build_daily_series` over mixed markets — one winning source/variety per date.  
**Evidence:** `test_district_fallback_is_not_an_average`.  
**Impact:** SMS can claim a district picture while quoting a single mandi’s modal. Misleading for sale decisions.  
**Rec:** Rename to `district_latest` **or** compute a true volume-weighted average and say so.

#### F-027 — P1 — Sustained-breach logic re-fires every 24h without a new cross
**Where:** `_check_crossing` `gte`: `prev >= threshold and latest >= threshold`.  
**Evidence:** `test_sustained_gte_breach_fires_without_fresh_cross`. Cooldown only delays, does not require a re-cross.  
**Impact:** Farmer gets a daily SMS for the entire period price stays above the line (capped at 3/user/run). May be intended; it is not “crossing detection” as the comments describe.  
**Rec:** Fire on edge only; optional digest for sustained breach.

#### F-028 — P1 — Cooldown compares ISO **strings**, some naive
**Where:** `AlertChecker._now()` / `_hours_ago()` strip tzinfo; DB `timestamptz` comes back as `...+00:00` or `Z`. Pre-filter `last_notified >= cooldown_cutoff` is a string compare.  
**Impact:** `+` vs `.` vs `Z` can skip or keep cooldown incorrectly around the 24h boundary. Tests pass because FakeSupabase and checker both use naive `utcnow()` strings.  
**Rec:** Parse to aware datetimes; compare as times. Keep `_now()` as timestamptz ISO with offset.

#### F-029 — P1 — SMS inbound `.upper()` + exact alias match
**Where:** `app/routers/sms.py` `message = (...).strip().upper()` then `.eq("source_key", message)`. Seed keys: `ONION`, `कांदा`, …  
**Impact:** `"ONION LASALGAON"`, `"price onion"`, extra whitespace beyond strip, or a different Devanagari spelling → help SMS. Help SMS is sent even to unregistered numbers (amplifier, F-007). Unknown keyword still costs an outbound SMS.  
**Rec:** Tokenise first word; fuzzy alias; do not SMS help to unknown MSISDNs.

#### F-030 — P1 — `latest_price_for_user` does not use source precedence
**Where:** `notifications/prices.py` latest row by `arrival_date desc limit 1` vs alert checker’s `build_daily_series`.  
**Impact:** Inbound SMS price and alert-crossing price can disagree on the same day if two sources exist.  
**Rec:** Share one resolver.

#### F-031 — P2 — Confidence intervals are not forecast intervals
**Where:** `MovingAverageModel` / `LinearRegressionModel` use `1.96 * pstdev(window or residuals)` **constant** across the 7-day horizon. Blend uses `max(σ_MA, σ_LR)`.  
**Impact:** Judges asking “why is day-7 as tight as day-1?” get an honest but statistically weak answer. `σ=0` on a perfect line → zero-width bounds (tested, by design).  
**Rec:** Widen with horizon or label as “in-sample residual band”, not “95% forecast CI”.

#### F-032 — P2 — Sanity clamp can push `upper_bound` outside the band
**Where:** `_make_forecast_rows` clamps `predicted` then rebuilds `upper = predicted + margin`.  
**Impact:** `test_clamped_center_keeps_bounds_sane` only asserts `lo <= p <= hi` and `p >= sanity_min`, not `hi <= sanity_max`. A crashing onion series clamped to 100 can still advertise an upper of thousands.  
**Rec:** Clamp lo/hi into the band after recentering.

#### F-033 — P2 — Forecast unique key cannot represent two methods for one date
**Where:** `uq_forecast (market_id, commodity_id, forecast_date)`. Re-run overwrites. Old future dates from a previous `last_date` remain until stale-mark.  
**Impact:** Mixed-age rows in `/summary` (2-day `generated_at` cutoff helps).  
**Rec:** Delete-then-insert per pair, or key by `generated_at` run id.

#### F-034 — P2 — Ingest upsert is one shot for the whole adapter batch
**Where:** `ingestion/runner.py` single `upsert(all_valid_for_adapter, ...)`.  
**Impact:** One undeclared column / NaN that slipped through fails the entire mandi-day. No chunking, no per-row error isolation.  
**Rec:** Chunk (e.g. 200) and count partial failures.

#### F-035 — P2 — `create_alert` returns `null` with HTTP 200 on empty insert
**Where:** `app/routers/alerts.py` `return res.data[0] if res.data else None`. No FK existence check for `commodity_id` / `market_id`.  
**Impact:** Invalid UUID / RLS rejection looks like success.  
**Rec:** 400/404 if `not res.data`; validate UUIDs against reference tables.

#### F-036 — P2 — Alert messages are English with a vernacular commodity token
**Where:** `alert_checker.py` MR/HI branches. `test_marathi_message_fits_in_70_chars` uses a `CapturingGateway.send_sms(self, recipient, message, template_id=None)` that **does not accept `**vars`**, so `TypeError` is swallowed and `sent_messages` stays empty — the 70-char assertion is a **false pass**.  
**Impact:** DLT templates (when configured) send whatever MSG91 has registered; mock path sends English. Farmers told “Marathi SMS” may receive English.  
**Rec:** Fix the test to `**kwargs`; write real MR/HI copy; keep ≤70 chars for UCS-2.

#### F-037 — P2 — MSG91 treats only HTTP 200 as success
**Where:** `MSG91Gateway.send_sms` `if resp.status_code == 200`.  
**Impact:** 201/202 → `failed` + cooldown rollback + retry storm.  
**Rec:** `resp.is_success`; persist `provider_ref` (column exists, never written — F-042).

#### F-038 — P2 — Linear regression uses day index, then predicts calendar days
**Where:** engine comments correctly avoid holiday-skewed slope, then emit 7 consecutive calendar dates including Sundays when mandis are closed.  
**Impact:** Minor for a 7-day hackathon model; do not call it “mandi-day forecast”.

#### F-039 — P3 — `DataGovInAdapter.DISTRICT_SPELLINGS` always tries Nashik/Nasik
**Where:** even if `TARGET_DISTRICT=Pune`. Extra API calls, possible wrong-district data if filters fail open.  
**Rec:** Spellings map keyed by requested district.

#### F-040 — P3 — Two HTTP clients and mismatched timeouts in one fetch
**Where:** `fetch_prices` uses `AsyncClient(timeout=10)` while `_get_json` uses `timeout=15` on the request. Pagination errors are swallowed (`partial data is better than none`) without incrementing `records_rejected`.  
**Rec:** One client; surface truncated pagination as `partial`.

---

### 5.4 API contract / privacy / ops

#### F-041 — P2 — Public commodities API leaks internal sanity bands
**Where:** `CommodityResponse.sanity_min/max`; `GET /api/v1/commodities/`.  
**Evidence:** `test_commodities_response_leaks_sanity_bands`.  
**Impact:** Validation policy is public; not secret, but it is not a farmer-facing field.  
**Rec:** Admin-only or omit from the public schema.

#### F-042 — P2 — `notification_log.provider_ref` is never set
**Where:** insert in `alert_checker.py` omits it; MSG91 response body unused.  
**Impact:** Cannot trace a failed SMS in the MSG91 dashboard — the comment on the column is aspirational.

#### F-043 — P2 — Dashboard `forecast-stats` is N+1 queries
**Where:** `app/routers/dashboard.py` one prices query per forecast (limit 50).  
**Impact:** Fine at demo scale; 50 sequential PostgREST round-trips on a 300 ms link is ~15 s.  
**Rec:** One prices query `in_(market_id)` / RPC.

#### F-044 — P2 — `/forecasts/summary` deduplicates in Python with a 2000-row cap
**Where:** `app/routers/forecasts.py`. PostgREST has no GROUP BY.  
**Impact:** At 5×4×7 the cap is fine. At 200 mandis × 20 crops × 7 days it silently drops pairs. `.order().order()` (two order calls) — supabase-py keeps the last order, so “newest run first, then day-1” may not actually be two-level sort.  
**Rec:** SQL view / RPC for “latest run, day-1 per pair”.

#### F-045 — P2 — In-process APScheduler on a web dyno
**Where:** `app/jobs.py`, `lifespan`. Documented `--workers 1`. Render/free-tier sleep + restart races catchup (F-024). Job lock TTL 15 min then steal → overlapping alert SMS if a run exceeds TTL.  
**Rec:** External cron hitting admin triggers, or a worker process; TTL > worst-case runtime.

#### F-046 — P2 — Sync Supabase client on the asyncio loop
**Where:** `IngestionRunner.run` is async but calls `self.supabase.table(...).execute()` synchronously; only forecast/alert wrap `to_thread`.  
**Impact:** One slow data.gov.in + PostgREST ingest blocks health checks on the single worker.  
**Rec:** `asyncio.to_thread` the runner, or use the async supabase client throughout.

#### F-047 — P2 — `structlog` is not configured
**Where:** no `structlog.configure` in `main.py`.  
**Impact:** Logs are not guaranteed JSON; correlation ids absent; `exc_info=True` formatting depends on defaults.  
**Rec:** Configure processors once at startup.

#### F-048 — P2 — `demo/mint_admin_token.py` does not create an admin
**Where:** JWT `sub` default `admin-demo-user`; `require_role` looks up `user_profiles`.  
**Impact:** Dashboard “paste admin JWT” fails 403 unless that UUID was elevated via `admin_set_role`. Demo script is a foot-gun.  
**Rec:** Mint only for a real `auth.users` id; print that requirement.

#### F-049 — P2 — No deploy/CI artefacts in-repo
**Where:** no Dockerfile, Procfile, GitHub Actions, `render.yaml`. `pytest_proof.txt` is a Windows run of **78** tests (older subset).  
**Impact:** “It passed on my machine” is the only evidence before this review.  
**Rec:** CI job: `pytest` on 3.11/3.12; pin `python-jose` replacement.

#### F-050 — P3 — Route prefix inconsistency
**Where:** markets/commodities/prices/forecasts set `/api/v1/...` on the router; alerts/sms/admin set prefix on `include_router`. Trailing slash on `/markets/` vs no slash on `/forecasts`. FastAPI redirects, but clients differ.  
**Rec:** One convention.

#### F-051 — P3 — `get_settings` is `lru_cache`’d
**Impact:** Tests and runtime cannot change env without `cache_clear()`. Contributes to F-006 confusion.  
**Rec:** Acceptable if documented; clear in tests.

#### F-052 — P3 — `create_app()` at import time
**Where:** `app = create_app()` in `main.py`.  
**Impact:** Importing `app.main` instantiates `InboundVerifier()` (module-level in `sms.py`) with whatever env exists at first import.  
**Rec:** Lazy verifier; factory stays, but side effects should move into lifespan.

#### F-053 — P3 — No user-profile API
**Where:** profiles are created by DB trigger only. No GET/PATCH `/me`. Farmers cannot set `lat/lng/phone/language` through this backend.  
**Impact:** Nearest-market alerts and SMS language depend on out-of-band profile writes (Supabase client). Fine if the frontend talks to PostgREST directly under RLS; undocumented here.

#### F-054 — P3 — No pagination on `GET /alerts/`
**Impact:** A farmer with years of alerts dumps the table. Add `limit`.

#### F-055 — P3 — `nearby_markets` comment says PostGIS; implementation is `earthdistance`
**Where:** `app/routers/markets.py` docstring vs `004_nearby_markets.sql`. No GiST index on `ll_to_earth(lat,lng)`.  
**Impact:** Five rows: irrelevant. Hundreds: seq scan per request.  
**Rec:** Fix the comment; add GiST if you scale.

#### F-056 — P3 — Seed `ON CONFLICT DO NOTHING` on `markets` before a unique key exists
**Where:** `002_seed.sql` vs unique `source_code` added in 003. Re-running 002 alone duplicates mandis. 003 deletes dupes then adds the constraint.  
**Impact:** Operator order matters.  
**Rec:** Unique key in 001; keep 003 as a patch for already-deployed DBs.

#### F-057 — P3 — `002` `on conflict do nothing` without specifying a constraint on markets insert
**Postgres:** `ON CONFLICT DO NOTHING` without a target only ignores unique-violation; with no unique besides PK (uuid) it never conflicts. Same as F-056.

#### F-058 — P4 — Duplicate `upsert_calls` method on `FakeSupabase`
**Where:** `tests/conftest.py` defines `upsert_calls` twice. Harmless; second wins.

#### F-059 — P2 — FakeSupabase.rpc historically returned `_ExecuteResult` without `.execute()`
**Where:** `tests/conftest.py` (fixed in this review). `admin.py` always calls `.rpc(...).execute()`. Existing `test_admin_forecast_run_accepts_admin_token` only asserted `not in (401, 403)` — a **500 was a pass**.  
**Impact:** Admin job paths were not actually tested. This review added `.execute()` on the stub and `test_admin_forecast_locked_returns_locked`.  
**Rec:** Never assert “not 401/403” as success.

#### F-060 — P2 — Settings cannot be constructed with field names
**Where:** `app/config.py` `SettingsConfigDict` has no `populate_by_name=True`; `extra=ignore`.  
**Evidence:** `test_settings_constructor_ignores_field_names`. Previously `test_resolve_template_returns_correct_lang` constructed `Settings(msg91_dlt_te_id_mr="tmpl_mr")` and asserted against `None` (hidden fail / env-dependent). Fixed in tests to inject a `SimpleNamespace`.  
**Impact:** Tests and scripts that pass kwargs silently use `.env` / process env instead.  
**Rec:** `populate_by_name=True`.

#### F-061 — P3 — `mark_stale_forecasts` granted to `authenticated` in 005, revoked in 007
**Impact:** Same class as F-015: later migrations are load-bearing. Skip 007 and any farmer JWT can stale the whole forecast table (SECURITY DEFINER UPDATE).  
**Rec:** Collapse grants into the function’s creating migration.

#### F-062 — P3 — Inbound SMS `no_data` is silent to the farmer
**Where:** `return {"status": "no_data"}` with no outbound SMS.  
**Impact:** Farmer who texted कांदा gets nothing. Help is only for unknown keywords.  
**Rec:** Send a short “no recent price” MR/HI message.

#### F-063 — P3 — Help SMS language is English regardless of profile
**Where:** `HELP_TEXT + SMS_KEYWORDS_HELP` always English; `resolve_template(lang)` may be None → mock still sends English.  
**Rec:** Localise help.

#### F-064 — P4 — `python-multipart` / form endpoints
**Where:** requirements comment “manual price entry”; no form routes exist.

#### F-065 — P4 — Health/docs vs problem deadline
Not a code defect. Idea submission deadline is 20 Sep 2026; this backend is a Stage 1–5 price-intel slice, not a complete PS response (F-001).

#### F-066 — P2 — Job lock steal after TTL can double-send SMS
**Where:** `006_job_locks.sql` `ON CONFLICT DO UPDATE WHERE expires_at < now()`. Alert job TTL default 15 min. Claim-then-send on the alert row mitigates but the first process may still be in `gateway.send_sms` after TTL expiry.  
**Rec:** Heartbeat/extend lock; or transactional outbox.

#### F-067 — P3 — `earthdistance` `ll_to_earth` treats lat/lng as numeric without CHECK
**Where:** markets lat/lng `numeric(9,6) not null` but no `between -90 and 90`. API nearby has Query bounds (`test_nearby_invalid_lng_rejected`); DB seed is trusted.  
**Rec:** CHECK constraints.

#### F-068 — P3 — No index on `alerts(last_notified_at)`, `alerts(expires_at)`
**Impact:** Expiry update is `lt expires_at` on all active rows; fine at demo N.

#### F-069 — P2 — Generic exception handler + `raise_server_exceptions=False` hide 500s in tests
**Where:** `app/main.py` `@app.exception_handler(Exception)`. TestClient constructed that way in `test_api.py` and audit tests. Combined with F-059, 500s look like “success” if assertions are loose.  
**Rec:** Assert exact status codes; log handler already does.

#### F-070 — P3 — `get_supabase` (anon, lru_cached) is a process-global client
**Where:** `app/deps.py`. Fine for public reads. Do not attach user JWTs to it (you don’t — `get_supabase_as_user` builds a new client). Good.

#### F-071 — P4 — `pytest.ini` `asyncio_default_fixture_loop_scope` unknown to pytest-asyncio 0.23
**Evidence:** session warning. Harmless.

#### F-072 — P3 — `test_db.py` and `demo/reconcile.py` are live-network scripts, not pytest
**Impact:** No automated proof that RLS or data.gov.in filters still match seed `source_code`s. `reconcile.py` is the right idea; it is not in CI.

---

## 6. Testing performed in this review

### 6.1 Prior suite
`pytest_proof.txt` (Windows, older snapshot): **78 passed**. That run did **not** include later API/auth/forecast-summary tests now in `tests/test_api.py`.

### 6.2 This review
Environment: Python 3.11.2, venv with `requirements.txt` as pinned.

```
165 passed, 2 warnings in 1.70s
```

Warnings: unknown pytest-asyncio config key; `gotrue` deprecation from supabase-py.

Added: `tests/test_backend_audit.py` (authz, JWT, CORS, webhook replay, phone normalisation, forecast-date anchoring, historical overflow 500, district_avg characterisation, arrival_qty gap, ingestion lock gap, Settings populate_by_name, slowapi absence, PS route gap, admin lock, SMS simulate, dashboard XSS sink, sanity-band leak).

Test-double fixes (evaluation-only, in `tests/conftest.py`):

- `FakeSupabase.rpc` now returns a builder with `.execute()` (matches supabase-py). This made admin job tests real.
- `delete()` returns deleted rows so `404 vs deleted` is testable.

Existing test fix: `test_resolve_template_returns_correct_lang` now injects a `SimpleNamespace` because `Settings(...)` field-name kwargs are ignored (F-060).

### 6.3 Not tested (limitations of this review)
- Live Supabase RLS (requires project keys; `demo/reconcile.py` Test 4 is the intended check).
- Live data.gov.in pagination/filters.
- MSG91 DLT delivery.
- Multi-process job-lock races against real Postgres.
- Selenium Agmarknet path (optional, Chrome).
- Load / soak.

---

## 7. Priority remediation (if the goal is SIH, not a mandi ticker)

**Week 0 — stop the bleeding (P0/P1 security)**  
1. Load HMAC secret and `APP_ENV` from Settings (F-006).  
2. Nonce + rate-limit webhook; stop using service_role for inbound SMS (F-007, F-008).  
3. Bound `days` on historical prices (F-025).  
4. Dashboard XSS (F-009).  
5. Replace python-jose (F-010).

**Week 0 — make price intel honest**  
6. Anchor forecasts to today / mark stale on data age (F-023).  
7. Lock ingestion (F-024).  
8. Parse arrivals (F-002).  
9. Edge-only alerts + timezone-safe cooldown (F-027, F-028).  
10. One price resolver for SMS and alerts (F-026, F-030).

**If scoring SIH26132 expected solution**  
11. Minimal transaction spine: `buyers` (verified), `lots` (qty, grade, market), `offers`, `payments` (status only), `grievances`.  
12. Match API: farmer lot → ranked buyers by demand + distance + price.  
13. Sale-window: forecast + arrivals + nearby mandi spread, in MR/HI SMS.  
14. FPO as first-class `user_profiles.role` or `organisations` table.

Without (11)–(14), further polish on MA/OLS will not move the PS score.

---

## 8. Finding index (quick)

| ID | Sev | One-liner |
|---|---|---|
| F-001 | P0 | Not the SIH expected product (no buyers/lots/payments/grievances) |
| F-006 | P0 | HMAC secret / APP_ENV not read from `.env` Settings |
| F-007 | P0 | Webhook = service-role + replayable HMAC + no rate limit |
| F-002 | P1 | Arrivals never ingested |
| F-003 | P1 | Buyer role unused |
| F-004 | P1 | 5 mandis × 4 crops only |
| F-005 | P1 | Agmarknet = Lasalgaon only |
| F-008 | P1 | slowapi unused |
| F-009 | P1 | Dashboard innerHTML XSS + localStorage JWT |
| F-010 | P1 | Unmaintained python-jose |
| F-011 | P1 | /health leaks env |
| F-012 | P1 | /docs public |
| F-013 | P1 | phone not unique / not E.164 |
| F-014 | P1 | 001 signup trusts client role |
| F-023 | P1 | Forecasts dated from last obs → empty farmer API |
| F-024 | P1 | Ingestion unlocked |
| F-025 | P1 | historical days overflow → 500 |
| F-026 | P1 | district_avg is not an average |
| F-027 | P1 | Sustained breach daily SMS |
| F-028 | P1 | Cooldown string-compares timestamps |
| F-029 | P1 | Exact SMS keyword match + help to anyone |
| F-030 | P1 | Two price resolvers |
| F-015–F-022 | P2–P3 | Grants, JWT, headers, CORS, mock log, public prices |
| F-031–F-040 | P2–P3 | Model CI, clamp, upsert batch, alert 200-null, MR test false pass, MSG91 200-only |
| F-041–F-072 | P2–P4 | Contract, ops, tests, schema nits |

**Count:** 72 findings (3 P0, 20 P1, remainder P2–P4).

---

## 9. Closing judgement

This is **above-average hackathon backend craft** for a **price-visibility** story: real validation, RLS patches, job locks, honest insufficient-data forecasts, and a test suite that already caught several of its own past bugs.

It is **below the bar for SIH26132** as written by Government of Maharashtra. The expected solution is a **market-linkage and transaction-enablement** system. This repository implements **none** of buyer matching, lots, grading workflow, offers, logistics, payments, or grievances.

If the team keeps the current scope, say so in the idea submission and be scored as a mandi-price + SMS advisory. If the team wants the PS, the backend needs a second product slice, not another forecasting tweak.

I would **not** ship the webhook or admin dashboard to a public URL until F-006, F-007, F-009, and F-025 are fixed.

---

*End of evaluation. Tests: 165 passed (2026-09-02, CPython 3.11.2).*
