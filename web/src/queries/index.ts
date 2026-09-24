import { queryOptions } from '@tanstack/react-query';
import { accuracy, forecasts, prices, reference, saleWindow } from '../api/index.ts';
import { ApiError } from '../api/errors.ts';
import { toDailyRows } from '../domain/dailyRows.ts';
import { selectLatestRun } from '../domain/forecastRun.ts';
import { latestByMarket } from '../domain/latestByMarket.ts';
import type { Lang } from '../i18n/locales.ts';
import type { Pair } from '../stores/prefs.ts';

const FIVE_MIN = 5 * 60_000;              // never poll faster than ingestion can change data (G9)
const SESSION = Infinity;

export const retry = (n: number, e: Error) => e instanceof ApiError && e.retryable && n < 2;

export const qk = {
  commodities: () => ['commodities'] as const,
  markets: (district: string) => ['markets', district] as const,
  history: (p: Pair, days: number) => ['prices', 'history', p.marketId, p.commodityId, days] as const,
  latest: (commodityId: string) => ['prices', 'latest', commodityId] as const,
  forecast: (p: Pair) => ['forecasts', p.marketId, p.commodityId] as const,
  summary: () => ['forecasts', 'summary'] as const,
  sale: (p: Pair, lang: Lang) => ['saleWindow', p.commodityId, p.marketId, lang] as const,
  accuracy: () => ['forecasts', 'accuracy'] as const,
};

export const commoditiesQuery = () => queryOptions({
  queryKey: qk.commodities(), queryFn: ({ signal }) => reference.commodities(signal), staleTime: SESSION, retry,
});

export const marketsQuery = (district: string) => queryOptions({
  queryKey: qk.markets(district), queryFn: ({ signal }) => reference.markets(district, signal), staleTime: SESSION, retry,
});

export const historyQuery = (p: Pair, days: number) => queryOptions({
  queryKey: qk.history(p, days),
  queryFn: ({ signal }) => prices.historical({ ...p, days }, signal),
  select: toDailyRows,
  staleTime: FIVE_MIN, retry,
});

export const latestForCommodityQuery = (commodityId: string) => queryOptions({
  queryKey: qk.latest(commodityId),
  queryFn: ({ signal }) => prices.latest({ commodityId, limit: 200 }, signal),
  select: latestByMarket,
  staleTime: FIVE_MIN, retry,
});

export const forecastQuery = (p: Pair) => queryOptions({
  queryKey: qk.forecast(p),
  queryFn: ({ signal }) => forecasts.forPair(p, signal),
  select: selectLatestRun,          // defence in depth, even after the S1 fix
  staleTime: FIVE_MIN, retry,
});

export const summaryQuery = () => queryOptions({
  queryKey: qk.summary(), queryFn: ({ signal }) => forecasts.summary(signal), staleTime: FIVE_MIN, retry,
});

export const saleWindowQuery = (p: Pair, lang: Lang) => queryOptions({
  queryKey: qk.sale(p, lang),
  queryFn: ({ signal }) => saleWindow.get({ ...p, lang }, signal),
  staleTime: FIVE_MIN, retry,
});

export const accuracyQuery = () => queryOptions({
  queryKey: qk.accuracy(), queryFn: ({ signal }) => accuracy.get(signal), staleTime: 60 * 60_000, retry,
});
