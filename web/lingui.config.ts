import { defineConfig } from '@lingui/cli';

export default defineConfig({
  sourceLocale: 'en',
  locales: ['mr', 'hi', 'en'],
  catalogs: [{ path: '<rootDir>/src/i18n/locales/{locale}/messages', include: ['src'] }],
  format: 'po',
});
