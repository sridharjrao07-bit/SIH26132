import { Link, Outlet } from '@tanstack/react-router';
import { useIsFetching } from '@tanstack/react-query';
import { Trans, useLingui } from '@lingui/react/macro';
import { usePrefs } from '../stores/prefs.ts';
import { LANGS, LANG_LABEL } from '../i18n/locales.ts';
import { useOnline } from '../ui/hooks.ts';

function LanguageSwitch() {
  const { t } = useLingui();
  const lang = usePrefs((s) => s.lang);
  const setLang = usePrefs((s) => s.setLang);
  return (
    <div role="group" aria-label={t`Language`} className="flex text-xs">
      {LANGS.map((l) => (
        <button
          key={l}
          lang={l}
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={`tap px-2 ${lang === l ? 'font-semibold text-ink underline underline-offset-4' : 'text-ink-2'}`}
        >
          {l === 'en' ? 'EN' : LANG_LABEL[l].slice(0, 3)}
        </button>
      ))}
    </div>
  );
}

function SyncStatus() {
  const online = useOnline();
  const fetching = useIsFetching();
  return (
    <span className="flex items-center gap-1.5 text-xs text-ink-2" aria-live="polite">
      <span aria-hidden className={`inline-block size-2 rounded-full ${online ? (fetching ? 'bg-ink-2' : 'bg-sell') : 'border border-ink-2'}`} />
      {!online ? <Trans>Offline</Trans> : fetching ? <Trans>Updating…</Trans> : <Trans>Live</Trans>}
    </span>
  );
}

function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  return (
    <div role="status" className="rule-b bg-paper-2 px-4 py-2 text-sm">
      <Trans>You are offline. Showing the prices saved on this phone. Check the date on each price.</Trans>
    </div>
  );
}

function BottomNav() {
  const item = 'tap flex flex-1 flex-col items-center justify-center text-xs text-ink-2';
  const active = { className: `${item} !text-ink font-semibold` };
  return (
    <nav className="rule-t fixed inset-x-0 bottom-0 z-10 flex bg-paper pb-[env(safe-area-inset-bottom)]">
      <Link to="/" className={item} activeProps={active} activeOptions={{ exact: true }}><Trans>Today</Trans></Link>
      <Link to="/bhav" className={item} activeProps={active}><Trans>Prices</Trans></Link>
      <Link to="/sell" className={item} activeProps={active}><Trans>Sell</Trans></Link>
      <Link to="/alerts" className={item} activeProps={active}><Trans>Alerts</Trans></Link>
      <Link to="/account" className={item} activeProps={active}><Trans>Account</Trans></Link>
    </nav>
  );
}

export function AppShell() {
  return (
    <div className="mx-auto min-h-dvh max-w-[1100px] pb-20">
      <header className="rule-b flex items-center justify-between gap-2 px-4">
        <Link to="/" className="tap flex items-center gap-2 font-semibold">
          <svg aria-hidden width="20" height="20" viewBox="0 0 64 64"><path d="M6 46 L22 30 L34 40 L58 14" fill="none" stroke="currentColor" strokeWidth="7" /><rect x="6" y="54" width="52" height="6" fill="var(--color-sell)" /></svg>
          <span><Trans>Krishi Bazaar</Trans></span>
        </Link>
        <div className="flex items-center gap-3">
          <SyncStatus />
          <LanguageSwitch />
        </div>
      </header>
      <OfflineBanner />
      <main>
        <Outlet />
      </main>
      <BottomNav />
    </div>
  );
}
