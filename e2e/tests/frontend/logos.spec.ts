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
    await adminPage.locator('input[type="file"]').setInputFiles({
      name: 'e2e-logo.png',
      mimeType: 'image/png',
      buffer: TINY_PNG,
    });

    // Logo.jsx's handleFileSelect auto-fills Name from the filename only
    // when the field is still empty; filling it explicitly here overwrites
    // that, so the row is findable under the worker-scoped generated name
    // rather than the literal "e2e-logo" the auto-fill would have produced
    // (which every worker's run would collide on).
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
    // retrievability. For a file uploaded through `LogoViewSet.upload`,
    // `url` is the raw server-side filesystem path (`/data/logos/<name>`,
    // from `core.utils.safe_upload_path`) — no route in
    // `dispatcharr/urls.py` actually serves `/data/logos/*`. What DOES match
    // it, confirmed empirically against this container (not assumed from
    // reading source alone — the read led to a wrong first guess of a 200
    // SPA-shell fallback, corrected here): `dispatcharr/urls.py`'s
    // `xc_stream_endpoint` route, `<str:username>/<str:password>/<str:channel_id>`,
    // registered ahead of the catch-all. `/data/logos/<file>` has exactly
    // three path segments, so it parses as username="data",
    // password="logos", channel_id="<file>" and 404s from `stream_xc`'s own
    // "no such user" lookup — `{"detail":"No User matches the given
    // query."}`, nothing image-shaped, and not the 200 a naive
    // `expect(status).toBe(200)` might have been tempted to assert. Neither
    // guess was filed as a defect: `created.url` is never meant to be
    // dereferenced directly by a client (`LogosTable.jsx`'s URL column only
    // renders a clickable link when the value `startsWith('http')`, so the
    // UI itself already knows a local path isn't one) — `cache_url`
    // (`LogoSerializer.get_cache_url`, an absolute URL to the AllowAny
    // `LogoViewSet.cache` action, which streams the real file via
    // `serve_local_or_remote_image`) is the field the product actually
    // exposes for retrieval, and is what the assertions below use.
    const rawUrlFetch = await api.get(created!.url);
    expect(
      rawUrlFetch.status(),
      'created.url collides with the XC live-stream route (3 path segments) and 404s there, rather than serving the image — see the comment above'
    ).toBe(404);

    expect(created!.cache_url, 'a stored logo should have a cache URL to serve it from').toBeTruthy();
    const fetched = await api.get(created!.cache_url);
    expect(fetched.status()).toBe(200);
    expect(fetched.headers()['content-type']).toContain('image');
    const body = await fetched.body();
    expect(body.length).toBe(TINY_PNG.length);

    // The browse half of the row: it is rendered in the table, scoped to the
    // logos-page container.
    await expect(adminPage.getByTestId('logos-page').getByText(name)).toBeVisible({
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
