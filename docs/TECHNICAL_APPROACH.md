# Technical Approach — DirectLink (SIH26033)

**Problem statement:** *Multiple intermediaries between the farmer and the
consumer reduce the farmer's earnings and increase the consumer's price.*

**Team solution name:** DirectLink
**Repository:** this one — branch `arena/01a0e3c9-sih26132`
**Companion documents:** [`docs/DIRECT_CHANNEL.md`](DIRECT_CHANNEL.md) (algorithms in depth),
[`docs/HANDOFF_NEXT_STEPS.md`](HANDOFF_NEXT_STEPS.md) (remaining work),
[`docs/API.md`](API.md) (HTTP contract)

---

## 1. Restating the problem precisely

The statement makes two claims, and a solution must address **both
simultaneously**:

1. Intermediaries **reduce farmer earnings** — the farmer receives less than
   the value his produce creates.
2. Intermediaries **increase consumer prices** — the consumer pays more than
   that same value costs to deliver.

A solution that only raises the farmer's price by charging the consumer more
solves neither. A solution that only cuts the consumer's price by squeezing the
farmer is worse than doing nothing. **The acceptance test is that both sides
improve on the same trade.**

A third, implicit requirement makes this hard: the gains must be *real*, not
transfers. If the platform simply becomes a new intermediary, nothing has been
solved — the chain got one link longer.

---

## 2. Solution overview

DirectLink attacks the problem in four moves.

| # | Move | What it does | Why it is necessary |
|---|------|--------------|---------------------|
| 1 | **Attribute** | Assign every rupee between farm gate and shelf to a named stage | You cannot fix a leak you cannot locate, and stakeholders will not accept a number they cannot decompose |
| 2 | **Cut and re-price** | Remove the chain and split the freed surplus between farmer and consumer | This is where the money is actually recovered |
| 3 | **Consolidate** | Pool small orders until a truck is economically viable | A household order cannot fill a truck; without this, move 2 is a theory |
| 4 | **Settle traceably** | Store every transaction with its counterfactual and a public receipt | Makes every claim auditable after the fact |

The critical design decision: **the platform charges a single transparent fee
(3%) and takes no position in the trade.** It does not buy from the farmer and
sell to the consumer. It is a matching and settlement layer, not a new
middleman. This is what makes the solution structurally different from the
problem it solves.

---

## 3. System architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Consumers / RWAs / hostels / institutions      Farmer / FPO  │
└───────────────────────┬──────────────────────────────┬───────┘
                        │  HTTPS / JSON                 │
┌───────────────────────▼──────────────────────────────▼───────┐
│                    FastAPI application                        │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  /api/v1/direct/*   (9 routes)                          │  │
│  │   rupee · fair-price · config · plan · group-buy        │  │
│  │   plans/commit · plans/{id} · trace/{token} · impact    │  │
│  └───────────────────────┬────────────────────────────────┘  │
│  ┌───────────────────────▼────────────────────────────────┐  │
│  │  DirectLink engine — `direct/`  (pure Python, no I/O)   │  │
│  │   value_chain  →  surplus  →  logistics                 │  │
│  │   consolidation  →  allocation  →  pipeline             │  │
│  └────────────────────────────────────────────────────────┘  │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│  Supabase / PostgreSQL + Row Level Security                   │
│   direct_plans · direct_allocations · direct_shipments        │
│   direct_orders · retail_prices · value_chain_profiles        │
│   consumer_nodes · group_buys · group_buy_members             │
│   (shares markets / commodities / prices / lots with the      │
│    existing mandi-side schema)                                │
└──────────────────────────────────────────────────────────────┘
                        ▲
┌───────────────────────┴──────────────────────────────────────┐
│  Government data sources                                      │
│   data.gov.in daily mandi prices  →  farm-gate anchor         │
│   Dept. of Consumer Affairs       →  retail anchor            │
└──────────────────────────────────────────────────────────────┘
```

### Why the engine does no I/O

The economics modules in `direct/` are pure functions of their inputs. Three
consequences, all of which matter:

- **They cannot be poisoned by stale data.** A cached or corrupted table cannot
  silently change a price.
- **They are testable without infrastructure.** 345 of the 970 tests exercise
  the engine with no database at all.
- **A evaluator can call them with their own numbers and check the arithmetic.**
  This is the single most important property for credibility — the
  `/api/v1/direct/rupee` and `/fair-price` endpoints are open books.

Only `POST /plans/commit` writes, and it **re-runs the engine server-side**
from the submitted inputs. A client cannot supply an impact figure and have it
stored.

---

## 4. Technical methodology

### 4.1 The value chain as an affine map

A chain is an ordered list of stages. Stage *i* takes produce in at price
`p_in`, applies margin `mᵢ`, absorbs handling cost `cᵢ`, and loses fraction
`ℓᵢ`:

```
p_out = (1 + mᵢ) · p_in + cᵢ        (price per surviving quintal)
q_out = (1 − ℓᵢ) · q_in             (quantity)
```

Composing *k* stages collapses to one affine map:

```
p_retail = A · p_farm + B      A = Π (1 + mᵢ)
w        = Π (1 − ℓᵢ)          w = quintals reaching a plate, per farm quintal
```

Two results fall out immediately, and both are used:

- **Exact attribution.** Stage *i* absorbs `value_in(i) − value_out(i)` per farm
  quintal. These telescope, so they sum to the total absorption with **no
  residual**. There is no "other" category and no unexplained remainder — which
  is what distinguishes an honest consumer-rupee chart from a decorative one.
- **Pass-through = 1/A.** A ₹1 change at the farm gate reaches the shelf as
  ₹`1/A`. This is the standard measure of market efficiency and is free once
  `A` is known. For the reference vegetable chain, pass-through ≈ 0.47.

### 4.2 Calibration: fit the level, take the shape from literature

The *shape* of the margin stack (which layer takes how much relative to the
others) comes from published value-chain studies and is fixed in code. Its
*level* swings wildly by commodity, district and season, so it is **fitted, not
assumed**.

`calibrate_margin_scale` solves for one scalar λ that scales every stage margin
so the chain reproduces an observed `(farm, retail)` pair. Because
`p_retail(λ)` is monotonically increasing in λ, the solve is a bisection over a
guaranteed bracket. It reports one of three statuses rather than returning a
bad fit silently:

| Status | Meaning |
|---|---|
| `ok` | pair is reachable |
| `glut` | implies λ ≤ 0 — the chain absorbs nothing |
| `unreachable` | λ would exceed the search ceiling |

**Why this matters for honesty:** the model is *told* the two prices it must
reproduce and then explains the gap. It is not handed the answer and asked to
draw a picture of it.

### 4.3 Splitting the margin from the work

Each stage's take splits into `margin_take` (markup) and `cost_take` (real
handling). The API's `avoidable` figure is **the margin only**, not the whole
spread.

This was a deliberate correction. An earlier version summed the take of stages
flagged `essential = False` — and since every stage of the reference chain is
non-essential in that sense, it declared 100% of the spread recoverable. That
is an overclaim: some of the spread pays for packing and transport that *any*
channel must pay. Promising to recover it would collapse under the first
question.

On the current real data: ₹2,032/qtl margin (85%), ₹369/qtl real work (15%).

### 4.4 The direct channel and the surplus split

All quantities are per **farm-gate quintal** — the single most important
convention in the codebase.

| Symbol | Meaning |
|---|---|
| `w` | direct delivered ratio (direct spoilage ≈ 1.5% vs 14.2% traditional — handled twice, not six times) |
| `T` | packing + freight + handling + last mile, ₹ per quintal loaded |
| `m` | platform fee — the only margin in the direct channel |
| `P` | farmer's mandi fallback |
| `R` | consumer's retail fallback |

Consumer outlay per farm quintal is `w · p_c`, and the chain identity is:

```
w · p_c = (1 + m) · (p_f + T)
```

The surplus available to divide, measured against both fallbacks:

```
Π_max = w · R − (1 + m) · (P + T)
```

If `Π_max ≤ 0` there is **no trade** — the mandi and the shop are already the
best available to each. The engine reports `viable = False` rather than
inventing a saving.

The two sides bargain over Π. Maximising the symmetric Nash product
`S_f^α · S_c^(1−α)` gives a closed form:

```
P_max = [w·R − (1+m)·T] / (1+m)       ceiling on the farm price
p_f*  = α · P_max + (1 − α) · P       the actual farm price
```

Three properties are load-bearing, and all three are tested:

1. **α = 0 ⇒ `p_f = P`** — farmer exactly at his mandi, consumer takes all.
   **α = 1 ⇒** consumer pays exactly `R`.
2. **First-order condition** `α · S_c = (1−α) · (1+m) · S_f`. At α = ½ the
   consumer's saving exceeds the farmer's gain by exactly `(1+m)` — not from
   bias, but because moving a rupee to the farmer costs `m` in platform fee.
3. **α cannot invent surplus.** `S_f + S_c + fee` is invariant in α to within
   a fraction of a percent. α decides who bears the fee, not how big the pie is.

**The fallback is `P`, not `P / w_trad`.** The farmer sells the same physical
quintals either way and is paid for all of them at the mandi. An earlier
per-consumer-quintal formulation was wrong here and produced per-lane gains
that did not roll up (₹92,752 by one path, ₹75,228 by another). It is fixed and
pinned by tests.

### 4.5 Freight and the chicken-and-egg problem

Distance is haversine × circuity (1.25), priced on a rate card:

| | |
|---|---|
| Vehicle | 90 qtl |
| FTL / LTL | ₹0.28 / ₹0.62 per qtl-km (LTL above an 85% fill threshold) |
| Per-trip floor | ₹1,800 |
| Loading / packing / last mile | ₹12 / ₹16 / ₹9 per qtl |

The per-trip floor is exactly why consolidation matters — and it creates a
circular dependency: **cost per quintal depends on load, but load depends on
which lanes are viable, which depends on cost.** Pricing each lane at one
quintal makes every lane hopeless.

`plan_direct_channel` breaks the cycle with an **optimistic-first fixed point**:
price all lanes at the FTL planning rate, solve, re-price each lane at the load
it actually received, repeat (capped at 4 passes). It terminates because each
pass only removes lanes unprofitable at the dearer rate, and it always ends in
a state where no lane is subsidised by a rate it would not get.

### 4.6 Allocation: an optimality certificate, not a heuristic

Matching `n` lots to `m` demands is a transportation LP. Greedy "best lane
first" is fast, obviously sensible, and **wrong**:

```
value = [[8, 7], [7, 0]],   supply = demand = [1, 1]
greedy: 8        optimum: 14     → greedy forfeits 43%
```

Shipping a solver that throws away 43% of the recovered surplus would be
indefensible when the entire pitch is recovering wasted surplus.

`direct/allocation.py` solves it with min-cost flow on a residual network
(successive shortest paths with potentials). **Reverse edges** are what fix the
counterexample: they let the solver undo an earlier commitment when a better
global arrangement exists.

The engine does not ask to be trusted. Every solve returns an
`optimality_certificate`, verified against ground truth:

- Every vertex of the transportation polytope is a BFS whose basis is a
  spanning tree of `K_{m,n}`
- Tests enumerate those trees by Prüfer sequence, keep those whose edges cross
  the supply/demand cut, solve each by leaf peeling, discard negative flows —
  that is the true LP optimum
- The engine matches it on 12 random 2×2 and 8 random 3×3 instances, and
  satisfies conservation and capacity on 20 more

### 4.7 Consolidation

First-fit-decreasing bin packing into vehicles. FFD is not optimal but is
provably close: `bins(FFD) ≤ 11/9 · OPT + 6/9`, confirmed against exhaustive
search on small instances. Freight is apportioned back to orders so the parts
sum to the trip total **exactly** — a receipt whose shares do not add up to the
bill is worthless, so this is asserted, not eyeballed.

### 4.8 Traceable settlement

The design rule is **no number is stored without the number it replaces**:

| Stored | Alongside |
|---|---|
| `farmer_realisation_rs` | `mandi_realisation_rs` |
| `consumer_price_per_qtl` | `retail_reference_per_qtl` |
| `direct_plans.impact` | `direct_plans.config` (the config that produced it) |

Database-level guarantees, not application-level hopes:

- `chk_mutual_gain` — `farmer_gain_rs ≥ 0 AND consumer_saving_rs ≥ 0`. The
  engine should never violate it; if it ever did, **the insert fails** rather
  than the platform quietly extracting from the people it claims to help.
- `chk_order_shares_reconcile` — farmer + logistics + platform = price × qty
  within ₹1, so a receipt can never misreport where the money went.

All writes go through `SECURITY DEFINER` RPCs that derive the owner from the
JWT (never the payload), validate what CHECK constraints cannot express, and
take row locks where a read-then-write would race. The notable case is
`group_buy_join`: `committed_qtl` is a running total over members, so two
simultaneous joins would both read and both write, silently dropping an order.
It takes `SELECT … FOR UPDATE` on the group row — serialising joins on one
group while leaving different groups parallel — then **re-derives** the total
from members rather than incrementing, so a lowered commitment cannot corrupt
it.

`trace_token` is a short random string from `gen_random_bytes`, not a UUID and
not derived from any id — a guessable token would let anyone enumerate orders.
The lookup returns redacted JSON with no names, phones or coordinates, and is
granted to `anon` because the point is that a buyer can scan a crate. Unknown
tokens 404, so the endpoint cannot probe which tokens exist.

---

## 5. Data: real, measured, cited

Both anchors are published government data. This matters more than it sounds —
the consumer-rupee analysis is a ratio of two prices, and if either were
invented, every downstream number would be decorative.

| Anchor | Source | Value |
|---|---|---|
| Farm gate | data.gov.in daily mandi prices, Lasalgaon APMC onion modal, 26 Sep 2026 | **₹2,226 /quintal** |
| Retail | Ministry of Consumer Affairs / Dept. of Consumer Affairs, daily wholesale-and-retail dataset (`fcainfoweb.nic.in`, 253,825 rows, 2014–2026) | **₹5,392 /quintal** |

- `ingestion/dca_retail.py` — live adapter. Resource id is **configurable**
  (`DCA_RETAIL_RESOURCE_ID`) because data.gov.in re-issues UUIDs on
  re-publication; hard-coding one is a bet it will not move.
- `data/gov_retail_prices.csv` + migration 040 — committed snapshot of the same
  dataset, so a demo with no wifi still runs on government-published numbers.
- `ingestion/retail_loader.py` — live first, snapshot second, and it **raises
  rather than guessing** when neither is available. A missing anchor must be
  loud; a plausible-looking fallback would discredit everything downstream.
- Units are normalised to ₹/quintal at the boundary (kg × 100) — the dataset
  mixes both in one column, and a kg figure passed through as quintals is wrong
  by 100× while still looking reasonable.

**Measuring made the case stronger, not weaker:**

| | Assumed (₹2,200→₹4,000) | Real (₹2,226→₹5,392) |
|---|---|---|
| Farmer's share of the rupee | 64% | **48%** |
| Margin share of the spread | 70% | **85%** |
| Farmer gain | +35.6% | **+64.5%** |
| Consumer saving | −20.5% | **−27.9%** |

The September 2026 onion spike (inflation 48% YoY) means the assumed retail
price had *understated* the problem.

---

## 6. Technology stack and justification

| Choice | Why |
|---|---|
| **Python 3.12** | Numerical work without a numerical-team headcount; the engine is ~2,500 lines of pure functions |
| **FastAPI** | Automatic OpenAPI so the contract is never out of date with the code; async where I/O demands it |
| **Pydantic** | Validation before the route body runs, so malformed input is a 422 rather than a bad number in the database |
| **Supabase / PostgreSQL** | Financial rows need ACID; Row Level Security moves authorisation into the database where it cannot be bypassed by a forgotten middleware |
| **Dataclasses + slots** | The engine allocates one object per lane per pass; slots keep that cheap at 60×25 scale |
| **pytest** | 970 tests. Optimality, conservation and attribution are properties, so they are asserted continuously rather than checked once |

Deliberately **not** used: an ML price predictor. The problem is a structural
one about chain margins, not a forecasting one; a model predicting next week's
mandi price would not remove a single intermediary.

---

## 7. Innovation

1. **Attribution that closes exactly.** Stage takes telescope to the total
   absorption with zero residual. Most "consumer rupee" visualisations leave an
   unexplained remainder; this one cannot.
2. **Calibrated, not asserted.** The model is fitted to observed prices and
   reports when the fit is impossible (`glut` / `unreachable`) instead of
   quietly producing a number.
3. **Provably optimal matching, with the certificate shipped.** The solver
   returns the evidence, and tests check it against brute-force vertex
   enumeration rather than trusting it.
4. **Counterfactual-carrying storage.** Every stored figure sits next to the
   figure it replaces, so an impact claim can be re-audited years later without
   re-running anything.
5. **Surplus maximisation that serves the neediest farmer first.** Because the
   mandi price *is* the farmer's opportunity cost, a lower fallback frees more
   surplus — so efficiency and equity are the same objective here, not
   competing ones. Given a ₹2,000 farmer and a ₹2,400 farmer on one lane, the
   engine picks up the ₹2,000 one and gives him the larger raise (+43.6% vs
   +28.0%). It is *not* a flat rate: the farm price tracks the mandi at rate
   `1−α`, so at α = ½ half of a mandi advantage carries over. Paying everyone
   identically would hand the best-off farmer the entire surplus and leave the
   worst-off no reason to join.

---

## 8. Results

Reproducible with `python demo/direct_channel_demo.py` (no database, network or
API keys required). All figures computed live from the engine.

**One lane — Lasalgaon farm gate → Nashik housing society, 62 km:**

| | Today | DirectLink | Change |
|---|---|---|---|
| Farmer receives | ₹2,226 | ₹3,663 | **+64.5%** |
| Consumer pays | ₹5,392 | ₹3,890 | **−27.9%** |
| Farmer's share | 48 paise | **95 paise** | — |

**District plan — 60 farmer lots × 25 consumer groups, one night:**

- Farmer gain **+72.8%**, consumer saving **−29.2%**
- Total surplus recovered: **₹2,529,818**
- Platform fee: ₹89,309 (2.9% of consumer spend) — the only margin taken
- Intermediaries displaced: 5
- 4 correctness invariants print pass: conservation, optimality, no
  over-selling, every lane mutual-gain

---

## 9. Verification status — what is proven and what is not

Being precise about this is the point of the exercise.

**Proven by test (970 tests, 0 failures):**

- Stage attribution sums to total absorption with no residual
- Chain composition is affine; pass-through is `1/A`
- `p_f* = α·P_max + (1−α)·P`; α = 0 leaves the farmer at `P`, α = 1 leaves the
  consumer at `R`
- Allocation is optimal (verified against brute-force vertex enumeration)
- Farmer gain + consumer saving = total surplus, exactly, at every aggregation
- Freight apportioned to orders sums to the trip total
- FFD within `11/9 · OPT + 6/9`
- Both price anchors load from real, dated, cited sources

**Model assumptions** (defensible, cited in code, all configurable):

- The *shape* of the traditional margin stack, from published value-chain
  studies. Its level is fitted to observed prices, not assumed.
- The freight rate card: 1.25 circuity factor, ₹1,800 per-trip floor
- Direct spoilage 1.5% vs 14.2% traditional — handled twice instead of six
  times, but it is a parameter
- Platform fee of 3%

**Not yet verified (stated plainly):**

- **Migrations 038–040 have never run against a real PostgreSQL instance.**
  They are written but unexecuted; there is no database in the build
  environment. This is the largest open risk.
- **The live retail adapter has not called the real API** (no key available).
  It is built to the same pattern as the working mandi adapter and fails loudly
  rather than silently.
- The Maharashtra retail row is the All-India average, not a Nashik bazaar
  survey. The row says so in its `note` column.

---

## 10. Limitations and future scope

- **Retail granularity.** State-level retail averages should be replaced with
  city/market surveys, recorded through the `retail_price_record` RPC.
- **Perishability is modelled as a static loss rate.** A time-and-temperature
  aware model would sharpen both chains.
- **Quality/grade matching** is present in the schema but not yet enforced in
  the allocation objective (`enforce_grade` defaults off).
- **No payment rails.** The direct channel computes settlement but does not yet
  move money; integrating UPI/e-RUPI is the natural next step.
- **Repeated-game effects.** The model prices a single trade. In practice,
  standing relationships between an FPO and an RWA would change both the
  logistics cost and the bargaining weights.
- **Front-end.** The React PWA in `web/` was deliberately untouched; the API is
  ready for it.

---

## 11. How to evaluate this in five minutes

```bash
git checkout arena/01a0e3c9-sih26132
source .venv/bin/activate

python demo/direct_channel_demo.py        # the whole argument, offline

RUN_SCHEDULER=0 RATE_LIMIT_ENABLED=0 python -m pytest tests/ -q
# 970 passed, 40 skipped, 0 failed

uvicorn app.main:app --reload             # then open /docs
```

Try `POST /api/v1/direct/rupee` with your own farm and retail prices. The
endpoint is a pure function with no database behind it — you can check the
arithmetic yourself, which is the point.
