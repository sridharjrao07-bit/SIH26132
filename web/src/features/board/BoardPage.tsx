import { Link, useNavigate, useSearch } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Trans } from '@lingui/react/macro';
import { commoditiesQuery, latestForCommodityQuery, marketsQuery, summaryQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { formatDay, formatINR, formatPct } from '../../domain/format.ts';
import { daysBetween, istToday } from '../../domain/dates.ts';
import { Sparkline } from '../../charts/Sparkline.tsx';
import { Block } from '../../ui/Skeleton.tsx';
import { CropIcon } from '../../ui/CropIcons.tsx';

/** Board = /forecasts/summary + /prices/latest. No per-pair history fan-out (G3). */
export function BoardPage() {
  const lang = usePrefs((s) => s.lang);
  const district = usePrefs((s) => s.district);
  const pinned = usePrefs((s) => s.pinnedPairs[0]);
  const commodities = useQuery(commoditiesQuery());
  const markets = useQuery(marketsQuery(district));
  const summary = useQuery(summaryQuery());
  const search = useSearch({ from: '/bhav' });
  const navigate = useNavigate({ from: '/bhav' });
  const crop = search.crop ?? pinned?.commodityId ?? commodities.data?.[0]?.id;
  const latest = useQuery({ ...latestForCommodityQuery(crop ?? ''), enabled: !!crop });
  const today = istToday();

  /* ── Summary strip calculations ─────────────────────────────── */
  const rows = latest.data ?? [];
  const bestRow = rows.reduce<(typeof rows)[0] | null>((best, r) => {
    if (!best) return r;
    return r.modal > best.modal ? r : best;
  }, null);
  const bestMarket = markets.data?.find((m) => m.id === bestRow?.marketId);

  const biggestMover = rows.reduce<{ row: (typeof rows)[0]; pct: number } | null>((best, r) => {
    if (!r.prev || r.prev.modal === 0) return best;
    const pct = ((r.modal - r.prev.modal) / r.prev.modal) * 100;
    if (!best || Math.abs(pct) > Math.abs(best.pct)) return { row: r, pct };
    return best;
  }, null);
  const moverMarket = markets.data?.find((m) => m.id === biggestMover?.row.marketId);
  const cropObj = commodities.data?.find((c) => c.id === crop);

  return (
    <div className="pb-4">

      {/* ── HEADER ──────────────────────────────────────────────── */}
      <div className="rule-b bg-paper px-4 pt-4 pb-0">
        <h1 className="text-lg font-semibold"><Trans>Mandi prices · {district}</Trans></h1>

        {/* Crop filter chips with SVG icons */}
        <div className="mt-3 -mx-4 px-4 flex gap-2 overflow-x-auto pb-3 scrollbar-hide" role="tablist">
          {(commodities.data ?? []).map((c) => {
            const isSelected = c.id === crop;
            return (
              <button
                key={c.id}
                role="tab"
                aria-selected={isSelected}
                onClick={() => navigate({ search: { crop: c.id }, replace: true })}
                className="tap shrink-0 flex items-center gap-1.5 rounded-md px-3 text-sm font-semibold transition-all"
                style={{
                  background: isSelected ? 'var(--color-accent)' : 'var(--color-paper-2)',
                  color: isSelected ? 'white' : 'var(--color-ink)',
                  border: isSelected ? 'none' : '1px solid var(--color-rule)',
                  transform: 'scale(1)',
                  transition: 'transform 90ms cubic-bezier(0.4,0,0.2,1), background-color 90ms',
                }}
                onMouseDown={(e) => (e.currentTarget.style.transform = 'scale(0.98)')}
                onMouseUp={(e) => (e.currentTarget.style.transform = 'scale(1)')}
                onMouseLeave={(e) => (e.currentTarget.style.transform = 'scale(1)')}
              >
                <CropIcon
                  commodityId={c.id}
                  size={16}
                  stroke={isSelected ? 'white' : 'var(--color-ink-2)'}
                />
                {cropName(c, lang)}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── SUMMARY STRIP (accent-tint hero) ─────────────────────── */}
      {!latest.isPending && bestRow && (
        <div
          className="px-4 py-4 grid grid-cols-2 gap-4 border-b border-rule"
          style={{ background: 'var(--color-accent-tint)' }}
        >
          {/* Best mandi today */}
          <div>
            <div className="flex items-center gap-1.5 mb-1">
              {/* Trophy icon */}
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M8 21h8M12 17v4M17 3H7v8a5 5 0 0 0 10 0V3z"/><path d="M17 3h2a2 2 0 0 1 2 2v1a3 3 0 0 1-3 3h-1M7 3H5a2 2 0 0 0-2 2v1a3 3 0 0 0 3 3h1"/>
              </svg>
              <p className="text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-accent)' }}>
                <Trans>Best today</Trans>
              </p>
            </div>
            <p className="tabular text-2xl font-bold text-ink leading-none">{formatINR(bestRow.modal)}</p>
            <p className="text-xs text-ink-2 mt-0.5">{bestMarket?.name ?? '—'}</p>
          </div>

          {/* Biggest mover */}
          {biggestMover && (
            <div className="border-l border-accent/20 pl-4">
              <div className="flex items-center gap-1.5 mb-1">
                {/* Trending icon */}
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="m23 6-9.5 9.5-5-5L1 18"/><path d="M17 6h6v6"/>
                </svg>
                <p className="text-[11px] font-bold uppercase tracking-wider" style={{ color: 'var(--color-accent)' }}>
                  <Trans>Biggest mover</Trans>
                </p>
              </div>
              <p
                className="tabular text-2xl font-bold leading-none"
                style={{ color: biggestMover.pct > 0 ? 'var(--color-sell)' : 'var(--color-wait)' }}
              >
                {biggestMover.pct > 0 ? '▲' : '▼'} {formatPct(Math.abs(biggestMover.pct))}
              </p>
              <p className="text-xs text-ink-2 mt-0.5">{moverMarket?.name ?? '—'}</p>
            </div>
          )}
        </div>
      )}

      {/* ── MANDI ROWS ───────────────────────────────────────────── */}
      {latest.isPending || !crop ? (
        <div className="space-y-2 p-4">
          {[0, 1, 2, 3].map((i) => <Block key={i} h={64} />)}
        </div>
      ) : (
        <div>
          {(markets.data ?? []).map((m, idx) => {
            const row = latest.data?.find((r) => r.marketId === m.id);
            const f = summary.data?.find((s) => s.market_id === m.id && s.commodity_id === crop);
            const diff = row?.prev ? row.modal - row.prev.modal : null;
            const isNearest = m.id === pinned?.marketId;
            const stagger = idx < 4 ? `row-stagger-${idx + 1}` : '';

            /* verdict border color: use diff direction as proxy (no per-row verdict on board) */
            const borderColor =
              diff === null ? 'var(--color-rule)'
              : diff > 50   ? 'var(--color-sell)'
              : diff < -50  ? 'var(--color-wait)'
              :               'var(--color-hold)';

            return (
              <div
                key={m.id}
                className={`${stagger} flex items-stretch border-b border-rule hover:bg-paper-2 transition-colors`}
                style={idx < 4 ? { animation: `row-in 200ms ${idx * 40}ms cubic-bezier(0.16,1,0.3,1) both` } : undefined}
              >
                {/* Verdict left border */}
                <div className="w-1 shrink-0 rounded-r-sm" style={{ background: borderColor }} aria-hidden />

                <div className="flex flex-1 items-center gap-3 px-3 py-3 min-h-[64px]">
                  {/* COLUMN 1: Mandi info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Link
                        to="/c/$crop/m/$market"
                        params={{ crop: crop!, market: m.id }}
                        className="font-semibold text-base text-ink hover:underline underline-offset-4 hover:text-accent transition-colors"
                      >
                        {m.name}
                      </Link>
                      {isNearest && (
                        <span
                          className="text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-sm"
                          style={{
                            background: 'var(--color-accent-tint)',
                            color: 'var(--color-accent)',
                            border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)',
                          }}
                        >
                          <Trans>Primary</Trans>
                        </span>
                      )}
                    </div>
                    {/* Forecast snippet */}
                    <div className="text-xs text-ink-2 mt-0.5">
                      {!f ? null
                        : f.status === 'insufficient_data' ? <Trans>Not enough data yet</Trans>
                        : f.predicted_price != null ? (
                          <span style={{ color: 'var(--color-forecast)' }}>
                            <Trans>Tomorrow: {formatINR(f.predicted_price)}</Trans>
                          </span>
                        ) : null}
                      {row && daysBetween(row.date, today) > 1 && (
                        <span className="ml-1 font-semibold text-hold">
                          <Trans>· {formatDay(row.date, lang)}</Trans>
                        </span>
                      )}
                    </div>
                  </div>

                  {/* COLUMN 2: Price + change */}
                  <div className="tabular text-right shrink-0">
                    <p className="text-lg font-semibold text-ink">{row ? formatINR(row.modal) : '—'}</p>
                    {diff !== null && Math.abs(diff) >= 0.5 && (
                      <p
                        className="text-xs font-semibold"
                        style={{ color: diff > 0 ? 'var(--color-sell)' : 'var(--color-wait)' }}
                      >
                        {diff > 0 ? '▲' : '▼'} {formatPct((Math.abs(diff) / row!.prev!.modal) * 100)}
                      </p>
                    )}
                  </div>

                  {/* COLUMN 3: Sparkline */}
                  <div className="shrink-0 w-20">
                    {row && <Sparkline daily={row.daily} />}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Empty state */}
      {!latest.isPending && crop && (latest.data?.length ?? 0) === 0 && (
        <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
          <svg width="56" height="56" viewBox="0 0 64 64" fill="none" stroke="var(--color-ink-2)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <rect x="8" y="32" width="48" height="28" rx="4"/>
            <path d="M20 32 L20 24 Q20 16 32 16 Q44 16 44 24 L44 32"/>
            <path d="M28 46 L36 46M32 42 L32 50"/>
          </svg>
          <p className="mt-4 text-base font-semibold text-ink">
            <Trans>No prices yet for {cropName(cropObj, lang)} in {district}</Trans>
          </p>
          <p className="mt-1 text-sm text-ink-2">
            <Trans>Prices are typically reported after 9 AM on market days.</Trans>
          </p>
        </div>
      )}

      <p className="px-4 py-3 text-xs text-ink-2">
        <Trans>Prices in ₹ per quintal. Change is against the previous reported day.</Trans>
      </p>
    </div>
  );
}
