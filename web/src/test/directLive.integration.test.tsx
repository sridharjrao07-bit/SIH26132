/**
 * DirectLink against the REAL backend, through the real API client.
 *
 * This is the check that was missing. The unit tests in direct.test.tsx assert
 * the shape the client *sends*; they cannot catch a field the backend *requires*
 * but the client never sends, because a stubbed fetch accepts anything. That is
 * exactly how `/plan` and `/group-buy` shipped broken — the client sent
 * `lots[].lot_id`, `demand` (singular) and `commodity`/`window`/`target_qtl`,
 * none of which the backend accepts, and every unit test still passed.
 *
 * It listens on its own port (8001 by default) so it does not fight the mock
 * integration tests, which expect the *mock* on 8000. Run it with:
 *
 *     DIRECT_API_BASE=http://127.0.0.1:8001 bash web/scripts/dev-backend.sh
 *     REQUIRE_DIRECT_API=1 npm test
 *
 * Skipped when nothing answers on that port. Set REQUIRE_DIRECT_API=1 to make
 * its absence a hard failure.
 */
import { describe, expect, test } from 'vitest';
import { createApiClient } from '../api/client.ts';
import { directApi } from '../api/endpoints/direct.ts';

const BASE = process.env.DIRECT_API_BASE ?? 'http://127.0.0.1:8001';
const apiUp = await fetch(`${BASE}/health`).then((r) => r.ok).catch(() => false);
if (process.env.REQUIRE_DIRECT_API === '1' && !apiUp) {
  throw new Error(`REQUIRE_DIRECT_API=1 but no API is reachable on ${BASE}`);
}

const direct = directApi(createApiClient({ baseUrl: BASE }));

describe.skipIf(!apiUp)('DirectLink against the live backend', () => {
  test('GET /direct/config returns calibration metadata', async () => {
    await expect(direct.config()).resolves.toBeTruthy();
  });

  test('POST /direct/rupee returns the audited Lasalgaon numbers', async () => {
    const r = await direct.rupee({
      farmPrice: 2226.39,
      retailPrice: 5392,
      commodity: 'Onion',
      market: 'Lasalgaon APMC',
    });
    // These are the independently audited figures. If the engine or the client
    // drifts, this fails rather than quietly showing a plausible wrong number.
    expect(r.farmer_share_pct).toBe(48.1155);
    expect(r.avoidable_per_farm_qtl).toBe(2032.2147);
    expect(r.unavoidable_per_farm_qtl).toBe(368.5753);
    expect(r.chain.stages).toHaveLength(5);
  });

  test('POST /direct/fair-price returns a surplus split that helps both sides', async () => {
    const r = await direct.fairPrice({
      farmPrice: 2226.39,
      retailPrice: 5392,
      originLat: 20.12,
      originLng: 74.33,
      destLat: 19.99,
      destLng: 73.79,
      quantityQtl: 25,
      commodity: 'Onion',
    });
    expect(r.split.farm_price_per_qtl).toBeGreaterThan(2226.39);
    expect(r.split.consumer_price_per_delivered_qtl).toBeLessThan(5392);
    expect(r.split.total_surplus_per_farm_qtl).toBeGreaterThan(0);
  });

  test('POST /direct/plan accepts the LotIn/DemandIn shapes and returns a plan', async () => {
    const r = await direct.plan({
      lots: [{
        id: 'L1', commodityId: 'c1', quantityQtl: 30, mandiPricePerQtl: 2226,
        lat: 20.12, lng: 74.33, farmerId: 'f1',
      }],
      demands: [{
        id: 'D1', commodityId: 'c1', quantityQtl: 25, retailPricePerQtl: 3890,
        lat: 19.99, lng: 73.79,
      }],
      alpha: 0.5,
    });
    // A 422 here means the client sent a field name the backend rejects — the
    // exact failure this file exists to catch.
    expect(r.allocations.length).toBeGreaterThan(0);
    expect(r.impact.surplus_rs).toBeGreaterThan(0);
    expect(r.impact.allocation_optimal).toBe(true);
    expect(r.shipments.length).toBeGreaterThan(0);
    // The freight block is nested, not flat on the shipment.
    expect(r.shipments[0].freight?.rate_basis).toBeTruthy();
  });

  test('POST /direct/group-buy accepts origin_lat/origin_lng + orders', async () => {
    const r = await direct.groupBuy({
      originLat: 19.99,
      originLng: 73.79,
      orders: [{ orderId: 'O1', qtl: 25, lat: 19.99, lng: 73.79 }],
      minLoadQtl: 20,
    });
    expect(r.viable).toBe(true);
    expect(r.freight_by_order.O1).toBeGreaterThan(0);
    expect(r.landed_cost_per_qtl).toBeGreaterThan(0);
  });

  test('GET /direct/trace on an unknown token resolves to null, not a throw', async () => {
    await expect(direct.trace('NOSUCHTOKEN')).resolves.toBeNull();
  });
});
