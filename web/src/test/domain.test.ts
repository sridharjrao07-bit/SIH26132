import { test } from 'vitest';
import assert from 'node:assert/strict';
import { toDailyRows } from '../domain/dailyRows.ts';
import { selectLatestRun } from '../domain/forecastRun.ts';
import { buildChartSeries } from '../domain/chartSeries.ts';
import { normalizeApiError } from '../api/errors.ts';
import type { PriceRow, ForecastRow } from '../api/schemas.ts';

const P = (d: string, modal: number, o: Partial<PriceRow> = {}): PriceRow => ({
  market_id: 'm', commodity_id: 'c', arrival_date: d, min_price: modal - 100, max_price: modal + 100,
  modal_price: modal, arrival_qty: 300, variety: 'General', grade: 'General', source: 'data_gov_in',
  market_name: null, commodity_name_en: null, commodity_name_mr: null, commodity_name_hi: null, ...o,
});
const F = (d: string, pr: number, gen: string, o: Partial<ForecastRow> = {}): ForecastRow => ({
  market_id: 'm', commodity_id: 'c', forecast_date: d, predicted_price: pr, lower_bound: pr - 50,
  upper_bound: pr + 50, confidence: 'medium', method: 'blend', observations: 42, status: 'ok',
  generated_at: gen, model_version: null, features_used: null, ...o,
});

test('G1: one row per day, source precedence then General variety, ascending', () => {
  const rows = [ // newest-first like the API
    P('2026-09-23', 2000, { source: 'agmarknet' }),
    P('2026-09-23', 2100, { source: 'data_gov_in', variety: 'Red' }),
    P('2026-09-23', 2150, { source: 'data_gov_in' }),
    P('2026-09-22', 1900, { source: 'csv' }),
  ];
  const d = toDailyRows(rows);
  assert.deepEqual(d.map((x) => [x.date, x.modal]), [['2026-09-22', 1900], ['2026-09-23', 2150]]);
});

test('G2: null arrivals stay null', () => {
  assert.equal(toDailyRows([P('2026-09-23', 2000, { arrival_qty: null })])[0].arrivals, null);
});

test('mixed runs: only the newest run survives', () => {
  const rows = [
    F('2026-09-24', 1990, '2026-09-23T00:30:00Z'), // yesterday's run, today's date
    F('2026-09-25', 2010, '2026-09-24T00:30:00Z'),
    F('2026-09-26', 2020, '2026-09-24T00:30:00Z'),
  ];
  assert.deepEqual(selectLatestRun(rows).map((r) => r.forecast_date), ['2026-09-25', '2026-09-26']);
});

test('fresh data: cone starts at last actual, no gap, horizon derived', () => {
  const daily = toDailyRows([P('2026-09-23', 2000), P('2026-09-22', 1900)]);
  const s = buildChartSeries(daily, [F('2026-09-25', 2050, 'g'), F('2026-09-26', 2080, 'g')], '2026-09-24');
  assert.equal(s.hasGap, false);
  assert.equal(s.horizonDays, 2);
  const lastActual = s.points.find((p) => p.date === '2026-09-23')!;
  assert.deepEqual(lastActual.band, [2000, 2000]);
  assert.equal(lastActual.kind, 'actual');
  assert.equal(s.points.at(-2)!.bridge, 2050);
  assert.ok(Math.abs(s.changePct! - 5.263) < 0.01);
  assert.ok(s.yDomain![0] > 0, 'non-zero baseline');
});

test('stale data (outage): gap flagged, no cone across missing days', () => {
  const daily = toDailyRows([P('2026-09-20', 2000)]);
  const s = buildChartSeries(daily, [F('2026-09-25', 2050, 'g')], '2026-09-24');
  assert.equal(s.missingDays, 3);
  assert.equal(s.hasGap, true);
  assert.equal(s.points[0].band, null);
  assert.equal(s.points[0].bridge, 2000);
});

test('overlap: actual wins over a forecast for the same day', () => {
  const daily = toDailyRows([P('2026-09-24', 2000)]);
  const s = buildChartSeries(daily, [F('2026-09-24', 1950, 'g'), F('2026-09-25', 2050, 'g')], '2026-09-24');
  assert.deepEqual(s.points.map((p) => [p.date, p.kind]), [['2026-09-24', 'actual'], ['2026-09-25', 'forecast']]);
});

test('G8: detail as string and as array', () => {
  const a = normalizeApiError(404, { detail: 'no recent prices for this commodity' });
  assert.equal(a.kind, 'not_found'); assert.equal(a.message, 'no recent prices for this commodity');
  const b = normalizeApiError(422, { detail: [{ loc: ['query', 'market_id'], msg: 'Field required' }] });
  assert.equal(b.kind, 'validation'); assert.deepEqual(b.fields, { market_id: 'Field required' });
  assert.equal(normalizeApiError(503, null).retryable, true);
});
