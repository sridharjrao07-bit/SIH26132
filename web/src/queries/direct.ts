import { queryOptions } from '@tanstack/react-query';
import { direct } from '../api/index.ts';
import { ApiError } from '../api/errors.ts';
import type { RupeeParams } from '../api/endpoints/direct.ts';
import { retry } from './index.ts';

const FIVE_MIN = 5 * 60_000;

export const dqk = {
  rupee: (p: RupeeParams) => ['direct', 'rupee', p.farmPrice, p.retailPrice, p.commodity] as const,
  fairPrice: (farmPrice: number, retailPrice: number, distanceKm: number) =>
    ['direct', 'fairPrice', farmPrice, retailPrice, distanceKm] as const,
  trace: (token: string) => ['direct', 'trace', token] as const,
};

/**
 * The consumer-rupee breakdown.
 *
 * `/rupee` is a pure function server-side — no database — so this is the one
 * headline number in the app that is available even with no credentials at all.
 * That is why it is the demo's anchor: a wrong answer here is visible to anyone.
 */
export const rupeeQuery = (p: RupeeParams) => queryOptions({
  queryKey: dqk.rupee(p),
  queryFn: ({ signal }) => direct.rupee(p, signal),
  staleTime: FIVE_MIN,
  retry,
});

/** A crate receipt looked up by its public token. Unknown tokens resolve to null. */
export const traceQuery = (token: string) => queryOptions({
  queryKey: dqk.trace(token),
  queryFn: ({ signal }) => direct.trace(token, signal),
  staleTime: FIVE_MIN,
  // A 404 on an unknown token is a legitimate answer, not a failure to retry.
  retry: (_n: number, e: Error) => e instanceof ApiError && e.retryable,
});
