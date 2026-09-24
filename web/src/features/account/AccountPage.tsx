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
    <div className="mx-auto max-w-2xl px-4 py-6 md:py-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold"><Trans>Account</Trans></h1>
        <p className="mt-1 text-ink-2 font-medium">
          {me.role === 'farmer' ? <Trans>Farmer account</Trans> : me.role === 'buyer' ? <Trans>Buyer account</Trans>
            : me.role === 'fpo' ? <Trans>FPO account</Trans> : <Trans>Admin account</Trans>}
        </p>
      </div>
      
      <div className="mb-10 border-b-2 border-ink pb-8">
        <h2 className="text-xl font-semibold mb-6"><Trans>Your details</Trans></h2>
        <form onSubmit={submit} className="space-y-5">
          <Field label={<Trans>Name</Trans>} autoComplete="name" value={name} onChange={(e) => { setName(e.target.value); setSaved(false); }} error={fieldError(save.error, 'name')} />
          <Field label={<Trans>Mobile number</Trans>} type="tel" inputMode="tel" autoComplete="tel" value={phone}
            onChange={(e) => { setPhone(e.target.value); setSaved(false); }} error={fieldError(save.error, 'phone')}
            hint={<Trans>SMS alerts go to this number.</Trans>} />
          <Field label={<Trans>District</Trans>} value={district} onChange={(e) => { setDistrict(e.target.value); setSaved(false); }} error={fieldError(save.error, 'district')} />
          <NativeSelect label={<Trans>SMS and advice language</Trans>} value={language} onChange={(v) => { setLanguage(v as Lang); setSaved(false); }}>
            {LANGS.map((l) => <option key={l} value={l} lang={l}>{LANG_LABEL[l]}</option>)}
          </NativeSelect>
          <ErrorNote error={Object.keys((save.error as { fields?: object } | null)?.fields ?? {}).length ? null : save.error} />
          
          <div className="pt-2 flex items-center justify-between">
            {saved && <p role="status" className="text-sm font-semibold text-buy"><Trans>Saved successfully.</Trans></p>}
            <Button type="submit" disabled={save.isPending} className="ml-auto w-full md:w-auto px-8"><Trans>Save changes</Trans></Button>
          </div>
        </form>
      </div>

      <div className="mb-10">
        <h2 className="text-xl font-semibold mb-4"><Trans>Quick links</Trans></h2>
        <ul className="text-base divide-y divide-rule border-y border-rule">
          <li><Link to="/sell" className="tap flex items-center justify-between py-4 hover:bg-paper-2 transition-colors"><Trans>My produce for sale</Trans><span aria-hidden>›</span></Link></li>
          {me.role !== 'fpo' && me.role !== 'admin' && (
            <li><Link to="/buy" className="tap flex items-center justify-between py-4 hover:bg-paper-2 transition-colors"><Trans>I buy produce</Trans><span aria-hidden>›</span></Link></li>
          )}
          <li><Link to="/forecasts/about" className="tap flex items-center justify-between py-4 hover:bg-paper-2 transition-colors"><Trans>About forecasts</Trans><span aria-hidden>›</span></Link></li>
        </ul>
      </div>

      <div className="pt-4 flex justify-center">
        <Button variant="quiet" className="text-sell border border-sell/30 hover:bg-sell/10 px-6 py-2 rounded transition-colors" onClick={signOut}><Trans>Sign out</Trans></Button>
      </div>
    </div>
  );
}
