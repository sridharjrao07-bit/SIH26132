# Frontend Design — Phase 3: Pages & Component Tree (APPROVED 2026-09-24)

Decisions:
1. **Verdict chip above the fold is kept.** `<VerdictChip>` (in `<PriceHeadline>`) and `<SaleWindowCard>` both read the **same `action` field from the same `['saleWindow',c,m,lang]` query**. The verdict is never derived or computed on the client.
2. **Today = one saved pair**, with the store designed for many: `prefs.pinnedPairs: Pair[]`, and Today renders only `[0]`. The Board tab covers the multi-crop overview. A pinned list can come after the demo if farmers ask for it.
3. **G7** was fixed by migration `037_headlines_require_approved.sql` (on `arena/01a0cef3-sih26132`, not yet on main). `<ReasonText>` renders `reason` as-is.
   - **Headline content can only ever appear in the `en` reason.** For `lang=mr|hi`, `apply_sale_language()` rebuilds `reason` entirely from `reason_code` templates and discards the English string, headlines included. This is structural: **there are no Marathi or Hindi headline templates, and there are not supposed to be.** Localizers should not go looking for them. The same applies to the better-market sentence, so in mr/hi `<BetterMarketCard>` is the only place a better mandi is surfaced.
   - Corollaries (verified 2026-09-24): (a) the pre-037 G7 exposure was limited to the English surface (the `lang=en` API and SMS replies). (b) A **Marathi demo is headline-free by design**, so the "approve a seed event?" decision only arises for an English demo segment.

Pages: `/` Today · `/c/:crop/m/:market` Crop detail · `/bhav` Board · `/compare/:crop` · `/forecasts/about` · `/setup` · `/alerts` (auth) · marketplace (phase 2, thin).
The component tree is as proposed in the Phase 3 chat record. `PairView` has compact and full variants and uses `PairHealthGate` for the ok / aging / stale / insufficient_data / no_prices states.
