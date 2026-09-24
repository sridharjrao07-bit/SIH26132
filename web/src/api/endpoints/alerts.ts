import * as v from 'valibot';
import type { ApiClient } from '../client.ts';
import { AlertSchema, OkSchema } from '../schemasMarket.ts';

export interface AlertCreate {
  commodity_id: string;
  market_id: string | null;
  threshold_price: number;
  condition: 'gte' | 'lte';
  expires_at?: string | null;
}
/** Omission = unchanged. Explicit expires_at: null CLEARS the expiry. */
export type AlertPatch = Partial<Pick<AlertCreate, 'threshold_price' | 'condition' | 'expires_at'>> & { active?: boolean };

export function alertsApi(api: ApiClient) {
  return {
    list: (signal?: AbortSignal) => api.get('/api/v1/alerts/', { schema: v.array(AlertSchema), auth: true, query: { limit: 200 }, signal }),
    create: (body: AlertCreate) => api.post('/api/v1/alerts/', { schema: AlertSchema, auth: true, body }),
    update: (id: string, patch: AlertPatch) => api.patch(`/api/v1/alerts/${id}`, { schema: AlertSchema, auth: true, body: patch }),
    remove: (id: string) => api.del(`/api/v1/alerts/${id}`, { schema: OkSchema, auth: true }),
  };
}
