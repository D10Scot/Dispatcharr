# G11 — Migration-Gate Contract

**Date:** 2026-09-01
**Status:** Draft, ready for review
**Parent:** `2026-09-01-e2e-programme-review-disposition.md` (goal definition),
`2026-08-23-e2e-coverage-roadmap-design.md` (programme rules)
**Verified at:** `origin/main` `76db0332` (G10 / PR #113 merged). Line numbers drift; symbol names are the
durable half of every citation.

## Why this exists

`CLAUDE.md` states the fork's direction: extract the streaming relay from the Django web
workers into its own process. The E2E suite — 77 spec files across eight Playwright
projects — exists to be the safety net that extraction is done against.

It cannot do that job yet, for one reason: **a test failure on a migration branch is
unclassifiable.** Some of these tests assert behaviour a client can observe and must survive
any rewrite that preserves behaviour. Others deliberately assert facts about *this*
implementation — `manage.py showmigrations` output, Redis key shapes, `pgrep -x ffmpeg`
counts, the AIO image's filesystem layout. Both kinds are red when the relay moves. Only the
first kind means something broke.

Today that distinction exists de facto, in project boundaries (`streaming-greybox`,
`lifecycle`) and in prose, and it is already leaky: `tests/lifecycle/restart-persistence.spec.ts`
mixes portable assertions (rows survive a restart) with AIO-image characterization in the same
file. Nothing states it per test. G11 makes it explicit, enforced, and visible to CI.

## Scope

The four parts of the goal definition, unchanged:

1. A per-test taxonomy — `@contract` / `@characterization` — applied to every test, with an ADR
   stating what each tag promises.
2. The quarantine guard generalised from one string to a capability allowlist.
3. A run-everything CI mode, required on migration branches.
4. The `data-testid` contract and the shared-instance mutation rules promoted from prose to an
   ADR, each with an enforced guard.

## 1. The taxonomy

### Mechanism

Playwright's **native tag API**, available since 1.42 and usable on the pinned 1.62.1
(`e2e/package.json`):

```ts
test('a client that reconnects resumes from the ring buffer', { tag: '@contract' }, async ({ … }) => {
```

Not a title suffix. Native tags are structured data: they survive `--grep @contract`, they
appear in the JSON reporter, and they cannot be broken by rewording a title. No test in the
suite uses tags today, so there is nothing to migrate off.

`test.describe()` accepts the same option and its tag is inherited by every test in the block —
but that is barely usable here: only **2** of the 77 spec files use `test.describe` at all. The
work is therefore **190 per-test tags**, one per test declaration. G11 will not introduce
`describe` wrappers purely to hoist a tag: restructuring 75 files to save keystrokes changes
what runs in parallel and buries the tags it was meant to surface.

### What each tag promises

Stated fully in ADR-0002; in summary:

- **`@contract`** — asserts behaviour observable at a client-facing surface: HTTP status and
  body, TS bytes on the wire, a row read back through the REST API, a rendered page. It must
  pass unchanged against any implementation that preserves behaviour. **This is the default.**
  A `@contract` test needs no justification, because "portable" is the standard this suite is
  held to.
- **`@characterization`** — deliberately coupled to this implementation. It asserts something
  that is true of the AIO image, the Redis key layout, the process table, the Django migration
  state, or the container's filesystem, and that a correct reimplementation is permitted to
  change. Every `@characterization` test **must carry a comment naming the implementation fact
  it is pinned to.**

That comment requirement is the whole value of the goal. Without it, a migration branch reads N
red tests and a human re-derives, one by one, which ones matter. With it, the same branch reads
N sentences saying exactly what moved.

### Enforcement

`e2e/tests/guards/tags.spec.ts` walks every `.spec.ts` under `e2e/tests/**` with the TypeScript
compiler API (`ts.createSourceFile`), finds every `test()`, `test.describe()`, `test.fail()`,
`test.skip()` and `test.only()` call expression, and asserts each carries exactly one of the two
tags — directly, or inherited from an enclosing `describe`.

**AST, not regex — and the decision is already made in this tree, not by this spec.**
`e2e/tests/frontend/pageerrors-enforcement.spec.ts` enforces that every test under
`tests/frontend/` destructures `pageErrors`, and it does so by importing `typescript` and
walking the AST. Its header states the reasoning G11 inherits wholesale: *"a checker that
silently skips a shape it cannot read has the same blind spot with the same consequence."*

The independent evidence points the same way. A source scan for the string `docker` across
`e2e/tests/**` today returns `tests/seeded/output-m3u.spec.ts:51`,
`tests/frontend/plugins.spec.ts:73` and `tests/frontend/connect.spec.ts:249` — all three of
them **comments**, none a grey-box escape. A guard that cannot tell code from prose either
fails on prose or is loosened until it catches nothing. `typescript` 5.7.2 is already a
devDependency, so this costs no new dependency.

**Fail-closed, inherited from the same precedent.** Every test declaration the walker finds
lands in one of three buckets — tagged, untagged, or **unverifiable** — and unverifiable fails,
naming the shape it could not read, unless pinned with a reason in a `KNOWN_UNVERIFIABLE`
constant. `pageerrors-enforcement.spec.ts` records why: its own first version recognised only
`test('name', async ({ … }) => { … })` and silently skipped named helpers and non-destructured
parameters, which is the defect it exists to close, one level up.

**One walker, not three.** `pageerrors-enforcement.spec.ts` already contains `isTestCallee()`
and the lifecycle-hook exclusion set (`beforeAll`/`beforeEach`/`afterEach`/`afterAll` declare
setup, not tests). G11's tag guard needs exactly the same predicate, and a third copy would
drift from both. The shared walker is extracted to **`e2e/tests/guards/ast.ts`** — the test
declaration finder, the callee predicate, the hook exclusions, and the three-bucket
fail-closed result — and `pageerrors-enforcement.spec.ts` is refactored onto it, its behaviour
unchanged and its comments preserved. That refactor is a G6-owned file edited by G11; it is
called out in the PR description, and it is the one place G11 touches test logic rather than
adding a tag.

`test.fail()` is included in the list deliberately: the suite has **20** `test.fail()` pins
across 17 files, and a pinned bug is exactly as much a contract statement as a passing test.

### Applying it

190 test declarations across 77 spec files. The default is `@contract`, so the bulk of the work
is mechanical; the judgement is confined to the files that are genuinely
implementation-coupled:

| Area | Expected tag | Why |
|---|---|---|
| `tests/seeded/**`, `tests/streaming/**`, `tests/streaming-failover/**`, `tests/frontend/**`, `tests/pristine/**` | `@contract` | Every assertion is at a client-facing surface. |
| `tests/streaming-greybox/output-profile-sharing.spec.ts` | `@characterization` | Counts `ffmpeg` processes with `pgrep -x` inside the container. |
| `tests/streaming-greybox/vod-redirect-profile.spec.ts` | Per test | The Redirect-mode behaviour is contract; the global `stream_settings` manipulation around it is machinery. Resolved per test during implementation, not assumed here. |
| `tests/lifecycle/upgrade-migrations.spec.ts` | Mixed | `manage.py showmigrations` assertions are characterization; "the rows are still there afterwards" is contract. This file is the reason the taxonomy is per test and not per project. |
| `tests/lifecycle/restart-persistence.spec.ts` | Mixed | Same split. |
| `tests/guards/**` | `@characterization` | Guards assert facts about this repository's own source tree. |

Anything ambiguous is resolved **towards `@contract`**, and the resolution argued in the
comment. A test wrongly marked `@characterization` is invisible on a migration branch; a test
wrongly marked `@contract` is merely a false alarm someone reads. The asymmetry decides it.

## 2. The generalised quarantine guard

`tests/streaming-greybox/quarantine.spec.ts` scans every `.ts` under `e2e/` for the literal
string `greybox/redis` and asserts the importer set equals `GREYBOX_ALLOWLIST`. Its own comment
states the principle: *"A convention plus a README decays silently. This does not."* The
problem is only that it polices one string. `node:child_process` is imported today by
`tests/streaming-greybox/output-profile-sharing.spec.ts` and would be accepted silently in any
new spec.

### Why this cannot be an import-graph guard

The obvious generalisation — flag any test whose transitive imports reach `node:child_process` —
is unimplementable here, and the reason is worth recording so it is not re-attempted.
`e2e/fixtures/index.ts:474` imports `Instance` from `./instance`, and re-exports it at
`:706`; `fixtures/instance.ts` imports `node:child_process`. Every test in the suite imports
`../../fixtures` — item 2 of `e2e/README.md`'s "Writing a test" makes that mandatory. So every
test transitively reaches subprocess execution, and an import-graph guard flags all 70 files.

The guard therefore polices **use**, in four dimensions, each with its own allowlist:

| Capability | Detected as | Allowlisted today |
|---|---|---|
| Container lifecycle | destructuring the `instance` fixture | `tests/lifecycle/**` |
| Subprocess execution | a direct import of `node:child_process` | `tests/streaming-greybox/output-profile-sharing.spec.ts` |
| Grey-box Redis | an import of `fixtures/greybox/redis` | unchanged from `GREYBOX_ALLOWLIST` |
| Container introspection | a **string or template literal** containing `pgrep`, `docker `, or `manage.py` | `output-profile-sharing.spec.ts`, `tests/lifecycle/**` |

The fourth row is where the AST earns its place a second time — it is precisely the rule that a
string scan cannot express without flagging the three comments listed above.

Assertions use `toEqual` on sorted arrays, not `toContain`, exactly as the existing guard does:
*removing* a legitimate use must also be a deliberate edit, or the allowlist rots in the other
direction.

**Scope extended beyond the definition, deliberately.** The definition says `e2e/tests/**`.
This spec also scans `e2e/fixtures/**` and `e2e/setup/**` with their own allowlist entries
(`fixtures/instance.ts`, `fixtures/greybox/redis.ts`). Otherwise the hole moves rather than
closes: add a grey-box helper under `fixtures/`, import it from a test, and a tests-only guard
sees nothing.

## 3. Where the guards live

A new **`guards` Playwright project**: `testDir: './tests/guards'`, no `dependencies`, no
`storageState`, no browser, no container. It is pure static analysis over the repository's own
source and runs in about a second.

This is the first project in `playwright.config.ts` that does not need an instance, so it also
gets a new **`guards` job** in `e2e-tests.yml` — checkout, Node, `npm ci`, `npx playwright test
--project=guards` — with no image download and no `scripts/e2e_up.sh` call, and it joins
`e2e-result`'s `needs`. Adding it to the existing seven-project `test` matrix would make it
download a 3 GB image and boot a container to read text files.

`quarantine.spec.ts` moves here from `streaming-greybox`, and its `SELF_PATH` constant follows
it. `pageerrors-enforcement.spec.ts` moves here too, from `tests/frontend/`: it opens no page
and needs no container, and its scope statement is directory-based (*"every `test()` under
`e2e/tests/frontend/`"*), so the rule it enforces and the blast-radius argument in its header
both survive the move unchanged. `e2e/README.md`'s CI section — *"If you add another project to `playwright.config.ts`, add
it to that matrix too"* — is amended to name the guards job as the one deliberate exception,
with the reason.

## 4. The two ADRs

`docs/adr/` currently holds one record, `0001-e2e-shared-api-seeded-container.md`. Two more:

**ADR-0002 — E2E test taxonomy.** What `@contract` and `@characterization` promise, the
comment obligation on the latter, the tie-break towards `@contract`, and what a migration
branch does with each colour of failure.

**ADR-0003 — The frontend `data-testid` contract and shared-instance mutation rules.**
Promoted from `e2e/README.md` and the module comment in `e2e/tests/frontend/helpers.ts`. Two
guards, both cheap and both catching something real:

- **`testid.spec.ts`** — every `testId` in `SURFACES` (`tests/frontend/helpers.ts`) must appear
  as a `data-testid` somewhere under `frontend/src/**`. Today a frontend rename surfaces as a
  `getByTestId` timeout that reads like a broken test, which `e2e/README.md:79` already
  observes without being able to prevent.
- **`global-mutation.spec.ts`** — **any write to `/api/core/settings/`**, confined to an
  allowlist. `playwright.config.ts` already contains the argument, twice, in prose: of
  `failover-buffering.spec.ts` raising `buffering_speed` it says *"nothing enforces that
  convention, so a future ffmpeg-profile spec added here without reading that test's header
  would race the raised threshold and fail silently"*, and it makes the same observation about
  `vod-redirect-profile.spec.ts` and `default_stream_profile`. This guard is that sentence,
  enforced.

  The rule is that blunt because the data model makes it exact. `core/models.py:CoreSettings`
  is not one row per setting: `key` is unique, `value` is a `JSONField`, and **each row is a
  whole settings group** — eight of them (`stream_settings`, `dvr_settings`, `backup_settings`,
  `proxy_settings`, `network_access`, `system_settings`, `epg_settings`,
  `user_limit_settings`, `core/models.py:201-208`). Every one is instance-wide. There is no
  such thing as a scoped `CoreSettings` write, so the guard needs no key list to maintain and
  cannot be defeated by a group nobody thought of — including `epg_settings`, which has no
  seeding migration and must be `POST`ed into existence before it can be `PATCH`ed.

  **The allowlist's first wave-6 entry is already known.** G14's spec (PR #118) needs exactly
  one global write — narrowing `network_access["XC_API"]` — and argues it is admissible because
  it denies nothing that exists. It never writes the `UI` scope, which gates the endpoint that
  would undo the change. That is the shape an allowlist entry should have: one group, one
  file, and a written argument for why the blast radius is nil. Wave 6 adds it; G11 ships the
  allowlist with the grey-box entries only.

  **Serialising a project is not a substitute for the allowlist**, which is worth stating
  because `playwright.config.ts` reaches for `workers: 1` twice. Two of these groups are read
  through caches that outlive the test that wrote them: `CoreSettings._get_group` caches each
  group in Redis for 300s, and `_REDIRECT_STREAM_PROFILE_ID_CACHE_KEY`
  (`core/models.py:225`) is **TTL-only** — it appears nowhere in `core/signals.py`, so unlike
  the group caches it has no `post_save` invalidation at all. A mutation reverted in teardown
  can therefore still be live for the next five minutes, in a different project, on a
  different worker. Serialisation bounds concurrency; only the allowlist bounds blast radius.

## 5. Run-everything CI mode

### The trigger

**Branch name pattern**: a pull request whose head branch matches **`migration/**`** runs the
full suite. Plus a `workflow_dispatch` boolean input as an escape hatch, for a branch that does
not follow the convention or a one-off full run on any branch.

One prefix, not two. An earlier draft also matched `relay/**`, on the reasoning that the
relay extraction is the migration this gate exists for. Dropped: two prefixes meaning exactly
the same thing is two things to remember and two places to drift, and the extraction can be
branched `migration/relay-…` at no cost. A second prefix can be added later by editing one
`case` arm; removing one that branches already depend on is harder.

Chosen over a PR label because the requirement is *"required on migration branches"* — a branch
pattern is literally that predicate. A label has to be remembered by a human, needs
`types: [labeled]` to re-trigger, and can be removed after a green run. The convention is
recorded in `CLAUDE.md` so it binds future work rather than living only here.

### What full mode changes

1. **Ignores the `changes` path filter** in `e2e-tests.yml` — the full matrix runs whatever the
   diff touched.
2. **Adds `lifecycle-upgrade` to the matrix.** The matrix becomes a `fromJSON` of a
   `changes`-job output rather than a hardcoded list, so the seven-project default and the
   eight-project full mode are one expression.
3. **Runs `lifecycle-tests.yml`'s jobs**, including both bash suites.

### The structural consequence, stated plainly

`lifecycle-tests.yml` is path-filtered on pull requests, and both its own header comment and
`e2e/README.md` state emphatically that it **must not** become a required check, because a
required check on a workflow that never triggers blocks a merge forever.

Making it required on migration branches means adopting the pattern `e2e-tests.yml` already
uses and documents: **always trigger on pull requests, decide inside a cheap `changes` job, and
add an always-reporting aggregate.** So:

- `lifecycle-tests.yml`'s `pull_request.paths` filter comes off.
- **The `suites` job's own `if:` comes off too.** `lifecycle-tests.yml:134` reads
  `if: github.event_name != 'pull_request'` — a second gate, independent of the path filter,
  that no amount of trigger surgery reaches. Removing only the path filter would leave both
  bash suites still unrun on every pull request, and full mode would silently deliver seven
  eighths of what it claims. G12's spec establishes the consequence of this gate having always
  been there: the two suites **have never run in CI on a pull request at all**, so the green
  runs on G7's own PR skipped them both. Full mode replaces the `if:` with the `changes` job's
  full-mode output.
- A `changes` job reproduces the filter as a job output, plus the branch-pattern check.
- A new **`Lifecycle result`** aggregate job runs `if: always()` and passes when everything it
  needs either succeeded or was deliberately skipped — the exact shape of `e2e-result`.
- Cost on an ordinary PR: one ~10s job. The AIO build and the four image pulls stay gated.
- `Lifecycle result` becomes eligible to be a required check. **Adding it to the Main ruleset is
  a repository-settings change outside this PR** — the spec's job is to make it safe, and to say
  so.

The header comment in `lifecycle-tests.yml` and the CI section of `e2e/README.md` are rewritten
in the same change. They currently assert the opposite rule, and leaving them would be worse
than never having written them.

### Prerequisite: the red bash suites

Full mode runs `test-puid-pgid.sh` and `test-tls-postgres.sh`, and **every run of those is
currently red**. The disposition's "8 of 126 and 7 of 12 scenarios" is corrected by G12's spec,
which counted them: those are *assertion* counts, and the true figures are 8 failed assertions
across **4 of 20** puid-pgid scenarios and **7 of 8** tls-postgres scenarios. G11 makes them
reachable; **G12 owns triaging them to green**. Until G12 lands, `Lifecycle result` must not be added to the
ruleset, or it blocks every migration branch on a pre-existing failure. Recorded here because
the two goals ship in different waves and the ordering is not otherwise obvious.

## Merge-order constraints

- **PR #113 (G10) — resolved.** It merged as `76db0332` while this spec was being written, so
  the constraint it created is discharged: its eight new spec files are in the retag's scope
  rather than arriving after it. This spec is rebased onto that tip and every count above is
  measured there. The general form of the constraint stands for anything still in flight —
  **a test PR that merges after the retag lands untagged and turns the tag guard red on
  `main`** — which is the whole argument for wave 5 running alone.
- **G12–G15 all touch spec files G11 retags.** The disposition's sequencing — wave 5 is G11
  alone — follows from this. Wave 6 tags its own new tests per ADR-0002.
- **Outbound, to G13:** G13's spec (PR #115) adds a new `dvr` Playwright project with its own
  CI matrix job. G11 PR A rewrites that matrix from a hardcoded list into a `fromJSON` of the
  `changes` job's output, so the two edits collide in `e2e-tests.yml`. G11 lands first and G13
  rebases onto the new shape; recorded here so G13 does not discover it at merge time.

## Delivery: two pull requests

**PR A — machinery.** The `guards` project and its CI job, all four guard specs, both ADRs, the
`CLAUDE.md` branch-pattern convention, the `e2e-tests.yml` and `lifecycle-tests.yml` changes,
the README rewrites, and `COVERAGE.md` rows. The tag guard ships **warning, not failing**, on
untagged files: it reports the count so the diff is honest about what PR B owes.

**PR B — the retag.** Tags on all 70 spec files, and the one-line flip of the tag guard to
blocking.

The split is for reviewability. PR A is where every decision lives and is worth reading closely;
PR B is bulk with a handful of judgement calls, which a reviewer can find by searching for
`@characterization`.

## Testing

The guards are themselves tests, which raises the obvious question of what tests the guards.
Each guard spec is verified by **mutation** during implementation, and the mutation recorded in
its comment — the standard `m3u-ingest.spec.ts` already sets in this suite, where a
fixture-internal assertion is justified by having demonstrated its removal passes every
behavioural test:

- Tag guard: add an untagged `test()` to a scratch file; the guard must fail. Add a tag inside a
  comment; it must still fail.
- Capability guard: add `import { execSync } from 'node:child_process'` to a non-allowlisted
  spec; the guard must fail. Add the word `pgrep` to a comment; it must **pass**.
- `testid` guard: rename a `data-testid` in `frontend/src/`; the guard must fail.
- Global-mutation guard: add a `proxy_settings` write to a non-allowlisted spec; must fail.

CI is verified by pushing the branch under both names — the ordinary name and a `relay/**`
name — and confirming the matrix expands to seven and eight projects respectively.

## Non-goals

- **Fixing any product code.** The programme's bug policy is unchanged: tests assert correct
  behaviour, pin defects with `test.fail()`, and file issues with
  `gh issue create --repo D10Scot/Dispatcharr`.
- **Triaging the red bash suites.** That is G12, and this spec depends on it only for the
  ruleset change, which is outside both.
- **Adding `Lifecycle result` to the Main ruleset.** A repository-settings change, gated on G12.
- **Rewriting any test's assertions.** G11 adds tags and guards. Where a test is found to be
  weak, that is G15's list, not this one.
- **A third tag.** `@slow`, `@flaky` and per-area tags are not in scope. Two tags with a stated
  default is the contract; more tags is a taxonomy nobody maintains.
