import { test, expect, parseXmltv, expectWellFormedXml } from '../../fixtures';

/**
 * `/output/epg` — the client-facing XMLTV guide surface.
 *
 * Every fetch below passes a distinct `?days=`. That is not tuning, it is the
 * only way this test can see its own channel.
 *
 * `/output/epg` is served from a Redis chunk cache with a 300-second TTL
 * (`stream_cached_response`, DEFAULT_CACHE_TTL), and the cache key is
 * `profile:username:d=:p=:logos=:tvgid=:origin=` — the raw query string is
 * NOT in it, so `?e2e=<token>` does not bust it. Creating a channel
 * invalidates the cache only when `epg_data` is involved
 * (`refresh_epg_programs` in apps/channels/signals.py), which a plain seeded
 * channel is not. Without a distinct `days` this test reads a body rendered
 * up to five minutes before its channel existed.
 *
 * `days` is clamped to 0-365 and only widens the programme window, so it is a
 * safe key to vary. Measured this session against the live stack (g5,
 * localhost:9291): a `?days=7` fetch, then creating a channel, then a second
 * `?days=7` fetch both counted 404 `<channel id=` elements — identical,
 * confirming the cache serves the pre-create body. A third fetch with
 * `?days=8` counted 405 — the new channel appeared immediately once the key
 * changed. The probe channel was deleted afterward so it doesn't linger in
 * the instance's channel population.
 */
function uniqueDays(testInfo: { workerIndex: number }): number {
  // 1-30, not the wider 1-365 the cache-key argument alone would allow.
  // `generate_epg` gives every EPG-less channel on the instance 6
  // programmes/day (apps/output/epg.py:227,1101,1653), for every channel —
  // not just this test's — so `days` also sets how much of that fires per
  // fetch. At 365 that's 2,190 programmes/channel, multiplied by every
  // channel every seeded test has ever left behind; parsing that body
  // against a live page timed out `expectWellFormedXml` and closed the page
  // mid-test twice in a row before this was narrowed to 30. Worker index
  // separates concurrent workers; the random component separates this test
  // from the same test in an earlier run inside the same 300-second window.
  return 1 + ((testInfo.workerIndex * 97 + Math.floor(Math.random() * 300)) % 30);
}

test('/output/epg is well-formed XMLTV carrying programmes for a seeded channel', async ({
  seed,
  request,
  adminPage,
}, testInfo) => {
  const channel = await seed.channel();
  const days = uniqueDays(testInfo);

  const res = await request.get(`/output/epg?days=${days}`);
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/xml');

  const body = await res.text();

  // A real XML parser's verdict, not the shallow reader's. parseXmltv would
  // extract elements out of a document with an unclosed root.
  await expectWellFormedXml(adminPage, body);

  const guide = parseXmltv(body);

  // The channel id is the formatted channel number for an anonymous request
  // (tvg_id_source defaults to 'channel_number'), so find by display-name —
  // the one value this test controls.
  const mine = guide.channels.find((c) => c.displayNames.includes(channel.name));
  expect(mine, `a <channel> for ${channel.name} should be in the guide`).toBeDefined();

  // A channel with no epg_data still gets programmes: generate_epg routes it
  // to generate_dummy_programs. That is what makes this row independent of
  // G3's EPG ingest.
  const mineProgrammes = guide.programmes.filter((p) => p.channel === mine!.id);
  expect(
    mineProgrammes.length,
    'the dummy EPG generator should have produced programmes'
  ).toBeGreaterThan(0);
  expect(mineProgrammes[0].start).toMatch(/^\d{14} [+-]\d{4}$/);
  expect(mineProgrammes[0].title).not.toBe('');
});
