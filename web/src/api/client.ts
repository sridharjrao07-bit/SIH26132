import * as v from 'valibot';
import { ApiError, normalizeApiError } from './errors.ts';

type Query = Record<string, string | number | boolean | null | undefined>;

export interface ApiClientConfig {
  /** '' in the browser: same-origin, /api is proxied to FastAPI (Vite dev proxy / CDN rewrite). */
  baseUrl: string;
  /** Returns the Supabase access token, or null when logged out. Only called for auth requests. */
  getToken?: () => Promise<string | null>;
  /** Called once on 401. Return true if the session was refreshed and the request should retry. */
  refreshSession?: () => Promise<boolean>;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
}

export interface RequestOptions<S extends v.GenericSchema> {
  schema: S;
  query?: Query;
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  auth?: boolean;
  /** TanStack Query passes this; cancels in-flight requests when the pair changes. */
  signal?: AbortSignal;
}

function toSearch(query?: Query): string {
  if (!query) return '';
  const p = new URLSearchParams();
  for (const [k, val] of Object.entries(query)) {
    if (val !== undefined && val !== null && val !== '') p.set(k, String(val));
  }
  const s = p.toString();
  return s ? `?${s}` : '';
}

export function createApiClient(cfg: ApiClientConfig) {
  const doFetch = cfg.fetchImpl ?? fetch;
  const timeoutMs = cfg.timeoutMs ?? 15_000;

  async function request<S extends v.GenericSchema>(path: string, opts: RequestOptions<S>, retried = false): Promise<v.InferOutput<S>> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    if (opts.auth) {
      const token = await cfg.getToken?.();
      if (!token) throw new ApiError(401, 'auth', 'missing bearer token');
      headers.Authorization = `Bearer ${token}`;
    }

    const timeout = AbortSignal.timeout(timeoutMs);
    const signal = opts.signal ? AbortSignal.any([opts.signal, timeout]) : timeout;

    let res: Response;
    try {
      res = await doFetch(`${cfg.baseUrl}${path}${toSearch(opts.query)}`, {
        method: opts.method ?? 'GET',
        headers,
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
        signal,
      });
    } catch (e) {
      if (opts.signal?.aborted) throw e;                 // caller cancelled: let TanStack handle it
      if (timeout.aborted) throw new ApiError(0, 'timeout', 'request timed out');
      throw new ApiError(0, 'network', 'network unavailable');
    }

    if (res.status === 401 && opts.auth && !retried && (await cfg.refreshSession?.())) {
      return request(path, opts, true);                   // retry exactly once after refresh
    }

    const text = await res.text();
    const json: unknown = text ? JSON.parse(text) : null;
    if (!res.ok) throw normalizeApiError(res.status, json);

    const parsed = v.safeParse(opts.schema, json);
    if (!parsed.success) {
      // The API changed shape under us (see G10). Fail loudly in dev, cleanly in prod.
      console.error('[api contract]', path, v.flatten(parsed.issues));
      throw new ApiError(res.status, 'contract', 'unexpected response from server');
    }
    return parsed.output;
  }

  return {
    get: <S extends v.GenericSchema>(path: string, o: Omit<RequestOptions<S>, 'method' | 'body'>) => request(path, { ...o, method: 'GET' }),
    post: <S extends v.GenericSchema>(path: string, o: Omit<RequestOptions<S>, 'method'>) => request(path, { ...o, method: 'POST' }),
    patch: <S extends v.GenericSchema>(path: string, o: Omit<RequestOptions<S>, 'method'>) => request(path, { ...o, method: 'PATCH' }),
    del: <S extends v.GenericSchema>(path: string, o: Omit<RequestOptions<S>, 'method' | 'body'>) => request(path, { ...o, method: 'DELETE' }),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
