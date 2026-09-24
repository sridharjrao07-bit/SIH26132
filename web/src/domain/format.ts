// Prices: Latin digits + en-IN grouping in EVERY locale (Phase 2 decision #3).
// Never toLocaleString('mr-IN') on numbers — some browsers switch to Devanagari digits.
import type { Lang } from '../i18n/locales.ts';

const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const pct = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1, minimumFractionDigits: 1 });

export const formatINR = (n: number) => `₹${inr.format(Math.round(n))}`;
export const formatNumber = (n: number) => inr.format(Math.round(n));
export const formatPct = (n: number) => `${pct.format(Math.abs(n))}%`;

/** Month names in the UI language, digits forced Latin via the -u-nu-latn extension. */
const dateLocale = (lang: Lang) => `${lang}-IN-u-nu-latn`;

export function formatDay(iso: string, lang: Lang, withYear = false) {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return new Intl.DateTimeFormat(dateLocale(lang), {
    day: 'numeric', month: 'short', ...(withYear ? { year: 'numeric' } : {}), timeZone: 'UTC',
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

export function formatTime(isoDateTime: string, lang: Lang) {
  return new Intl.DateTimeFormat(dateLocale(lang), {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata',
  }).format(new Date(isoDateTime));
}

export function formatDateTime(isoDateTime: string, lang: Lang) {
  return new Intl.DateTimeFormat(dateLocale(lang), {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata',
  }).format(new Date(isoDateTime));
}

export const hoursSince = (iso: string, now = Date.now()) => (now - Date.parse(iso)) / 3_600_000;
