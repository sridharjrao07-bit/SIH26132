# Krishi Bazaar Security Model

Krishi Bazaar enforces a strict 4-layer security model to prevent cross-tenant data leaks and unauthorized state mutations.

## The 4-Layer Model

1. **Authentication (FastAPI `Depends`)**
   - API endpoints use `get_current_user` to extract the JWT `sub` claim.
   - The token's issuer (`iss`) MUST match `SUPABASE_JWT_ISSUER` when operating against a live database, preventing token-forging vulnerabilities (PGRST301).

2. **Per-Request User Client**
   - Routers use `get_supabase_as_user` to mint a dedicated Supabase client for the request context.
   - **Crucially, this client is NEVER cached.** Using `@lru_cache` on a user-scoped client is a critical vulnerability that leaks connections across tenants.

3. **PostgREST Row-Level Security (RLS)**
   - The user client passes the JWT to Supabase.
   - Postgres RLS acts as a hard boundary. Even if the application logic contains a bug (e.g., forgetting a `.eq("user_id", user_id)` filter), the database will silently drop rows belonging to other tenants.
   - **Test Emulation:** Offline tests use `RlsFakeSupabase`, which mimics this by applying an ownership post-filter to all queries before returning results.

4. **Belt-and-Braces Application Logic & RPCs**
   - **RPC State Machines:** Critical state transitions (`mark_paid`, `offer_decide`, bookings) are handled by `SECURITY DEFINER` RPCs (e.g., `payment_mark_paid`, `storage_booking_create` — migration 036).
   - These RPCs bypass RLS internally but assert ownership server-side against `auth.uid()`, take row locks (`FOR UPDATE`) in a consistent lot-first order, and return typed `P000x` error codes the API maps to HTTP statuses. No router can force an invalid transition or bypass the capacity/state checks.
   - **One payment per offer** is enforced twice: `payment_create` is idempotent for any payment status, and `uq_payments_one_per_offer` (unique index) makes double billing structurally impossible.
   - **Fail-Closed Guard:** The application verifies RLS enforcement on startup via `startup_checks.py`. If `AUTH_DB_ENFORCEMENT=app` is detected in a non-dev environment, the backend refuses to start.

## Policy-vs-Query Audit

| Router | Table / RPC | Query Op | RLS Policy Enforced | Notes |
|---|---|---|---|---|
| `admin.py` | `ingestion_log` | SELECT | "Admins read ingestion log" | Uses `service_role` but gated by HTTP middleware. |
| `admin.py`, `intelligence.py` | `events` | SELECT | "Admins can view events" | Read-only for admins (Migration 018). |
| `forecasting/` | `weather_daily` | SELECT | "weather_admin_read" | Read-only for admins (Migration 017). |
| `alerts.py` | `alerts` | SELECT/INSERT/UPDATE | "Farmers read/create/update own alerts" | Handled natively by RLS. |
| `grievances.py` | `grievances` | SELECT/INSERT | "Owners read grievances" | Admin updates status directly, users only create/read. |
| `logistics.py` | `logistics_bookings` | SELECT/INSERT/UPDATE | "Owners read/create/update bookings" | Capacity checks done in Python, but row visibility enforced by RLS. |
| `markets.py` | `markets`, `prices` | SELECT | "Public can read markets/prices" | Public read tables. |
| `matching.py` | `buyers` | SELECT | "Public can read verified buyers" | Uses `public` client. |
| `sms.py` | `open_lots_for_user` | RPC | N/A (Security Definer) | Enforces visibility logic internally. |
| `offers.py` | `offers` | SELECT/INSERT | "Owners read/create offers" | **Note:** SELECT policy is extended in migration 014 to allow buyers to see offers they made. |
| `payments.py` | `payments` | SELECT / RPC | "Owners read payments" | Write mutations use `transition_payment_status` RPC. |
| `profile.py` | `user_profiles` | SELECT/UPDATE | "Users read/update own profile" | |
| `profile.py` | `buyers` | INSERT | "Buyers insert own profile" | **Note:** Added in migration 014 for self-service buyer onboarding. |
| `forecasting/` | `forecasts` | SELECT | "Public can read forecasts" | Columns `model_version` and `features_used` added in Migration 019 for ML auditability. |

## Mode Ladder

Controlled via `AUTH_DB_ENFORCEMENT`:
- `rls`: (Production Default) The user JWT is passed to PostgREST. Fails if issuer or secret is mismatched.
- `app`: (Development Only) Bypasses Postgres RLS entirely by using the `service_role` key, relying solely on Python-layer `.eq()` filters. Blocked from production.

## Role-Cache Propagation Window

`require_role` answers authorization from a **60-second in-process cache**
(`app/auth.py::_role_cache`) so that authenticated requests do not each pay a
`user_profiles` round-trip. Entries are `(role, expires_at)` pairs and are
evicted lazily, on the next read, once past their expiry.

The consequence is deliberate and bounded:

- A **first** request after a role change always sees the new role, because
  nothing is cached for that principal yet.
- A **cached** principal keeps their old role for at most `_ROLE_CACHE_TTL`
  (60 s). An admin demoted via the `admin_set_role` RPC — or by direct SQL —
  therefore retains admin access for at most one minute.
- The deployment is single-worker by design (in-process scheduler and rate
  limiter), so the cache has exactly one copy and there is no cross-replica
  divergence to reason about. Should that ever change, each worker holds its
  own cache and the TTL still bounds each of them independently.

There is **no invalidation hook**, and that is a decision rather than an
omission: role changes happen out-of-band, so a hook would have no caller and
would rot. If an in-app role-management endpoint is ever introduced, that
endpoint must call the hook and this section must be updated.

**Risk accepted:** up to 60 s of stale authorization after a demotion. It is
mitigated by the short TTL, and by the fact that destructive state transitions
live in `SECURITY DEFINER` RPCs which re-check `auth.uid()` server-side, so a
stale role grants no write path that bypasses ownership. Per-query ownership
filters are unaffected by this cache: it stores only the role, never row scope.
