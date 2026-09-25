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
import { Button, ErrorNote, fieldError, numOrUndef } from '../../ui/Form.tsx';
import { Block } from '../../ui/Skeleton.tsx';

export function AlertsPage() {
  const { t } = useLingui();
  return (
    <RequireAuth why={t`Alerts are sent by SMS to your phone number, so we need to know who you are.`}>
      {(me) => (
        <div className="mx-auto max-w-2xl">
          {/* ── DARK HERO STRIP ───────────────────────────────────── */}
          <div
            className="px-4 pt-6 pb-5"
            style={{ background: 'linear-gradient(135deg, #0F0E0C 0%, #1C1A17 60%, #0F0E0C 100%)' }}
          >
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-xl font-bold text-white"><Trans>Price Alerts</Trans></h1>
                <p className="text-sm text-white/60 mt-0.5">
                  <Trans>SMS when the mandi price crosses your target</Trans>
                </p>
              </div>
              {/* Bell icon */}
              <div className="flex size-10 shrink-0 items-center justify-center rounded-xl" style={{ background: 'var(--color-accent)' }}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
                </svg>
              </div>
            </div>

            {!me.phone && (
              <div className="mt-3 rounded-xl px-3 py-2 text-sm font-semibold" style={{ background: 'rgba(110,74,3,0.3)', color: '#F5C842', border: '1px solid rgba(245,200,66,0.2)' }}>
                <svg className="inline mr-1.5 -mt-0.5" width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden><path d="M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2zm1 15h-2v-6h2zm0-8h-2V7h2z"/></svg>
                <Trans>Add your phone number in Account so the SMS can reach you.</Trans>
              </div>
            )}
            <p className="mt-2 text-xs text-white/40">
              <Trans>Prices are checked about once an hour. No in-app notifications.</Trans>
            </p>
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
      market_id: market || null,
      threshold_price: threshold,
      condition,
      ...(expires ? { expires_at: new Date(`${expires}T23:59:59+05:30`).toISOString() } : {}),
    });
  };

  return (
    <div className="px-4 pt-4">
      <h2 className="text-base font-bold text-ink mb-3"><Trans>New Alert</Trans></h2>

      {/* ── SENTENCE FORM CARD (paper-2) ──────────────────────────── */}
      <form
        onSubmit={submit}
        className="rounded-2xl p-4 border border-rule mb-6"
        style={{ background: 'var(--color-paper-2)', boxShadow: 'var(--shadow-card)' }}
      >
        {/* Natural language sentence */}
        <p className="text-base leading-loose font-medium text-ink">
          <Trans>
            SMS me when{' '}
            <select
              className="rounded-md border border-rule px-2 py-1 text-sm font-semibold bg-paper text-ink focus:border-accent focus:outline-none"
              value={market}
              onChange={(e) => setMarket(e.target.value)}
            >
              <option value="">{t`nearest mandi`}</option>
              {markets.data?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
            {' '}goes{' '}
            {/* Condition toggle pills */}
            <span className="inline-flex rounded-md border border-rule overflow-hidden">
              <button
                type="button"
                onClick={() => setCondition('gte')}
                className="px-2 py-1 text-sm font-semibold transition-colors"
                style={{ background: condition === 'gte' ? 'var(--color-accent)' : 'var(--color-paper)', color: condition === 'gte' ? 'white' : 'var(--color-ink-2)' }}
              >
                {t`above`}
              </button>
              <button
                type="button"
                onClick={() => setCondition('lte')}
                className="px-2 py-1 text-sm font-semibold transition-colors"
                style={{ background: condition === 'lte' ? 'var(--color-accent)' : 'var(--color-paper)', color: condition === 'lte' ? 'white' : 'var(--color-ink-2)' }}
              >
                {t`below`}
              </button>
            </span>
            {' '}
            <input
              type="number"
              className="rounded-md border border-rule px-2 py-1 text-sm tabular text-center font-semibold bg-paper text-ink focus:border-accent focus:outline-none"
              style={{ width: 96 }}
              placeholder="₹ price"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              required
            />
            {' '}for{' '}
            <select
              className="rounded-md border border-rule px-2 py-1 text-sm font-semibold bg-paper text-ink focus:border-accent focus:outline-none"
              value={cropId}
              onChange={(e) => setCrop(e.target.value)}
            >
              {commodities.data?.map((c) => <option key={c.id} value={c.id}>{cropName(c, lang)}</option>)}
            </select>.
          </Trans>
        </p>

        {/* Current price context */}
        {current && (
          <p className="text-xs text-ink-2 mt-3 pl-1">
            <Trans>Current price here: {formatINR(current.modal)} · {formatDay(current.date, lang)}</Trans>
          </p>
        )}

        {/* Expiry + submit row */}
        <div className="mt-4 flex flex-col md:flex-row items-start md:items-center gap-3">
          <label className="text-sm flex items-center gap-2 text-ink-2">
            <span className="font-semibold"><Trans>Stop after (optional):</Trans></span>
            <input
              type="date"
              className="rounded-md border border-rule px-2 py-1 text-sm tabular bg-paper focus:border-accent focus:outline-none"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
            />
          </label>
          <div className="flex-1" />
          <Button
            type="submit"
            disabled={create.isPending || !numOrUndef(price)}
            className="w-full md:w-auto px-8 rounded-xl"
            style={{ background: 'var(--color-accent)', color: 'white', border: 'none' }}
          >
            <Trans>Save alert</Trans>
          </Button>
        </div>

        {!fieldError(create.error, 'threshold_price') && <ErrorNote error={create.error} className="mt-3" />}
        {fieldError(create.error, 'threshold_price') && (
          <p className="text-sm font-semibold mt-2" style={{ color: 'var(--color-wait)' }}>
            {fieldError(create.error, 'threshold_price')}
          </p>
        )}
      </form>
    </div>
  );
}

function AlertList() {
  const q = useQuery(alertsQuery());
  if (q.isPending) return <div className="px-4"><Block h={120} /></div>;
  if (q.isError) return <div className="px-4"><ErrorNote error={q.error} /></div>;

  return (
    <div className="px-4">
      <h2 className="text-base font-bold text-ink mb-3"><Trans>Your Alerts</Trans></h2>
      {q.data.length === 0 ? (
        /* Empty state illustration */
        <div className="flex flex-col items-center justify-center py-10 text-center rounded-2xl border border-rule" style={{ background: 'var(--color-paper-2)' }}>
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="var(--color-ink-2)" strokeWidth="1.25" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/>
            <path d="M13.73 21a2 2 0 0 1-3.46 0"/>
            <path d="M8 2 L8 0M12 2 L12 0M16 2 L16 0" strokeDasharray="2 1"/>
          </svg>
          <p className="mt-3 font-semibold text-ink"><Trans>No alerts yet</Trans></p>
          <p className="mt-1 text-sm text-ink-2 max-w-[240px]">
            <Trans>Set a target price above and get an SMS the moment the mandi crosses it.</Trans>
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {q.data.map((a) => <AlertRow key={a.id} alert={a} />)}
        </ul>
      )}
    </div>
  );
}

function AlertRow({ alert: a }: { alert: Alert }) {
  const { lang, district } = usePrefs();
  const { t } = useLingui();
  const commodities = useQuery(commoditiesQuery());
  const markets = useQuery(marketsQuery(district));
  const toggle = useAuthMutation(() => alertsApi.update(a.id, { active: !a.active }));
  const remove = useAuthMutation(() => alertsApi.remove(a.id));
  const crop = cropName(commodities.data?.find((c) => c.id === a.commodity_id), lang);
  const joined = (a as { markets?: { name?: string } | null }).markets?.name;
  const mandi = a.market_id ? joined ?? markets.data?.find((m) => m.id === a.market_id)?.name : null;
  const expired = a.expires_at != null && Date.parse(a.expires_at) < Date.now();
  const price = formatINR(a.threshold_price);

  /* State indicator: green border=active, slate=paused, rule=expired */
  const borderColor = expired ? 'var(--color-rule)' : a.active ? 'var(--color-sell)' : 'var(--color-wait)';
  const badgeBg = expired ? 'var(--color-paper-2)' : a.active ? 'var(--color-sell-tint)' : 'var(--color-wait-tint)';
  const badgeColor = expired ? 'var(--color-ink-2)' : a.active ? 'var(--color-sell)' : 'var(--color-wait)';
  const badgeLabel = expired ? t`Expired` : a.active ? t`Active` : t`Paused`;

  return (
    <li
      className="rounded-2xl border overflow-hidden"
      style={{ background: 'var(--color-paper)', borderColor: 'var(--color-rule)', boxShadow: 'var(--shadow-card)' }}
    >
      {/* Colored top accent line */}
      <div className="h-1 w-full" style={{ background: borderColor }} aria-hidden />

      <div className={`p-4 ${a.active && !expired ? '' : 'opacity-70'}`}>
        {/* Status badge */}
        <div className="flex items-center gap-2 mb-2">
          <span
            className="text-[11px] font-bold uppercase tracking-wide px-2 py-0.5 rounded-md"
            style={{ background: badgeBg, color: badgeColor }}
          >
            {badgeLabel}
          </span>
          {a.expires_at && !expired && (
            <span className="text-xs text-ink-2">
              <Trans>Until {formatDay(a.expires_at, lang)}</Trans>
            </span>
          )}
          {a.last_notified_at && (
            <span className="text-xs text-ink-2 ml-auto">
              <Trans>SMS sent {formatDateTime(a.last_notified_at, lang)}</Trans>
            </span>
          )}
        </div>

        {/* Alert sentence */}
        <p className="text-sm leading-snug font-medium text-ink">
          <Trans>
            SMS me when <strong>{mandi ?? t`nearest mandi`}</strong> goes{' '}
            <strong>{a.condition === 'gte' ? t`above` : t`below`}</strong>{' '}
            <strong>{price}</strong> for {crop}.
          </Trans>
        </p>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 px-4 pb-3 rule-t pt-3">
        {!expired && (
          <button
            className="tap flex-1 rounded-xl text-sm font-semibold border border-rule hover:bg-paper-2 transition-colors"
            disabled={toggle.isPending}
            onClick={() => toggle.mutate(undefined)}
          >
            {a.active ? <Trans>Pause</Trans> : <Trans>Resume</Trans>}
          </button>
        )}
        <button
          className="tap flex-1 rounded-xl text-sm font-semibold text-ink-2 hover:bg-paper-2 transition-colors"
          disabled={remove.isPending}
          onClick={() => remove.mutate(undefined)}
        >
          <Trans>Delete</Trans>
        </button>
      </div>
      <ErrorNote error={toggle.error ?? remove.error} className="px-4 pb-3" />
    </li>
  );
}
