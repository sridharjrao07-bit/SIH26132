# Migration Recovery Guide

## Recovering from Failed Migrations (025 and 026)

Migrations `025_events_claim_rpc.sql` and `026_live_events_view.sql` were deployed with schema mismatch errors referencing nonexistent columns. Depending on your environment, the migration runner may have failed at `025` or `026`.

`027_events_provenance_fixes.sql` is a forward migration that uses `CREATE OR REPLACE` and `DROP IF EXISTS` to cleanly recreate the faulty objects without dropping the tables.

### If Migration 026 Failed

If your migration runner aborted because `026` could not be applied:
1. Ensure your migration history table reflects `026` as unapplied (or revert the history entry if the runner incorrectly marked it as complete despite the error).
2. Do **NOT** manually apply `026`. 
3. Run `027_events_provenance_fixes.sql` directly. The migration runner will execute `025` (if not already applied), fail on `026` if you don't remove it from the run list.
4. **Action**: If you are using a strict migration runner, mark `026` as ignored/resolved in the runner's history, then deploy `027`. For example, in Supabase CLI, you might need to run `supabase migration repair --status applied 026_live_events_view` and then push the remaining migrations.

### Clean Installations
If you are bootstrapping a completely new database, `025` and `026` will execute successfully (or fail on `026`). If they fail, the recommended approach for clean installations is to merge `025`, `026`, and `027` manually, or use `supabase db reset` which applies them in order. 
*Note: Due to `026` failing, a clean `db push` might fail. If so, modify `026` locally just to pass, and allow `027` to overwrite it.*
