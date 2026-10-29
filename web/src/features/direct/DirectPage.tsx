import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Trans } from '@lingui/react/macro';
import { direct } from '../../api/index.ts';
import { Section } from '../../ui/Section.tsx';
import { Block } from '../../ui/Skeleton.tsx';
import { formatINR, formatPct } from '../../domain/format.ts';
import { RupeeChainChart } from './RupeeChainChart.tsx';
import { rupeeQuery } from '../../queries/direct.ts';

/**
 * The audited, government-published anchors for Lasalgaon onion.
 *
 * These are defaults, not constants: the farm price is the modal mandi price and
 * the retail price is the DCA all-India average, both for 26-09-2026. Starting
 * from the real pair means the screen opens showing the real answer, and the
 * user only edits them to explore a different lane.
 */
const DEFAULT_FARM = 2226.39;
const DEFAULT_RETAIL = 5392;

const COMMODITIES = ['Onion', 'Tomato', 'Potato', 'Soybean'];

/**
 * DirectLink — the consumer-rupee breakdown.
 *
 * This is the page the whole concept turns on. It answers one question with
 * numbers rather than adjectives: when a consumer pays ₹5,392 for a quintal of
 * onion, where did that money actually go? The engine fits the chain between the
 * two published prices and attributes every rupee to either a cost (real work
 * done) or a margin (markup taken).
 *
 * The split is the finding: for the default lane, 85% of the spread is margin and
 * 15% is cost. That is what "avoidable" means, and it is what direct trade
 * removes.
 */
export function DirectPage() {
  const [farm, setFarm] = useState(DEFAULT_FARM);
  const [retail, setRetail] = useState(DEFAULT_RETAIL);
  const [commodity, setCommodity] = useState(COMMODITIES[0]);

  const params = {
    farmPrice: farm,
    retailPrice: retail,
    commodity,
    market: 'Lasalgaon APMC',
  };

  const rupee = useQuery(rupeeQuery(params));
  const report = rupee.data;

  // A lane where the consumer pays less than the farmer is not a lane; refuse to
  // ask the engine rather than letting it fit a nonsense chain.
  const invalid = retail <= farm || farm <= 0;

  return (
    <div className="grid gap-3">
      <div className="flex flex-col gap-3 border-b border-rule pb-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="eyebrow">DirectLink</p>
          <h1 className="mt-1 text-2xl font-bold">
            <Trans>Where your rupee goes</Trans>
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-2">
            <Trans>
              The gap between what a farmer is paid and what a consumer pays is not
              all profit. Some of it is real work — packing, freight, storage. The
              engine separates the two, stage by stage.
            </Trans>
          </p>
        </div>
      </div>

      <Section title="Prices">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Farm-gate price (₹/quintal)" id="direct-farm">
            <input
              id="direct-farm"
              type="number"
              min={1}
              value={farm}
              onChange={(e) => setFarm(Number(e.target.value))}
              className="w-full rounded border border-rule bg-paper-2 px-3 py-2 font-mono"
            />
          </Field>
          <Field label="Retail price (₹/quintal)" id="direct-retail">
            <input
              id="direct-retail"
              type="number"
              min={1}
              value={retail}
              onChange={(e) => setRetail(Number(e.target.value))}
              className="w-full rounded border border-rule bg-paper-2 px-3 py-2 font-mono"
            />
          </Field>
          <Field label="Commodity" id="direct-commodity">
            <select
              id="direct-commodity"
              value={commodity}
              onChange={(e) => setCommodity(e.target.value)}
              className="w-full rounded border border-rule bg-paper-2 px-3 py-2"
            >
              {COMMODITIES.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </Field>
        </div>
        <p className="mt-2 text-xs text-ink-2">
          <Trans>Lasalgaon APMC, 26 September 2026. Farm price is the mandi modal; retail is the DCA all-India average.</Trans>
        </p>
      </Section>

      {invalid && (
        <Section title="Check the prices">
          <p className="text-sm" role="status">
            <Trans>A retail price below the farm-gate price has no chain to explain. Raise one or lower the other.</Trans>
          </p>
        </Section>
      )}

      {!invalid && rupee.isPending && (
        <Section title="Working it out">
          <div className="grid gap-2">
            <Block h={40} />
            <Block h={40} w="75%" />
          </div>
        </Section>
      )}

      {!invalid && rupee.isError && (
        <Section title="Could not work it out">
          <p className="text-sm" role="status">
            <Trans>The breakdown is unavailable right now. The engine runs on this device&apos;s request only — no stored data is involved.</Trans>
          </p>
        </Section>
      )}

      {!invalid && report && (
        <>
          <Section
            title="The finding"
            aside={<span className="font-mono text-xs text-ink-2">calibration: {report.calibration_status}</span>}
          >
            <div className="grid gap-4 sm:grid-cols-3">
              <Stat
                label="Farmer's share of the consumer's rupee"
                value={formatPct(report.farmer_share_pct)}
                tone={report.farmer_share_pct < 50 ? 'loss' : 'sell'}
              />
              <Stat
                label="Margin — avoidable"
                value={formatINR(report.avoidable_per_farm_qtl)}
                sub={formatPct(pctOf(report.avoidable_per_farm_qtl, report))}
                tone="loss"
              />
              <Stat
                label="Real work — unavoidable"
                value={formatINR(report.unavoidable_per_farm_qtl)}
                sub={formatPct(pctOf(report.unavoidable_per_farm_qtl, report))}
                tone="ink"
              />
            </div>
            <p className="mt-3 text-sm leading-relaxed">{report.verdict}</p>
          </Section>

          <Section title="Every rupee accounted for">
            <RupeeChainChart chain={report.chain} />
          </Section>

          <Section title="What direct trade would pay">
            <FairPricePanel farm={farm} retail={retail} commodity={commodity} />
          </Section>
        </>
      )}
    </div>
  );
}

/**
 * What the same lane pays if the intermediaries are removed and the surplus is
 * split between the two people who created it.
 *
 * Shown beside the breakdown rather than on its own screen: the point is not
 * "direct is cheaper", it is "the margin that disappears is the margin that was
 * never paying for anything".
 */
function FairPricePanel({ farm, retail, commodity }: { farm: number; retail: number; commodity: string }) {
  const [qty, setQty] = useState(25);

  const fair = useQuery({
    queryKey: ['direct', 'fair-price', farm, retail, commodity, qty],
    queryFn: ({ signal }) =>
      direct.fairPrice(
        {
          farmPrice: farm,
          retailPrice: retail,
          originLat: 20.12,
          originLng: 74.33,
          destLat: 19.99,
          destLng: 73.79,
          quantityQtl: qty,
          commodity,
        },
        signal,
      ),
    staleTime: 5 * 60_000,
  });

  const split = fair.data?.split;
  const distance = fair.data?.distance_km;

  return (
    <div className="grid gap-3">
      <div className="flex items-end gap-3">
        <Field label="Truckload (quintals)" id="direct-qty">
          <input
            id="direct-qty"
            type="number"
            min={1}
            value={qty}
            onChange={(e) => setQty(Number(e.target.value))}
            className="w-32 rounded border border-rule bg-paper-2 px-3 py-2 font-mono"
          />
        </Field>
        {distance != null && (
          <p className="text-xs text-ink-2">
            <Trans>{distance.toFixed(0)} km lane · freight {formatINR(fair.data?.freight_per_qtl ?? 0)}/quintal</Trans>
          </p>
        )}
      </div>

      {fair.isPending && <Block h={80} />}
      {fair.isError && (
        <p className="text-sm" role="status">
          <Trans>The direct comparison is unavailable right now.</Trans>
        </p>
      )}
      {split && (
        <dl className="grid gap-3 sm:grid-cols-3">
          <Row label="Farmer receives" value={formatINR(split.farm_price_per_qtl)} delta={split.farmer_gain_pct} deltaSuffix="more" tone="sell" />
          <Row label="Consumer pays" value={formatINR(split.consumer_price_per_delivered_qtl)} delta={split.consumer_saving_pct} deltaSuffix="less" tone="sell" />
          <Row label="New surplus created" value={formatINR(split.total_surplus_per_farm_qtl ?? 0)} tone="ink" />
        </dl>
      )}
      {split && (
        <p className="text-xs text-ink-2">
          <Trans>
            The platform takes {formatINR(split.platform_share_rs ?? 0)} and logistics
            {split.logistics_share_rs != null ? ` ${formatINR(split.logistics_share_rs)}` : ''} — together {formatPct(100 - (split.farmer_share_of_consumer_rupee_pct ?? 0))} of what the consumer pays.
          </Trans>
        </p>
      )}
    </div>
  );
}

const pctOf = (part: number, r: { avoidable_per_farm_qtl: number; unavoidable_per_farm_qtl: number }) => {
  const total = r.avoidable_per_farm_qtl + r.unavoidable_per_farm_qtl;
  return total > 0 ? (part / total) * 100 : 0;
};

function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-ink-2">{label}</label>
      {children}
    </div>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone: 'sell' | 'loss' | 'ink' }) {
  const colour = tone === 'sell' ? 'text-sell' : tone === 'loss' ? 'text-loss' : 'text-ink';
  return (
    <div>
      <dt className="text-xs uppercase tracking-[0.12em] text-ink-2">{label}</dt>
      <dd className={`mt-1 font-mono text-2xl font-bold ${colour}`}>
        {value}
        {sub && <span className="ml-2 text-sm font-normal text-ink-2">of the spread</span>}
      </dd>
    </div>
  );
}

/**
 * `delta` is a magnitude in both directions — `farmer_gain_pct` is +63.4 ("63.4%
 * more") and `consumer_saving_pct` is 27.4 ("27.4% less"). Printing a bare sign
 * would show "+27.9%" for a price that fell, so the caller states the direction
 * in words instead.
 */
function Row({ label, value, delta, deltaSuffix, tone }: { label: string; value: string; delta?: number | null; deltaSuffix?: 'more' | 'less'; tone: 'sell' | 'ink' }) {
  return (
    <div className="border-l-2 pl-3" style={{ borderColor: tone === 'sell' ? 'var(--color-sell)' : 'var(--color-rule)' }}>
      <dt className="text-xs uppercase tracking-[0.12em] text-ink-2">{label}</dt>
      <dd className="mt-1 font-mono text-lg font-semibold">
        {value}
        {delta != null && deltaSuffix && (
          <span className="ml-2 text-sm font-normal text-sell">
            {formatPct(delta)} {deltaSuffix}
          </span>
        )}
      </dd>
    </div>
  );
}
