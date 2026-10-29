import { useMemo } from 'react';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Trans } from '@lingui/react/macro';
import { formatINR, formatPct } from '../../domain/format.ts';
import type { ChainSummary, ChainStage } from '../../api/schemasDirect.ts';

const C = {
  sell: 'var(--color-sell)',
  sellDeep: 'var(--color-sell-deep)',
  loss: 'var(--color-loss)',
  warn: 'var(--color-warn)',
  ink2: 'var(--color-ink-2)',
  rule: 'var(--color-rule)',
  paper: 'var(--color-paper)',
};

/**
 * One segment of the consumer's rupee.
 *
 * `farmer` is the only segment that is not a deduction: it is what the producer
 * actually receives. Everything else is taken on the way from farm gate to
 * shop shelf, and `avoidable` is the distinction that matters — a margin take is
 * money for doing nothing, a cost take is money for doing something.
 */
interface Slice {
  key: string;
  label: string;
  amount: number;
  pct: number;
  kind: 'farmer' | 'margin' | 'cost';
  stageKey?: string;
  note?: string | null;
}

/**
 * The consumer-rupee breakdown as a single stacked bar.
 *
 * A waterfall is the honest shape for this: start at the retail price the
 * consumer pays, subtract each stage's take, and what is left is the farmer's
 * share. Recharts draws it as one stacked bar so the segments are to scale with
 * each other — a pie chart would be wrong here, because the total is not
 * "everything", it is one price.
 */
export function RupeeChainChart({ chain }: { chain: ChainSummary }) {
  const slices = useMemo(() => buildSlices(chain), [chain]);
  const retail = chain.retail_price;

  if (slices.length === 0 || !retail) return null;

  // Recharts stacks in data order, so one row with every slice is the whole bar.
  const row = useMemo(() => {
    const r: Record<string, number | string> = { label: 'consumer_rupee' };
    for (const s of slices) r[s.key] = s.amount;
    return r;
  }, [slices]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">
          <Trans>Where the consumer&apos;s ₹{formatINR(retail).replace('₹', '')} goes</Trans>
        </h3>
        <p className="font-mono text-xs text-ink-2">
          <Trans>farmer keeps {formatPct(chain.farmer_share_pct ?? 0)}</Trans>
        </p>
      </div>
      <div className="h-14 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={[row]} layout="vertical" margin={{ top: 0, right: 0, bottom: 0, left: 0 }} barCategoryGap={0}>
            <XAxis type="number" hide domain={[0, retail]} />
            <YAxis type="category" dataKey="label" hide />
            <Tooltip
              cursor={{ fill: 'color-mix(in oklab, var(--color-ink) 6%, transparent)' }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                return (
                  <div className="panel px-3 py-2 text-xs">
                    {payload.map((p) => {
                      const s = slices.find((x) => x.key === p.dataKey);
                      if (!s) return null;
                      return (
                        <div key={s.key} className="flex items-baseline gap-2">
                          <span aria-hidden className="inline-block size-2 rounded-sm" style={{ background: colourFor(s.kind) }} />
                          <span>{s.label}</span>
                          <span className="ml-auto font-mono">{formatINR(s.amount)}</span>
                          <span className="font-mono text-ink-2">{formatPct(s.pct)}</span>
                        </div>
                      );
                    })}
                  </div>
                );
              }}
            />
            <Bar dataKey="amount" stackId="rupee" radius={0} isAnimationActive={false}>
              {slices.map((s) => (
                <Cell key={s.key} fill={colourFor(s.kind)} stroke={C.paper} strokeWidth={1} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* The bar alone cannot be read on a phone: every segment is also a row. */}
      <table className="mt-3 w-full text-sm">
        <caption className="sr-only">
          <Trans>Stage-by-stage deduction from the retail price to the farm-gate price</Trans>
        </caption>
        <thead>
          <tr className="border-b border-rule text-left font-mono text-xs uppercase tracking-[0.12em] text-ink-2">
            <th scope="col" className="py-1.5 pr-2"><Trans>Stage</Trans></th>
            <th scope="col" className="py-1.5 pr-2 text-right"><Trans>Takes</Trans></th>
            <th scope="col" className="py-1.5 text-right"><Trans>Of rupee</Trans></th>
          </tr>
        </thead>
        <tbody>
          <tr className="border-b border-rule">
            <th scope="row" className="py-1.5 pr-2 text-left font-medium">
              <Trans>Farmer receives</Trans>
            </th>
            <td className="py-1.5 pr-2 text-right font-mono" style={{ color: C.sell }}>
              {formatINR(chain.farm_price)}
            </td>
            <td className="py-1.5 text-right font-mono text-ink-2">{formatPct(chain.farmer_share_pct ?? 0)}</td>
          </tr>
          {chain.stages.map((st) => (
            <StageRow key={st.key} stage={st} retail={retail} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StageRow({ stage: st, retail }: { stage: ChainStage; retail: number }) {
  const margin = st.margin_take ?? 0;
  const cost = st.cost_take ?? 0;
  return (
    <tr className="border-b border-rule last:border-0">
      <th scope="row" className="py-1.5 pr-2 text-left">
        <span className="block">{st.label_en}</span>
        {st.note && <span className="block text-xs text-ink-2">{st.note}</span>}
      </th>
      <td className="py-1.5 pr-2 text-right font-mono">
        {formatINR(st.take)}
        <span className="ml-1 text-xs text-ink-2" title="margin / real work">
          {margin > 0 && <span style={{ color: C.loss }}>·{formatINR(margin)}</span>}
          {cost > 0 && <span style={{ color: C.ink2 }}> +{formatINR(cost)}</span>}
        </span>
      </td>
      <td className="py-1.5 text-right font-mono text-ink-2">
        {formatPct((st.take / retail) * 100)}
      </td>
    </tr>
  );
}

function buildSlices(chain: ChainSummary): Slice[] {
  const out: Slice[] = [
    { key: 'farmer', label: 'Farmer', amount: chain.farm_price, pct: chain.farmer_share_pct ?? 0, kind: 'farmer' },
  ];
  for (const st of chain.stages) {
    const margin = st.margin_take ?? 0;
    const cost = st.cost_take ?? 0;
    // Margin first: it is the avoidable half, and putting it nearest the farmer's
    // segment makes the point visually — that money could have stayed in the farm.
    if (margin > 0) {
      out.push({
        key: `${st.key}_margin`, label: `${st.label_en} — margin`, amount: margin,
        pct: (margin / chain.retail_price) * 100, kind: 'margin', stageKey: st.key, note: st.note,
      });
    }
    if (cost > 0) {
      out.push({
        key: `${st.key}_cost`, label: `${st.label_en} — cost`, amount: cost,
        pct: (cost / chain.retail_price) * 100, kind: 'cost', stageKey: st.key, note: st.note,
      });
    }
  }
  return out;
}

const colourFor = (kind: Slice['kind']) =>
  kind === 'farmer' ? C.sell : kind === 'margin' ? C.loss : C.warn;
