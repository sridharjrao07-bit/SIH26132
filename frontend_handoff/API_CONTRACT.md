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
Returns calibration metadata: direct margin, spoilage by commodity, grade
aliases, spoilage floors and ceilings, dispatch cost defaults, utility weight,
and the planned-vs-committed delta ceiling.

### `POST` `/api/v1/direct/rupee`
The consumer-rupee breakdown. Pure function — no database.

Request: `farm_price`, `retail_price`, `commodity`, optional `distance_km`,
`chain`, `region`.

Response: total spread, absorption, stage-by-stage attribution (each with
`margin_take` and `cost_take`), farmer share, `avoidable` (margin only) versus
`unavoidable` (real work), `farmer_share_pct`, `farmer_share_verdict`,
`pass_through`, `qty_multiplier`.

### `POST` `/api/v1/direct/fair-price`
Fair-price suggestion for one lane.

Request: `farm_price`, `retail_price`, `distance_km`, `quantity_qtl`, `utility`,
`perishability`, optional `region`, `handling_cost_per_qtl`, `farmer_share`,
`displaced`, `stranded`.

Response: suggested farm and retail prices, transport and spoilage costs,
farmer gain, consumer saving, total surplus, `max_allowed_delta`,
`displaced_count`, `stranded_qtl`.

### `POST` `/api/v1/direct/plan`
The core planner: allocate supply to demand, consolidate into shipments, split
the surplus. Runs the full engine server-side and returns an optimality
certificate.

Request: `lots[]` (with `lat`, `lon`, `supply_qtl`, `price`), `demand[]` (with
`lat`, `lon`, `demand_qtl`, `price`), `config`, `group_size`, `vehicles`.

Response: `direct_plan`, `allocations`, `shipments`, `orders`, `summary`.

### `POST` `/api/v1/direct/plans/commit`
Persists a committed plan. **Re-runs the engine server-side** from the submitted
inputs — the caller's `summary` is never trusted. Honours
`if_absent: "delta_exceeded" | "always" | "never"`, storing
`planned_total_qtl` / `committed_total_qtl`.

### `GET` `/api/v1/direct/plans/{plan_id}`
Fetch a stored plan by id.

### `POST` `/api/v1/direct/group-buy`
For consumers. Request: `commodity`, `window`, `target_qtl`, `min_load_qtl`.
Response includes a `group_url`.

### `GET` `/api/v1/direct/impact`
For farmers. Returns `farmer_improvement_pct`, `best_mandi_price`,
`demand_depth`, `route_count`, `trace_token`.

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
- **Optimality.** `POST /api/v1/direct/plan` returns an `optimality_certificate`. A
  plan is accepted only when it matches brute-force enumeration of the
  transportation polytope.
