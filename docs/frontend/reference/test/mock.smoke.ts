// End-to-end against frontend_handoff/mock/mock_api.py: fetch → validate → collapse → chart series.
import { createApiClient } from '../src/api/client.ts';
import { pricesApi } from '../src/api/endpoints/prices.ts';
import { forecastsApi } from '../src/api/endpoints/forecasts.ts';
import { toDailyRows } from '../src/domain/dailyRows.ts';
import { selectLatestRun } from '../src/domain/forecastRun.ts';
import { buildChartSeries } from '../src/domain/chartSeries.ts';
import { istToday } from '../src/domain/dates.ts';

const api = createApiClient({ baseUrl: 'http://127.0.0.1:8000' });
const pair = { marketId: '11111111-1111-1111-1111-111111111101', commodityId: '22222222-2222-2222-2222-222222222201' };
const [hist, fc] = await Promise.all([pricesApi(api).historical({ ...pair, days: 30 }), forecastsApi(api).forPair(pair)]);
const s = buildChartSeries(toDailyRows(hist), selectLatestRun(fc), istToday());
console.log({ rawRows: hist.length, points: s.points.length, horizonDays: s.horizonDays, lastActual: s.lastActualDate,
  hasGap: s.hasGap, method: s.method, changePct: s.changePct?.toFixed(1), range: s.forecastRange, yDomain: s.yDomain });
console.log(s.points.slice(-3));
try { await api.get('/api/v1/forecasts', { query: { market_id: pair.marketId }, schema: (await import('valibot')).unknown() }); }
catch (e) { console.log('error path:', (e as Error).name, (e as any).kind, (e as any).fields); }
