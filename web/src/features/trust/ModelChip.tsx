import { useRef } from 'react';
import { Link } from '@tanstack/react-router';
import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { METHODS } from './methods.ts';
import { accuracyQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { formatDateTime } from '../../domain/format.ts';
import { AccuracyStatusLine } from './AccuracyCard.tsx';

interface Props {
  method: string;
  confidence: string | null;
  observations: number | null;
  generatedAt: string | null;
  modelVersion?: string | null;   // G5: null until the backend exposes it
}

/**
 * G4: every forecast carries the model that ACTUALLY produced it. Designed for the pending
 * state first: model_version null (G5) and accuracy unpublished (G6) are the demo states.
 */
export function ModelChip({ method, confidence, observations, generatedAt, modelVersion = null }: Props) {
  const { t, i18n } = useLingui();
  const lang = usePrefs((s) => s.lang);
  const ref = useRef<HTMLDialogElement>(null);
  const { data: acc } = useQuery(accuracyQuery());
  const m = METHODS[method];
  const label = m ? i18n._(m.label) : method;
  const conf = confidence === 'high' ? t`high confidence` : confidence === 'medium' ? t`medium confidence`
    // 'low' is dormant: the engine never emits it (F5). Kept for schema completeness.
    : confidence === 'low' ? t`low confidence` : null;

  return (
    <>
      <button
        onClick={() => ref.current?.showModal()}
        className="tap flex w-full items-center justify-between gap-3 text-left text-xs text-ink-2"
        aria-haspopup="dialog"
      >
        <span>
          <Trans>Model: {label}</Trans>
          {observations != null && <> · <Trans>{observations} days of data</Trans></>}
          {conf && <> · {conf}</>}
        </span>
        <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-full border border-ink-2 text-[13px] font-semibold">i</span>
      </button>

      <dialog
        ref={ref}
        className="m-0 mt-auto w-full max-w-none rounded-t bg-paper p-0 text-ink backdrop:bg-ink/40 sm:m-auto sm:max-w-md sm:rounded"
        onClick={(e) => { if (e.target === ref.current) ref.current?.close(); }}
      >
        <div className="px-4 pt-4 pb-6">
          <div className="mb-3 flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold"><Trans>Which model made this forecast?</Trans></h2>
            <button onClick={() => ref.current?.close()} className="tap -mt-3 -mr-2 px-3 text-lg" aria-label={t`Close`}>×</button>
          </div>
          <p className="font-semibold">{label}</p>
          <p className="mt-1 text-sm text-ink-2">{m ? i18n._(m.about) : t`Model details are not available.`}</p>

          <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-ink-2"><Trans>Price history used</Trans></dt>
            <dd className="tabular">{observations != null ? <Trans>{observations} days</Trans> : '—'}</dd>
            <dt className="text-ink-2"><Trans>Confidence</Trans></dt>
            <dd>{conf ?? '—'}</dd>
            <dt className="text-ink-2"><Trans>Generated</Trans></dt>
            <dd className="tabular">{generatedAt ? formatDateTime(generatedAt, lang) : '—'}</dd>
            <dt className="text-ink-2"><Trans>Model version</Trans></dt>
            <dd>{modelVersion ?? <span className="text-ink-2"><Trans>Not published yet</Trans></span>}</dd>
          </dl>

          <div className="rule-t mt-4 pt-3 text-sm">
            <AccuracyStatusLine report={acc} />
            <Link to="/forecasts/about" onClick={() => ref.current?.close()} className="tap mt-1 inline-flex items-center font-semibold underline underline-offset-4">
              <Trans>How forecasts are checked</Trans>
            </Link>
          </div>
        </div>
      </dialog>
    </>
  );
}
