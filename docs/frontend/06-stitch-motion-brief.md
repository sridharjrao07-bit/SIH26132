# Frontend Elevation Brief — Stitch MCP + Motion (for the frontend agent)

> **Who this is for:** the agent that has the **Stitch MCP** connected. This is your
> spec. You generate/iterate visuals with Stitch, then **translate** the output into
> this repo's existing React code. Do **not** fork the design — enhance it.
>
> **Golden rule:** the product's one job is the **verdict** (Sell / Hold / Wait).
> Colour is reserved for that answer; everything else is calm ink-on-paper. Motion
> must *guide attention to the verdict and give feedback* — never decorate for its
> own sake. This ships to farmers on **₹2000 phones over weak 3G**, so every
> animation must be **transform/opacity only** and **cheap**.

---

## 1. Guardrails — do NOT break these (hard constraints)

These are load-bearing. Breaking any of them fails the demo or the product.

**Design tokens** (`web/src/styles/index.css`, `@theme`)
- The default Tailwind palette is **switched off** (`--color-*: initial`). Generic
  classes like `bg-blue-500` **do not exist and will not build**. Only these exist:
  `paper #F7F4EE`, `paper-2 #EFEAE0`, `ink #1A1916`, `ink-2 #57534A`, `rule #DDD6C8`,
  `sell #1A5C32`, `hold #6E4A03`, `wait #475059`, `forecast #2D5B88` (chart only),
  `arrivals #CBBFA9` (chart only), `white`.
- All text colours are **≥ 7:1** on paper. Any new text/background pair must stay ≥ 7:1.
- **No shadows** (`--shadow-*: initial`) and **no gradients**. Radii only `2px`/`4px`.
- Type floor is **14px** (`--text-xs`). Price headline is `--text-price` (40px).
- Utilities to reuse: `tabular`, `rule-b`, `rule-t`, `tap` (48px min-height).

**Behaviour you must preserve** (from `web/README.md` "Rules the code enforces")
- The **verdict comes from the API** (`sale-window.action`) — read once, chip and
  card read the same query. **Never compute it on the client.**
- Thresholds, model labels, coverage and accuracy come **from the API only**; the
  code never types a "95". Pending states ("Not measured yet") are **intended**.
- Forecast method is shown as the API's `method`; never labelled "GBM" unless it says so.
- Prices: **Latin digits, `en-IN` grouping, in every language**; months via `-u-nu-latn`.
- The verdict is the **only** coloured element; price deltas use ▲▼ in ink.
- Offers writable only as `accepted`/`rejected` (forward-only, no reopen).
- A 404 on an owner-only resource renders as **"not found"**, never "permission denied".
- PATCH forms send **only changed fields** (omitted = unchanged, `null` = clear).
- Other mandis come from `/prices/latest` + `/markets`, not `sale_window.nearby`.

**i18n** (`@lingui`) — all user-facing strings via `<Trans>`/`t\`\`` macro; Marathi is
default; run `npm run i18n:check` and commit regenerated catalogs.

**Tech** — TanStack Router (URL is state, survives refresh), React Query, Lingui,
Tailwind v4, Recharts, zustand prefs. **No new heavy dependency without approval**
(avoid framer-motion/GSAP; prefer CSS/Tailwind or a ≤3 kb helper).

**Gates that must stay green** (run before you hand back):
`npm run typecheck` · `npm run i18n:check` · `npm test` · `npm run build`.

---

## 2. The motion system (define once, reuse everywhere)

Add a small, consistent motion language. Put the tokens/keyframes in
`index.css` `@theme` so Tailwind v4 exposes `animate-*` utilities, and gate
everything behind `motion-safe:` / `motion-reduce:`.

**Token table**

| Purpose | Duration | Easing | Distance |
|---|---|---|---|
| press / tap feedback | 90ms | `cubic-bezier(0.4,0,0.2,1)` | scale 0.98 |
| micro (chip, icon) | 140ms | `cubic-bezier(0.16,1,0.3,1)` | 2–4px |
| reveal (cards, lists) | 220ms | `cubic-bezier(0.16,1,0.3,1)` (decel) | 8px up |
| transition (route, range) | 260ms | `cubic-bezier(0.4,0,0.2,1)` | 12px / fade |
| chart / hero | 320ms | `cubic-bezier(0.16,1,0.3,1)` | fade + 8px |

- **Stagger:** 40ms per item, **cap at 6 items / 240ms total** (never cascade a long list).
- **Compositor only:** animate `transform` and `opacity`. Never animate
  `width/height/top/left/margin` (layout thrash on low-end devices).

**Starter CSS to add to `index.css` (inside `@theme`)**

```css
/* motion tokens */
--animate-rise: rise 220ms cubic-bezier(0.16,1,0.3,1) both;
--animate-fade: fade 220ms cubic-bezier(0.16,1,0.3,1) both;
--animate-pop:  pop 140ms cubic-bezier(0.16,1,0.3,1) both;
--animate-slide-down: slide-down 260ms cubic-bezier(0.4,0,0.2,1) both;

@keyframes rise { from { opacity: 0; transform: translateY(8px) } to { opacity: 1; transform: none } }
@keyframes fade { from { opacity: 0 } to { opacity: 1 } }
@keyframes pop  { 0% { transform: scale(0.96) } 60% { transform: scale(1.02) } 100% { transform: scale(1) } }
@keyframes slide-down { from { opacity: 0; transform: translateY(-8px) } to { opacity: 1; transform: none } }

/* respect the OS setting — this is non-negotiable */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.001ms !important; animation-iteration-count: 1 !important; transition-duration: 0.001ms !important; }
}
```

**The motion vocabulary** (the only animations we ship — map each to a screen in §5)

1. **Verdict reveal (the hero):** `VerdictChip` + `SaleWindowCard` `animate-rise` on
   mount; the verdict word gets a one-shot `animate-pop`. `aria-live="polite"` on the
   verdict so screen readers announce it.
2. **Price change:** on the headline, a brief background pulse toward `paper-2`
   (opacity only) when the value changes; the ▲▼ stays ink.
3. **Chart:** the `<figure>` does `animate-fade` on load and on **range change**
   (key the container by range so it re-mounts). **Do not enable Recharts internal
   animation** — keep `isAnimationActive={false}` (tests + determinism depend on it).
   A "draw-in" is allowed only if it's a CSS opacity/transform on the wrapper and the
   `pairView.integration` test still passes.
4. **Route transitions:** subtle `animate-fade` on `<main>` content via TanStack
   Router; forward nav may add a 12px slide. Keep it ≤260ms.
5. **List enter:** other-mandis, matches, offers, alerts — `animate-rise` with the
   capped stagger above. Long lists: animate only the first 6.
6. **Buttons/controls:** `transition-transform active:scale-[0.98]` (90ms).
7. **Skeletons:** extend `ui/Skeleton.tsx` with a slow opacity pulse (reduced-motion →
   static `paper-2`). Use them for every async fetch (prices, advice, matches, offers).
8. **Offline banner + sync dot:** banner `animate-slide-down`; the `SyncStatus` dot
   pulses only while `fetching` (opacity), static otherwise.
9. **Bottom nav active indicator:** animated underline/dot that slides between tabs
   (transform). 
10. **Confirmations:** a tiny toast (`animate-rise`, bottom, above nav) for "Offer
    accepted", "Payment recorded", "Alert saved". Auto-dismiss ~2.5s, `role="status"`.

---

## 3. How to use Stitch MCP (your workflow)

1. **One screen at a time.** Compose each Stitch prompt as:
   `[role] + [design-tokens block from Appendix A] + [this screen's real content & states] + [the specific elevation goal]`.
   Always paste the **full token block** so Stitch stays on-palette.
2. **Generate → review against §1.** If Stitch emits gradients, shadows, big radii, or
   off-palette colours, reject and re-prompt with "use only the provided tokens; no
   gradients, no shadows, 2–4px radius."
3. **Translate** the accepted mockup into the existing components (§4). Stitch gives you
   *layout and visual direction*, not final code.
4. Work in batches of 2–3 screens; keep `npm run typecheck`/`test` green between batches.

**Stitch prompt template**
```
You are designing a screen for "Krishi Bazaar", a mobile-first (360px) PWA for
Indian farmers, Marathi-first. Aesthetic: calm editorial "paper" — off-white paper,
near-black ink, hairline rules, NO gradients, NO shadows, radius 2-4px, generous
whitespace. Colour is used ONLY for the verdict. Target low-end Android.

DESIGN TOKENS (use ONLY these): <paste Appendix A block>

SCREEN: <name>. Purpose: <one line>. Content & states: <fields + loading/empty/offline>.
Elevate: <e.g. "make the Sell/Hold/Wait verdict the clear hero with a subtle reveal
animation; show the forecast band with a method label; add skeletons for loading">.
Deliver the layout and the motion notes (what animates, trigger, ~duration).
```

---

## 4. Translation rules (Stitch output → this codebase)

- **Colour:** replace every generic Tailwind colour with the token (build fails otherwise).
- **Strip** gradients, box-shadows, rounded-xl+ → map to `rounded` (4px) / `rounded-sm`.
- **Reuse, don't fork:** wire into `VerdictChip`, `SaleWindowCard`, `BetterMarketCard`,
  `PairView`, `ModelChip`, `AccuracyCard`, `HealthNotice`, `ui/Section`, `ui/Form`,
  `ui/Select`, `ui/Skeleton`. Add new primitives only when nothing fits.
- **i18n every string** (`<Trans>`/macro); keep `en-IN` Latin-digit prices.
- **Keep data flow unchanged:** same React Query keys, verdict from the API, no client math.
- **Accessibility stays:** `:focus-visible` ring, 48px `tap` targets, `aria-live` on
  verdict/sync/offline, chart `figure` has an `aria-label`, colour never the only signal.
- **Preserve the "don't fix these" behaviours** in §1 verbatim.

---

## 5. Screen-by-screen specs (P0 → P2)

Legend: **Motion** = the vocabulary item(s) from §2. **States** = loading/empty/offline
you must handle with skeletons + copy.

**P0 — the demo path**
- **Today / `PairView`** (hero). Price headline (`--text-price`), verdict chip above the
  fold, forecast band, other mandis, as-of stamp. *Motion:* 1 (verdict reveal), 2 (price
  pulse), 3 (chart fade on load + range change). *States:* skeleton headline+chart;
  `PairHealthGate` ok/aging/stale/insufficient/no_prices already exist — style them.
- **`SaleWindowCard` + `VerdictChip` + `BetterMarketCard`.** The answer block. Verdict
  label is the typographic hero; reason text as-is from API; better-mandi is the only
  place a better mandi shows in mr/hi. *Motion:* 1, 10 (toast on accept elsewhere).
- **`PriceForecastChart` + arrivals strip + `ChartCaption` + `ModelChip` + `AccuracyCard`.**
  Keep `isAnimationActive={false}`. Caption shows method label + "likely range"; Accuracy
  card shows its **pending** state first. *Motion:* 3.
- **Setup.** 3 taps (lang/crop/mandi). Clear progress, big tap targets, selection = the
  token colour on the selected chip only. *Motion:* 6, 5.
- **Sell: `NewLotPage` → `LotDetailPage`.** Form (qty/grade/price) then advice + matches +
  offers + payment + ledger + transport/storage + complaints. *Motion:* 5, 6, 10, 7.

**P1 — supporting flow**
- **Alerts.** Create/pause/delete with optimistic UI + skeletons. *Motion:* 5, 6, 10.
- **Buy.** Register → "waiting for verification" → supply + offer. *Motion:* 5, 10.
- **Board `/bhav`.** Multi-crop overview rows with sparklines. *Motion:* 5, 3.
- **`AppShell`.** Bottom-nav active indicator (9), sync dot (8), offline banner (8),
  route fade (4). Header stays hairline-calm.

**P2 — polish**
- **Account**, **forecasts/about** (the "how it works / accuracy pending" story),
  empty/error microcopy consistency, dark-mode? (out of scope unless asked).

---

## 6. Acceptance criteria (definition of done)

- [ ] `npm run typecheck && npm run i18n:check && npm test && npm run build` all green.
- [ ] Looks right at **360px** and on a real phone (not just jsdom).
- [ ] **`prefers-reduced-motion: reduce`** removes all motion (verified in DevTools).
- [ ] New text/background pairs **≥ 7:1**; colour still only on the verdict.
- [ ] No new dependency >3 kb; bundle delta small; animations are transform/opacity only.
- [ ] Verdict still read from the API once; no invented accuracy numbers; offers forward-only.
- [ ] Every async surface has a skeleton + an empty/offline state.
- [ ] Rehearsal still passes: `python demo/journey_rehearsal.py` (22/22) — behaviour unchanged.

---

## 7. Prioritized backlog

- **P0:** motion tokens + reduced-motion CSS (§2); verdict reveal + price pulse + chart
  fade; skeletons for the Today/advice/matches path; Setup + Sell flow polish; toast.
- **P1:** list stagger; bottom-nav indicator; sync/offline motion; Alerts/Buy/Board polish.
- **P2:** Account/about polish; motion audit; perf pass.

---

## Appendix A — Design-token block (paste into every Stitch prompt)

```
Colours (ONLY these): paper #F7F4EE, paper-2 #EFEAE0, ink #1A1916, ink-2 #57534A,
rule #DDD6C8, sell(green) #1A5C32, hold(amber) #6E4A03, wait(slate) #475059,
forecast(blue, chart only) #2D5B88, arrivals(tan, chart only) #CBBFA9, white #FFFFFF.
Type: IBM Plex Sans + IBM Plex Sans Devanagari; sizes 14/15/17/20/28/40px; tabular
figures for numbers. Radius 2-4px. No shadows, no gradients. Hairline rules (#DDD6C8).
Verdict is the only coloured element; price deltas use ▲/▼ in ink. Mobile-first 360px,
48px tap targets, generous whitespace, calm editorial "paper" feel.
```

## Appendix B — Example Stitch prompt (Today screen)

```
You are designing the "Today" screen for Krishi Bazaar, a mobile-first (360px) PWA for
Indian farmers, Marathi-first. Calm editorial "paper" aesthetic; NO gradients, NO
shadows, radius 2-4px; colour ONLY on the verdict. Low-end Android target.

DESIGN TOKENS (use ONLY these): <Appendix A block>

SCREEN "Today": shows the farmer's saved crop+mandi. Content: headline modal price
(₹/qtl, large, tabular) with a ▲/▼ delta; a prominent SELL / HOLD / WAIT verdict with a
one-line reason; a 7-day forecast band (dashed forecast line + shaded range) with a
method label and a "likely range" caption; a small arrivals strip; a short list of other
mandis with their prices; an "as of" timestamp; a sync/offline indicator.
States: loading (skeletons), stale ("अंदाज जुना आहे…"), offline (saved prices).
Elevate: make the verdict the unmistakable hero with a subtle rise+pop reveal; price
pulses gently when it changes; the chart fades in and on range change. Specify what
animates, its trigger, and ~duration (keep ≤320ms, transform/opacity only).
```
