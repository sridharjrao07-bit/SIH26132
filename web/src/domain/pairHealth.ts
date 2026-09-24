// One verdict per (market, commodity) pair, from four inputs (Phase 1 §4, with the review's
// staleness input). Every chart state maps to exactly one message.
import type { ForecastRow } from '../api/schemas.ts';
import { hoursSince } from './format.ts';

export type PairHealth = 'ok' | 'aging' | 'stale' | 'insufficient_data' | 'no_prices';

export interface PairHealthInput {
  hasPrices: boolean;                         // any daily point in range
  forecastRun: readonly ForecastRow[];        // selectLatestRun(/forecasts)
  summaryStatus: string | null;               // /forecasts/summary row for this pair, or null if absent
  now?: number;
}

export const AGING_HOURS = 24;

export function pairHealth({ hasPrices, forecastRun, summaryStatus, now = Date.now() }: PairHealthInput): PairHealth {
  if (!hasPrices) return 'no_prices';
  if (forecastRun.length > 0) {
    const gen = forecastRun[0].generated_at;
    return gen && hoursSince(gen, now) > AGING_HOURS ? 'aging' : 'ok';
  }
  if (summaryStatus === 'insufficient_data') return 'insufficient_data';
  // Prices exist but no usable forecast and the pair is missing from the summary (48h cutoff):
  // the forecast is stale, not absent. /forecasts never returns stale rows, so nothing is drawn (F2).
  return 'stale';
}
