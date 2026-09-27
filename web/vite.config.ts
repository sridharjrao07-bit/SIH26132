import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { lingui } from '@lingui/vite-plugin';
import { VitePWA } from 'vite-plugin-pwa';

// The browser only ever talks to its own origin: /api is proxied to FastAPI (or the mock).
// In production the CDN does the same rewrite, so there's no CORS and no API URL in the bundle.
const API_TARGET = process.env.API_TARGET ?? 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [
    react({ babel: { plugins: ['@lingui/babel-plugin-lingui-macro'] } }),
    lingui(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: 'Krishi Bazaar',
        short_name: 'कृषी बाजार',
        lang: 'mr',
        start_url: '/',
        display: 'standalone',
        background_color: '#F7F4EE',
        theme_color: '#F7F4EE',
        icons: [{ src: 'favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' }],
      },
      workbox: {
        // woff2 only: every phone we target supports it; the .woff fallbacks would double the precache
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        navigateFallbackDenylist: [/^\/api\//],
        runtimeCaching: [
          { // reference data: fine to serve stale, refresh in background
            urlPattern: /\/api\/v1\/(commodities|markets)\//,
            handler: 'StaleWhileRevalidate',
            options: { cacheName: 'kb-reference', expiration: { maxAgeSeconds: 7 * 86400 } },
          },
          { // prices/forecasts/advice: network first, fall back to last copy on flaky 3G
            urlPattern: /\/api\/v1\/(prices|forecasts|sale-window)/,
            handler: 'NetworkFirst',
            options: { cacheName: 'kb-data', networkTimeoutSeconds: 6, expiration: { maxEntries: 200, maxAgeSeconds: 2 * 86400 } },
          },
        ],
      },
    }),
  ],
  build: {
    rollupOptions: {
      output: {
        // Stable vendor chunks: an app deploy doesn't make farmers re-download React or Recharts.
        manualChunks(id) {
          if (!id.includes('node_modules')) return;
          if (/recharts|d3-|victory-vendor|decimal\.js|lodash|react-smooth|recharts-scale/.test(id)) return 'charts';
          // supabase-js is dynamically imported on sign-in only: keep it out of the preloaded vendor chunk
          if (/@supabase|tslib|isows|[\\/]ws[\\/]/.test(id)) return 'supabase';
          if (/[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'react';
          return 'vendor';
        },
      },
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    proxy: { '/api': { target: API_TARGET, changeOrigin: true }, '/__dev': { target: API_TARGET, changeOrigin: true } },
  },
  preview: { host: '0.0.0.0', port: 4173, allowedHosts: true, proxy: { '/api': { target: API_TARGET, changeOrigin: true } } },
  test: {
    environment: 'jsdom',
    globals: false,
    // globalSetup runs in the main Node.js thread before jsdom VMs are created;
    // it saves the native fetch so setup.ts can restore it inside each test VM.
    globalSetup: ['src/test/global-setup.ts'],
    setupFiles: ['src/test/setup.ts'],
    env: { VITE_API_BASE_URL: process.env.API_TARGET ?? 'http://127.0.0.1:8000' },
    // Use forks pool so each test file runs in a real Node.js child process.
    // The default vmThreads pool creates an isolated VM realm for jsdom which
    // breaks the native Node fetch (making integration tests fail with "network
    // unavailable"). In the forks pool, Node's global fetch is available normally.
    pool: 'forks',
    // Allow jsdom tests to reach the local mock API on :8000.
    testEnvironmentOptions: {
      url: 'http://127.0.0.1:8000',
      pretendToBeVisual: true,
      resources: 'usable',
    },
  },
});
