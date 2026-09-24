import type { ReactNode } from 'react';

/** Native select on purpose: the phone's own picker is faster, accessible, and costs 0 KB of JS. */
export function Select({ label, value, onChange, children, className = '' }: {
  label: string; value: string; onChange: (v: string) => void; children: ReactNode; className?: string;
}) {
  return (
    <label className={`relative block min-w-0 ${className}`}>
      <span className="sr-only">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="tap w-full appearance-none truncate rounded border border-rule bg-paper py-2 pr-8 pl-3 text-base font-semibold"
      >
        {children}
      </select>
      <svg aria-hidden className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2" width="12" height="8" viewBox="0 0 12 8">
        <path d="M1 1l5 5 5-5" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    </label>
  );
}
