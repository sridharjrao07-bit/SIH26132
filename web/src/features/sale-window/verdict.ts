import type { SaleWindow } from '../../api/schemas.ts';

// Colour exists on the verdict only (Phase 4). Both the chip and the card read the SAME
// `action` field from the SAME query: the verdict is never computed on the client.
export const VERDICT_TEXT: Record<SaleWindow['action'], string> = {
  SELL_NOW: 'text-sell', HOLD: 'text-hold', WAIT: 'text-wait',
};
export const VERDICT_BG: Record<SaleWindow['action'], string> = {
  SELL_NOW: 'bg-sell', HOLD: 'bg-hold', WAIT: 'bg-wait',
};
