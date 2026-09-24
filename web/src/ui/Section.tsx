import type { ReactNode } from 'react';

/** Elevated Bento Card style. */
export function Section({ title, aside, children, className = '' }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`px-4 py-6 md:py-8 border-b-2 border-rule last:border-b-0 ${className}`}>
      {(title || aside) && (
        <div className="flex flex-col md:flex-row md:items-baseline justify-between gap-4 mb-6">
          {title && <h2 className="text-xl md:text-2xl font-semibold leading-tight text-ink">{title}</h2>}
          {aside && <div className="flex items-center gap-3 text-sm font-medium">{aside}</div>}
        </div>
      )}
      {children}
    </section>
  );
}
