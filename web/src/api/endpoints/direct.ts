import type { ApiClient } from '../client.ts';
import {
  DirectConfigSchema,
  DirectPlanSchema,
  FairPriceReportSchema,
  GroupBuyReportSchema,
  RupeeReportSchema,
  TraceRecordSchema,
} from '../schemasDirect.ts';

export interface RupeeParams {
  farmPrice: number;
  retailPrice: number;
  commodity: string;
  market?: string;
  distanceKm?: number;
  chain?: string;
  region?: string;
}

export interface FairPriceParams {
  farmPrice: number;
  retailPrice: number;
  originLat: number;
  originLng: number;
  destLat: number;
  destLng: number;
  quantityQtl: number;
  commodity?: string;
  utility?: number;
  perishability?: number;
  region?: string;
  handlingCostPerQtl?: number;
  farmerShare?: number;
  displaced?: number;
  stranded?: number;
}

/**
 * One supply lot for the planner.
 *
 * Field names are the backend's, not ours: `id`, `commodity_id`,
 * `quantity_qtl` and `mandi_price_per_qtl` are all required by `LotIn`.
 * `mandi_price_per_qtl` is the fallback the farmer would get at the mandi, not
 * the price being asked for — that distinction is what the surplus is measured
 * against.
 */
export interface PlanLot {
  id: string;
  commodityId: string;
  quantityQtl: number;
  mandiPricePerQtl: number;
  lat?: number;
  lng?: number;
  farmerId?: string;
  marketName?: string;
  grade?: string;
  category?: string;
}

/** One demand node for the planner. `id`, `commodity_id` and `quantity_qtl` are required. */
export interface PlanDemand {
  id: string;
  commodityId: string;
  quantityQtl: number;
  retailPricePerQtl?: number;
  lat?: number;
  lng?: number;
  label?: string;
  kind?: string;
  category?: string;
  minGrade?: string;
}

export interface PlanParams {
  lots: PlanLot[];
  demands: PlanDemand[];
  alpha?: number;
  platformFeePct?: number;
  maxDistanceKm?: number;
  minAllocationQtl?: number;
  clusterSizeKm?: number;
  circuity?: number;
  calibrate?: boolean;
  enforceGrade?: boolean;
}

/** One consumer order in a group buy. `orderId` and `qtl` are required. */
export interface GroupOrder {
  orderId: string;
  qtl: number;
  lat?: number;
  lng?: number;
  label?: string;
}

export interface GroupBuyParams {
  originLat: number;
  originLng: number;
  orders: GroupOrder[];
  minLoadQtl?: number;
  clusterSizeKm?: number;
  circuity?: number;
}

/**
 * DirectLink: the consumer-rupee attribution engine and the direct channel.
 *
 * `/rupee` and `/fair-price` are pure functions — no database — which is why the
 * whole demo can run without credentials. `/plan` runs the engine server-side;
 * `/plans/commit` persists it and re-runs the engine rather than trusting the
 * caller's summary.
 */
export function directApi(api: ApiClient) {
  const toLot = (l: PlanLot) => ({
    id: l.id,
    commodity_id: l.commodityId,
    quantity_qtl: l.quantityQtl,
    mandi_price_per_qtl: l.mandiPricePerQtl,
    ...(l.lat != null ? { lat: l.lat } : {}),
    ...(l.lng != null ? { lng: l.lng } : {}),
    ...(l.farmerId ? { farmer_id: l.farmerId } : {}),
    ...(l.marketName ? { market_name: l.marketName } : {}),
    ...(l.grade ? { grade: l.grade } : {}),
    ...(l.category ? { category: l.category } : {}),
  });

  const toDemand = (d: PlanDemand) => ({
    id: d.id,
    commodity_id: d.commodityId,
    quantity_qtl: d.quantityQtl,
    ...(d.retailPricePerQtl != null ? { retail_price_per_qtl: d.retailPricePerQtl } : {}),
    ...(d.lat != null ? { lat: d.lat } : {}),
    ...(d.lng != null ? { lng: d.lng } : {}),
    ...(d.label ? { label: d.label } : {}),
    ...(d.kind ? { kind: d.kind } : {}),
    ...(d.category ? { category: d.category } : {}),
    ...(d.minGrade ? { min_grade: d.minGrade } : {}),
  });

  /** The shared engine knobs. Sent only when set, so the server defaults apply. */
  const planKnobs = (p: PlanParams) => ({
    ...(p.alpha != null ? { alpha: p.alpha } : {}),
    ...(p.platformFeePct != null ? { platform_fee_pct: p.platformFeePct } : {}),
    ...(p.maxDistanceKm != null ? { max_distance_km: p.maxDistanceKm } : {}),
    ...(p.minAllocationQtl != null ? { min_allocation_qtl: p.minAllocationQtl } : {}),
    ...(p.clusterSizeKm != null ? { cluster_size_km: p.clusterSizeKm } : {}),
    ...(p.circuity != null ? { circuity: p.circuity } : {}),
    ...(p.calibrate != null ? { calibrate: p.calibrate } : {}),
    ...(p.enforceGrade != null ? { enforce_grade: p.enforceGrade } : {}),
  });

  return {
    /** Calibration metadata: platform fee, spoilage bounds, dispatch defaults. */
    config: (signal?: AbortSignal) =>
      api.get('/api/v1/direct/config', { schema: DirectConfigSchema, signal }),

    /**
     * The consumer-rupee breakdown. This is the headline claim of the concept,
     * so it is a required field on every screen that quotes it.
     */
    rupee: (p: RupeeParams, signal?: AbortSignal) =>
      api.post('/api/v1/direct/rupee', {
        body: {
          farm_price: p.farmPrice,
          retail_price: p.retailPrice,
          commodity: p.commodity,
          ...(p.market ? { market: p.market } : {}),
          ...(p.distanceKm != null ? { distance_km: p.distanceKm } : {}),
          ...(p.chain ? { chain: p.chain } : {}),
          ...(p.region ? { region: p.region } : {}),
        },
        schema: RupeeReportSchema,
        signal,
      }),

    /** What one direct lane would pay the farmer and charge the consumer. */
    fairPrice: (p: FairPriceParams, signal?: AbortSignal) =>
      api.post('/api/v1/direct/fair-price', {
        body: {
          farm_price: p.farmPrice,
          retail_price: p.retailPrice,
          origin_lat: p.originLat,
          origin_lng: p.originLng,
          dest_lat: p.destLat,
          dest_lng: p.destLng,
          quantity_qtl: p.quantityQtl,
          ...(p.commodity ? { commodity: p.commodity } : {}),
          ...(p.utility != null ? { utility: p.utility } : {}),
          ...(p.perishability != null ? { perishability: p.perishability } : {}),
          ...(p.region ? { region: p.region } : {}),
          ...(p.handlingCostPerQtl != null
            ? { handling_cost_per_qtl: p.handlingCostPerQtl }
            : {}),
          ...(p.farmerShare != null ? { farmer_share: p.farmerShare } : {}),
          ...(p.displaced != null ? { displaced: p.displaced } : {}),
          ...(p.stranded != null ? { stranded: p.stranded } : {}),
        },
        schema: FairPriceReportSchema,
        signal,
      }),

    /**
     * Run the planner. Pure engine: the server allocates supply to demand,
     * consolidates into shipments and splits the surplus, returning an
     * optimality certificate in `impact.allocation_optimal`.
     */
    plan: (p: PlanParams, signal?: AbortSignal) =>
      api.post('/api/v1/direct/plan', {
        body: {
          lots: p.lots.map(toLot),
          demands: p.demands.map(toDemand),
          ...planKnobs(p),
        },
        schema: DirectPlanSchema,
        signal,
      }),

    /**
     * Persist a plan. The whole `PlanRequest` is nested under `plan` — the
     * server re-runs the engine from those inputs, so the caller's numbers are
     * never trusted. Commit the inputs, not the answer.
     */
    commit: (
      p: PlanParams & { planId?: string; commodityId?: string; district?: string },
      signal?: AbortSignal,
    ) =>
      api.post('/api/v1/direct/plans/commit', {
        auth: true,
        body: {
          plan: {
            lots: p.lots.map(toLot),
            demands: p.demands.map(toDemand),
            ...planKnobs(p),
          },
          ...(p.commodityId ? { commodity_id: p.commodityId } : {}),
          ...(p.district ? { district: p.district } : {}),
          ...(p.planId ? { plan_id: p.planId } : {}),
        },
        schema: DirectPlanSchema,
        signal,
      }),

    /** Fetch a stored plan by id. */
    planById: (planId: string, signal?: AbortSignal) =>
      api.get(`/api/v1/direct/plans/${encodeURIComponent(planId)}`, {
        schema: DirectPlanSchema,
        signal,
      }),

    /**
     * Truck-load consolidation for consumers. The origin is the delivery point
     * every order is consolidated towards; each order keeps its own coordinates
     * so the engine can cluster nearby consumers into one truck.
     */
    groupBuy: (p: GroupBuyParams, signal?: AbortSignal) =>
      api.post('/api/v1/direct/group-buy', {
        body: {
          origin_lat: p.originLat,
          origin_lng: p.originLng,
          orders: p.orders.map((o) => ({
            order_id: o.orderId,
            qtl: o.qtl,
            ...(o.lat != null ? { lat: o.lat } : {}),
            ...(o.lng != null ? { lng: o.lng } : {}),
            ...(o.label ? { label: o.label } : {}),
          })),
          ...(p.minLoadQtl != null ? { min_load_qtl: p.minLoadQtl } : {}),
          ...(p.clusterSizeKm != null ? { cluster_size_km: p.clusterSizeKm } : {}),
          ...(p.circuity != null ? { circuity: p.circuity } : {}),
        },
        schema: GroupBuyReportSchema,
        signal,
      }),

    /**
     * Public, unauthenticated crate receipt. No names, phone numbers or
     * coordinates come back — by design, so a QR code on a crate is safe to
     * publish. An unknown token 404s, which the client surfaces as null.
     */
    trace: (token: string, signal?: AbortSignal) =>
      api
        .get(`/api/v1/direct/trace/${encodeURIComponent(token)}`, {
          schema: TraceRecordSchema,
          signal,
        })
        .catch(() => null),
  };
}

export type DirectApi = ReturnType<typeof directApi>;
