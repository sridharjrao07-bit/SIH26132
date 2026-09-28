// Runtime mirrors of the DirectLink surface in frontend_handoff/API_CONTRACT.md.
// Only fields the UI reads are strict; extra fields pass through (v.object
// ignores unknown keys), so a backend adding a field cannot break the client.
import * as v from 'valibot';

const num = v.number();
// Several DirectLink fields are optional or nullable depending on calibration
// status, so they are read permissively and narrowed at the point of use.
const numOrNull = v.nullish(v.number(), null);
const str = v.string();
const strOrNull = v.nullish(v.string(), null);

/** One stage of the traditional chain, with its take split into margin and cost. */
export const ChainStageSchema = v.object({
  key: str,
  label_en: str,
  // Marathi and Hindi labels arrive as escaped unicode; the backend decodes them
  // into real Devanagari before serialising, so they are plain strings here.
  label_mr: strOrNull,
  label_hi: strOrNull,
  kind: strOrNull,
  essential: v.optional(v.boolean(), false),
  price_in: num,
  price_out: num,
  qty_in: numOrNull,
  qty_out: numOrNull,
  value_in: numOrNull,
  value_out: numOrNull,
  /** Cost take: packing, freight, labour. Real work. */
  cost_take: numOrNull,
  /** Margin take: markup over cost. Avoidable in principle. */
  margin_take: numOrNull,
  take: num,
  margin_pct: numOrNull,
  cost_per_qtl: numOrNull,
  loss_pct: numOrNull,
  spoilage_qtl: numOrNull,
  note: strOrNull,
  take_pct_of_consumer_rupee: numOrNull,
});
export type ChainStage = v.InferOutput<typeof ChainStageSchema>;

/** The fitted traditional chain: how the consumer's rupee is absorbed. */
export const ChainSummarySchema = v.object({
  chain_name: strOrNull,
  farm_price: num,
  retail_price: num,
  delivered_ratio: num,
  spoilage_pct: num,
  A: numOrNull,
  B: numOrNull,
  consumer_spend_per_farm_qtl: numOrNull,
  absorption_per_farm_qtl: numOrNull,
  margin_absorption_per_farm_qtl: numOrNull,
  cost_absorption_per_farm_qtl: numOrNull,
  farmer_share_pct: numOrNull,
  price_ratio_pct: numOrNull,
  absorption_per_delivered_qtl: numOrNull,
  margin_share_of_absorption_pct: numOrNull,
  pass_through: numOrNull,
  chain_length: v.optional(v.number(), 0),
  intermediary_count: v.optional(v.number(), 0),
  stages: v.optional(v.array(ChainStageSchema), []),
});
export type ChainSummary = v.InferOutput<typeof ChainSummarySchema>;

/**
 * POST /api/v1/direct/rupee — the consumer-rupee breakdown.
 *
 * This is the headline number of the whole concept, so the schema is the
 * strictest in the app: every field the demo quotes is required, because a
 * missing one would silently render as NaN.
 */
export const RupeeReportSchema = v.object({
  commodity: str,
  farm_price: num,
  retail_price: num,
  calibration_status: str,
  calibrated_margin_scale: numOrNull,
  farmer_share_pct: num,
  avoidable_per_farm_qtl: num,
  unavoidable_per_farm_qtl: num,
  verdict: str,
  chain: ChainSummarySchema,
});
export type RupeeReport = v.InferOutput<typeof RupeeReportSchema>;

/** The surplus split of one direct lane. */
export const DirectSplitSchema = v.object({
  retail_price: num,
  farmer_fallback_per_qtl: num,
  delivered_ratio: num,
  logistics_per_farm_qtl: numOrNull,
  effective_markup: numOrNull,
  alpha: numOrNull,
  farm_price_per_qtl: num,
  mandi_price_per_qtl: numOrNull,
  consumer_price_per_delivered_qtl: num,
  farmer_gain_per_farm_qtl: numOrNull,
  consumer_saving_per_farm_qtl: numOrNull,
  total_surplus_per_farm_qtl: numOrNull,
  farmer_share_rs: numOrNull,
  logistics_share_rs: numOrNull,
  platform_share_rs: numOrNull,
  consumer_outlay_per_farm_qtl: numOrNull,
  farmer_gain_pct: numOrNull,
  consumer_saving_pct: numOrNull,
  farmer_share_of_consumer_rupee_pct: numOrNull,
  viable: v.optional(v.boolean(), true),
  reason: v.optional(v.string(), ''),
});
export type DirectSplit = v.InferOutput<typeof DirectSplitSchema>;

/** POST /api/v1/direct/fair-price — what a direct lane would pay both sides. */
export const FairPriceReportSchema = v.object({
  viable: v.optional(v.boolean(), true),
  distance_km: numOrNull,
  freight_per_qtl: numOrNull,
  handling_per_qtl: numOrNull,
  freight_basis: strOrNull,
  split: DirectSplitSchema,
  reason: v.optional(v.string(), ''),
});
export type FairPriceReport = v.InferOutput<typeof FairPriceReportSchema>;

/** POST /api/v1/direct/plan — one allocation lane. */
export const AllocationSchema = v.object({
  allocation_id: v.optional(str, ''),
  lot_id: strOrNull,
  demand_id: strOrNull,
  farmer_id: strOrNull,
  shipment_id: v.optional(str, ''),
  farm_qtl: numOrNull,
  delivered_qtl: numOrNull,
  distance_km: numOrNull,
  farmer_price_per_qtl: numOrNull,
  mandi_price_per_qtl: numOrNull,
  farmer_gain_rs: numOrNull,
  consumer_price_per_qtl: numOrNull,
  retail_reference_per_qtl: numOrNull,
  consumer_saving_rs: numOrNull,
  surplus_rs: numOrNull,
  freight_rs: numOrNull,
  platform_fee_rs: numOrNull,
  farmer_share_rs: numOrNull,
  trace_token: strOrNull,
});
export type Allocation = v.InferOutput<typeof AllocationSchema>;

/** POST /api/v1/direct/plan — one consolidated shipment. */
export const ShipmentSchema = v.object({
  shipment_id: v.optional(str, ''),
  lane_key: v.optional(str, ''),
  distance_km: numOrNull,
  load_qtl: numOrNull,
  vehicles: v.optional(v.number(), 0),
  capacity_qtl: numOrNull,
  fill_pct: numOrNull,
  rate_basis: v.optional(str, ''),
  freight_rs: numOrNull,
  freight_per_qtl: numOrNull,
});
export type Shipment = v.InferOutput<typeof ShipmentSchema>;

export const PlanSummarySchema = v.object({
  lots_engaged: v.optional(numOrNull, null),
  groups_served: v.optional(numOrNull, null),
  supply_qtl: v.optional(numOrNull, null),
  demand_qtl: v.optional(numOrNull, null),
  moved_qtl: v.optional(numOrNull, null),
  delivered_qtl: v.optional(numOrNull, null),
  shipments: v.optional(numOrNull, null),
  avg_fill_pct: v.optional(numOrNull, null),
  farmer_gain_rs: v.optional(numOrNull, null),
  consumer_saving_rs: v.optional(numOrNull, null),
  total_surplus_rs: v.optional(numOrNull, null),
  platform_fee_rs: v.optional(numOrNull, null),
  freight_rs: v.optional(numOrNull, null),
  intermediaries_displaced: v.optional(numOrNull, null),
});
export type PlanSummary = v.InferOutput<typeof PlanSummarySchema>;

/** POST /api/v1/direct/plan — the full planner response. */
export const DirectPlanSchema = v.object({
  plan_id: v.optional(str, ''),
  allocations: v.optional(v.array(AllocationSchema), []),
  shipments: v.optional(v.array(ShipmentSchema), []),
  orders: v.optional(v.array(v.unknown()), []),
  summary: v.optional(PlanSummarySchema, {}),
  optimal: v.optional(v.boolean(), false),
  certificate: v.optional(v.unknown(), null),
});
export type DirectPlan = v.InferOutput<typeof DirectPlanSchema>;

/** GET /api/v1/direct/config — calibration metadata. Passed through loosely. */
export const DirectConfigSchema = v.object({
  category: v.optional(str, ''),
  alpha: v.optional(numOrNull, null),
  platform_fee: v.optional(numOrNull, null),
  min_load_qtl: v.optional(numOrNull, null),
});
export type DirectConfig = v.InferOutput<typeof DirectConfigSchema>;

/** GET /api/v1/direct/trace/{token} — a public, redacted crate receipt. */
export const TraceRecordSchema = v.object({
  trace_token: strOrNull,
  commodity: strOrNull,
  district: strOrNull,
  quantity_qtl: numOrNull,
  status: strOrNull,
  created_at: strOrNull,
  consumer: v.optional(v.unknown(), null),
  farmer: v.optional(v.unknown(), null),
});
export type TraceRecord = v.InferOutput<typeof TraceRecordSchema>;
