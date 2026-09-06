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
  TS_SYNC_BYTE,
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
 * Whether a viewer reconnecting to the SAME channel is bounded too is an open
 * question this test does not answer. Read on its own, the code says it should
 * be worse: `_channel_setup_needed` (apps/proxy/live_proxy/views.py) returns
 * "no setup needed" for a channel whose metadata still says `active` without
 * consulting the dead owner's heartbeat, so a reconnecting client would attach
 * as a follower to a channel nobody owns until `_check_orphaned_metadata`'s
 * 30s sweep clears it — and that sweep declines to clean a channel that still
 * has a live client. One hand measurement against this stack did not show
 * that: the first probe issued after the blocking restart returned delivered
 * 1880+ aligned TS bytes, inside the sweep interval. So either the mechanism
 * does not bite after a graceful stop (`stopsignal=TERM`, `stopwaitsecs=20`,
 * `die-on-term`, which lets the dying process run its own client-disconnect
 * and channel cleanup — unlike the `kill -9` the reading implicitly assumes),
 * or the sweep ran early on that run. Recorded in `e2e/COVERAGE.md` and filed
 * as an open question, not asserted as a defect; this test tunes a channel
 * that was not running when the relay went away.
 */
const RELAY_RESTART_CEILING_MS = 30_000;

/**
 * How many filler channels the Celery scenario's dedicated M3U catalogue
 * carries, and how many decoy `M3UAccount`s share it.
 *
 * A single account's own refresh cannot be made to outlast the restart by
 * catalogue size alone: the fake provider's `POST /scenarios` caps the
 * request body at 1 MiB (`e2e-upstream/src/server.ts`), which tops out
 * around 10,000 channels, and measured against this container even an
 * 8,000-channel refresh completes in ~2-3s — nowhere near
 * `RELAY_RESTART_CEILING_MS`'s ~7-9s measured restart duration. What
 * reliably takes longer is **queueing behind other work**: Celery's
 * `default` queue autoscales to 6 workers
 * (`docker/supervisord.d/celery-default.conf`), so `SLOW_REFRESH_DECOY_COUNT`
 * accounts against the same 8,000-channel catalogue, refreshed in the same
 * instant as the tracked account, force it to wait through several
 * worker-queue waves.
 * Measured empirically (see the whole-branch fix round in
 * task-4-report.md): 30 decoys pushed the tracked account's completion to
 * ~20s, roughly 2-3x the restart's own duration — margin against reasonable
 * host-to-host variance in worker throughput, not a number tuned to just
 * clear it.
 */
const SLOW_REFRESH_CHANNEL_COUNT = 8_000;
const SLOW_REFRESH_DECOY_COUNT = 30;

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
 * How many packets each of the two drained reads below (a) and (d) must
 * pump — sized against a measured system ceiling, not either read's own
 * idle window, so one number correctly defeats the reservoir for both.
 *
 * `drain()` only empties `StreamClient`'s own `chunks` array; undici's
 * `ReadableStream` queue and the kernel socket receive buffer sit below it,
 * and `pump()`'s `reader.read()` hands back whatever already arrived there
 * regardless of what `drain()` just cleared — proven in the review of fix
 * round 1: at 20 packets, all three ways a dead relay connection can look (a
 * sender that stops writing, a clean FIN, an RST) passed in 1ms flat against
 * a local server reproducing this test's sequence (`readPackets(200)`, a
 * 1.5s idle window, a teardown, `drain()`, then a timed read).
 *
 * The evidence that this size defeats every reservoir in the path is the
 * counterfactual table above (fix round 1's review), not a sysctl reading:
 * at 20 packets, all three ways a dead relay connection can look (a sender
 * that stops writing, a clean FIN, an RST) passed in 1ms flat; at this
 * constant's size the stall case instead fails at the 60s deadline, FIN and
 * RST still fail fast (10ms, 4ms), and a live stream still passes (1,292ms).
 *
 * `net.ipv4.tcp_rmem`'s third value — `docker exec … cat
 * /proc/sys/net/ipv4/tcp_rmem` → `4096 131072 33554432` bytes, 32 MiB — is
 * cited below only as an order-of-magnitude sanity check, not as the bound
 * this constant is sized against: it is the *container's* autotuned
 * receive-buffer ceiling, the wrong side of the connection from where stale
 * bytes actually accumulate. The reservoirs that matter are client-side —
 * the Playwright process's own host kernel receive buffer and undici's
 * `ReadableStream` queue — plus the container's `tcp_wmem` send buffer, and
 * none of those three was measured directly.
 *
 * 360,000 packets is 67,680,000 bytes, 64.55 MiB — roughly double the sysctl
 * figure above, for scale — needing ~12.8s of live production at this
 * scenario's ~5.3MB/s to satisfy, comfortably inside the existing 60s
 * `withDeadline`.
 *
 * Sized against the ceiling rather than against either read's idle window on
 * purpose, because a smaller, idle-window-calibrated size was tried first and
 * failed the wrong way: `api-uwsgi` carries `stopsignal=TERM` and
 * `stopwaitsecs=10` (`docker/supervisord.d/api-uwsgi.conf`), so
 * `instance.supervisorctl(['stop', 'api-uwsgi'])` alone can block for
 * seconds, and the 502 poll that follows has its own 30s budget — ~1.6s of
 * that combined window is already enough to put more than 8.46 MiB (a
 * 45,000-packet read, this constant's previous, idle-window-calibrated size)
 * into the receive buffers, making assertion (a) vacuous again on a slow
 * `stop` rather than a long poll. (d)'s window is longer still (two more
 * 60s-budget polls). One size, grounded in the one number that actually
 * bounds the reservoir regardless of how long either window runs, covers
 * both.
 */
const RESERVOIR_READ_PACKETS = 360_000;

/**
 * Full TS-alignment scan for the two large reads above, without
 * `expectTsAligned`'s per-packet `expect()` cost.
 *
 * The 8.7s a bare Node script measured for 360,000 packets through
 * `expectTsAligned` — long enough that a real run against this project's
 * container needed to be killed rather than waited out, under Playwright's
 * own per-assertion tracing overhead on top — is the cost of calling
 * `expect()` once per packet, not the cost of scanning: a raw sync-byte scan
 * over the same 360,000 packets in plain Node takes ~2ms. This scans every
 * packet with plain comparisons and asserts once, so the check stays
 * complete rather than sampled — sampling would give up exactly the coverage
 * that would catch this codebase's known chunk-splicing defect (the
 * un-fenced ownership lease lets two owners interleave chunks at alternating
 * indices; CLAUDE.md § Known defects records that readers decode the splice
 * with every other check passing), which would show up in the middle of a
 * long read, not at its edges.
 */
function expectTsAlignedFast(buffer: Buffer): void {
  expect(
    buffer.byteLength % TS_PACKET_SIZE,
    `buffer of ${buffer.byteLength} bytes is not a whole number of 188-byte packets`
  ).toBe(0);

  let badOffset = -1;
  for (let offset = 0; offset < buffer.byteLength; offset += TS_PACKET_SIZE) {
    if (buffer[offset] !== TS_SYNC_BYTE) {
      badOffset = offset;
      break;
    }
  }
  expect(
    badOffset,
    badOffset === -1
      ? `all ${buffer.byteLength / TS_PACKET_SIZE} packets aligned`
      : `expected sync byte 0x47 at offset ${badOffset}, got 0x${buffer[badOffset].toString(16)}`
  ).toBe(-1);
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
    // Asserted, not fired and forgotten: `supervisorctl()` returns the exit
    // code rather than throwing, so a `start` that failed here would
    // otherwise leave the hook green and the next test would fail elsewhere,
    // naming a symptom instead of this cause.
    const started = await instance.supervisorctl(['start', 'api-uwsgi']);
    expect(
      started.code,
      `afterEach could not restart api-uwsgi (exit ${started.code}): ` +
        `${started.stdout}${started.stderr}`
    ).toBe(0);
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
      // Drained first, but drain() only empties StreamClient's own `chunks`
      // array — it does NOT reach undici's ReadableStream queue or the
      // kernel receive buffer underneath, both of which can already be
      // holding pre-outage bytes by the time this runs. That is why the read
      // below asks for RESERVOIR_READ_PACKETS rather than a handful: see that
      // constant for the measurement proving a small read passes even when
      // the stream is dead, and this one does not. `readPackets` itself is
      // still the assertion that matters — it throws if the stream ends, and
      // only returns once it pumped enough live bytes to satisfy the count —
      // a bare byte-length check afterwards would be a tautology.
      streamClient.drain();
      expect(
        streamClient.bufferedByteCount,
        "drain() should leave at most a partial trailing packet in the client's own buffer"
      ).toBeLessThan(TS_PACKET_SIZE);
      const during = await withDeadline(
        streamClient.readPackets(RESERVOIR_READ_PACKETS),
        60_000,
        'the already-open stream during the API outage'
      );
      expectTsAlignedFast(during);

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
    // 200, not 1: the same reason as the two preconditions above — a channel
    // that answers with one synthetic 'error' or 'keepalive' packet and then
    // dies would otherwise pass "a new tune succeeds again" on 188 bytes that
    // prove nothing.
    expectTsAligned(await withDeadline(resumed.readPackets(200), 30_000, 'the resumed tune'));
    await resumed.close();

    // (d) D15, the observable form: restarting the control plane left the
    // relay's channel state in Redis alone. If any start path still flushed
    // DB 0, this channel's metadata, chunks and client set would have gone
    // with it and these packets would never arrive.
    //
    // Drained first, same reasoning and same size as (a) — RESERVOIR_READ_PACKETS
    // is sized against this container's measured 32 MiB receive-buffer
    // ceiling, not against either read's own idle window, and (d)'s window
    // (the `expectRunning` poll plus the readiness-route poll above, up to
    // 60s each) is if anything longer than (a)'s.
    //
    // A FAST read here is the expected healthy shape, not a warning sign: by
    // now the relay has a backlog of this channel's chunks sitting in its
    // Redis ring buffer, and once the client reads again they come back at
    // memory speed. That is the D15 proof, not something defeating it — if a
    // start path had flushed Redis DB 0, those chunks would not exist to be
    // served, fast or slow. What actually excludes the receive-side
    // reservoir is the volume: RESERVOIR_READ_PACKETS reads roughly double
    // this container's measured kernel-buffer ceiling, so satisfying it means
    // at least half of it came from somewhere past the client's socket
    // buffers — the relay's own ring buffer, fed by the still-running
    // channel — regardless of how fast the read returns.
    streamClient.drain();
    expect(
      streamClient.bufferedByteCount,
      "drain() should leave at most a partial trailing packet in the client's own buffer"
    ).toBeLessThan(TS_PACKET_SIZE);
    const after = await withDeadline(
      streamClient.readPackets(RESERVOIR_READ_PACKETS),
      60_000,
      'the already-open stream after the API process came back'
    );
    expectTsAlignedFast(after);
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
    // The Celery half needs a refresh that is provably still running the
    // instant the blocking restart returns — a two-channel catalogue's
    // refresh finished inside that ~7s window in measurement, which made the
    // in-flight assertion below fail (correctly: the task had already
    // completed, so nothing about surviving the restart was under test).
    // `SLOW_REFRESH_CHANNEL_COUNT`/`SLOW_REFRESH_DECOY_COUNT`'s own comment
    // has the reasoning and the measurements; the streaming scenario above
    // stays small on purpose since scenario size has no bearing on tune
    // latency.
    const slowScenario = await upstream.scenario({
      channels: Array.from({ length: SLOW_REFRESH_CHANNEL_COUNT }, (_, i) => ({
        id: i + 1,
        name: `slow-refresh-filler-${i + 1}`,
        tvgId: `slow-refresh-filler-${i + 1}.e2e`,
        logo: null,
      })),
    });
    // Settled — not just created — before the tracked account exists: an
    // unsettled decoy's own create-time refresh would already be consuming
    // worker slots that the tracked account's create-time settle
    // (`waitForCreateTimeGroupRefreshToSettle`, capped at 20s) also needs,
    // risking a false failure in setup rather than in the assertion this
    // test is actually about. `Promise.all`, not a loop: each call already
    // waits out its own settle, so awaiting them one at a time would
    // multiply that wait by `SLOW_REFRESH_DECOY_COUNT` instead of letting
    // Celery's workers absorb them together.
    const decoys = await Promise.all(
      Array.from({ length: SLOW_REFRESH_DECOY_COUNT }, () =>
        seed.upstreamM3UAccount(slowScenario)
      )
    );
    // An M3U account is the Celery half: refreshing one is a real queued task
    // whose completion is visible over REST. Seeded (and refreshed) before
    // anything else so the create-time group refresh has settled and the
    // account's task lock is free by the time the test triggers its own.
    const account = await seed.upstreamM3UAccount(slowScenario);
    const { channel: running } = await seed.upstreamChannel(scenario, {
      channelIds: [1],
      streamProfileId: proxy.id,
    });
    const { channel: after } = await seed.upstreamChannel(scenario, {
      channelIds: [2],
      streamProfileId: proxy.id,
    });

    await streamClient.open(`/proxy/ts/stream/${running.uuid}`);
    // 200, not 1: matches Scenario A's precondition idiom. The TS generator
    // emits a synthetic 'error' packet and a keepalive while a channel is
    // still coming up (apps/proxy/live_proxy/output/ts/generator.py:200-241,380),
    // and `expectTsAligned` only checks 188-byte alignment and the sync byte,
    // so either one passes it.
    expectTsAligned(await streamClient.readPackets(200));
    // Printed for the hand-run same-channel reconnect measurement recorded in
    // `e2e/COVERAGE.md`, which needs a channel this project left streaming
    // and has no other way to learn its uuid.
    console.log(`[relay-restart] channel ${running.uuid} is streaming before the restart`);

    const before = await api.json<M3uAccount>(
      await api.get(`/api/m3u/accounts/${account.id}/`),
      `M3U account ${account.id} before the relay restart`
    );

    // Discriminates "the task ran" from "the row was already successful":
    // `updated_at` is bumped only by a successful refresh (apps/m3u/tasks.py),
    // so a status/timestamp pair unchanged from `before` means this specific
    // trigger has not yet completed, however many refreshes came before it.
    async function refreshState(): Promise<string> {
      const body = await api.json<M3uAccount>(
        await api.get(`/api/m3u/accounts/${account.id}/`),
        `M3U account ${account.id} refresh state`
      );
      return `${body.status}:${body.updated_at === before.updated_at ? 'unchanged' : 'bumped'}`;
    }

    // Every decoy and the tracked account fire in the SAME `Promise.all`,
    // tracked account last: submitted together, Celery's workers pull
    // roughly in submission order, so the tracked refresh queues behind
    // whichever decoys land on a worker first rather than racing them for
    // the very first slot. This is the exact shape measured in the
    // calibration this constant's comment cites — firing the tracked
    // account from a separate, later call would not reproduce it.
    const triggerResponses = await Promise.all([
      ...decoys.map((d) => api.post(`/api/m3u/refresh/${d.id}/`, {})),
      api.post(`/api/m3u/refresh/${account.id}/`, {}),
    ]);
    const triggered = triggerResponses[triggerResponses.length - 1];
    expect(
      triggerResponses.every((res) => res.status() === 202),
      'every refresh — decoys and the tracked account alike — must be queued, or the tracked ' +
        'refresh is not actually contending for a worker slot'
    ).toBe(true);

    const restartBegan = Date.now();
    await instance.supervisorctl(['restart', 'relay-uwsgi']);
    console.log(
      `[relay-restart] supervisorctl restart returned after ${Date.now() - restartBegan}ms`
    );

    // In-flight proof, taken the instant the blocking restart call returns:
    // without this, the poll below can pass even if the task completed
    // during the restart itself rather than surviving it — `wait-for-stores.sh`
    // runs `wait_for_redis.py` on relay-uwsgi's own start, the only place a
    // reintroduced flush could bite, and a refresh that finished before that
    // point would never exercise it. If this fires reliably, the fix is
    // more contention — raise `SLOW_REFRESH_DECOY_COUNT`, not loosen this
    // assertion, since the spec asks for a task that survives the relay's
    // start path, not one that merely predates it.
    const midRestart = await refreshState();
    expect(
      midRestart,
      `the refresh had already reached '${midRestart}' by the moment the restart returned, so ` +
        'the poll below would prove nothing about surviving the relay start path'
    ).not.toBe('success:bumped');

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
    // 200, not 1: create_ts_packet (apps/proxy/live_proxy/utils.py:82-100)
    // returns a valid-looking 188-byte packet for a synthetic 'error' or
    // 'keepalive' TS packet too, which the generator emits on every abort
    // path while a channel is coming up — so a single packet cannot tell a
    // real tune apart from one that failed to start. `client` is opened for
    // the first time above, not reused across the restart the way Scenario
    // A's `streamClient` is, so there is nothing stale in its buffer to
    // `drain()` first — every byte it ever reads arrived after the restart
    // by construction. `readPackets` itself is the load-bearing assertion:
    // it throws if the stream ends before 200 packets arrive, so a channel
    // that never truly starts fails loudly instead of passing on one
    // synthetic packet. The extra bytes cost well under a second at this
    // scenario's rate against a 30s ceiling.
    const packet = await withDeadline(
      client.readPackets(200),
      60_000,
      'the first 200 TS packets after the relay restart'
    );
    const elapsedMs = Date.now() - restartBegan;
    console.log(
      `[relay-restart] first TS bytes ${elapsedMs}ms after the restart began ` +
        `(ceiling ${RELAY_RESTART_CEILING_MS}ms)`
    );
    expectTsAligned(packet);
    expect(
      elapsedMs,
      `the relay served its first bytes ${elapsedMs}ms after the restart began; the ceiling is ` +
        `${RELAY_RESTART_CEILING_MS}ms (stopwaitsecs=20 + startsecs=5)`
    ).toBeLessThanOrEqual(RELAY_RESTART_CEILING_MS);
    await client.close();

    // D15's Celery half: the task dispatched a moment before the restart —
    // and confirmed still in flight the instant the restart returned, above —
    // still ran to completion afterwards. A blind flush on any start path
    // would take the broker and the result backend with it — they share
    // Redis DB 0 with the relay's channel state.
    await expect
      .poll(refreshState, {
        timeout: 120_000,
        intervals: [2_000],
        message:
          'the refresh queued before the restart never completed. If it sits at the ' +
          'pre-trigger status forever, the create-time task lock was still held when it ' +
          'was triggered (D10Scot/Dispatcharr#59) rather than the restart having eaten it',
      })
      .toBe('success:bumped');
  }
);
