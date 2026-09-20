# Rollout Guide — Audit Fix Batch (commit `a442648`)

This guide takes the fixes from branch `main` (commit
`a442648`, 26 files: migration 036 + fixed 026/027, API fixes, tests, docs)
onto **your computer**, **GitHub `main`**, **Supabase**, and your **backend
hosting** — in the safe order, with verification at every step.

> **Order matters.** Apply the DATABASE migration **before** deploying the new
> backend code. The new storage/logistics endpoints call RPCs
> (`storage_booking_create`, …) that only exist after migration 036. The old
> booking endpoints were already broken (writes revoked by 031), so there is
> no working-state regression in either order — but migrations-first avoids
> `42883 function not found` errors from the new code.

---

## A. Your computer — get the code

```bash
cd /path/to/SIH26132

# 1. bring the branch down
git fetch origin

# 2. bring the changes to main
git checkout main
git pull origin main
```

No new Python dependencies were added — `pip install -r requirements.txt`
(or `make install-dev`) only if your env is stale.

Sanity check on your machine (offline tests only, no DB needed):

```bash
make ci-local          # ruff + full offline suite (DB tests skip without SUPABASE_DB_URL)
```

Expected: all pass. (Verified in CI-equivalent environment: **552 passed,
12 skipped** against a clean database install.)

---

## B. Supabase — apply the migrations

### B0. Back up first (non-negotiable)

Supabase Dashboard → **Database → Backups** → take a backup now
(or `pg_dump` with your connection string). 036 is idempotent and was
verified on clean installs, but it creates a unique index and swaps a foreign
key — if live data violates the new invariants you want a restore point.

### B1. Pre-check 1 — duplicate payments (blocks 036)

Migration 036 creates `uq_payments_one_per_offer` (one payment row per
offer). If your live data has multiple payments per offer, index creation
will fail. Run in Supabase **SQL Editor**:

```sql
SELECT offer_id, count(*) AS n
FROM public.payments
GROUP BY offer_id
HAVING count(*) > 1;
```

**If rows appear**, keep the newest payment per offer and archive/delete the
rest (review before running):

```sql
DELETE FROM public.payments p
USING public.payments keep
WHERE p.offer_id = keep.offer_id
  AND p.id <> keep.id
  AND (p.created_at, p.id) < (keep.created_at, keep.id);
```

**If zero rows** (expected on a young project) — continue.

### B2. Pre-check 2 — where your migration ledger stands

```sql
SELECT filename FROM public.schema_migrations ORDER BY filename;
```

Two common states:

| Ledger shows | Meaning | What happens on apply |
|---|---|---|
| last entry `025_events_claim_rpc.sql` | 026 never applied (it always failed) | Fixed 026/027 + 028–036 all run cleanly — events tables are created fresh |
| `026`/`027`/… up to `035` present | Ledger recorded them (manually or with forced apply) | Only 036 runs — fine |

Either way the apply below is safe. If the ledger disagrees wildly with
reality (e.g. 026 recorded but `public.events` missing), stop and reconcile
first — check with:

```sql
SELECT viewname FROM pg_views
WHERE schemaname='public' AND viewname LIKE '%live_events%';

SELECT column_name FROM information_schema.columns
WHERE table_schema='public' AND table_name='events'
ORDER BY ordinal_position;
-- expected: id, created_at, source_url, headline, event_date, commodity_id,
-- district, event_type, direction, magnitude, confidence, reasoning, raw_text,
-- reviewed_by, publication_date, source_document_id, event_hash, review_status
```

### B3. Apply

From your local clone (with `.env` filled):

```bash
# dry run first — now read-only safe (lists what would run, touches nothing)
make db-apply-dry

# real apply — takes seconds
make db-apply
```

`SUPABASE_DB_URL` in `.env` should be your project's connection string
(Supabase Dashboard → Project Settings → Database → Connection string;
session pooler on port 5432 works, use direct `db.<ref>.supabase.co:5432`
if DDL via pooler complains).

### B4. Verify the database

Run in Supabase SQL Editor — every query should match the stated expectation:

```sql
-- 1. ledger
SELECT count(*) FROM public.schema_migrations
WHERE filename = '036_marketplace_hardening.sql';          -- = 1

-- 2. the four booking RPCs exist
SELECT proname FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname='public' AND proname IN (
  'storage_booking_create','storage_booking_update',
  'logistics_booking_create','logistics_booking_update');  -- 4 rows

-- 3. one-payment-per-offer index
SELECT indexname FROM pg_indexes
WHERE indexname = 'uq_payments_one_per_offer';             -- 1 row

-- 4. payments.user_id FK is now RESTRICT
SELECT confdeltype FROM pg_constraint
WHERE conname = 'payments_user_id_fkey';                   -- 'r'

-- 5. dead grants revoked
SELECT has_function_privilege('authenticated',
  'public.nearest_market(double precision, double precision)', 'EXECUTE');  -- false

-- 6. events view healthy (fixes to 026/027)
SELECT count(*) FROM public.live_events_published;         -- runs without error
```

---

## C. Backend hosting — rebuild & redeploy

The repo ships `Dockerfile` + `docker-compose.yml` with two services:
`api` (N replicas) and `api-worker` (exactly **one** replica — the
scheduler). Both must pick up the new code.

```bash
# on the host (or via your platform's rebuild — Render/Railway/Fly/ECS etc.)
git pull origin main          # if deploying from a clone
docker compose up --build -d  # rebuilds api + api-worker

# verify
curl -f http://<host>:8000/readyz
```

If you deploy on a managed platform instead of raw Docker: trigger a
**rebuild/redeploy of both the web service and the worker** (not just the web
service). The SMS advice jobs (`sale_window` C13 fix) and forecast stamping
live in the worker.

No new environment variables are required.

### Operational changes to be aware of

- **`buyers.verified`** can now only be changed via the `buyer_verify` RPC
  (admin JWT) or `service_role`. If you have ops scripts that
  `UPDATE buyers SET verified=…` directly as `postgres`, prefix them with
  `SELECT set_config('app.buyer_verify_authorized','on',true);` or switch to
  the RPC.
- Direct double-payments are structurally blocked (unique index) — any
  internal tooling that inserts into `payments` will get a 23505 if it
  retries a payment that already exists; use `payment_create` (idempotent).

---

## D. Frontend / API consumers

Two contract changes to check in any frontend or Postman usage:

1. **Capacity errors are now 409 everywhere.** `POST /storage/bookings`
   used to return **400** "capacity exceeded"; it now returns **409** with an
   opaque detail (enforced inside the RPC under a row lock). Treat 409 on
   both `/storage/bookings` and `/logistics/bookings` as "capacity full".
2. **`PATCH` bookings now persist `notes`** (previously silently discarded).
   Nothing breaks, but notes you send will actually show up on GET.

Everything else (paths, payloads, success codes) is unchanged.
`POST /logistics/bookings` — which previously always failed — now works and
returns the booking row.

---

## E. CI (GitHub Actions)

Nothing to do — `.github/workflows/ci.yml` runs on the PR/merge. The DB job
rebuilds a clean database (ci_bootstrap + migrations 001→036) and runs the
full suite; this exact path was verified green before commit. Watch the
checks on the PR; they should pass.

---

## F. Post-deploy smoke checklist

```bash
# 1. liveness + readiness
curl -f https://<your-api>/health
curl -f https://<your-api>/readyz

# 2. facilities still list (public read)
curl -s https://<your-api>/api/v1/storage/facilities | head -c 300

# 3. markets nearby (RPC path, anon)
curl -s "https://<your-api>/api/v1/markets/nearby?lat=20.15&lng=74.44" | head -c 300

# 4. forecasts summary (day-1 selection fix)
curl -s https://<your-api>/api/v1/forecasts/summary | head -c 300
```

Then one authenticated flow through the app UI (or Postman collection):
list a lot → book storage (expect 201 + `status:"requested"`) → confirm the
booking (200) → verify notes persisted on the booking list.

---

## G. Rollback (if anything goes wrong)

- **Database**: restore the backup from B0 (Supabase Dashboard → Backups →
  Restore). There are no down-migration scripts; backup-restore is the path.
- **Code**: `git revert a442648` on `main` and redeploy, or redeploy the
  previous image tag.
- The old booking endpoints were already non-functional before this change,
  so a code rollback does not lose working behavior — only the hardening.
