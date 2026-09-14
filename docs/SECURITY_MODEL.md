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
   - **RPC State Machines:** Critical state transitions (like `mark_paid`) are handled by `SECURITY DEFINER` RPCs (e.g., `transition_payment_status`).
   - These RPCs bypass RLS internally but assert ownership via `IF auth.uid() IS NOT NULL AND auth.uid() <> p_user_id THEN RAISE`. This centralizes the state-machine rules and guarantees that no external router can force an invalid transition.
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
