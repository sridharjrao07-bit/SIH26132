import * as v from 'valibot';
import type { ApiClient } from '../client.ts';
import type { Lang } from '../../i18n/locales.ts';
import {
  BookingSchema, BuyerSchema, FacilitySchema, GrievanceSchema, LedgerSchema, LotAdviceSchema, LotSchema,
  MatchesSchema, OfferSchema, PaymentSchema, SupplySchema,
} from '../schemasMarket.ts';

export interface LotCreate {
  commodity_id: string;
  market_id?: string | null;
  quantity_qtl: number;
  grade: 'FAQ' | 'General' | 'Special';
  asking_price?: number | null;
  harvest_date?: string | null;
  quality_notes?: string | null;
}
export interface BuyerRegister {
  name: string;
  type: 'trader' | 'processor' | 'institutional' | 'fpo' | 'digital';
  district: string;
  phone: string;
  commodity_id?: string | null;
  demand_qty_qtl?: number | null;
  max_price?: number | null;
}

const A = { auth: true } as const;

export function marketplaceApi(api: ApiClient) {
  return {
    lots: (signal?: AbortSignal) => api.get('/api/v1/lots/', { ...A, schema: v.array(LotSchema), signal }),
    lot: (id: string, signal?: AbortSignal) => api.get(`/api/v1/lots/${id}`, { ...A, schema: LotSchema, signal }),
    createLot: (body: LotCreate) => api.post('/api/v1/lots/', { ...A, schema: LotSchema, body }),
    withdrawLot: (id: string) => api.patch(`/api/v1/lots/${id}/withdraw`, { ...A, schema: LotSchema, body: {} }),
    aggregate: (lot_ids: string[], asking_price?: number) =>
      api.post('/api/v1/lots/aggregate', { ...A, schema: LotSchema, body: { lot_ids, ...(asking_price ? { asking_price } : {}) } }),
    advice: (id: string, lang: Lang, signal?: AbortSignal) =>
      api.get(`/api/v1/lots/${id}/advice`, { ...A, schema: LotAdviceSchema, query: { lang }, signal }),
    matches: (id: string, signal?: AbortSignal) => api.get(`/api/v1/lots/${id}/matches`, { ...A, schema: MatchesSchema, signal }),
    ledger: (id: string, signal?: AbortSignal) => api.get(`/api/v1/lots/${id}/ledger`, { ...A, schema: LedgerSchema, signal }),

    offers: (signal?: AbortSignal) => api.get('/api/v1/offers/', { ...A, schema: v.array(OfferSchema), signal }),
    createOffer: (body: { lot_id: string; buyer_id: string; price_per_qtl: number; quantity_qtl: number }) =>
      api.post('/api/v1/offers/', { ...A, schema: OfferSchema, body }),
    /** Only accepted | rejected are writable; "expired" returns 422 (§9.2). */
    decideOffer: (id: string, status: 'accepted' | 'rejected') =>
      api.patch(`/api/v1/offers/${id}`, { ...A, schema: OfferSchema, body: { status } }),

    payments: (signal?: AbortSignal) => api.get('/api/v1/payments/', { ...A, schema: v.array(PaymentSchema), signal }),
    createPayment: (body: { offer_id: string; amount: number; reference?: string | null }) =>
      api.post('/api/v1/payments/', { ...A, schema: PaymentSchema, body }),
    markPayment: (id: string, to: 'paid' | 'failed' | 'disputed') =>
      api.patch(`/api/v1/payments/${id}/${to}`, { ...A, schema: PaymentSchema, body: {} }),

    grievances: (signal?: AbortSignal) => api.get('/api/v1/grievances/', { ...A, schema: v.array(GrievanceSchema), signal }),
    createGrievance: (body: { category: string; description: string; lot_id?: string | null; offer_id?: string | null }) =>
      api.post('/api/v1/grievances/', { ...A, schema: GrievanceSchema, body }),

    bookTransport: (body: { lot_id: string; logistics_id: string; quantity_qtl: number }) =>
      api.post('/api/v1/logistics/bookings', { ...A, schema: BookingSchema, body }),
    facilities: (district: string, signal?: AbortSignal) =>
      api.get('/api/v1/storage/facilities', { schema: v.array(FacilitySchema), query: { district }, signal }),
    storageBookings: (lotId: string, signal?: AbortSignal) =>
      api.get('/api/v1/storage/bookings', { ...A, schema: v.array(BookingSchema), query: { lot_id: lotId }, signal }),
    bookStorage: (body: { lot_id: string; facility_id: string; quantity_qtl: number }) =>
      api.post('/api/v1/storage/bookings', { ...A, schema: BookingSchema, body }),

    buyers: (commodityId?: string, signal?: AbortSignal) =>
      api.get('/api/v1/buyers/', { schema: v.array(BuyerSchema), query: { commodity_id: commodityId }, signal }),
    registerBuyer: (body: BuyerRegister) => api.post('/api/v1/buyers/register', { ...A, schema: BuyerSchema, body }),
    myBuyerProfile: (signal?: AbortSignal) => api.get('/api/v1/buyers/me', { ...A, schema: BuyerSchema, signal }),
    supply: (buyerId: string, signal?: AbortSignal) => api.get(`/api/v1/buyers/${buyerId}/supply`, { ...A, schema: SupplySchema, signal }),
  };
}
