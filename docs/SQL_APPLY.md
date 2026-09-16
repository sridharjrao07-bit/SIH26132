# Database Deployment and Migration Instructions

This document provides exact instructions for applying, verifying, and recovering database schema migrations, focusing on the complex event extraction pipelines (Migrations 025–028).

## Clean Installation

For a fresh environment, apply the migrations sequentially from `db/migrations/`:

```sh
psql -d $DATABASE_URL -f db/migrations/001_initial.sql
# ... apply up to 028 sequentially
psql -d $DATABASE_URL -f db/migrations/028_events_provenance_review_fixes.sql
```

## Upgrade and Recovery Paths

If you are upgrading an existing environment, you may encounter broken states from `026_live_events_view.sql` which referenced non-existent columns.

### Scenario A: Migration 026 Failed or is Absent
If `026` failed (e.g., throwing a column-does-not-exist error) or was skipped:
1. Ensure `025_events_claim_rpc.sql` has been applied successfully.
2. Skip attempting to apply `026` directly.
3. Apply `027_events_provenance_fixes.sql` first. It uses `CREATE OR REPLACE` for views and functions, bypassing the broken state.
4. Apply `028_events_provenance_review_fixes.sql` to finalize the schema, locking, and authorization corrections.

### Scenario B: Migration 027 Applied but Contains Flaws
Migration 027 was applied to some environments but omitted the `review_status` column and had race conditions in lock acquisition.
1. Leave `027_events_provenance_fixes.sql` in the applied state. Do NOT modify the file in place on production environments.
2. Apply `028_events_provenance_review_fixes.sql` as a forward migration. It creates the `review_status` column, backfills historical `legacy_reviewed` states, and replaces the flawed RPCs (`claim_source_document`, `review_event`, `publish_extracted_events_v2`) with corrected logic.

### Scenario C: Existing Incompatible Views
If you encounter errors about dropping dependent objects (e.g., `cannot drop function claim_source_document because other objects depend on it`):
1. Temporarily drop the dependent views manually.
2. Apply `028_events_provenance_review_fixes.sql` which will recreate `live_events_published` and `sale_window_headlines`.
3. If you have custom out-of-band views, recreate them after 028 completes.

## Verification Probes

After deployment, verify the state by running these probes as the `postgres` user:

```sql
-- 1. Verify review_status exists and constraints are applied
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'events' AND column_name = 'review_status';

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
```
