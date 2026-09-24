// Every authenticated query key starts with 'auth': it is never persisted to IndexedDB and
// is wiped on sign-out (see providers.tsx and useSignOut).
import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query';
import { account, alerts, marketplace } from '../api/index.ts';
import { ApiError } from '../api/errors.ts';
import { signOut } from '../auth/session.ts';
import type { Lang } from '../i18n/locales.ts';
import { retry } from './index.ts';

const ONE_MIN = 60_000;

export const ak = {
  all: ['auth'] as const,
  me: () => ['auth', 'me'] as const,
  alerts: () => ['auth', 'alerts'] as const,
  lots: () => ['auth', 'lots'] as const,
  lot: (id: string) => ['auth', 'lots', id] as const,
  advice: (id: string, lang: Lang) => ['auth', 'lots', id, 'advice', lang] as const,
  matches: (id: string) => ['auth', 'lots', id, 'matches'] as const,
  ledger: (id: string) => ['auth', 'lots', id, 'ledger'] as const,
  storage: (id: string) => ['auth', 'lots', id, 'storage'] as const,
  offers: () => ['auth', 'offers'] as const,
  payments: () => ['auth', 'payments'] as const,
  grievances: () => ['auth', 'grievances'] as const,
  supply: (buyerId: string) => ['auth', 'supply', buyerId] as const,
};

/** 401 after the one refresh attempt means signed out: don't retry. 404 means "not yours" or gone. */
const authRetry = (n: number, e: Error) => !(e instanceof ApiError && (e.kind === 'auth' || e.kind === 'not_found')) && retry(n, e);

export const meQuery = () => queryOptions({ queryKey: ak.me(), queryFn: ({ signal }) => account.me(signal), staleTime: 10 * ONE_MIN, retry: authRetry });
export const alertsQuery = () => queryOptions({ queryKey: ak.alerts(), queryFn: ({ signal }) => alerts.list(signal), staleTime: ONE_MIN, retry: authRetry });
export const lotsQuery = () => queryOptions({ queryKey: ak.lots(), queryFn: ({ signal }) => marketplace.lots(signal), staleTime: ONE_MIN, retry: authRetry });
export const lotQuery = (id: string) => queryOptions({ queryKey: ak.lot(id), queryFn: ({ signal }) => marketplace.lot(id, signal), staleTime: ONE_MIN, retry: authRetry });
export const adviceQuery = (id: string, lang: Lang) => queryOptions({ queryKey: ak.advice(id, lang), queryFn: ({ signal }) => marketplace.advice(id, lang, signal), staleTime: 5 * ONE_MIN, retry: authRetry });
export const matchesQuery = (id: string) => queryOptions({ queryKey: ak.matches(id), queryFn: ({ signal }) => marketplace.matches(id, signal), staleTime: 5 * ONE_MIN, retry: authRetry });
export const ledgerQuery = (id: string) => queryOptions({ queryKey: ak.ledger(id), queryFn: ({ signal }) => marketplace.ledger(id, signal), staleTime: ONE_MIN, retry: authRetry });
export const storageBookingsQuery = (id: string) => queryOptions({ queryKey: ak.storage(id), queryFn: ({ signal }) => marketplace.storageBookings(id, signal), staleTime: ONE_MIN, retry: authRetry });
export const offersQuery = () => queryOptions({ queryKey: ak.offers(), queryFn: ({ signal }) => marketplace.offers(signal), staleTime: ONE_MIN, retry: authRetry });
export const paymentsQuery = () => queryOptions({ queryKey: ak.payments(), queryFn: ({ signal }) => marketplace.payments(signal), staleTime: ONE_MIN, retry: authRetry });
export const grievancesQuery = () => queryOptions({ queryKey: ak.grievances(), queryFn: ({ signal }) => marketplace.grievances(signal), staleTime: ONE_MIN, retry: authRetry });
export const supplyQuery = (buyerId: string) => queryOptions({ queryKey: ak.supply(buyerId), queryFn: ({ signal }) => marketplace.supply(buyerId, signal), staleTime: ONE_MIN, retry: authRetry });
export const facilitiesQuery = (district: string) => queryOptions({ queryKey: ['storage', 'facilities', district], queryFn: ({ signal }) => marketplace.facilities(district, signal), staleTime: 60 * ONE_MIN, retry });
export const buyersQuery = (commodityId?: string) => queryOptions({ queryKey: ['buyers', commodityId ?? 'all'], queryFn: ({ signal }) => marketplace.buyers(commodityId, signal), staleTime: 10 * ONE_MIN, retry });

/** Mutation that refreshes every authenticated query when it succeeds. Marketplace writes
 *  ripple (an accepted offer changes the lot, the ledger and sibling offers), so we refetch
 *  all of 'auth' rather than guess which keys changed. */
export function useAuthMutation<TVars, TData>(fn: (vars: TVars) => Promise<TData>, onSuccess?: (d: TData) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: async (d) => { await qc.invalidateQueries({ queryKey: ak.all }); onSuccess?.(d); },
  });
}

export function useSignOut() {
  const qc = useQueryClient();
  return async () => { await signOut(); qc.removeQueries({ queryKey: ak.all }); };
}
