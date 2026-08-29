import { test, expect } from '../../fixtures';
import type { BackupEntry } from '../../fixtures';
import { SURFACES, gotoSurface } from './helpers';

const backupsSurface = SURFACES.find((s) => s.name === 'Backups');
if (!backupsSurface) {
  throw new Error('backups.spec.ts: no "Backups" entry in SURFACES — check helpers.ts');
}

// CREATE ONLY. Restoring a backup replaces the database under every parallel
// worker mid-run, and under every other project sharing this container
// locally. Restore is G7's, which stands up its own instance per scenario —
// see the Lifecycle row in COVERAGE.md.
//
// This spec is the reason the `frontend` project runs file-level parallelism:
// `apps/backups/services.py`'s `create_backup` derives the archive name from
// the clock at SECOND granularity and the caller cannot name it, while
// `list_backups` globs the directory and returns everything. Two concurrent
// creates overwrite one archive with another, and nothing identifies "mine".
// The before/after set difference below is only sound because one file runs
// in one worker. Do not split this file.

// The archive this test created, by name — never a remembered index into a
// list — matching the shape `plugins.spec.ts`'s `afterEach` settled on after
// Task 12 found that a test-body `finally`/`try` does not survive a
// Playwright-forced timeout: the test function is aborted and code after a
// `catch` in the body is not guaranteed to run. `afterEach` hooks run on
// their own budget regardless of how the body ended, and the `api` fixture
// used below is an `APIRequestContext`, independent of `page`, so it still
// works after a page-side timeout.
let nameToDeleteAfterEach: string | undefined;

test.afterEach(async ({ api }, testInfo) => {
  if (!nameToDeleteAfterEach) return;
  const name = nameToDeleteAfterEach;
  nameToDeleteAfterEach = undefined;

  // `delete_backup` (apps/backups/api_views.py, routed as
  // `<filename>/delete/` in apps/backups/api_urls.py) is a bodyless `DELETE`,
  // not the `POST` the original draft of this test assumed — confirmed
  // against the view's `@api_view(["DELETE"])` decorator and the route.
  // Unlike the plugin delete this shape is modelled on, this one is NOT
  // unconditionally 200: `apps/backups/services.py`'s `delete_backup` raises
  // `FileNotFoundError` for a missing file, which the view turns into a 404
  // — so idempotency here means treating 204 (deleted) and 404 (already
  // gone, e.g. because the test failed before the archive was ever created)
  // as both fine, not just always expecting one status.
  try {
    const cleanup = await api.delete(`/api/backups/${encodeURIComponent(name)}/delete/`);
    if (cleanup.status() !== 204 && cleanup.status() !== 404) {
      throw new Error(`backup cleanup failed: DELETE returned ${cleanup.status()}`);
    }
  } catch (cleanupError) {
    // Same non-masking shape as plugins.spec.ts: if the test itself already
    // failed, a cleanup failure on top of it must not replace that failure
    // as the reported cause — log it and stop. Only let a cleanup failure
    // fail the test when the test body otherwise passed.
    if (testInfo.status !== 'passed') {
      console.error(
        'backups.spec.ts: cleanup failed after an in-flight test failure — ' +
          'not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

test('a backup created from the Backups panel produces a complete archive', async ({
  adminPage,
  api,
  pageErrors,
}) => {
  const listBackups = async (): Promise<BackupEntry[]> =>
    api.json<BackupEntry[]>(await api.get('/api/backups/'), 'list backups');

  const before = new Set((await listBackups()).map((b) => b.name));

  // `page.goto('/settings#backups')` cannot reach this surface on a fresh
  // load (#58, see helpers.ts's module doc comment) — `gotoSurface` is the
  // sidebar-click workaround every spec in this project uses. It also
  // already waits on `backups-panel` becoming visible.
  await gotoSurface(adminPage, backupsSurface);

  // BackupManager.jsx's create button reads exactly "Create Backup" — the
  // brief's `/create backup|backup now|create/i` alternation was a
  // placeholder regex; read from source rather than kept as a loose match.
  await adminPage.getByRole('button', { name: 'Create Backup', exact: true }).click();

  // POST /api/backups/create/ returns 202 with a task_id; the archive is
  // written by a Celery task. Poll, never assume.
  let created: BackupEntry | undefined;
  await expect
    .poll(
      async () => {
        const fresh = (await listBackups()).filter((b) => !before.has(b.name));
        created = fresh[0];
        // Assigned as soon as a name is known, before any further await in
        // this test — see the `afterEach` above for why that ordering
        // matters. A false-positive early assignment on a request that later
        // turns out not to be "the" backup is harmless: cleanup by name is
        // idempotent either way.
        if (created) nameToDeleteAfterEach = created.name;
        return fresh.length;
      },
      { timeout: 90_000, intervals: [1_000] }
    )
    .toBe(1);

  expect(created!.name).toMatch(/^dispatcharr-backup-\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.\d{2}\.zip$/);
  expect(created!.size, 'an empty archive is a failed backup').toBeGreaterThan(0);

  // Structural validation without a zip parser: a complete archive begins
  // with a local file header and ends with an end-of-central-directory
  // record. Together they prove it is a zip AND that it was not truncated —
  // which a size check alone does not.
  const tokenBody = await api.json<{ token: string }>(
    await api.get(`/api/backups/${encodeURIComponent(created!.name)}/download-token/`),
    'backup download token'
  );
  const download = await api.get(
    `/api/backups/${encodeURIComponent(created!.name)}/download/` +
      `?token=${encodeURIComponent(tokenBody.token)}`
  );
  expect(download.status()).toBe(200);

  const bytes = await download.body();
  expect(bytes.length).toBe(created!.size);
  expect(bytes.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  expect(
    bytes.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06])),
    'no end-of-central-directory record: the archive is truncated'
  ).toBeGreaterThan(0);

  await pageErrors.expectClean();
});
