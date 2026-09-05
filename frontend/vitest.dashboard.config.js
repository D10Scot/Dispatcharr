// Tests for the static metrics dashboard (../dashboard). Run from frontend/
// so vitest and jsdom resolve from this package's node_modules:
//   npx vitest --run --config vitest.dashboard.config.js
//
// Uses a top-level Vite `root` (not `test.root`) plus `server.fs.allow`:
// on vitest 4.1.11, `test.root` alone leaves Vite's dev-server file access
// scoped to this package directory, so imports of files under ../dashboard
// (the fixture, the lib modules) 403 under jsdom. Root + fs.allow fixes it.
import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../dashboard', import.meta.url));

export default defineConfig({
  root,
  // Vite's default cacheDir is <root>/node_modules/.vite — with root set to
  // ../dashboard that would write into the dashboard tree itself. Keep it
  // under this package's node_modules instead, alongside the frontend
  // suite's own cache.
  cacheDir: fileURLToPath(new URL('./node_modules/.vite-dashboard', import.meta.url)),
  server: { fs: { allow: [root] } },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.js'],
    globals: true,
  },
});
