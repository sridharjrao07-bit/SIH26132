import { describe, expect, test, vi, afterEach } from 'vitest';
import { createApiClient } from '../api/client.ts';
import { directApi } from '../api/endpoints/direct.ts';

/**
 * Real response captured from POST /api/v1/direct/rupee on the Lasalgaon lane
 * (farm ₹2,226.39 -> retail ₹5,392, 2026-09-26), with the stage list trimmed to
 * two entries for brevity. The numbers are the engine's own output, so if the
 * schema stops matching the API this fails rather than silently rendering NaN.
 */
const RUPEE_FIXTURE = {
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
};

/** A client whose fetch is a spy returning `body`, so we can assert the request. */
function stub(body: unknown, init: { status?: number } = {}) {
  // Typed with parameters so `mock.calls` is `[string, RequestInit]`, not `[]`.
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) =>
    new Response(JSON.stringify(body), { status: init.status ?? 200, headers: { 'Content-Type': 'application/json' } }),
  );
  // The config key is `fetchImpl`, not `fetch`: passing the wrong name leaves the
  // client on globalThis.fetch and the spy is never called, so every assertion
  // below would vacuously pass against a real network request.
  return { fetch, api: directApi(createApiClient({ baseUrl: '', fetchImpl: fetch as unknown as typeof globalThis.fetch })) };
}

/** As `stub`, but with a bearer token, for the endpoints that write to the database. */
function authed(body: unknown, token = 'tok-123') {
  const { fetch } = stub(body);
  const authApi = directApi(createApiClient({
    baseUrl: '',
    fetchImpl: fetch as unknown as typeof globalThis.fetch,
    getToken: async () => token,
  }));
  return { fetch, api: authApi };
}

afterEach(() => vi.restoreAllMocks());

describe('direct.rupee: request shape', () => {
  test('sends snake_case — the API never sees camelCase', async () => {
    const { fetch, api } = stub(RUPEE_FIXTURE);
    await api.rupee({ farmPrice: 2226.39, retailPrice: 5392, commodity: 'Onion' });

    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ farm_price: 2226.39, retail_price: 5392, commodity: 'Onion' });
    // camelCase leaking through would be the bug this guards.
    expect(Object.keys(body).some((k) => /[A-Z]/.test(k))).toBe(false);
  });

  test('omits optional fields entirely rather than sending null', async () => {
    const { fetch, api } = stub(RUPEE_FIXTURE);
    await api.rupee({ farmPrice: 1, retailPrice: 2, commodity: 'Onion' });
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect('market' in body).toBe(false);
    expect('distance_km' in body).toBe(false);
    expect('chain' in body).toBe(false);
  });

  test('includes optional fields when supplied', async () => {
    const { fetch, api } = stub(RUPEE_FIXTURE);
    await api.rupee({
      farmPrice: 1, retailPrice: 2, commodity: 'Onion',
      market: 'Lasalgaon APMC', distanceKm: 72.8, region: 'MH',
    });
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.market).toBe('Lasalgaon APMC');
    expect(body.distance_km).toBe(72.8);
    expect(body.region).toBe('MH');
  });
});

describe('direct.rupee: response contract', () => {
  test('parses a real captured response and keeps every number', async () => {
    const { api } = stub(RUPEE_FIXTURE);
    const r = await api.rupee({ farmPrice: 2226.39, retailPrice: 5392, commodity: 'Onion' });

    expect(r.farmer_share_pct).toBe(48.1155);
    expect(r.avoidable_per_farm_qtl).toBe(2032.2147);
    expect(r.chain.stages).toHaveLength(2);
    expect(r.chain.stages[0].margin_take).toBe(156.6061);
    // Devanagari labels must survive as real characters, not escapes.
    expect(r.chain.stages[0].label_mr).toBe('गाव व्यापारी');
  });

  test('a missing headline field fails loudly instead of rendering NaN', async () => {
    const broken = structuredClone(RUPEE_FIXTURE) as Record<string, unknown>;
    delete broken.farmer_share_pct;
    const { api } = stub(broken);
    await expect(api.rupee({ farmPrice: 1, retailPrice: 2, commodity: 'Onion' })).rejects.toThrow(/unexpected response/);
  });

  test('a stage that is not an object fails loudly too', async () => {
    const broken = structuredClone(RUPEE_FIXTURE) as { chain: { stages: unknown[] } };
    broken.chain.stages[0] = 'village_aggregator';
    const { api } = stub(broken);
    await expect(api.rupee({ farmPrice: 1, retailPrice: 2, commodity: 'Onion' })).rejects.toThrow();
  });
});

describe('direct.trace: an unknown token is an answer, not an error', () => {
  test('404 resolves to null so the page can say "no such crate"', async () => {
    const { api } = stub({ detail: 'not found' }, { status: 404 });
    await expect(api.trace('NOPE')).resolves.toBeNull();
  });

  test('a known token resolves to the redacted record', async () => {
    const { api } = stub({
      trace_token: 'ABC123', commodity: 'vegetable', district: 'Nashik',
      quantity_qtl: 9.8, status: 'settled', created_at: '2026-09-26T10:00:00Z',
      consumer: null, farmer: null,
    });
    const r = await api.trace('ABC123');
    expect(r?.district).toBe('Nashik');
    expect(r?.quantity_qtl).toBe(9.8);
  });
});

describe('direct.plan: lot and demand mapping', () => {
  test('lots and demand are sent as snake_case arrays', async () => {
    const { fetch, api } = stub({ plan_id: 'DP-1', allocations: [], shipments: [], orders: [], summary: {} });
    await api.plan({
      lots: [{ lotId: 'L1', lat: 20.12, lon: 74.33, supplyQtl: 30, price: 2226 }],
      demand: [{ demandId: 'D1', lat: 19.99, lon: 73.79, demandQtl: 25, price: 3890 }],
      commodity: 'Onion',
      groupSize: 4,
    });
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.lots).toEqual([{ lot_id: 'L1', lat: 20.12, lon: 74.33, supply_qtl: 30, price: 2226 }]);
    expect(body.demand).toEqual([{ demand_id: 'D1', lat: 19.99, lon: 73.79, demand_qtl: 25, price: 3890 }]);
    expect(body.group_size).toBe(4);
  });

  test('commit sends the plan id and the safe default for if_absent', async () => {
    const { fetch, api } = authed({ plan_id: 'DP-1', allocations: [], shipments: [], orders: [], summary: {} });
    await api.commit({
      planId: 'DP-1',
      lots: [{ lotId: 'L1', lat: 20.12, lon: 74.33, supplyQtl: 30, price: 2226 }],
      demand: [{ demandId: 'D1', lat: 19.99, lon: 73.79, demandQtl: 25, price: 3890 }],
    });
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(init.body as string);
    expect(body.plan_id).toBe('DP-1');
    expect(body.if_absent).toBe('delta_exceeded');
  });

  test('commit attaches a bearer token, because a plan is written to the database', async () => {
    const { fetch, api } = authed({ plan_id: 'DP-1', allocations: [], shipments: [], orders: [], summary: {} });
    await api.commit({
      planId: 'DP-1',
      lots: [{ lotId: 'L1', lat: 20.12, lon: 74.33, supplyQtl: 30, price: 2226 }],
      demand: [{ demandId: 'D1', lat: 19.99, lon: 73.79, demandQtl: 25, price: 3890 }],
    });
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-123');
  });
});
