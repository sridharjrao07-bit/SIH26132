import type { ApiClient } from '../client.ts';
import { ProfileSchema, type Profile } from '../schemasMarket.ts';

export type ProfilePatch = Partial<Pick<Profile, 'name' | 'phone' | 'preferred_language' | 'district'>>;

export function accountApi(api: ApiClient) {
  return {
    me: (signal?: AbortSignal) => api.get('/api/v1/me/', { schema: ProfileSchema, auth: true, signal }),
    /** Omission = leave unchanged (API_CONTRACT §9.8): send only the fields the user touched. */
    update: (patch: ProfilePatch) => api.patch('/api/v1/me/', { schema: ProfileSchema, auth: true, body: patch }),
  };
}
