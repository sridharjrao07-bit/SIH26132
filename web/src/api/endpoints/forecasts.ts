import * as v from 'valibot';
import type { ApiClient } from '../client.ts';
import { ForecastRowSchema } from '../schemas.ts';
import type { PairParams } from './prices.ts';

export function forecastsApi(api: ApiClient) {
  return {
    /** status='ok' rows only, window [today, today+days-1]. Pass through selectLatestRun(). */
    forPair: (p: PairParams, signal?: AbortSignal) =>
      api.get('/api/v1/forecasts', {
        query: { market_id: p.marketId, commodity_id: p.commodityId, days: 7 },
        schema: v.array(ForecastRowSchema),
        signal,
      }),
    summary: (signal?: AbortSignal) =>
      api.get('/api/v1/forecasts/summary', { schema: v.array(ForecastRowSchema), signal }),
  };
}
