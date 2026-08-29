# G5 — Client Output Surfaces Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that everything Dispatcharr hands a client — an M3U playlist, an XMLTV guide, an HDHomeRun lineup, an Xtream Codes catalogue — is well-formed, correctly scoped to whoever asked for it, and that at least one advertised stream URL actually delivers bytes.

**Architecture:** No new Playwright project and no CI matrix job. Seventeen fast HTTP tests go in the existing `seeded` project (4 workers, 30s timeout); the two rows that need real bytes go in the existing `streaming` project (2 workers, 300s timeout, fake upstream provider available). Client-facing surfaces are driven through Playwright's built-in `request` context rather than the `api` fixture, because no real client of these surfaces carries a bearer token and because `ApiClient` retries on 401 — which is exactly the status the Xtream rejection rows assert on.

**Tech Stack:** TypeScript, Playwright 1.62.x, Node 24, the G1 fixture set (`api`, `seed`, `waitFor`, `streamClient`, `upstream`, `adminPage`), the G2 fake provider, Docker.

**Spec:** `docs/superpowers/specs/2026-08-29-e2e-client-output-surfaces-design.md` — read it before Task 1. The plan argues from it; every task cites the decisions it implements.

## Global Constraints

Copied from the spec and the programme rules. Every task's requirements implicitly include this section.

- **Drive client-facing surfaces with Playwright's built-in `request` fixture, never `api`.** (D3.) `api` is for seeding and admin reads only. `ApiClient.send` retries once through a token refresh **on any 401**, and Xtream answers bad credentials with 401 — so an XC rejection driven through `api` spends a pointless refresh and can throw a refresh error instead of returning the status under test. `request` is a built-in of the extended `test`, so `async ({ request, seed }) => …` just works.
- **The XC username is the Django username.** There is no `xc_username` custom property anywhere in the product. `xc_get_user`, `stream_xc` and timeshift's `_authenticate_user` all do `get_object_or_404(User, username=…)` then compare `custom_properties["xc_password"]`.
- **`get_short_epg` and `get_simple_data_table` require `?stream_id=<channel.id>`** — the numeric Channel primary key, **not** the UUID. `xc_get_epg` raises `Http404` when it is missing or non-integer. (Contrast `/proxy/ts/stream/<uuid>`, which is UUID-keyed. Both identifiers are in play in this goal; do not mix them.)
- **`/output/epg` is served from a 300-second Redis chunk cache** whose key is `profile:username:d=:p=:logos=:tvgid=:origin=` — **the raw query string is not in it**, so an arbitrary `?e2e=` parameter does *not* bust it. Every anonymous `/output/epg` fetch must pass a per-test `?days=<n>`. The XC route (`xmltv.php`) needs nothing: the key already contains the username, and `seed.xcUser()` generates a fresh one per test. (D7.)
- **Never assert a global count or an unfiltered list.** (Roadmap rule 4.) Four workers share one container; the M3U, the XMLTV guide and the HDHR lineup each render **every channel on the instance**, and a seeded Channel Profile automatically contains every other worker's channels. Locate your own rows by the name `seed` generated and assert on those.
- **`seed.channel()` lands in a shared "Default Group" unless given one.** `ChannelSerializer.create` auto-assigns it. Any test that asserts on a *category* must create its own group with `seed.channelGroup()`. (D9.)
- **Product defects are asserted correct, marked `test.fail()` with the defect's symbol named in a comment, and filed as issues — never patched.** Issues go to `gh issue create --repo D10Scot/Dispatcharr`; the explicit `--repo` flag is mandatory, because this checkout is a fork and `gh` without it resolves to upstream's public tracker.
- **XC passwords are generated per user and thrown away with them.** (D13.) Dispatcharr logs full provider URLs including `?password=` at INFO, and the CI workflow's failure step prints `docker logs dispatcharr-e2e` into the log. Never introduce a fixed XC credential here.
- **Exactly one login is spent by this whole goal** — issue #12's test (Task 12). The call site must say so in a comment. Everything else, including the entire authorization matrix, costs zero: XC authentication is query-string credentials against an unthrottled path.
- **The typecheck hook is blocking.** Any edit to `e2e/**/*.ts` runs `tsc --noEmit` for that package and blocks on failure. Run `cd e2e && npm ci` first or it degrades to a loud note.
- **G5 must not touch `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml` or `scripts/e2e_up.sh`.** (D2.) The unmerged G7 branch edits all three, and the workflow re-runs the zizmor hook, which blocks on every finding in the file.
- **G3 is in flight on `e2e/fixtures/seed.ts`, `e2e/fixtures/types.ts` and `e2e/fixtures/index.ts`.** Append only, at the end of the existing lists.
- **Import map — every shared symbol comes from exactly one place. Never redefine one locally.**

  | Symbol | From |
  |---|---|
  | `test`, `expect`, `expectTsAligned`, `TS_PACKET_SIZE`, `SEEDED_USER_PASSWORD` | `'../../fixtures'` |
  | `parseM3u`, `parseXmltv`, `xcQuery`, `expectWellFormedXml` | `'../../fixtures'` (defined in `fixtures/parse.ts`, re-exported) |
  | `Channel`, `ChannelGroup`, `User`, `XcUser`, `M3uEntry`, `XmltvProgramme` | `'../../fixtures'` (types, defined in `fixtures/types.ts`) |

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `e2e/fixtures/parse.ts` | `parseM3u`, `parseXmltv`, `xcQuery`, `expectWellFormedXml` — the only place that knows those wire formats |
| `e2e/tests/seeded/output-m3u.spec.ts` | Rows 1–2 — `/output/m3u` and its profile-scoped form |
| `e2e/tests/seeded/output-epg.spec.ts` | Row 3 — `/output/epg` is valid XMLTV with programmes |
| `e2e/tests/seeded/hdhr.spec.ts` | Rows 4, 5, 17 — the four HDHomeRun endpoints, and the known bug |
| `e2e/tests/seeded/xc-auth.spec.ts` | Rows 6, 19 — the XC handshake, and the known bug |
| `e2e/tests/seeded/xc-live.spec.ts` | Rows 7, 8, 15 — the XC live catalogue and EPG, and the known bug |
| `e2e/tests/seeded/xc-vod-empty.spec.ts` | Row 9 — six VOD/series paths on an empty catalogue |
| `e2e/tests/seeded/xc-output.spec.ts` | Row 10 — `get.php` and `xmltv.php` at the site root |
| `e2e/tests/seeded/output-authorization.spec.ts` | Rows 11, 12, 13 — the matrix, `hide_adult_content`, and the three unauthenticated surfaces |
| `e2e/tests/seeded/token-refresh-deleted-user.spec.ts` | Row 18 — issue #12; the one login this goal spends |
| `e2e/tests/streaming/output-m3u-stream.spec.ts` | Row 14 — one advertised URL delivers bytes |
| `e2e/tests/streaming/hidden-channel-streamable.spec.ts` | Row 16 — the known bug, byte-level half |

**Modified:**

| Path | Change |
|---|---|
| `e2e/fixtures/seed.ts` | Add `channelGroup()` and `xcUser()` |
| `e2e/fixtures/types.ts` | Add `ChannelGroup`, `ChannelGroupOverrides`, `XcUser`, `M3uEntry`, `M3uPlaylist`, `XmltvChannel`, `XmltvProgramme`, `XmltvDocument` |
| `e2e/fixtures/index.ts` | Export the four `parse.ts` functions and the seven new types; extend the `seed` inventory in the header comment |
| `e2e/COVERAGE.md` | Eleven G5 rows → `done`; add four `known-bug` rows; list the spec files |
| `e2e/README.md` | Add the new fixture exports to the tables; correct the stale "three-job matrix" line |

---

### Task 1: Seed factories for channel groups and XC users

Implements D4, D9 and D13. Every later task uses `xcUser`, and three use `channelGroup`, so this lands first — and it touches `seed.ts`, which G3 also edits, so landing early shrinks the conflict window.

**Files:**
- Modify: `e2e/fixtures/seed.ts`, `e2e/fixtures/types.ts`, `e2e/fixtures/index.ts`
- Test: `e2e/tests/seeded/seed-fixture.spec.ts`

**Interfaces:**
- Consumes: `Seeder.create`, `Seeder.generatedName`, `Seeder.user` — all existing.
- Produces:
  - `seed.channelGroup(overrides?: ChannelGroupOverrides): Promise<ChannelGroup>`
  - `seed.xcUser(overrides?: UserOverrides): Promise<XcUser>`
  - `type ChannelGroup = { id: number; name: string; channel_count: number; m3u_account_count: number }`
  - `type ChannelGroupOverrides = Record<string, never>`
  - `type XcUser = User & { xcPassword: string }`

- [ ] **Step 1: Add the types**

In `e2e/fixtures/types.ts`, after the `ChannelProfile` type:

```ts
/**
 * `/api/channels/groups/` — the grouping the Xtream API calls a *category*
 * and the M3U calls `group-title`. Not a Channel Profile: a group is
 * descriptive, a Channel Profile is an authorization membership. See
 * CONTEXT.md.
 *
 * `channel_count` and `m3u_account_count` are `SerializerMethodField`s on
 * `ChannelGroupSerializer`, so they are read-only — which is why
 * {@link ChannelGroupOverrides} is empty.
 */
export type ChannelGroup = {
  id: number;
  name: string;
  channel_count: number;
  m3u_account_count: number;
};

/**
 * `ChannelGroupSerializer` exposes `id`, `name` and two method fields, so
 * once the generated `name` is removed there is nothing left to override —
 * exactly the shape {@link ChannelProfileOverrides} has, and
 * `Record<string, never>` for the same reason: TypeScript applies no
 * excess-property check against a bare `{}`.
 */
export type ChannelGroupOverrides = Record<string, never>;

/**
 * A user who can authenticate against the Xtream Codes surface.
 *
 * **The XC username is the Django username.** There is no `xc_username`
 * custom property anywhere in the product: `xc_get_user`
 * (`apps/output/views.py`), `stream_xc` (`apps/proxy/live_proxy/views.py`)
 * and `_authenticate_user` (`apps/timeshift/views.py`) all look the user up
 * by `username` and then compare `custom_properties["xc_password"]` with
 * `!=`. The `xc_username` locals in `apps/timeshift/views.py` are *provider*
 * credentials from `get_transformed_credentials` and are unrelated.
 *
 * `xcPassword` is carried here rather than read back from the API because
 * `UserSerializer` does not return `custom_properties`.
 */
export type XcUser = User & { xcPassword: string };
```

- [ ] **Step 2: Write the failing tests**

Append to `e2e/tests/seeded/seed-fixture.spec.ts`:

```ts
test('seed.channelGroup creates a group with a generated name', async ({ seed }) => {
  const group = await seed.channelGroup();

  expect(group.id).toBeGreaterThan(0);
  expect(group.name).toMatch(/^e2e-w\d+-/);
});

test('seed.xcUser carries an xc_password the XC surface accepts', async ({
  seed,
  request,
}) => {
  const user = await seed.xcUser();

  expect(user.username).toMatch(/^e2e-w\d+-/);
  expect(user.xcPassword).toMatch(/^e2e-w\d+-/);
  // Not SEEDED_USER_PASSWORD: the XC password is a *separate* credential
  // living in custom_properties, and reusing the login password would make a
  // test that confused the two pass by accident.
  expect(user.xcPassword).not.toBe(SEEDED_USER_PASSWORD);

  // The product agrees the credential works. This is the whole point of the
  // factory, and it is asserted here rather than in every XC spec.
  const res = await request.get(`/player_api.php${xcQuery(user)}`);
  expect(res.status()).toBe(200);
});

test('seed.xcUser ignores an attempt to override xc_password', async ({ seed }) => {
  // xc_password is spread AFTER the caller's custom_properties, the same
  // ordering rule the generated identity fields use. A cast is the only way
  // to even attempt this, which is the point of the test.
  const user = await seed.xcUser({
    custom_properties: { xc_password: 'not-this' },
  });
  expect(user.xcPassword).not.toBe('not-this');
});
```

Add `SEEDED_USER_PASSWORD` and `xcQuery` to the file's existing import from `'../../fixtures'`.

- [ ] **Step 3: Run them and confirm they fail**

Run: `cd e2e && npx playwright test --project=seeded seed-fixture --grep "channelGroup|xcUser"`
Expected: FAIL — `seed.channelGroup is not a function`, and `xcQuery` is not exported.

- [ ] **Step 4: Implement both factories**

In `e2e/fixtures/seed.ts`, after `channelProfile()`:

```ts
  /**
   * `ChannelGroupSerializer` exposes one writable field, `name`, and this
   * factory generates it — so {@link ChannelGroupOverrides} is empty, exactly
   * as `channelProfile()`'s is.
   *
   * Reach for this whenever a test asserts on an Xtream *category* or an M3U
   * `group-title`. `seed.channel()` with no `channel_group_id` is
   * auto-assigned a shared "Default Group" by `ChannelSerializer.create`, and
   * four parallel workers all writing into that one group makes any
   * category-level assertion meaningless.
   */
  channelGroup(overrides: ChannelGroupOverrides = {}): Promise<ChannelGroup> {
    const body: { name: string } = {
      ...overrides,
      name: this.generatedName('channelGroup'),
    };
    return this.create<ChannelGroup>('/api/channels/groups/', 'channelGroup', body);
  }

  /**
   * A user who can authenticate against the Xtream Codes surface.
   *
   * The password is generated per user and thrown away with the run. That is
   * deliberate and load-bearing, not incidental tidiness: XC credentials
   * travel in query strings across four surfaces, Dispatcharr logs full
   * provider URLs including `?password=` at INFO, and
   * `.github/workflows/e2e-tests.yml`'s failure step prints
   * `docker logs dispatcharr-e2e` straight into the CI log. A throwaway
   * credential makes both of those harmless. **Do not introduce a fixed XC
   * password here.**
   *
   * `xc_password` is spread after the caller's `custom_properties` so a
   * caller cannot substitute one — the same ordering rule the generated
   * identity fields use. Other custom properties (`hide_adult_content`,
   * `epg_days`) pass through untouched.
   */
  async xcUser(overrides: UserOverrides = {}): Promise<XcUser> {
    const xcPassword = this.generatedName('xc-secret');
    const user = await this.user({
      ...overrides,
      custom_properties: {
        ...(overrides.custom_properties ?? {}),
        xc_password: xcPassword,
      },
    });
    return { ...user, xcPassword };
  }
```

Add `ChannelGroup`, `ChannelGroupOverrides` and `XcUser` to the type import at the top of `seed.ts`.

- [ ] **Step 5: Add `xcQuery` and create `parse.ts`'s first export**

Create `e2e/fixtures/parse.ts` with just this for now — the parsers arrive in Task 2:

```ts
import type { XcUser } from './types';

/**
 * The credential query string every Xtream endpoint takes.
 *
 * Four surfaces need this (`player_api.php`, `panel_api.php`, `get.php`,
 * `xmltv.php`) and two more embed it in a path. Hand-rolling it at each call
 * site is four chances to get the encoding wrong — a generated username
 * contains `@` and `.`, both of which must survive.
 *
 * `extra` carries the per-call parameters: `{ action: 'get_live_streams' }`,
 * `{ action: 'get_short_epg', stream_id: channel.id }`.
 */
export function xcQuery(
  user: XcUser,
  extra: Record<string, string | number> = {}
): string {
  const params = new URLSearchParams({
    username: user.username,
    password: user.xcPassword,
  });
  for (const [key, value] of Object.entries(extra)) {
    params.set(key, String(value));
  }
  return `?${params.toString()}`;
}
```

Export it from `e2e/fixtures/index.ts` alongside the existing re-exports, and add the two new factories plus `ChannelGroup`/`XcUser` to that file's `seed` inventory in the header comment.

- [ ] **Step 6: Run them and confirm they pass**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded seed-fixture`
Expected: PASS, every test in the file.

- [ ] **Step 7: Typecheck and commit**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Stage `e2e/fixtures/seed.ts`, `e2e/fixtures/types.ts`, `e2e/fixtures/parse.ts`, `e2e/fixtures/index.ts`, `e2e/tests/seeded/seed-fixture.spec.ts` and commit as `test(e2e): add channelGroup and xcUser seed factories`.

---

### Task 2: The M3U and XMLTV parsers

Implements D8. Every output row consumes these, so they land before any of them, and they are tested against literal fixtures rather than against a live response — a parser proved only by the endpoint it parses tells you nothing when the endpoint changes.

**Files:**
- Modify: `e2e/fixtures/parse.ts`, `e2e/fixtures/types.ts`, `e2e/fixtures/index.ts`
- Test: `e2e/tests/seeded/parse-fixture.spec.ts` (create)

**Interfaces:**
- Produces:
  - `parseM3u(text: string): M3uPlaylist`
  - `parseXmltv(text: string): XmltvDocument`
  - `expectWellFormedXml(page: Page, xml: string): Promise<void>`
  - `type M3uEntry = { attributes: Record<string, string>; title: string; url: string }`
  - `type M3uPlaylist = { header: Record<string, string>; entries: M3uEntry[] }`
  - `type XmltvChannel = { id: string; displayNames: string[] }`
  - `type XmltvProgramme = { channel: string; start: string; stop: string; title: string }`
  - `type XmltvDocument = { channels: XmltvChannel[]; programmes: XmltvProgramme[] }`

- [ ] **Step 1: Add the types**

Append to `e2e/fixtures/types.ts`:

```ts
/** One `#EXTINF` line plus the URL beneath it. */
export type M3uEntry = {
  /**
   * The quoted `key="value"` attributes on the `#EXTINF` line. Dispatcharr
   * emits `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, optionally
   * `tvc-guide-stationid`, and `group-title` — and nothing else. There is
   * deliberately no `catchup=`; catch-up is advertised only through the XC
   * `tv_archive` field. See the G8 gap row in COVERAGE.md.
   */
  attributes: Record<string, string>;
  /** Everything after the comma that ends the attribute list. */
  title: string;
  url: string;
};

export type M3uPlaylist = {
  /** Attributes on the `#EXTM3U` line: `x-tvg-url` and `url-tvg`. */
  header: Record<string, string>;
  entries: M3uEntry[];
};

export type XmltvChannel = { id: string; displayNames: string[] };

/** `start`/`stop` are XMLTV timestamps, e.g. `20260829120000 +0000`. */
export type XmltvProgramme = {
  channel: string;
  start: string;
  stop: string;
  title: string;
};

export type XmltvDocument = {
  channels: XmltvChannel[];
  programmes: XmltvProgramme[];
};
```

- [ ] **Step 2: Write the failing tests**

Create `e2e/tests/seeded/parse-fixture.spec.ts`:

```ts
import { test, expect, parseM3u, parseXmltv, expectWellFormedXml } from '../../fixtures';

const PLAYLIST = [
  '#EXTM3U x-tvg-url="http://h:9191/output/epg" url-tvg="http://h:9191/output/epg"',
  '#EXTINF:-1 tvg-id="42" tvg-name="News, Live" tvg-logo="" tvg-chno="42" group-title="World",News, Live',
  'http://h:9191/proxy/ts/stream/2a5d0f5e-0000-4000-8000-000000000001',
  '#EXTINF:-1 tvg-id="43" tvg-name="Sport" tvg-logo="http://h/l.png" tvg-chno="43" tvc-guide-stationid="X1" group-title="World",Sport',
  'http://h:9191/proxy/ts/stream/2a5d0f5e-0000-4000-8000-000000000002',
  '',
].join('\n');

test('parseM3u reads the header attributes', () => {
  const playlist = parseM3u(PLAYLIST);
  expect(playlist.header['x-tvg-url']).toBe('http://h:9191/output/epg');
  expect(playlist.header['url-tvg']).toBe('http://h:9191/output/epg');
});

test('parseM3u pairs each EXTINF with the URL beneath it', () => {
  const playlist = parseM3u(PLAYLIST);
  expect(playlist.entries).toHaveLength(2);
  expect(playlist.entries[0].attributes['tvg-chno']).toBe('42');
  expect(playlist.entries[0].url).toBe(
    'http://h:9191/proxy/ts/stream/2a5d0f5e-0000-4000-8000-000000000001'
  );
  expect(playlist.entries[1].attributes['tvc-guide-stationid']).toBe('X1');
});

test('parseM3u keeps a comma inside the title', () => {
  // The title is everything after the comma that FOLLOWS the last quoted
  // attribute. A naive lastIndexOf(',') would return "Live" here, silently
  // truncating every channel whose name contains a comma.
  expect(parseM3u(PLAYLIST).entries[0].title).toBe('News, Live');
});

test('parseM3u rejects a body that is not a playlist', () => {
  expect(() => parseM3u('<html>nope</html>')).toThrow(/not an M3U playlist/);
});

test('parseM3u rejects an EXTINF with no URL beneath it', () => {
  expect(() =>
    parseM3u('#EXTM3U\n#EXTINF:-1 tvg-id="1",A\n#EXTINF:-1 tvg-id="2",B\nhttp://h/2')
  ).toThrow(/not followed by a URL/);
});

const GUIDE = [
  '<?xml version="1.0" encoding="UTF-8"?>',
  '<tv generator-info-name="Dispatcharr">',
  '  <channel id="42">',
  '    <display-name>News &amp; Weather</display-name>',
  '    <icon src="" />',
  '  </channel>',
  '  <programme start="20260829120000 +0000" stop="20260829160000 +0000" channel="42">',
  '    <title>Morning &lt;Show&gt;</title>',
  '    <desc>Words</desc>',
  '  </programme>',
  '</tv>',
].join('\n');

test('parseXmltv reads channels and decodes entities', () => {
  const guide = parseXmltv(GUIDE);
  expect(guide.channels).toHaveLength(1);
  expect(guide.channels[0].id).toBe('42');
  expect(guide.channels[0].displayNames).toEqual(['News & Weather']);
});

test('parseXmltv reads programmes with their channel and title', () => {
  const guide = parseXmltv(GUIDE);
  expect(guide.programmes).toHaveLength(1);
  expect(guide.programmes[0].channel).toBe('42');
  expect(guide.programmes[0].start).toBe('20260829120000 +0000');
  expect(guide.programmes[0].title).toBe('Morning <Show>');
});

test('expectWellFormedXml accepts valid XML', async ({ adminPage }) => {
  await expectWellFormedXml(adminPage, GUIDE);
});

test('expectWellFormedXml rejects malformed XML', async ({ adminPage }) => {
  // Not vacuous: a helper that passes on anything reads as coverage and is
  // worse than no helper. `<tv>` is never closed.
  await expect(expectWellFormedXml(adminPage, '<tv><channel id="1">')).rejects.toThrow();
});
```

- [ ] **Step 3: Run them and confirm they fail**

Run: `cd e2e && npx playwright test --project=seeded parse-fixture`
Expected: FAIL — `parseM3u` is not exported.

- [ ] **Step 4: Implement the parsers**

Append to `e2e/fixtures/parse.ts`:

```ts
import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import type {
  M3uEntry,
  M3uPlaylist,
  XmltvChannel,
  XmltvDocument,
  XmltvProgramme,
} from './types';

/**
 * These two parsers are deliberately SHALLOW. They read the attributes and
 * elements this suite asserts on, and they are not M3U or XMLTV validators —
 * a body they accept is not thereby proved well-formed.
 *
 * `e2e/package.json` carries no XML or M3U dependency, and adding one to read
 * a handful of elements is a supply-chain decision out of proportion to the
 * need. Where a real *validity* verdict is wanted, use
 * {@link expectWellFormedXml}, which hands the document to the browser's own
 * DOMParser — a real XML parser this suite already has.
 */

const ATTRIBUTE = /([A-Za-z0-9_-]+)="([^"]*)"/g;

function attributesOf(line: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const match of line.matchAll(ATTRIBUTE)) {
    out[match[1]] = match[2];
  }
  return out;
}

export function parseM3u(text: string): M3uPlaylist {
  const lines = text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  if (lines.length === 0 || !lines[0].startsWith('#EXTM3U')) {
    throw new Error(
      `not an M3U playlist: the first line was ${JSON.stringify(lines[0] ?? '')}`
    );
  }

  const entries: M3uEntry[] = [];
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i];
    if (!line.startsWith('#EXTINF:')) continue;

    const url = lines[i + 1];
    if (url === undefined || url.startsWith('#')) {
      throw new Error(`#EXTINF is not followed by a URL: ${line}`);
    }

    // The title starts after the comma that follows the LAST quoted
    // attribute. Searching from the last quote rather than from the end of
    // the line is what keeps a comma inside a channel name intact —
    // group-title="World",News, Live must yield "News, Live", not "Live".
    const lastQuote = line.lastIndexOf('"');
    const comma = line.indexOf(',', lastQuote === -1 ? line.indexOf(':') : lastQuote);

    entries.push({
      attributes: attributesOf(line),
      title: comma === -1 ? '' : line.slice(comma + 1),
      url,
    });
    i++; // consume the URL line
  }

  return { header: attributesOf(lines[0]), entries };
}

/**
 * `html.escape(..., quote=True)` is what Dispatcharr writes with, so these
 * five are the whole set it can emit. `&amp;` is decoded last, or a body
 * containing the literal text `&amp;lt;` would decode twice.
 */
function decodeXmlEntities(value: string): string {
  return value
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&');
}

export function parseXmltv(text: string): XmltvDocument {
  const channels: XmltvChannel[] = [];
  for (const match of text.matchAll(/<channel id="([^"]*)">([\s\S]*?)<\/channel>/g)) {
    channels.push({
      id: decodeXmlEntities(match[1]),
      displayNames: [
        ...match[2].matchAll(/<display-name>([\s\S]*?)<\/display-name>/g),
      ].map((name) => decodeXmlEntities(name[1])),
    });
  }

  const programmes: XmltvProgramme[] = [];
  for (const match of text.matchAll(/<programme\b([^>]*)>([\s\S]*?)<\/programme>/g)) {
    const attributes = attributesOf(match[1]);
    const title = /<title[^>]*>([\s\S]*?)<\/title>/.exec(match[2]);
    programmes.push({
      channel: decodeXmlEntities(attributes.channel ?? ''),
      start: attributes.start ?? '',
      stop: attributes.stop ?? '',
      title: title ? decodeXmlEntities(title[1]) : '',
    });
  }

  return { channels, programmes };
}

/**
 * Assert a body parses as XML, using the browser's DOMParser.
 *
 * This is the only place in the suite that can honestly say "valid XML":
 * {@link parseXmltv} is a regex reader and would happily extract elements
 * from a document with an unclosed root. `adminPage` sits at `about:blank`,
 * which is a perfectly good context for `page.evaluate`.
 */
export async function expectWellFormedXml(page: Page, xml: string): Promise<void> {
  const failure = await page.evaluate((source: string) => {
    const doc = new DOMParser().parseFromString(source, 'application/xml');
    const problem = doc.querySelector('parsererror');
    return problem ? problem.textContent : null;
  }, xml);

  expect(failure, 'body should parse as well-formed XML').toBeNull();
}
```

Export `parseM3u`, `parseXmltv`, `expectWellFormedXml` and the five new types from `e2e/fixtures/index.ts`, and add a row for the three functions to that file's non-fixture export table.

- [ ] **Step 5: Run them and confirm they pass**

Run: `cd e2e && npx playwright test --project=seeded parse-fixture`
Expected: PASS, 9 tests.

- [ ] **Step 6: Typecheck and commit**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Commit as `test(e2e): add M3U and XMLTV parse helpers`.

---

### Task 3: Rows 1–2 — `/output/m3u` and its profile-scoped form

Implements D3, D14, D15's structural half.

**Files:**
- Create: `e2e/tests/seeded/output-m3u.spec.ts`

**Interfaces:**
- Consumes: `seed.channel`, `seed.channelProfile`, `parseM3u`, the built-in `request` fixture.

- [ ] **Step 1: Write the playlist test**

```ts
import { test, expect, parseM3u } from '../../fixtures';

test('/output/m3u renders a parseable playlist with a well-formed proxy URL', async ({
  seed,
  request,
  baseURL,
}) => {
  const channel = await seed.channel();

  // No bearer token: this is how a real client fetches a playlist, and it is
  // what makes the assertion meaningful. `request` is Playwright's built-in
  // context; the `api` fixture would add an Authorization header no TiviMate
  // or Plex install has.
  const res = await request.get('/output/m3u');
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('audio/x-mpegurl');

  const playlist = parseM3u(await res.text());

  // The header points clients at the guide. Both spellings are emitted
  // because different clients read different ones.
  expect(playlist.header['x-tvg-url']).toContain('/output/epg');
  expect(playlist.header['url-tvg']).toBe(playlist.header['x-tvg-url']);

  // NEVER assert on playlist.entries.length. Four workers share this
  // container and the playlist renders every channel on the instance.
  const mine = playlist.entries.find((e) => e.attributes['tvg-name'] === channel.name);
  expect(mine, `the seeded channel ${channel.name} should be in the playlist`).toBeDefined();

  expect(mine!.url).toBe(`${baseURL}/proxy/ts/stream/${channel.uuid}`);
  expect(mine!.title).toBe(channel.name);
  expect(mine!.attributes['group-title']).toBeTruthy();
});
```

- [ ] **Step 2: Run it**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded output-m3u --grep "parseable"`
Expected: PASS.

If `mine!.url` fails on the origin, read the actual value before adjusting: `build_absolute_uri_with_port` prefers `X-Forwarded-Host`/`X-Forwarded-Port` (nginx sets them) over the `Host` header, so the emitted origin is whatever nginx forwarded. Assert on the *path* and UUID and record the origin difference in a comment rather than hard-coding a value you did not derive.

- [ ] **Step 3: Write the profile-scoped test**

```ts
test('/output/m3u/<profile> renders only the channels enabled in that profile', async ({
  seed,
  api,
  request,
}) => {
  const profile = await seed.channelProfile();
  const included = await seed.channel();
  const excluded = await seed.channel();

  // A channel created through the API joins EVERY Channel Profile, enabled,
  // unless channel_profile_ids says otherwise (ChannelViewSet.create) — and a
  // profile created first picks up every existing channel the same way
  // (create_profile_memberships). So both channels are already members here;
  // the test disables one.
  //
  // That also means this profile contains every OTHER worker's channels.
  // Assert on membership of the two we seeded, never on the profile's size.
  const patch = await api.patch(
    `/api/channels/profiles/${profile.id}/channels/${excluded.id}/`,
    { enabled: false }
  );
  expect(patch.status()).toBe(200);

  const res = await request.get(`/output/m3u/${profile.name}`);
  expect(res.status()).toBe(200);

  const names = parseM3u(await res.text()).entries.map((e) => e.attributes['tvg-name']);
  expect(names).toContain(included.name);
  expect(names).not.toContain(excluded.name);
});

test('/output/m3u/<profile> 404s on a profile that does not exist', async ({
  seed,
  request,
}) => {
  // generate_m3u raises Http404 for an unknown profile name rather than
  // returning an empty playlist — worth pinning, because the HDHR lineup
  // makes the opposite choice for the same mistake (it returns []).
  const res = await request.get(`/output/m3u/${seed.generatedName('no-such-profile')}`);
  expect(res.status()).toBe(404);
});
```

- [ ] **Step 4: Run all three**

Run: `cd e2e && npx playwright test --project=seeded output-m3u`
Expected: PASS, 3 tests.

- [ ] **Step 5: Prove the exclusion assertion is not vacuous**

Temporarily change the `enabled: false` patch to `enabled: true`. Re-run. Expected: FAIL on `not.toContain`. **Revert.**

A membership assertion that passes whether or not the membership was changed is the single easiest way to ship a green profile test that proves nothing.

- [ ] **Step 6: Commit**

Commit as `test(e2e): /output/m3u playlist and profile scoping (G5 rows 1-2)`.

---

### Task 4: Row 3 — `/output/epg` is valid XMLTV with programmes

Implements D7 and D8. **Read D7 before starting: the cache is the reason this task has a step nothing else has.**

**Files:**
- Create: `e2e/tests/seeded/output-epg.spec.ts`

- [ ] **Step 1: Demonstrate the cache before relying on the workaround**

This is a gate, not a formality. Bring the stack up and run, by hand:

```bash
curl -s 'http://localhost:9191/output/epg?days=7' | grep -c '<channel id='
# create a channel through the UI or API, then immediately:
curl -s 'http://localhost:9191/output/epg?days=7' | grep -c '<channel id='
```

Expected: **the same count both times**, because `stream_cached_response` caches
the rendered body in Redis for `DEFAULT_CACHE_TTL = 300` seconds and creating a
channel with no `epg_data` invalidates nothing (`refresh_epg_programs` fires only
when `epg_data` is involved). Then repeat with `?days=8` and expect the new
channel to appear.

Record the observed counts in a comment at the top of the spec file. If the
second count *does* change, the cache is not behaving as the spec describes —
stop and re-read `apps/output/streaming_chunk_cache.py` before writing the test,
because D7's whole mitigation rests on this.

- [ ] **Step 2: Write the test**

```ts
import { test, expect, parseXmltv, expectWellFormedXml } from '../../fixtures';

/**
 * Every fetch below passes a distinct `?days=`. That is not tuning, it is the
 * only way this test can see its own channel.
 *
 * `/output/epg` is served from a Redis chunk cache with a 300-second TTL
 * (`stream_cached_response`, DEFAULT_CACHE_TTL), and the cache key is
 * `profile:username:d=:p=:logos=:tvgid=:origin=` — the raw query string is
 * NOT in it, so `?e2e=<token>` does not bust it. Creating a channel
 * invalidates the cache only when `epg_data` is involved
 * (`refresh_epg_programs` in apps/channels/signals.py), which a plain seeded
 * channel is not. Without a distinct `days` this test reads a body rendered
 * up to five minutes before its channel existed.
 *
 * `days` is clamped to 0-365 and only widens the programme window, so it is a
 * safe key to vary. Measured this session: two `?days=7` fetches either side
 * of a channel create returned identical channel counts; `?days=8` showed the
 * new channel immediately.
 */
function uniqueDays(testInfo: { workerIndex: number }): number {
  // 1-365. Worker index separates concurrent workers; the random component
  // separates this test from the same test in an earlier run inside the same
  // 300-second window.
  return 1 + ((testInfo.workerIndex * 97 + Math.floor(Math.random() * 300)) % 365);
}

test('/output/epg is well-formed XMLTV carrying programmes for a seeded channel', async ({
  seed,
  request,
  adminPage,
}, testInfo) => {
  const channel = await seed.channel();
  const days = uniqueDays(testInfo);

  const res = await request.get(`/output/epg?days=${days}`);
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/xml');

  const body = await res.text();

  // A real XML parser's verdict, not the shallow reader's. parseXmltv would
  // extract elements out of a document with an unclosed root.
  await expectWellFormedXml(adminPage, body);

  const guide = parseXmltv(body);

  // The channel id is the formatted channel number for an anonymous request
  // (tvg_id_source defaults to 'channel_number'), so find by display-name —
  // the one value this test controls.
  const mine = guide.channels.find((c) => c.displayNames.includes(channel.name));
  expect(mine, `a <channel> for ${channel.name} should be in the guide`).toBeDefined();

  // A channel with no epg_data still gets programmes: generate_epg routes it
  // to generate_dummy_programs. That is what makes this row independent of
  // G3's EPG ingest.
  const mineProgrammes = guide.programmes.filter((p) => p.channel === mine!.id);
  expect(
    mineProgrammes.length,
    'the dummy EPG generator should have produced programmes'
  ).toBeGreaterThan(0);
  expect(mineProgrammes[0].start).toMatch(/^\d{14} [+-]\d{4}$/);
  expect(mineProgrammes[0].title).not.toBe('');
});
```

- [ ] **Step 3: Run it**

Run: `cd e2e && npx playwright test --project=seeded output-epg`
Expected: PASS.

- [ ] **Step 4: Prove the cache workaround is what makes it pass**

Temporarily replace `uniqueDays(testInfo)` with the constant `7`. Run the spec
**twice in a row** with a fresh `seed.channel()` each time. Expected: the second
run FAILS on the missing `<channel>`, because it read the first run's cached
body. **Revert.**

Do not skip this. If the test passes with a constant `days`, the cache is not
where the spec says it is and D7's mitigation is cargo cult.

- [ ] **Step 5: Commit**

Commit as `test(e2e): /output/epg is valid XMLTV with programmes (G5 row 3)`.

---

### Task 5: Rows 4, 5 and 17 — the HDHomeRun endpoints, and the bug in them

Implements D6, D8, D10 defect 3 and D11.

**Files:**
- Create: `e2e/tests/seeded/hdhr.spec.ts`

- [ ] **Step 1: Write the discovery tests**

```ts
import { test, expect, expectWellFormedXml } from '../../fixtures';

type Discover = {
  FriendlyName: string;
  DeviceID: string;
  TunerCount: number;
  BaseURL: string;
  LineupURL: string;
};

type LineupEntry = {
  GuideNumber: string;
  GuideName: string;
  URL: string;
};

test('hdhr discover.json describes a tuner and points at its own lineup', async ({
  request,
}) => {
  const res = await request.get('/hdhr/discover.json');
  expect(res.status()).toBe(200);

  const device: Discover = await res.json();
  expect(device.FriendlyName).toBeTruthy();
  expect(device.DeviceID).toBeTruthy();
  expect(device.TunerCount).toBeGreaterThan(0);
  expect(device.LineupURL).toBe(`${device.BaseURL}/lineup.json`);

  // The URL it advertises actually resolves. A discovery document naming a
  // 404 is the failure mode that makes a tuner "not work in Plex".
  const lineup = await request.get(device.LineupURL);
  expect(lineup.status()).toBe(200);
});

test('hdhr device.xml is well-formed and agrees with discover.json', async ({
  request,
  adminPage,
}) => {
  const res = await request.get('/hdhr/device.xml');
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/xml');

  const body = await res.text();
  await expectWellFormedXml(adminPage, body);

  const lineupUrl = /<LineupURL>([^<]*)<\/LineupURL>/.exec(body)?.[1];
  const discover: Discover = await (await request.get('/hdhr/discover.json')).json();
  expect(lineupUrl).toBe(discover.LineupURL);
});

test('hdhr lineup_status.json reports a scannable cable source', async ({ request }) => {
  const res = await request.get('/hdhr/lineup_status.json');
  expect(res.status()).toBe(200);

  const status = await res.json();
  expect(status).toMatchObject({
    ScanInProgress: 0,
    ScanPossible: 0,
    Source: 'Cable',
    SourceList: ['Cable'],
  });
});
```

- [ ] **Step 2: Run them**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded hdhr --grep "discover|device.xml|lineup_status"`
Expected: PASS, 3 tests.

- [ ] **Step 3: Write the lineup tests**

```ts
test('hdhr lineup.json carries a seeded channel with a proxy URL', async ({
  seed,
  request,
  baseURL,
}) => {
  // No explicit channel_number. ChannelSerializer.create assigns one from
  // Channel.get_next_available_channel_number() when it is omitted, so a
  // seeded channel always has one — which matters here, because
  // LineupAPIView SKIPS any channel whose format_channel_number(..., empty=None)
  // is None. Hard-coding a number instead would collide with itself on a
  // second run against the same container.
  const channel = await seed.channel();
  expect(channel.channel_number, 'create should have assigned a number').not.toBeNull();

  const res = await request.get('/hdhr/lineup.json');
  expect(res.status()).toBe(200);

  const lineup: LineupEntry[] = await res.json();
  const mine = lineup.find((entry) => entry.GuideName === channel.name);
  expect(mine, `${channel.name} should be in the lineup`).toBeDefined();

  // format_channel_number renders a whole-valued float as an int, and
  // JSON.parse does the same to 9.0 — so String() over the number the API
  // returned matches on both whole and fractional values.
  expect(mine!.GuideNumber).toBe(String(channel.channel_number));
  expect(mine!.URL).toBe(`${baseURL}/proxy/ts/stream/${channel.uuid}`);
});

test('hdhr lineup scopes to a Channel Profile, and answers [] for an unknown one', async ({
  seed,
  api,
  request,
}) => {
  const profile = await seed.channelProfile();
  const included = await seed.channel();
  const excluded = await seed.channel();
  expect(
    (
      await api.patch(
        `/api/channels/profiles/${profile.id}/channels/${excluded.id}/`,
        { enabled: false }
      )
    ).status()
  ).toBe(200);

  const scoped: LineupEntry[] = await (
    await request.get(`/hdhr/${profile.name}/lineup.json`)
  ).json();
  const names = scoped.map((entry) => entry.GuideName);
  expect(names).toContain(included.name);
  expect(names).not.toContain(excluded.name);

  // LineupAPIView returns an empty lineup for a profile that does not exist,
  // where /output/m3u raises Http404 for the same mistake. Two surfaces, two
  // answers; pin both so a future unification is a deliberate change.
  const unknown = await request.get(`/hdhr/${seed.generatedName('no-such')}/lineup.json`);
  expect(unknown.status()).toBe(200);
  expect(await unknown.json()).toEqual([]);
});
```

- [ ] **Step 4: Run them**

Run: `cd e2e && npx playwright test --project=seeded hdhr`
Expected: PASS, 5 tests.

- [ ] **Step 5: Write the known-bug test (row 17)**

```ts
// Asserts the behaviour Dispatcharr SHOULD have. It fails today, and the
// cause is structural rather than a forgotten line: the four HDHomeRun views
// in apps/hdhr/api_views.py are `permission_classes = [AllowAny]` and take no
// user at all, so LineupAPIView builds `Channel.objects.all()` and has no
// principal to filter it by. There is not one occurrence of
// `hide_adult_content` anywhere under apps/hdhr/ — and there could not be,
// because it is a per-user preference and there is no user.
//
// The only access control on this surface is the M3U_EPG network ACL (which
// defaults to private networks) and the optional <channel_profile> path
// segment. Anything the ACL admits sees every channel on the instance,
// including adult ones and ones above every user level.
//
// Filed separately from the stream_xc adult-filter defect
// (hidden-channel-streamable.spec.ts): that function HAS the principal and
// omits one filter clause, so its fix is that clause. This one has no
// principal, so its fix is a design decision about how HDHR authenticates.
// One issue would not be closed by either change alone.
//
// Issue: <fill in the number from Step 7 before committing>
test.fail('hdhr lineup does not expose adult or above-level channels', async ({
  seed,
  request,
}) => {
  const restricted = await seed.channel({ user_level: 10, is_adult: true });

  const lineup: LineupEntry[] = await (await request.get('/hdhr/lineup.json')).json();
  const names = lineup.map((entry) => entry.GuideName);

  expect(
    names,
    'an unauthenticated caller should not see an admin-only adult channel'
  ).not.toContain(restricted.name);
});
```

- [ ] **Step 6: Run it and confirm it is an expected failure**

Run: `cd e2e && npx playwright test --project=seeded hdhr --grep "does not expose"`
Expected: reported as an **expected failure** (1 failed as expected), not a pass.

If it is reported as an unexpected **pass**, the lineup filtered the channel and
the spec's reading is wrong — stop and re-read `LineupAPIView` before changing
anything. A `test.fail()` that passes is a claim about the product that just got
falsified.

- [ ] **Step 7: File the issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "HDHomeRun endpoints apply no authorization: AllowAny with no principal" \
  --label needs-triage
```

The `--repo` flag is mandatory: this checkout is a fork, and `gh` without it
files on upstream's public tracker. Body should name `DiscoverAPIView`,
`LineupAPIView`, `LineupStatusAPIView` and `HDHRDeviceXMLAPIView`, state that
`Channel.objects.all()` is returned to anything the `M3U_EPG` ACL admits, note
that `hide_adult_content` appears nowhere under `apps/hdhr/` and cannot without
a principal, and link this test. Put the issue number in the comment above
`test.fail()`.

- [ ] **Step 8: Commit**

Commit as `test(e2e): HDHomeRun discovery and lineup, and the missing authorization (G5 rows 4-5, 17)`.

---

### Task 6: Rows 6 and 19 — the Xtream authentication handshake

Implements D3, D10 defect 5.

**Files:**
- Create: `e2e/tests/seeded/xc-auth.spec.ts`

- [ ] **Step 1: Write the handshake test**

```ts
import { test, expect, xcQuery } from '../../fixtures';

test('player_api.php returns a user_info / server_info envelope for valid credentials', async ({
  seed,
  request,
}) => {
  const user = await seed.xcUser();

  const res = await request.get(`/player_api.php${xcQuery(user)}`);
  expect(res.status()).toBe(200);

  const body = await res.json();
  expect(body.user_info).toMatchObject({
    username: user.username,
    auth: 1,
    status: 'Active',
  });
  expect(Number(body.user_info.max_connections)).toBeGreaterThan(0);
  expect(body.user_info.allowed_output_formats).toEqual(['ts', 'mp4']);

  // server_info.timezone is what XC clients use to interpret every EPG
  // timestamp, and _build_xc_server_info pins it to UTC deliberately (a
  // mis-set Docker /etc/timezone would otherwise shift the whole guide).
  expect(body.server_info.timezone).toBe('UTC');
  expect(body.server_info.port).toBeTruthy();
  expect(Number(body.server_info.timestamp_now)).toBeGreaterThan(0);
});

test('player_api.php answers an unknown action with the same envelope', async ({
  seed,
  request,
}) => {
  // xc_player_api falls through to xc_get_info for anything it does not
  // recognise, including get_account_info. That is deliberate
  // provider-compatibility behaviour, not an oversight, so it is pinned.
  const user = await seed.xcUser();
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'no_such_action' })}`
  );
  expect(res.status()).toBe(200);
  expect((await res.json()).user_info.auth).toBe(1);
});

test('player_api.php rejects a wrong password', async ({ seed, request }) => {
  const user = await seed.xcUser();

  // Driven through `request`, not `api`: ApiClient retries once through a
  // token refresh on ANY 401, which would spend a refresh and could throw
  // instead of returning the 401 this test exists to assert.
  const res = await request.get(
    `/player_api.php?username=${encodeURIComponent(user.username)}&password=wrong`
  );
  expect(res.status()).toBe(401);
});

test('player_api.php rejects a user with no xc_password at all', async ({
  seed,
  request,
}) => {
  // seed.user(), not seed.xcUser(): an ordinary account has no XC credential,
  // and xc_get_user returns None before it ever compares anything. This is
  // the path that keeps admin accounts off the XC surface.
  const plain = await seed.user();
  const res = await request.get(
    `/player_api.php?username=${encodeURIComponent(plain.username)}&password=anything`
  );
  expect(res.status()).toBe(401);
});
```

- [ ] **Step 2: Run them**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded xc-auth`
Expected: PASS, 4 tests.

- [ ] **Step 3: Write the known-bug test (row 19)**

```ts
// Asserts the behaviour Dispatcharr SHOULD have. `xc_get_user` returns None
// for a wrong password — which xc_player_api turns into 401 — but calls
// `get_object_or_404(User, username=…)` first, so an unknown username escapes
// as an Http404 and Django answers 404.
//
// An unauthenticated caller can therefore tell "no such account" from "wrong
// password" by status code alone, on an endpoint that takes credentials in a
// URL. Both failures should be indistinguishable.
//
// Found while specifying G5; it is not in the original brief. See D10 in the
// design doc.
//
// Issue: <fill in the number from Step 5 before committing>
test.fail('player_api.php does not distinguish an unknown user from a wrong password', async ({
  seed,
  request,
}) => {
  const user = await seed.xcUser();

  const wrongPassword = await request.get(
    `/player_api.php?username=${encodeURIComponent(user.username)}&password=wrong`
  );
  const unknownUser = await request.get(
    `/player_api.php?username=${seed.generatedName('ghost')}&password=wrong`
  );

  expect(wrongPassword.status()).toBe(401);
  expect(
    unknownUser.status(),
    'an unknown username must not be distinguishable from a wrong password'
  ).toBe(401);
});
```

- [ ] **Step 4: Run it and confirm it is an expected failure**

Run: `cd e2e && npx playwright test --project=seeded xc-auth --grep "does not distinguish"`
Expected: reported as an expected failure. The observed status for the unknown
user is 404.

- [ ] **Step 5: File the issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "XC player_api.php distinguishes an unknown username (404) from a wrong password (401)" \
  --label needs-triage
```

Name `xc_get_user` in `apps/output/views.py`, note that the same helper backs
`get.php`, `xmltv.php` and `panel_api.php`, and state the consequence: account
enumeration against an endpoint whose credentials travel in a URL. Put the
number in the comment.

- [ ] **Step 6: Commit**

Commit as `test(e2e): Xtream authentication handshake and its enumeration oracle (G5 rows 6, 19)`.

---

### Task 7: Rows 7, 8 and 15 — the Xtream live catalogue, its EPG, and the category bug

Implements D9 and D10 defect 1. Row 7 doubles as row 15's positive control, so the two are written together and differ in exactly one field.

**Files:**
- Create: `e2e/tests/seeded/xc-live.spec.ts`

**Interfaces:**
- Consumes: `seed.channelGroup`, `seed.channelProfile`, `seed.xcUser`, `xcQuery`.

- [ ] **Step 1: Write the catalogue test — and note the shape it shares with row 15**

```ts
import { test, expect, xcQuery } from '../../fixtures';
import type { XcUser } from '../../fixtures';

type XcCategory = { category_id: string; category_name: string };
type XcStream = {
  num: number;
  name: string;
  stream_id: number;
  stream_type: string;
  category_id: string;
  is_adult: number;
  tv_archive: number;
};

/**
 * `get_live_streams` is the one action served as a StreamingHttpResponse
 * (`_xc_stream_live_streams` yields the array element by element). The body
 * is valid JSON, but it arrives incrementally — read it whole before parsing.
 */
async function liveStreams(
  request: { get: (url: string) => Promise<{ text(): Promise<string> }> },
  user: XcUser
): Promise<XcStream[]> {
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_live_streams' })}`
  );
  return JSON.parse(await res.text());
}

test('the XC live catalogue lists a seeded channel under its own category', async ({
  seed,
  request,
}) => {
  // Own group, not the shared "Default Group" ChannelSerializer.create
  // auto-assigns: get_live_categories returns groups, and four workers all
  // writing into one group makes any category assertion meaningless.
  const group = await seed.channelGroup();
  const channel = await seed.channel({ channel_group_id: group.id, user_level: 0 });

  // One Channel Profile assigned, and a user_level 0 channel. This is
  // deliberately the exact shape the known-bug test below uses, differing
  // only in the channel's user_level — which makes this the positive control
  // for that bug rather than an unrelated happy path.
  const profile = await seed.channelProfile();
  const user = await seed.xcUser({ user_level: 1, channel_profiles: [profile.id] });

  const categories: XcCategory[] = await (
    await request.get(`/player_api.php${xcQuery(user, { action: 'get_live_categories' })}`)
  ).json();
  expect(categories.map((c) => c.category_id)).toContain(String(group.id));

  const streams = await liveStreams(request, user);
  const mine = streams.find((s) => s.stream_id === channel.id);
  expect(mine, `channel ${channel.id} should be in get_live_streams`).toBeDefined();
  expect(mine!.name).toBe(channel.name);
  expect(mine!.stream_type).toBe('live');
  expect(mine!.category_id).toBe(String(group.id));
  expect(mine!.is_adult).toBe(0);
  expect(mine!.tv_archive).toBe(0);
});

test('panel_api.php returns the same catalogue in one envelope', async ({
  seed,
  request,
}) => {
  const group = await seed.channelGroup();
  const channel = await seed.channel({ channel_group_id: group.id, user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  const body = await (await request.get(`/panel_api.php${xcQuery(user)}`)).json();

  expect(body.user_info.auth).toBe(1);
  expect(body.categories.live.map((c: XcCategory) => c.category_id)).toContain(
    String(group.id)
  );
  // available_channels is keyed by stream_id, which is the numeric Channel PK.
  expect(body.available_channels[String(channel.id)]?.name).toBe(channel.name);
});
```

- [ ] **Step 2: Run them**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded xc-live --grep "catalogue|panel_api"`
Expected: PASS, 2 tests.

- [ ] **Step 3: Write the EPG action tests**

```ts
test('get_short_epg returns programmes for a channel with no EPG source', async ({
  seed,
  request,
}) => {
  const channel = await seed.channel({ user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  // stream_id is the numeric Channel PK, NOT the UUID. xc_get_epg raises
  // Http404 without it — the /proxy/ts/ routes are the UUID-keyed ones.
  const body = await (
    await request.get(
      `/player_api.php${xcQuery(user, { action: 'get_short_epg', stream_id: channel.id })}`
    )
  ).json();

  // A channel with no epg_data still yields listings: xc_get_epg falls
  // through to generate_dummy_programs.
  expect(body.epg_listings.length).toBeGreaterThan(0);

  const first = body.epg_listings[0];
  // title and description are base64-encoded on this surface. A plain string
  // compare would silently pass against the encoded form of anything.
  expect(Buffer.from(first.title, 'base64').toString('utf8')).not.toBe('');
  expect(first.start).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  expect(first.stream_id).toBe(String(channel.id));
  expect(first).not.toHaveProperty('now_playing');
});

test('get_simple_data_table adds now_playing to the same listing shape', async ({
  seed,
  request,
}) => {
  const channel = await seed.channel({ user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  const body = await (
    await request.get(
      `/player_api.php${xcQuery(user, {
        action: 'get_simple_data_table',
        stream_id: channel.id,
      })}`
    )
  ).json();

  expect(body.epg_listings.length).toBeGreaterThan(0);
  // The one field that distinguishes the two actions: short=False adds it.
  expect(body.epg_listings[0]).toHaveProperty('now_playing');
});

test('the EPG actions 404 without a stream_id', async ({ seed, request }) => {
  const user = await seed.xcUser({ user_level: 1 });

  for (const action of ['get_short_epg', 'get_simple_data_table']) {
    const res = await request.get(`/player_api.php${xcQuery(user, { action })}`);
    expect(res.status(), `${action} with no stream_id`).toBe(404);
  }
});
```

- [ ] **Step 4: Run them**

Run: `cd e2e && npx playwright test --project=seeded xc-live`
Expected: PASS, 5 tests.

- [ ] **Step 5: Write the known-bug test (row 15)**

```ts
// Asserts the behaviour Dispatcharr SHOULD have. `xc_get_live_categories` in
// apps/output/views.py has three branches. The no-profiles branch and the
// admin branch both filter `channels__user_level__lte=user.user_level`. The
// has-profiles branch — the one a user with at least one Channel Profile
// takes — filters `"channels__user_level": 0`, an exact match.
//
// Symptom, and what this test asserts against: a channel at user_level 1 is
// listed by get_live_streams (which uses __lte everywhere) but its category
// is missing from get_live_categories, so an XC client shows a stream that
// belongs to no category.
//
// The positive control is 'the XC live catalogue lists a seeded channel under
// its own category' above: identical setup, user_level 0 channel, passes
// today. The two differ in exactly one field, which is what makes this a
// located defect rather than a guess.
//
// Issue: <fill in the number from Step 7 before committing>
test.fail('a profiled user sees the category of every channel it can list', async ({
  seed,
  request,
}) => {
  const group = await seed.channelGroup();
  const channel = await seed.channel({ channel_group_id: group.id, user_level: 1 });
  const profile = await seed.channelProfile();
  const user = await seed.xcUser({ user_level: 1, channel_profiles: [profile.id] });

  // Establish the premise before asserting the defect: the channel really is
  // visible to this user. Without this, a missing category could equally mean
  // the channel was filtered out for an unrelated reason, and the test would
  // indict the wrong line.
  const streams = await liveStreams(request, user);
  expect(streams.map((s) => s.stream_id)).toContain(channel.id);

  const categories: XcCategory[] = await (
    await request.get(`/player_api.php${xcQuery(user, { action: 'get_live_categories' })}`)
  ).json();

  expect(
    categories.map((c) => c.category_id),
    'a channel visible in get_live_streams must have a category'
  ).toContain(String(group.id));
});
```

- [ ] **Step 6: Run it and confirm it is an expected failure**

Run: `cd e2e && npx playwright test --project=seeded xc-live --grep "category of every channel"`
Expected: reported as an expected failure, failing on the final `toContain` —
**not** on the premise assertion. If it fails on the premise, the setup is wrong
and the defect has not been reached.

- [ ] **Step 7: File the issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "xc_get_live_categories filters user_level exactly instead of __lte for profiled users" \
  --label needs-triage
```

Quote the three branches, name the symptom (a stream with no category), and
note that the filter is copy-pasted across eight sites and this is the one that
diverges. Put the number in the comment.

- [ ] **Step 8: Commit**

Commit as `test(e2e): Xtream live catalogue, short EPG, and the category filter bug (G5 rows 7-8, 15)`.

---

### Task 8: Row 9 — the Xtream VOD and series actions on an empty catalogue

Implements D12. Six code paths, none of which G8 will reach for a while, and all of which a fresh instance runs on every XC client's first connect.

**Files:**
- Create: `e2e/tests/seeded/xc-vod-empty.spec.ts`

- [ ] **Step 1: Write the tests**

```ts
import { test, expect, xcQuery } from '../../fixtures';

/**
 * An empty VOD catalogue is the state every fresh Dispatcharr instance is in,
 * and every XC client asks these six questions on connect. So this is a real
 * assertion about six code paths not erroring, not a placeholder for G8.
 *
 * G8 deepens all six once the fake provider serves a catalogue. Until then
 * the shapes below are the contract: four list actions answer `[]`, and the
 * two detail actions answer 404 — **not** an empty object, because
 * `xc_get_series_info` and `xc_get_vod_info` both `raise Http404()` for a
 * missing or unknown id.
 */

test('the four XC list actions answer an empty catalogue with []', async ({
  seed,
  request,
}) => {
  const user = await seed.xcUser({ user_level: 1 });

  for (const action of [
    'get_vod_categories',
    'get_vod_streams',
    'get_series_categories',
    'get_series',
  ]) {
    const res = await request.get(`/player_api.php${xcQuery(user, { action })}`);
    expect(res.status(), action).toBe(200);
    expect(await res.json(), action).toEqual([]);
  }
});

test('the two XC detail actions 404 rather than erroring', async ({ seed, request }) => {
  const user = await seed.xcUser({ user_level: 1 });

  const cases: Array<[string, Record<string, string | number>]> = [
    ['get_vod_info', {}],
    ['get_vod_info', { vod_id: 999999999 }],
    ['get_series_info', {}],
    ['get_series_info', { series_id: 999999999 }],
  ];

  for (const [action, extra] of cases) {
    const res = await request.get(
      `/player_api.php${xcQuery(user, { action, ...extra })}`
    );
    // 404, not 500. The distinction is the whole test: a 500 here is an
    // unhandled exception reaching a client, and it is what an untested code
    // path on a fresh instance most often produces.
    expect(res.status(), `${action} ${JSON.stringify(extra)}`).toBe(404);
  }
});
```

- [ ] **Step 2: Run them**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded xc-vod-empty`
Expected: PASS, 2 tests.

If any case returns 500, that is a product defect this task just found: assert
the 404 you believe correct, mark it `test.fail()`, file it with
`gh issue create --repo D10Scot/Dispatcharr`, and say so in the task report.
Do not relax the assertion to whatever the product happens to do.

- [ ] **Step 3: Commit**

Commit as `test(e2e): Xtream VOD and series actions on an empty catalogue (G5 row 9)`.

---

### Task 9: Row 10 — `get.php` and `xmltv.php` at the site root

Implements D3 and D7's XC half.

**Files:**
- Create: `e2e/tests/seeded/xc-output.spec.ts`

- [ ] **Step 1: Write the tests**

```ts
import { test, expect, parseM3u, parseXmltv, xcQuery } from '../../fixtures';

/**
 * These two live at the SITE ROOT, not under /output/ — dispatcharr/urls.py
 * mounts them before the SPA catch-all. They route into the same
 * generate_m3u / generate_epg the /output/ endpoints use, but with a user, so
 * the bodies differ in ways worth pinning.
 *
 * Neither needs the ?days= cache workaround the anonymous /output/epg does:
 * the chunk-cache key contains the username, and seed.xcUser() generates a
 * fresh one per test.
 */

test('get.php renders an XC-flavoured playlist for its user', async ({
  seed,
  request,
  baseURL,
}) => {
  const channel = await seed.channel({ user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  const res = await request.get(`/get.php${xcQuery(user, { type: 'm3u_plus' })}`);
  expect(res.status()).toBe(200);

  const playlist = parseM3u(await res.text());

  // An XC request gets an XC guide URL, not /output/epg.
  expect(playlist.header['x-tvg-url']).toContain('/xmltv.php');

  const mine = playlist.entries.find((e) => e.attributes['tvg-name'] === channel.name);
  expect(mine, `${channel.name} should be in the XC playlist`).toBeDefined();

  // XC-style stream URL: /live/<username>/<password>/<numeric channel id>.
  // Note the numeric id here against the UUID /output/m3u emits — the same
  // channel, addressed two different ways by two different surfaces.
  expect(mine!.url).toBe(
    `${baseURL}/live/${user.username}/${user.xcPassword}/${channel.id}`
  );
});

test('xmltv.php renders a guide for its user', async ({ seed, request }) => {
  const channel = await seed.channel({ user_level: 0 });
  const user = await seed.xcUser({ user_level: 1 });

  const res = await request.get(`/xmltv.php${xcQuery(user)}`);
  expect(res.status()).toBe(200);
  expect(res.headers()['content-type']).toContain('application/xml');

  const guide = parseXmltv(await res.text());
  expect(
    guide.channels.some((c) => c.displayNames.includes(channel.name)),
    `${channel.name} should be in the XC guide`
  ).toBe(true);
});

test('both reject bad credentials with 401', async ({ seed, request }) => {
  const user = await seed.xcUser();
  const bad = `?username=${encodeURIComponent(user.username)}&password=wrong`;

  expect((await request.get(`/get.php${bad}`)).status()).toBe(401);
  expect((await request.get(`/xmltv.php${bad}`)).status()).toBe(401);
});
```

- [ ] **Step 2: Run them**

Run: `cd e2e && npx playwright test --project=seeded xc-output`
Expected: PASS, 3 tests.

- [ ] **Step 3: Commit**

Commit as `test(e2e): get.php and xmltv.php at the site root (G5 row 10)`.

---

### Task 10: Rows 11, 12 and 13 — the authorization matrix and the three open surfaces

Implements D5, D6 and D14. **Step 1 is a gate: it decides whether the matrix has two levels or three.**

**Files:**
- Create: `e2e/tests/seeded/output-authorization.spec.ts`

- [ ] **Step 1: Prove a level-10 user can be seeded**

Run, against a live container:

```bash
cd e2e && npx playwright test --project=seeded seed-fixture --grep "channelGroup"   # warms auth
```

then, in a Node one-liner or a throwaway spec, `seed.xcUser({ user_level: 10 })`
and read back `/api/accounts/users/<id>/`. Confirm `user_level` came back as 10.

If the API refuses it, the matrix drops to levels 0 and 1, and the
`COVERAGE.md` row must say so explicitly. **Do not reach for the bootstrap
admin instead**: that identity is shared across four workers and is read-only —
giving it an `xc_password`, or changing anything about it, would reach every
other worker mid-run and outlive the run.

Record the outcome in a comment at the top of the spec file.

- [ ] **Step 2: Write the matrix test**

```ts
import { test, expect, xcQuery } from '../../fixtures';
import type { XcUser } from '../../fixtures';

type XcStream = { stream_id: number; name: string };

async function liveStreams(
  request: { get: (url: string) => Promise<{ text(): Promise<string> }> },
  user: XcUser
): Promise<XcStream[]> {
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_live_streams' })}`
  );
  return JSON.parse(await res.text());
}

test('the XC catalogue is scoped to the requesting principal user_level', async ({
  seed,
  request,
}) => {
  const group = await seed.channelGroup();
  const levels = [0, 1, 10] as const;

  const channels = Object.fromEntries(
    await Promise.all(
      levels.map(async (level) => [
        level,
        await seed.channel({ channel_group_id: group.id, user_level: level }),
      ])
    )
  ) as Record<(typeof levels)[number], { id: number; name: string }>;

  // Seeded users, never the bootstrap admin: that identity is shared across
  // four workers and read-only. Costs zero logins — XC authentication is
  // query-string credentials against an unthrottled path, which is what makes
  // a nine-cell matrix free here where a JWT matrix would not be.
  for (const level of levels) {
    const user = await seed.xcUser({ user_level: level });
    const visible = new Set((await liveStreams(request, user)).map((s) => s.stream_id));

    // Restricted to OUR three channels. The catalogue also contains every
    // other worker's, so a set comparison against the whole response would
    // fail at 4 workers and pass at 1.
    const seen = levels.filter((l) => visible.has(channels[l].id));
    const expected = levels.filter((l) => l <= level);

    expect(seen, `a user_level ${level} principal`).toEqual(expected);
  }
});

test('a principal cannot read the EPG of a channel above its level', async ({
  seed,
  request,
}) => {
  const above = await seed.channel({ user_level: 10 });
  const user = await seed.xcUser({ user_level: 0 });

  // Asserted on get_short_epg rather than on stream_xc: these channels have
  // no Stream rows, so a /live/ request would fail for two possible reasons
  // and prove neither. stream_xc's filtering is covered by
  // hidden-channel-streamable.spec.ts, where there is a real upstream.
  const res = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_short_epg', stream_id: above.id })}`
  );
  expect(res.status()).toBe(404);
});
```

- [ ] **Step 3: Run them**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded output-authorization --grep "scoped|above its level"`
Expected: PASS, 2 tests.

- [ ] **Step 4: Write the `hide_adult_content` test**

```ts
test('hide_adult_content removes an adult channel from every XC listing path', async ({
  seed,
  request,
}) => {
  const clean = await seed.channel({ user_level: 0 });
  const adult = await seed.channel({ user_level: 0, is_adult: true });
  const user = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  const visible = new Set((await liveStreams(request, user)).map((s) => s.stream_id));
  expect(visible.has(clean.id), 'the non-adult channel should still be listed').toBe(true);
  expect(visible.has(adult.id), 'get_live_streams').toBe(false);

  const playlist = await (await request.get(`/get.php${xcQuery(user)}`)).text();
  expect(playlist).toContain(clean.name);
  expect(playlist, 'get.php').not.toContain(adult.name);

  const guide = await (await request.get(`/xmltv.php${xcQuery(user)}`)).text();
  expect(guide, 'xmltv.php').not.toContain(adult.name);

  // The per-channel EPG action applies the same filter, so it 404s rather
  // than leaking the programme titles of a channel the user cannot list.
  const epg = await request.get(
    `/player_api.php${xcQuery(user, { action: 'get_short_epg', stream_id: adult.id })}`
  );
  expect(epg.status(), 'get_short_epg for the adult channel').toBe(404);
});
```

- [ ] **Step 5: Write the characterization test (row 13)**

```ts
/**
 * NOT a `test.fail()`. This pins the product's ACTUAL authorization model for
 * three of its four output surfaces, and that model is deliberate: the
 * /output/ URLconf passes only `profile_name` (so `generate_m3u` and
 * `generate_epg` run with `user = None` and no filter at all), and the four
 * HDHomeRun views are `permission_classes = [AllowAny]` with no principal.
 * The only gate is the M3U_EPG network ACL, which defaults to loopback and
 * private ranges.
 *
 * **If this test goes red, the product changed and THIS TEST needs updating**
 * — the opposite of every `test.fail()` row in this suite, where red means
 * the product was fixed. Say so to whoever is reading the failure.
 */
test('the anonymous output surfaces apply no user_level filter at all', async ({
  seed,
  request,
}, testInfo) => {
  const restricted = await seed.channel({ user_level: 10 });

  const playlist = await (await request.get('/output/m3u')).text();
  expect(playlist, '/output/m3u').toContain(restricted.name);

  // A ?days= nothing else will reuse, for the same reason output-epg.spec.ts
  // has one: /output/epg is served from a 300-second Redis chunk cache whose
  // key contains `days` but NOT the raw query string, and creating a channel
  // does not invalidate it. A value fixed per worker would collide with this
  // same test's previous run inside that window. See D7 in the design doc.
  const days = 1 + ((testInfo.workerIndex * 89 + Math.floor(Math.random() * 300)) % 365);
  const guide = await (await request.get(`/output/epg?days=${days}`)).text();
  expect(guide, '/output/epg').toContain(restricted.name);

  const lineup = await (await request.get('/hdhr/lineup.json')).json();
  expect(
    lineup.map((entry: { GuideName: string }) => entry.GuideName),
    '/hdhr/lineup.json'
  ).toContain(restricted.name);
});
```

- [ ] **Step 6: Run the whole file**

Run: `cd e2e && npx playwright test --project=seeded output-authorization`
Expected: PASS, 4 tests.

- [ ] **Step 7: Prove the matrix is not vacuous**

Temporarily change `const expected = levels.filter((l) => l <= level);` to
`levels.filter((l) => l <= 10)`. Re-run. Expected: FAIL for the level-0 and
level-1 principals. **Revert.**

- [ ] **Step 8: Commit**

Commit as `test(e2e): XC authorization matrix, hide_adult_content, and the open surfaces (G5 rows 11-13)`.

---

### Task 11: Row 14 — one advertised URL delivers bytes

Implements D15. First `streaming` spec of this goal.

**Files:**
- Create: `e2e/tests/streaming/output-m3u-stream.spec.ts`

**Interfaces:**
- Consumes: `seed.upstreamChannel`, `upstream.scenario`, `upstream.log`, `streamClient`, `parseM3u`, and `lockedProfile` from `e2e/tests/streaming/helpers.ts`.

- [ ] **Step 1: Write the test**

```ts
import { test, expect, expectTsAligned, parseM3u, TS_PACKET_SIZE } from '../../fixtures';
import { lockedProfile } from './helpers';

/**
 * ONE URL, not all of them. Streaming n URLs costs n upstream connections and
 * proves nothing the first did not: every entry in the playlist is rendered
 * by the same f-string over the same queryset, so if one resolves and
 * delivers, the construction is right. output-m3u.spec.ts validates the rest
 * structurally.
 *
 * This test is what turns that structural check into a claim about the
 * product: the URL is taken VERBATIM out of the playlist and handed to a
 * client, with nothing reconstructed. A test that rebuilt the URL from
 * `channel.uuid` would pass even if the playlist emitted a wrong one.
 */
test('a URL taken verbatim from /output/m3u delivers aligned TS', async ({
  upstream,
  seed,
  api,
  request,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G5 Output', tvgId: 'g5-output.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
  });

  const playlist = parseM3u(await (await request.get('/output/m3u')).text());
  const mine = playlist.entries.find((e) => e.attributes['tvg-name'] === channel.name);
  expect(mine, `${channel.name} should be in the playlist`).toBeDefined();

  // StreamClient.open() accepts an absolute URL, so this is the playlist's
  // own string with no edit.
  await streamClient.open(mine!.url);
  const packets = await streamClient.readPackets(200);

  expect(packets.byteLength).toBe(200 * TS_PACKET_SIZE);
  expectTsAligned(packets);

  const opens = (await upstream.log(scenario)).filter(
    (e) => e.kind === 'open' && e.channelId === 1
  );
  expect(opens).toHaveLength(1);
});
```

- [ ] **Step 2: Run it**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming output-m3u-stream`
Expected: PASS.

- [ ] **Step 3: Prove the URL is really the playlist's**

Temporarily change the `open` call to
`streamClient.open('/proxy/ts/stream/00000000-0000-0000-0000-000000000000')`.
Re-run. Expected: FAIL on the open. **Revert.**

This confirms the test would notice a playlist emitting a wrong URL, which is
the only thing it is here to catch.

- [ ] **Step 4: Commit**

Commit as `test(e2e): an /output/m3u URL delivers bytes end to end (G5 row 14)`.

---

### Task 12: Rows 16 and 18 — the two remaining known bugs

Row 16 is the byte-level half of the adult-filter defect and lives in `streaming`. Row 18 is issue #12 and is the **only login this whole goal spends**. They share a task because each is one small test with an issue attached, not because they are related.

**Files:**
- Create: `e2e/tests/streaming/hidden-channel-streamable.spec.ts`
- Create: `e2e/tests/seeded/token-refresh-deleted-user.spec.ts`

- [ ] **Step 1: Write the streamable-hidden-channel test**

```ts
import { test, expect, xcQuery } from '../../fixtures';
import { lockedProfile } from './helpers';

type XcStream = { stream_id: number };

// Asserts the behaviour Dispatcharr SHOULD have. `stream_xc`
// (apps/proxy/live_proxy/views.py) applies `user_level__lte` and Channel
// Profile membership to the requesting user, then serves the channel — with
// no `is_adult` filter, and no `hidden_from_output` exclusion either. Every
// listing path applies both for the same user.
//
// So a `hide_adult_content` user cannot see this channel in get_live_streams,
// in get.php's playlist or in xmltv.php's guide, and can still watch it by
// asking for it by id. That is CLAUDE.md's "hidden channels are unlistable
// yet still streamable", located precisely.
//
// Filed separately from the HDHomeRun defect (hdhr.spec.ts): stream_xc HAS
// the principal and omits one filter clause, so its fix is that clause; HDHR
// has no principal at all. Neither change closes the other.
//
// Issue: <fill in the number from Step 4 before committing>
test.fail('a channel a user cannot list is not streamable by that user', async ({
  upstream,
  seed,
  api,
  request,
  streamClient,
}) => {
  const scenario = await upstream.scenario({
    channels: [{ id: 1, name: 'G5 Adult', tvgId: 'g5-adult.e2e', logo: null }],
    rate: 20,
  });
  const proxy = await lockedProfile(api, 'Proxy');
  const { channel } = await seed.upstreamChannel(scenario, {
    channelIds: [1],
    streamProfileId: proxy.id,
    channel: { user_level: 0, is_adult: true },
  });

  const user = await seed.xcUser({
    user_level: 1,
    custom_properties: { hide_adult_content: true },
  });

  // The premise: this user genuinely cannot list the channel. Without it a
  // refusal below could mean anything.
  const listed: XcStream[] = JSON.parse(
    await (
      await request.get(
        `/player_api.php${xcQuery(user, { action: 'get_live_streams' })}`
      )
    ).text()
  );
  expect(listed.map((s) => s.stream_id)).not.toContain(channel.id);

  // streamClient, not request.get(): APIResponse.body() awaits the full
  // download and would never resolve against an endless TS stream if the
  // product does serve it — which today it does. `open()` throws on a
  // non-2xx, so resolving means the bytes started flowing.
  const served = await streamClient
    .open(`/live/${user.username}/${user.xcPassword}/${channel.id}`)
    .then(() => true)
    .catch(() => false);

  try {
    expect(
      served,
      'a channel hidden from this user by hide_adult_content must not stream'
    ).toBe(false);
  } finally {
    // Abort whatever was opened, so a failing run does not leave an upstream
    // connection held for the rest of the project.
    await streamClient.close();
  }
});
```

- [ ] **Step 2: Run it and confirm it is an expected failure**

Run: `./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming hidden-channel-streamable`
Expected: reported as an expected failure, failing on the final `toBe(false)` —
not on the premise. If it fails on the premise, `hide_adult_content` did not
take effect and the setup is wrong.

- [ ] **Step 3: File the issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "stream_xc omits the is_adult and hidden_from_output filters every listing path applies" \
  --label needs-triage
```

Name `stream_xc` in `apps/proxy/live_proxy/views.py`, contrast it with
`_xc_live_streams_setup` and `generate_m3u`, and mention the second symptom
this test does not cover: `stream_xc` also omits
`.exclude(hidden_from_output=True)`, so a channel hidden from output is
streamable the same way. One fix closes both. Put the number in the comment.

- [ ] **Step 4: Write the token-refresh test (row 18)**

```ts
import { test, expect, SEEDED_USER_PASSWORD } from '../../fixtures';

// Asserts the behaviour Dispatcharr SHOULD have. A refresh token naming a
// user who has since been deleted gets a 500 from TokenRefreshView, not the
// 401 that would tell a client to log in again. Filed as
// https://github.com/D10Scot/Dispatcharr/issues/12.
//
// **This test costs ONE login out of three per minute for the entire suite,
// and it is the only login G5 spends.** seed.user() generates a fresh
// username every call, so it is a guaranteed cache miss in asUser's per-worker
// token cache. Budget it at one per run. A run that is cold — the first after
// `--reset`, or with playwright/.auth/ deleted — has already spent the whole
// budget in bootstrap, and a worker cannot wait out a throttle window the way
// bootstrap can, so an occasional 429 here on a cold rerun is a harness cost,
// not a product failure. See "The login throttle" in e2e/README.md.
test.fail('refreshing a deleted user\'s token returns 401, not 500', async ({
  seed,
  api,
  asUser,
  request,
}) => {
  const user = await seed.user();
  const client = await asUser(user.username, SEEDED_USER_PASSWORD);
  const refresh = await client.freshRefreshTokenForTest();

  expect((await api.delete(`/api/accounts/users/${user.id}/`)).status()).toBe(204);

  const res = await request.post('/api/accounts/token/refresh/', {
    data: { refresh },
  });

  expect(
    res.status(),
    'a refresh token naming a deleted user should be rejected, not crash'
  ).toBe(401);
});
```

`ApiClient` has no accessor for the refresh token today. Add the smallest one
that works, beside the existing `freshAccessToken()` and
`expireAccessTokenForTest()`:

```ts
  /**
   * Test hook: the raw refresh token this client holds. Only issue #12's
   * regression test needs it — it must present a refresh token to the
   * endpoint directly, after deleting the user it names.
   */
  freshRefreshTokenForTest(): string {
    return this.tokens.refresh;
  }
```

- [ ] **Step 5: Run it and confirm it is an expected failure**

Run: `cd e2e && npx playwright test --project=seeded token-refresh-deleted-user`
Expected: reported as an expected failure. The observed status is 500.

If it 429s, the run was cold. Wait a minute and re-run — that is the documented
cost, not a defect.

- [ ] **Step 6: Confirm the login budget claim**

Run, against the container:

```bash
docker exec dispatcharr-e2e grep 'POST /api/accounts/token/ ' /var/log/nginx/access.log | tail
```

Expected: exactly one entry attributable to this test per run. The trailing
space matters — it excludes `token/refresh/`, which is unthrottled and free.
If more than one appears, something else in G5 is logging in and must be found
before this task closes.

- [ ] **Step 7: Commit**

Commit as `test(e2e): pin the streamable hidden channel and issue #12 (G5 rows 16, 18)`.

---

### Task 13: Coverage inventory and documentation

**Files:**
- Modify: `e2e/COVERAGE.md`, `e2e/README.md`

- [ ] **Step 1: Move every G5 row to `done`**

Eleven rows. Each one's status becomes `done` except where a task recorded a
gap, in which case it stays `todo` with a note saying exactly what was tried.
Row 11's row must say whether the matrix landed at two levels or three
(Task 10, Step 1).

- [ ] **Step 2: Add the four new `known-bug` rows**

Rows 15, 16, 17 and 19 have no row in `COVERAGE.md` today. Add one each, status
`known-bug`, with the issue link, following the existing format:

```
| Output | XC get_live_categories filters user_level exactly for profiled users, so a listed channel can have no category ([#NN](…)) | G5 | known-bug |
| Output | A channel hidden from a user by hide_adult_content is still streamable through stream_xc ([#NN](…)) | G5 | known-bug |
| Output | The HDHomeRun endpoints apply no authorization at all — AllowAny with no principal ([#NN](…)) | G5 | known-bug |
| Output | XC player_api.php distinguishes an unknown username (404) from a wrong password (401) ([#NN](…)) | G5 | known-bug |
```

Row 18's row already exists; update its status only if the test landed.

- [ ] **Step 3: List the spec files under the G5 rows**

Follow the format the G1, G2 and G4 blocks at the bottom of the file use: a
prose sentence saying which rows share which file, then the list. Name all
eleven specs.

- [ ] **Step 4: Update `e2e/README.md`**

Four edits, all small:

1. Add `parseM3u`, `parseXmltv`, `xcQuery` and `expectWellFormedXml` to the
   "three exports that are not fixtures" table (it becomes seven).
2. Add `channelGroup` and `xcUser` to the `seed` row of the fixture table.
3. Add a short paragraph to "Writing a test": **client-facing output surfaces
   are driven with the built-in `request` fixture, not `api`** — no real client
   carries a bearer token, and `ApiClient` retries on 401, which is the status
   the XC rejection tests assert on.
4. Correct the CI section: it says the workflow runs "a hardcoded three-job
   matrix (`e2e-tests.yml:49-50`)". That has been five since G4, and the matrix
   is not at those lines. State the five project names and drop the line
   reference rather than replacing it with another one that will drift.

- [ ] **Step 5: Verify the whole goal**

Run: `cd e2e && npm run typecheck` — expect exit 0.
Run: `./scripts/e2e_up.sh --reset && npx playwright test --project=seeded` — expect
all G5 specs green, with the four `test.fail()` rows reported as **expected**
failures.
Run: `npx playwright test --project=streaming` — same, with one expected failure.

Record actual wall-clock for both projects and compare against what they took
before G5. Report any material increase rather than quietly accepting it: G5
adds seventeen tests to a 4-worker project and two to a 2-worker one, and
should not move either project's time much.

- [ ] **Step 6: Commit**

Commit as `docs(e2e): record G5 coverage`.

---

## Self-Review

**Spec coverage.** D1 → the goal's shape, and Task 8's non-goal note. D2 → the
File Structure table, which touches no config or workflow. D3 → Global
Constraints, applied in Tasks 3–12. D4 → Task 1. D5 → Tasks 10, 12. D6 → Task 10
Steps 2 and 5. D7 → Task 4 Steps 1 and 4, and Task 10 Step 5. D8 → Task 2.
D9 → Task 1, used in Tasks 7 and 10. D10 → Tasks 5, 6, 7, 12 (four defects with
issues) plus Task 12's row 18. D11 → the separate issues filed in Task 5 Step 7
and Task 12 Step 3, each naming the other. D12 → Task 8. D13 → Task 1 Step 4's
factory comment. D14 → Global Constraints, applied in every listing assertion.
D15 → Task 11.
Test inventory rows 1–19 → Tasks 3 (1–2), 4 (3), 5 (4, 5, 17), 6 (6, 19),
7 (7, 8, 15), 8 (9), 9 (10), 10 (11, 12, 13), 11 (14), 12 (16, 18).

**Known deferrals, stated rather than hidden.** Task 10 Step 1 must prove that
`POST /api/accounts/users/` accepts `user_level: 10` before the three-level
matrix depends on it, and says what to do if it does not. Task 3 Step 2 says to
read the emitted origin rather than assume it, because
`build_absolute_uri_with_port` prefers nginx's forwarded headers over the `Host`
header. Task 4 Step 1 requires demonstrating the EPG chunk cache before
depending on the workaround for it. All three are "run this and write down what
it says" steps, not placeholders — the alternative is asserting a value nobody
derived, which is the failure mode this programme has already caught four times.

**Type consistency.** `ChannelGroup`, `ChannelGroupOverrides`, `XcUser`,
`M3uEntry`, `M3uPlaylist`, `XmltvChannel`, `XmltvProgramme` and `XmltvDocument`
are defined in Tasks 1 and 2 before their first use in Task 3. `xcQuery` is
defined in Task 1 Step 5 and used from Task 6 onward with the same
`(user, extra?)` signature throughout. `liveStreams` is a local helper defined
independently in `xc-live.spec.ts` (Task 7) and `output-authorization.spec.ts`
(Task 10) — two copies of four lines, deliberately, because promoting it to a
shared module would put a `/player_api.php` call in the fixture layer where the
next reader would reasonably expect it to be the sanctioned XC client, which it
is not. `lockedProfile` comes from the existing
`e2e/tests/streaming/helpers.ts` in Tasks 11 and 12 and is never redefined.
