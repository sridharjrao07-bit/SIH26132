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
    <div role="group" aria-label={t`Language`} className="flex text-xs gap-1">
      {LANGS.map((l) => (
        <button
          key={l}
          lang={l}
          onClick={() => setLang(l)}
          aria-pressed={lang === l}
          className={`tap px-2 rounded-md transition-colors ${
            lang === l
              ? 'bg-accent text-white font-semibold'
              : 'text-ink-2 hover:bg-paper-2'
          }`}
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
      <span
        aria-hidden
        className={`inline-block size-2 rounded-full transition-colors ${
          online
            ? fetching
              ? 'bg-ink-2 animate-pulse'
              : 'bg-sell'
            : 'border border-ink-2'
        }`}
      />
      {!online ? (
        <Trans>Offline</Trans>
      ) : fetching ? (
        <Trans>Updating…</Trans>
      ) : (
        <Trans>Live</Trans>
      )}
    </span>
  );
}

/** Slide-in from top, accent-tinted warning banner. */
function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  return (
    <div
      role="status"
      style={{ animation: 'toast-in 240ms cubic-bezier(0.4,0,0.2,1) both' }}
      className="rule-b bg-hold-tint border-hold/30 px-4 py-2 text-sm font-medium text-hold"
    >
      <svg className="inline mr-1.5 -mt-0.5" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <circle cx="12" cy="12" r="10"/><path d="M12 8v4m0 4h.01"/>
      </svg>
      <Trans>Offline — showing saved prices. Check the date on each price.</Trans>
    </div>
  );
}

/* SVG icons for the bottom nav ─────────────────────────────────── */
function IconToday({ active }: { active: boolean }) {
  const c = active ? 'var(--color-accent)' : 'var(--color-ink-2)';
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
    </svg>
  );
}
function IconPrices({ active }: { active: boolean }) {
  const c = active ? 'var(--color-accent)' : 'var(--color-ink-2)';
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/>
    </svg>
  );
}
function IconSell({ active }: { active: boolean }) {
  const c = active ? 'var(--color-accent)' : 'var(--color-ink-2)';
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5" fill={c} stroke="none"/>
    </svg>
  );
}
function IconAlerts({ active }: { active: boolean }) {
  const c = active ? 'var(--color-accent)' : 'var(--color-ink-2)';
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>
    </svg>
  );
}
function IconAccount({ active }: { active: boolean }) {
  const c = active ? 'var(--color-accent)' : 'var(--color-ink-2)';
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>
    </svg>
  );
}

type NavTab = { to: string; labelEl: React.ReactNode; Icon: React.FC<{ active: boolean }>; exact?: boolean };

const NAV_TABS: NavTab[] = [
  { to: '/',       labelEl: <Trans>Today</Trans>,   Icon: IconToday,   exact: true },
  { to: '/bhav',   labelEl: <Trans>Prices</Trans>,  Icon: IconPrices },
  { to: '/sell',   labelEl: <Trans>Sell</Trans>,    Icon: IconSell },
  { to: '/alerts', labelEl: <Trans>Alerts</Trans>,  Icon: IconAlerts },
  { to: '/account',labelEl: <Trans>Account</Trans>, Icon: IconAccount },
];

function BottomNav() {
  return (
    <nav
      className="rule-t fixed inset-x-0 bottom-0 z-10 flex bg-paper pb-[env(safe-area-inset-bottom)]"
      aria-label="Main navigation"
    >
      {NAV_TABS.map(({ to, labelEl, Icon, exact }) => (
        <Link
          key={to}
          to={to}
          activeOptions={exact ? { exact: true } : undefined}
          className="tap relative flex flex-1 flex-col items-center justify-center gap-0.5 text-xs text-ink-2 transition-colors"
          activeProps={{
            className: 'tap relative flex flex-1 flex-col items-center justify-center gap-0.5 text-xs font-semibold !text-accent transition-colors',
          }}
        >
          {({ isActive }) => (
            <>
              <Icon active={isActive} />
              <span>{labelEl}</span>
              {/* Sliding active indicator — transform-only, no JS */}
              {isActive && (
                <span
                  aria-hidden
                  className="absolute top-0 inset-x-4 h-0.5 rounded-full bg-accent"
                  style={{ animation: 'nav-slide 200ms cubic-bezier(0.16,1,0.3,1) both' }}
                />
              )}
            </>
          )}
        </Link>
      ))}
    </nav>
  );
}

function TopNav() {
  const { t } = useLingui();
  return (
    <header className="rule-b sticky top-0 z-50 bg-paper">
      <div className="mx-auto flex h-14 max-w-[1120px] items-center justify-between px-4 lg:px-10">
        {/* Brand */}
        <Link to="/" className="flex items-center gap-2.5 tap" aria-label={t`Krishi Bazaar home`}>
          {/* Wheat/grain icon in accent circle */}
          <div
            className="flex size-8 shrink-0 items-center justify-center rounded-lg"
            style={{ background: 'var(--color-accent)' }}
            aria-hidden
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L12 22"/><path d="M5 7 Q8 4 12 6 Q16 4 19 7"/><path d="M5 11 Q8 8 12 10 Q16 8 19 11"/><path d="M5 15 Q8 12 12 14 Q16 12 19 15"/>
            </svg>
          </div>
          <div>
            <p className="text-sm font-bold leading-tight tracking-tight text-ink">
              <Trans>Krishi Bazaar</Trans>
            </p>
            <p className="text-[11px] leading-none text-ink-2">
              <Trans>कृषी बाजार</Trans>
            </p>
          </div>
        </Link>

        <div className="flex items-center gap-3">
          <SyncStatus />
          <div className="h-4 w-px bg-rule" aria-hidden />
          <LanguageSwitch />

          {/* Desktop nav links */}
          <nav className="hidden lg:flex items-center gap-1 ml-4" aria-label="Desktop navigation">
            {NAV_TABS.map(({ to, labelEl, exact }) => (
              <Link
                key={to}
                to={to}
                activeOptions={exact ? { exact: true } : undefined}
                className="tap px-3 text-sm text-ink-2 hover:text-ink rounded-lg hover:bg-paper-2 transition-colors"
                activeProps={{ className: 'tap px-3 text-sm font-semibold !text-accent rounded-lg hover:bg-accent-tint transition-colors' }}
              >
                {labelEl}
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </header>
  );
}

export function AppShell() {
  return (
    <div className="min-h-dvh bg-paper text-ink antialiased pb-16 lg:pb-0">
      <TopNav />
      <OfflineBanner />
      <main className="mx-auto max-w-[1120px]">
        <Outlet />
      </main>
      {/* Bottom nav only on mobile */}
      <div className="lg:hidden">
        <BottomNav />
      </div>
    </div>
  );
}
