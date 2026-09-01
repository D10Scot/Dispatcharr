# G15 — Test-Quality Remediation

**Date:** 2026-09-01
**Status:** Draft, ready for review
**Wave:** 6 (parallel with G12, G13, G14; after G11)
**Parent:** `2026-08-23-e2e-coverage-roadmap-design.md`
**Goal definition:** `2026-09-01-e2e-programme-review-disposition.md`, "G15 — Test-quality remediation"
**Revised:** 2026-09-01, after G11 landed (`45a33a4a`).
**Verified at:** `origin/main` **`45a33a4a`**. G11 has merged, as `4211cbb7` (PR #123 — the guards,
ADR 0002, ADR 0003 and the full-run CI mode) and `7a408c2b` (PR #124 — every test tagged, the tag
guard flipped to blocking). Earlier drafts were verified at `cf95410e` and at `76db0332`; every
count below is re-measured at `45a33a4a`, and the `test.fail()` audit's twenty rows were re-derived
there rather than carried forward. Line numbers drift; symbol names and test titles are the durable
half of every citation.

**Depends on, in merge order — both discharged:**

| Dependency | Why | State |
|---|---|---|
| ~~**PR #113 (G10)**~~ | It added five tests to `catchup-cascade.spec.ts` and the `expectTsAligned` import that makes item 4's change there a one-liner, and brought three further `test.fail()` pins that this audit covers as rows 18–20 | **Discharged — merged as `76db0332`** |
| ~~**G11 (wave 5)**~~ | G11 applied the `@contract` / `@characterization` taxonomy to every test in the suite, touching every file G15 touches, and added the `guards` Playwright project. G11 defines the taxonomy; G15 does not | **Discharged — merged as `4211cbb7` (#123) and `7a408c2b` (#124)**. G15 branches off `main` at or after `45a33a4a` |

**G15 must not define the tag taxonomy — it applies G11's, which is now concrete.** The mechanism,
from `docs/adr/0002-e2e-test-taxonomy.md` and `e2e/tests/guards/tags.spec.ts`:

- The tag is Playwright's native details option, an **inline object literal** as the second
  argument: `test('title', { tag: '@contract' }, async ({ … }) => { … })`, and identically
  `test.fail('title', { tag: '@contract' }, async ({ … }) => { … })`. A tag may be inherited from an
  enclosing `test.describe('…', { tag: … }, …)`, but the details object must be a literal — a
  by-reference object is reported `unverifiable` and **fails**.
- `@contract` is the default and needs no justification. `@characterization` additionally requires a
  `// @characterization: <the implementation fact it pins>` comment immediately above the
  declaration — the house style every guard in `tests/guards/` uses.
- `e2e/tests/guards/tags.spec.ts` is blocking and fails closed: any declaration carrying no
  recognised tag, both tags, or an unreadable details object fails the `guards` project.
  `KNOWN_UNVERIFIABLE` is empty and stays empty.

**Every test G15 adds is `@contract`** — a guard control, a frontend interaction and a body
assertion all assert client-observable behaviour — **except the contract-version guard (item 16),
which is `@characterization`**, because like every test in `tests/guards/` it asserts a fact about
this repository's own source tree rather than about a running product. The inventory's tag column
below carries these, not a placeholder.

## Goal

One PR of small, individually verified test fixes. G15 changes no product code and adds no
capability: it removes ways for the existing suite to be **green for the wrong reason**, deepens
three frontend surfaces that are wired but not exercised, and writes down the fake provider's
contract so consumer goals can cite a version instead of a memory.

Its risk is scope creep. Its discipline is that the file list is fixed in advance, in this
document, and that every item was verified against the tree before being written — three of the
seven briefed items came back partly or wholly different from the claim, and this spec says so
rather than implementing the claim.

## What this buys the migration gate

The programme exists for one thing: to make this suite a trustworthy gate for extracting the
streaming relay out of the Django workers (`CLAUDE.md`, and `docs/adr/0002-e2e-test-taxonomy.md`'s
Context, which states it in the same words). G15 adds no coverage of a new flow. What it adds is
**confidence that the coverage already claimed is real**, which is a different and, at this point in
the programme, scarcer thing.

Four contributions, in descending weight:

1. **The nine guards make nine pins usable as gate signal.** A `test.fail()` whose premise sits
   inside the inversion is green whenever *anything* in its body throws. On a migration branch that
   is the worst possible shape: the extraction breaks a seeding path, an ingest, a route — the pin
   greens, and a regression in a pinned path is **invisible**. Nine of the twenty pins are in that
   state today, and three of them are the only test in their file, so nothing else in the file
   would catch the breakage either. Guarding them converts nine silent passes into nine assertions
   that mean what they say. Row 7's is worth naming twice: it pins a *non-disclosure* property
   (issue [#89](https://github.com/D10Scot/Dispatcharr/issues/89)), and a hollow green there claims
   a security property nobody tested.
2. **The body assertions make the harness's own proofs discriminating.** `api-fixture.spec.ts` and
   `authorization.spec.ts` prove that authentication and the user-level matrix work — the two
   things every other test in the suite silently assumes. Both currently assert a status and
   nothing else. A relay extraction that moved a route under the SPA catch-all would answer 200
   with `index.html` and both would stay green, and every downstream test's failure would then be
   blamed on the feature rather than the harness. The assertions in D11 close that.
3. **`CONTRACT.md` gives the provider a citable behaviour set.** The extraction's own tests will
   lean on `e2e-upstream` exactly as G4–G10 do, and the non-guarantees — no calendar validation, no
   time-addressable archive — are the ones a new goal will otherwise rediscover by writing a test
   that passes for the wrong reason. A version a spec can cite is cheaper than a memory a reviewer
   has to hold.
4. **The three frontend interactions are regression coverage only.** Stats, Guide and Backups are
   client surfaces that the extraction does not move. They are worth having, and they are the part
   of G15 the migration gate would least miss.

**If the wave runs long, land in this order:** the guards first (Tasks 2–10), because they are the
whole migration argument; then Task 13, the body assertions; then Task 15, the contract and
`COVERAGE.md`. Tasks 11 and 12 are two-line assertion strengthenings and can ride with any of them.
**The three frontend interactions (Task 14) go last** and are the only part of this goal that can be
dropped to a follow-up without weakening the gate.

## What changed against the brief

Verification first, implementation second. Three corrections and one refutation:

| Briefed item | Verified as |
|---|---|
| "`expectWellFormedXml` in `xc-output.spec.ts` — the one-line fix the disposition claims" | **Two lines, not one.** `expectWellFormedXml(page, xml)` needs a `Page`; the target test declares `async ({ seed, request })` and has no browser context. The change is the call *plus* adding `adminPage` to the fixture destructuring. Cheap, but not a one-liner — and the difference matters, because it is what makes a request-only test open a browser context (D4) |
| "The two residual first-byte-only TS assertions … `catchup-path-layout.spec.ts` and one site in `catchup-cascade.spec.ts`" | **Exactly right, and both survived #113 and G11.** Re-verified at `45a33a4a`: `catchup-path-layout.spec.ts` still carries `expect(bytes[0]).toBe(0x47)` and does **not** import `expectTsAligned` (a two-line change); `catchup-cascade.spec.ts` still carries `expect((await streamClient.readPackets(20))[0]).toBe(0x47)` inside G8's original test, which #113 did not modify, but the file now **does** import `expectTsAligned` for #113's own tests (a one-line change). `grep -rn "0x47" e2e/tests` returns only these two assertions plus `contiguity.spec.ts`'s synthetic-packet *writer*, which is not an assertion |
| "Post-switch byte attribution … if the TS pattern can carry a per-stream marker" | **Yes, under the Proxy stream profile; no, under FFmpeg.** All three specs that would use it run Proxy. The full ruling, with the blocker for FFmpeg, is below |
| "`stats` 0 interactions, `guide` 1, `backups` 1, `users` 16, `dvr` 15, `connect` 12, `plugins` 8" | **Verified, one off by one.** Counting direct `.click(` / `.fill(` / `setInputFiles(` / `.selectOption(` / `.press(` calls in each spec file: `users` 16, `dvr` 15, `connect` 12, **`plugins` 9** (not 8), `logos` 4, `settings` 4, `guide` 1, `backups` 1, `stats` 0, `render` 0, `pageerrors-enforcement` 0. The metric excludes clicks inside `gotoSurface`, which every frontend spec performs; that is the right exclusion, since a sidebar click is navigation, not the surface's own behaviour |
| "Audit **every** `test.fail()`; #15 and #82 are confirmed instances" | **Both confirmed.** **Twenty sites, all on `main`** — seventeen at `cf95410e`, plus three that #113 brought, and **still exactly twenty at `45a33a4a`** after G11 re-tagged every declaration in the suite. **Nine need a guard, eleven are already safe.** Full table below, one row per site |
| "Status-only assertions in `api-fixture` / `authorization`" | Four tests, four status-only assertions. **Two are worth a body assertion, two are legitimately status-only.** Table below |
| "`e2e-upstream` sits at `1.0.0` with no contract document" | Correct, and the version is **purely documentary today** — the provider image is rebuilt from source in the same commit on every CI run and every local `scripts/e2e_up.sh`, tagged `:local`. Nothing pins a version, so a version can never be *stale*, only *uncited*. That changes what the contract doc is for (D9) |

## Verified facts this design rests on

Every row re-read at `45a33a4a`. Rows first established at `cf95410e` and re-checked at `76db0332`
were re-checked again against G11's tip rather than carried forward on trust. G11 changed no product
code, so every `apps/`, `core/`, `dispatcharr/` and `frontend/` citation holds at all three commits;
what G11 did change is the shape of every test declaration in `e2e/tests/`, which is why the pin
count and the audit table were re-derived rather than trusted.

| Fact | Source | Consequence |
|---|---|---|
| Playwright's `test.fail(title, body)` inverts the whole body: it passes when **anything** in it fails, a fixture error and a `TypeError` included | Playwright API docs, `test.fail()` | A pin whose premise sits inside its own body can be green for the wrong reason. This is the defect the goal exists to remove |
| The fix pattern already in the tree: move the premise into a **non-inverted sibling test in the same file** | `8386825c` (G9: `vod-range.spec.ts`, `vod-stream.spec.ts`, `xc-vod-catalogue.spec.ts`), `c1858c42` (G10: `catchup-proxy-mode.spec.ts`) | `c1858c42`'s message is the standard: a control elsewhere in the suite is not enough — *"Add a standalone, non-inverted test in this file (not just the pre-existing corroboration at `tests/seeded/output-authorization.spec.ts`)"* |
| `8386825c` left `seedVodMovie(...)` itself inside the inverted body and still counts as fixed | `vod-range.spec.ts`, "an unsatisfiable Range on a fresh session is 416, not 500" | The practical standard is not "nothing but the assertion is inside" — it is **"every premise is exercised, in the same shape, by a non-inverted assertion in the same file."** That is the rubric this audit applies |
| `expectTsAligned(buffer)` asserts the buffer is a whole number of 188-byte packets **and** carries `0x47` at every packet boundary | `e2e/fixtures/stream-client.ts:expectTsAligned` | A drop-in for `bytes[0] === 0x47` wherever the read is `readPackets(N)`, which always returns whole packets |
| `expectWellFormedXml(page, xml)` runs `new DOMParser().parseFromString(source, 'application/xml')` inside the browser and asserts no `parsererror` node | `e2e/fixtures/parse.ts:expectWellFormedXml` | It needs a `Page`. `adminPage` sitting at `about:blank` is a valid context, which is how `output-epg.spec.ts` and `hdhr.spec.ts` call it |
| `parseXmltv` is a regex reader that guards only on the substring `<tv` and would *"happily extract elements from a document with an unclosed root"* | `e2e/fixtures/parse.ts:parseXmltv`, and the doc comment on `expectWellFormedXml` | `parseXmltv` **stays shallow**. Its own comment says not to tighten it without a test proving real Dispatcharr output still parses. G15 adds the strict check beside it, never inside it |
| `xc-output.spec.ts`'s XMLTV test is `test('xmltv.php renders a guide for its user', async ({ seed, request })` | `e2e/tests/seeded/xc-output.spec.ts` | No `page` fixture. See D4 |
| The provider serves **one** looping TS asset, built once at image-build time, identical for every scenario and every channel: fixed PIDs (`-mpegts_start_pid 0x100 -streamid 0:256 -streamid 1:257`), a burned-in frame counter that *"is a human debugging aid only … no test asserts on it"* | `e2e-upstream/scripts/make-asset.sh`; `e2e-upstream/src/asset.ts:loadAsset` | **Nothing in the bytes identifies which stream served them today.** This is the whole of the marker question |
| Every connection already runs every packet through a per-connection rewriter that **copies** the packet and rewrites continuity counters, PCR, PTS and DTS | `e2e-upstream/src/ts-loop.ts:LoopRewriter.rewrite` | A marker needs no new copy and no new asset — the injection point exists |
| The three failover specs all select the **locked Proxy** stream profile | `failover-dead-air.spec.ts`, `failover-connect-failure.spec.ts`, `mid-stream-switch.spec.ts`, each `await lockedProfile(api, 'Proxy')` | The bytes those tests read are raw provider bytes, realigned to 188 and ring-buffered. Nothing rewrites them |
| `failover-buffering.spec.ts` uses `seed.streamProfile()` (an ffmpeg profile) because *"the buffering detector parses ffmpeg's stderr"* | `e2e/tests/streaming-failover/failover-buffering.spec.ts` | The one failover spec a marker cannot serve |
| The locked FFmpeg profile's parameters are `-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1` | `core/migrations/0006_set_locked_stream_profiles.py` | Default stream selection: one video, one audio. A third elementary stream, a private-data PID, or a PID absent from the PMT is **not mapped and not emitted**. The mpegts muxer also rewrites PAT/PMT/SDT and renumbers continuity counters |
| `failover-dead-air.spec.ts` already asserts control-plane identity — `before.stream_id === streams[0].id`, then polls to `streams[1].id` | `e2e/tests/streaming-failover/failover-dead-air.spec.ts` | The gap is narrow and specific: the *bytes* read after the switch are asserted aligned and are never attributed |
| `e2e-upstream/package.json` declares `"version": "1.0.0"`. The image is built from source on every run (`docker build -f e2e-upstream/Dockerfile -t dispatcharr-e2e-upstream:local e2e-upstream`) in `e2e-tests.yml`, `lifecycle-tests.yml` and `scripts/e2e_up.sh`; the server exposes no `/version`, `/health` or info route | `e2e-upstream/package.json`; `.github/workflows/e2e-tests.yml`; `scripts/e2e_up.sh`; `e2e-upstream/src/server.ts` route table | Provider and consumers always ship from one commit. The version cannot drift — so it is a **citable name for a behaviour set**, not a compatibility negotiation. D9 |
| `e2e-upstream/README.md` already documents the control API, XC scenario fields, the fault catalogue, catch-up, pacing, the TS asset and the VOD asset | `e2e-upstream/README.md`, section headings | The contract doc must not restate the README. It states *guarantees, non-guarantees and a version*, and links | 
| G11 deleted `quarantine.spec.ts` and replaced its role with the `guards` Playwright project: `e2e/tests/guards/capabilities.spec.ts` and its four siblings, sharing `e2e/tests/guards/ast.ts` (which exports `E2E_ROOT`, `REPO_ROOT`, `ROOTS`, `findTestCalls`, `listSpecFiles`, `readSpec`, `readTags`) and `allowlist.ts` | `e2e/tests/guards/`; `e2e/playwright.config.ts`, project `guards` | A version claim can be **enforced** from a test that runs with no container, no browser and no fixtures, in ~1s. This is where item 16's guard goes. D10 |
| The `guards` project runs `testDir: './tests/guards'` with `workers: 1`, `fullyParallel: false`, no `dependencies` and no fixtures, and has **its own CI job** rather than a matrix row — "the only project here that needs no running instance" | `e2e/playwright.config.ts`, the `guards` project comment; `.github/workflows/e2e-tests.yml` | Adding a test to `tests/guards/` adds no project and no workflow change, so **D12 still holds**. Its imports come from `@playwright/test` and `./ast`, not from `'../../fixtures'` |
| `capabilities.spec.ts` scans `tests/`, `fixtures/` and `setup/` and **skips `tests/guards/`** — "this directory's own source names every marker it polices" | `e2e/tests/guards/capabilities.spec.ts:usersOf` | A guard reading `e2e-upstream/` paths from disk cannot trip `CONTAINER_INTROSPECTION` by naming one |
| The `frontend` project's Stats page exposes: a "Refresh Now" `Button`, a "Refresh Interval (seconds)" `NumberInput`, and per-connection card actions | `frontend/src/pages/Stats.jsx:StatsPage`, `:Connections`; `frontend/src/components/cards/StreamConnectionCard.jsx` | Real interactions exist. Their addressability does not — see D7 |
| Every Stats card action is a `Tooltip`-wrapped icon-only `ActionIcon`: "Stop Channel", "Disconnect client", "Switch to another stream source", "Preview Channel" | `StreamConnectionCard.jsx` | Mantine's `Tooltip` contributes `aria-describedby`, which does **not** compute an accessible name. Same class as [#73](https://github.com/D10Scot/Dispatcharr/issues/73) |
| Every Backups **row** action is likewise an unlabelled `Tooltip`+`ActionIcon`, and the three are adjacent: Download, **Restore**, Delete | `frontend/src/components/backups/BackupManager.jsx:RowActions` | A positional locator that drifts by one clicks **Restore**, which replaces the database under every parallel worker. D8 |
| The Backups **toolbar** buttons carry visible text: "Upload", "Refresh", "Create Backup" | `BackupManager.jsx` | Addressable by `getByRole('button', { name })` today. This is what makes a backups interaction test possible at all |
| Backups routes: `POST /api/backups/upload/`, `DELETE /api/backups/<filename>/delete/`, `POST /api/backups/<filename>/restore/`, `GET …/download-token/`, `GET …/download/` | `apps/backups/api_urls.py` | Upload has an API surface a test can verify against |
| Guide exposes a "Search channels..." input (used today), "Filter by group" and "Filter by profile" selects, a "Clear filters" button, a "Jump to current time" icon button, and a programme click handler | `frontend/src/pages/Guide.jsx` | Three addressable controls beyond the one already used |

## The guard rubric

Applied uniformly in the audit below. A `test.fail()` site is **already safe** only if all three hold:

1. **Seed premise.** The same seeding shape — same helper, same field set — is exercised by a
   non-inverted assertion **in the same spec file**.
2. **Transport premise.** The response the inverted body reads is proven reachable and parseable
   by a non-inverted assertion in the same file, on the same route. A 403, a 500 or an HTML error
   page must not be able to satisfy the inversion.
3. **Discriminating assertion.** The inverted body's final `expect` is the only plausible failure
   — no unguarded `.json()` on an unproven body, no unguarded fixture call whose failure is
   indistinguishable from the defect.

Two things this rubric deliberately does **not** require, because `8386825c` did not:

- That the seed call physically sit outside the inverted body. It may sit inside, provided a
  non-inverted sibling proves the same call works.
- That corroboration live outside the file. It must live **inside** it — `c1858c42`'s standard.

**A `--reporter=json` note in a comment is not a guard.** Four sites carry a comment saying the
author verified by hand which assertion the pin fails at, and instructing the next editor to
re-verify the same way. That is a good comment and a decayed guard: nothing re-runs it. Where the
rubric is otherwise satisfied the comment stays and the site is marked safe; where it is the
*only* thing standing between the pin and a hollow green, the site needs a guard.

## The `test.fail()` audit — every site, with a verdict

**The total, stated so it cannot be re-litigated:**

```
grep -rnE "^\s*test\.fail\(" e2e/tests | wc -l     # 20 at 45a33a4a (20 at 76db0332, 17 at cf95410e)
```

**The grep still holds after G11.** PR #124 re-tagged every declaration in the suite, and the tag is
an inline object literal inserted as the second argument — `test.fail('title', { tag: '@contract' },
async …)` — so every site still *begins* with `test.fail(` on its own line and the anchored pattern
matches all twenty. Four of the twenty are the multi-line form, where `test.fail(` sits alone on the
line and the title and tag follow on the next: `catchup-provider-timezone.spec.ts:181`,
`catchup-proxy-mode.spec.ts:216`, `output-m3u.spec.ts:164` and
`catchup-m3u-advertisement.spec.ts:55`. The pattern is line-anchored, not title-anchored, so both
shapes count.

Twenty sites across seventeen files — three in `vod-range.spec.ts`, two in `xc-vod-playback.spec.ts`,
and one each in fifteen further files. **The table below carries all twenty, numbered 1–20, every one
of them on `main`.** Rows 18–20 are the three #113 brought; rows 1–17 were measured at `cf95410e`.
Re-derived at `45a33a4a`, the per-file breakdown is byte-for-byte the one the table encodes: **no row
was added, removed or reassigned by G11.**

**Nine need a guard. Eleven are already safe.**

The suite-wide figures G11 was cross-checked against have moved, because G11 itself moved them.
At `45a33a4a`: **80 spec files** (75 outside `tests/guards/`, plus five guards — four new, and
`pageerrors-enforcement.spec.ts` moved in from `tests/frontend/`; `quarantine.spec.ts` deleted), and
**196 test declarations** (176 plain `test(` plus these 20 `test.fail(`) — the same 196 named in
`tags.spec.ts`'s own header. The pin count is the only one of the three this audit depends on, and
it did not move.

Rows 8, 9 and 10 are `vod-range.spec.ts`'s three; rows 11 and 12 are `xc-vod-playback.spec.ts`'s two.
Every other row is the sole pin in its file. Cross-check the table against the `grep` above before
treating this audit as complete — a twenty-first site would mean a pin landed after `45a33a4a`, which
has no verdict and no guard here. The plan's Task 1 Step 2 re-derives this count and stops if it
exceeds the table; that is not ceremony, it is how this drift was caught the first time, and it is
why the count was re-derived a third time after G11.

**The debt is entirely pre-G9, and rows 18–20 are the evidence.** All three pins #113 shipped are
already guarded to this document's rubric, and two of them carry a standalone non-inverted sibling
whose title literally begins *"row 8 premise:"* / *"row 13 premise:"*. The pattern G15 is backporting
is already the house standard for new work; what needs backporting is everything written before
`8386825c`.

| # | File · test title | Introduced | Premise inside the inverted body | Non-inverted sibling in the same file | Verdict |
|---|---|---|---|---|---|
| 1 | `seeded/m3u-ingest.spec.ts` · *M3UAccount.locked is not writable over the API* (#15) | G3 (#78) | `seed.m3uAccount()`; `account.locked === false`; `PATCH /api/m3u/accounts/<id>/` returning `ok()` | The file's four other tests exercise `seed.upstreamM3UAccount` and the wait helpers — **no test PATCHes an account, and none calls `seed.m3uAccount()` bare** | **NEEDS A GUARD.** Cheap. Add a non-inverted control that seeds the same account and round-trips a PATCH of a *writable* field (`name`), asserting the read-back. That proves seed + PATCH route, leaving only `locked` inside |
| 2 | `seeded/hdhr.spec.ts` · *hdhr lineup does not expose adult or above-level channels* (#82) | G5 (#88) | `seed.channel({ user_level: 10, is_adult: true })`; `/hdhr/lineup.json` returning parseable JSON | `hdhr lineup.json carries a seeded channel with a proxy URL` covers the route and a **plain** `seed.channel()`, but not the restricted field set | **NEEDS A GUARD.** Cheap. Add a non-inverted control seeding the identical restricted shape and asserting the round-trip (`user_level === 10`, `is_adult === true`). Rubric 1 then holds; rubric 2 already does |
| 3 | `seeded/xc-live.spec.ts` · *a profiled user sees the category of every channel it can list* (#85) | G5 (#88) | `seed.channelGroup()`, `seed.channel({ user_level: 1 })`, `seed.channelProfile()`, `seed.xcUser({ user_level: 1, channel_profiles: [...] })`, **and the premise assertion itself** — that `get_live_streams` lists the channel — all inside | `the XC live catalogue lists a seeded channel under its own category` is named in the comment as "the positive control", but it uses a `user_level: 0` channel and an unprofiled user. The differing field is exactly the one the defect turns on | **NEEDS A GUARD.** Promote the `get_live_streams` containment check into a non-inverted sibling using the **identical** four-seed setup. Zero login cost (`seed.xcUser` spends none) |
| 4 | `seeded/token-refresh-deleted-user.spec.ts` · *refreshing a deleted user's token returns 401, not 500* (#12) | G5 (#88) | `seed.user()`, `asUser(...)` (**one login out of three per minute**), `freshRefreshTokenForTest()`, and `DELETE /api/accounts/users/<id>/ === 204` | **None — this is the only test in the file.** The comment names the exact hazard: a cold-run 429 from `asUser` reads as an expected failure and the pin is hollow, "verified with `--reporter=json`" | **NEEDS A GUARD.** Add a non-inverted control that posts a **live** principal's refresh token to `/api/accounts/token/refresh/` and asserts 200 — zero login, via `PRINCIPALS`. That covers the route premise. The `asUser` 429 hazard is a harness cost and stays named in the comment (D2) |
| 5 | `streaming/hidden-channel-streamable.spec.ts` · *a channel a user cannot list is not streamable by that user* (#87) | G5 (#88) | `upstream.scenario`, `lockedProfile`, `seed.upstreamChannel({ channel: { user_level: 0, is_adult: true } })`, `seed.xcUser({ hide_adult_content: true })`, and the listing-absence premise | **None — the only test in the file.** It reasons carefully about `xcLiveStreams` asserting 200 before parsing, and about only a refusal setting `served = false`; both are good, and neither is a guard against the setup failing | **NEEDS A GUARD.** Add a non-inverted sibling with the same setup asserting the listing half: absent for the `hide_adult_content` user, present for an admin. Costs one more upstream scenario (~60s in the `streaming` project) |
| 6 | `streaming/vod-adult-streamable.spec.ts` · *an adult movie a user cannot list is not streamable by that user* (#110) | G9 (#112) | Whole VOD catalogue seed and the listing-absence premise. It **does** carry an in-body positive control (`toContain(controlMovie.id)`), and the comment's claim for it is correct as far as it goes: the absence assertion cannot pass on a listing that never worked | **None — the only test in the file** | **NEEDS A GUARD — the weakest of the nine, and the one verdict this audit had to adjudicate (see below).** The in-body positive control makes the *absence* assertion non-vacuous; it does nothing about the seed-and-ingest premise, because a throw anywhere in the body still greens the pin. The control is scoped to **seed plus listing only**, no streaming, and its cost (a second ~120s ingest) is the honest price of a single-test file |
| 7 | `streaming/vod-upstream-error.spec.ts` · *an upstream failure on the VOD stream route does not return the provider credential* | G9 (#112) | The local `seedVodMovie` helper (scenario → `seed.xcAccount` → `refresh-vod` → a 120s `waitFor.resource` on the ingest), the fault arm, and the error-response fetch | **None — the only test in the file** | **NEEDS A GUARD, and it is the one worth most.** The assertion is that a credential is *not* disclosed, so a hollow green claims a security property that was never tested. Its comment additionally makes a claim that does not hold: *"The fault is armed only after ingest completes, so a failure here can only be the streaming-error path."* An ingest that never completes fails `waitFor.resource` inside the inverted body, which greens the pin — the ordering does not help. Add a non-inverted sibling asserting the **happy** path on the same route, then arm the fault in the pin. **The defect is filed: [#89](https://github.com/D10Scot/Dispatcharr/issues/89)**, *"Provider credentials can reach an unauthenticated client in a 500 response body from the VOD proxy"*, opened 2026-08-30 after checking with the repository owner and labelled `ready-for-agent`. It supersedes the pin's "deliberately not filed" comment, which was written before the decision and is now wrong. **Do not open a second issue** — cite #89 |
| 8 | `streaming/vod-range.spec.ts` · *a provider that ignores Range still yields the requested bytes* (#66) | G9 (#112) | `seedVodMovie`, full-GET session establishment, a direct provider 206 read, **and `upstream.fault(scenario, 'range-unsupported')`** — which throws on a non-2xx control response | `Range and seek on the VOD proxy match the provider byte-for-byte` covers `seedVodMovie`, the full GET and a 206 range read on the same route. It does **not** arm `range-unsupported` | **NEEDS A GUARD**, narrowly. Add a non-inverted sibling that arms `range-unsupported` and asserts the **provider itself** ignores Range (direct fetch through `toControl`, 200 with the whole asset). Fast, no Dispatcharr involved, and it pins exactly the unguarded link |
| 9 | `streaming/vod-range.spec.ts` · *an unsatisfiable Range on a fresh session is 416, not 500* (#98) | G9 (#112), fixed by `8386825c` | `seedVodMovie` and the fresh-session GET | `Range and seek …` carries the established-session 416 control, moved there by `8386825c` **for this pin** | **ALREADY SAFE.** The exemplar. Its comment names the sibling and the reason |
| 10 | `streaming/vod-range.spec.ts` · *a suffix Range returns the tail of the file* (#64) | G9 (#112) | `seedVodMovie`, the full GET, a direct provider 200 read and a length equality | `Range and seek …` exercises `seedVodMovie`, the full GET, a 206 range read and a direct-provider byte comparison — the same shapes | **ALREADY SAFE.** Rubrics 1–3 hold. The residual (`direct.status === 200` on a plain fetch) is the same call the sibling makes with a Range and is accepted |
| 11 | `streaming/xc-vod-playback.spec.ts` · *wrong XC credentials against the movie route are a 401, not a 500* (#100) | G9 (#112) | VOD seed and the bad-credential request | `the root XC movie and series routes authenticate and deliver bytes by Dispatcharr primary key (G9 row 14)` — same seed helper, same routes, 200 asserted | **ALREADY SAFE.** Rubrics 1–3 hold |
| 12 | `streaming/xc-vod-playback.spec.ts` · *an unknown episode id on the XC series route is a 404, not a 500* (#99) | G9 (#112) | VOD seed and the unknown-id request | Same control as row 11 | **ALREADY SAFE** |
| 13 | `seeded/xc-auth.spec.ts` · *player_api.php does not distinguish an unknown user from a wrong password* (#84) | G5 (#88) | `seed.xcUser()`, and `expect(wrongPassword.status()).toBe(401)` — a control assertion sitting inside the inversion | `player_api.php rejects a wrong password` (a standalone non-inverted test asserting exactly that 401), plus `player_api.php returns a user_info / server_info envelope for valid credentials` for the seed | **ALREADY SAFE.** Both premises have non-inverted siblings in the same file. The inline `wrongPassword` assertion is redundant belt-and-braces, not the guard |
| 14 | `seeded/m3u-refresh-failure.spec.ts` · *a failed refresh keeps the HTTP-status-specific message* (#60) | G3 (#78) | Scenario, `not-found` fault, `seed.m3uAccount`, `waitForCreateTimeGroupRefreshToSettle`, `waitFor.m3uRefreshComplete`, terminal status `error` | `a 404 from the playlist leaves the account in error with no catalogue` performs the **identical** setup non-inverted and asserts the `error` status | **ALREADY SAFE.** The strongest sibling in the suite: same fault, same helpers, same terminal assertion |
| 15 | `seeded/output-m3u.spec.ts` · *a channel name containing a double quote still produces a well-formed EXTINF line* (#80) | G5 (#88) | `seed.channel()`, `PATCH /api/channels/channels/<id>/ { name }` → 200, the `/output/m3u` GET, and `parseM3u` finding the entry | `/output/m3u renders a parseable playlist with a well-formed proxy URL` covers seed, route, parse and `wellFormed`. **No sibling PATCHes a channel name** | **NEEDS A GUARD**, minimal. Add the rename round-trip (PATCH `name`, read back) to the existing non-inverted first test. One `expect`, no new test |
| 16 | `seeded/vod-ingest-fidelity.spec.ts` · *GET /api/vod/categories/ accepts an m3u_account filter* (#96) | G9 (#112) | `seedCatalogue`, and the unfiltered-list premise | `a VOD refresh creates one category row per declared category, enabled for that account` — named explicitly in the pin's own comment as the non-inverted guard | **ALREADY SAFE** |
| 17 | `seeded/xc-vod-catalogue.spec.ts` · *XC get_vod_info returns the advanced data the REST API returns (G9 row 20, defect)* (#97) | G9 (#112), guarded by `8386825c` | Catalogue seed and the provider-info premise | `the XC VOD actions answer a real catalogue with Dispatcharr identities, not the provider's (G9 row 9)` — `8386825c` added the non-inverted provider-info bitrate assertion **for this pin** | **ALREADY SAFE** |
| 18 | `streaming/catchup-proxy-mode.spec.ts` · *an adult channel a user cannot list is also refused on the catch-up path* (#95 — the row-8 `hide_adult_content` pin) | G10 (#113), guarded in-PR by `c1858c42` | The catch-up seed and the listing-absence premise | `row 8 premise: a Standard viewer with hide_adult_content cannot list an adult channel` — a standalone non-inverted test added by `c1858c42` for exactly this | **ALREADY SAFE.** The commit message states the standard this audit codified: *"Add a standalone, non-inverted test in this file (not just the pre-existing corroboration at `tests/seeded/output-authorization.spec.ts`)"* |
| 19 | `streaming/catchup-provider-timezone.spec.ts` · *a requested start keeps its seconds whatever the provider timezone is* (#111) | G10 (#113) | `seedCatchupChannelInZone(..., 'UTC')` and `(..., 'Europe/Brussels')`, the `catchup-layout-404 { layout: 'path' }` fault arm, the four-candidate walk, and the UTC control half | **Two**, both non-inverted, both in this file: `row 13 premise: under UTC, the colon-seconds PATH candidate preserves the requested seconds` (same helper, same fault, same fixed instant, same candidate index `[2]`, same `toHaveLength(4)`) covers the UTC half; `the provider server_info.timezone converts the requested start before it is sent` seeds `'Europe/Brussels'` non-inverted and covers the other zone | **ALREADY SAFE**, and the strongest guard in the suite. Both zones' seeds and the fault arm are exercised un-inverted, and the premise test's own comment states the rubric: *"no assertion in that body — including the 'UTC control' — can guard its own premise"* |
| 20 | `seeded/catchup-m3u-advertisement.spec.ts` · *the generated M3U advertises catch-up for a catch-up channel* (#94) | G10 (#113) | `seed.channel({ is_catchup: true, catchup_days: 7 })`, the `/output/m3u` fetch and the uuid lookup | `a catch-up channel appears in the generated M3U (premise guard for the pin below)` — identical seed shape, identical route including the `m3uQuery()` cache-buster, identical uuid-based locator, asserting 200 and the entry defined. Plus `the XC catalogue does advertise the same channel as catch-up` for the asymmetry | **ALREADY SAFE.** Rubrics 1–3 all hold; the guard even avoids a title-based locator because #80's quote-escaping defect can corrupt `title`, which would let "channel not found" read as the catch-up omission |

Rows 1, 2, 3, 4, 5, 6, 7, 8 and 15 need work — **nine changes across nine files**, of which two
(rows 1 and 15) are single-assertion edits and one (row 8) is a fast provider-only control.

### The two verdicts that were contested, adjudicated

This audit was run twice — once directly against the tree, once by an independent reviewer — and the
two agreed on eighteen of twenty sites. Both contested rows are recorded here so the reasoning is
inspectable rather than a matter of whose count won.

**`output-m3u.spec.ts` (#80) — not contested; a summary-line error made it look contested.** Both
passes marked it **needs a guard** (row 15). An earlier draft of this document's summary sentence
said "six need a guard" while the table said nine, and a reader reconciling the prose rather than the
table would conclude row 15 had been dropped. It never was: it is row 15, it is Task 10 of the plan,
and `output-m3u.spec.ts` is in the plan's file-structure table. **The summary line was wrong and is
now derived from the table, with the `grep` that produces the total stated above it.**

**`vod-adult-streamable.spec.ts` (#110) — genuinely contested; resolved as NEEDS A GUARD.** The
reviewer marked it safe on the strength of the pin's *in-body* positive control
(`expect(listed).toContain(controlMovie.id)`), which does real work: it means the absence assertion
cannot pass on a listing that never returned anything. That reasoning is correct and is preserved in
the row above. It is not sufficient, for one reason and one consistency check:

- **The reason.** The in-body control is inside the inversion. `test.fail()` is satisfied by any
  failure in the body, so if `upstream.scenario(...)`, `seed.xcAccount(...)`, the `refresh-vod` call
  or the 120-second ingest wait throws, the positive control never executes and the pin greens. What
  the control proves is conditional on the body reaching it; nothing proves the body reaches it.
- **The consistency check.** `hidden-channel-streamable.spec.ts` (row 5) and
  `vod-upstream-error.spec.ts` (row 7) are the same shape — a single `test.fail()` alone in its file,
  with its whole setup inside the inversion — and both are marked needs-a-guard by both passes.
  Marking row 6 safe would mean the rubric's first condition ("the same seeding shape is exercised by
  a non-inverted assertion **in the same file**") is applied to two files and waived for a third, on
  the strength of an assertion that sits on the wrong side of the inversion. **A rubric applied
  inconsistently is worse than a stricter rubric**, and the goal exists to make premises structurally
  guarded rather than argued.

It remains the weakest of the nine — the cheapest to argue away and the one whose guard buys least —
and the row and the plan's Task 7 both say so, along with its cost (a second ~120s ingest).

Three sites are `test.fail()` **references in comments**, not call sites, and are excluded:
`dvr.spec.ts` (a comment explaining why the row-action test is *not* a pin — G13's file, untouched
by G15), `output-authorization.spec.ts` (a comment contrasting its passing assertions with the pins
elsewhere), and the three fixture doc comments in `stream-client.ts`, `page-errors.ts` and
`index.ts`. Verified by reading each.

## The per-stream TS marker ruling

**VERDICT: YES — under the Proxy stream profile, and only under it. G15 does not build it.**

### Why yes, mechanically

The bytes a client reads under the locked **Proxy** profile are the provider's own bytes:
`apps/proxy/live_proxy` reads raw HTTP into the ring buffer, realigns to 188-byte boundaries
(`input/buffer.py`) and serves them. No subprocess, no remux, no PID remapping. All three specs
that would use a marker — `failover-dead-air.spec.ts`, `failover-connect-failure.spec.ts`,
`mid-stream-switch.spec.ts` — select `lockedProfile(api, 'Proxy')`.

The provider already copies and rewrites **every packet on every connection**
(`LoopRewriter.rewrite` in `e2e-upstream/src/ts-loop.ts`, which renumbers continuity counters and
offsets PCR/PTS/DTS). The injection point exists. The cheapest marker that a test can read from
raw bytes with no decoder and no ffprobe: **a dedicated marker PID** — one 188-byte packet every
N packets on, say, PID `0x1FE`, payload `"E2E"` plus the scenario channel id as four ASCII digits.
A test scans on 188-byte boundaries for `pidOf(packet) === MARKER_PID` and reads the id. Two
functions, both of which have counterparts in `e2e-upstream/src/ts.ts` (`pidOf`, `payloadOffset`)
and in the suite's own TS helpers (`videoPidOf`, already exported from `e2e/fixtures`).

### Why no, under FFmpeg

The locked FFmpeg profile is `-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`
(`core/migrations/0006_set_locked_stream_profiles.py`). Default stream selection maps one video and
one audio stream and nothing else; a marker PID that is not a mapped elementary stream is dropped,
and one that *is* declared in the PMT would need `-copy_unknown` and a `-map` the profile does not
carry. The mpegts muxer additionally rewrites PAT/PMT/SDT and renumbers continuity counters, so
`program_number`, `service_id` and PID-based markers are all rewritten. `failover-buffering.spec.ts`
is the one failover spec on an ffmpeg profile — deliberately, because the buffering detector parses
ffmpeg's stderr — and it therefore **cannot** be given byte attribution by any mechanism in this
family. Nothing short of a marker that survives a remux (a watermark in the *video*, requiring a
decoder in the test) reaches it, and that is out of proportion to the finding.

### Why G15 does not build it

Three reasons, in descending weight:

1. **It is a provider change, and G15's brief is a fixed file list that does not include
   `e2e-upstream/src/`.** Adding a marker means editing `LoopRewriter` (or `stream.ts`), extending
   the scenario type so a channel can declare its marker id, adding a reader to `e2e/fixtures`, and
   rebuilding the provider image. That is a G2-class change to a shipped build, not a small
   verified fix, and it is exactly the scope creep this goal is defined to avoid.
2. **The control-plane assertion is already there and is not weak.** `failover-dead-air.spec.ts`
   polls `readChannelStatus(...).stream_id` to `streams[1].id`. The residual risk a marker closes
   is narrow and specific: that Dispatcharr updates the control plane to stream B while continuing
   to serve stream A's bytes. Real, worth closing eventually, and not the same order of risk as a
   pin that is green for the wrong reason.
3. **It changes the provider's contract, which item 7 is in the middle of writing down.** Landing a
   byte-format change in the same PR that first records the byte format is the wrong order.

**Recorded for the goal that does build it.** The mechanism above is viable and cheap; the blocker
is scope, not feasibility. It belongs with whichever goal next owns `e2e-upstream/` — it is a
provider capability plus one fixture reader plus three assertions, and this ruling is the evidence
that it will work. **G15 files no issue for this**: it is a test-suite improvement, not a product
defect. It is recorded as a `COVERAGE.md` **Gap** row (D6) so it is not re-derived a third time.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| **D1** | **The guard mechanism is the non-inverted sibling test in the same file** (`c1858c42`'s standard), applied against the three-part rubric above. Each control seeds its own fixtures | It is proven, it is already in the tree twice, and it survives an editor who does not read comments. G15 introduces no new pattern for a goal whose whole job is consolidation. **Rejected: a shared `beforeAll`/`describe.serial` fixture** — a `beforeAll` failure is not inverted, so it would guard the premise *and* halve the cost of the three expensive `streaming` controls. `vod-ingest-fidelity.spec.ts`'s header rejects exactly this, for exactly the right reason: *"not shared as a single seeded fixture — because `test.fail()` in Step 4 must not depend on Step 2/3 having already run in the same test, and a shared `beforeEach` would hide that dependency."* No spec in the tree uses `beforeAll`. Buying a guard by introducing the coupling the suite has explicitly refused is a bad trade; the duplicated seed cost is paid instead, and named in Risks |
| **D2** | **Rejected: converting pins to `test('…')` plus an in-body `test.fail()`.** Playwright supports `test.fail()` with no arguments inside a body, and it would make the premise structurally un-invertible with no sibling and no extra seed — but the docs **recommend against it** and **do not state** whether an error thrown before the call is reported as a real failure. A guard mechanism whose central property is undocumented is not a guard | The whole goal is removing tests that are green for reasons nobody verified. Adopting an unverified mechanism to do it would be self-refuting. Task 1 spikes it anyway and records the result in the plan; if the spike is positive, a **later** goal may adopt it — G15 does not, whatever the spike says. That keeps this PR's outcome independent of an experiment |
| **D3** | **A `--reporter=json` comment is not a guard, and is not deleted either** | Four sites carry one. Where the rubric is satisfied it is useful documentation of *which* assertion the pin fails at; where it is not, the sibling test replaces its load-bearing role and the comment is rewritten to point at the sibling |
| **D4** | **`xc-output.spec.ts`'s XMLTV test gains the `adminPage` fixture and one `expectWellFormedXml` call.** `parseXmltv` is not touched | Two lines, and the second one is the point: this is what makes a request-only test open a browser context. `output-epg.spec.ts` and `hdhr.spec.ts` already pay the same cost for the same check, and `adminPage` reuses `storageState` so it spends no login. `parseXmltv`'s own comment forbids tightening it |
| **D5** | **The two residual first-byte TS assertions are replaced with `expectTsAligned`** | Both reads are `readPackets(20)`, which returns whole packets, so `expectTsAligned` is a drop-in that additionally checks the sync byte at every 188-byte boundary. At `45a33a4a` the import already exists in `catchup-cascade.spec.ts` (a one-line change) and does not in `catchup-path-layout.spec.ts` (two). The former merge-order dependency on #113 is **discharged** |
| **D6** | **The per-stream marker is ruled feasible-under-Proxy, not built, and recorded as a `COVERAGE.md` Gap row** | See the ruling. A Gap row is how this programme records a resolved finding with no further action here — the convention `COVERAGE.md`'s own header states |
| **D7** | **The Stats interaction test drives "Refresh Now", not "Stop Channel"** | "Refresh Now" is a `Button` with visible text and is addressable today. Every per-connection action is a `Tooltip`-wrapped icon-only `ActionIcon` with no accessible name — the same defect as [#73](https://github.com/D10Scot/Dispatcharr/issues/73), on a different surface. G15 **files that** (candidate defect **C1**) and does not write a test that depends on a brittle positional locator |
| **D8** | **No backups test clicks a row action, and no backups test restores.** The backups interaction is **Upload**, via the text-labelled toolbar button | Download / **Restore** / Delete are three adjacent unlabelled icon buttons. A positional locator that drifts by one clicks Restore, which replaces the database under every parallel worker in the container. That is not a risk worth taking for a delete test, and restore is **G12's** on an isolated instance regardless (the `COVERAGE.md` Lifecycle row already says so). C1 covers the addressability |
| **D9** | **`e2e-upstream/CONTRACT.md`, at the provider's root, versioned `1.1.0` on landing** | The README is already the how-to (nine sections, control API through VOD asset) and the contract must not restate it. A sibling file is greppable from the package a consumer is reading, unlike a `docs/` path, and it keeps the provider's own documentation together. `1.1.0` because writing the contract down adds no behaviour and breaks nothing, and because bumping *something* on landing proves the bump procedure works |
| **D10** | **The version is made enforceable by a source-scan guard, not by a `/version` endpoint — and it goes in `e2e/tests/guards/upstream-contract.spec.ts`, not `tests/seeded/`.** It imports `REPO_ROOT` from `./ast` rather than hand-rolling a `path.resolve(__dirname, '../..')`, is tagged **`@characterization`** with the guards' shared comment style, and is listed in `COVERAGE.md`'s `## Guards (G11)` table with the mutation that proved it fails | An endpoint is a provider runtime change — out of G15's file list, and unnecessary: provider and consumers always ship from one commit, so there is nothing to negotiate at run time. What can actually rot is `CONTRACT.md` disagreeing with `package.json`. **G11 deleted `quarantine.spec.ts` and generalised its role into the `guards` project**, which is exactly this shape of test: repository source read from disk, no container, no browser, no fixtures, ~1s, its own CI job. Putting it in `tests/seeded/` instead would make a text-file comparison wait on a booted instance and four shared workers, for nothing. `@characterization` because it asserts a fact about this repository's own source tree, like every other test in that directory |
| **D11** | **Body assertions are added to two of the four status-only tests, and the other two stay status-only with a comment saying why** | A 403 whose body is DRF's stock `{"detail": …}` carries no signal. A 200 that could be an SPA `index.html`, or a list that could be empty, carries a lot. See the table |
| **D12** | **G15 edits no `.github/workflows/**` file and no `playwright.config.ts` project** — and this **still holds after D10 moved the contract guard into `tests/guards/`**, because G11 already created the `guards` project and its CI job. A new file under `testDir: './tests/guards'` is picked up by both with no edit to either | It adds no project and no CI job. Every new test lands in an existing project. This keeps G15 clear of the zizmor ratchet entirely and of G11's and G12's CI work. The one thing to check on landing is that the `guards` job is green, since it now runs one more test than G11 left it running |

## Real interactions for `stats`, `guide` and `backups`

`render.spec.ts` stays smoke-only — settled, not revisited. The residue verified above is that
three surfaces have a wiring proof and no behaviour proof. Each gets **one** interaction test whose
effect is observable through the API, not only in the DOM.

**Shared-instance discipline.** All three run in the `frontend` project against the shared seeded
container. Roadmap rule 4 binds: no global count, no unfiltered list, locate your own rows by the
name `seed` generated. `backups.spec.ts` is the documented exception — its module comment explains
why it is pinned to file-level parallelism and why its before/after set difference is sound —
and any new test in that file inherits the constraint, so **the new backups test goes in the same
file**, not a new one.

| Surface | New test | Why it is real signal | Selector |
|---|---|---|---|
| **Stats** | *the Refresh Now button re-reads the connection list* — open a stream (as today), assert the connection appears, close the client, click **Refresh Now**, assert the connection is gone from `stats-connections` faster than the 5s poll would have removed it | Today's test proves the page renders live data. This proves the page's own control drives a re-fetch — the wiring across `api.js` → `StatsUtils.fetchAllConnectionStats` → the grid — which the passive poll would produce anyway and therefore does not prove | `getByRole('button', { name: 'Refresh Now' })` |
| **Guide** | *filtering by Channel Profile narrows the grid to that profile's channels* — seed two channels, put one in a fresh Channel Profile, select it in "Filter by profile", assert the member is present and the non-member absent | The existing test drives the search box, which filters both server-side and client-side, so it proves reachability. Profile filtering is a different mechanism and the one that carries authorization semantics elsewhere in the product | `getByPlaceholder('Filter by profile')`, then the option by its seeded name |
| **Backups** | *an uploaded archive re-appears in the list and downloads back byte-identical* — create an archive (as today), download it, click **Upload**, submit the same bytes under a new name, assert it appears in the list and its download is byte-identical to what was uploaded | Exercises `POST /api/backups/upload/`, which no test touches. Byte-identity is the assertion — a size check would pass a truncated write, exactly as `logo-upload.spec.ts` reasons about `Buffer.equals` | `getByRole('button', { name: 'Upload' })`; the modal's own submit button |

Both new archives are registered in the existing `namesToDeleteAfterEach` set, so the file's
established `afterEach` cleans them up unchanged.

**Not written, and why:** a Stats "Stop Channel" / "Disconnect client" test (D7 — no accessible
name); a Backups delete-or-restore-from-the-row test (D8 — no accessible name, and the adjacent
control is Restore); a Guide programme-click → record flow (**G13 owns DVR execution**; creating a
`Recording` row from the Guide is that goal's subject, not this one's).

## `expectWellFormedXml` in `xc-output.spec.ts`

One test, two lines. `test('xmltv.php renders a guide for its user', async ({ seed, request })`
becomes `async ({ seed, request, adminPage })`, and one `await expectWellFormedXml(adminPage, body)`
joins the existing assertions on the parsed guide. The import list gains `expectWellFormedXml`.

`parseXmltv` **stays shallow**, per its own comment: *"Deliberately a substring test, not an
anchored root check … Do not 'tighten' this without a test proving real Dispatcharr output still
parses."* The strict check goes beside it, never inside it. This is the same division
`output-epg.spec.ts` already uses — parse for content, `DOMParser` for validity.

## The two residual TS assertions, and the merge order

| File | Site | State at `45a33a4a` | Change |
|---|---|---|---|
| `streaming/catchup-path-layout.spec.ts` | `expect(bytes[0]).toBe(0x47)`, in *the root XC PATH route streams and records the layout it was asked for* | Present, untouched by #113. The file imports only `test, expect` from `'../../fixtures'` | `expectTsAligned(bytes)`, plus the import — **2 lines** |
| `streaming/catchup-cascade.spec.ts` | `expect((await streamClient.readPackets(20))[0]).toBe(0x47)`, in G8's *the candidate cascade falls through to the QUERY layout when PATH 404s* | Present and unmodified by #113, but the file now imports `expectTsAligned` for #113's own five tests | `expectTsAligned(await streamClient.readPackets(20))` — **1 line** |

**Both merge-order dependencies are discharged.** #113 merged as `76db0332` and G11 as `4211cbb7` /
`7a408c2b`; the two sites survive both, at `catchup-cascade.spec.ts:62` and
`catchup-path-layout.spec.ts:49`. #113 added five tests to `catchup-cascade.spec.ts` and left G8's
test — the one carrying the residual assertion — untouched, and G11 only added a tag to it, so both
changes are written against `main` directly and #113 is what established `expectTsAligned` as that
file's convention. Both replacements are verified as drop-ins: `readPackets(N)` returns whole
188-byte packets, which is what `expectTsAligned` requires. The only other `0x47` in `e2e/tests` is
`contiguity.spec.ts`'s synthetic-packet *writer*, which is not an assertion and is not touched.

## The status-only assertion audit

Four tests, four status-only assertions. Two get a body assertion; two do not.

| File · test | Asserts | Body for that status | Verdict |
|---|---|---|---|
| `api-fixture.spec.ts` · *api fixture authenticates against a protected endpoint* | `GET /api/channels/channels/` → `status() === 200` | A DRF list (paginated or array) of `Channel` rows | **ADD A BODY ASSERTION.** `dispatcharr/urls.py` mounts the SPA catch-all after the API routes; a routing regression that shadowed `/api/channels/channels/` would answer **200 with `index.html`** and this test would pass. Assert the body parses as JSON and is a list/paginated shape — `api.json<...>(res, …)` already throws on a non-JSON body, so the assertion is one call, not a new helper |
| `api-fixture.spec.ts` · *api fixture recovers from an expired access token* | after `expireAccessTokenForTest()`, `GET /api/channels/channels/` → `status() === 200` | Same | **ADD TWO ASSERTIONS, one of them not a body one.** The signal this test claims is that the *refresh path ran*. If `/api/channels/channels/` ever became `AllowAny`, a 200 would prove nothing at all. Assert, in the same test with the built-in `request` fixture, that the **same endpoint answers 401 with no credentials** — that is what makes the 200 evidence of a valid token, and it needs no new fixture hook (`ApiClient` deliberately exposes no raw access-token getter; `freshAccessToken()` refreshes as a side effect and so cannot be used to observe one). Add the same JSON-shape assertion as the row above for the routing case |
| `authorization.spec.ts` · *a {streamer,standard} (user_level N) cannot list users* | `GET /api/accounts/users/` → `status() === 403` | DRF's stock `{"detail": "You do not have permission to perform this action."}` | **LEGITIMATELY STATUS-ONLY.** The detail string is DRF-internal and asserting it pins a framework message, not product behaviour. More importantly the test is **already correctly guarded**: it establishes identity through `users/me` first, precisely so the 403 has one remaining explanation. Add a comment recording that the status-only shape is deliberate |
| `authorization.spec.ts` · *an admin can list users* | `GET /api/accounts/users/` → `status() === 200` | A list of `User` rows | **ADD A BODY ASSERTION.** This is the positive half of an authorization matrix asserting nothing about what was authorized. A filter regression returning 200 with an empty list passes today. Assert the body contains the three fixed `PRINCIPALS` usernames — containment, not a count, so roadmap rule 4 holds on a shared instance |

**Relation to the known product defects.** None of the four sits next to a `CLAUDE.md`-catalogued
authorization defect: the copy-pasted channel-authorization filter, `output/views.py`'s
`"channels__user_level": 0`, and the missing `hide_adult_content` in `live_proxy`, `timeshift` and
`hdhr` are all on **channel** surfaces, and are already pinned by `output-authorization.spec.ts`,
`hidden-channel-streamable.spec.ts`, `hdhr.spec.ts` and `catchup-proxy-mode.spec.ts`.
These two files are the harness's own fixture proofs and the user-level matrix; the body assertions
above buy routing and filtering signal, not a new defect pin.

## The `e2e-upstream` contract

**`e2e-upstream/CONTRACT.md`, versioned, landing at `1.1.0`** (D9).

The README is the how-to and stays authoritative for mechanics — its nine sections already cover
the control API, XC scenario fields, scenario defaults and credentials, HEAD and probe connections,
the fault catalogue, catch-up, pacing, the TS asset and the VOD asset. The contract does the one
thing the README does not: it states, under a version, **what a consumer may rely on and what it
may not**, so a spec can write "e2e-upstream 1.1" instead of re-deriving it. It links to the README
for every mechanism rather than restating one.

**Structure:**

1. **Version and scope.** What the version names (a behaviour set, not an artefact — the image is
   rebuilt from source every run), and what it deliberately does not name.
2. **Guarantees.** The HTTP surface by route; the TS asset's determinism (188-byte-aligned, fixed
   PIDs `0x100`/`0x101`, loop duration *measured at load*, never hard-coded — `measureLoop`);
   continuity, PCR and PTS monotonicity across the loop seam (`LoopRewriter`); the catalogue's
   stable declared ids; the fault catalogue's names and scopes; the scenario log's record shape.
3. **Non-guarantees — the substance.** The two already known and confirmed in this session:
   **no calendar validation** on catch-up (any parseable timestamp is answered, impossible dates
   included) and **no time-addressable archive** (the catch-up routes serve the same loop whatever
   `start` they are given — the constraint that governs every timing row in G10). Plus everything
   else the audit finds: what is hard-coded, what is ignored, what is approximated. The plan's
   Task 8 enumerates these from source; the rule is that **anything a test could wrongly rely on
   gets a line**, and each line cites `file:symbol`.
4. **Known consumers**, and what each depends on, so a future change knows its blast radius.
5. **Bump policy.** Patch: a fix that leaves every documented guarantee true. Minor: a new route,
   fault, scenario field or documented guarantee — additive, no consumer changes. Major: a change
   to any documented guarantee or non-guarantee, including the byte format of the TS asset (which
   is what the per-stream marker of D6 would be). Because provider and consumers ship from one
   commit, a bump never breaks a build — it exists so a spec can cite a version and a reviewer can
   see, in one number, whether a consumer's assumptions moved.
6. **Enforcement.** One guard, `e2e/tests/guards/upstream-contract.spec.ts`, asserts that
   `CONTRACT.md`'s declared version equals `e2e-upstream/package.json`'s (D10). It resolves both
   paths from `REPO_ROOT`, imported from `./ast` — the guards' shared root constant, defined as
   `path.resolve(E2E_ROOT, '..')` — rather than repeating a `path.resolve(__dirname, …)` walk, so a
   directory move breaks one definition instead of six. It imports `test` and `expect` from
   `@playwright/test`, not from `'../../fixtures'`: the `guards` project runs with no fixtures. It
   is tagged `@characterization` under a `// @characterization: …` comment naming the fact it pins,
   in the same words its five siblings use. *A convention plus a README decays silently. This does
   not* — the sentence the deleted `quarantine.spec.ts` justified itself with, and which
   `allowlist.ts` now carries forward.

## File ownership in wave 6 — confirmed disjoint

Checked file by file against the disposition's assignments:

| Owner | Files | G15 touches? |
|---|---|---|
| **G13** | `e2e/tests/frontend/dvr.spec.ts` | **No.** Its only `test.fail()` mention is a comment, not a call site (audit note above). No Guide→record test (D-note under interactions) |
| **G12** | `e2e/tests/lifecycle/**`, `durable-state.ts`, backup **restore**, `lifecycle-tests.yml` | **No.** D8 keeps restore out of G15 explicitly |
| **G14** | `settings.spec.ts`, `plugins.spec.ts`, EPG matching, bulk ops, M3U filters/profiles, product WS events | **No.** G15's frontend work is `stats.spec.ts`, `guide.spec.ts`, `backups.spec.ts` only. `m3u-ingest.spec.ts` and `m3u-refresh-failure.spec.ts` appear in G15's audit, but for `test.fail()` guards — not M3U filters or profiles, which are G14's subject in different files |
| **G11** | ~~The tag taxonomy, the generalised quarantine guard, the run-everything CI mode, the `data-testid` ADR~~ — **landed** as `4211cbb7` and `7a408c2b` | **No.** G15 applies G11's tags and adds one file to the `guards` directory G11 created; it edits none of G11's own guards, `ast.ts`, `allowlist.ts`, the ADRs or the workflows, and D12 keeps it out of every workflow file |
| **G15** | `stats.spec.ts`, `guide.spec.ts`, `backups.spec.ts`; the nine `test.fail()` guard sites; `xc-output.spec.ts`; `catchup-path-layout.spec.ts`, `catchup-cascade.spec.ts`; `api-fixture.spec.ts`, `authorization.spec.ts`; `e2e-upstream/CONTRACT.md` + `e2e/tests/guards/upstream-contract.spec.ts`; `COVERAGE.md`, `README.md` | — |

The one shared-file collision risk is `e2e/COVERAGE.md`, which G12–G15 all append to. G15 edits
**only its own rows** and appends its new ones — the same discipline every prior goal in this
programme has followed. G15's Guards-table row is an append to a table G11 owns; the heading stays
`## Guards (G11)`, because it names the goal that built the project, not the goal that last added a
row.

**One exception, and it is a factual correction rather than a re-scoping.** `COVERAGE.md`'s G9 VOD
row for the credential-disclosure defect still says *"deliberately unfiled … no public issue exists,
pending a disclosure decision by the repo owner."* The decision was taken and the issue is
[#89](https://github.com/D10Scot/Dispatcharr/issues/89). G15 corrects that row to cite it, keeping
its `known-bug` status and its G9 assignment, and says so in the commit message. Leaving a row that
tells the next reader not to file an issue that already exists is worse than the ownership rule it
would honour.

## Guards G15 must satisfy — checked, all clear

Five blocking guards run in the `guards` project. Every one was checked against G15's file list, and
G15 trips none of them:

| Guard | Rule | G15 |
|---|---|---|
| `capabilities.spec.ts` · `CONTAINER_LIFECYCLE` | A test or hook destructuring the `instance` fixture must be one of the two `tests/lifecycle/` specs | **Clear.** G15 touches no lifecycle spec and destructures `instance` nowhere. The container is never restarted, replaced or upgraded by anything here |
| `capabilities.spec.ts` · `SUBPROCESS` | A direct `node:child_process` / `child_process` import must be `fixtures/instance.ts`, `fixtures/greybox/redis.ts` or `output-profile-sharing.spec.ts` | **Clear.** No task shells out. Item 16's guard reads two files with `node:fs/promises`, which is not on any list |
| `capabilities.spec.ts` · `CONTAINER_INTROSPECTION` | The markers `pgrep`, `docker ` and `manage.py` must not appear **in a string or template literal** outside `fixtures/instance.ts` and `output-profile-sharing.spec.ts` | **Clear, and the one worth stating explicitly.** The detector reads literals only, never comments — so the prose in these documents and in the specs' own header comments is invisible to it. Nothing G15 adds builds a command line. Item 16's guard also lives under `tests/guards/`, which `usersOf` skips outright |
| `global-mutation.spec.ts` · `GLOBAL_SETTINGS_WRITE` | Any `api.post/patch/put/delete` whose URL text resolves to contain `core/settings` must be on a four-file allowlist | **Clear, including the one case that looks like an exception.** Task 14's Stats test may set the **"Refresh Interval (seconds)"** `NumberInput` to `0` to remove the poll. That is a page control backed by `localStorage`, not a settings row — `stats.spec.ts`'s existing comment names the key, `stats-refresh-interval`, and locates it in `localStorage`. No G15 test writes `/api/core/settings/`; `lockedProfile(api, 'Proxy')` reads the locked profile rather than setting a default, and `grep -n "core/settings"` over the three frontend specs returns nothing today |
| `pageerrors-enforcement.spec.ts` | Every `test()` under `tests/frontend/` must destructure `pageErrors` | **Binding on Task 14, and already stated there.** All three new interaction tests take `pageErrors` and end with `await pageErrors.expectClean()`, as every test in that directory does. `KNOWN_UNVERIFIABLE` holds one entry (`plugins.spec.ts:15`) and G15 adds none |
| `tags.spec.ts` | Every declaration carries exactly one recognised tag, in an inline details literal | **Binding on every item.** The inventory's tag column is the answer, and `testid.spec.ts` is unaffected because G15 adds no `SURFACES` entry |

## Test inventory

Sixteen numbered changes. **Twelve add a test** — eight guard controls (audit rows 1–8), three
frontend interactions, one contract guard. **Six edit an existing test** — including the ninth
guard (audit row 15), which folds one assertion into a control that already exists rather than
adding a test.

| # | Change | File | Kind | Tag |
|---|---|---|---|---|
| 1 | Non-inverted control: seed an M3U account and PATCH a writable field | `seeded/m3u-ingest.spec.ts` | new test | `@contract` |
| 2 | Non-inverted control: the restricted channel shape round-trips | `seeded/hdhr.spec.ts` | new test | `@contract` |
| 3 | Non-inverted control: a profiled level-1 user lists a level-1 channel | `seeded/xc-live.spec.ts` | new test | `@contract` |
| 4 | Non-inverted control: a live principal's refresh token is accepted (zero login) | `seeded/token-refresh-deleted-user.spec.ts` | new test | `@contract` |
| 5 | Non-inverted control: the adult channel is unlistable for the filtered user, listable for an admin | `streaming/hidden-channel-streamable.spec.ts` | new test | `@contract` |
| 6 | Non-inverted control: the adult movie is unlistable for the filtered user | `streaming/vod-adult-streamable.spec.ts` | new test | `@contract` |
| 7 | Non-inverted control: the VOD stream route serves bytes with no fault armed | `streaming/vod-upstream-error.spec.ts` | new test | `@contract` |
| 8 | Non-inverted control: `range-unsupported` makes the **provider** ignore Range (direct, via `toControl`) | `streaming/vod-range.spec.ts` | new test | `@contract` |
| 9 | Fold a channel-rename round-trip into the existing non-inverted playlist test | `seeded/output-m3u.spec.ts` | edit | unchanged (`@contract`) |
| 10 | `expectWellFormedXml` on the XMLTV body; add `adminPage` | `seeded/xc-output.spec.ts` | edit | unchanged (`@contract`) |
| 11 | `expectTsAligned` replaces the first-byte check | `streaming/catchup-path-layout.spec.ts` | edit | unchanged (`@contract`) |
| 12 | `expectTsAligned` replaces the first-byte check (1 line — the import is already there) | `streaming/catchup-cascade.spec.ts` | edit | unchanged (`@contract`) |
| 13 | JSON-shape body assertions on both fixture proofs; an unauthenticated-401 assertion on the refresh proof | `seeded/api-fixture.spec.ts` | edit | unchanged (`@contract`) |
| 14 | Containment body assertion on the admin list; comment on the deliberate status-only 403 | `seeded/authorization.spec.ts` | edit | unchanged (`@contract`) |
| 15 | One interaction test each | `frontend/stats.spec.ts`, `frontend/guide.spec.ts`, `frontend/backups.spec.ts` | 3 new tests | `@contract` ×3 |
| 16 | `CONTRACT.md` + the version-agreement guard test | `e2e-upstream/CONTRACT.md`, `e2e/tests/guards/upstream-contract.spec.ts` | new file + new test | **`@characterization`** |

**Why the tags fall the way they do.** Items 1–8 and 15 assert client-observable behaviour — a row
read back through the REST API, a listing, bytes on the wire, a rendered page reacting to a click —
which is `@contract` by ADR 0002's default, and `@contract` needs no justification. Items 9–14 edit
existing tests without changing what they are, so their tags stay as G11 set them; every one is
`@contract` today, and none of G15's edits changes that. **Item 16 is the exception**: it reads
`e2e-upstream/package.json` and `e2e-upstream/CONTRACT.md` off disk and compares two strings in this
repository's own source. Nothing about it survives into a world where the relay is a separate
process except this repository's layout, which is exactly what `@characterization` means — and it is
why it belongs in `tests/guards/`, where all eight existing tests carry the same tag for the same
reason. It gets the directory's `// @characterization: <fact>` comment, which ADR 0002 requires and
the guard does not check.

Plus `COVERAGE.md` (three new Frontend rows, one Streaming Gap row for D6, one Upstream row for the
contract, **and one row in the `## Guards (G11)` table** for item 16's guard, carrying the mutation
that proved it fails) and one `README.md` section pointing at `CONTRACT.md`.

## Candidate product defects

Filed on the fork with an explicit `--repo D10Scot/Dispatcharr` (roadmap rule 5,
`docs/agents/issue-tracker.md`). **G15 files; G15 does not patch.**

- **C1 — verified. Icon-only action controls on Stats and Backups have no accessible name.**
  Every per-connection action in `StreamConnectionCard.jsx` ("Stop Channel", "Disconnect client",
  "Switch to another stream source", "Preview Channel") and every row action in
  `BackupManager.jsx:RowActions` ("Download", "Restore", "Delete") is a Mantine `Tooltip` wrapping
  an icon-only `ActionIcon`. A `Tooltip` contributes `aria-describedby`, which does not compute an
  accessible name, so `getByRole('button', { name })` cannot address any of them. Same class as
  [#73](https://github.com/D10Scot/Dispatcharr/issues/73) (plugin switches) and worth a *separate*
  issue rather than a comment on #73: #73's fix is two `aria-label`s on two `Switch`es in one file,
  this is eleven controls in two files, and one of them is **Restore**, where a mis-addressed click
  replaces the database. Filed as a **test blocker**, not merely an a11y nicety — it is why D7 and
  D8 exclude four otherwise-obvious tests. **Not pinned with `test.fail()`**: there is nothing to
  invert. A missing accessible name is not a behaviour a test can assert as correct-and-failing
  without asserting a specific `aria-label` string this fork has not chosen. The issue body names
  the eleven controls and proposes `aria-label` matching each `Tooltip`'s existing `label`.

No other candidate defect. This is a test-quality goal; if a guard added in Task 2–9 surfaces a
product defect that the hollow pin was hiding, it is filed then and named in the PR body — that is
the expected shape of a good outcome here, not an exception to the plan.

## Non-goals

- **Building the per-stream TS marker.** Ruled feasible under Proxy, deliberately not built (D6).
- **Any change to `render.spec.ts`.** Smoke-only by design; settled by the disposition.
- **Re-opening the two refuted items.** The `logo-upload.spec.ts` byte comparison is correct as
  written (`Buffer.equals` against `logoPayload`, under a comment rejecting same-length matching),
  and `m3u-ingest.spec.ts`'s source-text assertion stays — a behavioural replacement was tried and
  shown vacuous by mutation. Neither is touched.
- **Tightening `parseXmltv`.** D4.
- **Defining the tag taxonomy.** G11's.
- **Backup restore, and any `tests/lifecycle/**` change.** G12's.
- **Any DVR flow, including recording from the Guide.** G13's.
- **`settings.spec.ts`, `plugins.spec.ts`, M3U filters and profiles, product WS events.** G14's.
- **Adding a `/version` endpoint to the provider, or any `e2e-upstream/src/` change.** D10.
- **Any workflow or `playwright.config.ts` project change.** D12.
- **Any product code change.** One issue, no `apps/`, `core/`, `dispatcharr/` or `frontend/` edit.

## Risks

- ~~**G11 lands late and G15 has to be re-tagged.**~~ **Discharged.** G11 merged as `4211cbb7` and
  `7a408c2b`; every file G15 touches is already tagged, and the retag conflict this risk anticipated
  cannot happen. What replaces it is smaller and mechanical: **a new test with no tag fails the
  `guards` job**, which is blocking. Every item in the inventory carries its tag above, so the
  failure mode is forgetting, not choosing.
- **A hollow pin surfaces as a red `@contract` control, which by ADR 0002 blocks.** This is the same
  event as the risk below, seen through the taxonomy: every guard control G15 adds is non-inverted
  and `@contract`, so if the premise it exercises is genuinely broken, the control lands red and
  `docs/adr/0002-e2e-test-taxonomy.md` is unambiguous — *"a red `@contract` test blocks. Behaviour
  changed; either fix the implementation or argue the test was wrong."* There is no
  read-it-and-move-on disposition available, because that is `@characterization`'s and these are not
  characterization tests. **So the PR must either fix the premise or state in its body why the red
  is correct and what it means, before merge.** Retagging the control `@characterization` to quieten
  it is the one response that is out of bounds: it would make the exact class of failure this goal
  exists to expose invisible on a migration branch, which is the asymmetry ADR 0002 chose against.
- **Row 5, 6 and 7's sibling controls are expensive.** Each is a `streaming`-project test that
  stands up its own scenario, so each roughly doubles its file's runtime (~60s apiece, ~3 minutes
  total). That is the honest price of guarding three single-test files. It is paid, not optimised:
  a cheaper control that shares the pin's fixtures would share its failure modes.
- **A guard can turn a green pin red — and that is the point.** If any of rows 1–8 was passing
  *because* its premise was broken, adding the sibling makes the suite red on landing. The PR body
  must say so and the finding is triaged, not suppressed. This is the most likely way G15 grows,
  and the plan's **Task 16 Step 4** exists to absorb exactly one such finding. (An earlier draft
  said Task 10; Task 10 is the row-15 guard, and the step that reads the whole-suite result against
  Task 1's baseline is Task 16 Step 4.) See the ADR bullet above for why such a red blocks.
- **The Backups upload test adds an archive to a shared directory.** The file's module comment
  already explains why `backups.spec.ts` is pinned to file-level parallelism and why its before/
  after set difference is sound; the new test inherits that and registers its archive in the
  existing `namesToDeleteAfterEach`. It must go **in that file** — a second backups file would
  break the invariant the first one's comment establishes.
- **The Guide profile-filter select may not be addressable by placeholder alone.** Mantine
  `Select` renders a placeholder on the input, which `getByPlaceholder` reaches, but the option
  list is portalled. Mitigation: the plan's task verifies the locator against a running container
  before writing the assertion, and falls back to the store-level assertion (the filtered channel
  list from `/api/channels/channels/`) if the option cannot be addressed — recording which was used.
- **`CONTRACT.md`'s non-guarantee list is only as good as the audit that produced it.** A
  non-guarantee nobody noticed is exactly the kind a consumer goal will later rely on. Mitigation:
  the plan's Task 8 enumerates from source with `file:symbol` cites per line, and the contract
  says in its own header that an unlisted behaviour is **not** a guarantee — defaulting to
  "not promised" rather than "promised unless denied".
