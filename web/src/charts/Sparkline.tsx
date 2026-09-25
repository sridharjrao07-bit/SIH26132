import type { DailyPoint } from '../domain/dailyRows.ts';
import { daysBetween } from '../domain/dates.ts';

/**
 * Compact sparkline for Board rows.
 * Color-codes by trend: sell-green if rising, wait-slate if falling, hold-amber if flat.
 * Includes a subtle gradient fill beneath the line.
 */
export function Sparkline({ daily, w = 80, h = 28 }: { daily: DailyPoint[]; w?: number; h?: number }) {
  if (daily.length < 2) return <svg width={w} height={h} aria-hidden />;
  const vals = daily.map((d) => d.modal);
  const lo = Math.min(...vals), hi = Math.max(...vals), span = hi - lo || 1;
  const first = daily[0].date;
  const total = Math.max(daysBetween(first, daily[daily.length - 1].date), 1);
  const pt = (d: DailyPoint) =>
    [(daysBetween(first, d.date) / total) * (w - 4) + 2, h - 4 - ((d.modal - lo) / span) * (h - 8)] as const;

  let linePath = '';
  daily.forEach((d, i) => {
    const [x, y] = pt(d);
    const gap = i > 0 && daysBetween(daily[i - 1].date, d.date) > 1;
    linePath += `${i === 0 || gap ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  });

  /* Fill path: close the shape to the bottom */
  const [fx] = pt(daily[0]);
  const [lx, ly] = pt(daily[daily.length - 1]);
  const fillPath = `${linePath}L${lx.toFixed(1)},${(h - 2).toFixed(1)}L${fx.toFixed(1)},${(h - 2).toFixed(1)}Z`;

  /* Color by trend */
  const last = vals.at(-1) ?? 0;
  const first1 = vals[0];
  const diff = last - first1;
  const pct = (diff / first1) * 100;
  const lineColor =
    pct > 1 ? 'var(--color-sell)'
    : pct < -1 ? 'var(--color-wait)'
    : 'var(--color-hold)';
  const fillId = `sg-${w}-${h}-${Math.abs(Math.round(pct))}`;

  return (
    <svg width={w} height={h} aria-hidden className="overflow-visible">
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.15" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      {/* Gradient fill */}
      <path d={fillPath} fill={`url(#${fillId})`} />
      {/* Line */}
      <path d={linePath} fill="none" stroke={lineColor} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      {/* Terminal dot */}
      <circle cx={lx} cy={ly} r={2.5} fill={lineColor} />
    </svg>
  );
}
