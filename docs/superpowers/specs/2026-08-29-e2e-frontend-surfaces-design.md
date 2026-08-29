# G6 — Frontend Surfaces

**Date:** 2026-08-29
**Status:** Approved, ready for implementation planning
**Wave:** 2 (G1 and G2 landed; G4 landed at `6e71ca20`; G6 branches from `main` at `4a2ad2fd`)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`

**Siblings in flight.** Three other wave-2 goals touch surfaces G6 touches:

- **G7** (`2026-08-28-e2e-deployment-lifecycle-design.md`), unmerged on branch
  `feat/e2e-lifecycle-g7`, edits **four** of the files G6 edits: `e2e/playwright.config.ts`
  (adds lifecycle projects), `.github/workflows/e2e-tests.yml` (adds them to the matrix),
  `e2e/package.json` (test scripts) and `e2e/fixtures/index.ts` (registers its `instance`
  fixture). Every collision is additive and small, but whoever lands second rebases through
  them — and the workflow edit re-runs the zizmor hook, which blocks on **every** finding in
  the edited file. G7 also owns backup **restore** (see D9) and mutates the global
  `system_settings` CoreSettings row (`max_system_events = 7317`), which G6 must not touch.
- **G3** (content sources and ingest) owns the `Sources | Logo upload and assignment`
  `COVERAGE.md` row, which is the same domain as G6's `Frontend | Logos: upload and browse`
  row at a different level: G3 proves ingest and assignment through the API, G6 proves the
  Logos *page* reaches the API at all. G3 edits `e2e/fixtures/seed.ts`; **G6 deliberately does
  not** (D6), so the two do not collide there.

  They **do** collide textually on one paragraph of `e2e/README.md`. Both goals independently
  decided to correct its stale CI section — the one still describing a "hardcoded three-job
  matrix" and citing a line number — on the same grounds, that each is editing that file
  anyway (G3's D11; G6's D3 and "Current state" below). **G6 owns the final state of that
  paragraph**, because G6 is the goal that actually changes the matrix: it adds a sixth job,
  so G3's correction to five entries is outdated the moment G6 lands. Either merge order works
  and neither loses information — if G3 lands first, G6 rebases through it and rewrites the
  count to six; if G6 lands first, G3 drops the correction as already done. The conflict is
  foreseen; this note exists so whoever hits it knows which side is authoritative.
- **G5** (client output surfaces), and the **G8** goal being split out of it, own the VOD
  surface. The `/vods` page is a G6 non-goal for that reason.

## Goal

Prove the SPA and a real backend agree.

The frontend is the **best**-covered part of this repository: 202 vitest files, 6,128 tests,
71.9% coverage. G6 does not re-assert what that suite already owns. It targets the gap that
actually exists, which is narrow and precise:

- `frontend/src/api.js` is **4,017 lines** and `frontend/src/WebSocket.jsx` is **1,130** — the
  two largest files in the tree — and neither has a single test. `CLAUDE.md` records this;
  it is confirmed by `ls frontend/src/**/__tests__/` containing no `api` or `WebSocket` file.
- Every vitest test mocks `api.js`. Nothing anywhere proves a page's write reaches the server,
  or that the server's response shape is the one the store expects.
- The bundle under test in production is not even the bundle vitest ran against:
  `docker/Dockerfile` installs the frontend with `npm install`, not `npm ci`, while CI uses
  `npm ci` (`CLAUDE.md`, "Builds are not reproducible"). The image's dependency set was never
  tested. An E2E run against the image is the only thing that exercises what ships.

So **every G6 test is a wiring proof**, and nothing else. Per surface:

1. a cheap authenticated **render check** — the page mounts, produces no uncaught error, no
   `console.error`, and no failed network request, against a documented noise allowlist; and
2. one **write flow driven through the UI** whose effect is asserted **through the `api`
   fixture against real backend state**.

Never on a toast. `e2e/README.md`'s rule 6 forbids it because a toast assertion turns a
backend assertion into a frontend one — and here it would be worse than that. `api.js`'s
`errorNotification` shows a red toast *and rethrows*, and `request()` throws on any non-2xx,
so a UI write that never reached the server and a UI write the server rejected both surface as
a toast. A test that watched toasts would pass on a broken write. That is precisely the failure
G6 exists to catch, so the assertion has to be the server's own state.

## Current state

All nine G6 rows in `e2e/COVERAGE.md` are `todo`. The harness has exactly **one** browser test
in a shared population — `e2e/tests/seeded/authenticated-session.spec.ts`, which loads
`/channels` and asserts the notification bell is visible — plus `pristine`'s first-run form
test. Nine product surfaces are unobserved end to end.

Six Playwright projects exist — `bootstrap` plus the five test populations `pristine`,
`seeded`, `streaming`, `streaming-failover` and `streaming-greybox` — and
`.github/workflows/e2e-tests.yml` runs those five as a matrix. `e2e/README.md`'s **CI section
is stale**: it says the workflow "runs `pristine`, `seeded` and `streaming` as a hardcoded
three-job matrix (`e2e-tests.yml:49-50`)", which was true before G4 and is not now — and it
cites a line number, which this documentation series forbids. G6 corrects both while it is
editing that file (D3).

**Verified this session: not one of the nine target surfaces carries a `data-testid`.** Across
`frontend/src`, exactly **two** non-test source files contain the attribute at all —
`frontend/src/components/GuideRow.jsx` (`guide-row`) and
`frontend/src/components/forms/SuperuserForm.jsx` (`setup-help`). Both are leaves, neither is a
page. The other 110 files matching `data-testid` are `__tests__/*.test.jsx` files that *query*
by test id through React Testing Library; they do not define one. The task brief's
characterisation of "112 files that carry one — 48 under `components/forms/`, 18 under
`components/tables/`, …" counted the queries, not the attributes. The conclusion it drew is
unaffected and if anything stronger: the product has **two** test ids in total, and no page has
one.

## Verified facts this design rests on

Cited by symbol or filename, never by line number — line numbers in this repo drift, and an
earlier spec in this series shipped four wrong ones.

| Fact | Source | Consequence |
|---|---|---|
| Exactly two non-test files carry `data-testid`: `GuideRow.jsx` and `SuperuserForm.jsx`. No page component does | `grep -rn 'data-testid' frontend/src --include='*.jsx' \| grep -v __tests__` | Nine page surfaces have no stable handle. PR A exists. See D1 |
| The nine surfaces are `/guide`, `/dvr`, `/users`, `/settings`, `/plugins`, `/stats`, `/connect`, `/logos`, and `/settings#backups` | `frontend/src/App.jsx` `<Routes>`; `frontend/src/config/settingsNav.js` | Backups is **not** a route. It is a lazily-loaded section of the Settings page, selected by URL hash |
| `Settings.jsx` reads `useLocation().hash`, looks the id up in `SETTINGS_GROUPS`, and renders that section's `Component` inside `<Suspense>` | `frontend/src/pages/Settings.jsx`; `frontend/src/config/settingsNav.js` | `goto('/settings#backups')` renders `BackupManager` directly. No sidebar click is required, and the section arrives asynchronously |
| `BackupManager` is the `backups` section of the `backup` group, `adminOnly: true` | `frontend/src/config/settingsNav.js` | The "backups surface" is `frontend/src/components/backups/BackupManager.jsx`, not a page. It is the ninth file PR A edits |
| `UiSettingsForm` persists **only** to `localStorage` (`useLocalStorage` for `time-format`, `date-format`, `time-zone`) | `frontend/src/components/forms/settings/UiSettingsForm.jsx` | It cannot serve as the Settings write flow: there is no backend state to assert. See D5 |
| `/api/core/useragents/` is a `ModelViewSet` (`router.register(r'useragents', UserAgentViewSet)`), reachable from Settings → Network → User-Agents | `core/api_urls.py`; `frontend/src/config/settingsNav.js` | A row-scoped, parallel-safe Settings write. See D5 |
| `POST /api/plugins/plugins/import/` accepts a zip upload, extracts it into `PluginManager.plugins_dir`, creates the `PluginConfig` row, and calls `discover_plugins(force_reload=True)` | `apps/plugins/api_views.py`, `PluginImportAPIView`, `_install_plugin_from_zip` | A plugin can be installed **at runtime, over the product's own API**, with no container provisioning. See D8 |
| `discover_plugins(force_reload=True)` touches `<plugins_dir>/.reload_token`; `PluginsListAPIView` calls `discover_plugins(sync_db=False, use_cache=True)`, which reloads whenever that file's mtime exceeds the process's `_last_reload_token` | `apps/plugins/loader.py`, `discover_plugins`, `_get_reload_token`, `_touch_reload_token`; `apps/plugins/api_views.py`, `PluginsListAPIView` | **A plugin installed after boot is visible without a restart, in every uWSGI worker.** The token is a file on the shared `/data` volume, so it is the cross-process broadcast. `worker_process_init` discovery in `dispatcharr/celery.py` is Celery's *initial* load, not the only path. See D8 |
| The UI's own warning says an import "may briefly restart the backend" | `frontend/src/components/PluginWarnings.jsx`, `PluginRestartWarning` | This is a user-facing caution about module reload, not a statement that discovery requires a restart. The loader contradicts it |
| A plugin's trust flag is `cfg.ever_enabled or cfg.enabled` — a database value. The bundled GPG key is used only by the repo/hub manifest path | `apps/plugins/loader.py`, `_discover_plugins_impl`; `apps/plugins/api_views.py`, `OFFICIAL_KEY_PATH` | A locally imported plugin needs no signature. Enabling it is what causes its module to be imported and executed in-process |
| `POST /api/plugins/plugins/<key>/enabled/` sets `enabled` and `ever_enabled`, then force-reloads discovery, which imports the plugin module | `apps/plugins/api_views.py`, `PluginEnabledAPIView`; `apps/plugins/loader.py`, `_load_plugin` | Enabling runs arbitrary Python in the uWSGI worker. The fixture plugin must be inert. See D8 and Risks |
| `POST /api/backups/create/` returns **202** with a `task_id`; the archive is written by a Celery task | `apps/backups/api_views.py`, `create_backup`; `apps/backups/tasks.py` | The backups write flow is asynchronous. It polls, it does not assume |
| The backup filename is `dispatcharr-backup-%Y.%m.%d.%H.%M.%S.zip`, derived from the clock, and **the caller cannot name it**. `list_backups()` globs the directory and returns everything | `apps/backups/services.py`, `create_backup`, `list_backups` | Two concurrent creates in the same second collide on one filename, and no name identifies "my" backup. This is the single strongest constraint on G6's topology. See D2 and D9 |
| Downloading a backup is two calls: `GET /api/backups/<name>/download-token/` then `GET /api/backups/<name>/download/?token=…` | `apps/backups/api_urls.py`; `frontend/src/api.js`, `downloadBackup` | Archive validation costs two requests, not one |
| `api.js`'s `request()` throws on any non-2xx; `errorNotification` shows a toast **and rethrows** | `frontend/src/api.js` | A failed UI write is a rejected promise inside a handler, and a red toast. The toast is not evidence of anything. See the Goal |
| `API.createRecording` catches, toasts, and rethrows — returning nothing on failure | `frontend/src/api.js`, `createRecording` | The DVR write flow's only honest assertion is `GET /api/channels/recordings/` |
| `Connect.jsx` renders subscription badges with `{integration.subscriptions.map((sub) => sub.enabled && (<Badge …>` — **no `key` prop** | `frontend/src/pages/Connect.jsx`, `IntegrationRow` | React emits "Each child in a list should have a unique key" through `console.error`. The Connect render check will see it as soon as an integration has an enabled subscription. It is a real defect: file it, do not allowlist it. See D4 |
| `Connect.jsx` contains `console.log('Deleting connection', id)` and `Stats.jsx` contains `console.log('Processing channel stats:', …)` | `frontend/src/pages/Connect.jsx`, `frontend/src/pages/Stats.jsx` | The collector must filter on `console.error` and `pageerror`, not on all console output |
| The Logos page's "Cleanup Unused" button calls `handleCleanupUnused` → `/api/channels/logos/cleanup/`, which deletes every unreferenced logo instance-wide | `frontend/src/components/tables/LogosTable.jsx`; `apps/channels/api_urls.py` | **No G6 test may click it.** It would destroy other workers' and other goals' seeded logos |
| `getSingleFormDefaults()` defaults `start_time` to a rounded *now* and `end_time` to now + 60 min | `frontend/src/utils/forms/RecordingUtils.js` | A recording scheduled with the defaults starts immediately and `run_recording` fires. The DVR test **must** move both pickers. See D7 |
| The recording form uses Mantine 8's `DateTimePicker` for `start_time` and `end_time`, and a searchable `Select` for `channel_id` | `frontend/src/components/forms/Recording.jsx`; `frontend/package.json` pins `@mantine/dates` `~8.0.1` | The date entry is the fiddliest interaction in G6. See D7 |
| The Connection form labels its fields `Name`, `Connection Type`, `Webhook URL`, `Script Path` | `frontend/src/components/forms/Connection.jsx` | `getByLabel` drives it. No test id needed. See D4 |
| Logo upload and plugin import are both Mantine `Dropzone`s | `frontend/src/components/forms/Logo.jsx`; `frontend/src/pages/Plugins.jsx` | A `Dropzone` renders a real `<input type="file">`; `setInputFiles` with an in-memory `{name, mimeType, buffer}` drives both with no temp file |
| `adminPage` is an alias of `page`. The admin identity comes from the **project's** `storageState`, not from the fixture | `e2e/fixtures/index.ts`; `e2e/playwright.config.ts` | A new project that omits `storageState: 'playwright/.auth/admin.json'` silently hands back an unauthenticated page. The comment on the `streaming` project records exactly this trap |
| `streaming` sets `workers: 2` and does not set `fullyParallel`, so it inherits `false` — files run in parallel, tests within a file do not | `e2e/playwright.config.ts` | File-level parallelism is an existing, load-bearing pattern here. See D2 |
| `streaming-failover` and `streaming-greybox` both pin `workers: 1` because one spec in each mutates container-wide state | `e2e/playwright.config.ts`, project comments; `e2e/README.md` | The repo's established answer to a shared-state hazard is to make the race structurally impossible, not to document it |
| Playwright projects map 1:1 to CI matrix jobs; the matrix is hardcoded `[pristine, seeded, streaming, streaming-failover, streaming-greybox]` | `.github/workflows/e2e-tests.yml`, `test.strategy.matrix.project` | A project missing from the matrix gets no CI coverage and no failure signal. G6's matrix edit is a task, not an afterthought |
| The single required check is the `e2e-result` job, which aggregates `needs: [changes, upstream, test]` | `.github/workflows/e2e-tests.yml`, `e2e-result` | Adding a sixth matrix entry needs **no** branch-protection change |
| Every matrix job calls `./scripts/e2e_up.sh`, which brings up **both** containers — Dispatcharr and `e2e-upstream` — on a shared network | `.github/workflows/e2e-tests.yml`; `scripts/e2e_up.sh`; `e2e/README.md` | The Stats row's `upstream` dependency costs **nothing** in topology. G6 does not edit `e2e_up.sh`, removing one G7 collision |
| `./scripts/e2e_up.sh --reset` rebuilds the image only if `dispatcharr-e2e:local` does not exist | `e2e/README.md`, "Quick start" | After PR A, a local run against a stale image tests a bundle with no test ids. `docker rmi dispatcharr-e2e:local` first |
| The suite spends **zero** logins in steady state; `asPrincipal` is free, `asUser` costs one of three per minute | `e2e/README.md`, "The login throttle" | G6 adds no principal and calls no `asUser`. Every test drives the bootstrap admin |
| The frontend vitest suite passes in default order and fails under `vitest --sequence.shuffle`, from module mocks and store singletons leaking | `CLAUDE.md`, Testing | A statement about the unit suite, but a signal about how much global state the Zustand stores carry. See D10 |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Two PRs, in order. PR A (`feat/frontend-page-testids`) is a product change adding `data-testid` to nine files; PR B (`feat/e2e-frontend-surfaces-g6`) is the tests, gated on PR A** | This is a deliberate exception to the roadmap's convention that test goals do not touch the product, and it is justified four ways. (i) **There is no handle today** — two `data-testid`s exist in the entire product, neither on a page. (ii) **Roles cannot express these targets honestly.** The Guide grid is a `react-window` `VariableSizeList` inside nested Mantine `Box`es with no heading, no landmark and no accessible name; so are the Stats connections grid and the Connect integrations grid. `getByRole` on them would mean inventing an ARIA role the product does not have — a product change either way, and a worse one, because it changes assistive-technology behaviour rather than adding an inert attribute. (iii) **Text selectors couple the suite to UI copy**, so renaming a button breaks nine tests for no product reason. (iv) **A product diff reviewed as a product diff gets reviewed.** The same nine-file diff buried inside an eighteen-test PR does not — the reviewer's attention goes to the tests. Rejected: shipping one PR (loses (iv)); adding roles instead of ids (changes behaviour); driving everything by text (guarantees future breakage) |
| D1a | **Going forward the rule is: prefer `getByRole`/`getByLabel` where a role or label expresses the target honestly; reserve a test id for where it does not.** In G6 that means page roots and unnamed grid containers get test ids; every button, input and switch is driven by its accessible name | Concretely: "Add Logo", "New Connection", "Create Backup", `Name`, `Connection Type`, `Webhook URL`, `Enabled` are all reachable by role or label today and get no test id. The rule keeps PR A small and keeps the suite honest about the product's accessibility |
| D1b | **Test ids scope; seeded names identify; roles drive.** A test id names a *container*; the row inside it is found by the name `seed` generated; the control that acts on it is found by role | This is what keeps every assertion compliant with roadmap rule 4 without inventing per-row test ids. `stats-connections` scopes the grid, `channel.name` picks the worker's own connection out of it, `getByRole('button', { name: 'Stop' })` acts. No global count, no unfiltered list, and PR A stays at container granularity |
| D2 | **One new Playwright project, `frontend`: `workers: 2`, `fullyParallel` unset (so file-level parallelism), `timeout: 120_000`, `dependencies: ['bootstrap']`, `storageState: 'playwright/.auth/admin.json'`. One CI matrix job** | **Workers and parallelism are chosen from the backup filename, not from habit.** `create_backup` derives the name from the clock at second granularity and `list_backups` globs the directory, so two concurrent creates in the same second overwrite one archive with another and no name identifies either. Two workers with *file*-level parallelism makes that structurally impossible — only `backups.spec.ts` creates backups, and one file runs in one worker — while still halving wall clock. It is the same reasoning `streaming-failover` and `streaming-greybox` apply, one notch less severe because G6's hazards are confined to two files rather than latent in every future test. `streaming` already runs exactly this shape (`workers: 2`, `fullyParallel` unset), so it is a precedent, not an invention. **The timeout follows from the slowest operation**: the backups flow is a Celery task polled through `waitFor`, whose default budget is 60s, and the Stats flow opens a real upstream stream and waits out a 5s stats poll. 30s (the global default) cannot hold either; 300s (the streaming projects') would turn a page that never renders into a five-minute stall. 120s is 60s of polling plus page load and navigation, doubled for a CI runner already hosting four uWSGI workers, Postgres, Redis, Celery and two browsers. Rejected: folding G6 into `seeded` (nine browser surfaces would make the fast four-worker API job the long pole for the whole suite, and `seeded`'s `fullyParallel: true` reopens the backup race); `workers: 1` (buys nothing the file-level rule does not already buy); `workers: 4` (two Chromium contexts already share the runner with the container under test) |
| D2a | **One spec file per surface. This is load-bearing, not tidiness** | File-level parallelism is what makes D2 safe, and it only holds if the hazardous work is confined to one file each. Splitting `backups.spec.ts` in two would put two backup-creating files on two workers and reopen the second-granularity collision. The plan states this in `e2e/README.md` next to the project |
| D3 | **G6 edits four shared files and no more: `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`, `e2e/package.json`, `e2e/fixtures/index.ts` — plus `e2e/COVERAGE.md` and `e2e/README.md`. It does not edit `scripts/e2e_up.sh` or `e2e/fixtures/seed.ts`** | All four are also edited by the unmerged G7 branch; the two it avoids are the ones G7 and G3 respectively edit most heavily. `e2e_up.sh` is unnecessary because every matrix job already starts the upstream provider (D11 needs nothing more), and `seed.ts` is unnecessary because every G6 write flow creates its row *through the UI* — which is the point of the goal (D6). While editing `e2e/README.md`, G6 also corrects its stale CI section, which still describes a three-job matrix and cites a line number |
| D4 | **The render check watches three channels — `pageerror`, `console.error`, and any response with status ≥ 400 — filtered by a single, narrow, justified allowlist** | Three channels because the product routes failures to all three: an uncaught exception or unhandled rejection reaches `pageerror`, React's development warnings and the app's own `console.error` calls reach the console, and a rejected write reaches neither reliably but always shows as a 4xx/5xx response. **The allowlist is one exported constant, one entry per pattern, each carrying a `reason` string; patterns match exact URL paths or exact message prefixes, never a bare substring like `/api/`.** Every entry must be justified individually at review, and an entry whose reason is "this is a product defect" is not admissible: roadmap rule 5 applies — assert correct, `test.fail()`, file the issue. The already-identified case is `Connect.jsx`'s missing `key` prop on subscription badges, which React reports through `console.error`; that is a bug to file, not noise to allow |
| D5 | **The Settings write flow creates a User-Agent row through Settings → Network → User-Agents, and asserts it through `/api/core/useragents/`** | The COVERAGE row is "Settings: change and persist", and the obvious reading — change a global `CoreSettings` value — is unavailable and would be wrong twice over. `e2e/README.md` assigns "global `CoreSettings` changes" to the `pristine` project by name, roadmap rule 4 forbids mutating instance-wide state four workers share, and G7 already writes `system_settings.max_system_events` for its own persistence assertions. `UiSettingsForm`, the other candidate, persists only to `localStorage` and proves no wiring at all. User-Agents is a real Settings section, backed by a real DRF `ModelViewSet`, row-scoped, and touched by no other goal |
| D6 | **No `seed.ts` changes. Every write flow creates its row through the UI** | Adding a factory for a row the test is supposed to create through the browser would defeat the goal. The rows the tests need *as preconditions* — a channel for Guide, DVR and Stats — are covered by the existing `seed.channel()` and `seed.upstreamChannel()`. This also removes G6 from the `seed.ts` conflict G3 and G4 already share |
| D7 | **The DVR flow schedules into the *next* month by opening each `DateTimePicker`, advancing one month, and picking the 15th** | `getSingleFormDefaults()` defaults to *now* + 60 min, so a form submitted as-rendered creates a recording `run_recording` will fire — the opposite of what the row wants. Advancing one month and picking the 15th is deterministic whatever today's date is (15 to 46 days out), needs no arithmetic on the current date, exists in every month, and cannot land in the past. Both pickers move, because the form validates `end_time > start_time`. The exact locator for the calendar's day cell is a Mantine 8 rendering detail the plan resolves against the live DOM rather than assuming; the fallback, if the picker proves intractable, is recorded as a gap rather than replaced by an API create — an API create would prove nothing |
| D8 | **The Plugins row installs a fixture plugin through the product's own import endpoint, driven from the page's dropzone. No container provisioning, and no restart.** The plugin key is generated per run; the spec deletes it at the end | The brief offered two options — provision through `scripts/e2e_up.sh`, or restrict the row to the empty state. The code offers a third and better one. `PluginImportAPIView` extracts a zip into the plugins directory and force-reloads discovery; `discover_plugins(force_reload=True)` touches `<plugins_dir>/.reload_token`, and `PluginsListAPIView`'s cached discovery reloads whenever that file is newer than the process's last-seen token. The token is a file on the shared `/data` volume, so it is the cross-process broadcast: **every uWSGI worker converges without a restart.** `worker_process_init` in `dispatcharr/celery.py` is Celery's initial load, not the only discovery path — and the row is a browser row, so the web workers are the ones that matter. The plugin is inert by construction (a manifest, and a `Plugin` class whose `run` returns a constant), because enabling it causes its module to be imported and executed in the uWSGI worker. The zip is built in TypeScript as stored (uncompressed) entries rather than committed as a binary, so the key can carry per-run entropy — a committed archive has a fixed key, which collides with itself on a second run against a non-reset container, where import defaults to non-overwrite and returns 400 |
| D9 | **Backups: create and validate only. Restore is handed to G7 as a named gap in `COVERAGE.md`, with the reason** | Restoring on a shared instance replaces the database under every parallel worker mid-run, and under every *other* project sharing the container locally. G7 is the goal that owns tests needing a differently-configured instance and already stands up per-scenario containers; restore belongs there. The `COVERAGE.md` row is split accordingly: `Backups: create and validate the archive` → G6, `Backups: restore` → G7. Validation is structural and cheap: a new archive name appears in `/api/backups/` that was not in the pre-create snapshot, its reported `size` is non-zero, and the downloaded bytes begin with the local-file-header signature `PK\x03\x04`, end with an end-of-central-directory record `PK\x05\x06`, and are exactly `size` bytes long. That proves a complete, untruncated zip without a zip parser. The spec deletes its archive afterwards so a long-lived local container does not accumulate database dumps |
| D10 | **One surface per test. No multi-surface journeys** | `CLAUDE.md` records the vitest suite failing under `--sequence.shuffle` from module mocks and store singletons leaking. That is a statement about the unit suite, not about Playwright — each Playwright test gets its own browser context, so module state and Zustand singletons cannot leak *between* tests, and `storageState` is re-applied from `admin.json` each time. What it does tell us is how much global state these stores carry *within* one session, and the cheap structural answer is to give each test one surface and one flow. It costs nothing (a fresh context is the default) and removes the only route by which that hazard could reach this suite |
| D11 | **Stats is the only row that needs live data, and it borrows `upstream` and `streamClient` for exactly one test** | The Stats page renders active connections; with none, it renders an empty grid, which proves nothing about the wiring. The upstream provider is already running in every matrix job, so the dependency is free. Confining it to one test keeps the rest of the project independent of the two-container topology and of `E2E_BASE_URL`'s limitations (`e2e/README.md`: the escape hatch does not extend to provider-dependent tests) |
| D12 | **Guide and Stats are read surfaces; their second test asserts backend-sourced content rather than a write** | Neither COVERAGE row describes a write — "Guide grid renders and navigates" and "Stats page renders live data". Forcing a write onto them would mean inventing scope. Guide's wiring proof is that its grid is populated from `/api/channels/channels/`: the worker's own seeded channel appears as a row, reached **by clicking the sidebar link** rather than by `goto`, which is the one place the SPA's router wiring is exercised. Recording a programme from the Guide needs real EPG programme data, which is G3's ingest path; that is recorded as a gap, not attempted here |
| D13 | **Product defects are asserted correct, marked `test.fail()` with the defect named, and filed — never patched** | Roadmap rule 5. Issues go to `gh issue create --repo D10Scot/Dispatcharr`; the explicit `--repo` flag is mandatory, because this checkout is a fork and `gh` without it resolves to upstream's public tracker. The missing `key` prop in `Connect.jsx` is the first known candidate |
| D14 | **No new principals, and no `asUser`. Every test drives the bootstrap admin** | The login budget is three per minute for the entire suite and the cold path already spends all three (`e2e/README.md`). Every G6 write flow is an admin write — the REST API is deny-by-default (`CLAUDE.md`, Auth) and the Settings sections G6 uses are `adminOnly` in `settingsNav.js` — so a non-admin variant would be asserting *who may see what*, which is G5's `Output | Authorization matrix by user_level` row, not G6's wiring. `asPrincipal` remains free if a later row needs it |

## Project topology

```
bootstrap ──┬─→ seeded              (existing)  4 workers, fullyParallel
            ├─→ streaming           (existing)  2 workers, file-level
            ├─→ streaming-failover  (existing)  1 worker
            ├─→ streaming-greybox   (existing)  1 worker
            └─→ frontend            (new)       2 workers, file-level, 120s
pristine    (no dependency, existing)
```

`.github/workflows/e2e-tests.yml`'s matrix becomes
`[pristine, seeded, streaming, streaming-failover, streaming-greybox, frontend]`. Each job gets
its own container from `scripts/e2e_up.sh`, which is what makes D2's file-level rule sufficient:
a backup created by the `frontend` job cannot be seen by any other job.

No branch-protection change is required. The single required check is the aggregating
`e2e-result` job, not the matrix entries.

`e2e/package.json` gains `test:frontend`, and the bare-`npm test` message goes from five
populations to six.

## Test inventory

Ten spec files, eighteen tests, all under `e2e/tests/frontend/`.

| # | COVERAGE row | File | Mechanism | Est. |
|---|---|---|---|---|
| 1 | *(all nine)* | `render.spec.ts` | Nine tests from one table. Per surface: `goto(route)`, wait for the surface's page test id, assert the collector saw no `pageerror`, no `console.error` and no response ≥ 400 outside the allowlist | 9 × 5s |
| 2 | Guide grid renders and navigates | `guide.spec.ts` | Seed a channel; land on `/channels`; click the sidebar's Guide link; assert the URL and that a row bearing the seeded channel's name is present inside `guide-grid` | 15s |
| 3 | DVR: schedule, list, cancel a recording | `dvr.spec.ts` | Seed a channel; open the recording modal; pick it in the `Channel` select; advance both `DateTimePicker`s one month and pick the 15th (D7); submit; assert through `GET /api/channels/recordings/` that a recording exists for that channel with the expected window; assert the card is rendered inside `dvr-page` under the "Upcoming Recordings" heading; cancel it from the card; assert it is gone from the API | 45s |
| 4 | Users: create, edit, delete | `users.spec.ts` | Create a user through the Users table's modal under `seed.generatedName('user')`; assert through `GET /api/accounts/users/` filtered by that name; edit its `user_level` through the UI and re-assert; delete and assert 404/absence | 40s |
| 5 | Settings: change and persist | `settings.spec.ts` | `goto('/settings#user-agents')`; create a User-Agent with a generated name; assert through `GET /api/core/useragents/` filtered by that name; reload the page and assert the row is still rendered — the "persist" half, proved by a second read from the server rather than from the store | 30s |
| 6 | Plugins: list, enable, configure | `plugins.spec.ts` | Build an inert fixture plugin zip with a per-run key (D8); drop it on the Plugins dropzone; assert through `GET /api/plugins/plugins/` that the key is listed; toggle Enabled in the UI and assert `enabled: true` from the API; set the plugin's one settings field in the UI and assert it through the API; delete the plugin as cleanup | 60s |
| 7 | Stats page renders live data | `stats.spec.ts` | `seed.upstreamChannel()`; open a stream with `streamClient`; `goto('/stats')`; assert a connection bearing the seeded channel's name appears inside `stats-connections` within the page's poll interval; close the stream | 60s |
| 8 | Connect: webhook CRUD | `connect.spec.ts` | "New Connection"; fill `Name`, `Connection Type` = webhook, `Webhook URL`; submit; assert through `GET /api/connect/integrations/` filtered by the generated name; toggle `Enabled` and re-assert; delete and assert absence | 40s |
| 9 | Logos: upload and browse | `logos.spec.ts` | "Add Logo"; `setInputFiles` a 1×1 in-memory PNG onto the form's dropzone input; submit with a generated name; assert through `GET /api/channels/logos/` filtered by that name that the row exists and its URL is non-empty; assert the row is rendered in the table. **Never touch "Cleanup Unused"** | 40s |
| 10 | Backups: create and validate the archive | `backups.spec.ts` | `goto('/settings#backups')`; snapshot `GET /api/backups/`; click Create; poll until exactly one new name appears; assert `size > 0`; fetch a download token, download the archive, and assert `PK\x03\x04` at the head, an end-of-central-directory record `PK\x05\x06` near the tail, and a byte length equal to the reported `size`; delete it | 60s |

Estimated project wall clock at two workers: **~4 minutes**, comfortably inside the job's
30-minute budget and shorter than `streaming`.

Two `COVERAGE.md` changes accompany the tests, per roadmap rule 3:

- `Frontend | Backups: create and restore | G6 | todo` is **split** into
  `Frontend | Backups: create and validate the archive | G6 | done` and a new
  `Lifecycle | Backups: restore | G7 | todo` row carrying D9's reason.
- A gap note is added under the Guide row: the grid is proved to be populated from the channel
  API, but not from real EPG programme data, which needs G3's ingest path.

## Fixture additions

One new fixture, one new export, three test-support modules, and a handful of types. No change
to `seed.ts`.

- **`e2e/fixtures/page-errors.ts`** — a test-scoped `pageErrors` fixture. Attaches
  `page.on('pageerror')`, `page.on('console')` filtered to `type() === 'error'`, and
  `page.on('response')` filtered to `status() >= 400`, at fixture setup so nothing before the
  first `goto` is missed. Exposes the three collections and
  `expectClean()`, which fails with the full offending list rather than a count. Its header
  states D4's rule: patterns are exact paths or exact message prefixes, each carries a
  `reason`, and a product defect is filed, not allowlisted.
- **`EXPECTED_PAGE_NOISE`** — the allowlist, exported from the same module and re-exported from
  `e2e/fixtures/index.ts`. **It starts empty.** Its contents are determined by running the
  render check once against a real container and justifying, entry by entry, whatever it sees.
  Candidates worth expecting — and each is a candidate, not a fact, because none has been
  observed yet: a favicon 404, `GET /api/plugins/plugins/<key>/logo/` returning 404 for a
  plugin with no logo, and the WebSocket consumer's reconnect chatter. Anything that turns out
  to be a genuine defect goes to `gh issue create --repo D10Scot/Dispatcharr` instead.
- **`e2e/tests/frontend/helpers.ts`** — the surface table: nine `{ name, route, testId }` rows,
  a `gotoSurface(page, surface)` that navigates and waits for the test id, and the constants the
  specs share. Mirrors `e2e/tests/streaming/helpers.ts`, which is the existing precedent for
  per-project shared spec helpers. Not a page-object layer: eighteen tests do not earn one.
- **`e2e/tests/frontend/plugin-zip.ts`** — builds a plugin archive in memory as stored
  (uncompressed) zip entries: `plugin.json` and `plugin.py` under a directory named by the
  caller's generated key. Roughly fifty lines of buffer arithmetic, fully transparent, and it
  is what lets the key carry per-run entropy (D8). Used by one spec.
- **`e2e/tests/frontend/assets.ts`** — `TINY_PNG`, a 1×1 PNG as a `Buffer` literal, for the
  Logos upload. Passed to `setInputFiles({ name, mimeType, buffer })`; no temp file.
- **`e2e/fixtures/types.ts`** — add `UserAgent`, `ConnectIntegration`, `Recording`, `Logo`,
  `PluginListEntry` and `BackupEntry`, each with a comment naming the serializer or view it was
  read from, per the file's existing rule. No casts at call sites.

## PR A — the nine files

Additive attributes only. No behaviour change, no refactor, no restructuring, no reordering.
**Eleven attributes across nine files.** Each file gets its page-root id; three also get one
container id, and each of those three earns it by removing a specific false positive that the
page root cannot — D1a's rule applied, not a symmetry exercise.

| # | File | Anchor | Test ids |
|---|---|---|---|
| 1 | `frontend/src/pages/Guide.jsx` | `<Box ref={tvGuideRef} className="tv-guide">`; the "Main scrollable container for program content" `<Box ref={guideContainerRef}>` | `guide-page`, **`guide-grid`** — the grid container holds both the virtualized rows and the "No channels match your filters" empty state, so it is what distinguishes *rendered with rows* from *rendered empty*. That distinction is the wiring signal |
| 2 | `frontend/src/pages/DVR.jsx` | `<Box p={10}>` in `DVRPage`'s return | `dvr-page`. No container id: the section headings are real `<Title>` elements ("Currently Recording", "Upcoming Recordings"), and the recording is identified by its uniquely seeded channel name anyway |
| 3 | `frontend/src/pages/Users.jsx` | `<Box p={10}>` in `PageContent` | `users-page` |
| 4 | `frontend/src/pages/Settings.jsx` | `<Box p={10} maw={900} mx="auto">` | `settings-page` |
| 5 | `frontend/src/pages/Plugins.jsx` | `<AppShellMain p={16}>` in `PluginsPage`'s return | `plugins-page`. No container id: the plugin key carries per-run entropy, so nothing else on the page can match it |
| 6 | `frontend/src/pages/Stats.jsx` | `<Box style={{ overflowX: 'auto' }}>` (the page returns a fragment); the `<Box display="grid" p={10} pb={120}>` wrapping `<Connections>` | `stats-page`, **`stats-connections`** — the page also renders a fixed-position `<SystemEvents>` log at the bottom, which can print the same channel name. Scoping to the connections grid is what stops an event-log line passing for a live connection |
| 7 | `frontend/src/pages/Connect.jsx` | `<Box p="md" pb={120}>` (the page returns a fragment); the `<Box display="grid" py={10}>` wrapping the integration cards | `connect-page`, **`connect-integrations`** — same hazard: `<ConnectLogsSection>` is fixed at the bottom and prints integration names |
| 8 | `frontend/src/pages/Logos.jsx` | `<Box>` in `LogosPage`'s return | `logos-page` |
| 9 | `frontend/src/components/backups/BackupManager.jsx` | `<Stack gap="md">` in the component's return | `backups-panel` — required, not optional: `Settings.jsx` renders the section inside `<Suspense>` with a `<Loader/>` fallback, so `settings-page` alone cannot tell "the Backup section mounted" from "the spinner is still up" |

The ninth is not under `pages/` — the backups surface is a lazily-loaded Settings section, not a
route (see the fact table). It is the ninth *surface*, which is what the COVERAGE inventory
counts.

PR A ships no test of its own. The existing vitest page tests
(`frontend/src/pages/__tests__/*.test.jsx`) are the regression check that the attribute did not
disturb the render; `npm test` in `frontend/` must stay green, and the blocking
`frontend/**/*.jsx` eslint hook must stay at its pre-existing advisory level.

## Non-goals

- **Re-testing component behaviour vitest already covers.** 6,128 tests own that. G6 asserts
  wiring, not rendering logic.
- **Visual regression or screenshot diffing.** No baseline images, no pixel comparison.
- **The `/vods` page.** VOD belongs to the goal being split out of G5.
- **The `/channels` and `/sources` pages.** Neither is a G6 COVERAGE row; ingest UI is G3's.
- **`/plugins/browse`.** The plugin repo browser fetches signed manifests from a real remote
  repository over the network; that is an egress dependency this suite does not take.
- **Backup restore.** G7 (D9).
- **The authorization matrix.** Which surfaces a Streamer or Standard user may see is G5's
  `Output | Authorization matrix by user_level` row.
- **Any product change beyond PR A's additive test ids.**
- **Fixing product defects.** Assert correct, `test.fail()`, file with an explicit
  `--repo D10Scot/Dispatcharr`.

## Risks

- **PR A stalls in review and blocks PR B.** Mitigation: PR B is developed on a branch taken
  from PR A's, so the work proceeds; it is rebased onto `main` once PR A merges and is never
  merged first. If PR A is rejected outright, PR B's render checks can fall back to text
  selectors, but the write flows cannot — that would be the point to renegotiate scope rather
  than quietly ship a weaker suite.
- **The E2E image must be rebuilt after PR A**, or the bundle under test has no test ids and
  every G6 test fails on a locator. CI is safe — the `build` job builds from the PR's tree —
  but `scripts/e2e_up.sh --reset` reuses an existing `dispatcharr-e2e:local`. Locally,
  `docker rmi dispatcharr-e2e:local` first. This will be someone's confusing hour if it is not
  written down; the plan writes it into `e2e/README.md`.
- **The noise allowlist grows silently.** Mitigation: D4's rules — exact patterns, a `reason`
  per entry, empty at the start, and a defect is filed rather than allowlisted. It is a review
  obligation, and the first entry someone adds without a reason is the moment the check stops
  being worth running.
- **The Mantine `DateTimePicker` interaction is the most likely thing in G6 to be fragile.**
  It is a popover calendar, not a text input, and its day cells are a Mantine 8 rendering
  detail. Mitigation: D7's month-advance-then-fixed-day procedure is date-independent, so it
  cannot break on the 31st; the exact locator is resolved against the live DOM during
  implementation rather than assumed here; and if it proves intractable the row becomes a
  documented gap rather than an API create that proves nothing.
- **Enabling a plugin runs arbitrary Python in the uWSGI worker.** That is the product's design
  (`CLAUDE.md`: "run arbitrary Python in-process, unsandboxed"), and it is why D8 requires the
  fixture plugin to be inert — a manifest, and a `Plugin.run` returning a constant. It is also
  why the spec deletes the plugin at the end: a leftover plugin is loaded into every worker on
  every subsequent discovery for the life of the container.
- **Backup archives accumulate.** Each is a full database dump. The container outlives the run
  by design (`e2e/README.md`), so a local developer running the project repeatedly would fill
  `/data/backups`. Mitigation: the spec deletes its own archive; the delete runs in a
  `finally`-shaped teardown so a mid-test failure still cleans up.
- **The Guide grid may render no rows for a freshly seeded channel.** `filteredChannels` is
  filtered state, and whether a bare `seed.channel()` (no Channel Profile membership, no group,
  no EPG) survives the default filters has **not** been verified — there is no container to
  probe against from this worktree. This is the one assumption in the design that could change a
  test's shape. **Probe:** seed a channel, load `/guide`, and check whether a `guide-row`
  bearing its name is present; if it is not, determine which filter excluded it and add the
  precondition (most likely membership of the default Channel Profile) to the test rather than
  loosening the assertion.
- **Unhandled promise rejections may not reach `pageerror`.** Chromium reports them through
  `Runtime.exceptionThrown`, which Playwright surfaces as `pageerror`, but this has not been
  confirmed for this Playwright version against this app. It does not matter much: D4's third
  channel, the ≥ 400 response watcher, catches every failed write regardless of how the promise
  was handled. **Probe:** force a write to fail (a duplicate username) and check which of the
  three collectors sees it.
- **G7 collides on four files.** `e2e/playwright.config.ts`, `.github/workflows/e2e-tests.yml`,
  `e2e/package.json` and `e2e/fixtures/index.ts`. Every collision is additive; whoever lands
  second rebases. The workflow edit re-runs the zizmor hook, which blocks on **every** finding
  in the file, legacy included — the workflows are at zero findings and must stay there.
- **`e2e/README.md`'s CI section is already stale** and will be staler after this change. G6
  fixes it: three jobs becomes six, and the line-number citation goes.
