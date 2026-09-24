/** Static placeholder with the same footprint as the content. No shimmer (Phase 4). */
export function Block({ h, w = '100%', className = '' }: { h: number; w?: number | string; className?: string }) {
  return <div aria-hidden className={`rounded-sm bg-paper-2 ${className}`} style={{ height: h, width: w }} />;
}
