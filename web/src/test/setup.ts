import { i18n } from '@lingui/core';
import { messages as mr } from '../i18n/locales/mr/messages.po';
import { messages as en } from '../i18n/locales/en/messages.po';

// Recharts' ResponsiveContainer needs these in jsdom
class RO { observe() {} unobserve() {} disconnect() {} }
(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = RO;
if (!HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
}

i18n.load({ mr: mr as never, en: en as never });
i18n.activate('mr');
