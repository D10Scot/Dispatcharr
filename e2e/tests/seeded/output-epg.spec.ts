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
  // mid-test twice in a row before this was narrowed to 30.
  //
  // The `workerIndex * 97` term is a shift of an already-uniform
  // distribution over the 30 buckets below — it does not add separation
  // between workers, and none is needed here: this is one test in one spec
  // file, so it always runs on a single worker and never contends with
  // another worker for a cache key. It's kept only because a shift is
  // harmless and removing it buys nothing. The random component is what
  // matters: it separates this test from the same test in an earlier run
  // inside the same 300-second window. (Accepted risk, not fixed here: with
  // only 30 buckets, several such runs in one window can still collide —
  // see the task report.)
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

  // Filtering programmes by `mine!.id` (the channel number) relies on that
  // number being unique instance-wide, not merely per-request: `seed.channel()`
  // never overrides channel_number, so creation falls through to
  // `Channel.get_next_available_channel_number()` (apps/channels/models.py),
  // which builds a reserved set from EVERY existing channel_number on the
  // instance — not just this channel's group — before handing one out. So a
  // collision here would mean the allocator itself is broken. The exact-count
  // assertion below is a second line of defence regardless: a collision
  // (two channels sharing an id) would inflate the count past `6 * days`, so
  // that assertion would fail even if this reasoning were wrong.
  //
  // A channel with no epg_data still gets programmes: generate_epg routes it
  // to generate_dummy_programs. That is what makes this row independent of
  // G3's EPG ingest.
  const mineProgrammes = guide.programmes.filter((p) => p.channel === mine!.id);

  // Exact, not `toBeGreaterThan(0)`: generate_dummy_programs's default path
  // (apps/output/epg.py:223-232, the one this test hits — a plain seeded
  // channel has no epg_data, so `epg_source` is None and the custom-pattern
  // branch at :162 is skipped entirely) is a bare nested loop, `for day in
  // range(num_days)` × `for hour_offset in range(0, 24, program_length_hours)`
  // with `program_length_hours = 4` fixed at the call site (:1653) — six
  // 4-hour slots per day, every day, with no early cutoff. `export_cutoff`
  // IS threaded through this function's signature and is passed a real value
  // at the call site (:1660), but every place that actually reads it
  // (:675-703) is inside `generate_custom_dummy_programs`, the *other* dummy
  // path (triggered only when `epg_source.custom_properties` is set) — this
  // function's own default loop never looks at it. So the count is exactly
  // predictable: `6 * days`.
  expect(mineProgrammes.length, `expected 6 * ${days} programmes`).toBe(6 * days);

  expect(mineProgrammes[0].start).toMatch(/^\d{14} [+-]\d{4}$/);
  // Exact, not `.not.toBe('')`: the default dummy generator sets
  // `"title": channel_name` verbatim (apps/output/epg.py:251), with no
  // decoration — so the seeded channel's own name is the one predictable
  // value, not merely "some non-empty string".
  expect(mineProgrammes[0].title).toBe(channel.name);
});
