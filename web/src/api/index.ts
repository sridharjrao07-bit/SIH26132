import { createApiClient } from './client.ts';
import { pricesApi } from './endpoints/prices.ts';
import { forecastsApi } from './endpoints/forecasts.ts';
import { referenceApi } from './endpoints/reference.ts';
import { saleWindowApi } from './endpoints/saleWindow.ts';
import { accuracyApi } from './endpoints/accuracy.ts';

// Same-origin: Vite (dev) and the CDN (prod) proxy /api to FastAPI.
export const api = createApiClient({ baseUrl: import.meta.env.VITE_API_BASE_URL ?? '' });

export const prices = pricesApi(api);
export const forecasts = forecastsApi(api);
export const reference = referenceApi(api);
export const saleWindow = saleWindowApi(api);
export const accuracy = accuracyApi(api);
