# Phase 2 Stage 2c-9 — the Go coverage gate, and 2c's close-out

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Go relay's test suite into an enforced coverage ratchet measured where it is enforced, make "the parity matrix is 100% Go-columned" a mechanical check rather than a claim, give CodeQL a Go pack, and add the one test that drives both relays from the same bytes — then close stage 2c.

**Architecture:** One new script (`scripts/coverage_relay_go.sh`) measures and gates; one new floor file and its committed package-list companion carry the number and its provenance. `go-tests.yml` grows two jobs — `coverage`, which gates on a bare runner from the profile the existing `build` job now uploads, and `differential`, which builds `relay-go` and runs one Django harness test that drives both implementations against one `FakeUpstream`. `codeql.yml` grows a Go job of its own. `e2e/tests/guards/parity-matrix.spec.ts` grows an eighth check.

**Tech Stack:** bash + awk + sha256 for the gate (no Go needed to read a profile); Go 1.27.1, stdlib only, `go test -count=1 -race -covermode=atomic`; Django `LiveServerTestCase` + the stage-2a subprocess harness for the differential; Playwright `guards` project (no container) for the matrix check.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — § Stage 2c's nine-PR table (row 2c-9), Amendment A1.5 (CodeQL Go), A2.2 (a Go pin is one more reference in the existing `Pin` cell), A2.4 (the differential), § Testing, § Requirements this phase meets or carries (four rows name 2c-9), § Stage 2d.

## Global Constraints

Every task's requirements implicitly include all of these. A conflict with any is a **STOP and report**, not an amendment you make yourself.

1. **`-race` is mandatory and has no per-package exemption.** The measurement command is `go test -count=1 -race -covermode=atomic -coverprofile=… ./...` and nothing weakens it.
2. **`-count=1` is mandatory on every measurement.** `go test` caches a package's result *including its coverage profile* and replays it verbatim; without this a twelve-round local census is one run reported twelve times, with a spread of zero.
3. **The module stays standard-library only.** `relay/go.sum` must not exist; `go list -m all` must print exactly `github.com/D10Scot/Dispatcharr/relay`. `scripts/check_go_stdlib_only.sh relay` is the mechanical check and it already runs in `go-tests.yml`.
4. **No Postgres driver, no Redis client, on the Go side.** Same check.
5. **Lint and vet under three GOOS.** `golangci-lint run` and `go vet ./...` native, `GOOS=linux` and `GOOS=darwin`. Zero findings is a ratchet, in zizmor's idiom. `golangci-lint` is pinned at **v2.13.2** in both `go-tests.yml` and `.claude/hooks/run-go-checks.sh`.
6. **Every suppression is listed with its line and its reason.** On `a635190c` the census is **18 grep hits for `#nosec`/`nolint`, of which 16 are real suppressions** — `relay/internal/relaytest/fmp4.go:43` and `relay/buffer/ring.go:310` are prose explaining why no suppression was needed. **This PR adds exactly one**, and it is disclosed here rather than left for a reviewer to find: `relay/drain/drain_test.go`'s `os.ReadFile(path) // #nosec G304 -- a path this test computed from the repo root`, which R16 needs and which gosec fires on for any `os.ReadFile` of a variable. The census after this PR is 19 hits / 17 real. If any further suppression appears, the PR description lists it with its line and reason.
7. **`scripts/check_go_credential_logging.sh relay` stays at zero findings.** Any error-typed argument to a logging or formatting call goes through `redact.Error` or carries `// credential-logging: ok - <reason>`.
8. **`scripts/check_credential_logging.py` stays at zero findings** for every `*.py` this PR touches.
9. **Every `uses:` is a full 40-char commit SHA with the version as a trailing comment**, tool-resolved at PR time (`gh api repos/<owner>/<repo>/commits/<tag> --jq .sha`), never hand-typed, and the publisher confirmed. **zizmor at zero findings on every workflow this PR edits**, online audits on (`GH_TOKEN` from `gh auth token`).
10. **A channel UUID and a provider URL are secrets.** Nothing this PR adds may print either. The Go relay redacts its own log lines (`relay/redact`), which is why the differential test may print the child's output.
11. **Do not use the shared `dispatcharr-testrunner` container.** Start your own, named for this PR, and remove it when done. The `PostToolUse` hook will refuse loudly if the shared container is mounted at another worktree — that refusal is correct; run the label yourself instead of re-pointing the shared container, which another agent may hold.
12. **Stage and commit in separate Bash calls.** Write commit messages with the Write tool and commit with `git commit -F <file>`; a command containing both `git` and `commit` plus a heredoc trips the commit gate.
13. **`gh` always with `--repo D10Scot/Dispatcharr`.**
14. **Branch: `migration/phase2c-go-coverage-gate`.** The `migration/**` prefix is load-bearing — it bypasses the E2E path filters and runs every Playwright project.

---

## Rulings

These are the decisions this plan makes on the questions the spec and the eight predecessor plans left open. Each is measured or argued from the tree, not assumed.

### R1 — The denominator is the packages the shipped binary links, not `./...`

`go list -deps .` from `relay/` prints exactly **ten** packages of this module on `a635190c`: `relay` (main), `buffer`, `channel`, `config`, `control`, `drain`, `ffmpeg`, `httpapi`, `output`, `redact`. `relay/drain` is the tenth, added by 2c-8 and imported by `main.go`. Task 0 Step 2 expects exactly those ten; an eleventh, or a missing `drain`, is a stop-and-report. `relay/internal/relaytest` and `relay/internal/credlint` are in the module and in neither list: the first is the Go counterpart of `apps/proxy/live_proxy/tests/harness/` and the second is a lint tool invoked with `go run`.

Measured on `a635190c`, same run, same command:

| scope | statements | missing | coverage |
|---|---|---|---|
| the whole module (`./...`) | 4,463 | 1,172 | 73.74% |
| the ten linked packages | 3,696 | 587 | **84.12%** |
| the two excluded packages | 767 | 585 | 23.7% |

`relaytest` alone is 628 of those 767 statements. **The two excluded packages are 585 of the module's 1,172 missing statements** — half the module's shortfall is test scaffolding and a lint tool.

**The margin narrowed between 2c-7 and 2c-8, and that is worth stating rather than burying.** On the 2c-7 seed the same measurement gave 3,670 / 870 / 76.29% and 2,956 / 338 / 88.57%. 2c-8 added 740 linked statements carrying 249 missing ones — a **marginal coverage of 66.4%** on its own additions — which is what took the module from 88.57% to 84.12%. The 80% ceiling is `3696 - ceil(0.8 × 3696)` = **739**, so the margin is **152 statements**, where on the seed it was 253. One more PR of 2c-8's shape would breach it. Task 7 Step 4 is what acts on that if CI measures worse; the floor's header records it so the next stage reads it before, not after.

**And the gate is a TOTAL, which is worth saying out loud because D7's purpose is not.** D7 wants Gate 2 to catch a subtle regression; a single module-wide `missing` cannot tell one package getting worse from another getting better. Two packages are individually under 80% on `a635190c` and between them hold more than half the module's shortfall:

| package | statements | missing | coverage | share of the 587 |
|---|---|---|---|---|
| `relay/channel` | 1,063 | 219 | 79.40% | 37.3% |
| `relay/control` | 404 | 94 | 76.73% | 16.0% |
| **both** | 1,467 | **313** | 78.66% | **53.3%** |

So a future PR can add well-covered `httpapi` code and offset a `channel` regression with the total unmoved and the gate green. **`channel` and `control` are the packages that owe the shortfall**, and the next PR that adds to either should read the per-package table `--report` prints rather than the one number `--gate` compares. This plan does **not** add a per-package floor: a second ratchet is a second thing to re-measure and re-baseline, and stage 2c is closing rather than opening machinery. Naming the two packages in the floor's own header is the cheaper half, and it is what 2d reads before writing.

**The rule is decided by kind, not by number.** `scripts/coverage_live_path.coveragerc` excludes exactly these two kinds on the Python side — `omit = */tests/*` takes the harness out, and no script under `scripts/` is in its ten-module boundary list. The Go gate applies the same rule to the same kinds. The difference from the Python gate's own declined exclusion (§ Gate 2, "Denominator exclusion was considered and declined") is that that one was proposed *in order to reach a threshold it could not reach anyway*; this one is the scope rule the sibling gate already uses, and the threshold is met with 253 statements of margin either way.

It is derived mechanically rather than listed by hand so it cannot rot — and the derived list is hashed into the floor (`packages=`) with the sorted list committed beside it, so a package entering or leaving the binary is a deliberate re-baseline and never a silent denominator move.

### R2 — Per-package `-cover`, not `-coverpkg`

`go test -cover` instruments only the package under test, so a package's figure comes from its own tests. `-coverpkg` counts a package as covered when any other package's test walks through it. Both measured on `a635190c`, same denominator:

| mode | statements | missing | coverage |
|---|---|---|---|
| per-package (`-cover`) | 3,696 | 587 | 84.12% |
| cross-package (`-coverpkg`, merged per block) | 3,696 | 316 | 91.45% |

271 statements — 7.33 points — is entirely code executed by a neighbour's tests, and the gap **widened** with 2c-8 (it was 117 statements / 3.95 points on the 2c-7 seed). That is the measurement arguing for per-package more strongly than before: a third of the module's uncovered code is reached by some other package's test without any test asserting anything about it there. Per-package is kept because D7's stated purpose for Gate 2 is catching a subtle regression, which needs an *assertion over* the code rather than an *execution of* it, and an assertion lives in the package's own tests.

A timing objection was considered and **did not survive measurement** on the seed: instrumenting the live path into every test binary might have perturbed the suite's real-time assertions, but `relay/channel` took 75.0 s under `-coverpkg` and 75.2 s without. Recorded because a plan that cited an unmeasured reason would be worse than one that cites a measured non-reason.

A `-coverpkg` profile repeats every block once per test binary, so the gate **refuses one outright** rather than silently producing a plausible number from it.

### R3 — The files are `scripts/coverage_relay_go.*`, not the spec's `coverage_live_path_go.floor`

`dispatcharr/test_discovery.py`'s `_PATH_ALIASES` carries `("scripts/coverage_live_path", ("apps.proxy", "apps.proxy.live_proxy", "apps.channels"))` — a **prefix** match with no trailing slash, deliberately, so that the Python gate's script, rcfile, floor and floor companion all route to Gate 2's three Django labels. A file named `scripts/coverage_live_path_go.sh` matches that prefix. Editing the **Go** gate would then run three Django test labels, in CI and in the commit gate, for a change that touches no Python at all.

The alternative — tightening the alias to `scripts/coverage_live_path.` — was rejected: it edits the Python gate's own routing contract, and its pinned test (`tests/test_ci_test_routing.py`), inside a PR whose job is the Go gate and which must not be able to break the Python one.

So the spec's literal filename is amended (Amendment A9), and `go-tests.yml`'s own change detector names `scripts/coverage_relay_go\.` instead. The three files are:

- `scripts/coverage_relay_go.sh`
- `scripts/coverage_relay_go.floor`
- `scripts/coverage_relay_go.floor.packages`

### R4 — The floor's shape fields are `packages=` and `gomod=`

Read across from the Python floor, field for field:

| Python | Go | answers |
|---|---|---|
| `shape=per-container/v1-sysmon` | `shape=go-race-per-package/v1` | how was this measured |
| `modules=` + `.floor.modules` | `packages=` + `.floor.packages` | which files are in the denominator |
| `rcfile=` (the rcfile's raw bytes) | `gomod=` (`relay/go.mod`'s raw bytes) | did the measurement *definition* change |
| `missing=` | `missing=` | **the ratchet** |
| `statements=` (recorded, not compared) | `statements=` (recorded, not compared) | provenance |

`gomod=` is the honest counterpart of `rcfile=`: `relay/go.mod` fixes the toolchain version the measurement ran under (CI reads it via `go-version-file`) and the module's dependency set, and either moving makes two numbers incomparable rather than better or worse. `statements` is not compared for the Python gate's own reason — it moves whenever any statement is added to or removed from an already-included package, which is ordinary code work, not a scope change.

### R5 — The CI census, and how the floor is bootstrapped exactly once

**The floor's `missing` comes from CI, because that is where the gate is enforced.** The Python floor was first set from a 21-round *local* census whose maximum the very first CI run exceeded; that lesson is inherited rather than re-learned.

The bootstrap mechanism is **the absence of the floor file**, not a workflow input. `--gate` with no floor file prints the draw and exits 0, saying it is a census draw and not a gate. The obvious hole — someone deletes the floor and the gate is permanently off — is closed from the other side, in the workflow: the `Refuse a floor edited downward or deleted` step fails when the **base ref** carries a floor and the head does not. Absence is therefore forgiven only when the base is also absent, which is true exactly once, on the PR that introduces the floor.

A `workflow_dispatch` input (`census: true`) was considered and rejected: it would add a permanent input to a required workflow whose whole effect is to not gate.

**The stopping rule is the Python gate's**: dispatch `go-tests.yml` on the branch repeatedly, read `this run missing=` from each `Coverage gate` job, and stop when the **maximum has been unchanged for ≥6 consecutive rounds, with ≥12 rounds total**. Record every round, in order — a bare min/max cannot show the rule was met. `missing` is set to `max(rounds)`, by hand, because `--write-floor` writes the figure from the run it just took and cannot know it is the Nth of a campaign.

**Local draws are for design, not for the number.** A 12-round local census on `a635190c` measured **587–588** here, in order: `588 587 588 587 588 588 587 588 587 588 588 588`. A second rig drew **586** on the same tree, so the local range across both is **586–588** and **two** blocks flap, not one:

| block | what it is | seen |
|---|---|---|
| `relay/buffer/ring.go:262.3,263.1` | the empty-ring arm of `Ring.Oldest()`, covered when a test calls it before the first write | here, 4 of 12 draws; also on the 2c-7 seed |
| `relay/httpapi/fmp4.go:188.4,189.1` | the `ctx.Err() != nil` early return in the fMP4 client loop | on the second rig; **uncovered in all 12 draws here** |

Two rigs agreeing on the *kind* of flap — a branch whose execution depends on which goroutine wins a start-up race — and disagreeing on *which* blocks flap is the reason the number comes from CI and not from either of them. **Do not carry either block forward as the census**: Task 8 re-derives it from the CI draws' own profiles. That is two orders of magnitude tighter than the Python gate's 104-statement flappy set, and it is expected: the Go tests inject clocks and poll for conditions where the Python relay's spread comes from gevent background housekeeping this implementation deleted. It is **not** a reason to take fewer CI rounds.

### R6 — A draw beyond the census, and the one part of #312 the Go gate does not inherit

[#312](https://github.com/D10Scot/Dispatcharr/issues/312) is the Python gate's worked instance: a CI draw of 1,529 against a twelve-round census whose maximum was 1,525. The rule it establishes is carried into this floor's own header verbatim in shape:

> A draw above `missing` is a finding to investigate, not noise. Attribute it per package and then per **block** — diff the uncovered block sets, never difference the totals — against a green run's profile. If it is the documented flap exceeding its recorded envelope, the fix is a re-measurement PR of its own, never a floor bump on the PR that happened to draw it.

The gate's own failure message says this, so a reader does not have to find the header.

**One half of #312 cannot arise here, by construction.** Its second operational note is that CI's coverage artifacts are unusable locally because coverage.py records absolute paths (`/__w/Dispatcharr/Dispatcharr/…`) and the committed rcfile has no `[paths]` section. A Go coverprofile's first column is an **import path** — `github.com/D10Scot/Dispatcharr/relay/buffer/ring.go:31.42,35.3` — not a filesystem path, so a downloaded CI artifact parses identically on any machine with no remapping. State it in the floor header; it is the reason this gate's artifacts are directly diffable and the Python gate's are not.

### R7 — #309 is fixed here, and the stamp move alone was measured not to fix it

[#309](https://github.com/D10Scot/Dispatcharr/issues/309): `TestDeadAirOnAYoungConnectionSwitchesStreams` (`relay/channel/failover_test.go`) asserts the resolver was asked no sooner than `ConnectionTimeout + 2×HealthCheckInterval` = 400 ms after the last byte, and was seen to fail twice in twelve loaded runs at 399.968 ms and 399.990 ms.

**Fixed here, and the reason is this PR specifically**: the census is twelve green CI runs of the whole Go suite, and a test that fails under load makes every draw a coin toss. A flaky test in the workflow the close-out asks the user to make *required* is also the wrong thing to hand over.

**The first draft of this ruling had the mechanism wrong, and the measurement is what found that out.** It proposed moving the source's `lastWrite` stamp to before `sink.Write`, on the argument that `dataClock.Write` records the channel's own `lastData` at the start of the write, so a stamp taken afterwards is later than the monitor's clock and the `>=` assertion loses by that much. That argument is correct as far as it goes and the stamp move is kept — but a controlled A/B says it does not reduce the failure rate:

| shape | runs (loaded) | sub-400 ms gaps | minimum gap |
|---|---|---|---|
| A: stamp moved before the write | 60 | **2** (399.966 ms, 399.960 ms) | 399.960 ms |
| B: unmodified | 60 | **1** (399.995 ms) | 399.995 ms |
| C: stamp moved **and** the bound widened | 30 | 0 | 399.989 ms, against a 395 ms floor |

Two campaigns, same host, 28 busy-loop spinners on 14 cores, shapes alternating within each round so neither sees a different machine, `-race` off, the gap logged on every run rather than inferred from pass/fail. A and B are indistinguishable.

**The real mechanism, instrumented rather than argued.** A `println` in `monitorHealth` on this tree prints the inactivity at every tick:

```
TICK inactivity_us 250496 threshold_us 300000 unhealthyChecks 0 …
TICK inactivity_us 301093 threshold_us 300000 unhealthyChecks 0 …
TICK inactivity_us 351729 threshold_us 300000 unhealthyChecks 1 …
TICK inactivity_us 400631 threshold_us 300000 unhealthyChecks 2 …
```

The monitor's tick grid is phased on **its own start**, not on the last byte, so the first tick whose inactivity exceeds `ConnectionTimeout` lands at **301.093 ms** — 1.09 ms past 300, that overshoot being the ticker's accumulated drift over six ticks — and the third unhealthy check two ticks later at ~400.6 ms. **So the margin above a floor of exactly `ConnectionTimeout + 2 × HealthCheckInterval` is the drift alone, about a millisecond, not the 50 ms interval it looks like.** Any sub-millisecond perturbation breaches it, and the stamp order — tens of microseconds — is one such perturbation among several rather than the cause.

This also **disconfirms the mechanism the review proposed** (an unhealthy check counted before the first byte, which the trailing `if c.healthy { unhealthyChecks = 0 }` cannot reset). The trace shows `unhealthyChecks 0` at the 301 ms tick, so nothing was counted earlier; and it cannot be, because `inactivityThreshold()` (`relay/channel/health.go`) returns `InitGracePeriod` while `connected && ring.Head() == 0`, which this test leaves at `testTuning()`'s 60 s, and `channel.go:592-595` sets `lastData` at connect rather than leaving it zero. The conclusion the review drew from that mechanism is right; the mechanism is not.

**So the fix is the bound, and the stamp move rides along.** The floor becomes `ConnectionTimeout + 2×HealthCheckInterval − HealthCheckInterval/10` — 395 ms here. **The asserted count is unchanged at three**; what moves is the clock tolerance, which is what the issue's own second option proposed and what the first draft of this ruling wrongly declined. A tenth of an interval is two orders of magnitude below the 50 ms that separates this from acting one check early, so the test still catches what it exists to catch:

| break-check | observed |
|---|---|
| `maxUnhealthyChecks = 2` (acts on the second check) | **red** at 350.99 ms against 395 ms — 44 ms of margin — but **intermittently so**, see below |
| `maxUnhealthyChecks = 1` (acts on the first) | **red**, but through the earlier `sawUnhealthy` assertion on this host |
| unmodified | green, eight consecutive `-race` runs |

**The `= 2` row is itself intermittent, and the plan says so rather than presenting it as deterministic.** Measured here: 36 red of 36, gaps 350.1–352.0 ms, across an unloaded run of 12 and a loaded run of 24. Measured on a second rig: **9 red of 12, and 3 green at 400.17, 401.74 and 401.80 ms.** The greens are the same phase effect the mechanism above describes, one step earlier: whether the first tick past `ConnectionTimeout` lands at ~301 ms or ~351 ms depends on where the tick grid sits relative to the last byte, and with the monitor acting on the *second* check that difference puts the action at ~351 ms or ~401 ms. **The greens are above 400 ms, so the 5 ms tolerance is not what lets them through** — they would have passed the old bound too. Re-run until red; a single green run is not evidence the break-check is broken, and roughly a quarter of runs on one rig were green. That it did not reproduce here at all is itself the point: the phase is a property of the host, not of the test.

**The `= 1` row is host-dependent and is stated as such rather than as a property of the test.** On this host the switch happens too fast for the poll to observe the unhealthy window, so it reddens through `the channel was never observed unhealthy before it switched`; on the reviewer's host it reddens through the gap assertion at 301 ms. Either way it is not the row to cite as evidence about the gap, which is why `= 2` is the one the plan uses.

### R8 — The differential test: one test, real Django on both sides, citing no matrix row

Amendment A2.4 asks for "a `RelayHarnessTestCase` on the Python side that starts the Go binary as a subprocess, drives both from one paced `FakeUpstream`, and asserts contiguous `packet_index()` runs rather than a body digest". The scope is exactly that and no wider.

**It cites no matrix row and no row cites it.** A differential failure does not say which side is wrong, so it cannot serve as a row's pin; rows 7, 8 and 9 keep the per-language pins they already have. What it catches is the class neither side's own pins can see: two implementations that both satisfy their own tests and still hand a client different bytes.

**`RelayHarnessTestCase` is already a `LiveServerTestCase`** and already exports `DISPATCHARR_INTERNAL_API_BASE_URL = self.live_server_url` into `os.environ` — so the Go relay subprocess needs no stub control plane. It calls the **real** `POST /api/relay/channels/<id>/next-source` on the test's own Django, signed with the real `SECRET_KEY`. That is the first place in this phase the two halves of the Phase 1 contract meet across the language boundary, and it came free.

**Where it runs, and the anti-silence guard.** `go-tests.yml`'s own `differential` job is the only job that builds `relay-go` and boots Postgres and Redis together. The test skips when `DISPATCHARR_RELAY_GO_BIN` is unset — which is every other run of `apps.proxy.live_proxy.tests`, in `backend-tests.yml`'s `test` job and its `coverage-label` job alike, **deterministically in both**, which is what keeps Gate 2's Python census unperturbed. It **fails** rather than skips when the variable is set and the path is unusable, the split `relay/channel/source_transcode_real_test.go`'s `requireFFmpeg` already makes. And the job asserts, after the run, that the runner reported a nonzero test count and no `skipped=` — two mechanisms for one invariant, because "green because it never ran" is the one way this test can lie.

**Gate 2 (Python) is untouched, checked rather than assumed**: the new file is `apps/proxy/live_proxy/tests/test_relay_differential.py`, the rcfile omits `*/tests/*`, and `scripts/coverage_live_path.floor.modules` contains **zero** paths under `tests/`. No production module is edited. No Gate 2 run is owed.

**Cost, measured in a container on `a635190c`: 6.5 s for the module**, plus the job's own Go build and store bootstrap. It was 2.3 s on the 2c-7 seed; the difference is 2c-8's drain, which the test's `SIGTERM` teardown now raises and which spends a five-second client grace before anything else. The teardown wait is **30 s, not 10** — a 10 s wait sat only 5 s above the observed teardown and would have escalated to `SIGKILL` the first time the drain used more of its 15 s budget, a flake that would read as a hung relay.

### R9 — The realignment differential was built, run and dropped

A second differential test — a `FakeUpstream` whose payload begins 57 bytes into a packet, asserting both relays realign to 188-byte boundaries (matrix row 9's property, across the two implementations) — was written and run. It is **not** in this plan, and the reason is recorded so nobody rebuilds it.

`FakeUpstream` **loops** its payload. A payload of `b"\x00" * 57 + synthetic_ts(512)` is 96,313 bytes, which is not a multiple of 188, so every loop re-offsets the stream by 57 bytes: the relay realigns once and is broken again at the first loop point. Making the payload a multiple of 188 that *starts* mid-packet does not help either — the splice at the loop boundary is then a 188-byte span that begins with a real sync byte and contains two different packets' halves, which passes an alignment check while being garbage.

The test did redden (`byte 0 is 0xa2, not the sync byte 0x47`) and the cause was not diagnosed beyond the loop-phase argument above. **A test whose failure mode is a property of its own fixture is worse than no test.** Row 9 keeps its two per-language pins. If a future PR wants this, it needs a non-looping upstream, which `FakeUpstream` does not offer.

### R10 — Both clients join thirty seconds behind, not at the head

The first working draft set `new_client_behind_seconds=0` so both clients would join at the head. Measured: the Python client joined at packet index **178** and the Go client on an identically-configured channel at **0**, leaving 22 comparable packets out of 200. That is not a behavioural difference — it is how much read-ahead each relay had accumulated when its client attached, which is a scheduler measurement.

Setting it to **30** on a channel one second old takes *both* implementations' documented shorter-than-requested fallback — Python's `chunk_timestamps` lookup and Go's `Ring.Join`, pinned by `TestJoinFallsBackToTheOldestChunkWhenTheBufferIsShort` — so both start at the oldest resident chunk and the comparison covers the whole read. The assertion still compares *by index over the overlap* rather than by digest, and still fails loudly if the overlap is small, because the fallback is a behaviour and not a guarantee.

### R11 — "Every row gets a Go counterpart" means every row whose `Pin` is a test pin

After 2c-8, 28 of the matrix's 30 rows carry test pins and rows 26 and 27 carry the literal `white-box-only`. Those two are **exempt by construction, not by an exemption list**: their `Pin` cell is a sentinel rather than a test reference, so they never enter the check at all, and that the set of such rows is exactly {26, 27} is already a two-sided `toEqual` in the guard. Nothing new is needed to keep them honest.

**What is new is that nothing checked the Go half at all.** `docs/relay-parity-matrix.md`'s own header says "every row must show a passing Go-side equivalent before nginx's live locations move", which is stage 2d's precondition, and the guard's seven checks verify that a `.go` reference **resolves** while saying nothing about whether one is **present**. This PR adds the eighth check and a `GO_PARITY_CLOSED` flag in `GATE_1_CLOSED`'s two-branch shape.

Verified both ways on the seed tree: with the flag `true` it fails naming exactly `14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 30` — the thirteen rows 2c-8 owes — and with it `false` all eight checks pass, logging `15 of 28 pinned rows carry a Go reference`. (2c-8's plan says "from 14 Go-pinned rows"; it was written before 2c-7 closed row 11. 15 + 13 = 28 either way.)

### R12 — CodeQL's Go pack is its own job, not a fourth matrix entry

Go is a compiled language: its pack needs `build-mode: manual` and a real `go build` between `init` and `analyze`, which the three existing packs need neither of. The module root is `relay/`, not the repository root, so `autobuild` has no `go.mod` where it looks. Folding it into the matrix means either a conditional build step inside a working job or a matrix of objects whose `build-mode` is an empty string for three of four entries — both put three working analyses at risk to add a fourth. Twenty-five duplicated lines is the cheaper trade. `codeql.yml`'s `push` path filter gains `relay/**`, without which the pack would never run on a relay-only change.

### R13 — The stage-2c milestone is a follow-up PR, not this one

Eight predecessor plans say "the 2c goal milestone lands with 2c-9". Mechanically it cannot: `metrics/curated/milestones.yml` rows carry the **merge SHA**, and a merge commit cannot name itself — the spec's own § Documentation records that constraint. Phase 2b did exactly this: `61600940` merged 2b-4 as #275, and `0c1654d8` — *a separate PR, #276* — recorded the milestone against it.

So this PR touches **no** `metrics/curated/` file, and its final task hands the orchestrator the exact row and the exact commands for the one-line follow-up.

### R14 — The matrix line-number refresh 2c-6 offered to fold in here is declined

2c-6's plan notes that row 12's `Source` citation has drifted (`output/fmp4/generator.py:339-346` now sits at `:350-357`) and suggests "2c-9 — which re-points this matrix at Go tests on every row — can fold the refresh into the pass it is already making."

**The premise is gone.** 2c-8 closes the last thirteen rows; 2c-9 edits **no matrix row at all** — its matrix change is in the guard, not the document. A line-number refresh would therefore be a whole-file diff in a PR whose matrix diff is otherwise zero lines. The guard already fails on a citation that no longer *resolves*, so drift that has become wrong is caught; drift that is merely stale is a chore PR of its own.

### R15 — 2c-7's `"remux stderr"` rename is declined with the split it was attached to

2c-7's handoff: an Output Profile transcode's stderr is logged under the message `"remux stderr"` (`relay/output/fmp4.go:534`), shared with the fMP4 remux and disambiguated only by the logger's `format=` field — "a one-line rename belongs with Ruling R1's recommended `fmp4.go` split, not this PR."

The split is declined here: a file move reads as a whole delete plus a whole add, which is the wrong diff for a PR whose job is a gate, and 2d needs neither. The rename was explicitly conditioned on the split, so it goes with it. Both are recorded in the PR description as a named follow-up.

**One neighbouring one-liner IS done, and the difference is the kind of claim.** `relay/main.go`'s comment says "there is no Go equivalent yet" of the credential-logging rule, which `relay/internal/credlint` and `scripts/check_go_credential_logging.sh` have been since 2c-4. That is not a log message somebody would prefer differently — it is a **false statement about this repository's own tooling**, in the file a reader opens first, in a PR whose subject is that tooling. The rename was declined because its stated home was a refactor this PR is not doing; this has no such condition. Task 2 Step 7 carries it, and the correction also says what credlint does **not** cover here, so it does not replace one wrong claim with another: credlint inspects error-typed arguments and `cfg.Secret` is a string, so that line is still held by hand.

### R16 — the drain test reads `stopwaitsecs` instead of restating it

2c-8's `relay/drain/drain_test.go` asserts that the drain's budget fits inside supervisord's stop window, against a hand-copied `const supervisordStopWait = 20 * time.Second`. `docker/supervisord.d/relay-go.conf:34` is where that number actually lives. Change the conf and the test keeps asserting against the number it was written with, reporting green about a window that no longer exists — the derived-threshold hazard, in its purest form: **carry the formula and its denominator, never the bare number.**

**Fixed here, and the reason it is not the `"remux stderr"` rename of R15.** That rename was a log message somebody would prefer differently, conditioned on a refactor this PR declines. This is a *claim that can become false without anyone touching the test*, in a PR whose entire subject is replacing hand-copied claims with mechanical ones — the matrix's Go half, the floor's committed package list, the two shape hashes. A test that cannot notice its own premise moving is the same defect the rest of this PR exists to remove.

**The reason the test gives for copying is not true, and the counter-example is in this module.** Its comment says the conf "lives in a file this package cannot read". `relay/internal/relaytest/corpus.go` reads the Python harness's stderr fixtures from a Go test, resolving the repository from its own compiled-in path with `runtime.Caller` — precisely because `go test` sets the working directory to the package directory, which is a different depth for every package that asks. So the module already answers this question; the drain test simply did not use the answer.

**One repo-root answer, not two.** `relaytest.RepoRoot()` is exported (three lines wrapping the existing unexported `repoRoot()`) and `drain_test.go` reads the conf through it. A second, independently-maintained directory walk is the drift this avoids. `relay/internal/relaytest` is test support and **outside the coverage denominator by R1**, so exporting from it cannot move the gate; and `_test.go` imports do not enter `go list -deps .`, so `drain`'s test importing `relaytest` does not add a linked package either.

**It fails rather than skips or defaults** when the file or the key is absent. A helper that fell back to 20 would turn a renamed key into a permanently green test asserting a number nothing in the repository says any more — the silence-read-as-pass shape, one level up from the thing the test is for. The regex is anchored and comment-aware, so a `#stopwaitsecs=99` in a note is not read as the setting, which is also how supervisord's own parser behaves.

**Verified on `a635190c`**, 2c-8 as merged. Five break-checks, each reverted before the next:

| conf | expected | observed |
|---|---|---|
| `stopwaitsecs=10` | red, budget exceeds the window | `DefaultBudget is 15s against a stopwaitsecs of 10s: the drain would be SIGKILLed partway through, losing every release and every channel_stop` |
| `stopwaitsecs=16` | red, margin below 3s | `only 1s of margin between the drain budget and stopwaitsecs…` |
| `stopwaitsecs=60` | **green** | `ok` — the control that proves this is a bound, not an equality |
| key renamed to `stop_wait_secs` | red, naming the file and the key | `…declares no stopwaitsecs=<n>. Either supervisord's stop window for relay-go moved to another key, or it was removed…` |
| conf deleted | red, naming the file | `cannot read docker/supervisord.d/relay-go.conf: … -- this test's whole claim is a relationship between the drain's budget and that file's stopwaitsecs, so it must not pass without reading it` |

`gofmt -l` silent, `go vet` silent, `golangci-lint run ./drain/... ./internal/...` at `0 issues.`

**The `stopwaitsecs=60` row is the one that matters most**, and it is why the fix is not an equality check. Raising the window must not redden a test whose claim is that the budget *fits inside* it — though note that raising it is not free elsewhere: the conf's own header records that `relay-go` shares `priority=205` with `relay-uwsgi` precisely so its `stopwaitsecs` does not add a separate group to the container's 155 s stop budget against a 160 s `stop_grace_period`. That relationship is a different assertion and no test makes it; recorded here as a Phase 2d input rather than built.

---

## File structure

**Created:**

| Path | Responsibility |
|---|---|
| `scripts/coverage_relay_go.sh` | Measure, report, gate and write the floor. The only place that knows the measurement's shape. |
| `scripts/coverage_relay_go.floor` | The ratchet: `missing`, the shape fields, and the campaign that earned the number. |
| `scripts/coverage_relay_go.floor.packages` | The sorted linked-package list, so a `packages=` mismatch can name files rather than show two unequal hashes. |
| `apps/proxy/live_proxy/tests/test_relay_differential.py` | The cross-implementation differential (A2.4). One test. |

**Modified:**

| Path | Change |
|---|---|
| `.github/workflows/go-tests.yml` | `build` measures and uploads; new `coverage` and `differential` jobs; both added to `Go result`'s `needs` and its loop; the change detector learns three new paths. |
| `.github/workflows/codeql.yml` | A Go job, and `relay/**` on the push filter. |
| `e2e/tests/guards/parity-matrix.ts` | `GO_PARITY_CLOSED` and `goRefs()`. |
| `e2e/tests/guards/parity-matrix.spec.ts` | The eighth check. |
| `relay/channel/failover_test.go` | #309: the stamp moves to before the write. |
| `relay/drain/drain_test.go` | R16: `stopwaitsecs` is read from the conf, not restated. |
| `relay/internal/relaytest/corpus.go` | R16: `RepoRoot()` exported, three lines. |
| `relay/main.go` | One comment: the credential-logging rule has had a Go half since 2c-4 (R15). |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | Amendment A9 and the Done-log row. |
| `CLAUDE.md` | § Testing's "no coverage gate yet" paragraph, § Build reproducibility's CodeQL pack list, § Supply chain's CodeQL sentence. |

**Deliberately not touched, each for a stated reason:** `docs/relay-parity-matrix.md` (R11 — the check is in the guard; R14 — no line-number refresh); `metrics/curated/**` (R13); `relay/output/fmp4.go` (R15 — the split and its rename, both declined; `relay/main.go`'s comment is the one exception and R15 says why); `scripts/coverage_live_path*` and `dispatcharr/test_discovery.py` (R3 — this PR must not be able to break the Python gate); `docker/nginx.conf` (2d); any `apps/proxy/live_proxy/**` production module (2d deletes it).

---

## Task 0: Verify the seed against 2c-8 as merged

This plan was **re-seeded onto `a635190c`** (2c-8 as merged) and every figure, hunk and expected output in it was re-measured or re-captured there. This task is what confirms the tree the implementer starts from is still that one, and it runs before anything else. It was executed once already, at re-seed time, and every row below came back as expected — so a surprise here means `main` moved again, not that the expectation was a guess.

**Files:** none modified.

**Interfaces:**
- Consumes: the merged 2c-8 tree.
- Produces: a go/no-go for Tasks 1–9, and the real row-13 list for Task 7.

- [ ] **Step 1: Create the worktree and branch**

```bash
git -C /Users/dion/git/Dispatcharr fetch origin main
git -C /Users/dion/git/Dispatcharr worktree add \
  /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate \
  -b migration/phase2c-go-coverage-gate origin/main
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
git rev-parse HEAD
```

Expected: the printed SHA is **`a635190c`**, 2c-8 as merged (`relay(phase2): 2c-8 — control routes, the SIGTERM drain, the dev authorize fallback and the last parity pins (#315)`). If it is not, `origin/main` has moved past 2c-8; **stop and report** rather than guessing which commits are in between — every figure in this plan is measured on that commit.

- [ ] **Step 2: Confirm the four facts every later task depends on**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
test ! -e relay/go.sum && echo "go.sum absent: OK"
( cd relay && go list -deps . | grep '^github.com/D10Scot/Dispatcharr/relay' | sort )
grep -c "tests/" scripts/coverage_live_path.floor.modules
grep -n "GATE_1_CLOSED\|HIGHEST_ROW_ID" e2e/tests/guards/parity-matrix.ts
```

Expected, in order: `go.sum absent: OK`; a **ten**-line package list — `relay`, `buffer`, `channel`, `config`, `control`, **`drain`**, `ffmpeg`, `httpapi`, `output`, `redact`; `0`; and `GATE_1_CLOSED = true` with `HIGHEST_ROW_ID = 30`.

**`drain` is the expected tenth**, and it is expected rather than tolerated: `relay/main.go` imports it. Every figure in this plan was measured on `a635190c` with those exact ten, so Task 2 Step 2's expected output is a real number rather than a shape — but it still says to record what the script prints, because a local draw is a draw.

**An eleventh package, or a missing `drain`, is a stop-and-report.** Either is a denominator nobody has measured, and the response is to re-measure, not to proceed and let Task 8's campaign discover it twelve CI rounds later.

- [ ] **Step 3: Diff the merged tree against 2c-8's expectations**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
# The five control routes 2c-8 promised, in the Go route table:
grep -n 'mux.Handle\|mux.HandleFunc' relay/httpapi/server.go
# The drain, the real /readyz and the HEALTHCHECK:
ls relay/drain* 2>/dev/null; grep -rn "drain" relay/main.go | head
grep -n "HEALTHCHECK" docker/Dockerfile
# The dev-only authorize fallback:
grep -rn "_dispatcharr/authorize-internal" relay/ apps/ | head
```

Expected: `GET /proxy/relay/channels/{channelID}`, `DELETE` on the channel and on a client, `POST .../advance`, the XC live roots, `/healthz` and `/readyz` all present; a drain reachable from `main.go`; a `HEALTHCHECK` in the Dockerfile; and the `authorize-internal` fallback on both sides.

Also expected on the merged tree, from 2c-8's own review: `relay/drain/` as a package; `relay/httpapi/{control,advance,events,authorize,xc,drain,detail_golden,detail_builder}_test.go`; `docker/healthcheck.sh` at mode **100755** (`git ls-files -s docker/healthcheck.sh` — a healthcheck committed 100644 does not run); and Amendment **A8** with nine items, sitting between A7 and `## Stage 2d` in the spec.

**Anything absent is a stop-and-report, not a thing to build here.** 2c-9 owns the gate, not 2c-8's scope.

- [ ] **Step 4: Confirm the thirteen rows 2c-8 closed**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
awk -F'|' '/^\| [0-9]+ \|/ {n=$2; gsub(/^ +| +$/,"",n); printf "%s row %s\n", ($5 ~ /\.go/) ? "GO " : "---", n}' \
  docs/relay-parity-matrix.md | sort -k3 -n
```

Expected: **every** row `GO` except 26 and 27, which carry `white-box-only` and are neither. If any other row still shows `---`, Task 7's flag cannot be set to `true` — **stop and report**, naming the rows.

- [ ] **Step 5: Start your own test container**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
DISPATCHARR_TEST_CONTAINER=phase2c9 DISPATCHARR_TEST_DB_VOLUME=phase2c9-hookdb \
  .claude/hooks/start-test-container.sh
```

Expected: `==> ready`. Do **not** re-point `dispatcharr-testrunner`; another agent may hold it, and the `PostToolUse` hook refusing on a mismatch is the correct behaviour rather than a problem to work around.

- [ ] **Step 6: Take the baseline Go measurement, three times**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
for i in 1 2 3; do go test -count=1 -race ./... 2>&1 | grep -E '^(ok|FAIL|---)' ; echo "--- run $i ---"; done
```

Expected: every package `ok`, three times. A failure here is 2c-8's, not yours: **stop and report**. Note any `--- FAIL` line even if a later run passes — a flake in the seed poisons Task 8's census, and this is where to find out.

- [ ] **Step 7: Commit nothing.** This task writes no file.

---

## Task 1: Two Go tests that measure against the wrong source

Both are tests asserting a number against something other than where the number lives — #309 against a clock one layer off the monitor's, and the drain's window against a copy of a conf value. They are two commits inside one task because a reviewer would accept or reject them together: the same defect, in the same place, found by the same reading.

**Files:**
- Modify: `relay/channel/failover_test.go` (`deadAirSource.Run`)
- Modify: `relay/drain/drain_test.go` (`TestTheBudgetFitsInsideSupervisordsStopWindow`, plus a new `supervisordStopWait` helper)
- Modify: `relay/internal/relaytest/corpus.go` (export `RepoRoot()`)

**Interfaces:**
- Consumes: nothing.
- Produces: `relaytest.RepoRoot() string`, the module's one answer to "where is the repository from a test"; and a Go suite whose twelve-round CI census in Task 8 is not a coin toss.

- [ ] **Step 1: Read the two clocks and confirm the mechanism on this tree**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
grep -n "func (d dataClock) Write" -A 6 channel/health.go
grep -n "func (s deadAirSource) Run" -A 9 channel/failover_test.go
```

Expected: `dataClock.Write` sets `d.c.lastData = d.c.now()` **before** `d.c.ring.Write(p)`; `deadAirSource.Run` calls `s.lastWrite.set(time.Now())` **after** `sink.Write(payload)`. If either has moved, the fix below is against a different shape — re-derive it before editing.

- [ ] **Step 2: Measure the gap before changing anything**

The failure is one run in tens, so a pass/fail loop measures almost nothing. Log the gap instead. Add `t.Logf("GAPMEASURE %d", asked.Sub(wrote).Nanoseconds())` immediately after the `asked, wrote := …` line, build a test binary, and run it under load:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
go test -count=1 -c -o /tmp/chan_B.test ./channel/
for i in $(seq 1 28); do (while :; do :; done) & done
for i in $(seq 1 30); do /tmp/chan_B.test -test.run 'TestDeadAirOnAYoungConnectionSwitchesStreams' -test.count=1 -test.v 2>&1 | grep -o 'GAPMEASURE [0-9]*'; done
kill %1 %2 %3 %4 %5 %6 %7 %8 %9 %10 %11 %12 %13 %14 %15 %16 %17 %18 %19 %20 %21 %22 %23 %24 %25 %26 %27 %28
```

Expected: gaps clustered just above 400,000,000 ns with a minimum within a millisecond of it, and roughly one run in thirty **below** it. Measured on this tree: minimum 399.995 ms, one sub-400 in 30. **That thin margin is the finding** — not the individual failure.

- [ ] **Step 3: Instrument the monitor once, to see where the margin goes**

Add, temporarily, inside `monitorHealth`'s loop in `relay/channel/health.go` just after `threshold := c.inactivityThreshold()`:

```go
println("TICK inactivity_us", inactivity.Microseconds(), "threshold_us", threshold.Microseconds(), "unhealthyChecks", unhealthyChecks, "connected", c.connected, "head", int(c.ring.Head()))
```

Run the one test verbosely and read the ticks. Expected, and measured on this tree:

```
TICK inactivity_us 301093 threshold_us 300000 unhealthyChecks 0 connected true head 2
TICK inactivity_us 351729 threshold_us 300000 unhealthyChecks 1 connected true head 2
TICK inactivity_us 400631 threshold_us 300000 unhealthyChecks 2 connected true head 2
```

The tick grid is phased on the monitor's start, so the first tick past 300 ms lands at ~301 ms — the overshoot is ticker drift over six ticks — and the third unhealthy check two ticks later at ~400.6 ms. **The margin above a 400 ms floor is that drift, about a millisecond.** Note `unhealthyChecks 0` on the 301 ms tick: nothing is counted before the first byte, because `inactivityThreshold()` returns `InitGracePeriod` (60 s in `testTuning()`) while the ring is empty. **Revert this `println` before going on.**

- [ ] **Step 4: Apply the fix — the stamp move and the bound, together**

Both hunks are in **Appendix G**. The stamp moves before `sink.Write`, and the floor becomes `tuning.ConnectionTimeout + 2*tuning.HealthCheckInterval - tuning.HealthCheckInterval/10`. **The asserted count stays three**; only the clock tolerance moves.

- [ ] **Step 5: Prove it with a controlled A/B, both shapes, same host, same load**

Build three binaries — unmodified, stamp-only, stamp-plus-bound — each with the `GAPMEASURE` log, and run them **alternating within each round** so no shape gets a different machine:

```bash
for i in $(seq 1 30); do
  for shape in A B C; do
    /tmp/chan_${shape}.test -test.run 'TestDeadAirOnAYoungConnectionSwitchesStreams' -test.count=1 -test.v 2>&1 \
      | grep -oE 'GAPMEASURE [0-9]*|^(FAIL|--- FAIL)'
  done
done
```

Expected, and measured over two campaigns on this tree:

| shape | runs | sub-400 ms gaps | minimum |
|---|---|---|---|
| unmodified | 60 | 1 | 399.995 ms |
| stamp only | 60 | 2 | 399.960 ms |
| stamp + bound | 30 | 0 (against its own 395 ms floor) | 399.989 ms |

**The stamp move alone does not reduce the rate and the plan says so.** If your own A/B disagrees — if the stamp-only shape is clearly better on your host — say so in the PR description with the table, because that would mean the residual is host-dependent in a way this measurement did not see.

- [ ] **Step 5b: Break-check — the bound still catches a monitor that acts early**

Set `maxUnhealthyChecks = 2` in `relay/channel/failover.go` (it is `3`), run the one test, then restore:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
go test -count=1 -race -run 'TestDeadAirOnAYoungConnectionSwitchesStreams' ./channel/ 2>&1 | grep failover_test
```

Expected: **red**, naming the gap —

```
failover_test.go:390: the resolver was asked 350.988791ms after the last byte, under CONNECTION_TIMEOUT + two more checks less a tenth of an interval (395ms): the monitor did not wait for three consecutive checks
```

44 ms of margin against a 5 ms tolerance, which is what says the tolerance did not buy the fix at the cost of the assertion.

**Re-run until red: this break-check is itself intermittent.** 36 of 36 red here (12 unloaded, 24 loaded, gaps 350.1–352.0 ms), but 9 of 12 on a second rig, with 3 green at 400.17, 401.74 and 401.80 ms. The greens are the phase effect one step earlier — whether the first tick past `ConnectionTimeout` lands at ~301 ms or ~351 ms decides whether the *second* check lands at ~351 ms or ~401 ms — and they are **above 400 ms**, so the tolerance is not what lets them through; they would have passed the old bound too. A single green run is not evidence the break-check is broken.

**`maxUnhealthyChecks = 1` is host-dependent and must not be cited as the evidence.** On this host it reddens through the earlier `the channel was never observed unhealthy before it switched` — the switch outruns the poll — while on another it reddens through the gap at ~301 ms. Run it if you like; quote `= 2`.

Restore `3` and confirm eight consecutive green `-race` runs of the package before committing.

- [ ] **Step 6: Commit**

```bash
git add relay/channel/failover_test.go
```

Then, separately, with the message written to a file:

```bash
git commit -F /tmp/2c9-msg-1.txt
```

Message subject: `test(relay): widen the dead-air bound past the ticker's own drift (#309)`

- [ ] **Step 7: Confirm the drain test's stale premise on the merged tree**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
grep -n "supervisordStopWait\|cannot read" relay/drain/drain_test.go | head
grep -n "^stopwaitsecs" docker/supervisord.d/relay-go.conf
grep -n "func repoRoot" -A 8 relay/internal/relaytest/corpus.go
```

Expected: a `const supervisordStopWait = 20 * time.Second` with a comment claiming the conf "lives in a file this package cannot read"; `stopwaitsecs=20` in the conf; and `repoRoot()` resolving the repository from `runtime.Caller`, which is the counter-example to that claim. If the test already reads the conf, 2c-8's fix round did this — **skip to Step 11** and say so.

- [ ] **Step 8: Apply Appendix G**

The `relay/internal/relaytest/corpus.go` and `relay/drain/drain_test.go` halves of **Appendix G** — `RepoRoot()` exported, and the helper replacing the constant. Appendix G is one diff over four files; its other two (`failover_test.go`, `main.go`) belong to Steps 3 and to Task 2 Step 7 and are applied there.

- [ ] **Step 9: Run it**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
gofmt -l .
go vet ./drain/ ./internal/relaytest/
go test -count=1 -race ./drain/
golangci-lint run ./drain/... ./internal/...
```

Expected: `gofmt -l` silent, vet silent, `ok …/relay/drain`, `0 issues.`

- [ ] **Step 10: Five break-checks on the conf, each reverted before the next**

Edit `docker/supervisord.d/relay-go.conf` and re-run `go test -count=1 -race -run 'TestTheBudgetFitsInsideSupervisordsStopWindow' ./drain/` each time.

| conf | expected |
|---|---|
| `stopwaitsecs=10` | **red**: `DefaultBudget is 15s against a stopwaitsecs of 10s: the drain would be SIGKILLed partway through…` |
| `stopwaitsecs=16` | **red**: `only 1s of margin between the drain budget and stopwaitsecs…` |
| `stopwaitsecs=60` | **green** |
| key renamed to `stop_wait_secs` | **red**: `…declares no stopwaitsecs=<n>…` |
| the conf deleted | **red**: `cannot read docker/supervisord.d/relay-go.conf: …` |

**The `stopwaitsecs=60` row is not padding.** It is the control that proves the fix is a bound rather than an equality; without it, a helper that asserted `== 20` would pass the other four and be wrong. Restore `stopwaitsecs=20` and confirm green before committing.

- [ ] **Step 11: Commit, separately from Step 6's**

```bash
git add relay/drain/drain_test.go relay/internal/relaytest/corpus.go
```

Separately: `git commit -F /tmp/2c9-msg-1b.txt`, subject `test(relay): read supervisord's stop window rather than restating it`.

---

## Task 2: The gate script

**Files:**
- Create: `scripts/coverage_relay_go.sh` (Appendix A, verbatim)

**Interfaces:**
- Consumes: `relay/go.mod`, and `go list -deps .`.
- Produces: `--measure <dir>` writes `<dir>/relay.coverprofile` and `<dir>/relay.packages`; `--report <dir>`, `--gate <dir>`, `--write-floor [--shape-only] <dir>` read them. `--gate` exits 0 when no floor file exists, saying so; exits 1 on any shape mismatch or a `missing` above the floor.

- [ ] **Step 1: Write the script**

Create `scripts/coverage_relay_go.sh` with the contents of **Appendix A**, verbatim, and `chmod +x` it.

- [ ] **Step 2: Syntax-check it, then measure**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
bash -n scripts/coverage_relay_go.sh && echo "syntax OK"
bash scripts/coverage_relay_go.sh --measure /tmp/relay-go-coverage
bash scripts/coverage_relay_go.sh --report /tmp/relay-go-coverage
```

Expected: a **ten**-row per-package table, two `~out of scope` lines naming `internal/credlint` and `internal/relaytest`, and a summary line of the shape

```
coverage_relay_go: shape=go-race-per-package/v1  packages=10  statements=3696  missing=587  coverage=84.12%
```

`missing` will be **586, 587 or 588** — two blocks flap and which of them does is host-dependent (R5). **Record whatever it prints; it is Task 8's local design figure, not the floor.** `statements=3696` and `packages=10` are not expected to vary at all: if either does, something is in the denominator that this plan did not measure, and that is Task 0 Step 2's stop-and-report arriving late.

- [ ] **Step 3: Verify the bootstrap branch**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
bash scripts/coverage_relay_go.sh --gate /tmp/relay-go-coverage; echo "exit=$?"
```

Expected: `NO FLOOR at …` plus `this run statements=3696 missing=587 coverage=84.12% packages=0321b777fc5d (10)`, and `exit=0`.

- [ ] **Step 4: Write a throwaway floor and verify the gate passes**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
bash scripts/coverage_relay_go.sh --write-floor /tmp/relay-go-coverage
bash scripts/coverage_relay_go.sh --gate /tmp/relay-go-coverage; echo "exit=$?"
```

Expected: the floor is created with a stub header, and the gate prints `GATE PASSED.` with `exit=0`.

- [ ] **Step 5: Break-check all seven failure modes**

Run each, confirm the message **names the mechanism**, and restore between them. Keep backups: `cp scripts/coverage_relay_go.floor /tmp/floor.bak; cp scripts/coverage_relay_go.floor.packages /tmp/floorpkg.bak; cp /tmp/relay-go-coverage/relay.coverprofile /tmp/p.bak; cp /tmp/relay-go-coverage/relay.packages /tmp/rp.bak`.

| # | Mutation | Expected message (first line) |
|---|---|---|
| 1 | lower `missing=` in the floor by 38 | `GATE FAILED -- 38 more missed statements than the floor.` |
| 2 | append a fake package to `scripts/coverage_relay_go.floor.packages` | `GATE FAILED -- …floor.packages does not match the floor's packages= hash.` |
| 3 | set `gomod=deadbeef0000` in the floor | `GATE FAILED -- relay/go.mod changed (floor deadbeef0000, now …).` |
| 4 | set `shape=` to anything else | `GATE FAILED -- shape mismatch: floor "…", this run "go-race-per-package/v1".` |
| 5 | append five duplicate block lines to the profile | `the profile repeats block …` — and the message must say `-coverpkg` |
| 6 | `grep -v '^github.com/D10Scot/Dispatcharr/relay/redact/' /tmp/p.bak > …/relay.coverprofile` | `these linked packages are in the scope list but have NO block in the profile: …/redact` |
| 7 | `grep -v '/redact$' /tmp/rp.bak > …/relay.packages` | `GATE FAILED -- the linked package set changed.` plus a `< …/redact` diff line |
| 8 | set `missing=<MAX>` in the floor (an unfilled template) | `GATE FAILED -- the floor's missing= is [<MAX>], not a decimal integer.` |

All eight were verified on `a635190c`; each exits 1.

**Row 8 is the one this gate nearly shipped without.** `[ "$missing" -gt "<MAX>" ]` does not abort the script: bash prints "integer expected", the test exits 2, the `if` is false, and the gate reported `GATE PASSED` on a floor it could not read — a check green because it could not look, which is the exact failure this whole file exists to prevent one level up. It was found by running Appendix E's template through the tool rather than by reading either, and it is why Task 8 Step 4 gates against the floor it just wrote instead of assuming a hand-edit landed.

- [ ] **Step 6: Verify `--write-floor --shape-only` preserves prose**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
printf '# CAMPAIGN PROSE LINE THAT MUST SURVIVE\n' >> scripts/coverage_relay_go.floor
bash scripts/coverage_relay_go.sh --write-floor --shape-only /tmp/relay-go-coverage
grep -c "CAMPAIGN PROSE" scripts/coverage_relay_go.floor
```

Expected: `re-baselined shape/packages/package_count/gomod only; missing unchanged at …`, then `1`. This is the check that matters most about this script: the floor's header carries the campaign, and a tool that rewrote the file wholesale would delete it on every re-baseline.

- [ ] **Step 7: Correct `relay/main.go`'s claim that there is no Go credential-logging check**

One comment, in the file a reader of this module opens first. Replace:

```go
	// The secret is never logged, in any form, at any level -- not its value,
	// not its length, not a prefix. scripts/check_credential_logging.py polices
	// the Python side of this rule; there is no Go equivalent yet, so it is
	// held by hand here.
```

with:

```go
	// The secret is never logged, in any form, at any level -- not its value,
	// not its length, not a prefix. scripts/check_credential_logging.py polices
	// the Python side of this rule and scripts/check_go_credential_logging.sh
	// (relay/internal/credlint, 2c-4) polices this one -- but neither sees a
	// secret that is not an ERROR, so this particular line is still held by
	// hand: credlint checks error-typed arguments, and cfg.Secret is a string.
```

**Disclosed as a one-liner outside this task's subject, and it is a `.go` file**, so the `PostToolUse` Go hook fires on it: `go build ./...`, `go vet ./...` and `golangci-lint run` over the whole module, plus `go test -race` for the edited file's package — which is `main`, and has no test files, so that last part reports nothing. Run the three by hand as well, because a hook that runs is not a result you have read:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
gofmt -l .
go build ./... && go vet ./... && GOOS=linux go vet ./... && GOOS=darwin go vet ./...
golangci-lint run ./...
cd .. && scripts/check_go_credential_logging.sh relay
```

Expected: `gofmt -l` silent, build and all three vets silent, `0 issues.`, and `credlint: N package(s) clean`. Verified on `a635190c`: gofmt clean, build OK, vet ×3 OK, `0 issues.` under all three GOOS, and `credlint: 12 package(s) clean`.

It changes no statement, so it cannot move the coverage denominator — but it is committed **with the script**, before Task 8 writes the floor, so there is no commit in between where the tree and the floor disagree.

- [ ] **Step 8: Delete the throwaway floor and commit the script alone**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
rm -f scripts/coverage_relay_go.floor scripts/coverage_relay_go.floor.packages
git status --short
git add scripts/coverage_relay_go.sh relay/main.go
```

The floor is written for real in Task 8, from the CI census. Committing a placeholder here would make the workflow gate against a local number for the intervening commits.

Then, separately: `git commit -F /tmp/2c9-msg-2.txt`, subject `build(relay): the Go coverage gate's measurement and ratchet script`.

---

## Task 3: Wire the gate into `go-tests.yml`

**Files:**
- Modify: `.github/workflows/go-tests.yml` (the `changes` filter, the `build` job's test step, a new `coverage` job, `go-result`)

**Interfaces:**
- Consumes: `scripts/coverage_relay_go.sh` from Task 2.
- Produces: an artifact named `relay-go-coverage` holding `relay.coverprofile` and `relay.packages`; a `Coverage gate` job whose log line `this run missing=N` is what Task 8's census reads.

- [ ] **Step 1: Re-resolve every action pin this PR uses**

```bash
gh api repos/actions/upload-artifact/commits/v4.6.2 --jq .sha
gh api repos/actions/download-artifact/commits/v4.3.0 --jq .sha
gh api repos/actions/checkout/commits/v7.0.1 --jq .sha
gh api repos/actions/setup-go/commits/v7.0.0 --jq .sha
```

**Corrected during 2c-9's implementation** (see the spec's Amendment A9.12 and the Done-log row): the earlier text here appended a `--repo D10Scot/Dispatcharr` flag to the first call. `gh api` has no `--repo` flag — it errors `unknown flag: --repo` — and the flag would have been semantically wrong even if it existed: the endpoint's own path (`repos/actions/upload-artifact/...`) already names the repository whose tag is being resolved, and it is not this fork. Run without the flag, as above.

Expected: four 40-character SHAs. **Use whatever the tool returns today**, not the values written in Appendix C — those are what the seed tree already carries and are reproduced so the diff applies, not as authority. If any differs, update the appendix's line and say so in the PR description. Confirm each `<owner>/<repo>` is the real publisher before pinning (e.g. `gh api repos/actions/checkout --jq '.full_name, .owner.login'`).

- [ ] **Step 2: Apply the `go-tests.yml` half of Appendix C**

Four edits, in the file's own order: the header comment, the `changes` job's `pattern=` line and its explanation, the `build` job's test step (replaced by a measure step plus an upload step), and — after the `lint` job — the new `coverage` job. Then the `go-result` job's `needs`, its `env`, its `echo`, its loop and its final message.

- [ ] **Step 3: Lint the workflow**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
actionlint .github/workflows/go-tests.yml && echo "actionlint OK"
GH_TOKEN="$(gh auth token)" zizmor .github/workflows/go-tests.yml
```

Expected: actionlint silent; zizmor `No findings to report.` **Online, not offline** — the `impostor-commit` audit is invisible offline and is exactly what catches a SHA from the wrong repository. If zizmor's local version differs from the `version:` pinned in `.github/workflows/actions-lint.yml`, say so in the PR description rather than bumping one of them here.

- [ ] **Step 4: Prove the `build` job's step still runs the suite it replaced**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
grep -n "go test" scripts/coverage_relay_go.sh
```

Expected: exactly one line, carrying `-count=1 -race -covermode=atomic`. The step this PR deletes was `go test -race ./...`; the step that replaces it must be a superset, or the workflow quietly stops running the race detector.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/go-tests.yml
```

Separately: `git commit -F /tmp/2c9-msg-3.txt`, subject `ci(relay): measure Go coverage in the build job and gate it on a bare runner`.

---

## Task 4: The cross-implementation differential

**Files:**
- Create: `apps/proxy/live_proxy/tests/test_relay_differential.py` (Appendix B, verbatim)
- Modify: `.github/workflows/go-tests.yml` (the `differential` job, and `go-result`)

**Interfaces:**
- Consumes: `harness.asset`'s `TS_PACKET_SIZE`, `assert_ts_aligned`, `packet_index`; `harness.control`'s `ControlMixin`, `nginx_headers`; `harness.relay`'s `RelayHarnessTestCase`, `wait_until`; `manager_support`'s `proxy_stream_profile`. Every one of these exists on the seed tree and was called in a passing run.
- Produces: `DISPATCHARR_RELAY_GO_BIN` as the switch that makes the test run; `/tmp/differential.log` as the evidence the workflow's anti-skip step reads.

- [ ] **Step 1: Confirm every symbol the test calls exists**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
grep -n "^TS_PACKET_SIZE\|^def packet_index\|^def assert_ts_aligned" apps/proxy/live_proxy/tests/harness/asset.py
grep -n "^def nginx_headers\|^class ControlMixin\|    def set_proxy_setting" apps/proxy/live_proxy/tests/harness/control.py
grep -n "^def wait_until\|^class RelayHarnessTestCase\|    def make_channel\|    def stop_channel" apps/proxy/live_proxy/tests/harness/relay.py
grep -n "^def proxy_stream_profile" apps/proxy/live_proxy/tests/manager_support.py
grep -n "class RelayHarnessTestCase(LiveServerTestCase)" apps/proxy/live_proxy/tests/harness/relay.py
grep -n "DISPATCHARR_INTERNAL_API_BASE_URL" apps/proxy/live_proxy/tests/harness/relay.py
```

Expected: every grep matches. The last two are the load-bearing ones: the base class must be a `LiveServerTestCase` and must already export `DISPATCHARR_INTERNAL_API_BASE_URL = self.live_server_url`, because that is what lets the Go subprocess call the real Django with no stub.

- [ ] **Step 2: Confirm the Go relay's own switches have not moved**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
grep -n "DISPATCHARR_RELAY_GO_PORT\|DISPATCHARR_RELAY_GO_DEV_ROUTES\|DJANGO_SECRET_KEY" config/config.go
grep -n "DISPATCHARR_INTERNAL_API_BASE_URL" control/baseurl.go
grep -n 'GET /proxy/ts/stream/{channelID}' httpapi/server.go
grep -n "RelayTrustToken\|HeaderAuthorized" control/token.go
```

Expected: all five. The stream route is behind `cfg.DevRoutes`, which is why the test sets `DISPATCHARR_RELAY_GO_DEV_ROUTES=true`.

- [ ] **Step 3: Write the test**

Create `apps/proxy/live_proxy/tests/test_relay_differential.py` with the contents of **Appendix B**, verbatim.

The `PostToolUse` hook will refuse to run the label if the shared `dispatcharr-testrunner` container is mounted elsewhere. **That refusal is correct.** Do not re-point the shared container; run the label yourself in Step 5.

- [ ] **Step 4: Cross-compile `relay-go` into your own container**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
docker exec phase2c9 uname -m      # aarch64 or x86_64
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o /tmp/relay-go .   # GOARCH=amd64 on x86_64
docker cp /tmp/relay-go phase2c9:/tmp/relay-go
docker exec phase2c9 /tmp/relay-go 2>&1 | head -2
```

Expected: the binary starts and exits with `startup failed: reading secret file /data/jwt: open /data/jwt: no such file or directory`. That is the right failure — it proves the binary runs in the container and that it refuses to boot without a secret rather than inventing one.

- [ ] **Step 5: Run the label in your own container**

```bash
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
  -e DISPATCHARR_RELAY_GO_BIN=/tmp/relay-go \
  phase2c9 /dispatcharrpy/bin/python manage.py test --keepdb -v2 \
  apps.proxy.live_proxy.tests.test_relay_differential 2>&1 | tail -20
```

Expected: `Ran 1 test in ~6.5s` and `OK`, plus a `relay-go said:` block showing `starting on port …(dev routes: true)`, `connection attempt channel=…`, `channel stopped channel=…`, then `received terminated, draining`, `INFO draining budget=15s client_grace=5s` and `INFO drained elapsed=5.00…s`. The first three are the proof that the Go relay reached the real Django `next-source` and streamed; the last three are 2c-8's drain running on the test's own `SIGTERM`, and they are why the module takes 6.5 s rather than the 2.3 s it took before 2c-8.

- [ ] **Step 6: Confirm the skip path, which is the common case**

```bash
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
  phase2c9 /dispatcharrpy/bin/python manage.py test --keepdb -v2 \
  apps.proxy.live_proxy.tests.test_relay_differential 2>&1 | tail -6
```

Expected: `OK (skipped=1)` and the skip reason naming `DISPATCHARR_RELAY_GO_BIN`. This is what `backend-tests.yml` sees, in both its `test` and its `coverage-label` jobs — deterministically, which is what keeps Gate 2's Python census unperturbed.

- [ ] **Step 6b: Break-check — a corrupting relay must redden the comparison**

The differential's whole claim is that a byte-level divergence shows up. Prove it by building a relay that introduces one. In `relay/channel/health.go`'s `dataClock.Write`, between the `mu.Unlock()` and the `ring.Write`:

```go
	if len(p) > 100 {
		p[100] ^= 0xFF
	}
```

Offset 100 is inside a packet's filler — outside the sync byte, the PID, the continuity counter and the four-byte embedded index — so the packet still parses, still aligns and still carries its own index. Only the payload differs, which is exactly the divergence a body digest would find and a structural check might not.

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build -o /tmp/relay-go-corrupt .   # GOARCH=amd64 on x86_64
docker cp /tmp/relay-go-corrupt phase2c9:/tmp/relay-go-corrupt
```

Re-run Step 5 with `DISPATCHARR_RELAY_GO_BIN=/tmp/relay-go-corrupt`. Expected: **red**, with

```
AssertionError: … : packet index 0 differs between the two relays. This is a byte-level
divergence on the live path, not a timing difference: both relays were served the same
asset from its start.
```

**Revert `health.go` by restoring the file**, rebuild the good binary, and confirm Step 5 is green again before going on. Keep the corrupt binary: Step 7b uses it.

- [ ] **Step 7: Break-check the anti-silence guard**

The workflow step that asserts the test ran must actually fail on the skip output. Check it against the log Step 6 just produced:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
printf 'Ran 1 test in 0.001s\n\nOK (skipped=1)\n' > /tmp/fake-skip.log
grep -qE '^Ran [1-9][0-9]* tests?' /tmp/fake-skip.log && echo "count check PASSES (expected)"
grep -q 'skipped=' /tmp/fake-skip.log && echo "skip check FIRES (expected)"
```

Expected: both lines print. The count check alone would pass a skipped run — which is exactly why there are two.

- [ ] **Step 7b: Break-check — restore the pipe and watch a failing test report green**

The job runs its command through `scripts/ci_bootstrap_backend.sh`'s `exec bash -c "$CI_BACKEND_RUNNER"` — **a fresh shell with no `pipefail`** — so a `… | tee` runner exits with `tee`'s status and a failing test reports success. Appendix C redirects instead. Prove the hole is real, with the corrupting binary from Step 6b:

```bash
CMD='cd /repo && /dispatcharrpy/bin/python manage.py test --keepdb apps.proxy.live_proxy.tests.test_relay_differential'
# the shape this PR REPLACES:
docker exec <the env flags> -e DISPATCHARR_RELAY_GO_BIN=/tmp/relay-go-corrupt phase2c9 \
  bash -c "$CMD 2>&1 | tee /tmp/d.log" >/dev/null 2>&1; echo "exit=$?"
# the shape it ships:
docker exec <the env flags> -e DISPATCHARR_RELAY_GO_BIN=/tmp/relay-go-corrupt phase2c9 \
  bash -c "$CMD > /tmp/d2.log 2>&1" >/dev/null 2>&1; echo "exit=$?"
docker exec phase2c9 grep -E '^(Ran|FAILED|OK)' /tmp/d.log /tmp/d2.log
```

Expected, and measured on this tree:

| runner shape | exit | log |
|---|---|---|
| `… 2>&1 \| tee /tmp/d.log` | **0** | `Ran 1 test in 6.522s` / `FAILED (failures=1)` |
| `… > /tmp/d2.log 2>&1` | **1** | `Ran 1 test in 6.429s` / `FAILED (failures=1)` |

**And the two-assertion version of Step 7's guard passes that log**, which is why Appendix C carries a third assertion on the final status line:

```bash
printf 'Ran 1 test in 6.4s\n\nFAILED (failures=1)\n' > /tmp/l-fail.log
grep -qE '^Ran [1-9][0-9]* tests?' /tmp/l-fail.log && echo "count check PASSES (the hole)"
grep -q 'skipped=' /tmp/l-fail.log || echo "skip check PASSES (the hole)"
grep -qE '^OK$' /tmp/l-fail.log || echo "OK check FIRES (the fix)"
```

Expected: all three lines print. Exercise the guard on all four log shapes — `OK`, `FAILED`, `OK (skipped=1)`, `Ran 0 tests` — and confirm the first exits 0 and the other three exit 1.

- [ ] **Step 8: Run the whole label, to be sure the new file breaks nothing**

```bash
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
  phase2c9 /dispatcharrpy/bin/python manage.py test --keepdb \
  apps.proxy.live_proxy.tests 2>&1 | tail -5
```

Expected: `Ran 429 tests … OK (skipped=1)` — measured on `a635190c` in 67.7 s. The one skip is this test; if the count is higher, something else in the label is skipping and it is not this PR's doing.

**One failure in this label is expected noise and is re-run rather than investigated**: `test_a_buffering_threshold_change_does_not_reach_a_running_channel` is the pre-existing, timing-driven flake of [#273](https://github.com/D10Scot/Dispatcharr/issues/273). It reddened once and passed on the immediate re-run while preparing this plan, on a tree where this PR touches nothing it uses. Any *other* failure is this PR's to explain.

- [ ] **Step 9: Credential check**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
python3 scripts/check_credential_logging.py apps/proxy/live_proxy/tests/test_relay_differential.py
```

Expected: exit 0, no output.

- [ ] **Step 10: Add the `differential` job to the workflow**

Apply the second half of Appendix C's `go-tests.yml` diff: the `differential` job, and the `go-result` changes that add it. Then lint again:

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
actionlint .github/workflows/go-tests.yml && echo "actionlint OK"
GH_TOKEN="$(gh auth token)" zizmor .github/workflows/go-tests.yml
```

Expected: silent; `No findings to report.`

- [ ] **Step 11: Commit**

```bash
git add apps/proxy/live_proxy/tests/test_relay_differential.py .github/workflows/go-tests.yml
```

Separately: `git commit -F /tmp/2c9-msg-4.txt`, subject `test(phase2): drive both relays from the same bytes (Amendment A2.4)`.

---

## Task 5: CodeQL's Go pack

**Files:**
- Modify: `.github/workflows/codeql.yml`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a fourth CodeQL analysis, `Analyze (go)`, on push to `main`, weekly, and on dispatch.

- [ ] **Step 1: Apply the `codeql.yml` half of Appendix C**

Three edits: the header comment's language list, `relay/**` on the `push` `paths:` filter, and the `analyze-go` job inserted **above** the existing `analyze` matrix job so the matrix is untouched.

- [ ] **Step 2: Confirm the pins**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
grep -n "uses:" .github/workflows/codeql.yml
```

Expected: every `uses:` is a 40-hex SHA with a version comment, and the two `github/codeql-action/*` SHAs in the new job are **identical** to the ones the existing `analyze` job already uses. Two different CodeQL action versions in one workflow is a drift this PR must not introduce.

- [ ] **Step 3: Lint**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
actionlint .github/workflows/codeql.yml && echo "actionlint OK"
GH_TOKEN="$(gh auth token)" zizmor .github/workflows/codeql.yml
```

Expected: silent; `No findings to report.`

- [ ] **Step 4: Prove the build step is reachable from where the job runs it**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/relay
go build ./...
```

Expected: silent. `build-mode: manual` means CodeQL extracts whatever this command compiles; if it fails, the analysis silently sees nothing. That is the whole reason the mode is `manual` rather than `autobuild`, which would look for a `go.mod` at the repository root and find none.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/codeql.yml
```

Separately: `git commit -F /tmp/2c9-msg-5.txt`, subject `ci: analyse the relay module with CodeQL's Go pack (Amendment A1.5)`.

---

## Task 6: The matrix's eighth guard check

**Files:**
- Modify: `e2e/tests/guards/parity-matrix.ts` (`GO_PARITY_CLOSED`, `goRefs`)
- Modify: `e2e/tests/guards/parity-matrix.spec.ts` (the eighth check, the header comment, the import list)

**Interfaces:**
- Consumes: `parsePin`, `Pin`, `TestRef` — all already exported from `parity-matrix.ts`.
- Produces: `GO_PARITY_CLOSED`, which stage 2d reads as the machine-checkable form of its own precondition.

- [ ] **Step 1: Install the e2e dependencies**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/e2e
npm ci --prefer-offline --no-audit --no-fund
```

Expected: `added N packages`. A symlink to another checkout's `node_modules` does **not** work — Node resolves from the importing file's real path and `typescript` will not be found.

- [ ] **Step 2: Run the guard as it stands**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/e2e
npx playwright test --project=guards parity-matrix
```

Expected: `7 passed`, with `parity matrix: 30 rows — 28 pinned, 0 owed, 2 white-box-only.`

- [ ] **Step 3: Apply Appendix D**

Both hunks: `GO_PARITY_CLOSED` plus `goRefs()` at the end of `parity-matrix.ts`, and the eighth test plus the import and header-comment edits in `parity-matrix.spec.ts`.

The `PostToolUse` hook runs `tsc --noEmit` over `e2e/` on any `*.ts` edit and is blocking. Both files must typecheck.

- [ ] **Step 4: Run it with the flag `true` (the state this PR ships)**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/e2e
npx playwright test --project=guards parity-matrix
```

Expected on the 2c-8 tree: `8 passed`, logging `parity matrix (Go): 28 of 28 pinned rows carry a Go reference; 2 row(s) are not pinnable.`

**If it fails**, it will name the rows that lack a Go reference — which means Task 0 Step 4 was wrong or 2c-8 left a row open. Stop and report; do not flip the flag to `false` to make it pass. The flag is the claim, not the workaround.

- [ ] **Step 5: Break-check both branches**

First, remove a Go reference from a row's `Pin` cell (row 1 is fine) and re-run:

Expected: the eighth check fails, naming `Rows with a Python pin and no Go one: 1.` Restore the cell.

Second, flip `GO_PARITY_CLOSED` to `false` and re-run:

Expected: the eighth check fails with `No pinned row lacks a Go reference any more — you just closed the last one. Flip GO_PARITY_CLOSED to true …`. Restore `true`.

Both branches must be exercised. On the seed tree (before 2c-8) they were verified in the opposite states: `true` failed naming `14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 30`, and `false` passed logging `15 of 28`.

- [ ] **Step 6: Typecheck and commit**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate/e2e
npx tsc --noEmit
cd ..
git add e2e/tests/guards/parity-matrix.ts e2e/tests/guards/parity-matrix.spec.ts
```

Separately: `git commit -F /tmp/2c9-msg-6.txt`, subject `test(phase2): assert every pinnable parity row carries a Go reference`.

---

## Task 7: Open the PR and take the CI census

This is the task with the longest wall-clock and the least typing. It cannot start before Tasks 1–6 are pushed, because the census measures the workflow as it will be merged.

**Files:** none yet — Task 8 writes the floor.

**Interfaces:**
- Consumes: the `Coverage gate` job's log line `coverage_relay_go: floor missing=… this run missing=N` — or, while there is no floor, `this run statements=… missing=N …`.
- Produces: an ordered list of ≥12 CI draws.

- [ ] **Step 1: Push the branch and open a draft PR**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
git push -u origin migration/phase2c-go-coverage-gate
gh pr create --repo D10Scot/Dispatcharr --draft --base main \
  --title "coverage(phase2): 2c-9 — the Go coverage gate, and 2c's close-out" \
  --body-file /tmp/2c9-pr-body.md
```

The body is a placeholder at this point; Task 9 replaces it.

- [ ] **Step 2: Confirm the first run's shape before spending twelve of them**

```bash
gh run list --repo D10Scot/Dispatcharr --workflow go-tests.yml --branch migration/phase2c-go-coverage-gate --limit 1
gh run view --repo D10Scot/Dispatcharr <run-id> --log --job "Coverage gate" | grep "coverage_relay_go:"
```

Expected: `NO FLOOR at …` and `this run statements=3696 missing=N coverage=…% packages=0321b777fc5d (10)`, and the job **green**. Also confirm `Cross-implementation differential` and `Go result` are green.

**If `Coverage gate` is red on the first run, stop.** A red gate with no floor file means the parse failed, not that coverage regressed — read which of the seven messages it printed.

- [ ] **Step 3: Take the census**

Dispatch the workflow repeatedly on the branch and record `missing=` from each `Coverage gate` job, **in order**:

```bash
gh workflow run go-tests.yml --repo D10Scot/Dispatcharr --ref migration/phase2c-go-coverage-gate
# wait for it to finish, then:
gh run view --repo D10Scot/Dispatcharr <run-id> --log --job "Coverage gate" | grep "this run"
```

`go-tests.yml`'s concurrency group is per-ref with `cancel-in-progress`, so rounds on one branch are **sequential, not parallel** — dispatch the next only after the previous `Coverage gate` job has concluded.

**Stopping rule:** the maximum unchanged for ≥6 consecutive rounds, with ≥12 rounds total. Record every round in order; a bare min/max cannot show the rule was met.

- [ ] **Step 4: If the measured coverage is below 80%, do not lower anything**

Compute the ceiling from the run's own denominator: `ceiling = statements - ceil(0.8 × statements)`. On `a635190c` that is `3696 - 2957 = 739` against a local `missing` of 587–588 — **151–152 statements of margin**. (On the 2c-7 seed it was `2956 - 2365 = 591` against 338, a margin of 253: 2c-8's own additions are 66.4% covered at the margin and that is where the other hundred went.) A CI draw is expected to be worse than a local one, and 151 statements absorbs far more than the Python gate's largest observed local-to-CI delta of 35.

If `max(rounds)` exceeds the ceiling, the spec's ≥80% is not met, and there are exactly two legitimate responses: **name the packages that owe the shortfall** and add tests in this PR, or **amend the spec in-PR with a Done-log entry** saying the requirement moved and to whom. A lower floor with no statement either way is not one of them.

The per-package table `--report` prints is where that naming comes from, and on `a635190c` the answer is already known: `relay/channel` (219 missing of 1,063, 79.40%) and `relay/control` (94 of 404, 76.73%) hold **313 of the 587** between them, and are the only two packages individually under 80%. Read that table, not the single total — the total cannot tell one package worsening from another improving, which is the shape D7 exists to catch.

- [ ] **Step 5: Record the census**

Write the ordered sequence, `max`, `min`, `spread`, `n`, the round the maximum was set in, and which rounds carry any unrelated damage (a cancelled sibling job, say) into `/tmp/2c9-census.txt`. Task 8 pastes it into the floor's header.

---

## Task 8: Write the floor and its provenance

**Files:**
- Create: `scripts/coverage_relay_go.floor`
- Create: `scripts/coverage_relay_go.floor.packages`

**Interfaces:**
- Consumes: Task 7's census.
- Produces: the ratchet every later PR is held to, and the `Refuse a floor edited downward or deleted` step's base-ref comparison from here on.

- [ ] **Step 1: Machine-produce the file format**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
bash scripts/coverage_relay_go.sh --measure /tmp/relay-go-coverage
bash scripts/coverage_relay_go.sh --write-floor /tmp/relay-go-coverage
cat scripts/coverage_relay_go.floor
```

Expected: a stub header and nine `key=value` lines. The `missing` written here is **this local run's**, which is almost certainly not `max(rounds)`.

- [ ] **Step 2: Hand-edit `missing` to `max(rounds)` and recompute `percent`**

`percent = (1 - missing/statements) × 100`, to two places. This hand-edit is the documented step, not a workaround: `--write-floor` writes the figure from the run it just took and cannot know it is the Nth of a campaign, exactly as `scripts/coverage_live_path.floor`'s own procedure records.

Also set `runs=` to the census's `n` and `measured=` to today's date.

- [ ] **Step 3: Replace the stub header with the campaign**

Use **Appendix E** as the template. It must carry, at minimum:

1. That `missing` is a **maximum**, lower is better, set from the worst of ≥12 CI rounds, which is why there is no tolerance parameter.
2. The full ordered sequence, `max`/`min`/`spread`/`n`, and the round the maximum was set in.
3. The branch and the SHA it was measured on.
4. The flappy-block census, derived **first-hand from the CI draws' own profiles** — `awk 'NR>1 && $3==0 {print $1}' <profile> | LC_ALL=C sort` on a low draw and a high draw, diffed — and **not** carried over from the local campaign. Two rigs measuring `a635190c` locally found different sets: one saw `relay/buffer/ring.go:262.3,263.1` (the empty-ring arm of `Ring.Oldest()`) flap in 4 of 12 draws with `relay/httpapi/fmp4.go:188.4,189.1` (the `ctx.Err()` early return in the fMP4 client loop) uncovered throughout, the other drew one lower and only the second block explains it. Same kind of flap, different set; the CI draws are the ones this file records.
5. That `shape`, `packages` and `gomod` are **equality** checks, not comparisons, and `statements` is recorded provenance that is never compared.
6. The local-versus-CI note: the local 12-round census's own numbers, so the next campaign can see whether the gap reproduces. **Never a fixed offset to budget against** — the Python gate measured +35 once and +13 the next time.
7. The #312 rule: a draw above `missing` is a finding to investigate; the fix is a re-measurement PR of its own, never a floor bump on the PR that drew it.
8. The note that a Go coverprofile's first column is an **import path**, so CI's artifact parses locally with no remapping — the half of #312 this gate does not inherit.
9. **Which packages owe the shortfall**, with their per-package figures, and the statement that `missing` is a module total and so cannot tell one package worsening from another improving. On `a635190c` that is `relay/channel` (219 missing of 1,063, 79.40%) and `relay/control` (94 of 404, 76.73%) — 313 of the 587 between them. Re-derive from `--report`'s own table on the tree the floor is set on; do not copy these two rows forward if the numbers have moved.
10. A `HOW TO MOVE THIS FLOOR` section distinguishing a `missing` move (steps 1–5, the census) from a `--shape-only` re-baseline (one run, one command, `missing` untouched).

- [ ] **Step 4: Gate against the floor you just wrote, locally**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
bash scripts/coverage_relay_go.sh --gate /tmp/relay-go-coverage; echo "exit=$?"
```

Expected: `GATE PASSED.` and `exit=0`. A local draw at or under `max(rounds)` is what should happen; if it exits 1, the hand-edit is wrong.

- [ ] **Step 5: Verify the companion against the floor's own hash**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
grep -E '^packages=|^package_count=' scripts/coverage_relay_go.floor
wc -l < scripts/coverage_relay_go.floor.packages
```

Expected: `package_count=10` and ten lines. The gate checks the hash on every run anyway; this is the human-readable half.

- [ ] **Step 6: Commit and confirm CI**

```bash
git add scripts/coverage_relay_go.floor scripts/coverage_relay_go.floor.packages
```

Separately: `git commit -F /tmp/2c9-msg-7.txt`, subject `coverage(relay): the Go ratchet floor, from a <n>-round CI census`.

Push, then read the `Coverage gate` job:

Expected: the bootstrap line is **gone**, replaced by `denominator: floor …` / `floor missing=… this run missing=…` / `GATE PASSED.`, and `Refuse a floor edited downward or deleted` prints `no floor on main (…); nothing to compare` with `Expected exactly once, on the PR that introduces the floor.` That sentence appearing exactly once, on this PR, is the bootstrap working as designed.

---

## Task 9: The documents

**Files:**
- Modify: `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` (Amendment A9, the Done-log row)
- Modify: `CLAUDE.md` (three passages)

**Interfaces:**
- Consumes: every ruling above.
- Produces: the record the next reader works from — in particular whoever plans stage 2d.

- [ ] **Step 1: Add Amendment A9 to the spec**

Insert **Appendix F**'s amendment after Amendment A8 (2c-8's), in the same `#### Amendment A9 (2c-9) — …` shape. It carries ten numbered items: the filename correction (R3), the denominator rule and its two measured figures (R1), the per-package-versus-`-coverpkg` measurement (R2), the bootstrap-exactly-once mechanism (R5), the differential's scope and the realignment test that was dropped (R8, R9, R10), the matrix-guard check and what "every row" means for 26 and 27 (R11), CodeQL as its own job (R12), the two handoffs declined with their reasons (R14, R15), and the drain test now reading its threshold rather than restating it (R16). **A9.2's package count is written as ten on the merged tree, with the nine-package seed figures labelled as the seed's** — Task 0 Step 2 is where the real number comes from.

- [ ] **Step 2: Add the Done-log row**

**A three-cell table row, never a bullet.** Append to the `## Done log` table:

```
| 2c-9 -- the Go coverage gate and stage 2c's close-out (`migration/phase2c-go-coverage-gate`). ... | `migration/phase2c-go-coverage-gate` | pending |
```

Appendix F carries the full cell text.

- [ ] **Step 3: Verify the spec's table still parses**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
awk '/^## Done log/,/^## Risks/' docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md | grep -c '^| '
```

Expected: the previous count plus one. A Done-log entry written as a bullet is invisible to this.

- [ ] **Step 4: Update `CLAUDE.md`**

Three passages, from **Appendix F**, whose single `git diff` carries the spec and `CLAUDE.md` together:

1. § Testing's `go-tests.yml` paragraph — "It carries **no coverage gate yet** — 2c-9 adds the ratchet and the floor file" becomes a description of the gate that now exists, its denominator rule, its two shape hashes and its floor.
2. § Build reproducibility — "CodeQL (`codeql.yml`) analyzes three language packs" becomes four.
3. § Supply chain security — "CodeQL (`codeql.yml`) analyses `actions`, `python` and `javascript-typescript` and **not** `go` (Ruling R6 …)" becomes the four-pack statement with the own-job reason.

- [ ] **Step 5: Confirm no stale claim survives**

```bash
cd /Users/dion/git/Dispatcharr/.worktrees/phase2c-go-coverage-gate
grep -n "no coverage gate yet\|and \*\*not\*\* \`go\`\|three language packs" CLAUDE.md
```

Expected: no output. Each of those three strings is a claim this PR makes false.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md CLAUDE.md
```

Separately: `git commit -F /tmp/2c9-msg-8.txt`, subject `docs(phase2): Amendment A9 and the 2c-9 Done-log row`.

---

## Task 10: Close out stage 2c

**Files:** none in this repository beyond the PR body.

**Interfaces:**
- Consumes: everything above.
- Produces: the PR description, and the two things the **user** must do that no commit can.

- [ ] **Step 1: Write the PR description**

In this order: what this PR does; **the sixteen rulings**, each in a sentence with its measured figure where it has one; **the CI census**, in full, with the stopping rule and the ceiling computation, **and which packages owe the shortfall** — `relay/channel` and `relay/control`, 313 of 587 missing between them, the only two individually under 80%, named so 2d reads it before writing rather than after CI says so; **the seven gate break-checks** with their actual first lines; **#309's fix and the A/B that reshaped it** — the stamp move measured not to reduce the failure rate, the margin found to be ticker drift rather than a tick interval, and the bound widened by a tenth of an interval with the count unchanged; the `= 1` break-check named as host-dependent; **R16's drain test**, with its five break-checks and, in particular, the `stopwaitsecs=60` control that proves the assertion is a bound and not an equality; **the `differential` job's piped runner**, which reported green on a failing test until this PR redirected instead, with the two exit codes and the third assertion that now reads the final status line; **the differential test's three measurements** (the 178-versus-0 join point, the 6.5 s runtime of which ~5 s is 2c-8's drain grace, and the corrupting-relay break-check) and **the realignment test that was built and dropped**, with the loop-phase argument; **the credlint census** (`scripts/check_go_credential_logging.sh relay`, 12 packages clean) and **the suppression census** (18 grep hits and 16 real on `a635190c`, 19 and 17 after this PR, the one addition being `drain_test.go`'s `#nosec G304` with its reason); **`go.sum` verified absent** and `go list -m all` printing exactly one module — the last confirmation the spec's § Requirements table owes to 2c-9; **the stated divergences and declines**: R14 (no matrix line-number refresh), R15 (no `fmp4.go` split, no `"remux stderr"` rename), and `relay/main.go`'s one-line comment correction, disclosed as a one-liner outside this PR's subject with the reason it was not declined alongside the rename; and **what this PR does not do**: no nginx route (2d), no ADR (2d's docs PR), no `metrics/curated` update (R13), no HLS (Phase 4).

- [ ] **Step 2: Undraft, and wait for the required checks**

```bash
gh pr ready --repo D10Scot/Dispatcharr <pr-number>
```

`Go result`, `Backend result`, `Frontend result`, `E2E result` and `Lifecycle result` must all be green, plus the `pr-review` agent's review with every thread resolved. The branch is `migration/**`, so **every** Playwright project runs, including `lifecycle-upgrade` — budget for it.

- [ ] **Step 3: Tell the orchestrator, verbatim, what to tell the user**

Relay this text, unedited:

> **Two things need you, and neither is something a commit can do.**
>
> **1. Make `Go result` a required status check on the Main ruleset.** `go-tests.yml` has carried the four-part requireable shape since 2c-1 and now covers build, vet, `go test -race`, golangci-lint under three GOOS, the stdlib-only assertion, the credential-logging check, the coverage ratchet and the cross-implementation differential. Until it is required, a PR can merge with all of that red. Add `Go result` to the same required-checks list that already holds `Backend result`, `Frontend result`, `E2E result` and `Lifecycle result`.
>
> **2. Record the stage-2c milestone, after this PR merges.** A merge commit cannot name itself, so the milestone row is a one-line follow-up PR — exactly as `#276` was for stage 2b after `#275`. Add to `metrics/curated/milestones.yml`:
>
> ```yaml
>   - {sha: <2C9_MERGE_SHA>, label: Phase 2c Go relay, kind: goal, phase: phase2, pr: <2C9_PR_NUMBER>, summary: "Nine PRs: a stdlib-only Go relay serving the live TS and fMP4 paths with failover and Output Profiles, behind a CI coverage ratchet and a 28-of-28 Go-pinned parity matrix."}
> ```
>
> then `python -m metrics.build --validate-only` and open the PR.
>
> **What stage 2d needs from this PR, and what it does not.** It needs `GO_PARITY_CLOSED` — the machine-checkable form of the matrix's own cutover precondition, which until now was prose — and it needs the coverage ratchet to stay green while 2d deletes Python, so a regression in the Go relay during the flip is caught rather than absorbed. It does **not** need the differential test to survive the cutover: once nginx routes to the Go relay, "both relays deliver the same bytes" stops being a question anyone asks, and that test is a legitimate deletion in the 2d cleanup rather than something to carry forward. And it does not need anything from `relay/output/fmp4.go`'s recommended split, which this PR declined.

- [ ] **Step 4: Remove your container**

```bash
docker rm -f phase2c9
docker volume rm phase2c9-hookdb
```

---
---

## Appendix A — `scripts/coverage_relay_go.sh`

Verbatim. Verified on **`a635190c`**: `--measure`, `--report`, `--gate` (with and
without a floor), `--write-floor` and `--write-floor --shape-only` all run;
all seven failure modes in Task 2 Step 5 exit 1 with a message naming the
mechanism; and `--write-floor --shape-only` leaves a hand-added prose line in
the floor untouched.

Two portability notes, both deliberate. There is **no `${x@Q}`** anywhere: that
expansion is bash 4.4+, and macOS ships bash 3.2 at `/bin/bash`, so a script
that works under Homebrew's bash and dies under the system one is exactly the
silent environment split this repo already has enough of. And `sha12()` prefers
`sha256sum` (Linux, CI) and falls back to `shasum -a 256` (macOS), so the same
hash comes out of both.

```bash
#!/usr/bin/env bash
# The Go relay's coverage ratchet -- Gate 2's counterpart for `relay/`
# (Phase 2 spec, § Stage 2c, the 2c-9 row; § Testing, "then 2c-9's Go
# equivalent").
#
#   scripts/coverage_relay_go.sh --measure [dir]   run the suite, write the profile
#   scripts/coverage_relay_go.sh --report  [dir]   parse and print, no comparison
#   scripts/coverage_relay_go.sh --gate    [dir]   compare against the floor
#   scripts/coverage_relay_go.sh --write-floor [dir]
#   scripts/coverage_relay_go.sh --write-floor --shape-only [dir]
#
# [dir] defaults to $COVERAGE_RELAY_GO_DATA_DIR, else /tmp/dispatcharr-coverage-relay-go.
# --measure needs the Go toolchain; --report/--gate/--write-floor need only
# awk, sha256sum (or shasum) and the two files --measure left behind, which is
# why CI can gate on a bare runner from a downloaded artifact.
#
# WHAT IS MEASURED, and why it is not `./...`. The denominator is exactly the
# packages the SHIPPED BINARY LINKS -- `go list -deps .` from the module root,
# ten of them today. relay/internal/relaytest and relay/internal/credlint are
# in the module and in neither: the first is the Go counterpart of
# apps/proxy/live_proxy/tests/harness/ and the second is a lint tool run by
# `go run`, and scripts/coverage_live_path.coveragerc omits both kinds on the
# Python side (`omit = */tests/*`; no script under scripts/ is in its module
# list). The rule is "what the relay ships", decided by kind, and it is
# derived mechanically rather than listed by hand so it cannot rot -- but the
# derived list is hashed into the floor, so GROWING it is still a deliberate
# re-baseline and never a silent denominator move.
#
# The numbers this distinction is worth, measured 2026-09-15 on a635190c:
# the whole module is 4,463 statements / 1,172 missing / 73.74%; the ten linked
# packages are 3,696 / 587 / 84.12%. The two excluded packages are 767
# statements of which 585 are missing -- HALF the module's shortfall is test
# scaffolding and a lint tool. Stated here rather than in a PR description
# because a reader who runs `go test -cover ./...` and sees 74% must be able to
# find out in one place why this gate says 84%.
#
# PER-PACKAGE, NOT -coverpkg. `go test -cover` instruments only the package
# under test, so a package's figure comes from its OWN tests; `-coverpkg`
# counts a package as covered when any other package's test walks through it.
# Both were measured on the same tree and the same denominator: per-package
# 587 missing, -coverpkg 316 -- a 271-statement, 7.33-point difference that is
# entirely code executed by a neighbour's tests. Per-package is kept because
# the gate's stated purpose (spec D7) is catching a subtle regression, which
# needs an ASSERTION over the code, not an execution of it, and an assertion
# lives in the package's own tests. A -coverpkg profile is refused outright
# below rather than silently accepted: it repeats every block once per test
# binary, so the parse would still produce a plausible number.
#
# -race IS PART OF THE SHAPE. The concurrency model changes from
# gevent-cooperative to OS-thread-parallel goroutines in this phase, and
# `-race` is what makes a data race visible. It also changes timing, which
# changes which branches run, which is where this gate's run-to-run spread
# comes from. A figure measured without it is not comparable with one measured
# with it, in either direction -- the same argument scripts/coverage_live_path.sh
# makes about COVERAGE_CORE -- so the mode string below names it.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODULE_DIR="$REPO_ROOT/relay"
FLOOR="$REPO_ROOT/scripts/coverage_relay_go.floor"
FLOOR_PACKAGES="$REPO_ROOT/scripts/coverage_relay_go.floor.packages"
GOMOD="$MODULE_DIR/go.mod"

DATA_DIR="${COVERAGE_RELAY_GO_DATA_DIR:-/tmp/dispatcharr-coverage-relay-go}"
PROFILE_NAME="relay.coverprofile"
PACKAGES_NAME="relay.packages"

# Bumped whenever WHAT IS MEASURED or HOW changes -- the package-selection
# rule, the test command, the cover mode. A floor written under one shape is
# refused against a run under another rather than compared, because the two
# numbers are incomparable rather than better or worse.
SHAPE_ID="go-race-per-package/v1"

say() { echo "coverage_relay_go: $*"; }
die() { echo "coverage_relay_go: $*" >&2; exit 1; }

# sha256, first 12 hex chars, of stdin. Linux has sha256sum; macOS has shasum.
sha12() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | cut -c1-12
  else
    shasum -a 256 | cut -c1-12
  fi
}

sha12_file() { sha12 < "$1"; }

# ---------------------------------------------------------------- measure ---

measure() {
  local dir="$1"
  command -v go >/dev/null 2>&1 || die "--measure needs the Go toolchain on PATH."
  rm -rf "$dir"; mkdir -p "$dir"

  # The package list is derived FIRST and from `go list -deps .`, the same
  # question scripts/check_go_stdlib_only.sh asks: what does the binary link?
  # Written before the tests run so a failing suite still leaves evidence of
  # what the scope was.
  ( cd "$MODULE_DIR" && go list -deps . ) \
    | grep '^github.com/D10Scot/Dispatcharr/relay' \
    | LC_ALL=C sort > "$dir/$PACKAGES_NAME" \
    || die "could not list the binary's dependencies."
  [ -s "$dir/$PACKAGES_NAME" ] || die "the binary's dependency list came back empty."

  say "measuring $(wc -l < "$dir/$PACKAGES_NAME" | tr -d ' ') linked packages under $SHAPE_ID"
  # -count=1 is NOT decoration. `go test` caches a package's result, coverage
  # profile included, and replays it verbatim -- so a local twelve-round census
  # without this flag is one run reported twelve times, with a spread of zero
  # and a floor that has measured nothing. It costs nothing in CI (a fresh
  # runner has a cold cache) and is what makes a local census real.
  if ! ( cd "$MODULE_DIR" && CGO_ENABLED=1 go test -count=1 -race -covermode=atomic \
           -coverprofile="$dir/$PROFILE_NAME" ./... ); then
    # A failed suite does not DEGRADE this measurement, it INVALIDATES it: the
    # statements a dead package would have covered are counted as missed, which
    # moves the number the way a regression moves. The profile is removed so a
    # later --gate cannot read it by accident. (Same rule, same reason, as
    # scripts/coverage_live_path.floor's "a failed label invalidates a
    # measurement rather than degrading it".)
    rm -f "$dir/$PROFILE_NAME"
    die "the Go suite failed; the profile was discarded. Fix the tests, then measure again."
  fi
  say "profile: $dir/$PROFILE_NAME"
}

# ------------------------------------------------------------------ parse ---

# Reads $dir and prints one line:  <statements> <missing> <packages_hash> <package_count>
# plus, on stderr, the per-package table. Dies on every shape problem it can see.
parse() {
  local dir="$1"
  local profile="$dir/$PROFILE_NAME"
  local packages="$dir/$PACKAGES_NAME"

  [ -f "$profile" ]  || die "no profile at $profile -- run --measure first (or download the CI artifact)."
  [ -f "$packages" ] || die "no package list at $packages -- it is written by --measure alongside the profile."

  local mode
  mode="$(head -1 "$profile")"
  case "$mode" in
    "mode: atomic") : ;;
    *) die "the profile's first line is [$mode], expected [mode: atomic]. -covermode is part of the shape." ;;
  esac

  # Everything below is one awk pass so the per-package table and the totals
  # cannot disagree about what was counted.
  awk -v packages="$packages" '
    BEGIN {
      while ((getline pkg < packages) > 0) { if (pkg != "") inscope[pkg] = 1 }
      close(packages)
    }
    NR == 1 { next }
    NF != 3 { printf "MALFORMED %d %s\n", NR, $0 > "/dev/stderr"; bad++; next }
    {
      block = $1; n = $2 + 0; c = $3 + 0
      if (block in seen) { dup++; dupblock = block }
      seen[block] = 1
      pkg = block
      sub(/\/[^\/]*$/, "", pkg)          # drop "/file.go:1.2,3.4"
      present[pkg] = 1
      if (!(pkg in inscope)) { outn[pkg] += n; next }
      tot[pkg] += n
      if (c > 0) cov[pkg] += n
    }
    END {
      if (bad)  { print "PARSE_ERROR malformed-lines " bad; exit }
      if (dup)  { print "PARSE_ERROR duplicate-block " dupblock; exit }
      for (pkg in inscope) if (!(pkg in present)) { missingpkg = missingpkg " " pkg }
      if (missingpkg != "") { print "PARSE_ERROR absent-package" missingpkg; exit }
      for (pkg in tot) {
        statements += tot[pkg]; covered += cov[pkg]
        printf "  %7d %7d  %6.2f%%  %s\n", tot[pkg], tot[pkg] - cov[pkg], 100 * cov[pkg] / tot[pkg], pkg > "/dev/stderr"
      }
      for (pkg in outn) printf "  ~out of scope, not counted: %s, %d statements\n", pkg, outn[pkg] > "/dev/stderr"
      printf "TOTALS %d %d\n", statements, statements - covered
    }
  ' "$profile" > "$DATA_DIR/.totals" 2> "$DATA_DIR/.table"
  # Sorted here rather than in awk: `for (k in array)` has no defined order,
  # and a table whose rows move between runs makes two reports look different
  # when only their line order changed.
  LC_ALL=C sort "$DATA_DIR/.table" >&2

  local line; line="$(cat "$DATA_DIR/.totals")"
  case "$line" in
    "PARSE_ERROR duplicate-block "*)
      die "the profile repeats block ${line#PARSE_ERROR duplicate-block }.
        That is what a -coverpkg profile looks like: every block appears once per
        test binary. This gate's shape is per-package (-cover, no -coverpkg);
        re-measure with --measure." ;;
    "PARSE_ERROR absent-package"*)
      die "these linked packages are in the scope list but have NO block in the profile:${line#PARSE_ERROR absent-package}
        A package that compiled and ran always contributes blocks, so this means
        the profile is incomplete -- a partial or failed run. Measure again; do
        not gate on it." ;;
    "PARSE_ERROR malformed-lines"*)
      die "the profile has ${line#PARSE_ERROR malformed-lines } line(s) that are not 'block n count'." ;;
    "TOTALS "*) : ;;
    *) die "could not parse the profile at all (awk said [$line])." ;;
  esac

  local statements missing
  statements="$(echo "$line" | awk '{print $2}')"
  missing="$(echo "$line" | awk '{print $3}')"
  local pkg_hash pkg_count
  pkg_hash="$(sha12_file "$packages")"
  pkg_count="$(grep -c . "$packages")"
  echo "$statements $missing $pkg_hash $pkg_count"
}

percent_of() { awk -v s="$1" -v m="$2" 'BEGIN { printf "%.2f", (s == 0) ? 0 : 100 * (s - m) / s }'; }

# ----------------------------------------------------------------- report ---

report() {
  local dir="$1" parsed
  parsed="$(parse "$dir")" || exit 1
  set -- $parsed
  say "shape=$SHAPE_ID  packages=$4  statements=$1  missing=$2  coverage=$(percent_of "$1" "$2")%"
}

# ------------------------------------------------------------------- gate ---

floor_field() { grep -E "^$1=" "$FLOOR" | head -1 | cut -d= -f2-; }

gate() {
  local dir="$1" parsed
  parsed="$(parse "$dir")" || exit 1
  set -- $parsed
  local statements="$1" missing="$2" pkg_hash="$3" pkg_count="$4"
  local percent; percent="$(percent_of "$statements" "$missing")"

  if [ ! -f "$FLOOR" ]; then
    # The documented bootstrap, expected EXACTLY ONCE: on the PR that
    # introduces the floor, whose census draws are taken through this branch.
    # It cannot be used to disable the gate later, because go-tests.yml's
    # "Refuse a floor edited downward" step fails when the BASE ref carries a
    # floor and the head does not -- absence is forgiven only when the base is
    # also absent.
    say "NO FLOOR at $FLOOR -- this run is a census draw, not a gate."
    say "this run statements=$statements missing=$missing coverage=$percent% packages=$pkg_hash ($pkg_count)"
    return 0
  fi

  # Checked against the floor's own hash on EVERY run, independent of the
  # current data: --write-floor writes the two files in separate steps, so they
  # can drift, and a drifted companion makes a future mismatch message name the
  # wrong files.
  local companion_hash; companion_hash="$(sha12_file "$FLOOR_PACKAGES")"
  local floor_packages; floor_packages="$(floor_field packages)"
  if [ "$companion_hash" != "$floor_packages" ]; then
    echo "coverage_relay_go: GATE FAILED -- $FLOOR_PACKAGES does not match the floor's packages= hash." >&2
    echo "        floor packages=$floor_packages  companion file=$companion_hash" >&2
    echo "        The two are written in separate steps by --write-floor and have drifted." >&2
    exit 1
  fi

  local floor_shape; floor_shape="$(floor_field shape)"
  if [ "$floor_shape" != "$SHAPE_ID" ]; then
    echo "coverage_relay_go: GATE FAILED -- shape mismatch: floor \"$floor_shape\", this run \"$SHAPE_ID\"." >&2
    echo "        Two shapes measure different things; the numbers are incomparable, not better or worse." >&2
    exit 1
  fi

  if [ "$pkg_hash" != "$floor_packages" ]; then
    echo "coverage_relay_go: GATE FAILED -- the linked package set changed." >&2
    echo "        floor packages=$floor_packages ($(floor_field package_count))  this run=$pkg_hash ($pkg_count)" >&2
    diff <(cat "$FLOOR_PACKAGES") "$dir/$PACKAGES_NAME" | sed 's/^/          /' >&2 || true
    echo "        A package entering or leaving the binary moves the denominator. Re-baseline" >&2
    echo "        deliberately with --write-floor --shape-only if missing is unchanged." >&2
    exit 1
  fi

  local gomod_hash; gomod_hash="$(sha12_file "$GOMOD")"
  local floor_gomod; floor_gomod="$(floor_field gomod)"
  if [ "$gomod_hash" != "$floor_gomod" ]; then
    echo "coverage_relay_go: GATE FAILED -- relay/go.mod changed (floor $floor_gomod, now $gomod_hash)." >&2
    echo "        go.mod fixes the toolchain the measurement ran under and the module's" >&2
    echo "        dependency set -- the Go counterpart of the Python gate's rcfile hash." >&2
    echo "        Re-baseline with --write-floor --shape-only if missing is unchanged." >&2
    exit 1
  fi

  local floor_missing; floor_missing="$(floor_field missing)"
  # A floor whose `missing` is not a decimal integer must FAIL LOUDLY, not fall
  # through. `[ "$missing" -gt "<MAX>" ]` does not error out of the script: bash
  # prints "integer expected", the test exits 2, the `if` is false, and the gate
  # says GATE PASSED on a floor it could not read. That is this whole file's own
  # failure mode -- a check that is green because it could not look -- and the
  # placeholder case is real: the floor template ships `missing=<MAX>` for a
  # campaign to fill in, so an unfilled template would otherwise gate nothing.
  case "$floor_missing" in
    ""|*[!0-9]*)
      echo "coverage_relay_go: GATE FAILED -- the floor's missing= is [$floor_missing], not a decimal integer." >&2
      echo "        An unfilled template placeholder looks exactly like this. A floor that cannot be" >&2
      echo "        read cannot be compared, and a gate that cannot compare must not report green." >&2
      exit 1 ;;
  esac
  say "denominator: floor $(floor_field statements) statements  this run $statements statements"
  say "floor missing=$floor_missing  this run missing=$missing  coverage $percent%"
  if [ "$missing" -gt "$floor_missing" ]; then
    echo "coverage_relay_go: GATE FAILED -- $((missing - floor_missing)) more missed statements than the floor." >&2
    echo "        \`missing\` is a MAXIMUM and lower is better, set from the WORST of >=12 CI" >&2
    echo "        draws. A draw above it is a finding to investigate, not noise: attribute it" >&2
    echo "        per package and then per BLOCK -- diff the uncovered block sets, never" >&2
    echo "        difference the totals -- against a green run's profile." >&2
    echo "        If it is the documented flap exceeding its recorded envelope, the fix is a" >&2
    echo "        re-measurement PR of its own (see $FLOOR's HOW TO MOVE THIS FLOOR), never a" >&2
    echo "        floor bump on the PR that happened to draw it. See issue #312 for the Python" >&2
    echo "        gate's worked instance of exactly this." >&2
    exit 1
  fi
  say "GATE PASSED."
}

# ------------------------------------------------------------ write-floor ---

write_floor() {
  local dir="$1" shape_only="$2" parsed
  parsed="$(parse "$dir")" || exit 1
  set -- $parsed
  local statements="$1" missing="$2" pkg_hash="$3" pkg_count="$4"
  local gomod_hash; gomod_hash="$(sha12_file "$GOMOD")"

  if [ -e "$FLOOR" ] && [ ! -w "$FLOOR" ]; then
    die "$FLOOR is not writable from here -- run --write-floor from a writable checkout."
  fi

  # A floor that does not exist yet is created whole, with a stub header the
  # PR that sets it replaces with its own census. A floor that DOES exist is
  # edited FIELD BY FIELD and its prose is never touched: this file's header
  # carries the campaign, the flappy-block census and the HOW TO MOVE THIS
  # FLOOR procedure, and a tool that rewrote the file wholesale would delete
  # all of it on every re-baseline. (scripts/coverage_live_path.sh makes the
  # same distinction, for the same reason.)
  if [ ! -f "$FLOOR" ]; then
    cat > "$FLOOR" <<EOF
# The Go relay's ratchet floor. See docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
# (Stage 2c, the 2c-9 row) and docs/superpowers/plans/2026-09-13-phase2-2c9-go-coverage-gate.md.
#
# REPLACE THIS STUB with the campaign that earned the number below: every CI
# draw in order, max/min/spread/n, the stopping rule, and a HOW TO MOVE THIS
# FLOOR section. A floor with no provenance cannot be audited.
#
# Written by:  scripts/coverage_relay_go.sh --write-floor
# Enforced by: scripts/coverage_relay_go.sh --gate  (go-tests.yml, job coverage)
EOF
    say "created $FLOOR with a stub header -- replace it with the campaign."
  else
    local old; old="$(floor_field missing)"
    if [ "$shape_only" = "no" ] && [ -n "$old" ] && [ "$missing" -gt "$old" ]; then
      die "refusing to write a WORSE floor ($old -> $missing).
        A floor may rise only in a PR that earns and explains the rise, and may never
        simply be edited down. If the package set or go.mod changed and missing did
        NOT, use --write-floor --shape-only: it never writes missing/percent/measured/
        runs, so this check has nothing to refuse."
    fi
  fi

  # The companion is written to a TEMP file and moved into place only after
  # every floor field has been written, so a failure partway through cannot
  # leave the companion holding the NEW list while packages= still holds the
  # OLD hash -- the exact inconsistency gate()'s companion check exists to
  # catch. Same ordering, same reason, as the Python gate's own S1 fix.
  local tmp_packages="${FLOOR_PACKAGES}.tmp.$$"
  cp "$dir/$PACKAGES_NAME" "$tmp_packages" || die "could not stage $tmp_packages."

  set_field shape          "$SHAPE_ID"
  set_field packages       "$pkg_hash"
  set_field package_count  "$pkg_count"
  set_field gomod          "$gomod_hash"
  if [ "$shape_only" = "no" ]; then
    set_field statements "$statements"
    set_field missing    "$missing"
    set_field percent    "$(percent_of "$statements" "$missing")"
    set_field measured   "$(date -u +%Y-%m-%d)"
    set_field runs       1
  fi

  mv "$tmp_packages" "$FLOOR_PACKAGES"

  if [ "$shape_only" = "yes" ]; then
    say "re-baselined shape/packages/package_count/gomod only; missing unchanged at $(floor_field missing)."
  else
    say "wrote $FLOOR from THIS RUN (missing=$missing, runs=1)."
    say "A campaign must then hand-edit missing to max(runs), recompute percent, and set runs."
  fi
}

# set_field replaces `key=...` in the floor, or APPENDS it when no such line
# exists. Appending matters: a floor written before a field existed has no line
# to substitute, and a substitution that matches nothing would report success
# for a write that never happened -- then fail identically on the next --gate.
set_field() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" "$FLOOR"; then
    local tmp; tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" '
      $0 ~ "^" k "=" { print k "=" v; next } { print }
    ' "$FLOOR" > "$tmp" && mv "$tmp" "$FLOOR"
  else
    printf '%s=%s\n' "$key" "$value" >> "$FLOOR"
  fi
}

# ------------------------------------------------------------------- main ---

MODE=""
SHAPE_ONLY="no"
DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --measure|--report|--gate|--write-floor) MODE="$1" ;;
    --shape-only) SHAPE_ONLY="yes" ;;
    -*) die "unknown option $1" ;;
    *) DIR="$1" ;;
  esac
  shift
done
[ -n "$MODE" ] || die "one of --measure, --report, --gate, --write-floor is required."
[ "$SHAPE_ONLY" = "no" ] || [ "$MODE" = "--write-floor" ] || die "--shape-only is only for --write-floor."

DATA_DIR="${DIR:-$DATA_DIR}"
mkdir -p "$DATA_DIR"

case "$MODE" in
  --measure)     measure "$DATA_DIR" ;;
  --report)      report "$DATA_DIR" ;;
  --gate)        gate "$DATA_DIR" ;;
  --write-floor) write_floor "$DATA_DIR" "$SHAPE_ONLY" ;;
esac
```

---

## Appendix B — `apps/proxy/live_proxy/tests/test_relay_differential.py`

Verbatim. Verified in a container on **`a635190c`**: `Ran 1 test in 6.425s`,
`OK`, with the Go relay's own log confirming it reached the real Django
`next-source`, streamed, and then ran 2c-8's drain on the test's `SIGTERM`.
The skip path was verified separately (`OK (skipped=1)`, naming
`DISPATCHARR_RELAY_GO_BIN`), and the whole `apps.proxy.live_proxy.tests` label
runs `429 tests … OK (skipped=1)` in 66.6 s with this file present.

**And it was break-checked**, which no earlier draft of this plan did: a Go
relay that flips one filler byte per chunk (`p[100] ^= 0xFF` in
`dataClock.Write`, outside the sync byte, the PID, the continuity counter and
the embedded index) reddens it with `packet index 0 differs between the two
relays…`. Task 4 Step 6b is that check. A comparison nothing has ever made fail
is a comparison nobody has shown compares anything.

```python
"""The cross-implementation differential: both relays, the same bytes, compared.

Spec Amendment A2.4, owner 2c-9. `relay/internal/relaytest.SyntheticTS(512,
0x100)` and `harness/asset.py`'s `synthetic_ts(packets=512, pid=0x100)` produce
byte-identical output -- 96,256 bytes, SHA-256
e565411f3bbe6d0ab88a4dcd45d9e2a9ca1f65e049846dc5f61a2ec162f57f89, pinned from
the Go side by `relaytest.TestSyntheticTSMatchesThePythonHarness` -- so the two
relays can be driven from ONE upstream serving those bytes and their deliveries
compared by the index each packet carries in its own payload.

WHAT THIS CATCHES THAT NEITHER SIDE'S OWN PINS CAN. Every parity-matrix row is
pinned twice, once per language, and each pin asserts its own implementation
against the row's prose. Two implementations can both satisfy their own tests
and still hand a client different bytes -- a chunk boundary drawn differently, a
realignment that drops a packet on one side and carries it on the other, a join
that lands a chunk apart. That is the class of divergence this file exists for,
and it is the reason the assertion is CONTIGUITY AND OVERLAP rather than a body
digest: the two relays join a channel independently, so the first index each
sees legitimately differs, and a digest of the whole body fails on the join
point alone while saying nothing about the bytes.

IT CITES NO MATRIX ROW, AND NO ROW CITES IT -- deliberately. A differential
failure does not say which side is wrong, so it cannot serve as a row's pin;
rows 7, 8 and 9 keep the per-language pins they already have. This is a
separate, stated artefact that runs after both.

WHERE IT RUNS. `go-tests.yml`'s `differential` job, which is the only job that
builds `relay-go` and boots Postgres and Redis in the same container. Every
other run of this label -- `backend-tests.yml`'s `test` job and its
`coverage-label` job alike -- leaves DISPATCHARR_RELAY_GO_BIN unset and skips,
deterministically in both, which is what keeps Gate 2's Python census
unperturbed by a test that is sometimes present.
"""

import os
import socket
import subprocess
import time
import unittest

import requests
from django.conf import settings

from .harness.asset import TS_PACKET_SIZE, assert_ts_aligned, packet_index
from .harness.control import ControlMixin, nginx_headers
from .harness.relay import RelayHarnessTestCase, wait_until
from .manager_support import proxy_stream_profile

# How many whole packets each side is read for. 200 packets is 37,600 bytes --
# comfortably under the 512-packet asset, so neither delivery wraps back to
# index 0 and "ascending and contiguous" is a claim about one pass through the
# asset rather than about the loop point.
PACKETS_READ = 200


def require_relay_go() -> str:
    """The relay-go binary, or skip saying why there is none.

    Skips rather than fails when the variable is UNSET, because whether a Go
    binary has been built is a property of the job, not of the code under test,
    and this module is discovered by every run of this label. It FAILS when the
    variable is set and the path is unusable: a job that went to the trouble of
    naming a binary and then could not run it has a real problem, and a skip
    there is the silence-read-as-pass shape. `relay/channel/
    source_transcode_real_test.go`'s requireFFmpeg makes the same split.
    """
    path = os.environ.get("DISPATCHARR_RELAY_GO_BIN", "")
    if not path:
        raise unittest.SkipTest(
            "DISPATCHARR_RELAY_GO_BIN is unset; the cross-implementation differential "
            "did NOT run. go-tests.yml's `differential` job is what sets it."
        )
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise AssertionError(
            f"DISPATCHARR_RELAY_GO_BIN={path} is not an executable file. It was set "
            "deliberately, so this is a broken job rather than a host without Go."
        )
    return path


def free_port() -> int:
    """A port nothing is listening on, released immediately.

    Racy in principle and fine in practice for one process on a CI runner --
    and the alternative, a fixed port, is worse: 5658 is the relay's own
    production port and a developer running this on a host with a dev stack up
    would bind-conflict with it.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def contiguous_indices(body: bytes) -> list[int]:
    """Every packet's embedded index, asserted to be a strictly ascending run of 1.

    Returns the indices so a caller can compare ranges. Raises AssertionError
    naming the first break, because "the delivery had a gap" is useless without
    where.
    """
    assert_ts_aligned(body)
    indices = [
        packet_index(body[at : at + TS_PACKET_SIZE])
        for at in range(0, len(body), TS_PACKET_SIZE)
    ]
    for position, (left, right) in enumerate(zip(indices, indices[1:])):
        if right != left + 1:
            raise AssertionError(
                f"packet {position + 1} of {len(indices)} carries index {right}, "
                f"after {left}: the delivery is not a contiguous run. "
                f"First ten indices: {indices[:10]}"
            )
    return indices


class RelayDifferentialTests(ControlMixin, RelayHarnessTestCase):
    """Both relays, one upstream, the same asset; the deliveries compared."""

    def start_relay_go(self) -> str:
        """Run relay-go against the live Django in this test, return its base URL.

        Nothing is stubbed: the Go relay resolves its control plane from
        DISPATCHARR_INTERNAL_API_BASE_URL (relay/control/baseurl.go's first
        branch) and calls the REAL `POST /api/relay/channels/<id>/next-source`
        on this test's own LiveServerTestCase, signed with the REAL SECRET_KEY.
        That is the first time in this phase the two halves of the Phase 1
        contract meet across the language boundary.
        """
        binary = require_relay_go()
        port = free_port()
        env = dict(os.environ)
        env.update(
            {
                "DISPATCHARR_RELAY_GO_PORT": str(port),
                # Passed explicitly rather than inherited: how the process this
                # test runs in resolved its SECRET_KEY is not something the
                # child can be assumed to repeat, and a disagreement surfaces
                # as a 403 on every internal call with nothing naming the
                # cause (relay/config/config.go's own note on precedence).
                "DJANGO_SECRET_KEY": settings.SECRET_KEY,
                "DISPATCHARR_RELAY_GO_DEV_ROUTES": "true",
                "DISPATCHARR_INTERNAL_API_BASE_URL": self.live_server_url,
            }
        )
        process = subprocess.Popen(  # noqa: S603 - a path this test resolved itself
            [binary],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        def stop():
            if process.poll() is None:
                # SIGTERM, not SIGKILL: since 2c-8 that raises D6's drain, and
                # letting it run is what keeps this test from leaving a
                # half-torn-down channel behind. The wait is THIRTY seconds
                # against a drain budget of 15 s, not ten: the drain spends a
                # five-second client grace before anything else, so a 10 s
                # wait sat only 5 s above the observed teardown and would
                # escalate to SIGKILL the first time the drain used more of
                # its own budget -- a flake that would read as a hung relay.
                # Measured: the whole test takes ~6.5 s, of which ~5 s is this
                # grace (it was ~2.3 s before 2c-8 added the drain).
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            # Printed on the way out so a failed assertion above is read next
            # to whatever the relay was saying at the time. It redacts its own
            # URLs (relay/redact), so this cannot print a provider credential.
            output = process.stdout.read() if process.stdout else b""
            if output:
                print("relay-go said:\n" + output.decode(errors="replace"))

        self.addCleanup(stop)

        base = f"http://127.0.0.1:{port}"

        def healthy():
            if process.poll() is not None:
                raise AssertionError(
                    f"relay-go exited with {process.returncode} before answering /healthz"
                )
            try:
                return requests.get(f"{base}/healthz", timeout=1).status_code == 200
            except requests.RequestException:
                return False

        wait_until(healthy, timeout=20.0, what="relay-go to answer /healthz")
        return base

    def read_from(self, url: str, channel, client_id: str, count: int) -> bytes:
        """`count` whole packets from a tune at `url`, with nginx's own headers."""
        response = requests.get(
            url,
            stream=True,
            timeout=30.0,
            headers=nginx_headers(channel, client_id),
        )
        self.addCleanup(response.close)
        # NEVER response.text on a 200: a live stream's body does not end, and
        # `timeout` is a socket timeout (harness/relay.py's own note).
        if response.status_code != 200:
            self.fail(f"tune at {url} returned {response.status_code}: {response.text[:200]}")
        wanted = count * TS_PACKET_SIZE
        body = b""
        deadline = time.monotonic() + 30.0
        for chunk in response.raw.stream(8192, decode_content=False):
            body += chunk
            if len(body) >= wanted:
                break
            if time.monotonic() > deadline:
                self.fail(f"only {len(body)} of {wanted} bytes arrived from {url}")
        return body[:wanted]

    def both_deliveries(self, upstream) -> tuple[list[int], bytes, list[int], bytes]:
        """Tune each relay on its OWN channel against `upstream`; return both runs.

        Two channels rather than one, and it is not an evasion. A channel's
        upstream slot is Django's to hand out (`Channel.get_stream()`), so two
        relays tuning ONE channel would contend for the assignment and the test
        would be measuring that contention. Two channels on the same URL get
        the same bytes from the first byte either way -- FakeUpstream serves the
        payload from its start to every connection -- which is the property this
        comparison actually rests on.
        """
        go_base = self.start_relay_go()
        # THIRTY seconds behind, not zero, and the direction is the opposite of
        # the obvious one. A client asking to join at the HEAD lands wherever
        # its own relay's read-ahead had got to when it attached, which is a
        # timing measurement, not a behaviour: measured on this harness, the
        # Python client joined at index 178 while the Go client on an
        # identically-configured channel joined at 0, leaving 22 comparable
        # packets out of 200. Asking to join thirty seconds behind a channel
        # one second old takes BOTH implementations' documented
        # shorter-than-requested fallback -- Python's chunk_timestamps lookup
        # and Go's Ring.Join (pinned by TestJoinFallsBackToTheOldestChunkWhen
        # TheBufferIsShort) -- so both start at the OLDEST resident chunk and
        # the comparison is over the whole read rather than over whatever the
        # scheduler left in common.
        self.set_proxy_setting(new_client_behind_seconds=30)

        profile = proxy_stream_profile()
        py_channel = self.make_channel(upstream_url=upstream.url, profile=profile)
        go_channel = self.make_channel(upstream_url=upstream.url, profile=profile)

        py_body = self.read_from(
            f"{self.live_server_url}/proxy/ts/stream/{py_channel.uuid}",
            py_channel,
            "differential-python",
            PACKETS_READ,
        )
        go_body = self.read_from(
            f"{go_base}/proxy/ts/stream/{go_channel.uuid}",
            go_channel,
            "differential-go",
            PACKETS_READ,
        )
        self.addCleanup(self.stop_channel, py_channel)
        return contiguous_indices(py_body), py_body, contiguous_indices(go_body), go_body

    def assert_overlap_identical(self, py_indices, py_body, go_indices, go_body):
        """The packets both relays delivered are byte-identical, and there are some.

        The emptiness check is the half that matters: without it, two relays
        that delivered disjoint index ranges would compare zero packets and
        pass, which is the strongest possible divergence reported as agreement.
        """
        low = max(py_indices[0], go_indices[0])
        high = min(py_indices[-1], go_indices[-1])
        overlap = high - low + 1
        self.assertGreaterEqual(
            overlap,
            PACKETS_READ // 4,
            f"the two deliveries overlap by {overlap} packets -- python "
            f"{py_indices[0]}..{py_indices[-1]}, go {go_indices[0]}..{go_indices[-1]}. "
            "Too little overlap to compare; the two relays joined the channel at very "
            "different points, which is itself the divergence.",
        )
        for index in range(low, high + 1):
            py_at = (index - py_indices[0]) * TS_PACKET_SIZE
            go_at = (index - go_indices[0]) * TS_PACKET_SIZE
            self.assertEqual(
                py_body[py_at : py_at + TS_PACKET_SIZE],
                go_body[go_at : go_at + TS_PACKET_SIZE],
                f"packet index {index} differs between the two relays. This is a "
                "byte-level divergence on the live path, not a timing difference: "
                "both relays were served the same asset from its start.",
            )

    def test_both_relays_deliver_the_same_packets_from_the_same_upstream(self):
        """One asset in, the same packets out of both implementations."""
        py_indices, py_body, go_indices, go_body = self.both_deliveries(self.upstream)
        self.assert_overlap_identical(py_indices, py_body, go_indices, go_body)
```

---

## Appendix C — the workflow diff

Against **`a635190c`**; `git apply --check` passes. 2c-8 touched neither
workflow, so this hunk needed no re-anchoring. The four action SHAs are still
re-resolved in Task 3 Step 1 rather than taken from here.

`actionlint` is silent on both files and `zizmor 1.30.1` reports
`No findings to report. (2 ignored, 4 suppressed)` across both, run **online**
with `GH_TOKEN="$(gh auth token)"`.

```diff
diff --git a/.github/workflows/codeql.yml b/.github/workflows/codeql.yml
index 099f8b26..2556c2c9 100644
--- a/.github/workflows/codeql.yml
+++ b/.github/workflows/codeql.yml
@@ -4,6 +4,7 @@ name: CodeQL
 #   - actions: the GitHub Actions workflows that can push to production
 #   - python: the Django backend (apps/, core/, dispatcharr/, scripts/)
 #   - javascript-typescript: the React frontend and Playwright e2e suite
+#   - go: the relay/ module (its own job below, not the matrix — see there)
 #
 # No pull_request trigger, deliberately. The usual reason to avoid one
 # (SARIF upload needs security-events: write, which a fork PR's
@@ -30,6 +31,7 @@ on:
       - 'pyproject.toml'
       - 'frontend/**'
       - 'e2e/**'
+      - 'relay/**'
   schedule:
     - cron: '0 6 * * 1' # weekly, Monday 06:00 UTC
   workflow_dispatch:
@@ -42,6 +44,48 @@ concurrency:
   cancel-in-progress: true
 
 jobs:
+  # Go gets a job of its own rather than a fourth matrix entry (spec Amendment
+  # A1.5; 2c-1 Ruling R6). Go is a compiled language, so its pack needs
+  # `build-mode: manual` and a real `go build` between init and analyze, while
+  # the three packs above need neither — and the module root is `relay/`, not
+  # the repository root, so `autobuild` has no go.mod to find where it looks.
+  # Folding that into the matrix means either a conditional build step inside
+  # a working job or a matrix of objects whose `build-mode` is an empty string
+  # for three of four entries; both put the three analyses that work today at
+  # risk to add a fourth. Twenty-five duplicated lines is the cheaper trade.
+  analyze-go:
+    name: Analyze (go)
+    runs-on: ubuntu-latest
+    permissions:
+      contents: read
+      security-events: write
+    steps:
+      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
+        with:
+          persist-credentials: false
+
+      # Same pin and same source of truth as go-tests.yml: the toolchain is
+      # read from relay/go.mod so CI cannot drift from the Dockerfile's
+      # builder stage without go.mod moving too.
+      - uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0
+        with:
+          go-version-file: relay/go.mod
+
+      - name: Initialize CodeQL
+        uses: github/codeql-action/init@db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28 # v4.37.8
+        with:
+          languages: go
+          build-mode: manual
+
+      - name: Build the relay
+        working-directory: ./relay
+        run: go build ./...
+
+      - name: Perform CodeQL analysis
+        uses: github/codeql-action/analyze@db488ddef3bf6cb639b32c2e9a7c0a7ea8271d28 # v4.37.8
+        with:
+          category: "/language:go"
+
   analyze:
     name: Analyze (${{ matrix.language }})
     runs-on: ubuntu-latest
diff --git a/.github/workflows/go-tests.yml b/.github/workflows/go-tests.yml
index 26be35e8..565f5c36 100644
--- a/.github/workflows/go-tests.yml
+++ b/.github/workflows/go-tests.yml
@@ -8,9 +8,11 @@ name: Go Tests
 # workflow that never triggers reports nothing at all, leaving a required
 # check "Expected" forever and blocking the merge.
 #
-# The coverage ratchet is NOT here. It arrives in 2c-9, which adds a job to
-# this workflow and a floor file beside it; the aggregate below already has
-# the shape to take it.
+# The coverage ratchet IS here, as of 2c-9: `build` measures (one `go test
+# -race` run, now with -coverprofile), `coverage` gates against
+# scripts/coverage_relay_go.floor on a bare runner, and `differential` runs
+# the one test that drives BOTH relays from the same bytes. All three are in
+# `Go result`'s needs below.
 on:
   push:
     branches: [main]
@@ -102,7 +104,14 @@ jobs:
           # nothing here to verify. docker-build.yml would catch a broken
           # relay-builder stage, but only for a Dockerfile change and only
           # AFTER merge -- it triggers on push to main, not on PRs.
-          pattern='^(relay/|\.golangci\.yml$|scripts/check_go_stdlib_only\.sh$|scripts/check_go_credential_logging\.sh$|\.github/workflows/go-tests\.yml$|apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/)'
+          # scripts/coverage_relay_go.* is here and NOT under the Python
+          # gate's scripts/coverage_live_path prefix, deliberately: that
+          # prefix is a _PATH_ALIASES entry in dispatcharr/test_discovery.py
+          # that routes to three DJANGO labels, so a file named
+          # coverage_live_path_go.sh would have run the Python backend suite
+          # for a Go-only change. The differential test is named too, because
+          # it is the one Python file this workflow's `differential` job runs.
+          pattern='^(relay/|\.golangci\.yml$|scripts/check_go_stdlib_only\.sh$|scripts/check_go_credential_logging\.sh$|scripts/coverage_relay_go\.|\.github/workflows/go-tests\.yml$|apps/proxy/live_proxy/tests/harness/|apps/proxy/live_proxy/tests/test_relay_differential\.py$)'
           if printf '%s\n' "$changed" | grep -qE "$pattern"; then
             echo "go=true" >> "$GITHUB_OUTPUT"
           else
@@ -200,10 +209,24 @@ jobs:
       # gevent-cooperative to OS-thread-parallel goroutines in this phase, so
       # a data race the Python implementation made structurally impossible
       # becomes possible for the first time (spec § Testing).
-      - name: Test with the race detector
-        env:
-          CGO_ENABLED: "1"
-        run: go test -race ./...
+      #
+      # ONE run, not two. --measure IS `go test -count=1 -race
+      # -covermode=atomic -coverprofile=... ./...`, so adding the ratchet adds
+      # a profile, not a second pass over a 90-second suite. It exits non-zero
+      # and DELETES the profile when any package fails, so the `coverage` job
+      # below can never gate on a partial measurement.
+      - name: Test with the race detector, and measure coverage
+        working-directory: .
+        run: bash scripts/coverage_relay_go.sh --measure /tmp/relay-go-coverage
+
+      # The profile and the linked-package list travel to the `coverage` job,
+      # which needs neither Go nor this container to read them.
+      - name: Upload the coverage profile
+        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4.6.2
+        with:
+          name: relay-go-coverage
+          path: /tmp/relay-go-coverage
+          retention-days: 1
 
       - name: Assert the module is standard-library only
         working-directory: .
@@ -269,12 +292,184 @@ jobs:
           version: v2.13.2
           working-directory: relay
 
+  # Gate 2's Go counterpart (spec § Stage 2c, the 2c-9 row; § Testing). A bare
+  # runner, deliberately: the gate parses the profile with awk and compares
+  # hashes, so it needs no Go toolchain and no base image — and it needs git
+  # and a full history, which this repo's base image does not ship (see
+  # backend-tests.yml's coverage-gate, which installs git for exactly this).
+  coverage:
+    name: Coverage gate
+    runs-on: ubuntu-latest
+    needs: [changes, build]
+    if: needs.changes.outputs.go == 'true'
+    timeout-minutes: 10
+    steps:
+      - name: Checkout code
+        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
+        with:
+          persist-credentials: false
+          fetch-depth: 0
+
+      - name: Download the coverage profile
+        uses: actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093 # v4.3.0
+        with:
+          name: relay-go-coverage
+          path: /tmp/relay-go-coverage
+
+      - name: Compare against the floor
+        run: bash scripts/coverage_relay_go.sh --gate /tmp/relay-go-coverage
+
+      # Two questions, asked separately, in backend-tests.yml's idiom and for
+      # its reason. A floor that is RAISED permits more missed statements; a
+      # floor that is DELETED turns --gate's documented bootstrap branch ("no
+      # floor, this run is a census draw") into a permanent off switch. The
+      # base ref is what tells the two apart from the legitimate one-time
+      # absence on the PR that introduces the floor.
+      - name: Refuse a floor edited downward or deleted
+        if: always()
+        env:
+          BASE_REF: ${{ github.base_ref || github.event.repository.default_branch }}
+        run: |
+          set -euo pipefail
+          git fetch --depth=1 origin "$BASE_REF"
+          # FETCH_HEAD, not origin/$BASE_REF: the fetch above prints only
+          # "-> FETCH_HEAD", and whether it also moves the remote-tracking ref
+          # depends on the refspec actions/checkout left behind.
+          BASE=$(git rev-parse --verify FETCH_HEAD)
+          OLD_BLOB=$(git rev-parse --verify --quiet "${BASE}:scripts/coverage_relay_go.floor") || true
+          if [ ! -f scripts/coverage_relay_go.floor ]; then
+            if [ -n "$OLD_BLOB" ]; then
+              echo "The floor exists on ${BASE_REF} (${BASE}) and is GONE on this head."
+              echo "Deleting it makes --gate's bootstrap branch a permanent off switch."
+              exit 1
+            fi
+            echo "no floor on either side; nothing to compare"
+            echo "This is the census state: the floor-introducing PR before its own"
+            echo "floor commit lands. Expected on EVERY run until it does, and never"
+            echo "again afterwards -- once a floor is on the base ref, its absence"
+            echo "here is the deletion the branch above refuses."
+            exit 0
+          fi
+          if [ -z "$OLD_BLOB" ]; then
+            echo "no floor on ${BASE_REF} (${BASE}); this head introduces one"
+            echo "Expected exactly once, on the PR that introduces the floor."
+            exit 0
+          fi
+          OLD=$(git cat-file blob "$OLD_BLOB" | grep -E '^missing=' | cut -d= -f2)
+          NEW=$(grep -E '^missing=' scripts/coverage_relay_go.floor | cut -d= -f2)
+          echo "floor: base=$OLD head=$NEW"
+          if [ "$NEW" -gt "$OLD" ]; then
+            echo "The floor was raised ($OLD -> $NEW): more missed statements are now permitted."
+            echo "A floor may rise only in a PR that earns and explains the rise."
+            exit 1
+          fi
+
+  # Spec Amendment A2.4: the one test that drives BOTH relays from the same
+  # synthetic asset and compares what each delivers. It lives with the Python
+  # harness because that is what can start a real Django, a real Redis and a
+  # real fake upstream — and it runs HERE rather than in a backend label
+  # because it needs a compiled relay-go, which the base image does not ship
+  # and backend-tests.yml has no reason to build.
+  #
+  # It SKIPS when DISPATCHARR_RELAY_GO_BIN is unset, which is every other run
+  # of apps.proxy.live_proxy.tests — deterministically, in both
+  # backend-tests.yml's `test` and its `coverage-label` jobs, so Gate 2's
+  # Python census sees the same thing either way and is not perturbed. The
+  # step below asserts the skip did NOT happen here, because a silently
+  # skipped differential test is green for the one reason it must never be.
+  differential:
+    name: Cross-implementation differential
+    runs-on: ubuntu-latest
+    needs: changes
+    if: needs.changes.outputs.go == 'true'
+    timeout-minutes: 20
+    permissions:
+      contents: read
+      packages: read
+    container:
+      image: ${{ needs.changes.outputs.base_image }} # zizmor: ignore[unpinned-images]
+      credentials:
+        username: ${{ github.actor }}
+        password: ${{ secrets.GITHUB_TOKEN }}
+      options: --entrypoint "" --init
+    env:
+      DISPATCHARR_ENV: aio
+      DJANGO_SECRET_KEY: ci-test-secret-key
+      POSTGRES_DB: dispatcharr
+      POSTGRES_USER: dispatch
+      POSTGRES_PASSWORD: secret
+      DISPATCHARR_LOG_LEVEL: WARNING
+      SYNC_PYTHON_DEPS: 'true'
+    steps:
+      - name: Checkout code
+        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
+        with:
+          persist-credentials: false
+
+      - name: Set up Go
+        uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0
+        with:
+          go-version-file: relay/go.mod
+
+      - name: Build relay-go
+        working-directory: ./relay
+        run: go build -o /tmp/relay-go .
+
+      - name: Drive both relays from the same bytes
+        shell: bash
+        env:
+          GITHUB_WORKSPACE: ${{ github.workspace }}
+          DISPATCHARR_RELAY_GO_BIN: /tmp/relay-go
+          # REDIRECTED, NOT PIPED, and the difference is the whole job.
+          # ci_bootstrap_backend.sh runs this through `exec bash -c "$CI_BACKEND_RUNNER"`
+          # -- a fresh shell with no `pipefail` -- so `… | tee` would exit with
+          # tee's 0 and a FAILING differential would report green. Verified:
+          # `bash -c 'bash -c "exit 7" 2>&1 | tee /tmp/x'` exits 0, and the
+          # same command with `> /tmp/x 2>&1` exits 7. The two other
+          # CI_BACKEND_RUNNER call sites in this repository are single commands,
+          # so nothing upstream was protecting this one.
+          CI_BACKEND_RUNNER: >-
+            python manage.py test --keepdb -v2
+            apps.proxy.live_proxy.tests.test_relay_differential
+            > /tmp/differential.log 2>&1
+        run: bash scripts/ci_bootstrap_backend.sh
+
+      - name: Show the differential log
+        if: always()
+        shell: bash
+        run: cat /tmp/differential.log
+
+      # THREE assertions, because the step above can only be trusted for two
+      # of them. A skip is the "silence read as pass" shape -- the job green
+      # because the test never ran -- and Django prints "skipped=N" in its
+      # summary only when something skipped, so its absence is the assertion.
+      # A nonzero "Ran N tests" says the module ran at all. And the FINAL
+      # STATUS LINE must be exactly OK: "Ran 1 test … FAILED (failures=1)"
+      # satisfies both of the other two, which is what makes the third one
+      # load-bearing rather than belt-and-braces.
+      - name: Assert the differential test ran and passed
+        shell: bash
+        run: |
+          set -euo pipefail
+          grep -qE '^Ran [1-9][0-9]* tests?' /tmp/differential.log \
+            || { echo "the runner reported no tests; the module did not run"; exit 1; }
+          if grep -q 'skipped=' /tmp/differential.log; then
+            echo "the differential test SKIPPED in the one job that must not skip it:"
+            grep -n 'skipped\|DISPATCHARR_RELAY_GO_BIN' /tmp/differential.log | head -20
+            exit 1
+          fi
+          if ! grep -qE '^OK$' /tmp/differential.log; then
+            echo "the differential test RAN and did not pass:"
+            grep -nE '^(FAILED|ERROR|OK)' /tmp/differential.log | head -5
+            exit 1
+          fi
+
   # The one check in this workflow that may be required. It always reports,
   # because it is not gated on anything — see the comment on the triggers.
   go-result:
     name: Go result
     runs-on: ubuntu-latest
-    needs: [changes, build, lint]
+    needs: [changes, build, lint, coverage, differential]
     if: always()
     timeout-minutes: 5
     steps:
@@ -283,9 +478,11 @@ jobs:
           CHANGES_RESULT: ${{ needs.changes.result }}
           BUILD_RESULT: ${{ needs.build.result }}
           LINT_RESULT: ${{ needs.lint.result }}
+          COVERAGE_RESULT: ${{ needs.coverage.result }}
+          DIFFERENTIAL_RESULT: ${{ needs.differential.result }}
           GO_REQUIRED: ${{ needs.changes.outputs.go }}
         run: |
-          echo "changes=$CHANGES_RESULT build=$BUILD_RESULT lint=$LINT_RESULT go-required=$GO_REQUIRED"
+          echo "changes=$CHANGES_RESULT build=$BUILD_RESULT lint=$LINT_RESULT coverage=$COVERAGE_RESULT differential=$DIFFERENTIAL_RESULT go-required=$GO_REQUIRED"
           if [ "$CHANGES_RESULT" != "success" ]; then
             echo "Change detection itself failed — cannot prove the Go jobs were unnecessary."
             exit 1
@@ -296,10 +493,11 @@ jobs:
           fi
           # `skipped` here means a gated job never ran on a run that needed
           # it, so only an exact `success` may report green.
-          for pair in "build:$BUILD_RESULT" "lint:$LINT_RESULT"; do
+          for pair in "build:$BUILD_RESULT" "lint:$LINT_RESULT" \
+                      "coverage:$COVERAGE_RESULT" "differential:$DIFFERENTIAL_RESULT"; do
             if [ "${pair#*:}" != "success" ]; then
               echo "The Go jobs were required and ${pair%%:*} did not succeed."
               exit 1
             fi
           done
-          echo "Go build, vet, tests and lint passed."
+          echo "Go build, vet, tests, lint, the coverage gate and the differential passed."
```

---

## Appendix D — the parity-matrix guard diff

Against **`a635190c`**; `git apply --check` passes, and 2c-8 touched neither
guard file. Verified there: `tsc --noEmit` clean and **8 passed**, logging
`parity matrix: 30 rows — 28 pinned, 0 owed, 2 white-box-only.` and
`parity matrix (Go): 28 of 28 pinned rows carry a Go reference; 2 row(s) are not pinnable.`

Both break-checks run on the same tree. Removing row 1's Go reference fails
with `Rows with a Python pin and no Go one: 1.`; flipping `GO_PARITY_CLOSED` to
`false` fails with `No pinned row lacks a Go reference any more — you just
closed the last one. Flip GO_PARITY_CLOSED to true…`. (On the 2c-7 seed the
`true` branch named all thirteen rows 2c-8 then owed, which is the same check
seen from the other side.)

```diff
diff --git a/e2e/tests/guards/parity-matrix.spec.ts b/e2e/tests/guards/parity-matrix.spec.ts
index 9d534147..9922c9d8 100644
--- a/e2e/tests/guards/parity-matrix.spec.ts
+++ b/e2e/tests/guards/parity-matrix.spec.ts
@@ -20,7 +20,9 @@
  *   5. `white-box-only` rows are exactly the allowlisted ones, each with a
  *      justification in its `Notes` cell;
  *   6. unpinned rows are exactly the ones the guard still owes;
- *   7. rows owed by one PR are contiguous in file order.
+ *   7. rows owed by one PR are contiguous in file order;
+ *   8. every pinned row cites at least one `.go` test, once GO_PARITY_CLOSED
+ *      says the matrix is 100% Go-columned.
  *
  * Checks 5 and 6 duplicate a fact between the document and this directory on
  * purpose, in `capabilities.spec.ts`'s idiom and for its reason: `toEqual`,
@@ -109,6 +111,8 @@ import {
   citationProblem,
   citationsIn,
   GATE_1_CLOSED,
+  GO_PARITY_CLOSED,
+  goRefs,
   HIGHEST_ROW_ID,
   MATRIX_REL,
   parseMatrix,
@@ -333,6 +337,43 @@ test('Gate 1: the matrix is fully pinned when the flag says so', { tag: '@charac
   );
 });
 
+test('Gate 1 in Go: every pinnable row carries a Go reference', { tag: '@characterization' }, async () => {
+  const rows = parseMatrix(await readMatrix());
+
+  // Only `test` pins are in scope. An `owed:` pin is Gate 1's business and is
+  // already empty; a white-box-only pin is a row the Go relay is not held to
+  // at all, and the allowlist check above is what keeps that set honest.
+  const pinned = rows.filter((row) => parsePin(row.pin)?.kind === 'test');
+  const bare = pinned
+    .filter((row) => goRefs(parsePin(row.pin)).length === 0)
+    .map((row) => row.id)
+    .sort((a, b) => a - b);
+
+  if (GO_PARITY_CLOSED) {
+    expect(
+      bare,
+      'GO_PARITY_CLOSED is true, so every pinned row must cite at least one `.go` test. This ' +
+        "matrix is stage 2d's cutover checklist — its own header says every row must show a " +
+        'passing Go-side equivalent before nginx\'s live locations move — and a row that loses ' +
+        'its Go reference loses that evidence silently. Rows with a Python pin and no Go one: ' +
+        `${bare.join(', ') || '(none)'}.`,
+    ).toEqual([]);
+  } else {
+    expect(
+      bare.length,
+      'No pinned row lacks a Go reference any more — you just closed the last one. Flip ' +
+        'GO_PARITY_CLOSED to true in e2e/tests/guards/parity-matrix.ts, in this same commit: ' +
+        'the matrix is 100% Go-columned, and from here the guard asserts it stays so.',
+    ).toBeGreaterThan(0);
+  }
+
+  const goPinned = pinned.length - bare.length;
+  console.log(
+    `parity matrix (Go): ${goPinned} of ${pinned.length} pinned rows carry a Go reference; ` +
+      `${rows.length - pinned.length} row(s) are not pinnable.`,
+  );
+});
+
 test('rows owed by one PR are contiguous', { tag: '@characterization' }, async () => {
   const rows = parseMatrix(await readMatrix());
 
diff --git a/e2e/tests/guards/parity-matrix.ts b/e2e/tests/guards/parity-matrix.ts
index ea0bdb0b..6dfd06b7 100644
--- a/e2e/tests/guards/parity-matrix.ts
+++ b/e2e/tests/guards/parity-matrix.ts
@@ -568,3 +568,37 @@ export const HIGHEST_ROW_ID = 30;
  * `true`, so Gate 1 cannot silently reopen.
  */
 export const GATE_1_CLOSED = true;
+
+/**
+ * Whether every pinnable row now carries a **Go** test reference as well as a
+ * Python one.
+ *
+ * The second half of Gate 1, and the thing stage 2d's cutover checklist
+ * actually depends on: `docs/relay-parity-matrix.md`'s own header says "every
+ * row must show a passing Go-side equivalent before nginx's live locations
+ * move", and until 2c-9 nothing checked it. Amendment A2.2 ruled that "gets a
+ * Go column" means one more backticked `path::symbol` in the `Pin` cell a row
+ * already has, not a sixth table column — so the property is "every `test` pin
+ * carries at least one `.go` reference", and it is invisible to every other
+ * check here: `testRefProblem` verifies that a `.go` reference RESOLVES, and
+ * says nothing about whether one is present.
+ *
+ * The two white-box-only rows are exempt by construction rather than by an
+ * exemption list: their pin is not a `test` pin at all, so they never enter
+ * this check. That the set of such rows is exactly {26, 27} is already a
+ * two-sided `toEqual` above, which is what stops "white-box-only" being used
+ * to make an un-ported row stop counting here.
+ *
+ * Same two-branch shape as GATE_1_CLOSED, for the same reason: while `false`
+ * the guard asserts at least one row is still bare, so the PR that closes the
+ * last one is TOLD to flip this rather than discovering later that nobody
+ * noticed; once `true` it asserts none is, so the property cannot silently
+ * reopen when 2d starts deleting Python.
+ */
+export const GO_PARITY_CLOSED = true;
+
+/** The `.go` references in a pin, empty for every other pin kind. */
+export function goRefs(pin: Pin | undefined): TestRef[] {
+  if (pin?.kind !== 'test') return [];
+  return pin.refs.filter((ref) => ref.file.endsWith('.go'));
+}
```

---

## Appendix E — the floor file's header template

`--write-floor` creates the file with a stub header and then only ever edits
its `key=value` lines, never its prose — verified in Task 2 Step 6. So this
header is written once, by hand, in Task 8, and survives every later
re-baseline. Exercised as the real file: written as `scripts/coverage_relay_go.floor`,
put through `--write-floor --shape-only` (shape, `packages`, `package_count`
and `gomod` updated; every line of prose and every measurement placeholder
untouched) and then through `--write-floor` and `--gate` (`GATE PASSED`, prose
still intact).

Every `<placeholder>` is filled from Task 7's census. Nothing here may be left
as a placeholder in the committed file — **and since the fix round the gate
enforces that** rather than trusting it: a `missing=` that is not a decimal
integer now fails, because `[ "$missing" -gt "<MAX>" ]` does not abort the
script. Bash prints "integer expected", the test exits 2, the `if` is false and
the old code fell through to `GATE PASSED` on a floor it could not read. Found
by running this template through the tool rather than by reading it.

**This appendix regressed once and the check that should have caught it could
not**, which is worth recording where the next person splices an appendix. The
re-seed corrected these figures **in the plan document**, in place; the scratch
file this fence is spliced from kept the 2c-7 seed's. A later commit edited that
scratch file and re-spliced, silently restoring the old numbers into the one
appendix that becomes a committed file. The verification compared the fence
against **the same scratch file it was spliced from**, so it proved the splice
worked and could never prove the source was right — a tautological oracle, in
the shape this plan warns about elsewhere. The check that found it was a
reviewer reading the appendix against an earlier commit, and the durable fix is
below: every appendix source is now regenerated from the tree or from a named
commit, never hand-edited in one place and spliced from another.

```text
# The Go relay's ratchet floor -- Gate 2's counterpart for relay/. See
# docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md (Stage 2c, the
# 2c-9 row, and Amendment A9) and
# docs/superpowers/plans/2026-09-13-phase2-2c9-go-coverage-gate.md.
#
# `missing` is the ratchet -- a MAXIMUM, not a target, and lower is better. It
# is set from the WORST run of at least twelve IN CI, where the gate is
# enforced, which is why this gate carries no separate tolerance parameter: the
# measured spread is already inside the number. The floor is NOT set from a
# local census. The Python gate learned that the expensive way -- its first
# floor came from a 21-round LOCAL campaign whose maximum the very first CI run
# exceeded -- and this file inherits the lesson rather than re-learning it.
#
# WHAT IS MEASURED. The ten packages `go list -deps .` reports from relay/ on
# a635190c, `drain` included -- the packages the SHIPPED BINARY LINKS.
# relay/internal/relaytest (the Go
# counterpart of apps/proxy/live_proxy/tests/harness/) and
# relay/internal/credlint (a lint tool run with `go run`) are in the module and
# in NEITHER, by the same rule scripts/coverage_live_path.coveragerc applies on
# the Python side. The difference is large and stated rather than buried:
# measured on one run at a635190c, the whole module is 4,463 statements / 1,172
# missing / 73.74%; the ten linked packages are 3,696 / 587 / 84.12%; and the
# two excluded packages are 767 statements of which 585 are missing -- HALF the
# module's shortfall is test scaffolding and a lint tool.
#
# HOW. `go test -count=1 -race -covermode=atomic -coverprofile=... ./...`, per
# package -- NOT -coverpkg, which counts a package as covered when a
# neighbour's test walks through it (measured on the same tree: 316 missing
# instead of 587, a 271-statement, 7.33-point difference). A -coverpkg profile
# repeats every block once per test binary and --gate refuses one outright.
# -count=1 is load-bearing: `go test` replays a cached coverage profile
# verbatim, so a census without it is one run reported N times.
#
# -race IS PART OF THE SHAPE, not an option. A figure measured without it is
# not comparable with one measured with it in either direction, the same
# argument scripts/coverage_live_path.sh makes about COVERAGE_CORE.
#
# `shape`, `packages` and `gomod` are EQUALITY checks, not comparisons. A
# different measurement shape, package set or measurement DEFINITION makes two
# numbers incomparable rather than better or worse, and the gate says so
# instead of ratcheting.
#
# `packages` is a sha256 (first 12 hex chars) of the sorted list of this
# module's linked import paths -- WHICH packages are in scope, not how big they
# are -- with the full sorted list committed alongside this file in
# scripts/coverage_relay_go.floor.packages so a --gate mismatch can name the
# packages added and removed, not just show two unequal hashes. gate() verifies
# the companion against `packages` on EVERY run, independent of the current
# profile, because the two are written in separate steps by --write-floor and
# could otherwise drift silently.
#
# `gomod` is a sha256 (first 12 hex chars) of relay/go.mod's raw BYTES. It is
# the counterpart of the Python gate's `rcfile=`: go.mod fixes the toolchain
# version the measurement ran under (CI reads it through `go-version-file`) and
# the module's dependency set, and either moving makes two numbers
# incomparable. `packages` alone is blind to a toolchain bump.
#
# `statements` is NOT compared -- it is recorded provenance only. It moves
# whenever ANY statement is added to or removed from an already-included
# package, which is ordinary code work, not a scope change; comparing it for
# equality would fire on every PR that touches the relay.
#
# A DRAW ABOVE `missing` IS A FINDING TO INVESTIGATE, NOT NOISE. Attribute it
# per package and then per BLOCK -- diff the uncovered block SETS between a red
# draw's profile and a green one's, never difference the totals:
#
#   awk 'NR>1 && $3==0 {print $1}' relay.coverprofile | LC_ALL=C sort
#
# If it turns out to be the documented flap exceeding its recorded envelope,
# the fix is a re-measurement PR of its own -- more CI draws, then `missing`
# raised to the new worst with the census updated -- NEVER a floor bump on the
# PR that happened to draw it. Issue #312 is the Python gate's worked instance
# of exactly this.
#
# ONE HALF OF #312 CANNOT ARISE HERE, and it is worth knowing why. Its second
# operational note is that CI's coverage artifacts are unusable locally,
# because coverage.py records absolute paths (/__w/Dispatcharr/Dispatcharr/...)
# and the committed rcfile has no [paths] section. A Go coverprofile's first
# column is an IMPORT PATH --
# github.com/D10Scot/Dispatcharr/relay/buffer/ring.go:31.42,35.3 -- so a
# downloaded artifact parses identically on any machine with no remapping. The
# attribution command above works on a CI artifact as-is.
#
# Written by:  scripts/coverage_relay_go.sh --write-floor
# Enforced by: scripts/coverage_relay_go.sh --gate  (go-tests.yml, job coverage)
#
# PROVENANCE (Phase 2 PR 2c-9, Task 8 -- measured in CI, where the gate is
# enforced). `missing` below is the WORST of <N> rounds of go-tests.yml's own
# build + coverage jobs, on migration/phase2c-go-coverage-gate at <SHA>,
# <DATE>. Full sequence, in order:
#   <r1> <r2> <r3> <r4> <r5> <r6> <r7> <r8> <r9> <r10> <r11> <r12>
# max=<MAX> (round <k>)  min=<MIN>  spread=<MAX-MIN>  n=<N>
# The stopping rule (maximum unchanged for >=6 consecutive rounds, minimum 12)
# was met at round <k+5>.
#
# THE FLAPPY-BLOCK CENSUS, derived first-hand from two of these draws' own
# retained profiles (a maximum draw and a minimum draw, block sets diffed with
# the awk above), NOT inherited from a citation and NOT copied from the local
# campaign:
#   <one line per flapping block, file:range and the function it is in>
# <total> block(s) flap, and <total> == <MAX - MIN>, so on this tree that set
# IS the spread rather than merely a contributor to it.
#
# RE-DERIVE IT; DO NOT CARRY THE LOCAL SET FORWARD. Two rigs measuring the same
# tree locally found DIFFERENT flapping blocks: one saw
# relay/buffer/ring.go:262.3,263.1 (the empty-ring arm of Ring.Oldest()) flap in
# 4 of 12 draws with relay/httpapi/fmp4.go:188.4,189.1 (the ctx.Err() early
# return in the fMP4 client loop) uncovered in all 12, and the other drew a
# figure one lower that only the second block explains. Same kind of flap in
# both cases -- a branch whose execution depends on which goroutine wins a
# start-up race -- and a different set. That is why the enforced number comes
# from CI and why this census is the CI draws', not a local campaign's.
#
# CAVEAT, stated because this is the shape that lets such a list go stale
# unnoticed: unobserved-to-vary across <N> rounds is not proof of stability,
# only absence of observed variance in that sample. A future correction should
# re-derive from CI artifacts again rather than assume today's set is
# permanent.
#
# LOCAL VS CI. A 12-round LOCAL census on the same tree ran <lo>-<hi> (spread
# <s>; on a635190c it was 586-588 across two rigs, spread 2, TWO blocks --
# and they were not the same two on each rig, which is the point). Recorded so the next campaign can see whether the gap reproduces, and
# NOT as an offset to budget against: the Python gate measured local+35 in one
# campaign and local+13 in the next, which is itself the evidence that the gap
# is not a constant. The correct response stays "measure in CI".
#
# THE THRESHOLD. D7 requires >=80% on the live path, transferring to Go at
# >=80%. The ceiling is statements - ceil(0.8 * statements) = <CEILING>;
# `missing` is <MAX>, so the margin is <CEILING - MAX> statements and coverage
# at the floor is <PERCENT>%. AT a635190c THAT MARGIN IS 152 STATEMENTS (739 -
# 587), DOWN FROM 253 AT THE 2c-7 SEED: 2c-8 added 740 linked statements
# carrying 249 missing ones, a marginal coverage of 66.4% on its own additions.
# Recorded because the next PR of that shape breaches the gate, and the right
# time to know that is before it is written, not when CI says so.
#
# WHICH PACKAGES OWE THE SHORTFALL, and why this file names them. `missing` is
# a MODULE TOTAL, so it cannot tell one package getting worse from another
# getting better: a PR that adds well-covered code to one package can offset a
# regression in another with this number unmoved and the gate green. D7's
# stated purpose is catching a subtle regression, which is exactly the shape
# that hides in a total. On a635190c two packages are individually under 80%
# and between them hold more than half the shortfall:
#
#   relay/channel   1063 statements   219 missing   79.40%   37.3% of the 587
#   relay/control    404 statements    94 missing   76.73%   16.0% of the 587
#   both            1467 statements   313 missing   78.66%   53.3% of the 587
#
# So THOSE TWO are what a later stage should read before adding to either, and
# `--report`'s per-package table is where to read it -- not the one number
# `--gate` compares. No per-package floor is enforced here, deliberately: a
# second ratchet is a second thing to re-measure and re-baseline every time the
# module moves, and 2c-9 closes stage 2c rather than opening machinery for it.
# Naming them is the cheaper half of the same job.
#
# HOW TO MOVE THIS FLOOR (read before running --write-floor).
#
# THESE ARE TWO DIFFERENT KINDS OF MOVE, and only one of them needs a campaign.
# A `missing` move changes what the ratchet PERMITS and can only be justified
# by a real measurement of the spread -- steps 1-5 below. A
# `shape`/`packages`/`gomod`-only re-baseline (the linked package set or
# relay/go.mod changed, deliberately, and `missing` is UNCHANGED) is not a
# claim about the spread at all: it tells the gate "the thing being measured is
# different now, here is its new identity". That needs exactly ONE clean run
# and a single `--write-floor --shape-only`, which writes FEWER fields -- it
# never touches `missing`, `percent`, `measured` or `runs`, so there is no new
# figure to earn. Say which kind of move it is in the PR either way.
#
#   1. Measure IN CI: dispatch go-tests.yml on the branch repeatedly and read
#      `this run missing=` from each Coverage gate job, until the MAXIMUM has
#      been unchanged for >=6 consecutive rounds, >=12 total. Record every
#      round, in order -- a bare min/max cannot show the rule was met. Note
#      go-tests.yml's concurrency group is per-ref with cancel-in-progress, so
#      rounds on one branch are sequential, not parallel. Local rounds are
#      worth taking (they are far faster and they attribute per block) but they
#      do NOT set the number.
#   2. Take max(rounds). That number, not any single run's figure, is `missing`.
#   3. Run plain --write-floor once, from a writable checkout, to get the file
#      FORMAT, `shape`, `statements`, `packages`, `package_count` and `gomod`
#      machine-produced -- and scripts/coverage_relay_go.floor.packages
#      rewritten to match. Commit both; the companion is what lets a future
#      mismatch name packages rather than hashes.
#   4. Hand-edit `missing` to max(rounds) and recompute
#      `percent` = (1 - missing/statements) * 100. This hand-edit is the
#      honest, documented step: --write-floor writes the figure from the run it
#      JUST took and cannot know it is the Nth of a campaign.
#   5. Re-run --gate and confirm it exits 0 against the new floor before
#      committing.
shape=go-race-per-package/v1
statements=<STATEMENTS>
missing=<MAX>
percent=<PERCENT>
measured=<DATE>
runs=<N>
packages=<HASH>
package_count=<COUNT>
gomod=<HASH>
```

---

## Appendix F — the spec's Amendment A9 and its Done-log row

Against **`a635190c`**; `git apply --check` passes. This is the hunk that did
conflict on the re-seed and has been re-anchored: Amendment **A9 now sits after
A8** (spec line 2616, with A8 at 2465 and `## Stage 2d` at 2764), and the
Done-log row is appended after 2c-8's, taking that table from 12 rows to 13.
A9 carries **ten** numbered items.

`CLAUDE.md` did **not** conflict: 2c-8 edited its Architecture paragraph and
added a Known-defects bullet for [#314](https://github.com/D10Scot/Dispatcharr/issues/314),
none of which is one of this PR's three passages. The three are re-applied by
string match rather than by line, so they land wherever 2c-8 left them.

Task 9 Step 3's row count check is what catches a Done-log entry written as a
bullet, which is invisible to the table.

The same file carries this appendix's CLAUDE.md hunks (three passages,
§ Testing, § Build reproducibility and § Supply chain security), because they
were captured in one `git diff`.

```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index 436e2777..fee2778d 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -159,7 +159,7 @@ Coverage ~45.6% backend / 71.9% frontend, **inversely correlated with criticalit
 
 **E2E exists now**: a Playwright suite in `e2e/` (fourteen projects: `bootstrap`, `guards`, `pristine`, `seeded`, `streaming`, `streaming-failover`, `streaming-greybox`, `streaming-split`, `frontend`, `dvr`, `lifecycle`, `lifecycle-upgrade`, `lifecycle-restore`, `lifecycle-scheduling` — most run their own CI job and container; `guards` is static analysis over the suite's own source and needs neither) runs against a shared, API-seeded AIO container (ADR `docs/adr/0001`), with `e2e-upstream/` providing a fake provider image with twelve injectable faults. G4 covers the live streaming data path: TS alignment/continuity, multi-client upstream sharing, mid-stream switching, all three failover triggers, the three Stream Profile architectures, Output Profile process sharing. Read `e2e/README.md` before adding to it and `e2e/COVERAGE.md` for what is/isn't covered (the shared worklist across the seven-goal programme — updated in the same PR as the tests). `e2e-tests.yml` runs on push/PR, and the fork's **Main ruleset requires its checks on every PR** (the workflow always triggers; a `changes` job skips the heavy jobs for docs-only diffs, since a skipped job still satisfies a required check). **Every test workflow now has that shape and a result aggregate** — `E2E result`, `Lifecycle result`, `Backend result`, `Frontend result` — so each is requireable: no `paths:` filter on the `pull_request` trigger (nor on `push` for backend/frontend), a cheap always-running change detector (`changes`, or `plan` in `backend-tests.yml`), and an `if: always()` aggregate with three branches — detector failed ⇒ fail, run not required ⇒ pass, otherwise every heavy job must be exactly `success`. **A skipped heavy job on a *required* run fails the aggregate**; only the not-required branch forgives a skip. `streaming-split` is the newest, and the only project that takes a supervisord program away rather than the container: it stops `api-uwsgi` with a stream running and restarts `relay-uwsgi` with a Celery task queued, driving `instance.supervisorctl()` so it needs one allowlist line and no new grey-box capability.
 
-`go-tests.yml` is the fifth test workflow and carries the same four-part requireable shape as the others, with a **`Go result`** aggregate from its first commit. It runs `go build`, `go vet`, `go test -race` and `golangci-lint`, plus the stdlib-only assertion. It carries **no coverage gate yet** — 2c-9 adds the ratchet and the floor file. Making `Go result` an actually-required check on the Main ruleset is a repo-settings action, not something a commit accomplishes.
+`go-tests.yml` is the fifth test workflow and carries the same four-part requireable shape as the others, with a **`Go result`** aggregate from its first commit. It runs `go build`, `go vet`, `go test -race` and `golangci-lint` under three GOOS, plus the stdlib-only and credential-logging assertions. **Since 2c-9 it also carries the Go coverage ratchet and the cross-implementation differential**, both in `Go result`'s `needs`. `scripts/coverage_relay_go.sh` is Gate 2's Go counterpart and its denominator is the packages the shipped binary LINKS — `go list -deps .` from `relay/`, ten since 2c-8 added `relay/drain` — so `relay/internal/relaytest` (the Go harness) and `relay/internal/credlint` (a `go run` lint tool) are out of it by the same rule `scripts/coverage_live_path.coveragerc` applies on the Python side; measured on the same run, the whole module is 79.8% and the ten linked packages 84.1%, with `relaytest` alone contributing 628 of the module's uncounted statements. It measures **per package** (`go test -count=1 -race -covermode=atomic`, no `-coverpkg` — a `-coverpkg` profile repeats every block per test binary and is refused outright), `-count=1` because `go test` replays a cached coverage profile verbatim and a census without it is one run reported N times. `--gate` checks three shapes for equality — `shape=`, `packages=` (a hash of the sorted linked-package list, committed beside the floor in `scripts/coverage_relay_go.floor.packages` and verified against the hash on every run) and `gomod=` (a hash of `relay/go.mod`'s bytes, the counterpart of the Python gate's `rcfile=`, since go.mod fixes both the toolchain and the dependency set) — then compares `missing` against the floor; `statements` is recorded provenance and never compared. The floor's `missing` is the WORST of ≥12 **CI** draws under the same stopping rule the Python gate uses; a draw above it is a finding to investigate, not noise, and the fix is a re-measurement PR of its own, never a floor bump on the PR that drew it. Unlike the Python gate, a CI artifact is directly usable locally: a Go coverprofile's first column is an import path, not a filesystem path, so there is no `[paths]` remapping to get wrong ([#312](https://github.com/D10Scot/Dispatcharr/issues/312)'s second operational note does not apply). The **differential** job is the only one that builds `relay-go` and boots Postgres and Redis together; it runs `apps/proxy/live_proxy/tests/test_relay_differential.py`, which starts the Go binary against the test's own `LiveServerTestCase` Django and compares what both relays deliver from one `FakeUpstream` — and which SKIPS in every other run of that label, deterministically, because `DISPATCHARR_RELAY_GO_BIN` is unset there, so Gate 2's Python census is unperturbed. Making `Go result` an actually-required check on the Main ruleset is a repo-settings action, not something a commit accomplishes.
 
 **The e2e suite quarantines its Redis coupling on purpose.** `e2e/fixtures/greybox/redis.ts` is the only sanctioned way a test reaches Redis; `e2e/tests/guards/allowlist.ts` + `e2e/tests/guards/capabilities.spec.ts` enforce an importer allowlist across four capabilities (grey-box Redis, container lifecycle, subprocess execution, container introspection), each with a test that fails naming the offender — an assertion, not a convention. Phase 3 removes Redis from the data path, at which point every greybox test is rewritten or deleted; one file keeps that a single grep. Importing it from outside `tests/streaming-greybox/` adds work to that refactor. One row is deliberately uncovered: the un-fenced ownership lease couldn't be provoked from outside the container (the owner's cleanup loop re-acquires the deleted key in <500ms; a follower only contends when channel *metadata* is absent too) — `COVERAGE.md` carries the full trace and the untried lever, recorded as a gap rather than shipped as a passing test, deliberately.
 
@@ -169,7 +169,7 @@ Coverage ~45.6% backend / 71.9% frontend, **inversely correlated with criticalit
 
 ## Build reproducibility (improving)
 
-`uv.lock` is committed and hash-pins every resolved version (18 of 31 deps still have no exact pin in `pyproject.toml` itself); every `FROM`/`COPY --from=` in both Dockerfiles is digest-pinned, and both CI and `docker/Dockerfile` install the frontend with `npm ci` from the committed lockfile. Remaining gaps: the base image compiles comskip from `refs/heads/master` (no tagged release builds on current Ubuntu/FFmpeg/gcc — see comment in `docker/DispatcharrBase`) and installs Redis/PostgreSQL from unversioned apt (deliberate). Still no Python linter, formatter, type checker or pre-commit config. `lint.yml` covers actionlint, hadolint, gitleaks (full history) and `uv.lock` freshness — all as digest-pinned containers. CodeQL (`codeql.yml`) analyzes three language packs: `actions`, `python`, `javascript-typescript`.
+`uv.lock` is committed and hash-pins every resolved version (18 of 31 deps still have no exact pin in `pyproject.toml` itself); every `FROM`/`COPY --from=` in both Dockerfiles is digest-pinned, and both CI and `docker/Dockerfile` install the frontend with `npm ci` from the committed lockfile. Remaining gaps: the base image compiles comskip from `refs/heads/master` (no tagged release builds on current Ubuntu/FFmpeg/gcc — see comment in `docker/DispatcharrBase`) and installs Redis/PostgreSQL from unversioned apt (deliberate). Still no Python linter, formatter, type checker or pre-commit config. `lint.yml` covers actionlint, hadolint, gitleaks (full history) and `uv.lock` freshness — all as digest-pinned containers. CodeQL (`codeql.yml`) analyzes four language packs: `actions`, `python`, `javascript-typescript` and, since 2c-9, `go`.
 
 ## Supply chain security
 
@@ -184,7 +184,7 @@ GHCR pushes (`docker-build.yml`, `base-image.yml`, `ci.yml`, `release.yml`) are
 
 Permission hygiene: every workflow sets top-level `permissions: contents: read` and grants more only on the job that needs it. Add `persist-credentials: false` to every `actions/checkout`.
 
-`go-tests.yml` pins `actions/checkout` v7.0.1 while the other ten workflows pin v6.1.0, deliberately, per spec line 1783's refusal to fold workflow-drift maintenance into this phase. CodeQL (`codeql.yml`) analyses `actions`, `python` and `javascript-typescript` and **not** `go` (Ruling R6 of the 2c-1 plan, recommended owner 2c-9).
+`go-tests.yml` pins `actions/checkout` v7.0.1 while the other ten workflows pin v6.1.0, deliberately, per spec line 1783's refusal to fold workflow-drift maintenance into this phase. CodeQL (`codeql.yml`) analyses `actions`, `python`, `javascript-typescript` and — since 2c-9 (Amendment A1.5; 2c-1's Ruling R6) — `go`. The Go pack is **its own job**, not a fourth matrix entry: it is the only compiled language here, so it needs `build-mode: manual` and a real `go build` between `init` and `analyze`, and the module root is `relay/` rather than the repository root, where `autobuild` would look for a `go.mod` and find none. `codeql.yml`'s push path filter carries `relay/**` for the same reason.
 
 ## Conventions
 
diff --git a/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md b/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
index 6fdbc2d1..82efe9e8 100644
--- a/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
+++ b/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
@@ -2613,6 +2613,179 @@ whose wire name is not a Python identifier is silently input-blind, and
 this contract has one more such field waiting to be added the moment a
 fourth credential header is discovered.
 
+#### Amendment A9 (2c-9) — eleven rulings from the Go coverage gate and 2c's close-out
+
+**A9.1 — the gate's files are `scripts/coverage_relay_go.*`, not the 2c-9 row's
+`scripts/coverage_live_path_go.floor`.** `dispatcharr/test_discovery.py`'s
+`_PATH_ALIASES` carries `("scripts/coverage_live_path", …)` as a **prefix**
+match with no trailing slash, deliberately, so the Python gate's script,
+rcfile, floor and companion all route to Gate 2's three Django labels. A file
+named `coverage_live_path_go.sh` matches that prefix, so editing the **Go**
+gate would have run three Django labels — in CI and in the commit gate — for a
+change touching no Python. Tightening the alias instead was rejected: it edits
+the Python gate's routing contract and its pinned test inside a PR that must
+not be able to break the Python gate. `go-tests.yml`'s own change detector
+names `scripts/coverage_relay_go\.` instead.
+
+**A9.2 — the denominator is the packages the shipped binary LINKS, not
+`./...`.** `go list -deps .` from `relay/` is ten packages; `internal/relaytest`
+(the Go counterpart of `apps/proxy/live_proxy/tests/harness/`) and
+`internal/credlint` (a `go run` lint tool) are in neither, by the same rule
+`scripts/coverage_live_path.coveragerc` already applies on the Python side
+(`omit = */tests/*`, and no `scripts/` file in the ten-module boundary list).
+The count is **TEN** since 2c-8 added `relay/drain`, which `main.go` imports.
+Measured on one run at `a635190c`: the whole module is 4,463 statements /
+1,172 missing / **73.74%**; the ten linked packages are 3,696 / 587 /
+**84.12%**; the two excluded packages are 767 statements of which 585 are
+missing. (On the 2c-7 seed the same measurement was 3,670 / 870 / 76.29%
+against 2,956 / 338 / 88.57%, which is the drop 2c-8's own additions bought:
+740 new linked statements carrying 249 new missing ones, a **marginal coverage
+of 66.4%** on the code 2c-8 added. Stated because the ceiling is now closer —
+152 statements of margin rather than 253 — and the next PR of that shape would
+breach it.) The rule is decided by
+KIND, and it is derived mechanically so it cannot rot — but the derived list is
+hashed into the floor (`packages=`), with the sorted list committed beside it,
+so a package entering or leaving the binary is a deliberate re-baseline.
+
+**A9.3 — per-package `-cover`, not `-coverpkg`, measured rather than assumed.**
+Same tree, same denominator, measured on `a635190c`: per-package 587 missing /
+84.12%, `-coverpkg` (merged per block) 316 / **91.45%** — 271 statements, 7.33
+points, entirely code executed by a neighbour's tests, and a gap that WIDENED
+with 2c-8 (117 statements / 3.95 points on the 2c-7 seed). Per-package is kept because D7's stated
+purpose needs an ASSERTION over the code, which lives in the package's own
+tests, not an execution of it. A timing objection to `-coverpkg` was raised and
+did NOT survive measurement (`relay/channel` 75.0 s with, 75.2 s without),
+recorded because an unmeasured reason would be worse than a measured
+non-reason. A `-coverpkg` profile repeats every block once per test binary and
+is refused outright rather than silently producing a plausible number.
+`-count=1` is mandatory: `go test` replays a cached coverage profile verbatim,
+so a local census without it is one run reported N times with a spread of zero.
+
+**A9.4 — the floor is bootstrapped exactly once, by its own absence.** `--gate`
+with no floor file prints the draw and exits 0, saying it is a census draw. The
+hole that opens — delete the floor and the gate is off forever — is closed from
+the other side, in `go-tests.yml`: the `Refuse a floor edited downward or
+deleted` step FAILS when the base ref carries a floor and the head does not, so
+absence is forgiven only when the base is also absent. A `workflow_dispatch`
+census input was considered and rejected: a permanent input to a required
+workflow whose whole effect is to not gate. The stopping rule is the Python
+gate's — maximum unchanged for ≥6 consecutive rounds, ≥12 total, every round
+recorded in order — and the number comes from CI, never from the local census,
+which on the seed tree ran 337-338 over 12 rounds (spread **1**, one block:
+`relay/buffer/ring.go`'s empty-ring arm of `Ring.Oldest()`).
+
+**A9.5 — one half of #312 cannot arise here.** Its rule is carried in full: a
+draw above `missing` is a finding to investigate, attributed per package and
+then per BLOCK (diff the uncovered block sets, never difference the totals),
+and the fix is a re-measurement PR of its own, never a floor bump on the PR
+that drew it. Its second operational note does NOT transfer: a Go coverprofile's
+first column is an import path, not a filesystem path, so a downloaded CI
+artifact parses identically anywhere with no `[paths]` remapping.
+
+**A9.6 — the differential test's scope, and the second one that was dropped.**
+A2.4 is implemented as one test. It cites no matrix row and no row cites it: a
+differential failure does not say which side is wrong, so it cannot be a pin;
+rows 7, 8 and 9 keep their per-language pins. `RelayHarnessTestCase` is already
+a `LiveServerTestCase` exporting `DISPATCHARR_INTERNAL_API_BASE_URL`, so the Go
+subprocess calls the REAL `next-source` on the test's own Django with the real
+`SECRET_KEY` — no stub control plane, and the first place in this phase the two
+halves of the Phase 1 contract meet across the language boundary. **Both clients
+join thirty seconds behind, not at the head**: at `new_client_behind_seconds=0`
+the Python client joined at packet index 178 and the Go client at 0, leaving 22
+comparable packets of 200, which measures read-ahead rather than behaviour;
+asking for 30 s on a one-second-old channel takes both implementations'
+documented shorter-than-requested fallback to the oldest resident chunk. **A
+second differential — a mid-packet-start upstream, row 9's property across the
+two — was built, run, and DROPPED**: `FakeUpstream` loops its payload, so a
+prefix that is not a multiple of 188 re-offsets the stream every loop, and a
+payload that IS a multiple splices two packets' halves at the loop boundary
+behind a real sync byte. A test whose failure mode is a property of its own
+fixture is worse than no test; it needs a non-looping upstream, which the
+harness does not offer.
+
+**A9.7 — "every row gets a Go counterpart" means every row whose `Pin` is a
+test pin, and it is now mechanical.** Rows 26 and 27 are exempt BY
+CONSTRUCTION, not by an exemption list: their `Pin` cell is the
+`white-box-only` sentinel rather than a test reference, so they never enter the
+check, and that the set of such rows is exactly {26, 27} is already a two-sided
+`toEqual`. What was missing is that NOTHING checked the Go half:
+`testRefProblem` verifies a `.go` reference RESOLVES and says nothing about
+whether one is PRESENT, while `docs/relay-parity-matrix.md`'s own header makes
+"every row must show a passing Go-side equivalent" stage 2d's precondition.
+2c-9 adds an eighth guard check and a `GO_PARITY_CLOSED` flag in
+`GATE_1_CLOSED`'s two-branch shape, so the property cannot silently reopen when
+2d starts deleting Python.
+
+**A9.8 — CodeQL's Go pack is its own job.** Go is the only compiled language
+here: its pack needs `build-mode: manual` and a real `go build` between `init`
+and `analyze`, and the module root is `relay/`, where `autobuild` looking at
+the repository root finds no `go.mod`. A fourth matrix entry means either a
+conditional build step inside a working job or a matrix of objects whose
+`build-mode` is empty for three of four — both risk three working analyses to
+add a fourth. `codeql.yml`'s push path filter gains `relay/**`.
+
+**A9.9 — three handoffs declined, each with its reason.** 2c-6 offered 2c-9 the
+matrix line-number refresh "on the pass it is already making" — but **2c-9
+edits no matrix row at all** (2c-8 closed the last thirteen; this PR's matrix
+change is in the guard), so the refresh would be a whole-file diff in a PR
+whose matrix diff is zero lines, and it stays its own chore PR; the guard
+already fails on a citation that no longer RESOLVES. 2c-7 offered the
+`"remux stderr"` rename at `relay/output/fmp4.go`, explicitly conditioned on
+Ruling R1's recommended `fmp4.go` split; the split is declined here (a file
+move reads as a whole delete plus a whole add, the wrong diff for a gate PR,
+and 2d needs neither), so the rename goes with it. And the stage-2c
+`metrics/curated/` milestone is a SEPARATE follow-up PR, not this one: a
+milestone row carries the merge SHA and a merge commit cannot name itself —
+exactly what stage 2b did, `61600940` merging 2b-4 as #275 and #276 recording
+it afterwards.
+
+**A9.10 — a derived threshold that cannot notice its own source moving, fixed
+rather than declined.** 2c-8's `relay/drain/drain_test.go` asserts the drain's
+budget against a hand-copied `const supervisordStopWait = 20 * time.Second`,
+whose real home is `docker/supervisord.d/relay-go.conf:34`. Change the conf and
+the test keeps asserting the old window, green. Its stated reason for copying —
+the conf "lives in a file this package cannot read" — is not so, and the
+counter-example is in the same module: `relay/internal/relaytest/corpus.go`
+reads the Python harness's fixtures from a Go test through a `runtime.Caller`
+repo-root walk. 2c-9 exports that walk as `relaytest.RepoRoot()` (one answer,
+not two; test support, so outside the coverage denominator by A9.2, and
+`_test.go` imports do not enter `go list -deps .`) and has the drain test read
+the conf, FAILING rather than defaulting when the file or the key is absent.
+This is fixed where the `"remux stderr"` rename of A9.9 was declined because the
+two are different in kind: that was a log message conditioned on a refactor,
+this is a claim that can become false with nobody touching the test, in a PR
+whose whole subject is replacing hand-copied claims with mechanical ones.
+Five break-checks, verified on `a635190c`; the load-bearing one is
+`stopwaitsecs=60` staying GREEN, which is what makes the fix a bound rather
+than an equality. Not built and recorded as a Stage 2d input: nothing asserts
+the conf's own header claim that `relay-go` shares `priority=205` with
+`relay-uwsgi` so its `stopwaitsecs` does not add a separate group to the
+container's 155 s stop budget against a 160 s `stop_grace_period`.
+
+
+**A9.11 — #309's margin is ticker drift, not a tick interval, and the first fix
+proposed for it was measured not to work.** `TestDeadAirOnAYoungConnection
+SwitchesStreams` asserts the resolver was asked no sooner than
+`ConnectionTimeout + 2 x HealthCheckInterval` after the last byte. That floor
+looks like it has a 50 ms margin and does not: the monitor's tick grid is
+phased on its own start rather than on the last byte, so the first tick past
+`ConnectionTimeout` lands a drift-width late -- instrumented at **301.093 ms**
+against 300 -- and the third unhealthy check two ticks later at **~400.6 ms**.
+The margin above the floor is that drift, about a millisecond. 2c-9's first
+draft proposed moving the test source's own timestamp to before its write,
+which is directionally right and is kept; a controlled A/B (two campaigns, same
+host, 28 spinners on 14 cores, shapes alternating within each round, the gap
+logged every run) says it does not reduce the failure rate -- 2 sub-400 ms gaps
+in 60 runs with it against 1 in 60 without. Widening the floor by a tenth of an
+interval does: 0 in 30, with a minimum 5 ms clear of its own bound. **The
+asserted count stays three**; only the clock tolerance moves, and the test still
+reddens at 350.99 ms on a monitor that acts one check early. Recorded because
+the mechanism a reviewer proposed for it -- an unhealthy check counted before
+the first byte -- is disconfirmed by the same trace (`unhealthyChecks 0` at the
+301 ms tick; `inactivityThreshold()` returns `InitGracePeriod` while the ring is
+empty), and a right conclusion reached through a wrong mechanism is worth
+separating in the record.
+
 ## Stage 2d — cutover, and its trap
 
 **The historical bug this stage exists to not repeat.** Every live-bound nginx location today carries
@@ -2940,6 +3113,7 @@ Filled in as PRs merge; this spec lands as its own PR 0.
 | 2c-6 -- the Go relay's fMP4 output format (`migration/phase2c-fmp4`). One remux per channel reading the shared ring on `pipe:0`, the init segment replayed to every client, a refcounted lifecycle with no shutdown delay, and parity-matrix row 12 ([#222](https://github.com/D10Scot/Dispatcharr/issues/222)) reproduced, pinned and filed rather than fixed. Row 12 gets its Go pin. Amendment A6. [#304](https://github.com/D10Scot/Dispatcharr/issues/304) (a pre-existing 2c-4 defect, the stderr pipe truncated by a reap racing its drain) fixed in `relay/ffmpeg/spawn.go`, repairing `relay/channel/source_transcode.go` without editing it. Two Python-side findings from the port, reproduced and filed rather than fixed: the fMP4 scanner's resynchronisation arm discarding the whole working buffer ([#306](https://github.com/D10Scot/Dispatcharr/issues/306)) and the dead stop-during-restart guard in `_handle_bsf_error` ([#307](https://github.com/D10Scot/Dispatcharr/issues/307)). Three plan corrections found and fixed in the plan document as committed, run rather than read: Task 4 Step 7's break-check rows 16-18 name tests defined in `relay/httpapi/fmp4_test.go`, Task 6's file, and had to run there rather than in Task 4; Task 1 Step 2's expected result for `TestEveryStderrLineSurvivesTheWaitThatPrecedesTheJoin` describes a runtime failure the package cannot yet produce, since the two `StartPiped` tests appended in the same step leave it uncompilable until Step 3's implementation lands; and the issue-number-placeholder slot count was corrected from six to five (an instruction about the slots had been counted as one) with Task 8 Step 5's own verification grep narrowed to the paths that can carry a real slot, since run unscoped over all of `docs/` it could never return empty. | `migration/phase2c-fmp4` | pending |
 | 2c-7 -- the Go relay's Output Profiles (`migration/phase2c-output-profile`). One transcode per active `(channel, profile)` pair reading the channel's shared ring on `pipe:0` and writing a second in-process MPEG-TS ring, shared by every client on that profile; an fMP4 client on a profile runs it and 2c-6's remux chained, under `mpegts:p<id>` and `fmp4:p<id>`. Parity-matrix row 11 gets its Go pin, counted in spawns. The contract gained a null `argv` so a broken Output Profile can be told from a deactivated one. Amendment A7. Three plan corrections found, disclosed and **fixed in the plan document as committed**, run rather than read: Task 4 Step 5 and Task 7 Step 5 misassigned which break-check rows belong to which task -- rows 3-7 name `httpapi`-package tests Task 7 creates (Appendix P) and rows 8 and 11 name `output`-package tests Task 4 creates (Appendix I), so Task 4's Step 5 now reads "rows 8 and 11" and Task 7's now reads "rows 2, 3, 4, 5, 6, 7, 9, 10, 12, 13, 16, 17, 18", the amended lists this PR actually ran each row against; rows 16, 17 and 18 were re-checked against the same test rather than assumed correct, and confirmed already in Task 7's list -- `TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint` and `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` (both arms) are in `relay/httpapi/profile_test.go`, and no channel-package location for either exists. Task 5 Step 3's "Expected: green" for the whole-module `go build ./...` did not hold and is amended to name what actually goes green at that step: `go build`/`vet`/`golangci-lint` scoped to `./channel/... ./output/... ./control/... ./buffer/... ./ffmpeg/... ./internal/...` (every package but `httpapi`), `go test -race ./channel/...`, and `gofmt -l .` over the whole tree -- **commit `38669dba` (Task 5) does not build alone**, because `httpapi/fmp4.go` and `stream.go` still call `AttachOutput` with the pre-2c-7 signature; the whole-module build, vet, test and lint first go green at Task 6 Step 4 once `httpapi`'s own edits land, so a `go build ./...` bisect on this branch lands on Task 6's commit for a defect that is Task 5's incompleteness, not Task 6's own. No commit was ever made against a genuinely broken working tree regardless, since Task 6 was written and verified before either commit. Third, Task 9 Step 3's `ffmpeg.StartPiped`/`.Start` call-site breakdown named the wrong two files ("two in spawn.go, one in output/fmp4.go, one in output/profile.go"); the actual four are one in `output/profile.go`, two in `output/fmp4.go` (the initial spawn and the bitstream-filter retry) and one in `channel/source_transcode.go` -- the total of 4 was already right. | `migration/phase2c-output-profile` | pending |
 | 2c-8 -- the Go relay's control routes and drain (`migration/phase2c-control-drain`). The four remaining `/proxy/relay/…` routes (the single-channel `GET` with its `?fields=state` form, the channel `DELETE`, the client `DELETE` and `advance`), the detail endpoint with its five extra client fields and row 14's `owner` asymmetry, the XC live roots (Ruling R1: spec D1 scopes them and no PR owned them), the four events the tune and stop paths raise, the dev-only `POST /_dispatcharr/authorize-internal` fallback and the Go half that calls it, and D6's SIGTERM drain with a real `/readyz` and a role-aware Docker `HEALTHCHECK`. Thirteen parity-matrix rows get a Go pin, taking the matrix to 28 of 28 pinnable rows, and the ten authorize-matrix rows among them gain a Notes clause saying the Go pin covers the relay's ask-and-obey share and not the decision, which stays Django's. Amendment A8. Four defects found and fixed, three in code this PR did not write: `RequireInternal` verifying the bound signature against an empty body (A8.3), `Manager.publish` bypassing `addClient` for the first client of every channel (A8.4), `control.Emitter` panicking on a send after `Close` and on a second `Close` (A8.5), and -- in this PR's own first draft, found by a Gate 2 coverage test -- the `x-api-key` body field that never arrived, because DRF reads input by a field's NAME and `source=` maps only the output (A8.9). Two Python-side findings reproduced and filed rather than fixed: `source_bitrate` and `ffmpeg_bitrate` are read by `channel_status.py` and written by nothing, the second because the reader and the writer name two different constants ([#314](https://github.com/D10Scot/Dispatcharr/issues/314)). Four break-checks stayed green on a first attempt and each produced a better test or deleted unreachable code. Five plan-text corrections found and made in-tree, none changing the shipped code: Task 0 Step 2's expected `c.clients[` grep count on the merged 2c-7 tree said four hits including `StopClient`'s lookup, but `StopClient` does not exist until this PR's own Task 1 -- the measured count on the tree Task 0 actually ran against is three (one write, two reads); Appendix U's request-count fix, written for Task 4 Step 5, was applied at Task 1 instead so Task 1's own commit would not land with `./httpapi` red under Constraint 33, and both steps now say so; Tasks 2, 3 and 4 landed in one commit rather than three, plus Ruling R10's `Emitter` guards and Task 8's self-contained Docker/entrypoint/healthcheck pieces, because building each task in isolation surfaced a three-link build/test dependency chain the plan's task boundaries did not show; `authorize_test.go` (Task 6) defines `runningIDs` and `containsString`, and `xc_test.go` (Task 7) calls rather than redefines them, the reverse of where the plan first placed them; and `server.go`'s `/healthz`/`/readyz` doc comment was rewritten as one coherent paragraph rather than applied as Appendix J's original hunk, which would have left a stale 2c-1 sentence ("this PR adds no Docker HEALTHCHECK") sitting directly above the paragraph describing the HEALTHCHECK this PR adds -- Appendix J's hunk text is regenerated to match. | `migration/phase2c-control-drain` | pending |
+| 2c-9 -- the Go coverage gate and stage 2c's close-out (`migration/phase2c-go-coverage-gate`). `scripts/coverage_relay_go.sh` measures the ten packages the shipped binary LINKS (not `./...`: `internal/relaytest` and `internal/credlint` are out by the same rule the Python rcfile applies, worth 73.74% vs 84.12% on one run at `a635190c`) under `go test -count=1 -race -covermode=atomic`, and gates on `missing` against a floor whose number is the worst of >=12 CI draws, with `shape=`/`packages=`/`gomod=` as equality checks and `statements` recorded but never compared. `go-tests.yml` gains `coverage` and `differential` jobs, both in `Go result`'s needs; `codeql.yml` gains a Go job of its own with `build-mode: manual`. The parity matrix's Go half becomes mechanical: an eighth guard check plus `GO_PARITY_CLOSED`, with rows 26 and 27 exempt by construction rather than by an exemption list. Amendment A2.4's cross-implementation differential lands as one harness test that starts `relay-go` against the test's own `LiveServerTestCase` Django; a second differential (row 9's realignment) was built, run and dropped because `FakeUpstream`'s looping payload cannot express a mid-packet start without re-breaking every loop. [#309](https://github.com/D10Scot/Dispatcharr/issues/309) fixed by widening the dead-air bound by a tenth of a check interval, the asserted count of three unchanged -- the stamp move first proposed for it was measured not to reduce the failure rate (2 sub-400 ms gaps in 60 loaded runs against 1 in 60 unmodified) and the margin turned out to be the health monitor's ticker drift, about a millisecond, rather than the 50 ms interval the floor looks like. 2c-8's `relay/drain/drain_test.go` stops restating `docker/supervisord.d/relay-go.conf`'s `stopwaitsecs` as a Go constant and reads it, through a newly exported `relaytest.RepoRoot()`, failing rather than defaulting when the key is gone -- five break-checks, the load-bearing one being `stopwaitsecs=60` staying green so the assertion is a bound and not an equality. Amendment A9. Three handoffs declined with reasons (the matrix line-number refresh, the `fmp4.go` split and its `"remux stderr"` rename, the milestone row). | `migration/phase2c-go-coverage-gate` | pending |
 
 ## Risks
 
```

---

## Appendix G — the four Go source hunks (#309, R15's one-liner, R16)

Against **`a635190c`**; `git apply --check` passes. One diff, four files, three
rulings: `relay/channel/failover_test.go` is R7's stamp move, `relay/main.go`
is R15's one-line comment correction, and `relay/internal/relaytest/corpus.go`
plus `relay/drain/drain_test.go` are R16.

Verified on that tree, whole module unless stated: `gofmt -l` silent;
`go build ./...`; `go vet` native, `GOOS=linux` and `GOOS=darwin`;
`golangci-lint run ./...` at `0 issues.` under all three GOOS;
`scripts/check_go_credential_logging.sh relay` at `12 package(s) clean`;
`scripts/check_go_stdlib_only.sh relay` OK; `relay/go.sum` absent;
`go test -count=1 -race ./...` three times at 11 packages `ok` with no `FAIL`,
and three more times without `-race`.

Six break-checks, each reverted before the next. R7's, at
`maxUnhealthyChecks = 2`, reddens through the gap assertion at **350.99 ms
against the new 395 ms floor** — 44 ms of margin against a 5 ms tolerance,
which is what says the widened bound did not buy the fix at the cost of the
assertion. `= 1` is **host-dependent** and is not the row to cite: here it
reddens through the earlier `sawUnhealthy` assertion, elsewhere through the gap
at ~301 ms. R16's five are in Task 1 Step 10, and the load-bearing one there is
`stopwaitsecs=60` staying **green**, which is what makes that assertion a bound
rather than an equality.

R7's own evidence is not a break-check but a controlled A/B, in Task 1 Step 5:
two campaigns, same host, 28 spinners on 14 cores, shapes alternating within
each round, the gap logged on every run. Stamp-only drew 2 sub-400 ms gaps in
60 runs against the unmodified shape's 1 in 60; stamp-plus-bound drew 0 in 30
with a minimum 5 ms clear of its floor.

```diff
diff --git a/relay/channel/failover_test.go b/relay/channel/failover_test.go
index 17e58a57..ead8650e 100644
--- a/relay/channel/failover_test.go
+++ b/relay/channel/failover_test.go
@@ -174,10 +174,19 @@ func (c *timeCell) get() time.Time  { c.mu.Lock(); defer c.mu.Unlock(); return c
 
 func (s deadAirSource) Run(ctx context.Context, sink io.Writer) error {
 	payload := relaytest.SyntheticTS(s.packets, 0x100)
+	// Stamped BEFORE the write, because dataClock.Write records the channel's
+	// own lastData at the START of the write (health.go's dataClock) and the
+	// monitor measures from THAT -- so a stamp taken afterwards is later than
+	// the monitor's clock by however long the ring write took, and the
+	// assertion below is a `>=` on the gap. Directional, and MEASURED NOT TO
+	// BE SUFFICIENT on its own: under load this shape still drew 2 sub-400 ms
+	// gaps in 60 runs against the unfixed shape's 1 in 60. The bound below is
+	// what actually closes #309; this is the perturbation it was cheap to
+	// remove first.
+	s.lastWrite.set(time.Now())
 	if _, err := sink.Write(payload); err != nil {
 		return err
 	}
-	s.lastWrite.set(time.Now())
 	<-ctx.Done()
 	return ctx.Err()
 }
@@ -356,8 +365,29 @@ func TestDeadAirOnAYoungConnectionSwitchesStreams(t *testing.T) {
 		t.Fatal("the channel was never observed unhealthy before it switched")
 	}
 	asked, wrote := resolver.firstCallAt(), lastWrite.get()
-	if gap := asked.Sub(wrote); gap < tuning.ConnectionTimeout+2*tuning.HealthCheckInterval {
-		t.Fatalf("the resolver was asked %s after the last byte, under CONNECTION_TIMEOUT + two more checks (%s): the monitor did not wait for three consecutive checks", gap, tuning.ConnectionTimeout+2*tuning.HealthCheckInterval)
+	// THE CLAIM IS THREE CHECKS AND IT IS NOT WEAKENED; what moves is the
+	// clock tolerance, and #309 is why.
+	//
+	// The monitor's first unhealthy check is the first TICK whose inactivity
+	// exceeds CONNECTION_TIMEOUT, and the tick grid is phased on the monitor's
+	// start rather than on the last byte. Instrumented on this tree, the six
+	// ticks to 300 ms land at 301.093 ms -- 1.09 ms past, that overshoot being
+	// the ticker's accumulated drift -- and the third unhealthy check two ticks
+	// later at ~400.6 ms. So the margin above a floor of exactly
+	// CONNECTION_TIMEOUT + 2 intervals is the DRIFT ALONE, about a
+	// millisecond, not the 50 ms interval it looks like. Any sub-millisecond
+	// perturbation breaches it: measured at 399.966, 399.960 and 399.995 ms on
+	// a loaded host, with and without the stamp fix above alike.
+	//
+	// A tenth of an interval -- 5 ms here -- is two orders of magnitude below
+	// the 50 ms that separates this from acting one check early, so the test
+	// still reddens on a monitor that acts on the second check (~350.6 ms
+	// measured) or the first (~301 ms), which is what it exists to catch.
+	// Measured with this bound: 30 loaded runs, zero failures, minimum gap
+	// 399.989 ms -- 5 ms of real margin where the old bound had 40 microseconds.
+	floor := tuning.ConnectionTimeout + 2*tuning.HealthCheckInterval - tuning.HealthCheckInterval/10
+	if gap := asked.Sub(wrote); gap < floor {
+		t.Fatalf("the resolver was asked %s after the last byte, under CONNECTION_TIMEOUT + two more checks less a tenth of an interval (%s): the monitor did not wait for three consecutive checks", gap, floor)
 	} else if gap > 3*time.Second {
 		t.Fatalf("the resolver was asked %s after the last byte: the dead air was not acted on", gap)
 	}
diff --git a/relay/drain/drain_test.go b/relay/drain/drain_test.go
index 35c7460f..de014a00 100644
--- a/relay/drain/drain_test.go
+++ b/relay/drain/drain_test.go
@@ -2,22 +2,71 @@ package drain
 
 import (
 	"context"
+	"os"
+	"path/filepath"
+	"regexp"
+	"strconv"
 	"sync"
 	"testing"
 	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
 )
 
+// supervisordStopWaitRe finds the ONE key this test's claim rests on. Anchored
+// and comment-aware: `#stopwaitsecs=99` in a note must not be read as the
+// setting, and supervisord's own ini parser would not read it either.
+var supervisordStopWaitRe = regexp.MustCompile(`(?m)^[ \t]*stopwaitsecs[ \t]*=[ \t]*([0-9]+)[ \t]*$`)
+
+// supervisordStopWait reads relay-go's stopwaitsecs out of the conf that
+// actually ships, rather than restating it as a Go constant.
+//
+// WHY THIS IS READ AND NOT COPIED. The number is a THRESHOLD DERIVED FROM
+// ANOTHER FILE, and a derived threshold restated as a literal goes stale
+// silently: change the conf and this test keeps asserting against the number
+// it was written with, reporting green about a window that no longer exists.
+// The comment this replaces said the conf "lives in a file this package cannot
+// read" -- which is not so, and the counter-example is in this module:
+// relay/internal/relaytest/corpus.go reads the Python harness's stderr
+// fixtures from a test, by the same runtime.Caller walk RepoRoot exposes here.
+//
+// It FAILS rather than skips or defaults when the file or the key is missing.
+// A helper that fell back to 20 would turn a renamed key into a permanently
+// green test asserting a number nothing in the repository says any more, which
+// is the silence-read-as-pass shape this test exists to avoid one level up.
+func supervisordStopWait(t *testing.T) time.Duration {
+	t.Helper()
+	rel := filepath.Join("docker", "supervisord.d", "relay-go.conf")
+	path := filepath.Join(relaytest.RepoRoot(), rel)
+	raw, err := os.ReadFile(path) // #nosec G304 -- a path this test computed from the repo root
+	if err != nil {
+		t.Fatalf("cannot read %s: %v -- this test's whole claim is a relationship between the "+
+			"drain's budget and that file's stopwaitsecs, so it must not pass without reading it",
+			rel, err)
+	}
+	match := supervisordStopWaitRe.FindSubmatch(raw)
+	if match == nil {
+		t.Fatalf("%s declares no stopwaitsecs=<n>. Either supervisord's stop window for relay-go "+
+			"moved to another key, or it was removed -- both change what this test is asserting, "+
+			"so neither may be defaulted through", rel)
+	}
+	seconds, err := strconv.Atoi(string(match[1]))
+	if err != nil { // unreachable while the pattern is [0-9]+, kept so a widened pattern cannot pass silently
+		t.Fatalf("%s: stopwaitsecs=%q is not an integer: %v", rel, match[1], err)
+	}
+	return time.Duration(seconds) * time.Second
+}
+
 // The three budgets are Go-side constants that answer to ONE external number:
 // docker/supervisord.d/relay-go.conf's stopwaitsecs=20, after which
 // supervisord SIGKILLs this process. Pinned as an arithmetic relationship
 // rather than as three literals, so a later change to any of them has to keep
 // the sum inside the window it exists to fit.
 func TestTheBudgetFitsInsideSupervisordsStopWindow(t *testing.T) {
-	// docker/supervisord.d/relay-go.conf:34. Written here as a literal
-	// because it lives in a file this package cannot read, and the plan's
-	// docker/supervisord.d/relay-go.conf:34, which the plan's Task 8 changes
-	// together with this constant when either moves.
-	const supervisordStopWait = 20 * time.Second
+	// READ from docker/supervisord.d/relay-go.conf, not restated here: this
+	// assertion is a relationship between a Go constant and that file's
+	// number, and a copy of the number cannot notice the file changing.
+	supervisordStopWait := supervisordStopWait(t)
 
 	if DefaultBudget >= supervisordStopWait {
 		t.Fatalf("DefaultBudget is %s against a stopwaitsecs of %s: the drain would be "+
diff --git a/relay/internal/relaytest/corpus.go b/relay/internal/relaytest/corpus.go
index 362f3ec3..0aa3bde4 100644
--- a/relay/internal/relaytest/corpus.go
+++ b/relay/internal/relaytest/corpus.go
@@ -38,6 +38,17 @@ func repoRoot() string {
 	return filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(file))))
 }
 
+// RepoRoot is the repository root, resolved from this file's own compiled-in
+// path. Exported because this package is the module's ONE answer to "where is
+// the repo from a test": relay/drain's own test reads
+// docker/supervisord.d/relay-go.conf through it, and a second, independently
+// maintained directory walk is the kind of drift that goes wrong quietly.
+//
+// runtime.Caller rather than the working directory, for the reason repoRoot's
+// own comment gives: `go test` sets the cwd to the PACKAGE directory, which is
+// a different depth for every package that asks.
+func RepoRoot() string { return repoRoot() }
+
 // CorpusPath is the absolute path of one capture.
 func CorpusPath(name string) string {
 	for _, known := range CorpusNames {
diff --git a/relay/main.go b/relay/main.go
index aee395d5..f6fa530e 100644
--- a/relay/main.go
+++ b/relay/main.go
@@ -40,8 +40,10 @@ func main() {
 
 	// The secret is never logged, in any form, at any level -- not its value,
 	// not its length, not a prefix. scripts/check_credential_logging.py polices
-	// the Python side of this rule; there is no Go equivalent yet, so it is
-	// held by hand here.
+	// the Python side of this rule and scripts/check_go_credential_logging.sh
+	// (relay/internal/credlint, 2c-4) polices this one -- but neither sees a
+	// secret that is not an ERROR, so this particular line is still held by
+	// hand: credlint checks error-typed arguments, and cfg.Secret is a string.
 	log.Printf("starting on port %d (dev routes: %t)", cfg.Port, cfg.DevRoutes)
 
 	// THE SAME manager, not a second one. Two would give the list endpoint
```

---

## Self-review

**Spec coverage.** The 2c-9 row's four clauses: `go test ./... -race -cover` wired into a floor ratchet (Tasks 2, 3, 7, 8); the floor raised to ≥80% (Task 7 Step 4 computes the ceiling and forbids the third option); the parity matrix's Go counterpart on every row (Task 6, and R11 for what "every row" means); the `Go result` aggregate green in the four-part shape (Task 3, Task 4 Step 10, Task 10 Step 2). Amendment A1.5 is Task 5; A2.4 is Task 4. § Requirements' four 2c-9 rows: `go.sum` empty (Task 0 Step 2, Task 10 Step 1), no Postgres/Redis driver (same), 100% Go-columned matrix (Task 6), coverage transferring to Go at ≥80% (Task 8). § Stage 2d's needs are stated in Task 10 Step 3.

**Spec coverage, second pass.** Ruling R16 and Task 1's Steps 7-11 are not in the spec's 2c-9 row at all — they come from 2c-8's review handoff. They are in scope because the row's subject is the gate and R16 is the same defect class the gate exists to remove; the PR description says so plainly rather than letting a reader wonder why a drain test moved in a coverage PR.

**Placeholder scan.** Two placeholder kinds remain, both deliberate and marked: `<2C9_MERGE_SHA>`/`<2C9_PR_NUMBER>` in Task 10 Step 3, which name a commit that does not exist while the plan is being executed, and Appendix E's `<…>` fields, every one of which Task 8 fills from the CI census and none of which may survive into the committed floor. `<2C8_MERGED_SHA>` is gone — it is `a635190c`. Every other number in this plan is measured on `a635190c` and re-measured by the task that uses it.

**Type consistency.** `--measure`/`--report`/`--gate`/`--write-floor` are the script's four modes throughout; the data directory is `/tmp/relay-go-coverage` in every workflow step and every task; the artifact is `relay-go-coverage`; the floor's fields are `shape`, `statements`, `missing`, `percent`, `measured`, `runs`, `packages`, `package_count`, `gomod` in the script, the floor template and the rulings table alike; `GO_PARITY_CLOSED` and `goRefs` are spelled the same in both guard files; `DISPATCHARR_RELAY_GO_BIN` is the only switch name used by the test and the workflow.
