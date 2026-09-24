import { describe, expect, test, vi } from 'vitest';
import { render } from '@testing-library/react';
import { I18nProvider } from '@lingui/react';
import { i18n } from '@lingui/core';
import type { ReactElement, ReactNode } from 'react';
import { cloneElement } from 'react';
import { buildChartSeries } from '../domain/chartSeries.ts';
import { pairHealth } from '../domain/pairHealth.ts';
import type { DailyPoint } from '../domain/dailyRows.ts';
import type { ForecastRow } from '../api/schemas.ts';

// Give Recharts a real 360px box in jsdom so axis ticks actually render.
vi.mock('recharts', async (orig) => {
  const mod = await orig<typeof import('recharts')>();
  return { ...mod, ResponsiveContainer: ({ children }: { children: ReactElement }) => cloneElement(children, { width: 360, height: 220 } as never) };
});
const { PriceForecastChart, PointTooltip } = await import('../charts/PriceForecastChart.tsx');

const TODAY = '2026-09-24';
const daily: DailyPoint[] = Array.from({ length: 14 }, (_, i) => ({
  date: `2026-09-${String(10 + i).padStart(2, '0')}`, modal: 2400 + i * 10, min: 2300, max: 2600,
  arrivals: i === 3 ? null : 1200, source: 'agmarknet',
}));
const fc = (d: string, p: number): ForecastRow => ({
  market_id: 'm', commodity_id: 'c', forecast_date: d, predicted_price: p, lower_bound: p - 120, upper_bound: p + 120,
  confidence: 'medium', method: 'feature_ols', observations: 30, status: 'ok',
  generated_at: '2026-09-24T01:00:00Z', model_version: null, features_used: null,
});
const forecast = [fc('2026-09-25', 2550), fc('2026-09-26', 2570), fc('2026-09-27', 2590)];
const series = buildChartSeries(daily, forecast, TODAY);
const wrap = (ui: ReactNode) => render(<I18nProvider i18n={i18n}>{ui}</I18nProvider>);

describe('PriceForecastChart at 360px', () => {
  test('x ticks: Marathi month names with Latin digits; y ticks: ₹ en-IN', () => {
    const { container } = wrap(<PriceForecastChart series={series} lang="mr" />);
    const ticks = [...container.querySelectorAll('.recharts-cartesian-axis-tick-value')].map((n) => n.textContent ?? '');
    expect(ticks.length).toBeGreaterThan(3);
    const x = ticks.filter((s) => !s.startsWith('₹'));
    expect(x.some((s) => /[\u0900-\u097F]/.test(s))).toBe(true);   // Devanagari month
    expect(x.every((s) => !/[०-९]/.test(s))).toBe(true);           // never Devanagari digits
    expect(ticks.some((s) => /^₹\d{1,2},?\d{3}$/.test(s))).toBe(true);
  });

  test('arrivals strip has no visible y-axis', () => {
    const { container } = wrap(<PriceForecastChart series={series} lang="mr" />);
    const yAxes = container.querySelectorAll('.recharts-yAxis');
    expect(yAxes.length).toBe(1);                                   // only the price axis
  });
});

describe('Tooltip never pins on the bridge (F4)', () => {
  const lastActual = series.points.find((p) => p.kind === 'actual' && p.bridge != null)!;
  const firstForecast = series.points.find((p) => p.kind === 'forecast')!;

  test('last actual point carries the bridge but its tooltip shows only actual data', () => {
    expect(lastActual.bridge).not.toBeNull();
    const { container } = wrap(<PointTooltip active payload={[{ payload: lastActual } as never]} lang="mr" />);
    expect(container.textContent).toContain('₹2,530');
    expect(container.textContent).not.toContain('संभाव्य');         // no band
    expect(container.textContent).not.toContain('अंदाज');            // not labelled forecast
  });

  test('forecast point tooltip shows predicted + band', () => {
    const { container } = wrap(<PointTooltip active payload={[{ payload: firstForecast } as never]} lang="mr" />);
    expect(container.textContent).toContain('अंदाज');
    expect(container.textContent).toContain('₹2,550');
    expect(container.textContent).toContain('₹2,430–₹2,670');
  });

  test('arrivals null reads "not reported", never 0 (G2)', () => {
    const p = series.points.find((q) => q.date === '2026-09-13')!;
    const { container } = wrap(<PointTooltip active payload={[{ payload: p } as never]} lang="mr" />);
    expect(container.textContent).toContain('नोंद नाही');
  });
});

describe('pairHealth', () => {
  const now = Date.parse('2026-09-24T12:00:00Z');
  test.each([
    [{ hasPrices: false, forecastRun: forecast, summaryStatus: 'ok' }, 'no_prices'],
    [{ hasPrices: true, forecastRun: forecast, summaryStatus: 'ok' }, 'ok'],
    [{ hasPrices: true, forecastRun: forecast.map((f) => ({ ...f, generated_at: '2026-09-23T06:00:00Z' })), summaryStatus: 'ok' }, 'aging'],
    [{ hasPrices: true, forecastRun: [], summaryStatus: 'insufficient_data' }, 'insufficient_data'],
    [{ hasPrices: true, forecastRun: [], summaryStatus: null }, 'stale'],
    [{ hasPrices: true, forecastRun: forecast.map((f) => ({ ...f, generated_at: null })), summaryStatus: 'ok' }, 'ok'],
  ] as const)('%o → %s', (input, expected) => {
    expect(pairHealth({ ...input, forecastRun: [...input.forecastRun], now })).toBe(expected);
  });
});
