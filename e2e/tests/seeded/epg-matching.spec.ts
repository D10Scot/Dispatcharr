import { test, expect } from '../../fixtures';
import type { Channel, EpgData, EpgMatchAssociation } from '../../fixtures';

/**
 * `apps/channels/epg_matching.py` end to end: the exact-`tvg_id` short
 * circuit, the fuzzy scan, and the two `match-epg` HTTP shapes (per-channel
 * detail, and a collection call). Every test in this file is written to
 * **never touch the ML path** — see the rule below — so none of them can
 * download or exercise `sentence-transformers/all-MiniLM-L6-v2`.
 *
 * **Test 8 (the bulk "no match" characterization test) is not in this file.**
 * It was implemented, and both its own assertions and the file's typecheck
 * passed — but a live run against this shared container proved the design
 * unsafe: two channels named with `seed.channel()`'s own default
 * `e2e-w{worker}-{runToken}-{testId}-channel-{n}` shape scored 56.91 (bulk
 * `[50, 70)` ML band) against a *leftover* `EPGData` row from an earlier,
 * unrelated `epg-ingest.spec.ts` run (`e2e-w2-w287b9-...-epg-0-ch2`, itself
 * a `seed.generatedName('epg')`-shaped name) and were matched via the ML
 * "desperate last resort" branch — downloading
 * `sentence-transformers/all-MiniLM-L6-v2` into this container's
 * `/data/models` for real. Task 0's Probe B never measured a
 * generatedName-shaped token against *another* generatedName-shaped token
 * (only against natural-language EPG names, where the margin genuinely
 * holds at 17–26); two such tokens share enough character-level structure
 * (worker/run/test-id digits, hyphens stripped to nothing by
 * `normalize_name`) to land squarely in the ML band, and this container
 * already has years^Wmany runs' worth of such leftover rows sitting active.
 * The test's own assertions still reported green, because its ws-based
 * settle signal (a same-type, unrelated `epg_match` broadcast from another
 * worker) resolved *before* this run's ML-delayed match actually committed
 * — a second, independent defect in the test, not just in the pair choice.
 * Per the dispatching brief: "If a pair cannot be placed cleanly outside the
 * ML bands after measuring, stop and say so — the fallback (spec D6a) is a
 * decision for the controller, not something to work around." Left out
 * rather than shipped broken or silently disabled; see
 * `task-4-6-report.md` for the full trace.
 *
 * ---------------------------------------------------------------------------
 * The ML band rule (D6) — read this before adding a name pair to this file
 * ---------------------------------------------------------------------------
 * `try_epg_name_match` calls `get_sentence_transformer()` — which lazily
 * downloads `sentence-transformers/all-MiniLM-L6-v2` into `/data/models` on
 * first use — whenever the best fuzzy score falls inside the ML bands.
 * `_get_epg_match_thresholds(is_bulk_matching)` (`apps/channels/epg_matching.py`)
 * defines twelve numbers, six per branch:
 *
 * | Threshold | Bulk (`is_bulk_matching=True`, `len(channels_data) > 1`) | Single (`is_bulk_matching=False`) |
 * |---|---|---|
 * | `FUZZY_HIGH_CONFIDENCE` | 90 | 85 |
 * | `FUZZY_SKIP_ML` | 80 | 75 |
 * | `FUZZY_MEDIUM_CONFIDENCE` | 70 | 40 |
 * | `ML_HIGH_CONFIDENCE` | 0.75 | 0.65 |
 * | `ML_LAST_RESORT` | 0.65 | 0.50 |
 * | `FUZZY_LAST_RESORT_MIN` | 50 | 20 |
 *
 * A score at or above `FUZZY_SKIP_ML` matches with no ML call at all; a score
 * below `FUZZY_LAST_RESORT_MIN` never reaches `try_epg_name_match`'s ML
 * branches either (it falls through the last `if` to "no match", the branch
 * that begins with `logger.info(...best fuzzy score=...)`). Every score this
 * file produces or measures is engineered to land at or above
 * `FUZZY_SKIP_ML` or below `FUZZY_LAST_RESORT_MIN` for whichever path
 * (bulk/single) it takes: **>= 80 or < 50 on the bulk path, >= 75 or < 20 on
 * the single path.** Nothing here is allowed to land inside
 * `[FUZZY_LAST_RESORT_MIN, FUZZY_SKIP_ML)` on either branch — that is the
 * band that calls `get_sentence_transformer()`.
 *
 * ---------------------------------------------------------------------------
 * The cross-worker aliasing hazard
 * ---------------------------------------------------------------------------
 * `_active_epg_fuzzy_queryset` (and `_active_epg_lookup_queryset` beneath it)
 * filters on `epg_source__is_active=True` and nothing else — no scoping to a
 * source this test created. Every `EPGData` row of every active source on
 * the shared `seeded` container is a fuzzy-scan candidate, including G3's
 * `epg-ingest.spec.ts` fixtures and every other worker's concurrent EPG
 * source. The mitigation used throughout this file is (a) per-test entropy
 * baked into names that matter for a match, and (b) asserting the *specific*
 * `epg_data_id`/`epg_data`.`id` this test's own row got, never a bare
 * "something matched". That is a mitigation, not a proof: nothing here can
 * rule out a foreign row scoring higher than an intended one by coincidence.
 *
 * ---------------------------------------------------------------------------
 * D7 — `match-epg` is never called with an omitted or empty `channel_ids`
 * ---------------------------------------------------------------------------
 * `ChannelViewSet.match_epg` branches on `if channel_ids:` — an omitted or
 * empty list runs `match_epg_channels.delay()`, which rewrites every
 * EPG-less channel on the instance. Every collection call in this file
 * passes a non-empty `channel_ids`.
 *
 * ---------------------------------------------------------------------------
 * Probe B — measured scores (Task 0, `task-0-report.md`), verbatim
 * ---------------------------------------------------------------------------
 * Near-identical pair family (band a, need >= 75, single-channel path,
 * `FUZZY_SKIP_ML`), unsuffixed:
 *
 *   'Cascade Nature' | 'Cascade Natures'          -> 96.55172413793103
 *   'Cascade Nature' | 'Cascade Naturre'          -> 96.55172413793103
 *   'Meridian Cinema Plus' | 'Meridian Cinema Prime' -> 82.92682926829268
 *   'Quantum Signal One' | 'Quantum Sygnal One'   -> 94.44444444444444
 *   'Foghorn Aurora' | 'Foghorn Aurorra'          -> 96.55172413793103
 *
 * No-match family (band b, need < 50 against everything plausible, bulk
 * path, `FUZZY_LAST_RESORT_MIN`) — a `seed.generatedName('channel')`-shaped
 * token (e.g. `e2e-w3-a1b2c3-t9f8e7-channel-4`, normalised to one unbroken
 * low-vowel-density token with no natural-language structure) against seven
 * plausible *natural-language* EPG names — this margin holds, but see the
 * note at the top of the file on why it does not hold against another
 * generatedName-shaped candidate, which is what actually sank test 8:
 *
 *   'BBC One'                 -> 25.0
 *   'Sky Sports Main Event'   -> 17.391304347826086
 *   'Discovery Science'       -> 23.809523809523814
 *   'Fake Channel 1'          -> 19.354838709677423
 *   'Fake Channel 42'         -> 25.0
 *   'Meridian Cinema Prime'   -> 26.086956521739136
 *   'Quantum Signal One'      -> 23.25581395348837
 *   'Cascade Natures'         -> 25.0
 *
 * Test 7 uses the `Meridian Cinema Plus` / `Meridian Cinema Prime` pair
 * (82.93, an 8-point margin above `FUZZY_SKIP_ML`=75, comfortably clear of
 * the `[70, 80)` bulk ML band too — it never enters that branch, but the
 * margin matters because the *suffixed* pair below is what the test actually
 * runs). No third pair was built for the removed test 9's `[75, 80)`
 * disagreement band (see `task-4-6-brief.md` Task 6 — that band is
 * unreachable on the bulk path without calling `get_sentence_transformer()`
 * for every score in `[70, 80)`).
 *
 * Re-measured **with per-test entropy** (a shared suffix token in both
 * halves, per the cross-worker note above — required because an unsuffixed
 * `Meridian Cinema Prime` EPGData row created by one worker's test 7 run
 * would otherwise be a candidate for another worker's concurrent run of the
 * same test), using the same `docker exec ... manage.py shell` probe against
 * `normalize_name` + `rapidfuzz.fuzz.ratio`, single path (`FUZZY_SKIP_ML` =
 * 75):
 *
 *   'Meridian Cinema Plus w3-a1b2c3-t9f8e7-7' | 'Meridian Cinema Prime w3-a1b2c3-t9f8e7-7' -> 90.41
 *   'Meridian Cinema Plus w3a1b2c37'          | 'Meridian Cinema Prime w3a1b2c37'          -> 88.52
 *   'Meridian Cinema Plus x7q9'               | 'Meridian Cinema Prime x7q9'               -> 86.27
 *   'Meridian Cinema Plus e2e-w3-a1b2c3-3a7f9e21c4b8-x-4' | 'Meridian Cinema Prime e2e-w3-a1b2c3-3a7f9e21c4b8-x-4' -> 92.47
 *   'Meridian Cinema Plus e2e-w0-abc123-9f8e7d6c5b4a3f2e1d0c-x-1' | 'Meridian Cinema Prime e2e-w0-abc123-9f8e7d6c5b4a3f2e1d0c-x-1' -> 93.58
 *
 * A shared suffix *raises* the ratio (more of the two normalised strings are
 * now identical), so the margin only grows with a longer/more realistic
 * token — every shape tried, from a short 4-char token to a full
 * `seed.generatedName()`-length one, lands well clear of 75 and clear of the
 * `[40, 75)` single-path ML band. The test below uses a real
 * `seed.generatedName(...)` value as the token, which this table already
 * covers (the two `e2e-w...` rows).
 */

test('an exact tvg_id match short-circuits before any fuzzy name comparison', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  ws,
}) => {
  // One XMLTV fetch-and-parse plus a single-channel match against the
  // `seeded` project's 30s default.
  test.setTimeout(90_000);

  const prefix = seed.generatedName('epgmatch6');
  const declared = [1, 2].map((id) => ({
    id,
    name: `${prefix}-ch${id}`,
    tvgId: `${prefix}-ch${id}.e2e`,
    logo: null,
  }));
  const scenario = await upstream.scenario({ channels: declared });
  const source = await seed.upstreamEpgSource(scenario, { refresh_interval: 0 });

  // `/api/epg/epgdata/` has no filterset and no pagination — filter
  // client-side and locate with `find`, never a length or an index.
  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const targetRow = allEpgData.find(
    (d) => d.tvg_id === declared[0].tvgId && d.epg_source === source.id
  );
  expect(targetRow, `no EPGData for ${declared[0].tvgId}`).toBeDefined();
  const otherRow = allEpgData.find(
    (d) => d.tvg_id === declared[1].tvgId && d.epg_source === source.id
  );
  expect(otherRow, `no EPGData for ${declared[1].tvgId}`).toBeDefined();

  // `seed.channel()` always assigns its own generated name (a caller-supplied
  // `name` override is silently discarded — see `seed.ts`), which is exactly
  // the "deliberately unrelated name" this test needs: it shares no words
  // with `declared[0].name`, so only the exact-tvg_id path can succeed. Name
  // distance is irrelevant to this test, which is exactly why it must not
  // touch the fuzzy/ML branch.
  const channel = await seed.channel({ tvg_id: declared[0].tvgId });

  // Registered before the POST: the channel id already exists, so any early
  // arrival is queued rather than missed.
  const matchWait = ws.waitForMessage('single_channel_epg_match', {
    where: (d) => d.channel_id === channel.id,
  });

  const res = await api.post(`/api/channels/channels/${channel.id}/match-epg/`, {});
  expect(res.status()).toBe(202);
  const body = await api.json<{ accepted: boolean; channel_id: number }>(
    res,
    'match-epg (detail) response'
  );
  expect(body.accepted).toBe(true);
  expect(body.channel_id).toBe(channel.id);

  const message = await matchWait;
  expect(message.data?.matched).toBe(true);
  expect(message.data?.epg_id).toBe(targetRow!.id);

  const updated = await api.json<Channel>(
    await api.get(`/api/channels/channels/${channel.id}/`),
    'channel after match-epg'
  );
  expect(updated.epg_data_id).toBe(targetRow!.id);
});

// @characterization: pins FUZZY_SKIP_ML = 75 on the single-channel path
// (`_get_epg_match_thresholds(is_bulk_matching=False)`), the threshold this
// test's measured score (see below) sits above.
test('a near-identical name matches through fuzzy scoring alone, with no tvg_id and no ML call', { tag: '@characterization' }, async ({
  upstream,
  seed,
  api,
  ws,
}) => {
  // One XMLTV fetch-and-parse, a rename, and a single-channel match against
  // the `seeded` project's 30s default.
  test.setTimeout(120_000);

  // The shared-suffix token: per-test entropy in *both* halves of the pair,
  // so an identically-named foreign EPGData row from a concurrent worker's
  // run of this same test cannot be the one that wins the match (see the
  // header's cross-worker note). `seed.generatedName(...)` is exactly the
  // token shape re-measured above (the two `e2e-w...` rows), where the
  // score was 92.47/93.58 — comfortably above 75 regardless of the exact
  // token length this run produces.
  const token = seed.generatedName('fuzzy7');
  const epgName = `Meridian Cinema Prime ${token}`;
  const declared = [{ id: 1, name: epgName, tvgId: `${token}.e2e`, logo: null }];
  const scenario = await upstream.scenario({ channels: declared });
  const source = await seed.upstreamEpgSource(scenario, { refresh_interval: 0 });

  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const epgRow = allEpgData.find(
    (d) => d.tvg_id === declared[0].tvgId && d.epg_source === source.id
  );
  expect(epgRow, `no EPGData for ${declared[0].tvgId}`).toBeDefined();

  // `seed.channel()` always assigns its own generated name; rename through a
  // normal PATCH (a writable field on `ChannelSerializer`) to the raw
  // channel half of the measured pair plus the same token. No tvg_id and no
  // tvc_guide_stationid are ever set on this channel, so the exact-id path
  // (test 6) cannot fire and this is forced onto the fuzzy scan.
  const channel = await seed.channel();
  const renamed = await api.patch(`/api/channels/channels/${channel.id}/`, {
    name: `Meridian Cinema Plus ${token}`,
  });
  expect(renamed.status()).toBe(200);

  const matchWait = ws.waitForMessage('single_channel_epg_match', {
    where: (d) => d.channel_id === channel.id,
  });

  const res = await api.post(`/api/channels/channels/${channel.id}/match-epg/`, {});
  expect(res.status()).toBe(202);

  const message = await matchWait;
  expect(message.data?.matched).toBe(true);
  expect(message.data?.epg_id).toBe(epgRow!.id);

  const updated = await api.json<Channel>(
    await api.get(`/api/channels/channels/${channel.id}/`),
    'channel after match-epg'
  );
  expect(updated.epg_data_id).toBe(epgRow!.id);
});

test('a collection match-epg names its associations, and a confirming re-run reports no changes', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  ws,
}) => {
  // One XMLTV fetch-and-parse plus two bulk match calls against the
  // `seeded` project's 30s default.
  test.setTimeout(120_000);

  const prefix = seed.generatedName('epgmatch10');
  const declared = [1, 2].map((id) => ({
    id,
    name: `${prefix}-ch${id}`,
    tvgId: `${prefix}-ch${id}.e2e`,
    logo: null,
  }));
  const scenario = await upstream.scenario({ channels: declared });
  const source = await seed.upstreamEpgSource(scenario, { refresh_interval: 0 });

  const allEpgData = await api.json<EpgData[]>(
    await api.get('/api/epg/epgdata/'),
    'EPGData rows'
  );
  const epgRows = declared.map((spec) => {
    const row = allEpgData.find((d) => d.tvg_id === spec.tvgId && d.epg_source === source.id);
    expect(row, `no EPGData for ${spec.tvgId}`).toBeDefined();
    return row!;
  });

  // Both channels matched by exact tvg_id — no score is involved, so this
  // test never touches the ML rule despite running the bulk
  // (`is_bulk_matching = len(channels_data) > 1 = True`) thresholds.
  const channelA = await seed.channel({ tvg_id: declared[0].tvgId });
  const channelB = await seed.channel({ tvg_id: declared[1].tvgId });

  // Registered before the POST, correlated on channelA's id inside the
  // `associations` array — the one id this file's other tests cannot also
  // produce (they never touch these two channels).
  const firstMatch = ws.waitForMessage('epg_match', {
    where: (d) =>
      Array.isArray(d.associations) &&
      (d.associations as EpgMatchAssociation[]).some((a) => a.channel_id === channelA.id),
  });

  const res1 = await api.post('/api/channels/channels/match-epg/', {
    channel_ids: [channelA.id, channelB.id],
  });
  expect(res1.status()).toBe(202);

  const message1 = await firstMatch;
  const associations1 = (message1.data?.associations ?? []) as EpgMatchAssociation[];
  const matchA = associations1.find((a) => a.channel_id === channelA.id);
  const matchB = associations1.find((a) => a.channel_id === channelB.id);
  expect(matchA?.epg_data_id).toBe(epgRows[0].id);
  expect(matchB?.epg_data_id).toBe(epgRows[1].id);
  expect(message1.data?.matches_count).toBe(2);

  const readA1 = await api.json<Channel>(
    await api.get(`/api/channels/channels/${channelA.id}/`),
    'channel A after first match-epg'
  );
  expect(readA1.epg_data_id).toBe(epgRows[0].id);

  // The confirming re-run: `apply_matched_epg_to_channels` returns changed
  // rows only, and both channels already sit on the matched EPGData, so
  // nothing changes. This second `epg_match` cannot be correlated to this
  // POST by any id in its payload either (same limitation as test 8's
  // negative check — `associations` is empty here, so there is no id to
  // filter on), so it is treated as a best-effort settle signal and
  // `matches_count === 0` / an `associations` array excluding both ids is
  // the assertable contract, not proof this exact message was caused by
  // this exact POST.
  const secondMatch = ws.waitForMessage('epg_match', { timeoutMs: 30_000 });

  const res2 = await api.post('/api/channels/channels/match-epg/', {
    channel_ids: [channelA.id, channelB.id],
  });
  expect(res2.status()).toBe(202);

  const message2 = await secondMatch;
  expect(message2.data?.matches_count).toBe(0);
  const associations2 = (message2.data?.associations ?? []) as EpgMatchAssociation[];
  expect(
    associations2.some((a) => a.channel_id === channelA.id || a.channel_id === channelB.id)
  ).toBe(false);
});
