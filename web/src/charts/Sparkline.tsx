import type { DailyPoint } from '../domain/dailyRows.ts';
import { daysBetween } from '../domain/dates.ts';

/** 64×20, ink only, dot on the last point. A missing day breaks the line. */
export function Sparkline({ daily, w = 64, h = 20 }: { daily: DailyPoint[]; w?: number; h?: number }) {
  if (daily.length < 2) return <svg width={w} height={h} aria-hidden />;
  const vals = daily.map((d) => d.modal);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const first = daily[0].date, total = Math.max(daysBetween(first, daily[daily.length - 1].date), 1);
  const pt = (d: DailyPoint) => [(daysBetween(first, d.date) / total) * (w - 4) + 2, h - 2 - ((d.modal - lo) / span) * (h - 4)] as const;
  let path = '';
  daily.forEach((d, i) => {
    const [x, y] = pt(d);
    const gap = i > 0 && daysBetween(daily[i - 1].date, d.date) > 1;
    path += `${i === 0 || gap ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const [lx, ly] = pt(daily[daily.length - 1]);
  return (
    <svg width={w} height={h} aria-hidden className="overflow-visible">
      <path d={path} fill="none" stroke="currentColor" strokeWidth={1.5} />
      <circle cx={lx} cy={ly} r={2} fill="currentColor" />
    </svg>
  );
}
