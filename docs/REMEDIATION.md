# Judge Feedback Remediation Log

This document maps the specific findings from the recent hackathon judge review to the corresponding architectural and code changes implemented during the Post-Review Improvement Sprint.

## 1. Security & Missing "Mode Ladder"

**Finding**: While authentication was present, authorization lacked a mode ladder (e.g., distinguishing between a farmer and an admin context). This posed a risk if an admin endpoint was accidentally exposed or if a compromised token tried to escalate privileges.

**Remediation**:
- **Zero-Trust RLS Engine**: We migrated all role-based authorization from the API layer to PostgreSQL Row Level Security (RLS).
- **Service Role Constraints**: We removed the `get_supabase_service_role` dependency from all standard API endpoints. Service roles are now strictly gated to background jobs (ingestion, forecasting).
- **Admin Elevation Path**: Implemented `admin_set_role` RPC that verifies caller's `has_role('admin')` before changing a user's role in `user_profiles`. The application role is never blindly trusted from the JWT `sub` claim.
- **Documentation**: We authored `SECURITY_MODEL.md` detailing the 4-layer security posture (Ingest, Database RLS, API Gateway, Client).

## 2. Scope Gaps (Onboarding, Storage, Supply Volumes)

**Finding**: The prototype assumed farmers were already registered, lacked storage/warehousing capabilities (a crucial aspect of market linkages), and did not surface arrival volumes (essential for price discovery).

**Remediation**:
- **Buyer Onboarding**: Added `POST /buyers/register` enabling self-service registration. Added an admin workflow (`GET /admin/buyers` and `PATCH /admin/buyers/{id}/verify`) to vet and approve buyers. Added an explicit RLS policy `USING (auth.uid() = owner_user_id OR verified = true)` to ensure unverified buyers cannot participate in the marketplace.
- **Warehousing Integration**: Introduced `storage_facilities` and `storage_bookings` tables. The `storage` router mirrors the logistics flow, enforcing physical capacity constraints (`quantity_qtl` sum against `capacity_qtl`) in real-time. Added full state machine (requested -> confirmed -> completed/cancelled).
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
