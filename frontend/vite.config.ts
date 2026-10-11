import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Dev proxy target: the backend on :8000 locally, or `http://backend:8000` inside docker compose.
const proxyTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
