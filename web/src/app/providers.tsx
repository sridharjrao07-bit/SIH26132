import { useEffect, useState, type ReactNode } from 'react';
import { QueryClient } from '@tanstack/react-query';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { get, set, del } from 'idb-keyval';
import { I18nProvider } from '@lingui/react';
import { i18n, activateLocale } from '../i18n/index.ts';
import { usePrefs } from '../stores/prefs.ts';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      gcTime: 24 * 60 * 60_000,          // keep data around for the offline cache
      refetchOnWindowFocus: true,
      networkMode: 'offlineFirst',       // show cached data immediately on flaky 3G
    },
  },
});

// The last good data is saved to IndexedDB: a farmer with one bar of signal still sees
// the prices from the morning, clearly labelled with their "as of" time.
const persister = createAsyncStoragePersister({
  storage: { getItem: get, setItem: set, removeItem: del },
  key: 'kb-query-cache',
  throttleTime: 2000,
});

export function Providers({ children }: { children: ReactNode }) {
  const lang = usePrefs((s) => s.lang);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;
    activateLocale(lang).then(() => alive && setReady(true));
    return () => { alive = false; };
  }, [lang]);

  if (!ready) return null; // first paint waits for one small catalog, not the whole app

  return (
    <PersistQueryClientProvider client={queryClient} persistOptions={{
      persister, maxAge: 24 * 60 * 60_000, buster: 'v1',
      // Only public price data goes to IndexedDB. Account, lots, offers and alerts never outlive the session.
      dehydrateOptions: { shouldDehydrateQuery: (q) => q.state.status === 'success' && q.queryKey[0] !== 'auth' },
    }}>
      <I18nProvider i18n={i18n}>{children}</I18nProvider>
    </PersistQueryClientProvider>
  );
}
