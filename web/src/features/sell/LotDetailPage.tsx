import { useState } from 'react';
import { Link, useParams } from '@tanstack/react-router';
import { useQuery } from '@tanstack/react-query';
import { Trans, useLingui } from '@lingui/react/macro';
import { useLingui as useLinguiRuntime } from '@lingui/react';
import { RequireAuth } from '../../auth/RequireAuth.tsx';
import { marketplace } from '../../api/index.ts';
import { ApiError } from '../../api/errors.ts';
import type { Lot, LotAdvice, Match, Offer, Payment } from '../../api/schemasMarket.ts';
import {
  adviceQuery, buyersQuery, facilitiesQuery, grievancesQuery, ledgerQuery, lotQuery, matchesQuery,
  offersQuery, paymentsQuery, storageBookingsQuery, useAuthMutation,
} from '../../queries/auth.ts';
import { commoditiesQuery } from '../../queries/index.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { cropName } from '../price-detail/PairView.tsx';
import { formatDateTime, formatINR, formatNumber } from '../../domain/format.ts';
import { VERDICT_BG, VERDICT_TEXT } from '../sale-window/verdict.ts';
import { Button, ErrorNote, Field, NativeSelect, numOrUndef } from '../../ui/Form.tsx';
import { Section } from '../../ui/Section.tsx';
import { Block } from '../../ui/Skeleton.tsx';
import {
  BOOKING_STATUS, BUYER_TYPE, GRIEVANCE_CATEGORY, GRIEVANCE_STATUS, LEDGER_EVENT, LOT_STATUS, MATCH_REASON,
  OFFER_STATUS, PAYMENT_STATUS, label,
} from './labels.ts';

export function LotDetailPage() {
  const { t } = useLingui();
  const { lotId } = useParams({ from: '/sell/$lotId' });
  return (
    <RequireAuth why={t`Selling needs an account so buyers' offers reach you and every step is recorded.`}>
      {() => <LotDetail lotId={lotId} />}
    </RequireAuth>
  );
}

const STEPS = ['open', 'offered', 'matched', 'sold'] as const;
const canTrade = (l: Lot) => l.status === 'open' || l.status === 'offered';

function LotDetail({ lotId }: { lotId: string }) {
  const { _ } = useLinguiRuntime();
  const lang = usePrefs((s) => s.lang);
  const lot = useQuery(lotQuery(lotId));
  const commodities = useQuery(commoditiesQuery());
  const withdraw = useAuthMutation(() => marketplace.withdrawLot(lotId));
  const { t } = useLingui();

  if (lot.isPending) return <div className="p-4"><Block h={240} /></div>;
  if (lot.isError) {
    // 404 = gone or not yours (§6): an empty state, never "permission denied"
    return (
      <div className="px-4 py-6">
        {lot.error instanceof ApiError && lot.error.kind === 'not_found'
          ? <p><Trans>This lot was not found.</Trans></p> : <ErrorNote error={lot.error} />}
        <Link to="/sell" className="tap inline-flex items-center underline underline-offset-4"><Trans>‹ My produce</Trans></Link>
      </div>
    );
  }
  const l = lot.data;
  const crop = cropName(commodities.data?.find((c) => c.id === l.commodity_id), lang);
  const qty = formatNumber(l.quantity_qtl);
  const stepIdx = STEPS.indexOf(l.status as (typeof STEPS)[number]);

  return (
    <div className="mx-auto max-w-2xl">
      <div className="px-4 pt-3">
        <Link to="/sell" className="tap inline-flex items-center text-sm text-ink-2"><Trans>‹ My produce</Trans></Link>
        <h1 className="text-lg font-semibold">{crop} · <span className="tabular"><Trans>{qty} qtl</Trans></span></h1>
        <p className="text-sm text-ink-2">
          <Trans>Grade {l.grade}</Trans>
          {l.asking_price != null && <> · <span className="tabular"><Trans>asking {formatINR(l.asking_price)}</Trans></span></>}
        </p>
        {/* Forward-only progress (§5 state machine). Withdrawn is a side exit, shown as text. */}
        {l.status === 'withdrawn' ? (
          <p className="mt-2 text-sm font-semibold">{_(label(LOT_STATUS, 'withdrawn'))}</p>
        ) : (
          <ol className="mt-3 grid grid-cols-4 gap-1 text-xs" aria-label={t`Progress`}>
            {STEPS.map((s, i) => (
              <li key={s} aria-current={i === stepIdx ? 'step' : undefined}>
                <span className={`block h-1 ${i <= stepIdx ? 'bg-ink' : 'bg-rule'}`} />
                <span className={`mt-1 block ${i === stepIdx ? 'font-semibold' : 'text-ink-2'}`}>{_(label(LOT_STATUS, s))}</span>
              </li>
            ))}
          </ol>
        )}
      </div>

      {l.status !== 'withdrawn' && l.status !== 'sold' && <AdviceBlock lot={l} />}
      <OffersBlock lot={l} />
      {canTrade(l) && <BuyersBlock lot={l} />}
      <ComplaintBlock lot={l} />
      <LedgerBlock lotId={l.id} />

      {canTrade(l) && (
        <div className="px-4 py-4">
          <ErrorNote error={withdraw.error} />
          <Button variant="secondary" className="w-full" disabled={withdraw.isPending}
            onClick={() => { if (window.confirm(t`Withdraw this lot? This cannot be undone.`)) withdraw.mutate(undefined); }}>
            <Trans>Withdraw lot</Trans>
          </Button>
        </div>
      )}
    </div>
  );
}

/** THE PRODUCT (§4.1 step 4): server-decided action + localised reason + next step. */
function AdviceBlock({ lot }: { lot: Lot }) {
  const lang = usePrefs((s) => s.lang);
  const advice = useQuery(adviceQuery(lot.id, lang));
  if (advice.isPending) return <Section><Block h={120} /></Section>;
  if (advice.isError) return <Section><ErrorNote error={advice.error} /></Section>;
  const a = advice.data;
  return (
    <>
      <Section title={<Trans>Advice for this lot</Trans>}>
        <div className="flex gap-3">
          <span aria-hidden className={`w-[3px] shrink-0 ${VERDICT_BG[a.action]}`} />
          <div>
            <p className={`text-xl font-semibold ${VERDICT_TEXT[a.action]}`}>{a.action_label}</p>
            <p className="mt-1 text-base">{a.reason}</p>
            {a.next_step && <p className="mt-2 text-sm font-semibold"><Trans>Next:</Trans> {a.next_step}</p>}
          </div>
        </div>
      </Section>
      {canTrade(lot) && (a.suggested_transport.length > 0 || a.bookings.length > 0) && <TransportBlock lot={lot} advice={a} />}
      {canTrade(lot) && a.action === 'HOLD' && <StorageBlock lot={lot} />}
    </>
  );
}

function TransportBlock({ lot, advice }: { lot: Lot; advice: LotAdvice }) {
  const { _ } = useLinguiRuntime();
  const book = useAuthMutation((id: string) => marketplace.bookTransport({ lot_id: lot.id, logistics_id: id, quantity_qtl: lot.quantity_qtl }));
  const booked = new Set(advice.bookings.map((b) => b.logistics_id));
  return (
    <Section title={<Trans>Transport</Trans>}>
      {advice.bookings.map((b) => (
        <p key={b.id} className="text-sm"><span className="font-semibold">{b.option_name ?? <Trans>Booking</Trans>}</span> · {_(label(BOOKING_STATUS, b.status))}</p>
      ))}
      <ul className="-mx-4">
        {advice.suggested_transport.filter((o) => !booked.has(o.id)).map((o) => {
          const rate = o.rate_per_qtl != null ? formatINR(o.rate_per_qtl) : null;
          return (
            <li key={o.id} className="rule-t flex items-center justify-between gap-3 px-4 py-2">
              <div>
                <p className="font-semibold">{o.name}</p>
                {rate && <p className="tabular text-sm text-ink-2"><Trans>{rate} per quintal</Trans></p>}
              </div>
              <Button variant="secondary" className="text-sm" disabled={book.isPending} onClick={() => book.mutate(o.id)}><Trans>Book</Trans></Button>
            </li>
          );
        })}
      </ul>
      {/* 409 = capacity full: the server message states available vs used (§4.4) */}
      <ErrorNote error={book.error} />
    </Section>
  );
}

function StorageBlock({ lot }: { lot: Lot }) {
  const { _ } = useLinguiRuntime();
  const district = usePrefs((s) => s.district);
  const facilities = useQuery(facilitiesQuery(district));
  const bookings = useQuery(storageBookingsQuery(lot.id));
  const book = useAuthMutation((id: string) => marketplace.bookStorage({ lot_id: lot.id, facility_id: id, quantity_qtl: lot.quantity_qtl }));
  const active = (bookings.data ?? []).filter((b) => b.status === 'requested' || b.status === 'confirmed');
  return (
    <Section title={<Trans>Storage to hold your produce</Trans>}>
      {active.map((b) => {
        const name = facilities.data?.find((f) => f.id === b.facility_id)?.name;
        return <p key={b.id} className="text-sm"><span className="font-semibold">{name ?? <Trans>Storage</Trans>}</span> · {_(label(BOOKING_STATUS, b.status))}</p>;
      })}
      {active.length === 0 && (
        <ul className="-mx-4">
          {(facilities.data ?? []).slice(0, 4).map((f) => {
            const rate = f.rate_per_qtl != null ? formatINR(f.rate_per_qtl) : null;
            return (
              <li key={f.id} className="rule-t flex items-center justify-between gap-3 px-4 py-2">
                <div>
                  <p className="font-semibold">{f.name}</p>
                  {rate && <p className="tabular text-sm text-ink-2"><Trans>{rate} per quintal</Trans></p>}
                </div>
                <Button variant="secondary" className="text-sm" disabled={book.isPending} onClick={() => book.mutate(f.id)}><Trans>Book</Trans></Button>
              </li>
            );
          })}
        </ul>
      )}
      {/* Storage over capacity is a 400 (transport's is 409): same message either way (§9.3) */}
      <ErrorNote error={book.error} />
    </Section>
  );
}

function hoursLeft(iso: string | null) {
  if (!iso) return null;
  return Math.max(0, Math.round((Date.parse(iso) - Date.now()) / 3_600_000));
}

function OffersBlock({ lot }: { lot: Lot }) {
  const offers = useQuery(offersQuery());
  const buyers = useQuery(buyersQuery());
  const mine = (offers.data ?? []).filter((o) => o.lot_id === lot.id);
  if (offers.isPending) return null;
  if (offers.isError) return <Section><ErrorNote error={offers.error} /></Section>;
  if (mine.length === 0) return null;
  const buyerName = (id: string) => buyers.data?.find((b) => b.id === id)?.name;
  return (
    <Section title={<Trans>Offers</Trans>}>
      <ul className="-mx-4">{mine.map((o) => <OfferRow key={o.id} offer={o} buyerName={buyerName(o.buyer_id)} />)}</ul>
    </Section>
  );
}

function OfferRow({ offer: o, buyerName }: { offer: Offer; buyerName?: string }) {
  const { _ } = useLinguiRuntime();
  const decide = useAuthMutation((s: 'accepted' | 'rejected') => marketplace.decideOffer(o.id, s));
  const h = hoursLeft(o.expires_at);
  const price = formatINR(o.price_per_qtl);
  const qty = formatNumber(o.quantity_qtl);
  const total = formatINR(o.price_per_qtl * o.quantity_qtl);
  return (
    <li className="rule-t px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{buyerName ?? <Trans>Buyer</Trans>}</p>
          <p className="tabular text-sm"><Trans>{price}/qtl × {qty} qtl = {total}</Trans></p>
          <p className="text-xs text-ink-2">
            {_(label(OFFER_STATUS, o.status))}
            {o.status === 'pending' && h != null && <> · <Trans>expires in {h} h</Trans></>}
          </p>
        </div>
        {/* Only accepted/rejected are writable; "expired" is read-only (§9.2) */}
        {o.status === 'pending' && (
          <div className="flex shrink-0 flex-col gap-1">
            <Button className="text-sm" disabled={decide.isPending} onClick={() => decide.mutate('accepted')}><Trans>Accept</Trans></Button>
            <Button variant="secondary" className="text-sm" disabled={decide.isPending} onClick={() => decide.mutate('rejected')}><Trans>Reject</Trans></Button>
          </div>
        )}
      </div>
      <ErrorNote error={decide.error} />
      {o.status === 'accepted' && <PaymentBlock offer={o} />}
    </li>
  );
}

/** Settlement is mocked server-side (§9.9): we record status, we don't move money. */
function PaymentBlock({ offer }: { offer: Offer }) {
  const { _ } = useLinguiRuntime();
  const payments = useQuery(paymentsQuery());
  const [ref, setRef] = useState('');
  const pay = (payments.data ?? []).find((p) => p.offer_id === offer.id && p.status !== 'failed');
  const create = useAuthMutation(() => marketplace.createPayment({
    offer_id: offer.id, amount: offer.price_per_qtl * offer.quantity_qtl, ...(ref.trim() ? { reference: ref.trim() } : {}),
  }));
  const mark = useAuthMutation((to: 'paid' | 'failed' | 'disputed') => marketplace.markPayment(pay!.id, to));
  const amount = formatINR(offer.price_per_qtl * offer.quantity_qtl);

  if (payments.isPending) return null;
  return (
    <div className="mt-3 rounded border border-rule p-3">
      <p className="text-sm font-semibold"><Trans>Payment</Trans></p>
      {!pay ? (
        <div className="mt-2 space-y-2">
          <Field label={<Trans>Payment reference (optional)</Trans>} value={ref} onChange={(e) => setRef(e.target.value)} hint={<Trans>UPI or bank reference, if you have one.</Trans>} />
          <ErrorNote error={create.error} />
          <Button className="w-full text-sm" disabled={create.isPending} onClick={() => create.mutate(undefined)}><Trans>Record payment of {amount}</Trans></Button>
        </div>
      ) : (
        <PaymentStatus pay={pay} label={_(label(PAYMENT_STATUS, pay.status))} mark={mark} />
      )}
    </div>
  );
}

function PaymentStatus({ pay, label: statusLabel, mark }: {
  pay: Payment; label: string; mark: ReturnType<typeof useAuthMutation<'paid' | 'failed' | 'disputed', Payment>>;
}) {
  const lang = usePrefs((s) => s.lang);
  const amount = formatINR(pay.amount);
  return (
    <div className="mt-1">
      <p className="tabular text-sm">{amount} · {statusLabel}{pay.paid_at && <> · {formatDateTime(pay.paid_at, lang)}</>}</p>
      {pay.status === 'pending' && (
        <div className="mt-2 grid grid-cols-3 gap-1">
          <Button className="text-sm" disabled={mark.isPending} onClick={() => mark.mutate('paid')}><Trans>Received</Trans></Button>
          <Button variant="secondary" className="text-sm" disabled={mark.isPending} onClick={() => mark.mutate('failed')}><Trans>Failed</Trans></Button>
          <Button variant="secondary" className="text-sm" disabled={mark.isPending} onClick={() => mark.mutate('disputed')}><Trans>Dispute</Trans></Button>
        </div>
      )}
      <ErrorNote error={mark.error} />
    </div>
  );
}

function BuyersBlock({ lot }: { lot: Lot }) {
  const matches = useQuery(matchesQuery(lot.id));
  if (matches.isPending) return <Section><Block h={120} /></Section>;
  if (matches.isError) return <Section><ErrorNote error={matches.error} /></Section>;
  const m = matches.data;
  return (
    <Section title={<Trans>Buyers for this lot</Trans>}>
      {m.matches.length === 0 ? (
        // best_buyer may be null (§8): a real empty state
        <p className="text-sm text-ink-2">{m.advice || <Trans>No verified local buyer fits this lot yet.</Trans>}</p>
      ) : (
        <ul className="-mx-4">{m.matches.map((b, i) => <BuyerRow key={b.buyer_id} lot={lot} buyer={b} best={i === 0} />)}</ul>
      )}
    </Section>
  );
}

function BuyerRow({ lot, buyer: b, best }: { lot: Lot; buyer: Match; best: boolean }) {
  const { _ } = useLinguiRuntime();
  const [open, setOpen] = useState(false);
  const [price, setPrice] = useState(String(lot.asking_price ?? b.max_price ?? ''));
  const [qty, setQty] = useState(String(lot.quantity_qtl));
  const offer = useAuthMutation(() => marketplace.createOffer({
    lot_id: lot.id, buyer_id: b.buyer_id, price_per_qtl: numOrUndef(price) ?? 0, quantity_qtl: numOrUndef(qty) ?? 0,
  }), () => setOpen(false));
  const maxPrice = b.max_price != null ? formatINR(b.max_price) : null;
  const km = b.distance_km != null ? Math.round(b.distance_km) : null;

  return (
    <li className="rule-t px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-semibold">{b.buyer_name}{best && <span className="ml-2 text-xs font-semibold text-ink-2"><Trans>Best fit</Trans></span>}</p>
          <p className="text-sm text-ink-2">
            {_(label(BUYER_TYPE, b.buyer_type))}
            {b.district && <> · {b.district}</>}
            {km != null && <> · <span className="tabular">{km} km</span></>}
          </p>
          {maxPrice && <p className="tabular text-sm"><Trans>Pays up to {maxPrice}/qtl</Trans></p>}
          <p className="mt-1 text-xs text-ink-2">{b.reasons.map((r) => _(label(MATCH_REASON, r))).join(' · ')}</p>
        </div>
        {!open && <Button variant="secondary" className="shrink-0 text-sm" onClick={() => setOpen(true)}><Trans>Offer</Trans></Button>}
      </div>
      {open && (
        <form className="mt-3 space-y-2" onSubmit={(e) => { e.preventDefault(); offer.mutate(undefined); }}>
          <div className="grid grid-cols-2 gap-2">
            <Field label={<Trans>Price</Trans>} inputMode="numeric" required value={price} onChange={(e) => setPrice(e.target.value)} suffix="₹" />
            <Field label={<Trans>Quantity</Trans>} inputMode="decimal" required value={qty} onChange={(e) => setQty(e.target.value)} suffix={<Trans>qtl</Trans>} />
          </div>
          <p className="text-xs text-ink-2"><Trans>The offer stays open for 48 hours.</Trans></p>
          <ErrorNote error={offer.error} />
          <div className="grid grid-cols-2 gap-2">
            <Button type="submit" className="text-sm" disabled={offer.isPending || !numOrUndef(price) || !numOrUndef(qty)}><Trans>Send offer</Trans></Button>
            <Button type="button" variant="secondary" className="text-sm" onClick={() => setOpen(false)}><Trans>Cancel</Trans></Button>
          </div>
        </form>
      )}
    </li>
  );
}

const CATEGORIES = ['payment', 'quality', 'logistics', 'buyer', 'other'] as const;

function ComplaintBlock({ lot }: { lot: Lot }) {
  const { _ } = useLinguiRuntime();
  const lang = usePrefs((s) => s.lang);
  const list = useQuery(grievancesQuery());
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<(typeof CATEGORIES)[number]>('payment');
  const [text, setText] = useState('');
  const create = useAuthMutation(() => marketplace.createGrievance({ category, description: text.trim(), lot_id: lot.id }),
    () => { setOpen(false); setText(''); });
  const mine = (list.data ?? []).filter((g) => g.lot_id === lot.id);

  return (
    <Section title={<Trans>Problems</Trans>} aside={!open && <Button variant="quiet" className="text-sm" onClick={() => setOpen(true)}><Trans>Report a problem</Trans></Button>}>
      {mine.map((g) => (
        <p key={g.id} className="text-sm">
          <span className="font-semibold">{_(label(GRIEVANCE_CATEGORY, g.category))}</span> · {_(label(GRIEVANCE_STATUS, g.status))}
          {g.created_at && <span className="text-ink-2"> · {formatDateTime(g.created_at, lang)}</span>}
          <span className="block text-ink-2">{g.description}</span>
        </p>
      ))}
      {!open && mine.length === 0 && <p className="text-sm text-ink-2"><Trans>No problems reported.</Trans></p>}
      {open && (
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); create.mutate(undefined); }}>
          <NativeSelect label={<Trans>What is the problem about?</Trans>} value={category} onChange={(v) => setCategory(v as (typeof CATEGORIES)[number])}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{_(label(GRIEVANCE_CATEGORY, c))}</option>)}
          </NativeSelect>
          <label className="block">
            <span className="text-sm font-semibold"><Trans>Describe it</Trans></span>
            <textarea value={text} onChange={(e) => setText(e.target.value)} minLength={5} maxLength={2000} required rows={3}
              className="mt-1 w-full rounded border border-rule bg-paper px-3 py-2 text-base" />
          </label>
          <ErrorNote error={create.error} />
          <div className="grid grid-cols-2 gap-2">
            <Button type="submit" className="text-sm" disabled={create.isPending || text.trim().length < 5}><Trans>Send</Trans></Button>
            <Button type="button" variant="secondary" className="text-sm" onClick={() => setOpen(false)}><Trans>Cancel</Trans></Button>
          </div>
        </form>
      )}
    </Section>
  );
}

/** Transparency ledger: pre-sorted merged timeline, rendered as-is (§8 LotLedger). */
function LedgerBlock({ lotId }: { lotId: string }) {
  const { _ } = useLinguiRuntime();
  const lang = usePrefs((s) => s.lang);
  const ledger = useQuery(ledgerQuery(lotId));
  if (ledger.isPending) return <Section><Block h={80} /></Section>;
  if (ledger.isError) return <Section><ErrorNote error={ledger.error} /></Section>;
  return (
    <Section title={<Trans>Record of this lot</Trans>}>
      <ol className="relative ml-1 border-l border-rule">
        {ledger.data.events.map((e, i) => {
          const d = e.detail as { price_per_qtl?: number; amount?: number; quantity_qtl?: number };
          const money = d.amount ?? d.price_per_qtl;
          return (
            <li key={i} className="relative pb-3 pl-4 last:pb-0">
              <span aria-hidden className="absolute top-2 -left-[5px] size-[9px] rounded-full border border-ink bg-paper" />
              <p className="text-sm font-semibold">{_(label(LEDGER_EVENT, e.type))}
                {money != null && <span className="tabular font-normal"> · {formatINR(money)}{d.price_per_qtl != null && d.amount == null ? '/qtl' : ''}</span>}
              </p>
              {e.at && <p className="text-xs text-ink-2">{formatDateTime(e.at, lang)}</p>}
            </li>
          );
        })}
      </ol>
    </Section>
  );
}
