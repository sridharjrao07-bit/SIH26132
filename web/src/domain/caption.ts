import type { ChartSeries } from './chartSeries.ts';

/** Facts for the chart caption sentence. Wording lives in the i18n catalogs. */
export interface CaptionFacts {
  days: number;
  changePct: number | null;
  direction: 'up' | 'down' | 'flat' | null;
  range: { lower: number; upper: number } | null;
  horizonDays: number;
}

export function captionFacts(s: ChartSeries, days: number): CaptionFacts {
  const c = s.changePct;
  return {
    days,
    changePct: c,
    direction: c == null ? null : Math.abs(c) < 1 ? 'flat' : c > 0 ? 'up' : 'down',
    range: s.forecastRange,
    horizonDays: s.horizonDays,
  };
}
