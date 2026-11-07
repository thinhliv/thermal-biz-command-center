/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/** Cổng FastAPI. Khớp API_PORT trong .env ở thư mục gốc. */
const BACKEND = 'http://localhost:8080';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
    // Dev chạy qua proxy để tránh CORS và để frontend dùng đường dẫn tương đối,
    // giống hệt cách bản Electron/Capacitor gọi API.
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true },
      '/ws': { target: BACKEND, ws: true, changeOrigin: true },
    },
  },
  base: './', // Essential for Electron and Capacitor offline local loading
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
});
