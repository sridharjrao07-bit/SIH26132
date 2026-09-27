# Demo Runbook — DirectLink (SIH26033)

One page to run the DirectLink demo. Everything below is computed from real
data; every number quoted here was verified against the source CSVs by
`scripts/audit_numbers.py`, which re-derives them without importing the engine.

> **Not the Krishi Bazaar runbook.** `DEMO_RUNBOOK.md` describes the pre-pivot
> concept (PWA, mock API, sale windows) and references scripts now archived in
> `legacy/demo/`. It is kept for history only. This file is the one to follow.

---

## 0. Pre-flight — T-30 minutes

```bash
python scripts/rehearse_demo.py
```

Runs the numerical audit, the five-act demo, the migration linter, the test
suite and ruff, then prints one PASS/FAIL line per step. Seven seconds. If it
does not say `READY`, do not present — read the failing line and fix that.

If you want just the fast parts (no suite): `python scripts/rehearse_demo.py --fast`.

What must be green, and what it proves:

| Step | Proves |
|---|---|
| `numbers` | Every headline figure reconciles independently, and both price anchors are plausible |
| `demo` | The five acts run end to end on real data |
| `sql` | Migrations are statically sound, so 038–041 will apply |
| `tests` | 724 tests, 0 failed |
| `lint` | `ruff` clean |

---

## 1. Plan A — the full backend (needs credentials)

Needs in `.env`:

| Key | Why |
|---|---|
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | your project |
| `SUPABASE_JWT_SECRET` | must match, or **every** authed call 401s |
| `DATA_GOV_IN_API_KEY` | **required** — the app fails closed at startup without it |
| `DCA_RETAIL_RESOURCE_ID` | makes the retail anchor live rather than snapshot |

Then:

```bash
python scripts/apply_migrations.py --dry-run   # see what would run
python scripts/apply_migrations.py             # then apply
python scripts/exercise_rpc.py                 # exercises the write-path RPCs
RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 APP_ENV=development \
  .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**`DATA_GOV_IN_API_KEY` has no default.** It is a required `Settings` field, so
the app will not boot without it — even for a purely local run. A placeholder
string is enough to boot; it only needs to be real for the live retail adapter.

---

## 2. Plan B — engine only (guaranteed to work, no credentials)

This is the safe fallback, and on its own it carries the whole argument:

```bash
.venv/bin/python demo/direct_channel_demo.py
```

No database, no network, no keys. Reads the farm gate from
`data/gov_prices_60days.csv` and the retail anchor from
`data/gov_retail_prices.csv` (or live, if the adapter is configured). Prints the
five acts. If this runs, the demo runs.

To also show the HTTP surface with a dummy backend:

```bash
RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 APP_ENV=development \
SUPABASE_URL=https://placeholder.supabase.co \
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlIn0.abcdefghijklmnopqrstuvwxyz1234567890 \
SUPABASE_SERVICE_ROLE_KEY=$SUPABASE_ANON_KEY \
SUPABASE_JWT_SECRET=ci-placeholder-jwt-secret-32b-min \
DATA_GOV_IN_API_KEY=placeholder \
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The anon key must be **JWT-shaped** — the Supabase SDK rejects anything else at
construction time. Endpoints that need the database return a clean `503`, not a
crash. `/api/v1/direct/config` and `/api/v1/direct/rupee` are pure engine and
work fully.

---

## 3. The demo, act by act — what to say

### Act 1 — the leak

> "The farmer is paid ₹2,226 a quintal. You pay ₹5,392. Where does the other
> ₹3,166 go?"

The chain is fitted to that observed pair (5 stages, λ = 1.3825). Per-stage takes:
village trader ₹196 (8.2%), commission agent ₹258 (10.8%), wholesaler ₹509
(21.2%), distributor ₹434 (18.1%), retailer ₹1,004 (41.8%). Total absorbed
₹2,401 per farm quintal, on top of 14.2% physical spoilage.

Then the number that matters:

> "Of that ₹2,401, **₹2,032 — 85% — is margin**. ₹369, 15%, is real handling
> work. And the farmer keeps **48 paise** of your rupee."

Pass-through 0.4695: a ₹1 move at the farm reaches the shelf as 47 paise.

**If asked how 85% is derived:** margin is the take net of cost; it is measured
against *absorption* (₹2,401), not the ₹3,166 spread. Against the spread it would
be 64%, which is wrong. `scripts/audit_numbers.py` recomputes it independently.

**If asked whether 48% or 41% is right:** both. 48.1% is the farmer's share on a
*delivered* basis, `(farm/w)/retail`, where `w = 0.858` accounts for spoilage.
41.3% is the naive `farm/retail`. The engine reports both, separately labelled.

### Act 2 — the trade

One lane: Lasalgaon → a Nashik housing society, 62 km.

| | today | direct | |
|---|---|---|---|
| Farmer is paid | ₹2,226 | ₹3,663 | **+64.5%** |
| Consumer pays | ₹5,392 | ₹3,890 | **−27.9%** |

> "Intermediaries go from five to zero. The only margin left is a 3% platform
> fee — 2.9% of what the consumer spends."

The gain is a theorem, not a promise: the direct price is constructed so the
farmer is above his mandi fallback and the consumer below the shop, by
construction.

### Act 3 — the truck

One society orders 2 tonnes. A truck carries 9.

- 1 society: ₹90/qtl of freight for a 22%-full truck
- 24 societies pooled: ₹22/qtl at 89% fill — **4.0× cheaper**
- Below 76 qtl the truck loses money

> "Consolidation is not a convenience feature. It is the reason the direct
> channel can serve a small buyer at all."

### Act 4 — the plan

60 farmer lots, 25 consumer groups, one transportation problem.

- Farmer gain **₹1,246,216 (+72.8%)**
- Consumer saving **₹1,283,602 (−29.2%)**
- Total surplus **₹2,529,818**, platform fee ₹89,309 (2.9%)

Four correctness checks print ✓: surplus reconciles, the allocation is optimal
(no improving shift remains), no lane over-sells a lot, every lane is mutual-gain.

The plan id is a deterministic hash of the inputs — `DP-7b948ea7f328eff5` —
which is what makes the settlement auditable later.

### Act 5 — the receipt

> "This is the QR code on the crate. Any buyer can scan it and see exactly where
> their money went."

Farmer 94.9% (₹3,558/qtl), logistics 2.2% (₹83/qtl), platform 2.9%. The
counterfactual is stored alongside the actual — ₹2,110 → ₹3,558 at the mandi,
₹5,323 → ₹3,808 at the shop — so the claim can be audited, not taken on trust.

---

## 4. If it breaks

| Symptom | Cause | Fix |
|---|---|---|
| App won't start, `data_gov_in_api_key Field required` | no default for that field | set it to any placeholder string |
| App won't start, `Invalid API key` | anon key is not JWT-shaped | use the dummy JWT in §2 |
| `503` on `/api/v1/direct/impact` | no real Supabase | expected; that endpoint needs the DB. Use `/rupee` and `/config` instead |
| Retail line says `[snapshot]` | `DATA_GOV_IN_API_KEY` or `DCA_RETAIL_RESOURCE_ID` unset | expected offline; the committed snapshot is used and the numbers are identical |
| `403` on every authed call | `SUPABASE_JWT_SECRET` mismatch | match the project secret |
| Audit reports an anchor problem | a CSV changed | read the message; it names the bound that was breached |

The offline fallback for everything is §2. It needs nothing but Python.

---

## 5. What to say about accuracy

Be straight about this, because it is the question that decides whether a judge
trusts the rest:

- **Both price anchors are real.** Farm gate is a real data.gov.in mandi export
  (Lasalgaon onion modal, 26 Sep 2026). Retail is the Ministry of Consumer
  Affairs daily dataset. `scripts/audit_numbers.py` re-derives every figure from
  those CSVs without importing the engine, and all eleven reconcile to four
  decimal places.
- **The chain parameters are modelled, not measured.** Stage margins, costs and
  losses come from the engine's reference vegetable chain, then calibrated
  (λ = 1.3825) to reproduce the observed farm→retail pair. The *split* between
  margin and work is a model output, not a measurement.
- **The audit checks derivations, not anchors.** The engine calibrates to
  whatever pair it is given, so a plausible-but-wrong price still reconciles
  exactly. It rejects impossible anchors; `tests/test_retail_anchor.py` holds
  the plausibility band.

Say the second point before a judge finds it. "The prices are real, the
arithmetic is verified, and the chain split is a calibrated model" is a stronger
position than a claim that everything is measured.
