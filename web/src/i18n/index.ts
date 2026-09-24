import { i18n } from '@lingui/core';
import type { Lang } from './locales.ts';

// Only the active catalog is downloaded. @lingui/vite-plugin compiles .po on import.
const loaders: Record<Lang, () => Promise<{ messages: Record<string, unknown> }>> = {
  mr: () => import('./locales/mr/messages.po'),
  hi: () => import('./locales/hi/messages.po'),
  en: () => import('./locales/en/messages.po'),
};

export async function activateLocale(lang: Lang) {
  const { messages } = await loaders[lang]();
  i18n.load(lang, messages as never);
  i18n.activate(lang);
  document.documentElement.lang = lang;
}

export { i18n };
