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

export const CommoditySchema = v.object({
  id: v.string(),
  name_en: v.string(),
  name_mr: v.string(),
  name_hi: v.string(),
  category: v.string(),
  standard_unit: v.optional(v.string(), 'quintal'),
});
export type Commodity = v.InferOutput<typeof CommoditySchema>;

export const MarketSchema = v.object({
  id: v.string(),
  name: v.string(),                              // always display this, never hardcode (e.g. "Lasalgaon APCM")
  district: v.string(),
  taluka: v.nullish(v.string(), null),
  lat: v.number(),
  lng: v.number(),
  is_active: v.optional(v.boolean(), true),
});
export type Market = v.InferOutput<typeof MarketSchema>;

// Real shape per notifications/sale_window.py (verified on 6ae008b). Fields the UI does not
// read are left loose on purpose: `nearby` differs between the real API and the mock (G11),
// so the UI builds "other mandis" from /prices/latest instead.
export const SaleWindowSchema = v.object({
  commodity_id: v.string(),
  market_id: v.nullish(v.string(), null),
  recommendation: v.string(),
  action: v.picklist(['SELL_NOW', 'HOLD', 'WAIT']),
  action_label: v.string(),                      // already localised: render as-is
  reason: v.string(),                            // render as-is, never parse (headlines are en-only)
  reason_code: v.nullish(v.string(), null),
  lang: v.string(),
  latest_price: numOrNull,
  forecast_day1: numOrNull,
  forecast_trend: v.nullish(v.string(), null),
  arrivals_qty: numOrNull,
  district_arrivals_qty: numOrNull,
  supply_pressure: v.nullish(v.string(), null),
  market_name: v.nullish(v.string(), null),
  storage: v.optional(v.array(v.object({ name: v.nullish(v.string(), null) })), []),
  storage_available: v.nullish(v.boolean(), null),
  better_market: v.nullish(
    v.object({
      market: v.nullish(v.string(), null),
      modal_price: v.number(),
      premium_rs: v.number(),
      arrival_qty: numOrNull,
    }),
    null,
  ),
});
export type SaleWindow = v.InferOutput<typeof SaleWindowSchema>;

// G6 contract (docs/tickets/backend_gaps_G5-G7.md, Issue 2). Not deployed yet: the UI treats
// 404 as "not published". All numbers shown in accuracy copy come from here, never constants.
export const AccuracySchema = v.object({
  status: v.string(),                            // backfill_pending | provisional | certified
  thresholds: v.nullish(v.object({
    min_forecast_days: v.nullish(v.number(), null),
    min_backtest_days: v.nullish(v.number(), null),
  }), null),
  progress: v.nullish(v.object({                 // F3, only once the backend exposes it
    max_pair_days: v.number(),
    required: v.number(),
  }), null),
  metrics: v.nullish(v.object({
    mae: numOrNull,
    wmape: numOrNull,
    interval_coverage: numOrNull,                // 0..1, drives the "N in 10" caption
    nan_rate: numOrNull,
  }), null),
  updated_at: v.nullish(v.string(), null),
});
export type Accuracy = v.InferOutput<typeof AccuracySchema>;
