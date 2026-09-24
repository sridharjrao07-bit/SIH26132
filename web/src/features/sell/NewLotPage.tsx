import { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Trans, useLingui } from '@lingui/react/macro';
import { RequireAuth } from '../../auth/RequireAuth.tsx';
import { marketplace } from '../../api/index.ts';
import type { LotCreate } from '../../api/endpoints/marketplace.ts';
import { useAuthMutation } from '../../queries/auth.ts';
import { commoditiesQuery, latestForCommodityQuery, marketsQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { formatDay, formatINR } from '../../domain/format.ts';
import { Button, ErrorNote, Field, NativeSelect, fieldError, numOrUndef } from '../../ui/Form.tsx';

const GRADES = ['FAQ', 'General', 'Special'] as const;

export function NewLotPage() {
  const { t } = useLingui();
  return (
    <RequireAuth why={t`Selling needs an account so buyers' offers reach you and every step is recorded.`}>
      {() => <NewLotForm />}
    </RequireAuth>
  );
}

function NewLotForm() {
  const navigate = useNavigate();
  const { lang, district, pinnedPairs } = usePrefs();
  const commodities = useQuery(commoditiesQuery());
  const markets = useQuery(marketsQuery(district));
  const [crop, setCrop] = useState(pinnedPairs[0]?.commodityId ?? '');
  const [market, setMarket] = useState(pinnedPairs[0]?.marketId ?? '');
  const [qty, setQty] = useState('');
  const [grade, setGrade] = useState<(typeof GRADES)[number]>('General');
  const [price, setPrice] = useState('');
  const [harvest, setHarvest] = useState('');
  const [notes, setNotes] = useState('');
  const cropId = crop || commodities.data?.[0]?.id || '';
  const latest = useQuery({ ...latestForCommodityQuery(cropId), enabled: !!cropId });
  const here = latest.data?.find((r) => r.marketId === market);

  const create = useAuthMutation(marketplace.createLot, (lot) => navigate({ to: '/sell/$lotId', params: { lotId: lot.id } }));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const quantity = numOrUndef(qty);
    if (!quantity || !cropId) return;
    // Optional fields are omitted when empty, never sent as null.
    const body: LotCreate = { commodity_id: cropId, quantity_qtl: quantity, grade };
    if (market) body.market_id = market;
    const ask = numOrUndef(price); if (ask) body.asking_price = ask;
    if (harvest) body.harvest_date = harvest;
    if (notes.trim()) body.quality_notes = notes.trim();
    create.mutate(body);
  };

  return (
    <div className="mx-auto max-w-lg px-4 py-4">
      <h1 className="text-lg font-semibold"><Trans>List produce for sale</Trans></h1>
      <form onSubmit={submit} className="mt-3 space-y-3">
        <NativeSelect label={<Trans>Crop</Trans>} value={cropId} onChange={setCrop}>
          {(commodities.data ?? []).map((c) => <option key={c.id} value={c.id}>{cropName(c, lang)}</option>)}
        </NativeSelect>
        <NativeSelect label={<Trans>Mandi you would sell at</Trans>} value={market} onChange={setMarket}>
          <option value=""><Trans>Not decided</Trans></option>
          {(markets.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </NativeSelect>
        <Field label={<Trans>Quantity</Trans>} inputMode="decimal" required value={qty} onChange={(e) => setQty(e.target.value)}
          suffix={<Trans>quintal</Trans>} error={fieldError(create.error, 'quantity_qtl')} />
        <fieldset>
          <legend className="text-sm font-semibold"><Trans>Grade</Trans></legend>
          <div className="mt-1 grid grid-cols-3 gap-2">
            {GRADES.map((g) => (
              <label key={g} className={`tap flex items-center justify-center gap-2 rounded border px-2 ${grade === g ? 'border-ink font-semibold' : 'border-rule'}`}>
                <input type="radio" name="grade" className="sr-only" checked={grade === g} onChange={() => setGrade(g)} />
                {g === 'FAQ' ? 'FAQ' : g === 'General' ? <Trans>General</Trans> : <Trans>Special</Trans>}
              </label>
            ))}
          </div>
          <p className="mt-1 text-xs text-ink-2"><Trans>FAQ = fair average quality, the standard mandi grade.</Trans></p>
        </fieldset>
        <Field label={<Trans>Asking price (optional)</Trans>} inputMode="numeric" value={price} onChange={(e) => setPrice(e.target.value)}
          suffix={<Trans>₹ / quintal</Trans>} error={fieldError(create.error, 'asking_price')}
          hint={here ? <Trans>Latest mandi price: {formatINR(here.modal)} on {formatDay(here.date, lang)}</Trans> : undefined} />
        <Field label={<Trans>Harvest date (optional)</Trans>} type="date" value={harvest} onChange={(e) => setHarvest(e.target.value)} />
        <Field label={<Trans>Quality notes (optional)</Trans>} value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
        {!Object.keys((create.error as { fields?: object } | null)?.fields ?? {}).length && <ErrorNote error={create.error} />}
        <Button type="submit" className="w-full" disabled={create.isPending || !numOrUndef(qty)}><Trans>List and get advice</Trans></Button>
      </form>
    </div>
  );
}
