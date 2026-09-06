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
    await client.open(path);
    return 'ok';
  } catch (error) {
    if (error instanceof StreamStatusError) return `HTTP ${error.status}`;
    return String(error);
  }
}

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
    expectTsAligned(await streamClient.readPackets(1));

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
      const during = await withDeadline(
        streamClient.readPackets(20),
        60_000,
        'the already-open stream during the API outage'
      );
      expect(during.byteLength).toBe(20 * TS_PACKET_SIZE);
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
    const after = await withDeadline(
      streamClient.readPackets(20),
      60_000,
      'the already-open stream after the API process came back'
    );
    expect(after.byteLength).toBe(20 * TS_PACKET_SIZE);
    expectTsAligned(after);
    await streamClient.close();
  }
);
