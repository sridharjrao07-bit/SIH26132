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
import { Section } from '../../ui/Section.tsx';

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
  const save = useAuthMutation((p: ProfilePatch) => account.update(p), (p) => { setLang(p.preferred_language); setSaved(true); });

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(false);
    // PATCH semantics: omission = unchanged (§9.8). Only send what the user changed.
    const patch: ProfilePatch = {};
    if (name.trim() !== (me.name ?? '')) patch.name = name.trim();
    if (phone.trim() && toE164(phone) !== me.phone) patch.phone = toE164(phone);
    if (district.trim() !== (me.district ?? '')) patch.district = district.trim();
    if (language !== me.preferred_language) patch.preferred_language = language;
    if (Object.keys(patch).length) save.mutate(patch); else setSaved(true);
  };

  return (
    <div className="mx-auto max-w-2xl">
      <div className="px-4 pt-4">
        <h1 className="text-lg font-semibold"><Trans>Account</Trans></h1>
        <p className="mt-1 text-sm text-ink-2">
          {me.role === 'farmer' ? <Trans>Farmer account</Trans> : me.role === 'buyer' ? <Trans>Buyer account</Trans>
            : me.role === 'fpo' ? <Trans>FPO account</Trans> : <Trans>Admin account</Trans>}
        </p>
      </div>
      <Section title={<Trans>Your details</Trans>}>
        <form onSubmit={submit} className="space-y-3">
          <Field label={<Trans>Name</Trans>} autoComplete="name" value={name} onChange={(e) => { setName(e.target.value); setSaved(false); }} error={fieldError(save.error, 'name')} />
          <Field label={<Trans>Mobile number</Trans>} type="tel" inputMode="tel" autoComplete="tel" value={phone}
            onChange={(e) => { setPhone(e.target.value); setSaved(false); }} error={fieldError(save.error, 'phone')}
            hint={<Trans>SMS alerts go to this number.</Trans>} />
          <Field label={<Trans>District</Trans>} value={district} onChange={(e) => { setDistrict(e.target.value); setSaved(false); }} error={fieldError(save.error, 'district')} />
          <NativeSelect label={<Trans>SMS and advice language</Trans>} value={language} onChange={(v) => { setLanguage(v as Lang); setSaved(false); }}>
            {LANGS.map((l) => <option key={l} value={l} lang={l}>{LANG_LABEL[l]}</option>)}
          </NativeSelect>
          <ErrorNote error={Object.keys((save.error as { fields?: object } | null)?.fields ?? {}).length ? null : save.error} />
          {saved && <p role="status" className="text-sm font-semibold"><Trans>Saved.</Trans></p>}
          <Button type="submit" disabled={save.isPending} className="w-full"><Trans>Save</Trans></Button>
        </form>
      </Section>
      <Section>
        <ul className="-my-2 text-base">
          <li><Link to="/sell" className="tap flex items-center justify-between"><Trans>My produce for sale</Trans><span aria-hidden>›</span></Link></li>
          <li className="rule-t"><Link to="/direct" className="tap flex items-center justify-between"><Trans>Where my rupee goes</Trans><span aria-hidden>›</span></Link></li>
        </ul>
      </Section>
      <div className="px-4 py-4">
        <Button variant="secondary" className="w-full" onClick={signOut}><Trans>Sign out</Trans></Button>
      </div>
    </div>
  );
}
