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
// Recharts is ~half the JS. Lazy so price + verdict paint first on 3G; the chart streams in after.
const PriceForecastChart = lazy(() => import('../../charts/PriceForecastChart.tsx').then((m) => ({ default: m.PriceForecastChart })));
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

function VerdictIcon({ action }: { action: SaleWindow['action'] }) {
  if (action === 'SELL_NOW') {
    return (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
      </svg>
    );
  }
  if (action === 'HOLD') {
    return (
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 12h14M12 5l7 7-7 7" />
      </svg>
    );
  }
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v4l3 3" />
    </svg>
  );
}

function Delta({ now, before }: { now: number; before: number }) {
  const diff = now - before;
  const pct = (diff / before) * 100;
  if (Math.abs(diff) < 0.5) return <p className="text-sm"><Trans>— Same as the last price</Trans></p>;
  const abs = formatINR(Math.abs(diff));
  const p = formatPct(pct);
  // Ink + arrow, never red/green: colour is reserved for the verdict.
  // We use opacity animation here for price change (Motion 2)
  return (
    <p className="tabular text-sm animate-fade">
      {diff > 0 ? <Trans>▲ {abs} ({p})</Trans> : <Trans>▼ {abs} ({p})</Trans>}
    </p>
  );
}

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
  const summaryRow = summary.data?.find((r) => r.market_id === pair.marketId && r.commodity_id === pair.commodityId) ?? null;
  const health = history.data && forecast.data && summary.data
    ? pairHealth({ hasPrices: history.data.length > 0, forecastRun: forecast.data, summaryStatus: summaryRow?.status ?? null })
    : null;

  const daily = history.data ?? [];
  const last = daily.at(-1);
  const prev = daily.at(-2);
  const market = markets.data?.find((m) => m.id === pair.marketId);
  const crop = commodities.data?.find((c) => c.id === pair.commodityId);
  const head = forecast.data?.[0];
  const showForecastMeta = health === 'ok' || health === 'aging';

  return (
    <div className="lg:grid lg:grid-cols-[400px_1fr] lg:gap-x-12 max-w-[1120px] mx-auto pb-12">
      {/* PairSwitcher: header context */}
      <section className="bg-paper border-b border-rule px-space-md lg:px-0 py-3 sticky top-0 z-[10] lg:col-span-2">
        <div className="flex flex-wrap items-center gap-3 w-full">
          <Select label={t`Commodity`} value={pair.commodityId} onChange={(c) => onPairChange({ ...pair, commodityId: c })} className="flex-1 rounded-sm border border-rule bg-paper text-ink font-label-md text-label-md focus:border-ink">
            {(commodities.data ?? []).map((c) => <option key={c.id} value={c.id}>{cropName(c, lang)}</option>)}
          </Select>
          <Select label={t`Primary APMC`} value={pair.marketId} onChange={(m) => onPairChange({ ...pair, marketId: m })} className="flex-1 rounded-sm border border-rule bg-paper text-ink font-label-md text-label-md focus:border-ink">
            {(markets.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </Select>
        </div>
      </section>

      {/* LEFT COLUMN: Verdict -> Price -> Reason */}
      <div className="px-space-md lg:px-0 mt-6 lg:mt-8">
        {history.isPending || sale.isPending ? (
          <div className="space-y-4">
            <Block h={48} />
            <Block h={48} w={200} />
            <Block h={80} />
          </div>
        ) : last ? (
          <>
            {/* 1. VERDICT BAND */}
            {sale.data && (
              <div aria-live="polite" className="relative overflow-hidden mb-6 rounded-sm">
                <div aria-hidden className={`absolute inset-0 ${VERDICT_BG[sale.data.action]} origin-left animate-band`} />
                <div className="relative px-4 py-3 flex items-center gap-3 text-white animate-rise">
                  <VerdictIcon action={sale.data.action} />
                  <p className="text-xl lg:text-xl font-bold tracking-wide uppercase">{sale.data.action_label}</p>
                </div>
              </div>
            )}

            {/* 2. PRICE + DELTA */}
            <div className="mb-6 animate-fade">
              <p className="tabular text-price font-semibold">
                {formatINR(last.modal)}<span className="text-lg font-normal text-ink-2">/qtl</span>
              </p>
              {prev && <Delta now={last.modal} before={prev.modal} />}
            </div>

            {/* 3. REASON */}
            {sale.data && (
              <p className="text-base text-ink mb-6 animate-rise">
                {sale.data.reason}
              </p>
            )}

            {/* AS OF STAMP */}
            <div className="mb-8">
              <AsOfStamp priceDate={last.date} generatedAt={showForecastMeta ? head?.generated_at : null} />
            </div>
            
            {/* ALERT BUTTON */}
            <button className="tap w-full rounded-sm border border-ink px-4 font-semibold hover:bg-paper-2 transition-colors mb-6" onClick={() => navigate({ to: '/alerts' })}>
              <Trans>Send me an SMS when the price changes</Trans>
            </button>
            
            <AccuracyCard compact />
          </>
        ) : (
          <HealthNotice kind="no_prices" />
        )}
      </div>

      {/* RIGHT COLUMN: Chart -> Other Mandis */}
      <div className="px-space-md lg:px-0 mt-8 lg:mt-8">
        <Section
          title={<Trans>Price trend</Trans>}
          aside={
            <div role="tablist" aria-label={t`Range`} className="flex text-sm">
              {RANGES.map((r) => (
                <button key={r} role="tab" aria-selected={range === r} onClick={() => onRangeChange(r)}
                  className={`tap min-w-11 px-1.5 tabular ${range === r ? 'font-semibold underline underline-offset-4 text-ink' : 'text-ink-2'}`}>
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
                <p className="mb-2 text-xs font-semibold"><Trans>No mandi price for the last {series.missingDays} days (dotted line).</Trans></p>
              )}
              {/* key forces remount for animate-fade on range change */}
              <div key={range} className="animate-fade">
                <Suspense fallback={<Block h={292} />}>
                  <PriceForecastChart
                    series={showForecastMeta ? series : buildChartSeries(daily, [], today)}
                    lang={lang}
                  />
                </Suspense>
              </div>
              {range >= 180 && showForecastMeta && (
                <button onClick={() => onRangeChange(30)} className="tap text-sm font-semibold underline underline-offset-4">
                  <Trans>Enlarge the forecast ›</Trans>
                </button>
              )}
              {health !== 'ok' && <div className="mt-3"><HealthNotice kind={health} observations={summaryRow?.observations} /></div>}
              <ChartCaption facts={captionFacts(showForecastMeta ? series : buildChartSeries(daily, [], today), range)} />
              {showForecastMeta && head && (
                <div className="rule-t mt-3 pt-3">
                  <ModelChip method={head.method} confidence={head.confidence} observations={head.observations}
                    generatedAt={head.generated_at} modelVersion={head.model_version} />
                </div>
              )}
            </>
          )}
        </Section>

        {sale.data?.better_market && markets.data && (
          <Section className="mt-8">
            <BetterMarketCard better={sale.data.better_market} markets={markets.data} commodityId={pair.commodityId} from={market} />
          </Section>
        )}

        <Section title={<Trans>Other mandis · {cropName(crop, lang)}</Trans>} className="mt-8">
          <OtherMarketsList commodityId={pair.commodityId} current={market} markets={markets.data ?? []} />
        </Section>
      </div>
    </div>
  );
}
