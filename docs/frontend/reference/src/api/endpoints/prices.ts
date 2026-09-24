import * as v from 'valibot';
import type { ApiClient } from '../client.ts';
import { PriceRowSchema } from '../schemas.ts';

export interface PairParams { marketId: string; commodityId: string }

export function pricesApi(api: ApiClient) {
  return {
    /** Raw rows: newest-first, possibly several per day. Collapse with toDailyRows() before charting. */
    historical: (p: PairParams & { days: number }, signal?: AbortSignal) =>
      api.get('/api/v1/prices/historical', {
        query: { market_id: p.marketId, commodity_id: p.commodityId, days: p.days, limit: 1000 },
        schema: v.array(PriceRowSchema),
        signal,
      }),
    latest: (p: Partial<PairParams> & { limit?: number }, signal?: AbortSignal) =>
      api.get('/api/v1/prices/latest', {
        query: { market_id: p.marketId, commodity_id: p.commodityId, limit: p.limit ?? 50 },
        schema: v.array(PriceRowSchema),
        signal,
      }),
  };
}
