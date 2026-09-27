# DirectLink — architecture and algorithm

**Problem statement (SIH26033):** *multiple intermediaries between the farmer
and the consumer reduce the farmer's earnings and increase the consumer's
price.*

This document explains what we built to attack that, why each piece is shaped
the way it is, and exactly which claims are theorems and which are model
assumptions. Read `demo/direct_channel_demo.py` alongside it — that script runs
the whole argument offline, with no database.

---

## 1. The shape of the answer

Four moves, in order:

| # | Move | Module | What it guarantees |
|---|------|--------|--------------------|
| 1 | **Attribute** the consumer's rupee exactly, stage by stage | `direct/value_chain.py` | Every rupee between farm gate and shelf is assigned to a named stage; the attribution is additive and invertible |
| 2 | **Cut** the chain and re-price the trade | `direct/fair_price.py`, `direct/surplus.py` | Both sides are strictly better off than their fallback, by construction |
| 3 | **Consolidate** so a small order can move | `direct/logistics.py`, `direct/consolidation.py` | Freight is apportioned exactly; packing is within a proven bound of optimal |
| 4 | **Settle** traceably | `db/migrations/039_*.sql`, `app/routers/direct.py` | Every stored row carries its counterfactual; a receipt can be audited later |

Move 1 alone would only *show* the leak. Moves 2–4 are what close it, and move
4 is what makes the claim believable after the demo ends.

---

## 2. The chain as an affine map

A value chain is a list of stages. Stage *i* takes produce in at price
`p_in`, applies a margin `mᵢ`, absorbs a handling cost `cᵢ`, and loses a
fraction `ℓᵢ` of the quantity:

```
p_out = (1 + mᵢ) · p_in + cᵢ            (price per surviving quintal)
q_out = (1 − ℓᵢ) · q_in                 (quantity)
```

Composing *k* stages collapses to a single affine map — this is the fact the
whole model rests on:

```
p_retail = A · p_farm + B          where  A = Π (1 + mᵢ)
w        = Π (1 − ℓᵢ)              share of a farm quintal that reaches a plate
```

Two consequences fall out immediately and both are used:

* **Attribution is exact.** The amount absorbed by stage *i*, per farm quintal,
  is `value_in(i) − value_out(i)`. These sum to the total absorption with no
  residual, because they telescope. There is no "other" bucket and no
  unexplained remainder — which is what makes the consumer-rupee chart honest
  rather than decorative.
* **Pass-through is `1/A`.** A ₹1 change at the farm gate reaches the shelf as
  ₹`1/A`. For the reference vegetable chain `A ≈ 1.58`, so pass-through is
  ≈ 0.63: the chain dampens farm-price moves by more than a third. This is the
  standard measure of market efficiency and it is free once `A` is known.

### Calibration

The *shape* of the margin stack (which layer takes how much relative to the
others) comes from published value-chain studies and is baked into
`DEFAULT_CHAIN_PROFILES`. Its *level* varies enormously by commodity, district
and season, so it is fitted, not assumed.

`calibrate_margin_scale` solves for a single scalar λ that scales every stage
margin so the chain reproduces an observed `(farm, retail)` pair. Because
`p_retail(λ)` is monotonically increasing in λ, the solve is a bisection with a
guaranteed bracket, and it reports one of three statuses rather than silently
returning a bad fit:

* `ok` — the pair is reachable;
* `glut` — the observed pair implies λ ≤ 0 (the chain absorbs nothing, which
  happens in a glut);
* `unreachable` — λ would have to exceed the search ceiling.

**What this means for honesty:** the model is told the two prices it must
reproduce, and then explains the gap between them. It is not told the answer
and asked to draw a picture of it.

### Margin vs. work

Each stage's take splits into `margin_take` (markup) and `cost_take` (real
handling). Summed over the chain these give `margin_absorption` and
`cost_absorption`.

The `avoidable` figure reported by the API is **the margin**, not the whole
spread. This matters: an earlier version summed the take of stages flagged
`essential = False`, and since every stage of the reference chain is
non-essential in that sense, it declared 100% of ₹1,233/qtl avoidable. That is
an overclaim — some of the spread pays for packing and transport that any
channel, direct or not, must pay. Saying so is the difference between a number
that survives scrutiny and one that does not.

For the reference onion chain: ₹864 margin (70%), ₹369 work (30%), on top of
14.2% physical spoilage.

---

## 3. The direct channel and the split

### Units

Everything is per **farm-gate quintal**. This is the single most important
convention in the codebase and the source of one significant bug that has
already been fixed and pinned (see §7).

* `w` — direct delivered ratio: quintals arriving per quintal loaded. Direct
  spoilage ≈ 1.5%, versus 14.2% for the traditional chain, because the produce
  is handled twice instead of six times.
* `T` — packing + freight + handling + last mile, ₹ per quintal **loaded**.
* `m` — the platform fee. The only margin in the direct channel.
* `P` — the farmer's mandi fallback.
* `R` — the consumer's retail fallback.

The consumer's outlay per farm quintal is `w · p_c`, and the chain identity is

```
w · p_c = (1 + m) · (p_f + T)
```

### The pie

What is there to divide is what the direct channel creates over the
fallbacks:

```
Π_max = w · R − (1 + m) · (P + T)
```

If `Π_max ≤ 0` there is no trade: the farmer's mandi and the consumer's shop
are already the best available to each. The engine reports `viable = False`
rather than inventing a saving.

### The split

The two sides bargain over Π. The farmer's gain is `S_f = p_f − P`; the
consumer's saving is `S_c = w·R − (1+m)(p_f+T)`. Every rupee of farm price
moves `S_c` by `−(1+m)`, because the platform fee is levied on it. So the pie
**shrinks at rate `m`** as the farmer's share grows:

```
S_f + S_c = Π_max − m · S_f
```

Maximising the symmetric Nash product `S_f^α · S_c^(1−α)` gives a closed form:

```
P_max = [w·R − (1+m)·T] / (1+m)         the most the buyer could ever pay
p_f*  = α · P_max + (1 − α) · P          and the farmer's price is between
                                         his fallback and that ceiling
```

Three properties of this solution are load-bearing and all three are tested:

1. **α = 0 ⇒ `p_f = P`.** The farmer is exactly at his mandi; the consumer
   takes everything. α = 1 ⇒ the consumer pays exactly `R`.
2. **The first-order condition** is `α · S_c = (1−α) · (1+m) · S_f`. At α = ½
   the consumer's saving exceeds the farmer's gain by a factor of exactly
   `(1+m)` — not because of bias, but because moving a rupee to the farmer
   costs `m` in fee.
3. **α cannot invent surplus.** `S_f + S_c + fee` is invariant in α to within
   a fraction of a percent (the residual is the freight fixed point converging
   on a marginally different load). α only decides who bears the fee.

### The fallback, and why it is `P` and not `P / w_trad`

The farmer's disagreement payoff is **`P`**, the mandi price per quintal. He
sells the same physical quintals either way and is paid for all of them at the
mandi.

An earlier formulation used `P / w_trad` — mandi revenue per quintal *reaching
a shop through the traditional chain*. That is the right quantity for comparing
chains, but wrong for the farmer's actual choice, and it produced per-lane
gains that did not roll up (₹92,752 by one path, ₹75,228 by the other) and an
α = 0 case that left the farmer above his mandi. The bug is fixed and four
tests pin the corrected behaviour.

---

## 4. Freight, and the chicken-and-egg problem

`direct/logistics.py` prices a lane as haversine distance × circuity (1.25),
then applies a rate card:

| | value |
|---|---|
| Vehicle | 90 qtl |
| FTL rate | ₹0.28 /qtl-km |
| LTL rate | ₹0.62 /qtl-km (above the FTL fill threshold of 85%) |
| Per-trip floor | ₹1,800 |
| Loading / packing / last mile | ₹12 / ₹16 / ₹9 per qtl |

The per-trip floor is the whole reason consolidation matters, and it creates a
chicken-and-egg problem: **the cost per quintal depends on the load, but the
load depends on which lanes are viable, which depends on the cost.**

Pricing each lane at one quintal makes every lane hopeless (₹1,800/qtl).
`plan_direct_channel` breaks the cycle with an optimistic-first fixed point:

1. price every lane at the **FTL planning rate** (the best case);
2. solve the allocation;
3. re-price each lane at the load it actually got;
4. repeat, up to `MAX_FREIGHT_PASSES = 4`.

It terminates because each pass only removes lanes that are unprofitable at
the more expensive rate, and it always ends in a state where no lane is being
subsidised by a rate it would not receive.

A related unit trap, also fixed and pinned: **supply is farm-gate quintals,
demand is doorstep quintals.** `farm_qtl × w = delivered_qtl`. Before this was
handled, every order came out roughly 3% short.

---

## 5. Allocation: an optimality certificate, not a heuristic

Given `n` lots, `m` demands and a surplus per farm quintal for each pair, the
matching problem is a transportation LP. A greedy "best lane first" assignment
is fast, obviously sensible, and **wrong**. On

```
value = [[8, 7], [7, 0]],  supply = demand = [1, 1]
```

greedy scores 8 and stops; the optimum is 14 (take the anti-diagonal). Greedy
forfeits 43% of the available surplus. Since the entire pitch is "we recovered
surplus the chain was wasting", shipping a solver that throws away 43% of it
would be indefensible.

`direct/allocation.py` solves it properly with min-cost flow on a residual
network — successive shortest paths with potentials, which admits **reverse
edges**. Reverse edges are precisely what fixes the counterexample: they let
the solver undo an earlier commitment when a better global arrangement exists.

### Proving it optimal

The engine does not ask to be trusted on this. Every solve returns an
`optimality_certificate`, and the tests verify the engine against ground truth:

* Every vertex of the transportation polytope is a basic feasible solution
  whose basis is a spanning tree of `K_{m,n}`.
* `tests/test_allocation.py` enumerates those trees by Prüfer sequence, keeps
  the ones whose edges all cross the supply/demand cut, solves each by leaf
  peeling, and discards the infeasible (negative-flow) ones. That is the true
  LP optimum.
* The engine matches that brute-force optimum on 12 random 2×2 and 8 random
  3×3 instances, and satisfies conservation and capacity on 20 more.

---

## 6. Consolidation

`direct/consolidation.py` packs orders into vehicles with first-fit-decreasing
(FFD). FFD is not optimal, but it is provably close: `bins(FFD) ≤ 11/9 · OPT +
6/9`. The tests confirm the bound against an exhaustive search on small
instances and check FFD never beats OPT.

Apportioning the freight back to orders is done so the parts sum to the whole
**exactly**, to the paisa. A receipt whose shares do not add up to the bill is
worthless, so this is asserted rather than eyeballed.

---

## 7. Which farmer gets served first

This surprised us, so it is worth stating explicitly.

Total surplus on a lane is `Π = w·R − (1+m)(P+T)`. With `R`, `T` and `m` equal
across two lots, the lane with the **smaller** `P` frees up more surplus. The
farmer's mandi price *is* his opportunity cost, so **maximising total surplus
and prioritising the worst-paid farmer are the same objective**, not competing
ones. Given a farmer at ₹2,000 and one at ₹2,400 on the same lane, the engine
picks up the ₹2,000 farmer.

It is not a flat rate either. Since `p_f* = α·P_max + (1−α)·P`, the farm price
tracks the mandi fallback at rate `1−α` — at α = ½, half of a mandi advantage
carries over and half is pooled. Paying every farmer the same would hand the
best-off farmer the entire surplus and leave the worst-off no reason to join.

Net effect on the two-lot example: the ₹2,000 farmer gets **+43.6%**, the
₹2,400 farmer **+28.0%**. The gap narrows, both improve, and the needier
farmer improves more. Three tests pin this.

---

## 8. Persistence: the counterfactual travels with the fact

`db/migrations/039_direct_fulfilment.sql` adds `direct_plans`,
`direct_allocations`, `direct_shipments` and `direct_orders`.

The design rule is that **no number is stored without the number it replaces**:

| stored | alongside |
|--------|-----------|
| `farmer_realisation_rs` | `mandi_realisation_rs` |
| `consumer_price_per_qtl` | `retail_reference_per_qtl` |
| `direct_plans.impact` | `direct_plans.config` (the engine config that produced it) |

`chk_mutual_gain` on `direct_allocations` enforces `farmer_gain_rs ≥ 0 AND
consumer_saving_rs ≥ 0` **in the database**. The engine should never produce a
row that violates it, but if it ever did, the insert fails rather than the
platform quietly extracting from the people it claims to help.

`chk_order_shares_reconcile` enforces that farmer + logistics + platform equals
`consumer_price × qtl` to within ₹1, so a receipt can never misreport where the
money went.

### Writes

Nothing writes by direct table insert. Every write goes through a `SECURITY
DEFINER` RPC that derives the owner from the JWT (never from the payload),
validates what a CHECK constraint cannot express, and takes a row lock where a
read-then-write would race.

The interesting case is `group_buy_join`. `group_buys.committed_qtl` is a
running total over its members; two households joining at once would both read
the counter and both write back, silently dropping an order and leaving the
truck short. The RPC takes `SELECT … FOR UPDATE` on the group row — serialising
joins on the same group while leaving different groups parallel — and then
**re-derives** `committed_qtl` from the members rather than incrementing it, so
an upsert that *lowers* an existing commitment cannot corrupt the total.

### Traceability

`direct_orders.trace_token` is a short random string generated server-side from
`gen_random_bytes`, not a UUID and not derived from any id — a guessable token
would let anyone enumerate orders. `direct_order_trace(token)` returns a
redacted JSON receipt with no names, phone numbers or coordinates; it is
granted to `anon`, because the whole point is that a buyer can scan a crate.
Unknown tokens give 404, so the endpoint cannot be used to probe which tokens
exist.

---

## 9. API surface

Nine routes under `/api/v1/direct`.

The economics endpoints — `/rupee`, `/fair-price`, `/config`, `/plan`,
`/group-buy` — **never write anything**, so a caller can price a hypothetical
trade without touching the database. They do read, but only when a caller omits
an input they could have supplied:

* `retail_price` / `retail_price_per_qtl` are optional. Supply them and **no
  query is issued and no network call is made** — the arithmetic is a pure
  function of the request body, which is what makes it checkable by hand. (The
  process still needs well-formed `SUPABASE_*` values in its environment,
  because the FastAPI dependency constructs a client object before the handler
  runs; it is simply never used. Note that `SUPABASE_ANON_KEY=placeholder` is
  rejected by the Supabase SDK's key-shape check, so use any JWT-shaped dummy.)
  Omit the price and the live retail anchor is resolved instead
  (`ingestion/retail_loader.py`, which itself falls back to the committed
  government snapshot).
* `/plan` reads traditional chain shapes from `value_chain_profiles` when that
  table is populated, so a district officer can retune the model without a
  deploy. An empty or missing table is not an error: the engine falls back to
  its built-in `DEFAULT_CHAIN_PROFILES`, which is correct but less tunable.

Only `POST /plans/commit` writes, and it **re-runs the engine server-side**
from the submitted inputs. A client cannot supply an impact figure and have it
stored; the numbers in the database are always the engine's own.

Only `POST /plans/commit` writes, and it **re-runs the engine server-side**
from the submitted inputs. A client cannot supply an impact figure and have it
stored; the numbers in the database are always the engine's own.

---

## 10. Data provenance

Both anchors are real, published government data. This matters more than it
sounds: the consumer-rupee analysis is a ratio between two prices, and if
either is invented then every number downstream is decorative.

### Farm gate — real

`data/gov_prices_60days.csv` — 980 rows, 5 Nashik APMCs (Lasalgaon, Pimpalgaon
Baswant, Yeola, Manmad, Nashik), Aug–Sep 2026, from the data.gov.in daily
mandi price resource `9ef84268-d588-465a-a308-a864a43d0070`. The same
real-time adapter feeds the `prices` table in production.

Reference value: **Lasalgaon onion modal ₹2,226.39/quintal, 26 Sep 2026.**

### Retail — real, live when configured

Ministry of Consumer Affairs, Food & Public Distribution — Department of
Consumer Affairs, *"Essential Commodity: State-wise Daily Wholesale and Retail
Price of Onion"*, published daily at `fcainfoweb.nic.in` (mirrored on
data.gov.in and `dataful.in/datasets/19942`, 253,825 rows, 2014–2026).

* `ingestion/dca_retail.py` — live adapter. Resource id is **configurable**
  (`DCA_RETAIL_RESOURCE_ID`, per-commodity override via
  `DCA_RETAIL_RESOURCE_IDS`) because data.gov.in re-issues UUIDs when a dataset
  is re-published; hard-coding one is a bet it will not move.
* `data/gov_retail_prices.csv` — committed snapshot of the same dataset, so a
  demo with no wifi still runs on real numbers.
* `ingestion/retail_loader.py` — live first, snapshot second, and it **raises**
  rather than guessing if neither is available. A missing anchor must be loud:
  a plausible-looking fallback would discredit every figure below.
* `db/migrations/040_seed_retail_prices.sql` seeds the `retail_prices` table.

Units are normalised to ₹/quintal at the boundary (kg × 100), because the
dataset mixes both in one column and a kg figure passed through as quintals is
wrong by 100× while still looking reasonable.

### Why the real numbers are worse — and the fix is bigger

| | Assumed (₹2,200 → ₹4,000) | Real (₹2,226 → ₹5,392) |
|---|---|---|
| Farmer's share of the rupee | 64% | **48%** |
| Margin as a share of the spread | 70% | **85%** |
| Farmer gain from DirectLink | +35.6% | **+64.5%** |
| Consumer saving | −20.5% | **−27.9%** |

The September 2026 onion spike (inflation at 48% YoY) means the assumed figure
*understated* the problem. Measuring it rather than assuming it made the case
stronger.

### Known limitation

The Maharashtra retail row is the **All-India average** retail (₹53.92/kg,
reported 16 Sep 2026), not a Nashik bazaar survey. The row's `note` column says
so, and the live adapter replaces it with a state-specific observation as soon
as one is published. City-level retail surveys would tighten this further.

## 11. What is a theorem and what is a model

Being precise about this is the point of the whole exercise.

**Theorems** (true given the inputs, and tested):

* Stage attribution sums to the total absorption with no residual.
* Chain composition is affine; pass-through is `1/A`.
* `p_f* = α·P_max + (1−α)·P`; α = 0 leaves the farmer at `P`, α = 1 leaves the
  consumer at `R`.
* The allocation is optimal (verified against brute-force vertex enumeration).
* Farmer gain + consumer saving = total surplus, exactly, at every level of
  aggregation.
* Freight apportioned to orders sums to the trip total.
* FFD is within `11/9 · OPT + 6/9`.

**Model assumptions** (defensible, cited in code, and configurable):

* The *shape* of the traditional margin stack, from published value-chain
  studies. Its level is fitted to observed prices, not assumed.
* The freight rate card, including the 1.25 circuity factor and the ₹1,800
  per-trip floor.
* Direct spoilage of 1.5% versus 14.2% traditional — the direct chain handles
  the produce twice instead of six times, but the figure is a parameter.
* The platform fee of 3%.

Every one of these is a named parameter. A district officer can retune the
chain model in `value_chain_profiles` without a deploy.

---

## 12. Running it

```bash
# the whole argument, offline, no database or API keys
python demo/direct_channel_demo.py

# the engine's tests
pytest tests/test_value_chain.py tests/test_surplus.py \
       tests/test_allocation.py tests/test_logistics.py \
       tests/test_consolidation.py tests/test_direct_pipeline.py -q

# the API
uvicorn app.main:app --reload
# → http://localhost:8000/docs
```
