import { useMemo } from 'react';
import {
  Area, Bar, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis, type TooltipProps,
} from 'recharts';
import { useLingui } from '@lingui/react/macro';
import type { ChartPoint, ChartSeries } from '../domain/chartSeries.ts';
import { formatDay, formatINR, formatNumber } from '../domain/format.ts';
import { istToday, toDay } from '../domain/dates.ts';
import type { Lang } from '../i18n/locales.ts';

const C = {
  ink: '#0F172A', ink2: '#64748B', rule: '#E2E8F0', forecast: '#6366F1', arrivals: '#CBD5E1', paper: '#FFFFFF',
};
const DAY = 86_400_000;

/** G7 slot: approved market events will render here. Empty until the backend publishes them. */
export interface Annotation { date: string; direction: 'up' | 'down' | 'uncertain'; label: string }

interface Props {
  series: ChartSeries;
  lang: Lang;
  annotations?: Annotation[];
  height?: number;
}

function ticks(points: ChartPoint[], n = 4) {
  if (points.length < 2) return points.map((p) => p.x);
  const a = points[0].x, b = points[points.length - 1].x;
  return Array.from({ length: n }, (_, i) => Math.round((a + ((b - a) * i) / (n - 1)) / DAY) * DAY);
}

/** Tooltip renders strictly by point kind: an actual day never shows band/bridge values (F4). */
export function PointTooltip({ active, payload, lang }: TooltipProps<number, string> & { lang: Lang }) {
  const { t } = useLingui();
  const p = payload?.[0]?.payload as ChartPoint | undefined;
  if (!active || !p) return null;
  const day = formatDay(p.date, lang);
  return (
    <div className="rounded border border-ink bg-paper px-2.5 py-2 text-xs shadow-none">
      {p.kind === 'actual' ? (
        <>
          <div className="font-semibold">{day}</div>
          <div className="tabular text-sm font-semibold">{formatINR(p.actual!)}</div>
          {p.min != null && p.max != null && (
            <div className="tabular text-ink-2">{t`min`} {formatINR(p.min)} – {t`max`} {formatINR(p.max)}</div>
          )}
          <div className="tabular text-ink-2">
            {t`arrivals`} {p.arrivals != null ? `${formatNumber(p.arrivals)} ${t`qtl`}` : t`not reported`}
          </div>
        </>
      ) : (
        <>
          <div className="font-semibold">{day} · {t`forecast`}</div>
          <div className="tabular text-sm font-semibold">{formatINR(p.predicted!)}</div>
          {p.band && <div className="tabular text-ink-2">{t`likely`} {formatINR(p.band[0])}–{formatINR(p.band[1])}</div>}
        </>
      )}
    </div>
  );
}

export function PriceForecastChart({ series, lang, annotations = [], height = 220 }: Props) {
  const { t } = useLingui();
  const { points, yDomain, hasGap, confidence } = series;
  const xTicks = useMemo(() => ticks(points), [points]);
  const forecastPts = points.filter((p) => p.kind === 'forecast');
  const todayX = toDay(istToday());
  const xDomain: [number, number] = [points[0]?.x ?? 0, points[points.length - 1]?.x ?? 0];
  const hasArrivals = points.some((p) => p.arrivals != null);

  const xAxis = (hide: boolean) => (
    <XAxis
      dataKey="x" type="number" scale="time" domain={xDomain} ticks={xTicks} hide={hide}
      tickFormatter={(x: number) => formatDay(new Date(x).toISOString(), lang)}
      tick={{ fill: C.ink2, fontSize: 13 }} tickLine={false} axisLine={{ stroke: C.rule }} interval="preserveStartEnd"
    />
  );

  return (
    <figure className="m-0" aria-label={t`Price chart with forecast`}>
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} syncId="pair" margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            {forecastPts.length > 0 && (
              <ReferenceArea x1={forecastPts[0].x - DAY / 2} x2={forecastPts[forecastPts.length - 1].x + DAY / 2}
                fill={C.forecast} fillOpacity={0.05} stroke="none" ifOverflow="extendDomain"
                label={{ value: t`next ${forecastPts.length} days`, position: 'insideTopRight', fill: C.ink2, fontSize: 12 }} />
            )}
            {xAxis(true)}
            <YAxis
              domain={yDomain ?? ['auto', 'auto']} tickCount={4} width={56} orientation="left" mirror
              tickFormatter={(v: number) => formatINR(v)} tick={{ fill: C.ink2, fontSize: 12, dy: -8 }} tickLine={false} axisLine={false}
            />
            <Area
              dataKey="band" isAnimationActive={false} connectNulls={false} fill={C.forecast} fillOpacity={0.16}
              // dormant: engine never emits 'low' today (F5)
              stroke={confidence === 'low' ? C.forecast : 'none'} strokeDasharray={confidence === 'low' ? '3 3' : undefined}
              activeDot={false}
            />
            <Line dataKey="actual" isAnimationActive={false} stroke={C.ink} strokeWidth={2} dot={false} connectNulls={false}
              activeDot={{ r: 4, fill: C.ink, stroke: C.paper }} />
            <Line dataKey="bridge" isAnimationActive={false} connectNulls stroke={hasGap ? C.ink2 : C.forecast}
              strokeWidth={hasGap ? 1.5 : 2} strokeDasharray={hasGap ? '1 4' : '4 3'} dot={false} activeDot={false} />
            <Line dataKey="predicted" isAnimationActive={false} stroke={C.forecast} strokeWidth={2} strokeDasharray="4 3"
              dot={false} connectNulls={false} activeDot={{ r: 4, fill: C.forecast, stroke: C.paper }} />
            {todayX >= xDomain[0] && todayX <= xDomain[1] && (
              <ReferenceLine x={todayX} stroke={C.ink2} strokeWidth={1}
                label={{ value: t`today`, position: 'insideTopLeft', fill: C.ink2, fontSize: 12 }} />
            )}
            {annotations.map((a) => (
              <ReferenceDot key={a.date + a.label} x={toDay(a.date)} y={yDomain?.[0] ?? 0} r={4}
                fill={a.direction === 'down' ? C.ink : C.paper} stroke={C.ink} ifOverflow="visible" />
            ))}
            <Tooltip trigger="click" content={<PointTooltip lang={lang} />} cursor={{ stroke: C.ink2, strokeWidth: 1 }}
              isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Arrivals: a separate strip on the same time axis, never a second y-axis (Phase 4 §3.4).
          Its scale is internal and unlabeled so nobody reads magnitude across axes. */}
      <div style={{ height: hasArrivals ? 48 : 28 }} aria-hidden={!hasArrivals}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={points} syncId="pair" margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            {xAxis(false)}
            <YAxis hide domain={[0, 'dataMax']} />
            <Bar dataKey="arrivals" fill={C.arrivals} isAnimationActive={false} maxBarSize={10} />
            <Tooltip content={() => null} cursor={{ fill: 'transparent' }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {hasArrivals && <p className="-mt-1 text-xs text-ink-2">{t`Bars: arrivals at the mandi (quintal)`}</p>}
    </figure>
  );
}
