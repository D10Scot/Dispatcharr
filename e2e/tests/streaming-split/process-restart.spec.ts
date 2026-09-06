/**
 * The two uWSGI processes restart independently (Phase 1 PR 8).
 *
 * COVERAGE: Streaming — Django down; Lifecycle — bounded relay restart (P1).
 *
 * Runs alone in its own project. Each test takes one supervisord program away
 * for part of its run; `e2e/fixtures/instance.ts`'s header and
 * `playwright.config.ts`'s project comment say why that needs a container of
 * its own rather than a single worker inside an existing project.
 *
 * ---------------------------------------------------------------------------
 * WHY @contract, ON AN ALLOWLISTED CAPABILITY
 * ---------------------------------------------------------------------------
 * ADR-0002 says anything on `tests/guards/allowlist.ts` is
 * `@characterization` by construction, because those calls stop meaning
 * anything once the relay is its own process. This file is the second
 * exception, and it is the opposite case: the relay IS its own process here,
 * and the promise under test — an established stream is not disturbed by the
 * control plane going away, and a relay restart is bounded — is exactly what
 * a Go relay in Phase 2 must also keep. `supervisorctl` is the vocabulary,
 * not the subject. `tests/streaming-greybox/nginx-stream-buffering.spec.ts`
 * carries the same argument for `SUBPROCESS`; `e2e/README.md` records both.
 *
 * ---------------------------------------------------------------------------
 * WHAT AN OPERATOR SEES WHILE DJANGO IS DOWN, AND WHY THE NEW TUNE IS A 500
 * ---------------------------------------------------------------------------
 * Since Phase 1 PR 5, PR 6 and PR 7 the control plane is on more paths than
 * the authorize hop, and all of them fail together:
 *
 *  - a new tune  — nginx's `auth_request` subrequest to `api-uwsgi` cannot be
 *    served. `ngx_http_auth_request_module` allows 2xx, passes 401 and 403
 *    through, and maps everything else to its own 500 — so the client sees
 *    500, not the 502/504 a failed `uwsgi_pass` gives. That is why the probe
 *    below asserts 502 on an ordinary `/api/` route and 500 on a tune in the
 *    same outage: two different failure sites, two different codes.
 *  - a failover on a channel already running — `next_source()` and
 *    `release_source()` are the two synchronous control-plane calls, each
 *    (2 s connect + 5 s read) with one retry and a 0.1 s delay, so each can
 *    hold the channel's main-loop greenlet for ~14 s (spec Amendment S10,
 *    point 8). The failover then falls back to the candidate list cached at
 *    channel start — stale and unenforced — and posts a `channel_error` with
 *    reason `degraded_failover` once Django answers again.
 *  - every `relay_client` call from the control plane — but those originate
 *    in the process that is down, so they simply do not happen. Their budgets
 *    matter in the other direction (a relay outage): (1, 2) on the tune path,
 *    (2, 5) for admin reads and stops, (2, 20) for `advance`, no retries.
 *  - events — `emit_event` is fire-and-forget on a greenlet, so a transition
 *    during the outage is lost, logged once at the start and once on recovery
 *    ("Relay events reachable again after an outage"). Nothing on the byte
 *    path waits for it.
 *
 * This file asserts the first of those four; the other three are covered by
 * unit tests PR 6 shipped (`apps/proxy/live_proxy/tests/test_try_next_stream.py`)
 * and are described here so the numbers live beside the scenario that
 * motivates them.
 */
import {
  test,
  expect,
  StreamStatusError,
  TS_PACKET_SIZE,
  expectTsAligned,
} from '../../fixtures';
import type { Instance, M3uAccount } from '../../fixtures';
import { lockedProfile, newStreamClient, withDeadline } from '../streaming/helpers';

/**
 * nginx's own readiness route (`scripts/e2e_up.sh` polls it), `AllowAny`, and
 * served by the API process through `location ^~ /api/`. Once `bootstrap` has
 * run it answers 200; with `api-uwsgi` stopped, `uwsgi_pass` to the unix
 * socket fails and nginx answers 502.
 */
const API_PROBE = '/api/accounts/initialize-superuser/';

/** supervisord reports RUNNING once a program has stayed alive `startsecs=5`. */
const RUNNING_TIMEOUT_MS = 60_000;

/**
 * The spec's ceiling for a bounded relay restart, and its own justification:
 * "`stopwaitsecs=20` plus process start has to fit inside it or the restart is
 * not bounded in any useful sense". `docker/supervisord.d/relay-uwsgi.conf`
 * carries `stopwaitsecs=20` and `startsecs=5`, so 25s is the configured worst
 * case and 30s is the budget it has to fit inside. Measured from the moment
 * the restart command is issued, not from when it returns.
 *
 * What this ceiling covers is the *process*: the relay serving tunes again.
 * A viewer reconnecting to the SAME channel is a different question with a
 * worse answer — `_channel_setup_needed` (apps/proxy/live_proxy/views.py)
 * returns "no setup needed" for a channel whose metadata still says `active`
 * without consulting the dead owner's heartbeat, so the reconnecting client
 * attaches as a follower to a channel nobody owns, and only
 * `_check_orphaned_metadata`'s 30s sweep can clear it — and that sweep
 * declines to clean a channel that still has a live client, which a retrying
 * reconnect keeps supplying. Recorded in `e2e/COVERAGE.md` and filed rather
 * than asserted here; this test tunes a channel that was not running when the
 * relay went away.
 */
const RELAY_RESTART_CEILING_MS = 30_000;

async function expectRunning(
  instance: Instance,
  program: string,
  message: string
): Promise<void> {
  // Polled, not asserted once: both uWSGI programs run through
  // `wait-for-stores.sh`, so supervisord can report RUNNING before the store
  // waits finish — the same reasoning `tests/lifecycle/restart-persistence.spec.ts`
  // records at its own status polls.
  await expect
    .poll(async () => (await instance.supervisorctl(['status', program])).stdout, {
      timeout: RUNNING_TIMEOUT_MS,
      intervals: [1_000],
      message,
    })
    .toMatch(/RUNNING/);
}

/**
 * Bounds the `open()` call inside `openOutcome`. `expect.poll`'s own timeout
 * does not cancel an in-flight callback — it only stops scheduling a *next*
 * one — so an `open()` that never settles would otherwise run to the
 * project's 600s test timeout instead of to either poll's stated budget, and
 * would leave `api-uwsgi` stopped for whatever test the project runs next
 * (see the `afterEach` below).
 */
const OPEN_OUTCOME_DEADLINE_MS = 30_000;

/**
 * Open a stream and report the outcome as a string.
 *
 * Nothing is rethrown. `expect.poll` fails the test on the first throw from
 * its callback rather than retrying, so a transient connection reset while
 * uWSGI finishes recycling would end the test outright instead of being
 * retried like the status beside it. Every outcome becomes a string, the
 * budget covers all of them, and the failure message prints the last one —
 * `expect.poll`'s own `message` is typed `string`, not a callback, so the
 * reason has to travel in the polled value.
 */
async function openOutcome(
  client: ReturnType<typeof newStreamClient>,
  path: string
): Promise<string> {
  try {
    await withDeadline(client.open(path), OPEN_OUTCOME_DEADLINE_MS, `opening ${path}`);
    return 'ok';
  } catch (error) {
    if (error instanceof StreamStatusError) return `HTTP ${error.status}`;
    return String(error);
  }
}

/**
 * Backstop, not the primary cleanup — the primary is the `try`/`finally`
 * inside the first test below. A Playwright timeout abandons a test body
 * without running its `finally` (only `afterEach` hooks still run), so
 * without this an abandoned run would leave `api-uwsgi` stopped for the rest
 * of the project and the second test would fail naming something unrelated.
 * Checks the actual status rather than trusting a variable the abandoned body
 * never got to set, and is a no-op — one cheap `supervisorctl status` call —
 * for the second test, which never touches `api-uwsgi`.
 */
test.afterEach(async ({ instance }) => {
  const status = await instance.supervisorctl(['status', 'api-uwsgi']);
  if (!/RUNNING/.test(status.stdout)) {
    await instance.supervisorctl(['start', 'api-uwsgi']);
  }
});

test(
  'a running stream outlives the API process, and a new tune answers 500 until it is back',
  { tag: '@contract' },
  async ({ instance, api, seed, upstream, streamClient, request, baseURL }) => {
    // Everything is seeded before the API goes away: with `api-uwsgi` stopped
    // there is no REST surface at all, so a test that seeded lazily would fail
    // on its own setup and report it as the product's failure.
    await expectRunning(instance, 'api-uwsgi', 'api-uwsgi was not RUNNING before this test began');
    await expectRunning(instance, 'relay-uwsgi', 'relay-uwsgi was not RUNNING before this test began');

    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name: 'split running', tvgId: 'split-running.e2e', logo: null },
        { id: 2, name: 'split new tune', tvgId: 'split-new-tune.e2e', logo: null },
      ],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    const { channel: running } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    // A second channel, never tuned, so the blocked request below is a genuine
    // new tune rather than a second client on a channel the relay already
    // serves. nginx runs `auth_request` either way; using a fresh channel
    // removes the objection that it might not have.
    const { channel: fresh } = await seed.upstreamChannel(scenario, {
      channelIds: [2],
      streamProfileId: proxy.id,
    });

    await streamClient.open(`/proxy/ts/stream/${running.uuid}`);
    // 200, not 1: the TS generator emits a synthetic 'error' packet and a
    // keepalive while a channel is still coming up
    // (apps/proxy/live_proxy/output/ts/generator.py:200-241,380), and
    // `expectTsAligned` only checks 188-byte alignment and the sync byte, so
    // either one passes it. Matches the failover project's own precondition
    // idiom (`tests/streaming-failover/mid-stream-switch.spec.ts:24`).
    expectTsAligned(await streamClient.readPackets(200));

    let stopped = false;
    try {
      await instance.supervisorctl(['stop', 'api-uwsgi']);
      stopped = true;

      // Control assertion, first: a test that never actually stopped anything
      // passes everything below it. 502, not 500 — `uwsgi_pass` failing
      // directly on an `/api/` location, which is the distinction the tune
      // assertion completes.
      await expect
        .poll(async () => (await request.get(API_PROBE)).status(), {
          timeout: 30_000,
          intervals: [500],
          message: 'the API process was stopped but nginx still answered its readiness route',
        })
        .toBe(502);

      // (a) The established stream is undisturbed. Nothing on the byte path
      // calls Django once a stream runs.
      //
      // Drained first: readPackets() pumps the underlying reader in whatever
      // chunk size fetch delivers, which can be far larger than what was
      // asked for, so bytes already sitting in the client's buffer from the
      // precondition read above could satisfy the read below with nothing
      // new crossing the wire — a run in which stopping api-uwsgi killed the
      // established stream outright would still pass it. Draining means the
      // read can only succeed by pumping fresh bytes from the still-open
      // relay connection while the outage is in progress. `readPackets`
      // itself is the assertion that matters here: it throws if the stream
      // ends, and only returns once it pumped enough live bytes to satisfy
      // the count — a bare byte-length check afterwards would be a
      // tautology.
      streamClient.drain();
      const during = await withDeadline(
        streamClient.readPackets(20),
        60_000,
        'the already-open stream during the API outage'
      );
      expectTsAligned(during);

      // (b) A new tune is refused, and the refusal is nginx's own 500.
      const blocked = newStreamClient(baseURL!);
      const outcome = await openOutcome(blocked, `/proxy/ts/stream/${fresh.uuid}`);
      await blocked.close();
      expect(
        outcome,
        'with api-uwsgi stopped, the auth_request subrequest fails and nginx reports its own ' +
          'error: 500, not the 502/504 a direct uwsgi_pass failure gives (spec Amendment S7)'
      ).toBe('HTTP 500');
    } finally {
      if (stopped) await instance.supervisorctl(['start', 'api-uwsgi']);
    }

    await expectRunning(instance, 'api-uwsgi', 'api-uwsgi did not return to RUNNING');
    await expect
      .poll(async () => (await request.get(API_PROBE)).status(), {
        timeout: RUNNING_TIMEOUT_MS,
        intervals: [1_000],
        message: 'the API process came back but never served its readiness route',
      })
      .toBe(200);

    // (c) A new tune succeeds again.
    const resumed = newStreamClient(baseURL!);
    await expect
      .poll(async () => openOutcome(resumed, `/proxy/ts/stream/${fresh.uuid}`), {
        timeout: RUNNING_TIMEOUT_MS,
        intervals: [2_000],
        message: 'no tune succeeded after api-uwsgi came back',
      })
      .toBe('ok');
    expectTsAligned(await withDeadline(resumed.readPackets(1), 30_000, 'the resumed tune'));
    await resumed.close();

    // (d) D15, the observable form: restarting the control plane left the
    // relay's channel state in Redis alone. If any start path still flushed
    // DB 0, this channel's metadata, chunks and client set would have gone
    // with it and these packets would never arrive.
    //
    // Drained first, and more load-bearing here than at (a): the client has
    // been idle across the `expectRunning` poll and the readiness-route poll
    // above (up to 60s each), so its buffer is certainly holding leftovers by
    // now. Without draining, this read proves nothing a flushed Redis DB 0
    // would have disturbed — it would just hand back bytes that arrived
    // before the restart.
    streamClient.drain();
    const after = await withDeadline(
      streamClient.readPackets(20),
      60_000,
      'the already-open stream after the API process came back'
    );
    expectTsAligned(after);
    await streamClient.close();
  }
);

test(
  'a relay restart is bounded, and leaves a Celery task queued across it to finish',
  { tag: '@contract' },
  async ({ instance, api, seed, upstream, streamClient, baseURL }) => {
    await expectRunning(instance, 'api-uwsgi', 'api-uwsgi was not RUNNING before this test began');
    await expectRunning(instance, 'relay-uwsgi', 'relay-uwsgi was not RUNNING before this test began');

    const scenario = await upstream.scenario({
      channels: [
        { id: 1, name: 'split relay running', tvgId: 'split-relay-running.e2e', logo: null },
        { id: 2, name: 'split relay after', tvgId: 'split-relay-after.e2e', logo: null },
      ],
      rate: 20,
    });
    const proxy = await lockedProfile(api, 'Proxy');
    // An M3U account is the Celery half: refreshing one is a real queued task
    // whose completion is visible over REST. Seeded (and refreshed) before
    // anything else so the create-time group refresh has settled and the
    // account's task lock is free by the time the test triggers its own.
    const account = await seed.upstreamM3UAccount(scenario);
    const { channel: running } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    const { channel: after } = await seed.upstreamChannel(scenario, {
      channelIds: [2],
      streamProfileId: proxy.id,
    });

    await streamClient.open(`/proxy/ts/stream/${running.uuid}`);
    expectTsAligned(await streamClient.readPackets(1));
    // Printed for Task 11's hand-run same-channel reconnect measurement, which
    // needs a channel this project left streaming and has no other way to
    // learn its uuid.
    console.log(`[relay-restart] channel ${running.uuid} is streaming before the restart`);

    const before = await api.json<M3uAccount>(
      await api.get(`/api/m3u/accounts/${account.id}/`),
      `M3U account ${account.id} before the relay restart`
    );

    const triggered = await api.post(`/api/m3u/refresh/${account.id}/`, {});
    expect(
      triggered.status(),
      'the refresh must be queued before the restart, or there is nothing to survive it'
    ).toBe(202);

    const restartBegan = Date.now();
    await instance.supervisorctl(['restart', 'relay-uwsgi']);
    console.log(
      `[relay-restart] supervisorctl restart returned after ${Date.now() - restartBegan}ms`
    );

    // The running stream died with the process it was served by. Closing the
    // client here is bookkeeping, not an assertion: nothing processed its
    // disconnect, so its entry stays in the channel's client set until the
    // relay's own ghost-client sweep removes it.
    await streamClient.close();

    await expectRunning(instance, 'relay-uwsgi', 'relay-uwsgi did not return to RUNNING');

    // The bounded half: a tune the relay has never served answers with real,
    // aligned TS bytes inside the ceiling.
    const client = newStreamClient(baseURL!);
    await expect
      .poll(async () => openOutcome(client, `/proxy/ts/stream/${after.uuid}`), {
        // Deliberately above the ceiling. The assertion below is on the
        // measured number, so an over-budget restart fails with the number it
        // took rather than with a bare poll timeout — the shape
        // `tests/streaming/time-to-first-byte.spec.ts` uses.
        timeout: 120_000,
        intervals: [1_000],
        message: 'the relay never served a tune after the restart',
      })
      .toBe('ok');
    const packet = await withDeadline(
      client.readPackets(1),
      60_000,
      'the first TS packet after the relay restart'
    );
    const elapsedMs = Date.now() - restartBegan;
    console.log(
      `[relay-restart] first TS byte ${elapsedMs}ms after the restart began ` +
        `(ceiling ${RELAY_RESTART_CEILING_MS}ms)`
    );
    expect(packet.byteLength).toBe(TS_PACKET_SIZE);
    expectTsAligned(packet);
    expect(
      elapsedMs,
      `the relay served its first byte ${elapsedMs}ms after the restart began; the ceiling is ` +
        `${RELAY_RESTART_CEILING_MS}ms (stopwaitsecs=20 + startsecs=5)`
    ).toBeLessThanOrEqual(RELAY_RESTART_CEILING_MS);
    await client.close();

    // D15's Celery half: the task dispatched a moment before the restart still
    // ran to completion. A blind flush on any start path would take the broker
    // and the result backend with it — they share Redis DB 0 with the relay's
    // channel state. `updated_at` is bumped only by a successful refresh, so
    // it discriminates "the task ran" from "the row was already successful".
    await expect
      .poll(
        async () => {
          const body = await api.json<M3uAccount>(
            await api.get(`/api/m3u/accounts/${account.id}/`),
            `M3U account ${account.id} after the relay restart`
          );
          return `${body.status}:${body.updated_at === before.updated_at ? 'unchanged' : 'bumped'}`;
        },
        {
          timeout: 120_000,
          intervals: [2_000],
          message:
            'the refresh queued before the restart never completed. If it sits at the ' +
            'pre-trigger status forever, the create-time task lock was still held when it ' +
            'was triggered (D10Scot/Dispatcharr#59) rather than the restart having eaten it',
        }
      )
      .toBe('success:bumped');
  }
);
