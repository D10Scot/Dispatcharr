# G8 XC Provider Emulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the G2 fake upstream provider to speak Xtream Codes — `player_api.php`, a VOD and series catalogue served as a finite Range-capable file, and catch-up URLs in both layouts — and ship five Dispatcharr-facing plumbing proofs that the wiring works.

**Architecture:** Everything lives under the existing `/s/<id>` scenario prefix in the existing `e2e-upstream` container, so an XC `M3UAccount`'s `server_url` is the scenario's `internal` base and no new origin, port, container, network, Playwright project or CI job is introduced. The XC surface goes in new leaf modules under `e2e-upstream/src/xc/`; `src/server.ts` gains exactly one delegation, placed after all its existing branches and before its final 404. The looping TS asset serves live and catch-up playback unchanged; a second, finite MP4 asset with real `Range`/206/`Content-Range`/416 handling serves VOD and series playback.

**Tech Stack:** Node 24, TypeScript 5.7.2 (strict, `module: NodeNext`), vitest 3.2.7, Node's built-in `node:http` (no framework), ffmpeg (build-time only), Docker, Playwright 1.62.1.

**Spec:** `docs/superpowers/specs/2026-08-29-e2e-xc-provider-emulation-design.md`

## Global Constraints

- **G8 is a build. It ships five plumbing proofs and stops.** Anything in the spec's Non-goals belongs to G9 or G10. If a task tempts you into asserting product *behaviour* rather than *wiring*, that is the temptation that made G5 unshippable — write it down as a `COVERAGE.md` row for G9/G10 instead.
- **Node's standard library only** for the server. No express, fastify, koa. `package.json` has zero runtime dependencies and must keep zero.
- **TypeScript strict mode**, `"module": "NodeNext"`, `"moduleResolution": "nodenext"`. Intra-package imports carry the `.js` extension (`./errors.js`), including from `test/` into `src/`.
- **`.github/workflows/e2e-tests.yml`, `e2e/playwright.config.ts` and `scripts/e2e_up.sh` are NOT edited.** No new project, no new CI job, no new container or port. The `upstream` CI job already runs `e2e-upstream`'s vitest with no `needs: build` and picks up new test files automatically; the provider image is already built in `build` from `e2e-upstream/Dockerfile`.
- **Every `FROM` in a Dockerfile is `image:tag@sha256:<digest>`.** Task 5 adds no new base image — it extends the existing `asset` builder stage, which is already digest-pinned. Do not add one.
- **No product code is modified.** Not `apps/`, not `core/`, not `dispatcharr/`. Defects found are recorded as `COVERAGE.md` rows for G9/G10 (spec D25), not filed and not patched.
- **Credentials for an XC account go on the model fields and the URL path/query the XC protocol defines — never appended to `server_url` as `credentialQuery`.** `normalize_server_url` strips the query, so they would silently vanish. This is the exact inverse of the standard-M3U rule G2 documented.
- **The scenario base path is `/s/<id>`.** An XC `server_url` is `scenario.internal` verbatim.
- **Validate at the door.** Every new request field is checked in `parseScenarioRequest` / `parseFaultRequest` and rejected with a `BadRequestError` naming the offending field, in the style already in `src/scenario.ts` and `src/faults.ts`.
- **`ScenarioLog` keeps its four kinds** — `request`, `open`, `close`, `fault`. G4's tests read this log; a fifth kind breaks them. Everything G8 needs to record fits in a `request` entry's `path` (the PATH form's segments) plus its search string.
- **The default catalogue is identical across scenarios and aliases across parallel workers**, and worse than G2's channel catalogue does: `VODCategory` is unique on `(name, category_type)` globally, and `Movie`/`Series` are matched across *all* accounts by TMDB → IMDB → `(name, year)`. Every Playwright proof passes explicitly generated names and asserts on fields, never on counts that are not scoped to a generated name.
- **Naming:** "scenario", "fault", "upstream provider" are the canonical terms (root `CONTEXT.md`). An XC *category* maps to a Dispatcharr **Channel Group** for live and a **VOD Category** for VOD/series — never call either a "profile"; that word already means three other things.
- **Commit after every task.** Stage in one shell call, commit in the next — a `PreToolUse` hook rejects `git add` and `git commit` in the same Bash invocation.

## File structure

New, under `e2e-upstream/`:

| File | Responsibility |
|---|---|
| `src/xc/envelope.ts` | The `player_api.php` authentication envelope: `user_info` / `server_info` and their defaults |
| `src/xc/catalogue.ts` | The eight action payloads, rendered from a `Scenario`'s declared catalogue |
| `src/xc/catchup.ts` | Catch-up timestamp shapes, and parsing a PATH or QUERY catch-up request into recorded parameters |
| `src/xc/router.ts` | The XC route table: `player_api.php`, `live/…`, `movie/…`, `series/…`, `timeshift/…`, `streaming/timeshift.php` |
| `src/vod-asset.ts` | Loading a finite asset, and serving it with `Range`, 206, `Content-Range` and 416 |
| `scripts/make-vod-asset.sh` | Build-time generation of `assets/vod.mp4` |
| `test/xc-envelope.test.ts`, `test/xc-catalogue.test.ts`, `test/xc-router.test.ts`, `test/xc-catchup.test.ts`, `test/vod-asset.test.ts`, `test/xc-faults.test.ts` | One vitest file per unit above |

Modified: `src/scenario.ts` (catalogue declaration), `src/faults.ts` (four faults), `src/server.ts` (one delegation), `Dockerfile` (second asset), `README.md`; `e2e/fixtures/{upstream,types,seed}.ts`; `e2e/README.md`; `e2e/COVERAGE.md`.

New Playwright specs: `e2e/tests/seeded/xc-ingest.spec.ts`, `e2e/tests/seeded/vod-catalogue-ingest.spec.ts`, `e2e/tests/streaming/vod-byte-read.spec.ts`, `e2e/tests/streaming/catchup-path-layout.spec.ts`, `e2e/tests/streaming/catchup-cascade.spec.ts`.

---

### Task 1: Scenario declaration for XC, categories and the VOD/series catalogue

The whole build hangs off this shape, and nothing else can be written until the types exist. No routes yet: this task only teaches `ScenarioRegistry` what a catalogue is and teaches `parseScenarioRequest` to reject a malformed one by name.

**Files:**
- Modify: `e2e-upstream/src/scenario.ts`
- Test: `e2e-upstream/test/scenario.test.ts`

**Interfaces:**
- Consumes: `BadRequestError` from `src/errors.js`; the existing `ChannelSpec`, `ScenarioRequest`, `Scenario`, `parseScenarioRequest`, `ScenarioRegistry`.
- Produces, from `src/scenario.ts`:
  - `interface CategorySpec { id: number; name: string }`
  - `interface MovieSpec { id: number; name: string; year: number | null; categoryId: number; containerExtension: string; tmdbId: string | null; imdbId: string | null }`
  - `interface EpisodeSpec { id: number; title: string; episodeNum: number; containerExtension: string }`
  - `interface SeasonSpec { number: number; episodes: EpisodeSpec[] }`
  - `interface SeriesSpec { id: number; name: string; categoryId: number; seasons: SeasonSpec[] }`
  - `ChannelSpec` gains `categoryId: number`
  - `Scenario` gains `xc: boolean`, `liveCategories: CategorySpec[]`, `vodCategories: CategorySpec[]`, `seriesCategories: CategorySpec[]`, `vod: MovieSpec[]`, `series: SeriesSpec[]`, `account: AccountOverrides`
  - `interface AccountOverrides { userInfo?: Record<string, unknown>; serverInfo?: Record<string, unknown> }`

- [ ] **Step 1: Write the failing tests**

Append to `e2e-upstream/test/scenario.test.ts`:

```ts
describe('XC scenario declaration', () => {
  it('defaults to a non-XC scenario with no VOD or series catalogue', () => {
    const scenario = new ScenarioRegistry().create({});
    expect(scenario.xc).toBe(false);
    expect(scenario.vod).toEqual([]);
    expect(scenario.series).toEqual([]);
  });

  it('gives an XC scenario one movie, one series with one episode, and one category of each kind', () => {
    const scenario = new ScenarioRegistry().create({
      xc: true,
      username: 'u',
      password: 'p',
    });

    expect(scenario.liveCategories).toEqual([{ id: 1, name: 'E2E' }]);
    expect(scenario.vodCategories).toEqual([{ id: 1, name: 'E2E Movies' }]);
    expect(scenario.seriesCategories).toEqual([{ id: 1, name: 'E2E Series' }]);
    expect(scenario.vod).toHaveLength(1);
    expect(scenario.vod[0]).toMatchObject({ id: 1, name: 'Fake Movie 1', containerExtension: 'mp4' });
    expect(scenario.series).toHaveLength(1);
    expect(scenario.series[0].seasons).toEqual([
      {
        number: 1,
        episodes: [
          { id: 1, title: 'Fake Series 1 S01E01', episodeNum: 1, containerExtension: 'mp4' },
        ],
      },
    ]);
  });

  it('gives every default movie an explicit year', () => {
    // Movie identity across accounts falls back to (name, year) when there is
    // no TMDB or IMDB id, so a null year would make two workers' default
    // movies collide on (name, None) *and* would make the collision depend on
    // ingest-side year inference from the title. Declared, not inferred.
    const scenario = new ScenarioRegistry().create({ xc: true, username: 'u', password: 'p' });
    expect(scenario.vod[0].year).toEqual(expect.any(Number));
  });

  it('places every default channel in live category 1', () => {
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    expect(scenario.channels.map((c) => c.categoryId)).toEqual([1, 1]);
  });

  it('rejects xc: true without a username', () => {
    // credentialsMatch() returns true whenever username is undefined, so an
    // XC scenario with no credentials accepts anything — and every auth fault
    // written against it passes vacuously.
    expect(() => parseScenarioRequest({ xc: true })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ xc: true })).toThrow(/username/);
  });

  it('rejects a duplicate movie id, series id, episode id or category id by name', () => {
    const dupes: [Record<string, unknown>, RegExp][] = [
      [{ vod: [{ id: 1, name: 'a' }, { id: 1, name: 'b' }] }, /vod/],
      [{ series: [{ id: 2, name: 'a', seasons: [] }, { id: 2, name: 'b', seasons: [] }] }, /series/],
      [{ vodCategories: [{ id: 3, name: 'a' }, { id: 3, name: 'b' }] }, /vodCategories/],
      [
        {
          series: [
            {
              id: 1,
              name: 'a',
              seasons: [
                { number: 1, episodes: [{ id: 9, title: 'x', episodeNum: 1 }] },
                { number: 2, episodes: [{ id: 9, title: 'y', episodeNum: 1 }] },
              ],
            },
          ],
        },
        /episode/,
      ],
    ];
    for (const [body, pattern] of dupes) {
      expect(() => parseScenarioRequest(body)).toThrow(pattern);
    }
  });

  it('rejects a movie or series whose categoryId names no declared category', () => {
    // Silently falling through to Uncategorized would make a typo'd
    // categoryId look like Dispatcharr's category gating misbehaving.
    expect(() =>
      parseScenarioRequest({ vodCategories: [{ id: 1, name: 'a' }], vod: [{ id: 1, name: 'm', categoryId: 7 }] })
    ).toThrow(/categoryId 7/);
  });

  it('rejects control characters in a movie, series, episode or category name', () => {
    expect(() => parseScenarioRequest({ vod: [{ id: 1, name: 'a\nb' }] })).toThrow(
      /control characters/
    );
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd e2e-upstream && npm ci && npx vitest run test/scenario.test.ts`
Expected: FAIL — `scenario.xc` is `undefined`, `parseScenarioRequest` throws nothing.

- [ ] **Step 3: Add the catalogue types to `src/scenario.ts`**

Insert after the existing `ChannelSpec` interface, and add `categoryId` to `ChannelSpec`:

```ts
export interface ChannelSpec {
  id: number;
  name: string;
  tvgId: string;
  logo: string | null;
  /**
   * The XC live category this channel belongs to. Defaults to 1, which is
   * the default `liveCategories` entry, so the M3U playlist's existing
   * `group-title="E2E"` is unchanged for every pre-G8 scenario.
   */
  categoryId: number;
}

export interface CategorySpec {
  id: number;
  name: string;
}

export interface MovieSpec {
  id: number;
  name: string;
  /**
   * Always declared, never left to inference. With no TMDB or IMDB id,
   * `apps/vod/tasks.py` identifies a movie across *all* accounts by
   * `(name, year)` — so a null year both widens the cross-worker collision
   * and makes the row's identity depend on the ingest side's title parsing.
   */
  year: number | null;
  categoryId: number;
  /** The extension in the playback URL, so it must match what we serve. */
  containerExtension: string;
  tmdbId: string | null;
  imdbId: string | null;
}

export interface EpisodeSpec {
  id: number;
  title: string;
  episodeNum: number;
  containerExtension: string;
}

export interface SeasonSpec {
  number: number;
  episodes: EpisodeSpec[];
}

export interface SeriesSpec {
  id: number;
  name: string;
  categoryId: number;
  seasons: SeasonSpec[];
}

/**
 * Per-scenario overrides merged over the defaults in `src/xc/envelope.ts`.
 * Deliberately untyped beyond `Record<string, unknown>`: a test that wants
 * to see what Dispatcharr does with a garbage `exp_date` or an unknown
 * `timezone` must be able to send exactly that.
 */
export interface AccountOverrides {
  userInfo?: Record<string, unknown>;
  serverInfo?: Record<string, unknown>;
}
```

Extend `ScenarioRequest` and `Scenario`:

```ts
export interface ScenarioRequest {
  channels?: number | ChannelSpec[];
  username?: string;
  password?: string;
  maxConnections?: number;
  rate?: number;
  xc?: boolean;
  liveCategories?: CategorySpec[];
  vodCategories?: CategorySpec[];
  seriesCategories?: CategorySpec[];
  vod?: number | MovieSpec[];
  series?: number | SeriesSpec[];
  account?: AccountOverrides;
}

export interface Scenario {
  id: string;
  channels: ChannelSpec[];
  username?: string;
  password?: string;
  maxConnections: number | null;
  rate: number;
  /** When false, every XC route 404s for this scenario. */
  xc: boolean;
  liveCategories: CategorySpec[];
  vodCategories: CategorySpec[];
  seriesCategories: CategorySpec[];
  vod: MovieSpec[];
  series: SeriesSpec[];
  account: AccountOverrides;
}
```

- [ ] **Step 4: Add the defaults**

Alongside the existing `defaultChannels`, and update it to stamp `categoryId: 1`:

```ts
const DEFAULT_LIVE_CATEGORY: CategorySpec = { id: 1, name: 'E2E' };
const DEFAULT_VOD_CATEGORY: CategorySpec = { id: 1, name: 'E2E Movies' };
const DEFAULT_SERIES_CATEGORY: CategorySpec = { id: 1, name: 'E2E Series' };

/**
 * Fixed, not derived from the clock: a year that changed between two runs
 * would change a movie's cross-account identity key and make a rerun against
 * a non-reset container create a second Movie row instead of matching the
 * first.
 */
const DEFAULT_MOVIE_YEAR = 2020;

function defaultMovies(count: number): MovieSpec[] {
  return Array.from({ length: count }, (_unused, index) => {
    const n = index + 1;
    return {
      id: n,
      name: `Fake Movie ${n}`,
      year: DEFAULT_MOVIE_YEAR,
      categoryId: DEFAULT_VOD_CATEGORY.id,
      containerExtension: 'mp4',
      tmdbId: null,
      imdbId: null,
    };
  });
}

function defaultSeries(count: number): SeriesSpec[] {
  return Array.from({ length: count }, (_unused, index) => {
    const n = index + 1;
    return {
      id: n,
      name: `Fake Series ${n}`,
      categoryId: DEFAULT_SERIES_CATEGORY.id,
      seasons: [
        {
          number: 1,
          episodes: [
            {
              id: n,
              title: `Fake Series ${n} S01E01`,
              episodeNum: 1,
              containerExtension: 'mp4',
            },
          ],
        },
      ],
    };
  });
}
```

In `ScenarioRegistry.create`, resolve each field the same way `channels` already is, and default `vod`/`series` to **one when `xc` is true and zero otherwise** — a non-XC scenario has no route that could serve a catalogue, so materialising one would only be a way to trip over it later:

```ts
const xc = request.xc ?? false;
const scenario: Scenario = {
  id: randomUUID(),
  channels,
  username: request.username,
  password: request.password,
  maxConnections: request.maxConnections ?? null,
  rate: request.rate ?? 1,
  xc,
  liveCategories: request.liveCategories ?? [DEFAULT_LIVE_CATEGORY],
  vodCategories: request.vodCategories ?? [DEFAULT_VOD_CATEGORY],
  seriesCategories: request.seriesCategories ?? [DEFAULT_SERIES_CATEGORY],
  vod: Array.isArray(request.vod) ? request.vod : defaultMovies(request.vod ?? (xc ? 1 : 0)),
  series: Array.isArray(request.series)
    ? request.series
    : defaultSeries(request.series ?? (xc ? 1 : 0)),
  account: request.account ?? {},
};
```

- [ ] **Step 5: Add the validators**

`parseScenarioRequest` gains, in the same shape as the existing `channels` block. Note the ordering constraint: categories must be parsed **before** the items that reference them.

```ts
function parseCategories(value: unknown, field: string): CategorySpec[] {
  if (!Array.isArray(value)) {
    throw new BadRequestError(`'${field}' must be an array of { id, name }`);
  }
  const ids = new Set<number>();
  return value.map((entry) => {
    if (typeof entry !== 'object' || entry === null) {
      throw new BadRequestError(`'${field}' entries must be objects with an id and a name`);
    }
    const v = entry as Record<string, unknown>;
    if (!isNonNegativeInteger(v.id) || typeof v.name !== 'string') {
      throw new BadRequestError(
        `'${field}' entries must each have a non-negative integer id and a string name`
      );
    }
    if (ids.has(v.id)) {
      throw new BadRequestError(`'${field}' contains more than one entry with id ${v.id}`);
    }
    ids.add(v.id);
    assertNoControlChars(v.name, `${field}.name`);
    return { id: v.id, name: v.name };
  });
}
```

and, for movies and series, a check that every `categoryId` names a declared category:

```ts
function assertKnownCategory(categoryId: number, categories: CategorySpec[], field: string): void {
  if (!categories.some((c) => c.id === categoryId)) {
    // Falling through to Dispatcharr's "Uncategorized" bucket would make a
    // typo here read as the product's category gating misbehaving — the
    // exact confusion this validate-at-the-door pass exists to prevent.
    throw new BadRequestError(
      `'${field}' references categoryId ${categoryId}, which no declared category has`
    );
  }
}
```

Write `parseMovies(value, categories)` and `parseSeries(value, categories)` in the same style: reject a non-array; require `id` (non-negative integer, unique within the array) and `name` (string, no control characters); default `year` to `null`, `categoryId` to the first declared category's id, `containerExtension` to `'mp4'`, `tmdbId`/`imdbId` to `null`; for a series require `seasons` to be an array of `{ number, episodes }` with `number` a non-negative integer, and require every `episodes` entry to have a unique-across-the-whole-series `id`, an integer `episodeNum` and a string `title`. Every rejection names the field.

Finally, the XC credential rule, next to the existing password check:

```ts
if (body.xc !== undefined) {
  if (typeof body.xc !== 'boolean') {
    throw new BadRequestError("'xc' must be a boolean");
  }
  request.xc = body.xc;
}

// `credentialsMatch` treats an undefined username as "accept anything", so an
// XC scenario without credentials would authenticate every request and make
// `auth-failure` and `xc-auth-envelope` pass vacuously against it.
if (request.xc && request.username === undefined) {
  throw new BadRequestError("'xc' requires 'username'; an XC provider with no credentials cannot reject any");
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run test/scenario.test.ts && npm run typecheck`
Expected: PASS, and no type errors. The existing `server.test.ts` and `playlist.test.ts` must still pass — run `npx vitest run` to confirm the `categoryId` addition broke nothing.

- [ ] **Step 7: Commit**

```bash
git add e2e-upstream/src/scenario.ts e2e-upstream/test/scenario.test.ts
```

then, in a separate call:

```bash
git commit -m "feat(e2e-upstream): declare XC, categories and the VOD/series catalogue on a scenario"
```

---

### Task 2: The XC route seam and the account envelope

Adds the one delegation `src/server.ts` will ever gain, and the first route behind it. Deliberately its own task: if the seam is wrong — placed before the control routes, or swallowing a non-XC scenario's 404 message — every later task inherits the mistake.

**Files:**
- Create: `e2e-upstream/src/xc/envelope.ts`, `e2e-upstream/src/xc/router.ts`
- Modify: `e2e-upstream/src/server.ts`
- Test: `e2e-upstream/test/xc-envelope.test.ts`, `e2e-upstream/test/xc-router.test.ts`

**Interfaces:**
- Consumes: `Scenario`, `AccountOverrides` from `src/scenario.js`; `ScenarioLog` from `src/log.js`; `sendJson` from `src/server.js`.
- Produces:
  - `src/xc/envelope.ts`: `renderAccountEnvelope(scenario: Scenario, now: Date, host: string): Record<string, unknown>`
  - `src/xc/router.ts`: `interface XcContext { scenario: Scenario; req: IncomingMessage; res: ServerResponse; url: URL; subPath: string; log(status: number): void }` and `handleXc(context: XcContext): Promise<boolean>` — resolves `true` when it answered, `false` when the sub-path is not an XC route.

- [ ] **Step 1: Write the failing tests**

`e2e-upstream/test/xc-envelope.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario.js';
import { renderAccountEnvelope } from '../src/xc/envelope.js';

const scenario = () =>
  new ScenarioRegistry().create({ xc: true, username: 'user', password: 'pass' });

describe('renderAccountEnvelope', () => {
  it('carries every user_info and server_info key get_account_info() copies', () => {
    const envelope = renderAccountEnvelope(scenario(), new Date('2026-08-29T12:00:00Z'), 'h:8080');
    const userInfo = envelope.user_info as Record<string, unknown>;
    const serverInfo = envelope.server_info as Record<string, unknown>;

    // core/xtream_codes.py, Client.get_account_info — this is the exact set it
    // copies into M3UAccountProfile.custom_properties. A key missing here is a
    // key Dispatcharr silently stores as null.
    for (const key of [
      'username', 'password', 'message', 'auth', 'status', 'exp_date', 'is_trial',
      'active_cons', 'created_at', 'max_connections', 'allowed_output_formats',
    ]) {
      expect(userInfo).toHaveProperty(key);
    }
    for (const key of [
      'url', 'port', 'https_port', 'server_protocol', 'rtmp_port', 'timezone',
      'timestamp_now', 'time_now',
    ]) {
      expect(serverInfo).toHaveProperty(key);
    }
  });

  it('declares timezone UTC so a catch-up timestamp is not converted', () => {
    // convert_timestamp_to_provider_tz returns its input unchanged for a falsy
    // value or exactly "UTC". Anything else makes every catch-up assertion
    // depend on the date the suite runs (DST).
    const envelope = renderAccountEnvelope(scenario(), new Date(), 'h:8080');
    expect((envelope.server_info as Record<string, unknown>).timezone).toBe('UTC');
  });

  it('emits exp_date as a numeric string in the future', () => {
    // M3UAccountProfile.save() re-parses this on every save via float(), then
    // datetime.fromisoformat(). A shape like "2026-12-31 00:00:00" parses as
    // neither and is dropped without a warning.
    const now = new Date('2026-08-29T12:00:00Z');
    const expDate = (renderAccountEnvelope(scenario(), now, 'h:8080').user_info as Record<string, unknown>)
      .exp_date;
    expect(typeof expDate).toBe('string');
    expect(Number(expDate)).toBeGreaterThan(now.getTime() / 1000);
  });

  it('echoes the scenario credentials and never emits a top-level error key', () => {
    // _make_request raises when a dict has no user_info AND an 'error' key;
    // emitting one on a success is how a provider accidentally fails auth.
    const envelope = renderAccountEnvelope(scenario(), new Date(), 'h:8080');
    expect((envelope.user_info as Record<string, unknown>).username).toBe('user');
    expect(envelope).not.toHaveProperty('error');
  });

  it('lets a scenario override any user_info or server_info field', () => {
    const registry = new ScenarioRegistry();
    const custom = registry.create({
      xc: true,
      username: 'u',
      account: { serverInfo: { timezone: 'Europe/Brussels' }, userInfo: { max_connections: '4' } },
    });
    const envelope = renderAccountEnvelope(custom, new Date(), 'h:8080');
    expect((envelope.server_info as Record<string, unknown>).timezone).toBe('Europe/Brussels');
    expect((envelope.user_info as Record<string, unknown>).max_connections).toBe('4');
  });
});
```

`e2e-upstream/test/xc-router.test.ts`:

```ts
import { describe, it, expect, afterEach } from 'vitest';
import { startServer, registry } from '../src/server.js';

let server: Awaited<ReturnType<typeof startServer>> | undefined;
afterEach(async () => {
  await server?.close();
  server = undefined;
});

async function xcScenario(overrides: Record<string, unknown> = {}) {
  server = await startServer(0);
  const base = `http://127.0.0.1:${server.port}`;
  const created = await (
    await fetch(`${base}/scenarios`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ xc: true, username: 'user', password: 'pass', ...overrides }),
    })
  ).json();
  return { base, id: created.id as string };
}

const auth = '?username=user&password=pass';

describe('the XC route seam', () => {
  it('answers player_api.php with an authentication envelope', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('application/json');
    const body = await res.json();
    expect(body.user_info.auth).toBe(1);
  });

  it('rejects wrong credentials with 401', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/player_api.php?username=user&password=wrong`);
    expect(res.status).toBe(401);
  });

  it('404s an XC route on a non-XC scenario, naming the missing opt-in', async () => {
    server = await startServer(0);
    const base = `http://127.0.0.1:${server.port}`;
    const created = await (
      await fetch(`${base}/scenarios`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
    ).json();
    const res = await fetch(`${base}/s/${created.id}/player_api.php`);
    expect(res.status).toBe(404);
    // Naming the mistake, not just refusing: a bare 404 here is
    // indistinguishable from the `not-found` fault or a typo'd scenario id.
    expect((await res.json()).error).toMatch(/xc: true/);
  });

  it('leaves the pre-existing control and provider routes untouched', async () => {
    const { base, id } = await xcScenario();
    expect((await fetch(`${base}/s/${id}/connections`)).status).toBe(200);
    expect((await fetch(`${base}/s/${id}/log`)).status).toBe(200);
    expect((await fetch(`${base}/s/${id}/playlist.m3u${auth}`)).status).toBe(200);
    // The seam must sit after every existing branch: reached earlier, it would
    // swallow /fault, /rate, /log and /connections.
    const fault = await fetch(`${base}/s/${id}/fault`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fault: 'dead-air', active: true }),
    });
    expect(fault.status).toBe(200);
  });

  it('still 404s an unknown sub-path with a message naming it', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/nonsense`);
    expect(res.status).toBe(404);
    expect((await res.json()).error).toContain('/nonsense');
  });

  it('records every XC request in the scenario log', async () => {
    const { base, id } = await xcScenario();
    await fetch(`${base}/s/${id}/player_api.php${auth}`);
    const log = await (await fetch(`${base}/s/${id}/log`)).json();
    expect(log).toContainEqual(
      expect.objectContaining({ kind: 'request', method: 'GET', status: 200, path: `/s/${id}/player_api.php` })
    );
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd e2e-upstream && npx vitest run test/xc-envelope.test.ts test/xc-router.test.ts`
Expected: FAIL — `Cannot find module '../src/xc/envelope.js'`.

- [ ] **Step 3: Write `src/xc/envelope.ts`**

```ts
import type { Scenario } from '../scenario.js';

const ONE_YEAR_SECONDS = 365 * 24 * 60 * 60;

/** XC panels emit `YYYY-MM-DD HH:MM:SS` for `time_now`. */
function sqlDateTime(date: Date): string {
  return date.toISOString().replace('T', ' ').slice(0, 19);
}

/**
 * The `player_api.php` handshake body.
 *
 * The key set is not a guess: it is exactly what
 * `core/xtream_codes.Client.get_account_info()` copies into
 * `M3UAccountProfile.custom_properties`. Two entries are load-bearing beyond
 * storage — `user_info.exp_date`, which `M3UAccountProfile.save()` re-parses
 * on every save as a unix timestamp or an ISO string, and
 * `server_info.timezone`, which drives `convert_timestamp_to_provider_tz` in
 * `apps/timeshift/helpers.py`.
 *
 * `user_info.auth` is emitted as 1 but is **never read by the product**:
 * `Client.authenticate()` checks only that `user_info` is truthy. The
 * `xc-auth-envelope` fault exists to make that observable.
 *
 * No top-level `error` key, ever: `_make_request` raises on a dict that has
 * an `error` key and no `user_info`, and a stray one on a success path is an
 * authentication failure with no obvious cause.
 */
export function renderAccountEnvelope(
  scenario: Scenario,
  now: Date,
  host: string
): Record<string, unknown> {
  const nowSeconds = Math.floor(now.getTime() / 1000);
  const [hostname, port = '8080'] = host.split(':');

  return {
    user_info: {
      username: scenario.username ?? '',
      password: scenario.password ?? '',
      message: 'dispatcharr-e2e-upstream',
      auth: 1,
      status: 'Active',
      exp_date: String(nowSeconds + ONE_YEAR_SECONDS),
      is_trial: '0',
      active_cons: '0',
      created_at: String(nowSeconds - ONE_YEAR_SECONDS),
      // Mirrors the scenario's real limit so a G9 test can make
      // M3UAccount.max_streams and the provider's declared limit disagree on
      // purpose. `null` (unlimited) has no XC spelling; 1 is the honest
      // default for a scenario that never declared one.
      max_connections: String(scenario.maxConnections ?? 1),
      allowed_output_formats: ['ts', 'm3u8'],
      ...(scenario.account.userInfo ?? {}),
    },
    server_info: {
      url: hostname,
      port,
      https_port: '443',
      server_protocol: 'http',
      rtmp_port: '0',
      // "UTC" and a falsy value are the only two values
      // convert_timestamp_to_provider_tz treats as "no conversion".
      timezone: 'UTC',
      timestamp_now: nowSeconds,
      time_now: sqlDateTime(now),
      ...(scenario.account.serverInfo ?? {}),
    },
  };
}
```

- [ ] **Step 4: Write `src/xc/router.ts`**

```ts
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Scenario } from '../scenario.js';
import { renderAccountEnvelope } from './envelope.js';

export interface XcContext {
  scenario: Scenario;
  req: IncomingMessage;
  res: ServerResponse;
  url: URL;
  /** The path with `/s/<id>` already stripped, e.g. `/player_api.php`. */
  subPath: string;
  /** Records a `request` entry against this scenario. */
  log(status: number): void;
  sendJson(status: number, body: unknown): void;
}

/**
 * Every path this module owns. `server.ts` uses it to tell "an XC route on a
 * scenario that never opted in" apart from "a typo" — the first gets a 404
 * naming the missing `xc: true`, the second falls through to the generic 404
 * naming the path.
 */
const XC_PATHS = [
  /^\/player_api\.php$/,
  /^\/live\/[^/]+\/[^/]+\/\d+\.ts$/,
  /^\/movie\/[^/]+\/[^/]+\/\d+\.[A-Za-z0-9]+$/,
  /^\/series\/[^/]+\/[^/]+\/\d+\.[A-Za-z0-9]+$/,
  /^\/timeshift\/[^/]+\/[^/]+\/[^/]+\/[^/]+\/\d+\.ts$/,
  /^\/streaming\/timeshift\.php$/,
];

export function looksLikeXcRoute(subPath: string): boolean {
  return XC_PATHS.some((pattern) => pattern.test(subPath));
}

/** Credentials as XC sends them: query params on the API, path segments on playback. */
export function xcCredentialsMatch(
  scenario: Scenario,
  username: string | null,
  password: string | null
): boolean {
  return username === (scenario.username ?? '') && password === (scenario.password ?? '');
}

export async function handleXc(context: XcContext): Promise<boolean> {
  const { scenario, url, subPath, log, sendJson } = context;

  if (subPath === '/player_api.php') {
    if (
      !xcCredentialsMatch(
        scenario,
        url.searchParams.get('username'),
        url.searchParams.get('password')
      )
    ) {
      log(401);
      sendJson(401, { error: 'bad credentials' });
      return true;
    }
    const host = context.req.headers.host ?? 'e2e-upstream:8080';
    log(200);
    sendJson(200, renderAccountEnvelope(scenario, new Date(), host));
    return true;
  }

  return false;
}
```

- [ ] **Step 5: Wire the seam into `src/server.ts`**

Add the import, and insert this block **immediately before** the final `sendJson(res, 404, { error: \`no route for ...\` })` in `handle()` — after every existing branch, so `/fault`, `/rate`, `/log` and `/connections` are matched first:

```ts
  // The XC surface (G8). Deliberately last: every pre-existing `/s/<id>/*`
  // route above — including the four control routes — must match before this
  // sees the path, or a scenario id containing an unlucky segment would have
  // its control calls answered by the XC router.
  const xcMatch = /^\/s\/([^/]+)(\/.*)$/.exec(url.pathname);
  if (xcMatch) {
    const scenario = registry.get(xcMatch[1]);
    if (scenario && looksLikeXcRoute(xcMatch[2])) {
      if (!scenario.xc) {
        // Named, not bare: without this a G9 author who forgot `xc: true`
        // reads a 404 and starts debugging Dispatcharr's XC client.
        logRequest(scenario, req, url, 404);
        sendJson(res, 404, {
          error: `scenario ${scenario.id} was not created with xc: true, so ${xcMatch[2]} is not served`,
        });
        return;
      }
      const handled = await handleXc({
        scenario,
        req,
        res,
        url,
        subPath: xcMatch[2],
        log: (status) => logRequest(scenario, req, url, status),
        sendJson: (status, body) => sendJson(res, status, body),
      });
      if (handled) return;
    }
  }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run && npm run typecheck`
Expected: PASS, whole suite. `server.test.ts`'s "unknown path 404s naming the path" must still pass — that is the assertion proving the seam did not swallow the generic 404.

- [ ] **Step 7: Commit**

```bash
git add e2e-upstream/src/xc e2e-upstream/src/server.ts e2e-upstream/test/xc-envelope.test.ts e2e-upstream/test/xc-router.test.ts
```

then:

```bash
git commit -m "feat(e2e-upstream): add the XC route seam and the player_api.php auth envelope"
```

---

### Task 3: The eight catalogue actions

The payload shape, not the endpoint list, is where this goal's hidden work is. The tests below assert **fields**, keyed to the consumer that reads each one, because a payload that satisfies `core/xtream_codes.Client` and not `apps/vod/tasks.py` produces a refresh that reports success and creates nothing.

**Files:**
- Create: `e2e-upstream/src/xc/catalogue.ts`
- Modify: `e2e-upstream/src/xc/router.ts`
- Test: `e2e-upstream/test/xc-catalogue.test.ts`

**Interfaces:**
- Consumes: `Scenario`, `CategorySpec`, `MovieSpec`, `SeriesSpec` from `src/scenario.js`.
- Produces, from `src/xc/catalogue.ts`:
  - `renderLiveCategories(scenario): unknown[]`
  - `renderLiveStreams(scenario, categoryId: string | null, opts: { tvArchive: (channelId: number) => boolean }): unknown[]`
  - `renderVodCategories(scenario): unknown[]`
  - `renderSeriesCategories(scenario): unknown[]`
  - `renderVodStreams(scenario, categoryId: string | null): unknown[]`
  - `renderSeries(scenario, categoryId: string | null): unknown[]`
  - `renderVodInfo(scenario, vodId: number): Record<string, unknown> | undefined`
  - `renderSeriesInfo(scenario, seriesId: number): Record<string, unknown> | undefined`

- [ ] **Step 1: Write the failing tests**

`e2e-upstream/test/xc-catalogue.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario.js';
import {
  renderLiveCategories,
  renderLiveStreams,
  renderSeries,
  renderSeriesCategories,
  renderSeriesInfo,
  renderVodCategories,
  renderVodInfo,
  renderVodStreams,
} from '../src/xc/catalogue.js';

const xc = (overrides = {}) =>
  new ScenarioRegistry().create({ xc: true, username: 'u', password: 'p', ...overrides });

describe('live actions', () => {
  it('renders categories as { category_id, category_name }', () => {
    // apps/m3u/tasks.py, refresh_m3u_account_groups: category_id becomes
    // ChannelGroupM3UAccount.custom_properties['xc_id'] and category_name
    // becomes the ChannelGroup name. Nothing else is read.
    expect(renderLiveCategories(xc())).toEqual([{ category_id: '1', category_name: 'E2E' }]);
  });

  it('renders every field collect_xc_streams reads', () => {
    const [stream] = renderLiveStreams(xc(), null, { tvArchive: () => true }) as Record<string, unknown>[];
    expect(stream).toMatchObject({
      stream_id: 1,
      name: 'Fake Channel 1',
      category_id: '1',
      epg_channel_id: 'fake-1.e2e',
      stream_type: 'live',
      num: 1,
      is_adult: 0,
      tv_archive: 1,
      tv_archive_duration: expect.any(Number),
    });
    expect(stream).toHaveProperty('stream_icon');
    expect(stream).toHaveProperty('added');
    expect(stream).toHaveProperty('custom_sid');
  });

  it('omits tv_archive entirely when the caller says so', () => {
    // The `no-tv-archive` fault. `str(stream.get("tv_archive", "0"))` means an
    // absent key is a real "no archive", which is what the self-heal pass in
    // rollup_channel_catchup_fields reacts to.
    const [stream] = renderLiveStreams(xc(), null, { tvArchive: () => false }) as Record<string, unknown>[];
    expect(stream).not.toHaveProperty('tv_archive');
    expect(stream).not.toHaveProperty('tv_archive_duration');
  });

  it('filters live streams by category_id when one is given', () => {
    const scenario = xc({
      liveCategories: [{ id: 1, name: 'A' }, { id: 2, name: 'B' }],
      channels: [
        { id: 1, name: 'one', tvgId: 'one.e2e', logo: null, categoryId: 1 },
        { id: 2, name: 'two', tvgId: 'two.e2e', logo: null, categoryId: 2 },
      ],
    });
    const streams = renderLiveStreams(scenario, '2', { tvArchive: () => true }) as Record<string, unknown>[];
    expect(streams).toHaveLength(1);
    expect(streams[0].stream_id).toBe(2);
  });
});

describe('VOD actions', () => {
  it('renders every field process_movie_batch reads', () => {
    const [movie] = renderVodStreams(xc(), null) as Record<string, unknown>[];
    expect(movie).toMatchObject({
      stream_id: 1,
      name: 'Fake Movie 1',
      category_id: '1',
      container_extension: 'mp4',
      year: 2020,
    });
    // Read by process_movie_batch and stored verbatim as
    // M3UMovieRelation.custom_properties['basic_data'].
    for (const key of ['stream_icon', 'rating', 'plot', 'genre', 'duration_secs', 'added']) {
      expect(movie).toHaveProperty(key);
    }
  });

  it('omits is_adult unless it is meaningful', () => {
    // process_movie_batch only sets Movie.is_adult when the key is present,
    // deliberately, so a sparse provider cannot clear a flag another provider
    // set. Emitting a default 0 would defeat that.
    const [movie] = renderVodStreams(xc(), null) as Record<string, unknown>[];
    expect(movie).not.toHaveProperty('is_adult');
  });

  it('renders vod_info with both info and movie_data', () => {
    // refresh_movie_advanced_data requires `'info' in vod_info` and reads
    // movie_data separately. A bare info dict is silently ignored.
    const info = renderVodInfo(xc(), 1)!;
    expect(info).toHaveProperty('info');
    expect(info).toHaveProperty('movie_data');
    expect((info.info as Record<string, unknown>).plot).toEqual(expect.any(String));
  });

  it('returns undefined for an unknown vod id', () => {
    expect(renderVodInfo(xc(), 999)).toBeUndefined();
  });
});

describe('series actions', () => {
  it('renders every field process_series_batch reads, with the movie/series key skew', () => {
    const [series] = renderSeries(xc(), null) as Record<string, unknown>[];
    expect(series).toMatchObject({ series_id: 1, name: 'Fake Series 1', category_id: '1' });
    // Series use `cover` (not stream_icon), `plot` (not description) and
    // `releaseDate` (not release_date) first. That skew is real, and
    // reproducing it is what makes the ingest test meaningful.
    expect(series).toHaveProperty('cover');
    expect(series).toHaveProperty('plot');
    expect(series).toHaveProperty('releaseDate');
    expect(series).not.toHaveProperty('stream_icon');
  });

  it('renders series_info with info and an object keyed by season number', () => {
    const info = renderSeriesInfo(xc(), 1)!;
    expect(info).toHaveProperty('info');
    const episodes = info.episodes as Record<string, unknown[]>;
    expect(Object.keys(episodes)).toEqual(['1']);
    expect(episodes['1'][0]).toMatchObject({
      id: '1',
      title: 'Fake Series 1 S01E01',
      episode_num: 1,
      container_extension: 'mp4',
    });
    expect((episodes['1'][0] as Record<string, unknown>).info).toEqual(
      expect.objectContaining({ plot: expect.any(String), duration_secs: expect.any(Number) })
    );
  });

  it('returns undefined for an unknown series id', () => {
    expect(renderSeriesInfo(xc(), 999)).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd e2e-upstream && npx vitest run test/xc-catalogue.test.ts`
Expected: FAIL — `Cannot find module '../src/xc/catalogue.js'`.

- [ ] **Step 3: Write `src/xc/catalogue.ts`**

Every renderer is a pure function of the scenario. The file's header must state the rule the whole build depends on:

```ts
/**
 * The eight `player_api.php` action payloads.
 *
 * The endpoint list is bounded by `core/xtream_codes.Client`. The **field
 * set** is not: it is bounded by the consumers, `apps/m3u/tasks.py`
 * (`collect_xc_streams`) and `apps/vod/tasks.py` (`process_movie_batch`,
 * `process_series_batch`, `batch_process_episodes`,
 * `refresh_movie_advanced_data`). Satisfying the client alone yields a
 * provider whose refresh reports success and creates nothing.
 *
 * `docs/superpowers/specs/2026-08-29-e2e-xc-provider-emulation-design.md`,
 * "Required XC payload shapes", is the derived list and is normative. Do not
 * add a field it does not name without adding the consumer that reads it.
 *
 * Category ids are emitted as **strings** because both consumers compare them
 * with `str(...)`: `collect_xc_streams` keys `enabled_category_ids` by
 * `str(props["xc_id"])`, and `process_movie_batch` looks up
 * `str(movie_data.get('category_id'))`. Stream and movie ids are emitted as
 * **numbers**, which is what real panels send and what `int()` accepts.
 */
```

Then:

```ts
import type { CategorySpec, MovieSpec, Scenario, SeriesSpec } from '../scenario.js';

/** Days of archive a channel advertises when `tv_archive` is on. */
export const DEFAULT_ARCHIVE_DAYS = 7;
/** Seconds; short, finite, and consistent with the VOD asset we actually serve. */
const MOVIE_DURATION_SECS = 5;

function renderCategories(categories: CategorySpec[]): unknown[] {
  return categories.map((category) => ({
    category_id: String(category.id),
    category_name: category.name,
    parent_id: 0,
  }));
}

export function renderLiveCategories(scenario: Scenario): unknown[] {
  return renderCategories(scenario.liveCategories);
}

export function renderVodCategories(scenario: Scenario): unknown[] {
  return renderCategories(scenario.vodCategories);
}

export function renderSeriesCategories(scenario: Scenario): unknown[] {
  return renderCategories(scenario.seriesCategories);
}

export interface LiveStreamOptions {
  /** False omits `tv_archive`/`tv_archive_duration` entirely (the `no-tv-archive` fault). */
  tvArchive(channelId: number): boolean;
}

export function renderLiveStreams(
  scenario: Scenario,
  categoryId: string | null,
  options: LiveStreamOptions
): unknown[] {
  return scenario.channels
    .filter((channel) => categoryId === null || String(channel.categoryId) === categoryId)
    .map((channel) => {
      const archive = options.tvArchive(channel.id);
      return {
        num: channel.id,
        name: channel.name,
        stream_type: 'live',
        stream_id: channel.id,
        stream_icon: channel.logo ?? '',
        epg_channel_id: channel.tvgId,
        added: '0',
        category_id: String(channel.categoryId),
        custom_sid: '',
        is_adult: 0,
        // `direct_source` is deliberately absent: collect_xc_streams builds
        // the playback URL itself from server_url and never reads it.
        ...(archive ? { tv_archive: 1, tv_archive_duration: DEFAULT_ARCHIVE_DAYS } : {}),
      };
    });
}

function movieEntry(movie: MovieSpec): Record<string, unknown> {
  return {
    num: movie.id,
    name: movie.name,
    stream_type: 'movie',
    stream_id: movie.id,
    stream_icon: '',
    rating: '7.5',
    rating_5based: 3.75,
    added: '0',
    category_id: String(movie.categoryId),
    container_extension: movie.containerExtension,
    plot: `${movie.name} — e2e fixture`,
    genre: 'E2E',
    duration_secs: MOVIE_DURATION_SECS,
    year: movie.year,
    ...(movie.tmdbId === null ? {} : { tmdb_id: movie.tmdbId }),
    ...(movie.imdbId === null ? {} : { imdb_id: movie.imdbId }),
    // `is_adult` is deliberately absent unless a scenario declares it:
    // process_movie_batch only writes Movie.is_adult when the key is present,
    // so that a sparse provider cannot clear a flag another provider set.
  };
}

export function renderVodStreams(scenario: Scenario, categoryId: string | null): unknown[] {
  return scenario.vod
    .filter((movie) => categoryId === null || String(movie.categoryId) === categoryId)
    .map(movieEntry);
}

export function renderVodInfo(
  scenario: Scenario,
  vodId: number
): Record<string, unknown> | undefined {
  const movie = scenario.vod.find((m) => m.id === vodId);
  if (!movie) return undefined;
  return {
    info: {
      plot: `${movie.name} — e2e fixture, detailed`,
      genre: 'E2E',
      rating: '7.5',
      duration_secs: MOVIE_DURATION_SECS,
      releasedate: movie.year === null ? '' : `${movie.year}-01-01`,
      director: 'E2E Director',
      actors: 'E2E Actor',
      backdrop_path: [],
      youtube_trailer: '',
      ...(movie.tmdbId === null ? {} : { tmdb_id: movie.tmdbId }),
      ...(movie.imdbId === null ? {} : { imdb_id: movie.imdbId }),
    },
    movie_data: movieEntry(movie),
  };
}

function seriesEntry(series: SeriesSpec): Record<string, unknown> {
  return {
    num: series.id,
    series_id: series.id,
    name: series.name,
    // `cover`, not `stream_icon`; `plot`, not `description`; `releaseDate`
    // before `release_date`. process_series_batch reads these keys and not
    // the movie ones — the skew is the product's, and reproducing it is the
    // point.
    cover: '',
    plot: `${series.name} — e2e fixture`,
    genre: 'E2E',
    rating: '8.0',
    releaseDate: '2020-01-01',
    last_modified: '0',
    category_id: String(series.categoryId),
    episode_run_time: '5',
  };
}

export function renderSeries(scenario: Scenario, categoryId: string | null): unknown[] {
  return scenario.series
    .filter((series) => categoryId === null || String(series.categoryId) === categoryId)
    .map(seriesEntry);
}

export function renderSeriesInfo(
  scenario: Scenario,
  seriesId: number
): Record<string, unknown> | undefined {
  const series = scenario.series.find((s) => s.id === seriesId);
  if (!series) return undefined;

  // An object keyed by season number, which is what a PHP panel's
  // json_encode produces for a non-contiguous array. batch_process_episodes
  // also accepts a JSON array; a scenario that wants that shape is G9's to
  // add, and this renderer is where it goes.
  const episodes: Record<string, unknown[]> = {};
  for (const season of series.seasons) {
    episodes[String(season.number)] = season.episodes.map((episode) => ({
      // A string, matching real panels and matching
      // `str(episode_data.get('id'))` on the ingest side.
      id: String(episode.id),
      episode_num: episode.episodeNum,
      title: episode.title,
      container_extension: episode.containerExtension,
      info: {
        plot: `${episode.title} — e2e fixture`,
        rating: '7.0',
        duration_secs: MOVIE_DURATION_SECS,
        air_date: '2020-01-01',
        movie_image: '',
        backdrop_path: [],
      },
    }));
  }

  return {
    info: {
      name: series.name,
      plot: `${series.name} — e2e fixture, detailed`,
      genre: 'E2E',
      rating: '8.0',
      releaseDate: '2020-01-01',
    },
    episodes,
  };
}
```

- [ ] **Step 4: Dispatch the actions in `src/xc/router.ts`**

Replace the `player_api.php` branch's tail so it dispatches on `action` after the credential check, keeping the no-action case as the envelope:

```ts
    const action = url.searchParams.get('action');
    const categoryId = url.searchParams.get('category_id');

    if (action === null) {
      log(200);
      sendJson(200, renderAccountEnvelope(scenario, new Date(), host));
      return true;
    }

    // The tvArchive predicate is a function, not a boolean, because the
    // `no-tv-archive` fault is channel-scopable — Task 7 replaces this
    // always-true stub with a FaultStore lookup.
    const listActions: Record<string, () => unknown[]> = {
      get_live_categories: () => renderLiveCategories(scenario),
      get_live_streams: () => renderLiveStreams(scenario, categoryId, { tvArchive: () => true }),
      get_vod_categories: () => renderVodCategories(scenario),
      get_vod_streams: () => renderVodStreams(scenario, categoryId),
      get_series_categories: () => renderSeriesCategories(scenario),
      get_series: () => renderSeries(scenario, categoryId),
    };

    const list = listActions[action];
    if (list) {
      log(200);
      sendJson(200, list());
      return true;
    }

    if (action === 'get_vod_info') {
      const info = renderVodInfo(scenario, Number(url.searchParams.get('vod_id')));
      log(info ? 200 : 404);
      // `Client.get_vod_info` requires a dict, so a 404 body is a dict too —
      // the product surfaces the HTTPError, not a shape error.
      sendJson(info ? 200 : 404, info ?? { error: 'no such vod_id' });
      return true;
    }

    if (action === 'get_series_info') {
      const info = renderSeriesInfo(scenario, Number(url.searchParams.get('series_id')));
      log(info ? 200 : 404);
      sendJson(info ? 200 : 404, info ?? { error: 'no such series_id' });
      return true;
    }

    // An unrecognised action is a test author's typo, not a provider state.
    // Naming the valid set is the same courtesy parseFaultRequest extends.
    log(400);
    sendJson(400, {
      error: `unknown action '${action}'; this provider serves ${Object.keys(listActions)
        .concat('get_vod_info', 'get_series_info')
        .join(', ')} and the no-action handshake`,
    });
    return true;
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add e2e-upstream/src/xc/catalogue.ts e2e-upstream/src/xc/router.ts e2e-upstream/test/xc-catalogue.test.ts
```

then:

```bash
git commit -m "feat(e2e-upstream): render the eight XC catalogue actions"
```

---

### Task 4: XC live playback

`/live/<user>/<pass>/<streamId>.ts` serves the same paced loop as `/stream/<id>.ts`, through the same `streamLoop`, so it inherits `maxConnections` accounting, `dead-air`, `slow-trickle`, `disconnect` and the HEAD probe behaviour that already work.

**Files:**
- Modify: `e2e-upstream/src/server.ts`, `e2e-upstream/src/xc/router.ts`
- Test: `e2e-upstream/test/xc-router.test.ts`

**Interfaces:**
- Consumes: `getAsset()`, `connections`, `faults`, `scenarioLog` and the existing stream-serving block from `src/server.ts`.
- Produces: `serveChannelStream(scenario, channelId, req, res, url): Promise<void>` exported from `src/server.ts` — the existing stream route's body, extracted verbatim so the two routes cannot drift.

- [ ] **Step 1: Write the failing tests**

Append to `e2e-upstream/test/xc-router.test.ts`:

```ts
describe('XC live playback', () => {
  it('serves TS on /live/<user>/<pass>/<id>.ts', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/live/user/pass/1.ts`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('video/mp2t');
    const reader = res.body!.getReader();
    const { value } = await reader.read();
    expect(value![0]).toBe(0x47);
    await reader.cancel();
  });

  it('rejects wrong path credentials with 401 and consumes no connection slot', async () => {
    const { base, id } = await xcScenario({ maxConnections: 1 });
    expect((await fetch(`${base}/s/${id}/live/user/wrong/1.ts`)).status).toBe(401);
    // A rejected request that had taken the slot would make every later
    // connection-limit assertion wrong for a reason that looks like broken
    // accounting.
    const live = await (await fetch(`${base}/s/${id}/connections`)).json();
    expect(live.live).toBe(0);
  });

  it('404s an unknown channel id', async () => {
    const { base, id } = await xcScenario();
    expect((await fetch(`${base}/s/${id}/live/user/pass/99.ts`)).status).toBe(404);
  });

  it('answers HEAD with 200 and no body, without consuming a slot', async () => {
    const { base, id } = await xcScenario({ maxConnections: 1 });
    const res = await fetch(`${base}/s/${id}/live/user/pass/1.ts`, { method: 'HEAD' });
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('video/mp2t');
    expect((await (await fetch(`${base}/s/${id}/connections`)).json()).live).toBe(0);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd e2e-upstream && npx vitest run test/xc-router.test.ts`
Expected: FAIL — `/live/...` 404s.

- [ ] **Step 3: Extract the stream-serving body from `src/server.ts`**

Move the whole block that currently runs after `const streamMatch = ...` — the six fault checks, the HEAD branch, the method check, `getAsset()`, the `LiveConnection` construction, `tryAcquire` and the `streamLoop` call — into an exported function, and have the existing route call it. Behaviour must be unchanged; this is a pure extraction, and the existing `server.test.ts` and `faults.test.ts` are the proof.

```ts
/**
 * Serves one channel's paced TS loop, with the full fault and admission
 * pipeline. Extracted from the `/s/<id>/stream/<n>.ts` route so the XC
 * `/live/<user>/<pass>/<n>.ts` route and the two catch-up routes serve
 * byte-identical streams through byte-identical fault handling. Three copies
 * of this pipeline would drift, and the drift would look like a product bug.
 *
 * Does NOT check that the channel id is one the scenario declared: the
 * pre-existing `/stream/<n>.ts` route deliberately serves any numeric id, and
 * G4 tests rely on that. The XC routes check membership themselves, before
 * calling this.
 */
export async function serveChannelStream(
  scenario: Scenario,
  channelId: number,
  req: IncomingMessage,
  res: ServerResponse,
  url: URL
): Promise<void>
```

**Check membership in the XC route, not in the extracted function.** The existing
`/stream/<n>.ts` route serves any numeric channel id — G2 never checked, and G4 specs stream ids
they never declared — so adding the check here would break them. The XC test above requires the
404, and the XC route is where it belongs.

- [ ] **Step 4: Add the `/live/` route to `src/xc/router.ts`**

```ts
  const liveMatch = /^\/live\/([^/]+)\/([^/]+)\/(\d+)\.ts$/.exec(subPath);
  if (liveMatch) {
    const [, username, password, rawId] = liveMatch;
    if (!xcCredentialsMatch(scenario, decodeURIComponent(username), decodeURIComponent(password))) {
      log(401);
      sendJson(401, { error: 'bad credentials' });
      return true;
    }
    const channelId = Number(rawId);
    if (!scenario.channels.some((channel) => channel.id === channelId)) {
      log(404);
      sendJson(404, { error: `scenario ${scenario.id} declares no channel ${channelId}` });
      return true;
    }
    await context.serveChannelStream(scenario, channelId, context.req, context.res, url);
    return true;
  }
```

`serveChannelStream` is passed in on `XcContext` rather than imported, because `src/server.ts` already imports `src/xc/router.ts` and importing back would be a cycle — the same reasoning that put `BadRequestError` in its own leaf module.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run && npm run typecheck`
Expected: PASS, whole suite — including `faults.test.ts` and `stream.test.ts`, which are what prove the extraction was behaviour-preserving.

- [ ] **Step 6: Commit**

```bash
git add e2e-upstream/src/server.ts e2e-upstream/src/xc/router.ts e2e-upstream/test/xc-router.test.ts
```

then:

```bash
git commit -m "feat(e2e-upstream): serve XC live playback through the shared stream pipeline"
```

---

### Task 5: The finite VOD asset and Range serving

A second asset and a second serving path, not a parameter on the first. `streamLoop` is endless and deliberately sends no `Content-Length`; on the VOD path the absence of `Content-Length` is exactly what makes `apps/proxy/vod_proxy/multi_worker_connection_manager.py` emit a response with no `Accept-Ranges` and no `Content-Range` at all.

**Files:**
- Create: `e2e-upstream/scripts/make-vod-asset.sh`, `e2e-upstream/src/vod-asset.ts`
- Modify: `e2e-upstream/Dockerfile`, `e2e-upstream/src/xc/router.ts`, `e2e-upstream/src/server.ts`
- Test: `e2e-upstream/test/vod-asset.test.ts`, `e2e-upstream/test/xc-router.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks except `XcContext`.
- Produces, from `src/vod-asset.ts`:
  - `interface FiniteAsset { bytes: Buffer; contentType: string }`
  - `loadFiniteAsset(path: string, contentType: string): FiniteAsset`
  - `type RangeResult = { kind: 'full' } | { kind: 'partial'; start: number; end: number } | { kind: 'unsatisfiable' }`
  - `parseRange(header: string | undefined, length: number): RangeResult`
  - `serveFiniteAsset(res: ServerResponse, asset: FiniteAsset, options: { rangeHeader?: string; ignoreRange?: boolean; head?: boolean }): number` — returns the status it sent, for the caller to log.

- [ ] **Step 1: Write the failing tests**

`e2e-upstream/test/vod-asset.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { parseRange } from '../src/vod-asset.js';

describe('parseRange', () => {
  it('treats an absent or unparseable header as a full-body request', () => {
    // RFC 9110: a Range header a server does not understand is ignored, not
    // rejected. Dispatcharr never sends a multi-range request, and answering
    // 416 to one would be a fault this provider is not modelling.
    expect(parseRange(undefined, 100)).toEqual({ kind: 'full' });
    expect(parseRange('items=0-1', 100)).toEqual({ kind: 'full' });
    expect(parseRange('bytes=0-1,5-6', 100)).toEqual({ kind: 'full' });
    expect(parseRange('bytes=-', 100)).toEqual({ kind: 'full' });
  });

  it('parses a closed range', () => {
    expect(parseRange('bytes=10-19', 100)).toEqual({ kind: 'partial', start: 10, end: 19 });
  });

  it('parses an open-ended range', () => {
    expect(parseRange('bytes=90-', 100)).toEqual({ kind: 'partial', start: 90, end: 99 });
  });

  it('clamps an end past the last byte', () => {
    expect(parseRange('bytes=90-500', 100)).toEqual({ kind: 'partial', start: 90, end: 99 });
  });

  it('parses a suffix range', () => {
    expect(parseRange('bytes=-10', 100)).toEqual({ kind: 'partial', start: 90, end: 99 });
    expect(parseRange('bytes=-500', 100)).toEqual({ kind: 'partial', start: 0, end: 99 });
  });

  it('reports a start past the end, an inverted range and a zero suffix as unsatisfiable', () => {
    expect(parseRange('bytes=100-', 100)).toEqual({ kind: 'unsatisfiable' });
    expect(parseRange('bytes=50-10', 100)).toEqual({ kind: 'unsatisfiable' });
    expect(parseRange('bytes=-0', 100)).toEqual({ kind: 'unsatisfiable' });
  });
});
```

Append to `e2e-upstream/test/xc-router.test.ts` — these run against a synthetic asset, because `assets/` is gitignored and built inside the Docker image (the same reason G2's vitest suite synthesises its own TS):

```ts
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

/**
 * The vitest suite never sees the real assets — `assets/` is gitignored and
 * produced by the Docker builder stage. A recognisable byte pattern is all
 * the Range assertions need, and using one keeps this suite runnable with
 * `npm test` alone, no Docker.
 */
function syntheticVodAsset(): string {
  const dir = mkdtempSync(join(tmpdir(), 'e2e-upstream-vod-'));
  const path = join(dir, 'vod.mp4');
  writeFileSync(path, Buffer.from(Array.from({ length: 1000 }, (_u, i) => i % 251)));
  return path;
}

describe('XC VOD playback', () => {
  it('serves the whole asset with Content-Length and Accept-Ranges', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-length')).toBe('1000');
    expect(res.headers.get('accept-ranges')).toBe('bytes');
    expect(res.headers.get('content-type')).toBe('video/mp4');
    expect((await res.arrayBuffer()).byteLength).toBe(1000);
  });

  it('answers a Range with 206 and a Content-Range naming the full size', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`, {
      headers: { Range: 'bytes=100-199' },
    });
    expect(res.status).toBe(206);
    expect(res.headers.get('content-range')).toBe('bytes 100-199/1000');
    expect(res.headers.get('content-length')).toBe('100');
    const body = Buffer.from(await res.arrayBuffer());
    expect(body).toHaveLength(100);
    expect(body[0]).toBe(100 % 251);
  });

  it('answers an unsatisfiable Range with 416 and a Content-Range naming the size', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`, {
      headers: { Range: 'bytes=5000-' },
    });
    expect(res.status).toBe(416);
    expect(res.headers.get('content-range')).toBe('bytes */1000');
  });

  it('serves an episode on /series/<user>/<pass>/<id>.<ext>', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    expect((await fetch(`${base}/s/${id}/series/user/pass/1.mp4`)).status).toBe(200);
  });

  it('404s an unknown movie or episode id, and 401s wrong credentials', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    expect((await fetch(`${base}/s/${id}/movie/user/pass/99.mp4`)).status).toBe(404);
    expect((await fetch(`${base}/s/${id}/movie/user/wrong/1.mp4`)).status).toBe(401);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd e2e-upstream && npx vitest run test/vod-asset.test.ts test/xc-router.test.ts`
Expected: FAIL — `Cannot find module '../src/vod-asset.js'`.

- [ ] **Step 3: Write `src/vod-asset.ts`**

```ts
import { readFileSync } from 'node:fs';
import type { ServerResponse } from 'node:http';

export interface FiniteAsset {
  bytes: Buffer;
  contentType: string;
}

export type RangeResult =
  | { kind: 'full' }
  | { kind: 'partial'; start: number; end: number }
  | { kind: 'unsatisfiable' };

const SINGLE_BYTE_RANGE = /^bytes=(\d*)-(\d*)$/;

/**
 * Parses a single `bytes=` range against a known length.
 *
 * Anything this does not understand — another unit, a multi-range header, a
 * bare `bytes=-` — returns `full`, per RFC 9110's "ignore a Range you cannot
 * satisfy". Answering 416 to a multi-range request would be a *fault*, and
 * this provider models faults explicitly (`range-unsupported`) rather than by
 * accident.
 */
export function parseRange(header: string | undefined, length: number): RangeResult {
  if (!header) return { kind: 'full' };
  const match = SINGLE_BYTE_RANGE.exec(header.trim());
  if (!match) return { kind: 'full' };

  const [, rawStart, rawEnd] = match;
  if (rawStart === '' && rawEnd === '') return { kind: 'full' };

  if (rawStart === '') {
    const suffix = Number(rawEnd);
    // `bytes=-0` asks for the last zero bytes, which is unsatisfiable rather
    // than empty — and is the one suffix case a naive `length - suffix`
    // silently turns into "the whole file".
    if (suffix === 0) return { kind: 'unsatisfiable' };
    return { kind: 'partial', start: Math.max(0, length - suffix), end: length - 1 };
  }

  const start = Number(rawStart);
  if (start >= length) return { kind: 'unsatisfiable' };
  const end = rawEnd === '' ? length - 1 : Math.min(Number(rawEnd), length - 1);
  if (end < start) return { kind: 'unsatisfiable' };
  return { kind: 'partial', start, end };
}

export function loadFiniteAsset(path: string, contentType: string): FiniteAsset {
  return { bytes: readFileSync(path), contentType };
}

export interface ServeOptions {
  rangeHeader?: string;
  /** The `range-unsupported` fault: answer 200 with the whole body, no Accept-Ranges. */
  ignoreRange?: boolean;
  head?: boolean;
}

/**
 * Serves a finite asset, honouring Range. Returns the status sent, so the
 * caller logs what actually happened rather than what it intended.
 *
 * `Accept-Ranges` and `Content-Length` are not cosmetic here:
 * `apps/proxy/vod_proxy/multi_worker_connection_manager.py` learns the file
 * size from `Content-Range`, falling back to `Content-Length`, and emits
 * `Accept-Ranges`/`Content-Range` to its own client only once it knows that
 * size. A provider without them produces a VOD response with no seek metadata
 * at all.
 */
export function serveFiniteAsset(
  res: ServerResponse,
  asset: FiniteAsset,
  options: ServeOptions = {}
): number {
  const length = asset.bytes.byteLength;
  const range = options.ignoreRange ? { kind: 'full' as const } : parseRange(options.rangeHeader, length);

  if (range.kind === 'unsatisfiable') {
    res.writeHead(416, { 'Content-Range': `bytes */${length}`, 'Content-Length': 0 });
    res.end();
    return 416;
  }

  if (range.kind === 'partial') {
    const body = asset.bytes.subarray(range.start, range.end + 1);
    res.writeHead(206, {
      'Content-Type': asset.contentType,
      'Content-Length': body.byteLength,
      'Content-Range': `bytes ${range.start}-${range.end}/${length}`,
      'Accept-Ranges': 'bytes',
    });
    if (options.head) res.end();
    else res.end(body);
    return 206;
  }

  res.writeHead(200, {
    'Content-Type': asset.contentType,
    'Content-Length': length,
    // Omitted under `ignoreRange`: a provider that will not serve 206 does not
    // advertise that it will.
    ...(options.ignoreRange ? {} : { 'Accept-Ranges': 'bytes' }),
  });
  if (options.head) res.end();
  else res.end(asset.bytes);
  return 200;
}
```

- [ ] **Step 4: Lazily load the asset in `src/server.ts` and expose it on `XcContext`**

Mirror the existing `getAsset()` pattern exactly, and for the same reason — `readFileSync` on a path that exists only inside the image must not run at import time:

```ts
let vodAsset: FiniteAsset | undefined;
function getVodAsset(): FiniteAsset {
  if (!vodAsset) {
    vodAsset = loadFiniteAsset(
      process.env.UPSTREAM_VOD_ASSET ?? '/app/assets/vod.mp4',
      'video/mp4'
    );
  }
  return vodAsset;
}
```

**Do not cache across a changed `UPSTREAM_VOD_ASSET`** in tests: the vitest cases above each set the env var before starting a server, so read `process.env.UPSTREAM_VOD_ASSET` into the cache key, or simply key the module-level cache on the resolved path.

- [ ] **Step 5: Add the `/movie/` and `/series/` routes to `src/xc/router.ts`**

One handler for both, differing only in which catalogue it looks the id up in:

```ts
  const vodMatch = /^\/(movie|series)\/([^/]+)\/([^/]+)\/(\d+)\.[A-Za-z0-9]+$/.exec(subPath);
  if (vodMatch) {
    const [, kind, username, password, rawId] = vodMatch;
    if (!xcCredentialsMatch(scenario, decodeURIComponent(username), decodeURIComponent(password))) {
      log(401);
      sendJson(401, { error: 'bad credentials' });
      return true;
    }
    const wanted = Number(rawId);
    const known =
      kind === 'movie'
        ? scenario.vod.some((movie) => movie.id === wanted)
        : scenario.series.some((series) =>
            series.seasons.some((season) => season.episodes.some((episode) => episode.id === wanted))
          );
    if (!known) {
      log(404);
      sendJson(404, { error: `scenario ${scenario.id} declares no ${kind} with id ${wanted}` });
      return true;
    }
    const status = context.serveVodAsset(context.res, {
      rangeHeader: context.req.headers.range,
      head: context.req.method === 'HEAD',
    });
    log(status);
    return true;
  }
```

Like `serveChannelStream`, this is handed in on `XcContext` rather than imported, so `router.ts` never reaches back into `server.ts` — the cycle `src/errors.ts` exists to avoid. `XcContext` gains one member, already bound to the lazily-loaded asset so the router never sees a file path:

```ts
  /** `serveFiniteAsset` with the VOD asset already bound. Returns the status sent. */
  serveVodAsset(res: ServerResponse, options: ServeOptions): number;
```

and `server.ts` supplies it as `(res, options) => serveFiniteAsset(res, getVodAsset(), options)`. The route above calls `context.serveVodAsset(context.res, { ... })`.

- [ ] **Step 6: Add the build-time asset**

`e2e-upstream/scripts/make-vod-asset.sh`:

```bash
#!/usr/bin/env bash
# Generate the finite VOD asset. Build-time only, alongside make-asset.sh, in
# the Docker builder stage — the runtime image carries the assets, not ffmpeg.
#
# Deliberately short and deliberately *finite*: the whole point of this asset
# is that it has an end, a Content-Length and a byte offset you can seek to.
# The TS loop next to it has none of those and never will.
set -euo pipefail

OUT="${1:?usage: make-vod-asset.sh <output.mp4>}"
DURATION="${VOD_ASSET_DURATION_SECONDS:-5}"
FPS="${VOD_ASSET_FPS:-25}"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc=size=320x180:rate=${FPS}:duration=${DURATION}" \
  -f lavfi -i "sine=frequency=440:duration=${DURATION}" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -c:a aac -b:a 64k \
  -movflags +faststart \
  -f mp4 "${OUT}"

# ffmpeg's version is unpinned (see make-asset.sh), so assert the output
# rather than a byte-exact artifact. Nothing downstream may hardcode this
# size: the server reads it from the file at load time.
SIZE="$(stat -c%s "${OUT}" 2>/dev/null || stat -f%z "${OUT}")"
if [ "${SIZE}" -lt 1024 ]; then
  echo "make-vod-asset.sh: ${OUT} is only ${SIZE} bytes — ffmpeg produced nothing usable" >&2
  exit 1
fi

# `ftyp` is the first box of every MP4. A file that does not start with one is
# not an MP4, whatever the extension says — and Dispatcharr infers its
# client-facing Content-Type from that extension.
if [ "$(dd if="${OUT}" bs=1 skip=4 count=4 2>/dev/null)" != "ftyp" ]; then
  echo "make-vod-asset.sh: ${OUT} does not begin with an ftyp box — this is not an MP4" >&2
  exit 1
fi

echo "Wrote ${OUT} (${SIZE} bytes)"
```

`e2e-upstream/Dockerfile` — extend the **existing** `asset` builder stage and the runtime copy. No new base image, so no new digest to resolve:

```dockerfile
COPY scripts/make-asset.sh scripts/make-vod-asset.sh ./
RUN chmod +x make-asset.sh make-vod-asset.sh \
 && ./make-asset.sh /build/loop.ts \
 && ./make-vod-asset.sh /build/vod.mp4
```

and in the runtime stage:

```dockerfile
COPY --from=asset /build/vod.mp4 /app/assets/vod.mp4
ENV UPSTREAM_VOD_ASSET=/app/assets/vod.mp4
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run && npm run typecheck`
Expected: PASS.

Then prove the image still builds and carries both assets:

```bash
docker build -f e2e-upstream/Dockerfile -t dispatcharr-e2e-upstream:local e2e-upstream
docker run --rm --entrypoint sh dispatcharr-e2e-upstream:local -c 'ls -l /app/assets'
```
Expected: both `loop.ts` and `vod.mp4`, `vod.mp4` over 1 KB.

- [ ] **Step 8: Commit**

```bash
git add e2e-upstream/src/vod-asset.ts e2e-upstream/src/server.ts e2e-upstream/src/xc/router.ts e2e-upstream/scripts/make-vod-asset.sh e2e-upstream/Dockerfile e2e-upstream/test/vod-asset.test.ts e2e-upstream/test/xc-router.test.ts
```

then:

```bash
git commit -m "feat(e2e-upstream): serve a finite, Range-capable VOD asset"
```

---

### Task 6: Catch-up, both layouts

Both routes serve the ordinary looping TS — `_stream_from_provider` requires a TS sync byte in the first 1024 bytes, so nothing else will be accepted — and both record what they were asked for. The archive is **not** time-addressable; the recorded parameters are the whole of the evidence, and every G10 row inherits that limit.

**Files:**
- Create: `e2e-upstream/src/xc/catchup.ts`
- Modify: `e2e-upstream/src/xc/router.ts`
- Test: `e2e-upstream/test/xc-catchup.test.ts`, `e2e-upstream/test/xc-router.test.ts`

**Interfaces:**
- Consumes: `serveChannelStream` via `XcContext` (Task 4).
- Produces, from `src/xc/catchup.ts`:
  - `type CatchupLayout = 'path' | 'query'`
  - `interface CatchupRequest { layout: CatchupLayout; username: string; password: string; streamId: number; start: string; startIso: string | null; durationMinutes: number }`
  - `parseCatchupTimestamp(value: string): string | null` — canonical `YYYY-MM-DDTHH:MM:SS`, or `null`
  - `parseCatchupPath(subPath: string): CatchupRequest | undefined`
  - `parseCatchupQuery(url: URL): CatchupRequest | undefined`

- [ ] **Step 1: Write the failing tests**

`e2e-upstream/test/xc-catchup.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { parseCatchupPath, parseCatchupQuery, parseCatchupTimestamp } from '../src/xc/catchup.js';

describe('parseCatchupTimestamp', () => {
  it('accepts all four shapes build_timeshift_candidate_urls emits', () => {
    // apps/timeshift/helpers.py: three PATH shapes then four QUERY shapes,
    // drawn from these four strftime formats. A provider that recognises only
    // one silently turns the cascade into "the first shape wins", which is
    // the exact behaviour G10 exists to test.
    for (const value of [
      '2026-08-29:14-00',      // %Y-%m-%d:%H-%M      (PATH, and QUERY colon-dash)
      '2026-08-29_14-00',      // %Y-%m-%d_%H-%M      (PATH, and QUERY underscore)
      '2026-08-29:14:00:00',   // %Y-%m-%d:%H:%M:%S   (PATH, and QUERY colon-seconds)
      '2026-08-29 14:00:00',   // %Y-%m-%d %H:%M:%S   (QUERY SQL)
    ]) {
      expect(parseCatchupTimestamp(value)).toBe('2026-08-29T14:00:00');
    }
  });

  it('returns null for anything else', () => {
    expect(parseCatchupTimestamp('yesterday')).toBeNull();
    expect(parseCatchupTimestamp('1756476000')).toBeNull();
  });
});

describe('parseCatchupPath', () => {
  it('reads the PATH layout segments', () => {
    const request = parseCatchupPath('/timeshift/user/pass/65/2026-08-29:14-00/7.ts')!;
    expect(request).toMatchObject({
      layout: 'path',
      username: 'user',
      password: 'pass',
      durationMinutes: 65,
      start: '2026-08-29:14-00',
      startIso: '2026-08-29T14:00:00',
      streamId: 7,
    });
  });

  it('URL-decodes credentials', () => {
    // build_timeshift_url_format_b quotes username and password with safe=''.
    const request = parseCatchupPath('/timeshift/us%40er/p%2Fss/60/2026-08-29:14-00/1.ts')!;
    expect(request.username).toBe('us@er');
    expect(request.password).toBe('p/ss');
  });

  it('returns undefined for a non-catch-up path', () => {
    expect(parseCatchupPath('/live/user/pass/1.ts')).toBeUndefined();
  });
});

describe('parseCatchupQuery', () => {
  it('reads the QUERY layout parameters, including an SQL timestamp with a space', () => {
    // build_timeshift_url_format_a interpolates `start` raw — only username
    // and password are quoted — so the SQL shape arrives percent-encoded by
    // requests. URLSearchParams decodes it; splitting on '+' would not.
    const url = new URL(
      'http://h/s/x/streaming/timeshift.php?username=user&password=pass&stream=7&start=2026-08-29%2014%3A00%3A00&duration=65'
    );
    expect(parseCatchupQuery(url)).toMatchObject({
      layout: 'query',
      username: 'user',
      password: 'pass',
      streamId: 7,
      startIso: '2026-08-29T14:00:00',
      durationMinutes: 65,
    });
  });

  it('returns undefined when a required parameter is missing', () => {
    expect(parseCatchupQuery(new URL('http://h/x?username=user'))).toBeUndefined();
  });
});
```

Append to `e2e-upstream/test/xc-router.test.ts`:

```ts
describe('XC catch-up', () => {
  const start = '2026-08-29:14-00';

  it('serves TS on the PATH layout and records what it was asked for', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/timeshift/user/pass/65/${start}/1.ts`);
    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toBe('video/mp2t');
    const reader = res.body!.getReader();
    expect((await reader.read()).value![0]).toBe(0x47);
    await reader.cancel();

    const log = await (await fetch(`${base}/s/${id}/log`)).json();
    // No new LogEntry kind: the PATH form's segments are already in `path`,
    // and G4's readers of this log must keep working.
    expect(log).toContainEqual(
      expect.objectContaining({
        kind: 'request',
        status: 200,
        path: `/s/${id}/timeshift/user/pass/65/${start}/1.ts`,
      })
    );
  });

  it('serves TS on the QUERY layout, recording the parameters in the logged path', async () => {
    const { base, id } = await xcScenario();
    const query = `username=user&password=pass&stream=1&start=${encodeURIComponent(start)}&duration=65`;
    const res = await fetch(`${base}/s/${id}/streaming/timeshift.php?${query}`);
    expect(res.status).toBe(200);
    await res.body!.cancel();

    const log = await (await fetch(`${base}/s/${id}/log`)).json();
    const entry = log.find((e: { path?: string }) => e.path?.includes('timeshift.php'));
    expect(entry.path).toContain('stream=1');
    expect(entry.path).toContain('duration=65');
  });

  it('401s wrong catch-up credentials on both layouts', async () => {
    const { base, id } = await xcScenario();
    expect(
      (await fetch(`${base}/s/${id}/timeshift/user/wrong/65/${start}/1.ts`)).status
    ).toBe(401);
    expect(
      (await fetch(`${base}/s/${id}/streaming/timeshift.php?username=user&password=wrong&stream=1&start=${start}&duration=65`))
        .status
    ).toBe(401);
  });

  it('400s an unrecognised timestamp shape, naming the four it accepts', async () => {
    const { base, id } = await xcScenario();
    const res = await fetch(`${base}/s/${id}/timeshift/user/pass/65/yesterday/1.ts`);
    expect(res.status).toBe(400);
    expect((await res.json()).error).toMatch(/%Y-%m-%d/);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd e2e-upstream && npx vitest run test/xc-catchup.test.ts test/xc-router.test.ts`
Expected: FAIL — `Cannot find module '../src/xc/catchup.js'`.

- [ ] **Step 3: Write `src/xc/catchup.ts`**

```ts
export type CatchupLayout = 'path' | 'query';

export interface CatchupRequest {
  layout: CatchupLayout;
  username: string;
  password: string;
  streamId: number;
  /** Exactly as sent, so a test can assert on the shape as well as the instant. */
  start: string;
  /** Canonical `YYYY-MM-DDTHH:MM:SS`, or null when the shape was not recognised. */
  startIso: string | null;
  durationMinutes: number;
}

/**
 * The four timestamp shapes `build_timeshift_candidate_urls` emits across its
 * seven candidates:
 *
 *   %Y-%m-%d:%H-%M      PATH candidate 0, QUERY candidate 5
 *   %Y-%m-%d_%H-%M      PATH candidate 1, QUERY candidate 3
 *   %Y-%m-%d:%H:%M:%S   PATH candidate 2, QUERY candidate 6
 *   %Y-%m-%d %H:%M:%S   QUERY candidate 4 (SQL)
 *
 * One regex covers all four: the date, then `:`/`_`/space, then the hour, then
 * `-`/`:`, then the minute, then optionally the same separator and seconds.
 */
const CATCHUP_TIMESTAMP = /^(\d{4}-\d{2}-\d{2})[:_ ](\d{2})[-:](\d{2})(?:[-:](\d{2}))?$/;

export const ACCEPTED_TIMESTAMP_SHAPES =
  '%Y-%m-%d:%H-%M, %Y-%m-%d_%H-%M, %Y-%m-%d:%H:%M:%S, %Y-%m-%d %H:%M:%S';

export function parseCatchupTimestamp(value: string): string | null {
  const match = CATCHUP_TIMESTAMP.exec(value.trim());
  if (!match) return null;
  const [, date, hour, minute, second] = match;
  return `${date}T${hour}:${minute}:${second ?? '00'}`;
}

const CATCHUP_PATH = /^\/timeshift\/([^/]+)\/([^/]+)\/([^/]+)\/([^/]+)\/(\d+)\.ts$/;

export function parseCatchupPath(subPath: string): CatchupRequest | undefined {
  const match = CATCHUP_PATH.exec(subPath);
  if (!match) return undefined;
  const [, username, password, duration, start, streamId] = match;
  return {
    layout: 'path',
    username: decodeURIComponent(username),
    password: decodeURIComponent(password),
    streamId: Number(streamId),
    start: decodeURIComponent(start),
    startIso: parseCatchupTimestamp(decodeURIComponent(start)),
    durationMinutes: Number(duration),
  };
}

export function parseCatchupQuery(url: URL): CatchupRequest | undefined {
  const username = url.searchParams.get('username');
  const password = url.searchParams.get('password');
  const stream = url.searchParams.get('stream');
  const start = url.searchParams.get('start');
  if (username === null || password === null || stream === null || start === null) {
    return undefined;
  }
  return {
    layout: 'query',
    username,
    password,
    streamId: Number(stream),
    start,
    startIso: parseCatchupTimestamp(start),
    durationMinutes: Number(url.searchParams.get('duration') ?? '0'),
  };
}
```

- [ ] **Step 4: Add the two routes to `src/xc/router.ts`**

One shared tail, so the layouts cannot diverge in anything but how they were parsed:

```ts
  const catchup =
    parseCatchupPath(subPath) ??
    (subPath === '/streaming/timeshift.php' ? parseCatchupQuery(url) : undefined);

  if (catchup) {
    if (!xcCredentialsMatch(scenario, catchup.username, catchup.password)) {
      log(401);
      sendJson(401, { error: 'bad credentials' });
      return true;
    }
    if (catchup.startIso === null) {
      // Named, because a bare 400 here is indistinguishable from a cascade
      // step legitimately failing — and this provider must never be the
      // reason a cascade test reports the wrong shape as unsupported.
      log(400);
      sendJson(400, {
        error: `unrecognised catch-up timestamp '${catchup.start}'; this provider accepts ${ACCEPTED_TIMESTAMP_SHAPES}`,
      });
      return true;
    }
    if (!scenario.channels.some((channel) => channel.id === catchup.streamId)) {
      log(404);
      sendJson(404, { error: `scenario ${scenario.id} declares no channel ${catchup.streamId}` });
      return true;
    }
    // The archive is not time-addressable: the same loop is served whatever
    // `start` asked for. That is a stated, deliberate gap — G10 can prove
    // Dispatcharr asked for the right moment, never that it received it.
    await context.serveChannelStream(scenario, catchup.streamId, context.req, context.res, url);
    return true;
  }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add e2e-upstream/src/xc/catchup.ts e2e-upstream/src/xc/router.ts e2e-upstream/test/xc-catchup.test.ts e2e-upstream/test/xc-router.test.ts
```

then:

```bash
git commit -m "feat(e2e-upstream): answer catch-up URLs in both layouts and record their parameters"
```

---

### Task 7: The four new faults

Follows G2's conventions exactly: validated at the door, per-channel scoping where it means something, and `appliedTo: 0` documented as the correct outcome for a new-connection-only fault rather than a partial failure.

**Files:**
- Modify: `e2e-upstream/src/faults.ts`, `e2e-upstream/src/xc/router.ts`, `e2e-upstream/src/server.ts`
- Test: `e2e-upstream/test/faults.test.ts`, `e2e-upstream/test/xc-faults.test.ts`

**Interfaces:**
- Consumes: `FaultStore`, `parseFaultRequest`, `FAULT_NAMES` from `src/faults.js`.
- Produces: `FaultName` gains `'xc-auth-envelope' | 'no-tv-archive' | 'catchup-layout-404' | 'range-unsupported'`; `FaultRequest` gains `layout?: CatchupLayout`.

- [ ] **Step 1: Write the failing tests**

Append to `e2e-upstream/test/faults.test.ts`:

```ts
describe('the G8 faults', () => {
  it('accepts the four new names', () => {
    for (const fault of ['xc-auth-envelope', 'no-tv-archive', 'range-unsupported'] as const) {
      expect(parseFaultRequest({ fault, active: true }).fault).toBe(fault);
    }
    expect(parseFaultRequest({ fault: 'catchup-layout-404', active: true, layout: 'path' }).layout).toBe('path');
  });

  it('requires a layout on catchup-layout-404', () => {
    // Without a layout this is indistinguishable from `not-found`, and the
    // cascade — the part of catch-up most likely to be wrong — becomes
    // unobservable. Rejected at the door rather than defaulted.
    expect(() => parseFaultRequest({ fault: 'catchup-layout-404', active: true })).toThrow(/layout/);
    expect(() =>
      parseFaultRequest({ fault: 'catchup-layout-404', active: true, layout: 'both' })
    ).toThrow(/path.*query/);
  });

  it('reports appliedTo 0 for all four, even with a live connection open', () => {
    // All four can only affect the next request: a live response has already
    // sent its headers. Zero is correct here, not a partial failure.
    const store = new FaultStore();
    const connections = new ConnectionRegistry();
    for (const fault of ['xc-auth-envelope', 'no-tv-archive', 'range-unsupported'] as const) {
      expect(store.apply('s', { fault, active: true }, connections).appliedTo).toBe(0);
    }
  });
});
```

`e2e-upstream/test/xc-faults.test.ts` (new file, same `xcScenario` helper — copy it in rather than exporting it from `xc-router.test.ts`, so each file stands alone):

```ts
describe('xc-auth-envelope', () => {
  it('answers 200 with auth 0 rather than 401', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'xc-auth-envelope', active: true });
    const res = await fetch(`${base}/s/${id}/player_api.php${auth}`);
    // 200, deliberately. Client.authenticate() checks only that user_info is
    // truthy, so this is the shape the product mistakes for a successful
    // login — which is the whole point of the fault.
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.user_info.auth).toBe(0);
    expect(body.user_info.status).toBe('Disabled');
  });
});

describe('auth-failure on the XC surface', () => {
  it('401s player_api.php', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'auth-failure', active: true });
    expect((await fetch(`${base}/s/${id}/player_api.php${auth}`)).status).toBe(401);
  });
});

describe('no-tv-archive', () => {
  it('omits tv_archive from get_live_streams', async () => {
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'no-tv-archive', active: true });
    const [stream] = await (
      await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_streams`)
    ).json();
    expect(stream).not.toHaveProperty('tv_archive');
  });

  it('scopes to one channel when a channel filter is given', async () => {
    const { base, id } = await xcScenario({ channels: 2 });
    await arm(base, id, { fault: 'no-tv-archive', active: true, channel: 2 });
    const streams = await (
      await fetch(`${base}/s/${id}/player_api.php${auth}&action=get_live_streams`)
    ).json();
    expect(streams[0]).toHaveProperty('tv_archive');
    expect(streams[1]).not.toHaveProperty('tv_archive');
  });
});

describe('catchup-layout-404', () => {
  it('404s only the named layout', async () => {
    const { base, id } = await xcScenario();
    const start = '2026-08-29:14-00';
    await arm(base, id, { fault: 'catchup-layout-404', active: true, layout: 'path' });

    expect((await fetch(`${base}/s/${id}/timeshift/user/pass/65/${start}/1.ts`)).status).toBe(404);

    const query = `username=user&password=pass&stream=1&start=${encodeURIComponent(start)}&duration=65`;
    const ok = await fetch(`${base}/s/${id}/streaming/timeshift.php?${query}`);
    expect(ok.status).toBe(200);
    await ok.body!.cancel();
  });
});

describe('range-unsupported', () => {
  it('answers 200 with the whole body and no Accept-Ranges', async () => {
    process.env.UPSTREAM_VOD_ASSET = syntheticVodAsset();
    const { base, id } = await xcScenario();
    await arm(base, id, { fault: 'range-unsupported', active: true });
    const res = await fetch(`${base}/s/${id}/movie/user/pass/1.mp4`, {
      headers: { Range: 'bytes=100-199' },
    });
    expect(res.status).toBe(200);
    expect(res.headers.get('accept-ranges')).toBeNull();
    expect((await res.arrayBuffer()).byteLength).toBe(1000);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd e2e-upstream && npx vitest run test/faults.test.ts test/xc-faults.test.ts`
Expected: FAIL — `parseFaultRequest` rejects the new names.

- [ ] **Step 3: Extend `src/faults.ts`**

Add the four names to `FaultName` and `FAULT_NAMES`; add `layout?: 'path' | 'query'` to `FaultRequest`; validate it:

```ts
  if (request.fault === 'catchup-layout-404') {
    // Required, not defaulted: a layout-less variant is exactly `not-found`,
    // and blocking both layouts makes the seven-candidate cascade
    // unobservable — which is the one thing this fault exists to expose.
    if (body.layout !== 'path' && body.layout !== 'query') {
      throw new BadRequestError(
        "'catchup-layout-404' requires 'layout' to be 'path' or 'query'"
      );
    }
    request.layout = body.layout;
  } else if (body.layout !== undefined) {
    throw new BadRequestError(`'layout' is only meaningful on 'catchup-layout-404'`);
  }
```

All four fall through `apply`'s `default:` branch, so `appliedTo` stays 0 with no further change — extend the comment there to name them.

- [ ] **Step 4: Consult the faults from the XC routes**

- `player_api.php`: check `auth-failure` (401) **before** the credential check, exactly as the playlist and stream routes do; check `xc-auth-envelope` after a successful credential check and, when armed, emit the envelope with `user_info.auth = 0` and `status = 'Disabled'`.
- `get_live_streams`: pass `tvArchive: (channelId) => !faults.isActive(scenario.id, 'no-tv-archive', channelId)`.
- Catch-up: after parsing, `if (faults.isActive(scenario.id, 'catchup-layout-404', catchup.streamId) && faults.configOf(scenario.id, 'catchup-layout-404', catchup.streamId)?.layout === catchup.layout)` → log 404 and `sendJson(404, …)`.
- VOD: `context.serveVodAsset(context.res, { ..., ignoreRange: faults.isActive(scenario.id, 'range-unsupported') })`. **Scenario-wide only** — a VOD id is not a channel id, so the `channel` filter has no meaning here; say so in the README row.

`faults` is reached through `XcContext`, like `serveChannelStream`, not by importing `server.ts`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd e2e-upstream && npx vitest run && npm run typecheck`
Expected: PASS, whole suite.

- [ ] **Step 6: Commit**

```bash
git add e2e-upstream/src/faults.ts e2e-upstream/src/xc/router.ts e2e-upstream/src/server.ts e2e-upstream/test/faults.test.ts e2e-upstream/test/xc-faults.test.ts
```

then:

```bash
git commit -m "feat(e2e-upstream): add the xc-auth-envelope, no-tv-archive, catchup-layout-404 and range-unsupported faults"
```

---

### Task 8: The `e2e/` fixture surface

Everything a G9 or G10 agent touches, so that none of them ever opens `e2e-upstream/src/`. No new Playwright fixture is registered on `test.extend`: these are `Seeder` methods, `UpstreamClient` methods and types.

**Files:**
- Modify: `e2e/fixtures/upstream.ts`, `e2e/fixtures/types.ts`, `e2e/fixtures/seed.ts`
- Test: `npm run typecheck` in `e2e/` (this package has no unit runner; the blocking `tsc --noEmit` hook on `e2e/**/*.ts` is its gate, and Task 9's specs are its first real exercise)

**Interfaces:**
- Consumes: the provider's control API from Tasks 1–7.
- Produces:
  - `UpstreamScenario` gains `username?: string`, `password?: string`, and the catalogue echo `vod: MovieSpec[]`, `series: SeriesSpec[]`, `liveCategories: CategorySpec[]`, `vodCategories: CategorySpec[]`, `seriesCategories: CategorySpec[]`
  - `ScenarioRequest` gains the Task 1 fields
  - `FaultName` gains the four new names; `FaultOptions` gains `layout?: 'path' | 'query'`
  - `upstream.xcUrl(scenario: UpstreamScenario): string`
  - `seed.xcAccount(scenario: UpstreamScenario, overrides?: M3uAccountOverrides): Promise<M3uAccount>`

- [ ] **Step 1: Extend `e2e/fixtures/upstream.ts`**

Mirror the provider's types exactly. `username`/`password` are already echoed by `POST /scenarios` — the type simply never named them:

```ts
export interface UpstreamScenario {
  id: string;
  internal: string;
  control: string;
  credentialQuery: string;
  channels: UpstreamChannel[];
  /**
   * Echoed by the provider and typed here because an XC account needs the two
   * values *separately*: `credentialQuery` is the pre-formatted query string,
   * which is exactly what an XC `server_url` must not carry (the product's
   * `normalize_server_url` strips the query, so they would silently vanish).
   *
   * As `e2e-upstream/README.md` already warns for `credentialQuery`, these are
   * not secret from the control API or from an attached test report. They are
   * per-test throwaways; do not reuse a meaningful credential here.
   */
  username?: string;
  password?: string;
  liveCategories: UpstreamCategory[];
  vodCategories: UpstreamCategory[];
  seriesCategories: UpstreamCategory[];
  vod: UpstreamMovie[];
  series: UpstreamSeries[];
}
```

and:

```ts
  /**
   * The base URL an XC `M3UAccount.server_url` takes: the scenario's internal
   * origin and path, and **nothing else**.
   *
   * Deliberately not `playlistUrl()` with a different suffix. XC credentials
   * travel as real `username`/`password` parameters that the client sends
   * itself, and `core/xtream_codes.normalize_server_url` strips any query
   * string from `server_url` before use — so appending `credentialQuery` here
   * would remove the credentials rather than supply them, and the failure
   * would surface as an authentication error against a provider that is
   * configured correctly.
   */
  xcUrl(scenario: UpstreamScenario): string {
    return scenario.internal;
  }
```

Add the four fault names to the `FaultName` union and `layout?: 'path' | 'query'` to `FaultOptions`, with the doc comment on `layout` saying it is required for `catchup-layout-404` and rejected on anything else.

- [ ] **Step 2: Extend `e2e/fixtures/types.ts`**

Add `UpstreamCategory`, `UpstreamMovie`, `UpstreamSeries`, `UpstreamSeason`, `UpstreamEpisode`, each with a comment naming the consumer it was derived from, per that file's existing convention. Re-export them from `e2e/fixtures/index.ts` alongside the existing upstream types.

- [ ] **Step 3: Add `seed.xcAccount` to `e2e/fixtures/seed.ts`**

```ts
  /**
   * An Xtream Codes `M3UAccount` pointed at an XC scenario.
   *
   * Not `m3uAccount({ account_type: 'XC' })`, because two things are the
   * inverse of the standard-M3U path and both are easy to get wrong:
   *
   * 1. `server_url` is the scenario's **bare** internal base. No
   *    `credentialQuery`: `normalize_server_url` strips the query before use,
   *    so appending one deletes the credentials.
   * 2. The credentials go on the model's `username`/`password` fields, which
   *    the XC client actually reads — unlike a standard M3U refresh, which
   *    reads neither and needs them embedded in the URL.
   *
   * `is_active: true` is required for the same reason as `m3uAccount`: an
   * inactive account never starts a refresh. Unlike a standard account,
   * creating this one starts **no** background refresh —
   * `refresh_account_on_save` skips XC — so `waitFor.m3uRefreshComplete`'s own
   * trigger is the only one, and there is nothing to race.
   */
  xcAccount(
    scenario: UpstreamScenario,
    overrides: M3uAccountOverrides = {}
  ): Promise<M3uAccount> {
    return this.m3uAccount({
      account_type: 'XC',
      username: scenario.username ?? null,
      password: scenario.password ?? '',
      is_active: true,
      ...overrides,
      server_url: scenario.internal,
    });
  }
```

Note the ordering: `server_url` is spread **after** `overrides`, matching the file's existing "generated identity field last" rule, because a caller passing a `server_url` here is making the exact mistake this factory exists to prevent.

- [ ] **Step 4: Typecheck**

Run: `cd e2e && npm ci && npm run typecheck`
Expected: no errors. (The `PostToolUse` hook runs this on every `e2e/**/*.ts` edit and blocks on failure; both packages are typecheck-clean and must stay so.)

- [ ] **Step 5: Commit**

```bash
git add e2e/fixtures/upstream.ts e2e/fixtures/types.ts e2e/fixtures/seed.ts e2e/fixtures/index.ts
```

then:

```bash
git commit -m "feat(e2e): expose the XC scenario, catalogue and faults through the upstream fixture"
```

---

### Task 9: Plumbing proofs 1 and 2 — XC ingest and VOD catalogue ingest

The first two Dispatcharr-facing proofs. They assert **fields**, not counts: a sparse payload that satisfies `core/xtream_codes.Client` and not `apps/vod/tasks.py` produces a refresh reporting `success` with nothing behind it, and a count assertion would not catch it.

**Files:**
- Create: `e2e/tests/seeded/xc-ingest.spec.ts`, `e2e/tests/seeded/vod-catalogue-ingest.spec.ts`

**Interfaces:**
- Consumes: `seed.xcAccount`, `upstream.scenario`, `waitFor.m3uRefreshComplete`, `waitFor.resource`, `api` — all existing except `seed.xcAccount` (Task 8).
- Produces: nothing later tasks depend on.

**Before writing:** bring up the stack with `./scripts/e2e_up.sh` from the repo root, and remember that CI runs each project in its own fresh container while a local run shares one.

- [ ] **Step 1: Write `e2e/tests/seeded/xc-ingest.spec.ts`**

```ts
import { test, expect } from '../../fixtures';
import type { M3uAccount } from '../../fixtures';

interface StreamPage {
  count: number;
  results: {
    id: number;
    name: string;
    url: string;
    is_catchup: boolean;
    catchup_days: number;
    custom_properties: Record<string, unknown> | null;
  }[];
}

test('Dispatcharr ingests live streams from an Xtream Codes account', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  // Explicit names, always. VODCategory is globally unique on (name, type) and
  // Movie/Series are matched across every account by (name, year) — so the
  // default catalogue aliases across the four `seeded` workers even harder
  // than the default channel catalogue does.
  const prefix = seed.generatedName('xc');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    liveCategories: [{ id: 1, name: `${prefix}-cat` }],
    channels: [
      { id: 1, name: `${prefix}-a`, tvgId: `${prefix}-a.e2e`, logo: null, categoryId: 1 },
      { id: 2, name: `${prefix}-b`, tvgId: `${prefix}-b.e2e`, logo: null, categoryId: 1 },
    ],
  });

  const account = await seed.xcAccount(scenario);

  // m3uRefreshComplete owns the trigger. Safe here in a way it is not for a
  // standard account: `refresh_account_on_save` skips XC accounts, so nothing
  // is refreshing in the background to race with.
  const refreshed: M3uAccount = await waitFor.m3uRefreshComplete(account.id);
  expect(refreshed.status).toBe('success');

  const page = await api.json<StreamPage>(
    await api.get(`/api/channels/streams/?search=${encodeURIComponent(prefix)}`),
    'streams created by the XC ingest'
  );

  expect(page.results.map((s) => s.name).sort()).toEqual([`${prefix}-a`, `${prefix}-b`]);

  const first = page.results.find((s) => s.name === `${prefix}-a`)!;
  // The playback URL Dispatcharr built for itself, from get_stream_url's
  // shape — proof the XC path was taken and not the M3U one.
  expect(first.url).toContain(`/live/${prefix}-user/${prefix}-pass/1.ts`);
  // Provider stream id retained: this is what _prepare_catchup_stream_attempt
  // later reads, as a string.
  expect(first.custom_properties?.stream_id).toBe('1');
  // tv_archive / tv_archive_duration survived the round trip.
  expect(first.is_catchup).toBe(true);
  expect(first.catchup_days).toBeGreaterThan(0);
});
```

- [ ] **Step 2: Run it**

Run: `cd e2e && npx playwright test --project=seeded xc-ingest`
Expected: PASS. If `status` is `error`, read `last_message` — it names which XC call failed, and the fix is almost always a missing payload field, not a routing problem.

- [ ] **Step 3: Write `e2e/tests/seeded/vod-catalogue-ingest.spec.ts`**

```ts
import { test, expect } from '../../fixtures';

interface Page<T> {
  count: number;
  results: T[];
}
interface MovieRow { id: number; uuid: string; name: string; year: number | null }
interface SeriesRow { id: number; uuid: string; name: string }
interface EpisodeRow { id: number; name: string; season_number: number; episode_number: number }

test('Dispatcharr ingests a VOD and series catalogue from an Xtream Codes account', async ({
  upstream,
  seed,
  api,
  waitFor,
}) => {
  const prefix = seed.generatedName('vod');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
    vod: [{ id: 1, name: `${prefix}-movie`, year: 2020, categoryId: 1 }],
    series: [
      {
        id: 1,
        name: `${prefix}-series`,
        categoryId: 1,
        seasons: [{ number: 1, episodes: [{ id: 1, title: `${prefix}-ep`, episodeNum: 1 }] }],
      },
    ],
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  // The M3U refresh finishing says NOTHING about VOD: refresh_vod_content is
  // fired with .delay() *after* it returns, so the account reaches `success`
  // before any Movie exists. Poll for the rows themselves.
  const movies = await waitFor.resource<Page<MovieRow>>(
    `/api/vod/movies/?search=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the VOD movie named ${prefix}-movie to be ingested`, timeoutMs: 120_000 }
  );
  expect(movies.results[0]).toMatchObject({ name: `${prefix}-movie`, year: 2020 });

  const series = await waitFor.resource<Page<SeriesRow>>(
    `/api/vod/series/?search=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the series named ${prefix}-series to be ingested`, timeoutMs: 120_000 }
  );

  // Episodes are NOT part of the refresh. get_series_info is a separate,
  // on-demand call, and this endpoint is what reaches it — synchronously.
  await api.get(`/api/vod/series/${series.results[0].id}/provider-info/`);

  const episodes = await api.json<Page<EpisodeRow>>(
    await api.get(`/api/vod/episodes/?search=${encodeURIComponent(prefix)}`),
    'episodes created by the series-info fetch'
  );
  expect(episodes.results[0]).toMatchObject({
    name: `${prefix}-ep`,
    season_number: 1,
    episode_number: 1,
  });
});
```

If `/api/vod/episodes/` does not support `?search=`, read the episodes off `GET /api/vod/series/<pk>/episodes/` instead and assert the same three fields — check the viewset before writing, and leave a comment saying which route you used and why.

- [ ] **Step 4: Run it**

Run: `cd e2e && npx playwright test --project=seeded vod-catalogue-ingest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add e2e/tests/seeded/xc-ingest.spec.ts e2e/tests/seeded/vod-catalogue-ingest.spec.ts
```

then:

```bash
git commit -m "test(e2e): prove XC live and VOD catalogue ingest reach the database"
```

---

### Task 10: Plumbing proof 3 — one VOD byte read through `/proxy/vod/`

**Files:**
- Create: `e2e/tests/streaming/vod-byte-read.spec.ts`

**Interfaces:**
- Consumes: Task 9's ingest pattern; Playwright's built-in `request` context.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the spec**

```ts
import { test, expect } from '../../fixtures';

interface Page<T> { count: number; results: T[] }
interface MovieRow { id: number; uuid: string; name: string }

test('a VOD stream is delivered through /proxy/vod/ with seek metadata', async ({
  upstream,
  seed,
  api,
  waitFor,
  request,
}) => {
  const prefix = seed.generatedName('vodread');
  const scenario = await upstream.scenario({
    xc: true,
    username: `${prefix}-user`,
    password: `${prefix}-pass`,
    vodCategories: [{ id: 1, name: `${prefix}-movies` }],
    vod: [{ id: 1, name: `${prefix}-movie`, year: 2020, categoryId: 1 }],
    series: 0,
  });

  const account = await seed.xcAccount(scenario, { enable_vod: true });
  expect((await waitFor.m3uRefreshComplete(account.id)).status).toBe('success');

  const movies = await waitFor.resource<Page<MovieRow>>(
    `/api/vod/movies/?search=${encodeURIComponent(prefix)}`,
    (body) => body.count === 1,
    { description: `the VOD movie ${prefix}-movie to be ingested`, timeoutMs: 120_000 }
  );
  const uuid = movies.results[0].uuid;

  // Playwright's `request` context, not the `api` fixture: `stream_vod` is
  // AllowAny and no real client of this surface carries a bearer token. It
  // follows the session-path redirect `stream_vod` issues on a first request,
  // which is where the actual bytes come from.
  const full = await request.get(`/proxy/vod/movie/${uuid}`);
  expect(full.status()).toBe(200);
  const headers = full.headers();
  // Both come from the provider's Content-Length. Without it,
  // multi_worker_connection_manager emits neither, and every seek a client
  // attempts is unbounded.
  expect(headers['accept-ranges']).toBe('bytes');
  const total = Number(headers['content-length']);
  expect(total).toBeGreaterThan(1024);
  const body = await full.body();
  expect(body.byteLength).toBe(total);
  // The asset is a real MP4: box size, then 'ftyp'.
  expect(body.subarray(4, 8).toString('ascii')).toBe('ftyp');

  // A mid-file Range, which is the thing the finite asset exists for.
  const partial = await request.get(`/proxy/vod/movie/${uuid}`, {
    headers: { Range: `bytes=100-199` },
  });
  expect(partial.status()).toBe(206);
  expect(partial.headers()['content-range']).toBe(`bytes 100-199/${total}`);
  const slice = await partial.body();
  expect(slice.byteLength).toBe(100);
  expect(slice).toEqual(body.subarray(100, 200));

  // One upstream connection per session, not per byte range: this is the
  // architecture that distinguishes VOD from the live ring buffer.
  const log = await upstream.log(scenario);
  const movieRequests = log.filter((entry) => entry.path?.includes('/movie/'));
  expect(movieRequests.length).toBeGreaterThan(0);
  expect(movieRequests.every((entry) => entry.status === 200 || entry.status === 206)).toBe(true);
});
```

- [ ] **Step 2: Run it**

Run: `cd e2e && npx playwright test --project=streaming vod-byte-read`
Expected: PASS.

If the second request returns 200 rather than 206, read `docker logs dispatcharr-e2e | grep VOD-` — the connection manager only validates and forwards a `Range` once it has learned `content_length`, so a 200 means the *first* request's `Content-Length` never reached it. That is a provider bug (Task 5), not a product one; do not adjust the assertion to match.

- [ ] **Step 3: Commit**

```bash
git add e2e/tests/streaming/vod-byte-read.spec.ts
```

then:

```bash
git commit -m "test(e2e): prove a VOD stream reaches a client through /proxy/vod/ with seek metadata"
```

---

### Task 11: Plumbing proofs 4 and 5 — catch-up layouts and the candidate cascade

Both proofs drive **proxy mode**, through the root XC catch-up routes, which authenticate with XC credentials in the URL and therefore need no JWT. Neither touches a global setting.

Two facts shape these specs, and both are easy to get backwards:

- **In proxy mode the client's layout is irrelevant.** `client_timeshift_url_layout` is used only in redirect mode; the proxy path always walks `build_timeshift_candidate_urls`' seven candidates, PATH shapes first. So the way to make a QUERY request reach the provider is to 404 the PATH layout, not to call `timeshift.php`. Redirect mode needs `CoreSettings`' default stream profile changed globally, which a 2-worker project cannot do safely — that is G10's, with a project decision of its own.
- **The winning candidate index is cached per account** (`_set_cached_format_index`). Proof 5 therefore uses its own account and says so.

**Files:**
- Create: `e2e/tests/streaming/catchup-path-layout.spec.ts`, `e2e/tests/streaming/catchup-cascade.spec.ts`

**Interfaces:**
- Consumes: `seed.xcUser()` and `xcQuery()` **from G5** — the root catch-up routes authenticate through `_authenticate_user`, which reads `User.custom_properties['xc_password']`. If G5 has not landed, this task is blocked; that is the dependency the roadmap records.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write a shared setup helper**

Put it in `e2e/tests/streaming/helpers.ts`, which already exists:

```ts
/**
 * An XC account whose ingested streams advertise catch-up, and a Channel
 * wired to them with `Channel.is_catchup` actually set.
 *
 * The second refresh is the point. `rollup_channel_catchup_fields` runs
 * *inside* `refresh_m3u_account` and rolls `Stream.is_catchup` up to every
 * channel holding a stream from that account — but only during a refresh, so
 * a channel created after the first one is still `is_catchup: false`.
 * PATCHing the field is possible (`ChannelSerializer` exposes it) and is the
 * fallback if this proves flaky, but it skips the ingest path these proofs
 * exist to exercise.
 */
export async function seedCatchupChannel(...)
```

It must: create an XC scenario with one explicitly named channel; `seed.xcAccount(scenario)`; `waitFor.m3uRefreshComplete`; find the ingested `Stream` by name; create a `Channel` wired to it; refresh again; then assert `channel.is_catchup === true` **before returning**, so a failure names this link rather than surfacing later as a bare 400 from the catch-up route.

It must also wait for the provider timezone to reach the database, because `refresh_account_profiles` runs asynchronously:

```ts
  // server_info.timezone lands on the default profile via a .delay()'d task,
  // after the refresh this test already waited on. Reading it too early sees
  // null — and because convert_timestamp_to_provider_tz treats null exactly
  // like "UTC", the timestamp assertion would then pass for the wrong reason.
  await waitFor.resource<M3uAccount>(
    `/api/m3u/accounts/${account.id}/`,
    (body) =>
      body.profiles.some(
        (profile) => profile.custom_properties?.server_info?.timezone === 'UTC'
      ),
    { description: 'the XC account profile to carry server_info.timezone' }
  );
```

`e2e/fixtures/types.ts`'s `M3uAccount` has **no `profiles` field** today, even though
`M3UAccountSerializer` exposes one read-only. Add it in this task rather than casting:

```ts
/** Read-only nested `M3UAccountProfileSerializer` rows on `M3UAccountSerializer`. */
export type M3uAccountProfile = {
  id: number;
  name: string;
  is_default: boolean;
  is_active: boolean;
  max_streams: number;
  search_pattern: string;
  replace_pattern: string;
  /**
   * `refresh_account_profiles` merges `Client.get_account_info()` in here, so
   * `user_info` and `server_info` appear only *after* that task runs — which
   * is a separate `.delay()` from the refresh a test waited on.
   */
  custom_properties: {
    user_info?: Record<string, unknown>;
    server_info?: { timezone?: string; [key: string]: unknown };
    [key: string]: unknown;
  } | null;
};
```

and add `profiles: M3uAccountProfile[]` to `M3uAccount`, which is what the snippet above reads.
Both go next to the existing `M3uAccount` declaration, whose comment convention (naming the
serializer each field came from) applies here too.

- [ ] **Step 2: Write `catchup-path-layout.spec.ts`**

```ts
import { test, expect } from '../../fixtures';
import { seedCatchupChannel } from './helpers';

test('a catch-up request reaches the provider in the PATH layout with the right parameters', async ({
  upstream, seed, api, waitFor, streamClient,
}) => {
  const { scenario, channel, providerStreamId, xcUser } = await seedCatchupChannel({
    upstream, seed, api, waitFor,
  });

  // Two hours ago, on a whole minute — the archive is not time-addressable,
  // so the instant is arbitrary; what matters is that the provider records
  // the one we asked for.
  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));

  // The root XC PATH route: /timeshift/<user>/<pass>/<duration>/<start>/<Channel.id>.ts
  // Note Channel.id, the numeric PK — unlike every live_proxy endpoint, which
  // is keyed by the UUID.
  await streamClient.open(
    `/timeshift/${xcUser.username}/${xcUser.xcPassword}/60/${start}/${channel.id}.ts`
  );
  const bytes = await streamClient.readPackets(20);
  expect(bytes[0]).toBe(0x47);
  await streamClient.close();

  const log = await upstream.log(scenario);
  const asked = log.filter((entry) => entry.path?.includes('/timeshift/'));
  expect(asked.length).toBeGreaterThan(0);
  const path = asked[0].path!;

  expect(path).toContain(`/${scenario.username}/${scenario.password}/`);
  // 60 requested + DURATION_BUFFER_MINUTES (5). Assert the derived value: the
  // product pads every client hint because provider archives lag live.
  expect(path).toContain('/65/');
  expect(path).toMatch(new RegExp(`/${providerStreamId}\\.ts$`));
  // Unchanged, because the provider declares server_info.timezone "UTC" and
  // convert_timestamp_to_provider_tz skips conversion for exactly that value.
  expect(path).toContain(start);
});
```

`catchupTimestamp(date)` formats `%Y-%m-%d:%H-%M` — put it in `helpers.ts` next to `seedCatchupChannel`, with a comment naming `normalize_catchup_timestamp_input` as the set of shapes Dispatcharr accepts from a client.

- [ ] **Step 3: Write `catchup-cascade.spec.ts`**

```ts
test('the candidate cascade falls through to the QUERY layout when PATH 404s', async ({
  upstream, seed, api, waitFor, streamClient,
}) => {
  // A FRESH account, deliberately: _set_cached_format_index caches the winning
  // candidate index per account in the Django cache, and a reused account
  // would start the walk at whatever last worked rather than at candidate 0.
  const { scenario, channel, xcUser } = await seedCatchupChannel({ upstream, seed, api, waitFor });

  await upstream.fault(scenario, 'catchup-layout-404', { layout: 'path' });

  const start = catchupTimestamp(new Date(Date.now() - 2 * 60 * 60 * 1000));
  await streamClient.open(
    `/timeshift/${xcUser.username}/${xcUser.xcPassword}/60/${start}/${channel.id}.ts`
  );
  expect((await streamClient.readPackets(20))[0]).toBe(0x47);
  await streamClient.close();

  const log = await upstream.log(scenario);
  const attempts = log.filter(
    (entry) => entry.kind === 'request' && entry.path?.includes('timeshift')
  );

  // build_timeshift_candidate_urls emits three PATH shapes, then four QUERY
  // shapes. With PATH blocked, a correct cascade shows all three PATH attempts
  // 404 and then a QUERY attempt succeed.
  const pathAttempts = attempts.filter((e) => e.path!.includes('/timeshift/'));
  const queryAttempts = attempts.filter((e) => e.path!.includes('timeshift.php'));

  expect(pathAttempts).toHaveLength(3);
  expect(pathAttempts.every((e) => e.status === 404)).toBe(true);
  expect(queryAttempts.length).toBeGreaterThan(0);
  expect(queryAttempts[0].status).toBe(200);
  // The QUERY attempt carried the same parameters the PATH ones did.
  expect(queryAttempts[0].path).toContain(`username=${scenario.username}`);
  expect(queryAttempts[0].path).toContain('duration=65');
});
```

- [ ] **Step 4: Run them**

Run: `cd e2e && npx playwright test --project=streaming catchup-`
Expected: PASS.

If the client gets a bare 400 with no provider request at all, the failure is one of the five catch-up preconditions, not the cascade — `seedCatchupChannel` asserts four of them, so check the fifth (`is_catchup_enabled`, i.e. `CoreSettings.get_catchup_enabled()` and the user's own `custom_properties.catchup_enabled`) before touching anything else.

If `pathAttempts` is 1 rather than 3, the provider recognised only one timestamp shape — a Task 6 bug, not a product one. Re-run `npx vitest run test/xc-catchup.test.ts`.

- [ ] **Step 5: Commit**

```bash
git add e2e/tests/streaming/helpers.ts e2e/tests/streaming/catchup-path-layout.spec.ts e2e/tests/streaming/catchup-cascade.spec.ts
```

then:

```bash
git commit -m "test(e2e): prove catch-up URLs reach the provider and the candidate cascade falls back"
```

---

### Task 12: Documentation and the coverage inventory

The definition of done for this goal is that a G9 or G10 agent can write their tests without opening `e2e-upstream/src/`. That is a documentation deliverable, not a follow-up.

**Files:**
- Modify: `e2e-upstream/README.md`, `e2e/README.md`, `e2e/COVERAGE.md`, `CONTEXT.md`

- [ ] **Step 1: Extend `e2e-upstream/README.md`**

- **Provider-facing endpoints**: add the six XC routes with the product symbol that builds each one (`Client.get_stream_url`, `M3UMovieRelation.get_stream_url`, `build_timeshift_url_format_b`, and so on).
- **Control API**: document the new `POST /scenarios` fields — `xc`, `liveCategories`, `vodCategories`, `seriesCategories`, `vod`, `series`, `account` — and that `xc: true` requires `username`, with the reason (`credentialsMatch` accepts everything without one).
- **Fault catalogue**: four new rows in the existing table, each with its `appliedTo: 0` note. `range-unsupported`'s row must say it is **scenario-wide only** — a VOD id is not a channel id, so the `channel` filter has no meaning there.
- **Scenario defaults**: extend the existing "read before asserting on names" warning to movie titles, series names and category names, and state plainly *why it is worse than for channels*: `VODCategory` is unique on `(name, category_type)` globally, and `Movie`/`Series` are matched across all accounts by TMDB → IMDB → `(name, year)`, so two workers running the default catalogue share one row.
- **A new "Catch-up" section**: both layouts, all four timestamp shapes, the parameters recorded in the log — and, in bold, that **the archive is not time-addressable**: the same loop is served whatever `start` asked for, so nothing here can prove Dispatcharr seeks to the right moment, only that it asked for the right one.
- **A new "The VOD asset" section**: finite, `Content-Length`, `Accept-Ranges`, 206 with `Content-Range`, 416 on an unsatisfiable range; that it is a second asset and not a mode of the TS loop; and that the loop deliberately has no `Content-Length` because it has no end.

- [ ] **Step 2: Extend `e2e/README.md`**

In "The fake upstream provider" section, add a paragraph on XC scenarios: `upstream.xcUrl()` and `seed.xcAccount()`, the no-`credentialQuery` rule and its reason, and the two asynchrony facts a test author will otherwise be bitten by — **VOD ingest is a separate task fired after the M3U refresh completes**, and **`server_info.timezone` reaches the profile through a second `.delay()`'d task**.

- [ ] **Step 3: Update `e2e/COVERAGE.md`**

Flip the nine `G8` rows added in this branch's first commit from `todo` to `done`, except the time-addressability gap row, which stays `todo` and is owned by G10. Add a prose block below the table, matching the existing G1/G2/G4 blocks, listing which spec covers which row.

**Also perform the rebase resolution the spec's Siblings section specifies**, if G5 has already landed: re-label G5's catch-up and `catchup=` gap rows to G10, its "XC VOD and series actions against a real catalogue" row to G9, and delete its "Fake provider speaks Xtream Codes" row, which this goal's five build rows supersede.

- [ ] **Step 4: Extend `CONTEXT.md`**

Two entries, both because the words already mean something else in this codebase:

- **Category** — an Xtream Codes grouping. Live categories become **Channel Groups**; VOD and series categories become **VOD Categories**. Never a "profile".
- **Catch-up / timeshift** — the two words are used interchangeably by the product (`apps/timeshift/` serves `/proxy/catchup/`). Prefer **catch-up** for the feature and **timeshift** only when naming a symbol that already spells it that way.

- [ ] **Step 5: Verify the whole thing**

```bash
cd e2e-upstream && npm run typecheck && npx vitest run
cd ../e2e && npm run typecheck
npx playwright test --project=seeded
npx playwright test --project=streaming
```

Expected: all green. **If Docker or the container is down, say the tests did not run — do not describe the work as verified.**

- [ ] **Step 6: Commit**

```bash
git add e2e-upstream/README.md e2e/README.md e2e/COVERAGE.md CONTEXT.md
```

then:

```bash
git commit -m "docs(e2e): document the XC surface, the VOD asset and the catch-up layouts"
```

---

## Self-review

**Spec coverage.** Every spec section maps to a task: scenario declaration → Task 1; the auth envelope and route seam → Task 2; "Required XC payload shapes" → Task 3 (and it is quoted as normative in that file's header); the three playback route shapes → Tasks 4 and 5; the two catch-up routes → Task 6; the four new faults → Task 7; the fixture additions → Task 8; the five-row test inventory → Tasks 9–11; the README/COVERAGE/CONTEXT deliverables → Task 12. D20 and D21 are enforced by the Global Constraints rather than by a task, deliberately — they are prohibitions, and the check is that no task's file list names those three files.

**Two decisions that changed shape while planning, both recorded in the tasks that carry them.** The spec's proof 4 said "a catch-up URL arriving at the provider in each layout"; in proxy mode the client's layout has no effect on the provider URL — `client_timeshift_url_layout` is redirect-mode only — so Task 11 gets both layouts to the provider by 404ing PATH rather than by calling `timeshift.php`, and redirect mode moves to G10 with a project decision of its own. And Task 4 extracts `serveChannelStream` from `server.ts` rather than duplicating the fault pipeline three times; the extraction is behaviour-preserving and the existing `faults.test.ts` is what proves it.

**Placeholders.** None: every code step carries real code, every "extend the README" step names the sections and the sentences they must contain, and the two places where a route or serializer field must be confirmed against the product before writing (`/api/vod/episodes/?search=`, `M3UAccountProfile.custom_properties` on the account serializer) say so explicitly and give the fallback.

**Type consistency.** `serveChannelStream` and `serveVodAsset` are named identically in Tasks 4, 5, 6 and 7 and are reached through `XcContext` in all of them (`serveVodAsset` being `src/vod-asset.ts`'s `serveFiniteAsset` with the lazily-loaded asset bound), never imported from `server.ts` — the cycle `src/errors.ts` exists to avoid. `FaultName`, `FaultOptions.layout`, `UpstreamScenario.username`/`password` and the `CategorySpec`/`MovieSpec`/`SeriesSpec` shapes are declared once in Task 1 and mirrored once in Task 8, with the provider and fixture spellings matching field for field.
