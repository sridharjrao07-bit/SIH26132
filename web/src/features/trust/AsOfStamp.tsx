import { Trans } from '@lingui/react/macro';
import { usePrefs } from '../../stores/prefs.ts';
import { formatDay, formatTime } from '../../domain/format.ts';
import { daysBetween, istToday } from '../../domain/dates.ts';

/** Quiet when fresh, prominent when the price day is old (review point 2). */
export function AsOfStamp({
  priceDate,
  generatedAt,
  dark = false,
}: {
  priceDate: string;
  generatedAt?: string | null;
  dark?: boolean;
}) {
  const lang = usePrefs((s) => s.lang);
  const age = daysBetween(priceDate, istToday());
  const day = formatDay(priceDate, lang);
  const old = age >= 2;
  const baseClass = dark
    ? `text-xs ${old ? 'font-semibold text-yellow-300' : 'text-white/50'}`
    : `text-xs ${old ? 'font-semibold text-ink' : 'text-ink-2'}`;
  return (
    <p className={baseClass}>
      {old && <span aria-hidden>⚠ </span>}
      {old ? (
        <Trans>Price from {day} ({age} days old)</Trans>
      ) : (
        <Trans>Mandi price of {day}</Trans>
      )}
      {generatedAt && (
        <>
          {' · '}
          <Trans>forecast updated {formatTime(generatedAt, lang)}</Trans>
        </>
      )}
    </p>
  );
}
