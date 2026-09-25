import type { ForecastRow } from '../api/schemas.ts';

/**
 * /forecasts dedupes per date by newest generated_at, so its output can MIX runs:
 * today's row from yesterday's run + tomorrow..+6 from today's run.
 * Keep only the newest run. The real engine stamps one generated_at per run;
 * the mock stamps per row (µs apart), hence the tolerance window.
 */
export function selectLatestRun(rows: readonly ForecastRow[], toleranceMs = 10 * 60_000): ForecastRow[] {
  // Parse once and drop rows we cannot place in time (missing/malformed generated_at).
  // Otherwise a single bad timestamp poisons Math.max -> NaN and wipes the whole run.
  const stamped = rows
    .map((r) => ({ r, ts: Date.parse(r.generated_at ?? '') }))
    .filter((x) => x.r.predicted_price != null && Number.isFinite(x.ts));
  if (stamped.length === 0) return [];
  const newest = Math.max(...stamped.map((x) => x.ts));
  return stamped
    .filter((x) => newest - x.ts <= toleranceMs)
    .map((x) => x.r)
    .sort((a, b) => (a.forecast_date < b.forecast_date ? -1 : 1));
}
