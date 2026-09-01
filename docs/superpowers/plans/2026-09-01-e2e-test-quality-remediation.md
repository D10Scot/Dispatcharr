# G15 — Test-Quality Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the ways the existing E2E suite can be green for the wrong reason, deepen three frontend surfaces that are wired but not exercised, and give the fake upstream provider a versioned contract. One PR of small, individually verified fixes. **No product code changes.**

**Spec:** `docs/superpowers/specs/2026-09-01-e2e-test-quality-remediation-design.md` — read it before Task 1. Every task below cites the spec decisions and audit rows it implements. Where a task and the spec disagree, the spec was verified at `45a33a4a` and wins; say so in the task report rather than silently diverging.

**Verified at `45a33a4a`** (`origin/main`). Earlier drafts were written at `cf95410e` and at `76db0332`; **G11 has since merged**, as `4211cbb7` (PR #123 — the guards, ADR 0002, ADR 0003, full-run CI) and `7a408c2b` (PR #124 — every test tagged, the tag guard blocking), and both documents are rebased onto `45a33a4a`. **Branch off `origin/main` at or after `45a33a4a`.**

**Tech Stack:** TypeScript 5.7.2 (strict; `npm run typecheck` = `tsc --noEmit`), Playwright 1.62.1, Node 24, the G1 fixture set (`api`, `seed`, `waitFor`, `streamClient`, `upstream`, `asPrincipal`, `adminPage`, `pageErrors`, built-in `request`), the G8 XC provider, Docker.

---

## Merge-order gate — both discharged, the gate is open

- [x] ~~**PR #113 (G10) is merged to `main`.**~~ **Discharged** — merged as `76db0332`. It also brought three further `test.fail()` pins; all three are already guarded and are audit rows 18–20, so they add no task.
- [x] ~~**G11 (wave 5) is merged to `main`.**~~ **Discharged** — merged as `4211cbb7` (#123) and `7a408c2b` (#124), with `45a33a4a` on top. Every spec file this plan touches is already tagged.

**Branch off `origin/main` at or after `45a33a4a`.** Nothing here waits on another goal.

**The tag mechanism, since this plan applies it and does not define it** (`docs/adr/0002-e2e-test-taxonomy.md`, `e2e/tests/guards/tags.spec.ts`):

- Playwright's native details option, as an **inline object literal in the second argument**:

  ```ts
  test('a title that says what is asserted', { tag: '@contract' }, async ({ seed, api }) => { … });
  test.fail('the pin title', { tag: '@contract' }, async ({ seed, api }) => { … });
  ```

  A tag may be inherited from an enclosing `test.describe('…', { tag: … }, …)`. The details object **must be a literal** — `const d = { tag: '@contract' }; test('…', d, fn)` is reported `unverifiable` and **fails**.
- `@contract` is the default and needs no justification. `@characterization` additionally requires a `// @characterization: <the implementation fact it pins>` comment immediately above the declaration; the guard does not check that comment, and the ADR requires it anyway.
- `e2e/tests/guards/tags.spec.ts` is **blocking** and fails closed. `KNOWN_UNVERIFIABLE` is empty; do not add to it.

**Every test this plan adds is `@contract`** — Tasks 2–9's guard controls and Task 14's three interactions all assert client-observable behaviour — **except Task 15's contract-version guard, which is `@characterization`** because it asserts a fact about this repository's own source tree, like all eight tests already in `tests/guards/`. Tasks 10–13 edit existing tests without changing what they are; leave their tags alone.

---

## Global constraints

Copied from the spec and the programme rules. Every task's requirements implicitly include this section.

- **No product code is modified.** Not `apps/`, not `core/`, not `dispatcharr/`, not `frontend/`. One issue is filed (Task 15's **C1**); nothing is patched.
- **No `e2e-upstream/src/` change, no new provider capability, no `/version` endpoint.** (Spec D10.) The only file this plan adds under `e2e-upstream/` is `CONTRACT.md`.
- **No `.github/workflows/**` change and no `e2e/playwright.config.ts` project change.** (Spec D12.) This keeps G15 entirely clear of the zizmor ratchet and of G11's and G12's CI work. If a task tempts you to edit a workflow, stop and report. **This still holds even though Task 15 adds a file under `e2e/tests/guards/`**: G11 already created the `guards` project (`testDir: './tests/guards'`) and its own CI job, so a new file there is picked up by both with no edit to either.
- **The five blocking guards in the `guards` project bind every task.** G15 was checked against all of them and trips none — see the spec's "Guards G15 must satisfy". In short: destructure `instance` nowhere (`CONTAINER_LIFECYCLE`); import no `child_process` (`SUBPROCESS`); put no `pgrep`, `docker ` or `manage.py` in a **string or template literal** (`CONTAINER_INTROSPECTION` — comments are invisible to it, code is not); write nothing to `/api/core/settings/` (`GLOBAL_SETTINGS_WRITE` — the Stats "Refresh Interval" `NumberInput` is a page control backed by the `stats-refresh-interval` **localStorage** key, not a settings row, so Task 14 Step 1 is clear); destructure `pageErrors` in every `test()` under `tests/frontend/` (`pageerrors-enforcement.spec.ts`, binding on all three of Task 14's tests); and tag every declaration (`tags.spec.ts`). Run `npm run test:guards` — it needs no container and takes about a second — after any task that adds a test.
- **G15 does not edit G11's guards.** Not `tests/guards/ast.ts`, not `allowlist.ts`, not the five existing guard specs, not the ADRs. Task 15 adds one new file to that directory and nothing else.
- **Every guard is a non-inverted sibling test in the same spec file.** (Spec D1.) Not a comment, not corroboration in another file — `c1858c42`'s standard. Do **not** convert any pin to `test('…')` plus an in-body `test.fail()`, whatever Task 1's spike shows (spec D2).
- **A `test.fail()` body is satisfied by ANY failure in it** — a fixture error, a `TypeError`, an upstream 500. That is the defect being removed. Re-read the spec's three-part rubric before writing any guard.
- **Never assert a global count or an unfiltered list** (roadmap rule 4). Four workers share one container in `seeded`; the `frontend` project shares it too. Locate your own rows by the name `seed` generated. The one documented exception is `backups.spec.ts`'s before/after set difference, whose module comment explains why it is sound — Task 14 inherits it and does not weaken it.
- **Product defects are asserted *correct*, marked `test.fail()`, and filed — never patched.** Issues go to `gh issue create --repo D10Scot/Dispatcharr` — **the explicit `--repo` flag is mandatory**: this checkout is a fork of `Dispatcharr/Dispatcharr` and `gh` without it resolves to the upstream public tracker (`docs/agents/issue-tracker.md`). Add `--label needs-triage`; if that fails because the label does not exist, re-run without it and say so in the task report.
- **Update `e2e/COVERAGE.md` in the same PR** (roadmap rule 3). Task 15 owns it; no other task edits it.
- **The typecheck hook is blocking.** Any edit under `e2e/**/*.ts` runs `tsc --noEmit` for that package. Run `cd e2e && npm ci` once before starting, or the check degrades to a loud note.
- **Commit after every task.** Stage in one shell call, commit in the next — a `PreToolUse` hook rejects `git add` and `git commit` in the same Bash invocation. Conventional Commits, `test(e2e): …` for test changes, `docs(e2e): …` for the contract.
- **Import map — every shared symbol comes from exactly one place. Never redefine one locally.**

  | Symbol | From |
  |---|---|
  | `test`, `expect`, `expectTsAligned`, `expectWellFormedXml`, `parseM3u`, `parseXmltv`, `TS_PACKET_SIZE`, `StreamStatusError`, `xcLiveStreams`, `readChannelStatus`, `PRINCIPALS`, `SEEDED_USER_PASSWORD` | `'../../fixtures'` |
  | `Channel`, `Stream`, `M3uAccount`, `User`, `BackupEntry`, `LogEntry`, `UpstreamScenario`, `ApiClient` (types) | `'../../fixtures'` |
  | `lockedProfile`, `withDeadline`, `newStreamClient`, `seedCatchupChannel`, `catchupTimestamp` | `'./helpers'` from `tests/streaming/`; `'../streaming/helpers'` elsewhere |
  | `SURFACES`, `gotoSurface` | `'./helpers'` from `tests/frontend/` |
  | `E2E_ROOT`, `REPO_ROOT`, `ROOTS`, `findTestCalls`, `listSpecFiles`, `readSpec`, `readTags` | `'./ast'` from `tests/guards/` — Task 15's guard only |

  **The `guards` project is the one exception to the first row.** It runs with no fixtures, so a test under `tests/guards/` imports `test` and `expect` from `@playwright/test` and its path constants from `./ast`, never from `'../../fixtures'`. Every other test in this plan follows the table above.

---

## How to run what you change

```bash
./scripts/e2e_up.sh --reset          # once, at the start
cd e2e && npm ci
npx playwright install --with-deps chromium
npm run typecheck
npm run test:guards                  # Task 15, and after ANY task that adds a test
npm run test:seeded                  # Tasks 2, 3, 4, 5, 10, 11, 13
npm run test:streaming               # Tasks 6, 7, 8, 9, 12
npm run test:frontend                # Task 14
```

`npm run test:guards` needs **no container and no browser** and finishes in about a second — it is static analysis over this repository's own source. Run it after every task that adds a test: an untagged declaration fails it, and finding that out at Task 16 costs more than running it fourteen times.

`streaming-greybox` **must be run alone locally** — it observes container-wide state. No task in this plan touches it, but do not run it concurrently with anything else if you run it at all.

To confirm a `test.fail()` pin is still red *for the right reason* — the single most important verification in this plan — run the file with the JSON reporter and read which assertion the body failed at:

```bash
npx playwright test --project=<project> tests/<path>.spec.ts --reporter=json 2>/dev/null \
  | python3 -c "import json,sys; d=json.load(sys.stdin); [print(t['title'], r.get('status'), [e.get('message','')[:200] for e in r.get('errors',[])]) for s in d['suites'] for sp in s.get('suites',[s]) for t in sp.get('specs',[]) for r in t['tests'][0]['results']]"
```

A pin whose recorded error moved from the intended assertion to somewhere else is a regression in the pin, not a fix.

---

## File structure

**Created:**

| Path | Responsibility | Task |
|---|---|---|
| `e2e-upstream/CONTRACT.md` | The versioned contract: guarantees, non-guarantees, consumers, bump policy | 15 |
| `e2e/tests/guards/upstream-contract.spec.ts` | One `@characterization` guard asserting `CONTRACT.md` and `package.json` declare the same version. In the `guards` project — no container, no browser, no fixtures — **not** in `tests/seeded/` | 15 |

**Modified — one task each, no file touched by two tasks:**

| Path | Change | Task |
|---|---|---|
| `e2e/tests/seeded/m3u-ingest.spec.ts` | +1 non-inverted control (audit row 1) | 2 |
| `e2e/tests/seeded/hdhr.spec.ts` | +1 non-inverted control (audit row 2) | 3 |
| `e2e/tests/seeded/xc-live.spec.ts` | +1 non-inverted control (audit row 3) | 4 |
| `e2e/tests/seeded/token-refresh-deleted-user.spec.ts` | +1 non-inverted control (audit row 4) | 5 |
| `e2e/tests/streaming/hidden-channel-streamable.spec.ts` | +1 non-inverted control (audit row 5) | 6 |
| `e2e/tests/streaming/vod-adult-streamable.spec.ts` | +1 non-inverted control (audit row 6) | 7 |
| `e2e/tests/streaming/vod-upstream-error.spec.ts` | +1 non-inverted control (audit row 7) | 8 |
| `e2e/tests/streaming/vod-range.spec.ts` | +1 provider-only control (audit row 8) | 9 |
| `e2e/tests/seeded/output-m3u.spec.ts` | fold a rename round-trip into the existing control (audit row 15) | 10 |
| `e2e/tests/seeded/xc-output.spec.ts` | `expectWellFormedXml` + `adminPage` (D4) | 11 |
| `e2e/tests/streaming/catchup-path-layout.spec.ts` | `expectTsAligned` (D5) | 12 |
| `e2e/tests/streaming/catchup-cascade.spec.ts` | `expectTsAligned` (D5) | 12 |
| `e2e/tests/seeded/api-fixture.spec.ts` | body + unauthenticated-401 assertions (D11) | 13 |
| `e2e/tests/seeded/authorization.spec.ts` | containment assertion + a deliberate-status-only comment (D11) | 13 |
| `e2e/tests/frontend/stats.spec.ts` | +1 interaction test (D7) | 14 |
| `e2e/tests/frontend/guide.spec.ts` | +1 interaction test | 14 |
| `e2e/tests/frontend/backups.spec.ts` | +1 interaction test (D8) | 14 |
| `e2e/COVERAGE.md`, `e2e/README.md` | rows and one section | 15 |

**Dependency order:** 1 → {2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14} → 15 → 16.
Tasks 2–14 are mutually independent, touch disjoint files, and may run in any order or in parallel. Task 15 must run **after** them all; Task 16 last.

**Priority order, if the wave runs long** (spec, "What this buys the migration gate"): the nine premise guards first — **Tasks 2–10** — because they are the whole migration-gate argument; then **Task 13**, the body assertions on the harness's own proofs; then **Task 15**, the contract and the inventory. Tasks 11 and 12 are two-line assertion strengthenings and can ride with any of them. **Task 14's three frontend interactions go last** and are the only part of this goal that can be dropped to a follow-up without weakening the gate. This is a priority order, not a dependency: the dependency order above still governs.

---

### Task 1: Preflight — establish the baseline and settle the D2 spike

Nothing else in this plan is trustworthy without a known-good baseline: several tasks make a currently-green `test.fail()` go red *for a good reason*, and you cannot tell that from a pin that was already broken.

**Files:** none modified. This task produces a report only.

- [ ] **Step 1: Branch and environment.** Confirm `git merge-base --is-ancestor 45a33a4a HEAD` succeeds — that single check covers both discharged dependencies, since `45a33a4a` sits on top of G11's `7a408c2b`, which sits on top of G10's `76db0332`. Branch `test/e2e-test-quality` off `origin/main`. `cd e2e && npm ci && npx playwright install --with-deps chromium`. `npm run test:guards` (about a second, no container) to confirm the guards are green **before** you start, so a red one later is yours. `./scripts/e2e_up.sh --reset`.

- [ ] **Step 2: Re-derive the site count before baselining anything.** Run:

  ```bash
  grep -rnE "^\s*test\.fail\(" e2e/tests | wc -l      # expect 20 at 45a33a4a
  grep -rncE "^\s*test\.fail\(" e2e/tests | grep -v ':0$' | sort
  ```

  Reconcile the per-file counts against the spec's audit table, which carries one row per site (rows 1–20, all on `main`). Expect three in `vod-range.spec.ts`, two in `xc-vod-playback.spec.ts`, one in each of fifteen further files.

  **The grep survives G11's retag**, and this was checked rather than assumed: the tag went in as an inline object literal in the *second* argument, so every site still begins with `test.fail(` on its own line. Four are the multi-line form, where `test.fail(` sits alone and the title and tag follow on the next line — `catchup-provider-timezone.spec.ts`, `catchup-proxy-mode.spec.ts`, `output-m3u.spec.ts`, `catchup-m3u-advertisement.spec.ts`. The pattern is line-anchored, not title-anchored, so both shapes count.

  **If the total exceeds 20, a pin landed after `45a33a4a` and this plan is short a task** — stop and report it rather than proceeding; a new pin has no verdict and no guard. This check is not ceremony: it is what caught the table going stale when #113 merged mid-review, and it is why the count was re-derived a third time after G11.

- [ ] **Step 3: Baseline all affected projects with the JSON reporter.** Run `seeded`, `streaming` and `frontend` and record, for **every site the count above produced**, which assertion the body failed at. Save the output to a scratch file. This is the reference the later tasks compare against.

  **Expected:** every pin is red-as-expected (Playwright reports "expected failure"), and each fails at the assertion its own comment names. **If any pin currently fails somewhere else — at a seed call, at a `.json()`, at a fixture — that pin was already hollow.** Record it prominently: the guard task for that file will make it go loudly red, and that is a finding for the PR body, not a bug in this plan.

- [ ] **Step 4: The D2 spike — settle it, then discard it.** Write a throwaway spec (not committed) in `e2e/tests/seeded/` containing two tests: one calling `test.fail()` with no arguments **after** a deliberately-failing `expect`, and one calling it **before**. Run with the JSON reporter and record whether Playwright reports the first as a real failure or as an expected failure.

  **Why this is done at all, given spec D2 forbids adopting it:** the spec rejects the in-body form because Playwright's docs recommend against it and do not state the pre-call semantics. Recording the empirical answer once, in this plan's task report, means the next goal that considers it starts from evidence rather than repeating the question. **Delete the spec file before committing. Do not use the mechanism anywhere in this PR, whatever the result.**

- [ ] **Step 5: Verify the two locators Task 14 depends on before anything is written against them.** With the container up, open `/stats` and `/guide` in a browser (or a scratch Playwright script) and confirm: `getByRole('button', { name: 'Refresh Now' })` resolves on Stats; `getByPlaceholder('Filter by profile')` resolves on Guide **and its option list can be addressed** once opened. Record what works. If the Guide profile select's options are portalled beyond reach, record the fallback Task 14 must use (assert the filtered set through `/api/channels/channels/` instead of the DOM).

**Verification:** the task report contains (a) the re-derived site count with its per-file breakdown, reconciled against the spec's table, (b) the full baseline table — one row per site, (c) the D2 spike result in one sentence, (d) the two locator findings. No files are committed by this task.

---

### Tasks 2–9: the premise guards

**Read the spec's "The guard rubric" and "The `test.fail()` audit" before the first of these.** Every one of these tasks has the same shape, so the shape is stated once here and each task below gives only what is specific to it.

**The shape:**

1. Add a **new, non-inverted** `test(...)` in the same file, immediately **above** the pin it guards.
2. It performs the pin's premise — the same seeding shape, the same route — and asserts the premise, un-inverted.
3. Rewrite the pin's comment: replace any "verified with `--reporter=json`" sentence's load-bearing role with a named reference to the new control, in the style `vod-range.spec.ts` already uses (*"It now lives as a non-inverted assertion in the test above ('<title>'), which actually guards it."*). Keep the `--reporter=json` note where it documents *which* assertion the pin fails at; that is still useful.
4. Do **not** delete the pin's own inline premise assertions. They are redundant belt-and-braces after the control exists, and removing them makes the pin's body harder to read for no gain.
5. Tag the new control `{ tag: '@contract' }` — an inline literal, second argument. **Leave the pin's existing tag alone**: G11 already tagged all twenty pins `@contract`, and the pin is not changing what it asserts.

**The shared verification:** run the file's project; assert the new control **passes**, and the pin is still reported as an **expected failure** at the same assertion the Task 1 baseline recorded. Then run the *whole project* once, to catch a control that disturbs a neighbour on the shared instance. Finish with `npm run test:guards` — a second, no container — because an untagged control fails a blocking guard.

**If a control lands red, it blocks and must be resolved before merge.** These controls are `@contract` and non-inverted, so `docs/adr/0002-e2e-test-taxonomy.md` gives them no read-it-and-move-on disposition: *"a red `@contract` test blocks. Behaviour changed; either fix the implementation or argue the test was wrong."* A red control means the pin it guards was hollow — the good outcome this goal exists to produce. Fix the premise, or explain the red in the PR body and say what it means. **Do not retag the control `@characterization` to quieten it**; that would hide exactly the failure class this goal exists to expose.

---

### Task 2: Guard the `M3UAccount.locked` pin (#15) — audit row 1

**File:** `e2e/tests/seeded/m3u-ingest.spec.ts`

The pin's premise is that `seed.m3uAccount()` works and that `PATCH /api/m3u/accounts/<id>/` is accepted. **No test in this file does either** — the other four exercise `seed.upstreamM3UAccount` and the wait helpers.

- [ ] **Step 1** Add `test('an M3U account round-trips a PATCH of a writable field', …)` taking `{ seed, api }`. Seed with `seed.m3uAccount()`. Assert `account.locked === false`. `PATCH` a new `name` (use `seed.generatedName(...)`), assert the response is `ok()`, read the account back and assert the name is the new one.
- [ ] **Step 2** In the pin's doc comment, add a sentence naming the control and what it guards.

**Do not** assert anything about `locked` in the control — that is the pin's job, and asserting it non-inverted would make the control itself fail today.

**Verification:** `npm run test:seeded -- tests/seeded/m3u-ingest.spec.ts`. The control passes; the pin is still an expected failure at `expect(readBack.locked).toBe(false)`.

---

### Task 3: Guard the HDHomeRun lineup pin (#82) — audit row 2

**File:** `e2e/tests/seeded/hdhr.spec.ts`

`hdhr lineup.json carries a seeded channel with a proxy URL` already guards the route and a **plain** `seed.channel()`. What is unguarded is the restricted field set the pin uses — `{ user_level: 10, is_adult: true }`.

- [ ] **Step 1** Add `test('a channel seeded with the restricted attributes the lineup pin depends on round-trips them', …)` taking `{ seed }`. Seed `seed.channel({ user_level: 10, is_adult: true })` and assert the returned row carries `user_level === 10` and `is_adult === true`.
- [ ] **Step 2** In the pin's comment (it is long and good — do not shorten it), add a sentence: the restricted seed shape is guarded by the control above, and the lineup route and its JSON parse by `hdhr lineup.json carries a seeded channel with a proxy URL`.

**Note for the implementer:** the seeded channel this control creates is left on the shared instance, as every `seed.channel()` is. That is fine — it is namespaced, and `hdhr.spec.ts`'s exact-literal assertions are on `discover.json`/`device.xml`, not on the lineup's contents. Do not add a cleanup that the rest of the file does not have.

**Verification:** `npm run test:seeded -- tests/seeded/hdhr.spec.ts`, then the whole `seeded` project.

---

### Task 4: Guard the XC category pin (#85) — audit row 3

**File:** `e2e/tests/seeded/xc-live.spec.ts`

The pin's comment names `the XC live catalogue lists a seeded channel under its own category` as its positive control, but that test uses a `user_level: 0` channel and an unprofiled user — and the differing field is exactly the one the defect turns on. The premise assertion (that `get_live_streams` lists the level-1 channel for the profiled level-1 user) sits **inside** the inverted body.

- [ ] **Step 1** Add `test('a profiled level-1 user lists a level-1 channel', …)` taking `{ seed, request }`, with the **identical** four-seed setup: `seed.channelGroup()`, `seed.channel({ channel_group_id, user_level: 1 })`, `seed.channelProfile()`, `seed.xcUser({ user_level: 1, channel_profiles: [profile.id] })`. Assert `xcLiveStreams(request, user, …)` contains the channel id — the exact assertion currently inside the pin.
- [ ] **Step 2** Correct the pin's comment: it currently claims the level-0 test is "the positive control"; it is a *contrast case*, not a control. Say so, and name the new control.

**Zero login cost:** `seed.xcUser` mints a row and an `xc_password`; it does not call `/api/accounts/token/`.

**Verification:** `npm run test:seeded -- tests/seeded/xc-live.spec.ts`. The control passes; the pin is still an expected failure at the `categories` containment assertion.

---

### Task 5: Guard the deleted-user token-refresh pin (#12) — audit row 4

**File:** `e2e/tests/seeded/token-refresh-deleted-user.spec.ts`

This is the only test in its file, and its own comment names the hazard precisely: a cold-run 429 from `asUser` reads as an expected failure and the pin never reaches the call it exists to exercise.

- [ ] **Step 1** Add `test('a live user\'s refresh token is accepted by /api/accounts/token/refresh/', …)` taking `{ asPrincipal, request }`. Obtain the `standard` principal through `asPrincipal` (**zero login** — the tokens are pre-minted by `bootstrap`), take its refresh token via `freshRefreshTokenForTest()`, `POST` it to `/api/accounts/token/refresh/` and assert **200** with a body carrying a string `access`.

  **This must not spend a login.** Do not use `asUser` here and do not call `seed.user()`. The whole point is that the file's one login stays at one.

- [ ] **Step 2** Rewrite the pin's `test.fail()` caveat paragraph. Keep the 429 hazard note — it is real and the control cannot remove it — but change what it claims: the *route* premise is now guarded by the control above, so a broken refresh endpoint can no longer green the pin; what remains unguarded is the seed-and-login half, which is a harness cost, not a product signal.

**Verification:** `npm run test:seeded -- tests/seeded/token-refresh-deleted-user.spec.ts`. The control passes; the pin is still an expected failure at `toBe(401)`. Confirm with `loginsSpentByThisWorker()` in a scratch run, or by reading the file, that the control adds no login.

---

### Task 6: Guard the hidden-channel streamability pin (#87) — audit row 5

**File:** `e2e/tests/streaming/hidden-channel-streamable.spec.ts` — project `streaming`

The only test in its file. Its whole setup — scenario, `lockedProfile('Proxy')`, `seed.upstreamChannel({ channel: { user_level: 0, is_adult: true } })`, `seed.xcUser({ hide_adult_content: true })` — plus the listing-absence premise, is inside the inversion.

- [ ] **Step 1** Add `test('an adult channel is unlistable for a hide_adult_content user and listable for an admin', …)` above the pin, with the identical setup. Assert: `xcLiveStreams` for the filtered user does **not** contain the channel id; the same call for an admin XC user **does**. Both halves — the negative alone could pass because the seed silently failed.
- [ ] **Step 2** In the pin's comment, replace the load-bearing part of the `--reporter=json` sentence with a reference to the control. Keep the excellent paragraph about why only a refusal may set `served = false` — it is a different hazard and still applies.

**Cost:** this roughly doubles the file's runtime (a second upstream scenario, ~60s). That is the honest price of guarding a single-test file; do not try to share the pin's fixtures to save it, because a shared fixture shares the failure modes the control exists to separate.

**Verification:** `npm run test:streaming -- tests/streaming/hidden-channel-streamable.spec.ts`. The control passes; the pin is still an expected failure at the `served` assertion.

---

### Task 7: Guard the adult-VOD streamability pin (#110) — audit row 6

**File:** `e2e/tests/streaming/vod-adult-streamable.spec.ts` — project `streaming`

**The weakest of the nine, the one verdict the audit had to adjudicate, and worth knowing why before you write it** (spec, "The two verdicts that were contested"). This pin already carries an in-body positive control (`toContain(controlMovie.id)`), and its comment's argument for that control is correct as far as it goes: the absence assertion cannot pass on a listing that never worked. What the in-body control cannot do is guard the *seed and ingest* — a throw anywhere in the body still greens the pin. The guard closes only that.

- [ ] **Step 1** Read the pin fully first. It declares its scenario inline: two movies (`501` adult, `502` control) in one category, an XC account, a VOD refresh and an ingest wait. Add a non-inverted control above it with the **identical** two-movie setup, asserting the **listing** half only — the adult movie absent from the `hide_adult_content` user's `get_vod_streams`, the control movie present. **Do not stream anything in the control**; the ingest is the expensive part and the streaming half is the pin's subject.
- [ ] **Step 2** Update the pin's comment: keep the paragraph explaining why the in-body positive control makes the absence assertion non-vacuous — it is true and worth keeping — and add that the seed-and-ingest premise is guarded by the control above.

**Cost:** a second ~120s ingest. That is the honest price of guarding a single-test file, and it is paid rather than avoided by sharing fixtures (spec D1 rejects a shared `beforeAll` and says why).

**Verification:** `npm run test:streaming -- tests/streaming/vod-adult-streamable.spec.ts`. The control passes; the pin is still an expected failure at the `not.toBe(200)` assertion its comment names.

---

### Task 8: Guard the VOD upstream-error credential pin — audit row 7

**File:** `e2e/tests/streaming/vod-upstream-error.spec.ts` — project `streaming`

**The most important of the eight.** The pin asserts a credential is *not* disclosed in an error response. A hollow green here claims a security property that was never tested — the worst failure mode in the suite.

**Its comment currently makes a claim that does not hold**, and correcting it is part of this task. It argues: *"The fault is armed only after ingest completes, so a failure here can only be the streaming-error path."* That is false. The file's local `seedVodMovie` helper ends in a `waitFor.resource` with a 120-second timeout; an ingest that never completes fails **inside the inverted body** and greens the pin, and the arming order does not help.

- [ ] **Step 1** Add a non-inverted control above the pin using the file's own `seedVodMovie(upstream, seed, api, waitFor)` helper, **no fault armed**: `GET` the VOD stream route for the seeded movie and assert bytes flow (a 200/206 and a non-empty body). This proves the scenario, the account, the `refresh-vod` 202, the ingest wait, the session mint and the route — everything the pin's premise rests on.
- [ ] **Step 2** If the pin arms a fault through `upstream.fault(...)`, add to the control — or as a second, equally cheap control — a direct assertion that the fault produces the upstream failure the pin depends on. `upstream.fault` throws on a non-2xx control response, and a throw inside the inversion is indistinguishable from the defect.
- [ ] **Step 3** Rewrite the pin's `test.fail()` caveat paragraph. Delete the incorrect ordering argument, name the control, and state explicitly that this pin asserts an *absence*, so an unguarded premise would claim a security property was verified when it was not.

- [ ] **Step 4: Correct the comment's filing status.** The pin's comment currently reads, verbatim: *"DELIBERATELY NOT FILED as a public issue: this is a disclosure decision for the repo owner, recorded in the G9 task report instead. Do not open one from this comment."* **That is now wrong.** The defect **is** filed, as [#89](https://github.com/D10Scot/Dispatcharr/issues/89), *"Provider credentials can reach an unauthenticated client in a 500 response body from the VOD proxy"*, opened 2026-08-30 **after checking with the repository owner** and labelled `ready-for-agent`. The disclosure decision was taken; the comment predates it. Replace that paragraph with a citation of #89, in the shape the suite's other pins use (*"KNOWN BUG — see #94"*).

  **Do not open a second issue.** #89 is this defect: it cites `apps/proxy/vod_proxy/multi_worker_connection_manager.py:1405`, the same line the pin's comment quotes, and its Provenance section names this very `test.fail()` as its pin. Cite it; do not duplicate it.

- [ ] **Step 5: Flag the matching `COVERAGE.md` row for Task 15.** `e2e/COVERAGE.md`'s VOD row for this defect carries the same stale claim — *"Known defect, deliberately unfiled … no public issue exists, pending a disclosure decision by the repo owner. Do not open one from this row."* **Do not edit `COVERAGE.md` here** (Task 15 owns that file, and two tasks editing it is how the shared-file rule breaks). Report the exact row text in your task report so Task 15 Step 6 can correct it to cite #89.

**Verification:** `npm run test:streaming -- tests/streaming/vod-upstream-error.spec.ts`. Then re-read the pin's recorded failure in the JSON reporter and confirm it is still the credential assertion.

---

### Task 9: Guard the `range-unsupported` fault arm (#66) — audit row 8

**File:** `e2e/tests/streaming/vod-range.spec.ts` — project `streaming`

`Range and seek on the VOD proxy match the provider byte-for-byte` already guards `seedVodMovie`, the full-GET session establishment and a 206 range read. The single unguarded link is `upstream.fault(scenario, 'range-unsupported')`, which throws on a non-2xx control response — and a throw greens the pin.

- [ ] **Step 1** Add `test('the range-unsupported fault makes the provider ignore Range', …)`. Create a scenario, arm `range-unsupported`, and fetch the VOD asset **directly from the provider** through `upstream.toControl(...)` with a `Range` header. Assert the provider answers **200** (not 206) with the whole asset. Clear the fault in a `finally`, exactly as the pin does — `range-unsupported` is scenario-scoped and the scenario outlives the test.

  **No Dispatcharr involvement.** This is a provider-only proof and should run in a few seconds; do not seed a movie or open a session for it.

- [ ] **Step 2** Update the pin at *a provider that ignores Range still yields the requested bytes* to name the control.

**Do not touch** the other two pins in this file: *an unsatisfiable Range on a fresh session is 416, not 500* (already guarded by `8386825c`) and *a suffix Range returns the tail of the file* (audit row 10, already safe). Their comments are correct as written.

**Verification:** `npm run test:streaming -- tests/streaming/vod-range.spec.ts`. All three pins still expected-failures at their recorded assertions; the new control passes.

---

### Task 10: Guard the EXTINF quote-escaping pin (#80) — audit row 15

**File:** `e2e/tests/seeded/output-m3u.spec.ts`

The smallest guard in the plan. `/output/m3u renders a parseable playlist with a well-formed proxy URL` already covers the seed, the route, `parseM3u` and `wellFormed`. The one unguarded premise is the channel **rename** — no test in the file PATCHes a channel name.

- [ ] **Step 1** In the existing non-inverted first test, after its current assertions, PATCH the seeded channel's `name` to a new generated value (no quote character), assert the PATCH is 200, and assert the read-back carries the new name.
- [ ] **Step 2** In the pin's doc comment, replace the load-bearing part of the `--reporter=json` sentence with a reference to that assertion.

**Do not** add a second `/output/m3u` fetch to the control. The 2-second anonymous cache the file's comments describe makes a second fetch a source of flake, and the rename round-trip is provable through the API alone.

**Verification:** `npm run test:seeded -- tests/seeded/output-m3u.spec.ts`. The pin still an expected failure at the `wellFormed` assertion.

---

### Task 11: `expectWellFormedXml` in `xc-output.spec.ts` — spec D4

**File:** `e2e/tests/seeded/xc-output.spec.ts`

- [ ] **Step 1** In `test('xmltv.php renders a guide for its user', …)`, change the fixture destructuring from `{ seed, request }` to `{ seed, request, adminPage }`, add `expectWellFormedXml` to the import from `'../../fixtures'`, and call `await expectWellFormedXml(adminPage, body)` alongside the existing assertions on the parsed guide.
- [ ] **Step 2** Add a two-line comment recording the division of labour, in the shape `output-epg.spec.ts` already uses: `parseXmltv` reads content and is **deliberately shallow** (it guards only on the substring `<tv` and would extract elements from a document with an unclosed root — see its own comment, which forbids tightening it); `expectWellFormedXml` is the only place in the suite that can honestly say "valid XML".

**Do not modify `parseXmltv`.** Its comment says: *"Do not 'tighten' this without a test proving real Dispatcharr output still parses."*

**Note the real cost, and record it in the commit message:** this makes a request-only test open a browser context. `adminPage` reuses `storageState`, so it spends no login, and `output-epg.spec.ts` and `hdhr.spec.ts` already pay the same cost for the same check — but the disposition called this a "one-line fix" and it is two, with a browser context attached. Say so.

**Verification:** `npm run test:seeded -- tests/seeded/xc-output.spec.ts`. All four tests pass.

---

### Task 12: Replace the two residual first-byte TS assertions — spec D5

**Files:** `e2e/tests/streaming/catchup-path-layout.spec.ts`, `e2e/tests/streaming/catchup-cascade.spec.ts` — project `streaming`

Both reads are `readPackets(20)`, which returns whole 188-byte packets, so `expectTsAligned` is a drop-in that additionally checks the sync byte at every packet boundary rather than only the first.

- [ ] **Step 1** `catchup-path-layout.spec.ts`: replace `expect(bytes[0]).toBe(0x47)` with `expectTsAligned(bytes)`. Add `expectTsAligned` to the import from `'../../fixtures'` — this file does not import it.
- [ ] **Step 2** `catchup-cascade.spec.ts`: in G8's test *the candidate cascade falls through to the QUERY layout when PATH 404s*, replace `expect((await streamClient.readPackets(20))[0]).toBe(0x47)` with `expectTsAligned(await streamClient.readPackets(20))`. **This file already imports `expectTsAligned`** (#113's own five tests use it), so this is a one-line change — confirm before adding a duplicate import. Do not touch #113's five tests.
- [ ] **Step 3** Confirm no other first-byte-only site remains: `grep -rn "0x47" e2e/tests e2e/fixtures`. At `45a33a4a` that returns seven hits, and after this task it should return five: `fixtures/stream-client.ts`'s `TS_SYNC_BYTE` constant and the two prose mentions around `expectTsAligned`, two doc-comment mentions in `fixtures/index.ts`, `contiguity.spec.ts:10`'s synthetic-packet **writer** (`out[off] = 0x47` — not an assertion, not touched), and `fixtures/seed.ts:620`, which is the fourth byte of a **PNG magic number** in a logo-upload payload and has nothing to do with TS. Report anything beyond those rather than changing it — it is outside this task's file list.

**Verification:** `npm run test:streaming -- tests/streaming/catchup-path-layout.spec.ts tests/streaming/catchup-cascade.spec.ts`. Both files pass unchanged in outcome; the assertions are strictly stronger.

---

### Task 13: The status-only assertion fixes — spec D11

**Files:** `e2e/tests/seeded/api-fixture.spec.ts`, `e2e/tests/seeded/authorization.spec.ts`

Four status-only assertions were audited. Two get a body assertion; two stay as they are, with a comment.

- [ ] **Step 1 — `api fixture authenticates against a protected endpoint`.** Add a body assertion: parse the response through `api.json<...>(res, …)`, which throws on a non-JSON body, and assert the result is a list/paginated shape. Comment the reason: `dispatcharr/urls.py` mounts the SPA catch-all **after** the API routes, so a routing regression that shadowed `/api/channels/channels/` would answer **200 with `index.html`** and a status-only assertion would pass.
- [ ] **Step 2 — `api fixture recovers from an expired access token`.** Add the same JSON-shape assertion, **and** an assertion that the same endpoint answers **401 with no credentials**, using the built-in `request` fixture. That is what makes the 200 evidence that a valid token was presented: without it, the endpoint becoming `AllowAny` would leave this test green while proving nothing about the refresh path.

  **Do not** try to observe the access token directly. `ApiClient` exposes no raw getter, and `freshAccessToken()` refreshes as a side effect, so reading it would perturb what it measures.

- [ ] **Step 3 — `an admin can list users`.** Add a **containment** assertion: the body contains the three fixed `PRINCIPALS` usernames. Containment, not a count and not an equality — four workers share the instance and other tests create users (roadmap rule 4). Comment the reason: a filter regression returning 200 with an empty or wrongly-scoped list passes today.
- [ ] **Step 4 — the two `cannot list users` tests.** No assertion change. Add a comment recording that the status-only shape is **deliberate**: the body is DRF's stock `{"detail": …}`, asserting it would pin a framework string rather than product behaviour, and the test is already correctly guarded by the `users/me` identity check that narrows the 403 to one cause.

**Verification:** `npm run test:seeded -- tests/seeded/api-fixture.spec.ts tests/seeded/authorization.spec.ts`. All pass.

---

### Task 14: Real interactions for Stats, Guide and Backups

**Files:** `e2e/tests/frontend/stats.spec.ts`, `guide.spec.ts`, `backups.spec.ts` — project `frontend`

One interaction test per surface, each with an effect observable beyond the DOM. **Use Task 1 Step 5's locator findings.** Every test navigates with `gotoSurface`, never `page.goto` — issue #58, documented in `tests/frontend/helpers.ts`. Every test ends with `await pageErrors.expectClean()`, as every test in this directory does.

- [ ] **Step 1 — Stats: `test('the Refresh Now button re-reads the connection list', …)`.** Reuse the existing test's setup (scenario, `lockedProfile('Proxy')`, `seed.upstreamChannel`, `streamClient.open`, `withDeadline(readPackets(100), …)`). Assert the connection appears in `stats-connections`. Then **close the stream client**, click `getByRole('button', { name: 'Refresh Now' })`, and assert the connection is gone — with a timeout **shorter than the page's own 5s poll interval would need**, so the assertion is about the click and not about the poll. If that margin proves too tight in CI, set the "Refresh Interval (seconds)" `NumberInput` to `0` first (the page renders "Refreshing disabled" when it is), which removes the poll entirely and makes the click the only possible cause. Record which you used and why.

  **Do not** write a "Stop Channel" or "Disconnect client" test. Those controls are `Tooltip`-wrapped icon-only `ActionIcon`s with no accessible name (spec D7, defect **C1**), and the only way to address them is a positional selector this suite should not depend on.

- [ ] **Step 2 — Guide: `test('filtering by Channel Profile narrows the grid to that profile\'s channels', …)`.** Seed two channels; put one in a fresh `seed.channelProfile()`. `gotoSurface`, select that profile in "Filter by profile", and assert the member is present in `guide-grid` and the non-member is absent. Locate rows by the channel logo's `alt` text — `channel.name` reaches the DOM only there and in a hover-mounted `Tooltip` label, which the existing test's comment establishes.

  If Task 1 Step 5 found the select's options unaddressable, use the recorded fallback and say so in a comment.

  **Do not** click a programme and record it. Creating a `Recording` row from the Guide is **G13's** subject.

- [ ] **Step 3 — Backups: `test('an uploaded archive re-appears in the list and downloads back byte-identical', …)`, in `backups.spec.ts`.** Create an archive as the existing test does (or reuse one it left, if the file's structure makes that natural), download it via the `download-token` → `download` pair, then click `getByRole('button', { name: 'Upload' })`, submit the same bytes through the modal, and assert: the new name appears in `GET /api/backups/`, and its download is **byte-identical** to what was uploaded (`Buffer.equals`, not a length comparison — `logo-upload.spec.ts`'s reasoning applies unchanged).

  **Register every new archive name in the existing `namesToDeleteAfterEach` set** so the file's `afterEach` cleans it up. Read that hook and its two long comments before writing — they explain why it is a `Set`, why cleanup treats 204 and 404 alike, and why it must not mask an in-flight test failure.

  **This test goes in `backups.spec.ts`, not a new file.** The module comment explains that the file is pinned to file-level parallelism because `create_backup` names archives by the clock at second granularity and `list_backups` globs the directory; a second backups file would break the before/after set difference the first one's assertions rest on.

  **Do not click a row action.** Download, **Restore** and Delete are three adjacent unlabelled `ActionIcon`s; a positional locator that drifts by one clicks Restore, which replaces the database under every parallel worker (spec D8). Restore is G12's, on an isolated instance.

- [ ] **Step 4** Tag all three new tests `{ tag: '@contract' }` — an inline object literal as the second argument. They drive a rendered page and assert an effect observable through the API, which is `@contract` by ADR 0002's default and needs no justification comment.

- [ ] **Step 5** Confirm each of the three destructures `pageErrors`. `e2e/tests/guards/pageerrors-enforcement.spec.ts` is blocking and requires it of **every** `test()` under `tests/frontend/`; its `KNOWN_UNVERIFIABLE` holds one pinned entry (`plugins.spec.ts:15`) and G15 adds none. This is the same requirement as the `await pageErrors.expectClean()` line above, stated as the named guard it is.

**Verification:** `npm run test:frontend`, then `npm run test:guards`. All three files pass, and the pre-existing tests in them are unchanged in outcome. Run the frontend project twice in a row — the backups file's set-difference logic is the one place in this plan where a leftover from the previous run changes the result.

---

### Task 15: The `e2e-upstream` contract, the inventory, and the issue

**Files:** `e2e-upstream/CONTRACT.md` (new), `e2e-upstream/package.json`, `e2e/tests/guards/upstream-contract.spec.ts` (new), `e2e/COVERAGE.md`, `e2e/README.md`

- [ ] **Step 1: Audit the provider from source, and write the non-guarantees first.** Read every file under `e2e-upstream/src/` and `e2e-upstream/scripts/`, and skim `e2e-upstream/test/` for behaviours the unit tests pin. Produce the **non-guarantee** list before the guarantee list — it is the substance, and it is the half a consumer goal will otherwise rediscover the hard way.

  Two are already confirmed and must appear, each quoting the code:
  - **No calendar validation on catch-up.** The provider answers any parseable timestamp, impossible dates included (`e2e-upstream/src/xc/catchup.ts`, `CATCHUP_TIMESTAMP_SHAPES`).
  - **No time-addressable archive.** The catch-up routes serve the same looping asset whatever `start` they are given. This is the constraint that governs every timing assertion in G10; state it in the same words G10's spec uses so the two cannot drift.

  Then find more. Check at least: does it validate credentials, and how strictly? does it honour `Range` on VOD, and where does `range-unsupported` change that? does it emit a truthful `Content-Length`? does it respect a requested duration? does XMLTV shift with wall-clock or sit at a fixed window? is the connection limit enforced truthfully? do catalogue ids drift across restarts? what does the TS asset **not** carry (per spec D6: no per-stream identity — one asset, fixed PIDs `0x100`/`0x101`, and the burned-in frame counter is *"a human debugging aid only … no test asserts on it"*)? **Every line cites `file:symbol`.**

- [ ] **Step 2: Write `e2e-upstream/CONTRACT.md`.** Follow the spec's six-part structure: version and scope; guarantees; non-guarantees; known consumers; bump policy; enforcement. **Link to `README.md` for every mechanism rather than restating it** — the README's nine sections are the how-to and stay authoritative. Put a sentence in the header stating the default: **an unlisted behaviour is not a guarantee.**

- [ ] **Step 3: Bump `e2e-upstream/package.json` to `1.1.0`** (spec D9) and record in `CONTRACT.md` why: writing the contract adds no behaviour and breaks nothing, and bumping on landing proves the procedure works.

- [ ] **Step 4: Write `e2e/tests/guards/upstream-contract.spec.ts`** — a source-scan guard, no container, no browser, no fixtures. **It goes in `tests/guards/`, not `tests/seeded/`.** G11 deleted `quarantine.spec.ts` (which older drafts of this plan named as the mould) and generalised its role into the `guards` Playwright project; that project is exactly this shape of test, and putting a two-string comparison in `tests/seeded/` would make it wait on a booted instance for nothing.

  Five things it must get right, each matching what its five siblings already do:

  - **Imports.** `import { test, expect } from '@playwright/test'` — **not** `'../../fixtures'`; the `guards` project runs with no fixtures. Read the files with `node:fs/promises`.
  - **Roots.** `import { REPO_ROOT } from './ast'` and resolve both paths from it. **Do not hand-roll a `path.resolve(__dirname, '../..')` walk** — `ast.ts` defines `E2E_ROOT` and `REPO_ROOT = path.resolve(E2E_ROOT, '..')` precisely so a directory move breaks one definition instead of six.
  - **Tag.** `{ tag: '@characterization' }`, an inline literal in the second argument. It asserts a fact about this repository's own source tree, not client-observable behaviour — the same reason all eight existing guard tests carry that tag.
  - **Comment.** A `// @characterization: …` comment immediately above the declaration, naming the fact it pins, in the shared style the directory already uses (*"every test in this file asserts facts about this repository's own source tree … See docs/adr/0002-e2e-test-taxonomy.md"*). ADR 0002 requires it; the guard does not check it.
  - **Justification.** The sentence the deleted `quarantine.spec.ts` justified itself with, which `allowlist.ts` now carries forward: *a convention plus a README decays silently. This does not.*

  It has no effect on `capabilities.spec.ts`: that guard skips `tests/guards/` outright ("this directory's own source names every marker it polices"), so naming an `e2e-upstream/` path in a string literal here cannot trip `CONTAINER_INTROSPECTION`.

  **Do not** add a `/version` endpoint or any other `e2e-upstream/src/` change (spec D10). **Do not** edit `ast.ts`, `allowlist.ts` or any existing guard.

- [ ] **Step 5: `e2e/COVERAGE.md`.** Append:
  - three **Frontend** rows for the three new interaction tests, assigned G15;
  - one **Streaming** *Gap* row recording spec D6 — the per-stream TS marker is feasible under the Proxy profile via a dedicated marker PID injected in `LoopRewriter`, impossible under the locked FFmpeg profile (`-c:v copy -c:a copy` maps one video and one audio and the mpegts muxer rewrites PAT/PMT and PIDs), deliberately not built by G15 because it is a provider change, and recorded so it is not re-derived;
  - one **Upstream** row for `CONTRACT.md` and its version guard;
  - **one row in the `## Guards (G11)` table**, whose columns are `| Guard | Enforces | Proved by |`. Guard: `tests/guards/upstream-contract.spec.ts`. Enforces: `CONTRACT.md`'s declared version equals `e2e-upstream/package.json`'s. Proved by: the mutation from this task's Verification — editing `package.json`'s version made it fail, reverting made it pass. Every guard in that table carries its mutation, and "verified by mutation, recorded in its own header comment" is the section's own rule; a row without one would be the first exception. **Leave the heading as `## Guards (G11)`** — it names the goal that built the project, not the goal that last added a row.

- [ ] **Step 6: Correct the stale `COVERAGE.md` row Task 8 reports.** The VOD row for the credential-disclosure defect claims *"deliberately unfiled … no public issue exists, pending a disclosure decision by the repo owner. Do not open one from this row."* That is now wrong: the defect is filed as [#89](https://github.com/D10Scot/Dispatcharr/issues/89), opened 2026-08-30 after checking with the repository owner. Rewrite the row to cite #89, keeping its `known-bug` status and its G9 goal assignment. **This is the one row belonging to another goal that G15 edits**, and it is a factual correction rather than a re-scoping — say so in the commit message.

  Update no other goal's rows. Do **not** renumber or reorder the table.

- [ ] **Step 7: `e2e/README.md`.** One short section pointing at `e2e-upstream/CONTRACT.md` and saying what it is for: cite a version, not a memory. No existing text rewritten.

- [ ] **Step 8: File defect C1.** `gh issue create --repo D10Scot/Dispatcharr --label needs-triage`. Title: icon-only action controls on Stats and Backups have no accessible name. Body: name all eleven controls with `file:symbol` (`StreamConnectionCard.jsx` — "Stop Channel", "Disconnect client", "Switch to another stream source", "Preview Channel"; `BackupManager.jsx:RowActions` — "Download", "Restore", "Delete"); explain that Mantine's `Tooltip` contributes `aria-describedby`, which does not compute an accessible name, so `getByRole('button', { name })` cannot address any of them; state that this is filed **separately from [#73](https://github.com/D10Scot/Dispatcharr/issues/73)** because #73's fix is two `aria-label`s on two `Switch`es in one file while this is eleven controls in two, and because one of them is **Restore**, where a mis-addressed click replaces the database; propose `aria-label` matching each `Tooltip`'s existing `label`; and record that this **blocked** two otherwise-obvious tests in this PR (spec D7, D8).

  **No `test.fail()` pin for C1.** There is nothing to invert: a missing accessible name is not a behaviour a test can assert as correct-and-failing without pinning a specific `aria-label` string this fork has not chosen. Say that in the issue.

**Verification:** `npm run typecheck`; `npm run test:guards` (no container needed). Then **deliberately edit `e2e-upstream/package.json`'s version, re-run `npm run test:guards`, and confirm the guard fails** naming both declared versions — a guard nobody has seen fail is not a guard, and every row in `COVERAGE.md`'s Guards table carries the mutation that proved it. **Revert the edit**, re-run, confirm green, and record the mutation's exact output for Step 5's Guards row and for the guard's own header comment.

---

### Task 16: Whole-suite verification and the PR

- [ ] **Step 1** `cd e2e && npm run typecheck`.
- [ ] **Step 2** `npm run test:guards` first — it needs no container, takes a second, and an untagged declaration anywhere in the PR fails it. Then `./scripts/e2e_up.sh --reset`, then `npm run test:seeded`, `npm run test:streaming`, `npm run test:frontend`, each to completion. Run `streaming-failover` too — G15 does not edit it, but Task 12's and Task 9's neighbours share fixtures with it and a regression there would be this PR's.
- [ ] **Step 3 — the verification this whole plan exists for.** Re-run the JSON-reporter command from the header against every file holding a `test.fail()`, and diff the result against Task 1 Step 3's baseline. **Every pin must still be an expected failure at the same assertion.** A pin that moved is a regression in the pin. A pin that went from expected-failure to *unexpected pass* means the product defect was fixed between the baseline and now — verify against the issue and report it; do not silently delete the pin.
- [ ] **Step 4** If any guard added in Tasks 2–9 turned a previously-green pin loudly red, that pin was hollow. Say so **in the PR body**, name it, and say what the premise failure was. This is the expected good outcome of the goal, not a failure of it — the spec's Risks section anticipates exactly one such finding.
- [ ] **Step 5** Push and open the PR with `gh pr create --repo D10Scot/Dispatcharr`. The body must contain:

  - **The count: twenty `test.fail()` sites on `main`, nine guarded here, eleven already safe** — with the `grep` that produces the total (`grep -rnE "^\s*test\.fail\(" e2e/tests | wc -l`) and the figure Task 1 Step 2 re-derived. These are the spec's numbers; an earlier draft of this plan said "seventeen … eight already safe", which was the count at `cf95410e` before #113 brought three more, and it is wrong.
  - The per-stream TS marker verdict in one sentence: yes under Proxy, no under FFmpeg, deliberately not built.
  - The corrections to the brief: the `expectWellFormedXml` change is two lines not one, and `plugins` has 9 interactions not 8.
  - The C1 issue link, and the correction that **the VOD credential-disclosure defect is filed as [#89](https://github.com/D10Scot/Dispatcharr/issues/89)** — the pin's comment and the `COVERAGE.md` row both said it was deliberately unfiled, and both were updated (Task 8, Task 15 Step 6). No new issue was opened for it.
  - Any hollow pin found in Step 4, named, with what its premise failure was. If a guard control landed **red**, say so here explicitly: it is `@contract` and non-inverted, so by `docs/adr/0002-e2e-test-taxonomy.md` it **blocks**, and the PR must either fix the premise or make the argument for merging with it red.

---

## What this plan deliberately does not do

Each of these was considered and ruled out in the spec. Do not add them, and if a reviewer asks for one, point at the decision rather than implementing it.

| Not done | Why | Spec |
|---|---|---|
| Build the per-stream TS marker | Feasible under Proxy, but it is a provider change with a fixture reader and an image rebuild — G2-class work, not a small verified fix | D6 |
| Convert pins to in-body `test.fail()` | Playwright recommends against it and does not document the pre-call semantics. Task 1 spikes it for the record only | D2 |
| Tighten `parseXmltv` | Its own comment forbids it without a test proving real Dispatcharr output still parses | D4 |
| A Stats "Stop Channel" test, a Backups row-action test | No accessible name; the Backups case risks clicking **Restore** | D7, D8 |
| Backup restore | G12's, on an isolated instance | D8 |
| A Guide programme → record flow | G13's | — |
| `settings.spec.ts`, `plugins.spec.ts`, M3U filters/profiles, product WS events | G14's | — |
| Define the tag taxonomy | G11's | — |
| A `/version` endpoint on the provider | Provider and consumers ship from one commit; there is nothing to negotiate at run time, and a source-scan guard closes the only thing that can rot | D10 |
| Any workflow or `playwright.config.ts` project change | Keeps G15 clear of the zizmor ratchet and of G11/G12's CI work | D12 |
| Any product code change | One issue filed, nothing patched | roadmap rule 5 |
