import { test, expect, xcQuery } from '../../fixtures';
import { lockedProfile } from './helpers';

type XcStream = { stream_id: number };

// Asserts the behaviour Dispatcharr SHOULD have. `stream_xc`
// (apps/proxy/live_proxy/views.py) applies `user_level__lte` and Channel
// Profile membership to the requesting user, then serves the channel — with
// no `is_adult` filter, and no `hidden_from_output` exclusion either. Every
// listing path applies both for the same user.
//
// So a `hide_adult_content` user cannot see this channel in get_live_streams,
// in get.php's playlist or in xmltv.php's guide, and can still watch it by
// asking for it by id. That is CLAUDE.md's "hidden channels are unlistable
// yet still streamable", located precisely.
//
// Filed separately from the HDHomeRun defect (hdhr.spec.ts): stream_xc HAS
// the principal and omits one filter clause, so its fix is that clause; HDHR
// has no principal at all. Neither change closes the other.
//
// Issue: https://github.com/D10Scot/Dispatcharr/issues/87
test.fail('a channel a user cannot list is not streamable by that user', async ({
  upstream,
  seed,
  api,
  request,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G5 Adult', tvgId: 'g5-adult.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
    channel: { user_level: 0, is_adult: true },
  });

  const user = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  // The premise: this user genuinely cannot list the channel. Without it a
  // refusal below could mean anything.
  const listed: XcStream[] = JSON.parse(
    await (
      await request.get(
        `/player_api.php${xcQuery(user, { action: 'get_live_streams' })}`
      )
    ).text()
  );
  expect(listed.map((s) => s.stream_id)).not.toContain(channel.id);

  // streamClient, not request.get(): APIResponse.body() awaits the full
  // download and would never resolve against an endless TS stream if the
  // product does serve it — which today it does. `open()` throws on a
  // non-2xx, so resolving means the bytes started flowing.
  const served = await streamClient
    .open(`/live/${user.username}/${user.xcPassword}/${channel.id}`)
    .then(() => true)
    .catch(() => false);

  try {
    expect(
      served,
      'a channel hidden from this user by hide_adult_content must not stream'
    ).toBe(false);
  } finally {
    // Abort whatever was opened, so a failing run does not leave an upstream
    // connection held for the rest of the project.
    await streamClient.close();
  }
});
