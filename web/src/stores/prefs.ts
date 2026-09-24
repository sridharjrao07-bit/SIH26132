import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { DEFAULT_LANG, type Lang } from '../i18n/locales.ts';

export interface Pair { commodityId: string; marketId: string }

interface PrefsState {
  lang: Lang;
  district: string;
  /** Designed for N (Phase 3 decision 2); Today renders only [0]. */
  pinnedPairs: Pair[];
  setLang: (lang: Lang) => void;
  pinPair: (pair: Pair) => void;
}

export const usePrefs = create<PrefsState>()(
  persist(
    (set) => ({
      lang: DEFAULT_LANG,
      district: 'Nashik',
      pinnedPairs: [],
      setLang: (lang) => set({ lang }),
      // New pin goes first; de-duplicated
      pinPair: (pair) => set((s) => ({
        pinnedPairs: [pair, ...s.pinnedPairs.filter((p) => p.commodityId !== pair.commodityId || p.marketId !== pair.marketId)].slice(0, 5),
      })),
    }),
    { name: 'kb-prefs', version: 1 },
  ),
);
