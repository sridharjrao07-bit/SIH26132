/** Static placeholder with the same footprint as the content. No shimmer (Phase 4). */
export function Block({ h, w = '100%', className = '' }: { h: number; w?: number | string; className?: string }) {
  return <div aria-hidden className={`animate-[skeleton_1.4s_ease-in-out_infinite] rounded-lg bg-paper-2 ${className}`} style={{ height: h, width: w }} />;
}
