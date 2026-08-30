import { test, expect } from '../../fixtures';
import type { ApiClient, PluginListEntry } from '../../fixtures';
import { buildPluginZip } from './plugin-zip';
import { SURFACES, gotoSurface } from './helpers';

const pluginsSurface = SURFACES.find((s) => s.name === 'Plugins');
if (!pluginsSurface) {
  throw new Error('plugins.spec.ts: no "Plugins" entry in SURFACES — check helpers.ts');
}

// The archive is built here rather than committed as a binary so the plugin
// key can carry per-run entropy. A committed zip has a fixed key, which
// collides with itself on a second run against a non-reset container:
// PluginImportAPIView defaults to non-overwrite and returns 400.
test('the plugin archive builder produces a readable zip', () => {
  const zip = buildPluginZip({ key: 'e2e_probe', name: 'E2E Probe' });

  // Local file header, and an end-of-central-directory record.
  expect(zip.subarray(0, 4)).toEqual(Buffer.from([0x50, 0x4b, 0x03, 0x04]));
  expect(zip.lastIndexOf(Buffer.from([0x50, 0x4b, 0x05, 0x06]))).toBeGreaterThan(0);

  // Both members are present, under the key's directory — which is what
  // `_install_plugin_from_zip` walks to choose the plugin directory.
  expect(zip.includes('e2e_probe/plugin.json')).toBe(true);
  expect(zip.includes('e2e_probe/plugin.py')).toBe(true);

  // The signature/EOCD/member checks above would all still pass with broken
  // central-directory offset arithmetic (`zipOf`'s `offset` accumulator).
  // Read the EOCD's own pointer to the central directory and follow it: it
  // must land on a central-header signature, and central directory size +
  // offset + the EOCD's own 22 bytes must account for the whole buffer.
  const cdOffset = zip.readUInt32LE(zip.length - 22 + 16);
  const cdSize = zip.readUInt32LE(zip.length - 22 + 12);
  expect(zip.subarray(cdOffset, cdOffset + 4)).toEqual(Buffer.from([0x50, 0x4b, 0x01, 0x02]));
  expect(cdOffset + cdSize + 22).toBe(zip.length);
});

/**
 * The row's plugin, by the key this test generated — never a remembered id,
 * matching the pattern `logos.spec.ts` / `connect.spec.ts` settled on. Typed
 * against the real `ApiClient` for the same reason: a future signature drift
 * on the fixture is then caught by `npm run typecheck` here, not silently
 * ignored.
 */
async function findPlugin(api: ApiClient, key: string): Promise<PluginListEntry | undefined> {
  const body = await api.json<{ plugins: PluginListEntry[] }>(
    await api.get('/api/plugins/plugins/'),
    'list plugins'
  );
  return body.plugins.find((p) => p.key === key);
}

// This test's polls on `findPlugin` are what exercise the `.reload_token`
// mechanism: a plugin dropped into `plugins_dir` after boot becomes visible
// to the listing process with no provisioning step and — as far as this test
// can show — no restart. `PluginImportAPIView` calls
// `discover_plugins(force_reload=True)` (apps/plugins/api_views.py:412),
// which touches `<plugins_dir>/.reload_token` (apps/plugins/loader.py:812-817);
// `PluginsListAPIView.get` (apps/plugins/api_views.py:116-122) calls
// `discover_plugins(use_cache=True)` (no `sync_db`), which reloads whenever
// that file's mtime (`_get_reload_token`, loader.py:804-806) exceeds the
// process's `_last_reload_token` (loader.py:78-87). The token is a file on
// the shared /data volume, so it is the cross-process broadcast. The
// `worker_process_init` discovery in dispatcharr/celery.py is Celery's initial
// load, not the only path — and this is a browser row, so the web workers are
// the ones that matter.
//
// This does NOT itself prove no uWSGI respawn happened — the assertions
// below (plugin appears in the list; settings round-trip) would pass
// identically through a respawn, transparently. The product's own UI warns
// an import "may briefly restart the backend" (PluginWarnings.jsx,
// PluginRestartWarning), so that possibility is real. The out-of-band check
// is `docker logs`, recorded in e2e/COVERAGE.md against this row: no uWSGI
// respawn during a mutation run, only `apps.plugins.loader` discovery lines.
//
// The plugin is inert by construction (see plugin-zip.ts): enabling it imports
// and runs its module in the uWSGI worker, unsandboxed. It is deleted in
// `test.afterEach` below, not in the test body — a leftover plugin is loaded
// on every subsequent discovery for the life of the container, so cleanup
// must survive more than the happy path.
let keyToDeleteAfterEach: string | undefined;

// Moved out of the test body so cleanup survives a Playwright test timeout:
// on timeout Playwright aborts the test function, and code after a `catch`
// in the body does not reliably run — an in-body try/catch could not close
// this. `afterEach` hooks run with their own budget regardless of how the
// test body ended (including timeout), and `api` is an `APIRequestContext`,
// independent of `page`, so it still works after a page-side timeout.
test.afterEach(async ({ api }, testInfo) => {
  if (!keyToDeleteAfterEach) return;
  const key = keyToDeleteAfterEach;
  keyToDeleteAfterEach = undefined;

  // `PluginDeleteAPIView` (apps/plugins/api_views.py:540-541) is a bodyless
  // `DELETE`, not a `POST` — confirmed against the view and its `urls.py`
  // route, which the initial draft of this test got wrong. It is also
  // unconditionally idempotent: a missing `target_dir`/`PluginConfig` row is
  // silently a no-op inside the same 200, so this always expects 200, even
  // if the test failed before the import ever created the plugin.
  try {
    const cleanup = await api.delete(`/api/plugins/plugins/${key}/delete/`);
    if (cleanup.status() !== 200) {
      throw new Error(`plugin cleanup failed: DELETE returned ${cleanup.status()}`);
    }
  } catch (cleanupError) {
    // Same non-masking shape the previous in-body try/catch had: if the test
    // itself already failed, a cleanup failure on top of it must not replace
    // that failure as the reported cause — log it and stop. Only let a
    // cleanup failure fail the test when the test body otherwise passed.
    if (testInfo.status !== 'passed') {
      console.error(
        'plugins.spec.ts: cleanup failed after an in-flight test failure — ' +
          'not overwriting it. Cleanup error:',
        cleanupError
      );
      return;
    }
    throw cleanupError;
  }
});

test('a plugin imported through the Plugins page lists, enables and configures', async ({
  adminPage,
  api,
  seed,
  pageErrors,
}) => {
  // Per-run entropy in the key: `_sanitize_plugin_key`
  // (apps/plugins/api_views.py:76-81) lowercases and replaces anything
  // outside [a-z0-9_], so the generated name is normalised here to the key
  // the server will actually derive from the zip's top-level directory name.
  const key = seed.generatedName('plugin').toLowerCase().replace(/[^a-z0-9_]/g, '_');
  const displayName = `E2E ${key}`;

  // Registered as soon as the key is known, before the plugin necessarily
  // exists — the `afterEach` DELETE above is safely idempotent either way,
  // and this is the only point between here and a mid-flow timeout where a
  // plain assignment (rather than a step that can itself throw) is guaranteed
  // to run.
  keyToDeleteAfterEach = key;

  await gotoSurface(adminPage, pluginsSurface);
  await expect(adminPage.getByTestId('plugins-page')).toBeVisible();

  await adminPage.getByRole('button', { name: 'Import Plugin', exact: true }).click();

  // The import modal renders *two* `input[type="file"]` elements: Mantine
  // `Dropzone`'s own hidden input (`accept="application/zip,..."`) and the
  // `FileInput` below it (`accept=".zip"`) — confirmed against the real
  // DOM, where a bare `input[type="file"]` locator resolves to both and
  // throws a strict-mode violation. Scope to the `FileInput`'s `accept`
  // value to pick the one this flow actually drives.
  await adminPage.locator('input[type="file"][accept=".zip"]').setInputFiles({
    name: `${key}.zip`,
    mimeType: 'application/zip',
    buffer: buildPluginZip({ key, name: displayName }),
  });
  await adminPage.getByRole('button', { name: 'Upload', exact: true }).click();

  // `handleImportPlugin` (Plugins.jsx:267-337) only reveals "Done" once the
  // upload has resolved and `imported` is set — waiting on it is the
  // upload-finished barrier. The modal does not auto-close on success, and
  // it sits on top of the plugin grid, so the card below is unreachable
  // until this closes it.
  await adminPage.getByRole('button', { name: 'Done', exact: true }).click();

  await expect.poll(() => findPlugin(api, key), { timeout: 60_000 }).toBeDefined();
  expect((await findPlugin(api, key))!.enabled).toBe(false);

  // Enable through the UI. The switch lives on the plugin's card
  // (PluginCard.jsx:546-553), scoped by the generated key's display name so
  // it cannot be another plugin's. `.mantine-Card-root` is a Mantine-internal
  // class, not contract — a library upgrade could rename it silently — but
  // there is no better handle today: neither PluginCard.jsx nor Plugins.jsx
  // sets a per-card `data-testid` or other stable attribute (checked).
  // Plugins.jsx:397 does set `data-testid="plugins-page"` on the page itself
  // — used above at :143 — but nothing scopes to an individual card, so
  // text-scoping by display name is the only option here.
  const card = adminPage
    .getByTestId('plugins-page')
    .locator('.mantine-Card-root', { hasText: displayName });

  // Mantine's `Switch` renders its real `<input role="switch">` visually
  // hidden (`width:0;height:0`, confirmed against the real DOM) under a
  // styled track — Playwright's actionability check refuses to click an
  // element with a zero-size box, so this drives the associated
  // `<label class="mantine-Switch-body">` a real click forwards to the
  // input, exactly as a mouse click would. `label.mantine-Switch-body` is
  // also Mantine-internal, and is only necessary because `PluginCard.jsx`'s
  // `Switch` has no `label`/`aria-label` (filed as D10Scot/Dispatcharr#73);
  // once that's fixed this should become `getByRole('switch', { name: … })`.
  await card.locator('label.mantine-Switch-body').first().click();

  // The page shows a trust confirmation before enabling an untrusted
  // plugin (`onRequireTrust` → `requireTrust` in Plugins.jsx:246-251,
  // wired to `PluginCard`'s `handleEnableChange` at PluginCard.jsx:282-283
  // for a plugin whose `ever_enabled` is still false). Confirmed against
  // the real dialog: title "Enable third-party plugins?", confirm button
  // "I understand, enable" (Plugins.jsx:568).
  await adminPage
    .getByRole('dialog')
    .getByRole('button', { name: 'I understand, enable', exact: true })
    .click();

  await expect
    .poll(async () => (await findPlugin(api, key))?.enabled, { timeout: 60_000 })
    .toBe(true);

  // Configure: the manifest declares one string field, `note`. The
  // "Settings" button only renders once the plugin is enabled (`hasFields`,
  // PluginCard.jsx:345, requires `enabled`), so this could not have been
  // reached before the poll above settled.
  await card.getByRole('button', { name: 'Settings', exact: true }).click();
  const settingsDialog = adminPage.getByRole('dialog');
  await settingsDialog.getByLabel('Note', { exact: true }).fill('configured-by-e2e');
  await settingsDialog.getByRole('button', { name: 'Save', exact: true }).click();

  await expect
    .poll(async () => (await findPlugin(api, key))?.settings?.note, { timeout: 60_000 })
    .toBe('configured-by-e2e');

  // The fixture's own teardown calls `pageErrors.expectClean()` unconditionally
  // (fixtures/index.ts:388-392) — this in-body call is not redundant with
  // that. It narrows the check to *this flow*: it fails inside this test's
  // captured region, attributing any console error to the import/enable/
  // configure steps above rather than to whatever `afterEach` cleanup does
  // next, and before that cleanup runs at all.
  await pageErrors.expectClean();
});
