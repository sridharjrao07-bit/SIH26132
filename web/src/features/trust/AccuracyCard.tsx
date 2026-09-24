import { Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { accuracyQuery } from '../../queries/index.ts';
import type { AccuracyReport } from '../../api/endpoints/accuracy.ts';
import { formatINR, formatPct } from '../../domain/format.ts';
import { Block } from '../../ui/Skeleton.tsx';

/**
 * G6 accuracy card. Built pending-first: `not_published` (endpoint not deployed) and
 * `backfill_pending` are the states that will demo. "Pending is intended behaviour, not a
 * missing feature." No number on this card is ever a frontend constant.
 */
export function AccuracyCard({ compact = false }: { compact?: boolean }) {
  const { data, isPending, isError } = useQuery(accuracyQuery());
  if (isPending) return <Block h={compact ? 64 : 140} />;
  if (isError || !data) return null;
  return <AccuracyView report={data} compact={compact} />;
}

export function AccuracyView({ report, compact }: { report: AccuracyReport; compact?: boolean }) {
  const heading = <h2 className="text-sm font-semibold text-ink-2"><Trans>Forecast accuracy</Trans></h2>;

  if (report.status === 'not_published' || report.status === 'backfill_pending') {
    const t = 'thresholds' in report ? report.thresholds : null;
    const progress = 'progress' in report ? report.progress : null;
    return (
      <div className="space-y-2">
        {heading}
        <p className="text-base font-semibold"><Trans>Not measured yet</Trans></p>
        <p className="text-sm">
          <Trans>We are still collecting mandi history. Accuracy will be published only after the forecasts have been tested against real past prices.</Trans>
        </p>
        {!compact && (
          <p className="text-sm text-ink-2">
            <Trans>Until then, every forecast is shown with its likely range and the name of the model that made it, never as a single certain number.</Trans>
          </p>
        )}
        {!compact && t?.min_forecast_days != null && t?.min_backtest_days != null && (
          <p className="text-sm text-ink-2">
            <Trans>A mandi needs {t.min_forecast_days} days of prices before we forecast, and {t.min_backtest_days} days before accuracy can be tested.</Trans>
          </p>
        )}
        {/* F3: shown only once the backend exposes progress. Never estimated on the client. */}
        {progress && (
          <div className="flex items-center gap-2 pt-1 text-xs text-ink-2">
            <span><Trans>Verified history</Trans></span>
            <div className="h-1.5 flex-1 bg-paper-2" aria-hidden>
              <div className="h-full bg-ink-2" style={{ width: `${Math.min(progress.max_pair_days / progress.required, 1) * 100}%` }} />
            </div>
            <span className="tabular">{progress.max_pair_days}/{progress.required}</span>
          </div>
        )}
      </div>
    );
  }

  if ((report.status === 'provisional' || report.status === 'certified') && 'metrics' in report && report.metrics) {
    const m = report.metrics;
    const inTen = m.interval_coverage != null ? Math.round(m.interval_coverage * 10) : null;
    return (
      <div className="space-y-3">
        {heading}
        {report.status === 'provisional' && <p className="text-xs text-ink-2"><Trans>Provisional: tested on a few mandis only.</Trans></p>}
        <dl className="grid grid-cols-2 gap-3">
          {m.mae != null && (
            <div><dt className="text-xs text-ink-2"><Trans>Typical error</Trans></dt><dd className="tabular text-lg font-semibold">{formatINR(m.mae)}</dd></div>
          )}
          {m.wmape != null && (
            <div><dt className="text-xs text-ink-2"><Trans>Average % error</Trans></dt><dd className="tabular text-lg font-semibold">{formatPct(m.wmape * 100)}</dd></div>
          )}
        </dl>
        {inTen != null && !compact && (
          <p className="text-sm"><Trans>In past tests, the real price stayed inside the likely range {inTen} times out of 10.</Trans></p>
        )}
      </div>
    );
  }

  // Unknown future status: say nothing rather than guess
  return null;
}

/** One-line version for the model sheet. */
export function AccuracyStatusLine({ report }: { report: AccuracyReport | undefined }) {
  if (!report) return null;
  if (report.status === 'not_published' || report.status === 'backfill_pending') {
    return <p><Trans>Accuracy: not measured yet. We are collecting history first.</Trans></p>;
  }
  if ('metrics' in report && report.metrics?.interval_coverage != null) {
    const inTen = Math.round(report.metrics.interval_coverage * 10);
    return <p><Trans>In past tests, the real price stayed inside the likely range {inTen} times out of 10.</Trans></p>;
  }
  return null;
}
