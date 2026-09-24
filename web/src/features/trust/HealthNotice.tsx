import { Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { accuracyQuery } from '../../queries/index.ts';
import type { PairHealth } from '../../domain/pairHealth.ts';

/**
 * One specific, honest message per health state. Numbers come from the G6 thresholds only.
 * If G6 isn't deployed, the copy has no numbers rather than hardcoded ones.
 */
export function HealthNotice({ kind, observations }: { kind: Exclude<PairHealth, 'ok'>; observations?: number | null }) {
  const { data: acc } = useQuery(accuracyQuery());
  const need = acc && 'thresholds' in acc ? acc.thresholds?.min_forecast_days ?? null : null;

  let body;
  switch (kind) {
    case 'aging':
      body = <Trans>This forecast is more than a day old. New prices have not arrived from the mandi yet.</Trans>;
      break;
    case 'stale':
      body = <Trans>The forecast is out of date, so it is hidden. Waiting for new mandi data.</Trans>;
      break;
    case 'insufficient_data':
      body = need != null && observations != null
        ? <Trans>A forecast needs at least {need} days of prices. This mandi has {observations} so far.</Trans>
        : <Trans>There is not enough price history yet for an honest forecast.</Trans>;
      break;
    case 'no_prices':
      body = <Trans>No recent price for this crop at this mandi.</Trans>;
      break;
  }

  const progress = kind === 'insufficient_data' && need && observations != null ? Math.min(observations / need, 1) : null;

  return (
    <div role="status" className="rounded border border-rule px-3 py-3 text-sm">
      <p>{body}</p>
      {progress != null && (
        <div className="mt-2 flex items-center gap-2 text-xs text-ink-2">
          <div className="h-1.5 flex-1 bg-paper-2" aria-hidden>
            <div className="h-full bg-ink-2" style={{ width: `${progress * 100}%` }} />
          </div>
          <span className="tabular">{observations}/{need}</span>
        </div>
      )}
    </div>
  );
}
