# Handoff: what to do next

**Status of this handoff:** everything described as DONE below is committed and
pushed. Nothing described as TODO has been started.

| | |
|---|---|
| Branch | `arena/01a0e3c9-sih26132` |
| HEAD | `e4c3875` |
| Remote | pushed, remote tip matches HEAD |
| Working tree | clean |
| Diff vs `main` (`43dec5c`) | 43 files changed, +11,234 / −71 |
| Tests | **970 passed, 40 skipped, 0 failed** |
| Lint | `ruff check .` clean |

```bash
git clone <repo> && cd SIH26132
git checkout arena/01a0e3c9-sih26132
source .venv/bin/activate   # or: python3.12 -m venv .venv && pip install -r requirements-dev.txt
```

---

## What is built (do not rebuild this)

| Piece | Path |
|---|---|
| Engine (pure Python, no I/O) | `direct/` — `value_chain`, `surplus`, `logistics`, `consolidation`, `allocation`, `fair_price`, `pipeline` |
| HTTP API (9 routes) | `app/routers/direct.py`, `app/schemas/direct.py` |
| Schema | `db/migrations/038_direct_channel.sql`, `039_direct_fulfilment.sql`, `040_seed_retail_prices.sql` |
| Retail data (live + snapshot) | `ingestion/dca_retail.py`, `ingestion/retail_loader.py`, `data/gov_retail_prices.csv` |
| Demo (offline, 5 acts) | `demo/direct_channel_demo.py` |
| Docs | `docs/DIRECT_CHANNEL.md` |

Run `python demo/direct_channel_demo.py` first — it is the fastest way to see
the whole argument and it needs no database.

### Verified (do not re-verify from scratch)

- Allocation is **provably optimal** — checked against brute-force enumeration
  of transportation-polytope vertices (Prüfer sequences), not trusted
- Farmer gain + consumer saving = total surplus, exactly, at every aggregation
- Stage attribution telescopes to the total absorption with no residual
- FFD packing within `11/9·OPT + 6/9`
- 970 tests pass; all 40 skips are in `ci/allowed-skips.txt`, so CI is green
- Both price anchors are real government data (see `docs/DIRECT_CHANNEL.md` §10)

---

## Supabase: what to keep, what to add, what to retire

The repo was built for SIH26132 (market linkage, price discovery) and has been
pivoted to SIH26033 (disintermediation). Both feature sets share a spine. This
section is the decision record for the database.

### The dependency direction (checked, not assumed)

Every foreign key runs **new → old**. No table created by migrations 001–037
references anything created by 038–040. Concretely, the new tables depend on
exactly three old ones:

| Old table | FKs from new tables | Why it is needed |
|---|---|---|
| `user_profiles` | 7 | plan generator, farmer, organiser, order owner |
| `commodities` | 5 | every plan, allocation, order and retail price row |
| `lots` | 2 | supply side of the matching problem |

**So the old schema is inert with respect to the new one.** It costs storage;
it cannot corrupt or constrain the new tables.

### KEEP — required (6 tables)

`user_profiles`, `commodities`, `lots`, plus three with no FK but which the new
work reads as data:

- **`markets`** — seeded with the 5 Nashik APMCs the entire scenario is set in
- **`prices`** — the real mandi data that *is* the farm-gate anchor; migration
  040 pairs each retail observation against it
- **`commodity_alias`** — ingestion uses it to map source spellings

Nothing here is negotiable. Removing any of these breaks the new schema or
silently removes the data the headline numbers come from.

### KEEP for now — old features, still working (do not drop)

`alerts`, `notification_log`, `forecasts`, `events`, `weather_daily`, `buyers`,
`offers`, `payments`, `grievances`, `fpo_members`, `logistics_bookings`,
`logistics_options`, `storage_bookings`, `storage_facilities`, `ingestion_log`,
`job_locks`.

**Recommendation: leave them in place and simply do not demo them.** Four
reasons, in order of weight:

1. **Dropping is not even persistent.** `scripts/apply_migrations.py` replays
   001–037 on any fresh database, so a dropped table reappears on the next
   fresh deploy. To make removal stick you would have to edit the historical
   migrations — which breaks the `test_migration_coverage` ratchet and
   desynchronises every already-migrated environment.
2. **`DROP` is irreversible.** No undo, no `ALTER` back.
3. **18 of the 20 routers serve these tables** (`alerts`, `buyers`,
   `forecasts`, `grievances`, `intelligence`, `logistics`, `matching`,
   `offers`, `payments`, `prices`, `storage`, …). Dropping their tables
   converts working endpoints into 500s. Roughly 63 test-file references touch
   these tables.
4. **They cost almost nothing.** Empty or low-traffic tables are a rounding
   error next to the risk.

The pivot changed what you *demonstrate*, not what has to be destroyed.

### If they genuinely must be retired — do it reversibly

If the decision is made to slim the schema, move rather than drop. A new
**forward** migration (`041_retire_sih26132.sql`, added at the end, never by
editing 001–037):

```sql
create schema if not exists legacy;

-- Reversible: one ALTER brings it straight back.
alter table public.forecasts          set schema legacy;
alter table public.alerts             set schema legacy;
alter table public.notification_log   set schema legacy;
alter table public.events             set schema legacy;
alter table public.weather_daily      set schema legacy;
alter table public.buyers             set schema legacy;
alter table public.offers             set schema legacy;
alter table public.payments           set schema legacy;
alter table public.grievances         set schema legacy;
alter table public.fpo_members        set schema legacy;
alter table public.logistics_bookings set schema legacy;
alter table public.logistics_options  set schema legacy;
alter table public.storage_bookings   set schema legacy;
alter table public.storage_facilities set schema legacy;
```

Then, **in the same change set**, disable the corresponding routers in
`app/routers/__init__.py` — otherwise the app keeps serving routes against
tables that are no longer at `public.*` and every one of them 500s.

Recovery if it was a mistake:

```sql
alter table legacy.forecasts set schema public;   -- one line per table
```

Only once the retirement has survived a full demo cycle should anyone consider
`drop schema legacy cascade`. Not before.

### Sequencing with P0

Do this **after** P0 (validating the migrations), never before. If 038–040 fail
to apply and you have already re-homed old tables, you cannot tell whether the
failure is in the new migrations or a side effect of the retirement.

---

## TODO, in priority order

### P0 — Validate the database layer (highest risk)

**Migrations 038, 039 and 040 have never executed against a real Postgres.**
They are written but entirely unverified. This is the single largest risk in
the project: everything else has been tested, this has not.

There is no Postgres in the sandbox this was built in, so this could not be
done. It needs a real Supabase project or a local Postgres 16.

```bash
export SUPABASE_DB_URL="postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres"

# See what would run first — catches ordering and filename problems cheaply.
python scripts/apply_migrations.py --dry-run

python scripts/apply_migrations.py
```

**Acceptance criteria:**
1. All 41 migrations apply cleanly in order (040 last).
2. Re-running `apply_migrations.py` is a no-op, not an error.
3. `psql "$SUPABASE_DB_URL" -c "\d public.direct_orders"` shows the table with
   `chk_order_shares_reconcile` and `chk_mutual_gain` present.
4. Seed check returns rows:
   ```sql
   select district, price_date, retail_price, source_ref
   from public.retail_prices order by price_date desc limit 5;
   ```

**Likely failures and what they mean:**
- `relation "commodities" does not exist` — 040 joins `commodities` on
  `lower(name_en) = 'onion'`; if your seed spells it differently the row is
  skipped silently. Verify with the query above rather than assuming.
- Missing `public.set_updated_at()` — confirmed present at
  `db/migrations/001_schema.sql:175`, so 038's triggers should resolve.
- Any error in 039 leaves 038 applied. Fix forward; do not hand-edit applied
  migrations.

Then exercise the write path, which no test has touched:

```sql
-- as an authenticated user (set request.jwt.claims, or use the API)
select public.consumer_node_upsert('Test RWA', 'rwa', 'Nashik');
select public.group_buy_create('<onion-commodity-uuid>', now() + interval '2 days', 100, 90);
select public.group_buy_join('<group-buy-uuid>', 20.0);
```

**Concurrency check worth actually running** — `group_buy_join` takes
`SELECT … FOR UPDATE` on the group row so two simultaneous joins cannot lose an
order. Open two psql sessions and join concurrently; `committed_qtl` must equal
the true sum of member quantities, not one join's value.

### P1 — Verify the live retail adapter

`ingestion/dca_retail.py` has never talked to the real API (no key was
available). It is built to the same pattern as the working mandi adapter, and it
fails loudly rather than silently, but it is unproven.

```bash
# Find the resource id: open the "Essential Commodity: State-wise Daily
# Wholesale and Retail Price of Onion" dataset on data.gov.in, click API,
# copy the UUID from the URL shown.
export DATA_GOV_IN_API_KEY="<your key>"
export DCA_RETAIL_RESOURCE_ID="<uuid>"
# per-commodity alternative:
# export DCA_RETAIL_RESOURCE_IDS="onion=<uuid>,tomato=<uuid>,potato=<uuid>"

python -c "
from ingestion.retail_loader import latest_retail_price
print(latest_retail_price('Onion','Maharashtra'))
# must print ('live', ...) - if it prints ('snapshot', ...) the live path failed
"
```

**Acceptance criteria:** returns `origin == 'live'`; prices land in
500–10,000 ₹/quintal for onion; the loader falls back to `snapshot` (not an
error) when the key is removed; it **raises** when both sources are missing.

### P2 — Wire the engine to the database

Both of these are currently hardcoded in Python, which makes two claims in
`docs/DIRECT_CHANNEL.md` **false as written**:

- `DEFAULT_CHAIN_PROFILES` in `direct/pipeline.py:341` — the
  `value_chain_profiles` table (038) is created but **never read and never
  seeded**. So "a district officer can retune the model without a deploy" is
  not true yet.
- Retail price — now loaded from real data, but by the demo rather than by the
  engine/API. `app/routers/direct.py` should call
  `ingestion.retail_loader.latest_retail_price()` when the caller does not
  supply a `retail_price`.

Work: add a loader that reads `value_chain_profiles` (falling back to the
hardcoded defaults when the table is empty), thread it through `DirectConfig`,
and seed `value_chain_profiles` from `DEFAULT_CHAIN_PROFILES` in a migration.
Then correct or delete the two claims in the docs.

### P3 — Tighten the retail anchor

The Maharashtra retail row is the **All-India average** (₹53.92/kg, reported
16 Sep 2026), not a Nashik bazaar survey. The row's `note` column says so and
migration 040 documents it, but a city-level figure would be better. Options:
a field survey recorded through the `retail_price_record` RPC, or a
Nashik-specific resource if one is published.

### P4 — React UI (explicitly out of scope so far)

`web/` was deliberately untouched. The API is ready for it; `/api/v1/direct/*`
endpoints are self-contained and the economics routes need no database.

---

## Constraints to respect

- **Work only on `arena/01a0e3c9-sih26132`.** Do not create, switch to, or push
  any other branch.
- **Never commit credentials.** `.env` is not in the repo; only `.env.example`.
- `tests/test_env_example_sync.py` enforces that every `Settings` field appears
  in `.env.example` **and** vice versa — adding a setting without updating
  `.env.example` fails the build.
- `tests/test_privileges.py::test_migration_coverage` is a literal count
  ratchet (currently **41** = migrations 001–040 plus `003b`). Adding a
  migration requires bumping it.
- `tests/test_api_docs_sync.py` requires `docs/API.md` to match the routes.
  After any route change: `PYTHONPATH=. python scripts/generate_api_docs.py`.
- Run tests with:
  ```bash
  RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 python -m pytest tests/ -q
  ```
  Check skips against `ci/allowed-skips.txt`; CI fails on any unlisted reason.

## Known traps (each already cost time once)

- **FastAPI 0.141 wraps `include_router()` in `_IncludedRouter`.** Filtering
  `app.routes` for a path returns nothing. Verify registration with
  `app.openapi()["paths"]`.
- **Supply is farm-gate quintals; demand is doorstep quintals.**
  `farm_qtl × w = delivered_qtl`. Getting this wrong produces a ~3% shortfall
  on every order that looks like a rounding error.
- **The farmer's fallback is `P`, not `P / w_trad`.** He is paid for every
  physical quintal at the mandi. The older per-consumer-quintal formulation
  produced per-lane gains that did not roll up.
- **Two forecast tests are IST-sensitive.** They seed rows from
  `get_ist_today()`, because `/forecasts/summary` filters on the IST date.
  Using UTC `date.today()` makes them fail for ~5.5 hours every day.
- **`_verdict` in `direct/fair_price.py` keys off margin share, not farmer
  share.** Reverting to share-alone resurrects a self-contradictory verdict
  ("healthy, limited headroom" for a chain the engine improves by +64%).
- **The DCA dataset mixes ₹/kg and ₹/quintal in one column.** Normalise at the
  boundary; a kg figure passed through as quintals is wrong by 100× and still
  looks plausible.
- **DCA `_normalise` must key on `(state, date)`.** Date alone lets one state's
  wholesale overwrite another's.

## Definition of done

P0 and P1 closed, i.e. migrations applied to a real Postgres, the write-path
RPCs exercised (including the concurrent-join check), and the live retail
adapter returning `origin == 'live'`. At that point the claim "this works" is
backed by execution rather than by tests against a double.
