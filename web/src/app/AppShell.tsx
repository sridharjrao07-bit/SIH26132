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
    <div className="bg-background text-on-surface antialiased font-body-md selection:bg-primary selection:text-on-primary min-h-dvh pb-20">
      <header className="bg-surface/80 backdrop-blur-md sticky top-0 z-50 shadow-sm border-b border-outline-variant/40">
        <div className="w-full px-space-md lg:px-margin-desktop flex items-center justify-between h-16 max-w-full">
          {/* Brand & Sync */}
          <div className="flex items-center gap-6">
            <Link to="/" className="flex items-center gap-3 tap">
              <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center text-on-primary shadow-sm shadow-primary/30">
                <svg aria-hidden width="20" height="20" viewBox="0 0 64 64"><path d="M6 46 L22 30 L34 40 L58 14" fill="none" stroke="currentColor" strokeWidth="7" /><rect x="6" y="54" width="52" height="6" fill="var(--color-primary-fixed)" /></svg>
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-headline-lg text-[1.375rem] font-bold text-primary tracking-tight"><Trans>Krishi Bazaar</Trans></span>
                  <span className="hidden sm:inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-50 text-primary border border-emerald-200/80 font-label-sm text-label-sm">
                    <span className="w-1.5 h-1.5 rounded-full bg-primary-container animate-pulse"></span>
                    <SyncStatus />
                  </span>
                </div>
                <p className="hidden md:block font-label-sm text-label-sm text-on-surface-variant leading-none"><Trans>Indian APMC Telemetry & Predictive Analytics</Trans></p>
              </div>
            </Link>
          </div>
          
          <div className="flex items-center gap-3">
            <div className="hidden md:flex items-center px-2.5 py-1 rounded-lg bg-surface-container-lowest border border-outline-variant/60 shadow-xs font-label-sm">
              <LanguageSwitch />
            </div>
            <div className="flex md:hidden">
              <LanguageSwitch />
            </div>
            
            <div className="hidden sm:block h-6 w-px bg-outline-variant/40 mx-1"></div>
            <div className="hidden sm:flex items-center gap-2 pl-1">
              <div className="w-8 h-8 rounded-full bg-surface-container-high border border-outline-variant/80 flex items-center justify-center font-headline-md text-primary font-bold text-xs">AK</div>
              <div className="hidden 2xl:block text-left">
                <div className="font-label-sm text-label-sm font-semibold text-on-surface leading-tight">Anand Kumar</div>
                <div className="text-[11px] text-on-surface-variant font-body-sm">FPO Lead / Azadpur</div>
              </div>
            </div>
          </div>
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
