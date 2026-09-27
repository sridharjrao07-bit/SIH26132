import { useMemo, useState } from 'react';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { MarketLatest } from '../../domain/latestByMarket.ts';
import type { Market } from '../../api/schemas.ts';
import { formatINR, formatNumber } from '../../domain/format.ts';

const palette = ['var(--color-signal)', 'var(--color-gain)', 'var(--color-accent)', 'var(--color-loss)'];
const dotClasses = ['bg-signal', 'bg-gain', 'bg-accent', 'bg-loss'];

interface Props {
  rows: MarketLatest[];
  markets: Market[];
  commodity: string;
}

export function BoardInsights({ rows, markets, commodity }: Props) {
  const [visibleMarkets, setVisibleMarkets] = useState(3);
  const marketNames = useMemo(() => new Map(markets.map((market) => [market.id, market.name])), [markets]);
  const ranked = useMemo(() => [...rows].sort((a, b) => b.modal - a.modal), [rows]);
  const selected = ranked.slice(0, visibleMarkets);

  const trendData = useMemo(() => {
    const byDay = new Map<string, Record<string, string | number>>();
    selected.forEach((row) => row.daily.forEach((day) => {
      const item = byDay.get(day.date) ?? { date: day.date.slice(5) };
      item[row.marketId] = day.modal;
      byDay.set(day.date, item);
    }));
    return [...byDay.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([, value]) => value);
  }, [selected]);

  const arrivalData = ranked.slice(0, 6).map((row) => ({
    name: marketNames.get(row.marketId) ?? row.marketName ?? row.marketId,
    value: row.arrivals ?? 0,
  }));

  const movement = rows.reduce((acc, row) => {
    if (!row.prev) return acc;
    const pct = ((row.modal - row.prev.modal) / row.prev.modal) * 100;
    if (pct > 0.25) acc.rising += 1;
    else if (pct < -0.25) acc.falling += 1;
    else acc.steady += 1;
    return acc;
  }, { rising: 0, steady: 0, falling: 0 });
  const movementData = [
    { name: 'Rising', value: movement.rising, color: 'var(--color-gain)' },
    { name: 'Steady', value: movement.steady, color: 'var(--color-warn)' },
    { name: 'Falling', value: movement.falling, color: 'var(--color-loss)' },
  ].filter((item) => item.value > 0);

  if (!rows.length) return null;

  return (
    <section className="grid gap-3 xl:grid-cols-12" aria-label="Market visualisations">
      <article className="glass-panel diagonal-panel p-4 sm:p-5 xl:col-span-7">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow">Comparative signal</p>
            <h2 className="mt-1 text-base font-semibold">7-day mandi price trend</h2>
            <p className="mt-1 text-xs text-ink-2">{commodity} · ₹ per quintal · hover or tap for values</p>
          </div>
          <div className="segmented" role="group" aria-label="Number of mandis shown">
            {[2, 3, 4].map((count) => (
              <button key={count} onClick={() => setVisibleMarkets(count)} aria-pressed={visibleMarkets === count}>
                {count} mandis
              </button>
            ))}
          </div>
        </div>
        <div className="h-64" role="img" aria-label={`Price trend for ${selected.length} mandis`}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={trendData} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--color-rule)" strokeDasharray="2 5" />
              <XAxis dataKey="date" tick={{ fill: 'var(--color-ink-2)', fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis tickFormatter={(value: number) => `₹${Math.round(value / 100) / 10}k`} tick={{ fill: 'var(--color-ink-2)', fontSize: 11 }} tickLine={false} axisLine={false} width={48} />
              <Tooltip contentStyle={{ background: 'var(--color-card)', border: '1px solid var(--color-rule)', borderRadius: 4 }} formatter={(value) => formatINR(Number(value))} />
              {selected.map((row, index) => (
                <Line key={row.marketId} dataKey={row.marketId} name={marketNames.get(row.marketId) ?? row.marketName ?? row.marketId}
                  stroke={palette[index]} strokeWidth={2.25} dot={false} activeDot={{ r: 4 }} connectNulls />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-2">
          {selected.map((row, index) => <span key={row.marketId} className="flex items-center gap-2"><i className={`size-2.5 rounded-full ${dotClasses[index]}`} />{marketNames.get(row.marketId) ?? row.marketName}</span>)}
        </div>
      </article>

      <article className="glass-panel diagonal-panel p-4 xl:col-span-3">
        <p className="eyebrow">Supply pulse</p>
        <h2 className="mt-1 text-sm font-semibold">Latest arrivals by mandi</h2>
        <div className="mt-3 h-56" role="img" aria-label="Arrival quantities by mandi">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={arrivalData} layout="vertical" margin={{ left: 0, right: 8 }}>
              <XAxis type="number" hide />
              <YAxis type="category" dataKey="name" width={72} tick={{ fill: 'var(--color-ink-2)', fontSize: 10 }} tickLine={false} axisLine={false} />
              <Tooltip cursor={{ fill: 'var(--color-paper-2)' }} contentStyle={{ background: 'var(--color-card)', border: '1px solid var(--color-rule)', borderRadius: 4 }} formatter={(value) => `${formatNumber(Number(value))} qtl`} />
              <Bar dataKey="value" fill="var(--color-signal)" radius={[0, 3, 3, 0]} maxBarSize={18} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </article>

      <article className="glass-panel diagonal-panel p-4 xl:col-span-2">
        <p className="eyebrow">Market breadth</p>
        <h2 className="mt-1 text-sm font-semibold">Direction today</h2>
        <div className="relative mx-auto mt-2 h-36 max-w-44" role="img" aria-label="Share of rising, steady and falling markets">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={movementData} dataKey="value" innerRadius={43} outerRadius={62} paddingAngle={4} stroke="none">
                {movementData.map((entry) => <Cell key={entry.name} fill={entry.color} />)}
              </Pie>
              <Tooltip contentStyle={{ background: 'var(--color-card)', border: '1px solid var(--color-rule)', borderRadius: 4 }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
            <span className="font-mono text-xl font-semibold">{rows.length}</span>
          </div>
        </div>
        <div className="space-y-2 text-xs">
          {movementData.map((item) => <div key={item.name} className="flex items-center justify-between"><span className="flex items-center gap-2"><i className={`size-2 rounded-full ${item.name === 'Rising' ? 'bg-gain' : item.name === 'Falling' ? 'bg-loss' : 'bg-warn'}`} />{item.name}</span><strong className="font-mono">{item.value}</strong></div>)}
        </div>
      </article>
    </section>
  );
}