# Plan: a cold HLS entry waits for the source's first chunk before it probes (#560)

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The whole change is byte-exact. Appendix A is the Go code and its tests, B the frontend mirror, C the E2E and its COVERAGE.md row, D the spec amendment, E the parity-matrix rows and F the defect-ledger entry. Each appendix is a `git diff` against the seed. The implementer applies them and does not rewrite them. The only slot to fill is `⟨PR⟩` in Appendix F.

**Goal.** An HLS entry on a cold channel answers the multivariant when the channel's ring publishes its first chunk late. Today that is every cold tune on the built-in `ffmpeg` stream profile, and every Proxy source under about 680 kb/s; both answer 502. After the fix, every HLS probe waits for a chunk past where its generation starts, bounded by the pipeline's stop, the ring's close and a new `hls.SourceStartWait` of 15 s. Only once that chunk exists does the probe spawn ffprobe and start its 3 s (or 8 s) bound. The entry's wait gains the same 15 s (43 s → 58 s), and hls.js's entry timeout follows it (65 s → 80 s). Owner ruling R113; issue #560.

**Seed.** `a9d6cee3` (`a9d6cee36a66484bdeb05cbb38dcfed49301f818`, `main`, "chore: fork housekeeping", #557). The brief named `a1e9da65` or later. `git diff --stat a1e9da65 a9d6cee3 -- relay e2e/tests/streaming frontend/src/utils docs/relay-parity-matrix.md metrics/curated/defects.yml docs/superpowers/specs` is empty, so the investigator's line numbers hold at this seed. Every `file:line` below was re-grepped at the seed with `git show "a9d6cee3:<path>"`. **The implementer re-greps them at the PR's base** (Task 1), and stops if anything named here has changed shape rather than just moved lines.

**Branch.** `fix/560-cold-hls-probe`, worktree `.worktrees/fix-560`, off `origin/main` at the seed. Under R113 **this plan is the branch's first commit and ships in the fix PR itself.** There is no separate plan PR.

**Authority**, in order of precedence:

1. **Owner ruling R113** (binding): fix it now, because it blocks the owner's QSV hardware run. Also the rulings the Phase 4 spec carries: R30 (the quick and full probe bounds), R40 (a ring that closes under a probe is a stop), R55/R58 (the 30 s startup allowance), R56/R57 (the entry's waits are DERIVED from the pipeline's own bounds, "so they cannot drift below what a legitimate cold software start can take"), and R21/R27/R52/R80/R93 (the Go ratchet: a raise needs a per-file listing, and O is counted by the start-line rule over every census round). Also R87: every HLS spec stops the channels it tuned.
2. **The Phase 4 spec**, `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` at the seed:
   - D9 (`:218`): "bounded to 3 s or 3,000,000 bytes"; "the bound **is** the probe's share of the zap time and the failover gap".
   - D7 (`:216`) and § Entry (`:315`): the multivariant waits up to 43 s, then 503 with `Retry-After: 1`.
   - § Encoder argv › Failure (`:585-648`): a failed probe fails the output and sets the channel's mark, and new HLS entries answer 502 until the next source boundary.
   - § Browser player (`:1180-1185`): hls.js's entry timeout is the tune budget plus the ready wait plus a margin.
   - ADR 0008 and ADR 0009 do not speak to probe timing. Nothing in them changes.
3. **The investigator's report** (the orchestrator's scratch `phase4/hls-arm64.md`, 2026-09-30). It carries the mechanism, the arm64 reproduction (a 502 at t = 3.025 s on the `ffmpeg` profile, and 200 on Proxy), the 6.08 s time to first body byte on the `ffmpeg` profile, and the Proxy `rate: 0.1` reproduction.
4. CLAUDE.md: the Go hooks, stdlib-only, credlint, zero lint findings under three GOOS, `go test -race`, and the Go coverage ratchet as amended by R21/R27 (§ Testing). Also AGENTS.md's test rules, `e2e/README.md`, `e2e/COVERAGE.md` and ADR 0002 (taxonomy tags), and `docs/agents/metrics.md` (the ledger).

**Issues.** The fix PR closes #560, and only its description carries `Closes #560.` (§ PR description draft). This plan's own commit, and every commit on the branch, says `Refs #560` and never a closing keyword in any form ("fix", "fixes", "close", "closes", "resolve", "resolves" followed by `#560`). GitHub reads commit messages too.

## Global constraints

1. **Standard library only** (`scripts/check_go_stdlib_only.sh relay`). The fix adds `fmt` to `relay/hls/feed.go`; it is stdlib.
2. **Zero lint findings under three GOOS** (`golangci-lint run ./...` natively, with `GOOS=linux` and with `GOOS=darwin`). Also green: `go vet ./...` under the same three, `go test -race ./...` and credlint (`go run ./internal/credlint ./...`). The new error messages are built with `errors.New` and with `fmt.Errorf` over a `time.Duration`; neither formats an error value, so credlint has nothing to flag. Measured clean on the prototype.
3. **The test-modification rule.** Exactly two existing Go tests and three existing frontend tests change, each because the entry wait it pins is what this PR changes. § Tests changed lists each with before and after. No assertion is deleted, weakened or given a wider tolerance.
4. **No local E2E stack.** The implementer does not build an image or start a Playwright stack. The E2E's red and green are both read from CI (Task 2 and Task 8). The shared `e2e-upstream` provider and `dispatcharr-testrunner` are never touched.
5. **No floor raise.** `scripts/coverage_relay_go.floor` is not edited (§ Coverage).
6. **No Python change**, so there is no backend label, no Gate 2 and no Django container.

## Overlap with sibling work

| Work | Touches | Interaction |
|---|---|---|
| PR #559, fix #553 (`fix/553-interlaced-output-rate`; **merged, `main` at `250ee10f`**) | `relay/hls/probe.go`, `probe_test.go`, the spec's § Encoder argv `R` bullet and **Changelog tail**, and **the tail of `metrics/curated/defects.yml`** | No Go overlap: this plan does not touch `probe.go`. Appendices A, B, C and E apply cleanly on #559's head (`67edca5d`, checked with `git apply --check`). **D and F conflict on their last hunk only**, because both PRs append after the same last line. #559 merged first, so this PR re-anchors those two hunks so its entries land after #559's (Task 1); the round-1 review confirmed that on `250ee10f` only D's and F's last hunks fail. The validator then reads `48 defects`. |
| `.worktrees/fix-542`, `.worktrees/fixplan-554-556` | plan documents only at their heads (`git diff --stat origin/main...<branch>`) | None. |
| The owner's QSV hardware runbook (`runbook-hw`) | an operational note that cold HLS on an FFmpeg-profile channel 502s | After this merges, the note is obsolete: a cold tune waits instead. The orchestrator relays this (open question 4). |

## The defect, at the seed

The chain, re-grepped at `a9d6cee3`:

- `relay/httpapi/stream.go:301` runs `serveHLSEntry` straight after `Channels.Attach`. Attach returns once the tune has started, not once bytes exist. `relay/channel/hlsoutput.go:122` then calls `hls.Start` under `outMu`.
- `relay/hls/pipeline.go:439-441`: generation 0 starts at `ring.Head()`, or at `ring.Join(JoinBehind)`, which on an empty ring is also the head (`relay/buffer/ring.go:424-425`).
- `relay/hls/pipeline.go:671` arms `pctx` (Analyze + KillWait + 1 s), and **`:684` arms the feed's 3 s deadline at the spawn**.
- `relay/hls/feed.go:95-101`: with no chunk past the start, `ring.Wait` hits that deadline, and the feed ends `feedStopped` with `written == 0`. `pipeline.go:689` then closes ffprobe's stdin. ffprobe prints `pipe:0: End of file` and exits 1.
- `pipeline.go:626`: `probeGeneration` returns a quick-probe error at once, with no re-probe. `:501-504`: `run` logs `the HLS probe failed` and calls `finish(ErrFailed)`.
- `relay/httpapi/hls.go:327-342`: the entry marks the channel (`FailHLS`) and answers 502 `{"error": "HLS output failed"}`.

**Why 3 s is always too short on the `ffmpeg` profile.** Its ffmpeg (`-user_agent {userAgent} -i {streamUrl} -c copy -f mpegts pipe:1`, `core/migrations/0006_set_locked_stream_profiles.py:12-16`) analyses its own input before it writes a byte. The ring then publishes only whole 255,868-byte chunks (`relay/buffer/ring.go:190-202`). The investigator measured the first body byte at 6.08 s on a real-time source. A Proxy source is as late when its rate is under about 680 kb/s, since 255,868 × 8 / 3 s ≈ 682 kb/s; reproduced at `rate: 0.1`, where the first chunk landed at 4.83 s.

**A second path, found while prototyping, has the same mechanism.** After a generation dies (`outcomeDied`, `pipeline.go:560`) or ends over-long (`:575`), the next one starts at `ring.Head()`, so its probe waits for the *next* chunk. At the seed, real ffprobe fails there whenever that chunk takes more than 3 s. The seed's `TestDeathsAfterTheFirstSegmentRestartUntilTheThirdWithinAMinute` passes only because its stand-in probe prints its JSON without reading stdin, on a ring that never advances (§ Tests changed).

**A boundary is not affected.** A running generation's feed sees a source boundary only when it reads the chunk at the boundary index (`feed.go:69-73`), and nothing else in `attempt` watches for one (`pipeline.go:810-1016`). So the new connection's first chunk exists before the next generation's probe starts. Q6's failover gap is unchanged.

**Measured red at the seed** (planner, `go test -count=1 -race`, on a scratch export of `a9d6cee3`, running only the two new tests that compile there):

```
--- FAIL: TestAProbeWaitsForTheSourcesFirstChunk (3.52s)
    cold_probe_seed_test.go:56: Ready = hls: the HLS output failed with the first chunk 3.5s after the start: the probe's 3s bound ran out before its input arrived
        time=2026-09-30T17:14:35.662+01:00 level=ERROR msg="the HLS probe failed" channel=test format=hls generation=0 error="hls: the probe failed: ffmpeg: the process exited with status 1"
--- FAIL: TestARingThatClosesBeforeItsFirstChunkIsAStop (0.21s)
    cold_probe_seed_test.go:77: a ring that closed before its first chunk spawned 1 probe(s) or logged an error:
```

The first ERROR line is byte for byte the production log in the issue. (The file name differs only because the planner ran a seed-only copy of the two tests. The other two tests use a new `Config` field and do not compile at the seed; their red is BC2 and BC4.)

## The design

### What was weighed

The investigator named three directions.

1. **Wait for the first chunk before spawning ffprobe and arming its bounds. Chosen.** It removes the mechanism, not a symptom. The probe's bound goes back to meaning what D9 says, "the probe's share of the zap time": analysis, not the source's cold start. ffprobe also no longer sits idle on an empty pipe. It covers generation 0, the post-death restart and the post-over-long restart with one change in one place, `Pipeline.probe`, which every probe goes through, the R30 re-probe included (the re-probe's wait returns at once because the chunk already exists).
2. **Treat a zero-byte `feedStopped` probe as "no input yet" and retry. Rejected.** After direction 1 it is unreachable. When ffprobe is spawned, at least one chunk past the start is resident. The feed's first `Read` returns it at once, and its `Write` blocks only on the pipe, which the feed context does not interrupt. So the feed either writes those bytes or fails the write (`feedWriteFailed`, once `pctx` kills a process that never reads). A ring evicted past the start still returns its oldest chunks (`ring.go:352-357`). A retry loop for an unreachable state would need a bound of its own and a test that cannot be driven. It is complexity with nothing to hold.
3. **Give the entry's wait a term for the source's start. Chosen, as the consequence of 1.** R56/R57's rule is that the entry's wait is derived from the pipeline's own bounds. Direction 1 adds a bound (the wait for the first chunk), so the derivation gains its term. Leaving the wait at 43 s would knowingly drift below the worst legitimate cold start, which R57 forbids.

### The total bound, and why 15 s

The wait needs a bound of its own. The pipeline's context and the ring's close are not enough: the channel's rules for a source that sends nothing are slow. While a connection is up and the ring is empty, the health monitor's threshold is `channel_init_grace_period`, 60 s by default (`relay/channel/health.go:36-41`, `apps/proxy/config.py:59`), then 3 checks at 5 s, and only then a reconnect or a switch. That is 75 s before the first recovery attempt, and far longer before the ring closes. Without a bound of its own, an entry on a dead source would sit to its own deadline and answer 503. And a pipeline held by a running session (the post-death case) would wait with no bound at all short of the channel's end.

**`hls.SourceStartWait` = 15 s**, a package constant, with a `Config.SourceStartWait` override for tests alone (the idiom of `ExitGrace` and `StallTimeout`). The justification:

- **2.5 times the measured 6.08 s** first chunk of the `ffmpeg` profile. VLC and Streamlink were not measured; Streamlink's own playlist resolution typically takes a few seconds, well inside 15 s.
- **The Proxy source's 5 s connect bound** (dial and response headers, `relay/channel/source_proxy.go:71-75`; `relay/httpapi/stream.go:895` does not set it, so the default holds), plus one 255,868-byte chunk at 205 kb/s.
- **It keeps the entry's wait under every timeout that fronts it**: 58 s against nginx's 300 s on the tune locations (`docker/nginx.conf:350`, `:538`, `:697`). hls.js's entry timeout becomes 80 s.

### What happens when the bound passes

**The output fails as a failed probe does.** `finish(ErrFailed)` runs, the entry marks the channel and answers 502 `{"error": "HLS output failed"}`, and the mark holds until the next source boundary (spec § Encoder argv › Failure; parity row 44). The log line is `the HLS probe failed … error="hls: the channel's source sent no input within 15s, so the probe never ran"`. The channel and its TS clients are unaffected. This adds no new error, no new status and no new branch in `watchHLS`, `FailHLS` or the entry, and it gives a viewer of a dead source a bounded answer at about 15 s rather than a 503 at 58 s. The frontend already words a 502 as "The channel's source is unavailable." (`FloatingVideoUtils.js:132`).

**A ring that closes during the wait is a stop**, as R40 makes one that closes under a probe: `feedClosed` → `finish(nil)` → the entry's 503 "the channel is ending". **A stop during the wait ends it at once**, with no ERROR.

**One implementation fact the prototype found:** `Ring.Wait` answers **nil** when `Close` wakes it, and `ErrClosed` only on the next call (`ring.go:452-467`). `feed` meets that through its Read-then-Wait loop. So `awaitInput` loops on `ring.Head() <= start`, and a single `Wait` is wrong. BC5 pins this.

### What a client sees

- **The entry blocks** from the tune until the multivariant (headers included), or until an error: 502 at `SourceStartWait` for a source that sends nothing, 502 for a probe that fails, 503 `Retry-After: 1` at 58 s for inits that never arrive. A typical cold `ffmpeg`-profile tune: the first chunk at about 6 s, the quick probe 3 s, then the encoder's first init. The software 576i encode is ready a few seconds after its spawn, so the entry answers at about 12-15 s. That is an estimate from the measured terms, not a measurement: the E2E asserts success, not a time, and the owner's hardware run records the real figure (open question 1).
- **hls.js** (the browser player, D18): `manifestLoadPolicy.maxLoadTimeMs` becomes 80 s (the 14.1 s tune budget, plus 58 s, plus a 7.9 s margin), `timeoutRetry: null`, and `errorRetry` retries once after 1 s. At the seed's 65 s, hls.js would abandon a legitimate worst-case entry at 72.1 s. And an abandoned entry stops its not-ready pipeline at refcount zero (`hlsoutput.go:159-185`), so the retry would start cold again. Hence Appendix B. The E2E harness's own entry timeout (`e2e/fixtures/hls.ts:364`, 60 s) is raised the same way, to a derived 80 s, so a slow CI entry fails as the relay's 503 rather than as a Playwright request timeout (Appendix C). A 502 retried once meets the channel's mark and fails fast with the same message.
- **Safari and AVPlayer.** Where MSE or ManagedMediaSource exists, Safari runs hls.js, as above. Native playback (AVFoundation, and the Mino app) sends one request and waits. Its own timeout for a multivariant that takes a while was never measured in this programme; the 4a-1b AVPlayer runs saw about a 20 s cold entry succeed. The worst case moves from 43 s to 58 s past the tune, and a typical cold `ffmpeg` tune moves from a certain 502 at 3 s to success at about 12-15 s. Open question 1 asks the owner's hardware run to record a cold `ffmpeg`-profile entry in AVPlayer.
- **A media playlist's wait stays 43 s.** It is requested only after its multivariant, which is served only once one generation's inits exist, so the source has started. `defaultPlaylistWait` keeps its own derivation, under nginx's 60 s on `/hls/`, and `docker/nginx.conf:476-477` stays true. **Which nginx timeout governs the entry:** the entry is a tune request, served on `^~ /proxy/ts/stream/`, `^~ /live/` and the XC three-segment regex, each `proxy_read_timeout 300s` (`docker/nginx.conf:350`, `:538`, `:697`); the 60 s on `^~ /hls/` (`:488`) governs only the session resources. The stale comment at `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts:653-655`, which put the entry's wait on `/hls/`, is corrected in Appendix C.

### Linger, rewind and reclaim (4a-3, 4a-1c)

- **A pipeline that is not ready never lingers** (`hlsoutput.go:194-203`, `lingerEligibleLocked` ends `return p.IsReady()`). So an entry that times out, or a pipeline that fails at `SourceStartWait`, leaves no linger, exactly as a failed probe does at the seed.
- **A lingering pipeline whose later generation waits for input** (after a death at the ring's head) keeps lingering. Its wait ends at the first chunk, at 15 s (a failure; the mark, as at the seed, where it failed at 3 s), at the channel's stop, or at the linger's end.
- **Reclaim.** An entry request in flight is activity, so its channel is not reclaimable while it waits (parity row 46). The longest such hold grows from 43 s to 58 s past the tune, and only on a cold channel that has not yet published a chunk.
- **The rewind window** starts with the pipeline and holds nothing until the first segment. The wait adds nothing to it.

### What is not changed

- `QuickProbe`, `FullProbe` and the probe's argv; the startup stall allowance; the entry's 502/503 contract (only the 43 s becomes 58 s); the media playlist's wait; `docker/nginx.conf`.
- **No CLAUDE.md edit.** CLAUDE.md names neither the probe bound nor the 43 s wait. Its frontend test count (6,216) does not move: this PR changes three frontend tests and adds none.
- **ADRs 0008 and 0009** are not amended: neither speaks to probe timing.

### The spec: an amendment, and a Changelog line

Yes, the spec needs both. D9's bound gains a start ("the bound starts at the generation's first chunk"). The entry's 43 s becomes 58 s in D7, § Entry, § Presence › Activity and § Automatic generation's R42 bullet. The browser player's 65 s becomes 80 s. § Encoder argv › Failure gains a paragraph, "A probe waits for its input". The Changelog gains an entry. The PR sections (§ 4a-1b, § 4a-1d) and earlier Changelog entries are history and are left alone. Appendix D is the diff.

### The parity matrix: three rows amended, no new row

No new row is needed. **Row 33** is the probe's behaviour ("Each HLS generation is probed where it starts … bounded at 3 s"), and this changes when that bound starts, so row 33 is extended in place: the claim, a `relay/hls/feed.go:116-132` source citation, and five pins (all four `cold_probe_test.go` tests, which also pin its note's close-and-stop clause, and the E2E). **Row 37** states the entry's "not ready within 43 s", which becomes 58 s, with one more pin. **Row 36** (`:210`) said "so the entry's 43 s waits stay under nginx's 60 s"; it now says a media playlist's 43 s wait stays under the 60 s on `/hls/` and the entry's 58 s under the 300 s on the tune locations, consistent with Appendix D's R42 bullet, and its pin `TestTheEntryWaitsCoverTheLongestTargetDuration` pins exactly that pair. One line each, per the matrix's own rules. `npx playwright test --project=guards` passes on the prototype, so every new citation and pin resolves (Appendix E).

### The defect ledger: one entry

Yes, one entry. Precedent: #553 (`hls-interlaced-field-rate-doubled`), #111 and #97 each added a `fixed` entry for a defect that never had a CLAUDE.md item. The new entry is `hls-cold-probe-502`, `correctness`, severity **high** (every cold HLS tune on the default stream profile fails, and it blocks the owner's QSV run), `fixed`, `test: relay/hls/cold_probe_test.go`, and `fixed_in: ⟨PR⟩` filled once the PR exists (Appendix F).

## Tasks

**Task 0: occupancy.** Run `git -C /Users/dion/git/Dispatcharr/.worktrees/fix-560 status --porcelain && git -C /Users/dion/git/Dispatcharr/.worktrees/fix-560 log --oneline -3`. The tip must be this plan's commit and nothing else. If another agent's edits are in flight, stop and report to the orchestrator.

**Task 1: re-anchor.** Let `BASE` be `origin/main` at the time you work.
- `git show "${BASE}:relay/hls/pipeline.go"` must still read `feedCtx, stopFeed := context.WithTimeout(pctx, bound.Analyze)` inside `func (p *Pipeline) probe`, and `defaultReadyWait    = hls.QuickProbe.Analyze + …` with `defaultPlaylistWait = defaultReadyWait` in `relay/httpapi/hls.go`. `git show "${BASE}:relay/buffer/ring.go"`'s `Wait` must still answer nil on a close wake.
- If `BASE` ≠ `a9d6cee3`: merge `origin/main` into the branch (never rebase it: the plan commit has been pushed and reviewed at its SHA), then `git apply --check` each appendix. If PR #559 has merged, Appendices D and F fail on their last hunk only: apply them with `git apply --3way`, keep **both** entries with #559's first, and record it in the PR body.
- If anything else has changed shape, stop and report.

**Task 2: the E2E first, and its red read from CI.**
- Apply Appendix C (`e2e/tests/streaming/hls-entry.spec.ts`, `e2e/fixtures/hls.ts`, `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts` and `e2e/COVERAGE.md`). Run `cd e2e && npm ci && npx tsc --noEmit && npx playwright test --project=guards`.
- Commit (message in § Commits) and push.
- Dispatch the E2E workflow on the branch: `gh workflow run e2e-tests.yml --repo D10Scot/Dispatcharr --ref fix/560-cold-hls-probe`. Only the plan and the E2E are on the branch, so this runs the seed's relay.
- From the `streaming` job, record the new test's red. It must be `an HLS entry at /proxy/ts/stream/<uuid>?output_format=hls answered 502, want 200: {"error": "HLS output failed"}` (the fixture's own message, `e2e/fixtures/hls.ts:366-368`). A green result here would mean CI's `ffmpeg` profile publishes its first chunk within 3 s, and the E2E cannot see the defect. Then stop and report; do not go on to the fix.
- Record the run id. If the rest of the matrix is slow, the `streaming` job's result is the one this task needs; the run need not finish.

**Task 3: the Go change, red before green.**
- Apply Appendix A.
- Run each break-check in § Break-checks BC1-BC6 against the fixed tree, revert each before the next, and record the red lines.
- Run the gates from `relay/`: `gofmt -l .` must print nothing; then `go build ./...`, `go vet ./...` (natively and with `GOOS=linux` and `GOOS=darwin`), `go test -count=1 -race ./...`, `golangci-lint run ./...` under the same three, and `go run ./internal/credlint ./...`. From the repo root: `scripts/check_go_stdlib_only.sh relay` and `scripts/check_go_credential_logging.sh relay`.
- The `TestReal*` tests must **run**, not skip: ffmpeg and ffprobe must be on `PATH`. A skip line (`is not on PATH`) means they did not run, and the report says so.
- The `PostToolUse` Go hook also runs on every `.go` edit. A hook run is no substitute for this list.

**Task 4: the frontend mirror.** Apply Appendix B. Run `cd frontend && npm ci && npx vitest --run`: every test passes, 6,216 of them (the count is unchanged: no `it` is added). Then run the frontend break-check FE-BC.

**Task 5: the documents.** Apply Appendices D and E. Run `cd e2e && npx playwright test --project=guards` (the parity-matrix spec checks every citation and pin in rows 33, 36 and 37).

**Task 6: commits and the PR.**
- Commit per § Commits and push.
- Open a draft PR: `gh pr create --repo D10Scot/Dispatcharr --draft --base main --head fix/560-cold-hls-probe --title "fix(relay): a cold HLS entry waits for the source's first chunk before it probes (#560)" --body-file <file>`, with the body from § PR description draft and its slots filled.
- Check the closing references: `gh pr view <n> --repo D10Scot/Dispatcharr --json closingIssuesReferences --jq '[.closingIssuesReferences[].number]'` must print `[560]` and nothing else.
- Then apply Appendix F with `⟨PR⟩` filled in. Run `python -m metrics.build --validate-only --curated metrics/curated`, which prints `ok: … 47 defects` (48 if #559 has merged). Commit the ledger and push.

**Task 7: the Go coverage census** (§ Coverage). Its result goes in the PR body.

**Task 8: CI.** Every required check on the head is green (§ Gates), and the new E2E passes in the `streaming` job: that is its green.

### Commits

Stage and commit in separate Bash calls, each message written to a file and committed with `-F`, each ending with the harness's attribution lines. Every message says `Refs #560` and carries no closing keyword. In order:

1. `docs(plan): a cold HLS entry waits for the source's first chunk (Refs #560)` (the planner's; already on the branch).
2. `test(e2e): a cold hls tune on the ffmpeg profile answers the multivariant (Refs #560)`: Appendix C.
3. `fix(relay): a probe waits for its generation's first chunk before its bound starts (Refs #560)`: Appendix A.
4. `fix(frontend): hls.js's entry timeout follows the relay's 58 s ready wait (Refs #560)`: Appendix B.
5. `docs: spec amendment and parity rows 33, 36 and 37 for #560 (Refs #560)`: Appendices D and E.
6. `docs(metrics): ledger entry for the cold HLS probe (Refs #560)`: Appendix F, after the PR exists.

## Tests added

- `relay/hls/cold_probe_test.go` (new; named for the defect):
  - **`TestAProbeWaitsForTheSourcesFirstChunk`.** A pipeline over an empty ring. After `QuickProbe.Analyze + 500 ms` (3.5 s) the test writes more than `QuickProbe.Bytes`, and `Ready` must answer nil within 10 s. The probe command is `sh` behaving as ffprobe does on `pipe:0`: it reads its input to the end, fails `pipe:0: End of file` (exit 1) on an empty input, and prints the probe JSON otherwise. Red at the seed (quoted above). About 3.5 s.
  - **`TestASourceThatSendsNothingFailsTheOutputAfterTheStartWait`.** `Config.SourceStartWait` is 400 ms and nothing is ever written. `Ready` must answer `ErrFailed` no earlier than 400 ms and within 5 s, with no probe spawned and the log saying `sent no input within 400ms`. This is the never-produces-a-byte case.
  - **`TestARingThatClosesBeforeItsFirstChunkIsAStop`.** The ring closes 200 ms in. `Err` must be nil, with no probe spawned and no ERROR logged. Red at the seed (quoted above).
  - **`TestAStopWhileWaitingForTheFirstChunkIsAStop`.** `SourceStartWait` is 1 minute, and `Stop` 200 ms in must return within 2 s, with `Err` nil, no probe spawned and no ERROR.
- `relay/httpapi/hls_test.go::TestTheEntryWaitAlsoCoversTheSourcesStart`: `readyWait()` ≥ `SourceStartWait` + quick + full + the startup allowance, and < 300 s (nginx on the tune locations).
- `e2e/tests/streaming/hls-entry.spec.ts`, `a cold hls tune on the built-in ffmpeg stream profile answers the multivariant` (`@contract`): a fresh channel on the locked `ffmpeg` profile, `mpeg2-576i-mp2` at `rate: 1`. The entry answers the multivariant, and the video playlist lists at least one segment within 60 s. `finally` leaves the session and calls `stopChannels` (R87). Its red is Task 2's CI run; its green is the PR's.

## Tests changed

Each change pins a behaviour this PR changes. Nothing is loosened.

1. **`relay/hls/pipeline_test.go::TestDeathsAfterTheFirstSegmentRestartUntilTheThirdWithinAMinute`** (`:343`).
   - **Before:** `newHarness` writes one chunk, and the ring never advances.
   - **After:** a `feedRing(t, h)` line (the helper at `:1077`, which the R55 tests already use) keeps the ring advancing every 20 ms, with a two-line comment. Every assertion is unchanged (ErrFailed, three spawns, `init-0/1/2`, two discontinuities, "keep dying").
   - **Why:** each restart at the ring's head now probes the chunks after the head and waits for them. On a ring that never advances, the second generation waits out `SourceStartWait` and the test's 10 s `waitDone` fires. That is the new, intended behaviour for a source that sent nothing, and `TestASourceThatSendsNothingFailsTheOutputAfterTheStartWait` pins it. The old premise, a restarted generation producing segments from no input, held only because the stand-in probe never reads stdin, and real ffprobe fails there at the seed.
   - **Verified not weakened:** with only the added line, the test passes at the seed three times out of three (6.14-6.16 s), and it passes on the fix five times out of five (6.16-6.21 s, against 6.18 s at the seed).
2. **`relay/httpapi/hls_automatic_test.go::TestTheEntryWaitsCoverTheLongestTargetDuration`** (`:224`).
   - **Before:** it asserts `got != 43*time.Second` for both ReadyWait and PlaylistWait (`:236`).
   - **After:** a `want` map, `ReadyWait` 58 s and `PlaylistWait` 43 s, compared per name, and a comment clause "the entry's adds the source's start (issue #560), 58 s". The floor and the under-60 s checks are unchanged.
   - **Why:** the ReadyWait value is exactly the behaviour this PR changes.
3. **`frontend/src/components/__tests__/FloatingVideo.test.jsx::'uses the live HLS config'`** (`:669-677`).
   - **Before:** `maxLoadTimeMs > HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS` (14,100 + 43,000), under the message "the entry timeout must cover the relay tune budget plus its ready wait"; the import list names `HLS_RELAY_WAIT_MS`.
   - **After:** `… + HLS_RELAY_READY_WAIT_MS` (14,100 + 58,000), message unchanged; the import names `HLS_RELAY_READY_WAIT_MS` in its place.
   - **Why:** Appendix B makes `HLS_RELAY_WAIT_MS` the playlist wait. Left alone, this pin would keep comparing against 43 s under a message naming the ready wait, and stay green with the entry timeout back at 65 s: a test gone hollow without changing (review round 1, finding 1).
4. **`frontend/src/utils/components/__tests__/FloatingVideoUtils.test.js::'bounds the entry timeout by the relay and by nginx'`** (`:568-575`).
   - **Before:** `maxLoadTimeMs > HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS`. **After:** `… + HLS_RELAY_READY_WAIT_MS`; the `< 300_000` and `timeoutRetry` checks are unchanged. **Why:** the same as 3, in the unit that builds the config.
5. **`…FloatingVideoUtils.test.js::'mirrors the relay bounds as literals'`** (`:588-591`).
   - **Before:** pins `HLS_RELAY_WAIT_MS` 43000 and `HLS_RELAY_TUNE_BUDGET_MS` 14100. **After:** the same two, plus `expect(HLS_RELAY_READY_WAIT_MS).toBe(58000)`; the file's import list gains `HLS_RELAY_READY_WAIT_MS`. **Why:** the new mirror constant is pinned where its siblings are, rather than in a near-duplicate `it`.

`relay/httpapi/hls_test.go::TestTheEntryWaitsOutALegitimateColdStart` (`:1199`) is **not** changed. It still holds, as it states it (ReadyWait and PlaylistWait ≥ the cold start, < 60 s), and the new term has its own test above.

## Break-checks

Apply each wrong edit alone to the fixed tree, run the named test with `go test -count=1 -run '<name>' ./<pkg>` from `relay/`, compare the red line with the one below, record it in the PR body, and revert. Every one was run on the prototype of this exact diff; the lines are quoted from those runs (line numbers are the prototype's).

- **BC1: the deadline armed at the spawn again**, the seed's shape. In `Pipeline.probe`, delete the three-line `if fed, err := awaitInput(…); err != nil { … }` and leave `_ = wait`. Test `TestAProbeWaitsForTheSourcesFirstChunk`, in `./hls`:
  `cold_probe_test.go:57: Ready = hls: the HLS output failed with the first chunk 3.5s after the start: the probe's 3s bound ran out before its input arrived`
- **BC2: no bound of its own.** In `awaitInput`, `context.WithTimeout(ctx, within)` → `context.WithCancel(ctx)`. Test `TestASourceThatSendsNothingFailsTheOutputAfterTheStartWait`:
  `cold_probe_test.go:79: Ready = context deadline exceeded after 5.001716416s, want ErrFailed: a source that never sent a byte held the pipeline past SourceStartWait`
- **BC3: a close treated as a failure.** In `awaitInput`, the `ErrClosed` arm returns `feedResult{end: feedStopped}`. Test `TestARingThatClosesBeforeItsFirstChunkIsAStop`:
  `cold_probe_test.go:106: Err after the ring closed before its first chunk = hls: the HLS output failed, want nil: the channel is ending`
- **BC4: the wait deaf to a stop.** In `awaitInput`, `context.WithTimeout(ctx, within)` → `context.WithTimeout(context.WithoutCancel(ctx), within)`. Test `TestAStopWhileWaitingForTheFirstChunkIsAStop`:
  `cold_probe_test.go:127: Stop took 7.500692209s: the wait for the first chunk did not end with the pipeline's context`
- **BC5: a single `Wait`.** In `awaitInput`, the `case err == nil:` arm returns `feedResult{}, nil` instead of `continue`. A close wake now reads as input. Test `TestARingThatClosesBeforeItsFirstChunkIsAStop`:
  `cold_probe_test.go:109: a ring that closed before its first chunk spawned 1 probe(s) or logged an error:`
- **BC6: the entry's wait without the new term.** In `relay/httpapi/hls.go`, `defaultReadyWait    = hls.SourceStartWait + defaultPlaylistWait` → `defaultReadyWait    = defaultPlaylistWait`. Tests `TestTheEntryWaitAlsoCoversTheSourcesStart|TestTheEntryWaitsCoverTheLongestTargetDuration`, in `./httpapi`:
  `hls_automatic_test.go:239: the default ReadyWait is 43s, want 58s`
  `hls_test.go:1223: the default ReadyWait is 43s, below the source's start plus a cold start, 56s (SourceStartWait 15s + 41s)`
- **FE-BC: hls.js's entry timeout without the new term.** In `FloatingVideoUtils.js`, `HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_READY_WAIT_MS + 7_900` → `HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS + 7_900`. `npx vitest --run src/utils/components/__tests__/FloatingVideoUtils.test.js src/components/__tests__/FloatingVideo.test.jsx` reddens both files, 2 failed of 118:
  `FAIL src/components/__tests__/FloatingVideo.test.jsx > FloatingVideo > Live channel over HLS > uses the live HLS config` / `AssertionError: the entry timeout must cover the relay tune budget plus its ready wait: expected 65000 to be greater than 72100`
  `FAIL src/utils/components/__tests__/FloatingVideoUtils.test.js > FloatingVideoUtils: live channels over HLS > buildLiveHlsConfig > bounds the entry timeout by the relay and by nginx` / `AssertionError: expected 65000 to be greater than 72100`
- **The E2E's break-check is its CI red** (Task 2): the seed's relay is the wrong edit.

## Coverage (R21, R52, R80, R93)

**Expected: no raise, O = 0.**

The PR's new or changed non-test statements under `relay/` are these:
- `relay/hls/feed.go`: `awaitInput`, whole.
- `relay/hls/pipeline.go`: the `wait` default and the `awaitInput` call in `probe`. Also `SourceStartWait`, a constant, and the `Config` field, neither a statement.
- `relay/httpapi/hls.go`: the two package-level `var` initialisers, which Go's coverage does not instrument.

The prototype's measurement, over `./hls ./httpapi` with `-race -covermode=atomic`, took every block whose **start line** falls in an added range of `git diff -U0 a9d6cee3 -- relay ':!*_test.go' ':!relay/internal'`: 15 statements, 0 uncovered. Every arm of `awaitInput` has its own test: nil (test 1), the timeout (test 2), `ErrClosed` (test 3) and the context (test 4). The floor's `missing` (705 at the seed) does not move, and `scripts/coverage_relay_go.floor` is **not edited**.

**The census is still run**, because the PR changes product Go code, and R21/D20 define the additions measure by the census:
1. Dispatch `go-tests.yml` on the branch (`gh workflow run go-tests.yml --repo D10Scot/Dispatcharr --ref fix/560-cold-hls-probe`) at least twelve times, one at a time (its concurrency group cancels an in-progress run on the same ref). Continue until the maximum has held for six consecutive rounds. A round counts only when its `build` job succeeded.
2. Record each round's `this run missing=` from the `Coverage gate` job's log, in order, with its run id.
3. From each round's `relay-go-coverage` artifact, **O is computed thus**. Take `git diff -U0 "${BASE}" "${HEAD}" -- relay ':!*_test.go' ':!relay/internal'`, and collect each file's added line ranges from the `+start,count` of every `@@` header. A profile line `<importpath>/<file>:<sl>.<sc>,<el>.<ec> <stmts> <count>` counts when `<file>` is in that diff, `<sl>` is in one of its added ranges, and `<count>` is 0. O is the sum of `<stmts>` over those lines, per file. The expected listing is `relay/hls/feed.go 0`, `relay/hls/pipeline.go 0` and `relay/httpapi/hls.go 0` in every round.
4. **Every round must be ≤ 705.** A round above 705 with O = 0 is not this PR's code. Stop the census, attribute the difference per block against a base-profile round (`awk 'NR>1 && $3==0 {print $1}'` on both, then diff the sets), and report it. A pre-existing flap above the floor is a re-measurement PR of its own, and **never a raise here**.
5. Run the loop detached; the orchestrator watches a stopfile. About twelve sequential runs, several hours.

The floor still carries `raise_from=691` / `raise_listed=14` from 4a-3. They are inert while `missing` does not rise (`scripts/check_floor_raise.sh` reads them only on a rise), and this PR leaves them alone, as #559 does.

**Python Gate 2**: untouched, since there is no Python change.

## Gates

- **Go:** Task 3, § Break-checks, § Coverage.
- **Frontend:** Task 4 (the whole vitest suite; `Frontend result`).
- **E2E:** `tsc --noEmit` and `guards` locally (Tasks 2 and 5). The `streaming` project on CI runs the new test: red at Task 2, green on the PR head. `E2E result` must be green.
- **Metrics:** `python -m metrics.build --validate-only --curated metrics/curated`.
- **CI:** every required check green on the PR's head: `Go result`, `E2E result`, `Lifecycle result`, `Backend result`, `Frontend result`, and the review bot once `pr-merge-gate` marks the PR ready.
- **No hardware gate.** The owner's QSV run is what this unblocks, and open question 1 asks it to record a cold entry. It does not gate the merge.

## Open questions, each with a recommendation

1. **AVPlayer's own timeout on a slow multivariant is unmeasured.** Recommendation: the owner's QSV hardware run, which this PR unblocks, records one cold entry on an `ffmpeg`-profile channel in AVPlayer: its time to multivariant and whether the item plays. No code waits on it. The worst case moves from 43 s to 58 s past the tune only when every bound is spent; the common case moves from a certain 502 to success.
2. **15 s for `SourceStartWait`, or tie it to the channel's `channel_init_grace_period`?** Recommendation: 15 s, a constant. Tying it to the per-channel setting (60 s by default) would make the entry's wait per-channel, and 60 s would put the entry's worst case at 103 s, past hls.js's timeout and past any plausible AVPlayer patience. A source slower than 15 s to its first chunk is failing by any viewer's measure. Owner may prefer 10 s: that makes 53 s and 75 s, at the cost of the Proxy connect-plus-one-chunk margin.
3. **A slow but alive source is marked HLS-failed until its next boundary.** A source that sends its first chunk after 15 s while a TS client holds the channel leaves HLS refused (502) until a reconnect or switch. That is the spec's existing failure semantics, and at the seed the same channel failed at 3 s, so this strictly narrows the case. Recommendation: accept it. The alternative, a separate `ErrNoInput` that answers 503 and sets no mark, adds a sentinel and branches in `watchHLS`, `FailHLS` and the entry for a case this PR already makes rare.
4. **The runbook's cold-502 note.** Recommendation: once this merges, the orchestrator tells `runbook-hw` that a cold HLS tune on an FFmpeg/VLC/Streamlink channel now waits rather than failing, so the "warm the channel first" workaround can go.
5. **Should more HLS E2E coverage seed the default profile?** The investigator notes that Proxy-only seeding hid this. Recommendation: this PR adds the one cold `ffmpeg`-profile test. Moving other specs off Proxy would change what they measure (Proxy's fast start is deliberate there for `rate: 1` pacing), so that is a follow-up issue if the owner wants one, not this PR.

## PR description draft

Fill the `⟨…⟩` slots from Tasks 1, 2, 3, 4 and 7.

> **fix(relay): a cold HLS entry waits for the source's first chunk before it probes.** A cold channel's HLS pipeline starts at the entry's attach, before the ring holds a byte, and the quick probe armed its 3 s feed deadline at ffprobe's spawn. The built-in `ffmpeg` stream profile, the default, publishes its first chunk about 6 s after a cold tune, so every cold HLS tune on it answered 502 `HLS output failed`; so did any Proxy source under about 680 kb/s. Every probe now waits for a chunk past where its generation starts before it spawns ffprobe and starts its bound. The wait is bounded by the pipeline's stop, by the ring's close (a stop, as R40) and by `hls.SourceStartWait`, 15 s, after which the output fails as a failed probe does. The entry's wait is 58 s (R57's 43 s plus those 15 s), and hls.js's entry timeout is 80 s; a media playlist's wait stays 43 s. A generation restarted at the ring's head after a death waits the same way. A source boundary never did, so the failover gap is unchanged. Spec: D7, D9, § Entry, § Encoder argv › Failure, § Presence, § Browser player and a Changelog entry. Parity rows 33, 36 and 37 are amended. The E2E harness's entry timeout is 80 s, derived as the player's. Owner ruling R113. Plan: `docs/superpowers/plans/2026-09-30-fix-560-cold-hls-probe.md` (this PR's first commit), passed at `⟨plan PASS SHA⟩`. Anchors re-grepped at `⟨BASE⟩`: ⟨moved lines, or "none moved"; and whether #559's entries were re-anchored⟩.
>
> **Red first.** Go, at the seed: `TestAProbeWaitsForTheSourcesFirstChunk` answered `Ready = hls: the HLS output failed … the probe's 3s bound ran out before its input arrived`, with the issue's own `the HLS probe failed … exited with status 1` log. E2E: run ⟨Task 2 run id⟩, the new test answered ⟨the 502 line⟩ on the seed's relay.
>
> **Break-checks:** ⟨BC1-BC6 and FE-BC, one line each: the wrong edit and the red line⟩.
>
> **Tests changed:** `TestDeathsAfterTheFirstSegmentRestartUntilTheThirdWithinAMinute` gains `feedRing` (its ring now advances, as a live channel's does; assertions unchanged; passes at the seed with the line too). `TestTheEntryWaitsCoverTheLongestTargetDuration` pins ReadyWait at 58 s and PlaylistWait at 43 s (was 43 s for both). The two frontend entry-timeout pins (`FloatingVideo.test.jsx`'s `uses the live HLS config`, `FloatingVideoUtils.test.js`'s `bounds the entry timeout by the relay and by nginx`) compare against the 58 s ready wait, not the 43 s playlist wait, and the literal-mirror test pins 58000 too.
>
> **Coverage (R21).** No raise: O = 0 (`relay/hls/feed.go` 0, `relay/hls/pipeline.go` 0, `relay/httpapi/hls.go` 0 by the start-line rule in every round); the floor is unchanged at 705. Census, ⟨N⟩ rounds in order: ⟨`this run missing=` per round with run ids⟩; max ⟨m⟩ ≤ 705.
>
> **Ledger:** `hls-cold-probe-502` → fixed.
>
> Closes #560.
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

## Appendix extraction

Each appendix below is one fenced `diff` block, byte-exact output of `git diff a9d6cee3 -- <paths>` from the planner's prototype (`git add -N` for the new test file), with only `fixed_in: 999999` replaced by `fixed_in: ⟨PR⟩` in F. To extract appendix X to a file:

```bash
PLAN=docs/superpowers/plans/2026-09-30-fix-560-cold-hls-probe.md
python3 - "$PLAN" X > /tmp/560-X.diff <<'PY'
import sys, re
text = open(sys.argv[1], encoding="utf-8").read()
section = text.split(f"\n## Appendix {sys.argv[2]} ", 1)[1]
body = section.split("\n```diff\n", 1)[1].split("\n```\n", 1)[0]
sys.stdout.write(body + "\n")
PY
git apply --check /tmp/560-X.diff && git apply /tmp/560-X.diff
```

The planner extracted all six this way from the committed plan and ran `git apply --check` on each against a clean seed tree; all six pass.

## Appendix A — the Go change and its tests (`relay/`)

```diff
diff --git a/relay/hls/cold_probe_test.go b/relay/hls/cold_probe_test.go
new file mode 100644
index 00000000..c071a4a2
--- /dev/null
+++ b/relay/hls/cold_probe_test.go
@@ -0,0 +1,135 @@
+package hls
+
+import (
+	"context"
+	"errors"
+	"path/filepath"
+	"strings"
+	"sync/atomic"
+	"testing"
+	"time"
+
+	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
+)
+
+// Issue #560: a probe's bound is a bound on analysis, never on the source's
+// start. These tests run a pipeline over a ring that is EMPTY when it starts,
+// as a cold channel's is: the pipeline starts at the entry's attach, and the
+// source publishes its first chunk only later (about 6 s on the FFmpeg stream
+// profile, whose ffmpeg analyses its own input first).
+
+// coldHarness is a harness whose ring holds nothing yet.
+func coldHarness(t *testing.T) *standInHarness {
+	return &standInHarness{t: t, src: newTestSource(), logs: &logBuffer{}, spawnLog: filepath.Join(t.TempDir(), "spawns")}
+}
+
+// eofProbe is what ffprobe does on pipe:0: it reads its input to the end, and
+// with no input at all fails "pipe:0: End of file", exit 1. Otherwise it
+// answers the probe JSON in path. spawned counts its spawns.
+func eofProbe(path string, spawned *atomic.Int32) func(int) (string, []string) {
+	return func(int) (string, []string) {
+		spawned.Add(1)
+		return "sh", []string{"-c", `n=$(wc -c); if [ "$n" -eq 0 ]; then echo "pipe:0: End of file" >&2; exit 1; fi; cat "$1"`, "sh", path}
+	}
+}
+
+// A first chunk later than the quick probe's whole bound is waited for, and
+// the output becomes ready.
+func TestAProbeWaitsForTheSourcesFirstChunk(t *testing.T) {
+	h := coldHarness(t)
+	probe := file(t, "probe.json", []byte(probeVideoOnly))
+	video := file(t, "v.mp4", videoStream(0, 2, 50))
+	var spawned atomic.Int32
+	p := h.startWith(probeVideoOnly, func(c *Config) {
+		c.ProbeCommand = eofProbe(probe, &spawned)
+	}, func(Spawn) []string {
+		return []string{"--fd-file", relaytest.FDFileArg(1, video), "--wait-stdin-eof"}
+	})
+	late := QuickProbe.Analyze + 500*time.Millisecond
+	time.Sleep(late)
+	// More than QuickProbe.Bytes, so the probe ends on bytes at once.
+	for written := 0; written <= QuickProbe.Bytes; written += testChunk {
+		h.src.write(t, chunkOf('a'))
+	}
+	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
+	defer cancel()
+	if err := p.Ready(ctx); err != nil {
+		t.Fatalf("Ready = %v with the first chunk %v after the start: the probe's %v bound ran out before its input arrived\n%s",
+			err, late, QuickProbe.Analyze, h.logs.String())
+	}
+}
+
+// A source that never sends a byte fails the output once SourceStartWait has
+// passed, and never before it, with no probe spawned.
+func TestASourceThatSendsNothingFailsTheOutputAfterTheStartWait(t *testing.T) {
+	h := coldHarness(t)
+	probe := file(t, "probe.json", []byte(probeVideoOnly))
+	var spawned atomic.Int32
+	const wait = 400 * time.Millisecond
+	started := time.Now()
+	p := h.startWith(probeVideoOnly, func(c *Config) {
+		c.SourceStartWait = wait
+		c.ProbeCommand = eofProbe(probe, &spawned)
+	}, func(Spawn) []string { return nil })
+	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
+	defer cancel()
+	err := p.Ready(ctx)
+	elapsed := time.Since(started)
+	if !errors.Is(err, ErrFailed) {
+		t.Fatalf("Ready = %v after %v, want ErrFailed: a source that never sent a byte held the pipeline past SourceStartWait\n%s", err, elapsed, h.logs.String())
+	}
+	if elapsed < wait {
+		t.Fatalf("the output failed %v after the start, before SourceStartWait (%v)", elapsed, wait)
+	}
+	if n := spawned.Load(); n != 0 {
+		t.Fatalf("%d probe(s) spawned with no input: the wait did not precede the spawn", n)
+	}
+	if logs := h.logs.String(); !strings.Contains(logs, "sent no input within 400ms") {
+		t.Fatalf("the failure does not say the source sent nothing:\n%s", logs)
+	}
+	waitDone(t, p, 5*time.Second)
+}
+
+// A ring that closes before its first chunk is a stop, as one that closes
+// under a probe is (R40): the channel is ending.
+func TestARingThatClosesBeforeItsFirstChunkIsAStop(t *testing.T) {
+	h := coldHarness(t)
+	probe := file(t, "probe.json", []byte(probeVideoOnly))
+	var spawned atomic.Int32
+	p := h.startWith(probeVideoOnly, func(c *Config) {
+		c.ProbeCommand = eofProbe(probe, &spawned)
+	}, func(Spawn) []string { return nil })
+	time.Sleep(200 * time.Millisecond)
+	h.src.ring.Close()
+	waitDone(t, p, 5*time.Second)
+	if err := p.Err(); err != nil {
+		t.Fatalf("Err after the ring closed before its first chunk = %v, want nil: the channel is ending\n%s", err, h.logs.String())
+	}
+	if n := spawned.Load(); n != 0 || strings.Contains(h.logs.String(), "level=ERROR") {
+		t.Fatalf("a ring that closed before its first chunk spawned %d probe(s) or logged an error:\n%s", n, h.logs.String())
+	}
+}
+
+// A stop while the pipeline waits for its first chunk ends it at once, as a
+// stop, however long SourceStartWait is.
+func TestAStopWhileWaitingForTheFirstChunkIsAStop(t *testing.T) {
+	h := coldHarness(t)
+	probe := file(t, "probe.json", []byte(probeVideoOnly))
+	var spawned atomic.Int32
+	p := h.startWith(probeVideoOnly, func(c *Config) {
+		c.SourceStartWait = time.Minute
+		c.ProbeCommand = eofProbe(probe, &spawned)
+	}, func(Spawn) []string { return nil })
+	time.Sleep(200 * time.Millisecond)
+	stopped := time.Now()
+	p.Stop()
+	if took := time.Since(stopped); took > 2*time.Second {
+		t.Fatalf("Stop took %v: the wait for the first chunk did not end with the pipeline's context", took)
+	}
+	if err := p.Err(); err != nil {
+		t.Fatalf("Err after a Stop during the wait = %v, want nil: a stop is not a failure\n%s", err, h.logs.String())
+	}
+	if n := spawned.Load(); n != 0 || strings.Contains(h.logs.String(), "level=ERROR") {
+		t.Fatalf("a stop during the wait spawned %d probe(s) or logged an error:\n%s", n, h.logs.String())
+	}
+}
diff --git a/relay/hls/feed.go b/relay/hls/feed.go
index 3d0d9207..79196c32 100644
--- a/relay/hls/feed.go
+++ b/relay/hls/feed.go
@@ -3,6 +3,7 @@ package hls
 import (
 	"context"
 	"errors"
+	"fmt"
 	"io"
 	"time"
 
@@ -103,6 +104,33 @@ func feed(ctx context.Context, src Source, start uint64, w io.Writer, limit int,
 	}
 }
 
+// awaitInput waits until the ring holds a chunk past start, the ring closes,
+// ctx ends, or within passes (issue #560). A probe runs it before spawning
+// ffprobe, so the probe's own bound measures analysis and never the source's
+// start: on a cold channel the pipeline starts before the ring holds a byte.
+// A ring that closes is feedClosed and a context that ends is feedStopped, as
+// feed reports them; within passing is feedStopped with an error of its own.
+//
+// It loops because Wait answers nil when Close wakes it and ErrClosed only on
+// the next call, exactly as feed's Read-then-Wait loop meets it.
+func awaitInput(ctx context.Context, ring *buffer.Ring, start uint64, within time.Duration) (feedResult, error) {
+	wctx, cancel := context.WithTimeout(ctx, within)
+	defer cancel()
+	for ring.Head() <= start {
+		err := ring.Wait(wctx, start)
+		switch {
+		case err == nil:
+			continue
+		case errors.Is(err, buffer.ErrClosed):
+			return feedResult{end: feedClosed}, errors.New("hls: the channel's ring closed before any input arrived")
+		case ctx.Err() != nil:
+			return feedResult{end: feedStopped}, ctx.Err()
+		}
+		return feedResult{end: feedStopped}, fmt.Errorf("hls: the channel's source sent no input within %v, so the probe never ran", within)
+	}
+	return feedResult{}, nil
+}
+
 // arrival is the PDT anchor's clock: the ring's arrival time for a chunk,
 // or now when the chunk has already left the ring.
 func arrival(ring *buffer.Ring, index uint64, now func() time.Time) time.Time {
diff --git a/relay/hls/pipeline.go b/relay/hls/pipeline.go
index 7fe229a7..60284ea3 100644
--- a/relay/hls/pipeline.go
+++ b/relay/hls/pipeline.go
@@ -60,8 +60,9 @@ func StartupStall(target int) time.Duration {
 // target seconds (ruling R42): the stall timeout max(10 s, 5 x target), and
 // the allowance before a generation's first fragment, max(StartupStallFactor x
 // StallTimeout, the stall timeout) -- 30 s at every target from 2 to 6 (ruling
-// R58), which is what keeps the entry's waits at 43 s, under nginx's 60 s
-// read timeout on /hls/. The wait before a first fragment is an encoder's cold
+// R58), which is what keeps a media playlist's wait at 43 s, under nginx's 60 s
+// read timeout on /hls/, and the entry's at 58 s with SourceStartWait (issue
+// #560). The wait before a first fragment is an encoder's cold
 // start, whose GOP is 2 s in every mode, or a copy's first closed GOP, at most
 // 2 x K = 12 s of media, so the allowance does not need to grow with the
 // target: three times max(10 s, 5 x 6) would be 90 s.
@@ -70,6 +71,16 @@ func stallLimits(target int) (stall, startup time.Duration) {
 	return stall, max(StartupStallFactor*StallTimeout, stall)
 }
 
+// SourceStartWait bounds how long a probe waits for the first chunk past where
+// its generation starts, before ffprobe is spawned and the probe's own bound
+// begins (issue #560). A cold channel's pipeline starts at the entry's attach,
+// before its ring holds a byte, and the FFmpeg stream profile publishes its
+// first chunk about 6 s later, after its own ffmpeg's input analysis. 15 s is
+// 2.5 times that measured 6 s, and the Proxy source's 5 s connect bound plus
+// one 255,868-byte chunk at 205 kb/s. A source that sends nothing for longer
+// fails the output, as a failed probe does.
+const SourceStartWait = 15 * time.Second
+
 // stopJoinWait bounds Stop's wait for the pipeline to wind down: the exit
 // grace, the reap budget and a margin.
 const stopJoinWait = GenerationExitGrace + ffmpeg.KillWait + 2*time.Second
@@ -124,6 +135,8 @@ type Config struct {
 	// first video fragment (R55); zero means StartupStallFactor x the stall
 	// timeout in force.
 	StartupStallTimeout time.Duration
+	// SourceStartWait overrides the package's SourceStartWait, for tests.
+	SourceStartWait time.Duration
 	// Command maps a Spawn to the command and argv actually run. Nil runs
 	// FFmpeg with the built argv; the stand-in tests replace it.
 	Command func(Spawn) (string, []string)
@@ -661,6 +674,15 @@ func needsFullProbe(p Probe, fed feedResult, mode Mode) bool {
 // probe runs one ffprobe over the bytes the generation will start from,
 // within bound.
 func (p *Pipeline) probe(ctx context.Context, gen int, start uint64, bound ProbeBound) (Probe, feedResult, error) {
+	// The bound is on analysis, not on the source's start (issue #560): no
+	// ffprobe, and no clock, until the generation's first chunk exists.
+	wait := p.cfg.SourceStartWait
+	if wait <= 0 {
+		wait = SourceStartWait
+	}
+	if fed, err := awaitInput(ctx, p.cfg.Source.Ring(), start, wait); err != nil {
+		return Probe{}, fed, err
+	}
 	command, argv := p.cfg.FFprobe, ProbeArgvFor(bound, p.cfg.Mode)
 	if command == "" {
 		command = "ffprobe"
diff --git a/relay/hls/pipeline_test.go b/relay/hls/pipeline_test.go
index dbf51e79..61123446 100644
--- a/relay/hls/pipeline_test.go
+++ b/relay/hls/pipeline_test.go
@@ -342,6 +342,9 @@ func TestEOFMidFragmentSegmentsOnlyTheWholeFragments(t *testing.T) {
 // discontinuity; a third such death within 60 s is a total failure.
 func TestDeathsAfterTheFirstSegmentRestartUntilTheThirdWithinAMinute(t *testing.T) {
 	h := newHarness(t)
+	// A live channel's ring advances: each restart at the head probes the
+	// chunks after it, and waits for them (issue #560).
+	feedRing(t, h)
 	stream := file(t, "v.mp4", videoStream(0, 2, 50))
 	p := h.start(probeVideoOnly, nil, func(Spawn) []string {
 		return []string{"--fd-file", relaytest.FDFileArg(1, stream)}
diff --git a/relay/httpapi/hls.go b/relay/httpapi/hls.go
index 8b0637ea..88a8a50b 100644
--- a/relay/httpapi/hls.go
+++ b/relay/httpapi/hls.go
@@ -42,10 +42,17 @@ const readyWaitMargin = 2 * time.Second
 // stall allowance a generation gets before its first fragment -- 30 s at every
 // target duration up to the longest, 6 (R55, R58) -- plus a margin: 43 s. A 503
 // on the multivariant fails an AVPlayer item outright, so this must not be
-// shorter. nginx's proxy_read_timeout on /hls/ is 60 s, above both.
+// shorter.
+//
+// The entry's wait also covers the source's start (issue #560): on a cold
+// channel the probe first waits up to hls.SourceStartWait (15 s) for the
+// ring's first chunk, so the entry waits 58 s, under nginx's 300 s
+// proxy_read_timeout on the tune locations. A media playlist is requested only
+// after its multivariant, once the source has started, so its wait keeps 43 s,
+// under nginx's 60 s on /hls/.
 var (
-	defaultReadyWait    = hls.QuickProbe.Analyze + hls.FullProbe.Analyze + hls.StartupStall(hls.MaxTargetDuration) + readyWaitMargin
-	defaultPlaylistWait = defaultReadyWait
+	defaultPlaylistWait = hls.QuickProbe.Analyze + hls.FullProbe.Analyze + hls.StartupStall(hls.MaxTargetDuration) + readyWaitMargin
+	defaultReadyWait    = hls.SourceStartWait + defaultPlaylistWait
 )
 
 const (
diff --git a/relay/httpapi/hls_automatic_test.go b/relay/httpapi/hls_automatic_test.go
index 4fd21e73..b38dc6cf 100644
--- a/relay/httpapi/hls_automatic_test.go
+++ b/relay/httpapi/hls_automatic_test.go
@@ -220,9 +220,11 @@ func TestAnAutomaticSessionIsSilentOnlyAfterTwoOfItsTargetDurations(t *testing.T
 
 // The entry's waits cover the longest target's cold start, derived and not
 // hand-added: quick probe + re-probe + the startup allowance at target 6 + the
-// margin, 43 s, under nginx's 60 s.
+// margin, 43 s, under nginx's 60 s; the entry's adds the source's start
+// (issue #560), 58 s.
 func TestTheEntryWaitsCoverTheLongestTargetDuration(t *testing.T) {
 	floor := hls.QuickProbe.Analyze + hls.FullProbe.Analyze + hls.StartupStall(hls.MaxTargetDuration)
+	want := map[string]time.Duration{"ReadyWait": 58 * time.Second, "PlaylistWait": 43 * time.Second}
 	for name, got := range map[string]time.Duration{
 		"ReadyWait":    HLSDeps{}.readyWait(),
 		"PlaylistWait": HLSDeps{}.playlistWait(),
@@ -233,8 +235,8 @@ func TestTheEntryWaitsCoverTheLongestTargetDuration(t *testing.T) {
 		if got >= 60*time.Second {
 			t.Errorf("the default %s is %v: readyWait %v is not under nginx's 60 s", name, got, got)
 		}
-		if got != 43*time.Second {
-			t.Errorf("the default %s is %v, want 43s", name, got)
+		if got != want[name] {
+			t.Errorf("the default %s is %v, want %v", name, got, want[name])
 		}
 	}
 }
diff --git a/relay/httpapi/hls_test.go b/relay/httpapi/hls_test.go
index 1ffc2144..8146a5f2 100644
--- a/relay/httpapi/hls_test.go
+++ b/relay/httpapi/hls_test.go
@@ -1211,6 +1211,23 @@ func TestTheEntryWaitsOutALegitimateColdStart(t *testing.T) {
 	}
 }
 
+// Issue #560: on a cold channel the probe first waits up to hls.SourceStartWait
+// for the ring's first chunk, so the entry's wait covers the source's start as
+// well as a cold start, and stays under nginx's 300 s proxy_read_timeout on the
+// tune locations. A media playlist is requested only after its multivariant,
+// once the source has started, so its wait does not carry the term.
+func TestTheEntryWaitAlsoCoversTheSourcesStart(t *testing.T) {
+	cold := hls.QuickProbe.Analyze + hls.FullProbe.Analyze + hls.StartupStall(hls.MaxTargetDuration)
+	got := HLSDeps{}.readyWait()
+	if floor := hls.SourceStartWait + cold; got < floor {
+		t.Errorf("the default ReadyWait is %v, below the source's start plus a cold start, %v (SourceStartWait %v + %v)",
+			got, floor, hls.SourceStartWait, cold)
+	}
+	if got >= 300*time.Second {
+		t.Errorf("the default ReadyWait is %v, not under nginx's 300 s proxy_read_timeout on the tune locations", got)
+	}
+}
+
 // enterAsync starts an HLS entry on a goroutine and returns what it answered.
 type entryAnswer struct {
 	status int
```

## Appendix B — the frontend mirror (`frontend/`)

```diff
diff --git a/frontend/src/components/__tests__/FloatingVideo.test.jsx b/frontend/src/components/__tests__/FloatingVideo.test.jsx
index 88f8a749..19d4ad15 100644
--- a/frontend/src/components/__tests__/FloatingVideo.test.jsx
+++ b/frontend/src/components/__tests__/FloatingVideo.test.jsx
@@ -10,7 +10,7 @@ import FloatingVideo from '../FloatingVideo';
 import {
   HLS_LEAVE_WAIT_MS,
   HLS_RELAY_TUNE_BUDGET_MS,
-  HLS_RELAY_WAIT_MS,
+  HLS_RELAY_READY_WAIT_MS,
 } from '../../utils/components/FloatingVideoUtils.js';
 import useVideoStore from '../../store/useVideoStore';
 
@@ -672,7 +672,7 @@ describe('FloatingVideo', () => {
       expect(
         capturedHlsConfig.manifestLoadPolicy?.default?.maxLoadTimeMs ?? 0,
         'the entry timeout must cover the relay tune budget plus its ready wait'
-      ).toBeGreaterThan(HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS);
+      ).toBeGreaterThan(HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_READY_WAIT_MS);
       expect(capturedHlsConfig.backBufferLength).toBe(120);
     });
 
diff --git a/frontend/src/utils/components/FloatingVideoUtils.js b/frontend/src/utils/components/FloatingVideoUtils.js
index c6842e5d..b4252db7 100644
--- a/frontend/src/utils/components/FloatingVideoUtils.js
+++ b/frontend/src/utils/components/FloatingVideoUtils.js
@@ -13,10 +13,13 @@ export const buildLiveStreamUrl = (path) => {
   return `${path}?${params.toString()}`;
 };
 
-// The relay's entry and first-playlist waits (relay/httpapi/hls.go:47-48,
-// defaultReadyWait = defaultPlaylistWait = QuickProbe 3 s + FullProbe 8 s +
-// 3 x StallTimeout 10 s + 2 s, ruling R57).
+// The relay's first-playlist wait (relay/httpapi/hls.go, defaultPlaylistWait =
+// QuickProbe 3 s + FullProbe 8 s + 3 x StallTimeout 10 s + 2 s, ruling R57).
 export const HLS_RELAY_WAIT_MS = 43_000;
+// The relay's entry wait (defaultReadyWait): the playlist wait plus the 15 s a
+// cold channel's source gets to publish its first chunk before the probe runs
+// (hls.SourceStartWait, issue #560).
+export const HLS_RELAY_READY_WAIT_MS = 58_000;
 // The next-source budget the relay spends before the entry's ready wait starts
 // (relay/httpapi/stream.go:193, tuneBudget = 2 x (2 s + 5 s) + 100 ms).
 export const HLS_RELAY_TUNE_BUDGET_MS = 14_100;
@@ -24,7 +27,7 @@ export const HLS_RELAY_TUNE_BUDGET_MS = 14_100;
 // under nginx's 300 s proxy_read_timeout on ^~ /proxy/ts/stream/
 // (docker/nginx.conf:350).
 export const HLS_ENTRY_TIMEOUT_MS =
-  HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS + 7_900; // 65 000
+  HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_READY_WAIT_MS + 7_900; // 80 000
 // The media-playlist timeout: above the relay's 43 s first-segment wait, under
 // nginx's 60 s proxy_read_timeout on ^~ /hls/ (docker/nginx.conf:488).
 export const HLS_PLAYLIST_TIMEOUT_MS = 50_000;
diff --git a/frontend/src/utils/components/__tests__/FloatingVideoUtils.test.js b/frontend/src/utils/components/__tests__/FloatingVideoUtils.test.js
index c8467017..1d34d8ca 100644
--- a/frontend/src/utils/components/__tests__/FloatingVideoUtils.test.js
+++ b/frontend/src/utils/components/__tests__/FloatingVideoUtils.test.js
@@ -16,6 +16,7 @@ import {
   buildLiveHlsConfig,
   getHlsLivePlayerErrorMessage,
   HLS_RELAY_WAIT_MS,
+  HLS_RELAY_READY_WAIT_MS,
   HLS_RELAY_TUNE_BUDGET_MS,
 } from '../FloatingVideoUtils';
 
@@ -568,7 +569,7 @@ describe('FloatingVideoUtils: live channels over HLS', () => {
     it('bounds the entry timeout by the relay and by nginx', () => {
       const entry = config.manifestLoadPolicy.default;
       expect(entry.maxLoadTimeMs).toBeGreaterThan(
-        HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_WAIT_MS
+        HLS_RELAY_TUNE_BUDGET_MS + HLS_RELAY_READY_WAIT_MS
       );
       expect(entry.maxLoadTimeMs).toBeLessThan(300_000);
       expect(entry.timeoutRetry).toBeNull();
@@ -587,6 +588,7 @@ describe('FloatingVideoUtils: live channels over HLS', () => {
 
     it('mirrors the relay bounds as literals', () => {
       expect(HLS_RELAY_WAIT_MS).toBe(43000);
+      expect(HLS_RELAY_READY_WAIT_MS).toBe(58000);
       expect(HLS_RELAY_TUNE_BUDGET_MS).toBe(14100);
     });
 
```

## Appendix C — the E2E, its harness timeout, a stale comment and its COVERAGE.md row (`e2e/`)

```diff
diff --git a/e2e/COVERAGE.md b/e2e/COVERAGE.md
index 43fa9d22..f2d5c890 100644
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -208,6 +208,7 @@ resolve (see the G8/G10 Gap rows).
 | Sources | **Gap:** the bulk-path fuzzy "no match" characterization test (would have been test 8) was implemented, its own assertions and the file's typecheck passed, and it was cut before shipping — see `epg-matching.spec.ts`'s header. Mechanism: `_active_epg_fuzzy_queryset` admits every active source's `EPGData` with no scoping to the test's own source; two `seed.channel()`/`seed.generatedName('epg')`-shaped names (worker/run/test-id digits, stripped to nothing by `normalize_name`) share enough character-level structure to land inside the bulk path's `[50, 80)` ML band by coincidence — measured at fuzzy 56.91 against a leftover row from an unrelated `epg-ingest.spec.ts` run — triggering `get_sentence_transformer()` and a real ~88 MB model download, then matching the two unrelated generated names via the ML "desperate last resort" branch at cosine 0.91 (the aggressive-ML finding, folded in here rather than filed separately). The test's own ws-based settle signal also resolved before the ML-delayed match actually committed — a second, independent defect in the test design, not just in the pair choice. What a future owner needs: a fixture-scoped way to deactivate other sources during the test, or a dedicated single-worker project. G14's own shipped tests 6, 7, 10, 11, 12 and 13 each leave behind an active upstream EPG source with a generated-shape `EPGData` name of exactly this kind — six more candidates per run for the next test that lands in this band by coincidence, not just the one leftover row measured above | G14 | todo |
 | Upstream | Phase 4a codec fixtures: six named looping TS assets (`mpeg2-576i-mp2`, `h264-1080i-aac-ac3`, `hevc-aac`, `h264-gop10-aac`, `h264-eac3`, `h264-noaudio`) beside the default `loop`, and a scenario channel's optional `asset` field choosing one. Each fixture's streams, PIDs and keyframe spacing are a `CONTRACT.md` guarantee, checked by `scripts/make-asset.sh` at image build; the field, the routing and the name list are covered by `e2e-upstream`'s vitest suite. No E2E spec consumes them yet: 4a-1b onwards does | 4a-0 | done |
 | Streaming | Live HLS entry (Phase 4a-1b): an `hls` tune answers a multivariant playlist, not bytes, on all three entry forms — `/proxy/ts/stream/<uuid>?output_format=hls`, `/live/<u>/<p>/<id>.m3u8` and the bare `/<u>/<p>/<id>.m3u8` — with `application/vnd.apple.mpegurl`, `Cache-Control: no-store` and every URI under `/hls/<token>/`; `player_api.php` advertises `m3u8`, `get.php?output=m3u8` emits `.m3u8` URLs, and `/api/mino/capabilities/` answers anonymously. A Redirect-profile channel is served over HLS through the relay (spec D13). `tests/streaming/hls-entry.spec.ts` | 4a-1b | done |
+| Streaming | A cold HLS tune on the built-in `ffmpeg` stream profile, the stock default, answers the multivariant and publishes media segments (issue #560): its ffmpeg analyses its own input first, so the channel's ring publishes its first chunk about 6 s after the tune, and the quick probe's 3 s bound used to start before it and answer 502. The channel is fresh, so nothing warmed it; every other HLS spec seeds Proxy, whose first chunk lands in about 1.5 s. The probe's wait for its input, its 15 s bound, a ring that closes and a stop during it are pinned in Go (`relay/hls/cold_probe_test.go`). `tests/streaming/hls-entry.spec.ts` | 4a-1b | done |
 | Streaming | Live HLS playlists per codec fixture: the audio groups and `CODECS` of the multivariant on `h264-eac3` (three groups, `mp4a.40.2`, `ac-3`, `ec-3`), `h264-noaudio` (one `aac` group, relay-synthesised silence), `mpeg2-576i-mp2` (720×576, `FRAME-RATE=50.000`, `aac` only) and `h264-1080i-aac-ac3` (1920×1080 at 50, `aac` and `ac3`); a media playlist conforms (`VERSION:7`, `TARGETDURATION:2`, `INDEPENDENT-SEGMENTS`, PDT on every segment, at least 6 listed, the media sequence advancing across reloads), and an init segment and two media segments parse in TypeScript with the durations their `EXTINF` claims and no edit list. `tests/streaming/hls-playlists.spec.ts` | 4a-1b | done |
 | Streaming | Live HLS sessions: a tampered token, a left session and a client stopped through `/proxy/ts/stop_client/` are refused 403; a session on a stopped channel is refused 410 once and 403 after; `/proxy/ts/status/<uuid>` lists an `hls` client that disappears at once on `DELETE /hls/<token>` beside a TS client that stays, with no wait for the idle timeout. `tests/streaming/hls-sessions.spec.ts` | 4a-1b | done |
 | Streaming | Live HLS failover: an upstream fault on `h264-1080i-aac-ac3` switches the channel to an alternate carrying `mpeg2-576i-mp2`, and the next media playlist carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` with the media sequence continuing and the multivariant's `CODECS` unchanged. `tests/streaming/hls-failover.spec.ts` | 4a-1b | done |
diff --git a/e2e/fixtures/hls.ts b/e2e/fixtures/hls.ts
index b6801f85..b902fa28 100644
--- a/e2e/fixtures/hls.ts
+++ b/e2e/fixtures/hls.ts
@@ -357,11 +357,22 @@ export interface HlsEntry {
 /**
  * An HLS tune: `path` is any of the three entry forms. Requires a 200 and
  * returns the parsed multivariant and its session token. A 503 (the relay's
- * own 20 s wait for the encoder's init segments ran out) is an error here,
+ * own 58 s wait for the encoder's init segments ran out) is an error here,
  * not retried: a viewer's first tune failing is a finding, not noise.
  */
+/**
+ * The entry request's own timeout, derived as the browser player's is
+ * (frontend/src/utils/components/FloatingVideoUtils.js, HLS_ENTRY_TIMEOUT_MS):
+ * the relay's next-source budget (14.1 s, relay/httpapi/stream.go's tuneBudget)
+ * plus its entry wait (58 s: hls.SourceStartWait 15 s + the 43 s cold start,
+ * issue #560) plus a 7.9 s margin, so a slow entry fails as the relay's own
+ * 503 rather than as a request timeout. Under nginx's 300 s on the tune
+ * locations.
+ */
+const ENTRY_TIMEOUT_MS = 14_100 + 58_000 + 7_900;
+
 export async function enterHls(request: APIRequestContext, path: string): Promise<HlsEntry> {
-  const response = await request.get(path, { timeout: 60_000 });
+  const response = await request.get(path, { timeout: ENTRY_TIMEOUT_MS });
   const text = await response.text();
   if (response.status() !== 200) {
     throw new Error(`an HLS entry at ${path} answered ${response.status()}, want 200: ${text.slice(0, 300)}`);
diff --git a/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts b/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
index 436343fa..8f39375d 100644
--- a/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
+++ b/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
@@ -650,9 +650,10 @@ test(
         `location "${block.header}" does not set proxy_http_version 1.1:\n${body}`
       ).toBe(true);
 
-      // Above the relay's own 43 s waits (R57) (the entry's init wait, a media
-      // playlist's first-segment wait), and the byte-path locations' own
-      // connect budget rather than the server block's inherited 75.
+      // Above the relay's 43 s wait for a media playlist's first segment
+      // (R57), the one long wait on /hls/ (the entry's 58 s wait is on the
+      // tune locations, at 300 s; issue #560), and the byte-path locations'
+      // own connect budget rather than the server block's inherited 75.
       expect(
         has(/^\s*proxy_read_timeout\s+60s\s*;/),
         `location "${block.header}" does not set proxy_read_timeout 60s:\n${body}`
diff --git a/e2e/tests/streaming/hls-entry.spec.ts b/e2e/tests/streaming/hls-entry.spec.ts
index 14253c0d..86cc8246 100644
--- a/e2e/tests/streaming/hls-entry.spec.ts
+++ b/e2e/tests/streaming/hls-entry.spec.ts
@@ -1,5 +1,5 @@
 import { test, expect, parseM3u, readChannelStatus, xcQuery } from '../../fixtures';
-import { MEDIA_SESSION_TOKEN_RE, enterHls, leaveHls } from '../../fixtures/hls';
+import { MEDIA_SESSION_TOKEN_RE, enterHls, leaveHls, waitForSegments } from '../../fixtures/hls';
 import { lockedProfile, stopChannels } from './helpers';
 
 /**
@@ -92,6 +92,39 @@ test(
   }
 );
 
+test(
+  'a cold hls tune on the built-in ffmpeg stream profile answers the multivariant',
+  { tag: '@contract' },
+  async ({ upstream, seed, api, request }) => {
+    // Issue #560. The built-in `ffmpeg` profile is the stock default, and its
+    // ffmpeg analyses its own input before it writes a byte: measured, the
+    // ring's first chunk lands about 6 s after a cold tune at `rate: 1`, past
+    // the quick probe's 3 s bound, which used to start at the entry's attach
+    // and answer 502. Every other HLS spec seeds Proxy, whose first chunk is
+    // about 1.5 s. The channel is fresh, so nothing has warmed it.
+    const scenario = await upstream.scenario({
+      channels: [{ id: 1, name: 'HLS Cold FFmpeg', tvgId: 'hls-cold-ffmpeg.e2e', logo: null, asset: 'mpeg2-576i-mp2' }],
+      rate: 1,
+    });
+    const ffmpeg = await lockedProfile(api, 'ffmpeg');
+    const { channel } = await seed.upstreamChannel(scenario, {
+      channelIds: [1],
+      streamProfileId: ffmpeg.id,
+    });
+    let token: string | undefined;
+    try {
+      const entry = await enterHls(request, `/proxy/ts/stream/${channel.uuid}?output_format=hls`);
+      token = entry.token;
+      expect(entry.multivariant.text).toContain('#EXT-X-STREAM-INF');
+      const video = await waitForSegments(request, entry.token, 'video', 1, 60_000);
+      expect(video.segments.length, 'the cold channel publishes media segments').toBeGreaterThanOrEqual(1);
+    } finally {
+      if (token) await leaveHls(request, token);
+      await stopChannels(api, channel.uuid);
+    }
+  }
+);
+
 test(
   'the Xtream API advertises m3u8 and get.php emits .m3u8 stream URLs',
   { tag: '@contract' },
```

## Appendix D — the spec amendment

```diff
diff --git a/docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md b/docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md
index 79628d23..2f332d9b 100644
--- a/docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md
+++ b/docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md
@@ -213,9 +213,9 @@ exports `LIBVA_DRIVERS_PATH`. The compose files carry `/dev/dri` only as a comme
 | **D4** | **An opaque media-session token** (§ The media-session token; R22): `v1.<session id>.<MAC>`, where the session id is 128 random bits. The relay mints and verifies it. The channel, client id, user and HLS profile live in the relay's **session table**, never in the token. It is valid exactly while its session is: MAC verifies, **and** the session id is in the table, **and** the session has not ended. A session ends on an explicit leave, on an admin stop or stream-limit termination, on idle departure plus the resume window, or on relay restart. There is **no absolute expiry**, so a continuously watched session is never cut off. It is not bound to an IP address. | A channel UUID in the token would hand every Xtream user the anonymous live capability (finding 2; `authorize.py:77-84`), which Xtream surfaces never expose today. The relay needs the session table anyway, for presence (D5), so holding the claims there costs nothing, and every revocation is simply a table delete: no revoked set. The session id is distinct from the client id, because the client id appears in stats and events, and the token must not. The MAC rejects a forged id before any table lookup and keeps the check constant-time. There is no IP binding because AirPlay hands a URL to an Apple TV that fetches from a different address, and phones roam between access points. |
 | **D5** | **An HLS viewer is a client in the channel's registry for exactly as long as its session is live.** It **arrives** when the multivariant is served (the `Attach` call, a `client_connect` event). It is **active** on every request carrying its token. It **leaves** when it calls `DELETE /hls/<token>` (the Mino app on zap and after the R11 countdown; the browser player on close or switch), or after the **idle timeout**, `max(12 s, 6 × TARGETDURATION)`, with no request in flight (§ Presence thresholds). Leaving emits `client_disconnect` with `duration` and `bytes_sent` and calls the release func. A departed (not left) session may **resume** within 300 s **if its channel is still running** (another viewer, or 4a-3's linger), with a new `client_connect`. When its channel stops, a session becomes **STOPPED**: its next request gets 410 and it is then removed (§ Presence). `output_format` is `hls`, so `/proxy/relay/channels`, `/proxy/ts/status/` and the stats page show it without change. Admin stop, and stream-limit termination, end the session. | M7 measured AVPlayer reloading every target duration (2 s) even while paused, so an idle timeout of six target durations (at least 12 s) cannot mistake a paused viewer for a departed one. The explicit leave is what makes a zap as fast as TS's connection close (finding 1). The idle timeout covers only clients that never call it: third-party apps, a killed app, a closed tab. The per-user stream limit needs no change, because it counts the relay's client list, which now includes HLS sessions (§ Presence says what a limit-1 user gets on zap). |
 | **D6** | **The relay owns packaging.** One ffmpeg per (channel, HLS profile) reads the channel's ring on stdin. It writes **one fragmented-MP4 stream per rendition on its own file descriptor**: video on fd 1, stereo AAC on fd 3, AC-3 on fd 4, E-AC-3 on fd 5, each `-movflags frag_keyframe+delay_moov+default_base_moof`. A new package, `relay/hls`, parses the boxes (stdlib `encoding/binary`), cuts segments, stores them, and renders every playlist. The segmenter accumulates video fragments until the 2 s grid is reached, and checks that each segment's first sample is a sync sample; it does not cut at every fragment. **Rejected:** ffmpeg's own `-f hls` muxer, and one muxed audio-plus-video stream. | M4 shows the shape works, with 2.000 s segments on every rendition. `-f hls` writes files the relay would have to watch (no inotify in the stdlib) and playlists it would have to rewrite: for tokens, for D10's discontinuities across processes, and for 4a-3's on-disk window. A muxed stream cannot carry two alternative audio codecs as HLS renditions. `buffer.Fragments` is not reused, because it is a cursor stream for one long response, and HLS needs random access by media sequence across aligned renditions (`hls.Store`). The spawn helper gains `ExtraFiles` (stdlib `os/exec`); `start()` (`relay/ffmpeg/spawn.go:113-197`) keeps `Setpgid` and `Pdeathsig`. Accumulating to the grid guards against stray non-IDR keyframes the encoder may emit (Q1). |
-| **D7** | **Playlists** (§ Playlists, exact tags). There is one video rendition and one audio group per audio codec: `aac` always; `ac3` when the source carries AC-3 or E-AC-3; `eac3` when it carries E-AC-3. Each group gets its own `EXT-X-STREAM-INF` on the same video playlist. `CODECS` is read from each rendition's **init segment** (`avcC`, `hvcC`, `esds`, `dac3` and `dec3` boxes). `EXT-X-PROGRAM-DATE-TIME` is written on **every** segment, derived from the ring's **arrival time** of the generation's first chunk plus media time (the known drift is § Risks). `TARGETDURATION` is 2 (transcode), with `INDEPENDENT-SEGMENTS`, `VERSION:7`, a media sequence that continues across generations, and `DISCONTINUITY-SEQUENCE`. The live-edge playlist lists 10 segments. A media playlist request **waits** for its rendition's first segment, bounded by 43 s (R57, amends R56), then answers 503 with `Retry-After: 1`. The multivariant waits for every first-generation init segment, bounded the same way. | Apple rules 2.3, 2.5-2.6, 7.4, 8.4, 8.11 and 9.11-9.12 (Appendix A). The 2 s target departs **deliberately** from Apple 7.5/7.6's 6 s target (a SHOULD): R8 prefers lower latency, and M4 measured about 7.3 s behind PDT at 2 s against about 24.5 s at 6 s. Codec strings read from init segments stay true in every mode, copy included. Arrival time rather than publish time keeps PDT honest while the encoder catches up the first generation's `JoinBehind` backlog. Holding a request until content exists is simpler for every player than an empty live playlist. |
+| **D7** | **Playlists** (§ Playlists, exact tags). There is one video rendition and one audio group per audio codec: `aac` always; `ac3` when the source carries AC-3 or E-AC-3; `eac3` when it carries E-AC-3. Each group gets its own `EXT-X-STREAM-INF` on the same video playlist. `CODECS` is read from each rendition's **init segment** (`avcC`, `hvcC`, `esds`, `dac3` and `dec3` boxes). `EXT-X-PROGRAM-DATE-TIME` is written on **every** segment, derived from the ring's **arrival time** of the generation's first chunk plus media time (the known drift is § Risks). `TARGETDURATION` is 2 (transcode), with `INDEPENDENT-SEGMENTS`, `VERSION:7`, a media sequence that continues across generations, and `DISCONTINUITY-SEQUENCE`. The live-edge playlist lists 10 segments. A media playlist request **waits** for its rendition's first segment, bounded by 43 s (R57, amends R56), then answers 503 with `Retry-After: 1`. The multivariant waits for every first-generation init segment, bounded by 58 s: the same 43 s plus the 15 s a cold channel's source gets to publish its first chunk (issue #560, R113). | Apple rules 2.3, 2.5-2.6, 7.4, 8.4, 8.11 and 9.11-9.12 (Appendix A). The 2 s target departs **deliberately** from Apple 7.5/7.6's 6 s target (a SHOULD): R8 prefers lower latency, and M4 measured about 7.3 s behind PDT at 2 s against about 24.5 s at 6 s. Codec strings read from init segments stay true in every mode, copy included. Arrival time rather than publish time keeps PDT honest while the encoder catches up the first generation's `JoinBehind` backlog. Holding a request until content exists is simpler for every player than an empty live playlist. |
 | **D8** | **The default re-encode** (§ Encoder argv). The source is decoded in software, and deinterlaced with `bwdif=mode=send_field:deint=interlaced` when the probe says it is interlaced (50i → 50p, Apple 1.14-1.15). **Output geometry and frame rate are fixed for the channel's run** at the first generation's probe: at most 1920×1080, never upscaled at the first generation, and `scale`/`pad`/`fps` enforce them on every later generation. Video is H.264 High@L4.2 at constant frame rate, with a forced IDR every 2.000 s and a bitrate from a table by output height. It is encoded with `h264_qsv` behind `hwupload`, or with `libx264 -preset veryfast -tune zerolatency` (D11). **Audio**, per R20 and Apple 2.3/2.6: stereo AAC 160 kb/s always. An AC-3 source track is copied. An E-AC-3 source track is copied **and** an AC-3 rendition is encoded from it at the source's layout (640 kb/s at 5.1, 192 kb/s at 2.0; § Encoder argv › Channel layouts), giving three audio renditions. Only **qualifying** audio streams are mapped (§ Encoder argv). **The rendition set is fixed at generation 0**, as geometry is, and every later generation fills every declared rendition (§ Encoder argv, rendition filling). A rendition with no source is filled with **relay-synthesised silence** (M8): canned silent frames, counted against the video segments' time spans, with no audio output in the ffmpeg argv at all. | ADR 0009 makes codec, field order and keyframe spacing Mino's decisions. Software decode plus `bwdif`'s `deint=interlaced` handles mixed progressive and interlaced content without a hardware filter chain whose behaviour on progressive frames is unknown (Q1). Encoding is the expensive half, and it is the half that goes to Quick Sync. Fixed output parameters are what ADR 0009 promised across a switch, and what keeps the multivariant true after one. A PMT-declared audio track with no packets would otherwise make ffmpeg fail every rendition (finding 7). Silence satisfies Apple 2.3 on a video-only source. It is synthesised by the relay because an ffmpeg `anullsrc` input never lets the generation exit on stdin EOF, and it is unpaced (M8). |
-| **D9** | **A probe precedes every generation, and reads from where that generation will start** (D10): the first generation from `JoinBehind` behind live, every later one from its boundary index. The probe is `ffprobe -show_streams -of json`, decoded with stdlib `encoding/json`, bounded to **3 s or 3,000,000 bytes** (`-analyzeduration 3000000 -probesize 3000000`; 3 MB is 3 s of an 8 Mb/s source, and a faster one ends on bytes first), with **one re-probe at 8 s or 5 MB only when the video has no width, height or `field_order`** (or, in *automatic* mode only, the 3 s window held fewer than 2 keyframes, R37) and the first probe's feed stopped for a reason more bytes would change (not at a boundary or the ring's close). The encoder analyses its own `pipe:0` input at the bound its generation's probe succeeded with (amended by R30). It decides interlacing (`field_order`), frame rate, geometry and the qualifying audio streams, and, in *automatic* mode, the copy decisions (D12). A probe that finds no video stream fails the HLS attach with 502, and the channel's TS clients are unaffected. `Channel.AttachOutput` holds `outMu` across a pipeline's start (`relay/channel/output.go:126-185`). The HLS attach therefore only registers its pipeline under `outMu`, and runs the probe (3 s, or 11 s with its re-probe) and the init wait (up to 43 s, R57 amending R56) **outside** it, so an fMP4 or Output Profile attach on the same channel never waits behind them. | Every later choice depends on these facts, and the relay is the only process that can see the bytes. Probing across a boundary would describe the old source's streams, and M3 shows how silently a stream mismatch fails (finding 6). The 3 s bound (R30): on an MPEG-TS pipe ffprobe reads to its `-analyzeduration` whatever it has found (mpegts is a no-header format), so the bound **is** the probe's share of the zap time and the failover gap. The 4a-1a plan review measured every decision on the 4a-0 fixtures identical to a full probe at 2.5-3 s and geometry lost at 1 s; the bound must exceed the GOP, which the re-probe covers when it does not. |
+| **D9** | **A probe precedes every generation, and reads from where that generation will start** (D10): the first generation from `JoinBehind` behind live, every later one from its boundary index. The probe is `ffprobe -show_streams -of json`, decoded with stdlib `encoding/json`, bounded to **3 s or 3,000,000 bytes** (`-analyzeduration 3000000 -probesize 3000000`; 3 MB is 3 s of an 8 Mb/s source, and a faster one ends on bytes first), with **one re-probe at 8 s or 5 MB only when the video has no width, height or `field_order`** (or, in *automatic* mode only, the 3 s window held fewer than 2 keyframes, R37) and the first probe's feed stopped for a reason more bytes would change (not at a boundary or the ring's close). The bound starts at the generation's first chunk, never before it: the probe first waits for a chunk past where its generation starts, up to 15 s (`hls.SourceStartWait`; issue #560, R113), and only then spawns ffprobe. The encoder analyses its own `pipe:0` input at the bound its generation's probe succeeded with (amended by R30). It decides interlacing (`field_order`), frame rate, geometry and the qualifying audio streams, and, in *automatic* mode, the copy decisions (D12). A probe that finds no video stream fails the HLS attach with 502, and the channel's TS clients are unaffected. `Channel.AttachOutput` holds `outMu` across a pipeline's start (`relay/channel/output.go:126-185`). The HLS attach therefore only registers its pipeline under `outMu`, and runs the probe (3 s, or 11 s with its re-probe, after up to 15 s waiting for its input) and the init wait (up to 58 s, R57 amending R56, #560) **outside** it, so an fMP4 or Output Profile attach on the same channel never waits behind them. | Every later choice depends on these facts, and the relay is the only process that can see the bytes. Probing across a boundary would describe the old source's streams, and M3 shows how silently a stream mismatch fails (finding 6). The 3 s bound (R30): on an MPEG-TS pipe ffprobe reads to its `-analyzeduration` whatever it has found (mpegts is a no-header format), so the bound **is** the probe's share of the zap time and the failover gap. The 4a-1a plan review measured every decision on the 4a-0 fixtures identical to a full probe at 2.5-3 s and geometry lost at 1 s; the bound must exceed the GOP, which the re-probe covers when it does not. |
 | **D10** | **The encoder restarts at every source boundary. It does not survive a switch.** A boundary is every new upstream connection: an `applySwitch`, or a reconnect of the same URL. The channel records the ring index of the boundary's first chunk. The running generation's writer stops **at** that index and closes stdin. The generation then exits on its own (M8: 0.065 s), and its flushed tail becomes the generation's last, possibly short, segments. The argv never carries an input that could keep it alive: no lavfi source. A generation still running 5 s after stdin closed is killed. The grace is its own constant,
 `hls.GenerationExitGrace` = 5 s, and `ffmpeg.KillWait` (500 ms, `relay/ffmpeg/spawn.go:60-62`)
 stays the reap budget after the kill. If the channel has an HLS pipeline, a new generation is probed and started at the boundary. A channel with none starts nothing there (R19; § Encoder argv › Failure). Its first segment is marked `EXT-X-DISCONTINUITY` with a new `EXT-X-MAP` (`init-<gen>.mp4`), and the media sequence continues. | M3: a surviving encoder silently drops a source with different PIDs, so every failover to another provider would be a picture that stops with no error anywhere. M6: AVPlayer plays across a discontinuity. Restarting also makes a change of codec, resolution or audio layout between providers safe, and the fixed output parameters (D8) keep the declared variant true. The cost is the gap measured in M6 (Q6). |
@@ -312,7 +312,7 @@ every mechanism above is `os/exec`, `os`, `crypto/rand`, `encoding/binary`, `enc
 | `GET /live/<u>/<p>/<id>.m3u8`, `GET /<u>/<p>/<id>.m3u8` | `xcForcedFormat` (`.m3u8` ⇒ `hls`) | same |
 | any of the above on a channel whose probe finds no video | relay | 502 `{"error": "no video stream in the source"}`. TS clients are unaffected. |
 | any of the above when the channel's HLS output has failed (§ Encoder argv, failure) | relay | 502 `{"error": "HLS output failed"}` |
-| first-generation init segments not ready within 43 s (R57, amends R56; the first generation that writes a complete set, R41) | relay | 503, `Retry-After: 1`. The session is dropped. |
+| first-generation init segments not ready within 58 s (R57's 43 s, amending R56, plus the source's start, #560; the first generation that writes a complete set, R41) | relay | 503, `Retry-After: 1`. The session is dropped. |
 | draining relay | relay (`Lifecycle`) | 503, as for every tune |
 | every hop denial (401, 403, 404, 429) | unchanged | unchanged |
 
@@ -643,6 +643,22 @@ window. Only a probe that read its whole bound and still failed ends the output.
 feed ended because the channel's ring closed is a stop, at every generation (R40): the channel is
 ending.
 
+**A probe waits for its input** (issue #560, R113). The probe's bound is a bound on analysis, not on
+the source's start: a cold channel's pipeline starts at the entry's attach, before its ring holds a
+byte, and the built-in FFmpeg stream profile publishes its first chunk about 6 s later, after its own
+ffmpeg's input analysis (the ring publishes only whole 255,868-byte chunks, so a Proxy source under
+about 680 kb/s is as late). So every probe first waits for a chunk past where its generation starts,
+and spawns ffprobe, and starts its 3 s or 8 s bound, only once one exists. The wait is bounded by the
+pipeline's stop, by the ring's close (a stop, as R40) and by `hls.SourceStartWait`, 15 s: 2.5 times
+the FFmpeg profile's measured 6 s, and the Proxy source's 5 s connect bound plus one chunk at 205 kb/s.
+A source that sends nothing for 15 s fails the output as a failed probe does (the mark, and 502
+on the entry). The entry's wait gains the same 15 s (58 s); a media playlist's does not, because it
+is requested only after its multivariant, once the source has started. A generation restarted at the
+ring's head after a death waits the same way, where it used to probe no bytes at all. A generation at
+a source boundary never waits: the running generation's feed sees the boundary only when the new
+connection's first chunk is published, so that chunk exists before the next probe starts, and Q6's
+failover gap is unchanged.
+
 **Automatic generation (4a-1d).** The rules are applied per rendition, from the probe. Amended by the
 4a-1d plan: the copy conditions below are the whole rule; the rows the plan added are marked.
 
@@ -712,8 +728,8 @@ Such a source is encoded, which is correct and only costs the copy (R63; § Risk
   generation's first video fragment is `max(30 s, the stall timeout)`, not three times it: before the
   first fragment the wait is an encoder's cold start, whose GOP is 2 s in every mode, or a copy's
   first closed GOP, which is at most 2 × K = 12 s of media, and three times 30 s would push the
-  entry's wait (43 s) past nginx's 60 s `proxy_read_timeout` on `/hls/`. So the waits stay 43 s at
-  every target. The presence thresholds (§ Presence thresholds) take the session's pipeline's
+  media playlist's wait (43 s) past nginx's 60 s `proxy_read_timeout` on `/hls/`. So that wait stays 43 s at
+  every target, and the entry's 58 s (#560). The presence thresholds (§ Presence thresholds) take the session's pipeline's
   target, set once the first generation's inits exist. The store's byte ceiling scales with the
   target (64 MiB at 2, 192 MiB at 6), which keeps RFC 8216 § 6.2.2's 21 segments of a copied
   source up to about 12 Mb/s at a target of 6, and the ten listed ones up to about 26 Mb/s; above
@@ -760,7 +776,7 @@ Transcode mode always has TD = 2. *Automatic* mode may declare up to 6 (4a-1d).
   once".
 - **Activity** is any request carrying the session's token, **and** the entry request that created
   the session. A request counts from its arrival until its response is complete. So an entry
-  waiting up to 43 s (R57, amends R56) for the first init segments, or a media-playlist request long-polling for the
+  waiting up to 58 s (R57, amends R56; #560) for the first init segments, or a media-playlist request long-polling for the
   first segment, is activity for its whole duration. Silence and idle departure are measured from
   the **end** of the last request, and only while none is in flight.
 
@@ -1177,8 +1193,8 @@ break-check therefore reddens deterministically, not one run in several thousand
   - `liveSyncDurationCount: 3`;
   - `backBufferLength: 120`, so a 60-minute window is not held in browser memory;
   - recovery on `NETWORK_ERROR` and `MEDIA_ERROR`, as the recordings path already does;
-  - a `manifestLoadPolicy` (entry) timeout of 65 s: the relay's next-source budget (14.1 s,
-    `tuneBudget`) plus its 43 s ready wait (R57) plus a margin, under nginx's 300 s read timeout on
+  - a `manifestLoadPolicy` (entry) timeout of 80 s: the relay's next-source budget (14.1 s,
+    `tuneBudget`) plus its 58 s ready wait (R57; #560) plus a margin, under nginx's 300 s read timeout on
     `/proxy/ts/stream/`; and a `playlistLoadPolicy` timeout of 50 s, above the relay's 43 s
     first-segment wait and under nginx's 60 s `/hls/` read timeout. hls.js 1.6's defaults (a 20 s
     manifest load, a 10 s playlist first byte) are shorter than a legitimate cold software start.
@@ -2273,6 +2289,15 @@ Filled in as PRs merge.
   § Open questions records CI's measurements: Q9 is answered (hls.js keeps reloading while paused,
   so there is no leave on pause), and Q6's software gap is 7.91-9.97 s over six runs, under the
   10 s threshold every time but at its edge, so the owner's Quick Sync measurement decides.
+- **2026-09-30, amended by the fix for #560** (`docs/superpowers/plans/2026-09-30-fix-560-cold-hls-probe.md`,
+  written against `a9d6cee3`; owner ruling R113). D7, D9, § Entry, § Encoder argv › Failure, § Automatic
+  generation's R42 bullet, § Presence › Activity and § Browser player: a probe first waits for a chunk
+  past where its generation starts, up to `hls.SourceStartWait` (15 s), and only then spawns ffprobe and
+  starts its bound; a source that sends nothing for 15 s fails the output as a failed probe does. The
+  entry's wait is 58 s (R57's 43 s plus those 15 s) and hls.js's entry timeout 80 s; a media playlist's
+  wait stays 43 s. The quick probe's 3 s had started at the entry's attach, before a cold channel's ring
+  held a byte, so every cold tune on the built-in FFmpeg stream profile, whose first chunk lands about
+  6 s after the tune, answered 502.
 
 ## Appendix A — the owner's rulings (2026-09-26/27), restated
 
```

## Appendix E — the parity-matrix rows 33, 36 and 37

```diff
diff --git a/docs/relay-parity-matrix.md b/docs/relay-parity-matrix.md
index 6780ecdb..1125c916 100644
--- a/docs/relay-parity-matrix.md
+++ b/docs/relay-parity-matrix.md
@@ -204,11 +204,11 @@ PR's first, which is the distance git needs to merge them cleanly.
 <!-- block: phase 4 -->
 | 31 | An HLS generation's segments are 2.000 s plus or minus one frame, each starting with a sync sample: the segmenter accumulates the encoder's fragments until the 2 s grid from the generation's first video frame is reached and cuts only before a fragment that opens on a sync sample | `relay/hls/segmenter.go:238-275`, `relay/hls/argv.go:340-393` | `relay/hls/real_test.go::TestRealThe1080iFixtureGivesAligned2sSegmentsOnThreeRenditions`, `relay/hls/pipeline_test.go::TestSegmentsAccumulateToTheGridAndCutOnlyAtASyncSample` | Phase 4a-1a (spec D6, D8). The real pin runs 12 s of the 4a-0 `h264-1080i-aac-ac3` fixture through the software transcode (`-force_key_frames expr:gte(t,n_forced*2)`, `-g` and `-keyint_min` at round(2R)) and checks every segment but the generation's flushed last one. The stand-in pin feeds one-second fragments, a non-sync one on a grid line included, so the accumulation and the sync rule are held without a real encoder. Served since 4a-1b, which links the package. |
 | 32 | A source boundary (every new upstream connection: a failover or a same-URL reconnect) ends the HLS generation at the boundary's first chunk, and the next generation's first segment carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` while the media sequence continues | `relay/channel/boundary.go:38-63`, `relay/channel/channel.go:622-624`, `relay/hls/feed.go:61-104`, `relay/hls/store.go:107-136`, `relay/hls/store.go:209-241` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity`, `relay/channel/boundary_test.go::TestEveryConnectionAttemptRecordsASourceBoundary`, `e2e/tests/streaming/hls-failover.spec.ts::a failover to a different asset starts a new generation behind EXT-X-DISCONTINUITY` | Phase 4a-1a (spec D10, M3). The real pin feeds two 4a-0 fixtures with different PIDs across a recorded boundary; one encoder fed straight across it silently drops the second source, which is the break-check. `buffer.Ring.MarkBoundary` publishes the old connection's pending whole packets before the boundary, so the chunk at the boundary index is the new connection's own. |
-| 33 | Each HLS generation is probed where it starts: the first from the join point behind live, every later one from its boundary index, so the second generation's probe describes the second source | `relay/hls/pipeline.go:328-444`, `relay/hls/pipeline.go:468-549` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity` | Phase 4a-1a (spec D9). The probe's feed stops at the next boundary as the generation's does. It is bounded at 3 s or 3,000,000 bytes, with one re-probe at 8 s or 5 MB when the video has no geometry or field order (ruling R30; the long-GOP case is `relay/hls/real_test.go::TestRealALongGOPIsReprobedAtTheFullBound`); on an MPEG-TS pipe ffprobe reads to its bound whatever it has found, so the bound is the probe's share of the failover gap (Q6). A connection that ends at the next boundary before it can be probed is skipped rather than failing the output, at generation 0 as at any later one (plan review, round 1 finding 3 and ruling R39); a ring that closes under a probe is a stop (R40). |
+| 33 | Each HLS generation is probed where it starts: the first from the join point behind live, every later one from its boundary index, so the second generation's probe describes the second source; and the probe's bound starts at that start's first chunk, never before it | `relay/hls/pipeline.go:328-444`, `relay/hls/pipeline.go:468-549`, `relay/hls/feed.go:116-132` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity`, `relay/hls/cold_probe_test.go::TestAProbeWaitsForTheSourcesFirstChunk`, `relay/hls/cold_probe_test.go::TestASourceThatSendsNothingFailsTheOutputAfterTheStartWait`, `relay/hls/cold_probe_test.go::TestARingThatClosesBeforeItsFirstChunkIsAStop`, `relay/hls/cold_probe_test.go::TestAStopWhileWaitingForTheFirstChunkIsAStop`, `e2e/tests/streaming/hls-entry.spec.ts::a cold hls tune on the built-in ffmpeg stream profile answers the multivariant` | Phase 4a-1a (spec D9). The probe's feed stops at the next boundary as the generation's does. It is bounded at 3 s or 3,000,000 bytes, with one re-probe at 8 s or 5 MB when the video has no geometry or field order (ruling R30; the long-GOP case is `relay/hls/real_test.go::TestRealALongGOPIsReprobedAtTheFullBound`); on an MPEG-TS pipe ffprobe reads to its bound whatever it has found, so the bound is the probe's share of the failover gap (Q6). A connection that ends at the next boundary before it can be probed is skipped rather than failing the output, at generation 0 as at any later one (plan review, round 1 finding 3 and ruling R39); a ring that closes under a probe is a stop (R40). Since issue #560 (R113) a probe first waits for a chunk past its start, up to `hls.SourceStartWait` (15 s), and spawns ffprobe and starts its bound only then: a cold channel's ring is empty when the pipeline starts, and the built-in `ffmpeg` stream profile publishes its first chunk about 6 s later, so a bound armed at the spawn answered every such tune 502. A source that sends nothing for 15 s fails the output as a failed probe does; a ring that closes, or a stop, during the wait is a stop. |
 | 34 | With no usable Quick Sync the HLS encoder runs in software and never refuses: a missing render node, a failing one-frame detection encode or its timeout selects libx264, and Quick Sync is written off for the process only when a software retry succeeds where it failed and the detection encode, re-run, fails | `relay/hls/detect.go:89-173`, `relay/hls/pipeline.go:574-606` | `relay/hls/detect_test.go::TestDetection`, `relay/hls/real_test.go::TestRealDetectionWithoutQuickSyncGivesSoftware`, `relay/hls/pipeline_test.go::TestASourceCausedEarlyFailureDoesNotWriteQuickSyncOff`, `relay/hls/pipeline_test.go::TestQuickSyncIsWrittenOffOnlyWhenSoftwareSucceedsAndRedetectionFails`, `relay/hls/detect_test.go::TestADetectionCutShortByTheCallerIsNotCached` | Phase 4a-1a (spec D11, finding 5). A detection or re-check cut short by the caller's own context is no evidence and writes nothing off (plan review, finding 1). The QSV argv itself has not run on Quick Sync hardware (Q1); these pins hold the selection and the write-off rule, not the device. |
 | 35 | An audio stream that does not qualify (no known codec, 0 channels or a 0 sample rate, which is what a PMT-declared PID carrying no packets probes as) declares no HLS rendition and is never mapped into the encoder's argv | `relay/hls/probe.go:167-173`, `relay/hls/argv.go:124-154`, `relay/hls/argv.go:260-294` | `relay/hls/real_test.go::TestRealADeclaredButEmptyAudioPIDIsNotMapped`, `relay/hls/argv_test.go::TestANonQualifyingAudioStreamIsNotMapped` | Phase 4a-1a (spec § Encoder argv, finding 7). Mapping such a stream fails every output of the generation (ffmpeg 9.0.1: `sample rate not set`). The real pin strips the AC-3 PID's packets from the 4a-0 1080i fixture and keeps its PMT entry. |
-| 36 | A stalled HLS encoder is a death: a generation that writes no new video fragment for max(10 s, 5 x TARGETDURATION) of the channel's ring advancing is killed (before its first fragment, max(30 s, that): R55 as amended by R58) and counted against the restart bound, while an encoder starved by an idle ring is left alone | `relay/hls/pipeline.go:68-71`, `relay/hls/pipeline.go:1003-1041` | `relay/hls/pipeline_test.go::TestAStalledEncoderIsKilledAsADeath`, `relay/hls/pipeline_test.go::TestAStarvedEncoderIsNotKilled`, `relay/hls/pipeline_test.go::TestASlowFirstFragmentIsNotKilledAsAStall`, `relay/hls/pipeline_test.go::TestAnEncoderThatWritesNothingPastTheStartupAllowanceIsKilled` | Phase 4a-1a (ruling R33, R38). The ring, not the bytes fed, is the measure of input advancing, because a wedged encoder that stops reading its stdin stops the feed too. The clock starts at the first ring advance after the latest fragment and resets whenever the ring is idle for half the timeout, so the watchdog is inert below roughly 410 kb/s (a 255,868-byte chunk less often than every 5 s). Before a generation's first video fragment the allowance is StartupStallFactor (3) times the timeout (ruling R55, 4a-1b): a cold software encode of a 1080i source is fed at real time and was measured killed healthy at 10 s. Since 4a-1d the timeout is the pipeline's own (ruling R42: 10 s at TARGETDURATION 2, 30 s at 6) and the startup allowance is max(30 s, the timeout), 30 s at every target up to 6 (ruling R58), so the entry's 43 s waits stay under nginx's 60 s; pinned also by `relay/hls/automatic_pipeline_test.go::TestTheStallLimitsFollowTheTargetDuration` and `relay/httpapi/hls_automatic_test.go::TestTheEntryWaitsCoverTheLongestTargetDuration`. |
-| 37 | A live tune whose output format resolves to `hls` answers a multivariant playlist rather than bytes: `?output_format=hls` or `m3u8` through the hop's aliases, or an Xtream `.m3u8` URL on either XC root through the relay's extension override, gets 200 `application/vnd.apple.mpegurl` with `Cache-Control: no-store` once the first generation that writes a complete set of init segments has done so, every URI under `/hls/<token>/`; not ready within 43 s (R57) is 503 with `Retry-After: 1` and leaves no client | `apps/proxy/authorize.py:251-260`, `relay/httpapi/xc.go:65-76`, `relay/httpapi/stream.go:429-434`, `relay/httpapi/hls.go:200-354` | `relay/httpapi/hls_test.go::TestAnHLSTuneAnswersAMultivariantPlaylistRatherThanBytes`, `relay/httpapi/hls_test.go::TestAnXCM3U8URLForcesHLSOnBothRoots`, `relay/httpapi/hls_test.go::TestAnEntryWhoseInitsNeverArriveIs503AndLeavesNoClient`, `e2e/tests/streaming/hls-entry.spec.ts::an hls tune answers a multivariant playlist on all three entry forms` | Phase 4a-1b (spec D2, D3, § Entry). The multivariant carries a fresh token on every entry, hence `no-store`. `X-Relay-Output` is ignored on an `hls` tune (D12), so the client's `output_profile_id` is null. `hls` is never a deployment or user default (D2, R23). |
+| 36 | A stalled HLS encoder is a death: a generation that writes no new video fragment for max(10 s, 5 x TARGETDURATION) of the channel's ring advancing is killed (before its first fragment, max(30 s, that): R55 as amended by R58) and counted against the restart bound, while an encoder starved by an idle ring is left alone | `relay/hls/pipeline.go:68-71`, `relay/hls/pipeline.go:1003-1041` | `relay/hls/pipeline_test.go::TestAStalledEncoderIsKilledAsADeath`, `relay/hls/pipeline_test.go::TestAStarvedEncoderIsNotKilled`, `relay/hls/pipeline_test.go::TestASlowFirstFragmentIsNotKilledAsAStall`, `relay/hls/pipeline_test.go::TestAnEncoderThatWritesNothingPastTheStartupAllowanceIsKilled` | Phase 4a-1a (ruling R33, R38). The ring, not the bytes fed, is the measure of input advancing, because a wedged encoder that stops reading its stdin stops the feed too. The clock starts at the first ring advance after the latest fragment and resets whenever the ring is idle for half the timeout, so the watchdog is inert below roughly 410 kb/s (a 255,868-byte chunk less often than every 5 s). Before a generation's first video fragment the allowance is StartupStallFactor (3) times the timeout (ruling R55, 4a-1b): a cold software encode of a 1080i source is fed at real time and was measured killed healthy at 10 s. Since 4a-1d the timeout is the pipeline's own (ruling R42: 10 s at TARGETDURATION 2, 30 s at 6) and the startup allowance is max(30 s, the timeout), 30 s at every target up to 6 (ruling R58), so a media playlist's 43 s wait stays under nginx's 60 s `proxy_read_timeout` on `/hls/`, and the entry's, 58 s with `hls.SourceStartWait` (issue #560), stays under the 300 s on the tune locations that front it; pinned also by `relay/hls/automatic_pipeline_test.go::TestTheStallLimitsFollowTheTargetDuration` and `relay/httpapi/hls_automatic_test.go::TestTheEntryWaitsCoverTheLongestTargetDuration`. |
+| 37 | A live tune whose output format resolves to `hls` answers a multivariant playlist rather than bytes: `?output_format=hls` or `m3u8` through the hop's aliases, or an Xtream `.m3u8` URL on either XC root through the relay's extension override, gets 200 `application/vnd.apple.mpegurl` with `Cache-Control: no-store` once the first generation that writes a complete set of init segments has done so, every URI under `/hls/<token>/`; not ready within 58 s (R57's 43 s plus `hls.SourceStartWait`, issue #560) is 503 with `Retry-After: 1` and leaves no client | `apps/proxy/authorize.py:251-260`, `relay/httpapi/xc.go:65-76`, `relay/httpapi/stream.go:429-434`, `relay/httpapi/hls.go:200-354` | `relay/httpapi/hls_test.go::TestAnHLSTuneAnswersAMultivariantPlaylistRatherThanBytes`, `relay/httpapi/hls_test.go::TestAnXCM3U8URLForcesHLSOnBothRoots`, `relay/httpapi/hls_test.go::TestAnEntryWhoseInitsNeverArriveIs503AndLeavesNoClient`, `relay/httpapi/hls_test.go::TestTheEntryWaitAlsoCoversTheSourcesStart`, `e2e/tests/streaming/hls-entry.spec.ts::an hls tune answers a multivariant playlist on all three entry forms` | Phase 4a-1b (spec D2, D3, § Entry). The multivariant carries a fresh token on every entry, hence `no-store`. `X-Relay-Output` is ignored on an `hls` tune (D12), so the client's `output_profile_id` is null. `hls` is never a deployment or user default (D2, R23). |
 | 38 | `/hls/` is authorized by the media-session token alone: `v1.<sid>.<mac>`, a 128-bit random sid and an HMAC-SHA256 of `SECRET_KEY` over `media-session`, `v1` and the sid, naming no channel; a GET whose token is malformed or whose MAC is wrong, or whose sid is unknown (left, ended by an admin, past its resume window, or minted before a relay restart), is 403 with one body and no detail; a GET on a session whose channel stopped is 410 once and 403 after; `X-Relay-*` and `X-Dispatcharr-Authorized` are ignored there | `relay/control/mediasession.go:50-79`, `relay/session/table.go:205-240`, `relay/httpapi/hls.go:394-437` | `relay/control/mediasession_test.go::TestAMediaSessionTokenIsRefusedWhenForgedOrTampered`, `relay/httpapi/hls_test.go::TestAStoppedSessionIs410OnceThen403AndADeleteIs204`, `relay/httpapi/hls_test.go::TestARejectedTokensTextNeverReachesTheLog`, `e2e/tests/streaming/hls-sessions.spec.ts::a tampered token, a left session and a stopped client are refused` | Phase 4a-1b (spec D4, § The media-session token; R13, R22). No expiry field: the token lives exactly as long as its session (R22). The MAC is compared with `hmac.Equal` before any table lookup. The token is never logged by the relay; nginx's access log records it as it records XC credentials (spec § Risks). |
 | 39 | An HLS viewer is a client in the channel's registry exactly while its session is live: it arrives with its multivariant (`client_connect`), is active on every request carrying its token, and leaves, with `client_disconnect` (`duration`, `bytes_sent`) and its Attach release, on `DELETE /hls/<token>` (204, idempotent), on an admin client stop or stream-limit termination, or once `max(12 s, 6 x TARGETDURATION)` has passed with no request in flight | `relay/session/table.go:287-409`, `relay/session/departure.go:29-46`, `relay/httpapi/control.go:128-170` | `relay/session/table_test.go::TestAnIdleSessionDepartsAfterTheIdleTimeoutAndNotBefore`, `relay/session/table_test.go::TestARequestInFlightHoldsASessionActive`, `relay/httpapi/hls_test.go::TestALeaveEndsTheSessionAtOnceAndIsIdempotent`, `relay/httpapi/hls_test.go::TestAnAdminClientStopEndsAnHLSSession`, `e2e/tests/streaming/hls-sessions.spec.ts::an hls client is listed while it plays and leaves at once on DELETE` | Phase 4a-1b (spec D5, § Presence). The one place the relay infers presence rather than observing it (spec § The ADR 0006 amendment). The per-user stream limit counts these clients because it counts the registry; a departed session is not a client. |
 | 40 | A stopped channel's HLS sessions become STOPPED on the goroutine that decided the stop, never synchronously on the channel's own: an admin stop and the drain in `Manager.Stop`, the last client's release in `stopIfStillIdle`, and a run that ended by itself or an HLS output that failed on a fresh goroutine, which drops their client entries (`client_disconnect`, no release) and then makes the manager's idle decision, so no stop waits on its own `done` | `relay/channel/manager.go:340-473`, `relay/channel/channel.go:184-188`, `relay/httpapi/hls.go:370-385` | `relay/httpapi/hls_test.go::TestSelfStopRunEnded`, `relay/httpapi/hls_test.go::TestSelfStopHLSFailedWithNoOtherClient`, `relay/httpapi/hls_test.go::TestSelfStopHLSFailedWithATSClient`, `relay/httpapi/hls_test.go::TestAnAdminChannelStopEndsItsHLSSessions` | Phase 4a-1b (spec § Presence, Who ends sessions). The run-ended case is the break-check's oracle: done synchronously from `run()`'s defers, the stop waits out `StopWait` on its own `done` and logs `source goroutine did not return in time`. |
```

## Appendix F — the defect-ledger entry (fill `⟨PR⟩`)

```diff
diff --git a/metrics/curated/defects.yml b/metrics/curated/defects.yml
index 0d02eeeb..51e0a337 100644
--- a/metrics/curated/defects.yml
+++ b/metrics/curated/defects.yml
@@ -47,3 +47,4 @@
 - {id: catchup-provider-tz-drops-seconds, title: "convert_timestamp_to_provider_tz dropped the requested seconds for a non-UTC provider timezone while the UTC branch kept them, so the precision asked for depended on the provider's declared zone", area: correctness, severity: low, status: fixed, source: null, issue: 111, test: e2e/tests/streaming/catchup-provider-timezone.spec.ts, fixed_in: 438, carried_as: null, first_seen: 2026-09-01, status_changed: 2026-09-25}
 - {id: xc-vod-info-detailed-info-gate, title: "xc_get_vod_info gated the relation's detailed_info merge on Movie.custom_properties, so a movie with none lost bitrate, video, audio and the plot override on the XC surface", area: correctness, severity: low, status: fixed, source: null, issue: 97, test: e2e/tests/seeded/xc-vod-catalogue.spec.ts, fixed_in: 453, carried_as: null, first_seen: 2026-08-31, status_changed: 2026-09-25}
 - {id: vod-category-account-filter-500, title: "VODCategoryFilter.m3u_account named m3u_account__id, a relation VODCategory does not have, so ?m3u_account= on /api/vod/categories/ was a 500", area: correctness, severity: low, status: fixed, source: null, issue: 96, test: e2e/tests/seeded/vod-ingest-fidelity.spec.ts, fixed_in: 453, carried_as: null, first_seen: 2026-08-30, status_changed: 2026-09-25}
+- {id: hls-cold-probe-502, title: "A cold HLS entry answered 502 whenever the channel's ring published its first chunk more than 3 s after the tune, which is every cold tune on the default FFmpeg stream profile: the quick probe's 3 s bound started when the pipeline did, before the ring held a byte, so ffprobe read an empty pipe and the output failed", area: correctness, severity: high, status: fixed, source: null, issue: 560, test: relay/hls/cold_probe_test.go, fixed_in: ⟨PR⟩, carried_as: null, first_seen: 2026-09-30, status_changed: 2026-09-30}
```
