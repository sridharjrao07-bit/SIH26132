import { Link } from '@tanstack/react-router';
import { Trans } from '@lingui/react/macro';

/**
 * Shown for any URL the router does not match.
 *
 * Without this, TanStack Router falls back to its own bare "Not Found" and logs
 * a warning on every miss — which is how a mistyped path looks identical to a
 * broken page. The farmer-facing copy names the four places that do exist.
 */
export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-lg px-4 py-12 text-center">
      <p className="eyebrow">404</p>
      <h1 className="mt-2 text-2xl font-bold">
        <Trans>This page does not exist</Trans>
      </h1>
      <p className="mt-2 text-sm text-ink-2">
        <Trans>
          The link may be old, or the address may have a typo. These are the pages
          that work:
        </Trans>
      </p>
      <nav className="mt-6 grid gap-2 text-left" aria-label="Available pages">
        <Link to="/" className="tap panel flex items-center justify-between px-4 py-3">
          <span><Trans>Today&apos;s prices</Trans></span>
          <span aria-hidden>›</span>
        </Link>
        <Link to="/bhav" className="tap panel flex items-center justify-between px-4 py-3">
          <span><Trans>Mandi board</Trans></span>
          <span aria-hidden>›</span>
        </Link>
        <Link to="/direct" className="tap panel flex items-center justify-between px-4 py-3">
          <span><Trans>Where your rupee goes</Trans></span>
          <span aria-hidden>›</span>
        </Link>
        <Link to="/sell" className="tap panel flex items-center justify-between px-4 py-3">
          <span><Trans>Sell your produce</Trans></span>
          <span aria-hidden>›</span>
        </Link>
      </nav>
    </div>
  );
}
