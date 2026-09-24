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
        <table className="w-full border-collapse">
          <thead className="sr-only">
            <tr><th><Trans>Mandi</Trans></th><th><Trans>Price</Trans></th><th><Trans>Change</Trans></th><th><Trans>7 days</Trans></th></tr>
          </thead>
          <tbody>
            {(markets.data ?? []).map((m) => {
              const row = latest.data?.find((r) => r.marketId === m.id);
              const f = summary.data?.find((s) => s.market_id === m.id && s.commodity_id === crop);
              const diff = row?.prev ? row.modal - row.prev.modal : null;
              return (
                <tr key={m.id} className="rule-b align-top">
                  <td className="py-3 pl-4">
                    <Link to="/c/$crop/m/$market" params={{ crop, market: m.id }} className="font-semibold underline-offset-4 hover:underline">{m.name}</Link>
                    <div className="text-xs text-ink-2">
                      {!f ? <Trans>No forecast</Trans>
                        : f.status === 'insufficient_data' ? <Trans>Not enough data for a forecast yet</Trans>
                        : f.predicted_price != null ? <Trans>Tomorrow likely {formatINR(f.predicted_price)}</Trans> : null}
                    </div>
                    {row && daysBetween(row.date, today) > 1 && (
                      <div className="text-xs font-semibold"><Trans>Price of {formatDay(row.date, lang)}</Trans></div>
                    )}
                  </td>
                  <td className="tabular py-3 text-right font-semibold">{row ? formatINR(row.modal) : '—'}</td>
                  <td className="tabular py-3 pl-3 text-right text-sm">
                    {diff == null ? '' : Math.abs(diff) < 0.5 ? '—' : `${diff > 0 ? '▲' : '▼'} ${formatPct((diff / row!.prev!.modal) * 100)}`}
                  </td>
                  <td className="py-3 pr-4 pl-3 text-ink">{row && <Sparkline daily={row.daily} />}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <p className="px-4 py-3 text-xs text-ink-2"><Trans>Prices in ₹ per quintal. Change is against the previous reported day.</Trans></p>
    </div>
  );
}
