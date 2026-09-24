import type { ReactNode } from 'react';
import { Trans } from '@lingui/react/macro';
import type { SaleWindow } from '../../api/schemas.ts';
import { formatINR, formatNumber } from '../../domain/format.ts';
import { VERDICT_BG } from './verdict.ts';

function Signal({ label, value, sub, muted }: { label: ReactNode; value: ReactNode; sub?: ReactNode; muted?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-ink-2">{label}</dt>
      <dd className={`font-semibold ${muted ? 'text-ink-2' : ''}`}>{value}</dd>
      {sub && <dd className="tabular text-xs text-ink-2">{sub}</dd>}
    </div>
  );
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

export function SaleWindowCard({ sale }: { sale: SaleWindow }) {
  const pressure = sale.supply_pressure === 'high' ? <Trans>High</Trans>
    : sale.supply_pressure === 'low' ? <Trans>Low</Trans>
    : sale.supply_pressure ? <Trans>Normal</Trans> : '—';
  const trend = sale.forecast_trend === 'up' ? <>▲ <Trans>Rising</Trans></>
    : sale.forecast_trend === 'down' ? <>▼ <Trans>Falling</Trans></>
    : sale.forecast_trend ? <>— <Trans>Steady</Trans></> : '—';

  return (
    <div id="verdict" className="scroll-mt-4" aria-live="polite">
      <div className="relative overflow-hidden mb-4 rounded-sm">
        <div aria-hidden className={`absolute inset-0 ${VERDICT_BG[sale.action]} origin-left animate-band`} />
        <div className="relative px-4 py-3 flex items-center gap-3 text-white animate-rise">
          <VerdictIcon action={sale.action} />
          <p className="text-xl lg:text-2xl font-bold tracking-wide uppercase">{sale.action_label}</p>
        </div>
      </div>
      
      {/* Rendered as-is, never parsed. Headlines can only appear in the en reason (by design). */}
      <p className="text-base text-ink animate-rise">{sale.reason}</p>
      
      <dl className="mt-6 grid grid-cols-3 gap-3 rule-t pt-4 animate-rise">
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
