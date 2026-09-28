import { vi } from 'vitest';
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

// Integration tests hit the local mock server on :8000 which is a different origin.
// jsdom's VM context may not have access to Node's native fetch (undici). Use
// vi.stubGlobal to replace fetch with the undici fetch that Node 18+ ships natively
// so that integration API calls succeed in the test environment.
// This does NOT affect unit tests — they don't make real network calls.
// Helper to wrap fetch and strip signal (jsdom's AbortSignal fails undici's instanceof check)
function wrapFetchWithSignalStrip(originalFetch: any) {
  return function (input: RequestInfo | URL, init?: RequestInit) {
    if (init && init.signal) {
      delete init.signal;
    }
    return originalFetch(input, init);
  };
}

try {
  // No @ts-expect-error here: on the TypeScript version this repo resolves, `undici`
  // already has ambient types, so the directive is unused and tsc rejects it. If a
  // future upgrade drops those types the error reappears and it needs restoring.
  const { fetch: undiciFetch, Headers: UHeaders, Request: URequest, Response: UResponse } =
    await import('undici');
  vi.stubGlobal('fetch', wrapFetchWithSignalStrip(undiciFetch));
  vi.stubGlobal('Headers', UHeaders);
  vi.stubGlobal('Request', URequest);
  vi.stubGlobal('Response', UResponse);
} catch {
  // undici not available
}

const g = globalThis as unknown as Record<string, unknown>;
if (g.__nativeFetch) globalThis.fetch = wrapFetchWithSignalStrip(g.__nativeFetch);
if (g.__nativeHeaders) globalThis.Headers = g.__nativeHeaders as typeof Headers;
if (g.__nativeRequest) globalThis.Request = g.__nativeRequest as typeof Request;
if (g.__nativeResponse) globalThis.Response = g.__nativeResponse as typeof Response;

i18n.load({ mr: mr as never, en: en as never });
i18n.activate('mr');


