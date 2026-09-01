import { test, expect, expectTsAligned } from '../../fixtures';
import type { Channel, M3uAccount, StreamPage, UpstreamScenario } from '../../fixtures';
import { catchupRequests, catchupTimestampWithSeconds, withDeadline } from './helpers';

/**
 * `server_info.timezone` from the provider's own handshake drives
 * `convert_timestamp_to_provider_tz` (`apps/timeshift/helpers.py:134-160`),
 * and drops the seconds while it is at it.
 *
 * THE LIMIT: every assertion here reads the URL Dispatcharr **sent**, out of
 * the provider's scenario log. G8's archive is not time-addressable, so
 * these tests prove the right moment was ASKED FOR — never that Dispatcharr
 * seeks to it.
 *
 * A FIXED JANUARY DATE, deliberately: Europe/Brussels is +01:00 in January
 * and +02:00 in July, so a `new Date()` here would make the expected
 * provider timestamp a function of the day the suite runs. Do not
 * "modernise" these literals.
 *
 * `seedCatchupChannel` is not usable: it waits for the profile timezone to
 * be exactly `'UTC'`. That wait is the important part of it, so it is
 * reproduced below with the zone as a parameter rather than skipped.
 */
async function seedCatchupChannelInZone(
  fx: {
    upstream: import('../../fixtures').UpstreamClient;
    seed: import('../../fixtures').Seeder;
    api: import('../../fixtures').ApiClient;
    waitFor: import('../../fixtures').Waiter;
  },
  timezone: string
): Promise<{ scenario: UpstreamScenario; channel: Channel; providerStreamId: number }> {
  const { upstream, seed, api, waitFor } = fx;
  const prefix = seed.generatedName('catchup-tz');
  const providerStreamId = 1;

  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      { id: providerStreamId, name: `${prefix}-ch`, tvgId: `${prefix}-ch.e2e`, logo: null, categoryId: 1 },
    ],
    account: { serverInfo: { timezone } },
  });

  const account = await seed.xcAccount(scenario);
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    `streams ingested for ${prefix}`
  );
  const ingested = page.results.find((s) => s.name === `${prefix}-ch`);
  if (!ingested) throw new Error(`no ingested Stream named "${prefix}-ch" — the XC ingest is broken, not catch-up`);

  const created = await seed.channel({ streams: [ingested.id] });

  // D6: THE POLL IS A PRECONDITION, NOT A CONVENIENCE.
  // `refresh_account_profiles` is a separate `.delay()`'d task fired after
  // the refresh awaited above. Reading too early sees null — and
  // `convert_timestamp_to_provider_tz` treats null EXACTLY like "UTC"
  // (helpers.py:145-146), so a timestamp assertion made before this lands
  // passes whether or not any conversion happened. That is the failure mode
  // this wait exists to close.
  await waitFor.resource<M3uAccount>(
    `/api/m3u/accounts/${account.id}/`,
    (body) =>
      body.profiles.some(
        (p) =>
          (p.custom_properties as { server_info?: { timezone?: string } } | null)?.server_info
            ?.timezone === timezone
      ),
    { description: `the XC account profile to carry server_info.timezone ${timezone}` }
  );

  const channel = await api.json<Channel>(
    await api.get(`/api/channels/channels/${created.id}/`),
    `channel ${created.id} after wiring`
  );
  if (!channel.is_catchup) {
    throw new Error(
      `channel ${channel.id} is not is_catchup after the refresh — check the five ` +
        'preconditions before suspecting the timezone conversion.'
    );
  }

  return { scenario, channel, providerStreamId };
}

// 2026-01-15 is a WINTER date: Europe/Brussels is CET, +01:00. In July it
// would be CEST, +02:00, and this constant would be wrong for half the year.
const WINTER_START_UTC = '2026-01-15:12-00';
const WINTER_START_BRUSSELS = '2026-01-15:13-00';

test('the provider server_info.timezone converts the requested start before it is sent', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  const { scenario, channel, providerStreamId } = await seedCatchupChannelInZone(
    { upstream, seed, api, waitFor },
    'Europe/Brussels'
  );

  await streamClient.open(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(WINTER_START_UTC)}&duration=60`,
    { headers: { Authorization: `Bearer ${await api.freshAccessToken()}` } }
  );
  expectTsAligned(await streamClient.readPackets(20));
  await streamClient.close();

  const asked = catchupRequests(await upstream.log(scenario));
  expect(asked).toHaveLength(1);
  expect(asked[0].streamId).toBe(String(providerStreamId));

  // +01:00. The client asked for 12:00 UTC; the provider indexes its archive
  // in its own local time, so Dispatcharr asks it for 13:00
  // (`convert_timestamp_to_provider_tz`, helpers.py:158-160, reading the
  // DEFAULT profile's server_info even when another profile wins the
  // capacity walk — views.py:1658-1664).
  expect(asked[0].start).toBe(WINTER_START_BRUSSELS);

  // This proves the right moment was asked for, in the provider's own
  // clock. It does not prove Dispatcharr seeks to it: the fake archive
  // serves the same loop whatever `start` it is given, and it would have
  // served identical bytes for a wrong conversion.
});

// Guards the premise the test.fail() below depends on, from OUTSIDE the
// inverted block: test.fail() is satisfied by ANY failure inside it, so no
// assertion in that body — including the "UTC control" — can guard its own
// premise. This is the SAME shape of check the test.fail() below performs
// for its UTC half (same fault, same fixed instant, same candidate index),
// kept as a standalone, non-inverted test in this file so a change that
// silently breaks the four-candidate walk, or the colon-seconds candidate's
// second-preservation under UTC, signals here rather than only inside the
// inverted test where it would just read as "the pin still fails".
test('row 13 premise: under UTC, the colon-seconds PATH candidate preserves the requested seconds', async ({
  upstream,
  seed,
  api,
  waitFor,
  streamClient,
}) => {
  const startUtc = catchupTimestampWithSeconds(new Date(Date.UTC(2026, 0, 15, 12, 0, 45)));
  const token = await api.freshAccessToken();

  const utc = await seedCatchupChannelInZone({ upstream, seed, api, waitFor }, 'UTC');
  await upstream.fault(utc.scenario, 'catchup-layout-404', { layout: 'path' });
  // streamClient, not `request`: Playwright's request fixture buffers the
  // whole response body before its promise resolves (APIResponse.body()
  // internally awaits the full download — fixtures/stream-client.ts's class
  // doc says so directly), and this is a live, unbounded TS body. It hangs
  // to the project's 300s timeout instead of the open resolving on headers.
  // Confirmed by running this file before this fix: both `request.get()`
  // calls stalled for the full 300s and the run reported "Request context
  // disposed" at teardown. Nothing here needs the bytes, so open, then
  // close without reading — wrapped in withDeadline so a genuine stall
  // still fails by name rather than as an opaque project timeout.
  await withDeadline(
    streamClient.open(
      `/proxy/catchup/${utc.channel.uuid}?start=${encodeURIComponent(startUtc)}&duration=60`,
      { headers: { Authorization: `Bearer ${token}` } }
    ),
    30_000,
    'catch-up stream open (UTC)'
  );
  await streamClient.close();

  const utcAsked = catchupRequests(await upstream.log(utc.scenario));
  // Same walk as the test.fail() below: three PATH 404s then the QUERY
  // winner (apps/timeshift/helpers.py:466-498).
  expect(utcAsked, 'three PATH candidates then the QUERY winner, under UTC').toHaveLength(4);
  expect(utcAsked[2].start, 'UTC preserves the requested seconds').toBe('2026-01-15:12:00:45');
});

test.fail(
  'a requested start keeps its seconds whatever the provider timezone is',
  async ({ upstream, seed, api, waitFor, streamClient }) => {
    // KNOWN BUG — defect C3, filed as #111. Under a
    // non-UTC provider timezone, `convert_timestamp_to_provider_tz`
    // reformats through `strftime("%Y-%m-%d:%H-%M")` (helpers.py:160) and
    // drops the seconds, BEFORE `build_timeshift_candidate_urls`
    // re-derives the colon-seconds shape from the already-truncated value.
    // Under "UTC" the same start keeps them, because the function returns
    // its input unchanged (helpers.py:145-146). The precision of the
    // moment Dispatcharr asks for therefore depends on a field the
    // provider declares.
    //
    // The UTC control runs FIRST and PASSES, in this same test, so the
    // finding recorded here is the INCONSISTENCY between the two zones —
    // not truncation on its own, which someone could reasonably defend as
    // a minute-resolution product.
    //
    // The `catchup-layout-404 { layout: 'path' }` fault is what makes
    // candidate 2 observable at all: unfaulted, candidate 0 wins and the
    // colon-seconds shape is never sent.
    //
    // Derived through `catchupTimestampWithSeconds` rather than
    // hand-written. That helper exists precisely for a client timestamp
    // that carries seconds, and this is its only consumer — a literal here
    // would let the helper's shape and this test's expectation drift apart
    // silently. A FIXED instant (D11), not `new Date()`: Europe/Brussels is
    // +01:00 in January and +02:00 in July. Month index 0 is January.
    const startUtc = catchupTimestampWithSeconds(new Date(Date.UTC(2026, 0, 15, 12, 0, 45)));
    expect(startUtc, 'the fixed January instant this test is built on').toBe('2026-01-15:12-00-45');
    const token = await api.freshAccessToken();

    const utc = await seedCatchupChannelInZone({ upstream, seed, api, waitFor }, 'UTC');
    await upstream.fault(utc.scenario, 'catchup-layout-404', { layout: 'path' });
    // streamClient, not `request` — see the row-13-premise test above for
    // why: Playwright's request fixture buffers the full (unbounded, live)
    // response body before resolving, and hangs to the 300s project
    // timeout. Open and close without reading; nothing here needs the
    // bytes.
    await withDeadline(
      streamClient.open(
        `/proxy/catchup/${utc.channel.uuid}?start=${encodeURIComponent(startUtc)}&duration=60`,
        { headers: { Authorization: `Bearer ${token}` } }
      ),
      30_000,
      'catch-up stream open (UTC)'
    );
    await streamClient.close();
    const utcAsked = catchupRequests(await upstream.log(utc.scenario));
    // FOUR, exactly. With `catchup-layout-404 { layout: 'path' }` armed the
    // walk is deterministic: three PATH 404s, then QUERY candidate 3 wins
    // (apps/timeshift/helpers.py:466-498). A lower bound cannot tell "walked
    // PATH correctly" from "walked PATH five times", and the shape assertion
    // below indexes [2], which needs the walk pinned rather than bounded.
    expect(utcAsked, 'three PATH candidates then the QUERY winner, under UTC').toHaveLength(4);
    // PASSES: candidate 2, %Y-%m-%d:%H:%M:%S, keeps the requested :45.
    expect(utcAsked[2].start, 'UTC preserves the requested seconds').toBe('2026-01-15:12:00:45');

    const brussels = await seedCatchupChannelInZone(
      { upstream, seed, api, waitFor },
      'Europe/Brussels'
    );
    await upstream.fault(brussels.scenario, 'catchup-layout-404', { layout: 'path' });
    await withDeadline(
      streamClient.open(
        `/proxy/catchup/${brussels.channel.uuid}?start=${encodeURIComponent(startUtc)}&duration=60`,
        { headers: { Authorization: `Bearer ${token}` } }
      ),
      30_000,
      'catch-up stream open (Europe/Brussels)'
    );
    await streamClient.close();
    const bxlAsked = catchupRequests(await upstream.log(brussels.scenario));
    // Four again, for the same reason. The zone changes the timestamp, not
    // the candidate list.
    expect(
      bxlAsked,
      'three PATH candidates then the QUERY winner, under Europe/Brussels'
    ).toHaveLength(4);
    // FAILS TODAY: this is the CORRECT value. The actual value is
    // '2026-01-15:13:00:00'. Never invert this to assert the :00 — a
    // test.fail() that asserts the bug goes green the wrong way and locks
    // the defect in.
    expect(
      bxlAsked[2].start,
      'a non-UTC provider timezone must not truncate the requested seconds'
    ).toBe('2026-01-15:13:00:45');
  }
);

// Note the streamClient.open() calls above deliberately ignore the response
// body: with PATH blocked the walk falls through to QUERY and succeeds, so
// the client gets a stream body this test does not read — open, then close
// without ever calling readPackets(). `request.get()` (Playwright's request
// fixture) was tried first and does not work here: APIResponse.body()
// buffers the full response before resolving, and this is a live, unbounded
// TS body, so it hangs to the project's 300s timeout instead of resolving
// once headers arrive.
