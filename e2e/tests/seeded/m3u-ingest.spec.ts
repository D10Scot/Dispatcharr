import { test, expect } from '../../fixtures';
import type { ChannelGroup, M3uAccount, StreamPage } from '../../fixtures';

/**
 * The `group-title` every fake-provider channel carries, hardcoded in
 * `e2e-upstream/src/playlist.ts` (`renderPlaylist`). There is exactly one
 * ChannelGroup in play across every scenario and every worker, which is why
 * the group assertions below are membership checks and never counts.
 */
const UPSTREAM_GROUP_NAME = 'E2E';

test('an M3U refresh ingests the declared catalogue faithfully', async ({
  upstream,
  seed,
  api,
}) => {
  const prefix = seed.generatedName('catalogue');
  const declared = [1, 2, 3].map((id) => ({
    id,
    name: `${prefix}-ch${id}`,
    tvgId: `${prefix}-ch${id}.e2e`,
    logo: `https://example.invalid/${prefix}-ch${id}.png`,
  }));
  const scenario = await upstream.scenario({ channels: declared });

  const account = await seed.upstreamM3UAccount(scenario);

  // Scoped to this account, so `count` describes only this test's rows.
  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?m3u_account=${account.id}`),
    'streams ingested by this account'
  );
  expect(page.count).toBe(3);

  const byName = new Map(page.results.map((s) => [s.name, s]));
  for (const channel of declared) {
    const stream = byName.get(channel.name);
    expect(stream, `no stream named ${channel.name}`).toBeDefined();
    expect(stream!.tvg_id).toBe(channel.tvgId);
    expect(stream!.logo_url).toBe(channel.logo);
    expect(stream!.m3u_account).toBe(account.id);
    expect(stream!.is_custom).toBe(false);
    // The URL survived the round trip, which is what proves the playlist was
    // parsed rather than merely fetched.
    expect(stream!.url).toContain(scenario.id);
    expect(stream!.url).toContain(`/stream/${channel.id}.ts`);
  }

  // Every stream landed in one group, and that group is wired to this account.
  const groupIds = new Set(page.results.map((s) => s.channel_group));
  expect(groupIds.size).toBe(1);
  const groupId = page.results[0].channel_group;
  expect(groupId).not.toBeNull();

  const readBack = await api.json<M3uAccount & { channel_groups: { channel_group: number }[] }>(
    await api.get(`/api/m3u/accounts/${account.id}/`),
    'account read-back for its group relations'
  );
  expect(readBack.channel_groups.map((g) => g.channel_group)).toContain(groupId);

  // Global, unpaginated list — membership only, never a count.
  const groups = await api.json<ChannelGroup[]>(
    await api.get('/api/channels/groups/'),
    'channel groups'
  );
  expect(groups.find((g) => g.id === groupId)?.name).toBe(UPSTREAM_GROUP_NAME);
});
