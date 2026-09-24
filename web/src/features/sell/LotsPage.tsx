import { useState } from 'react';
import { Link } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Trans, useLingui } from '@lingui/react/macro';
import { useLingui as useLinguiRuntime } from '@lingui/react';
import { RequireAuth } from '../../auth/RequireAuth.tsx';
import { marketplace } from '../../api/index.ts';
import type { Lot, Profile } from '../../api/schemasMarket.ts';
import { lotsQuery, offersQuery, useAuthMutation } from '../../queries/auth.ts';
import { commoditiesQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { formatINR, formatNumber } from '../../domain/format.ts';
import { Button, ErrorNote, Field, numOrUndef } from '../../ui/Form.tsx';
import { Section } from '../../ui/Section.tsx';
import { Block } from '../../ui/Skeleton.tsx';
import { LOT_STATUS, label } from './labels.ts';

export function LotsPage() {
  const { t } = useLingui();
  return (
    <RequireAuth why={t`Selling needs an account so buyers' offers reach you and every step is recorded.`}>
      {(me) => <Lots me={me} />}
    </RequireAuth>
  );
}

function Lots({ me }: { me: Profile }) {
  const lots = useQuery(lotsQuery());
  const offers = useQuery(offersQuery());
  const pending = (lotId: string) => (offers.data ?? []).filter((o) => o.lot_id === lotId && o.status === 'pending').length;

  return (
    <div className="mx-auto max-w-2xl">
      <div className="flex items-end justify-between gap-3 px-4 pt-4 pb-3">
        <div>
          <h1 className="text-lg font-semibold"><Trans>My produce for sale</Trans></h1>
          <p className="text-sm text-ink-2"><Trans>List a lot, get advice, and choose a buyer.</Trans></p>
        </div>
        <Link to="/sell/new" className="tap inline-flex shrink-0 items-center rounded bg-ink px-4 font-semibold text-paper"><Trans>+ List produce</Trans></Link>
      </div>
      {lots.isPending ? <div className="p-4"><Block h={160} /></div>
        : lots.isError ? <div className="p-4"><ErrorNote error={lots.error} /></div>
        : lots.data.length === 0 ? (
          <Section><p className="text-sm text-ink-2"><Trans>Nothing listed yet. Tap “List produce” to add your first lot.</Trans></p></Section>
        ) : (
          <ul className="rule-t">
            {lots.data.map((l) => <LotRow key={l.id} lot={l} pendingOffers={pending(l.id)} />)}
          </ul>
        )}
      {me.role === 'fpo' && lots.data && <PoolLots lots={lots.data} />}
    </div>
  );
}

function LotRow({ lot, pendingOffers }: { lot: Lot; pendingOffers: number }) {
  const { _ } = useLinguiRuntime();
  const lang = usePrefs((s) => s.lang);
  const commodities = useQuery(commoditiesQuery());
  const crop = cropName(commodities.data?.find((c) => c.id === lot.commodity_id), lang);
  const qty = formatNumber(lot.quantity_qtl);
  return (
    <li className="rule-b">
      <Link to="/sell/$lotId" params={{ lotId: lot.id }} className="tap flex items-center justify-between gap-3 px-4 py-3">
        <div className={lot.status === 'withdrawn' ? 'text-ink-2' : ''}>
          <p className="font-semibold">{crop} · <span className="tabular"><Trans>{qty} qtl</Trans></span></p>
          <p className="text-sm text-ink-2">
            {_(label(LOT_STATUS, lot.status))}
            {lot.asking_price != null && <> · <span className="tabular"><Trans>asking {formatINR(lot.asking_price)}</Trans></span></>}
          </p>
        </div>
        <span className="flex items-center gap-2">
          {pendingOffers > 0 && <span className="rounded border border-ink px-2 text-xs font-semibold tabular"><Trans>{pendingOffers} new</Trans></span>}
          <span aria-hidden className="text-ink-2">›</span>
        </span>
      </Link>
    </li>
  );
}

/** FPO pooling (role-gated). The server requires 2–50 open lots of one crop (§9.7). */
function PoolLots({ lots }: { lots: Lot[] }) {
  const lang = usePrefs((s) => s.lang);
  const commodities = useQuery(commoditiesQuery());
  const [picked, setPicked] = useState<string[]>([]);
  const [price, setPrice] = useState('');
  const open = lots.filter((l) => l.status === 'open');
  const crop = picked.length ? open.find((l) => l.id === picked[0])?.commodity_id : null;
  const pool = useAuthMutation(() => marketplace.aggregate(picked, numOrUndef(price)), () => { setPicked([]); setPrice(''); });
  const total = open.filter((l) => picked.includes(l.id)).reduce((s, l) => s + l.quantity_qtl, 0);
  const totalLabel = formatNumber(total);

  return (
    <Section title={<Trans>Pool lots (FPO)</Trans>}>
      <p className="mb-2 text-sm text-ink-2"><Trans>Pick at least 2 open lots of the same crop to sell as one bigger lot.</Trans></p>
      {open.length < 2 ? <p className="text-sm"><Trans>You need at least 2 open lots to pool.</Trans></p> : (
        <>
          <ul className="-mx-4 rule-t">
            {open.map((l) => {
              const disabled = crop != null && l.commodity_id !== crop;
              const qty = formatNumber(l.quantity_qtl);
              return (
                <li key={l.id} className="rule-b px-4">
                  <label className={`tap flex items-center gap-3 ${disabled ? 'text-ink-2' : ''}`}>
                    <input type="checkbox" disabled={disabled} checked={picked.includes(l.id)}
                      onChange={(e) => setPicked(e.target.checked ? [...picked, l.id] : picked.filter((x) => x !== l.id))} />
                    {cropName(commodities.data?.find((c) => c.id === l.commodity_id), lang)} · <span className="tabular"><Trans>{qty} qtl</Trans></span>
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="mt-3 space-y-3">
            <Field label={<Trans>Asking price for the pool (optional)</Trans>} inputMode="numeric" value={price} onChange={(e) => setPrice(e.target.value)} suffix={<Trans>₹ / quintal</Trans>} />
            <ErrorNote error={pool.error} />
            <Button className="w-full" disabled={picked.length < 2 || pool.isPending} onClick={() => pool.mutate(undefined)}>
              <Trans>Pool {picked.length} lots ({totalLabel} qtl)</Trans>
            </Button>
          </div>
        </>
      )}
    </Section>
  );
}
