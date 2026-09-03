import { test, expect, WsListener } from '../../fixtures';
import type { EpgSource } from '../../fixtures';

/**
 * The socket's own event vocabulary, pinned directly — as distinct from two
 * other vocabularies this codebase has that sound like the same thing and are
 * not:
 *
 *  - `core/utils.py:log_system_event` writes a `SystemEvent` row and fans out
 *    to Connect (webhook/script/API). It sends **no** WebSocket message at
 *    all. `apps/connect/models.py:SUPPORTED_EVENTS` is that fixed dict's
 *    vocabulary — the Connect/plugin-hook surface, unrelated to `/ws/`.
 *  - `core/models.py:SystemEvent.EVENT_TYPES` is the *DB* vocabulary for the
 *    rows `log_system_event` writes. It is never asserted here or anywhere in
 *    this suite: `max_system_events` (default 100) truncates that table
 *    instance-wide on every call, so a row this test wrote could be gone by
 *    the time it looked.
 *  - The **socket's** vocabulary — what this file pins — is the set of
 *    `data.type` string literals at `send_websocket_update()` call sites.
 *    There is no registry; each is a bare literal at its own call site, and
 *    the three vocabularies above overlap only by coincidence of naming (a
 *    `channel_stats` WebSocket push and a `SystemEvent` about a channel are
 *    two unrelated things that happen to share a word).
 *
 * `ws-fixture.spec.ts` pins the `ws` *fixture* — `waitForMessage`'s queue and
 * consumption semantics, using `playlist_created` as a convenient real event
 * to drive them. This file pins the *product*: two socket-level facts that
 * nothing else in the suite asserts.
 *
 * ---------------------------------------------------------------------------
 * A wrong premise this file's design started from, and what is true instead
 * ---------------------------------------------------------------------------
 * The obvious way to write test 15 below would lean on ambient, beat-driven
 * `channel_stats` traffic — `e2e/fixtures/ws.ts`'s own doc comment says "a
 * socket on a live instance sees `channel_stats` roughly once a second".
 * That is true of an actively *streaming* channel (`ClientManager` fires it
 * on client connect/disconnect — `apps/proxy/live_proxy/client_manager.py`),
 * but false of this file's idle `seeded`-project instance, and there is no
 * Celery Beat entry driving it either way:
 *
 *   - `dispatcharr/settings.py`'s `CELERY_BEAT_SCHEDULE["fetch-channel-statuses"]`
 *     names `apps.proxy.tasks.fetch_channel_stats` but ships `"enabled": False`
 *     — explicitly, per its own comment ("Explicitly disable the old
 *     fetch-channel-statuses task").
 *   - `core/tasks.py:beat_periodic_task` also calls a `fetch_channel_stats`
 *     copy, but nothing schedules `beat_periodic_task` itself — no
 *     `CELERY_BEAT_SCHEDULE` entry, no `PeriodicTask`-seeding migration. It is
 *     unreachable on a stock instance.
 *
 * Confirmed empirically: a socket connected to this idle instance received
 * zero `channel_stats` frames over a 25s window. The only two things that do
 * emit it are request/event-driven, not periodic: `GET /proxy/ts/status`
 * (`apps/proxy/live_proxy/views.py:channel_status`, the bare collection form
 * with no `channel_id` — `e2e/fixtures/channel-status.ts` already documents
 * this as a reason to avoid that form elsewhere) and a client connecting to
 * an active channel. So test 15 below drives the emission itself, by polling
 * that endpoint, rather than waiting on ambient traffic that does not exist
 * here.
 */

test.describe('epg_data_created', () => {
  let source: EpgSource | undefined;

  test.afterEach(async ({ api }) => {
    if (source) {
      const deleted = await api.delete(`/api/epg/sources/${source.id}/`);
      if (!deleted.ok()) {
        // Non-masking: log rather than throw, so a cleanup failure never
        // hides an already-failing test's real cause (same shape as
        // network-acl.spec.ts's afterEach). Left active, this dummy source's
        // auto-created EPGData row is exactly the generated-shape fuzzy
        // candidate the test-8 gap row in COVERAGE.md blames for its 56.91
        // collision — worth knowing about even when the test itself passed.
        console.error(
          `ws-product-events.spec.ts: DELETE /api/epg/sources/${source.id}/ failed with ` +
            `${deleted.status()} — an active dummy EPG source was left behind`
        );
      }
      source = undefined;
    }
  });

  test('a dummy EPG source create emits epg_data_created, correlated on source_id', { tag: '@contract' }, async ({
    seed,
    ws,
  }) => {
    // `apps/epg/signals.py:trigger_refresh_on_new_epg_source` skips dummy
    // sources entirely, and `create_or_update_refresh_task` skips scheduling
    // for them too — so this POST dispatches no Celery task at all. The event
    // this test waits for comes from a third receiver on the same
    // `post_save`, `create_dummy_epg_data`, which runs in-process and
    // synchronously within the request: by the time the POST below resolves,
    // the event has already been sent.
    //
    // The correlating id (`source.id`) does not exist until the POST returns,
    // so the wait is registered *after* it — not a race, because
    // `WsListener` queues a message that arrives with no waiter interested
    // yet, and the next matching wait consumes it from that queue rather than
    // missing it.
    source = await seed.epgSource({
      source_type: 'dummy',
      refresh_interval: 0,
      is_active: true,
    });

    const message = await ws.waitForMessage('epg_data_created', {
      where: (data) => data.source_id === source!.id,
      timeoutMs: 15_000,
    });

    expect(message.data?.epg_data_id).toBeTruthy();
    expect(message.data?.source_name).toBe(source.name);
  });
});

test('the admin-only filter: an admin socket receives channel_stats, a Streamer socket never does', { tag: '@contract' }, async ({
  ws,
  asPrincipal,
  api,
  baseURL,
}) => {
  // `dispatcharr/consumers.py:ADMIN_ONLY_UPDATE_TYPES` includes
  // `channel_stats` (with `vod_stats`, `timeshift_stats`, `vod_started`,
  // `vod_stopped`) because its payload carries channel/content UUIDs usable
  // against the anonymous `/proxy/ts/stream/<uuid>` surface, upstream URLs
  // and client IPs. `user_may_receive_update` enforces it as a **silent
  // drop**: `consumers.py`'s `update()` handler simply never forwards the
  // message to a socket that fails the check — there is no error frame, no
  // close, nothing observable on that socket at all. "Admin" here means
  // `user_level >= 10` (`user_is_admin`), which a Streamer (`user_level 0`)
  // never satisfies. This is the only coverage that filter has ever had.
  const streamerClient = await asPrincipal('streamer');
  // A second, hand-built listener: the `ws` fixture is always the bootstrap
  // admin, so the Streamer's socket is built directly from its own fresh
  // token rather than through the fixture. `asPrincipal` identities are
  // shared and read-only across the whole run — nothing here mutates one, it
  // only reads a token for it.
  const streamer = new WsListener(baseURL!, await streamerClient.freshAccessToken());
  await streamer.ready();

  try {
    // Drive the emission ourselves — see the file header for why ambient
    // traffic cannot be relied on here. `GET /proxy/ts/status` (bare, no
    // channel id) broadcasts `channel_stats` as a side effect of being
    // polled, every time, regardless of whether any channel is active
    // (confirmed empirically: `{"channels": [], "count": 0}` on this idle
    // instance still triggers the broadcast). The interval and count below
    // are arbitrary spacing for a self-driven signal, not derived from any
    // beat schedule — there isn't one; see the header.
    const POLL_INTERVAL_MS = 1_000;
    const POLL_COUNT = 5;
    // Longer than the full polling span (roughly (POLL_COUNT - 1) *
    // POLL_INTERVAL_MS ≈ 4s), so both waits below are still live for every
    // poll and the negative wait's timeout is the thing that ends the test,
    // not a race against the loop.
    const WINDOW_MS = 8_000;

    // Both waits are registered *before* the polling loop starts, so neither
    // can miss a message that arrives while the loop is still running.
    //
    // The admin wait is bare-type (D12a's last resort, not its default): the
    // `{"channels": [], "count": 0}` payload this idle instance's `GET
    // /proxy/ts/status` broadcasts carries nothing test-owned to correlate
    // on. It is safe here specifically because this wait is only a premise
    // guard, not the assertion under test — a foreign `channel_stats`
    // arriving in this window still proves "the event fired while the
    // Streamer socket was open", which is all the negative below needs, and
    // a foreign message can only strengthen that guard, never weaken it.
    // Nothing else in `seeded` emits `channel_stats`: `channel-status.ts`
    // reads the per-channel form (`GET /proxy/ts/status/<uuid>`), which does
    // not broadcast (`apps/proxy/live_proxy/views.py:24-48`) — only the bare
    // collection form polled below does.
    const adminWait = ws.waitForMessage('channel_stats', { timeoutMs: WINDOW_MS });
    const streamerWait = streamer.waitForMessage('channel_stats', { timeoutMs: WINDOW_MS });
    // If the premise guard below throws (adminWait never resolves),
    // streamerWait is left with no consumer until streamer.close() rejects
    // it in the finally block. Attaching a no-op handler here keeps that
    // rejection from being reported as a second, unrelated failure — the
    // `expect(streamerWait).rejects` below still observes and asserts on the
    // same rejection.
    streamerWait.catch(() => {});

    for (let i = 0; i < POLL_COUNT; i++) {
      await api.get('/proxy/ts/status');
      if (i < POLL_COUNT - 1) {
        await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
      }
    }

    // Premise guard, first: the admin socket must have seen at least one
    // `channel_stats` in the window, or the negative below would be vacuous
    // (nobody could tell "correctly filtered" from "no traffic happened at
    // all"). A bare `waitForMessage` is the only tool `WsListener` offers for
    // "did this arrive" — it has no "read everything the socket saw"
    // counting method (by design: messages are consumed, so counting and
    // waiting on the same queue would race each other) — so the guard is
    // shaped as a wait expected to *resolve*, not a count.
    const adminMessage = await adminWait;
    expect(adminMessage.data?.type).toBe('channel_stats');

    // The filter itself: the same window, the same broadcast group, and the
    // Streamer socket got nothing. For the same reason as above this is a
    // wait expected to *reject with a timeout*, not a count of zero — there
    // is no way to ask "how many arrived" without consuming them, and a
    // timeout is indistinguishable from "definitely never came" only because
    // the premise guard above already proved the event fired at least once
    // in this exact window.
    await expect(streamerWait).rejects.toThrow(/timed out after/);
  } finally {
    streamer.close();
  }
});
