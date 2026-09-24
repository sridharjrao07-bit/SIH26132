import { useState } from 'react';
import { Link } from '@tanstack/react-router';
import { Trans, useLingui } from '@lingui/react/macro';
import { RequireAuth } from '../../auth/RequireAuth.tsx';
import { account } from '../../api/index.ts';
import type { Profile } from '../../api/schemasMarket.ts';
import type { ProfilePatch } from '../../api/endpoints/account.ts';
import { useAuthMutation, useSignOut } from '../../queries/auth.ts';
import { usePrefs } from '../../stores/prefs.ts';
import { LANGS, LANG_LABEL, type Lang } from '../../i18n/locales.ts';
import { Button, ErrorNote, Field, NativeSelect, fieldError } from '../../ui/Form.tsx';

/** "9812345678" -> "+919812345678". Anything else is sent as typed and the server decides. */
export const toE164 = (s: string) => {
  const d = s.replace(/\D/g, '');
  if (d.length === 10) return `+91${d}`;
  if (d.length === 12 && d.startsWith('91')) return `+${d}`;
  return s.trim();
};

export function AccountPage() {
  const { t } = useLingui();
  return (
    <RequireAuth why={t`Your account holds your phone number for SMS alerts and the produce you list for sale.`}>
      {(me) => <Account me={me} />}
    </RequireAuth>
  );
}

function Account({ me }: { me: Profile }) {
  const setLang = usePrefs((s) => s.setLang);
  const signOut = useSignOut();
  const [name, setName] = useState(me.name ?? '');
  const [phone, setPhone] = useState(me.phone ?? '');
  const [district, setDistrict] = useState(me.district ?? '');
  const [language, setLanguage] = useState<Lang>(me.preferred_language);
  const [saved, setSaved] = useState(false);
  const save = useAuthMutation((p: ProfilePatch) => account.update(p), (p) => {
    setLang(p.preferred_language);
    setSaved(true);
  });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(false);
    const patch: ProfilePatch = {};
    if (name.trim() !== (me.name ?? '')) patch.name = name.trim();
    if (phone.trim() && toE164(phone) !== me.phone) patch.phone = toE164(phone);
    if (district.trim() !== (me.district ?? '')) patch.district = district.trim();
    if (language !== me.preferred_language) patch.preferred_language = language;
    if (Object.keys(patch).length) save.mutate(patch); else setSaved(true);
  };

  /* Initials for avatar */
  const initials = (me.name ?? 'U')
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase();

  const roleLabel =
    me.role === 'farmer' ? <Trans>Farmer account</Trans>
    : me.role === 'buyer' ? <Trans>Buyer account</Trans>
    : me.role === 'fpo'   ? <Trans>FPO account</Trans>
    :                       <Trans>Admin account</Trans>;

  return (
    <div className="mx-auto max-w-2xl">

      {/* ── PROFILE HERO (dark ink) ──────────────────────────────── */}
      <div
        className="px-4 pt-8 pb-6"
        style={{ background: 'linear-gradient(135deg, #0F0E0C 0%, #1C1A17 60%, #0F0E0C 100%)' }}
      >
        <div className="flex items-center gap-4">
          {/* Avatar circle */}
          <div
            className="flex size-16 shrink-0 items-center justify-center rounded-full text-xl font-bold text-white"
            style={{ background: 'var(--color-accent)' }}
            aria-label={me.name ?? 'User'}
          >
            {initials}
          </div>
          <div>
            <p className="text-xl font-bold text-white">{me.name ?? <Trans>Your Account</Trans>}</p>
            <span
              className="inline-block text-xs font-semibold mt-1 px-2 py-0.5 rounded-md"
              style={{ background: 'var(--color-accent-tint)', color: 'var(--color-accent)' }}
            >
              {roleLabel}
            </span>
            {me.phone && (
              <p className="text-sm text-white/50 mt-1">{me.phone}</p>
            )}
          </div>
        </div>
      </div>

      <div className="px-4 pb-8">

        {/* ── DETAILS FORM CARD (paper surface, shadow) ─────────── */}
        <div
          className="rounded-2xl p-4 md:p-6 mt-4 border border-rule"
          style={{ background: 'var(--color-paper)', boxShadow: 'var(--shadow-card)' }}
        >
          <h2 className="text-base font-bold text-ink mb-4"><Trans>Your details</Trans></h2>
          <form onSubmit={submit} className="space-y-4">
            <Field
              label={<Trans>Name</Trans>}
              autoComplete="name"
              value={name}
              onChange={(e) => { setName(e.target.value); setSaved(false); }}
              error={fieldError(save.error, 'name')}
            />
            <Field
              label={<Trans>Mobile number</Trans>}
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              value={phone}
              onChange={(e) => { setPhone(e.target.value); setSaved(false); }}
              error={fieldError(save.error, 'phone')}
              hint={<Trans>SMS alerts go to this number.</Trans>}
            />
            <Field
              label={<Trans>District</Trans>}
              value={district}
              onChange={(e) => { setDistrict(e.target.value); setSaved(false); }}
              error={fieldError(save.error, 'district')}
            />
            <NativeSelect
              label={<Trans>SMS and advice language</Trans>}
              value={language}
              onChange={(v) => { setLanguage(v as Lang); setSaved(false); }}
            >
              {LANGS.map((l) => (
                <option key={l} value={l} lang={l}>{LANG_LABEL[l]}</option>
              ))}
            </NativeSelect>
            <ErrorNote
              error={Object.keys((save.error as { fields?: object } | null)?.fields ?? {}).length ? null : save.error}
            />

            <div className="pt-1 flex items-center justify-between">
              {saved && (
                <p role="status" className="text-sm font-semibold" style={{ color: 'var(--color-sell)' }}>
                  <Trans>Saved successfully.</Trans>
                </p>
              )}
              <Button
                type="submit"
                disabled={save.isPending}
                className="ml-auto w-full md:w-auto px-8 rounded-xl"
                style={{ background: 'var(--color-accent)', color: 'white', border: 'none' }}
              >
                <Trans>Save changes</Trans>
              </Button>
            </div>
          </form>
        </div>

        {/* ── QUICK LINKS CARD (paper-2 surface) ───────────────── */}
        <div
          className="rounded-2xl p-4 mt-4 border border-rule"
          style={{ background: 'var(--color-paper-2)' }}
        >
          <h2 className="text-base font-bold text-ink mb-3"><Trans>Quick links</Trans></h2>
          <ul className="divide-y divide-rule">
            <li>
              <Link
                to="/sell"
                className="tap flex items-center gap-3 py-3 hover:text-accent transition-colors"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><circle cx="7" cy="7" r="1.5" fill="var(--color-accent)" stroke="none"/>
                </svg>
                <span className="flex-1 text-sm font-medium"><Trans>My produce for sale</Trans></span>
                <span aria-hidden className="text-ink-2">›</span>
              </Link>
            </li>
            {me.role !== 'fpo' && me.role !== 'admin' && (
              <li>
                <Link
                  to="/buy"
                  className="tap flex items-center gap-3 py-3 hover:text-accent transition-colors"
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="M6 2 L3 6 L3 20 A2 2 0 0 0 5 22 L19 22 A2 2 0 0 0 21 20 L21 6 L18 2 Z"/><path d="M3 6 L21 6"/><path d="M16 10 A4 4 0 0 1 8 10"/>
                  </svg>
                  <span className="flex-1 text-sm font-medium"><Trans>I buy produce</Trans></span>
                  <span aria-hidden className="text-ink-2">›</span>
                </Link>
              </li>
            )}
            <li>
              <Link
                to="/forecasts/about"
                className="tap flex items-center gap-3 py-3 hover:text-accent transition-colors"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                  <circle cx="12" cy="12" r="10"/><path d="M12 16v-4m0-4h.01"/>
                </svg>
                <span className="flex-1 text-sm font-medium"><Trans>About forecasts</Trans></span>
                <span aria-hidden className="text-ink-2">›</span>
              </Link>
            </li>
          </ul>
        </div>

        {/* ── SIGN OUT ─────────────────────────────────────────── */}
        <div className="mt-6 text-center">
          <Button
            variant="quiet"
            className="border border-rule rounded-xl px-8 text-ink-2 hover:bg-paper-2 transition-colors"
            onClick={signOut}
          >
            <Trans>Sign out</Trans>
          </Button>
          <p className="mt-2 text-xs text-ink-2">
            <Trans>You will need to sign in again to manage alerts and listings.</Trans>
          </p>
        </div>
      </div>
    </div>
  );
}
