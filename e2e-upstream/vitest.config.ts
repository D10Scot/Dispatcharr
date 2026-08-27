import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['test/**/*.test.ts'],
    // The seam and pacing tests move real time; the 5s default is not enough.
    testTimeout: 30_000,
  },
});
