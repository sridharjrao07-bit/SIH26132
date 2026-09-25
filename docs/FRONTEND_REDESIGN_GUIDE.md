# Krishi Bazaar — Frontend UI Redesign Guide

> **Target Audience:** Frontend Engineering & Product Design Teams  
> **Scope:** **UI Redesign Only** (Visual design, component layouts, design tokens, micro-interactions, responsive ergonomics, accessibility, and i18n).  
> **Backend & API Constraint:** No backend endpoint signatures, database schemas, or API contracts are to be modified. All UI enhancements build on existing REST endpoints and database invariants.

---

## 1. Executive Summary & Core Mission

Krishi Bazaar is an AI-powered agricultural intelligence and marketplace Progressive Web App (PWA) designed for Indian farmers, FPOs (Farmer Producer Organizations), and mandi traders.

### The Problem with Traditional AgTech UIs
* **Visual Clutter & Distrust:** Traditional dashboards overload rural users with dense data tables, red/green trading candlestick charts, and academic statistical jargon (e.g., "95% confidence intervals", "multivariate regression residual bands").
* **Poor Rural Ergonomics:** Interfaces break under direct sunlight, fail on low-cost Android phones (sub-₹3000 devices over erratic 2G/3G connections), and feature tiny touch targets that are difficult for farmers using one hand in the field.
* **Loss of the Core Answer:** Farmers do not want to analyze raw econometric curves; they open the app with one urgent decision in mind: **"Should I harvest and sell today, or should I hold my crop in storage?"**

### The Redesign Mandate
1. **The Product's One Job is the Verdict:** Highlighting the localized recommendation (**SELL NOW**, **HOLD**, or **WAIT**) above all else.
2. **"Ink on Paper" Visual Discipline:** Warm, paper-like background (`#F7F4EE`) and high-contrast deep ink (`#0F0E0C`) offering glare-resistant legibility in direct sunlight.
3. **Colour is Reserved for the Answer:** Price changes use directional symbols (▲ / ▼) in neutral ink. Vivid semantic color is strictly quarantined to the verdict.
4. **Extreme Low-End Device Budget:** 60fps animations utilizing exclusively GPU-accelerated `transform` and `opacity` properties (zero layout reflows/repaints).

---

## 2. Design System & Token Architecture

The Tailwind CSS v4 setup (`web/src/styles/index.css`) **disables generic utility palettes** (`--color-*: initial`). Generic utility classes (such as `bg-blue-500` or `text-red-600`) will fail the build. All UI elements must strictly utilize the tokens detailed below.

### 2.1 Color Tokens & Contrast Hierarchy

| Category | Token Name | Hex Value | Min Contrast Ratio | Purpose & Usage Rule |
| :--- | :--- | :--- | :--- | :--- |
| **Surfaces** | `paper` | `#F7F4EE` | Canvas base | Primary app background. Warm, paper-like, reduces solar glare. |
| | `paper-2` | `#EFEAE0` | — | Secondary container, table headers, elevated cards. |
| | `ink-hero` | `#0F0E0C` | — | Deep ink hero panel for high-prominence headers. |
| | `accent-tint` | `#EEF2FF` | — | Light indigo background for selected filters/tabs. |
| **Ink & Text** | `ink` | `#0F0E0C` | **16.0:1** on paper | Primary text, titles, numbers, price indicators (▲/▼). |
| | `ink-2` | `#57534A` | **7.0:1** on paper | Secondary labels, timestamps, explanatory subtext. |
| | `rule` | `#DDD6C8` | — | 1px hairline dividers and subtle card borders. |
| **Brand Accent** | `accent` | `#4338CA` | 8.2:1 on paper | Deep Indigo. Buttons, active tab indicators, links. |
| | `accent-2` | `#6366F1` | — | Interactive hover state for accent elements. |
| | `accent-dark` | `#312E81` | — | Active / pressed state for primary buttons. |
| **Semantic Verdicts** *(Locked)* | `sell` | `#1A5C32` | **7.3:1** on paper | **SELL NOW** verdict badge, border, and accent. |
| | `sell-tint` | `#EBF5EE` | — | Light green background tint for SELL card. |
| | `hold` | `#6E4A03` | **7.2:1** on paper | **HOLD** verdict badge, border, and accent. |
| | `hold-tint` | `#FDF6E2` | — | Light amber background tint for HOLD card. |
| | `wait` | `#475059` | **7.5:1** on paper | **WAIT** verdict badge, border, and accent. |
| | `wait-tint` | `#F1F3F5` | — | Light neutral grey background tint for WAIT card. |
| **Data Viz** | `forecast` | `#2D5B88` | — | AI forecast line and projected cone (**Chart only**). |
| | `arrivals` | `#CBBFA9` | — | Mandi arrival volume bars (**Separate chart strip only**). |

> **Hard Invariant:** Never use `sell` (green) or `hold` (amber) for general price changes or UI chrome. If modal price increased by ₹50, display `▲ ₹50` in `ink`, NOT green. Colour is reserved for the action.

---

### 2.2 Typography & Indian Number Formatting

```
Fonts:
  Primary Latin:      "IBM Plex Sans", system-ui, sans-serif
  Devanagari:         "IBM Plex Sans Devanagari", system-ui, sans-serif
```

1. **Type Scale:**
   * `--text-xs`: `14px` (**Absolute minimum type floor** — no text may be smaller than 14px on mobile).
   * `--text-sm`: `15px` (Metadata, subtitles, timestamps).
   * `--text-base`: `17px` (Body text, input fields, button labels).
   * `--text-lg`: `20px` (Card titles, section headings).
   * `--text-xl`: `28px` (Screen headers, modal titles).
   * `--text-price`: `40px` (Hero price figures).
2. **Line Heights & Devanagari Matras:**
   * English: `line-height: 1.45`.
   * Marathi & Hindi (`:lang(mr)`, `:lang(hi)`): `line-height: 1.55`.  
     *Devanagari matras (upper and lower diacritics like ो, ौ, ु, ू) require generous vertical room. Never set `leading-none` or `overflow-hidden` on Devanagari text containers.*
3. **Indian Number Formatting Standard (`en-IN` Tabular Numerals):**
   * Currency figures must use the Indian numbering system grouping (lakhs/crores: `₹1,82,700` and `₹1,827/क्विंटल`).
   * Numerals in Marathi and Hindi screens must render in **Latin digits with `-u-nu-latn`** (`1, 2, 3...`, not `१, २, ३...`) per farmer field testing preferences.
   * All prices and numeric columns must carry the `.tabular` utility class (`font-variant-numeric: tabular-nums`).

---

### 2.3 Tactile Touch Targets & Spatial Spacing

1. **Minimum Tap Target (`.tap`):** Every interactive button, selector, card link, and input must have a minimum physical height/width of **48px** (`min-height: 48px`).
2. **Spacing Grid:** Multiples of 4px/8px:
   * `--spacing-1` (4px), `--spacing-2` (8px), `--spacing-3` (12px), `--spacing-4` (16px), `--spacing-6` (24px), `--spacing-8` (32px), `--spacing-12` (48px).
3. **Corner Radii:**
   * Badges & Chips: `--radius-md` (6px).
   * Inputs & Buttons: `--radius-lg` (8px).
   * Cards & Modals: `--radius-2xl` (12px).
   * Hero Dark Banner: `--radius-hero` (0px sharp flush).
   * Floating Action Chips: `--radius-full` (9999px).

---

## 3. Shell & Navigation Redesign

### 3.1 Mobile PWA App Shell

```
┌────────────────────────────────────────────────────────┐
│ [Logo] Krishi Bazaar       [Mandi: Lasalgaon ▼] [मराठी]│ <- Top Bar (48px)
├────────────────────────────────────────────────────────┤
│ [Offline Banner: You are working offline - cached]     │ <- Conditional Banner
├────────────────────────────────────────────────────────┤
│                                                        │
│                     PAGE CONTENT                       │
│              (Scrollable Viewport Area)                │
│                                                        │
├────────────────────────────────────────────────────────┤
│  [  ★  ]     [  🌾  ]     [  🛒  ]     [  🔔  ]     [  👤  ] │ <- Bottom Bar (56px)
│  Today        Sell         Buy        Alerts      Account
└────────────────────────────────────────────────────────┘
```

1. **Top App Bar:**
   * **Mandi Selector:** Quick-switch chip with district proximity pill (`Lasalgaon APMC (12 km)`).
   * **Language Switcher:** 3-state toggle pill: `English | मराठी | हिंदी`. Switching languages updates the Lingui context instantly without full page reloads.
   * **Network Health Indicator:** Clean hairline status bar that drops down smoothly when the device disconnects (`"ऑफलाइन मोड — सेव्ह केलेला डेटा दाखवत आहे"`).
2. **Bottom Navigation Bar (PWA):**
   * Fixed at screen bottom, elevated with `var(--shadow-card)` and subtle `border-t border-rule`.
   * Height: 56px with safe-area inset padding for modern gesture-navigation phones.
   * Active tab indicator: 2px animated indigo line (`nav-indicator`) sliding under the active icon.
   * Tabs:
     1. **Today (आजचे भाव):** Price discovery, forecast chart, and sale window verdict.
     2. **Sell (शेतमाल विक्री):** Farmer lot creation, active listings, buyer matching, transaction ledger.
     3. **Buy (खरेदी):** Verified trader directory, procurement board, and offer dispatch.
     4. **Alerts (किंमत सूचना):** SMS alert configuration and active price threshold watchers.
     5. **Account (खाते):** Profile, language selection, district setting, and role switcher.

### 3.2 Responsive Tablet & Desktop Breakpoints

* **Mobile Viewport (360px – 640px):** Single-column stacked cards. Bottom navigation bar active.
* **Tablet / Desktop Viewport (≥ 768px):** Bottom navigation shifts to a top header navigation bar. Max container width: `1024px`. Today screen adopts a **2-column layout**:
  * **Left Column (60% width):** Hero Price Card + 7-Day Price Forecast Chart + Arrival Strip.
  * **Right Column (40% width):** Sale Window Verdict Card + Better Mandi Transport Arbitrage Card + Model Accuracy Transparency Card.

---

## 4. Screen-by-Screen Component Specifications

### 4.1 Screen 1: Today & Price Discovery (`TodayPage`, `PairView`)

The primary home screen designed for daily farmer check-ins.

```
┌────────────────────────────────────────────────────────┐
│ Onion (कांदा) — Lasalgaon APMC                         │
│ ₹2,150 / quintal                                       │
│ ▲ ₹40 vs yesterday           Updated: Today, 06:30 AM  │
├────────────────────────────────────────────────────────┤
│ ┌────────────────────────────────────────────────────┐ │
│ │ [ ACTION: HOLD (थोडे थांबा) ]                     │ │
│ │ "Prices likely to rise by ₹150–200 over next 5     │ │
│ │  days due to reduced arrivals from Niphad."        │ │
│ └────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────┤
│ 7-Day AI Price Forecast                                │
│ [ Chart Canvas: Past 30 Days (Solid) + 7 Days (Cone) ] │
│ [ Arrivals Strip: 7-Day Moving Avg Volumes           ] │
│ Caption: "Likely price band based on rainfall & lags"  │
│ [Chip: Model: Trend with arrivals and weather ⓘ]       │
├────────────────────────────────────────────────────────┤
│ Alternative Mandis Nearby                              │
│ • Pimpalgaon APMC (18 km): ₹2,280 (+₹130)              │
│   Net gain after ₹40 transport: +₹90/qtl [View Route]  │
└────────────────────────────────────────────────────────┘
```

#### Component 1: Hero Price Headline (`PriceHeadline.tsx`)
* **Price Value:** 40px bold tabular numerals (`--text-price`, `tabular`).
* **Unit Label:** Display unit clearly (`/ क्विंटल` or `/ quintal`) in `ink-2` (15px).
* **Trend Delta:** Directional icon + difference amount: `▲ ₹40 कालपेक्षा जास्त` (in neutral `ink`, no green/red).
* **As-Of Freshness Stamp (`AsOfStamp.tsx`):** `"आजचे भाव • सकाळी ०६:३०"` with a soft pulsing green dot if arrival was recorded today.

#### Component 2: Sale Window Verdict Card (`SaleWindowCard.tsx` & `VerdictChip.tsx`)
* **Verdict Hierarchy:**
  * **SELL NOW (`#1A5C32` / `#EBF5EE`):** "आत्ताच विक्री करा" (Best current price window).
  * **HOLD (`#6E4A03` / `#FDF6E2`):** "थोडे थांबा" (Anticipated upward trend).
  * **WAIT (`#475059` / `#F1F3F5`):** "थांबा / नवीन आवक येईपर्यंत वाट पाहा" (Insufficient volume or flat trend).
* **Micro-interaction:** When rendered, the verdict background draws in with `.verdict-band-fill` (`scaleX(0)` to `scaleX(1)` over 260ms), while the verdict text slides up smoothly (`.verdict-band-content`).
* **Plain Language Reason:** Localized sentence explaining *why* (e.g. `"कमी आवक आणि पावसाच्या शक्यतेमुळे पुढील आठवड्यात भाव वाढण्याची शक्यता"`). Never displays raw statistical metrics or internal equation parameters.

#### Component 3: Price Forecast & Arrival Chart (`PriceForecastChart.tsx`)
* **History Section:** Solid 2px ink line for observed historical prices over selected window (default: 30 days).
* **Forecast Section:**
  * Point prediction: Dashed line in `--color-forecast` (`#2D5B88`).
  * Uncertainty Cone: Semi-transparent area fill (`rgba(45, 91, 136, 0.12)`) bounded by `upper_bound` and `lower_bound`.
  * Horizon Label: Display `"पुढील N दिवस"` where $N$ matches the exact count of forecast points returned by the API (never hardcode "7").
* **Arrival Strip:** Synchronized sub-chart below price curve showing 7-day average mandi arrivals (`#CBBFA9`). The y-axis of arrivals is normalized internally and never labeled against the price axis to prevent scale confusion.
* **Scrub Tooltip:** Renders a clean card showing Date, Modal Price, and Estimated Range.

#### Component 4: Explainable AI & Model Chip (`ModelChip.tsx` & `AccuracyCard.tsx`)
* **Explainable Model Label:** Displays friendly localized methodology from `web/src/features/trust/methods.ts`:
  * `feature_ols`: *"हवामान आणि आवक आधारित अंदाज (Trend with arrivals and weather)"*.
  * `ols`: *"किंमतीचा सरळ ट्रेंड (Straight-line trend)"*.
  * `gbm`: *"मशीन लर्निंग मॉडेल (Gradient boosting machine)"*.
  * `blend`: *"सरासरी + ट्रेंड (Average + trend)"*.
* **Accuracy Transparency Card:** Displays real historical performance if available. If backtest is pending, clearly display: *"मॉडेल पडताळणी सुरू आहे (Verification pending)"*.

#### Component 5: Better Market Card (`BetterMarketCard.tsx`)
* Compares neighboring mandis in the district.
* Calculates transport-adjusted net arbitrage:  
  $$\text{Net Advantage} = \text{Neighbor Mandi Price} - \text{Local Mandi Price} - \text{Estimated Transport Cost}$$
* If positive, highlights the opportunity: *"पिंपळगाव बाजारपेठेत वाहतूक खर्च वजा जाता ₹90/क्विंटल अधिक नफा मिळू शकतो."*

---

### 4.2 Screen 2: Farmer Selling & Produce Management (`LotsPage`, `NewLotPage`, `LotDetailPage`)

Allows farmers to digitize crop inventory, receive verified buyer offers, and track payments.

#### Component 1: 3-Step Produce Listing Wizard (`NewLotPage.tsx`)
* **Step 1: Commodity & Variety:** Large visual cards for primary district commodities (Onion, Tomato, Soyabean, Cotton).
* **Step 2: Quantity:** Huge numeric input box with clear Quintal stepper buttons (`+5`, `+10`, `+50 qtl`).
* **Step 3: Harvest Date & Quality Grade:** Simple grade selector (`FAQ / सामान्य`, `Super / उत्तम`, `Special / दर्जेदार`) with clear descriptions.
* **Action Button:** Sticky 48px button: `"शेतमाल विक्रीसाठी नोंदवा (List Produce)"`.

#### Component 2: Lot Status Tracker (`LotDetailPage.tsx`)
* Visual forward-only progress bar:
  $$\text{नोंदणी केली (Open)} \longrightarrow \text{ऑफर आली (Offered)} \longrightarrow \text{करार झाला (Matched)} \longrightarrow \text{विक्री पूर्ण (Sold)}$$
* State transitions are forward-only (never render a "Reopen" button).

#### Component 3: Verified Buyer Matching Card
* Lists ranked buyers matching commodity and quantity requirements.
* Displays:
  * Buyer Name & Business Type (FPO / Trader / Processor).
  * Verification Badge: Verified shield icon.
  * Payment Reliability Badge: High / Medium payment speed record.
  * Distance from farm in kilometers.

#### Component 4: Offer Decision Action Bar
* When a buyer places an offer on the lot:
  * Displays: Offered Price per Quintal, Total Value (`₹`), Expiry Countdown ("48 तासांत निर्णय घ्या").
  * Dual Buttons:
    * **Reject Button:** Outlined button in neutral `ink-2` (`"नाकारा"`).
    * **Accept Button:** Solid button in brand `accent` (`"ऑफर स्वीकारा"`).
* Accepting triggers immediate status advance to `matched`.

#### Component 5: Transparent Audit Ledger (`LotDetailPage.tsx` -> `Ledger`)
* Chronological timeline showing all verifiable transaction milestones:
  * `[10:00 AM]` शेतमाल नोंदवला — 100 क्विंटल कांदा (Lot Created).
  * `[02:30 PM]` सह्याद्री फार्म्स कडून ₹2,100 ची ऑफर प्राप्त (Offer Received).
  * `[04:15 PM]` ऑफर स्वीकारली — व्यवहार निश्चित (Offer Accepted).
  * `[05:00 PM]` देयक जमा झाले (Payment Received via Escrow/UPI).

---

### 4.3 Screen 3: Buyer Procurement Board (`BuyPage.tsx`, `BoardPage.tsx`)

Designed for FPOs, processors, and mandi commission agents seeking consistent supply.

* **Filter Bar:** Quick filtering by Commodity, Distance Radius (10km, 25km, 50km), and Minimum Quantity.
* **Aggregated Supply Cards:** Cards displaying available farmer lots with Grade badges, location village/APMC, and asking price.
* **Instant Offer Modal:** Input for offering price per quintal and quantity with automatic validation against lot availability.

---

### 4.4 Screen 4: SMS Price Alerts (`AlertsPage.tsx`)

For farmers without smartphones or traveling outside 4G coverage.

* **Visual Alert Rule Builder:**
  * "मला एसएमएस पाठवा जेव्हा [कांदा] चे भाव [लासलगाव] मार्केटमध्ये [₹2,200] पेक्षा [जास्त / जास्त किंवा समान] होतील."
* **Simulated SMS Preview Box:** Real-time preview card rendering the exact text message that will arrive on their basic feature phone in Marathi/Hindi.
* **Active Alert Toggle:** Prominent switch to pause or reactivate alerts.

---

## 5. Micro-Interactions & Animation Budget

Animations must be respectful of low-power mobile processors and high-latency connections.

### 5.1 Performance Rules
1. **Properties Permitted in Keyframes:** Only `transform` and `opacity`.
2. **Forbidden Animation Properties:** Never animate `width`, `height`, `margin`, `padding`, `top/left`, or `box-shadow` (these force browser layout reflows and stutter on ₹2000 devices).
3. **Duration Ceiling:** 90ms to 320ms maximum. No slow luxury animations.
4. **Easing:** Snappy decelerate curve: `cubic-bezier(0.16, 1, 0.3, 1)`.

### 5.2 Keyframe Inventory (`web/src/styles/index.css`)

```css
/* Card & Page Entry */
@keyframes rise {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Verdict Badge Reveal */
@keyframes band {
  from { transform: scaleX(0); opacity: 0.6; }
  to   { transform: scaleX(1); opacity: 1; }
}

/* Tactile Button / Chip Tap Feedback */
.chip-press:active {
  transform: scale(0.98);
  transition: transform 90ms cubic-bezier(0.4, 0, 0.2, 1);
}

/* Staggered List Rendering */
.row-stagger-1 { animation: rise 200ms cubic-bezier(0.16, 1, 0.3, 1) both; }
.row-stagger-2 { animation: rise 200ms 40ms cubic-bezier(0.16, 1, 0.3, 1) both; }
.row-stagger-3 { animation: rise 200ms 80ms cubic-bezier(0.16, 1, 0.3, 1) both; }
.row-stagger-4 { animation: rise 200ms 120ms cubic-bezier(0.16, 1, 0.3, 1) both; }
```

### 5.3 Reduced Motion Accessibility
When a user has OS-level reduced motion enabled, all animations are instantaneously neutralized:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
  }
}
```

---

## 6. Internationalization & Linguistic Ergonomics

### 6.1 Translation Discipline (Lingui.js)
* Every string rendered to users must be wrapped in `<Trans>` or the `t\`\`` macro.
* Catalogs reside in `web/src/i18n/locales/{en,hi,mr}/messages.po`.
* Default App Language: **Marathi (`mr`)**.

### 6.2 Plain Agricultural Glossary

Avoid stiff dictionary translations. Use terms used daily in Maharashtra and Northern APMC mandis:

| English Source | Marathi Translation (`mr`) | Hindi Translation (`hi`) | Avoid (Too formal / Academic) |
| :--- | :--- | :--- | :--- |
| **Sell Now** | आत्ताच विका / विक्री करा | अभी बेचें | तत्काळ विक्री |
| **Hold** | थोडे थांबा / माल राखून ठेवा | रोक कर रखें | धारणा करा |
| **Wait** | प्रतीक्षा करा / थांबा | प्रतीक्षा करें | विलंब करा |
| **Arrivals** | आवक | आवक | आगमन |
| **Modal Price** | सरासरी भाव / आजचा भाव | औसत भाव | बहुलक किंमत |
| **Forecast** | संभाव्य अंदाज | मूल्य अनुमान | भविष्यकथन |
| **Verified Buyer** | पडताळणी झालेले व्यापारी | सत्यापित खरीदार | प्रमाणित ग्राहक |
| **Lot** | शेतमाल लॉट | फसल खेप | संचय |

---

## 7. Frontend Engineering Guardrails (Non-Negotiables)

1. **The Verdict Comes from the API:**  
   The frontend must never calculate or infer whether a farmer should sell or hold. It reads `saleWindow.action` (`SELL_NOW`, `HOLD`, `WAIT`) directly from the API. The `VerdictChip` and `SaleWindowCard` must subscribe to the exact same query.
2. **State Machine Invariants:**  
   Never render options to "reopen" a sold/withdrawn lot, or "re-negotiate" an accepted offer. The marketplace state machine is forward-only.
3. **No Phantom Feature Claims:**  
   If model accuracy or backfill is still calculating, render the intended pending state (*"पडताळणी सुरू आहे"*), rather than inventing mock percentages or hiding the component.
4. **Offline Resilience:**  
   Cached prices must display with an unambiguous offline indicator rather than failing with an unhandled network error screen.

---

## 8. Verification & Quality Gate Checklist

Before opening any pull request with UI redesign changes, run and verify the complete frontend test and build suite:

```bash
# 1. Typecheck: Verify strict TypeScript compilation
npm run typecheck --prefix web

# 2. Internationalization: Verify 0 missing translation keys
npm run i18n:check --prefix web

# 3. Unit & Integration Tests: Run against the local mock server
python3 frontend_handoff/mock/mock_api.py &
MOCK_PID=$!
sleep 1
REQUIRE_MOCK=1 npm test --prefix web
kill $MOCK_PID

# 4. Production Build: Ensure Vite bundle compiles and generates PWA service workers
npm run build --prefix web
```

All 4 commands must exit with code `0`.
