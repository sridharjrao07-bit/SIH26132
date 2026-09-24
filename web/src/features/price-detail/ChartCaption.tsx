import { Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import type { CaptionFacts } from '../../domain/caption.ts';
import { formatINR, formatPct } from '../../domain/format.ts';
import { accuracyQuery } from '../../queries/index.ts';

/**
 * The takeaway sentence under the chart: screen-reader text, screenshot context, and the
 * summary for anyone who doesn't read charts. Never says "95%": coverage is unverified (G6).
 */
export function ChartCaption({ facts }: { facts: CaptionFacts }) {
  const { data: acc } = useQuery(accuracyQuery());
  const { days, changePct, direction, range, horizonDays } = facts;
  const pct = changePct != null ? formatPct(changePct) : '';
  const lo = range ? formatINR(range.lower) : '';
  const hi = range ? formatINR(range.upper) : '';
  const cov = acc && 'metrics' in acc ? acc.metrics?.interval_coverage ?? null : null;
  const inTen = cov != null ? Math.round(cov * 10) : null;

  return (
    <p className="mt-3 text-sm">
      {direction === 'up' && <Trans>Price rose {pct} in {days} days.</Trans>}
      {direction === 'down' && <Trans>Price fell {pct} in {days} days.</Trans>}
      {direction === 'flat' && <Trans>Price was steady over {days} days.</Trans>}
      {range && horizonDays > 0 && (
        <> <Trans>Likely range for the next {horizonDays} days: {lo}–{hi} (model’s estimate).</Trans></>
      )}
      {range && inTen != null && (
        <> <Trans>In past tests, the real price stayed inside this range {inTen} times out of 10.</Trans></>
      )}
    </p>
  );
}
