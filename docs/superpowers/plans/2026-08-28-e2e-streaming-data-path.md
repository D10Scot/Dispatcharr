# G4 — Live Streaming Data Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove Dispatcharr's live streaming data path end to end — aligned contiguous bytes, multi-client sharing of one upstream, mid-stream switching, all three failover triggers, and the three Stream Profile architectures.

**Architecture:** Three Playwright projects, one CI matrix job each, so the suite triples in scope while wall-clock stays near ten minutes. `streaming` holds the fast rows; `streaming-failover` holds rows that pay a real product-defined wait; `streaming-greybox` is a quarantine holding the only tests permitted to touch Redis, isolated so Phase 3 can find and rewrite them as one unit. Tests drive the fake upstream provider (G2) and assert through `/proxy/ts/status/<id>`, because `live_proxy` emits no WebSocket event for a switch, a failover or a teardown.

**Tech Stack:** TypeScript, Playwright 1.62.x, Node 24, the G1 fixture set (`api`, `seed`, `upstream`, `streamClient`, `waitFor`, `ws`), the G2 fake provider and its eight faults, Docker, Redis.

**Spec:** `docs/superpowers/specs/2026-08-28-e2e-streaming-data-path-design.md` — read it before Task 1. The plan argues from it; every task cites the decisions it implements.

## Global Constraints

Copied verbatim from the spec and the programme rules. Every task's requirements implicitly include this section.

- **Every `live_proxy` endpoint is keyed by the channel's UUID STRING, never its numeric id.** `urls.py` captures `<str:channel_id>` on all seven routes, `stream_ts` never reassigns it, and `channel_status` passes it straight to `ChannelStatus.get_detailed_channel_info`, which reads `RedisKeys.channel_metadata(channel_id)` with no DB lookup. `views.py`'s XC path calls `stream_ts(request._request, str(channel.uuid), ...)`, which settles which identifier is canonical. Passing `channel.id` to `/proxy/ts/status/`, `/change_stream/`, `/next_stream/` or `/stop/` returns 404 every time, for every channel. Use `channel.uuid` throughout.
- **Import map — every shared symbol comes from exactly one place. Never redefine one locally.**
  Task code blocks below often omit the import lines; this table is authoritative.

  | Symbol | From |
  |---|---|
  | `test`, `expect`, `expectTsAligned`, `expectContiguous`, `videoPidOf`, `readChannelStatus`, `TS_PACKET_SIZE` | `'../../fixtures'` |
  | `lockedProfile`, `newStreamClient` | `'./helpers'` from a spec in `tests/streaming/`; **`'../streaming/helpers'`** from a spec in `tests/streaming-failover/` or `tests/streaming-greybox/` |
  | `greyboxRedis`, `GREYBOX_ALLOWLIST` | `'../../fixtures/greybox/redis'` — importable ONLY from `tests/streaming-greybox/`, enforced by the allowlist meta-test |

  The relative path to `helpers.ts` differs by which project directory the spec
  lives in. It is one module in `tests/streaming/`, shared across all three
  projects — not one copy per directory.

- **Never assert a global count or an unfiltered list.** Scope every assertion to the worker's own seeded rows. (Roadmap rule 4; `e2e/README.md`.)
- **Find built-in Stream Profiles by name, never by count.** `Proxy` and `Redirect` come from `core/migrations/0007`, `VLC` from `0019`.
- **Product defects are asserted correct, marked `test.fail()` with the defect named in a comment, and filed as issues — never patched.** Issues go to `gh issue create --repo D10Scot/Dispatcharr`; the explicit `--repo` flag is mandatory, because this checkout is a fork and `gh` without it resolves to upstream's public tracker.
- **Every read that could hang is bounded by the `withDeadline()` pattern** from `e2e/tests/streaming/stalled-stream.spec.ts`. The project timeout is 300 000 ms; an unbounded deadlocked read burns all of it and reports a timeout instead of a named failure.
- **`UpstreamChannel` requires all four fields — `id`, `name`, `tvgId`, `logo`.** None are optional. A two-field literal does not compile, and the blocking typecheck hook refuses the edit. `tvgId` is a slug of the name; `logo` is `null` unless a test asserts on it.
- **Scenarios declare explicit channel ids and names.** Channel 1 is always "Fake Channel 1" across all scenarios; an implicit catalogue is a cross-test collision with parallel workers.
- **Five of the eight faults are "new connection only"** (`not-found`, `auth-failure`, `connection-limit`, `redirect-chain`, `non-ts-bytes`). They must be armed *before* the connection they affect, and `appliedTo: 0` is the correct response for them — not a failure.
- **`upstream.toControl(url)` throws on any URL not under the internal origin.** That is a safety property. Never bypass it.
- **The typecheck hook is blocking.** Any edit to `e2e/**/*.ts` runs `tsc --noEmit` for that package and blocks on failure. Run `cd e2e && npm ci` first or it degrades to a loud note.
- **The zizmor hook is blocking on every finding** in an edited `.github/workflows/*.yml`, legacy included. The workflows are at zero findings; keep them there.
- **G7 is in flight on six shared files** — `scripts/e2e_up.sh`, `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`, `e2e/COVERAGE.md`, `e2e/README.md`, `e2e/package.json`. G4 lands its edits to these first; G7 rebases through them. G3 additionally collides on `e2e/fixtures/seed.ts`.

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `e2e/tests/streaming/single-client.spec.ts` | Row 1 — aligned, contiguous TS to one client |
| `e2e/tests/streaming/shared-upstream.spec.ts` | Rows 2–3 — N clients on one upstream; teardown releases it |
| `e2e/tests/streaming/stream-profiles.spec.ts` | Rows 5–6 — Redirect and FFmpeg architectures |
| `e2e/tests/streaming-failover/mid-stream-switch.spec.ts` | Row 7 |
| `e2e/tests/streaming-failover/failover-dead-air.spec.ts` | Row 8 |
| `e2e/tests/streaming-failover/failover-connect-failure.spec.ts` | Row 9 |
| `e2e/tests/streaming-failover/failover-buffering.spec.ts` | Row 10 |
| `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts` | Row 11 |
| `e2e/tests/streaming-greybox/ownership-lease.spec.ts` | Row 12 — the flagship |
| `e2e/tests/streaming-greybox/quarantine.spec.ts` | D5 — the allowlist meta-test |
| `e2e/fixtures/greybox/redis.ts` | The single sanctioned Redis accessor |
| `e2e/fixtures/channel-status.ts` | Typed reader for `/proxy/ts/status/<id>` |

**Modified:**

| Path | Change |
|---|---|
| `e2e/fixtures/seed.ts` | Add `stream()` and `upstreamChannel()` (D3) |
| `e2e/fixtures/types.ts` | Add `Stream`, `StreamOverrides`, `ChannelStatus`, `OutputProfile` |
| `e2e/fixtures/index.ts` | Export `expectContiguous`, `channelStatus`; register no new fixture for greybox |
| `e2e/fixtures/stream-client.ts` | Add `expectContiguous(buffer, pid)` (D6) |
| `e2e/playwright.config.ts` | Add `streaming-failover`, `streaming-greybox` projects |
| `.github/workflows/e2e-tests.yml` | Add both to the matrix |
| `e2e/package.json` | Add `test:streaming-failover`, `test:streaming-greybox`; update the bare-`test` message |
| `scripts/e2e_up.sh` | Publish Redis, **only if Task 9's probe proves it reachable** (D4) |
| `e2e/COVERAGE.md` | Nine rows → `done`; add row 12 as `known-bug` |
| `e2e/README.md` | Document the three projects and the greybox "run it alone" rule |

---

### Task 1: Stream and upstream-channel seed factories

Implements D3. Every subsequent task uses these, so this lands first — and it touches `seed.ts`, which G3 also edits, so landing early shrinks the conflict window.

**Files:**
- Modify: `e2e/fixtures/seed.ts`
- Modify: `e2e/fixtures/types.ts`
- Test: `e2e/tests/seeded/seed-fixture.spec.ts`

**Interfaces:**
- Consumes: `Seeder.create`, `Seeder.generatedName`, `UpstreamClient.streamUrl`, `UpstreamScenario` — all existing.
- Produces:
  - `seed.stream(overrides?: StreamOverrides): Promise<Stream>`
  - `seed.upstreamChannel(scenario: UpstreamScenario, opts: UpstreamChannelOptions): Promise<{ channel: Channel; streams: Stream[] }>`
  - `type Stream = { id: number; name: string; url: string; is_custom: boolean }`
  - `type StreamOverrides = { url?: string; is_custom?: boolean; channel_group?: number | null }`
  - `type UpstreamChannelOptions = { channelIds: number[]; streamProfileId?: number | null; channel?: ChannelOverrides }`

- [ ] **Step 1: Add the types**

In `e2e/fixtures/types.ts`, after the `StreamProfile` type:

```ts
/**
 * A `Stream` row. Streams are what a `Channel` points at; the channel is what
 * a client tunes. `is_custom: true` marks a row created by hand rather than
 * ingested from an M3U account — which is what every G4 test wants, because
 * ingesting would test the M3U path (G3) rather than the streaming path.
 */
export type Stream = {
  id: number;
  name: string;
  url: string;
  is_custom: boolean;
};

/** Omits `name`: the factory owns it. See the ordering note in seed.ts. */
export type StreamOverrides = {
  url?: string;
  is_custom?: boolean;
  channel_group?: number | null;
};

/**
 * Options for {@link Seeder.upstreamChannel}. `channelIds` are the *fake
 * provider's* channel ids, in the order the resulting Channel should try
 * them — so `[1, 2]` makes provider channel 1 the primary and 2 the
 * failover target.
 */
export type UpstreamChannelOptions = {
  channelIds: number[];
  streamProfileId?: number | null;
  channel?: ChannelOverrides;
};
```

- [ ] **Step 2: Write the failing test**

Append to `e2e/tests/seeded/seed-fixture.spec.ts`:

```ts
test('seed.stream creates a custom stream with a generated name', async ({ seed }) => {
  const stream = await seed.stream({ url: 'http://127.0.0.1:9/x.ts' });

  expect(stream.id).toBeGreaterThan(0);
  expect(stream.is_custom).toBe(true);
  expect(stream.url).toBe('http://127.0.0.1:9/x.ts');
  expect(stream.name).toMatch(/^e2e-w\d+-/);
});

test('seed.stream ignores an attempt to override the generated name', async ({ seed }) => {
  // The identity field is spread AFTER overrides. A cast is the only way to
  // even attempt this, which is the point of the test: the type forbids it,
  // and the ordering enforces it for bodies that dodge the type.
  const stream = await seed.stream({ name: 'not-this' } as never);
  expect(stream.name).not.toBe('not-this');
});
```

- [ ] **Step 3: Run it and confirm it fails**

Run: `cd e2e && npx playwright test --project=seeded seed-fixture --grep "seed.stream"`
Expected: FAIL — `seed.stream is not a function`.

- [ ] **Step 4: Implement `seed.stream()`**

In `e2e/fixtures/seed.ts`, after `streamProfile()`:

```ts
  stream(overrides: StreamOverrides = {}): Promise<Stream> {
    const body: StreamOverrides & { name: string } = {
      url: 'http://127.0.0.1:9/stream.ts',
      is_custom: true,
      ...overrides,
      name: this.generatedName('stream'),
    };
    return this.create<Stream>('/api/channels/streams/', 'stream', body);
  }
```

The unroutable default mirrors `m3uAccount()`'s: a factory must never point at a live service by accident.

- [ ] **Step 5: Run it and confirm it passes**

Run: `cd e2e && npx playwright test --project=seeded seed-fixture --grep "seed.stream"`
Expected: PASS, 2 tests.

- [ ] **Step 6: Write the failing test for `upstreamChannel`**

```ts
test('seed.upstreamChannel wires a channel to the provider in order', async ({
  seed,
  upstream,
}) => {
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: 'Primary', tvgId: 'primary.e2e', logo: null },
      { id: 2, name: 'Backup', tvgId: 'backup.e2e', logo: null },
    ],
  });

  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
  });

  expect(streams).toHaveLength(2);
  expect(streams[0].url).toBe(upstream.streamUrl(scenario, 1));
  expect(streams[1].url).toBe(upstream.streamUrl(scenario, 2));
  expect(channel.streams).toEqual([streams[0].id, streams[1].id]);
  expect(channel.uuid).toBeTruthy();
});
```

- [ ] **Step 7: Run it and confirm it fails**

Run: `cd e2e && npx playwright test --project=seeded seed-fixture --grep "upstreamChannel"`
Expected: FAIL — `seed.upstreamChannel is not a function`.

- [ ] **Step 8: Implement `upstreamChannel()`**

```ts
  /**
   * The five-step wiring every streaming test needs, once: one Stream per
   * provider channel id, then a Channel pointing at them in that order.
   *
   * Streams are created serially rather than with Promise.all. The order of
   * `channel.streams` decides which upstream is primary and which is the
   * failover target, and a concurrent create gives the API no reason to
   * preserve it.
   */
  async upstreamChannel(
    scenario: UpstreamScenario,
    opts: UpstreamChannelOptions
  ): Promise<{ channel: Channel; streams: Stream[] }> {
    const streams: Stream[] = [];
    for (const channelId of opts.channelIds) {
      streams.push(await this.stream({ url: this.upstreamStreamUrl(scenario, channelId) }));
    }

    const channel = await this.channel({
      ...opts.channel,
      streams: streams.map((s) => s.id),
      stream_profile_id: opts.streamProfileId ?? null,
    });

    return { channel, streams };
  }
```

`Seeder` has no `upstream` reference, so add a small private helper rather than
importing `UpstreamClient` (which would create a fixture cycle):

```ts
  private upstreamStreamUrl(scenario: UpstreamScenario, channelId: number): string {
    return `${scenario.internal}/stream/${channelId}.ts${scenario.credentialQuery}`;
  }
```

Confirm this matches `UpstreamClient.streamUrl` exactly before moving on — if
the provider's URL shape changes, two places must change. Add a comment in each
naming the other.

- [ ] **Step 9: Run it and confirm it passes**

Run: `cd e2e && npx playwright test --project=seeded seed-fixture`
Expected: PASS, all tests in the file.

- [ ] **Step 10: Commit**

Stage `e2e/fixtures/seed.ts`, `e2e/fixtures/types.ts`, `e2e/tests/seeded/seed-fixture.spec.ts` and commit as `test(e2e): add stream and upstreamChannel seed factories`.

---

### Task 2: Contiguity assertion and the channel-status reader

Implements D6 and gives every later task its assertion surface.

**Files:**
- Modify: `e2e/fixtures/stream-client.ts`
- Create: `e2e/fixtures/channel-status.ts`
- Modify: `e2e/fixtures/types.ts`, `e2e/fixtures/index.ts`
- Test: `e2e/tests/streaming/single-client.spec.ts` (created in Task 3; assert here with a unit-style spec)

**Interfaces:**
- Produces:
  - `expectContiguous(buffer: Buffer, pid: number): void`
  - `videoPidOf(buffer: Buffer): number`
  - `readChannelStatus(api: ApiClient, channelUuid: string): Promise<ChannelStatus>`
  - `type ChannelStatus = { stream_id: number | null; stream_name: string | null; url: string | null; state: string; owner: string | null; client_count: number; buffer_index: number; total_bytes: number; avg_bitrate_kbps: number; clients: ChannelStatusClient[]; ffmpeg_speed?: number; video_codec?: string; resolution?: string }`

- [ ] **Step 1: Write the failing test**

Create `e2e/tests/streaming/contiguity.spec.ts`:

```ts
import { test, expect } from '@playwright/test';
import { expectContiguous, videoPidOf, TS_PACKET_SIZE } from '../../fixtures';

/** Build `count` TS packets on `pid` with continuity counters from `startCc`. */
function synth(pid: number, count: number, startCc = 0, skipAt = -1): Buffer {
  const out = Buffer.alloc(count * TS_PACKET_SIZE);
  let cc = startCc;
  for (let i = 0; i < count; i++) {
    const off = i * TS_PACKET_SIZE;
    out[off] = 0x47;
    out[off + 1] = (pid >> 8) & 0x1f;
    out[off + 2] = pid & 0xff;
    if (i === skipAt) cc = (cc + 1) & 0x0f; // drop one, simulating a lost packet
    out[off + 3] = 0x10 | (cc & 0x0f); // payload only, no adaptation field
    cc = (cc + 1) & 0x0f;
  }
  return out;
}

test('expectContiguous accepts an unbroken counter run', () => {
  expect(() => expectContiguous(synth(0x0100, 40), 0x0100)).not.toThrow();
});

test('expectContiguous accepts a counter that wraps past 15', () => {
  expect(() => expectContiguous(synth(0x0100, 40, 13), 0x0100)).not.toThrow();
});

test('expectContiguous rejects a gap in the counter', () => {
  expect(() => expectContiguous(synth(0x0100, 40, 0, 20), 0x0100)).toThrow(
    /continuity/i
  );
});

test('videoPidOf picks the busiest non-null PID', () => {
  const mixed = Buffer.concat([synth(0x0100, 30), synth(0x1fff, 5)]);
  expect(videoPidOf(mixed)).toBe(0x0100);
});
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `cd e2e && npx playwright test --project=streaming contiguity`
Expected: FAIL — `expectContiguous` is not exported.

- [ ] **Step 3: Implement both helpers**

Append to `e2e/fixtures/stream-client.ts`:

```ts
/** The null PID carries stuffing only and has no meaningful counter. */
const TS_NULL_PID = 0x1fff;

/** PID is 13 bits: the low 5 of byte 1 and all of byte 2. */
function pidAt(buffer: Buffer, offset: number): number {
  return ((buffer[offset + 1] & 0x1f) << 8) | buffer[offset + 2];
}

/**
 * The busiest PID that is not the null PID. Which PID carries video is a
 * property of the asset, not of Dispatcharr, so tests derive it rather than
 * hard-coding it — a re-muxed asset would otherwise silently assert nothing.
 */
export function videoPidOf(buffer: Buffer): number {
  const counts = new Map<number, number>();
  for (let off = 0; off + TS_PACKET_SIZE <= buffer.byteLength; off += TS_PACKET_SIZE) {
    const pid = pidAt(buffer, off);
    if (pid === TS_NULL_PID) continue;
    counts.set(pid, (counts.get(pid) ?? 0) + 1);
  }
  let best = -1;
  let bestCount = 0;
  for (const [pid, n] of counts) {
    if (n > bestCount) {
      best = pid;
      bestCount = n;
    }
  }
  expect(best, 'buffer contains no non-null PID').toBeGreaterThanOrEqual(0);
  return best;
}

/**
 * Assert the 4-bit continuity counter on `pid` increments by exactly one per
 * payload-bearing packet, wrapping at 16.
 *
 * This is what proves nothing was lost or spliced. A byte count proves only
 * that bytes arrived — and the defect this suite most needs to catch (two
 * owners interleaving chunks at alternating indices) produces a stream whose
 * length is perfectly correct.
 *
 * Packets with adaptation_field_control 0b00 or 0b10 carry no payload and do
 * not advance the counter; skipping them is required by the TS spec, not an
 * optimisation.
 */
export function expectContiguous(buffer: Buffer, pid: number): void {
  let previous: number | null = null;
  let checked = 0;

  for (let off = 0; off + TS_PACKET_SIZE <= buffer.byteLength; off += TS_PACKET_SIZE) {
    if (pidAt(buffer, off) !== pid) continue;

    const afc = (buffer[off + 3] >> 4) & 0x03;
    if (afc === 0b00 || afc === 0b10) continue; // no payload: counter does not advance

    const cc = buffer[off + 3] & 0x0f;
    if (previous !== null) {
      const expected = (previous + 1) & 0x0f;
      expect(
        cc,
        `continuity counter gap on PID 0x${pid.toString(16)} at byte ${off}: ` +
          `expected ${expected}, saw ${cc}`
      ).toBe(expected);
    }
    previous = cc;
    checked++;
  }

  expect(checked, `no payload-bearing packets on PID 0x${pid.toString(16)}`).toBeGreaterThan(0);
}
```

- [ ] **Step 4: Run it and confirm it passes**

Run: `cd e2e && npx playwright test --project=streaming contiguity`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add the channel-status reader**

Create `e2e/fixtures/channel-status.ts`:

```ts
import type { ApiClient } from './api';
import type { ChannelStatus } from './types';

/**
 * Read `/proxy/ts/status/<id>`.
 *
 * This is G4's primary assertion surface. It is admin-only, so it goes
 * through the `api` fixture rather than `streamClient`.
 *
 * Use the per-channel form, never the bare collection endpoint: `GET
 * /proxy/ts/status` broadcasts a `channel_stats` WebSocket event as a side
 * effect of being polled, which would perturb any test waiting on the socket.
 */
export async function readChannelStatus(
  api: ApiClient,
  channelUuid: string
): Promise<ChannelStatus> {
  const res = await api.get(`/proxy/ts/status/${channelUuid}`);
  return api.json<ChannelStatus>(res, `channel status for ${channelUuid}`);
}
```

Add the matching types to `types.ts` and export both from `index.ts`.

- [ ] **Step 6: Typecheck and commit**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Stage and commit as `test(e2e): add TS contiguity assertion and channel-status reader`.

---

### Task 3: Project topology — two new projects, CI matrix, scripts, docs

Implements D1 and D2's structure. Nothing in Tasks 6–12 can run until this lands.

**Files:**
- Modify: `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`, `e2e/package.json`, `e2e/README.md`

- [ ] **Step 1: Add the two projects**

In `e2e/playwright.config.ts`, after the `streaming` project:

```ts
    {
      name: 'streaming-failover',
      testDir: './tests/streaming-failover',
      dependencies: ['bootstrap'],
      // Each row here pays a product-defined wait: the dead-air watchdog is
      // >10s sampled 3x at 5s, and the buffering detector needs the ffmpeg
      // process's cumulative speed= to cross a threshold. 300s is the same
      // ceiling `streaming` uses and is not generous here.
      timeout: 300_000,
      workers: 2,
      use: { storageState: 'playwright/.auth/admin.json' },
    },
    {
      name: 'streaming-greybox',
      testDir: './tests/streaming-greybox',
      dependencies: ['bootstrap'],
      timeout: 300_000,
      // One worker, unlike its siblings: these tests mutate shared Redis
      // state (deleting an ownership lease), so parallel workers inside this
      // project would race each other.
      workers: 1,
      use: { storageState: 'playwright/.auth/admin.json' },
    },
```

- [ ] **Step 2: Do NOT touch the CI workflow in this task**

The CI-matrix edit belongs to Task 13, not here. Playwright *errors* rather than
reporting zero tests when a project's `testDir` does not exist, and these two
directories are not created until Tasks 7 and 10 — so adding the projects to CI
now would redden every intermediate commit on this branch for no benefit. The
directories come into existence naturally as those tasks land.

- [ ] **Step 4: Add npm scripts**

In `e2e/package.json`:

```json
    "test:streaming-failover": "playwright test --project=streaming-failover",
    "test:streaming-greybox": "playwright test --project=streaming-greybox",
```

Update the bare `test` script's message to list all five populations. It
currently names three; leaving it stale makes it read as a broken error
message forever.

- [ ] **Step 5: Document the topology**

In `e2e/README.md`, add the two projects to the population table, and state
plainly: **`streaming-greybox` must be run alone locally.** In CI it is safe
because each matrix job has its own container, but locally all projects can
share one, and this project deletes ownership leases out from under whatever
else is running.

- [ ] **Step 6: Verify the config still parses**

Run: `cd e2e && npx playwright test --list --project=streaming`
Expected: exits 0 and lists the existing streaming specs. This proves the config
file still parses with the two new project entries in it.

Do **not** try to `--list` the new projects yet: their `testDir` directories do
not exist until Tasks 7 and 10, and Playwright errors on a missing `testDir`
rather than reporting zero tests.

- [ ] **Step 7: Commit**

Stage all four files and commit as `test(e2e): add streaming-failover and streaming-greybox projects`.

---

### Task 4: Row 1 — a single client receives aligned, contiguous TS

**Files:**
- Create: `e2e/tests/streaming/single-client.spec.ts`

**Interfaces:**
- Consumes: `seed.upstreamChannel`, `expectContiguous`, `videoPidOf`, `readChannelStatus`.

- [ ] **Step 1: Write the test**

**First create the shared helper module** `e2e/tests/streaming/helpers.ts`.
Seven later tasks import from it; defining these inline would mean six
copy-pasted duplicates of the same logic, which the task review treats as a
defect. Playwright's default `testMatch` collects only `*.spec.ts`, so a
`helpers.ts` sitting inside a `testDir` is not picked up as a suite.

```ts
// e2e/tests/streaming/helpers.ts
import { expect } from '@playwright/test';
import { StreamClient } from '../../fixtures';
import type { ApiClient, StreamProfile } from '../../fixtures';

/** Find a locked built-in Stream Profile by name. Never assert on a count. */
export async function lockedProfile(api: ApiClient, name: string): Promise<StreamProfile> {
  const page = await api.json<{ results?: StreamProfile[] } | StreamProfile[]>(
    await api.get('/api/core/streamprofiles/'),
    'stream profiles'
  );
  const all = Array.isArray(page) ? page : (page.results ?? []);
  const found = all.find((p) => p.name === name);
  expect(found, `the locked "${name}" stream profile should ship`).toBeDefined();
  return found!;
}

/**
 * A second, third, ... StreamClient. The `streamClient` fixture provides
 * exactly one per test; rows that assert on upstream *sharing* need several.
 * The caller owns closing each one.
 */
export function newStreamClient(): StreamClient {
  return new StreamClient(process.env.E2E_BASE_URL ?? 'http://localhost:9191');
}
```

Then the spec itself:

```ts
import { test, expect, expectTsAligned, expectContiguous, videoPidOf, TS_PACKET_SIZE, readChannelStatus } from '../../fixtures';
import { lockedProfile } from './helpers';

test('one client receives aligned, contiguous TS through the Proxy profile', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Single', tvgId: 'g4-single.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  const packets = await streamClient.readPackets(400);

  expect(packets.byteLength).toBe(400 * TS_PACKET_SIZE);
  expectTsAligned(packets);
  // Alignment proves framing. Contiguity proves nothing was lost or spliced —
  // which is the property the whole relay extraction rests on.
  expectContiguous(packets, videoPidOf(packets));

  const status = await readChannelStatus(api, channel.uuid);
  expect(status.client_count).toBe(1);

  // total_bytes is assigned only once the metadata field exists, so a status
  // read taken moments after start can omit it entirely. Poll rather than read
  // once — a bare read makes this a flake, not a detector.
  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).total_bytes ?? 0, {
      timeout: 30_000,
    })
    .toBeGreaterThan(0);

  // The provider agrees it served exactly one connection for this channel.
  const opens = (await upstream.log(scenario)).filter(
    (e) => e.kind === 'open' && e.channelId === 1
  );
  expect(opens).toHaveLength(1);
});
```

- [ ] **Step 2: Bring up the stack and run it**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming single-client`
Expected: PASS.

- [ ] **Step 3: Prove the contiguity assertion is not vacuous**

Temporarily change `expectContiguous` to compare against `(previous + 2) & 0x0f`.
Re-run. Expected: FAIL with a continuity-counter message. **Revert the change.**

This step is not optional. A contiguity assertion that silently passes on any
input is worse than no assertion, because it reads as coverage.

- [ ] **Step 4: Commit**

Commit as `test(e2e): single client receives aligned contiguous TS (G4 row 1)`.

---

### Task 5: Rows 2–3 — N clients share one upstream, and teardown releases it

**Files:**
- Create: `e2e/tests/streaming/shared-upstream.spec.ts`

- [ ] **Step 1: Write the sharing test**

Import the shared helpers Task 4 created — do not redefine them:

```ts
import { test, expect, expectTsAligned, readChannelStatus } from '../../fixtures';
import { lockedProfile, newStreamClient } from './helpers';
```

Then:

```ts
test('three clients share exactly one upstream connection', async ({
  upstream,
  seed,
  api,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Shared', tvgId: 'g4-shared.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  const clients = [newStreamClient(), newStreamClient(), newStreamClient()];
  try {
    for (const c of clients) {
      await c.open(`/proxy/ts/stream/${channel.uuid}`);
      expectTsAligned(await c.readPackets(20));
    }

    await expect
      .poll(async () => (await readChannelStatus(api, channel.uuid)).client_count, {
        timeout: 20_000,
      })
      .toBe(3);

    // The point of the row: three clients, one upstream.
    const live = await upstream.connections(scenario);
    expect(live.live).toBe(1);

    await clients[0].close();
    await expect
      .poll(async () => (await readChannelStatus(api, channel.uuid)).client_count, {
        timeout: 20_000,
      })
      .toBe(2);
    expect((await upstream.connections(scenario)).live).toBe(1);
  } finally {
    await Promise.all(clients.map((c) => c.close().catch(() => {})));
  }
});
```

`newStreamClient()` lives in the shared helper module created in Task 4 — it
constructs a `StreamClient` against `E2E_BASE_URL`, because the `streamClient`
fixture provides exactly one instance per test and this row needs three.

- [ ] **Step 2: Run it**

Run: `cd e2e && npx playwright test --project=streaming shared-upstream --grep "share"`
Expected: PASS.

- [ ] **Step 3: Write the teardown test**

```ts
test('closing every client releases the upstream', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Teardown', tvgId: 'g4-teardown.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  expectTsAligned(await streamClient.readPackets(20));
  expect((await upstream.connections(scenario)).live).toBe(1);

  await streamClient.close();

  // The channel does not stop the instant the last client leaves — the owner
  // notices on its next main-loop iteration. Poll rather than assert once.
  await expect
    .poll(async () => (await upstream.connections(scenario)).live, { timeout: 60_000 })
    .toBe(0);
});
```

- [ ] **Step 4: Run it**

Run: `cd e2e && npx playwright test --project=streaming shared-upstream`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

Commit as `test(e2e): N clients share one upstream; teardown releases it (G4 rows 2-3)`.

---

### Task 6: Rows 5–6 — the Redirect and FFmpeg architectures

Implements D9 and D10. Row 4 (Proxy) is already covered by Task 4.

**Files:**
- Create: `e2e/tests/streaming/stream-profiles.spec.ts`

- [ ] **Step 1: Write the Redirect test**

```ts
test('the Redirect profile 302s the client at the provider and carries no bytes', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({ channels: [{ id: 1, name: 'G4 Redirect', tvgId: 'g4-redirect.e2e', logo: null }] });
  const redirect = await lockedProfile(api, 'Redirect');
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: redirect.id,
  });

  // Manual redirect: the Location header names a container-internal hostname
  // the Playwright host cannot resolve. Following it would exercise the fake
  // provider, not Dispatcharr — and validate_stream_url returns the URL it was
  // given, not the redirect target, so the Location is the upstream URL itself.
  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`, { redirect: 'manual' });

  expect(streamClient.status).toBe(302);
  // `headers` is a fetch `Headers` object and is optional until open() resolves
  // — it has no index signature, so `.get()` is the only way in.
  const location = streamClient.headers?.get('location');
  expect(location, 'a Redirect profile must send a Location').toBeTruthy();

  // toControl throws on anything not under the internal origin — so this line
  // is itself the assertion that we were sent at the provider and nowhere else.
  expect(() => upstream.toControl(location!)).not.toThrow();
  expect(location).toBe(streams[0].url);

  // No bytes traversed Dispatcharr: that is what "no failover after connect"
  // means for this architecture.
  expect((await upstream.connections(scenario)).live).toBe(0);
});
```

- [ ] **Step 2: Run it**

Run: `cd e2e && npx playwright test --project=streaming stream-profiles --grep Redirect`
Expected: PASS.

- [ ] **Step 3: Write the FFmpeg test**

```ts
test('the FFmpeg profile spawns a subprocess and reports its progress', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 FFmpeg', tvgId: 'g4-ffmpeg.e2e', logo: null }],
    rate: 20,
  });
  // Any profile that is not Proxy or Redirect takes the subprocess branch by
  // exclusion; seed.streamProfile()'s default command is an ffmpeg remux.
  const profile = await seed.streamProfile();
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: profile.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  const packets = await streamClient.readPackets(400);
  expectTsAligned(packets);
  expectContiguous(packets, videoPidOf(packets));

  // ffmpeg-derived fields appear on /status only for subprocess profiles.
  // Without this the row is indistinguishable from the Proxy row — and this is
  // the first test in this repository of any kind that spawns a subprocess.
  //
  // ffmpeg_speed arrives as a STRING. get_detailed_channel_info assigns the raw
  // Redis value with no conversion, while the neighbouring
  // get_basic_channel_info wraps it in float() — so the two endpoints disagree
  // about this field's type. Passing the raw value to toBeGreaterThan throws a
  // matcher error rather than failing an assertion, so parse it here.
  await expect
    .poll(
      async () => {
        const raw = (await readChannelStatus(api, channel.uuid)).ffmpeg_speed;
        return raw === undefined ? 0 : Number.parseFloat(raw);
      },
      { timeout: 60_000 }
    )
    .toBeGreaterThan(0);
});
```

- [ ] **Step 4: Run both**

Run: `cd e2e && npx playwright test --project=streaming stream-profiles`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

Commit as `test(e2e): Redirect and FFmpeg stream profile architectures (G4 rows 5-6)`.

---

### Task 7: Row 7 — a mid-stream switch does not disturb clients

Implements D7. First test in `streaming-failover`.

**Files:**
- Create: `e2e/tests/streaming-failover/mid-stream-switch.spec.ts`

- [ ] **Step 1: Write the test**

```ts
test('switching the upstream mid-stream does not disturb a reading client', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: 'G4 Switch A', tvgId: 'g4-switch-a.e2e', logo: null },
      { id: 2, name: 'G4 Switch B', tvgId: 'g4-switch-b.e2e', logo: null },
    ],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  const before = await streamClient.readPackets(200);
  expectTsAligned(before);

  const beforeStatus = await readChannelStatus(api, channel.uuid);
  expect(beforeStatus.stream_id).toBe(streams[0].id);

  // change_stream names its target; next_stream would depend on ordering.
  const res = await api.post(`/proxy/ts/change_stream/${channel.uuid}`, {
    stream_id: streams[1].id,
  });
  expect(res.status(), 'switch should be applied, not merely accepted').toBe(200);

  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).stream_id, {
      timeout: 60_000,
    })
    .toBe(streams[1].id);

  const after = await streamClient.readPackets(200);
  expectTsAligned(after);

  const afterStatus = await readChannelStatus(api, channel.uuid);
  // The invariant that makes a switch invisible to clients: the chunk index is
  // monotonic for the channel's life and is never reset by a switch. Asserting
  // it directly tests the mechanism rather than its symptom.
  expect(afterStatus.buffer_index).toBeGreaterThan(beforeStatus.buffer_index);
  expect(afterStatus.client_count).toBe(1);

  // The provider saw the handover: channel 1 closed, channel 2 opened.
  const log = await upstream.log(scenario);
  expect(log.some((e) => e.kind === 'open' && e.channelId === 2)).toBe(true);
});
```

- [ ] **Step 2: Run it**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming-failover mid-stream-switch`
Expected: PASS.

- [ ] **Step 3: Prove the switch assertion is real**

Temporarily change the `change_stream` POST to target `streams[0].id` (a switch
to the stream already playing). Re-run. Expected: FAIL on the `stream_id` poll
or on `buffer_index`. **Revert.**

- [ ] **Step 4: Commit**

Commit as `test(e2e): mid-stream switch does not disturb clients (G4 row 7)`.

---

### Task 8: Rows 8–9 — dead-air and connect-failure failover

**Files:**
- Create: `e2e/tests/streaming-failover/failover-dead-air.spec.ts`, `failover-connect-failure.spec.ts`

- [ ] **Step 1: Write the dead-air test**

```ts
test('a dead upstream fails over to the next stream', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: 'G4 DeadAir A', tvgId: 'g4-deadair-a.e2e', logo: null },
      { id: 2, name: 'G4 DeadAir B', tvgId: 'g4-deadair-b.e2e', logo: null },
    ],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  expectTsAligned(await streamClient.readPackets(100));

  // dead-air applies to live connections as well as new ones, so this reaches
  // the connection already open. The watchdog is >10s, sampled 3x at 5s — call
  // it ~25s before it fires, and allow generous headroom over that.
  await upstream.fault(scenario, 'dead-air', { channel: 1 });

  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).stream_id, {
      timeout: 120_000,
      intervals: [2_000],
    })
    .toBe(streams[1].id);

  // The client survived the failover: it is still attached and still fed.
  const after = await streamClient.readPackets(100);
  expectTsAligned(after);
  expect((await readChannelStatus(api, channel.uuid)).client_count).toBe(1);
});
```

- [ ] **Step 2: Run it**

Run: `cd e2e && npx playwright test --project=streaming-failover failover-dead-air`
Expected: PASS. Note the elapsed time — if it lands near 120s rather than ~30s,
the watchdog is not what moved the channel and the test needs re-examination
before being trusted.

- [ ] **Step 3: Write the connect-failure test**

```ts
test('an upstream that refuses the connection fails over before serving', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: 'G4 Connect A', tvgId: 'g4-connect-a.e2e', logo: null },
      { id: 2, name: 'G4 Connect B', tvgId: 'g4-connect-b.e2e', logo: null },
    ],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
    streamProfileId: proxy.id,
  });

  // not-found is a "new connection only" fault: arm it BEFORE the first
  // client, and expect appliedTo: 0 — there is no live connection to apply it
  // to, which is correct rather than a failure.
  const armed = await upstream.fault(scenario, 'not-found', { channel: 1 });
  expect(armed.appliedTo).toBe(0);

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  expectTsAligned(await streamClient.readPackets(100));

  const status = await readChannelStatus(api, channel.uuid);
  expect(status.stream_id, 'should never have settled on the 404 stream').toBe(
    streams[1].id
  );

  // The provider saw the refused attempt on 1 and the successful one on 2.
  const log = await upstream.log(scenario);
  expect(log.some((e) => e.kind === 'open' && e.channelId === 2)).toBe(true);
});
```

- [ ] **Step 4: Run both**

Run: `cd e2e && npx playwright test --project=streaming-failover --grep failover`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

Commit as `test(e2e): dead-air and connect-failure failover (G4 rows 8-9)`.

---

### Task 9: Row 10 — buffering failover, with dead air excluded by construction

Implements D8, the subtlest decision in the spec. **Read D8 before starting.**

**Files:**
- Create: `e2e/tests/streaming-failover/failover-buffering.spec.ts`

- [ ] **Step 1: Find the buffering settings and how to raise the threshold**

The detector's thresholds are snapshotted in `StreamManager.__init__`, so they
must be set **before** the channel starts. Locate `buffering_speed` and
`buffering_timeout` in the settings registry and record the exact API path and
key shape in a comment in the spec file. Do not guess: read
`core/api_urls.py` and the settings model.

- [ ] **Step 2: Write the test**

```ts
test('a degraded but not dead upstream fails over on the buffering detector', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [
      { id: 1, name: 'G4 Buffering A', tvgId: 'g4-buffering-a.e2e', logo: null },
      { id: 2, name: 'G4 Buffering B', tvgId: 'g4-buffering-b.e2e', logo: null },
    ],
    rate: 20,
  });

  // PRE-ARM. speed= is a cumulative average since ffmpeg starts, so a trickle
  // applied mid-stream needs ~55s to drag the average below 1.0 and the ~25s
  // dead-air watchdog wins first. Armed before the first connection, the
  // process never has a fast period to average against.
  const armed = await upstream.fault(scenario, 'slow-trickle', {
    channel: 1,
    rate: 0.3,
  });
  expect(armed.appliedTo).toBe(0);

  // ffmpeg profile: the buffering detector parses ffmpeg's stderr, so it is
  // inert for Proxy and Redirect. That is a documented product trap, not a
  // limitation of this test.
  const profile = await seed.streamProfile();
  const { channel, streams } = await seed.upstreamChannel(scenario, {
    channelIds: [1, 2],
    streamProfileId: profile.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);

  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).stream_id, {
      timeout: 180_000,
      intervals: [2_000],
    })
    .toBe(streams[1].id);

  // THE DISCRIMINATOR. slow-trickle keeps delivering bytes; dead air requires
  // a >10s silence. If the provider never went silent for 10s, the dead-air
  // watchdog cannot have fired, so the switch can only have come from the
  // buffering detector. This is what makes a false pass structurally
  // impossible rather than merely unlikely.
  const log = await upstream.log(scenario);
  const gaps = maxGapMs(log.filter((e) => e.channelId === 1));
  expect(
    gaps,
    `provider went quiet for ${gaps}ms — dead air could have caused this switch, ` +
      'so the test no longer proves the buffering detector fired'
  ).toBeLessThan(10_000);
});
```

`maxGapMs` is a local helper computing the largest interval between consecutive
provider log timestamps for that channel.

- [ ] **Step 3: Run it**

Run: `cd e2e && npx playwright test --project=streaming-failover failover-buffering`
Expected: PASS.

- [ ] **Step 4: If it does not fail over, do not weaken the test**

If the channel never switches, the honest outcomes in order of preference are:
(a) raise `buffering_speed` above 1.0, which is the documented lever, and
re-run; (b) if it still does not arm, record row 10 as a **documented gap** in
`COVERAGE.md` with a comment naming what was tried. **Do not** relax the
discriminator to let a dead-air switch satisfy the test — that converts the row
into a duplicate of Task 8 wearing a buffering label, which is worse than an
honest gap.

- [ ] **Step 5: Commit**

Commit as `test(e2e): buffering failover with dead air excluded by construction (G4 row 10)`.

---

### Task 10: The grey-box quarantine — Redis access, and the meta-test that enforces it

Implements D4 and D5. **Step 1 is a gate: it decides the mechanism.**

**Files:**
- Create: `e2e/fixtures/greybox/redis.ts`, `e2e/tests/streaming-greybox/quarantine.spec.ts`
- Modify: `scripts/e2e_up.sh` — **only if Step 1 succeeds**

- [ ] **Step 1: Probe whether a published Redis port is reachable at all**

The spec expects this to fail. `docker/uwsgi.ini` starts Redis as a bare
`attach-daemon = redis-server` — no config file, no `--bind`, no `requirepass`
— which leaves **protected mode** active, under which Redis serves loopback
only and refuses a connection arriving from the bridge gateway.

Run, against a container started with `-p 127.0.0.1:9403:6379` added by hand:

```bash
docker run --rm --network host redis:7-alpine redis-cli -h 127.0.0.1 -p 9403 PING
```

Expected: `DENIED Redis is running in protected mode...`, not `PONG`.

- [ ] **Step 2: Take the branch the probe dictates**

**If it answered `PONG`:** add `-p "127.0.0.1:${REDIS_PORT}:6379"` to
`scripts/e2e_up.sh`'s app-container `docker run`, defaulting
`REDIS_PORT="${DISPATCHARR_E2E_REDIS_PORT:-9403}"` alongside the existing
`PORT` and `UPSTREAM_PORT`, and implement the helper over a real client.

**If it answered `DENIED` (expected):** do not touch `scripts/e2e_up.sh` at
all — that removes G4 from one of the six files G7 also edits. Implement the
helper over `docker exec … redis-cli --json` instead. Do **not** disable
protected mode: that means editing the shipped `docker/uwsgi.ini` and
contaminating the image under test.

Record which branch was taken, and the probe output, in a comment at the top of
`redis.ts`.

- [ ] **Step 3: Implement the helper**

```ts
/**
 * The ONLY sanctioned way an E2E test reaches Redis.
 *
 * This file is quarantined on purpose. Phase 3 of this fork's stated
 * direction removes Redis from the video data path entirely, at which point
 * every test importing this helper must be rewritten or deleted. Keeping the
 * coupling in one file, imported only from `e2e/tests/streaming-greybox/`,
 * makes that blast radius a single grep instead of an archaeology exercise.
 *
 * The allowlist below is enforced by `quarantine.spec.ts`, not by convention.
 * If you are adding an import from outside that directory, you are doing
 * something the extraction will have to undo. Reconsider.
 */
export const GREYBOX_ALLOWLIST = [
  'tests/streaming-greybox/output-profile-sharing.spec.ts',
  'tests/streaming-greybox/ownership-lease.spec.ts',
];

export interface GreyboxRedis {
  get(key: string): Promise<string | null>;
  del(key: string): Promise<number>;
  keys(pattern: string): Promise<string[]>;
}

export function greyboxRedis(): GreyboxRedis { /* per Step 2's branch */ }
```

- [ ] **Step 4: Write the allowlist meta-test**

```ts
import { test, expect } from '@playwright/test';
import { readdir, readFile } from 'node:fs/promises';
import { GREYBOX_ALLOWLIST } from '../../fixtures/greybox/redis';

test('only allowlisted specs import the grey-box Redis helper', async () => {
  const root = new URL('../..', import.meta.url).pathname;
  const importers: string[] = [];

  async function walk(dir: string, rel: string): Promise<void> {
    for (const entry of await readdir(`${root}${dir}`, { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
      const childRel = rel ? `${rel}/${entry.name}` : entry.name;
      if (entry.isDirectory()) {
        await walk(`${dir}/${entry.name}`, childRel);
      } else if (entry.name.endsWith('.ts') && childRel !== 'fixtures/greybox/redis.ts') {
        const src = await readFile(`${root}${dir}/${entry.name}`, 'utf8');
        if (src.includes('greybox/redis')) importers.push(childRel);
      }
    }
  }
  await walk('', '');

  // A convention plus a README decays silently. This does not.
  expect(importers.sort()).toEqual([...GREYBOX_ALLOWLIST].sort());
});
```

- [ ] **Step 5: Prove the meta-test is not vacuous**

Add `import { greyboxRedis } from '../../fixtures/greybox/redis';` to
`e2e/tests/streaming/single-client.spec.ts`. Re-run the meta-test.
Expected: FAIL, naming `tests/streaming/single-client.spec.ts`. **Revert.**

- [ ] **Step 6: Commit**

Commit as `test(e2e): grey-box Redis helper and the meta-test that quarantines it`.

---

### Task 11: Row 11 — one transcode process per (channel, profile)

**Files:**
- Create: `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts`

- [ ] **Step 1: Write the test**

```ts
test('two clients on one output profile share a single transcode', async ({
  upstream,
  seed,
  api,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Output', tvgId: 'g4-output.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  const output = await api.json<{ id: number }>(
    await api.post('/api/core/outputprofiles/', {
      name: seed.generatedName('outputProfile'),
      command: 'ffmpeg',
      parameters: '-i pipe:0 -c copy -f mpegts pipe:1',
      is_active: true,
    }),
    'output profile'
  );

  const clients = [newStreamClient(), newStreamClient()];
  try {
    for (const c of clients) {
      await c.open(`/proxy/ts/stream/${channel.uuid}?output_profile=${output.id}`);
      expectTsAligned(await c.readPackets(20));
    }

    // Both clients are attached to the same output profile...
    const status = await readChannelStatus(api, channel.uuid);
    expect(status.client_count).toBe(2);
    expect(status.clients.every((c) => c.output_profile_id === output.id)).toBe(true);

    // ...and exactly one worker owns the transcode. The byte stream cannot
    // show this: two ffmpegs would produce byte-identical output. Only the
    // owner lock distinguishes "shared" from "duplicated", which is why this
    // row is in the quarantine.
    const owners = await greyboxRedis().keys(
      `*output*owner*${channel.id}*`
    );
    expect(owners).toHaveLength(1);
  } finally {
    await Promise.all(clients.map((c) => c.close().catch(() => {})));
  }
});
```

- [ ] **Step 2: Confirm the key pattern against the product**

Read `apps/proxy/live_proxy/redis_keys.py`, `RedisKeys.output_buffer_owner`,
and replace the wildcard pattern above with the exact key. A wildcard that
matches nothing would make `toHaveLength(1)` fail loudly, but a wildcard that
matches two unrelated keys would pass for the wrong reason.

- [ ] **Step 3: Run it, then prove it is not vacuous**

Run: `cd e2e && npx playwright test --project=streaming-greybox output-profile-sharing`
Expected: PASS.

Then change the assertion to `toHaveLength(2)` and confirm it FAILS. **Revert.**

- [ ] **Step 4: Commit**

Commit as `test(e2e): output profile is shared per (channel, profile) (G4 row 11)`.

---

### Task 12: Row 12 — the flagship: the ownership lease is not fenced

Implements D11. This is the defect the relay extraction most needs pinned, and
the task most likely to end in an honest gap rather than a test.

**Files:**
- Create: `e2e/tests/streaming-greybox/ownership-lease.spec.ts`
- Modify: `e2e/COVERAGE.md` (new row, `known-bug`)

- [ ] **Step 1: Write the test asserting CORRECT behaviour**

```ts
// Asserts the behaviour Dispatcharr SHOULD have. It is expected to fail today:
// StreamBuffer.add_chunk() writes with no ownership check and no fencing
// token, and the lease fails open in three places. Two owners can therefore
// interleave chunks at alternating monotonic indices while every consistency
// check still passes — a spliced stream that decodes and looks correct.
//
// Marked test.fail() rather than skipped: skipping loses the information.
// When someone fences the lease, this goes red the other way and says so.
test.fail('only one worker writes to a channel buffer at a time', async ({
  upstream,
  seed,
  api,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G4 Lease', tvgId: 'g4-lease.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  await streamClient.open(`/proxy/ts/stream/${channel.uuid}`);
  expectTsAligned(await streamClient.readPackets(100));

  const before = await readChannelStatus(api, channel.uuid);
  // NOT toBeTruthy(). channel_status.py falls back to the literal string
  // 'unknown' when the owner metadata key is absent, and 'unknown' is truthy.
  // Without this guard the final assertion below compares 'unknown' to
  // 'unknown' and reports success while proving nothing about the lease —
  // a vacuous pass on the most serious defect in the system, inside the very
  // test written to catch it.
  expect(
    before.owner,
    'no worker owns this channel yet; the test has nothing to observe'
  ).not.toBe('unknown');

  // Drop the lease out from under the running owner. The owner does not hold
  // a fencing token, so it keeps writing; a second worker is free to claim
  // the key and start writing too.
  const redis = greyboxRedis();
  await redis.del(`live:channel:${channel.id}:owner`);

  // Bytes are still flowing, so the original owner has not stopped...
  await expect
    .poll(async () => (await readChannelStatus(api, channel.uuid)).total_bytes, {
      timeout: 30_000,
    })
    .toBeGreaterThan(before.total_bytes);

  // ...and no second worker should have claimed ownership while that is true.
  const after = await readChannelStatus(api, channel.uuid);
  expect(
    after.owner,
    'a second worker claimed the lease while the first was still writing'
  ).toBe(before.owner);
});
```

- [ ] **Step 2: Run it and read the result carefully**

Run: `cd e2e && npx playwright test --project=streaming-greybox ownership-lease`

Three possible outcomes, and they mean different things:

1. **Reported as an expected failure** — the defect reproduces. This is the
   result the spec predicts. Proceed to Step 3.
2. **Reported as an unexpected pass** — the original owner re-acquired the key
   before any other worker noticed, so the test does not discriminate. Do not
   leave it: it would sit green forever proving nothing. Go to Step 4.
3. **Errors rather than failing** — the key name is wrong. Confirm it against
   `RedisKeys.channel_owner` and re-run.

- [ ] **Step 3: If it reproduces, file the issue**

`gh issue create --repo D10Scot/Dispatcharr` — the explicit `--repo` flag is
mandatory. Title it for the defect, not the test. Link the failing assertion,
name `StreamBuffer.add_chunk` and the three fail-open sites, and state the
consequence: readers decode a spliced stream with every consistency check
passing. Reference the issue number in a comment above `test.fail()`.

- [ ] **Step 4: If it does not discriminate, record a gap — do not fake it**

Delete the test. Add a row to `COVERAGE.md` with status `todo` and a comment
naming exactly what was attempted and why it could not be provoked from
outside the container. A test that passes for the wrong reason is worse than
an acknowledged gap, because it reads as coverage of the most serious defect
in the system.

- [ ] **Step 5: Commit**

Commit as `test(e2e): pin the un-fenced ownership lease (G4 row 12)` — or, on
the Step 4 branch, `docs(e2e): record the ownership lease as an unprovable gap`.

---

### Task 13: Coverage inventory and documentation

**Files:**
- Modify: `e2e/COVERAGE.md`, `e2e/README.md`

- [ ] **Step 1: Move every G4 row to `done`**

Nine rows. Split the single "Stream Profile: Redirect / Proxy / FFmpeg" row
into three, matching the three tests. Add row 12 with status `known-bug` and
its issue link, or `todo` with the gap note if Task 12 took the Step 4 branch.

- [ ] **Step 2: List the spec files under each row**

Follow the existing format — the G1 and G2 blocks at the bottom of the file
name the specs covering their rows. Do the same for G4's.

- [ ] **Step 3: Document the three projects**

In `e2e/README.md`: what each project is for, why `streaming-greybox` runs one
worker and must be run alone locally, and that the quarantine is enforced by a
meta-test rather than by convention.

- [ ] **Step 4: Verify the whole suite**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run each of the three projects in turn against a fresh container. Record actual
wall-clock per project and compare against the spec's estimates (~4 / ~7 / ~3
minutes). Report any that materially exceed them rather than quietly accepting.

- [ ] **Step 5: Commit**

Commit as `docs(e2e): record G4 coverage`.

---

## Self-Review

**Spec coverage.** D1 → Task 3. D2 → Tasks 3, 10. D3 → Task 1. D4 → Task 10
Step 1–2. D5 → Task 10 Steps 4–5. D6 → Task 2. D7 → Task 7. D8 → Task 9.
D9 → Task 6. D10 → Task 6. D11 → Task 12. D12 → Tasks 9, 12. D13 → Global
Constraints. D14, D15 → Global Constraints, applied in every task.
Test inventory rows 1–12 → Tasks 4, 5, 6, 7, 8, 9, 11, 12.

**Known deferrals, stated rather than hidden.** Task 9 Step 1 requires reading
the settings registry for `buffering_speed`'s API shape, and Task 11 Step 2
requires reading `RedisKeys.output_buffer_owner`. Both are "read this file and
write down what it says" steps rather than placeholders — the alternative was
inventing a key name and presenting it as fact, which is the failure mode this
programme has already caught four times.

**Type consistency.** `Stream`, `StreamOverrides`, `UpstreamChannelOptions`,
`ChannelStatus`, `GreyboxRedis` are defined in Tasks 1, 2 and 10 before their
first use in Tasks 4 onward. `lockedProfile()` and `newStreamClient()` are
local helpers used across Tasks 4–12; they are defined in Task 4 and must be
extracted to a shared `e2e/tests/streaming/helpers.ts` at first reuse in Task
5 rather than copy-pasted.
