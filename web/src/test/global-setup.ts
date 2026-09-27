// Vitest global setup: runs in the main Node.js thread before any test environments
// (including jsdom) are created. We save the native fetch here so the per-test setup
// can restore it inside jsdom's restricted VM context.
export default function setup() {
  // globalThis here is the real Node.js globalThis (not a jsdom VM).
  // Stash the native fetch so setup.ts can read it.
  (globalThis as unknown as Record<string, unknown>).__nativeFetch = globalThis.fetch;
  (globalThis as unknown as Record<string, unknown>).__nativeHeaders = globalThis.Headers;
  (globalThis as unknown as Record<string, unknown>).__nativeRequest = globalThis.Request;
  (globalThis as unknown as Record<string, unknown>).__nativeResponse = globalThis.Response;
}
