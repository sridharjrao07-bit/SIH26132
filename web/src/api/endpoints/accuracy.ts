import type { ApiClient } from '../client.ts';
import { ApiError } from '../errors.ts';
import { AccuracySchema, type Accuracy } from '../schemas.ts';

export type AccuracyReport = Accuracy | { status: 'not_published' };

export function accuracyApi(api: ApiClient) {
  return {
    get: async (signal?: AbortSignal): Promise<AccuracyReport> => {
      try {
        return await api.get('/api/v1/forecasts/accuracy', { schema: AccuracySchema, signal });
      } catch (e) {
        // G6 not deployed yet → honest "not published" state, with no invented numbers
        if (e instanceof ApiError && e.kind === 'not_found') return { status: 'not_published' };
        throw e;
      }
    },
  };
}
