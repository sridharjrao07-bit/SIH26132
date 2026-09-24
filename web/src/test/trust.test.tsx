import { describe, expect, test } from 'vitest';
import { render, screen } from '@testing-library/react';
import { I18nProvider } from '@lingui/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { i18n } from '@lingui/core';
import type { ReactNode } from 'react';
import { AccuracyView } from '../features/trust/AccuracyCard.tsx';
import { HealthNotice } from '../features/trust/HealthNotice.tsx';
import { qk } from '../queries/index.ts';

function wrap(ui: ReactNode, accuracy?: unknown) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (accuracy) qc.setQueryData(qk.accuracy(), accuracy);
  return render(<QueryClientProvider client={qc}><I18nProvider i18n={i18n}>{ui}</I18nProvider></QueryClientProvider>);
}

describe('AccuracyCard: pending states first', () => {
  test('not_published (G6 not deployed): honest copy, no numbers at all', () => {
    const { container } = wrap(<AccuracyView report={{ status: 'not_published' }} />);
    expect(screen.getByText('अजून मोजलेली नाही')).toBeTruthy();
    expect(container.textContent).not.toMatch(/\d/);      // no invented thresholds or metrics
    expect(container.textContent).not.toMatch(/95/);
  });

  test('backfill_pending: thresholds come from the API, progress hidden until F3 lands', () => {
    const { container } = wrap(<AccuracyView report={{ status: 'backfill_pending', thresholds: { min_forecast_days: 10, min_backtest_days: 57 }, progress: null, metrics: null, updated_at: null }} />);
    expect(container.textContent).toContain('10');
    expect(container.textContent).toContain('57');
    expect(container.textContent).not.toContain('/57');   // no progress row without the field
  });

  test('backfill_pending with F3 progress shows the row from data', () => {
    const { container } = wrap(<AccuracyView report={{ status: 'backfill_pending', thresholds: null, progress: { max_pair_days: 23, required: 57 }, metrics: null, updated_at: null }} />);
    expect(container.textContent).toContain('23/57');
  });

  test('certified: "N in 10" is computed from interval_coverage, never hardcoded', () => {
    const { container } = wrap(<AccuracyView report={{ status: 'certified', thresholds: null, progress: null, metrics: { mae: 142, wmape: 0.081, interval_coverage: 0.909, nan_rate: 0 }, updated_at: null }} />);
    expect(container.textContent).toContain('10 पैकी 9');
    expect(container.textContent).toContain('₹142');
  });
});

describe('HealthNotice', () => {
  test('insufficient_data without G6: no numbers', () => {
    const { container } = wrap(<HealthNotice kind="insufficient_data" observations={7} />, { status: 'not_published' });
    expect(container.textContent).not.toMatch(/\d/);
  });
  test('insufficient_data with G6 thresholds: numbers + progress from data', () => {
    const { container } = wrap(<HealthNotice kind="insufficient_data" observations={7} />,
      { status: 'backfill_pending', thresholds: { min_forecast_days: 10, min_backtest_days: 57 }, progress: null, metrics: null, updated_at: null });
    expect(container.textContent).toContain('7/10');
  });
});
