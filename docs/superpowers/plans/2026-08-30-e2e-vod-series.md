# G9 — VOD and Series End to End Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that an Xtream Codes catalogue becomes `VODCategory`, `Movie`, `Series` and `Episode` rows with the right fields and the right gating; that the four XC VOD/series list actions and the two detail actions answer correctly against **real content**; and that `vod_proxy` delivers those bytes to a client, including Range and seek.

**Architecture:** No new Playwright project, no CI matrix job, no `scripts/e2e_up.sh` change and no `.github/workflows/e2e-tests.yml` change (spec D13). Eight spec files land in the existing `seeded` project (4 workers, 30 s default timeout — every G9 test there raises its own with `test.setTimeout()`), five in `streaming` (2 workers, 300 s, fake provider available) and one in `streaming-greybox` (1 worker, 300 s, the home for container-wide state hazards). The only `playwright.config.ts` edit is one appended comment line.

**Tech Stack:** TypeScript, Playwright 1.62.x, Node 24, the G1 fixture set (`api`, `seed`, `waitFor`, `streamClient`, `upstream`, `adminPage`, `request`), G2's fake upstream provider as extended by G8 (`xc: true` scenarios, the finite `assets/vod.mp4`, twelve faults), Docker.

**Spec:** `docs/superpowers/specs/2026-08-30-e2e-vod-series-design.md` — read it before Task 1. Where this plan and the spec disagree, the spec wins; every place this plan knowingly departs from it is called out in the task that departs and again in Self-review.

**Verified at:** product code at `4b094f6a` (this worktree's HEAD); `e2e/` and `e2e-upstream/` at `e8f70df9` (`origin/main`, which carries G3, G8 and G6 PR B). Product code is byte-identical between the two — `git diff --stat 4b094f6a origin/main -- apps/ dispatcharr/ core/` prints nothing — so every `apps/…:NNN` citation below was read in this worktree and is valid against `origin/main` too. Line numbers drift; the symbol name is the durable half of every citation.

---

## Global Constraints

Copied from the spec and the programme rules. Every task's requirements implicitly include this section.

- **G9 must not touch the four Lua scripts in `vod_proxy`'s stream counter, or the `active_streams` accounting they implement.** (Spec D12.) `_LUA_INCR_ACTIVE_STREAMS`, `_LUA_DECR_ACTIVE_STREAMS`, `_LUA_CLEANUP_IF_IDLE` and `_LUA_META_SAVE_IF_EXISTS` (`apps/proxy/vod_proxy/multi_worker_connection_manager.py`, lines 20–85) mutate `active_streams` **outside** the session metadata lock deliberately — a real bug fix for Jellyfin-style range-request churn, pinned by `apps/proxy/vod_proxy/tests/test_vod_lock_contention.py` and documented in their own header. Concretely: no G9 test asserts a concurrency property of `active_streams`; no G9 test reads or writes a `vod_persistent_connection:*` hash from outside the product; and **no G9 test that fails may be "fixed" by editing those scripts.** If a G9 row appears to indict them, that is a finding to escalate to the controller, not a patch to write.
- **Product defects are asserted *correct*, marked `test.fail()` with the indicted symbol named in a comment, and filed as issues — never patched.** Issues go to `gh issue create --repo D10Scot/Dispatcharr`; the explicit `--repo` is **mandatory**, because this checkout is a fork of `Dispatcharr/Dispatcharr` and `gh` without it resolves to upstream's public tracker.
  - **A `test.fail()` that asserts the *buggy* behaviour goes green the wrong way and locks the defect in.** Every `test.fail()` in this plan asserts what the product *should* do, so it fails today and turns into a real, loud failure the moment somebody fixes the product. Read each one's assertion before writing it: if it would still pass after the fix, it is written backwards.
- **One defect is NOT to be filed as a public issue.** The spec's **defect 1** — an upstream failure during a VOD stream returns the provider URL, credentials included, to an unauthenticated caller — is a security finding awaiting a disclosure decision from the repo owner. **No task in this plan files it.** Task 11 pins it with a `test.fail()` whose comment names the indicted symbol and says the issue is deliberately unfiled pending that decision, and the task's report records the finding for the controller. Do not run `gh issue create` for it, do not reference it from a public issue body, and do not put a reproduction recipe in a commit message.
- **Never assert a global count or an unfiltered list.** (Roadmap rule 4, and spec D3 sharpens it for VOD.) `VODCategory` is unique on `(name, category_type)` **globally**; `Movie` and `Series` are matched across *all* accounts by TMDB → IMDB → `(name, year)`. Four workers share one container. So: **every scenario declares generated names for movies, series *and* categories**, and no G9 assertion is a count that is not scoped by `?m3u_account=<id>` **and** a generated name.
- **`GET /api/vod/categories/` writes rows.** `VODCategoryViewSet.list` (`apps/vod/api_views.py:647`) `get_or_create`s the two `Uncategorized` categories and, for **every active XC account on the instance with `enable_vod`**, their relations — including other workers' accounts. Locate your own category with `find`, never a length or an index. **No G9 test may assert that an account *lacks* an `Uncategorized` relation.**
- **Every VOD refresh is triggered explicitly by `POST /api/m3u/accounts/<id>/refresh-vod/`** (spec D2) and awaited with `waitFor.resource` on a filtered `/api/vod/movies/` or `/api/vod/series/` read. That action (`M3UAccountViewSet.refresh_vod`, `apps/m3u/api_views.py:444-479`) returns **202** and fires `refresh_vod_content.delay()`; it returns **400** for a non-XC account or one without `custom_properties['enable_vod']`. `waitFor.m3uRefreshComplete` says nothing about VOD — `refresh_vod_content` is a separate task.
- **An XC account create blocks on two synchronous provider round-trips.** `M3UAccountViewSet.create` (`apps/m3u/api_views.py:136-145`) calls `refresh_m3u_groups(account_id)` inline for an XC account and `refresh_categories(account_id)` inline when `enable_vod` is true — neither `.delay()`d, neither wrapped in `try`. **Every G9 `seeded` test therefore calls `test.setTimeout()` on its first line** (spec D4), and a provider fault is armed only *after* the account exists.
- **XC client surfaces are driven through Playwright's built-in `request` context, never the `api` fixture.** (Spec D7, inherited verbatim from G5's D3.) No real XC client carries a bearer token, and `ApiClient.send` retries once through a token refresh **on any 401** — which would silently spend a refresh on exactly the rows that assert a 401. `request` is a built-in of the extended `test`, so `async ({ request, seed }) => …` just works. `api` is for seeding and admin reads only.
- **VOD responses are finite, so `request.get()` is the right tool for reading a VOD body** — unlike live TS, where `APIResponse.body()` would never resolve. Use `streamClient` only where the spec's row calls for it (a `redirect: 'manual'` probe, or a byte-granular read). Note `StreamClient.open()` **throws on any non-2xx** unless `redirect: 'manual'` and the status is 3xx, so a row asserting a 4xx/5xx status must use `request.get()`.
- **The typecheck hook is blocking.** Any edit to `e2e/**/*.ts` runs `tsc --noEmit` for that package and blocks on failure. Run `cd e2e && npm ci` before the first edit or it degrades to a loud note. The same applies to `e2e-upstream/**/*.ts`: run `cd e2e-upstream && npm ci` before Task 1.
- **G9 does not edit `.github/workflows/e2e-tests.yml`.** Editing it re-arms the zizmor hook, which blocks on **every** finding in the edited file. The workflow's seven-project matrix already contains `seeded`, `streaming` and `streaming-greybox`, so G9 needs no change there.
- **G10 (catch-up) is in flight in the same programme and shares four files with G9**: `e2e/COVERAGE.md`, `e2e/README.md`, `e2e/fixtures/types.ts` and `e2e/fixtures/seed.ts`. Every G9 edit to those is **additive and at the end of an existing list**. G10 may also edit `e2e-upstream/src/xc/router.ts` (catch-up routes) and `e2e-upstream/README.md`; Tasks 1 and 2 must append rather than restructure.
- **Import map — every shared symbol comes from exactly one place. Never redefine one locally.**

  | Symbol | From |
  |---|---|
  | `test`, `expect` | `'../../fixtures'` |
  | `Movie`, `Series`, `Episode`, `VodCategory`, `M3uMovieRelation`, `M3uSeriesRelation`, `M3uEpisodeRelation`, `VodLogo`, `CategorySettingRow`, `VodPage` | `'../../fixtures'` (defined in `fixtures/types.ts`, Task 3) |
  | `M3uAccount`, `M3uAccountOverrides`, `User`, `UserOverrides`, `StreamProfile`, `UpstreamScenario`, `UpstreamMovie`, `UpstreamSeries` | `'../../fixtures'` (already exported) |
  | `xcQuery`, `XcUser` | `'../../fixtures'` — **see Task 3 Step 1**; these are G5's and may not have landed yet |
  | `lockedProfile`, `withDeadline`, `newStreamClient` | `'./helpers'` in `e2e/tests/streaming/` (existing) |

---

## Substrate check — what is actually on `main`, and where the spec is now stale

The spec was written at `8d6db577`, before G8 merged. Four of its assumptions have since changed or turned out not to hold. **Every one of these is load-bearing for at least one task**, so they are stated here rather than left to be rediscovered.

| Spec claim | Reality at `e8f70df9` | Consequence |
|---|---|---|
| G5 supplies `seed.xcUser()` and `xcQuery()`, "inherited unchanged" | **G5 has not merged.** `origin/main`'s `e2e/fixtures/seed.ts` has no `xcUser`, and there is no `parse.ts` and no `xcQuery` anywhere. G8 shipped a *local* stand-in, `seedXcUser`, in `e2e/tests/streaming/helpers.ts`, whose own comment says whichever of G5/G9 lands second should reconcile it | **Task 3 Step 1** is a gate: if G5 has landed, use its exports; if not, G9 adds `xcQuery` and `seed.xcUser` itself, in the exact shape G5's plan specifies, and leaves G8's local `seedXcUser` alone for G5 to reconcile |
| Fixture addition: `M3uAccountOverrides` gains `enable_vod`, `auto_enable_new_groups_vod`, `auto_enable_new_groups_series` | **Already there** — `e2e/fixtures/types.ts:646-649`, added by G3/G8 | Task 3 drops that bullet. `seed.xcAccount(scenario, { enable_vod: true })` typechecks today (`e2e/tests/streaming/vod-byte-read.spec.ts` uses it) |
| Fixture addition: `streamClient.readBytes(n)` — "G8's byte-read proof needs this too; if G8 has landed it, G9 uses it unchanged" | **G8 did not add it.** `e2e/fixtures/stream-client.ts` still has only `readPackets`/`collectFor` over the private `takeBytes`. G8's byte-read proof used `request.get()` instead | Task 3 adds `readBytes` |
| Rows 1, 2 and 19 live in `e2e/tests/seeded/vod-catalogue-ingest.spec.ts` | **That file already exists** — it is G8's plumbing proof 2 | G9's rows go in a **new** file, `e2e/tests/seeded/vod-ingest-fidelity.spec.ts`. G8's file is not touched |
| "There is no `frontend` project yet" | There is — G6 PR B merged at `e8f70df9`; the CI matrix is now seven projects | Cosmetic for G9, but the README's CI paragraph is already correct and must not be "fixed" back |

Three further facts G8 recorded in `e2e/COVERAGE.md` that the spec did not have:

- **The spec's defect 6 is already filed as [#66](https://github.com/D10Scot/Dispatcharr/issues/66)**, and the spec's `range-unsupported` mechanism is confirmed byte-for-byte there (a 100-byte body claiming `Content-Range: bytes 100-199/125585` that is actually bytes 0–99). **Task 10 must not file it again** — it references #66.
- **A seventh, related defect is already filed as [#64](https://github.com/D10Scot/Dispatcharr/issues/64)**: `_validate_range_header` (`multi_worker_connection_manager.py:580-612`) splits `bytes=<start>-<end>` on the first `-` and treats an empty `start_str` as `start_byte = 0`, so the suffix range `bytes=-500` ("the last 500 bytes", RFC 9110) is silently reinterpreted as `bytes=0-500`. `COVERAGE.md` assigns the pin to G9. **Task 10 pins it** — no new issue.
- **`not-found` and `auth-failure` are no-ops on the provider's `/movie/` and `/series/` routes.** They never reach `serveChannelStream`, which is where `/live/` and both catch-up routes inherit them. `COVERAGE.md` assigns the fix to G9, at the `handleXc` seam. **Task 2 does it** — rows 15 and 17 cannot exist without it.

---

## File structure

**Created:**

| Path | Responsibility | Task |
|---|---|---|
| `e2e/tests/seeded/vod-fixture.spec.ts` | Proves the Task 3 fixture additions before anything consumes them | 3 |
| `e2e/tests/seeded/vod-ingest-fidelity.spec.ts` | Rows 1, 2, 19 — catalogue ingest fidelity, category rows, and defect 5 | 4 |
| `e2e/tests/seeded/vod-category-gating.spec.ts` | Rows 3, 4, 5 — gating on, gating off, `Uncategorized` | 5 |
| `e2e/tests/seeded/vod-episodes.spec.ts` | Rows 6, 7 — on-demand episode ingest, both `episodes` shapes | 6 |
| `e2e/tests/seeded/vod-advanced-data.spec.ts` | Row 8 — advanced data, the 24 h throttle, and list-sync survival | 7 |
| `e2e/tests/seeded/xc-vod-catalogue.spec.ts` | Rows 9, 10, 20 — the six XC VOD/series actions, adult listing, defect 2 | 8 |
| `e2e/tests/streaming/vod-stream.spec.ts` | Rows 11, 12 — session mint, byte delivery, episode/series entry points | 9 |
| `e2e/tests/streaming/xc-vod-playback.spec.ts` | Row 14 — the root XC playback routes, plus the episode-404 defect | 9 |
| `e2e/tests/streaming/vod-range.spec.ts` | Rows 13, 17, 18 + the #64 suffix-range pin | 10 |
| `e2e/tests/streaming/vod-upstream-error.spec.ts` | Row 15 — defect 1, the credential-disclosure pin. **Files no issue** | 11 |
| `e2e/tests/streaming/vod-adult-streamable.spec.ts` | Row 16 — defect 4, unlistable-but-streamable | 11 |
| `e2e/tests/streaming-greybox/vod-redirect-profile.spec.ts` | Row 21 — VOD Redirect mode | 12 |

**Modified:**

| Path | Change | Task | Shared with |
|---|---|---|---|
| `e2e-upstream/src/scenario.ts` | `MovieSpec.isAdult`/`categoryId: number \| null`/`vodInfo`; `SeriesSpec.seasonsAsArray`; their door validators | 1 | G10 may touch this file |
| `e2e-upstream/src/xc/catalogue.ts` | Emit the four new fields; array-shaped `episodes` | 1 | — |
| `e2e-upstream/src/xc/router.ts` | Honour `auth-failure` and `not-found` on `/movie/` and `/series/` | 2 | **G10 owns the catch-up branches of this file** |
| `e2e-upstream/README.md` | Scenario-field table, fault table, the "no effect on `/movie|series/`" paragraph | 1, 2 | G10 |
| `e2e-upstream/test/scenario.test.ts` | Door cases for the four new fields | 1 | — |
| `e2e-upstream/test/xc-catalogue.test.ts` | Render cases for the four new fields | 1 | — |
| `e2e-upstream/test/xc-faults.test.ts` | `auth-failure`/`not-found` on the VOD routes | 2 | G10 |
| `e2e/fixtures/stream-client.ts` | `readBytes(n)` | 3 | — |
| `e2e/fixtures/types.ts` | Seven VOD entity types, `VodPage`, `CategorySettingRow`, `VodLogo`; the `UpstreamMovie`/`UpstreamSeries` addendum mirrors | 3 | **G10** |
| `e2e/fixtures/upstream.ts` | Header note on `not-found`/`auth-failure` reaching the VOD routes | 3 | G10 |
| `e2e/fixtures/index.ts` | Export the new types and `readBytes`; extend the header inventory | 3 | **G10** |
| `e2e/fixtures/seed.ts` | **Only if G5 has not landed:** `xcUser()` | 3 | **G10** |
| `e2e/fixtures/parse.ts` | **Only if G5 has not landed:** created, with `xcQuery` | 3 | G5 |
| `e2e/playwright.config.ts` | One appended comment line on `streaming-greybox` | 12 | G10 |
| `e2e/COVERAGE.md` | Eleven G9 rows → `done`/`known-bug`; new rows; spec-file list; gap notes | 13 | **G10** |
| `e2e/README.md` | A "VOD" section; fixture-table and export-table entries | 13 | **G10** |

**Which tasks touch shared files.** Tasks **1, 2, 3, 12 and 13** touch files another task or another goal also edits. Tasks **4–11** are entirely file-disjoint: each creates exactly one or two spec files under `e2e/tests/` and modifies nothing. Sequence 1 → 2 → 3 first (they are the substrate), then 4–12 in any order or in parallel, then **13 last** — it lists the files the others create.

---

### Task 1: The G8 provider addendum — three `MovieSpec` fields and array-shaped seasons

Implements the spec's "What G9 needs from G8 that G8 does not have", plus the array-`episodes` shape that G8's own `renderSeriesInfo` comment defers to G9 ("`batch_process_episodes` also accepts a JSON array; a scenario that wants that shape is G9's to add, and this renderer is where it goes" — `e2e-upstream/src/xc/catalogue.ts`).

**This task is gated. It is not yet agreed.**

**Files:**
- Modify: `e2e-upstream/src/scenario.ts`
- Modify: `e2e-upstream/src/xc/catalogue.ts`
- Modify: `e2e-upstream/README.md`
- Modify: `e2e-upstream/test/scenario.test.ts`
- Modify: `e2e-upstream/test/xc-catalogue.test.ts`

**Interfaces produced:**
- `MovieSpec.isAdult?: boolean`
- `MovieSpec.categoryId: number | null` (was `number`)
- `MovieSpec.vodInfo?: Record<string, unknown>`
- `SeriesSpec.seasonsAsArray?: boolean`

- [ ] **Step 1: The gate**

Ask the controller whether the addendum is agreed **before writing any code**. It is a change to another goal's shipped component, and the spec lists it as an open dependency.

- **Agreed** → do the whole task.
- **Declined** → do nothing here; record the decision; Tasks 3, 5, 6, 8 and 11 each take the fallback named in their own Step 1. Note in the report that declining costs **row 16 and the positive half of row 10 entirely** — "adult VOD filtering is unobservable end to end" is the only VOD authorization property in the goal, and there is no other way to set `Movie.is_adult` (`MovieViewSet` is a `ReadOnlyModelViewSet`, and `process_movie_batch` writes the field only when the provider's entry carries an `is_adult` key: `apps/vod/tasks.py:534`).
- **Partially agreed** → implement only the agreed fields and record which ones. Each dependent task names its fallback per field.

Run `cd e2e-upstream && npm ci` before the first edit so the typecheck hook is real rather than a note.

- [ ] **Step 2: Widen `MovieSpec` and `SeriesSpec`**

In `e2e-upstream/src/scenario.ts`, in `interface MovieSpec`, change `categoryId` and append two optional fields:

```ts
  /**
   * `null` means "emit no `category_id` key at all" — the only way to route a
   * movie into Dispatcharr's own `Uncategorized` bucket through the product's
   * real path. `process_movie_batch` (`apps/vod/tasks.py`) looks the provider's
   * `category_id` up in a string-keyed map and falls through to
   * `categories['__uncategorized__']` when it is absent or unknown; there is no
   * other way in.
   *
   * Undefined still defaults to the first declared VOD category, exactly as
   * before — `null` is a deliberate declaration, not an omission.
   */
  categoryId: number | null;
  /**
   * Emitted as `is_adult: 1`/`0` on the `get_vod_streams` entry, and **only
   * when declared**. `process_movie_batch` writes `Movie.is_adult` only when
   * the key is present (`apps/vod/tasks.py:534`, via
   * `parse_is_adult` in `apps/m3u/utils.py:25`), deliberately, so that a sparse
   * provider cannot clear a flag another provider set. Leaving this undefined
   * therefore reproduces a sparse provider; setting it reproduces one that
   * reports.
   */
  isAdult?: boolean;
  /**
   * **Replaces** — never merges with — the default `info` object
   * `renderVodInfo` builds for this movie. A merge could only ever *add* keys,
   * and the shape a test needs here is defined by what it *omits*: an advanced
   * payload carrying `bitrate`/`video`/`audio` and none of
   * `director`/`actors`/`youtube_trailer`/`backdrop_path` is what leaves
   * `Movie.custom_properties` at `None` after a successful advanced refresh
   * (`clean_custom_properties({})` returns `None`, `apps/vod/tasks.py:2132`).
   * `movie_data` is unaffected and still rendered from the movie entry.
   */
  vodInfo?: Record<string, unknown>;
```

In `interface SeriesSpec`, append:

```ts
  /**
   * When true, `get_series_info` emits `episodes` as a **JSON array** indexed
   * by position rather than an object keyed by season number — what a PHP
   * panel's `json_encode` produces when the season keys happen to be
   * contiguous from 0. `batch_process_episodes` (`apps/vod/tasks.py:1387`)
   * accepts both and uses the key *or the index* as the season number, so
   * season `0` is real under this shape and unreachable under the other.
   *
   * The door requires `seasons[i].number === i` when this is set, so the
   * declared season number and the index a client will infer can never
   * disagree.
   */
  seasonsAsArray?: boolean;
```

`ResolvedChannelSpec` and every other type are untouched. `defaultMovies` and `defaultSeries` are untouched — they already produce a concrete `categoryId` and no `isAdult`/`vodInfo`/`seasonsAsArray`.

- [ ] **Step 3: Validate the new fields at the door**

In `parseMovies` (`e2e-upstream/src/scenario.ts`), replace the `categoryId` block with:

```ts
    const categoryId = v.categoryId === undefined ? categories[0].id : v.categoryId;
    if (categoryId !== null) {
      if (!isNonNegativeInteger(categoryId)) {
        throw new BadRequestError(
          `'${field}' entry '${v.name}' categoryId must be a non-negative integer or null`,
        );
      }
      assertKnownCategory(categoryId, categories, `${field}.categoryId`);
    }
```

and add, before the `return`:

```ts
    if (v.isAdult !== undefined && typeof v.isAdult !== 'boolean') {
      throw new BadRequestError(`'${field}' entry '${v.name}' isAdult must be a boolean`);
    }
    const isAdult = v.isAdult as boolean | undefined;

    if (
      v.vodInfo !== undefined &&
      (typeof v.vodInfo !== 'object' || v.vodInfo === null || Array.isArray(v.vodInfo))
    ) {
      throw new BadRequestError(
        `'${field}' entry '${v.name}' vodInfo must be an object; it replaces the whole 'info' payload of get_vod_info`,
      );
    }
    const vodInfo = v.vodInfo as Record<string, unknown> | undefined;
```

and widen the returned object to `{ id, name, year, categoryId, containerExtension, tmdbId, imdbId, ...(isAdult === undefined ? {} : { isAdult }), ...(vodInfo === undefined ? {} : { vodInfo }) }`. Spreading conditionally (rather than assigning `undefined`) keeps the echoed scenario free of `"isAdult": null` noise, matching how `tmdbId`/`imdbId` are already handled in `movieEntry`.

In `parseSeries`, after `parseSeasons` returns:

```ts
    if (v.seasonsAsArray !== undefined && typeof v.seasonsAsArray !== 'boolean') {
      throw new BadRequestError(`'${field}' entry '${v.name}' seasonsAsArray must be a boolean`);
    }
    if (v.seasonsAsArray === true) {
      seasons.forEach((season, index) => {
        if (season.number !== index) {
          // Under the array shape the *index* is the season number the client
          // infers. Accepting a mismatch would produce a scenario whose
          // declared season numbers and ingested season numbers differ for a
          // reason no failure message could explain.
          throw new BadRequestError(
            `'${field}' entry '${v.name}' declares seasonsAsArray but seasons[${index}].number is ${season.number}; under the array shape the position IS the season number, so they must match`,
          );
        }
      });
    }
```

- [ ] **Step 4: Render the new fields**

In `e2e-upstream/src/xc/catalogue.ts`:

1. `movieEntry` — replace the unconditional `category_id` line and the `is_adult` comment:

```ts
    ...(movie.categoryId === null ? {} : { category_id: String(movie.categoryId) }),
    ...(movie.isAdult === undefined ? {} : { is_adult: movie.isAdult ? 1 : 0 }),
```

Keep the existing comment explaining why `is_adult` is absent by default; extend it with "…unless the scenario declares `isAdult`".

2. `renderVodStreams` — a movie with `categoryId === null` must never match a `category_id=` filter:

```ts
  return scenario.vod
    .filter(
      (movie) =>
        categoryId === null ||
        (movie.categoryId !== null && String(movie.categoryId) === categoryId),
    )
    .map(movieEntry);
```

3. `renderVodInfo` — `vodInfo` replaces the whole `info` object:

```ts
  return {
    info: movie.vodInfo ?? {
      plot: `${movie.name} — e2e fixture, detailed`,
      /* …the existing default object, unchanged… */
    },
    movie_data: movieEntry(movie),
  };
```

4. `renderSeriesInfo` — when `series.seasonsAsArray` is true, build a positional array instead of the keyed object. Extract the per-season episode mapping into a local `renderSeason(season)` so the two shapes cannot drift, then:

```ts
  const episodes = series.seasonsAsArray
    ? series.seasons.map(renderSeason)
    : Object.fromEntries(series.seasons.map((season) => [String(season.number), renderSeason(season)]));
```

- [ ] **Step 5: Vitest cases**

In `e2e-upstream/test/scenario.test.ts`, add door cases asserting **exact** messages:

1. `{ xc: true, username: 'u', password: 'p', vod: [{ id: 1, name: 'm', categoryId: null }] }` parses, and the resolved movie has `categoryId: null`.
2. `vod: [{ id: 1, name: 'm', categoryId: 99 }]` with `vodCategories: [{ id: 1, name: 'c' }]` throws `BadRequestError` whose message contains `references categoryId 99`.
3. `vod: [{ id: 1, name: 'm', isAdult: 'yes' }]` throws, message contains `isAdult must be a boolean`.
4. `vod: [{ id: 1, name: 'm', vodInfo: [] }]` throws, message contains `vodInfo must be an object`.
5. `series: [{ id: 1, name: 's', seasonsAsArray: true, seasons: [{ number: 1, episodes: [] }] }]` throws, message contains `seasons[0].number is 1`.
6. `series: [{ id: 1, name: 's', seasonsAsArray: true, seasons: [{ number: 0, episodes: [] }, { number: 1, episodes: [] }] }]` parses.

In `e2e-upstream/test/xc-catalogue.test.ts`:

7. `renderVodStreams` omits `category_id` for a `categoryId: null` movie, and includes it as a **string** otherwise.
8. A `categoryId: null` movie is absent from `renderVodStreams(scenario, '1')` and present in `renderVodStreams(scenario, null)`.
9. `renderVodStreams` emits `is_adult: 1` for `isAdult: true`, `is_adult: 0` for `isAdult: false`, and **no `is_adult` key at all** when undefined (`expect(entry).not.toHaveProperty('is_adult')` — not `toBeUndefined()`, which passes on an absent *and* a present-but-undefined key).
10. `renderVodInfo(...).info` deep-equals the declared `vodInfo` exactly — no default keys survive — while `.movie_data.stream_id` is still the movie id.
11. `renderSeriesInfo` returns `episodes` as an `Array` under `seasonsAsArray: true` with `episodes[0]` being season 0's list, and as a keyed object otherwise. Assert `Array.isArray(info.episodes)` explicitly; a JSON round trip would hide the difference from a shallow `toEqual`.

- [ ] **Step 6: Document it**

In `e2e-upstream/README.md`, in the `POST /scenarios` field list (the block that already documents `liveCategories` / `vodCategories` / `vod` / `series`), append entries for `isAdult`, `categoryId: null`, `vodInfo` and `seasonsAsArray`, each in one or two sentences, each naming the product symbol that makes it matter. Keep the existing "VOD and category rows are not scenario-scoped in the product" warning where it is.

- [ ] **Step 7: Verify**

Run:

```bash
cd /Users/dion/git/<worktree>/e2e-upstream && npm run typecheck && npm test
```

Expected: exit 0 from both, with the eleven new cases passing and **no existing case changed**. If an existing `scenario.test.ts` or `xc-catalogue.test.ts` case had to be edited to keep passing, the change is not additive — stop and report rather than adjusting the old case.

- [ ] **Step 8: Commit**

`test(e2e-upstream): declare adult, uncategorised, advanced-payload and array-season movies (G9 addendum)`

---

### Task 2: `not-found` and `auth-failure` reach the provider's VOD routes

Closes the `todo` Gap row `e2e/COVERAGE.md` already assigns to G9 ("`not-found`/`auth-failure` have no effect on `/movie/…` or `/series/…` … G9 should decide whether VOD-playback faults need `not-found`/`auth-failure` coverage and, if so, fix it once at the seam"). **Rows 15 and 17 cannot exist without this.** Independent of Task 1's gate — this one is already sanctioned.

**Files:**
- Modify: `e2e-upstream/src/xc/router.ts`
- Modify: `e2e-upstream/test/xc-faults.test.ts`
- Modify: `e2e-upstream/README.md`

- [ ] **Step 1: Confirm the gap is still there**

Read the `vodMatch` branch of `handleXc` in `e2e-upstream/src/xc/router.ts` — the block guarded by
`/^\/(movie|series)\/([^/]+)\/([^/]+)\/(\d+)\.[A-Za-z0-9]+$/`. As of `e8f70df9` it checks **only** `range-unsupported`, via `context.faults.isActive(scenario.id, 'range-unsupported')` in the `serveVodAsset` call. If `auth-failure` or `not-found` already appear there, this task is done — record that and stop.

- [ ] **Step 2: Add the two checks, in the same order `/player_api.php` uses**

`auth-failure` goes **before** the credential comparison, matching `/player_api.php` and `serveChannelStream` — the fault models valid credentials that stop being accepted, which must win over a 401 that would otherwise read as "the credentials were always wrong". Insert immediately after the two `decodeURIComponent` guards and before `if (!xcCredentialsMatch(...))`:

```ts
    // Checked ahead of the credential comparison, exactly as `/player_api.php`
    // and `serveChannelStream` do. Scenario-wide only: a VOD id is not a
    // channel id, so there is no channel scope to resolve against — a
    // `{ channel: n }` arm stores under scope `n` (see `scopeOf` in
    // `faults.ts`) and this check, which passes no channel, will not see it.
    if (context.faults.isActive(scenario.id, 'auth-failure')) {
      log(401);
      sendJson(401, { error: 'fault: auth-failure' });
      return true;
    }
```

`not-found` goes **after** the membership check, so an id the scenario genuinely does not declare still produces the specific `declares no ${kind} with id ${wanted}` message rather than the generic fault one. Insert immediately before the `serveVodAsset` call:

```ts
    if (context.faults.isActive(scenario.id, 'not-found')) {
      log(404);
      sendJson(404, { error: 'fault: not-found' });
      return true;
    }
```

Do not add a method gate. `COVERAGE.md`'s neighbouring Gap row (`handleXc` has no method check, so `POST /movie/...` and `POST /player_api.php` answer 200 instead of 405) lands at this same seam, but no G9 test exercises a non-GET VOD request, and a behaviour change nothing asserts is a change nobody can verify. Task 13 re-states that row as still `todo` with this reason.

- [ ] **Step 3: Vitest cases**

In `e2e-upstream/test/xc-faults.test.ts`, alongside the existing `range-unsupported` VOD describes, add four cases against a scenario declaring one movie and one series with one episode:

1. `not-found` armed scenario-wide → `GET /s/<id>/movie/<u>/<p>/1.mp4` answers **404** with body `{ error: 'fault: not-found' }`, and the scenario log records a `request` entry with `status: 404`.
2. Same fault → `GET /s/<id>/series/<u>/<p>/<episodeId>.mp4` answers 404.
3. `auth-failure` armed → `/movie/<u>/<p>/1.mp4` with the **correct** credentials answers **401** with `{ error: 'fault: auth-failure' }`.
4. `not-found` armed with `{ channel: 1 }` → `/movie/<u>/<p>/1.mp4` still answers **200**, because a channel-scoped arm is invisible to a scenario-wide check. Assert this rather than leaving it implicit: it is the one surprising consequence of the scoping, and a test author who arms it that way would otherwise see a silent no-op.

- [ ] **Step 4: Correct the README**

In `e2e-upstream/README.md`, the paragraph beginning "**`auth-failure` and `xc-auth-envelope` compose on `player_api.php` only.**" currently ends: "The `/movie/` and `/series/` VOD routes do **not** — they never reach `serveChannelStream` — so `not-found`/`auth-failure` have no effect there, unchanged from before this fault set existed."

Replace that sentence with a statement that the `/movie/` and `/series/` routes now honour both **when armed scenario-wide** (no `channel`), checked directly in `handleXc` rather than inherited from `serveChannelStream`, and that a channel-scoped arm does not reach them because a VOD id is not a channel id. Update the `not-found` and `auth-failure` rows of the fault table's "Applies to" column to say `live + VOD (scenario-wide)`.

- [ ] **Step 5: Verify**

```bash
cd /Users/dion/git/<worktree>/e2e-upstream && npm run typecheck && npm test
```

Expected: exit 0, four new cases passing, no existing case changed.

- [ ] **Step 6: Commit**

`test(e2e-upstream): honour not-found and auth-failure on the VOD playback routes`

---

### Task 3: The `e2e/` fixture surface

Everything Tasks 4–12 import. Touches four shared fixture files, so it lands before any consumer and its edits are strictly additive, at the end of each existing list.

**Files:**
- Modify: `e2e/fixtures/stream-client.ts`
- Modify: `e2e/fixtures/types.ts`
- Modify: `e2e/fixtures/upstream.ts`
- Modify: `e2e/fixtures/index.ts`
- Modify (**only if G5 has not landed** — see Step 1): `e2e/fixtures/seed.ts`
- Create (**only if G5 has not landed**): `e2e/fixtures/parse.ts`
- Create: `e2e/tests/seeded/vod-fixture.spec.ts`

- [ ] **Step 1: The two gates**

Run:

```bash
cd /Users/dion/git/<worktree>/e2e && npm ci
grep -n 'xcUser' fixtures/seed.ts; grep -n 'xcQuery' fixtures/index.ts
```

- **Both print a match** → G5 has landed. Import `xcQuery`, `XcUser` and `seed.xcUser` from `'../../fixtures'` throughout G9 and **skip Step 5**.
- **Neither prints** → G5 has not landed. Do Step 5. Note that G8 already ships a local `seedXcUser` in `e2e/tests/streaming/helpers.ts`; **leave it alone.** Its own comment assigns the reconciliation to whichever of G5/G9 lands second, but deleting it would edit a file three G8 specs import while G5's own branch is still in flight. Task 13 records the duplication as a `todo` note naming G5 as the owner.

Second gate: read Task 1's outcome. If the addendum was **declined**, skip the `UpstreamMovie`/`UpstreamSeries` widening in Step 3 and leave those two types exactly as they are.

- [ ] **Step 2: `streamClient.readBytes`**

In `e2e/fixtures/stream-client.ts`, immediately after `readPackets`:

```ts
  /**
   * Exactly `count` bytes, with no 188-byte multiplier.
   *
   * `readPackets` is the MPEG-TS reader and is the wrong tool for VOD: a VOD
   * body is an MP4, has no packet structure, and its interesting reads are
   * byte offsets ("the 8 192 bytes starting at 40 000"), not packet counts.
   * Same pump, same private `takeBytes`, same "throws if the stream ends
   * first" contract.
   */
  async readBytes(count: number): Promise<Buffer> {
    await this.fill(count);
    return this.takeBytes(count);
  }
```

Read the existing `readPackets` body first and mirror it exactly — if it inlines its accumulate loop rather than calling a `fill` helper, inline the same loop here with `wanted = count`. The one rule: **do not duplicate `takeBytes`**, and do not change `readPackets`.

Export it from `e2e/fixtures/index.ts` implicitly (the class is already exported) and add it to that file's `streamClient` header entry: `open`, `readPackets`, `readBytes`, `collectFor`, `close`.

- [ ] **Step 3: The types**

Append to `e2e/fixtures/types.ts`, at the end of the file, each with the serializer it came from named in its doc comment, per that file's convention:

```ts
/** `VODLogoSerializer`; the model is `apps/vod/models.py` `VODLogo` (`name`, unique `url`). */
export type VodLogo = { id: number; name: string; url: string };

/**
 * `/api/vod/movies/` — `MovieSerializer`, `fields = '__all__'` plus a nested
 * read-only `logo`. Nullability is the model's (`apps/vod/models.py` `Movie`).
 *
 * `custom_properties` is `None` far more often than it looks: ingest sets it
 * to `custom_props or None` and only ever populates
 * `youtube_trailer`/`director`/`actors`/`release_date`
 * (`apps/vod/tasks.py`, `process_movie_batch`), and
 * `clean_custom_properties({})` returns `None`. A provider entry carrying none
 * of those four leaves it null — which is the precondition of the
 * `get_vod_info` defect pinned in `xc-vod-catalogue.spec.ts`.
 *
 * `rating` is a `CharField`, not a number.
 */
export type Movie = {
  id: number;
  uuid: string;
  name: string;
  description: string | null;
  year: number | null;
  rating: string | null;
  genre: string | null;
  duration_secs: number | null;
  logo: VodLogo | null;
  tmdb_id: string | null;
  imdb_id: string | null;
  is_adult: boolean;
  custom_properties: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

/** `/api/vod/series/` — `SeriesSerializer`, `fields = '__all__'` plus nested `logo` and the `episode_count` method field. `Series` has no `is_adult` and no `duration_secs`. */
export type Series = {
  id: number;
  uuid: string;
  name: string;
  description: string | null;
  year: number | null;
  rating: string | null;
  genre: string | null;
  logo: VodLogo | null;
  tmdb_id: string | null;
  imdb_id: string | null;
  custom_properties: Record<string, unknown> | null;
  episode_count: number;
  created_at: string;
  updated_at: string;
};

/**
 * `/api/vod/episodes/` — `EpisodeSerializer`, `fields = '__all__'` with a
 * nested read-only `series`. `season_number` and `episode_number` are both
 * `IntegerField(null=True)` and both participate in
 * `unique_together ('series', 'season_number', 'episode_number')`.
 */
export type Episode = {
  id: number;
  uuid: string;
  name: string;
  description: string | null;
  air_date: string | null;
  rating: string | null;
  duration_secs: number | null;
  series: Series;
  season_number: number | null;
  episode_number: number | null;
  tmdb_id: string | null;
  imdb_id: string | null;
  custom_properties: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

/**
 * `/api/vod/categories/` — `VODCategorySerializer`. **Unpaginated**: no
 * `pagination_class` on `VODCategoryViewSet` and no
 * `DEFAULT_PAGINATION_CLASS` in `dispatcharr/settings.py`, so the list
 * endpoint returns a bare array of every category on the instance. Locate
 * yours with `find`, never a length or an index.
 *
 * `m3u_accounts` is `M3UVODCategoryRelationSerializer(source='m3u_relations')`,
 * whose three fields are exactly `category` (the id), `m3u_account` (the id)
 * and `enabled` — not nested objects.
 */
export type VodCategoryRelation = {
  category: number;
  m3u_account: number;
  enabled: boolean;
};
export type VodCategory = {
  id: number;
  name: string;
  category_type: 'movie' | 'series';
  category_type_display: string;
  m3u_accounts: VodCategoryRelation[];
};

/**
 * `/api/vod/movies/<pk>/providers/` — `M3UMovieRelationSerializer`,
 * `fields = '__all__'` with `movie`, `category` and `m3u_account` all nested
 * as full objects, plus a `quality_info` method field.
 *
 * `custom_properties` is the read-back surface for "what did the provider
 * actually say": `basic_data` is the whole `get_vod_streams` entry,
 * `detailed_info`/`movie_data` arrive from `refresh_movie_advanced_data`, and
 * `detailed_fetched` gates the 24-hour throttle.
 */
export type M3uMovieRelation = {
  id: number;
  movie: Movie;
  category: VodCategory | null;
  m3u_account: M3uAccount;
  stream_id: string;
  container_extension: string | null;
  custom_properties: Record<string, unknown> | null;
  last_advanced_refresh: string | null;
  last_seen: string;
  created_at: string;
  updated_at: string;
};

/** `/api/vod/series/<pk>/providers/` — `M3USeriesRelationSerializer`, `fields = '__all__'`. **`id` is what XC's `get_series` emits as `series_id`** — not `Series.id`. */
export type M3uSeriesRelation = {
  id: number;
  series: Series;
  category: VodCategory | null;
  m3u_account: M3uAccount;
  external_series_id: string;
  custom_properties: Record<string, unknown> | null;
  last_episode_refresh: string | null;
  last_seen: string;
  created_at: string;
  updated_at: string;
};

/** `M3UEpisodeRelationSerializer`, `fields = '__all__'`. `unique_together` is `('m3u_account', 'stream_id')`, so several relations may point at one `Episode`. */
export type M3uEpisodeRelation = {
  id: number;
  episode: Episode;
  series_relation: number | null;
  m3u_account: M3uAccount;
  stream_id: string;
  container_extension: string | null;
  custom_properties: Record<string, unknown> | null;
  last_seen: string;
  created_at: string;
  updated_at: string;
};

/**
 * One row of the `category_settings` array in the body of
 * `PATCH /api/m3u/accounts/<id>/group-settings/`
 * (`M3UAccountViewSet.update_group_settings`, `apps/m3u/api_views.py`).
 *
 * **The key is `id` — the `VODCategory` primary key — not `category`.** Rows
 * without it are silently skipped. Like {@link GroupSettingRow}, this action
 * uses no serializer and issues a `bulk_create(update_conflicts=True,
 * update_fields=['enabled', 'custom_properties'])`, so an omitted field is
 * written as its zero value: omitting `custom_properties` writes `{}`.
 */
export type CategorySettingRow = {
  id: number;
  enabled: boolean;
  custom_properties: Record<string, unknown>;
};

/** `VODPagination` — `page_size` 20, `page_size` query param up to 100. Movies, series and episodes all paginate; categories do not. */
export type VodPage<T> = { count: number; next: string | null; previous: string | null; results: T[] };
```

Then, **only if Task 1 landed**, widen the two upstream mirrors already in this file:

- `UpstreamMovie.categoryId` becomes `number | null`, and the type gains `isAdult?: boolean` and `vodInfo?: Record<string, unknown>`.
- `UpstreamSeries` gains `seasonsAsArray?: boolean`.

Each with a one-line comment pointing at `MovieSpec`/`SeriesSpec` in `e2e-upstream/src/scenario.ts`, matching how the existing mirrors are annotated. Note for the implementer: `UpstreamMovie` declares `containerExtension`, `tmdbId` and `imdbId` as **required** even though the provider's own door defaults them — G8's `vod-catalogue-ingest.spec.ts` records this. Do not "fix" that; every G9 scenario literal supplies all three.

- [ ] **Step 4: `upstream.ts` header note**

In `e2e/fixtures/upstream.ts`, the block comment above `export type FaultName` lists the scoping quirk of each of G8's four additions. Append a fifth bullet — **only if Task 2 landed** — recording that `not-found` and `auth-failure`, though channel-scopable in general, reach `/movie/` and `/series/` **only when armed scenario-wide**, because a VOD id is not a channel id and the VOD branch of `handleXc` resolves them with no channel argument.

- [ ] **Step 5: `xcQuery` and `seed.xcUser` — only if Step 1's first gate said G5 has not landed**

Create `e2e/fixtures/parse.ts` containing exactly G5's `xcQuery` (its plan, Task 1 Step 5) — the function, its doc comment, and its `import type { XcUser } from './types';`:

```ts
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

Add `export type XcUser = User & { xcPassword: string };` to `e2e/fixtures/types.ts` with G5's doc comment — the load-bearing sentence being **"The XC username is the Django username"**: there is no `xc_username` custom property anywhere in the product; `xc_get_user`, `stream_xc_movie` and `stream_xc_episode` all do `get_object_or_404(User, username=…)` and then compare `custom_properties['xc_password']`.

Add `seed.xcUser` to `e2e/fixtures/seed.ts`, after `user()`, exactly as G5's plan specifies — generating the password with `this.generatedName('xc-secret')` and spreading `xc_password` **after** the caller's `custom_properties` so a caller cannot substitute one. The password is a per-run throwaway on purpose: XC credentials travel in query strings, Dispatcharr logs full provider URLs at INFO, and the CI failure step prints `docker logs dispatcharr-e2e` into the log. **Do not introduce a fixed XC password.**

Export `xcQuery` from `e2e/fixtures/index.ts` and add `xcUser` to that file's `seed` inventory. Write a one-line comment above the export saying this is G5's contract, carried by G9 because G5 had not merged, and that G5's branch should delete whichever copy lands second.

- [ ] **Step 6: The fixture spec**

Create `e2e/tests/seeded/vod-fixture.spec.ts` with three tests:

```ts
import { test, expect } from '../../fixtures';
import type { VodCategory } from '../../fixtures';

test('readBytes returns exactly the requested byte count', async ({ upstream, streamClient }) => {
  test.setTimeout(60_000);
  // The provider's own control origin, not the product: this asserts the
  // fixture, not Dispatcharr. A scenario with one movie is the cheapest way
  // to get a finite body with a known length.
  const scenario = await upstream.scenario({
    xc: true,
    username: 'readbytes-u',
    password: 'readbytes-p',
    vod: [{ id: 1, name: 'readbytes-movie', year: 2020, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null }],
    series: 0,
  });
  await streamClient.open(
    upstream.toControl(`${scenario.internal}/movie/readbytes-u/readbytes-p/1.mp4`)
  );
  const head = await streamClient.readBytes(8);
  expect(head.byteLength).toBe(8);
  // `ftyp` is the first box of every MP4 — proves the bytes are the asset's
  // and start at offset zero, not that eight arbitrary bytes arrived.
  expect(head.subarray(4, 8).toString('ascii')).toBe('ftyp');
});

test('the VOD category list is an unpaginated array', async ({ api }) => {
  test.setTimeout(60_000);
  // Pins the shape VodCategory[] depends on: a bare array, not { results }.
  // VODCategoryViewSet declares no pagination_class and settings.py sets no
  // DEFAULT_PAGINATION_CLASS. If this ever starts returning an object, every
  // `find` in G9 silently stops finding anything.
  const body = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'vod categories');
  expect(Array.isArray(body)).toBe(true);
});
```

Plus, **only if Step 5 ran**, G5's own `seed.xcUser` case: the generated `xcPassword` is not `SEEDED_USER_PASSWORD`, and `GET /player_api.php${xcQuery(user)}` answers 200.

- [ ] **Step 7: Verify**

```bash
cd /Users/dion/git/<worktree>/e2e && npm run typecheck
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded vod-fixture
```

Expected: typecheck exit 0; all tests in the file pass.

- [ ] **Step 8: Commit**

`test(e2e): VOD entity types, readBytes, and the XC credential helpers (G9)`

---

### Task 4: Rows 1, 2 and 19 — catalogue ingest fidelity, category rows, and the `m3u_account` filter defect

Row 1 asserts what a `Movie`/`Series` actually contains after ingest; row 2 asserts the categories; row 19 pins the spec's **defect 5**.

**This is a new file. `e2e/tests/seeded/vod-catalogue-ingest.spec.ts` already exists — it is G8's plumbing proof that the rows appear at all, and it is not touched.** G9's rows go in `vod-ingest-fidelity.spec.ts`.

**Files:**
- Create: `e2e/tests/seeded/vod-ingest-fidelity.spec.ts`

- [ ] **Step 1: The scenario and the account**

One scenario, reused by all three tests via a local `async function seedCatalogue(...)` in the file — or duplicated per test if that reads more plainly; do not promote it to `e2e/fixtures/`.

```ts
const prefix = seed.generatedName('vodfid');
const scenario = await upstream.scenario({
  xc: true,
  username: `${prefix}-user`,
  password: `${prefix}-pass`,
  vodCategories: [
    { id: 1, name: `${prefix}-movies-a` },
    { id: 2, name: `${prefix}-movies-b` },
  ],
  seriesCategories: [{ id: 1, name: `${prefix}-shows` }],
  vod: [
    { id: 101, name: `${prefix}-alpha`, year: 1999, categoryId: 1, containerExtension: 'mp4', tmdbId: null, imdbId: null },
    { id: 102, name: `${prefix}-beta`, year: 2011, categoryId: 2, containerExtension: 'mkv', tmdbId: null, imdbId: null },
  ],
  series: [
    { id: 201, name: `${prefix}-show`, categoryId: 1, seasons: [{ number: 1, episodes: [{ id: 301, title: `${prefix}-s1e1`, episodeNum: 1, containerExtension: 'mp4' }] }] },
  ],
});
const account = await seed.xcAccount(scenario, { enable_vod: true });
expect((await api.post(`/api/m3u/accounts/${account.id}/refresh-vod/`, {})).status()).toBe(202);
```

Every name is generated: `VODCategory` is unique on `(name, category_type)` **globally**, and `Movie`/`Series` are matched across accounts by `(name, year)` when no external id is present.

`test.setTimeout(150_000)` on the first line of each test — the account create alone blocks on two synchronous provider round-trips, and `seeded`'s project default is 30 s.

- [ ] **Step 2: Row 1 — the movie and series rows**

Wait, then assert. Scope by **both** `m3u_account` and the generated name:

```ts
const movies = await waitFor.resource<VodPage<Movie>>(
  `/api/vod/movies/?m3u_account=${account.id}&name=${encodeURIComponent(prefix)}`,
  (body) => body.count === 2,
  { description: `both ${prefix} movies to be ingested`, timeoutMs: 120_000 }
);
```

`MovieFilter.m3u_account` is `NumberFilter(field_name='m3u_relations__m3u_account__id')` and `name` is `CharFilter(lookup_expr='icontains')` (`apps/vod/api_views.py:53-65`), so this is a properly scoped count.

For each movie, assert against **what the provider actually declared**, which for G8's `movieEntry` renderer is:

| Field | Expected | Source |
|---|---|---|
| `name` | `${prefix}-alpha` / `${prefix}-beta` | declared |
| `year` | `1999` / `2011` | declared |
| `genre` | `'E2E'` | `movieEntry`'s fixed `genre` |
| `description` | `` `${name} — e2e fixture` `` | `movieEntry`'s `plot`; ingest reads `description` then `plot` |
| `rating` | `'7.5'` | `movieEntry`'s fixed `rating`, through `normalize_rating` |
| `duration_secs` | `5` | `movieEntry`'s `duration_secs` |
| `is_adult` | `false` | no `is_adult` key declared, and the model default is `False` |
| `custom_properties` | `null` | `movieEntry` emits **no** `director`/`actors`/`trailer`/`release_date`, so `process_movie_batch` builds `custom_props = {}` and stores `custom_props or None` |
| `logo` | `null` | `movieEntry` emits `stream_icon: ''`, and ingest does `logo_url = movie_data.get('stream_icon') or ''` |

**Do not assert `logo.url`,** which the spec's row 1 asks for. `MovieSpec` has no way to declare a `stream_icon`, so no `VODLogo` can be created. Assert `logo === null` instead, and Task 13 records "row-level `stream_icon` → `VODLogo` ingest is unreachable — `MovieSpec` declares no image URL" as a named `todo` gap naming the one-field provider change that would close it.

Then the relation, which is where "what the provider said" is preserved:

```ts
const relations = await api.json<M3uMovieRelation[]>(
  await api.get(`/api/vod/movies/${alpha.id}/providers/`),
  'movie providers'
);
const mine = relations.find((r) => r.m3u_account.id === account.id);
expect(mine).toBeDefined();
expect(mine!.stream_id).toBe('101');           // a CharField — a string, not 101
expect(mine!.container_extension).toBe('mp4');
expect(mine!.category?.name).toBe(`${prefix}-movies-a`);
const basic = mine!.custom_properties?.basic_data as Record<string, unknown>;
expect(basic.stream_id).toBe(101);              // the provider's own JSON — a number
expect(basic.container_extension).toBe('mp4');
expect(mine!.custom_properties?.detailed_fetched).toBe(false);
```

The `'101'` / `101` asymmetry is deliberate and worth the comment: `M3UMovieRelation.stream_id` is a `CharField`, while `basic_data` is the provider's untouched JSON entry.

Assert the second movie's `container_extension` is `'mkv'` and its category is `${prefix}-movies-b` — a single-movie assertion would not prove the category map is per-movie.

Then the series, the same way: `/api/vod/series/?m3u_account=${account.id}&name=${prefix}` for `count === 1`, then `/api/vod/series/${id}/providers/` for `external_series_id === '201'` and `category.name === ${prefix}-shows`. Note `process_series_batch` reads `cover`/`plot`/`releaseDate`, not the movie keys — so `description` is `` `${prefix}-show — e2e fixture` `` and `genre` is `'E2E'`.

- [ ] **Step 3: Row 2 — the category rows**

```ts
const categories = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'vod categories');
```

**Unpaginated and global.** Use `find` by the generated name, never a length and never an index. Assert:

- a `category_type: 'movie'` category named `${prefix}-movies-a` exists, and one named `${prefix}-movies-b`;
- a `category_type: 'series'` category named `${prefix}-shows` exists;
- each carries an `m3u_accounts` entry with `m3u_account === account.id` and `enabled === true` — `batch_create_categories` creates relations with `enabled = custom_properties['auto_enable_new_groups_vod']` / `_series`, both defaulting to `True` even though `M3UVODCategoryRelation.enabled` defaults to `False` on the model.

Do **not** assert anything about categories this test did not declare, and do **not** assert that this account lacks an `Uncategorized` relation — this very call creates one for every active XC account on the instance with `enable_vod`, including other workers'.

- [ ] **Step 4: Row 19 — pin defect 5**

```ts
// Asserts the behaviour Dispatcharr SHOULD have. VODCategoryFilter
// (apps/vod/api_views.py:624) declares
//   m3u_account = NumberFilter(field_name="m3u_account__id")
// but VODCategory has no `m3u_account` relation — the reverse accessor is
// `m3u_relations`. The filter is in Meta.fields too, so it imports cleanly
// and fails only at query time with
//   FieldError: Cannot resolve keyword 'm3u_account' into field. Choices are:
//   category_type, created_at, id, m3u_relations, m3umovierelation,
//   m3useriesrelation, name, updated_at
// MovieFilter and SeriesFilter get this right ("m3u_relations__m3u_account__id");
// only VODCategoryFilter does not. The frontend never passes the filter, which
// is why nothing has hit it.
//
// Issue: <fill in from Step 5 before committing>
test.fail('GET /api/vod/categories/ accepts an m3u_account filter', async ({ ... }) => {
```

Assert `res.status()` is `200` **and** that every returned category has an `m3u_accounts` entry for this account — a status-only assertion would go green on a fix that returned 200 with an unfiltered list.

This test still needs the account to exist, so it re-runs Step 1's seeding (or shares the local helper). It does **not** need `refresh-vod` to have completed — the filter raises before any row is read — but seeding it anyway makes the post-fix assertion meaningful.

- [ ] **Step 5: File the issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "VODCategoryFilter.m3u_account names a relation VODCategory does not have, so the filter is a 500" \
  --label needs-triage
```

Body: name `VODCategoryFilter` in `apps/vod/api_views.py`, quote the `FieldError` text, contrast with `MovieFilter`/`SeriesFilter`'s correct `m3u_relations__m3u_account__id`, and note that `Meta.fields` lists it too, which is why it imports cleanly. Put the number in the comment above the `test.fail()`.

- [ ] **Step 6: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded vod-ingest-fidelity
```

Expected: two passing tests and one reported as an **expected failure**. If the `test.fail()` passes, the defect has been fixed — remove `test.fail()`, close the issue, and say so.

If a row-1 assertion fails on `count: 0` rather than on a field, the refresh itself failed: `refresh_vod_content` swallows every exception into a log line and a return string (`apps/vod/tasks.py:52-128`), so a broken refresh is indistinguishable from an empty one at the API. Check `docker logs dispatcharr-e2e | grep -i 'refreshing vod\|Error refreshing VOD'` before suspecting an assertion.

- [ ] **Step 7: Commit**

`test(e2e): VOD catalogue ingest fidelity and the category-filter defect (G9 rows 1, 2, 19)`

---

### Task 5: Rows 3, 4 and 5 — category gating

Implements spec D9 and D10. Three tests, one file, no shared files.

**Files:**
- Create: `e2e/tests/seeded/vod-category-gating.spec.ts`

- [ ] **Step 1: Fallback check**

Read Task 1's outcome. If `MovieSpec.categoryId: number | null` did **not** land, row 5 keeps only its first half (the `Uncategorized` **relation**, which needs no special content) and drops the "declare a movie with `categoryId: null` and assert it lands in `Uncategorized`" half. Task 13 records the routing half as a named `todo` gap.

- [ ] **Step 2: Row 3 — gating on**

`test.setTimeout(180_000)`. The full arc, in one test:

1. Scenario: one generated VOD category, two generated movies in it.
2. `seed.xcAccount(scenario, { enable_vod: true, auto_enable_new_groups_vod: false })`. All three are write-only `BooleanField`s on `M3UAccountSerializer` that land in `custom_properties` and are echoed back by `to_representation` (`apps/m3u/serializers.py`), so they are settable at create and readable back.
3. `POST /api/m3u/accounts/<id>/refresh-vod/` → expect **202**.
4. Wait for the category to exist and be **disabled**, then assert zero movies:

```ts
// `waitFor.condition` resolves to void — it proves the predicate held, it
// does not hand back the body. `waitFor.resource<T>` is the one that
// returns the body, but it types the response as a single `T`, and this
// endpoint answers with a bare array. So: wait, then read.
await waitFor.condition(async () => {
  const all = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'categories');
  return all.some(
    (c) => c.name === categoryName && c.m3u_accounts.some((r) => r.m3u_account === account.id)
  );
}, { description: 'the gated category and its relation to exist' });

const all = await api.json<VodCategory[]>(await api.get('/api/vod/categories/'), 'categories');
const category = all.find((c) => c.name === categoryName)!;
const relation = category.m3u_accounts.find((r) => r.m3u_account === account.id)!;
expect(relation.enabled).toBe(false);
```

then assert `/api/vod/movies/?m3u_account=${account.id}&name=${prefix}` has `count === 0`.

**Assert the category's state alongside the zero.** A bare `count === 0` is exactly what a refresh that crashed also produces; the disabled relation is what makes "gated" and "broken" distinguishable in the failure message.

5. Enable it:

```ts
const res = await api.patch(`/api/m3u/accounts/${account.id}/group-settings/`, {
  category_settings: [{ id: category.id, enabled: true, custom_properties: {} }],
});
expect(res.status()).toBe(200);
```

**The key is `id`, not `category`** — rows without it are silently skipped (`M3UAccountViewSet.update_group_settings`, `apps/m3u/api_views.py:552-568`). And `custom_properties` must be supplied: the action reads raw `request.data` and issues a `bulk_create(update_conflicts=True, update_fields=['enabled', 'custom_properties'])`, so omitting it writes `{}`.

6. `refresh-vod` again; wait for `count === 2`.
7. `refresh-vod` a **third** time; wait for a settled state and assert the relation is **still** `enabled: true`. This is `bulk_create(..., ignore_conflicts=True)`'s "a manual enable is never re-disabled by a later refresh" property (`batch_create_categories`, `apps/vod/tasks.py:293-360`), and it is the half of the arc a naive implementation gets wrong.

Waiting on the third refresh needs a positive signal, not a sleep. Use `waitFor.condition` on "the two movies are still there **and** the relation is still enabled", with the count check as the thing that would change if the refresh had re-disabled and cleaned up. Give it `timeoutMs: 60_000` and a `description` that names both halves.

- [ ] **Step 3: Row 4 — gating off removes the content**

`test.setTimeout(180_000)`. Two generated categories, one generated movie each, account created with `enable_vod: true` (so both categories auto-enable). Refresh; wait for `count === 2`. Then `PATCH group-settings` with `category_settings: [{ id: <categoryA.id>, enabled: false, custom_properties: {} }]`; `refresh-vod`; wait for `count === 1` scoped to this account and prefix, and assert the survivor is movie B by name.

The mechanism being pinned is `cleanup_orphaned_vod_content(account_id, scan_start_time)` (`apps/vod/tasks.py:1735`): `process_movie_batch` skips movie A entirely (its relation is disabled, so `continue`), leaving A's `M3UMovieRelation.last_seen` older than this scan's start; cleanup deletes that relation, then deletes every **globally** orphaned `Movie`. Name that chain in a comment — a reader who does not know it will assume the disabled category is being filtered at read time, which is not what happens.

Also assert movie A is gone from the **unscoped-by-account but name-scoped** read `/api/vod/movies/?name=<movieAName>` with `count === 0`, which is what proves the `Movie` row itself was deleted rather than just the relation. This is safe under rule 4 because the name is generated.

- [ ] **Step 4: Row 5 — the `Uncategorized` fallback**

`test.setTimeout(150_000)`. Account created with `enable_vod: true, auto_enable_new_groups_vod: false, auto_enable_new_groups_series: false`; one generated category, one movie, one series. `refresh-vod`; wait for the refresh to have run (poll `/api/vod/categories/` for the generated category's relation).

Then assert:

- a `category_type: 'movie'` category named exactly `Uncategorized` exists and carries an `m3u_accounts` entry for this account with `enabled === false`;
- the same for `category_type: 'series'`.

`refresh_movies` and `refresh_series` `get_or_create` both the `Uncategorized` category **and** its relation on **every** refresh, with `enabled = auto_enable_new_groups_vod` / `_series` (`apps/vod/tasks.py:183-210`). Because the account was created with both flags false, `enabled: false` is a real assertion about the account's flags rather than a coincidence — and it is the reason this test sets them false rather than leaving the defaults.

Two hazards, both of which must appear as comments:

1. `GET /api/vod/categories/` itself `get_or_create`s these relations for every `enable_vod` account, with `defaults={'enabled': auto_enable_new}` — so this assertion holds whether the refresh or the listing created it, and the test must **not** claim the refresh created it.
2. **Never assert that an account lacks an `Uncategorized` relation.** Any other worker's category listing creates one.

**With the addendum**, add a second scenario movie declared `categoryId: null`, refresh, and assert it landed in `Uncategorized` — which requires the account's `auto_enable_new_groups_vod` to be **true** for that movie to survive `process_movie_batch`'s "skip if the Uncategorized relation is disabled" branch. Use a **separate account** for that half rather than flipping the flag mid-test, and read the movie's relation via `/api/vod/movies/<pk>/providers/` asserting `category.name === 'Uncategorized'`.

- [ ] **Step 5: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded vod-category-gating
```

Expected: three passing tests (no `test.fail()` in this file). Run it twice back to back against the same container — the third-refresh assertion in row 3 is exactly the kind that passes once and fails on a warm instance if it is secretly asserting creation rather than persistence.

- [ ] **Step 6: Commit**

`test(e2e): VOD category gating, both directions, and the Uncategorized fallback (G9 rows 3, 4, 5)`

---

### Task 6: Rows 6 and 7 — episode ingest on demand, both `episodes` shapes

**Files:**
- Create: `e2e/tests/seeded/vod-episodes.spec.ts`

- [ ] **Step 1: Fallback check**

Read Task 1's outcome. If `SeriesSpec.seasonsAsArray` did **not** land, row 7 keeps only its second half — one season declaring two entries with different provider ids and the same `episode_num` — and drops the array-shape half. Task 13 records "the array-keyed `episodes` shape (season 0) is undeclarable" as a named `todo` gap. Row 6 is unaffected either way.

- [ ] **Step 2: Row 6 — object-keyed `episodes`**

`test.setTimeout(150_000)`. Scenario: one generated series category, one generated series with **two** seasons:

```ts
series: [{
  id: 201,
  name: `${prefix}-show`,
  categoryId: 1,
  seasons: [
    { number: 1, episodes: [{ id: 301, title: `${prefix}-s1e1`, episodeNum: 1, containerExtension: 'mp4' }] },
    { number: 2, episodes: [{ id: 302, title: `${prefix}-s2e1`, episodeNum: 1, containerExtension: 'mkv' }] },
  ],
}],
vod: 0,
```

`seed.xcAccount(scenario, { enable_vod: true })`; `refresh-vod`; wait for `/api/vod/series/?m3u_account=<id>&name=<prefix>` to reach `count === 1`.

**Episodes are not part of the refresh.** `refresh_vod_content` makes exactly four provider calls — `get_vod_categories`, `get_series_categories`, `get_vod_streams`, `get_series` — and `get_series_info` is not among them. Episodes arrive only on demand:

```ts
const info = await api.json<SeriesInfo>(
  await api.get(`/api/vod/series/${series.id}/provider-info/`),
  'series provider-info'
);
```

This call is **synchronous**: `SeriesViewSet.series_info` (`apps/vod/api_views.py:399`) calls `refresh_series_episodes(account, series, relation.external_series_id)` inline, inside the HTTP request, forcing the fetch when `episodes_fetched` or `detailed_fetched` is unset. Assert on the response, not on a poll — and this is one of the two reasons this file needs its raised timeout.

Declare the response shape locally in the spec file (it is a hand-built dict, not a serializer, so it does not belong in `fixtures/types.ts`):

```ts
type SeriesInfoEpisode = {
  id: number; uuid: string; name: string; title: string;
  episode_number: number | null; season_number: number | null;
  container_extension: string;
};
type SeriesInfo = {
  id: number; series_id: string; name: string;
  episodes_fetched: boolean; detailed_fetched: boolean;
  episodes: Record<string, SeriesInfoEpisode[]>;
};
```

Assert:

- `info.episodes_fetched === true` and `info.detailed_fetched === true`;
- `Object.keys(info.episodes).sort()` is `['1', '2']` — **string** keys, built as `String(episode.season_number ?? 0)`;
- `info.episodes['1'][0]` has `title === `${prefix}-s1e1``, `episode_number === 1`, `season_number === 1`, `container_extension === 'mp4'`;
- `info.episodes['2'][0]` has `container_extension === 'mkv'` — proving the per-episode extension survives, not just the season grouping.

Then cross-check through the collection endpoint: `GET /api/vod/episodes/?series=${series.id}` (`EpisodeFilter.series` is `NumberFilter(field_name='series__id')`) and assert `count === 2` and the two `(season_number, episode_number)` pairs. This is the second, independent read of the same rows — the `provider-info` response is assembled by hand and could agree with itself while the rows are wrong.

- [ ] **Step 3: Row 7 — array-keyed seasons, and two streams for one episode**

`test.setTimeout(150_000)`. One series declared with `seasonsAsArray: true` and:

```ts
seasons: [
  { number: 0, episodes: [{ id: 401, title: `${prefix}-s0e1`, episodeNum: 1, containerExtension: 'mp4' }] },
  { number: 1, episodes: [
      { id: 402, title: `${prefix}-s1e1-a`, episodeNum: 1, containerExtension: 'mp4' },
      { id: 403, title: `${prefix}-s1e1-b`, episodeNum: 1, containerExtension: 'mkv' },
  ] },
],
```

The door requires `seasons[i].number === i` under `seasonsAsArray`, which both satisfy. Episode ids are unique **across the whole scenario**, not per series — the provider's door enforces that, because `M3UEpisodeRelation.unique_together` is `('m3u_account', 'stream_id')`.

`refresh-vod`, wait for the series, then `GET /api/vod/series/<pk>/provider-info/`.

Assert:

- `Object.keys(info.episodes)` contains `'0'` — **season 0 is real under the array shape**. `batch_process_episodes` (`apps/vod/tasks.py:1387-1425`) accepts a dict *or* a list and uses the key **or the index** as the season number; index 0 is what makes season 0 reachable at all.
- Season 1 has exactly **one** episode, not two. `Episode.unique_together` is `('series', 'season_number', 'episode_number')`, so two provider streams with the same `episode_num` collapse to one `Episode`.
- That one episode has **two** `M3UEpisodeRelation` rows. The endpoint for this is `GET /api/vod/series/<pk>/episodes/` — `SeriesViewSet.get_episodes` (`apps/vod/api_views.py:374`), which returns a **plain unpaginated array** of `EpisodeSerializer` payloads each carrying an extra `providers` key holding that episode's `M3UEpisodeRelationSerializer` rows. Note this is *not* `EpisodeViewSet`: that viewset declares only an `image` action and has no `providers` route, and `/api/vod/series/<pk>/provider-info/`'s per-episode `container_extension` resolves from a dict keyed by `episode_id`, so it collapses the two relations and cannot prove they exist.

```ts
type EpisodeWithProviders = Episode & { providers: M3uEpisodeRelation[] };
const withProviders = await api.json<EpisodeWithProviders[]>(
  await api.get(`/api/vod/series/${series.id}/episodes/`), 'series episodes with providers'
);
const s1e1 = withProviders.find((e) => e.season_number === 1 && e.episode_number === 1)!;
expect(s1e1.providers.map((r) => r.stream_id).sort()).toEqual(['402', '403']);
```

`stream_id` is a `CharField`, so these are strings. Assert the two ids, not just `providers.length === 2` — the length alone would pass on two relations pointing at the wrong streams.

Two streams for one episode is normal provider behaviour (different languages or qualities), not a duplicate — say so in a comment, because the natural reading of "two ids, one row" is a bug.

- [ ] **Step 4: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded vod-episodes
```

Expected: two passing tests. A `500` from `provider-info` means the synchronous `get_series_info` call failed; `SeriesViewSet.series_info` wraps its whole body in a `try` that returns `{'error': …}` with status 500, so read the body before suspecting the assertions.

- [ ] **Step 5: Commit**

`test(e2e): on-demand episode ingest in both provider shapes (G9 rows 6, 7)`

---

### Task 7: Row 8 — advanced movie data, the 24-hour throttle, and list-sync survival

**Files:**
- Create: `e2e/tests/seeded/vod-advanced-data.spec.ts`

- [ ] **Step 1: Seed and ingest**

`test.setTimeout(180_000)`. One generated VOD category, one generated movie (`id: 501`, an explicit `year`), `series: 0`. `seed.xcAccount(scenario, { enable_vod: true })`, `refresh-vod`, wait for `count === 1`.

Read the relation first and record the baseline:

```ts
const before = (await api.json<M3uMovieRelation[]>(
  await api.get(`/api/vod/movies/${movie.id}/providers/`), 'relation before'
)).find((r) => r.m3u_account.id === account.id)!;
expect(before.custom_properties?.detailed_fetched).toBe(false);
expect(before.last_advanced_refresh).toBeNull();
```

`process_movie_batch` sets `detailed_fetched: False` at create and stores the whole `get_vod_streams` entry as `custom_properties.basic_data`.

- [ ] **Step 2: Drive the advanced fetch**

```ts
const info = await api.json<Record<string, unknown>>(
  await api.get(`/api/vod/movies/${movie.id}/provider-info/`), 'movie provider-info'
);
```

`MovieViewSet.provider_info` (`apps/vod/api_views.py:132`) calls `refresh_movie_advanced_data(relation.id, force_refresh=…)` **synchronously** when `needs_refresh`, then re-reads both objects from the database. So the response already reflects the fetch.

Assert on the response: `info.director === 'E2E Director'` and `info.actors === 'E2E Actor'` (G8's `renderVodInfo` defaults), and `info.container_extension === 'mp4'` (which comes from the relation's stored `movie_data`, not from `info` — proving both halves of the payload landed).

Then re-read the relation and assert the storage side:

```ts
expect(after.custom_properties?.detailed_fetched).toBe(true);
expect(after.custom_properties?.detailed_info).toBeTruthy();
expect(after.custom_properties?.movie_data).toBeTruthy();
expect(after.last_advanced_refresh).not.toBeNull();
```

`refresh_movie_advanced_data` (`apps/vod/tasks.py:2198`) requires `'info' in vod_info`, reads `movie_data` separately, tolerates either being a list, and stores `detailed_info`/`movie_data` on the **relation** with `detailed_fetched: True` and `last_advanced_refresh = now`.

- [ ] **Step 3: The 24-hour throttle**

Call `GET /api/vod/movies/<pk>/provider-info/` a second time, re-read the relation, and assert `last_advanced_refresh` is **unchanged** — byte-identical to the value from Step 2. `provider_info` recomputes `needs_refresh` as `force_refresh or not detailed_fetched or not last_advanced_refresh or (now - last_advanced_refresh) > 86400s`, and none of those holds a second later, so the task is never called.

Then call `GET /api/vod/movies/<pk>/provider-info/?force_refresh=true`, re-read, and assert `last_advanced_refresh` **moved** (`new > old` as `Date` values). `?force_refresh=true` is compared as `request.query_params.get('force_refresh', 'false').lower() == 'true'`, so the literal string matters — `?force_refresh=1` does nothing.

A timestamp comparison needs both values parsed: `new Date(after.last_advanced_refresh!).getTime()`. Do not compare the ISO strings with `>`.

- [ ] **Step 4: The merge survives a list sync**

`POST refresh-vod` again, wait for the refresh to settle, then re-read the relation and assert `custom_properties.detailed_info` and `custom_properties.movie_data` are **still there**, and that `basic_data` is present too. `process_movie_batch` merges `basic_data` into the existing `custom_properties` rather than replacing the dict — that is the property row 8 exists to pin, and the one a refactor of the merge would break silently.

Waiting for "the refresh settled" here has no count change to hang on, since the movie is already present. Use `waitFor.condition` polling the relation's `last_seen` and asserting it advanced past the value read before the refresh — `cleanup_orphaned_vod_content` keys on exactly that field, so it is both the honest signal and the one the product itself relies on.

- [ ] **Step 5: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded vod-advanced-data
```

Expected: one passing test.

- [ ] **Step 6: Commit**

`test(e2e): advanced movie data, its throttle, and list-sync survival (G9 row 8)`

---

### Task 8: Rows 9, 10 and 20 — the XC VOD and series actions against a real catalogue

G5 proved these six paths do not error on an **empty** catalogue. This task is the fidelity half. Everything here is driven through Playwright's built-in `request` context with `xcQuery(user)` — never `api`.

**Files:**
- Create: `e2e/tests/seeded/xc-vod-catalogue.spec.ts`

- [ ] **Step 1: Fallback check**

Read Task 1's outcome.

- No `MovieSpec.isAdult` → drop row 10's second half (the `hide_adult_content` positive control). Row 10's series assertions stand.
- No `MovieSpec.vodInfo` → **row 20 becomes unverifiable at this layer.** Do not write a weaker version of it. Still **file the defect-2 issue** (Step 5) with a note in the body that no E2E test pins it and why, and Task 13 records it as a `known-bug` row with `todo` status and that reason.

- [ ] **Step 2: Row 9 — the VOD actions**

`test.setTimeout(150_000)`. Seed as in Task 4: two generated VOD categories, two movies (one in each), one series category, one series with one episode. `seed.xcAccount(scenario, { enable_vod: true })`, `refresh-vod`, wait for `count === 2`.

Create the client identity with `seed.xcUser()` (or G8's local `seedXcUser` if Task 3 Step 1 took that branch — but that helper defaults `user_level: 10`, so pass `user_level: 1` explicitly here; row 10 depends on the user being a non-admin).

Then, with `request`:

```ts
const listed = JSON.parse(
  await (await request.get(`/player_api.php${xcQuery(user, { action: 'get_vod_categories' })}`)).text()
) as { category_id: string; category_name: string }[];
```

Assert:

1. `get_vod_categories` **contains** an entry with `category_name === `${prefix}-movies-a`` whose `category_id === String(movieCategoryA.id)` — the **Dispatcharr** `VODCategory` primary key, emitted as a string. Locate with `find`; the list is every VOD category on the instance.
   Note: `xc_get_vod_categories` filters `m3umovierelation__m3u_account__is_active=True`, so a category with no ingested movie does not appear. Both of this test's categories have one.
2. `get_vod_streams` contains both movies, each with:
   - `stream_id === movie.id` — **`Movie.pk`, a number, not the provider's `stream_id`.** This is the assertion that catches a passing-for-the-wrong-reason test: the provider declared `101`/`102` and Dispatcharr emits its own ids.
   - `stream_type === 'movie'`
   - `container_extension` equal to what the scenario declared (`'mp4'` / `'mkv'`)
   - `year` equal to the declared year
   - `category_id === String(<that movie's VODCategory pk>)`
3. `get_vod_streams&category_id=<movieCategoryA.id>` narrows to exactly one of the two — assert the other movie's `stream_id` is **absent**, not just that the first is present.
4. `get_vod_info&vod_id=<alpha.id>` answers 200 with an `info` object and a `movie_data` object, `movie_data.stream_id === alpha.id` and `movie_data.container_extension === 'mp4'`.

The round trip closes: the id `get_vod_streams` emits is the id `get_vod_info` takes (`xc_get_vod_info` filters `movie_id=vod_id`).

- [ ] **Step 3: Row 10 — the series actions, and adult filtering on the listing**

Same file, second test, `test.setTimeout(180_000)`.

Series half:

- `get_series` contains this test's series with **`series_id === M3USeriesRelation.pk`** — *not* `Series.pk`. `xc_get_series` emits `row['id']`, the relation's own primary key, while `xc_get_vod_streams` emits `row['movie__id']`, the content's. **Assert both halves of that asymmetry explicitly** (i.e. assert `series_id !== series.id` as well as `series_id === relation.id`, unless they happen to collide — read the relation id from `/api/vod/series/<pk>/providers/` and assert equality against it). The asymmetry is exactly the kind of thing a refactor unifies and breaks.
- `get_series_info&series_id=<that relation id>` answers 200 with `episodes` grouped by season, each episode's `id` equal to the **`Episode` primary key**. This call is synchronous on the product side too (`xc_get_series_info` calls `refresh_series_episodes` inline), which is the second reason for the raised timeout.

Adult half (**requires `MovieSpec.isAdult`**):

- Declare a third movie with `isAdult: true` in the same scenario, alongside a non-adult control.
- Create a **second** XC user: `seed.xcUser({ user_level: 1, custom_properties: { hide_adult_content: true } })`. `user_level` must be below 10 — `xc_get_vod_streams` applies the filter only when `user.user_level < 10 and custom_properties.hide_adult_content`.
- Assert the adult movie's `stream_id` is **absent** from that user's `get_vod_streams`, while the non-adult one is **present** — the positive control matters as much as the absence, because an empty list would satisfy the absence alone.
- Assert `get_vod_info&vod_id=<adult movie pk>` for that user answers **404**. `xc_get_vod_info` adds `movie__is_adult=False` to its filters and raises `Http404` when nothing matches; there is no custom `handler404` in `dispatcharr/urls.py`, so the client sees Django's 404.
- Assert the **first** user (no `hide_adult_content`) still sees the adult movie in `get_vod_streams` — otherwise the absence above could be an ingest failure.

This is the positive control for row 16, which asserts the same movie is nonetheless *streamable*.

- [ ] **Step 4: Row 20 — pin defect 2 (requires `MovieSpec.vodInfo`)**

Declare a movie whose advanced payload carries `bitrate`/`video`/`audio` and **none** of `director`/`actors`/`youtube_trailer`/`backdrop_path`:

```ts
{
  id: 601,
  name: `${prefix}-sparse`,
  year: 2005,
  categoryId: 1,
  containerExtension: 'mp4',
  tmdbId: null,
  imdbId: null,
  vodInfo: {
    plot: `${prefix}-sparse — detailed plot`,
    genre: 'E2E',
    rating: '7.5',
    duration_secs: 5,
    bitrate: 4321,
    video: { codec_name: 'h264', width: 320, height: 180 },
    audio: { codec_name: 'aac' },
  },
}
```

Why this shape works, and why it must not be "simplified": `movieEntry` emits no `director`/`actors`/`trailer`/`release_date`, so ingest leaves `Movie.custom_properties` at `None` (`custom_props or None`). `refresh_movie_advanced_data` then reads this `info`: it may set `movie.description`/`genre`/`rating`/`year` from it, but the only keys it ever writes into `custom_props` are `youtube_trailer`, `backdrop_path`, `actors` and `director` — none of which this payload has — so `clean_custom_properties({})` returns `None` and `Movie.custom_properties` stays null. **Adding a `director` to this literal silently disarms the test.**

Then:

```ts
// Asserts the behaviour Dispatcharr SHOULD have. `xc_get_vod_info`
// (apps/output/views.py:1675) gates the whole detailed_info merge on
//     if movie.custom_properties:
// and then, one line later (:1680), reads the data off the *relation*:
//     detailed_info = movie_relation.custom_properties.get('detailed_info', {})
// — the wrong object's truthiness. The commented-out :1679 shows the source
// that was intended. A movie whose provider payload carries none of
// trailer/director/actors/backdrop has Movie.custom_properties = None
// (clean_custom_properties({}) returns None, apps/vod/tasks.py:2132), so
// bitrate, video, audio, cover_big and the plot override never reach an XC
// client even though refresh_movie_advanced_data just fetched and stored
// them on the relation. /api/vod/movies/<pk>/provider-info/ reads the same
// relation and returns them correctly, which is what makes the two
// disagree.
//
// Issue: <fill in from Step 5 before committing>
test.fail('XC get_vod_info returns the advanced data the REST API returns', async ({ ... }) => {
```

Drive `/api/vod/movies/<pk>/provider-info/` (which returns `bitrate: 4321`, `video`, `audio`) and XC `get_vod_info&vod_id=<pk>` (which returns `bitrate: 0`, `video: {}`, `audio: {}`), and assert **they agree**:

```ts
expect(xcInfo.info.bitrate).toBe(restInfo.bitrate);
expect(xcInfo.info.video).toEqual(restInfo.video);
expect(xcInfo.info.audio).toEqual(restInfo.audio);
```

Guard the premise first — `expect(restInfo.bitrate).toBe(4321)` — so a failure caused by the advanced fetch never happening is distinguishable from the defect. Order matters: if the premise assertion is the one that fails, the `test.fail()` still reports "expected failure" and tells you nothing. Put the premise in a `expect(...).toBe(4321)` immediately preceded by a comment saying that a failure *there* means the fixture is wrong, not the product.

- [ ] **Step 5: File the defect-2 issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "xc_get_vod_info gates the detailed_info merge on Movie.custom_properties while reading the relation's" \
  --label needs-triage
```

Body: name `xc_get_vod_info` in `apps/output/views.py`, quote lines 1675–1680 including the commented-out 1679, explain that `clean_custom_properties({})` returns `None` so a sparse provider leaves `Movie.custom_properties` null, and contrast with `MovieViewSet.provider_info`, which reads the same relation and returns the data correctly. Put the number in the comment.

- [ ] **Step 6: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=seeded xc-vod-catalogue
```

Expected: two passing tests and one expected failure (or two passing tests and no `test.fail()`, if `vodInfo` was declined).

- [ ] **Step 7: Commit**

`test(e2e): XC VOD and series actions against a real catalogue (G9 rows 9, 10, 20)`

---

### Task 9: Rows 11, 12 and 14 — the playback entry points

Two files, one task: both are "a VOD URL delivers the asset's bytes", differing only in which route resolves the content. Both go in `streaming` (2 workers, 300 s, fake provider available).

G8's `e2e/tests/streaming/vod-byte-read.spec.ts` already proves `/proxy/vod/movie/<uuid>` answers 200 with `Accept-Ranges`, a `Content-Length` matching the body, an `ftyp` box, and a `bytes=100-199` slice. **Do not restate any of that.** What is new here is the 301 mint, the `Content-Type`, the provider-log correlation, and the episode/series entry points.

**Files:**
- Create: `e2e/tests/streaming/vod-stream.spec.ts`
- Create: `e2e/tests/streaming/xc-vod-playback.spec.ts`

- [ ] **Step 1: A shared local setup**

Both files need "an XC account with one movie and one series, ingested, with episodes fetched". Write it once per file as a local `async function seedVodContent(...)`; do **not** promote it into `e2e/fixtures/` or into `e2e/tests/streaming/helpers.ts`, which G8 specs already import and which G10 may be editing.

The setup is Task 4's Step 1 plus, for the series, one `GET /api/vod/series/<pk>/provider-info/` to force episode ingest (episodes are never created by `refresh-vod`).

- [ ] **Step 2: Row 11 — session mint, redirect, and byte delivery**

`test.setTimeout(180_000)`.

```ts
await streamClient.open(`/proxy/vod/movie/${movie.uuid}`, { redirect: 'manual' });
expect(streamClient.status).toBe(301);
const location = streamClient.headers!.get('location')!;
expect(location).toMatch(/\/vod_\d+_\d+$/);
```

**301, not 302.** With no `session_id` and the global default Stream Profile *not* Redirect, `stream_vod` mints `vod_{int(time*1000)}_{randint(1000,9999)}` and returns a **hand-built** `HttpResponse(status=301, headers={'Location': …})` via `_vod_session_path_redirect` (`apps/proxy/vod_proxy/views.py:102-142`). The `Location` is a **relative** path with `session_id` and `token` stripped from the query. The 302 case is `HttpResponseRedirect` straight at the provider and belongs to row 21; the status alone distinguishes them, which is why this assertion is worth its line.

Then re-open following redirects and read the body with `request.get` (finite asset, so `APIResponse.body()` resolves):

```ts
const res = await request.get(`/proxy/vod/movie/${movie.uuid}`);
expect(res.status()).toBe(200);
const headers = res.headers();
expect(headers['accept-ranges']).toBe('bytes');
expect(headers['content-type']).toBe('video/mp4');
```

`Content-Type` comes from the provider's header (`loadFiniteAsset(path, 'video/mp4')` in `e2e-upstream/src/server.ts`), else is inferred from the URL extension, else defaults to `video/mp4`. Assert the value, not just its presence.

Compare the first bytes against the provider directly:

```ts
const direct = await fetch(
  upstream.toControl(`${scenario.internal}/movie/${scenario.username}/${scenario.password}/501.mp4`)
);
const assetBytes = Buffer.from(await direct.arrayBuffer());
const served = await res.body();
expect(served.byteLength).toBe(Number(headers['content-length']));
expect(served.subarray(0, 1024)).toEqual(assetBytes.subarray(0, 1024));
```

`toControl` rewrites the container-internal origin to one this process can reach and **throws** on any URL outside that origin, which is what stops a test making a real outbound request.

Finally, correlate with the provider log:

```ts
const log = await upstream.log(scenario);
const movieRequests = log.filter((e) => e.kind === 'request' && e.path?.includes(`/movie/`) && e.path?.includes('501.'));
expect(movieRequests.length).toBeGreaterThan(0);
expect(movieRequests.every((e) => e.status === 200 || e.status === 206)).toBe(true);
```

Do **not** assert `movieRequests.length === 1`: the direct `fetch` above also lands in this log, and the session may reconnect. Assert the id and the statuses, not the count.

- [ ] **Step 3: Row 12 — episode and series entry points**

Same file, second test, `test.setTimeout(180_000)`.

- `GET /proxy/vod/episode/<Episode.uuid>` → 200, body byte-identical to the asset (compare against the provider through `toControl`, as above, using the `/series/<u>/<p>/<episodeStreamId>.<ext>` route).
- `GET /proxy/vod/series/<Series.uuid>` → 200, and the body is the **same** bytes. `stream_vod`'s `series` content type resolves to the first episode by `(season_number, episode_number)` ordering.

Declare the series with **two** episodes in season 1 (`episodeNum` 1 and 2) so "the first episode" is a real claim rather than the only option, and assert through the provider log that the request Dispatcharr made carried the **first** episode's declared stream id and not the second's.

`/proxy/vod/` routes only `stream_vod` (four patterns), `vod_stats` and `stop_vod_client` (`apps/proxy/vod_proxy/urls.py`). `head_vod` is **not routed** — do not add a HEAD assertion.

- [ ] **Step 4: Row 14 — the root XC playback routes**

New file `e2e/tests/streaming/xc-vod-playback.spec.ts`, `test.setTimeout(180_000)`.

The routes are mounted at the **site root**, before the SPA catch-all (`dispatcharr/urls.py:57-64`):

```
movie/<username>/<password>/<stream_id>.<extension>   → stream_xc_movie
series/<username>/<password>/<stream_id>.<extension>  → stream_xc_episode
```

`<stream_id>` is the **Dispatcharr** primary key — `Movie.pk` for the movie route, `Episode.pk` for the series route — not the provider's. Credentials are the Django username and `User.custom_properties['xc_password']`, same model as G5's live `stream_xc`.

First test, passing:

1. `GET /movie/<user>/<xcPassword>/<Movie.pk>.mp4` → 200, body byte-identical to the asset.
2. Wrong password → **401**. `stream_xc_movie` returns `{"error": "Invalid credentials"}` with 401 on mismatch, and also on the absence of `xc_password` entirely.
3. Unknown username → **404**, from `get_object_or_404(User, username=…)`.
4. Unknown movie id → **404**: `M3UMovieRelation.objects.filter(...).first()` returns `None` and the view returns `JsonResponse({"error": "Movie not found"}, status=404)`.
5. `GET /series/<user>/<xcPassword>/<Episode.pk>.mp4` → 200, same bytes.

Use `request.get()` throughout — `streamClient.open()` throws on a non-2xx and these rows are mostly about non-2xx statuses.

Second test, `test.fail()`:

```ts
// Asserts the behaviour Dispatcharr SHOULD have. `stream_xc_episode`
// (apps/proxy/vod_proxy/views.py:1449-1454) wraps its lookup in
//     try: episode_relation = M3UEpisodeRelation.objects.filter(...).first()
//     except M3UEpisodeRelation.DoesNotExist: return 404
// but `.first()` returns None and never raises DoesNotExist, so the guard
// is dead: the next line dereferences `episode_relation.episode`, raising
// AttributeError, and the client gets a 500. `stream_xc_movie`, four
// functions above, does the same lookup and correctly checks `if not
// movie_relation` before returning 404. One guard clause closes it, and
// this test goes green when it lands.
//
// Issue: <fill in from Step 5 before committing>
test.fail('an unknown episode id on the XC series route is a 404, not a 500', ...)
```

Assert `res.status()` is `404`. Pick an episode id that certainly does not exist — `Number.MAX_SAFE_INTEGER` is not safe (the column is a 32-bit integer and an out-of-range value can raise a different error); use `<highest real Episode.pk> + 1_000_000`, read from a `GET /api/vod/episodes/?ordering=-id&page_size=1` — or simply an id this test created and then... no: do not delete rows. Read the max id and add a margin, and say in a comment why a fixed literal would be wrong.

**This is a deliberate, stated departure from the spec.** The spec folds this defect "into row 14's assertions rather than given its own `test.fail()`", while also saying "row 14 will go green on [the fix]" — which can only be true if row 14 fails today. A passing row cannot contain an assertion the product fails. Splitting it keeps row 14 green and still pins the defect, at the cost of a seventh `test.fail()` in the goal. Record the departure in the task report.

- [ ] **Step 5: File the episode-404 issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "stream_xc_episode's DoesNotExist guard is dead after .first(), so an unknown episode id is a 500" \
  --label needs-triage
```

Body: name `stream_xc_episode` in `apps/proxy/vod_proxy/views.py`, quote the `try`/`except` and the following dereference, and contrast with `stream_xc_movie`'s correct `if not movie_relation` check in the same file.

- [ ] **Step 6: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming vod-stream xc-vod-playback
```

Expected: three passing tests and one expected failure.

- [ ] **Step 7: Commit**

`test(e2e): VOD playback entry points and the root XC routes (G9 rows 11, 12, 14)`

---

### Task 10: Rows 13, 17, 18 and the suffix-range pin

Four tests in one file: one passing seek proof and three defect pins. Two of the three issues **already exist** — do not file them again.

**Files:**
- Create: `e2e/tests/streaming/vod-range.spec.ts`

- [ ] **Step 1: Row 13 — Range and seek, proved against the provider**

`test.setTimeout(180_000)`. Seed one movie as in Task 9 Step 1.

Establish a session with one **full** request first. This is not ceremony: `RedisVODConnection.get_stream` learns `state.content_length` only when `request_count == 1` (`multi_worker_connection_manager.py:513-531`), and every Range assertion below depends on it being known.

```ts
const full = await request.get(`/proxy/vod/movie/${movie.uuid}`);
expect(full.status()).toBe(200);
const total = Number(full.headers()['content-length']);
```

Then a mid-file range at an offset well past the head G8's proof already covered:

```ts
const start = 40_000;
const end = start + 8_191;
const partial = await request.get(`/proxy/vod/movie/${movie.uuid}`, {
  headers: { Range: `bytes=${start}-${end}` },
});
expect(partial.status()).toBe(206);
expect(partial.headers()['content-range']).toBe(`bytes ${start}-${end}/${total}`);
expect(partial.headers()['content-length']).toBe('8192');
```

**Guard the offset against the asset's real size first** — `expect(total).toBeGreaterThan(end + 1)`. The asset is generated at Docker build time from unpinned ffmpeg (`e2e-upstream/scripts/make-vod-asset.sh` asserts only "at least 1 KB and starts with an `ftyp` box"), so its length is a runtime fact, not a constant. If the guard fails, derive `start` as `Math.floor(total / 3)` instead of hardcoding. Do not hardcode a byte count anywhere in this file.

Then the differential comparison — the part that makes this more than an internal-consistency check (spec D8):

```ts
const direct = await fetch(
  upstream.toControl(`${scenario.internal}/movie/${scenario.username}/${scenario.password}/501.mp4`),
  { headers: { Range: `bytes=${start}-${end}` } }
);
expect(direct.status).toBe(206);
const expected = Buffer.from(await direct.arrayBuffer());
expect(await partial.body()).toEqual(expected);
```

That proves Dispatcharr returned **the requested bytes**, not merely 8 192 bytes with plausible headers — which is exactly what defect 6 does. Comparing against `full.body().subarray(start, end + 1)` would also work but is weaker: it cannot tell a correct proxy from one that slices the file itself.

Finally, the open-ended range:

```ts
const open = await request.get(`/proxy/vod/movie/${movie.uuid}`, {
  headers: { Range: `bytes=${start}-` },
});
expect(open.status()).toBe(206);
expect(open.headers()['content-range']).toBe(`bytes ${start}-${total - 1}/${total}`);
```

`_validate_range_header` rewrites an empty `end_str` to `content_length - 1`, and `stream_content_with_session` builds `Content-Range` from the client's requested range and the stored full size.

- [ ] **Step 2: Row 17 — pin defect 3**

```ts
// Asserts the behaviour Dispatcharr SHOULD have. On a session's FIRST
// request, `state.content_length` is unset — `get_stream`
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:467) only
// validates a Range when it already knows the size, and it only learns the
// size at `request_count == 1` (:513). So an unsatisfiable Range on a fresh
// session is passed to the provider verbatim; the provider's 416 then hits
// `response.raise_for_status()` (:509) and becomes
// `HttpResponse("Streaming error: ...", status=500)` (:1405). The SAME
// request on an established session returns a correct 416
// ("Requested Range Not Satisfiable", :1114), which the control assertion
// below proves.
//
// Issue: <fill in from Step 3 before committing>
test.fail('an unsatisfiable Range on a fresh session is 416, not 500', ...)
```

Use a **fresh** movie (its own scenario and account, or at minimum a `Movie.uuid` no earlier test in this file has opened) so the session really is new. Then:

```ts
const res = await request.get(`/proxy/vod/movie/${movie.uuid}`, {
  headers: { Range: `bytes=99999999-` },
});
expect(res.status()).toBe(416);
```

Add the **control** in the same test, before the `test.fail()` assertion is reached is not possible — a `test.fail()` test that passes its control and fails its subject is still reported as an expected failure, which is what we want. So: first establish a session with a full request on a *second* movie, then send the same unsatisfiable Range to it and assert **416** as a plain `expect`. That control is what distinguishes "Dispatcharr never answers 416" (a bigger claim, and false) from "Dispatcharr answers 416 only once it knows the size" (the actual defect). Put the control first; if it fails, the failure message says so before the subject is touched.

Note `COVERAGE.md`'s existing G8 row warns "G9 should not write an assertion expecting a 416 to surface end to end until this is fixed". That warning is about a *passing* assertion. A `test.fail()` asserting 416 is the correct way to pin it, and Task 13 amends that row to say so.

- [ ] **Step 3: File the defect-3 issue**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "An unsatisfiable Range on a VOD session's first request is a 500, not a 416" \
  --label needs-triage
```

Body: name `get_stream` and `_validate_range_header` in `apps/proxy/vod_proxy/multi_worker_connection_manager.py`, explain the `request_count == 1` ordering, and note that the same request on an established session correctly returns 416 at `:1114`. Mention that the 500 body additionally carries the provider URL, **without quoting it** — that is the subject of the unfiled security finding, and this issue should not become its disclosure. One sentence: "the 500's body is `f'Streaming error: {e}'`, which is a separate concern tracked out of band."

- [ ] **Step 4: Row 18 — pin defect 6 (already filed as #66)**

```ts
// Asserts the behaviour Dispatcharr SHOULD have. With `range-unsupported`
// armed, the provider ignores Range and answers 200 with the whole asset
// from offset zero. `stream_content_with_session`
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:1303) then sets
// `status_code = 206 if range_header else 200` regardless of what the
// upstream actually answered, and :1312-1377 fabricates Content-Range and a
// shortened Content-Length purely from the client's requested range and the
// previously-known full size. `stream_generator()` (:1152) is a pure
// passthrough with no offset skipping. So the client gets the HEAD of the
// file under headers describing the slice it asked for — internally
// consistent, spec-shaped, and silently wrong.
//
// Filed as https://github.com/D10Scot/Dispatcharr/issues/66. Do not file a
// second issue for this.
test.fail('a provider that ignores Range still yields the requested bytes', ...)
```

Sequence: seed a fresh movie; establish the session with a full request (so `content_length` is known and `Content-Range` can be fabricated at all); read the asset directly from the provider through `toControl` **before arming the fault**; arm `range-unsupported` scenario-wide (`upstream.fault(scenario, 'range-unsupported')` — a `channel` is rejected with 400, since a VOD id is not a channel id); request the mid-file range; assert the **bytes** equal that range of the asset.

Assert the bytes, not the length and not the headers. `COVERAGE.md`'s G8 row records the measured symptom precisely: with a 125,585-byte asset and `Range: bytes=100-199`, the 100-byte body was byte-identical to bytes **0–99** while the response claimed `Content-Range: bytes 100-199/125585`. A length-only assertion passes today.

Clear the fault in a `finally` — `range-unsupported` is scenario-scoped and the scenario outlives the test, but leaving it armed makes the next test in the file read the wrong thing if the file is ever reordered.

- [ ] **Step 5: The suffix-range pin (already filed as #64)**

`COVERAGE.md` assigns this to G9 and the issue exists.

```ts
// Asserts the behaviour Dispatcharr SHOULD have. RFC 9110's `bytes=-500`
// means "the last 500 bytes". `_validate_range_header`
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:580-612) splits
// on the first '-' and treats an empty start_str as `start_byte = 0`, then
// rewrites the header to `bytes=0-500` — the client asking for the tail of a
// file is served the head, with a 206 and a Content-Range describing the
// wrong slice, and no error anywhere. The provider's own `parseRange`
// (e2e-upstream/src/vod-asset.ts) implements the suffix form correctly, so
// the upstream is not the source of this.
//
// Filed as https://github.com/D10Scot/Dispatcharr/issues/64. Do not file a
// second issue for this.
test.fail('a suffix Range returns the tail of the file', ...)
```

Establish a session with a full request (the rewrite happens in `_validate_range_header`, which only runs once `content_length` is known — on a fresh session the suffix header would reach the provider unmodified and *succeed*, which would make the test pass for the wrong reason). Then `Range: bytes=-500`, and assert the 500 bytes equal `assetBytes.subarray(total - 500)`.

- [ ] **Step 6: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming vod-range
```

Expected: one passing test and three expected failures. Confirm each `test.fail()` fails on its **subject** assertion and not on its control or its premise — Playwright reports both the same way, so read the attached error.

- [ ] **Step 7: Commit**

`test(e2e): VOD Range and seek, and three range defects (G9 rows 13, 17, 18 + #64)`

---

### Task 11: Rows 15 and 16 — the two security-adjacent pins

Both are `test.fail()`s in `streaming`. **They differ in one crucial way: row 15 files no issue.**

**Files:**
- Create: `e2e/tests/streaming/vod-upstream-error.spec.ts`
- Create: `e2e/tests/streaming/vod-adult-streamable.spec.ts`

- [ ] **Step 1: Read this before writing row 15**

The spec's **defect 1** is a security finding awaiting a disclosure decision from the repo owner. **This task does not file it.** Do not run `gh issue create` for it. Do not name it in another issue's body. Do not put a reproduction in the commit message. The `test.fail()` and its comment are the whole deliverable; the finding goes in this task's report, addressed to the controller, for the owner to decide on.

Row 15 also depends on **Task 2** — `not-found` is a no-op on the provider's `/movie/` route without it. If Task 2 did not land, row 15 cannot be written: record that and stop, and Task 13 records the row as `todo` naming Task 2 as the blocker.

- [ ] **Step 2: Row 15**

`test.setTimeout(180_000)`. Seed one movie as in Task 9 Step 1 and let it ingest **before** arming anything. Arming a fault before the account exists turns the account create itself into the failure — `M3UAccountViewSet.create` calls `refresh_m3u_groups` and `refresh_categories` inline with no `try`.

Then:

```ts
await upstream.fault(scenario, 'not-found');
const res = await request.get(`/proxy/vod/movie/${movie.uuid}`);
```

`request.get`, not `streamClient.open` — `open()` throws on a non-2xx.

```ts
const body = await res.text();
// Asserts the behaviour Dispatcharr SHOULD have. Any exception raised while
// establishing the upstream VOD connection becomes
//     HttpResponse(f"Streaming error: {str(e)}", status=500)
// (apps/proxy/vod_proxy/multi_worker_connection_manager.py:1405, and the
// same shape at apps/proxy/vod_proxy/views.py:845). `stream_vod` is
// AllowAny and gated only by network_access_allowed(request, "STREAMS"),
// whose default ACL is 0.0.0.0/0 — so this response body reaches an
// unauthenticated caller. The account credential must not appear in it.
//
// DELIBERATELY NOT FILED as a public issue: this is a disclosure decision
// for the repo owner, recorded in the G9 task report instead. Do not open
// one from this comment.
expect(
  body,
  'an upstream failure must not return the provider account credential to the caller'
).not.toContain(scenario.password);
expect(res.status(), 'an upstream failure should not surface as a 500').not.toBe(500);
```

Assert the credential first. The status assertion is secondary and is there because a fix that stopped leaking the credential while still returning a 500 would be incomplete — but if only one assertion can be the reason this is `test.fail()`, it should be the credential one.

`scenario.password` is a per-test throwaway generated from `seed.generatedName`, which is why it is safe to reference it in an assertion at all.

Clear the fault in a `finally`.

- [ ] **Step 3: Row 16**

**Requires `MovieSpec.isAdult`.** If Task 1 declined it, do not write this test; record "adult VOD filtering is unobservable end to end" and Task 13 makes the row a `todo` gap.

`test.setTimeout(180_000)`. Scenario declares one movie with `isAdult: true` and one control movie without. `seed.xcAccount(scenario, { enable_vod: true })`, `refresh-vod`, wait for both. Create `seed.xcUser({ user_level: 1, custom_properties: { hide_adult_content: true } })`.

```ts
// Asserts the behaviour Dispatcharr SHOULD have. `xc_get_vod_streams` and
// `xc_get_vod_info` (apps/output/views.py) filter `movie__is_adult=False`
// for a non-admin with hide_adult_content. `stream_xc_movie`,
// `stream_xc_episode` and `stream_vod` (apps/proxy/vod_proxy/views.py)
// apply no adult filter at all — so a movie this user cannot list is one
// they can still watch by asking for it by primary key.
//
// This is the VOD analogue of G5's live defect (stream_xc omitting the
// is_adult and hidden_from_output filters), on different functions with a
// different fix, so it is a separate issue: closing one does not close the
// other.
//
// Issue: <fill in from Step 4 before committing>
test.fail('an adult movie a user cannot list is not streamable by that user', ...)
```

The premise, first, so a refusal below cannot mean anything else:

```ts
const listed = JSON.parse(
  await (await request.get(`/player_api.php${xcQuery(user, { action: 'get_vod_streams' })}`)).text()
) as { stream_id: number }[];
expect(listed.map((s) => s.stream_id)).not.toContain(adultMovie.id);
expect(listed.map((s) => s.stream_id)).toContain(controlMovie.id);
```

Then the subject:

```ts
const res = await request.get(`/movie/${user.username}/${user.xcPassword}/${adultMovie.id}.mp4`);
expect(
  res.status(),
  'a movie hidden from this user by hide_adult_content must not stream'
).not.toBe(200);
```

`request.get` is safe here — the VOD asset is finite, so an unwanted 200 downloads a few hundred kilobytes and returns, unlike G5's live analogue, which had to avoid an endless TS stream. No `streamClient`, and nothing to close.

- [ ] **Step 4: File the row-16 issue only**

```bash
gh issue create --repo D10Scot/Dispatcharr \
  --title "stream_xc_movie, stream_xc_episode and stream_vod apply no is_adult filter, so a hidden movie is streamable" \
  --label needs-triage
```

Body: name the three functions in `apps/proxy/vod_proxy/views.py`, contrast with `xc_get_vod_streams`/`xc_get_vod_info` in `apps/output/views.py`, and say explicitly that this is separate from the live-streaming analogue G5 filed, because the fix is a different clause in different functions.

**Do not file anything for row 15.**

- [ ] **Step 5: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming vod-upstream-error vod-adult-streamable
```

Expected: two expected failures. For row 15, confirm the failure is on the credential assertion, not on a timeout or on the fault failing to arm — `upstream.fault(...)` returns `appliedTo: 0` for `not-found`, which is **correct and expected** (headers are already sent on any response that is already open), not a sign the call did nothing.

- [ ] **Step 6: Report the security finding**

In this task's report, addressed to the controller: state that an unauthenticated caller can obtain the provider account credential through an upstream-error response on the VOD path; name `multi_worker_connection_manager.py:1405` and `views.py:845`; note the two related INFO-level log lines in `apps/proxy/vod_proxy/views.py` (the full request path at `stream_vod`'s entry, and the entire client header dict) that are in the same family as CLAUDE.md's existing credential-logging findings; and say that no public issue was filed, pending the owner's disclosure decision. **No reproduction steps beyond "the test in `vod-upstream-error.spec.ts` pins it".**

- [ ] **Step 7: Commit**

`test(e2e): pin the adult-VOD streaming gap and an unfiled upstream-error finding (G9 rows 15, 16)`

Keep the message at that level of detail. Do not name the leaked field.

---

### Task 12: Row 21 — VOD Redirect mode

The one row that mutates a **global** `CoreSettings` row, which is why it goes in `streaming-greybox` (1 worker) rather than `streaming`.

**Files:**
- Create: `e2e/tests/streaming-greybox/vod-redirect-profile.spec.ts`
- Modify: `e2e/playwright.config.ts` (one appended comment line)

- [ ] **Step 1: The spec-file header**

The file's header comment must state, before anything else:

- This spec **mutates a global row** — `CoreSettings`'s `stream_settings` group, specifically `default_stream_profile` — and restores it in a `finally`.
- **VOD Redirect mode is a global setting with no per-content override.** `stream_vod` consults `CoreSettings.is_default_stream_profile_redirect()` (`core/models.py:549`), which compares `get_default_stream_profile_id()` against the locked `Redirect` profile's id. There is no per-movie and no per-account override — the exact opposite of live streaming, where G4 passed `streamProfileId` per stream. That is why the row cannot be written any other way.
- **A crashed run leaves the instance's default Stream Profile on Redirect**, which breaks every subsequent live-streaming test in that container until it is reset. The restore is therefore unconditional and in a `finally`, never gated on an assertion passing.
- The precedent is `e2e/tests/streaming-failover/failover-buffering.spec.ts`, which does the same read-modify-write-restore against the global `proxy_settings` row. Read it before writing this one.

- [ ] **Step 2: The settings read/write**

```ts
const CORE_SETTINGS_PATH = '/api/core/settings/';
const STREAM_SETTINGS_KEY = 'stream_settings';  // core/models.py:201

type SettingsRow = { id: number; key: string; value: Record<string, unknown> };

const rows = await api.json<SettingsRow[]>(await api.get(CORE_SETTINGS_PATH), 'core settings');
const row = rows.find((r) => r.key === STREAM_SETTINGS_KEY)!;
const original = row.value;
```

`GET /api/core/settings/` returns a plain array — no `DEFAULT_PAGINATION_CLASS` is configured. `value` is the **whole** settings-group blob (`default_user_agent`, `default_stream_profile`, `m3u_hash_key`, `default_output_format`, `hdhr_output_profile_id`), so every write is a read-modify-write of the full object.

Guard against a dirty instance before writing, exactly as the buffering spec does:

```ts
const redirect = await lockedProfile(api, 'Redirect');
expect(original.default_stream_profile, 'a previous run left stream_settings dirty')
  .not.toBe(redirect.id);
```

`lockedProfile` is the existing helper in `e2e/tests/streaming/helpers.ts` — import it as `'../streaming/helpers'`. `REDIRECT_PROFILE_NAME` is the literal `"Redirect"` (`core/models.py:47`), and the profile is looked up by `name` with `locked=True`.

Write:

```ts
await api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, {
  value: { ...original, default_stream_profile: redirect.id },
});
```

`_get_group`'s Redis cache is invalidated by `CoreSettings`'s `post_save` signal (`core/models.py:372-410`), so the change is visible to every uWSGI worker immediately — unlike `proxy_settings`, which the buffering spec has to outlast a 10-second process-local cache for. **Verify this rather than assuming it**: read `/api/core/settings/` back and assert the value took, and if the redirect assertion below proves flaky, add a `waitFor.condition` retry around the `streamClient.open` rather than a sleep.

- [ ] **Step 3: The assertions**

```ts
await streamClient.open(`/proxy/vod/movie/${movie.uuid}`, { redirect: 'manual' });
expect(streamClient.status).toBe(302);
```

**302, not 301.** The Redirect branch returns `HttpResponseRedirect(selected['final_stream_url'])` (`apps/proxy/vod_proxy/views.py:758`), while the session-mint path returns a hand-built `HttpResponse(status=301, …)`. The status alone distinguishes "sent at the provider" from "sent to your own session URL", which is the whole point of the row.

```ts
const location = streamClient.headers!.get('location')!;
// Throws on any URL outside the provider's internal origin, which is what
// proves the client was sent at the provider and not somewhere else.
const control = upstream.toControl(location);
expect(control).toContain('/movie/');

const connections = await upstream.connections(scenario);
expect(connections.live).toBe(0);
```

`live === 0` is what proves **no bytes traversed Dispatcharr**: in Redirect mode the product never opens an upstream connection at all, it hands the URL to the client.

Optionally follow `control` with `fetch` and assert 200 plus an `ftyp` box, proving the URL the client was handed actually works. Keep it — a redirect to a URL that 404s would satisfy every assertion above.

- [ ] **Step 4: The restore**

```ts
} finally {
  await api.patch(`${CORE_SETTINGS_PATH}${row.id}/`, { value: original });
}
```

Unconditional. Not inside an `if`, not after an assertion, not skipped on success.

- [ ] **Step 5: The config comment**

In `e2e/playwright.config.ts`, in the `streaming-greybox` project's existing block comment (the one explaining why `workers: 1`), append one sentence naming the second reason: a VOD spec now mutates the global `stream_settings` row's `default_stream_profile`, and a second worker running any streaming test concurrently would take the Redirect path unexpectedly. **Append to the existing comment; do not restructure it, and change no `workers`, `timeout` or `testDir` value.** This is the only edit G9 makes to this file, and it is deliberately behaviour-free.

- [ ] **Step 6: Verify**

```bash
./scripts/e2e_up.sh && cd e2e && npx playwright test --project=streaming-greybox vod-redirect-profile
```

Expected: one passing test. Then, in the same container, re-run one existing streaming test — `npx playwright test --project=streaming vod-byte-read` — and confirm it still passes. That is the check that the restore actually restored; a dirty `stream_settings` would turn that test's 200 into a 302.

- [ ] **Step 7: Commit**

`test(e2e): VOD Redirect mode sends the client at the provider (G9 row 21)`

---

### Task 13: Documentation and the coverage inventory

**Runs last.** It lists the files the other tasks create, and its `known-bug` rows carry the issue numbers they filed.

**Files:**
- Modify: `e2e/COVERAGE.md`
- Modify: `e2e/README.md`

- [ ] **Step 1: Move the eleven existing G9 rows**

The eleven `| … | G9 | todo |` rows at `e2e/COVERAGE.md`. Each becomes `done` where a test landed, or stays `todo` with a note saying exactly what was tried and why it could not be. Specifically:

| Existing row | New status | Note if not `done` |
|---|---|---|
| Catalogue ingest → `VODCategory`, `Movie`, `Series`, relations | `done` | — |
| Category gating | `done` | — |
| Episode ingest on demand, both `episodes` shapes | `done`, or `todo` if `seasonsAsArray` was declined | name the declined addendum field |
| Advanced movie data merge | `done` | — |
| XC VOD/series actions against a real catalogue | `done` | — |
| `vod_proxy` session mint, redirect, byte delivery | `done` | — |
| `vod_proxy` Range and seek | `done` | — |
| `vod_proxy` against `range-unsupported` | `known-bug`, linked to [#66](https://github.com/D10Scot/Dispatcharr/issues/66) | — |
| Root XC playback routes | `done` | — |
| **Characterization: `Client.authenticate()` checks only `user_info`** | stays `todo`, **re-labelled** | See Step 3 |
| **Known defect: suffix range `bytes=-500`** ([#64](https://github.com/D10Scot/Dispatcharr/issues/64)) | `known-bug` | now pinned by `vod-range.spec.ts` |

Two further existing G8 rows need amending, not adding:

- The row saying "a provider's 416 is unreachable through `vod_proxy` … G9 should not write an assertion expecting a 416 to surface end to end until this is fixed" → append that G9 pinned it with a `test.fail()` asserting the correct 416, and that the passing control (a 416 *is* returned on an established session, `:1114`) sits in the same file. Status `known-bug` with the defect-3 issue number.
- The row saying "`not-found`/`auth-failure` have no effect on `/movie/…` or `/series/…`" → `done`, naming Task 2 and the scenario-wide-only scoping.

Leave the two `handleXc` **method-gate** rows at `todo`, and append the reason G9 declined: the fix is one guard at the seam Task 2 already touched, but no G9 test exercises a non-GET VOD request, and an unasserted behaviour change is one nobody can verify closed.

- [ ] **Step 2: Add the new rows**

Rows 15, 16, 17, 19 and 20 have no row today. Add one each in the existing format, status `known-bug`, with the issue link:

```
| VOD | **Known defect:** VODCategoryFilter.m3u_account names a relation VODCategory does not have, so `GET /api/vod/categories/?m3u_account=<id>` is a 500 ([#NN](…)) | G9 | known-bug |
| VOD | **Known defect:** xc_get_vod_info gates the detailed_info merge on Movie.custom_properties while reading the relation's, so a sparse provider's bitrate/video/audio never reach an XC client ([#NN](…)) | G9 | known-bug |
| VOD | **Known defect:** an unsatisfiable Range on a VOD session's first request is a 500, not a 416 ([#NN](…)) | G9 | known-bug |
| VOD | **Known defect:** stream_xc_movie/stream_xc_episode/stream_vod apply no is_adult filter, so a movie a hide_adult_content user cannot list is still streamable ([#NN](…)) | G9 | known-bug |
| VOD | **Known defect:** stream_xc_episode's DoesNotExist guard is dead after .first(), so an unknown episode id is a 500 rather than a 404 ([#NN](…)) | G9 | known-bug |
```

And **row 15's**, which carries no link:

```
| VOD | **Known defect, deliberately unfiled:** an upstream failure during a VOD stream returns the provider account credential to an unauthenticated caller. Pinned by `e2e/tests/streaming/vod-upstream-error.spec.ts`; **no public issue exists**, pending a disclosure decision by the repo owner. Do not open one from this row | G9 | known-bug |
```

That wording is the whole entry. No mechanism, no line numbers, no reproduction — the `test.fail()`'s comment carries the technical detail where it belongs, in the code, and the task report carries it for the owner.

- [ ] **Step 3: Re-label the `xc-auth-envelope` characterization row**

Spec's Non-goals: **G9 does not file it.** `Client.authenticate()` ignoring `auth`/`status` is a *provider-compatibility* property of XC **account authentication**, not of VOD; the honest home for it is whichever goal owns that, which is G3's and G8's territory. Filing an issue for a behaviour no test pins produces an issue nobody can verify closed. Rewrite the row to say exactly that, keep it `todo`, and name G3/G8 rather than leaving "G9 decides whether to file it" standing.

- [ ] **Step 4: Add the named gaps**

Each of these was tried, or considered and declined, and must be a row rather than silence:

- **`stream_icon` → `VODLogo` ingest is unreachable.** `MovieSpec` declares no image URL and `movieEntry` emits `stream_icon: ''`, so no `VODLogo` is ever created from a G9 scenario and `Movie.logo` is always null. Closing it is one optional `MovieSpec` field. `todo`.
- **Multi-provider VOD selection and priority ordering.** `_order_candidates` and `_xc_fetch_priority_distinct_relations` are real, but proving them needs two accounts deliberately sharing one `Movie` row — the exact aliasing hazard spec D3 forbids everywhere else, and a failure indistinguishable from a cross-worker collision. `todo`.
- **Pre-stream failover between providers.** `_select_vod_stream` never connects — it rejects a candidate only for a missing URL, a profile at capacity, or a non-`http(s)` URL — so there is nothing to fail over *from* except a capacity rejection. Needs the two-account setup above. `todo`.
- **Seek semantics.** G9 proves the requested byte range comes back; it does not prove a player can decode from that offset. A container question, not a proxy question. `todo`.
- **`head_vod`.** Not routed (`apps/proxy/vod_proxy/urls.py`). Dead code stays dead. `done` as a note.
- **`vod_stats` and `stop_vod_client`.** Admin-only observability; `stop_vod_client`'s stop signal is checked every 100 chunks and needs a long stream to observe. `todo`.
- **VOD image and logo proxying, and `/api/vod/all/`.** Spec D15. `done` as a note.
- **`batch_refresh_series_episodes`.** Reachable only through a task with no endpoint, and its 24-hour cutoff makes it unobservable inside a test run. `todo`.
- **The four `vod_proxy` Lua scripts and `active_streams` concurrency.** Not touched, not asserted, not "fixed" under a failing test. Restate spec D12's reasoning in one sentence. `done` as a note.
- **`seedXcUser` duplication**, if Task 3 Step 5 ran: `e2e/tests/streaming/helpers.ts` and `e2e/fixtures/seed.ts` now both provide an XC user factory. G5 owns collapsing them. `todo`.
- **Defect #61 (unencoded credentials in `collect_xc_streams`)**, whose existing row says it is owned by whichever of G9/G10 first ingests an XC account with an unsanitised credential. Append: **G9 declines it.** It is a *live* stream-URL construction defect in `apps/m3u/tasks.py`, which G3 owns, and it is unassertable through any VOD route regardless — the provider's `/movie/` route matches `[^/]+` per credential segment, so a slash-bearing credential is a malformed URL by construction. `todo`, owner unchanged.

- [ ] **Step 5: List the spec files**

Follow the format of the G1/G2/G4/G8 blocks at the bottom of the file: a prose sentence saying which rows share which file, then the list. Name all twelve G9 spec files:

`vod-fixture.spec.ts`, `vod-ingest-fidelity.spec.ts`, `vod-category-gating.spec.ts`, `vod-episodes.spec.ts`, `vod-advanced-data.spec.ts`, `xc-vod-catalogue.spec.ts` (all `seeded`); `vod-stream.spec.ts`, `xc-vod-playback.spec.ts`, `vod-range.spec.ts`, `vod-upstream-error.spec.ts`, `vod-adult-streamable.spec.ts` (all `streaming`); `vod-redirect-profile.spec.ts` (`streaming-greybox`).

State explicitly that `e2e/tests/seeded/vod-catalogue-ingest.spec.ts` and `e2e/tests/streaming/vod-byte-read.spec.ts` remain **G8's** rows and were not touched.

- [ ] **Step 6: `e2e/README.md`**

Four edits, all additive:

1. **A new "VOD" section**, placed after "The fake upstream provider" and before "The login throttle", covering exactly four things and nothing else:
   - **`POST /api/m3u/accounts/<id>/refresh-vod/` is the trigger** (202; 400 for a non-XC account or one without `enable_vod`). `waitFor.m3uRefreshComplete` says nothing about VOD, and an M3U refresh reaching `success` does not mean any `Movie` exists.
   - **Movie, series *and* category names must be generated.** `VODCategory` is unique on `(name, category_type)` globally; `Movie`/`Series` are matched across all accounts by TMDB → IMDB → `(name, year)`. Scope every assertion by `?m3u_account=` **and** a generated name.
   - **`GET /api/vod/categories/` is unpaginated and it writes rows** — it `get_or_create`s the two `Uncategorized` categories and their relations for every active `enable_vod` XC account on the instance, including other workers'. Use `find`, never a length. **Never assert that an account lacks an `Uncategorized` relation.**
   - **The four Lua scripts in `vod_proxy`'s stream counter are off limits.** They bypass the session metadata lock deliberately, as a real bug fix pinned by `apps/proxy/vod_proxy/tests/test_vod_lock_contention.py`. A failing VOD test is never fixed by editing them.
2. Add `readBytes` to the `streamClient` row of the Fixtures table (`open`, `readPackets`, `readBytes`, `collectFor`, `close`).
3. Add the seven VOD entity types to the "Types" section's list of what `fixtures/types.ts` covers, and — if Task 3 Step 5 ran — add `xcQuery` to the "exports that are not fixtures" table and `xcUser` to the `seed` row.
4. Leave the CI paragraph alone. It correctly says seven projects as of G6.

- [ ] **Step 7: Verify the whole goal**

```bash
cd /Users/dion/git/<worktree>/e2e && npm run typecheck
cd /Users/dion/git/<worktree>/e2e-upstream && npm run typecheck && npm test
./scripts/e2e_up.sh --reset
cd /Users/dion/git/<worktree>/e2e
npx playwright test --project=seeded
npx playwright test --project=streaming
npx playwright test --project=streaming-greybox
```

Expected:
- both typechecks exit 0, `e2e-upstream`'s vitest green;
- `seeded`: every G9 spec green, with **two** expected failures (rows 19 and 20) — one if `vodInfo` was declined;
- `streaming`: every G9 spec green, with **six** expected failures (rows 15, 16, 17, 18, the suffix-range pin, and the episode-404 pin) — five if `isAdult` was declined;
- `streaming-greybox`: green, and the previously-passing `streaming` specs still green afterwards.

Record actual wall-clock for each project and compare against what it took before G9. G9 adds six tests to a 4-worker project, nine to a 2-worker one and one to a 1-worker one, several of which block on synchronous provider round-trips. Report any material increase rather than quietly accepting it.

- [ ] **Step 8: Commit**

`docs(e2e): record G9 coverage`

---

## Self-review

**Spec coverage.** D1 → Tasks 1 and 2 are the only provider work, both gated or pre-sanctioned. D2 → Global Constraints, applied in Tasks 4–8. D3 → Global Constraints and every scenario literal in Tasks 4–12. D4 → the `test.setTimeout()` on the first line of every `seeded` test, Tasks 4–8. D5 → Task 12. D6 → Tasks 9, 10, 11. D7 → Global Constraints, applied in Task 8 and Task 11's row 16. D8 → Task 10 Step 1's differential comparison. D9 → Task 5 Steps 2 and 3. D10 → Task 5 Step 4. D11 → the issue-filing steps in Tasks 4, 8, 9, 11, and the two "already filed" notes in Task 10 — **with the one deliberate exception the brief requires**, defect 1, which Task 11 pins and does not file. D12 → Global Constraints, repeated in Task 13's README section. D13 → the File structure table, which touches no workflow and changes one comment in `playwright.config.ts`. D14 → `seed.xcAccount` with VOD overrides throughout; no new factory. D15 → Task 13's gap rows.

Test inventory rows 1–21 → Tasks 4 (1, 2, 19), 5 (3, 4, 5), 6 (6, 7), 7 (8), 8 (9, 10, 20), 9 (11, 12, 14), 10 (13, 17, 18), 11 (15, 16), 12 (21).

**Three deliberate departures from the spec, each stated where it happens.**

1. **Rows 1, 2 and 19 go in a new file**, `vod-ingest-fidelity.spec.ts`, not `vod-catalogue-ingest.spec.ts` — that name is already taken by G8's plumbing proof, which merged after the spec was written.
2. **The `stream_xc_episode` 404 defect gets its own `test.fail()`** rather than being "folded into row 14's assertions". The spec asks for both that and for row 14 to be a passing row, and those cannot both hold: a passing test cannot contain an assertion the product fails. Splitting it is the minimal resolution, at the cost of a seventh `test.fail()` in the goal.
3. **Row 1 does not assert `logo.url`.** `MovieSpec` declares no image URL and G8's `movieEntry` emits `stream_icon: ''`, so no `VODLogo` can exist. The plan asserts `logo === null` and records the gap.

**Two additions the spec did not have**, both because `e2e/COVERAGE.md` assigns them to G9 and both costing no new issue: the suffix-range pin (#64, Task 10 Step 5) and the `handleXc` fault seam (Task 2). The second is a hard dependency of row 15, not an optional extra.

**Where the plan says "verify, then decide" rather than asserting a value nobody derived.** Task 3 Step 1 (has G5 landed?). Task 1 Step 1 (is the addendum agreed?). Task 10 Step 1 (the asset's real length, which is not a constant — the generator asserts only "at least 1 KB and starts with `ftyp`", because ffmpeg is unpinned). Task 12 Step 2 (does the `stream_settings` write take effect immediately, or does it need outlasting a cache the way `proxy_settings` does?). All four are "run this and write down what it says" steps.

Every other endpoint, status code, header value, settings key and literal in this plan was read out of the tree at the commits named at the top, including the two that a first draft had left as open questions: `SeriesViewSet.get_episodes` is the surface row 7's two-relations assertion needs (`EpisodeViewSet` has no `providers` action), and `waitFor.condition` resolves to void rather than to the body.

**Type consistency.** The seven VOD entity types, `VodPage`, `CategorySettingRow` and `VodLogo` are defined in Task 3 before their first use in Task 4. `xcQuery`/`XcUser`/`seed.xcUser` come from exactly one place, decided by Task 3 Step 1's gate and used identically from Task 8 onward. `readBytes` is defined in Task 3 Step 2 and used only where a byte-granular read is genuinely needed; every other body read in the goal is `request.get()` plus `body()`, because a VOD response is finite. `lockedProfile` comes from the existing `e2e/tests/streaming/helpers.ts` in Task 12 and is never redefined. The per-file `seedVodContent`/`seedCatalogue` helpers in Tasks 4, 5, 8 and 9 are deliberately **not** promoted to the fixture layer: they encode one goal's scenario shape, and putting a `refresh-vod` POST in `fixtures/` would make it look like the sanctioned way to seed VOD for every future goal, which it is not.

**Ownership ledger.** Tasks 1, 2, 3, 12 and 13 touch shared files and must not run concurrently with each other. Tasks 4–11 create only their own spec files and can run in any order or in parallel, after Task 3. Task 13 must run last.
