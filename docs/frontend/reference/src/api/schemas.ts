// Runtime mirrors of frontend_handoff/types/api-types.ts for the price/forecast surface.
// Only fields the UI reads are strict; extra fields pass through (v.object ignores unknown keys).
import * as v from 'valibot';

const isoDate = v.pipe(v.string(), v.regex(/^\d{4}-\d{2}-\d{2}$/));
const num = v.number();
const numOrNull = v.nullish(v.number(), null);

export const PriceRowSchema = v.object({
  market_id: v.string(),
  commodity_id: v.string(),
  arrival_date: isoDate,
  min_price: numOrNull,
  max_price: numOrNull,
  modal_price: num,
  arrival_qty: numOrNull,                       // G2: nullable
  variety: v.optional(v.string(), 'General'),
  grade: v.optional(v.string(), 'General'),
  source: v.string(),
  market_name: v.nullish(v.string(), null),
  commodity_name_en: v.nullish(v.string(), null),
  commodity_name_mr: v.nullish(v.string(), null),
  commodity_name_hi: v.nullish(v.string(), null),
});
export type PriceRow = v.InferOutput<typeof PriceRowSchema>;

export const ForecastRowSchema = v.object({
  market_id: v.string(),
  commodity_id: v.string(),
  forecast_date: isoDate,
  predicted_price: numOrNull,
  lower_bound: numOrNull,
  upper_bound: numOrNull,
  confidence: v.nullish(v.string(), null),     // 'high' | 'medium' ('low' is dormant, F5)
  method: v.string(),                           // open set: never narrow to a union (G4)
  observations: numOrNull,
  status: v.string(),
  generated_at: v.nullish(v.string(), null),
  model_version: v.nullish(v.string(), null),   // G5, null until the backend ships it
  features_used: v.nullish(v.unknown(), null),  // G5
});
export type ForecastRow = v.InferOutput<typeof ForecastRowSchema>;
