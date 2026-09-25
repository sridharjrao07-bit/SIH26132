import { test } from 'vitest';
import assert from 'node:assert/strict';
import { toDailyRows } from '../domain/dailyRows.ts';
import { selectLatestRun } from '../domain/forecastRun.ts';
import { buildChartSeries } from '../domain/chartSeries.ts';
import { pairHealth } from '../domain/pairHealth.ts';
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

// ── changePct must not blow up when the first price is 0 (or missing) ─────────
test('edge: changePct is null (not Infinity/NaN) when first modal is 0', () => {
  const daily = toDailyRows([P('2026-09-22', 0), P('2026-09-23', 2000)]);
  const s = buildChartSeries(daily, [], '2026-09-24');
  assert.ok(s.changePct === null || Number.isFinite(s.changePct),
    `changePct should be null or finite, got ${s.changePct}`);
});

// ── selectLatestRun must ignore a malformed timestamp, not poison the run ─────
test('edge: one malformed generated_at does not wipe the whole selection', () => {
  const rows = [
    F('2026-09-25', 2010, 'not-a-date'),                 // malformed
    F('2026-09-26', 2020, '2026-09-24T00:30:00Z'),
    F('2026-09-27', 2030, '2026-09-24T00:31:00Z'),
  ];
  const run = selectLatestRun(rows);
  assert.deepEqual(run.map((r) => r.forecast_date), ['2026-09-26', '2026-09-27'],
    'malformed row should be dropped, valid newest run kept');
});

// ── empty inputs must not crash ───────────────────────────────────────────────
test('edge: buildChartSeries with no prices and no forecast', () => {
  const s = buildChartSeries([], [], '2026-09-24');
  assert.deepEqual(s.points, []);
  assert.equal(s.yDomain, null);
  assert.equal(s.changePct, null);
  assert.equal(s.horizonDays, 0);
  assert.equal(s.forecastRange, null);
});

// ── forecast-only (no history yet) still yields a chart + domain ──────────────
test('edge: forecast-only series draws the band and a y-domain', () => {
  const s = buildChartSeries([], [F('2026-09-25', 2050, 'g'), F('2026-09-26', 2080, 'g')], '2026-09-24');
  assert.equal(s.horizonDays, 2);
  assert.ok(s.yDomain, 'yDomain computed from the band');
  assert.equal(s.lastActualDate, null);
  assert.equal(s.hasGap, false);
});

// ── unknown source ranks last; General variety preferred on ties ──────────────
test('edge: unknown source is ranked last, General preferred among equal ranks', () => {
  const rows = [
    P('2026-09-23', 9999, { source: 'mystery_source' }),
    P('2026-09-23', 2100, { source: 'data_gov_in', variety: 'Red' }),
    P('2026-09-23', 2150, { source: 'data_gov_in', variety: 'General' }),
  ];
  const d = toDailyRows(rows);
  assert.equal(d.length, 1);
  assert.equal(d[0].modal, 2150); // best rank + General
});

// ── pairHealth: every branch ──────────────────────────────────────────────────
test('edge: pairHealth classifies all five states', () => {
  const now = Date.parse('2026-09-24T12:00:00Z');
  assert.equal(pairHealth({ hasPrices: false, forecastRun: [], summaryStatus: null, now }), 'no_prices');
  assert.equal(pairHealth({ hasPrices: true, forecastRun: [F('2026-09-25', 1, '2026-09-24T11:00:00Z')], summaryStatus: 'ok', now }), 'ok');
  assert.equal(pairHealth({ hasPrices: true, forecastRun: [F('2026-09-25', 1, '2026-09-20T11:00:00Z')], summaryStatus: 'ok', now }), 'aging');
  assert.equal(pairHealth({ hasPrices: true, forecastRun: [], summaryStatus: 'insufficient_data', now }), 'insufficient_data');
  assert.equal(pairHealth({ hasPrices: true, forecastRun: [], summaryStatus: null, now }), 'stale');
  // forecast run present but generated_at missing -> not aging
  assert.equal(pairHealth({ hasPrices: true, forecastRun: [F('2026-09-25', 1, '')], summaryStatus: 'ok', now }), 'ok');
});

// ── error normalization: unmapped statuses and odd shapes ─────────────────────
test('edge: normalizeApiError maps 5xx->server, unknown 4xx->bad_request, non-string loc', () => {
  assert.equal(normalizeApiError(502, null).kind, 'server');
  assert.equal(normalizeApiError(502, null).retryable, true);
  assert.equal(normalizeApiError(418, null).kind, 'bad_request');
  const arr = normalizeApiError(422, { detail: [{ loc: ['body', 'items', 0, 'qty'], msg: 'too small' }] });
  assert.deepEqual(arr.fields, { 'items.0.qty': 'too small' });
  const empty = normalizeApiError(422, { detail: [] });
  assert.equal(empty.kind, 'validation');
});
