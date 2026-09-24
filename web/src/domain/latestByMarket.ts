// /prices/latest returns up to 7 days of rows, several per market-day. Reduce to the latest
// winning row per market with the same precedence as build_daily_rows (G1).
import type { PriceRow } from '../api/schemas.ts';
import { toDailyRows, type DailyPoint } from './dailyRows.ts';

export interface MarketLatest extends DailyPoint {
  marketId: string;
  marketName: string | null;
  prev: DailyPoint | null;
  /** up to 7 days, ascending, for sparklines */
  daily: DailyPoint[];
}

export function latestByMarket(rows: readonly PriceRow[]): MarketLatest[] {
  const byMarket = new Map<string, PriceRow[]>();
  for (const r of rows) {
    const list = byMarket.get(r.market_id);
    if (list) list.push(r); else byMarket.set(r.market_id, [r]);
  }
  const out: MarketLatest[] = [];
  for (const [marketId, list] of byMarket) {
    const daily = toDailyRows(list);
    const last = daily.at(-1);
    if (!last) continue;
    out.push({ ...last, marketId, marketName: list[0].market_name, prev: daily.at(-2) ?? null, daily });
  }
  return out;
}
