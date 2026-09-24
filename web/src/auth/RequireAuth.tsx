import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from '@tanstack/react-router';
import { Trans, useLingui } from '@lingui/react/macro';
import { useSession, supabaseConfigured, devAuthEnabled, signInWithPassword, signUp, devSignIn } from './session.ts';
import { meQuery } from '../queries/auth.ts';
import { Button, ErrorNote, Field } from '../ui/Form.tsx';
import { Block } from '../ui/Skeleton.tsx';
import type { Profile } from '../api/schemasMarket.ts';

/** Price discovery never needs an account. Only alerts and selling do, and they say why. */
export function SignIn({ why }: { why: ReactNode }) {
  const { t } = useLingui();
  const [mode, setMode] = useState<'in' | 'up'>('in');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sent, setSent] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      if (mode === 'in') await signInWithPassword(email, password);
      else if ((await signUp(email, password)).needsConfirmation) setSent(true);
    } catch (err) { setError(err); } finally { setBusy(false); }
  };

  const dev = async (role: 'farmer' | 'buyer' | 'fpo') => {
    setBusy(true); setError(null);
    try { await devSignIn(role); } catch (err) { setError(err); } finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-md px-4 py-4">
      <h1 className="text-lg font-semibold">{mode === 'in' ? <Trans>Sign in</Trans> : <Trans>Create account</Trans>}</h1>
      <p className="mt-1 text-sm text-ink-2">{why}</p>
      {supabaseConfigured ? (
        sent ? (
          <p className="mt-4 text-sm"><Trans>Check your email to confirm the account, then sign in.</Trans></p>
        ) : (
          <form onSubmit={submit} className="mt-4 space-y-3">
            <Field label={t`Email`} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            <Field label={t`Password`} type="password" autoComplete={mode === 'in' ? 'current-password' : 'new-password'} required minLength={6}
              value={password} onChange={(e) => setPassword(e.target.value)} />
            <ErrorNote error={error} />
            <Button type="submit" disabled={busy} className="w-full">{mode === 'in' ? <Trans>Sign in</Trans> : <Trans>Create account</Trans>}</Button>
            <Button type="button" variant="quiet" className="w-full" onClick={() => setMode(mode === 'in' ? 'up' : 'in')}>
              {mode === 'in' ? <Trans>New here? Create an account</Trans> : <Trans>Already have an account? Sign in</Trans>}
            </Button>
          </form>
        )
      ) : !devAuthEnabled && (
        <p className="mt-4 text-sm"><Trans>Sign-in is not configured on this build.</Trans></p>
      )}
      {devAuthEnabled && (
        <div className="mt-6 rule-t pt-4">
          <p className="text-xs text-ink-2"><Trans>Development only: sign in to the mock server as</Trans></p>
          <div className="mt-2 grid grid-cols-3 gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => dev('farmer')}><Trans>Farmer</Trans></Button>
            <Button variant="secondary" disabled={busy} onClick={() => dev('buyer')}><Trans>Buyer</Trans></Button>
            <Button variant="secondary" disabled={busy} onClick={() => dev('fpo')}>FPO</Button>
          </div>
          {!supabaseConfigured && <div className="mt-3"><ErrorNote error={error} /></div>}
        </div>
      )}
      <p className="mt-6 rule-t pt-3 text-sm">
        <Trans>Prices, forecasts and advice work without an account.</Trans>{' '}
        <Link to="/forecasts/about" className="underline underline-offset-4"><Trans>How forecasts work</Trans></Link>
      </p>
    </div>
  );
}

/** Renders children with the loaded profile, or the sign-in screen. */
export function RequireAuth({ why, children }: { why: ReactNode; children: (me: Profile) => ReactNode }) {
  const userId = useSession((s) => s.userId);
  const me = useQuery({ ...meQuery(), enabled: !!userId });
  if (!userId) return <SignIn why={why} />;
  if (me.isPending) return <div className="p-4"><Block h={160} /></div>;
  if (me.isError) return <div className="p-4"><ErrorNote error={me.error} /></div>;
  return <>{children(me.data)}</>;
}
