import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Trans, useLingui } from '@lingui/react/macro';
import { RequireAuth } from '../../auth/RequireAuth.tsx';
import { alerts as alertsApi } from '../../api/index.ts';
import type { Alert } from '../../api/schemasMarket.ts';
import { alertsQuery, useAuthMutation } from '../../queries/auth.ts';
import { commoditiesQuery, latestForCommodityQuery, marketsQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { formatDateTime, formatDay, formatINR } from '../../domain/format.ts';
import { Button, ErrorNote, Field, NativeSelect, fieldError, numOrUndef } from '../../ui/Form.tsx';
import { Section } from '../../ui/Section.tsx';
import { Block } from '../../ui/Skeleton.tsx';

export function AlertsPage() {
  const { t } = useLingui();
  return (
    <RequireAuth why={t`Alerts are sent by SMS to your phone number, so we need to know who you are.`}>
      {(me) => (
        <div className="mx-auto max-w-2xl">
          <div className="px-4 pt-4">
            <h1 className="text-lg font-semibold"><Trans>Price alerts</Trans></h1>
            <p className="mt-1 text-sm"><Trans>Get an SMS when the price at your mandi goes above or below a price you choose.</Trans></p>
            {!me.phone && (
              <p className="mt-2 rounded border border-ink px-3 py-2 text-sm font-semibold">
                <Trans>Add your phone number in Account, otherwise the SMS cannot reach you.</Trans>
              </p>
            )}
            <p className="mt-2 text-xs text-ink-2"><Trans>Prices are checked about once an hour. There are no notifications inside the app.</Trans></p>
          </div>
          <NewAlert />
          <AlertList />
        </div>
      )}
    </RequireAuth>
  );
}

function NewAlert() {
  const { t } = useLingui();
  const { lang, district, pinnedPairs } = usePrefs();
  const commodities = useQuery(commoditiesQuery());
  const markets = useQuery(marketsQuery(district));
  const [crop, setCrop] = useState(pinnedPairs[0]?.commodityId ?? '');
  const [market, setMarket] = useState(pinnedPairs[0]?.marketId ?? '');
  const [condition, setCondition] = useState<'gte' | 'lte'>('gte');
  const [price, setPrice] = useState('');
  const [expires, setExpires] = useState('');
  const cropId = crop || commodities.data?.[0]?.id || '';
  const latest = useQuery({ ...latestForCommodityQuery(cropId), enabled: !!cropId });
  const current = latest.data?.find((r) => r.marketId === market);

  const create = useAuthMutation(alertsApi.create, () => { setPrice(''); setExpires(''); });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const threshold = numOrUndef(price);
    if (!threshold || !cropId) return;
    create.mutate({
      commodity_id: cropId,
      market_id: market || null,                       // null = nearest mandi at check time
      threshold_price: threshold,
      condition,
      // Omit expiry entirely when unset, rather than sending null.
      ...(expires ? { expires_at: new Date(`${expires}T23:59:59+05:30`).toISOString() } : {}),
    });
  };

  return (
    <Section title={<Trans>New alert</Trans>}>
      <form onSubmit={submit} className="space-y-3">
        <NativeSelect label={<Trans>Crop</Trans>} value={cropId} onChange={setCrop}>
          {(commodities.data ?? []).map((c) => <option key={c.id} value={c.id}>{cropName(c, lang)}</option>)}
        </NativeSelect>
        <NativeSelect label={<Trans>Mandi</Trans>} value={market} onChange={setMarket}>
          <option value="">{t`Nearest mandi to me`}</option>
          {(markets.data ?? []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </NativeSelect>
        <fieldset>
          <legend className="text-sm font-semibold"><Trans>Send the SMS when the price</Trans></legend>
          <div className="mt-1 grid grid-cols-2 gap-2">
            {(['gte', 'lte'] as const).map((c) => (
              <label key={c} className={`tap flex items-center gap-2 rounded border px-3 ${condition === c ? 'border-ink font-semibold' : 'border-rule'}`}>
                <input type="radio" name="condition" value={c} checked={condition === c} onChange={() => setCondition(c)} />
                {c === 'gte' ? <Trans>goes above</Trans> : <Trans>falls below</Trans>}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label={<Trans>Price</Trans>} inputMode="numeric" required value={price} onChange={(e) => setPrice(e.target.value)}
          suffix={<Trans>₹ / quintal</Trans>} error={fieldError(create.error, 'threshold_price')}
          hint={current ? <Trans>Latest price here: {formatINR(current.modal)} on {formatDay(current.date, lang)}</Trans> : undefined} />
        <Field label={<Trans>Stop after (optional)</Trans>} type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
        {!fieldError(create.error, 'threshold_price') && <ErrorNote error={create.error} />}
        <Button type="submit" disabled={create.isPending || !numOrUndef(price)} className="w-full"><Trans>Save alert</Trans></Button>
      </form>
    </Section>
  );
}

function AlertList() {
  const q = useQuery(alertsQuery());
  if (q.isPending) return <div className="p-4"><Block h={120} /></div>;
  if (q.isError) return <div className="p-4"><ErrorNote error={q.error} /></div>;
  return (
    <Section title={<Trans>Your alerts</Trans>}>
      {q.data.length === 0 ? (
        <p className="text-sm text-ink-2"><Trans>No alerts yet.</Trans></p>
      ) : (
        <ul className="-mx-4">{q.data.map((a) => <AlertRow key={a.id} alert={a} />)}</ul>
      )}
    </Section>
  );
}

function AlertRow({ alert: a }: { alert: Alert }) {
  const { lang, district } = usePrefs();
  const commodities = useQuery(commoditiesQuery());
  const markets = useQuery(marketsQuery(district));
  const toggle = useAuthMutation(() => alertsApi.update(a.id, { active: !a.active }));   // only the touched field
  const remove = useAuthMutation(() => alertsApi.remove(a.id));
  const crop = cropName(commodities.data?.find((c) => c.id === a.commodity_id), lang);
  // The real list joins markets(name); fall back to the district list, then "nearest".
  const joined = (a as { markets?: { name?: string } | null }).markets?.name;
  const mandi = a.market_id ? joined ?? markets.data?.find((m) => m.id === a.market_id)?.name : null;
  const expired = a.expires_at != null && Date.parse(a.expires_at) < Date.now();
  const price = formatINR(a.threshold_price);

  return (
    <li className="rule-t px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className={a.active && !expired ? '' : 'text-ink-2'}>
          <p className="font-semibold">{crop} · {mandi ?? <Trans>nearest mandi</Trans>}</p>
          <p className="tabular text-sm">{a.condition === 'gte' ? <Trans>Above {price}</Trans> : <Trans>Below {price}</Trans>}</p>
          <p className="text-xs text-ink-2">
            {expired ? <Trans>Expired</Trans> : !a.active ? <Trans>Paused</Trans> : a.expires_at ? <Trans>Until {formatDay(a.expires_at, lang)}</Trans> : <Trans>No end date</Trans>}
            {a.last_notified_at && <> · <Trans>Last SMS {formatDateTime(a.last_notified_at, lang)}</Trans></>}
          </p>
        </div>
        <div className="flex shrink-0 gap-1">
          {!expired && (
            <Button variant="secondary" className="text-sm" disabled={toggle.isPending} onClick={() => toggle.mutate(undefined)}>
              {a.active ? <Trans>Pause</Trans> : <Trans>Resume</Trans>}
            </Button>
          )}
          <Button variant="quiet" className="text-sm" disabled={remove.isPending} onClick={() => remove.mutate(undefined)}><Trans>Delete</Trans></Button>
        </div>
      </div>
      <ErrorNote error={toggle.error ?? remove.error} />
    </li>
  );
}
