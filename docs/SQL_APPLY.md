# SQL to apply (Supabase)

Run these **in order** on the project SQL editor (Dashboard → SQL → New query).  
Paste **one file at a time**, run, confirm success, then the next.

If this is a **new** project, start at `001`.  
If you already applied a senior-review pass through `007`, start at `008`.

| # | File | What it does |
|---|---|---|
| 1 | `db/migrations/001_schema.sql` | Core schema: markets, commodities, prices, forecasts, profiles, alerts, RLS, `set_updated_at` |
| 2 | `db/migrations/002_seed.sql` | Nashik APMCs + Onion/Tomato/Soybean/Maize aliases |
| 3 | `db/migrations/003_security_patch.sql` | Signup cannot self-elevate `role`; unique market `source_code` |
| 4 | `db/migrations/003b_admin_set_role_grants.sql` | `admin_set_role` execute grants |
| 5 | `db/migrations/004_nearby_markets.sql` | `nearby_markets` earthdistance RPC |
| 6 | `db/migrations/005_forecast_stale_fn.sql` | `mark_stale_forecasts` |
| 7 | `db/migrations/006_job_locks.sql` | `claim_job_lock` / `release_job_lock` + `nearest_market` |
| 8 | `db/migrations/007_security_hardening.sql` | Tighten SECURITY DEFINER grants |
| 9 | `db/migrations/008_marketplace.sql` | Buyers, lots, offers, payments, grievances, logistics options, FPO role, unique phone |
| 10 | `db/migrations/009_logistics_bookings.sql` | Book a godown/truck against a lot |
| 11 | `db/migrations/010_lot_grade_check.sql` | `lots.grade` must be FAQ / General / Special |

After `008`, seed includes Nashik buyers (traders, processor, institutional, eNAM) and MSWC godowns / truck unions.

Elevate a real `auth.users` uuid to admin (SQL editor, as postgres):

```sql
select public.admin_set_role('<auth.users uuid>'::uuid, 'admin');
```

FPO:

```sql
select public.admin_set_role('<auth.users uuid>'::uuid, 'fpo');
```
