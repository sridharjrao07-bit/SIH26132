# Judge Feedback Remediation Log

This document maps the specific findings from the recent hackathon judge review to the corresponding architectural and code changes implemented during the Post-Review Improvement Sprint.

## 1. Security & Missing "Mode Ladder"

**Finding**: While authentication was present, authorization lacked a mode ladder (e.g., distinguishing between a farmer and an admin context). This posed a risk if an admin endpoint was accidentally exposed or if a compromised token tried to escalate privileges.

**Remediation**:
- **Zero-Trust RLS Engine (Phase 2)**: We implemented PostgreSQL Row Level Security (RLS) for tenant isolation on core tables. The `get_supabase_as_user` dependency mints a fresh, per-request client where PostgREST executes as the `authenticated` role.
- **Fail-Closed Guard**: `AUTH_DB_ENFORCEMENT=app` is blocked from starting in production by `app/startup_checks.py` (unless explicitly overridden), preventing accidental deployment of the mock layer.
- **Ownership Asserting RPCs**: All state-machine transitions (e.g. `transition_payment_status`) are executed via `SECURITY DEFINER` RPCs that perform an explicit ownership check (`p_user_id = auth.uid()`). These RPCs are explicitly granted to `authenticated` and `service_role`.
- **RlsFakeSupabase Canary**: Our test harness uses `RlsFakeSupabase` globally as the default `fake_supabase`, ensuring all local tests simulate RLS constraints (owner-only visibility). Tests like `test_rls_guard.py` explicitly verify this cross-tenant isolation and the fail-closed guard.
- **Service Role Audit**: We audited the `get_supabase_service_role` dependency. Service roles are now correctly scoped (e.g. `require_role('admin')`, buyer-supply verification, and background ingestion), while standard endpoints use `get_supabase_as_user` (which is explicitly **NOT** `@lru_cache`'d).
- **Documentation**: We authored `SECURITY_MODEL.md` detailing the 4-layer security posture (Ingest, Database RLS, API Gateway, Client), and updated line 32 of `README.md` to document the auth mode.

## 2. Scope Gaps (Onboarding, Storage, Supply Volumes)

**Finding**: The prototype assumed farmers were already registered, lacked storage/warehousing capabilities (a crucial aspect of market linkages), and did not surface arrival volumes (essential for price discovery).

**Remediation**:
- **Buyer Onboarding**: Added `POST /buyers/register` enabling self-service registration. Added an admin workflow (`GET /admin/buyers` and `PATCH /admin/buyers/{id}/verify`) to vet and approve buyers. Added an explicit RLS policy `USING (auth.uid() = owner_user_id OR verified = true)` to ensure unverified buyers cannot participate in the marketplace.
- **Warehousing Integration**: Introduced `storage_facilities` and `storage_bookings` tables. The `storage` router mirrors the logistics flow, enforcing physical capacity constraints (`quantity_qtl` sum against `capacity_qtl`). Added full state machine (requested -> confirmed -> completed/cancelled).
- **Arrival Volumes**: Added `arrival_qty` tracking to the `prices` API and `ingestion_log`. Implemented `MAX_ARRIVAL_QTY_QTL` in `PriceValidator` to prevent bad unit conversions (e.g., kilograms parsed as tonnes) from polluting the dataset.

## 3. Generalization Risk

**Finding**: The hardcoded Nashik/onion data indicated the platform might not scale easily to new districts or crops without significant refactoring.

**Remediation**:
- **Data-Driven Model**: Demonstrated that scaling requires zero code changes. Crops, markets, and regional aliases are managed entirely via SQL inserts (`commodities`, `markets`, `commodity_alias`).
- **Geo-Routing**: Utilized PostgreSQL `earthdistance` for `nearby_markets` RPC, proving that logistics routing works via mathematical coordinates, decoupled from district boundaries.
- **Scaling Roadmap**: Published `SCALING.md` outlining the exact SQL required to onboard Jalgaon bananas as a worked example, while candidly documenting the current limitations around language fallbacks and transport models.

## 4. Transparency

**Finding**: The original documentation did not clearly delineate what was fully implemented versus what was stubbed or planned.

**Remediation**:
- **Honest Limitations**: Added explicit "What Does Not Yet Generalize" sections to `SCALING.md`.
- **Anticipated Q&A**: Authored `JUDGE_QA.md` directly addressing the hard questions around vendor lock-in (Supabase), mock testing vs. live testing, and data provenance.

## 5. Commit Hash Table

| Sprint Goal | Commit Hash |
|---|---|
| Hygiene & Setup | 61875e7 |
| Phase 2 (Zero-Trust RLS) | e7f5205 → 71b17e3 |
| Phase 3 (Onboarding & Storage) | ed3656a, 2651fcb, fb37d36 |
| Phase 4 (Scaling & Docs) | 3eecfcf, 6d85356 |
| Post-Review Corrections (B1-B5) | cbc4f71, 128fc4b |

## 6. Deferred

| Item | Reason |
|---|---|
| Live PGRST301 Validation | Deferred. We lack live credentials in the current environment to execute `tests/test_rls_live.py`. **Risk Accepted**: If the hosted project rejects the tokens (due to JWT issuer/secret mismatch), every authenticated endpoint will return 500 in `rls` mode while all offline tests stay green. |
