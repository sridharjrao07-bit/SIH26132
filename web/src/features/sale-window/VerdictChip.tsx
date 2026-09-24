import type { SaleWindow } from '../../api/schemas.ts';
import { VERDICT_BG } from './verdict.ts';

/** Compact verdict above the fold (Phase 3 decision 1). Taps through to the full card. */
export function VerdictChip({ sale }: { sale: SaleWindow }) {
  // Use pulse-glow if it's a SELL recommendation, otherwise a neutral glow
  const glow = sale.action === 'SELL_NOW' ? 'pulse-glow' : 'shadow-sm';
  return (
    <a href="#verdict" className={`tap inline-flex items-center gap-2 px-4 py-2 mt-2 rounded-lg ${VERDICT_BG[sale.action]} ${glow} transition-transform active:scale-95 hover:shadow-md`}>
      <span className="text-white font-headline-md text-headline-md font-bold tracking-wide">{sale.action_label}</span>
      <span aria-hidden className="text-white/80 ml-1">›</span>
    </a>
  );
}
