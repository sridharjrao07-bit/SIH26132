import type { ReactNode } from 'react';

/** Full-width band separated by a hairline. No cards, no shadows. */
export function Section({ title, aside, children, className = '' }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rule-b px-4 py-4 ${className}`}>
      {(title || aside) && (
        <div className="mb-3 flex items-baseline justify-between gap-3">
          {title && <h2 className="text-sm font-semibold text-ink-2">{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}
