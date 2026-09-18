/**
 * Krishi Bazaar API — TypeScript types (hand-written)
 * ===================================================
 *
 * WHY BY HAND?
 * The backend's OpenAPI document only declares a response schema for 11 of 67
 * operations. Codegen tools (openapi-typescript, orval, etc.) will type almost
 * everything as `any`, and the few schemas that DO exist will silently omit
 * fields the API actually returns. These types are written from the real
 * payloads.
 *
 * Verified against: live `/openapi.json` + real handler output.
 * Update discipline: treat this file as the contract. If a field is missing at
 * runtime, the backend broke it — don't loosen the type to hide it.
 *
 * COMPILER TARGET
 * The typed client at the bottom (createClient) uses async/await and
 * Object.entries, so this file needs ES2017 or newer. With a default (ES5)
 * tsconfig you get two errors that are not real problems:
 *     TS2705: An async function ... requires the 'Promise' constructor
 *     TS2550: Property 'entries' does not exist on type 'ObjectConstructor'
 * Fix by setting, in your tsconfig.json:
 *     "target": "es2017", "lib": ["es2017", "dom"]
 * The types themselves (everything above createClient) compile under strict
 * mode with no errors.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Enums — the closed vocabularies the UI must render
// ─────────────────────────────────────────────────────────────────────────────

/** Sale-window recommendation, as a stable machine value. */
export type SaleAction = "SELL_NOW" | "HOLD" | "WAIT";
export type SaleRecommendation = "sell" | "hold" | "wait";

/** Stable codes — safe to branch on for icons/tooltips. `reason` prose is localised and may change. */
export type SaleReasonCode =
  | "sell_no_storage"
  | "sell_arrivals"
  | "sell_forecast"
  | "hold"
  | "wait";

export type Language = "en" | "mr" | "hi";
export type SupplyPressure = "high" | "normal" | "low";
export type ForecastTrend = "up" | "down" | "flat";

export type ForecastConfidence = "high" | "medium" | "low";
export type ForecastStatus = "ok" | "insufficient_data" | "stale";
export type ForecastMethod = "ma" | "ols" | "feature_ols" | "gbm" | "holt_winters" | "blend" | "naive";

/** Lot lifecycle. Monotonic — the backend rejects backwards transitions. */
export type LotStatus = "open" | "offered" | "matched" | "sold" | "withdrawn";
export type LotGrade = "FAQ" | "General" | "Special";

/** Read a lot back as one of these; you can only WRITE `accepted` | `rejected`. */
export type OfferStatus = "pending" | "accepted" | "rejected" | "expired";

export type PaymentStatus = "pending" | "paid" | "failed" | "disputed";

/** Active = requested | confirmed. completed/cancelled are terminal. */
export type BookingStatus = "requested" | "confirmed" | "completed" | "cancelled";

export type GrievanceStatus = "open" | "in_progress" | "resolved" | "rejected";
export type GrievanceCategory = "payment" | "quality" | "logistics" | "buyer" | "other";

export type BuyerType = "trader" | "processor" | "institutional" | "fpo" | "digital";
export type PaymentReliability = "high" | "medium" | "low";
export type VerificationState = "pending" | "approved" | "rejected";

export type UserRole = "farmer" | "buyer" | "fpo" | "admin";

export type LogisticsKind = "transport" | "storage";

/** Machine codes on a match — map these to human labels; never render raw. */
export type MatchReason =
  | "verified"
  | "same_district"
  | "price_covers_ask"
  | "bid_below_ask"
  | "volume_fit"
  | "bid_low"
  | "reliability_high"
  | "reliability_medium"
  | "reliability_low"
  | "distance_ok"
  | "distance_far"
  | (string & {});

// ─────────────────────────────────────────────────────────────────────────────
// Reference data
// ─────────────────────────────────────────────────────────────────────────────

export interface Market {
  id: string;
  name: string;
  district: string;
  state: string;
  taluka: string | null;
  lat: number;
  lng: number;
  is_active: boolean;
}

export interface MarketNearby extends Market {
  /** Only present on GET /api/v1/markets/nearby */
  distance_km: number;
}

export interface Commodity {
  id: string;
  name_en: string;
  name_mr: string;
  name_hi: string;
  /** "vegetable" | "oilseed" | "cereal" */
  category: string;
  standard_unit: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Prices and forecasts
// ─────────────────────────────────────────────────────────────────────────────

export interface PriceRecord {
  id: string;
  market_id: string;
  commodity_id: string;
  /** "YYYY-MM-DD" */
  arrival_date: string;
  min_price: number | null;
  max_price: number | null;
  modal_price: number;
  /** Always "quintal" — all prices are normalised to Rs/quintal at ingest. */
  unit: string;
  /** MAY BE NULL — the source did not report arrivals. Grey the widget, don't show 0. */
  arrival_qty: number | null;
  variety: string;
  grade: string;
  source: string;
  created_at?: string;
  // Flattened joins — present on /prices/latest and /prices/historical
  market_name?: string | null;
  district?: string | null;
  commodity_name_en?: string | null;
  commodity_name_mr?: string | null;
  commodity_name_hi?: string | null;
}

export interface Forecast {
  id: string | null;
  market_id: string;
  commodity_id: string;
  /** "YYYY-MM-DD" */
  forecast_date: string;
  predicted_price: number | null;
  lower_bound: number | null;
  upper_bound: number | null;
  confidence: ForecastConfidence | null;
  method: ForecastMethod | string;
  observations: number | null;
  status: ForecastStatus;
  generated_at: string | null;
  // Flattened joins — present on /forecasts and /forecasts/summary
  market_name?: string | null;
  district?: string | null;
  commodity_name_en?: string | null;
  commodity_name_mr?: string | null;
  commodity_name_hi?: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Sale window — the headline recommendation
// ─────────────────────────────────────────────────────────────────────────────

export interface SaleWindow {
  commodity_id: string;
  market_id: string | null;
  recommendation: SaleRecommendation;
  action: SaleAction;
  /**
   * ALREADY LOCALISED by the backend when you pass ?lang=mr|hi.
   * Render this directly. Do NOT build your own translation map.
   *   en: Sell Now / Hold / Wait
   *   mr: आज विका / थोडे थांबा / थांबा
   *   hi: आज बेचें / थोड़ा रुकें / रुकें
   */
  action_label: string;
  reason: string;
  reason_code: SaleReasonCode | string | null;
  lang: Language;
  latest_price: number | null;
  forecast_day1: number | null;
  forecast_trend: ForecastTrend | null;
  arrivals_qty: number | null;
  district_arrivals_qty: number | null;
  supply_pressure: SupplyPressure | string | null;
  nearby: MarketNearby[];
  market_name: string | null;
  /** Nearby cold-storage facilities. */
  storage: StorageFacility[];
  storage_available: boolean | null;
  district: string | null;
  /** Non-null when a neighbouring mandi pays meaningfully more — a strong upsell card. */
  better_market: BetterMarket | null;
}

export interface BetterMarket {
  market_id: string;
  market: string | null;
  price: number;
  delta: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Matching
// ─────────────────────────────────────────────────────────────────────────────

export interface MatchItem {
  buyer_id: string;
  buyer_name: string;
  buyer_type: BuyerType | string;
  verified: boolean;
  district: string | null;
  score: number;
  reasons: MatchReason[];
  max_price: number | null;
  demand_qty_qtl: number | null;
  payment_reliability: PaymentReliability | string | null;
  distance_km: number | null;
}

export interface MatchesResponse {
  lot_id: string;
  /** MAY BE NULL — the lot has no verified local buyer yet. Render an empty state. */
  best_buyer: MatchItem | null;
  /** Up to 10. */
  matches: MatchItem[];
  advice: string;
}

// ─────────────────────────────────────────────────────────────────────────────
// Profile
// ─────────────────────────────────────────────────────────────────────────────

export interface UserProfile {
  id: string;
  name: string | null;
  /** E.164, e.g. "+919812345678". */
  phone: string | null;
  role: UserRole;
  /** Drive your whole i18n default from this. New farmers default to "mr". */
  preferred_language: Language;
  district: string | null;
  lat: number | null;
  lng: number | null;
  created_at?: string;
  updated_at?: string;
}

/** PATCH /api/v1/me/ — omission means "leave unchanged". `role` is NOT writable. */
export interface ProfileUpdate {
  name?: string;
  phone?: string;
  preferred_language?: Language;
  district?: string;
  lat?: number;
  lng?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Marketplace
// ─────────────────────────────────────────────────────────────────────────────

export interface Lot {
  id: string;
  user_id: string;
  commodity_id: string;
  market_id: string | null;
  quantity_qtl: number;
  grade: LotGrade | string;
  quality_notes: string | null;
  harvest_date: string | null;
  asking_price: number | null;
  status: LotStatus;
  fpo_id: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface LotCreate {
  commodity_id: string;
  market_id?: string | null;
  /** > 0 and <= 1,000,000 */
  quantity_qtl: number;
  grade?: LotGrade;
  quality_notes?: string | null;
  /** "YYYY-MM-DD" */
  harvest_date?: string | null;
  asking_price?: number | null;
  fpo_id?: string | null;
}

export interface LotGradeUpdate {
  grade: LotGrade;
  quality_notes?: string | null;
}

/** POST /api/v1/lots/aggregate — role `fpo` required. 2–50 lots, all `open`, one commodity. */
export interface LotAggregate {
  /** min 2, max 50 */
  lot_ids: string[];
  asking_price?: number | null;
  market_id?: string | null;
}

export interface Offer {
  id: string;
  lot_id: string;
  buyer_id: string;
  price_per_qtl: number;
  quantity_qtl: number;
  status: OfferStatus;
  created_at?: string;
  updated_at?: string;
  /** Computed by the API (created_at + 48h). Use this for countdowns — don't compute it. */
  expires_at?: string | null;
}

export interface OfferCreate {
  lot_id: string;
  buyer_id: string;
  price_per_qtl: number;
  quantity_qtl: number;
}

/** Only `accepted` | `rejected` are writable. Sending "expired" returns 422. */
export interface OfferUpdate {
  status: "accepted" | "rejected";
}

export interface Payment {
  id: string;
  offer_id: string;
  amount: number;
  reference: string | null;
  status: PaymentStatus;
  paid_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface PaymentCreate {
  offer_id: string;
  amount: number;
  reference?: string | null;
}

export interface Grievance {
  id: string;
  user_id: string;
  offer_id: string | null;
  lot_id: string | null;
  category: GrievanceCategory;
  description: string;
  status: GrievanceStatus;
  created_at?: string;
  updated_at?: string;
}

export interface GrievanceCreate {
  category: GrievanceCategory;
  /** 5–2000 chars */
  description: string;
  offer_id?: string | null;
  lot_id?: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Advice — the composite object behind the farmer's main screen
// ─────────────────────────────────────────────────────────────────────────────

export interface LotAdvice {
  lot_id: string;
  action: SaleAction;
  action_label: string;
  reason: string;
  /** MAY BE NULL — render nothing rather than an empty card. */
  next_step: string | null;
  /** MAY BE NULL if there is no recent price for the commodity. */
  sale_window: SaleWindow | null;
  /** MAY BE NULL — no verified buyer fits yet. */
  best_buyer: MatchItem | null;
  /** Up to 5 here; /matches gives up to 10. */
  matches: MatchItem[];
  bookings: LogisticsBooking[];
  suggested_transport: LogisticsOption[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Ledger — the transparent record (render as a vertical stepper)
// ─────────────────────────────────────────────────────────────────────────────

export type LedgerEventType =
  | "lot_created"
  | "offer_pending" | "offer_accepted" | "offer_rejected" | "offer_expired"
  | "payment_pending" | "payment_paid" | "payment_failed" | "payment_disputed"
  | "grievance_open" | "grievance_in_progress" | "grievance_resolved" | "grievance_rejected"
  | "booking_requested" | "booking_confirmed" | "booking_completed" | "booking_cancelled"
  | (string & {});

export interface LedgerEvent {
  at: string;
  type: LedgerEventType;
  detail: Record<string, unknown>;
}

export interface LotLedger {
  lot: Lot;
  offers: Offer[];
  payments: Payment[];
  grievances: Grievance[];
  bookings: LogisticsBooking[];
  /** Pre-sorted merged timeline. Render directly. */
  events: LedgerEvent[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Buyers
// ─────────────────────────────────────────────────────────────────────────────

export interface Buyer {
  id: string;
  name: string;
  type: BuyerType;
  verified: boolean;
  phone: string | null;
  district: string | null;
  lat: number | null;
  lng: number | null;
  commodity_id: string | null;
  demand_qty_qtl: number | null;
  max_price: number | null;
  quality_requirements: string | null;
  payment_reliability: PaymentReliability | null;
  // Present on admin responses; may be absent on the public list
  verification_state?: VerificationState;
  review_notes?: string | null;
  owner_user_id?: string;
  created_at?: string;
  updated_at?: string;
}

export interface BuyerRegisterRequest {
  /** 2–200 chars */
  name: string;
  type: BuyerType;
  district: string;
  phone: string;
  commodity_id?: string | null;
  demand_qty_qtl?: number | null;
  max_price?: number | null;
  quality_requirements?: string | null;
  payment_reliability?: PaymentReliability | null;
  lat?: number | null;
  lng?: number | null;
}

export interface BuyerSupplyResponse {
  buyer_id: string;
  buyer_name: string;
  lots: Lot[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Logistics and storage
// ─────────────────────────────────────────────────────────────────────────────

export interface LogisticsOption {
  id: string;
  name: string;
  kind: LogisticsKind;
  district: string | null;
  /** Capacity in quintals. May be null (uncapped). */
  capacity_qtl: number | null;
  rate_per_qtl: number | null;
  contact?: string | null;
  is_active: boolean;
  created_at?: string;
}

export interface LogisticsBooking {
  id: string;
  user_id: string;
  lot_id: string;
  logistics_id: string;
  kind: LogisticsKind | string;
  quantity_qtl: number;
  status: BookingStatus;
  scheduled_date: string | null;
  notes: string | null;
  option_name?: string | null;
  rate_per_qtl?: number | null;
  created_at?: string;
  updated_at?: string;
}

export interface LogisticsBookCreate {
  lot_id: string;
  logistics_id: string;
  quantity_qtl?: number | null;
  /** "YYYY-MM-DD" */
  scheduled_date?: string | null;
  notes?: string | null;
}

export interface LogisticsBookUpdate {
  status: "confirmed" | "cancelled" | "completed";
  notes?: string | null;
}

export interface StorageFacility {
  id: string;
  district: string;
  name: string;
  capacity_qtl: number;
  rate_per_qtl: number;
  contact: string | null;
  lat: number | null;
  lng: number | null;
  is_active: boolean;
  created_at: string;
}

export interface StorageBooking {
  id: string;
  user_id: string;
  lot_id: string;
  facility_id: string;
  quantity_qtl: number;
  status: BookingStatus;
  storage_start_date: string | null;
  storage_end_date: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface StorageBookCreate {
  lot_id: string;
  facility_id: string;
  quantity_qtl: number;
  storage_start_date?: string | null;
  storage_end_date?: string | null;
  notes?: string | null;
}

export interface StorageBookUpdate {
  status: "confirmed" | "cancelled" | "completed";
  notes?: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Alerts
// ─────────────────────────────────────────────────────────────────────────────

export interface Alert {
  id: string;
  user_id: string;
  commodity_id: string;
  /** null = resolve to the nearest market at check time */
  market_id: string | null;
  threshold_price: number;
  /** gte = sell signal, lte = buy-input signal */
  condition: "gte" | "lte";
  active: boolean;
  expires_at: string | null;
  last_notified_at: string | null;
  notified_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface AlertCreate {
  commodity_id: string;
  market_id?: string | null;
  /** must be > 0 */
  threshold_price: number;
  condition: "gte" | "lte";
  expires_at?: string | null;
}

/** Omission = leave unchanged. Explicit `expires_at: null` CLEARS the expiry. */
export interface AlertUpdate {
  threshold_price?: number | null;
  condition?: "gte" | "lte" | null;
  active?: boolean | null;
  expires_at?: string | null;
}

// ─────────────────────────────────────────────────────────────────────────────
// Errors — ONE handler must cope with BOTH shapes below
// ─────────────────────────────────────────────────────────────────────────────

export interface ValidationErrorItem {
  loc: (string | number)[];
  msg: string;
  type: string;
}

/** FastAPI validation failure (422) and most business errors. */
export type ApiErrorBody =
  | { detail: string }
  | { detail: ValidationErrorItem[] };

/** Type guard — use this in your error renderer. */
export function isValidationError(
  body: unknown
): body is { detail: ValidationErrorItem[] } {
  return (
    typeof body === "object" &&
    body !== null &&
    "detail" in body &&
    Array.isArray((body as { detail: unknown }).detail)
  );
}

export function errorMessage(body: unknown, fallback = "Something went wrong"): string {
  if (isValidationError(body)) {
    return body.detail.map((d) => d.msg).join(", ") || fallback;
  }
  if (typeof body === "object" && body !== null && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
  }
  return fallback;
}

/**
 * Status cheat-sheet:
 *   400 bad input / referenced record missing / booking qty > lot qty
 *   401 missing, invalid or expired token        -> refresh session, retry once
 *   403 authenticated but wrong role             -> hide the feature
 *   404 not found OR NOT YOURS                   -> show an empty state, NOT "permission denied"
 *   409 invalid state transition / duplicate / capacity / cross-tenant
 *   422 validation failed (Pydantic or an invalid enum/id)
 *   429 rate limited (120 req/min/IP global)
 *   503 data store unavailable or a job failed   -> retry-able banner
 */
export type ApiStatus = 400 | 401 | 403 | 404 | 409 | 422 | 429 | 500 | 503;

// ─────────────────────────────────────────────────────────────────────────────
// Optional: a tiny typed fetch wrapper
// ─────────────────────────────────────────────────────────────────────────────
//
//   const api = createClient({ baseUrl: import.meta.env.VITE_API_BASE_URL });
//   const w = await api.get<SaleWindow>("/api/v1/sale-window/", {
//     query: { commodity_id: onionId, lang: "mr" },
//   });
//
// Point VITE_API_BASE_URL at the mock (http://localhost:8000) during dev and at
// the real backend for integration — no code change.

export interface ClientOptions {
  baseUrl: string;
  /** Return the Supabase access token, or null when signed out. */
  getToken?: () => string | null | Promise<string | null>;
  onUnauthorized?: () => void;
}

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown) {
    super(errorMessage(body, `HTTP ${status}`));
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export interface RequestOptions {
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
}

export function createClient(opts: ClientOptions) {
  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    options?: RequestOptions
  ): Promise<T> {
    const url = new URL(path, opts.baseUrl);
    if (options?.query) {
      for (const [k, v] of Object.entries(options.query)) {
        if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
      }
    }

    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const token = await opts.getToken?.();
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const res = await fetch(url.toString(), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: options?.signal,
    });

    const text = await res.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    if (!res.ok) {
      if (res.status === 401) opts.onUnauthorized?.();
      throw new ApiError(res.status, parsed);
    }
    return parsed as T;
  }

  return {
    get: <T>(p: string, o?: RequestOptions) => request<T>("GET", p, undefined, o),
    post: <T>(p: string, b?: unknown, o?: RequestOptions) => request<T>("POST", p, b, o),
    patch: <T>(p: string, b?: unknown, o?: RequestOptions) => request<T>("PATCH", p, b, o),
    del: <T>(p: string, o?: RequestOptions) => request<T>("DELETE", p, undefined, o),
  };
}
