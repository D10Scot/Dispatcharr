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
