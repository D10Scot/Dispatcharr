# Phase 2 PR 2c-4 — the Go relay's ffmpeg source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Go relay serve the **FFmpeg, VLC and Streamlink stream-profile architectures**: a transcode profile's command line is spawned as a subprocess in its own process group that dies with the relay, its fd 1 is the video, its fd 2 is parsed line by line with a port of `apps/proxy/live_proxy/services/log_parsers.py`, the parsed stream info and ffmpeg's `speed=` reach the status payload, and the buffering detector arms exactly as slowly as ffmpeg's cumulative average makes it — pinned by a real ffmpeg, which is parity-matrix row 4. Plus the contract change that lets the relay carry no shell word splitter (Amendment A4.1), and the Go credential-logging guard #283 asked for, because ffmpeg's argv and stderr both carry the provider URL.

**Architecture:** 2c-3's manager, ring, registry and `promoteOnFirstChunk` are untouched. `ffmpeg` (the 2c-1 stub) gets the spawn, the parsers and the detector. `channel` gets a second `Source`, `TranscodeSource`, beside `ProxySource`, plus the stats a transcode process reports and a package-private seam through which a source is handed the channel it runs on. `httpapi`'s tune path grows two branches — a transcode profile, and a Proxy profile whose URL forces ffmpeg — and the list payload gains the seven ffmpeg-derived fields. A new package, `redact`, is the module's one redactor, and `internal/credlint` is the type-aware check that every error reaching a log went through it. One Python change: Django builds each source's argv with `StreamProfile.build_command` and sends it, so the Go side spawns byte for byte what the Python relay spawns.

**This PR stays inert in every deployment**: every route is behind 2c-1's dev flag, and nginx routes nothing to port 5658 until stage 2d.

**Tech Stack:** Go 1.27.1, standard library only (`os/exec`, `syscall`, `go/types` for the guard); Django on the one Python task.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — D5 and its first exception, the 2c-4 row of the nine-PR table (~line 1803), Amendments A1.2–A1.4 (~1853–1885), A2 (2c-2) and A3 (2c-3). This plan amends the spec in Task 10 where its text is factually wrong, and says so in the Done log.

---

## Sequencing: this plan sits on 2c-3, which is not yet merged

2c-3's plan is on `main` at `c1763e00` (PR #287, `docs/superpowers/plans/2026-09-13-phase2-2c3-fanout.md`; read it with `git show "c1763e00:docs/superpowers/plans/2026-09-13-phase2-2c3-fanout.md"`), being implemented in parallel on `migration/phase2c-fanout`. **This plan was built and verified on `81d41975` (2c-2 as merged) with 2c-3's appendices B–K applied by hand and its prose edits (Tasks 1, 2, 3, 5, 6, 8) applied from their descriptions** — the manager's `Started`/`Attach(id, *Client, start)` shape, the client registry, `Tuning.ShutdownDelay`, `Ring.TotalBytes`/`MaxChunksPerRead`, `identify`, the list endpoint and its golden, `ControlPlaneConfig.Delay`. That reconstruction passed 2c-3's own tests and 2c-2's unchanged, three times under `-race`, at 0 lint findings, before a line of 2c-4 was written.

**It is a reconstruction, and Task 0 is the diff.** Every appendix here was verified against the reconstruction, not against the tree 2c-3 actually merges; the orchestrator fills `<2C3_MERGED_SHA>` in Task 0, and a symbol that differs from the ledger below is a **stop-and-report**, never a reconciliation in passing. Three shapes this plan depends on most, with what changes if 2c-3 landed them differently:

| 2c-3 shape this plan builds on | Where 2c-4 touches it | If your tree differs |
|---|---|---|
| `Manager.Attach(id string, client *Client, start func() (Started, error))`, `Started{Source, Tuning, Info}` | `startTune` returns a `Started` whose `Source` is now one of two types; `channel.run` gains three lines before `source.Run` | a different `Started` shape moves Task 6 Step 3 and Task 7 Step 2 — stop and report |
| `httpapi.identify`, `ErrUnsupportedOutput`, `writeTuneFailure`'s arms, `ControlDeps`, `ChannelsHandler`/`describeChannel`, `golden_test.go`'s `goldenPayload` and `TestTheLiveEndpointProducesTheGoldensKeySet`, the rig's `fanRig`/`tuneAs`/`listChannels`/`waitForHead`/`packetRun` | Task 7 adds arms, fields and a transcode rig on top of all of them | a renamed helper is a find-and-replace in Appendix Q; a missing one is a stop |
| `relaytest.ControlPlaneConfig{SourceURL, Kind, Settings, Status, FailFirst, RedirectTo, Body, Delay}` and `EffectiveProxySettings()` | Task 5 adds seven fields and a `SetSettings`; the effective settings gain `DEFAULT_USER_AGENT` | Appendix J is the whole file as it stands after 2c-4; diff it against yours rather than applying it blind |

**Ruled, and binding on every task below: 2c-4 adds no second first-chunk watcher and no second promotion mechanism.** `promoteOnFirstChunk` stays the only place `waiting_for_clients` becomes `active`. The one new write of `StateActive` this PR adds — the buffering **recovery** edge in `stats.go`'s `reportBuffering` — is guarded by `c.state == StateBuffering` and can never promote a channel that has not already been active. Task 0 Step 2a's count therefore moves from **one to two**, and the second line is named there. Break-check 10 shows that removing that guard reddens nothing, which is recorded rather than hidden: the guard is a design rule (§ Sequencing of the 2c-3 plan), not a tested property.

**Seed your scratch module from the merged tree INCLUDING its `_test.go` files, never from a plan's appendices** — 2c-3's rule, unchanged, and the reason this plan's own reconstruction is called one.

---

## Global Constraints

Every task's requirements implicitly include this section. Constraints 1–20 are 2c-1's, 2c-2's and 2c-3's, restated because this plan is executed by an agent who has not read them; 21–26 are new.

1. **Anchor every command with an absolute path, or open it with a `cd` into your own worktree.** The shell's working directory has been observed drifting into another agent's worktree with no `cd` issued. A relative path that resolves somewhere else does not error; it writes a plausible file in the wrong tree.

2. **`go test -race` is mandatory on every Go test run: locally, in the hook, in the commit gate, in CI.** This PR adds the first goroutine that reads a subprocess's stderr while another copies its stdout, and a detector both of them touch.

3. **Standard library only. No `require` line, no `go.sum`, ever.** `scripts/check_go_stdlib_only.sh` is the mechanical check. Everything here is in `os/exec`, `syscall`, `regexp`, `bufio`, `go/ast`, `go/types`, `go/importer`, `net/http/httptest`, `sync`, `context`, `time` and `log/slog`. **`go/importer`'s `"gc"` mode resolves standard packages from the toolchain's export data in about a hundred milliseconds on Go 1.27.1 — measured; it is what makes a stdlib-only type-aware linter viable.** If a task appears to need a dependency, stop and report.

4. **Nothing in `relay/` may open a Postgres connection or a Redis connection, in any task, including a test.** This PR spawns processes; none of them is a database.

5. **Every pin is tool-resolved on the day the PR is opened, never copied from this plan.** This PR adds no new action pin. It adds one `apt-get install` step to `go-tests.yml` (Task 8), which is not a pin.

6. **zizmor blocks on every finding in any workflow file you touch.** This PR touches `go-tests.yml` — two steps and a pattern. The edited file was linted clean with zizmor 1.29.0 offline while this plan was written; re-run it on yours.

7. **Do not add a Docker `HEALTHCHECK`, a SIGTERM drain, or a `/readyz` that reports anything real.** Those are 2c-8's.

8. **Every Go constant that mirrors a Python literal carries its source `file:line` in a comment and is pinned by a test naming the same location.** This PR adds two: `ffmpeg.KillWait` (500 ms, `input/manager.py:1746`) and `TranscodeSource`'s 8192 read size (`apps/proxy/config.py:7`), both pinned by `TestTranscodeSourceDefaultsMatchPython`. Every threshold comes off the wire (Constraint 13).

9. **Prefer `t.Setenv` over manual environment save/restore, and never run an environment-mutating test with `t.Parallel()`.** Every test that spawns the stand-in calls `t.Setenv(relaytest.StandInEnv, "1")`; none takes `t.Parallel()`.

10. **Only Task 4 (the Python side) and Task 7 Step 6 (regenerating the golden) need the shared `dispatcharr-testrunner` container.** Before either edit:

    ```bash
    docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
    ```

    If it is not your worktree, re-point it with `.claude/hooks/start-test-container.sh` — **after** checking nobody else is mid-task in the tree it currently holds (`docker ps`, and `stat -f '%Sm %N'` on that tree's recently-touched files; a modification younger than a few minutes means occupied). Every other task runs on the host.

11. **Stage and commit in separate Bash calls, and write commit messages to a file and use `-F`.**

12. **A provider URL is a credential and never reaches a log, an error message or a public response body.** This PR is the first where the URL sits in a subprocess's **argv** and comes back on its **stderr** — ffmpeg prints `Input #0, mpegts, from '<url>':` in its preamble and the HLS demuxer prints every segment URL it opens. Constraint 21 is the mechanical half; Ruling R8 is the design.

13. **A control-plane setting is read from the wire or the tune fails. Never from a Go-side default.** This PR adds three required keys — `buffering_speed`, `buffering_timeout`, `DEFAULT_USER_AGENT` — and the per-key test grows three subtests. **The two thresholds are read on every tune, Proxy tunes included**, so the per-key test cannot go green against a Proxy rig while a transcode tune silently defaults.

14. **Parity is against the code, not against the summary.** Every behavioural claim here carries a `file:line`. Five places where reading the source changed this plan: the parser is keyed on the **whole** command string, not its basename (`input/manager.py:797-803`); `_parse_ffmpeg_stats` drops the **whole** line when one captured number does not parse (`:1249`); the UDP filter drops values and **leaves their flags** (`:808-812`); `connecting` is set on **both** paths, not the transcode one (`:1905-1963`, correcting 2c-2's `state.go` comment); and `endswith('.m3u8')` runs over the whole URL, query string included (`utils.py:55`).

15. **Decide every lint finding in this plan, and re-lint after every `#nosec`.** This PR adds **two** `#nosec` — `G204` on the spawn (`ffmpeg/spawn.go`) and the `G204,G702` **pair** on credlint's `go list` call, where the taint rule fired only once the first was silenced, the same shape as 2c-1's `G304/G703` — one `#nosec G304` on the stand-in's fixture read (a test-support file that is not `_test.go`), and one `//nolint:errorlint` on a test asserting identity. Six other findings were **fixed rather than suppressed**: three `unused-parameter` trampolines, one `context-as-argument` order, one `noctx` (`exec.CommandContext` with `context.Background()`), and the G702 above.

16. **Run the four checks after every task, from the module root**, and treat any of the four failing as a stop:

    ```bash
    cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
    ```

    `gofmt -l .` must print nothing.

17. **An ordering bug is not a data race, and `-race` is silent on every one of them.** This PR's two most instructive defects were both false-reason passes on a test that could not have failed: a helper process that died of EPIPE before the mechanism under test was reached (twice, Ruling R6), and a kill test whose three-second bound let `os/exec`'s own fallback SIGKILL stand in for ours (break-check 8).

18. **One mechanism per invariant.** Break-check 10 is listed *because* it does not redden.

19. **The borrowed-slice contract is asserted, not enforced.** `TranscodeSource.Run` writes into the ring through `io.Writer` exactly as `ProxySource` does and holds no chunk; nothing here mutates one.

20. **Do not widen the endpoint.** `GET /proxy/relay/channels` gains seven **fields** and no route. The single-channel `GET`/`DELETE`, the client `DELETE` and `advance` are 2c-8's.

21. **Every error-typed argument to a formatting or logging call in `relay/` passes through `redact.Error`, or carries `// credential-logging: ok - <reason>` on a line the call spans or the line above it.** `scripts/check_go_credential_logging.sh` runs `relay/internal/credlint` and zero findings is a ratchet, in the PostToolUse hook and in `go-tests.yml`. A marker with no reason clears nothing. Ruling R7 states the rule's reach and its known gaps.

22. **Every line the stand-in writes to stderr came out of a real ffmpeg**, or is declared where it is written with the reason a real ffmpeg cannot be made to emit it — `harness/ffmpeg_stderr.py`'s rule, carried. This plan declares three such lines: an edited **output** resolution (Task 6), a VLC message (Task 6, because no VLC capture exists), and a **re-ordered** capture whose curve recovers (Task 6, because a real cumulative average never climbs back over a threshold it has crossed). **The corpus is read in place from `apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/`, never copied**; `relaytest.CorpusPath` resolves it from the source tree.

23. **The real-ffmpeg test fails rather than skips when `CI` is set and ffmpeg is absent.** A skip there would turn row 4's only real-ffmpeg pin into a test that is green because it never ran. `go-tests.yml` installs ffmpeg (Task 8); on a developer host without it the test skips and says so.

24. **`Pdeathsig` is Linux-only by build tag, and its pin runs on Linux.** `syscall.SysProcAttr` has no such field on darwin; the relay is built for Linux only (`docker/Dockerfile`'s `relay-builder` stage) and tested on both. `spawn_linux_test.go` runs in CI's Linux and, locally, in the repo's own Go image (Task 3 Step 6 has the command). `GOOS=linux go vet ./...` is part of Task 3's check so a darwin host still compiles the Linux half.

25. **The stand-in is the test binary re-executed, and the trampoline is one per package.** `relaytest.StandInCommand` builds the `(command, argv)` a fake control plane answers with; each package that spawns declares one `TestStandIn` returning at once unless `RELAY_STANDIN=1`. No Python stand-in, no second binary on `PATH`, nothing that could read as a second implementation of ffmpeg. Global Constraint 9's `t.Setenv` is what turns the re-executed binary into the stand-in, because the spawn passes `os.Environ()` exactly as `input/manager.py:839` passes `os.environ`.

26. **The `Pdeathsig` and SIGKILL tests assert a mechanism, not an outcome, and two shapes of outcome were measured to pass without it.** A child that has a write outstanding to a pipe its dead parent held dies of EPIPE (Go terminates a program on EPIPE to fd 1); a child that ignores SIGTERM still ends in `ErrExited{-9}` 500 ms later, because `os/exec.WaitDelay` sends its own SIGKILL. Task 3's tests are shaped around both — the child blocks on sleep alone, the parent reads the child's one write before announcing it, and the kill bound is half of `KillWait`. Do not loosen either.

### The six ways a Go test can be green and meaningless

Every test this PR adds is bound by all six, and every task that adds an assertion ends with a **break-check**: patch the defect in, watch the test go red *for the right reason*, revert. **A break-check that does not go red is a finding, not a formality** — three of this plan's own failed to redden on the first attempt (§ Break-check, rows 8, 17 and 20) and each changed the test.

1. **The tautological oracle — a test whose expected value is computed by the code under test cannot fail.** Every parser expectation in Appendix G is a literal, most of them lines from the captured corpus; `Round`'s expectations were produced by `python3 -c 'print(round(x, n))'`; the argv literals in the Python tests were derived by hand and confirmed against `shlex.split`, never written as `build_command(...)[1:]`. The golden for the list payload is rendered by **Django's** serializer.

2. **A pin that supplies the default pins nothing.** The detector test runs at threshold 2.0, not 1.0; the timeout tests at the API's maximum 10.0 (`core/serializers.py:96`) and 1 s; the threshold-snapshot test at the API's minimum 0.1 and then 10.0; the blank-user-agent test asserts the fixture's literal, not Go's transport default.

3. **A test can go hollow without changing.** Every break-check below names the edit and the expected failure text.

4. **A fixture that patches away the subject its docstring names.** The stand-in is a **real process** on the real spawn path; it replays a **real capture**. `relaytest.NewUpstream` and `NewControlPlane` are sinks and sources. The one thing a test reaches into is `channel.Stats()` and `State()`, which is what the payload renders.

5. **A substring assertion pins nothing when the string has more than one source.** `ErrBufferingTimeout`, `ErrInputFailed`, `ErrCommandIsAURL`, `*ErrExited`, `*ErrUnservedKind`, `*ErrProfileArgvAbsent`, `*ErrProfileUnbuildable`, `ErrNoFFmpegProfile` are all named. The two places this plan asserts on message text are both about what must **not** be in it — a credential — and the secret has exactly **one** source, the URL the test put in argv and the stand-in echoed back.

6. **A true positive for a false reason.** Ruling R6 is this plan's worked instance, twice over: a parent-death test that passed with the mechanism removed because the child died of something else. When a break-check reddens, read the message and confirm it names the mechanism.

### Working rules

- Run the four checks after every task (Global Constraint 16), then `scripts/check_go_credential_logging.sh relay` (Constraint 21).
- Stage and commit in separate Bash calls; write commit messages to a file and use `-F`.
- Every commit message ends with the attribution lines this session was given.
- **Every Go file in this plan has been built, vetted, race-tested three times and linted at zero findings before this plan was written**, in a scratch module seeded from `81d41975` plus 2c-3's appendices (§ Sequencing). The real-ffmpeg test ran on ffmpeg 9.0.1 (host) and the Linux-only test in the repo's Go 1.27.1 image, both ways. Where you find a discrepancy, your tree is the fact and this plan is the claim — **stop and report it** (Task 0 Step 0).

---

## Rulings

Decisions this plan makes that the spec leaves open, that 2c-3 left to its successor, or that the tree contradicts. Each is binding; each names what it was decided against.

### R1 — Django builds the argv and sends it as `stream_profile.argv`. The relay carries no shell word splitter and no substitution table. (Amendment A4.1)

Amendment A1.3 gives 2c-4 two options: implement POSIX word splitting matching `shlex.split` plus the three substitutions, differential-tested against Python; or extend the contract with a pre-split `stream_profile.argv_template`, as `output_profiles[*].argv` already is. **This plan rules for the contract extension, and goes one step further than the named alternative: Django sends the argv fully built — `StreamProfile.build_command(url, user_agent, pk)` with the command removed — not a template with placeholders.**

Three findings, from reading `core/models.py:137-160` and running `shlex.split` over the corpus, drove it:

- **A template is not enough.** `{channelId}` substitutes `str(channel_id)`, and the id Python passes is `channel.id` at `input/manager.py:791` — the **numeric pk** of whatever `get_stream_object(identifier)` returned. The Go relay knows the channel by UUID; the pk is on no contract field. A template would have needed a `channel_pk` field beside it. A built argv needs nothing.
- **Substitution happens per PART, after splitting** (`core/models.py:154-158`). A URL with a space, or a `$`, stays one argument. A Go port that substituted and then split, or split and then re-split a token, would diverge on exactly the URLs the M3U transform builds. The built argv has been through the one implementation.
- **The corpus has teeth.** `shlex.split` in POSIX mode with `comments=False`: `#standard{access=file,mux=ts,dst=-}` is one token (core/migrations/0019 and 0027's VLC profile); `--http-header User-Agent={userAgent}` substitutes inside a token (0011); `"a\"b\\c\$d"` keeps `\$` as two characters (double quotes escape only `\\` and `\"`); `title=a\ b` joins; `#` mid-line is not a comment; an unbalanced quote raises `ValueError: No closing quotation`. A Go implementation of all of that, differential-tested over a finite corpus, would be a second copy of the truth with a test that proves it agrees on the cases somebody thought of. **One implementation, on the side that already runs it, agrees on every case.** It is A1.4's argument applied to a different function: there is nothing left for Go to duplicate.

**What it costs, stated.** Django's side is in scope: one serializer field, `_stream_profile_ref` grows three keyword arguments, the locked-ffmpeg helper returns the row rather than the flattened dict (because the dict now differs per source URL), `get_stream_info_for_switch` adds one internal key, and the zero-ORM allowlist's `hits` for `resolve_source` moves by one flagged call site. Two existing tests that compare `ffmpeg_stream_profile` to an exact dict gain the key. The **wire** grows one additive key on an object two fields already render; `args` stays, because the Python relay's force-ffmpeg path reads it and D5 forbids removing what exists.

**Three states, and a Go client tells them apart by presence.** A list is the built argv (empty for Proxy and Redirect, whose `build_command` returns `[]`). JSON `null` is "shlex refused the parameters" — an unbalanced quote a row can already carry, which the Python relay meets only at spawn time inside a broad `except` that returns `False` and retries; the relay refuses **that profile** by name (503) rather than the whole answer. The key **absent** is a control plane older than this relay, reported as a contract mismatch (502) like an absent setting. `control.StreamProfileRef` carries `ArgvPresent` for exactly this, through a custom `UnmarshalJSON`, because `encoding/json` cannot tell null from absent for a plain slice.

**The user agent is defaulted the way the Python relay defaults it**, `user_agent or Config.DEFAULT_USER_AGENT` (`input/manager.py:73`), on the Django side when building and on the Go side for the UDP filter — off the wire, from `DEFAULT_USER_AGENT`, which A1.4 already put there.

### R2 — A buffering timeout ends the tune in 2c-4, with a named error, and 2c-5 replaces exactly one arm.

`_parse_ffmpeg_stats` calls `_try_next_stream()` when buffering has lasted longer than `buffering_timeout` (`input/manager.py:1178-1182`, parity-matrix row 1). 2c-4 has no failover to call. The same decision 2c-2 took for `ErrUpstreamIdle`, for the same reason: ending the source with `channel.ErrBufferingTimeout` is the honest shape, the channel goes to `error` carrying it, and a half-failover that looked like row 1 and was not would be worse. `stderrReader.progress`'s `TimedOut` arm is the one line 2c-5 replaces; `ffmpeg.Detector.Reset` is the successful-switch branch (`:1185-1186`), already there for it, called by nothing in 2c-4.

**Owed to 2c-5 with the events route**: the `channel_buffering` event (`:1217-1226`) and `channel_failover` (`:1195-1206`), and `healthy`. Recorded in Amendment A4.3.

### R3 — The buffering thresholds live on `Tuning` and the source reads them through the seam that hands it its channel. The source holds no copy.

The first draft of `TranscodeSource` carried `BufferingSpeed` and `BufferingTimeout` fields beside `channel.Tuning`'s. The first tests written against it **never armed**: the fields the tests set on `Tuning` were not the fields the detector read. That is the stale-duplicate shape 2c-2's R5 refused, found the way it always is, and it is the reason this ruling exists.

**Ruled: `Tuning` gains `BufferingSpeed` and `BufferingTimeout` (parity-matrix row 5 — snapshotted at `publish`, like the other four), `Channel.run` hands the source its channel through a package-private `attachable` interface before `source.Run`, and the detector is built from `s.channel.tuning`.** `httpapi.tuningFrom` reads both keys on every tune. A bare `TranscodeSource.Run` with no channel has zero thresholds — a speed no sample is below — and no test drives it that way; every transcode test goes through the manager.

### R4 — Row 4's Go pin drives a real ffmpeg, in CI too, and asserts the shape of the curve with a derived floor.

The spec's 2c-4 row says "its own real-ffmpeg test, mirroring 2a's harness". The Python pin **replays a capture** of the curve; a Go test that did the same would be the other half of the same pin, not a real-ffmpeg one. **Ruled: both halves.** `ffmpeg/detector_test.go` and `channel/source_transcode_test.go` replay the slow-trickle capture through the detector and through a real channel; `channel/source_transcode_real_test.go` spawns a real ffmpeg with the **production** parameters (`core/migrations/0003`'s `-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`, substituted) against an upstream paced to a quarter of the asset's own byte rate, the same shape as `scripts/capture_ffmpeg_stderr.py`'s slow-trickle run, and watches the detector arm.

**What it asserts is the shape** (CAPTURE.md's rule for the corpus, applied to a live curve): the first reported speed is above the threshold; buffering is never reported while the speed is at or above it; and arming takes at least `armingFloor` of wall clock after the first progress record. The floor's derivation is in the test's own comment — a media lead of L seconds against an upstream at rate r crosses 1.0 at t = L/(1−r) — with the measurements: on this host, ffmpeg 9.0.1, first speed **10.9x** and **10.8x**, armed **12.2 s** and **12.1 s** after the first record, two runs; the capture the Python pin replays (ffmpeg 8.1.2) crossed at 18–20 s of `elapsed=`. **Four seconds** is a floor an instantaneous-rate detector cannot reach — it would arm on the first record, half a second in — and sits well below every measurement. Widen it if a real ffmpeg ever arms slower; never lower it towards a measurement.

**The cost is about 21 s of wall clock per run**, with `testing.Short()` skipping it, and it is spent in CI on purpose: `go-tests.yml` installs the distribution's ffmpeg, and the test **fails** rather than skips when `CI` is set and none is found (Constraint 23). The distribution's version, not the Dispatcharr image's 8.1.2: the claim is about ffmpeg's cumulative average, which every version this project has met shares, and the test asserts no digit.

### R5 — The stand-in is the test binary re-executed, and the corpus is read in place.

2a-2's stand-in is a Python program installed on `PATH` as `ffmpeg`. The Go relay could spawn it unchanged, and this plan decided against it: a Go test that needs `python3` on the runner is a test that skips or fails for a reason unrelated to the relay, and a stand-in that lives in another language's test tree is one nobody running `go test` reads. **Ruled: `relaytest.RunStandIn` is the port, the test binary re-executed with `-test.run=^TestStandIn$ -- <flags>` is the process, and `relaytest.StandInCommand` is the `(command, argv)` a fake control plane answers with** — the shape `os/exec`'s own tests use. It keeps `standin.py`'s flags (`-i`, `--stderr-corpus`, `--stderr-interval`, `--stderr-loop`, `--exit-after-bytes`, `--exit-code`, `--dead-air-after-bytes`) and adds three the Python relay never needed: `--echo-argv`, `--ignore-sigterm`, `--stdin-probe`.

**The corpus is 2a-2's, read from `apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/` through `relaytest.CorpusPath`**, which locates the repository from its own source path. Two copies of a corpus that must never be hand-edited is one copy nobody remembers to regenerate; CAPTURE.md's rule — the digits are a timing measurement, only the shape is asserted — binds every Go test that opens it. `go-tests.yml`'s change detector fires on the fixtures directory for the same reason.

**And `select {}` is not an idle loop in a helper process.** With its stderr pump finished, a stand-in whose only goroutine blocked on an empty select was killed by the runtime — "fatal error: all goroutines are asleep - deadlock!" — on **stderr**, where the relay's reader took the message for a diagnostic line. Every idle in `standin.go` and the parent helper is a sleep loop, as `standin.py:196-197`'s is.

### R6 — D5's first exception is pinned on Linux, and the pin was wrong twice before it was right.

`TestAChildOfADeadRelayDiesWithIt` re-executes the test binary as a **relay** that spawns the stand-in through `ffmpeg.Start`, prints the child's pid and sleeps; the test SIGKILLs that parent and watches the child. Removing `Pdeathsig` must redden it. **It did not, twice**, and both times the child died of something that was not the mechanism:

1. The first helper copied `/dev/zero` into a stdout pipe nobody drained. When the parent died the pipe's read end closed, the child's next write got EPIPE, and **Go terminates a program on EPIPE to fd 1**. Green with `Pdeathsig` removed.
2. The second helper put the child in dead-air mode — one write, then sleep — and printed the pid at once. The child was still **starting** (state `R`, measured through `/proc/<pid>/stat` in the Go image) when the parent was killed, its first write hit the dead pipe, same exit. Green again, in 30 ms.

**Ruled: the parent reads the child's one write before announcing it**, so by the time the test acts the child has entered its sleep loop and will never write again, and only the kernel can end it. Against the repo's Go 1.27.1 image: **PASS** with `Pdeathsig`, **FAIL in 5.02 s** without it — `child 4357 outlived its dead parent by five seconds -- Pdeathsig is not set, and an ffmpeg blocked on a stalled upstream would hold its provider slot forever`. That is the defect `CLAUDE.md` § Operationally records, in the shape it actually takes: an ffmpeg blocked **reading** never writes and never sees EPIPE.

The same lesson closed break-check 8: `TestCancelKillsTheChildWithSIGKILL` allowed three seconds and stayed green with SIGTERM injected, because `os/exec.WaitDelay` sends its own SIGKILL 500 ms after a signal the child ignored. The bound is now **half of `KillWait`**: a SIGKILL is acted on in milliseconds, the fallback cannot fire before 500 ms, and 250 ms sits between the two mechanisms. Measured: 502 ms with SIGTERM injected, red.

### R7 — #283's guard is keyed on the error TYPE, lives in the module, and found a real leak on its first run.

The brief asks for the minimum: every `exec.Cmd` error, every stderr line echoing argv, and every log line pass through a redaction, with a mechanical check that fails on a wrapped `%w` of an error that can carry a URL. **Ruled: `relay/internal/credlint`, a `go/types`-aware `main` package run by `scripts/check_go_credential_logging.sh`, in the hook and in `go-tests.yml`.** The rule: in every non-test file, every argument of static type `error` handed to `fmt.Errorf` and its `Sprint`/`Fprint`/`Print` family, package `log`'s `Print`/`Fatal`/`Panic` family, or `log/slog`'s level functions and `*Logger` methods (and `slog.Any`), must be a direct call to `redact.Error`, or the call carries `// credential-logging: ok - <reason>` on a line it spans or the line above. A marker with no reason clears nothing — the Python check's rule, for the Python check's reason.

**Why the type and not the name.** A provider URL reaches a Go log through one door: an error that carries it. `net/http` wraps every client failure in a `*url.Error` whose `Error()` prints the whole URL and masks only userinfo. 2c-2's review found the leak at the one `*url.Error` site the human guard missed. A check blind to the variable's name and keyed on its type cannot miss the next one. **Strings are not checked**, and the Python check has the same limit; what a string can carry — an ffmpeg stderr line echoing the URL — is redacted by `redact.Line` at the one site such lines are logged, and `TestAProviderURLInStderrNeverReachesTheLog`, whose secret has exactly one source, is the guard for that door.

**Its first run over the module reported 18 sites.** Two were fixed with `redact.Error`: `control.Unavailable.Error()` formats the transport's `*url.Error` with `%v`, whose message carries the control-plane base URL — which `DISPATCHARR_INTERNAL_API_BASE_URL` may give with userinfo — and `control.attempt`'s `NewRequestWithContext` wrap. Sixteen took markers with reasons: `encoding/json` errors over settings values, `*fs.PathError`s over the secret **file's** path and fixture paths, the checker's own diagnostics. The existing `channel.withoutURL` moved to `redact.Error` so one function is the allowlist, and `channel.go`'s `"upstream failed"` and `writeTuneFailure`'s default arm now go through it.

**Known gaps, stated as the Python check states its three.** A composite literal storing an error in a field (`control.Unavailable{Err: err}`) is not a call and is not seen; the type's `Error()` method is, one hop later, which is where the real one was found. `errors.Join`, and an error stringified by hand and passed as a string, are invisible. The redactor allowlist is one full name; `TestTheRedactorIsExactlyRedactError` fails if a local function named `Error` is ever mistaken for it.

### R8 — `redact.Line` is structural: any URL becomes its scheme and host. And the Python relay's stderr logging is a credential leak, filed not fixed.

ffmpeg prints the URL it was given verbatim in `Input #0, mpegts, from '<url>':`, and the HLS demuxer prints **every segment URL it opens** — derived from the provider URL, same credentialled path, different tail. An exact-match strip of the URL the relay was given would leave the credential in every segment line. **Ruled: `redact.Line` replaces anything with a scheme by `scheme://host/[redacted]`**, keeping the host because it is what an operator needs to tell providers apart and it is not a credential. Every stderr line the transcode source logs goes through it, at every level.

**The Python relay logs those same lines at INFO, unredacted** (`input/manager.py:1094`: `logger.info(f"Stream info for channel {self.channel_id}: {content}")`, reached by the `Input #0` line through the `'input'` keyword at `:1093`), and `scripts/check_credential_logging.py` cannot see it because the variable is named `content`. That is the incident class `CLAUDE.md` § Known defects records at five other sites. **It is filed as an issue in Task 10, recorded in `CLAUDE.md`, and not fixed here**: it is a Python-relay edit inside a stage scoped to the Go one, and D10 keeps relay-internal Python edits out. The Go relay does not reproduce it; a log line is not streaming behaviour a client can observe, and D5's parity does not extend to leaking credentials.

### R9 — The seven ffmpeg-derived fields land on the list payload now, and `stream_type` was 2c-4's all along.

2c-3's `NOT_SERVED_BY_2C3` excuses nine fields; seven are ffmpeg-derived and one, `stream_type`, is attributed to "channel_service from the probed input format, 2c-5". Reading `log_parsers.py:64-76` and `channel_service.py:879`: the input format comes from the `Input #0, mpegts` line's `parse_input_format`, through `parse_and_store_stream_info`'s `stream_type` key, into `ChannelMetadataField.STREAM_TYPE`. **It is the parser's output and it is 2c-4's.** Ruled: `channelPayload` gains `video_codec`, `resolution`, `source_fps`, `ffmpeg_speed`, `audio_codec`, `audio_channels` and `stream_type`, each present only when a transcode process reported it (`channel_status.py:605-627` assigns each inside an `if`); the golden's populated channel gains all seven; `NOT_SERVED_BY_2C3` becomes `NOT_SERVED_YET` with two entries (`logo_id`, `healthy`); and `TestTheLiveEndpointProducesTheGoldensKeySet` drives a **transcode** tune, because a Proxy tune renders a payload seven keys short. `source_fps` is a float here and a string on the detail endpoint — row 14's asymmetry, 2c-8's.

**Every value is rounded the way Python stores it, at the moment it is applied** (`channel.Stats`'s comments carry each `file:line`), with `ffmpeg.Round` doing Python's `round()`: correctly rounded on the exact binary value, so `round(2.675, 2)` is `2.67` and `round(1.0005, 3)` is `1.0`, where a naive `math.Round(x*1000)/1000` gets the second wrong. Every expectation in `TestRoundMatchesPythonsRound` came from `python3`.

### R10 — `connecting` is not ported, and 2c-2's comment about it is corrected.

`state.go` at `81d41975` says "Connecting is set by the transcode path (2c-4)". It is not: `_set_waiting_for_clients` (`input/manager.py:1905-1963`) sets `connecting` on **both** paths, for the window after a connection is up and before the ring holds `INITIAL_BEHIND_CHUNKS` (4) chunks, and `promote_channel_when_buffer_ready` moves it on. That window belongs to the promotion machinery, whose one mechanism is `promoteOnFirstChunk` firing on the **first** chunk. Porting `connecting` would mean a second state-writer on the promotion path for a sub-second window nothing observes through the list endpoint. **Ruled: declared, never entered, comment corrected**; a later PR that wants it adds a transition rather than a constant.

### R11 — force-ffmpeg is decided at tune time from the URL; no locked ffmpeg profile is a 503; and the UDP filter's dangling flag is reproduced.

`input/manager.py:445-453` flips a Proxy channel to `transcode = True` with `force_ffmpeg` at connect time when `detect_stream_type(self.url)` is HLS, RTSP or UDP, and `_establish_transcode_connection` then uses the stored locked ffmpeg profile, falling back to the channel's own Proxy profile — whose `build_command` returns `[]`, so the spawn fails, retries three times and fails over. The URL is known at tune time here, so `startTune` decides then: `channel.NeedsFFmpeg(url)` on a Proxy kind takes `ffmpeg_stream_profile`, and a `null` one is `ErrNoFFmpegProfile`, answered 503 before anything is spawned. Same failed tune, reported by name.

The UDP filter (`:808-812`) drops every argument containing the user agent or `user-agent`/`user_agent` in any case, **and leaves the flags that introduced them**: `-headers 'User-Agent: X'` becomes a bare `-headers` whose value is now `-i`. That is Python's own defect, reproduced per D5 (`TestTheUDPFilterDropsUserAgentArguments` expects the dangling flag, and an earlier draft of that test expected it gone), and **filed as an issue in Task 10**. Note the Python filter also runs over `cmd[0]`, the command itself; that shape is not reproduced, because the command is not an argument.

### R12 — The stats flow through a package-private seam, and the recovery edge is guarded by state.

A `Source` has one method, and 2c-2's R6 keeps it that way for 2c-4's benefit. The transcode source needs to hand its channel parsed info, progress and the buffering edges. **Ruled: `channel.attachable`, an unexported interface with one unexported method, checked once in `Channel.run` before `source.Run`.** `*TranscodeSource` implements it; `ProxySource` has nothing to report and does not. Nothing outside the package can point a source at a channel it does not run on. `reportBuffering(true)` moves `initializing`/`waiting_for_clients`/`active` to `buffering`; `reportBuffering(false)` moves **only** `buffering` to `active`. Python's `hset` at `:1247` is unguarded; the guard is what keeps `promoteOnFirstChunk` the one promotion mechanism, and a channel that is stopping or errored stays so on both edges — a divergence in the safe direction.

### R13 — The kinds test narrows, and `ErrNotProxyKind` becomes `ErrUnservedKind`.

2c-2's `TestATuneRefusesAKindItDoesNotServe` iterates `redirect` and `transcode`. This PR serves `transcode`, so the test iterates `redirect` alone until 2c-5 serves that too, and the error whose name said "not Proxy" now says what is true.

---

## The 2c-3 dependency ledger

Every row was verified at the **reconstruction** this plan was built on (§ Sequencing), not at a merged SHA. **Task 0 re-checks every row against `<2C3_MERGED_SHA>`**, and a row that does not match is a stop.

| What this PR depends on | Expected shape | If your tree differs |
|---|---|---|
| Module `github.com/D10Scot/Dispatcharr/relay` at `relay/`, Go 1.27.1, no `go.sum` | 2c-1's | every import path moves |
| `buffer.Ring` with `Write`, `Read`, `Join`, `Wait`, `Head`, `TotalBytes`, `Close`, `Closed`; `buffer.TSPacketSize`, `ChunkBytes`, `MaxChunksPerRead` | 2c-2 + 2c-3 Task 1 | none of this PR's edits touch `buffer`; a missing `TotalBytes` breaks Appendix Q's golden test |
| `channel.Source` (one method), `ProxySource` with `ChunkSize`/`ConnectTimeout`/`ReadTimeout`/`Transport`, `ErrUpstreamIdle`, `ErrUpstreamStatus`, and `withoutURL` at `source_proxy.go` | 2c-2 | Task 1 moves `withoutURL` to `redact.Error`; Appendix N is the whole file after |
| `channel.Channel` with `id`, `ring`, `log`, `tuning`, `source SourceInfo`, `startedAt`, `mu`, `state`, `lastErr`, `clients map[string]*Client`, `cancel`, `done`; `run`, `promoteOnFirstChunk`, `setState`, `stop`, `Stats`-free | 2c-3 Appendix C | Task 6 adds `stats Stats` and three lines to `run`; Appendix M is the whole file after |
| `channel.Tuning{ChunkBytes, Retention, JoinBehind, ShutdownDelay}` | 2c-3 Task 2 Step 2 | Task 6 adds two fields |
| `channel.State` and its eight constants, `StateBuffering` never entered | 2c-2 | Task 6 enters it |
| `channel.Manager` with `Attach(id, *Client, start func() (Started, error))`, `Started{Source, Tuning, Info}`, `Snapshot`, `stopIfStillIdle` | 2c-3 Appendix D | **not edited by this PR**; a different `Started` is a stop |
| `channel/manager_test.go`'s `testTuning()` and `testClient(id)`, `concurrent_test.go`'s `sourceCounter`/`countingSource`/`waitForStart` | 2c-2 + 2c-3 Task 3 Step 2 | Appendix O declares none of them and calls `testTuning`/`testClient` |
| `control.StreamProfileRef{ID, Command, Args, Kind}`, `control.Source` with `StreamProfile` and **no** `FFmpegStreamProfile`, `NextSourceAnswer`, `Settings` with `Int`/`Float`/`Seconds`/`String`, `KindProxy`/`KindRedirect`/`KindTranscode` | 2c-2 | Task 5 adds `Argv`/`ArgvPresent`/`UnmarshalJSON` and `FFmpegStreamProfile`; Appendix K is the whole file after |
| `httpapi.StreamDeps{Secret, Channels, Control, Log, Now}`, `identify`, `mintClientID`, `peerAddress`, `startProxyTune(parent, client, id)`, `tuningFrom` with five keys, `writeTuneFailure`, `serveClient`, `writeChunks`, `ErrNotProxyKind`, `ErrNoSource`, `ErrUnsupportedOutput`, `OutputFormatMPEGTS`, `tuneBudget` | 2c-3 Appendix F | Task 7 renames one function and one error and adds branches, keys and arms; Appendix P is the whole file after |
| `httpapi.ControlDeps`, `ChannelsHandler`, `describeChannel`, `channelPayload` with sixteen fields, `clientPayload`, `RequireInternal`, `DefaultClientLimit` | 2c-3 Appendix G | Task 7 adds seven fields; Appendix P |
| `httpapi/golden_test.go`'s `goldenPayload`, `TestTheListPayloadMatchesDjangosSerializer`, `TestEveryOptionalFieldIsAbsentRatherThanNull`, `TestTheLiveEndpointProducesTheGoldensKeySet`, `keysOf`, `decodeGolden`; `testdata/channels_clients_all.json` | 2c-3 Appendix H/K | Task 7 edits the literal, one test's rig, and regenerates the JSON |
| `httpapi/stream_test.go`'s `testSecret`, `rigChunkBytes`, `rigBudgetBytes`, `rig`, `newRig`, `tune`, `TestATuneRefusesAKindItDoesNotServe`, `TestEveryProxySettingThisRelayReadsIsRequired`; `fanout_test.go`'s `rigAssetPackets`, `rigSettings`, `fanRig`, `fanRigWith`, `tuneAs`, `listChannels`, `waitForHead`, `packetRun` | 2c-2 + 2c-3 Appendix I | Appendix Q's `transcode_test.go` declares none of them; two of 2c-2's tests are edited |
| `relaytest.SyntheticTS`, `PacketIndex`, `AlignmentProblem`, `NominalByteRate`, `NewUpstream`/`Config{Payload, Status, Rate, StopAfterBytes, Abrupt, DeadAir}`, `NewControlPlane`/`ControlPlaneConfig{SourceURL, Kind, Settings, Status, FailFirst, RedirectTo, Body, Delay}`, `EffectiveProxySettings()` with `buffering_speed` **and** `buffering_timeout` already present | 2c-2 + 2c-3 Task 8 | Task 5 extends `ControlPlaneConfig`; Appendix J is the whole file after |
| `relay/ffmpeg/ffmpeg.go`, a doc-comment-only stub naming `os/exec` + `SysProcAttr{Setpgid, Pdeathsig}` and the splitter 2c-4 would write | 2c-1 | Task 2 replaces the comment; the splitter half of it is now wrong (R1) |
| `.claude/hooks/run-go-checks.sh` with build, vet, lint and `-race`, walking up for `go.mod`; `go-tests.yml` with `build`, `lint`, `go-result`, the stdlib step, and a change detector | 2c-1 | Task 8 adds one step to each and two entries to the pattern |
| Amendment **A3** in the spec, and rows 8, 10, 13 carrying Go references | 2c-3 Tasks 9 and 11 | Task 10 appends **A4** after A3; Task 9 edits rows 4, 5, 28 and 29 |

**Verified in this tree, not inherited:** everything with a `file:line` in this plan — `input/manager.py:1-160`, `:384-660`, `:700-960`, `:955-1280`, `:1400-1470`, `:1700-1910` and `:2041-2231` read in full; `services/log_parsers.py` in full; `services/channel_service.py:784-906`; `channel_status.py:433-627`; `utils.py:31-69`; `core/models.py:130-215`; `next_source.py:95-160`, `:242-368`, `:500-700` and `:812-1011`; `apps/proxy/serializers.py:12-91`; `apps/proxy/config.py` in full; `core/serializers.py:95-96`; `core/migrations/0003`, `0006`, `0007`, `0011`, `0019`, `0027`; `harness/README.md`, `ffmpeg_stderr.py`, `standin.py`, `process.py`, `CAPTURE.md`; `tests/test_manager_stderr_failover.py`, `manager_support.py`, `test_property_log_parsers.py`; `tests/zero_orm_allowlist.py:280-330`; `scripts/capture_ffmpeg_stderr.py`; `scripts/check_credential_logging.py:1-80`; `.golangci.yml`; `go-tests.yml`; `run-go-checks.sh`.

---

## File Structure

```
relay/redact/redact.go                    NEW  — Error (was channel.withoutURL) and Line
relay/redact/redact_test.go               NEW
relay/ffmpeg/ffmpeg.go                    EDIT — the stub's comment: the splitter half is withdrawn (R1)
relay/ffmpeg/parse.go                     NEW  — the log_parsers.py port: Info, Kind, Tool, CanParse, Parse, AutoParse
relay/ffmpeg/progress.go                  NEW  — the frame= record parser and Round
relay/ffmpeg/detector.go                  NEW  — the buffering state machine, clock-injected
relay/ffmpeg/spawn.go                     NEW  — Process: Start, Stdout, ReadStderr, Kill, Wait; ErrExited, ErrCommandIsAURL, KillWait
relay/ffmpeg/spawn_linux.go               NEW  — Setpgid + Pdeathsig
relay/ffmpeg/spawn_other.go               NEW  — Setpgid only
relay/ffmpeg/parse_test.go                NEW
relay/ffmpeg/format_test.go               NEW  — two formatting helpers the parse test uses
relay/ffmpeg/progress_test.go             NEW
relay/ffmpeg/detector_test.go             NEW
relay/ffmpeg/spawn_test.go                NEW  — the trampoline, seven spawn tests
relay/ffmpeg/spawn_linux_test.go          NEW  — the parent helper and the Pdeathsig pin
relay/ffmpeg/procgone_test.go             NEW  — one helper shared by the two files above
relay/internal/relaytest/corpus.go        NEW  — the Python fixtures, read in place
relay/internal/relaytest/standin.go       NEW  — RunStandIn, StandInCommand, StandInArgs
relay/internal/relaytest/controlplane.go  EDIT — Command/Argv/ArgvAbsent/ArgvNull/FFmpegProfile/UserAgent/BlankUserAgent, SetSettings, DEFAULT_USER_AGENT
relay/control/nextsource.go               EDIT — StreamProfileRef.Argv/ArgvPresent/UnmarshalJSON, Source.FFmpegStreamProfile, two redact.Error
relay/control/settings.go                 EDIT — three markers
relay/control/profile_test.go             NEW
relay/config/config.go                    EDIT — two markers
relay/channel/streamtype.go               NEW  — StreamTypeOf, NeedsFFmpeg
relay/channel/stats.go                    NEW  — Stats, Channel.Stats, reportInfo/reportProgress/reportBuffering
relay/channel/source_transcode.go         NEW  — TranscodeSource, stderrReader, ErrBufferingTimeout, ErrInputFailed
relay/channel/channel.go                  EDIT — stats field, attachable, run's three lines, redact.Error
relay/channel/tuning.go                   EDIT — BufferingSpeed, BufferingTimeout
relay/channel/state.go                    EDIT — the Connecting comment (R10)
relay/channel/source_proxy.go             EDIT — withoutURL deleted; redact.Error at four sites
relay/channel/streamtype_test.go          NEW
relay/channel/source_transcode_test.go    NEW  — the trampoline, fourteen tests
relay/channel/source_transcode_real_test.go NEW — row 4, real ffmpeg
relay/httpapi/stream.go                   EDIT — startTune, transcodeSource, three keys, four errors, five arms
relay/httpapi/channels.go                 EDIT — seven fields, one marker
relay/httpapi/golden_test.go              EDIT — the literal gains seven fields; the live test drives a transcode rig
relay/httpapi/stream_test.go              EDIT — the kinds test narrows; the per-key list grows by three
relay/httpapi/transcode_test.go           NEW  — the trampoline, the transcode rig, eleven tests
relay/httpapi/testdata/channels_clients_all.json  REGENERATED from Django
relay/internal/credlint/check.go          NEW  — the rule
relay/internal/credlint/main.go           NEW
relay/internal/credlint/check_test.go     NEW
relay/main.go                             EDIT — two markers
scripts/check_go_credential_logging.sh    NEW
.claude/hooks/run-go-checks.sh            EDIT — the credlint step
.github/workflows/go-tests.yml            EDIT — install ffmpeg; run the guard; two detector entries

                                          --- the Python half, Amendment A4.1 ---
apps/proxy/serializers.py                 EDIT — StreamProfileRefSerializer.argv
apps/proxy/next_source.py                 EDIT — _stream_profile_ref, _locked_ffmpeg_profile, _LockedFfmpegProfile, six call sites, one info key
apps/proxy/tests/test_stream_profile_argv.py   NEW
apps/proxy/tests/test_next_source_resolution.py  EDIT — one expected dict gains argv
apps/proxy/tests/test_next_source_api.py         EDIT — the same at the wire
apps/proxy/tests/test_relay_list_payload_golden.py  EDIT — seven fields in the fixture; NOT_SERVED_YET
apps/proxy/live_proxy/tests/zero_orm_allowlist.py   EDIT — two hits counts and a 2c-4 paragraph

                                          --- documents ---
docs/relay-parity-matrix.md               EDIT — rows 4, 5, 28 and 29 gain a Go reference
docs/superpowers/specs/2026-09-09-…-design.md   EDIT — Amendment A4, the 2c-4 and 2c-5 rows, a Done log row
CLAUDE.md                                 EDIT — § Test hooks, § Architecture, § Known defects (two new bullets)
```

Nothing under `core/`, `dispatcharr/`, `frontend/`, `e2e/` or `metrics/` is touched. `relay/buffer` and `relay/channel/manager.go` are not touched.

---

## Task 0: Diff the merged 2c-3 tree against this plan's expectations

**Nothing else is written until this task is done and reported.** The ledger above was verified against a reconstruction of 2c-3 (§ Sequencing); this task is the check that the tree 2c-3 merged **is** that shape.

- [ ] **Step 0: Seed from the MERGED SHA the orchestrator names**

  ```bash
  cd <your worktree> && git log --oneline -1 <2C3_MERGED_SHA>
  git diff --stat <2C3_MERGED_SHA> HEAD -- relay/
  ```

  `<2C3_MERGED_SHA>` is 2c-3 as merged onto `main`, filled in by the orchestrator. If it is empty when you read this, **stop**: this plan cannot be executed against a branch tip, for the reason the 2c-3 plan gives — the branch moved four times while that plan was written. Anything later than the merge SHA is a diff against it, and Step 2's table is the diff.

- [ ] **Step 1: Confirm the module, the toolchain, ffmpeg and Docker**

  ```bash
  cd <your worktree>/relay && cat go.mod && go version && golangci-lint --version && ls go.sum 2>&1
  ffmpeg -version | head -1
  docker images --format '{{.ID}} {{.Repository}}:{{.Tag}}' | grep golang
  ```

  Expect module `github.com/D10Scot/Dispatcharr/relay`, `go 1.27.1`, golangci-lint 2.13.2, **no `go.sum`**. ffmpeg on `PATH` is needed for Task 6's real-ffmpeg test (it skips loudly without one; **record the version**, this plan was verified on 9.0.1). A local `golang` image is needed for Task 3 Step 6, the Linux-only pin; the repo's relay-builder base is one (`docker/Dockerfile`).

- [ ] **Step 2: Confirm every symbol this PR calls by name**

  ```bash
  cd <your worktree>/relay && grep -rn "^func \|^type \|^const \|^var " \
    buffer/ring.go channel/channel.go channel/manager.go channel/source_proxy.go channel/tuning.go \
    channel/state.go channel/client.go control/settings.go control/nextsource.go httpapi/stream.go \
    httpapi/channels.go httpapi/server.go internal/relaytest/*.go ffmpeg/ffmpeg.go | sed 's/{$//'
  ```

  Against the ledger, check in particular:

  | Symbol | Expected shape | If it differs |
  |---|---|---|
  | `(*Manager).Attach` | `func (m *Manager) Attach(id string, client *Client, start func() (Started, error)) (*Channel, func(), error)` | Task 6 and 7 build `Started`; a different shape is a stop |
  | `Started` | `struct{ Source Source; Tuning Tuning; Info SourceInfo }` | same |
  | `(*Channel).run` | sets `StateWaitingForClients`, starts `promoteOnFirstChunk`, calls `source.Run(ctx, c.ring)`, three-arm switch | Task 6 inserts three lines before `setState`; Appendix M assumes this body |
  | `Channel` fields | `id, ring, log, tuning, source, startedAt, mu, state, lastErr, clients, cancel, done` | Task 6 adds `stats` after `lastErr` |
  | `Tuning` | four fields ending in `ShutdownDelay` | Task 6 adds two |
  | `withoutURL` | declared in `channel/source_proxy.go`, called at four sites there | Task 1 deletes it and calls `redact.Error`; a fifth call site elsewhere is a finding |
  | `startProxyTune` | `func startProxyTune(parent context.Context, client *control.Client, id string) (channel.Started, error)`, detaching with `context.WithoutCancel` | Task 7 renames it; the detach stays |
  | `tuningFrom` | five keys: `settingChunkBytes`, `settingRetention`, `settingJoinBehind`, `settingShutdownDelay`, `settingReadSize` | Task 7 adds three constants and two reads |
  | `channelPayload` | sixteen fields, `AvgBitrate` followed by `Clients` | Task 7 inserts seven between them |
  | `ControlPlaneConfig` | eight fields ending in `Delay time.Duration` | Task 5 adds seven; Appendix J is the file after |
  | `EffectiveProxySettings()` | carries `buffering_timeout: 15`, `buffering_speed: 1.0`, `channel_shutdown_delay: 0`, `BUFFER_CHUNK_SIZE: 255868`, `CHUNK_SIZE: 8192` | Task 5 adds `DEFAULT_USER_AGENT`; the two thresholds MUST already be there — 2c-2 typed the stored seven |
  | `ffmpeg/ffmpeg.go` | a package doc comment and nothing else | Task 2 replaces the comment; any code in it is a stop |
  | `TestATuneRefusesAKindItDoesNotServe` | iterates `[]string{control.KindRedirect, control.KindTranscode}` | Task 7 narrows it |
  | `TestEveryProxySettingThisRelayReadsIsRequired` | five keys in its list | Task 7 adds three |

- [ ] **Step 2a: Count the writers of `StateActive`, and know what the number will become**

  ```bash
  cd <your worktree>/relay && grep -rnE "state = StateActive|setState\(StateActive" --include='*.go' . | grep -v _test.go
  ```

  **Expect exactly one line at `<2C3_MERGED_SHA>`, `channel/channel.go`'s, inside `promoteOnFirstChunk`** — 2c-3's Task 12 Step 3a measured it. **After Task 6 the count is TWO**, and the second is `channel/stats.go`'s `c.state = StateActive` inside `reportBuffering`, under `case !on && c.state == StateBuffering`. That is the buffering **recovery** edge (`input/manager.py:1244-1247`), guarded so it can only fire on a channel that is already past promotion; it is not a second first-chunk mechanism (§ Sequencing). Task 11 Step 3a re-runs this grep and expects two, naming both.

- [ ] **Step 3: Confirm the Python side this PR edits is where the plan says**

  ```bash
  cd <your worktree> && grep -n '^def _stream_profile_ref\|^def _locked_ffmpeg_profile\|^def _source_from_info\|^def _resolve_alternates\|^def _commit\|^def resolve_initial_source\|^def resolve_source\|^def get_stream_info_for_switch\|_UNRESOLVED_FFMPEG_PROFILE = ' apps/proxy/next_source.py
  grep -n 'kind = serializers.CharField()' apps/proxy/serializers.py
  grep -n 'NOT_SERVED_BY_2C3' apps/proxy/tests/test_relay_list_payload_golden.py
  grep -n 'hits=' apps/proxy/live_proxy/tests/zero_orm_allowlist.py
  ```

  At `81d41975` the eight functions are at `:105`, `:125`, `:643`, `:673`, `:696`, `:500`, `:812` and `:242`, the sentinel above them, `kind` at `serializers.py:50`. The golden test file is 2c-3's (Appendix J of that plan); if it is absent, 2c-3 merged without it and Task 7 Step 6 is a stop. The two `resolve_source` entries carry `hits=38`.

- [ ] **Step 4: Confirm CI's shape before editing it**

  ```bash
  cd <your worktree> && grep -n "relay/\|check_go_stdlib_only\|Go result\|pattern=" .github/workflows/go-tests.yml
  grep -n 'golangci-lint run' .claude/hooks/run-go-checks.sh
  ```

  Task 8 adds one step after the stdlib assertion, one before the build, and two alternatives to the detector pattern; the hook gains one block before the lint block. If the file's shape has moved, Appendix S's diffs are applied by hand.

- [ ] **Step 5: Run the four checks and the corpus check on the tree as merged**

  ```bash
  cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
  ls -la ../apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/
  ```

  **A red tree here is a stop.** The three `.stderr` files and `CAPTURE.md` must be present: every parser and detector test reads them in place.

- [ ] **Step 6: Report**

  Every ledger row that did not match, and which task absorbs it. Do not start Task 1 until this is reported.

---
## Task 1: `relay/redact` — the module's one redactor

Ruling R7 needs an allowlist of one function, and Ruling R8 needs a line redactor. Both go in a package nothing else in the module can be confused with.

**Files:**
- Create: `relay/redact/redact.go`, `relay/redact/redact_test.go` (Appendices A, B)
- Modify: `relay/channel/source_proxy.go` — delete `withoutURL`, call `redact.Error` at its two sites and at the two `%w` wraps of `writeErr`/`readErr`; `relay/channel/channel.go` — `run`'s `"upstream failed"` log goes through `redact.Error`

**Interfaces:**
- Produces: `redact.Error(err error) error` (a `*url.Error` anywhere in the chain becomes its inner error; anything else is returned as it came); `redact.Line(s string) string` (every `scheme://…` becomes `scheme://host/[redacted]`); `redact.Placeholder`.

- [ ] **Step 1: Write the two files from Appendices A and B, and move `withoutURL`**

  `redact.Error` is `channel.withoutURL`'s body, moved, so 2c-2's two credential tests (`TestAConnectFailureNeverEchoesTheProviderURL`, `TestAMalformedSourceURLNeverEchoesTheProviderCredential`) keep passing against the same function under its new name. Delete the declaration from `source_proxy.go` (its doc comment says there is no Go equivalent of the Python script "yet"; Task 8 is the yet), replace the four sites, add the import. Appendix N is `source_proxy.go` in full afterwards.

- [ ] **Step 2: Run the tests**

  ```bash
  cd <your worktree>/relay && go test -race -count=1 ./redact ./channel
  ```

  `TestLineKeepsTheHostAndDropsEverythingElse` has six cases; the third is an HLS segment URL that is NOT the exact URL a relay was given, which is the whole reason `Line` is structural (R8).

- [ ] **Step 3: Break-check**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1a | `Error` returns `err` unchanged for a `*url.Error` | `TestErrorStripsTheURLOutOfAURLError`, and 2c-2's two channel tests | `the redacted error still carries "hunter2": …` |
  | 1b | `Line`'s replacement keeps `parsed.Path` | `TestLineKeepsTheHostAndDropsEverythingElse`, `TestLineNeverLeavesACredentialBehind` | `Line("…") … still carries "hunter2"` |

- [ ] **Step 4: Commit**

---

## Task 2: `relay/ffmpeg` — the parsers and the detector

The port of `log_parsers.py` (235 statements at 69% coverage — the spec's "highest-risk single port in the whole phase", § Risks), of `_parse_ffmpeg_stats`'s three regexes, and of its buffering decision as a clock-injected state machine.

**Files:**
- Create: `relay/ffmpeg/parse.go`, `progress.go`, `detector.go` (Appendices C, D, E); `parse_test.go`, `format_test.go`, `progress_test.go`, `detector_test.go` (Appendix G); `relay/internal/relaytest/corpus.go` (Appendix H)
- Modify: `relay/ffmpeg/ffmpeg.go` — replace 2c-1's stub comment with the one in Appendix C's header (its "2c-4 writes a splitter" paragraph is withdrawn by R1)

**Interfaces:**
- Produces: `ffmpeg.Info` (twelve pointer fields, one per `log_parsers.py` dict key), `Kind` and its seven constants, `Tool` and `ToolFor(command)`, `CanParse(tool, line) Kind`, `Parse(kind, line) (Info, bool)`, `AutoParse(line) (Kind, Info, bool)`; `Progress` (four pointer fields), `IsProgressLine`, `ParseProgress`, `Round(x, places)`; `Detector{Threshold, Timeout, Now}` with `Observe(speed) Verdict`, `Buffering()`, `Reset()`, and the five verdicts. `relaytest.CorpusNames`, `CorpusPath`, `Corpus`, `SplitCorpus`, `CorpusSpeeds`, `CorpusElapsed`.

- [ ] **Step 1: Write `relaytest/corpus.go` first**

  It reads the Python fixtures **in place** (Constraint 22) and locates the repository through `runtime.Caller` — four `Dir`s up from `relay/internal/relaytest/corpus.go` — because `go test` sets the cwd to the package directory, which is a different depth for every package that reads the corpus. In a scratch module outside the repo, symlink `apps/` beside `relay/` (this plan's own verification did) rather than copying a fixture.

- [ ] **Step 2: Write the three source files from the appendices**

  Five places the port follows the code and not the docstring, each with its citation in the source:
  - `ToolFor` lowercases the **whole** command and looks it up in a four-entry map (`input/manager.py:797-803`); `/usr/bin/ffmpeg` is unknown and falls to `AutoParse`.
  - `AutoParse` tries ffmpeg, vlc, streamlink in `LogParserFactory._parsers`' insertion order (`log_parsers.py:364-368`), and never reports `KindVLCInputFailed`: that kind parses to nothing, so `auto_parse` moves on (`:404-411`). Only direct routing sees it.
  - `ParseProgress` returns `false` for the **whole** line when a captured number fails to parse: `[0-9.]+` captures `1.2.3`, Python's `float()` raises, and the `except` at `:1249` swallows the line.
  - `speedRe` is `speed=\s*([0-9.]+)x?` and **stops at the `e`** — parity-matrix row 28, issue #227. Do not widen it.
  - The VLC codec maps are ordered slices, because Python iterates a dict and takes the first tuple with any matching pattern (`:199-204`, `:263-268`) — and `"avc"` is a substring of `"avcodec"`, so a VLC decoder line naming no codec is reported as `h264`. Verified against the Python parser before the test row was written; reproduced.

- [ ] **Step 3: Write the four test files from Appendix G and run them**

  ```bash
  cd <your worktree>/relay && go test -race -count=1 ./ffmpeg ./internal/relaytest
  ```

  `TestCanParseAndParseAgreeWithThePythonParsers` is a twenty-row table whose ffmpeg rows are **real lines** — four verbatim from the corpus preamble — and whose expectations are literals. `TestTheCorpusPreambleParsesAsPythonStoresIt` drives the whole `normal` preamble through the ffmpeg parser and compares the merged result to what the capture carries. `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` PINS A DEFECT (row 28) and asserts the wrong value on purpose. `TestRoundMatchesPythonsRound`'s nine expectations came from `python3 -c 'print(round(x, n))'`; write none of your own without running Python. `TestTheCapturedLeadIsNeverCalledBufferingBeforeItCrosses` is row 4's corpus half.

- [ ] **Step 4: Break-check, four edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | `detector.go`: `speed < d.Threshold` becomes `<=` | `TestTheDetectorFollowsPythonsTransitions` | `speed AT the threshold is not buffering (:1235's >=): got buffering started` |
  | 2 | `detector.go`: `> d.Timeout` becomes `>=` | the same test | `exactly the timeout later is NOT a timeout (:1178's strict >): got buffering timeout` |
  | 4 | `progress.go`: `speedRe` reads the exponent | `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` | `the parser reported the true speed …; #227 appears to have been fixed, which makes this row a parity CHANGE, not a pin` — **read the message**: on this plan's run it reddened one assertion EARLIER, on the guard that the capture still carries e-notation, because the widened regex is also what that guard reads. Both are the right mechanism |
  | — | `parse.go`: the VLC `vlcVideoCodecs` slice reordered | `TestCanParseAndParseAgreeWithThePythonParsers/vlc decoder video…` on the codec | not run; listed because it is the one place order is behaviour |

- [ ] **Step 5: Run the four checks and commit**

---

## Task 3: `relay/ffmpeg` — the spawn

D5's first exception, and the fd-for-fd contract of `input/manager.py:823-923`.

**Files:**
- Create: `relay/ffmpeg/spawn.go`, `spawn_linux.go`, `spawn_other.go` (Appendix F); `spawn_test.go`, `spawn_linux_test.go`, `procgone_test.go` (Appendix G); `relay/internal/relaytest/standin.go` (Appendix I)

**Interfaces:**
- Produces: `ffmpeg.Start(ctx, command, argv) (*Process, error)`; `(*Process).Stdout() io.Reader`, `PID()`, `ReadStderr(fn func(line string))`, `Kill()`, `Wait() error`; `ErrExited{Code}` (Python's `returncode`: the status, or minus the signal), `ErrCommandIsAURL`, `KillWait = 500ms`. `relaytest.StandInEnv`, `StandInCommand(args...) (command, argv)`, `StandInArgs()`, `RunStandIn(args) int`.

- [ ] **Step 1: Write `standin.go`**

  Ruling R5. The flags are `standin.py`'s plus `--echo-argv`, `--ignore-sigterm` and `--stdin-probe`. **Every idle is a sleep loop, never `select {}`** (R5's last paragraph — the runtime's deadlock detector writes to stderr, where the relay's reader lives). The fetch error goes through `redact.Error` (Constraint 21 applies to test-support files that are not `_test.go`).

- [ ] **Step 2: Write the three spawn files**

  The observable contract, fd for fd: stdin `/dev/null` (`os/exec`'s default for a nil `Stdin`; `POSIX_SPAWN_OPEN` of `/dev/null` at `:842`), stdout a pipe the caller reads (`:843`), stderr a pipe `ReadStderr` drains (`:844`), the environment inherited (`:839`), the executable resolved on `PATH` (`:836`'s `shutil.which`; `exec.LookPath`). What differs is the exception: `Setpgid` everywhere, `Pdeathsig: SIGKILL` on Linux, `Cancel` sending **SIGKILL to the group** (`:1743` sends SIGKILL, never SIGTERM), `WaitDelay = KillWait` (`:1746`'s half second).

  `ReadStderr` splits on **CR or LF, whichever comes first** (`:981-991`), flushes a buffer past 1 KiB with no terminator and no `frame=` (`:986-991`), skips empty lines (`:994-996`) and emits the remainder at EOF (`:1015-1021`). `Wait` closes the stdout pipe first (a child still writing gets EPIPE rather than blocking on a full pipe nobody drains), then reads the `ProcessState` rather than `exec`'s context error, so a process this package killed reports `ErrExited{-9}` and the caller, who holds the reason, decides.

  `Start` refuses a command containing `://` (`ErrCommandIsAURL`): `exec.Error` prints the command **name**, and that is the one shape `redact.Error` is not built to strip.

  `spawn_linux.go`'s comment states the one way `Pdeathsig` can fire early — it is delivered when the forking **thread** exits — and why it does not here: nothing in the module locks an OS thread.

- [ ] **Step 3: Write the tests and the trampoline**

  `TestStandIn` is five lines and returns at once unless `RELAY_STANDIN=1`. `standIn(ctx, t, args...)` sets the variable with `t.Setenv` and calls `Start` on `relaytest.StandInCommand(args...)`, so every test runs the real spawn path. `assetFile` writes `relaytest.SyntheticTS` to a temp file the stand-in reads with `-i`.

  | Test | What it pins |
  |---|---|
  | `TestStdoutIsTheChildsFd1Verbatim` | fd 1 is the video, byte for byte, and exit 0 after EOF is `nil` |
  | `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord` | for all three captures, the reader sees exactly `len(records)` progress lines — a count read off the corpus, not typed |
  | `TestALongUnterminatedLineIsFlushedWhileTheChildStillRuns` | the 1 KiB flush, asserted while the child is alive (dead-air), so EOF cannot be what delivered it |
  | `TestCancelKillsTheChildWithSIGKILL` | the child ignores SIGTERM; it dies within **`KillWait/2`** and reports `-9` (R6's second lesson) |
  | `TestTheChildsStdinIsDevNull` | the child reads EOF at once |
  | `TestWaitReportsTheChildsExitStatus` | 0, 1 and 3 |
  | `TestACommandThatIsAURLIsRefusedBeforeSpawning`, `TestAMissingExecutableFailsStartWithoutEchoingArgv` | the two `exec.Error` shapes, with a secret in argv that must not appear |
  | `TestAChildOfADeadRelayDiesWithIt` (Linux) | D5's exception, Ruling R6 |

- [ ] **Step 4: Run on the host**

  ```bash
  cd <your worktree>/relay && go test -race -count=1 ./ffmpeg && GOOS=linux go vet ./ffmpeg
  ```

  On darwin `spawn_linux_test.go` does not compile into the test binary; the `GOOS=linux go vet` is what proves it compiles at all.

- [ ] **Step 5: Break-check, three edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 8 | `spawn.go`: `Cancel` sends `SIGTERM` | `TestCancelKillsTheChildWithSIGKILL` | `the child took 502.16ms to die after cancel; a direct SIGKILL takes milliseconds, and 500ms is WaitDelay's own fallback kill after a signal the child ignored` |
  | 17 | `spawn.go`: `cr := bytes.IndexByte(buf, '\r')` becomes `cr := -1` | `TestReadStderrSplitsOnCROrLFAndSeesEveryRecord`, `normal` and `slow-trickle` subtests | `the reader saw 1 progress lines, the corpus holds 11 records -- the split lost or merged records`; `truncation` stays green, and should — it has no CR |
  | — | `spawn.go`: `Start` no longer refuses `://` | `TestACommandThatIsAURLIsRefusedBeforeSpawning` | not run |

  **Break-check 8 stayed green in this plan's first draft** (a three-second bound) and **17 was mis-applied** on the first attempt — the edit did not land and the unmodified tree passed. Confirm the edit is in the file before reading a green as a finding.

- [ ] **Step 6: Run the Linux-only pin in the repo's Go image, both ways**

  ```bash
  cd <your worktree> && IMG=$(docker images --format '{{.ID}} {{.Repository}}' | awk '$2=="golang"{print $1; exit}')
  docker run --rm -v "$PWD/relay:/work/relay" -v "$PWD/apps:/work/apps:ro" -w /work/relay -e GOFLAGS=-buildvcs=false "$IMG" \
    sh -c 'go test -race -count=1 -run TestAChildOfADeadRelayDiesWithIt -v ./ffmpeg'
  ```

  Then copy `relay/` to a scratch directory, remove `Pdeathsig: syscall.SIGKILL` from `spawn_linux.go`, and run the same command against the copy. **Expect `child <pid> outlived its dead parent by five seconds -- Pdeathsig is not set…` after 5.02 s.** If the broken copy passes, read Ruling R6 before touching the test: both false-reason passes it records took under 30 ms.

- [ ] **Step 7: Run the four checks and commit**

---

## Task 4: Amendment A4.1 — Django builds the argv

Ruling R1. **This is the one task that needs the shared container** (Global Constraint 10). Do the container check before the first edit.

**Files:**
- Modify: `apps/proxy/serializers.py` (Appendix T2), `apps/proxy/next_source.py` (Appendix T1 — replacement bodies and named one-line edits), `apps/proxy/tests/test_next_source_resolution.py`, `apps/proxy/tests/test_next_source_api.py`, `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` (Appendix T4)
- Create: `apps/proxy/tests/test_stream_profile_argv.py` (Appendix T3)

**Interfaces:**
- Produces, on the wire: `stream_profile.argv` and `ffmpeg_stream_profile.argv`, a list of strings or `null`, **always present**.

- [ ] **Step 1: The serializer field**

  After `kind` (`serializers.py:50`), Appendix T2's field: `ListField(child=CharField(allow_blank=True), allow_null=True)`, **not** `required=False` — presence is how the relay tells an unbuildable profile from an older Django (R1).

- [ ] **Step 2: `next_source.py`**

  Appendix T1, in order: replace `_stream_profile_ref` (the three keyword arguments and the `ValueError` branch); replace `_locked_ffmpeg_profile` (it returns the **row**); add `_LockedFfmpegProfile` below it; give `resolve_initial_source` its `locked_ffmpeg_profile` kwarg and change its two Source literals; add `'channel_pk': channel.id` to `get_stream_info_for_switch`'s dict; replace `_source_from_info`; the one-line wrap in `_resolve_alternates` and `_commit` (keeping `_resolve_alternates`'s **eager** `.get()`, which is the one query `test_an_unresolved_locked_ffmpeg_profile_is_resolved_once` counts); the holder in `resolve_source` and its four uses.

  **`pk` is what the Python relay passes** at `input/manager.py:791` — `channel.id`, the Channel's pk for a channel tune, the Stream's for a stream-hash preview — and `get_stream_info_for_switch` looks the channel up at `:259` already, so the key costs no query.

- [ ] **Step 3: The tests, and the two expectations that gain a key**

  Appendix T3 in full. Then the two exact-dict assertions Appendix T4 names gain `"argv": [...]` built by hand from the fixture's parameters and `source["url"]` — never `build_command(...)[1:]`.

  ```bash
  cd <your worktree> && python manage.py test apps.proxy.tests.test_stream_profile_argv apps.proxy.tests.test_next_source_resolution apps.proxy.tests.test_next_source_api apps.proxy.tests.test_next_source_edges apps.proxy.tests.test_redirect_transcode_flag
  ```

- [ ] **Step 4: The zero-ORM ratchet moves, and you record why**

  ```bash
  cd <your worktree> && python manage.py test apps.proxy.live_proxy.tests.test_zero_orm_reads
  ```

  `_stream_profile_ref` now calls `profile.build_command(...)`, a model-method name the scanner flags, at **one** site inside `resolve_source`'s reachable subtree. Expect both `resolve_source` EDGE entries to fail naming **39**; update `hits` on both and add a 2c-4 paragraph in the idiom of the 2c-1 one already there ("neither issues a query… the count moved because a flagged CALL SITE exists, which is the ratchet working"). `build_command` is pure (`core/models.py:137-160`, string work on a loaded row). **If the number is anything but 39, find the second site before writing it down.**

- [ ] **Step 5: Break-check, two edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | — | `_stream_profile_ref` substitutes BEFORE splitting (`shlex_split(parameters.replace(...))`) | `test_a_url_with_spaces_is_substituted_after_splitting_not_before` | the URL arrives as two arguments |
  | — | `argv = []` on `ValueError` | `test_unparseable_parameters_render_null_and_keep_the_rest` | `None != []` |

- [ ] **Step 6: Commit**

---

## Task 5: `relay/control` — argv presence, the ffmpeg profile, and the fake Django's knobs

**Files:**
- Modify: `relay/control/nextsource.go` (Appendix K — the file in full), `relay/control/settings.go` (three markers), `relay/config/config.go` (two markers), `relay/main.go` (two markers), `relay/internal/relaytest/controlplane.go` (Appendix J — the file in full)
- Create: `relay/control/profile_test.go` (Appendix K)

**Interfaces:**
- Produces: `StreamProfileRef.Argv []string`, `ArgvPresent bool`, `(*StreamProfileRef).UnmarshalJSON`; `Source.FFmpegStreamProfile *StreamProfileRef`. `relaytest.ControlPlaneConfig` gains `Command`, `Argv`, `ArgvAbsent`, `ArgvNull`, `FFmpegProfile *ProfileConfig`, `UserAgent`, `BlankUserAgent`; `(*ControlPlane).SetSettings(map[string]any)`; `EffectiveProxySettings()` gains `DEFAULT_USER_AGENT`.

- [ ] **Step 1: `nextsource.go`**

  The custom unmarshaller decodes into an alias plus a `json.RawMessage` for `argv`, then sets `ArgvPresent` from the raw's length and `Argv` from its content, with an explicit-`null` check. `Argv` is tagged `json:"-"` so the default encoder never writes it back. The two `redact.Error` calls are the two real findings credlint reported (R7): `Unavailable.Error()`'s `%v` of the transport error, and `attempt`'s request-build wrap.

- [ ] **Step 2: The markers**

  Appendix K, and the `config.go`/`main.go`/`settings.go` lines Appendix S lists. Every marker has a reason; `check_test.go` fails a bare one.

- [ ] **Step 3: `controlplane.go`**

  Appendix J. `SetSettings` swaps the settings **every later answer** carries, under the fake's own mutex, read in the handler under the same mutex — the row 5 test changes a setting between two tunes with it. The `profile` closure renders `stream_profile` and `ffmpeg_stream_profile` alike, with the three argv shapes.

- [ ] **Step 4: Run**

  ```bash
  cd <your worktree>/relay && go test -race -count=1 ./control ./internal/relaytest
  ```

  `TestArgvPresenceIsDecodedInAllThreeStates` has four rows, and the two that matter are the last two: `null` and absent decode to the same nil slice and a different `ArgvPresent`.

- [ ] **Step 5: Break-check**

  | # | The edit | Expected red |
  |---|---|---|
  | — | `UnmarshalJSON` sets `ArgvPresent = true` unconditionally | `TestArgvPresenceIsDecodedInAllThreeStates/absent…` |
  | 7 | (in Task 7) `transcodeSource` ignores `ArgvPresent` | `TestAnAbsentOrNullArgvFailsTheTuneBeforeAnythingIsSpawned/absent…`: `answered 503, want 502` |

- [ ] **Step 6: Commit**

---

## Task 6: `relay/channel` — the transcode source, the stats and the seam

**Files:**
- Create: `relay/channel/streamtype.go`, `stats.go`, `source_transcode.go` (Appendix L); `streamtype_test.go`, `source_transcode_test.go`, `source_transcode_real_test.go` (Appendix O)
- Modify: `relay/channel/channel.go` (Appendix M, in full), `tuning.go`, `state.go` (Appendix M)

**Interfaces:**
- Produces: `channel.TranscodeSource{Command, Argv, URL, UserAgent, ChunkSize, Now}` implementing `Source`; `ErrBufferingTimeout`, `ErrInputFailed`; `channel.Stats` (sixteen pointer fields) and `(*Channel).Stats()`; `Tuning.BufferingSpeed float64`, `Tuning.BufferingTimeout time.Duration`; `StreamTypeOf(url) string`, `NeedsFFmpeg(url) bool`. Package-private: `attachable`, `(*Channel).reportInfo/reportProgress/reportBuffering`.

- [ ] **Step 1: `tuning.go`, `state.go`, `channel.go`**

  Two fields on `Tuning` (R3). The `state.go` comment (R10). In `channel.go`: `stats Stats` after `lastErr`; the `attachable` interface; three lines at the top of `run` — `if a, ok := source.(attachable); ok { a.attach(c) }` — **before** `setState(StateWaitingForClients)` and before `promoteOnFirstChunk` starts; and `redact.Error(err)` on the `"upstream failed"` line. Nothing else in the file moves.

- [ ] **Step 2: `stats.go` and `streamtype.go`**

  `Stats` mirrors the metadata hash's stream-info and ffmpeg-performance fields, **rounded at apply time** the way Python stores them (each field's comment carries its `file:line`; R9). `reportInfo` has `hset` semantics: a nil field leaves the earlier value standing. `reportBuffering` is the guarded pair of edges (R12). `StreamTypeOf` is `detect_stream_type` (`utils.py:31-69`) read branch by branch — five answers, not the docstring's four, and `endswith('.m3u8')` over the whole URL.

- [ ] **Step 3: `source_transcode.go`**

  `Run` starts the process with `argv()` — the UDP filter, `input/manager.py:808-812`, dangling flags included (R11) — builds the detector from **`s.channel.tuning`** (R3), drains stderr on a goroutine through `stderrReader.line`, copies fd 1 into the sink on the calling goroutine, and on EOF gives the process `KillWait` to exit on its own before killing it (`waitOrKill`). The return arms, in order: a write error; the recorded cause (`fail` keeps the first); the parent's cancellation; nil for exit 0; `*ErrExited` otherwise.

  `stderrReader.line` is `_read_stderr`'s `frame=` gate, `_parse_ffmpeg_stats`, and `_log_stderr_content` in that order (`:993`, `:1102`, `:1031`): progress first, then phase tracking (`:1041-1045`), then routing — direct through `ToolFor` when the command is known (`:1054-1069`, where `KindVLCInputFailed` ends the source), `AutoParse` otherwise (`:1071-1072`) — then the input-phase gate for ffmpeg kinds (`:1079-1082`), then the log at Python's level, **through `redact.Line`** (R8). `progress` maps the five verdicts: `Started` logs and sets `buffering`; `Continuing` does nothing (Python re-writes a state that has not changed); `TimedOut` ends the source (R2); `Ended` clears.

- [ ] **Step 4: The tests**

  Appendix O. `TestStandIn` again (one per package, Constraint 25); `standInSource` sets the environment and builds the source; `transcodeTuning(speed, timeout)` is `testTuning()` plus the two thresholds, **never the defaults**; `captureLog` is a `slog` handler into a locked buffer.

  | Test | What it pins |
  |---|---|
  | `TestATranscodeProcessesFd1ReachesTheRingInOrder` | the child's fd 1 reaches the ring as whole packets in order; exit 0 stops the channel like a clean Proxy EOF |
  | `TestParsedStderrReachesTheChannelsStats` | the `normal` preamble and last record, rounded as stored, with `video_bitrate` absent because the corpus line has no kb/s |
  | `TestOutputPhaseStreamLinesDoNotOverwriteTheInputs` | the input-phase gate, with an edited output resolution (Constraint 22's first declared line) |
  | `TestTheCapturedLeadIsNeverLabelledBufferingBeforeItCrosses` | **row 4, corpus half**, state read before stats for the ordering reason in its comment |
  | `TestASustainedSubThresholdSpeedEndsTheSourceWithATimeout` | R2: `ErrBufferingTimeout`, after at least the timeout, at the API maximum threshold |
  | `TestBufferingEndsWhenTheSpeedRecovers` | the recovery edge, on a re-ordered capture (Constraint 22's third line) |
  | `TestAProviderURLInStderrNeverReachesTheLog` | **the secret has one source**, the host survives |
  | `TestAMissingCommandFailsTheChannelWithoutEchoingArgv` | an `exec.Error` names the executable and nothing from argv |
  | `TestTheUDPFilterDropsUserAgentArguments` | R11, dangling flag included |
  | `TestTheBuiltArgvIsSpawnedVerbatim` | what Django built is what the child received |
  | `TestANonZeroExitPutsTheChannelInError` | `ErrExited{3}` |
  | `TestAVLCInputFailureEndsTheSource` | direct routing through a symlink named `vlc` first on `PATH` — the Python harness's own trick (Constraint 22's second line) |
  | `TestStoppingTheChannelKillsTheChild` | a release kills a child that ignores SIGTERM |
  | `TestTranscodeSourceDefaultsMatchPython` | Constraint 8 |
  | `TestTheCumulativeLeadMustBurnOffBeforeTheDetectorArms` | **row 4, real ffmpeg** (R4) — ~21 s, skipped under `-short` |
  | `TestStreamTypeOfMatchesDetectStreamType` | sixteen URLs, two of them the whole-URL-versus-path distinction |

  ```bash
  cd <your worktree>/relay && go test -race -count=1 ./channel
  go test -race -count=1 -run TestTheCumulativeLeadMustBurnOffBeforeTheDetectorArms -v ./channel
  ```

  The second prints the ffmpeg version and `first speed …x; armed …s after the first record`. **Record both numbers in the PR description** beside this plan's (10.9x / 12.2 s and 10.8x / 12.1 s on ffmpeg 9.0.1).

- [ ] **Step 5: Break-check, eight edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 3 | `stderrReader.line`: `redacted := line` | `TestAProviderURLInStderrNeverReachesTheLog` | `the log carries "hunter2" from the provider URL` |
  | 5 | the `if r.inputPhase` gate dropped | `TestOutputPhaseStreamLinesDoNotOverwriteTheInputs` | `resolution = 999x999, want the INPUT's 320x180 -- the output phase's stream line overwrote it` |
  | 6 | `argv()` never filters | `TestTheUDPFilterDropsUserAgentArguments` | `UDP argv = [… "-user_agent" "VLC/3.0.20" …]` |
  | 10 | `reportBuffering`'s recovery arm unguarded (`case !on:`) | **expected NOT to redden**; measured green across the whole package. The guard keeps one promotion mechanism (§ Sequencing) and is a design rule, not a tested property. Report it, do not invent a test for it |
  | 12 | `Run` builds the detector from a literal `Tuning{BufferingSpeed: 10}` instead of `s.channel.tuning` | Task 7's `TestABufferingThresholdChangeDoesNotReachARunningChannel` | `the running channel picked up the new threshold` |
  | 14 | `reportInfo` returns at once | `TestParsedStderrReachesTheChannelsStats` | `source_fps = <nil>, want 25` (and two more) |
  | 18 | the `default:` log arm logs `line` instead of `redacted` | `TestAProviderURLInStderrNeverReachesTheLog` | as 3 — the echo line lands on that arm, which is why the test's line carries no keyword |
  | 19 | the `TimedOut` arm no longer calls `fail` | `TestASustainedSubThresholdSpeedEndsTheSourceWithATimeout` | `the source did not end after buffering past the timeout` |

- [ ] **Step 6: Run the four checks and commit**

---

## Task 7: `relay/httpapi` — the tune path and the payload

**Files:**
- Modify: `relay/httpapi/stream.go`, `channels.go` (Appendix P, both in full), `golden_test.go`, `stream_test.go` (Appendix Q, the edits), `testdata/channels_clients_all.json` (regenerated), `apps/proxy/tests/test_relay_list_payload_golden.py` (Appendix T5)
- Create: `relay/httpapi/transcode_test.go` (Appendix Q)

**Interfaces:**
- Consumes: everything Tasks 5 and 6 produce.
- Produces: `startTune` (was `startProxyTune`), `transcodeSource`, `ErrUnservedKind` (was `ErrNotProxyKind`), `ErrProfileArgvAbsent`, `ErrProfileUnbuildable`, `ErrNoFFmpegProfile`, `settingBufferingSpeed`, `settingBufferingTimeout`, `settingDefaultUserAgent`; seven fields on `channelPayload`.

- [ ] **Step 1: `stream.go`**

  `tuningFrom` reads the two thresholds on every tune (Constraint 13). `startTune` reads `DEFAULT_USER_AGENT` unconditionally and falls back to it when the answer's user agent is blank (`input/manager.py:73`), then branches on `kind` **and** the URL: Proxy + `NeedsFFmpeg` → the locked ffmpeg profile or `ErrNoFFmpegProfile`; Proxy → `ProxySource` as before; transcode → `transcodeSource(&answer.Source.StreamProfile, …)`; anything else → `ErrUnservedKind`. `transcodeSource` maps the three argv states to two errors and a source. `writeTuneFailure` gains three arms — `ErrProfileArgvAbsent` 502 (the same class and status as an absent setting), `ErrProfileUnbuildable` 503, `ErrNoFFmpegProfile` 503 — and its default arm goes through `redact.Error`. The detaching context is unchanged.

- [ ] **Step 2: `channels.go`**

  Seven fields between `AvgBitrate` and `Clients`, in `RelayChannelSerializer`'s order; `describeChannel` copies them from `c.Stats()`, pointer fields for the two floats, `omitempty` strings for the rest. The comment block naming the absent fields shrinks to two (R9).

- [ ] **Step 3: The three test-file edits**

  `stream_test.go`: the kinds test iterates `redirect` only (R13); the per-key list gains `settingBufferingSpeed`, `settingBufferingTimeout`, `settingDefaultUserAgent`. `golden_test.go`: `goldenPayload`'s populated channel gains the seven fields (`sourceFPS := 25.0`, `speed := 1.02`); `TestTheLiveEndpointProducesTheGoldensKeySet` builds a **`transcodeRig`** replaying the `normal` corpus and waits on `waitForStats` — a Proxy rig renders seven keys short and would report the golden as wrong.

- [ ] **Step 4: `transcode_test.go`**

  Appendix Q. `transcodeRig` starts its own upstream so its URL can be put in the argv (which is what Django does with `{streamUrl}`), and hands it to `newRig` as `SourceURL`; the stand-in is the profile's command.

  | Test | What it pins |
  |---|---|
  | `TestATranscodeTuneDeliversTheChildsOutput` | the architecture end to end: the **child** fetches the provider, exactly once; the client gets whole packets |
  | `TestTheListEndpointCarriesTheFfmpegDerivedFields` | the seven fields with the corpus's values and DRF's types (`source_fps` a float here — row 14's list side) |
  | `TestTheProxyProfileStreamsWithNoFfmpegAndNoStats` | **row 29**, meaningful only now that both architectures exist |
  | `TestAnAbsentOrNullArgvFailsTheTuneBeforeAnythingIsSpawned` | 502 / 503, zero provider requests, no address in the body |
  | `TestAProxyProfileWithAnHLSURLIsPlayedThroughTheFFmpegProfile` | force-ffmpeg; the discriminator is `ffmpeg_speed` on the payload |
  | `TestAProxyProfileWithAnHLSURLAndNoFFmpegProfileIsRefused` | 503, and the raw reader is never pointed at a playlist |
  | `TestABufferingThresholdChangeDoesNotReachARunningChannel` | **row 5** — API minimum then maximum, `SetSettings` between two tunes, the second channel is the falsifier |
  | `TestABlankUserAgentFallsBackToTheWireDefault` | at `startTune`, against the fixture's literal |
  | `TestAChildThatExitsNonZeroEndsTheTune` | the response ends, the channel carries `status 2` — take the `*Channel` **while the client is attached**, because its release drops it from the manager |

  ```bash
  cd <your worktree>/relay && go test -race -count=1 ./httpapi
  ```

- [ ] **Step 5: Break-check, seven edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 7 | `transcodeSource` ignores `ArgvPresent` | `…/absent: an older control plane` | `answered 503, want 502` |
  | 9 | `tuningFrom` falls back to `1.0` for `buffering_speed` | `TestEveryProxySettingThisRelayReadsIsRequired/buffering_speed` **only** | `an answer missing only "buffering_speed" tuned with 200, want 502 -- the relay substituted a default of its own` |
  | 11 | `NeedsFFmpeg` always false | both HLS tests | `channel c-hls never reported an ffmpeg speed within fifteen seconds`; `answered 200, want 503` |
  | 12 | (Task 6's) | the row 5 test | `the running channel picked up the new threshold` |
  | 15 | `describeChannel` reads `channel.Stats{}` | `TestTheListEndpointCarriesTheFfmpegDerivedFields` **and** `TestTheLiveEndpointProducesTheGoldensKeySet` | `resolution = <nil> (<nil>), want 320x180 (string)`; `the live payload's keys are …` |
  | 16 | the `KindTranscode` branch becomes unreachable | `TestATranscodeTuneDeliversTheChildsOutput` | `tune for client-a answered 501, want 200` |
  | — | `startTune` skips the `DEFAULT_USER_AGENT` fallback | `TestABlankUserAgentFallsBackToTheWireDefault` | `UserAgent = "", want the wire's DEFAULT_USER_AGENT` |

- [ ] **Step 6: Regenerate the golden from Django** (container)

  Edit `apps/proxy/tests/test_relay_list_payload_golden.py` per Appendix T5 — the populated channel's fixture gains the seven fields, `NOT_SERVED_BY_2C3` becomes `NOT_SERVED_YET` with `logo_id` and `healthy` — then:

  ```bash
  cd <your worktree> && DISPATCHARR_WRITE_GOLDEN=1 python manage.py test apps.proxy.tests.test_relay_list_payload_golden
  python manage.py test apps.proxy.tests.test_relay_list_payload_golden
  git diff --stat relay/httpapi/testdata/channels_clients_all.json
  ```

  **Yours governs.** The committed Appendix Q JSON was written by hand in DRF's spelling; if the regenerated file differs by more than the seven new keys, report which field.

- [ ] **Step 7: Run the four checks and commit**

---

## Task 8: the credential guard, the hook and the workflow

Ruling R7, and Constraint 23's ffmpeg install.

**Files:**
- Create: `relay/internal/credlint/check.go`, `main.go`, `check_test.go` (Appendix R); `scripts/check_go_credential_logging.sh` (Appendix R)
- Modify: `.claude/hooks/run-go-checks.sh`, `.github/workflows/go-tests.yml` (Appendix S)

- [ ] **Step 1: The checker**

  Appendix R. `ListPackages` runs `go list -deps` and keeps the module's own packages in dependency order; `Checker` implements `types.Importer`, answering module packages from its cache and everything else from `importer.ForCompiler(fset, "gc", nil)`; `inspect` walks every call, resolves the callee through `types.Info.Uses` to its full name, and checks each argument whose static type implements `error` and is not a `nil` literal. `Sinks` and `Redactors` are the two maps the rule is made of.

- [ ] **Step 2: Run it against the module, expect zero**

  ```bash
  cd <your worktree> && scripts/check_go_credential_logging.sh relay
  ```

  If Tasks 1, 5 and 6 landed every marker and wrap, it prints `credlint: 10 package(s) clean`. **Its first run over this plan's own tree reported 18 sites**; each is resolved in Appendices K, L, M, N, S. A finding here is a task above that missed one, not a reason to add a marker in this task.

- [ ] **Step 3: Its own tests**

  ```bash
  cd <your worktree>/relay && go test -race -count=1 ./internal/credlint
  ```

  The fixture package in `check_test.go` names every `// BAD` line; the test compares reported lines to that set in **both** directions, and separately that the bare marker is reported for the no-reason reason. `newCheckerWithRedact` type-checks the real `redact` package first so the allowlist is exercised against the name `go/types` gives it.

- [ ] **Step 4: The hook and the workflow**

  Appendix S, as diffs. The hook gains a block between the test run and the lint block. The workflow gains an `Install ffmpeg` step before `Build`, an `Assert no error reaches a log unredacted` step after the stdlib assertion, and two alternatives in the change detector's pattern: the script, and the corpus fixtures directory (a re-capture must run the Go parser tests). Then:

  ```bash
  cd <your worktree> && zizmor .github/workflows/go-tests.yml
  bash -n .claude/hooks/run-go-checks.sh
  ```

  Zero findings; this plan's copy was clean under zizmor 1.29.0 offline.

- [ ] **Step 5: Break-check**

  | # | The edit | Expected red |
  |---|---|---|
  | 13 | `Redactors` emptied | `TestTheRuleReportsExactlyTheBadLines` (two `// ok` lines now reported) and `TestTheRedactorIsExactlyRedactError`; and `scripts/check_go_credential_logging.sh relay` reports the module's `redact.Error` call sites |
  | — | `markerFor` accepts a bare marker | the bare-marker assertion in `TestTheRuleReportsExactlyTheBadLines` |

- [ ] **Step 6: `CLAUDE.md` § Test hooks**

  After the Go-hook paragraph, one paragraph: the Go hook and `go-tests.yml` also run `scripts/check_go_credential_logging.sh` (`relay/internal/credlint`, stdlib `go/types`) — every error-typed argument to a formatting or logging call passes through `redact.Error` or carries `// credential-logging: ok - <reason>`; zero findings is a ratchet; the marker's reason is required; the rule's three known gaps are in `check.go`'s header. And that `go-tests.yml` installs ffmpeg for row 4's real-ffmpeg test, which fails rather than skips under `CI`.

- [ ] **Step 7: Commit**

---

## Task 9: the parity matrix — rows 4, 5, 28 and 29 get their Go pin

Amendment A2.2's rule: a Go reference appended to the existing `Pin` cell, one line per row, no padding, no formatter. **Tasks 2, 6 and 7 must be committed first**: the guard resolves each `.go` reference by opening the file.

- [ ] **Step 1: Read the four rows before editing them**

  ```bash
  cd <your worktree> && grep -n '^| 4 \|^| 5 \|^| 28 \|^| 29 ' docs/relay-parity-matrix.md
  ```

- [ ] **Step 2: Append, and add one sentence to each Notes cell**

  | Row | Append to `Pin` | Append to `Notes` |
  |---|---|---|
  | 4 | `` `relay/channel/source_transcode_real_test.go::TestTheCumulativeLeadMustBurnOffBeforeTheDetectorArms` ``, `` `relay/ffmpeg/detector_test.go::TestTheCapturedLeadIsNeverCalledBufferingBeforeItCrosses` ``, `` `relay/channel/source_transcode_test.go::TestTheCapturedLeadIsNeverLabelledBufferingBeforeItCrosses` `` | The Go pin is 2c-4's, and its first reference is the one REAL-ffmpeg test in the matrix: production parameters against a quarter-speed upstream, asserting the shape (first speed above 1.0, never buffering while at or above it, at least 4 s to arm) and no digit; measured 10.9x and 12.2 s on ffmpeg 9.0.1. The other two replay the capture, as this row's Python pin does. |
  | 5 | `` `relay/httpapi/transcode_test.go::TestABufferingThresholdChangeDoesNotReachARunningChannel` `` | The Go pin is 2c-4's: `channel.Tuning` is snapshotted at `publish`, the transcode source reads its thresholds from it, and the second channel tuned after the change is what makes the test falsifiable. |
  | 28 | `` `relay/ffmpeg/progress_test.go::TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` `` | The Go pin is 2c-4's and reads the same truncation capture; `ffmpeg/progress.go`'s `speedRe` is the Python regex verbatim and its comment names this row. |
  | 29 | `` `relay/httpapi/transcode_test.go::TestTheProxyProfileStreamsWithNoFfmpegAndNoStats` `` | The Go pin is 2c-4's, the first PR in which both architectures exist and the row can fail: buffering_speed at the API maximum on a Proxy tune, no speed reported, state never buffering, none of the seven ffmpeg-derived keys on the payload. |

- [ ] **Step 3: Run the guard**

  ```bash
  cd <your worktree>/e2e && npx playwright test --project=guards parity-matrix
  ```

  No container. The owed list stays empty.

- [ ] **Step 4: Commit**

---

## Task 10: the spec amendment, `CLAUDE.md`, two issues, and the Done log

- [ ] **Step 1: Write Amendment A4 into the spec**

  After Amendment A3 (2c-3's), Appendix U1's text: A4.1 (Django builds the argv — R1), A4.2 (the credential guard and the Python relay's own stderr leak — R7, R8), A4.3 (inputs for 2c-5: the `TimedOut` arm, the two events, `healthy`, `Detector.Reset`), A4.4 (rows 5, 28 and 29 close here with row 4), A4.5 (`connecting` is not transcode-specific — R10), A4.6 (the UDP filter's dangling flag, reproduced and filed — R11).

- [ ] **Step 2: Edit the nine-PR table's 2c-4 and 2c-5 rows, in the table**

  2c-4's "What it does" becomes: *ffmpeg spawn via `os/exec` + `syscall.SysProcAttr{Setpgid, Pdeathsig}` (D5 exception 1), the `log_parsers.py` port, Amendment A4.1 (Django builds `stream_profile.argv`; no Go word splitter), the seven ffmpeg-derived fields on `GET /proxy/relay/channels`, and the Go credential-logging guard (#283).* Its gate: *Row 4 (the `speed=` arming delay) gets a Go column with its own real-ffmpeg test, mirroring 2a's harness; rows 5, 28 and 29 too (Amendment A4.4).* 2c-5's "What it does" gains: *the buffering-timeout arm 2c-4's `TranscodeSource` ends the tune on (`ErrBufferingTimeout`), the `channel_buffering` and `channel_failover` events, and `healthy` (Amendment A4.3).*

- [ ] **Step 3: `CLAUDE.md`**

  § Architecture, after 2c-3's sentence on the client registry: one sentence — since 2c-4 the Go relay serves the FFmpeg/VLC/Streamlink architecture; Django builds the argv (`StreamProfile.build_command`) and sends it as `stream_profile.argv` (Amendment A4.1); the relay spawns it with `Setpgid` and, on Linux, `Pdeathsig SIGKILL`, kills with SIGKILL, parses stderr with `relay/ffmpeg`'s port of `log_parsers.py`, and ends the tune with `ErrBufferingTimeout` until 2c-5 wires failover.

  § Known defects, two new bullets (Appendix U2): the Python relay logs the provider URL at INFO through ffmpeg's `Input #0 … from '<url>':` line and the HLS demuxer's segment lines (`input/manager.py:1094`), invisible to `check_credential_logging.py`; and the UDP filter's dangling flag (`:808-812`). Each cites the issue from Step 4.

- [ ] **Step 4: File the two issues**

  ```bash
  gh issue create --repo D10Scot/Dispatcharr --label needs-triage --title "Python relay logs the provider URL at INFO through ffmpeg's stderr preamble" --body-file <file>
  gh issue create --repo D10Scot/Dispatcharr --label needs-triage --title "The UDP user-agent filter leaves dangling flags in the transcode argv" --body-file <file>
  ```

  Always `--repo`; `gh` otherwise resolves to the upstream tracker. Put the numbers into the two `CLAUDE.md` bullets and Amendment A4.2/A4.6.

- [ ] **Step 5: The Done log**

  One row for 2c-4 naming the branch `migration/phase2c-ffmpeg`, and one for its review fix round when there is one.

- [ ] **Step 6: Commit**

---

## Task 11: final verification and the PR description

- [ ] **Step 1: Confirm the scope of the diff, both directions**

  ```bash
  cd <your worktree> && git diff --stat main...HEAD
  ```

  Against the File Structure. Anything outside it is a finding.

- [ ] **Step 2: The three guards**

  ```bash
  cd <your worktree> && scripts/check_go_stdlib_only.sh relay && scripts/check_go_credential_logging.sh relay && zizmor .github/workflows/go-tests.yml
  ```

  `go.sum` still **absent**; the module graph one line; no package named for Redis; zero credlint findings; zero zizmor findings.

- [ ] **Step 3: The full verification pass, three times**

  ```bash
  cd <your worktree>/relay && gofmt -l . && go build ./... && go vet ./... && GOOS=linux go vet ./... && golangci-lint run ./...
  for i in 1 2 3; do go test -race -count=1 ./... || echo "RUN $i FAILED"; done
  ```

  Three clean runs. This plan's own measured about 34 s (`channel`, 21 of it the real ffmpeg), 16 s (`httpapi`), 8 s (`ffmpeg`).

- [ ] **Step 3a: The `StateActive` count**

  ```bash
  cd <your worktree>/relay && grep -rnE "state = StateActive|setState\(StateActive" --include='*.go' . | grep -v _test.go
  ```

  **Expect exactly two lines**: `channel/channel.go`'s in `promoteOnFirstChunk`, and `channel/stats.go`'s in `reportBuffering` under its `StateBuffering` guard. A third is a stop.

- [ ] **Step 4: The Linux pin, once more, in the image** — Task 3 Step 6's command on the final tree.

- [ ] **Step 5: Run the relay by hand once**

  ```bash
  cd <your worktree>/relay && DISPATCHARR_RELAY_GO_DEV_ROUTES=1 DISPATCHARR_RELAY_GO_PORT=5658 DJANGO_SECRET_KEY=hand-run-secret go run .
  ```

  `/healthz` answers 200; a tune the control plane cannot answer for fails with a body naming no URL and no variable value; and with `DISPATCHARR_ENV=dev` against a `runserver 5656` whose channel uses the locked ffmpeg profile, `GET /proxy/relay/channels` (signed) shows `ffmpeg_speed` and `stream_type` after a few seconds — the one end-to-end check no rig papers over, because it is a real ffmpeg on a real Django answer.

- [ ] **Step 6: Write the PR description**

  In this order: what this PR does; **Ruling R1** and what it cost on the Django side; **the three break-checks that did not redden** (R6 twice, break-check 8) and what closed each; **the credlint census** — 18 findings, the two real ones, the sixteen markers; **the measurements** — the real-ffmpeg numbers on your host and ffmpeg version, next to this plan's; **the stated divergences**: `redact.Line` on stderr where Python logs raw (R8); recovery to `active` only from `buffering` (R12); a URL-shaped command refused before spawning (Task 3); `connecting` not entered (R10); a buffering timeout ending the tune rather than failing over, until 2c-5 (R2); the UDP filter's `cmd[0]` not filtered (R11); `ErrExited` carrying the status Python only logs; **what this PR does not do**: no failover, no `release`, no `events`, no `channel_buffering`/`channel_failover`, no `healthy`, no Redirect (2c-5); no fMP4 (2c-6); no Output Profile — `output_profiles[*].argv` is still undeclared on `NextSourceAnswer` (2c-7); no detail endpoint, no `advance`, no drain (2c-8); no Go coverage ratchet and no CodeQL Go pack (2c-9).

- [ ] **Step 7: Commit, and do not push or open a PR unless told to**

---
## Break-check × what each can redden

Every break-check in this plan, and the task it belongs to. A `✓` means it was run against this plan's own verified implementation and the message in the task table is the one that appeared. The numbering is the order they were run in, which is why it is not the task order.

| # | Task | The injected defect | What reddens | Verified |
|---|---|---|---|---|
| 1 | 2 | detector `<` becomes `<=` | `TestTheDetectorFollowsPythonsTransitions`, "speed AT the threshold" | ✓ |
| 2 | 2 | detector `>` becomes `>=` | the same test, "exactly the timeout later" | ✓ |
| 3 | 6 | stderr lines logged raw | `TestAProviderURLInStderrNeverReachesTheLog` | ✓ |
| 4 | 2 | `speedRe` reads the exponent | `TestAScientificNotationSpeedIsUnderReportedAsItsMantissa` — on its **guard** assertion, which reads the same regex | ✓ |
| 5 | 6 | the input-phase gate dropped | `TestOutputPhaseStreamLinesDoNotOverwriteTheInputs` | ✓ |
| 6 | 6 | the UDP filter removed | `TestTheUDPFilterDropsUserAgentArguments` | ✓ |
| 7 | 7 | `ArgvPresent` ignored | `…/absent: an older control plane`, `answered 503, want 502` | ✓ |
| 8 | 3 | `Cancel` sends SIGTERM | `TestCancelKillsTheChildWithSIGKILL`, 502 ms | ✓ — **after** the bound moved from 3 s to `KillWait/2` (R6) |
| 9 | 7 | `buffering_speed` falls back to a literal | `TestEveryProxySettingThisRelayReadsIsRequired/buffering_speed` **only** | ✓ |
| 10 | 6 | the recovery arm unguarded | **nothing** — expected, recorded (§ Sequencing) | ✓ (green) |
| 11 | 7 | `NeedsFFmpeg` always false | both HLS tests | ✓ |
| 12 | 6 | the detector built from a literal, not the channel's tuning | `TestABufferingThresholdChangeDoesNotReachARunningChannel` | ✓ |
| 13 | 8 | `Redactors` emptied | both credlint tests; the script reports the module's own calls | ✓ |
| 14 | 6 | `reportInfo` a no-op | `TestParsedStderrReachesTheChannelsStats` | ✓ |
| 15 | 7 | stats not rendered | `TestTheListEndpointCarriesTheFfmpegDerivedFields` **and** `TestTheLiveEndpointProducesTheGoldensKeySet` | ✓ |
| 16 | 7 | the transcode branch unreachable | `TestATranscodeTuneDeliversTheChildsOutput`, 501 | ✓ |
| 17 | 3 | `ReadStderr` splits on LF only | `…SeesEveryRecord/normal` and `/slow-trickle`; `truncation` green | ✓ — **on the second attempt**; the first edit never landed |
| 18 | 6 | the default log arm unredacted | `TestAProviderURLInStderrNeverReachesTheLog` | ✓ |
| 19 | 6 | `TimedOut` no longer ends the source | `TestASustainedSubThresholdSpeedEndsTheSourceWithATimeout` | ✓ |
| 20 | 3 | `Pdeathsig` removed (Linux, in the Go image) | `TestAChildOfADeadRelayDiesWithIt`, 5.02 s | ✓ — **on the third helper** (R6) |
| 1a, 1b | 1 | `redact.Error`/`Line` neutered | the redact tests and 2c-2's two | — |
| — | 4 | substitute before split; `[]` on `ValueError` | the two Python tests named | — (container) |
| — | 5 | `ArgvPresent` always true | `TestArgvPresenceIsDecodedInAllThreeStates/absent…` | — |
| — | 7 | the `DEFAULT_USER_AGENT` fallback skipped | `TestABlankUserAgentFallsBackToTheWireDefault` | — |

**Three rows deserve a second look before you trust them, and every one comes from a break-check that did not redden.**

- **8** stayed green at a three-second bound because `os/exec.WaitDelay` sends its own SIGKILL 500 ms after a signal the child ignored — the outcome was identical and only the **time** told the mechanisms apart. If your run reddens above 250 ms with the correct code, the host is slow, not the test wrong; report the number.
- **17** stayed green because the injected edit did not apply (a quoting mistake in the harness that ran it) and the unmodified tree passed. **Confirm an injected edit is in the file before reading a green as a finding.** The corrected run reddened on `normal` and `slow-trickle` and stayed green on `truncation`, which has no CR at all — the right shape.
- **20** stayed green twice, for two different EPIPE reasons (R6). The helper's child now blocks on nothing but sleep, and the parent reads the child's one write before announcing it. If it stays green on your tree, check `/proc/<child>/stat` before the kill: the state must be `S`.

**Row 10 is listed because it does not redden.** The guard on the recovery edge is what keeps `promoteOnFirstChunk` the one promotion mechanism; no test can see it, and § Sequencing says so rather than inventing one.

---

## What to report back

1. **Task 0's diff** — every ledger row that did not match `<2C3_MERGED_SHA>`, and which task absorbed it. In particular the `Started`/`Attach` shape, `EffectiveProxySettings` carrying both thresholds, and whether `test_relay_list_payload_golden.py` exists.
2. **The `StateActive` count** at Task 0 (one) and at Task 11 (two, named).
3. **Every break-check's actual failure message**, and specifically: did **8**, **17** and **20** behave as this plan predicts, and did **10** stay green?
4. **The real-ffmpeg numbers** — ffmpeg version, first speed, seconds to arm, two runs — beside this plan's 9.0.1 / 10.9x / 12.2 s.
5. **The credlint census** — the number of findings its first run reported on your tree before Task 5/6's markers (this plan's: 18), the two `redact.Error` fixes, and anything new it reported that this plan does not name.
6. **The zero-ORM number** — expected 39 on both `resolve_source` entries.
7. **The golden file** — whether Django's regeneration matched Appendix Q's hand-written JSON beyond the seven new keys.
8. **The lint ledger** — the four `#nosec`/`nolint` this plan names and nothing else.
9. **The Linux pin's two Docker runs** — PASS with `Pdeathsig`, the five-second FAIL without.
10. **The two issue numbers** filed in Task 10.
11. **The stated divergences**, as a list (Task 11 Step 6).
12. **Anything in the spec, `CLAUDE.md`, the 2c-3 plan or this plan you found wrong or stale.** The three most likely places: the ledger's `file:line` citations into `next_source.py` (2c-3's Python task may have moved them), this plan's reading of `get_basic_channel_info`'s seven `if`s, and Appendix T1's line-number anchors.

---

## Appendix — the files, in full

Every Go file below was written, built, vetted, run under `go test -race` three times and linted at **0 issues** in a scratch module seeded from `81d41975` plus 2c-3's appendices (§ Sequencing), with `scripts/check_go_credential_logging.sh` clean and `GOOS=linux go vet` clean. The real-ffmpeg test ran on ffmpeg 9.0.1; the Linux-only test ran in the repo's Go 1.27.1 image, both ways. The Python files (Appendix T) were syntax-checked and **not executed** — they need the shared container, which Global Constraint 10 keeps out of a planning session; Task 4 runs them, and yours governs.

**Two literals are oracles and must be regenerated rather than trusted:** the golden JSON (Task 7 Step 6), and — carried from 2c-2 — the synthetic asset's SHA-256.

**Appendices M, N, P and J are whole files that 2c-3 owns and 2c-4 edits.** Diff them against your tree rather than overwriting: a 2c-3 fix round may have moved something this plan's reconstruction did not see.


### Appendix A — `relay/redact/redact.go`

**`relay/redact/redact.go`**

```go
// Package redact is the one place a provider URL is stripped before it can
// reach a log line or an error message.
//
// A provider URL is a credential (CLAUDE.md, § Known defects): Xtream URLs
// carry the password in the PATH (/live/<user>/<pass>/<id>.ts), in the QUERY
// (?username=&password=) and sometimes in the userinfo. The Python side is
// policed by scripts/check_credential_logging.py; the Go side is policed by
// relay/internal/credlint, which requires every error-typed argument to a
// formatting or logging call to pass through Error below, or to carry a
// written reason it need not. That is what makes this package the ONE source
// of redaction: a second implementation would be a second thing for the
// linter to know about, and the one it did not know about would be the leak.
package redact

import (
	"errors"
	"net/url"
	"regexp"
	"strings"
)

// Error strips the URL out of an error that carries one.
//
// net/http wraps every client failure in a *url.Error whose Error() prints the
// whole URL, and its own redaction covers ONLY userinfo -- it turns
// http://user:pw@host into http://user:***@host and leaves the path and query
// string untouched, which is exactly where a Dispatcharr provider credential
// lives. The inner error is what is left: "dial tcp 127.0.0.1:1: connect:
// connection refused" names a host and a port and no secret.
//
// Every other error is returned as it came. os/exec's *exec.Error carries the
// program NAME (exec.Command's first argument), never its arguments; an
// *os.PathError from os.StartProcess carries the executable's path. Neither
// is a URL unless an operator set a Stream Profile's command TO a URL, and a
// command that is a URL is a misconfiguration this relay refuses before it
// spawns anything (channel.TranscodeSource). Moved here from
// channel.withoutURL (2c-2) so that one function is the redactor for the
// whole module.
func Error(err error) error {
	var urlErr *url.Error
	if errors.As(err, &urlErr) && urlErr.Err != nil {
		return urlErr.Err
	}
	return err
}

// urlPattern matches anything that looks like a URL with a scheme, up to the
// first whitespace or quote. Quotes end a match because ffmpeg quotes the URL
// it prints ("Input #0, mpegts, from 'http://...':") and a match that swallowed
// the closing quote would also swallow the rest of the line.
var urlPattern = regexp.MustCompile(`[A-Za-z][A-Za-z0-9+.-]*://[^\s'"]+`)

// Placeholder is what replaces the credential-bearing part of a URL.
const Placeholder = "[redacted]"

// Line replaces every URL in a line of text with its scheme and host and the
// placeholder, so "http://user:pw@host:8080/live/u/p/1.ts?token=t" becomes
// "http://host:8080/[redacted]".
//
// STRUCTURAL, NOT EXACT-MATCH, and the difference is what a stderr line
// needs. ffmpeg prints the URL it was given verbatim in its preamble, and
// that exact string could be replaced by a lookup. But the HLS demuxer also
// prints every segment URL it opens ("[hls @ 0x...] Opening 'http://host/
// path/seg-3.ts' for reading"), and those are DERIVED from the provider URL
// -- same credentialled path, different tail -- so an exact-match strip
// leaves the credential in every segment line. Anything with a scheme is
// treated as a URL, and only its host survives.
//
// The host is kept because it is what an operator needs to tell one provider
// from another in a log, and it is not a credential: the same host appears
// in the M3U account's own configuration.
func Line(s string) string {
	return urlPattern.ReplaceAllStringFunc(s, func(match string) string {
		parsed, err := url.Parse(match)
		if err != nil || parsed.Host == "" {
			// Unparseable, or a scheme with no authority (udp://... parses
			// with a host; "file:///x" has none): nothing to keep safely.
			scheme, _, found := strings.Cut(match, "://")
			if !found {
				return Placeholder
			}
			return scheme + "://" + Placeholder
		}
		return parsed.Scheme + "://" + parsed.Host + "/" + Placeholder
	})
}
```

### Appendix B — `relay/redact/redact_test.go`

**`relay/redact/redact_test.go`**

```go
package redact

import (
	"errors"
	"fmt"
	"net/url"
	"strings"
	"testing"
)

// The credential is in the PATH and the QUERY, not the userinfo: net/url's
// own String() already masks userinfo, so a test whose secret lived there
// would pass against an unredacted error and prove nothing.
const secretURL = "http://provider.example:8080/live/subscriber/hunter2/9.ts?token=s3cr3t"

func TestErrorStripsTheURLOutOfAURLError(t *testing.T) {
	inner := errors.New("dial tcp 127.0.0.1:1: connect: connection refused")
	err := Error(&url.Error{Op: "Get", URL: secretURL, Err: inner})
	for _, secret := range []string{"hunter2", "s3cr3t", "/live/subscriber"} {
		if strings.Contains(err.Error(), secret) {
			t.Fatalf("the redacted error still carries %q: %s", secret, err)
		}
	}
	if !errors.Is(err, inner) {
		t.Fatalf("the transport's own reason was lost: %v", err)
	}
}

// A wrapped *url.Error is found through the chain, which is what makes the
// function safe to apply to an error that has already been annotated once.
func TestErrorFindsAURLErrorThroughAWrap(t *testing.T) {
	wrapped := fmt.Errorf("connecting: %w", &url.Error{Op: "Get", URL: secretURL, Err: errors.New("refused")})
	if got := Error(wrapped).Error(); strings.Contains(got, "hunter2") {
		t.Fatalf("the wrapped URL survived: %s", got)
	}
}

func TestErrorLeavesAnOrdinaryErrorAlone(t *testing.T) {
	plain := errors.New("exit status 1")
	// Identity is the assertion -- the same error value comes back, not a
	// wrap of it -- so errors.Is would pass against exactly the wrapping
	// this test forbids.
	if got := Error(plain); got != plain { //nolint:errorlint // identity, not equivalence, is the claim
		t.Fatalf("an error with no URL was replaced: %v", got)
	}
	if got := Error(nil); got != nil {
		t.Fatalf("Error(nil) = %v, want nil", got)
	}
}

func TestLineKeepsTheHostAndDropsEverythingElse(t *testing.T) {
	for _, tc := range []struct{ in, want string }{
		{
			// ffmpeg's own preamble line, quoted.
			"Input #0, mpegts, from '" + secretURL + "':",
			"Input #0, mpegts, from 'http://provider.example:8080/[redacted]':",
		},
		{
			// userinfo, path and query all go; only the host stays.
			"opening http://user:pw@host/live/u/p/1.ts?password=x for reading",
			"opening http://host/[redacted] for reading",
		},
		{
			// An HLS segment URL derived from the provider URL: not the exact
			// string the relay was given, still a credentialled path.
			"[hls @ 0x1] Opening 'https://cdn.example/live/subscriber/hunter2/seg-3.ts' for reading",
			"[hls @ 0x1] Opening 'https://cdn.example/[redacted]' for reading",
		},
		{
			// Two URLs on one line, both replaced.
			"a http://one.example/x/y b udp://239.0.0.1:1234?fifo_size=1 c",
			"a http://one.example/[redacted] b udp://239.0.0.1:1234/[redacted] c",
		},
		{
			// No URL, no change.
			"frame=  150 fps=0.0 q=-1.0 size=352KiB time=00:00:05.85 bitrate= 492.2kbits/s speed=11.5x",
			"frame=  150 fps=0.0 q=-1.0 size=352KiB time=00:00:05.85 bitrate= 492.2kbits/s speed=11.5x",
		},
		{
			// A scheme with no authority keeps the scheme only.
			"reading file:///etc/passwd",
			"reading file://[redacted]",
		},
	} {
		if got := Line(tc.in); got != tc.want {
			t.Errorf("Line(%q)\n got %q\nwant %q", tc.in, got, tc.want)
		}
	}
}

// The property the whole package exists for, asserted directly: after Line,
// none of the secret's parts survive, for every spelling of URL the corpus
// and the M3U transform produce.
func TestLineNeverLeavesACredentialBehind(t *testing.T) {
	for _, in := range []string{
		secretURL,
		"http://user:hunter2@host/stream.ts",
		"http://host/get.php?username=subscriber&password=hunter2&type=m3u",
		"rtsp://user:hunter2@cam.example:554/live",
		"'" + secretURL + "'",
		"prefix " + secretURL + " suffix",
	} {
		got := Line(in)
		for _, secret := range []string{"hunter2", "s3cr3t", "subscriber", "password"} {
			if strings.Contains(got, secret) {
				t.Errorf("Line(%q) = %q still carries %q", in, got, secret)
			}
		}
	}
}
```

### Appendix C — `relay/ffmpeg/parse.go` (and the stub comment it replaces in `ffmpeg.go`)

**`relay/ffmpeg/parse.go`**

```go
package ffmpeg

import (
	"regexp"
	"strconv"
	"strings"
)

// Info is what one parsed stderr line says about the stream: the dict
// apps/proxy/live_proxy/services/log_parsers.py's parse methods return, with a
// nil pointer wherever Python leaves the key unset. Presence matters because
// channel_service._update_stream_info_in_redis (channel_service.py:844-880)
// writes only the keys that are not None, so a later line that names the codec
// and nothing else must not blank the resolution an earlier line set.
type Info struct {
	VideoCodec   *string
	Resolution   *string
	Width        *int
	Height       *int
	SourceFPS    *float64
	PixelFormat  *string
	VideoBitrate *float64

	AudioCodec    *string
	SampleRate    *int
	AudioChannels *string
	AudioBitrate  *float64

	// InputFormat is the dict's 'stream_type' key -- "mpegts", "hls" -- which
	// channel_service stores under ChannelMetadataField.STREAM_TYPE and the
	// list endpoint renders as stream_type. The Python name is kept on the
	// wire and not here, because here it would read as the KIND of parse.
	InputFormat *string
}

// Kind is what a parser says a line is: log_parsers.py's stream_type strings,
// spelled exactly, because input/manager.py:1080 branches on them by name.
type Kind string

// The seven kinds. VLCInputFailed is the one that never carries an Info: it is
// a signal to the caller (input/manager.py:1059-1064 closes the socket on it),
// not a parse.
const (
	KindInput          Kind = "input"
	KindVideo          Kind = "video"
	KindAudio          Kind = "audio"
	KindVLCVideo       Kind = "vlc_video"
	KindVLCAudio       Kind = "vlc_audio"
	KindVLCInputFailed Kind = "vlc_input_failed"
	KindStreamlink     Kind = "streamlink"
)

// Tool names the parser that handles a command's output.
type Tool string

// The three tools, keyed by input/manager.py:797-802's command_to_parser
// mapping.
const (
	ToolFFmpeg     Tool = "ffmpeg"
	ToolVLC        Tool = "vlc"
	ToolStreamlink Tool = "streamlink"
)

// ToolFor maps a Stream Profile's command to its parser, exactly as
// input/manager.py:797-803 does: the WHOLE command string, lowercased, looked
// up in a four-entry map. "/usr/bin/ffmpeg" is therefore unknown and falls
// back to auto-detection, which is the Python behaviour and is not improved
// here.
func ToolFor(command string) (Tool, bool) {
	switch strings.ToLower(command) {
	case "ffmpeg":
		return ToolFFmpeg, true
	case "cvlc", "vlc":
		return ToolVLC, true
	case "streamlink":
		return ToolStreamlink, true
	}
	return "", false
}

// factoryOrder is LogParserFactory._parsers' insertion order
// (log_parsers.py:364-368), which is the order AutoParse tries them in.
var factoryOrder = []Tool{ToolFFmpeg, ToolVLC, ToolStreamlink}

// CanParse reports which kind of line this is for the tool, or "" when the
// tool's parser does not recognise it. The port of each parser's can_parse.
func CanParse(tool Tool, line string) Kind {
	lower := strings.ToLower(line)
	switch tool {
	case ToolFFmpeg:
		// log_parsers.py:47-62.
		if strings.HasPrefix(lower, "input #") {
			return KindInput
		}
		if strings.Contains(lower, "stream #") {
			if strings.Contains(lower, "video:") {
				return KindVideo
			} else if strings.Contains(lower, "audio:") {
				return KindAudio
			}
		}
	case ToolVLC:
		// log_parsers.py:163-186.
		if strings.Contains(lower, "unable to open the mrl") {
			return KindVLCInputFailed
		}
		if strings.Contains(lower, "ts demux debug") && strings.Contains(lower, "type=") {
			if strings.Contains(lower, "video") {
				return KindVLCVideo
			} else if strings.Contains(lower, "audio") {
				return KindVLCAudio
			}
		}
		// 'x' in line: the ORIGINAL line, case-sensitively, as the Python
		// reads `'x' in line` beside three checks against `lower`.
		if strings.Contains(lower, "decoder") &&
			(strings.Contains(lower, "channels:") || strings.Contains(lower, "samplerate:") ||
				strings.Contains(line, "x") || strings.Contains(lower, "fps")) {
			if strings.Contains(lower, "audio") || strings.Contains(lower, "channels:") || strings.Contains(lower, "samplerate:") {
				return KindVLCAudio
			}
			return KindVLCVideo
		}
		if strings.Contains(lower, "stream_out_transcode") &&
			(strings.Contains(lower, "source fps") || (strings.Contains(lower, "source ") && strings.Contains(line, "x"))) {
			return KindVLCVideo
		}
	case ToolStreamlink:
		// log_parsers.py:312-319.
		if strings.Contains(lower, "opening stream:") || strings.Contains(lower, "available streams:") {
			return KindStreamlink
		}
	}
	return ""
}

// Parse parses a line as the given kind. The port of LogParserFactory.parse:
// the kind picks the parser AND the method through each parser's
// STREAM_TYPE_METHODS, so KindVLCInputFailed -- which no parser lists --
// returns nothing, exactly as parse('vlc_input_failed', ...) does.
func Parse(kind Kind, line string) (Info, bool) {
	switch kind {
	case KindInput:
		return ffmpegInputFormat(line)
	case KindVideo:
		return ffmpegVideo(line)
	case KindAudio:
		return ffmpegAudio(line)
	case KindVLCVideo:
		return vlcVideo(line)
	case KindVLCAudio:
		return vlcAudio(line)
	case KindStreamlink:
		return streamlinkVideo(line)
	}
	return Info{}, false
}

// AutoParse tries every parser in factory order and returns the first that
// both recognises the line AND parses something out of it. The port of
// LogParserFactory.auto_parse (log_parsers.py:399-413), including its one
// consequence worth knowing: a VLC "unable to open the MRL" line is recognised
// (KindVLCInputFailed) but parses to nothing, so AutoParse moves on and never
// reports it. Only the direct route through ToolFor + CanParse sees it, which
// is why input/manager.py's socket-closing branch is reachable only when the
// command is literally "vlc" or "cvlc".
func AutoParse(line string) (Kind, Info, bool) {
	for _, tool := range factoryOrder {
		kind := CanParse(tool, line)
		if kind == "" {
			continue
		}
		if info, ok := Parse(kind, line); ok {
			return kind, info, true
		}
	}
	return "", Info{}, false
}

// The FFmpeg regexes, log_parsers.py:67-133, as RE2. Every one is expressible
// verbatim: \b is an ASCII word boundary in both engines for these inputs,
// and \d is ASCII-only here where Python's is Unicode-aware -- a difference
// no ffmpeg build produces text to exercise.
var (
	ffInputRe       = regexp.MustCompile(`Input #\d+,\s*([^,]+)`)
	ffVideoCodecRe  = regexp.MustCompile(`Video:\s*([a-zA-Z0-9_]+)`)
	ffResolutionRe  = regexp.MustCompile(`\b(\d{3,5})x(\d{3,5})\b`)
	ffFPSRe         = regexp.MustCompile(`(\d+(?:\.\d+)?)\s*fps`)
	ffPixelFormatRe = regexp.MustCompile(`Video:\s*[^,]+,\s*([^,(]+)`)
	ffKbpsRe        = regexp.MustCompile(`(\d+(?:\.\d+)?)\s*kb/s`)
	ffAudioCodecRe  = regexp.MustCompile(`Audio:\s*([a-zA-Z0-9_]+)`)
	ffSampleRateRe  = regexp.MustCompile(`(\d+)\s*Hz`)
	ffChannelsRe    = regexp.MustCompile(`(?i)\b(mono|stereo|5\.1|7\.1|quad|2\.1)\b`)
)

func ffmpegInputFormat(line string) (Info, bool) {
	m := ffInputRe.FindStringSubmatch(line)
	if m == nil {
		return Info{}, false
	}
	format := strings.TrimSpace(m[1])
	if format == "" {
		return Info{}, false
	}
	return Info{InputFormat: &format}, true
}

// resolutionWithin applies the 100..10000 bound both Python video parsers
// share (log_parsers.py:92, :210, :220).
func resolutionWithin(w, h int) bool {
	return w >= 100 && w <= 10000 && h >= 100 && h <= 10000
}

func ffmpegVideo(line string) (Info, bool) {
	var info Info
	set := false
	if m := ffVideoCodecRe.FindStringSubmatch(line); m != nil {
		info.VideoCodec = ptr(m[1])
		set = true
	}
	if m := ffResolutionRe.FindStringSubmatch(line); m != nil {
		w, _ := strconv.Atoi(m[1])
		h, _ := strconv.Atoi(m[2])
		if resolutionWithin(w, h) {
			info.Resolution = ptr(m[1] + "x" + m[2])
			info.Width, info.Height = ptr(w), ptr(h)
			set = true
		}
	}
	if m := ffFPSRe.FindStringSubmatch(line); m != nil {
		if fps, err := strconv.ParseFloat(m[1], 64); err == nil {
			info.SourceFPS = ptr(fps)
			set = true
		}
	}
	if m := ffPixelFormatRe.FindStringSubmatch(line); m != nil {
		pf := strings.TrimSpace(m[1])
		// log_parsers.py:104-105 splits at '(' -- unreachable, since the
		// capture group already excludes it. Ported so the shape matches.
		if before, _, found := strings.Cut(pf, "("); found {
			pf = strings.TrimSpace(before)
		}
		info.PixelFormat = ptr(pf)
		set = true
	}
	if m := ffKbpsRe.FindStringSubmatch(line); m != nil {
		if kbps, err := strconv.ParseFloat(m[1], 64); err == nil {
			info.VideoBitrate = ptr(kbps)
			set = true
		}
	}
	return info, set
}

func ffmpegAudio(line string) (Info, bool) {
	var info Info
	set := false
	if m := ffAudioCodecRe.FindStringSubmatch(line); m != nil {
		info.AudioCodec = ptr(m[1])
		set = true
	}
	if m := ffSampleRateRe.FindStringSubmatch(line); m != nil {
		if hz, err := strconv.Atoi(m[1]); err == nil {
			info.SampleRate = ptr(hz)
			set = true
		}
	}
	if m := ffChannelsRe.FindStringSubmatch(line); m != nil {
		info.AudioChannels = ptr(m[1])
		set = true
	}
	if m := ffKbpsRe.FindStringSubmatch(line); m != nil {
		if kbps, err := strconv.ParseFloat(m[1], 64); err == nil {
			info.AudioBitrate = ptr(kbps)
			set = true
		}
	}
	return info, set
}

// The VLC codec maps, log_parsers.py:199-204 and :263-268, in their
// insertion order: Python iterates a dict and takes the FIRST tuple with any
// matching pattern, so order is behaviour.
var (
	vlcVideoCodecs = []struct {
		patterns []string
		codec    string
	}{
		{[]string{"avc", "h.264", "type=0x1b"}, "h264"},
		{[]string{"hevc", "h.265", "type=0x24"}, "hevc"},
		{[]string{"mpeg-2", "type=0x02"}, "mpeg2video"},
		{[]string{"mpeg-4", "type=0x10"}, "mpeg4"},
	}
	vlcAudioCodecs = []struct {
		patterns []string
		codec    string
	}{
		{[]string{"type=0xf", "adts"}, "aac"},
		{[]string{"type=0x03", "type=0x04"}, "mp3"},
		{[]string{"type=0x06", "type=0x81"}, "ac3"},
		{[]string{"type=0x0b", "lpcm"}, "pcm"},
	}
	vlcFPSFractionRe  = regexp.MustCompile(`source fps\s+(\d+)/(\d+)`)
	vlcSourceResRe    = regexp.MustCompile(`source\s+(\d{3,4})x(\d{3,4})`)
	vlcResolutionRe   = regexp.MustCompile(`(\d{3,4})x(\d{3,4})`)
	vlcFPSRe          = regexp.MustCompile(`(\d+\.?\d*)\s*fps`)
	vlcChannelsRe     = regexp.MustCompile(`channels:\s*(\d+)`)
	vlcSampleRateRe   = regexp.MustCompile(`samplerate:\s*(\d+)`)
	vlcHzRe           = regexp.MustCompile(`(\d+)\s*hz`)
	vlcChannelWordsRe = regexp.MustCompile(`\b(mono|stereo|5\.1|7\.1|quad|2\.1)\b`)
)

func vlcVideo(line string) (Info, bool) {
	lower := strings.ToLower(line)
	var info Info
	set := false
	for _, entry := range vlcVideoCodecs {
		if containsAny(lower, entry.patterns) {
			info.VideoCodec = ptr(entry.codec)
			set = true
			break
		}
	}
	if m := vlcFPSFractionRe.FindStringSubmatch(lower); m != nil {
		num, _ := strconv.Atoi(m[1])
		den, _ := strconv.Atoi(m[2])
		if den > 0 {
			info.SourceFPS = ptr(float64(num) / float64(den))
			set = true
		}
	}
	if m := vlcSourceResRe.FindStringSubmatch(lower); m != nil {
		w, _ := strconv.Atoi(m[1])
		h, _ := strconv.Atoi(m[2])
		if resolutionWithin(w, h) {
			info.Resolution = ptr(m[1] + "x" + m[2])
			info.Width, info.Height = ptr(w), ptr(h)
			set = true
		}
	} else if m := vlcResolutionRe.FindStringSubmatch(line); m != nil {
		// The fallback runs against the ORIGINAL line, log_parsers.py:216.
		w, _ := strconv.Atoi(m[1])
		h, _ := strconv.Atoi(m[2])
		if resolutionWithin(w, h) {
			info.Resolution = ptr(m[1] + "x" + m[2])
			info.Width, info.Height = ptr(w), ptr(h)
			set = true
		}
	}
	if info.SourceFPS == nil {
		if m := vlcFPSRe.FindStringSubmatch(lower); m != nil {
			// "25." parses as 25 in both languages; a bare "." does not
			// parse in either and Python's except drops the whole line.
			fps, err := strconv.ParseFloat(m[1], 64)
			if err != nil {
				return Info{}, false
			}
			info.SourceFPS = ptr(fps)
			set = true
		}
	}
	return info, set
}

func vlcAudio(line string) (Info, bool) {
	lower := strings.ToLower(line)
	var info Info
	set := false
	for _, entry := range vlcAudioCodecs {
		if containsAny(lower, entry.patterns) {
			info.AudioCodec = ptr(entry.codec)
			set = true
			break
		}
	}
	if strings.Contains(lower, "channels:") {
		if m := vlcChannelsRe.FindStringSubmatch(lower); m != nil {
			n, _ := strconv.Atoi(m[1])
			name, known := map[int]string{1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}[n]
			if !known {
				name = strconv.Itoa(n)
			}
			info.AudioChannels = ptr(name)
			set = true
		}
	}
	if strings.Contains(lower, "samplerate:") {
		if m := vlcSampleRateRe.FindStringSubmatch(lower); m != nil {
			hz, _ := strconv.Atoi(m[1])
			info.SampleRate = ptr(hz)
			set = true
		}
	}
	if m := vlcHzRe.FindStringSubmatch(lower); m != nil && info.SampleRate == nil {
		hz, _ := strconv.Atoi(m[1])
		info.SampleRate = ptr(hz)
		set = true
	}
	if info.AudioChannels == nil {
		if m := vlcChannelWordsRe.FindStringSubmatch(lower); m != nil {
			info.AudioChannels = ptr(m[1])
			set = true
		}
	}
	return info, set
}

var streamlinkQualityRe = regexp.MustCompile(`(\d+p|\d+x\d+)`)

// streamlinkResolutions is log_parsers.py:335-341's table, and its default
// -- 1920x1080 for any quality not listed, "160p" included -- is the Python
// behaviour, reproduced rather than corrected.
var streamlinkResolutions = map[string][3]int{
	"2160p": {3840, 2160},
	"1080p": {1920, 1080},
	"720p":  {1280, 720},
	"480p":  {854, 480},
	"360p":  {640, 360},
}

func streamlinkVideo(line string) (Info, bool) {
	m := streamlinkQualityRe.FindStringSubmatch(line)
	if m == nil {
		return Info{}, false
	}
	quality := m[1]
	var w, h int
	var resolution string
	if strings.Contains(quality, "x") {
		resolution = quality
		ws, hs, _ := strings.Cut(quality, "x")
		w, _ = strconv.Atoi(ws)
		h, _ = strconv.Atoi(hs)
	} else {
		dims, known := streamlinkResolutions[quality]
		if !known {
			dims = [3]int{1920, 1080}
		}
		w, h = dims[0], dims[1]
		resolution = strconv.Itoa(w) + "x" + strconv.Itoa(h)
	}
	return Info{
		VideoCodec:  ptr("h264"),
		Resolution:  ptr(resolution),
		Width:       ptr(w),
		Height:      ptr(h),
		PixelFormat: ptr("yuv420p"),
	}, true
}

func containsAny(s string, patterns []string) bool {
	for _, p := range patterns {
		if strings.Contains(s, p) {
			return true
		}
	}
	return false
}

func ptr[T any](v T) *T { return &v }
```

### Appendix D — `relay/ffmpeg/progress.go`

**`relay/ffmpeg/progress.go`**

```go
package ffmpeg

import (
	"regexp"
	"strconv"
	"strings"
)

// Progress is what one ffmpeg progress record ("frame=  150 fps=0.0 ...
// speed=11.5x") says, the four values input/manager.py:1102-1135's
// _parse_ffmpeg_stats extracts. A nil pointer is a field the line did not
// carry.
type Progress struct {
	// Speed is the cumulative playback-to-wall-clock ratio ffmpeg reports.
	Speed *float64
	// FPS is ffmpeg's own output frame rate.
	FPS *float64
	// ActualFPS is FPS / Speed when both are present and Speed is positive.
	ActualFPS *float64
	// OutputBitrateKbps is the output bitrate in kbit/s, with an 'm' or 'g'
	// unit scaled up.
	OutputBitrateKbps *float64
}

// The three regexes, input/manager.py:1109, :1113 and :1117, verbatim.
//
// speedRe STOPS AT THE 'e' OF SCIENTIFIC NOTATION, and that is parity-matrix
// row 28 (issue #227): real ffmpeg emits "speed=1.41e+03x" on a truncated
// input and both status surfaces then report 1.41, a thousandfold
// under-report. Spec D5 is strict parity, defects included; do not widen the
// character class without changing the Python side and the row together.
var (
	speedRe   = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)
	fpsRe     = regexp.MustCompile(`fps=\s*([0-9.]+)`)
	bitrateRe = regexp.MustCompile(`(?i)bitrate=\s*([0-9.]+(?:\.[0-9]+)?)\s*([kmg]?)bits/s`)
)

// IsProgressLine is the gate input/manager.py:993 and :1017 apply before
// calling _parse_ffmpeg_stats: the substring "frame=" anywhere in the line.
func IsProgressLine(line string) bool { return strings.Contains(line, "frame=") }

// ParseProgress extracts the four values from a progress record.
//
// It returns false when the line carries none of them, AND when a captured
// number does not parse: `[0-9.]+` happily captures "1.2.3", Python's float()
// then raises, and the except at input/manager.py:1249 swallows the WHOLE
// line -- no stats update, no buffering check. A Go port that parsed the
// fields it could and skipped the one it could not would arm the buffering
// detector on a line Python ignores.
func ParseProgress(line string) (Progress, bool) {
	var p Progress
	if m := speedRe.FindStringSubmatch(line); m != nil {
		v, err := strconv.ParseFloat(m[1], 64)
		if err != nil {
			return Progress{}, false
		}
		p.Speed = &v
	}
	if m := fpsRe.FindStringSubmatch(line); m != nil {
		v, err := strconv.ParseFloat(m[1], 64)
		if err != nil {
			return Progress{}, false
		}
		p.FPS = &v
	}
	if m := bitrateRe.FindStringSubmatch(line); m != nil {
		v, err := strconv.ParseFloat(m[1], 64)
		if err != nil {
			return Progress{}, false
		}
		switch strings.ToLower(m[2]) {
		case "m":
			v *= 1000
		case "g":
			v *= 1_000_000
		}
		p.OutputBitrateKbps = &v
	}
	if p.FPS != nil && p.Speed != nil && *p.Speed > 0 {
		actual := *p.FPS / *p.Speed
		p.ActualFPS = &actual
	}
	if p.Speed == nil && p.FPS == nil && p.OutputBitrateKbps == nil {
		return Progress{}, false
	}
	return p, true
}

// Round rounds to `places` decimal places the way Python's round() does on a
// float: on the exact decimal expansion of the binary value, ties to even.
// strconv's 'f' formatting is correctly rounded on the same expansion, so
// formatting and parsing back gives the same double Python's round() gives,
// where math.Round(x*1000)/1000 can differ by one unit in the last place on
// a value like 0.0005 whose binary form is not what it looks like.
//
// It exists because the Python relay stores every stat as str(round(x, n))
// (input/manager.py:1260-1269, channel_service.py:858-880) and the status
// endpoints read that string back as a float, so the value on the wire is
// the rounded one.
func Round(x float64, places int) float64 {
	v, err := strconv.ParseFloat(strconv.FormatFloat(x, 'f', places, 64), 64)
	if err != nil {
		return x
	}
	return v
}
```

### Appendix E — `relay/ffmpeg/detector.go`

**`relay/ffmpeg/detector.go`**

```go
package ffmpeg

import "time"

// Detector is the buffering state machine of input/manager.py:1165-1247,
// lifted out of _parse_ffmpeg_stats so it can be driven with an injected
// clock. It decides nothing about what happens on a timeout: Python calls
// _try_next_stream() there (parity-matrix row 1, 2c-5's), and the source
// that owns this detector decides what a TimedOut verdict means for it.
//
// THRESHOLDS ARE SNAPSHOTTED BY THE CALLER, not read here: Python reads
// buffering_speed and buffering_timeout once in StreamManager.__init__
// (input/manager.py:61-62, parity-matrix row 5), and this struct is built
// once per source with the values that tune's next-source answer carried.
type Detector struct {
	// Threshold is buffering_speed: a reported speed strictly below it is
	// buffering (input/manager.py:1166's `<`), at or above it is not
	// (:1235's `>=`).
	Threshold float64

	// Timeout is buffering_timeout: buffering sustained for LONGER than this
	// (:1178's `>`) is a timeout.
	Timeout time.Duration

	// Now is the clock. Nil means time.Now.
	Now func() time.Time

	buffering bool
	since     time.Time
}

// Verdict is what one observation changed.
type Verdict int

// The five verdicts. Continuing and Started both mean "the channel is
// buffering now" -- Python writes the BUFFERING state on every sub-threshold
// sample (:1232-1234), not only the first -- and are told apart because the
// first is when Python raises the channel_buffering event (:1217-1226).
const (
	// Steady: speed at or above the threshold, and it already was.
	Steady Verdict = iota
	// Started: the first sub-threshold sample after being fine.
	Started
	// Continuing: a further sub-threshold sample, within the timeout.
	Continuing
	// TimedOut: a sub-threshold sample more than Timeout after buffering
	// started. Python tries the next stream here; on success it resets
	// (Reset), on failure it stays buffering and tries again on the NEXT
	// sample (:1210), so this verdict repeats until something resets it.
	TimedOut
	// Ended: speed back at or above the threshold after buffering.
	Ended
)

func (v Verdict) String() string {
	switch v {
	case Steady:
		return "steady"
	case Started:
		return "buffering started"
	case Continuing:
		return "buffering"
	case TimedOut:
		return "buffering timeout"
	case Ended:
		return "buffering ended"
	}
	return "unknown"
}

// Observe feeds one reported speed to the detector.
func (d *Detector) Observe(speed float64) Verdict {
	now := d.Now
	if now == nil {
		now = time.Now
	}
	if speed < d.Threshold {
		if !d.buffering {
			d.buffering = true
			d.since = now()
			return Started
		}
		// input/manager.py:1174-1175's `if buffering_start_time is None`
		// arm is unreachable: the two are set together at :1213-1214 and
		// cleared together at :1185-1186 and :1240-1241. Not ported.
		if now().Sub(d.since) > d.Timeout {
			return TimedOut
		}
		return Continuing
	}
	if d.buffering {
		d.buffering = false
		d.since = time.Time{}
		return Ended
	}
	return Steady
}

// Buffering reports whether the last observation left the channel buffering.
func (d *Detector) Buffering() bool { return d.buffering }

// Reset is the successful-switch branch (:1185-1186): buffering cleared and
// the clock forgotten, so the NEXT sub-threshold sample starts a fresh
// window. 2c-5's failover calls it; nothing in 2c-4 does.
func (d *Detector) Reset() {
	d.buffering = false
	d.since = time.Time{}
}
```

### Appendix F — the spawn — `spawn.go`, `spawn_linux.go`, `spawn_other.go`

**`relay/ffmpeg/spawn.go`**

```go
package ffmpeg

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os/exec"
	"strings"
	"syscall"
	"time"
)

// Process is one running transcode subprocess: ffmpeg, VLC or streamlink,
// spawned from a Stream Profile's command and argv.
//
// THE OBSERVABLE CONTRACT IS input/manager.py:823-923's, fd for fd. stdin is
// /dev/null (POSIX_SPAWN_OPEN of /dev/null onto fd 0 there; os/exec's
// default for a nil Stdin here). stdout, fd 1, is the pipe the relay reads
// video from -- the profile's `pipe:1` -- and Stdout below is its read end.
// stderr, fd 2, is a pipe a reader drains line by line (ReadStderr), the
// port of the stderr reader thread. The environment is the relay's own,
// exactly as os.environ is passed there. The executable is resolved on PATH
// (shutil.which there, exec.LookPath here).
//
// WHAT DIFFERS IS D5's FIRST NAMED EXCEPTION. Python spawns with
// os.posix_spawn -- chosen because fork() hangs in gevent's _before_fork
// atfork handler, a reason that does not exist in Go and is not cargo-culted
// here -- with no setsid and no PDEATHSIG, so an ffmpeg blocked on a stalled
// upstream survives its worker and holds a provider slot (CLAUDE.md,
// § Operationally). This process is started in its own process group
// (Setpgid) so a kill reaches everything it forked, and on Linux with
// Pdeathsig SIGKILL so it dies with the relay. sysProcAttr in spawn_linux.go
// and spawn_other.go carries the per-OS half: syscall.SysProcAttr has no
// Pdeathsig field on darwin, and the relay is built for Linux only
// (docker/Dockerfile's relay-builder stage) but tested on both.
//
// KILL SEMANTICS MATCH PYTHON'S. _close_socket (input/manager.py:1737-1749)
// sends SIGKILL, never SIGTERM, and waits half a second. Cancel below sends
// SIGKILL to the whole process group and Wait gives the process WaitDelay to
// go, which is that same half second.
type Process struct {
	cmd    *exec.Cmd
	stdout io.ReadCloser
	stderr io.ReadCloser
	cancel context.CancelFunc
	// ended is closed by Wait once the process has been reaped.
	ended chan struct{}
	err   error
}

// KillWait is how long a killed process is given to be reaped before Wait
// stops waiting for its pipes: input/manager.py:1746's wait(timeout=0.5).
const KillWait = 500 * time.Millisecond

// ErrCommandIsAURL refuses a Stream Profile whose command carries a scheme.
// A command is an executable name; one that is a URL would put a provider
// credential into every os/exec error message (exec.Error prints the NAME),
// which is the one shape redact.Error is not built to strip. Python would
// try to spawn it and fail; this fails earlier and says why.
var ErrCommandIsAURL = errors.New("ffmpeg: a stream profile's command must be an executable, not a URL")

// ErrExited is a process that ended on its own with a non-zero status.
//
// Code is Python's returncode (input/manager.py:867-873): the exit status
// when the process exited, and MINUS the signal number when it was killed by
// one, so a SIGKILLed process reports -9. Python reads the code only to log
// it -- every end of the stdout pipe is "Server closed connection"
// (:1868-1872) whatever the status -- and the source that owns this process
// decides what to do with a non-zero one.
type ErrExited struct{ Code int }

func (e *ErrExited) Error() string {
	if e.Code < 0 {
		return fmt.Sprintf("ffmpeg: the process was killed by signal %d", -e.Code)
	}
	return fmt.Sprintf("ffmpeg: the process exited with status %d", e.Code)
}

// Start spawns command with argv, in its own process group, and returns once
// it is running. ctx cancellation kills the whole group.
func Start(ctx context.Context, command string, argv []string) (*Process, error) {
	if strings.Contains(command, "://") {
		return nil, ErrCommandIsAURL
	}
	ctx, cancel := context.WithCancel(ctx)
	// #nosec G204 -- the command and its arguments ARE the Stream Profile:
	// an operator-configured executable and the argv Django built from its
	// parameters (StreamProfile.build_command). Spawning them is this
	// function's whole job, and the URL-in-command case is refused above.
	cmd := exec.CommandContext(ctx, command, argv...)
	cmd.SysProcAttr = sysProcAttr()
	cmd.Cancel = func() error {
		// The whole group, not just the leader: with Setpgid the child's
		// own pid is the group id, and the negative form addresses the
		// group. A process that has already gone answers ESRCH, which
		// os/exec treats as "already dead".
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	cmd.WaitDelay = KillWait

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		return nil, fmt.Errorf("ffmpeg: opening the stdout pipe: %w", err) // credential-logging: ok - an os.Pipe failure, no URL anywhere in it
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		cancel()
		return nil, fmt.Errorf("ffmpeg: opening the stderr pipe: %w", err) // credential-logging: ok - an os.Pipe failure, no URL anywhere in it
	}
	if err := cmd.Start(); err != nil {
		cancel()
		// exec.Error carries the command NAME (refused above if it were a
		// URL); a *fs.PathError carries the executable's path. Neither
		// carries argv, which is where the URL is.
		return nil, fmt.Errorf("ffmpeg: starting %s: %w", command, err) // credential-logging: ok - exec.Error and PathError name the executable, never argv, and a URL-shaped command is refused before this line
	}
	return &Process{cmd: cmd, stdout: stdout, stderr: stderr, cancel: cancel, ended: make(chan struct{})}, nil
}

// Stdout is the read end of the process's fd 1: the video bytes.
func (p *Process) Stdout() io.Reader { return p.stdout }

// PID is the process id, for tests and logs.
func (p *Process) PID() int { return p.cmd.Process.Pid }

// ReadStderr drains fd 2 to EOF, calling fn for every line.
//
// THE SPLIT IS input/manager.py:981-1003's: whichever of CR or LF comes
// first ends a line, because ffmpeg TERMINATES a progress record with CR
// (rewriting one status line in place) and ends everything else with LF; a
// reader that split on LF alone would see one enormous line per tune.
// Empty lines are skipped after trimming, as :994-996 does. And a buffer
// that grows past 1 KiB with no terminator and no "frame=" in it is flushed
// as a line (:986-991), which is how a long diagnostic with no newline still
// reaches the log rather than waiting for the next record.
//
// It never returns an error: a broken stderr pipe means the process is
// going, and Wait is where that is reported.
func (p *Process) ReadStderr(fn func(line string)) {
	var buf []byte
	chunk := make([]byte, 4096) // input/manager.py:976's read size
	for {
		n, err := p.stderr.Read(chunk)
		if n > 0 {
			buf = append(buf, chunk[:n]...)
			for {
				cr := bytes.IndexByte(buf, '\r')
				nl := bytes.IndexByte(buf, '\n')
				if cr == -1 && nl == -1 {
					if len(buf) > 1024 && !bytes.Contains(buf, []byte("frame=")) {
						emit(fn, buf)
						buf = buf[:0]
					}
					break
				}
				var line []byte
				if cr != -1 && (nl == -1 || cr < nl) {
					line, buf = buf[:cr], buf[cr+1:]
				} else {
					line, buf = buf[:nl], buf[nl+1:]
				}
				emit(fn, line)
			}
		}
		if err != nil {
			break
		}
	}
	// :1015-1021: whatever is left when the pipe closes is one last line.
	emit(fn, buf)
}

func emit(fn func(string), line []byte) {
	// utf-8 with errors ignored there (:992); Go strings carry the bytes as
	// they are and a parser regex simply fails to match an invalid sequence.
	text := strings.TrimSpace(string(line))
	if text != "" {
		fn(text)
	}
}

// Kill sends SIGKILL to the process group. Idempotent; safe after exit.
func (p *Process) Kill() { p.cancel() }

// Wait reaps the process and reports how it ended: nil for exit status 0,
// *ErrExited otherwise, and ctx.Err()-shaped errors are NOT what it returns
// -- a process this package killed reports ErrExited{Code: -9}, and the
// caller knows whether it asked for that.
//
// It closes the stdout pipe first, so a process still writing to fd 1 after
// the reader has stopped gets EPIPE rather than blocking forever on a full
// pipe nobody drains. Callable more than once.
func (p *Process) Wait() error {
	select {
	case <-p.ended:
		return p.err
	default:
	}
	_ = p.stdout.Close()
	err := p.cmd.Wait()
	// exec.CommandContext reports the context's own error once it has
	// killed the process, which would make "we cancelled it" and "it died
	// of signal 9 on its own" indistinguishable. The ProcessState is the
	// fact; the context is the reason, and the caller holds the reason.
	if p.cmd.ProcessState != nil {
		if status, ok := p.cmd.ProcessState.Sys().(syscall.WaitStatus); ok {
			switch {
			case status.Exited() && status.ExitStatus() == 0:
				err = nil
			case status.Exited():
				err = &ErrExited{Code: status.ExitStatus()}
			case status.Signaled():
				err = &ErrExited{Code: -int(status.Signal())}
			default:
				err = &ErrExited{Code: -1}
			}
		}
	} else if err != nil {
		err = &ErrExited{Code: -1}
	}
	p.err = err
	p.cancel()
	close(p.ended)
	return err
}
```

**`relay/ffmpeg/spawn_linux.go`**

```go
//go:build linux

package ffmpeg

import "syscall"

// sysProcAttr is the Linux half of spec D5's first exception: a process
// group of its own, so Kill reaches everything the child forked, and
// SIGKILL on parent death, so an ffmpeg blocked on a stalled upstream cannot
// outlive the relay and hold a provider slot (CLAUDE.md, § Operationally,
// the defect Python's os.posix_spawn without PDEATHSIG leaves open).
//
// Pdeathsig is delivered when the THREAD that forked the child exits, not
// the process (prctl(2)). Go's runtime never exits an OS thread except when
// a goroutine that called runtime.LockOSThread returns while still locked,
// and nothing in this module locks a thread, so the forking thread lives as
// long as the process does. Stated because it is the one way this could
// fire early, and it is guarded by convention rather than by code.
func sysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
}
```

**`relay/ffmpeg/spawn_other.go`**

```go
//go:build !linux

package ffmpeg

import "syscall"

// sysProcAttr on a non-Linux host: the process group only. There is no
// Pdeathsig field in syscall.SysProcAttr here -- the relay is built for
// Linux (docker/Dockerfile's relay-builder stage) and only tested elsewhere
// -- so the parent-death half of D5's exception is a Linux-only property,
// pinned by spawn_linux_test.go and honestly absent on a darwin developer
// host rather than emulated.
func sysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setpgid: true}
}
```

### Appendix G — the `ffmpeg` tests

**`relay/ffmpeg/parse_test.go`**

```go
package ffmpeg

import (
	"reflect"
	"strings"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

func s(v string) *string   { return &v }
func i(v int) *int         { return &v }
func f(v float64) *float64 { return &v }

// A SUPERSET of what apps/proxy/live_proxy/tests/test_property_log_parsers.py
// exercises, as a table. Every FFmpeg row below is a REAL line: the first
// four are taken verbatim from the captured corpus (see
// TestTheCorpusPreambleParsesAsPythonStoresIt for the proof they are), and
// the shapes the Python property tests generate are represented by one
// concrete instance each.
func TestCanParseAndParseAgreeWithThePythonParsers(t *testing.T) {
	for _, tc := range []struct {
		name string
		tool Tool
		line string
		kind Kind
		want Info
		ok   bool
	}{
		{
			"ffmpeg input line from the corpus", ToolFFmpeg,
			"Input #0, mpegts, from 'http://127.0.0.1:33123/live.ts':",
			KindInput, Info{InputFormat: s("mpegts")}, true,
		},
		{
			"ffmpeg video line from the corpus: no kb/s, so no bitrate", ToolFFmpeg,
			"  Stream #0:0[0x100]: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 320x180 [SAR 1:1 DAR 16:9], 25 fps, 25 tbr, 90k tbn, start 1.423222",
			KindVideo, Info{VideoCodec: s("h264"), Resolution: s("320x180"), Width: i(320), Height: i(180),
				SourceFPS: f(25), PixelFormat: s("yuv420p")}, true,
		},
		{
			"ffmpeg audio line from the corpus", ToolFFmpeg,
			"  Stream #0:1[0x101]: Audio: aac (LC) ([15][0][0][0] / 0x000F), 44100 Hz, mono, fltp, 66 kb/s, start 1.400000",
			KindAudio, Info{AudioCodec: s("aac"), SampleRate: i(44100), AudioChannels: s("mono"), AudioBitrate: f(66)}, true,
		},
		{
			"ffmpeg OUTPUT video line still parses as video: phase tracking is the caller's", ToolFFmpeg,
			"  Stream #0:0: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 320x180 [SAR 1:1 DAR 16:9], q=2-31, 25 fps, 25 tbr, 90k tbn",
			KindVideo, Info{VideoCodec: s("h264"), Resolution: s("320x180"), Width: i(320), Height: i(180),
				SourceFPS: f(25), PixelFormat: s("yuv420p")}, true,
		},
		{
			"the property test's video shape, with a bitrate and a fractional fps", ToolFFmpeg,
			"  Stream #0:0: Video: hevc (High), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 4500 kb/s, 29.97 fps, 90k tbn",
			KindVideo, Info{VideoCodec: s("hevc"), Resolution: s("1920x1080"), Width: i(1920), Height: i(1080),
				SourceFPS: f(29.97), PixelFormat: s("yuv420p"), VideoBitrate: f(4500)}, true,
		},
		{
			"a resolution outside 100..10000 is dropped and the codec still parses", ToolFFmpeg,
			"  Stream #0:0: Video: h264 (High), yuv420p, 12000x1080, 25.00 fps",
			KindVideo, Info{VideoCodec: s("h264"), SourceFPS: f(25), PixelFormat: s("yuv420p")}, true,
		},
		{
			"the property test's audio shape", ToolFFmpeg,
			"  Stream #0:1(und): Audio: mp3 (LC), 48000 Hz, stereo, fltp, 128 kb/s",
			KindAudio, Info{AudioCodec: s("mp3"), SampleRate: i(48000), AudioChannels: s("stereo"), AudioBitrate: f(128)}, true,
		},
		{
			"the channel word is matched case-insensitively", ToolFFmpeg,
			"  Stream #0:1: Audio: ac3, 48000 Hz, 5.1(side), fltp, 384 kb/s",
			KindAudio, Info{AudioCodec: s("ac3"), SampleRate: i(48000), AudioChannels: s("5.1"), AudioBitrate: f(384)}, true,
		},
		{
			"a progress record is not a stream line", ToolFFmpeg,
			"frame=  150 fps=0.0 q=-1.0 size=     352KiB time=00:00:05.85 bitrate= 492.2kbits/s speed=11.5x",
			"", Info{}, false,
		},
		{
			"an Input line with nothing after the number parses to nothing", ToolFFmpeg,
			"Input #0", KindInput, Info{}, false,
		},
		{
			"vlc ts demux video by stream type", ToolVLC,
			"[00007f] ts demux debug: pid[0x100] type=0x1b es_id=0x0 -- video",
			KindVLCVideo, Info{VideoCodec: s("h264")}, true,
		},
		{
			"vlc ts demux audio by stream type", ToolVLC,
			"[00007f] ts demux debug: pid[0x101] type=0xf audio",
			KindVLCAudio, Info{AudioCodec: s("aac")}, true,
		},
		{
			"vlc decoder audio format", ToolVLC,
			"[00007f] main decoder debug: AAC channels: 2 samplerate: 48000",
			KindVLCAudio, Info{AudioChannels: s("stereo"), SampleRate: i(48000)}, true,
		},
		{
			"vlc decoder audio with an unnamed channel count is the number as a string", ToolVLC,
			"[00007f] main decoder debug: AAC channels: 3 samplerate: 44100",
			KindVLCAudio, Info{AudioChannels: s("3"), SampleRate: i(44100)}, true,
		},
		{
			"vlc transcode source fps and resolution", ToolVLC,
			"[00007f] stream_out_transcode debug: source fps 30/1, source 1280x720",
			KindVLCVideo, Info{SourceFPS: f(30), Resolution: s("1280x720"), Width: i(1280), Height: i(720)}, true,
		},
		{
			// "avcodec" contains "avc", the first pattern of the h264 tuple
			// (log_parsers.py:200), so a line that names no codec is
			// reported as h264. Verified against the Python parser before
			// this row was written; a port that tokenised would diverge.
			"vlc decoder video: the generic resolution and fps, and the avc-in-avcodec quirk", ToolVLC,
			"[00007f] avcodec decoder debug: using frame size 1920x1080 at 25 fps",
			KindVLCVideo, Info{VideoCodec: s("h264"), Resolution: s("1920x1080"), Width: i(1920), Height: i(1080), SourceFPS: f(25)}, true,
		},
		{
			"vlc input failure is recognised and parses to nothing", ToolVLC,
			"[00007f] main input error: unable to open the MRL 'http://x/y'",
			KindVLCInputFailed, Info{}, false,
		},
		{
			"streamlink named quality", ToolStreamlink,
			"[cli][info] Opening stream: 720p (hls)",
			KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("1280x720"), Width: i(1280), Height: i(720), PixelFormat: s("yuv420p")}, true,
		},
		{
			"streamlink explicit resolution", ToolStreamlink,
			"[cli][info] Opening stream: 854x480 (hls)",
			KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("854x480"), Width: i(854), Height: i(480), PixelFormat: s("yuv420p")}, true,
		},
		{
			"streamlink unknown quality DEFAULTS to 1080p -- log_parsers.py:342, reproduced not fixed", ToolStreamlink,
			"[cli][info] Available streams: 160p, 360p, 720p (best)",
			KindStreamlink, Info{VideoCodec: s("h264"), Resolution: s("1920x1080"), Width: i(1920), Height: i(1080), PixelFormat: s("yuv420p")}, true,
		},
		{
			"an ffmpeg line is not a vlc line", ToolVLC,
			"Input #0, mpegts, from 'http://127.0.0.1:33123/live.ts':",
			"", Info{}, false,
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if kind := CanParse(tc.tool, tc.line); kind != tc.kind {
				t.Fatalf("CanParse(%s) = %q, want %q", tc.tool, kind, tc.kind)
			}
			if tc.kind == "" {
				return
			}
			got, ok := Parse(tc.kind, tc.line)
			if ok != tc.ok {
				t.Fatalf("Parse ok = %v, want %v (got %s)", ok, tc.ok, describe(got))
			}
			if ok && !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("Parse =\n  %s\nwant\n  %s", describe(got), describe(tc.want))
			}
		})
	}
}

// ToolFor is the WHOLE command lowercased, not its basename
// (input/manager.py:797-803): "/usr/bin/ffmpeg" is unknown and falls back to
// auto-detection. A port that took the basename would route a line
// differently from Python for every profile whose command is a path.
func TestToolForMatchesTheWholeCommandNotItsBasename(t *testing.T) {
	for cmd, want := range map[string]Tool{"ffmpeg": ToolFFmpeg, "FFmpeg": ToolFFmpeg, "cvlc": ToolVLC, "vlc": ToolVLC, "streamlink": ToolStreamlink} {
		if got, ok := ToolFor(cmd); !ok || got != want {
			t.Errorf("ToolFor(%q) = %q, %v; want %q", cmd, got, ok, want)
		}
	}
	for _, cmd := range []string{"/usr/bin/ffmpeg", "ffmpeg-static", ""} {
		if got, ok := ToolFor(cmd); ok {
			t.Errorf("ToolFor(%q) = %q, want unknown -- Python's map is keyed on the whole string", cmd, got)
		}
	}
}

// AutoParse tries ffmpeg, then vlc, then streamlink (LogParserFactory._parsers'
// insertion order), and reports the FIRST that parses something. The vlc
// input-failure kind is recognised by can_parse but parses to nothing, so
// auto_parse never surfaces it -- which is why the socket-closing branch in
// input/manager.py is reachable only when the command is literally vlc.
func TestAutoParseFollowsTheFactoryOrderAndNeverReportsAVLCInputFailure(t *testing.T) {
	kind, info, ok := AutoParse("  Stream #0:0: Video: h264, yuv420p, 320x180, 25 fps")
	if !ok || kind != KindVideo || info.VideoCodec == nil || *info.VideoCodec != "h264" {
		t.Fatalf("AutoParse(ffmpeg video) = %q, %s, %v", kind, describe(info), ok)
	}
	// A line BOTH the ffmpeg and vlc parsers recognise: "stream #" with
	// "video:" for ffmpeg, "decoder" with "x" for vlc. ffmpeg wins by order.
	kind, _, ok = AutoParse("Stream #0 decoder Video: h264 320x180")
	if !ok || kind != KindVideo {
		t.Fatalf("a line both parsers recognise was reported as %q; the factory tries ffmpeg first", kind)
	}
	if kind, _, ok := AutoParse("[00007f] main input error: unable to open the MRL 'http://x/y'"); ok {
		t.Fatalf("AutoParse reported %q for a VLC input failure; auto_parse returns None for it", kind)
	}
}

// The corpus preamble, driven the way _log_stderr_content drives it: every
// line through the ffmpeg parser, and the union of what parses is exactly
// the stream info Python's status endpoint would carry for this capture.
// Read from the same fixture the Python tests read, never from a copy.
func TestTheCorpusPreambleParsesAsPythonStoresIt(t *testing.T) {
	preamble, _ := relaytest.SplitCorpus(relaytest.Corpus("normal"))
	var merged Info
	parsed := 0
	for _, line := range strings.Split(string(preamble), "\n") {
		kind := CanParse(ToolFFmpeg, strings.TrimSpace(line))
		if kind == "" {
			continue
		}
		info, ok := Parse(kind, strings.TrimSpace(line))
		if !ok {
			continue
		}
		parsed++
		merged = mergeForTest(merged, info)
	}
	if parsed < 3 {
		t.Fatalf("only %d preamble lines parsed; the corpus has an Input line, a video Stream line and an audio Stream line", parsed)
	}
	want := Info{
		InputFormat: s("mpegts"),
		VideoCodec:  s("h264"), Resolution: s("320x180"), Width: i(320), Height: i(180),
		SourceFPS: f(25), PixelFormat: s("yuv420p"),
		AudioCodec: s("aac"), SampleRate: i(44100), AudioChannels: s("mono"), AudioBitrate: f(66),
	}
	if !reflect.DeepEqual(merged, want) {
		t.Fatalf("the merged preamble is\n  %s\nwant\n  %s -- re-derive against the capture (CAPTURE.md) before touching the parser",
			describe(merged), describe(want))
	}
}

// mergeForTest is the hset semantics: a later non-nil field overwrites, a
// nil one leaves the earlier value standing.
func mergeForTest(into, from Info) Info {
	if from.VideoCodec != nil {
		into.VideoCodec = from.VideoCodec
	}
	if from.Resolution != nil {
		into.Resolution = from.Resolution
	}
	if from.Width != nil {
		into.Width = from.Width
	}
	if from.Height != nil {
		into.Height = from.Height
	}
	if from.SourceFPS != nil {
		into.SourceFPS = from.SourceFPS
	}
	if from.PixelFormat != nil {
		into.PixelFormat = from.PixelFormat
	}
	if from.VideoBitrate != nil {
		into.VideoBitrate = from.VideoBitrate
	}
	if from.AudioCodec != nil {
		into.AudioCodec = from.AudioCodec
	}
	if from.SampleRate != nil {
		into.SampleRate = from.SampleRate
	}
	if from.AudioChannels != nil {
		into.AudioChannels = from.AudioChannels
	}
	if from.AudioBitrate != nil {
		into.AudioBitrate = from.AudioBitrate
	}
	if from.InputFormat != nil {
		into.InputFormat = from.InputFormat
	}
	return into
}

func describe(info Info) string {
	var parts []string
	add := func(name string, v any) {
		switch p := v.(type) {
		case *string:
			if p != nil {
				parts = append(parts, name+"="+*p)
			}
		case *int:
			if p != nil {
				parts = append(parts, name+"="+strings.TrimSpace(strings.Repeat(" ", 0)+itoa(*p)))
			}
		case *float64:
			if p != nil {
				parts = append(parts, name+"="+ftoa(*p))
			}
		}
	}
	add("video_codec", info.VideoCodec)
	add("resolution", info.Resolution)
	add("width", info.Width)
	add("height", info.Height)
	add("source_fps", info.SourceFPS)
	add("pixel_format", info.PixelFormat)
	add("video_bitrate", info.VideoBitrate)
	add("audio_codec", info.AudioCodec)
	add("sample_rate", info.SampleRate)
	add("audio_channels", info.AudioChannels)
	add("audio_bitrate", info.AudioBitrate)
	add("stream_type", info.InputFormat)
	if len(parts) == 0 {
		return "{}"
	}
	return "{" + strings.Join(parts, " ") + "}"
}
```

**`relay/ffmpeg/format_test.go`**

```go
package ffmpeg

import "strconv"

func itoa(v int) string     { return strconv.Itoa(v) }
func ftoa(v float64) string { return strconv.FormatFloat(v, 'g', -1, 64) }
```

**`relay/ffmpeg/progress_test.go`**

```go
package ffmpeg

import (
	"regexp"
	"strconv"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The whole speed field, exponent included -- what the production regex
// declines to read. The gap between the two is parity-matrix row 28.
var fullSpeedRe = regexp.MustCompile(`speed=\s*([0-9.]+(?:[eE][+-]?[0-9]+)?)x?`)

// PINS A DEFECT: issue #227, parity-matrix row 28. Do not "fix" this.
//
// The truncation capture's one record reads speed=<mantissa>e+03x on a real
// ffmpeg 8.1.2. The production regex stops at the 'e' and reports the
// mantissa, a roughly thousandfold under-report; D5 is strict parity, defects
// included, so this asserts the WRONG value. It fails if someone widens the
// character class to read the exponent, which is exactly the change that must
// not be made without changing the Python side and the row together.
func TestAScientificNotationSpeedIsUnderReportedAsItsMantissa(t *testing.T) {
	_, records := relaytest.SplitCorpus(relaytest.Corpus("truncation"))
	if len(records) != 1 {
		t.Fatalf("the truncation capture carries %d records, want exactly 1 (CAPTURE.md)", len(records))
	}
	record := string(records[0])
	actual, _ := strconv.ParseFloat(fullSpeedRe.FindStringSubmatch(record)[1], 64)
	mantissa, _ := strconv.ParseFloat(speedRe.FindStringSubmatch(record)[1], 64)
	if actual/mantissa < 100 {
		t.Fatalf("the truncation capture no longer carries a scientific-notation speed=; "+
			"re-derive this test against the new capture (CAPTURE.md): %q", record)
	}

	p, ok := ParseProgress(record)
	if !ok || p.Speed == nil {
		t.Fatalf("the record did not parse as progress: %q", record)
	}
	if *p.Speed != mantissa {
		t.Fatalf("Speed = %v, want the mantissa %v", *p.Speed, mantissa)
	}
	if *p.Speed >= actual/100 {
		t.Fatalf("the parser reported the true speed %v; #227 appears to have been fixed, "+
			"which makes this row a parity CHANGE, not a pin", *p.Speed)
	}
}

// Every shape CAPTURE.md names as one a hand-written line would have got
// wrong, against the parser: the space-padded speed, the Lsize= final record,
// the elapsed= trailer, plus the unit scaling and the actual-fps derivation.
func TestParseProgressReadsTheRealRecordShapes(t *testing.T) {
	for _, tc := range []struct {
		name         string
		line         string
		speed, fps   float64
		kbps, actual float64
	}{
		{"padded short speed", "frame=  174 fps=171 q=-1.0 size=     421KiB time=00:00:06.89 bitrate= 500.3kbits/s speed= 6.8x elapsed=0:00:01.01    ", 6.8, 171, 500.3, 171 / 6.8},
		{"three-space-padded integer speed", "frame=   12 fps=0.0 q=-1.0 size=      30KiB time=00:00:00.48 bitrate= 512.0kbits/s speed=   1x", 1, 0, 512, 0},
		{"the Lsize final record", "frame=  819 fps= 21 q=-1.0 Lsize=    2016KiB time=00:00:32.67 bitrate= 505.5kbits/s speed=0.848x elapsed=0:00:38.52    ", 0.848, 21, 505.5, 21 / 0.848},
		{"megabits are scaled to kilobits", "frame=1 fps=25 q=-1.0 size=1KiB time=00:00:00.04 bitrate=  2.5Mbits/s speed=1.0x", 1, 25, 2500, 25},
		{"gigabits too", "frame=1 fps=25 q=-1.0 size=1KiB time=00:00:00.04 bitrate=  1.5Gbits/s speed=2x", 2, 25, 1_500_000, 12.5},
	} {
		t.Run(tc.name, func(t *testing.T) {
			p, ok := ParseProgress(tc.line)
			if !ok {
				t.Fatalf("did not parse: %q", tc.line)
			}
			if p.Speed == nil || *p.Speed != tc.speed {
				t.Errorf("Speed = %v, want %v", deref(p.Speed), tc.speed)
			}
			if p.FPS == nil || *p.FPS != tc.fps {
				t.Errorf("FPS = %v, want %v", deref(p.FPS), tc.fps)
			}
			if p.OutputBitrateKbps == nil || *p.OutputBitrateKbps != tc.kbps {
				t.Errorf("OutputBitrateKbps = %v, want %v", deref(p.OutputBitrateKbps), tc.kbps)
			}
			if tc.actual == 0 {
				// fps=0.0 with a positive speed still divides: 0/1 = 0,
				// and Python computes it (actual_fps = 0/1.0 = 0.0).
				if p.ActualFPS == nil || *p.ActualFPS != 0 {
					t.Errorf("ActualFPS = %v, want 0", deref(p.ActualFPS))
				}
				return
			}
			if p.ActualFPS == nil || *p.ActualFPS != tc.actual {
				t.Errorf("ActualFPS = %v, want %v", deref(p.ActualFPS), tc.actual)
			}
		})
	}
}

// A captured number that float() would refuse drops the WHOLE line, as
// input/manager.py:1249's except does -- not the one field. "1.2.3" is what
// `[0-9.]+` captures from a corrupted record; a partial parse would feed the
// buffering detector a speed Python never saw.
func TestAnUnparseableNumberDropsTheWholeRecord(t *testing.T) {
	if p, ok := ParseProgress("frame=1 fps=25 q=-1.0 bitrate= 500kbits/s speed=1.2.3x"); ok {
		t.Fatalf("a record with speed=1.2.3x parsed as %+v; Python drops the line", p)
	}
	// The frame= gate is the CALLER's (input/manager.py:993 and :1017
	// check it before calling _parse_ffmpeg_stats), which is why it is a
	// separate predicate rather than folded into ParseProgress.
	if IsProgressLine("fps=25 speed=1.0x") {
		t.Fatal("a line without frame= is not a progress record (input/manager.py:993)")
	}
	if !IsProgressLine("frame=  150 fps=0.0 q=-1.0 speed=11.5x") {
		t.Fatal("a frame= line is a progress record")
	}
	if _, ok := ParseProgress("frame=1 q=-1.0"); ok {
		t.Fatal("a frame= line carrying none of the three fields parsed as progress")
	}
}

// Round is Python's round(): correctly rounded on the exact binary value.
// Every expected value below was produced by `python3 -c 'print(round(x, n))'`
// rather than reasoned about, because the two examples that look like ties
// are not: 2.675 is 2.67499999... in binary and rounds DOWN, and 1.0005 is
// 1.00049999... and rounds DOWN, where 0.0005 is 0.00050000000000000001 and
// rounds UP. A naive math.Round(x*1000)/1000 gets 1.0005 wrong.
func TestRoundMatchesPythonsRound(t *testing.T) {
	for _, tc := range []struct {
		x      float64
		places int
		want   float64
	}{
		{0.8485, 3, 0.849},
		{11.5, 3, 11.5},
		{2.675, 2, 2.67},
		{0.5, 0, 0}, // ties to even
		{1.5, 0, 2},
		{171.0 / 6.8, 1, 25.1},
		{499.4, 1, 499.4},
		{0.0005, 3, 0.001},
		{1.0005, 3, 1.0},
	} {
		if got := Round(tc.x, tc.places); got != tc.want {
			t.Errorf("Round(%v, %d) = %v, want %v", tc.x, tc.places, got, tc.want)
		}
	}
}

func deref(p *float64) any {
	if p == nil {
		return nil
	}
	return *p
}
```

**`relay/ffmpeg/detector_test.go`**

```go
package ffmpeg

import (
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// A clock the test advances by hand, so a fifteen-second timeout costs no
// wall clock and the "more than" at input/manager.py:1178 can be tested at
// the boundary.
type clock struct{ at time.Time }

func (c *clock) now() time.Time { return c.at }
func (c *clock) tick(d time.Duration) {
	c.at = c.at.Add(d)
}

func newDetector(c *clock, threshold float64, timeout time.Duration) *Detector {
	return &Detector{Threshold: threshold, Timeout: timeout, Now: c.now}
}

// The transitions of input/manager.py:1165-1247, one observation at a time.
// The threshold is 2.0 and the timeout 15s: NOT the defaults (1.0 and 15s
// together would let a detector that ignored Threshold and compared against a
// hard-coded 1.0 pass), so every comparison below is against a value the
// wire supplied.
func TestTheDetectorFollowsPythonsTransitions(t *testing.T) {
	c := &clock{at: time.Unix(1_789_000_000, 0)}
	d := newDetector(c, 2.0, 15*time.Second)

	if v := d.Observe(2.0); v != Steady {
		t.Fatalf("speed AT the threshold is not buffering (:1235's >=): got %s", v)
	}
	if v := d.Observe(5.0); v != Steady {
		t.Fatalf("a fast sample is steady: got %s", v)
	}
	if v := d.Observe(1.99); v != Started {
		t.Fatalf("the first sub-threshold sample starts buffering: got %s", v)
	}
	c.tick(15 * time.Second)
	if v := d.Observe(1.5); v != Continuing {
		t.Fatalf("exactly the timeout later is NOT a timeout (:1178's strict >): got %s", v)
	}
	c.tick(time.Millisecond)
	if v := d.Observe(1.5); v != TimedOut {
		t.Fatalf("more than the timeout later is a timeout: got %s", v)
	}
	// Python's failed-switch branch: nothing resets, so the next sample
	// times out again.
	if v := d.Observe(1.5); v != TimedOut {
		t.Fatalf("a further sample after an unhandled timeout times out again: got %s", v)
	}
	if v := d.Observe(2.0); v != Ended {
		t.Fatalf("recovering to the threshold ends buffering: got %s", v)
	}
	if d.Buffering() {
		t.Fatal("Buffering() still true after Ended")
	}
	if v := d.Observe(1.0); v != Started {
		t.Fatalf("a fresh dip starts a FRESH window, not a continuation of the old one: got %s", v)
	}
	c.tick(10 * time.Second)
	if v := d.Observe(1.0); v != Continuing {
		t.Fatalf("ten seconds into the fresh window is not a timeout: got %s", v)
	}
	d.Reset()
	if d.Buffering() {
		t.Fatal("Reset left the detector buffering")
	}
	if v := d.Observe(1.0); v != Started {
		t.Fatalf("after Reset (a successful switch) the next dip starts over: got %s", v)
	}
}

// Parity-matrix row 4's invariant on the captured curve: the detector never
// says "buffering" while the speed it was handed is at or above the
// threshold. Driven from the slow-trickle capture, whose speed= opens above
// 10x against a 0.25x upstream and crosses below 1.0 only after tens of
// seconds of real ffmpeg wall clock -- the cumulative-average delay that is
// ffmpeg's own behaviour, invisible in the Python and visible only in a real
// capture. The real-ffmpeg half of row 4 is channel's
// TestTheCumulativeLeadMustBurnOffBeforeTheDetectorArms; this is the half
// that costs no wall clock.
func TestTheCapturedLeadIsNeverCalledBufferingBeforeItCrosses(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("slow-trickle")
	const threshold = 1.0 // proxy_settings' default buffering_speed; the corpus was captured against it
	crossing := -1
	for idx, v := range speeds {
		if v < threshold {
			crossing = idx
			break
		}
	}
	if crossing <= 0 {
		t.Fatalf("slow-trickle no longer opens above %v and crosses below it (crossing at %d); re-derive (CAPTURE.md)", threshold, crossing)
	}
	if elapsed := relaytest.CorpusElapsed("slow-trickle", crossing); elapsed < 10 {
		t.Fatalf("the capture's own wall clock to the crossing is %.1fs, under ten seconds; "+
			"re-derive -- row 4's claim is that this delay is tens of seconds", elapsed)
	}

	c := &clock{at: time.Unix(1_789_000_000, 0)}
	d := newDetector(c, threshold, 300*time.Second)
	for idx, v := range speeds {
		verdict := d.Observe(v)
		c.tick(500 * time.Millisecond) // ffmpeg's own progress cadence
		buffering := verdict == Started || verdict == Continuing || verdict == TimedOut
		if v >= threshold && buffering {
			t.Fatalf("record %d: the detector armed while the speed was still %vx (>= %v)", idx, v, threshold)
		}
		if idx < crossing && buffering {
			t.Fatalf("record %d, before the crossing at %d: buffering %s", idx, crossing, verdict)
		}
		if idx == crossing && verdict != Started {
			t.Fatalf("record %d is the crossing (%vx) and the verdict is %s, want %s", idx, v, verdict, Started)
		}
	}
	if !d.Buffering() {
		t.Fatal("the capture ends below the threshold, so the detector must end buffering")
	}
}
```

**`relay/ffmpeg/spawn_test.go`**

```go
package ffmpeg

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// TestStandIn is the trampoline: the test binary re-executed as the stand-in
// (see relaytest/standin.go). It returns at once in an ordinary run.
func TestStandIn(_ *testing.T) {
	if os.Getenv(relaytest.StandInEnv) != "1" {
		return
	}
	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
}

// standIn starts the stand-in with args through the package's own Start, so
// every test here exercises the real spawn path.
func standIn(ctx context.Context, t *testing.T, args ...string) *Process {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(args...)
	p, err := Start(ctx, command, argv)
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	return p
}

// assetFile writes a synthetic TS asset to a temp file the stand-in can
// read as its -i input.
func assetFile(t *testing.T, packets int) (string, []byte) {
	t.Helper()
	payload := relaytest.SyntheticTS(packets, 0x100)
	path := t.TempDir() + "/asset.ts"
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatalf("writing the asset: %v", err)
	}
	return path, payload
}

// The bytes a child writes to fd 1 are what Stdout reads, verbatim, and a
// child that ends with status 0 after EOF reports nil.
func TestStdoutIsTheChildsFd1Verbatim(t *testing.T) {
	path, payload := assetFile(t, 256)
	p := standIn(t.Context(), t, "-i", path)

	got, err := io.ReadAll(p.Stdout())
	if err != nil {
		t.Fatalf("reading stdout: %v", err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatalf("stdout delivered %d bytes, want the asset's %d, byte for byte", len(got), len(payload))
	}
	if err := p.Wait(); err != nil {
		t.Fatalf("Wait after a clean exit: %v", err)
	}
}

// ReadStderr splits on CR and LF and sees every progress record of a real
// capture: CR == records - 1 for a gracefully-ended capture, so a reader
// that split on either alone would miscount (CAPTURE.md). The count is read
// off the corpus by relaytest.SplitCorpus, not typed.
func TestReadStderrSplitsOnCROrLFAndSeesEveryRecord(t *testing.T) {
	for _, corpus := range relaytest.CorpusNames {
		t.Run(corpus, func(t *testing.T) {
			_, records := relaytest.SplitCorpus(relaytest.Corpus(corpus))
			path, _ := assetFile(t, 4)
			p := standIn(t.Context(), t, "-i", path, "--stderr-corpus", relaytest.CorpusPath(corpus), "--stderr-interval", "0")

			var mu sync.Mutex
			var lines []string
			done := make(chan struct{})
			go func() {
				defer close(done)
				p.ReadStderr(func(line string) {
					mu.Lock()
					lines = append(lines, line)
					mu.Unlock()
				})
			}()
			_, _ = io.Copy(io.Discard, p.Stdout())
			<-done
			_ = p.Wait()

			mu.Lock()
			defer mu.Unlock()
			progress := 0
			for _, l := range lines {
				if IsProgressLine(l) {
					progress++
				}
			}
			if progress != len(records) {
				t.Fatalf("the reader saw %d progress lines, the corpus holds %d records -- the split lost or merged records", progress, len(records))
			}
			for _, l := range lines {
				if strings.ContainsAny(l, "\r\n") {
					t.Fatalf("a line still carries a terminator: %q", l)
				}
				if strings.TrimSpace(l) == "" {
					t.Fatal("an empty line was emitted; input/manager.py:994-996 skips them")
				}
			}
		})
	}
}

// A buffer past 1 KiB with no terminator and no frame= is flushed as a line
// rather than held until the next terminator (input/manager.py:986-991).
// Driven with a child that writes 1,500 bytes of diagnostic and no newline,
// then stops: without the flush the reader would deliver it only at EOF,
// which happens to be the same moment here -- so the child STAYS ALIVE
// (dead air) and the assertion is that the line arrives while it does.
func TestALongUnterminatedLineIsFlushedWhileTheChildStillRuns(t *testing.T) {
	// A corpus file of one 1,500-byte unterminated line, written by the
	// test: this is a shape the corpus rule forbids for progress lines and
	// permits for a diagnostic, because it carries no speed=.
	corpus := t.TempDir() + "/long.stderr"
	long := strings.Repeat("x", 1500)
	if err := os.WriteFile(corpus, []byte(long), 0o600); err != nil {
		t.Fatal(err)
	}
	path, _ := assetFile(t, 4)
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	p := standIn(ctx, t, "-i", path, "--stderr-corpus", corpus, "--dead-air-after-bytes", "188")

	got := make(chan string, 1)
	go p.ReadStderr(func(line string) {
		select {
		case got <- line:
		default:
		}
	})
	select {
	case line := <-got:
		if line != long {
			t.Fatalf("the flushed line is %d bytes, want %d: %q", len(line), len(long), strings.TrimLeft(line, "x"))
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the unterminated line was not flushed while the child was alive")
	}
	p.Kill()
	_ = p.Wait()
}

// Cancelling the context kills the child with SIGKILL, not SIGTERM: the
// stand-in ignores SIGTERM, so a Cancel that sent the polite signal would
// leave it alive and this test would time out. input/manager.py:1743 sends
// SIGKILL and nothing else.
func TestCancelKillsTheChildWithSIGKILL(t *testing.T) {
	path, _ := assetFile(t, 4)
	ctx, cancel := context.WithCancel(t.Context())
	p := standIn(ctx, t, "-i", path, "--dead-air-after-bytes", "188", "--ignore-sigterm")

	// Let the child install its signal disposition before signalling it.
	buf := make([]byte, 188)
	if _, err := io.ReadFull(p.Stdout(), buf); err != nil {
		t.Fatalf("reading the first packet: %v", err)
	}
	pid := p.PID()

	start := time.Now()
	cancel()
	err := p.Wait()
	var exited *ErrExited
	if !errors.As(err, &exited) || exited.Code != -9 {
		t.Fatalf("Wait after cancel = %v, want ErrExited{Code: -9} (killed by SIGKILL)", err)
	}
	// WITHIN HALF OF KillWait, and the bound is the whole discrimination.
	// os/exec's WaitDelay sends its own SIGKILL once the delay has passed,
	// so a Cancel that sent SIGTERM to a child ignoring it would STILL end
	// in ErrExited{-9} -- 500 ms later. The first version of this test
	// allowed three seconds and stayed green with SIGTERM injected. A
	// SIGKILL is acted on in milliseconds; the WaitDelay fallback cannot
	// fire before 500 ms; 250 ms sits between the two mechanisms.
	if took := time.Since(start); took > KillWait/2 {
		t.Fatalf("the child took %s to die after cancel; a direct SIGKILL takes milliseconds, and %s is "+
			"WaitDelay's own fallback kill after a signal the child ignored", took, KillWait)
	}
	if !processGone(pid) {
		t.Fatalf("pid %d is still alive after Wait returned", pid)
	}
}

// The child's stdin is /dev/null: it reads EOF at once
// (input/manager.py:842's POSIX_SPAWN_OPEN of /dev/null). A child whose
// stdin were the relay's own, or a pipe nobody writes, would block here.
func TestTheChildsStdinIsDevNull(t *testing.T) {
	path, _ := assetFile(t, 4)
	p := standIn(t.Context(), t, "-i", path, "--stdin-probe")
	var report string
	done := make(chan struct{})
	go func() {
		defer close(done)
		p.ReadStderr(func(line string) {
			if strings.HasPrefix(line, "stand-in stdin:") {
				report = line
			}
		})
	}()
	_, _ = io.Copy(io.Discard, p.Stdout())
	<-done
	_ = p.Wait()
	if report != "stand-in stdin: EOF" {
		t.Fatalf("the child saw %q on stdin, want an immediate EOF", report)
	}
}

// A non-zero exit reaches Wait as ErrExited with the child's own code, and
// a clean exit after a partial copy reports nil: Wait reports the STATUS,
// and what a status means is the caller's decision.
func TestWaitReportsTheChildsExitStatus(t *testing.T) {
	path, _ := assetFile(t, 8)
	for _, code := range []int{0, 1, 3} {
		t.Run("exit "+strconv.Itoa(code), func(t *testing.T) {
			p := standIn(t.Context(), t, "-i", path, "--exit-after-bytes", "376", "--exit-code", strconv.Itoa(code))
			got, _ := io.ReadAll(p.Stdout())
			if len(got) != 376 {
				t.Fatalf("stdout delivered %d bytes before the exit, want 376", len(got))
			}
			err := p.Wait()
			if code == 0 {
				if err != nil {
					t.Fatalf("Wait = %v, want nil for exit status 0", err)
				}
				return
			}
			var exited *ErrExited
			if !errors.As(err, &exited) || exited.Code != code {
				t.Fatalf("Wait = %v, want ErrExited{Code: %d}", err, code)
			}
		})
	}
}

// A command that is a URL is refused before anything is spawned: exec.Error
// prints the command NAME, and a URL there would be the one shape
// redact.Error cannot strip.
func TestACommandThatIsAURLIsRefusedBeforeSpawning(t *testing.T) {
	_, err := Start(t.Context(), "http://provider.example/live/u/hunter2/1.ts", nil)
	if !errors.Is(err, ErrCommandIsAURL) {
		t.Fatalf("Start with a URL command = %v, want ErrCommandIsAURL", err)
	}
	if err != nil && strings.Contains(err.Error(), "hunter2") {
		t.Fatalf("the refusal echoes the credential: %v", err)
	}
}

// A command that cannot be found fails Start with exec's own error, which
// names the executable and never the argv.
func TestAMissingExecutableFailsStartWithoutEchoingArgv(t *testing.T) {
	_, err := Start(t.Context(), "relay-no-such-executable-2c4", []string{"-i", "http://provider.example/live/u/hunter2/1.ts"})
	if err == nil {
		t.Fatal("Start found an executable that does not exist")
	}
	if strings.Contains(err.Error(), "hunter2") {
		t.Fatalf("the start error echoes the URL from argv: %v", err)
	}
	if !strings.Contains(err.Error(), "relay-no-such-executable-2c4") {
		t.Fatalf("the start error lost the executable's name: %v", err)
	}
}
```

**`relay/ffmpeg/spawn_linux_test.go`**

```go
//go:build linux

package ffmpeg

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// parentEnv turns the re-executed test binary into a RELAY: a process that
// spawns the stand-in through this package's Start, prints the child's pid,
// and then hangs. The test kills it and watches the child.
const parentEnv = "RELAY_PDEATHSIG_PARENT"

// TestParentProcess is the second trampoline. Under parentEnv it is the
// relay stand-in described above; in an ordinary run it returns at once.
func TestParentProcess(t *testing.T) {
	if os.Getenv(parentEnv) != "1" {
		return
	}
	// THE CHILD MUST BLOCK ON NOTHING BUT TIME. An earlier version of this
	// helper had it copy /dev/zero into a stdout pipe nobody drained, and
	// the break-check that removed Pdeathsig STAYED GREEN: when the parent
	// died the pipe's read end closed, the child's next write got EPIPE,
	// and it exited on its own -- a true positive for a false reason. The
	// defect this test guards is an ffmpeg blocked READING a stalled
	// upstream, which never writes and so never sees EPIPE; only the
	// kernel's parent-death signal reaches it. Dead-air mode is that shape:
	// one write, then a sleep loop, with stdin already /dev/null.
	command, argv := relaytest.StandInCommand("-i", "/dev/zero", "--dead-air-after-bytes", "188")
	p, err := Start(context.Background(), command, argv)
	if err != nil {
		fmt.Println("start failed:", err)
		os.Exit(1)
	}
	// READ THE CHILD'S ONE WRITE BEFORE ANNOUNCING IT. The second version of
	// this helper printed the pid at once, and the break-check stayed green
	// a second time: the child was still starting when the parent was
	// killed, its first write to fd 1 found a pipe with no reader, and Go
	// terminates a program on EPIPE to stdout -- measured at state R and
	// gone within 10 ms, with Pdeathsig removed. Once these 188 bytes are
	// in hand the child has entered its sleep loop and will never write
	// again, so from here only the kernel can end it.
	if _, err := io.ReadFull(p.Stdout(), make([]byte, 188)); err != nil {
		fmt.Println("the child never wrote:", err)
		os.Exit(1)
	}
	fmt.Println(p.PID())
	// Never reaps the child. The only thing that can end it now is the
	// kernel. A sleep loop rather than `select {}`: with no other goroutine
	// the runtime would report a deadlock and EXIT, and a parent that dies
	// on its own takes the child with it through the very mechanism under
	// test.
	for {
		time.Sleep(time.Hour)
	}
}

// SPEC D5's FIRST EXCEPTION, pinned: a child of a dead relay dies with it.
//
// The child is in its own process group (Setpgid), so killing the parent's
// group would not reach it and killing the parent alone reaches it ONLY
// through Pdeathsig. The parent is SIGKILLed, which is the shape of a crash
// or an OOM kill rather than a drain, and the child must be gone within a
// bounded time. Without Pdeathsig the child is reparented to init and lives
// on holding its provider slot -- the defect CLAUDE.md § Operationally
// records for the Python relay.
func TestAChildOfADeadRelayDiesWithIt(t *testing.T) {
	t.Setenv(relaytest.StandInEnv, "1")
	t.Setenv(parentEnv, "1")
	parent := exec.CommandContext(t.Context(), os.Args[0], "-test.run=^TestParentProcess$")
	parent.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	stdout, err := parent.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := parent.Start(); err != nil {
		t.Fatalf("starting the parent: %v", err)
	}
	defer func() {
		_ = parent.Process.Kill()
		_ = parent.Wait()
	}()

	scanner := bufio.NewScanner(stdout)
	if !scanner.Scan() {
		t.Fatal("the parent printed nothing")
	}
	line := strings.TrimSpace(scanner.Text())
	childPID, err := strconv.Atoi(line)
	if err != nil {
		t.Fatalf("the parent printed %q, want the child's pid", line)
	}
	if processGone(childPID) {
		t.Fatalf("child %d is not alive before the parent is killed", childPID)
	}

	if err := syscall.Kill(parent.Process.Pid, syscall.SIGKILL); err != nil {
		t.Fatalf("killing the parent: %v", err)
	}
	_ = parent.Wait()

	deadline := time.Now().Add(5 * time.Second)
	for !processGone(childPID) {
		if time.Now().After(deadline) {
			_ = syscall.Kill(childPID, syscall.SIGKILL)
			t.Fatalf("child %d outlived its dead parent by five seconds -- Pdeathsig is not set, "+
				"and an ffmpeg blocked on a stalled upstream would hold its provider slot forever", childPID)
		}
		time.Sleep(20 * time.Millisecond)
	}
}
```

**`relay/ffmpeg/procgone_test.go`**

```go
package ffmpeg

import (
	"errors"
	"syscall"
)

// processGone reports whether pid no longer exists. Signal 0 checks
// existence without delivering anything; a zombie still "exists" until it is
// reaped, which is why callers Wait first.
func processGone(pid int) bool {
	err := syscall.Kill(pid, 0)
	return errors.Is(err, syscall.ESRCH)
}
```

### Appendix H — `relay/internal/relaytest/corpus.go`

**`relay/internal/relaytest/corpus.go`**

```go
package relaytest

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
)

// The captured real-ffmpeg stderr corpus, READ IN PLACE from the Python
// harness's own fixtures directory and never copied into this module.
//
// apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/CAPTURE.md is
// the authority on what these files are: verbatim captures from ffmpeg 8.1.2,
// CR separators included, never hand-edited. Two copies of a corpus that must
// not be edited is one copy nobody remembers to regenerate, so the Go tests
// open the same bytes the Python tests open. Every rule that file states
// about the corpus -- the digits are a timing measurement, only the SHAPE is
// asserted -- binds the Go tests too.

// CorpusNames are the three captures, harness/ffmpeg_stderr.py:15's
// CORPUS_NAMES.
var CorpusNames = []string{"normal", "slow-trickle", "truncation"}

// repoRoot locates the repository from this file's own path: relay/internal/
// relaytest/corpus.go is four levels below it. runtime.Caller rather than
// the working directory, because `go test` sets the cwd to the PACKAGE
// directory, which is a different depth for every package that reads the
// corpus.
func repoRoot() string {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		panic("relaytest: runtime.Caller failed")
	}
	return filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(file))))
}

// CorpusPath is the absolute path of one capture.
func CorpusPath(name string) string {
	for _, known := range CorpusNames {
		if known == name {
			return filepath.Join(repoRoot(), "apps", "proxy", "live_proxy", "tests", "harness",
				"fixtures", "ffmpeg_stderr", name+".stderr")
		}
	}
	panic(fmt.Sprintf("relaytest: unknown corpus %q", name))
}

// Corpus is one capture, byte for byte.
func Corpus(name string) []byte {
	raw, err := os.ReadFile(CorpusPath(name))
	if err != nil {
		panic(fmt.Sprintf("relaytest: reading the %s corpus: %v", name, err)) // credential-logging: ok - an *fs.PathError over a fixture path
	}
	return raw
}

// SplitCorpus is harness/ffmpeg_stderr.py's split(): the preamble, and every
// progress record, splitting on CR OR LF because that is what
// input/manager.py's _read_stderr does (:981-991) and what the captures need
// -- ffmpeg TERMINATES a record with CR, and a gracefully-exiting ffmpeg ends
// its last one with LF, so `truncation` has zero CR bytes and a CR-only split
// finds no record in it at all.
func SplitCorpus(raw []byte) (preamble []byte, records [][]byte) {
	lines := bytes.Split(bytes.ReplaceAll(raw, []byte("\r"), []byte("\n")), []byte("\n"))
	for _, line := range lines {
		if bytes.Contains(line, []byte("speed=")) {
			records = append(records, line)
		}
	}
	if len(records) == 0 {
		return raw, nil
	}
	first := bytes.Index(raw, records[0])
	return raw[:first], records
}

// The PRODUCTION speed regex, copied deliberately rather than imported from
// package ffmpeg: these helpers exist so a test can quote what the shipped
// parser sees, and importing the parser would make the quote move if the
// parser moved. Same rationale, and the same literal, as
// apps/proxy/live_proxy/tests/manager_support.py:24.
var (
	corpusSpeedRe   = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)
	corpusElapsedRe = regexp.MustCompile(`elapsed=(\d+):(\d\d):(\d\d(?:\.\d+)?)`)
)

// CorpusSpeeds is every progress record's speed=, as the production regex
// reads it -- manager_support.py's corpus_speeds.
func CorpusSpeeds(name string) []float64 {
	_, records := SplitCorpus(Corpus(name))
	out := make([]float64, 0, len(records))
	for _, r := range records {
		m := corpusSpeedRe.FindSubmatch(r)
		if m == nil {
			panic(fmt.Sprintf("relaytest: a %s record carries no speed=: %q", name, r))
		}
		v, err := strconv.ParseFloat(string(m[1]), 64)
		if err != nil {
			panic(fmt.Sprintf("relaytest: %s record %q: %v", name, r, err)) // credential-logging: ok - a strconv error over a captured progress record
		}
		out = append(out, v)
	}
	return out
}

// CorpusElapsed is record `index`'s elapsed= in seconds -- the real ffmpeg
// wall clock it took -- manager_support.py's corpus_elapsed. ffmpeg 8.1.2
// appends this field after speed=; nothing in production parses it.
func CorpusElapsed(name string, index int) float64 {
	_, records := SplitCorpus(Corpus(name))
	m := corpusElapsedRe.FindSubmatch(records[index])
	if m == nil {
		panic(fmt.Sprintf("relaytest: %s record %d carries no elapsed=", name, index))
	}
	h, _ := strconv.Atoi(string(m[1]))
	mi, _ := strconv.Atoi(string(m[2]))
	s, _ := strconv.ParseFloat(string(m[3]), 64)
	return float64(h*3600+mi*60) + s
}
```

### Appendix I — `relay/internal/relaytest/standin.go`

**`relay/internal/relaytest/standin.go`**

```go
package relaytest

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The stand-in: a program that behaves like ffmpeg from the relay's side
// without being one. The Go counterpart of apps/proxy/live_proxy/tests/
// harness/standin.py, which states the rule this one keeps:
//
//	Every spawn is real. The child program is the stand-in when the test's
//	subject is the relay's REACTION to what a process said or did -- a stderr
//	line, an exit code, an exit moment, a byte rate -- because those must be
//	exact and a real ffmpeg cannot be made exact on demand. The child program
//	is real ffmpeg when the test's subject is the bytes a remuxer produces.
//	It is never a Go object standing in for a process.
//
//	And every line the stand-in writes to stderr came out of a real ffmpeg.
//
// HOW IT IS A SEPARATE PROCESS WITHOUT A SECOND BINARY: the test binary
// re-executes itself. A package that spawns the stand-in declares one
// trampoline test,
//
//	func TestStandIn(t *testing.T) {
//		if os.Getenv(StandInEnv) != "1" { return }
//		os.Exit(RunStandIn(StandInArgs()))
//	}
//
// and StandInCommand builds the (command, argv) pair that reaches it:
// os.Args[0] with -test.run=^TestStandIn$ and the stand-in's own flags after
// "--". The relay's spawn passes os.Environ() to the child exactly as
// input/manager.py:839 passes os.environ, so a t.Setenv(StandInEnv, "1") in
// the test is what turns the re-executed binary into the stand-in. This is
// the shape os/exec's own tests use, and it needs no Python and no second
// executable on PATH -- which also keeps the module free of anything that
// could look like a second implementation of ffmpeg.
//
// Flags, harness/standin.py:26-36's, plus three for tests Python has no need
// of because its stand-in runs under a relay that never sends SIGKILL to a
// process group:
//
//	-i INPUT                 a URL to GET and copy to stdout, or a file path,
//	                         or pipe:0
//	--stderr-corpus PATH     the captured .stderr file to replay
//	--stderr-interval S      seconds between progress records (default 0.05);
//	                         the preamble is always written immediately
//	--stderr-loop            restart the corpus when it runs out
//	--exit-after-bytes N     exit after copying N bytes
//	--exit-code N            the code to exit with (default 0)
//	--dead-air-after-bytes N stop writing after N bytes but stay alive
//	--echo-argv              write "stand-in argv: ..." to stderr first, so a
//	                         test can see what it was spawned with
//	--ignore-sigterm         stay alive through SIGTERM, so a test can tell
//	                         SIGKILL from SIGTERM
//	--stdin-probe            report on stderr whether stdin was at EOF

// StandInEnv is the environment variable that turns the re-executed test
// binary into the stand-in.
const StandInEnv = "RELAY_STANDIN"

// StandInCommand is the (command, argv) a fake control plane answers with to
// make the relay spawn the stand-in with args.
func StandInCommand(args ...string) (command string, argv []string) {
	argv = append([]string{"-test.run=^TestStandIn$", "--"}, args...)
	return os.Args[0], argv
}

// StandInArgs is the stand-in's own arguments: everything after "--".
func StandInArgs() []string {
	for i, a := range os.Args {
		if a == "--" {
			return os.Args[i+1:]
		}
	}
	return nil
}

type standInOptions struct {
	input          string
	corpus         string
	interval       time.Duration
	loop           bool
	exitAfter      int
	exitCode       int
	deadAirAfter   int
	echoArgv       bool
	ignoreSigterm  bool
	stdinProbe     bool
	haveExitAfter  bool
	haveDeadAir    bool
	positional     []string
	originalArgs   []string
	fatalParseFlag string
}

func parseStandIn(args []string) standInOptions {
	o := standInOptions{interval: 50 * time.Millisecond, originalArgs: args}
	for i := 0; i < len(args); i++ {
		next := func() string {
			if i+1 >= len(args) {
				o.fatalParseFlag = args[i]
				return ""
			}
			i++
			return args[i]
		}
		switch a := args[i]; a {
		case "--stderr-corpus":
			o.corpus = next()
		case "--stderr-interval":
			secs, _ := strconv.ParseFloat(next(), 64)
			o.interval = time.Duration(secs * float64(time.Second))
		case "--stderr-loop":
			o.loop = true
		case "--exit-after-bytes":
			o.exitAfter, _ = strconv.Atoi(next())
			o.haveExitAfter = true
		case "--exit-code":
			o.exitCode, _ = strconv.Atoi(next())
		case "--dead-air-after-bytes":
			o.deadAirAfter, _ = strconv.Atoi(next())
			o.haveDeadAir = true
		case "--echo-argv":
			o.echoArgv = true
		case "--ignore-sigterm":
			o.ignoreSigterm = true
		case "--stdin-probe":
			o.stdinProbe = true
		case "-i":
			// ffmpeg's own input flag. Above the generic dash branch, for
			// the reason standin.py:90-101 records: `-i` starts with a dash.
			o.input = next()
		default:
			if strings.HasPrefix(a, "-") {
				// Any other flag -- ffmpeg's own, whatever the profile
				// carries -- is accepted and ignored, so the production
				// parameter string works unchanged.
				continue
			}
			o.positional = append(o.positional, a)
		}
	}
	if o.input == "" && len(o.positional) > 0 {
		o.input = o.positional[len(o.positional)-1]
	}
	return o
}

// RunStandIn runs the stand-in and returns the exit code the caller should
// os.Exit with.
func RunStandIn(args []string) int {
	o := parseStandIn(args)
	if o.fatalParseFlag != "" {
		fmt.Fprintf(os.Stderr, "stand-in: %s needs a value\n", o.fatalParseFlag)
		return 2
	}
	if o.echoArgv {
		// Mimics the one thing about ffmpeg's stderr that matters to the
		// redaction tests: it echoes the URL it was given.
		fmt.Fprintf(os.Stderr, "stand-in argv: %s\n", strings.Join(o.originalArgs, " "))
	}
	if o.ignoreSigterm {
		signal.Ignore(syscall.SIGTERM)
	}
	if o.stdinProbe {
		buf := make([]byte, 1)
		n, err := os.Stdin.Read(buf)
		switch {
		case n == 0 && err == io.EOF:
			fmt.Fprintln(os.Stderr, "stand-in stdin: EOF")
		case err != nil:
			fmt.Fprintf(os.Stderr, "stand-in stdin: error %v\n", err) // credential-logging: ok - a read error on fd 0
		default:
			fmt.Fprintln(os.Stderr, "stand-in stdin: data")
		}
	}
	if o.input == "" {
		fmt.Fprintln(os.Stderr, "stand-in: no input; expected `-i <url>` or a positional")
		return 2
	}

	if o.corpus != "" {
		go pumpStderr(o.corpus, o.interval, o.loop)
	}

	var source io.ReadCloser
	switch {
	case o.input == "pipe:0":
		source = os.Stdin
	case strings.Contains(o.input, "://"):
		client := &http.Client{Timeout: 0}
		response, err := client.Get(o.input) //nolint:noctx // the stand-in is a separate process with no context to carry
		if err != nil {
			// The stand-in's stderr is what the relay under test redacts, and
			// this error would carry the input URL as ffmpeg's own would; it
			// is stripped here anyway, so a test that captures the child's
			// stderr directly is not handed a URL by test support.
			fmt.Fprintf(os.Stderr, "stand-in: fetching input: %v\n", redact.Error(err))
			return 1
		}
		defer func() { _ = response.Body.Close() }()
		source = response.Body
	default:
		f, err := os.Open(o.input)
		if err != nil {
			fmt.Fprintf(os.Stderr, "stand-in: opening input: %v\n", err) // credential-logging: ok - an *fs.PathError over a test asset path
			return 1
		}
		defer func() { _ = f.Close() }()
		source = f
	}

	copied := 0
	buf := make([]byte, 8192)
	for {
		n, err := source.Read(buf)
		if n > 0 {
			chunk := buf[:n]
			if o.haveExitAfter && copied+n >= o.exitAfter {
				_, _ = os.Stdout.Write(chunk[:o.exitAfter-copied])
				return o.exitCode
			}
			if o.haveDeadAir && copied+n >= o.deadAirAfter {
				_, _ = os.Stdout.Write(chunk[:o.deadAirAfter-copied])
				// Alive, connected, producing nothing -- what a dead-air
				// watchdog is for. A sleep loop, as standin.py:196-197, and
				// NOT `select {}`: with the stderr pump finished this would
				// be the only goroutine, and Go's runtime kills a process
				// whose every goroutine is asleep with "fatal error: all
				// goroutines are asleep - deadlock!" -- on stderr, where the
				// relay's reader would take it for a diagnostic line.
				for {
					time.Sleep(time.Second)
				}
			}
			if _, werr := os.Stdout.Write(chunk); werr != nil {
				// The relay closed its side: an ordinary end.
				return o.exitCode
			}
			copied += n
		}
		if err != nil {
			return o.exitCode
		}
	}
}

// pumpStderr replays a capture: the preamble at once, then one progress
// record per interval, CR-terminated -- standin.py:117-156, including its
// stated non-exactness about the LAST record of a real capture.
func pumpStderr(path string, interval time.Duration, loop bool) {
	raw, err := os.ReadFile(path) // #nosec G304 -- a fixture path the test itself chose
	if err != nil {
		fmt.Fprintf(os.Stderr, "stand-in: reading the corpus: %v\n", err) // credential-logging: ok - an *fs.PathError over a fixture path
		return
	}
	preamble, records := SplitCorpus(raw)
	_, _ = os.Stderr.Write(preamble)
	for {
		for _, record := range records {
			if interval > 0 {
				time.Sleep(interval)
			}
			if _, err := os.Stderr.Write(append(append([]byte(nil), record...), '\r')); err != nil {
				return
			}
		}
		if !loop {
			return
		}
	}
}
```

### Appendix J — `relay/internal/relaytest/controlplane.go` — the whole file after 2c-4

**`relay/internal/relaytest/controlplane.go`**

```go
package relaytest

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"sync"
	"time"
)

// EffectiveProxySettings is what Amendment A1.4 makes Django send on every
// next-source answer: the seven stored CoreSettings keys, plus every public
// plain-valued class attribute of apps/proxy/config.py's TSConfig under its
// own SCREAMING_CASE name.
//
// The values here are typed from apps/proxy/config.py BY HAND, and the Python
// side asserts the same literals independently (A1.4's value test). Deriving
// them from anything would make this fixture agree with a wrong wire format.
//
// Only the keys a Go test needs are present, because a fixture that carried
// all thirty-eight would make an "every key is required" assertion pass for
// the wrong reason: with everything present, a test cannot show that an
// ABSENT key fails. Add a key here when a Go consumer starts reading it.
func EffectiveProxySettings() map[string]any {
	return map[string]any{
		// The stored CoreSettings group (core/models.py:719-730).
		"buffering_timeout":          15,
		"buffering_speed":            1.0,
		"redis_chunk_ttl":            60,
		"channel_shutdown_delay":     0,
		"channel_init_grace_period":  60,
		"channel_client_wait_period": 5,
		"new_client_behind_seconds":  5,
		// TSConfig's class-attribute defaults, the half A1.4 adds.
		"BUFFER_CHUNK_SIZE":      255868,                     // apps/proxy/config.py:15, 188 * 1361
		"DEFAULT_USER_AGENT":     "VLC/3.0.20 LibVLC/3.0.20", // :6
		"CHUNK_SIZE":             8192,                       // :7
		"STREAM_TIMEOUT":         20,                         // :103
		"FAILOVER_GRACE_PERIOD":  20,                         // :120
		"KEEPALIVE_INTERVAL":     0.5,                        // :97
		"MAX_KEEPALIVE_DURATION": 300,                        // :122
	}
}

// ControlPlaneConfig shapes a fake Django.
type ControlPlaneConfig struct {
	// SourceURL is what next-source answers with. Empty means the answer
	// carries a null source.
	SourceURL string

	// Kind is the stream_profile.kind on the answer. Empty means "proxy".
	Kind string

	// Settings is the proxy_settings object. Nil means
	// EffectiveProxySettings().
	Settings map[string]any

	// Status forces a status code on every call. Zero means 200.
	Status int

	// FailFirst answers the first n calls with 503 before behaving, so a test
	// can show the retry budget being spent.
	FailFirst int

	// RedirectTo, when set, answers 302 to it.
	RedirectTo string

	// Body, when non-empty, is returned verbatim with a 200 instead of a
	// generated answer, so a test can drive the non-JSON and non-object rows
	// of the error table.
	Body string

	// Delay holds every answer for this long before writing it, so a test
	// can act while a next-source call is still in flight. Zero answers at
	// once.
	Delay time.Duration

	// Command and Argv are the stream_profile's built command line. Empty
	// and nil render as "" and [] -- the Proxy and Redirect shape.
	Command string
	Argv    []string

	// ArgvAbsent leaves the argv key out of stream_profile entirely, the
	// shape of a control plane older than 2c-4. ArgvNull sends it as null,
	// the shape of a profile whose parameters shlex could not split. Both
	// apply to ffmpeg_stream_profile too when one is sent.
	ArgvAbsent bool
	ArgvNull   bool

	// FFmpegProfile, when set, is sent as ffmpeg_stream_profile; nil sends
	// null, which is "no locked ffmpeg profile installed".
	FFmpegProfile *ProfileConfig

	// UserAgent overrides the source's user_agent. Empty means
	// "relaytest/1.0", the fixture's usual value; BlankUserAgent sends "".
	UserAgent      string
	BlankUserAgent bool
}

// ProfileConfig is one stream-profile object the fake sends.
type ProfileConfig struct {
	ID      int
	Command string
	Argv    []string
}

// ControlPlane is a fake Django answering POST /api/relay/... .
type ControlPlane struct {
	server *httptest.Server

	mu       sync.Mutex
	requests []RecordedRequest
	settings map[string]any
}

// SetSettings replaces the proxy_settings every LATER answer carries. It is
// how a test changes a setting between two tunes, the way an operator's
// save does, to show that a channel already running does not pick it up
// (parity-matrix row 5).
func (c *ControlPlane) SetSettings(settings map[string]any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.settings = settings
}

// RecordedRequest is one call the fake received.
type RecordedRequest struct {
	Method string
	Path   string
	Header http.Header
	Body   []byte
}

// NewControlPlane starts a fake control plane. Register Close with t.Cleanup.
func NewControlPlane(cfg ControlPlaneConfig) *ControlPlane {
	c := &ControlPlane{}
	c.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body := make([]byte, 0)
		if r.Body != nil {
			buf := make([]byte, 1<<16)
			for {
				n, err := r.Body.Read(buf)
				body = append(body, buf[:n]...)
				if err != nil {
					break
				}
			}
		}
		c.mu.Lock()
		seen := len(c.requests)
		c.requests = append(c.requests, RecordedRequest{
			Method: r.Method,
			// RequestURI, not URL.Path: the bound token signs the FULL path
			// including the query string, so a test that needs to verify the
			// signature needs the full path back.
			Path:   r.RequestURI,
			Header: r.Header.Clone(),
			Body:   body,
		})
		c.mu.Unlock()

		if cfg.Delay > 0 {
			select {
			case <-r.Context().Done():
				return
			case <-time.After(cfg.Delay):
			}
		}

		switch {
		case cfg.RedirectTo != "":
			http.Redirect(w, r, cfg.RedirectTo, http.StatusFound)
			return
		case seen < cfg.FailFirst:
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		case cfg.Status != 0 && cfg.Status != http.StatusOK:
			w.WriteHeader(cfg.Status)
			_, _ = w.Write([]byte(`{"detail":"relaytest: configured status"}`))
			return
		case cfg.Body != "":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(cfg.Body))
			return
		}

		c.mu.Lock()
		settings := c.settings
		c.mu.Unlock()
		if settings == nil {
			settings = cfg.Settings
		}
		if settings == nil {
			settings = EffectiveProxySettings()
		}
		kind := cfg.Kind
		if kind == "" {
			kind = "proxy"
		}
		profile := func(id int, command string, argv []string) map[string]any {
			object := map[string]any{"id": id, "command": command, "args": "", "kind": kind}
			switch {
			case cfg.ArgvAbsent:
			case cfg.ArgvNull:
				object["argv"] = nil
			case argv == nil:
				object["argv"] = []string{}
			default:
				object["argv"] = argv
			}
			return object
		}
		var ffmpegProfile any
		if cfg.FFmpegProfile != nil {
			ffmpegProfile = profile(cfg.FFmpegProfile.ID, cfg.FFmpegProfile.Command, cfg.FFmpegProfile.Argv)
		}
		userAgent := "relaytest/1.0"
		if cfg.UserAgent != "" {
			userAgent = cfg.UserAgent
		}
		if cfg.BlankUserAgent {
			userAgent = ""
		}

		answer := map[string]any{
			"alternates":      []any{},
			"error":           nil,
			"proxy_settings":  settings,
			"output_profiles": map[string]any{},
			"source":          nil,
		}
		if cfg.SourceURL != "" {
			answer["source"] = map[string]any{
				"stream_id":             1,
				"url":                   cfg.SourceURL,
				"user_agent":            userAgent,
				"transcode":             false,
				"m3u_profile_id":        1,
				"slot_reserved":         true,
				"channel_name":          "Test Channel",
				"stream_name":           "Test Stream",
				"m3u_profile_name":      "Test Profile",
				"stream_profile":        profile(1, cfg.Command, cfg.Argv),
				"ffmpeg_stream_profile": ffmpegProfile,
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(answer)
	}))
	return c
}

// URL is the base URL to hand a control.Client.
func (c *ControlPlane) URL() string { return c.server.URL }

// Requests is every call the fake has received, in order.
func (c *ControlPlane) Requests() []RecordedRequest {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]RecordedRequest(nil), c.requests...)
}

// Close stops the fake.
func (c *ControlPlane) Close() { c.server.Close() }
```

### Appendix K — `relay/control/nextsource.go` (whole file after 2c-4), `settings.go`'s three markers, and `profile_test.go`

**`relay/control/nextsource.go`**

```go
package control

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The three stream-profile architectures, as StreamProfileRef.Kind spells
// them. Added to the contract by 2c-1 Task 0 (Finding F1): `transcode` alone
// collapses Proxy and Redirect onto the same false, and both locked profiles
// carry an empty command, so nothing else on the wire separates them.
const (
	KindProxy     = "proxy"
	KindRedirect  = "redirect"
	KindTranscode = "transcode"
)

// Timeouts for next-source, from spec § The contract: connect 2s, read 5s,
// one retry at 0.1s -- the same numbers Python's own next-source client
// uses, at apps/proxy/control_plane.py:37 (CONNECT_TIMEOUT), :38
// (READ_TIMEOUT) and :41 (RETRY_DELAY). Pinned by TestTheTimeoutsMatchPython.
const (
	ConnectTimeout = 2 * time.Second
	ReadTimeout    = 5 * time.Second
	RetryDelay     = 100 * time.Millisecond
	attempts       = 2
)

// StreamProfileRef is the next-source answer's stream_profile object, and
// its ffmpeg_stream_profile object, which the same serializer renders.
type StreamProfileRef struct {
	ID      int    `json:"id"`
	Command string `json:"command"`
	Args    string `json:"args"`
	Kind    string `json:"kind"`

	// Argv is the argument list Django BUILT for this tune: StreamProfile.
	// build_command(url, user_agent, pk) with the command removed
	// (core/models.py:137-160 -- shlex.split of the profile's parameters,
	// then the {streamUrl}/{userAgent}/{channelId} substitutions). Spec
	// Amendment A4.1: the relay carries no word splitter and no
	// substitution table, so the argv it spawns is byte for byte the argv
	// the Python relay spawns from the same answer.
	//
	// Three states, and the difference between the last two is the whole
	// reason for ArgvPresent: a LIST is the built argv (empty for Proxy and
	// Redirect, whose build_command returns []); JSON NULL means Django
	// could not split the parameters (an unbalanced quote, which shlex
	// refuses with ValueError) and the tune cannot be served; the key
	// ABSENT means a control plane older than this relay, which is not a
	// profile problem and must not be reported as one.
	Argv []string `json:"-"`

	// ArgvPresent reports whether the answer carried the argv key at all.
	ArgvPresent bool `json:"-"`
}

// UnmarshalJSON decodes the object and records whether argv was present, a
// distinction encoding/json cannot make for a slice field on its own: an
// absent key and an explicit null both leave it nil.
func (p *StreamProfileRef) UnmarshalJSON(data []byte) error {
	type plain StreamProfileRef
	var aux struct {
		plain
		ArgvRaw json.RawMessage `json:"argv"`
	}
	if err := json.Unmarshal(data, &aux); err != nil {
		return err
	}
	*p = StreamProfileRef(aux.plain)
	p.Argv, p.ArgvPresent = nil, false
	if len(aux.ArgvRaw) == 0 {
		return nil
	}
	p.ArgvPresent = true
	if bytes.Equal(bytes.TrimSpace(aux.ArgvRaw), []byte("null")) {
		return nil
	}
	if err := json.Unmarshal(aux.ArgvRaw, &p.Argv); err != nil {
		return fmt.Errorf("stream_profile.argv is not a list of strings: %w", err) // credential-logging: ok - an encoding/json type error naming the JSON shape, never a value
	}
	if p.Argv == nil {
		p.Argv = []string{}
	}
	return nil
}

// Source is one candidate upstream.
type Source struct {
	StreamID       int              `json:"stream_id"`
	URL            string           `json:"url"`
	UserAgent      string           `json:"user_agent"`
	Transcode      bool             `json:"transcode"`
	M3UProfileID   int              `json:"m3u_profile_id"`
	SlotReserved   bool             `json:"slot_reserved"`
	StreamProfile  StreamProfileRef `json:"stream_profile"`
	ChannelName    string           `json:"channel_name"`
	StreamName     string           `json:"stream_name"`
	M3UProfileName string           `json:"m3u_profile_name"`

	// FFmpegStreamProfile is the locked "ffmpeg" profile, built for this
	// same URL, or nil when none is installed (apps/proxy/next_source.py's
	// _locked_ffmpeg_profile, Phase 2 PR 2b-1). It is what a Proxy channel
	// whose URL turns out to be HLS, RTSP or UDP is played through instead
	// (input/manager.py:445-453's force_ffmpeg).
	FFmpegStreamProfile *StreamProfileRef `json:"ffmpeg_stream_profile"`
}

// NextSourceRequest is the POST body.
type NextSourceRequest struct {
	ExcludeStreamIDs  []int  `json:"exclude_stream_ids"`
	Reason            string `json:"reason"`
	CurrentURL        string `json:"current_url,omitempty"`
	TargetStreamID    *int   `json:"target_stream_id,omitempty"`
	CurrentStreamID   *int   `json:"current_stream_id,omitempty"`
	IncludeAlternates bool   `json:"include_alternates"`
}

// NextSourceAnswer is the response body. output_profiles is deliberately not
// declared: 2c-7 owns Output Profiles and json.Unmarshal ignores what no field
// names, so leaving it out now costs nothing and claims nothing.
type NextSourceAnswer struct {
	Source     *Source  `json:"source"`
	Alternates []Source `json:"alternates"`
	// Error is a CharField(allow_null=True) on the wire, so JSON null
	// unmarshals to the empty string. Callers test Source == nil, never this.
	Error         string   `json:"error"`
	ProxySettings Settings `json:"proxy_settings"`
}

// Unavailable means the control plane could not be reached or did not answer
// like Django. Only this is retried, and only this triggers the degraded
// fallback 2c-5 adds.
type Unavailable struct {
	Path   string
	Reason string
	Err    error

	// retryable is set only on the two outcomes that consume the second
	// attempt -- a transport failure and a 5xx. It is unexported because it
	// is this package's retry bookkeeping, not something a caller decides.
	// Spec § Error handling per hop is explicit that the non-JSON, non-object
	// and 3xx outcomes raise on the FIRST pass: a client built to the
	// uncorrected table burns a second full (2, 5) budget -- up to seven
	// extra seconds of dead air -- on a misconfigured deployment.
	retryable bool
}

func (e *Unavailable) Error() string {
	if e.Err != nil {
		// Through redact.Error: Err is the transport's *url.Error on a
		// connection failure, and its message carries the control-plane
		// base URL, which DISPATCHARR_INTERNAL_API_BASE_URL may give with
		// userinfo. Found by relay/internal/credlint's first run over this
		// module (2c-4), the shape 2c-2's review found once by hand.
		return fmt.Sprintf("control plane unavailable at %s: %s: %v", e.Path, e.Reason, redact.Error(e.Err))
	}
	return fmt.Sprintf("control plane unavailable at %s: %s", e.Path, e.Reason)
}

func (e *Unavailable) Unwrap() error { return e.Err }

// Refused is a 4xx other than next-source's own 404. Deliberately NOT a
// subclass of Unavailable: a 403 from a SECRET_KEY mismatch between the api
// and relay roles must fail the tune loudly rather than make every failover on
// the deployment degrade silently forever.
type Refused struct {
	Path   string
	Status int
}

func (e *Refused) Error() string {
	return fmt.Sprintf("control plane refused %s with %d", e.Path, e.Status)
}

// Client calls Django's /api/relay/... routes.
type Client struct {
	// Secret is the deployment's Django SECRET_KEY.
	Secret string
	// HTTP is the transport. Nil means a client built from ConnectTimeout and
	// ReadTimeout that never follows a redirect.
	HTTP *http.Client
	// BaseURL overrides the resolver, for tests. Empty means BaseURL().
	BaseURL string
	// Now is the clock the bound token's timestamp comes from. Nil means
	// time.Now.
	Now func() time.Time
}

// NewHTTPClient is the transport Client uses when none is supplied.
//
// CheckRedirect refuses every redirect rather than following it, reproducing
// requests' allow_redirects=False: a followed redirect re-sends the signed
// internal headers to whatever a stray `return 301` names.
func NewHTTPClient() *http.Client {
	return &http.Client{
		Timeout: ConnectTimeout + ReadTimeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}
}

// NextSource asks Django which stream to play. identifier is the channel uuid
// or a stream hash, exactly as the Python relay passes it.
//
// A 404 is mapped to an answer with a nil Source and the error string
// "identifier not found", NOT to an error: the channel was deleted mid
// playback, which is an answer (apps/proxy/control_plane.py:158-165).
func (c *Client) NextSource(ctx context.Context, identifier string, req NextSourceRequest) (*NextSourceAnswer, error) {
	path := "/api/relay/channels/" + identifier + "/next-source"
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("encoding the next-source request: %w", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
	}

	raw, status, err := c.post(ctx, path, body)
	if err != nil {
		var refused *Refused
		if errors.As(err, &refused) && status == http.StatusNotFound {
			return &NextSourceAnswer{Alternates: []Source{}, Error: "identifier not found"}, nil
		}
		return nil, err
	}

	var answer NextSourceAnswer
	if err := json.Unmarshal(raw, &answer); err != nil {
		return nil, &Unavailable{Path: path, Reason: "2xx body did not decode as a next-source answer", Err: err}
	}
	return &answer, nil
}

// post is the disposition table from spec § Error handling per hop, in full.
// Only a 5xx or a transport failure consumes the second attempt; every other
// non-2xx outcome raises on the first pass.
func (c *Client) post(ctx context.Context, path string, body []byte) ([]byte, int, error) {
	base := c.BaseURL
	if base == "" {
		resolved, err := BaseURL()
		if err != nil {
			return nil, 0, err
		}
		base = resolved
	}
	httpClient := c.HTTP
	if httpClient == nil {
		httpClient = NewHTTPClient()
	}
	now := c.Now
	if now == nil {
		now = time.Now
	}

	var last error
	for attempt := range attempts {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return nil, 0, ctx.Err()
			case <-time.After(RetryDelay):
			}
		}

		raw, status, err := c.attempt(ctx, httpClient, now, base, path, body)
		if err == nil {
			return raw, status, nil
		}
		var unavailable *Unavailable
		if !errors.As(err, &unavailable) || !unavailable.retryable {
			return nil, status, err
		}
		last = err
	}
	return nil, 0, last
}

func (c *Client) attempt(
	ctx context.Context,
	httpClient *http.Client,
	now func() time.Time,
	base, path string,
	body []byte,
) ([]byte, int, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, base+path, bytes.NewReader(body))
	if err != nil {
		return nil, 0, fmt.Errorf("building the request for %s: %w", path, redact.Error(err))
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(HeaderInternal, InternalPrincipalToken(c.Secret))
	// The bound token signs the FULL path, query string included. There is no
	// query string on this route today; passing path rather than a bare path
	// constant is what keeps that true when one is added.
	request.Header.Set(HeaderInternalRequest,
		InternalRequestHeader(c.Secret, http.MethodPost, path, body, now().Unix()))

	response, err := httpClient.Do(request)
	if err != nil {
		return nil, 0, &Unavailable{Path: path, Reason: "transport failure", Err: err, retryable: true}
	}
	defer func() { _ = response.Body.Close() }()

	status := response.StatusCode
	switch {
	case status >= 300 && status < 400:
		return nil, status, &Unavailable{Path: path, Reason: fmt.Sprintf("answered %d; a redirect is never followed", status)}
	case status >= 400 && status < 500:
		return nil, status, &Refused{Path: path, Status: status}
	case status >= 500:
		return nil, status, &Unavailable{Path: path, Reason: fmt.Sprintf("answered %d", status), retryable: true}
	}

	raw, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, status, &Unavailable{Path: path, Reason: "2xx body could not be read", Err: err, retryable: true}
	}
	var probe any
	if err := json.Unmarshal(raw, &probe); err != nil {
		return nil, status, &Unavailable{Path: path, Reason: "2xx body is not JSON", Err: err}
	}
	if _, isObject := probe.(map[string]any); !isObject {
		return nil, status, &Unavailable{Path: path, Reason: "2xx body is JSON but not an object"}
	}
	return raw, status, nil
}
```

**`relay/control/settings.go`**

```go
package control

import (
	"encoding/json"
	"fmt"
	"time"
)

// Settings is the next-source answer's proxy_settings object, held as raw JSON
// keyed by name rather than as a struct.
//
// A MAP, NOT A STRUCT, and the reason is the whole point of Amendment A1.4.
// Django sends EFFECTIVE settings: the stored CoreSettings group's seven
// snake_case keys, plus every one of apps/proxy/config.py's TSConfig
// class-attribute defaults under its own SCREAMING_CASE name. The relay
// therefore holds no default of its own and there is no second copy to drift.
//
// A struct would reintroduce exactly that. An absent key unmarshals into a
// struct field as the zero value, silently -- a chunk size of 0 deadlocks the
// ring and a retention of 0 empties it -- and only the fields somebody
// remembered to make a pointer would say so. Every accessor below FAILS on an
// absent key instead, for every key, including ones a later PR starts reading.
type Settings map[string]json.RawMessage

// ErrSettingAbsent names a key the control plane did not send.
type ErrSettingAbsent struct{ Key string }

func (e *ErrSettingAbsent) Error() string {
	return fmt.Sprintf("proxy_settings carries no %q: Django sends effective settings, so an "+
		"absent key means the control plane is older than this relay", e.Key)
}

// Int reads an integer setting.
func (s Settings) Int(key string) (int, error) {
	raw, ok := s[key]
	if !ok {
		return 0, &ErrSettingAbsent{Key: key}
	}
	// Through float64: the serializer declares several of these as FloatField,
	// so 15 arrives as 15.0 and json.Unmarshal into an int refuses it.
	var value float64
	if err := json.Unmarshal(raw, &value); err != nil {
		return 0, fmt.Errorf("proxy_settings[%q] is not a number: %w", key, err) // credential-logging: ok - an encoding/json error over a settings value, which is a number or a short string
	}
	return int(value), nil
}

// Float reads a floating-point setting.
func (s Settings) Float(key string) (float64, error) {
	raw, ok := s[key]
	if !ok {
		return 0, &ErrSettingAbsent{Key: key}
	}
	var value float64
	if err := json.Unmarshal(raw, &value); err != nil {
		return 0, fmt.Errorf("proxy_settings[%q] is not a number: %w", key, err) // credential-logging: ok - an encoding/json error over a settings value
	}
	return value, nil
}

// Seconds reads a setting expressed in seconds as a duration. Fractional
// values are honoured: KEEPALIVE_INTERVAL is 0.5.
func (s Settings) Seconds(key string) (time.Duration, error) {
	value, err := s.Float(key)
	if err != nil {
		return 0, err
	}
	return time.Duration(value * float64(time.Second)), nil
}

// String reads a string setting.
func (s Settings) String(key string) (string, error) {
	raw, ok := s[key]
	if !ok {
		return "", &ErrSettingAbsent{Key: key}
	}
	var value string
	if err := json.Unmarshal(raw, &value); err != nil {
		return "", fmt.Errorf("proxy_settings[%q] is not a string: %w", key, err) // credential-logging: ok - an encoding/json error over a settings value; DEFAULT_USER_AGENT is the only string and is not a credential
	}
	return value, nil
}
```

**`relay/control/profile_test.go`**

```go
package control

import (
	"encoding/json"
	"testing"
)

// The three states of stream_profile.argv, decoded from the wire: a list, an
// explicit null, and an absent key. encoding/json cannot tell the last two
// apart for a plain slice field, and the relay must, because they mean
// different things (an unbuildable profile versus an older Django).
func TestArgvPresenceIsDecodedInAllThreeStates(t *testing.T) {
	for _, tc := range []struct {
		name    string
		body    string
		present bool
		argv    []string
	}{
		{"a built list", `{"id":1,"command":"ffmpeg","args":"-i {streamUrl}","kind":"transcode","argv":["-i","http://p/1.ts"]}`, true, []string{"-i", "http://p/1.ts"}},
		{"an empty list, the Proxy shape", `{"id":2,"command":"","args":"","kind":"proxy","argv":[]}`, true, []string{}},
		{"null, an unbuildable profile", `{"id":3,"command":"ffmpeg","args":"-i \"{streamUrl}","kind":"transcode","argv":null}`, true, nil},
		{"absent, an older control plane", `{"id":4,"command":"ffmpeg","args":"-i {streamUrl}","kind":"transcode"}`, false, nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var ref StreamProfileRef
			if err := json.Unmarshal([]byte(tc.body), &ref); err != nil {
				t.Fatalf("decoding: %v", err)
			}
			if ref.ArgvPresent != tc.present {
				t.Fatalf("ArgvPresent = %v, want %v", ref.ArgvPresent, tc.present)
			}
			if (ref.Argv == nil) != (tc.argv == nil) || len(ref.Argv) != len(tc.argv) {
				t.Fatalf("Argv = %#v, want %#v", ref.Argv, tc.argv)
			}
			for i := range tc.argv {
				if ref.Argv[i] != tc.argv[i] {
					t.Fatalf("Argv[%d] = %q, want %q", i, ref.Argv[i], tc.argv[i])
				}
			}
			// The other fields still decode through the custom unmarshaller.
			if ref.Command == "" && tc.name != "an empty list, the Proxy shape" {
				t.Fatal("Command was lost by UnmarshalJSON")
			}
		})
	}
}

// The whole next-source answer, with ffmpeg_stream_profile both null and
// present, through the client's own decoding.
func TestTheFFmpegStreamProfileDecodesNullAndPresent(t *testing.T) {
	var answer NextSourceAnswer
	body := `{"source":{"stream_id":1,"url":"http://p/1.m3u8","user_agent":"ua","transcode":false,"m3u_profile_id":1,
		"slot_reserved":true,"channel_name":"c","stream_name":"s","m3u_profile_name":"m",
		"stream_profile":{"id":1,"command":"","args":"","kind":"proxy","argv":[]},
		"ffmpeg_stream_profile":{"id":9,"command":"ffmpeg","args":"-i {streamUrl}","kind":"transcode","argv":["-i","http://p/1.m3u8"]}},
		"alternates":[],"error":null,"proxy_settings":{}}`
	if err := json.Unmarshal([]byte(body), &answer); err != nil {
		t.Fatalf("decoding: %v", err)
	}
	if answer.Source.FFmpegStreamProfile == nil || answer.Source.FFmpegStreamProfile.ID != 9 {
		t.Fatalf("ffmpeg_stream_profile = %+v, want id 9", answer.Source.FFmpegStreamProfile)
	}
	if !answer.Source.FFmpegStreamProfile.ArgvPresent || len(answer.Source.FFmpegStreamProfile.Argv) != 2 {
		t.Fatalf("ffmpeg_stream_profile.argv = %#v, want two elements", answer.Source.FFmpegStreamProfile.Argv)
	}
	if err := json.Unmarshal([]byte(`{"source":{"stream_profile":{"id":1,"kind":"proxy"},"ffmpeg_stream_profile":null}}`), &answer); err != nil {
		t.Fatalf("decoding a null ffmpeg_stream_profile: %v", err)
	}
	if answer.Source.FFmpegStreamProfile != nil {
		t.Fatal("a null ffmpeg_stream_profile decoded as present")
	}
}
```

### Appendix L — `relay/channel/streamtype.go`, `stats.go`, `source_transcode.go`

**`relay/channel/streamtype.go`**

```go
package channel

import (
	"net/url"
	"strings"
)

// StreamTypeOf classifies an upstream URL the way
// apps/proxy/live_proxy/utils.py:31-69's detect_stream_type does, because
// the answer decides an architecture: a Proxy profile whose URL is HLS, RTSP
// or UDP is played through ffmpeg regardless (input/manager.py:445-453's
// force_ffmpeg), since the raw-HTTP reader cannot follow a playlist or
// speak RTSP.
//
// The five answers are Python's strings: "udp", "rtsp", "hls", "ts" and
// "unknown" for an empty URL. Ported by reading the function, not the
// docstring, which lists four.
func StreamTypeOf(rawURL string) string {
	if rawURL == "" {
		return "unknown"
	}
	lower := strings.ToLower(rawURL)
	if strings.HasPrefix(lower, "udp://") {
		return "udp"
	}
	if strings.HasPrefix(lower, "rtsp://") || strings.HasPrefix(lower, "rtp://") {
		return "rtsp"
	}
	if strings.HasSuffix(lower, ".m3u8") || strings.Contains(lower, ".m3u8?") || strings.Contains(lower, "/playlist.m3u") {
		return "hls"
	}
	// The additional patterns are checked on the PATH alone (utils.py:61-66),
	// so a query string mentioning "manifest" does not count.
	if parsed, err := url.Parse(rawURL); err == nil {
		path := strings.ToLower(parsed.Path)
		m3u := strings.Contains(path, ".m3u") || strings.Contains(path, ".m3u8")
		for _, word := range []string{"playlist", "manifest", "master"} {
			if strings.Contains(path, word) && m3u {
				return "hls"
			}
		}
	}
	return "ts"
}

// NeedsFFmpeg reports whether a URL's stream type forces the transcode path
// on a Proxy profile: input/manager.py:445's (HLS, RTSP, UDP) tuple.
func NeedsFFmpeg(rawURL string) bool {
	switch StreamTypeOf(rawURL) {
	case "hls", "rtsp", "udp":
		return true
	}
	return false
}
```

**`relay/channel/stats.go`**

```go
package channel

import (
	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
)

// Stats is the stream information a transcode process has told this
// channel: the in-memory equivalent of the metadata hash's stream-info
// fields (ChannelMetadataField.VIDEO_CODEC ... STREAM_TYPE, written by
// channel_service.py:844-880) and its ffmpeg-performance fields
// (FFMPEG_SPEED ... FFMPEG_OUTPUT_BITRATE, written by
// input/manager.py:1250-1275).
//
// A nil pointer is a field the hash never had, which the status endpoints
// render by OMITTING the key (channel_status.py:605-627 assigns each only
// inside an `if`). The Proxy architecture spawns nothing and so never sets
// any of them -- parity-matrix row 29.
//
// EVERY VALUE IS ROUNDED THE WAY PYTHON STORES IT, at the moment it is
// applied: Python writes str(round(x, n)) into the hash and reads the string
// back as a float, so the rounded value is what the wire carries.
type Stats struct {
	VideoCodec    *string
	Resolution    *string
	Width         *int
	Height        *int
	SourceFPS     *float64 // round(fps, 2), channel_service.py:858
	PixelFormat   *string
	VideoBitrate  *float64 // round(kbps, 1), :864
	AudioCodec    *string
	SampleRate    *int
	AudioChannels *string
	AudioBitrate  *float64 // round(kbps, 1), :877
	StreamType    *string  // the probed input format, :879

	FFmpegSpeed         *float64 // round(speed, 3), input/manager.py:1260
	FFmpegFPS           *float64 // round(fps, 1), :1263
	ActualFPS           *float64 // round(fps / speed, 1), :1266
	FFmpegOutputBitrate *float64 // round(kbps, 1), :1269
}

// Stats is a snapshot of what the transcode process has reported so far.
func (c *Channel) Stats() Stats {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.stats
}

// reportInfo merges one parsed stream-info line, with hset semantics: a
// field the line did not carry leaves the earlier value standing.
func (c *Channel) reportInfo(info ffmpeg.Info) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if info.VideoCodec != nil {
		c.stats.VideoCodec = info.VideoCodec
	}
	if info.Resolution != nil {
		c.stats.Resolution = info.Resolution
	}
	if info.Width != nil {
		c.stats.Width = info.Width
	}
	if info.Height != nil {
		c.stats.Height = info.Height
	}
	if info.SourceFPS != nil {
		c.stats.SourceFPS = rounded(*info.SourceFPS, 2)
	}
	if info.PixelFormat != nil {
		c.stats.PixelFormat = info.PixelFormat
	}
	if info.VideoBitrate != nil {
		c.stats.VideoBitrate = rounded(*info.VideoBitrate, 1)
	}
	if info.AudioCodec != nil {
		c.stats.AudioCodec = info.AudioCodec
	}
	if info.SampleRate != nil {
		c.stats.SampleRate = info.SampleRate
	}
	if info.AudioChannels != nil {
		c.stats.AudioChannels = info.AudioChannels
	}
	if info.AudioBitrate != nil {
		c.stats.AudioBitrate = rounded(*info.AudioBitrate, 1)
	}
	if info.InputFormat != nil {
		c.stats.StreamType = info.InputFormat
	}
}

// reportProgress applies one progress record's four values.
func (c *Channel) reportProgress(p ffmpeg.Progress) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if p.Speed != nil {
		c.stats.FFmpegSpeed = rounded(*p.Speed, 3)
	}
	if p.FPS != nil {
		c.stats.FFmpegFPS = rounded(*p.FPS, 1)
	}
	if p.ActualFPS != nil {
		c.stats.ActualFPS = rounded(*p.ActualFPS, 1)
	}
	if p.OutputBitrateKbps != nil {
		c.stats.FFmpegOutputBitrate = rounded(*p.OutputBitrateKbps, 1)
	}
}

// reportBuffering moves the channel into and out of the buffering state,
// the port of input/manager.py:1232-1234 (hset BUFFERING on a sub-threshold
// sample) and :1244-1247 (hset ACTIVE on recovery).
//
// RECOVERY MOVES TO ACTIVE ONLY FROM BUFFERING. Python's hset is unguarded
// -- it writes ACTIVE whatever the state was -- and promoteOnFirstChunk is
// the one mechanism for waiting_for_clients -> active in this package
// (channel.go), so a second path that could set active from any state would
// be the two-mechanism shape 2c-2's review found and removed. A channel that
// is stopping or has errored stays that way too, on both edges; Python's
// stderr thread can race its own teardown into a stale BUFFERING write,
// and that is a divergence in the safe direction.
func (c *Channel) reportBuffering(on bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	switch {
	case on && (c.state == StateWaitingForClients || c.state == StateActive || c.state == StateInitializing):
		c.state = StateBuffering
	case !on && c.state == StateBuffering:
		c.state = StateActive
	}
}

func rounded(x float64, places int) *float64 {
	v := ffmpeg.Round(x, places)
	return &v
}
```

**`relay/channel/source_transcode.go`**

```go
package channel

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// ErrBufferingTimeout is returned when ffmpeg's reported speed stayed below
// buffering_speed for longer than buffering_timeout.
//
// 2c-4 ENDS THE TUNE ON THIS, the same decision 2c-2 took for
// ErrUpstreamIdle and for the same reason: Python calls _try_next_stream()
// at this point (input/manager.py:1182, parity-matrix row 1) and 2c-4 has no
// failover to call. Ending the source with a named error is the honest
// shape; 2c-5 replaces the one call site that raises it with the failover,
// and rows 1 and 6 close there.
var ErrBufferingTimeout = errors.New("channel: the transcode process buffered past buffering_timeout")

// ErrInputFailed is VLC's "unable to open the MRL": input/manager.py:1059-1064
// closes the socket on it, which the main loop then reads as a connection
// failure. Only reachable when the profile's command is literally vlc or
// cvlc -- auto-detection never reports it (ffmpeg.AutoParse).
var ErrInputFailed = errors.New("channel: the transcode process could not open its input")

// TranscodeSource is the FFmpeg, VLC and Streamlink stream-profile
// architectures: a subprocess whose fd 1 is the video and whose fd 2 is
// parsed line by line. The port of input/manager.py's transcode half --
// _establish_transcode_connection, the stderr reader thread,
// _log_stderr_content and _parse_ffmpeg_stats -- behind the same one-method
// Source interface ProxySource implements.
//
// THE ARGV ARRIVES BUILT. Django ran StreamProfile.build_command on the
// answer (core/models.py:137-160: shlex.split of the profile's parameters,
// then the three {streamUrl}/{userAgent}/{channelId} substitutions), so
// Argv is what Python would spawn, and this relay carries no shell word
// splitter and no substitution table. Spec Amendment A4.1 has the ruling.
// The ONE transformation left here is Python's own, at input/manager.py:
// 808-812: a UDP upstream has every user-agent argument removed.
type TranscodeSource struct {
	// Command is the profile's executable: "ffmpeg", "vlc", "streamlink",
	// or an operator's path. It also selects the log parser
	// (ffmpeg.ToolFor), exactly as input/manager.py:797-803 does.
	Command string

	// Argv is the built argument list, without the command.
	Argv []string

	// URL is the provider URL the argv carries. Read for ONE thing: the
	// stream type, which decides the UDP filter. It is never logged and
	// never put in an error.
	URL string

	// UserAgent is the user agent Django substituted for {userAgent}, so
	// the UDP filter can find the arguments that carry it
	// (input/manager.py:811's `self.user_agent not in arg`).
	UserAgent string

	// ChunkSize is the read size off fd 1. Zero means 8192,
	// apps/proxy/config.py:7's CHUNK_SIZE, which input/manager.py:1843's
	// os.read uses. The same default, for the same reason, as ProxySource.
	ChunkSize int

	// Now is the detector's clock. Nil means time.Now.
	Now func() time.Time

	// channel is set by run() through attach: where stats and state go,
	// and where the detector's thresholds come from. THE SOURCE HOLDS NO
	// COPY OF buffering_speed OR buffering_timeout: they are read off the
	// channel's Tuning, the one snapshot of the tune's proxy_settings
	// (parity-matrix row 5), so there is no second field to drift from it.
	// An earlier draft carried both on this struct as well, and the first
	// tests written against it never armed, because the fields the tests
	// set were not the fields the detector read.
	channel *Channel

	mu    sync.Mutex
	cause error
}

// attach is the seam Channel.run uses to hand a source its channel. It is
// unexported and the interface it satisfies is package-private, so nothing
// outside this package can point a source at a channel it does not run on.
func (s *TranscodeSource) attach(c *Channel) { s.channel = c }

func (s *TranscodeSource) chunkSize() int {
	if s.ChunkSize > 0 {
		return s.ChunkSize
	}
	return 8192
}

func (s *TranscodeSource) log() *slog.Logger {
	if s.channel != nil && s.channel.log != nil {
		return s.channel.log
	}
	return slog.Default()
}

// argv applies the one transformation input/manager.py:808-812 applies at
// spawn time: on a UDP upstream every argument that contains the user agent,
// or "user-agent" or "user_agent" in any case, is dropped.
//
// Python filters self.transcode_cmd, which INCLUDES the command at index 0;
// a command containing "user-agent" would be dropped there and the spawn
// would fail on the first argument. That shape is not reproduced: the
// command is not an argument.
func (s *TranscodeSource) argv() []string {
	if StreamTypeOf(s.URL) != "udp" {
		return s.Argv
	}
	kept := make([]string, 0, len(s.Argv))
	for _, arg := range s.Argv {
		lower := strings.ToLower(arg)
		if (s.UserAgent != "" && strings.Contains(arg, s.UserAgent)) ||
			strings.Contains(lower, "user-agent") || strings.Contains(lower, "user_agent") {
			continue
		}
		kept = append(kept, arg)
	}
	return kept
}

// fail records why the source is ending and stops the process. The first
// cause wins; a later one (the SIGKILL's own exit status, say) does not
// overwrite it.
func (s *TranscodeSource) fail(cause error, cancel context.CancelFunc) {
	s.mu.Lock()
	if s.cause == nil {
		s.cause = cause
	}
	s.mu.Unlock()
	cancel()
}

func (s *TranscodeSource) failure() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.cause
}

// Run spawns the process and copies its fd 1 into sink until it ends, the
// detector times out, or ctx is done.
func (s *TranscodeSource) Run(parent context.Context, sink io.Writer) error {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()

	proc, err := ffmpeg.Start(ctx, s.Command, s.argv())
	if err != nil {
		return fmt.Errorf("channel: starting the transcode process: %w", redact.Error(err))
	}

	var tuning Tuning
	if s.channel != nil {
		tuning = s.channel.tuning
	}
	reader := &stderrReader{source: s, cancel: cancel, inputPhase: true,
		detector: ffmpeg.Detector{Threshold: tuning.BufferingSpeed, Timeout: tuning.BufferingTimeout, Now: s.Now}}
	reader.tool, reader.toolKnown = ffmpeg.ToolFor(s.Command)
	stderrDone := make(chan struct{})
	go func() {
		defer close(stderrDone)
		proc.ReadStderr(reader.line)
	}()

	buf := make([]byte, s.chunkSize())
	var copyErr error
	for {
		n, readErr := proc.Stdout().Read(buf)
		if n > 0 {
			if _, writeErr := sink.Write(buf[:n]); writeErr != nil {
				copyErr = fmt.Errorf("channel: writing transcode bytes to the buffer: %w", redact.Error(writeErr))
				break
			}
		}
		if readErr != nil {
			break
		}
	}

	// fd 1 is closed. Python's _close_socket kills and waits half a second
	// (input/manager.py:1737-1749); a process that exits on its own inside
	// that window reports its real status, one that lingers is killed.
	exit := waitOrKill(proc)
	cancel()
	<-stderrDone

	switch {
	case copyErr != nil:
		return copyErr
	case s.failure() != nil:
		return s.failure()
	case parent.Err() != nil:
		return parent.Err()
	case exit == nil:
		return nil
	default:
		return exit
	}
}

func waitOrKill(proc *ffmpeg.Process) error {
	done := make(chan error, 1)
	go func() { done <- proc.Wait() }()
	select {
	case err := <-done:
		return err
	case <-time.After(ffmpeg.KillWait):
		proc.Kill()
		return <-done
	}
}

// stderrReader is the port of the stderr reader thread's per-line work:
// _read_stderr's frame= gate (input/manager.py:993), _parse_ffmpeg_stats
// and the buffering decision (:1102-1247), and _log_stderr_content's phase
// tracking, parser routing and log levels (:1031-1100).
type stderrReader struct {
	source     *TranscodeSource
	cancel     context.CancelFunc
	tool       ffmpeg.Tool
	toolKnown  bool
	inputPhase bool
	detector   ffmpeg.Detector
}

func (r *stderrReader) line(line string) {
	s := r.source
	log := s.log()

	if ffmpeg.IsProgressLine(line) {
		r.progress(line)
	}

	lower := strings.ToLower(line)
	// Phase tracking, :1041-1045: an Input or decoder line means the input
	// phase, an Output or encoder line ends it. Stream lines are parsed as
	// input info only during the input phase, so the OUTPUT stream lines
	// ffmpeg prints for its own remux do not overwrite the source's.
	if strings.HasPrefix(lower, "input #") || strings.Contains(lower, "decoder") {
		r.inputPhase = true
	}
	if strings.HasPrefix(lower, "output #") || strings.Contains(lower, "encoder") {
		r.inputPhase = false
	}

	var kind ffmpeg.Kind
	var info ffmpeg.Info
	var parsed bool
	if r.toolKnown {
		// Direct routing, :1054-1069.
		kind = ffmpeg.CanParse(r.tool, line)
		if kind == ffmpeg.KindVLCInputFailed {
			log.Warn("the transcode process could not open its input", "channel", s.channelID(), "line", redact.Line(line))
			s.fail(ErrInputFailed, r.cancel)
		} else if kind != "" {
			info, parsed = ffmpeg.Parse(kind, line)
		}
	} else {
		kind, info, parsed = ffmpeg.AutoParse(line)
	}
	if parsed && s.channel != nil {
		switch kind {
		case ffmpeg.KindVideo, ffmpeg.KindAudio, ffmpeg.KindInput:
			// FFmpeg lines count only during the input phase, :1079-1082.
			if r.inputPhase {
				s.channel.reportInfo(info)
			}
		default:
			// VLC and Streamlink lines count any time, :1083-1085.
			s.channel.reportInfo(info)
		}
	}

	// The log levels of :1088-1098, through redact.Line: ffmpeg's preamble
	// echoes the provider URL ("Input #0, mpegts, from '<url>':") and its
	// HLS demuxer echoes every segment URL, and Python logs both verbatim
	// at INFO -- a credential leak scripts/check_credential_logging.py
	// cannot see, because the variable is not named for a URL. Not
	// reproduced.
	redacted := redact.Line(line)
	switch {
	case containsAny(lower, "error", "failed", "cannot", "invalid", "corrupt"):
		log.Error("transcode process error", "channel", s.channelID(), "line", redacted)
	case containsAny(lower, "warning", "deprecated", "ignoring"):
		log.Warn("transcode process warning", "channel", s.channelID(), "line", redacted)
	case strings.HasPrefix(line, "frame=") || strings.Contains(line, "fps=") || strings.Contains(line, "speed="):
		// Python's trace level; slog has no lower level than Debug.
		log.Debug("transcode stats", "channel", s.channelID(), "line", redacted)
	case containsAny(lower, "input", "output", "stream", "video", "audio"):
		log.Info("transcode stream info", "channel", s.channelID(), "line", redacted)
	default:
		log.Debug("transcode process output", "channel", s.channelID(), "line", redacted)
	}
}

// progress is _parse_ffmpeg_stats: the four values to the channel, then the
// buffering decision on the speed.
func (r *stderrReader) progress(line string) {
	s := r.source
	p, ok := ffmpeg.ParseProgress(line)
	if !ok {
		return
	}
	if s.channel != nil {
		s.channel.reportProgress(p)
	}
	if p.Speed == nil {
		return
	}
	switch verdict := r.detector.Observe(*p.Speed); verdict {
	case ffmpeg.Started:
		// :1213-1226: the flag, the clock, a warning, the channel_buffering
		// event -- which is 2c-5's, with the events route -- and the state.
		s.log().Warn("buffering started", "channel", s.channelID(), "speed", *p.Speed, "threshold", r.detector.Threshold)
		if s.channel != nil {
			s.channel.reportBuffering(true)
		}
	case ffmpeg.Continuing:
		// :1232-1234 re-writes the BUFFERING state on every sample; the
		// state is already buffering here, so there is nothing to write.
	case ffmpeg.TimedOut:
		// :1178-1211: Python tries the next stream. 2c-4 ends the tune with
		// a named error instead (ErrBufferingTimeout's comment); 2c-5
		// replaces this arm and this arm only.
		s.log().Error("buffering timeout reached", "channel", s.channelID(), "speed", *p.Speed, "timeout", r.detector.Timeout)
		s.fail(ErrBufferingTimeout, r.cancel)
	case ffmpeg.Ended:
		s.log().Info("buffering ended", "channel", s.channelID(), "speed", *p.Speed)
		if s.channel != nil {
			s.channel.reportBuffering(false)
		}
	case ffmpeg.Steady:
	}
}

func (s *TranscodeSource) channelID() string {
	if s.channel == nil {
		return ""
	}
	return s.channel.id
}

func containsAny(s string, words ...string) bool {
	for _, w := range words {
		if strings.Contains(s, w) {
			return true
		}
	}
	return false
}
```

### Appendix M — `relay/channel/channel.go` (whole file after 2c-4), `tuning.go`, `state.go`

**`relay/channel/channel.go`**

```go
// Package channel owns a channel's lifecycle: ownership, the state machine,
// the switch coordination between the HTTP handlers and the channel's own
// goroutine, and the client registry.
//
// Empty at 2c-1. 2c-2 brings the first real type.
//
// WHAT THIS PACKAGE DELIBERATELY DOES NOT CONTAIN, because the Python relay's
// equivalents are deleted rather than ported (spec D2):
//
//   - No ownership lease. One relay process per host by construction, so
//     there is never a second writer to fence against. live:channel:{id}:owner,
//     _ensure_owner_or_stop, release_ownership's non-atomic GET-compare-DELETE
//     and extend_ownership's non-atomic GET-EXPIRE all go. Ownership becomes
//     map[uuid]*Channel behind a sync.RWMutex.
//   - No follower path and no live:events:{id} pub/sub. Those were
//     multi-worker follower-to-owner coordination; with one owner per channel
//     by construction they have no purpose.
//   - No Redis client, and no Postgres driver. The phase's two checkable
//     invariants (spec § Stage 2c, "The two invariants"). Switch coordination
//     is a Go chan; the degraded-fallback source cache, the metadata hash, the
//     stopping flag and the timing counters are all fields on the channel
//     struct.
package channel

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"sort"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// ErrDuplicateClient is returned by Attach when the channel already has a
// client registered under this id.
//
// The port of client_manager.py:218-221, whose add_client returns False for an
// id already in _registered_clients; views.py:748-753 turns that False into a
// 503. One process means one registry, so what Python enforces per worker is
// enforced outright here.
var ErrDuplicateClient = errors.New("channel: a client with this id is already attached")

// SourceInfo is what the next-source answer said about the stream this channel
// is playing, kept so the status endpoints can render it without a second
// control-plane call. The fields are exactly the ones
// ChannelStatus.get_basic_channel_info reads out of the metadata hash.
type SourceInfo struct {
	// URL is the provider URL. It reaches the /proxy/relay/channels payload
	// because channel_status.py:472 puts it there and the Stats page shows it;
	// that surface is internal and HMAC-authenticated. It must never reach a
	// log line or a public response body.
	URL string

	// StreamProfileID is rendered as a STRING, because the metadata hash stores
	// str(source["stream_profile"]["id"]) (input/manager.py:2165) and the
	// serializer declares CharField.
	StreamProfileID int

	StreamID       int
	StreamName     string
	ChannelName    string
	M3UProfileID   int
	M3UProfileName string
}

// Channel is one running channel: its ring buffer, its source goroutine, its
// client count and its state.
//
// There is NO OWNERSHIP LEASE here, and that is spec D2 rather than an
// omission. One relay process per host by construction means there is never a
// second writer to fence against, so live:channel:{id}:owner,
// _ensure_owner_or_stop, release_ownership's non-atomic GET-compare-DELETE and
// extend_ownership's non-atomic GET-EXPIRE are deleted rather than ported --
// together with the follower path and live:events:{id}, which existed only to
// let a non-owning worker ask the owner to act.
type Channel struct {
	id        string
	ring      *buffer.Ring
	log       *slog.Logger
	tuning    Tuning
	source    SourceInfo
	startedAt time.Time

	mu      sync.RWMutex
	state   State
	lastErr error
	// stats is what a transcode process has reported (stats.go). Empty for
	// the Proxy architecture, which spawns nothing -- parity-matrix row 29.
	stats Stats
	// clients is the registry. Guarded by mu; the manager reads its length
	// through Clients() inside its own critical section, which is what makes
	// stopIfStillIdle's re-check and claim's addClient mutually exclusive.
	clients map[string]*Client

	cancel context.CancelFunc
	done   chan struct{}
}

// ID is the channel uuid the control plane and every client address it by.
func (c *Channel) ID() string { return c.id }

// Ring is the channel's buffer. Readers take chunks from it directly.
func (c *Channel) Ring() *buffer.Ring { return c.ring }

// Tuning is the channel-start-time settings this channel was started with.
//
// SNAPSHOTTED AT CHANNEL START, which is parity-matrix row 5 and not an
// optimisation: Python reads its thresholds in StreamManager.__init__ and a
// proxy_settings change never reaches a running channel. Serving it from here
// is also what lets a second client attach without a next-source call, since
// the settings arrive on that answer and the second client never makes one.
func (c *Channel) Tuning() Tuning { return c.tuning }

// State is the channel's current lifecycle state.
func (c *Channel) State() State {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.state
}

// Err is the error that put the channel into StateError, or nil.
func (c *Channel) Err() error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.lastErr
}

// Clients is how many readers are attached.
//
// Never capped, matching channel_status.py:461's SCARD: the LIST is capped at
// ten without ?clients=all, the COUNT never is. The manager calls this inside
// its own lock (stopIfStillIdle), so it must never take m.mu itself.
func (c *Channel) Clients() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.clients)
}

// Done is closed once the source goroutine has returned and the ring is shut.
func (c *Channel) Done() <-chan struct{} { return c.done }

// addClient and dropClient are the only writers of c.clients. They exist as
// methods so the manager can adjust the count while holding its own lock
// without reaching into this struct -- the lock order is always manager then
// channel, and nothing takes them the other way round.
func (c *Channel) addClient(cl *Client) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, taken := c.clients[cl.ID]; taken {
		return false
	}
	c.clients[cl.ID] = cl
	return true
}

// dropClient removes one client and reports how many remain.
func (c *Channel) dropClient(id string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.clients, id)
	return len(c.clients)
}

// ClientSnapshot is every attached client, oldest connection first and ties
// broken by id.
//
// DETERMINISTIC ORDER, where Python's is arbitrary: channel_status.py:533 reads
// a Redis SET with SMEMBERS and slices the first ten of whatever order that
// returned, so no order is the contract and any deterministic one is parity. It
// is deterministic here because a golden-file comparison against the Python
// serializer needs it to be, and because "the ten clients the list shows" being
// a stable set is strictly better than a set that reshuffles between polls.
func (c *Channel) ClientSnapshot() []Client {
	c.mu.RLock()
	defer c.mu.RUnlock()
	out := make([]Client, 0, len(c.clients))
	for _, cl := range c.clients {
		out = append(out, *cl)
	}
	sort.Slice(out, func(i, j int) bool {
		if !out[i].ConnectedAt.Equal(out[j].ConnectedAt) {
			return out[i].ConnectedAt.Before(out[j].ConnectedAt)
		}
		return out[i].ID < out[j].ID
	})
	return out
}

// Source is what the next-source answer said about this channel's stream.
func (c *Channel) Source() SourceInfo { return c.source }

// StartedAt is when the channel was published.
func (c *Channel) StartedAt() time.Time { return c.startedAt }

func (c *Channel) setState(state State, err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.state = state
	if err != nil {
		c.lastErr = err
	}
}

// attachable is the optional interface a Source implements to be handed the
// channel it runs on, for stats and state. TranscodeSource does; ProxySource
// has nothing to report and does not. Checked once, in run, so a source is
// attached to exactly the channel whose goroutine runs it.
type attachable interface{ attach(*Channel) }

// run is the source goroutine. Exactly one per channel, started by the
// manager.
//
// It does NOT remove itself from the manager's map. Manager.claim drops a
// channel whose ring has closed, and that is the only place it happens: two
// mechanisms for one property means deleting either one changes no test,
// because the other covers for it silently.
func (c *Channel) run(ctx context.Context, source Source) {
	defer close(c.done)
	defer c.ring.Close()

	if a, ok := source.(attachable); ok {
		a.attach(c)
	}
	c.setState(StateWaitingForClients, nil)
	go c.promoteOnFirstChunk(ctx)
	err := source.Run(ctx, c.ring)

	switch {
	case err == nil:
		// A clean upstream EOF. Python treats this as the stream ending and
		// the channel stopping; the failover that would try the next
		// candidate instead is parity-matrix rows 1-3 and 2c-5's.
		c.log.Info("upstream ended", "channel", c.id)
		c.setState(StateStopped, nil)
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		c.log.Info("channel stopped", "channel", c.id)
		c.setState(StateStopped, nil)
	default:
		// Through redact.Error, which is what relay/internal/credlint holds
		// every error-typed log argument in this module to: a provider URL
		// carries provider credentials (CLAUDE.md, § Known defects).
		c.log.Error("upstream failed", "channel", c.id, "error", redact.Error(err))
		c.setState(StateError, err)
	}
}

// promoteOnFirstChunk moves a channel out of waiting_for_clients the moment
// its first chunk is published, mirroring the waiting_for_clients + data ->
// active half of Python's promotion (apps/proxy/live_proxy/services/
// channel_service.py:204-240's promote_channel_when_buffer_ready): "clients"
// is not a separate condition to check here the way it is there, because a
// channel in this manager never exists without at least one attached client
// -- Manager.publish always installs the first client before starting this
// goroutine (manager.go's own doc comment on publish). No parity-matrix row
// pins this transition yet; it is one to add when a later PR builds the
// status routes that expose `state`.
//
// THIS IS THE ONLY PLACE state MOVES TO active. An earlier version called an
// equivalent method (markActive) from the manager's Attach path instead --
// on a SECOND client's arrival, never the first -- which meant a channel's
// very first (and often only) client never triggered it at all, and a
// second client's call raced run()'s own concurrent write of
// waiting_for_clients so it was usually a no-op anyway: measured by review
// at 0/300 rounds ever reaching active. Two mechanisms for one transition is
// exactly the shape CLAUDE.md's Ruling R11 warns about elsewhere in this
// package -- removing the wrong one would have changed no test. There is
// now exactly one.
//
// Runs as its own goroutine, started by run() alongside the source's copy
// loop, because Ring.Wait is the ring's only "something was published"
// signal and the copy loop itself is busy blocking on the upstream read.
func (c *Channel) promoteOnFirstChunk(ctx context.Context) {
	if err := c.ring.Wait(ctx, 0); err != nil {
		// ctx.Err(): the channel stopped before any data arrived. ErrClosed:
		// the ring closed with nothing ever published (e.g. an immediate
		// upstream failure) -- Python's equivalent returns None ("no
		// promotion applies") in both cases, never active.
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.state == StateWaitingForClients {
		c.state = StateActive
	}
}

// ensure the ring satisfies io.Writer where it is used as the sink.
var _ io.Writer = (*buffer.Ring)(nil)

// stop cancels the source and waits for it, bounded by wait.
func (c *Channel) stop(wait time.Duration) {
	c.cancel()
	select {
	case <-c.done:
	case <-time.After(wait):
		c.log.Warn("source goroutine did not return in time", "channel", c.id, "waited", wait)
	}
}
```

**`relay/channel/tuning.go`**

```go
package channel

import "time"

// Tuning is the channel-start-time settings a channel runs on, already
// resolved from the control plane's proxy_settings into Go types.
//
// A plain struct of durations and ints rather than the wire object, so this
// package never imports the wire package: httpapi resolves proxy_settings once
// per tune and hands the result down, and 2c-4's ffmpeg source is handed the
// same struct. Every field names its source, because a value with no named
// source is the second copy Amendment A1.4 exists to stop.
//
// THREE FIELDS, NOT SIX. An earlier draft of this struct also carried a client
// timeout, a keepalive interval and a keepalive cap. All three are 2c-5's,
// because in Python all three are gated on a health flag only the failover
// machinery lowers: _should_send_keepalive returns False unless
// stream_manager.healthy is false (output/ts/generator.py:549-551) and
// _is_timeout returns False unless the same flag is false (:592). A channel
// this PR serves is either running or finished, so neither gate ever opens,
// and a field with no reader is a stale duplicate of the truth waiting to
// happen.
type Tuning struct {
	// ChunkBytes is the ring's write unit, from BUFFER_CHUNK_SIZE.
	ChunkBytes int

	// Retention is how far back the ring reaches, from redis_chunk_ttl. The
	// key keeps its Redis-era name on the wire because D5 is strict parity
	// and renaming a settings key is a change the settings UI can see.
	Retention time.Duration

	// JoinBehind is how far behind live a new client starts, from
	// new_client_behind_seconds. Zero means start at the live head, which is
	// what the setting's own 0 means (output/ts/generator.py:296-302).
	JoinBehind time.Duration

	// ShutdownDelay is how long a channel with no clients stays up, from
	// channel_shutdown_delay. 2c-3 supplies it; see the plan's Ruling R4.
	ShutdownDelay time.Duration

	// BufferingSpeed is buffering_speed: the ffmpeg-reported speed below
	// which a transcode channel is buffering. Read by TranscodeSource's
	// detector and by nothing on the Proxy path -- parity-matrix row 29,
	// the detector is ffmpeg-exclusive.
	BufferingSpeed float64

	// BufferingTimeout is buffering_timeout: how long buffering may last
	// before the detector gives up on the source.
	BufferingTimeout time.Duration
}
```

**`relay/channel/state.go`**

```go
package channel

// State is a channel's lifecycle state, spelled exactly as
// apps/proxy/live_proxy/constants.py's ChannelState spells it, because these
// strings reach a client through the status endpoints' `state` field and a
// rename is a wire change.
//
// The full Python vocabulary is eight values. Buffering is entered only by
// the ffmpeg stderr reader (2c-4's TranscodeSource; parity-matrix row 29
// pins that the Proxy architecture never enters it) and Stopping by the
// coordinated teardown (2c-8). Connecting is NOT transcode-specific, which
// 2c-2's version of this comment said: input/manager.py:1905-1963 sets it on
// BOTH paths, for the window after a connection is up and before the ring
// holds INITIAL_BEHIND_CHUNKS (4) chunks, and promote_channel_when_buffer_
// ready moves it on. That window is not ported -- promoteOnFirstChunk is the
// one promotion mechanism here and it fires on the first chunk, not the
// fourth -- so Connecting is declared and never entered, and a later PR
// that wants it adds a transition rather than a constant.
type State string

// The eight states. Only Initializing, WaitingForClients, Active, Error and
// Stopped are reachable in 2c-2.
const (
	StateInitializing      State = "initializing"
	StateConnecting        State = "connecting"
	StateWaitingForClients State = "waiting_for_clients"
	StateActive            State = "active"
	StateBuffering         State = "buffering"
	StateError             State = "error"
	StateStopping          State = "stopping"
	StateStopped           State = "stopped"
)
```

### Appendix N — `relay/channel/source_proxy.go` — the whole file after 2c-4

**`relay/channel/source_proxy.go`**

```go
package channel

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"sync/atomic"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// Source produces one channel's upstream bytes.
//
// One method, so 2c-4's ffmpeg source drops in beside this one without either
// knowing about the other. The ring buffer is the sink and is an io.Writer, so
// a source never learns what a chunk is.
type Source interface {
	// Run copies upstream bytes into sink. It returns nil on a clean upstream
	// EOF, ctx.Err() when the caller cancels, and a named error otherwise.
	Run(ctx context.Context, sink io.Writer) error
}

// ErrUpstreamIdle is returned when the upstream sent nothing for ReadTimeout.
//
// 2c-2 ENDS THE TUNE ON THIS. That is not the dead-air failover trigger, which
// is parity-matrix row 2 and 2c-5's: Python's fetch_chunk returns False on a
// CHUNK_TIMEOUT read timeout and the main loop keeps going, and only the
// separate 10-second watchdog, observed on three consecutive five-second
// health checks, calls _try_next_stream(). 2c-2 has no failover to call, so
// the honest thing is to end the copy and say why, rather than ship a
// half-detector that looks like row 2 and is not.
var ErrUpstreamIdle = errors.New("channel: upstream sent nothing within the read timeout")

// ErrUpstreamStatus is returned when the provider answered other than 200.
type ErrUpstreamStatus struct{ Status int }

func (e *ErrUpstreamStatus) Error() string {
	return fmt.Sprintf("channel: upstream answered HTTP %d", e.Status)
}

// ProxySource is the Proxy stream-profile architecture: a raw HTTP GET whose
// body goes straight into the ring buffer. No subprocess, no stderr, and --
// parity-matrix row 29 -- therefore no ffmpeg_speed, no buffering state and no
// buffering failover, however far below the threshold the upstream runs.
//
// The Python original (input/http_streamer.py) reads the response on an OS
// thread and writes it down an O_NONBLOCK pipe, which the main loop then
// reads with select, so that the Proxy and transcode paths share one
// fetch_chunk(). That whole apparatus exists to keep a blocking read off the
// gevent hub. Go's scheduler multiplexes blocking I/O onto OS threads itself,
// so the pipe, the fcntl, the select and the second thread all go and what is
// left is the copy they existed to perform.
type ProxySource struct {
	// URL is the provider URL Django's next-source answer named.
	URL string

	// UserAgent goes on the request when non-empty.
	UserAgent string

	// ChunkSize is the read size. Zero means 8192, apps/proxy/config.py:7's
	// CHUNK_SIZE, which is also HTTPStreamReader's own default parameter
	// value at apps/proxy/live_proxy/input/http_streamer.py:18. Pinned,
	// against the zero value rather than a passed-in one, by
	// TestProxySourceDefaultsMatchPython.
	ChunkSize int

	// ConnectTimeout bounds the dial and the response headers. Zero means 5
	// seconds, the first half of apps/proxy/live_proxy/input/
	// http_streamer.py:71's timeout=(5, 30). Pinned by
	// TestProxySourceDefaultsMatchPython.
	ConnectTimeout time.Duration

	// ReadTimeout bounds the gap between bytes, which is what requests' read
	// timeout means. Zero means 30 seconds, the second half of the same pair
	// at the same line. Pinned by TestProxySourceDefaultsMatchPython.
	ReadTimeout time.Duration

	// Transport overrides the HTTP transport, for tests. Nil means one built
	// from ConnectTimeout with no retries and a single connection, matching
	// HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1).
	Transport http.RoundTripper
}

func (s ProxySource) chunkSize() int {
	if s.ChunkSize > 0 {
		return s.ChunkSize
	}
	return 8192
}

func (s ProxySource) connectTimeout() time.Duration {
	if s.ConnectTimeout > 0 {
		return s.ConnectTimeout
	}
	return 5 * time.Second
}

func (s ProxySource) readTimeout() time.Duration {
	if s.ReadTimeout > 0 {
		return s.ReadTimeout
	}
	return 30 * time.Second
}

func (s ProxySource) transport() http.RoundTripper {
	if s.Transport != nil {
		return s.Transport
	}
	return &http.Transport{
		DialContext:           (&net.Dialer{Timeout: s.connectTimeout()}).DialContext,
		ResponseHeaderTimeout: s.connectTimeout(),
		MaxIdleConns:          1,
		MaxConnsPerHost:       1,
		DisableCompression:    true,
	}
}

// Run connects and copies until the upstream ends, the upstream goes idle, or
// ctx is done.
func (s ProxySource) Run(parent context.Context, sink io.Writer) error {
	// The derived context is the watchdog's lever. `parent` is kept under its
	// own name so a cancellation can be attributed correctly below: without
	// it, a client that disconnects at the same moment the watchdog fires
	// would be reported as an idle upstream, which is the wrong diagnosis on
	// the one signal 2c-5 turns into a failover.
	ctx, cancel := context.WithCancel(parent)
	defer cancel()

	request, err := http.NewRequestWithContext(ctx, http.MethodGet, s.URL, nil)
	if err != nil {
		// The URL came from the control plane, so a bad one is a control-plane
		// answer this relay cannot use. The URL itself is NEVER in the message:
		// it carries provider credentials (CLAUDE.md, credential logging).
		// NewRequestWithContext returns url.Parse's own error unwrapped on a
		// malformed URL, which is already a *url.Error printing the whole
		// string verbatim -- withoutURL strips it here exactly as it does at
		// the connect-failure site below; a bare %w was found by review to
		// leak it into channel.go's "upstream failed" log line.
		return fmt.Errorf("channel: the source URL is not usable: %w", redact.Error(err))
	}
	if s.UserAgent != "" {
		request.Header.Set("User-Agent", s.UserAgent)
	}

	client := &http.Client{Transport: s.transport()}
	// A fresh *http.Transport per Run and no IdleConnTimeout set on it means
	// an idle keep-alive connection this transport pools is never expired on
	// its own -- IdleConnTimeout's zero value is "no limit", not "the
	// default". Every tune builds a new one, so a clean upstream EOF (which
	// leaves the connection reusable, not closed) would leak one goroutine
	// and one open socket to the provider per completed tune, forever, with
	// nothing ever reusing the pool that held it. CloseIdleConnections is
	// this http.Client's own method and is a safe no-op if s.Transport was
	// overridden with a RoundTripper that does not implement it.
	defer client.CloseIdleConnections()
	response, err := client.Do(request)
	if err != nil {
		return fmt.Errorf("channel: connecting to the upstream: %w", redact.Error(err))
	}
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusOK {
		return &ErrUpstreamStatus{Status: response.StatusCode}
	}

	// The idle watchdog. requests' read timeout is the gap BETWEEN bytes, and
	// Go has no transport-level equivalent, so the deadline is enforced here:
	// a timer re-armed on every successful read, cancelling the request
	// context when it expires, which makes the in-flight Read return.
	var idled atomic.Bool
	watchdog := time.AfterFunc(s.readTimeout(), func() {
		idled.Store(true)
		cancel()
	})
	defer watchdog.Stop()

	buf := make([]byte, s.chunkSize())
	for {
		n, readErr := response.Body.Read(buf)
		if n > 0 {
			watchdog.Reset(s.readTimeout())
			if _, writeErr := sink.Write(buf[:n]); writeErr != nil {
				return fmt.Errorf("channel: writing upstream bytes to the buffer: %w", redact.Error(writeErr))
			}
		}
		if readErr == nil {
			continue
		}
		if errors.Is(readErr, io.EOF) {
			return nil
		}
		if parentErr := parent.Err(); parentErr != nil {
			return parentErr
		}
		if idled.Load() {
			return ErrUpstreamIdle
		}
		if ctxErr := ctx.Err(); ctxErr != nil {
			return ctxErr
		}
		return fmt.Errorf("channel: reading the upstream: %w", redact.Error(readErr))
	}
}
```

### Appendix O — the `channel` tests

**`relay/channel/streamtype_test.go`**

```go
package channel

import "testing"

// detect_stream_type's five answers, from its own branches
// (apps/proxy/live_proxy/utils.py:31-69), plus the one that reads the path
// and not the query.
func TestStreamTypeOfMatchesDetectStreamType(t *testing.T) {
	for url, want := range map[string]string{
		"":                                      "unknown",
		"udp://239.0.0.1:1234":                  "udp",
		"UDP://239.0.0.1:1234":                  "udp",
		"rtsp://cam.example/live":               "rtsp",
		"rtp://cam.example/live":                "rtsp",
		"http://p/live/u/p/1.m3u8":              "hls",
		"http://p/live/u/p/1.M3U8?token=x":      "hls",
		"http://p/playlist.m3u":                 "hls",
		"http://p/hls/manifest.m3u8":            "hls",
		"http://p/hls/master.m3u":               "hls",
		"http://p/x?redirect=master.m3u8":       "hls", // endswith('.m3u8') runs over the WHOLE url, query included (utils.py:55)
		"http://p/x?redirect=master.m3u8&a=1":   "ts",  // ...but the path-word patterns read the PATH alone (utils.py:61-66)
		"http://p/live/u/p/1.ts":                "ts",
		"http://p/live/u/p/1":                   "ts",
		"http://p/playlist":                     "ts", // "playlist" without .m3u is not HLS
		"http://p/live/manifest.mpd":            "ts", // DASH is not detected; Python answers ts
		"http://user:pw@p/live/u/p/stream.m3u8": "hls",
	} {
		if got := StreamTypeOf(url); got != want {
			t.Errorf("StreamTypeOf(%q) = %q, want %q", url, got, want)
		}
	}
	if NeedsFFmpeg("http://p/1.ts") || !NeedsFFmpeg("http://p/1.m3u8") || !NeedsFFmpeg("udp://x") || !NeedsFFmpeg("rtsp://x") {
		t.Fatal("NeedsFFmpeg does not follow input/manager.py:445's (HLS, RTSP, UDP) tuple")
	}
}
```

**`relay/channel/source_transcode_test.go`**

```go
package channel

import (
	"bytes"
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// TestStandIn is this package's trampoline (relaytest/standin.go).
func TestStandIn(_ *testing.T) {
	if os.Getenv(relaytest.StandInEnv) != "1" {
		return
	}
	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
}

// standInSource is a TranscodeSource that spawns the stand-in with args. The
// URL is a placeholder the UDP filter reads and nothing else does.
func standInSource(t *testing.T, args ...string) *TranscodeSource {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(args...)
	return &TranscodeSource{Command: command, Argv: argv, URL: "http://provider.invalid/live.ts", UserAgent: "test/1.0"}
}

// transcodeTuning is testTuning with the two thresholds a transcode channel
// reads. NOT the defaults (1.0, 15s): 10.0 is the API's maximum
// buffering_speed (core/serializers.py:96) and the slow-trickle corpus opens
// above it and stays below it from its second record, which is what lets a
// detector test arm in milliseconds rather than after the tens of seconds a
// real cumulative average takes (row 4).
func transcodeTuning(speed float64, timeout time.Duration) Tuning {
	tuning := testTuning()
	tuning.BufferingSpeed = speed
	tuning.BufferingTimeout = timeout
	return tuning
}

func assetFile(t *testing.T, packets int) (string, []byte) {
	t.Helper()
	payload := relaytest.SyntheticTS(packets, 0x100)
	path := filepath.Join(t.TempDir(), "asset.ts")
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	return path, payload
}

// captureLog is a slog handler that keeps every line, so a test can assert
// what did and did not reach the log.
type captureLog struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (c *captureLog) logger() *slog.Logger {
	return slog.New(slog.NewTextHandler(&lockedWriter{c: c}, &slog.HandlerOptions{Level: slog.LevelDebug}))
}

func (c *captureLog) String() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.buf.String()
}

type lockedWriter struct{ c *captureLog }

func (w *lockedWriter) Write(p []byte) (int, error) {
	w.c.mu.Lock()
	defer w.c.mu.Unlock()
	return w.c.buf.Write(p)
}

func attachTranscode(t *testing.T, m *Manager, id string, source *TranscodeSource, tuning Tuning) (*Channel, func()) {
	t.Helper()
	ch, release, err := m.Attach(id, testClient("a"), func() (Started, error) {
		return Started{Source: source, Tuning: tuning}, nil
	})
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	return ch, release
}

func waitFor(t *testing.T, what string, timeout time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out after %s waiting for %s", timeout, what)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

// THE TRANSCODE PATH END TO END AT THE CHANNEL: the child's fd 1 is the
// video, it reaches the ring as whole packets in order, and a child that ends
// cleanly stops the channel exactly as a clean Proxy EOF does.
func TestATranscodeProcessesFd1ReachesTheRingInOrder(t *testing.T) {
	path, payload := assetFile(t, 64)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	ch, release := attachTranscode(t, m, "transcode-1", standInSource(t, "-i", path), transcodeTuning(1.0, 15*time.Second))
	defer release()

	select {
	case <-ch.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("the channel did not finish after the child copied its asset and exited")
	}
	if state := ch.State(); state != StateStopped {
		t.Fatalf("state = %q after a clean child exit, want %q (err %v)", state, StateStopped, ch.Err())
	}
	chunks, _, _ := ch.Ring().Read(0)
	got := bytes.Join(chunks, nil)
	// testTuning's chunk is four packets, so the last partial chunk is
	// held back by the packetiser; everything published must be the
	// asset's own packets in order.
	if len(got) == 0 || len(got) > len(payload) {
		t.Fatalf("the ring holds %d bytes of a %d-byte asset", len(got), len(payload))
	}
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the ring's bytes are not whole packets: %s", problem)
	}
	for i := 0; i < len(got); i += buffer.TSPacketSize {
		if idx := relaytest.PacketIndex(got[i : i+buffer.TSPacketSize]); idx != i/buffer.TSPacketSize {
			t.Fatalf("packet at byte %d carries index %d, want %d", i, idx, i/buffer.TSPacketSize)
		}
	}
}

// The parsed preamble and the last progress record reach the channel's
// stats, rounded the way Python stores them. Expected values are read off
// the corpus (the shape CAPTURE.md guarantees), never typed as digits.
func TestParsedStderrReachesTheChannelsStats(t *testing.T) {
	path, _ := assetFile(t, 8)
	speeds := relaytest.CorpusSpeeds("normal")
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	// interval 0: the whole corpus is on stderr before the copy finishes,
	// so the last record is the one the channel holds when it stops.
	src := standInSource(t, "-i", path, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	ch, release := attachTranscode(t, m, "transcode-stats", src, transcodeTuning(0.1, 300*time.Second))
	defer release()
	<-ch.Done()

	stats := ch.Stats()
	want := map[string]struct{ got, want any }{
		"video_codec":    {deref(stats.VideoCodec), "h264"},
		"resolution":     {deref(stats.Resolution), "320x180"},
		"source_fps":     {deref(stats.SourceFPS), 25.0},
		"pixel_format":   {deref(stats.PixelFormat), "yuv420p"},
		"audio_codec":    {deref(stats.AudioCodec), "aac"},
		"sample_rate":    {deref(stats.SampleRate), 44100},
		"audio_channels": {deref(stats.AudioChannels), "mono"},
		"audio_bitrate":  {deref(stats.AudioBitrate), 66.0},
		"stream_type":    {deref(stats.StreamType), "mpegts"},
		"ffmpeg_speed":   {deref(stats.FFmpegSpeed), ffmpeg.Round(speeds[len(speeds)-1], 3)},
	}
	for name, tc := range want {
		if tc.got != tc.want {
			t.Errorf("%s = %v, want %v", name, tc.got, tc.want)
		}
	}
	if stats.FFmpegFPS == nil || stats.ActualFPS == nil || stats.FFmpegOutputBitrate == nil {
		t.Errorf("the progress record's fps, actual fps and bitrate did not all reach the stats: %+v", stats)
	}
	if stats.VideoBitrate != nil {
		t.Errorf("video_bitrate = %v: the corpus video line carries no kb/s, so Python never sets it", *stats.VideoBitrate)
	}
}

// Stream lines AFTER the "Output #0" line are the remux's own and must not
// overwrite the input's (input/manager.py:1041-1045, :1079-1082). Driven
// with a corpus whose output video line differs from its input one.
func TestOutputPhaseStreamLinesDoNotOverwriteTheInputs(t *testing.T) {
	corpus := filepath.Join(t.TempDir(), "phases.stderr")
	// Real ffmpeg 8.1.2 lines (the corpus preamble), with the OUTPUT video
	// line's resolution changed to something a remux could never produce
	// from this input, so an overwrite is unmistakable. A stderr line
	// edited for a test is the SYNTHETIC exception harness/ffmpeg_stderr.py
	// allows, and the reason is that a real ffmpeg cannot be made to print
	// an output resolution that differs from a copied input's.
	lines := []string{
		"Input #0, mpegts, from 'http://127.0.0.1:1/live.ts':",
		"  Stream #0:0[0x100]: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 320x180 [SAR 1:1 DAR 16:9], 25 fps, 25 tbr, 90k tbn, start 1.423222",
		"Output #0, mpegts, to 'pipe:1':",
		"  Stream #0:0: Video: h264 (Constrained Baseline) ([27][0][0][0] / 0x001B), yuv420p(progressive), 999x999 [SAR 1:1 DAR 16:9], q=2-31, 25 fps, 25 tbr, 90k tbn",
		"",
	}
	if err := os.WriteFile(corpus, []byte(strings.Join(lines, "\n")), 0o600); err != nil {
		t.Fatal(err)
	}
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--stderr-corpus", corpus, "--stderr-interval", "0")
	ch, release := attachTranscode(t, m, "transcode-phase", src, transcodeTuning(0.1, 300*time.Second))
	defer release()
	<-ch.Done()
	if got := deref(ch.Stats().Resolution); got != "320x180" {
		t.Fatalf("resolution = %v, want the INPUT's 320x180 -- the output phase's stream line overwrote it", got)
	}
}

// PARITY-MATRIX ROW 4's invariant on the stand-in path, sampled the way the
// Python pin samples it: the channel is never labelled buffering while the
// speed it reports is still at or above the threshold. The slow-trickle
// capture replayed at 20 ms a record, at the DEFAULT buffering_speed of 1.0
// (the corpus was captured against it), with a timeout nothing reaches.
//
// STATE IS READ BEFORE STATS, and the order is load-bearing: the reader
// writes the speed and THEN the state (stderrReader.progress), so a sample
// that reads the state as buffering is guaranteed a speed at least as new
// as the one that armed it. Read the other way round, a sample could pair
// the previous record's speed with the new state and fail for a reason
// that is not the mechanism.
func TestTheCapturedLeadIsNeverLabelledBufferingBeforeItCrosses(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("slow-trickle")
	const threshold = 1.0
	crossing := -1
	for idx, v := range speeds {
		if v < threshold {
			crossing = idx
			break
		}
	}
	if crossing <= 0 {
		t.Fatalf("slow-trickle does not open above %v and cross below it; re-derive (CAPTURE.md)", threshold)
	}
	for _, v := range speeds[crossing:] {
		if v >= threshold {
			t.Fatal("the capture climbs back above the threshold after crossing; the invariant below is no longer race-free -- re-derive (CAPTURE.md)")
		}
	}

	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02")
	ch, release := attachTranscode(t, m, "row4", src, transcodeTuning(threshold, 300*time.Second))
	defer release()

	type sample struct {
		state State
		speed *float64
	}
	var samples []sample
	waitFor(t, "the channel to reach buffering", 15*time.Second, func() bool {
		state := ch.State()
		samples = append(samples, sample{state, ch.Stats().FFmpegSpeed})
		return state == StateBuffering
	})
	lead := 0
	for _, s := range samples {
		if s.speed == nil {
			continue
		}
		if *s.speed >= threshold {
			lead++
			if s.state == StateBuffering {
				t.Fatalf("the channel was buffering while its reported speed was %vx", *s.speed)
			}
		}
	}
	if lead == 0 {
		t.Fatal("never observed the lead at all; poll faster or pace the corpus slower")
	}
	m.Stop("row4")
}

// A sustained sub-threshold speed past buffering_timeout ends the source
// with ErrBufferingTimeout and puts the channel in error -- 2c-4's stand-in
// for the failover 2c-5 wires here. The lever is buffering_speed at the API
// maximum, as parity-matrix row 1's Python pin uses it: the capture opens
// above 10 and every later record is below, so the detector arms on record
// two. The timeout is 1s and the tail is 75 records at 20 ms, 1.5s, which
// outlasts it; the assertion is that the error is the timeout's, not the
// SIGKILL's.
func TestASustainedSubThresholdSpeedEndsTheSourceWithATimeout(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("slow-trickle")
	const apiMax = 10.0 // core/serializers.py:96's max_value
	if speeds[0] <= apiMax {
		t.Fatal("slow-trickle no longer opens above the API's maximum buffering_speed; re-derive (CAPTURE.md)")
	}
	for _, v := range speeds[1:] {
		if v >= apiMax {
			t.Fatal("slow-trickle no longer stays below the API's maximum after its first record; re-derive")
		}
	}
	if tail := time.Duration(len(speeds)-1) * 20 * time.Millisecond; tail < 1400*time.Millisecond {
		t.Fatalf("the below-threshold tail is %s, too short to outlast the 1s timeout with margin; re-derive", tail)
	}

	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02", "--stderr-loop")
	ch, release := attachTranscode(t, m, "timeout", src, transcodeTuning(apiMax, time.Second))
	defer release()

	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	started := time.Now()
	select {
	case <-ch.Done():
	case <-time.After(15 * time.Second):
		t.Fatal("the source did not end after buffering past the timeout")
	}
	if elapsed := time.Since(started); elapsed < time.Second {
		t.Fatalf("the source ended %s after buffering began, before the 1s timeout could have elapsed", elapsed)
	}
	if !errors.Is(ch.Err(), ErrBufferingTimeout) {
		t.Fatalf("Err() = %v, want ErrBufferingTimeout", ch.Err())
	}
	if ch.State() != StateError {
		t.Fatalf("state = %q, want %q", ch.State(), StateError)
	}
}

// Recovery: a speed back at the threshold moves buffering to active, and
// only from buffering. Driven with the normal capture, whose records all sit
// between 0.1 and 10, first with the threshold above them (buffering from
// record one) and then a second source with the threshold below them.
func TestBufferingEndsWhenTheSpeedRecovers(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("normal")
	// A detector run entirely at the channel level: its Observe is unit
	// tested in package ffmpeg, so this asserts only the state edge.
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	// Threshold between the first record and the rest: buffering on record
	// two, and recovery never, because every later record is below it.
	// Then a second corpus pass with the threshold below everything.
	minimum, maximum := speeds[0], speeds[0]
	for _, v := range speeds {
		minimum = min(minimum, v)
		maximum = max(maximum, v)
	}
	corpus := filepath.Join(t.TempDir(), "recovery.stderr")
	// The capture's own records, then the capture's own FIRST record again:
	// a real line, re-ordered so the curve recovers. A synthetic ORDER, not
	// a synthetic line, which the corpus rule permits with a reason: real
	// ffmpeg's cumulative average never climbs back over a threshold it
	// has crossed, so no capture can show a recovery.
	_, records := relaytest.SplitCorpus(relaytest.Corpus("normal"))
	var body []byte
	for _, r := range records {
		body = append(body, r...)
		body = append(body, '\r')
	}
	body = append(body, records[0]...)
	body = append(body, '\r')
	if err := os.WriteFile(corpus, body, 0o600); err != nil {
		t.Fatal(err)
	}
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504", "--stderr-corpus", corpus, "--stderr-interval", "0.02")
	threshold := (minimum + maximum) / 2
	ch, release := attachTranscode(t, m, "recovery", src, transcodeTuning(threshold, 300*time.Second))
	defer release()
	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	waitFor(t, "recovery to active", 10*time.Second, func() bool { return ch.State() == StateActive })
	m.Stop("recovery")
}

// THE PROVIDER URL NEVER REACHES THE LOG, and the secret has exactly one
// source: the argv the stand-in echoes back on stderr, which is where a
// real ffmpeg's "Input #0, mpegts, from '<url>':" line puts it. The host is
// asserted PRESENT so the pass is redaction, not a log that dropped the
// line.
func TestAProviderURLInStderrNeverReachesTheLog(t *testing.T) {
	const secretURL = "http://provider.example:8080/live/subscriber/hunter2/9.ts?token=s3cr3t"
	path, _ := assetFile(t, 8)
	logs := &captureLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Log: logs.logger()})
	t.Cleanup(m.StopAll)

	src := standInSource(t, "-i", path, "--echo-argv", "-user_agent", "test/1.0", "-headers", "Referer: "+secretURL, "-x", secretURL)
	src.URL = secretURL
	ch, release := attachTranscode(t, m, "redact", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	<-ch.Done()

	got := logs.String()
	if !strings.Contains(got, "stand-in argv:") {
		t.Fatalf("the echoed argv line never reached the log, so nothing was redacted:\n%s", got)
	}
	for _, secret := range []string{"hunter2", "s3cr3t", "/live/subscriber", "token="} {
		if strings.Contains(got, secret) {
			t.Fatalf("the log carries %q from the provider URL:\n%s", secret, got)
		}
	}
	if !strings.Contains(got, "provider.example:8080") {
		t.Fatalf("the host was redacted too; an operator can no longer tell providers apart:\n%s", got)
	}
}

// A command that cannot be found ends the channel in error with a message
// that names the executable and nothing from argv.
func TestAMissingCommandFailsTheChannelWithoutEchoingArgv(t *testing.T) {
	logs := &captureLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Log: logs.logger()})
	t.Cleanup(m.StopAll)
	src := &TranscodeSource{Command: "relay-no-such-executable-2c4", Argv: []string{"-i", "http://p/live/u/hunter2/1.ts"}, URL: "http://p/live/u/hunter2/1.ts"}
	ch, release := attachTranscode(t, m, "missing", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	<-ch.Done()
	if ch.State() != StateError || ch.Err() == nil {
		t.Fatalf("state = %q, err = %v", ch.State(), ch.Err())
	}
	if strings.Contains(logs.String(), "hunter2") {
		t.Fatalf("the failure log echoes argv:\n%s", logs.String())
	}
	if !strings.Contains(ch.Err().Error(), "relay-no-such-executable-2c4") {
		t.Fatalf("the error lost the executable's name: %v", ch.Err())
	}
}

// The UDP filter, input/manager.py:808-812: on a udp:// upstream every
// argument carrying the user agent, or "user-agent"/"user_agent" in any
// case, is dropped; on any other upstream nothing is.
func TestTheUDPFilterDropsUserAgentArguments(t *testing.T) {
	argv := []string{"-user_agent", "VLC/3.0.20", "-headers", "User-Agent: VLC/3.0.20", "-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}
	udp := &TranscodeSource{Argv: argv, URL: "udp://239.0.0.1:1234", UserAgent: "VLC/3.0.20"}
	// "-headers" SURVIVES: the filter drops the arguments that carry the
	// user agent, not the flags that introduced them, so Python spawns a
	// dangling -headers whose value becomes the next argument (-i). A defect
	// of the Python relay's own, reproduced per D5 and recorded rather than
	// tidied; an earlier draft of this test expected the flag gone too.
	want := []string{"-headers", "-i", "udp://239.0.0.1:1234", "-c", "copy", "-f", "mpegts", "pipe:1"}
	if got := udp.argv(); strings.Join(got, " ") != strings.Join(want, " ") {
		t.Fatalf("UDP argv = %q, want %q", got, want)
	}
	http := &TranscodeSource{Argv: argv, URL: "http://p/1.ts", UserAgent: "VLC/3.0.20"}
	if got := http.argv(); strings.Join(got, " ") != strings.Join(argv, " ") {
		t.Fatalf("HTTP argv was filtered: %q", got)
	}
}

// The argv Django built is what the child receives, verbatim and in order:
// the stand-in echoes what it was given, and the log carries it. No URL in
// this argv, so nothing is redacted and the comparison is exact.
func TestTheBuiltArgvIsSpawnedVerbatim(t *testing.T) {
	path, _ := assetFile(t, 8)
	logs := &captureLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Log: logs.logger()})
	t.Cleanup(m.StopAll)
	extra := []string{"-user_agent", "VLC/3.0.20 LibVLC/3.0.20", "-c:v", "copy", "-metadata", "title=a b", "-f", "mpegts", "pipe:1"}
	args := append([]string{"-i", path, "--echo-argv"}, extra...)
	src := standInSource(t, args...)
	ch, release := attachTranscode(t, m, "argv", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	<-ch.Done()
	want := "stand-in argv: " + strings.Join(args, " ")
	if !strings.Contains(logs.String(), want) {
		t.Fatalf("the child did not receive the argv verbatim; want a log line carrying %q in:\n%s", want, logs.String())
	}
}

// A non-zero exit reaches the channel as an error carrying the child's own
// code (input/manager.py's returncode).
func TestANonZeroExitPutsTheChannelInError(t *testing.T) {
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	src := standInSource(t, "-i", path, "--exit-after-bytes", "752", "--exit-code", "3")
	ch, release := attachTranscode(t, m, "exit3", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	<-ch.Done()
	var exited *ffmpeg.ErrExited
	if !errors.As(ch.Err(), &exited) || exited.Code != 3 {
		t.Fatalf("Err() = %v, want ErrExited{Code: 3}", ch.Err())
	}
	if ch.State() != StateError {
		t.Fatalf("state = %q, want %q", ch.State(), StateError)
	}
}

// VLC's "unable to open the MRL" ends the source (input/manager.py:1059-1064
// closes the socket on it), and only when the command is literally vlc:
// the stand-in is reached through a symlink named vlc first on PATH, which
// is how ToolFor sees "vlc" and routes the line directly.
func TestAVLCInputFailureEndsTheSource(t *testing.T) {
	dir := t.TempDir()
	if err := os.Symlink(os.Args[0], filepath.Join(dir, "vlc")); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	corpus := filepath.Join(dir, "vlc.stderr")
	// VLC's own message (modules/... "unable to open the MRL"), the one
	// line log_parsers.py:170 matches. No VLC capture exists in the corpus;
	// this is the SYNTHETIC exception with its reason: it is a VLC line and
	// the corpus rule is about ffmpeg's.
	if err := os.WriteFile(corpus, []byte("[00007f] main input error: unable to open the MRL 'http://p/x'\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	t.Setenv(relaytest.StandInEnv, "1")
	_, argv := relaytest.StandInCommand("-i", path, "--dead-air-after-bytes", "1504", "--stderr-corpus", corpus, "--stderr-interval", "0")
	src := &TranscodeSource{Command: "vlc", Argv: argv, URL: "http://provider.invalid/live.ts", UserAgent: "x"}
	ch, release := attachTranscode(t, m, "vlc", src, transcodeTuning(1.0, 15*time.Second))
	defer release()
	select {
	case <-ch.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("the source did not end on VLC's input failure")
	}
	if !errors.Is(ch.Err(), ErrInputFailed) {
		t.Fatalf("Err() = %v, want ErrInputFailed", ch.Err())
	}
}

// Cancelling the channel (a stop) kills the child and reports the
// cancellation, not the SIGKILL's exit status.
func TestStoppingTheChannelKillsTheChild(t *testing.T) {
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504", "--ignore-sigterm")
	ch, release := attachTranscode(t, m, "stop", src, transcodeTuning(1.0, 15*time.Second))
	waitFor(t, "the first chunk", 10*time.Second, func() bool { return ch.Ring().Head() >= 1 })
	release()
	select {
	case <-ch.Done():
	case <-time.After(5 * time.Second):
		t.Fatal("the channel did not stop within five seconds: the child was not killed")
	}
	if ch.State() != StateStopped {
		t.Fatalf("state = %q after a stop, want %q (err %v)", ch.State(), StateStopped, ch.Err())
	}
}

func deref(v any) any {
	switch p := v.(type) {
	case *string:
		if p != nil {
			return *p
		}
	case *int:
		if p != nil {
			return *p
		}
	case *float64:
		if p != nil {
			return *p
		}
	}
	return nil
}

// Global Constraint 8's ratchet for the one default this source carries.
func TestTranscodeSourceDefaultsMatchPython(t *testing.T) {
	var s TranscodeSource
	if got := s.chunkSize(); got != 8192 {
		t.Errorf("chunkSize() = %d, want 8192 (apps/proxy/config.py:7's CHUNK_SIZE, input/manager.py:1843)", got)
	}
	if ffmpeg.KillWait != 500*time.Millisecond {
		t.Errorf("ffmpeg.KillWait = %s, want 500ms (input/manager.py:1746's wait(timeout=0.5))", ffmpeg.KillWait)
	}
}

var _ = context.Background
```

**`relay/channel/source_transcode_real_test.go`**

```go
package channel

import (
	"bytes"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The asset's duration, scripts/capture_ffmpeg_stderr.py:30's ASSET_SECONDS.
const realAssetSeconds = 8

// requireFFmpeg finds a real ffmpeg, and REFUSES TO SKIP UNDER CI: a skip
// there would turn parity-matrix row 4's only real-ffmpeg pin into a test
// that is green because it never ran, which is the "silence read as pass"
// hollow shape. go-tests.yml installs ffmpeg for exactly this test.
func requireFFmpeg(t *testing.T) string {
	t.Helper()
	path, err := exec.LookPath("ffmpeg")
	if err != nil {
		if os.Getenv("CI") != "" {
			t.Fatal("ffmpeg is not on PATH and CI is set: go-tests.yml must install it, because this is row 4's only real-ffmpeg pin")
		}
		t.Skip("ffmpeg is not on PATH; row 4's real-ffmpeg pin did NOT run on this host")
	}
	version, err := exec.CommandContext(t.Context(), path, "-version").Output() // #nosec G204 -- a LookPath result, "-version" only
	if err == nil {
		t.Logf("ffmpeg: %s", strings.SplitN(string(version), "\n", 2)[0])
	}
	return path
}

// buildRealAsset is scripts/capture_ffmpeg_stderr.py:40-52's asset, built
// the same way: eight seconds of lavfi test pattern and tone, H.264 and
// AAC in MPEG-TS, so a `-c copy` remux has real packets to copy.
func buildRealAsset(t *testing.T, ffmpegPath string) []byte {
	t.Helper()
	cmd := exec.CommandContext(t.Context(), ffmpegPath, // #nosec G204 -- a LookPath result and fixed arguments
		"-hide_banner", "-loglevel", "error", "-y",
		"-f", "lavfi", "-i", "testsrc=size=320x180:rate=25:duration=8",
		"-f", "lavfi", "-i", "sine=frequency=440:duration=8",
		"-c:v", "libx264", "-preset", "ultrafast", "-b:v", "400k", "-pix_fmt", "yuv420p",
		"-c:a", "aac", "-b:a", "64k", "-f", "mpegts", "pipe:1")
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	asset, err := cmd.Output()
	if err != nil {
		t.Fatalf("ffmpeg could not build the asset: %v: %s", err, stderr.String())
	}
	if len(asset) < 100*buffer.TSPacketSize {
		t.Fatalf("the asset is only %d bytes", len(asset))
	}
	return asset
}

// PARITY-MATRIX ROW 4, WITH A REAL FFMPEG: speed= is ffmpeg's cumulative
// average since process start, so against an upstream held to a quarter of
// real time the reported speed OPENS well above 1.0 -- the probe and the
// first burst count as media time earned in almost no wall time -- and only
// crosses below it once that lead has burned off, tens of seconds later.
// The Python pin replays a capture of that curve; this drives the curve.
//
// The command is the PRODUCTION one: core/migrations/0003's
// `-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1` with the URL
// substituted, exactly what Django's build_command produces for the locked
// ffmpeg profile, no -loglevel, so the parser sees the default verbosity.
//
// What is asserted is the SHAPE (CAPTURE.md's rule): the first reported
// speed is above the threshold; buffering is never reported while the
// speed is at or above it; and the arming takes at least ArmingFloor of
// wall clock. The floor's derivation: with a media lead L seconds and an
// upstream at rate r, the cumulative average crosses 1.0 at t = L/(1-r);
// measured on this host at r = 0.25, the crossing came 18.7s in (ffmpeg
// 9.0.1), and the capture the Python pin replays crossed at 18-20s (ffmpeg
// 8.1.2). Four seconds is a floor an instantaneous-rate detector could not
// reach -- it would arm on the first progress record, half a second in --
// and comfortably below every measurement. Widen the floor if a real
// ffmpeg ever arms slower; never lower it towards a measurement.
const armingFloor = 4 * time.Second

func TestTheCumulativeLeadMustBurnOffBeforeTheDetectorArms(t *testing.T) {
	if testing.Short() {
		t.Skip("real ffmpeg for ~20s; run without -short")
	}
	ffmpegPath := requireFFmpeg(t)
	asset := buildRealAsset(t, ffmpegPath)

	// A quarter of the asset's OWN byte rate, scripts/capture_ffmpeg_stderr
	// .py:34's slow-trickle setting, expressed in relaytest's units: Rate is
	// a multiple of NominalByteRate, not of this asset's rate.
	assetRate := float64(len(asset)) / realAssetSeconds
	up := relaytest.NewUpstream(relaytest.Config{Payload: asset, Rate: 0.25 * assetRate / relaytest.NominalByteRate})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.ChunkBytes * 16})
	t.Cleanup(m.StopAll)
	tuning := Tuning{ChunkBytes: buffer.ChunkBytes, Retention: time.Minute,
		BufferingSpeed: 1.0, BufferingTimeout: 300 * time.Second}
	src := &TranscodeSource{
		Command:   "ffmpeg", // the profile's command, so ToolFor routes to the ffmpeg parser
		Argv:      []string{"-i", up.URL(), "-c:v", "copy", "-c:a", "copy", "-f", "mpegts", "pipe:1"},
		URL:       up.URL(),
		UserAgent: "VLC/3.0.20 LibVLC/3.0.20",
	}
	ch, release := attachTranscode(t, m, "row4-real", src, tuning)
	defer release()

	type sample struct {
		at    time.Time
		state State
		speed *float64
	}
	var samples []sample
	var firstSpeedAt time.Time
	deadline := time.Now().Add(90 * time.Second)
	for {
		// State BEFORE stats, for the ordering reason the stand-in test
		// gives: the reader writes the speed and then the state.
		state := ch.State()
		speed := ch.Stats().FFmpegSpeed
		samples = append(samples, sample{time.Now(), state, speed})
		if speed != nil && firstSpeedAt.IsZero() {
			firstSpeedAt = time.Now()
		}
		if state == StateBuffering {
			break
		}
		if state == StateError || state == StateStopped {
			t.Fatalf("the channel ended (%s, %v) before the detector armed; ffmpeg's stderr is in the log above", state, ch.Err())
		}
		if time.Now().After(deadline) {
			t.Fatal("the detector never armed within ninety seconds against a quarter-speed upstream")
		}
		time.Sleep(100 * time.Millisecond)
	}
	armedAt := samples[len(samples)-1].at
	m.Stop("row4-real")

	var first *float64
	for _, s := range samples {
		if s.speed != nil {
			first = s.speed
			break
		}
	}
	if first == nil || *first <= tuning.BufferingSpeed {
		t.Fatalf("the first reported speed was %v; row 4 needs a lead ABOVE %v to burn off", deref(first), tuning.BufferingSpeed)
	}
	for _, s := range samples {
		if s.speed != nil && *s.speed >= tuning.BufferingSpeed && s.state == StateBuffering {
			t.Fatalf("buffering was reported while the speed was still %vx", *s.speed)
		}
	}
	if took := armedAt.Sub(firstSpeedAt); took < armingFloor {
		t.Fatalf("the detector armed %s after the first progress record, under the %s floor: either speed= "+
			"is no longer a cumulative average or the detector is not reading it", took, armingFloor)
	}
	t.Logf("first speed %vx; armed %s after the first record", *first, armedAt.Sub(firstSpeedAt).Round(100*time.Millisecond))
}
```

### Appendix P — `relay/httpapi/stream.go` and `channels.go` — whole files after 2c-4

**`relay/httpapi/stream.go`**

```go
package httpapi

import (
	"context"
	"crypto/rand"
	"errors"
	"fmt"
	"log/slog"
	"math/big"
	"net"
	"net/http"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// StreamDeps is everything the live TS handler needs.
type StreamDeps struct {
	// Secret is the deployment's Django SECRET_KEY, used to verify the
	// X-Dispatcharr-Authorized marker nginx sets.
	Secret string

	// Channels owns every running channel.
	Channels *channel.Manager

	// Control calls Django's /api/relay/... routes.
	Control *control.Client

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger

	// Now is the clock a client's ConnectedAt comes from. Nil means time.Now.
	Now func() time.Time
}

// The proxy_settings keys this PR reads. Named constants rather than literals
// at the call site, so a rename on the wire is one edit and a typo is a
// compile error rather than a runtime ErrSettingAbsent.
const (
	settingChunkBytes       = "BUFFER_CHUNK_SIZE"
	settingRetention        = "redis_chunk_ttl"
	settingJoinBehind       = "new_client_behind_seconds"
	settingReadSize         = "CHUNK_SIZE"
	settingShutdownDelay    = "channel_shutdown_delay"
	settingBufferingSpeed   = "buffering_speed"
	settingBufferingTimeout = "buffering_timeout"
	settingDefaultUserAgent = "DEFAULT_USER_AGENT"
)

// tuningFrom resolves the channel-start-time settings out of a next-source
// answer, and returns the upstream read size alongside them.
//
// Every key is required. Amendment A1.4 makes Django send EFFECTIVE settings,
// so an absent key means a control plane older than this relay, and falling
// back to a Go-side default would be exactly the second copy A1.4 removes.
func tuningFrom(s control.Settings) (channel.Tuning, int, error) {
	var t channel.Tuning
	var err error

	if t.ChunkBytes, err = s.Int(settingChunkBytes); err != nil {
		return t, 0, err
	}
	if t.Retention, err = s.Seconds(settingRetention); err != nil {
		return t, 0, err
	}
	if t.JoinBehind, err = s.Seconds(settingJoinBehind); err != nil {
		return t, 0, err
	}
	if t.ShutdownDelay, err = s.Seconds(settingShutdownDelay); err != nil {
		return t, 0, err
	}
	// The buffering thresholds, read on EVERY tune including a Proxy one
	// that will never consult them: a setting is read from the wire or the
	// tune fails (Global Constraint 13), and reading them only on the
	// transcode path would leave the per-key test green against a Proxy
	// rig while a transcode tune silently defaulted.
	if t.BufferingSpeed, err = s.Float(settingBufferingSpeed); err != nil {
		return t, 0, err
	}
	if t.BufferingTimeout, err = s.Seconds(settingBufferingTimeout); err != nil {
		return t, 0, err
	}
	readSize, err := s.Int(settingReadSize)
	if err != nil {
		return t, 0, err
	}
	return t, readSize, nil
}

// OutputFormatMPEGTS is the only output format this relay serves.
//
// The value channel_status.py:567 records when no format was chosen
// (`output_format or 'mpegts'`). fMP4 is 2c-6's.
const OutputFormatMPEGTS = "mpegts"

// tuneBudget bounds a DETACHED next-source call -- see startProxyTune.
//
// control.Client's own worst case: two attempts of (ConnectTimeout,
// ReadTimeout) plus the retry delay between them. `attempts` is unexported, so
// the 2 is written here; if control ever changes it this over- or undershoots,
// which costs a longer or shorter gate wait and never correctness, because each
// attempt is still bounded by the client's own http.Client.Timeout.
const tuneBudget = 2*(control.ConnectTimeout+control.ReadTimeout) + control.RetryDelay

// StreamHandler serves GET /proxy/ts/stream/{channelID}.
func StreamHandler(deps StreamDeps) http.HandlerFunc {
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}
	now := deps.Now
	if now == nil {
		now = time.Now
	}

	return func(w http.ResponseWriter, r *http.Request) {
		id, client, err := identify(r, deps.Secret, now)
		if err != nil {
			writeTuneFailure(w, log, id, err)
			return
		}
		if id == "" {
			http.Error(w, "no channel in the request", http.StatusBadRequest)
			return
		}

		ch, release, err := deps.Channels.Attach(id, client, func() (channel.Started, error) {
			return startTune(r.Context(), deps.Control, id)
		})
		if err != nil {
			writeTuneFailure(w, log, id, err)
			return
		}
		defer release()

		w.Header().Set("Content-Type", "video/mp2t")
		w.Header().Set("Cache-Control", "no-cache")
		w.WriteHeader(http.StatusOK)
		rc := http.NewResponseController(w)
		if err := rc.Flush(); err != nil {
			return
		}

		serveClient(r.Context(), w, rc, ch, client, log)
	}
}

// ErrUnsupportedOutput is returned when the authorize hop asked for an output
// format or an Output Profile this relay does not serve.
//
// Refused rather than served, for 2c-2's reason on stream_profile.kind: a
// relay that logged "fmp4" in its registry and then wrote MPEG-TS would be
// wrong in a way nothing on the wire says, and serving it under the label
// "mpegts" would be a lie in the payload /proxy/stats/ renders. 2c-6 brings
// fMP4 and 2c-7 the Output Profiles.
type ErrUnsupportedOutput struct {
	Format    string
	ProfileID string
}

func (e *ErrUnsupportedOutput) Error() string {
	if e.ProfileID != "" {
		return fmt.Sprintf("the Go relay serves no Output Profile yet, and this tune asked for %q", e.ProfileID)
	}
	return fmt.Sprintf("the Go relay serves only %q, not %q", OutputFormatMPEGTS, e.Format)
}

// identify resolves which channel this request is for and who is asking.
//
// The five X-Relay-* values are read ONLY when X-Dispatcharr-Authorized proves
// nginx put them there. Without that check any client could name any channel,
// any client id, any address and any user by hand and bypass whatever the
// authorize hop decided -- that marker is the entire reason
// apps/proxy/authorize.py can be the only place the decision is made. An
// untrusted request falls back to the path value and to values resolved here,
// which is the dev shape; 2c-8 brings POST /_dispatcharr/authorize-internal.
//
// One closure rather than five `if trusted` blocks: five is five chances to
// omit one, and the one omitted is the one that matters.
func identify(r *http.Request, secret string, now func() time.Time) (string, *channel.Client, error) {
	trusted := control.IsRelayTrusted(secret, r.Header.Get(control.HeaderAuthorized))

	header := func(name string) string {
		if !trusted {
			return ""
		}
		return r.Header.Get(name)
	}

	id := header("X-Relay-Channel")
	if id == "" {
		id = r.PathValue("channelID")
	}

	// Refused before anything is registered or attached, so a tune this relay
	// cannot serve never reaches the control plane.
	if profileID := header("X-Relay-Output"); profileID != "" {
		return id, nil, &ErrUnsupportedOutput{ProfileID: profileID}
	}
	if format := header("X-Relay-Output-Format"); format != "" && format != OutputFormatMPEGTS {
		return id, nil, &ErrUnsupportedOutput{Format: format}
	}

	clientID := header("X-Relay-Client")
	if clientID == "" {
		clientID = mintClientID(now())
	}

	ip := header("X-Relay-Client-IP")
	if ip == "" {
		ip = peerAddress(r)
	}

	// NOT trust-gated, deliberately: User-Agent is the client's own header on
	// every path, not an authorize-hop assertion. client_manager.py:236 reads
	// it straight off the request too, with the same "unknown" fallback.
	userAgent := r.Header.Get("User-Agent")
	if userAgent == "" {
		userAgent = "unknown"
	}

	userID := header("X-Relay-User")
	if userID == "" {
		// client_manager.py:241's fallback, on the wire as a STRING.
		userID = "0"
	}

	return id, &channel.Client{
		ID:           clientID,
		UserID:       userID,
		IPAddress:    ip,
		UserAgent:    userAgent,
		OutputFormat: OutputFormatMPEGTS,
		ConnectedAt:  now(),
	}, nil
}

// mintClientID is apps/proxy/authorize.py:145-147's mint_client_id, spelled the
// same way on the wire: client_<unix millis>_<four digits>.
//
// crypto/rand rather than math/rand: gosec reports G404 on math/rand, and the
// id is a handle an admin can stop a client by (DELETE
// /proxy/relay/channels/<id>/clients/<client_id>, 2c-8), so guessability is not
// nothing. Python's random.randint is what it is; matching the FORMAT is the
// parity requirement, matching the generator is not.
func mintClientID(at time.Time) string {
	n, err := rand.Int(rand.Reader, big.NewInt(9000))
	if err != nil {
		// crypto/rand.Reader does not fail on any platform this runs on; if it
		// somehow did, a tune must still get an id rather than a 500.
		n = big.NewInt(0)
	}
	return fmt.Sprintf("client_%d_%d", at.UnixMilli(), 1000+n.Int64())
}

// peerAddress is the untrusted-path client address: the socket's peer, which
// behind a proxy is the proxy. The trusted path carries the real one on
// X-Relay-Client-IP, resolved once by the hop with get_client_ip's
// trusted-proxy rules (parity-matrix row 17).
func peerAddress(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// ErrUnservedKind is returned when the channel's Stream Profile is one this
// relay does not serve yet: Redirect, until 2c-5. 2c-2's ErrNotProxyKind,
// renamed when the transcode kind started being served.
type ErrUnservedKind struct{ Kind string }

func (e *ErrUnservedKind) Error() string {
	return fmt.Sprintf("the Go relay does not serve the %q stream profile yet", e.Kind)
}

// ErrProfileArgvAbsent is returned when the stream profile object carries no
// argv key at all: a control plane older than 2c-4 (spec Amendment A4.1).
// Reported as a contract mismatch, the same class as an absent
// proxy_settings key, and never as a profile problem.
type ErrProfileArgvAbsent struct{ ProfileID int }

func (e *ErrProfileArgvAbsent) Error() string {
	return fmt.Sprintf("stream profile %d carries no argv: the control plane is older than this relay", e.ProfileID)
}

// ErrProfileUnbuildable is returned when Django could not build the
// profile's argv -- argv is null, because shlex refused the parameters
// (an unbalanced quote) -- or the profile has no command. Python fails at
// spawn time on the same profile (build_command raises inside
// _establish_transcode_connection, which returns False); this fails the
// tune before anything is spawned.
type ErrProfileUnbuildable struct{ ProfileID int }

func (e *ErrProfileUnbuildable) Error() string {
	return fmt.Sprintf("stream profile %d cannot be built into a command line", e.ProfileID)
}

// ErrNoFFmpegProfile is returned when a Proxy channel's URL needs ffmpeg
// (HLS, RTSP or UDP) and the answer carries no locked ffmpeg profile.
// Python falls back to the channel's own Proxy profile, whose
// build_command returns [], and spawns nothing (input/manager.py:790-795,
// then :836's posix_spawn of an empty command fails); the outcome is the
// same failed tune, reported here by name.
var ErrNoFFmpegProfile = errors.New("this channel's URL needs ffmpeg and the control plane has no locked ffmpeg profile")

// ErrNoSource is returned when next-source had no candidate.
var ErrNoSource = errors.New("the control plane has no source for this channel")

// startTune makes the one control-plane call a tune needs and builds the
// source from its answer: ProxySource for a Proxy profile, TranscodeSource
// for a transcode one, and TranscodeSource on the locked ffmpeg profile for
// a Proxy profile whose URL is HLS, RTSP or UDP (input/manager.py:445-453's
// force_ffmpeg, decided at connect time there and at tune time here, since
// the URL is known at both).
//
// IT DETACHES FROM THE CALLING CLIENT'S REQUEST CONTEXT, and that is a decision
// fan-out forces rather than a tidy-up. Manager.Attach runs start() behind a
// per-channel gate: the first client in makes the call and every later client
// for that channel waits on the gate. With the caller's own r.Context(), that
// first client closing its tab mid-call cancels next-source for ALL of them --
// they wake, find no channel, and each retries into the same failure. Harmless
// at one client, which is why 2c-2 could ship it; wrong the moment a second
// client can be waiting.
//
// PYTHON DETACHES TOO, by construction rather than by choice. Its tune calls
// generate_stream_url -> control_plane.next_source from inside the client's own
// request greenlet (views.py:340 and :390), and uWSGI does not cancel a
// greenlet when its client hangs up -- the greenlet runs to completion and only
// discovers the disconnect on a later write. So the channel starts, and the
// followers polling _channel_setup_needed attach to it. A Go relay that
// propagated cancellation would be strictly less available than the Python one
// it replaces. (2c-3's startProxyTune, renamed in 2c-4 when it grew the
// transcode branch; the detaching is unchanged.)
//
// context.WithoutCancel keeps any values on the request context while dropping
// its cancellation, and the timeout puts back a bound of the right shape: the
// control client's own worst case rather than the viewer's patience.
func startTune(parent context.Context, client *control.Client, id string) (channel.Started, error) {
	ctx, cancel := context.WithTimeout(context.WithoutCancel(parent), tuneBudget)
	defer cancel()

	answer, err := client.NextSource(ctx, id, control.NextSourceRequest{
		ExcludeStreamIDs: []int{},
		Reason:           "initial",
	})
	if err != nil {
		return channel.Started{}, err
	}
	if answer.Source == nil {
		return channel.Started{}, ErrNoSource
	}

	tuning, readSize, err := tuningFrom(answer.ProxySettings)
	if err != nil {
		return channel.Started{}, err
	}
	// The user agent the Python relay would use: the answer's, or
	// DEFAULT_USER_AGENT when blank (input/manager.py:73's
	// `user_agent or Config.DEFAULT_USER_AGENT`). Off the wire, never a Go
	// literal, and read unconditionally so the per-key test covers it.
	defaultUserAgent, err := answer.ProxySettings.String(settingDefaultUserAgent)
	if err != nil {
		return channel.Started{}, err
	}
	userAgent := answer.Source.UserAgent
	if userAgent == "" {
		userAgent = defaultUserAgent
	}

	// KIND, NEVER TRANSCODE. `transcode` is false for Proxy AND for Redirect
	// (apps/proxy/next_source.py:504), and both locked profiles carry an empty
	// command, so a relay that branched on `transcode` would treat a Redirect
	// channel as Proxy and stream a provider URL that should have been a 302 --
	// silently, and to the wrong architecture. `kind` is the field 2c-1 Task 0
	// added for exactly this.
	var source channel.Source
	switch kind := answer.Source.StreamProfile.Kind; {
	case kind == control.KindProxy && channel.NeedsFFmpeg(answer.Source.URL):
		// force_ffmpeg: the Proxy reader cannot follow a playlist or speak
		// RTSP, so the locked ffmpeg profile plays the URL instead.
		if answer.Source.FFmpegStreamProfile == nil {
			return channel.Started{}, ErrNoFFmpegProfile
		}
		source, err = transcodeSource(answer.Source.FFmpegStreamProfile, answer.Source.URL, userAgent, readSize)
	case kind == control.KindProxy:
		source = channel.ProxySource{
			URL:       answer.Source.URL,
			UserAgent: answer.Source.UserAgent,
			ChunkSize: readSize,
		}
	case kind == control.KindTranscode:
		source, err = transcodeSource(&answer.Source.StreamProfile, answer.Source.URL, userAgent, readSize)
	default:
		return channel.Started{}, &ErrUnservedKind{Kind: kind}
	}
	if err != nil {
		return channel.Started{}, err
	}

	return channel.Started{
		Source: source,
		Tuning: tuning,
		Info: channel.SourceInfo{
			URL:             answer.Source.URL,
			StreamProfileID: answer.Source.StreamProfile.ID,
			StreamID:        answer.Source.StreamID,
			StreamName:      answer.Source.StreamName,
			ChannelName:     answer.Source.ChannelName,
			M3UProfileID:    answer.Source.M3UProfileID,
			M3UProfileName:  answer.Source.M3UProfileName,
		},
	}, nil
}

// transcodeSource builds the transcode architecture's source from a profile
// object whose argv Django built. The three states of argv are the three
// outcomes: a list is spawned, null cannot be built, and an absent key is a
// control plane older than this relay (control.StreamProfileRef).
func transcodeSource(profile *control.StreamProfileRef, url, userAgent string, readSize int) (channel.Source, error) {
	if !profile.ArgvPresent {
		return nil, &ErrProfileArgvAbsent{ProfileID: profile.ID}
	}
	if profile.Argv == nil || profile.Command == "" {
		return nil, &ErrProfileUnbuildable{ProfileID: profile.ID}
	}
	return &channel.TranscodeSource{
		Command:   profile.Command,
		Argv:      profile.Argv,
		URL:       url,
		UserAgent: userAgent,
		ChunkSize: readSize,
	}, nil
}

// writeTuneFailure turns a tune error into a status. It never echoes the error
// text to the client: a control-plane message can name a variable, and a
// source URL carries provider credentials.
func writeTuneFailure(w http.ResponseWriter, log *slog.Logger, id string, err error) {
	var unserved *ErrUnservedKind
	var argvAbsent *ErrProfileArgvAbsent
	var unbuildable *ErrProfileUnbuildable
	var unsupported *ErrUnsupportedOutput
	var refused *control.Refused
	var unavailable *control.Unavailable
	var misconfigured *control.ErrNotConfigured
	var absent *control.ErrSettingAbsent

	switch {
	case errors.As(err, &unserved):
		log.Warn("refusing a tune for an unsupported stream profile", "channel", id, "kind", unserved.Kind)
		http.Error(w, "this stream profile is not served yet", http.StatusNotImplemented)
	case errors.As(err, &argvAbsent):
		// The same class as an absent proxy_settings key, and the same
		// status: the control plane predates this relay.
		log.Error("the control plane sent a stream profile with no argv", "channel", id, "profile", argvAbsent.ProfileID)
		http.Error(w, "control plane contract mismatch", http.StatusBadGateway)
	case errors.As(err, &unbuildable):
		log.Error("the stream profile cannot be built into a command line", "channel", id, "profile", unbuildable.ProfileID)
		http.Error(w, "stream profile cannot be built", http.StatusServiceUnavailable)
	case errors.Is(err, ErrNoFFmpegProfile):
		log.Error("the channel's URL needs ffmpeg and no locked ffmpeg profile is installed", "channel", id)
		http.Error(w, "no ffmpeg profile for this stream", http.StatusServiceUnavailable)
	case errors.As(err, &unsupported):
		log.Warn("refusing a tune for an unsupported output",
			"channel", id, "format", unsupported.Format, "output_profile", unsupported.ProfileID)
		http.Error(w, "this output is not served yet", http.StatusNotImplemented)
	case errors.Is(err, channel.ErrDuplicateClient):
		// views.py:748-753's 503: a client id already attached to this channel
		// is a client that never released, not a new viewer.
		log.Warn("refusing a duplicate client id", "channel", id)
		http.Error(w, "failed to register client", http.StatusServiceUnavailable)
	case errors.Is(err, ErrNoSource):
		log.Info("no source available", "channel", id)
		http.Error(w, "no source available", http.StatusServiceUnavailable)
	case errors.As(err, &absent):
		log.Error("the control plane sent incomplete proxy_settings", "channel", id, "key", absent.Key)
		http.Error(w, "control plane contract mismatch", http.StatusBadGateway)
	case errors.As(err, &misconfigured):
		// The variable name only, never the value: a control-plane URL can
		// carry userinfo.
		log.Error("the control-plane address is misconfigured", "variable", misconfigured.Variable)
		http.Error(w, "control plane misconfigured", http.StatusInternalServerError)
	case errors.As(err, &refused):
		log.Error("the control plane refused the tune", "channel", id, "status", refused.Status)
		http.Error(w, "control plane refused", http.StatusBadGateway)
	case errors.As(err, &unavailable):
		log.Error("the control plane is unreachable", "channel", id, "reason", unavailable.Reason)
		http.Error(w, "control plane unreachable", http.StatusBadGateway)
	default:
		log.Error("the tune failed", "channel", id, "error", redact.Error(err))
		http.Error(w, "tune failed", http.StatusInternalServerError)
	}
}

// serveClient is the client loop: position once, then read, write, wait.
//
// NO KEEPALIVE PACKETS AND NO CLIENT TIMEOUT, and both omissions are parity
// rather than scope-cutting. Python sends a keepalive only when
// _should_send_keepalive says so, and that requires the owner's
// stream_manager.healthy to be FALSE (output/ts/generator.py:546-551);
// _is_timeout likewise disconnects only when the same flag is false (:592).
// Nothing lowers that flag except the health monitor and the failover
// machinery, which are 2c-5's. The error packets at :209-250 are the other
// half of the same story: every one of them is inside
// _wait_for_initialization, the path a follower takes while another worker
// elects itself owner -- deleted outright by D2, not ported.
func serveClient(
	ctx context.Context,
	w http.ResponseWriter,
	rc *http.ResponseController,
	ch *channel.Channel,
	client *channel.Client,
	log *slog.Logger,
) {
	tuning := ch.Tuning()
	ring := ch.Ring()

	// Positioned ONCE, at setup, exactly as output/ts/generator.py:264-302
	// positions a client. A JoinBehind of zero means the live head, which is
	// what new_client_behind_seconds = 0 means there too.
	cursor := ring.Head()
	if tuning.JoinBehind > 0 {
		cursor = ring.Join(tuning.JoinBehind)
	}

	for {
		chunks, next, skipped := ring.Read(cursor)
		if skipped > 0 {
			// The jump find_oldest_available_chunk performs
			// (input/buffer.py:407-452): the client fell behind past
			// retention, so it resumes at the oldest resident chunk with a gap
			// in its stream. Logged, never a disconnect -- Python does not
			// disconnect such a client either.
			log.Warn("client fell behind the ring",
				"channel", ch.ID(), "client", client.ID,
				"skipped", skipped, "head", ring.Head())
		}
		if len(chunks) > 0 {
			cursor = next
			if !writeChunks(w, rc, chunks) {
				return
			}
			continue
		}

		err := ring.Wait(ctx, cursor)
		if err == nil {
			continue
		}
		if errors.Is(err, buffer.ErrClosed) {
			// One last read. The writer may have published between the Read
			// above and Close, and without this the tail of a stream that
			// ended cleanly is dropped.
			if final, _, _ := ring.Read(cursor); len(final) > 0 {
				writeChunks(w, rc, final)
			}
		}
		return
	}
}

// writeChunks writes and flushes, reporting whether the client is still there.
// A write error is an ordinary client disconnect and is not logged: one line
// per viewer leaving would bury everything else.
func writeChunks(w http.ResponseWriter, rc *http.ResponseController, chunks [][]byte) bool {
	for _, data := range chunks {
		// #nosec G705 -- this is the video path. gosec's taint analysis sees
		// bytes from an outbound HTTP response reaching w.Write and reports a
		// cross-site-scripting risk; the bytes are an MPEG-TS stream served as
		// video/mp2t, the response carries no HTML context, and copying
		// provider bytes to a viewer is the only thing this process exists to
		// do. Re-linted after adding this: no further rule fires on the line,
		// unlike the G304/G703 pair in 2c-1's secret reader.
		if _, err := w.Write(data); err != nil {
			return false
		}
	}
	return rc.Flush() == nil
}
```

**`relay/httpapi/channels.go`**

```go
package httpapi

import (
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"strconv"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
)

// DefaultClientLimit caps the clients list when ?clients=all is absent.
//
// apps/proxy/relay_views.py:57's DEFAULT_CLIENT_LIMIT: what the Stats page and
// /proxy/stats/ have always shown. client_count is NEVER capped
// (channel_status.py:461 is a SCARD), which is what makes ?clients=all
// necessary for relay_client.live_connections and merely cosmetic elsewhere.
const DefaultClientLimit = 10

// ControlDeps is what the internal control routes need.
type ControlDeps struct {
	Secret   string
	Channels *channel.Manager
	Log      *slog.Logger
	Now      func() time.Time
}

// clientPayload is one row of the `clients` list, field for field and IN
// DECLARATION ORDER with apps/proxy/relay_serializers.py's
// RelayChannelClientSerializer, because DRF renders in declaration order and
// so does encoding/json.
//
// PRESENCE IS PER FIELD and is the part that is easy to get wrong. DRF
// declares each of these required=False with NO default=, so
// Field.get_attribute raises SkipField for a key the source dict never set and
// the key vanishes from the JSON entirely rather than rendering as null. Which
// keys ChannelStatus.get_basic_channel_info sets unconditionally and which it
// sets inside an `if` is therefore the contract:
//
//	client_id          always            (:565)
//	user_agent         always, NULLABLE  (:566 -- hmget returns None)
//	output_format      always            (:567, `or 'mpegts'`)
//	output_profile_id  always, NULLABLE  (:579-582, set on BOTH branches)
//	ip_address         only if truthy    (:570-571)
//	connected_at       only if truthy    (:573-574)
//	user_id            only if truthy    (:576-577)
type clientPayload struct {
	ClientID        string  `json:"client_id"`
	UserAgent       *string `json:"user_agent"`
	OutputFormat    string  `json:"output_format"`
	OutputProfileID *int    `json:"output_profile_id"`
	IPAddress       string  `json:"ip_address,omitempty"`
	ConnectedAt     float64 `json:"connected_at,omitempty"`
	UserID          string  `json:"user_id,omitempty"`
}

// channelPayload is get_basic_channel_info, field for field and in
// RelayChannelSerializer's declaration order.
//
// Nine fields are set unconditionally there and are therefore always present
// here: channel_id, state, url, stream_profile, owner, buffer_index,
// client_count, uptime, started_at -- three of them nullable. The rest are
// conditional, hence the pointers and the omitempty.
//
// TWO OF THE CONDITIONAL FIELDS ARE STILL ABSENT after 2c-4, and each absence
// has a reason rather than a gap:
//
//	logo_id        NEVER EMITTED BY PYTHON EITHER. ChannelMetadataField.LOGO_ID
//	               is written only into the timeshift key family
//	               (apps/timeshift/views.py:2984), never into the live hash
//	               channel_status.py:486 reads, so the `if not raw: continue`
//	               always continues. Exact parity by doing nothing.
//	healthy        needs StreamManager.healthy, which is 2c-5's.
//
// The seven ffmpeg-derived fields -- video_codec, resolution, source_fps,
// ffmpeg_speed, audio_codec, audio_channels, stream_type -- arrive in 2c-4
// from channel.Stats, each present only when the transcode process reported
// it (channel_status.py:605-627 assigns each inside an `if`), and never on
// the Proxy architecture, which spawns nothing: parity-matrix row 29.
// source_fps is a FLOAT here and a STRING on the detail endpoint, row 14's
// asymmetry, which 2c-8 carries with that endpoint.
type channelPayload struct {
	ChannelID      string   `json:"channel_id"`
	State          *string  `json:"state"`
	URL            string   `json:"url"`
	StreamProfile  string   `json:"stream_profile"`
	Owner          *string  `json:"owner"`
	BufferIndex    uint64   `json:"buffer_index"`
	ClientCount    int      `json:"client_count"`
	Uptime         float64  `json:"uptime"`
	StartedAt      *float64 `json:"started_at"`
	ChannelName    string   `json:"channel_name,omitempty"`
	M3UProfileID   *int     `json:"m3u_profile_id,omitempty"`
	StreamID       *int     `json:"stream_id,omitempty"`
	StreamName     string   `json:"stream_name,omitempty"`
	TotalBytes     *uint64  `json:"total_bytes,omitempty"`
	AvgBitrateKbps *float64 `json:"avg_bitrate_kbps,omitempty"`
	AvgBitrate     string   `json:"avg_bitrate,omitempty"`
	VideoCodec     string   `json:"video_codec,omitempty"`
	Resolution     string   `json:"resolution,omitempty"`
	SourceFPS      *float64 `json:"source_fps,omitempty"`
	FFmpegSpeed    *float64 `json:"ffmpeg_speed,omitempty"`
	AudioCodec     string   `json:"audio_codec,omitempty"`
	AudioChannels  string   `json:"audio_channels,omitempty"`
	StreamType     string   `json:"stream_type,omitempty"`

	// Clients is ALWAYS PRESENT, never omitted: channel_status.py:587 assigns
	// it on every path, so an empty channel renders "clients": [] and not an
	// absent key. Never nil here for the same reason.
	Clients []clientPayload `json:"clients"`
}

type channelListPayload struct {
	Channels []channelPayload `json:"channels"`
	Count    int              `json:"count"`
}

// ChannelsHandler serves GET /proxy/relay/channels[?clients=all].
//
// The route relay_client.list_channels calls, and through it
// relay_client.live_connections -- which authorize_stream reaches on EVERY
// tune for a stream-limited user (spec D4). Those two read only channel_id and
// the clients list; /proxy/stats/ and the channel_stats WebSocket message read
// the rest.
func ChannelsHandler(deps ControlDeps) http.HandlerFunc {
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}
	now := deps.Now
	if now == nil {
		now = time.Now
	}

	return func(w http.ResponseWriter, r *http.Request) {
		limit := DefaultClientLimit
		if r.URL.Query().Get("clients") == "all" {
			limit = -1
		}

		channels := deps.Channels.Snapshot()
		payload := channelListPayload{
			Channels: make([]channelPayload, 0, len(channels)),
			Count:    len(channels),
		}
		for _, c := range channels {
			payload.Channels = append(payload.Channels, describeChannel(c, limit, now()))
		}

		body, err := json.Marshal(payload)
		if err != nil {
			// Unreachable: every field is a plain type. Answering 500 rather
			// than a half-written 200 if it ever happens.
			log.Error("encoding the channel list failed", "error", err) // credential-logging: ok - an encoding/json error over plain struct fields; the URL it could name is one this payload carries on purpose (Ruling R7 of the 2c-3 plan)
			http.Error(w, "internal error", http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(body)
	}
}

// describeChannel renders one channel the way get_basic_channel_info does.
func describeChannel(c *channel.Channel, limit int, at time.Time) channelPayload {
	state := string(c.State())
	// OWNER IS ALWAYS NULL, and that is spec D2 rather than a missing value.
	// The metadata hash's owner field is the elected worker id; with one
	// process and no election there is no worker to name, and
	// channel_status.py:474's own default for "nobody owns this" is None. No
	// consumer reads it: grepped across frontend/src (zero hits) and across
	// relay_client's two readers, which take channel_id and clients.
	// Note the ASYMMETRY parity-matrix row 14 pins -- the DETAIL endpoint
	// defaults owner to the literal string 'unknown' -- is 2c-8's to carry.
	var owner *string

	info := c.Source()
	head := c.Ring().Head()
	uptime := at.Sub(c.StartedAt()).Seconds()
	startedAt := float64(c.StartedAt().UnixNano()) / float64(time.Second)

	clients := c.ClientSnapshot()
	out := channelPayload{
		ChannelID:     c.ID(),
		State:         &state,
		URL:           info.URL,
		StreamProfile: strconv.Itoa(info.StreamProfileID),
		Owner:         owner,
		BufferIndex:   head,
		ClientCount:   len(clients),
		Uptime:        uptime,
		StartedAt:     &startedAt,
		ChannelName:   info.ChannelName,
		StreamName:    info.StreamName,
		Clients:       make([]clientPayload, 0, len(clients)),
	}
	if info.M3UProfileID != 0 {
		id := info.M3UProfileID
		out.M3UProfileID = &id
	}
	if info.StreamID != 0 {
		id := info.StreamID
		out.StreamID = &id
	}

	// total_bytes and the two bitrate fields, exactly as channel_status.py
	// :510-524 derives them: the byte counter first, then avg_bitrate_kbps
	// only when uptime is positive, then the display string in Mbps above
	// 1000 Kbps and Kbps at or below it, both to two decimal places.
	if total := c.Ring().TotalBytes(); total > 0 {
		out.TotalBytes = &total
		if uptime > 0 {
			kbps := float64(total) * 8 / uptime / 1000
			out.AvgBitrateKbps = &kbps
			if kbps > 1000 {
				out.AvgBitrate = fmt.Sprintf("%.2f Mbps", kbps/1000)
			} else {
				out.AvgBitrate = fmt.Sprintf("%.2f Kbps", kbps)
			}
		}
	}

	// The ffmpeg-derived fields, exactly the seven get_basic_channel_info
	// copies out of the hash (:605-627), each only when the reader set it.
	// A stream_type of "" (channel_service writes str(input_format), never
	// empty) and a codec of "" would be dropped by omitempty where Python's
	// `if video_codec:` drops them too.
	stats := c.Stats()
	if stats.VideoCodec != nil {
		out.VideoCodec = *stats.VideoCodec
	}
	if stats.Resolution != nil {
		out.Resolution = *stats.Resolution
	}
	out.SourceFPS = stats.SourceFPS
	out.FFmpegSpeed = stats.FFmpegSpeed
	if stats.AudioCodec != nil {
		out.AudioCodec = *stats.AudioCodec
	}
	if stats.AudioChannels != nil {
		out.AudioChannels = *stats.AudioChannels
	}
	if stats.StreamType != nil {
		out.StreamType = *stats.StreamType
	}

	for i, cl := range clients {
		if limit >= 0 && i >= limit {
			break
		}
		userAgent := cl.UserAgent
		row := clientPayload{
			ClientID:        cl.ID,
			UserAgent:       &userAgent,
			OutputFormat:    cl.OutputFormat,
			OutputProfileID: cl.OutputProfileID,
			IPAddress:       cl.IPAddress,
			ConnectedAt:     float64(cl.ConnectedAt.UnixNano()) / float64(time.Second),
			UserID:          cl.UserID,
		}
		out.Clients = append(out.Clients, row)
	}
	return out
}

// RequireInternal gates a handler on the two internal headers, the same pair
// apps/proxy/permissions.py's IsInternalRelay checks: the static
// X-Dispatcharr-Internal and the per-request X-Dispatcharr-Internal-Request,
// which binds method, FULL path (query string included), body and a
// 120-second window.
//
// Not IsAdmin and no principal: these hops must not need a resolved User.
// A refusal answers 403 with a fixed body and names nothing.
func RequireInternal(secret string, now func() time.Time, next http.HandlerFunc) http.HandlerFunc {
	if now == nil {
		now = time.Now
	}
	return func(w http.ResponseWriter, r *http.Request) {
		if !control.IsInternalPrincipal(secret, r.Header.Get(control.HeaderInternal)) {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		// The bound token signs r.URL.RequestURI(), which is Django's
		// get_full_path(): the escaped path plus the query string. This route
		// is reached WITH a query string (?clients=all) and without, and the
		// two sign differently -- the correction spec section The contract
		// records, and the reason it is not cosmetic.
		if !control.VerifyInternalRequest(
			secret, r.Header.Get(control.HeaderInternalRequest),
			r.Method, r.URL.RequestURI(), nil, now(),
		) {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		next(w, r)
	}
}
```

### Appendix Q — the `httpapi` tests — `transcode_test.go` in full; `golden_test.go` and `stream_test.go` as edited; the golden JSON

**`relay/httpapi/transcode_test.go`**

```go
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// TestStandIn is this package's trampoline (relaytest/standin.go).
func TestStandIn(_ *testing.T) {
	if os.Getenv(relaytest.StandInEnv) != "1" {
		return
	}
	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
}

// transcodeRig is fanRig with a TRANSCODE stream profile whose command is
// the stand-in, fetching the rig's own upstream: the fake Django answers
// kind "transcode" and a built argv, exactly as it would for the locked
// ffmpeg profile after Django's build_command substituted the URL.
func transcodeRig(t *testing.T, overrides map[string]any, standInArgs ...string) *rig {
	t.Helper()
	return transcodeRigWith(t, relaytest.ControlPlaneConfig{Kind: control.KindTranscode}, overrides, standInArgs...)
}

func transcodeRigWith(t *testing.T, cp relaytest.ControlPlaneConfig, overrides map[string]any, standInArgs ...string) *rig {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	// The upstream is started first so its URL can be put in the argv,
	// which is what Django does with {streamUrl}; fanRigWith starts its own
	// and this one is the same object because newRig only creates one when
	// cp.SourceURL is empty.
	upstream := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	t.Cleanup(upstream.Close)
	cp.SourceURL = upstream.URL()
	if cp.Kind == control.KindTranscode {
		cp.Command, cp.Argv = relaytest.StandInCommand(append([]string{"-i", upstream.URL()}, standInArgs...)...)
	}
	cp.Settings = rigSettings(overrides)
	r := newRig(t, cp, relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	// newRig started an upstream of its own that nothing will call; the
	// one the child fetches is the one the assertions count.
	r.Upstream = upstream
	return r
}

// waitForStats blocks until the channel has a reported ffmpeg speed: the
// stderr reader has parsed at least one progress record.
func waitForStats(t *testing.T, r *rig, id string) {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for {
		if ch := r.Manager.Get(id); ch != nil && ch.Stats().FFmpegSpeed != nil {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("channel %s never reported an ffmpeg speed within fifteen seconds", id)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

func listedChannel(t *testing.T, r *rig) map[string]any {
	t.Helper()
	status, body := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d", status)
	}
	var payload struct {
		Channels []map[string]any `json:"channels"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatalf("decoding the list body: %v", err)
	}
	if len(payload.Channels) != 1 {
		t.Fatalf("the relay listed %d channels, want 1", len(payload.Channels))
	}
	return payload.Channels[0]
}

// THE TRANSCODE ARCHITECTURE END TO END: the control plane names a transcode
// profile, the relay spawns its command with the built argv, the CHILD
// fetches the provider -- the relay itself never does -- and the client
// receives the child's fd 1 as whole, in-order TS packets.
func TestATranscodeTuneDeliversTheChildsOutput(t *testing.T) {
	r := transcodeRig(t, nil)
	response := r.tuneAs(t, "c-transcode", "client-a")
	defer func() { _ = response.Body.Close() }()
	if got := response.Header.Get("Content-Type"); got != "video/mp2t" {
		t.Fatalf("Content-Type = %q", got)
	}
	packetRun(t, "the client", response.Body, 400)
	if n := r.Upstream.Requests(); n != 1 {
		t.Fatalf("the provider saw %d requests, want exactly 1 -- from the child, not the relay", n)
	}
	seen := r.Control.Requests()
	if len(seen) != 1 || !strings.HasSuffix(seen[0].Path, "/c-transcode/next-source") {
		t.Fatalf("the control plane saw %d calls: %+v", len(seen), seen)
	}
}

// The seven ffmpeg-derived fields reach GET /proxy/relay/channels with the
// values the corpus carries, typed as RelayChannelSerializer declares them:
// source_fps and ffmpeg_speed as floats on this endpoint (row 14's list
// side), the rest as strings.
func TestTheListEndpointCarriesTheFfmpegDerivedFields(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("normal")
	r := transcodeRig(t, nil, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	response := r.tuneAs(t, "c-stats", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-stats", 1)
	waitForStats(t, r, "c-stats")
	// The whole capture is on stderr before the first byte reaches the
	// client (interval 0), so the last record is the one reported. Waited
	// for rather than assumed, because the reader and the copy loop are
	// two goroutines.
	deadline := time.Now().Add(5 * time.Second)
	for {
		speed := r.Manager.Get("c-stats").Stats().FFmpegSpeed
		if speed != nil && *speed == speeds[len(speeds)-1] {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("ffmpeg_speed settled at %v, want the capture's last record %v", speed, speeds[len(speeds)-1])
		}
		time.Sleep(20 * time.Millisecond)
	}

	ch := listedChannel(t, r)
	for key, want := range map[string]any{
		"video_codec":    "h264",
		"resolution":     "320x180",
		"source_fps":     25.0,
		"ffmpeg_speed":   speeds[len(speeds)-1],
		"audio_codec":    "aac",
		"audio_channels": "mono",
		"stream_type":    "mpegts",
	} {
		if got := ch[key]; got != want {
			t.Errorf("%s = %v (%T), want %v (%T)", key, got, got, want, want)
		}
	}
	if got := ch["state"]; got != string(channel.StateActive) {
		t.Errorf("state = %v, want active: the normal capture never dips below the default threshold", got)
	}
}

// PARITY-MATRIX ROW 29: the buffering detector is ffmpeg-exclusive. A Proxy
// channel with buffering_speed at the API's MAXIMUM -- a threshold no real
// stream reaches -- never reports a speed, never enters buffering, and its
// payload carries none of the seven ffmpeg-derived keys. Meaningful only now
// that both architectures exist: against 2c-3's Proxy-only relay it could
// not have failed.
func TestTheProxyProfileStreamsWithNoFfmpegAndNoStats(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, map[string]any{"buffering_speed": 10.0, "buffering_timeout": 1})
	response := r.tuneAs(t, "c-proxy", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 2000)
	waitForHead(t, r, "c-proxy", 3)

	ch := listedChannel(t, r)
	for _, key := range []string{"video_codec", "resolution", "source_fps", "ffmpeg_speed", "audio_codec", "audio_channels", "stream_type"} {
		if v, present := ch[key]; present {
			t.Errorf("a Proxy channel carries %s = %v; nothing on that path can set it", key, v)
		}
	}
	if got := ch["state"]; got != string(channel.StateActive) {
		t.Errorf("state = %v, want active -- the Proxy path must never enter buffering, whatever the threshold", got)
	}
}

// The three states of stream_profile.argv at the tune surface. A missing key
// is a contract mismatch (502) like a missing setting; null is a profile
// that cannot be built (503); and in both cases NOTHING is spawned, which
// the provider's request count proves.
func TestAnAbsentOrNullArgvFailsTheTuneBeforeAnythingIsSpawned(t *testing.T) {
	for _, tc := range []struct {
		name string
		cp   relaytest.ControlPlaneConfig
		want int
	}{
		{"absent: an older control plane", relaytest.ControlPlaneConfig{Kind: control.KindTranscode, ArgvAbsent: true}, http.StatusBadGateway},
		{"null: unparseable parameters", relaytest.ControlPlaneConfig{Kind: control.KindTranscode, ArgvNull: true}, http.StatusServiceUnavailable},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := transcodeRigWith(t, tc.cp, nil)
			response := r.tune(t, "/proxy/ts/stream/c-argv", nil)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != tc.want {
				t.Fatalf("answered %d, want %d", response.StatusCode, tc.want)
			}
			if n := r.Upstream.Requests(); n != 0 {
				t.Fatalf("the provider saw %d requests for a tune that could not be built", n)
			}
			body, _ := io.ReadAll(response.Body)
			if strings.Contains(string(body), "127.0.0.1") {
				t.Fatalf("the refusal body names the provider: %s", body)
			}
		})
	}
}

// force_ffmpeg (input/manager.py:445-453): a PROXY profile whose URL is HLS
// is played through the locked ffmpeg profile, not the raw reader. The
// discriminator is the stats: only the transcode path can produce an
// ffmpeg_speed, so its presence proves the child ran.
func TestAProxyProfileWithAnHLSURLIsPlayedThroughTheFFmpegProfile(t *testing.T) {
	t.Setenv(relaytest.StandInEnv, "1")
	upstream := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	t.Cleanup(upstream.Close)
	hlsURL := strings.TrimSuffix(upstream.URL(), ".ts") + ".m3u8"
	command, argv := relaytest.StandInCommand("-i", hlsURL, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	cp := relaytest.ControlPlaneConfig{
		Kind:          control.KindProxy,
		SourceURL:     hlsURL,
		FFmpegProfile: &relaytest.ProfileConfig{ID: 9, Command: command, Argv: argv},
		Settings:      rigSettings(nil),
	}
	r := newRig(t, cp, relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	r.Upstream = upstream

	response := r.tuneAs(t, "c-hls", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 200)
	waitForStats(t, r, "c-hls")
	if n := upstream.Requests(); n != 1 {
		t.Fatalf("the provider saw %d requests, want 1 -- from the ffmpeg profile's child", n)
	}
	if _, present := listedChannel(t, r)["ffmpeg_speed"]; !present {
		t.Fatal("no ffmpeg_speed on the payload: the HLS URL was served by the raw reader, not by the ffmpeg profile")
	}
}

// ...and with NO locked ffmpeg profile installed, the same tune is refused
// 503 rather than handed to a reader that cannot follow a playlist.
func TestAProxyProfileWithAnHLSURLAndNoFFmpegProfileIsRefused(t *testing.T) {
	upstream := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(64, 0x100)})
	t.Cleanup(upstream.Close)
	cp := relaytest.ControlPlaneConfig{Kind: control.KindProxy, SourceURL: strings.TrimSuffix(upstream.URL(), ".ts") + ".m3u8", Settings: rigSettings(nil)}
	r := newRig(t, cp, relaytest.Config{})
	response := r.tune(t, "/proxy/ts/stream/c-hls-none", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("answered %d, want 503", response.StatusCode)
	}
	if n := upstream.Requests(); n != 0 {
		t.Fatalf("the provider saw %d requests: the raw reader was pointed at a playlist", n)
	}
}

// PARITY-MATRIX ROW 5: the thresholds are snapshotted at channel start. A
// proxy_settings change while a channel runs does not reach it, and the
// second channel is what makes this falsifiable: built AFTER the change from
// the same capture and the same stand-in, it buffers at once, so the only
// difference between the two channels is when their tuning was taken.
//
// buffering_speed 0.1 is the API's MINIMUM (core/serializers.py:96) and the
// normal capture never dips to it, so channel A must never buffer; 10.0 is
// the maximum and every record after the first is below it, so channel B
// must.
func TestABufferingThresholdChangeDoesNotReachARunningChannel(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("normal")
	for i, v := range speeds {
		if v <= 0.1 || (i > 0 && v >= 10.0) {
			t.Fatalf("the normal capture no longer sits between the API's minimum and maximum thresholds after its first record; re-derive (CAPTURE.md)")
		}
	}
	r := transcodeRig(t, map[string]any{"buffering_speed": 0.1, "buffering_timeout": 300},
		"--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0.02", "--stderr-loop")

	running := r.tuneAs(t, "c-before", "client-a")
	defer func() { _ = running.Body.Close() }()
	waitForStats(t, r, "c-before")

	// The operator's save, as the control plane would report it from now
	// on: every LATER next-source answer carries the new threshold.
	r.Control.SetSettings(rigSettings(map[string]any{"buffering_speed": 10.0, "buffering_timeout": 300}))

	// The running channel keeps parsing records (the speed keeps changing)
	// and never buffers.
	seen := map[float64]bool{}
	deadline := time.Now().Add(1500 * time.Millisecond)
	for time.Now().Before(deadline) {
		ch := r.Manager.Get("c-before")
		if state := ch.State(); state == channel.StateBuffering {
			t.Fatal("the running channel picked up the new threshold")
		}
		if speed := ch.Stats().FFmpegSpeed; speed != nil {
			seen[*speed] = true
		}
		time.Sleep(20 * time.Millisecond)
	}
	if len(seen) < 4 {
		t.Fatalf("too few distinct speeds after the change to prove records were still being parsed: %v", seen)
	}

	// Same capture, same stand-in, new channel: it snapshots the NEW
	// threshold and buffers at once.
	after := r.tuneAs(t, "c-after", "client-b")
	defer func() { _ = after.Body.Close() }()
	deadline = time.Now().Add(10 * time.Second)
	for r.Manager.Get("c-after") == nil || r.Manager.Get("c-after").State() != channel.StateBuffering {
		if time.Now().After(deadline) {
			t.Fatal("the channel started after the change never buffered: the new threshold was not snapshotted either")
		}
		time.Sleep(20 * time.Millisecond)
	}
}

// A blank user_agent on the answer falls back to the wire's
// DEFAULT_USER_AGENT for the argv filter, as input/manager.py:73 does for
// the whole StreamManager. Asserted on the source startTune builds, against
// the fixture's own literal, because nothing about a blank agent is visible
// from outside on a non-UDP tune.
func TestABlankUserAgentFallsBackToTheWireDefault(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{
		Kind: control.KindTranscode, SourceURL: "udp://239.0.0.1:1234", BlankUserAgent: true,
		Command: "ffmpeg", Argv: []string{"-i", "udp://239.0.0.1:1234"}, Settings: rigSettings(nil),
	})
	t.Cleanup(cp.Close)
	started, err := startTune(context.Background(), &control.Client{Secret: testSecret, BaseURL: cp.URL(), HTTP: control.NewHTTPClient()}, "c-ua")
	if err != nil {
		t.Fatalf("startTune: %v", err)
	}
	source, ok := started.Source.(*channel.TranscodeSource)
	if !ok {
		t.Fatalf("the source is a %T, want *channel.TranscodeSource", started.Source)
	}
	if source.UserAgent != "VLC/3.0.20 LibVLC/3.0.20" {
		t.Fatalf("UserAgent = %q, want the wire's DEFAULT_USER_AGENT", source.UserAgent)
	}
	if source.Command != "ffmpeg" || len(source.Argv) != 2 {
		t.Fatalf("the source was built from the wrong profile: %+v", source)
	}
}

// A transcode child that exits non-zero ends the client's response and puts
// the channel in error carrying the child's code, which is what 2c-5's
// connection-failure accounting (row 3) will read.
func TestAChildThatExitsNonZeroEndsTheTune(t *testing.T) {
	r := transcodeRig(t, nil, "--exit-after-bytes", "376000", "--exit-code", "2")
	response := r.tuneAs(t, "c-exit", "client-a")
	defer func() { _ = response.Body.Close() }()
	// Taken WHILE the client is attached: once the response ends the
	// client's release drops the channel from the manager, and a Get
	// afterwards finds nothing -- which is correct, and not what this
	// test is about.
	waitForHead(t, r, "c-exit", 1)
	ch := r.Manager.Get("c-exit")
	done := make(chan []byte, 1)
	go func() {
		body, _ := io.ReadAll(response.Body)
		done <- body
	}()
	select {
	case body := <-done:
		if len(body) == 0 {
			t.Fatal("the client received nothing")
		}
	case <-time.After(15 * time.Second):
		t.Fatal("the response never ended after the child exited")
	}
	<-ch.Done()
	var exited interface{ Error() string }
	if !errors.As(ch.Err(), &exited) || !strings.Contains(ch.Err().Error(), "status 2") {
		t.Fatalf("Err() = %v, want the child's exit status 2", ch.Err())
	}
}

var _ = buffer.TSPacketSize
```

**`relay/httpapi/golden_test.go`**

```go
package httpapi

import (
	"encoding/json"
	"net/http"
	"os"
	"reflect"
	"sort"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// goldenPath holds a payload rendered by DJANGO'S OWN SERIALIZER --
// apps/proxy/relay_serializers.py's RelayChannelListSerializer -- from the
// fixture apps/proxy/tests/test_relay_list_payload_golden.py builds. It is the
// oracle for this endpoint's absent-versus-null-versus-present behaviour, and
// it is produced by the OTHER implementation, which is the only thing that
// makes it able to fail (hollow shape 1: an expected value the code under test
// computes cannot fail).
//
// Regenerate it with the command in this PR's Task, never by running the Go.
const goldenPath = "testdata/channels_clients_all.json"

// goldenPayload is the Go value the golden file must describe: two channels,
// one with every conditional field set and two clients, one with none and no
// clients at all. Every present/absent/null case this endpoint can produce is
// in here, which is what makes the comparison a check on the SHAPE rather than
// on one happy path.
func goldenPayload() channelListPayload {
	state := "active"
	stopped := "stopped"
	var noOwner *string
	streamID := 41
	m3uProfileID := 3
	total := uint64(9_999_888)
	kbps := 2_665.3034666666666
	startedA := 1_789_000_000.5
	startedB := 1_789_000_100.0
	uaA := "VLC/3.0.20"
	var uaAbsent *string
	profileID := 7
	sourceFPS := 25.0
	speed := 1.02

	return channelListPayload{
		Count: 2,
		Channels: []channelPayload{
			{
				ChannelID:      "11111111-1111-4111-8111-111111111111",
				State:          &state,
				URL:            "http://provider.invalid/live/sub/pw/41.ts",
				StreamProfile:  "1",
				Owner:          noOwner,
				BufferIndex:    120,
				ClientCount:    2,
				Uptime:         30.0,
				StartedAt:      &startedA,
				ChannelName:    "BBC One HD",
				M3UProfileID:   &m3uProfileID,
				StreamID:       &streamID,
				StreamName:     "BBC One HD (UK)",
				TotalBytes:     &total,
				AvgBitrateKbps: &kbps,
				AvgBitrate:     "2.67 Mbps",
				VideoCodec:     "h264",
				Resolution:     "1920x1080",
				SourceFPS:      &sourceFPS,
				FFmpegSpeed:    &speed,
				AudioCodec:     "aac",
				AudioChannels:  "stereo",
				StreamType:     "mpegts",
				Clients: []clientPayload{
					{
						ClientID:        "client_1789000000000_1234",
						UserAgent:       &uaA,
						OutputFormat:    "mpegts",
						OutputProfileID: &profileID,
						IPAddress:       "198.51.100.4",
						ConnectedAt:     1_789_000_001.25,
						UserID:          "7",
					},
					{
						ClientID:        "client_1789000000000_5678",
						UserAgent:       uaAbsent,
						OutputFormat:    "mpegts",
						OutputProfileID: nil,
					},
				},
			},
			{
				ChannelID:     "22222222-2222-4222-8222-222222222222",
				State:         &stopped,
				URL:           "",
				StreamProfile: "0",
				Owner:         noOwner,
				BufferIndex:   0,
				ClientCount:   0,
				Uptime:        0,
				StartedAt:     &startedB,
				Clients:       []clientPayload{},
			},
		},
	}
}

// THE CROSS-IMPLEMENTATION PIN. Decoded rather than byte-compared, and that is
// a decision with one known consequence: DRF renders a Python float as "5.0"
// where encoding/json renders float64(5) as "5". Decoding both sides into
// map[string]any makes each a float64 and the spellings equal, which is right,
// because every consumer parses -- relay_client._request calls .json() and
// api.js parses -- and none compares bytes. What the decode does NOT lose is
// the part that matters: an absent key stays absent, a null stays nil, and a
// string stays a string, so the presence contract is still fully pinned.
func TestTheListPayloadMatchesDjangosSerializer(t *testing.T) {
	want := decodeGolden(t)

	encoded, err := json.Marshal(goldenPayload())
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var got any
	if err := json.Unmarshal(encoded, &got); err != nil {
		t.Fatalf("decoding this relay's own payload: %v", err)
	}

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("this relay's list payload differs from the one Django's "+
			"RelayChannelListSerializer renders from the same fixture.\n got: %s\nwant: %s",
			encoded, mustMarshal(t, want))
	}
}

// The presence contract, named field by field, so a failure says WHICH key
// moved rather than printing two blobs. A struct tag losing its omitempty, or
// gaining one it must not have, is exactly the edit this catches and the
// DeepEqual above reports only as "they differ".
func TestEveryOptionalFieldIsAbsentRatherThanNull(t *testing.T) {
	encoded, err := json.Marshal(goldenPayload())
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var payload struct {
		Channels []map[string]any `json:"channels"`
	}
	if err := json.Unmarshal(encoded, &payload); err != nil {
		t.Fatalf("decoding: %v", err)
	}

	// The nine get_basic_channel_info sets unconditionally, three of them
	// nullable (channel_status.py:469-479).
	always := []string{
		"channel_id", "state", "url", "stream_profile", "owner",
		"buffer_index", "client_count", "uptime", "started_at", "clients",
	}
	for i, ch := range payload.Channels {
		for _, key := range always {
			if _, present := ch[key]; !present {
				t.Errorf("channel %d has no %q: get_basic_channel_info sets it on every path, "+
					"so it must never be omitted", i, key)
			}
		}
		if ch["owner"] != nil {
			t.Errorf("channel %d reports owner %v, want null: spec D2 deletes the ownership "+
				"election, so there is no worker to name", i, ch["owner"])
		}
	}

	// The minimal channel carries none of the conditional keys.
	minimal := payload.Channels[1]
	for _, key := range []string{
		"channel_name", "logo_id", "m3u_profile_id", "stream_id", "stream_name",
		"total_bytes", "avg_bitrate_kbps", "avg_bitrate", "healthy",
		"video_codec", "resolution", "source_fps", "ffmpeg_speed",
		"audio_codec", "audio_channels", "stream_type",
	} {
		if _, present := minimal[key]; present {
			t.Errorf("a channel with no %s still carries the key, as %v: DRF declares it "+
				"required=False with no default, so an unset key VANISHES rather than "+
				"rendering as null", key, minimal[key])
		}
	}

	// The clientless channel still carries an EMPTY LIST, never an absent key
	// and never null (channel_status.py:587 assigns it on every path).
	clients, present := minimal["clients"].([]any)
	if !present || clients == nil {
		t.Fatalf("a channel with no clients rendered clients as %v, want []", minimal["clients"])
	}
	if len(clients) != 0 {
		t.Fatalf("the clientless channel lists %d clients", len(clients))
	}

	// Per-client presence: four keys always, three only when truthy.
	rows, _ := payload.Channels[0]["clients"].([]any)
	if len(rows) != 2 {
		t.Fatalf("the populated channel lists %d clients, want 2", len(rows))
	}
	full, _ := rows[0].(map[string]any)
	bare, _ := rows[1].(map[string]any)
	for _, key := range []string{"client_id", "user_agent", "output_format", "output_profile_id"} {
		if _, present := bare[key]; !present {
			t.Errorf("a client with nothing optional set has no %q: it is assigned on every "+
				"path in channel_status.py and must always be present", key)
		}
	}
	for _, key := range []string{"ip_address", "connected_at", "user_id"} {
		if _, present := bare[key]; present {
			t.Errorf("a client with no %s still carries the key, as %v: it is set inside an "+
				"`if` and must vanish when unset", key, bare[key])
		}
		if _, present := full[key]; !present {
			t.Errorf("a fully populated client has no %q", key)
		}
	}
	if bare["user_agent"] != nil {
		t.Errorf("a client whose hash carried no user_agent reports %v, want null: hmget "+
			"returns None and the field is allow_null", bare["user_agent"])
	}
	if bare["output_profile_id"] != nil {
		t.Errorf("a client with no Output Profile reports %v, want null", bare["output_profile_id"])
	}
	if _, isString := full["user_id"].(string); !isString {
		t.Errorf("user_id rendered as %T, want a string: RelayChannelClientSerializer declares "+
			"CharField and relay_client.live_connections int()s it itself", full["user_id"])
	}
}

// The handler's live output has the same key set as the golden's populated
// channel. Without this, the two tests above pin a struct literal and nothing
// pins that the handler builds it.
func TestTheLiveEndpointProducesTheGoldensKeySet(t *testing.T) {
	// A TRANSCODE tune, so the seven ffmpeg-derived keys the golden's
	// populated channel carries are produced by a real stderr reader
	// parsing a real capture -- a Proxy tune would render a payload seven
	// keys short and this test would report the golden as wrong.
	r := transcodeRig(t, nil, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	response := r.tuneAs(t, "c-keys", "client-a")
	defer func() { _ = response.Body.Close() }()

	// The channel must have published at least one chunk, so total_bytes and
	// the two bitrate fields are present, and the reader must have seen the
	// whole capture, so ffmpeg_speed is -- together they are exactly the
	// conditional fields the golden's populated channel carries.
	waitForHead(t, r, "c-keys", 1)
	waitForStats(t, r, "c-keys")

	status, body := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d, want 200", status)
	}
	var live struct {
		Channels []map[string]any `json:"channels"`
	}
	if err := json.Unmarshal(body, &live); err != nil {
		t.Fatalf("decoding the live body: %v", err)
	}
	if len(live.Channels) != 1 {
		t.Fatalf("the relay listed %d channels, want 1", len(live.Channels))
	}

	encoded, _ := json.Marshal(goldenPayload())
	var golden struct {
		Channels []map[string]any `json:"channels"`
	}
	_ = json.Unmarshal(encoded, &golden)

	if got, want := keysOf(live.Channels[0]), keysOf(golden.Channels[0]); !reflect.DeepEqual(got, want) {
		t.Fatalf("the live payload's keys are\n  %v\nand the golden's populated channel's are\n  %v\n"+
			"-- the handler and the shape this endpoint promises have diverged", got, want)
	}
	// Asserted on the LIVE payload, not on goldenPayload(): the struct literal
	// hard-codes a nil owner, so an assertion there cannot see a handler that
	// started naming one. The break-check that put a process identity in
	// describeChannel left this test green until this line went in.
	if live.Channels[0]["owner"] != nil {
		t.Fatalf("the handler reported owner %v, want null -- spec D2 deletes the ownership "+
			"election, so there is no worker to name", live.Channels[0]["owner"])
	}

	liveClients, _ := live.Channels[0]["clients"].([]any)
	if len(liveClients) != 1 {
		t.Fatalf("the live payload lists %d clients, want 1", len(liveClients))
	}
	goldenClients, _ := golden.Channels[0]["clients"].([]any)
	liveRow, _ := liveClients[0].(map[string]any)
	goldenRow, _ := goldenClients[0].(map[string]any)
	if got, want := keysOf(liveRow), keysOf(goldenRow); !reflect.DeepEqual(got, want) {
		t.Fatalf("the live client row's keys are\n  %v\nand the golden's are\n  %v", got, want)
	}
}

func keysOf(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func decodeGolden(t *testing.T) any {
	t.Helper()
	raw, err := os.ReadFile(goldenPath)
	if err != nil {
		t.Fatalf("reading %s: %v -- regenerate it with this PR's Python command", goldenPath, err)
	}
	var want any
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatalf("decoding %s: %v", goldenPath, err)
	}
	return want
}

func mustMarshal(t *testing.T, v any) string {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshalling: %v", err)
	}
	return string(raw)
}
```

**`relay/httpapi/stream_test.go`**

```go
package httpapi

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

const testSecret = "phase2c1-test-secret"

// The chunk size the rig's fake control plane sends, and the unit every read
// length below is expressed in.
//
// DELIBERATELY NOT buffer.ChunkBytes. A rig that sent the default would be a
// pin that supplies the default (hollow shape 2), and it would disarm this
// whole end-to-end layer against the one property Amendment A1.4 exists to
// prove: with the wire value equal to the constant, a relay that ignored
// BUFFER_CHUNK_SIZE entirely would behave identically and every test here
// would stay green. Measured: with the default, forcing New to ignore
// cfg.ChunkBytes reddens 0 of these tests; with 700 packets it reddens them.
//
// 700 packets rather than a round number of bytes, so the chunk stays a whole
// number of TS packets as the real one is.
const rigChunkBytes = buffer.TSPacketSize * 700

// Enough ring for sixty-four of those, so a test can read several chunks
// without the writer evicting the head of what it is about to read. The
// earlier 188*4000 budget gave a capacity of TWO at the default chunk size,
// against a test that read exactly two -- no margin at all.
const rigBudgetBytes = rigChunkBytes * 64

// rig is a whole relay in front of a whole fake deployment: a fake Django, a
// fake provider, and this process's own mux served over a real socket.
//
// A REAL SERVER, not httptest.NewRecorder: the subject is a long-lived
// streaming response, and a recorder buffers the whole body and returns only
// once the handler has finished. Every assertion about a client reading while
// the upstream still runs needs a real connection.
type rig struct {
	Relay    *httptest.Server
	Upstream *relaytest.Upstream
	Control  *relaytest.ControlPlane
	Manager  *channel.Manager
}

func newRig(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config) *rig {
	t.Helper()

	upstream := relaytest.NewUpstream(up)
	t.Cleanup(upstream.Close)

	if cp.SourceURL == "" {
		cp.SourceURL = upstream.URL()
	}
	if cp.Settings == nil {
		// Only when the caller has not supplied its own: the per-key required
		// test deletes a key from the full set and must keep that set.
		settings := relaytest.EffectiveProxySettings()
		settings["BUFFER_CHUNK_SIZE"] = rigChunkBytes
		cp.Settings = settings
	}
	controlPlane := relaytest.NewControlPlane(cp)
	t.Cleanup(controlPlane.Close)

	manager := channel.NewManager(channel.ManagerConfig{BudgetBytes: rigBudgetBytes})
	t.Cleanup(manager.StopAll)

	server := New(Config{
		DevRoutes: true,
		Stream: StreamDeps{
			Secret:   testSecret,
			Channels: manager,
			Control: &control.Client{
				Secret:  testSecret,
				BaseURL: controlPlane.URL(),
				HTTP:    control.NewHTTPClient(),
			},
		},
		// THE SAME manager, not a second one. Two would give the list endpoint
		// an empty map while the tune path filled another, and every assertion
		// about what the list shows would be about the wrong object.
		Control: ControlDeps{Secret: testSecret, Channels: manager},
	})
	relay := httptest.NewServer(server.Handler())
	t.Cleanup(relay.Close)

	return &rig{Relay: relay, Upstream: upstream, Control: controlPlane, Manager: manager}
}

func (r *rig) tune(t *testing.T, path string, header http.Header) *http.Response {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+path, nil)
	if err != nil {
		t.Fatalf("building the tune request: %v", err)
	}
	for name, values := range header {
		for _, v := range values {
			request.Header.Add(name, v)
		}
	}
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("tuning: %v", err)
	}
	return response
}

// THE VERTICAL SLICE, end to end: a request reaches the relay, the relay asks
// the control plane, the control plane names a Proxy source, the relay
// connects to it, and the client receives the provider's bytes as whole,
// in-order TS packets.
func TestATuneDeliversTheProvidersBytes(t *testing.T) {
	payload := relaytest.SyntheticTS(4096, 0x100) // ~770 KB, three default chunks
	rig := newRig(t,
		relaytest.ControlPlaneConfig{},
		relaytest.Config{Payload: payload},
	)

	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("tune = %d, want 200", response.StatusCode)
	}
	if got := response.Header.Get("Content-Type"); got != "video/mp2t" {
		t.Fatalf("Content-Type = %q, want video/mp2t", got)
	}

	// Two chunks' worth. The client is positioned five seconds behind live and
	// the buffer is younger than that, so it starts at the oldest chunk --
	// meaning what arrives is the head of the provider's own payload.
	want := rigChunkBytes * 2
	got := make([]byte, want)
	if _, err := io.ReadFull(response.Body, got); err != nil {
		t.Fatalf("reading the stream: %v", err)
	}

	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the client received bytes that are not whole TS packets: %s", problem)
	}
	first := relaytest.PacketIndex(got[:buffer.TSPacketSize])
	for i := 0; i < len(got); i += buffer.TSPacketSize {
		want := (first + i/buffer.TSPacketSize) % 4096
		if idx := relaytest.PacketIndex(got[i : i+buffer.TSPacketSize]); idx != want {
			t.Fatalf("packet at byte %d carries index %d, want %d -- the stream is out of order or has gaps",
				i, idx, want)
		}
	}
	if n := rig.Upstream.Requests(); n != 1 {
		t.Fatalf("the provider saw %d requests for one tune, want 1", n)
	}
}

// A1.4's payoff, asserted where it can actually be seen. Making the rig send a
// non-default BUFFER_CHUNK_SIZE is necessary but NOT sufficient: every other
// test here reads a byte stream, and a relay that ignored the wire value and
// used the constant would still deliver correct, aligned, in-order TS -- just
// in differently sized pieces no HTTP client can observe. Measured: with the
// rig alone, forcing New to ignore cfg.ChunkBytes reddens 0 of these tests.
//
// This one looks at the ring the tune actually built. It is the only test in
// the package that reaches past the response body, and that is the point:
// chunk size is invisible from outside by construction, so an end-to-end
// assertion on it has to go one layer in or not exist.
func TestTheRingUsesTheChunkSizeTheControlPlaneSent(t *testing.T) {
	payload := relaytest.SyntheticTS(4096, 0x100)
	rig := newRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Payload: payload})

	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	if _, err := io.ReadFull(response.Body, make([]byte, rigChunkBytes)); err != nil {
		t.Fatalf("reading the stream: %v", err)
	}

	ch := rig.Manager.Get("a-channel-uuid")
	if ch == nil {
		t.Fatal("the channel is not in the manager after a successful tune")
	}
	chunks, _, _ := ch.Ring().Read(0)
	if len(chunks) == 0 {
		t.Fatal("the ring holds no chunks after the client read a chunk's worth")
	}
	if got := len(chunks[0]); got != rigChunkBytes {
		t.Fatalf("the ring's chunk is %d bytes, want %d -- the relay used its own "+
			"constant instead of the BUFFER_CHUNK_SIZE the control plane sent, "+
			"which is the second copy Amendment A1.4 removes", got, rigChunkBytes)
	}
}

// The tune makes exactly one next-source call, signed with both internal
// headers. A client that could reach the relay without them would be talking
// to a relay that had not asked Django anything.
func TestATuneMakesOneSignedControlPlaneCall(t *testing.T) {
	rig := newRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{})
	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("tune = %d, want 200", response.StatusCode)
	}
	// Read a little so the tune has certainly gone through.
	if _, err := io.ReadFull(response.Body, make([]byte, rigChunkBytes)); err != nil {
		t.Fatalf("reading the stream: %v", err)
	}

	seen := rig.Control.Requests()
	if len(seen) != 1 {
		t.Fatalf("the control plane saw %d calls, want 1", len(seen))
	}
	if !strings.HasSuffix(seen[0].Path, "/a-channel-uuid/next-source") {
		t.Fatalf("the call went to %s", seen[0].Path)
	}
	if got := seen[0].Header.Get(control.HeaderInternal); got != control.InternalPrincipalToken(testSecret) {
		t.Fatalf("%s was not the internal-principal token", control.HeaderInternal)
	}
	if seen[0].Header.Get(control.HeaderInternalRequest) == "" {
		t.Fatalf("%s was absent: the call would 403 against a real Django", control.HeaderInternalRequest)
	}
}

// The relay refuses a kind it does not serve loudly rather than falling
// through: Redirect, until 2c-5. `kind` is what it branches on: `transcode`
// is false for Redirect as well as Proxy, so a relay that read that field
// would serve a Redirect channel's provider URL through the Proxy path
// silently. (2c-2 listed transcode here too; 2c-4 serves it.)
func TestATuneRefusesAKindItDoesNotServe(t *testing.T) {
	for _, kind := range []string{control.KindRedirect} {
		t.Run(kind, func(t *testing.T) {
			rig := newRig(t, relaytest.ControlPlaneConfig{Kind: kind}, relaytest.Config{})
			response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != http.StatusNotImplemented {
				t.Fatalf("a %q channel tuned with %d, want 501", kind, response.StatusCode)
			}
			if n := rig.Upstream.Requests(); n != 0 {
				t.Fatalf("the provider was contacted %d times for a %q channel", n, kind)
			}
		})
	}
}

// Amendment A1.4's contract, enforced at runtime. An older control plane that
// sends only the seven stored keys fails the tune with a named key, rather
// than the relay quietly substituting a Go-side default.
func TestATuneRefusesIncompleteProxySettings(t *testing.T) {
	stored := map[string]any{
		"buffering_timeout":          15,
		"buffering_speed":            1.0,
		"redis_chunk_ttl":            60,
		"channel_shutdown_delay":     0,
		"channel_init_grace_period":  60,
		"channel_client_wait_period": 5,
		"new_client_behind_seconds":  5,
	}
	rig := newRig(t, relaytest.ControlPlaneConfig{Settings: stored}, relaytest.Config{})
	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("a pre-A1.4 control plane tuned with %d, want 502", response.StatusCode)
	}
	if n := rig.Upstream.Requests(); n != 0 {
		t.Fatal("the provider was contacted despite incomplete settings")
	}
}

// EVERY key is required, one at a time. The test above only proves that SOME
// key is required: with seven of them missing at once, defaulting any one in
// code still leaves six others to fail the tune, so it stays green against a
// relay that has quietly reintroduced a Go-side default. Found by running
// exactly that break-check and watching it not redden.
//
// Each subtest removes ONE key from an otherwise complete answer, so the only
// thing that can fail the tune is that key's own absence.
func TestEveryProxySettingThisRelayReadsIsRequired(t *testing.T) {
	for _, key := range []string{
		settingChunkBytes, settingRetention, settingJoinBehind, settingReadSize,
		settingShutdownDelay, settingBufferingSpeed, settingBufferingTimeout,
		settingDefaultUserAgent,
	} {
		t.Run(key, func(t *testing.T) {
			settings := relaytest.EffectiveProxySettings()
			if _, present := settings[key]; !present {
				t.Fatalf("the fixture does not carry %q, so removing it proves nothing", key)
			}
			delete(settings, key)

			rig := newRig(t, relaytest.ControlPlaneConfig{Settings: settings}, relaytest.Config{})
			response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != http.StatusBadGateway {
				t.Fatalf("an answer missing only %q tuned with %d, want 502 -- the relay "+
					"substituted a default of its own", key, response.StatusCode)
			}
		})
	}
}

// X-Relay-Channel is authoritative ONLY when the trust marker proves nginx put
// it there. Without the marker a hand-crafted header must be ignored and the
// path value used, or any client could name any channel and skip the hop.
func TestXRelayChannelIsIgnoredWithoutTheTrustMarker(t *testing.T) {
	rig := newRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{})
	response := rig.tune(t, "/proxy/ts/stream/from-the-path", http.Header{
		"X-Relay-Channel": []string{"from-the-header"},
	})
	defer func() { _ = response.Body.Close() }()

	seen := rig.Control.Requests()
	if len(seen) != 1 {
		t.Fatalf("the control plane saw %d calls, want 1", len(seen))
	}
	if !strings.Contains(seen[0].Path, "from-the-path") {
		t.Fatalf("the tune asked about %s: an unverified X-Relay-Channel was believed", seen[0].Path)
	}
}

func TestXRelayChannelIsUsedWithTheTrustMarker(t *testing.T) {
	rig := newRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{})
	response := rig.tune(t, "/proxy/ts/stream/from-the-path", http.Header{
		control.HeaderAuthorized: []string{control.RelayTrustToken(testSecret)},
		"X-Relay-Channel":        []string{"from-the-header"},
	})
	defer func() { _ = response.Body.Close() }()

	seen := rig.Control.Requests()
	if len(seen) != 1 {
		t.Fatalf("the control plane saw %d calls, want 1", len(seen))
	}
	if !strings.Contains(seen[0].Path, "from-the-header") {
		t.Fatalf("the tune asked about %s: the authorize hop's resolved channel was ignored", seen[0].Path)
	}
}

// The dev flag still gates the whole route, as 2c-1 built it.
func TestTheStreamRouteIsUnregisteredWithoutTheDevFlag(t *testing.T) {
	server := New(Config{DevRoutes: false})
	rec := httptest.NewRecorder()
	server.Handler().ServeHTTP(rec,
		httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/proxy/ts/stream/abc", nil))
	if rec.Code != http.StatusNotFound {
		t.Fatalf("GET a stream with DevRoutes=false = %d, want 404 (the route must not be registered at all)", rec.Code)
	}
}

// A stream that ends cleanly ends the client's response rather than hanging
// it, and the client gets every byte the provider sent.
func TestAStreamThatEndsClosesTheClientsResponse(t *testing.T) {
	payload := relaytest.SyntheticTS(4096, 0x100)
	rig := newRig(t,
		relaytest.ControlPlaneConfig{},
		relaytest.Config{Payload: payload, StopAfterBytes: len(payload)},
	)

	response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
	defer func() { _ = response.Body.Close() }()
	done := make(chan []byte, 1)
	go func() {
		body, _ := io.ReadAll(response.Body)
		done <- body
	}()

	select {
	case body := <-done:
		if len(body) == 0 {
			t.Fatal("the client received nothing at all")
		}
		if problem := relaytest.AlignmentProblem(body); problem != "" {
			t.Fatalf("the delivered stream is not whole TS packets: %s", problem)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the client's response never ended after the upstream stopped")
	}
}
```

**`relay/httpapi/testdata/channels_clients_all.json`** (hand-written in DRF's spelling; regenerate — yours governs)

```json
{"channels": [{"channel_id": "11111111-1111-4111-8111-111111111111", "state": "active", "url": "http://provider.invalid/live/sub/pw/41.ts", "stream_profile": "1", "owner": null, "buffer_index": 120, "client_count": 2, "uptime": 30.0, "started_at": 1789000000.5, "channel_name": "BBC One HD", "m3u_profile_id": 3, "stream_id": 41, "stream_name": "BBC One HD (UK)", "total_bytes": 9999888, "avg_bitrate_kbps": 2665.3034666666667, "avg_bitrate": "2.67 Mbps", "video_codec": "h264", "resolution": "1920x1080", "source_fps": 25.0, "ffmpeg_speed": 1.02, "audio_codec": "aac", "audio_channels": "stereo", "stream_type": "mpegts", "clients": [{"client_id": "client_1789000000000_1234", "user_agent": "VLC/3.0.20", "output_format": "mpegts", "output_profile_id": 7, "ip_address": "198.51.100.4", "connected_at": 1789000001.25, "user_id": "7"}, {"client_id": "client_1789000000000_5678", "user_agent": null, "output_format": "mpegts", "output_profile_id": null}]}, {"channel_id": "22222222-2222-4222-8222-222222222222", "state": "stopped", "url": "", "stream_profile": "0", "owner": null, "buffer_index": 0, "client_count": 0, "uptime": 0.0, "started_at": 1789000100.0, "clients": []}], "count": 2}
```

### Appendix R — the credential guard — `relay/internal/credlint/*` and `scripts/check_go_credential_logging.sh`

**`relay/internal/credlint/check.go`**

```go
// Package credlint is the Go side of scripts/check_credential_logging.py: a
// type-aware check that no error can reach a log line or an error message
// unredacted.
//
// THE RULE. In every non-test Go file of the module, every argument of type
// error handed to a formatting or logging call -- fmt.Errorf and its Sprint
// family, package log's Print family, and log/slog's level methods, on the
// package and on a *slog.Logger -- must be a direct call to redact.Error, or
// the call must carry a `credential-logging: ok - <reason>` comment on one
// of its own lines or the line above it. A bare reason-less marker clears
// nothing, for the reason the Python check gives: an exemption nobody has
// to justify is not reviewable.
//
// WHY THE ERROR TYPE IS THE HOOK. A provider URL reaches a Go log through
// exactly one door in this module: an error that carries it. net/http wraps
// every client failure in a *url.Error whose Error() prints the whole URL,
// and a %w or a slog "error" key hands that string to the log. 2c-2's review
// found the leak at the one *url.Error site the human guard missed; a check
// that is blind to the variable's NAME and keyed on its TYPE cannot miss
// the next one. Strings are not checked: a string argument to a log call is
// either a literal or a value the author chose to log, and the Python check
// has the same limit (it matches variable names, not values). What a string
// CAN carry -- an ffmpeg stderr line echoing the URL -- is redacted by
// redact.Line at the one site such lines are logged, and the test whose
// secret has exactly one source (channel.TestAProviderURLInStderrNeverReaches
// TheLog) is the guard for that door.
//
// KNOWN GAPS, stated as the Python check states its three. A composite
// literal that stores an error in a field (control.Unavailable{Err: err})
// is not a call and is not checked; the type's Error() method is, so the
// leak surfaces there, one hop later, which is where 2c-4 found and fixed
// one. errors.Join and a custom Error() that formats a field with %v are
// checked only if they go through the listed functions. And an error
// stringified by hand (err.Error() passed as a string) is invisible, by the
// string rule above.
//
// TYPE-CHECKED WITH THE STANDARD LIBRARY ONLY: go/parser, go/types and the
// gc export-data importer, which on this toolchain resolves standard
// packages in about a hundred milliseconds. Module-local packages are
// checked from source in dependency order (go list -deps), so
// github.com/.../relay/redact resolves to the real package and the
// allowlist below is a full name, not a guess.
package main

import (
	"bytes"
	"context"
	"fmt"
	"go/ast"
	"go/importer"
	"go/parser"
	"go/token"
	"go/types"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
)

// Marker is the exemption comment, modelled on `# credential-logging: ignore
// - <reason>` on the Python side and `# zizmor: ignore[...]` before it.
const Marker = "credential-logging: ok"

// Redactors are the functions an error may pass through on its way to a
// log or a message. One entry; a second implementation would be a second
// thing to remember.
var Redactors = map[string]bool{
	"github.com/D10Scot/Dispatcharr/relay/redact.Error": true,
}

// Sinks are the functions whose error-typed arguments are checked, by
// go/types full name. Methods are spelled the way types.Func.FullName
// spells them.
var Sinks = map[string]bool{
	"fmt.Errorf": true, "fmt.Sprintf": true, "fmt.Sprint": true, "fmt.Sprintln": true,
	"fmt.Fprintf": true, "fmt.Fprint": true, "fmt.Fprintln": true,
	"fmt.Printf": true, "fmt.Print": true, "fmt.Println": true,
	"log.Printf": true, "log.Print": true, "log.Println": true,
	"log.Fatalf": true, "log.Fatal": true, "log.Fatalln": true,
	"log.Panicf": true, "log.Panic": true, "log.Panicln": true,
	"log/slog.Error": true, "log/slog.Warn": true, "log/slog.Info": true, "log/slog.Debug": true, "log/slog.Log": true,
	"log/slog.ErrorContext": true, "log/slog.WarnContext": true, "log/slog.InfoContext": true, "log/slog.DebugContext": true,
	"log/slog.Any":             true,
	"(*log/slog.Logger).Error": true, "(*log/slog.Logger).Warn": true, "(*log/slog.Logger).Info": true,
	"(*log/slog.Logger).Debug": true, "(*log/slog.Logger).Log": true, "(*log/slog.Logger).With": true,
	"(*log/slog.Logger).ErrorContext": true, "(*log/slog.Logger).WarnContext": true,
	"(*log/slog.Logger).InfoContext": true, "(*log/slog.Logger).DebugContext": true,
}

// Finding is one unredacted error argument.
type Finding struct {
	Pos    token.Position
	Callee string
	Arg    int
	Reason string
}

func (f Finding) String() string {
	return fmt.Sprintf("%s: %s argument %d has type error and is not redacted: %s", f.Pos, f.Callee, f.Arg, f.Reason)
}

// Package is one module package to check: its import path, directory and
// non-test Go files, as `go list` reports them.
type Package struct {
	ImportPath string
	Dir        string
	Files      []string
}

// ListPackages runs `go list -deps` on the patterns and returns the
// module's own packages in dependency order.
func ListPackages(moduleDir string, patterns ...string) (module string, pkgs []Package, err error) {
	out, err := goList(moduleDir, "-m", "-f", "{{.Path}}")
	if err != nil {
		return "", nil, err
	}
	module = strings.TrimSpace(out)

	args := append([]string{"-deps", "-f", "{{.ImportPath}}\t{{.Dir}}\t{{join .GoFiles \",\"}}"}, patterns...)
	out, err = goList(moduleDir, args...)
	if err != nil {
		return "", nil, err
	}
	for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
		parts := strings.SplitN(line, "\t", 3)
		if len(parts) != 3 || !strings.HasPrefix(parts[0], module) {
			continue
		}
		var files []string
		for _, f := range strings.Split(parts[2], ",") {
			if f != "" {
				files = append(files, filepath.Join(parts[1], f))
			}
		}
		pkgs = append(pkgs, Package{ImportPath: parts[0], Dir: parts[1], Files: files})
	}
	return module, pkgs, nil
}

func goList(dir string, args ...string) (string, error) {
	// #nosec G204,G702 -- the go tool with fixed flags and the caller's
	// package patterns; both rule ids are needed, the taint rule G702 fires
	// on the same line once G204 is silenced (the G304/G703 pairing 2c-1
	// found, on a different rule pair).
	cmd := exec.CommandContext(context.Background(), "go", append([]string{"list"}, args...)...)
	cmd.Dir = dir
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	out, err := cmd.Output()
	if err != nil {
		return "", fmt.Errorf("go list %s: %w: %s", strings.Join(args, " "), err, stderr.String()) // credential-logging: ok - the go tool's own diagnostics about package paths
	}
	return string(out), nil
}

// Checker type-checks packages in order and collects findings.
type Checker struct {
	fset     *token.FileSet
	std      types.Importer
	checked  map[string]*types.Package
	Findings []Finding
}

// NewChecker builds a checker whose standard-library imports come from the
// gc importer.
func NewChecker() *Checker {
	fset := token.NewFileSet()
	return &Checker{fset: fset, std: importer.ForCompiler(fset, "gc", nil), checked: map[string]*types.Package{}}
}

// Import satisfies types.Importer: a module package already checked is
// returned from the cache, everything else goes to the gc importer.
func (c *Checker) Import(path string) (*types.Package, error) {
	if pkg, ok := c.checked[path]; ok {
		return pkg, nil
	}
	return c.std.Import(path)
}

// CheckSources type-checks one package given as file name to source, for
// tests and for CheckPackage.
func (c *Checker) CheckSources(importPath string, sources map[string]string) error {
	var files []*ast.File
	names := make([]string, 0, len(sources))
	for name := range sources {
		names = append(names, name)
	}
	sort.Strings(names)
	for _, name := range names {
		f, err := parser.ParseFile(c.fset, name, sources[name], parser.ParseComments)
		if err != nil {
			return err
		}
		files = append(files, f)
	}
	info := &types.Info{Types: map[ast.Expr]types.TypeAndValue{}, Uses: map[*ast.Ident]types.Object{}, Selections: map[*ast.SelectorExpr]*types.Selection{}}
	conf := types.Config{Importer: c}
	pkg, err := conf.Check(importPath, c.fset, files, info)
	if err != nil {
		return err
	}
	c.checked[importPath] = pkg
	for _, f := range files {
		c.inspect(f, info)
	}
	return nil
}

// CheckPackage reads a package's files and checks them.
func (c *Checker) CheckPackage(p Package) error {
	sources := map[string]string{}
	for _, name := range p.Files {
		raw, err := os.ReadFile(name) // #nosec G304 -- a path `go list` reported for a package the caller named
		if err != nil {
			return err
		}
		sources[name] = string(raw)
	}
	return c.CheckSources(p.ImportPath, sources)
}

var errorType = types.Universe.Lookup("error").Type().Underlying().(*types.Interface)

func (c *Checker) inspect(f *ast.File, info *types.Info) {
	markers := markerLines(c.fset, f)
	ast.Inspect(f, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		callee := calleeName(call, info)
		if !Sinks[callee] {
			return true
		}
		for i, arg := range call.Args {
			tv, ok := info.Types[arg]
			if !ok || tv.Type == nil {
				continue
			}
			if !types.Implements(tv.Type, errorType) && !types.Implements(types.NewPointer(tv.Type), errorType) {
				continue
			}
			if isNil(tv) {
				continue
			}
			if inner, ok := arg.(*ast.CallExpr); ok && Redactors[calleeName(inner, info)] {
				continue
			}
			start := c.fset.Position(call.Pos())
			end := c.fset.Position(call.End())
			if reason, ok := markerFor(markers, start.Line, end.Line); ok {
				if reason == "" {
					c.Findings = append(c.Findings, Finding{Pos: start, Callee: callee, Arg: i,
						Reason: "the credential-logging marker has no reason; write `credential-logging: ok - <why this cannot carry a URL>`"})
				}
				continue
			}
			c.Findings = append(c.Findings, Finding{Pos: start, Callee: callee, Arg: i,
				Reason: "wrap it in redact.Error(...) or add `// credential-logging: ok - <reason>` on the call"})
		}
		return true
	})
}

func isNil(tv types.TypeAndValue) bool { return tv.IsNil() }

// calleeName resolves a call's function to go/types' full name, or "".
func calleeName(call *ast.CallExpr, info *types.Info) string {
	var id *ast.Ident
	switch fn := call.Fun.(type) {
	case *ast.Ident:
		id = fn
	case *ast.SelectorExpr:
		id = fn.Sel
	default:
		return ""
	}
	obj, ok := info.Uses[id]
	if !ok {
		return ""
	}
	fn, ok := obj.(*types.Func)
	if !ok {
		return ""
	}
	return fn.FullName()
}

// markerLines maps a line number to the marker's reason ("" when the
// marker has none) for every comment carrying it.
func markerLines(fset *token.FileSet, f *ast.File) map[int]string {
	out := map[int]string{}
	for _, group := range f.Comments {
		for _, comment := range group.List {
			text := comment.Text
			idx := strings.Index(text, Marker)
			if idx < 0 {
				continue
			}
			rest := strings.TrimSpace(text[idx+len(Marker):])
			reason := ""
			if strings.HasPrefix(rest, "-") {
				reason = strings.TrimSpace(strings.TrimPrefix(rest, "-"))
			}
			out[fset.Position(comment.Pos()).Line] = reason
		}
	}
	return out
}

// markerFor finds a marker on any line the call spans, or the line above
// its first, and reports its reason.
func markerFor(markers map[int]string, start, end int) (string, bool) {
	for line := start - 1; line <= end; line++ {
		if reason, ok := markers[line]; ok {
			return reason, true
		}
	}
	return "", false
}
```

**`relay/internal/credlint/main.go`**

```go
package main

import (
	"fmt"
	"os"
)

// Usage: credlint [-C module-dir] [patterns...]  (default ./...)
// Exit:  0 = no findings; 1 = findings, one per line; 2 = could not run.
func main() {
	dir := "."
	args := os.Args[1:]
	if len(args) >= 2 && args[0] == "-C" {
		dir, args = args[1], args[2:]
	}
	if len(args) == 0 {
		args = []string{"./..."}
	}
	_, pkgs, err := ListPackages(dir, args...)
	if err != nil {
		fmt.Fprintln(os.Stderr, "credlint:", err) // credential-logging: ok - the checker's own diagnostics: go list output and type errors
		os.Exit(2)
	}
	checker := NewChecker()
	for _, p := range pkgs {
		if err := checker.CheckPackage(p); err != nil {
			fmt.Fprintf(os.Stderr, "credlint: %s: %v\n", p.ImportPath, err) // credential-logging: ok - a type-check error naming source positions
			os.Exit(2)
		}
	}
	for _, f := range checker.Findings {
		fmt.Println(f)
	}
	if len(checker.Findings) > 0 {
		fmt.Fprintf(os.Stderr, "credlint: %d unredacted error argument(s); see relay/internal/credlint/check.go for the rule\n", len(checker.Findings))
		os.Exit(1)
	}
	fmt.Printf("credlint: %d package(s) clean\n", len(pkgs))
}
```

**`relay/internal/credlint/check_test.go`**

```go
package main

import (
	"strings"
	"testing"
)

// A fixture package with every shape the rule speaks to. Each line that
// must be reported names itself in a comment, so a finding's line is
// checked against the fixture rather than counted.
const fixture = `package fixture

import (
	"errors"
	"fmt"
	"log"
	"log/slog"
	"net/url"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

type wrapped struct{ err error }

func (w wrapped) Error() string { return fmt.Sprintf("wrapped: %v", w.err) } // BAD: a method formatting an error field

func shapes(logger *slog.Logger, err error) error {
	_ = fmt.Errorf("plain: %w", err)                  // BAD
	_ = fmt.Errorf("redacted: %w", redact.Error(err)) // ok: through the redactor
	_ = fmt.Errorf("marked: %w", err)                 // credential-logging: ok - a test fixture with a reason
	// credential-logging: ok - a marker on the line above
	_ = fmt.Errorf("marked above: %w", err)
	_ = fmt.Errorf("bare marker: %w", err) // credential-logging: ok
	_ = fmt.Errorf("no error here: %s", "text")
	_ = fmt.Errorf("nil is fine: %w", nil)
	logger.Error("slog method", "error", err)                // BAD
	logger.Error("slog redacted", "error", redact.Error(err)) // ok
	slog.Warn("slog package", "error", err)                   // BAD
	log.Printf("log package: %v", err)                        // BAD
	_ = slog.Any("error", err)                                // BAD
	var uerr *url.Error
	if errors.As(err, &uerr) {
		return fmt.Errorf("typed: %w", uerr) // BAD: a *url.Error is an error
	}
	return wrapped{err: err} // not a call: the known composite-literal gap
}
`

// newCheckerWithRedact type-checks the module's own redact package first, so
// the fixture's import of it resolves to the real package and the allowlist
// is exercised against the name go/types gives it.
func newCheckerWithRedact(t *testing.T) *Checker {
	t.Helper()
	_, pkgs, err := ListPackages("../..", "./redact")
	if err != nil {
		t.Fatalf("listing the redact package: %v", err)
	}
	c := NewChecker()
	for _, p := range pkgs {
		if err := c.CheckPackage(p); err != nil {
			t.Fatalf("checking %s: %v", p.ImportPath, err)
		}
	}
	if len(c.Findings) != 0 {
		t.Fatalf("the redact package itself has findings: %v", c.Findings)
	}
	return c
}

func TestTheRuleReportsExactlyTheBadLines(t *testing.T) {
	c := newCheckerWithRedact(t)
	if err := c.CheckSources("example.com/fixture", map[string]string{"fixture.go": fixture}); err != nil {
		t.Fatalf("type-checking the fixture: %v", err)
	}
	want := map[int]bool{}
	for i, line := range strings.Split(fixture, "\n") {
		if strings.Contains(line, "// BAD") || strings.Contains(line, "bare marker") {
			want[i+1] = true
		}
	}
	got := map[int]bool{}
	for _, f := range c.Findings {
		got[f.Pos.Line] = true
	}
	for line := range want {
		if !got[line] {
			t.Errorf("line %d was not reported: %s", line, strings.Split(fixture, "\n")[line-1])
		}
	}
	for line := range got {
		if !want[line] {
			t.Errorf("line %d was reported and should not have been: %s", line, strings.Split(fixture, "\n")[line-1])
		}
	}
	for _, f := range c.Findings {
		if strings.Contains(strings.Split(fixture, "\n")[f.Pos.Line-1], "bare marker") && !strings.Contains(f.Reason, "no reason") {
			t.Errorf("the bare marker was reported for the wrong reason: %s", f.Reason)
		}
	}
}

// The redactor allowlist is the ONE function, spelled as go/types spells
// it. A rename on either side must fail here, not silently clear every call.
func TestTheRedactorIsExactlyRedactError(t *testing.T) {
	if len(Redactors) != 1 || !Redactors["github.com/D10Scot/Dispatcharr/relay/redact.Error"] {
		t.Fatalf("Redactors = %v, want exactly relay/redact.Error", Redactors)
	}
	c := NewChecker()
	// A package that defines its own Error and calls it: NOT a redactor.
	src := `package fixture
import "fmt"
func Error(err error) error { return err }
func f(err error) error { return fmt.Errorf("local: %w", Error(err)) } // BAD
`
	if err := c.CheckSources("example.com/local", map[string]string{"local.go": src}); err != nil {
		t.Fatal(err)
	}
	if len(c.Findings) != 1 {
		t.Fatalf("a local function named Error cleared the call: %v", c.Findings)
	}
}
```

**`scripts/check_go_credential_logging.sh`**

```bash
#!/usr/bin/env bash
# The Go side of scripts/check_credential_logging.py: every error-typed
# argument to a formatting or logging call in relay/ passes through
# redact.Error or carries a `credential-logging: ok - <reason>` marker.
# relay/internal/credlint/check.go states the rule, its reach and its known
# gaps; this script only runs it from the module root, so the hook and
# go-tests.yml invoke one thing.
#
# Stdlib only, like the module it checks: `go run` builds the checker from
# the module's own source, so there is nothing to install and no version to
# pin.
set -euo pipefail

MODULE_ROOT="${1:-relay}"
cd "$MODULE_ROOT"
exec go run ./internal/credlint ./...
```

### Appendix S — the hook and the workflow, as diffs; and the markers in `config.go` and `main.go`

**`.claude/hooks/run-go-checks.sh`**

```diff
--- /Users/dion/git/Dispatcharr/.worktrees/plan-2c4/.claude/hooks/run-go-checks.sh	2026-09-13 15:52:46
+++ .claude/hooks/run-go-checks.sh	2026-09-13 16:41:47
@@ -7,6 +7,7 @@
 #   build        go build ./...          the whole module
 #   vet          go vet ./...            the whole module
 #   lint         golangci-lint run       the whole module, zero findings
+#   credlint     go run ./internal/credlint ./...   the whole module, zero findings
 #   tests        go test -race ./<pkg>   the edited file's package only
 #
 # Zero lint findings is a ratchet, the same rule as zizmor's: the module
@@ -110,6 +111,19 @@
 fi
 
 if [ -z "$BLOCK_TITLE" ]; then
+  # The credential-logging guard, the Go side of scripts/
+  # check_credential_logging.py: zero findings is a ratchet like the
+  # linter's. Run through the same script go-tests.yml runs, so the two
+  # cannot disagree. It is built from the module's own source by `go run`,
+  # so there is nothing to install and no version to pin.
+  OUT="$(cd "$MODULE_ROOT" && go run ./internal/credlint ./... 2>&1)"
+  if [ $? -ne 0 ]; then
+    block "credential-logging findings in ${MODULE_ROOT}" \
+          "$(printf '%s' "$OUT" | head -30)"$'\n\n'"Every error-typed log or format argument passes through redact.Error, or carries '// credential-logging: ok - <reason>'. relay/internal/credlint/check.go states the rule."
+  fi
+fi
+
+if [ -z "$BLOCK_TITLE" ]; then
   if command -v golangci-lint >/dev/null 2>&1; then
     # Keep in sync with the pinned `version:` in go-tests.yml — that is the
     # whole point of this check. A silent version mismatch is worse than no
```

**`.github/workflows/go-tests.yml`**

```diff
--- /Users/dion/git/Dispatcharr/.worktrees/plan-2c4/.github/workflows/go-tests.yml	2026-09-13 15:52:46
+++ .github/workflows/go-tests.yml	2026-09-13 16:41:47
@@ -83,7 +83,7 @@
           # nothing here to verify. docker-build.yml would catch a broken
           # relay-builder stage, but only for a Dockerfile change and only
           # AFTER merge -- it triggers on push to main, not on PRs.
-          pattern='^(relay/|\.golangci\.yml$|scripts/check_go_stdlib_only\.sh$|\.github/workflows/go-tests\.yml$)'
+          pattern='^(relay/|\.golangci\.yml$|scripts/check_go_stdlib_only\.sh$|scripts/check_go_credential_logging\.sh$|\.github/workflows/go-tests\.yml$|apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/)'
           if printf '%s\n' "$changed" | grep -qE "$pattern"; then
             echo "go=true" >> "$GITHUB_OUTPUT"
           else
@@ -113,6 +113,20 @@
           # Dockerfile's builder stage without go.mod moving too.
           go-version-file: relay/go.mod
 
+      # Real ffmpeg, for parity-matrix row 4's one real-ffmpeg pin
+      # (relay/channel/source_transcode_real_test.go). The test FAILS rather
+      # than skips when CI is set and ffmpeg is absent, so a runner image
+      # that stops shipping it cannot turn the pin into a silent skip. The
+      # distribution's ffmpeg, not the Dispatcharr image's 8.1.2: the row's
+      # claim is about ffmpeg's cumulative speed= average, which every
+      # version this project has met shares, and the test asserts a shape,
+      # never a digit.
+      - name: Install ffmpeg
+        run: |
+          sudo apt-get update
+          sudo apt-get install -y --no-install-recommends ffmpeg
+          ffmpeg -version | head -1
+
       - name: Build
         run: go build ./...
 
@@ -130,6 +144,15 @@
         working-directory: .
         run: scripts/check_go_stdlib_only.sh relay
 
+      # The Go side of the credential-logging rule (lint.yml's
+      # credential-logging job is the Python side): every error-typed
+      # argument to a formatting or logging call passes through
+      # redact.Error or carries a written reason. relay/internal/credlint
+      # states the rule; the PostToolUse hook runs the same script.
+      - name: Assert no error reaches a log unredacted
+        working-directory: .
+        run: scripts/check_go_credential_logging.sh relay
+
   lint:
     name: golangci-lint
     runs-on: ubuntu-latest
```

**`relay/config/config.go`** — two markers, on the two `fmt.Errorf` lines of `ReadSecretFile`:

```go
132:		return "", fmt.Errorf("reading secret file %s: %w", path, err) // credential-logging: ok - an *fs.PathError naming the operator-named secret FILE, which is configuration, never the secret and never a URL
136:		return "", fmt.Errorf("%s: %w", path, ErrEmptySecret) // credential-logging: ok - a sentinel and the secret file's path
```

**`relay/main.go`** — two markers, on the two `log.Printf` lines:

```go
33:		log.Printf("startup failed: %v", err) // credential-logging: ok - config.Load's errors name a variable, a port, or the secret FILE's path, never the secret
83:		log.Printf("server stopped: %v", err) // credential-logging: ok - a net.Listen or Serve error naming the bind address
```

### Appendix T — the Python half

**T1 — `apps/proxy/next_source.py`, replacement bodies and named edits**

```python
# apps/proxy/next_source.py -- the 2c-4 edits, as REPLACEMENT BODIES. Each block
# below replaces the function of the same name at 81d41975 (line numbers in the
# task); the rest of the module is untouched.

# --- replaces _stream_profile_ref (next_source.py:105-122) --------------------

def _stream_profile_ref(profile, *, url, user_agent, pk):
    """A StreamProfile flattened to the wire shape StreamProfileRefSerializer renders,
    with the argv Django BUILT for this source.

    One construction site for what used to be four near-identical dict
    literals. That duplication has already cost this module a
    production defect once: the `transcode` derivation lived at two
    points, they disagreed about Redirect, and every reconnect during
    a recording spawned an empty executable
    (apps/proxy/tests/test_redirect_transcode_flag.py's own docstring).
    A second per-profile fact derived independently in four places is
    that defect pre-built.

    Phase 2 PR 2c-4, spec Amendment A4.1: `argv` is StreamProfile.build_command
    (core/models.py:137-160 -- shlex.split of `parameters`, then the three
    {streamUrl}/{userAgent}/{channelId} substitutions) with the command
    removed, built here for THIS source's url, user agent and object, so the
    Go relay carries no word splitter and no substitution table and spawns,
    byte for byte, what the Python relay spawns from the same answer. The
    user agent is defaulted the way input/manager.py:73 defaults it
    (`user_agent or Config.DEFAULT_USER_AGENT`), because that is the value
    the Python relay substitutes.

    Three shapes, and a Go client tells them apart by presence: a list (empty
    for Proxy and Redirect, whose build_command returns []); None when shlex
    refuses the parameters -- an unbalanced quote raises ValueError, which
    the Python relay meets only at spawn time inside
    _establish_transcode_connection's broad except -- rendered as JSON null
    so the relay refuses the tune by name; and the key absent, which only a
    Django older than this can produce.
    """
    from apps.proxy.config import TSConfig

    try:
        argv = profile.build_command(url, user_agent or TSConfig.DEFAULT_USER_AGENT, pk)[1:]
    except ValueError:
        # OutputProfileSerializer validates nothing and StreamProfile's
        # serializer validates no better: an unbalanced quote can already
        # be sitting in the row. The answer still serves -- the relay
        # refuses this profile, not the whole channel list.
        logger.error(
            "StreamProfile %s has unparseable parameters; sending argv=null", profile.id
        )
        argv = None
    return {
        "id": profile.id,
        "command": profile.command,
        "args": profile.parameters,
        "kind": _profile_kind(profile),
        "argv": argv,
    }


# --- replaces _locked_ffmpeg_profile (next_source.py:125-150) ----------------

def _locked_ffmpeg_profile():
    """The locked 'ffmpeg' StreamProfile ROW, or None.

    input/manager.py:737 used to run this query inside the relay process on
    the force-ffmpeg reconnect path (HLS/RTSP/UDP upstreams detected at
    connect time). Phase 2 PR 2b-1 folds it into every next-source answer
    instead: Django is already holding an open ORM here, and the relay
    cannot be.

    None means "no locked ffmpeg profile is installed", which is what the
    relay's own `except StreamProfile.DoesNotExist` branch already handled
    by falling back to the channel's own profile. The key is always
    present so the relay can tell "not installed" from "old Django".

    THE ROW, NOT THE FLATTENED DICT, since Phase 2 PR 2c-4: the dict now
    carries an argv built for each Source's own URL, so what one
    resolve_source() call shares across the primary source and its N
    alternates is the row, and each Source renders it for itself
    (_LockedFfmpegProfile.ref). Called through _LockedFfmpegProfile, which
    is what keeps it to one query per resolve_source() call
    (test_resolving_with_alternates_runs_the_locked_ffmpeg_query_once).
    """
    return StreamProfile.objects.filter(name="ffmpeg", locked=True).first()


class _LockedFfmpegProfile:
    """The locked ffmpeg row, resolved at most once per resolve_source() call
    and only when a Source is actually about to be built.

    Replaces the pre-resolved-dict threading 2b-1 used for the N-alternates
    case (resolve_source()'s note): the holder is created once in
    resolve_source(), handed to resolve_initial_source, _resolve_alternates
    and _commit, and queries the first time any of them needs the row --
    never for an answer that builds no Source, which is what
    NextSourceDbCleanupTests pins.

    Accepts what the old kwarg accepted, so the existing call shapes and
    tests keep working: the _UNRESOLVED_FFMPEG_PROFILE sentinel (resolve
    lazily), None (not installed), a StreamProfile row (pre-resolved).
    """

    def __init__(self, profile=_UNRESOLVED_FFMPEG_PROFILE):
        self._profile = profile

    @classmethod
    def wrap(cls, value):
        return value if isinstance(value, cls) else cls(value)

    def get(self):
        if self._profile is _UNRESOLVED_FFMPEG_PROFILE:
            self._profile = _locked_ffmpeg_profile()
        return self._profile

    def ref(self, *, url, user_agent, pk):
        """ffmpeg_stream_profile for one Source: the row built for THIS url, or None."""
        profile = self.get()
        if profile is None:
            return None
        return _stream_profile_ref(profile, url=url, user_agent=user_agent, pk=pk)


# --- resolve_initial_source (next_source.py:500-640): the signature gains a
#     kwarg and the two Source literals change. Everything else is untouched.
#
#   def resolve_initial_source(identifier, *, locked_ffmpeg_profile=_UNRESOLVED_FFMPEG_PROFILE):
#       ...
#       locked = _LockedFfmpegProfile.wrap(locked_ffmpeg_profile)
#
#   the stream-preview literal (:562-569):
#                       "stream_profile": _stream_profile_ref(
#                           stream_profile, url=stream_url, user_agent=stream_user_agent, pk=stream.id
#                       ),
#                       ...
#                       "ffmpeg_stream_profile": locked.ref(
#                           url=stream_url, user_agent=stream_user_agent, pk=stream.id
#                       ),
#
#   the channel literal (:620-627):
#                   "stream_profile": _stream_profile_ref(
#                       stream_profile, url=stream_url, user_agent=stream_user_agent, pk=channel.id
#                   ),
#                   ...
#                   "ffmpeg_stream_profile": locked.ref(
#                       url=stream_url, user_agent=stream_user_agent, pk=channel.id
#                   ),
#
#   pk is what the Python relay passes: input/manager.py:791's
#   `channel.id`, where channel is get_stream_object(self.channel_id) -- the
#   Channel's pk for a channel tune, the Stream's for a stream-hash preview.

# --- get_stream_info_for_switch (next_source.py:242-368): ONE key added to the
#     dict it returns, so _source_from_info can build argv with the same pk the
#     Python relay uses. Internal to this module; not on the wire.
#
#           'm3u_profile_name': m3u_profile.name,
#           'channel_pk': channel.id,

# --- replaces _source_from_info (next_source.py:643-670) ----------------------

def _source_from_info(info, *, slot_reserved, locked_ffmpeg_profile=_UNRESOLVED_FFMPEG_PROFILE):
    """Shape one Source dict from a get_stream_info_for_switch answer.

    `info['stream_profile']` is a core.models.StreamProfile id (the
    ffmpeg/proxy/redirect profile), not the M3U profile -- the seven fields
    here are the SourceSerializer contract Task 6 adds.

    locked_ffmpeg_profile: see resolve_source()'s N-alternates note --
    _resolve_alternates calls this once per candidate, so a caller that
    knows it in advance (that function, and _commit) should pass it rather
    than let each call re-run the query. Since 2c-4 it is a
    _LockedFfmpegProfile (or anything its wrap() accepts), and the
    flattening happens here, per Source, because the argv depends on
    info['url'].
    """
    locked = _LockedFfmpegProfile.wrap(locked_ffmpeg_profile)
    stream_profile = StreamProfile.objects.get(id=info["stream_profile"])
    return {
        "stream_id": info["stream_id"],
        "url": info["url"],
        "user_agent": info["user_agent"],
        "transcode": info["transcode"],
        "stream_profile": _stream_profile_ref(
            stream_profile, url=info["url"], user_agent=info["user_agent"], pk=info.get("channel_pk")
        ),
        "m3u_profile_id": info["m3u_profile_id"],
        "slot_reserved": slot_reserved,
        "channel_name": info.get("channel_name"),
        "stream_name": info.get("stream_name"),
        "m3u_profile_name": info.get("m3u_profile_name"),
        "ffmpeg_stream_profile": locked.ref(
            url=info["url"], user_agent=info["user_agent"], pk=info.get("channel_pk")
        ),
    }


# --- _resolve_alternates (next_source.py:673-693) and _commit (:696-714): one
#     line each. The lazy-resolve `if ... is _UNRESOLVED_FFMPEG_PROFILE:` block in
#     _resolve_alternates becomes
#
#       locked_ffmpeg_profile = _LockedFfmpegProfile.wrap(locked_ffmpeg_profile)
#
#     and both keep passing `locked_ffmpeg_profile=locked_ffmpeg_profile` down.
#     test_an_unresolved_locked_ffmpeg_profile_is_resolved_once still holds:
#     the holder calls _locked_ffmpeg_profile() through the module attribute,
#     once, and only when a candidate is built -- with get_alternate_streams
#     patched to [], the assertion `locked.assert_called_once()` needs the
#     holder to resolve EAGERLY in _resolve_alternates, as the old code did at
#     :681-682. Keep that: call `locked_ffmpeg_profile.get()` right after
#     wrap(), which is the one query the test counts.

# --- resolve_source (next_source.py:812-960): the holder is created once and
#     threaded. Three edits.
#
#   after `is_failover_request = ...` (:895):
#       locked = _LockedFfmpegProfile()
#
#   the initial-tune branch (:905, :916-919):
#       answer = resolve_initial_source(identifier, locked_ffmpeg_profile=locked)
#       ...
#           answer["alternates"] = _resolve_alternates(
#               identifier, answer["source"]["stream_id"], locked_ffmpeg_profile=locked,
#           )
#
#   both _commit calls (:930 and :950):
#       "source": _commit(identifier, info, locked_ffmpeg_profile=locked),
```

**T2 — `apps/proxy/serializers.py`, one field**

```python
# apps/proxy/serializers.py -- one field on StreamProfileRefSerializer, after `kind`
# (serializers.py:50). The docstring's `args` paragraph is unchanged.

    # Phase 2 PR 2c-4, spec Amendment A4.1: the argument list Django BUILT
    # for this source -- StreamProfile.build_command(url, user_agent, pk)
    # with the command removed -- so the Go relay carries no shlex and no
    # substitution table. `args` stays: the Python relay's force-ffmpeg path
    # still reads it (input/manager.py:745's stored["args"]), and D5 forbids
    # altering what exists.
    #
    # allow_null: null is "shlex refused these parameters" (an unbalanced
    # quote), a real state a row can be in, and the relay refuses THAT
    # profile rather than the whole answer. NOT required=False: a Go relay
    # tells an unbuildable profile from an older Django by whether the key
    # is present, so every producer must send it.
    argv = serializers.ListField(
        child=serializers.CharField(allow_blank=True), allow_null=True
    )
```

**T3 — `apps/proxy/tests/test_stream_profile_argv.py`**

```python
"""Phase 2 PR 2c-4, spec Amendment A4.1: next-source carries the BUILT argv.

The Go relay spawns exactly what StreamProfile.build_command produces for the
same url, user agent and object, because Django builds it and sends it. These
tests pin the builder from the Python side: every migration-shipped parameter
string, the adversarial shapes that made a Go port of shlex the riskier path,
and the three states of the field. The Go side pins presence and refusal
(relay/control/profile_test.go, relay/httpapi/transcode_test.go).

EVERY EXPECTED ARGV IS A LITERAL, never `build_command(...)[1:]` -- that would
be the tautological oracle, the same function computing both sides. The
literals were derived by hand from the parameters and confirmed against
`python3 -c 'import shlex; ...'` while the plan was written.
"""

from django.test import TestCase
from rest_framework.renderers import JSONRenderer

from apps.proxy.config import TSConfig
from apps.proxy.next_source import _stream_profile_ref
from apps.proxy.serializers import StreamProfileRefSerializer
from core.models import PROXY_PROFILE_NAME, REDIRECT_PROFILE_NAME, StreamProfile

URL = "http://provider.example/live/subscriber/hunter2/41.ts?token=s3cr3t"
UA = "Dispatcharr/2c4 (test)"


def profile(command, parameters, **fields):
    """An UNLOCKED row, so core/models.py:78-101's protected-field guard
    never runs; created rather than fetched because a TransactionTestCase
    earlier in the process may have flushed the migration-seeded rows."""
    return StreamProfile.objects.create(
        name=f"argv-{command}-{abs(hash(parameters))}", command=command,
        parameters=parameters, **fields,
    )


class MigrationShippedProfiles(TestCase):
    """Every parameter string core/migrations ships, with its argv."""

    def test_the_locked_ffmpeg_profiles_parameters(self):
        # core/migrations/0006's new_parameters, the locked profile's final shape.
        ref = _stream_profile_ref(
            profile("ffmpeg", "-user_agent {userAgent} -i {streamUrl} -c copy -f mpegts pipe:1"),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(
            ref["argv"],
            ["-user_agent", UA, "-i", URL, "-c", "copy", "-f", "mpegts", "pipe:1"],
        )
        self.assertEqual(ref["kind"], "transcode")

    def test_migration_0003s_original_ffmpeg_parameters(self):
        ref = _stream_profile_ref(
            profile("ffmpeg", "-i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1"),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(ref["argv"], ["-i", URL, "-c:v", "copy", "-c:a", "copy", "-f", "mpegts", "pipe:1"])

    def test_the_streamlink_profiles_parameters(self):
        # core/migrations/0011's final shape: the user agent inside a token.
        ref = _stream_profile_ref(
            profile("streamlink", "{streamUrl} --http-header User-Agent={userAgent} best --stdout"),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(ref["argv"], [URL, "--http-header", f"User-Agent={UA}", "best", "--stdout"])

    def test_the_vlc_profiles_parameters(self):
        # core/migrations/0019 and 0027: `#standard{...}` is ONE token, because
        # shlex.split runs with comments=False and braces are word characters.
        ref = _stream_profile_ref(
            profile(
                "vlc",
                "-vv -I dummy --no-video-title-show --play-and-exit --http-user-agent {userAgent} "
                "{streamUrl} --sout #standard{access=file,mux=ts,dst=-}",
            ),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(
            ref["argv"],
            ["-vv", "-I", "dummy", "--no-video-title-show", "--play-and-exit",
             "--http-user-agent", UA, URL, "--sout", "#standard{access=file,mux=ts,dst=-}"],
        )

    def test_proxy_and_redirect_carry_an_empty_list(self):
        for name in (PROXY_PROFILE_NAME, REDIRECT_PROFILE_NAME):
            row, _ = StreamProfile.objects.get_or_create(
                name=name, defaults={"command": "", "parameters": "", "locked": True}
            )
            ref = _stream_profile_ref(row, url=URL, user_agent=UA, pk=41)
            self.assertEqual(ref["argv"], [], name)
            self.assertIn(ref["kind"], ("proxy", "redirect"))


class AdversarialShapes(TestCase):
    """The shlex behaviours a Go port would have had to reproduce exactly."""

    def test_a_placeholder_inside_a_quoted_token_stays_one_token(self):
        ref = _stream_profile_ref(
            profile("ffmpeg", "-headers 'User-Agent: {userAgent}' -i {streamUrl}"),
            url=URL, user_agent=UA, pk=41,
        )
        self.assertEqual(ref["argv"], ["-headers", f"User-Agent: {UA}", "-i", URL])

    def test_a_url_with_spaces_is_substituted_after_splitting_not_before(self):
        # Substitution is per PART (core/models.py:154-158), so a URL with a
        # space stays one argument; a split-after-substitute port would
        # produce two.
        spaced = "http://p/live/a b/1.ts"
        ref = _stream_profile_ref(profile("ffmpeg", "-i {streamUrl}"), url=spaced, user_agent=UA, pk=1)
        self.assertEqual(ref["argv"], ["-i", spaced])

    def test_backslash_escapes_and_double_quote_rules(self):
        # Inside double quotes shlex honours only \\ and \" (posix mode's
        # escapedquotes); `\$` stays two characters.
        ref = _stream_profile_ref(
            profile("ffmpeg", r'-x "a\"b\\c\$d" -metadata title=a\ b'),
            url=URL, user_agent=UA, pk=1,
        )
        self.assertEqual(ref["argv"], ["-x", 'a"b\\c\\$d', "-metadata", "title=a b"])

    def test_a_hash_is_not_a_comment(self):
        ref = _stream_profile_ref(profile("ffmpeg", "-i {streamUrl} # not a comment"), url=URL, user_agent=UA, pk=1)
        self.assertEqual(ref["argv"], ["-i", URL, "#", "not", "a", "comment"])

    def test_tabs_and_newlines_split_like_spaces(self):
        ref = _stream_profile_ref(profile("ffmpeg", "-i\t{streamUrl}\n-f mpegts"), url=URL, user_agent=UA, pk=1)
        self.assertEqual(ref["argv"], ["-i", URL, "-f", "mpegts"])

    def test_unparseable_parameters_render_null_and_keep_the_rest(self):
        ref = _stream_profile_ref(profile("ffmpeg", '-i "{streamUrl}'), url=URL, user_agent=UA, pk=1)
        self.assertIsNone(ref["argv"])
        self.assertEqual(ref["command"], "ffmpeg")
        self.assertEqual(ref["kind"], "transcode")

    def test_a_blank_user_agent_substitutes_the_relays_default(self):
        # input/manager.py:73: `user_agent or Config.DEFAULT_USER_AGENT`.
        ref = _stream_profile_ref(profile("ffmpeg", "-user_agent {userAgent}"), url=URL, user_agent="", pk=1)
        self.assertEqual(ref["argv"], ["-user_agent", TSConfig.DEFAULT_USER_AGENT])
        self.assertNotEqual(TSConfig.DEFAULT_USER_AGENT, "")

    def test_channel_id_is_the_objects_pk_and_empty_without_one(self):
        # core/models.py:150: str(channel_id) if channel_id else "".
        row = profile("ffmpeg", "-metadata channel={channelId}")
        self.assertEqual(_stream_profile_ref(row, url=URL, user_agent=UA, pk=41)["argv"], ["-metadata", "channel=41"])
        self.assertEqual(_stream_profile_ref(row, url=URL, user_agent=UA, pk=None)["argv"], ["-metadata", "channel="])


class TheWire(TestCase):
    def test_the_serializer_renders_a_list_and_a_null_and_never_omits_the_key(self):
        built = StreamProfileRefSerializer(
            _stream_profile_ref(profile("ffmpeg", "-i {streamUrl}"), url=URL, user_agent=UA, pk=1)
        ).data
        self.assertEqual(built["argv"], ["-i", URL])
        broken = StreamProfileRefSerializer(
            _stream_profile_ref(profile("ffmpeg", '-i "{streamUrl}'), url=URL, user_agent=UA, pk=1)
        ).data
        self.assertIn("argv", broken)
        self.assertIsNone(broken["argv"])
        rendered = JSONRenderer().render(broken)
        self.assertIn(b'"argv": null', rendered)

    def test_the_answer_serializer_carries_argv_on_both_profile_objects(self):
        # StreamProfileRefSerializer renders stream_profile AND
        # ffmpeg_stream_profile (serializers.py:91), so one field covers both.
        from apps.proxy.serializers import SourceSerializer

        fields = SourceSerializer().fields
        self.assertIn("argv", fields["stream_profile"].fields)
        self.assertIn("argv", fields["ffmpeg_stream_profile"].fields)
```

**T4 — the existing tests and the allowlist**

Two existing tests compare `ffmpeg_stream_profile` to an exact dict and gain
the `argv` key; the value is a literal derived from the fixture's parameters
and the answer's own url, never from build_command:

apps/proxy/tests/test_next_source_resolution.py::test_the_locked_ffmpeg_profile_is_carried_when_one_exists
    parameters "-i {streamUrl} -c copy -f mpegts pipe:1" ->
        "argv": ["-i", source["url"], "-c", "copy", "-f", "mpegts", "pipe:1"],

apps/proxy/tests/test_next_source_api.py (around :323, the same assertion at the wire)
    the same key, with the fixture's parameters and `source["url"]`.

apps/proxy/tests/test_next_source_edges.py::test_an_unresolved_locked_ffmpeg_profile_is_resolved_once
    unchanged: _resolve_alternates still resolves eagerly through the module
    attribute, once (see the _resolve_alternates note in next_source_2c4.py).

apps/proxy/live_proxy/tests/zero_orm_allowlist.py, both `resolve_source` EDGE entries
    `hits` moves by the number of NEW flagged call sites in resolve_source's
    reachable subtree: _stream_profile_ref now calls profile.build_command(...),
    a model-method name the scanner flags, at ONE site. Expected 38 -> 39;
    measure it (the guard test names the number), and add a 2c-4 paragraph in
    the idiom of the 2c-1 one already there.

**T5 — `apps/proxy/tests/test_relay_list_payload_golden.py`, 2c-3's file with 2c-4's edits**

```python
"""The golden fixture for the Go relay's GET /proxy/relay/channels.

Phase 2 PR 2c-3. This file renders a payload through Django's own
RelayChannelListSerializer and pins the result to
relay/httpapi/testdata/channels_clients_all.json, which a Go test reads back.
That is the whole point: the Go encoder is compared against the OTHER
implementation, not against a Go struct literal the same PR also wrote.

WHAT THIS PINS AND WHAT IT DOES NOT. It pins the SERIALIZER -- which keys
survive, which render as null, which vanish. It does NOT drive
ChannelStatus.get_basic_channel_info, so the mapping from "the source dict set
this key inside an if" to "this key is optional" is 2c-3's reading of
apps/proxy/live_proxy/channel_status.py:469-587, not a measurement of Python's
execution. Driving the real builder would need a Redis with a channel in it,
which is a much heavier fixture for one more link in the chain; the
completeness assertion below is what stops the reading from silently narrowing
instead.

Regenerate the golden with:

    DISPATCHARR_WRITE_GOLDEN=1 python manage.py test \\
        apps.proxy.tests.test_relay_list_payload_golden
"""

import json
import os
from pathlib import Path

from django.test import SimpleTestCase
from rest_framework.renderers import JSONRenderer

from apps.proxy.relay_serializers import (
    RelayChannelListSerializer,
    RelayChannelSerializer,
)

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "relay"
    / "httpapi"
    / "testdata"
    / "channels_clients_all.json"
)

# Every RelayChannelSerializer field the Go relay does not produce yet, and
# why. A field in neither this mapping nor the fully-populated fixture channel
# fails test_the_fixture_covers_every_serializer_field, which is what stops
# the golden from silently narrowing as the endpoint grows. 2c-3 excused
# nine; 2c-4's transcode source produces seven of them (the input format
# included -- it is log_parsers.py's parse_input_format, not 2c-5's).
NOT_SERVED_YET = {
    "logo_id": (
        "ChannelMetadataField.LOGO_ID is written only into the TIMESHIFT key "
        "family (apps/timeshift/views.py:2984, timeshift:channel:<id>:metadata), "
        "never into the live:channel:<uuid>:metadata hash channel_status.py:486 "
        "reads, so the live list endpoint never emits it in Python either"
    ),
    "healthy": "needs StreamManager.healthy, which arrives in 2c-5",
}


def fixture():
    """Two channels: one with every conditional field and two clients, one with
    none and no clients. Every present/absent/null case this endpoint can
    produce is in here."""
    return {
        "count": 2,
        "channels": [
            {
                "channel_id": "11111111-1111-4111-8111-111111111111",
                "state": "active",
                "url": "http://provider.invalid/live/sub/pw/41.ts",
                "stream_profile": "1",
                "owner": None,
                "buffer_index": 120,
                "client_count": 2,
                "uptime": 30.0,
                "started_at": 1789000000.5,
                "channel_name": "BBC One HD",
                "m3u_profile_id": 3,
                "stream_id": 41,
                "stream_name": "BBC One HD (UK)",
                "total_bytes": 9999888,
                "avg_bitrate_kbps": 2665.3034666666666,
                "avg_bitrate": "2.67 Mbps",
                # The seven ffmpeg-derived fields, Phase 2 PR 2c-4: present only
                # when a transcode process reported them (channel_status.py:
                # 605-627). source_fps is a FLOAT on this endpoint and a string
                # on the detail one (parity-matrix row 14).
                "video_codec": "h264",
                "resolution": "1920x1080",
                "source_fps": 25.0,
                "ffmpeg_speed": 1.02,
                "audio_codec": "aac",
                "audio_channels": "stereo",
                "stream_type": "mpegts",
                "clients": [
                    {
                        "client_id": "client_1789000000000_1234",
                        "user_agent": "VLC/3.0.20",
                        "output_format": "mpegts",
                        "output_profile_id": 7,
                        "ip_address": "198.51.100.4",
                        "connected_at": 1789000001.25,
                        "user_id": "7",
                    },
                    {
                        # Nothing optional. user_agent and output_profile_id
                        # are assigned on every path in channel_status.py and
                        # are therefore present-as-null, not absent.
                        "client_id": "client_1789000000000_5678",
                        "user_agent": None,
                        "output_format": "mpegts",
                        "output_profile_id": None,
                    },
                ],
            },
            {
                "channel_id": "22222222-2222-4222-8222-222222222222",
                "state": "stopped",
                "url": "",
                "stream_profile": "0",
                "owner": None,
                "buffer_index": 0,
                "client_count": 0,
                "uptime": 0.0,
                "started_at": 1789000100.0,
                "clients": [],
            },
        ],
    }


def rendered():
    return JSONRenderer().render(RelayChannelListSerializer(fixture()).data)


class RelayListPayloadGoldenTests(SimpleTestCase):
    def test_the_golden_file_is_what_the_serializer_renders(self):
        payload = rendered()
        if os.environ.get("DISPATCHARR_WRITE_GOLDEN") == "1":
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_bytes(payload)
            self.skipTest(f"rewrote {GOLDEN}")

        self.assertTrue(
            GOLDEN.exists(),
            f"{GOLDEN} is missing; regenerate it with DISPATCHARR_WRITE_GOLDEN=1",
        )
        # Parsed, not byte-compared, for the same reason the Go side does:
        # nothing downstream compares bytes, and a whitespace difference
        # between two JSON writers is not a contract change.
        self.assertEqual(
            json.loads(GOLDEN.read_bytes()),
            json.loads(payload),
            "relay/httpapi/testdata/channels_clients_all.json has drifted from "
            "what RelayChannelListSerializer renders; regenerate it with "
            "DISPATCHARR_WRITE_GOLDEN=1 and read the diff before committing",
        )

    def test_the_fixture_covers_every_serializer_field(self):
        """Every declared field is exercised or explicitly excused.

        Without this, a hand-written fixture that quietly omitted a field
        would pin a payload narrower than the contract, and the Go side would
        agree with it.
        """
        declared = set(RelayChannelSerializer().fields)
        populated = set(fixture()["channels"][0])
        excused = set(NOT_SERVED_YET)

        missing = declared - populated - excused
        self.assertEqual(
            missing,
            set(),
            "these RelayChannelSerializer fields are neither in the fixture nor "
            f"in NOT_SERVED_YET with a reason: {sorted(missing)}",
        )
        stale = excused - declared
        self.assertEqual(
            stale,
            set(),
            f"NOT_SERVED_YET names fields the serializer does not declare: {sorted(stale)}",
        )

    def test_an_unset_optional_field_vanishes_rather_than_rendering_null(self):
        """The DRF behaviour the whole golden rests on.

        required=False with NO default= makes Field.get_attribute raise
        SkipField for a missing key, so the key leaves the JSON entirely. A
        default= on any of them would turn every absence into a null and change
        /proxy/ts/status and /proxy/stats/ as well.
        """
        minimal = json.loads(rendered())["channels"][1]
        for key in ("channel_name", "stream_id", "total_bytes", "avg_bitrate"):
            self.assertNotIn(key, minimal, f"{key} rendered for a channel that has none")
        for key in ("channel_id", "state", "url", "owner", "clients"):
            self.assertIn(key, minimal, f"{key} must be present on every channel")
        self.assertIsNone(minimal["owner"])
        self.assertEqual(minimal["clients"], [])
```

### Appendix U — the documents

**U1 — Amendment A4, verbatim, after A3 in the spec**

```markdown
#### Amendment A4 (2c-4) — six corrections and inputs from the ffmpeg source

**A4.1 — Django builds the argv; the relay carries no shell word splitter.
CLOSES A1.3.** A1.3 offered 2c-4 a Go port of `shlex.split` plus the three
substitutions, differential-tested against Python, or a pre-split
`stream_profile.argv_template`. 2c-4 took the contract extension and went
one step further: `stream_profile.argv` and `ffmpeg_stream_profile.argv`
carry `StreamProfile.build_command(url, user_agent, pk)` with the command
removed — built by Django for each Source's own URL, user agent and
object. A template was not enough: `{channelId}` substitutes the numeric pk
(`input/manager.py:791`'s `channel.id`), which is on no contract field, and
substitution happens per part after splitting (`core/models.py:154-158`),
so a URL with a space stays one argument. The corpus is what settles it —
`#standard{access=file,mux=ts,dst=-}` is one token, `\$` survives inside
double quotes, an unbalanced quote raises — and a second implementation of
all that is a second copy of the truth. Three states on the wire: a list
(empty for Proxy and Redirect), `null` (shlex refused the parameters; the
relay refuses that profile with 503), the key absent (an older Django; a
502 contract mismatch). `args` stays, per D5. The user agent is defaulted
on both sides the way `input/manager.py:73` defaults it, from
`DEFAULT_USER_AGENT`, which A1.4 already put on the wire.

**A4.2 — the Go credential-logging guard (#283), and a Python leak it
would have caught.** `relay/internal/credlint` type-checks the module with
`go/types` (stdlib; the gc importer resolves standard packages in ~100 ms)
and requires every error-typed argument to a formatting or logging call to
pass through `redact.Error` or carry `// credential-logging: ok - <reason>`.
Keyed on the TYPE because a provider URL reaches a Go log through one door,
an error that carries it, and 2c-2's review found the leak at the one
`*url.Error` site a name-based guard missed. Its first run reported 18
sites; two were real (`control.Unavailable.Error()`'s `%v` of the
transport error, and the request-build wrap), the rest took markers with
reasons. Stderr lines are redacted structurally by `redact.Line`, because
ffmpeg echoes the URL it was given and the HLS demuxer echoes every derived
segment URL. **The Python relay logs those same lines at INFO, unredacted**
(`input/manager.py:1094`), invisible to `scripts/check_credential_logging.py`
because the variable is named `content` — filed as an issue, recorded in
`CLAUDE.md` § Known defects, not fixed here (D10).

**A4.3 — inputs for 2c-5.** 2c-4's `TranscodeSource` ends the tune with
`channel.ErrBufferingTimeout` where `_parse_ffmpeg_stats` calls
`_try_next_stream()` (`input/manager.py:1178-1182`); `stderrReader.progress`'s
`TimedOut` arm is the one line 2c-5 replaces, and `ffmpeg.Detector.Reset` is
the successful-switch branch (`:1185-1186`) already there for it. The
`channel_buffering` (`:1217-1226`) and `channel_failover` (`:1195-1206`)
events, and `healthy`, arrive with the events route. `ffmpeg.ErrExited`
carries Python's `returncode` for row 3's connection-failure accounting.

**A4.4 — rows 5, 28 and 29 close in 2c-4 with row 4.** The nine-PR table
named only row 4. Row 5 (thresholds snapshotted at start) is
`channel.Tuning`'s two new fields and a test that changes the setting
between two tunes; row 28 (the scientific-notation under-report, #227) is
`ffmpeg/progress.go`'s regex, verbatim; row 29 (the detector is
ffmpeg-exclusive) could not fail until both architectures existed. Row 4's
Go pin is the matrix's one REAL-ffmpeg test, measured at 10.9x opening speed
and 12.2 s to arm on ffmpeg 9.0.1.

**A4.5 — `connecting` is not transcode-specific.** 2c-2's `state.go`
comment said 2c-4 would set it. `input/manager.py:1905-1963` sets it on
both paths, for the window before the ring holds `INITIAL_BEHIND_CHUNKS`
chunks; that window belongs to the promotion machinery whose one mechanism
fires on the first chunk. Declared, never entered, comment corrected.

**A4.6 — the UDP user-agent filter leaves dangling flags, reproduced and
filed.** `input/manager.py:808-812` drops every argument carrying the user
agent or `user-agent`/`user_agent`, and leaves the flags that introduced
them: `-headers 'User-Agent: X'` becomes a bare `-headers` whose value is
now `-i`. Reproduced per D5 (`TestTheUDPFilterDropsUserAgentArguments`
expects the dangling flag), filed as an issue. The Python filter also runs
over `cmd[0]`; that shape is not reproduced.
```

**U2 — `CLAUDE.md`'s two new Known-defects bullets**

§ Known defects, Security — two new bullets after the credential-logging one:

- **The Python relay logs the provider URL at INFO on every transcode tune**, through ffmpeg's own stderr: the preamble line `Input #0, mpegts, from '<url>':` reaches `logger.info(f"Stream info for channel {self.channel_id}: {content}")` at `apps/proxy/live_proxy/input/manager.py:1094` via the `'input'` keyword at `:1093`, and the HLS demuxer's `Opening '<segment url>' for reading` lines follow it. `scripts/check_credential_logging.py` cannot see it — the variable is named `content`, not for a URL. The Go relay redacts every stderr line structurally (`relay/redact.Line`) and does not reproduce this. Filed as [#NNN]; a Python-relay fix is inside the relay and stays out of Phase 2 (D10).

§ Known defects, Correctness — one new bullet:

- **The UDP user-agent filter leaves dangling flags** (`apps/proxy/live_proxy/input/manager.py:808-812`): on a `udp://` upstream every argument containing the user agent or `user-agent`/`user_agent` is dropped, and the flag that introduced it is kept, so `-headers 'User-Agent: X'` spawns as a bare `-headers` whose value becomes the next argument, `-i`. The filter also runs over `cmd[0]`, the command itself. The Go relay reproduces the dangling flag per D5 and not the `cmd[0]` case. Filed as [#NNN].
