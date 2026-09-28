import * as v from 'valibot';
import type { ApiClient } from '../client.ts';
import {
  DirectConfigSchema,
  DirectPlanSchema,
  FairPriceReportSchema,
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

export interface PlanLot {
  lotId: string;
  lat: number;
  lon: number;
  supplyQtl: number;
  price: number;
}

export interface PlanDemand {
  demandId: string;
  lat: number;
  lon: number;
  demandQtl: number;
  price: number;
}

export interface PlanParams {
  lots: PlanLot[];
  demand: PlanDemand[];
  commodity?: string;
  district?: string;
  groupSize?: number;
  vehicles?: number;
  alpha?: number;
}

export interface CommitParams extends PlanParams {
  planId: string;
  ifAbsent?: 'delta_exceeded' | 'always' | 'never';
}

/**
 * DirectLink: the consumer-rupee attribution engine and the direct channel.
 *
 * `/rupee` and `/fair-price` are pure functions — no database, no network beyond
 * this call — which is why the whole demo can run without credentials.
 * `/plan` runs the engine server-side; `/plans/commit` persists it and re-runs
 * the engine rather than trusting the caller's summary.
 */
export function directApi(api: ApiClient) {
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
     * optimality certificate alongside the result.
     */
    plan: (p: PlanParams, signal?: AbortSignal) =>
      api.post('/api/v1/direct/plan', {
        body: {
          lots: p.lots.map((l) => ({
            lot_id: l.lotId,
            lat: l.lat,
            lon: l.lon,
            supply_qtl: l.supplyQtl,
            price: l.price,
          })),
          demand: p.demand.map((d) => ({
            demand_id: d.demandId,
            lat: d.lat,
            lon: d.lon,
            demand_qtl: d.demandQtl,
            price: d.price,
          })),
          ...(p.commodity ? { commodity: p.commodity } : {}),
          ...(p.district ? { district: p.district } : {}),
          ...(p.groupSize != null ? { group_size: p.groupSize } : {}),
          ...(p.vehicles != null ? { vehicles: p.vehicles } : {}),
          ...(p.alpha != null ? { alpha: p.alpha } : {}),
        },
        schema: DirectPlanSchema,
        signal,
      }),

    /**
     * Persist a plan. The server re-runs the engine from these inputs, so the
     * caller's summary is never trusted — commit the inputs, not the answer.
     */
    commit: (p: CommitParams, signal?: AbortSignal) =>
      api.post('/api/v1/direct/plans/commit', {
        auth: true,
        body: {
          plan_id: p.planId,
          lots: p.lots.map((l) => ({
            lot_id: l.lotId,
            lat: l.lat,
            lon: l.lon,
            supply_qtl: l.supplyQtl,
            price: l.price,
          })),
          demand: p.demand.map((d) => ({
            demand_id: d.demandId,
            lat: d.lat,
            lon: d.lon,
            demand_qtl: d.demandQtl,
            price: d.price,
          })),
          if_absent: p.ifAbsent ?? 'delta_exceeded',
          ...(p.commodity ? { commodity: p.commodity } : {}),
          ...(p.district ? { district: p.district } : {}),
          ...(p.groupSize != null ? { group_size: p.groupSize } : {}),
          ...(p.vehicles != null ? { vehicles: p.vehicles } : {}),
          ...(p.alpha != null ? { alpha: p.alpha } : {}),
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

/** Guard so a caller can narrow a loose plan payload without a cast. */
export const isPlanLike = (x: unknown): x is { plan_id: string } =>
  v.safeParse(v.object({ plan_id: v.string() }), x).success;
