/**
 * Signing in through an OpenID provider (SSO spec PR S5, the happy path).
 *
 * The browser clicks the provider's button on the login page; the fake OP in
 * `e2e-upstream` auto-approves the queued login and Mino completes the code flow
 * server-side, provisions the user just in time at the level its role claim maps to,
 * and hands the session to the SPA. The rest proves the session is a real one: the
 * channels page loads, the WebSocket connects, and a live channel plays.
 *
 * Plays over HLS in the floating player, which decodes H.264 and AAC through MSE: like
 * `tests/frontend/player-hls.spec.ts`, it cannot run in Playwright's linux/arm64
 * Chromium.
 */
import type { Page } from '@playwright/test';
import { test, expect } from './fixtures';
import { listRows } from '../../setup/http';
import { lockedProfile, stopChannels } from '../streaming/helpers';
import { SURFACES, gotoSurface } from '../frontend/helpers';
import { assertScopedStack } from './scope';
import {
  ADMIN_ROLE,
  createSsoProvider,
  retireSsoProvider,
  signInThroughSso,
  uniqueToken,
} from './helpers';
import type { SsoProvider, UserRow } from './helpers';

test.beforeAll(() => {
  assertScopedStack();
});

const guideSurface = SURFACES.find((s) => s.name === 'Guide');
if (!guideSurface) {
  throw new Error('sign-in.spec.ts: no "Guide" entry in SURFACES — check tests/frontend/helpers.ts');
}

const providers: SsoProvider[] = [];
const tuned: string[] = [];

test.afterEach(async ({ api }) => {
  await stopChannels(api, ...tuned.splice(0));
  for (const provider of providers.splice(0)) await retireSsoProvider(api, provider);
});

/** Whether the page's `/ws/` socket received `connection_established`. */
function watchWebSocket(page: Page): { established: () => boolean } {
  let established = false;
  page.on('websocket', (socket) => {
    if (!new URL(socket.url()).pathname.startsWith('/ws/')) return;
    socket.on('framereceived', (frame) => {
      if (typeof frame.payload === 'string' && frame.payload.includes('connection_established')) {
        established = true;
      }
    });
  });
  return { established: () => established };
}

test(
  'signs in through the fake OP and plays a channel',
  { tag: '@contract' },
  async ({ page, api, seed, upstream }) => {
    const provider = await createSsoProvider(api, 'signin');
    providers.push(provider);
    const username = `sso-admin-${uniqueToken()}`;
    await provider.queueLogin({
      sub: `sub-${uniqueToken()}`,
      preferred_username: username,
      email: `${username}@example.test`,
      name: 'SSO Admin',
      roles: [ADMIN_ROLE],
    });

    const name = `SSO Play ${uniqueToken()}`;
    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name, tvgId: `${name.toLowerCase().replace(/\W+/g, '-')}.e2e`, logo: null, asset: 'mpeg2-576i-mp2' },
      ],
      rate: 1,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel } = await seed.upstreamChannel(scenario, { channelIds: [1], streamProfileId: proxy.id });
    tuned.push(channel.uuid);

    // Muted, so playback never depends on the headless autoplay policy.
    await page.addInitScript(() => {
      localStorage.setItem('dispatcharr-player-prefs', JSON.stringify({ muted: true }));
    });
    const ws = watchWebSocket(page);

    await signInThroughSso(page, provider);

    // The channels page loads.
    await expect(page).toHaveURL(/\/channels/, { timeout: 30_000 });

    // The user was created just in time at the level its role mapped to.
    const users = listRows<UserRow>(await api.json<unknown>(await api.get('/api/accounts/users/'), 'list users'));
    const created = users.find((u) => u.username === username);
    expect(created, `a user ${username} was provisioned`).toBeDefined();
    expect(created!.user_level, 'the mapped level is Admin').toBe(10);

    // The WebSocket connects with the SSO session's token.
    await expect
      .poll(() => ws.established(), { timeout: 30_000, message: 'the /ws/ socket sent connection_established' })
      .toBe(true);

    // A live channel plays in the floating player.
    await gotoSurface(page, guideSurface!);
    // The Seeder generates the channel's own name; `name` above is the upstream's.
    await page.getByPlaceholder('Search channels...').fill(channel.name);
    await page
      .getByTestId('guide-grid')
      .locator('.channel-logo', { has: page.getByAltText(channel.name, { exact: false }) })
      .click();
    const video = page.getByTestId('floating-video').locator('video');
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

    // The OP saw exactly one honest login, end to end.
    expect((await provider.opLog()).map((e) => `${e.endpoint}:${e.outcome}`)).toEqual([
      'authorize:accepted',
      'token:accepted',
    ]);
  }
);
