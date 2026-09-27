import type { ReactNode } from 'react';

/** Full-width band separated by a hairline. No cards, no shadows. */
export function Section({ title, aside, children, className = '' }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel diagonal-panel reveal px-4 py-4 sm:px-5 sm:py-5 ${className}`}>
      {(title || aside) && (
        <div className="mb-3 flex items-baseline justify-between gap-3">
          {title && <h2 className="font-mono text-xs font-semibold uppercase tracking-[0.12em] text-ink-2">{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}
