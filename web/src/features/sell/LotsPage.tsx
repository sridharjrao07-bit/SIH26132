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
import { Block } from '../../ui/Skeleton.tsx';
import { LOT_STATUS, label } from './labels.ts';
import { CropIcon } from '../../ui/CropIcons.tsx';

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
  const pending = (lotId: string) =>
    (offers.data ?? []).filter((o) => o.lot_id === lotId && o.status === 'pending').length;

  return (
    <div className="mx-auto max-w-2xl">

      {/* ── DARK HERO STRIP ───────────────────────────────────────── */}
      <div
        className="px-4 pt-6 pb-5"
        style={{ background: 'linear-gradient(135deg, #0F0E0C 0%, #1C1A17 60%, #0F0E0C 100%)' }}
      >
        <div className="flex items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-white"><Trans>My Produce</Trans></h1>
            <p className="text-sm text-white/60 mt-0.5">
              <Trans>List lots · Get offers · Choose buyers</Trans>
            </p>
          </div>
          <Link
            to="/sell/new"
            className="tap shrink-0 flex items-center gap-1.5 rounded-xl px-4 font-semibold text-sm"
            style={{ background: 'var(--color-accent)', color: 'white' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M12 5v14M5 12h14"/>
            </svg>
            <Trans>List produce</Trans>
          </Link>
        </div>
      </div>

      {/* ── LOT CONTENT ───────────────────────────────────────────── */}
      <div className="px-4 pt-4 pb-8">
        {lots.isPending ? (
          <div className="space-y-3">
            {[0, 1].map((i) => <Block key={i} h={88} />)}
          </div>
        ) : lots.isError ? (
          <ErrorNote error={lots.error} />
        ) : lots.data.length === 0 ? (
          /* ── Empty state ── */
          <div
            className="flex flex-col items-center justify-center py-12 text-center rounded-2xl border border-rule"
            style={{ background: 'var(--color-paper-2)' }}
          >
            {/* Crate / box illustration */}
            <svg width="56" height="56" viewBox="0 0 64 64" fill="none" stroke="var(--color-ink-2)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <rect x="8" y="28" width="48" height="32" rx="4"/>
              <path d="M8 36 L56 36"/>
              <path d="M24 36 L24 28 M40 36 L40 28"/>
              <path d="M8 28 L16 16 L48 16 L56 28"/>
              <path d="M16 16 L24 28 M48 16 L40 28"/>
              {/* Plus icon */}
              <circle cx="32" cy="48" r="8" strokeWidth="1.5"/>
              <path d="M32 44 L32 52 M28 48 L36 48" strokeWidth="2"/>
            </svg>
            <p className="mt-4 text-base font-semibold text-ink"><Trans>Nothing listed yet</Trans></p>
            <p className="mt-1 text-sm text-ink-2 max-w-[240px]">
              <Trans>Tap "List produce" to add your first lot and start receiving buyer offers.</Trans>
            </p>
            <Link
              to="/sell/new"
              className="tap mt-4 flex items-center gap-1.5 rounded-xl px-6 font-semibold text-sm text-white"
              style={{ background: 'var(--color-accent)' }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M12 5v14M5 12h14"/>
              </svg>
              <Trans>List produce</Trans>
            </Link>
          </div>
        ) : (
          <ul className="space-y-3">
            {lots.data.map((l) => (
              <LotRow key={l.id} lot={l} pendingOffers={pending(l.id)} />
            ))}
          </ul>
        )}

        {/* FPO Pool section */}
        {me.role === 'fpo' && lots.data && <PoolLots lots={lots.data} />}
      </div>
    </div>
  );
}

function LotRow({ lot, pendingOffers }: { lot: Lot; pendingOffers: number }) {
  const { _ } = useLinguiRuntime();
  const lang = usePrefs((s) => s.lang);
  const commodities = useQuery(commoditiesQuery());
  const crop = cropName(commodities.data?.find((c) => c.id === lot.commodity_id), lang);
  const qty = formatNumber(lot.quantity_qtl);

  const isOpen = lot.status === 'open';
  const topBorderColor = isOpen ? 'var(--color-sell)' : 'var(--color-rule)';
  const statusBg = isOpen ? 'var(--color-sell-tint)' : 'var(--color-paper-2)';
  const statusColor = isOpen ? 'var(--color-sell)' : 'var(--color-ink-2)';

  return (
    <li
      className="rounded-2xl border overflow-hidden transition-shadow hover:shadow-md"
      style={{ background: 'var(--color-paper)', borderColor: 'var(--color-rule)', boxShadow: 'var(--shadow-card)' }}
    >
      {/* Colored top accent line */}
      <div className="h-1 w-full" style={{ background: topBorderColor }} aria-hidden />

      <Link
        to="/sell/$lotId"
        params={{ lotId: lot.id }}
        className={`flex items-center gap-3 p-4 ${lot.status === 'withdrawn' ? 'opacity-60' : ''}`}
      >
        {/* Crop icon box */}
        <div
          className="flex shrink-0 size-10 items-center justify-center rounded-xl"
          style={{ background: 'var(--color-accent-tint)' }}
          aria-hidden
        >
          <CropIcon
            commodityId={lot.commodity_id}
            size={20}
            stroke="var(--color-accent)"
          />
        </div>

        {/* Details */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-semibold text-ink">{crop}</p>
            <span className="tabular text-sm text-ink-2">
              <Trans>{qty} qtl</Trans>
            </span>
            {/* Status badge */}
            <span
              className="text-[11px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md"
              style={{ background: statusBg, color: statusColor }}
            >
              {_(label(LOT_STATUS, lot.status))}
            </span>
          </div>
          {lot.asking_price != null && (
            <p className="text-sm text-ink-2 mt-0.5">
              <Trans>Asking <span className="tabular">{formatINR(lot.asking_price)}</span>/qtl</Trans>
            </p>
          )}
        </div>

        {/* Right: offers badge + chevron */}
        <div className="flex items-center gap-2">
          {pendingOffers > 0 && (
            <span
              className="tabular text-xs font-bold px-2 py-0.5 rounded-md"
              style={{ background: 'var(--color-accent-tint)', color: 'var(--color-accent)' }}
            >
              <Trans>{pendingOffers} new</Trans>
            </span>
          )}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-ink-2)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="m9 18 6-6-6-6"/>
          </svg>
        </div>
      </Link>
    </li>
  );
}

function PoolLots({ lots }: { lots: Lot[] }) {
  const lang = usePrefs((s) => s.lang);
  const commodities = useQuery(commoditiesQuery());
  const [picked, setPicked] = useState<string[]>([]);
  const [price, setPrice] = useState('');
  const open = lots.filter((l) => l.status === 'open');
  const crop = picked.length ? open.find((l) => l.id === picked[0])?.commodity_id : null;
  const pool = useAuthMutation(
    () => marketplace.aggregate(picked, numOrUndef(price)),
    () => { setPicked([]); setPrice(''); },
  );
  const total = open.filter((l) => picked.includes(l.id)).reduce((s, l) => s + l.quantity_qtl, 0);
  const totalLabel = formatNumber(total);

  return (
    <div
      className="mt-6 rounded-2xl border p-4"
      style={{ background: 'var(--color-accent-tint)', borderColor: 'color-mix(in srgb, var(--color-accent) 20%, transparent)' }}
    >
      <h2 className="text-base font-bold mb-1" style={{ color: 'var(--color-accent)' }}>
        <Trans>Pool lots (FPO)</Trans>
      </h2>
      <p className="text-sm text-ink-2 mb-3">
        <Trans>Pick 2+ open lots of the same crop to sell as one bigger lot.</Trans>
      </p>

      {open.length < 2 ? (
        <p className="text-sm text-ink-2"><Trans>You need at least 2 open lots to pool.</Trans></p>
      ) : (
        <>
          <ul className="space-y-2 mb-3">
            {open.map((l) => {
              const disabled = crop != null && l.commodity_id !== crop;
              const qty = formatNumber(l.quantity_qtl);
              return (
                <li key={l.id} className="rounded-xl border border-rule bg-paper p-3">
                  <label className={`flex items-center gap-3 ${disabled ? 'opacity-40' : ''}`}>
                    <input
                      type="checkbox"
                      disabled={disabled}
                      checked={picked.includes(l.id)}
                      onChange={(e) =>
                        setPicked(e.target.checked ? [...picked, l.id] : picked.filter((x) => x !== l.id))
                      }
                      className="rounded accent-accent"
                    />
                    <span className="text-sm font-medium">
                      {cropName(commodities.data?.find((c) => c.id === l.commodity_id), lang)}{' '}
                      <span className="tabular text-ink-2"><Trans>{qty} qtl</Trans></span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="space-y-3">
            <Field
              label={<Trans>Asking price for the pool (optional)</Trans>}
              inputMode="numeric"
              value={price}
              onChange={(e) => setPrice(e.target.value)}
              suffix={<Trans>₹ / quintal</Trans>}
            />
            <ErrorNote error={pool.error} />
            <Button
              className="w-full rounded-xl"
              style={picked.length >= 2 ? { background: 'var(--color-accent)', color: 'white', border: 'none' } : {}}
              disabled={picked.length < 2 || pool.isPending}
              onClick={() => pool.mutate(undefined)}
            >
              <Trans>Pool {picked.length} lots ({totalLabel} qtl)</Trans>
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
