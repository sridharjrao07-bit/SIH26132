// Mirror of forecasting/engine.py::build_daily_rows (G1). Keep in sync, since the chart
// must show the same series the forecaster trained on.
import type { PriceRow } from '../api/schemas.ts';

export const SOURCE_PRECEDENCE: Record<string, number> = {
  data_gov_in: 1, agmarknet: 2, manual: 3, manual_seed: 4, demo_seed: 5, csv: 6,
};
const rank = (source: string) => SOURCE_PRECEDENCE[source] ?? 99;

export interface DailyPoint {
  date: string;              // YYYY-MM-DD
  modal: number;
  min: number | null;
  max: number | null;
  arrivals: number | null;   // G2: null = not reported, never 0
  source: string;
}

export function toDailyRows(rows: readonly PriceRow[]): DailyPoint[] {
  const byDate = new Map<string, PriceRow[]>();
  for (const r of rows) {
    const list = byDate.get(r.arrival_date);
    if (list) list.push(r); else byDate.set(r.arrival_date, [r]);
  }
  const out: DailyPoint[] = [];
  for (const [date, dayRows] of byDate) {
    const best = Math.min(...dayRows.map((r) => rank(r.source)));
    const candidates = dayRows.filter((r) => rank(r.source) === best);
    const chosen = candidates.find((r) => (r.variety || 'General') === 'General') ?? candidates[0];
    out.push({
      date,
      modal: chosen.modal_price,
      min: chosen.min_price,
      max: chosen.max_price,
      arrivals: chosen.arrival_qty,
      source: chosen.source,
    });
  }
  // ISO dates sort correctly as strings; ascending for charts
  return out.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
}
