import type { ReactNode } from 'react';

/** Premium section card — paper surface with accent heading. */
export function Section({
  title,
  aside,
  children,
  className = '',
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`py-6 border-b border-rule last:border-b-0 ${className}`}>
      {(title || aside) && (
        <div className="flex flex-col md:flex-row md:items-baseline justify-between gap-3 mb-5">
          {title && (
            <h2 className="text-lg font-semibold leading-snug text-ink">{title}</h2>
          )}
          {aside && (
            <div className="flex items-center gap-1">{aside}</div>
          )}
        </div>
      )}
      {children}
    </section>
  );
}
