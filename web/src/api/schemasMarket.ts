// Authenticated endpoints (profile, alerts, marketplace). Shapes follow
// frontend_handoff/types/api-types.ts. looseObject keeps unknown extra fields rather than
// failing: the OpenAPI models under-declare what the API returns (API_CONTRACT §9.1).
import * as v from 'valibot';

const str = v.string();
const strOrNull = v.nullish(v.string(), null);
const numOrNull = v.nullish(v.number(), null);

export const ProfileSchema = v.looseObject({
  id: str,
  name: strOrNull,
  phone: strOrNull,
  role: v.picklist(['farmer', 'buyer', 'fpo', 'admin']),
  preferred_language: v.optional(v.picklist(['en', 'mr', 'hi']), 'mr'),
  district: strOrNull,
  lat: numOrNull,
  lng: numOrNull,
});
export type Profile = v.InferOutput<typeof ProfileSchema>;

export const AlertSchema = v.looseObject({
  id: str,
  commodity_id: str,
  market_id: strOrNull,                       // null = nearest mandi at check time
  threshold_price: v.number(),
  condition: v.picklist(['gte', 'lte']),
  active: v.optional(v.boolean(), true),
  expires_at: strOrNull,
  last_notified_at: strOrNull,
  notified_count: v.optional(v.number(), 0),
  created_at: v.optional(str),
});
export type Alert = v.InferOutput<typeof AlertSchema>;

export const LotStatus = v.picklist(['open', 'offered', 'matched', 'sold', 'withdrawn']);
export const LotSchema = v.looseObject({
  id: str,
  user_id: str,
  commodity_id: str,
  market_id: strOrNull,
  quantity_qtl: v.number(),
  grade: str,
  quality_notes: strOrNull,
  harvest_date: strOrNull,
  asking_price: numOrNull,
  status: LotStatus,
  fpo_id: strOrNull,
  created_at: v.optional(str),
});
export type Lot = v.InferOutput<typeof LotSchema>;

export const OfferSchema = v.looseObject({
  id: str,
  lot_id: str,
  buyer_id: str,
  price_per_qtl: v.number(),
  quantity_qtl: v.number(),
  status: v.picklist(['pending', 'accepted', 'rejected', 'expired']),
  created_at: v.optional(str),
  expires_at: strOrNull,                     // computed by the API: never compute it here
});
export type Offer = v.InferOutput<typeof OfferSchema>;

export const PaymentSchema = v.looseObject({
  id: str,
  offer_id: str,
  amount: v.number(),
  reference: strOrNull,
  status: v.picklist(['pending', 'paid', 'failed', 'disputed']),
  paid_at: strOrNull,
  created_at: v.optional(str),
});
export type Payment = v.InferOutput<typeof PaymentSchema>;

export const GrievanceSchema = v.looseObject({
  id: str,
  lot_id: strOrNull,
  offer_id: strOrNull,
  category: str,
  description: str,
  status: str,
  created_at: v.optional(str),
});
export type Grievance = v.InferOutput<typeof GrievanceSchema>;

export const MatchSchema = v.looseObject({
  buyer_id: str,
  buyer_name: str,
  buyer_type: str,
  verified: v.boolean(),
  district: strOrNull,
  score: v.number(),
  reasons: v.array(str),
  max_price: numOrNull,
  demand_qty_qtl: numOrNull,
  payment_reliability: strOrNull,
  distance_km: numOrNull,
});
export type Match = v.InferOutput<typeof MatchSchema>;

export const LogisticsOptionSchema = v.looseObject({
  id: str,
  name: str,
  kind: str,
  district: strOrNull,
  capacity_qtl: numOrNull,
  rate_per_qtl: numOrNull,
  contact: strOrNull,
});
export type LogisticsOption = v.InferOutput<typeof LogisticsOptionSchema>;

export const BookingSchema = v.looseObject({
  id: str,
  lot_id: str,
  status: str,
  quantity_qtl: v.number(),
  kind: v.optional(strOrNull, null),
  logistics_id: v.optional(strOrNull, null),
  facility_id: v.optional(strOrNull, null),
  option_name: v.optional(strOrNull, null),
});
export type Booking = v.InferOutput<typeof BookingSchema>;

export const FacilitySchema = v.looseObject({
  id: str,
  name: str,
  district: strOrNull,
  capacity_qtl: numOrNull,
  rate_per_qtl: numOrNull,
  contact: strOrNull,
});
export type Facility = v.InferOutput<typeof FacilitySchema>;

export const LotAdviceSchema = v.looseObject({
  lot_id: str,
  action: v.picklist(['SELL_NOW', 'HOLD', 'WAIT']),
  action_label: str,                          // already localised
  reason: str,                                // already localised
  next_step: strOrNull,                       // may be null: render nothing
  best_buyer: v.nullish(MatchSchema, null),
  matches: v.optional(v.array(MatchSchema), []),
  bookings: v.optional(v.array(BookingSchema), []),
  suggested_transport: v.optional(v.array(LogisticsOptionSchema), []),
});
export type LotAdvice = v.InferOutput<typeof LotAdviceSchema>;

export const MatchesSchema = v.looseObject({
  lot_id: str,
  best_buyer: v.nullish(MatchSchema, null),
  matches: v.array(MatchSchema),
  advice: v.optional(str, ''),
});

export const LedgerSchema = v.looseObject({
  lot: LotSchema,
  events: v.array(v.looseObject({ at: str, type: str, detail: v.optional(v.record(str, v.unknown()), {}) })),
});
export type Ledger = v.InferOutput<typeof LedgerSchema>;

export const BuyerSchema = v.looseObject({
  id: str,
  name: str,
  type: str,
  verified: v.boolean(),
  district: strOrNull,
  commodity_id: strOrNull,
  demand_qty_qtl: numOrNull,
  max_price: numOrNull,
  verification_state: v.optional(strOrNull, null),
});
export type Buyer = v.InferOutput<typeof BuyerSchema>;

export const SupplySchema = v.looseObject({
  buyer_id: str,
  buyer_name: str,
  lots: v.array(LotSchema),
});

export const OkSchema = v.unknown();
