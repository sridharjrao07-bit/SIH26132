import type { ReactNode } from 'react';

/** Elevated Bento Card style. */
export function Section({ title, aside, children, className = '' }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`glass-tile rounded-2xl p-6 relative m-4 ${className} hover:shadow-lg transition-all duration-300`}>
      {(title || aside) && (
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-5 mb-4">
          {title && <h2 className="font-headline-md text-headline-md font-bold text-slate-900 tracking-tight">{title}</h2>}
          {aside && <div className="flex flex-wrap items-center gap-3">{aside}</div>}
        </div>
      )}
      {children}
    </section>
  );
}
