import { test, expect } from '../../fixtures';
import type { ApiClient } from '../../fixtures';
import { lockedProfile } from '../streaming/helpers';

/**
 * This spec mutates a **global** row — `CoreSettings`'s `stream_settings`
 * group, specifically `default_stream_profile` — and restores it in a
 * `finally`.
 *
 * VOD Redirect mode is a global setting with no per-content override.
 * `stream_vod` consults `CoreSettings.is_default_stream_profile_redirect()`
 * (`core/models.py:549`), which compares `get_default_stream_profile_id()`
 * against the locked `Redirect` profile's id. There is no per-movie and no
 * per-account override — the exact opposite of live streaming, where G4
 * passed `streamProfileId` per stream. That is why the row cannot be written
 * any other way.
 *
 * A crashed run leaves the instance's default Stream Profile on Redirect,
 * which breaks every subsequent live-streaming test in that container until
 * it is reset. The restore is therefore unconditional and in a `finally`,
 * never gated on an assertion passing.
 *
 * The precedent is `e2e/tests/streaming-failover/failover-buffering.spec.ts`,
 * which does the same read-modify-write-restore against the global
 * `proxy_settings` row. Read it before writing this one.
 *
 * This is why the file lives in `streaming-greybox` (`workers: 1`) rather
 * than `streaming` — see the second reason appended to that project's block
 * comment in `playwright.config.ts`.
 */

const CORE_SETTINGS_PATH = '/api/core/settings/';
const STREAM_SETTINGS_KEY = 'stream_settings'; // core/models.py:201

interface SettingsRow {
  id: number;
  key: string;
  value: Record<string, unknown>;
}

async function readStreamSettingsRow(api: ApiClient): Promise<SettingsRow> {
  const rows = await api.json<SettingsRow[]>(await api.get(CORE_SETTINGS_PATH), 'core settings');
  const row = rows.find((r) => r.key === STREAM_SETTINGS_KEY);
  expect(row, `the "${STREAM_SETTINGS_KEY}" CoreSettings row should exist`).toBeDefined();
  return row!;
}

test('VOD Redirect mode sends the client at the provider and carries no bytes (G9 row 21)', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  // An XC account create blocks on two synchronous provider round-trips
  // (apps/m3u/api_views.py:136-145), on top of the ingest wait below.
  test.setTimeout(180_000);

  const prefix = seed.generatedName('vodredirect');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    vod: [
      {
        id: 1,
        name: `${prefix}-movie`,
        year: 2021,
        categoryId: 1,
        containerExtension: 'mp4',
        tmdbId: null,
        imdbId: null,
      },
    ],
    series: 0,
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  interface MoviePage {
    count: number;
    results: { id: number; uuid: string; name: string }[];
  }
  const movies = await waitFor.resource<MoviePage>(
    `/api/vod/movies/?search=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the VOD movie ${prefix}-movie to be ingested`, timeoutMs: 120_000 }
  );
  const movie = movies.results[0];

  const row = await readStreamSettingsRow(api);
  const original = row.value;
  const redirect = await lockedProfile(api, 'Redirect');

  // A previous run that timed out before its `finally` completed would leave
  // `default_stream_profile` pointed at Redirect already — turn that into a
  // loud, named failure rather than a test that passes for the wrong reason.
  // This stack's default Stream Profile is ffmpeg (id 1), not Redirect
  // (id 4), so "not redirect.id" is the expected starting value.
  expect(
    original.default_stream_profile,
    'a previous run left stream_settings dirty on the Redirect profile'
  ).not.toBe(redirect.id);

  try {
    await api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, {
      value: { ...original, default_stream_profile: redirect.id },
    });

    // Verified rather than assumed: unlike proxy_settings (a 10s per-process
    // cache the buffering spec has to outlast), _get_group's Redis cache is
    // invalidated by a post_save receiver on CoreSettings, so this should be
    // visible to every uWSGI worker immediately.
    const readBack = await readStreamSettingsRow(api);
    expect(readBack.value.default_stream_profile).toBe(redirect.id);

    // 302, not 301: the Redirect branch returns
    // HttpResponseRedirect(selected['final_stream_url'])
    // (apps/proxy/vod_proxy/views.py:758), while the session-mint path (the
    // default profile, exercised by vod-stream.spec.ts row 11) returns a
    // hand-built HttpResponse(status=301, ...) whose Location is a relative
    // session path. The status alone distinguishes "sent at the provider"
    // from "sent to your own session URL", which is the whole point of this
    // row. If this proves flaky, retry with waitFor.condition rather than a
    // sleep — the settings write above is already verified, so a flake here
    // would point elsewhere.
    await streamClient.open(`/proxy/vod/movie/${movie.uuid}`, { redirect: 'manual' });
    expect(streamClient.status).toBe(302);

    const location = streamClient.headers!.get('location')!;
    // Throws on any URL outside the provider's internal origin, which is
    // what proves the client was sent at the provider and not somewhere
    // else.
    const control = upstream.toControl(location);
    expect(control).toContain('/movie/');

    // upstream.connections(scenario).live is the instrument the live-TS
    // Redirect row uses (stream-profiles.spec.ts) to prove no bytes
    // traversed Dispatcharr, and is asserted here too for consistency — but
    // mutation-checked (task-12 report) to read 0 for VOD even during a real
    // session-mint fetch that DOES traverse Dispatcharr, so it is not by
    // itself proof of anything for this row; the provider's request log
    // below is the mutation-verified discriminator.
    const connections = await upstream.connections(scenario);
    expect(connections.live).toBe(0);

    // THE DISCRIMINATOR for "no bytes traversed Dispatcharr": read the
    // provider's request log for the movie asset *before* anything follows
    // the redirect. In Redirect mode `stream_vod`'s branch is a pure
    // `HttpResponseRedirect` build (apps/proxy/vod_proxy/views.py:758) — it
    // never itself calls the provider — so this must be empty. Mutation-
    // checked (task-12 report): the log genuinely observes a hit once
    // something below actually follows the redirect, so an empty result here
    // is not just an instrument that never fires for VOD paths.
    const beforeFollow = await upstream.log(scenario);
    const hitsBeforeFollow = beforeFollow.filter(
      (e) => e.kind === 'request' && e.path?.includes('/movie/')
    );
    expect(
      hitsBeforeFollow.length,
      'Dispatcharr itself must not have contacted the provider before the client follows the redirect'
    ).toBe(0);

    // Follow the redirect and confirm the URL the client was handed actually
    // works — a redirect to a URL that 404s would otherwise satisfy every
    // assertion above.
    const direct = await fetch(control);
    expect(direct.status).toBe(200);
    const assetBytes = Buffer.from(await direct.arrayBuffer());
    // The asset is a real MP4: box size, then 'ftyp'.
    expect(assetBytes.subarray(4, 8).toString('ascii')).toBe('ftyp');

    // Confirms the log instrument actually fires for this path — the
    // complementary half of the discriminator above (mutation-check
    // guidance: prove a negative-assertion instrument can also observe the
    // event, not just reason that it should).
    const afterFollow = await upstream.log(scenario);
    const hitsAfterFollow = afterFollow.filter(
      (e) => e.kind === 'request' && e.path?.includes('/movie/')
    );
    expect(hitsAfterFollow.length).toBeGreaterThan(0);
  } finally {
    // Unconditional. Not inside an `if`, not after an assertion, not skipped
    // on success — a crashed run must not leave the instance's default
    // Stream Profile on Redirect for every subsequent live-streaming test.
    await api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, { value: original });
  }
});
