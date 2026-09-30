import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import { devProxy } from './devProxy.js';

/* global process */

// https://vite.dev/config/
export default defineConfig({
  // The base URL for the build, adjust this to match your desired path
  plugins: [react()],

  // publicDir: '/data',

  server: {
    port: 9191,
    // Without this, /api/* is served as the React SPA in debug mode and
    // Swagger UI at /api/swagger/ never loads the OpenAPI schema; and since
    // #542 the live surface is proxied to relay-go (devProxy.js).
    proxy: devProxy(process.env),
  },

  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setupTests.js'],
    globals: true,
  },
});
