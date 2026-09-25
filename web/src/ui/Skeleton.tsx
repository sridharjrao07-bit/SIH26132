/**
 * Block — animated pulse skeleton, sized to match final layout.
 * Dark variant for use inside ink-hero panels.
 */
export function Block({
  h,
  w = '100%',
  className = '',
  dark = false,
}: {
  h: number;
  w?: number | string;
  className?: string;
  dark?: boolean;
}) {
  return (
    <div
      aria-hidden
      className={`rounded-lg ${dark ? 'bg-white/10' : 'bg-paper-2'} animate-pulse-soft ${className}`}
      style={{ height: h, width: w, animation: 'pulse-soft 1.4s ease-in-out infinite' }}
    />
  );
}
