import { lazy, Suspense, useMemo } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useQueries, useQuery } from '@tanstack/react-query';
import { Trans, useLingui } from '@lingui/react/macro';
import {
  commoditiesQuery, forecastQuery, historyQuery, marketsQuery, saleWindowQuery, summaryQuery,
} from '../../queries/index.ts';
import { usePrefs, type Pair } from '../../stores/prefs.ts';
import { buildChartSeries } from '../../domain/chartSeries.ts';
import { pairHealth } from '../../domain/pairHealth.ts';
import { istToday } from '../../domain/dates.ts';
import { formatINR, formatPct } from '../../domain/format.ts';
import { captionFacts } from '../../domain/caption.ts';
import type { Commodity, SaleWindow } from '../../api/schemas.ts';
import type { Lang } from '../../i18n/locales.ts';
import { Section } from '../../ui/Section.tsx';
import { Select } from '../../ui/Select.tsx';
import { Block } from '../../ui/Skeleton.tsx';
import { CropIcon } from '../../ui/CropIcons.tsx';
// Recharts is ~half the JS. Lazy so price + verdict paint first on 3G.
const PriceForecastChart = lazy(() =>
  import('../../charts/PriceForecastChart.tsx').then((m) => ({ default: m.PriceForecastChart })),
);
import { VERDICT_BG } from '../sale-window/verdict.ts';
import { BetterMarketCard } from '../sale-window/BetterMarketCard.tsx';
import { OtherMarketsList } from '../markets/OtherMarketsList.tsx';
import { AsOfStamp } from '../trust/AsOfStamp.tsx';
import { HealthNotice } from '../trust/HealthNotice.tsx';
import { ModelChip } from '../trust/ModelChip.tsx';
import { AccuracyCard } from '../trust/AccuracyCard.tsx';
import { ChartCaption } from './ChartCaption.tsx';

export const RANGES = [30, 90, 180, 365] as const;
export type Range = (typeof RANGES)[number];

export const cropName = (c: Commodity | undefined, lang: Lang) =>
  !c ? '' : (lang === 'mr' ? c.name_mr : lang === 'hi' ? c.name_hi : c.name_en) || c.name_en;

interface Props {
  pair: Pair;
  range: Range;
  onPairChange: (p: Pair) => void;
  onRangeChange: (r: Range) => void;
}

/* ── Verdict icon SVGs ──────────────────────────────────────────── */
function VerdictIcon({ action }: { action: SaleWindow['action'] }) {
  if (action === 'SELL_NOW') {
    return (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
      </svg>
    );
  }
  if (action === 'HOLD') {
    return (
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d="M5 12h14M12 5l7 7-7 7" />
      </svg>
    );
  }
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="10" /><path d="M12 8v4l3 3" />
    </svg>
  );
}

/* ── Delta (price change) ────────────────────────────────────────── */
function Delta({ now, before }: { now: number; before: number }) {
  const diff = now - before;
  const pct = (diff / before) * 100;
  if (Math.abs(diff) < 0.5)
    return <p className="text-sm text-white/70"><Trans>— Same as the last price</Trans></p>;
  const abs = formatINR(Math.abs(diff));
  const p = formatPct(pct);
  return (
    <p className="tabular text-sm text-white/80 animate-fade flex items-center gap-1">
      <span className="inline-block">{diff > 0 ? '▲' : '▼'}</span>
      {diff > 0
        ? <Trans>{abs} ({p}) from yesterday</Trans>
        : <Trans>{abs} ({p}) from yesterday</Trans>}
    </p>
  );
}

/* ── Empty / No-prices illustration ─────────────────────────────── */
function EmptyIllustration({ kind }: { kind: 'no_prices' | 'offline' }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
      {/* Crop/field SVG illustration */}
      <svg width="64" height="64" viewBox="0 0 64 64" fill="none" stroke="var(--color-ink-2)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <rect x="8" y="48" width="48" height="4" rx="2"/>
        <path d="M20 48 C20 48 18 36 24 28 C28 22 32 20 32 20"/>
        <path d="M44 48 C44 48 46 36 40 28 C36 22 32 20 32 20"/>
        <path d="M32 20 L32 10"/>
        <path d="M28 14 C29 11 34 10 36 13"/>
        <path d="M24 40 C26 36 30 35 32 38"/>
        <path d="M40 40 C38 36 34 35 32 38"/>
      </svg>
      <p className="mt-4 text-base font-semibold text-ink">
        {kind === 'offline'
          ? <Trans>Showing saved prices — reconnect for live data</Trans>
          : <Trans>No prices available yet</Trans>}
      </p>
      <p className="mt-1 text-sm text-ink-2">
        {kind === 'offline'
          ? <Trans>Check the date on each price shown below.</Trans>
          : <Trans>This mandi hasn't reported prices yet. Try checking after 9 AM.</Trans>}
      </p>
    </div>
  );
}

/* ── Main PairView ───────────────────────────────────────────────── */
export function PairView({ pair, range, onPairChange, onRangeChange }: Props) {
  const { t } = useLingui();
  const lang = usePrefs((s) => s.lang);
  const district = usePrefs((s) => s.district);
  const navigate = useNavigate();

  const commodities = useQuery(commoditiesQuery());
  const markets = useQuery(marketsQuery(district));
  const [history, forecast, summary, sale] = useQueries({
    queries: [historyQuery(pair, range), forecastQuery(pair), summaryQuery(), saleWindowQuery(pair, lang)],
  });

  const today = istToday();
  const series = useMemo(
    () => (history.data ? buildChartSeries(history.data, forecast.data ?? [], today) : null),
    [history.data, forecast.data, today],
  );
  const summaryRow =
    summary.data?.find((r) => r.market_id === pair.marketId && r.commodity_id === pair.commodityId) ?? null;
  const health =
    history.data && forecast.data && summary.data
      ? pairHealth({
          hasPrices: history.data.length > 0,
          forecastRun: forecast.data,
          summaryStatus: summaryRow?.status ?? null,
        })
      : null;

  const daily = history.data ?? [];
  const last = daily.at(-1);
  const prev = daily.at(-2);
  const market = markets.data?.find((m) => m.id === pair.marketId);
  const crop = commodities.data?.find((c) => c.id === pair.commodityId);
  const head = forecast.data?.[0];
  const showForecastMeta = health === 'ok' || health === 'aging';
  const isForecastLoading = forecast.isPending && !forecast.data;

  return (
    <div className="lg:grid lg:grid-cols-[400px_1fr] lg:gap-x-12 pb-12">

      {/* ── PAIR SWITCHER (sticky top, paper surface) ──────────────── */}
      <section
        className="rule-b bg-paper px-4 lg:px-0 py-3 sticky top-14 z-10 lg:col-span-2"
        aria-label={t`Select crop and mandi`}
      >
        <div className="flex flex-wrap items-center gap-3 w-full max-w-[1120px] mx-auto">
          {/* Crop icon beside selector */}
          {crop && (
            <div
              className="flex size-8 shrink-0 items-center justify-center rounded-lg"
              style={{ background: 'var(--color-accent-tint)' }}
              aria-hidden
            >
              <CropIcon
                commodityId={pair.commodityId}
                size={18}
                stroke="var(--color-accent)"
              />
            </div>
          )}
          <Select
            label={t`Commodity`}
            value={pair.commodityId}
            onChange={(c) => onPairChange({ ...pair, commodityId: c })}
            className="flex-1 rounded-lg border border-rule bg-paper text-ink focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none transition-colors"
          >
            {(commodities.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{cropName(c, lang)}</option>
            ))}
          </Select>
          <Select
            label={t`Primary APMC`}
            value={pair.marketId}
            onChange={(m) => onPairChange({ ...pair, marketId: m })}
            className="flex-1 rounded-lg border border-rule bg-paper text-ink focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none transition-colors"
          >
            {(markets.data ?? []).map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </Select>
        </div>
      </section>

      {/* ── LEFT COLUMN: Hero → Reason → Alert → Model ─────────────── */}
      <div className="mt-0">

        {/* DARK HERO PANEL (ink-hero surface, 0px radius) */}
        <div
          className="relative overflow-hidden"
          style={{
            background: isForecastLoading
              ? undefined   // will use aurora-bg
              : 'linear-gradient(135deg, #0F0E0C 0%, #1C1A17 50%, #0F0E0C 100%)',
            ...(isForecastLoading
              ? {
                  backgroundImage:
                    'linear-gradient(135deg, #0F0E0C 0%, #1e1b4b 20%, #134e4a 40%, #2e1065 60%, #1e1b4b 80%, #0F0E0C 100%)',
                  backgroundSize: '400% 400%',
                  animation: 'aurora 6s ease-in-out infinite',
                }
              : {}),
          }}
        >
          <div className="px-4 lg:px-6 pt-6 pb-8">

            {history.isPending || sale.isPending ? (
              /* ── Loading skeleton inside dark hero ── */
              <div className="space-y-4">
                <Block h={40} dark />
                <Block h={64} w={200} dark />
                <Block h={20} w={160} dark />
                <Block h={48} dark />
              </div>
            ) : last ? (
              <>
                {/* 1. VERDICT BAND */}
                {sale.data && (
                  <div id="verdict" aria-live="polite" className="verdict-band mb-5 -mx-4 lg:-mx-6 overflow-hidden">
                    <div
                      aria-hidden
                      className={`verdict-band-fill ${VERDICT_BG[sale.data.action]}`}
                      style={{ animation: 'band 260ms cubic-bezier(0.16,1,0.3,1) both' }}
                    />
                    <div
                      className="verdict-band-content px-4 lg:px-6 py-3 flex items-center gap-3 text-white"
                      style={{ animation: 'rise 220ms cubic-bezier(0.16,1,0.3,1) both' }}
                    >
                      <VerdictIcon action={sale.data.action} />
                      <p className="text-lg font-bold tracking-wide uppercase">
                        {sale.data.action_label}
                      </p>
                    </div>
                  </div>
                )}

                {/* 2. PRICE — cross-fades on first load */}
                <div className="mb-4" style={{ animation: 'count-up 400ms cubic-bezier(0.16,1,0.3,1) both' }}>
                  <p className="tabular text-white leading-none" style={{ fontSize: '48px', fontWeight: 700 }}>
                    {formatINR(last.modal)}
                    <span className="text-lg font-normal text-white/60 ml-1"><Trans>/quintal</Trans></span>
                  </p>
                  {prev && <div className="mt-2"><Delta now={last.modal} before={prev.modal} /></div>}
                </div>

                {/* 3. REASON */}
                {sale.data && (
                  <p className="text-white/70 text-sm mb-5 leading-relaxed" style={{ animation: 'rise 220ms 60ms cubic-bezier(0.16,1,0.3,1) both' }}>
                    {sale.data.reason}
                  </p>
                )}

                {/* AS-OF STAMP */}
                <div className="mb-0">
                  <AsOfStamp
                    priceDate={last.date}
                    generatedAt={showForecastMeta ? head?.generated_at : null}
                    dark
                  />
                </div>
              </>
            ) : (
              <EmptyIllustration kind="no_prices" />
            )}
          </div>
        </div>

        {/* ── RECOMMENDATION (accent-tint surface) ─────────────────── */}
        {sale.data?.reason && (
          <div className="mx-4 lg:mx-0 mt-4 rounded-2xl border border-accent/20 p-4" style={{ background: 'var(--color-accent-tint)' }}>
            <div className="flex items-start gap-2.5">
              <div className="mt-0.5 flex shrink-0 size-5 items-center justify-center rounded-full" style={{ background: 'var(--color-accent)' }} aria-hidden>
                <svg width="10" height="10" viewBox="0 0 24 24" fill="white" aria-hidden>
                  <path d="M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2zm1 15h-2v-6h2zm0-8h-2V7h2z"/>
                </svg>
              </div>
              <div>
                <p className="text-xs font-bold uppercase tracking-wide mb-1" style={{ color: 'var(--color-accent)' }}>
                  <Trans>Why this verdict?</Trans>
                </p>
                <p className="text-sm text-ink leading-relaxed">
                  {sale.data.reason}
                </p>
              </div>
            </div>
          </div>
        )}

        {/* ── ALERT CTA CARD (paper surface, shadow) ───────────────── */}
        {last && (
          <div className="mx-4 lg:mx-0 mt-4 rounded-2xl border border-rule p-4 flex items-center gap-3 cursor-pointer hover:bg-paper-2 transition-colors" style={{ boxShadow: 'var(--shadow-card)' }} onClick={() => navigate({ to: '/alerts' })}>
            <div className="flex shrink-0 size-10 items-center justify-center rounded-xl" style={{ background: 'var(--color-accent-tint)' }} aria-hidden>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-ink"><Trans>Set a price alert</Trans></p>
              <p className="text-xs text-ink-2"><Trans>SMS when price crosses your target</Trans></p>
            </div>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="m9 18 6-6-6-6"/>
            </svg>
          </div>
        )}

        {/* ── MODEL ACCURACY CARD (paper-2 surface) ─────────────────── */}
        <div className="mx-4 lg:mx-0 mt-4 mb-6">
          <AccuracyCard compact />
        </div>
      </div>

      {/* ── RIGHT COLUMN: Chart → Other Mandis ─────────────────────── */}
      <div className="px-4 lg:px-0 mt-2 lg:mt-8">
        <Section
          title={<Trans>Price trend</Trans>}
          aside={
            <div role="tablist" aria-label={t`Range`} className="flex gap-0.5">
              {RANGES.map((r) => (
                <button
                  key={r}
                  role="tab"
                  aria-selected={range === r}
                  onClick={() => onRangeChange(r)}
                  className={`tap min-w-10 px-2 text-sm rounded-lg transition-colors chip-press ${
                    range === r
                      ? 'font-semibold text-accent bg-accent-tint'
                      : 'text-ink-2 hover:bg-paper-2'
                  }`}
                >
                  {r === 365 ? t`1y` : t`${r}d`}
                </button>
              ))}
            </div>
          }
        >
          {!series || !health ? (
            <Block h={300} />
          ) : health === 'no_prices' ? (
            <HealthNotice kind="no_prices" />
          ) : (
            <>
              {series.hasGap && (
                <p className="mb-2 text-xs font-semibold text-ink-2">
                  <Trans>No mandi price for the last {series.missingDays} days (dotted line).</Trans>
                </p>
              )}
              {/* key forces remount → fade animation on range change */}
              <div key={range} style={{ animation: 'fade 220ms cubic-bezier(0.16,1,0.3,1) both' }}>
                <Suspense fallback={<Block h={292} />}>
                  <PriceForecastChart
                    series={showForecastMeta ? series : buildChartSeries(daily, [], today)}
                    lang={lang}
                  />
                </Suspense>
              </div>
              {range >= 180 && showForecastMeta && (
                <button
                  onClick={() => onRangeChange(30)}
                  className="tap text-sm font-semibold text-accent underline underline-offset-4 mt-1"
                >
                  <Trans>Enlarge the forecast ›</Trans>
                </button>
              )}
              {health !== 'ok' && (
                <div className="mt-3">
                  <HealthNotice kind={health} observations={summaryRow?.observations} />
                </div>
              )}
              <ChartCaption
                facts={captionFacts(
                  showForecastMeta ? series : buildChartSeries(daily, [], today),
                  range,
                )}
              />
              {showForecastMeta && head && (
                <div className="rule-t mt-3 pt-3">
                  <ModelChip
                    method={head.method}
                    confidence={head.confidence}
                    observations={head.observations}
                    generatedAt={head.generated_at}
                    modelVersion={head.model_version}
                  />
                </div>
              )}
            </>
          )}
        </Section>

        {sale.data?.better_market && markets.data && (
          <Section className="mt-6">
            <BetterMarketCard
              better={sale.data.better_market}
              markets={markets.data}
              commodityId={pair.commodityId}
              from={market}
            />
          </Section>
        )}

        <Section title={<Trans>Other mandis · {cropName(crop, lang)}</Trans>} className="mt-6">
          <OtherMarketsList
            commodityId={pair.commodityId}
            current={market}
            markets={markets.data ?? []}
          />
        </Section>
      </div>
    </div>
  );
}
