import { Link } from '@tanstack/react-router';
import { Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { latestForCommodityQuery } from '../../queries/index.ts';
import type { Market } from '../../api/schemas.ts';
import { distanceKm } from '../../domain/geo.ts';
import { formatDay, formatINR } from '../../domain/format.ts';
import { daysBetween, istToday } from '../../domain/dates.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { Block } from '../../ui/Skeleton.tsx';

/**
 * Built from /prices/latest + market coordinates, NOT sale_window.nearby: the real API's
 * `nearby` is {market, modal_price, arrival_qty} with no id or distance, and the mock differs (G11).
 */
export function OtherMarketsList({ commodityId, current, markets }: { commodityId: string; current: Market | undefined; markets: Market[] }) {
  const lang = usePrefs((s) => s.lang);
  const { data, isPending } = useQuery(latestForCommodityQuery(commodityId));
  if (isPending) return <Block h={140} />;
  const rows = (data ?? [])
    .filter((r) => r.marketId !== current?.id)
    .map((r) => {
      const m = markets.find((x) => x.id === r.marketId);
      return { ...r, name: m?.name ?? r.marketName ?? '—', km: m && current ? Math.round(distanceKm(current, m)) : null };
    })
    .sort((a, b) => b.modal - a.modal);

  if (rows.length === 0) return <p className="text-sm text-ink-2"><Trans>No other mandi reported this crop in the last 7 days.</Trans></p>;

  const today = istToday();
  return (
    <ul>
      {rows.map((r) => (
        <li key={r.marketId} className="rule-b last:border-b-0">
          <Link to="/c/$crop/m/$market" params={{ crop: commodityId, market: r.marketId }} className="tap flex items-center gap-3 rounded-lg px-2 py-2 transition-colors hover:bg-paper-2">
            <span className="min-w-0 flex-1 truncate">{r.name}</span>
            {daysBetween(r.date, today) > 1 && <span className="text-xs text-ink-2">{formatDay(r.date, lang)}</span>}
            <span className="tabular w-20 text-right font-semibold">{formatINR(r.modal)}</span>
            <span className="tabular w-14 text-right text-sm text-ink-2">{r.km != null ? `${r.km} km` : ''}</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
