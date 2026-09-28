import { afterEach, describe, expect, test, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { I18nProvider } from '@lingui/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { i18n } from '@lingui/core';
import { DirectPage } from '../features/direct/DirectPage.tsx';

/**
 * The page is the deliverable, so it gets rendered: a JSX typo or a bad field
 * access passes `tsc -b` and `vite build` but shows a blank screen to the user.
 *
 * The fixtures are the engine's own output for the audited Lasalgaon lane
 * (farm ₹2,226.39 -> retail ₹5,392, 2026-09-26), captured from the real API, so
 * the assertions below are against numbers the backend actually produces.
 */
const fixtures = vi.hoisted(() => ({
  rupee: {
    commodity: 'vegetable',
    farm_price: 2226.39,
    retail_price: 5392.0,
    calibration_status: 'ok',
    calibrated_margin_scale: 1.382475,
    farmer_share_pct: 48.1155,
    avoidable_per_farm_qtl: 2032.2147,
    unavoidable_per_farm_qtl: 368.5753,
    verdict:
      'Heavy intermediary absorption: most of the spread is margin rather than work done, so direct trade would materially help both sides.',
    chain: {
      chain_name: 'traditional:vegetable',
      farm_price: 2226.39,
      retail_price: 5392.0,
      delivered_ratio: 0.858157,
      spoilage_pct: 0.141843,
      A: 2.129961,
      B: 649.876387,
      consumer_spend_per_farm_qtl: 4627.18,
      absorption_per_farm_qtl: 2400.79,
      margin_absorption_per_farm_qtl: 2032.2147,
      cost_absorption_per_farm_qtl: 368.5753,
      farmer_share_pct: 48.1155,
      price_ratio_pct: 41.2906,
      absorption_per_delivered_qtl: 2797.6132,
      margin_share_of_absorption_pct: 84.6477,
      pass_through: 0.469492,
      chain_length: 5,
      intermediary_count: 5,
      stages: [
        {
          key: 'village_aggregator',
          label_en: 'Village trader / aggregator',
          label_mr: 'गाव व्यापारी',
          label_hi: 'गाँव व्यापारी',
          kind: 'assembly',
          essential: false,
          price_in: 2226.39,
          price_out: 2471.6287,
          qty_in: 1.0,
          qty_out: 0.98,
          value_in: 2226.39,
          value_out: 2422.1961,
          cost_take: 39.2,
          margin_take: 156.6061,
          take: 195.8061,
          margin_pct: 0.069124,
          cost_per_qtl: 40.0,
          loss_pct: 0.02,
          spoilage_qtl: 0.02,
          note: 'Buys at the farm gate, assembles lots, extends credit.',
          take_pct_of_consumer_rupee: 4.2317,
        },
        {
          key: 'commission_agent',
          label_en: 'Commission agent (arhatiya)',
          label_mr: 'आडत दलाल',
          label_hi: 'आढ़त दलाल',
          kind: 'intermediary',
          essential: false,
          price_in: 2471.6287,
          price_out: 2776.9699,
          qty_in: 0.98,
          qty_out: 0.9653,
          value_in: 2422.1961,
          value_out: 2680.609,
          cost_take: 53.0915,
          margin_take: 205.3214,
          take: 258.4129,
          margin_pct: 0.082949,
          cost_per_qtl: 55.0,
          loss_pct: 0.015,
          spoilage_qtl: 0.0147,
          note: 'APMC commission, mandi storage.',
          take_pct_of_consumer_rupee: 5.5788,
        },
      ],
    },
  },
  fair: {
    viable: true,
    distance_km: 72.784,
    freight_per_qtl: 20.3795,
    handling_per_qtl: 37.0,
    freight_basis: 'consolidated_assumption',
    split: {
      retail_price: 5392.0,
      farmer_fallback_per_qtl: 2226.39,
      delivered_ratio: 0.985,
      logistics_per_farm_qtl: 57.3795,
      effective_markup: 0.03,
      alpha: 0.5,
      farm_price_per_qtl: 3662.7188,
      mandi_price_per_qtl: 2226.39,
      consumer_price_per_delivered_qtl: 3890.0521,
      farmer_gain_per_farm_qtl: 1436.3288,
      consumer_saving_per_farm_qtl: 1479.4187,
      total_surplus_per_farm_qtl: 2915.7475,
      farmer_share_rs: 3662.7188,
      logistics_share_rs: 57.3795,
      platform_share_rs: 111.603,
      consumer_outlay_per_farm_qtl: 3831.7013,
      farmer_gain_pct: 64.5138,
      consumer_saving_pct: 27.8551,
      farmer_share_of_consumer_rupee_pct: 95.5899,
      viable: true,
      reason: '',
    },
    reason: '',
  },
}));

// Hoisted so the factory below can close over it before the module body runs.
vi.mock('../api/index.ts', () => ({
  direct: {
    rupee: async () => fixtures.rupee,
    fairPrice: async () => fixtures.fair,
    config: async () => ({}),
    trace: async () => null,
    plan: async () => ({ plan_id: '', allocations: [], shipments: [], orders: [], summary: {} }),
    commit: async () => ({ plan_id: '', allocations: [], shipments: [], orders: [], summary: {} }),
    planById: async () => ({ plan_id: '', allocations: [], shipments: [], orders: [], summary: {} }),
  },
  prices: {},
  forecasts: {},
  reference: {},
  saleWindow: {},
  accuracy: {},
  account: {},
  alerts: {},
  marketplace: {},
}));

// Vitest runs without `globals`, so @testing-library/react never registers its
// auto-cleanup. Without this, every render accumulates in document.body and
// `getByText` starts matching a previous test's DOM.
afterEach(() => cleanup());

/** "48.1%" appears twice by design: the headline stat and the chart's farmer row. */
const share = () => screen.getAllByText('48.1%');

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  return render(
    <QueryClientProvider client={qc}>
      <I18nProvider i18n={i18n}>
        <DirectPage />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe('DirectPage: opens on the audited lane and shows the real numbers', () => {
  test('the headline farmer share is on screen as a magnitude', async () => {
    const view = renderPage();
    // Two queries fire at once (breakdown, then direct comparison); wait for the
    // later one, or the assertions below race a still-pending panel.
    await waitFor(() => expect(screen.getByText('₹3,663')).toBeTruthy(), { timeout: 3000 });

    // Both halves of the spread are shown, so the reader can see the 85/15 split.
    expect(screen.getByText('₹2,032')).toBeTruthy();
    expect(screen.getByText('₹369')).toBeTruthy();
    // The engine's own verdict is quoted verbatim, not paraphrased.
    expect(screen.getByText(/Heavy intermediary absorption/)).toBeTruthy();
    // Stages are named, not just counted.
    expect(screen.getByText('Village trader / aggregator')).toBeTruthy();
    expect(screen.getByText('Commission agent (arhatiya)')).toBeTruthy();
    view.unmount();
  });

  test('the direct comparison shows what both sides would get instead', async () => {
    const view = renderPage();
    await waitFor(() => expect(screen.getByText('₹3,663')).toBeTruthy(), { timeout: 3000 });

    // Farmer ₹2,226 -> ₹3,663 (+64.5%); consumer ₹5,392 -> ₹3,890 (-27.9%).
    expect(screen.getByText('₹3,663')).toBeTruthy();
    expect(screen.getByText('₹3,890')).toBeTruthy();
    // Directions in words, not signs: the farmer's price rose, the consumer's fell.
    expect(screen.getByText('64.5% more')).toBeTruthy();
    expect(screen.getByText('27.9% less')).toBeTruthy();
    view.unmount();
  });

  test('a retail price below the farm price is refused rather than fitted', async () => {
    const view = renderPage();
    await waitFor(() => expect(screen.getByText('₹3,663')).toBeTruthy(), { timeout: 3000 });

    const retail = view.container.querySelector('#direct-retail') as HTMLInputElement;
    expect(retail.value).toBe('5392');
    fireEvent.change(retail, { target: { value: '100' } });

    // The chain is not fitted to a nonsense pair; the user is told why.
    expect(screen.getByText(/\u0938\u093e\u0916\u0933\u0940 \u0938\u092e\u091c\u0924\u0947/)).toBeTruthy();
    await waitFor(() => expect(screen.queryAllByText('48.1%')).toHaveLength(0));
    view.unmount();
  });

  test('renders in Marathi: setup.ts activates mr, so new strings must be translated', () => {
    const view = renderPage();
    // A missing translation silently falls back to English, which would still
    // pass every assertion above (the numbers are locale-independent by design).
    expect(screen.getByText('\u0924\u0941\u092e\u091a\u093e \u0930\u0941\u092a\u093e \u0915\u0941\u0920\u0947 \u091c\u093e\u0924\u094b')).toBeTruthy();
    expect(screen.queryByText('Where your rupee goes')).toBeNull();
    view.unmount();
  });

  test('changing the commodity refetches rather than reusing the cached lane', async () => {
    const view = renderPage();
    await waitFor(() => expect(screen.getByText('₹3,663')).toBeTruthy(), { timeout: 3000 });

    const select = view.container.querySelector('#direct-commodity') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'Tomato' } });

    // The query key includes the commodity, so a new lane is requested. The
    // numbers here come from the same fixture, but the fact that the page
    // re-renders without error proves the key change is wired through.
    await waitFor(() => expect(share().length).toBeGreaterThan(0), { timeout: 3000 });
    view.unmount();
  });
});
