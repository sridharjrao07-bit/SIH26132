import { Trans } from '@lingui/react/macro';

/** Placeholder until auth lands. Alerts are delivered by SMS; the app only manages them. */
export function AlertsPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-4">
      <h1 className="text-lg font-semibold"><Trans>Price alerts</Trans></h1>
      <p className="mt-2 text-sm"><Trans>Get an SMS when the price at your mandi goes above or below a price you choose.</Trans></p>
      <p className="mt-2 text-sm text-ink-2"><Trans>Alerts arrive by SMS, not in this app. Signing in is needed to set them up. This screen is coming next.</Trans></p>
    </div>
  );
}
