import type { ReactNode } from 'react';
import { Trans } from '@lingui/react/macro';
import type { SaleWindow } from '../../api/schemas.ts';
import { formatINR, formatNumber } from '../../domain/format.ts';
import { VERDICT_BG, VERDICT_TEXT } from './verdict.ts';

function Signal({ label, value, sub, muted }: { label: ReactNode; value: ReactNode; sub?: ReactNode; muted?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-2">{label}</dt>
      <dd className={`font-semibold ${muted ? 'text-ink-2' : ''}`}>{value}</dd>
      {sub && <dd className="tabular text-xs text-ink-2">{sub}</dd>}
    </div>
  );
}

export function SaleWindowCard({ sale }: { sale: SaleWindow }) {
  const pressure = sale.supply_pressure === 'high' ? <Trans>High</Trans>
    : sale.supply_pressure === 'low' ? <Trans>Low</Trans>
    : sale.supply_pressure ? <Trans>Normal</Trans> : '—';
  const trend = sale.forecast_trend === 'up' ? <>▲ <Trans>Rising</Trans></>
    : sale.forecast_trend === 'down' ? <>▼ <Trans>Falling</Trans></>
    : sale.forecast_trend ? <>— <Trans>Steady</Trans></> : '—';

  return (
    <div id="verdict" className="scroll-mt-4">
      <p className={`text-xl font-semibold ${VERDICT_TEXT[sale.action]}`}>{sale.action_label}</p>
      <div aria-hidden className={`mt-2 mb-3 h-[3px] w-full ${VERDICT_BG[sale.action]}`} />
      {/* Rendered as-is, never parsed. Headlines can only appear in the en reason (by design). */}
      <p className="text-base">{sale.reason}</p>
      <dl className="mt-4 grid grid-cols-3 gap-3">
        <Signal
          label={<Trans>Arrivals</Trans>}
          value={pressure}
          muted={sale.arrivals_qty == null}
          sub={sale.arrivals_qty != null ? <Trans>{formatNumber(sale.arrivals_qty)} qtl</Trans> : <Trans>not reported</Trans>}
        />
        <Signal
          label={<Trans>Forecast</Trans>}
          value={trend}
          sub={sale.forecast_day1 != null ? formatINR(sale.forecast_day1) : undefined}
        />
        <Signal
          label={<Trans>Storage</Trans>}
          value={sale.storage_available ? <Trans>Available</Trans> : sale.storage_available === false ? <Trans>None nearby</Trans> : '—'}
          sub={sale.storage_available && sale.storage.length > 0 ? sale.storage[0].name : undefined}
        />
      </dl>
    </div>
  );
}

export function SaleWindowEmpty() {
  return (
    <div className="text-sm">
      <p className="font-semibold"><Trans>No advice for today</Trans></p>
      <p className="mt-1 text-ink-2">
        <Trans>This mandi has not reported a price for this crop in the last 15 days. Try a nearby mandi below.</Trans>
      </p>
    </div>
  );
}
