# Frontend Design — Phase 5: API Service Layer (APPROVED 2026-09-24)

Reference implementation: [`reference/`](reference/). It type-checks under `strict` + `erasableSyntaxOnly`, has 7 unit tests, and a smoke test that runs against `frontend_handoff/mock/mock_api.py`.

## Layers (dependencies point downward only)

```
features/*  (components)         useQuery(pairChartQuery(...))   never calls fetch
   │
queries/    (TanStack options)   keys, staleTime, select → domain
   │
domain/     (pure TS)            toDailyRows · selectLatestRun · buildChartSeries · pairHealth · format
   │
api/endpoints/*                  one function per route, typed params → validated rows
   │
api/client.ts + schemas.ts       fetch, auth, timeout, abort, 401-refresh-once, Valibot, normalizeApiError
```

- Components never see raw API rows. `select` turns them into view models.
- The domain layer has no React and no fetch, so it's unit-testable and mirrors the backend rules.
- Every response is validated. A shape change (G10-style drift) becomes `ApiError{kind:'contract'}` instead of rendering `undefined`.

## Query options (sketch for the frontend repo)

```ts
// queries/keys.ts
export const qk = {
  history:  (m: string, c: string, days: number) => ['prices', 'history', m, c, days] as const,
  forecast: (m: string, c: string)               => ['forecasts', m, c] as const,
  summary:  ()                                    => ['forecasts', 'summary'] as const,
  sale:     (c: string, m: string | null, lang: Lang) => ['saleWindow', c, m, lang] as const,
};

// queries/pairChart.ts
const FIVE_MIN = 5 * 60_000;
export const historyQuery = (p: PairParams, days: number) => queryOptions({
  queryKey: qk.history(p.marketId, p.commodityId, days),
  queryFn: ({ signal }) => prices.historical({ ...p, days }, signal),
  select: toDailyRows,                       // G1, memoised per query
  staleTime: FIVE_MIN,
  retry: (n, e) => e instanceof ApiError && e.retryable && n < 2,
});
export const forecastQuery = (p: PairParams) => queryOptions({
  queryKey: qk.forecast(p.marketId, p.commodityId),
  queryFn: ({ signal }) => forecasts.forPair(p, signal),
  select: selectLatestRun,
  staleTime: FIVE_MIN,
});

// features/price-detail/usePairChart.ts
export function usePairChart(p: PairParams, days: number) {
  const [h, f] = useQueries({ queries: [historyQuery(p, days), forecastQuery(p)] });
  const series = useMemo(
    () => (h.data ? buildChartSeries(h.data, f.data ?? [], istToday()) : null),
    [h.data, f.data],
  );
  // The forecast failing must not blank the history chart; PairHealthGate decides the notice.
  return { series, isLoading: h.isPending, historyError: h.error, forecastError: f.error };
}
```

Changing range from 30 to 90 days changes only the history key, so the forecast stays cached. Changing the pair aborts in-flight requests through `signal`.

## Verified output (mock at `arena/01a0cef3-sih26132` @ 6ae008b, after the S1 and S2 fixes)

```
rawRows 36 · multiRowDays 5 → dailyPoints 31 · horizonDays 7 · points 38
lastActual 2026-09-24 · hasGap false · method feature_ols · confidence medium
error path: 422 → ApiError{kind:'validation', fields:{commodity_id:'field required'}}
```

`npm run smoke` now **asserts invariants** instead of relying on the numbers above:
- one point per day, in order
- multi-row days resolved to `data_gov_in`
- one run per response
- `horizonDays` equals the number of forecast points

Seeded random values like `changePct` may differ between mock versions and are not regressions.
Earlier output (`horizonDays: 6`, today's forecast dropped) came from the pre-S1 mock and is obsolete.

## Standing rules
- **Thresholds, model names/labels and accuracy copy come from the API** (G6 `thresholds` / `metrics` / `progress`, forecast `method` / `model_version`). They are never constants in the frontend.
- `selectLatestRun()` stays as a safety net even though S1 is fixed.
- "Actual wins" stays. It guards the last-actual vs. day-1 edge during data gaps.
