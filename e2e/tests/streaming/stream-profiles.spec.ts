import { test, expect, expectTsAligned, expectContiguous, videoPidOf, readChannelStatus } from '../../fixtures';
import { lockedProfile } from './helpers';

test('the Redirect profile 302s the client at the provider and carries no bytes', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: [{ id: 1, name: 'G4 Redirect', tvgId: 'g4-redirect.e2e', logo: null }] });
  const redirect = await lockedProfile(api, 'Redirect');
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: redirect.id,
  });

  // Manual redirect: the Location header names a container-internal hostname
  // the Playwright host cannot resolve. Following it would exercise the fake
  // provider, not Dispatcharr — and validate_stream_url returns the URL it was
  // given, not the redirect target, so the Location is the upstream URL itself.
  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`, { redirect: 'manual' });

  expect(streamClient.status).toBe(302);
  const location = streamClient.headers?.get('location');
  expect(location, 'a Redirect profile must send a Location').toBeTruthy();

  // toControl throws on anything not under the internal origin — so this line
  // is itself the assertion that we were sent at the provider and nowhere else.
  expect(() => upstream.toControl(location!)).not.toThrow();
  expect(location).toBe(streams[0].url);

  // No bytes traversed Dispatcharr: that is what "no failover after connect"
  // means for this architecture.
  expect((await upstream.connections(scenario)).live).toBe(0);
});

test('the FFmpeg profile spawns a subprocess and reports its progress', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 FFmpeg', tvgId: 'g4-ffmpeg.e2e', logo: null }],
    rate: 20,
  });
  // Any profile that is not Proxy or Redirect takes the subprocess branch by
  // exclusion; seed.streamProfile()'s default command is an ffmpeg remux.
  const profile = await seed.streamProfile();
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: profile.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  const packets = await streamClient.readPackets(400);
  expectTsAligned(packets);
  expectContiguous(packets, videoPidOf(packets));

  // ffmpeg-derived fields appear on /status only for subprocess profiles.
  // Without this the row is indistinguishable from the Proxy row — and this is
  // the first test in this repository of any kind that spawns a subprocess.
  //
  // ffmpeg_speed arrives as a STRING. get_detailed_channel_info assigns the raw
  // Redis value with no conversion, while the neighbouring
  // get_basic_channel_info wraps it in float() — so the two endpoints disagree
  // about this field's type. Passing the raw value to toBeGreaterThan throws a
  // matcher error rather than failing an assertion, so parse it here.
  await expect
    .poll(
      async () => {
        const raw = (await readChannelStatus(api, channel.uuid)).ffmpeg_speed;
        return raw === undefined ? 0 : Number.parseFloat(raw);
      },
      { timeout: 60_000 }
    )
    .toBeGreaterThan(0);
});
