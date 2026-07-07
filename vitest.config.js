import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['webui/tests/**/*.test.js'],
    exclude: ['**/node_modules/**', '**/vendor/**', '**/data/**'],
    environment: 'node', // overridden per-file via "@vitest-environment happy-dom" where DOM is needed
    globals: false,
  },
});
