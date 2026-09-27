import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Trans } from '@lingui/react/macro';
import { commoditiesQuery, latestForCommodityQuery, marketsQuery, summaryQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { formatDay, formatINR } from '../../domain/format.ts';
import { daysBetween, istToday } from '../../domain/dates.ts';
import { Sparkline } from '../../charts/Sparkline.tsx';
import { Block } from '../../ui/Skeleton.tsx';
import { TrendIndicator } from '../../ui/TrendIndicator.tsx';
import { BoardInsights } from './BoardInsights.tsx';

/** Board = /forecasts/summary + /prices/latest. No per-pair history fan-out (G3). */
export function BoardPage() {
  const lang = usePrefs((s) => s.lang);
  const district = usePrefs((s) => s.district);
  const pinned = usePrefs((s) => s.pinnedPairs[0]);
  const commodities = useQuery(commoditiesQuery());
  const markets = useQuery(marketsQuery(district));
  const summary = useQuery(summaryQuery());
  const search = useSearch({ from: '/bhav' });
  const navigate = useNavigate({ from: '/bhav' });
  const crop = search.crop ?? pinned?.commodityId ?? commodities.data?.[0]?.id;
  const latest = useQuery({ ...latestForCommodityQuery(crop ?? ''), enabled: !!crop });
  const today = istToday();
  const rows = latest.data ?? [];
  const pricedRows = rows.filter((row) => row.prev);
  const average = rows.length ? rows.reduce((total, row) => total + row.modal, 0) / rows.length : null;
  const best = rows.length ? rows.reduce((top, row) => row.modal > top.modal ? row : top) : null;
  const averageChange = pricedRows.length
    ? pricedRows.reduce((total, row) => total + ((row.modal - (row.prev?.modal ?? row.modal)) / (row.prev?.modal ?? row.modal)) * 100, 0) / pricedRows.length
    : null;
  const totalArrivals = rows.reduce((total, row) => total + (row.arrivals ?? 0), 0);
  const cropLabel = cropName(commodities.data?.find((item) => item.id === crop), lang);

  return (
    <div className="grid gap-3">
      <div className="flex flex-col gap-4 border-b border-rule pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">Operational overview</p>
          <h1 className="mt-1 text-2xl font-bold"><Trans>Mandi prices · {district}</Trans></h1>
          <p className="mt-1 text-sm text-ink-2">Compare price movement, arrivals and forecast signals across the district.</p>
        </div>
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Commodity">
          {(commodities.data ?? []).map((c) => (
            <button key={c.id} role="tab" aria-selected={c.id === crop}
              onClick={() => navigate({ search: { crop: c.id }, replace: true })}
              className={`diagonal-small min-h-9 border px-3 text-sm transition-colors ${c.id === crop ? 'border-signal bg-signal/15 font-semibold text-signal' : 'border-rule bg-card text-ink-2 hover:border-signal hover:text-ink'}`}>
              {cropName(c, lang)}
            </button>
          ))}
        </div>
      </div>

      {latest.isPending || !crop ? (
        <div className="space-y-3 p-4">{[0, 1, 2, 3].map((i) => <Block key={i} h={52} />)}</div>
      ) : (
        <>
          <section className="grid grid-cols-2 gap-3 lg:grid-cols-4" aria-label="Market highlights">
            <article className="glass-panel diagonal-panel metric-card p-4">
              <p className="eyebrow">Average spot</p>
              <p className="mt-3 font-mono text-2xl font-semibold">{average == null ? '—' : formatINR(average)}</p>
              <p className="mt-1 text-xs text-ink-2">{cropLabel} · district average</p>
            </article>
            <article className="glass-panel diagonal-panel metric-card p-4">
              <p className="eyebrow">Market movement</p>
              <div className="mt-3"><TrendIndicator value={averageChange} /></div>
              <p className="mt-2 text-xs text-ink-2">average change vs previous report</p>
            </article>
            <article className="glass-panel diagonal-panel metric-card p-4">
              <p className="eyebrow">Best available</p>
              <p className="mt-3 font-mono text-2xl font-semibold text-gain">{best ? formatINR(best.modal) : '—'}</p>
              <p className="mt-1 truncate text-xs text-ink-2">{best ? markets.data?.find((market) => market.id === best.marketId)?.name ?? best.marketName : 'No report'}</p>
            </article>
            <article className="glass-panel diagonal-panel metric-card p-4">
              <p className="eyebrow">Reported arrivals</p>
              <p className="mt-3 font-mono text-2xl font-semibold text-signal">{new Intl.NumberFormat('en-IN', { notation: 'compact' }).format(totalArrivals)}</p>
              <p className="mt-1 text-xs text-ink-2">quintals across {rows.length} mandis</p>
            </article>
          </section>

          <BoardInsights rows={rows} markets={markets.data ?? []} commodity={cropLabel} />

          <section className="glass-panel diagonal-panel overflow-hidden">
            <div className="flex items-center justify-between border-b border-rule px-4 py-3">
              <div><p className="eyebrow">Price board</p><h2 className="mt-1 text-sm font-semibold">All reporting mandis</h2></div>
              <span className="font-mono text-xs text-ink-2">{rows.length} live</span>
            </div>
            <div className="grid gap-px bg-rule sm:grid-cols-2 xl:grid-cols-3">
            {(markets.data ?? []).map((m) => {
              const row = latest.data?.find((r) => r.marketId === m.id);
              const f = summary.data?.find((s) => s.market_id === m.id && s.commodity_id === crop);
              const diff = row?.prev ? row.modal - row.prev.modal : null;
              const pct = row?.prev ? (diff ?? 0) / row.prev.modal * 100 : null;
              return (
                <Link key={m.id} to="/c/$crop/m/$market" params={{ crop, market: m.id }} className="group bg-card p-4 transition-colors hover:bg-paper-2">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <h3 className="truncate font-semibold group-hover:text-signal">{m.name}</h3>
                      <div className="mt-1 text-xs text-ink-2">
                      {!f ? <Trans>No forecast</Trans>
                        : f.status === 'insufficient_data' ? <Trans>Not enough data for a forecast yet</Trans>
                        : f.predicted_price != null ? <Trans>Tomorrow likely {formatINR(f.predicted_price)}</Trans> : null}
                      </div>
                    </div>
                    {row && <Sparkline daily={row.daily} w={88} h={28} />}
                  </div>
                  <div className="mt-4 flex items-end justify-between gap-3">
                    <div>
                      <p className="tabular font-mono text-xl font-semibold">{row ? formatINR(row.modal) : '—'}</p>
                    {row && daysBetween(row.date, today) > 1 && (
                        <p className="text-xs font-semibold text-warn"><Trans>Price of {formatDay(row.date, lang)}</Trans></p>
                    )}
                    </div>
                    <TrendIndicator value={pct} compact />
                  </div>
                </Link>
              );
            })}
            </div>
          </section>
        </>
      )}
      <p className="px-4 py-3 text-xs text-ink-2"><Trans>Prices in ₹ per quintal. Change is against the previous reported day.</Trans></p>
    </div>
  );
}
