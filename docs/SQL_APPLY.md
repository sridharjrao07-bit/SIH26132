# Database Deployment and Migration Instructions

This document provides exact instructions for applying, verifying, and recovering database schema migrations, focusing on the complex event extraction pipelines.

## Clean Installation

The primary, safe method to apply migrations is using the ledger-driven Python script. It automatically tracks applied migrations in the `schema_migrations` table and applies only the pending ones.

```sh
# Using Make (preferred)
make db-apply

# Or using Python directly
python scripts/apply_migrations.py
```

### Manual Fallback

If you cannot run the Python script (e.g. missing dependencies), you can apply the migrations manually in sequential order up to `034` using `psql`.

```sh
psql -d $DATABASE_URL -f db/migrations/001_schema.sql
# ... apply up to 034 sequentially
psql -d $DATABASE_URL -f db/migrations/034_fix_indexes.sql
```

## Upgrade and Recovery Paths

If you are upgrading an existing environment, you may encounter broken states from partial manual patches or failed earlier migrations (026, 027, 028).

**Golden Rule:** If a migration failed but the transaction was committed or partial schema modifications exist, DO NOT attempt to modify past migration files or re-run them out of sequence. Always finish with `029_events_provenance_review_fixes_v2.sql`.

### Scenario A: Clean state up to 025 (026 Failed or is Absent)
1. Skip attempting to apply `026`, `027`, or `028` directly.
2. Apply `029_events_provenance_review_fixes_v2.sql`. It includes all schema fixes (creating `review_status`, backfilling legacy records, and recreating views and RPCs).

### Scenario B: 027 or 028 Applied but Contains Flaws
Migration 027 omitted the `review_status` column and had race conditions. Migration 028 lacked robust type casting and proper runner snapshots.
1. Leave `027` and `028` in their applied states. Do NOT modify the files in place on production environments.
2. Apply `029_events_provenance_review_fixes_v2.sql` as a forward migration. It creates the `review_status` column using `USING` clauses to gracefully handle manual text-column patches, backfills historical `legacy_reviewed` states, and replaces the flawed RPCs (`claim_source_document`, `review_event`, `publish_extracted_events_v2`) with corrected logic.

### Scenario C: Existing Incompatible Views
If you encounter errors about dropping dependent objects (e.g., `cannot drop function claim_source_document because other objects depend on it`):
1. Temporarily drop the dependent views manually.
2. Apply `029_events_provenance_review_fixes_v2.sql` which will recreate `live_events_published` and `sale_window_headlines`.
3. If you have custom out-of-band views, recreate them after 029 completes.

## Verification Probes

After deployment, verify the state by running these probes as the `postgres` user:

```sql
-- 1. Verify review_status is a valid ENUM type
SELECT column_name, data_type, udt_name
FROM information_schema.columns 
WHERE table_name = 'events' AND column_name = 'review_status';
-- Expected: data_type='USER-DEFINED', udt_name='review_state'

-- 2. Verify legacy reviews were reconciled
SELECT review_status, count(*) 
FROM events 
WHERE reviewed_by IS NOT NULL 
GROUP BY review_status;
-- Expected: If historical reviews existed, they should be in 'legacy_reviewed'.

-- 3. Verify RPC existence and security definitions
SELECT p.proname, p.prosecdef 
FROM pg_proc p 
JOIN pg_namespace n ON p.pronamespace = n.oid 
WHERE n.nspname = 'public' 
  AND p.proname IN ('claim_source_document', 'review_event', 'publish_extracted_events_v2');

-- 4. Verify view security
SELECT grantee, privilege_type 
FROM information_schema.role_table_grants 
WHERE table_name = 'live_events_published';
-- Expected: service_role has SELECT, public does NOT.
```
