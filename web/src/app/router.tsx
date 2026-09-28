import { createRootRoute, createRoute, createRouter, lazyRouteComponent } from '@tanstack/react-router';
import { AppShell } from './AppShell.tsx';
import { NotFoundPage } from '../features/direct/NotFoundPage.tsx';
import { TodayPage } from '../features/today/TodayPage.tsx';
import { PairDetailPage } from '../features/price-detail/PairDetailPage.tsx';
import { RANGES, type Range } from '../features/price-detail/PairView.tsx';

// URL state: shareable, survives refresh (Phase 1 §4)
const rangeSearch = (s: Record<string, unknown>): { range?: Range } => {
  const r = Number(s.range);
  return (RANGES as readonly number[]).includes(r) && r !== 30 ? { range: r as Range } : {};
};

const root = createRootRoute({ component: AppShell, notFoundComponent: NotFoundPage });
const today = createRoute({ getParentRoute: () => root, path: '/', component: TodayPage, validateSearch: rangeSearch });
const pair = createRoute({ getParentRoute: () => root, path: '/c/$crop/m/$market', component: PairDetailPage, validateSearch: rangeSearch });
const board = createRoute({
  getParentRoute: () => root, path: '/bhav', component: lazyRouteComponent(() => import('../features/board/BoardPage.tsx'), 'BoardPage'),
  validateSearch: (s: Record<string, unknown>): { crop?: string } => (typeof s.crop === 'string' ? { crop: s.crop } : {}),
});
const setup = createRoute({ getParentRoute: () => root, path: '/setup', component: lazyRouteComponent(() => import('../features/setup/SetupPage.tsx'), 'SetupPage') });
const account = createRoute({ getParentRoute: () => root, path: '/account', component: lazyRouteComponent(() => import('../features/account/AccountPage.tsx'), 'AccountPage') });
const sell = createRoute({ getParentRoute: () => root, path: '/sell', component: lazyRouteComponent(() => import('../features/sell/LotsPage.tsx'), 'LotsPage') });
const sellNew = createRoute({ getParentRoute: () => root, path: '/sell/new', component: lazyRouteComponent(() => import('../features/sell/NewLotPage.tsx'), 'NewLotPage') });
const lot = createRoute({ getParentRoute: () => root, path: '/sell/$lotId', component: lazyRouteComponent(() => import('../features/sell/LotDetailPage.tsx'), 'LotDetailPage') });
const direct = createRoute({ getParentRoute: () => root, path: '/direct', component: lazyRouteComponent(() => import('../features/direct/DirectPage.tsx'), 'DirectPage') });

export const router = createRouter({
  routeTree: root.addChildren([today, pair, board, setup, account, sell, sellNew, lot, direct]),
  defaultPreload: 'intent',
  scrollRestoration: true,
});

declare module '@tanstack/react-router' {
  interface Register { router: typeof router }
}
