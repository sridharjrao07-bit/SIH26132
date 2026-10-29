# API Contract — DirectLink (SIH26033)

Base URL: `/api/v1`

This contract reflects the API **after the pivot from SIH26132 to SIH26033**.
Endpoints belonging to the retired feature set (forecasts, alerts, SMS, buyers,
offers, payments, grievances, logistics bookings, storage, matching,
intelligence, dashboard, admin) are no longer served; that code now lives under
`legacy/` in the repository.

All requests and responses are `application/json`. Authenticated routes require
`Authorization: Bearer <jwt>`.

---

## DirectLink

### `GET` `/api/v1/direct/config`
Returns the active assumptions: `category`, `traditional_chain`, `direct_chain`,
`freight`, and derived pass-through/markup values.

### `POST` `/api/v1/direct/rupee`
The consumer-rupee breakdown. Pure function — no database.

Request: `farm_price` (required), optional `retail_price`, `commodity_id`,
`category`, `calibrate`, and a complete optional `stages` override.

Response: a leakage report containing the calibrated chain, stage attribution,
farmer share, avoidable margin, real-work cost, and verdict fields. The exact
response schema is the validated `RupeeResponse` returned by the backend.

### `POST` `/api/v1/direct/fair-price`
Fair-price suggestion for one lane.

Request: `farm_price`, optional `retail_price`, `commodity_id`, `category`,
`origin_lat`, `origin_lng`, `dest_lat`, `dest_lng`, `alpha`,
`platform_fee_pct`, `load_qtl`, and `circuity`.

Response: a two-sided quote containing distance, freight, direct/traditional
comparisons, the farmer/consumer split, and the leakage report it displaces.

### `POST` `/api/v1/direct/plan`
The core planner: allocate supply to demand, consolidate into shipments, split
the surplus. Runs the full engine server-side and returns an optimality
certificate.

Request: `lots[]` and `demands[]`. Each lot uses `id`, `commodity_id`,
`quantity_qtl`, `mandi_price_per_qtl` and optional coordinates/category/grade.
Each demand uses `id`, `commodity_id`, `quantity_qtl`, optional
`retail_price_per_qtl`, coordinates, `category`, and `kind`. Optional planner
configuration is `alpha`, `platform_fee_pct`, `max_distance_km`,
`min_allocation_qtl`, `cluster_size_km`, `circuity`, `calibrate`,
`enforce_grade`, and nested `freight`.

Response: `plan_id`, `config`, `allocations`, `shipments`, `impact`,
`calibrations`, and notes/unserved-demand fields as applicable.

### `POST` `/api/v1/direct/plans/commit`
Persists a committed plan. The request is `{ "plan": <PlanRequest>,
"commodity_id": optional, "district": optional }`. The plan is recomputed
server-side; there is no `if_absent` field.

### `GET` `/api/v1/direct/plans/{plan_id}`
Fetch a stored plan by id.

### `POST` `/api/v1/direct/group-buy`
For consumers. Request: `orders[]`, `origin_lat`, `origin_lng`, optional
`min_load_qtl`, `cluster_size_km`, `circuity`, and `freight`. Each order uses
`order_id`, `qtl`, optional coordinates, and `label`. The response is the
computed pool/freight result; it does not include a `group_url`.

### `GET` `/api/v1/direct/impact`
Returns an aggregate of committed DirectLink allocations. It may return a
dependency error when Supabase is unavailable; it is not a pure calculation.

### `GET` `/api/v1/direct/trace/{token}`
Public, unauthenticated. Redacted trace record for a crate: producer district,
harvest date, grade, food miles, per-stage deduction, and the farmer's share.
No names, phone numbers or coordinates are returned. Unknown tokens return 404.

---

## Reference data

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/markets/` | Mandi list |
| `GET` | `/api/v1/markets/nearby` | Markets near a point |
| `GET` | `/api/v1/commodities/` | Commodity list |
| `GET` | `/api/v1/prices/latest` | Latest mandi prices — the farm-gate anchor |
| `GET` | `/api/v1/prices/historical` | Historical mandi prices |

## Lots

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/lots/` | List lots |
| `POST` | `/api/v1/lots/` | Create a lot |
| `POST` | `/api/v1/lots/aggregate` | Aggregate view |
| `GET` | `/api/v1/lots/{lot_id}` | One lot |
| `PATCH` | `/api/v1/lots/{lot_id}/grade` | Update grade |
| `GET` | `/api/v1/lots/{lot_id}/ledger` | Lot ledger |
| `PATCH` | `/api/v1/lots/{lot_id}/withdraw` | Withdraw quantity |

## Profile

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/v1/me/` | Current user profile |
| `PATCH` | `/api/v1/me/` | Update profile |

---

## Operational

| Method | Path | Notes |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/readyz` | Readiness |
| `GET` | `/metrics` | Metrics |

---

## Conventions

- **Quantities.** Supply is quoted in **farm-gate quintals**; demand in
  **doorstep quintals**. `farm_qtl × w = delivered_qtl`. Mixing these produces a
  systematic shortfall.
- **Money.** All prices are ₹ per quintal unless a field name says otherwise.
  Farmer gain and consumer saving are both measured against real fallbacks (the
  mandi price and the retail price), never against each other.
- **Optimality.** `POST /api/v1/direct/plan` returns the engine's allocation
  impact and optimality flag; the backend recomputes the plan before commit.
