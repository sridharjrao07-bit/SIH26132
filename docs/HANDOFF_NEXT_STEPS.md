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
| Tests | **764 passed, 44 skipped, 0 failed** |
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

## Repository layout after the pivot

The SIH26132 feature code has been **moved, not deleted**, into `legacy/`
(`git mv`, so history is preserved and a single `git mv` restores anything):

- `legacy/routers/` — 13 retired routers (`forecasts`, `alerts`, `buyers`,
  `offers`, `payments`, `grievances`, `matching`, `storage`, `intelligence`,
  `dashboard`, `admin`, `sms`, old `logistics`)
- `legacy/notifications/`, `legacy/schemas/`, `legacy/demo/`, `legacy/tests/`

The retained app serves six groups: `markets`, `commodities`, `prices`, `lots`,
`me`, `direct`. `legacy/` is excluded from linting.

**Kept in the active tree on purpose** (the new work depends on them, not
sentiment): `app/schemas/marketplace.py` (`lots.py`/`profile.py` import it),
`notifications/{alert_checker,prices,sale_window,sms_gateway}.py` (the scheduler
and `profile.py` import them), `app/services/{marketplace,jobs}.py`, and the
mandi + retail ingestion adapters that supply both price anchors.

See `legacy/README.md` for what to update when restoring a file.

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

The applier prefers the pure-Python `pg8000` driver and falls back to
`psycopg2`. The driver is imported **lazily inside `_connect()`** on purpose:
several tests import this script to enumerate migrations, and a module-level
`import pg8000.dbapi` turns a missing optional driver into an import error that
fails the whole test file. `scripts/exercise_rpc.py` exercises the write-path
RPCs against a live database — that is the fastest way to run the acceptance
checks above.

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
order, and recomputes `committed_qtl` as `sum(m.qtl)` rather than incrementing
it. This is now scripted, so you do not need two psql sessions:

```bash
python scripts/exercise_rpc.py
```

It was rewritten from a print-only smoke script into a verifier that asserts and
exits non-zero. The contention check opens **two independent connections**,
releases them onto the same group with a `threading.Barrier`, and asserts
`committed_qtl == sum(members.qtl)`. It joins with **different** quantities
(30 and 40) on purpose: with equal quantities a lost update is coincidentally
invisible, because 20+20 read stale twice still lands on 40. 30 and 40 make any
lost increment show up as `committed_qtl` disagreeing with the members table.

It also covers `direct_plan_commit` (including idempotency on `plan_id`),
`direct_impact`, `direct_order_trace` on an unknown token, and that a join
exceeding the target is refused with the real headroom.

**Three things were broken and are fixed, all of which would have failed during
your run:**

1. `exercise_rpc.py` did a module-level `import pg8000.dbapi`, but pg8000 is in
   neither requirements file — only `psycopg2-binary` is installed. The script
   could not run at all in a fresh clone.
2. `apply_migrations._connect` only enabled SSL when the URL contained
   `sslmode=require`. Supabase's 5432 connection refuses plaintext and its
   connection strings carry no `sslmode`, so `apply_migrations.py --dry-run`
   would have failed at step 3 with what looks like a network error. SSL is now
   on unless `sslmode=disable` is explicit.
3. Nothing ever asserted `origin == 'live'`; the one existing test accepted
   either value and so was vacuous for the live branch. Four tests added,
   including one proven non-vacuous by breaking the branch and watching it fail.

**Verified statically, so your SQL assertions will hold:** 041 seeds 3 rows with
5 stages each and `is_active` true, and its `ON CONFLICT` target matches
`uq_value_chain_profiles_scope` exactly. 040 seeds 5 rows into `retail_prices`,
and its `ON CONFLICT` target matches `uq_retail_price_record` from 038 — which
depends on 002 having seeded an `onion` commodity row (it has).

### P1 — Live retail adapter: fail-fast bounds added (code done, **offline fallback verified**, live run still unverified)

`ingestion/dca_retail.py` previously used a 30 s read timeout with tenacity
backoff. One unreachable host therefore cost ~65 s **per page**, and
`fetch_retail` walks several pages — which reads to a caller as a hang.

Now bounded at three levels, all configurable:

| Bound | Default | Env |
|---|---|---|
| connect | 3 s | `DCA_RETAIL_CONNECT_TIMEOUT_SECONDS` |
| read | 5 s | `DCA_RETAIL_TIMEOUT_SECONDS` |
| whole paginated fetch | 20 s | `DCA_RETAIL_DEADLINE_SECONDS` |

A dead host now fails in ~1.6 s and the loader falls back to the committed
snapshot, logging `retail_live_fetch_failed_using_snapshot`. The bounds are
resolved per construction, so they can be tuned without a restart, and a
garbage value degrades to the safe default rather than raising at import.

**Verified offline:** with no network and a placeholder key,
`latest_retail_price()` completes in ~1.6 s and falls back to the committed
snapshot, so the demo can never hang. `tests/test_retail_anchor.py` covers the
kg→quintal conversion, the 500–10,000 plausibility band, and that the loader
raises rather than guessing when nothing is available.

**Still unverified:** the adapter has never called the real API (no key). To
close this, set `DATA_GOV_IN_API_KEY` and `DCA_RETAIL_RESOURCE_ID` and confirm
`latest_retail_price()` returns `origin == 'live'`.

```bash
export DATA_GOV_IN_API_KEY="<key>"
export DCA_RETAIL_RESOURCE_ID="<uuid>"   # dataset page on data.gov.in -> API
python -c "from ingestion.retail_loader import latest_retail_price; \
           print(latest_retail_price('Onion','Maharashtra'))"
```

### P2 — Engine wired to the database (code done, **API boot verified**, live run still unverified)

Both hardcoded-in-Python dependencies are now overridable from Postgres.

**Retail price is optional.** `retail_price` / `retail_price_per_qtl` default
to `None` in `app/schemas/direct.py`; `_resolve_retail_price` in
`app/routers/direct.py` fills an omitted one from the live anchor (which falls
back to the snapshot). Supply the price and the endpoint is still a pure
function — no database, no network. That seam is deliberate: it is what keeps
the arithmetic hand-checkable.

**Chain profiles are read from the table.** `_load_chain_profiles` queries
`value_chain_profiles` for `is_active = true AND channel = 'traditional'` and
threads the result into `DirectConfig`. Precedence is commodity-specific
override → category override → built-in default, and an empty, missing or
unparsable table is *not* an error — the built-in `DEFAULT_CHAIN_PROFILES` is
used instead, so a half-migrated database cannot take the planning endpoints
down.

**Boot verified with a placeholder backend.** `uvicorn app.main:app` starts
cleanly with `SUPABASE_URL=https://placeholder.supabase.co` and a JWT-shaped
dummy anon key; `/health` returns `ok` and `/openapi.json` serves 24 paths.
`/api/v1/direct/rupee` and `/api/v1/direct/config` are pure engine and return
the audited numbers (`farmer_share_pct` 48.1155, `avoidable_per_farm_qtl`
2032.2147, λ 1.382475). Database-backed routes return a clean `503` rather than
a crash, and a missing required field is a `422`, not a 500.

Note that **`DATA_GOV_IN_API_KEY` has no default** — the app fails closed at
startup without it, even locally. That is documented in
`docs/DEMO_RUNBOOK_DIRECTLINK.md` §1 and §4.

**Migration 041** seeds `value_chain_profiles` for `vegetable`, `oilseed` and
`cereal`, and adds the natural unique key
`(category, scope_district, channel, coalesce(commodity_id, …))`. The key
matters: the table's only prior unique constraint was a random-uuid primary
key, so a plain `ON CONFLICT DO NOTHING` would have had nothing to conflict on
and would duplicate every row on re-run. `EXPECTED_MIGRATIONS` is bumped 41 →
42.

**Still unverified:** `value_chain_profiles` has never been queried against a
real Postgres, and migration 041 has never been applied. See P0.

### P3 — Tighten the retail anchor (audit now guards the anchors)

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

## The credential-gated half — one command

```bash
export SUPABASE_DB_URL="postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres"
export DATA_GOV_IN_API_KEY="<key>"
export DCA_RETAIL_RESOURCE_ID="<uuid>"
python scripts/verify_live_stack.py
```

Ten checks in dependency order: preflight, static SQL lint, dry run, apply,
**idempotency**, the two seeded-row assertions, the write path including the
concurrency check, the live retail adapter, the snapshot fallback, and the
offline rehearsal. Exits non-zero on any failure, one PASS/FAIL line each with
the numbers.

`docs/AGENT_LOOP_PROMPT.md` is a ready-made prompt to hand another agent to run
this and iterate on failures. It includes the sandbox-reset repair (this repo has
reset eight times, rewinding git to baseline and deleting `.venv`), the known
failure modes, and an explicit "what a green run still does not prove" section.

## Before the demo: one command

    python scripts/rehearse_demo.py

Runs the audit, the five-act demo, the migration linter, the test suite and
ruff, then prints one PASS/FAIL line per step. `--fast` skips the suite. Takes
about seven seconds. If it says `READY`, the demo is safe to run.

`scripts/audit_numbers.py` is the part worth knowing about. It re-derives every
headline number from `data/` without importing the engine, so it catches a
wrong derivation that the test suite cannot: the suite proves the engine is
self-consistent, and a chain with wrong stage parameters is perfectly
self-consistent. Every figure reconciles to four decimal places.

Its one real limitation, stated in its own output: it checks the *derivations*,
not the *anchors*. The engine calibrates to whatever (farm, retail) pair it is
handed, so a plausible-but-wrong price still reconciles exactly. It rejects
impossible anchors (₹12/quintal, retail below farm, anchors months apart) but
not a subtly wrong one. `tests/test_retail_anchor.py` covers the plausibility
band. Do not present a number from the audit as "verified against the market"
— it is verified against the data, which is what "real data" means.

## Definition of done

P0 and P1 closed, i.e. migrations applied to a real Postgres, the write-path
RPCs exercised (including the concurrent-join check), and the live retail
adapter returning `origin == 'live'`. At that point the claim "this works" is
backed by execution rather than by tests against a double.
