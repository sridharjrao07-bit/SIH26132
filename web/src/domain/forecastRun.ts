import type { ForecastRow } from '../api/schemas.ts';

/**
 * /forecasts dedupes per date by newest generated_at, so its output can MIX runs:
 * today's row from yesterday's run + tomorrow..+6 from today's run.
 * Keep only the newest run. The real engine stamps one generated_at per run;
 * the mock stamps per row (µs apart), hence the tolerance window.
 */
export function selectLatestRun(rows: readonly ForecastRow[], toleranceMs = 10 * 60_000): ForecastRow[] {
  const stamped = rows.filter((r) => r.generated_at && r.predicted_price != null);
  if (stamped.length === 0) return [];
  const newest = Math.max(...stamped.map((r) => Date.parse(r.generated_at!)));
  return stamped
    .filter((r) => newest - Date.parse(r.generated_at!) <= toleranceMs)
    .sort((a, b) => (a.forecast_date < b.forecast_date ? -1 : 1));
}
