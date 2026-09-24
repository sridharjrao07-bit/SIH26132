import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Trans } from '@lingui/react/macro';
import { commoditiesQuery, latestForCommodityQuery, marketsQuery, summaryQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { formatDay, formatINR, formatPct } from '../../domain/format.ts';
import { daysBetween, istToday } from '../../domain/dates.ts';
import { Sparkline } from '../../charts/Sparkline.tsx';
import { Block } from '../../ui/Skeleton.tsx';

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

  return (
    <div>
      <div className="rule-b px-4 pt-4 pb-3">
        <h1 className="text-lg font-semibold"><Trans>Mandi prices · {district}</Trans></h1>
        <div className="mt-3 flex flex-wrap gap-2" role="tablist">
          {(commodities.data ?? []).map((c) => (
            <button key={c.id} role="tab" aria-selected={c.id === crop}
              onClick={() => navigate({ search: { crop: c.id }, replace: true })}
              className={`tap rounded border px-3 ${c.id === crop ? 'border-ink bg-ink text-paper font-semibold' : 'border-rule'}`}>
              {cropName(c, lang)}
            </button>
          ))}
        </div>
      </div>

      {latest.isPending || !crop ? (
        <div className="space-y-3 p-4">{[0, 1, 2, 3].map((i) => <Block key={i} h={52} />)}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead className="bg-paper-2 border-b border-rule">
              <tr>
                <th className="py-2 pl-4 font-semibold text-ink-2"><Trans>Mandi</Trans></th>
                <th className="py-2 pl-3 font-semibold text-ink-2 text-right"><Trans>Price</Trans></th>
                <th className="py-2 pl-3 font-semibold text-ink-2 text-right"><Trans>Change</Trans></th>
                <th className="py-2 pr-4 pl-3 font-semibold text-ink-2"><Trans>7 days</Trans></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {(markets.data ?? []).map((m) => {
                const row = latest.data?.find((r) => r.marketId === m.id);
                const f = summary.data?.find((s) => s.market_id === m.id && s.commodity_id === crop);
                const diff = row?.prev ? row.modal - row.prev.modal : null;
                const isNearest = m.id === pinned?.marketId;
                return (
                  <tr key={m.id} className={`align-top hover:bg-paper-2 transition-colors ${isNearest ? 'bg-paper-2' : ''}`}>
                    <td className="py-3 pl-4">
                      <div className="flex items-center gap-2">
                        <Link to="/c/$crop/m/$market" params={{ crop, market: m.id }} className="font-semibold text-base underline-offset-4 hover:underline text-ink">{m.name}</Link>
                        {isNearest && <span className="text-[10px] uppercase font-bold text-ink-2 px-1 border border-rule rounded"><Trans>Primary</Trans></span>}
                      </div>
                      <div className="text-xs text-ink-2 mt-1">
                        {!f ? <Trans>No forecast</Trans>
                          : f.status === 'insufficient_data' ? <Trans>Not enough data for a forecast yet</Trans>
                          : f.predicted_price != null ? <Trans>Tomorrow likely {formatINR(f.predicted_price)}</Trans> : null}
                      </div>
                      {row && daysBetween(row.date, today) > 1 && (
                        <div className="text-xs font-semibold mt-1"><Trans>Price of {formatDay(row.date, lang)}</Trans></div>
                      )}
                    </td>
                    <td className="tabular py-3 pl-3 text-right font-medium text-base">{row ? formatINR(row.modal) : '—'}</td>
                    <td className="tabular py-3 pl-3 text-right">
                      {diff == null ? '' : Math.abs(diff) < 0.5 ? '—' : (
                        <span className={diff > 0 ? 'text-sell font-semibold' : 'text-wait font-semibold'}>
                          {diff > 0 ? '▲' : '▼'} {formatPct((Math.abs(diff) / row!.prev!.modal) * 100)}
                        </span>
                      )}
                    </td>
                    <td className="py-3 pr-4 pl-3 text-ink w-24">
                      {row && <Sparkline daily={row.daily} />}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="px-4 py-3 text-xs text-ink-2"><Trans>Prices in ₹ per quintal. Change is against the previous reported day.</Trans></p>
    </div>
  );
}
