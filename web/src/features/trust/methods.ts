import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';

// Verified against forecasting/engine.py and frontend_handoff/types/api-types.ts @ e94809f.
// `auto` is a model_id registry key (never a method); `naive` is backtest-only. Unknown values
// fall back to the raw string, so a new engine method never breaks the UI (G4).
// GBM is only ever named when method === 'gbm'.
export const METHODS: Record<string, { label: MessageDescriptor; about: MessageDescriptor }> = {
  moving_avg: {
    label: msg`Moving average`,
    about: msg`Average of the last 7 days of prices, carried forward. Used when a mandi has only 10–14 days of history.`,
  },
  blend: {
    label: msg`Average + trend`,
    about: msg`A mix of the recent average and the recent trend. Used automatically when there is enough history but no advanced model has been approved.`,
  },
  ma: { label: msg`Moving average`, about: msg`Average of recent prices, carried forward.` },
  ols: { label: msg`Straight-line trend`, about: msg`Continues the recent price trend in a straight line.` },
  feature_ols: {
    label: msg`Trend with arrivals and weather`,
    about: msg`A regression on recent prices, mandi arrivals, rainfall and district prices. Signals that did not change recently are dropped automatically.`,
  },
  holt_winters: { label: msg`Seasonal smoothing`, about: msg`Holt-Winters smoothing: follows the level and trend of prices over time.` },
  gbm: {
    label: msg`Gradient boosting (GBM)`,
    about: msg`A machine-learning model trained on prices, arrivals, weather and market signals across mandis.`,
  },
  none: { label: msg`No forecast`, about: msg`Not enough price history to make an honest forecast.` },
};
