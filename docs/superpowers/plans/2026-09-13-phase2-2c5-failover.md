# Phase 2 PR 2c-5 — the Go relay's failover and the Redirect architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Go relay **fail over**: the three triggers of parity-matrix rows 1, 2 and 3 (buffering, dead air, connect failure) drive one port of `StreamManager.run`'s two loops; a channel asks the control plane for its next source through the `next-source` client 2c-2 built, falls back to the candidate list cached at channel start when the control plane is unreachable, and never on a refusal; the chunk index is untouched by a switch; the `release` and `events` routes land, with an emitter that posts fire-and-forget and logs an outage once. Plus the **Redirect** stream-profile architecture (the 302, `validate_stream_url`'s probe, the fall-through to the cached alternates, the internal-principal override), and the **health flag** that opens the keepalive and client-timeout gates 2c-2 deferred (Amendment A2.5), with the error TS packet that amendment recorded as a divergence. Rows 1, 2, 3 and 6 get a Go column; row 7 gains a pin across a switch; row 5 keeps 2c-4's.

**Architecture:** `channel.Channel.run` becomes the supervisor `StreamManager.run` is: an outer loop over sources bounded by `MAX_STREAM_SWITCHES`, an inner loop over attempts bounded by `MAX_RETRIES`, one `Source.Run` per attempt under a context the health monitor and the stderr reader can cancel. A `Resolver` interface is how the channel asks for its next source, implemented in `httpapi` over `control.Client` because that is where the candidate cache and the Unavailable-versus-Refused distinction live; an `EventSink` interface is how it reports, adapted to `control.Emitter` in `httpapi` so `channel` keeps not importing the wire package. The transcode source's `TimedOut` arm — the one line Amendment A4.3 named — calls the channel's failover from the stderr goroutine, as `_parse_ffmpeg_stats` does from its thread. `startTune` grows a Redirect branch that returns a 302 as an error out of the start function, so `Manager.Attach` never publishes a channel for it — which is what Python does too, and Ruling R7 proves.

**This PR stays inert in every deployment**: every route is behind 2c-1's dev flag, and nginx routes nothing to port 5658 until stage 2d.

**Tech Stack:** Go 1.27.1, standard library only; Django on one Python test file.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — D1, D2, D5, D7; the 2c-5 row of the nine-PR table (~line 1804, as 2c-4 amended it); § Error handling per hop (~841, the corrected table); Amendments A1.2 (Redirect has no owning PR but this one), A1.4 (settings off the wire), A2.1 (`next-source` landed in 2c-2), A2.5 (the health flag, the keepalive, the client timeout, the error packets), A3 as renumbered on `main`, and A4 as 2c-4 lands it (A4.3 is this PR's brief in the spec's own words). This plan amends the spec in Task 7 where its text is factually wrong or silent, and says so in the Done log.

---

## Sequencing: this plan sits on 2c-4 as merged at `d92b33be`, and was re-seeded from that tree

2c-4's plan is on `main` at `97a5457a` (PR #294, `docs/superpowers/plans/2026-09-13-phase2-2c4-ffmpeg.md`) and its implementation, PR #298 on `migration/phase2c-ffmpeg`, squash-merged as **`d92b33be`** (`git diff --quiet 823cac44 d92b33be` is empty: tree-identical to the final branch head). **Every appendix in this plan was built and verified on `d92b33be`'s `relay/`, every `_test.go` included, taken with `git archive d92b33be relay`.** It was not always so, and the history is stated: the first draft was built on `main` at `29224271` (2c-3) with 2c-4's plan appendices applied from `b0a323fe`, because 2c-4's implementation was unreachable then; it was re-checked against the plan's `97a5457a` appendices (four deltas, none in a file this plan changes); and when 2c-4 merged, the merged tree was diffed byte for byte against that seed. **The result: identical for every file this plan edits or calls into.** The merge differs from the seed in exactly four files — `ffmpeg/procgone_test.go` (a zombie-aware `processGone`), `ffmpeg/spawn_linux_test.go` (an `_ *testing.T`), the Django-regenerated `channels_clients_all.json` (semantically identical to the hand-written one, compact spelling), and `main.go` (a comparison artefact: the appendix set carried only its two marker lines) — and this plan takes all four from the tree. Task 0 remains the check that the tree you execute against IS `d92b33be`.

**Task 0 is the diff, and its stop rule is binding.** A symbol that differs from the ledger below is a **stop-and-report**, never a reconciliation in passing. The shapes this plan depends on most, with what changes if your tree differs from `d92b33be`:

| 2c-4 shape this plan builds on | Where 2c-5 touches it | If your tree differs |
|---|---|---|
| `channel.Started{Source, Tuning, Info}`; `Manager.Attach(id, *Client, func() (Started, error))` | Task 2 adds `Resolver` to `Started`; nothing else about `Attach` moves | a different `Started` moves Tasks 2 and 3 — stop and report |
| `channel.Tuning` with six fields ending `BufferingTimeout`; `httpapi.tuningFrom` reading eight keys | Task 2 adds ten fields; Task 3 reads eleven more keys | a seventh field on `Tuning` or a ninth key in `tuningFrom` means 2c-4 read something this plan does not know about — stop |
| `channel.TranscodeSource` with `attach`, `fail`, `failure`, a `stderrReader` whose `progress` has a five-arm `switch` on `detector.Observe`, and `ErrBufferingTimeout` | Task 2 replaces the `TimedOut` arm, deletes `ErrBufferingTimeout`, resets `cause` at the top of `Run`, and raises `channel_buffering` on `Started` | Appendix N is the whole file after; diff it against yours rather than applying it blind |
| `ffmpeg.Detector{Threshold, Timeout, Now}` with `Observe`, `Buffering`, `Reset`, unexported `since` | Task 2 adds `BufferingFor` | a renamed field is a one-line edit; a missing `Reset` is a stop |
| `httpapi.startTune(parent, client, id)`, `transcodeSource`, `writeTuneFailure`'s nine arms, `ErrUnservedKind`, `ErrNoFFmpegProfile`, `serveClient` with no keepalive, `channelPayload` with 23 fields | Task 3 reshapes `startTune`, Task 4 adds the Redirect branch and an arm, Task 5 rewrites `serveClient` and adds a field | Appendix P is the whole `stream.go`; a renamed helper is a find-and-replace, a missing one a stop |
| `relaytest.ControlPlaneConfig` with fifteen fields ending `BlankUserAgent`, `SetSettings`, `RecordedRequest{Method, Path, Header, Body}`, `EffectiveProxySettings()` with fourteen keys | Task 1 adds two fields, three mutators, event recording, route dispatch and six keys | Appendix E is the whole file after |
| `relaytest.Config` with `DeadAir`; `Upstream` with `Requests`, `Headers`, and a rate throttle that sleeps `min(wait, 250ms)` once (issue #300) | Task 1 adds `DeadAirAfterBytes` and `Methods` and fixes #300 | Appendix F |
| `httpapi/stream_test.go`'s `rig{Relay, Upstream, Control, Manager}`, `newRig`, `tune`; `fanout_test.go`'s `fanRig`, `fanRigWith`, `rigSettings`, `tuneAs`, `listChannels`, `waitForHead`, `packetRun`; `transcode_test.go`'s `transcodeRig`, `waitForStats`, `listedChannel` | Tasks 3–5 add a field, a constructor and three test files that call all of them | a renamed helper is a find-and-replace in Appendices S–W |
| `channel/source_transcode_test.go`'s `standInSource`, `transcodeTuning`, `assetFile`, `captureLog`, `attachTranscode`, `waitFor`; `manager_test.go`'s `testTuning`, `asStarted`, `testClient`, `int32Counter` | Task 2 edits `testTuning` and three tests and adds a file that calls the rest | Appendices O, R and AF |
| `apps/proxy/tests/test_relay_list_payload_golden.py` with `NOT_SERVED_YET = {"logo_id": …, "healthy": …}` | Task 5 removes `healthy` and adds it to the fixture | if `healthy` is not in `NOT_SERVED_YET`, 2c-4 shipped it and Task 5's Python half is a no-op — say so |
| Amendment **A4** in the spec, with A4.3 naming this PR's inputs | Task 7 appends A5 after it | if A4 is numbered differently on `main`, cite the spec's number |

**Ruled, and binding on every task below: 2c-5 adds no third writer of `StateActive`.** `promoteOnFirstChunk` stays the one promotion mechanism, and 2c-4's guarded recovery edge in `stats.go`'s `reportBuffering` stays the only other write. The buffering-triggered switch moves the channel out of `buffering` by calling `reportBuffering(false)` — the existing writer, not a new one — because that is what `_parse_ffmpeg_stats`'s `hset ACTIVE` after a successful switch is (`input/manager.py:1195-1197`). Task 0 counts two, Task 8 counts two, and both name the lines.

**Seed your scratch module from the merged tree INCLUDING its `_test.go` files** — 2c-3's rule, unchanged; this plan's own seed is exactly that tree.

**Amendment numbering.** Where this plan says "Amendment A3" or "A4" it means the spec's own section as it stands on `main`. The 2c-3 plan carries stale sub-numbers at its `:1345`, `:1369` and `:1458`; the 2c-4 plan's Appendix U1 is A4's text as proposed and may have been renumbered in its fix round. Cite the spec, never a plan, for a sub-number.

---

## Global Constraints

Every task's requirements implicitly include this section. Constraints 1–26 are 2c-1's through 2c-4's, restated because this plan is executed by an agent who has not read them; 27–35 are new, the last two being lessons 2c-4's own fix round paid for.

1. **Anchor every command with an absolute path, or open it with a `cd` into your own worktree.** The shell's working directory has been observed drifting into another agent's worktree with no `cd` issued.

2. **`go test -race` is mandatory on every Go test run: locally, in the hook, in the commit gate, in CI.** This PR adds a health-monitor goroutine that reads what the source goroutine writes, a stderr goroutine that adopts a source the run goroutine then reads, and an emitter goroutine behind every event. Every one of them is a race the detector can see.

3. **Standard library only. No `require` line, no `go.sum`, ever.** `scripts/check_go_stdlib_only.sh` is the mechanical check. Everything here is in `net/http`, `context`, `sync`, `time`, `encoding/json`, `sort`, `strings`, `io`, `net`, `errors`, `fmt`, `log/slog`.

4. **Nothing in `relay/` may open a Postgres connection or a Redis connection, in any task, including a test.** The degraded-fallback cache is a slice on a struct, not a key. The brief says a plan that needs either is a STOP, not an amendment; this plan needs neither, and Ruling R9 is where the one place that could have (the #190 `hdel`s) is shown not to.

5. **Every pin is tool-resolved on the day the PR is opened, never copied from this plan.** This PR adds no pin.

6. **zizmor blocks on every finding in any workflow file you touch.** This PR touches no workflow.

7. **Do not add a Docker `HEALTHCHECK`, a SIGTERM drain, or a `/readyz` that reports anything real.** Those are 2c-8's. `control.Emitter.Close` exists so the drain can call it; nothing calls it in this PR except tests.

8. **Every Go constant that mirrors a Python literal carries its source `file:line` in a comment and is pinned by a test naming the same location.** This PR adds five in `channel/failover.go` — `retryBackoffStep`, `retryBackoffCap` (`input/manager.py:557`), `maxUnhealthyChecks` (`:1556`), `healthActionCooldown` (`:1557`), `stableReconnectAfter` (`:1580`) — pinned by `TestTheFailoverLiteralsMatchPython`; three in `httpapi` — `keepaliveAfterEmptyReads` (`output/ts/generator.py:546`), `probeTimeout` (`views.py:480`), `probeChunk` (`url_utils.py:200`), `probeRedirectLimit` (requests' default); and `control.MaxEventsPerBatch` (`serializers.py:272`), pinned by `TestABatchOverTheRoutesLimitIsRefusedLocally`. Every threshold comes off the wire (Constraint 13).

9. **Prefer `t.Setenv` over manual environment save/restore, and never run an environment-mutating test with `t.Parallel()`.**

10. **Only Task 5's Python half needs the shared `dispatcharr-testrunner` container** — one test module, `apps.proxy.tests.test_relay_list_payload_golden`, plus the golden regeneration on the host with `TEST_USE_SQLITE=1`. Before Task 5's Python edit:

    ```bash
    docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
    ```

    If it is not your worktree, re-point it with `.claude/hooks/start-test-container.sh` — **after** checking nobody else is mid-task in the tree it currently holds (`docker ps`, and `stat -f '%Sm %N'` on that tree's recently-touched files; a modification younger than a few minutes means occupied). Every other task runs on the host.

11. **Stage and commit in separate Bash calls, and write commit messages to a file and use `-F`.**

12. **A provider URL is a credential and never reaches a log, an error message or a public response body.** This PR puts a URL into two new places: an event's `details` (`stream_switch`'s `new_url`, `channel_error`'s `url`) and the Redirect `Location` header. The first goes through `redact.Line` and is cut at 100 characters (Ruling R10); the second is the whole point of the architecture and is what Python sends (`views.py:540`).

13. **A control-plane setting is read from the wire or the tune fails. Never from a Go-side default.** This PR adds eleven required keys — `CONNECTION_TIMEOUT`, `HEALTH_CHECK_INTERVAL`, `channel_init_grace_period`, `MAX_RETRIES`, `RETRY_WINDOW_SECONDS`, `STABLE_CONNECTION_THRESHOLD`, `MAX_STREAM_SWITCHES`, `STREAM_TIMEOUT`, `FAILOVER_GRACE_PERIOD`, `KEEPALIVE_INTERVAL`, `MAX_KEEPALIVE_DURATION` — and the per-key test grows by eleven subtests. **All eleven are read on every tune, Redirect tunes included**, for 2c-4's reason: a key read only on the path that consults it leaves the per-key test green against a rig that never takes that path.

14. **Parity is against the code, not against the summary.** Every behavioural claim here carries a `file:line`. Six places where reading the source changed this plan: a clean upstream EOF is a **retried connection failure**, not the stream ending (`input/manager.py:1870-1875` then `:555-563`; 2c-2's `TestACleanUpstreamEndClosesTheRing` was pinning the pre-loop shape and is reshaped in Task 2); a health-requested switch records **no** failure (`:505-507` breaks before `:534`); `_note_stable_connection` resets the tried set but **not** the failure counter (`:199-204`); the buffering-timeout branch, on failure, **asks again on the next record** (`:1210`); `validate_stream_url` returns the URL it was **given**, not the redirect target (`url_utils.py:183`, `:250`); and `release_source` on the Redirect path runs only when the tune reserved a slot (`views.py:516-517`).

15. **Decide every lint finding in this plan, and re-lint after every `#nosec`.** This PR adds **no suppression**: four findings on the first lint (an ineffectual assignment, two unused parameters, a De Morgan simplification) were fixed rather than suppressed, and the eight 2c-4 carries are untouched. Task 8 Step 6 lists them as zero new.

16. **Run the four checks after every task, from the module root**, and treat any of the four failing as a stop:

    ```bash
    cd <your worktree>/relay && gofmt -l . && go build ./... && go vet ./... && GOOS=linux go vet ./... && GOOS=darwin go vet ./... && go test -race ./... && golangci-lint run ./... && GOOS=linux golangci-lint run ./... && GOOS=darwin golangci-lint run ./...
    ```

    `gofmt -l .` must print nothing. **Vet and lint run three times, under the native, `linux` and `darwin` GOOS** (Constraint 35).

17. **An ordering bug is not a data race, and `-race` is silent on every one of them.** This PR's instructive one: `TestTwoClientsShareOneSource` asserted the source ran once and released the channel immediately after `Attach`; the supervisor loop's first attempt now starts a few statements later than 2c-2's bare `source.Run`, and the release arrived first — zero runs, a green detector, a red test. Task 2 waits for the run before releasing.

18. **One mechanism per invariant.** The buffering-triggered switch's `active` write is the existing recovery edge, not a new one (§ Sequencing).

19. **The borrowed-slice contract is asserted, not enforced.** `dataClock` hands every write straight to the ring and holds nothing.

20. **Do not widen the endpoint.** `GET /proxy/relay/channels` gains one **field** (`healthy`) and no route. The single-channel `GET`/`DELETE`, the client `DELETE` and `advance` are 2c-8's.

21. **Every error-typed argument to a formatting or logging call in `relay/` passes through `redact.Error`, or carries `// credential-logging: ok - <reason>`.** `scripts/check_go_credential_logging.sh` reports the module clean at zero findings after this PR; the two markers this PR adds are both on `encoding/json` errors over request bodies (`control/release.go:40`, `control/events.go:56`).

22. **Every line the stand-in writes to stderr came out of a real ffmpeg**, or is declared where it is written with the reason. This PR adds no stderr line: rows 1 and 6 replay the captures 2c-4 uses, and their alternate child is **silent** on stderr, for a reason Task 2 states.

23. **The real-ffmpeg test fails rather than skips when `CI` is set and ffmpeg is absent.** Unchanged; Task 2 edits its tuning to build on `testTuning()` (Constraint 27) and nothing else.

24. **`Pdeathsig` is Linux-only by build tag, and its pin runs on Linux.** Unchanged.

25. **The stand-in is the test binary re-executed, and the trampoline is one per package.** Unchanged; this PR's transcode tests use `--dead-air-after-bytes` to keep a silent child alive.

26. **The `Pdeathsig` and SIGKILL tests assert a mechanism, not an outcome.** Unchanged.

27. **A test's `Tuning` is built on `testTuning()` or `transcodeTuning()`, never as a bare literal.** `MAX_RETRIES` is on `Tuning` now, and a literal that omits it is a channel that **never connects** — `retry_count < 0` is false on the first pass, which is exactly what Python does with `MAX_RETRIES = 0` and exactly what a test author does not intend. The real-ffmpeg test failed this way before Task 2 rebuilt its tuning: ninety seconds waiting for a detector on a source that never ran. A test whose subject is one threshold overrides that one field. The check: `grep -rn 'Tuning{' relay --include='*_test.go'` prints exactly one hit, `testTuning()`'s own literal.

28. **A test that measures a timeout takes its clock BEFORE the thing it measures starts.** Row 1's pin takes `started` before `Attach`; row 2's reads the source's own last-write time and the resolver's own call time, both recorded by the parties themselves. The 2c-4 review's 2-in-8 flake is the reason.

29. **The health monitor's compressed thresholds are on the wire, never patched.** `CONNECTION_TIMEOUT: 0.3` and `HEALTH_CHECK_INTERVAL: 0.05` come through `rigSettings` and `Tuning` exactly as an operator's values would; no test reaches into a running channel to shorten a wait.

30. **A break-check that reddens on a different clause than predicted is recorded with the clause that fired.** Row 2's did (§ Break-check, row 1): the sibling assertion caught the injected edit first. The mechanism was still the one under test; the table says which assertion spoke.

31. **Widen a sample window, never lower an asserted count.** The keepalive test asserts at least five null packets in an eight-second window at a 50 ms interval; if it reports fewer on a slow host, the window grows.

32. **Every event this relay raises is one Python raises, with the same `type` and the same `details` keys.** The vocabulary is `core/models.py`'s `SystemEvent.EVENT_TYPES`; an unknown type is rejected by `core/relay_events.py:apply_event_batch` and counted, not raised, so a misspelling would be a silent loss. This PR raises exactly five types: `channel_buffering`, `channel_failover`, `stream_switch`, `channel_reconnect` (one shape, `attempt`/`max_attempts`; the `reason: health_monitor` shape lives inside the unreachable `_attempt_reconnect`, R4) and `channel_error` (`error_type: connection_failed`, `reason: degraded_failover`), and nothing else — `channel_start`, `channel_stop`, `client_connect` and `client_disconnect` are the tune and stop paths' and are 2c-8's (Ruling R11).

33. **The fake control plane is one server answering three routes by path suffix**, and a test that asserts a request count names the route (`RequestsTo("/next-source")`), because the release on teardown and the event batches now share the log.

34. **A test proving a process died uses the zombie-aware probe, and the Go CI job runs in a container with `--init`.** 2c-4's fix round found `processGone` reading a killed child as alive because nothing had reaped it: in the base image there is no init to adopt orphans, so a dead child sits in `/proc` as state `Z` until its parent waits. The merged `ffmpeg/procgone_test.go` checks the `/proc` state and falls back to `kill(0)`, and `go-tests.yml` runs the build job with `--entrypoint "" --init`. This PR adds no process-death test; any later one reuses `processGone` and never a bare `kill(0)`.

35. **Every gate list carries the three-GOOS vet and lint.** Build-tagged files are invisible to one OS's lint: `ffmpeg/spawn_linux.go` and `spawn_linux_test.go` compile only under `GOOS=linux`, `spawn_other.go` only elsewhere, and a native darwin run type-checks neither Linux half. The hook, `go-tests.yml` and Task 8 all run vet and lint under the native, `linux` and `darwin` GOOS; this plan's own gate did too, and its numbers below are from that shape.

### The six ways a Go test can be green and meaningless

Every test this PR adds is bound by all six, and every task that adds an assertion ends with a **break-check**: patch the defect in, watch the test go red *for the right reason*, revert. **A break-check that does not go red is a finding, not a formality** — one of this plan's twenty did not (§ Break-check, row 20), and it is listed as an unpinned edit rather than hidden.

1. **The tautological oracle.** Every expected value is a literal or a Python line: `"Connection failed after 3 attempts"` and `"All 1 stream options failed"` are `input/manager.py:679-682`'s strings; the failure-window test's clock values are the row's own Notes; the keepalive packet's four header bytes are `utils.py:82-90`'s.

2. **A pin that supplies the default pins nothing.** Row 2 runs at `CONNECTION_TIMEOUT` 300 ms and `HEALTH_CHECK_INTERVAL` 50 ms; row 6 at `MAX_STREAM_SWITCHES` **0**; the keepalive tests at `KEEPALIVE_INTERVAL` 50 ms and `MAX_KEEPALIVE_DURATION` 0.5 s; the budget test at a 300 ms transport timeout. `testTuning()` carries the production values so that a test which does NOT override one runs the real shape (Constraint 27).

3. **A test can go hollow without changing.** Every break-check below names the edit and the message that appeared.

4. **A fixture that patches away the subject.** The channel-package tests use fake *sources* (a 404, a dead-air writer, a flowing writer) and a fake *resolver*, because the loop is the subject; the httpapi tests use the real fake control plane over HTTP and real fake upstreams, because the disposition table and the probe are the subject. Nothing reaches into a channel except `State()`, `Err()`, `Source()`, `Healthy()`, `Ring()`.

5. **A substring assertion pins nothing when the string has more than one source.** `ErrNoAlternate`, `*ErrSourcesExhausted`, `ErrRedirectValidationFailed`, `*redirectAnswer` are all named. The two message assertions are on a credential's absence, and the secret (`hunter2`) has exactly one source, the test's own URL.

6. **A true positive for a false reason.** Row 2's dead-air pin asserts the gap between the last byte and the resolver's call, not merely that a switch happened — a monitor that acted on the first inactive check would switch too, sooner. Row 6's pin has a sibling proving the same bound DOES stop a main-loop switch, so the asymmetry is pinned rather than the absence of a bound.

### Working rules

- Run the four checks after every task (Constraint 16), then `scripts/check_go_credential_logging.sh relay` (Constraint 21). **Run `relay/channel` at least eight times consecutively under `-race` before Task 2 is committed**: it holds four timing-shaped tests (rows 1, 2, 6 and the health restoration).
- Stage and commit in separate Bash calls; write commit messages to a file and use `-F`.
- Every commit message ends with the attribution lines this session was given.
- **Every Go file in this plan has been built, vetted and linted under three GOOS values at zero findings, race-tested and run without the race detector before this plan was written**, in a scratch module seeded from `d92b33be` as § Sequencing describes: `go test -race ./...` three times, `./channel` eight times consecutively, `./ffmpeg ./channel` without `-race` three times, credlint clean, stdlib only, no `go.sum`. Where you find a discrepancy, your tree is the fact and this plan is the claim — **stop and report it** (Task 0 Step 0).

---

## Rulings

Decisions this plan makes that the spec leaves open, that 2c-4 left to its successor, or that the tree contradicts. Each is binding; each names what it was decided against.

### R1 — A clean upstream EOF is a connection failure, retried and counted. 2c-2's pin of the opposite is reshaped, not kept.

`fetch_chunk` reads an empty chunk as "Server closed connection" (`input/manager.py:1870-1875`), `_process_stream_data` returns, and `run`'s retry loop records a failure and reconnects with backoff (`:555-563`) — three times, then the source is exhausted (`:534-537`, row 3). A transcode child that exits 0 after copying its input takes the same path. 2c-2 ended the channel in `stopped` on the first EOF and pinned it (`TestACleanUpstreamEndClosesTheRing`), which was the honest shape before there was a loop; 2c-4's `channel.go` comment said as much ("the failover that would try the next candidate instead is parity-matrix rows 1-3 and 2c-5's"). **Ruled: the loop is ported whole and the test becomes `TestACleanUpstreamEndIsRetriedAndThenExhaustsTheSource`** — three requests at the provider, `error` with "Connection failed after 3 attempts", the ring closed. Four other 2c-2/2c-4 tests change their expected attempt count and nothing else (Task 2 Step 2, Task 3 Step 3). Decided against a `Tuning.MaxRetries` of one for the old tests: a test that keeps its old assertion by supplying the number that makes it true is hollow shape 2.

### R2 — The Resolver is an interface in `channel`; its implementation and the degraded fallback live in `httpapi`. `channel` still does not import `control`.

`_try_next_stream` (`input/manager.py:2041-2225`) does two things: asks Django (`:2076-2082`) and, on `ControlPlaneUnavailable`, picks from the cached list (`:2099-2107`); then swaps the URL, clears the failure history, resets the packetiser, raises `stream_switch` and does the degraded bookkeeping. The first half is wire-shaped — it needs the candidate list the initial answer carried, and the Unavailable/Refused distinction the wire client makes — and the second half is channel state. **Ruled: `channel.Resolver.Next(ctx, NextRequest) (Resolved, error)`, with `Resolved{Source, Info, Degraded}`; `httpapi.resolver` implements it over `control.Client` and holds `answer.Alternates`; `channel.failover` does the second half.** The channel-package tests drive the loop with a scripted resolver; the httpapi tests drive the disposition with a real fake control plane. Decided against `channel` importing `control` for `control.Source`: 2c-2's `tuning.go` made "this package never imports the wire package" a property, and this plan keeps it at the cost of one ten-line adapter (`httpapi.EventSink`).

### R3 — The health monitor cancels the running attempt; Python's loop notices its flag up to `CHUNK_TIMEOUT` later. A divergence in the safe direction, and `CHUNK_TIMEOUT` is not read.

`_monitor_health` sets `needs_stream_switch` (`:1587-1590`) and the main loop checks it between `fetch_chunk` calls (`:1364-1365`), each of which blocks up to `CHUNK_TIMEOUT` (5 s) in `select` on a silent pipe (`:1845`) — the Python pin for row 2 measured 5.47 s of that wait. **Ruled: `monitorHealth` sets the same flag and calls `cancelAttempt`, so `Source.Run` returns at once** and the loop acts on the flag. Nothing a client can observe gets slower; `CHUNK_TIMEOUT` has no reader here and is not on `Tuning`. Decided against a per-read timeout in the sources to reproduce the delay: it would reproduce a wait, not a behaviour.

### R4 — The live reconnect path is the inner loop's fall-through (`:521-534`); the outer loop's `_attempt_reconnect` branch is unreachable and is not ported. Found by the reviewer, against a shape that had ported the dead branch.

`_monitor_health` sets `needs_reconnect` only while the stream is connected (`:1565`, `:1583`). While connected, the main loop is inside `_process_stream_data`, whose loop condition includes `not self.needs_reconnect` (`:1364-1365`), so it returns; the inner retry loop then clears the flag (`:527`), closes the socket (`:531`) and **falls through to the failure accounting** (`:533-534`) — "Repeated health reconnects count toward max_retries like any other URL failure" — and the next attempt on the same URL is the reconnect. The outer loop's `_attempt_reconnect` branch (`:414-426`) is checked only at the top of the outer loop, which is reached after the inner loop ends with the flag already cleared and the stream disconnected; nothing sets it between. **Ruled: `run` takes the flag inside the inner loop after `runAttempt` and falls through to the failure accounting, exactly `:521-534`; the outer branch and its `channel_reconnect{reason: health_monitor}` (`:1655-1662`, inside the dead `_attempt_reconnect`) are not ported.** This plan's first draft did the opposite — took the flag at the outer top and judged a reconnect by a delivered byte — and the reviewer reproduced the consequence with an injected clock: after the first reconnect the flag stayed set, the monitor's own `if not self.needs_reconnect` guard (`:1581`) never cancelled again, and a second stall on the same stable stream was logged and never acted on. `TestASecondStableStallIsActedOnAfterAHealthReconnect` drives two stable stalls with an injected clock and expects three runs; its failure message names the stale flag (break-check row 23). The stable literal itself (`stableReconnectAfter`, `:1580`) stays pinned as a decision by `healthActionFor`.

### R5 — `channel_reconnect` on a retry is raised as the attempt starts, not once it is established.

`:486-496` raises it after `connection_result` is True. For the Proxy architecture that moment is "the reader thread started", which never fails; for transcode it is "the spawn succeeded". A Source has neither. **Ruled: raised at the start of every attempt after the first**, carrying `attempt` and `max_attempts`. The one divergence: a transcode spawn that fails at once (a missing command) will have announced a reconnect it never made. Stated in the PR description; a sixth `Source` method to report establishment was decided against, since 2c-2's R6 keeps the interface at one method and this is the only consumer.

### R6 — The buffering-triggered switch runs on the stderr goroutine, parks the new source, and cancels its own attempt. The main loop never counts it. (Rows 1 and 6.)

`_parse_ffmpeg_stats` calls `_try_next_stream()` from the stderr thread (`:1178-1182`); `update_url` kills the process the thread is reading (`:1483`), so the thread ends with it; the switch never touches `stream_switch_attempts` (row 6, #221). **Ruled: `stderrReader.progress`'s `TimedOut` arm calls `Channel.failoverFromBuffering`, which resolves synchronously, parks the `Resolved` in `c.pending`, calls `reportBuffering(false)`, raises `channel_failover{reason: buffering_timeout, duration}`, and cancels the attempt; `run` adopts `pending` without incrementing `switches`.** `TranscodeSource.Run` already waits for its stderr reader before returning, so the adoption cannot race the reader. On failure Python stays buffering and asks again on the very next progress record (`:1210`) — one control-plane call per record, reproduced (`TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord`) and **filed as an issue** in Task 7, because it is a Python defect the port must carry (D5), not one to fix in transit. `Detector.Reset` is called on success for fidelity (A4.3's "successful-switch branch"); the process is about to die, so nothing observes it.

### R7 — A Redirect tune publishes no channel: the 302 is an error out of the start function, and Python renders nothing for it either.

`stream_ts`'s Redirect branch (`views.py:468-547`) returns before `ChannelService.initialize_channel` (`:578`), which is the only writer of the `live:channel:<uuid>:metadata` hash `build_live_channel_stats_data` renders; `views.py` performs no `hset`/`set`/`sadd` of its own before that point (grepped: none), and the ownership key `try_acquire_ownership` took is released by the `finally` at `:645-648` that the redirect `return` passes through. What a Redirect tune leaves in Redis is Django's own `channel_stream:`/`stream_profile:` keys, released a moment later, and `channel_source_cache` with a TTL, which nothing renders. So the list endpoint shows **nothing** for a Redirect channel in Python, and the Go relay must show nothing too. **Ruled: `startTune` returns `*redirectAnswer` (an `error`) for a Redirect kind; `Manager.Attach` treats it as a failed start — gate released, no channel — and `StreamHandler` writes the `Location` and the status.** Pinned by `TestARedirectProfileHandsTheClientTheProviderURLAndFetchesNothing`, which asserts `Manager.Get` is nil and the list has `count: 0` after a 302. A concurrent second client on a Redirect channel waits on the gate and then makes its own probe and gets its own 302; Python's follower would wait `CLIENT_WAIT_TIMEOUT` for an initialisation that never comes — an edge where Go is strictly kinder, stated. **The Python harness proof was not run** (this plan had no container and no Django); the reading above is static, and Task 4 Step 5 names the one-test harness check an implementer can run to confirm it.

### R8 — The internal-principal override is `control.IsInternalPrincipal` on the request's own static header, not trust-gated.

`decision.is_internal` (`views.py:461`) is `request_is_internal(request)` (`authorize_views.py:177`), the static `X-Dispatcharr-Internal` token that the DVR's fetch carries with no bound counterpart (`internal_auth.py:45-49`). nginx does not blank it on relay-bound locations (only the trust marker and the four `X-Relay-*` are overridden), so the relay sees what the DVR sent. **Ruled: `identify`'s caller reads it with `IsInternalPrincipal(secret, …)` and passes `internal` into `startTune`, which reads the Redirect kind as Proxy from that point — force-ffmpeg included, because `transcode = False` there (`:467`) and `run` re-evaluates the URL's stream type on every pass.** A forged header answers the ordinary 302 (pinned in the same test).

### R9 — The `hdel`s of #190 have no Go analogue and 2c-5 needs no Redis read. `Release` is called once per channel by construction.

`CLAUDE.md` § Known defects records that `Channel.release_stream()` `hdel`s `STREAM_ID`/`M3U_PROFILE` from the relay's metadata hash "so a duplicate release can't `DECR` the provider counter twice", and asks whether 2c-5 is where they move. The relay's hash does not exist under the Go relay, so Django's `hdel` becomes a no-op against it and the *Python* relay still needs it until 2d; the property it protects — one release per channel — is met here structurally: `Channel.run`'s deferred `releaseSlot` is the only caller, and `run` exits once. **Ruled: nothing moves in this PR, no Redis read is needed, no STOP.** The two Django-side reads (`release_stream()`'s recovery branch and `_release_stale_stream_assignment()`) are fallbacks taken only when Django's own `stream_profile:` key is already gone (`apps/channels/models.py:501-542`), and under the Go relay they find nothing and warn "profile_connections may leak" — the same corner Python already documents, now reachable one way rather than two. Recorded in Amendment A5.4 as an input for 2d, where the hash is deleted for good. `channel_pk` is sent as `null`: it is on no contract field, and Django uses it only in that same fallback (Ruling in `control/release.go`'s comment).

### R10 — `stream_switch`'s `new_url` goes through `redact.Line`, which keeps less than Python's `redact_url`. A stated divergence in the safe direction.

`update_url` puts `redact_url(new_url)[:100]` in the event's details (`:1523-1532`); `redact_url` masks userinfo, the Xtream path segments and the sensitive query keys and leaves the rest (`dispatcharr/utils.py:180-216`). `redact.Line` keeps scheme and host and replaces everything after with `[redacted]`. The WebSocket push drops `details` entirely (`core/relay_events.py:_WS_FIELDS`), so a browser sees neither; the `SystemEvent` row sees the redacted form. **Ruled: `redact.Line`, cut at 100** — one redactor for the module (2c-4's R7), and a row carrying `http://host/[redacted]` where Python's carries `http://host/live/***/***/1.ts` is a difference in the direction the credential rule points. `channel_error`'s `url` is the same.

### R11 — The events client lands with the five types the failover machinery raises; the four the tune and stop paths raise are 2c-8's.

`input/manager.py` raises `channel_buffering`, `channel_failover`, `stream_switch`, `channel_reconnect` (`:486-496`; the second shape at `:1655-1662` is inside the unreachable `_attempt_reconnect`, R4) and `channel_error` (`connection_failed`, `connection_exception`, `degraded_failover`). `channel_start`, `channel_stop`, `client_connect` and `client_disconnect` are raised from `views.py`, `server.py` and `output/ts/generator.py:130-141` — the tune path and the coordinated stop, which 2c-8 owns with the control routes. **Ruled: this PR raises the manager's five and no other**; `connection_exception` is not reachable (a Go `Source.Run` returns an error rather than raising, and every error is the `connection_failed` shape). Recorded in Amendment A5.3 as 2c-8's input so the four are not lost between rows.

### R12 — The emitter is one worker and a bounded queue, batching what has queued; Python spawns a greenlet per event. Events raised during an outage are lost, not queued for retry.

`emit_event` spawns `post_events` on a greenlet per event (`control_plane.py:317-345`); a slow control plane accumulates one blocked greenlet per transition. **Ruled: `control.Emitter` — a 1024-deep channel, one goroutine, batches of up to `MaxEventsPerBatch` (200, the route's `max_length`), order preserved, a full queue dropping the newest with a warning.** The `_events_down` flag is ported per emitter with its once-per-transition logging (pinned); a failed batch is not retried beyond the client's one retry, so an event raised during an outage is lost exactly as `CLAUDE.md` § Operationally records. Decided against a goroutine per event: it reproduces a resource shape, not a behaviour, and the batch limit is a contract the route enforces.

### R13 — Every failover threshold is on `Tuning`, ten new fields; `URL_SWITCH_TIMEOUT`, `CHUNK_TIMEOUT` and `RETRY_WAIT_INTERVAL` are not read.

`URL_SWITCH_TIMEOUT` (`:408-412`) resets a `url_switching` flag that got stuck; the Go switch is synchronous and cannot stick. `CHUNK_TIMEOUT` is R3's. `RETRY_WAIT_INTERVAL` has an accessor (`config_helper.py:94-96`) and no caller — the backoff is the `.25 * failures` literal. **Ruled: not read, not on `Tuning`, stated here.** The three client-loop keys A2.5 named arrive as `ClientTimeout` (the sum `_is_timeout` computes from two keys, `output/ts/generator.py:585-587`), `KeepaliveInterval` and `MaxKeepalive`.

### R14 — The `_is_timeout` disconnect is ported as the condition Python evaluates minus its `url_switching` exemption, and pinned through the keepalive cap, because on the TS path the cap is the exit a client can reach.

Row 12's Notes already record it: the keepalive path refreshes `last_yield_time` on every packet it sends whenever a client sits at the head of an unhealthy stream, which is the one condition under which `_is_timeout`'s 40 s could otherwise elapse. The reachable disconnect on TS is `MAX_KEEPALIVE_DURATION`. **Ruled: `serveClient` evaluates `time.Since(lastYield) > ClientTimeout && !Healthy()` exactly, and the pin is `TestAClientIsDroppedOnceTheKeepaliveCapIsReached`.** The `url_switching` exemption (`output/ts/generator.py:593-596`) is **not ported, and stated as a divergence**: `url_switching` is true only inside `update_url`'s own body (set at `input/manager.py:1476-1477`, cleared at `:1540`), a window of at most the old process's kill and stderr join, and a client reprieved in it is dropped on its next poll a second later. This plan's first draft carried a `Switching()` flag that was set and cleared under one lock hold and so could never read true — dead code the reviewer found; dropping it is the honest shape, since a flag spanning the whole switch would reprieve clients Python does not. fMP4's missing exemption is row 12 and 2c-6's, untouched.

### R15 — The error TS packet is ported for the client that received nothing; the initialization-timeout packet is not.

A2.5 recorded that Python's first client of a channel whose upstream then fails receives error TS packets where 2c-2 answered zero bytes, and named this PR the owner. `_wait_for_initialization` yields `create_ts_packet('error', "Error: <error_message>")` when the state it polls is `error`/`stopped`/`stopping` (`:235-239`), where `error_message` is what `run`'s finally block wrote (`:679-682`); a client already streaming is ended by `_check_resources` with no packet (`:455-459`). **Ruled: `serveClient` writes one packet carrying `ErrSourcesExhausted.Message()` when the ring closes with `sent == 0` and the channel is in error, "Error: Unknown error" for a stopped one, and nothing for a client that had bytes.** The "Error: Initialization timeout" packet after `CLIENT_WAIT_TIMEOUT` (`:249-251`) is **not** ported: this relay has no initializing wait a client can time out in, and a source that never delivers is ended by the health monitor's `InitGracePeriod`. Both halves are in the PR description's divergence list, replacing A2.5's.

---

## The 2c-4 dependency ledger

Every row below was verified at `d92b33be` with `git show "d92b33be:relay/<path>"` and `grep -n`, never off a working tree (§ Sequencing). **Task 0 re-checks every row against your tree**, and a row that does not match is a stop.

| What this PR depends on | Expected shape | If your tree differs |
|---|---|---|
| Module `github.com/D10Scot/Dispatcharr/relay` at `relay/`, Go 1.27.1, no `go.sum` | 2c-1's | every import path moves |
| `buffer.Ring` with `Write`, `Read`, `Join`, `Wait`, `Head`, `TotalBytes`, `ResetPosition`, `Close`, `Closed`; `buffer.TSPacketSize` | 2c-2 + 2c-3 | `ResetPosition` is what the switch calls; a missing one is a stop |
| `channel.Source` (one method), `ProxySource`, `ErrUpstreamIdle`, `ErrUpstreamStatus` | 2c-2 | untouched |
| `channel.Channel` with `id, ring, log, tuning, source, startedAt, mu, state, lastErr, stats, clients, cancel, done`; `run`, `promoteOnFirstChunk`, `setState`, `attachable` | 2c-4 Appendix M | Task 2 replaces `run` and adds seventeen fields; Appendix G is the whole file after |
| `channel.Tuning` with six fields | 2c-4 Appendix M | Task 2 adds ten; Appendix H |
| `channel.Manager`, `ManagerConfig{BudgetBytes, StopWait, Log, Now}`, `Started{Source, Tuning, Info}`, `publish`, `claim`, `stopIfStillIdle`, `Snapshot` | 2c-3 Appendix D, unchanged by 2c-4 | Task 2 adds two config fields and one `Started` field and edits `publish`; Appendix I |
| `channel.TranscodeSource`, `stderrReader`, `ErrBufferingTimeout`, `ErrInputFailed`, `waitOrKill`, `containsAny` | 2c-4 Appendix L | Task 2 edits three places; Appendix N is the whole file after |
| `channel.Stats`, `reportInfo`, `reportProgress`, `reportBuffering` with the guarded recovery edge | 2c-4 Appendix L | untouched; `failoverFromBuffering` calls `reportBuffering(false)` |
| `ffmpeg.Detector`, `Observe`, `Buffering`, `Reset`, `since` | 2c-4 Appendix E | Task 2 adds `BufferingFor`; Appendix J |
| `control.Client{Secret, HTTP, BaseURL, Now}`, `post`, `attempt`, `Unavailable{Path, Reason, Err, retryable}`, `Refused{Path, Status}`, `NewHTTPClient`, `ConnectTimeout`, `ReadTimeout`, `RetryDelay`, `attempts` | 2c-2 + 2c-4 Appendix K | Task 1 adds two files that call `post`; `nextsource.go` is untouched |
| `control.NextSourceRequest{…, CurrentStreamID *int, IncludeAlternates}`, `NextSourceAnswer{Source, Alternates, ProxySettings}`, `Source{…, SlotReserved, FFmpegStreamProfile}` | 2c-2 + 2c-4 | read by Task 3's resolver and Task 4's Redirect branch |
| `control.HeaderInternal`, `IsInternalPrincipal`, `InternalPrincipalToken`, `InternalRequestHeader`, `VerifyInternalRequest` | 2c-1 | R8 reads `IsInternalPrincipal` |
| `httpapi.StreamDeps{Secret, Channels, Control, Log, Now}`, `identify`, `mintClientID`, `peerAddress`, `startTune(parent, client, id)`, `transcodeSource`, `tuningFrom` (eight keys), `writeTuneFailure` (nine arms), `serveClient`, `writeChunks`, `ErrUnservedKind`, `ErrProfileArgvAbsent`, `ErrProfileUnbuildable`, `ErrNoFFmpegProfile`, `ErrNoSource`, `OutputFormatMPEGTS`, `tuneBudget` | 2c-4 Appendix P | Tasks 3–5 reshape; Appendix P here is the whole file after |
| `httpapi.ControlDeps`, `ChannelsHandler`, `describeChannel`, `channelPayload` (23 fields, `AvgBitrate` followed by `VideoCodec`), `clientPayload`, `RequireInternal`, `DefaultClientLimit` | 2c-4 Appendix P | Task 5 inserts `Healthy` between them; Appendix Q |
| `httpapi/golden_test.go`'s `goldenPayload`, the three tests, `keysOf`, `decodeGolden`; `testdata/channels_clients_all.json` with the seven ffmpeg keys | 2c-4 Appendix Q | Task 5 adds `healthy` to both |
| `httpapi/stream_test.go`'s `testSecret`, `rigChunkBytes`, `rigBudgetBytes`, `rig`, `newRig`, `tune`, `TestATuneRefusesAKindItDoesNotServe` (iterating `redirect` alone), `TestEveryProxySettingThisRelayReadsIsRequired` (eight keys), `TestAStreamThatEndsClosesTheClientsResponse`; `fanout_test.go`'s helpers; `transcode_test.go`'s `TestStandIn`, `transcodeRig`, `transcodeRigWith`, `waitForStats`, `listedChannel`, `TestAChildThatExitsNonZeroEndsTheTune`, two `startTune` calls in `TestABlankUserAgentFallsBackToTheWireDefault` | 2c-4 Appendix Q | Tasks 3–5 edit exactly these; Appendices S, T |
| `relaytest.ControlPlaneConfig` (fifteen fields), `ControlPlane{server, mu, requests, settings}`, `SetSettings`, `RecordedRequest`, `NewControlPlane` (one handler, always a next-source answer), `EffectiveProxySettings()` (fourteen keys incl. `DEFAULT_USER_AGENT`) | 2c-4 Appendix J | Task 1 rewrites the file; Appendix E |
| `relaytest.Config{Payload, Status, Rate, StopAfterBytes, Abrupt, DeadAir}`, `Upstream{Requests, Headers, Close}`, `NominalByteRate = 250000`, `WriteChunk` | 2c-2 + 2c-3 | Task 1 adds `DeadAirAfterBytes` and `Methods`; Appendix F |
| `relaytest.StandInCommand`, `StandInArgs`, `RunStandIn`, `StandInEnv`, `CorpusPath`, `CorpusSpeeds`, `Corpus`, `SplitCorpus` | 2c-4 Appendices H, I | called, not edited |
| `channel/source_transcode_test.go`'s `TestStandIn`, `standInSource`, `transcodeTuning`, `assetFile`, `captureLog`, `attachTranscode`, `waitFor`, `deref`, `TestASustainedSubThresholdSpeedEndsTheSourceWithATimeout`, `TestATranscodeProcessesFd1ReachesTheRingInOrder`; `source_transcode_real_test.go`'s bare `Tuning{…}` literal at its `:102` | 2c-4 Appendix O | Task 2 replaces one test with three, edits one, rebuilds one tuning; Appendix O |
| `channel/manager_test.go`'s `testTuning` (two fields), `asStarted`, `testClient`, `blockingSource`, `int32Counter`, `TestTwoClientsShareOneSource`, `TestACleanUpstreamEndClosesTheRing`, `TestAnUpstreamFailurePutsTheChannelInError` | 2c-2 + 2c-3 | Task 2 edits all four; Appendix R; the new tests are Appendix AF |
| `apps/proxy/tests/test_relay_list_payload_golden.py` with `NOT_SERVED_YET = {"logo_id", "healthy"}` and a fixture without `healthy` | 2c-4 Appendix T5 | Task 5 |
| Amendment **A4** in the spec; rows 4, 5, 28, 29 carrying Go references; the 2c-5 row reading as 2c-4's Task 10 Step 2 left it | 2c-4 Tasks 9, 10 | Task 6 edits rows 1, 2, 3, 6, 7; Task 7 appends A5 |
| `.claude/hooks/run-go-checks.sh` running credlint; `scripts/check_go_credential_logging.sh`; `scripts/check_go_stdlib_only.sh` | 2c-4 Task 8 | run, not edited |

**Verified at `d92b33be`, not inherited** (`apps/proxy/live_proxy/input/manager.py` is byte-identical between `29224271` and `d92b33be`, so every citation below was re-checked line by line against that file with `grep -n` after the reviewer found a drift list in the first draft): everything with a `file:line` in this plan — `input/manager.py:28-160`, `:183-206`, `:384-720`, `:753-860`, `:1102-1250`, `:1277-1380`, `:1462-1720`, `:1815-1966`, `:2020-2231` read in full; `views.py:160-280`, `:380-600`, `:645-648`, `:857`; `url_utils.py` in full; `next_source.py:717-755`, `:961-1011`; `control_plane.py:60-345`; `core/relay_events.py` in full; `serializers.py:232-280`; `api_views.py:90-135`; `relay_serializers.py:34-66`; `channel_status.py:300-325`, `:520-535`; `output/ts/generator.py:100-160`, `:200-260`, `:300-420`, `:520-604`; `utils.py:71-98`; `apps/proxy/config.py` in full; `config_helper.py` in full; `apps/channels/models.py:501-542`; `internal_auth.py:40-60`; `authorize_views.py:177`; `dispatcharr/utils.py:180-216`; `harness/faults.py:1-58`; `tests/test_manager_connection_failover.py`, `test_manager_stderr_failover.py:91-188`, `:363-460`, `test_failover_retry_window.py`; `e2e/tests/streaming-failover/*.spec.ts` and `streaming/stream-profiles.spec.ts:1-46`.

---

## File Structure

```
relay/control/release.go                  NEW  — ReleaseRequest, Client.Release
relay/control/events.go                   NEW  — Event, MaxEventsPerBatch, Client.PostEvents, Emitter
relay/control/release_test.go             NEW
relay/control/events_test.go              NEW
relay/internal/relaytest/controlplane.go  EDIT — three routes by suffix, Alternates, SlotReserved, SetStatus, SetDelay, Events, RequestsTo, six settings keys
relay/internal/relaytest/upstream.go      EDIT — DeadAirAfterBytes, Methods
relay/channel/tuning.go                   EDIT — ten fields
relay/channel/events.go                   NEW  — Event, EventSink, discardEvents, Channel.emit
relay/channel/failover.go                 NEW  — Resolver, NextRequest, Resolved, ErrNoAlternate, ErrSourcesExhausted, the five literals, failureCounter, healthActionFor, Channel.failover, failoverFromBuffering
relay/channel/health.go                   NEW  — dataClock, Healthy, inactivityThreshold, monitorHealth, takeFlag, flagSet
relay/channel/channel.go                  EDIT — sixteen fields, run (the supervisor), runAttempt, takePending, noteStable, releaseSlot; Source() under mu
relay/channel/manager.go                  EDIT — ManagerConfig.Events/Release, Started.Resolver, publish
relay/channel/source_transcode.go         EDIT — ErrBufferingTimeout deleted, cause reset, channel_buffering raised, the TimedOut arm
relay/ffmpeg/detector.go                  EDIT — BufferingFor
relay/channel/failover_test.go            NEW  — the fakes, a fake clock and twelve tests
relay/channel/manager_test.go             EDIT — testTuning, TestTwoClientsShareOneSource, TestACleanUpstreamEnd…, TestAnUpstreamFailure…
relay/channel/source_transcode_test.go    EDIT — the alternate-silent rows 1 and 6 tests and the no-alternate test replace the timeout test; the clean-exit test
relay/channel/source_transcode_real_test.go EDIT — the tuning literal builds on testTuning()
relay/httpapi/stream.go                   EDIT — eleven setting keys, tuningFrom, StreamDeps.Probe, the handler's redirect write, startTune(parent, tuneDeps, id, internal), infoFrom, sourceBuilder, the redirect arm, serveClient, errorPacketMessage
relay/httpapi/failover.go                 NEW  — resolver, isUnavailable, pickCached, resolved
relay/httpapi/redirect.go                 NEW  — the four constants, ErrRedirectValidationFailed, redirectAnswer, NewProbeClient, redirectTune, validateStreamURL
relay/httpapi/packets.go                  NEW  — signalPacket
relay/httpapi/events.go                   NEW  — EventSink, ReleaseVia
relay/httpapi/channels.go                 EDIT — Healthy field and its assignment
relay/main.go                             EDIT — one client, one emitter, the manager's two hooks
relay/httpapi/stream_test.go              EDIT — rig.Emitter, newRigWithClient, the kinds test, the per-key list, the EOF test
relay/httpapi/transcode_test.go           EDIT — two startTune calls, the exit test
relay/httpapi/golden_test.go              EDIT — healthy on the populated channel
relay/httpapi/testdata/channels_clients_all.json  REGENERATED from Django (healthy: true)
relay/httpapi/failover_test.go            NEW  — failoverRig and five tests
relay/httpapi/redirect_test.go            NEW  — redirectRig, tuneNoFollow and five tests
relay/httpapi/keepalive_test.go           NEW  — packetsUntil and four tests

                                          --- the Python half ---
apps/proxy/tests/test_relay_list_payload_golden.py  EDIT — healthy leaves NOT_SERVED_YET and joins the fixture

                                          --- documents ---
docs/relay-parity-matrix.md               EDIT — rows 1, 2, 3, 6 gain a Go reference; row 7 gains one across a switch
docs/superpowers/specs/2026-09-09-…-design.md   EDIT — Amendment A5, the 2c-5 and 2c-8 rows, a Done log row
CLAUDE.md                                 EDIT — § Architecture, § Known defects (one new bullet)
```

Nothing under `core/`, `dispatcharr/`, `frontend/`, `e2e/`, `metrics/`, `.github/` or `.claude/` is touched. `relay/buffer`, `relay/redact`, `relay/config`, `relay/internal/credlint`, `relay/ffmpeg/{parse,progress,spawn}*.go` are not touched.

---

## Task 0: Diff the merged 2c-4 tree against this plan's expectations

**Nothing else is written until this task is done and reported.**

- [ ] **Step 0: Seed from the merged SHA**

  ```bash
  cd <your worktree> && git log --oneline -1 d92b33be
  git diff --stat d92b33be HEAD -- relay/ apps/proxy/
  ```

  `d92b33be` is 2c-4 as merged onto `main` (PR #298), whose tree every appendix here was built on. The diff must be **empty** for `relay/`: if it is not, Step 2's table is the diff, and a file this plan replaces whole (§ File Structure) that has moved since is a stop-and-report, because applying the appendix would revert the change.

- [ ] **Step 1: Confirm the module, the toolchain, ffmpeg and the fixtures**

  ```bash
  cd <your worktree>/relay && cat go.mod && go version && golangci-lint --version && ls go.sum 2>&1
  ffmpeg -version | head -1
  ls -la ../apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/
  ```

  Expect module `github.com/D10Scot/Dispatcharr/relay`, `go 1.27.1`, golangci-lint 2.13.2, **no `go.sum`**, three `.stderr` files and `CAPTURE.md`. Record the ffmpeg version.

- [ ] **Step 2: Confirm every symbol this PR calls by name**

  ```bash
  cd <your worktree>/relay && grep -rn "^func \|^type \|^const \|^var " \
    channel/channel.go channel/manager.go channel/source_transcode.go channel/stats.go channel/tuning.go \
    ffmpeg/detector.go control/nextsource.go httpapi/stream.go httpapi/channels.go \
    internal/relaytest/controlplane.go internal/relaytest/upstream.go | sed 's/{$//'
  ```

  Against the ledger, check in particular:

  | Symbol | Expected shape | If it differs |
  |---|---|---|
  | `Started` | `struct{ Source Source; Tuning Tuning; Info SourceInfo }` | Task 2 adds `Resolver`; a fourth field already present is a stop |
  | `Tuning` | six fields ending `BufferingTimeout time.Duration` | Task 2 adds ten; a seventh already present is a stop |
  | `(*stderrReader).progress` | a `switch verdict := r.detector.Observe(*p.Speed); verdict` with `Started`, `Continuing`, `TimedOut`, `Ended`, `Steady` arms; `TimedOut` calls `s.fail(ErrBufferingTimeout, r.cancel)` | Appendix N replaces the file; any other shape is a stop |
  | `(*TranscodeSource).Run` | `ctx, cancel := context.WithCancel(parent)` then `proc, err := ffmpeg.Start(ctx, s.Command, s.argv())` | Task 2 inserts the cause reset between them |
  | `(*Channel).run` | `defer close(c.done); defer c.ring.Close()`, the `attachable` check, `setState(StateWaitingForClients)`, `go c.promoteOnFirstChunk`, one `source.Run`, a three-arm switch | Task 2 replaces the body; Appendix G |
  | `startTune` | `func startTune(parent context.Context, client *control.Client, id string) (channel.Started, error)`, `Reason: "initial"`, no `IncludeAlternates` | Task 3 changes the signature and the request |
  | `tuningFrom` | eight keys | Task 3 reads nineteen |
  | `channelPayload` | `AvgBitrate` immediately followed by `VideoCodec` | Task 5 inserts `Healthy` between them |
  | `ControlPlaneConfig` | fifteen fields ending `BlankUserAgent bool` | Task 1 adds `Alternates`, `SlotReserved` |
  | `EffectiveProxySettings()` | fourteen keys, `DEFAULT_USER_AGENT` included | Task 1 adds six |
  | `Detector` | `since time.Time` unexported; `Reset` present | Task 2 adds `BufferingFor` |
  | `TestATuneRefusesAKindItDoesNotServe` | iterates `[]string{control.KindRedirect}` | Task 4 narrows it to an invented kind |
  | `TestEveryProxySettingThisRelayReadsIsRequired` | eight keys | Task 3 adds eleven |

- [ ] **Step 2a: Count the writers of `StateActive`, and know what the number will stay**

  ```bash
  cd <your worktree>/relay && grep -rnE "state = StateActive|setState\(StateActive" --include='*.go' . | grep -v _test.go
  ```

  **Expect exactly two lines at `d92b33be`**: `channel/channel.go`'s inside `promoteOnFirstChunk`, and `channel/stats.go`'s inside `reportBuffering` under `case !on && c.state == StateBuffering`. **After Task 2 the count is still TWO**, and Task 8 Step 3a re-runs this grep and expects the same two lines. `failoverFromBuffering` calls `reportBuffering(false)`; it adds no write (§ Sequencing).

- [ ] **Step 3: Confirm the Python side this PR edits is where the plan says**

  ```bash
  cd <your worktree> && grep -n 'NOT_SERVED_YET\|"healthy"' apps/proxy/tests/test_relay_list_payload_golden.py
  grep -n '^| [12367] ' docs/relay-parity-matrix.md | cut -c1-40
  grep -n '^#### Amendment A[0-9]' docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
  grep -n '^| 2c-5 \|^| 2c-8 ' docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md | cut -c1-60
  ```

  Expect `"healthy": "needs StreamManager.healthy, which arrives in 2c-5"` inside `NOT_SERVED_YET` and no `"healthy"` in the fixture; rows 1, 2, 3, 6 with Python-only pins and row 7 with 2c-2's `TestResetPositionDoesNotRewindTheChunkIndex`; Amendments A1–A4; the two table rows.

- [ ] **Step 4: Run the four checks, credlint and the stdlib check on the tree as merged**

  ```bash
  cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
  cd <your worktree> && scripts/check_go_credential_logging.sh relay && scripts/check_go_stdlib_only.sh relay
  ```

  **A red tree here is a stop.**

- [ ] **Step 5: Report**

  Every ledger row that did not match, and which task absorbs it. Do not start Task 1 until this is reported.

---

## Task 1: `relay/control` — `release`, `events`, the emitter, and the fakes

**Files:**
- Create: `relay/control/release.go`, `relay/control/events.go`, `relay/control/release_test.go`, `relay/control/events_test.go` (Appendices A, B, C, D)
- Replace: `relay/internal/relaytest/controlplane.go` (Appendix E)
- Modify: `relay/internal/relaytest/upstream.go` (Appendix F — the whole file after)

**Interfaces:**
- Consumes: `control.Client.post` (2c-2), `Unavailable`, `Refused`, `ErrNotConfigured.Variable`, `redact.Error`.
- Produces: the #300 fix in `relaytest.Upstream`'s throttle; `control.ReleaseRequest{StreamID, M3UProfileID, ChannelPK *int}`; `(*Client).Release(ctx, identifier, ReleaseRequest) (bool, error)`; `control.Event{Type, ChannelID, ChannelName, ClientID string; StreamID *int; Details map[string]any}`; `MaxEventsPerBatch = 200`; `(*Client).PostEvents(ctx, []Event) error`; `NewEmitter(*Client, *slog.Logger) *Emitter` with `Emit(Event)`, `Close()`, `Down() bool`; `relaytest.ControlPlaneConfig.Alternates []AlternateConfig{StreamID, URL, UserAgent, Argv}`, `.SlotReserved *bool`; `(*ControlPlane).SetStatus(int)`, `SetDelay(time.Duration)`, `RequestsTo(suffix) []RecordedRequest`, `Events() []RecordedEvent`, `EventsOfType(string)`; `RecordedRequest.At`; `relaytest.Config.DeadAirAfterBytes`; `(*Upstream).Methods() []string`; six more keys on `EffectiveProxySettings()`.

- [ ] **Step 1: Write the four `control` files from Appendices A–D and replace the two `relaytest` files from Appendices E–F**

  The fake control plane now dispatches on the path suffix: `/release` answers `{"released": true}` (`api_views.py:96-100`), `/events` records the batch and answers `{"accepted": n, "rejected": 0}`, everything else is a next-source answer built from `SourceURL` (stream 1) and `Alternates`, honouring `exclude_stream_ids` and `current_url` and listing the rest when `include_alternates` is set — the shape `resolve_source` produces. `SetStatus` and `SetDelay` change every LATER answer, which is the only way a test can take the control plane down after a tune. The upstream's `DeadAirAfterBytes` is `harness/standin.py`'s flag on the provider rather than the child.

  **And the upstream's throttle is fixed — issue #300, found by the 2c-4 review and owned here because this PR extends the file.** The throttle slept `min(wait, 250ms)` ONCE, capping the total wait, so any rate below ~37,600 B/s was delivered faster than configured: the three `Rate 0.05` fixtures (`channel/fanout_test.go:247`, `channel/manager_test.go:117` and `:332`) about three times too fast, and row 4's quarter-rate upstream looping every 13.5 s instead of 32 s. Appendix F sleeps in steps of at most 250 ms until due, breaking when the client's context ends. **None of this PR's own fixtures sits on the bug** — every 2c-5 upstream runs at `Rate: 4` (1 MB/s) or unpaced — and none of the four affected tests needed its window widened (measured; Constraint 31 would have applied if one had). Row 4's real-ffmpeg test now arms **6.5–6.6 s** after the first record (two runs) at 10.2–10.3x opening speed on ffmpeg 9.0.1 against a truly quarter-rate upstream, where 2c-4 measured 12.2 s on the capped throttle; both are above the 4 s floor, and the floor does not move.

- [ ] **Step 2: Run the two packages**

  ```bash
  cd <your worktree>/relay && go build ./... && go vet ./... && go test -race -count=1 ./control/ ./internal/relaytest/
  ```

  Expect `ok` for both. The emitter's outage test counts `level=WARN` lines, not the message alone: the later batches log the same message at DEBUG, which is the whole point.

- [ ] **Step 3: Break-checks**

  In `control/events.go`'s `post`, delete `e.down = true` from the `default` arm. Run `TestTheEmitterLogsOnceIntoAnOutageAndOnceOutOfIt`: red, "the emitter does not report the outage". Revert.

  Then #300's: put the throttle back to a single `time.Sleep(min(wait, 250*time.Millisecond))` and run `go test -race -count=1 -v -run TestTheCumulativeLeadMustBurnOffBeforeTheDetectorArms ./channel/`. The test stays green either way (its 4 s floor is below both measurements — that is what a floor is for), so the break-check is the **number**: the logged "armed N s after the first record" must be well above this plan's 6.5–6.6 s with the cap back in place (2c-4 measured 12.2 s) and near it with the fix. Record both. Revert.

- [ ] **Step 4: Lint, credlint, commit**

  ```bash
  cd <your worktree>/relay && golangci-lint run ./... && cd .. && scripts/check_go_credential_logging.sh relay
  ```

  Zero findings. Stage the six files; commit with `-F` — `relay(control): the release and events routes, the emitter, and the fakes' failover shape (2c-5 Task 1)`.

---

## Task 2: `relay/channel` — the supervisor loop, the health monitor, the failover, the events

**Files:**
- Replace: `relay/channel/channel.go` (Appendix G), `relay/channel/tuning.go` (H), `relay/channel/manager.go` (I), `relay/ffmpeg/detector.go` (J), `relay/channel/source_transcode.go` (N), `relay/channel/manager_test.go` (R), `relay/channel/source_transcode_test.go` (O)
- Create: `relay/channel/events.go` (K), `relay/channel/failover.go` (L), `relay/channel/health.go` (M), `relay/channel/failover_test.go` (AF)
- Modify: `relay/channel/source_transcode_real_test.go` — the three-line tuning edit Appendix O names

**Interfaces:**
- Consumes: `buffer.Ring.ResetPosition`, `ffmpeg.Detector.Reset`/`BufferingFor`, `redact.Error`/`Line`, `TranscodeSource.attach`/`fail`.
- Produces: `channel.Resolver`, `NextRequest{Exclude []int; CurrentURL string; CurrentStreamID int}`, `Resolved{Source, Info, Degraded}`, `ErrNoAlternate`, `*ErrSourcesExhausted{Tried, Attempts, Last}` with `Message()`; `channel.Event`, `EventSink`; `ManagerConfig.Events EventSink`, `.Release func(id string, info SourceInfo)`; `Started.Resolver`; `(*Channel).Healthy()`; `Tuning`'s ten new fields; `failoverFromBuffering(time.Duration) bool` (package-private, called by the stderr reader).

- [ ] **Step 1: Write the files**

  Appendices G–O, R and AF are whole files. Four things to read before applying them, because they are where a merge difference would hide (Task 0 Step 0):

  - `channel.go`'s `run` is the port of `input/manager.py:384-709`, loop for loop; its comment carries the line map. `releaseSlot` is deferred FIRST so it runs LAST, after the ring has closed.
  - The health monitor's reconnect flag is taken INSIDE the inner loop, after `runAttempt`, and falls through to the failure accounting (`:521-534`, Ruling R4). There is no outer-loop reconnect branch and no `channel_reconnect{reason: health_monitor}`; both were in this plan's first draft, and the reviewer showed the flag going stale.
  - `source_transcode.go` changes in three places: `ErrBufferingTimeout` and its comment are deleted; `Run` resets `s.cause` under `s.mu` before `ffmpeg.Start`; `progress`'s `Started` arm raises `channel_buffering` and its `TimedOut` arm calls `failoverFromBuffering`. Everything else is 2c-4's byte for byte.
  - `manager.go` changes in three places: two `ManagerConfig` fields, one `Started` field, and `publish`'s literal (`events`, `release`, `ctx`, `now`, `channelName`, `healthy`, `lastData`, `tried`, `currentStreamID`, `failures`). `Attach`, `claim`, `release`, `stopIfStillIdle`, `Snapshot` are untouched.

- [ ] **Step 2: Note the four existing tests whose expectations move, and why each moves**

  | Test | Was | Is | Ruling |
  |---|---|---|---|
  | `TestACleanUpstreamEndClosesTheRing` | one EOF → `stopped` | renamed `TestACleanUpstreamEndIsRetriedAndThenExhaustsTheSource`: three requests, `error`, "Connection failed after 3 attempts", ring closed | R1 |
  | `TestAnUpstreamFailurePutsTheChannelInError` | one 404 → `error` | three requests, then `error`; `ErrUpstreamStatus` reachable through the wrapper | R1 |
  | `TestATranscodeProcessesFd1ReachesTheRingInOrder` | clean exit → `stopped` | three runs, `error`, packet order asserted within a run | R1 |
  | `TestTwoClientsShareOneSource` | released at once after `Attach` | waits for the source to start first | Constraint 17 |
  | `TestASustainedSubThresholdSpeedEndsTheSourceWithATimeout` | `ErrBufferingTimeout` ends the tune | **deleted**; replaced by rows 1 and 6 and the no-alternate test | R6 |
  | `source_transcode_real_test.go`'s tuning | a bare literal | built on `testTuning()` | Constraint 27 |

  `testTuning()` gains the ten fields at production values with a comment that says why (hollow shape 2).

- [ ] **Step 3: Run the package, eight times**

  ```bash
  cd <your worktree>/relay && go build ./... && go vet ./... && for i in 1 2 3 4 5 6 7 8; do go test -race -count=1 ./channel/ 2>&1 | tail -1; done
  ```

  Eight `ok`. The package takes about a minute per run: rows 1 and 6 wait out a 1 s timeout each, the real-ffmpeg test twenty seconds, and the retry tests 0.75 s of backoff each.

- [ ] **Step 4: The break-checks, one at a time, reverting between them**

  | # | Edit | Run | Expect red on |
  |---|---|---|---|
  | 1 | `maxUnhealthyChecks = 1` | `TestDeadAirOnAYoungConnectionSwitchesStreams` | "never observed unhealthy before it switched" (Constraint 30: the gap assertion is second) |
  | 2 | `failureCounter.record`'s reset `if` → `if false` | `TestTheRetryWindowResetsTheCounterAfterAnIdleGap` | "counted as 4, want 1" |
  | 3 | `if failures >= c.tuning.MaxRetries` → `>` | `TestThreeConnectFailuresExhaustTheSourceAndFailOver` | a 10 s timeout waiting for the alternate |
  | 4 | `failoverFromBuffering` returns false when `MaxStreamSwitches < 1` | `TestABufferingFailoverIgnoresMaxStreamSwitches` | a 15 s timeout "waiting for the switch despite a bound of zero" |
  | 5 | the `TimedOut` arm's `failoverFromBuffering` call → `if false` | `TestASustainedSubThresholdSpeedFailsTheChannelOver` | a 15 s timeout "waiting for the switch" |
  | 6 | `c.ring.ResetPosition()` deleted from `failover` | `TestTheChunkIndexIsMonotonicAcrossAFailover` | "chunk 2 is not whole packets: byte 188 is 0xb1" |
  | 7 | `defer c.releaseSlot()` deleted | `TestTheSlotIsReleasedOnceWhenTheSourceGoroutineReturns` | a 5 s timeout waiting for the release |
  | 8 | `stream_switch`'s `new_url` unredacted | `TestThreeConnectFailuresExhaustTheSourceAndFailOver` | "must be the redacted URL, host kept and path gone" |
  | 9 | the `degraded_failover` emit → `if false` | `TestAFailoverFromTheCacheRaisesDegradedFailoverOnRecovery` | "raised 0 times, want exactly 1" |
  | 10 | `s.cause = nil` reset removed | `TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord` | **stays green** — recorded, not hidden (§ Break-check, row 20) |
  | 11 | the inner loop's `c.takeFlag(&c.needsReconnect)` → `c.flagSet(...)` (read, never cleared) | `TestASecondStableStallIsActedOnAfterAHealthReconnect` | "stall 2: the source ran 2 times, want 3 -- needsReconnect stayed set after the first reconnect and the monitor never cancelled again" (row 23) |

- [ ] **Step 5: Count the `StateActive` writers**

  Task 0 Step 2a's grep: still two lines, the same two.

- [ ] **Step 6: Lint, credlint, commit**

  Zero findings, no suppression. Stage the twelve files; commit — `relay(channel): the supervisor loop, the health monitor and the failover — rows 1, 2, 3, 6 (2c-5 Task 2)`.

---

## Task 3: `relay/httpapi` — the resolver, the settings, the events and release wiring, the degraded fallback

**Files:**
- Replace: `relay/httpapi/stream.go` (Appendix P — the whole file after Tasks 3, 4 and 5; apply it once here, the later tasks add tests against parts of it), `relay/main.go` (Appendix U)
- Create: `relay/httpapi/failover.go` (V), `relay/httpapi/events.go` (W), `relay/httpapi/failover_test.go` (X), `relay/httpapi/redirect.go` (Y — `stream.go` calls `redirectTune` and names `*redirectAnswer` and `ErrRedirectValidationFailed`, so the package does not compile without it; Task 4 adds only its tests), `relay/httpapi/packets.go` (AA — `serveClient` calls `signalPacket`; Task 5 adds its tests)
- Modify: `relay/httpapi/stream_test.go` (Appendix S — the whole file after: `rig.Emitter`, `newRigWithClient`, the kinds test, the per-key list, the EOF test), `relay/httpapi/transcode_test.go` (T — two `startTune` calls and the exit test)

**Interfaces:**
- Consumes: everything Task 1 and 2 produce; `control.Client.NextSource`; `channel.NeedsFFmpeg`.
- Produces: `httpapi.EventSink(*control.Emitter) channel.EventSink`; `ReleaseVia(*control.Client, *slog.Logger) func(string, channel.SourceInfo)`; `tuneDeps{control, probe, log}`; `startTune(parent, tuneDeps, id string, internal bool)`; `infoFrom`; `sourceBuilder{kind, userAgent, readSize}.source(*control.Source)`; `resolver`; eleven `setting*` constants; `StreamDeps.Probe`.

- [ ] **Step 1: Write the files**

  `stream.go` is applied whole; Tasks 4 and 5 test what it already contains. Its `startTune` sends `IncludeAlternates: true` (`url_utils.py:55-58` does), builds the `sourceBuilder` once per tune, and hands the channel a `resolver` holding `answer.Alternates`. `main.go` builds one `control.Client`, one `Emitter`, and a manager with both hooks.

  The rig's manager now carries `EventSink` and `ReleaseVia` over the rig's own client, so the fake's request log sees releases and events too — which is why `TestAStreamThatEndsClosesTheClientsResponse` counts with `RequestsTo("/next-source")` (Constraint 33).

- [ ] **Step 2: Run the package**

  ```bash
  cd <your worktree>/relay && go build ./... && go vet ./... && go test -race -count=1 ./httpapi/ 2>&1 | tail -3
  ```

  Expect `ok` in about a minute. `stream.go` is applied whole, which is why `redirect.go` and `packets.go` are created here: the handler and the client loop already call into them. Their behaviour is pinned in Tasks 4 and 5.

- [ ] **Step 3: The four existing tests that move**

  | Test | Change | Ruling |
  |---|---|---|
  | `TestATuneRefusesAKindItDoesNotServe` | iterates an invented kind, `"hls-passthrough"`; Redirect is served | R7 |
  | `TestEveryProxySettingThisRelayReadsIsRequired` | nineteen keys | Constraint 13 |
  | `TestAStreamThatEndsClosesTheClientsResponse` | three requests at the provider, then the tune and one failover at the control plane | R1 |
  | `TestAChildThatExitsNonZeroEndsTheTune` | three requests, thirty-second bound | R1 |

- [ ] **Step 4: Break-checks**

  | # | Edit | Run | Expect red on |
  |---|---|---|---|
  | 11 | `case isUnavailable(err):` → `case false && …` | `TestAFailoverFallsBackToTheCachedCandidatesWhenTheControlPlaneIsDown` | a 15 s timeout "waiting for the switch to the cached second stream" |
  | 12 | `case isUnavailable(err):` → `case err != nil:` | `TestARefusedFailoverNeverUsesTheCache` | "the channel did not end after a refused failover" |
  | 13 | `control/nextsource.go`'s `attempts = 1` | `TestTheDegradedFallbackSpendsTheClientsRetryBudgetFirst` | "saw 2 next-source calls, want 3" |
  | 14 | `settingMaxRetries` read replaced by a literal 3 | `TestEveryProxySettingThisRelayReadsIsRequired/MAX_RETRIES` **only** | "tuned with 200, want 502" |

  Row 14 was not run on this plan's tree (every key is read through the same `tuningFrom` shape 2c-4's row 9 verified); run it and report.

- [ ] **Step 5: Lint, credlint, commit**

  Commit — `relay(httpapi): the resolver, the degraded fallback and the event and release wiring (2c-5 Task 3)`.

---

## Task 4: `relay/httpapi` — the Redirect architecture

**Files:**
- Create: `relay/httpapi/redirect_test.go` (Appendix Z); `relay/httpapi/redirect.go` (Y) was created in Task 3 and is what this task pins

**Interfaces:**
- Produces: `probeTimeout`, `probeRedirectLimit`, `probeChunk`, `ErrRedirectValidationFailed`, `*redirectAnswer{Location, Status}`, `NewProbeClient()`, `redirectTune`, `validateStreamURL(ctx, *http.Client, url, userAgent) (bool, string)`.

- [ ] **Step 1: Read `validateStreamURL` against `url_utils.py:138-262` before trusting it**

  Five decisions, each cited in the code: a non-HTTP scheme is valid unprobed (`:154-157`); a HEAD that errors is "HEAD not supported", never "invalid" (`:175-178`); a HEAD 2xx is valid (`:181-183`); a GET 2xx with one byte is valid whatever the Content-Type (`:234-250`); the URL returned is the one given (`:183`, `:250`). The probe sends **no** `User-Agent` when the answer's is blank (`:163`'s `None` value), which Go needs `req.Header["User-Agent"] = nil` for.

- [ ] **Step 2: Write `redirect_test.go` and run**

  ```bash
  cd <your worktree>/relay && go test -race -count=1 -run 'Redirect|InternalPrincipal' ./httpapi/
  ```

  Five tests: the 302 with the provider URL and only a HEAD at the provider, no channel, an empty list, one release; the fall-through to an alternate after HEAD and GET both 404; the 502 JSON body; the internal-principal 200 through Proxy and the forged marker's 302; the rtsp 301 with no probe.

- [ ] **Step 3: Break-checks**

  | # | Edit | Run | Expect red on |
  |---|---|---|---|
  | 15 | `if source.SlotReserved` → `if false && …` | `TestARedirectProfileHandsTheClientTheProviderURLAndFetchesNothing` | "release calls = [], want one for stream 1" |
  | 16 | `if !internal {` → `if true {` | `TestAnInternalPrincipalOnARedirectChannelIsServedThroughProxy` | "answered 302, want 200 through Proxy" |

- [ ] **Step 4: Ruling R7's Python confirmation (optional, container)**

  If the shared container is yours (Constraint 10), one harness check confirms the static reading behind R7: in `apps/proxy/live_proxy/tests/`, a `RelayHarnessTestCase` that makes a channel on the locked Redirect profile, tunes it with `allow_redirects=False`, asserts 302, then calls `relay_client.list_channels()` and asserts the channel's uuid is absent. **Do not commit it** — it is a check on this plan's reading, not a test the PR needs — but report the result. If the container is not yours, say so and skip it.

- [ ] **Step 5: Lint, credlint, commit**

  Commit — `relay(httpapi): the Redirect architecture — the probe, the fall-through, the release and the internal-principal override (2c-5 Task 4)`.

---

## Task 5: `relay/httpapi` — the health flag, the keepalives, the client timeout, the error packet; the golden

**Files:**
- Create: `relay/httpapi/keepalive_test.go` (Appendix AB); `relay/httpapi/packets.go` (AA) was created in Task 3 and is what this task pins alongside `serveClient`
- Modify: `relay/httpapi/channels.go` (Appendix Q — the whole file after), `relay/httpapi/golden_test.go` (AC — `healthy` on the populated channel), `relay/httpapi/testdata/channels_clients_all.json` (regenerated), `apps/proxy/tests/test_relay_list_payload_golden.py` (AD — two edits)

- [ ] **Step 1: The Python half first, then regenerate the golden**

  In `apps/proxy/tests/test_relay_list_payload_golden.py`: delete the `"healthy"` entry from `NOT_SERVED_YET` (leaving `logo_id` alone, with 2c-4's paragraph adjusted to say seven fields came in 2c-4 and `healthy` in 2c-5), and add `"healthy": True,` to the populated fixture channel immediately after `"avg_bitrate": "2.67 Mbps",` — the serializer's declaration order (`relay_serializers.py:56`). Then, on the host:

  ```bash
  cd <your worktree> && DISPATCHARR_WRITE_GOLDEN=1 TEST_USE_SQLITE=1 python manage.py test apps.proxy.tests.test_relay_list_payload_golden
  git diff --stat relay/httpapi/testdata/
  ```

  The regenerated JSON differs from 2c-4's by exactly one key, `"healthy": true`, between `avg_bitrate` and `video_codec`. Then, in the container, the same module without the variable: three tests pass, `test_the_fixture_covers_every_serializer_field` among them.

- [ ] **Step 2: Write the Go files and run**

  ```bash
  cd <your worktree>/relay && go test -race -count=1 -run 'Keepalive|Healthy|ErrorPacket|Golden|KeySet' ./httpapi/
  ```

  Four new tests plus the three golden ones. The keepalive test takes eight seconds: five of them proving a HEALTHY channel sends nothing at the head.

- [ ] **Step 3: Break-checks**

  | # | Edit | Run | Expect red on |
  |---|---|---|---|
  | 17 | `if !ch.Healthy() && empties >= …` → `if empties >= …` | `TestAnUnhealthyChannelSendsKeepalivesAtTheBufferHeadAndAHealthyOneDoesNot` | "the first keepalive came 1.004s after the last asset packet, while the channel was still HEALTHY" |
  | 18 | the `MaxKeepalive` check → `if false` | `TestAClientIsDroppedOnceTheKeepaliveCapIsReached` | "the response did not end within 15s" |
  | 19 | `out.Healthy = &healthy` → `_ = healthy` | `TestHealthyOnTheListPayloadFollowsTheHealthMonitor` **and** `TestTheLiveEndpointProducesTheGoldensKeySet` | "healthy = <nil> while data flows" and the key-set diff |
  | 20 | `if sent == 0 {` → `if false {` | `TestAClientWithNoBytesGetsAnErrorPacketWhenEverySourceFails` | "the body is 0 bytes, want exactly one error packet" |

- [ ] **Step 4: Lint, credlint, commit**

  Commit — `relay(httpapi): the health flag, the keepalives, the client timeout and the error packet (2c-5 Task 5, Amendment A2.5)`.

---

## Task 6: the parity matrix — rows 1, 2, 3 and 6 get their Go pin; row 7 gains one across a switch

Amendment A2.2's rule: a Go reference appended to the existing `Pin` cell, one line per row, no padding, no formatter. **Tasks 2, 3 and 5 must be committed first**: the guard resolves each `.go` reference by opening the file.

- [ ] **Step 1: Read the five rows before editing them**

  ```bash
  cd <your worktree> && grep -n '^| 1 \|^| 2 \|^| 3 \|^| 6 \|^| 7 ' docs/relay-parity-matrix.md
  ```

- [ ] **Step 2: Append, and add one sentence to each Notes cell**

  | Row | Append to `Pin` | Append to `Notes` |
  |---|---|---|
  | 1 | `` `relay/channel/source_transcode_test.go::TestASustainedSubThresholdSpeedFailsTheChannelOver` `` | The Go pin is 2c-5's: the same lever (buffering_speed at the API maximum, a 1s timeout against the slow-trickle capture), the switch made from the stderr goroutine, the clock taken before the source starts, `channel_failover` carrying `reason: buffering_timeout` and a `duration` past the timeout. |
  | 2 | `` `relay/channel/failover_test.go::TestDeadAirOnAYoungConnectionSwitchesStreams` ``, `` `relay/httpapi/failover_test.go::TestAFailoverKeepsTheClientAttachedAndFed` `` | The Go pin is 2c-5's and drives the same unstable branch: CONNECTION_TIMEOUT and HEALTH_CHECK_INTERVAL off the wire at 300 ms and 50 ms, and the assertion is on the GAP between the last byte and the resolver's call — at least the threshold plus two more checks — so a monitor acting on its first inactive check reddens. The stable branch's 30 s literal is pinned as a decision (`healthActionFor` at 29 s versus 30 s), not driven; the reconnect it selects is the inner loop's fall-through at `:521-534`, and a second stall after it is pinned by `failover_test.go::TestASecondStableStallIsActedOnAfterAHealthReconnect`. One stated divergence: the Go monitor CANCELS the running attempt when it raises a flag, where Python's main loop notices the flag between `fetch_chunk` calls, each blocking up to `CHUNK_TIMEOUT` (5 s) in `select` on a silent pipe (`:1364-1365`, `:1845`) — the Go relay acts up to five seconds sooner and `CHUNK_TIMEOUT` is not read (spec Amendment A5.7). The second reference is the e2e spec's claim at the relay: the client is still attached and fed after the switch. |
  | 3 | `` `relay/channel/failover_test.go::TestThreeConnectFailuresExhaustTheSourceAndFailOver` ``, `` `relay/channel/failover_test.go::TestTheRetryWindowResetsTheCounterAfterAnIdleGap` `` | The Go pins are 2c-5's: three attempts at the source, one resolver request excluding stream 1, two `channel_reconnect`, one `channel_error` with `connection_failed` and `attempts` 3, one `stream_switch`; and the window with an injected clock at t = 0, 1700, 3400 and 5201. A clean EOF is a counted failure here as it is in Python (`:1868-1872`), which 2c-2 had pinned the other way. |
  | 6 | `` `relay/channel/source_transcode_test.go::TestABufferingFailoverIgnoresMaxStreamSwitches` ``, `` `relay/channel/failover_test.go::TestMaxStreamSwitchesBoundsAMainLoopSwitch` `` | The Go pin is 2c-5's, reproduced not fixed: with MAX_STREAM_SWITCHES at zero off the wire, a buffering failover still switches and the channel keeps playing, while the sibling proves the same zero DOES end the loop after a connect-failure switch — the asymmetry is what is pinned, not the absence of a bound. |
  | 7 | `` `relay/channel/failover_test.go::TestTheChunkIndexIsMonotonicAcrossAFailover` `` | The Go pin across a SWITCH is 2c-5's: the primary's chunks stay readable from index 0 after the failover, the head keeps climbing, and the primary's three stray trailing bytes are dropped by `ResetPosition` rather than glued to the alternate's first packet. |

- [ ] **Step 3: Run the guard**

  ```bash
  cd <your worktree>/e2e && npx playwright test --project=guards parity-matrix
  ```

  No container. The owed list stays empty.

- [ ] **Step 4: Commit**

  `docs(parity): rows 1, 2, 3, 6 and 7 get their Go pin (2c-5 Task 6)`.

---

## Task 7: the spec amendment, `CLAUDE.md`, one issue, and the Done log

- [ ] **Step 1: Write Amendment A5 into the spec**

  After Amendment A4 (as it stands on `main`), Appendix AE's text: A5.1 (a clean EOF is a retried failure — R1; the loop's shape), A5.2 (the Resolver seam and where the degraded fallback lives — R2; the timing shape reproduced), A5.3 (the events client and the six types; the four that are 2c-8's — R11, R12), A5.4 (the #190 `hdel`s need no move and no Redis read; an input for 2d — R9), A5.5 (the Redirect tune publishes no channel — R7; the internal override — R8), A5.6 (A2.5 closed: the health flag, the keepalives, the client timeout, and the error packet's two halves — R14, R15), A5.7 (the stated divergences — R3, R4, R5, R10, R13), A5.8 (the Python defect the port carries: one next-source call per progress record after a buffering timeout with no alternate — R6, filed).

- [ ] **Step 2: Edit the nine-PR table's 2c-5 and 2c-8 rows, in the table**

  2c-5's "What it does" becomes: *The three failover triggers (rows 1, 2, 3) as one port of `StreamManager.run`'s two loops; the control-plane client's remaining routes (`release`, `events`; `next-source` landed in 2c-2, Amendment A2.1) and an emitter that batches and logs an outage once; the degraded fallback to the candidate list cached at channel start, never on a refusal; the Redirect Stream Profile architecture — the 302, `validate_stream_url`'s provider probe, the fall-through to the cached alternates, the internal-principal override that serves it through Proxy (`views.py:462-480`), publishing no channel (Amendment A5.5); the health flag, the keepalives, the client timeout and the error packet (Amendments A2.5, A5.6); and the six events the failover machinery raises (A5.3).* Its gate: *Rows 1, 2, 3 and 6 get a Go column; row 7 gains a pin across a switch.* 2c-8's "What it does" gains: *the four events the tune and stop paths raise — `channel_start`, `channel_stop`, `client_connect`, `client_disconnect` (Amendment A5.3).*

- [ ] **Step 3: `CLAUDE.md`**

  § Architecture, after 2c-4's sentence: one sentence — since 2c-5 the Go relay fails over: the three triggers drive one port of `StreamManager.run`'s loops (`relay/channel/channel.go`), a clean EOF is a retried connection failure, the buffering-triggered switch bypasses `MAX_STREAM_SWITCHES` as in Python (row 6), the degraded fallback reads the candidate list the initial `next-source` answer carried and never a Redis key, a Redirect channel is a 302 with no channel published, and `GET /proxy/relay/channels` carries `healthy`.

  § Known defects, Correctness — one new bullet after the `MAX_STREAM_SWITCHES` one: **A buffering timeout with no alternate asks `next-source` on every progress record** (`input/manager.py:1178-1211`): when `_try_next_stream()` fails, the buffering flag stays set and the next `speed=` record — every ~0.5 s — reaches the timeout branch again and makes another control-plane call, for as long as the speed stays low. The Go relay reproduces it per D5 (`TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord`). Filed as [#NNN].

- [ ] **Step 4: File the issue**

  ```bash
  gh issue create --repo D10Scot/Dispatcharr --label needs-triage --title "A buffering timeout with no alternate stream calls next-source on every ffmpeg progress record" --body-file <file>
  ```

  Always `--repo`. Put the number into the `CLAUDE.md` bullet and Amendment A5.8.

- [ ] **Step 5: The Done log**

  One row for 2c-5 naming the branch `migration/phase2c-failover`, and one for its review fix round when there is one.

- [ ] **Step 6: Commit**

---

## Task 8: final verification and the PR description

- [ ] **Step 1: The whole gate**

  ```bash
  cd <your worktree>/relay && ls go.sum 2>&1; gofmt -l . && go build ./... \
    && go vet ./... && GOOS=linux go vet ./... && GOOS=darwin go vet ./... \
    && golangci-lint run ./... && GOOS=linux golangci-lint run ./... && GOOS=darwin golangci-lint run ./... \
    && for i in 1 2 3; do go test -race -count=1 ./... 2>&1 | grep -v '^ok\|no test files'; done \
    && for i in 1 2 3 4 5 6 7 8; do go test -race -count=1 ./channel/ 2>&1 | grep -v '^ok'; done \
    && for i in 1 2 3; do go test -count=1 ./ffmpeg/ ./channel/ 2>&1 | grep -v '^ok'; done
  cd <your worktree> && scripts/check_go_credential_logging.sh relay && scripts/check_go_stdlib_only.sh relay
  ```

  `go.sum` absent; nothing printed by any loop; `0 issues` three times; credlint clean; stdlib only. The no-race runs are break-check 22 of 2c-4's plan: the stand-in's stderr pump is joined, and a scheduling-dependent pass under `-race` alone was how that bug hid.

- [ ] **Step 2: The backend labels the commit gate will run**

  `apps/proxy/tests/` is the one Python file touched; the gate runs its label in the container. Confirm it is green there.

- [ ] **Step 3a: The `StateActive` count**

  Task 0 Step 2a's grep: two lines, `channel/channel.go`'s `promoteOnFirstChunk` and `channel/stats.go`'s `reportBuffering`.

- [ ] **Step 4: The guard**

  `cd e2e && npx playwright test --project=guards parity-matrix` — green, owed list empty.

- [ ] **Step 5: Push and open the PR**

  Branch `migration/phase2c-failover`, base `main`, draft until the reviewer passes it.

- [ ] **Step 6: The PR description**

  In this order: what this PR does; **Ruling R1** and the four tests it reshaped; **the twenty-three break-checks** with their actual messages, and the one that stayed green (row 20) with its reason; **the eight consecutive `relay/channel` runs and three module runs**; **the credlint census** — two markers added, both `encoding/json`, zero findings; **zero suppressions**; **the edits no test pins**, stated: the transcode source's cause reset (no stand-in shape produces a first-attempt-only VLC failure), `Detector.Reset` on a buffering switch (the process dies before the next record), `Emitter`'s `ErrNotConfigured` arm, and `redirectTune`'s "failed to release" log; **the stated divergences**, as a list: a clean EOF's retry replacing 2c-2's stop (R1, Python's own shape); the health monitor cancelling the attempt where Python waits up to `CHUNK_TIMEOUT` (R3); the outer loop's `_attempt_reconnect` branch not ported because Python cannot reach it (R4); `channel_reconnect` raised at attempt start (R5); after a buffering-triggered switch the new source starts as attempt 1 with a clean history, where Python's main loop may record one failure for the attempt the switch ended (`:533-534`) unless `update_url`'s clear (`:1512`) lands after it, and so may announce the new source as attempt 2 or 3 with a `channel_reconnect` (N4 of the review); `redact.Line` on event URLs where Python's `redact_url` keeps more (R10); one emitter worker and batching where Python spawns a greenlet per event, with a full queue dropping (R12); `URL_SWITCH_TIMEOUT`, `CHUNK_TIMEOUT`, `RETRY_WAIT_INTERVAL` not read (R13); the `_is_timeout` disconnect reachable only through the keepalive cap on TS (R14, as in Python), and its `url_switching` exemption not ported (R14); the initialization-timeout packet not ported (R15); `channel_pk` sent as null (R9); a concurrent second client on a Redirect channel getting its own 302 rather than a wait (R7); the slot released when the source goroutine returns rather than at the stop path's cleanup, seconds earlier; **the Python defect filed** (R6); **what this PR does not do**: no fMP4 (2c-6); no Output Profile (2c-7); no `channel_start`/`channel_stop`/`client_connect`/`client_disconnect`, no detail endpoint, no `advance`, no drain (2c-8); no Go coverage ratchet and no CodeQL Go pack (2c-9); no nginx route (2d).

---

## Break-check × what each can redden

Every break-check in this plan, and the task it belongs to. A `✓` means it was run against this plan's own verified implementation and the message in the task table is the one that appeared.

| # | Task | The injected defect | What reddens | Verified |
|---|---|---|---|---|
| 1 | 2 | `maxUnhealthyChecks = 1` | `TestDeadAirOnAYoungConnectionSwitchesStreams`, on "never observed unhealthy before it switched" — the sibling clause; the gap assertion is second (Constraint 30) | ✓ |
| 2 | 2 | the window reset disabled | `TestTheRetryWindowResetsTheCounterAfterAnIdleGap`, "counted as 4, want 1" | ✓ |
| 3 | 2 | `>=` becomes `>` on `MaxRetries` | `TestThreeConnectFailuresExhaustTheSourceAndFailOver`, 10 s timeout | ✓ |
| 4 | 2 | the stderr path consults the bound | `TestABufferingFailoverIgnoresMaxStreamSwitches`, 15 s timeout | ✓ |
| 5 | 2 | the `TimedOut` arm no longer switches | `TestASustainedSubThresholdSpeedFailsTheChannelOver`, 15 s timeout | ✓ |
| 6 | 2 | `ResetPosition` skipped on a switch | `TestTheChunkIndexIsMonotonicAcrossAFailover`, "byte 188 is 0xb1, not the sync byte" | ✓ |
| 7 | 2 | `releaseSlot` not deferred | `TestTheSlotIsReleasedOnceWhenTheSourceGoroutineReturns`, 5 s timeout | ✓ |
| 8 | 2 | `new_url` unredacted | `TestThreeConnectFailuresExhaustTheSourceAndFailOver`, the credential named | ✓ |
| 9 | 2 | `degraded_failover` never raised | `TestAFailoverFromTheCacheRaisesDegradedFailoverOnRecovery`, "raised 0 times" | ✓ |
| 10 | 1 | the outage flag never set | `TestTheEmitterLogsOnceIntoAnOutageAndOnceOutOfIt`, "does not report the outage" | ✓ |
| 11 | 3 | `Unavailable` no longer falls back | `TestAFailoverFallsBackToTheCachedCandidatesWhenTheControlPlaneIsDown`, 15 s timeout | ✓ |
| 12 | 3 | every error falls back | `TestARefusedFailoverNeverUsesTheCache`, "did not end after a refused failover" | ✓ |
| 13 | 3 | the client's retry removed | `TestTheDegradedFallbackSpendsTheClientsRetryBudgetFirst`, "saw 2 next-source calls, want 3" | ✓ |
| 14 | 3 | `MAX_RETRIES` falls back to a literal | `…IsRequired/MAX_RETRIES` only | — (run it) |
| 15 | 4 | the Redirect release skipped | `TestARedirectProfileHandsTheClientTheProviderURLAndFetchesNothing`, "release calls = []" | ✓ |
| 16 | 4 | the internal override removed | `TestAnInternalPrincipalOnARedirectChannelIsServedThroughProxy`, "answered 302, want 200" | ✓ |
| 17 | 5 | the keepalive's health gate removed | `TestAnUnhealthyChannelSendsKeepalives…`, "1.004s after the last asset packet, while the channel was still HEALTHY" | ✓ |
| 18 | 5 | the keepalive cap removed | `TestAClientIsDroppedOnceTheKeepaliveCapIsReached`, "did not end within 15s" | ✓ |
| 19 | 5 | `healthy` not rendered | `TestHealthyOnTheListPayloadFollowsTheHealthMonitor` **and** `TestTheLiveEndpointProducesTheGoldensKeySet` | ✓ |
| 20 | 2 | the transcode source's cause reset removed | **nothing** — no stand-in produces a first-attempt-only failure; listed as an unpinned edit | ✓ (green) |
| 21 | 5 | the error packet not sent | `TestAClientWithNoBytesGetsAnErrorPacketWhenEverySourceFails`, "the body is 0 bytes" | ✓ |
| 23 | 2 | `needsReconnect` read but never cleared inside the inner loop (`flagSet` for `takeFlag`) | `TestASecondStableStallIsActedOnAfterAHealthReconnect`, "stall 2: the source ran 2 times, want 3 -- needsReconnect stayed set after the first reconnect and the monitor never cancelled again" | ✓ |
| 22 | 1 | #300's throttle cap put back | nothing reddens; the row-4 arming time moves from 6.5–6.6 s (real quarter rate) to about 12 s (capped) — a measurement, recorded, not a pin | ✓ (6.5 s and 6.6 s with the fix, two runs on this host) |

**Row 1 deserves a second look.** With one check instead of three, the switch happens on the first tick after the threshold, and the test's 20 ms poll usually misses the unhealthy window, so the `sawUnhealthy` clause fires before the gap clause can. Both clauses guard the same mechanism; if on your host the gap clause fires instead, that is the same finding. Neither is the "switch happened" clause, which a one-check monitor also satisfies — which is why the test has the other two.

**Row 22 is a measurement, not a pin.** Row 4's test asserts a floor, and both throttles clear it; what the fix changes is how honest the number under the floor is. If your host reports an arming time under 4 s with the fix, that is the test reddening for its own reason, not this row's.

**Row 20 is listed because it does not redden.** The stale cause would surface only when a transcode child fails on its first attempt and succeeds on its second; no stand-in flag produces that, and the corpus is static. Recorded as an unpinned edit in the PR description rather than pinned by a test that rewrites a fixture between attempts and races the backoff.

---

## What to report back

1. **Task 0's diff** — every appendix file Step 0 found not `identical` to the merged tree, what you carried across, and every ledger row that did not match. This is the report the orchestrator most needs, because this plan's seed was not the implemented tree (§ Sequencing).
2. **The `StateActive` count** at Task 0 (two) and at Task 8 (two, the same lines).
3. **Every break-check's actual failure message**, and specifically whether row 1 reddened on the sibling clause or the gap, whether row 14 reddened on its key alone, whether row 20 stayed green, and row 23's stale-flag message.
4. **The gate's counts** — three `-race` runs of the module, eight of `relay/channel`, three no-race runs of `./ffmpeg ./channel`, and the three-GOOS vet and lint.
5. **The credlint census** — zero findings, two markers added; anything new it reported that this plan does not name.
5a. **#300** — the row-4 arming time with and without the fix on your host and ffmpeg version, beside this plan's 6.5–6.6 s (fix) and 2c-4's 12.2 s (cap), and whether any of the three `Rate 0.05` tests needed a wider window.
6. **The golden file** — whether Django's regeneration matched Appendix AC's edit beyond the one new key.
7. **The lint ledger** — zero new suppressions, 2c-4's eight untouched.
8. **The issue number** filed in Task 7.
9. **The stated divergences**, as a list (Task 8 Step 6).
10. **Ruling R7's Python confirmation** if the container was yours, or that it was not.
11. **Anything in the spec, `CLAUDE.md`, the 2c-4 plan or this plan you found wrong or stale.** The three most likely places: the `file:line` citations into `input/manager.py` (verified at `29224271`; 2c-4's Python task touches `next_source.py`, not this file, but check), this plan's reading of `views.py:645-648`'s `finally` covering the redirect `return`, and the `EffectiveProxySettings` line comments into `apps/proxy/config.py`.

---

## Appendix — the files, in full

Every file below is the whole file as it stands after this PR, built and verified as § Working rules describes. A file this plan **edits** is given whole so an implementer diffs rather than patches; where the diff against 2c-4's version is small, the task names it.

### Appendix A — `relay/control/release.go`

**`relay/control/release.go`**

```go
package control

import (
	"context"
	"encoding/json"
	"fmt"
)

// ReleaseRequest is the body of POST /api/relay/channels/<id>/release,
// apps/proxy/serializers.py's ReleaseRequestSerializer: three optional
// integers, every one of which apps/proxy/control_plane.py:236-240's
// release_source sends as an explicit key, null when unknown. Pointers
// without omitempty reproduce that: the key is always on the wire.
//
// stream_id and m3u_profile_id are what Django's release_source falls back
// to for a channel deleted mid-playback (apps/proxy/next_source.py:961-1011);
// the Python relay reads them out of its own metadata hash
// (live_proxy/server.py:2364-2367) and this relay reads them off the channel's
// SourceInfo. channel_pk is the Channel's numeric primary key, which is on no
// contract field, so this relay never sends it -- the Python relay's normal
// stop path sends it from the hash, and Django uses it only in that same
// deleted-channel fallback, to delete a key it would otherwise leave behind
// (CLAUDE.md § Known defects, #190). Recorded as a stated divergence.
type ReleaseRequest struct {
	StreamID     *int `json:"stream_id"`
	M3UProfileID *int `json:"m3u_profile_id"`
	ChannelPK    *int `json:"channel_pk"`
}

// Release gives a reserved provider slot back. It returns Django's own
// `released` flag, and the same error classes NextSource returns: a Refused
// for a 4xx, an Unavailable for an outage. There is no 404 mapping here --
// control_plane.release_source has none either: a release for an unknown
// identifier is a refusal the caller logs and moves on from
// (live_proxy/server.py:2374-2385).
func (c *Client) Release(ctx context.Context, identifier string, req ReleaseRequest) (bool, error) {
	path := "/api/relay/channels/" + identifier + "/release"
	body, err := json.Marshal(req)
	if err != nil {
		return false, fmt.Errorf("encoding the release request: %w", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
	}
	raw, _, err := c.post(ctx, path, body)
	if err != nil {
		return false, err
	}
	var answer struct {
		Released bool `json:"released"`
	}
	if err := json.Unmarshal(raw, &answer); err != nil {
		return false, &Unavailable{Path: path, Reason: "2xx body did not decode as a release answer", Err: err}
	}
	return answer.Released, nil
}
```

### Appendix B — `relay/control/events.go`

**`relay/control/events.go`**

```go
package control

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// Event is one relay transition, the shape apps/proxy/serializers.py's
// RelayEventSerializer accepts and apps/proxy/control_plane.py:296-311's
// emit_event builds: the type, the channel's id and name, and the two
// identity keys emit_event copies out of details to the top level when
// present (client_id, stream_id). Details is everything else, and it keeps
// its own copy of those two keys exactly as emit_event leaves them there.
//
// A PROVIDER URL NEVER CROSSES HERE UNREDACTED. input/manager.py's
// stream_switch and channel_error carry a URL in details -- through
// redact_url and truncated to 100 characters -- and core/relay_events.py's
// WebSocket push is a field whitelist that drops details entirely. The relay's
// half of that contract is that whatever it puts in details went through
// redact.Line first, and that is the PRODUCERS' job, not this type's or
// channel.emit's: the two sites in package channel that put a URL in
// details (failover's stream_switch, run's channel_error) each call
// redact.Line before building the map. A third site would have to too.
type Event struct {
	Type        string         `json:"type"`
	ChannelID   string         `json:"channel_id,omitempty"`
	ChannelName string         `json:"channel_name,omitempty"`
	ClientID    string         `json:"client_id,omitempty"`
	StreamID    *int           `json:"stream_id,omitempty"`
	Details     map[string]any `json:"details"`
}

// MaxEventsPerBatch is RelayEventBatchSerializer's max_length
// (apps/proxy/serializers.py:272): a larger batch is a 400, which would
// refuse every event in it.
const MaxEventsPerBatch = 200

// PostEvents posts one batch. Unlike NextSource and Release it is the
// caller's job to decide whether a failure matters: Emitter below is the
// fire-and-forget caller, and it never lets an error reach the byte path.
func (c *Client) PostEvents(ctx context.Context, events []Event) error {
	if len(events) == 0 {
		return nil
	}
	if len(events) > MaxEventsPerBatch {
		return fmt.Errorf("control: a batch of %d events exceeds the route's limit of %d", len(events), MaxEventsPerBatch)
	}
	body, err := json.Marshal(struct {
		Events []Event `json:"events"`
	}{events})
	if err != nil {
		return fmt.Errorf("encoding the events batch: %w", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
	}
	_, _, err = c.post(ctx, "/api/relay/events", body)
	return err
}

// Emitter is the port of apps/proxy/control_plane.py:255-329's post_events
// and emit_event: transitions are posted without blocking the caller, an
// outage is logged once on the way in and once on the way out (the
// _events_down flag, module-level there and per-emitter here), and an event
// raised while the control plane is down is LOST, not queued for retry --
// CLAUDE.md § Operationally records that as measured behaviour, and this
// keeps it.
//
// ONE WORKER AND A QUEUE, where Python spawns one greenlet per event. The
// difference is deliberate and in the safe direction: a relay whose control
// plane is slow would otherwise accumulate one blocked goroutine per
// transition for the length of the outage, and the events route accepts up
// to MaxEventsPerBatch per call, so whatever has queued while one batch was
// in flight goes as the next batch. Order is preserved, which the greenlets
// did not guarantee. A full queue drops the newest event with a warning
// rather than blocking: a stall on the byte path is the one cost this
// design exists to refuse (control_plane.py:311-313's own reasoning).
type Emitter struct {
	client *Client
	log    *slog.Logger
	// timeout bounds one batch's post. Zero means the client's own worst
	// case, two attempts of ConnectTimeout+ReadTimeout plus the retry delay.
	timeout time.Duration

	queue chan Event
	done  chan struct{}

	mu   sync.Mutex
	down bool
}

// EmitterQueueDepth is how many events may wait for the worker. At one
// transition per failover and one stats flush per thirty seconds per channel
// (the Python relay's cadence), a thousand is hours of backlog, not seconds.
const EmitterQueueDepth = 1024

// NewEmitter starts the worker. Close stops it.
func NewEmitter(client *Client, log *slog.Logger) *Emitter {
	if log == nil {
		log = slog.Default()
	}
	e := &Emitter{
		client:  client,
		log:     log,
		timeout: 2*(ConnectTimeout+ReadTimeout) + RetryDelay,
		queue:   make(chan Event, EmitterQueueDepth),
		done:    make(chan struct{}),
	}
	go e.run()
	return e
}

// Emit queues one event. It never blocks and never fails: a full queue is
// logged and the event dropped.
func (e *Emitter) Emit(event Event) {
	select {
	case e.queue <- event:
	default:
		e.log.Warn("relay event dropped: the events queue is full", "type", event.Type, "channel", event.ChannelID)
	}
}

// Close stops the worker once the queue has drained. It is what the SIGTERM
// drain (2c-8) will call; tests call it to know every posted batch has been
// recorded by the fake.
func (e *Emitter) Close() {
	close(e.queue)
	<-e.done
}

// Down reports whether the last batch failed: post_events' _events_down.
func (e *Emitter) Down() bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.down
}

func (e *Emitter) run() {
	defer close(e.done)
	for first := range e.queue {
		batch := []Event{first}
		// Whatever else is already waiting goes in the same batch, up to
		// the route's limit.
	drain:
		for len(batch) < MaxEventsPerBatch {
			select {
			case next, ok := <-e.queue:
				if !ok {
					break drain
				}
				batch = append(batch, next)
			default:
				break drain
			}
		}
		e.post(batch)
	}
}

// post is post_events' disposition (control_plane.py:265-329), one log line
// per transition into and out of an outage rather than one per batch.
func (e *Emitter) post(batch []Event) {
	ctx, cancel := context.WithTimeout(context.Background(), e.timeout)
	defer cancel()
	err := e.client.PostEvents(ctx, batch)

	e.mu.Lock()
	defer e.mu.Unlock()

	var refused *Refused
	var misconfigured *ErrNotConfigured
	switch {
	case err == nil:
		if e.down {
			e.log.Info("relay events reachable again after an outage")
			e.down = false
		}
	case errors.As(err, &refused):
		if e.down {
			e.log.Debug("relay events refused", "status", refused.Status, "events", len(batch))
		} else {
			e.log.Error("relay events refused", "status", refused.Status, "events", len(batch))
			e.down = true
		}
	case errors.As(err, &misconfigured):
		// The variable name only, never the value: control_plane.py:297-315's
		// own rule, for the same reason -- the value can carry userinfo.
		if e.down {
			e.log.Debug("could not post relay events: the control-plane address is misconfigured", "variable", misconfigured.Variable, "events", len(batch))
		} else {
			e.log.Error("could not post relay events: the control-plane address is misconfigured", "variable", misconfigured.Variable, "events", len(batch))
			e.down = true
		}
	default:
		if e.down {
			e.log.Debug("could not post relay events", "events", len(batch), "error", redact.Error(err))
		} else {
			e.log.Warn("could not post relay events", "events", len(batch), "error", redact.Error(err))
			e.down = true
		}
	}
}
```

### Appendix C — `relay/control/release_test.go`

**`relay/control/release_test.go`**

```go
package control

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The release body is ReleaseRequestSerializer's, every key present and null
// when unknown, exactly as control_plane.release_source sends it; the answer
// is Django's own flag.
func TestReleaseSendsAllThreeKeysAndReadsTheFlag(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
	t.Cleanup(cp.Close)
	streamID := 41
	released, err := testClient(t, cp).Release(context.Background(), "c-1", ReleaseRequest{StreamID: &streamID})
	if err != nil || !released {
		t.Fatalf("Release = %v, %v; want true, nil", released, err)
	}
	seen := cp.RequestsTo("/release")
	if len(seen) != 1 || seen[0].Path != "/api/relay/channels/c-1/release" {
		t.Fatalf("the fake saw %+v", seen)
	}
	var body map[string]any
	if err := json.Unmarshal(seen[0].Body, &body); err != nil {
		t.Fatalf("decoding: %v", err)
	}
	for _, key := range []string{"stream_id", "m3u_profile_id", "channel_pk"} {
		if _, present := body[key]; !present {
			t.Fatalf("release body %s lacks %q: control_plane.release_source sends every key", seen[0].Body, key)
		}
	}
	if body["stream_id"] != 41.0 || body["m3u_profile_id"] != nil || body["channel_pk"] != nil {
		t.Fatalf("release body = %s", seen[0].Body)
	}
	if seen[0].Header.Get(HeaderInternalRequest) == "" {
		t.Fatal("the release was not signed")
	}
}

// The disposition table applies to release as it does to next-source: a 4xx
// is a Refused and is not retried; a 5xx is retried once and is Unavailable.
func TestReleaseFollowsTheDispositionTable(t *testing.T) {
	refusing := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusNotFound})
	t.Cleanup(refusing.Close)
	_, err := testClient(t, refusing).Release(context.Background(), "c-1", ReleaseRequest{})
	var refused *Refused
	if !errors.As(err, &refused) || refused.Status != http.StatusNotFound {
		t.Fatalf("a 404 on release = %v, want a Refused carrying 404 (no 404 mapping here, unlike next-source)", err)
	}
	if n := len(refusing.Requests()); n != 1 {
		t.Fatalf("a 404 was retried: %d requests", n)
	}

	down := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusBadGateway})
	t.Cleanup(down.Close)
	_, err = testClient(t, down).Release(context.Background(), "c-1", ReleaseRequest{})
	var unavailable *Unavailable
	if !errors.As(err, &unavailable) {
		t.Fatalf("a 502 on release = %v, want an Unavailable", err)
	}
	if n := len(down.Requests()); n != 2 {
		t.Fatalf("a 502 was attempted %d times, want 2", n)
	}
}
```

### Appendix D — `relay/control/events_test.go`

**`relay/control/events_test.go`**

```go
package control

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The batch reaches Django in RelayEventBatchSerializer's shape, signed with
// both internal headers, and the identity keys ride at the top level the way
// emit_event puts them there.
func TestPostEventsSendsTheBatchDjangoAccepts(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
	t.Cleanup(cp.Close)
	client := testClient(t, cp)
	streamID := 41
	err := client.PostEvents(context.Background(), []Event{
		{Type: "stream_switch", ChannelID: "c-1", ChannelName: "BBC One", StreamID: &streamID, Details: map[string]any{"new_url": "http://host/[redacted]", "stream_id": 41}},
		{Type: "channel_buffering", ChannelID: "c-1", Details: map[string]any{"speed": 0.8}},
	})
	if err != nil {
		t.Fatalf("PostEvents: %v", err)
	}
	seen := cp.RequestsTo("/events")
	if len(seen) != 1 || seen[0].Method != http.MethodPost {
		t.Fatalf("the fake saw %+v, want one POST to /api/relay/events", seen)
	}
	if seen[0].Header.Get(HeaderInternal) == "" || seen[0].Header.Get(HeaderInternalRequest) == "" {
		t.Fatal("the batch was not signed with both internal headers")
	}
	var body struct {
		Events []map[string]any `json:"events"`
	}
	if err := json.Unmarshal(seen[0].Body, &body); err != nil || len(body.Events) != 2 {
		t.Fatalf("body = %s", seen[0].Body)
	}
	if body.Events[0]["stream_id"] != 41.0 || body.Events[0]["channel_name"] != "BBC One" || body.Events[0]["type"] != "stream_switch" {
		t.Fatalf("the first event lost its identity keys: %v", body.Events[0])
	}
	if _, present := body.Events[1]["stream_id"]; present {
		t.Fatal("an event with no stream id carried the key")
	}
	if got := cp.Events(); len(got) != 2 || got[0].Details["new_url"] != "http://host/[redacted]" {
		t.Fatalf("the fake recorded %+v", got)
	}
}

// A batch over the route's limit is refused before it is sent: a 400 from
// Django would refuse every event in it.
func TestABatchOverTheRoutesLimitIsRefusedLocally(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
	t.Cleanup(cp.Close)
	batch := make([]Event, MaxEventsPerBatch+1)
	for i := range batch {
		batch[i] = Event{Type: "channel_buffering"}
	}
	if err := testClient(t, cp).PostEvents(context.Background(), batch); err == nil {
		t.Fatal("a batch of 201 events was sent")
	}
	if len(cp.Requests()) != 0 {
		t.Fatal("the oversized batch reached the control plane")
	}
	if MaxEventsPerBatch != 200 {
		t.Errorf("MaxEventsPerBatch = %d, want 200 (apps/proxy/serializers.py:272's max_length)", MaxEventsPerBatch)
	}
}

// logCapture keeps every line an slog handler writes.
type logCapture struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (c *logCapture) Write(p []byte) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.buf.Write(p)
}

func (c *logCapture) count(substr string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return strings.Count(c.buf.String(), substr)
}

// THE OUTAGE FLAG (control_plane.py:255-329): three batches failing during
// an outage log ONE warning, not three; the batch that succeeds afterwards
// logs one recovery line; and the events raised during the outage are lost,
// not delivered late (CLAUDE.md § Operationally).
func TestTheEmitterLogsOnceIntoAnOutageAndOnceOutOfIt(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
	t.Cleanup(cp.Close)
	logs := &logCapture{}
	emitter := NewEmitter(testClient(t, cp), slog.New(slog.NewTextHandler(logs, &slog.HandlerOptions{Level: slog.LevelDebug})))
	// Small enough that each Emit is its own batch: the worker is idle
	// between them.
	emitter.timeout = 2 * time.Second

	cp.SetStatus(http.StatusServiceUnavailable)
	for i := 0; i < 3; i++ {
		emitter.Emit(Event{Type: "channel_buffering", ChannelID: "c-1"})
		// Wait for the worker to have posted it before the next, so three
		// batches are posted rather than one batch of three.
		deadline := time.Now().Add(5 * time.Second)
		for len(cp.RequestsTo("/events")) < 2*(i+1) && time.Now().Before(deadline) {
			time.Sleep(10 * time.Millisecond)
		}
	}
	if !emitter.Down() {
		t.Fatal("the emitter does not report the outage")
	}
	// The handler captures DEBUG too, so count the WARN line alone: the
	// later batches are logged at DEBUG, which is the whole point.
	if got := logs.count("level=WARN msg=\"could not post relay events\""); got != 1 {
		t.Fatalf("the outage was logged at WARN %d times, want once on the transition", got)
	}

	cp.SetStatus(0)
	emitter.Emit(Event{Type: "channel_failover", ChannelID: "c-1"})
	emitter.Close()
	if emitter.Down() {
		t.Fatal("the emitter still reports the outage after a successful batch")
	}
	if got := logs.count("level=INFO msg=\"relay events reachable again"); got != 1 {
		t.Fatalf("the recovery was logged %d times, want once", got)
	}
	// Six failed posts (three batches, each retried once), then one that
	// landed: only the last event is in the fake's log.
	if got := cp.EventsOfType("channel_buffering"); len(got) != 0 {
		t.Fatalf("%d events raised during the outage were delivered; they must be lost, not queued", len(got))
	}
	if got := cp.EventsOfType("channel_failover"); len(got) != 1 {
		t.Fatalf("the event raised after recovery was not delivered: %+v", got)
	}
}

// A refusal is logged as an error, once, and not retried.
func TestARefusedEventsRouteIsLoggedOnceAndNotRetried(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusForbidden})
	t.Cleanup(cp.Close)
	logs := &logCapture{}
	emitter := NewEmitter(testClient(t, cp), slog.New(slog.NewTextHandler(logs, nil)))
	emitter.Emit(Event{Type: "channel_buffering"})
	emitter.Emit(Event{Type: "channel_buffering"})
	emitter.Close()
	if got := logs.count("relay events refused"); got != 1 {
		t.Fatalf("the refusal was logged %d times, want once", got)
	}
	if n := len(cp.RequestsTo("/events")); n < 1 || n > 2 {
		t.Fatalf("the fake saw %d event posts, want one or two batches and no retries of a 403", n)
	}
}

// Emit never blocks: a full queue drops with a warning rather than stalling
// the caller. The worker is held in a post that will time out while the
// queue is filled past its depth.
func TestEmitNeverBlocksOnAFullQueue(t *testing.T) {
	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Delay: 500 * time.Millisecond})
	t.Cleanup(cp.Close)
	logs := &logCapture{}
	client := testClient(t, cp)
	client.HTTP = &http.Client{Timeout: 100 * time.Millisecond}
	emitter := NewEmitter(client, slog.New(slog.NewTextHandler(logs, nil)))
	emitter.timeout = 100 * time.Millisecond
	t.Cleanup(emitter.Close)

	emitter.Emit(Event{Type: "channel_buffering"})
	deadline := time.Now().Add(2 * time.Second)
	for len(cp.RequestsTo("/events")) == 0 && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		for i := 0; i < EmitterQueueDepth+50; i++ {
			emitter.Emit(Event{Type: "channel_buffering"})
		}
	}()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Emit blocked on a full queue")
	}
	if logs.count("events queue is full") == 0 {
		t.Fatal("no drop was logged")
	}
}

var _ = errors.Is
```

### Appendix E — `relay/internal/relaytest/controlplane.go`

**`relay/internal/relaytest/controlplane.go`**

```go
package relaytest

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
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
		"BUFFER_CHUNK_SIZE":           255868,                     // apps/proxy/config.py:15, 188 * 1361
		"DEFAULT_USER_AGENT":          "VLC/3.0.20 LibVLC/3.0.20", // :6
		"CHUNK_SIZE":                  8192,                       // :7
		"STREAM_TIMEOUT":              20,                         // :103
		"FAILOVER_GRACE_PERIOD":       20,                         // :120
		"KEEPALIVE_INTERVAL":          0.5,                        // :97
		"MAX_KEEPALIVE_DURATION":      300,                        // :122
		"CONNECTION_TIMEOUT":          10,                         // :13
		"HEALTH_CHECK_INTERVAL":       5,                          // :104
		"MAX_RETRIES":                 3,                          // :9
		"RETRY_WINDOW_SECONDS":        1800,                       // :10
		"STABLE_CONNECTION_THRESHOLD": 30,                         // :11
		"MAX_STREAM_SWITCHES":         10,                         // :14
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

	// Delay holds every answer for this long before writing it. Zero is the
	// ordinary immediate answer. 2c-3's R11 test needs a next-source call
	// still in flight when a client disconnects, and there is no other way
	// to arrange that deterministically.
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

	// Alternates are the channel's other streams, in the order Django's
	// own traversal would offer them (2c-5). SourceURL is stream 1; each
	// alternate names its own stream id and URL. A next-source call whose
	// exclude_stream_ids or current_url rules out stream 1 is answered
	// with the first alternate it does not rule out, and a call with
	// include_alternates lists the rest -- the shape resolve_source
	// (apps/proxy/next_source.py:804-960) produces. With none, the fake
	// answers a null source once stream 1 is excluded, which is Django's
	// "no candidate" answer.
	Alternates []AlternateConfig

	// SlotReserved is the source's slot_reserved flag. Nil means true, the
	// value every earlier fixture sent.
	SlotReserved *bool
}

// AlternateConfig is one alternate stream the fake offers. Argv is the
// built argv for THIS stream's URL, as Django builds one per candidate
// (Amendment A4.1); nil renders as [] under the config's Command.
type AlternateConfig struct {
	StreamID  int
	URL       string
	UserAgent string
	Argv      []string
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
	events   []RecordedEvent
	settings map[string]any
	status   int
	delay    time.Duration
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

// SetStatus makes every LATER call answer with status, whatever the route:
// 503 is an outage the client retries once and then degrades on, 403 a
// refusal it never degrades on. Zero restores the configured behaviour. It is
// how a test takes the control plane down AFTER a tune succeeded, which is
// the only moment the degraded fallback can be observed.
func (c *ControlPlane) SetStatus(status int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.status = status
}

// SetDelay holds every LATER answer for d before writing it, overriding the
// config's Delay: how a test makes the control plane slow AFTER a tune, so
// a failover's own budget can be watched being spent. Zero restores it.
func (c *ControlPlane) SetDelay(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.delay = d
}

// RecordedRequest is one call the fake received, and when.
type RecordedRequest struct {
	Method string
	Path   string
	Header http.Header
	Body   []byte
	At     time.Time
}

// RecordedEvent is one event out of a posted batch, decoded.
type RecordedEvent struct {
	Type        string
	ChannelID   string
	ChannelName string
	StreamID    *int
	Details     map[string]any
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
			At:     time.Now(),
		})
		forced := c.status
		delay := c.delay
		c.mu.Unlock()

		if delay == 0 {
			delay = cfg.Delay
		}
		if delay > 0 {
			time.Sleep(delay)
		}

		switch {
		case cfg.RedirectTo != "":
			http.Redirect(w, r, cfg.RedirectTo, http.StatusFound)
			return
		case seen < cfg.FailFirst:
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		case forced != 0 && forced != http.StatusOK:
			w.WriteHeader(forced)
			_, _ = w.Write([]byte(`{"detail":"relaytest: status set by the test"}`))
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

		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "/release"):
			// apps/proxy/api_views.py:96-100: ReleaseResponseSerializer.
			_ = json.NewEncoder(w).Encode(map[string]any{"released": true})
		case strings.HasSuffix(r.URL.Path, "/events"):
			c.recordEvents(body)
			var batch struct {
				Events []json.RawMessage `json:"events"`
			}
			_ = json.Unmarshal(body, &batch)
			_ = json.NewEncoder(w).Encode(map[string]any{"accepted": len(batch.Events), "rejected": 0})
		default:
			_ = json.NewEncoder(w).Encode(c.nextSourceAnswer(cfg, body))
		}
	}))
	return c
}

func (c *ControlPlane) recordEvents(body []byte) {
	var batch struct {
		Events []struct {
			Type        string         `json:"type"`
			ChannelID   string         `json:"channel_id"`
			ChannelName string         `json:"channel_name"`
			StreamID    *int           `json:"stream_id"`
			Details     map[string]any `json:"details"`
		} `json:"events"`
	}
	if err := json.Unmarshal(body, &batch); err != nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, e := range batch.Events {
		c.events = append(c.events, RecordedEvent{Type: e.Type, ChannelID: e.ChannelID, ChannelName: e.ChannelName, StreamID: e.StreamID, Details: e.Details})
	}
}

// nextSourceAnswer picks a candidate the way Django's resolve_source does:
// the first of stream 1 and the alternates, in order, that the request's
// exclude_stream_ids does not name and whose URL is not the current_url
// (apps/proxy/next_source.py:242-368's own "already playing" rejection),
// or a null source.
func (c *ControlPlane) nextSourceAnswer(cfg ControlPlaneConfig, body []byte) map[string]any {
	var req struct {
		Exclude           []int  `json:"exclude_stream_ids"`
		CurrentURL        string `json:"current_url"`
		IncludeAlternates bool   `json:"include_alternates"`
	}
	_ = json.Unmarshal(body, &req)
	excluded := map[int]bool{}
	for _, id := range req.Exclude {
		excluded[id] = true
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
	slotReserved := true
	if cfg.SlotReserved != nil {
		slotReserved = *cfg.SlotReserved
	}

	type candidate struct {
		id        int
		url       string
		userAgent string
		argv      []string
	}
	var candidates []candidate
	if cfg.SourceURL != "" {
		candidates = append(candidates, candidate{1, cfg.SourceURL, userAgent, cfg.Argv})
	}
	for _, alt := range cfg.Alternates {
		ua := alt.UserAgent
		if ua == "" {
			ua = userAgent
		}
		candidates = append(candidates, candidate{alt.StreamID, alt.URL, ua, alt.Argv})
	}
	render := func(cand candidate) map[string]any {
		return map[string]any{
			"stream_id":             cand.id,
			"url":                   cand.url,
			"user_agent":            cand.userAgent,
			"transcode":             kind == "transcode",
			"m3u_profile_id":        1,
			"slot_reserved":         slotReserved,
			"channel_name":          "Test Channel",
			"stream_name":           "Test Stream",
			"m3u_profile_name":      "Test Profile",
			"stream_profile":        profile(1, cfg.Command, cand.argv),
			"ffmpeg_stream_profile": ffmpegProfile,
		}
	}

	answer := map[string]any{
		"alternates":      []any{},
		"error":           nil,
		"proxy_settings":  settings,
		"output_profiles": map[string]any{},
		"source":          nil,
	}
	chosen := -1
	for i, cand := range candidates {
		if excluded[cand.id] || (req.CurrentURL != "" && cand.url == req.CurrentURL) {
			continue
		}
		chosen = i
		break
	}
	if chosen < 0 {
		return answer
	}
	answer["source"] = render(candidates[chosen])
	if req.IncludeAlternates {
		alternates := []any{}
		for i, cand := range candidates {
			if i != chosen {
				alternates = append(alternates, render(cand))
			}
		}
		answer["alternates"] = alternates
	}
	return answer
}

// URL is the base URL to hand a control.Client.
func (c *ControlPlane) URL() string { return c.server.URL }

// Requests is every call the fake has received, in order.
func (c *ControlPlane) Requests() []RecordedRequest {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]RecordedRequest(nil), c.requests...)
}

// RequestsTo is every call whose path ends with suffix, in order: "/release",
// "/events" or "/next-source".
func (c *ControlPlane) RequestsTo(suffix string) []RecordedRequest {
	var out []RecordedRequest
	for _, r := range c.Requests() {
		if strings.HasSuffix(strings.SplitN(r.Path, "?", 2)[0], suffix) {
			out = append(out, r)
		}
	}
	return out
}

// Events is every event the fake has been posted, in order.
func (c *ControlPlane) Events() []RecordedEvent {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]RecordedEvent(nil), c.events...)
}

// EventsOfType is Events filtered to one type.
func (c *ControlPlane) EventsOfType(typ string) []RecordedEvent {
	var out []RecordedEvent
	for _, e := range c.Events() {
		if e.Type == typ {
			out = append(out, e)
		}
	}
	return out
}

// Close stops the fake. A relay whose control plane has been closed sees a
// transport failure on its next call, which is the other shape of
// control.Unavailable beside SetStatus's 5xx.
func (c *ControlPlane) Close() { c.server.Close() }
```

### Appendix F — `relay/internal/relaytest/upstream.go`

The whole file after 2c-5: `DeadAirAfterBytes`, `Methods`, and the #300 throttle fix (Task 1 Step 1), whose comment cites the issue.

**`relay/internal/relaytest/upstream.go`**

```go
package relaytest

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"time"
)

// WriteChunk is how much the upstream writes to the wire at a time: 50 TS
// packets, apps/proxy/live_proxy/tests/harness/upstream.py:31's
// _WRITE_CHUNK. Pinned by TestNominalByteRateAndWriteChunkMatchThePythonHarness.
const WriteChunk = PacketSize * 50

// Config shapes one Upstream. The zero value is a valid unpaced upstream
// serving 512 synthetic packets on a loop, which is what most tests want.
type Config struct {
	// Payload is the asset to loop. Nil means SyntheticTS(512, 0x100).
	Payload []byte

	// Status is the response status. Zero means 200; any other value is sent
	// with a short JSON body and no stream.
	Status int

	// Rate paces the response at Rate * NominalByteRate bytes per second.
	// Zero means unpaced.
	//
	// UNPACED BY DEFAULT, and that is a DELIBERATE divergence from
	// harness/upstream.py, whose FakeUpstream defaults to 1.0. Its docstring
	// gives the reason: unpaced, it pushed ~34 MB/s into Redis and filled DB
	// 0 -- shared with the Celery broker and the Django cache -- to 2.17 GB in
	// 50 seconds, taking the test process down. Spec D2 deletes that failure
	// mode: the Go ring is bounded at MaxBytesPerChannel per channel by
	// construction, so an unpaced upstream costs a bounded 73 MiB and a much
	// faster test. Set Rate when the test's subject is throughput.
	Rate float64

	// StopAfterBytes ends the response after this many bytes. Zero means the
	// loop runs until the client goes away.
	StopAfterBytes int

	// Abrupt makes StopAfterBytes abort the response rather than end it
	// cleanly, so the reader sees a broken connection instead of EOF.
	Abrupt bool

	// DeadAir sends the 200 and the headers, then nothing at all for this
	// long -- exactly what a provider that stops producing looks like from
	// the relay's side. 2c-5's dead-air trigger (parity-matrix row 2) acts
	// on it.
	DeadAir time.Duration

	// DeadAirAfterBytes sends this many bytes and then nothing at all until
	// the client goes away: a provider that STOPPED rather than one that
	// never started, which is the shape that takes the relay past its
	// init grace period and onto CONNECTION_TIMEOUT (input/manager.py:
	// 1547-1551). Zero means no dead air. harness/standin.py's
	// --dead-air-after-bytes, on the upstream rather than the child.
	DeadAirAfterBytes int
}

// Upstream is a looping TS provider on 127.0.0.1.
type Upstream struct {
	server *httptest.Server

	mu       sync.Mutex
	requests int
	headers  []http.Header
	methods  []string
}

// NewUpstream starts an upstream. Register its Close with t.Cleanup.
func NewUpstream(cfg Config) *Upstream {
	payload := cfg.Payload
	if payload == nil {
		payload = SyntheticTS(512, 0x100)
	}
	if len(payload) == 0 {
		panic("relaytest: payload must not be empty")
	}

	u := &Upstream{}
	u.server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		u.mu.Lock()
		u.requests++
		u.headers = append(u.headers, r.Header.Clone())
		u.methods = append(u.methods, r.Method)
		u.mu.Unlock()
		u.serve(w, r, cfg, payload)
	}))
	return u
}

// URL is the upstream's stream URL.
func (u *Upstream) URL() string { return u.server.URL + "/live.ts" }

// Requests is how many HTTP requests the upstream has answered. The count a
// "three clients share exactly one upstream connection" assertion reads.
func (u *Upstream) Requests() int {
	u.mu.Lock()
	defer u.mu.Unlock()
	return u.requests
}

// Headers is the header set of each request the upstream answered, in order.
// Cloned at receipt, so a test reading them races nothing.
func (u *Upstream) Headers() []http.Header {
	u.mu.Lock()
	defer u.mu.Unlock()
	return append([]http.Header(nil), u.headers...)
}

// Methods is the HTTP method of each request the upstream answered, in
// order -- how a test tells a HEAD probe from a GET that would have streamed.
func (u *Upstream) Methods() []string {
	u.mu.Lock()
	defer u.mu.Unlock()
	return append([]string(nil), u.methods...)
}

// Close stops the server and waits for its handlers.
func (u *Upstream) Close() { u.server.Close() }

func (u *Upstream) serve(w http.ResponseWriter, r *http.Request, cfg Config, payload []byte) {
	if cfg.Status != 0 && cfg.Status != http.StatusOK {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(cfg.Status)
		_, _ = w.Write([]byte(`{"error":"relaytest: configured status"}`))
		return
	}

	w.Header().Set("Content-Type", "video/mp2t")
	w.WriteHeader(http.StatusOK)
	rc := http.NewResponseController(w)
	if err := rc.Flush(); err != nil {
		return
	}

	if cfg.DeadAir > 0 {
		select {
		case <-r.Context().Done():
		case <-time.After(cfg.DeadAir):
		}
		return
	}

	var rate float64
	if cfg.Rate > 0 {
		rate = cfg.Rate * NominalByteRate
	}

	sent := 0
	at := 0
	started := time.Now()
	for {
		if cfg.StopAfterBytes > 0 && sent >= cfg.StopAfterBytes {
			if cfg.Abrupt {
				// The stdlib's own way to end a response without a clean
				// terminator. It also suppresses the server's stack trace,
				// which an ordinary panic would print over every test.
				panic(http.ErrAbortHandler)
			}
			return
		}
		if r.Context().Err() != nil {
			return
		}
		if cfg.DeadAirAfterBytes > 0 && sent >= cfg.DeadAirAfterBytes {
			// Connected, silent, and still here: the relay's watchdog is
			// what ends this, by hanging up.
			<-r.Context().Done()
			return
		}

		want := WriteChunk
		if cfg.StopAfterBytes > 0 && cfg.StopAfterBytes-sent < want {
			want = cfg.StopAfterBytes - sent
		}
		if cfg.DeadAirAfterBytes > 0 && cfg.DeadAirAfterBytes-sent < want {
			want = cfg.DeadAirAfterBytes - sent
		}
		piece := make([]byte, 0, want)
		for len(piece) < want {
			take := min(want-len(piece), len(payload)-at)
			piece = append(piece, payload[at:at+take]...)
			at = (at + take) % len(payload)
		}

		if _, err := w.Write(piece); err != nil {
			// The relay closed its side -- an ordinary end to a tune.
			return
		}
		if err := rc.Flush(); err != nil && !errors.Is(err, http.ErrNotSupported) {
			return
		}
		sent += len(piece)

		if rate > 0 {
			due := started.Add(time.Duration(float64(sent) / rate * float64(time.Second)))
			// Sleep UNTIL DUE, in steps of at most 250 ms so a client that
			// has gone is noticed within a step rather than after the whole
			// wait. An earlier form slept min(wait, 250ms) ONCE, capping the
			// total wait: any rate below ~37,600 B/s was delivered faster
			// than configured -- Rate 0.05 fixtures about three times too
			// fast, row 4's quarter-rate upstream looping every 13.5 s
			// instead of 32 s (issue #300, found by the 2c-4 review).
			for {
				wait := time.Until(due)
				if wait <= 0 || r.Context().Err() != nil {
					break
				}
				time.Sleep(min(wait, 250*time.Millisecond))
			}
		}
	}
}
```

### Appendix G — `relay/channel/channel.go`

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
	startedAt time.Time
	now       func() time.Time
	// channelName is StreamManager.channel_name: resolved once at construction
	// (input/manager.py:41-44) and carried on every event, unchanged by a
	// failover -- the SourceInfo's name can move, this one does not.
	channelName string

	// resolver, events and release are the channel's three ways of reaching
	// the control plane, handed in by the manager (release) and the tune
	// (resolver) and never touched again. Nil resolver means no failover;
	// events is never nil.
	resolver Resolver
	events   EventSink
	release  func(id string, info SourceInfo)
	// ctx is the channel's own context, for the stderr reader's failover,
	// which has no context of its own to make the control-plane call with.
	ctx context.Context

	mu      sync.RWMutex
	state   State
	lastErr error
	// source is what the channel is playing NOW. Guarded by mu since 2c-5,
	// because a failover rewrites it (input/manager.py:2160-2171's hset).
	source SourceInfo
	// stats is what a transcode process has reported (stats.go). Empty for
	// the Proxy architecture, which spawns nothing -- parity-matrix row 29.
	stats Stats
	// clients is the registry. Guarded by mu; the manager reads its length
	// through Clients() inside its own critical section, which is what makes
	// stopIfStillIdle's re-check and claim's addClient mutually exclusive.
	clients map[string]*Client

	// The health monitor's view (health.go), all under mu: StreamManager's
	// healthy, connected, last_data_time and connection_start_time, and the
	// two recovery flags it raises for the run loop. url_switching is NOT
	// here: the one thing that read it, _is_timeout's exemption, is not
	// ported (the 2c-5 plan's Ruling R14).
	healthy        bool
	connected      bool
	lastData       time.Time
	connStart      time.Time
	needsReconnect bool
	needsSwitch    bool
	// cancelAttempt ends the attempt currently running, so the health monitor
	// and the stderr reader can make the run loop act now rather than at the
	// next read. Nil between attempts.
	cancelAttempt context.CancelFunc

	// The switch bookkeeping (failover.go): tried_stream_ids,
	// current_stream_id, _failover_degraded, and the source a
	// buffering-triggered switch has adopted and parked for the run loop.
	// tried and currentStreamID are under mu; switchMu serialises failover
	// itself, whose control-plane call must not hold mu.
	switchMu         sync.Mutex
	tried            map[int]bool
	currentStreamID  int
	failoverDegraded bool
	pending          *Resolved
	failures         failureCounter

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

// Source is what the next-source answer said about this channel's stream --
// the CURRENT one, after any failover.
func (c *Channel) Source() SourceInfo {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.source
}

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

// run is the channel's supervisor goroutine, the port of StreamManager.run
// (input/manager.py:384-709). Exactly one per channel, started by the
// manager.
//
// THE SHAPE IS PYTHON'S, loop for loop. The outer loop is one source at a
// time and is bounded by MaxStreamSwitches; the inner loop is one attempt at
// a time on that source and is bounded by MaxRetries. An attempt is one
// Source.Run: it ends on a clean EOF, an error, or a cancellation the health
// monitor or the stderr reader asked for. EVERY end that is not a stop is a
// connection failure, a clean EOF included -- "Server closed connection",
// :1870-1875 -- counted and retried with backoff (:555-563), until the
// counter reaches MaxRetries and the source is exhausted (:534-537,
// parity-matrix row 3), at which point the resolver is asked for the next
// one (:596-611). The health monitor's switch request is honoured after the
// attempt it ended (:505-507, :428-438); its RECONNECT request is cleared
// inside the inner loop and falls through to the failure accounting
// (:521-534), so the reconnect is simply the next attempt on the same URL.
// The outer loop's own reconnect branch (:414-426, _attempt_reconnect) is
// NOT ported, because it is unreachable in Python: the monitor sets the flag
// only while connected (:1565), and :527 clears it on every pass of the
// inner loop before the outer loop's top can see it. The stderr reader's
// buffering switch is adopted between attempts too (failover.go). Out of
// sources, the channel ends in error naming the count (:678-682).
//
// It does NOT remove itself from the manager's map. Manager.claim drops a
// channel whose ring has closed, and that is the only place it happens: two
// mechanisms for one property means deleting either one changes no test,
// because the other covers for it silently.
func (c *Channel) run(ctx context.Context, first Source) {
	defer c.releaseSlot()
	defer close(c.done)
	defer c.ring.Close()

	c.setState(StateWaitingForClients, nil)
	go c.promoteOnFirstChunk(ctx)
	go c.monitorHealth(ctx)

	source := first
	switches := 0
	var last error
	for ctx.Err() == nil && switches <= c.tuning.MaxStreamSwitches {
		urlFailed := false
		for ctx.Err() == nil && c.failures.count < c.tuning.MaxRetries && !urlFailed && !c.flagSet(&c.needsSwitch) {
			attempt := c.failures.count + 1
			if attempt > 1 {
				// :486-496, on a retry. Python raises it once the connection
				// is established; a Source has no such moment, so it is
				// raised as the attempt starts -- a transcode spawn that
				// fails at once will have announced a reconnect it never
				// made, which Python would not have. Stated, not hidden.
				c.emit("channel_reconnect", map[string]any{"attempt": attempt, "max_attempts": c.tuning.MaxRetries})
			}
			c.log.Info("connection attempt", "channel", c.id, "attempt", attempt, "max", c.tuning.MaxRetries)

			startedAt := c.now()
			err := c.runAttempt(ctx, source)
			if ctx.Err() != nil {
				break
			}
			if resolved := c.takePending(); resolved != nil {
				// The stderr reader switched on a buffering timeout
				// (:1178-1211) and has already cleared the failure history,
				// as update_url does. It never touched `switches`: row 6.
				source = resolved.Source
				break
			}
			if c.flagSet(&c.needsSwitch) {
				// :505-507: leave for the switch without counting a failure.
				c.log.Info("stream needs to switch", "channel", c.id, "after", c.now().Sub(startedAt).Round(100*time.Millisecond))
				break
			}
			if duration := c.now().Sub(startedAt); duration >= c.tuning.StableThreshold {
				// :508-513: a stable run resets the rotation.
				c.log.Info("stream was stable; resetting the switch rotation", "channel", c.id, "duration", duration.Round(time.Second))
				c.noteStable()
				switches = 0
			}
			if c.takeFlag(&c.needsReconnect) {
				// :521-531: the monitor asked for a same-URL reconnect on a
				// stream that had been stable. The flag is CLEARED HERE, on
				// every pass, and the attempt it ended falls through to the
				// failure accounting below -- "Repeated health reconnects
				// count toward max_retries like any other URL failure" -- so
				// the reconnect is the next attempt, announced by the
				// channel_reconnect above like any retry. Clearing it
				// anywhere else leaves the monitor's own `if not
				// needs_reconnect` guard (:1581) shut, and a second stall on
				// the same stream is never acted on; the 2c-5 plan's
				// reviewer reproduced exactly that against an earlier shape
				// of this loop.
				c.log.Info("health monitor requested reconnect", "channel", c.id)
			}

			if err == nil {
				err = errUpstreamEnded
			}
			last = err
			failures := c.failures.record()
			if failures >= c.tuning.MaxRetries {
				urlFailed = true
				c.log.Warn("maximum retry attempts reached for this URL", "channel", c.id, "attempts", c.tuning.MaxRetries, "error", redact.Error(err))
				// :541-551.
				c.emit("channel_error", map[string]any{
					"error_type": "connection_failed",
					"url":        truncate(redact.Line(c.Source().URL), 100),
					"attempts":   c.tuning.MaxRetries,
				})
				continue
			}
			wait := retryBackoff(failures)
			c.log.Info("reconnecting after a connection failure", "channel", c.id, "in", wait, "attempt", failures, "max", c.tuning.MaxRetries, "error", redact.Error(err))
			select {
			case <-ctx.Done():
			case <-time.After(wait):
			}
		}
		if ctx.Err() != nil {
			break
		}

		if c.takeFlag(&c.needsSwitch) {
			// :428-438: the health monitor's switch.
			if resolved, ok := c.failover(ctx, "health_monitor"); ok {
				switches++
				source = resolved.Source
				continue
			}
			// "Continue with normal flow": the same URL, retried.
			c.failures.clear()
			continue
		}
		if urlFailed {
			// :596-611.
			if resolved, ok := c.failover(ctx, "max_retries_exceeded"); ok {
				switches++
				source = resolved.Source
				continue
			}
			c.log.Error("no alternative stream after the switch attempts", "channel", c.id, "switches", switches)
			break
		}
	}

	switch {
	case ctx.Err() != nil:
		c.log.Info("channel stopped", "channel", c.id)
		c.setState(StateStopped, nil)
	default:
		// :678-682: the ERROR state and its message, for the client waiting
		// on its first byte.
		c.mu.RLock()
		tried := len(c.tried)
		c.mu.RUnlock()
		err := &ErrSourcesExhausted{Tried: tried, Attempts: c.tuning.MaxRetries, Last: last}
		// Through redact.Error, which is what relay/internal/credlint holds
		// every error-typed log argument in this module to: a provider URL
		// carries provider credentials (CLAUDE.md, § Known defects).
		c.log.Error("upstream failed", "channel", c.id, "error", redact.Error(err))
		c.setState(StateError, err)
	}
}

// runAttempt is one connection: one Source.Run, under a context the health
// monitor and the stderr reader can cancel, with the channel marked
// connected and healthy for its duration (input/manager.py:1314-1315,
// :1320).
func (c *Channel) runAttempt(ctx context.Context, source Source) error {
	if a, ok := source.(attachable); ok {
		a.attach(c)
	}
	attemptCtx, cancel := context.WithCancel(ctx)
	defer cancel()

	c.mu.Lock()
	now := c.now()
	c.connected = true
	c.healthy = true
	c.connStart = now
	c.lastData = now
	c.cancelAttempt = cancel
	c.mu.Unlock()

	err := source.Run(attemptCtx, dataClock{c: c})

	c.mu.Lock()
	c.connected = false
	c.cancelAttempt = nil
	c.mu.Unlock()
	return err
}

// takePending hands the run loop a source the stderr reader adopted.
func (c *Channel) takePending() *Resolved {
	c.mu.Lock()
	defer c.mu.Unlock()
	resolved := c.pending
	c.pending = nil
	return resolved
}

// noteStable is _note_stable_connection (input/manager.py:199-204): the
// tried set shrinks to the current stream.
func (c *Channel) noteStable() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.tried = map[int]bool{}
	if c.currentStreamID != 0 {
		c.tried[c.currentStreamID] = true
	}
}

// releaseSlot gives the provider slot back once the source goroutine has
// returned: the one place this relay releases, where the Python relay
// releases from the stop path's _release_stream_resources
// (live_proxy/server.py:2335-2385). Once per channel by construction, which
// is what the metadata hdels CLAUDE.md records under #190 exist to
// guarantee against a duplicate release, and why they have no analogue here.
func (c *Channel) releaseSlot() {
	if c.release == nil {
		return
	}
	c.release(c.id, c.Source())
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

### Appendix H — `relay/channel/tuning.go`

**`relay/channel/tuning.go`**

```go
package channel

import "time"

// Tuning is the channel-start-time settings a channel runs on, already
// resolved from the control plane's proxy_settings into Go types.
//
// A plain struct of durations and ints rather than the wire object, so this
// package never imports the wire package: httpapi resolves proxy_settings once
// per tune and hands the result down, and the ffmpeg source is handed the
// same struct. Every field names its source, because a value with no named
// source is the second copy Amendment A1.4 exists to stop.
//
// SIXTEEN FIELDS, and every one snapshotted at channel start (parity-matrix
// row 5). 2c-5 added the last ten: the failover thresholds
// StreamManager.__init__ reads once (input/manager.py:50-52, :76-78) and the
// three client-loop values 2c-2 deferred to the health flag they are gated
// on (output/ts/generator.py:387-405, :549-551, :583-604). Python reads
// STREAM_TIMEOUT, FAILOVER_GRACE_PERIOD, KEEPALIVE_INTERVAL and
// MAX_KEEPALIVE_DURATION per call rather than once, but they are class
// attributes no running process ever changes, so a start-time snapshot is
// the same value.
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

	// ConnectionTimeout is CONNECTION_TIMEOUT: how long without data before
	// the health monitor marks the stream unhealthy, once the ring holds a
	// chunk (input/manager.py:1547-1551, parity-matrix row 2).
	ConnectionTimeout time.Duration

	// HealthCheckInterval is HEALTH_CHECK_INTERVAL: the health monitor's
	// tick (input/manager.py:78, :1609).
	HealthCheckInterval time.Duration

	// InitGracePeriod is channel_init_grace_period: the inactivity threshold
	// while a connection is up but the ring is still empty
	// (input/manager.py:1549-1550).
	InitGracePeriod time.Duration

	// MaxRetries is MAX_RETRIES: consecutive connection failures before the
	// source is exhausted (input/manager.py:50, :534-537, row 3).
	MaxRetries int

	// RetryWindow is RETRY_WINDOW_SECONDS: a gap since the last failure
	// longer than this resets the counter (input/manager.py:183-193, row 3).
	RetryWindow time.Duration

	// StableThreshold is STABLE_CONNECTION_THRESHOLD: a connection that ran
	// this long resets the switch rotation (input/manager.py:52, :508-513).
	StableThreshold time.Duration

	// MaxStreamSwitches is MAX_STREAM_SWITCHES: the main loop's bound on
	// switches (input/manager.py:388-402), which the buffering path does
	// not consult (row 6).
	MaxStreamSwitches int

	// ClientTimeout is STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD, the sum
	// _is_timeout computes (output/ts/generator.py:585-587): how long a
	// client may go without a yielded chunk on an UNHEALTHY channel before
	// it is dropped.
	ClientTimeout time.Duration

	// KeepaliveInterval is KEEPALIVE_INTERVAL: the gap between keepalive
	// packets sent to a client waiting at the head of an unhealthy channel
	// (output/ts/generator.py:405).
	KeepaliveInterval time.Duration

	// MaxKeepalive is MAX_KEEPALIVE_DURATION: the wall-clock cap on those
	// keepalives before the client is dropped (output/ts/generator.py:
	// 371-380).
	MaxKeepalive time.Duration
}
```

### Appendix I — `relay/channel/manager.go`

**`relay/channel/manager.go`**

```go
package channel

import (
	"context"
	"fmt"
	"log/slog"
	"sort"
	"sync"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// ManagerConfig is what a Manager needs.
type ManagerConfig struct {
	// BudgetBytes is each channel's ring size. Zero means
	// buffer.MaxBytesPerChannel.
	BudgetBytes int

	// StopWait bounds how long Stop waits for a source goroutine.
	StopWait time.Duration

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger

	// Now is the clock handed to every ring, injectable so the join-point
	// tests do not sleep. Nil means time.Now.
	Now func() time.Time

	// Events receives every transition a channel reports (events.go). Nil
	// discards them, which is what a test that is not about events wants
	// and what no deployment should run.
	Events EventSink

	// Release gives a channel's provider slot back once its source
	// goroutine has returned, whatever ended it: the one release call per
	// channel (Channel.releaseSlot). Nil means no control plane to tell,
	// which only a test wants.
	Release func(id string, info SourceInfo)
}

// Manager owns every running channel.
//
// map[string]*Channel behind a sync.RWMutex is the whole of what the
// ownership lease used to buy (spec D2). Nothing here is in Redis, so nothing
// here can fail open the three ways server.py's lease does.
type Manager struct {
	cfg ManagerConfig
	log *slog.Logger

	mu       sync.Mutex
	channels map[string]*Channel
	// starting holds one gate per channel currently being started. A second
	// client arriving mid-start waits on the gate rather than starting a
	// second source, which is what makes "one upstream per channel" a
	// property of the code -- WITHOUT holding the manager lock across the
	// control-plane call, which is what makes one slow control plane cost one
	// tune rather than every tune.
	starting map[string]chan struct{}
}

// NewManager builds a manager. It starts no goroutines of its own.
func NewManager(cfg ManagerConfig) *Manager {
	if cfg.BudgetBytes <= 0 {
		cfg.BudgetBytes = buffer.MaxBytesPerChannel
	}
	if cfg.StopWait <= 0 {
		cfg.StopWait = 5 * time.Second
	}
	log := cfg.Log
	if log == nil {
		log = slog.Default()
	}
	return &Manager{
		cfg:      cfg,
		log:      log,
		channels: map[string]*Channel{},
		starting: map[string]chan struct{}{},
	}
}

// Started is what a start function hands back: the source to run, the tuning
// the channel runs on, what the control plane said about the stream, and the
// resolver the channel fails over through.
//
// A struct rather than a fourth return value: (Source, Tuning, SourceInfo,
// error) is where a signature stops being readable, and 2c-4's ffmpeg source
// adds a fifth. Resolver is nil for a channel with no failover, which is a
// test shape: every tune builds one, because it holds the candidate list
// cached at channel start.
type Started struct {
	Source   Source
	Tuning   Tuning
	Info     SourceInfo
	Resolver Resolver
}

// Attach returns the channel for id, starting it from start() if it is not
// already running, and registers one client against it.
//
// The returned release function must be called exactly once, and a deferred
// call is the only correct shape: it drops the client and, when that was the
// last one, stops the channel after ShutdownDelay.
//
// `start` is a FUNCTION rather than a value so a second client on a running
// channel never calls the control plane at all -- which is the behaviour
// views.py:712 has today, and the reason next-source runs once per channel
// while output profiles resolve once per client (2b-2's own ruling).
//
// START RUNS OUTSIDE THE MANAGER LOCK. An earlier draft called it while
// holding the lock, on the reasoning that one process needs one mutex where
// Python needs a per-channel init lock plus an ownership lease plus a
// _channels_setting_up set. That reasoning is right about correctness and
// wrong about everything else. start() makes the next-source call, whose own
// budget is two attempts of (2s, 5s) plus a retry delay, and holding the
// manager lock across it serialises every concurrent Attach, Get, Stop and
// release behind one slow control plane. Worse, a panic inside start() left
// the lock held forever: the relay then answered /healthz with 200 while
// every subsequent tune blocked. Demonstrated, and pinned by
// TestAPanickingStartDoesNotWedgeTheManager.
//
// The exclusion that actually matters is preserved by a gate: the caller that
// claims the start publishes a channel under `starting`, later callers wait on
// it and retry, and the gate is closed from a deferred call so a panic wakes
// them instead of stranding them.
func (m *Manager) Attach(id string, client *Client, start func() (Started, error)) (*Channel, func(), error) {
	var gate chan struct{}
	for {
		existing, wait, own, err := m.claim(id, client)
		if err != nil {
			return nil, nil, err
		}
		if existing != nil {
			// No markActive call here: promoteOnFirstChunk (run's own
			// goroutine) is the one mechanism for waiting_for_clients ->
			// active, and it runs regardless of which or how many clients
			// are attached, so a second client's arrival needs no separate
			// trigger.
			return existing, func() { m.release(existing, client.ID) }, nil
		}
		if own != nil {
			gate = own
			break
		}
		// Someone else is starting this channel. Wait for them and look
		// again; they may have succeeded, failed, or panicked.
		<-wait
	}

	// REGISTERED BEFORE start() IS CALLED, so it runs when Attach RETURNS --
	// which is after publish has installed the channel. The ordering is the
	// whole point and it is easy to get subtly wrong: an earlier version
	// closed the gate when the START finished, inside a helper, so a waiter
	// woken by it raced the caller's own map insertion. When the waiter won it
	// found neither a channel nor a gate, claimed a fresh one, and started a
	// SECOND upstream -- a second provider connection with no map entry and
	// nothing that would ever stop it, plus a first client whose release tore
	// down the other client's channel. Measured at 8 concurrent clients: it
	// went wrong within the first few rounds, and -race never flagged it,
	// because an ordering bug is not a data race.
	//
	// A deferred call still runs while a panic unwinds, so this also keeps the
	// panic guarantee the helper was written for.
	defer m.releaseGate(id, gate)

	started, err := start()
	if err != nil {
		// A failed start leaves no channel, and the deferred release lets the
		// next caller claim a fresh gate and try again. A tune that failed is
		// retryable; nothing here caches the failure.
		return nil, nil, err
	}

	c := m.publish(id, client, started)
	return c, func() { m.release(c, client.ID) }, nil
}

// releaseGate clears the start claim and wakes everyone waiting on it. It is
// called from Attach's deferred call and nowhere else, so the close happens
// exactly once and only after the channel is reachable.
func (m *Manager) releaseGate(id string, gate chan struct{}) {
	m.mu.Lock()
	delete(m.starting, id)
	m.mu.Unlock()
	close(gate)
}

// claim inspects the map once, under the lock. It returns exactly one of: a
// running channel with this caller registered against it; a gate to wait on
// because someone else is starting; or a gate this caller now owns.
func (m *Manager) claim(id string, client *Client) (existing *Channel, wait, own chan struct{}, err error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if c, running := m.channels[id]; running {
		// A FINISHED CHANNEL IS NOT A RUNNING ONE. Once the ring is closed
		// nothing will ever be published to it again, so handing it to a new
		// client serves whatever is left in the buffer and then EOF, with no
		// re-tune and no error -- a channel whose upstream 404'd would answer
		// every later viewer with an empty 200, forever. Drop it here and fall
		// through to a fresh start.
		//
		// The ring, not c.done: the ring closes FIRST inside run's deferred
		// calls, so this covers the whole window from "nothing more will be
		// published" onward rather than just the tail of it.
		//
		// THIS IS THE ONLY PLACE A FINISHED CHANNEL IS DROPPED. An earlier
		// draft also had run() remove itself from the map, which was worse in
		// a way that is easy to miss: with two mechanisms, removing this one
		// changed no test, because the other silently covered for it. One
		// mechanism means the break-check reddens. The cost is that a finished
		// channel nobody re-tunes stays in the map until its last client
		// releases -- and release stops it, so the entry cannot outlive the
		// clients watching it.
		if !c.ring.Closed() {
			if !c.addClient(client) {
				return nil, nil, nil, ErrDuplicateClient
			}
			return c, nil, nil, nil
		}
		delete(m.channels, id)
	}
	if gate, starting := m.starting[id]; starting {
		return nil, gate, nil, nil
	}
	gate := make(chan struct{})
	m.starting[id] = gate
	return nil, nil, gate, nil
}

// publish installs the started channel and registers its first client.
func (m *Manager) publish(id string, client *Client, started Started) *Channel {
	ctx, cancel := context.WithCancel(context.Background())
	now := m.cfg.Now
	if now == nil {
		now = time.Now
	}
	events := m.cfg.Events
	if events == nil {
		events = discardEvents{}
	}
	c := &Channel{
		id: id,
		ring: buffer.New(buffer.Config{
			BudgetBytes: m.cfg.BudgetBytes,
			ChunkBytes:  started.Tuning.ChunkBytes,
			Retention:   started.Tuning.Retention,
			Now:         m.cfg.Now,
		}),
		log:         m.log,
		tuning:      started.Tuning,
		source:      started.Info,
		channelName: started.Info.ChannelName,
		startedAt:   now(),
		now:         now,
		resolver:    started.Resolver,
		events:      events,
		release:     m.cfg.Release,
		ctx:         ctx,
		state:       StateInitializing,
		clients:     map[string]*Client{client.ID: client},
		// StreamManager.__init__ (input/manager.py:76-78, :93-96): healthy
		// until the monitor says otherwise, the initial stream already in
		// the tried set, and the failure window from the tune's settings.
		healthy:         true,
		lastData:        now(),
		tried:           map[int]bool{},
		currentStreamID: started.Info.StreamID,
		failures:        failureCounter{window: started.Tuning.RetryWindow, now: now},
		cancel:          cancel,
		done:            make(chan struct{}),
	}
	if started.Info.StreamID != 0 {
		c.tried[started.Info.StreamID] = true
	}

	m.mu.Lock()
	m.channels[id] = c
	m.mu.Unlock()

	go c.run(ctx, started.Source)
	return c
}

// Get returns a running channel, or nil.
func (m *Manager) Get(id string) *Channel {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.channels[id]
}

// Stop tears a channel down immediately, whatever its client count.
func (m *Manager) Stop(id string) bool {
	c := m.take(id)
	if c == nil {
		return false
	}
	c.setState(StateStopping, nil)
	c.stop(m.cfg.StopWait)
	return true
}

// take removes a channel from the map and returns it, or nil.
func (m *Manager) take(id string) *Channel {
	m.mu.Lock()
	defer m.mu.Unlock()
	c, running := m.channels[id]
	if !running {
		return nil
	}
	delete(m.channels, id)
	return c
}

// StopAll tears every channel down. The SIGTERM drain that calls it in
// anger is 2c-8's; this exists so a test and a shutdown path have one way to
// do it.
func (m *Manager) StopAll() {
	for _, id := range m.ids() {
		m.Stop(id)
	}
}

func (m *Manager) ids() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	ids := make([]string, 0, len(m.channels))
	for id := range m.channels {
		ids = append(ids, id)
	}
	return ids
}

// 2c-3 changes exactly two things here and preserves everything else: the drop
// names a client, and the delay comes off the channel's own Tuning rather than
// the manager's config (it is a channel-start-time setting, parity-matrix row
// 5). The drop stays OUTSIDE m.mu and the decision stays inside
// stopIfStillIdle, which is 2c-2's fix and is correct with a registry for the
// same reason it is correct with a counter: claim's addClient and
// stopIfStillIdle's re-check are both under m.mu, so whichever runs first is
// the one acted on and the other sees the consequence.
func (m *Manager) release(c *Channel, clientID string) {
	if remaining := c.dropClient(clientID); remaining > 0 {
		return
	}
	if c.tuning.ShutdownDelay <= 0 {
		m.stopIfStillIdle(c)
		return
	}
	time.AfterFunc(c.tuning.ShutdownDelay, func() {
		m.stopIfStillIdle(c)
	})
}

// stopIfStillIdle re-checks c's client count and, if it is still zero,
// removes c from the map and tears it down -- both under m.mu, in the same
// critical section claim() uses to read the map and call addClient.
//
// THE RE-CHECK MUST HAPPEN UNDER m.mu, and that is the whole fix (found by a
// downstream reviewer, verified here before being trusted): dropClient()
// above only touches c.mu, so the moment between it returning zero and this
// method's own lock acquisition is a window in which claim() can run to
// completion -- see the map, find the ring not yet closed, and addClient()
// -- entirely unaware that the caller that dropped to zero already decided
// to stop this channel. Re-reading Clients() here, under the same lock
// claim() holds across its own check-and-addClient, makes the two mutually
// exclusive: whichever runs first is the one whose view of "is this channel
// idle" is the one that is acted on, and the other sees the consequence
// (either the channel is already gone from the map, or Clients() is back
// above zero and this call is a no-op). Demonstrated at roughly one race in
// several thousand rounds by TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined
// against the pre-fix code (a plain c.Clients() == 0 check taken outside the
// lock): a client attaching at that exact instant was handed a channel that
// stopIfStillIdle then tore down anyway, in the same round.
//
// The identity check (`existing == c`) guards a narrower case than the race
// above: by the time this runs, id's map entry might already be a DIFFERENT,
// newer channel (this one's ring closed on its own and a fresh tune
// replaced it in claim() before this call ever got the lock). Deleting the
// map entry unconditionally in that case would remove the wrong channel.
// Tearing down c itself is still correct and safe either way -- c.stop is
// idempotent-ish (context.CancelFunc more than once is a no-op, and a select
// on an already-closed c.done returns immediately) -- so this always runs it
// once Clients() reads zero, and only touches the map when c is still the
// entry it names.
func (m *Manager) stopIfStillIdle(c *Channel) {
	stop := func() bool {
		m.mu.Lock()
		defer m.mu.Unlock()
		if c.Clients() != 0 {
			return false
		}
		if existing, ok := m.channels[c.id]; ok && existing == c {
			delete(m.channels, c.id)
		}
		return true
	}()
	if !stop {
		return
	}
	c.setState(StateStopping, nil)
	c.stop(m.cfg.StopWait)
}

// Snapshot is every channel the manager holds, in id order.
//
// The list endpoint's source. Ordered so the payload is stable between polls;
// build_live_channel_stats_data's own order is a Redis SCAN's, which is
// arbitrary and not a contract.
func (m *Manager) Snapshot() []*Channel {
	m.mu.Lock()
	out := make([]*Channel, 0, len(m.channels))
	for _, c := range m.channels {
		out = append(out, c)
	}
	m.mu.Unlock()
	sort.Slice(out, func(i, j int) bool { return out[i].id < out[j].id })
	return out
}

// Describe is a one-line state summary, for logs and for the 2c-8 status
// routes to build on.
func (c *Channel) Describe() string {
	return fmt.Sprintf("channel %s state=%s clients=%d head=%d", c.id, c.State(), c.Clients(), c.ring.Head())
}
```

### Appendix J — `relay/ffmpeg/detector.go`

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

// BufferingFor is how long the channel has been buffering, `buffering_duration`
// at input/manager.py:1177 -- the value the channel_failover event carries as
// `duration` (:1204). Zero when not buffering.
func (d *Detector) BufferingFor() time.Duration {
	if !d.buffering {
		return 0
	}
	now := d.Now
	if now == nil {
		now = time.Now
	}
	return now().Sub(d.since)
}

// Reset is the successful-switch branch (:1185-1186): buffering cleared and
// the clock forgotten, so the NEXT sub-threshold sample starts a fresh
// window. 2c-5's failover calls it; nothing in 2c-4 does.
func (d *Detector) Reset() {
	d.buffering = false
	d.since = time.Time{}
}
```

### Appendix K — `relay/channel/events.go`

**`relay/channel/events.go`**

```go
package channel

// Event is one transition this package reports, the domain half of what
// control.Event puts on the wire: httpapi adapts one to the other so this
// package keeps not importing the wire package (tuning.go's own rule).
//
// The identity keys mirror apps/proxy/control_plane.py:296-311's emit_event:
// channel_id and channel_name from the channel, and stream_id lifted out of
// Details to the top level when the transition carries one -- and LEFT in
// Details too, as emit_event leaves it, because core/relay_events.py:
// _apply_stream_stats is written around that shape.
type Event struct {
	Type        string
	ChannelID   string
	ChannelName string
	ClientID    string
	StreamID    *int
	Details     map[string]any
}

// EventSink receives events. Emit must never block the caller: the byte
// path calls it, and a slow control plane must cost a queued event, not a
// stalled stream (control_plane.py:311-313).
type EventSink interface {
	Emit(Event)
}

// discardEvents is the sink a Manager built with no Events uses.
type discardEvents struct{}

func (discardEvents) Emit(Event) {}

// emit builds and sends one event for this channel.
func (c *Channel) emit(typ string, details map[string]any) {
	if details == nil {
		details = map[string]any{}
	}
	event := Event{Type: typ, ChannelID: c.id, ChannelName: c.channelName, Details: details}
	if id, ok := details["stream_id"].(int); ok {
		event.StreamID = &id
	}
	c.events.Emit(event)
}
```

### Appendix L — `relay/channel/failover.go`

**`relay/channel/failover.go`**

```go
package channel

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// Resolver is how a channel asks for its next source: the port of
// _try_next_stream's control-plane half (input/manager.py:2041-2131) behind
// one method, so this package never imports the wire package. httpapi
// implements it over control.Client, and it is where the degraded fallback
// lives -- the candidate list cached at channel start, consulted only when
// the control plane is unreachable -- because that list is wire-shaped and
// the decision "the control plane refused, never degrade" is a distinction
// only the wire client can make (spec § Error handling per hop).
//
// ONE PER CHANNEL, built by the tune that started it, because the cache it
// holds is that tune's answer.
type Resolver interface {
	// Next asks for the next source, excluding the stream ids already tried.
	// It returns ErrNoAlternate when nothing is left -- a null source from
	// Django, or an empty cache during an outage -- and any other error for
	// a refusal or a transport failure the fallback could not cover. A
	// Resolved whose Degraded flag is set came from the cache, unenforced.
	Next(ctx context.Context, req NextRequest) (Resolved, error)
}

// NextRequest is what _try_next_stream sends (input/manager.py:2081-2087):
// the tried set plus the current stream, sorted, and the URL and id being
// failed over FROM, so Django's traversal starts after it and never answers
// with the URL already playing.
type NextRequest struct {
	Exclude         []int
	CurrentURL      string
	CurrentStreamID int
}

// Resolved is a next source ready to run.
type Resolved struct {
	Source   Source
	Info     SourceInfo
	Degraded bool
}

// ErrNoAlternate is "No alternate stream available" (input/manager.py:2110).
var ErrNoAlternate = errors.New("channel: no alternate stream available")

// ErrSourcesExhausted is the error a channel ends in once every candidate has
// failed: run()'s finally block (input/manager.py:678-682), which writes
// "All N stream options failed" when any stream id was ever tried and
// "Connection failed after N attempts" otherwise. Last is the error the
// final attempt ended with, so errors.Is and errors.As still see the
// mechanism -- an ErrExited, an ErrUpstreamStatus, ErrInputFailed.
type ErrSourcesExhausted struct {
	Tried    int
	Attempts int
	Last     error
}

// Message is the text Python writes into the metadata hash's error_message,
// which a client waiting for its first byte receives in an error TS packet
// (output/ts/generator.py:229, utils.py:71-98).
func (e *ErrSourcesExhausted) Message() string {
	if e.Tried > 0 {
		return fmt.Sprintf("All %d stream options failed", e.Tried)
	}
	return fmt.Sprintf("Connection failed after %d attempts", e.Attempts)
}

func (e *ErrSourcesExhausted) Error() string {
	if e.Last != nil {
		return "channel: " + e.Message() + ": " + redact.Error(e.Last).Error()
	}
	return "channel: " + e.Message()
}

func (e *ErrSourcesExhausted) Unwrap() error { return e.Last }

// errUpstreamEnded stands in for a nil Run result in the failure accounting:
// a clean upstream EOF is "Server closed connection" (input/manager.py:
// 1868-1872), a connection failure like any other, retried and counted.
var errUpstreamEnded = errors.New("channel: the upstream ended the connection")

// The bare literals of the retry loop and the health monitor, none of which
// a setting supplies. Each is pinned by TestTheFailoverLiteralsMatchPython.
const (
	// retryBackoffStep and retryBackoffCap: `min(.25 * failures, 3)` at
	// input/manager.py:557 and :588.
	retryBackoffStep = 250 * time.Millisecond
	retryBackoffCap  = 3 * time.Second

	// maxUnhealthyChecks is the health monitor's `max_unhealthy_checks = 3`
	// (input/manager.py:1556): the number of consecutive checks that must
	// find the stream inactive before it acts (parity-matrix row 2).
	maxUnhealthyChecks = 3

	// healthActionCooldown is `action_cooldown = 30` (input/manager.py:1557).
	healthActionCooldown = 30 * time.Second

	// stableReconnectAfter is the bare `stable_time >= 30` at
	// input/manager.py:1580: a stream that was stable this long is
	// reconnected in place before it is switched. apps/proxy/config.py:119
	// names MIN_STABLE_TIME_BEFORE_RECONNECT = 30 for it and nothing reads
	// that (CLAUDE.md § Known defects, dead or unwired), so it is a literal
	// here as it is there.
	stableReconnectAfter = 30 * time.Second
)

// retryBackoff is the wait before the next attempt on the same URL.
func retryBackoff(failures int) time.Duration {
	return min(time.Duration(failures)*retryBackoffStep, retryBackoffCap)
}

// healthAction is the health monitor's decision once the checks have run
// out (input/manager.py:1576-1590): reconnect in place if the stream had
// been stable, switch streams otherwise.
type healthAction int

const (
	actionSwitch healthAction = iota
	actionReconnect
)

func healthActionFor(stableFor time.Duration) healthAction {
	if stableFor >= stableReconnectAfter {
		return actionReconnect
	}
	return actionSwitch
}

// failureCounter is _record_connection_failure and its two neighbours
// (input/manager.py:183-197): a count that resets when the gap since the
// last failure exceeds the window, so three failures at t=0, 1700 and 3400
// trip a 1800-second window even though the span is 3400 (parity-matrix
// row 3's Notes).
type failureCounter struct {
	window time.Duration
	now    func() time.Time

	count int
	last  time.Time
}

func (f *failureCounter) record() int {
	now := f.now()
	if !f.last.IsZero() && now.Sub(f.last) > f.window {
		f.count = 0
	}
	f.last = now
	f.count++
	return f.count
}

func (f *failureCounter) clear() {
	f.count = 0
	f.last = time.Time{}
}

// failover is _try_next_stream (input/manager.py:2041-2225) minus the
// control-plane call, which is the resolver's. It records the candidate as
// tried, refuses the URL already playing (update_url's own first check,
// :1464-1466), resets the packetiser (:1515-1520, never the chunk index --
// row 7), swaps the source info, clears the failure history (:1512) and
// raises stream_switch (:1523-1532); then the degraded bookkeeping of
// :2191-2202. url_switching (set at :1476-1477, cleared at :1540) is not carried:
// its one reader, _is_timeout's exemption, is not ported (Ruling R14). It does NOT stop the running attempt -- the caller does,
// because the two callers stop it differently: the run loop has already
// seen it end, and the stderr reader cancels it after adopting the result.
//
// Serialised by switchMu, because the stderr reader and the run loop can
// both reach it, and a second switch racing the first would exclude the
// wrong stream id.
func (c *Channel) failover(ctx context.Context, why string) (Resolved, bool) {
	c.switchMu.Lock()
	defer c.switchMu.Unlock()

	if c.resolver == nil {
		c.log.Error("no alternate stream available: this channel has no resolver", "channel", c.id, "trigger", why)
		return Resolved{}, false
	}

	c.mu.RLock()
	current := c.source
	exclude := make([]int, 0, len(c.tried)+1)
	for id := range c.tried {
		exclude = append(exclude, id)
	}
	if c.currentStreamID != 0 && !c.tried[c.currentStreamID] {
		exclude = append(exclude, c.currentStreamID)
	}
	c.mu.RUnlock()
	sort.Ints(exclude)

	resolved, err := c.resolver.Next(ctx, NextRequest{Exclude: exclude, CurrentURL: current.URL, CurrentStreamID: c.currentStreamID})
	if err != nil {
		if errors.Is(err, ErrNoAlternate) {
			c.log.Error("no alternate stream available", "channel", c.id, "trigger", why)
		} else {
			c.log.Error("the failover could not be resolved", "channel", c.id, "trigger", why, "error", redact.Error(err))
		}
		return Resolved{}, false
	}

	c.mu.Lock()
	c.tried[resolved.Info.StreamID] = true
	c.mu.Unlock()

	if resolved.Info.URL == current.URL {
		// update_url returns False on the URL already playing, and
		// _try_next_stream reports the failover failed (:2143-2153).
		c.log.Error("the failover named the URL already playing", "channel", c.id, "stream", resolved.Info.StreamID)
		return Resolved{}, false
	}

	c.log.Info("switching stream", "channel", c.id, "trigger", why, "stream", resolved.Info.StreamID, "m3u_profile", resolved.Info.M3UProfileID)
	c.mu.Lock()
	c.ring.ResetPosition()
	c.source = resolved.Info
	c.currentStreamID = resolved.Info.StreamID
	c.failures.clear()
	c.mu.Unlock()

	// stream_switch (:1523-1532): the URL through redact_url and cut at 100
	// characters there; through redact.Line here, which keeps less --
	// scheme and host only -- and the same cut.
	c.emit("stream_switch", map[string]any{
		"new_url":   truncate(redact.Line(resolved.Info.URL), 100),
		"stream_id": resolved.Info.StreamID,
	})

	c.mu.Lock()
	degradedBefore := c.failoverDegraded
	c.failoverDegraded = resolved.Degraded
	c.mu.Unlock()
	if !resolved.Degraded && degradedBefore {
		// Django is answering again: say, once, that an earlier failover ran
		// blind on the cached list and may have exceeded max_streams
		// (:2191-2202).
		c.emit("channel_error", map[string]any{"reason": "degraded_failover"})
	}
	return resolved, true
}

// failoverFromBuffering is the stderr reader's entry: _parse_ffmpeg_stats'
// buffering-timeout branch (input/manager.py:1178-1211, parity-matrix row
// 1), which calls _try_next_stream from the reader thread and, on success,
// clears the buffering state and raises channel_failover. It never touches
// the main loop's switch counter, which is row 6.
//
// The new source is parked for the run loop and the running attempt is
// cancelled; Run returns to the loop once this reader has returned, because
// TranscodeSource.Run waits for its stderr reader before it returns, exactly
// as Python's update_url kills the process the reader was reading.
func (c *Channel) failoverFromBuffering(bufferingFor time.Duration) bool {
	ctx := c.ctx
	if ctx == nil {
		ctx = context.Background()
	}
	resolved, ok := c.failover(ctx, "buffering_timeout")
	if !ok {
		return false
	}
	c.mu.Lock()
	c.pending = &resolved
	cancel := c.cancelAttempt
	c.mu.Unlock()
	// :1190-1197's hset ACTIVE after the switch, through the guarded
	// recovery edge -- the one existing writer of StateActive beside
	// promoteOnFirstChunk, not a third.
	c.reportBuffering(false)
	c.emit("channel_failover", map[string]any{
		"reason":   "buffering_timeout",
		"duration": bufferingFor.Seconds(),
	})
	if cancel != nil {
		cancel()
	}
	return true
}

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n]
}
```

### Appendix M — `relay/channel/health.go`

**`relay/channel/health.go`**

```go
package channel

import (
	"context"
	"time"
)

// dataClock is the sink a source writes into: the ring, with the channel's
// last-data timestamp refreshed on every write -- input/manager.py:1367's
// `self.last_data_time = time.time()` after every successful fetch_chunk.
// Every byte an upstream hands over passes through here, so "no data for
// N seconds" is measured from the last byte, not the last chunk.
type dataClock struct{ c *Channel }

func (d dataClock) Write(p []byte) (int, error) {
	d.c.mu.Lock()
	d.c.lastData = d.c.now()
	d.c.mu.Unlock()
	return d.c.ring.Write(p)
}

// Healthy is StreamManager.healthy: true from the moment a connection is
// up until the health monitor sees no data for longer than the inactivity
// threshold, and true again when data resumes. It gates the keepalives and
// the client timeout (output/ts/generator.py:549-551, :592), and it is the
// `healthy` field on GET /proxy/relay/channels (channel_status.py:527-529).
func (c *Channel) Healthy() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.healthy
}

// inactivityThreshold is _health_inactivity_threshold (input/manager.py:
// 1547-1551): the init grace period while a connection is up and the ring
// is still empty, CONNECTION_TIMEOUT otherwise. Called with mu held.
func (c *Channel) inactivityThreshold() time.Duration {
	if c.connected && c.ring.Head() == 0 {
		return c.tuning.InitGracePeriod
	}
	return c.tuning.ConnectionTimeout
}

// monitorHealth is _monitor_health (input/manager.py:1553-1609): every
// HealthCheckInterval, compare the time since the last byte against the
// threshold; after maxUnhealthyChecks consecutive failures and outside the
// cooldown, ask the run loop for a reconnect (a stream that had been stable)
// or a switch (one that had not) -- parity-matrix row 2.
//
// WHERE IT DIFFERS: Python sets a flag the main loop notices between
// fetch_chunk calls (:1364-1365), each of which blocks up to CHUNK_TIMEOUT
// (5s) in select on a silent pipe (:1845), so the loop acts up to five
// seconds after the flag. This
// monitor sets the same flag and CANCELS the running attempt, so the loop
// acts at once. A divergence in the safe direction, stated rather than
// reproduced: CHUNK_TIMEOUT is not read.
func (c *Channel) monitorHealth(ctx context.Context) {
	interval := max(c.tuning.HealthCheckInterval, time.Millisecond)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	unhealthyChecks := 0
	var lastAction time.Time
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}

		c.mu.Lock()
		now := c.now()
		inactivity := now.Sub(c.lastData)
		threshold := c.inactivityThreshold()
		var cancel context.CancelFunc

		switch {
		case inactivity > threshold && c.connected:
			if c.healthy {
				c.log.Warn("stream unhealthy: no data", "channel", c.id, "inactive", inactivity.Round(100*time.Millisecond))
				c.healthy = false
			}
			unhealthyChecks++
			if unhealthyChecks >= maxUnhealthyChecks && now.Sub(lastAction) > healthActionCooldown {
				stableFor := c.lastData.Sub(c.connStart)
				switch healthActionFor(stableFor) {
				case actionReconnect:
					if !c.needsReconnect {
						c.log.Info("health monitor: reconnecting a stream that had been stable", "channel", c.id, "stable", stableFor.Round(time.Second))
						c.needsReconnect = true
						lastAction = now
						cancel = c.cancelAttempt
					}
				case actionSwitch:
					if !c.needsSwitch {
						c.log.Info("health monitor: switching an unstable stream", "channel", c.id, "stable", stableFor.Round(time.Second))
						c.needsSwitch = true
						lastAction = now
						cancel = c.cancelAttempt
					}
				}
				unhealthyChecks = 0
			}
		case c.connected && !c.healthy:
			c.log.Info("stream health restored: data resumed", "channel", c.id, "after", inactivity.Round(100*time.Millisecond))
			c.healthy = true
			unhealthyChecks = 0
			c.needsReconnect = false
			c.needsSwitch = false
		}
		if c.healthy {
			unhealthyChecks = 0
		}
		c.mu.Unlock()

		if cancel != nil {
			cancel()
		}
	}
}

// takeFlag reads and clears one of the two recovery flags under the lock.
func (c *Channel) takeFlag(flag *bool) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	set := *flag
	*flag = false
	return set
}

func (c *Channel) flagSet(flag *bool) bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return *flag
}
```

### Appendix N — `relay/channel/source_transcode.go`

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
	// A fresh attempt has no cause yet: the run loop calls Run again on the
	// same source after a failure (input/manager.py's retry loop), and a
	// cause left over from the last attempt would end this one at once.
	s.mu.Lock()
	s.cause = nil
	s.mu.Unlock()

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
		// event and the state.
		s.log().Warn("buffering started", "channel", s.channelID(), "speed", *p.Speed, "threshold", r.detector.Threshold)
		if s.channel != nil {
			s.channel.emit("channel_buffering", map[string]any{"speed": *p.Speed})
			s.channel.reportBuffering(true)
		}
	case ffmpeg.Continuing:
		// :1232-1234 re-writes the BUFFERING state on every sample; the
		// state is already buffering here, so there is nothing to write.
	case ffmpeg.TimedOut:
		// :1178-1211, parity-matrix row 1: the next stream, asked for from
		// THIS goroutine, as Python asks from its stderr thread. On success
		// the channel has parked the new source and cancelled this attempt;
		// on failure Python stays buffering and asks again on the very next
		// record (:1210) -- one control-plane call per progress record until
		// something answers, reproduced and filed rather than rate-limited.
		bufferingFor := r.detector.BufferingFor()
		s.log().Error("buffering timeout reached", "channel", s.channelID(), "speed", *p.Speed, "buffering_for", bufferingFor.Round(100*time.Millisecond), "timeout", r.detector.Timeout)
		if s.channel != nil && s.channel.failoverFromBuffering(bufferingFor) {
			s.log().Info("switched to the next stream after a buffering timeout", "channel", s.channelID())
			// :1185-1186, the successful-switch branch: buffering cleared
			// and the clock forgotten. The process this reader belongs to
			// is about to be killed, so the reset is for fidelity, not
			// for the next record.
			r.detector.Reset()
		} else {
			s.log().Error("failed to switch to the next stream after a buffering timeout", "channel", s.channelID())
		}
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

### Appendix O — `relay/channel/source_transcode_test.go`

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
// cleanly is RETRIED exactly as a clean Proxy EOF is (input/manager.py:
// 1870-1875, then the retry loop): three runs of the same asset, then the
// source is exhausted and the channel ends in error.
func TestATranscodeProcessesFd1ReachesTheRingInOrder(t *testing.T) {
	path, payload := assetFile(t, 64)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	ch, release := attachTranscode(t, m, "transcode-1", standInSource(t, "-i", path), transcodeTuning(1.0, 15*time.Second))
	defer release()

	select {
	case <-ch.Done():
	case <-time.After(20 * time.Second):
		t.Fatal("the channel did not finish after the child copied its asset and exited three times")
	}
	if state := ch.State(); state != StateError {
		t.Fatalf("state = %q after three clean child exits, want %q (err %v)", state, StateError, ch.Err())
	}
	var exhausted *ErrSourcesExhausted
	if !errors.As(ch.Err(), &exhausted) || exhausted.Attempts != 3 {
		t.Fatalf("Err() = %v, want ErrSourcesExhausted after MAX_RETRIES attempts", ch.Err())
	}
	chunks, _, _ := ch.Ring().Read(0)
	got := bytes.Join(chunks, nil)
	// testTuning's chunk is four packets, so each run's last partial chunk
	// is held back by the packetiser -- and dropped by the switch-less
	// ResetPosition-free retry, which is Python's own shape: a reconnect
	// does not touch the buffer. Everything published must be the asset's
	// own packets in order, the index wrapping at each rerun.
	if len(got) == 0 || len(got) > 3*len(payload) {
		t.Fatalf("the ring holds %d bytes of a %d-byte asset run three times", len(got), len(payload))
	}
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the ring's bytes are not whole packets: %s", problem)
	}
	packets := len(payload) / buffer.TSPacketSize
	previous := -1
	for i := 0; i < len(got); i += buffer.TSPacketSize {
		idx := relaytest.PacketIndex(got[i : i+buffer.TSPacketSize])
		if idx != (previous+1)%packets && (previous < 0 || idx != 0) {
			t.Fatalf("packet at byte %d carries index %d after %d: out of order within a run", i, idx, previous)
		}
		previous = idx
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

	// interval 0: the whole corpus is on stderr before the stand-in exits,
	// by construction -- RunStandIn joins its stderr pump before returning
	// (break-check 22) -- so the last record is the one the channel holds
	// when it stops.
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

// slowTrickleTail checks the capture still has the shape rows 1 and 6 lean
// on: opens above the API's maximum buffering_speed, stays below it from the
// second record, and its below-threshold tail outlasts a 1s timeout.
func slowTrickleTail(t *testing.T) {
	t.Helper()
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
}

// PARITY-MATRIX ROW 1: ffmpeg's reported speed below buffering_speed,
// sustained longer than buffering_timeout, switches streams
// (input/manager.py:1064-1066, :1122-1191). The lever is buffering_speed at
// the API maximum, as the Python pin uses it: the capture opens above 10 and
// every later record is below, so the detector arms on record two, and a
// 1s timeout against a 1.5s tail (replayed at 20 ms a record, looping) is
// what fires it. The resolver hands over a second stand-in, whose child is
// then the one producing bytes.
//
// The clock starts BEFORE the source does, so it can only be EARLIER than
// the detector's own `since`; the switch landing under a second of it would
// mean the detector timed out early. (2c-4's timeout test learnt this the
// hard way: a clock taken after the first poll saw buffering reddened 2 in
// 8 under -race.)
func TestASustainedSubThresholdSpeedFailsTheChannelOver(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	// The alternate's child is SILENT on stderr: with the threshold at the
	// API maximum every record of any capture is below it, so a child that
	// replayed one would put the channel straight back into buffering and
	// hide the active edge the switch itself produces (:1190-1197).
	alternate := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504")
	ran := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: countingRuns{inner: alternate, runs: ran},
		Info:   SourceInfo{URL: "http://provider.invalid/alternate.ts", StreamID: 2, M3UProfileID: 1},
	}}}
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02", "--stderr-loop")

	started := time.Now()
	ch, release := attachWith(t, m, "row1", src, transcodeTuning(apiMax, time.Second), resolver)
	defer release()

	waitFor(t, "buffering", 10*time.Second, func() bool { return ch.State() == StateBuffering })
	waitFor(t, "the switch", 15*time.Second, func() bool { return ch.Source().StreamID == 2 })
	if elapsed := time.Since(started); elapsed < time.Second {
		t.Fatalf("the channel switched %s after it started, before the 1s buffering_timeout could have elapsed", elapsed)
	}
	waitFor(t, "the alternate's child to run", 10*time.Second, func() bool { return ran.get() == 1 })
	waitFor(t, "the state to leave buffering", 10*time.Second, func() bool { return ch.State() == StateActive })

	if len(events.of("channel_buffering")) == 0 {
		t.Fatal("buffering never armed: no channel_buffering event")
	}
	failovers := events.of("channel_failover")
	if len(failovers) != 1 {
		t.Fatalf("channel_failover raised %d times, want 1: %+v", len(failovers), failovers)
	}
	if reason := failovers[0].Details["reason"]; reason != "buffering_timeout" {
		t.Fatalf("channel_failover reason = %v, want buffering_timeout", reason)
	}
	if d, _ := failovers[0].Details["duration"].(float64); d < 1.0 {
		t.Fatalf("channel_failover duration = %v, want at least the 1s buffering_timeout", d)
	}
	req := resolver.requests()
	if len(req) != 1 || len(req[0].Exclude) != 1 || req[0].Exclude[0] != 1 || req[0].CurrentStreamID != 1 {
		t.Fatalf("the resolver was asked %+v, want one request excluding stream 1 and naming it as current", req)
	}
	m.Stop("row1")
}

// PARITY-MATRIX ROW 6 (issue #221, reproduced not fixed): MAX_STREAM_SWITCHES
// bounds the main loop's switches (input/manager.py:388-402) and NOT a
// buffering-triggered one, which the stderr thread makes without touching
// the counter (:1134-1138). With the bound at ZERO a buffering failover
// still switches. Falsifiable in the direction that matters: teach the
// stderr path to consult the counter -- the natural fix for #221 -- and a
// bound of zero refuses this switch. Its sibling in failover_test.go shows
// the same bound DOES stop a main-loop switch, so the two together pin the
// asymmetry rather than the absence of a bound.
func TestABufferingFailoverIgnoresMaxStreamSwitches(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	// The alternate's child is SILENT on stderr: with the threshold at the
	// API maximum every record of any capture is below it, so a child that
	// replayed one would put the channel straight back into buffering and
	// hide the active edge the switch itself produces (:1190-1197).
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

	waitFor(t, "the switch despite a bound of zero", 15*time.Second, func() bool { return ch.Source().StreamID == 2 })
	waitFor(t, "the alternate's child to run", 10*time.Second, func() bool { return ran.get() == 1 })
	// And the channel keeps going on the new source: the bound of zero,
	// which ends the main loop after ITS first switch, is never consulted.
	time.Sleep(300 * time.Millisecond)
	if state := ch.State(); state != StateActive {
		t.Fatalf("state = %q after a buffering failover under MAX_STREAM_SWITCHES = 0, want active: the stderr path consulted the main loop's bound", state)
	}
	if len(events.of("channel_failover")) != 1 {
		t.Fatal("the switch was not the buffering path's: no channel_failover event")
	}
	m.Stop("row6")
}

// The failure branch of the same arm (input/manager.py:1210): with nothing
// to fail over to, Python logs an error, stays buffering, and asks the
// control plane AGAIN ON THE VERY NEXT RECORD -- one next-source call per
// progress record, for as long as the speed stays low. Reproduced per D5
// and filed as an issue; the assertion is that the channel keeps playing
// (the child is never killed) while the resolver is asked repeatedly.
func TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord(t *testing.T) {
	slowTrickleTail(t)
	const apiMax = 10.0
	path, _ := assetFile(t, 8)
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	resolver := &fakeResolver{} // every answer is ErrNoAlternate
	src := standInSource(t, "-i", path, "--dead-air-after-bytes", "1504",
		"--stderr-corpus", relaytest.CorpusPath("slow-trickle"), "--stderr-interval", "0.02", "--stderr-loop")

	ch, release := attachWith(t, m, "no-alt", src, transcodeTuning(apiMax, time.Second), resolver)
	defer release()

	waitFor(t, "the first failed switch", 10*time.Second, func() bool { return len(resolver.requests()) >= 1 })
	waitFor(t, "a third failed switch, one per record", 10*time.Second, func() bool { return len(resolver.requests()) >= 3 })
	if state := ch.State(); state != StateBuffering {
		t.Fatalf("state = %q, want buffering: a failed switch leaves the channel where it was", state)
	}
	select {
	case <-ch.Done():
		t.Fatalf("the channel ended (%v): a failed buffering switch must not end the tune", ch.Err())
	default:
	}
	m.Stop("no-alt")
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

**And `relay/channel/source_transcode_real_test.go`, one edit** — its tuning literal at 2c-4's `:102-103` becomes three lines built on `testTuning()` (Constraint 27):

```go
	tuning := testTuning()
	tuning.ChunkBytes, tuning.Retention = buffer.ChunkBytes, time.Minute
	tuning.BufferingSpeed, tuning.BufferingTimeout = 1.0, 300*time.Second
```

Nothing else in that file moves.

### Appendix P — `relay/httpapi/stream.go`

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

	// Probe is the HTTP client validate_stream_url's port probes a Redirect
	// channel's provider with. Nil means one built from probeTimeout that
	// follows redirects, as requests does there.
	Probe *http.Client
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

	// The failover thresholds and the client-loop values 2c-5 reads
	// (channel.Tuning names each one's Python line).
	settingConnectionTimeout   = "CONNECTION_TIMEOUT"
	settingHealthCheckInterval = "HEALTH_CHECK_INTERVAL"
	settingInitGracePeriod     = "channel_init_grace_period"
	settingMaxRetries          = "MAX_RETRIES"
	settingRetryWindow         = "RETRY_WINDOW_SECONDS"
	settingStableThreshold     = "STABLE_CONNECTION_THRESHOLD"
	settingMaxStreamSwitches   = "MAX_STREAM_SWITCHES"
	settingStreamTimeout       = "STREAM_TIMEOUT"
	settingFailoverGrace       = "FAILOVER_GRACE_PERIOD"
	settingKeepaliveInterval   = "KEEPALIVE_INTERVAL"
	settingMaxKeepalive        = "MAX_KEEPALIVE_DURATION"
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
	if t.ConnectionTimeout, err = s.Seconds(settingConnectionTimeout); err != nil {
		return t, 0, err
	}
	if t.HealthCheckInterval, err = s.Seconds(settingHealthCheckInterval); err != nil {
		return t, 0, err
	}
	if t.InitGracePeriod, err = s.Seconds(settingInitGracePeriod); err != nil {
		return t, 0, err
	}
	if t.MaxRetries, err = s.Int(settingMaxRetries); err != nil {
		return t, 0, err
	}
	if t.RetryWindow, err = s.Seconds(settingRetryWindow); err != nil {
		return t, 0, err
	}
	if t.StableThreshold, err = s.Seconds(settingStableThreshold); err != nil {
		return t, 0, err
	}
	if t.MaxStreamSwitches, err = s.Int(settingMaxStreamSwitches); err != nil {
		return t, 0, err
	}
	// _is_timeout's total_timeout is the SUM of two settings
	// (output/ts/generator.py:585-587); both are read, one field holds it.
	streamTimeout, err := s.Seconds(settingStreamTimeout)
	if err != nil {
		return t, 0, err
	}
	failoverGrace, err := s.Seconds(settingFailoverGrace)
	if err != nil {
		return t, 0, err
	}
	t.ClientTimeout = streamTimeout + failoverGrace
	if t.KeepaliveInterval, err = s.Seconds(settingKeepaliveInterval); err != nil {
		return t, 0, err
	}
	if t.MaxKeepalive, err = s.Seconds(settingMaxKeepalive); err != nil {
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
		// request_is_internal (apps/proxy/internal_auth.py): the DVR's own
		// fetch carries the static X-Dispatcharr-Internal and no bound
		// counterpart, and views.py:461 reads it off the decision to keep a
		// Redirect channel from 302ing that header to a provider.
		internal := control.IsInternalPrincipal(deps.Secret, r.Header.Get(control.HeaderInternal))

		ch, release, err := deps.Channels.Attach(id, client, func() (channel.Started, error) {
			return startTune(r.Context(), tuneDeps{control: deps.Control, probe: deps.Probe, log: log}, id, internal)
		})
		if err != nil {
			var redirect *redirectAnswer
			if errors.As(err, &redirect) {
				// The Redirect architecture: no channel, no ring, no bytes
				// (views.py:526-540). HttpResponseRedirect's 302 for an HTTP
				// URL, a hand-built 301 for rtsp/rtp/udp, which Django's
				// redirect class refuses.
				log.Info("redirecting the client to the provider", "channel", id, "status", redirect.Status)
				w.Header().Set("Location", redirect.Location)
				w.WriteHeader(redirect.Status)
				return
			}
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

// ErrUnservedKind is returned when the channel's Stream Profile kind is one
// this relay does not know: not proxy, transcode or redirect, which since
// 2c-5 are all served, so only a control plane newer than this relay can
// produce it. 2c-2's ErrNotProxyKind, renamed when the transcode kind
// started being served.
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
// tuneDeps is what startTune needs beyond the request: the control client,
// the Redirect probe and a logger.
type tuneDeps struct {
	control *control.Client
	probe   *http.Client
	log     *slog.Logger
}

func startTune(parent context.Context, deps tuneDeps, id string, internal bool) (channel.Started, error) {
	ctx, cancel := context.WithTimeout(context.WithoutCancel(parent), tuneBudget)
	defer cancel()
	client := deps.control

	answer, err := client.NextSource(ctx, id, control.NextSourceRequest{
		ExcludeStreamIDs: []int{},
		Reason:           "initial",
		// generate_stream_url asks for the alternates on the initial call
		// (url_utils.py:55-58) and caches them for the degraded fallback and
		// the Redirect fall-through; 2c-2 did not ask, having neither.
		IncludeAlternates: true,
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
	kind := answer.Source.StreamProfile.Kind
	switch kind {
	case control.KindProxy, control.KindTranscode:
	case control.KindRedirect:
		if !internal {
			// views.py:468-547: probe, fall through the cached alternates,
			// release the slot, and hand the client the provider URL.
			return channel.Started{}, redirectTune(ctx, deps, id, answer, defaultUserAgent)
		}
		// views.py:462-467: an internal principal (the DVR) on a Redirect
		// channel is served through Proxy instead, because ffmpeg re-sends
		// its -headers line -- X-Dispatcharr-Internal included -- to
		// whatever a 302 names. `transcode` is forced False there; here the
		// kind is read as Proxy from this point on, force_ffmpeg included.
		deps.log.Info("internal principal on a Redirect-profile channel: serving via Proxy", "channel", id)
		kind = control.KindProxy
	default:
		return channel.Started{}, &ErrUnservedKind{Kind: kind}
	}

	build := sourceBuilder{kind: kind, userAgent: userAgent, readSize: readSize}
	source, err := build.source(answer.Source)
	if err != nil {
		return channel.Started{}, err
	}

	return channel.Started{
		Source: source,
		Tuning: tuning,
		Info:   infoFrom(answer.Source),
		Resolver: &resolver{
			control:    client,
			id:         id,
			build:      build,
			alternates: answer.Alternates,
			log:        deps.log,
		},
	}, nil
}

// infoFrom is what the status endpoints render about a source.
func infoFrom(source *control.Source) channel.SourceInfo {
	return channel.SourceInfo{
		URL:             source.URL,
		StreamProfileID: source.StreamProfile.ID,
		StreamID:        source.StreamID,
		StreamName:      source.StreamName,
		ChannelName:     source.ChannelName,
		M3UProfileID:    source.M3UProfileID,
		M3UProfileName:  source.M3UProfileName,
	}
}

// sourceBuilder turns a control.Source into the Source that plays it, for
// the initial tune and for every failover candidate after it: the kind is
// the channel's profile and never changes across candidates (the answer's
// stream_profile is the channel's, apps/proxy/next_source.py:609-622), the
// user agent is defaulted once (input/manager.py:73), and force_ffmpeg is
// decided per candidate from its own URL (:445-453, on every pass of the
// main loop).
type sourceBuilder struct {
	kind      string
	userAgent string
	readSize  int
}

func (b sourceBuilder) source(candidate *control.Source) (channel.Source, error) {
	userAgent := candidate.UserAgent
	if userAgent == "" {
		userAgent = b.userAgent
	}
	switch {
	case b.kind == control.KindProxy && channel.NeedsFFmpeg(candidate.URL):
		// force_ffmpeg: the Proxy reader cannot follow a playlist or speak
		// RTSP, so the locked ffmpeg profile plays the URL instead.
		if candidate.FFmpegStreamProfile == nil {
			return nil, ErrNoFFmpegProfile
		}
		return transcodeSource(candidate.FFmpegStreamProfile, candidate.URL, userAgent, b.readSize)
	case b.kind == control.KindProxy:
		// The defaulted agent here too: Python's HTTP reader sends
		// self.user_agent (input/manager.py:165), which :73 has already
		// defaulted, so a blank user_agent reaches the provider as
		// DEFAULT_USER_AGENT on both architectures. Found by review; the
		// first draft defaulted only the transcode arms, and a blank agent
		// on the Proxy path would have reached a provider as Go's own.
		return channel.ProxySource{
			URL:       candidate.URL,
			UserAgent: userAgent,
			ChunkSize: b.readSize,
		}, nil
	case b.kind == control.KindTranscode:
		return transcodeSource(&candidate.StreamProfile, candidate.URL, userAgent, b.readSize)
	}
	return nil, &ErrUnservedKind{Kind: b.kind}
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
	case errors.Is(err, ErrRedirectValidationFailed):
		// views.py:542-547: JsonResponse({"error": ...}, status=502).
		log.Error("every redirect candidate failed validation", "channel", id)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(`{"error": "All available streams failed validation"}`))
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

// keepaliveAfterEmptyReads is _should_send_keepalive's `consecutive_empty < 5`
// (output/ts/generator.py:546): a client at the head of an unhealthy channel
// receives keepalives only once five successive reads have found nothing.
const keepaliveAfterEmptyReads = 5

// serveClient is the client loop: position once, then read, write, wait --
// the port of _stream_data_generator (output/ts/generator.py:325-420) with
// its two health-gated mechanisms, both of which 2c-2 and 2c-3 left out
// because nothing could lower the flag they are gated on until 2c-5's
// health monitor arrived:
//
//   - KEEPALIVES (:371-389, :542-551): a client waiting at the buffer head
//     of an UNHEALTHY channel, after five empty reads, is sent one null TS
//     packet every KeepaliveInterval, each refreshing its last-yield time,
//     for at most MaxKeepalive of wall clock, after which it is dropped.
//   - THE CLIENT TIMEOUT (:583-604): a client with no yielded chunk for
//     ClientTimeout on an UNHEALTHY channel is dropped. Its url_switching
//     exemption (:593-596) is not ported -- see the branch itself for why.
//     Row 12's Notes record what this means on the TS path:
//     the keepalives refresh the very timer this reads, so on a channel
//     that is unhealthy for long enough to reach it, it is the keepalive cap
//     that actually ends the client. Ported as it is, because it is the
//     condition Python evaluates; pinned through the cap, because that is
//     the exit a client can reach.
//
// The standard wait (:400-403) sleeps min(0.1 * consecutive_empty, 1.0) and
// re-checks; here Ring.Wait is bounded by the same backoff so the health
// flag is re-read at Python's cadence, and each timeout counts as one empty
// read.
//
// THE ERROR PACKET (:235-239, utils.py:71-98): a client that has received
// NOTHING when its channel ends in error is handed one 188-byte packet
// carrying "Error: <message>" before the body closes -- what the first
// client of a channel whose every source failed sees in Python (row 3's own
// pin reads it), and what Amendment A2.5 recorded 2c-2 as not sending. A
// client already streaming when the channel errors gets a closed body and
// no packet, as _check_resources gives it (:455-459). The initialization
// timeout packet (:249-251, after CLIENT_WAIT_TIMEOUT with no ready state)
// is NOT ported: this relay has no initializing wait a client can time out
// in, and a channel whose source never delivers is ended by the health
// monitor's init grace period instead.
//
// AND NO GHOST-CLIENT DISCONNECT. output/ts/generator.py:579-581's
// _is_ghost_client needs consecutive_empty > 100 AND the buffer 50 chunks
// ahead of the client at the same instant -- a client 50 chunks behind whose
// chunks exist is fed on its next read, which resets consecutive_empty, so the
// two conditions are mutually exclusive outside the expiry window
// find_oldest_available_chunk already recovers from. Not ported, and the
// reason is that it is unreachable rather than that it is 2c-5's.
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

	// POSITIONED ONCE, at setup, exactly as output/ts/generator.py:264-302
	// positions a client -- and this is the call parity-matrix row 8 is
	// about, because from 2c-3 onward the ring the client joins is usually
	// one ANOTHER client has been filling. A JoinBehind of zero means the
	// live head, which is what new_client_behind_seconds = 0 means there.
	cursor := ring.Head()
	if tuning.JoinBehind > 0 {
		cursor = ring.Join(tuning.JoinBehind)
	}

	var sent int
	lastYield := time.Now()
	var keepaliveStart time.Time
	empties := 0
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
			for _, c := range chunks {
				sent += len(c)
			}
			lastYield = time.Now()
			keepaliveStart = time.Time{}
			empties = 0
			continue
		}

		empties++
		wait := min(time.Duration(empties)*100*time.Millisecond, time.Second)
		if !ch.Healthy() && empties >= keepaliveAfterEmptyReads {
			if keepaliveStart.IsZero() {
				keepaliveStart = time.Now()
			}
			if time.Since(keepaliveStart) > tuning.MaxKeepalive {
				log.Warn("keepalive duration exceeded with no stream recovery, disconnecting",
					"channel", ch.ID(), "client", client.ID, "max", tuning.MaxKeepalive)
				return
			}
			if !writeChunks(w, rc, [][]byte{signalPacket("")}) {
				return
			}
			sent += buffer.TSPacketSize
			lastYield = time.Now()
			wait = tuning.KeepaliveInterval
		} else if time.Since(lastYield) > tuning.ClientTimeout && !ch.Healthy() {
			// _is_timeout (:583-604) minus its url_switching exemption
			// (:593-596), which is not ported: url_switching is true only
			// inside update_url's own body (input/manager.py:1476-1540), a
			// window of at most the old process's kill-and-join, and a
			// client reprieved there is dropped on its next poll anyway.
			log.Warn("no data and the stream is unhealthy, disconnecting",
				"channel", ch.ID(), "client", client.ID, "timeout", tuning.ClientTimeout)
			return
		}

		waitCtx, cancel := context.WithTimeout(ctx, max(wait, time.Millisecond))
		err := ring.Wait(waitCtx, cursor)
		cancel()
		switch {
		case err == nil:
			continue
		case errors.Is(err, context.DeadlineExceeded) && ctx.Err() == nil:
			// One empty read; round again.
			continue
		case errors.Is(err, buffer.ErrClosed):
			// One last read. The writer may have published between the Read
			// above and Close, and without this the tail of a stream that
			// ended cleanly is dropped.
			if final, _, _ := ring.Read(cursor); len(final) > 0 {
				writeChunks(w, rc, final)
				sent += len(final[0])
			}
			if sent == 0 {
				if message := errorPacketMessage(ch); message != "" {
					writeChunks(w, rc, [][]byte{signalPacket(message)})
				}
			}
		}
		return
	}
}

// errorPacketMessage is the text _wait_for_initialization puts in the error
// packet for a channel that ended before the client's first byte
// (output/ts/generator.py:235-239): the error message the channel recorded,
// "Unknown error" when a stopped channel recorded none, and nothing for a
// channel that is still running.
func errorPacketMessage(ch *channel.Channel) string {
	switch ch.State() {
	case channel.StateError:
		var exhausted *channel.ErrSourcesExhausted
		if errors.As(ch.Err(), &exhausted) {
			return "Error: " + exhausted.Message()
		}
		return "Error: Unknown error"
	case channel.StateStopped, channel.StateStopping:
		return "Error: Unknown error"
	}
	return ""
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

### Appendix Q — `relay/httpapi/channels.go`

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
// ONE CONDITIONAL FIELD IS STILL ABSENT after 2c-5, with a reason rather
// than a gap:
//
//	logo_id        NEVER EMITTED BY PYTHON EITHER. ChannelMetadataField.LOGO_ID
//	               is written only into the timeshift key family
//	               (apps/timeshift/views.py:2984), never into the live hash
//	               channel_status.py:486 reads, so the `if not raw: continue`
//	               always continues. Exact parity by doing nothing.
//
// healthy arrived in 2c-5 with the health monitor: channel_status.py:527-529
// sets it only when the answering process holds the channel's StreamManager
// -- which the single relay process always does for a channel in its map --
// so it is present on every channel this relay lists, true from the tune
// until the monitor sees no data for the inactivity threshold.
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
	Healthy        *bool    `json:"healthy,omitempty"`
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

	// healthy (:527-529): the health monitor's flag, on every channel this
	// process holds.
	healthy := c.Healthy()
	out.Healthy = &healthy

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

### Appendix R — `relay/channel/manager_test.go`

**`relay/channel/manager_test.go`**

```go
package channel

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// testTuning is the channel-start-time settings every channel test runs on.
// The ten failover fields carry apps/proxy/config.py's own values -- the
// production shape, so a 2c-2 test that drives a 404 now sees three attempts
// and 0.75s of backoff, as the Python relay would. A test whose SUBJECT is
// one of these thresholds overrides it with a non-default value (hollow
// shape 2: a pin that supplies the default pins nothing).
func testTuning() Tuning {
	return Tuning{
		ChunkBytes:          buffer.TSPacketSize * 4,
		Retention:           time.Minute,
		ConnectionTimeout:   10 * time.Second,
		HealthCheckInterval: 5 * time.Second,
		InitGracePeriod:     60 * time.Second,
		MaxRetries:          3,
		RetryWindow:         1800 * time.Second,
		StableThreshold:     30 * time.Second,
		MaxStreamSwitches:   10,
		ClientTimeout:       40 * time.Second,
		KeepaliveInterval:   500 * time.Millisecond,
		MaxKeepalive:        300 * time.Second,
	}
}

// asStarted wraps a 2c-2-shaped start function in 2c-3's Started shape.
func asStarted(f func() (Source, Tuning, error)) func() (Started, error) {
	return func() (Started, error) {
		source, tuning, err := f()
		return Started{Source: source, Tuning: tuning}, err
	}
}

// testClient is a registry row with a caller-chosen id. Distinct ids matter:
// two Attach calls under ONE id are a duplicate registration and are refused
// (ErrDuplicateClient), which is parity-matrix row 13's first half and exactly
// what these tests must not accidentally exercise.
func testClient(id string) *Client {
	return &Client{ID: id, UserID: "0", OutputFormat: "mpegts"}
}

// A source that blocks until its context is done, counting how many times it
// was started.
type blockingSource struct{ started *int32Counter }

func (s blockingSource) Run(ctx context.Context, _ io.Writer) error {
	s.started.inc()
	<-ctx.Done()
	return ctx.Err()
}

type int32Counter struct {
	mu sync.Mutex
	n  int
}

func (c *int32Counter) inc() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.n++
}

func (c *int32Counter) get() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.n
}

// Two clients on one channel start ONE source, and the second never calls the
// control plane. Counted at the source, not at the manager, so it fails if
// Attach starts a second reader however it managed to.
func TestTwoClientsShareOneSource(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	started := &int32Counter{}
	starts := &int32Counter{}
	start := func() (Source, Tuning, error) {
		starts.inc()
		return blockingSource{started: started}, testTuning(), nil
	}

	first, releaseFirst, err := m.Attach("chan-1", testClient("a"), asStarted(start))
	if err != nil {
		t.Fatalf("first Attach: %v", err)
	}
	second, releaseSecond, err := m.Attach("chan-1", testClient("b"), asStarted(start))
	if err != nil {
		t.Fatalf("second Attach: %v", err)
	}
	if first != second {
		t.Fatal("the second client got a different Channel")
	}
	if got := starts.get(); got != 1 {
		t.Fatalf("the start function ran %d times, want 1 -- the second client "+
			"must not call the control plane", got)
	}
	if got := first.Clients(); got != 2 {
		t.Fatalf("Clients() = %d, want 2", got)
	}
	// The source goroutine starts after Attach returns; releasing before it
	// has called Run would count zero runs and prove nothing about sharing.
	waitFor(t, "the source to start", 5*time.Second, func() bool { return started.get() == 1 })

	releaseSecond()
	if m.Get("chan-1") == nil {
		t.Fatal("the channel stopped when the second of two clients left")
	}
	releaseFirst()
	if m.Get("chan-1") != nil {
		t.Fatal("the channel is still running after its last client left")
	}
	<-first.Done()
	if state := first.State(); state != StateStopping && state != StateStopped {
		t.Fatalf("state = %q after teardown", state)
	}
	if got := started.get(); got != 1 {
		t.Fatalf("the source ran %d times, want 1", got)
	}
}

// The one upstream CONNECTION, as the provider sees it. The test above counts
// starts inside this process; this one counts HTTP requests at the provider,
// which is what parity-matrix row 10 is actually about.
func TestTwoClientsMakeOneUpstreamRequest(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{Rate: 0.05})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	start := func() (Source, Tuning, error) {
		return ProxySource{URL: up.URL()}, testTuning(), nil
	}
	ch, releaseFirst, err := m.Attach("chan-2", testClient("a"), asStarted(start))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	_, releaseSecond, err := m.Attach("chan-2", testClient("b"), asStarted(start))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}

	deadline := time.Now().Add(5 * time.Second)
	for ch.Ring().Head() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if ch.Ring().Head() == 0 {
		t.Fatal("no chunk was published within five seconds")
	}
	if got := up.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1 -- two clients must share one upstream", got)
	}

	releaseSecond()
	releaseFirst()
	<-ch.Done()
}

// A CLEAN UPSTREAM EOF IS A CONNECTION FAILURE, retried and counted, not the
// stream ending: fetch_chunk reads an empty chunk as "Server closed
// connection" (input/manager.py:1870-1875), _process_stream_data returns,
// and the retry loop records a failure and reconnects (:555-563). Three of
// them exhaust the source (:534-537, parity-matrix row 3); with nothing to
// fail over to, the channel ends in error naming the attempts, and its ring
// closes so no reader blocks forever. 2c-2 ended the channel on the first
// EOF, which was the honest shape before there was a retry loop to run;
// this is the Python one.
func TestACleanUpstreamEndIsRetriedAndThenExhaustsTheSource(t *testing.T) {
	payload := relaytest.SyntheticTS(8, 0x100)
	up := relaytest.NewUpstream(relaytest.Config{Payload: payload, StopAfterBytes: len(payload)})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	ch, release, err := m.Attach("chan-3", testClient("a"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: up.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	defer release()

	select {
	case <-ch.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("the source goroutine did not return after the upstream ended three times")
	}
	if got := up.Requests(); got != 3 {
		t.Fatalf("the provider saw %d requests, want MAX_RETRIES = 3: a clean EOF is reconnected, not accepted", got)
	}
	if state := ch.State(); state != StateError {
		t.Fatalf("state = %q after three clean EOFs, want %q", state, StateError)
	}
	var exhausted *ErrSourcesExhausted
	if !errors.As(ch.Err(), &exhausted) || exhausted.Message() != "Connection failed after 3 attempts" {
		t.Fatalf("Err() = %v, want ErrSourcesExhausted saying \"Connection failed after 3 attempts\" (input/manager.py:682)", ch.Err())
	}
	// Asked AT THE HEAD, not at cursor 0. Wait reports freshness before
	// closure, so a caught-up reader is the only one that can observe the
	// ring being shut -- a reader with a backlog is correctly told to come
	// and get it first.
	if err := ch.Ring().Wait(t.Context(), ch.Ring().Head()); !errors.Is(err, buffer.ErrClosed) {
		t.Fatalf("Wait at the head returned %v, want ErrClosed -- the ring is still "+
			"open after the source returned, and every reader would block forever", err)
	}
}

// A channel with one attached client and flowing bytes reaches active --
// found broken by review: the prior mechanism (a manager-side markActive,
// called only on a SECOND client's Attach) measured 0/300 rounds ever
// reaching it, because a channel's first client never triggered it and
// run()'s own concurrent write of waiting_for_clients usually raced a
// second client's call into a no-op. promoteOnFirstChunk is now the one
// mechanism, driven by the ring publishing its first chunk rather than by
// how many clients have attached.
func TestAChannelWithFlowingBytesBecomesActive(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{Rate: 0.2})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	ch, release, err := m.Attach("chan-active", testClient("a"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: up.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	defer release()

	deadline := time.Now().Add(5 * time.Second)
	for ch.State() != StateActive && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if state := ch.State(); state != StateActive {
		t.Fatalf("state = %q after bytes flowed for up to five seconds, want %q", state, StateActive)
	}
	if got := ch.Describe(); !strings.Contains(got, "state=active") {
		t.Fatalf("Describe() = %q, want it to report state=active", got)
	}
}

// A source that fails to start leaves the channel in error, and the failure
// reaches the caller rather than becoming a channel that streams nothing.
func TestAnUpstreamFailurePutsTheChannelInError(t *testing.T) {
	up := relaytest.NewUpstream(relaytest.Config{Status: 404})
	t.Cleanup(up.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	ch, release, err := m.Attach("chan-4", testClient("a"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: up.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	defer release()

	select {
	case <-ch.Done():
	case <-time.After(10 * time.Second):
		t.Fatal("the source goroutine did not return after three 404s")
	}
	if state := ch.State(); state != StateError {
		t.Fatalf("state = %q after an upstream 404, want %q", state, StateError)
	}
	// Three attempts (MAX_RETRIES) before the source is exhausted, and the
	// last attempt's error still visible through the exhaustion wrapper.
	if got := up.Requests(); got != 3 {
		t.Fatalf("the provider saw %d requests, want 3", got)
	}
	var status *ErrUpstreamStatus
	if !errors.As(ch.Err(), &status) || status.Status != 404 {
		t.Fatalf("Err() = %v, want an *ErrUpstreamStatus carrying 404 inside the exhaustion error", ch.Err())
	}
}

// B1. A panic inside start() must not leave the manager locked. Before the
// gate-and-defer restructure this wedged the relay permanently: /healthz kept
// answering 200 while every later Attach blocked forever on a mutex nobody
// would release.
func TestAPanickingStartDoesNotWedgeTheManager(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	func() {
		defer func() {
			if recover() == nil {
				t.Error("the panic did not propagate to the caller")
			}
		}()
		_, _, _ = m.Attach("boom", testClient("a"), asStarted(func() (Source, Tuning, error) {
			panic("the control plane exploded")
		}))
	}()

	done := make(chan struct{})
	go func() {
		defer close(done)
		_, release, err := m.Attach("after", testClient("a"), asStarted(func() (Source, Tuning, error) {
			return blockingSource{started: &int32Counter{}}, testTuning(), nil
		}))
		if err != nil {
			t.Errorf("the Attach after the panic failed: %v", err)
			return
		}
		release()
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("the Attach after a panicking start blocked: the manager lock was " +
			"never released, and every tune on this process is now stuck")
	}
}

// The same property for the channel that panicked: its gate must have been
// closed, or a second client for THAT id waits on it forever.
func TestAPanickingStartReleasesItsGate(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
	t.Cleanup(m.StopAll)

	func() {
		defer func() { _ = recover() }()
		_, _, _ = m.Attach("boom", testClient("a"), asStarted(func() (Source, Tuning, error) { panic("boom") }))
	}()

	done := make(chan struct{})
	go func() {
		defer close(done)
		_, release, err := m.Attach("boom", testClient("a"), asStarted(func() (Source, Tuning, error) {
			return blockingSource{started: &int32Counter{}}, testTuning(), nil
		}))
		if err != nil {
			t.Errorf("retrying the panicked channel failed: %v", err)
			return
		}
		release()
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("a second client for the panicked channel waited on a gate that was never closed")
	}
}

// SF4. A channel whose source has returned is finished: its ring is closed and
// nothing will ever be published to it again. Handing it to a new client
// serves the residual buffer and then EOF, with no re-tune and no error -- so
// a channel whose upstream 404'd would answer every later viewer with an empty
// 200, forever.
func TestAFinishedChannelIsNotHandedToANewClient(t *testing.T) {
	dead := relaytest.NewUpstream(relaytest.Config{Status: 404})
	t.Cleanup(dead.Close)
	live := relaytest.NewUpstream(relaytest.Config{Rate: 0.05})
	t.Cleanup(live.Close)

	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)

	first, releaseFirst, err := m.Attach("chan-5", testClient("a"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: dead.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("first Attach: %v", err)
	}
	<-first.Done()
	if first.State() != StateError {
		t.Fatalf("state = %q after a 404, want %q", first.State(), StateError)
	}

	// The first client is still attached, which is the case that matters: a
	// release would have stopped the channel anyway.
	second, releaseSecond, err := m.Attach("chan-5", testClient("b"), asStarted(func() (Source, Tuning, error) {
		return ProxySource{URL: live.URL()}, testTuning(), nil
	}))
	if err != nil {
		t.Fatalf("second Attach: %v", err)
	}
	defer releaseSecond()
	defer releaseFirst()

	if second == first {
		t.Fatal("the second client was handed the finished channel: it would read the " +
			"residual buffer and then EOF, with no re-tune")
	}
	// Polled, not asserted immediately: the source goroutine starts after
	// Attach returns, so a bare assertion here would race the dial rather
	// than test the re-tune.
	deadline := time.Now().Add(5 * time.Second)
	for live.Requests() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if got := live.Requests(); got != 1 {
		t.Fatalf("the live provider saw %d requests, want 1 -- the second client did not re-tune", got)
	}
}

// A downstream reviewer's claim, verified here before being trusted: the
// last client's release() and a concurrent Attach on the same id are not
// mutually exclusive unless the "am I still idle" re-check runs under the
// SAME lock claim() holds across its own map-read-and-addClient. Confirmed
// real against the pre-fix code -- a plain c.Clients() == 0 check taken
// outside m.mu -- at roughly one race in several thousand rounds: the
// arriving client's claim() would see the channel still in the map, add
// itself, and be handed a *Channel that the releasing goroutine's Stop then
// tore down anyway, because its decision was made from a snapshot the
// arriving client had already invalidated.
func TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined(t *testing.T) {
	const rounds = 20000
	for round := range rounds {
		counter := &int32Counter{}
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})

		_, releaseFirst, err := m.Attach("shared", testClient("a"), asStarted(func() (Source, Tuning, error) {
			return blockingSource{started: counter}, testTuning(), nil
		}))
		if err != nil {
			t.Fatalf("round %d: first Attach: %v", round, err)
		}

		var wg sync.WaitGroup
		var second *Channel
		var releaseSecond func()
		var secondErr error
		start := make(chan struct{})
		wg.Add(2)
		go func() {
			defer wg.Done()
			<-start
			releaseFirst()
		}()
		go func() {
			defer wg.Done()
			<-start
			second, releaseSecond, secondErr = m.Attach("shared", testClient("b"), asStarted(func() (Source, Tuning, error) {
				return blockingSource{started: counter}, testTuning(), nil
			}))
		}()
		close(start)
		wg.Wait()

		if secondErr != nil {
			t.Fatalf("round %d: second Attach: %v", round, secondErr)
		}
		if second == nil {
			t.Fatalf("round %d: second Attach returned a nil channel with no error", round)
		}
		// THE PROPERTY: whichever channel the second client was handed --
		// the first's, if it won the race, or a freshly started one, if the
		// first's had already been removed -- it must not be a channel that
		// is stopping or stopped out from under a client that just arrived.
		if state := second.State(); state == StateStopping || state == StateStopped {
			t.Fatalf("round %d: the second client was handed a %s channel", round, state)
		}
		releaseSecond()

		// After both releases, exactly the sources this round started must
		// have stopped -- no leaked goroutine still holding a "started" slot
		// this manager no longer has a map entry for.
		deadline := time.Now().Add(5 * time.Second)
		for len(m.ids()) != 0 {
			if time.Now().After(deadline) {
				t.Fatalf("round %d: the manager still holds %d channel(s) after both clients released",
					round, len(m.ids()))
			}
			time.Sleep(time.Millisecond)
		}
	}
}
```

### Appendix S — `relay/httpapi/stream_test.go`

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
	Emitter  *control.Emitter
}

func newRig(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config) *rig {
	t.Helper()
	return newRigWithClient(t, cp, up, control.NewHTTPClient())
}

// newRigWithClient is newRig with the control client's transport chosen by
// the test: how the budget-shape test compresses ConnectTimeout+ReadTimeout
// to something a test can wait out.
func newRigWithClient(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config, httpClient *http.Client) *rig {
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

	// ONE control client, as main.go builds one: the tune, the failover,
	// the release on teardown and the events all go through it, so the fake
	// sees them in one request log.
	client := &control.Client{Secret: testSecret, BaseURL: controlPlane.URL(), HTTP: httpClient}
	emitter := control.NewEmitter(client, nil)
	manager := channel.NewManager(channel.ManagerConfig{
		BudgetBytes: rigBudgetBytes,
		Events:      EventSink(emitter),
		Release:     ReleaseVia(client, nil),
	})
	// Order matters: channels stop (and release) before the emitter drains,
	// and the emitter drains before the fake closes.
	t.Cleanup(emitter.Close)
	t.Cleanup(manager.StopAll)

	server := New(Config{
		DevRoutes: true,
		Stream: StreamDeps{
			Secret:   testSecret,
			Channels: manager,
			Control:  client,
		},
		// THE SAME manager, not a second one. Two would give the list endpoint
		// an empty map while the tune path filled another, and every assertion
		// about what the list shows would be about the wrong object.
		Control: ControlDeps{Secret: testSecret, Channels: manager},
	})
	relay := httptest.NewServer(server.Handler())
	t.Cleanup(relay.Close)

	return &rig{Relay: relay, Upstream: upstream, Control: controlPlane, Manager: manager, Emitter: emitter}
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

// The relay refuses a kind it does not know loudly rather than falling
// through. `kind` is what it branches on: `transcode` is false for Redirect
// as well as Proxy, so a relay that read that field would serve a Redirect
// channel's provider URL through the Proxy path silently. All three kinds
// are served since 2c-5 (2c-2 listed transcode and redirect here), so the
// kind that can reach this arm is one a newer control plane invents.
func TestATuneRefusesAKindItDoesNotServe(t *testing.T) {
	for _, kind := range []string{"hls-passthrough"} {
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
		settingChunkBytes, settingRetention, settingJoinBehind, settingReadSize, settingShutdownDelay,
		settingBufferingSpeed, settingBufferingTimeout, settingDefaultUserAgent,
		settingConnectionTimeout, settingHealthCheckInterval, settingInitGracePeriod, settingMaxRetries,
		settingRetryWindow, settingStableThreshold, settingMaxStreamSwitches, settingStreamTimeout,
		settingFailoverGrace, settingKeepaliveInterval, settingMaxKeepalive,
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

// A stream that ends cleanly is RECONNECTED, three times, before the source
// is exhausted (input/manager.py:1870-1875 and the retry loop; 2c-2 ended
// the tune on the first EOF, before there was a loop) -- and only then does
// the client's response end rather than hang, with every byte the provider
// sent across the three connections. With no alternate on the fake control
// plane, the failover finds nothing and the channel errors.
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
	case <-time.After(20 * time.Second):
		t.Fatal("the client's response never ended after the upstream stopped")
	}
	if n := rig.Upstream.Requests(); n != 3 {
		t.Fatalf("the provider saw %d requests, want MAX_RETRIES = 3: a clean EOF is reconnected before the source is given up", n)
	}
	// The failover asked the control plane, which had nothing left once
	// stream 1 was excluded.
	if calls := rig.Control.RequestsTo("/next-source"); len(calls) != 2 || !strings.Contains(string(calls[1].Body), `"reason":"failover"`) {
		t.Fatalf("the control plane saw %d next-source calls, want the tune and one failover: %+v", len(calls), calls)
	}
}
```

### Appendix T — `relay/httpapi/transcode_test.go`

**`relay/httpapi/transcode_test.go`**

```go
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
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
	// The whole capture is on stderr before the stand-in exits, by
	// construction (RunStandIn joins its stderr pump; break-check 22), and
	// at interval 0 it is written in one burst, so the last record is the
	// one reported once the reader has drained it. Waited for rather than
	// assumed, because the reader and the copy loop are two goroutines.
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
// DEFAULT_USER_AGENT on BOTH architectures, as input/manager.py:73 does for
// the whole StreamManager: the transcode source's UDP filter reads it, and
// the Proxy reader sends it (:165). Asserted on the source startTune builds,
// against the fixture's own literal, because nothing about a blank agent is
// visible from outside on a non-UDP transcode tune -- and on the Proxy path
// the provider would see Go's own default instead, which review found the
// first draft allowing.
func TestABlankUserAgentFallsBackToTheWireDefault(t *testing.T) {
	const wireDefault = "VLC/3.0.20 LibVLC/3.0.20"
	t.Run("transcode", func(t *testing.T) {
		cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{
			Kind: control.KindTranscode, SourceURL: "udp://239.0.0.1:1234", BlankUserAgent: true,
			Command: "ffmpeg", Argv: []string{"-i", "udp://239.0.0.1:1234"}, Settings: rigSettings(nil),
		})
		t.Cleanup(cp.Close)
		started, err := startTune(context.Background(), tuneDeps{control: &control.Client{Secret: testSecret, BaseURL: cp.URL(), HTTP: control.NewHTTPClient()}, log: slog.Default()}, "c-ua", false)
		if err != nil {
			t.Fatalf("startTune: %v", err)
		}
		source, ok := started.Source.(*channel.TranscodeSource)
		if !ok {
			t.Fatalf("the source is a %T, want *channel.TranscodeSource", started.Source)
		}
		if source.UserAgent != wireDefault {
			t.Fatalf("UserAgent = %q, want the wire's DEFAULT_USER_AGENT", source.UserAgent)
		}
		if source.Command != "ffmpeg" || len(source.Argv) != 2 {
			t.Fatalf("the source was built from the wrong profile: %+v", source)
		}
	})
	t.Run("proxy", func(t *testing.T) {
		cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{
			Kind: control.KindProxy, SourceURL: "http://provider.invalid/live.ts", BlankUserAgent: true,
			Settings: rigSettings(nil),
		})
		t.Cleanup(cp.Close)
		started, err := startTune(context.Background(), tuneDeps{control: &control.Client{Secret: testSecret, BaseURL: cp.URL(), HTTP: control.NewHTTPClient()}, log: slog.Default()}, "c-ua-proxy", false)
		if err != nil {
			t.Fatalf("startTune: %v", err)
		}
		source, ok := started.Source.(channel.ProxySource)
		if !ok {
			t.Fatalf("the source is a %T, want channel.ProxySource", started.Source)
		}
		if source.UserAgent != wireDefault {
			t.Fatalf("UserAgent = %q, want the wire's DEFAULT_USER_AGENT -- a blank agent would reach the provider as Go's own", source.UserAgent)
		}
	})
}

// A transcode child that exits non-zero is a connection failure: three of
// them exhaust the source (row 3's accounting), the client's response ends,
// and the channel is in error still carrying the child's code through the
// exhaustion error.
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
	case <-time.After(30 * time.Second):
		t.Fatal("the response never ended after the child exited three times")
	}
	<-ch.Done()
	var exited interface{ Error() string }
	if !errors.As(ch.Err(), &exited) || !strings.Contains(ch.Err().Error(), "status 2") {
		t.Fatalf("Err() = %v, want the child's exit status 2", ch.Err())
	}
	if n := r.Upstream.Requests(); n != 3 {
		t.Fatalf("the provider saw %d requests, want 3: one per attempt on the same source", n)
	}
}

var _ = buffer.TSPacketSize
```

### Appendix U — `relay/main.go`

**`relay/main.go`**

```go
// Command relay-go is the Go relay. At stage 2c-1 it binds its port, answers
// /healthz and /readyz, and does nothing else: nginx routes no location to
// this process until stage 2d, and every route beyond the two health
// endpoints is behind the dev flag.
package main

import (
	"errors"
	"log"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/config"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/httpapi"
)

func main() {
	log.SetFlags(log.LstdFlags | log.LUTC)
	log.SetPrefix("relay-go: ")

	cfg, err := config.Load()
	if err != nil {
		// Exit rather than degrade. supervisord's startretries=20 will show
		// this line twenty times in the container log, which is the loud
		// failure a misconfigured secret deserves -- the alternative is a
		// process that serves health checks happily and 403s every internal
		// call with nothing saying why.
		log.Printf("startup failed: %v", err) // credential-logging: ok - config.Load's errors name a variable, a port, or the secret FILE's path, never the secret
		os.Exit(1)
	}

	// The secret is never logged, in any form, at any level -- not its value,
	// not its length, not a prefix. scripts/check_credential_logging.py polices
	// the Python side of this rule; there is no Go equivalent yet, so it is
	// held by hand here.
	log.Printf("starting on port %d (dev routes: %t)", cfg.Port, cfg.DevRoutes)

	// THE SAME manager, not a second one. Two would give the list endpoint
	// an empty map while the tune path filled another, and every assertion
	// about what the list shows would be about the wrong object.
	// One control client for the tune path, the failover, the release on
	// teardown and the events; one emitter behind it, so an outage is logged
	// once for the whole process as control_plane.py's module flag does.
	client := &control.Client{Secret: cfg.Secret}
	emitter := control.NewEmitter(client, slog.Default())
	channels := channel.NewManager(channel.ManagerConfig{
		Events:  httpapi.EventSink(emitter),
		Release: httpapi.ReleaseVia(client, slog.Default()),
	})
	srv := &http.Server{
		Addr: net.JoinHostPort("0.0.0.0", strconv.Itoa(cfg.Port)),
		Handler: httpapi.New(httpapi.Config{
			DevRoutes: cfg.DevRoutes,
			Stream: httpapi.StreamDeps{
				Secret:   cfg.Secret,
				Channels: channels,
				Control:  client,
			},
			Control: httpapi.ControlDeps{Secret: cfg.Secret, Channels: channels},
		}).Handler(),

		// ReadHeaderTimeout only. A read or write deadline on the whole
		// request would be wrong for this process by construction: serving
		// long-lived responses is the reason it exists, and it is why
		// docker/uwsgi.relay.ini carries no harakiri either. Bounding just
		// the header read closes the slow-header class without touching the
		// body, which is the stream.
		ReadHeaderTimeout: 10 * time.Second,

		// IdleTimeout bounds an idle KEEP-ALIVE connection -- the gap between
		// one request finishing and the next starting on the same socket. It
		// never touches a stream in flight, because a stream is one request
		// that has not finished, which is why this is safe on a process whose
		// whole purpose is long-lived responses. 120s is comfortably longer
		// than any client's gap between requests and short enough that an
		// abandoned socket does not outlive the session.
		IdleTimeout: 120 * time.Second,
	}

	// No graceful shutdown here. D6's SIGTERM drain is 2c-8's, and a
	// half-implemented drain -- one that stops accepting but does not wait for
	// anything, because there is nothing to wait for yet -- would look like
	// the feature while being the default. supervisord's stopwaitsecs=20
	// bounds the stop either way.
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Printf("server stopped: %v", err) // credential-logging: ok - a net.Listen or Serve error naming the bind address
		os.Exit(1)
	}
}
```

### Appendix V — `relay/httpapi/failover.go`

**`relay/httpapi/failover.go`**

```go
package httpapi

import (
	"context"
	"errors"
	"log/slog"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
)

// resolver is channel.Resolver over the control client: the control-plane
// half of _try_next_stream (input/manager.py:2076-2131) and the whole of its
// degraded fallback, which is why it is one per channel -- it holds the
// candidate list the initial answer carried, the in-memory form of
// live:channel:{id}:source_cache (spec § Stage 2c's key-family table,
// "Degraded-fallback cache: an in-memory field on the channel struct").
//
// THE DISPOSITION IS THE SPEC'S ERROR TABLE, and the distinction it turns on
// is the one apps/proxy/control_plane.py:118-136 draws: only an Unavailable
// -- a transport failure or a 5xx, both already retried once by the client
// -- falls back to the cache, "stale, unenforced, and no slot moves"
// (input/manager.py:2107-2112). A Refused (a 404 for a deleted channel, a
// 403 from a SECRET_KEY mismatch between roles) fails the switch loudly,
// because "the cached list would keep a deleted channel streaming, and a
// token fault would make every failover on the deployment degrade forever
// instead of failing once" (:2084-2098). A null source is ErrNoAlternate.
//
// THE TIMING SHAPE IS THE CLIENT'S: a failover against an unreachable
// control plane costs two attempts of (ConnectTimeout, ReadTimeout) plus the
// retry delay -- up to ~14 s of dead air on a hang, CLAUDE.md § Operationally
// -- before the cache is consulted, exactly as the Python relay spends
// control_plane.py's budget first. The context is bounded by tuneBudget for
// the same reason startTune's is.
type resolver struct {
	control    *control.Client
	id         string
	build      sourceBuilder
	alternates []control.Source
	log        *slog.Logger
}

func (r *resolver) Next(parent context.Context, req channel.NextRequest) (channel.Resolved, error) {
	ctx, cancel := context.WithTimeout(parent, tuneBudget)
	defer cancel()

	current := req.CurrentStreamID
	request := control.NextSourceRequest{
		ExcludeStreamIDs: req.Exclude,
		Reason:           "failover",
		CurrentURL:       req.CurrentURL,
	}
	if current != 0 {
		request.CurrentStreamID = &current
	}

	answer, err := r.control.NextSource(ctx, r.id, request)
	switch {
	case err == nil:
		if answer.Source == nil {
			return channel.Resolved{}, channel.ErrNoAlternate
		}
		return r.resolved(answer.Source, false)
	case isUnavailable(err):
		r.log.Warn("control plane unreachable during failover; using the cached candidate list unenforced", "channel", r.id)
		candidate := r.pickCached(req)
		if candidate == nil {
			return channel.Resolved{}, channel.ErrNoAlternate
		}
		return r.resolved(candidate, true)
	default:
		// A Refused, or a misconfigured address: never degrade.
		return channel.Resolved{}, err
	}
}

func isUnavailable(err error) bool {
	var unavailable *control.Unavailable
	return errors.As(err, &unavailable)
}

// pickCached is _pick_cached_alternate (input/manager.py:2020-2039): the
// first cached candidate not already tried and not the URL playing. The
// shape checks there guard a cache written by an older Django; here the
// candidates were decoded by control.Source and a candidate with no stream
// id or URL is skipped for the same reason.
func (r *resolver) pickCached(req channel.NextRequest) *control.Source {
	excluded := map[int]bool{}
	for _, id := range req.Exclude {
		excluded[id] = true
	}
	for i := range r.alternates {
		candidate := &r.alternates[i]
		if candidate.StreamID == 0 || candidate.URL == "" {
			continue
		}
		if excluded[candidate.StreamID] || candidate.URL == req.CurrentURL {
			continue
		}
		return candidate
	}
	return nil
}

// resolved builds the Source for a candidate. A candidate whose profile
// cannot be built -- a null argv, Amendment A4.3 -- is TERMINAL for that
// candidate: reported as the switch's failure, never retried as a
// connection failure, because no retry against the same profile can change
// what Django could not split.
func (r *resolver) resolved(candidate *control.Source, degraded bool) (channel.Resolved, error) {
	source, err := r.build.source(candidate)
	if err != nil {
		return channel.Resolved{}, err
	}
	return channel.Resolved{Source: source, Info: infoFrom(candidate), Degraded: degraded}, nil
}
```

### Appendix W — `relay/httpapi/events.go`

**`relay/httpapi/events.go`**

```go
package httpapi

import (
	"context"
	"log/slog"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// EventSink adapts control.Emitter to channel.EventSink, field for field.
// The two types exist so package channel never imports the wire package;
// this is the whole of the seam between them.
func EventSink(emitter *control.Emitter) channel.EventSink {
	return eventSink{emitter}
}

type eventSink struct{ emitter *control.Emitter }

func (s eventSink) Emit(e channel.Event) {
	s.emitter.Emit(control.Event{
		Type:        e.Type,
		ChannelID:   e.ChannelID,
		ChannelName: e.ChannelName,
		ClientID:    e.ClientID,
		StreamID:    e.StreamID,
		Details:     e.Details,
	})
}

// ReleaseVia is the manager's Release hook over the control client: the
// port of live_proxy/server.py:2335-2385's _release_stream_resources,
// called once per channel when its source goroutine returns. A refusal or
// an outage is logged and the slot "stays counted", exactly as there; the
// call is bounded by the client's own worst case, since a channel's
// teardown must not wait on a hung control plane.
func ReleaseVia(client *control.Client, log *slog.Logger) func(id string, info channel.SourceInfo) {
	if log == nil {
		log = slog.Default()
	}
	return func(id string, info channel.SourceInfo) {
		ctx, cancel := context.WithTimeout(context.Background(), tuneBudget)
		defer cancel()
		req := control.ReleaseRequest{}
		if info.StreamID != 0 {
			streamID := info.StreamID
			req.StreamID = &streamID
		}
		if info.M3UProfileID != 0 {
			profileID := info.M3UProfileID
			req.M3UProfileID = &profileID
		}
		released, err := client.Release(ctx, id, req)
		switch {
		case err != nil:
			log.Warn("could not release the provider slot; it stays counted", "channel", id, "error", redact.Error(err))
		case !released:
			log.Debug("the control plane found no slot to release", "channel", id)
		}
	}
}
```

### Appendix X — `relay/httpapi/failover_test.go`

**`relay/httpapi/failover_test.go`**

```go
package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// failoverRig is a rig whose control plane knows a second stream, served by
// a second upstream: the shape every failover test needs. The primary is the
// rig's own upstream, configured by `primary`; the alternate loops the same
// asset unpaced.
func failoverRig(t *testing.T, primary relaytest.Config, overrides map[string]any) (*rig, *relaytest.Upstream) {
	t.Helper()
	alternate := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100)})
	t.Cleanup(alternate.Close)
	cp := relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}
	return fanRigWith(t, cp, primary, overrides), alternate
}

func listedStreamID(t *testing.T, r *rig) int {
	t.Helper()
	ch := listedChannel(t, r)
	id, _ := ch["stream_id"].(float64)
	return int(id)
}

// readAligned reads n packets and checks only their alignment: across a
// switch the two upstreams' packet indices do not continue one another, so
// packetRun's contiguity check does not apply here.
func readAligned(t *testing.T, body io.Reader, packets int) []byte {
	t.Helper()
	got := make([]byte, packets*buffer.TSPacketSize)
	if _, err := io.ReadFull(body, got); err != nil {
		t.Fatalf("reading %d packets: %v", packets, err)
	}
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the client received bytes that are not whole TS packets: %s", problem)
	}
	return got
}

// The e2e dead-air spec's claim, end to end at the relay: the client
// survives the failover -- still attached, still fed -- and the list shows
// the alternate. CONNECTION_TIMEOUT and HEALTH_CHECK_INTERVAL come off the
// wire compressed; the switch itself is row 2's, pinned in package channel.
func TestAFailoverKeepsTheClientAttachedAndFed(t *testing.T) {
	r, alternate := failoverRig(t,
		relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3},
		map[string]any{"CONNECTION_TIMEOUT": 0.3, "HEALTH_CHECK_INTERVAL": 0.05})
	response := r.tuneAs(t, "c-failover", "client-a")
	defer func() { _ = response.Body.Close() }()

	before := packetRun(t, "the client before the dead air", response.Body, 1000)
	_ = before
	if got := listedStreamID(t, r); got != 1 {
		t.Fatalf("stream_id = %d before the failover, want 1", got)
	}

	// The rest of the primary's bytes, then the alternate's: the read spans
	// the switch, and every packet is still whole.
	readAligned(t, response.Body, 3000)
	waitFor(t, "the list to show the alternate", 10*time.Second, func() bool { return listedStreamID(t, r) == 2 })
	if n := alternate.Requests(); n != 1 {
		t.Fatalf("the alternate saw %d requests, want 1", n)
	}
	ch := listedChannel(t, r)
	if ch["client_count"] != 1.0 {
		t.Fatalf("client_count = %v after the failover, want 1: the client was dropped", ch["client_count"])
	}
	if ch["healthy"] != true {
		t.Fatalf("healthy = %v after the failover, want true: data is flowing again", ch["healthy"])
	}
	switches := r.Control.EventsOfType("stream_switch")
	waitFor(t, "the stream_switch event to reach the control plane", 5*time.Second, func() bool {
		switches = r.Control.EventsOfType("stream_switch")
		return len(switches) == 1
	})
	if switches[0].ChannelID != "c-failover" || switches[0].StreamID == nil || *switches[0].StreamID != 2 {
		t.Fatalf("stream_switch = %+v, want channel c-failover and stream 2", switches[0])
	}
}

// waitFor polls cond every 20 ms until it holds or the deadline passes.
func waitFor(t *testing.T, what string, timeout time.Duration, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out after %s waiting for %s", timeout, what)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

// THE DEGRADED FALLBACK (input/manager.py:2107-2112, CLAUDE.md § Operationally):
// with the control plane answering 503, a failover falls back to the
// candidate list the initial answer carried -- unenforced -- after spending
// the client's own retry: two next-source attempts, then the cached
// alternate. And once the control plane answers again, the next failover
// goes through it and raises channel_error with reason degraded_failover,
// once (:2183-2192).
//
// The primary and the first alternate each end after two chunks, so each
// is exhausted after three quick EOFs; the third candidate flows.
func TestAFailoverFallsBackToTheCachedCandidatesWhenTheControlPlaneIsDown(t *testing.T) {
	second := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), StopAfterBytes: rigChunkBytes * 2})
	t.Cleanup(second.Close)
	third := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100)})
	t.Cleanup(third.Close)
	cp := relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{
		{StreamID: 2, URL: second.URL()},
		{StreamID: 3, URL: third.URL()},
	}}
	r := fanRigWith(t, cp, relaytest.Config{StopAfterBytes: rigChunkBytes * 2}, nil)

	response := r.tuneAs(t, "c-degraded", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-degraded", 1)

	// The outage begins after the tune.
	r.Control.SetStatus(http.StatusServiceUnavailable)

	waitFor(t, "the switch to the cached second stream", 15*time.Second, func() bool { return second.Requests() >= 1 })
	calls := r.Control.RequestsTo("/next-source")
	if len(calls) != 3 {
		t.Fatalf("the control plane saw %d next-source calls, want 3: the tune and the failover's two attempts before the cache was used", len(calls))
	}
	if !strings.Contains(string(calls[1].Body), `"reason":"failover"`) || !strings.Contains(string(calls[1].Body), `"exclude_stream_ids":[1]`) {
		t.Fatalf("the failover call was %s, want reason failover excluding stream 1", calls[1].Body)
	}
	if got := listedStreamID(t, r); got != 2 {
		t.Fatalf("stream_id = %d, want the cached alternate 2", got)
	}

	// Django is back; the second stream exhausts too; the third comes from
	// the control plane, with the cached list now excluded correctly.
	r.Control.SetStatus(0)
	waitFor(t, "the switch to the third stream", 15*time.Second, func() bool { return third.Requests() >= 1 })
	calls = r.Control.RequestsTo("/next-source")
	last := calls[len(calls)-1]
	if !strings.Contains(string(last.Body), `"exclude_stream_ids":[1,2]`) {
		t.Fatalf("the second failover excluded %s, want [1,2]", last.Body)
	}
	waitFor(t, "the degraded_failover event", 5*time.Second, func() bool {
		for _, e := range r.Control.EventsOfType("channel_error") {
			if e.Details["reason"] == "degraded_failover" {
				return true
			}
		}
		return false
	})
	degraded := 0
	for _, e := range r.Control.EventsOfType("channel_error") {
		if e.Details["reason"] == "degraded_failover" {
			degraded++
		}
	}
	if degraded != 1 {
		t.Fatalf("degraded_failover raised %d times, want exactly once on recovery", degraded)
	}
	readAligned(t, response.Body, 200)
}

// A REFUSAL NEVER DEGRADES (spec § Error handling per hop; input/manager.py:
// 2095-2106): a 403 -- a SECRET_KEY mismatch between roles -- fails the
// switch loudly, the cached alternate is never touched, and the channel ends
// in error rather than streaming a candidate nobody reserved.
func TestARefusedFailoverNeverUsesTheCache(t *testing.T) {
	r, alternate := failoverRig(t, relaytest.Config{StopAfterBytes: rigChunkBytes * 2}, nil)
	response := r.tuneAs(t, "c-refused", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-refused", 1)
	ch := r.Manager.Get("c-refused")

	r.Control.SetStatus(http.StatusForbidden)
	select {
	case <-ch.Done():
	case <-time.After(15 * time.Second):
		t.Fatal("the channel did not end after a refused failover")
	}
	// The channel ended in error -- run()'s own exhaustion error, as Python's
	// finally block writes it; the refusal itself is logged at the switch
	// (input/manager.py:2101-2105) and is not what the channel records -- and
	// the client's release then moved it to stopping.
	var exhausted *channel.ErrSourcesExhausted
	if !errors.As(ch.Err(), &exhausted) {
		t.Fatalf("Err() = %v (state %q), want the exhaustion error", ch.Err(), ch.State())
	}
	if n := alternate.Requests(); n != 0 {
		t.Fatalf("the alternate saw %d requests: a refusal degraded onto the cache", n)
	}
	calls := r.Control.RequestsTo("/next-source")
	if len(calls) != 2 {
		t.Fatalf("the control plane saw %d next-source calls, want 2: a 403 is not retried", len(calls))
	}
}

// THE TIMING SHAPE of the fallback: "after up to ~14 s per control-plane
// call" (CLAUDE.md § Operationally) is two attempts of (ConnectTimeout,
// ReadTimeout) plus the retry delay, spent before the cache is read. Here the
// client's transport times out at 300 ms and the control plane answers after
// 400 ms, so each attempt is a transport failure; the fake's own request log
// shows the second attempt at least 400 ms after the first (timeout plus the
// 100 ms retry delay), and the alternate is not contacted until after both.
// A client that skipped the retry, or one that read the cache before its
// first attempt failed, reddens this.
func TestTheDegradedFallbackSpendsTheClientsRetryBudgetFirst(t *testing.T) {
	alternate := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100)})
	t.Cleanup(alternate.Close)
	cp := relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}
	cp.Settings = rigSettings(nil)
	slow := control.NewHTTPClient()
	slow.Timeout = 300 * time.Millisecond
	r := newRigWithClient(t, cp, relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), StopAfterBytes: rigChunkBytes * 2}, slow)

	response := r.tuneAs(t, "c-budget", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-budget", 1)
	r.Control.SetDelay(400 * time.Millisecond)

	waitFor(t, "the cached alternate to be contacted", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
	calls := r.Control.RequestsTo("/next-source")
	if len(calls) != 3 {
		t.Fatalf("the control plane saw %d next-source calls, want 3: the tune and two failover attempts", len(calls))
	}
	first, second := calls[1].At, calls[2].At
	if gap := second.Sub(first); gap < 400*time.Millisecond {
		t.Fatalf("the second attempt came %s after the first, under the 300 ms timeout plus the 100 ms retry delay", gap)
	}
	if gap := second.Sub(first); gap > 3*time.Second {
		t.Fatalf("the second attempt came %s after the first: the budget was not the client's", gap)
	}
}

// The provider slot goes back when the channel's source goroutine returns,
// with the ids of the stream it was playing THEN: after a failover, the
// alternate's. Observed at the fake, which records the release body.
func TestTheSlotIsReleasedWithTheCurrentStreamWhenTheChannelEnds(t *testing.T) {
	r, alternate := failoverRig(t, relaytest.Config{StopAfterBytes: rigChunkBytes * 2}, nil)
	response := r.tuneAs(t, "c-release", "client-a")
	waitFor(t, "the switch to the alternate", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
	_ = response.Body.Close()
	waitFor(t, "the release", 10*time.Second, func() bool { return len(r.Control.RequestsTo("/release")) == 1 })
	release := r.Control.RequestsTo("/release")[0]
	var body map[string]any
	if err := json.Unmarshal(release.Body, &body); err != nil {
		t.Fatalf("decoding the release body: %v", err)
	}
	if body["stream_id"] != 2.0 || body["m3u_profile_id"] != 1.0 {
		t.Fatalf("release body = %s, want stream 2 on profile 1", release.Body)
	}
	if _, present := body["channel_pk"]; !present || body["channel_pk"] != nil {
		t.Fatalf("release body = %s, want channel_pk present and null", release.Body)
	}
	if release.Header.Get(control.HeaderInternalRequest) == "" {
		t.Fatal("the release was not signed")
	}
}
```

### Appendix Y — `relay/httpapi/redirect.go`

**`relay/httpapi/redirect.go`**

```go
package httpapi

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The Redirect stream-profile architecture (views.py:468-547): no bytes
// through the relay and no failover after connect. The provider URL is
// probed, the cached alternates are tried in turn when it fails, the
// reserved slot is given back, and the client is handed the URL -- the one
// that VALIDATED, not wherever the probe was redirected to, because
// validate_stream_url returns the URL it was given (url_utils.py:183, :250).

// probeTimeout is the (5, 5) pair views.py:480 and :503 pass
// validate_stream_url: connect 5s, read 5s.
const probeTimeout = 5 * time.Second

// probeRedirectLimit is requests' DEFAULT_REDIRECT_LIMIT (30), which
// allow_redirects=True on the probe (url_utils.py:174, :190) is bounded by;
// past it requests raises TooManyRedirects and the URL is invalid.
const probeRedirectLimit = 30

// probeChunk is the first-chunk read of the GET probe, url_utils.py:196's
// iter_content(chunk_size=188*10).
const probeChunk = buffer.TSPacketSize * 10

// ErrRedirectValidationFailed is "All available redirect URLs failed
// validation" (views.py:542-547), answered 502 with a JSON body.
var ErrRedirectValidationFailed = errors.New("httpapi: every redirect candidate failed validation")

// redirectAnswer is the tune's outcome on a Redirect channel: not a channel
// at all, so it travels as an error out of the start function and the
// handler writes it. Status is 302 for an HTTP URL (HttpResponseRedirect)
// and 301 for rtsp/rtp/udp, which Django's redirect class refuses and
// views.py:533-538 builds by hand.
type redirectAnswer struct {
	Location string
	Status   int
}

func (r *redirectAnswer) Error() string {
	return fmt.Sprintf("httpapi: redirect the client with %d", r.Status)
}

// NewProbeClient is the client validate_stream_url's port probes with when
// StreamDeps.Probe is nil: requests' defaults, redirects followed up to
// thirty, one connection per probe.
func NewProbeClient() *http.Client {
	return &http.Client{
		Transport: &http.Transport{
			DialContext:           (&net.Dialer{Timeout: probeTimeout}).DialContext,
			ResponseHeaderTimeout: probeTimeout,
			DisableKeepAlives:     true,
		},
		CheckRedirect: func(_ *http.Request, via []*http.Request) error {
			if len(via) >= probeRedirectLimit {
				return errors.New("too many redirects")
			}
			return nil
		},
	}
}

// redirectTune is the views.py:468-547 branch. It returns a *redirectAnswer
// when a candidate validated, ErrRedirectValidationFailed when none did, and
// in either case has released the slot the initial answer reserved.
func redirectTune(ctx context.Context, deps tuneDeps, id string, answer *control.NextSourceAnswer, defaultUserAgent string) error {
	probe := deps.probe
	if probe == nil {
		probe = NewProbeClient()
	}
	source := answer.Source

	// Python passes the answer's user_agent RAW here, not the defaulted one
	// StreamManager would use (views.py:479-481 versus input/manager.py:73), so
	// a blank agent sends no User-Agent header at all.
	_ = defaultUserAgent
	valid, message := validateStreamURL(ctx, probe, source.URL, source.UserAgent)
	final := source.URL
	deps.log.Info("validated the redirect URL", "channel", id, "valid", valid, "result", message)
	if !valid {
		deps.log.Warn("the primary stream URL failed validation; trying the cached alternates", "channel", id, "result", message)
		tried := map[int]bool{source.StreamID: true}
		for i := range answer.Alternates {
			alt := &answer.Alternates[i]
			if tried[alt.StreamID] {
				continue
			}
			tried[alt.StreamID] = true
			deps.log.Info("trying an alternate stream", "channel", id, "stream", alt.StreamID)
			if valid, message = validateStreamURL(ctx, probe, alt.URL, alt.UserAgent); valid {
				final = alt.URL
				deps.log.Info("an alternate stream validated", "channel", id, "stream", alt.StreamID)
				break
			}
			deps.log.Warn("an alternate stream failed validation", "channel", id, "stream", alt.StreamID, "result", message)
		}
	}

	// views.py:516-525: the slot the initial answer reserved goes back
	// before the client is sent to the provider, because nothing here will
	// ever stream through it.
	if source.SlotReserved {
		streamID, profileID := source.StreamID, source.M3UProfileID
		released, err := deps.control.Release(ctx, id, control.ReleaseRequest{StreamID: &streamID, M3UProfileID: &profileID})
		switch {
		case err != nil:
			deps.log.Warn("could not release the slot before redirecting", "channel", id, "error", redact.Error(err))
		case !released:
			deps.log.Warn("failed to release the stream before redirecting", "channel", id)
		}
	}

	if !valid {
		return ErrRedirectValidationFailed
	}
	status := http.StatusFound
	lower := strings.ToLower(final)
	if strings.HasPrefix(lower, "rtsp://") || strings.HasPrefix(lower, "rtp://") || strings.HasPrefix(lower, "udp://") {
		status = http.StatusMovedPermanently
	}
	return &redirectAnswer{Location: final, Status: status}
}

// validateStreamURL is url_utils.py:138-262's validate_stream_url: a
// non-HTTP scheme is valid unprobed; a HEAD that answers 2xx is valid; a GET
// that answers 2xx and yields at least one byte is valid; anything else is
// not, with the reason. The Content-Type is never a reason to refuse
// (:234-250, "always consider the stream valid if we got data").
func validateStreamURL(ctx context.Context, probe *http.Client, rawURL, userAgent string) (bool, string) {
	lower := strings.ToLower(rawURL)
	if strings.HasPrefix(lower, "udp://") || strings.HasPrefix(lower, "rtp://") || strings.HasPrefix(lower, "rtsp://") {
		return true, "Non-HTTP protocol (UDP/RTP/RTSP) - validation skipped"
	}

	request := func(method string) (*http.Response, error) {
		ctx, cancel := context.WithTimeout(ctx, probeTimeout)
		req, err := http.NewRequestWithContext(ctx, method, rawURL, nil)
		if err != nil {
			cancel()
			return nil, err
		}
		// requests sends the header only when it has a value; Go's client
		// sends its own default unless told to send none.
		if userAgent != "" {
			req.Header.Set("User-Agent", userAgent)
		} else {
			req.Header["User-Agent"] = nil
		}
		req.Header.Set("Connection", "close")
		response, err := probe.Do(req)
		if err != nil {
			cancel()
			return nil, err
		}
		// The read below runs under the same deadline; the body's Close
		// releases it.
		body := response.Body
		response.Body = closerFunc{Reader: body, close: func() error { cancel(); return body.Close() }}
		return response, nil
	}

	// HEAD first (:171-178); any error means "HEAD not supported", not
	// "invalid" (:175-178).
	if head, err := request(http.MethodHead); err == nil {
		status := head.StatusCode
		_ = head.Body.Close()
		if status >= 200 && status < 300 {
			return true, "Valid (HEAD request)"
		}
	}

	get, err := request(http.MethodGet)
	if err != nil {
		var netErr net.Error
		switch {
		case errors.As(err, &netErr) && netErr.Timeout():
			return false, "Timeout connecting to stream"
		case strings.Contains(err.Error(), "too many redirects"):
			return false, "Too many redirects"
		}
		return false, "Request error: " + redact.Error(err).Error()
	}
	defer func() { _ = get.Body.Close() }()
	if get.StatusCode < 200 || get.StatusCode >= 300 {
		return false, fmt.Sprintf("Invalid HTTP status: %d", get.StatusCode)
	}
	first := make([]byte, probeChunk)
	n, readErr := io.ReadFull(get.Body, first)
	switch {
	case n > 0:
		return true, fmt.Sprintf("Valid (GET request, received %d bytes)", n)
	case readErr != nil && !errors.Is(readErr, io.EOF) && !errors.Is(readErr, io.ErrUnexpectedEOF):
		var netErr net.Error
		if errors.As(readErr, &netErr) && netErr.Timeout() {
			return false, "Timeout connecting to stream"
		}
		return false, "Request error: " + redact.Error(readErr).Error()
	}
	return false, "Empty response from server"
}

type closerFunc struct {
	io.Reader
	close func() error
}

func (c closerFunc) Close() error { return c.close() }
```

### Appendix Z — `relay/httpapi/redirect_test.go`

**`relay/httpapi/redirect_test.go`**

```go
package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// redirectRig is a rig whose control plane names the Redirect profile.
func redirectRig(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config) *rig {
	t.Helper()
	cp.Kind = control.KindRedirect
	return fanRigWith(t, cp, up, nil)
}

// tuneNoFollow is rig.tune with redirects NOT followed, so a 302 is the
// answer rather than a fetch of the provider.
func (r *rig) tuneNoFollow(t *testing.T, path string, header http.Header) *http.Response {
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
	client := r.Relay.Client()
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := client.Do(request)
	if err != nil {
		t.Fatalf("tuning: %v", err)
	}
	return response
}

// THE REDIRECT ARCHITECTURE (views.py:468-540; e2e stream-profiles.spec.ts):
// the client is handed the provider URL -- the one validated, not wherever
// the probe was sent -- with a 302, no bytes traverse the relay (the
// provider sees the HEAD probe and nothing else), no channel exists for the
// list endpoint to render, and the slot the tune reserved is released
// before the answer.
func TestARedirectProfileHandsTheClientTheProviderURLAndFetchesNothing(t *testing.T) {
	r := redirectRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect", nil)
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusFound {
		t.Fatalf("a Redirect channel answered %d, want 302", response.StatusCode)
	}
	if got := response.Header.Get("Location"); got != r.Upstream.URL() {
		t.Fatalf("Location = %q, want the provider URL %q", got, r.Upstream.URL())
	}
	if methods := r.Upstream.Methods(); len(methods) != 1 || methods[0] != http.MethodHead {
		t.Fatalf("the provider saw %v, want exactly one HEAD probe and no GET", methods)
	}
	if r.Manager.Get("c-redirect") != nil {
		t.Fatal("a Redirect tune left a channel in the manager")
	}
	status, body := r.listChannels(t, "")
	if status != http.StatusOK || !strings.Contains(string(body), `"count":0`) {
		t.Fatalf("the list endpoint answered %d %s after a Redirect tune, want an empty list: nothing was initialised", status, body)
	}
	releases := r.Control.RequestsTo("/release")
	if len(releases) != 1 || !strings.Contains(string(releases[0].Body), `"stream_id":1`) {
		t.Fatalf("release calls = %+v, want one for stream 1 before the redirect", releases)
	}
}

// When the primary fails validation the cached alternates are tried in turn
// (views.py:483-514): HEAD then GET on the primary, both 404, then the
// alternate validates and is the Location.
func TestARedirectFallsThroughToACachedAlternateWhenTheProbeFails(t *testing.T) {
	alternate := relaytest.NewUpstream(relaytest.Config{})
	t.Cleanup(alternate.Close)
	r := redirectRig(t, relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}, relaytest.Config{Status: 404})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-alt", nil)
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusFound {
		t.Fatalf("answered %d, want 302", response.StatusCode)
	}
	if got := response.Header.Get("Location"); got != alternate.URL() {
		t.Fatalf("Location = %q, want the alternate %q", got, alternate.URL())
	}
	if methods := r.Upstream.Methods(); len(methods) != 2 || methods[0] != http.MethodHead || methods[1] != http.MethodGet {
		t.Fatalf("the primary saw %v, want a HEAD then a GET before it was given up on", methods)
	}
}

// Every candidate failing validation is a 502 with views.py:545-547's JSON
// body, and the slot is still released.
func TestARedirectWhoseEveryCandidateFailsValidationIs502(t *testing.T) {
	alternate := relaytest.NewUpstream(relaytest.Config{Status: 500})
	t.Cleanup(alternate.Close)
	r := redirectRig(t, relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}, relaytest.Config{Status: 404})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-none", nil)
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("answered %d, want 502", response.StatusCode)
	}
	body, _ := io.ReadAll(response.Body)
	var decoded map[string]any
	if err := json.Unmarshal(body, &decoded); err != nil || decoded["error"] != "All available streams failed validation" {
		t.Fatalf("body = %s, want {\"error\": \"All available streams failed validation\"}", body)
	}
	if len(r.Control.RequestsTo("/release")) != 1 {
		t.Fatal("the slot was not released after a failed validation")
	}
}

// THE INTERNAL-PRINCIPAL OVERRIDE (views.py:445-467, Phase 1 PR 5): a
// request carrying a valid X-Dispatcharr-Internal on a Redirect channel is
// served through the Proxy path -- a 200 with the provider's bytes -- so the
// header is never re-sent to a provider by a 302.
func TestAnInternalPrincipalOnARedirectChannelIsServedThroughProxy(t *testing.T) {
	r := redirectRig(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-dvr", http.Header{
		control.HeaderInternal: []string{control.InternalPrincipalToken(testSecret)},
	})
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusOK {
		t.Fatalf("an internal principal on a Redirect channel answered %d, want 200 through Proxy", response.StatusCode)
	}
	if got := response.Header.Get("Content-Type"); got != "video/mp2t" {
		t.Fatalf("Content-Type = %q", got)
	}
	packetRun(t, "the DVR", response.Body, 200)
	if methods := r.Upstream.Methods(); len(methods) != 1 || methods[0] != http.MethodGet {
		t.Fatalf("the provider saw %v, want one GET and no probe", methods)
	}
	// And a forged marker does not: the token is checked, not the header's
	// presence.
	forged := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-forged", http.Header{control.HeaderInternal: []string{"not-the-token"}})
	defer func() { _ = forged.Body.Close() }()
	if forged.StatusCode != http.StatusFound {
		t.Fatalf("a forged internal marker answered %d, want the 302 an ordinary client gets", forged.StatusCode)
	}
}

// A non-HTTP provider URL is not probed (url_utils.py:154-157) and, because
// HttpResponseRedirect refuses the scheme, is answered with a hand-built 301
// (views.py:533-538).
func TestANonHTTPRedirectTargetIsNotProbedAndAnswers301(t *testing.T) {
	r := redirectRig(t, relaytest.ControlPlaneConfig{SourceURL: "rtsp://provider.invalid:554/live/1"}, relaytest.Config{})
	response := r.tuneNoFollow(t, "/proxy/ts/stream/c-redirect-rtsp", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusMovedPermanently {
		t.Fatalf("answered %d, want 301", response.StatusCode)
	}
	if got := response.Header.Get("Location"); got != "rtsp://provider.invalid:554/live/1" {
		t.Fatalf("Location = %q", got)
	}
	if n := r.Upstream.Requests(); n != 0 {
		t.Fatalf("the rig's upstream saw %d requests: an rtsp URL was probed over HTTP", n)
	}
}
```

### Appendix AA — `relay/httpapi/packets.go`

**`relay/httpapi/packets.go`**

```go
package httpapi

import "github.com/D10Scot/Dispatcharr/relay/buffer"

// signalPacket is apps/proxy/live_proxy/utils.py:71-98's create_ts_packet:
// one 188-byte packet on the null PID (0x1FFF) -- sync byte, PID high bits
// 0x1F, PID low bits 0xFF, and byte 3 left ZERO, which is what Python
// writes, an adaptation-field-control value of "reserved" that every player
// this project has met discards as a null packet -- with an optional message
// in the payload from byte 4, cut at 180. The keepalive and the error packet
// are the same packet with and without a message; the error PID is the same
// PID (:87-92 sets both branches to 0x1FFF).
func signalPacket(message string) []byte {
	packet := make([]byte, buffer.TSPacketSize)
	packet[0] = 0x47
	packet[1] = 0x1F
	packet[2] = 0xFF
	if message != "" {
		copy(packet[4:4+180], message)
	}
	return packet
}
```

### Appendix AB — `relay/httpapi/keepalive_test.go`

**`relay/httpapi/keepalive_test.go`**

```go
package httpapi

import (
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// nullPID is the PID of the keepalive and error packets (utils.py:87-92).
const nullPID = 0x1FFF

func pidOf(packet []byte) int { return int(packet[1]&0x1f)<<8 | int(packet[2]) }

// packetsUntil reads whole packets until `stop` returns true for one, the
// body ends, or the deadline passes -- at which point the body is closed so
// the reader returns -- and hands back the packets with the time each
// arrived. The reading goroutine owns the slices until it is done, so the
// race detector has nothing to say.
func packetsUntil(t *testing.T, body io.ReadCloser, deadline time.Duration, stop func([]byte) bool) ([][]byte, []time.Time) {
	t.Helper()
	type result struct {
		packets [][]byte
		at      []time.Time
	}
	done := make(chan result, 1)
	go func() {
		var out result
		defer func() { done <- out }()
		for {
			packet := make([]byte, buffer.TSPacketSize)
			if _, err := io.ReadFull(body, packet); err != nil {
				return
			}
			out.packets = append(out.packets, packet)
			out.at = append(out.at, time.Now())
			if stop(packet) {
				return
			}
		}
	}()
	select {
	case r := <-done:
		return r.packets, r.at
	case <-time.After(deadline):
		_ = body.Close()
		r := <-done
		return r.packets, r.at
	}
}

// KEEPALIVES ARE GATED ON THE HEALTH FLAG (output/ts/generator.py:387-405,
// :542-551): a client waiting at the buffer head receives null packets only
// once the channel is UNHEALTHY, and never while it is merely quiet. The
// primary goes silent after three chunks with CONNECTION_TIMEOUT at 5s, so
// the channel stays healthy for five seconds of silence -- in which no null
// packet may arrive -- and unhealthy after, at which point they must, at
// KEEPALIVE_INTERVAL. The control plane is slowed so the failover does not
// end the wait early.
func TestAnUnhealthyChannelSendsKeepalivesAtTheBufferHeadAndAHealthyOneDoesNot(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3}, map[string]any{
		"CONNECTION_TIMEOUT": 5, "HEALTH_CHECK_INTERVAL": 0.05, "KEEPALIVE_INTERVAL": 0.05,
	})
	r.Control.SetDelay(4 * time.Second)
	response := r.tuneAs(t, "c-keepalive", "client-a")
	defer func() { _ = response.Body.Close() }()

	// Everything the primary sends, up to the last asset packet before
	// the silence, plus whatever follows within eight seconds.
	packets, at := packetsUntil(t, response.Body, 8*time.Second, func([]byte) bool { return false })
	var lastAsset, firstNull time.Time
	nulls := 0
	for i, p := range packets {
		if pidOf(p) == nullPID {
			nulls++
			if firstNull.IsZero() {
				firstNull = at[i]
			}
			continue
		}
		if !firstNull.IsZero() {
			// A resumed asset packet after keepalives is the reconnect the
			// failed failover falls back to; fine, and not this test's.
			break
		}
		lastAsset = at[i]
	}
	if nulls == 0 {
		t.Fatal("no keepalive packet arrived on an unhealthy channel")
	}
	if quiet := firstNull.Sub(lastAsset); quiet < 5*time.Second {
		t.Fatalf("the first keepalive came %s after the last asset packet, while the channel was still HEALTHY (CONNECTION_TIMEOUT 5s): the health gate is not applied", quiet)
	}
	if nulls < 5 {
		t.Fatalf("only %d keepalives in the window; at a 50 ms interval there should be many", nulls)
	}
	for _, p := range packets {
		if pidOf(p) == nullPID && (p[0] != 0x47 || p[1] != 0x1F || p[2] != 0xFF || p[3] != 0x00) {
			t.Fatalf("a keepalive packet is not create_ts_packet's: % x", p[:4])
		}
	}
}

// THE KEEPALIVE CAP (output/ts/generator.py:371-380): keepalives refresh the
// timer _is_timeout reads, so a permanently failed stream would hold a client
// forever; MAX_KEEPALIVE_DURATION ends it. Compressed to half a second, with
// the control plane too slow to ever switch: the response ends, and the
// client count goes to zero.
func TestAClientIsDroppedOnceTheKeepaliveCapIsReached(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3}, map[string]any{
		"CONNECTION_TIMEOUT": 0.3, "HEALTH_CHECK_INTERVAL": 0.05, "KEEPALIVE_INTERVAL": 0.05, "MAX_KEEPALIVE_DURATION": 0.5,
	})
	r.Control.SetDelay(6 * time.Second)
	response := r.tuneAs(t, "c-cap", "client-a")
	defer func() { _ = response.Body.Close() }()

	started := time.Now()
	packets, _ := packetsUntil(t, response.Body, 15*time.Second, func([]byte) bool { return false })
	if elapsed := time.Since(started); elapsed > 12*time.Second {
		t.Fatalf("the response did not end within %s: the keepalive cap did not drop the client", elapsed)
	}
	nulls := 0
	for _, p := range packets {
		if pidOf(p) == nullPID {
			nulls++
		}
	}
	if nulls == 0 {
		t.Fatal("the client was dropped without any keepalive: something other than the cap ended it")
	}
	waitFor(t, "the client count to reach zero", 5*time.Second, func() bool {
		ch := r.Manager.Get("c-cap")
		return ch == nil || ch.Clients() == 0
	})
}

// `healthy` on GET /proxy/relay/channels (channel_status.py:527-529): true
// while data flows, false once the monitor has seen none for the threshold,
// and present on every channel this relay holds. The 2c-3 golden's
// NOT_SERVED_YET entry for it goes with this test.
func TestHealthyOnTheListPayloadFollowsTheHealthMonitor(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4, DeadAirAfterBytes: rigChunkBytes * 3}, map[string]any{
		"CONNECTION_TIMEOUT": 0.3, "HEALTH_CHECK_INTERVAL": 0.05,
	})
	r.Control.SetDelay(4 * time.Second)
	response := r.tuneAs(t, "c-healthy", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-healthy", 1)
	if got := listedChannel(t, r)["healthy"]; got != true {
		t.Fatalf("healthy = %v while data flows, want true", got)
	}
	waitFor(t, "healthy to go false on dead air", 5*time.Second, func() bool {
		return listedChannel(t, r)["healthy"] == false
	})
	status, _ := r.listChannels(t, "")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d", status)
	}
}

// THE ERROR PACKET (output/ts/generator.py:235-239; parity-matrix row 3's
// Python pin reads it): a client that received nothing when its channel
// ended in error gets exactly one 188-byte packet on the null PID carrying
// "Error: <message>", with the message run()'s finally block would have
// written -- and then the body ends. Amendment A2.5 recorded 2c-2 as
// answering with zero bytes here.
func TestAClientWithNoBytesGetsAnErrorPacketWhenEverySourceFails(t *testing.T) {
	r := fanRig(t, relaytest.Config{Status: 404}, nil)
	response := r.tuneAs(t, "c-error-packet", "client-a")
	defer func() { _ = response.Body.Close() }()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the body: %v", err)
	}
	if len(body) != buffer.TSPacketSize {
		t.Fatalf("the body is %d bytes, want exactly one error packet", len(body))
	}
	if pidOf(body) != nullPID || body[0] != 0x47 {
		t.Fatalf("the packet is not on the null PID: % x", body[:4])
	}
	want := "Error: All 1 stream options failed"
	if got := string(body[4 : 4+len(want)]); got != want {
		t.Fatalf("the packet carries %q, want %q", got, want)
	}
	if r.Upstream.Requests() != 3 {
		t.Fatalf("the provider saw %d requests, want 3", r.Upstream.Requests())
	}
}
```

### Appendix AC — `relay/httpapi/golden_test.go`

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
	healthy := true

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
				Healthy:        &healthy,
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
	// Asserted on the LIVE row, for the same reason as owner above: the key-set
	// check just above would stay green whether output_profile_id rendered as
	// null or as a bare integer -- both carry the key -- so a *Client.OutputProfileID
	// that lost its pointer and became an int would pass undetected.
	if got := liveRow["output_profile_id"]; got != nil {
		t.Fatalf("the live client reports output_profile_id %v, want null: 2c-3 serves "+
			"no Output Profile yet, so every attached client's OutputProfileID is nil", got)
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

**And `relay/httpapi/testdata/channels_clients_all.json`, regenerated by Django (Task 5 Step 1)** — `d92b33be`'s line with `"healthy":true` inserted between `"avg_bitrate":"2.67 Mbps"` and `"video_codec":"h264"` on channel 1, in Django's own compact spelling:

```json
{"channels":[{"channel_id":"11111111-1111-4111-8111-111111111111","state":"active","url":"http://provider.invalid/live/sub/pw/41.ts","stream_profile":"1","owner":null,"buffer_index":120,"client_count":2,"uptime":30.0,"started_at":1789000000.5,"channel_name":"BBC One HD","m3u_profile_id":3,"stream_id":41,"stream_name":"BBC One HD (UK)","total_bytes":9999888,"avg_bitrate_kbps":2665.3034666666667,"avg_bitrate":"2.67 Mbps","healthy":true,"video_codec":"h264","resolution":"1920x1080","source_fps":25.0,"ffmpeg_speed":1.02,"audio_codec":"aac","audio_channels":"stereo","stream_type":"mpegts","clients":[{"client_id":"client_1789000000000_1234","user_agent":"VLC/3.0.20","output_format":"mpegts","output_profile_id":7,"ip_address":"198.51.100.4","connected_at":1789000001.25,"user_id":"7"},{"client_id":"client_1789000000000_5678","user_agent":null,"output_format":"mpegts","output_profile_id":null}]},{"channel_id":"22222222-2222-4222-8222-222222222222","state":"stopped","url":"","stream_profile":"0","owner":null,"buffer_index":0,"client_count":0,"uptime":0.0,"started_at":1789000100.0,"clients":[]}],"count":2}
```

### Appendix AF — `relay/channel/failover_test.go`

**`relay/channel/failover_test.go`**

```go
package channel

import (
	"context"
	"errors"
	"io"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// fakeResolver hands back a scripted list of answers, then ErrNoAlternate,
// recording every request and when it was made. A nil answers list is a
// resolver with nothing to offer.
type fakeResolver struct {
	mu       sync.Mutex
	answers  []Resolved
	err      error
	reqs     []NextRequest
	calledAt []time.Time
	// block, when set, holds every call until it is closed: for a test
	// that needs the channel to STAY in its pre-switch state.
	block chan struct{}
}

func (r *fakeResolver) Next(ctx context.Context, req NextRequest) (Resolved, error) {
	r.mu.Lock()
	r.reqs = append(r.reqs, req)
	r.calledAt = append(r.calledAt, time.Now())
	block := r.block
	r.mu.Unlock()
	if block != nil {
		select {
		case <-block:
		case <-ctx.Done():
			return Resolved{}, ctx.Err()
		}
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.err != nil {
		return Resolved{}, r.err
	}
	if len(r.answers) == 0 {
		return Resolved{}, ErrNoAlternate
	}
	next := r.answers[0]
	r.answers = r.answers[1:]
	return next, nil
}

func (r *fakeResolver) requests() []NextRequest {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]NextRequest(nil), r.reqs...)
}

func (r *fakeResolver) firstCallAt() time.Time {
	r.mu.Lock()
	defer r.mu.Unlock()
	if len(r.calledAt) == 0 {
		return time.Time{}
	}
	return r.calledAt[0]
}

// eventLog is an EventSink that keeps everything, with the wall clock each
// event arrived at.
type eventLog struct {
	mu     sync.Mutex
	events []Event
	at     []time.Time
}

func (l *eventLog) Emit(e Event) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.events = append(l.events, e)
	l.at = append(l.at, time.Now())
}

func (l *eventLog) of(typ string) []Event {
	l.mu.Lock()
	defer l.mu.Unlock()
	var out []Event
	for _, e := range l.events {
		if e.Type == typ {
			out = append(out, e)
		}
	}
	return out
}

func (l *eventLog) all() []Event {
	l.mu.Lock()
	defer l.mu.Unlock()
	return append([]Event(nil), l.events...)
}

// countingRuns wraps a source and counts its Runs -- the way a test tells
// that the source a resolver handed over is the one now producing bytes.
type countingRuns struct {
	inner Source
	runs  *int32Counter
}

func (s countingRuns) Run(ctx context.Context, sink io.Writer) error {
	s.runs.inc()
	return s.inner.Run(ctx, sink)
}

func (s countingRuns) attach(c *Channel) {
	if a, ok := s.inner.(attachable); ok {
		a.attach(c)
	}
}

// failingSource fails at connect time, every time, with a 404 -- Python's
// HTTPStreamReader getting a 404 and closing the pipe at once.
type failingSource struct{ runs *int32Counter }

func (s failingSource) Run(context.Context, io.Writer) error {
	s.runs.inc()
	return &ErrUpstreamStatus{Status: 404}
}

// flowingSource writes one synthetic packet every tick until cancelled.
type flowingSource struct {
	runs *int32Counter
	tick time.Duration
}

func (s flowingSource) Run(ctx context.Context, sink io.Writer) error {
	if s.runs != nil {
		s.runs.inc()
	}
	payload := relaytest.SyntheticTS(64, 0x200)
	tick := s.tick
	if tick <= 0 {
		tick = 5 * time.Millisecond
	}
	for i := 0; ; i = (i + 1) % 64 {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(tick):
		}
		if _, err := sink.Write(payload[i*buffer.TSPacketSize : (i+1)*buffer.TSPacketSize]); err != nil {
			return err
		}
	}
}

// deadAirSource writes `packets` whole packets and then produces nothing
// until cancelled -- a provider that stopped, not one that hung up. It
// records when it wrote its last byte, which is the moment the dead-air
// clock starts from.
type deadAirSource struct {
	packets   int
	lastWrite *timeCell
}

type timeCell struct {
	mu sync.Mutex
	t  time.Time
}

func (c *timeCell) set(t time.Time) { c.mu.Lock(); c.t = t; c.mu.Unlock() }
func (c *timeCell) get() time.Time  { c.mu.Lock(); defer c.mu.Unlock(); return c.t }

func (s deadAirSource) Run(ctx context.Context, sink io.Writer) error {
	payload := relaytest.SyntheticTS(s.packets, 0x100)
	if _, err := sink.Write(payload); err != nil {
		return err
	}
	s.lastWrite.set(time.Now())
	<-ctx.Done()
	return ctx.Err()
}

// attachWith is attachTranscode with a resolver: the shape every failover
// test needs.
func attachWith(t *testing.T, m *Manager, id string, source Source, tuning Tuning, resolver Resolver) (*Channel, func()) {
	t.Helper()
	ch, release, err := m.Attach(id, testClient("a"), func() (Started, error) {
		return Started{Source: source, Tuning: tuning, Info: SourceInfo{URL: "http://provider.invalid/primary.ts", StreamID: 1, M3UProfileID: 1, ChannelName: "Test Channel"}, Resolver: resolver}, nil
	})
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	return ch, release
}

// Global Constraint 8's ratchet for the bare literals of the retry loop and
// the health monitor: each names its Python line, and each is asserted
// against the number written there.
func TestTheFailoverLiteralsMatchPython(t *testing.T) {
	if retryBackoff(1) != 250*time.Millisecond || retryBackoff(2) != 500*time.Millisecond || retryBackoff(12) != 3*time.Second || retryBackoff(13) != 3*time.Second {
		t.Errorf("retryBackoff is not min(.25 * failures, 3) (input/manager.py:557): %s %s %s", retryBackoff(1), retryBackoff(2), retryBackoff(13))
	}
	if maxUnhealthyChecks != 3 {
		t.Errorf("maxUnhealthyChecks = %d, want 3 (input/manager.py:1556)", maxUnhealthyChecks)
	}
	if healthActionCooldown != 30*time.Second {
		t.Errorf("healthActionCooldown = %s, want 30s (input/manager.py:1557)", healthActionCooldown)
	}
	if stableReconnectAfter != 30*time.Second {
		t.Errorf("stableReconnectAfter = %s, want 30s (input/manager.py:1580's bare literal)", stableReconnectAfter)
	}
	if healthActionFor(30*time.Second) != actionReconnect || healthActionFor(29*time.Second) != actionSwitch {
		t.Error("healthActionFor: a stream stable for >= 30s reconnects in place, a younger one switches (input/manager.py:1576-1590)")
	}
}

// PARITY-MATRIX ROW 3's window half (input/manager.py:183-193): failures at
// t=0, 1700 and 3400 trip a 1800-second window even though the span is 3400,
// because each gap is under the window; a gap over it resets the count.
// Driven with an injected clock, so it costs nothing and cannot flake.
func TestTheRetryWindowResetsTheCounterAfterAnIdleGap(t *testing.T) {
	var now time.Time
	clock := func() time.Time { return now }
	base := time.Date(2026, 9, 14, 12, 0, 0, 0, time.UTC)
	counter := failureCounter{window: 1800 * time.Second, now: clock}

	now = base
	if got := counter.record(); got != 1 {
		t.Fatalf("first failure counted as %d", got)
	}
	now = base.Add(1700 * time.Second)
	if got := counter.record(); got != 2 {
		t.Fatalf("a failure 1700s later counted as %d, want 2 (inside the window)", got)
	}
	now = base.Add(3400 * time.Second)
	if got := counter.record(); got != 3 {
		t.Fatalf("a failure 1700s after that counted as %d, want 3: the span is 3400s but each gap is under 1800s", got)
	}
	now = base.Add(3400*time.Second + 1801*time.Second)
	if got := counter.record(); got != 1 {
		t.Fatalf("a failure 1801s after the last counted as %d, want 1: the gap exceeded the window and the counter resets", got)
	}
	counter.clear()
	if counter.count != 0 || !counter.last.IsZero() {
		t.Fatal("clear did not reset the counter and the last-failure time")
	}
}

// PARITY-MATRIX ROW 3: MAX_RETRIES (3) consecutive connection failures
// exhaust the source and the channel asks for the next one
// (input/manager.py:50-52, :182-192, :533-538). Asserted at the source
// (three Runs), at the resolver (one request excluding stream 1 and naming
// it as current), at the events (two channel_reconnect, one channel_error
// with connection_failed and attempts 3, one stream_switch), and at the
// outcome (the alternate runs, the channel is active).
func TestThreeConnectFailuresExhaustTheSourceAndFailOver(t *testing.T) {
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	primary := &int32Counter{}
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: flowingSource{runs: alternate},
		Info:   SourceInfo{URL: "http://provider.invalid/live/u/hunter2/alt.ts", StreamID: 2, M3UProfileID: 1, ChannelName: "Not The Channel"},
	}}}

	ch, release := attachWith(t, m, "row3", failingSource{runs: primary}, testTuning(), resolver)
	defer release()

	waitFor(t, "the alternate to run", 10*time.Second, func() bool { return alternate.get() == 1 })
	waitFor(t, "the channel to go active on the alternate", 10*time.Second, func() bool { return ch.State() == StateActive })

	if got := primary.get(); got != 3 {
		t.Fatalf("the primary was attempted %d times, want MAX_RETRIES = 3", got)
	}
	reqs := resolver.requests()
	if len(reqs) != 1 {
		t.Fatalf("the resolver was asked %d times, want 1", len(reqs))
	}
	if len(reqs[0].Exclude) != 1 || reqs[0].Exclude[0] != 1 || reqs[0].CurrentStreamID != 1 || reqs[0].CurrentURL != "http://provider.invalid/primary.ts" {
		t.Fatalf("the request was %+v, want exclude [1], current stream 1 and the primary URL", reqs[0])
	}
	if got := ch.Source().StreamID; got != 2 {
		t.Fatalf("Source().StreamID = %d after the switch, want 2", got)
	}

	if reconnects := events.of("channel_reconnect"); len(reconnects) != 2 {
		t.Fatalf("channel_reconnect raised %d times, want 2 (attempts 2 and 3): %+v", len(reconnects), reconnects)
	} else if reconnects[1].Details["attempt"] != 3 || reconnects[1].Details["max_attempts"] != 3 {
		t.Fatalf("the last channel_reconnect carried %+v, want attempt 3 of 3", reconnects[1].Details)
	}
	failed := events.of("channel_error")
	if len(failed) != 1 || failed[0].Details["error_type"] != "connection_failed" || failed[0].Details["attempts"] != 3 {
		t.Fatalf("channel_error = %+v, want one with error_type connection_failed and attempts 3", failed)
	}
	if url, _ := failed[0].Details["url"].(string); strings.Contains(url, "hunter2") || strings.Contains(url, "/live/") {
		t.Fatalf("channel_error carries the provider credential: %q", url)
	}
	switched := events.of("stream_switch")
	if len(switched) != 1 || switched[0].StreamID == nil || *switched[0].StreamID != 2 || switched[0].ChannelID != "row3" {
		t.Fatalf("stream_switch = %+v, want one naming stream 2 on channel row3", switched)
	}
	// channel_name is the channel's, fixed at construction (input/manager.py:
	// 41-44), not the alternate's -- whose SourceInfo here carries a name of
	// its own precisely so this can tell them apart.
	if switched[0].ChannelName != "Test Channel" {
		t.Fatalf("stream_switch channel_name = %q, want the channel's own \"Test Channel\"", switched[0].ChannelName)
	}
	if url, _ := switched[0].Details["new_url"].(string); strings.Contains(url, "hunter2") || !strings.HasPrefix(url, "http://provider.invalid/") {
		t.Fatalf("stream_switch new_url = %q: must be the redacted URL, host kept and path gone", url)
	}
}

// PARITY-MATRIX ROW 2: no data for longer than the inactivity threshold,
// observed on three consecutive health checks, switches streams
// (input/manager.py:1547-1551, :1553-1609, :414-438) -- the unstable branch,
// the same one the Python pin drives, because the stable branch needs 30
// seconds of wall clock (row 2's Notes). Thresholds compressed off the
// tuning: 300 ms of silence, checked every 50 ms.
//
// THE THREE CHECKS ARE THE ASSERTION, not the switch alone. The source
// records when it wrote its last byte; the resolver records when it was
// asked; the gap must be at least the threshold plus two more intervals. A
// port that acted on the first inactive check would ask at ~300-350 ms and
// redden. And no connection failure is counted: Python leaves the retry loop
// on the flag before its failure accounting (:505-507).
func TestDeadAirOnAYoungConnectionSwitchesStreams(t *testing.T) {
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)

	lastWrite := &timeCell{}
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: flowingSource{runs: alternate},
		Info:   SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 2, M3UProfileID: 1},
	}}}
	tuning := testTuning()
	tuning.ConnectionTimeout = 300 * time.Millisecond
	tuning.HealthCheckInterval = 50 * time.Millisecond

	ch, release := attachWith(t, m, "row2", deadAirSource{packets: 8, lastWrite: lastWrite}, tuning, resolver)
	defer release()

	sawUnhealthy := false
	waitFor(t, "the switch to the alternate", 10*time.Second, func() bool {
		if !ch.Healthy() {
			sawUnhealthy = true
		}
		return alternate.get() == 1
	})
	if !sawUnhealthy {
		t.Fatal("the channel was never observed unhealthy before it switched")
	}
	asked, wrote := resolver.firstCallAt(), lastWrite.get()
	if gap := asked.Sub(wrote); gap < tuning.ConnectionTimeout+2*tuning.HealthCheckInterval {
		t.Fatalf("the resolver was asked %s after the last byte, under CONNECTION_TIMEOUT + two more checks (%s): the monitor did not wait for three consecutive checks", gap, tuning.ConnectionTimeout+2*tuning.HealthCheckInterval)
	} else if gap > 3*time.Second {
		t.Fatalf("the resolver was asked %s after the last byte: the dead air was not acted on", gap)
	}
	if len(events.of("stream_switch")) != 1 {
		t.Fatalf("stream_switch raised %d times, want 1", len(events.of("stream_switch")))
	}
	if errs := events.of("channel_error"); len(errs) != 0 {
		t.Fatalf("channel_error raised %+v: a health-requested switch records no connection failure", errs)
	}
	waitFor(t, "health to be restored on the alternate", 5*time.Second, ch.Healthy)
}

// The health flag comes back on its own when data resumes before the third
// check (input/manager.py:1594-1601), and nothing is switched. A source that
// pauses for one threshold and a half, against a threshold of 300 ms
// checked every 200 ms: the check at 400 ms finds it inactive, the one at
// 600 ms finds data 100 ms old.
func TestHealthIsRestoredWhenDataResumesBeforeTheThirdCheck(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	resolver := &fakeResolver{}
	tuning := testTuning()
	tuning.ConnectionTimeout = 300 * time.Millisecond
	tuning.HealthCheckInterval = 200 * time.Millisecond

	source := pausingSource{pause: 450 * time.Millisecond}
	ch, release := attachWith(t, m, "restore", source, tuning, resolver)
	defer release()

	waitFor(t, "the channel to be marked unhealthy during the pause", 3*time.Second, func() bool { return !ch.Healthy() })
	waitFor(t, "health to be restored once data resumes", 3*time.Second, ch.Healthy)
	if got := len(resolver.requests()); got != 0 {
		t.Fatalf("the resolver was asked %d times: a pause shorter than three checks must not switch", got)
	}
	m.Stop("restore")
}

// pausingSource writes, stops for `pause`, then writes forever.
type pausingSource struct{ pause time.Duration }

func (s pausingSource) Run(ctx context.Context, sink io.Writer) error {
	payload := relaytest.SyntheticTS(8, 0x100)
	if _, err := sink.Write(payload); err != nil {
		return err
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-time.After(s.pause):
	}
	return flowingSource{}.Run(ctx, sink)
}

// Out of candidates, the channel ends in error carrying Python's own message
// (input/manager.py:679-682): "All N stream options failed" when any stream
// id was tried -- the initial one counts -- and the last attempt's error
// still reachable through it.
func TestAnExhaustedChannelEndsInErrorNamingTheCount(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	ch, release := attachWith(t, m, "exhausted", failingSource{runs: &int32Counter{}}, testTuning(), &fakeResolver{})
	defer release()
	<-ch.Done()
	if ch.State() != StateError {
		t.Fatalf("state = %q, want error", ch.State())
	}
	var exhausted *ErrSourcesExhausted
	if !errors.As(ch.Err(), &exhausted) || exhausted.Message() != "All 1 stream options failed" {
		t.Fatalf("Err() = %v, want \"All 1 stream options failed\"", ch.Err())
	}
	var status *ErrUpstreamStatus
	if !errors.As(ch.Err(), &status) || status.Status != 404 {
		t.Fatalf("the last attempt's error is not reachable through the exhaustion error: %v", ch.Err())
	}
}

// A resolver that names the URL already playing is refused, as update_url
// refuses it (input/manager.py:1464-1466), and the failover reports failure.
func TestAFailoverThatNamesTheURLAlreadyPlayingIsRefused(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	resolver := &fakeResolver{answers: []Resolved{{Source: flowingSource{}, Info: SourceInfo{URL: "http://provider.invalid/primary.ts", StreamID: 7}}}}
	ch, release := attachWith(t, m, "same-url", failingSource{runs: &int32Counter{}}, testTuning(), resolver)
	defer release()
	<-ch.Done()
	if ch.State() != StateError || ch.Source().StreamID != 1 {
		t.Fatalf("state = %q, stream %d: the switch to the URL already playing went through", ch.State(), ch.Source().StreamID)
	}
	if len(resolver.requests()) != 1 {
		t.Fatalf("the resolver was asked %d times, want 1", len(resolver.requests()))
	}
}

// PARITY-MATRIX ROW 7 ACROSS A SWITCH: the chunk index is monotonic for the
// channel's life and a switch never rewinds it or empties the ring
// (CLAUDE.md § Architecture) -- what the packetiser holds is dropped
// (ResetPosition, input/buffer.py's reset_buffer_position), so the old
// upstream's partial trailing packet is never glued to the new one's first
// bytes. The primary writes eight whole packets and three stray bytes before
// failing; the alternate's packets must arrive aligned, after the primary's,
// with the head still climbing.
func TestTheChunkIndexIsMonotonicAcrossAFailover(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{
		Source: flowingSource{runs: alternate},
		Info:   SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 2},
	}}}
	tuning := testTuning()
	tuning.MaxRetries = 1 // one failure exhausts the primary, so the ring holds one copy of its packets
	ch, release := attachWith(t, m, "row7", raggedSource{}, tuning, resolver)
	defer release()

	waitFor(t, "the primary's chunks", 5*time.Second, func() bool { return ch.Ring().Head() >= 2 })
	headBefore := ch.Ring().Head()
	waitFor(t, "the alternate to run", 10*time.Second, func() bool { return alternate.get() == 1 })
	waitFor(t, "the alternate's chunks", 10*time.Second, func() bool { return ch.Ring().Head() >= headBefore+2 })

	chunks, _, skipped := ch.Ring().Read(0)
	if skipped != 0 || len(chunks) < 4 {
		t.Fatalf("the ring holds %d chunks from index 0 with %d skipped: the switch emptied it", len(chunks), skipped)
	}
	for i, chunk := range chunks {
		if problem := relaytest.AlignmentProblem(chunk); problem != "" {
			t.Fatalf("chunk %d is not whole packets: %s -- the stray bytes were glued to the new upstream's first packet", i, problem)
		}
	}
	// The primary's packets first (pid 0x100), the alternate's after (pid
	// 0x200), and never the other way round.
	seenAlternate := false
	for i, chunk := range chunks {
		pid := int(chunk[1]&0x1f)<<8 | int(chunk[2])
		switch {
		case pid == 0x200:
			seenAlternate = true
		case pid == 0x100 && seenAlternate:
			t.Fatalf("chunk %d carries the primary's packets after the alternate's: the index rewound", i)
		}
	}
	if !seenAlternate {
		t.Fatal("no chunk from the alternate reached the ring")
	}
	m.Stop("row7")
}

// raggedSource writes eight whole packets and three stray bytes, then fails.
type raggedSource struct{}

func (raggedSource) Run(_ context.Context, sink io.Writer) error {
	payload := relaytest.SyntheticTS(8, 0x100)
	if _, err := sink.Write(append(payload, 0x47, 0x01, 0x02)); err != nil {
		return err
	}
	return &ErrUpstreamStatus{Status: 502}
}

// The degraded bookkeeping of _try_next_stream (input/manager.py:2191-2202):
// a switch resolved from the cache sets the flag and raises nothing; the next
// switch the control plane answers raises channel_error with
// reason degraded_failover, once.
func TestAFailoverFromTheCacheRaisesDegradedFailoverOnRecovery(t *testing.T) {
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Events: events})
	t.Cleanup(m.StopAll)
	second := &int32Counter{}
	third := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{
		{Source: failingSource{runs: second}, Info: SourceInfo{URL: "http://provider.invalid/2.ts", StreamID: 2}, Degraded: true},
		{Source: flowingSource{runs: third}, Info: SourceInfo{URL: "http://provider.invalid/3.ts", StreamID: 3}},
	}}
	tuning := testTuning()
	tuning.MaxRetries = 1
	ch, release := attachWith(t, m, "degraded", failingSource{runs: &int32Counter{}}, tuning, resolver)
	defer release()

	waitFor(t, "the third source to run", 10*time.Second, func() bool { return third.get() == 1 })
	if got := ch.Source().StreamID; got != 3 {
		t.Fatalf("Source().StreamID = %d, want 3", got)
	}
	var degraded []Event
	for _, e := range events.of("channel_error") {
		if e.Details["reason"] == "degraded_failover" {
			degraded = append(degraded, e)
		}
	}
	if len(degraded) != 1 {
		t.Fatalf("degraded_failover raised %d times, want exactly 1, on the recovery: %+v", len(degraded), events.all())
	}
	// Ordered: the degraded_failover event follows the second stream_switch,
	// never the first.
	var switches, degradedAt int
	for i, e := range events.all() {
		if e.Type == "stream_switch" {
			switches++
		}
		if e.Type == "channel_error" && e.Details["reason"] == "degraded_failover" {
			degradedAt = i
			if switches != 2 {
				t.Fatalf("degraded_failover was raised after %d switches, want 2", switches)
			}
		}
	}
	_ = degradedAt
	m.Stop("degraded")
}

// The other half of row 6: MAX_STREAM_SWITCHES DOES bound a main-loop
// switch. With the bound at zero, `stream_switch_attempts <= 0` admits the
// first pass, the connect-failure switch happens, and the loop then exits
// without ever running the new source (input/manager.py:388-402) -- the
// channel errors although its alternate would have flowed. Together with
// TestABufferingFailoverIgnoresMaxStreamSwitches this pins the asymmetry.
func TestMaxStreamSwitchesBoundsAMainLoopSwitch(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{Source: flowingSource{runs: alternate}, Info: SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 2}}}}
	tuning := testTuning()
	tuning.MaxRetries = 1
	tuning.MaxStreamSwitches = 0
	ch, release := attachWith(t, m, "bound", failingSource{runs: &int32Counter{}}, tuning, resolver)
	defer release()
	<-ch.Done()
	if ch.State() != StateError {
		t.Fatalf("state = %q, want error: the bound of zero ends the loop after its first switch", ch.State())
	}
	if len(resolver.requests()) != 1 {
		t.Fatalf("the resolver was asked %d times, want 1: the switch itself happens", len(resolver.requests()))
	}
	if alternate.get() != 0 {
		t.Fatal("the alternate ran: the main loop ignored MAX_STREAM_SWITCHES")
	}
}

// The provider slot is released exactly once, when the source goroutine
// returns, with the CURRENT source's ids -- after a failover, the
// alternate's -- and on a stop as much as on an exhaustion.
func TestTheSlotIsReleasedOnceWhenTheSourceGoroutineReturns(t *testing.T) {
	var mu sync.Mutex
	var released []SourceInfo
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Release: func(_ string, info SourceInfo) {
		mu.Lock()
		defer mu.Unlock()
		released = append(released, info)
	}})
	t.Cleanup(m.StopAll)
	alternate := &int32Counter{}
	resolver := &fakeResolver{answers: []Resolved{{Source: flowingSource{runs: alternate}, Info: SourceInfo{URL: "http://provider.invalid/alt.ts", StreamID: 2, M3UProfileID: 5}}}}
	tuning := testTuning()
	tuning.MaxRetries = 1
	ch, release := attachWith(t, m, "release", failingSource{runs: &int32Counter{}}, tuning, resolver)
	waitFor(t, "the alternate to run", 10*time.Second, func() bool { return alternate.get() == 1 })
	mu.Lock()
	n := len(released)
	mu.Unlock()
	if n != 0 {
		t.Fatalf("released %d times while the channel was still running", n)
	}
	release()
	<-ch.Done()
	waitFor(t, "the release", 5*time.Second, func() bool { mu.Lock(); defer mu.Unlock(); return len(released) == 1 })
	mu.Lock()
	defer mu.Unlock()
	if released[0].StreamID != 2 || released[0].M3UProfileID != 5 {
		t.Fatalf("released %+v, want the alternate's stream 2 on profile 5", released[0])
	}
}

// fakeClock is an injectable time.Now for the manager, so a "stable for 31
// seconds" stream costs no wall clock.
type fakeClock struct {
	mu sync.Mutex
	t  time.Time
}

func (c *fakeClock) now() time.Time {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.t
}

func (c *fakeClock) advance(d time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.t = c.t.Add(d)
}

// stallingSource writes two chunks' worth, reports it, then writes again on
// every resume signal and reports each, blocking until cancelled: a provider
// that goes quiet after a stable run, twice over. Every Run counts.
type stallingSource struct {
	runs   *int32Counter
	resume chan struct{}
	wrote  chan struct{}
}

func (s stallingSource) Run(ctx context.Context, sink io.Writer) error {
	s.runs.inc()
	payload := relaytest.SyntheticTS(8, 0x100)
	if _, err := sink.Write(payload); err != nil {
		return err
	}
	s.wrote <- struct{}{}
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-s.resume:
			if _, err := sink.Write(payload[:4*buffer.TSPacketSize]); err != nil {
				return err
			}
			s.wrote <- struct{}{}
		}
	}
}

// THE RECONNECT FLAG IS CLEARED ON EVERY PASS OF THE INNER LOOP
// (input/manager.py:521-531), and a shape that cleared it only at the outer
// loop's top left it set after the first reconnect: the monitor's own guard
// (`if not self.needs_reconnect`, :1581) then never cancelled again, and a
// SECOND stall on a stable stream was logged and never acted on -- the 2c-5
// plan's reviewer reproduced that against an earlier loop. Two stable stalls
// with an injected clock (31 s of stability, then 35 s of silence, twice):
// each must cancel the attempt and start the next, so the source runs three
// times, and channel_reconnect is raised for attempts 2 and 3 with no
// `reason: health_monitor` shape, which is the outer branch Python cannot
// reach (Ruling R4).
func TestASecondStableStallIsActedOnAfterAHealthReconnect(t *testing.T) {
	clock := &fakeClock{t: time.Date(2026, 9, 14, 12, 0, 0, 0, time.UTC)}
	events := &eventLog{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400, Now: clock.now, Events: events})
	t.Cleanup(m.StopAll)

	runs := &int32Counter{}
	src := stallingSource{runs: runs, resume: make(chan struct{}), wrote: make(chan struct{})}
	tuning := testTuning()
	tuning.HealthCheckInterval = 20 * time.Millisecond
	ch, release := attachWith(t, m, "stall-twice", src, tuning, &fakeResolver{})
	defer release()

	for stall := 1; stall <= 2; stall++ {
		<-src.wrote                     // this attempt's first bytes: the ring holds a chunk
		clock.advance(31 * time.Second) // stable past stableReconnectAfter
		src.resume <- struct{}{}
		<-src.wrote                     // lastData is now 31 s after connStart
		clock.advance(35 * time.Second) // silence past CONNECTION_TIMEOUT, past the cooldown
		want := stall + 1
		deadline := time.Now().Add(5 * time.Second)
		for runs.get() != want && time.Now().Before(deadline) {
			time.Sleep(10 * time.Millisecond)
		}
		if runs.get() != want {
			t.Fatalf("stall %d: the source ran %d times, want %d -- needsReconnect stayed set after the first reconnect and the monitor never cancelled again", stall, runs.get(), want)
		}
	}
	reconnects := events.of("channel_reconnect")
	if len(reconnects) != 2 || reconnects[0].Details["attempt"] != 2 || reconnects[1].Details["attempt"] != 3 {
		t.Fatalf("channel_reconnect = %+v, want attempts 2 and 3", reconnects)
	}
	for _, e := range reconnects {
		if e.Details["reason"] == "health_monitor" {
			t.Fatalf("channel_reconnect carried reason health_monitor: the outer-loop branch is unreachable in Python and is not ported")
		}
	}
	if ch.State() != StateActive {
		t.Fatalf("state = %q after two reconnects, want active", ch.State())
	}
	m.Stop("stall-twice")
}
```

### Appendix AD — `apps/proxy/tests/test_relay_list_payload_golden.py`, two edits

The file is 2c-4's (its Appendix T5). Two edits, both in the same idiom; nothing else moves.

**1. `NOT_SERVED_YET` loses `healthy`**, and its comment says why the count moved:

```python
# Every RelayChannelSerializer field the Go relay does not produce yet, and
# why. A field in neither this mapping nor the fully-populated fixture channel
# fails test_the_fixture_covers_every_serializer_field, which is what stops
# the golden from silently narrowing as the endpoint grows. 2c-3 excused
# nine; 2c-4's transcode source produced seven of them (the input format
# included -- it is log_parsers.py's parse_input_format), and 2c-5's health
# monitor produced `healthy` (channel_status.py:527-529). One remains.
NOT_SERVED_YET = {
    "logo_id": (
        "ChannelMetadataField.LOGO_ID is written only into the TIMESHIFT key "
        "family (apps/timeshift/views.py:2984, timeshift:channel:<id>:metadata), "
        "never into the live:channel:<uuid>:metadata hash channel_status.py:486 "
        "reads, so the live list endpoint never emits it in Python either"
    ),
}
```

**2. The populated fixture channel gains `healthy`**, in the serializer's declaration order — immediately after `avg_bitrate` and before the seven ffmpeg-derived fields (`relay_serializers.py:55-57`):

```python
                "avg_bitrate": "2.67 Mbps",
                # Phase 2 PR 2c-5: the health monitor's flag, present on every
                # channel the relay process holds (channel_status.py:527-529).
                "healthy": True,
                # The seven ffmpeg-derived fields, Phase 2 PR 2c-4: present only
```

Then regenerate (Task 5 Step 1). The JSON gains exactly `"healthy": true` between `"avg_bitrate"` and `"video_codec"` on channel 1 and nothing on channel 2, which has no manager.

### Appendix AE — Amendment A5, verbatim, after A4 in the spec

```markdown
#### Amendment A5 (2c-5) — eight corrections and inputs from the failover

**A5.1 — a clean upstream EOF is a retried connection failure, and the
loop is ported whole.** `fetch_chunk` reads an empty chunk as "Server closed
connection" (`input/manager.py:1868-1872`); `_process_stream_data` returns;
the retry loop records a failure and reconnects with backoff (`:557-568`),
three times, and only then asks for the next source (`:533-538`, `:600-616`).
2c-2 ended the channel on the first EOF and pinned it, which was the honest
shape before there was a loop; 2c-5 replaces `Channel.run` with the port of
`StreamManager.run`'s two loops (`relay/channel/channel.go`) and reshapes
that test. The key-family table's "Timing/telemetry" row is now closed:
`connection_attempt`, `last_data` and `transcode_active` are the channel's
`connStart`, `lastData` and `connected` fields.

**A5.2 — the Resolver seam, and where the degraded fallback lives.**
`channel.Resolver` is how a channel asks for its next source; `httpapi`
implements it over `control.Client` and holds the candidate list the initial
answer carried (`IncludeAlternates: true`, as `url_utils.py:60-61` asks) --
the in-memory form of `channel_source_cache`. Only a `control.Unavailable`
falls back to it, after the client's own retry; a `Refused` fails the switch
loudly (§ Error handling per hop, `input/manager.py:2095-2112`). The timing
shape CLAUDE.md records -- "after up to ~14 s per control-plane call" -- is
the client's two attempts of (2 s, 5 s) plus the retry delay, spent before
the cache is read, and is pinned at compressed values.

**A5.3 — the events client lands with six types; four are 2c-8's.**
`control.Emitter` posts fire-and-forget through one worker and a bounded
queue, batching up to the route's `max_length` of 200, logging an outage
once on the way in and once on the way out, and losing -- not queuing --
what is raised during it. The relay raises `channel_buffering`,
`channel_failover`, `stream_switch`, `channel_reconnect` and `channel_error`
(`connection_failed`, `degraded_failover`): `input/manager.py`'s five, the
`channel_reconnect{reason: health_monitor}` shape excluded because it lives
inside `_attempt_reconnect`, which A5.7 shows Python cannot reach.
`channel_start`, `channel_stop`, `client_connect` and `client_disconnect`
are raised from the tune path and the coordinated stop (`views.py`,
`server.py`, `output/ts/generator.py:129`) and **belong to 2c-8** with the
control routes; the 2c-8 row is amended to say so.

**A5.4 — the #190 `hdel`s need no move and no Redis read; an input for
2d.** `Channel.release_stream()`'s `hdel` of `STREAM_ID`/`M3U_PROFILE` from
the relay's metadata hash guards a duplicate release against a double
`DECR`. The Go relay has no hash, so Django's `hdel` is a no-op against it,
and the property is met structurally: `Channel.run`'s deferred release is
the one call, once per channel. The two Django-side fallback reads
(`release_stream()`'s recovery branch, `_release_stale_stream_assignment`)
run only when Django's own `stream_profile:` key is already gone
(`apps/channels/models.py:501-542`) and find nothing under the Go relay,
warning "profile_connections may leak" -- the corner Python already
documents. 2d deletes the hash and the reads together. `channel_pk` is sent
as null: it is on no contract field and Django uses it only in that
fallback.

**A5.5 — a Redirect tune publishes no channel, because Python renders none.**
`stream_ts`'s Redirect branch (`views.py:468-547`) returns before
`initialize_channel`, the only writer of the metadata hash the list endpoint
renders, and passes through the `finally` at `:645-648` that releases the
ownership it took. The Go tune returns the 302 as an error out of the start
function; `Manager.Attach` publishes nothing; `GET /proxy/relay/channels`
shows nothing. The internal-principal override reads the request's own
static `X-Dispatcharr-Internal` (`request_is_internal`, `views.py:461`) and
serves the channel through Proxy, force-ffmpeg included, exactly as
`transcode = False` at `:467` does.

**A5.6 — Amendment A2.5 closes.** `channel.Tuning` carries `ClientTimeout`
(the sum `_is_timeout` computes, `output/ts/generator.py:585-587`),
`KeepaliveInterval` and `MaxKeepalive`; `Channel.Healthy()` is the flag
`_monitor_health` lowers and raises; `serveClient` sends keepalives at the
head of an unhealthy channel after five empty reads, caps them, and
evaluates `_is_timeout`'s condition -- reachable on TS only through the cap,
as row 12's Notes record -- minus its `url_switching` exemption
(`output/ts/generator.py:593-596`), which is not ported: `url_switching` is
true only inside `update_url`'s own body (set at `input/manager.py:1476-1477`, cleared at `:1540`), and
a client reprieved in that window is dropped on its next poll. The error TS packet is ported for the client that
received nothing when its channel ended (`:229-231`, the message from
`run`'s finally block); the initialization-timeout packet (`:252-254`) is
not, because this relay has no initializing wait a client can time out in.
`healthy` is on the list payload and leaves the golden's `NOT_SERVED_YET`.

**A5.7 — the stated divergences.** The health monitor cancels the running
attempt where Python's loop notices its flag between `fetch_chunk` calls
(`:1364-1365`), each blocking up to `CHUNK_TIMEOUT` in `select` (`:1845`), so
the Go relay acts up to five seconds sooner and `CHUNK_TIMEOUT` is not read;
the outer loop's `_attempt_reconnect` branch (`:414-426`) is not ported,
because Python cannot reach it -- the monitor sets `needs_reconnect` only
while connected (`:1565`) and the inner loop clears it on every pass
(`:527`) before the outer loop's top can see it -- so a health reconnect is
the inner loop's fall-through (`:521-534`) here as there, and no
`channel_reconnect{reason: health_monitor}` is raised; after a
buffering-triggered switch the new source starts as attempt 1 with a clean
history, where Python's main loop may record one failure for the attempt the
switch ended (`:533-534`) unless `update_url`'s clear (`:1512`) lands after
it; `channel_reconnect` is raised as a retry attempt starts rather than once
established; event URLs
go through `redact.Line` (scheme and host) where `redact_url` keeps more;
one emitter worker and batching where Python spawns a greenlet per event;
`URL_SWITCH_TIMEOUT` and `RETRY_WAIT_INTERVAL` are not read (the first
resets a flag the synchronous switch cannot leave stuck, the second has no
Python caller); the slot is released when the source goroutine returns
rather than at the stop path's cleanup; a second client arriving during a
Redirect tune gets its own probe and 302 rather than Python's follower wait.
Every one is in the safe direction and none is client-observable streaming
behaviour.

**A5.8 — a Python defect the port carries.** A buffering timeout whose
`_try_next_stream()` fails leaves the buffering flag set, and the next
`speed=` record -- every ~0.5 s -- reaches the timeout branch again
(`input/manager.py:1178-1211`): one control-plane call per progress record
for as long as the speed stays low. Reproduced per D5
(`TestABufferingTimeoutWithNoAlternateKeepsPlayingAndAsksOnEveryRecord`),
recorded in `CLAUDE.md` § Known defects, filed as [#NNN], not fixed here
(D10).
```
