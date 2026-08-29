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

// NEVER click "Cleanup Unused" on this page. It calls
// /api/channels/logos/cleanup/, which deletes every unreferenced logo
// instance-wide — four workers' data and other goals' seeded logos with it.
test('a logo uploaded through the Logos page is stored server-side and listed', async ({
  adminPage,
  api,
  seed,
  pageErrors,
}) => {
  const name = seed.generatedName('logo');

  // Captured rather than left to propagate straight out of the `try` below,
  // matching connect.spec.ts's shape: cleanup must run unconditionally
  // afterward, and a plain `finally` block would let an unrelated lookup
  // failure silently replace a real assertion failure already in flight.
  let testError: unknown;

  try {
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
  } catch (err) {
    testError = err;
  }

  // Cleanup always runs, whether or not the flow above succeeded, and looks
  // the row up by the generated name (never a remembered id) so it works no
  // matter how far the flow got. Same asymmetric treatment Tasks 7-9 settled
  // on: a failure to *look up* the row is caught and, if a real test failure
  // is already in flight, only logged — never allowed to overwrite it. A
  // failure in the *delete itself* is never swallowed, even when the flow
  // above already failed — a broken teardown must stay loud.
  //
  // An uploaded logo leaves more behind than a database row: the file
  // `LogoViewSet.upload` wrote under `/data/logos/`. `?delete_file=true` on
  // the DELETE is what `LogoViewSet.destroy` reads to also `os.remove()`
  // that file (only when `logo.url` starts with `/data/logos`, which every
  // logo this test creates does) — passing it unconditionally here is safe
  // for a row this test made and is what removes the on-disk residue, not
  // just the row.
  let leftover: Logo | undefined;
  try {
    leftover = await findLogo(api, name);
  } catch (lookupError) {
    if (testError) {
      console.error(
        'logos.spec.ts: cleanup lookup failed after an in-flight test failure — ' +
          'not overwriting it. Lookup error:',
        lookupError
      );
    } else {
      testError = lookupError;
    }
  }
  if (leftover) {
    if (testError) {
      console.error(
        'logos.spec.ts: an in-flight test failure preceded cleanup (see below); ' +
          'running cleanup regardless:',
        testError
      );
    }
    const cleanup = await api.delete(`/api/channels/logos/${leftover.id}/?delete_file=true`);
    expect(cleanup.status()).toBe(204);
  }

  if (testError) throw testError;
});
