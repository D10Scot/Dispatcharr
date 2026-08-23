import { defineConfig } from '@playwright/test';

const baseURL = process.env.E2E_BASE_URL || 'http://localhost:9191';

export default defineConfig({
  timeout: 30_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : 'list',
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'bootstrap',
      testDir: './setup',
      testMatch: /.*\.setup\.ts/,
    },
    {
      name: 'pristine',
      testDir: './tests/pristine',
      workers: 1,
      fullyParallel: false,
      // Never retry, whatever the global setting says. These tests consume
      // first-run state: attempt 1 creates the superuser, so attempt 2 is
      // served the login form instead of the setup form and dies on the first
      // assertion — making every pristine failure report the same wrong
      // error, whatever actually broke. `seeded` and `streaming` may retry
      // safely: their seeded names carry fresh runToken entropy per attempt.
      retries: 0,
    },
    {
      name: 'seeded',
      testDir: './tests/seeded',
      dependencies: ['bootstrap'],
      fullyParallel: true,
      workers: 4,
      use: { storageState: 'playwright/.auth/admin.json' },
    },
    {
      name: 'streaming',
      testDir: './tests/streaming',
      dependencies: ['bootstrap'],
      timeout: 300_000,
      workers: 2,
    },
  ],
});
