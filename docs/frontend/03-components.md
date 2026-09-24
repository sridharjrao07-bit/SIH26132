# Frontend Design — Phase 3: Pages & Component Tree (APPROVED 2026-09-24)

Decisions:
1. **Verdict chip above the fold is kept.** `<VerdictChip>` (in `<PriceHeadline>`) and `<SaleWindowCard>` both read the **same `action` field from the same `['saleWindow',c,m,lang]` query**. The verdict is never derived or computed on the client.
2. **Today = one saved pair**, with the store designed for many: `prefs.pinnedPairs: Pair[]`, and Today renders only `[0]`. The Board tab covers the multi-crop overview. A pinned list can come after the demo if farmers ask for it.
3. **G7** was fixed by migration `037_headlines_require_approved.sql` (on `arena/01a0cef3-sih26132`, not yet on main). `<ReasonText>` renders `reason` as-is.
   - Note: for `lang=mr|hi`, `apply_sale_language` rebuilds `reason` from `reason_code` templates, so headlines **and** the better-market sentence only appear in English. In Marathi, `<BetterMarketCard>` is the only place the better market is surfaced.

Pages: `/` Today · `/c/:crop/m/:market` Crop detail · `/bhav` Board · `/compare/:crop` · `/forecasts/about` · `/setup` · `/alerts` (auth) · marketplace (phase 2, thin).
The component tree is as proposed in the Phase 3 chat record. `PairView` has compact and full variants and uses `PairHealthGate` for the ok / aging / stale / insufficient_data / no_prices states.
