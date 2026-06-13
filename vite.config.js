import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
  root: 'webui',
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.js'],
  },
});
