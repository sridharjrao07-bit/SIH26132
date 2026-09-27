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
import type { Commodity } from '../../api/schemas.ts';
import type { Lang } from '../../i18n/locales.ts';
import { Section } from '../../ui/Section.tsx';
import { Select } from '../../ui/Select.tsx';
import { Block } from '../../ui/Skeleton.tsx';
// Recharts is ~half the JS. Lazy so price + verdict paint first on 3G; the chart streams in after.
const PriceForecastChart = lazy(() => import('../../charts/PriceForecastChart.tsx').then((m) => ({ default: m.PriceForecastChart })));
import { VerdictChip } from '../sale-window/VerdictChip.tsx';
import { SaleWindowCard, SaleWindowEmpty } from '../sale-window/SaleWindowCard.tsx';
import { BetterMarketCard } from '../sale-window/BetterMarketCard.tsx';
import { OtherMarketsList } from '../markets/OtherMarketsList.tsx';
import { AsOfStamp } from '../trust/AsOfStamp.tsx';
import { HealthNotice } from '../trust/HealthNotice.tsx';
import { ModelChip } from '../trust/ModelChip.tsx';
import { AccuracyCard } from '../trust/AccuracyCard.tsx';
import { ChartCaption } from './ChartCaption.tsx';
import { TrendIndicator } from '../../ui/TrendIndicator.tsx';

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
  const changePct = last && prev ? ((last.modal - prev.modal) / prev.modal) * 100 : null;
  const arrivalValues = daily.map((point) => point.arrivals).filter((value): value is number => value != null);
  const averageArrivals = arrivalValues.length ? arrivalValues.reduce((total, value) => total + value, 0) / arrivalValues.length : null;
  const spread = last?.min != null && last.max != null ? last.max - last.min : null;

  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_380px]">
      {/* PairSwitcher: sticky, one tap to change crop or mandi */}
      <div className="sticky top-20 z-[5] col-span-full flex gap-2 border border-rule bg-card/95 p-2 shadow-panel backdrop-blur-xl diagonal-panel">
        <Select label={t`Crop`} value={pair.commodityId} onChange={(c) => onPairChange({ ...pair, commodityId: c })} className="w-[42%]">
          {(commodities.data ?? []).map((c) => <option key={c.id} value={c.id}>{cropName(c, lang)}</option>)}
        </Select>
        <Select label={t`Mandi`} value={pair.marketId} onChange={(m) => onPairChange({ ...pair, marketId: m })} className="flex-1">
          {(markets.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </Select>
      </div>

      <section className="col-span-full grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Selected market highlights">
        <article className="glass-panel diagonal-panel metric-card p-4">
          <p className="eyebrow">Spot price</p>
          <p className="mt-3 font-mono text-2xl font-semibold">{last ? formatINR(last.modal) : '—'}</p>
          <div className="mt-2"><TrendIndicator value={changePct} compact /></div>
        </article>
        <article className="glass-panel diagonal-panel metric-card p-4">
          <p className="eyebrow">Daily spread</p>
          <p className="mt-3 font-mono text-2xl font-semibold text-warn">{spread == null ? '—' : formatINR(spread)}</p>
          <p className="mt-1 text-xs text-ink-2">min to max trading range</p>
        </article>
        <article className="glass-panel diagonal-panel metric-card p-4">
          <p className="eyebrow">Average arrivals</p>
          <p className="mt-3 font-mono text-2xl font-semibold text-signal">{averageArrivals == null ? '—' : Math.round(averageArrivals).toLocaleString('en-IN')}</p>
          <p className="mt-1 text-xs text-ink-2">quintals per reported day</p>
        </article>
        <article className="glass-panel diagonal-panel metric-card p-4">
          <p className="eyebrow">Forecast confidence</p>
          <p className="mt-3 font-mono text-2xl font-semibold text-gain">{head?.confidence ?? '—'}</p>
          <p className="mt-1 text-xs text-ink-2">{series?.horizonDays ?? 0}-day outlook</p>
        </article>
      </section>

      <div className="grid min-w-0 content-start gap-3">
        {/* 1. PRICE */}
        <Section className="market-hero">
          {history.isPending ? (
            <div className="space-y-2"><Block h={16} w={120} /><Block h={44} w={200} /><Block h={16} w={220} /></div>
          ) : last ? (
            <>
              <p className="text-sm text-ink-2"><Trans>Latest mandi price (modal)</Trans></p>
              <p className="tabular text-price font-semibold">
                {formatINR(last.modal)} <span className="text-base font-normal text-ink-2"><Trans>/quintal</Trans></span>
              </p>
              {prev && <Delta now={last.modal} before={prev.modal} />}
              {last.min != null && last.max != null && (
                <p className="tabular text-sm text-ink-2"><Trans>Min {formatINR(last.min)} · Max {formatINR(last.max)}</Trans></p>
              )}
              <div className="mt-2">
                {sale.data ? <VerdictChip sale={sale.data} /> : sale.isPending ? <Block h={48} w={160} /> : null}
              </div>
              <AsOfStamp priceDate={last.date} generatedAt={showForecastMeta ? head?.generated_at : null} />
            </>
          ) : (
            <HealthNotice kind="no_prices" />
          )}
        </Section>

        {/* 2. FORECAST BAND */}
        <Section
          title={<Trans>Price trend</Trans>}
          aside={
            <div role="tablist" aria-label={t`Range`} className="flex text-sm">
              {RANGES.map((r) => (
                <button key={r} role="tab" aria-selected={range === r} onClick={() => onRangeChange(r)}
                  className={`min-h-9 min-w-11 rounded-md px-2 tabular transition-colors ${range === r ? 'bg-ink font-semibold text-paper' : 'text-ink-2 hover:bg-paper-2'}`}>
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
              <Suspense fallback={<Block h={292} />}>
                <PriceForecastChart
                  // stale / insufficient: history only, no forecast drawn (F2)
                  series={showForecastMeta ? series : buildChartSeries(daily, [], today)}
                  lang={lang}
                />
              </Suspense>
              {range >= 180 && showForecastMeta && (
                <button onClick={() => onRangeChange(30)} className="tap text-sm font-semibold underline underline-offset-4">
                  <Trans>Enlarge the forecast ›</Trans>
                </button>
              )}
              {health !== 'ok' && <div className="mt-3"><HealthNotice kind={health} observations={summaryRow?.observations} /></div>}
              <ChartCaption facts={captionFacts(showForecastMeta ? series : buildChartSeries(daily, [], today), range)} />
              {showForecastMeta && head && (
                <div className="rule-t mt-3">
                  <ModelChip method={head.method} confidence={head.confidence} observations={head.observations}
                    generatedAt={head.generated_at} modelVersion={head.model_version} />
                </div>
              )}
            </>
          )}
        </Section>
      </div>

      <div className="grid content-start gap-3">
        {/* 3. VERDICT */}
        <Section title={<Trans>Advice</Trans>}>
          {sale.isPending ? <Block h={160} /> : sale.data ? <SaleWindowCard sale={sale.data} /> : <SaleWindowEmpty />}
        </Section>

        {sale.data?.better_market && markets.data && (
          <Section>
            <BetterMarketCard better={sale.data.better_market} markets={markets.data} commodityId={pair.commodityId} from={market} />
          </Section>
        )}

        <Section title={<Trans>Other mandis · {cropName(crop, lang)}</Trans>}>
          <OtherMarketsList commodityId={pair.commodityId} current={market} markets={markets.data ?? []} />
        </Section>

        <Section>
          <button className="tap w-full rounded-lg bg-ink px-4 font-semibold text-paper transition-all hover:-translate-y-0.5 hover:bg-sell-deep" onClick={() => navigate({ to: '/alerts' })}>
            <Trans>Send me an SMS when the price changes</Trans>
          </button>
        </Section>

        <Section>
          <AccuracyCard compact />
        </Section>
      </div>
    </div>
  );
}

function Delta({ now, before }: { now: number; before: number }) {
  const diff = now - before;
  const pct = (diff / before) * 100;
  if (Math.abs(diff) < 0.5) return <p className="text-sm"><Trans>— Same as the last price</Trans></p>;
  const abs = formatINR(Math.abs(diff));
  const p = formatPct(pct);
  // Ink + arrow, never red/green: colour is reserved for the verdict.
  return (
    <p className="tabular text-sm">
      {diff > 0 ? <Trans>▲ {abs} ({p}) since the last price</Trans> : <Trans>▼ {abs} ({p}) since the last price</Trans>}
    </p>
  );
}
