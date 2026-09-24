export const LANGS = ['mr', 'hi', 'en'] as const;
export type Lang = (typeof LANGS)[number];
export const DEFAULT_LANG: Lang = 'mr';            // Nashik farmer default, matches user_profiles fallback
export const LANG_LABEL: Record<Lang, string> = { mr: 'मराठी', hi: 'हिंदी', en: 'English' };
export const isLang = (x: unknown): x is Lang => typeof x === 'string' && (LANGS as readonly string[]).includes(x);
