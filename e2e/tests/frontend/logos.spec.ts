import { test, expect } from '../../fixtures';
import type { ApiClient, Logo } from '../../fixtures';
import { listRows } from '../../setup/http';
import { SURFACES, gotoSurface } from './helpers';
import { TINY_PNG } from './assets';

const logosSurface = SURFACES.find((s) => s.name === 'Logos');
if (!logosSurface) {
  throw new Error('logos.spec.ts: no "Logos" entry in SURFACES — check helpers.ts');
}

/**
 * The row this test created, by the generated name it used — never a
 * remembered id, matching the pattern `connect.spec.ts` and `users.spec.ts`
 * settled on. Typed against the real `ApiClient` for the same reason
 * `connect.spec.ts`'s fix round 1 adopted it: a future signature drift on
 * the fixture is then caught by `npm run typecheck` here, not silently
 * ignored.
 */
async function findLogo(api: ApiClient, name: string): Promise<Logo | undefined> {
  const body = await api.json<unknown>(
    await api.get(`/api/channels/logos/?name=${encodeURIComponent(name)}`),
    'list logos'
  );
  return listRows<Logo>(body).find((l) => l.name === name);
}

// The row to clean up, by the generated name this test used — never a
// remembered id. Module-level, not test-body state, and assigned the moment
// the name is generated (see the test body below), before any further await
// that can throw.
//
// Why this lives outside the test body, and why in `afterEach` rather than a
// body-level `try`/`catch`/rethrow (this file's own shape until this round,
// shared with dvr.spec.ts and connect.spec.ts): a `catch` runs on a normal
// throw, but Playwright does not raise a normal exception when a test
// exceeds its timeout — it tears the test function down mid-`await`, and
// code written after that `await`, the `catch` block and everything below it
// included, does not reliably run. `afterEach` hooks are Playwright's own
// fixture-teardown machinery, run on their own budget regardless of how the
// test body ended, including a forced timeout — the same reasoning
// `plugins.spec.ts`'s `afterEach` documents, and the shape this file now
// matches. The `api` fixture used below is an `ApiClient`, wrapping an
// `APIRequestContext` independent of `page`, so it still works after a
// page-side timeout.
//
// This module-level binding is safe only because the `frontend` project's
// block in playwright.config.ts leaves `fullyParallel` unset, and its own
// comment there says so deliberately — it inherits Playwright's default of
// `false`, not a project-level override, so tests within one file never run
// concurrently and one test's write here can never be read by another
// test's `afterEach`. A module-level binding under `fullyParallel: true`
// would be a cross-test race; this file relies on that inherited default
// holding, not on it happening to be pinned some other way.
let nameToCleanup: string | undefined;

test.afterEach(async ({ api }, testInfo) => {
  if (!nameToCleanup) return;
  const name = nameToCleanup;
  nameToCleanup = undefined;

  try {
    const leftover = await findLogo(api, name);
    if (leftover) {
      // An uploaded logo leaves more behind than a database row: the file
      // `LogoViewSet.upload` wrote under `/data/logos/`. `?delete_file=true`
      // on the DELETE is what `LogoViewSet.destroy` reads to also
      // `os.remove()` that file (only when `logo.url` starts with
      // `/data/logos`, which every logo this test creates does) — passing
      // it unconditionally here is safe for a row this test made and is
      // what removes the on-disk residue, not just the row.
      const cleanup = await api.delete(`/api/channels/logos/${leftover.id}/?delete_file=true`);
      if (cleanup.status() !== 204) {
        throw new Error(`logo cleanup failed: DELETE returned ${cleanup.status()}`);
      }
    }
  } catch (cleanupError) {
    // Same non-masking shape plugins.spec.ts/backups.spec.ts settled on: if
    // the test itself already failed, a cleanup failure on top of it must
    // not replace that failure as the reported cause — log it and stop.
    // Only let a cleanup failure fail the test when the test body otherwise
    // passed. (An earlier version of this file's cleanup gave the delete
    // failure different treatment from the lookup failure — never
    // swallowing it, even on an already-failed test. That asymmetry is gone
    // in this shape, in favour of the uniform non-masking treatment
    // plugins.spec.ts and backups.spec.ts already use for the whole cleanup
    // step — an unconditional throw here would silently replace a real test
    // failure already in flight with this cleanup failure instead.)
    if (testInfo.status !== 'passed') {
      console.error(
        'logos.spec.ts: cleanup failed after an in-flight test failure — ' +
          'not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

// NEVER click "Cleanup Unused" on this page. It calls
// /api/channels/logos/cleanup/, which deletes every unreferenced logo
// instance-wide — four workers' data and other goals' seeded logos with it.
test('a logo uploaded through the Logos page is stored server-side and listed', { tag: '@contract' }, async ({
  adminPage,
  api,
  seed,
  pageErrors,
}) => {
  const name = seed.generatedName('logo');
  // Assigned immediately, before any further `await` that can throw — the
  // only point between here and a mid-flow timeout where a plain assignment
  // (rather than a step that can itself throw) is guaranteed to run. See
  // `nameToCleanup`'s own comment above.
  nameToCleanup = name;

  // `page.goto('/logos')` cannot reach this surface on a fresh load (#58)
  // — gotoSurface is the sidebar-click workaround every spec in this
  // project uses. The sidebar's accessible link name is "Logo Manager",
  // not "Logos" (SIDEBAR_LINK_LABEL in helpers.ts already accounts for
  // this divergence).
  await gotoSurface(adminPage, logosSurface);

  // LogosTable.jsx: the create button's real label is "Add Logo".
  await adminPage.getByRole('button', { name: 'Add Logo', exact: true }).click();

  // Mantine's Dropzone renders a real <input type="file">, hidden. Setting
  // files on it directly is how Playwright drives a dropzone; there is no
  // need to synthesise a drag event.
  //
  // The uploaded filename is derived from the worker-scoped generated
  // `name`, not a constant. `LogoViewSet.upload` writes to a fully
  // deterministic path (`core.utils.safe_upload_path` does no
  // uniquification) and `get_or_create(url=file_path)`s the row against
  // it — a constant filename is therefore a shared, permanent key across
  // every run this test has ever made. If a row under that path ever
  // leaks (a killed process, an aborted run), the *next* run's upload
  // returns that same old row, still carrying the *previous* run's name:
  // `findLogo(name)` never matches it, the poll below burns its full
  // timeout, and cleanup — which only deletes rows matching its own
  // generated name — can never reach it either, since it is looking for
  // the wrong name on the very row it needs to delete. A per-run filename
  // turns a leaked row into an ordinary, independently-cleanable one
  // instead of a permanently wedged path.
  const uploadFilename = `${name}.png`;
  await adminPage.locator('input[type="file"]').setInputFiles({
    name: uploadFilename,
    mimeType: 'image/png',
    buffer: TINY_PNG,
  });

  // Logo.jsx's handleFileSelect auto-fills Name from the filename (minus
  // extension) only when the field is still empty — which, since the
  // filename above already *is* the generated name, would already land on
  // the right value. Filled explicitly anyway rather than relied upon: the
  // row's identity is what the rest of this test depends on, and an
  // explicit fill keeps that true even if the auto-fill behaviour changes.
  await adminPage.getByLabel('Name', { exact: true }).fill(name);

  // Logo.jsx's submit button reads "Create" for a new logo ("Update" only
  // once `logo` is non-null, i.e. editing) — the brief's own
  // `/save|create|submit|upload/i` was a placeholder regex; read from
  // source rather than kept as a loose match.
  await adminPage.getByRole('button', { name: 'Create', exact: true }).click();

  // The assertion is the server's state, not a toast — api.js's
  // errorNotification toasts AND rethrows, so a red toast and a green
  // toast are equally consistent with a write that never left the
  // browser. `LogoViewSet.get_queryset` filters `?name=` with
  // `name__icontains`, so this is a real filter, not an assumption; the
  // `.find()` on the exact name still guards against a substring match.
  let created: Logo | undefined;
  await expect
    .poll(async () => (created = await findLogo(api, name)), { timeout: 60_000 })
    .toBeDefined();

  expect(created!.name).toBe(name);
  expect(created!.url, 'an uploaded logo should record a server-side location').toBeTruthy();

  // `created.url` is deliberately NOT what gets fetched to prove
  // retrievability — it is a raw server-side filesystem path, not a route
  // this app serves, and (per the `Logo` type's own doc comment in
  // `fixtures/types.ts`) it doesn't even fail *cleanly*: it happens to
  // collide with the XC live-stream route and 404s from an unrelated
  // "no such user" lookup. Asserting that specific accidental status here
  // would pin this one-surface test to another route's routing order for
  // no benefit to what this test is actually proving. `cache_url` is what
  // the product exposes for retrieval, and is what the assertions below
  // use.
  expect(created!.cache_url, 'a stored logo should have a cache URL to serve it from').toBeTruthy();
  const fetched = await api.get(created!.cache_url);
  expect(fetched.status()).toBe(200);
  expect(fetched.headers()['content-type']).toContain('image');
  const body = await fetched.body();
  expect(body.length).toBe(TINY_PNG.length);

  // The browse half of the row: it is rendered in the table, scoped to the
  // logos-page container. Exact match is required, not incidental: the
  // Name column cell reads exactly `name`, but since the upload filename
  // is now also derived from `name` (see the fix above), the row's URL
  // column cell reads `/data/logos/<name>.png` — a substring match on
  // `name` resolves both and violates Playwright's strict mode.
  await expect(
    adminPage.getByTestId('logos-page').getByText(name, { exact: true })
  ).toBeVisible({
    timeout: 30_000,
  });

  await pageErrors.expectClean();
});
