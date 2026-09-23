# Fix plan, category A — the Go relay's carried defects

**Goal.** Fix the eleven defects the Go relay carries from the deleted Python relay. Stage 2d-4 deleted `apps/proxy/live_proxy/`, so spec D5's "reproduce, do not fix" has nothing left to agree with: each of these is now an ordinary Go bug (spec Amendment A10's closing bullet, A16.12 item 4). Seven PRs close all eleven issues. Six are Go-only or Go-first; one (#233) is Django-first with a relay-side contract pin.

**Category A, planned second** (order B, A, J, C, D, E, G, H, I, F). **Seed: `a54b09a9`** (`main`, 2026-09-23). Every `file:line` below was opened at the seed.

**What has already been verified, and how.** Every production change in this plan was prototyped in a scratch export of the seed (`git archive a54b09a9 relay core/… apps/proxy/…`), never in a worktree, and every test was run red against the seed code and green against the fix. The diff appendices (A, C, E, G, I, K, M, N) are the prototype's own `diff -u` output. Extracted from this document and applied with `git apply` in PR order to a fresh seed export, they reproduce the prototype byte for byte. **Fix round 1**, on the fable comparison of #348 and this plan, absorbed #348's fragment ceiling and short-`moof` arm into A-4, widened `relaytest`'s copied regex in A-1, hoisted a `clock()` helper in A-2, stated row 6's `Max`/`Max+1` asymmetry, repaired Appendix N (the first assembly stripped the whitespace-only last context line off every block, so `git apply` refused N), and added open question 4. Every change was re-prototyped, re-run red at the seed and green after, and re-checked with the same appendix check. The Go test appendices are the prototype's final test functions, verbatim. The prototype passes `go build`, `go vet`, `go test -race` on every edited package, `golangci-lint run` on darwin and with `GOOS=linux` (0 issues, repo `.golangci.yml`), and `relay/internal/credlint` (12 packages clean). The two Django halves were run in a private container (`fixplan-A`, its own DB volume, never `dispatcharr-testrunner`) against a writable copy of the tree: `core.tests` 107 OK, `apps.proxy.tests` 380 OK. The break-checks listed in each PR were each run and each reddened with the message quoted. **The implementer re-does all of it on the real branch; the prototype proves the plan is buildable, not that the PR is done.**

---

## Files this plan touches

| PR | Production | Tests and fixtures | Docs and ledger |
|---|---|---|---|
| A-1 | `relay/ffmpeg/progress.go`, `relay/ffmpeg/spawn.go` | `relay/ffmpeg/progress_test.go`, `relay/ffmpeg/spawn_test.go`, `relay/channel/source_transcode_test.go`, `relay/internal/relaytest/corpus.go`, `relay/internal/relaytest/corpus_test.go` (new), two new captures under `relay/internal/relaytest/testdata/ffmpeg_stderr/` | `relay/internal/relaytest/testdata/ffmpeg_stderr/CAPTURE.md`, `docs/relay-parity-matrix.md` (rows 4, 28), `CLAUDE.md`, `metrics/curated/defects.yml` |
| A-2 | `relay/ffmpeg/detector.go`, `relay/channel/channel.go`, `relay/channel/failover.go`, `relay/channel/source_transcode.go`, `relay/channel/tuning.go` | `relay/ffmpeg/detector_test.go`, `relay/channel/source_transcode_test.go` | matrix (rows 1, 3, 4, 5, 6), `CLAUDE.md`, `defects.yml` |
| A-3 | `relay/channel/source_transcode.go` | `relay/channel/source_transcode_test.go` | matrix (row 1), `CLAUDE.md`, `defects.yml` |
| A-4 | `relay/output/fmp4.go` | `relay/output/scanner_test.go` | none |
| A-5 | `relay/httpapi/fmp4.go` | `relay/httpapi/fmp4_test.go` | matrix (row 12), `CLAUDE.md`, `defects.yml` |
| A-6 | `relay/httpapi/detail.go`, `apps/proxy/relay_serializers.py` | `relay/httpapi/detail_golden_test.go`, `relay/httpapi/transcode_test.go`, `relay/httpapi/testdata/channel_detail.json`, `apps/proxy/tests/test_relay_detail_payload_golden.py` | matrix (rows 18, 28), `CLAUDE.md`, `defects.yml` |
| A-7 | `core/relay_events.py` | `core/tests/test_relay_events.py`, `relay/channel/manager_test.go` | none |

Nothing under `docker/`, `e2e/`, `frontend/` or `scripts/` changes. No migration. No new Go dependency (`scripts/check_go_stdlib_only.sh` is unaffected: every import added is stdlib, and only in tests).

## Overlap with other categories

Checked against every other category's evidence in `sweep-report.md` and `issues-{B..J}.md`.

- **`CLAUDE.md`.** A deletes six bullets in § Known defects (lines 128, 129, 130, 134, 135, 136) and rewrites one clause each in line 63 (§ Test hooks) and line 82 (§ Architecture › State). **J** edits the `hls_proxy` and dead-`RedisKeys` sentences (§ Architecture, § Structural constraints, the "Dead or unwired" paragraph after line 136, § Testing). **E** (#232) edits the "Two debugging traps" paragraph. No sentence is shared. The one proximity risk is J's "Dead or unwired" paragraph two lines below A's last deleted bullet; whichever lands second rebases, and A's edits are whole-bullet deletions, so the resolution is mechanical. **B goes first and edits none of A's lines.**
- **`metrics/curated/defects.yml`.** A flips three existing rows (lines 21, 22, 32) and appends four. Every category that closes a ledger issue appends too, so appends collide textually at the end of the file. Resolve by keeping both entries; the validator cares about ids, not order.
- **`core/utils.py`, `core/models.py`, `apps/proxy/next_source.py`.** Cited by A as **evidence only** for #233 and **not edited**. I (#162) may edit `core/utils.py:79,105`; G (#81) cites `core/utils.py:1012`; E (#297/#177) edits `core/models.py:57-60` and adds a `core` migration, and E (#232) edits `core/models.py:359-361`; C (#171) edits `apps/proxy/next_source.py:285`. None of those lines is one A depends on: A-7's fix is in `core/relay_events.py`, which no other category touches.
- **`apps/proxy/constants.py`.** A-6 leaves `ChannelMetadataField.SOURCE_BITRATE`/`FFMPEG_BITRATE`/`FFMPEG_OUTPUT_BITRATE` (`:78-90`) alone. They have been dead since 2d-4 (no Go reader, no Python reader). J's item 2 audits `apps/proxy/redis_keys.py`'s builders, not this class; if J widens to `ChannelMetadataField`, it owns their deletion and A does not race it. Named so neither plan assumes the other did it.
- **`docs/relay-parity-matrix.md`, `relay/**`, `core/relay_events.py`, `apps/proxy/relay_serializers.py`.** A only.

**Within A the PRs are serial.** A-1, A-2 and A-3 all edit `relay/channel/source_transcode_test.go`; matrix rows 6 and 28 are adjacent lines (the block comment in that file explains why adjacent-line edits conflict); the `CLAUDE.md` bullets are adjacent. Implement in the order A-1 … A-7, each branch cut from `main` after its predecessor merges.

---

## Global Constraints

Numbered so a task step can cite one. **A conflict between a constraint and a task step is a STOP and report, never a judgement call.**

1. **Anchor every command** with an absolute path or a leading `cd <your worktree> &&`. The shell's cwd is shared or correlated across concurrent agents (`CLAUDE.md` § Repository and direction).
2. **`set -o pipefail` on every pipeline whose emptiness or exit status you read**; never `2>/dev/null` a git query you will interpret; always `git show "${ref}:path"` with braces.
3. **Stage and commit in separate Bash calls**; write the message with the Write tool and commit with `git commit -F <file>`. The commit gate matches on command text. **The gate runs `go build`, `go vet` and `go test -race ./...` over the whole module for any staged `*.go` — about four minutes, dominated by `relay/httpapi` (≈125 s) and `relay/channel` (≈85 s).** Do not mistake the wait for a hang.
4. **The test-modification rule, verbatim from the planner brief.** A test may change only when the behaviour it pins is the thing being changed, and every such change is listed in the PR section with its before and after assertion. A test that deliberately pins a defect is flipped to pin the fix, and the PR shows the flipped test failing before the fix and passing after. Never widen a tolerance, lower a count or delete an assertion to make a run green. New behaviour gets a new test named after the defect.
5. **Red before green, on the real branch.** Every PR's Task 1 writes or flips its tests against the unmodified production code and records the failure message; Task 2 applies the fix. A test that is green before the fix is not a pin of it: STOP.
6. **The Go coverage ratchet never moves in a fix PR.** `scripts/coverage_relay_go.floor` says `missing=589`, and `--gate` fails the run on any draw above it. Every statement a PR adds must be executed by **its own package's** tests (the gate measures per package, never `-coverpkg`). Verify with Task 4's per-package profile, then `scripts/coverage_relay_go.sh --measure && --gate` locally as indicative; CI's `Go result` is the authority. **A draw above the floor is a finding to attribute per block, never a floor edit in the same PR.** Prototype measurements, per package, seed → all seven PRs applied (round 1's `ffmpeg` and `output` re-measured after the fix round): `relay/ffmpeg` 34 → 28 missing, `relay/output` 15 → 12, `relay/channel` 219 → 219, `relay/httpapi` 126 → 111 (httpapi's figure moves run to run by more than this plan's change).
7. **Gate 2 (the Python ratchet) is touched by A-6 alone.** `apps/proxy/relay_serializers.py` is one of its nine modules. A-6 deletes one covered declaration, so `missing` cannot rise and `modules=`/`rcfile=` do not move; run `scripts/coverage_live_path_isolated.sh` before pushing anyway (a green label does not imply a green gate).
8. **Parity-matrix citations: shift, do not re-survey.** When a PR moves code a row's `Source` range cites, move the range by the PR's own line delta so it still covers what it covered. Correcting a range that was already imprecise at the seed is A9.9's chore, not a fix PR's. The guard checks only that a range lies inside its file, so this is a review obligation, not a mechanical one.
9. **The guard is run, not assumed.** A PR that edits `docs/relay-parity-matrix.md`, or renames a Go test the matrix pins, runs `cd <worktree>/e2e && npx playwright test --project=guards parity-matrix` before pushing. A renamed pin with no matrix edit fails there.
10. **Lint as CI lints.** `cd <worktree>/relay && golangci-lint run ./... && GOOS=linux golangci-lint run ./...` — the second catches build-tagged files the first cannot see. Zero findings is a ratchet. `scripts/check_go_credential_logging.sh` must stay clean.
11. **A channel UUID and a provider URL are secrets.** Neither appears in a log, a test, a commit message or a PR body. The stream hash in A-7's tests is `sha256("test")`, not a real one.
12. **Branch names.** `migration/A-5-fmp4-client-timeout` and `migration/A-6-detail-ffmpeg-bitrate` touch `relay/httpapi/` and take the `migration/` prefix, which runs the full E2E matrix. Every other PR is `fix/A-<n>-<slug>`.
13. **The metrics ledger is edited only when the PR number exists** (open the draft PR first, then commit the ledger edit). Validate with `python -m metrics.build --validate-only --curated metrics/curated`.
14. **Implementation happens in a worktree per PR, off `main`, after the previous A PR merges.** Before writing into any worktree, check occupancy by container and mtime (`CLAUDE.md` § Repository and direction).

---

## Rulings

The design choices this plan makes. Each is the plan's recommendation; the three the user may want to overrule are repeated under **Open questions**.

**R1 — #221: a spent budget refuses the buffering switch and keeps the channel playing.** `MAX_STREAM_SWITCHES` becomes a counter both paths share (a `Channel` field under `mu`, replacing the run loop's local). A buffering switch counts against it; when it is spent, `failoverFromBuffering` returns `false` **without calling the resolver**. The main loop's own behaviour at its bound is unchanged: it ends the channel, because it reaches the bound with no working source. The buffering path reaches it with a source that is still delivering, only slowly, so ending the tune there would turn a degraded stream into a dead one. The stable-run reset (`STABLE_CONNECTION_THRESHOLD`, `channel.go:488-493`) is unchanged: it fires only where the main loop sees an attempt end, and a buffering-cancelled attempt leaves through the `takePending` branch before it. An operator's `Advance` also parks a pending source; it is **not** counted, because it is not automatic.

**R2 — #302: a failed buffering switch defers the next ask by one `buffering_timeout`, and keeps the clock.** A new `Detector.Defer()` sets a hold; `Observe` returns `TimedOut` only once the hold has passed. The three methods that read the time go through one `clock()` helper (fix round 1). That replaces the seed's two copies of the nil-clock fallback, and would have been a third, with one statement, and the detector test covers it with a wall-clock case, so the PR adds no uncovered block to a package whose ratchet has no headroom. `BufferingFor` still measures from the first sub-threshold sample, which is the `duration` a later `channel_failover` reports. `Ended` and `Reset` clear the hold. A bare detector that nobody defers still repeats `TimedOut` on every sample, so `TestTheDetectorFollowsPythonsTransitions`'s "a further sample after an unhandled timeout times out again" is **unchanged and still true**. R1's refusal returns through the same `false`, so a spent budget is re-checked once per timeout, locally, with no network call.

**R3 — #222: an fMP4 client leaves by the exit a TS client reaches, without the keepalive bytes.** The TS loop (`relay/httpapi/stream.go:1005-1031`) drops a client only on an unhealthy channel, and its keepalive packets refresh the very timer its `ClientTimeout` clause reads, so its reachable exit is `MaxKeepalive` (row 12's own Notes say so). The fMP4 loop gets the same exit: on a healthy channel it never times a client out; on an unhealthy one it drops the client once `MaxKeepalive` has passed with nothing to send, counted from the first such read and cleared by the next fragment, as `keepaliveStart` is. **No bytes are written**: an ISO-BMFF stream has no null packet a player is known to skip (a top-level `free` box is legal in the format, but no test in this repo can say whether every MSE implementation tolerates one between fragments). `nginx`'s `proxy_read_timeout 300s` on the live locations (`docker/nginx.conf:333`, `:490`) is at least the default `MaxKeepalive` of 300 s, so the silent wait is not cut short upstream. The `url_switching` exemption stays unported in both loops, for the reason `stream.go:1024-1028` gives.

**R4 — #314: emit `ffmpeg_bitrate`; delete `source_bitrate` from the serializer.** The Go relay already parses the output bitrate into `channel.Stats.FFmpegOutputBitrate` (`relay/channel/stats.go:39`, `:105-107`) and drops it at the renderer; one assignment fixes that. `source_bitrate` has never had a writer in either relay, and adding one is feature work with nothing behind it: ffmpeg's input line for a live source reads `Duration: N/A, start: 1.400000, bitrate: N/A` (`relay/internal/relaytest/testdata/ffmpeg_stderr/normal.stderr`, the preamble), and no frontend file reads the field (`grep -rn source_bitrate frontend/src` is empty at the seed). Removing a declared-but-never-emitted optional field changes no response any client has ever received.

**R5 — #233: Django classifies; the relay passes the identifier through.** The rule "not a UUID means a stream hash" already lives in Django (`apps/proxy/next_source.py:247-257`'s `get_stream_object`). `core/relay_events.py` applies the same rule to an event's `channel_id`: a non-UUID is moved to `details["stream_hash"]` and the row is written with no channel, as `vod_start`'s rows are. The relay keeps no identifier rule of its own; the relay side of this PR is a **contract pin** that it names the identifier verbatim (the property Django's fix depends on), not a code change. Putting a second copy of the rule in Go would be two mechanisms for one property, the shape `relay/channel/channel.go:431-434` warns against.

**R6 — #306 and #119: the resync arm searches for the `moof` literal; the aligned scans keep striding; and no fragment can grow the buffer without bound.** `findMoofOffset` is correct wherever the scan starts on a box boundary: the init segment from offset 0, and a fragment's successor from its own `moof`'s end. It is left alone there, because striding is what stops a `moof` inside an `mdat` payload from being taken for a box. The desync arm (`relay/output/fmp4.go:217-227`) changes to a new `resyncOffset`. It finds the next `moof` literal whose length field reads between `minMoofBox` (16: a header plus an `mfhd`) and `maxMoofBoxBytes` (1 MiB). With nothing found, the arm keeps the last seven bytes (a four-byte length plus three of the type) instead of clearing the buffer, so a header split across two reads survives and the buffer stays bounded. **Two further changes are adopted from #348's A-4** (fix round 1), closing faults beside the arm that my first draft left in place. An aligned `moof` shorter than `minMoofBox` is resynchronised past: at the seed a length below 8 returned without consuming (`:229-231`) and stalled the buffer for good. And a fragment whose end cannot be found is abandoned past `maxFragmentBytes` (64 MiB) instead of held toward a length of up to 4 GiB; its end is unfindable when its own length is corrupt (`:233-236`) or the next box's is (`:238-240`). The false comment at `:136-140` ("recovers at the next real box header either way") is corrected.

**R7 — #24: flush past 64 KiB whatever the buffer carries.** A new `maxStderrLine = 64 << 10` joins the existing 1 KiB rule: past it the buffer is emitted as a line and reset, `frame=` or not. It flushes; it never truncates or drops, so no byte of stderr is lost. The buffer is bounded by the cap plus one 4 KiB read.

**R8 — #299: the gate accepts a `size=`/`Lsize=`-led record carrying `speed=`.** `IsProgressLine` keeps `frame=` as its first clause and adds the ffmpeg 6.x shape. The test corpus gains two **real** ffmpeg 6.1.1 captures, taken with the repository's own `scripts/capture_ffmpeg_stderr.py` in `ubuntu:24.04` (apt `ffmpeg 6.1.1-3ubuntu5`). Measured for this plan: `normal` 12 records, `slow-trickle` 64, **zero `frame=` bytes in either**, every record begins `size=`, and each opens with `speed=N/A` — which is why `relaytest.CorpusSpeeds` (which panics on a non-numeric speed, correctly for the 8.1.2 corpus) must not be called on them.

**R9 — #296: a dropped argument takes its partner.** A dropped value takes the flag before it; a dropped flag takes the value after it. This also fixes the shipped Streamlink profile, `{streamUrl} --http-header User-Agent={userAgent} best --stdout` (`core/migrations/0011_fix_stream_profiles_and_user_agents.py:10`), which on a UDP upstream spawned as `--http-header best --stdout`, handing the quality selector to the header.

**R10 — #227: widen `speedRe`, and its copy in `relaytest`, and nothing else.** `fpsRe` keeps `[0-9.]+`: #227 itself records that ffmpeg is not observed to print a frame rate in scientific notation, and `bitrateRe` is anchored on its unit and fails to match rather than truncating. `relaytest.CorpusSpeeds` quotes the shipped parser by copy (`corpus.go:104-110`; its comment says "the PRODUCTION speed regex … the same literal"), so the copy is widened in the same PR and the comment rewritten, dropping its reference to the deleted `manager_support.py`. *Reversed in fix round 1*: the first draft left the copy narrow because no caller reads `truncation` through it, which made the divergence latent rather than absent. A new `relaytest` test (`TestCorpusSpeedsReadsAScientificNotationSpeedWhole`) pins the two together.

**R11 — the ledger.** Three existing rows move to `fixed`: `max-stream-switches-unbounded` (#221), `fmp4-timeout-no-switch-exemption` (#222), `ffmpeg-speed-scientific-notation` (#227). Four defects that `CLAUDE.md` § Known defects lists **have no ledger row at the seed** (#296, #299, #302, #314) although `docs/agents/metrics.md` says every such item gets one; each fix PR adds its row directly as `fixed` (a new id, so the forward-only check has nothing to compare). #24, #119, #306 and #233 are not `CLAUDE.md` items and get no row.

**R12 — the Phase 2 spec is not amended.** It is closed (A16); A16.12 item 4 lists #222, #296, #299, #302 and #314 as owed, and a fix discharges the debt without rewriting the record of it.

---

## Issue register

Root causes verified at `a54b09a9`. "Upstreamable" is no for every PR: the Go relay, `core/relay_events.py` and `relay_serializers.py` exist only in this fork. The Python originals of these defects live on in upstream's own Python relay, the code this fork deleted at stage 2d-4, and a fix there would be a separate PR against different code (not verified against upstream's current tree: this checkout has no upstream ref fetched).

| # | Root cause at the seed | Fix | Tests (rule 5) | Size | PR |
|---|---|---|---|---|---|
| 227 | `relay/ffmpeg/progress.go:33` `speedRe = speed=\s*([0-9.]+)x?` stops at the `e`; its comment at `:25-31` forbids widening it under D5 | Widen to `([0-9.]+(?:[eE][-+]?[0-9]+)?)` (R10) | **Flip** `progress_test.go:23` `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` → `TestAScientificNotationSpeedIsReadWithItsExponent` | S | A-1 |
| 299 | `relay/ffmpeg/progress.go:40` `IsProgressLine` requires `frame=`; ffmpeg 6.x stream-copy records carry none, so `source_transcode.go:234` never calls `progress` | Accept a `size=`/`Lsize=`-led record carrying `speed=` (R8) | New `TestAnFFmpeg6StreamCopyRecordIsAProgressRecord`, `TestAnFFmpeg6StreamCopyArmsTheBufferingDetector`; two captures join `CorpusNames`, so `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord` runs on them | S | A-1 |
| 24 | `relay/ffmpeg/spawn.go:254` flushes an unterminated buffer only when it lacks `frame=`; nothing else bounds `buf` (`:244-272`) before the trailing `emit` at `:274` (the sweep's `:271` has drifted) | Flush past `maxStderrLine` regardless (R7) | New `TestAnUnterminatedFrameRecordCannotGrowTheReaderWithoutBound` | S | A-1 |
| 302 | `relay/channel/source_transcode.go:342-344`: a failed switch logs and leaves the detector as it was; `relay/ffmpeg/detector.go:86-88` then returns `TimedOut` on every later sample, and `:326` asks again each time | `Detector.Defer()` after a failed switch (R2) | **Flip** `source_transcode_test.go:442` `TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord` → `…AsksOncePerTimeoutNotOnEveryRecord`; new `detector_test.go` `TestADeferredTimeoutIsHeldBackForAnotherTimeout` | S | A-2 |
| 221 | `relay/channel/channel.go:455-457`: `switches` is a run-loop local; `failover.go:293-318` (`failoverFromBuffering`) never reads or increments it; `channel.go:476-482` adopts its result without counting | Shared counter, buffering path consults and counts it (R1) | **Flip** `source_transcode_test.go:396` `TestABufferingFailoverIgnoresMaxStreamSwitches` → `TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent`; new `TestABufferingFailoverCountsAgainstMaxStreamSwitches`; `failover_test.go:604` `TestMaxStreamSwitchesBoundsAMainLoopSwitch` unchanged | M | A-2 |
| 296 | `relay/channel/source_transcode.go:105-119` drops each argument carrying the user agent and keeps the flag before it | Drop the partner too (R9) | **Flip** `source_transcode_test.go:569` `TestTheUDPFilterDropsUserAgentArguments` → `…WithTheirFlags`; new `TestTheUDPFilterLeavesNoDanglingFlag` | S | A-3 |
| 306 | `relay/output/fmp4.go:221-225`: the desync arm calls the box-striding `findMoofOffset(s.frag, 1)`, which re-reads a length at a one-byte shift, strides past every box, returns -1, and the arm clears the whole buffer | `resyncOffset` + bounded tail; from #348, the short-`moof` arm and the fragment ceiling (R6) | **Flip** `scanner_test.go:181` `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` → `TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof`; new `TestAMoofHeaderSplitAcrossReadsSurvivesAResync`, `TestAMoofLiteralWithAnImplausibleLengthIsNotAResyncPoint`, `TestAMoofShorterThanARealOneDoesNotStallTheBuffer`, `TestAFragmentThatNeverEndsIsAbandonedAtTheCeiling` | M | A-4 |
| 119 | Same code path as #306 (`fmp4.go:145-165` strides by any length ≥ 8; `:221-225` clears on -1). Its counterexample reaches the flush only with two garbage bytes, because the arm starts at offset 1 (measured: prefix `01` resyncs at 1 even at the seed; `01 01` returns -1) | As #306 | New `TestAGarbageRunThatReadsAsALargeLengthDoesNotHideTheNextMoof` carries the counterexample at the finder (with a real 16-byte `moof`) and the two-byte form through the scanner; the issue's literal empty `moof` is a rejection case under the 16-byte floor | — | A-4 |
| 222 | `relay/httpapi/fmp4.go:229-237`: on an empty wait, `time.Since(lastYield) > tuning.ClientTimeout` drops the client with no health check and no keepalive equivalent | R3 | **Flip** `fmp4_test.go:384` `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` → `TestAStalledFMP4ClientOnAHealthyChannelStaysConnectedLikeATSClient`; new `TestAnFMP4ClientOnAnUnhealthyStallIsDroppedAtTheKeepaliveCap` | M | A-5 |
| 314 | `relay/httpapi/detail.go:115-133` documents both fields as absences; `detailPayload` (`:134-173`) declares neither; `channel.Stats.FFmpegOutputBitrate` (`relay/channel/stats.go:39`) is set and never rendered. `apps/proxy/relay_serializers.py:133` declares `source_bitrate`, which nothing writes | R4 | **Flip** `detail_golden_test.go:222` `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` → `TestTheDetailPayloadCarriesTheFFmpegOutputBitrate`; new `TestTheDetailEndpointCarriesTheFFmpegOutputBitrate`; Python `NEVER_WRITTEN` emptied and the fixture gains `ffmpeg_bitrate` | S | A-6 |
| 233 | The relay posts the tuned identifier as `channel_id` (`relay/channel/events.go:38`, `manager.go:310-313`, `channel.go:651`); for `/proxy/ts/stream/<stream_hash>` that is a sha256 hex string. `core/relay_events.py:183` passes it to `log_system_event`, whose `SystemEvent.objects.create` raises on the `UUIDField` (`core/models.py:817`) and whose bare `except Exception` (`core/utils.py:922-924`) swallows it. **Reproduced at the seed**: `ERROR core.utils Failed to log system event channel_start: ['"9f86…0a08" is not a valid UUID.']`, and no row. Every event of a preview tune is lost, not only start and stop | R5 | New `test_a_stream_hash_tune_raised_no_lifecycle_rows`, `test_a_uuid_channel_id_is_not_mistaken_for_a_stream_hash`; Go contract pin `TestAStreamHashTuneNamesItsHashAsTheEventChannelID` | S | A-7 |

**Duplicates.** #119 and #306 are one defect: the same arm, the same stride, the same clear. **#306 survives** — it is the number the code comment, the Go pin and the matrix-era record name — and #119 closes as its duplicate, its fuzz counterexample kept as a regression example in `TestAGarbageRunThatReadsAsALargeLengthDoesNotHideTheNextMoof`. No other pair in A duplicates.

**Tracker notes for the lead (writes deferred).** #24 carries a `wontfix` label whose triage comment cites the deleted ownership lease, which is unrelated; the sweep recommends dropping it. #222's triage comment also says `wontfix` (no label). Each issue's title still names Python paths; the sweep's retitles apply.

---

## The common task shape

Every PR below runs the same five tasks; each section lists only what is specific to it.

- **Task 0 — branch and seed check.** `cd /Users/dion/git/Dispatcharr && git fetch origin && git worktree add .worktrees/<branch-dir> -b <branch> origin/main`. Then re-open every seed citation in the PR's own row of the issue register and confirm it still says what the register says. A drifted line number is a re-anchor; a drifted **behaviour** is a STOP.
- **Task 1 — tests first, red.** Write the new and flipped tests (the PR's test appendix). Run the package and record the failure. The expected failure text below was measured on the prototype; the wording must name the mechanism, not merely fail (a red from a compile error or a panic is not the pin).
- **Task 2 — the fix, green.** Apply the PR's production appendix (`patch -p1 < <file>` from the worktree root, or by hand; the anchors are unique at the seed). Run the package under `-race`. Then run each break-check: make the stated wrong edit, confirm the stated test reddens with the stated message, and revert. **Record each in the PR body.**
- **Task 3 — docs and ledger.** Matrix, `CLAUDE.md`, `defects.yml` and any fixture docs, as the section lists. Open the draft PR first if the ledger needs its number (GC 13). Every `<…>` in a drafted matrix row is a `path:start-end` range to fill from the real branch (the prototype's span is given beside it as a guide); `#<PR>` is the PR's own number. The guard rejects a `Source` cell that is not a resolvable citation.
- **Task 4 — verify as CI verifies.** From `<worktree>/relay`: `go build ./... && go vet ./... && go test -count=1 -race ./<pkgs>/`; `golangci-lint run ./... && GOOS=linux golangci-lint run ./...`; `cd <worktree> && scripts/check_go_credential_logging.sh && scripts/check_go_stdlib_only.sh relay`. Coverage: `go test -count=1 -race -covermode=atomic -coverprofile=<scratch>/p.out ./<pkg>/` per edited package, then `go tool cover -func=<scratch>/p.out` and confirm every function the PR touched shows no uncovered new block; then `COVERAGE_RELAY_GO_DATA_DIR=<scratch>/cov scripts/coverage_relay_go.sh --measure && scripts/coverage_relay_go.sh --gate` (GC 6). Matrix guard when the section says so (GC 9). Metrics validation when `defects.yml` changed (GC 13). Backend labels when the section names any, in **your own** container (`DISPATCHARR_TEST_CONTAINER=<yours> DISPATCHARR_TEST_DB_VOLUME=<yours>-db CLAUDE_HOOK_REPO_ROOT=<worktree> .claude/hooks/start-test-container.sh`), never the shared `dispatcharr-testrunner`, one label at a time.

Commit (GC 3), push, and open the PR as a **draft** with the description below, ending `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

---

## PR A-1 — `fix/A-1-ffmpeg-stderr-parsing`

**Closes #227, #299, #24.** Size M (three S fixes in one package, plus a corpus capture). Upstreamable: no.
**Go packages:** `relay/ffmpeg`, `relay/channel` (one test), `relay/internal/relaytest` (test support, outside the coverage denominator). **Backend labels:** none (`scripts/ci_backend_test_labels.py` returns `[]` for `relay/` paths). **E2E:** path-gated matrix; `fix/` prefix.
**Why one PR.** All three are the stderr path's parsing, two share a file, and #299's new captures are read by `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord`, which #24 also relies on.

### Task 1 specifics — the captures, then the tests

**Step 1: capture the ffmpeg 6.1.1 corpus.** The repository's own script, unmodified, in a distro image whose apt ffmpeg is 6.1.1. Resolve the image digest first and record it (the supply-chain rule is for committed `FROM` lines; here it is provenance):

```bash
cd <worktree> && docker buildx imagetools inspect ubuntu:24.04 --format '{{json .Manifest.Digest}}'
mkdir -p <scratch>/ff6 && docker run --rm --name <yourname>-ff6cap \
  -v <worktree>:/repo:ro -v <scratch>/ff6:/out ubuntu:24.04@sha256:<digest> bash -c '
    set -e; export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null && apt-get install -y -qq ffmpeg python3 >/dev/null 2>&1
    ffmpeg -version | head -1
    python3 /repo/scripts/capture_ffmpeg_stderr.py /out'
cp <scratch>/ff6/normal.stderr       relay/internal/relaytest/testdata/ffmpeg_stderr/ffmpeg6-normal.stderr
cp <scratch>/ff6/slow-trickle.stderr relay/internal/relaytest/testdata/ffmpeg_stderr/ffmpeg6-slow-trickle.stderr
```

The planner's run of exactly this printed `ffmpeg version 6.1.1-3ubuntu5`, `normal: 4501 bytes, 12 progress records`, `slow-trickle: 9371 bytes, 64 progress records`. **The digits will differ and do not matter** (`CAPTURE.md`'s own rule). **The shape must hold, and it is a STOP if it does not:** `grep -c 'frame=' <file>` prints `0` for both (the pin is about records with no `frame=`); every record begins `size=`; `slow-trickle`'s speeds start above 1.0 and end below it. `truncation.stderr` from this run is **not** committed. Never hand-edit a capture.

**Step 2: tests.** Appendix B, placed as follows. `progress_test.go`: replace the `fullSpeedRe` declaration and the whole of `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` (seed `:11-47`) with Appendix B's `var (...)` block and `TestAScientificNotationSpeedIsReadWithItsExponent`; insert `TestAnFFmpeg6StreamCopyRecordIsAProgressRecord` before `// Every shape CAPTURE.md names`; add `"strings"` to the imports. `spawn_test.go`: append `TestAnUnterminatedFrameRecordCannotGrowTheReaderWithoutBound`. `source_transcode_test.go`: insert `TestAnFFmpeg6StreamCopyArmsTheBufferingDetector` before `// Recovery: a speed back at the threshold`. New file `relay/internal/relaytest/corpus_test.go` (`package relaytest`, importing only `testing`) holding `TestCorpusSpeedsReadsAScientificNotationSpeedWhole`. `corpus.go`: Appendix A's hunk (the two new names, and the widened copied regex, R10).

**Expected red at the seed** (measured):

```
progress_test.go:…: Speed = 1.41, want the whole value 1410 (the mantissa alone is 1.41: issue #227)
progress_test.go:…: a real ffmpeg 6.1.1 progress record is not a progress line (#299): "size=       0kB time=00:00:00.02 bitrate=   0.0kbits/s speed=N/A"
spawn_test.go:105: the reader saw 0 progress lines, the corpus holds 12 records -- the split lost or merged records
spawn_test.go:…: a 2098169-byte line reached the callback: the buffer grew past maxStderrLine (65536) plus one read
source_transcode_test.go:…: timed out after 10s waiting for a speed reported off a 6.1.1 record
corpus_test.go:16: CorpusSpeeds read the truncation record as 1.41, its mantissa: the copied regex has fallen behind package ffmpeg's (#227)
```

(The #24 test references `maxStderrLine`, which the seed lacks; for its red run, declare `const maxStderrLine = 64 << 10` alone in `spawn.go` first — a constant nothing reads changes no behaviour — then add its use in Task 2.)

### Task 2 specifics

Appendix A: `progress.go` (regex and gate), `spawn.go` (the cap), `corpus.go` (the names, the widened copy and its comment).

**Break-checks** (each run on the prototype):

| Wrong edit | Test that reddens | Message |
|---|---|---|
| `speedRe` back to `speed=\s*([0-9.]+)x?` | `TestAScientificNotationSpeedIsReadWithItsExponent` | `Speed = 1.41, want the whole value 1410 …` |
| `corpusSpeedRe` back to `speed=\s*([0-9.]+)x?` | `TestCorpusSpeedsReadsAScientificNotationSpeedWhole` | `CorpusSpeeds read the truncation record as 1.41, its mantissa …` |
| `IsProgressLine`'s second clause replaced with `return false` | `TestAnFFmpeg6StreamCopyRecordIsAProgressRecord`, `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord/ffmpeg6-*`, `TestAnFFmpeg6StreamCopyArmsTheBufferingDetector` | the three #299 messages above |
| `len(buf) > maxStderrLine \|\|` removed from the flush condition | `TestAnUnterminatedFrameRecordCannotGrowTheReaderWithoutBound` | `a 2098169-byte line reached the callback …` |

### Test changes under rule 4

| Test | Before | After |
|---|---|---|
| `progress_test.go` `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` → **renamed** `TestAScientificNotationSpeedIsReadWithItsExponent` | `*p.Speed == mantissa` and `*p.Speed < actual/100`; the precondition read the mantissa through the production `speedRe` | `*p.Speed == actual`; the precondition reads the mantissa through a **test-local** `mantissaSpeedRe`, because once `speedRe` reads the exponent it can no longer supply the other reading (and an oracle computed by the code under test cannot fail) |
| `relaytest.CorpusNames` | three names | five; `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord`'s assertion is unchanged and now also runs on the two 6.1.1 captures |

Unchanged and still passing, named because they sit next to the edits: `TestAnUnparseableNumberDropsTheWholeRecord` (its `fps=25 speed=1.0x` line has no `size=` prefix, so it is still not a progress line), `TestALongUnterminatedLineIsFlushedWhileTheChildStillRuns`, `TestParseProgressReadsTheRealRecordShapes`.

### Task 3 specifics

- **Matrix row 28**, replaced in place (one line, no padding; GC 9 runs the guard):

  ```text
  | 28 | `ffmpeg_speed` is parsed with an optional exponent: real ffmpeg 8.1.2 emits `speed=1.41e+03x` on a truncated input and both status surfaces report 1410, not its mantissa | `relay/ffmpeg/progress.go:<regex block through IsProgressLine>`, `relay/httpapi/detail.go:485-500`, `relay/httpapi/channels.go:85-95` | `relay/ffmpeg/progress_test.go::TestAScientificNotationSpeedIsReadWithItsExponent` | Filed as [#227](https://github.com/D10Scot/Dispatcharr/issues/227) and fixed in #<PR>. The Python relay's `[0-9.]+` stopped at the `e` and reported the mantissa, a 1000x under-report, and the Go relay reproduced it per D5 until stage 2d-4 left it an ordinary Go defect. Found by capturing a real ffmpeg stderr corpus in 2a-2, not by reading the regex. Failover was never affected: the reachable case under-reports a high speed as a still-high one. `fps=` keeps the narrow class; ffmpeg is not observed to print a frame rate in scientific notation. |
  ```

  (The prototype's regex block through `IsProgressLine` is `progress.go:25-56`.)
- **Matrix row 4**: its `relay/ffmpeg/progress.go:20-40` citation shifts to the same span (GC 8). No other row cites `progress.go` or `spawn.go`.
- **`CAPTURE.md`**: "These three files" becomes "These five files"; a provenance paragraph for the two 6.1.1 captures (image and digest, `ffmpeg -version` line, date, the command above, and that `truncation` from that run was not kept); the table gains two rows stating shape only (no `frame=` anywhere, `size=`-led records, an opening `speed=N/A`); the #227 paragraph (seed `:88-97`) ends "Fixed in #<PR>; the parser now reads the exponent" in place of "Reproduced here, not fixed".
- **`CLAUDE.md`**: delete the #299 bullet (seed line 135). In line 63, replace "so the verbatim-ported `IsProgressLine` gate never passes and the pin fails rather than skips when `CI` is set" with "which the `IsProgressLine` gate did not accept until [#299](https://github.com/D10Scot/Dispatcharr/issues/299) was fixed, so the pin failed rather than skipped when `CI` is set". The rest of that sentence (why CI runs on the base image) stays true and stays.
- **`defects.yml`**: `ffmpeg-speed-scientific-notation` → `status: fixed, fixed_in: <PR>, status_changed: <date>` (keep its `test`). Append:
  `- {id: ffmpeg6-progress-gate-blind, title: "The buffering-progress gate required frame=, which ffmpeg 6.x stream-copy records never carry, so no speed was recorded and the buffering detector could never arm on a user-supplied ffmpeg 6", area: correctness, severity: low, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 299, test: relay/ffmpeg/progress_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-14, status_changed: <date>}`

### Coverage

Every statement A-1 adds to `relay/ffmpeg` (the gate's second clause, the cap's condition) is executed by the package's own new tests. Measured with A-1 and A-2 together, after fix round 1: 352 → 355 statements, 34 → 28 missing. `relay/internal/relaytest` is outside the denominator.

### PR description draft

> **fix(relay): read ffmpeg's exponent, accept ffmpeg 6 progress records, bound the stderr reader**
>
> Three defects the Go relay carried from the Python relay's stderr path, each an ordinary Go bug since stage 2d-4.
>
> - #227: `speedRe` stopped at the `e` of `speed=1.41e+03x` and reported 1.41. It now reads the exponent. Parity-matrix row 28's pin is flipped (before: speed equals the mantissa; after: speed equals the whole value).
> - #299: `IsProgressLine` required `frame=`, which ffmpeg 6.x stream-copy records never carry. It now also accepts a `size=`/`Lsize=`-led record carrying `speed=`. Two real ffmpeg 6.1.1 captures join the corpus (provenance in `CAPTURE.md`).
> - #24: an unterminated stderr buffer containing `frame=` grew without bound. It is now flushed past 64 KiB, whatever it carries; nothing is dropped.
>
> Red at the base, green here, and each break-check reddened: <table from Task 2>. Coverage: no new uncovered statement in `relay/ffmpeg`. Ledger: `ffmpeg-speed-scientific-notation` → fixed; `ffmpeg6-progress-gate-blind` added as fixed.

---

## PR A-2 — `fix/A-2-buffering-failover-bounds`

**Closes #221, #302.** Size M. Upstreamable: no.
**Go packages:** `relay/ffmpeg` (detector), `relay/channel`. **Backend labels:** none. **E2E:** path-gated; `fix/` prefix.
**Why one PR.** Both are the stderr path's buffering-timeout branch, and they interlock: R1's refusal and R2's deferral are the same `false` return, so either alone would leave the other's test describing a half-built behaviour.

### Task 1 specifics

Appendix D. `detector_test.go`: append `TestADeferredTimeoutIsHeldBackForAnotherTimeout`. `source_transcode_test.go`: **replace** the seed's `TestABufferingFailoverIgnoresMaxStreamSwitches` (with its comment, `:387-434`) by `TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent` followed by `TestABufferingFailoverCountsAgainstMaxStreamSwitches`, and **replace** `TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord` (with its comment, `:436-466`) by `TestABufferingTimeoutWithNoAlternateAsksOncePerTimeoutNotOnEveryRecord`.

**Expected red at the seed** (measured; the detector test fails to compile until `Defer` exists, so add an empty `func (d *Detector) Defer() {}` for the red run — a method nothing calls changes no behaviour):

```
detector_test.go:…: 14s after a deferral: got buffering timeout, want buffering -- the timeout was not held back
source_transcode_test.go:…: the resolver was asked 1 times under MAX_STREAM_SWITCHES = 0: the buffering path ignored the bound (#221)
source_transcode_test.go:…: the resolver was asked 29 times under MAX_STREAM_SWITCHES = 1, want 1: the buffering switch was not counted (#221)
source_transcode_test.go:…: asks 0 and 1 were 22.007ms apart, under the 1s buffering_timeout: the channel is asking on every record (#302)
```

(29, not 2, because #302 is unfixed at the seed too: both uncounted switches happen, the resolver's answers run out, and the third source then asks on every record. The break-check below, made with #302 fixed, reads 2.)

### Task 2 specifics

Appendix C: `detector.go` (`retryAt`, the `clock()` helper, `Defer`, `Observe`, `BufferingFor`, `Reset`, the `TimedOut` comment), `channel.go` (the `switches` field and its three accessors, the run loop's five uses), `failover.go` (the budget check and the count in `failoverFromBuffering`), `source_transcode.go` (the `Defer` call on a failed switch), `tuning.go` (the `MaxStreamSwitches` comment).

**Break-checks** (each run on the prototype):

| Wrong edit | Test that reddens | Message |
|---|---|---|
| the budget check in `failoverFromBuffering` disabled (`false &&`) | `TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent`, `TestABufferingFailoverCountsAgainstMaxStreamSwitches` | `asked 1 times under MAX_STREAM_SWITCHES = 0 …`; `asked 2 times under MAX_STREAM_SWITCHES = 1, want 1 …` |
| `c.countSwitch()` removed from `failoverFromBuffering` | `TestABufferingFailoverCountsAgainstMaxStreamSwitches` | `asked 3 times under MAX_STREAM_SWITCHES = 1, want 1 …` |
| `r.detector.Defer()` removed from `source_transcode.go` | `TestABufferingTimeoutWithNoAlternateAsksOncePerTimeoutNotOnEveryRecord` | `asks 0 and 1 were 22.011791ms apart …` |

### Test changes under rule 4

| Test | Before | After |
|---|---|---|
| `TestABufferingFailoverIgnoresMaxStreamSwitches` → **replaced by** `TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent` | with `MaxStreamSwitches = 0`: the channel reaches stream 2, the alternate runs once, state is `active` 300 ms later, exactly one `channel_failover` | with `MaxStreamSwitches = 0`, three `buffering_timeout`s after buffering: zero resolver requests, still on stream 1, alternate never ran, zero `channel_failover`, channel not ended. The setup (corpus, lever, resolver answer) is unchanged, so the only variable is the bound |
| (new) `TestABufferingFailoverCountsAgainstMaxStreamSwitches` | — | with `MaxStreamSwitches = 1` and two answers, both sources slow: exactly one request, channel on stream 2 |
| `TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord` → **replaced by** `TestABufferingTimeoutWithNoAlternateAsksOncePerTimeoutNotOnEveryRecord` | at least 3 requests within 10 s (one per record); state `buffering`; channel not ended | at least 3 requests within 20 s **and every consecutive gap ≥ the 1 s timeout** (a lower bound only); state `buffering` — **kept**; channel not ended — **kept** |
| (new) `TestADeferredTimeoutIsHeldBackForAnotherTimeout` | — | clock-injected: `TimedOut` → `Defer` → `Continuing` at +14 s → `TimedOut` at +15 s; `BufferingFor` keeps the original start; `Ended` clears the hold; then a detector with **no** injected clock: a two-hour-old window times out, and a deferral taken now holds the next ask back (covers `clock()`'s wall-clock branch) |

**Why the #302 test's corpus changed, and why that is not a tolerance.** The seed test replays `slow-trickle` with `--stderr-loop`; every pass re-opens with a record above the threshold, which ends buffering and restarts the clock. Under the defect that did not matter (three asks land inside one pass, tens of milliseconds apart). Under the fix, three asks span two seconds and cross passes, so "state is buffering" would be sampled at an arbitrary point of the loop. The replacement corpus is the capture's own records with its sub-threshold tail repeated four times — a synthetic **order**, not a synthetic line, the same exception `TestBufferingEndsWhenTheSpeedRecovers` (seed `:468-511`) takes with a stated reason — so the channel buffers once and stays buffering, and the seed's state assertion survives unchanged. Measured: 3/3 green, 3.1 s each.

**Unchanged and still true**: `detector_test.go`'s `TestTheDetectorFollowsPythonsTransitions` (a detector nobody defers still repeats `TimedOut`; R2); `failover_test.go`'s `TestMaxStreamSwitchesBoundsAMainLoopSwitch` (the main loop's bound, still ending the channel); `TestASustainedSubThresholdSpeedFailsTheChannelOver` (row 1; its tuning's bound is above zero).

### Task 3 specifics

- **Matrix row 6**, replaced in place:

  ```text
  | 6 | `MAX_STREAM_SWITCHES` bounds buffering-triggered switches as well as the main loop's: a buffering timeout with the budget spent does not ask for a next source, and the channel keeps playing on the slow source rather than ending | `relay/channel/channel.go:<run loop, setState through the needsSwitch branch>`, `relay/channel/failover.go:<failoverFromBuffering>` | `relay/channel/source_transcode_test.go::TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent`, `relay/channel/source_transcode_test.go::TestABufferingFailoverCountsAgainstMaxStreamSwitches`, `relay/channel/failover_test.go::TestMaxStreamSwitchesBoundsAMainLoopSwitch` | Filed as [#221](https://github.com/D10Scot/Dispatcharr/issues/221) and fixed in #<PR>. Python's stderr path called `_try_next_stream()` without touching `stream_switch_attempts`, which only the main loop checked, and the Go relay reproduced that per D5 until stage 2d-4. One counter now serves both paths. What the bound does differs, on purpose: the main loop ends the channel at its bound, having no working source, while the buffering path refuses the switch and keeps a source that is still delivering. So the counts differ by one: the main loop resolves at most `MAX_STREAM_SWITCHES + 1` switches, because its `<=` admits a pass at the bound and the switch it makes there is applied and then ends the channel unrun, while the buffering path makes at most `MAX_STREAM_SWITCHES`, all of which run. The stable-run reset still fires only where the main loop sees an attempt end. The third pin is the main loop's side. |
  ```

  (Prototype spans: `channel.go:455-491`, `failover.go:283-318`.)
- **Rows 1, 3, 4, 5**: shift their `channel.go`, `detector.go` and `source_transcode.go` ranges by this PR's delta (GC 8). Row 29 (`channel.go:120-135`) sits above the new field and does not move.
- **`CLAUDE.md`**: delete the #221 bullet (line 128) and the #302 bullet (line 129). In line 82, replace "the buffering-triggered switch bypasses `MAX_STREAM_SWITCHES` as in Python (row 6)" with "the buffering-triggered switch counts against `MAX_STREAM_SWITCHES` and, once it is spent, is refused rather than fatal (row 6, [#221](https://github.com/D10Scot/Dispatcharr/issues/221))".
- **`defects.yml`**: `max-stream-switches-unbounded` → `fixed` (keep `test`). Append:
  `- {id: buffering-timeout-asks-every-record, title: "A buffering timeout with no alternate asked next-source on every ffmpeg progress record, about twice a second, for as long as the speed stayed low", area: correctness, severity: medium, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 302, test: relay/channel/source_transcode_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-15, status_changed: <date>}`

### Coverage

Every statement A-2 adds is executed by its package's own tests: in `relay/channel` the refusal by the bound-zero test, the count by the bound-one test, the accessors by every run; in `relay/ffmpeg` the hold and the `clock()` helper's both branches by `TestADeferredTimeoutIsHeldBackForAnotherTimeout` (`go tool cover -func`: `clock`, `Observe`, `Defer` at 100%). Measured with A-2 and A-3 together, `relay/channel` went 1063 → 1081 statements and 219 → 219 missing. **A9.2's rule applies** (spec A10's "Go coverage margin" bullet): this PR adds linked statements to `relay/channel`, so read the per-package figure before pushing, not after CI.

### PR description draft

> **fix(relay): bound buffering switches by MAX_STREAM_SWITCHES, and stop asking on every record**
>
> - #221: a buffering-triggered switch never counted against `MAX_STREAM_SWITCHES`. One counter now serves both paths. With the budget spent the buffering path does not ask for a next source and keeps playing the slow one; the main loop still ends the channel at its bound, as before.
> - #302: a buffering timeout with no alternate asked `next-source` on every progress record. The detector now defers the next ask by one `buffering_timeout` and keeps its clock, so a later `channel_failover`'s `duration` is still measured from the start of buffering.
>
> Two defect pins flipped (before/after in the PR's test table), parity-matrix row 6 rewritten. Red at the base, green here, break-checks: <table>.

---

## PR A-3 — `fix/A-3-udp-user-agent-filter`

**Closes #296.** Size S. Upstreamable: no.
**Go package:** `relay/channel`. **Backend labels:** none. **E2E:** path-gated; `fix/` prefix.

### Task 1 specifics

Appendix F. **Replace** `TestTheUDPFilterDropsUserAgentArguments` (with its comment, seed `:566-585`) by `TestTheUDPFilterDropsUserAgentArgumentsWithTheirFlags`, and insert `TestTheUDPFilterLeavesNoDanglingFlag` before `// The argv Django built is what the child receives`.

**Expected red at the seed** (measured):

```
source_transcode_test.go:…: UDP argv = ["-headers" "-i" "udp://239.0.0.1:1234" "-c" "copy" "-f" "mpegts" "pipe:1"], want ["-i" "udp://239.0.0.1:1234" "-c" "copy" "-f" "mpegts" "pipe:1"]
source_transcode_test.go:…: streamlink UDP argv = "udp://239.0.0.1:1234 --http-header best --stdout", want "udp://239.0.0.1:1234 best --stdout"
```

### Task 2 specifics

Appendix E: `argv()` rewritten, `carriesUserAgent` and `isFlag` added (the first is the seed's predicate, moved out so the loop reads plainly; `golangci-lint`'s staticcheck asked for exactly that on the prototype's first draft).

**Break-check**: delete the `case !isFlag(arg) && i > 0 && isFlag(s.Argv[i-1])` arm → both tests redden with the two messages above.

### Test changes under rule 4

| Test | Before | After |
|---|---|---|
| `TestTheUDPFilterDropsUserAgentArguments` → **renamed** `TestTheUDPFilterDropsUserAgentArgumentsWithTheirFlags` | UDP `want` keeps a bare `-headers` before `-i`; the non-UDP branch is untouched | UDP `want` is the same list without `-headers`; the non-UDP assertion is unchanged |
| (new) `TestTheUDPFilterLeavesNoDanglingFlag` | — | the shipped Streamlink parameters on UDP keep `best --stdout`; `-user_agent ""` loses both elements |

### Task 3 specifics

- **Matrix**: no row describes the filter. Row 1's `source_transcode.go` range shifts (GC 8).
- **`CLAUDE.md`**: delete the #296 bullet (line 134).
- **`defects.yml`**: append `- {id: udp-user-agent-dangling-flag, title: "The UDP user-agent filter dropped the argument carrying the user agent and kept the flag before it, so -headers 'User-Agent: X' spawned as a bare -headers and the shipped Streamlink profile's --http-header took best as its value", area: correctness, severity: low, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 296, test: relay/channel/source_transcode_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-14, status_changed: <date>}`

### Coverage

Every new branch is executed by the two tests (the value-takes-flag arm by the first, the flag-takes-value arm by the second's blank case).

### PR description draft

> **fix(relay): the UDP user-agent filter drops a flag with its value**
>
> On a `udp://` upstream the filter dropped each argument carrying the user agent and kept the flag in front of it, so `-headers 'User-Agent: X' -i <url>` spawned as `-headers -i <url>`, and the shipped Streamlink profile spawned as `--http-header best --stdout`. A dropped value now takes its flag, and a dropped flag takes its value. Closes #296.

---

## PR A-4 — `fix/A-4-fmp4-scanner-resync`

**Closes #306; closes #119 as its duplicate.** Size M (it grew from S when round 1 absorbed #348's ceiling). Upstreamable: no.
**Go package:** `relay/output`. **Backend labels:** none. **E2E:** path-gated; `fix/` prefix (`relay/output/` is not in GC 12's list). **The guards project does not run on this PR** (open question 4); no matrix row cites `relay/output/fmp4.go`, so there is nothing for it to catch.

**What round 1 added, from #348's A-4 (attributed in the code comments too).** My first draft fixed the resync arm and left two faults beside it on the aligned path, both present at the seed and both surviving that draft (measured: the two tests below were red against it with only a stub field added). An aligned `moof` whose length is below 8 made `fmp4.go:229-231` return without consuming anything, so every later write grew the buffer and nothing was published again; a length from 8 to 15 was trusted and published as a bogus fragment of its own. And a corrupt length, either the aligned `moof`'s own (`:233-236`) or the next box's after a valid `moof` (`findMoofOffset` returning -1 at `:238-240`), held the buffer open toward a length of up to 4 GiB. #348's `MaxFragmentBytes` ceiling and `minMoofBox = 16` close both. They are adopted here as an unexported constant `maxFragmentBytes` (64 MiB) with a per-scanner `ceiling` field for tests, rather than an exported package `var` a test lowers, so no test can race another scanner's read. The resync candidate floor rises from 8 to 16, because a real `moof` carries an `mfhd` and 8 admits an empty box. The synthetic fragments every scanner test uses carry a 16-byte `moof` (`relaytest/fmp4.go:80-81`), so the floor is compatible with all of them.

### Task 1 specifics

Appendix H. **Replace** `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` (seed `:181-218`) by, in this order: `TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof`, `TestAGarbageRunThatReadsAsALargeLengthDoesNotHideTheNextMoof`, `TestAMoofHeaderSplitAcrossReadsSurvivesAResync`, `TestAMoofLiteralWithAnImplausibleLengthIsNotAResyncPoint`, `TestAMoofShorterThanARealOneDoesNotStallTheBuffer` and `TestAFragmentThatNeverEndsIsAbandonedAtTheCeiling`. Add `"encoding/binary"` and `"fmt"` to the imports.

**Expected red at the seed** (measured). For the red run only, add three compile stubs to `fmp4.go`: `func resyncOffset([]byte, int) int { return -1 }`, `const resyncTail = 7`, and a `ceiling int` field on `scanner`. None of them changes behaviour, since nothing calls or reads them:

```
scanner_test.go:203: 0 fragments published behind a misaligned working buffer, want 1 (fragment 5; 6 is held back): the resync discarded them (#306)
scanner_test.go:220: resyncOffset found the moof at -1, want 1 (#119)
scanner_test.go:252: published 0 fragments, want fragment 0: its header straddled the read and was discarded
scanner_test.go:268: longer than any moof: resyncOffset chose -1, want the real moof at 9
scanner_test.go:298: published 0 fragments behind a 4-byte moof, want fragment 0 alone
scanner_test.go:298: published 2 fragments behind a 12-byte moof, want fragment 0 alone
scanner_test.go:333: the working buffer holds 4112 bytes after write 4, past the 4096-byte ceiling
scanner_test.go:333: the working buffer holds 4120 bytes after write 4, past the 4096-byte ceiling
```

(Line 268 names whichever rejection case the map yields first; every case fails at the seed.)

### Task 2 specifics

Appendix G: the corrected `findMoofOffset` comment; `minMoofBox`, `maxFragmentBytes`, `maxMoofBoxBytes`, `resyncTail`, `resyncOffset`; the `ceiling` field with `fragmentCeiling` and `abandon`; and `flush`'s three changes (a short aligned `moof` is resynchronised past, the tail is kept, and each of the two waits is abandoned past the ceiling).

**Break-checks** (each run on the prototype after round 1):

| Wrong edit | Test that reddens | Message |
|---|---|---|
| the arm calls `findMoofOffset(s.frag, 1)` again | `…ResynchronisesAtTheNextMoof`, `…DoesNotHideTheNextMoof`, and both new tests | `0 fragments published behind a misaligned working buffer …`; `published 0 fragments after two garbage bytes, want fragment 0 alone (#119)` |
| the tail replaced by `s.frag = s.frag[:0]` | `TestAMoofHeaderSplitAcrossReadsSurvivesAResync` | `published 0 fragments, want fragment 0: its header straddled the read and was discarded` |
| the `size <= maxMoofBoxBytes` bound removed | `TestAMoofLiteralWithAnImplausibleLengthIsNotAResyncPoint` | `resyncOffset chose 1, want the real moof at 9` |
| the floor lowered to `size >= 8` | `TestAMoofLiteralWithAnImplausibleLengthIsNotAResyncPoint` | `#119's empty moof, 8 bytes: resyncOffset chose 1, want the real moof at 9` |
| `\|\| size < minMoofBox` removed from the misaligned test | `TestAMoofShorterThanARealOneDoesNotStallTheBuffer` | `published 0 fragments behind a 4-byte moof …`; `published 2 fragments behind a 12-byte moof …` |
| the ceiling check in the `size > len(s.frag)` arm disabled | `TestAFragmentThatNeverEndsIsAbandonedAtTheCeiling/the moof's own length is corrupt` **only** | `the working buffer holds 4112 bytes after write 4 …` |
| the ceiling check in the `findMoofOffset == -1` arm disabled | `TestAFragmentThatNeverEndsIsAbandonedAtTheCeiling/the box after the moof is corrupt` **only** | `the working buffer holds 4120 bytes after write 4 …` |

The last two rows are why the ceiling test has two shapes: each arm is reached by exactly one of them.

### Test changes under rule 4

| Test | Before | After |
|---|---|---|
| `TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised` → **replaced by** `TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof` | same input (a 72-byte `junk` box, fragments 5 and 6): zero fragments published, head 0 | same input: one fragment published, carrying index 5 (6 held back as every newest fragment is) |

The other five are new. **#119's literal counterexample** (one garbage byte before an *empty* 8-byte `moof`) is now a **rejection** case, because the 16-byte floor refuses an empty box on purpose. Its finder assertion runs on one garbage byte before a real 16-byte `moof`, and its scanner-level form is two garbage bytes, since a one-byte prefix resynchronises even at the seed. Unchanged: `TestABoxLengthBelowEightAdvancesOneByteRatherThanGivingUp` (it tests `findMoofOffset` directly, which R6 leaves alone), `TestABoxBetweenTwoFragmentsIsCarriedInsideThePrecedingOne`, `TestABoxLongerThanWhatHasArrivedIsNotAFragmentYet` (below the ceiling the wait is unchanged), `TestTheSameBytesSplitAcrossReadsProduceTheSameFragments`, `TestTenMegabytesWithNoMoofAborts`.

### Task 3 specifics

No matrix row cites `relay/output/fmp4.go`, no `CLAUDE.md` line names #306 or #119, and neither is a ledger item (R11). Also run `go test -race -run 'FMP4|Profile' ./httpapi/`, the fMP4 end-to-end rigs that drive this scanner (prototype: green).

### Coverage

`relay/output` measured 243 → 261 statements and 15 → 12 missing. `go tool cover -func` shows `findMoofOffset`, `fragmentCeiling`, `abandon`, `write` and `flush` at 100% and `resyncOffset` at 100% (its trailing `return -1` is reached by the rejection test's "nothing after it" assertion, added for that reason).

### PR description draft

> **fix(relay): the fMP4 scanner resynchronises instead of discarding its buffer, and cannot grow without bound**
>
> When the working buffer did not start at a `moof`, the scanner searched from offset 1 with the box-striding scanner, read a length at a one-byte shift, jumped past every box, got -1 and cleared the whole buffer, fragments and all. It now searches for the next `moof` literal whose length is plausible (16 bytes to 1 MiB), and with nothing found keeps only the seven bytes a split header could start in. The aligned scans still stride, which is what keeps a `moof` inside an `mdat` from being taken for a box. Two adjacent faults are closed too, following #348's design. An aligned `moof` shorter than a real one no longer stalls the buffer. A fragment whose end cannot be found, because its own length or its successor's is corrupt, is abandoned past 64 MiB instead of buffering toward 4 GiB. Closes #306; closes #119, the same defect found by fuzzing, whose counterexample is kept as a regression example.

---

## PR A-5 — `migration/A-5-fmp4-client-timeout`

**Closes #222.** Size M. Upstreamable: no.
**Go package:** `relay/httpapi`. **Backend labels:** none. **E2E:** `migration/` prefix (GC 12): the full matrix runs, which is what an `relay/httpapi/` change to a client loop should face.

### Task 1 specifics

Appendix J. **Replace** `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` (with its comment, seed `:356-465`, the end of the file) by `TestAStalledFMP4ClientOnAHealthyChannelStaysConnectedLikeATSClient` followed by `TestAnFMP4ClientOnAnUnhealthyStallIsDroppedAtTheKeepaliveCap`.

**Expected red at the seed** (measured, seed `fmp4.go` with the new tests):

```
fmp4_test.go:…: the fMP4 client was dropped (16776 bytes sent) on a HEALTHY channel inside 6s: the loop timed it out on elapsed time alone (#222)
fmp4_test.go:…: the fMP4 client was dropped 193.067375ms after the channel went unhealthy, before the 2s keepalive cap: stream_timeout + failover_grace_period ended it (#222)
```

### Task 2 specifics

Appendix I: the doc comment rewritten (R3), `lastYield` replaced by `stallStart`, the empty-wait branch gated on health and capped by `MaxKeepalive`.

**Break-checks** (each run on the prototype):

| Wrong edit | Test that reddens | Message |
|---|---|---|
| the `if ch.Healthy() { continue }` gate removed | `…OnAHealthyChannelStaysConnectedLikeATSClient` | `dropped (16776 bytes sent) on a HEALTHY channel inside 6s …` (its compressed `MAX_KEEPALIVE_DURATION` of 1 s is what makes this edit visible) |
| `tuning.MaxKeepalive` replaced by `tuning.ClientTimeout` | `…DroppedAtTheKeepaliveCap` | `dropped 552.222834ms after the channel went unhealthy, before the 2s keepalive cap …` |
| the seed's whole `fmp4.go` | both | the two red messages above |

### Test changes under rule 4

| Test | Before | After |
|---|---|---|
| `TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` → **replaced by** `TestAStalledFMP4ClientOnAHealthyChannelStaysConnectedLikeATSClient` | stall with `STREAM_TIMEOUT` 1 + `FAILOVER_GRACE_PERIOD` 1: the fMP4 body ends within 30 s and no sooner than 2 s, the channel is healthy, `Clients() == 1` | same compression plus `MAX_KEEPALIVE_DURATION` 1: the fMP4 body is **still open** after 3 × 2 s, the channel is healthy, `Clients() == 2`. **The remux stand-in changes from 200 fragments at 20 ms to 5 at once**: the stand-in ignores its input, so 200 fragments fed the fMP4 client for four seconds of a six-second window, and the prototype's first draft passed with the defect's elapsed-time drop re-inserted. Five fragments starve the client from its first second, which is the stall the test's name describes. |
| (new) `TestAnFMP4ClientOnAnUnhealthyStallIsDroppedAtTheKeepaliveCap` | — | `CONNECTION_TIMEOUT` 0.3, client timeout 0.5, cap 2: the fMP4 client is not dropped while the channel is healthy, is dropped no sooner than 2 s after the last healthy observation and within 6 s, and the TS client ends too |

**The unhealthy test's clock** is read *before* the last `Healthy()` call that returned `true`, so the flip, and the cap's clock that cannot start before it, both come after it and the measured gap is never shorter than the real one. The prototype's first draft read it after the poll's 10 ms wait and measured **1.99 s against a 2 s cap once in a full package run under `-race`**: the flip had landed inside the wait. Three repeats of the corrected test, 29.4 s each; most of that is teardown waiting on the control-plane hold, as `TestAClientIsDroppedOnceTheKeepaliveCapIsReached` (18 s) already does.

### Task 3 specifics

- **Matrix row 12**, replaced in place:

  ```text
  | 12 | An fMP4 client leaves by the exit a TS client reaches: on a healthy channel a stall never times it out, and on an unhealthy one it is dropped once `MAX_KEEPALIVE_DURATION` passes with nothing to send, not `stream_timeout + failover_grace_period` into the stall | `relay/httpapi/fmp4.go:<doc comment through the loop>`, `relay/httpapi/stream.go:1005-1031` | `relay/httpapi/fmp4_test.go::TestAStalledFMP4ClientOnAHealthyChannelStaysConnectedLikeATSClient`, `relay/httpapi/fmp4_test.go::TestAnFMP4ClientOnAnUnhealthyStallIsDroppedAtTheKeepaliveCap` | Filed as [#222](https://github.com/D10Scot/Dispatcharr/issues/222) and fixed in #<PR>. Python's fMP4 `_is_timeout()` dropped a client on elapsed time since its last fragment alone, with no health check, no `url_switching` exemption and no keepalive, 40s into any stall including a slow failover, while a TS viewer on the same channel stayed. 2a-6 found the TS side's reachable exit is the keepalive cap, because each keepalive refreshes the timer its client timeout reads. The fMP4 loop now takes that exit without writing keepalive bytes, since an fMP4 stream has no null packet a player is known to skip. Neither loop ports the `url_switching` exemption, which the keepalive shadows. |
  ```

  (Prototype span: `fmp4.go:112-239`.)
- **`CLAUDE.md`**: delete the #222 bullet (line 130).
- **`defects.yml`**: `fmp4-timeout-no-switch-exemption` → `fixed` (keep `test`).

### Coverage

`relay/httpapi`'s new statements (the gate, the clock, the cap) are executed by the two tests; the deleted `lastYield` statements were covered. Measured 126 → 111 missing, a move dominated by run-to-run spread rather than this change; read the per-function figures (Task 4), not the package total.

### PR description draft

> **fix(relay): an fMP4 viewer is no longer dropped 40s into a stall a TS viewer survives**
>
> The fMP4 client loop dropped a client on elapsed time since its last fragment alone, so a slow failover that a TS viewer rode out ended an fMP4 viewer at `stream_timeout + failover_grace_period`. It now leaves by the exit the TS loop reaches: never on a healthy channel, and on an unhealthy one once `MAX_KEEPALIVE_DURATION` passes with nothing to send. No keepalive bytes are written into the fMP4 stream. Parity-matrix row 12 and its pin are rewritten; before/after in the PR's test table. Closes #222. Runs the full E2E matrix (`migration/` prefix).

---

## PR A-6 — `migration/A-6-detail-ffmpeg-bitrate`

**Closes #314.** Size S. Upstreamable: no.
**Go package:** `relay/httpapi`. **Backend label:** `apps.proxy.tests`. **Gate 2:** yes (GC 7). **E2E:** `migration/` prefix (GC 12).

### Task 1 specifics

- **Python.** In `apps/proxy/tests/test_relay_detail_payload_golden.py` (Appendix K's third file): empty `NEVER_WRITTEN` with its new comment, and add `"ffmpeg_bitrate": "4200.0"` to `fixture()` after `actual_fps`. Run `apps.proxy.tests.test_relay_detail_payload_golden` in your container: **red** at the seed, measured as `FAILED (failures=2)`: `test_the_golden_file_is_what_the_serializer_renders` ("relay/httpapi/testdata/channel_detail.json has drifted from what RelayChannelDetailSerializer renders") and `test_the_fixture_covers_every_serializer_field` ("…neither in the fixture nor in NEVER_WRITTEN with a reason: ['source_bitrate']").
- **Go.** Appendix L. In `detail_golden_test.go`: add `FFmpegBitrate: "4200.0",` after `ActualFPS` in `detailGoldenPayload()`, and **replace** `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` (with its comment, seed `:216-245`) by `TestTheDetailPayloadCarriesTheFFmpegOutputBitrate`. In `transcode_test.go`: insert `TestTheDetailEndpointCarriesTheFFmpegOutputBitrate` before `// PARITY-MATRIX ROW 29`; add `"math"`, `"regexp"` and `"strconv"` to its imports. For the red run declare the struct field alone (`FFmpegBitrate string `+"`json:"ffmpeg_bitrate,omitempty"`"+` after `ActualFPS`; a field nothing assigns renders nothing). Red at the seed (measured): `detail_golden_test.go:164: this relay's detail payload differs from the one Django's RelayChannelDetailSerializer renders …`, `detail_golden_test.go:230: ffmpeg_bitrate on the detail golden is <nil> (<nil>) …`, `transcode_test.go:205: ffmpeg_bitrate = <nil> (<nil>), want "506.0": the parsed output bitrate did not reach the detail payload (#314)`.

### Task 2 specifics

- **Go**: Appendix K's `detail.go` hunks (the field, the assignment, the comment).
- **Python**: Appendix K's `relay_serializers.py` hunk (delete `source_bitrate`).
- **Regenerate the golden** from Django's serializer, never by hand: the testrunner mounts `/repo` read-only, so use 2c-8's base64 recipe (`docs/superpowers/plans/2026-09-13-phase2-2c8-control-drain.md:594-607`) against your container, or run `DISPATCHARR_WRITE_GOLDEN=1 … manage.py test apps.proxy.tests.test_relay_detail_payload_golden` against a **writable** copy and `docker cp` the file out. Read the diff: it must add exactly `"ffmpeg_bitrate": "4200.0"` and nothing else (the prototype's regenerated golden differed from the seed's by that one key).
- Run `apps.proxy.tests` whole in your container (prototype: 380 OK), then `relay/httpapi` under `-race`.

**Break-checks** (each run on the prototype):

| Wrong edit | Test that reddens | Message |
|---|---|---|
| the `out.FFmpegBitrate = …` assignment removed | `TestTheDetailEndpointCarriesTheFFmpegOutputBitrate` | `ffmpeg_bitrate = <nil> (<nil>), want "506.0": the parsed output bitrate did not reach the detail payload (#314)` |
| `source_bitrate = serializers.CharField(required=False)` restored | `test_the_fixture_covers_every_serializer_field` | `these RelayChannelDetailSerializer fields are neither in the fixture nor in NEVER_WRITTEN with a reason: ['source_bitrate']` |

### Test changes under rule 4

| Test | Before | After |
|---|---|---|
| `TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites` → **replaced by** `TestTheDetailPayloadCarriesTheFFmpegOutputBitrate` | `source_bitrate` and `ffmpeg_bitrate` both absent from the payload; `video_bitrate`, `audio_bitrate`, `avg_bitrate` present | `ffmpeg_bitrate` present on the golden as a non-empty string. The neighbour-presence assertions are **not lost**: `TestTheDetailPayloadMatchesDjangosSerializer` compares the whole payload, neighbours included, against the golden. `source_bitrate`'s absence moves to the Python completeness test, which is the only place it can fail — a golden rendered from a fixture that never sets a key cannot tell whether the serializer still declares it |
| Python `NEVER_WRITTEN` | two entries with reasons | empty, with the comment saying why; `test_the_fixture_covers_every_serializer_field`'s assertions are unchanged |
| Python `fixture()` | no `ffmpeg_bitrate` | `"ffmpeg_bitrate": "4200.0"` |
| `detailGoldenPayload()` (Go) | no `FFmpegBitrate` | `FFmpegBitrate: "4200.0"` |

### Task 3 specifics

- **Matrix**: no row describes these fields. Rows 18 and 28 cite `detail.go` ranges below the edited comment and shift (GC 8); row 14's `:10-25` (the import block) does not.
- **`CLAUDE.md`**: delete the #314 bullet (line 136).
- **`defects.yml`**: append `- {id: detail-bitrate-fields-unwritten, title: "GET /proxy/ts/status/<uuid> declared source_bitrate, which nothing wrote, and ffmpeg_bitrate, which the relay parsed and never rendered", area: correctness, severity: low, status: fixed, source: "CLAUDE.md#known-defects-and-traps", issue: 314, test: relay/httpapi/transcode_test.go, fixed_in: <PR>, carried_as: null, first_seen: 2026-09-15, status_changed: <date>}`

### Coverage

Go: one covered `if` in `describeChannel`. Gate 2: one covered declaration removed from `relay_serializers.py`; run `scripts/coverage_live_path_isolated.sh` before pushing (GC 7).

### PR description draft

> **fix(relay): the channel detail endpoint reports the ffmpeg output bitrate**
>
> `ffmpeg_bitrate` was read under one constant and written under another in the Python relay, so it never reached `GET /proxy/ts/status/<uuid>`; the Go relay parsed the value and dropped it at the renderer. It is now rendered, as a string like the endpoint's other rates. `source_bitrate`, which the serializer declared and nothing in either relay ever wrote, is removed from the serializer: ffmpeg reports `bitrate: N/A` for a live input, and no client reads the field. The golden is regenerated from Django's serializer. Closes #314. Runs the full E2E matrix (`migration/` prefix).

---

## PR A-7 — `fix/A-7-stream-hash-events`

**Closes #233.** Size S. Upstreamable: no.
**Backend label:** `core.tests`. **Go package:** `relay/channel` (one test). **E2E:** path-gated; `fix/` prefix.

### Task 1 specifics

- **Python**: Appendix N's test hunk — insert `test_a_stream_hash_tune_raised_no_lifecycle_rows` and `test_a_uuid_channel_id_is_not_mistaken_for_a_stream_hash` into `EventBatchWritesSystemEventRowsTests` before `test_an_unknown_event_type_is_counted_as_rejected_not_raised`. Run `core.tests.test_relay_events` in your container. **Red at the seed** (measured):

```
ERROR core.utils Failed to log system event channel_start: ['"9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08" is not a valid UUID.']
ERROR core.utils Failed to log system event channel_stop: [... is not a valid UUID.']
ERROR: test_a_stream_hash_tune_raised_no_lifecycle_rows (… SystemEvent.DoesNotExist)
```

  The second test passes at the seed; it is the guard that the fix does not reclassify a real channel.
- **Go**: Appendix O — append `TestAStreamHashTuneNamesItsHashAsTheEventChannelID` to `relay/channel/manager_test.go`. It **passes at the seed**, by design: it pins the relay property Django's fix depends on (the identifier passes through verbatim), and no relay code changes (R5). Its two break-checks, each run on the prototype: `emit`'s literal (`events.go:38`) set to `ChannelID: c.channelName` → `channel_start named channel "Test Channel", want the stream hash it was tuned by, verbatim`; `emitStop`'s `ChannelID: c.id` (`channel.go:651`) set to `strings.ToUpper(c.id)` → `channel_stop named channel "9F86D081…", want the stream hash …`.

### Task 2 specifics

Appendix M: `_channel_uuid` and its one call site in `apply_event_batch`. Run `core.tests` whole (prototype: 107 OK).

**Break-check**: make `_channel_uuid` return `value` unconditionally → `test_a_stream_hash_tune_raised_no_lifecycle_rows` reddens with the seed's `DoesNotExist` and the two `Failed to log system event` lines.

### Test changes under rule 4

None changed; three added (two Python, one Go).

### Task 3 specifics

No matrix row (the matrix is the relay's behaviour, and the relay's is unchanged), no `CLAUDE.md` bullet names #233, no ledger row (R11). **Behaviour worth one line in the PR body**: the WebSocket push for a hash tune's `stream_switch`/`channel_failover`/`client_disconnect` already carried the hash as `channel_id` before this PR (`_push` reads the posted event, and ran even when the row write failed); that is unchanged.

### Coverage

`core/relay_events.py` is not in Gate 2. The Go test adds no statements.

### PR description draft

> **fix(core): a stream-by-hash preview tune records its lifecycle events**
>
> `/proxy/ts/stream/<stream_hash>`, the admin single-stream preview, is tuned by a Stream's sha256 hash, and the relay posts that identifier as each event's `channel_id`. `SystemEvent.channel_id` is a UUIDField, so every event of a preview tune raised inside `log_system_event` and was swallowed: no row, no Connect fan-out. `core/relay_events.py` now applies the rule `get_stream_object` already applies — not a UUID means a stream hash — and writes the row with no channel and the hash in `details["stream_hash"]`. The relay is unchanged; a Go test pins that it passes the identifier through verbatim, which is what this relies on. Closes #233.

---

## Decision memos

None. Category A holds none of the brief's rule-4 policy items (#82, #94, #16, #277, #109, #133).

## Coverage table

| Issue | Where |
|---|---|
| #24 | PR A-1 |
| #119 | PR A-4 (closed as duplicate of #306) |
| #221 | PR A-2 |
| #222 | PR A-5 |
| #227 | PR A-1 |
| #233 | PR A-7 |
| #296 | PR A-3 |
| #299 | PR A-1 |
| #302 | PR A-2 |
| #306 | PR A-4 |
| #314 | PR A-6 |

## Open questions

Each has a recommended answer the plan already follows; the implementation needs a ruling only if the user wants the other one.

1. **#221 — what a spent budget does on the buffering path (R1).** The plan refuses the switch and keeps the slow source playing. The alternative is the main loop's behaviour, ending the channel. Two consequences the user should know, both of sharing one counter. Once buffering switches have spent the budget, the next dead-air or connect-failure failover is the main loop's last: it switches and then ends the channel, exactly as if the main loop had made the earlier switches itself. And the budget refills only when the main loop sees an attempt end after `STABLE_CONNECTION_THRESHOLD` (30 s default); a buffering-cancelled attempt never counts as stable, so a long-lived channel whose sources only ever degrade slowly can spend all ten switches and keep none for the rest of that tune. Refilling on some other signal (a quiet period with no buffering, say) is a design the issue does not ask for.
2. **#222 — the fMP4 exit (R3).** The plan drops an fMP4 client on an unhealthy channel after `MAX_KEEPALIVE_DURATION` (300 s default) with no bytes sent. The smaller alternative keeps the old `stream_timeout + failover_grace_period` (40 s) but gates it on health, which fixes the stalled-remux case and still drops fMP4 viewers 40 s into a slow failover that TS viewers survive. A third option writes top-level `free` boxes as keepalives, which would need a player-compatibility check this repository cannot run.
3. **#314 — `source_bitrate` (R4).** The plan deletes it from the serializer. The alternatives are to keep it declared and absent (no behaviour change, and the Python golden keeps an excuse entry forever) or to give it a writer from ffmpeg's input `bitrate:` field, which reads `N/A` for live inputs.
4. **The guards project does not run on a relay-only PR.** `e2e-tests.yml:110`'s path pattern has no `relay/` prefix, and the guards trigger (`:127-133`) adds only `docs/relay-parity-matrix.md`. So a PR touching nothing but `relay/` can move a line a matrix row cites and pass PR CI, and the guard then fails on `main`. Raised by #348 and the round-1 review. **In this plan it reaches only A-4**, not A-3 as the review first had it: A-3 shifts row 1's `source_transcode.go:320-341` citation (its `argv()` rewrite adds lines above it), so it edits the matrix and triggers the guard. A-1, A-2, A-5 and A-6 edit the matrix, A-6 also edits `apps/`, and A-7 edits `core/`. A-4 edits only `relay/output/`, and no row cites `relay/output/fmp4.go` (`grep -c` is 0 at the seed), so nothing the guard checks can move. Every A PR still runs the guard locally (GC 9). The workflow's missing prefix is a one-line fix outside category A's issues, for the lead to route (category G owns workflows).

---

## Appendices

Every diff below is the prototype's `diff -u` against the seed (Appendix E against the tree after A-2), relabelled `a/`/`b/` so `git apply` (or `patch -p1`) applies it from the worktree root. Applied with `git apply` in the order A, C, E, G, I, K, M, N to a fresh seed export, they reproduce the prototype byte for byte. Every Go block is the prototype's final test function, extracted verbatim; placement is in each PR's Task 1. The timestamps `diff` prints have been dropped.

### Appendix A — A-1 production: `progress.go`, `spawn.go`, `relaytest/corpus.go`

```diff
--- a/relay/ffmpeg/progress.go
+++ b/relay/ffmpeg/progress.go
@@ -22,22 +22,38 @@
 	OutputBitrateKbps *float64
 }
 
-// The three regexes, input/manager.py:1109, :1113 and :1117, verbatim.
+// The three regexes. fpsRe and bitrateRe are input/manager.py:1113 and :1117
+// verbatim.
 //
-// speedRe STOPS AT THE 'e' OF SCIENTIFIC NOTATION, and that is parity-matrix
-// row 28 (issue #227): real ffmpeg emits "speed=1.41e+03x" on a truncated
-// input and both status surfaces then report 1.41, a thousandfold
-// under-report. Spec D5 is strict parity, defects included; do not widen the
-// character class without changing the Python side and the row together.
+// speedRe READS AN EXPONENT, and that is parity-matrix row 28 (issue #227,
+// fixed): real ffmpeg emits "speed=1.41e+03x" on a truncated input, and the
+// Python relay's `[0-9.]+` (input/manager.py:1109) stopped at the 'e' and
+// reported 1.41, a thousandfold under-report on both status surfaces.
+// fpsRe keeps the narrow class: ffmpeg is not observed to print a frame rate
+// in scientific notation, and a speculative widening is a change with no
+// capture behind it.
 var (
-	speedRe   = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)
+	speedRe   = regexp.MustCompile(`speed=\s*([0-9.]+(?:[eE][-+]?[0-9]+)?)x?`)
 	fpsRe     = regexp.MustCompile(`fps=\s*([0-9.]+)`)
 	bitrateRe = regexp.MustCompile(`(?i)bitrate=\s*([0-9.]+(?:\.[0-9]+)?)\s*([kmg]?)bits/s`)
 )
 
-// IsProgressLine is the gate input/manager.py:993 and :1017 apply before
-// calling _parse_ffmpeg_stats: the substring "frame=" anywhere in the line.
-func IsProgressLine(line string) bool { return strings.Contains(line, "frame=") }
+// IsProgressLine is the gate in front of ParseProgress.
+//
+// input/manager.py:993 and :1017 required the substring "frame=", and that
+// is blind on ffmpeg 6.x (issue #299): a stream-copy progress record there
+// begins "size=" and carries no frame= at all
+// ("size=      19kB time=00:00:01.06 bitrate= 148.5kbits/s speed=2.01x"),
+// so no speed was ever recorded and the buffering detector could never arm.
+// 7.1, 8.1.2 (the shipped ffmpeg) and 9.0 lead with frame= and pass the first
+// clause; ffmpeg 6.x passes the second. Lines arrive trimmed (emit), so the
+// prefix test sees the record's first token.
+func IsProgressLine(line string) bool {
+	if strings.Contains(line, "frame=") {
+		return true
+	}
+	return (strings.HasPrefix(line, "size=") || strings.HasPrefix(line, "Lsize=")) && strings.Contains(line, "speed=")
+}
 
 // ParseProgress extracts the four values from a progress record.
 //
--- a/relay/ffmpeg/spawn.go
+++ b/relay/ffmpeg/spawn.go
@@ -223,6 +223,10 @@
 // PID is the process id, for tests and logs.
 func (p *Process) PID() int { return p.cmd.Process.Pid }
 
+// maxStderrLine is the most ReadStderr holds without a terminator before it
+// flushes the buffer as a line regardless of what it carries (issue #24).
+const maxStderrLine = 64 << 10
+
 // ReadStderr drains fd 2 to EOF, calling fn for every line.
 //
 // THE SPLIT IS input/manager.py:981-1003's: whichever of CR or LF comes
@@ -234,6 +238,13 @@
 // as a line (:986-991), which is how a long diagnostic with no newline still
 // reaches the log rather than waiting for the next record.
 //
+// A BUFFER PAST maxStderrLine IS FLUSHED WHATEVER IT CARRIES (issue #24).
+// The 1 KiB rule exempts a buffer containing "frame=" so a progress record is
+// never cut in half -- and Python applied nothing else, so a child writing
+// "frame=" with no CR or LF grew the buffer until EOF, without bound, in the
+// process that carries every live viewer. A real record is a few hundred
+// bytes; nothing that long is one.
+//
 // It never returns an error: a broken stderr pipe means the process is
 // going, and Wait is where that is reported.
 func (p *Process) ReadStderr(fn func(line string)) {
@@ -251,7 +262,7 @@
 				cr := bytes.IndexByte(buf, '\r')
 				nl := bytes.IndexByte(buf, '\n')
 				if cr == -1 && nl == -1 {
-					if len(buf) > 1024 && !bytes.Contains(buf, []byte("frame=")) {
+					if len(buf) > maxStderrLine || (len(buf) > 1024 && !bytes.Contains(buf, []byte("frame="))) {
 						emit(fn, buf)
 						buf = buf[:0]
 					}
--- a/relay/internal/relaytest/corpus.go
+++ b/relay/internal/relaytest/corpus.go
@@ -26,8 +26,11 @@
 // the digits are a timing measurement, only the SHAPE is asserted -- binds
 // these tests.
 
-// CorpusNames are the three captures.
-var CorpusNames = []string{"normal", "slow-trickle", "truncation"}
+// CorpusNames are the captures: three from the shipped ffmpeg 8.1.2, and two
+// from ffmpeg 6.1.1 (issue #299), whose stream-copy progress records begin
+// size= and carry no frame= at all. CorpusSpeeds panics on the 6.1.1 pair --
+// each opens with a speed=N/A record -- so read those through SplitCorpus.
+var CorpusNames = []string{"normal", "slow-trickle", "truncation", "ffmpeg6-normal", "ffmpeg6-slow-trickle"}
 
 // pkgDir is this file's own directory, from its compiled-in path.
 //
@@ -104,10 +107,12 @@
 // The PRODUCTION speed regex, copied deliberately rather than imported from
 // package ffmpeg: these helpers exist so a test can quote what the shipped
 // parser sees, and importing the parser would make the quote move if the
-// parser moved. Same rationale, and the same literal, as
-// apps/proxy/live_proxy/tests/manager_support.py:24.
+// parser moved. The copy must therefore move WITH it, by hand: issue #227's
+// fix widened package ffmpeg's speedRe to read an exponent, and this literal
+// was widened in the same PR so the two agree on a scientific-notation
+// record.
 var (
-	corpusSpeedRe   = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)
+	corpusSpeedRe   = regexp.MustCompile(`speed=\s*([0-9.]+(?:[eE][-+]?[0-9]+)?)x?`)
 	corpusElapsedRe = regexp.MustCompile(`elapsed=(\d+):(\d\d):(\d\d(?:\.\d+)?)`)
 )
 
```

### Appendix B — A-1 tests (`progress_test.go`, `spawn_test.go`, `source_transcode_test.go`, new `relaytest/corpus_test.go`)

```go
// progress_test.go: replaces the seed's single `var fullSpeedRe = ...` (:11-13)
var (
	fullSpeedRe     = regexp.MustCompile(`speed=\s*([0-9.]+(?:[eE][+-]?[0-9]+)?)x?`)
	mantissaSpeedRe = regexp.MustCompile(`speed=\s*([0-9.]+)`)
)

// Issue #227, parity-matrix row 28: FIXED. The truncation capture's one
// record reads speed=<mantissa>e+03x on a real ffmpeg 8.1.2, and the parser
// reports the whole value -- the Python relay's `[0-9.]+` stopped at the 'e'
// and reported the mantissa, a roughly thousandfold under-report on both
// status surfaces. Reddens if the character class is narrowed back.
func TestAScientificNotationSpeedIsReadWithItsExponent(t *testing.T) {
	_, records := relaytest.SplitCorpus(relaytest.Corpus("truncation"))
	if len(records) != 1 {
		t.Fatalf("the truncation capture carries %d records, want exactly 1 (CAPTURE.md)", len(records))
	}
	record := string(records[0])
	actual, _ := strconv.ParseFloat(fullSpeedRe.FindStringSubmatch(record)[1], 64)
	mantissa, _ := strconv.ParseFloat(mantissaSpeedRe.FindStringSubmatch(record)[1], 64)
	if actual/mantissa < 100 {
		t.Fatalf("the truncation capture no longer carries a scientific-notation speed=; "+
			"re-derive this test against the new capture (CAPTURE.md): %q", record)
	}

	p, ok := ParseProgress(record)
	if !ok || p.Speed == nil {
		t.Fatalf("the record did not parse as progress: %q", record)
	}
	if *p.Speed != actual {
		t.Fatalf("Speed = %v, want the whole value %v (the mantissa alone is %v: issue #227)", *p.Speed, actual, mantissa)
	}
}

// ISSUE #299: ffmpeg 6.x's stream-copy progress record begins size= and
// carries no frame=, so the frame= gate saw none of them and no speed was
// ever recorded. Every record of the real 6.1.1 capture is now a progress
// record, and every one whose speed is a number yields it.
func TestAnFFmpeg6StreamCopyRecordIsAProgressRecord(t *testing.T) {
	_, records := relaytest.SplitCorpus(relaytest.Corpus("ffmpeg6-normal"))
	if len(records) < 3 {
		t.Fatalf("the ffmpeg6-normal capture carries %d records; re-derive (CAPTURE.md)", len(records))
	}
	speeds := 0
	for _, raw := range records {
		record := strings.TrimSpace(string(raw))
		if strings.Contains(record, "frame=") {
			t.Fatalf("the 6.1.1 capture carries frame=, so it no longer exercises #299: %q", record)
		}
		if !IsProgressLine(record) {
			t.Fatalf("a real ffmpeg 6.1.1 progress record is not a progress line (#299): %q", record)
		}
		if p, ok := ParseProgress(record); ok && p.Speed != nil {
			speeds++
		}
	}
	if speeds != len(records)-1 {
		t.Fatalf("%d of %d records yielded a speed, want all but the opening speed=N/A", speeds, len(records))
	}
}

// ISSUE #24: a child that writes "frame=" with no CR or LF must not grow the
// reader's buffer without bound. The 1 KiB flush exempts a buffer containing
// frame= so a progress record is never cut, and before the fix nothing else
// bounded it: 2 MiB of such output reached fn as ONE 2 MiB line at EOF, held
// in memory the whole way. Driven through ReadStderr itself over an in-memory
// pipe, no child process, so the only variable is the splitter.
func TestAnUnterminatedFrameRecordCannotGrowTheReaderWithoutBound(t *testing.T) {
	const total = 2 << 20
	chunk := bytes.Repeat([]byte("frame=  1 "), 4096/10)
	var input []byte
	for len(input) < total {
		input = append(input, chunk...)
	}
	p := &Process{stderr: io.NopCloser(bytes.NewReader(input))}
	var lines []string
	p.ReadStderr(func(line string) { lines = append(lines, line) })

	delivered := 0
	for _, l := range lines {
		if len(l) > maxStderrLine+4096 {
			t.Fatalf("a %d-byte line reached the callback: the buffer grew past maxStderrLine (%d) plus one read", len(l), maxStderrLine)
		}
		delivered += len(l)
	}
	if len(lines) < 2 {
		t.Fatalf("%d lines from %d unterminated bytes, want the buffer flushed repeatedly", len(lines), len(input))
	}
	// Nothing is dropped: the cap flushes, it does not truncate. Trimming
	// removes at most the trailing space of each flushed line.
	if delivered < len(input)-len(lines) {
		t.Fatalf("%d of %d bytes were delivered: the cap discarded output instead of flushing it", delivered, len(input))
	}
}

// ISSUE #299 at the channel: a transcode source whose ffmpeg is 6.x -- a
// user-supplied Stream Profile pointing at a system ffmpeg -- arms the
// buffering detector. The stand-in replays the real 6.1.1 slow-trickle
// capture with the threshold at the API maximum, above every record; before
// the fix the frame= gate dropped every record and the state never moved.
func TestAnFFmpeg6StreamCopyArmsTheBufferingDetector(t *testing.T) {
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("ffmpeg6-slow-trickle"), "--stderr-interval", "0.02")
	ch, release := attachTranscode(t, m, "ffmpeg6", src, transcodeTuning(apiMax, 300*time.Second))
	defer release()
	waitFor(t, "a speed reported off a 6.1.1 record", 10*time.Second, func() bool { return ch.Stats().FFmpegSpeed != nil })
	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	m.Stop("ffmpeg6")
}

// Issue #227, the test-support half. CorpusSpeeds quotes the shipped parser's
// speed regex by copy, so the copy has to read the truncation capture's
// exponent exactly as package ffmpeg now does; a copy left at `[0-9.]+`
// would hand every caller the mantissa, about a thousandth of the value,
// while the parser under test reads the whole of it.
func TestCorpusSpeedsReadsAScientificNotationSpeedWhole(t *testing.T) {
	speeds := CorpusSpeeds("truncation")
	if len(speeds) != 1 {
		t.Fatalf("the truncation capture carries %d records, want exactly 1 (CAPTURE.md)", len(speeds))
	}
	if speeds[0] < 100 {
		t.Fatalf("CorpusSpeeds read the truncation record as %v, its mantissa: the copied regex has fallen behind package ffmpeg's (#227)", speeds[0])
	}
}
```

### Appendix C — A-2 production: `detector.go`, `channel.go`, `failover.go`, `tuning.go`, `source_transcode.go`

```diff
--- a/relay/ffmpeg/detector.go
+++ b/relay/ffmpeg/detector.go
@@ -27,6 +27,9 @@
 
 	buffering bool
 	since     time.Time
+	// retryAt holds a TimedOut back after a failed switch (Defer). Zero
+	// means no hold.
+	retryAt time.Time
 }
 
 // Verdict is what one observation changed.
@@ -44,9 +47,10 @@
 	// Continuing: a further sub-threshold sample, within the timeout.
 	Continuing
 	// TimedOut: a sub-threshold sample more than Timeout after buffering
-	// started. Python tries the next stream here; on success it resets
-	// (Reset), on failure it stays buffering and tries again on the NEXT
-	// sample (:1210), so this verdict repeats until something resets it.
+	// started. The caller tries the next stream here; on success it resets
+	// (Reset), on failure it defers (Defer) and the verdict is held back for
+	// another Timeout. A caller that does neither sees it on every sample,
+	// which is what Python did (:1210, issue #302).
 	TimedOut
 	// Ended: speed back at or above the threshold after buffering.
 	Ended
@@ -68,22 +72,29 @@
 	return "unknown"
 }
 
+// clock is the detector's one reading of the time: Now, or the wall clock
+// when Now is nil. One helper rather than a nil check in each of the three
+// methods that read it, so the fallback is one statement a test can cover.
+func (d *Detector) clock() time.Time {
+	if d.Now == nil {
+		return time.Now()
+	}
+	return d.Now()
+}
+
 // Observe feeds one reported speed to the detector.
 func (d *Detector) Observe(speed float64) Verdict {
-	now := d.Now
-	if now == nil {
-		now = time.Now
-	}
 	if speed < d.Threshold {
 		if !d.buffering {
 			d.buffering = true
-			d.since = now()
+			d.since = d.clock()
 			return Started
 		}
 		// input/manager.py:1174-1175's `if buffering_start_time is None`
 		// arm is unreachable: the two are set together at :1213-1214 and
 		// cleared together at :1185-1186 and :1240-1241. Not ported.
-		if now().Sub(d.since) > d.Timeout {
+		at := d.clock()
+		if at.Sub(d.since) > d.Timeout && !at.Before(d.retryAt) {
 			return TimedOut
 		}
 		return Continuing
@@ -91,6 +102,7 @@
 	if d.buffering {
 		d.buffering = false
 		d.since = time.Time{}
+		d.retryAt = time.Time{}
 		return Ended
 	}
 	return Steady
@@ -106,11 +118,7 @@
 	if !d.buffering {
 		return 0
 	}
-	now := d.Now
-	if now == nil {
-		now = time.Now
-	}
-	return now().Sub(d.since)
+	return d.clock().Sub(d.since)
 }
 
 // Reset is the successful-switch branch (:1185-1186): buffering cleared and
@@ -119,4 +127,16 @@
 func (d *Detector) Reset() {
 	d.buffering = false
 	d.since = time.Time{}
+	d.retryAt = time.Time{}
 }
+
+// Defer is the failed-switch branch, and it is issue #302's fix. Python left
+// the detector untouched when _try_next_stream failed (:1210), so the very
+// next record -- about every half second -- timed out again and asked the
+// control plane again, for as long as the speed stayed low. Defer keeps the
+// channel buffering and keeps the clock (BufferingFor still measures from the
+// first sub-threshold sample, which is the duration a later channel_failover
+// reports) and holds the next TimedOut back for one more Timeout: a channel
+// with nowhere to go asks once per buffering_timeout instead of once per
+// record.
+func (d *Detector) Defer() { d.retryAt = d.clock().Add(d.Timeout) }
--- a/relay/channel/channel.go
+++ b/relay/channel/channel.go
@@ -160,6 +160,11 @@
 	failoverDegraded bool
 	pending          *Resolved
 	failures         failureCounter
+	// switches is stream_switch_attempts: the switches made since the
+	// rotation last reset, bounded by Tuning.MaxStreamSwitches. A channel
+	// field under mu rather than a run-loop local since issue #221's fix,
+	// because the stderr reader's buffering switch counts against it too.
+	switches int
 
 	cancel context.CancelFunc
 	done   chan struct{}
@@ -452,9 +457,8 @@
 	go c.monitorHealth(ctx)
 
 	source := first
-	switches := 0
-	var last error
-	for ctx.Err() == nil && switches <= c.tuning.MaxStreamSwitches {
+	var last error
+	for ctx.Err() == nil && c.switchCount() <= c.tuning.MaxStreamSwitches {
 		urlFailed := false
 		for ctx.Err() == nil && c.failures.count < c.tuning.MaxRetries && !urlFailed && !c.flagSet(&c.needsSwitch) {
 			attempt := c.failures.count + 1
@@ -476,7 +480,9 @@
 			if resolved := c.takePending(); resolved != nil {
 				// The stderr reader switched on a buffering timeout
 				// (:1178-1211) and has already cleared the failure history,
-				// as update_url does. It never touched `switches`: row 6.
+				// as update_url does, and counted the switch (issue #221,
+				// row 6) -- or an operator's Advance parked it, which is
+				// not counted.
 				source = resolved.Source
 				break
 			}
@@ -489,7 +495,7 @@
 				// :508-513: a stable run resets the rotation.
 				c.log.Info("stream was stable; resetting the switch rotation", "channel", c.id, "duration", duration.Round(time.Second))
 				c.noteStable()
-				switches = 0
+				c.resetSwitches()
 			}
 			if c.takeFlag(&c.needsReconnect) {
 				// :521-531: the monitor asked for a same-URL reconnect on a
@@ -537,7 +543,7 @@
 		if c.takeFlag(&c.needsSwitch) {
 			// :428-438: the health monitor's switch.
 			if resolved, ok := c.failover(ctx, "health_monitor"); ok {
-				switches++
+				c.countSwitch()
 				source = resolved.Source
 				continue
 			}
@@ -548,11 +554,11 @@
 		if urlFailed {
 			// :596-611.
 			if resolved, ok := c.failover(ctx, "max_retries_exceeded"); ok {
-				switches++
+				c.countSwitch()
 				source = resolved.Source
 				continue
 			}
-			c.log.Error("no alternative stream after the switch attempts", "channel", c.id, "switches", switches)
+			c.log.Error("no alternative stream after the switch attempts", "channel", c.id, "switches", c.switchCount())
 			break
 		}
 	}
@@ -605,6 +611,27 @@
 	return err
 }
 
+// switchCount, countSwitch and resetSwitches are the switch counter's three
+// operations, under mu because the run loop and the stderr reader both reach
+// it (issue #221).
+func (c *Channel) switchCount() int {
+	c.mu.RLock()
+	defer c.mu.RUnlock()
+	return c.switches
+}
+
+func (c *Channel) countSwitch() {
+	c.mu.Lock()
+	defer c.mu.Unlock()
+	c.switches++
+}
+
+func (c *Channel) resetSwitches() {
+	c.mu.Lock()
+	defer c.mu.Unlock()
+	c.switches = 0
+}
+
 // takePending hands the run loop a source the stderr reader adopted.
 func (c *Channel) takePending() *Resolved {
 	c.mu.Lock()
--- a/relay/channel/failover.go
+++ b/relay/channel/failover.go
@@ -283,8 +283,16 @@
 // failoverFromBuffering is the stderr reader's entry: _parse_ffmpeg_stats'
 // buffering-timeout branch (input/manager.py:1178-1211, parity-matrix row
 // 1), which calls _try_next_stream from the reader thread and, on success,
-// clears the buffering state and raises channel_failover. It never touches
-// the main loop's switch counter, which is row 6.
+// clears the buffering state and raises channel_failover.
+//
+// IT COUNTS AGAINST MAX_STREAM_SWITCHES, which is issue #221's fix and
+// parity-matrix row 6. Python's stderr path never touched the main loop's
+// counter, so a source that kept speed below the threshold could switch
+// without limit. Here a spent budget REFUSES the switch without asking the
+// control plane -- and, unlike the main loop, does not end the channel: the
+// main loop reaches its bound with no working source, where this source is
+// still delivering, only slowly. The caller defers (Detector.Defer), so a
+// spent budget is re-checked once per buffering_timeout, locally.
 //
 // The new source is parked for the run loop and the running attempt is
 // cancelled; Run returns to the loop once this reader has returned, because
@@ -295,10 +303,16 @@
 	if ctx == nil {
 		ctx = context.Background()
 	}
+	if used := c.switchCount(); used >= c.tuning.MaxStreamSwitches {
+		c.log.Warn("buffering timeout with the stream switch budget spent; staying on the current stream",
+			"channel", c.id, "switches", used, "max", c.tuning.MaxStreamSwitches)
+		return false
+	}
 	resolved, ok := c.failover(ctx, "buffering_timeout")
 	if !ok {
 		return false
 	}
+	c.countSwitch()
 	c.mu.Lock()
 	c.pending = &resolved
 	cancel := c.cancelAttempt
--- a/relay/channel/tuning.go
+++ b/relay/channel/tuning.go
@@ -74,9 +74,9 @@
 	// this long resets the switch rotation (input/manager.py:52, :508-513).
 	StableThreshold time.Duration
 
-	// MaxStreamSwitches is MAX_STREAM_SWITCHES: the main loop's bound on
-	// switches (input/manager.py:388-402), which the buffering path does
-	// not consult (row 6).
+	// MaxStreamSwitches is MAX_STREAM_SWITCHES: the bound on automatic
+	// switches (input/manager.py:388-402), the main loop's and, since issue
+	// #221's fix, the buffering path's too (row 6).
 	MaxStreamSwitches int
 
 	// ClientTimeout is STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD, the sum
--- a/relay/channel/source_transcode.go
+++ b/relay/channel/source_transcode.go
@@ -326,10 +326,10 @@
 	case ffmpeg.TimedOut:
 		// :1178-1211, parity-matrix row 1: the next stream, asked for from
 		// THIS goroutine, as Python asks from its stderr thread. On success
-		// the channel has parked the new source and cancelled this attempt;
-		// on failure Python stays buffering and asks again on the very next
-		// record (:1210) -- one control-plane call per progress record until
-		// something answers, reproduced and filed rather than rate-limited.
+		// the channel has parked the new source and cancelled this attempt.
+		// On failure the channel stays buffering and the detector DEFERS:
+		// the next ask is one buffering_timeout away, not one progress
+		// record away as it was in Python (:1210, issue #302).
 		bufferingFor := r.detector.BufferingFor()
 		s.log().Error("buffering timeout reached", "channel", s.channelID(), "speed", *p.Speed, "buffering_for", bufferingFor.Round(100*time.Millisecond), "timeout", r.detector.Timeout)
 		if s.channel != nil && s.channel.failoverFromBuffering(bufferingFor) {
@@ -340,7 +340,8 @@
 			// for the next record.
 			r.detector.Reset()
 		} else {
-			s.log().Error("failed to switch to the next stream after a buffering timeout", "channel", s.channelID())
+			s.log().Error("failed to switch to the next stream after a buffering timeout", "channel", s.channelID(), "retry_in", r.detector.Timeout)
+			r.detector.Defer()
 		}
 	case ffmpeg.Ended:
 		s.log().Info("buffering ended", "channel", s.channelID(), "speed", *p.Speed)
```

### Appendix D — A-2 tests (`detector_test.go`, `source_transcode_test.go`)

```go
// Issue #302: after a failed switch the caller DEFERS, and the next TimedOut
// is held back for one more Timeout -- the channel stays buffering throughout,
// and BufferingFor keeps measuring from the first sub-threshold sample,
// because that is the duration a later channel_failover reports.
func TestADeferredTimeoutIsHeldBackForAnotherTimeout(t *testing.T) {
	c := &clock{at: time.Unix(1_789_000_000, 0)}
	d := newDetector(c, 2.0, 15*time.Second)

	if v := d.Observe(1.0); v != Started {
		t.Fatalf("got %s, want %s", v, Started)
	}
	c.tick(15*time.Second + time.Millisecond)
	if v := d.Observe(1.0); v != TimedOut {
		t.Fatalf("got %s, want %s", v, TimedOut)
	}
	d.Defer()
	c.tick(14 * time.Second)
	if v := d.Observe(1.0); v != Continuing {
		t.Fatalf("14s after a deferral: got %s, want %s -- the timeout was not held back", v, Continuing)
	}
	if !d.Buffering() {
		t.Fatal("a deferral left the detector not buffering")
	}
	if got, want := d.BufferingFor(), 29*time.Second+time.Millisecond; got != want {
		t.Fatalf("BufferingFor = %s, want %s: a deferral must not restart the clock", got, want)
	}
	c.tick(time.Second)
	if v := d.Observe(1.0); v != TimedOut {
		t.Fatalf("a full timeout after the deferral: got %s, want %s", v, TimedOut)
	}
	// Recovery clears the hold with the rest of the state, so a fresh dip
	// times out on its own window rather than on a stale deferral.
	d.Defer()
	if v := d.Observe(2.0); v != Ended {
		t.Fatalf("got %s, want %s", v, Ended)
	}
	if v := d.Observe(1.0); v != Started {
		t.Fatalf("got %s, want %s", v, Started)
	}
	c.tick(15*time.Second + time.Millisecond)
	if v := d.Observe(1.0); v != TimedOut {
		t.Fatalf("a fresh window after recovery: got %s, want %s -- the old deferral survived Ended", v, TimedOut)
	}

	// A detector with no injected clock reads the wall clock, the relay's
	// production shape: a deferral taken just now holds a one-hour timeout
	// back, where an unset hold would let an hour-old window time out.
	wall := &Detector{Threshold: 2.0, Timeout: time.Hour}
	wall.Observe(1.0)
	wall.since = wall.since.Add(-2 * time.Hour)
	if v := wall.Observe(1.0); v != TimedOut {
		t.Fatalf("a wall-clock window two hours old: got %s, want %s", v, TimedOut)
	}
	wall.Defer()
	if v := wall.Observe(1.0); v != Continuing {
		t.Fatalf("a wall-clock deferral: got %s, want %s -- Defer did not read the wall clock", v, Continuing)
	}
}

// PARITY-MATRIX ROW 6, issue #221, FIXED: MAX_STREAM_SWITCHES bounds a
// buffering-triggered switch as it bounds the main loop's. With the bound at
// ZERO the buffering path never asks the control plane at all, and -- unlike
// the main loop, which ends the channel at its bound -- the channel keeps
// playing, slowly, on the source it has. Python's stderr thread never touched
// the counter (input/manager.py:1134-1138), so this switched regardless.
func TestABufferingFailoverIsRefusedOnceMaxStreamSwitchesIsSpent(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	alternate := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504")
	ran := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: countingRuns{inner: alternate, runs: ran},
		Info:   SourceInfo{URL: "http://provider.invalid/alternate.ts", StreamID: 2, M3UProfileID: 1},
	}}}
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02", "--stderr-loop")
	tuning := transcodeTuning(apiMax, time.Second)
	tuning.MaxStreamSwitches = 0

	ch, release := attachWith(t, m, "row6", src, tuning, resolver)
	defer release()

	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	// Three buffering_timeouts: the defect asked, and switched, inside the
	// first one.
	time.Sleep(3 * time.Second)
	if n := len(resolver.requests()); n != 0 {
		t.Fatalf("the resolver was asked %d times under MAX_STREAM_SWITCHES = 0: the buffering path ignored the bound (#221)", n)
	}
	if ch.Source().StreamID != 1 || ran.get() != 0 {
		t.Fatalf("the channel moved to stream %d (alternate ran %d times) with no switch budget", ch.Source().StreamID, ran.get())
	}
	if n := len(events.of("channel_failover")); n != 0 {
		t.Fatalf("channel_failover raised %d times with no switch budget", n)
	}
	select {
	case <-ch.Done():
		t.Fatalf("the channel ended (%v): a spent budget refuses the switch, it does not end a source that is still delivering", ch.Err())
	default:
	}
	m.Stop("row6")
}

// The other half of row 6: a buffering switch is COUNTED, so with a bound of
// one the first buffering timeout switches and the second, on the alternate,
// does not. The alternate replays the same slow capture, so it buffers too;
// the resolver holds a second answer, so only the bound can stop the ask.
func TestABufferingFailoverCountsAgainstMaxStreamSwitches(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	slow := func() *TranscodeSource {
		return standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
			"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02", "--stderr-loop")
	}
	resolver := &fakeResolver{answers: []Resolved{
		{Source: slow(), Info: SourceInfo{URL: "http://provider.invalid/two.ts", StreamID: 2, M3UProfileID: 1}},
		{Source: slow(), Info: SourceInfo{URL: "http://provider.invalid/three.ts", StreamID: 3, M3UProfileID: 1}},
	}}
	tuning := transcodeTuning(apiMax, time.Second)
	tuning.MaxStreamSwitches = 1

	ch, release := attachWith(t, m, "row6-count", slow(), tuning, resolver)
	defer release()

	waitFor(t, "the first switch", 15*time.Second, func() bool { return ch.Source().StreamID == 2 })
	waitFor(t, "the alternate to buffer", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	time.Sleep(3 * time.Second)
	if n := len(resolver.requests()); n != 1 {
		t.Fatalf("the resolver was asked %d times under MAX_STREAM_SWITCHES = 1, want 1: the buffering switch was not counted (#221)", n)
	}
	if id := ch.Source().StreamID; id != 2 {
		t.Fatalf("the channel is on stream %d, want 2", id)
	}
	m.Stop("row6-count")
}

// Issue #302, FIXED. The failure branch of the same arm (input/manager.py:
// 1210) left Python buffering with its clock unchanged, so the very next
// progress record -- here every 20 ms -- timed out again and asked the
// control plane again. The detector now defers after a failed ask: the
// channel keeps playing and stays buffering, and consecutive asks are at
// least one buffering_timeout apart -- a LOWER BOUND ONLY.
//
// A SYNTHETIC ORDER, NOT A SYNTHETIC LINE, which the corpus rule permits with
// a reason (TestBufferingEndsWhenTheSpeedRecovers uses the same exception):
// the slow-trickle capture's own records, with its sub-threshold tail
// repeated, so the channel buffers once and stays buffering for five
// seconds. Replaying the capture with --stderr-loop instead would re-open
// every pass with a record above the threshold, end the buffering and
// restart the clock, and "still buffering" could not be asserted at all.
func TestABufferingTimeoutWithNoAlternateAsksOncePerTimeoutNotOnEveryRecord(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	const timeout = time.Second
	_, records := relaytest.SplitCorpus(relaytest.Corpus("slow-trickle"))
	body := append(append([]byte{}, records[0]...), '\r')
	for range 4 {
		for _, r := range records[1:] {
			body = append(body, r...)
			body = append(body, '\r')
		}
	}
	corpus := filepath.Join(t.TempDir(), "long-tail.stderr")
	if err := os.WriteFile(corpus, body, 0o600); err != nil {
		t.Fatal(err)
	}
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	resolver := &fakeResolver{} // every answer is ErrNoAlternate
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", corpus, "--stderr-interval", "0.02")

	ch, release := attachWith(t, m, "no-alt", src, transcodeTuning(apiMax, timeout), resolver)
	defer release()

	waitFor(t, "a third failed switch", 20*time.Second, func() bool { return len(resolver.requests()) >= 3 })
	if state := ch.State(); state != StateBuffering {
		t.Fatalf("state = %q, want buffering: a failed switch leaves the channel where it was", state)
	}
	resolver.mu.Lock()
	at := append([]time.Time(nil), resolver.calledAt...)
	resolver.mu.Unlock()
	for i := 1; i < len(at); i++ {
		if gap := at[i].Sub(at[i-1]); gap < timeout {
			t.Fatalf("asks %d and %d were %s apart, under the %s buffering_timeout: the channel is asking on every record (#302)", i-1, i, gap, timeout)
		}
	}
	select {
	case <-ch.Done():
		t.Fatalf("the channel ended (%v): a failed buffering switch must not end the tune", ch.Err())
	default:
	}
	m.Stop("no-alt")
}
```

### Appendix E — A-3 production: `source_transcode.go` (against the tree after A-2)

```diff
--- a/relay/channel/source_transcode.go
+++ b/relay/channel/source_transcode.go
@@ -96,7 +96,13 @@
 
 // argv applies the one transformation input/manager.py:808-812 applies at
 // spawn time: on a UDP upstream every argument that contains the user agent,
-// or "user-agent" or "user_agent" in any case, is dropped.
+// or "user-agent" or "user_agent" in any case, is dropped -- AND ITS PARTNER
+// WITH IT, which is issue #296's fix. Python dropped the argument alone, so
+// `-headers 'User-Agent: X'` spawned as a bare `-headers` whose value became
+// the next argument, and the shipped Streamlink profile's
+// `--http-header User-Agent=X best` spawned as `--http-header best`. A
+// dropped VALUE takes the flag in front of it; a dropped FLAG
+// (`-user_agent`) takes the value after it.
 //
 // Python filters self.transcode_cmd, which INCLUDES the command at index 0;
 // a command containing "user-agent" would be dropped there and the spawn
@@ -106,18 +112,40 @@
 	if StreamTypeOf(s.URL) != "udp" {
 		return s.Argv
 	}
-	kept := make([]string, 0, len(s.Argv))
-	for _, arg := range s.Argv {
-		lower := strings.ToLower(arg)
-		if (s.UserAgent != "" && strings.Contains(arg, s.UserAgent)) ||
-			strings.Contains(lower, "user-agent") || strings.Contains(lower, "user_agent") {
+	drop := make([]bool, len(s.Argv))
+	for i, arg := range s.Argv {
+		if !s.carriesUserAgent(arg) {
 			continue
 		}
-		kept = append(kept, arg)
+		drop[i] = true
+		switch {
+		case isFlag(arg) && i+1 < len(s.Argv) && !isFlag(s.Argv[i+1]):
+			drop[i+1] = true
+		case !isFlag(arg) && i > 0 && isFlag(s.Argv[i-1]):
+			drop[i-1] = true
+		}
 	}
+	kept := make([]string, 0, len(s.Argv))
+	for i, arg := range s.Argv {
+		if !drop[i] {
+			kept = append(kept, arg)
+		}
+	}
 	return kept
+}
+
+// carriesUserAgent is input/manager.py:811's test: the user agent itself, or
+// "user-agent" or "user_agent" in any case.
+func (s *TranscodeSource) carriesUserAgent(arg string) bool {
+	lower := strings.ToLower(arg)
+	return (s.UserAgent != "" && strings.Contains(arg, s.UserAgent)) ||
+		strings.Contains(lower, "user-agent") || strings.Contains(lower, "user_agent")
 }
 
+// isFlag is an argv element that names an option rather than carrying a
+// value: a leading dash and something after it.
+func isFlag(arg string) bool { return len(arg) > 1 && arg[0] == '-' }
+
 // fail records why the source is ending and stops the process. The first
 // cause wins; a later one (the SIGKILL's own exit status, say) does not
 // overwrite it.
```

### Appendix F — A-3 tests (`source_transcode_test.go`)

```go
// The UDP filter, input/manager.py:808-812: on a udp:// upstream every
// argument carrying the user agent, or "user-agent"/"user_agent" in any
// case, is dropped together with its partner; on any other upstream nothing
// is.
func TestTheUDPFilterDropsUserAgentArgumentsWithTheirFlags(t *testing.T) {
	argv := []string{"-user_agent", "VLC/3.0.20", "-headers", "User-Agent: VLC/3.0.20", "-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}
	udp := &TranscodeSource{Argv: argv, URL: "udp://239.0.0.1:1234", UserAgent: "VLC/3.0.20"}
	// "-headers" GOES WITH ITS VALUE (issue #296). Python dropped the value
	// alone and spawned a dangling -headers whose value became the next
	// argument, -i.
	want := []string{"-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}
	if got := udp.argv(); strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("UDP argv = %q, want %q", got, want)
	}
	http := &TranscodeSource{Argv: argv, URL: "http://p/1.ts", UserAgent: "VLC/3.0.20"}
	if got := http.argv(); strings.Join(got, " ") != strings.Join(argv, " ") {
		t.Fatalf("HTTP argv was filtered: %q", got)
	}
}

// ISSUE #296 on a shipped profile: Streamlink's parameters are
// "{streamUrl} --http-header User-Agent={userAgent} best --stdout"
// (core/migrations/0011_fix_stream_profiles_and_user_agents.py:10). The
// filter used to leave `--http-header best`, taking the quality selector as
// the header's value; a flag whose value is dropped must go with it. And a
// dropped FLAG takes its value: `-user_agent` with an empty user agent
// substituted leaves no stray "" behind.
func TestTheUDPFilterLeavesNoDanglingFlag(t *testing.T) {
	const url = "udp://239.0.0.1:1234"
	streamlink := &TranscodeSource{
		Argv: []string{url, "--http-header", "User-Agent=VLC/3.0.20", "best", "--stdout"},
		URL:  url, UserAgent: "VLC/3.0.20",
	}
	if got, want := strings.Join(streamlink.argv(), " "), url+" best --stdout"; got != want {
		t.Fatalf("streamlink UDP argv = %q, want %q", got, want)
	}
	blank := &TranscodeSource{Argv: []string{"-user_agent", "", "-i", url, "pipe:1"}, URL: url}
	if got := blank.argv(); len(got) != 3 || got[0] != "-i" {
		t.Fatalf("argv = %q, want the flag and its empty value both gone", got)
	}
}
```

### Appendix G — A-4 production: `relay/output/fmp4.go`

```diff
--- a/relay/output/fmp4.go
+++ b/relay/output/fmp4.go
@@ -135,9 +135,12 @@
 //
 // MP4 boxes are [4-byte big-endian length][4-byte type][payload]. A length
 // below 8 is not a valid box, and Python advances ONE byte on it rather than
-// giving up -- a resynchronisation, reproduced here because a stream that
-// desynchronises mid-fragment recovers at the next real box header either way
-// and the two implementations must recover at the same byte.
+// giving up. That is NOT a resynchronisation: any length of 8 or more is
+// trusted and strided over, so a scan that starts off a box boundary reads a
+// garbage length, jumps past every real box and returns -1 (issues #306 and
+// #119). This function is therefore used only where the scan starts ON a
+// boundary -- the init segment from offset 0, a fragment's successor from its
+// own moof's end -- and resyncOffset below is what a misaligned buffer uses.
 //
 // Python's `except struct.error` arm is UNREACHABLE: unpack_from cannot fail
 // while offset+8 <= len(data). Not reproduced, because there is nothing to
@@ -164,6 +167,57 @@
 	return -1
 }
 
+// minMoofBox is the smallest real moof, and the smallest length resyncOffset
+// accepts for a candidate: its own 8-byte header plus an mfhd, 16 bytes. A
+// "moof" shorter than that is garbage that happens to spell the type, and an
+// aligned one is resynchronised past rather than trusted (flush). Adopted from
+// #348's A-4.
+const minMoofBox = 16
+
+// maxFragmentBytes is the most the working buffer holds while a fragment has
+// no end in sight -- an aligned moof whose own length is corrupt, or a valid
+// one followed by a box whose length is, both of which make the fragment's
+// end unfindable and would otherwise hold the buffer open toward a 4 GiB
+// length. Past it the fragment is abandoned and the scanner resynchronises.
+// 64 MiB is 50 Mbit/s over a 10-second keyframe interval with margin; adopted
+// from #348's A-4.
+const maxFragmentBytes = 64 << 20
+
+// maxMoofBoxBytes is the largest length resyncOffset accepts for a candidate
+// moof box's OWN header -- the moof, not the fragment: a moof holds a few
+// track headers and a sample table and runs to kilobytes, where the mdat
+// after it can run to megabytes. A "moof" literal inside a payload reads a
+// length that is garbage; one past this bound is refused as a resync point
+// rather than trusted, because the aligned path would then wait for that many
+// bytes before publishing anything.
+const maxMoofBoxBytes = 1 << 20
+
+// resyncTail is how much of a working buffer with no resync point in it is
+// kept: the most of a moof header that can sit at the end without its "moof"
+// literal being complete -- a four-byte length and three bytes of the type.
+const resyncTail = 7
+
+// resyncOffset finds the next plausible moof header at or after start in a
+// buffer that is NOT aligned on a box boundary, the fix for issues #306 and
+// #119. It searches for the four-byte type literal and checks the length in
+// front of it, rather than striding by lengths it cannot trust: the first
+// candidate whose length is between minMoofBox and maxMoofBoxBytes wins. -1
+// when there is none.
+func resyncOffset(data []byte, start int) int {
+	for from := start; from+8 <= len(data); {
+		i := bytes.Index(data[from+4:], moofBox)
+		if i < 0 {
+			return -1
+		}
+		at := from + i
+		if size := binary.BigEndian.Uint32(data[at : at+4]); size >= minMoofBox && size <= maxMoofBoxBytes {
+			return at
+		}
+		from = at + 1
+	}
+	return -1
+}
+
 // scanner turns the remux's fd 1 byte stream into an init segment and a
 // sequence of fragments, the port of _reader_loop's body (manager.py:289-349)
 // and _flush_complete_fragments (:252-287).
@@ -173,8 +227,25 @@
 	init       []byte
 	initStored bool
 	frag       []byte
+
+	// ceiling overrides maxFragmentBytes for one scanner, for tests; zero
+	// means the constant. A field rather than a package variable a test
+	// lowers, so no test can race another scanner's read of it.
+	ceiling int
 }
 
+func (s *scanner) fragmentCeiling() int {
+	if s.ceiling > 0 {
+		return s.ceiling
+	}
+	return maxFragmentBytes
+}
+
+// abandon gives up a fragment whose end cannot be found: dropping one byte
+// misaligns the buffer, so the next pass of flush resynchronises past the
+// moof that could not be bounded.
+func (s *scanner) abandon() { s.frag = s.frag[1:] }
+
 // ErrNoInitSegment is the abort at manager.py:334-339: 10 MB of remux output
 // with no moof box in it.
 var ErrNoInitSegment = fmt.Errorf("output: no moof box in the first %d bytes of the remux output", MaxInitSegmentBytes)
@@ -214,29 +285,47 @@
 // stops mid-stream leaves one fragment unpublished until `final` runs.
 func (s *scanner) flush() {
 	for len(s.frag) >= 8 {
-		if !bytes.Equal(s.frag[4:8], moofBox) {
+		size := int64(binary.BigEndian.Uint32(s.frag[0:4]))
+		if !bytes.Equal(s.frag[4:8], moofBox) || size < minMoofBox {
 			// manager.py:259-266: the stream is not aligned to a moof, so drop
 			// bytes until one is found. start=1, not 0, or this would find the
-			// box it has already rejected.
-			next := findMoofOffset(s.frag, 1)
+			// box it has already rejected. Through resyncOffset, not
+			// findMoofOffset: Python strided from offset 1 by a garbage length
+			// and cleared the whole buffer on the -1 it got (#306, #119). A
+			// moof shorter than minMoofBox is not one either: aligned on it,
+			// the seed returned without consuming anything and the buffer
+			// grew with every write (#348's A-4).
+			next := resyncOffset(s.frag, 1)
 			if next < 0 {
-				s.frag = s.frag[:0]
+				// Nothing yet. Keep only the tail a header could be arriving
+				// in, so the buffer stays bounded and a moof whose header
+				// straddles this read is still found on the next.
+				if len(s.frag) > resyncTail {
+					s.frag = append(s.frag[:0], s.frag[len(s.frag)-resyncTail:]...)
+				}
 				return
 			}
 			s.frag = s.frag[next:]
 			continue
 		}
-		size := int64(binary.BigEndian.Uint32(s.frag[0:4]))
-		if size < 8 {
-			return
-		}
 		if size > int64(len(s.frag)) {
 			// _find_moof_offset(frag_buf, start=moof_size) returns -1 for a
-			// start past the end, and manager.py:279 breaks. Same answer.
+			// start past the end, and manager.py:279 breaks. Same answer --
+			// unless the moof's own length is corrupt and the wait would
+			// never end.
+			if len(s.frag) > s.fragmentCeiling() {
+				s.abandon()
+				continue
+			}
 			return
 		}
 		next := findMoofOffset(s.frag, int(size))
 		if next < 0 {
+			// The same wait, for the box after the moof.
+			if len(s.frag) > s.fragmentCeiling() {
+				s.abandon()
+				continue
+			}
 			return
 		}
 		s.out.Put(s.frag[:next])
```

### Appendix H — A-4 tests (`scanner_test.go`)

```go
func TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof(t *testing.T) {
	// ISSUE #306, FIXED. manager.py:259-266 said "drop bytes until we find
	// one" and searched from offset 1 with the box-striding scanner -- but
	// offset 1 re-reads a four-byte length at a one-byte shift, which for any
	// real box is a bogus size in the tens of thousands, so the scan jumped
	// past every following box, returned -1, and the WHOLE working buffer was
	// cleared, fragments and all. The resync arm now looks for the next moof
	// header itself, so the fragments behind the misalignment are kept: 5 is
	// published (6 bounds it) and 6 is held back as every newest fragment is.
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	if err := s.write(slices.Concat(
		relaytest.MP4Box("junk", make([]byte, 64)),
		relaytest.SyntheticFMP4Fragment(5),
		relaytest.SyntheticFMP4Fragment(6),
	)); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	got := collect(f)
	if len(got) != 1 {
		t.Fatalf("%d fragments published behind a misaligned working buffer, want 1 (fragment 5; 6 is held back): the resync discarded them (#306)", len(got))
	}
	if index := relaytest.FMP4FragmentIndex(got[0]); index != 5 {
		t.Fatalf("the published fragment carries index %d, want 5", index)
	}
}

func TestAGarbageRunThatReadsAsALargeLengthDoesNotHideTheNextMoof(t *testing.T) {
	// ISSUE #119's shrunk counterexample, both at the finder and through the
	// scanner. One garbage byte before a moof: the striding scan read
	// 0x01000000 as a length at offset 0 and jumped clear past it. The
	// issue's own moof is EMPTY (8 bytes), which minMoofBox now refuses as a
	// resync point on purpose, so the finder is asserted on a real 16-byte one
	// and the empty box is kept in the rejection test below. Two garbage
	// bytes through the scanner: the resync arm starts at offset 1, reads
	// 0x01000000 there, and did the same.
	if at := resyncOffset(slices.Concat([]byte{0x01}, relaytest.SyntheticFMP4Fragment(0)), 0); at != 1 {
		t.Fatalf("resyncOffset found the moof at %d, want 1 (#119)", at)
	}
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	if err := s.write(slices.Concat([]byte{0x01, 0x01}, relaytest.SyntheticFMP4Fragment(0), relaytest.SyntheticFMP4Fragment(1))); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if got := collect(f); len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
		t.Fatalf("published %d fragments after two garbage bytes, want fragment 0 alone (#119)", len(got))
	}
}

func TestAMoofHeaderSplitAcrossReadsSurvivesAResync(t *testing.T) {
	// The tail a resync with nothing to find must keep. A megabyte of garbage
	// arrives with the first six bytes of fragment 0's header at its end, and
	// the rest of the stream in the next read. Clearing the buffer -- what
	// the -1 did -- loses those six bytes, and fragment 0 with them; keeping
	// everything would hold the megabyte. resyncTail keeps seven.
	fragment := relaytest.SyntheticFMP4Fragment(0)
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	garbage := bytes.Repeat([]byte{0x01}, 1<<20)
	if err := s.write(slices.Concat(garbage, fragment[:6])); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if held := len(s.frag); held > resyncTail {
		t.Fatalf("the working buffer holds %d bytes after a megabyte with no moof, want at most %d", held, resyncTail)
	}
	if err := s.write(slices.Concat(fragment[6:], relaytest.SyntheticFMP4Fragment(1))); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if got := collect(f); len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
		t.Fatalf("published %d fragments, want fragment 0: its header straddled the read and was discarded", len(got))
	}
}

func TestAMoofLiteralWithAnImplausibleLengthIsNotAResyncPoint(t *testing.T) {
	// A "moof" inside a payload reads a garbage length. Too long, and the
	// aligned path would wait for 4 GiB of it; too short -- #119's own empty
	// box among them -- and it is not a moof at all (minMoofBox). Each is
	// skipped for the real moof after it.
	for name, bogus := range map[string][]byte{
		"longer than any moof":       {0xFF, 0xFF, 0xFF, 0xFF, 'm', 'o', 'o', 'f'},
		"#119's empty moof, 8 bytes": relaytest.MP4Box("moof", nil),
		"shorter than an mfhd needs": relaytest.MP4Box("moof", make([]byte, 4)),
	} {
		data := slices.Concat([]byte{0x00}, bogus, relaytest.SyntheticFMP4Fragment(0))
		if at, want := resyncOffset(data, 1), 1+len(bogus); at != want {
			t.Fatalf("%s: resyncOffset chose %d, want the real moof at %d", name, at, want)
		}
		// And with nothing after it, a refused candidate leaves no resync
		// point at all, rather than being taken for want of a better one.
		if at := resyncOffset(slices.Concat([]byte{0x00}, bogus), 1); at != -1 {
			t.Fatalf("%s: resyncOffset chose %d with no real moof in the buffer, want -1", name, at)
		}
	}
}

func TestAMoofShorterThanARealOneDoesNotStallTheBuffer(t *testing.T) {
	// Adopted from #348's A-4. A buffer ALIGNED on a "moof" whose length is
	// below a real moof's 16 bytes (its own header plus an mfhd) is not on a
	// fragment. The seed returned without consuming anything for a length
	// below 8 (fmp4.go:229-231), so every later write grew the buffer and
	// nothing was ever published again; a length from 8 to 15 was trusted and
	// published as a bogus fragment of its own. Either way fragment 0, whole
	// and right behind it, must be what comes out.
	for _, size := range []uint32{4, 12} {
		t.Run(fmt.Sprintf("length %d", size), func(t *testing.T) {
			short := make([]byte, max(size, 8))
			binary.BigEndian.PutUint32(short[0:4], size)
			copy(short[4:8], "moof")
			f := buffer.NewFragments(buffer.FragmentsConfig{})
			s := &scanner{out: f, initStored: true}
			if err := s.write(slices.Concat(short, relaytest.SyntheticFMP4Fragment(0), relaytest.SyntheticFMP4Fragment(1))); err != nil {
				t.Fatalf("the scanner rejected the stream: %v", err)
			}
			got := collect(f)
			if len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
				t.Fatalf("published %d fragments behind a %d-byte moof, want fragment 0 alone", len(got), size)
			}
		})
	}
}

func TestAFragmentThatNeverEndsIsAbandonedAtTheCeiling(t *testing.T) {
	// Adopted from #348's A-4, both shapes of it. An aligned moof whose own
	// length is corrupt waits for bytes that never come (fmp4.go:233-236); a
	// valid moof followed by a box whose length is corrupt makes the search
	// for the NEXT moof return -1 on every pass (:238-240). Either way the
	// seed held the working buffer open toward a length of up to 4 GiB. Past
	// the ceiling the scanner gives the fragment up and resynchronises, so
	// the buffer stays bounded and the next real fragment is published. The
	// ceiling is lowered on this scanner alone rather than fed 64 MiB.
	const ceiling = 4096
	shapes := map[string][]byte{
		"the moof's own length is corrupt": slices.Concat(
			[]byte{0x7f, 0xff, 0xff, 0xff}, []byte("moof"), make([]byte, 8)),
		"the box after the moof is corrupt": slices.Concat(
			relaytest.MP4Box("moof", make([]byte, 8)), []byte{0xff, 0xff, 0xff, 0x00}, []byte("mdat")),
	}
	for name, corrupt := range shapes {
		t.Run(name, func(t *testing.T) {
			f := buffer.NewFragments(buffer.FragmentsConfig{})
			s := &scanner{out: f, initStored: true, ceiling: ceiling}
			writes := [][]byte{corrupt}
			for range 8 {
				writes = append(writes, bytes.Repeat([]byte{0x01}, 1024))
			}
			for i, w := range writes {
				if err := s.write(w); err != nil {
					t.Fatalf("the scanner rejected write %d: %v", i, err)
				}
				if held := len(s.frag); held > ceiling {
					t.Fatalf("the working buffer holds %d bytes after write %d, past the %d-byte ceiling", held, i, ceiling)
				}
			}
			if err := s.write(slices.Concat(relaytest.SyntheticFMP4Fragment(0), relaytest.SyntheticFMP4Fragment(1))); err != nil {
				t.Fatalf("the scanner rejected the stream: %v", err)
			}
			if got := collect(f); len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
				t.Fatalf("published %d fragments after the ceiling, want fragment 0 alone", len(got))
			}
		})
	}
}
```

### Appendix I — A-5 production: `relay/httpapi/fmp4.go`

```diff
--- a/relay/httpapi/fmp4.go
+++ b/relay/httpapi/fmp4.go
@@ -110,52 +110,35 @@
 }
 
 // serveFMP4Client is the fMP4 client loop: the port of
-// _stream_data_generator and _is_timeout (output/fmp4/generator.py:268-357).
+// _stream_data_generator and _is_timeout (output/fmp4/generator.py:268-357),
+// with issue #222 fixed.
 //
-// PARITY-MATRIX ROW 12 IS THIS FUNCTION, and specifically what it does NOT do.
-// Set it beside serveClient, which is the TS generator's loop, and TWO
-// mechanisms are missing from this one -- both absent from the Python fMP4
-// generator too, and both reproduced as absences:
+// IT LEAVES A CLIENT ON THE SAME EXIT serveClient DOES, which is what
+// parity-matrix row 12 now records. Python's fMP4 generator dropped a client
+// on elapsed time since its last fragment ALONE -- no health check, no
+// keepalive -- so a stall that left a TS viewer on the same channel
+// connected dropped an fMP4 viewer stream_timeout + failover_grace_period
+// (40s by default) in, including in the middle of a slow failover. Set this
+// beside serveClient:
 //
-//   - NO HEALTH GATE. serveClient disconnects only when the channel is
-//     unhealthy (`!ch.Healthy()`, output/ts/generator.py:592's
-//     `not stream_manager.healthy`). Here, elapsed time ALONE ends the client
-//     (generator.py:350-357: `if time.time() - self.last_yield_time > timeout`
-//     and nothing else). A channel whose upstream is fine and whose remux has
-//     merely stalled drops its fMP4 viewers and keeps its TS ones. THIS IS THE
-//     ONE THE ROW'S TEST RESTS ON.
-//   - NO KEEPALIVE. serveClient sends a null TS packet every KeepaliveInterval
-//     to a waiting client on an unhealthy channel, and each one REFRESHES the
-//     very timer the timeout reads (output/ts/generator.py:366-389), which is
-//     why on the TS path the reachable exit is MaxKeepalive and not
-//     ClientTimeout at all. There is nothing to refresh lastYield here but a
-//     real fragment.
+//   - THE HEALTH GATE. A healthy channel never times its clients out: a
+//     remux that has merely stalled while the upstream is fine is waited
+//     for, as serveClient waits (output/ts/generator.py:592's
+//     `not stream_manager.healthy`).
+//   - THE KEEPALIVE CAP, WITHOUT THE KEEPALIVE BYTES. On an unhealthy
+//     channel serveClient sends a null TS packet every KeepaliveInterval,
+//     each refreshing the timer ClientTimeout reads, so its reachable exit
+//     is MaxKeepalive and never ClientTimeout. An fMP4 byte stream has no
+//     null packet a player is known to skip, so nothing is written here --
+//     and the exit is the same one: MaxKeepalive of an unhealthy channel with
+//     nothing to send, counted from the first such read and cleared by the
+//     next fragment, as serveClient's keepaliveStart is. The one timing
+//     difference is where the clock starts: serveClient waits five empty
+//     reads first (at most 1.5s of its backoff), this loop starts it on the
+//     first.
 //
-// THE url_switching EXEMPTION IS A THIRD DIFFERENCE IN PYTHON AND NOT IN GO,
-// and saying so is more useful than listing it as one. Python's TS generator
-// gives a client more time while a switch is in progress
-// (output/ts/generator.py:594-599) and its fMP4 generator does not -- but 2c-5
-// did not port that exemption to serveClient either, on the ground that the
-// keepalive path shadows it (parity-matrix row 12's own Notes say the same:
-// "the url_switching clause is carried in the citations, not tested"). So
-// NEITHER Go loop has it, it is not a divergence between them, and the row's
-// contrast rests on the health gate alone. If a later PR ports it to
-// serveClient, it must NOT be ported here, and this comment goes back to
-// naming three.
-//
-// The consequence is the row's claim, in one sentence: an fMP4 viewer is
-// dropped ClientTimeout into a stall that leaves a TS viewer on the same
-// channel connected. It is filed as issue #222 and it is REPRODUCED, NOT
-// FIXED, per spec D5 -- the Python fix would add the health check, the
-// switching exemption and a keepalive to output/fmp4/generator.py:350-357, and
-// it would change this function, the Python test, the matrix row and the issue
-// together. Do not "improve" this loop.
-//
-// THE THRESHOLD IS THE SAME SUM, which is the part that makes the divergence a
-// gating difference rather than a timing one: Tuning.ClientTimeout is
-// STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD, exactly the sum _is_timeout computes
-// at generator.py:351 and exactly the sum the TS generator computes at
-// output/ts/generator.py:585-587.
+// Neither loop has the url_switching exemption, for the reason serveClient's
+// own branch gives.
 func serveFMP4Client(
 	ctx context.Context,
 	w http.ResponseWriter,
@@ -179,7 +162,10 @@
 	// TestAnFMP4ClientOnAFreshBufferStartsAtTheFirstFragment.
 	cursor := fragments.Join(tuning.JoinBehind)
 
-	lastYield := time.Now()
+	// stallStart is when this client last found nothing to send on an
+	// UNHEALTHY channel after having been fed: serveClient's keepaliveStart,
+	// with no keepalive to send.
+	var stallStart time.Time
 	for {
 		if ctx.Err() != nil {
 			// serveClient's reason: the admin stop and the hang-up both
@@ -198,13 +184,13 @@
 			if !writeChunks(w, rc, frags) {
 				return
 			}
-			lastYield = time.Now()
+			stallStart = time.Time{}
 			// Touch, not Sent: the fMP4 generator writes last_active and no
 			// byte counter (output/fmp4/generator.py:288-295), so an fMP4
 			// client's detail row carries no bytes_sent, avg_rate_KBps or
 			// current_rate_KBps -- reproduced as an absence with a
 			// mechanism rather than a format check in the renderer.
-			client.Touch(lastYield)
+			client.Touch(time.Now())
 			continue
 		}
 
@@ -227,11 +213,16 @@
 			}
 			return
 		case errors.Is(err, context.DeadlineExceeded) && ctx.Err() == nil:
-			// ROW 12. No health check, no switching exemption, no keepalive:
-			// elapsed time since the last fragment, and nothing else.
-			if time.Since(lastYield) > tuning.ClientTimeout {
-				log.Warn("fMP4 no data for the client timeout, disconnecting",
-					"channel", ch.ID(), "client", client.ID, "timeout", tuning.ClientTimeout)
+			// ROW 12, issue #222: serveClient's exit, as the doc comment says.
+			if ch.Healthy() {
+				continue
+			}
+			if stallStart.IsZero() {
+				stallStart = time.Now()
+			}
+			if time.Since(stallStart) > tuning.MaxKeepalive {
+				log.Warn("fMP4 client waited out the keepalive cap with no stream recovery, disconnecting",
+					"channel", ch.ID(), "client", client.ID, "max", tuning.MaxKeepalive)
 				return
 			}
 			continue
@@ -245,5 +236,6 @@
 // where serveClient's TS loop backs off to a second
 // (output/ts/generator.py:400-403's min(0.1 * consecutive_empty, 1.0)) --
 // _stream_data_generator has no such backoff, and the difference is
-// observable as how promptly the timeout below fires once a stall begins.
+// observable as how promptly the keepalive cap's clock starts once a stall
+// begins.
 const fmp4EmptyReadWait = 50 * time.Millisecond
```

### Appendix J — A-5 tests (`fmp4_test.go`)

```go
// PARITY-MATRIX ROW 12, issue #222, FIXED.
//
// A healthy channel whose fragments stop arriving keeps its fMP4 client
// connected, exactly as it keeps its TS client: the stall here is on the
// UPSTREAM, so both clients go quiet together, and the health monitor keeps
// its default CONNECTION_TIMEOUT (10s), so the channel stays healthy for the
// whole window. Before the fix the fMP4 client was dropped at
// stream_timeout + failover_grace_period -- compressed here to 1 + 1 = 2s --
// on elapsed time alone. Watched for three times that.
//
// BOTH CLIENTS ARE STARVED. The upstream stalls, so the TS client goes
// quiet, and the stand-in remux -- which ignores its input -- writes its five
// fragments at once and then stays alive producing nothing, so the fMP4
// client is quiet from its first second. A remux that kept producing would
// feed the fMP4 client and hide the timeout this window exists to catch: the
// defect-era version of this test used 200 fragments at 20 ms, four seconds
// of them.
func TestAStalledFMP4ClientOnAHealthyChannelStaysConnectedLikeATSClient(t *testing.T) {
	const (
		streamTimeout = 1.0
		failoverGrace = 1.0
	)
	upstreamStall := 200_000
	r := fanRig(t, relaytest.Config{Rate: 8, DeadAirAfterBytes: upstreamStall}, map[string]any{
		"STREAM_TIMEOUT":        streamTimeout,
		"FAILOVER_GRACE_PERIOD": failoverGrace,
		// Compressed too, below the window: the fix's other exit, so a loop
		// that dropped the health gate and kept the cap is dropped at one
		// second here rather than passing on the 300s default.
		"MAX_KEEPALIVE_DURATION": 1.0,
	}, withRemux(standInRemux(t, "--fmp4-fragments", "5", "--fmp4-interval", "0")))

	ts := r.tuneAs(t, "c-row12", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	waitForHead(t, r, "c-row12", 1)

	fmp4 := r.tuneFMP4(t, "c-row12", "client-fmp4")
	defer func() { _ = fmp4.Body.Close() }()

	drained := make(chan int, 1)
	go func() {
		body, _ := io.ReadAll(fmp4.Body)
		drained <- len(body)
	}()

	window := 3 * time.Duration((streamTimeout+failoverGrace)*float64(time.Second))
	select {
	case sent := <-drained:
		t.Fatalf("the fMP4 client was dropped (%d bytes sent) on a HEALTHY channel inside %s: the loop timed it out on elapsed time alone (#222)", sent, window)
	case <-time.After(window):
	}

	ch := r.Manager.Get("c-row12")
	if ch == nil {
		t.Fatal("the channel stopped, so the window says nothing about either client")
	}
	if !ch.Healthy() {
		t.Fatal("the channel went unhealthy inside the window, which opens both loops' own exits: the assertion above would then be about the health monitor")
	}
	if got := ch.Clients(); got != 2 {
		t.Fatalf("the channel has %d clients after the stall, want 2: both loops hold a client on a healthy channel", got)
	}
}

// The other half of row 12: on an UNHEALTHY channel the fMP4 client is
// dropped where the TS client is -- MAX_KEEPALIVE_DURATION in, not
// stream_timeout + failover_grace_period in. Both are compressed, the cap
// (2s) well above the client timeout (0.5s), so the clock tells the two
// exits apart. The remux writes its five fragments at once and then stalls,
// so the fMP4 client is starved before the channel goes unhealthy -- under
// the defect it is dropped before the channel is even unhealthy, and the
// first check below says so.
//
// THE CLOCK IS TAKEN BEFORE THE EVENT IT BOUNDS: lastHealthy is read just
// before the last Healthy() call that returned true, so the flip -- and the
// cap's clock, which cannot start before it -- came after it, and the gap
// asserted is never shorter than the real one. (A first draft took it after
// the poll's own wait and measured 1.99s against a 2s cap once in a full
// package run under -race: the flip had landed inside the wait.) The control plane is held for 8s after
// the tune, so the failover the health monitor asks for cannot end the
// channel inside the six-second window: an fMP4 end well inside it is the cap's.
func TestAnFMP4ClientOnAnUnhealthyStallIsDroppedAtTheKeepaliveCap(t *testing.T) {
	const maxKeepalive = 2 * time.Second
	r := fanRig(t, relaytest.Config{Rate: 8, DeadAirAfterBytes: 200_000}, map[string]any{
		"CONNECTION_TIMEOUT": 0.3, "HEALTH_CHECK_INTERVAL": 0.05, "KEEPALIVE_INTERVAL": 0.05,
		"STREAM_TIMEOUT": 0.25, "FAILOVER_GRACE_PERIOD": 0.25,
		"MAX_KEEPALIVE_DURATION": maxKeepalive.Seconds(),
	}, withRemux(standInRemux(t, "--fmp4-fragments", "5", "--fmp4-interval", "0")))

	ts := r.tuneAs(t, "c-row12-cap", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	waitForHead(t, r, "c-row12-cap", 1)
	fmp4 := r.tuneFMP4(t, "c-row12-cap", "client-fmp4")
	defer func() { _ = fmp4.Body.Close() }()
	r.Control.SetDelay(8 * time.Second)
	ch := r.Manager.Get("c-row12-cap")
	if ch == nil {
		t.Fatal("the channel is not running")
	}

	ended := func(body io.Reader) chan struct{} {
		done := make(chan struct{})
		go func() {
			_, _ = io.Copy(io.Discard, body)
			close(done)
		}()
		return done
	}
	fmp4Done, tsDone := ended(fmp4.Body), ended(ts.Body)

	// lastHealthy is read BEFORE the Healthy() call that saw true, so the
	// flip -- which that call had not seen yet -- came after it.
	var lastHealthy time.Time
	for deadline := time.Now().Add(15 * time.Second); ; {
		before := time.Now()
		if !ch.Healthy() {
			break
		}
		lastHealthy = before
		if before.After(deadline) {
			t.Fatal("the channel never went unhealthy")
		}
		select {
		case <-fmp4Done:
			t.Fatal("the fMP4 client was dropped while the channel was still HEALTHY: it was timed out on elapsed time alone (#222)")
		case <-time.After(10 * time.Millisecond):
		}
	}
	if lastHealthy.IsZero() {
		t.Fatal("the channel was already unhealthy at the first look, so there is no clock taken before the flip")
	}

	select {
	case <-fmp4Done:
	case <-time.After(6 * time.Second):
		t.Fatal("the fMP4 client was still connected six seconds into an unhealthy stall against a two-second keepalive cap")
	}
	if took := time.Since(lastHealthy); took < maxKeepalive {
		t.Fatalf("the fMP4 client was dropped %s after the channel went unhealthy, before the %s keepalive cap: stream_timeout + failover_grace_period ended it (#222)", took, maxKeepalive)
	}
	select {
	case <-tsDone:
	case <-time.After(12 * time.Second):
		t.Fatal("the TS client outlived the fMP4 one by twelve seconds: the two loops no longer share an exit")
	}
}
```

### Appendix K — A-6 production: `detail.go`, `relay_serializers.py`, and the Python golden test

```diff
--- a/relay/httpapi/detail.go
+++ b/relay/httpapi/detail.go
@@ -115,22 +115,13 @@
 // detailPayload is get_detailed_channel_info, field for field and in
 // RelayChannelDetailSerializer's declaration order.
 //
-// TWO FIELDS THE SERIALIZER DECLARES ARE ABSENT HERE AND UNREACHABLE THERE,
-// which is exact parity by doing nothing -- the same shape as logo_id on the
-// list endpoint (channels.go):
-//
-//	source_bitrate  ChannelMetadataField.SOURCE_BITRATE has NO WRITER in the
-//	                tree. channel_status.py:359 is its only reference beside
-//	                the constant itself.
-//	ffmpeg_bitrate  channel_status.py:404 reads ChannelMetadataField
-//	                .FFMPEG_BITRATE ("ffmpeg_bitrate"), and the writer at
-//	                input/manager.py:1269 writes FFMPEG_OUTPUT_BITRATE
-//	                ("ffmpeg_output_bitrate"), which nothing reads. The two
-//	                constants are different strings (constants.py:90-91), so
-//	                the operator's output-bitrate reading never reaches this
-//	                payload in either relay.
-//
-// Both are reproduced as absences per D5 and filed rather than fixed.
+// ffmpeg_bitrate IS THE OUTPUT BITRATE THE STDERR READER PARSES, which is
+// issue #314's fix. In the Python relay it was read under one constant
+// ("ffmpeg_bitrate", channel_status.py:404) and written under another
+// ("ffmpeg_output_bitrate", input/manager.py:1269), so it never reached this
+// payload; the Go relay held the value in channel.Stats and dropped it here.
+// source_bitrate, which the serializer also declared and nothing in either
+// relay ever wrote, was removed from the serializer by the same fix.
 type detailPayload struct {
 	ChannelID      string                `json:"channel_id"`
 	State          *string               `json:"state"`
@@ -168,6 +159,7 @@
 	FFmpegSpeed    *float64              `json:"ffmpeg_speed,omitempty"`
 	FFmpegFPS      string                `json:"ffmpeg_fps,omitempty"`
 	ActualFPS      string                `json:"actual_fps,omitempty"`
+	FFmpegBitrate  string                `json:"ffmpeg_bitrate,omitempty"`
 	StreamType     string                `json:"stream_type,omitempty"`
 	Clients        []detailClientPayload `json:"clients"`
 }
@@ -348,6 +340,9 @@
 	if stats.ActualFPS != nil {
 		out.ActualFPS = pythonFloat(*stats.ActualFPS)
 	}
+	if stats.FFmpegOutputBitrate != nil {
+		out.FFmpegBitrate = pythonFloat(*stats.FFmpegOutputBitrate)
+	}
 	if stats.StreamType != nil {
 		out.StreamType = *stats.StreamType
 	}
--- a/apps/proxy/relay_serializers.py
+++ b/apps/proxy/relay_serializers.py
@@ -130,7 +130,6 @@
     video_bitrate = serializers.CharField(required=False)
     source_fps = serializers.CharField(required=False)
     pixel_format = serializers.CharField(required=False)
-    source_bitrate = serializers.CharField(required=False)
     audio_codec = serializers.CharField(required=False)
     sample_rate = serializers.CharField(required=False)
     audio_channels = serializers.CharField(required=False)
--- a/apps/proxy/tests/test_relay_detail_payload_golden.py
+++ b/apps/proxy/tests/test_relay_detail_payload_golden.py
@@ -40,28 +40,19 @@
     / "channel_detail.json"
 )
 
-# Two RelayChannelDetailSerializer fields the Go relay never emits, because
-# NEITHER RELAY CAN: each is read by channel_status.py and written by nothing
-# in the tree. Kept as a mapping with a reason for the list golden's reason --
-# a field in neither this mapping nor the fully-populated fixture fails
+# RelayChannelDetailSerializer fields the Go relay never emits, each with the
+# reason. Kept as a mapping with a reason for the list golden's reason -- a
+# field in neither this mapping nor the fully-populated fixture fails
 # test_the_fixture_covers_every_serializer_field, which is what stops the
 # golden from narrowing as the endpoint grows.
-NEVER_WRITTEN = {
-    "source_bitrate": (
-        "ChannelMetadataField.SOURCE_BITRATE has no writer anywhere in the "
-        "tree: apps/proxy/live_proxy/channel_status.py:359 is its only "
-        "reference beside the constant declaration itself, so the key is "
-        "never in the metadata hash and the `if source_bitrate:` never fires"
-    ),
-    "ffmpeg_bitrate": (
-        "channel_status.py:404 reads ChannelMetadataField.FFMPEG_BITRATE "
-        "('ffmpeg_bitrate') and the only writer, input/manager.py:1269, "
-        "writes FFMPEG_OUTPUT_BITRATE ('ffmpeg_output_bitrate'), which "
-        "nothing reads -- two different strings at constants.py:90-91, so "
-        "the operator's output bitrate never reaches this payload in either "
-        "relay"
-    ),
-}
+#
+# EMPTY SINCE ISSUE #314. It held source_bitrate, which nothing in either
+# relay ever wrote and which the serializer no longer declares, and
+# ffmpeg_bitrate, which the Go relay now emits from the output bitrate its
+# stderr reader parses. With it empty, a serializer that still declared
+# source_bitrate fails the completeness test below -- the pin for its
+# removal.
+NEVER_WRITTEN = {}
 
 
 def fixture():
@@ -135,6 +126,9 @@
         "ffmpeg_speed": 1.02,
         "ffmpeg_fps": "25.0",
         "actual_fps": "24.5",
+        # Issue #314: the output bitrate, str(round(kbps, 1)) as the other
+        # detail-endpoint rates are.
+        "ffmpeg_bitrate": "4200.0",
         "stream_type": "mpegts",
         "clients": [
             {
```

### Appendix L — A-6 Go tests (`detail_golden_test.go`, `transcode_test.go`)

```go
// detail_golden_test.go, detailGoldenPayload(): one line, after ActualFPS
		FFmpegBitrate: "4200.0",

// Issue #314, FIXED: ffmpeg_bitrate is on the payload, a string like the
// other detail-endpoint rates. Asserted against the GOLDEN, which Django's
// serializer rendered, so a relay that emitted the key under another name
// fails here. That source_bitrate is gone from the SERIALIZER is pinned on
// the Python side, by test_the_fixture_covers_every_serializer_field with
// NEVER_WRITTEN empty: a golden rendered from a fixture that never set the
// key cannot tell whether the serializer still declares it.
func TestTheDetailPayloadCarriesTheFFmpegOutputBitrate(t *testing.T) {
	golden, ok := decodeDetailGolden(t).(map[string]any)
	if !ok {
		t.Fatalf("the detail golden is not an object")
	}
	if got, isString := golden["ffmpeg_bitrate"].(string); !isString || got == "" {
		t.Errorf("ffmpeg_bitrate on the detail golden is %v (%T), want the output bitrate as a string (#314)", golden["ffmpeg_bitrate"], golden["ffmpeg_bitrate"])
	}
}

// Issue #314: the output bitrate the stderr reader parses reaches the DETAIL
// endpoint as ffmpeg_bitrate, a string rounded to one place as Python stored
// it. The expected value is read off the capture with a test-local pattern,
// not through the parser under test.
func TestTheDetailEndpointCarriesTheFFmpegOutputBitrate(t *testing.T) {
	_, records := relaytest.SplitCorpus(relaytest.Corpus("normal"))
	m := regexp.MustCompile(`bitrate=\s*([0-9.]+)kbits/s`).FindSubmatch(records[len(records)-1])
	if m == nil {
		t.Fatal("the normal capture's last record carries no bitrate=; re-derive (CAPTURE.md)")
	}
	kbps, _ := strconv.ParseFloat(string(m[1]), 64)
	want := strconv.FormatFloat(math.Round(kbps*10)/10, 'f', -1, 64)
	if !strings.Contains(want, ".") {
		want += ".0"
	}

	r := transcodeRig(t, nil, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	response := r.tuneAs(t, "c-bitrate", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-bitrate", 1)
	deadline := time.Now().Add(5 * time.Second)
	for {
		stats := r.Manager.Get("c-bitrate").Stats()
		if stats.FFmpegOutputBitrate != nil && *stats.FFmpegOutputBitrate == math.Round(kbps*10)/10 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("the output bitrate settled at %v, want the capture's last record %v", stats.FFmpegOutputBitrate, kbps)
		}
		time.Sleep(20 * time.Millisecond)
	}

	status, body := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-bitrate", nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d", status)
	}
	var detail map[string]any
	if err := json.Unmarshal(body, &detail); err != nil {
		t.Fatalf("decoding the detail body: %v", err)
	}
	if got := detail["ffmpeg_bitrate"]; got != want {
		t.Fatalf("ffmpeg_bitrate = %v (%T), want %q: the parsed output bitrate did not reach the detail payload (#314)", got, got, want)
	}
}
```

### Appendix M — A-7 production: `core/relay_events.py`

```diff
--- a/core/relay_events.py
+++ b/core/relay_events.py
@@ -12,6 +12,7 @@
 
 import logging
 import time
+import uuid
 
 from django.db import close_old_connections
 from django.utils import timezone
@@ -56,6 +57,31 @@
     return None if value == "" else value
 
 
+def _channel_uuid(value, details):
+    """The channel UUID an event names, or None -- and never a stream hash.
+
+    Issue #233. The relay posts the identifier it was tuned by as
+    channel_id, and /proxy/ts/stream/<stream_hash> -- the admin single-stream
+    preview -- is tuned by a Stream's sha256 hash, not a Channel's UUID
+    (apps/proxy/next_source.py's get_stream_object: "UUID check failed,
+    assume stream hash"). SystemEvent.channel_id is a UUIDField, so the hash
+    raised ValidationError inside log_system_event, whose bare
+    `except Exception` swallowed it: no row and no Connect fan-out for any
+    event of a preview tune -- channel_start, channel_stop and everything
+    between. The same rule get_stream_object applies decides it here: a
+    value that is not a UUID is written as details["stream_hash"] and the
+    row carries no channel, as vod_start's rows do.
+    """
+    if value is None:
+        return None
+    try:
+        uuid.UUID(str(value))
+    except ValueError:
+        details.setdefault("stream_hash", value)
+        return None
+    return value
+
+
 def _push(event):
     payload = {
         "success": True,
@@ -192,6 +218,7 @@
         details.pop("channel_id", None)
         details.pop("channel_name", None)
         details.pop("event_type", None)
+        channel_id = _channel_uuid(channel_id, details)
 
         # 2b-2: the relay posts a user id because it no longer holds a
         # User row on a live surface (apps/proxy/authorize_views.py's
```

### Appendix N — A-7 Python tests (`core/tests/test_relay_events.py`)

```diff
--- a/core/tests/test_relay_events.py
+++ b/core/tests/test_relay_events.py
@@ -48,7 +48,51 @@
         failover = SystemEvent.objects.get(event_type="channel_failover")
         self.assertEqual(str(failover.channel_id), channel_id)
         self.assertEqual(failover.details, {"reason": "dead_air"})
+
+    def test_a_stream_hash_tune_raised_no_lifecycle_rows(self):
+        """Issue #233. A /proxy/ts/stream/<stream_hash> preview tune posts
+        the Stream's sha256 hash as channel_id, and SystemEvent.channel_id
+        is a UUIDField: the write raised inside log_system_event and was
+        swallowed, so neither channel_start nor channel_stop left a row. The
+        hash now travels in details and the row carries no channel."""
+        from core.relay_events import apply_event_batch
+
+        stream_hash = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
+        counts = apply_event_batch(
+            [
+                {
+                    "type": "channel_start",
+                    "channel_id": stream_hash,
+                    "channel_name": "Preview Stream",
+                    "stream_id": 7,
+                    "details": {"stream_name": "Preview Stream", "stream_id": 7},
+                },
+                {
+                    "type": "channel_stop",
+                    "channel_id": stream_hash,
+                    "channel_name": "Preview Stream",
+                    "details": {"runtime": 12.5, "total_bytes": 1024},
+                },
+            ]
+        )
 
+        self.assertEqual(counts, {"accepted": 2, "rejected": 0})
+        for event_type in ("channel_start", "channel_stop"):
+            row = SystemEvent.objects.get(event_type=event_type)
+            self.assertIsNone(row.channel_id)
+            self.assertEqual(row.channel_name, "Preview Stream")
+            self.assertEqual(row.details["stream_hash"], stream_hash)
+
+    def test_a_uuid_channel_id_is_not_mistaken_for_a_stream_hash(self):
+        from core.relay_events import apply_event_batch
+
+        channel_id = "66666666-6666-4666-8666-666666666666"
+        apply_event_batch([{"type": "channel_start", "channel_id": channel_id, "details": {}}])
+
+        row = SystemEvent.objects.get()
+        self.assertEqual(str(row.channel_id), channel_id)
+        self.assertNotIn("stream_hash", row.details)
+
     def test_an_unknown_event_type_is_counted_as_rejected_not_raised(self):
         from core.relay_events import apply_event_batch
 
```

### Appendix O — A-7 Go contract pin (`relay/channel/manager_test.go`, appended)

```go
// ISSUE #233's relay half: a channel tuned by a STREAM HASH -- the admin
// single-stream preview, /proxy/ts/stream/<stream_hash> -- names that hash,
// verbatim, as the ChannelID of every event it raises. core/relay_events.py
// tells a hash from a channel UUID by parsing it, the rule next_source.py's
// get_stream_object applies, and records it as details["stream_hash"]; that
// only works if the relay passes the identifier through untouched, which is
// what this pins. The relay holds no rule of its own about identifiers.
func TestAStreamHashTuneNamesItsHashAsTheEventChannelID(t *testing.T) {
	const streamHash = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)
	ch, release := attachWith(t, m, streamHash, flowingSource{runs: &int32Counter{}}, testTuning(), nil)
	defer release()
	m.Stop(streamHash)
	<-ch.Done()

	for _, typ := range []string{"channel_start", "channel_stop"} {
		got := events.of(typ)
		if len(got) != 1 {
			t.Fatalf("%d %s events, want 1", len(got), typ)
		}
		if got[0].ChannelID != streamHash {
			t.Fatalf("%s named channel %q, want the stream hash it was tuned by, verbatim", typ, got[0].ChannelID)
		}
	}
}
```
