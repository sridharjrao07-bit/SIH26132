import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { Trans, useLingui } from '@lingui/react/macro';
import { useLingui as useLinguiRuntime } from '@lingui/react';
import { RequireAuth } from '../../auth/RequireAuth.tsx';
import { marketplace } from '../../api/index.ts';
import { ApiError } from '../../api/errors.ts';
import type { BuyerRegister } from '../../api/endpoints/marketplace.ts';
import type { Lot, Profile } from '../../api/schemasMarket.ts';
import { supplyQuery, useAuthMutation } from '../../queries/auth.ts';
import { commoditiesQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { formatINR, formatNumber } from '../../domain/format.ts';
import { toE164 } from '../account/AccountPage.tsx';
import { Button, ErrorNote, Field, NativeSelect, fieldError, numOrUndef } from '../../ui/Form.tsx';
import { Section } from '../../ui/Section.tsx';
import { Block } from '../../ui/Skeleton.tsx';
import { BUYER_TYPE, MATCH_REASON, label } from '../sell/labels.ts';

// G12: the API has no "my buyer profile" endpoint (the public list hides owner_user_id), so the
// id returned by /buyers/register is kept on this device, keyed by user.
const useMyBuyer = create<{ byUser: Record<string, string>; set: (u: string, b: string) => void }>()(
  persist((set) => ({ byUser: {}, set: (u, b) => set((s) => ({ byUser: { ...s.byUser, [u]: b } })) }), { name: 'kb-buyer', version: 1 }),
);

export function BuyPage() {
  const { t } = useLingui();
  return (
    <RequireAuth why={t`Buyers need an account so farmers know who is making the offer.`}>
      {(me) => <Buy me={me} />}
    </RequireAuth>
  );
}

function Buy({ me }: { me: Profile }) {
  const buyerId = useMyBuyer((s) => s.byUser[me.id]);
  const status = useQuery({
    queryKey: ['buyers', 'status', buyerId],
    queryFn: ({ signal }) => marketplace.buyers(undefined, signal).then(async (verified) =>
      verified.some((b) => b.id === buyerId) ? 'verified' as const : 'pending' as const),
    enabled: !!buyerId, staleTime: 5 * 60_000,
  });
  return (
    <div className="mx-auto max-w-2xl">
      <div className="px-4 pt-4">
        <h1 className="text-lg font-semibold"><Trans>Buy produce</Trans></h1>
      </div>
      {!buyerId ? <RegisterBuyer me={me} />
        : status.isPending ? <div className="p-4"><Block h={120} /></div>
        : status.data === 'pending' ? (
          <Section>
            <p className="font-semibold"><Trans>Waiting for verification</Trans></p>
            <p className="mt-1 text-sm text-ink-2"><Trans>An admin checks every buyer before farmers can see them. You will be able to see produce and make offers after that.</Trans></p>
          </Section>
        ) : <Supply buyerId={buyerId} />}
    </div>
  );
}

const TYPES = ['trader', 'processor', 'institutional', 'fpo', 'digital'] as const;

function RegisterBuyer({ me }: { me: Profile }) {
  const { _ } = useLinguiRuntime();
  const lang = usePrefs((s) => s.lang);
  const save = useMyBuyer((s) => s.set);
  const commodities = useQuery(commoditiesQuery());
  const [name, setName] = useState(me.name ?? '');
  const [type, setType] = useState<(typeof TYPES)[number]>('trader');
  const [district, setDistrict] = useState(me.district ?? '');
  const [phone, setPhone] = useState(me.phone ?? '');
  const [crop, setCrop] = useState('');
  const [qty, setQty] = useState('');
  const [max, setMax] = useState('');
  const register = useAuthMutation((b: BuyerRegister) => marketplace.registerBuyer(b), (b) => save(me.id, b.id));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const body: BuyerRegister = { name: name.trim(), type, district: district.trim(), phone: toE164(phone) };
    if (crop) body.commodity_id = crop;
    const q = numOrUndef(qty); if (q) body.demand_qty_qtl = q;
    const m = numOrUndef(max); if (m) body.max_price = m;
    register.mutate(body);
  };
  const fe = (f: string) => fieldError(register.error, f);

  return (
    <Section title={<Trans>Register as a buyer</Trans>}>
      <p className="mb-6 text-sm text-ink-2"><Trans>After you register, an admin verifies you. Only verified buyers are shown to farmers.</Trans></p>
      <form onSubmit={submit} className="space-y-5 bg-paper-2 p-4 md:p-6 rounded">
        <Field label={<Trans>Business name</Trans>} required minLength={2} maxLength={200} value={name} onChange={(e) => setName(e.target.value)} error={fe('name')} />
        <NativeSelect label={<Trans>Type</Trans>} value={type} onChange={(v) => setType(v as (typeof TYPES)[number])}>
          {TYPES.map((t) => <option key={t} value={t}>{_(label(BUYER_TYPE, t))}</option>)}
        </NativeSelect>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Field label={<Trans>District</Trans>} required value={district} onChange={(e) => setDistrict(e.target.value)} error={fe('district')} />
          <Field label={<Trans>Mobile number</Trans>} type="tel" required value={phone} onChange={(e) => setPhone(e.target.value)} error={fe('phone')} />
        </div>
        <NativeSelect label={<Trans>Crop you buy</Trans>} value={crop} onChange={setCrop}>
          <option value=""><Trans>Any crop</Trans></option>
          {(commodities.data ?? []).map((c) => <option key={c.id} value={c.id}>{cropName(c, lang)}</option>)}
        </NativeSelect>
        <div className="grid grid-cols-2 gap-4">
          <Field label={<Trans>Quantity needed</Trans>} inputMode="decimal" value={qty} onChange={(e) => setQty(e.target.value)} suffix={<Trans>qtl</Trans>} error={fe('demand_qty_qtl')} />
          <Field label={<Trans>Highest price</Trans>} inputMode="numeric" value={max} onChange={(e) => setMax(e.target.value)} suffix="₹" error={fe('max_price')} />
        </div>
        {!Object.keys((register.error as { fields?: object } | null)?.fields ?? {}).length && <ErrorNote error={register.error} />}
        <Button type="submit" className="w-full mt-4" disabled={register.isPending}><Trans>Register</Trans></Button>
      </form>
    </Section>
  );
}

/** Buyer-side view uses /buyers/{id}/supply, never the farmer's lot screen (§9.6). */
function Supply({ buyerId }: { buyerId: string }) {
  const supply = useQuery(supplyQuery(buyerId));
  if (supply.isPending) return <div className="p-4"><Block h={160} /></div>;
  if (supply.isError) {
    return <Section>{supply.error instanceof ApiError && supply.error.kind === 'not_found'
      ? <p className="text-sm"><Trans>Your buyer profile is not verified yet.</Trans></p> : <ErrorNote error={supply.error} />}</Section>;
  }
  return (
    <Section title={<Trans>Produce that fits what you buy</Trans>}>
      {supply.data.lots.length === 0 ? <p className="text-sm text-ink-2"><Trans>No open lots match right now.</Trans></p>
        : (
          <div className="mt-4 border border-rule rounded-sm overflow-hidden">
            {/* Table Header for Desktop */}
            <div className="hidden md:flex bg-paper-2 px-4 py-2 text-xs font-semibold text-ink-2 border-b border-rule">
              <div className="flex-[2]">Crop & Grade</div>
              <div className="flex-[3]">Location</div>
              <div className="flex-[1] text-right">Qty & Price</div>
              <div className="flex-[1] text-right ml-4">Action</div>
            </div>
            <ul className="divide-y divide-rule bg-paper">
              {supply.data.lots.map((l) => <SupplyRow key={l.id} lot={l} buyerId={buyerId} />)}
            </ul>
          </div>
        )}
    </Section>
  );
}

function SupplyRow({ lot, buyerId }: { lot: Lot; buyerId: string }) {
  const { _ } = useLinguiRuntime();
  const lang = usePrefs((s) => s.lang);
  const commodities = useQuery(commoditiesQuery());
  const [open, setOpen] = useState(false);
  const [price, setPrice] = useState(String(lot.asking_price ?? ''));
  const [qty, setQty] = useState(String(lot.quantity_qtl));
  const [sent, setSent] = useState(false);
  const bid = useAuthMutation(() => marketplace.createOffer({
    lot_id: lot.id, buyer_id: buyerId, price_per_qtl: numOrUndef(price) ?? 0, quantity_qtl: numOrUndef(qty) ?? 0,
  }), () => { setOpen(false); setSent(true); });
  const extra = lot as Lot & { market_name?: string | null; reasons?: string[] };
  const q = formatNumber(lot.quantity_qtl);

  return (
    <li className="px-4 py-4 flex flex-col md:flex-row md:items-center gap-4 hover:bg-paper-2 transition-colors">
      <div className="flex-1 flex flex-col md:flex-row justify-between md:items-center w-full gap-4">
        {/* Crop & Grade */}
        <div className="flex-[2] flex flex-row md:flex-col justify-between items-baseline md:items-start w-full md:w-auto">
          <p className="font-semibold text-base md:text-lg">{cropName(commodities.data?.find((c) => c.id === lot.commodity_id), lang)}</p>
          <p className="text-sm text-ink-2 mt-1 md:mt-0"><Trans>Grade {lot.grade}</Trans></p>
        </div>
        
        {/* Location & Reasons */}
        <div className="flex-[3] flex flex-row md:flex-col justify-between items-baseline md:items-start w-full md:w-auto mt-2 md:mt-0">
          <p className="font-semibold text-sm md:text-base">{extra.market_name ?? '—'}</p>
          {extra.reasons?.length ? <p className="text-xs text-ink-2 mt-1 hidden md:block">{extra.reasons.map((r) => _(label(MATCH_REASON, r))).join(' · ')}</p> : null}
        </div>

        {/* Qty & Price */}
        <div className="flex-[1] text-left md:text-right mt-2 md:mt-0 flex flex-row md:flex-col justify-between items-baseline md:items-end w-full md:w-auto">
          <p className="tabular font-medium text-base md:text-lg"><Trans>{q} qtl</Trans></p>
          {lot.asking_price != null && <p className="tabular text-sm text-ink-2 mt-1"><Trans>asking {formatINR(lot.asking_price)}</Trans></p>}
        </div>
      </div>
      
      {/* Action / Form */}
      <div className="flex-[1] shrink-0 mt-4 md:mt-0 md:ml-4 w-full md:w-auto flex flex-col justify-center">
        {sent ? (
          <p role="status" className="text-xs font-semibold text-sell md:text-right"><Trans>Offer sent. The farmer has 48 hours to reply.</Trans></p>
        ) : open ? (
          <form className="bg-paper border border-rule rounded p-3 space-y-3 shadow-sm w-full min-w-[200px]" onSubmit={(e) => { e.preventDefault(); bid.mutate(undefined); }}>
            <Field label={<Trans>Price</Trans>} inputMode="numeric" required value={price} onChange={(e) => setPrice(e.target.value)} suffix="₹" />
            <Field label={<Trans>Quantity</Trans>} inputMode="decimal" required value={qty} onChange={(e) => setQty(e.target.value)} suffix={<Trans>qtl</Trans>} />
            <ErrorNote error={bid.error} />
            <div className="flex flex-col gap-2 mt-2">
              <Button type="submit" className="text-sm w-full" disabled={bid.isPending || !numOrUndef(price) || !numOrUndef(qty)}><Trans>Send offer</Trans></Button>
              <Button type="button" variant="secondary" className="text-sm w-full" onClick={() => setOpen(false)}><Trans>Cancel</Trans></Button>
            </div>
          </form>
        ) : (
          <Button variant="secondary" className="text-sm w-full md:w-auto md:ml-auto" onClick={() => setOpen(true)}>
            <Trans>Make offer</Trans>
          </Button>
        )}
      </div>
    </li>
  );
}
