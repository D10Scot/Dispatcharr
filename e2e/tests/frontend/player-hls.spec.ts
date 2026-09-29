import type { Page, Request } from '@playwright/test';
import { test, expect, readChannelStatus } from '../../fixtures';
import type { ApiClient, Seeder, UpstreamClient } from '../../fixtures';
import { MEDIA_SESSION_TOKEN_RE } from '../../fixtures/hls';
import { listRows } from '../../setup/http';
import { lockedProfile, stopChannels, withDeadline } from '../streaming/helpers';
import { SURFACES, gotoSurface } from './helpers';

const guideSurface = SURFACES.find((s) => s.name === 'Guide');
if (!guideSurface) {
  throw new Error('player-hls.spec.ts: no "Guide" entry in SURFACES — check helpers.ts');
}

/**
 * The browser player plays a live channel over HLS (Phase 4a-2, spec D18, § Browser
 * player) and ends its media session with `DELETE /hls/<token>` when it closes
 * (R24: the E2E never waits out the idle timeout).
 *
 * Runs in CI's Chromium, linux/amd64: it decodes H.264 and AAC through MSE, which
 * Playwright's linux/arm64 Chromium does not, so this cannot run on an arm64 Linux
 * host. hls.js is preferred over Chromium 151's native HLS by design.
 */

// Every channel this file tuned. The player leaves its session on close, and with
// the rewind window on (Phase 4a-3) that leaves the channel lingering for 300 s, so
// the teardown below stops it: fixture teardown runs even when a timeout abandons
// the test body.
const tuned: string[] = [];

test.afterEach(async ({ api }) => {
  await stopChannels(api, ...tuned.splice(0));
});

/** One SD channel the relay encodes in software on CI, as hls-sessions.spec.ts builds it. */
async function hlsChannel(upstream: UpstreamClient, seed: Seeder, api: ApiClient, name: string) {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name, tvgId: `${name.toLowerCase().replace(/\W+/g, '-')}.e2e`, logo: null, asset: 'mpeg2-576i-mp2' }],
    rate: 1,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });
  tuned.push(channel.uuid);
  return channel;
}

/**
 * The player preferences the page reads at load: a web-player Output Profile is set
 * (so the test can show the HLS tune ignores it, R18) and the player is muted, so
 * autoplay never depends on the headless autoplay policy.
 */
async function setPlayerPrefs(page: Page, api: ApiClient): Promise<void> {
  const profiles = listRows<{ id: number }>(
    await api.json<unknown>(await api.get('/api/core/outputprofiles/'), 'output profiles')
  );
  expect(profiles.length, 'an Output Profile to set as the web-player preference').toBeGreaterThan(0);
  const prefs = JSON.stringify({ webPlayerOutputProfileId: profiles[0].id, muted: true });
  await page.addInitScript((value) => {
    localStorage.setItem('dispatcharr-player-prefs', value);
  }, prefs);
}

interface Seen {
  method: string;
  url: URL;
  at: number;
}

/** Every request the page makes, from before the play click. */
function recordRequests(page: Page): Seen[] {
  const seen: Seen[] = [];
  page.on('request', (request: Request) => {
    seen.push({ method: request.method(), url: new URL(request.url()), at: Date.now() });
  });
  return seen;
}

/** Play the channel from the TV Guide's channel logo (`GuideRow.jsx` -> `getShowVideoUrl`). */
async function playFromGuide(page: Page, channelName: string): Promise<void> {
  await gotoSurface(page, guideSurface!);
  await page.getByPlaceholder('Search channels...').fill(channelName);
  await page.getByTestId('guide-grid').getByAltText(channelName, { exact: false }).click();
}

/** The one media-session token the page's `/hls/…` requests carry. */
function sessionToken(seen: Seen[]): string {
  const tokens = new Set(
    seen.filter((s) => s.url.pathname.startsWith('/hls/')).map((s) => s.url.pathname.split('/')[2])
  );
  expect([...tokens], 'exactly one media session was used').toHaveLength(1);
  const [token] = [...tokens];
  expect(token).toMatch(MEDIA_SESSION_TOKEN_RE);
  return token;
}

test(
  'a channel plays over HLS in the browser player, and closing the player leaves its session',
  { tag: '@contract' },
  async ({ adminPage, api, seed, upstream, streamClient, pageErrors }) => {
    const channel = await hlsChannel(upstream, seed, api, 'Player HLS');
    await setPlayerPrefs(adminPage, api);
    const seen = recordRequests(adminPage);

    // A TS client holds the channel open first, so it is still running when the
    // status is read after the leave (with no other client the leave would stop it).
    await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
    await withDeadline(streamClient.readPackets(20), 30_000, 'readPackets(20)');

    await playFromGuide(adminPage, channel.name);

    // The entry: an HLS tune with no Output Profile, although the preference is set.
    await expect
      .poll(() => seen.some((s) => s.url.pathname === `/proxy/ts/stream/${channel.uuid}`), {
        timeout: 30_000,
        message: 'the player requested the channel',
      })
      .toBe(true);
    const entry = seen.find((s) => s.url.pathname === `/proxy/ts/stream/${channel.uuid}`)!;
    expect(entry.url.searchParams.get('output_format'), 'the channel is tuned over HLS').toBe('hls');
    expect(
      entry.url.searchParams.has('output_profile'),
      'R18: an HLS tune carries no Output Profile, although the preference is set'
    ).toBe(false);

    // Playback: currentTime advances (a cold SD software entry needs the first budget).
    const video = adminPage.getByTestId('floating-video').locator('video');
    await expect
      .poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), {
        timeout: 60_000,
        message: 'the video started playing',
      })
      .toBeGreaterThan(0);
    const t0 = await video.evaluate((v: HTMLVideoElement) => v.currentTime);
    await expect
      .poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), {
        timeout: 30_000,
        message: 'the video keeps playing',
      })
      .toBeGreaterThan(t0 + 3);
    expect(await video.evaluate((v: HTMLVideoElement) => v.paused), 'the video is playing').toBe(false);

    // Presence: the HLS session is listed beside the TS client.
    const while_ = await readChannelStatus(api, channel.uuid);
    expect(while_.clients.map((c) => c.output_format).sort(), 'both viewers are listed').toEqual(['hls', 'mpegts']);

    await pageErrors.expectClean();
    pageErrors.waiveAutomaticCheck(
      'closing the player destroys hls.js, which aborts whichever playlist or segment request is in flight by design (FloatingVideo.jsx HLS destroy); the check above covered the whole playback'
    );

    // The leave.
    const token = sessionToken(seen);
    const left = adminPage.waitForResponse(
      (r) => r.request().method() === 'DELETE' && new URL(r.url()).pathname.startsWith('/hls/'),
      { timeout: 15_000 }
    );
    await adminPage.getByTestId('floating-video-close').click();
    const response = await left;
    expect(new URL(response.url()).pathname, 'the leave names the session the player used').toBe(`/hls/${token}`);
    expect(response.status(), 'the leave is answered 204').toBe(204);

    // The very next read: the 204 is written after the release, so no wait.
    const after = await readChannelStatus(api, channel.uuid);
    expect(after.clients.map((c) => c.output_format), 'only the TS client remains').toEqual(['mpegts']);
    await streamClient.close();
  }
);

// Characterization: this records hls.js 1.6.15's live-playlist reload behaviour with
// a paused media element (spec Q9). A different player library or version may
// change it; it pins nothing about Mino, and nothing gates on the numbers.
test(
  'Q9: how often hls.js reloads a live playlist while the player is paused',
  { tag: '@characterization' },
  async ({ adminPage, api, seed, upstream, pageErrors }, testInfo) => {
    const channel = await hlsChannel(upstream, seed, api, 'Player HLS Paused');
    await setPlayerPrefs(adminPage, api);
    const seen = recordRequests(adminPage);

    await playFromGuide(adminPage, channel.name);
    const video = adminPage.getByTestId('floating-video').locator('video');
    await expect
      .poll(() => video.evaluate((v: HTMLVideoElement) => v.currentTime), {
        timeout: 60_000,
        message: 'the video started playing',
      })
      .toBeGreaterThan(0);

    const token = sessionToken(seen);
    const windowSeconds = 20;
    await video.evaluate((v: HTMLVideoElement) => v.pause());
    const start = Date.now();
    await adminPage.waitForTimeout(windowSeconds * 1000);
    const inWindow = seen.filter((s) => s.method === 'GET' && s.at >= start);
    const videoPlaylistReloads = inWindow.filter((s) => s.url.pathname === `/hls/${token}/video.m3u8`).length;
    const segmentsFetched = inWindow.filter(
      (s) => s.url.pathname.startsWith(`/hls/${token}/`) && s.url.pathname.endsWith('.m4s')
    ).length;
    expect(await video.evaluate((v: HTMLVideoElement) => v.paused), 'the player stayed paused').toBe(true);

    // Recorded, never asserted on. It does not resume: if hls.js stopped reloading, the
    // session would have departed at the 12 s idle timeout, and a resumed player's 403
    // would fail the page-error check for the very outcome this measurement reports.
    const measurement = { videoPlaylistReloads, segmentsFetched, windowSeconds };
    testInfo.annotations.push({ type: 'Q9', description: JSON.stringify(measurement) });
    await testInfo.attach('q9.json', { body: JSON.stringify(measurement, null, 2), contentType: 'application/json' });
    console.log(`Q9: ${JSON.stringify(measurement)}`);

    await pageErrors.expectClean();
    pageErrors.waiveAutomaticCheck(
      'closing the player destroys hls.js, which aborts whichever playlist or segment request is in flight by design (FloatingVideo.jsx HLS destroy); the check above covered the whole playback'
    );
    await adminPage.getByTestId('floating-video-close').click();
  }
);
