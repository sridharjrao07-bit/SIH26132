// Formats history + forecast into ONE array for a Recharts ComposedChart.
//   <Line dataKey="actual"/>  <Line dataKey="predicted" strokeDasharray="4 3"/>
//   <Line dataKey="bridge" strokeDasharray={gap ? "1 3" : "4 3"}/>  <Area dataKey="band"/>
// Recharts draws [lo, hi] array values as a range area, which gives us the band.
import type { ForecastRow } from '../api/schemas.ts';
import type { DailyPoint } from './dailyRows.ts';
import { daysBetween, toDay } from './dates.ts';

export type PointKind = 'actual' | 'forecast';

export interface ChartPoint {
  date: string;
  x: number;                          // UTC ms, for a numeric time axis
  kind: PointKind;
  actual: number | null;
  min: number | null;
  max: number | null;
  arrivals: number | null;            // consumed by the separate arrivals strip (syncId)
  predicted: number | null;
  band: [number, number] | null;
  bridge: number | null;              // only set on the two points joining actual → forecast
}
// F4: there is no synthetic *point*. The cone's zero-width start and the bridge value ride on
// the real last-actual point, and the tooltip renders strictly by `kind`: an 'actual' point
// shows actual/min/max/arrivals only, never band or bridge. So "forecast ₹2,450 ± 0" can't appear.

export interface ChartSeries {
  points: ChartPoint[];
  lastActualDate: string | null;
  /** Calendar days with no reported price between the last actual and today (0 = fresh). */
  missingDays: number;
  /** Drawn dotted grey, no cone, when data is missing (Phase 4 §3.2). */
  hasGap: boolean;
  horizonDays: number;                // derived from rows, never assume 7
  forecastRange: { lower: number; upper: number } | null;
  changePct: number | null;           // first → last actual in range, for the caption
  method: string | null;
  confidence: string | null;
  generatedAt: string | null;
  yDomain: [number, number] | null;   // non-zero baseline, 6% padding
}

const blank = (date: string, kind: PointKind): ChartPoint => ({
  date, x: toDay(date), kind, actual: null, min: null, max: null, arrivals: null,
  predicted: null, band: null, bridge: null,
});

export function buildChartSeries(daily: readonly DailyPoint[], forecast: readonly ForecastRow[], today: string): ChartSeries {
  const points: ChartPoint[] = daily.map((d) => ({
    ...blank(d.date, 'actual'),
    actual: d.modal, min: d.min, max: d.max, arrivals: d.arrivals,
  }));
  const last = daily.at(-1) ?? null;

  // Actual wins: drop forecast rows on/before the last reported day (morning ingest overlap).
  const fc = forecast.filter((f) => f.predicted_price != null && (!last || f.forecast_date > last.date));

  // "Missing" = no price before today. Today itself may simply not be reported yet.
  const missingDays = last ? Math.max(0, daysBetween(last.date, today) - 1) : 0;
  const hasGap = missingDays > 0;

  if (last && fc.length > 0) {
    const lastPt = points[points.length - 1];
    lastPt.bridge = last.modal;
    if (!hasGap) {
      // Cone starts at a point: the band fans out from the last real price.
      lastPt.band = [last.modal, last.modal];
    }
  }

  fc.forEach((f, i) => {
    const lo = f.lower_bound ?? f.predicted_price!;
    const hi = f.upper_bound ?? f.predicted_price!;
    points.push({
      ...blank(f.forecast_date, 'forecast'),
      predicted: f.predicted_price,
      band: [lo, hi],
      bridge: i === 0 && last ? f.predicted_price : null,
    });
  });

  const lows = points.flatMap((p) => [p.actual, p.min, p.band?.[0]].filter((n): n is number => n != null));
  const highs = points.flatMap((p) => [p.actual, p.max, p.band?.[1]].filter((n): n is number => n != null));
  let yDomain: [number, number] | null = null;
  if (lows.length) {
    const lo = Math.min(...lows), hi = Math.max(...highs), pad = Math.max((hi - lo) * 0.06, 1);
    yDomain = [Math.max(0, Math.floor(lo - pad)), Math.ceil(hi + pad)];
  }

  const first = daily[0];
  const head = fc[0] ?? null;
  return {
    points,
    lastActualDate: last?.date ?? null,
    missingDays,
    hasGap,
    horizonDays: fc.length,
    forecastRange: fc.length
      ? { lower: Math.min(...fc.map((f) => f.lower_bound ?? f.predicted_price!)), upper: Math.max(...fc.map((f) => f.upper_bound ?? f.predicted_price!)) }
      : null,
    changePct: first && last && first !== last ? ((last.modal - first.modal) / first.modal) * 100 : null,
    method: head?.method ?? null,
    confidence: head?.confidence ?? null,
    generatedAt: head?.generated_at ?? null,
    yDomain,
  };
}
