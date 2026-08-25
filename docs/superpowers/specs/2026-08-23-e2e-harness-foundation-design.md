# G1 — E2E Harness Foundation

**Date:** 2026-08-23
**Status:** Approved, ready for implementation planning
**Wave:** 1 (parallel with G2, disjoint files)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`

## Goal

Build the harness that five wave-2 goals code against: fixtures, auth reuse, API seeding,
project topology, CI wiring, a glossary, a coverage inventory, and worked exemplars.

G1's output is a **contract**, not test coverage. It succeeds if a wave-2 agent can write a
correct test by copying an exemplar and reading fixture signatures, without reading G1's
internals.

## Current state

- `e2e/` holds one spec (`first-run-setup-and-login.spec.js`), plain JS, `workers: 1`,
  `fullyParallel: false`. Playwright pinned at 1.62.1 via `e2e/package-lock.json`.
- `.github/workflows/e2e-tests.yml` builds the AIO image, runs one container, runs the suite.
- The existing test consumes the pristine first-run state, which every other test would want.

## Verified facts this design rests on

Each was checked against the pinned types in `e2e/node_modules` or this repo, not recalled.

| Fact | Source | Consequence |
|---|---|---|
| Auth is JWT; the browser persists **three** localStorage keys: `accessToken`, `refreshToken`, `tokenExpiration` (the access token's `exp` claim, unix seconds) | `frontend/src/store/auth.jsx:15–25, 186–190` | `storageState` can carry auth. **All three keys are required** — `getToken()` reads `tokenExpiration` first and refreshes if it is missing or past, so a state with only the tokens silently forces a refresh on every call |
| There is **no** `token` key. `api.js:192` clears a `token` key on the 401 path, but nothing ever writes it | `frontend/src/api.js:192` vs `store/auth.jsx:188` | Dead key. A hand-built `storageState` using `token` authenticates nobody and lands the test on `/login` with no obvious cause |
| `StorageState` is `{ cookies, origins }`, `origins` carrying localStorage | `playwright/types/test.d.ts:7504` | The above actually works |
| `TestProject` supports `dependencies`, `fullyParallel`, `retries`, `teardown`, `timeout`, `workers` | `playwright/types/test.d.ts:173, 319, 445, 624, 711, 752` | Project topology below is expressible; ordering is a real dependency, not a convention |
| `testInfo.workerIndex` is unique per worker, and a restarted worker gets a **new** index | `test.d.ts:2705` | Prefix namespacing is safe even across worker restarts |
| **`APIResponse` has only `body(): Promise<Buffer>`, which awaits full download** | `playwright-core/types/types.d.ts`; `playwright-core/src/server/network.ts` | **Playwright's `request` fixture cannot read an endless stream.** `/proxy/ts/stream/<uuid>` never ends, so `body()` never resolves |
| `ACCESS_TOKEN_LIFETIME = 30 minutes`, refresh 1 day, no rotation | `dispatcharr/settings.py:452` | A token captured in setup goes stale mid-run; API helpers must refresh |
| `ci.yml` does not push on pull requests; its build is multi-arch | `.github/workflows/ci.yml:148, 79` | Image cannot be shared between jobs via GHCR on the PR path |
| AIO image is ~3.6 GB (`:base` 3.56 GB) | `docker images` | Image transport is expensive; minimise the number of consumers |
| The app is WebSocket-driven for async work — 40+ message types on one `updates` group | `frontend/src/WebSocket.jsx` | Background work does not complete with the HTTP response that triggers it |
| `POST /api/accounts/initialize-superuser/` is IP-gated to private/loopback by default | `dispatcharr/utils.py:142–171` | Works from CI (the request arrives from the Docker gateway, a private address). Pointing `E2E_BASE_URL` at a *public* instance fails bootstrap unless `DISPATCHARR_SETUP_ALLOWED_IP` is set |
| Usernames must match `^[A-Za-z0-9._@-]+$` | `apps/accounts/serializers.py:16` | The `e2e-w0-…` prefix format is legal; do not introduce other separators |

## Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **TypeScript**, `e2e/` only | Playwright transpiles natively; one `tsconfig.json`. Fixture signatures become the enforced contract between agents who will not read each other's code |
| D2 | **Hand-written seeding helpers** over DRF | A client generated from `/api/schema/` would encode the API's known inconsistencies as the contract. When a serializer is fixed we want a red test |
| D3 | **Shared container, API-seeded**, per-worker prefix namespacing | Fast; the alternative (container per spec) costs 40–60s of boot each |
| D4 | **One build job → `docker save` → artifact → three consumer jobs** | `docker/Dockerfile:14` uses `npm install` with no lockfile, so N builds can produce N different frontend bundles. Build once = one artifact under test |
| D5 | **REST polling by default**, WS fixture available | Polling is robust; the WS message vocabulary is a fixed dict in the product and will drift. Toast assertions are banned |
| D6 | **Streaming client is Node `fetch`**, in a dedicated Playwright project | Forced by the `APIResponse.body()` finding above |
| D7 | **No cleanup** — namespacing only | Container dies with the job. Cascade-delete ordering across `Channel`/`Stream`/`ChannelProfile` is a flake source that masks real assertions |
| D8 | **Transparent 401→refresh** in the `api` fixture | Product config stays untouched, so the suite still exercises the real token path |
| D9 | **E2E required on PRs**, known bugs marked `test.fail()` | Skipping loses information; advisory means nobody looks |
| D10 | **root `CONTEXT.md` glossary + one ADR** | Three things are called "profile" in this codebase |

## Architecture

### Directory layout

```
e2e/
├── COVERAGE.md             inventory: area / flow / owning goal / status
├── README.md               local dev, incl. E2E_BASE_URL escape hatch
├── tsconfig.json
├── playwright.config.ts
├── fixtures/
│   ├── index.ts            the single import surface for wave 2
│   ├── api.ts              authed APIRequestContext + refresh
│   ├── seed.ts             namespaced factories
│   ├── auth.ts             storageState, asUser()
│   ├── wait.ts             REST polling helpers
│   ├── ws.ts               /ws/ subscription
│   └── stream-client.ts    Node fetch, TS-aware
├── setup/
│   └── bootstrap.setup.ts  superuser + admin storageState
└── tests/
    ├── pristine/           fresh-instance only (holds the ported first-run test)
    ├── seeded/             the default population
    └── streaming/          byte-level, long timeouts
```

### Playwright projects

| Project | `testDir` | `dependencies` | Notes |
|---|---|---|---|
| `bootstrap` | `setup/` | — | Creates the superuser via `/api/accounts/initialize-superuser/`, obtains a JWT, writes `storageState` |
| `pristine` | `tests/pristine/` | — | Runs against its own untouched container. `workers: 1` |
| `seeded` | `tests/seeded/` | `[bootstrap]` | The default. Parallel workers |
| `streaming` | `tests/streaming/` | `[bootstrap]` | Long `timeout`, low `workers` |

### CI topology

```
build (amd64 only) ──docker save──> artifact
                                       ├─→ pristine  (own container)
                                       ├─→ seeded    (own container, parallel workers)
                                       └─→ streaming (own container, isolated)
```

Three consumers, no `--shard`. The container is the expensive unit, not the tests; Playwright's
in-process workers give parallelism inside each job for free, and uWSGI's 4 workers × 400
greenlets will not notice. Revisit only if `seeded` wall-clock passes ~15 minutes.

## Fixture contract

This table is the deliverable. Wave-2 agents should need nothing beyond it.

| Fixture | Provides |
|---|---|
| `api` | Authed `APIRequestContext`; transparent 401→refresh (D8) |
| `seed` | `seed.channel()`, `seed.user()`, `seed.m3uAccount()`, `seed.epgSource()`, `seed.channelProfile()`, `seed.streamProfile()` |
| `adminPage` | `Page` with admin `storageState` pre-applied |
| `asUser(level)` | Context for Streamer (0) / Standard (1), for the authorization matrix |
| `waitFor` | REST polling, e.g. `waitFor.m3uRefreshComplete(id)` |
| `ws` | `/ws/` subscription, for state only observable over WebSocket |
| `streamClient` | Node `fetch`: `readPackets(n)`, `collectFor(ms)`, `expectTsAligned()` |

Two deliberate properties:

- **`seed.*` generates names; callers cannot pass one.** Namespacing is unbypassable rather
  than a convention someone forgets. Format: `e2e-w${workerIndex}-${testId}-${entity}`.
- **There is no `seed.profile()`.** `streamProfile` and `channelProfile` are distinct and
  nobody can reach for an ambiguous one by accident.

`streamClient` owning `readPackets`/`collectFor`/`expectTsAligned` is what makes G4 tractable —
otherwise G4's agent writes 188-byte alignment logic from scratch and every later test copies it.

## Conventions wave 2 must follow

1. Never assert on a global count or an unfiltered list.
2. Never assert on notification toasts — that makes a backend test a frontend test.
3. Never assume the instance is empty.
4. Read the root `CONTEXT.md` before naming a fixture, spec or variable.
5. Update `COVERAGE.md` in the same PR.
6. Product bugs get `test.fail()` + an issue, never a product patch.

## Deliverables

- [ ] `e2e/` migrated to TypeScript, `tsconfig.json`, Playwright config with four projects
- [ ] All seven fixtures, exported from `fixtures/index.ts`
- [ ] `bootstrap` setup project
- [ ] Existing first-run test ported into `tests/pristine/`
- [ ] Three exemplars: seeded CRUD, async-wait (poll + WS), authz (`asUser`)
- [ ] Throwaway static-TS upstream + one `streaming` exemplar proving `streamClient` works
- [ ] Root `CONTEXT.md` — glossary only, no implementation detail (see `docs/agents/domain.md`)
- [ ] `e2e/COVERAGE.md` — inventory seeded with all seven goals' intended areas, status `todo`
- [ ] `e2e/README.md` + `scripts/e2e_up.sh` (native-arch build, `E2E_BASE_URL` escape hatch)
- [ ] `.github/workflows/e2e-tests.yml` rewritten to the build→artifact→3-consumer topology
- [ ] ADR: "E2E tests run against a shared, API-seeded AIO container"

**Human step, not automatable:** D9 ("E2E required on PRs") needs a branch-protection rule on
`main` naming the three consumer jobs. This fork has no branch protection today, so the
workflow alone does not make anything required — an agent cannot do this and must not claim
D9 is satisfied by shipping the workflow.

### Definition of done

A wave-2 agent, given only the root `CONTEXT.md`, `e2e/COVERAGE.md` and `fixtures/index.ts`, can write a
passing test for a flow G1 never touched, without reading fixture internals.

## Non-goals

- Feature coverage. G1 ships exemplars, not tests. Areas belong to G3–G7.
- The real fake provider. G1's static-TS upstream is throwaway and G2 deletes it.
- Fixing product bugs found while building the harness — file them.
- Touching the backend or frontend unit suites.

## Risks

| Risk | Mitigation |
|---|---|
| `streamClient` ships unproven because G2 isn't ready | The throwaway static-TS upstream exists precisely to prevent this. A fixture with no passing test is a fixture that doesn't work, and G4's agent would be the one to find out |
| Fixture API churns after wave 2 starts | G1 must merge before wave 2 is dispatched. No exceptions — this is the whole point of the wave structure |
| 3.6 GB artifact transport dominates CI time | Measured after first run. Fallback: buildx `cache-from: type=gha` with per-job builds |
| Prefix convention violated by a wave-2 agent | Made unbypassable in the helper API rather than documented (see above) |
| `:base` may not publish an arm64 manifest, breaking native local builds | **Unverified.** Confirm during implementation; if absent, local dev falls back to `E2E_BASE_URL` against a remote instance |
