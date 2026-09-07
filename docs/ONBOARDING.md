# Onboarding a new mandi or crop

Demo seed is **5 Nashik APMCs × Onion, Tomato, Soybean, Maize**. That is a fixture, not the product ceiling.

## 1. Market row

Insert into `public.markets` with the **exact** `source_code` spelling used by data.gov.in for that APMC (`market` field). `lat`/`lng` must be valid. `district` must match `TARGET_DISTRICT` (or you will ingest then reject as `unknown_market`).

```sql
insert into public.markets (name, district, state, taluka, lat, lng, source_code, is_active)
values ('Pune Market Yard', 'Pune', 'Maharashtra', 'Haveli', 18.5204, 73.8567, 'Pune', true);
```

## 2. Commodity + aliases

If the crop is new, insert `commodities` (sanity band in Rs/quintal) then **one alias per source spelling**:

| source | source_key | notes |
|---|---|---|
| `data_gov_in` | API `commodity` string (`Soyabean` not `Soybean`) | required for ingest |
| `agmarknet` | scraper dropdown name | only if `ENABLE_AGMARKNET=1` |
| `sms` | uppercase English **and** Devanagari tokens | inbound SMS first-token match |

Never point ingestion at `commodities.name_en` alone — alias misspellings burn data.gov.in quota and write `unknown_commodity`.

## 3. Env

```
TARGET_DISTRICT=Pune
TARGET_STATE=Maharashtra
ENABLE_AGMARKNET=0
```

`DataGovInAdapter` only retries extra district spellings listed in `DISTRICT_SPELLINGS` for **that** district (Nashik↔Nasik). Add a pair there if the API uses a second spelling.

Agmarknet (optional) iterates seeded Nashik short names when `TARGET_DISTRICT` is Nashik/Nasik; other districts query the district name once. Keep it off on free PaaS (Selenium + Chrome).

## 4. Buyers / logistics (marketplace)

Verified buyers and godowns/trucks are rows in `buyers` / `logistics_options` (see `008_marketplace.sql` seed). Matching is local-first: same district, then distance, then price fit.

## 5. Apply SQL

`docs/SQL_APPLY.md` — run `001` … `011` in order on a new project.

## 6. Token-claims alignment (for AUTH_DB_ENFORCEMENT=rls)

When `AUTH_DB_ENFORCEMENT=rls`, minted tokens are forwarded to PostgREST as the
user credential.  Three things must match the hosted project:

1. **Legacy JWT secret enabled**: Supabase Dashboard → Settings → API → JWT Settings
   → enable "Use legacy JWT secret". This lets PostgREST verify HS256 tokens signed
   with `SUPABASE_JWT_SECRET`.

2. **`SUPABASE_JWT_ISSUER`** set in `.env`:
   ```
   SUPABASE_JWT_ISSUER=https://<your-ref>.supabase.co/auth/v1
   ```
   `mint_admin_token.py` reads this and adds `iss` to the payload.
   Without `iss`, PostgREST returns `PGRST301` (403 from the app).

3. **`SUPABASE_JWT_SECRET`** must match the project secret exactly (same settings page).

For development/CI the `SUPABASE_JWT_ISSUER` env var is left empty intentionally:
tokens omit `iss` and work with `AUTH_DB_ENFORCEMENT=app` (service-role client).
FakeSupabase in tests is unaffected by either mode.
