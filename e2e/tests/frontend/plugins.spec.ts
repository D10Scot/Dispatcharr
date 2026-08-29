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

// A plugin dropped in after boot is visible with NO restart, in every uWSGI
// worker. `PluginImportAPIView` calls `discover_plugins(force_reload=True)`
// (apps/plugins/api_views.py:411), which touches `<plugins_dir>/.reload_token`
// (apps/plugins/loader.py:812-817); `PluginsListAPIView.get`
// (apps/plugins/api_views.py:116-122) calls `discover_plugins(use_cache=True)`
// (no `sync_db`), which reloads whenever that file's mtime
// (`_get_reload_token`, loader.py:804-806) exceeds the process's
// `_last_reload_token` (loader.py:78-87). The token is a file on the shared
// /data volume, so it is the cross-process broadcast. The
// `worker_process_init` discovery in dispatcharr/celery.py is Celery's initial
// load, not the only path — and this is a browser row, so the web workers are
// the ones that matter.
//
// The plugin is inert by construction (see plugin-zip.ts): enabling it imports
// and runs its module in the uWSGI worker, unsandboxed. It is deleted at the
// end of the test — a leftover plugin is loaded on every subsequent discovery
// for the life of the container.
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

  // Captured rather than thrown immediately: cleanup below must run
  // unconditionally, and a bare `finally` would let an unrelated cleanup
  // failure silently replace a real assertion failure already in flight —
  // same shape as dvr.spec.ts / logos.spec.ts / connect.spec.ts.
  let testError: unknown;

  try {
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
    // it cannot be another plugin's.
    const card = adminPage
      .getByTestId('plugins-page')
      .locator('.mantine-Card-root', { hasText: displayName });

    // Mantine's `Switch` renders its real `<input role="switch">` visually
    // hidden (`width:0;height:0`, confirmed against the real DOM) under a
    // styled track — Playwright's actionability check refuses to click an
    // element with a zero-size box, so this drives the associated
    // `<label class="mantine-Switch-body">` a real click forwards to the
    // input, exactly as a mouse click would.
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
    await settingsDialog.getByLabel('Note').fill('configured-by-e2e');
    await settingsDialog.getByRole('button', { name: 'Save', exact: true }).click();

    await expect
      .poll(async () => (await findPlugin(api, key))?.settings?.note, { timeout: 60_000 })
      .toBe('configured-by-e2e');

    await pageErrors.expectClean();
  } catch (err) {
    testError = err;
  }

  // Cleanup always runs, whether or not the flow above succeeded — a leftover
  // plugin is imported into every uWSGI worker on every subsequent discovery
  // for the life of the container, not merely untidy. `PluginDeleteAPIView`
  // (apps/plugins/api_views.py:540-541) is a bodyless `DELETE`, not a `POST`
  // — confirmed against the view and its `urls.py` route, which the initial
  // draft of this test got wrong. It is also unconditionally idempotent: a
  // missing `target_dir`/`PluginConfig` row is silently a no-op inside the
  // same 200, so this always expects 200, even if the flow above failed
  // before the import ever created the plugin.
  try {
    const cleanup = await api.delete(`/api/plugins/plugins/${key}/delete/`);
    if (cleanup.status() !== 200) {
      throw new Error(`plugin cleanup failed: DELETE returned ${cleanup.status()}`);
    }
  } catch (cleanupError) {
    if (testError) {
      console.error(
        'plugins.spec.ts: cleanup failed after an in-flight test failure — ' +
          'not overwriting it. Cleanup error:',
        cleanupError
      );
    } else {
      testError = cleanupError;
    }
  }

  if (testError) throw testError;
});
