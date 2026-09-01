import { test, expect } from '../../fixtures';
import type { M3uAccount } from '../../fixtures';
import {
  catchupRequests,
  catchupTimestamp,
  newStreamClient,
  seedCatchupChannel,
  withDeadline,
} from '../streaming/helpers';

/**
 * POSITIVE CONTROL for the main test below.
 *
 * An empty provider log proves nothing on its own — it is exactly what a
 * test that never actually triggered a request also produces. Before
 * trusting `toHaveLength(0)` as evidence that a precondition failure blocked
 * upstream contact, this proves the same log-reading path
 * (`upstream.log()` → `catchupRequests()`) against the same kind of scenario
 * CAN see a non-empty result when a request genuinely reaches the provider.
 *
 * Uses its own scenario/channel rather than sharing the main test's: once a
 * request reaches the provider, that scenario's log carries the entry
 * permanently (`ScenarioLog.record` only appends), which would break the
 * main test's own `toHaveLength(0)` if they shared a scenario.
 *
 * All four preconditions are satisfied here (real catch-up channel, active
 * account, valid timestamp), so `_serve_catchup` reaches the success path.
 * Empirically (checked before writing this assertion, not assumed from the
 * architecture docs) this stack's default Stream Profile is *not* Redirect:
 * the first request 301s the client back to `catchup_proxy` itself with a
 * freshly minted `session_id` (`_redirect_with_new_session`,
 * `apps/timeshift/views.py:437`) rather than straight at the provider.
 * "Established session_id requests keep proxying below" (`views.py:409`) —
 * so the *second* request, replaying that same Location, is the one that
 * walks into `_attempt_timeshift_stream` and actually contacts the
 * provider. Two hops, not one; a test that stopped at the first 301 would
 * itself be the empty-log trap this control exists to catch.
 *
 * The second hop's response is a live, unbounded `video/mp2t` body (this is
 * `catchup_proxy` proxying real stream bytes) — `request.get()` buffers a
 * whole response before resolving and hangs the test timeout out trying,
 * so this uses `StreamClient`, the same incremental reader the streaming
 * rows use, and closes it the moment a few packets are confirmed flowing.
 * That open+read is wrapped in `withDeadline`, so a stalled second hop
 * surfaces as a named 10s timeout rather than the 300s project timeout.
 *
 * Only true on a *fresh* scenario. `_find_matching_pool_session` is called
 * with `include_busy=True` (`views.py:390-397`), so a scenario that already
 * has a pool entry for this media — a second test reusing it, or a retried
 * run — could route the first request straight into the proxy branch
 * instead of minting a new session, changing which hop actually contacts
 * the provider. `seedCatchupChannel` here always builds a brand-new
 * scenario, so that never happens in this test as written.
 */
test('positive control: a satisfied request reaches the provider and is logged', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
  baseURL,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const token = await api.freshAccessToken();
  const auth = { Authorization: `Bearer ${token}` };
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  expect(
    catchupRequests(await upstream.log(scenario)),
    'sanity: nothing has touched this fresh scenario yet'
  ).toHaveLength(0);

  const first = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}`,
    { headers: auth, maxRedirects: 0 }
  );
  expect(first.status(), 'a fully satisfied first request mints a session and redirects').toBe(301);
  const sessionLocation = first.headers()['location'];
  expect(sessionLocation, 'the redirect must carry a Location header').toBeTruthy();

  // Replay with the minted session_id — this is the hop that actually
  // proxies bytes from the provider. A live TS body, so read a couple of
  // packets and close rather than waiting for the (never-ending) stream.
  const client = newStreamClient(baseURL!);
  try {
    await withDeadline(
      (async () => {
        await client.open(sessionLocation, { headers: auth });
        // 200, not merely "not an error": a second 3xx would also satisfy
        // < 400 while actually being another bounce rather than proxied
        // bytes, which is exactly the failure this hop exists to rule out.
        expect(
          client.status,
          'the session-bearing replay must return 200 (proxied bytes), not another redirect'
        ).toBe(200);
        await client.readPackets(1);
      })(),
      10_000,
      'positive control: second-hop open + readPackets'
    );
  } finally {
    await client.close();
  }

  expect(
    catchupRequests(await upstream.log(scenario)),
    'a genuinely satisfied request must be visible through the same log-reading path the main test trusts to prove absence'
  ).not.toHaveLength(0);
});

/**
 * Four ways the catch-up preconditions fail closed, and the assertion that
 * gives them meaning: **the provider was never contacted**.
 *
 * `_serve_catchup`'s preconditions (`apps/timeshift/views.py:353-365`) all
 * return before any upstream request, and three distinct causes produce the
 * same `400` body. A downstream row that only checked the status would
 * report "400 Bad Request" for a broken account, a broken channel, a
 * mistyped timestamp or a genuine cascade failure alike. So this row asserts
 * the *empty* provider log as a first-class signal, and each cause
 * separately, before any streaming row in this goal runs.
 *
 * `seedCatchupChannel` imported from `../streaming/helpers`: it is
 * catch-up seeding, not streaming-specific — G8 put it there because its
 * only consumers were there. Importing across the project directory is safe
 * (`testMatch` never collects `helpers.ts`); copying it here is how the two
 * copies drift.
 */
test('every catch-up precondition fails closed without reaching the provider', { tag: '@contract' }, async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const { scenario, channel } = await seedCatchupChannel({ upstream, seed, api, waitFor });
  const token = await api.freshAccessToken();
  const auth = { Authorization: `Bearer ${token}` };
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  // 1. A channel that is not catch-up at all. `get_channel_catchup_streams`
  //    returns [] on `not channel.is_catchup` before it queries anything
  //    (apps/channels/utils.py:141-142).
  const plain = await seed.channel();
  const notCatchup = await request.get(
    `/proxy/catchup/${plain.uuid}?start=${encodeURIComponent(start)}`,
    { headers: auth, maxRedirects: 0 }
  );
  expect(notCatchup.status()).toBe(400);
  expect(await notCatchup.text()).toContain('Timeshift not supported for this channel');

  // 2. An unparseable timestamp. `parse_catchup_timestamp` returns None and
  //    `_serve_catchup` bails at views.py:358-359 — before
  //    `get_channel_catchup_streams`, so this is reachable on a channel that
  //    IS catch-up and is a genuinely different link in the chain.
  const badTs = await request.get(
    `/proxy/catchup/${channel.uuid}?start=not-a-time`,
    { headers: auth, maxRedirects: 0 }
  );
  expect(badTs.status()).toBe(400);
  expect(await badTs.text()).toContain('Invalid timestamp');

  // 3. No `start` at all. Caught one level up, in `catchup_proxy` itself
  //    (views.py:335-336), with a different message — which is the only
  //    reason a caller can tell "you sent nothing" apart from "you sent
  //    rubbish".
  const noTs = await request.get(`/proxy/catchup/${channel.uuid}`, {
    headers: auth,
    maxRedirects: 0,
  });
  expect(noTs.status()).toBe(400);
  expect(await noTs.text()).toContain('Missing start parameter');

  // 4. LAST, because it breaks the account for everything above. Deactivating
  //    the M3U account makes `get_channel_catchup_streams`'s
  //    `m3u_account__is_active=True` filter (apps/channels/utils.py:145)
  //    return [] for a channel whose own `is_catchup` is still True — and
  //    the response is BYTE-IDENTICAL to case 1's. That is the finding, not
  //    an accident: two unrelated misconfigurations are indistinguishable to
  //    a client, and a support report saying "Timeshift not supported for
  //    this channel" identifies neither.
  //
  //    Located by `username`, NOT by name. `seedCatchupChannel` creates the
  //    account internally and does not return it, so it has to be found —
  //    and `seed.xcAccount` generates the account's `name` itself, with no
  //    guarantee it contains the scenario's prefix. What it does put on the
  //    model's own fields is the scenario's credentials
  //    (`seed.xcAccount`'s docstring), and `M3uAccount.username` is typed in
  //    `e2e/fixtures/types.ts`. A name-substring match would pass today and
  //    silently select the wrong account the moment that generator changes.
  const accounts = await api.json<M3uAccount[] | { results: M3uAccount[] }>(
    await api.get('/api/m3u/accounts/'),
    'M3U accounts'
  );
  const rows = Array.isArray(accounts) ? accounts : accounts.results;
  const account = rows.find((a) => a.username === scenario.username);
  expect(account, `the M3U account seedCatchupChannel created for ${scenario.username}`).toBeDefined();
  await api.patch(`/api/m3u/accounts/${account!.id}/`, { is_active: false });

  const deactivated = await request.get(
    `/proxy/catchup/${channel.uuid}?start=${encodeURIComponent(start)}`,
    { headers: auth, maxRedirects: 0 }
  );
  expect(deactivated.status()).toBe(400);
  expect(await deactivated.text()).toContain('Timeshift not supported for this channel');

  // THE POINT OF THE ROW. Every one of the four returned before any provider
  // contact, so a break anywhere in the five-link chain can never reach —
  // or be mistaken for a failure of — the upstream.
  expect(
    catchupRequests(await upstream.log(scenario)),
    'a precondition failure must never reach the provider'
  ).toHaveLength(0);
});
