// Full farmer journey (API_CONTRACT §4.1) against the running mock, through the real API layer,
// then a render of each signed-in screen. Skipped if the mock is down.
import { beforeAll, describe, expect, test } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { I18nProvider } from '@lingui/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from '@tanstack/react-router';
import { i18n } from '@lingui/core';
type ComponentType = () => React.ReactNode;
import { account, alerts, marketplace } from '../api/index.ts';
import { ApiError } from '../api/errors.ts';
import { devSignIn, useSession } from '../auth/session.ts';
import { AlertsPage } from '../features/alerts/AlertsPage.tsx';
import { LotsPage } from '../features/sell/LotsPage.tsx';
import { LotDetailPage } from '../features/sell/LotDetailPage.tsx';
import { AccountPage } from '../features/account/AccountPage.tsx';
import { BuyPage } from '../features/buy/BuyPage.tsx';

const BASE = 'http://127.0.0.1:8000';
const ONION = '22222222-2222-2222-2222-222222222201';
const LASALGAON = '11111111-1111-1111-1111-111111111101';
const mockUp = await fetch(`${BASE}/health`).then((r) => r.ok).catch(() => false);
if (process.env.REQUIRE_MOCK === '1' && !mockUp) throw new Error('REQUIRE_MOCK=1 but the mock API is not reachable on :8000');

function renderAt(path: string, routes: Record<string, ComponentType>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRootRoute();
  const children = Object.entries(routes).map(([p, C]) => createRoute({ getParentRoute: () => root, path: p, component: C }));
  for (const p of ['/', '/sell/new', '/forecasts/about', '/buy', '/sell', '/account', '/sell/$lotId']) {
    if (!routes[p]) children.push(createRoute({ getParentRoute: () => root, path: p, component: () => null }));
  }
  const router = createRouter({ routeTree: root.addChildren(children), history: createMemoryHistory({ initialEntries: [path] }) });
  return render(<QueryClientProvider client={qc}><I18nProvider i18n={i18n}><RouterProvider router={router} /></I18nProvider></QueryClientProvider>);
}

describe.skipIf(!mockUp)('marketplace against the mock', () => {
  let lotId = '';
  beforeAll(async () => { await fetch(`${BASE}/__dev/reset`); await devSignIn('farmer'); });

  test('signed out: auth endpoints fail with an auth error before any request', async () => {
    const saved = useSession.getState();
    useSession.getState()._set(null);
    await expect(account.me()).rejects.toMatchObject({ kind: 'auth' });
    useSession.setState(saved);
  });

  test('farmer: list → advice → matches → offer → accept → pay → ledger', async () => {
    const me = await account.me();
    expect(me.role).toBe('farmer');

    const lot = await marketplace.createLot({ commodity_id: ONION, market_id: LASALGAON, quantity_qtl: 40, grade: 'FAQ', asking_price: 2300 });
    lotId = lot.id;
    expect(lot.status).toBe('open');

    const advice = await marketplace.advice(lot.id, 'mr');
    expect(['SELL_NOW', 'HOLD', 'WAIT']).toContain(advice.action);
    expect(advice.action_label.length).toBeGreaterThan(0);

    const m = await marketplace.matches(lot.id);
    expect(m.matches.length).toBeGreaterThan(0);
    expect(m.matches.every((x) => x.verified)).toBe(true);        // unverified buyers never appear

    const offer = await marketplace.createOffer({ lot_id: lot.id, buyer_id: m.matches[0].buyer_id, price_per_qtl: 2350, quantity_qtl: 40 });
    expect(offer.status).toBe('pending');
    expect(offer.expires_at).toBeTruthy();                        // computed by the API, not us
    expect((await marketplace.lot(lot.id)).status).toBe('offered');

    await marketplace.decideOffer(offer.id, 'accepted');
    expect((await marketplace.lot(lot.id)).status).toBe('matched');

    const pay = await marketplace.createPayment({ offer_id: offer.id, amount: 2350 * 40 });
    await marketplace.markPayment(pay.id, 'paid');
    expect((await marketplace.lot(lot.id)).status).toBe('sold');   // paid closes the lot atomically

    const ledger = await marketplace.ledger(lot.id);
    const types = ledger.events.map((e) => e.type);
    expect(types[0]).toBe('lot_created');
    expect(types).toContain('offer_accepted');
    expect(types).toContain('payment_paid');
  });

  test('errors: invalid transition is a 409 with the server message; 422 maps to fields', async () => {
    const e1 = await marketplace.withdrawLot(lotId).catch((e) => e);
    expect(e1).toBeInstanceOf(ApiError);
    expect(e1.kind).toBe('conflict');
    const e2 = await marketplace.createLot({ commodity_id: ONION, quantity_qtl: 0, grade: 'General' }).catch((e) => e);
    expect(e2.kind).toBe('validation');
    expect(e2.fields.quantity_qtl).toBeTruthy();
  });

  test('alerts: create, pause (only the touched field), delete', async () => {
    const a = await alerts.create({ commodity_id: ONION, market_id: null, threshold_price: 2600, condition: 'gte' });
    expect(a.market_id).toBeNull();
    const paused = await alerts.update(a.id, { active: false });
    expect(paused.active).toBe(false);
    expect(paused.threshold_price).toBe(2600);                     // omitted = unchanged
    await alerts.remove(a.id);
    expect((await alerts.list()).find((x) => x.id === a.id)).toBeUndefined();
  });

  test('screens render signed in', async () => {
    await alerts.create({ commodity_id: ONION, market_id: LASALGAON, threshold_price: 2600, condition: 'gte' });
    const cases: [string, Record<string, ComponentType>, RegExp][] = [
      ['/alerts', { '/alerts': AlertsPage }, /2,600/],
      ['/sell', { '/sell': LotsPage }, /40/],
      [`/sell/${lotId}`, { '/sell/$lotId': LotDetailPage }, /₹2,350/],
      ['/account', { '/account': AccountPage }, /Ramesh Patil|Dev User/],
      ['/buy', { '/buy': BuyPage }, /./],
    ];
    for (const [path, routes, expected] of cases) {
      const { container, unmount } = renderAt(path, routes);
      await waitFor(() => {
        const html = container.innerHTML;
        expect(html.includes('value="Ramesh Patil"') || expected.test(container.textContent ?? '')).toBe(true);
      }, { timeout: 8000 });
      expect(container.textContent).not.toMatch(/[०-९]/);        // Latin digits everywhere
      unmount();
    }
  });
});
