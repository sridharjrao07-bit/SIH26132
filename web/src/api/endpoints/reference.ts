import * as v from 'valibot';
import type { ApiClient } from '../client.ts';
import { CommoditySchema, MarketSchema } from '../schemas.ts';

export function referenceApi(api: ApiClient) {
  return {
    commodities: (signal?: AbortSignal) =>
      api.get('/api/v1/commodities/', { schema: v.array(CommoditySchema), signal }),
    markets: (district: string | undefined, signal?: AbortSignal) =>
      api.get('/api/v1/markets/', { query: { district, active_only: true }, schema: v.array(MarketSchema), signal }),
  };
}
