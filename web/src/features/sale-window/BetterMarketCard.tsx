import { Link } from '@tanstack/react-router';
import { Trans } from '@lingui/react/macro';
import type { Market, SaleWindow } from '../../api/schemas.ts';
import { formatINR } from '../../domain/format.ts';
import { distanceKm } from '../../domain/geo.ts';

/**
 * In mr/hi this card is the ONLY place a better mandi is mentioned: the localised reason
 * is rebuilt from templates and drops the English better-market sentence.
 */
export function BetterMarketCard({ better, markets, commodityId, from }: {
  better: NonNullable<SaleWindow['better_market']>; markets: Market[]; commodityId: string; from: Market | undefined;
}) {
  const target = markets.find((m) => m.name === better.market);
  const km = target && from ? Math.round(distanceKm(from, target)) : null;
  const body = (
    <>
      <p className="text-xs text-ink-2"><Trans>Better price nearby</Trans></p>
      <p className="font-semibold">{better.market ?? '—'}</p>
      <p className="tabular text-sm">
        <span className="font-semibold">{formatINR(better.modal_price)}</span>
        {' '}(+{formatINR(better.premium_rs)})
        {km != null && <span className="text-ink-2"> · {km} km</span>}
      </p>
    </>
  );
  return target ? (
    <Link to="/c/$crop/m/$market" params={{ crop: commodityId, market: target.id }} className="tap flex items-center justify-between gap-3">
      <div>{body}</div>
      <span aria-hidden className="text-ink-2">›</span>
    </Link>
  ) : <div>{body}</div>;
}
