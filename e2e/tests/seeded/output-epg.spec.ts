import { test, expect, epgQuery, parseXmltv, expectWellFormedXml } from '../../fixtures';

/**
 * `/output/epg` — the client-facing XMLTV guide surface.
 *
 * Every fetch below goes through `epgQuery()` rather than a bare URL, and
 * that is not tuning — it is the only way this test can see its own channel.
 * `/output/epg` is served from a 300-second Redis chunk cache that a plain
 * `seed.channel()` does not invalidate, so an un-busted fetch reads a body
 * rendered up to five minutes before the channel existed. The helper carries
 * the cache-key analysis, the empirical confirmation of it, and why the
 * entropy lives on `tvg_id_source` rather than on `days`.
 */

test('/output/epg is well-formed XMLTV carrying programmes for a seeded channel', { tag: '@contract' }, async ({
  seed,
  request,
  adminPage,
}) => {
  const channel = await seed.channel();
  // One day, fixed. The body carries 6 programmes per day for EVERY EPG-less
  // channel the instance has accumulated — a population that only ever grows,
  // since nothing in `seeded` deletes a channel — and the whole string also
  // goes through `page.evaluate` in expectWellFormedXml plus four `matchAll`
  // passes in parseXmltv, inside this project's 30-second timeout. A wider
  // window bought nothing here: 6 is still an exact, falsifiable count.
  const days = 1;

  const res = await request.get(`/output/epg${epgQuery(days)}`);
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/xml');

  const body = await res.text();

  // A real XML parser's verdict, not the shallow reader's. parseXmltv would
  // extract elements out of a document with an unclosed root.
  await expectWellFormedXml(adminPage, body);

  const guide = parseXmltv(body);

  // The channel id is the formatted channel number for an anonymous request
  // (`tvg_id_source` is compared only against 'tvg_id' and 'gracenote', and
  // epgQuery()'s cache-busting token is neither, so this takes the same
  // default branch as an unset parameter), so find by display-name — the one
  // value this test controls.
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
