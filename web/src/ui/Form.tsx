import type { InputHTMLAttributes, ReactNode } from 'react';
import { Trans } from '@lingui/react/macro';
import { ApiError } from '../api/errors.ts';

/** Labelled input with a visible label (never placeholder-only) and a field-level API error. */
export function Field({ label, hint, error, suffix, ...input }: InputHTMLAttributes<HTMLInputElement> & {
  label: ReactNode; hint?: ReactNode; error?: string; suffix?: ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-sm font-semibold text-ink-2">{label}</span>
      <span className="mt-1 flex items-center gap-2">
        <input
          {...input}
          aria-invalid={error ? true : undefined}
          className={`tap w-full min-w-0 border-b-2 bg-paper-2 px-3 pt-2 pb-1 text-base rounded-t-sm focus:outline-none focus:border-ink transition-colors ${error ? 'border-sell text-sell' : 'border-rule'} ${input.className ?? ''}`}
        />
        {suffix && <span className="shrink-0 text-sm text-ink-2 font-medium">{suffix}</span>}
      </span>
      {hint && !error && <span className="mt-1 block text-xs text-ink-2">{hint}</span>}
      {error && <span role="alert" className="mt-1 block text-xs font-semibold text-sell">{error}</span>}
    </label>
  );
}

export function NativeSelect({ label, value, onChange, children }: { label: ReactNode; value: string; onChange: (v: string) => void; children: ReactNode }) {
  return (
    <label className="block">
      <span className="text-sm font-semibold text-ink-2">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)}
        className="tap mt-1 w-full border-b-2 border-rule bg-paper-2 px-3 pt-2 pb-1 text-base rounded-t-sm focus:outline-none focus:border-ink transition-colors">
        {children}
      </select>
    </label>
  );
}

export function Button({ children, variant = 'primary', className = '', ...b }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'secondary' | 'quiet' }) {
  const style = variant === 'primary'
    ? 'bg-ink text-paper border border-ink'
    : variant === 'secondary' ? 'border border-ink' : 'underline underline-offset-4';
  return (
    <button {...b} className={`tap rounded px-4 font-semibold disabled:opacity-60 ${style} ${className}`}>{children}</button>
  );
}

export function ErrorNote({ error, className = '' }: { error: unknown, className?: string }) {
  if (!error) return null;
  const e = error instanceof ApiError ? error : null;
  let msg: ReactNode;
  switch (e?.kind) {
    case 'network': case 'timeout': msg = <Trans>No connection. Try again when you have signal.</Trans>; break;
    case 'auth': msg = <Trans>Please sign in again.</Trans>; break;
    case 'forbidden': msg = <Trans>Your account can't do this.</Trans>; break;
    case 'not_found': msg = <Trans>Not found.</Trans>; break;
    case 'rate_limited': msg = <Trans>Too many requests. Wait a minute and try again.</Trans>; break;
    case 'unavailable': case 'server': msg = <Trans>The server is having trouble. Try again shortly.</Trans>; break;
    case 'contract': msg = <Trans>The server sent something unexpected.</Trans>; break;
    default: msg = e?.message ?? (error instanceof Error ? error.message : String(error));  // 400/409/422: the server's own message
  }
  return <p role="alert" className={`rounded border border-sell px-3 py-2 text-sm text-sell ${className}`}>{msg}</p>;
}

export const fieldError = (error: unknown, field: string) =>
  error instanceof ApiError ? error.fields[field] : undefined;

/** Parse a number input; empty -> undefined so optional fields are omitted, not sent as null. */
export const numOrUndef = (s: string) => {
  const n = Number(s.replace(/,/g, ''));
  return s.trim() === '' || !Number.isFinite(n) ? undefined : n;
};
