import type { SaleWindow } from '../../api/schemas.ts';
import { VERDICT_BG, VERDICT_TEXT } from './verdict.ts';

/** Compact verdict above the fold (Phase 3 decision 1). Taps through to the full card. */
export function VerdictChip({ sale }: { sale: SaleWindow }) {
  return (
    <a href="#verdict" className="tap flex items-center gap-3">
      <span aria-hidden className={`h-7 w-[3px] ${VERDICT_BG[sale.action]}`} />
      <span className={`text-lg font-semibold ${VERDICT_TEXT[sale.action]}`}>{sale.action_label}</span>
      <span aria-hidden className="ml-auto text-ink-2">›</span>
    </a>
  );
}
