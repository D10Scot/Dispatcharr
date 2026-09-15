# Phase 2 PR 2c-7 — the Go relay's Output Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve **Output Profiles** from the Go relay: an optional downstream transcode reading the channel's shared ring on `pipe:0` and writing MPEG-TS on `pipe:1`, **one process per active `(channel, profile)` pair shared by every client on that profile** — parity-matrix **row 11**, "ten AC3 clients cost one ffmpeg". A client on a profile reads that process's output instead of the channel's own ring; an fMP4 client on a profile runs **two chained processes**, the transcode under `mpegts:p<id>` and 2c-6's remux under `fmp4:p<id>` reading it, exactly as `views.py:765-792` composes them. Row 11 gets a Go pin.

**Architecture:** `relay/output`'s `Pipeline` — 2c-6's spawn, writer, supervisor and stop — gains **a second sink**: an Output Profile transcode writes a `buffer.Ring` of MPEG-TS where the fMP4 remux writes a `buffer.Fragments` of MP4 boxes. That is a second constructor, `output.StartProfile`, **and an edit to `Pipeline` itself**: it binds `*buffer.Fragments` in five places — the struct field, the constructor, the accessor, `run`'s deferred close and `reader`'s scanner — and all five are reached (Ruling R11, which corrects 2c-6's R1 on exactly this point). `Channel.AttachOutput`'s refcount, its registry and its key **are** untouched, and the key is already the compound string `_parse_output_key` splits. The profile's argv comes off the wire — `output_profiles[*].argv` on the `next-source` answer (2b-2), cached per channel and refreshed by every later answer — so the relay builds no command line and splits no words (Amendment A4.1). `httpapi` resolves the client's profile against that cache, attaches the transcode, and hands the resulting ring to `serveClient` or to the remux, at exactly the point `views.py:765-776` does.

**This PR stays inert in every deployment**: every route is behind 2c-1's dev flag, and nginx routes nothing to port 5658 until stage 2d.

**Tech Stack:** Go 1.27.1, standard library only; three Python files changed (Ruling R4).

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — D1, D2, D5, D6, D7; the 2c-7 row of the nine-PR table (~line 1806); § Risks' note that `output/profile/manager.py` is "the least-understood code in the phase", deliberately ported last; Amendments A1.4 (settings off the wire), A2.2 (a Go pin is a reference in the existing `Pin` cell), A3.6 (a shared resource's context is not a client's), A4.1 (Django builds argv; the relay carries no word splitter), A4.7 (`go-tests.yml` runs in the base image), A5 as 2c-5 landed it, and A6 as 2c-6 lands it — **A6.1 named this PR's shape and A6.6 is its measurement**. This plan amends the spec in Task 8 where its text is silent, and says so in the Done log.

---

## Sequencing: this plan sits on 2c-6 as merged, on `main` at `eb7fac07`

2c-6's plan is **merged, on `main` at `9823cded`** (PR #305, `docs/superpowers/plans/2026-09-13-phase2-2c6-fmp4.md`; read it with `git -C <repo> show "9823cded:docs/superpowers/plans/2026-09-13-phase2-2c6-fmp4.md"` — cite `main`, not the `docs/phase2c6-plan` branch, which may be deleted — **brace the expansion in zsh**, or the `:path` is eaten as a history modifier and you get the tip commit's diff instead, exit code 0 and all).

**2c-6 IS MERGED, and this plan has been re-seeded from it.** `main` is **`eb7fac07`** (the squash of PR #308; `git diff --quiet 63e6494f eb7fac07` is empty, so the merge commit's tree is the branch head's). Every appendix here was re-extracted against that tree and the whole gate re-run on it — the results are in § What was verified on `eb7fac07` below.

**The module this plan's appendices were developed in was seeded with `git archive eb7fac07 relay`, every `_test.go` included** — 91 Go files, 42 of them tests — not from 2c-6's appendices and not from a reconstruction. That is the brief's rule, and this plan obeys it now where its first three drafts could not.

**The implementation differs from its own plan's appendices in four files, and none of them moves an anchor of this PR's.** Diffed file by file:

| File | Delta | Touches 2c-7? |
|---|---|---|
| `output/fmp4.go` | one comment line: `[#NNN]` → `[#307]` | edited by Appendix G, 15 lines from its nearest anchor — applied clean |
| `output/scanner_test.go` | one comment line: `[#NNN]` → `[#306]` | not touched |
| `httpapi/fmp4_test.go` | an 11-line doc comment above the row-12 test, rewritten (the stall is on the UPSTREAM, not the remux) | not touched |
| `ffmpeg/spawn_test.go` | **+121 lines, 80 of them code**: a new `TestAPipedProcessCanBeFedOnItsStandardInput` | not touched |

The fourth is worth naming because it is the one the orchestrator's summary did not: the implementation **added a test beyond its plan's appendices**, pinning `StartPiped`'s fd 0 round trip. Non-comment code changed in exactly that one file, and it is a file this PR does not edit.

**All fifteen of this plan's diff appendices applied to the real merged tree with `git apply` and no fuzz**, and the six whole-file appendices were copied in unchanged. That is a stronger statement than the earlier drafts could make, and it is what § What was verified rests on.

**Task 0's stop rule is still binding**, and it is now a confirmation rather than a discovery: every row of the ledger below was checked against `eb7fac07` while writing this, with the counts each row states. A symbol that differs from it means your seed is not `eb7fac07` — **stop and report**, never reconcile in passing.

### The 2c-6 dependency ledger

| 2c-6 shape this plan builds on | Where 2c-7 touches it | If your tree differs |
|---|---|---|
| `relay/output` exists, with `Pipeline`, `Config`, `Remux`, `Start`, `run`, `generation`, `writer`, `reader`, `scanner`, `readSize`, `stopJoinWait`, `FormatFMP4`, `InitSegmentTimeout`. **`Pipeline` binds `*buffer.Fragments` at five sites**: the struct field, `Start`'s constructor, the `Fragments()` accessor, `run`'s `defer p.frags.Close()` and `reader`'s `scanner{out: p.frags}` | Task 4 reaches **all five** (Ruling R11) — a `ring` field beside `frags`, a `Ring()` beside `Fragments()`, `defer p.closeSink()`, `generation` calling `p.read(proc)` — plus a `bsf` field and one guard in `generation`'s stderr callback; everything else is new in `output/profile.go` | a renamed `Pipeline`, `Config` or `Start` moves every anchor in Appendix G — **stop and report** rather than re-deriving. **A `Pipeline` that already carries a sink abstraction means 2c-6's fix round went further than this plan knows: read Ruling R11 before writing anything** |
| `Pipeline.run`'s retry arm calls `ffmpeg.StartPiped(ctx, p.cfg.command(), p.cfg.argvNoBSF())` | Task 4 leaves it alone and fills `cfg.Remux` for the profile pipeline so it could never spawn the fMP4 remux — Ruling R3's second half | if `run` no longer restarts at all, Ruling R3's structural guard is moot; say so and keep the field assignment |
| `Config.command()` returns `RemuxCommand` for an empty `Command`, and `Config.argv()` returns `RemuxArgv()` for a nil `Argv` | **Not used by the profile path**, deliberately (Ruling R3) | a `Config` whose zero value is no longer the production remux removes R3's reason; re-read it before simplifying |
| `channel/output.go` with `outputEntry`, `AttachOutput(format string, remux output.Remux)`, `releaseOutput`, `stopOutputs`, `outputRegistry`, `OutputFormats` | Task 5 changes `AttachOutput`'s second parameter to `OutputSpec` and adds one branch; the refcount, the lock order and both stop paths are **untouched** | a different `AttachOutput` signature is a one-line edit; a registry that is no longer a `map[string]*outputEntry` is a **stop** |
| `channel/channel.go` with `budgetBytes`, `outputRegistry` embedded, and `defer c.stopOutputs()` in `run` | Task 5 adds `outputProfiles` to the struct and two methods; the defer is untouched and Task 9 re-counts it | a missing `defer c.stopOutputs()` is a stop: break-check 13 patches exactly that line |
| `channel/manager.go`'s `Started{Source, Tuning, Info, Resolver}` and `publish`'s `&Channel{…}` | Task 5 adds one field to each | Appendix I gives both anchors |
| `channel/failover.go`'s `Resolved{Source, Info, Degraded}` and the switch's `c.mu.Lock()` block | Task 5 adds one field and three lines | a reshaped switch is a stop |
| `httpapi/stream.go`'s `StreamDeps{Secret, Channels, Control, Log, Now, Probe, Remux}`, `identify`'s `X-Relay-Output` **refusal**, `serveClient(ctx, w, rc, ch, client, log)`, `StreamHandler`'s `defer release()` → fMP4 branch → TS headers, `writeTuneFailure`'s switch | Task 6 replaces the refusal, adds a `ring` parameter to `serveClient`, inserts one block before the fMP4 branch and one case in `writeTuneFailure` | Appendix K gives every anchor; a handler that no longer branches on `client.OutputFormat` is a stop |
| `httpapi/fmp4.go`'s `serveFMP4(w, r, deps, ch, client, log)` and `ch.AttachOutput(output.FormatFMP4, deps.Remux)` | Task 6 adds a `source *buffer.Ring` parameter and composes the key | Appendix J |
| `httpapi/fanout_test.go`'s `fanRig`, `fanRigWith`, `rigSettings`, `tuneAs`, `listChannels`, `waitForHead`, and `TestAnOutputThisRelayDoesNotServeIsRefused`'s **three** rows with an `andFMP4 bool` field and an `output` import (the third row and both arrived in 2c-6's fix round) | Task 7 replaces all three profile-bearing rows and removes the `andFMP4` field, the `output` import and the `if tc.andFMP4` block with them; the helpers are used unchanged | **two** rows and no `andFMP4` means you seeded from before `eb7fac07` — re-seed. A test that no longer refuses `hls` is a stop |
| `httpapi/fmp4_test.go`'s `standInRemux`, `readAtLeast`, `rig.tuneFMP4` | Task 7 calls all three unchanged | a renamed helper is a find-and-replace in Appendix N |
| `httpapi/stream_test.go`'s `rigOption`, `withRemux`, variadic `newRig`/`newRigWithClient` | Task 7 uses `withRemux` unchanged | |
| `httpapi/golden_test.go`'s `TestTheLiveEndpointProducesTheGoldensKeySet`, whose live-row assertion says `output_profile_id` must be null "because 2c-3 serves no Output Profile yet" | Task 7 rewrites that **message** and keeps the assertion (Ruling R7) | |
| `internal/relaytest/standin.go` with `--spawn-log`, `SpawnCount`, `runFMP4StandIn`, the `-i pipe:0` copy loop | Task 3 adds `--ts-pid`, `--stdin-pid-log`, `rewritePID`, `StdinPacketPID` | a missing `--spawn-log`/`SpawnCount` is a **stop**: row 11's pin is a spawn count and Global Constraint 35 forbids substituting a registry count |
| `internal/relaytest/controlplane.go`'s answer builder, which sends `"output_profiles": map[string]any{}` unconditionally | Task 3 makes it configurable | |
| `internal/relaytest/fmp4.go`'s `SyntheticFMP4Init`, `SyntheticFMP4Fragment`, `FMP4ShapeProblem` | Task 7's chained test calls all three unchanged | |
| `relay/output/real_test.go`'s `requireFFmpeg` and `buildFragmentableAsset` | Task 4's real-ffmpeg test calls both unchanged | if `buildFragmentableAsset` no longer produces **AAC** audio, Appendix F's codec assertion loses its contrast — stop and report |
| Amendment **A6** in the spec | Task 8 appends **A7** after it | if A6 is numbered differently on `main`, cite the spec's number |
| `relay/output/fmp4.go:416`'s `[#NNN]` slot in `Pipeline.run`'s supervisor comment, which 2c-6's implementation fills with a real issue number before its PR opens | **Nothing.** Measured: that comment sits **15 lines** above Appendix G's nearest anchor (`defer p.frags.Close()`), and a unified hunk carries three lines of context, so the fill cannot move it | a filled slot is expected and is **not** drift. `grep -rn '\[#NNN\]' relay/` returning anything on the merged implementation is 2c-6's own Task 8 Step 5 failing, not this PR's problem — report it and carry on |

**Seed your scratch module from the merged tree INCLUDING its `_test.go` files.** Task 0 Step 0 is where the two are reconciled.

### What was verified on `eb7fac07`

Every number below was produced on the merged tree with this plan's appendices applied, in the foreground, and is what Task 9's own gate should reproduce.

| Gate | Result |
|---|---|
| `gofmt -l .` | silent |
| `go build ./...`, `go vet ./...` × native / `GOOS=linux` / `GOOS=darwin` | green |
| `golangci-lint run ./...` × the same three | `0 issues.` each |
| `scripts/check_go_credential_logging.sh relay` | `credlint: 11 package(s) clean` |
| `scripts/check_go_stdlib_only.sh relay` | `OK: relay depends on the standard library only.` |
| `relay/go.sum` | absent; `go.mod` is two lines with no `require` |
| `go test -race -count=1 ./...` | green **×3** |
| `go test -race ./channel ./output ./httpapi` | green **×8** (`channel` 74.8–75.9s, `output` 2.7–3.2s, `httpapi` 70.0–71.4s) |
| `go test ./ffmpeg ./channel ./output` **without** `-race` | green **×3** (`channel` 57.7–58.3s) |
| Appendices R, S and T re-applied as diffs | all three clean under `git apply --check` |
| `npx playwright test --project=guards parity-matrix` | **7 passed** with `relay/httpapi/profile_test.go` present; without it, one failure naming that file, which is correct on a plan-only branch |
| the two tests the review round added | `TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint` 0.13s, `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` 1.99s |
| suppressions in the module | **18** — sixteen on the merged 2c-6 tree, two this PR's |
| `TestARealAC3ProfileTranscodesTheChannelsRing` | PASS on the host at **ffmpeg 9.0.1** (0.15s) **and in the base image at 8.1.2** (0.12s) |
| `apps.proxy.tests` with the Django change applied | `Ran 379 tests … OK`, in a dedicated container on a **fresh** DB volume |
| the seeded `OutputProfile` rows | both present after that run — `1 Media Server (AC3 Audio) t t`, `2 Web Player (AAC Audio) t t` |
| `OutputProfileRefSerializer().fields['argv'].allow_null` | `True`, and `{'id': 9, 'argv': None}` renders as JSON null |


---

## Global Constraints

Every task's requirements implicitly include this section. Constraints 1–38 are 2c-1's through 2c-6's, restated because this plan is executed by an agent who has not read them; 39–45 are new, and 44 and 45 are inherited from 2c-6's own implementation round.

1. **Anchor every command with an absolute path, or open it with a `cd` into your own worktree.** The shell's working directory has been observed drifting into another agent's worktree with no `cd` issued.

2. **`go test -race` is mandatory on every Go test run: locally, in the hook, in the commit gate, in CI.** This PR adds three goroutines per Output Profile pipeline (writer, reader, stderr) plus a supervisor, all touching one `buffer.Ring`, and it adds a second entry to a refcounted registry two client goroutines mutate.

3. **Standard library only. No `require` line, no `go.sum`, ever.** `scripts/check_go_stdlib_only.sh relay` is the mechanical check. Everything here is in `bytes`, `context`, `encoding/json`, `errors`, `fmt`, `io`, `log/slog`, `net/http`, `os`, `strconv`, `strings`, `sync`, `time`.

4. **Nothing in `relay/` may open a Postgres connection or a Redis connection, in any task, including a test.** The six `output_*` Redis key families this PR would have needed (`output_owner`, `output_state`, `output_buffer_index`, `output_buffer_chunk`/`_prefix`, `output_chunk_timestamps`) are already deleted by spec D2 and by 2c-6; the Output Profile's own owner lock, state key and TTL refresh (`output/profile/manager.py:312-358`) go with them, for Ruling R2's reason.

5. **Every pin is tool-resolved on the day the PR is opened, never copied from this plan.** This PR adds no action pin and no image pin.

6. **zizmor blocks on every finding in any workflow file you touch.** This PR touches no workflow. `go-tests.yml` already runs in the base image (Amendment A4.7), which is what Task 4's real-ffmpeg test needs.

7. **Do not add a Docker `HEALTHCHECK`, a SIGTERM drain, or a `/readyz` that reports anything real.** Those are 2c-8's.

8. **Every Go constant that mirrors a Python literal carries its source `file:line` in a comment and is pinned by a test naming the same location.** This PR adds **no new numeric constant**: `readSize` (65536) gains `output/profile/manager.py:231` as a second citation beside `output/fmp4/manager.py:294`, and `stopJoinWait` (5s) gains `output/profile/manager.py:141`. The two **string** constants it does add are key shapes — `FormatMPEGTS` and the `:p<id>` suffix — pinned token for token by `TestTheProfileKeyIsMPEGTSWhateverTheClientFormat` against `views.py:731-734` and `output/profile/manager.py:303`.

9. **Prefer `t.Setenv` over manual environment save/restore, and never run an environment-mutating test with `t.Parallel()`.** Every test that spawns the stand-in calls `t.Setenv(relaytest.StandInEnv, "1")`, so none of them may be parallel.

10. **This PR DOES need a Django test run, and it must not be the shared `dispatcharr-testrunner` container.** Ruling R4 changes three Python files and `apps.proxy.tests` is the label that covers them. Start your own container from your own worktree and use it:

    ```bash
    cd <your worktree>
    DISPATCHARR_TEST_CONTAINER=<yourname> DISPATCHARR_TEST_DB_VOLUME=<yourname>-hookdb \
      .claude/hooks/start-test-container.sh
    ```

    The `PostToolUse` hooks ignore those variables and always drive `dispatcharr-testrunner`, so before letting an edit-triggered run happen, check where the shared container is mounted:

    ```bash
    docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
    ```

    If it is not your worktree, either re-point it — **after** checking nobody else is mid-task in the tree it currently holds (`docker ps`, and `stat -f '%Sm %N'` on that tree's recently-touched files; a modification younger than a few minutes means occupied) — or write the Python with `python3`/`sed` from a Bash call, which fires no hook, and run the label yourself. The exact invocation, measured working:

    ```bash
    docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
      -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
      -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
      -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
      <yourname> /dispatcharrpy/bin/python /repo/manage.py test apps.proxy.tests --keepdb
    ```

    **Without `DJANGO_SECRET_KEY` the run dies before the first test** with `ImproperlyConfigured: The SECRET_KEY setting must not be empty` — measured, and it looks like a broken container rather than a missing variable.

11. **Stage and commit in separate Bash calls, and write commit messages to a file and use `-F`.** The `PreToolUse` gate runs before the command, so one Bash call that stages and commits is blocked, and a message merely containing the words `git commit` trips it too.

12. **A provider URL is a credential and never reaches a log, an error message or a public response body.** This PR adds one new source of log lines — the transcode's own stderr — and it goes through `redact.Line`, inherited unchanged from 2c-6's `generation`. Python logs these at WARNING unredacted (`output/profile/manager.py:291`), the same divergence 2c-4's Ruling R8 and 2c-6's R8 record. The **argv** is never logged: an operator's Output Profile parameters are not a credential, but they are also not something any message here needs.

13. **A control-plane setting is read from the wire or the tune fails. Never from a Go-side default.** This PR reads **no new setting**: the transcode's join window is the channel's `Tuning.JoinBehind`, its retention `Tuning.Retention`, its write unit `Tuning.ChunkBytes` and its byte budget the manager's `BudgetBytes`. The **argv** is on the wire too (`output_profiles[*].argv`, 2b-2) and Ruling R3 is why it gets no Go-side fallback at all.

14. **Parity is against the code, not against the summary.** Every behavioural claim here carries a `file:line`. **Five places where reading the source — or running it — changed this plan**, each recorded in the ruling or the test that carries it: the Output Profile's Redis namespace is the literal `mpegts:p{id}` at six sites **whatever the client's output format**, so fMP4-plus-profile is a CHAIN of two processes and not one process under a combined key (`output/profile/manager.py:303`, `views.py:790-792`); `output_profiles[*].argv` carries the command as element 0 where `stream_profile.argv` does not (`apps/proxy/serializers.py:230` against `next_source.py`'s `_stream_profile_ref`); a profile omitted from that map is indistinguishable from a deactivated one, which is why Ruling R4 changes Django; the profile's `_stderr_loop` parses **nothing** where the remux's watches for the bitstream filter (`output/profile/manager.py:270-295`); and `transcode_active` is an input-side key with one USE in the whole tree — a `delete` — and no writer and no reader (Ruling R8; three grep lines, two of them the key helper's own def and return).

15. **Decide every lint finding in this plan, and re-lint after every `#nosec`.** This PR adds **two suppressions**, both in test-support code and both reasoned at the line: `internal/relaytest/standin.go`'s `os.ReadFile(path) // #nosec G304` in `StdinPacketPID` (a path the test itself chose, the same reason `SpawnCount`'s own G304 beside it carries) and `output/profile_real_test.go`'s `exec.CommandContext(...) // #nosec G204` on the ffprobe call (a `LookPath` result and fixed arguments, the reason `output/real_test.go`'s two carry). **An earlier draft of this constraint said "no suppression", which was simply wrong** — caught by review, and recorded rather than quietly corrected, because a census nobody recounts is how the next one drifts. Three OTHER findings were fixed rather than suppressed, and each changed the code for the better: two `nilerr` reports on `profileReader`'s `return nil` under an error check (closed by giving that function no error return at all — it has nothing to report), and one `unused` on a `setOutputProfiles` method the failover path did not end up calling (closed by deleting it and keeping one writer). Task 9 Step 5 lists the two additions by file and line. **Measured on `eb7fac07`: sixteen in the module before this PR, eighteen after** — 2c-6's own plan recounts fourteen for its own scope, so use the grep rather than either number.

16. **Run the four checks after every task, from the module root**, and treat any of the four failing as a stop:

    ```bash
    cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
    ```

    `gofmt -l .` must print nothing. Add `GOOS=linux` and `GOOS=darwin` passes of `go vet` and `golangci-lint` at Task 9 — Amendment A4.7's rule. **No task here edits `spawn_linux.go` or `spawn_other.go`**, so unlike 2c-6 there is no mid-plan three-GOOS pass to run.

17. **An ordering bug is not a data race, and `-race` is silent on every one of them.** This PR's instructive one: a `Pipeline` whose writer starts at `Source.Head()` on a ring nothing is still filling feeds its child **nothing at all**, for ever. Correct behaviour, and a fixture that never produces a byte — the first draft of Task 4's ring test failed after fifteen seconds with "the ring holds 0 chunks" and read as a broken pipeline. `JoinBehind` wider than the fixture is what makes it a test; production reads `new_client_behind_seconds`, which `output/profile/manager.py:180-184` sets for exactly this reason ("so the buffer is pre-populated by the time the first client connects").

18. **One mechanism per invariant.** This PR adds **no third writer of `StateActive`**: `promoteOnFirstChunk`'s assignment (`channel/channel.go:540` on `eb7fac07`, `:583` once Appendix L applies) and `reportBuffering`'s guarded recovery edge (`channel/stats.go:129`) stay the only two, and an output pipeline never touches channel state. Task 0 counts two, Task 9 counts two, and both name the lines. A pipeline is still stopped by exactly two mechanisms that cannot overlap — `releaseOutput` at a refcount of zero, and `stopOutputs` from `run`'s defers. The **failure** paths were collapsed to one for the same reason: see Ruling R4's last paragraph.

19. **The borrowed-slice contract is asserted, not enforced.** `Ring.Read` returns slice headers into the ring's own arrays, and 2c-3 named **this PR** as one of the two most likely to want to mutate one. It does not: the transcode's writer hands each chunk straight to `os.File.Write`, and `profileReader` hands its own read buffer to `Ring.Write`, which copies (2c-2's `TestAPublishedChunkIsNeverRewritten` asserts that by content).

20. **Do not widen the endpoint.** `GET /proxy/relay/channels` gains **no field and no route**: the only wire change on that endpoint is that a client's existing `output_profile_id` can now be a non-null integer. The single-channel `GET`/`DELETE`, the client `DELETE` and `advance` are 2c-8's.

21. **Every error-typed argument to a formatting or logging call in `relay/` passes through `redact.Error`, or carries `// credential-logging: ok - <reason>`.** `scripts/check_go_credential_logging.sh relay` reports the module clean at zero findings after this PR, across eleven packages. This PR adds **two markers**, both `encoding/json` type errors naming a JSON shape and never a value — `OutputProfileRef.UnmarshalJSON` and `NextSourceAnswer.UnmarshalJSON` (`control/nextsource.go`, the same shape 2c-4 and 2c-5 added for the other decoders) — and one `redact.Error` call, in `attachOutputProfile`'s failure log. **An earlier draft said one**; there are two decoders and each needs its own.

22. **Every line the stand-in writes to stderr came out of a real ffmpeg**, or is declared where it is written with the reason. This PR adds **none** — its stand-in additions are all on fd 0 and fd 1.

23. **The real-ffmpeg test fails rather than skips when `CI` is set and ffmpeg is absent.** Task 4's real test calls 2c-6's `requireFFmpeg` unchanged, which already carries that rule. Its **ffprobe** half skips rather than fails when ffprobe is absent, and says so in the skip message; the base image ships both.

24. **`Pdeathsig` is Linux-only by build tag, and its pin runs on Linux.** Unchanged. `StartProfile` reaches `ffmpeg.StartPiped`, which shares `sysProcAttr()` with `Start`, so the transcode gets the same process group and the same `Pdeathsig` — this PR adds no second copy and no second test.

25. **The stand-in is the test binary re-executed, and the trampoline is one per package.** `relay/output` and `relay/httpapi` both already have one; this PR adds none.

26. **The `Pdeathsig` and SIGKILL tests assert a mechanism, not an outcome.** Unchanged.

27. **A test's `Tuning` is built on `testTuning()` or `transcodeTuning()`, never as a bare literal.** This PR adds no test in `relay/channel` and so builds no `Tuning`; the `httpapi` tests reach their settings through `rigSettings`, which starts from `relaytest.EffectiveProxySettings()`.

28. **A test that measures a timeout takes its clock BEFORE the thing it measures starts.** No test in this PR measures a timeout. The two that wait — the stop tests — poll a condition with a fifteen-second ceiling and assert the condition, never the elapsed time.

29. **Compressed thresholds are on the wire, never patched.** No test here compresses one.

30. **A break-check that reddens on a different clause than predicted is recorded with the clause that fired.** Two of this plan's fifteen did, and both produced a better test rather than a footnote (§ Break-check, rows 8 and 12).

31. **Widen a sample window, never lower an asserted count.** The two stop tests wait fifteen seconds for a registry to empty; if a slow host makes one flaky, raise the fifteen, never weaken the emptiness.

32. **Every event this relay raises is one Python raises, with the same `type` and the same `details` keys.** This PR raises **none**. `output/profile/manager.py` calls `log_system_event` nowhere and posts no relay event — verified by grep, zero hits — so there is nothing here for 2c-8 to owe either.

33. **The fake control plane is one server answering three routes by path suffix**, and a test that asserts a request count names the route (`RequestsTo("/next-source")`).

34. **A shared resource's lifetime is never a client's request context.** `AttachOutput` starts its pipeline on `context.Background()`, and that is now load-bearing twice over: one transcode is shared by every client on the profile, and — for an fMP4 client on a profile — the transcode outlives the remux that reads it and vice versa. Unchanged from 2c-6; this PR adds no second context.

35. **A sharing claim is counted in SPAWNS, never in registry entries.** Demonstrated again here, for the Output Profile: with `AttachOutput`'s reuse branch disabled, the registry assertion (one key, `mpegts:p3`) and **both PID assertions** stayed green while the spawn count reddened at 2. `relaytest`'s `--spawn-log` and `SpawnCount` are the mechanism, and they are `output_support.py:83`'s `spawn_logging_standin` and `:111`'s `spawn_count` in Go.

36. **A break-check's patch and its revert must target a string that occurs exactly once in the file.** Every patch in § Break-check is applied by a script that **asserts its anchor is present** and prints `APPLIED <path>` — paid for here: one break-check's anchor guessed the wrong indentation, the patch silently did nothing, and the test ran green against unmodified code. The `assert` is what caught it. Re-run the package after every revert, not only after the patch.

37. **A real-ffmpeg fMP4 test needs at least eight seconds of asset** (Amendment A6.6). The Output Profile transcode has **no such threshold** — it is `-f mpegts` out, not `-movflags delay_moov` — and Task 4's real test measured at **0.3s** for four chunks from the same eight-second asset `buildFragmentableAsset` already builds. Recorded because A6.6 named this PR as the place to check.

38. **Nothing in this PR reads or writes the `output_*` Redis keys, and nothing reinstates an owner lock.** Ruling R2.

39. **The Output Profile argv carries the COMMAND as element 0 and `stream_profile.argv` does not.** `core/models.py:200-203`'s `build_command` is `[self.command] + shlex_split(self.parameters)` and `apps/proxy/serializers.py:230` sends the result whole, where `next_source.py`'s `_stream_profile_ref` sends `command` in its own field and the rest in `argv`. The split happens in exactly two places — `control.OutputProfileRef.Command()/Args()` and `channel.OutputProfile.Command()/Args()` — and both are pinned. Nothing else indexes `Argv[0]`.

40. **Three states on the wire, not two, and they get three different answers.** A profile **absent** from `output_profiles` was deactivated between the authorize hop and the tune: serve the client with no profile and register null (`views.py:150-155`, `:725-751`). A profile **present with a null argv** is one Django could not build: 500. **`output_profiles` itself absent** is a control plane older than 2b-2: 502, the same class as an absent `proxy_settings` key. Ruling R4 is why the middle state exists at all.

41. **A pass-through stand-in cannot pin which ring a client read.** Its output equals its input, so the profile's ring and the channel's hold the same bytes and no assertion on them can fail. `--ts-pid` rewrites every packet's PID, which keeps the output a valid same-length transport stream and makes its provenance readable from any packet; `--stdin-pid-log` does the mirror image for a chained process's fd 0. Both were added because a break-check stayed green without them (§ Break-check, rows 2 and 12).

42. **A substring assertion pins nothing when the string has more than one source, and `os/exec` is a source.** Paid for here: `TestAProfileWithNoCommandIsRefusedRatherThanDefaultedToTheRemux` asserted `strings.Contains(err, "no command")` and stayed **green** with the guard it tests removed, because `os/exec`'s own message for an empty `Path` is literally `exec: no command`. Closed with `errors.Is(err, ErrProfileCommandAbsent)`.

43. **`relay/output`'s `fmp4.go` now holds the shared pipeline and is not renamed.** Ruling R1. Its package doc says so; a future PR may split it, and this one deliberately does not.

44. **A gate this plan writes must be able to PASS, and a grep whose emptiness you interpret must be scoped by path.** Inherited from 2c-6, which wrote a `grep -rn '\[#NNN\]' relay/ docs/` gate that could not: `docs/` recursively contains 2c-6's own plan, whose `[#NNN]` table lists the slots, so the gate matched its own documentation and could never return empty. **This plan is now a second such file** — it carries four `[#NNN]` occurrences of its own, in the ledger row about `output/fmp4.go:416` and in this constraint — so a recursive `docs/` grep is further from passing today than when 2c-6 wrote it, which is the point: a gate whose corpus grows cannot be fixed by tidying one file. **Scope by path, never `docs/` recursively**, and name the files. This PR writes exactly one grep whose emptiness is the assertion — Task 9 Step 3's `ls relay/go.sum`, which is a single path — plus the `[#NNN]` check it does **not** write, because this PR files no issue and leaves no slot (Task 8's amendment and matrix row carry real references only). If you add one, check it can fail: create the thing it looks for, watch it go red, delete it. And never `2>/dev/null` it, and never read `$?` through a pipe.

45. **A break-check's revert targets a string that occurs exactly once in the file.** Already Constraint 36 here, and restated as 2c-6's own implementation round re-learned it. Constraint 36's other half — that every patch **asserts its anchor and prints on success** — is what this plan pays for in § Break-check row 7.

### The six ways a Go test can be green and meaningless

Every test this PR adds is bound by all six, and every task that adds an assertion ends with a **break-check**: patch the defect in, watch the test go red *for the right reason*, revert. **A break-check that does not go red is a finding, not a formality** — three of this plan's fifteen did not, and all three produced a better test (§ Break-check, rows 2, 8 and 12).

1. **The tautological oracle.** Every expected value is a literal or a Python line: `mpegts:p3` is `output/profile/manager.py:303`; the four `FormatKey` rows are `views.py:731-734`; the 500 body is `views.py:771`'s exact JSON; the AC3 argv is `core/migrations/0024_outputprofile.py` read token for token; the decoded argv in `TestTheOutputProfileArgvCarriesTheCommandFirst` is `apps/proxy/tests/test_next_source_api.py:551`'s own expected value. The codec assertion in the real test is read back by **ffprobe**, a different program.

2. **A pin that supplies the default pins nothing.** The `FormatKey` table asserts the nil arm **and** the non-nil arm; the mixed-client tests assert the profile client's PID **and** the plain client's; the deactivated-profile test sends an answer carrying a **different** active profile, so "the map is empty" cannot be what makes it pass.

3. **A test can go hollow without changing.** Every break-check below names the edit and the message that appeared.

4. **A fixture that patches away the subject.** The Output Profile tests drive a real subprocess through the real `ffmpeg.StartPiped`, because the relay's reaction to a process is the subject — and the stand-in **transforms** its input (`--ts-pid`) rather than copying it, because a copier makes the subject invisible (Constraint 41). The one test whose subject is the bytes a real transcoder produces uses real ffmpeg and the **migration's own** argv, with no substitution.

5. **A substring assertion pins nothing when the string has more than one source.** Constraint 42, and its scar.

6. **A true positive for a false reason.** The chained test asserts four things together — two spawns, two registry keys, an fMP4 body, and the PID the remux was fed — because any three are satisfiable without the chain.

### Working rules

- Run the four checks after every task (Constraint 16), then `scripts/check_go_credential_logging.sh relay` and `scripts/check_go_stdlib_only.sh relay` (Constraints 21 and 3). Both scripts take the module directory **relative to the repo root** and must be invoked from there, not from inside `relay/`.
- **Run `relay/output` at least eight times consecutively under `-race` before Task 4 is committed**, and the Output Profile subset of `relay/httpapi` eight times before Task 7. Measured here: `relay/output` eight for eight at ~2.7s, the httpapi subset (`-run 'Profile|Transcode|Chained|Output'`) eight for eight at ~4.8s, the whole module three for three.
- Stage and commit in separate Bash calls; write commit messages to a file and use `-F`.
- Every commit message ends with the attribution lines this session was given.
- **Every Go file in this plan has been built, vetted (native, `GOOS=linux`, `GOOS=darwin`), race-tested and linted at zero findings before this plan was written**, in a scratch module seeded as § Sequencing describes. Where you find a discrepancy, **your tree is the fact and this plan is the claim — stop and report it** (Task 0 Step 0).

---

## Rulings

Decisions this plan makes that the spec leaves open, that 2c-6 left to its successor, or that the tree contradicts. Each is binding; each names what it was decided against.

### R1 — `output/fmp4.go` keeps the shared pipeline and is NOT split or renamed

2c-6's Ruling R1 promised 2c-7 would "add a dimension and rewrite nothing", and after this PR `fmp4.go` holds `Pipeline`, `run`, `generation`, `writer` and the sink branch — machinery both processes share — under a name that describes only one of them. The obvious tidy-up is to move the shared half into `output/pipeline.go`.

**Ruled: do not move it.** A file move shows in a branch diff as a whole delete plus a whole add, so every line of 2c-6's carefully-reviewed prose re-enters review to buy a better file name, and this plan was written against a 2c-6 that had not merged — a predecessor fix round that touched `fmp4.go` would invalidate a moved appendix completely where it invalidates one hunk of a diff. The package doc says the file's name is narrower than its contents and why, and the split is left as a recommendation for 2c-9, whose own diff is mostly a floor file.

Decided against a `relay/output/profile` sub-package: `Pipeline` is unexported-field-heavy and a sub-package would have to export `ring`, `bsf` and `closeSink` to reach them.

### R2 — The owner lock, the state key and the TTL refresh are DELETED, not ported, and the map is the answer

`OutputProfileManager` carries the same three-way coordination the fMP4 remux does: `_acquire_owner_lock`/`_release_owner_lock` (`output/profile/manager.py:312-327`), `_set_state` (`:329-335`), `_refresh_redis_ttls` (`:337-358`), plus `ensure_output_profile`'s staleness question and its non-owner reader-buffer branch (`server.py:1406-1538`, five arms including a 5-second `live:events:` round trip so a non-owner can ask the owner to start one).

**All of it goes, for spec D2's stated reason and 2c-6's Ruling R3 applied unchanged**: those mechanisms exist so a second uWSGI worker can discover another worker's process, and with one relay process the registry map *is* that discovery. `PROFILE_KEY_TTL` (3600) and `PROFILE_TTL_REFRESH_INTERVAL` (60) exist so an orphaned key cannot outlive the process that wrote it, and nothing here can be orphaned. `_cleanup_redis`'s chunk-key scan (`:360-389`) goes with them — a Go ring is freed by the garbage collector.

**The lifecycle that survives is the refcount, and it stops at zero with NO shutdown delay.** Python's disconnect sweep reads every remaining client's `output_profile_id` and stops any transcode no longer named (`server.py:1216-1219`), and it runs **before** the `if total == 0` branch at `:1221` that honours `channel_shutdown_delay` — so the last profile client leaving stops the transcode at once while the channel itself lingers. Identical in shape to the format sweep 2c-6 ported; pinned by `TestTheLastProfileClientLeavingStopsTheTranscodeAndNotTheChannel`.

### R3 — `ProfileConfig` is its own type, because `Config`'s zero value is the fMP4 remux

2c-6's Ruling R1 named `output.Remux` as "the seam that names the process" and said 2c-7 would reach through it. **Reading its zero-value semantics is what changed that.** `Config.command()` returns `RemuxCommand` for an empty `Command` and `Config.argv()` returns `RemuxArgv()` for a nil `Argv` — correct for an fMP4 pipeline whose default *is* the production remux, and exactly wrong for an Output Profile, where an empty command means the operator's row is broken and the tune must fail. A profile reaching `Config` with a blank command would silently become an ffmpeg remux.

**Ruled: `StartProfile` takes its own `ProfileConfig` with explicit `Command` and `Argv` and no fallback**, and refuses an empty command with `ErrProfileCommandAbsent` before spawning. Python reaches the same failure one step later (`posix_spawn_proc([""])` raises, `start()` returns False at `manager.py:89-95`, `ensure_output_profile` returns False, `views.py:767-772` answers 500), so the status is parity and only the log differs.

**The same trap survives inside `Pipeline`, and it is closed structurally.** `run`'s bitstream-filter retry calls `ffmpeg.StartPiped(ctx, p.cfg.command(), p.cfg.argvNoBSF())`. A first draft left the profile pipeline's `cfg.Remux` empty on the reasoning that `bsf` is false so the arm is unreachable — and the break-check that set `bsf` to true proved how bad that reasoning was: the retry spawned a **real ffmpeg remux**, the spawn log stayed at one because the second process was not the stand-in, and the test reported "still running" instead of "two spawns". `StartProfile` now fills `cfg.Remux` from the profile's own command line, so even an unreachable retry respawns the right process, and the break-check reddens in 0.02s on the count. Two guards, and the structural one is the field assignment.

Decided against adding a `Kind` field to `Config` and branching inside `Start`: one constructor with two zero-value meanings is the thing this ruling exists to avoid.

### R4 — Django sends a NULL argv instead of omitting a malformed profile, and that is a three-line contract change this PR owns

`_with_output_profiles` (`apps/proxy/next_source.py`) catches `build_command()`'s `ValueError` — `shlex` refusing an unbalanced quote in `parameters`, which `OutputProfileSerializer` validates nothing against — logs it, and **skips the entry**, so one bad row cannot 500 next-source for every channel. That rescue is right and this PR keeps it.

**What it cannot express is the difference between two profiles that get opposite answers.** A profile **deactivated** between the authorize hop and the tune is also absent from the map, and Python serves that client with **no profile at all** (`views.py:150-155` re-reads the row with `is_active=True`, gets `None`, and `:725-751` registers the client with that `None`). A profile Django could not **build** is present and active, and Python **500s** the client that selects it (`build_command()` raises inside `stream_ts`'s try, `:823-827` answers 500). On the wire both are the same absence, so a Go relay reading this map can reproduce one of them and not the other — and the one it would silently get wrong is the 500, meaning a device that needs AC3 is handed the original audio and nothing says so.

**Ruled: the entry is sent with `"argv": null`.** Three states, exactly `stream_profile.argv`'s (Amendment A4.1): a list is the built command, JSON null is "Django could not build it", the key absent is a control plane older than 2b-2. `OutputProfileRefSerializer.argv` gains `allow_null=True`; `_with_output_profiles`'s `except` sets `argv = None` and falls through instead of `continue`; the log line stays, because it is still the operator's only signal. `apps/proxy/tests/test_next_source_api.py`'s `test_a_malformed_active_profile_is_skipped_not_a_500` is renamed and inverted, and gains a **deactivated** row created before the call so the answer really had the chance to carry it — the two states are only being told apart if both appear in one answer.

This is the same class of change the brief authorises for A4.1, and it is the whole of this PR's Django footprint: three files, no migration, no new route, no new field.

**The 500's BODY is parity for one of the two faults and a stated divergence for the other.** `views.py:771`'s `{"error": "Failed to start output profile transcode"}` is reproduced character for character; Python's unbuildable-profile 500 carries `str(ValueError)` — shlex's own message — which never crosses this wire and cannot be reconstructed from anything the relay holds. **One failure branch serves both**, deliberately (Constraint 18): an earlier draft had a separate `Buildable()` check in `httpapi` whose break-check could not redden, because removing it left `StartProfile` producing the same 500. The distinction that survives is in the log, where `redact.Error(err)` names `ErrProfileCommandAbsent` or the spawn error.

### R5 — The profile set is cached PER CHANNEL and refreshed by every next-source answer, never per client

Python resolves the Output Profile row **per client** (`views.py:150-155`, reached from both the owner-init and follower branches of `stream_ts`). The relay cannot: `next-source` runs once per channel, the second client on a running channel makes no control-plane call at all (`views.py:712`), and 2b-2's Ruling R3 already rejected a per-client route — which is why the whole active set travels on every answer, "and a Go relay caches it per channel".

**Ruled: `channel.Channel` holds the set from the tune's answer and replaces it on every later answer a failover receives from the control plane.** Not a start-time snapshot like `Tuning`: `Tuning` is snapshotted because `StreamManager.__init__` snapshots it (parity row 5), and the profile row is the opposite — Python re-reads it every time. Refreshing on failover costs one field on `Resolved` and three lines under the switch's existing `Lock`, and it is strictly closer to Python than a snapshot.

**A DEGRADED resolution refreshes nothing**, and that falls out rather than being arranged: it came from the candidate list cached at channel start and carries no answer, so `Resolved.OutputProfiles.Known` is false and the channel keeps what it had.

**The residual divergence, stated:** an operator who edits an Output Profile's `parameters` while a channel is running reaches new clients on that channel only after its next `next-source` call — a failover, a resume, or a restart — where Python reaches them on the next tune. Not fixed, because fixing it needs the per-client route 2b-2's R3 rejected, and not tested, because there is no Python behaviour there to pin — only the absence of one.

**The REFRESH itself is tested, and an earlier draft of this ruling wrongly implied it was not.** That draft said only the divergence went unpinned, which left the impression that everything else here was covered; it was not. Deleting the two-line assignment in `channel/failover.go` left the **entire** suite green — found by review, not by this plan. `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` now pins both halves of the rule in one test: an operator changes the active set between two answers and a failover that reaches Django picks it up (break-check 17), while a **degraded** failover leaves the channel's copy alone (break-check 18). Both arms belong together, because a relay that refreshed from the cached candidate list would CLEAR the map rather than update it, and a one-armed test would call that a pass.

**The read hands out the map without copying it, and that is safe because nothing mutates it in place** — every write replaces the whole struct. `OutputProfiles()` takes `RLock`; the failover writes under the switch's `Lock`. `AttachOutput` never reads it, so `outMu` still never nests with `mu`.

### R6 — `X-Relay-Output` is SERVED, and a malformed one is 400 rather than 501

2c-3's Ruling R10 refused any non-empty `X-Relay-Output` with 501, "until Output Profiles are served". They are served now, so the refusal goes and the 501 subtest's Output Profile row goes with it — the mirror of 2c-6's own Task 8 Step 1, which moved that test's format row from `fmp4` to `hls`.

**What is still refused is a value that is not a positive integer**, and it is answered **400**. `apps/proxy/authorize_views.py:154-162` already denies a non-digit `X-Relay-Output` with 403 one hop earlier, so a relay only ever sees `""` or digits through nginx, and this branch is reachable only when the internal contract is broken. There is no Python status to reproduce; 400 is the relay saying the header it was handed is not a profile id, where 403 would be an authorization decision it is not making. **The value is never echoed into the body**, asserted by the same subtest.

`ErrUnsupportedOutput.ProfileID` stays on the struct and is never set again: it is what the 501 log line named for two stages, and removing it would silently narrow the message for a case that no longer arises.

### R7 — The golden fixture is NOT extended; the live list endpoint is where the profile claim is pinned

`apps/proxy/tests/test_relay_list_payload_golden.py`'s fixture **already** carries `output_profile_id: 7` on one client and `null` on the other, and `relay/httpapi/testdata/channels_clients_all.json` already renders both. The serializer behaviour this PR could add to it — an integer rather than a null — is already exercised.

**The claim worth pinning is a different one**: that a real tune naming a profile puts that id in the registry, and a real tune naming none puts null there. That is a property of `identify`, `attachOutputProfile` and `SetClientOutputProfile`, not of the serializer, and `TestTheListPayloadNamesEachClientsOwnOutputProfile` asserts it against the live endpoint with one client of each kind — plus the key's **presence** on both rows, which `channel_status.py:579-582` sets on both branches and which a value check alone would miss.

2c-6's Ruling R11 made the same call for `output_format` and this is the same reasoning; the difference is that this PR **does** touch Python, for Ruling R4's unrelated reason, so "this PR touches no Python file" is not among its claims.

`golden_test.go`'s `TestTheLiveEndpointProducesTheGoldensKeySet` keeps its `output_profile_id` must-be-null assertion and gets a **new message**: its old one said "2c-3 serves no Output Profile yet", which stops being true here and would read as a stale comment rather than as the claim it still makes.

### R8 — `transcode_active` is an input-side key with no writer and no reader, and this PR does not touch it

The brief asks what the `transcode_active` metadata field means for an Output Profile. **Nothing.** `RedisKeys.transcode_active` (`apps/proxy/live_proxy/redis_keys.py:89-91`) has exactly one reference in the non-test tree — a `delete` in `input/manager.py:1797`, on the transcode teardown path — and no writer and no reader anywhere. It is an input-side key about the channel's own ffmpeg, not about an Output Profile, and it is dead in the Python relay already. It appears on no payload: `channel_status.py` never reads it.

Recorded so the next reader of the brief does not go looking, and left alone: deleting dead Python is 2d's job, not this PR's.

### R9 — fMP4 and an Output Profile COMPOSE, as a chain of two processes, and the registry key is Python's own compound string

The brief asks whether the two combine and, if not, with what status they are refused. **They combine.** `views.py` runs `ensure_output_profile` first (`:765-767`), resolves `get_buffer(channel_id, profile=id)` second (`:773-776`), and hands **that** buffer to `ensure_output_format` as `source_buffer` under the key `f'fmp4:p{id}'` (`:731-734`, `:790-792`). The transcode's own Redis namespace is the literal `f"mpegts:p{self.profile_id}"` at six sites in `output/profile/manager.py` — **always `mpegts`, whatever the client asked for** — because an Output Profile's output *is* MPEG-TS (`core/models.py:173-174`). So the two live under two keys that cannot collide, and the second reads the first.

**Ruled: one registry, keyed by the compound string, and the composition lives in `httpapi` where `views.py` puts it.** `output.ProfileKey(id)` is `mpegts:p<id>`; `output.FormatKey(format, id)` is `views.py:731-734`'s `f'{fmt}:p{id}' if profile else fmt`. `attachOutputProfile` returns the ring, and `serveFMP4` passes it as the remux's `Source`. Two `defer`s in the handler, released in the right order by Go's own LIFO rule.

Decided against a `(channel, format, profile)` triple key: the compound string is what Python writes, what `_parse_output_key` reads, and what the disconnect sweep compares (`server.py:1187-1196` builds `f"{fmt}:p{pid}"`), so a structured key would be a second spelling of an existing one.

### R10 — `serveClient` takes the ring it should read rather than asking the channel for one

Python's `StreamGenerator` is handed its buffer (`output/ts/generator.py:673-698`, and `:51-52`'s own docstring: "passed in so the generator is buffer-agnostic"), and everything else it consults — the health flag, the keepalives, the error packet — stays the CHANNEL's. The Go loop did `ring := ch.Ring()` inline.

**Ruled: `serveClient` takes a `ring *buffer.Ring` parameter and nothing else changes.** One parameter, one call site, and the health gate, the keepalive cap and `errorPacketMessage` keep reading `ch`. A profile client is therefore subject to exactly the same client timeout and keepalive behaviour as a plain one, on a ring the channel does not own — which is Python's shape.

Decided against `ch.Buffer(profileID)`: `get_buffer`'s Python signature exists because `ProxyServer` owns both maps, and reproducing it would put the profile registry back inside `Channel` where `AttachOutput` already keeps it.

### R11 — The second sink is two nil-able fields and three branches on `Pipeline`, not a sink interface and not a second pipeline type

**2c-6's R1 sentence — that 2c-7 "adds a second `Pipeline` constructor and a second sink type, not a change to the lifecycle, the refcount or the spawn" — overstates the constructor's share of the work, and this ruling is the correction.** The refcount and the key really are ready: `AttachOutput(format string, …)` keys on an arbitrary string, so `mpegts:p3` and `fmp4:p3` slot in with no edit at all. But `Pipeline` **binds `*buffer.Fragments` in five places**, and a transcode emits MPEG-TS, so every one of them has to be reached:

| | site in 2c-6's `output/fmp4.go` | what 2c-7 does |
|---|---|---|
| 1 | the struct field, `frags *buffer.Fragments` (`:338`) | a sibling field `ring *buffer.Ring` |
| 2 | `Start`'s constructor, `frags: buffer.NewFragments(…)` (`:375`) | `StartProfile` builds its own `Pipeline` with `ring:` set and `frags` nil |
| 3 | the accessor `Fragments()` (`:388`) | a sibling `Ring()`, nil for the other kind |
| 4 | `run`'s `defer p.frags.Close()` (`:431`) | `defer p.closeSink()` |
| 5 | `reader`'s `s := &scanner{out: p.frags}` (`:594`) | `generation` calls `p.read(proc)`, which branches |

plus one caller outside the package, `httpapi/fmp4.go:53`'s `pipeline.Fragments()`, which is untouched because an fMP4 client still wants fragments.

**Ruled: two nil-able fields, three branches on `p.ring != nil`, and exactly one of the two non-nil for a pipeline's life** — set by its constructor, never reassigned, so the branches need no lock and `-race` has nothing to find.

**Decided against a `sink` interface** (`write([]byte) error; final(); Close()`, unexported so nothing outside the package can implement it). It is the tidier shape and it does not fit, for a reason that only appears on the retry path: `reader` builds a **fresh** `scanner` per generation, deliberately, because the no-bitstream-filter restart must re-scan generation 2's leading bytes as an init segment (`SetInit` then keeps the first, 2c-6's R10). A single long-lived sink object on `Pipeline` cannot express that, so the interface would need a **factory** field plus a separate close field — two function-typed fields where the branch is one boolean test, and a reader of `generation` would have to follow both to learn what the process's output does.

**Decided against a second `Transcode` type.** `outputEntry.pipeline` is a `*output.Pipeline` and `AttachOutput` returns one; two types means the registry, the refcount and both stop paths become generic over them — which is precisely the "change to the lifecycle, the refcount or the spawn" 2c-6's R1 promised not to make, arrived at from the other direction.

**The honest size, stated so a reviewer can check it rather than take it:** Appendix G is a **127-line diff** to `output/fmp4.go`, of which about half is comment; Appendix H is a new 202-line file. Small and localised, and not "a constructor".

---

## File Structure

**New, in `relay/`:**

| File | Responsibility | Lines |
|---|---|---|
| `output/profile.go` | The Output Profile transcode: `FormatMPEGTS`, `ProfileKey`, `FormatKey`, `ErrProfileCommandAbsent`, `ProfileConfig`, `StartProfile`, `profileReader`. | 202 |
| `output/profile_test.go` | The key table, the ring, the empty command, the absent bitstream-filter retry, the two stops. | 231 |
| `output/profile_real_test.go` | The one real-ffmpeg test, on the migration's own AC3 argv, with ffprobe reading the codec back. | 137 |
| `httpapi/profile.go` | `attachOutputProfile` (the three wire states and their three answers), `writeProfileFailure`, `outputProfilesFrom`. | 139 |
| `httpapi/profile_test.go` | Row 11's pin, the mixed channel, the chain, the registry's profile id, the four failure shapes, the concurrent-list race pin and the failover refresh. | 778 |
| `control/outputprofile_test.go` | The argv's command-first shape and the decoder's three states. | 112 |

**Modified:**

| File | Edit |
|---|---|
| `control/nextsource.go` | `OutputProfileRef` with its `UnmarshalJSON`, `Command()`, `Args()`; `OutputProfiles`/`OutputProfilesPresent` on `NextSourceAnswer` with its `UnmarshalJSON`. |
| `output/fmp4.go` | `Pipeline.ring`, `Pipeline.bsf`, `closeSink`, `read`, `Ring()`; `run`'s defer; one guard in `generation`'s stderr callback; two doc sentences. |
| `channel/output.go` | `OutputProfile`, `OutputProfiles`, `OutputSpec`; `AttachOutput`'s second parameter and one branch. |
| `channel/channel.go` | `outputProfiles` on the struct; `OutputProfiles()`; `SetClientOutputProfile()`. |
| `channel/manager.go` | `Started.OutputProfiles`; one line in `publish`. |
| `channel/failover.go` | `Resolved.OutputProfiles`; three lines under the switch's `Lock`. |
| `httpapi/stream.go` | `identify` accepts `X-Relay-Output`; `ErrOutputProfileMalformed`; one case in `writeTuneFailure`; the profile block in `StreamHandler`; `serveClient`'s `ring` parameter; one corrected comment. |
| `httpapi/fmp4.go` | `serveFMP4`'s `source` parameter and the composed key. |
| `httpapi/failover.go` | `resolved` takes and carries the profiles. |
| `httpapi/fanout_test.go` | `TestAnOutputThisRelayDoesNotServeIsRefused`: the Output Profile row becomes two malformed-value rows at 400, plus a body-echo assertion. |
| `httpapi/golden_test.go` | One assertion message. |
| `internal/relaytest/asset.go` | `PacketPID`. |
| `internal/relaytest/asset_test.go` | Its pin, including `rewritePID`'s carry. |
| `internal/relaytest/standin.go` | `--ts-pid`, `--stdin-pid-log`, `rewritePID`, `StdinPacketPID`. |
| `internal/relaytest/controlplane.go` | `OutputProfiles`, `OutputProfilesAbsent`, `OutputProfileConfig`, `SetOutputProfiles` (the mutable override a mid-channel edit needs), and the answer builder's new block. |
| `apps/proxy/serializers.py` | `OutputProfileRefSerializer.argv` gains `allow_null=True` (Ruling R4). |
| `apps/proxy/next_source.py` | `_with_output_profiles`'s `except` sets `argv = None` instead of `continue` (Ruling R4). |
| `apps/proxy/tests/test_next_source_api.py` | The malformed-profile test renamed and inverted; a deactivated row added. |
| `docs/relay-parity-matrix.md` | Row 11 gains its Go pin. One line. |
| `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` | Amendment A7; the Done log. |
| `CLAUDE.md` | § Video path's Output Profile sentence gains the Go half. |

**Not touched, and each for a stated reason:** `apps/proxy/live_proxy/**` (2d deletes it; its ORM read at `views.py:152` stays allowlisted and this PR moves the zero-ORM allowlist by **zero** sites — the contract field that closes it has existed since 2b-2 and the Python relay still cannot use it); `apps/proxy/tests/test_relay_list_payload_golden.py` and `relay/httpapi/testdata/channels_clients_all.json` (Ruling R7); `relay/channel/stats.go` and `state.go` (Constraint 18); `relay/buffer/**` (the transcode's sink is `buffer.Ring` unchanged); `go.mod` (Constraint 3); any workflow (Constraint 6); `metrics/curated/` (milestones are per stage and the 2c goal milestone lands with 2c-9).

---

## Task 0: Confirm the merged 2c-6 tree is what this plan's appendices were built on

**Files:** none changed. This task produces a report, and a stop if anything differs.

**Interfaces:**
- Consumes: the merged 2c-6 tree at `eb7fac07` (`main`, the squash of PR #308).
- Produces: a verified statement that every symbol in § Sequencing's ledger exists with the shape this plan's appendices were built against.

- [ ] **Step 0: Seed your scratch module from the merged 2c-6 tree, tests included**

```bash
cd /Users/dion/git/Dispatcharr
git fetch origin main
git rev-parse eb7fac07^{tree} >/dev/null   # a bad ref says so; never 2>/dev/null this
git worktree add <your worktree> -b migration/phase2c-output-profile eb7fac07
# git archive, not cp -R: it takes exactly what the commit holds, tests and
# all, with no chance of an untracked file from another run coming along.
mkdir -p <scratch>/2c7 && git archive eb7fac07 relay | tar -x -C <scratch>/2c7 --strip-components=0
cp <your worktree>/.golangci.yml <scratch>/2c7/relay/.golangci.yml
# relaytest/corpus.go locates the repo from its own path, so the Python
# harness's fixtures must be reachable at the same relative depth.
ln -sfn <your worktree>/apps <scratch>/2c7/apps
cd <scratch>/2c7/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
```

Expected: all four green on the untouched tree, and `find relay -name '*.go' | wc -l` = **91**, of which **42** are `_test.go`. If they are not, the merge is broken and nothing below is your problem — **stop and report**.

**Measured on `eb7fac07` while this plan was written**, so you have something to compare against: `gofmt -l` silent; build and vet green; `golangci-lint` `0 issues.`; `go test -race -count=1 ./...` green with `channel` ~75s, `httpapi` ~67s, `ffmpeg` ~10s and everything else under 4s.

- [ ] **Step 1: Check every symbol in the dependency ledger**

Run each of these and compare against § Sequencing's table. **Every grep must find what it names; a miss is a stop-and-report, not a reconciliation.**

```bash
cd <your worktree>/relay
grep -n "func Start(ctx context.Context, cfg Config)" output/fmp4.go          # expect exactly 1
grep -n "type Pipeline struct" -A 10 output/fmp4.go                          # expect cfg, log, frags, cancel, done -- no ring, no bsf
grep -n "p\.frags" output/fmp4.go                                            # expect exactly 3: run's defer, reader's scanner, the accessor
grep -n "frags: buffer.NewFragments\|func (p \*Pipeline) Fragments" output/fmp4.go   # expect 1 each -- the other two of Ruling R11's five sites
grep -n "pipeline.Fragments()" httpapi/fmp4.go                               # expect exactly 1, and it stays
grep -n "func (p \*Pipeline) reader\|func (p \*Pipeline) writer\|func (p \*Pipeline) run\|func (p \*Pipeline) generation" output/fmp4.go   # expect 4
grep -n "readSize = 65536\|stopJoinWait = 5" output/fmp4.go                  # expect both
grep -n "func (c \*Channel) AttachOutput" output/channel_output_NOPE 2>/dev/null; \
  grep -n "func (c \*Channel) AttachOutput(format string, remux output.Remux)" channel/output.go   # expect exactly 1
grep -n "func (c \*Channel) releaseOutput\|func (c \*Channel) stopOutputs\|type outputRegistry\|func (c \*Channel) OutputFormats" channel/output.go  # expect 4
grep -n "defer c.stopOutputs()" channel/channel.go                           # expect exactly 1
grep -n "budgetBytes int" channel/channel.go                                 # expect exactly 1
grep -n "type Started struct" -A 8 channel/manager.go                        # expect 4 fields, no OutputProfiles
grep -n "type Resolved struct" -A 6 channel/failover.go                      # expect 3 fields, no OutputProfiles
grep -n "X-Relay-Output\"" httpapi/stream.go                                 # expect exactly 1, the REFUSAL
grep -n "func serveClient" -A 8 httpapi/stream.go                            # expect ch then client, NO ring parameter
grep -n "ring := ch.Ring()" httpapi/stream.go                                # expect exactly 1
grep -n "func serveFMP4(" -A 9 httpapi/fmp4.go                               # expect no source parameter
grep -n "ch.AttachOutput(output.FormatFMP4, deps.Remux)" httpapi/fmp4.go     # expect exactly 1
grep -n "func SpawnCount\|--spawn-log" internal/relaytest/standin.go         # expect both
grep -n '"output_profiles"' internal/relaytest/controlplane.go               # expect exactly 1, the unconditional empty map
grep -n "output_profiles is deliberately not" control/nextsource.go          # expect 1 -- 2c-4's placeholder comment this PR replaces
grep -rn "StateActive" channel/ --include=*.go | grep -v _test.go            # expect exactly 2 WRITERS plus the const and one comment
```

**Ruling R11's five sites are the ones to check hardest.** If `grep -n "p\.frags"` returns anything but three, or if `Pipeline` already carries a sink abstraction of its own, 2c-6's fix round reshaped the type and Appendix G's anchors are stale — **stop and report** rather than re-deriving the diff.

- [ ] **Step 2: Count the `StateActive` writers and name their lines**

Constraint 18. Expected: exactly two — `promoteOnFirstChunk`'s assignment in `channel/channel.go` (**`:540`** on `eb7fac07`, in the function that starts at `:529`; the file is 555 lines, so a citation of `:583` is only true AFTER Appendix L adds its field block, and this task runs BEFORE that) and `reportBuffering`'s guarded recovery edge in `channel/stats.go` (`:129`, unmoved). The other two hits are the constant's declaration in `state.go` and a comment in `failover.go`. **Three writers is a stop.** Record both line numbers; Task 9 counts them again.

- [ ] **Step 3: Check the Python side is what this plan read**

```bash
cd <your worktree>
grep -n "mpegts:p" apps/proxy/live_proxy/output/profile/manager.py            # expect 7 LINES: SIX f"mpegts:p{self.profile_id}" sites (:303 :315 :325 :332 :349 :364) plus :361, a docstring
grep -n "read_size = 65536" apps/proxy/live_proxy/output/profile/manager.py   # expect 1 (:231)
grep -n "t.join(timeout=5)" apps/proxy/live_proxy/output/profile/manager.py   # expect 1 (:141)
grep -n "def _stderr_loop" -A 26 apps/proxy/live_proxy/output/profile/manager.py   # expect NO aac_adtstoasc, NO retry
grep -n "log_system_event\|post_events" apps/proxy/live_proxy/output/profile/manager.py  # expect NOTHING
grep -n "resolved_output_format}:p{resolved_output_profile.id}" apps/proxy/live_proxy/views.py   # expect 2 (:621, :732)
grep -n "source_buffer=source_buffer if resolved_output_profile else None" apps/proxy/live_proxy/views.py  # expect 1 (:792)
grep -n "Failed to start output profile transcode" apps/proxy/live_proxy/views.py  # expect 1 (:771)
grep -n "argv = serializers.ListField" apps/proxy/serializers.py              # expect 2: :64 is StreamProfileRefSerializer's and ALREADY has allow_null=True; :230 is OutputProfileRefSerializer's and does not -- :230 is the one Task 2 edits
grep -n "continue" apps/proxy/next_source.py | head                            # expect the _with_output_profiles skip
grep -n "def build_command" -A 4 core/models.py                                # expect [self.command] + shlex_split(...)
grep -rn "transcode_active" apps/ --include=*.py                               # expect 3 LINES: the helper's def and its return (redis_keys.py:89, :91) and ONE delete (input/manager.py:1797). No writer, no reader
```

If `views.py:771`'s body string or the `mpegts:p` literal differs by a character, **stop**: Constraint 8's pins are those strings.

- [ ] **Step 4: Report**

State: the merged SHA, every ledger row as matched or differing, the two `StateActive` writer lines, and whether the Python constants are unchanged. **If anything differs, stop here and report before writing a line of Go.**

**Every one of these greps was run against `eb7fac07` while this plan was written and returned the counts stated.** A difference therefore means your seed is not `eb7fac07`, not that the plan guessed — check `git rev-parse HEAD` in your worktree before reporting a mismatch.

---

## Task 1: `relay/control` — `output_profiles` on the answer

**Files:**
- Modify: `relay/control/nextsource.go` (Appendix A)
- Create: `relay/control/outputprofile_test.go` (Appendix B)

**Interfaces:**
- Consumes: `NextSourceAnswer` as 2c-2 declared it.
- Produces: `control.OutputProfileRef{ID int; Argv []string}` with `Command() string` and `Args() []string`; `NextSourceAnswer.OutputProfiles map[string]OutputProfileRef` and `NextSourceAnswer.OutputProfilesPresent bool`. Task 5 converts them; nothing else reads them.

- [ ] **Step 1: Write the failing tests**

Write `relay/control/outputprofile_test.go` exactly as Appendix B gives it. Three tests: the argv's command-first shape, the three states of the key (absent, empty object, entries, explicit null), and a null argv decoding as present-but-nil.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd <scratch>/2c7/relay && go test -run 'OutputProfile|AnAbsentOutputProfiles' ./control/`
Expected: FAIL to **compile** — `undefined: OutputProfileRef`. A compile failure is the correct red here; there is no type yet.

- [ ] **Step 3: Write the implementation**

Apply Appendix A to `relay/control/nextsource.go`. It replaces 2c-4's placeholder comment on `NextSourceAnswer` ("output_profiles is deliberately not declared: 2c-7 owns Output Profiles") with the field pair, and adds `OutputProfileRef` above it.

Two things to get right, both pinned by Step 1's tests:

- **`Argv` carries the command as element 0** (Constraint 39). `Command()` and `Args()` are the only places that split it.
- **`UnmarshalJSON` on both types**, because `encoding/json` cannot report an absent key on a slice or a map field — absent and explicit-null both leave it nil. `StreamProfileRef.UnmarshalJSON` is the shape to copy; it is in the same file.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd <scratch>/2c7/relay && go test -race -count=1 ./control/`
Expected: PASS, all of `relay/control` (the existing `nextsource_test.go` must stay green: `NextSourceAnswer` now has a custom `UnmarshalJSON` and every existing decode goes through it).

- [ ] **Step 5: Break-check rows 14 and 15**

Run § Break-check's rows 14 and 15 and record the messages. **A green break-check here is a stop**, not a formality.

- [ ] **Step 6: Run the four checks and commit**

```bash
cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && gofmt -l .
```

```bash
git -C <your worktree> add relay/control/nextsource.go relay/control/outputprofile_test.go
```

```bash
git -C <your worktree> commit -F <message file>
```

---

## Task 2: Django — a null argv instead of an omission

**Files:**
- Modify: `apps/proxy/serializers.py` (Appendix C)
- Modify: `apps/proxy/next_source.py` (Appendix C)
- Modify: `apps/proxy/tests/test_next_source_api.py` (Appendix C)

**Interfaces:**
- Consumes: `_with_output_profiles` and `OutputProfileRefSerializer` as 2b-2 left them.
- Produces: an `output_profiles` map whose entries may carry `"argv": null`. Task 6 is the only consumer of that state.

Ruling R4 is the argument; this task is the three edits.

**Before you start, read Global Constraint 10.** This task needs a Django test run and must not use the shared container.

- [ ] **Step 1: Write the failing test**

Apply Appendix C's `test_next_source_api.py` hunk: `test_a_malformed_active_profile_is_skipped_not_a_500` becomes `test_a_malformed_active_profile_carries_a_null_argv_not_a_500`, its `assertNotIn(bad.id)` becomes an `assertIn` with a message plus an equality on the whole entry, and a **deactivated** profile is created **before** the `_next_source` call so the same answer can be asserted not to carry it.

The ordering is load-bearing: an earlier draft created the deactivated row *after* the call, so `assertNotIn` passed for a row the answer never had the chance to include.

- [ ] **Step 2: Run it to verify it fails**

```bash
docker exec -e TEST_USE_SQLITE= -e POSTGRES_HOST=/var/run/postgresql \
  -e POSTGRES_DB=dispatcharr -e POSTGRES_USER=dispatch -e POSTGRES_PASSWORD=secret \
  -e REDIS_HOST=localhost -e REDIS_PORT=6379 -e REDIS_DB=0 \
  -e DJANGO_SECRET_KEY=hook-test-secret -e DISPATCHARR_LOG_LEVEL=WARNING \
  <yourcontainer> /dispatcharrpy/bin/python /repo/manage.py test \
  apps.proxy.tests.test_next_source_api.OutputProfilesOnTheContractTests --keepdb
```

Expected: FAIL with

```
AssertionError: '<id>' not found in {'<other id>': {'id': …, 'argv': [...]}} : a profile whose parameters shlex could not split is absent from output_profiles; it must be present with a null argv, or a relay cannot tell it from a DEACTIVATED profile and will serve the client plain where Python answers 500
```

- [ ] **Step 3: Write the implementation**

Apply Appendix C's `serializers.py` and `next_source.py` hunks: `allow_null=True` on the `argv` field, and `argv = None` plus a fall-through where the `except ValueError` arm used to `continue`. The `logger.error` stays — it is still the operator's only signal — with its wording changed from "omitting it" to "carries a null argv".

- [ ] **Step 4: Run the label to verify it passes**

```bash
docker exec <yourcontainer> redis-cli FLUSHALL
# then the same docker exec as Step 2, with the label apps.proxy.tests
```

Expected: `Ran 379 tests` … `OK`. (379 is what this plan measured; a different count means the label grew or shrank for another reason — say so rather than adjusting.)

Also run the credential check over the three files:

```bash
cd <your worktree> && python3 scripts/check_credential_logging.py \
  apps/proxy/next_source.py apps/proxy/serializers.py apps/proxy/tests/test_next_source_api.py
```

Expected: no output, exit 0.

- [ ] **Step 5: Break-check row 1**

Run § Break-check's row 1 and record the message.

- [ ] **Step 6: Commit**

```bash
git -C <your worktree> add apps/proxy/serializers.py apps/proxy/next_source.py apps/proxy/tests/test_next_source_api.py
```

```bash
git -C <your worktree> commit -F <message file>
```

**The commit gate will run `apps.proxy.tests` for you** (`scripts/ci_backend_test_labels.py` maps all three paths to exactly `['apps.proxy.tests']` — verified). If it reports the shared container is mounted at another worktree, it warns rather than blocks; you have already run the label yourself in Step 4, so say so in the commit and move on.

---

## Task 3: `relay/internal/relaytest` — the fake control plane's profiles, and two ways to see which ring a process read

**Files:**
- Modify: `relay/internal/relaytest/controlplane.go` (Appendix D)
- Modify: `relay/internal/relaytest/standin.go` (Appendix E)
- Modify: `relay/internal/relaytest/asset.go` (Appendix F)
- Modify: `relay/internal/relaytest/asset_test.go` (Appendix F)

**Interfaces:**
- Consumes: `ControlPlaneConfig`, `standInOptions`, `RunStandIn`, `SyntheticTS`, `PacketIndex` as 2c-6 left them.
- Produces: `relaytest.OutputProfileConfig{ID int; Argv []string; ArgvNull bool}`; `ControlPlaneConfig.OutputProfiles map[string]OutputProfileConfig` and `.OutputProfilesAbsent bool`; `(*ControlPlane).SetOutputProfiles(map[string]OutputProfileConfig)`, which replaces the map every LATER answer carries — the mutator Task 7's refresh test needs, mirroring `SetSettings`; the stand-in flags `--ts-pid N` and `--stdin-pid-log PATH`; `relaytest.PacketPID(packet []byte) int` and `relaytest.StdinPacketPID(path string) int`. Tasks 4 and 7 use all of them.

**Why the two stand-in flags exist** (Constraint 41): the stand-in's `-i pipe:0` copy loop makes its output equal its input, so a profile client's bytes and a plain client's bytes are identical and **no assertion on them can fail**. `--ts-pid` rewrites every whole packet's 13-bit PID, which keeps the output a valid same-length transport stream and makes its provenance readable from any packet — what an Output Profile does in miniature. `--stdin-pid-log` writes the PID of the first whole packet a process reads on fd 0, which is the only way to see which ring a *chained* process was fed, because the fMP4 stand-in ignores its input entirely.

- [ ] **Step 1: Write the failing test**

Append Appendix F's `TestPacketPIDReadsBackWhatSyntheticTSWroteAndWhatRewritePIDSets` to `relay/internal/relaytest/asset_test.go`.

It asserts three things, and the third is the one a careless implementation fails: `PacketPID` round-trips what `SyntheticTS` wrote; `rewritePID` sets **both** bytes of a 13-bit value (0x1FF needs the low five bits of byte 1 as well as all of byte 2, so a rewrite touching only byte 2 passes for every PID under 0x100 and fails here) without breaking the sync byte or the embedded index; and a partial trailing packet is **carried, not rewritten**, because 8192-byte reads do not land on 188-byte boundaries.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd <scratch>/2c7/relay && go test -run TestPacketPIDReadsBack ./internal/relaytest/`
Expected: FAIL to compile — `undefined: PacketPID`, `undefined: rewritePID`.

- [ ] **Step 3: Write the implementation**

Apply Appendices D, E and F. Three independent edits:

- `asset.go` gains `PacketPID`, beside `PacketIndex` and reading the same layout.
- `standin.go` gains the two flags, `rewritePID` and `StdinPacketPID`. The PID rewrite runs **inside the existing copy loop** with a `carry` across reads; `--stdin-pid-log` runs in `runFMP4StandIn`'s drain goroutine, before the `io.Copy(io.Discard, …)`.
- `controlplane.go` gains the config fields, `SetOutputProfiles` and a block that builds the `output_profiles` object, replacing the unconditional `"output_profiles": map[string]any{}` literal. **`SetOutputProfiles` needs its own `hasProfs` flag rather than a nil check**, for `ControlPlaneConfig.OutputProfiles`' own reason: nil means "the empty object Django sends when nothing is active", which a test may set deliberately. `OutputProfilesAbsent` leaves the key out; a nil map sends `{}`; `ArgvNull` sends `"argv": null`; a nil `Argv` sends `[]`. An entry's `ID` defaults to its map key parsed as an integer.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd <scratch>/2c7/relay && go test -race -count=1 ./internal/relaytest/`
Expected: PASS. The synthetic-asset digest test must stay green — `PacketPID` reads bytes and writes none, and `rewritePID` is only reached through a flag.

- [ ] **Step 5: Run the four checks and commit**

```bash
cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && gofmt -l .
```

```bash
git -C <your worktree> add relay/internal/relaytest/
```

```bash
git -C <your worktree> commit -F <message file>
```

---

## Task 4: `relay/output` — the second sink and `StartProfile`

**Files:**
- Modify: `relay/output/fmp4.go` (Appendix G)
- Create: `relay/output/profile.go` (Appendix H)
- Create: `relay/output/profile_test.go` (Appendix I)
- Create: `relay/output/profile_real_test.go` (Appendix J)

**Interfaces:**
- Consumes: `Pipeline`, `Config`, `Remux`, `Start`, `run`, `generation`, `writer`, `reader`, `readSize`, `stopJoinWait` from 2c-6 — **and edits `Pipeline` itself**, at Ruling R11's five `*buffer.Fragments` bindings; `ffmpeg.StartPiped`; `buffer.New`/`Ring`; `relaytest.StandInCommand`, `SpawnCount`, `PacketPID`, `AlignmentProblem`; 2c-6's `requireFFmpeg` and `buildFragmentableAsset`.
- Produces: `output.FormatMPEGTS`, `output.ProfileKey(int) string`, `output.FormatKey(string, *int) string`, `output.ErrProfileCommandAbsent`, `output.ProfileConfig`, `output.StartProfile(ctx, ProfileConfig) (*Pipeline, error)`, `(*Pipeline).Ring() *buffer.Ring`. Task 5 calls `StartProfile` and `ProfileKey`; Task 6 calls `FormatKey` and `Ring`.

- [ ] **Step 1: Write the failing tests**

Write `relay/output/profile_test.go` and `relay/output/profile_real_test.go` exactly as Appendices I and J give them. Six tests plus the real one:

1. `TestTheProfileKeyIsMPEGTSWhateverTheClientFormat` — the key table, against `output/profile/manager.py:303` and `views.py:731-734`.
2. `TestAProfileTranscodeFillsItsOwnRingFromTheChannels` — bytes arrive, they are a transport stream, and **every packet carries the child's PID** rather than the asset's.
3. `TestAProfileWithNoCommandIsRefusedRatherThanDefaultedToTheRemux` — `errors.Is(err, ErrProfileCommandAbsent)`, **never** a substring (Constraint 42).
4. `TestAProfileStderrIsNotWatchedForTheBitstreamFilterError` — one spawn, then the pipeline ended.
5. `TestStoppingAProfileTranscodeClosesItsRing`.
6. `TestACancelledContextEndsTheProfileTranscode`.
7. `TestARealAC3ProfileTranscodesTheChannelsRing` — real ffmpeg, the migration's own argv, ffprobe reading `ac3` back from an AAC asset.

**Note `standInProfile`'s `JoinBehind: time.Minute`** and read its comment before shortening it (Constraint 17): with a zero join window the writer starts at the head of a ring nothing is still filling and the child is fed nothing, for ever.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd <scratch>/2c7/relay && go test -run 'Profile' ./output/`
Expected: FAIL to compile — `undefined: StartProfile`, `undefined: ProfileConfig`, `undefined: ProfileKey`, `p.Ring undefined`.

- [ ] **Step 3: Write the implementation**

Apply Appendix G to `output/fmp4.go` and write `output/profile.go` from Appendix H.

`fmp4.go`'s edits, all additive. **Ruling R11's five `*buffer.Fragments` bindings are the checklist** — work through them in order and tick each, because missing one still compiles and then panics on a nil `frags` the first time a profile client tunes:

| # | site in 2c-6's `output/fmp4.go` | edit |
|---|---|---|
| 1 | the struct field `frags *buffer.Fragments` | add `ring *buffer.Ring` beside it, and `bsf bool` |
| 2 | `Start`'s `frags: buffer.NewFragments(...)` | add `bsf: true`; `StartProfile` (Appendix H) builds the other shape |
| 3 | `func (p *Pipeline) Fragments()` | add `func (p *Pipeline) Ring()` beside it |
| 4 | `run`'s `defer p.frags.Close()` | `defer p.closeSink()`, which branches |
| 5 | `reader`'s `s := &scanner{out: p.frags}` | leave `reader` alone; `generation`'s reader goroutine calls `p.read(proc)`, which branches |

**Exactly one of `ring` and `frags` is non-nil for the life of a pipeline**, set by its constructor and never reassigned, so the three branches need no lock and `-race` has nothing to find.

Two edits that are not on that list:

- `generation`'s stderr callback gains `p.bsf &&` in front of the bitstream-filter condition.
- `readSize`'s comment gains `output/profile/manager.py:231`, and the package doc gains Ruling R1's paragraph.

**`scanner.out` stays `*buffer.Fragments` and is not generalised.** The scanner is the fMP4 box splitter and a transcode has no boxes to split; `profileReader` writes to the ring directly and constructs no scanner at all.

`profile.go` is new and holds nothing shared. Three things to get right:

- **`StartProfile` does not use `Config.command()`/`argv()`** (Ruling R3). It refuses an empty command with `ErrProfileCommandAbsent` before spawning.
- **It fills `cfg.Remux` from the profile's own command line** even though `bsf` is false, so an unreachable retry could never spawn the fMP4 remux (Ruling R3's second half, and break-check 8's finding).
- **`profileReader` returns nothing.** It has nothing to report — EOF on fd 1 and a closed ring are both ordinary ends — and a signature carrying an `error` it could only fill with nil is what `nilerr` reports (Constraint 15).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd <scratch>/2c7/relay && go test -race -count=1 ./output/`
Expected: PASS, including `TestARealAC3ProfileTranscodesTheChannelsRing` if ffmpeg is on your PATH. Record the ffmpeg version the test logs.

**Run it in the production base image too**, which is where `go-tests.yml` runs it (Amendment A4.7) and which ships ffmpeg **8.1.2** where a developer host is likely to have something newer. There is no Go toolchain in that image, so cross-compile the package's test binary and run that:

```bash
cd <scratch>/2c7/relay
GOOS=linux GOARCH=arm64 go test -c -o /tmp/output.test ./output/     # GOARCH=amd64 on an Intel host
docker run --rm -e LD_LIBRARY_PATH=/usr/local/lib -e CI=1 \
  -v /tmp/output.test:/tmp/output.test:ro \
  --entrypoint /tmp/output.test ghcr.io/d10scot/dispatcharr:base \
  -test.run='TestARealAC3ProfileTranscodesTheChannelsRing' -test.v
```

**`LD_LIBRARY_PATH=/usr/local/lib` is not optional and it is issue [#226](https://github.com/D10Scot/Dispatcharr/issues/226)**, the same workaround `apps/proxy/live_proxy/tests/harness/asset.py:95`'s `_FFMPEG_ENV` applies on the Python side. Without it, on the arm64 base image, `ffmpeg -version` dies with `symbol lookup error: undefined symbol: rist_peer_config_defaults_set_versioned` — measured — and the test then fails inside `buildFragmentableAsset` with a message about the asset rather than about the image. **The amd64 image CI pulls does NOT need it**, and that is measured rather than assumed: `go-tests.yml`'s `build` job has run parity-matrix row 4's real-ffmpeg pin green inside that image since 2c-4, with no such variable anywhere in the workflow. The defect is the arm64 build's, reproduced here. Say which architecture you ran.

Measured for comparison: **8.1.2 in the base image, 0.12s; 9.0.1 on this host, 0.15s** — the codec assertion and the "an Output Profile transcode has no `delay_moov` threshold" measurement (Amendment A7.7) hold identically on both, unlike A6.6's fMP4 threshold which had to be measured twice to say so.

Then **eight consecutive runs** (Working rules):

```bash
for i in 1 2 3 4 5 6 7 8; do go test -race -count=1 ./output/ | tail -1; done
```

- [ ] **Step 5: Break-check rows 3, 4, 5, 6, 7, 8**

Run § Break-check's rows 3 through 8 and record each message. Row 8 is the one whose first form did not redden usefully; re-read it before running.

- [ ] **Step 6: Run the four checks and commit**

```bash
cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && gofmt -l .
```

```bash
git -C <your worktree> add relay/output/
```

```bash
git -C <your worktree> commit -F <message file>
```

---

## Task 5: `relay/channel` — the profile types, the spec, and the cached set

**Files:**
- Modify: `relay/channel/output.go` (Appendix K)
- Modify: `relay/channel/channel.go` (Appendix L)
- Modify: `relay/channel/manager.go` (Appendix L)
- Modify: `relay/channel/failover.go` (Appendix L)

**Interfaces:**
- Consumes: `output.StartProfile`, `output.ProfileConfig`, `output.ProfileKey` from Task 4.
- Produces: `channel.OutputProfile{ID int; Argv []string}` with `Command()`/`Args()`; `channel.OutputProfiles{Known bool; ByID map[string]OutputProfile}` with `Lookup(string) (OutputProfile, bool)`; `channel.OutputSpec{Source *buffer.Ring; Profile *OutputProfile; Remux output.Remux}`; `AttachOutput(format string, spec OutputSpec)`; `(*Channel).OutputProfiles() OutputProfiles`; `(*Channel).SetClientOutputProfile(clientID string, profileID *int)`; `Started.OutputProfiles`; `Resolved.OutputProfiles`. Task 6 uses every one.

**This task has no tests of its own**, and that is deliberate rather than an omission. Everything it adds is exercised end to end by Task 7, in a package whose suite runs in five seconds rather than seventy-five, and every one of its behaviours has a break-check there (rows 2, 7, 9, 10, 11, 12, 13, 16, 17, 18). A `channel`-package test would duplicate those against a hand-built `Manager` and add a minute to every run.

**The failover refresh is among them, and it did not used to be.** An earlier draft shipped `channel/failover.go`'s two-line assignment with nothing exercising it — deleting it left the whole suite green — and Ruling R5 argued for the mechanism while the plan left it unpinned. Task 7's `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` closes it in both directions. Task 9 Step 3 no longer names it as an accepted gap.

- [ ] **Step 1: Apply Appendix K to `relay/channel/output.go`**

Three new types above `AttachOutput`, and one branch inside it.

- `OutputProfile.Command()`/`Args()` are **nil-safe**, and that matters: a profile Django could not build reaches `AttachOutput` with a nil `Argv`, and indexing it here would turn a control-plane data problem into a panic in the channel package. Found by break-check 5's first form, which reddened with `EOF` on the client's socket instead of a status.
- `OutputSpec.Source` nil means the channel's own ring. `OutputSpec.Profile` non-nil makes it a transcode; `OutputSpec.Remux` is ignored then.
- `AttachOutput`'s reuse branch, its refcount, its lock order, `releaseOutput` and `stopOutputs` are **untouched**.

- [ ] **Step 2: Apply Appendix L to `channel.go`, `manager.go` and `failover.go`**

- `Channel` gains `outputProfiles OutputProfiles`, guarded by `mu` and **replaced wholesale, never mutated in place**, which is what lets `OutputProfiles()` hand its map out without copying.
- `OutputProfiles()` takes `RLock`; `SetClientOutputProfile` takes `Lock` and mutates the registered `*Client`.
- `Started` gains the field; `publish` carries it.
- `Resolved` gains the field; the switch assigns it **under its existing `Lock`**, guarded by `Known` so a degraded resolution leaves the channel's copy alone.

**There is no `setOutputProfiles` method.** An earlier draft had one and `unused` reported it, because the failover assigns the field directly inside the lock it already holds. One writer, no wrapper.

- [ ] **Step 3: Run the four checks**

```bash
cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && gofmt -l .
```

Expected: green. `relay/channel`'s own suite (~75s) must be unaffected: nothing this task adds is reached by any existing test.

- [ ] **Step 4: Commit**

```bash
git -C <your worktree> add relay/channel/
```

```bash
git -C <your worktree> commit -F <message file>
```

---

## Task 6: `relay/httpapi` — the resolution, the chain and the ring

**Files:**
- Create: `relay/httpapi/profile.go` (Appendix M)
- Modify: `relay/httpapi/stream.go` (Appendix N)
- Modify: `relay/httpapi/fmp4.go` (Appendix O)
- Modify: `relay/httpapi/failover.go` (Appendix O)

**Interfaces:**
- Consumes: everything Task 5 produced, plus `output.FormatKey`, `output.ProfileKey` and `(*Pipeline).Ring()`.
- Produces: `attachOutputProfile`, `writeProfileFailure`, `profileNotStartedBody`, `outputProfilesFrom`, `ErrOutputProfileMalformed`; `serveClient` with a `ring` parameter; `serveFMP4` with a `source` parameter. Task 7's tests drive all of it through HTTP.

- [ ] **Step 1: Write `relay/httpapi/profile.go`**

Appendix M. `attachOutputProfile` is `views.py:765-776` in order, and its three failure answers are Constraint 40's three wire states:

| the wire says | Python does | this does |
|---|---|---|
| no `X-Relay-Output` | serves plain, registers null | returns `ch.Ring()` and a no-op release |
| id present, **not in the map** | re-reads with `is_active=True`, gets `None`, serves plain and registers null (`views.py:150-155`, `:725-751`) | logs, calls `SetClientOutputProfile(id, nil)`, returns `ch.Ring()` |
| id present, **argv null** | `build_command()` raises, `:823-827` answers 500 | 500 with `views.py:771`'s body (through the same branch as a spawn failure) |
| id present, argv good, spawn fails | `ensure_output_profile` returns False, `:767-772` answers 500 | 500 with the same body |
| **`output_profiles` key absent** | cannot happen (2b-2 always sends it) | 502, the class an absent `proxy_settings` key gets |

- [ ] **Step 2: Apply Appendix N to `stream.go`**

Six edits:

- `identify` parses `X-Relay-Output` into `*int` instead of refusing it, and refuses a non-positive-integer with `ErrOutputProfileMalformed`. **What it records is what the hop asked for**, not what the tune ends up serving — the set that resolves it is the channel's, and the channel does not exist yet.
- `ErrOutputProfileMalformed` is declared beside `ErrUnsupportedOutput`, and `writeTuneFailure` answers it 400 **without echoing the value**.
- `StreamHandler` gains the profile block **after `defer release()` and before the fMP4 branch**, with `defer releaseProfile()`.
- `serveClient` takes `ring *buffer.Ring` and loses its `ring := ch.Ring()` line; the one existing call passes `source`.
- `ErrUnsupportedOutput`'s doc comment is corrected, and its `Error()` names both served formats.

- [ ] **Step 3: Apply Appendix O to `fmp4.go` and `failover.go`**

`serveFMP4` gains `source *buffer.Ring` and composes its key with `output.FormatKey(output.FormatFMP4, client.OutputProfileID)`, passing `Source: source`. `resolver.resolved` gains a `profiles` parameter; the live arm passes `outputProfilesFrom(answer)` and the degraded arm passes a zero value.

- [ ] **Step 4: Run the four checks**

```bash
cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && gofmt -l .
```

Expected: **one failure**, `TestAnOutputThisRelayDoesNotServeIsRefused`, whose `X-Relay-Output: 7` row still expects 501. That is the correct red and Task 7 fixes it; do not fix it here.

- [ ] **Step 5: Commit**

```bash
git -C <your worktree> add relay/httpapi/profile.go relay/httpapi/stream.go relay/httpapi/fmp4.go relay/httpapi/failover.go
```

```bash
git -C <your worktree> commit -F <message file>
```

---

## Task 7: `relay/httpapi` — row 11's pin and the surrounding behaviours

**Files:**
- Create: `relay/httpapi/profile_test.go` (Appendix P)
- Modify: `relay/httpapi/fanout_test.go` (Appendix Q)
- Modify: `relay/httpapi/golden_test.go` (Appendix Q)

**Interfaces:**
- Consumes: `fanRig`, `fanRigWith`, `tuneAs`, `listChannels`, `waitForHead`, `waitFor`, `withRemux`, `standInRemux`, `readAtLeast`, `channelListPayload`, `rigAssetPackets`, `rigChunkBytes`; `relaytest.OutputProfileConfig`, `SetOutputProfiles`, `NewUpstream`, `AlternateConfig`, `SpawnCount`, `PacketPID`, `StdinPacketPID`, `SyntheticFMP4Init`, `FMP4ShapeProblem`; `Channel.ClientSnapshot`, `Channel.OutputProfiles`.
- Produces: nothing other tasks use.

- [ ] **Step 1: Write `relay/httpapi/profile_test.go`**

Appendix P. Twelve tests. Read `transcodePID`'s comment first: it is Constraint 41 in one paragraph, and without it three of these tests cannot fail.

1. **`TestTwoClientsOnOneOutputProfileShareOneTranscode` — parity-matrix row 11.** One spawn for two clients, both reading the transcode's PID, one upstream request, one `next-source` call, one registry key.
2. `TestAProfileClientAndAPlainClientShareOneUpstream` — opposite halves of one claim: the profile client's packets carry the transcode's PID **and only** it; the plain client's carry the asset's **and only** it.
3. `TestAnFMP4ClientOnAnOutputProfileRunsTheTranscodeAndTheRemuxChained` — two spawns, two keys, an fMP4 body, and the PID the remux was fed.
4. `TestTheListPayloadNamesEachClientsOwnOutputProfile` — the integer, the null, and the key's presence on both.
5. `TestAProfileMissingFromTheAnswerIsServedWithoutOne` — 200, the channel's own PIDs, no pipeline, and a registry row of null.
6. `TestAProfileWhoseArgvDjangoCouldNotBuildIsAFiveHundred` — `views.py:771`'s exact body.
7. `TestATranscodeThatCannotBeSpawnedIsAFiveHundred` — the same body by the other route.
8. `TestATuneNamingAProfileAgainstAnOlderControlPlaneIsABadGateway` — 502, **and** an ordinary tune unaffected.
9. `TestTheLastProfileClientLeavingStopsTheTranscodeAndNotTheChannel`.
10. `TestStoppingTheChannelStopsItsProfileTranscode` — with a **second reference the test never releases**, which is what makes it about `stopOutputs` rather than about the refcount. Read its comment: without that reference the break-check stays green.
11. `TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint` — a reader hammering `ClientSnapshot` for the whole of a tune whose profile is not in the answer. **Its oracle is the registry value, not the detector**: a test whose only assertion is "no race" passes on any run where the goroutines miss each other, which is the silence-read-as-pass shape. Run it with `-race` or it pins only the value (break-check 16).
12. `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` — Ruling R5's mechanism, both arms (break-checks 17 and 18).

- [ ] **Step 2: Run them to verify they fail**

Run: `cd <scratch>/2c7/relay && go test -run 'Profile|Transcode|Chained' ./httpapi/`
Expected: with Task 6 applied they **pass**; with Task 6 reverted they fail to compile. If you are executing tasks in order, run them before Task 6's commit is on your branch to see the red, or accept the compile failure in Task 6 Step 4 as the red for this task and say which you did.

- [ ] **Step 3: Fix the 501 subtest and the golden message**

Apply Appendix Q. `TestAnOutputThisRelayDoesNotServeIsRefused`'s table gains a `status` column and loses the merged tree's `andFMP4 bool`; **both** of its profile-bearing rows go — the bare `X-Relay-Output: 7` row and the `"an Output Profile on an fMP4 tune"` row that 2c-6's fix round added — replaced by `"seven"` and `"0"`, both expecting **400**. The `if tc.andFMP4` block goes with them, and so does the `output` import, which that fix round added for that row alone and which `go vet` reports as unused the moment the row is deleted.

**Do not read this as dropping the concern that row guarded.** Its comment named an identify that returned early on a format it serves and so silently dropped the Output Profile — a real hazard, and under 2c-7 no longer a 501 question at all, because the profile is resolved after the channel is up rather than refused in `identify`. `TestAnFMP4ClientOnAnOutputProfileRunsTheTranscodeAndTheRemuxChained` is the stronger form of the same guard: it asserts the transcode really spawned, that both `mpegts:p3` and `fmp4:p3` are registered, and that the remux's own fd 0 carried the transcode's packets. A relay that dropped the profile and streamed plain fMP4 passes a status check and fails all three. Say so in the PR description rather than letting a reviewer find a deleted row.

The loop also gains an assertion that the refused value is not echoed into the body. `golden_test.go`'s live-row message stops citing 2c-3.

- [ ] **Step 4: Run the package to verify everything passes**

Run: `cd <scratch>/2c7/relay && go test -race -count=1 ./httpapi/`
Expected: PASS.

Then **eight consecutive runs of the Output Profile subset**:

```bash
for i in 1 2 3 4 5 6 7 8; do go test -race -count=1 -run 'Profile|Transcode|Chained|Output' ./httpapi/ | tail -1; done
```

- [ ] **Step 5: Break-check rows 2, 9, 10, 11, 12, 13, 16, 17, 18**

Run § Break-check's rows 2 and 9 through 13 and record each message. **Row 2's registry half is Global Constraint 35's demonstration**: with `AttachOutput`'s reuse branch disabled, comment out the spawn assertion and confirm the registry and PID assertions stay **green**. Restore the assertion afterwards.

- [ ] **Step 6: Run the four checks and commit**

```bash
cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && gofmt -l .
```

```bash
git -C <your worktree> add relay/httpapi/profile_test.go relay/httpapi/fanout_test.go relay/httpapi/golden_test.go
```

```bash
git -C <your worktree> commit -F <message file>
```

---

## Task 8: the parity matrix, the spec amendment and `CLAUDE.md`

**Files:**
- Modify: `docs/relay-parity-matrix.md` (Appendix R)
- Modify: `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` (Appendix S)
- Modify: `CLAUDE.md` (Appendix T)

**Interfaces:**
- Consumes: the test names Task 7 created.
- Produces: row 11's Go column, Amendment A7, one Done-log line, one `CLAUDE.md` sentence.

- [ ] **Step 1: Add row 11's Go pin**

Appendix R, which is a **diff** — apply it, do not hand-edit. One line changes and only its `Pin` and `Notes` cells grow (Amendment A2.2: a Go pin is a reference appended to the existing cell, not a new column). Read the HTML comment at the top of that file anyway: one row is one line, cells are never padded, and no Markdown formatter may be run over it.

**The reviewer of this plan mis-applied the prose version** and put the reference after the row's closing pipe, making a six-cell row the guard rejects. That is why it is a diff now.

- [ ] **Step 2: Run the matrix guard**

```bash
cd <your worktree>/e2e && npm ci && npx playwright test --project=guards parity-matrix
```

Expected: **7 passed**, and it needs no container. **`npm ci` first** — a fresh worktree has no `e2e/node_modules` and `npx playwright` without it reports nothing useful.

**Run this AFTER Task 7**, not before: the guard's `every pin resolves` test opens every file a Pin cell names, and `relay/httpapi/profile_test.go` does not exist until Task 7 creates it. Run it early and you get one failure reading `pin names no such file: relay/httpapi/profile_test.go`, which is correct and tells you only that you are out of order.

- [ ] **Step 3: Append Amendment A7 after A6, and one Done-log line**

Appendix S, also a **diff**: A7 lands after A6.6 and before `## Stage 2d`, and the Done-log row after the last existing `| 2c-6 ` row. Seven items: the chain and its two keys (R9); the three wire states and the Django change (R4); the profile set is cached per channel and refreshed on failover, with its stated divergence (R5); `ProfileConfig` rather than `Remux`, and why (R3); the owner lock and TTL refresh deleted (R2); `transcode_active` is dead (R8); and the measurement 2c-8 needs — an Output Profile transcode has **no `delay_moov` threshold**, so A6.6's eight-second floor does not apply to it.

- [ ] **Step 4: Update `CLAUDE.md`**

Appendix T, a **diff**. One sentence in § Video path, **appended to the existing parenthetical rather than replacing the paragraph** — that paragraph already gained a 2c-6 sentence about fMP4, and a replacement written against the older text would silently drop it.

- [ ] **Step 5: Commit**

```bash
git -C <your worktree> add docs/relay-parity-matrix.md docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md CLAUDE.md
```

```bash
git -C <your worktree> commit -F <message file>
```

---

## Task 9: final verification and the PR description

**Files:** none changed.

- [ ] **Step 1: The whole module, three times, under `-race`**

```bash
cd <your worktree>/relay
for i in 1 2 3; do go test -race -count=1 -timeout 900s ./... ; done
```

Expected: every package `ok`, three times. Measured here: `channel` ~75s, `httpapi` ~70s, everything else under 9s.

**The Linux pins run in the base image, and on an arm64 host that needs one variable.** `ffmpeg` there dies with `symbol lookup error: undefined symbol: rist_peer_config_defaults_set_versioned` unless `LD_LIBRARY_PATH=/usr/local/lib` is set — issue [#226](https://github.com/D10Scot/Dispatcharr/issues/226), the workaround `harness/asset.py:95` already applies on the Python side. **amd64, which is what CI pulls, is fine and needs nothing** — `go-tests.yml`'s real-ffmpeg pin has run green in that image since 2c-4 with no such variable. This is a local arm64 step only, and Task 4 Step 4 carries the exact invocation.

- [ ] **Step 2: Three GOOS, build, vet and lint**

```bash
cd <your worktree>/relay
gofmt -l . && go build ./... && go vet ./... && GOOS=linux go vet ./... && GOOS=darwin go vet ./...
golangci-lint run ./... && GOOS=linux golangci-lint run ./... && GOOS=darwin golangci-lint run ./...
```

Expected: `gofmt -l` silent, `0 issues.` three times.

**And list every suppression, not just the count** (Constraint 15). Expected: **eighteen** in the module — sixteen on the merged 2c-6 tree plus **two of this PR's** —

```bash
cd <your worktree>/relay && grep -rn "#nosec\|nolint" --include='*.go' . | sort
```

`internal/relaytest/standin.go`'s `#nosec G304` in `StdinPacketPID` and `output/profile_real_test.go`'s `#nosec G204` on the ffprobe call. Any other new one is a finding this plan did not decide — stop and report it rather than reasoning about it in the PR description.

- [ ] **Step 3: The two module-level checks, and the counts**

```bash
cd <your worktree>
scripts/check_go_credential_logging.sh relay     # expect: credlint: 11 package(s) clean
scripts/check_go_stdlib_only.sh relay            # expect: OK: relay depends on the standard library only.
ls relay/go.sum                                   # expect: No such file or directory
grep -rn "StateActive" relay/channel/ --include=*.go | grep -v _test.go   # expect the SAME two writers Task 0 recorded
grep -rn "AttachOutput" relay/ --include=*.go | grep -v _test.go          # expect 3: the definition and two call sites
grep -rn "ffmpeg.StartPiped\|ffmpeg.Start(" relay/ --include=*.go | grep -v _test.go  # expect 4: two in spawn.go, one in output/fmp4.go, one in output/profile.go
```

**Name the accepted gap here rather than leaving it implied:** Task 5 added no test of its own, so `channel.OutputProfiles`, `SetClientOutputProfile`, `OutputSpec` and the failover refresh are covered only end-to-end through `httpapi` — which for each of them is a real pin with a break-check, not an absence. What remains genuinely unpinned is narrower and is stated in Ruling R5: the **staleness window** between two `next-source` answers, which has no Python counterpart to compare against.

- [ ] **Step 4: Run the Django label once more**

The same `docker exec` as Task 2 Step 4, on `apps.proxy.tests`. Expected: `OK`.

- [ ] **Step 5: Write the PR description**

In this order: what this PR does; **Ruling R9** and the chain it found in `views.py`; **Ruling R4** and what it cost on the Django side, wire shape included; **the three break-checks that did not redden on a first attempt** (rows 2, 8 and 12) and what closed each — the pass-through stand-in that made a ring invisible, the retry that spawned a real ffmpeg instead of the stand-in, and the remux whose input nothing could see; **the substring assertion that `os/exec` satisfied** (Constraint 42); **the break-check whose anchor did not match and ran green against unmodified code** (Constraint 36); **the credlint census** — **two** markers added (`control/nextsource.go`'s two decoders), one `redact.Error`, eleven packages clean; **two suppressions**, `internal/relaytest/standin.go`'s `#nosec G304` in `StdinPacketPID` and `output/profile_real_test.go`'s `#nosec G204` on the ffprobe call, each with its line and reason; **the measurements** — the real-ffmpeg numbers on your host and ffmpeg version, next to this plan's (ffmpeg 9.0.1, four chunks in 0.3s, ffprobe reporting `ac3` twice because `+resend_headers` repeats the PMT), and the eight-times-eight run counts; **the stated divergences**, as a list: the unbuildable-profile 500's body (R4); the profile set refreshed per channel rather than per client (R5); a malformed `X-Relay-Output` answered 400 where Python's hop answers 403 a hop earlier (R6); `redact.Line` on the transcode's stderr where Python logs raw (Constraint 12); the owner lock, state key and TTL refresh deleted (R2); **the edits no test pins**: the failover's profile refresh, `Channel.OutputProfiles`'s and `SetClientOutputProfile`'s own concurrency, and `FormatKey`'s nil arm on the fMP4 path (a no-profile fMP4 client, which 2c-6's tests already cover by name); **what this PR does not do**: no detail endpoint, no `advance`, no drain, no `client_connect` (2c-8); no Go coverage ratchet and no CodeQL Go pack (2c-9); no nginx route (2d); no HLS (Phase 4); no `metrics/curated` update.

---

## Break-check × what each can redden

Eighteen. Every row was run in the scratch module described in § Sequencing, and the **Message** column is what actually appeared, not what was predicted. **Apply every patch with a script that asserts its anchor is present and prints on success** (Constraint 36); one row below was first run with a wrong-indentation anchor, the patch silently did nothing, and the test ran green against unmodified code.

| # | Patch | Test | Verified message |
|---|---|---|---|
| 1 | `apps/proxy/next_source.py`: the **two-line** anchor `	argv = None\n	logger.error(` at twelve spaces' indent → `	logger.error(` plus a `continue` after the call. **A bare `argv = None` is NOT unique after this PR's own edit** — it occurs at `:148` too, in `_stream_profile_ref`'s pre-existing `stream_profile.argv` rescue, at eight spaces — so the patch would land in the wrong function (Constraints 36 and 45). Measured on the edited tree: the twelve-space two-line form occurs exactly once | `OutputProfilesOnTheContractTests::test_a_malformed_active_profile_carries_a_null_argv_not_a_500` | RED — `AssertionError: '36' not found in {'35': {...}} : a profile whose parameters shlex could not split is absent from output_profiles; it must be present with a null argv, or a relay cannot tell it from a DEACTIVATED profile and will serve the client plain where Python answers 500` |
| 2 | `channel/output.go`: **`	if entry, running := c.outputs[format]; running {\n		entry.refs++`** → `; running && false {` — the bare `if entry, running := c.outputs[format]; running` occurs **twice** (`AttachOutput` and `releaseOutput`), so the anchor must carry the following line (Constraints 36 and 45) | `TestTwoClientsOnOneOutputProfileShareOneTranscode` | RED — `the relay spawned 2 transcodes for two clients on one Output Profile, want 1`. **And the registry and PID assertions stayed GREEN**, which is Global Constraint 35's demonstration: with the spawn assertion commented out the whole test passed while a process leaked per client |
| 3 | `output/profile.go`: `FormatKey`'s body → **`_ = strconv.Itoa; return format`** — a bare `return format` leaves `strconv` unused and the package fails to BUILD, which is not the mechanism under test (Constraint 44's sibling: a break-check must redden on its own claim, not on a compile error) | `TestTwoClientsOnOneOutputProfileShareOneTranscode`, `…Chained` | RED — `the channel's output registry holds [mpegts], want exactly one mpegts:p3` and `holds [mpegts fmp4], want exactly mpegts:p3 and fmp4:p3` |
| 4 | `httpapi/stream.go`: `serveClient(…, source, …)` → `serveClient(…, ch.Ring(), …)` | `TestTwoClientsOnOneOutputProfileShareOneTranscode`, `…ShareOneUpstream` | RED — `the first client's packets carry PIDs map[256:174], want only the transcode's 0x1ff`. **This is the row `--ts-pid` exists for**: with a pass-through stand-in both rings hold the same bytes and this patch is invisible |
| 5 | `httpapi/profile.go`: the not-found branch → `writeProfileFailure(w); return nil, nil, false` | `TestAProfileMissingFromTheAnswerIsServedWithoutOne` | RED — `a tune naming a deactivated profile answered 500, want 200` |
| 6 | `httpapi/profile.go`: `if !profiles.Known {` → `if false {` | `TestATuneNamingAProfileAgainstAnOlderControlPlaneIsABadGateway` | RED — `a tune naming a profile against a control plane with no output_profiles answered 200, want 502` |
| 7 | `channel/output.go`: `if entry.refs <= 0 {` → `if false {` | `TestTheLastProfileClientLeavingStopsTheTranscodeAndNotTheChannel` | RED — `the channel still runs [mpegts:p3] fifteen seconds after its last profile client left`. **First run used a wrong-indentation anchor, the patch did nothing, and the test ran green** — Constraint 36's scar |
| 8 | `output/profile.go`: `bsf: false` → `bsf: true` | `TestAProfileStderrIsNotWatchedForTheBitstreamFilterError` | RED — `the relay spawned 2 transcodes for one Output Profile whose stderr named the bitstream filter, want 1`. **Its first form did not say that.** With `cfg.Remux` left empty the retry spawned a REAL ffmpeg remux (`Config.command()` falls back to `RemuxCommand`), the spawn log stayed at 1 because the second process was not the stand-in, and the test reported `the transcode was still running fifteen seconds after its process exited` after a 15s wait. Two fixes, both kept: `StartProfile` now fills `cfg.Remux` from the profile's own command line (Ruling R3), and the test asserts the **count** before the liveness. The row now reddens in 0.02s |
| 9 | `httpapi/profile.go`: drop `ch.SetClientOutputProfile(client.ID, nil)` — the setter ALONE; the bare `client.OutputProfileID = nil` that once sat beside it is gone, deleted as the data race break-check 16 pins | `TestAProfileMissingFromTheAnswerIsServedWithoutOne` | RED — `the client is registered with output_profile_id 3, want null: the profile it named is not active` |
| 10 | `control/nextsource.go`: move `a.OutputProfilesPresent = true` above the length check | `TestAnAbsentOutputProfilesKeyIsNotAnEmptyOne`, `TestATuneNamingAProfileAgainstAnOlderControlPlaneIsABadGateway` | RED — `OutputProfilesPresent is true, want false` and `answered 200, want 502` |
| 11 | `output/profile.go`: delete `if cfg.Command == "" { return nil, ErrProfileCommandAbsent }` | `TestAProfileWithNoCommandIsRefusedRatherThanDefaultedToTheRemux` | RED — `the error is "output: starting the Output Profile transcode: ffmpeg: starting : exec: no command", want ErrProfileCommandAbsent`. **Its first form stayed GREEN**: the assertion was `strings.Contains(err, "no command")` and `os/exec`'s own message for an empty `Path` is literally `exec: no command` — two sources for one string (Constraint 42). Closed with `errors.Is` |
| 12 | `httpapi/fmp4.go`: `channel.OutputSpec{Remux: deps.Remux, Source: source}` → drop `Source` | `TestAnFMP4ClientOnAnOutputProfileRunsTheTranscodeAndTheRemuxChained` | RED — `the remux's fd 0 carried PID 0x100, want the transcode's 0x1ff (the channel's own ring is 0x100): the fMP4 remux must read the Output Profile's output, not the channel's`. **Its first form stayed GREEN**: the fMP4 stand-in ignores its input entirely, so nothing observable said which ring fed it. `--stdin-pid-log` is what closed it |
| 13 | `channel/channel.go`: delete `defer c.stopOutputs()` | `TestStoppingTheChannelStopsItsProfileTranscode` | RED — `the stopped channel still runs [mpegts:p3] with a reference on it that was never released`. **Its first form stayed GREEN**: with only the client's own reference, a stopped channel closes its ring, the pass-through transcode reaches EOF and exits, and the client's deferred release empties the registry — the refcount covered for the mechanism under test. Closed by having the test take a second reference it never drops. (2c-6's `TestStoppingTheChannelStopsItsRemux` does **not** have this hole and reddens on the same patch, because its stand-in keeps producing fragments after fd 0 closes) |
| 14 | `control/nextsource.go`: `Command()`'s `return p.Argv[0]` → `p.Argv[len(p.Argv)-1]` | `TestTheOutputProfileArgvCarriesTheCommandFirst` | RED — `Command() is "pipe:1", want argv[0] -- ffmpeg` |
| 15 | `control/nextsource.go`: `Args()`'s `return p.Argv[1:]` → `p.Argv` | `TestTheOutputProfileArgvCarriesTheCommandFirst` | RED — `Args() is [ffmpeg -i pipe:0 -c:a ac3 pipe:1], want everything after argv[0]: [-i pipe:0 -c:a ac3 pipe:1]` |

| 16 | `httpapi/profile.go`: reinstate `client.OutputProfileID = nil` after `ch.SetClientOutputProfile(client.ID, nil)` | `TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint` | RED — `WARNING: DATA RACE`, a write at `httpapi/profile.go:94` against a read at `channel/channel.go:243` (`ClientSnapshot`). **This row exists because the line was IN the plan** until the review found it: it looks free — same field, same value, a pointer this goroutine created — and it races the list endpoint, because `Attach` put that pointer in the channel's registry. Run this row with `-race` or it proves nothing |
| 17 | `channel/failover.go`: delete the two-line `if resolved.OutputProfiles.Known { c.outputProfiles = … }` | `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` | RED — `the channel still holds map[3:{…}] after a failover whose answer carried profile 9: the refresh at channel/failover.go did not happen`. **Before this test existed the same deletion left the ENTIRE suite green**, which is what the review found: Ruling R5 argued for a mechanism nothing exercised |
| 18 | `channel/failover.go`: drop the `Known` guard so the refresh is unconditional | the same test | RED — `a DEGRADED failover cleared the profile set to map[]: the cached candidate list carries no answer, so Resolved.OutputProfiles.Known is false and the channel keeps what it had`. The other half of one rule, and the reason both arms are in one test: a relay refreshing from the degraded cache would CLEAR the map rather than update it |

**And one more, on the real-ffmpeg test**, kept separate because it patches a fixture rather than the relay: changing the AC3 argv's `-c:a ac3` to `-c:a copy` reddens `TestARealAC3ProfileTranscodesTheChannelsRing` with `the transcode's audio codec is "aac", want ac3`, which is what makes the ffprobe assertion a transcode claim rather than a plumbing one.

---

## What to report back

1. The merged 2c-6 SHA you seeded from, and every ledger row as matched or differing (Task 0).
2. The two `StateActive` writer lines, counted at Task 0 and again at Task 9.
3. The eighteen break-check messages, **as they appeared**, with the three that needed a second form called out, and rows 16–18 run under `-race` (16 proves nothing without it).
4. The eight consecutive `relay/output` runs, the eight `httpapi` subset runs, and the three whole-module runs.
5. The ffmpeg version your real test logged and what it measured.
6. `credlint: 11 package(s) clean`, `OK: relay depends on the standard library only`, `go.sum` absent, `0 issues.` under three GOOS.
7. The Django label's `Ran N tests … OK`.
8. Anything in this plan your tree contradicted.

---

## Appendix — the files, in full

Every file below was built, vetted under three GOOS, race-tested and linted at zero findings in the scratch module § Sequencing describes, **built and re-verified against the MERGED 2c-6 tree, `main` at `eb7fac07`**, whose 91 Go files (42 of them tests) were taken with `git archive`. All fifteen diffs below applied to it with `git apply` and no fuzz. Whole files are given whole; edits to 2c-6's files are given as diffs against the tree that plan's appendices produce.


### Appendix A — `relay/control/nextsource.go`

The wire type and the answer's field pair. `OutputProfileRef.UnmarshalJSON` and `NextSourceAnswer.UnmarshalJSON` exist for the same reason `StreamProfileRef`'s does: `encoding/json` cannot report an absent key on a slice or a map field.

**`relay/control/nextsource.go`**

```diff
--- a/control/nextsource.go
+++ b/control/nextsource.go
@@ -124,9 +124,72 @@
 	IncludeAlternates bool   `json:"include_alternates"`
 }
 
-// NextSourceAnswer is the response body. output_profiles is deliberately not
-// declared: 2c-7 owns Output Profiles and json.Unmarshal ignores what no field
-// names, so leaving it out now costs nothing and claims nothing.
+// OutputProfileRef is one entry of the answer's output_profiles map: an
+// is_active OutputProfile with its command line already built
+// (apps/proxy/serializers.py:217-230's OutputProfileRefSerializer).
+//
+// ARGV CARRIES THE COMMAND AS ELEMENT 0, unlike StreamProfileRef.Argv, which
+// has it stripped off the front. core/models.py:200-203's build_command is
+// `[self.command] + shlex_split(self.parameters)` and 2b-2 sends the whole
+// list, where next_source.py's _stream_profile_ref sends `command` in its own
+// field and the REST in argv. The asymmetry is on the wire and is reproduced
+// rather than tidied: Command() and Args() below are the only places that
+// split it, and TestTheOutputProfileArgvCarriesTheCommandFirst pins it against
+// the same Python lines.
+//
+// Argv nil with Present true is Django saying it could NOT build the list --
+// shlex refused the profile's parameters (an unbalanced quote), which
+// OutputProfileSerializer validates nothing against, so such a row can already
+// be sitting in the database.
+type OutputProfileRef struct {
+	ID int `json:"id"`
+
+	// Argv is build_command() in full, or nil when Django sent null.
+	Argv []string `json:"-"`
+}
+
+// UnmarshalJSON decodes the entry, mapping an explicit null argv to a nil
+// slice and an empty list to an empty non-nil one -- the same distinction
+// StreamProfileRef.UnmarshalJSON makes, for the same reason.
+func (p *OutputProfileRef) UnmarshalJSON(data []byte) error {
+	var aux struct {
+		ID      int             `json:"id"`
+		ArgvRaw json.RawMessage `json:"argv"`
+	}
+	if err := json.Unmarshal(data, &aux); err != nil {
+		return err
+	}
+	p.ID, p.Argv = aux.ID, nil
+	if len(aux.ArgvRaw) == 0 || bytes.Equal(bytes.TrimSpace(aux.ArgvRaw), []byte("null")) {
+		return nil
+	}
+	if err := json.Unmarshal(aux.ArgvRaw, &p.Argv); err != nil {
+		return fmt.Errorf("output_profiles[].argv is not a list of strings: %w", err) // credential-logging: ok - an encoding/json type error naming the JSON shape, never a value
+	}
+	if p.Argv == nil {
+		p.Argv = []string{}
+	}
+	return nil
+}
+
+// Command is the executable to spawn: argv[0]. Empty when Django could not
+// build the list, or when the profile's own command field is blank.
+func (p OutputProfileRef) Command() string {
+	if len(p.Argv) == 0 {
+		return ""
+	}
+	return p.Argv[0]
+}
+
+// Args is everything after the command, the way ffmpeg.StartPiped takes it.
+func (p OutputProfileRef) Args() []string {
+	if len(p.Argv) < 2 {
+		return []string{}
+	}
+	return p.Argv[1:]
+}
+
+// NextSourceAnswer is the response body.
 type NextSourceAnswer struct {
 	Source     *Source  `json:"source"`
 	Alternates []Source `json:"alternates"`
@@ -134,8 +197,56 @@
 	// unmarshals to the empty string. Callers test Source == nil, never this.
 	Error         string   `json:"error"`
 	ProxySettings Settings `json:"proxy_settings"`
+
+	// OutputProfiles is every is_active OutputProfile, keyed by stringified
+	// id (apps/proxy/next_source.py's _with_output_profiles, 2b-2). The WHOLE
+	// active set travels because next-source runs once per CHANNEL while the
+	// profile is resolved once per CLIENT, and the second client on a running
+	// channel makes no next-source call at all (views.py:712) -- 2b-2's own
+	// Ruling R3, which named a Go relay caching the map per channel as what
+	// closes views.py:152's ORM read.
+	OutputProfiles map[string]OutputProfileRef `json:"-"`
+
+	// OutputProfilesPresent reports whether the answer carried the key at
+	// all. An ABSENT key is a control plane older than 2b-2 and is a contract
+	// mismatch, not "this deployment has no profiles"; an empty OBJECT is the
+	// latter, and apps/proxy/tests/test_next_source_api.py::
+	// test_no_active_profiles_is_an_empty_object_not_a_missing_key pins that
+	// Django sends one. encoding/json cannot tell a nil map from an absent
+	// key on its own, which is why this flag exists -- StreamProfileRef.
+	// ArgvPresent is the same shape for the same reason.
+	OutputProfilesPresent bool `json:"-"`
 }
 
+// UnmarshalJSON decodes the answer and records whether output_profiles was
+// present, which a plain map field cannot report.
+func (a *NextSourceAnswer) UnmarshalJSON(data []byte) error {
+	type plain NextSourceAnswer
+	var aux struct {
+		plain
+		ProfilesRaw json.RawMessage `json:"output_profiles"`
+	}
+	if err := json.Unmarshal(data, &aux); err != nil {
+		return err
+	}
+	*a = NextSourceAnswer(aux.plain)
+	a.OutputProfiles, a.OutputProfilesPresent = nil, false
+	if len(aux.ProfilesRaw) == 0 {
+		return nil
+	}
+	a.OutputProfilesPresent = true
+	if bytes.Equal(bytes.TrimSpace(aux.ProfilesRaw), []byte("null")) {
+		return nil
+	}
+	if err := json.Unmarshal(aux.ProfilesRaw, &a.OutputProfiles); err != nil {
+		return fmt.Errorf("output_profiles is not an object of profiles: %w", err) // credential-logging: ok - an encoding/json type error naming the JSON shape, never a value
+	}
+	if a.OutputProfiles == nil {
+		a.OutputProfiles = map[string]OutputProfileRef{}
+	}
+	return nil
+}
+
 // Unavailable means the control plane could not be reached or did not answer
 // like Django. Only this is retried, and only this triggers the degraded
 // fallback 2c-5 adds.
```


### Appendix B — `relay/control/outputprofile_test.go`

Three tests. The argv literal is `apps/proxy/tests/test_next_source_api.py:551`'s own expected value, read off that line.

**`relay/control/outputprofile_test.go`**

```go
package control

import (
	"encoding/json"
	"reflect"
	"testing"
)

// THE OUTPUT PROFILE ARGV CARRIES THE COMMAND AS ELEMENT 0, where
// stream_profile.argv does not. The literal below is
// apps/proxy/tests/test_next_source_api.py:551's own expected value, read off
// that line rather than computed from the model: core/models.py:200-203's
// build_command is `[self.command] + shlex_split(self.parameters)` and
// apps/proxy/serializers.py:230 sends the result whole, while
// apps/proxy/next_source.py's _stream_profile_ref sends `command` separately
// and argv without it.
//
// A DIFFERENT SHAPE ON THE SAME WIRE IS EASY TO GET WRONG IN ONE DIRECTION
// ONLY: a relay that stripped element 0 here would spawn `-i` with the real
// command as its first argument, which fails loudly; one that did NOT strip it
// where stream_profile needs it would pass the command twice. Both are pinned,
// this one here.
func TestTheOutputProfileArgvCarriesTheCommandFirst(t *testing.T) {
	const body = `{"id": 4, "argv": ["ffmpeg", "-i", "pipe:0", "-c:a", "ac3", "pipe:1"]}`
	var ref OutputProfileRef
	if err := json.Unmarshal([]byte(body), &ref); err != nil {
		t.Fatalf("decoding the entry: %v", err)
	}
	if ref.ID != 4 {
		t.Fatalf("the entry's id is %d, want 4", ref.ID)
	}
	if got := ref.Command(); got != "ffmpeg" {
		t.Fatalf("Command() is %q, want argv[0] -- ffmpeg", got)
	}
	want := []string{"-i", "pipe:0", "-c:a", "ac3", "pipe:1"}
	if got := ref.Args(); !reflect.DeepEqual(got, want) {
		t.Fatalf("Args() is %v, want everything after argv[0]: %v", got, want)
	}
}

// AN ABSENT output_profiles KEY IS NOT AN EMPTY MAP, and encoding/json cannot
// tell them apart on a plain map field -- both leave it nil. The distinction
// is load-bearing: an empty object is a deployment with no active profile (and
// Django always sends one, pinned by
// apps/proxy/tests/test_next_source_api.py::
// test_no_active_profiles_is_an_empty_object_not_a_missing_key), while an
// absent key is a control plane older than Phase 2 PR 2b-2, which a tune
// naming a profile must fail on rather than serve plain.
//
// THE TWO CASES ARE ASSERTED AGAINST EACH OTHER in one test, so a decoder that
// collapsed them could not pass half of it.
func TestAnAbsentOutputProfilesKeyIsNotAnEmptyOne(t *testing.T) {
	for _, tc := range []struct {
		name    string
		body    string
		present bool
		size    int
	}{
		{"absent", `{"source": null, "error": null, "alternates": []}`, false, 0},
		{"empty object", `{"source": null, "error": null, "alternates": [], "output_profiles": {}}`, true, 0},
		{"one entry", `{"source": null, "error": null, "alternates": [], "output_profiles": {"4": {"id": 4, "argv": ["ffmpeg", "pipe:1"]}}}`, true, 1},
		// Not a shape Django sends; decoded rather than rejected so an
		// unexpected null cannot be read as "the key was there with entries".
		{"explicit null", `{"source": null, "error": null, "alternates": [], "output_profiles": null}`, true, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var answer NextSourceAnswer
			if err := json.Unmarshal([]byte(tc.body), &answer); err != nil {
				t.Fatalf("decoding the answer: %v", err)
			}
			if answer.OutputProfilesPresent != tc.present {
				t.Fatalf("OutputProfilesPresent is %v, want %v", answer.OutputProfilesPresent, tc.present)
			}
			if len(answer.OutputProfiles) != tc.size {
				t.Fatalf("the map holds %d entries, want %d", len(answer.OutputProfiles), tc.size)
			}
		})
	}
}

// A NULL argv IS DJANGO SAYING IT COULD NOT BUILD THE LIST -- shlex refused
// the profile's parameters, which OutputProfileSerializer validates nothing
// against. It is a DIFFERENT fault from the profile being absent and gets a
// different answer, so the decode must keep them apart: nil Argv with the
// entry present.
func TestANullOutputProfileArgvDecodesAsPresentButUnbuildable(t *testing.T) {
	const body = `{"source": null, "error": null, "alternates": [], "output_profiles": {"9": {"id": 9, "argv": null}}}`
	var answer NextSourceAnswer
	if err := json.Unmarshal([]byte(body), &answer); err != nil {
		t.Fatalf("decoding the answer: %v", err)
	}
	entry, found := answer.OutputProfiles["9"]
	if !found {
		t.Fatal("the entry with a null argv vanished from the map; an unbuildable profile must stay visible")
	}
	if entry.Argv != nil {
		t.Fatalf("a null argv decoded as %v, want nil", entry.Argv)
	}
	if got := entry.Command(); got != "" {
		t.Fatalf("Command() is %q for a null argv, want the empty string", got)
	}
	// And an EMPTY LIST is not the same thing: Django sends [] for a profile
	// whose build_command somehow produced nothing, which is still "built".
	const empty = `{"source": null, "error": null, "alternates": [], "output_profiles": {"9": {"id": 9, "argv": []}}}`
	var second NextSourceAnswer
	if err := json.Unmarshal([]byte(empty), &second); err != nil {
		t.Fatalf("decoding the empty-argv answer: %v", err)
	}
	if second.OutputProfiles["9"].Argv == nil {
		t.Fatal("an empty argv list decoded as nil, which is how a NULL argv is spelled")
	}
}
```


### Appendix C — the three Python edits

Ruling R4. No migration, no new route, no new field — one serializer keyword, one control-flow change, one test.


**`apps/proxy/serializers.py`**

```diff
diff --git a/apps/proxy/serializers.py b/apps/proxy/serializers.py
index d2fcc977..dc1b4c39 100644
--- a/apps/proxy/serializers.py
+++ b/apps/proxy/serializers.py
@@ -227,7 +227,20 @@ class OutputProfileRefSerializer(serializers.Serializer):
     """
 
     id = serializers.IntegerField()
-    argv = serializers.ListField(child=serializers.CharField(allow_blank=True))
+    # allow_null, Phase 2 PR 2c-7: null means Django could NOT build the
+    # list -- shlex refused the profile's `parameters` (an unbalanced
+    # quote), which OutputProfileSerializer validates nothing against, so
+    # such a row can already be sitting in the database. Sending the entry
+    # with a null argv rather than omitting it is what lets a relay tell
+    # "this profile is broken" (Python answers 500 to the client that
+    # selected it) from "this profile is not active" (Python serves that
+    # client with no profile at all). Omitted, the two are the same
+    # absence on the wire and the second answer would be given to both.
+    # The same three-state shape StreamProfileRefSerializer's argv already
+    # has, for the same reason (Amendment A4.1).
+    argv = serializers.ListField(
+        child=serializers.CharField(allow_blank=True), allow_null=True
+    )
 
 
 class NextSourceResponseSerializer(serializers.Serializer):
```


**`apps/proxy/next_source.py`**

```diff
diff --git a/apps/proxy/next_source.py b/apps/proxy/next_source.py
index f6930fd4..f35b5c43 100644
--- a/apps/proxy/next_source.py
+++ b/apps/proxy/next_source.py
@@ -871,13 +871,25 @@ def _with_output_profiles(answer):
             # next-source answer means one bad row would otherwise 500
             # next-source for every channel, on every tune, failover and
             # resume, regardless of which profile that channel uses.
-            # Skip it and keep the rest of the map serving.
+            #
+            # Phase 2 PR 2c-7 changed the shape of that rescue and not
+            # its purpose: the entry is sent with a NULL argv instead of
+            # being omitted. Omitting it made a broken profile
+            # indistinguishable on the wire from a DEACTIVATED one, and
+            # those get opposite answers -- Python 500s the client that
+            # selected a broken profile (build_command raises inside
+            # stream_ts's try) and serves the client whose profile was
+            # deactivated with no profile at all (views.py:150-155
+            # re-reads the row with is_active=True and gets None). A Go
+            # relay reading this map could only reproduce one of the two.
+            # next-source itself still answers, which is what this arm
+            # exists for.
+            argv = None
             logger.error(
-                "OutputProfile %s has unparseable parameters; omitting "
-                "it from next-source's output_profiles map",
+                "OutputProfile %s has unparseable parameters; its entry "
+                "in next-source's output_profiles map carries a null argv",
                 profile.id,
             )
-            continue
         output_profiles[str(profile.id)] = {"id": profile.id, "argv": argv}
     answer["output_profiles"] = output_profiles
     return answer
```


**`apps/proxy/tests/test_next_source_api.py`**

```diff
diff --git a/apps/proxy/tests/test_next_source_api.py b/apps/proxy/tests/test_next_source_api.py
index 5e9540b9..5aeac7b5 100644
--- a/apps/proxy/tests/test_next_source_api.py
+++ b/apps/proxy/tests/test_next_source_api.py
@@ -603,7 +603,7 @@ class OutputProfilesOnTheContractTests(RelayApiTestCase):
             str(seeded.id), self._next_source(self.channel.uuid)["output_profiles"]
         )
 
-    def test_a_malformed_active_profile_is_skipped_not_a_500(self):
+    def test_a_malformed_active_profile_carries_a_null_argv_not_a_500(self):
         # Review finding B1. OutputProfileSerializer validates nothing,
         # so an unbalanced quote in `parameters` can already be sitting
         # in the database. Before output_profiles existed, a malformed
@@ -611,8 +611,17 @@ class OutputProfilesOnTheContractTests(RelayApiTestCase):
         # active profile into EVERY next-source answer means one bad row
         # would otherwise 500 next-source for every channel on every
         # tune, failover and resume -- regardless of which profile that
-        # channel uses. Assert absence explicitly: a call that merely
-        # succeeds could still be silently missing the good rows too.
+        # channel uses.
+        #
+        # 2c-7 changed the rescue from OMITTING the entry to sending it
+        # with a null argv. Omission made a broken profile look exactly
+        # like a deactivated one, and the two get opposite answers: a
+        # client selecting a broken profile gets a 500 (build_command
+        # raises inside stream_ts's try), and a client whose profile was
+        # deactivated is served with no profile at all. A relay reading
+        # this map could only reproduce one of the two. The null is what
+        # keeps them apart, and it is the same three-state shape
+        # stream_profile.argv already uses.
         from core.models import OutputProfile
 
         good = OutputProfile.objects.create(
@@ -627,6 +636,16 @@ class OutputProfilesOnTheContractTests(RelayApiTestCase):
             parameters='-i pipe:0 "unterminated',
             is_active=True,
         )
+        # A DEACTIVATED ROW, created BEFORE the call below so the answer
+        # really had the chance to carry it. It is the other half of the
+        # distinction this test exists for: "present with a null argv" and
+        # "absent" are only being told apart if both appear in one answer.
+        gone = OutputProfile.objects.create(
+            name="2b2-deactivated",
+            command="ffmpeg",
+            parameters="-i pipe:0 -c:a ac3 pipe:1",
+            is_active=False,
+        )
         # Confirm the fixture actually reproduces the failure mode this
         # test exists to guard -- if shlex ever stops raising on this
         # input, the test above would pass for the wrong reason.
@@ -645,8 +664,25 @@ class OutputProfilesOnTheContractTests(RelayApiTestCase):
             f"no ERROR log named the malformed profile's id ({bad.id}): {logs.output}",
         )
 
-        self.assertNotIn(str(bad.id), answer["output_profiles"])
-        self.assertIn(str(good.id), answer["output_profiles"])
+        # PRESENT, with a null argv -- not absent. The presence is asserted
+        # first and by name: without it the equality below reports a bare
+        # KeyError, which says which key is missing but not why that matters.
+        self.assertIn(
+            str(bad.id), answer["output_profiles"],
+            "a profile whose parameters shlex could not split is absent from "
+            "output_profiles; it must be present with a null argv, or a relay "
+            "cannot tell it from a DEACTIVATED profile and will serve the "
+            "client plain where Python answers 500",
+        )
+        # Asserted as the whole entry rather than as `argv is None`, so a
+        # serializer that started dropping the id would fail here too.
+        self.assertEqual(
+            answer["output_profiles"][str(bad.id)],
+            {"id": bad.id, "argv": None},
+        )
+        self.assertNotIn(str(gone.id), answer["output_profiles"])
+        # And the good row is untouched: a call that merely succeeds could
+        # still be silently missing the rows that build.
         self.assertEqual(
             answer["output_profiles"][str(good.id)],
             {
```


### Appendix D — `relay/internal/relaytest/controlplane.go`

The fake control plane's `output_profiles`. Three shapes a test needs: the empty object Django always sends, entries with argv, and the key absent entirely.

**`relay/internal/relaytest/controlplane.go`**

```diff
--- a/internal/relaytest/controlplane.go
+++ b/internal/relaytest/controlplane.go
@@ -4,6 +4,7 @@
 	"encoding/json"
 	"net/http"
 	"net/http/httptest"
+	"strconv"
 	"strings"
 	"sync"
 	"time"
@@ -118,8 +119,35 @@
 	// SlotReserved is the source's slot_reserved flag. Nil means true, the
 	// value every earlier fixture sent.
 	SlotReserved *bool
+
+	// OutputProfiles is the answer's output_profiles map, keyed by
+	// stringified id (2c-7). Nil sends the empty object Django sends when no
+	// profile is active -- apps/proxy/tests/test_next_source_api.py::
+	// test_no_active_profiles_is_an_empty_object_not_a_missing_key pins that
+	// it is an object and not a missing key.
+	OutputProfiles map[string]OutputProfileConfig
+
+	// OutputProfilesAbsent leaves the key out entirely: the shape of a
+	// control plane older than Phase 2 PR 2b-2, which the relay must report
+	// as a contract mismatch rather than as "no profiles are configured".
+	OutputProfilesAbsent bool
 }
 
+// OutputProfileConfig is one entry of the fake's output_profiles map.
+type OutputProfileConfig struct {
+	// ID is the entry's id field. Zero means the map key parsed as an int.
+	ID int
+
+	// Argv is build_command() in full, COMMAND FIRST -- the shape
+	// OutputProfileRefSerializer sends (apps/proxy/serializers.py:230),
+	// which is not stream_profile.argv's shape.
+	Argv []string
+
+	// ArgvNull sends argv as null: a profile whose parameters shlex could
+	// not split.
+	ArgvNull bool
+}
+
 // AlternateConfig is one alternate stream the fake offers. Argv is the
 // built argv for THIS stream's URL, as Django builds one per candidate
 // (Amendment A4.1); nil renders as [] under the config's Command.
@@ -147,6 +175,8 @@
 	settings map[string]any
 	status   int
 	delay    time.Duration
+	profiles map[string]OutputProfileConfig
+	hasProfs bool
 }
 
 // SetSettings replaces the proxy_settings every LATER answer carries. It is
@@ -159,6 +189,21 @@
 	c.settings = settings
 }
 
+// SetOutputProfiles replaces the output_profiles map every LATER answer
+// carries. It is how a test changes the active Output Profile set between two
+// next-source calls, the way an operator editing a profile does, to show that
+// a running channel picks the change up on its next answer and NOT from the
+// degraded cache (2c-7's Ruling R5).
+//
+// A separate `hasProfs` flag rather than a nil check, for ControlPlaneConfig.
+// OutputProfiles' own reason: nil means "the empty object Django sends when
+// nothing is active", which a test may want to set deliberately.
+func (c *ControlPlane) SetOutputProfiles(profiles map[string]OutputProfileConfig) {
+	c.mu.Lock()
+	defer c.mu.Unlock()
+	c.profiles, c.hasProfs = profiles, true
+}
+
 // SetStatus makes every LATER call answer with status, whatever the route:
 // 503 is an outage the client retries once and then degrades on, 403 a
 // refusal it never degrades on. Zero restores the configured behaviour. It is
@@ -388,11 +433,37 @@
 	}
 
 	answer := map[string]any{
-		"alternates":      []any{},
-		"error":           nil,
-		"proxy_settings":  settings,
-		"output_profiles": map[string]any{},
-		"source":          nil,
+		"alternates":     []any{},
+		"error":          nil,
+		"proxy_settings": settings,
+		"source":         nil,
+	}
+	c.mu.Lock()
+	liveProfiles, overridden := c.profiles, c.hasProfs
+	c.mu.Unlock()
+	configured := cfg.OutputProfiles
+	if overridden {
+		configured = liveProfiles
+	}
+	if !cfg.OutputProfilesAbsent {
+		profiles := map[string]any{}
+		for key, entry := range configured {
+			id := entry.ID
+			if id == 0 {
+				id, _ = strconv.Atoi(key)
+			}
+			object := map[string]any{"id": id}
+			switch {
+			case entry.ArgvNull:
+				object["argv"] = nil
+			case entry.Argv == nil:
+				object["argv"] = []string{}
+			default:
+				object["argv"] = entry.Argv
+			}
+			profiles[key] = object
+		}
+		answer["output_profiles"] = profiles
 	}
 	chosen := -1
 	for i, cand := range candidates {
```


### Appendix E — `relay/internal/relaytest/standin.go`

Two flags. `--ts-pid` makes a pass-through stand-in's output distinguishable from its input; `--stdin-pid-log` makes a chained process's input visible. Constraint 41 is why both exist, and break-check rows 4 and 12 are what paid for them.

**`relay/internal/relaytest/standin.go`**

```diff
--- a/internal/relaytest/standin.go
+++ b/internal/relaytest/standin.go
@@ -74,6 +74,18 @@
 //	--fmp4-exit              exit after the last fragment instead of staying
 //	                         alive producing nothing -- a remux that ENDED,
 //	                         where the default is one that STALLED
+//	--ts-pid N               rewrite the 13-bit PID of every 188-byte packet
+//	                         it copies to N, so a test can tell this process's
+//	                         output from its input. What an Output Profile
+//	                         transcode does in miniature: the bytes on fd 1 are
+//	                         still a transport stream and are still the same
+//	                         length, and they are not the bytes on fd 0.
+//	--stdin-pid-log PATH     write the PID of the first whole transport-stream
+//	                         packet it reads on fd 0 to PATH, so a test can
+//	                         assert WHICH ring a chained process was fed. Only
+//	                         meaningful with --fmp4-fragments, whose output
+//	                         ignores its input entirely; without it nothing
+//	                         about a remux's fd 0 is observable from outside.
 //	--spawn-log PATH         append this process's pid to PATH before doing
 //	                         anything else, so a test can count how many times
 //	                         the relay spawned it. apps/proxy/live_proxy/tests/
@@ -122,6 +134,9 @@
 	fmp4BSFError   bool
 	fmp4Exit       bool
 	spawnLog       string
+	tsPID          int
+	haveTSPID      bool
+	stdinPIDLog    string
 	haveExitAfter  bool
 	haveDeadAir    bool
 	positional     []string
@@ -173,6 +188,11 @@
 			o.haveFMP4 = true
 		case "--fmp4-exit":
 			o.fmp4Exit = true
+		case "--ts-pid":
+			o.tsPID, _ = strconv.Atoi(next())
+			o.haveTSPID = true
+		case "--stdin-pid-log":
+			o.stdinPIDLog = next()
 		case "--spawn-log":
 			o.spawnLog = next()
 		case "-i":
@@ -292,10 +312,24 @@
 
 	copied := 0
 	buf := make([]byte, 8192)
+	// The PID rewrite carries a partial packet between reads: 8192 is not a
+	// multiple of 188, so a packet header can straddle two Read calls and a
+	// per-read rewrite would miss every packet that did.
+	var carry []byte
 	for {
 		n, err := source.Read(buf)
 		if n > 0 {
 			chunk := buf[:n]
+			if o.haveTSPID {
+				chunk, carry = rewritePID(append(carry, chunk...), o.tsPID)
+				n = len(chunk)
+				if n == 0 {
+					if err != nil {
+						return o.exitCode
+					}
+					continue
+				}
+			}
 			if o.haveExitAfter && copied+n >= o.exitAfter {
 				_, _ = os.Stdout.Write(chunk[:o.exitAfter-copied])
 				return o.exitCode
@@ -325,6 +359,21 @@
 	}
 }
 
+// rewritePID sets the 13-bit PID of every WHOLE packet in data and returns the
+// rewritten prefix plus the trailing bytes that are not yet a whole packet.
+//
+// It assumes data begins on a packet boundary, which it does: the relay's ring
+// hands the writer whole 188-byte chunks, and every byte after that is
+// accounted for by the carry.
+func rewritePID(data []byte, pid int) (whole, rest []byte) {
+	full := (len(data) / PacketSize) * PacketSize
+	for offset := 0; offset < full; offset += PacketSize {
+		data[offset+1] = (data[offset+1] &^ 0x1F) | byte((pid>>8)&0x1F)
+		data[offset+2] = byte(pid & 0xFF)
+	}
+	return data[:full], append([]byte(nil), data[full:]...)
+}
+
 // pumpStderr replays a capture: the preamble at once, then one progress
 // record per interval, CR-terminated -- standin.py:117-156, including its
 // stated non-exactness about the LAST record of a real capture.
@@ -381,6 +430,9 @@
 	// ffmpeg reads continuously too; a stand-in that did not would turn every
 	// test into a deadlock that looked like a slow one.
 	go func() {
+		if o.stdinPIDLog != "" {
+			logFirstPacketPID(os.Stdin, o.stdinPIDLog)
+		}
 		_, _ = io.Copy(io.Discard, os.Stdin)
 	}()
 
@@ -410,6 +462,43 @@
 	}
 }
 
+// logFirstPacketPID reads until it has one whole transport-stream packet and
+// writes that packet's PID to path as decimal. It gives up silently after a
+// bounded read: a caller that never sends a transport stream is a test whose
+// own assertion will say so more usefully than this could.
+func logFirstPacketPID(source io.Reader, path string) {
+	buf := make([]byte, 0, 4*PacketSize)
+	chunk := make([]byte, PacketSize)
+	for len(buf) < 4*PacketSize {
+		n, err := source.Read(chunk)
+		buf = append(buf, chunk[:n]...)
+		for offset := 0; offset+PacketSize <= len(buf); offset++ {
+			if buf[offset] != SyncByte {
+				continue
+			}
+			_ = os.WriteFile(path, []byte(strconv.Itoa(PacketPID(buf[offset:offset+PacketSize]))), 0o600)
+			return
+		}
+		if err != nil {
+			return
+		}
+	}
+}
+
+// StdinPacketPID reads back what --stdin-pid-log wrote, or -1 when the file
+// does not exist -- which is what a process that was fed nothing leaves.
+func StdinPacketPID(path string) int {
+	raw, err := os.ReadFile(path) // #nosec G304 -- a path the test itself chose
+	if err != nil {
+		return -1
+	}
+	pid, err := strconv.Atoi(strings.TrimSpace(string(raw)))
+	if err != nil {
+		return -1
+	}
+	return pid
+}
+
 // SpawnCount is how many lines a --spawn-log holds: how many times the relay
 // spawned the stand-in. Zero when the file does not exist, which is what a
 // relay that spawned nothing leaves behind -- output_support.py:111's
```


### Appendix F — `relay/internal/relaytest/asset.go` and `asset_test.go`

`PacketPID` reads the field `SyntheticTS` writes and `--ts-pid` rewrites. Its pin asserts both bytes of a 13-bit value and `rewritePID`'s carry, because 8192-byte reads do not land on 188-byte boundaries.


**`relay/internal/relaytest/asset.go`**

```diff
--- a/internal/relaytest/asset.go
+++ b/internal/relaytest/asset.go
@@ -77,6 +77,15 @@
 	return out
 }
 
+// PacketPID reads back the 13-bit PID from one packet's second and third
+// bytes -- the field SyntheticTS writes and the one --ts-pid rewrites.
+func PacketPID(packet []byte) int {
+	if len(packet) < 3 {
+		panic(fmt.Sprintf("relaytest: a packet is %d bytes, got %d", PacketSize, len(packet)))
+	}
+	return int(packet[1]&0x1F)<<8 | int(packet[2])
+}
+
 // PacketIndex reads back the index SyntheticTS embedded in one packet.
 func PacketIndex(packet []byte) int {
 	if len(packet) < 8 {
```


**`relay/internal/relaytest/asset_test.go`**

```diff
--- a/internal/relaytest/asset_test.go
+++ b/internal/relaytest/asset_test.go
@@ -81,3 +81,49 @@
 		t.Errorf("WriteChunk = %d, want 9400 (apps/proxy/live_proxy/tests/harness/upstream.py:31)", WriteChunk)
 	}
 }
+
+// THE PID ROUND-TRIPS, and the rewrite the stand-in performs is visible
+// through it. PacketPID and --ts-pid are the mechanism the Output Profile
+// tests use to tell a transcode's output from its input (2c-7), so the two
+// halves are pinned against each other here rather than only inside the tests
+// that depend on them.
+func TestPacketPIDReadsBackWhatSyntheticTSWroteAndWhatRewritePIDSets(t *testing.T) {
+	asset := SyntheticTS(4, 0x100)
+	for offset := 0; offset < len(asset); offset += PacketSize {
+		if got := PacketPID(asset[offset : offset+PacketSize]); got != 0x100 {
+			t.Fatalf("packet at %d carries PID %#x, want the 0x100 SyntheticTS wrote", offset, got)
+		}
+	}
+
+	// A VALUE THAT EXERCISES BOTH BYTES: 0x1FF needs the low five bits of
+	// byte 1 as well as the whole of byte 2, so a rewrite that touched only
+	// one of them would fail here and pass for any PID under 0x100.
+	whole, rest := rewritePID(append([]byte(nil), asset...), 0x1FF)
+	if len(rest) != 0 {
+		t.Fatalf("a whole number of packets left %d bytes over", len(rest))
+	}
+	for offset := 0; offset < len(whole); offset += PacketSize {
+		packet := whole[offset : offset+PacketSize]
+		if got := PacketPID(packet); got != 0x1FF {
+			t.Fatalf("packet at %d carries PID %#x after the rewrite, want 0x1FF", offset, got)
+		}
+		if packet[0] != SyncByte {
+			t.Fatalf("the rewrite broke the sync byte at %d", offset)
+		}
+		if got := PacketIndex(packet); got != offset/PacketSize {
+			t.Fatalf("the rewrite moved packet %d's embedded index to %d", offset/PacketSize, got)
+		}
+	}
+
+	// A PARTIAL TRAILING PACKET IS CARRIED, NOT REWRITTEN: 8192-byte reads do
+	// not land on 188-byte boundaries, and a rewrite that assumed they did
+	// would corrupt every packet after the first short read.
+	partial := append([]byte(nil), asset[:PacketSize+7]...)
+	done, carry := rewritePID(partial, 0x1FF)
+	if len(done) != PacketSize {
+		t.Fatalf("rewritePID returned %d whole bytes, want one packet", len(done))
+	}
+	if len(carry) != 7 {
+		t.Fatalf("rewritePID carried %d bytes, want the 7 that are not yet a packet", len(carry))
+	}
+}
```


### Appendix G — `relay/output/fmp4.go`

Five additive edits and two doc paragraphs. **Nothing is moved and nothing is renamed** (Ruling R1). `Pipeline` gains the second sink; `generation`'s bitstream-filter scan gains a guard.

**`relay/output/fmp4.go`**

```diff
--- a/output/fmp4.go
+++ b/output/fmp4.go
@@ -19,6 +19,13 @@
 // Config.Command/Config.Argv and Channel.AttachOutput's format key are those
 // three seams; what 2c-7 adds is a second Pipeline constructor and a second
 // sink type, not a change to the lifecycle, the refcount or the spawn.
+//
+// 2c-7 DID EXACTLY THAT, and this file's name is now narrower than its
+// contents: Pipeline, its supervisor, its writer and its stop are shared by
+// both processes and live here, while profile.go holds only what the Output
+// Profile adds. The file is NOT split, deliberately -- a move shows in a diff
+// as a whole delete and a whole add, and every line of 2c-6's reviewed prose
+// would re-enter review to buy a better file name (the 2c-7 plan's Ruling R1).
 package output
 
 import (
@@ -104,6 +111,9 @@
 	MaxInitSegmentBytes = 10 * 1024 * 1024
 
 	// readSize is manager.py:294's 65536: the read off the remux's fd 1.
+	// output/profile/manager.py:231 is the same literal for the Output
+	// Profile transcode, so both processes read in the same unit and one
+	// constant carries both citations (2c-7).
 	readSize = 65536
 
 	// stopJoinWait is manager.py:168's `t.join(timeout=5)`: how long a stop
@@ -336,11 +346,49 @@
 	cfg   Config
 	log   *slog.Logger
 	frags *buffer.Fragments
+
+	// ring is the SECOND SINK, 2c-7's: an Output Profile transcode writes
+	// MPEG-TS into a buffer.Ring where the remux writes MP4 boxes into
+	// frags. Exactly one of the two is non-nil for the life of a pipeline,
+	// set by the constructor and never changed, so the three branches that
+	// read it need no lock.
+	ring *buffer.Ring
 
+	// bsf is whether this pipeline's stderr is watched for the
+	// aac_adtstoasc refusal and restarted without the filter. TRUE ONLY FOR
+	// THE REMUX: an Output Profile's argv is the operator's, and Python's
+	// OutputProfileManager never scans its stderr for anything
+	// (output/profile/manager.py:270-295), so a profile that happened to
+	// carry `-bsf:a aac_adtstoasc` must not be restarted here when Python
+	// would leave it dead.
+	bsf bool
+
 	cancel context.CancelFunc
 	done   chan struct{}
+}
+
+// closeSink shuts whichever buffer this pipeline writes, which is what wakes a
+// client waiting on it and ends every read loop.
+func (p *Pipeline) closeSink() {
+	if p.ring != nil {
+		p.ring.Close()
+		return
+	}
+	p.frags.Close()
 }
 
+// read is one generation's fd 1 into this pipeline's sink.
+//
+// Only the fMP4 reader can fail -- ErrNoInitSegment, the 10 MB abort -- so the
+// transcode arm reports nothing and this returns nil for it.
+func (p *Pipeline) read(proc *ffmpeg.Process) error {
+	if p.ring != nil {
+		p.profileReader(proc)
+		return nil
+	}
+	return p.reader(proc)
+}
+
 // Start spawns the remux and returns once its process is running. The pipeline
 // then runs until Stop is called or ctx is done; Done is closed once its
 // process has been reaped and its buffer is shut.
@@ -377,6 +425,7 @@
 			Retention:   cfg.Retention,
 			Now:         cfg.Now,
 		}),
+		bsf:    true,
 		cancel: cancel,
 		done:   make(chan struct{}),
 	}
@@ -384,9 +433,14 @@
 	return p, nil
 }
 
-// Fragments is the buffer clients read.
+// Fragments is the buffer an fMP4 client reads. Nil for an Output Profile
+// transcode, whose sink is Ring.
 func (p *Pipeline) Fragments() *buffer.Fragments { return p.frags }
 
+// Ring is the buffer an Output Profile transcode writes and its clients read.
+// Nil for the fMP4 remux, whose sink is Fragments.
+func (p *Pipeline) Ring() *buffer.Ring { return p.ring }
+
 // Done is closed once the pipeline's process has ended and its buffer is shut.
 func (p *Pipeline) Done() <-chan struct{} { return p.done }
 
@@ -428,7 +482,7 @@
 	// The buffer closes with the pipeline, which is what wakes a client
 	// waiting for an init segment that will now never arrive and what ends a
 	// client's read loop.
-	defer p.frags.Close()
+	defer p.closeSink()
 
 	for generation := 0; ; generation++ {
 		bsf, err := p.generation(ctx, proc)
@@ -478,7 +532,7 @@
 			// (manager.py:372), the same divergence 2c-4's Ruling R8 records
 			// for the input side.
 			p.log.Warn("remux stderr", "line", redact.Line(line))
-			if strings.Contains(line, bsfErrorFilter) && strings.Contains(line, bsfErrorPhrase) {
+			if p.bsf && strings.Contains(line, bsfErrorFilter) && strings.Contains(line, bsfErrorPhrase) {
 				wantRetry = true
 				// manager.py:374-378 starts a thread that kills the process
 				// (:387-389). Kill is that SIGKILL to the whole group; cancel
@@ -499,7 +553,7 @@
 	var readErr error
 	go func() {
 		defer close(readerDone)
-		readErr = p.reader(proc)
+		readErr = p.read(proc)
 	}()
 
 	select {
```


### Appendix H — `relay/output/profile.go`

The Output Profile transcode. Its own config type, for Ruling R3's reason; `cfg.Remux` filled from the profile's own command line so an unreachable retry could never spawn the fMP4 remux; `profileReader` returning nothing because it has nothing to report.

**`relay/output/profile.go`**

```go
package output

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strconv"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The Output Profile transcode: the port of
// apps/proxy/live_proxy/output/profile/manager.py.
//
// ONE PROCESS PER (channel, profile) PAIR, shared by every client on that
// profile -- parity-matrix row 11, "ten AC3 clients cost one ffmpeg". It reads
// the channel's own TS ring on fd 0 and writes MPEG-TS on fd 1 into a SECOND
// buffer.Ring, which is then what its clients read instead of the channel's.
// Everything about starting it, feeding it, supervising it and stopping it is
// Pipeline's, unchanged from 2c-6; what this file adds is the sink, the
// command line's source and the registry key.

// FormatMPEGTS is the output-format key a plain TS client tunes under, and the
// value channel_status.py:567 records for it. Named here rather than imported
// from httpapi because ProfileKey below composes it.
const FormatMPEGTS = "mpegts"

// ProfileKey is the registry key an Output Profile transcode runs under:
// `mpegts:p<id>`, which is EXACTLY the Redis format namespace
// OutputProfileManager builds for itself (output/profile/manager.py:303, :315,
// :325, :332, :349, :364 -- SIX sites, all the literal
// f"mpegts:p{self.profile_id}". A seventh line, :361, carries the same text in
// a docstring and is not a site).
//
// ALWAYS mpegts, WHATEVER THE CLIENT'S OUTPUT FORMAT, and that is Python's
// shape rather than a simplification: the transcode's own output is MPEG-TS
// (an OutputProfile reads raw TS on pipe:0 and writes to pipe:1,
// core/models.py:173-174), so an fMP4 client on a profile gets TWO processes
// chained -- this one under `mpegts:p3`, and the remux under `fmp4:p3` reading
// this one's ring. views.py:765-792 spells that chain out: ensure_output_profile
// first, get_buffer(profile=) second, ensure_output_format(f"fmp4:p{id}",
// source_buffer=that) third.
func ProfileKey(profileID int) string {
	return FormatKey(FormatMPEGTS, &profileID)
}

// FormatKey composes an output registry key from a format and an optional
// profile id: views.py:731-734's `f'{fmt}:p{id}' if profile else fmt`, and the
// inverse of server.py:1367-1382's _parse_output_key. A nil or zero id is the
// bare format.
func FormatKey(format string, profileID *int) string {
	if profileID == nil {
		return format
	}
	return format + ":p" + strconv.Itoa(*profileID)
}

// ErrProfileCommandAbsent is a profile whose built command line is empty or
// whose argv[0] is blank.
//
// Python reaches the same failure one step later and reports it the same way:
// posix_spawn_proc([""]) raises, OutputProfileManager.start returns False
// (manager.py:89-95), ensure_output_profile returns False, and views.py:767-772
// answers 500. Named here so the log says which of the two 500s this is.
var ErrProfileCommandAbsent = errors.New("output: the Output Profile has no command to spawn")

// ProfileConfig is what StartProfile needs.
//
// DELIBERATELY NOT Config, and not Config.Remux either. Remux's zero value
// means "the production fMP4 remux" (Config.command() falls back to
// RemuxCommand and Config.argv() to RemuxArgv), which is exactly the wrong
// default here: an Output Profile with no command must fail the tune, not
// quietly become a remux. 2c-6's Ruling R1 named Remux as the seam 2c-7 would
// reach through; reading its zero-value semantics is what changed that (the
// 2c-7 plan's Ruling R3).
type ProfileConfig struct {
	// ChannelID and ProfileID identify the pair, for logs.
	ChannelID string
	ProfileID int

	// Source is the channel's TS ring: the transcode's fd 0.
	Source *buffer.Ring

	// Command and Argv are core/models.py:200-203's build_command() split at
	// element 0 -- the command, then its arguments. Off the wire, never
	// built here: spec Amendment A4.1, and the relay carries no word
	// splitter.
	Command string
	Argv    []string

	// JoinBehind is how far behind live the writer starts reading the
	// source. manager.py:180-184 positions it with new_client_behind_seconds,
	// exactly as the fMP4 remux's writer is positioned.
	JoinBehind time.Duration

	// Retention, ChunkBytes and BudgetBytes bound the output ring, from the
	// channel's own Tuning and budget -- the same numbers the channel's ring
	// is built from, because Python builds the profile's StreamBuffer from
	// the same Config (manager.py:301-310, a plain StreamBuffer).
	Retention   time.Duration
	ChunkBytes  int
	BudgetBytes int

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger

	// Now is the output ring's clock. Nil means time.Now.
	Now func() time.Time
}

// StartProfile spawns the Output Profile transcode and returns once its
// process is running.
//
// SYNCHRONOUS FOR THE SAME REASON Start is (2c-6's Ruling R4):
// ensure_output_profile calls OutputProfileManager.start() inline
// (server.py:1532) before views.py builds the StreamingHttpResponse, so a
// spawn that fails reaches views.py:767-772 and the client gets a 500 with a
// body. A wholly asynchronous start would make that failure a 200 with an
// empty body instead.
func StartProfile(ctx context.Context, cfg ProfileConfig) (*Pipeline, error) {
	log := cfg.Log
	if log == nil {
		log = slog.Default()
	}
	key := ProfileKey(cfg.ProfileID)
	log = log.With("channel", cfg.ChannelID, "format", key)

	if cfg.Command == "" {
		return nil, ErrProfileCommandAbsent
	}

	ctx, cancel := context.WithCancel(ctx)
	proc, err := ffmpeg.StartPiped(ctx, cfg.Command, cfg.Argv)
	if err != nil {
		cancel()
		return nil, fmt.Errorf("output: starting the Output Profile transcode: %w", redact.Error(err))
	}
	p := &Pipeline{
		// THE COMMAND FIELDS ARE FILLED IN even though nothing restarts this
		// pipeline: `bsf` is false, so run's retry arm is unreachable. Left
		// EMPTY, as a first draft had them, Config.command() would fall back
		// to RemuxCommand and Config.argv() to RemuxArgv -- so if that arm
		// ever did become reachable it would spawn the fMP4 REMUX in place of
		// the operator's transcode. Found by the break-check that set `bsf`
		// to true: the spawn count stayed at 1 because the second process was
		// a real ffmpeg and not the stand-in. Two guards, and the structural
		// one is this.
		cfg: Config{
			ChannelID:  cfg.ChannelID,
			Source:     cfg.Source,
			JoinBehind: cfg.JoinBehind,
			Remux:      Remux{Command: cfg.Command, Argv: cfg.Argv, ArgvNoBSF: cfg.Argv},
		},
		log: log,
		ring: buffer.New(buffer.Config{
			BudgetBytes: cfg.BudgetBytes,
			Retention:   cfg.Retention,
			ChunkBytes:  cfg.ChunkBytes,
			Now:         cfg.Now,
		}),
		bsf:    false,
		cancel: cancel,
		done:   make(chan struct{}),
	}
	go p.run(ctx, proc)
	return p, nil
}

// profileReader is _reader_loop (output/profile/manager.py:229-268): fd 1
// straight into the output ring, which packetises and realigns it exactly as
// StreamBuffer.add_chunk does for the channel's own input.
//
// NO SCANNER AND NO INIT SEGMENT. The remux's reader has to split MP4 boxes
// because a player needs the moov before any fragment; a transcode's output is
// MPEG-TS and the ring's own 188-byte realignment is the whole of the
// structure it has.
//
// IT RETURNS NOTHING, unlike reader, which has the 10 MB no-init-segment abort
// to report. Both of this loop's exits are ordinary: EOF on fd 1 is how every
// stopped process ends, and a closed output ring is this pipeline's own stop.
// A signature carrying an `error` it could only ever fill with nil would be a
// lie, and nilerr says so.
func (p *Pipeline) profileReader(proc *ffmpeg.Process) {
	buf := make([]byte, readSize)
	stdout := proc.Stdout()
	for {
		n, readErr := stdout.Read(buf)
		if n > 0 {
			if _, writeErr := p.ring.Write(buf[:n]); writeErr != nil {
				// buffer.ErrClosed, the only error Ring.Write returns: the
				// ring shut under us, which only this pipeline's own stop
				// does.
				break
			}
		}
		if readErr != nil {
			break
		}
	}
}
```


### Appendix I — `relay/output/profile_test.go`

Six tests. Read `standInProfile`'s `JoinBehind` comment before shortening it (Constraint 17), and `TestAProfileWithNoCommand…`'s `errors.Is` comment before turning it back into a substring (Constraint 42).

**`relay/output/profile_test.go`**

```go
package output

import (
	"context"
	"errors"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// transcodePID is the PID the stand-in rewrites every packet to, and assetPID
// is the one sourceRing's asset carries. The rewrite is what makes "this came
// out of the transcode" observable: a pass-through stand-in copies its input,
// so without it the transcode's ring and the channel's hold the same bytes and
// nothing can tell them apart (a fixture that patches away its subject).
const (
	transcodePID = 0x1FF
	assetPID     = 0x100
)

// standInProfile is a ProfileConfig whose command is this test binary acting
// as a pass-through: `-i pipe:0` makes RunStandIn copy fd 0 to fd 1, which is
// structurally what an Output Profile does (raw TS in, TS out).
func standInProfile(t *testing.T, source *buffer.Ring, args ...string) ProfileConfig {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(
		append(args, "--ts-pid", strconv.Itoa(transcodePID), "-i", "pipe:0")...)
	return ProfileConfig{
		ChannelID: "c-profile",
		ProfileID: 3,
		Source:    source,
		Command:   command,
		Argv:      argv,
		// A JOIN WINDOW WIDER THAN THE FIXTURE, so the writer starts at the
		// ring's OLDEST chunk rather than at its head. With JoinBehind zero
		// the writer starts at the live head, which on a ring nothing is
		// still filling means it feeds the child nothing at all -- correct
		// behaviour, and a fixture that never produces a byte. The
		// production value is new_client_behind_seconds, which
		// output/profile/manager.py:180-184 reads for exactly this reason:
		// "so the buffer is pre-populated by the time the first client
		// connects".
		JoinBehind:  time.Minute,
		Retention:   time.Minute,
		ChunkBytes:  buffer.TSPacketSize * 16,
		BudgetBytes: buffer.ChunkBytes * 8,
	}
}

// THE REGISTRY KEY IS `mpegts:p<id>` WHATEVER THE CLIENT'S FORMAT, and the
// expected values are read off the Python lines rather than computed here.
//
// Two sources, deliberately: views.py:731-734 composes the key a CLIENT's
// format resolves to (`f'{fmt}:p{id}'`), and output/profile/manager.py builds
// the transcode's own namespace as the literal f"mpegts:p{self.profile_id}" at
// six sites regardless of that format. ProfileKey is the second; FormatKey is
// the first.
func TestTheProfileKeyIsMPEGTSWhateverTheClientFormat(t *testing.T) {
	if got := ProfileKey(3); got != "mpegts:p3" {
		t.Fatalf("ProfileKey(3) is %q, want output/profile/manager.py:303's mpegts:p3", got)
	}
	three := 3
	for _, tc := range []struct {
		format string
		id     *int
		want   string
	}{
		// views.py:731-734, both arms.
		{"mpegts", nil, "mpegts"},
		{"fmp4", nil, "fmp4"},
		{"mpegts", &three, "mpegts:p3"},
		{"fmp4", &three, "fmp4:p3"},
	} {
		if got := FormatKey(tc.format, tc.id); got != tc.want {
			t.Errorf("FormatKey(%q, %v) is %q, want views.py:731-734's %q", tc.format, tc.id, got, tc.want)
		}
	}
}

// THE TRANSCODE'S OUTPUT IS A SECOND RING OF MPEG-TS, realigned to 188 bytes
// by the ring itself exactly as StreamBuffer.add_chunk realigns the channel's
// own input (output/profile/manager.py:256's add_chunk).
func TestAProfileTranscodeFillsItsOwnRingFromTheChannels(t *testing.T) {
	source := sourceRing(t, 2048)
	p, err := StartProfile(t.Context(), standInProfile(t, source))
	if err != nil {
		t.Fatalf("starting the transcode: %v", err)
	}
	t.Cleanup(p.Stop)

	if p.Fragments() != nil {
		t.Fatal("an Output Profile transcode built a fragment buffer; its sink is a ring")
	}
	ring := p.Ring()
	if ring == nil {
		t.Fatal("the transcode has no output ring")
	}
	if !waitFor(func() bool { return ring.Head() >= 3 }, 15*time.Second) {
		t.Fatalf("the transcode's ring holds %d chunks after fifteen seconds, want at least 3", ring.Head())
	}

	chunks, _, _ := ring.Read(0)
	if len(chunks) == 0 {
		t.Fatal("the transcode's ring returned no chunks at its oldest cursor")
	}
	for i, chunk := range chunks {
		if problem := relaytest.AlignmentProblem(chunk); problem != "" {
			t.Fatalf("chunk %d of the transcode's ring is not a transport stream: %s", i, problem)
		}
		// AND THE BYTES CAME OUT OF THE CHILD, not out of the source ring: the
		// stand-in rewrote every packet's PID, so a pipeline that had somehow
		// copied its input into its output would carry the asset's instead.
		for offset := 0; offset < len(chunk); offset += relaytest.PacketSize {
			if got := relaytest.PacketPID(chunk[offset : offset+relaytest.PacketSize]); got != transcodePID {
				t.Fatalf("a packet in the transcode's ring carries PID %#x, want the child's %#x (the asset's is %#x)",
					got, transcodePID, assetPID)
			}
		}
	}
}

// A PROFILE WITH NO COMMAND FAILS BEFORE ANYTHING IS SPAWNED, and it does NOT
// fall back to the fMP4 remux. Config.command() returns RemuxCommand for an
// empty Command, which is why ProfileConfig does not reuse Config: an operator
// whose OutputProfile row has a blank command must get a failed tune, not an
// ffmpeg remux nobody asked for (Ruling R3).
func TestAProfileWithNoCommandIsRefusedRatherThanDefaultedToTheRemux(t *testing.T) {
	cfg := standInProfile(t, sourceRing(t, 64))
	cfg.Command = ""
	p, err := StartProfile(t.Context(), cfg)
	if p != nil {
		p.Stop()
		t.Fatal("a profile with no command started a pipeline")
	}
	if err == nil {
		t.Fatal("a profile with no command started without an error")
	}
	// errors.Is, NOT a substring. An earlier draft asserted
	// strings.Contains(err, "no command") and stayed GREEN with the guard
	// removed, because os/exec's own message for an empty Path is literally
	// "exec: no command" -- two sources for one string, which is hollow
	// shape 5, found by the break-check that was supposed to redden it.
	if !errors.Is(err, ErrProfileCommandAbsent) {
		t.Fatalf("the error is %q, want ErrProfileCommandAbsent", err)
	}
}

// THE BITSTREAM-FILTER RETRY IS THE REMUX'S ALONE. Python's
// OutputProfileManager._stderr_loop (output/profile/manager.py:270-295) logs
// every line and looks at none of them, where FMP4RemuxManager's watches for
// the aac_adtstoasc refusal and restarts without the filter
// (output/fmp4/manager.py:373-378). An operator whose Output Profile
// parameters happen to carry `-bsf:a aac_adtstoasc` therefore gets ONE dead
// process in Python, and must get one here.
//
// COUNTED IN SPAWNS, because a retry is a second spawn and nothing else in the
// pipeline's observable state distinguishes it from a process that simply
// ended. The remux's own retry is pinned the other way by
// TestTheRetryIsNotRepeatedWhenItAlsoReportsTheBitstreamFilterError, so this
// pair asserts both directions of the same switch.
func TestAProfileStderrIsNotWatchedForTheBitstreamFilterError(t *testing.T) {
	log := filepath.Join(t.TempDir(), "profile-spawns.log")
	cfg := standInProfile(t, sourceRing(t, 256), "--spawn-log", log, "--fmp4-bsf-error", "--fmp4-exit")
	p, err := StartProfile(t.Context(), cfg)
	if err != nil {
		t.Fatalf("starting the transcode: %v", err)
	}
	t.Cleanup(p.Stop)

	// THE WAIT IS NOT AN ASSERTION, and the order matters. A pipeline that
	// retried is still running when its first process has gone, so a Fatal
	// here would report "still running" where the mechanism under test is the
	// SPAWN. Fall through on the timeout so the count below names it -- the
	// break-check that patched `bsf` to true reddened on "still running"
	// before this was reordered, which is a true positive for a message that
	// does not say what happened.
	select {
	case <-p.Done():
	case <-time.After(15 * time.Second):
	}
	if got := relaytest.SpawnCount(log); got != 1 {
		t.Fatalf("the relay spawned %d transcodes for one Output Profile whose stderr named the bitstream filter, want 1: "+
			"the retry is the fMP4 remux's and output/profile/manager.py:270-295 has none", got)
	}
	// AND THE PIPELINE ENDED, which is the other half: a profile whose process
	// exited must not leave a supervisor waiting for a generation that will
	// never come.
	select {
	case <-p.Done():
	default:
		t.Fatal("the transcode is still running fifteen seconds after its only process exited")
	}
}

// STOPPING THE PIPELINE CLOSES ITS RING, which is what ends every client
// reading it -- the transcode's counterpart of the fragment buffer's close.
func TestStoppingAProfileTranscodeClosesItsRing(t *testing.T) {
	p, err := StartProfile(t.Context(), standInProfile(t, sourceRing(t, 512)))
	if err != nil {
		t.Fatalf("starting the transcode: %v", err)
	}
	ring := p.Ring()
	if !waitFor(func() bool { return ring.Head() >= 1 }, 15*time.Second) {
		t.Fatal("the transcode produced nothing before the stop")
	}
	p.Stop()
	if !ring.Closed() {
		t.Fatal("the stopped transcode's ring is still open, so a client reading it would never end")
	}
}

// A CANCELLED CONTEXT ENDS THE PIPELINE, which is what Channel.stopOutputs and
// the refcount both reach it through.
func TestACancelledContextEndsTheProfileTranscode(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	p, err := StartProfile(ctx, standInProfile(t, sourceRing(t, 512)))
	if err != nil {
		t.Fatalf("starting the transcode: %v", err)
	}
	cancel()
	select {
	case <-p.Done():
	case <-time.After(15 * time.Second):
		t.Fatal("the transcode outlived its context by fifteen seconds")
	}
}
```


### Appendix J — `relay/output/profile_real_test.go`

The one real-ffmpeg test. It drives `core/migrations/0024_outputprofile.py`'s locked AC3 profile on an AAC asset and reads the codec back with ffprobe, which is what makes it a transcode claim rather than a plumbing one.

**`relay/output/profile_real_test.go`**

```go
package output

import (
	"bytes"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// seededAC3Argv is core/migrations/0024_outputprofile.py's locked
// "Media Server (AC3 Audio)" profile, exactly as build_command() would return
// it: the `command` field first, then shlex.split of `parameters`
// (core/models.py:200-203).
//
// A LITERAL READ OFF THAT MIGRATION, token for token, and NOT computed from
// anything this package holds -- an expected value the code under test
// produced cannot fail. It is also the argv a real deployment runs: the
// migration ships this row locked and active, so it is what an operator
// selecting "Media Server (AC3 Audio)" gets.
func seededAC3Argv() []string {
	return []string{
		"ffmpeg",
		"-fflags", "+discardcorrupt+genpts+nobuffer",
		"-probesize", "512K",
		"-analyzeduration", "0",
		"-i", "pipe:0",
		"-map", "0",
		"-c:v", "copy",
		"-c:a", "ac3",
		"-b:a", "384k",
		"-max_muxing_queue_size", "4096",
		"-flush_packets", "1",
		"-mpegts_flags", "+pat_pmt_at_frames+resend_headers+initial_discontinuity",
		"-f", "mpegts", "pipe:1",
	}
}

// THE ONE TEST IN THIS PR THAT DRIVES A REAL TRANSCODE, on the production argv
// of a profile the migrations actually ship.
//
// WHAT IT BUYS OVER THE STAND-IN TESTS: everything else here substitutes a
// pass-through for the child, because the subject is the relay's reaction to a
// process. This one's subject is the bytes a real ffmpeg produces from the
// relay's own fd 0 and fd 1 wiring -- that `-i pipe:0 ... -f mpegts pipe:1`
// really works when its input is the channel's ring and its output is a
// buffer.Ring, that the result is still a transport stream the ring can
// packetise, and that the audio really was re-encoded.
//
// AAC IN, AC3 OUT, which is what makes the last assertion able to fail: the
// asset is built with AAC audio and the profile asks for AC3, so a relay that
// had somehow copied its input to its output would produce a stream whose
// audio codec is still AAC. ffprobe reads the codec back -- an independent
// tool, not this package.
func TestARealAC3ProfileTranscodesTheChannelsRing(t *testing.T) {
	ffmpegPath := requireFFmpeg(t)
	asset := buildFragmentableAsset(t, ffmpegPath)

	source := buffer.New(buffer.Config{
		BudgetBytes: len(asset) * 2,
		ChunkBytes:  buffer.TSPacketSize * 64,
	})
	if _, err := source.Write(asset); err != nil {
		t.Fatalf("filling the source ring: %v", err)
	}

	argv := seededAC3Argv()
	p, err := StartProfile(t.Context(), ProfileConfig{
		ChannelID:   "c-real-profile",
		ProfileID:   1,
		Source:      source,
		Command:     argv[0],
		Argv:        argv[1:],
		JoinBehind:  time.Minute,
		Retention:   time.Minute,
		ChunkBytes:  buffer.TSPacketSize * 64,
		BudgetBytes: len(asset) * 4,
	})
	if err != nil {
		t.Fatalf("starting the real transcode: %v", err)
	}
	t.Cleanup(p.Stop)

	out := p.Ring()
	if !waitFor(func() bool { return out.Head() >= 4 }, 30*time.Second) {
		t.Fatalf("the real transcode produced %d chunks in thirty seconds, want at least 4", out.Head())
	}

	var produced []byte
	chunks, _, _ := out.Read(0)
	for _, chunk := range chunks {
		produced = append(produced, chunk...)
	}
	if problem := relaytest.AlignmentProblem(produced); problem != "" {
		t.Fatalf("what the real transcode produced is not a transport stream: %s", problem)
	}
	if bytes.HasPrefix(asset, produced) {
		t.Fatal("the transcode's output is a prefix of its input: nothing was re-encoded")
	}

	// THE AUDIO CODEC, READ BACK BY ffprobe. The assertion that makes this a
	// transcode test rather than a plumbing test, and the one thing no
	// stand-in can produce.
	probe, err := exec.LookPath("ffprobe")
	if err != nil {
		t.Skip("ffprobe is not on PATH; the codec half of this test did NOT run")
	}
	cmd := exec.CommandContext(t.Context(), probe, // #nosec G204 -- a LookPath result and fixed arguments
		"-hide_banner", "-loglevel", "error",
		"-select_streams", "a:0", "-show_entries", "stream=codec_name",
		"-of", "default=nw=1:nk=1", "-f", "mpegts", "pipe:0")
	cmd.Stdin = bytes.NewReader(produced)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	codec, err := cmd.Output()
	if err != nil {
		t.Fatalf("ffprobe could not read the transcode's output: %v: %s", err, stderr.String())
	}
	// THE FIRST LINE ONLY. `-mpegts_flags +resend_headers` makes the muxer
	// repeat the PAT/PMT, and ffprobe reports the audio stream once per
	// program it finds -- measured: two identical "ac3" lines from this argv
	// on ffmpeg 9.0.1. Every line is checked rather than only the first, so a
	// stream that carried ac3 AND something else would still fail.
	lines := strings.Fields(strings.TrimSpace(string(codec)))
	if len(lines) == 0 {
		t.Fatal("ffprobe reported no audio stream in the transcode's output")
	}
	for _, got := range lines {
		if got != "ac3" {
			t.Fatalf("the transcode's audio codec is %q, want ac3: the asset's is aac and "+
				"core/migrations/0024_outputprofile.py's locked profile asks for -c:a ac3", got)
		}
	}
}
```


### Appendix K — `relay/channel/output.go`

Three new types and one branch in `AttachOutput`. The refcount, the lock order, `releaseOutput` and `stopOutputs` are untouched. `OutputProfile.Command()`/`Args()` are nil-safe because break-check 5's first form panicked here.

**`relay/channel/output.go`**

```diff
--- a/channel/output.go
+++ b/channel/output.go
@@ -4,9 +4,89 @@
 	"context"
 	"sync"
 
+	"github.com/D10Scot/Dispatcharr/relay/buffer"
 	"github.com/D10Scot/Dispatcharr/relay/output"
 )
 
+// OutputProfile is one is_active OutputProfile as the control plane described
+// it: core/models.py:200-203's build_command() in full, COMMAND FIRST.
+//
+// A plain struct rather than the wire type, for Tuning's reason: this package
+// never imports the wire package, so httpapi converts once per answer.
+type OutputProfile struct {
+	// ID is the OutputProfile primary key, which is what the authorize hop
+	// puts in X-Relay-Output and what the client registry renders as
+	// output_profile_id.
+	ID int
+
+	// Argv is [command, arg...]. NIL MEANS DJANGO COULD NOT BUILD IT --
+	// shlex refused the profile's parameters -- which is a different fault
+	// from the profile being absent, and the two get different answers (the
+	// 2c-7 plan's Ruling R4).
+	Argv []string
+}
+
+// Command is the executable to spawn: argv[0], or the empty string when
+// Django could not build the list. NIL-SAFE ON PURPOSE -- an unbuildable
+// profile reaches AttachOutput with a nil Argv, and indexing it there would
+// turn a control-plane data problem into a panic in the channel package.
+func (p OutputProfile) Command() string {
+	if len(p.Argv) == 0 {
+		return ""
+	}
+	return p.Argv[0]
+}
+
+// Args is everything after the command, the way ffmpeg.StartPiped takes it.
+func (p OutputProfile) Args() []string {
+	if len(p.Argv) < 2 {
+		return []string{}
+	}
+	return p.Argv[1:]
+}
+
+// OutputProfiles is a next-source answer's whole active set.
+type OutputProfiles struct {
+	// Known reports whether the answer carried output_profiles at all. False
+	// means a control plane older than Phase 2 PR 2b-2, which is a contract
+	// mismatch rather than "no profiles are configured" -- an empty ByID with
+	// Known true is the latter.
+	Known bool
+
+	// ByID is keyed by the STRINGIFIED id, as the map arrives and as
+	// X-Relay-Output spells it.
+	ByID map[string]OutputProfile
+}
+
+// Lookup returns the profile with this id, and whether the set holds one.
+func (p OutputProfiles) Lookup(id string) (OutputProfile, bool) {
+	profile, found := p.ByID[id]
+	return profile, found
+}
+
+// OutputSpec is what varies between the output pipelines one channel can run.
+// Everything else -- the join window, the retention, the byte budget, the
+// logger -- comes off the channel, so a caller cannot give two pipelines on
+// the same channel two different memory profiles by accident.
+type OutputSpec struct {
+	// Source is the ring the process reads on fd 0. Nil means the channel's
+	// own ring. An Output Profile transcode always reads the channel's; an
+	// fMP4 remux reads the channel's when no profile is active and the
+	// PROFILE'S when one is -- views.py:773-776 resolves get_buffer(profile)
+	// first and hands it to ensure_output_format at :790-792.
+	Source *buffer.Ring
+
+	// Profile, when non-nil, makes this an Output Profile transcode: its own
+	// command line, a buffer.Ring of MPEG-TS as the sink, and no
+	// bitstream-filter retry. Nil makes it the fMP4 remux.
+	Profile *OutputProfile
+
+	// Remux is the process an fMP4 pipeline spawns. Ignored when Profile is
+	// set -- an Output Profile's command comes off the wire and must never
+	// fall back to the remux literal (the 2c-7 plan's Ruling R3).
+	Remux output.Remux
+}
+
 // outputEntry is one running output pipeline and how many clients hold it.
 type outputEntry struct {
 	pipeline *output.Pipeline
@@ -43,7 +123,7 @@
 // reaches in here. Starting a pipeline spawns a process, which is milliseconds
 // of LookPath and fork/exec -- short, but not something the status endpoints'
 // State() and Clients() should ever queue behind.
-func (c *Channel) AttachOutput(format string, remux output.Remux) (*output.Pipeline, func(), error) {
+func (c *Channel) AttachOutput(format string, spec OutputSpec) (*output.Pipeline, func(), error) {
 	c.outMu.Lock()
 	defer c.outMu.Unlock()
 
@@ -60,15 +140,43 @@
 	// same shape. What ends this pipeline is its refcount reaching zero or
 	// stopOutputs, both below, and both are reached on every path a channel or
 	// a client can end.
-	pipeline, err := output.Start(context.Background(), output.Config{
-		ChannelID:   c.id,
-		Source:      c.ring,
-		JoinBehind:  c.tuning.JoinBehind,
-		Retention:   c.tuning.Retention,
-		BudgetBytes: c.budgetBytes,
-		Remux:       remux,
-		Log:         c.log,
-	})
+	source := spec.Source
+	if source == nil {
+		source = c.ring
+	}
+	var (
+		pipeline *output.Pipeline
+		err      error
+	)
+	if spec.Profile != nil {
+		// 2c-7. The transcode's sink is a second buffer.Ring of MPEG-TS, its
+		// command line comes off the wire, and it has no bitstream-filter
+		// retry to make -- OutputProfileManager._stderr_loop
+		// (output/profile/manager.py:270-295) logs and does nothing else.
+		pipeline, err = output.StartProfile(context.Background(), output.ProfileConfig{
+			ChannelID:   c.id,
+			ProfileID:   spec.Profile.ID,
+			Source:      source,
+			Command:     spec.Profile.Command(),
+			Argv:        spec.Profile.Args(),
+			JoinBehind:  c.tuning.JoinBehind,
+			Retention:   c.tuning.Retention,
+			ChunkBytes:  c.tuning.ChunkBytes,
+			BudgetBytes: c.budgetBytes,
+			Log:         c.log,
+			Now:         c.now,
+		})
+	} else {
+		pipeline, err = output.Start(context.Background(), output.Config{
+			ChannelID:   c.id,
+			Source:      source,
+			JoinBehind:  c.tuning.JoinBehind,
+			Retention:   c.tuning.Retention,
+			BudgetBytes: c.budgetBytes,
+			Remux:       spec.Remux,
+			Log:         c.log,
+		})
+	}
 	if err != nil {
 		return nil, nil, err
 	}
```


### Appendix L — `relay/channel/channel.go`, `manager.go` and `failover.go`

One field and two methods on the channel; one field carried through `Started`; one field and three lines on the failover. There is deliberately no `setOutputProfiles` wrapper: the failover assigns the field inside the lock it already holds, and a wrapper was reported `unused`.


**`relay/channel/channel.go`**

```diff
--- a/channel/channel.go
+++ b/channel/channel.go
@@ -94,6 +94,11 @@
 	// Profile transcodes. Its own mutex, never nested with mu -- see
 	// output.go's lock-order note.
 	outputRegistry
+
+	// outputProfiles is the active OutputProfile set as the control plane
+	// last described it, under mu. REPLACED WHOLESALE, never mutated in
+	// place, so OutputProfiles() can hand its map out without copying it.
+	outputProfiles OutputProfiles
 	// channelName is StreamManager.channel_name: resolved once at construction
 	// (input/manager.py:41-44) and carried on every event, unchanged by a
 	// failover -- the SourceInfo's name can move, this one does not.
@@ -246,6 +251,44 @@
 	return out
 }
 
+// OutputProfiles is the active OutputProfile set from the most recent
+// next-source answer this channel received.
+//
+// PER CHANNEL, NOT PER CLIENT, and that is 2b-2's Ruling R3 rather than a
+// simplification here: next-source runs once per channel while Python resolves
+// the profile once per client (views.py:605 and :712 re-read the row), so the
+// whole active set travels on every answer and the relay serves every later
+// client from this copy. The divergence that leaves is stated in the 2c-7
+// plan's Ruling R5 and is bounded by the refresh below: a profile edited
+// between two next-source calls reaches a new client only after the next one.
+//
+// The returned map is the one the channel holds. It is never mutated in place
+// -- setOutputProfiles replaces it -- so a reader that keeps it keeps a
+// consistent snapshot.
+func (c *Channel) OutputProfiles() OutputProfiles {
+	c.mu.RLock()
+	defer c.mu.RUnlock()
+	return c.outputProfiles
+}
+
+// SetClientOutputProfile records which Output Profile this client is actually
+// being served under, once the handler has resolved it against the set above.
+//
+// A SECOND WRITE RATHER THAN A LATER FIRST ONE, because the resolution needs
+// the channel and Attach is what creates it: identify() records the id the
+// authorize hop asked for, and this corrects it to null on the one path where
+// the two differ -- a profile deactivated between the hop and the tune, which
+// Python reproduces by re-reading the row with is_active=True and getting None
+// (views.py:150-155), then registering the client with that None
+// (views.py:751).
+func (c *Channel) SetClientOutputProfile(clientID string, profileID *int) {
+	c.mu.Lock()
+	defer c.mu.Unlock()
+	if client, attached := c.clients[clientID]; attached {
+		client.OutputProfileID = profileID
+	}
+}
+
 // Source is what the next-source answer said about this channel's stream --
 // the CURRENT one, after any failover.
 func (c *Channel) Source() SourceInfo {
```


**`relay/channel/manager.go`**

```diff
--- a/channel/manager.go
+++ b/channel/manager.go
@@ -93,6 +93,11 @@
 	Tuning   Tuning
 	Info     SourceInfo
 	Resolver Resolver
+
+	// OutputProfiles is the active OutputProfile set the tune's next-source
+	// answer carried (2c-7), cached on the channel and refreshed by every
+	// later answer a failover receives.
+	OutputProfiles OutputProfiles
 }
 
 // Attach returns the channel for id, starting it from start() if it is not
@@ -253,6 +258,7 @@
 		channelName:    started.Info.ChannelName,
 		budgetBytes:    m.cfg.BudgetBytes,
 		outputRegistry: outputRegistry{outputs: map[string]*outputEntry{}},
+		outputProfiles: started.OutputProfiles,
 		startedAt:      now(),
 		now:            now,
 		resolver:       started.Resolver,
```


**`relay/channel/failover.go`**

```diff
--- a/channel/failover.go
+++ b/channel/failover.go
@@ -45,6 +45,13 @@
 	Source   Source
 	Info     SourceInfo
 	Degraded bool
+
+	// OutputProfiles is the active set the SAME next-source answer carried
+	// (2c-7). Zero -- Known false -- for a degraded resolution, which came
+	// from the candidate list cached at channel start and has no answer of
+	// its own, and the channel's existing set is then kept rather than
+	// cleared.
+	OutputProfiles OutputProfiles
 }
 
 // ErrNoAlternate is "No alternate stream available" (input/manager.py:2110).
@@ -223,6 +230,15 @@
 	c.source = resolved.Info
 	c.currentStreamID = resolved.Info.StreamID
 	c.failures.clear()
+	// The Output Profile set travels on every next-source answer, so a
+	// failover that reached Django refreshes it and a DEGRADED one -- which
+	// never called Django -- leaves the channel-start copy in place (2c-7's
+	// Ruling R5). Under the same Lock as the rest of the switch, so a client
+	// attaching mid-switch reads one state or the other and never half of
+	// each.
+	if resolved.OutputProfiles.Known {
+		c.outputProfiles = resolved.OutputProfiles
+	}
 	c.mu.Unlock()
 
 	// stream_switch (:1523-1532): the URL through redact_url and cut at 100
```


### Appendix M — `relay/httpapi/profile.go`

`views.py:765-776` in order, with Constraint 40's three wire states and their three answers. One failure branch serves both 500s, deliberately (Ruling R4's last paragraph).

**`relay/httpapi/profile.go`**

```go
package httpapi

import (
	"log/slog"
	"net/http"
	"strconv"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/output"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The Output Profile half of the stream handler: resolve the profile the
// authorize hop named against the set next-source sent, start (or join) its
// transcode, and hand back the ring the client's own output is built from.
//
// views.py:765-776, in order and for the same reasons:
//
//	if resolved_output_profile:
//	    cmd = resolved_output_profile.build_command()
//	    if not proxy_server.ensure_output_profile(channel_id, id, cmd):
//	        ... return JsonResponse({...}, status=500)
//	source_buffer = proxy_server.get_buffer(channel_id, profile=id or None)
//
// The one thing that is not in that order is WHERE the profile row comes
// from: Python re-reads it from the database per client (views.py:150-155),
// and this relay reads it off the channel's cached copy of the next-source
// answer, which is what closes that ORM read (2b-2's Ruling R3).

// profileNotStartedBody is views.py:771's JsonResponse body, character for
// character. One of the few error bodies views.py spells out in full, so a
// client that reads it cannot tell the two implementations apart.
const profileNotStartedBody = `{"error": "Failed to start output profile transcode"}`

// attachOutputProfile resolves this client's Output Profile and starts or
// joins its transcode.
//
// It returns the ring whatever serves this client should read: the profile's
// output ring when a transcode is running, and the channel's own ring when no
// profile was asked for -- or when the one asked for is no longer in the
// active set, which is Python's own answer and not a fallback invented here.
//
// THE ABSENT PROFILE IS NOT AN ERROR, and that is the single least obvious
// behaviour in this file. The authorize hop resolved the id with
// is_active=True and put it in X-Relay-Output; views.py:150-155 then re-reads
// the row with is_active=True and gets None if it was deactivated in between,
// and :725-751 registers the client with that None and serves it plain TS.
// Reproduced: the client streams, and its registry row says null.
//
// `ok` false means the response has already been written and the caller must
// return.
func attachOutputProfile(
	w http.ResponseWriter,
	ch *channel.Channel,
	client *channel.Client,
	log *slog.Logger,
) (source *buffer.Ring, release func(), ok bool) {
	noop := func() {}
	if client.OutputProfileID == nil {
		return ch.Ring(), noop, true
	}
	id := strconv.Itoa(*client.OutputProfileID)

	profiles := ch.OutputProfiles()
	if !profiles.Known {
		// A contract mismatch: 502, as an absent proxy_settings key is. Not
		// a 500, which is what a profile that exists but cannot be started
		// gets, and not a silent fall-through to plain TS, which would serve
		// a client the wrong audio codec because the relay is newer than
		// Django.
		log.Error("the control plane sent no output_profiles", "channel", ch.ID(), "client", client.ID, "output_profile", id)
		http.Error(w, "control plane contract mismatch", http.StatusBadGateway)
		return nil, nil, false
	}

	profile, found := profiles.Lookup(id)
	if !found {
		// Deactivated between the authorize hop and the tune. Python serves
		// the client with no profile at all and records null; so does this.
		log.Info("the Output Profile this tune named is no longer active, serving without one",
			"channel", ch.ID(), "client", client.ID, "output_profile", id)
		// SetClientOutputProfile IS THE WRITE, and there is deliberately no
		// second one here. An earlier draft also assigned
		// `client.OutputProfileID = nil` directly, which reads as harmless --
		// same value, same field, the struct the caller already holds -- and is
		// a DATA RACE: Attach registered this pointer in the channel's own
		// registry, so the list endpoint reads the field under RLock
		// (channel/channel.go's ClientSnapshot) while this goroutine writes it
		// under no lock at all. Caught by the review, reproduced with `-race`,
		// and pinned by TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint.
		ch.SetClientOutputProfile(client.ID, nil)
		return ch.Ring(), noop, true
	}
	// ONE FAILURE BRANCH FOR TWO FAULTS, deliberately (Global Constraint 18).
	// An argv Django could not build (`argv: null`, shlex refused the
	// profile's parameters) reaches StartProfile as an empty command and comes
	// back as ErrProfileCommandAbsent; a command that is not on disk comes
	// back as a spawn error. Python answers 500 to both -- build_command()
	// raises inside stream_ts's try (:823-827) for the first, and
	// ensure_output_profile returns False (:767-772) for the second -- so the
	// STATUS is parity either way, and only the LOG needs to tell them apart.
	//
	// The BODY is views.py:771's for both, and for the unbuildable case that
	// is a stated divergence: Python's carries shlex's own message, which
	// never crosses this wire and cannot be reproduced from anything the relay
	// holds.
	pipeline, releaseOutput, err := ch.AttachOutput(output.ProfileKey(profile.ID), channel.OutputSpec{Profile: &profile})
	if err != nil {
		log.Error("the Output Profile transcode could not be started",
			"channel", ch.ID(), "client", client.ID, "output_profile", id,
			"error", redact.Error(err))
		writeProfileFailure(w)
		return nil, nil, false
	}
	return pipeline.Ring(), releaseOutput, true
}

// writeProfileFailure writes views.py:770-772's 500.
func writeProfileFailure(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusInternalServerError)
	_, _ = w.Write([]byte(profileNotStartedBody))
}

// outputProfilesFrom converts a next-source answer's map into the wire-free
// form the channel package holds. One conversion per answer, at the one place
// the wire is read.
func outputProfilesFrom(answer *control.NextSourceAnswer) channel.OutputProfiles {
	if !answer.OutputProfilesPresent {
		return channel.OutputProfiles{}
	}
	byID := make(map[string]channel.OutputProfile, len(answer.OutputProfiles))
	for id, ref := range answer.OutputProfiles {
		byID[id] = channel.OutputProfile{ID: ref.ID, Argv: ref.Argv}
	}
	return channel.OutputProfiles{Known: true, ByID: byID}
}
```


### Appendix N — `relay/httpapi/stream.go`

Six edits. `identify` records what the hop asked for, not what the tune serves; the resolution runs after `defer release()` and before the fMP4 branch, exactly where `views.py` puts it; `serveClient` takes the ring it should read (Ruling R10).

**`relay/httpapi/stream.go`**

```diff
--- a/httpapi/stream.go
+++ b/httpapi/stream.go
@@ -9,6 +9,7 @@
 	"math/big"
 	"net"
 	"net/http"
+	"strconv"
 	"time"
 
 	"github.com/D10Scot/Dispatcharr/relay/buffer"
@@ -220,13 +221,24 @@
 		}
 		defer release()
 
+		// views.py:765-776, BEFORE the format branch and in that order: the
+		// Output Profile transcode is started (or joined) first, and the
+		// buffer everything below reads is get_buffer(channel, profile) --
+		// the profile's output ring when one is running, the channel's own
+		// when none is. 2c-7.
+		source, releaseProfile, ok := attachOutputProfile(w, ch, client, log)
+		if !ok {
+			return
+		}
+		defer releaseProfile()
+
 		// views.py:789-818's branch, at the same point: after the channel is
 		// up and the client is registered, and on the client's OWN resolved
 		// format rather than on anything about the channel -- a TS viewer and
 		// an fMP4 viewer share one channel, one upstream and one ring, and
 		// differ only from here down.
 		if client.OutputFormat == output.FormatFMP4 {
-			serveFMP4(w, r, deps, ch, client, log)
+			serveFMP4(w, r, deps, ch, client, source, log)
 			return
 		}
 
@@ -238,7 +250,7 @@
 			return
 		}
 
-		serveClient(r.Context(), w, rc, ch, client, log)
+		serveClient(r.Context(), w, rc, ch, source, client, log)
 	}
 }
 
@@ -249,9 +261,12 @@
 // relay that logged "fmp4" in its registry and then wrote MPEG-TS would be
 // wrong in a way nothing on the wire says, and serving it under the label
 // "mpegts" would be a lie in the payload /proxy/stats/ renders. 2c-6 brought
-// fMP4, so Format now only ever names a format NEITHER implementation has;
-// 2c-7 brings the Output Profiles, and ProfileID is still every tune that
-// asks for one.
+// fMP4 and 2c-7 the Output Profiles, so this now only ever names a format
+// NEITHER implementation has -- `hls`, whose Python manager does not exist
+// either (_OUTPUT_FORMAT_MANAGERS registers only fmp4, server.py:1352-1353).
+// ProfileID is kept on the struct and is never set: it is what the 501's log
+// line named for two stages and removing it would silently narrow the
+// message.
 type ErrUnsupportedOutput struct {
 	Format    string
 	ProfileID string
@@ -261,7 +276,7 @@
 	if e.ProfileID != "" {
 		return fmt.Sprintf("the Go relay serves no Output Profile yet, and this tune asked for %q", e.ProfileID)
 	}
-	return fmt.Sprintf("the Go relay serves only %q, not %q", OutputFormatMPEGTS, e.Format)
+	return fmt.Sprintf("the Go relay serves only %q and %q, not %q", OutputFormatMPEGTS, output.FormatFMP4, e.Format)
 }
 
 // identify resolves which channel this request is for and who is asking.
@@ -291,10 +306,25 @@
 		id = r.PathValue("channelID")
 	}
 
-	// Refused before anything is registered or attached, so a tune this relay
-	// cannot serve never reaches the control plane.
+	// 2c-7: X-Relay-Output is SERVED rather than refused. Its value is the
+	// OutputProfile primary key apps/proxy/authorize.py:483-488 resolved, and
+	// apps/proxy/authorize_views.py:154-162 has already rejected anything but
+	// "" or a digit string with a 403 -- so a non-digit here means the
+	// internal contract is broken and never reaches a deployment through
+	// nginx. Refused with a 400 rather than guessed at: there is no Python
+	// counterpart to reproduce, because Python's hop denies it a hop earlier.
+	//
+	// WHAT IS RECORDED HERE IS WHAT THE HOP ASKED FOR, not what the tune ends
+	// up serving. The set that resolves it is the channel's, and the channel
+	// does not exist yet; attachOutputProfile corrects this to null on the
+	// one path where the two differ.
+	var outputProfileID *int
 	if profileID := header("X-Relay-Output"); profileID != "" {
-		return id, nil, &ErrUnsupportedOutput{ProfileID: profileID}
+		parsed, convErr := strconv.Atoi(profileID)
+		if convErr != nil || parsed <= 0 {
+			return id, nil, &ErrOutputProfileMalformed{Value: profileID}
+		}
+		outputProfileID = &parsed
 	}
 	// 2c-6: fmp4 joins mpegts. Anything else is still refused rather than
 	// served under a label that is not true -- and there is no third format to
@@ -333,13 +363,25 @@
 	}
 
 	return id, &channel.Client{
-		ID:           clientID,
-		UserID:       userID,
-		IPAddress:    ip,
-		UserAgent:    userAgent,
-		OutputFormat: outputFormat,
-		ConnectedAt:  now(),
+		ID:              clientID,
+		UserID:          userID,
+		IPAddress:       ip,
+		UserAgent:       userAgent,
+		OutputFormat:    outputFormat,
+		OutputProfileID: outputProfileID,
+		ConnectedAt:     now(),
 	}, nil
+}
+
+// ErrOutputProfileMalformed is an X-Relay-Output that is not a positive
+// integer on a trusted request. Unreachable through nginx -- the authorize
+// hop answers 403 for it (apps/proxy/authorize_views.py:154-162) -- and
+// answered 400 rather than 403 here because it is this relay saying the
+// header it was handed is not a profile id, not an authorization decision.
+type ErrOutputProfileMalformed struct{ Value string }
+
+func (e *ErrOutputProfileMalformed) Error() string {
+	return fmt.Sprintf("X-Relay-Output is %q, which is not an Output Profile id", e.Value)
 }
 
 // mintClientID is apps/proxy/authorize.py:145-147's mint_client_id, spelled the
@@ -523,9 +565,10 @@
 	}
 
 	return channel.Started{
-		Source: source,
-		Tuning: tuning,
-		Info:   infoFrom(answer.Source),
+		Source:         source,
+		Tuning:         tuning,
+		Info:           infoFrom(answer.Source),
+		OutputProfiles: outputProfilesFrom(answer),
 		Resolver: &resolver{
 			control:    client,
 			id:         id,
@@ -621,6 +664,7 @@
 	var argvAbsent *ErrProfileArgvAbsent
 	var unbuildable *ErrProfileUnbuildable
 	var unsupported *ErrUnsupportedOutput
+	var malformedProfile *ErrOutputProfileMalformed
 	var refused *control.Refused
 	var unavailable *control.Unavailable
 	var misconfigured *control.ErrNotConfigured
@@ -651,6 +695,11 @@
 		log.Warn("refusing a tune for an unsupported output",
 			"channel", id, "format", unsupported.Format, "output_profile", unsupported.ProfileID)
 		http.Error(w, "this output is not served yet", http.StatusNotImplemented)
+	case errors.As(err, &malformedProfile):
+		// The value is NOT echoed: an internal header this relay was handed
+		// is not something to reflect into a response body.
+		log.Error("X-Relay-Output is not an Output Profile id", "channel", id)
+		http.Error(w, "malformed output profile", http.StatusBadRequest)
 	case errors.Is(err, channel.ErrDuplicateClient):
 		// views.py:748-753's 503: a client id already attached to this channel
 		// is a client that never released, not a new viewer.
@@ -733,11 +782,11 @@
 	w http.ResponseWriter,
 	rc *http.ResponseController,
 	ch *channel.Channel,
+	ring *buffer.Ring,
 	client *channel.Client,
 	log *slog.Logger,
 ) {
 	tuning := ch.Tuning()
-	ring := ch.Ring()
 
 	// POSITIONED ONCE, at setup, exactly as output/ts/generator.py:264-302
 	// positions a client -- and this is the call parity-matrix row 8 is
```


### Appendix O — `relay/httpapi/fmp4.go` and `failover.go`

The remux's key gains the profile and its source becomes the profile's ring (Ruling R9); the resolver carries the answer's profiles and a degraded resolution carries none (Ruling R5).


**`relay/httpapi/fmp4.go`**

```diff
--- a/httpapi/fmp4.go
+++ b/httpapi/fmp4.go
@@ -34,9 +34,18 @@
 	deps StreamDeps,
 	ch *channel.Channel,
 	client *channel.Client,
+	source *buffer.Ring,
 	log *slog.Logger,
 ) {
-	pipeline, releaseOutput, err := ch.AttachOutput(output.FormatFMP4, deps.Remux)
+	// THE KEY CARRIES THE PROFILE AND THE SOURCE IS THE PROFILE'S RING, both
+	// 2c-7's and both straight off views.py: :731-734 composes the format key
+	// as f'{fmt}:p{id}' when a profile is active, and :790-792 hands
+	// ensure_output_format the profile's buffer as the remux's input. So an
+	// fMP4 client on an Output Profile runs TWO chained processes -- the
+	// transcode under `mpegts:p3` writing a TS ring, and this remux under
+	// `fmp4:p3` reading it -- and an fMP4 client with no profile runs one.
+	key := output.FormatKey(output.FormatFMP4, client.OutputProfileID)
+	pipeline, releaseOutput, err := ch.AttachOutput(key, channel.OutputSpec{Remux: deps.Remux, Source: source})
 	if err != nil {
 		// views.py:789-798's JsonResponse({"error": ...}, status=500), body and
 		// all: a relay that answered a bare 500 here would be distinguishable
```


**`relay/httpapi/failover.go`**

```diff
--- a/httpapi/failover.go
+++ b/httpapi/failover.go
@@ -60,14 +60,16 @@
 		if answer.Source == nil {
 			return channel.Resolved{}, channel.ErrNoAlternate
 		}
-		return r.resolved(answer.Source, false)
+		return r.resolved(answer.Source, false, outputProfilesFrom(answer))
 	case isUnavailable(err):
 		r.log.Warn("control plane unreachable during failover; using the cached candidate list unenforced", "channel", r.id)
 		candidate := r.pickCached(req)
 		if candidate == nil {
 			return channel.Resolved{}, channel.ErrNoAlternate
 		}
-		return r.resolved(candidate, true)
+		// The cached list carries no answer of its own, so the channel keeps
+		// the Output Profile set it already had (2c-7's Ruling R5).
+		return r.resolved(candidate, true, channel.OutputProfiles{})
 	default:
 		// A Refused, or a misconfigured address: never degrade.
 		return channel.Resolved{}, err
@@ -107,10 +109,15 @@
 // candidate: reported as the switch's failure, never retried as a
 // connection failure, because no retry against the same profile can change
 // what Django could not split.
-func (r *resolver) resolved(candidate *control.Source, degraded bool) (channel.Resolved, error) {
+func (r *resolver) resolved(candidate *control.Source, degraded bool, profiles channel.OutputProfiles) (channel.Resolved, error) {
 	source, err := r.build.source(candidate)
 	if err != nil {
 		return channel.Resolved{}, err
 	}
-	return channel.Resolved{Source: source, Info: infoFrom(candidate), Degraded: degraded}, nil
+	return channel.Resolved{
+		Source:         source,
+		Info:           infoFrom(candidate),
+		Degraded:       degraded,
+		OutputProfiles: profiles,
+	}, nil
 }
```


### Appendix P — `relay/httpapi/profile_test.go`

Ten tests, including parity-matrix row 11. Read `transcodePID`'s comment first: without the PID rewrite three of these cannot fail.

**`relay/httpapi/profile_test.go`**

```go
package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"path/filepath"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/output"
)

// transcodePID is the PID the stand-in transcode rewrites every packet to.
//
// IT IS WHAT MAKES "THE CLIENT READ THE TRANSCODE'S RING" OBSERVABLE. A
// pass-through stand-in copies its input, so a profile client's bytes and a
// plain client's bytes are identical and no assertion on them can fail --
// a fixture that patches away its own subject. Rewriting the PID keeps the
// output a valid, same-length transport stream and makes its provenance
// readable from any packet, which is what an Output Profile does in miniature:
// its fd 1 is not its fd 0.
const transcodePID = 0x1FF

// assetPID is the PID relaytest.SyntheticTS stamps on the channel's own
// stream, which fanRig builds its upstream from.
const assetPID = 0x100

// pidsIn reads the PID of every whole packet in data.
//
// THE TRAILING PARTIAL PACKET IS DROPPED RATHER THAN FAILED ON, because these
// bodies are read to a byte count and a reader that stops mid-packet is the
// reader's own boundary and not a misalignment of the stream. Every whole
// packet is still checked for its sync byte, which is the alignment claim
// rows 7 and 9 pin and which relaytest.AlignmentProblem would make on a body
// that happened to end on a boundary and miss on every body that did not.
func pidsIn(t *testing.T, data []byte) map[int]int {
	t.Helper()
	whole := (len(data) / relaytest.PacketSize) * relaytest.PacketSize
	if whole == 0 {
		t.Fatalf("the client received %d bytes, which is less than one packet", len(data))
	}
	counts := map[int]int{}
	for offset := 0; offset < whole; offset += relaytest.PacketSize {
		packet := data[offset : offset+relaytest.PacketSize]
		if packet[0] != relaytest.SyncByte {
			t.Fatalf("byte %d is %#02x, not the sync byte %#02x: the client's stream is misaligned",
				offset, packet[0], relaytest.SyncByte)
		}
		counts[relaytest.PacketPID(packet)]++
	}
	return counts
}

// standInProfileArgv is an Output Profile whose built command line spawns this
// test binary as a pass-through: `-i pipe:0` makes RunStandIn copy fd 0 to
// fd 1, which is structurally what an Output Profile does (raw MPEG-TS in on
// pipe:0, MPEG-TS out on pipe:1 -- core/models.py:173-174).
//
// COMMAND FIRST, as OutputProfileRefSerializer sends it
// (apps/proxy/serializers.py:230, and the literal in
// apps/proxy/tests/test_next_source_api.py:551). A fixture that sent the
// stream_profile shape instead would spawn the wrong argv and this file's
// tests would fail for a reason that is not their subject.
func standInProfileArgv(t *testing.T, args ...string) []string {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(
		append(args, "--ts-pid", strconv.Itoa(transcodePID), "-i", "pipe:0")...)
	return append([]string{command}, argv...)
}

// profileRig is fanRig with one active Output Profile on the next-source
// answer.
func profileRig(t *testing.T, id string, entry relaytest.OutputProfileConfig, up relaytest.Config, overrides map[string]any) *rig {
	t.Helper()
	return fanRigWith(t, relaytest.ControlPlaneConfig{
		OutputProfiles: map[string]relaytest.OutputProfileConfig{id: entry},
	}, up, overrides)
}

// tuneProfile opens a stream under an Output Profile, the way the authorize
// hop opens one: X-Relay-Output carries the id apps/proxy/authorize.py:483-488
// resolved. It returns the response without asserting its status, so a caller
// whose subject IS the status can read it.
func (r *rig) tuneProfile(t *testing.T, channelID, clientID, profileID, format string) *http.Response {
	t.Helper()
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", channelID)
	header.Set("X-Relay-Client", clientID)
	header.Set("X-Relay-Client-IP", "198.51.100.4")
	header.Set("X-Relay-User", "7")
	header.Set("X-Relay-Output", profileID)
	if format != "" {
		header.Set("X-Relay-Output-Format", format)
	}
	return r.tune(t, "/proxy/ts/stream/"+channelID, header)
}

// PARITY-MATRIX ROW 11: one transcode process per active (channel, profile)
// pair, whatever the client count. "Ten AC3 clients cost one ffmpeg."
//
// COUNTED BY SPAWNS, NOT BY REGISTRY ENTRIES, which is Global Constraint 35
// and the reason this test can fail at all. A relay that started a SECOND
// transcode per client and overwrote its map entry satisfies "the registry
// holds one pipeline" while leaking a process; the spawn log answers "how many
// processes were started" directly. It is
// apps/proxy/live_proxy/tests/output_support.py:83's spawn_logging_standin and
// :111's spawn_count in Go, and the Python pin it mirrors is
// test_output_profile_sharing.py::OutputProfileSharingTests::
// test_two_clients_on_one_output_profile_share_a_single_transcode.
func TestTwoClientsOnOneOutputProfileShareOneTranscode(t *testing.T) {
	log := filepath.Join(t.TempDir(), "profile-spawns.log")
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t, "--spawn-log", log),
	}, relaytest.Config{Rate: 4}, nil)

	first := r.tuneProfile(t, "c-share-profile", "client-a", "3", "")
	defer func() { _ = first.Body.Close() }()
	if first.StatusCode != http.StatusOK {
		t.Fatalf("the first profile tune answered %d, want 200", first.StatusCode)
	}
	firstBytes := readAtLeast(first.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(firstBytes) < 20*buffer.TSPacketSize {
		t.Fatalf("the first client received %d bytes, want at least 20 packets", len(firstBytes))
	}
	if got := pidsIn(t, firstBytes); got[transcodePID] == 0 || got[assetPID] != 0 {
		t.Fatalf("the first client's packets carry PIDs %v, want only the transcode's %#x", got, transcodePID)
	}

	second := r.tuneProfile(t, "c-share-profile", "client-b", "3", "")
	defer func() { _ = second.Body.Close() }()
	if second.StatusCode != http.StatusOK {
		t.Fatalf("the second profile tune answered %d, want 200", second.StatusCode)
	}
	secondBytes := readAtLeast(second.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(secondBytes) < 20*buffer.TSPacketSize {
		t.Fatalf("the second client received %d bytes, want at least 20 packets", len(secondBytes))
	}
	// BOTH CLIENTS ARE READING THE TRANSCODE, which is what "share" means. A
	// second client silently served the channel's own ring would also produce
	// one spawn.
	if got := pidsIn(t, secondBytes); got[transcodePID] == 0 || got[assetPID] != 0 {
		t.Fatalf("the second client's packets carry PIDs %v, want only the transcode's %#x", got, transcodePID)
	}

	if got := relaytest.SpawnCount(log); got != 1 {
		t.Fatalf("the relay spawned %d transcodes for two clients on one Output Profile, want 1", got)
	}

	// Complementary, not redundant, and in the same spirit as the Python
	// test's own second assertion: the key it is registered under is the one
	// output/profile/manager.py builds for itself.
	ch := r.Manager.Get("c-share-profile")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if formats := ch.OutputFormats(); len(formats) != 1 || formats[0] != "mpegts:p3" {
		t.Fatalf("the channel's output registry holds %v, want exactly one mpegts:p3", formats)
	}
	if got := ch.Clients(); got != 2 {
		t.Fatalf("the channel has %d clients, want 2", got)
	}
	// ONE UPSTREAM AND ONE next-source FOR BOTH, which is what makes the
	// single transcode a SHARING claim rather than a coincidence of two
	// separate channels.
	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1", got)
	}
	if got := len(r.Control.RequestsTo("/next-source")); got != 1 {
		t.Fatalf("the relay made %d next-source calls, want 1", got)
	}
}

// A PROFILE CLIENT READS THE TRANSCODE'S RING AND A PLAIN CLIENT READS THE
// CHANNEL'S, on one channel and one upstream: views.py:773-776's get_buffer
// (channel, profile) is the only thing that differs between them.
//
// PROVED IN THE BYTES, through the PID the stand-in transcode rewrites: the
// profile client's packets carry the transcode's PID and the plain client's
// carry the asset's. Without that rewrite a pass-through stand-in would make
// the two streams identical and the assertion could not fail -- see
// transcodePID above.
func TestAProfileClientAndAPlainClientShareOneUpstream(t *testing.T) {
	log := filepath.Join(t.TempDir(), "profile-spawns.log")
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t, "--spawn-log", log),
	}, relaytest.Config{Rate: 4}, nil)

	plain := r.tuneAs(t, "c-mixed-profile", "client-plain")
	defer func() { _ = plain.Body.Close() }()
	waitForHead(t, r, "c-mixed-profile", 1)

	profiled := r.tuneProfile(t, "c-mixed-profile", "client-profile", "3", "")
	defer func() { _ = profiled.Body.Close() }()
	if profiled.StatusCode != http.StatusOK {
		t.Fatalf("the profile tune answered %d, want 200", profiled.StatusCode)
	}
	profiledBytes := readAtLeast(profiled.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(profiledBytes) < 20*buffer.TSPacketSize {
		t.Fatalf("the profile client received %d bytes, want at least 20 packets", len(profiledBytes))
	}
	plainBytes := readAtLeast(plain.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(plainBytes) < 20*buffer.TSPacketSize {
		t.Fatalf("the plain client received %d bytes, want at least 20 packets", len(plainBytes))
	}

	// THE TWO ASSERTIONS ARE OPPOSITE HALVES OF ONE CLAIM, and both are made:
	// a relay that sent every client the transcode's ring would pass the first
	// and fail the second, and one that ignored the profile entirely -- which
	// is the defect this whole PR could regress into -- fails the first.
	if got := pidsIn(t, profiledBytes); got[transcodePID] == 0 || got[assetPID] != 0 {
		t.Fatalf("the profile client's packets carry PIDs %v, want only the transcode's %#x", got, transcodePID)
	}
	if got := pidsIn(t, plainBytes); got[assetPID] == 0 || got[transcodePID] != 0 {
		t.Fatalf("the plain client's packets carry PIDs %v, want only the asset's %#x", got, assetPID)
	}

	if got := relaytest.SpawnCount(log); got != 1 {
		t.Fatalf("the relay spawned %d transcodes, want 1: the plain client must not have one", got)
	}
	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1: the two clients share one upstream", got)
	}
}

// AN fMP4 CLIENT ON AN OUTPUT PROFILE RUNS TWO PROCESSES, CHAINED, and that is
// Python's composition rather than a choice here. views.py runs
// ensure_output_profile first (:765-767), resolves get_buffer(channel,
// profile) second (:773-776), and hands THAT buffer to ensure_output_format as
// the remux's source under the compound key f'fmp4:p{id}' (:731-734, :790-792).
// So the transcode writes a TS ring under `mpegts:p3` and the remux reads it
// and writes fragments under `fmp4:p3`.
//
// TWO SPAWNS AND TWO REGISTRY KEYS ARE BOTH ASSERTED, because either alone is
// satisfiable by the wrong thing: two spawns with one key would be a leak, and
// two keys with one spawn would mean a pipeline that never started.
func TestAnFMP4ClientOnAnOutputProfileRunsTheTranscodeAndTheRemuxChained(t *testing.T) {
	dir := t.TempDir()
	transcodeLog := filepath.Join(dir, "transcode-spawns.log")
	remuxLog := filepath.Join(dir, "remux-spawns.log")
	// WHAT THE REMUX WAS FED, which nothing else here can see: the stand-in
	// remux writes synthetic fMP4 and IGNORES its input, so without this the
	// chained test passes whether the remux read the transcode's ring or the
	// channel's -- a fixture that patches away its own subject. Demonstrated:
	// the break-check that dropped Source from the remux's OutputSpec stayed
	// GREEN until this file was added.
	remuxInput := filepath.Join(dir, "remux-stdin-pid")
	r := fanRigWith(t, relaytest.ControlPlaneConfig{
		OutputProfiles: map[string]relaytest.OutputProfileConfig{
			"3": {ID: 3, Argv: standInProfileArgv(t, "--spawn-log", transcodeLog)},
		},
	}, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--spawn-log", remuxLog, "--stdin-pid-log", remuxInput,
			"--fmp4-fragments", "60", "--fmp4-interval", "0.02")))

	response := r.tuneProfile(t, "c-chained", "client-a", "3", output.FormatFMP4)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the fMP4 profile tune answered %d, want 200", response.StatusCode)
	}
	if got := response.Header.Get("Content-Type"); got != ContentTypeFMP4 {
		t.Fatalf("the Content-Type is %q, want %q", got, ContentTypeFMP4)
	}
	body := readAtLeast(response.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second)
	if len(body) == 0 {
		t.Fatal("the chained client received no bytes at all")
	}
	if problem := relaytest.FMP4ShapeProblem(body); problem != "" && len(body) > 2*len(relaytest.SyntheticFMP4Init()) {
		t.Fatalf("the chained client's bytes are not fMP4: %s", problem)
	}

	ch := r.Manager.Get("c-chained")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	keys := map[string]bool{}
	for _, key := range ch.OutputFormats() {
		keys[key] = true
	}
	if len(keys) != 2 || !keys["mpegts:p3"] || !keys["fmp4:p3"] {
		t.Fatalf("the channel's output registry holds %v, want exactly mpegts:p3 and fmp4:p3", ch.OutputFormats())
	}
	if got := relaytest.SpawnCount(transcodeLog); got != 1 {
		t.Fatalf("the relay spawned %d Output Profile transcodes, want 1", got)
	}
	if got := relaytest.SpawnCount(remuxLog); got != 1 {
		t.Fatalf("the relay spawned %d remuxes, want 1", got)
	}
	// AND THE CHAIN RUNS IN THE RIGHT ORDER: the remux's fd 0 carries the
	// TRANSCODE's packets, not the channel's. views.py:790-792 hands
	// ensure_output_format the profile's buffer as source_buffer, and this is
	// the only thing that can tell whether that happened.
	deadline := time.Now().Add(15 * time.Second)
	for relaytest.StdinPacketPID(remuxInput) == -1 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	switch got := relaytest.StdinPacketPID(remuxInput); got {
	case transcodePID:
	case -1:
		t.Fatal("the remux read no transport-stream packet at all on fd 0 within fifteen seconds")
	default:
		t.Fatalf("the remux's fd 0 carried PID %#x, want the transcode's %#x (the channel's own ring is %#x): "+
			"the fMP4 remux must read the Output Profile's output, not the channel's", got, transcodePID, assetPID)
	}
}

// THE LIST PAYLOAD NAMES THE PROFILE THE CLIENT IS ACTUALLY BEING SERVED
// UNDER. channel_status.py:579-582 sets output_profile_id on BOTH branches, so
// the key is never absent -- null for a client with no profile, the integer id
// for one with.
//
// ASSERTED ON THE LIVE ENDPOINT, not on the golden fixture, for 2c-6's Ruling
// R11 reason: the golden already carries an integer and a null on its two
// clients, so it pins the SERIALIZER and pins nothing about whether a real
// tune puts the id in the registry. That is a property of identify and the
// handler.
func TestTheListPayloadNamesEachClientsOwnOutputProfile(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	plain := r.tuneAs(t, "c-listed-profile", "client-plain")
	defer func() { _ = plain.Body.Close() }()
	profiled := r.tuneProfile(t, "c-listed-profile", "client-profile", "3", "")
	defer func() { _ = profiled.Body.Close() }()
	if profiled.StatusCode != http.StatusOK {
		t.Fatalf("the profile tune answered %d, want 200", profiled.StatusCode)
	}
	if got := readAtLeast(profiled.Body, buffer.TSPacketSize, 15*time.Second); len(got) == 0 {
		t.Fatal("the profile client received no bytes")
	}

	status, body := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d, want 200", status)
	}
	var payload channelListPayload
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatalf("parsing the list payload: %v", err)
	}
	seen := map[string]*int{}
	for _, ch := range payload.Channels {
		for _, client := range ch.Clients {
			seen[client.ClientID] = client.OutputProfileID
		}
	}
	if got := seen["client-profile"]; got == nil || *got != 3 {
		t.Fatalf("the profile client is listed with output_profile_id %v, want 3", got)
	}
	if got := seen["client-plain"]; got != nil {
		t.Fatalf("the plain client is listed with output_profile_id %v, want null", *got)
	}
	// AND THE KEY IS PRESENT ON BOTH, which is the half a value check misses:
	// channel_status.py sets it on both branches, so a relay that omitted it
	// for the plain client would render a payload Django never produces.
	raw := map[string]any{}
	if err := json.Unmarshal(body, &raw); err != nil {
		t.Fatalf("re-parsing the list payload: %v", err)
	}
	channels, _ := raw["channels"].([]any)
	for _, entry := range channels {
		object, _ := entry.(map[string]any)
		clients, _ := object["clients"].([]any)
		for _, c := range clients {
			row, _ := c.(map[string]any)
			if _, present := row["output_profile_id"]; !present {
				t.Fatalf("a client row has no output_profile_id key at all: %v", row)
			}
		}
	}
}

// A PROFILE DEACTIVATED BETWEEN THE AUTHORIZE HOP AND THE TUNE IS SERVED
// WITHOUT ONE, and the client's registry row says null.
//
// Python's own behaviour and not a fallback invented here: the hop resolved
// the id with is_active=True (apps/proxy/authorize.py:203-222) and put it in
// X-Relay-Output; views.py:150-155 then re-reads the row with is_active=True
// and gets None, and :725-751 registers the client with that None and serves
// it plain TS. The Go relay reaches the same answer because the deactivated
// profile is no longer in the next-source map.
func TestAProfileMissingFromTheAnswerIsServedWithoutOne(t *testing.T) {
	// An answer carrying a DIFFERENT active profile, so the map is known and
	// non-empty and the only thing missing is the one this tune names -- a
	// fixture with an empty map would also pass a relay that treated "no
	// profiles at all" as its own special case.
	r := profileRig(t, "8", relaytest.OutputProfileConfig{
		ID:   8,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-gone", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("a tune naming a deactivated profile answered %d, want 200", response.StatusCode)
	}
	served := readAtLeast(response.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(served) < 20*buffer.TSPacketSize {
		t.Fatalf("the client received %d bytes, want the channel's own stream", len(served))
	}
	if got := pidsIn(t, served); got[assetPID] == 0 || got[transcodePID] != 0 {
		t.Fatalf("the client's packets carry PIDs %v, want only the asset's %#x: no transcode should exist", got, assetPID)
	}

	ch := r.Manager.Get("c-gone")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if got := ch.OutputFormats(); len(got) != 0 {
		t.Fatalf("the channel runs output pipelines %v for a profile that is not active", got)
	}
	clients := ch.ClientSnapshot()
	if len(clients) != 1 {
		t.Fatalf("the channel has %d clients, want 1", len(clients))
	}
	if clients[0].OutputProfileID != nil {
		t.Fatalf("the client is registered with output_profile_id %d, want null: the profile it named is not active",
			*clients[0].OutputProfileID)
	}
}

// THE DEACTIVATED-PROFILE CORRECTION DOES NOT RACE THE LIST ENDPOINT, which is
// the one place this PR writes to a *channel.Client the channel already holds.
//
// FOUND BY REVIEW, NOT BY DESIGN. attachOutputProfile's not-found arm corrects
// the client's registry row to null, and an earlier draft did it twice -- once
// through Channel.SetClientOutputProfile, which takes the channel's write lock,
// and once as a bare `client.OutputProfileID = nil` on the struct the caller
// already holds. The second looks free: same field, same value, a pointer this
// goroutine created. It is a data race, because Attach put that pointer in the
// channel's registry and ClientSnapshot reads the field under RLock. `-race`
// reported it as a write at httpapi/profile.go against a read at
// channel/channel.go's ClientSnapshot.
//
// THE ASSERTION IS THE REGISTRY VALUE, NOT "NO RACE". A test whose only oracle
// is the detector passes on any run where the two goroutines happen not to
// overlap, which is the "silence read as pass" shape. So this asserts what the
// correction is FOR -- the client ends up listed with a null profile -- and the
// detector is what makes the concurrent reader worth having. Run it with
// -race or it pins only the value.
func TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint(t *testing.T) {
	// An answer carrying a DIFFERENT active profile, so the map is known and
	// non-empty and the only thing missing is the one this tune names -- the
	// arm that performs the correction.
	r := profileRig(t, "8", relaytest.OutputProfileConfig{
		ID:   8,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	// A reader hammering ClientSnapshot for the whole of the tune, which is
	// the exact call GET /proxy/relay/channels?clients=all makes.
	stop := make(chan struct{})
	var readers sync.WaitGroup
	readers.Add(1)
	go func() {
		defer readers.Done()
		for {
			select {
			case <-stop:
				return
			default:
			}
			if ch := r.Manager.Get("c-race"); ch != nil {
				_ = ch.ClientSnapshot()
			}
		}
	}()

	response := r.tuneProfile(t, "c-race", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	close(stop)
	readers.Wait()

	if response.StatusCode != http.StatusOK {
		t.Fatalf("the tune answered %d, want 200", response.StatusCode)
	}
	ch := r.Manager.Get("c-race")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	clients := ch.ClientSnapshot()
	if len(clients) != 1 {
		t.Fatalf("the channel has %d clients, want 1", len(clients))
	}
	if clients[0].OutputProfileID != nil {
		t.Fatalf("the client is registered with output_profile_id %d, want null: "+
			"the profile it named is not in the answer's map", *clients[0].OutputProfileID)
	}
}

// A PROFILE DJANGO COULD NOT BUILD IS A 500 WITH views.py:771's OWN BODY.
//
// The wire says `argv: null`, which is _with_output_profiles reporting that
// shlex refused the profile's parameters -- a row OutputProfileSerializer
// validates nothing against, so it can already be in the database. Python
// reaches the same failure one statement later (build_command() raises inside
// stream_ts's try) and answers 500 too; the BODY diverges, because Python's
// carries shlex's message and this relay has never seen it.
func TestAProfileWhoseArgvDjangoCouldNotBuildIsAFiveHundred(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{ID: 3, ArgvNull: true},
		relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-unbuildable", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusInternalServerError {
		t.Fatalf("a tune naming an unbuildable profile answered %d, want 500", response.StatusCode)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the body: %v", err)
	}
	if string(body) != profileNotStartedBody {
		t.Fatalf("the 500 body is %q, want views.py:771's %q", body, profileNotStartedBody)
	}
}

// A TRANSCODE THAT CANNOT BE SPAWNED IS THE SAME 500, which is
// ensure_output_profile returning False (server.py:1532-1538, views.py:767-772)
// rather than build_command raising.
func TestATranscodeThatCannotBeSpawnedIsAFiveHundred(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: []string{"/nonexistent/dispatcharr-transcode", "-i", "pipe:0"},
	}, relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-nospawn-profile", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusInternalServerError {
		t.Fatalf("a tune whose transcode could not be spawned answered %d, want 500", response.StatusCode)
	}
	body, _ := io.ReadAll(response.Body)
	if string(body) != profileNotStartedBody {
		t.Fatalf("the 500 body is %q, want views.py:771's %q", body, profileNotStartedBody)
	}
}

// A CONTROL PLANE THAT SENDS NO output_profiles AT ALL IS A CONTRACT MISMATCH,
// not "this deployment has no profiles".
//
// Django has sent the key on every answer since Phase 2 PR 2b-2 and sends an
// EMPTY OBJECT when nothing is active, which
// apps/proxy/tests/test_next_source_api.py::
// test_no_active_profiles_is_an_empty_object_not_a_missing_key pins. An absent
// key therefore means the relay is newer than the control plane, and serving
// the client plain TS would hand a device the wrong audio codec silently. 502,
// the same answer an absent proxy_settings key gets.
func TestATuneNamingAProfileAgainstAnOlderControlPlaneIsABadGateway(t *testing.T) {
	r := fanRigWith(t, relaytest.ControlPlaneConfig{OutputProfilesAbsent: true},
		relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-oldcp", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("a tune naming a profile against a control plane with no output_profiles answered %d, want 502",
			response.StatusCode)
	}

	// AND A TUNE THAT NAMES NO PROFILE IS UNAFFECTED, which is what stops this
	// from being a blanket refusal: an older control plane serves every
	// ordinary client exactly as before.
	plain := r.tuneAs(t, "c-oldcp", "client-plain")
	defer func() { _ = plain.Body.Close() }()
	if got := readAtLeast(plain.Body, buffer.TSPacketSize, 15*time.Second); len(got) == 0 {
		t.Fatal("a tune with no Output Profile received nothing against a control plane with no output_profiles")
	}
}

// THE PROFILE SET IS REFRESHED BY A FAILOVER'S next-source ANSWER, AND NOT BY
// A DEGRADED ONE. Ruling R5's mechanism, pinned in both directions.
//
// WHY IT NEEDS A TEST AT ALL. R5 argues the relay should refresh the cached set
// on every answer rather than snapshot it at channel start, because Python
// re-reads the OutputProfile row per client and a start-time snapshot would go
// stale for a channel's whole life. That argument is only worth anything if the
// refresh happens: deleting `channel/failover.go`'s two-line assignment left the
// ENTIRE suite green before this test existed, found by review.
//
// BOTH ARMS IN ONE TEST, deliberately. The refresh and its exception are one
// rule -- refresh from an answer, never from the cache -- and a test that only
// proved the first would pass a relay that refreshed from the degraded
// candidate list too, which is the failure R5 actually warns about: that list
// was cached at channel start and carries no profile set at all, so refreshing
// from it would clear the map rather than update it.
//
// The primary and the first alternate each stop after two chunks, so each is
// exhausted after three quick EOFs -- TestAFailoverFallsBackToTheCachedCandidates
// WhenTheControlPlaneIsDown's own fixture shape, for the same reason.
func TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot(t *testing.T) {
	second := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, assetPID), StopAfterBytes: rigChunkBytes * 2})
	t.Cleanup(second.Close)
	third := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, assetPID)})
	t.Cleanup(third.Close)

	// At the tune, profile 3 is the only active one.
	cp := relaytest.ControlPlaneConfig{
		Alternates: []relaytest.AlternateConfig{
			{StreamID: 2, URL: second.URL()},
			{StreamID: 3, URL: third.URL()},
		},
		OutputProfiles: map[string]relaytest.OutputProfileConfig{
			"3": {ID: 3, Argv: standInProfileArgv(t)},
		},
	}
	r := fanRigWith(t, cp, relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, assetPID), StopAfterBytes: rigChunkBytes * 2}, nil)

	response := r.tuneAs(t, "c-refresh", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-refresh", 1)

	ch := r.Manager.Get("c-refresh")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if _, found := ch.OutputProfiles().Lookup("3"); !found {
		t.Fatal("the channel did not cache the tune's own profile set")
	}
	if _, found := ch.OutputProfiles().Lookup("9"); found {
		t.Fatal("the channel already holds profile 9, which no answer has carried")
	}

	// THE OPERATOR EDITS THE SET between answers: 3 is deactivated and 9
	// appears. Nothing tells the running channel; only its next answer can.
	r.Control.SetOutputProfiles(map[string]relaytest.OutputProfileConfig{
		"9": {ID: 9, Argv: standInProfileArgv(t)},
	})

	// The primary exhausts, the failover reaches Django, and the answer it
	// gets carries the NEW set.
	waitFor(t, "the failover to the second stream", 15*time.Second, func() bool { return second.Requests() >= 1 })
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if _, found := ch.OutputProfiles().Lookup("9"); found {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if _, found := ch.OutputProfiles().Lookup("9"); !found {
		t.Fatalf("the channel still holds %v after a failover whose answer carried profile 9: "+
			"the refresh at channel/failover.go did not happen", ch.OutputProfiles().ByID)
	}
	if _, found := ch.OutputProfiles().Lookup("3"); found {
		t.Fatal("the channel still holds profile 3: the set is REPLACED by an answer, not merged into")
	}

	// AND THE DEGRADED ARM. The control plane goes down, the second stream
	// exhausts, and the failover falls back to the candidate list cached at
	// channel start -- which carries no profile set. The channel must keep
	// the one it has rather than clear it.
	r.Control.SetStatus(http.StatusServiceUnavailable)
	waitFor(t, "the degraded failover to the third stream", 20*time.Second, func() bool { return third.Requests() >= 1 })
	if _, found := ch.OutputProfiles().Lookup("9"); !found {
		t.Fatalf("a DEGRADED failover cleared the profile set to %v: the cached candidate list "+
			"carries no answer, so Resolved.OutputProfiles.Known is false and the channel keeps what it had",
			ch.OutputProfiles().ByID)
	}
	if !ch.OutputProfiles().Known {
		t.Fatal("a degraded failover made the channel's set unknown, which would 502 every later profile tune")
	}
}

// THE LAST PROFILE CLIENT LEAVING STOPS THE TRANSCODE AND NOT THE CHANNEL.
//
// Python's disconnect sweep reads every remaining client's output_profile_id
// and stops any transcode no longer named (server.py:1216-1219), and it runs
// BEFORE the `if total == 0` branch at :1221 that honours
// channel_shutdown_delay -- so the transcode stops at once while the channel
// keeps running for the plain client still watching.
func TestTheLastProfileClientLeavingStopsTheTranscodeAndNotTheChannel(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	plain := r.tuneAs(t, "c-outlives-profile", "client-plain")
	defer func() { _ = plain.Body.Close() }()
	waitForHead(t, r, "c-outlives-profile", 1)

	profiled := r.tuneProfile(t, "c-outlives-profile", "client-profile", "3", "")
	if profiled.StatusCode != http.StatusOK {
		t.Fatalf("the profile tune answered %d, want 200", profiled.StatusCode)
	}
	if got := readAtLeast(profiled.Body, buffer.TSPacketSize, 15*time.Second); len(got) == 0 {
		t.Fatal("the profile client received no bytes")
	}
	ch := r.Manager.Get("c-outlives-profile")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if got := len(ch.OutputFormats()); got != 1 {
		t.Fatalf("the channel runs %d output pipelines before the profile client leaves, want 1", got)
	}

	_ = profiled.Body.Close()

	deadline := time.Now().Add(15 * time.Second)
	for len(ch.OutputFormats()) != 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if got := ch.OutputFormats(); len(got) != 0 {
		t.Fatalf("the channel still runs %v fifteen seconds after its last profile client left", got)
	}
	if r.Manager.Get("c-outlives-profile") == nil {
		t.Fatal("the channel stopped: a transcode's last client leaving must not end a channel a plain client is still watching")
	}
	if ch.Ring().Closed() {
		t.Fatal("the channel's ring closed when the profile client left")
	}
}

// STOPPING THE CHANNEL STOPS ITS TRANSCODE, with the client still attached --
// stop_all_output_profiles (server.py:1563-1566) from stop_channel's local
// cleanup at :1772, which reaches the Go registry through run's deferred
// stopOutputs.
func TestStoppingTheChannelStopsItsProfileTranscode(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-stopped-profile", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the profile tune answered %d, want 200", response.StatusCode)
	}
	if got := readAtLeast(response.Body, buffer.TSPacketSize, 15*time.Second); len(got) == 0 {
		t.Fatal("the profile client received no bytes")
	}
	ch := r.Manager.Get("c-stopped-profile")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if got := len(ch.OutputFormats()); got != 1 {
		t.Fatalf("the channel runs %d output pipelines before the stop, want 1", got)
	}

	// A SECOND REFERENCE NOBODY RELEASES, which is what makes this test about
	// stopOutputs and not about the refcount.
	//
	// Found by break-check: with `defer c.stopOutputs()` removed from
	// Channel.run this test stayed GREEN, because a stopped channel closes its
	// ring, the pass-through transcode reaches EOF on fd 0 and exits, its own
	// ring closes, the client's loop ends and its deferred release empties the
	// registry. The refcount covered for the mechanism under test. (2c-6's
	// TestStoppingTheChannelStopsItsRemux does NOT have this hole, because its
	// stand-in remux keeps producing fragments after fd 0 closes and its
	// client therefore never releases -- a difference in the stand-in, not in
	// the relay.) Holding a reference the test never drops leaves stopOutputs
	// as the only thing that can empty the map.
	profiles := ch.OutputProfiles()
	profile, found := profiles.Lookup("3")
	if !found {
		t.Fatal("the channel does not hold the Output Profile the tune used")
	}
	if _, _, err := ch.AttachOutput(output.ProfileKey(profile.ID), channel.OutputSpec{Profile: &profile}); err != nil {
		t.Fatalf("taking a second reference on the transcode: %v", err)
	}

	r.Manager.Stop("c-stopped-profile")

	deadline := time.Now().Add(15 * time.Second)
	for len(ch.OutputFormats()) != 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if got := ch.OutputFormats(); len(got) != 0 {
		t.Fatalf("the stopped channel still runs %v with a reference on it that was never released", got)
	}
}
```


### Appendix Q — `relay/httpapi/fanout_test.go` and `golden_test.go`

Both of the merged tree's profile-bearing rows go — the bare one and the `andFMP4` one its fix round added, which is the combination 2c-7 makes work — replaced by two malformed-value rows at 400, plus an assertion that the refused value is never echoed. The `andFMP4` field, its `if` block and the `output` import go with them; `go vet` reports that import unused the moment the row is deleted. The golden's live-row message stops citing a stage that no longer describes it (Ruling R7).


**`relay/httpapi/fanout_test.go`**

```diff
--- a/httpapi/fanout_test.go
+++ b/httpapi/fanout_test.go
@@ -7,6 +7,7 @@
 	"fmt"
 	"io"
 	"net/http"
+	"strings"
 	"sync"
 	"testing"
 	"time"
@@ -14,7 +15,6 @@
 	"github.com/D10Scot/Dispatcharr/relay/buffer"
 	"github.com/D10Scot/Dispatcharr/relay/control"
 	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
-	"github.com/D10Scot/Dispatcharr/relay/output"
 )
 
 // rigAssetPackets is how many packets the fan-out tests' upstream loops.
@@ -431,10 +431,10 @@
 // control plane is asked.
 func TestAnOutputThisRelayDoesNotServeIsRefused(t *testing.T) {
 	for _, tc := range []struct {
-		name    string
-		header  string
-		value   string
-		andFMP4 bool
+		name   string
+		header string
+		value  string
+		status int
 	}{
 		// 2c-6 SERVES fmp4, so this row moved to a format NEITHER relay has.
 		// `hls` is the honest choice: apps/proxy/hls_proxy/ exists, is 1,206
@@ -444,24 +444,31 @@
 		// what both implementations do. Before 2c-6 this row said "fmp4"; a
 		// row that still did would now be asserting the opposite of what this
 		// PR ships.
-		{"an output format it does not serve", "X-Relay-Output-Format", "hls", false},
-		{"an Output Profile", "X-Relay-Output", "7", false},
-		// 2c-6 SERVES fmp4 and 2c-7 will serve Output Profiles; a tune asking
-		// for BOTH is still refused, and nothing else here covers the pair --
-		// the rows above vary one header each, so an identify that served a
-		// recognised format and never looked at the profile would satisfy
-		// both of them.
+		{"an output format it does not serve", "X-Relay-Output-Format", "hls", http.StatusNotImplemented},
+		// 2c-7 SERVES Output Profiles, so 2c-6's two profile rows are GONE and
+		// neither is replaced by a 501: the bare-profile row is now
+		// TestTwoClientsOnOneOutputProfileShareOneTranscode's subject, and the
+		// fMP4-plus-profile row 2c-6's fix round added is
+		// TestAnFMP4ClientOnAnOutputProfileRunsTheTranscodeAndTheRemuxChained's.
 		//
-		// NOT ABOUT THE ORDER OF THE TWO CHECKS, and this was measured rather
-		// than assumed: swapping them so the format is tested first leaves all
-		// three subtests passing, because the profile arm refuses
-		// unconditionally wherever it sits. What this row actually guards is
-		// an identify that RETURNED EARLY on a format it serves -- a plausible
-		// tidy-up once there are two served formats -- which would accept this
-		// tune and stream plain fMP4 while silently dropping the Output
-		// Profile the operator configured. Python runs the `fmp4:p7` pipeline
-		// for it instead (server.py's _parse_output_key).
-		{"an Output Profile on an fMP4 tune", "X-Relay-Output", "7", true},
+		// THE CONCERN THAT ROW GUARDED IS NOT DROPPED WITH IT. Its comment
+		// named an identify that RETURNED EARLY on a format it serves and so
+		// silently dropped the Output Profile -- which under 2c-7 is no longer
+		// a 501 question at all, because the profile is resolved after the
+		// channel is up rather than refused in identify. The chained test is
+		// the stronger form of the same guard: it asserts the transcode really
+		// spawned, that both `mpegts:p3` and `fmp4:p3` are registered, and that
+		// the remux's own fd 0 carried the TRANSCODE's packets. A relay that
+		// dropped the profile and streamed plain fMP4 passes a status check and
+		// fails all three.
+		//
+		// What is still refused is a value that is not a positive integer,
+		// which apps/proxy/authorize_views.py:154-162 denies 403 one hop
+		// earlier, so it reaches a relay only when the internal contract is
+		// broken. 400, not 501: the relay serves this output, it just cannot
+		// read the header.
+		{"a malformed Output Profile id", "X-Relay-Output", "seven", http.StatusBadRequest},
+		{"a zero Output Profile id", "X-Relay-Output", "0", http.StatusBadRequest},
 	} {
 		t.Run(tc.name, func(t *testing.T) {
 			r := fanRig(t, relaytest.Config{Rate: 4}, nil)
@@ -469,16 +476,18 @@
 			header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
 			header.Set("X-Relay-Channel", "c-output")
 			header.Set(tc.header, tc.value)
-			if tc.andFMP4 {
-				header.Set("X-Relay-Output-Format", output.FormatFMP4)
-			}
 
 			response := r.tune(t, "/proxy/ts/stream/c-output", header)
 			defer func() { _ = response.Body.Close() }()
-			if response.StatusCode != http.StatusNotImplemented {
-				t.Fatalf("a tune asking for %s=%s answered %d, want 501",
-					tc.header, tc.value, response.StatusCode)
+			if response.StatusCode != tc.status {
+				t.Fatalf("a tune asking for %s=%s answered %d, want %d",
+					tc.header, tc.value, response.StatusCode, tc.status)
 			}
+			// And the refused value is never echoed into the body.
+			body, _ := io.ReadAll(response.Body)
+			if strings.Contains(string(body), tc.value) {
+				t.Fatalf("the refusal body repeats the rejected value %q: %q", tc.value, body)
+			}
 			if got := len(r.Control.Requests()); got != 0 {
 				t.Fatalf("the relay made %d control-plane calls for a tune it cannot serve, "+
 					"want 0 -- the refusal must happen before anything is reserved", got)
```


**`relay/httpapi/golden_test.go`**

```diff
--- a/httpapi/golden_test.go
+++ b/httpapi/golden_test.go
@@ -295,8 +295,9 @@
 	// null or as a bare integer -- both carry the key -- so a *Client.OutputProfileID
 	// that lost its pointer and became an int would pass undetected.
 	if got := liveRow["output_profile_id"]; got != nil {
-		t.Fatalf("the live client reports output_profile_id %v, want null: 2c-3 serves "+
-			"no Output Profile yet, so every attached client's OutputProfileID is nil", got)
+		t.Fatalf("the live client reports output_profile_id %v, want null: this tune named "+
+			"no Output Profile, and channel_status.py:579-582 renders null for such a "+
+			"client rather than omitting the key", got)
 	}
 }
 
```

### Appendix R — `docs/relay-parity-matrix.md`, row 11's Go pin

**A DIFF, not an instruction, and that is a correction.** An earlier draft said "append one reference, comma-separated, inside the same cell", and the reviewer applying it put the reference after the row's closing pipe — a six-cell row the matrix guard rejects. Every other appendix in this plan applies mechanically; this one now does too.

Read the HTML comment at the top of that file before touching it regardless: one row is one line, cells are never padded, and no Markdown formatter may be run over it.

**Verified**: applied to `docs/relay-parity-matrix.md` at `eb7fac07`, the row stays **five cells** with no padding, and `cd e2e && npx playwright test --project=guards parity-matrix` passes **7/7** with `relay/httpapi/profile_test.go` present. Without that file the guard fails one test, `every pin resolves`, naming exactly `relay/httpapi/profile_test.go` — which is correct and expected on a branch that carries the plan and not the implementation.

**`docs/relay-parity-matrix.md`**

```diff
diff --git a/docs/relay-parity-matrix.md b/docs/relay-parity-matrix.md
index 4b82eb7e..79f10bbb 100644
--- a/docs/relay-parity-matrix.md
+++ b/docs/relay-parity-matrix.md
@@ -181,7 +181,7 @@ PR's first, which is the distance git needs to merge them cleanly.
 | 18 | What the status payload's `stream_name` and `m3u_profile_name` contain when the channel metadata hash was never written one | `apps/proxy/live_proxy/channel_status.py:74`, `apps/proxy/live_proxy/channel_status.py:106` | `apps/proxy/live_proxy/tests/test_zero_orm_reads.py::StatusNameFallbackTests::test_the_key_is_absent_when_redis_has_no_name_and_no_row_exists`, `apps/proxy/live_proxy/tests/test_zero_orm_reads.py::StatusNameFallbackTests::test_the_orm_fills_the_name_when_redis_has_none_and_the_row_exists` | 2b-3's answer: **absence is the contract.** The key is absent from the payload entirely — not null, not `''`, not the id — because `channel_status.py` only assigns it inside a truthy branch and `RelayChannelDetailSerializer` declares both `required=False`. Python's ORM fallback is best-effort enrichment on top of that: it fills the key when the row still exists and leaves it absent when the row is gone. The Go relay has no database and always omits it, which is inside the contract rather than a divergence from it. 2c: omit the key; never substitute null, `''` or the numeric id. The reads are NOT deleted — every name write in the tree guards the name on a value `url_utils.py:31-42`'s `tune_extras` degrades to `None` for a control plane that predates 2b-1, and the relay and control plane are separately deployable, so both fallbacks are reachable under version skew (`views.py:553-566` records it). They are allowlisted in `zero_orm_allowlist.py` and deleted wholesale in 2d. One production path defeats the repair rather than needing it — a degraded failover writes the new id and leaves the old name standing, so the key is present and wrong ([#265](https://github.com/D10Scot/Dispatcharr/issues/265)); that is a distinct defect from this row, cited not fixed. Coverage reads the two fallbacks as asymmetric (`:72-78` missing in 13/13, `:103-110` covered in 13/13) but that is one fixture's shape — `test_live_db_cleanup.py:322-344` supplies a `stream_name` and not an `m3u_profile_name`, mocks the query, and asserts nothing about either fallback. The spec and this row previously cited `:92`; 2b-1 moved it to `:106` |
 <!-- block: already pinned -->
 | 10 | Multi-client upstream sharing: three clients on one channel share exactly one upstream connection, and closing every client releases it | `apps/proxy/live_proxy/server.py:629-648`, `apps/proxy/live_proxy/server.py:2017-2052` | `e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection`, `e2e/tests/streaming/shared-upstream.spec.ts::closing every client releases the upstream`, `apps/proxy/live_proxy/tests/test_relay_client_stream.py::ClientSetTests::test_the_client_set_from_three_sharing_clients_to_an_empty_channel`, `relay/httpapi/fanout_test.go::TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint`, `relay/channel/fanout_test.go::TestNClientsShareOneSourceAndTheChannelOutlivesAllButTheLast` | The row asserts two things, so it cites both tests in the same file: the first proves the sharing, the second proves the release. `initialize_channel` reuses the buffer/client manager when the channel is already active (`:629-648`); the cleanup loop's `last_client_disconnect`/`channel_shutdown_delay` timer stops it once every client has gone (`:2017-2052`). The harness test does not exercise either citation directly: it never closes its own clients (it stops the channel by operator command instead), so `:2017-2052`'s disconnect-driven teardown is not reached, and with `:637`'s reuse check patched out the test still passed, because `views.py:619-622` already short-circuits `initialize_channel` within one process. What it actually proves: three clients share one upstream request; an operator-issued stop ends every stream with the upstream's request count still 1, and no reconnect happens. Release-on-client-disconnect stays e2e-only, carried by the two `shared-upstream.spec.ts` references, which stand |
-| 11 | One transcode process runs per active `(channel, profile)` pair across the cluster: a second client on the same Output Profile attaches to the existing process's buffer instead of spawning its own | `apps/proxy/live_proxy/output/profile/manager.py:67-122`, `apps/proxy/live_proxy/output/profile/manager.py:312-321` | `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts::two clients on one output profile share a single transcode`, `apps/proxy/live_proxy/tests/test_output_profile_sharing.py::OutputProfileSharingTests::test_two_clients_on_one_output_profile_share_a_single_transcode` | Ten AC3 clients cost one ffmpeg. 2a-6 added the second pin, an in-process harness test that counts SPAWNS of the profile's own command rather than surviving processes: the channel runs the locked Proxy stream profile, which spawns nothing, so every line in the spawn log is an Output Profile transcode. Both stand — the e2e spec proves the same claim through nginx in a container. |
+| 11 | One transcode process runs per active `(channel, profile)` pair across the cluster: a second client on the same Output Profile attaches to the existing process's buffer instead of spawning its own | `apps/proxy/live_proxy/output/profile/manager.py:67-122`, `apps/proxy/live_proxy/output/profile/manager.py:312-321` | `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts::two clients on one output profile share a single transcode`, `apps/proxy/live_proxy/tests/test_output_profile_sharing.py::OutputProfileSharingTests::test_two_clients_on_one_output_profile_share_a_single_transcode`, `relay/httpapi/profile_test.go::TestTwoClientsOnOneOutputProfileShareOneTranscode` | Ten AC3 clients cost one ffmpeg. 2a-6 added the second pin, an in-process harness test that counts SPAWNS of the profile's own command rather than surviving processes: the channel runs the locked Proxy stream profile, which spawns nothing, so every line in the spawn log is an Output Profile transcode. Both stand — the e2e spec proves the same claim through nginx in a container. Go column added in Phase 2 stage 2c-7, counting SPAWNS as the two Python pins do: with `Channel.AttachOutput`'s reuse branch disabled the registry assertion and both PID assertions stay green and only the count reddens. The Go relay reaches the same claim with one process and no owner lock — spec D2 deletes `output_owner`/`output_state`, so "across the cluster" becomes "in the one relay process" and the sharing is the registry's refcount. |
 | 21 | Authorize matrix — **XC credentials** (`<user>/<pass>` path segments, compared with `hmac.compare_digest`): every check enforced; `hidden_from_output` and adult filtering answer 403 | `apps/proxy/authorize.py:148-174`, `apps/proxy/authorize.py:420-442` | `e2e/tests/streaming/authorize-matrix.spec.ts::a hidden channel is refused on the XC live root to an ordinary XC user`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_xc_user_with_hide_adult_content_is_refused_on_the_live_root` | `resolve_xc_user` is the constant-time comparison CLAUDE.md's Known defects section already names. `hidden_from_output` is pinned on-path by the cited e2e test; the adult-filter half for this principal is now also pinned on-path by the cited Python test, a live-root equivalent to the catch-up-root test that used to be this row's only proof of it (drives `/timeshift/...`, off the matrix's live-path scope) |
 | 22 | Authorize matrix — **JWT / API key / query-param JWT**, non-admin: every check enforced | `apps/proxy/authorize.py:227-265`, `apps/proxy/authorize.py:420-442` | `e2e/tests/streaming/authorize-matrix.spec.ts::an adult channel is refused on the native stream route to a hide_adult_content viewer` | `_drf_user` runs the DRF authenticator set explicitly rather than relying on the calling view's own `authentication_classes`. Drives `/proxy/ts/stream/<uuid>` with an `X-API-Key` principal, in scope; the plan's first draft pinned this row to a catch-up test, which the matrix's own scope paragraph excludes |
 | 24 | Authorize matrix — **Anonymous** (a bare channel UUID): the ACL applies, `hidden_from_output` answers 403, and every user-scoped check is inapplicable — an anonymous request with a valid UUID still streams an ordinary channel | `apps/proxy/authorize.py:316`, `apps/proxy/authorize.py:325-327`, `apps/proxy/authorize.py:386-389` | `e2e/tests/streaming/authorize-matrix.spec.ts::a channel hidden from output is refused even to an anonymous request`, `e2e/tests/streaming/authorize-matrix.spec.ts::an ordinary channel still streams with no credential at all` | `hidden_from_output` is checked with no principal at all, which is why it is the one check anonymous also fails |
```

### Appendix S — Amendment A7 and the Done-log line

Applied as a diff for Appendix R's reason. A7 goes after A6.6 and before `## Stage 2d`; the Done-log row goes after the last existing `| 2c-6 ` row.

**`docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`**

```diff
diff --git a/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md b/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
index d0f95a25..b8d43476 100644
--- a/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
+++ b/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
@@ -2367,6 +2367,96 @@ a Go test that hands the ring a finite asset once has to make the asset long
 enough. 2c-7's Output Profile transcode reads the same ring and will meet the
 same threshold if its test asset is short.
 
+#### Amendment A7 (2c-7) — seven findings and rulings from the Output Profile
+
+**A7.1 — fMP4 and an Output Profile COMPOSE, as a chain of two processes,
+and the registry key is Python's own compound string.** `views.py` runs
+`ensure_output_profile` first (`:765-767`), resolves `get_buffer(channel_id,
+profile=id)` second (`:773-776`), and hands that buffer to
+`ensure_output_format` as `source_buffer` under the key `f'fmp4:p{id}'`
+(`:731-734`, `:790-792`). The transcode's own namespace is the literal
+`f"mpegts:p{self.profile_id}"` at six sites in `output/profile/manager.py`
+— **always `mpegts`, whatever the client asked for**, because an Output
+Profile's output *is* MPEG-TS (`core/models.py:173-174`). So an fMP4 client
+on a profile runs two processes under two keys that cannot collide, and the
+second reads the first. One registry, keyed by the compound string
+`_parse_output_key` splits; the composition lives in `httpapi` where
+`views.py` puts it.
+
+**A7.2 — the contract could not tell a BROKEN Output Profile from a
+DEACTIVATED one, and they get opposite answers. CLOSED in 2c-7.**
+`_with_output_profiles` skipped a profile whose `parameters` `shlex` could
+not split, so one bad row could not 500 next-source for every channel. But a
+profile deactivated between the authorize hop and the tune is also absent
+from the map, and Python serves that client with **no profile at all**
+(`views.py:150-155`, `:725-751`) where it **500s** the client that selects a
+broken one (`build_command()` raises inside `stream_ts`'s try, `:823-827`).
+A relay reading this map could reproduce one and not the other, and the one
+it would get wrong silently hands a device the original audio. Closed by
+sending the entry with `"argv": null` instead of omitting it —
+`OutputProfileRefSerializer.argv` gains `allow_null=True` — which is exactly
+`stream_profile.argv`'s three-state shape from Amendment A4.1: a list is the
+built command, null is "Django could not build it", the key absent is a
+control plane older than 2b-2. Three files, no migration, no new field.
+
+**A7.3 — the Output Profile argv carries the COMMAND as element 0 and
+`stream_profile.argv` does not.** `core/models.py:200-203`'s `build_command`
+is `[self.command] + shlex_split(self.parameters)` and
+`apps/proxy/serializers.py:230` sends the result whole, where
+`next_source.py`'s `_stream_profile_ref` sends `command` in its own field and
+the rest in `argv`. Reproduced rather than tidied; the split happens in
+exactly two places and both are pinned token for token.
+
+**A7.4 — the profile set is cached PER CHANNEL and refreshed by every
+next-source answer, never per client.** Python re-reads the row per client
+(`views.py:150-155`); the relay cannot, because next-source runs once per
+channel and the second client makes no control-plane call at all
+(`views.py:712`) — Amendment A1/2b-2's Ruling R3 rejected a per-client route.
+The set arrives on every answer, so the channel replaces its copy on every
+non-degraded failover; a degraded resolution came from the cached candidate
+list and carries no answer, so it leaves the copy alone. **Residual
+divergence, stated and untested**: an operator editing a profile's
+`parameters` mid-channel reaches new clients on that channel only after its
+next next-source call, where Python reaches them on the next tune. Untested
+deliberately — there is no Python behaviour here to pin, only the absence of
+one.
+
+**A7.5 — `output.Config`'s zero value is the fMP4 remux, which makes it the
+wrong type for an Output Profile.** `Config.command()` returns
+`RemuxCommand` for an empty `Command` and `Config.argv()` returns
+`RemuxArgv()` for a nil `Argv`. A profile reaching that with a blank command
+would silently become an ffmpeg remux, where Python fails the tune. So
+`StartProfile` takes its own `ProfileConfig` with no fallback and refuses an
+empty command before spawning. The same trap survives inside `Pipeline` —
+`run`'s bitstream-filter retry calls `cfg.command()`/`cfg.argvNoBSF()` — and
+is closed structurally by filling `cfg.Remux` from the profile's own command
+line even though the retry is unreachable for a profile. **Found by a
+break-check**: with those fields empty, forcing the retry spawned a real
+ffmpeg remux and the spawn-log assertion could not see it.
+
+**A7.6 — the owner lock, the state key and the TTL refresh are deleted with
+the lease.** `output/profile/manager.py:312-358`'s `_acquire_owner_lock`,
+`_set_state` and `_refresh_redis_ttls`, and `ensure_output_profile`'s
+five-arm staleness question including its 5-second `live:events:` round trip
+(`server.py:1406-1538`), exist so a second uWSGI worker can discover another
+worker's process. With one relay process the registry map is that discovery,
+and nothing can be orphaned. `PROFILE_KEY_TTL` and
+`PROFILE_TTL_REFRESH_INTERVAL` go with them, as does `_cleanup_redis`'s
+chunk-key scan. What survives is the refcount, which stops the transcode at
+zero with **no** shutdown delay — Python's disconnect sweep runs at
+`server.py:1216-1219`, before the `if total == 0` branch at `:1221` that
+honours `channel_shutdown_delay`.
+
+**A7.7 — two inputs for later stages.** First, `transcode_active`
+(`apps/proxy/live_proxy/redis_keys.py:89-91`) has **one** reference in the
+non-test tree — a `delete` at `input/manager.py:1797` — and no writer and no
+reader. It is an input-side key about the channel's own ffmpeg, it appears on
+no payload, and it is dead in the Python relay already; 2d deletes it with
+the rest. Second, A6.6's eight-second `delay_moov` floor **does not apply to
+an Output Profile transcode**: its output is `-f mpegts`, not fragmented MP4,
+so it produces bytes as soon as it has input. Measured on ffmpeg 9.0.1: four
+chunks out of the same eight-second asset in 0.3 seconds.
+
 ## Stage 2d — cutover, and its trap
 
 **The historical bug this stage exists to not repeat.** Every live-bound nginx location today carries
@@ -2692,6 +2782,7 @@ Filled in as PRs merge; this spec lands as its own PR 0.
 | 2c-4 -- the Go relay's ffmpeg source: `relay/ffmpeg`'s spawn (`os/exec` + `SysProcAttr{Setpgid, Pdeathsig}`, D5 exception 1), the `log_parsers.py` port and the clock-injected buffering detector, `relay/channel`'s `TranscodeSource` and the package-private `attachable` seam, Amendment A4.1 (Django builds `stream_profile.argv`; no Go word splitter), the Go credential-logging guard `relay/internal/credlint` (#283) plus its `scripts/check_go_credential_logging.sh`, and the seven ffmpeg-derived fields on `GET /proxy/relay/channels`. Parity matrix rows 4 (real-ffmpeg), 5, 28 and 29 get a Go column (Amendment A4.4). Two Python-relay defects found and filed rather than fixed, per D10: the provider-URL INFO leak through ffmpeg's stderr preamble ([#295](https://github.com/D10Scot/Dispatcharr/issues/295)) and the UDP filter's dangling flag ([#296](https://github.com/D10Scot/Dispatcharr/issues/296)). CI fix round (2026-09-14): golangci-lint's darwin/linux build-tag blind spot fixed, the fixture-vs-migration-seed argv mismatch fixed, and row 4's real-ffmpeg pin moved onto the base image's production ffmpeg after both relays' shared `frame=` progress gate was found structurally blind to ffmpeg 6.x, filed rather than fixed as [#299](https://github.com/D10Scot/Dispatcharr/issues/299) (Amendment A4.7). | `migration/phase2c-ffmpeg` | pending |
 | 2c-5 -- the Go relay's failover: the three triggers (rows 1, 2, 3) as one port of `StreamManager.run`'s two loops, a clean EOF ported as a retried connection failure (R1); the control-plane client's `release` and `events` routes and an emitter that batches and logs an outage once (R12); the degraded fallback to the candidate list cached at channel start, never on a refusal (R2); the Redirect Stream Profile architecture -- the 302, the provider probe, the fall-through to the cached alternates, the internal-principal override, publishing no channel (R7, R8); the health flag, the keepalives, the client timeout and the error packet closing Amendment A2.5 (R14, R15); the five events the failover machinery raises (R11). Parity matrix rows 1, 2, 3 and 6 get a Go column; row 7 gains a pin across a switch. A pre-existing Python defect (one `next-source` call per buffering progress record when no alternate exists) reproduced per D5 and filed as [#302](https://github.com/D10Scot/Dispatcharr/issues/302) (R6). | `migration/phase2c-failover` | pending |
 | 2c-6 -- the Go relay's fMP4 output format (`migration/phase2c-fmp4`). One remux per channel reading the shared ring on `pipe:0`, the init segment replayed to every client, a refcounted lifecycle with no shutdown delay, and parity-matrix row 12 ([#222](https://github.com/D10Scot/Dispatcharr/issues/222)) reproduced, pinned and filed rather than fixed. Row 12 gets its Go pin. Amendment A6. [#304](https://github.com/D10Scot/Dispatcharr/issues/304) (a pre-existing 2c-4 defect, the stderr pipe truncated by a reap racing its drain) fixed in `relay/ffmpeg/spawn.go`, repairing `relay/channel/source_transcode.go` without editing it. Two Python-side findings from the port, reproduced and filed rather than fixed: the fMP4 scanner's resynchronisation arm discarding the whole working buffer ([#306](https://github.com/D10Scot/Dispatcharr/issues/306)) and the dead stop-during-restart guard in `_handle_bsf_error` ([#307](https://github.com/D10Scot/Dispatcharr/issues/307)). Three plan corrections found and fixed in the plan document as committed, run rather than read: Task 4 Step 7's break-check rows 16-18 name tests defined in `relay/httpapi/fmp4_test.go`, Task 6's file, and had to run there rather than in Task 4; Task 1 Step 2's expected result for `TestEveryStderrLineSurvivesTheWaitThatPrecedesTheJoin` describes a runtime failure the package cannot yet produce, since the two `StartPiped` tests appended in the same step leave it uncompilable until Step 3's implementation lands; and the issue-number-placeholder slot count was corrected from six to five (an instruction about the slots had been counted as one) with Task 8 Step 5's own verification grep narrowed to the paths that can carry a real slot, since run unscoped over all of `docs/` it could never return empty. | `migration/phase2c-fmp4` | pending |
+- **2c-7 — the Go relay's Output Profiles** (`migration/phase2c-output-profile`). One transcode per active `(channel, profile)` pair reading the channel's shared ring on `pipe:0` and writing a second in-process MPEG-TS ring, shared by every client on that profile; an fMP4 client on a profile runs it and 2c-6's remux chained, under `mpegts:p<id>` and `fmp4:p<id>`. Parity-matrix row 11 gets its Go pin, counted in spawns. The contract gained a null `argv` so a broken Output Profile can be told from a deactivated one. Amendment A7.
 
 ## Risks
 
```

### Appendix T — `CLAUDE.md`, one sentence

§ Video path's Output Profile sentence gains the Go half. **Note it is APPENDED to the existing parenthetical rather than replacing the paragraph**: that paragraph already gained a 2c-6 sentence about fMP4, and a replacement written against the older text would silently drop it.

**`CLAUDE.md`**

```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index a38fc18b..31609244 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -80,7 +80,7 @@ Django 6 + DRF, React 19 SPA same-origin, Celery, Redis for broker/cache/channel
 
 **State.** PostgreSQL holds durable rows — including settings, but **`CoreSettings` is one row per settings *group*, not per setting**: `key` unique, `value` a `JSONField`, eight groups (`core/models.py:201-208`). Every group is instance-wide, so there is no scoped settings write — treat any as blast radius (E2E allowlists them; see `docs/adr/0003`). `epg_settings` has no seeding migration, so POST it before you can PATCH it. Redis holds ownership leases, channel metadata, client sets, counters and switch requests (TTL'd), **the video bytes** in a ring buffer (**~256 KB chunks** — `input/buffer.py`'s `target_chunk_size` reads `ConfigHelper.get('BUFFER_CHUNK_SIZE', TS_PACKET_SIZE * 5644)`, but `ConfigHelper.get` is `getattr(Config, name, default)` and `BaseConfig.BUFFER_CHUNK_SIZE` **exists**, at `apps/proxy/config.py:15`, as `188 * 1361` = 255,868 bytes, so the `5644` literal is an unreachable default and the effective chunk is a quarter of what it looks like; at a 54 KB/s trickle a chunk takes ~4.7s to roll, not ~20s — 60s TTL), `live:events:*` pub/sub, plus Celery broker / Channels layer / Django cache. All share **DB 0**, so video memory pressure takes out the task queue and cache. `scripts/wait_for_redis.py` is wait-only — it never flushes, in any role. AIO's Redis starts empty because supervisord runs it non-persistent (`--save "" --appendonly no`), not because anything wipes it, so a control-plane restart leaves a running relay's keys untouched. Since Phase 2 stage 2c-2, the Go relay's ring is a per-channel in-process buffer, not Redis-backed: a 300-chunk / 76,760,400-byte cap and the same 60-second retention as the Python relay, whichever binds first, sized from `BUFFER_CHUNK_SIZE` on the `next-source` answer (Amendment A1.4) rather than from a Go-side constant. Since stage 2c-3, the Go relay's client registry is likewise a map in process memory with no TTL, no heartbeat and no ghost sweep, because with one process a client entry cannot outlive the goroutine that made it; `GET /proxy/relay/channels[?clients=all]` is served from it and performs no write. Since 2c-4 the Go relay serves the FFmpeg/VLC/Streamlink architecture too: Django builds the argv (`StreamProfile.build_command`) and sends it as `stream_profile.argv` (Amendment A4.1); the relay spawns it with `Setpgid` and, on Linux, `Pdeathsig SIGKILL`, kills with SIGKILL, parses stderr with `relay/ffmpeg`'s port of `log_parsers.py`, and ends the tune with `ErrBufferingTimeout` until 2c-5 wires failover. Since 2c-5 the Go relay fails over: the three triggers drive one port of `StreamManager.run`'s loops (`relay/channel/channel.go`), a clean EOF is a retried connection failure, the buffering-triggered switch bypasses `MAX_STREAM_SWITCHES` as in Python (row 6), the degraded fallback reads the candidate list the initial `next-source` answer carried and never a Redis key, a Redirect channel is a 302 with no channel published, and `GET /proxy/relay/channels` carries `healthy`.
 
-**Video path.** Three locked built-in **Stream Profiles** = three architectures: *Redirect* (302 to provider — no bytes through us, no failover after connect), *Proxy* (raw HTTP into the ring buffer, no subprocess, dead-air failover only), *FFmpeg/VLC/Streamlink* (spawn, read stdout, parse stderr, full failover). Default FFmpeg profile is a remux, not a transcode. **Do not confuse Stream Profile (upstream) with Output Profile** (optional downstream transcode reading the shared buffer on `pipe:0`, shared per `(channel, profile)` clusterwide — ten AC3 clients cost one ffmpeg). **There is no HLS output**: `_OUTPUT_FORMAT_MANAGERS` registers only `fmp4`, MPEG-TS (default) uses no output-side ffmpeg, and the 1,206-line `apps/proxy/hls_proxy/` is dead. Since Phase 2 stage 2c-6 the Go relay serves fMP4 too, from `relay/output`: one remux per channel spawned by the first fMP4 client and stopped by the last, reading the channel's shared ring on `pipe:0` and writing a second in-process buffer of whole fragments (`buffer.Fragments`, not `buffer.Ring` — the write unit is a variable-length fragment and the client-positioning rules differ), so an fMP4 channel costs roughly twice a TS-only channel's resident memory. It refuses any other format 501, as `hls` has no manager on either side. HLS *upstreams* are handled by forcing the ffmpeg profile.
+**Video path.** Three locked built-in **Stream Profiles** = three architectures: *Redirect* (302 to provider — no bytes through us, no failover after connect), *Proxy* (raw HTTP into the ring buffer, no subprocess, dead-air failover only), *FFmpeg/VLC/Streamlink* (spawn, read stdout, parse stderr, full failover). Default FFmpeg profile is a remux, not a transcode. **Do not confuse Stream Profile (upstream) with Output Profile** (optional downstream transcode reading the shared buffer on `pipe:0`, shared per `(channel, profile)` clusterwide — ten AC3 clients cost one ffmpeg). Since Phase 2 stage 2c-7 the Go relay serves them too, from `relay/output`: one transcode per pair, started by the first client on that profile and stopped by the last with no shutdown delay, writing a second in-process `buffer.Ring` its clients read instead of the channel's. Its argv is `output_profiles[*].argv` off the `next-source` answer, cached per channel and refreshed by every later answer a non-degraded failover receives (an edit mid-channel reaches new clients only after the next one, where Python re-reads the row per client), and an entry with a **null** argv is Django saying `shlex` refused that profile's parameters — a 500 for the client that selects it, where a profile merely absent from the map was deactivated and that client is served with no profile at all. An fMP4 client on a profile runs **two** chained processes, `mpegts:p<id>` then `fmp4:p<id>`, exactly as `views.py:765-792` composes them. **There is no HLS output**: `_OUTPUT_FORMAT_MANAGERS` registers only `fmp4`, MPEG-TS (default) uses no output-side ffmpeg, and the 1,206-line `apps/proxy/hls_proxy/` is dead. Since Phase 2 stage 2c-6 the Go relay serves fMP4 too, from `relay/output`: one remux per channel spawned by the first fMP4 client and stopped by the last, reading the channel's shared ring on `pipe:0` and writing a second in-process buffer of whole fragments (`buffer.Fragments`, not `buffer.Ring` — the write unit is a variable-length fragment and the client-positioning rules differ), so an fMP4 channel costs roughly twice a TS-only channel's resident memory. It refuses any other format 501, as `hls` has no manager on either side. HLS *upstreams* are handled by forcing the ffmpeg profile.
 
 One uWSGI worker owns a channel's upstream, elected by `redis.set("live:channel:{id}:owner", worker_id, nx=True, ex=30)` (`live_proxy/server.py`); followers serve their own clients from the same keys and ask the owner to act over `live:events:{id}`. `_ensure_owner_or_stop()` runs each main-loop iteration. `input/buffer.py` realigns to 188-byte TS packets before writing chunks. **The chunk index is monotonic for the channel's life, never reset by a stream switch** — why a switch doesn't touch clients; new clients start ~5s behind live via the timestamp zset.
 
```
