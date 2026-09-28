import { Link, Outlet } from '@tanstack/react-router';
import { useIsFetching } from '@tanstack/react-query';
import { Trans, useLingui } from '@lingui/react/macro';
import { usePrefs } from '../stores/prefs.ts';
import { LANGS, LANG_LABEL } from '../i18n/locales.ts';
import { useOnline } from '../ui/hooks.ts';

function Icon({ name }: { name: 'today' | 'prices' | 'direct' | 'sell' | 'account' }) {
  const paths = {
    today: <><path d="M4 11.5 12 5l8 6.5"/><path d="M6.5 10.5V20h11v-9.5M10 20v-5h4v5"/></>,
    prices: <><path d="M4 19V9M10 19V5M16 19v-7M22 19V3"/><path d="M2 19h22"/></>,
    sell: <><path d="M5 7h14l-1 13H6L5 7Z"/><path d="M9 7a3 3 0 0 1 6 0"/></>,
    direct: <><path d="M12 3v18"/><path d="M5 8h14"/><path d="M8 8l-3 6h6L8 8Z"/><path d="M16 8l-3 6h6l-3-6Z"/></>,
    account: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  };
  return <svg aria-hidden width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}

function LanguageSwitch() {
  const { t } = useLingui();
  const lang = usePrefs((s) => s.lang);
  const setLang = usePrefs((s) => s.setLang);
  return (
    <div role="group" aria-label={t`Language`} className="segmented text-xs">
      {LANGS.map((l) => (
        <button key={l} lang={l} onClick={() => setLang(l)} aria-pressed={lang === l}
          className="min-h-8 px-2" aria-selected={lang === l}>
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
    <span className="hidden items-center gap-2 border border-rule bg-paper-2 px-3 py-1.5 font-mono text-xs text-ink-2 sm:flex diagonal-small" aria-live="polite">
      <span aria-hidden className={`inline-block size-2 rounded-full ${online ? (fetching ? 'bg-saffron live-dot' : 'bg-sell live-dot') : 'border border-ink-2'}`} />
      {!online ? <Trans>Offline</Trans> : fetching ? <Trans>Updating…</Trans> : <Trans>Live</Trans>}
    </span>
  );
}

function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  return <div role="status" className="bg-saffron px-4 py-2 text-center text-sm font-semibold"><Trans>You are offline. Showing the prices saved on this phone. Check the date on each price.</Trans></div>;
}

const navItems = [
  { to: '/', label: <Trans>Today</Trans>, icon: 'today' as const, exact: true },
  { to: '/bhav', label: <Trans>Prices</Trans>, icon: 'prices' as const },
  { to: '/direct', label: <Trans>Direct</Trans>, icon: 'direct' as const },
  { to: '/sell', label: <Trans>Sell</Trans>, icon: 'sell' as const },
  { to: '/account', label: <Trans>Account</Trans>, icon: 'account' as const },
];

function DesktopNav() {
  return <nav className="hidden items-center gap-1 lg:flex">{navItems.map((item) => (
    <Link key={item.to} to={item.to} activeOptions={{ exact: item.exact }} className="diagonal-small px-3 py-2 text-sm font-medium text-ink-2 transition-colors hover:bg-paper-2 hover:text-ink" activeProps={{ className: 'bg-saffron text-paper hover:bg-saffron hover:text-paper' }}>{item.label}</Link>
  ))}</nav>;
}

function BottomNav() {
  const item = 'tap flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-ink-2 transition-colors';
  return <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-rule bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden">{navItems.map((nav) => (
    <Link key={nav.to} to={nav.to} className={item} activeProps={{ className: `${item} font-semibold text-sell` }} activeOptions={{ exact: nav.exact }}><Icon name={nav.icon}/>{nav.label}</Link>
  ))}</nav>;
}

export function AppShell() {
  const district = usePrefs((s) => s.district);
  const ticker = [`${district} mandi network`, 'Prices refreshed from official reports', 'Forecast confidence shown with every outlook', 'Tap any market to compare'];
  return (
    <div className="min-h-dvh bg-paper pb-20 lg:pb-0">
      <header className="sticky top-0 z-20 border-b border-rule bg-paper/90 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-[1440px] items-center gap-5 px-4 sm:px-6 lg:px-8">
          <Link to="/" className="flex shrink-0 items-center gap-3">
            <span className="diagonal-small grid size-9 place-items-center bg-saffron text-lg font-extrabold text-paper">K</span>
            <span className="leading-none"><strong className="block text-[17px] font-extrabold">KRISHI BAZAAR</strong><small className="mt-1 hidden font-mono text-[10px] uppercase tracking-[0.2em] text-ink-2 sm:block">Mandi intelligence</small></span>
          </Link>
          <DesktopNav />
          <div className="ml-auto flex items-center gap-2"><SyncStatus/><LanguageSwitch/></div>
        </div>
      </header>
      <OfflineBanner />
       <div className="flex overflow-hidden border-b border-rule bg-paper-2 text-ink">
         <div className="z-10 shrink-0 bg-saffron px-4 py-2 font-mono text-xs font-semibold text-paper diagonal-small">LIVE MANDI</div>
        <div className="overflow-hidden"><div className="ticker-track flex gap-10 whitespace-nowrap py-2 font-mono text-xs">{[...ticker, ...ticker].map((item, index) => <span key={`${item}-${index}`}>{item}</span>)}</div></div>
      </div>
      <main className="mx-auto max-w-[1440px] px-3 py-5 sm:px-6 lg:px-8"><Outlet /></main>
      <BottomNav />
    </div>
  );
}
