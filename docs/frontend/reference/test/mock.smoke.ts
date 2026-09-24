// End-to-end against frontend_handoff/mock/mock_api.py: fetch → validate → collapse → chart series.
// Asserts invariants instead of relying on recorded output, so mock changes don't look like regressions.
import assert from 'node:assert/strict';
import * as v from 'valibot';
import { createApiClient } from '../src/api/client.ts';
import { pricesApi } from '../src/api/endpoints/prices.ts';
import { forecastsApi } from '../src/api/endpoints/forecasts.ts';
import { toDailyRows } from '../src/domain/dailyRows.ts';
import { selectLatestRun } from '../src/domain/forecastRun.ts';
import { buildChartSeries } from '../src/domain/chartSeries.ts';
import { istToday } from '../src/domain/dates.ts';

const api = createApiClient({ baseUrl: process.env.API_BASE ?? 'http://127.0.0.1:8000' });
const pair = { marketId: '11111111-1111-1111-1111-111111111101', commodityId: '22222222-2222-2222-2222-222222222201' };
const [hist, fc] = await Promise.all([pricesApi(api).historical({ ...pair, days: 30 }), forecastsApi(api).forPair(pair)]);

const daily = toDailyRows(hist);
const run = selectLatestRun(fc);
const s = buildChartSeries(daily, run, istToday());

// G1: one point per day, ascending; multi-row days resolved by source precedence
assert.equal(new Set(daily.map((d) => d.date)).size, daily.length);
assert.ok(daily.every((d, i) => i === 0 || daily[i - 1].date < d.date));
const multi = hist.filter((r, _, all) => all.filter((x) => x.arrival_date === r.arrival_date).length > 1);
for (const r of multi) {
  const winner = daily.find((d) => d.date === r.arrival_date)!;
  assert.equal(winner.source, 'data_gov_in', `precedence on ${r.arrival_date}`);
}
// S1: a single run; forecasts start after the last actual; horizon comes from the data
assert.equal(new Set(fc.map((r) => r.generated_at)).size, 1, 'one generation run per response');
assert.equal(run.length, fc.length);
assert.equal(s.horizonDays, s.points.filter((p) => p.kind === 'forecast').length);
assert.equal(s.points.length, daily.length + s.horizonDays);

console.log({ rawRows: hist.length, multiRowDays: new Set(multi.map((r) => r.arrival_date)).size, dailyPoints: daily.length,
  horizonDays: s.horizonDays, points: s.points.length, lastActual: s.lastActualDate, hasGap: s.hasGap,
  method: s.method, confidence: s.confidence, changePct: s.changePct?.toFixed(1), range: s.forecastRange, yDomain: s.yDomain });

try { await api.get('/api/v1/forecasts', { query: { market_id: pair.marketId }, schema: v.unknown() }); }
catch (e) { console.log('error path:', (e as Error).name, (e as { kind?: string }).kind, (e as { fields?: object }).fields); }
console.log('smoke OK');
