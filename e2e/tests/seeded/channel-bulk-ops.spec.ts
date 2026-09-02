import { test, expect } from '../../fixtures';
import type { ApiClient, Channel } from '../../fixtures';

/**
 * `ChannelViewSet`'s bulk-mutation surface: `edit/bulk`, `bulk-delete`,
 * `assign` and `reorder` (`apps/channels/api_views.py`).
 *
 * **D9.** `ChannelViewSet.reorder` (`:2315-2378`) shifts every `Channel` on
 * the instance whose number falls between the old and desired positions,
 * with no account, group or profile filter — and `insert_after_id: null`
 * sets the desired position to 1, making the shift range `[1, old_number)`,
 * which on this instance is every channel any test has ever created.
 * **`null` is never sent** by any test in this file; test 23 always passes a
 * real `insert_after_id` and stays inside its own three-channel band, which
 * is what makes the shift both observable and safe to provoke.
 *
 * **D18.** [#72](https://github.com/D10Scot/Dispatcharr/issues/72) is
 * deliberately not reproduced. This file creates channels and profiles but
 * never concurrently, because provoking that race leaves a
 * partially-populated membership set on a shared instance, and a
 * reproduction that fails to fire is a green test proving nothing.
 *
 * ---------------------------------------------------------------------------
 * The worker band
 * ---------------------------------------------------------------------------
 * `syncWindowFor` in `./helpers.ts` (G3's `D3`) is the precedent for this
 * scheme, but its two slots are already spent: `auto-channel-sync.spec.ts`
 * (G3) uses **both** `slot: 0` and `slot: 1` for its own two tests, so the
 * whole `9000 + workerIndex * 200 .. +199` span (`workers: 4` on the
 * `seeded` project, so `workerIndex` 0-3) is already claimed end to end —
 * `9000` through `9799`. `syncWindowFor` itself guards against a third slot
 * for exactly this reason (its doc comment: a `slot: 2` would start inside
 * the *next* worker's `slot: 0` window). So this file cannot reuse that
 * helper or its numeric range; it derives an adjacent band the same way,
 * one thousand down where nothing else reaches (confirmed by grepping
 * `e2e/tests` and `e2e/fixtures` for four-digit `channel_number` literals
 * before picking it — the only other four-digit numbers found are
 * `refresh_interval` seconds/hours in `async-wait.spec.ts` and
 * `refresh-scheduling.spec.ts`, an unrelated field).
 *
 * `bandFor(workerIndex, testSlot)` starts at `8000`, `+200` per worker (so
 * worker 3's band tops out at `8799`, still 200 clear of G3's `9000`), and
 * `+40` per test slot inside that — one slot per test below, 0 through 4,
 * each with 40 numbers of headroom though no test here uses more than about
 * a dozen. Every channel this file creates is inside its own test's
 * sub-range, and every assertion is on that test's own ids — never a global
 * count or an unfiltered list.
 *
 * No `afterEach` deletes these channels. `authorization.spec.ts` and
 * `m3u-filters.spec.ts` (this goal's own precedent) leave their seeded rows
 * in place too: nothing here is ever read by number outside the test that
 * created it, so a leftover row is inert, not a hazard — the band, not
 * cleanup, is what keeps this file safe to run repeatedly against a
 * long-lived container.
 */

const BAND_BASE = 8000;
const WORKER_SPAN = 200;
const TEST_SPAN = 40;

function bandFor(workerIndex: number, testSlot: number): number {
  return BAND_BASE + workerIndex * WORKER_SPAN + testSlot * TEST_SPAN;
}

async function readChannel(api: ApiClient, id: number): Promise<Channel> {
  return api.json<Channel>(
    await api.get(`/api/channels/channels/${id}/`),
    `channel ${id} read-back`
  );
}

test('edit/bulk applies every valid row', { tag: '@contract' }, async ({ seed, api }, testInfo) => {
  const base = bandFor(testInfo.workerIndex, 0);
  const a = await seed.channel({ channel_number: base, user_level: 0 });
  const b = await seed.channel({ channel_number: base + 1, user_level: 0 });
  const c = await seed.channel({ channel_number: base + 2, user_level: 0 });

  // `edit/bulk` (apps/channels/api_views.py:ChannelViewSet.edit_bulk) takes
  // a bare list of `{id, ...}` objects, not an envelope.
  const res = await api.patch('/api/channels/channels/edit/bulk/', [
    { id: a.id, channel_number: base + 10, user_level: 1 },
    { id: b.id, channel_number: base + 11, user_level: 5 },
    { id: c.id, channel_number: base + 12, user_level: 10 },
  ]);
  expect(res.ok()).toBeTruthy();

  const expectations: [Channel, number, number][] = [
    [a, base + 10, 1],
    [b, base + 11, 5],
    [c, base + 12, 10],
  ];
  for (const [channel, expectedNumber, expectedLevel] of expectations) {
    const readBack = await readChannel(api, channel.id);
    expect(readBack.channel_number).toBe(expectedNumber);
    expect(readBack.user_level).toBe(expectedLevel);
  }
});

test('edit/bulk validates before it applies', { tag: '@contract' }, async ({ seed, api }, testInfo) => {
  const base = bandFor(testInfo.workerIndex, 1);
  const a = await seed.channel({ channel_number: base, user_level: 0 });
  const b = await seed.channel({ channel_number: base + 1, user_level: 0 });
  const c = await seed.channel({ channel_number: base + 2, user_level: 0 });

  // `edit_bulk` (:1140-1155) walks the raw payload first and collects every
  // entry with no `id` into `missing_ids` *before* it fetches a single
  // `Channel` row — the 400 below fires ahead of any read or write, which is
  // what the "none of the valid rows changed" assertion is pinning.
  const res = await api.patch('/api/channels/channels/edit/bulk/', [
    { id: a.id, user_level: 5 },
    { id: b.id, user_level: 5 },
    { id: c.id, user_level: 5 },
    { user_level: 5 },
  ]);
  expect(res.status()).toBe(400);
  const body: { errors: unknown[] } = await res.json();
  expect(Array.isArray(body.errors)).toBe(true);
  expect(body.errors.length).toBeGreaterThan(0);

  for (const channel of [a, b, c]) {
    const readBack = await readChannel(api, channel.id);
    expect(readBack.user_level).toBe(0);
  }
});

test('bulk-delete removes exactly the ids in its body', { tag: '@contract' }, async ({ seed, api }, testInfo) => {
  const base = bandFor(testInfo.workerIndex, 2);
  const a = await seed.channel({ channel_number: base });
  const b = await seed.channel({ channel_number: base + 1 });
  const c = await seed.channel({ channel_number: base + 2 });
  const keep = await seed.channel({ channel_number: base + 3 });

  // `BulkDeleteChannelsAPIView.delete` (:2540-2548) returns
  // `Response({"message": "Channels deleted"}, status=204)` — a 204 *with a
  // body*. Assert only the status; the body is not part of the contract a
  // 204 makes. No `stop_stream` in the body: no stream is running, and the
  // flag would reach into the proxy for no reason.
  const res = await api.delete('/api/channels/channels/bulk-delete/', {
    channel_ids: [a.id, b.id, c.id],
  });
  expect(res.status()).toBe(204);

  for (const channel of [a, b, c]) {
    const getRes = await api.get(`/api/channels/channels/${channel.id}/`);
    expect(getRes.status()).toBe(404);
  }

  const keepReadBack = await readChannel(api, keep.id);
  expect(keepReadBack.channel_number).toBe(base + 3);
});

test('assign renumbers exactly the ids it was given', { tag: '@contract' }, async ({ seed, api }, testInfo) => {
  const base = bandFor(testInfo.workerIndex, 3);
  const a = await seed.channel({ channel_number: base });
  const b = await seed.channel({ channel_number: base + 1 });
  const c = await seed.channel({ channel_number: base + 2 });
  const excluded = await seed.channel({ channel_number: base + 3 });

  // `assign` (:1928-1944) performs no collision check — it walks
  // `channel_ids` in list order and writes `starting_number`,
  // `starting_number + 1`, ... with a plain per-id `.update()`. The band is
  // what makes that safe to provoke here.
  const startingNumber = base + 20;
  const res = await api.post('/api/channels/channels/assign/', {
    channel_ids: [a.id, b.id, c.id],
    starting_number: startingNumber,
  });
  expect(res.ok()).toBeTruthy();

  const expectations: [Channel, number][] = [
    [a, startingNumber],
    [b, startingNumber + 1],
    [c, startingNumber + 2],
  ];
  for (const [channel, expected] of expectations) {
    const readBack = await readChannel(api, channel.id);
    expect(readBack.channel_number).toBe(expected);
  }

  const excludedReadBack = await readChannel(api, excluded.id);
  expect(excludedReadBack.channel_number).toBe(base + 3);
});

// @characterization: reorder shifts by a raw channel_number range query
// (channel_number__gte / __lt) with no account, group or profile filter —
// see the file header's D9 note. This test stays inside its own
// three-channel band so the global shift the endpoint actually performs is
// both observable and safe on a shared instance.
test('reorder moves one channel and shifts only the ones between', { tag: '@characterization' }, async ({ seed, api }, testInfo) => {
  const base = bandFor(testInfo.workerIndex, 4);
  const n = base + 10;
  const first = await seed.channel({ channel_number: n });
  const second = await seed.channel({ channel_number: n + 1 });
  const third = await seed.channel({ channel_number: n + 2 });

  // Moving `third` to just after `first`: target_number = n, desired_number
  // = n + 1. Since desired (n + 1) < old (n + 2), `reorder` takes the
  // "moving up" branch and increments every channel with
  // `channel_number in [n + 1, n + 2)` — which, inside this test's band,
  // is only `second`.
  const res = await api.post(`/api/channels/channels/${third.id}/reorder/`, {
    insert_after_id: first.id,
  });
  expect(res.ok()).toBeTruthy();

  const firstAfter = await readChannel(api, first.id);
  const secondAfter = await readChannel(api, second.id);
  const thirdAfter = await readChannel(api, third.id);

  expect(firstAfter.channel_number).toBe(n);
  expect(thirdAfter.channel_number).toBe(n + 1);
  expect(secondAfter.channel_number).toBe(n + 2);
});
