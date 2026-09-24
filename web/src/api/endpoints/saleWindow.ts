import type { ApiClient } from '../client.ts';
import { ApiError } from '../errors.ts';
import { SaleWindowSchema, type SaleWindow } from '../schemas.ts';
import type { Lang } from '../../i18n/locales.ts';

export function saleWindowApi(api: ApiClient) {
  return {
    /** Returns null on 404 ("no recent prices"): that's a designed empty state, not an error. */
    get: async (p: { commodityId: string; marketId: string | null; lang: Lang }, signal?: AbortSignal): Promise<SaleWindow | null> => {
      try {
        return await api.get('/api/v1/sale-window/', {
          query: { commodity_id: p.commodityId, market_id: p.marketId, lang: p.lang },
          schema: SaleWindowSchema,
          signal,
        });
      } catch (e) {
        if (e instanceof ApiError && e.kind === 'not_found') return null;
        throw e;
      }
    },
  };
}
