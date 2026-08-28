import { defineConfig } from '@playwright/test';
import { MAX_LOGIN_WAIT_MS } from './setup/login';
import { PRINCIPAL_NAMES } from './setup/principals';

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
      // Longer than the global 30s because this is the one place allowed to
      // wait out the login throttle: every login here — the admin's and one
      // per principal — backs off for a window rather than failing when the
      // 3/minute budget is already spent. Safe where nothing runs in parallel
      // and no test is waiting, and impossible in a worker.
      //
      // Derived rather than a round number, so adding a principal to the
      // roster cannot silently push the worst case past it: one login per
      // principal plus the admin's, each able to block for `MAX_LOGIN_WAIT_MS`,
      // plus a minute for the requests around them. Ordinary runs take ~2s.
      timeout: (PRINCIPAL_NAMES.length + 1) * MAX_LOGIN_WAIT_MS + 60_000,
      // Retries deliberately stay as the global setting (1 in CI). With the
      // admin pair persisted before anything that can throw, and the principal
      // file rewritten after each principal, a retry now starts *warm*: it
      // spends no logins and re-attempts only what failed. That is the
      // opposite of `pristine`, which sets `retries: 0` because its first
      // attempt consumes the first-run state its second attempt would need.
      // Bootstrap consumes nothing — it is idempotent by construction.
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
      // Matches `seeded`: `adminPage` (in fixtures/index.ts) is an alias of
      // `page` that states which principal a test drives, not a fixture that
      // authenticates one — without a storageState here it would silently
      // hand back an unauthenticated page. `bootstrap` is already a
      // dependency of this project, so the admin auth state exists by the
      // time any test runs.
      use: { storageState: 'playwright/.auth/admin.json' },
    },
    {
      name: 'streaming-failover',
      testDir: './tests/streaming-failover',
      dependencies: ['bootstrap'],
      // Each row here pays a product-defined wait: the dead-air watchdog is
      // >10s sampled 3x at 5s, and the buffering detector needs the ffmpeg
      // process's cumulative speed= to cross a threshold. 300s is the same
      // ceiling `streaming` uses and is not generous here.
      timeout: 300_000,
      // One worker, unlike its siblings: `failover-buffering.spec.ts`
      // mutates the global `proxy_settings` row (raising `buffering_speed`)
      // for the duration of its run. That is only safe because every other
      // spec in this directory drives the locked Proxy stream profile, where
      // the buffering detector is inert (it parses ffmpeg's stderr, which
      // Proxy never produces) — nothing enforces that convention, so a
      // future ffmpeg-profile spec added here without reading that test's
      // header would race the raised threshold and fail silently. Serialising
      // the project makes that race structurally impossible instead of
      // merely documented, the same reasoning `streaming-greybox` applies to
      // its own container-wide process count below.
      workers: 1,
      use: { storageState: 'playwright/.auth/admin.json' },
    },
    {
      name: 'streaming-greybox',
      testDir: './tests/streaming-greybox',
      dependencies: ['bootstrap'],
      timeout: 300_000,
      // One worker, unlike its siblings: `output-profile-sharing.spec.ts`
      // counts every `ffmpeg` process running in the container (`pgrep -x
      // ffmpeg`) — a container-wide observable, not one scoped to its own
      // channel, the same class of shared-state hazard as
      // `failover-buffering.spec.ts`'s global `proxy_settings` mutation in
      // `streaming-failover`. A second worker running any spec here that
      // starts its own transcode — or a future grey-box test that mutates
      // Redis directly, the way the deleted ownership-lease flagship did —
      // would race against it in a way no other project risks.
      workers: 1,
      use: { storageState: 'playwright/.auth/admin.json' },
    },
    {
      // Owns its container's lifecycle: restarts it mid-test. Must run alone —
      // `fixtures/instance.ts` has the reasoning, `e2e/README.md` has the rule.
      name: 'lifecycle',
      testDir: './tests/lifecycle',
      // The split between the two lifecycle projects is structural, not a
      // `--grep`: `--grep` matches test *titles*, so which spec ran would
      // depend on wording, and nothing would give this project the
      // complementary filter — it would run the ~9-minute upgrade spec too,
      // on every PR, which is exactly what D16 exists to prevent.
      testMatch: /restart-persistence\.spec\.ts$/,
      workers: 1,
      fullyParallel: false,
      // Two container boots and a full readiness wait.
      timeout: 600_000,
      // Attempt 1 consumes the state attempt 2 would need — the same reason
      // `pristine` sets this, and here also because a retry would re-run
      // `provisionAdmin` against an instance that already has the superuser
      // and spend a login it does not need.
      retries: 0,
      // No `dependencies` and no `storageState`, for the same reason
      // `pristine` has neither: `bootstrap` targets whichever container is up
      // before a project starts, and this spec replaces the container
      // mid-run — a persisted token would point at an instance that no longer
      // exists.
    },
    {
      // Identical settings to `lifecycle` — the split is which spec runs, not
      // how. Separate projects rather than one project plus `--grep` because
      // `--grep` matches test *titles*: which spec ran would depend on wording
      // nobody has written yet, and `lifecycle` would have no complementary
      // filter, so it would run this ~9-minute spec on every PR (D16).
      name: 'lifecycle-upgrade',
      testDir: './tests/lifecycle',
      testMatch: /upgrade-migrations\.spec\.ts$/,
      workers: 1,
      fullyParallel: false,
      // A ~3.6 GB baseline pull, a fresh boot on an empty volume, a container
      // replacement and a second boot.
      timeout: 600_000,
      retries: 0,
    },
  ],
});
