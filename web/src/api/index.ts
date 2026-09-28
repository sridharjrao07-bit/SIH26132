import { createApiClient } from './client.ts';
import { pricesApi } from './endpoints/prices.ts';
import { forecastsApi } from './endpoints/forecasts.ts';
import { referenceApi } from './endpoints/reference.ts';
import { saleWindowApi } from './endpoints/saleWindow.ts';
import { accuracyApi } from './endpoints/accuracy.ts';
import { accountApi } from './endpoints/account.ts';
import { alertsApi } from './endpoints/alerts.ts';
import { marketplaceApi } from './endpoints/marketplace.ts';
import { directApi } from './endpoints/direct.ts';
import { getToken, refreshSession } from '../auth/session.ts';

// Same-origin: Vite (dev) and the CDN (prod) proxy /api to FastAPI.
export const api = createApiClient({ baseUrl: import.meta.env.VITE_API_BASE_URL ?? '', getToken, refreshSession });

export const prices = pricesApi(api);
export const forecasts = forecastsApi(api);
export const reference = referenceApi(api);
export const saleWindow = saleWindowApi(api);
export const accuracy = accuracyApi(api);
export const account = accountApi(api);
export const alerts = alertsApi(api);
export const marketplace = marketplaceApi(api);
export const direct = directApi(api);
