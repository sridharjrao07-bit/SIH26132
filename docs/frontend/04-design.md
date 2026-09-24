# Frontend Design — Phase 4: Visual Language & Data Viz (APPROVED 2026-09-24)

## Palette (contrast measured on paper `#F7F4EE`)
| Token | Hex | Ratio |
|---|---|---|
| paper | `#F7F4EE` | — |
| ink | `#1A1916` | 16.01 |
| ink-2 (secondary) | `#57534A` | 6.98 (accepted) |
| **sell** | `#1A5C32` | 7.30 |
| **hold** | `#6E4A03` | 7.24 |
| **wait** | `#475059` | 7.47 |
| forecast | `#2D5B88` | 6.46 (chart element only, never text) |
| arrivals | `#CBBFA9` | chart element only |
| rule | `#DDD6C8` | hairlines only |

The original `#1F6B3A` / `#A86A12` / `#56606B` failed 7:1 (Hold was 4.04). F1 replaces them.
The verdict is also always identified by its **label**, never by hue alone.

## Rules
- **Colour on the verdict only.** Price changes use ▲▼ in ink. Rationale for judges: "The product's one job is the verdict; colour is reserved for the answer, not the data."
- Arrivals go in a **separate strip** (`syncId`). The strip's y-scale is internal and never labelled against the price axis.
- Band copy is "likely range / model's estimate". **Never say "95%".** The future "N in 10" caption is generated only from G6 `metrics.interval_coverage`, never hardcoded.
- The default range is 30 days, with an "enlarge ›" link back from 180/365.
- **F2 stale state (v1):** history only, plus the notice "अंदाज जुना आहे, नवीन डेटाची वाट पाहत आहोत". The API never returns stale forecast rows, so none are drawn.
- **F3:** the accuracy progress row ("23/57 days") is **not built** until G6 exposes a `progress` field.
- **F4:** the bridge/cone start is geometry only. The tooltip renders by point `kind` and never shows band or bridge values on an actual point.
- **F5:** `confidence: 'low'` styling (dashed band outline) is **dormant**. `forecasting/engine.py` never emits it (n<10 → no prediction). QA: don't try to trigger it.
- Horizon label: "पुढील N दिवस" where **N = number of forecast points**, never a literal 7 (see Phase 5 finding S1).
- Gap rule: the dotted bridge appears only when a price is missing **before today** (`last_actual < today − 1`). Today not yet being reported is normal, not a gap.
