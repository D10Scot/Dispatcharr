# Phase 2 PR 2c-8 — the Go relay's control routes and drain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Go relay's externally-observable surface. The four `/proxy/relay/…` routes 2c-3 did not serve — the single-channel `GET` (with its `?fields=state` form), the channel `DELETE`, the client `DELETE` and the `advance` `POST`; the detail endpoint's five extra client fields and parity-matrix **row 14**'s `owner` asymmetry; the **XC live roots**, which spec D1 scopes and no PR owned (Ruling R1); the four events the tune and stop paths raise — `channel_start`, `channel_stop`, `client_connect` (both client types) and `client_disconnect` (TS only); the dev-only `POST /_dispatcharr/authorize-internal` fallback and the Go half that calls it; and D6's SIGTERM drain, a `/readyz` that reports something real and a Docker `HEALTHCHECK`. **Every remaining un-Go'd parity-matrix row gets a Go pin: thirteen of them, taking the matrix from 14 Go-pinned rows to 28 of the 28 that can carry one.**

**Architecture:** Three new `httpapi` files carry the routes (`detail.go` renders `get_detailed_channel_info`, `control.go` the two `DELETE`s and the `advance`, `xc.go` the two XC roots as a thin wrapper around the TS handler), one new `control` file carries the authorize client, and one new package, `relay/drain`, carries the shutdown sequence so it can be driven and measured by a test rather than only by a signal. `channel` gains a per-client meter (the four counters the TS generator writes and the fMP4 one does not), a stop signal per client, `state_changed_at`, and `Advance` — the operator switch, which shares `applySwitch` with the automatic failover so the two cannot spawn different things. Django gains one route, three serializer fields on the advance request and one helper; the relay still opens no Postgres connection and no Redis connection.

**This PR stays inert in every deployment**: every route is behind 2c-1's dev flag except `/healthz` and `/readyz`, and nginx routes nothing to port 5658 until stage 2d.

**Tech Stack:** Go 1.27.1, standard library only; **eight Python files touched — six changed and two added** (of the six, one is an existing test whose expected payload grows); two Docker files changed and one added, the added one committed executable.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — D1 (scope: the live TS route **and the XC live roots**), D2, **D5 and its exception 2** (§ The contract's dev-fallback section in full), **D6** (the drain, the health endpoints, the supervisord and `HEALTHCHECK` wiring), D7; the 2c-8 row of the nine-PR table (~line 1807); § The contract's Django→relay table and its four field-level quirks; the corrected per-hop error table; Amendments A1.4, A2.2, A3.1, A3.4, A4.1, A5.3, A6.5, and A7 as 2c-7 lands it. This plan amends the spec in Task 9 where its text is silent or wrong, and says so in the Done log.

---

## Sequencing: this plan sits on 2c-7 as merged, at `d6d71f97`

**2c-7 is merged, on `main` at `d6d71f97`** (PR #311, a squash of `migration/phase2c-output-profile` at `002e1e82`; 28 files, +2483/−97). Read its plan with `git -C <repo> show "d6d71f97:docs/superpowers/plans/2026-09-13-phase2-2c7-output-profiles.md"` — cite `main`, not the `docs/phase2c7-plan` branch, which may be deleted, and **brace the expansion in zsh** or the `:path` is eaten as a history modifier and you get the tip commit's diff instead, exit code 0 and all.

**This plan has been re-seeded from that SHA, tests included, and every appendix re-captured against it.** Nothing here was built against 2c-7's appendices any more; `git archive d6d71f97 relay` is the baseline every diff below is taken from. The history is worth one sentence because it is what the ledger is for: the appendices were first built on `eb7fac07` with 2c-7's own plan appendices applied over it, at a point when 2c-7 was neither merged nor implemented, and the ledger below was written as the set of expectations that seeding created.

**What the re-seed found, which is the only number that matters here: of seventeen Go hunks, SIXTEEN applied to the merged tree unchanged and ONE did not** — `internal/relaytest/controlplane.go`, which the ledger had already flagged as "the one file both PRs edit in the same two structs and the same answer builder". Its five additions were re-applied by hand and re-captured. Every whole-file appendix is byte-identical to what was verified before the re-seed. Task 0's own ledger walk found **no other difference**: `control.Source` still carries the profile fields, `Resolved` still carries `OutputProfiles`, `sourceBuilder`/`infoFrom`/`resolver.build` are unchanged, `Manager.publish` still seeds its client map with the literal Ruling R4 replaces, `relaytest` has `SetOutputProfiles` with its own `hasProfs`, `httpapi/profile.go`'s unlocked write is gone, and `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` exists and stays green through Task 1's `applySwitch` extraction.

**Two of the three document hunks had to be re-captured, exactly as the plan predicted.** Appendix AN's spec hunk was anchored where A6 ended and 2c-7 inserted A7 there; its Done-log placeholder row for 2c-7 is gone, replaced by the real row 2c-7 merged. Appendix AM's matrix hunk moved because row 11 now carries a Go pin and Notes of its own. Appendix AO's `CLAUDE.md` hunk was re-captured too and its content is unchanged. **The Python/Docker hunk applied to the merged tree without a change** beyond one blob index line.

**`d6d71f97` is `d6d71f97`.** Task 0 remains in the plan as the check a later reader re-runs, not as work still owed.

### The 2c-7 dependency ledger

| 2c-7 shape this plan builds on | Where 2c-8 touches it | If your tree differs |
|---|---|---|
| `control.Source` carries `StreamProfile StreamProfileRef`, `FFmpegStreamProfile *StreamProfileRef`, `Transcode`, the three names and `SlotReserved` | Task 3's `advanceSource` builds one out of the advance body, so `sourceBuilder.source` and `infoFrom` — the same two functions the tune and every failover use — turn it into a running source | a renamed field is a one-line edit in `httpapi/control.go`; a `control.Source` that no longer carries `StreamProfile` is a **stop**: the whole advance contract extension rests on it |
| `control.StreamProfileRef` with `ID`, `Command`, `Args`, `Kind`, `Argv`, `ArgvPresent` and its `UnmarshalJSON` | Task 3 decodes the advance body's `stream_profile` and `ffmpeg_stream_profile` into it, unchanged | a changed decoder is fine; a removed `ArgvPresent` is a **stop** (Amendment A4.3's three states collapse) |
| `control.NextSourceAnswer.OutputProfiles` and `channel.OutputProfiles{Known, …}` | **Nothing.** Task 3's `Advance` carries no output profiles and the channel keeps its cached set, which is what a degraded failover also does (2c-7's Ruling R5) | if `OutputProfiles.Known` is gone, re-read R5 before deciding what `Advance` should do with the set |
| `channel.Resolved{Source, Info, Degraded, OutputProfiles}` | Task 1 factors `applySwitch` out of `failover` and Task 3's `Advance` calls it with a `Resolved` whose `OutputProfiles` is the zero value | a reshaped `Resolved` moves both anchors; Appendix D gives them |
| `channel.Channel` with `resolver`, `outputProfiles`, `outputRegistry`, `switchMu`, `tried`, `currentStreamID`, `pending`, `cancelAttempt` | Task 1 adds `stateChangedAt` and three accessors, Task 3 adds `Advance` and `ExcludedStreamIDs` | a `Channel` that no longer holds `tried` as a `map[int]bool` is a **stop** |
| `channel.Manager.publish`'s `&Channel{…}` literal, whose `clients:` field is `map[string]*Client{client.ID: client}` | Task 1 replaces that literal with an empty map plus `c.addClient(client)` — **the defect this PR found** (Ruling R4) | a `publish` that already calls `addClient` means the defect was fixed upstream; keep the change as a no-op and say so |
| `httpapi.StreamDeps{Secret, Channels, Control, Log, Now, Probe, Remux}` and `StreamHandler`'s body: `identify` → `internal` → `Attach` → `attachOutputProfile` → the format branch | Task 6 adds `Lifecycle`, Task 6 inserts the authorize call before `identify` and gives `identify` a fourth parameter, Task 4 adds two emits around `serveClient`, Task 8 adds the drain gate at the top | a handler that no longer branches on `client.OutputFormat` is a **stop**; Appendix N gives every anchor |
| `httpapi.sourceBuilder{kind, userAgent, readSize}` and its `source(candidate *control.Source)`, plus `infoFrom(source *control.Source)` | Task 3 reaches both through `builderFor(ch)`, which type-asserts the channel's own `Resolver` to `*resolver` and reads its `build` field | a `resolver` that no longer holds a `build sourceBuilder` is a **stop**: Ruling R5 is about reusing the tune's builder rather than assembling a second one |
| `httpapi.ControlDeps{Secret, Channels, Log, Now}`, `ChannelsHandler` and `RequireInternal` | Task 2 and Task 3 add four handlers behind the same gate; Task 3 changes `RequireInternal` to verify the signature over the **body** (Ruling R3) | a `RequireInternal` that already buffers the body means the fix landed upstream; verify it hands the handler a reader over the same bytes |
| `httpapi.channelPayload`/`clientPayload` and `describeChannel` | **Untouched.** Task 2 adds a separate `detailPayload`; the list endpoint gains no field and no route | a merged payload type is a **stop**: row 14 is an asymmetry and one type cannot carry it |
| `httpapi/golden_test.go`'s `goldenPath`, `goldenPayload`, `decodeGolden`, `mustMarshal` | Task 2's `detail_golden_test.go` calls `decodeGolden` and `mustMarshal` unchanged and adds a second golden beside the first | a renamed helper is a find-and-replace in Appendix P |
| `internal/relaytest.ControlPlane` with `NewControlPlane`, `RequestsTo`, `Events`, `EventsOfType`, `SetSettings`, `recordEvents` and `nextSourceAnswer` | Task 2 adds `Nameless`, Task 6 adds the authorize route with `AuthorizeDecision`/`SetAuthorize`/`AuthorizeRequests`/`NonJSONBody`, Task 4 adds `ClientID` to `RecordedEvent` | a fake whose default arm no longer answers next-source for an unmatched path is fine; the authorize arm is matched by suffix before it |
| **THE ONE FILE BOTH PRs EDIT IN THE SAME PLACES.** 2c-7's fix round adds `OutputProfiles`, `OutputProfilesAbsent` and `OutputProfileConfig` to `ControlPlaneConfig`, `SetOutputProfiles` with **its own `hasProfs` flag** (nil means the empty object Django sends, so a nil check would be wrong), and a block in the answer builder replacing the unconditional `"output_profiles": map[string]any{}` | 2c-8 adds three fields to `ControlPlaneConfig` (`Nameless`, `Authorize`), two to the `ControlPlane` struct's mu-guarded block (`authorize`), `ClientID` to `RecordedEvent` and its decoder, a `names()` helper inside the answer builder's `render`, and the authorize arm before the `/release` switch | **EXPECT APPENDIX M TO GO STALE HERE** and to need re-applying by hand. Both PRs add fields to the same two structs and both touch the answer builder. Neither change is semantically entangled with the other — re-apply 2c-8's five additions, keep 2c-7's, and re-capture |
| `channel/failover.go`'s two-line `if resolved.OutputProfiles.Known { c.outputProfiles = … }` | Task 1 factors `applySwitch` out of `failover` and **those two lines move into it**, unchanged and in the same order; `failover` calls it, and Task 3's `Advance` becomes its second caller with a `Resolved` whose `OutputProfiles` is the zero value, so `Known` is false and the set is left alone | **2c-7's fix round PINNED this**, with `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` — before that test existed, deleting those two lines left the entire suite green. The refactor must leave it passing. **If it does not, stop**: the extraction changed behaviour it was written not to change |
| `httpapi/profile.go` **without** `client.OutputProfileID = nil` after `ch.SetClientOutputProfile(client.ID, nil)`, and `httpapi/profile_test.go`'s `TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint` | **Nothing.** Task 2's detail endpoint reads the same field through `ClientSnapshot`, under the same lock, and adds no second writer | a `httpapi/profile.go` that still carries that unlocked write means you seeded from before the fix round — re-seed. Run the race probe with `-race` or it proves nothing |
| 2c-7's own Appendices R, S and T are **diff hunks**, not whole files (its fix round's addendum) | Nothing, unless you are extracting 2c-7's appendices to build a baseline — which is what § Sequencing describes and which needs an extractor that handles both shapes | a seeding script that only writes whole files silently drops three of them; the module then fails to compile, which is the loud half of the failure |
| `internal/relaytest`'s `StandInCommand`, `SyntheticFMP4Init`, `SyntheticFMP4Fragment`, `EffectiveProxySettings`, `SyntheticTS` | Tasks 4 and 7 call all five unchanged | a missing `SyntheticFMP4Fragment` is a **stop**: two tests read past the init segment by its length and break-check 9 stayed green until they did |
| `httpapi/fmp4_test.go`'s `standInRemux`, `readAtLeast`, `rig.tuneFMP4`; `stream_test.go`'s `rig`, `newRig`, `newRigWithClient`, `rigOption`, `withRemux`, `rig.tune`; `fanout_test.go`'s `fanRig`, `fanRigWith`, `rigSettings`, `tuneAs`, `listChannels`, `waitForHead`, `packetRun`; `failover_test.go`'s `failoverRig`, `waitFor`, `readAligned`, `listedChannel`, `listedStreamID` | Every task calls them; Task 8 adds a `Lifecycle` field to `rig` and wires it into `StreamDeps` and the new `HealthDeps` | a renamed helper is a find-and-replace; a `rig` that does not expose `Manager`, `Control` and `Emitter` is a **stop** |
| Amendment **A7** in the spec | Task 9 appends **A8** after it | if A7 is numbered differently on `main`, cite the spec's number |
| `docs/relay-parity-matrix.md` with row 11 Go-pinned by 2c-7 | Task 9 appends a Go pin to thirteen OTHER rows; row 11 is not touched | if row 11 is still `owed:` or carries no `relay/` reference, 2c-7 did not close it — report it and carry on; this PR's own count is stated against 28 pinnable rows |

**Seed your scratch module from the merged tree INCLUDING its `_test.go` files.** Task 0 Step 0 is where the two are reconciled.

---

## Global Constraints

Every task's requirements implicitly include this section. Constraints 1–43 are 2c-1's through 2c-7's, restated because this plan is executed by an agent who has not read them; 44–52 are new.

1. **Anchor every command with an absolute path, or open it with a `cd` into your own worktree.** The shell's working directory has been observed drifting into another agent's worktree with no `cd` issued.

2. **`go test -race` is mandatory on every Go test run: locally, in the hook, in the commit gate, in CI.** This PR adds a goroutine per client (the stop watcher), a shared per-client counter two goroutines touch, a concurrent `StopAll`, and a drain that runs while clients are still unwinding.

3. **Standard library only. No `require` line, no `go.sum`, ever.** `scripts/check_go_stdlib_only.sh relay` is the mechanical check. Everything here is in `bytes`, `context`, `encoding/json`, `errors`, `fmt`, `io`, `log/slog`, `math`, `net/http`, `os`, `os/signal`, `path`, `regexp`, `strconv`, `strings`, `sync`, `sync/atomic`, `syscall`, `time`.

4. **Nothing in `relay/` may open a Postgres connection or a Redis connection, in any task, including a test.** The detail endpoint is where this is most tempting: `get_detailed_channel_info` has **two ORM fallbacks** (`channel_status.py:71-79`, `:97-114`, the `Stream` and `M3UAccountProfile` name lookups) and a Redis `SCAN` of the buffer keyspace (`:286-300`). None is ported. Ruling R7 says what the payload does instead.

5. **Every pin is tool-resolved on the day the PR is opened, never copied from this plan.** This PR adds no action pin and no image pin.

6. **zizmor blocks on every finding in any workflow file you touch.** This PR touches no workflow.

7. **THIS IS THE PR THAT ADDS THE `HEALTHCHECK`, THE DRAIN AND A REAL `/readyz`.** Constraint 7 of 2c-1 through 2c-7 forbade all three and named this PR; Task 8 discharges it. `control.Emitter.Close` (2c-5: "exists so the drain can flush it") and `Pipeline.Stop` (2c-6: "exists so the drain can reach it through `Manager.StopAll` → `Channel.stop` → `run`'s defers") are the two seams those PRs left, and Task 8 is the first caller of both in anger.

8. **Every Go constant that mirrors a Python literal carries its source `file:line` in a comment and is pinned by a test naming the same location.** This PR adds `DefaultClientLimit`'s sibling `detailBufferSample` (5, `channel_status.py:237`), `userAgentEventLimit` (100, `output/ts/generator.py:137`), `OwnerUnknown` and `WorkerUnknown` (the literal `"unknown"`, `channel_status.py:45` and `:181`), `XCStreamIDPattern` (`dispatcharr/utils.py:115`), and `MaxInternalBody`. The three drain budgets are **not** in this class — they describe this process's shutdown against this deployment's supervisord configuration, not a Python literal — and Constraint 46 covers them instead.

9. **Prefer `t.Setenv` over manual environment save/restore, and never run an environment-mutating test with `t.Parallel()`.** Every test that spawns the fMP4 stand-in calls `t.Setenv(relaytest.StandInEnv, "1")`, so none of them may be parallel.

10. **This PR DOES need a Django test run, and it must not be the shared `dispatcharr-testrunner` container.** Eight Python files are touched: six changed (`authorize_views.py`, `next_source.py`, `relay_client.py`, `relay_serializers.py`, `live_proxy/views.py`, and `live_proxy/tests/zero_orm_allowlist.py`), one existing test amended (`tests/test_relay_client.py`) and two added. Start your own container from your own worktree:

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

    **Without `DJANGO_SECRET_KEY` the run dies before the first test** with `ImproperlyConfigured: The SECRET_KEY setting must not be empty` — measured, and it looks like a broken container rather than a missing variable. **`dispatcharr/urls.py` is in `_SHARED_PATH_PREFIXES`**, so this PR's commit gate runs **all sixteen** backend labels, not three. Task 10 runs them.

11. **Stage and commit in separate Bash calls, and write commit messages to a file and use `-F`.** The `PreToolUse` gate runs before the command, so one Bash call that stages and commits is blocked, and a message merely containing the words `git commit` trips it too.

12. **A provider URL is a credential and never reaches a log, an error message or a public response body.** This PR adds no new log line carrying one. The detail endpoint **does** carry the URL in its payload, deliberately and for 2c-3's Ruling R7 reason: that endpoint is internal, gated on the static `X-Dispatcharr-Internal` **and** a per-request bound token, reachable only by a caller holding `SECRET_KEY`, and it carries the URL today — `channel_status.py:42`. Omitting it would blank the Stats page's URL column for every Go-served channel.

13. **A control-plane setting is read from the wire or the tune fails. Never from a Go-side default.** This PR reads **no new setting**. The drain's three budgets are Go-side constants and Constraint 46 states why that is not an exception.

14. **Parity is against the code, not against the summary.** Every behavioural claim here carries a `file:line`. **Six places where reading the source — or running it — changed this plan**, each recorded in the ruling or the test that carries it: the XC live roots have no owning PR (R1); `RelayAdvanceRequestSerializer` cannot describe a source a relay with no word splitter can spawn (R2); `RequireInternal` was verifying the signature against an empty body (R3); `Manager.publish` seeded its client map without `addClient` (R4); `ffmpeg_bitrate` is read under one constant and written under another (R7); and the fMP4 generator writes `last_active` and no byte counter, which makes the detail endpoint's three counter fields a per-format asymmetry rather than a per-client one (R8).

15. **Decide every lint finding in this plan, and re-lint after every `#nosec`.** This PR adds **no suppression**. Two findings on the first lint were fixed rather than suppressed: a `revive` "comment on exported method" where a new accessor was inserted between an existing doc comment and its function, and a `staticcheck` ST1011 on a `time.Duration` constant named with a `Secs` suffix. Task 10 lists them as zero new against 2c-7's zero.

16. **Run the four checks after every task, from the module root**, and treat any of the four failing as a stop:

    ```bash
    cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
    ```

    `gofmt -l .` must print nothing. Add `GOOS=linux` and `GOOS=darwin` passes of `go vet` and `golangci-lint` at Task 10 — Amendment A4.7's rule. No task here edits `spawn_linux.go` or `spawn_other.go`, so there is no mid-plan three-GOOS pass to run.

17. **An ordering bug is not a data race, and `-race` is silent on every one of them.** This PR's instructive one is Ruling R11: the drain must stop the channels **before** it calls `Shutdown`, because a live stream is one request that never finishes and `http.Server.Shutdown` waits for in-flight requests — a drain in the other order blocks for the whole budget and then SIGKILLs with nothing released. `-race` says nothing about it; break-check 14 does.

18. **One mechanism per invariant.** This PR's three: a client leaves the registry by exactly one route (the serving goroutine's deferred release — `StopClient` signals and does **not** remove, Ruling R6); a channel announces its ending in exactly one place (`run`'s deferred `emitStop`, Ruling R9); and a client is registered by exactly one function (`addClient`, which Ruling R4 restores). Task 0 counts all three, Task 10 counts them again, and both name the lines.

19. **The borrowed-slice contract is asserted, not enforced.** `Ring.Read` returns slice headers into the ring's own arrays. This PR's one new reader of ring internals, `Ring.Sample`, copies out three scalars per chunk (index, length, first byte) and hands back no slice at all, which is why it needs no contract.

20. **This is the PR that widens the endpoint.** Constraint 20 of 2c-3 through 2c-7 said "the single-channel `GET`/`DELETE`, the client `DELETE` and `advance` are 2c-8's". They are here. `GET /proxy/relay/channels` — the collection — gains **no field and no route**: the list payload is untouched, and row 14 is an asymmetry precisely because the two endpoints differ.

21. **Every error-typed argument to a formatting or logging call in `relay/` passes through `redact.Error`, or carries `// credential-logging: ok - <reason>`.** `scripts/check_go_credential_logging.sh relay` reports the module clean at zero findings after this PR, across **twelve** packages (eleven plus the new `drain`). This PR adds **two markers** — the `encoding/json` type error in `writeJSONStatus` and `http.Server.Shutdown`'s context error in the drain — and three `redact.Error` calls.

22. **Every line the stand-in writes to stderr came out of a real ffmpeg**, or is declared where it is written with the reason. This PR adds **none**.

23. **The real-ffmpeg test fails rather than skips when `CI` is set and ffmpeg is absent.** This PR adds **no real-ffmpeg test**: nothing here is about what a transcoder produces.

24. **`Pdeathsig` is Linux-only by build tag, and its pin runs on Linux.** Unchanged; this PR spawns nothing new.

25. **The stand-in is the test binary re-executed, and the trampoline is one per package.** `relay/httpapi` already has one; this PR adds none. `relay/drain`'s tests spawn nothing.

26. **The `Pdeathsig` and SIGKILL tests assert a mechanism, not an outcome.** Unchanged, and Ruling R10 applies the same principle to the emitter's closed-channel guard: `net/http` RECOVERS a panic in the goroutine serving a request, so a test asserting an outcome cannot see it and the pin is on the mechanism.

27. **A test's `Tuning` is built on `testTuning()` or `transcodeTuning()`, never as a bare literal.** This PR adds no test in `relay/channel`; the `httpapi` tests reach their settings through `rigSettings`, which starts from `relaytest.EffectiveProxySettings()`.

28. **A test that measures a timeout takes its clock BEFORE the thing it measures starts.** Three tests here measure one, and all three do: `TestTheDrainRaisesTheGateFirstAndFlushesTheEventsLast`, `TestADependencyThatHangsDoesNotOverrunTheBudget` and `TestTheDrainStopsTheChannelEndsTheClientAndFlushesTheEvents` each take `started := time.Now()` **before** `drain.Run` is called, never inside it.

29. **Compressed thresholds are on the wire, never patched.** The drain's budgets are not on the wire and are passed as `Deps` fields instead, which is the same principle one layer up: a test supplies its own budget rather than editing the constant.

30. **A break-check that reddens on a different clause than predicted is recorded with the clause that fired.** Two of this plan's twenty-four did, and both are in the table.

31. **Widen a sample window, never lower an asserted count.** Two tests here wait fifteen seconds for a registry to change; if a slow host makes one flaky, raise the fifteen and never weaken the assertion. **Paid for twice in this PR**, both times the other way round: break-checks 9 and 10 stayed GREEN because a test read too FEW bytes and configured too few cases, and the fix was to widen the read and add rows — not to relax anything.

32. **Every event this relay raises is one Python raises, with the same `type` and the same `details` keys.** The vocabulary is `core/models.py`'s `SystemEvent.EVENT_TYPES`; an unknown type is rejected by `core/relay_events.py:apply_event_batch` and counted, not raised, so a misspelling would be a silent loss. This PR raises exactly four new types — `channel_start`, `channel_stop`, `client_connect`, `client_disconnect` — and with them the relay raises the complete set: 2c-5's five plus these four. **Nothing is owed to a later PR.**

33. **The fake control plane is one server answering four routes by path suffix**, and a test that asserts a request count names the route (`RequestsTo("/next-source")`). **This PR made that rule load-bearing**: `channel_start` posts to `/api/relay/events` on every tune, so five existing assertions that counted requests across the whole fake became 2-instead-of-1 and were narrowed to the route (Task 4 Step 5).

34. **A shared resource's lifetime is never a client's request context.** Unchanged. The drain's own contexts are `context.Background()` with a deadline, never a request's.

35. **A sharing claim is counted in SPAWNS, never in registry entries.** No sharing claim here.

36. **A break-check's patch and its revert must target a string that occurs exactly once in the file.** Every patch in § Break-check is applied by a script that **asserts its anchor is present and unique** and prints `APPLIED <path>`. Paid for here: break-check 2's revert string was a substring of a line elsewhere in the same function, the revert's uniqueness assertion fired mid-run, and the file was left patched — which is why the harness asserts on the revert as well as on the patch, and re-runs the package after every revert.

37. **A real-ffmpeg fMP4 test needs at least eight seconds of asset** (Amendment A6.6). No test here uses real ffmpeg.

38. **Nothing in this PR reads or writes the `output_*` Redis keys, and nothing reinstates an owner lock.** Unchanged.

39. **The Output Profile argv carries the COMMAND as element 0 and `stream_profile.argv` does not.** Unchanged, and it matters once here: the advance body's `stream_profile` is a `StreamProfileRef`, so its command is in its own field and `transcodeSource` reads both — the same two functions the tune uses (Ruling R5).

40. **Three states on the wire, not two.** Unchanged; this PR adds no fourth.

41. **A pass-through stand-in cannot pin which ring a client read.** No test here is about which ring.

42. **A substring assertion pins nothing when the string has more than one source.** Every assertion here is on a decoded JSON value, a status code, a registry field or an `errors.Is`, never on a message substring.

43. **`relay/output`'s `fmp4.go` holds the shared pipeline and is not renamed.** Unchanged.

44. **THE DETAIL ENDPOINT RENDERS FROM MEMORY AND HAS NO FALLBACK.** `get_detailed_channel_info` fills `stream_name` and `m3u_profile_name` from an ORM lookup when the metadata hash has none (`channel_status.py:71-79`, `:97-114`). The Go relay cannot, and 2b-1 put both names on the `next-source` answer so the case is unreachable in practice. Row 18's Go answer is therefore **absent**, stated as a divergence (Ruling R7) and pinned by `TestTheNamesComeOffTheWireAndAreAbsentWhenTheAnswerCarriedNone`.

45. **THE BOUND TOKEN SIGNS THE BODY, AND THE GATE MUST READ IT.** `internal_auth.py:126-152` signs `[context, METHOD, FULL_PATH, timestamp, sha256(BODY)]`. Every route behind `RequireInternal` before this PR was a `GET` or a bodyless `DELETE`, so verifying against `nil` was right by accident; `POST …/advance` is not, and neither is `POST /_dispatcharr/authorize-internal` on the Django side. Ruling R3.

46. **THE DRAIN'S BUDGETS ARE GO-SIDE CONSTANTS, AND THAT IS NOT AN EXCEPTION TO CONSTRAINT 13.** Constraint 13 is about values an operator changes in the UI and Django reads through `ConfigHelper`. These describe **this process's shutdown against this deployment's supervisord configuration**, which ships in the same image as the binary. They are derived from `docker/supervisord.d/relay-go.conf`'s `stopwaitsecs=20`, they carry that derivation in their doc comments, and `TestTheBudgetFitsInsideSupervisordsStopWindow` pins the arithmetic — including the margin — rather than the three numbers.

47. **NO IDENTITY-BEARING MATERIAL TRAVELS AS A HEADER ON THE AUTHORIZE ROUTE.** Not the `Authorization` header, not the cookie, not the API key, and not the internal-principal question. The bound token signs no header, so a captured `X-Dispatcharr-Internal-Request` for that path would otherwise stay valid for 120 seconds against any combination of forwarded values. The question is the POST body, in full, so `sha256(body)` binds it. Spec § The contract's M-R3-1 and its `internal` fix.

48. **`internal` IS A BODY FIELD AND NEVER THE TRANSPORT'S OWN HEADER.** `IsInternalRelay` requires the relay to send `X-Dispatcharr-Internal` on this very POST, and `authorize_stream` reads `request_is_internal` off the request it is handed: a view that passed its incoming request through would return `INTERNAL_PRINCIPAL` for **every** tune in **every** nginx-less deployment, before any channel flag, adult filter, profile membership or credential check ran. The Django view builds the request it authorizes **entirely** from the body and inherits nothing from the transport request.

49. **THE SESSION PRINCIPAL IS RESOLVED FROM THE SESSION STORE, AND THE TEST ASSERTS THE IDENTITY.** `@api_view`'s own `dispatch` sets `request.user` to `AnonymousUser` before `authorize_stream` runs, which is why `_session_user` calls `django.contrib.auth.get_user(request)` instead. A view that forwarded the cookie and read `request.user` downgrades a session viewer to anonymous with **no error**: a hidden channel still 403s, so the visible half looks right, while an ordinary channel streams a 200 with real bytes and `user_level`, Channel Profile membership, adult filtering and the per-user stream limit have quietly stopped applying. **A status-only assertion cannot see it.** The assertion is `X-Relay-User`.

50. **A DENIAL REACHES THE VIEWER AS ITSELF.** `authorize_error_response`, never `subrequest_error_response`. The 403 collapse exists only because `ngx_http_auth_request_module` can transport a 2xx, a 401 and a 403 and nothing else; a direct POST has no such constraint, and collapsing would hand the Go relay a 403 where production answers 404 for an unknown channel or 429 for a user over their stream limit.

51. **`/healthz` IS LIVENESS AND `/readyz` IS READINESS, AND THE DRAIN SEPARATES THEM.** `/healthz` answers 200 throughout the drain, because a supervisor that restarted the process mid-drain would defeat it. `/readyz` answers 503 from the moment the gate goes up. Neither probes the control plane: a relay that deregistered during a Django outage would drop viewers whose streams need nothing from Django (Ruling R12).

52. **THE `HEALTHCHECK` IS ROLE-AWARE OR IT IS WRONG.** The image runs four program sets and only the `all`, `all-dev` and `relay` rungs start `relay-go`. `HEALTHCHECK` runs as a fresh process with the **container's** environment, which carries `DISPATCHARR_ROLE` only when the operator set it explicitly — the default `entrypoint.sh` applies is invisible to it. Hence the one line that writes the resolved role to `/run/dispatcharr-role`, and a probe that exits 0 for a role with nothing to check.

53. **EVERY DOCUMENT APPENDIX IS A `git diff` HUNK, CAPTURED AGAINST THE SEED SHA AND ROUND-TRIPPED.** Not prose, not a "replace this paragraph with", not a quoted after-text. This applies to `CLAUDE.md`, `docs/relay-parity-matrix.md` and the spec's Amendment and Done-log rows exactly as it applies to a Go file. **Two failures paid for it.** A reviewer applying a prose matrix instruction — "append one reference inside the same cell" — produced a **six-cell row**, which `e2e/tests/guards/parity-matrix.spec.ts` rejects. And a prose `CLAUDE.md` "after" paragraph would have **silently dropped a sentence a previous PR had added to the same paragraph**, because the quoted text was written against an older copy and nothing compares the two; `git apply` refuses when its context has moved, and prose cannot. Round-tripped means: extracted back out of the finished plan document and checked with `git apply --check`, which is Task 9 Step 0 and Task 10 Step 6. **And re-captured on re-seed** — Appendix AN's spec hunk is anchored where A6 ends and 2c-7 inserts A7 there, so it is *expected* to be stale against the merged tree.

54. **GATE 2 IS A GATE THIS PR CAN FAIL WITH EVERY DJANGO LABEL GREEN, AND IT IS RUN, NOT REASONED ABOUT.** Five of the Python files this PR edits — `authorize_views.py`, `next_source.py`, `relay_client.py`, `relay_serializers.py` and `live_proxy/views.py` — are inside `scripts/coverage_live_path.coveragerc`'s module list, and `scripts/coverage_live_path.floor`'s `missing` is a **MAXIMUM**, not a target: **one uncovered new statement raises it and fails `backend-tests.yml`'s `Coverage gate` however green `apps.proxy.tests` is.** 2c-7's CI found this the expensive way — ~28 statements added to two in-scope files, its own label green, the gate failing at missing=1529 against a floor of 1525.

    So: run it.

    ```bash
    cd <your worktree>
    for s in proxy liveproxy channels; do
      DISPATCHARR_TEST_CONTAINER=<yourname>-$s DISPATCHARR_TEST_DB_VOLUME=<yourname>-$s-db \
        .claude/hooks/start-test-container.sh
    done
    COVERAGE_ISOLATED_PREFIX=<yourname> COVERAGE_ISOLATED_OUT=/tmp/cov \
      bash scripts/coverage_live_path_isolated.sh --gate
    ```

    One label per container, `COVERAGE_CORE=sysmon` (the script sets it; the default C tracer drops every statement executing after a `gevent.sleep()` and its figure is not comparable in either direction). **A regression is attributed per file and then per line from `live-path.json`, and covered with a real test in one of the gate's three labels** — `apps.proxy.tests`, `apps.channels.tests`, `apps.proxy.live_proxy.tests`. **The floor is never raised.** The per-line attribution is one command and it is what turns "the gate failed" into "this statement needs a test":

    ```bash
    python3 - <<'PY'
    import json, subprocess, re
    d = json.load(open('/tmp/live-path.json'))   # docker cp it out of the proxy container
    for f in ('apps/proxy/authorize_views.py', 'apps/proxy/next_source.py',
              'apps/proxy/live_proxy/views.py'):
        diff = subprocess.run(['git','diff','-U0','--',f], capture_output=True, text=True).stdout
        added = set()
        for m in re.finditer(r'^@@ -\S+ \+(\d+)(?:,(\d+))? @@', diff, re.M):
            start = int(m.group(1)); n = int(m.group(2) or 1)
            added.update(range(start, start + n))
        missing = set(d['files'][f]['missing_lines'])
        print(f, sorted(added & missing))
    PY
    ```

    **Measured on this PR's own tree: `missing` 1497-1498 against the floor's 1525, `statements` 8073 -> 8202, and ZERO added-and-missing lines in all three files.** `modules=` and `rcfile=` are unchanged, because this PR adds no file the rcfile includes and does not edit the rcfile; `statements` moving is recorded provenance and is not compared. **Nine statements were uncovered on the first measurement and all nine are now tested** — § Break-check's own last section names them, and one of them was not a coverage gap at all but a live defect (Ruling R13).

### The six ways a Go test can be green and meaningless

Every test this PR adds is bound by all six, and every task that adds an assertion ends with a **break-check**: patch the defect in, watch the test go red *for the right reason*, revert. **A break-check that does not go red is a finding, not a formality** — four of this plan's twenty-four did not, and all four produced better tests or deleted dead code (§ Break-check, rows 2, 3, 9 and 10, plus 3b which deleted an unreachable branch).

1. **The tautological oracle.** Every expected value is a literal, a Python line, or output from the other implementation: the detail payload's shape is a golden rendered by `RelayChannelDetailSerializer`; `pythonFloat`'s ten expected strings were printed by a `python3` in the repo's own test container and pasted in; `humanBytes`'s seven are `channel_status.py:141-149` read arm by arm; `OwnerUnknown` is `:45`; `XCStreamIDPattern` is `dispatcharr/utils.py:115`.

2. **A pin that supplies the default pins nothing.** The detail golden carries a fully populated channel **and** the row-18 test carries a nameless one; the counters test carries a TS client **and** an fMP4 one; the `internal` test carries a marked request **and** an unmarked one; the denial test carries four statuses **and** both body branches; the XC format test carries four extensions, two of which must leave the hop's answer standing.

3. **A test can go hollow without changing.** Every break-check below names the edit and the message that appeared. And five existing tests went hollow in exactly this way when `channel_start` started posting: they counted requests across the whole fake, and the count moved from 1 to 2 without a line of theirs changing. Task 4 Step 5 narrows all five to the route.

4. **A fixture that patches away the subject.** **The scar of this PR.** Break-checks 2 and 3 removed `pythonFloat`'s decimal point and `describeBufferStats`'s `keys_missing` assignment and the golden test stayed **GREEN** — because the golden's fixture is a Go struct literal that supplies both, so the two functions that do the work were exercised by nothing. `detail_builder_test.go` (Task 2) drives them directly and both break-checks then redden.

5. **A substring assertion pins nothing when the string has more than one source.** Constraint 42.

6. **A true positive for a false reason.** The advance test asserts four things together — the alternate upstream is contacted, the listed `stream_id` moves, the client is still fed, and the event names the new stream — because any three are satisfiable without a switch. The client-DELETE test asserts that one client left **and** the other is still being served, because a handler that tore the whole channel down satisfies the first alone.

### Working rules

- Run the four checks after every task (Constraint 16), then `scripts/check_go_credential_logging.sh relay` and `scripts/check_go_stdlib_only.sh relay` (Constraints 21 and 3). Both scripts take the module directory **relative to the repo root** and must be invoked from there, not from inside `relay/`.
- **Run this PR's own test subset at least eight times consecutively under `-race` before Task 8 is committed, the whole module three times under `-race`, AND three times WITHOUT it, before Task 10.** The no-race rounds are not ceremony: this PR's one flaky test was green 8/8 under `-race` and failed roughly half of all no-race rounds, because the detector's own overhead was hiding a latching wait (Constraint 55). Measured on the re-seeded tree: subset 8/8, whole module 3/3 under `-race` and 3/3 without, ~90s per round (`relay/httpapi` dominates).

55. **A WAIT ON A LATCH THAT FIRES EARLY IS A FLAKE `-race` WILL HIDE FROM YOU.** `TestAnAdvanceSwitchesTheChannelAndKeepsTheClientFed` waited for `listedStreamID == 2` and then asserted the alternate upstream had been contacted. `applySwitch` sets the channel's `SourceInfo` on the **handler's own goroutine**, so that condition is true the instant the advance returns — before the run loop has taken the parked source and dialled anything. Under `-race` the extra instrumentation let the dial land first and the test was green 8/8; without it, it failed about half the time. **Wait on the thing the test is about** — here, `alternate.Requests() >= 1` — and assert the cheap derived fact afterwards, when it is no longer a latch that fires early. Constraint 31 still holds in the other direction: widen the window, never lower the count; nothing here weakened an assertion, the wait moved to the right signal and a second assertion was added.
- Stage and commit in separate Bash calls; write commit messages to a file and use `-F`.
- Every commit message ends with the attribution lines this session was given.
- **Every Go file in this plan has been built, vetted (native, `GOOS=linux`, `GOOS=darwin`), race-tested and linted at zero findings before this plan was written**, in a scratch module seeded as § Sequencing describes; every Python change has been run in a private container across all sixteen backend labels. Where you find a discrepancy, **your tree is the fact and this plan is the claim — stop and report it** (Task 0 Step 0).

---
## Rulings

### R1 — The XC live roots have no owning PR, and 2c-8 builds them

§ Stage 2c's "**It serves**" paragraph names `GET /proxy/ts/stream/<id>`, **the XC live roots**, the five control routes, `/healthz` and `/readyz`. The nine-PR table names the roots in **no row**. Walked, row by row: 2c-2 is "the Proxy stream-profile architecture only"; 2c-3 fan-out; 2c-4 ffmpeg; 2c-5 failover and Redirect; 2c-6 fMP4; 2c-7 Output Profiles; 2c-9 the coverage ratchet; 2d the cutover, which *routes* them and cannot *build* them. Grepped across all six merged plans and 2c-7's draft: the only hits for `stream_xc` are in 2c-1's allowlist prose, explaining why a *Django* symbol is not the relay's problem.

**The parity matrix does not compensate.** Row 15 is the roots' only row and it was never marked `owed:` by anyone — it carried a Python pin from 2a and no PR was named to give it a Go one. This is the same shape as 2c-1's Finding F2 about Redirect, found the same way: by walking the table against the prose rather than by trusting either.

**Ruled: 2c-8 builds both roots, as a WRAPPER around the TS handler.** `stream_xc` authorizes once and passes its decision into `stream_ts` (`views.py:862-889`), so an XC tune is not authorized twice and mints no second client id — row 15. The Go shape is the same one: `XCHandler` validates the path against `XC_STREAM_ID_PATTERN`, applies the extension's output-format override, and calls `StreamHandler`'s own function. The channel it serves is the one the hop resolved (`X-Relay-Channel`) or the one the dev fallback's decision named, **never the numeric path id**, which this relay cannot map to a uuid without the ORM query D2 forbids. The extension is the one thing the path contributes and it contributes it to the *format*: `.mp4` forces fMP4, `.ts` forces MPEG-TS (`:872-878`), overriding the hop — because `resolve_output_format`'s `force` parameter is one the hop deliberately never passes ("the hop authorizes a URI and the override is a property of the view's call", `apps/proxy/authorize.py:236-246`).

**Cost, stated:** one 72-line file, one four-line edit to the routing table and 158 lines of test. **Cost of not doing it:** row 15 cannot close, so the matrix cannot reach 100% Go-pinned, so 2c-9's own gate ("the matrix's Python test-reference column gains its Go counterpart on every row") cannot be met — and 2d would discover at cutover that nginx has two live locations with nothing behind them.

### R2 — The advance route needs the stream profile, and Django sends it

`RelayAdvanceRequestSerializer` (`apps/proxy/relay_serializers.py:187-222`) carries `url`, `user_agent`, `stream_id`, `m3u_profile_id`, three names and `reset_tried`. That was sufficient while the relay rebuilt the ffmpeg command itself: `StreamManager.update_url` keeps the manager's own `stream_profile` and `transcode` flag across a switch and re-substitutes `{streamUrl}` at spawn time (`input/manager.py:1462-1540`).

**Amendment A4.1 took that away.** Django builds `stream_profile.argv` for *each Source's own URL, user agent and object*, "so the Go relay carries no word splitter and no substitution table". A Go relay handed a url alone therefore has **nothing it can spawn**: the argv it holds embeds the URL it is switching away from.

**Ruled: the serializer gains three fields — `stream_profile`, `ffmpeg_stream_profile` and `transcode`** — rendered by the same `StreamProfileRefSerializer` the `next-source` answer uses, which are the three of `SourceSerializer`'s fields the flat fields do not already duplicate **and that the relay needs**. `slot_reserved` is in that set too and is deliberately NOT sent: Django moved the provider slot when it resolved this candidate (Phase 1 PR 6), and the relay releases only what it reserved, so an advance that claimed a reservation would make the channel's own release double-release — `advanceSource` sets it false and says so. `m3u_profile_id` and `m3u_profile_name` ARE duplicated by flat fields and so need nothing. `relay_client.advance()` forwards them; `change_stream` and `next_stream` each already hold the resolved `stream_info` dict that carries all three. They are `required=False` on the serializer because the **Python** relay's handler ignores them and both relays run through the whole of stage 2c (D3); the **Go** relay refuses an advance with no `stream_profile` with a 400, which is what DRF answers for a missing required field anyway.

**One producer had no profile to send, and it now builds one.** `change_stream` accepts a bare `url` with no `stream_id` — reachable only by a hand-crafted admin call, never by the UI, whose `switchStream` always sends `stream_id` (`frontend/src/api.js:3314-3322`) — and that path resolves no `Stream` row. It asks the **channel** for its own effective profile through a new `next_source.channel_stream_profile_ref()`, which is the same profile the Python relay uses there. A channel identifier that names no row leaves the three fields unset and the Go relay answers 400, which is the truth; the lookup is wrapped in `except Http404` so this adds no 404 to a path that never had one.

**The alternative considered and rejected:** a nested `source` object carrying the whole answer shape. It would have duplicated `url`, `user_agent` and `stream_id` in one body — the stale-duplicate-of-the-truth shape 2c-2's R5 refused — for the convenience of one decoder.

### R3 — `RequireInternal` was verifying the signature against an empty body

`internal_auth.py:126-152` signs five fields and the fifth is `sha256(BODY)`. 2c-3's `RequireInternal` passes `nil` where the body goes:

```go
control.VerifyInternalRequest(secret, r.Header.Get(control.HeaderInternalRequest),
    r.Method, r.URL.RequestURI(), nil, now())
```

Every route behind that gate until now was a `GET` or a bodyless `DELETE`, so `nil` and the real body hash identically and the gate was **right by accident**. `POST …/advance` carries a body, and the gate 403s every call — measured, on the first run of `TestAnAdvanceSwitchesTheChannelAndKeepsTheClientFed`, before a line of the handler was suspected.

**Ruled: the gate buffers the body, verifies against it, and hands the handler a reader over the same bytes.** Bounded at `MaxInternalBody` (1 MiB) with a 413 beyond it: the largest body any of these five routes carries is a resolved source, so that is three orders of magnitude of headroom, and the bound exists because an unauthenticated caller must not be able to make this process buffer an arbitrary body *before* the signature is checked. A read error leaves the (truncated) bytes to fail the signature check rather than being reported separately — a truncated body cannot match, and one refusal is better than two.

### R4 — The first client of every channel bypassed `addClient`

`Manager.publish` built its registry as a map literal:

```go
clients: map[string]*Client{client.ID: client},
```

so the first client of a channel never ran `addClient`. That was harmless while `addClient`'s only job was the duplicate-id check — the literal cannot produce a duplicate. This PR gives `addClient` two more jobs (install the transfer counters, install the stop signal), and the literal skips both: **the first client of every channel had a nil meter and could not be stopped by id, while the second and every later one could.**

Found by `TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming`, whose `DELETE` reported `locally_processed: false` about a client the registry was listing. Not by review.

**Ruled: `publish` builds an empty map and calls `addClient`.** One mechanism (Constraint 18), and the break-check is exact: restore the literal and that test reddens on the same line it first did.

### R5 — The operator switch reuses the TUNE's source builder, not one assembled from the request

`sourceBuilder` holds three tune-time facts: which of the three Stream Profile architectures this channel plays, the defaulted user agent (`input/manager.py:73`), and the upstream read size (`CHUNK_SIZE`). An advance body carries none of them, and the first two are not the advance's to decide: Python's `StreamManager` keeps its own `transcode` flag and stream profile across `update_url`, and `next_source.py:609-622` is explicit that the answer's `stream_profile` is the **channel's**.

**Ruled: `builderFor(ch)` type-asserts the channel's own `Resolver` to `*resolver` and reads its `build` field.** `Channel.Resolver()` is exported for this and says so in its doc comment. A channel with no resolver — a test shape — answers the advance with `success: false` rather than assembling a second builder from the request, because a second builder is free to disagree with the first.

### R6 — `StopClient` signals and does NOT remove

`ChannelService.stop_client` does two things: it `SETEX`es the client's stop key, which the generator's loop polls (`services/channel_service.py:665-673`), and it removes the client from the worker's own `ClientManager` when it finds one there (`:692-698`). The generator's cleanup then removes it **again** (`output/ts/generator.py:643`'s `if self.client_id in client_manager.clients`), so Python has two removal mechanisms and the registry is the same shape either way.

**Ruled: the Go relay keeps one.** `StopClient` closes the client's stop signal and returns whether a client of that id was registered; the serving goroutine's deferred release is the single route by which a client leaves. This matters more than tidiness: `release` is also what decides whether the channel was left idle, and a second remover would let a `DELETE` tear a channel down while its client goroutine was still writing.

`locally_processed` is then "a client of that id was signalled", which with one process is the same question `ClientManager` answers there. `event_published` is always `false` (D2 deletes the pub/sub) and `stop_key_set` is the signal's own success, because the signal lives **on** the client and cannot exist without one — where Python attempts the `SETEX` *before* it looks the channel up, so its `stop_key_set` is true even for a channel that does not exist.

### R7 — The detail endpoint renders from memory, and three of its fields are unreachable in BOTH relays

`get_detailed_channel_info` is 390 lines and reaches Redis and the ORM repeatedly. Walked field by field, three groups do not port:

**Two fields NOTHING WRITES, in either relay.** `source_bitrate` has no writer anywhere in the tree — `channel_status.py:359` is its only reference beside the constant declaration. `ffmpeg_bitrate` is read under `ChannelMetadataField.FFMPEG_BITRATE` (`"ffmpeg_bitrate"`) and the only writer, `input/manager.py:1269`, writes `FFMPEG_OUTPUT_BITRATE` (`"ffmpeg_output_bitrate"`) — **two different strings**, `constants.py:90-91`. So the operator's output bitrate never reaches this payload in either relay. Reproduced as absences per D5 and filed, the same shape as `logo_id` on the list endpoint.

**The buffer-health walk's Redis half.** `latest_chunk_ttl` is a TTL on a chunk key; `diagnostics.all_buffer_keys` and `.total_buffer_keys` are a `SCAN` of the buffer keyspace; `error`/`diagnostics.exception` are that walk's own `except` arm. None has an in-memory analogue, and reporting the ring's age bound as a TTL would name a mechanism that is not the one doing the work. **Everything else ports**: `chunks`, `avg_chunk_size`, `recent_chunk_sizes`, `keys_found`, `keys_missing`, `total_sample_bytes`, `estimated_ts_packets`, `is_ts_aligned` and `diagnostics.first_chunk` all come off `Ring.Sample`. `keys_missing` keeps its meaning and changes its cause: an expired key there, an evicted chunk here.

**The two ORM name fallbacks.** Constraint 44. Row 18's Go answer is **absent**.

**And one field type nobody would guess.** `keys_missing` must be **present and empty** on a fully resident sample, because `channel_status.py:275` assigns it inside the same `if chunk_sizes:` arm as `keys_found`. A `[]uint64` with `omitempty` drops it and without `omitempty` renders `null` in the arm where Python omits it entirely — so it is a `*[]uint64`, alone among the four slice fields, and the golden caught it.

### R8 — The three byte counters are a PER-FORMAT asymmetry, not a per-client one

`RelayDetailClientSerializer` declares `bytes_sent`, `avg_rate_KBps` and `current_rate_KBps` `required=False`, and `get_detailed_channel_info` sets each only when the client's hash has the key (`:202-213`). **Which clients have them is decided by the output format.** The TS generator writes `chunks_sent`, `bytes_sent`, `avg_rate_KBps`, `current_rate_KBps` and `last_active` on a 1-second throttle (`output/ts/generator.py:508-519`); the fMP4 generator writes **`last_active` and nothing else** (`output/fmp4/generator.py:288-295`) — `emit_event` and `hset` each appear once in that file.

**Ruled: the absence gets a mechanism rather than a format check in the renderer.** `Client.Sent(n, at)` is what a TS client calls and `Client.Touch(at)` is what an fMP4 client calls; the renderer emits the three fields when `Sends > 0`, which reproduces both the fMP4 absence and the not-yet-written TS one.

**Two stated divergences.** Go's counters are live where Python's are a 1-second-throttled snapshot, so a TS client carries them from its first chunk rather than from its first flush; and `last_active` is the true last write rather than the last flush. Both are fresher, neither changes a shape.

### R9 — `channel_stop` is raised from the one place a channel ends

Python raises it from `ProxyServer.stop_channel`'s owner branch (`server.py:1827`, `:1842`), which the admin stop, the last-client disconnect sweep and the orphan sweep all reach, and which a channel whose sources are exhausted reaches through the cleanup thread.

**Ruled: `Channel.run`'s deferred `emitStop`.** One mechanism where Python has several, and the set of endings that announce themselves is the same or slightly larger — a divergence in the safe direction, since an ending that raised nothing would be a missing event rather than a spurious one.

**Its position among the defers is load-bearing and easy to get wrong.** It must run **before** `close(c.done)`: `stop()` returns the moment `done` closes, so an emit after it races the SIGTERM drain's own emitter flush and loses the last `channel_stop` of a shutdown — the one it most matters to keep. Deferred calls run last-in first-out, so the declaration order is `releaseSlot`, `close(done)`, `emitStop`, `ring.Close`, `stopOutputs`, and the execution order is the reverse.

### R10 — The emitter's closed-channel guard is pinned on the MECHANISM, because net/http hides the outcome

The drain closes the emitter while a client goroutine is still unwinding and raising `client_disconnect`: a send on a closed channel, which panics. A test's own cleanup then closes an emitter the drain already closed: a second close, which also panics. Both are real and both are reachable from Task 8's own sequence.

**The first one is invisible to a test that asserts an outcome.** `net/http` **recovers** a panic in the goroutine serving a request: the drain test printed `http: panic serving 127.0.0.1:…: send on closed channel` and **passed**. A recovered panic that kills one viewer's connection and nothing else is exactly what an outcome assertion cannot see — break-check 18 stayed green against the drain test until the pin moved.

**Ruled: `Emit` drops an event raised after `Close` and `Close` is idempotent, and `control/events_test.go` pins both directly.** Dropping is the disposition this type already has for a full queue and the one `control_plane.py` states ("an event raised while the control plane is down is LOST, not queued").

### R11 — The drain's order is the design, and the channels must stop before `Shutdown`

`http.Server.Shutdown` waits for in-flight requests. **A live stream is one request that never finishes.** A drain that called `Shutdown` first would block for its whole budget and then be SIGKILLed with every provider slot unreleased and every `channel_stop` undelivered.

**Ruled, five steps, each there because the next would be wrong without it:** raise the gate (new tunes 503, `/readyz` 503); serve the connected viewers for `ClientGrace`; stop every channel concurrently, which is what ends the client goroutines — each ring closes, each `serveClient` sees `ErrClosed` and returns, each output pipeline is stopped by `run`'s defers, each slot is released; shut the server down, which is now immediate; flush the emitter **last**, because steps three and four are what raise the events it exists to deliver.

**`Manager.StopAll` became concurrent for the arithmetic.** `Stop` waits up to `StopWait` (5s) for one channel's source goroutine, so a sequential walk costs N × 5s — ten channels is fifty seconds against a twenty-second window. Concurrent, the sweep costs `StopWait` however many channels there are.

**And the events budget is RESERVED, not residual.** Steps 2–4 share one deadline; step 5's budget is subtracted from the total up front, so a slow teardown costs the shutdown its wait and never costs the events their delivery. Clamped to a third of the budget so a caller cannot reserve more than it has.

### R13 — `source=` alone does not rename an input field, and the hyphenated header never arrived

`AuthorizeInternalHeadersSerializer` declares the third credential header as

```python
x_api_key = serializers.CharField(source="x-api-key", ...)
```

because `x-api-key` is not a Python identifier. **`source=` is the wrong half of the mapping.** DRF reads INPUT by a field's NAME — `x_api_key` — and uses `source` only to decide where the value lands in `validated_data`. So a body carrying `"x-api-key"`, which is what § The contract specifies and what the Go relay sends, deserialized to `None`; `HTTP_X_API_KEY` was never set on the synthesised request; and **an API-key client would have resolved to anonymous in the nginx-less shape and to its real user in production** — the exact cross-shape divergence D5 exists to prevent, and the one this third field was added to close.

**Ruled: `to_internal_value` maps the wire name onto the field name, and `source=` keeps `validated_data` hyphenated for `_synthetic_request`.** Three lines.

**Found by a coverage test, not by review**, and that is the part worth keeping. The first Gate 2 measurement listed `authorize_views.py:501` — the `HTTP_X_API_KEY` assignment — among nine uncovered new statements. Writing a test to cover it is what produced the 200 where a rejected key must give 401. Every earlier reading of this code, including the one that wrote § The contract's own three-field justification into the docstring, had looked straight past it: the declaration *names* the wire key, on the line above the comment explaining why the wire key matters.

**And the test that caught it asserts the right thing.** A valid key proving a 200 would have been the weaker shape — it needs a fixture whose own plumbing can fail — where a **rejected** credential must answer 401 (parity-matrix row 30's own distinction: rejected is refused, merely declined falls through to anonymous). A 401 is positive evidence the header reached `_drf_user`'s union; the anonymous 200 in the same test is what stops "this view 401s everything" being the reason.

### R12 — `/readyz` does not probe the control plane

The tempting implementation asks Django whether it is reachable and reports unready when it is not. **Ruled against.** At stage 2d nginx routes the live locations to this process; a relay that marked itself unready during a Django outage would be taken out of rotation — and a running stream needs nothing from Django once it is running (`CLAUDE.md` § Operationally: stopping `api-uwsgi` "does not disturb a running stream"). Deregistering would turn a degraded new-tune path into a total outage for viewers who were fine.

**What it reports instead:** whether this process is draining, and how many channels and clients it holds. The counts are what make it a report rather than a second liveness probe — an operator watching a rolling restart reads them to see the channels fall to zero, and a body that only ever said `"ready"` would be 2c-1's static 200 under a new name, which is exactly what 2c-1 refused to wire a `HEALTHCHECK` to. The control plane's reachability is reported where it belongs: in the emitter's one-line-per-transition log.

---

## File Structure

**Go, created — 20 `.go` files and one generated JSON fixture, 21 in all.** The table's rows are not a count: the test row below is eight files, and the appendix list (`Appendix A` … `Appendix AQ`) is the authority. **Go, modified: 17.**

| File | Responsibility |
|---|---|
| `relay/buffer/sample.go` | `Ring.Sample(n)`: the diagnostic shape of the n newest resident chunks, for the detail endpoint's buffer walk. No slice leaves the ring. |
| `relay/channel/clientstats.go` | `ClientStats` and the per-client meter. `Sent` for a TS client, `Touch` for an fMP4 one (R8). |
| `relay/channel/advance.go` | `Channel.Advance` — the operator switch — and `ExcludedStreamIDs`. |
| `relay/control/authorize.go` | `Client.Authorize`: the dev fallback's HTTP call, its request and decision types, and `Denied`. |
| `relay/drain/drain.go` | The SIGTERM sequence, its three budgets and their derivation. |
| `relay/drain/drain_test.go` | The budget arithmetic against supervisord, the order, and the hang. |
| `relay/httpapi/detail.go` | `GET /proxy/relay/channels/{id}` and its `?fields=state` form, plus the `DELETE` dispatch. |
| `relay/httpapi/control.go` | `stopResponse`, `ClientHandler`, `AdvanceHandler`, the shared JSON writers. |
| `relay/httpapi/health.go` | `Lifecycle` and `ReadyHandler`. |
| `relay/httpapi/clientevents.go` | `client_connect` and `client_disconnect`, and the asymmetry between them. |
| `relay/httpapi/authorize.go` | `authorizeTune`, `decisionHeader`, `writeAuthorizeFailure`. |
| `relay/httpapi/xc.go` | The two XC live roots (R1). |
| `relay/httpapi/testdata/channel_detail.json` | The golden, rendered by Django's own serializer. |
| `relay/httpapi/{control,advance,events,authorize,xc,drain,detail_golden,detail_builder}_test.go` | The tests. **Eight files in one row**, which is what made the heading above read 18 when the applied tree has 21 created. |

**Go, modified (17), named in full:** `channel/{channel,client,events,failover,manager}.go`, `control/{events,events_test}.go`, `httpapi/{channels,fmp4,server,stream}.go`, `httpapi/{fanout,server,stream,transcode}_test.go`, `internal/relaytest/controlplane.go`, `main.go`.

**Python, created (2):** `apps/proxy/tests/test_authorize_internal_view.py`, `apps/proxy/tests/test_relay_detail_payload_golden.py`.
**Python, modified (7 production and allowlist files, plus 1 existing test):** `apps/proxy/{authorize_views,next_source,relay_client,relay_serializers}.py`, `apps/proxy/live_proxy/views.py`, `apps/proxy/live_proxy/tests/zero_orm_allowlist.py`, `apps/proxy/tests/test_relay_client.py`, `dispatcharr/urls.py`.

**Docker, created (1):** `docker/healthcheck.sh`. **Modified (2):** `docker/Dockerfile`, `docker/entrypoint.sh`.

**Docs, modified (3):** `docs/relay-parity-matrix.md` (thirteen rows), the spec (Amendment A8 and the Done log), `CLAUDE.md` (two sentences).

---
## Task 0: Diff the merged 2c-7 tree against this plan's expectations

**Files:** none. This task writes nothing.

**Interfaces:**
- Consumes: the merged 2c-7 tree at `d6d71f97`.
- Produces: a go/stop for every task after it.

- [ ] **Step 0: Seed your scratch module from the merged tree, tests included**

```bash
# d6d71f97 is filled in by the orchestrator when 2c-7 merges.
cd <your worktree>
git fetch origin main
git log --oneline -1 d6d71f97

# relaytest/corpus.go locates the repo from its OWN path -- four levels above
# relay/internal/relaytest/corpus.go -- so the Python harness's fixtures must
# be reachable at the same relative depth or every package that reads the
# corpus panics. Working in the worktree itself satisfies that; a scratch
# module elsewhere needs apps/proxy/live_proxy/tests/harness/ copied beside it.
cd relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
```

Expected: all four green on the merged tree before you change anything. If they are not, **stop and report** — this plan's baseline is a green 2c-7.

- [ ] **Step 1: Check every symbol in the dependency ledger**

```bash
cd <your worktree>/relay
# The six shapes whose absence is a STOP.
grep -n 'StreamProfile  *StreamProfileRef' control/nextsource.go
grep -n 'ArgvPresent' control/nextsource.go | head -3
grep -n 'type Resolved struct' -A 12 channel/failover.go
grep -n 'clients: *map\[string\]\*Client' channel/manager.go
grep -n 'type sourceBuilder struct' -A 5 httpapi/stream.go
grep -n 'func infoFrom' httpapi/stream.go
grep -n 'build  *sourceBuilder' httpapi/failover.go
```

Expected: one hit each, and `channel/manager.go`'s client map is still the literal `map[string]*Client{client.ID: client}` — which Task 1 replaces (Ruling R4). **A `publish` that already calls `addClient` means the defect was fixed upstream: keep Task 1's change as a no-op and say so in the report.**

- [ ] **Step 2: Count the three one-mechanism invariants, and record the numbers**

```bash
cd <your worktree>/relay
# One writer of the client registry.
grep -rn 'c.clients\[' channel/ | grep -v '_test.go'
# One place a channel ends.
grep -n 'defer c.releaseSlot\|defer close(c.done)\|defer c.ring.Close\|defer c.stopOutputs' channel/channel.go
# Two writers of StateActive, still (2c-7's Constraint 18).
grep -rn 'StateActive' channel/*.go | grep -v '_test.go'
```

Expected before this PR: **four hits, two of them writes** (`addClient`'s insert at `channel.go:228` and `SetClientOutputProfile`'s update) and two reads (`addClient`'s duplicate check, `StopClient`'s lookup). **This grep cannot see `publish`'s map literal at all** — `clients: map[string]*Client{client.ID: client}` contains no `c.clients[` — which is exactly how the defect survived: the obvious census misses the third writer. **Step 1's `clients: *map\[string\]\*Client` grep is what catches it**, and the two belong together. Also expected: four defers in `run`; two writers of `StateActive`. Task 10 counts all three again.

- [ ] **Step 3: List the rows this PR owes, and expect the count**

```bash
cd <your worktree>
awk -F'|' '/^\| [0-9]+ \|/ {pin=$5; if (pin !~ /relay\//) {id=$2; gsub(/ /,"",id); print id}}' \
  docs/relay-parity-matrix.md | tr '\n' ' '
```

Expected on the merged 2c-7 tree: **`14 15 16 17 18 19 20 21 22 23 24 25 26 27 30`** — fifteen ids, of which **26 and 27 are `white-box-only`** and take no Go pin (the guard requires their `Pin` cell to be exactly that word). **Thirteen rows are this PR's.** If row 11 is in that list, 2c-7 did not close it: report it and carry on, because this PR's count is against the 28 rows that can carry a Go pin, not against 30.

- [ ] **Step 4: Confirm the two seams 2c-5 and 2c-6 left for this PR**

```bash
cd <your worktree>/relay
grep -n 'func (e \*Emitter) Close' -B 4 control/events.go
grep -n 'func (m \*Manager) StopAll' -B 4 channel/manager.go
```

Expected: `Emitter.Close`'s comment says it "is what the SIGTERM drain (2c-8) will call", and `StopAll`'s says "the SIGTERM drain that calls it in anger is 2c-8's". Task 8 is the first caller of both.

- [ ] **Step 5: Report, and stop if anything differs**

A symbol that differs from the ledger is a **stop-and-report**, never a reconciliation in passing.

---

## Task 1: `relay/channel` and `relay/buffer` — the per-client meter, the stop signal, and the switch seam

**Files:**
- Create: `relay/buffer/sample.go` (Appendix A), `relay/channel/clientstats.go` (Appendix B)
- Modify: `relay/channel/client.go` (Appendix C), `relay/channel/channel.go` (Appendix D), `relay/channel/manager.go` (Appendix E), `relay/channel/failover.go` (Appendix F)

**Interfaces:**
- Produces: `buffer.SampleChunk`, `(*buffer.Ring).Sample(int) []SampleChunk`; `channel.ClientStats`, `(channel.Client).Sent(int, time.Time)`, `.Touch(time.Time)`, `.Stats(time.Time) ClientStats`, `.Stopped() <-chan struct{}`; `(*channel.Channel).StopClient(string) bool`, `.StateChangedAt() time.Time`, `.Local() Local`, `.Resolver() Resolver`, `.applySwitch(Resolved)`.
- Consumes: nothing new.

- [ ] **Step 1: Write `relay/buffer/sample.go`** — Appendix A, in full.

- [ ] **Step 2: Write `relay/channel/clientstats.go`** — Appendix B, in full.

Read `ClientStats`'s doc comment before the code: **which fields exist is a property of the output format**, and `Sends` is what turns that into a mechanism rather than a check in the renderer (Ruling R8).

- [ ] **Step 3: Apply the `client.go`, `channel.go`, `manager.go` and `failover.go` diffs** — Appendices C–F.

Four things land here and each is separable:

1. `Client` gains the unexported `meter` and `stop` fields and the exported `Stopped()`.
2. `addClient` installs both — **and `publish` stops seeding its map literal and calls `addClient` instead** (Ruling R4).
3. `setState` records `stateChangedAt` on a change, `publish` seeds it, and `StateChangedAt()`, `Local()` and `Resolver()` expose what the detail endpoint needs.
4. `applySwitch` is factored out of `failover` — **byte for byte, in the same order**, so `failover`'s behaviour is unchanged — and Task 3's `Advance` becomes its second caller.

- [ ] **Step 4: Run the four checks**

```bash
cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
```

Expected: green. `relay/channel` takes ~75s.

- [ ] **Step 5: Break-check 4 — restore the map literal**

```bash
# In channel/manager.go, replace
#   clients:        map[string]*Client{},
#   ... c.addClient(client)
# with the old literal and delete the addClient call.
```

This cannot redden until Task 3's test exists, so **record it as deferred and run it at Task 3 Step 6**. Stated rather than skipped: a break-check with no test yet is a scheduling fact, not an exemption.

- [ ] **Step 6: Commit**

```bash
git add relay/buffer/sample.go relay/channel/clientstats.go relay/channel/client.go \
        relay/channel/channel.go relay/channel/manager.go relay/channel/failover.go
```

```bash
git commit -F <message file>
```

---

## Task 2: `relay/httpapi` — the detail endpoint, its golden, and the walk the golden cannot pin

**Files:**
- Create: `relay/httpapi/detail.go` (Appendix G), `relay/httpapi/detail_golden_test.go` (Appendix P), `relay/httpapi/detail_builder_test.go` (Appendix Q), `relay/httpapi/testdata/channel_detail.json` (generated, Step 3), `apps/proxy/tests/test_relay_detail_payload_golden.py` (Appendix X)
- Modify: `relay/internal/relaytest/controlplane.go` (Appendix M, the `Nameless` half)

**Interfaces:**
- Consumes: Task 1's `Ring.Sample`, `Client.Stats`, `Channel.StateChangedAt`, `Channel.Local`.
- Produces: `httpapi.ChannelHandler(ControlDeps) http.HandlerFunc`, `OwnerUnknown`, `WorkerUnknown`, `describeChannelDetail`, `describeBufferStats`, `humanBytes`, `unixFloat`, `pythonFloat`, `detailPayload`, `statePayload`.

- [ ] **Step 1: Write the Python golden fixture** — Appendix X, in full.

It is the sibling of `test_relay_list_payload_golden.py` and follows its shape exactly, including the completeness assertion that stops the fixture narrowing as the endpoint grows. **`NEVER_WRITTEN` is this one's `NOT_SERVED_YET`**, and it names the two fields Ruling R7 found unreachable in both relays.

- [ ] **Step 2: Write `relay/httpapi/detail.go`** — Appendix G, in full.

- [ ] **Step 3: Generate the golden from Django's own serializer**

The documented command writes the file, and in a container whose repo mount is **read-only** it cannot:

```bash
docker exec ... <yourname> /dispatcharrpy/bin/python /repo/manage.py test \
  apps.proxy.tests.test_relay_detail_payload_golden   # with DISPATCHARR_WRITE_GOLDEN=1
# OSError: [Errno 30] Read-only file system: '/repo/relay/httpapi/testdata/channel_detail.json'
```

Render it to stdout and write it on the host instead. **Base64, not raw**: Django's startup chatter goes to stdout too and lands in the file after the JSON, which `json.tool` then rejects at exactly the byte the payload ended on — measured.

```bash
cd <your worktree>
mkdir -p relay/httpapi/testdata
docker exec -e TEST_USE_SQLITE=1 -e DJANGO_SECRET_KEY=hook-test-secret \
  -e DISPATCHARR_LOG_LEVEL=ERROR -e DJANGO_SETTINGS_MODULE=dispatcharr.settings_test \
  -w /repo <yourname> /dispatcharrpy/bin/python -c "
import django, base64
django.setup()
from apps.proxy.tests.test_relay_detail_payload_golden import rendered
print('GOLDEN64:'+base64.b64encode(rendered()).decode())
" 2>/dev/null | grep '^GOLDEN64:' | sed 's/^GOLDEN64://' | base64 -d \
  > relay/httpapi/testdata/channel_detail.json
python3 -m json.tool relay/httpapi/testdata/channel_detail.json > /dev/null && echo JSON-OK
```

Then run the fixture's own tests, which verify the file matches what the serializer renders:

```bash
docker exec ... <yourname> /dispatcharrpy/bin/python /repo/manage.py test \
  apps.proxy.tests.test_relay_detail_payload_golden \
  apps.proxy.tests.test_relay_list_payload_golden --keepdb
```

Expected: `Ran 10 tests`, `OK`.

- [ ] **Step 4: Write the two Go test files** — Appendices P and Q.

**Q is not optional and it is not padding.** Break-checks 2 and 3 removed `pythonFloat`'s decimal point and `describeBufferStats`'s `keys_missing` assignment and the golden test in P stayed **GREEN**, because P's fixture is a Go struct literal that supplies both — the "fixture that patches away the subject" hazard, exactly. Q drives the three functions directly.

- [ ] **Step 5: Apply the `Nameless` half of the controlplane diff** — Appendix M.

- [ ] **Step 6: Register the two GET routes** — deferred to Task 3, which registers all four at once.

- [ ] **Step 7: Run the four checks, then the break-checks**

Break-checks 1, 2, 3 and 19 (§ Break-check). Break-check 3b is recorded there as a **finding**: the index filter it patched turned out to be unreachable, because `Ring.Sample(n)` already returns at most n chunks and always the newest, so the guard was deleted rather than kept as a branch no test can pin.

- [ ] **Step 8: Commit**

```bash
git add relay/httpapi/detail.go relay/httpapi/detail_golden_test.go \
        relay/httpapi/detail_builder_test.go relay/httpapi/testdata/channel_detail.json \
        relay/internal/relaytest/controlplane.go \
        apps/proxy/tests/test_relay_detail_payload_golden.py
```

```bash
git commit -F <message file>
```

---

## Task 3: the three remaining control routes, the body-signing fix, and Django's advance contract

**Files:**
- Create: `relay/channel/advance.go` (Appendix AQ), `relay/httpapi/control.go` (Appendix H), `relay/httpapi/control_test.go` (Appendix R), `relay/httpapi/advance_test.go` (Appendix S)
- Modify: `relay/httpapi/channels.go` (Appendix I), `relay/httpapi/server.go` (Appendix J, the route table); `apps/proxy/relay_serializers.py`, `apps/proxy/relay_client.py`, `apps/proxy/next_source.py`, `apps/proxy/live_proxy/views.py`, `apps/proxy/live_proxy/tests/zero_orm_allowlist.py`, `apps/proxy/tests/test_relay_client.py` (Appendix Y)

**Interfaces:**
- Consumes: Task 1's `Channel.Advance`, `StopClient`, `Resolver`; 2c-7's `sourceBuilder`, `infoFrom`, `control.Source`.
- Produces: `httpapi.ClientHandler`, `AdvanceHandler`, `stopResponse`, `builderFor`, `MaxInternalBody`; the three new serializer fields; `next_source.channel_stream_profile_ref`.

- [ ] **Step 1: Write `relay/channel/advance.go` and `relay/httpapi/control.go`** — Appendices AQ and H, in full.

`Advance` is `change_stream_url`'s owner branch over a source Django has already resolved. It calls Task 1's `applySwitch`, so an operator's switch and an automatic failover cannot spawn different things; what they do NOT share is the tried-set bookkeeping, which is where the two genuinely differ (`failover` records the candidate before the URL check, `update_url` after).

- [ ] **Step 2: Apply the `channels.go` diff** — Appendix I. **This is Ruling R3**: `RequireInternal` buffers the body, verifies against it, and hands the handler a reader over the same bytes.

- [ ] **Step 3: Register all four routes** — Appendix J's `server.go` diff.

One gate per route rather than a wrapper around the mux: the two health endpoints must stay ungated (a probe holds no `SECRET_KEY`), and a middleware with an exception list is one edit away from exempting a route it should not.

- [ ] **Step 4: Apply the three Python edits** — Appendix Y's `relay_serializers.py`, `relay_client.py`, `next_source.py` and `live_proxy/views.py` hunks. **Ruling R2.**

- [ ] **Step 5: Allowlist the new in-process import edge** — Appendix Y's `zero_orm_allowlist.py` hunk.

`views.py` importing `next_source.channel_stream_profile_ref` is a new edge and Gate 1's static half refuses an unlisted one. **The hit count is measured, not asserted**: the first draft said 3 and the scanner said 7, because the reachable subtree includes `_LockedFfmpegProfile.ref` → `_locked_ffmpeg_profile`'s `StreamProfile.objects.filter`, which really is a query. The entry says so. Run:

```bash
docker exec ... <yourname> /dispatcharrpy/bin/python /repo/manage.py test \
  apps.proxy.live_proxy.tests.test_zero_orm_reads --keepdb
```

Expected: `OK`. A different count is the ratchet working — re-read the subtree, then update the number and the reason **together**.

- [ ] **Step 6: Write the two Go test files and run the break-checks** — Appendices R and S.

Break-checks 4 (deferred from Task 1), 5, 6, 7, 19, 20 and 21.

- [ ] **Step 7: Run the four Go checks and the Python labels**

```bash
cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
docker exec ... <yourname> /dispatcharrpy/bin/python /repo/manage.py test \
  apps.proxy.tests apps.proxy.live_proxy.tests --keepdb
```

Expected: green, and `apps.proxy.tests` at **403** tests (398 before this PR, plus the five Ruling R13 / Gate 2 tests Task 5 adds). **Two existing Python tests move in this step** and both are in Appendix Y: `test_advance_sends_the_resolved_source_and_the_long_budget` gains the three new payload keys, and `test_stream_id_is_coerced_to_int_before_reaching_the_service` went 500 until the bare-url branch was gated on `if not stream_id:` rather than on `if stream_profile is None:` — a mocked `resolve_source` answer carries no `stream_profile`, and the looser condition sent that path into a channel lookup it had no row for.

- [ ] **Step 8: Commit** (stage and commit in separate calls). Stage `relay/channel/advance.go` with the rest.

---

## Task 4: the four events

**Files:**
- Create: `relay/httpapi/clientevents.go` (Appendix K), `relay/httpapi/events_test.go` (Appendix T)
- Modify: `relay/channel/events.go` (Appendix L), `relay/channel/channel.go` and `manager.go` (the emit halves of Appendices D and E), `relay/httpapi/stream.go` and `fmp4.go` (Appendices N and O), `relay/internal/relaytest/controlplane.go` (Appendix M, the `ClientID` half), `relay/httpapi/{fanout,stream,transcode}_test.go` (Appendix U)

**Interfaces:**
- Produces: `channel.Channel.Emit`, `httpapi.emitClientConnect`, `emitClientDisconnect`, `clientEventDetails`, `userAgentEventLimit`.

- [ ] **Step 1: Lift `client_id` in `channel.emit`, and export `Emit`** — Appendix L.

`control_plane.py:331-333` loops over **two** names and leaves both in `details`. 2c-5 lifted `stream_id`; this adds the second, with the first events that carry one.

- [ ] **Step 2: Raise `channel_start` in `publish` and `channel_stop` in `run`'s defers** — Appendices E and D.

**Read Ruling R9 before placing `emitStop`.** Its position among the defers decides whether the last `channel_stop` of a shutdown is delivered.

- [ ] **Step 3: Write `relay/httpapi/clientevents.go`** — Appendix K, in full.

- [ ] **Step 4: Wire the two emits, the counters and the stop signal into the handlers** — Appendices N and O.

Five edits: `client_connect` before `serveClient` and `client_disconnect` after it; `client_connect` inside `serveFMP4` at `generator.py:113-127`'s own point; `client.Sent` per chunk and per keepalive; `client.Touch` per fragment batch; and `stopContext`, applied to the **request** so both output formats inherit it.

- [ ] **Step 5: Narrow the five request-count assertions** — Appendix U.

**This is Constraint 33 becoming load-bearing.** `channel_start` posts to `/api/relay/events` on every tune, so five assertions that counted requests across the whole fake went from 1 to 2 — three in `stream_test.go`, one in `fanout_test.go` and one in `transcode_test.go`. They are narrowed to `RequestsTo("/next-source")`. **Two of the three in `stream_test.go` were passing by timing, not by correctness**: they never read the body, so the emitter had usually not posted yet when the assertion ran. Narrowing removes a latent flake as well as a failure.

- [ ] **Step 6: Add `ClientID` to `RecordedEvent`** — Appendix M's second half.

- [ ] **Step 7: Write `events_test.go` and run the break-checks** — Appendix T; break-checks 8, 9 and **25**.

**`TestStoppingAChannelRaisesChannelStop` closes the emitter before it counts**, and that is not tidiness: `eventsOf` returns on the first matching event, so a second raise landing a moment later is invisible to a `len()` check that runs immediately after it. `Emitter.Close` drains the queue and waits for the worker, so after it nothing is in flight. Break-check 25 is the proof, and it passed 6/6 without this.

**Break-check 9's scar is in the test.** It stayed GREEN until the fMP4 read was widened past the init segment: `serveFMP4` writes the init **before** the fragment loop starts, so a read that stopped there queried the detail endpoint before the loop had run once — and an fMP4 row with no counters proves nothing when a client that has sent nothing has none either way.

- [ ] **Step 8: Run the four checks and commit.**

---

## Task 5: Django — `POST /_dispatcharr/authorize-internal`

**Files:**
- Create: `apps/proxy/tests/test_authorize_internal_view.py` (Appendix Z)
- Modify: `apps/proxy/authorize_views.py`, `dispatcharr/urls.py` (Appendix Y)

**Interfaces:**
- Produces: `authorize_internal_view`, `AuthorizeInternalRequestSerializer`, `AuthorizeInternalHeadersSerializer`, `_synthetic_request`; the route named `authorize-internal`.

- [ ] **Step 1: Apply the `authorize_views.py` hunk** — Appendix Y.

**Read Constraints 47–50 first.** Three of this view's failure modes return a 200 with real bytes and no error at all:

| What goes wrong | What the viewer sees | What has silently stopped applying |
|---|---|---|
| The transport's own `X-Dispatcharr-Internal` answers `authorize_stream`'s `is_internal` | 200, bytes | `hidden_from_output`, adult filtering, profile membership, the XC credential check, the stream limit — **everything** |
| The session principal is read from `request.user` | 200, bytes | `user_level`, profile membership, adult filtering, the per-user stream limit |
| `REMOTE_ADDR` is the relay's own address | 200, bytes | the STREAMS ACL |

`_synthetic_request` builds the request **entirely** from the body, and the session is loaded the way `SessionMiddleware.process_request` loads it — from the body's cookie, through `SESSION_ENGINE`'s `SessionStore` — because `_session_user` calls `django.contrib.auth.get_user(request)`, which reads the **session**, not `request.user`.

- [ ] **Step 2: Register the route** — Appendix Y's `dispatcharr/urls.py` hunk.

**Its own path, not `/_dispatcharr/authorize`.** That one is an `internal;` exact-match nginx location (`docker/nginx.conf:120`), which wins over every prefix and regex location, so a POST to it is 404'd before Django sees it in every nginx-fronted deployment. Reusing it would turn a `SECRET_KEY` mismatch between roles from today's silent-but-working degrade into every live tune failing.

**Registered unconditionally**, because Django cannot know at boot whether the relay it will talk to has nginx in front of it.

- [ ] **Step 3: Write the tests** — Appendix Z, in full.

Seventeen tests, twelve of them about the decision and five about Gate 2 (Task 5 Step 3's own note). The four that matter most assert an **identity or a status vocabulary**, never "it worked": the hidden channel that must still 403 with `internal: false` while every call carries the transport header; the same channel authorizing with `internal: true`, so "nothing is ever internal" cannot be what makes the first pass; `X-Relay-User` carrying the real user id for a forwarded session cookie; and the unknown channel answering **404** with no `X-Authorize-Status`, which is how you tell `authorize_error_response` was called and not `subrequest_error_response`.

- [ ] **Step 4: Run the label**

```bash
docker exec ... <yourname> /dispatcharrpy/bin/python /repo/manage.py test \
  apps.proxy.tests.test_authorize_internal_view --keepdb
```

Expected: `Ran 17 tests`, `OK` — twelve plus the five Gate 2 tests below.

- [ ] **Step 5: Commit.**

---

## Task 6: `relay/control` and `relay/httpapi` — the Go half of the dev fallback

**Files:**
- Create: `relay/control/authorize.go` (Appendix V), `relay/httpapi/authorize.go` (Appendix W), `relay/httpapi/authorize_test.go` (Appendix AA)
- Modify: `relay/httpapi/stream.go` (Appendix N), `relay/internal/relaytest/controlplane.go` (Appendix M, the authorize half)

**Interfaces:**
- Produces: `control.AuthorizePath`, `AuthorizeRequest`, `AuthorizeHeaders`, `Decision`, `Denied`, `DeniedBodyLimit`, `(*Client).Authorize`; `httpapi.authorizeTune`, `decisionHeader`, `writeAuthorizeFailure`, `headerOrNil`; `relaytest.AuthorizeDecision`, `SetAuthorize`, `AuthorizeRequests`, `AuthorizePath`.

- [ ] **Step 1: Write `relay/control/authorize.go`** — Appendix V, in full.

**ONE ATTEMPT, NO RETRY**, and it is a decision: this call is the in-process `authorize_stream()` call's successor, and Python's inline path cannot fail with a 5xx because there is no wire between it and the decision. A retry would add a full `(2s, 5s)` to the tune's critical path for a fault a second attempt will meet again.

**The four denial statuses are a DECISION and every other 4xx is an outage.** 401/403/404/429 are what `AuthorizeDenied` is raised with; a 400 from the serializer or a 403 from `IsInternalRelay` on a `SECRET_KEY` mismatch is the contract being wrong and must not reach the viewer as a refusal of their tune.

- [ ] **Step 2: Write `relay/httpapi/authorize.go`** — Appendix W, in full.

- [ ] **Step 3: Give `identify` a fourth parameter and call the fallback** — Appendix N.

The decision is checked **first** in `identify`'s one closure, so a request that carried no valid marker can never fall back to reading its own headers: the two sources are exclusive by construction and never merged.

- [ ] **Step 4: Teach the fake control plane the route** — Appendix M's authorize half.

**The default decision is deliberately minimal** — the channel out of the URI and nothing else. Django resolves more than that on every live tune (it always mints a client id), and filling those in by default would silently change what every untrusted rig from 2c-2 onward observes. A test that is *about* the hop sets the fields it is about.

- [ ] **Step 5: Write `authorize_test.go` and run the break-checks** — Appendix AA; break-checks 10, 11 and 12.

**Break-check 10's scar is in the test.** `writeAuthorizeFailure` has two branches — a JSON body is forwarded verbatim, a non-JSON one answers with the status text — and every row of the first draft supplied a body, so patching the second branch stayed GREEN. The table now carries three body-less rows, and the fake grew `NonJSONBody` to produce them.

- [ ] **Step 6: Run the four checks and commit.**

---

## Task 7: the XC live roots

**Files:**
- Create: `relay/httpapi/xc.go` (Appendix AB), `relay/httpapi/xc_test.go` (Appendix AC)
- Modify: `relay/httpapi/server.go` (Appendix J)

**Interfaces:**
- Produces: `httpapi.XCHandler`, `XCStreamIDPattern`, `xcForcedFormat`.

- [ ] **Step 1: Write `relay/httpapi/xc.go`** — Appendix AB, in full. **Ruling R1.**

- [ ] **Step 2: Register both roots** — Appendix J.

**The bare three-segment root does not shadow `/proxy/relay/channels`**, which also has three segments: `net/http`'s mux prefers the more specific pattern, and three literal segments beat three wildcards. Asserted rather than trusted — `TestTheBareXCRootDoesNotShadowTheControlRoutes` — because the failure would be a 404 on every stats poll in the deployment.

- [ ] **Step 3: Write `xc_test.go` and run break-checks 15 and 16** — Appendix AC.

- [ ] **Step 4: Run the four checks and break-check 24, then commit.**

**`TestStreamRouteIsUnregisteredWithoutTheDevFlag` now loops over all seven gated paths**, not one. Six of them are new in this PR, and `GET /{username}/{password}/{channelID}` is the broadest pattern this relay has ever registered — three bare wildcards at the site root. The plan's opening claim is inertness in every deployment, and one path of seven cannot carry it. The same test also asserts `/healthz` and `/readyz` still answer 200, so "the mux is empty" cannot be why the seven pass.

---

## Task 8: the drain, `/readyz`, and the Docker `HEALTHCHECK`

**Files:**
- Create: `relay/drain/drain.go` (Appendix AD), `relay/drain/drain_test.go` (Appendix AE), `relay/httpapi/health.go` (Appendix AF), `relay/httpapi/drain_test.go` (Appendix AG), `docker/healthcheck.sh` (Appendix AH)
- Modify: `relay/main.go` (Appendix AI), `relay/httpapi/server.go`, `stream.go`, `server_test.go`, `stream_test.go` (Appendices J, N, AJ), `relay/channel/manager.go` (Appendix E, the `StopAll` half), `relay/control/events.go` and `events_test.go` (Appendices AK, AL), `docker/Dockerfile`, `docker/entrypoint.sh` (Appendix Y)

**Interfaces:**
- Produces: `drain.Run`, `Deps`, `DefaultBudget`, `DefaultClientGrace`, `DefaultEventsBudget`; `httpapi.Lifecycle`, `HealthDeps`, `ReadyHandler`, `StatusReady`, `StatusDraining`.

- [ ] **Step 1: Make `Emitter.Emit` safe after `Close` and `Close` idempotent** — Appendix AK. **Ruling R10.**

- [ ] **Step 2: Pin both directly** — Appendix AL's addition to `control/events_test.go`, and break-checks 18 and 18b.

**Pinned here and not through the drain**, because `net/http` recovers a panic in the goroutine serving a request: the drain test printed `http: panic serving …: send on closed channel` and passed.

- [ ] **Step 3: Make `StopAll` concurrent** — Appendix E. **Ruling R11's arithmetic.**

- [ ] **Step 4: Write `relay/httpapi/health.go` and wire `Lifecycle` through** — Appendices AF, J, N, AJ.

One `Lifecycle`, shared by the tune path, `/readyz` and the drain. Two would let the probe say "ready" while the handler refused every tune.

- [ ] **Step 5: Update 2c-1's health test** — Appendix AJ's `server_test.go` hunk.

2c-1 asserted both endpoints answer the literal `"ok\n"`. That is the ratchet this PR deliberately changes: `/healthz` keeps it, `/readyz` answers the payload. The replacement asserts the **counts** as well as the status, because a body that only ever said `"ready"` would be the static 200 under a new name.

- [ ] **Step 6: Write `relay/drain/drain.go` and its test** — Appendices AD and AE. **Ruling R11.**

`TestTheBudgetFitsInsideSupervisordsStopWindow` pins the **arithmetic**, not the three numbers: the budget must be inside `stopwaitsecs`, the margin must be at least three seconds, and the grace plus the flush must leave room for the teardown between them.

- [ ] **Step 7: Wire the signal handler into `main.go`** — Appendix AI.

The handler is installed **before** `ListenAndServe`, so a SIGTERM during startup is drained rather than killing the process with channels running — supervisord sends one the moment a `docker stop` lands, which can be inside `startsecs=5`. And `main` waits for the drain after `ListenAndServe` returns `ErrServerClosed`, because the emitter flush runs **after** `Shutdown` returns and exiting there would drop every `channel_stop` of the shutdown.

- [ ] **Step 8: Write `relay/httpapi/drain_test.go`** — Appendix AG.

Three tests, and the clock in each starts **before** `drain.Run` (Constraint 28).

- [ ] **Step 9: Add the `HEALTHCHECK`, the role file and the probe** — Appendix Y's `Dockerfile` and `entrypoint.sh` hunks, and Appendix AH.

**`docker/healthcheck.sh` MUST BE COMMITTED EXECUTABLE, and the `HEALTHCHECK` must not depend on that.** Both, and the reason each is there:

```bash
cd <your worktree>
chmod +x docker/healthcheck.sh
git add docker/healthcheck.sh
git ls-files -s docker/healthcheck.sh     # must print 100755, not 100644
```

**Exec form does not go through a shell**, so `CMD ["/app/docker/healthcheck.sh"]` on a 0644 file cannot start at all. Measured, in a real container: the probe reports **exit −1** with `OCI runtime exec failed: … exec: "/app/docker/healthcheck.sh"` and the container is `unhealthy` for ever. **Nothing else in this plan would catch it** — hadolint is clean either way, and no Go or Python test reads this file.

**So the `CMD` names the interpreter**, `["/bin/sh", "/app/docker/healthcheck.sh"]`, and the mode is set as well. Belt and braces on purpose: the mode is the intent, the interpreter is the guarantee, and a mode bit is exactly the thing lost when a file is written from a plan's appendix by hand, or applied by a patch that does not carry modes. Measured with the same container, same 0644 file: the interpreter form runs, and answers **exit 7** (`curl: (7) Failed to connect to 127.0.0.1:5658`) because the relay is not there — which is the probe working.

**AND `unhealthy` IS THE SAME WORD FOR BOTH**, which is why the break-check below asserts the exit code and not the status. "The probe ran and the relay is down" and "the probe could not run at all" are the same one-word answer from `docker inspect`; −1 against 7 is what separates them.

**Note that 0644 is not anomalous in this tree** — six of the eleven shell scripts under `docker/` are committed 0644 (`docker/init/*.sh`, `docker/tests/*.sh`), because they are sourced or invoked as `bash <file>` rather than exec'd. Only `entrypoint.sh`, `build-dev.sh` and `supervisord.d/wait-for-stores.sh` are 0755. So "match the neighbours" is not the argument; "exec form cannot exec a non-executable file" is.

hadolint, with the interpreter form, verified:

```bash
docker run --rm -i hadolint/hadolint@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d \
  hadolint - < docker/Dockerfile
```

Expected: no output, on this tree and on `main`. Then run break-check 23.

- [ ] **Step 10: Run the break-checks** — 13, 14, 17, 22 and **23**, the container one.

- [ ] **Step 11: Run this PR's subset eight times**

```bash
cd <your worktree>/relay
for i in $(seq 1 8); do
  go test -race -count=1 ./drain/ ./httpapi/ -run \
    'Detail|OwnerAndSource|FieldsState|Deleting|Advance|ResetTried|Readyz|Drain|TuneArriving|ChannelStart|BothClientTypes|StoppingAChannelRaises|OnlyATSClients|Untrusted|TrustedTuneMakesNo|InternalTravels|ADenial|UnreachableControl|DecisionsValues|XC|Budget|Dependency|RunWithNo|Health|PythonFloat|DescribeBufferStats|HumanBytes|UnixFloat|NamesComeOffTheWire' \
    >/dev/null 2>&1 || echo "round $i FAILED"
done
```

Expected: eight silent rounds. Measured on the re-seeded tree: 8/8. **Then run the whole module three times WITHOUT `-race` as well** (Constraint 55): this PR's one flaky test was green 8/8 under the detector and failed about half of all no-race rounds.

- [ ] **Step 12: Commit.**

---

## Task 9: the parity matrix, the spec amendment and `CLAUDE.md`

**Files:**
- Modify: `docs/relay-parity-matrix.md` (Appendix AM), `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` (Appendix AN), `CLAUDE.md` (Appendix AO)

- [ ] **Step 0: Re-capture all three document hunks against the tree you are on**

**Every document appendix in this plan is a `git diff` hunk captured against `eb7fac07`, and at least one of them will not apply to the merged 2c-7 tree.** Appendix AN's spec hunk certainly will not: it is anchored between the end of A6 and `## Stage 2d`, and 2c-7 inserts A7 there; its Done-log context moves the same way. Appendix AO's `CLAUDE.md` hunk may not, since 2c-7 edits § Video path. Appendix AM's matrix hunk probably will, because 2c-7 touches row 11 and the `<!-- block: -->` markers keep two lines between blocks — but "probably" is not a plan.

So: apply what applies, redo by hand what does not, and **re-capture every one of the three** before you commit.

```bash
cd <your worktree>
for f in <the three hunks, extracted from Appendices AM, AN and AO>; do
  printf '%-16s ' "$(basename "$f")"
  git apply --check "$f" && echo "applies" || echo "STALE -- redo this edit by hand"
done
```

**A hunk and not prose, and the rule was paid for twice.** A reviewer applying a prose instruction to the matrix produced a six-cell row the guard rejects; and a prose "replace this paragraph" for `CLAUDE.md` would have silently dropped a sentence a previous PR had added to the same paragraph, because the quoted "after" text is written against an older copy and nothing compares the two. `git apply` refuses when its context has moved; a paragraph of prose does not.

- [ ] **Step 1: Apply Appendix AM — a Go pin on thirteen rows, and a Notes clause on ten of them**

Amendment A2.2: a Go pin is a reference appended to the existing `Pin` cell, **not a sixth column**. Rows 26 and 27 take none — the guard requires their cell to be exactly `white-box-only`.

**The Notes clause is the second half and it is not optional.** Ten of the thirteen are authorize-matrix rows whose decisions are Django's; the relay's whole share is to ask the complete question and obey the answer exactly. `Notes` is where a reader learns what a pin covers, so without the clause the next reader concludes a Go test now decides who may watch what. Rows 15 and 21 take a different clause from the other eight, because on the XC path the relay's share is larger.

If the hunk is stale and you are redoing this by hand, read the HTML comment at the top of that file first — one row is one line, cells are never padded, and no Markdown formatter may be run over it — and check your work with this before you run the guard:

```bash
cd <your worktree>
awk -F'|' '/^\| [0-9]+ \|/ {if (NF != 7) print "MALFORMED row " $2 ": " NF " fields"}' \
  docs/relay-parity-matrix.md
```

Silence means every row is still five cells. **That is the check that would have caught the six-cell row.**

**Ten of the thirteen are authorize-matrix rows, and what the Go pin asserts there is narrower than what the row is about.** Those decisions are Django's and stay Django's; the relay's whole share is to ask completely and obey exactly, and that is what the named tests pin — the question travelling in full (rows 16, 20, 22, 23), the internal-principal question travelling as a body field (19), the answer's values being used rather than the path and the socket (24), the denial's status reaching the viewer as itself (25, 30), and the XC path authorizing once (15, 21). **Appendix AM's hunk widens those ten rows' `Notes` to say so**, which is where it belongs: the PR description is read once and the table is read for the rest of the phase.

- [ ] **Step 2: Run the guard**

```bash
cd <your worktree>/e2e && npm ci && npx playwright test --project=guards
```

**`npm ci` first, every time, in a fresh worktree** — `e2e/node_modules` is not shared between worktrees and `npx playwright` without it fails in a way that looks nothing like a matrix problem.

Expected on a tree where this PR's Go files exist: **16 passed**, and the line `parity matrix: 30 rows — 28 pinned, 0 owed, 2 white-box-only.`

**Expected on a plan-only branch, or if you run this before Tasks 2–8 have landed their tests: exactly ONE failure, `every pin resolves`, naming the Go test files that do not exist yet.** Measured, on the plan-only branch this document was written on — 15 passed, 1 failed, and the count line still printed:

```
parity matrix: 30 rows — 28 pinned, 0 owed, 2 white-box-only.

  1) [guards] › tests/guards/parity-matrix.spec.ts:222:5 › every pin resolves @characterization

    Error: A pin that does not resolve is a row claiming cover it does not have — the one failure
    mode this matrix exists to prevent.
    docs/relay-parity-matrix.md:172 (row 14) — pin names no such file: relay/httpapi/detail_golden_test.go
    docs/relay-parity-matrix.md:173 (row 15) — pin names no such file: relay/httpapi/xc_test.go
    …
```

That is the guard working — it resolves every `path::symbol` against the tree — and it is **not a broken row**. Anything else failing is, and so is that failure once Tasks 2–8 have landed.

**WHEN THE HUNK WAS STALE AND YOU REDID THE EDIT BY HAND, THIS IS THE STEP THAT CATCHES A MALFORMED ROW**, which is exactly how the six-cell row was found. Do not skip it on the grounds that the diff looked right.

- [ ] **Step 3: Apply Appendix AN — Amendment A8 and the two Done-log rows**

One hunk carries both. **It is anchored where A6 ends, so on the merged 2c-7 tree it will not apply**: A8 goes after A7, and the Done-log rows go after 2c-7's. The hunk's own 2c-7 placeholder row says so in the text, so a stale application is loud rather than silent. Redo both edits by hand against the merged spec and re-capture (Step 0).

- [ ] **Step 4: Apply Appendix AO — `CLAUDE.md`**

Two edits in one hunk: the § Architecture sentence that still says "At 2c-1 it serves `/healthz` and `/readyz` and nothing else", and one bullet appended to § Known defects' Correctness list. **Do not rewrite the paragraph from the plan's prose** — the paragraph has gained a sentence from nearly every PR in this stage, and a hand-retyped "after" version drops whichever ones landed since this plan was written.

- [ ] **Step 5: Fill the `[#NNN]` slots**

```bash
cd <your worktree>
grep -rn '\[#NNN\]' docs/relay-parity-matrix.md docs/superpowers/specs/ CLAUDE.md \
  relay/ apps/proxy/ 2>/dev/null
```

Expected after the fill: no output. **Scoped to the paths that can carry a real slot**, which is 2c-6's own correction — run unscoped over all of `docs/` it can never return empty.

There are **two** slots in this PR and they are in the spec's **Done-log row** (Appendix AN) and in **`CLAUDE.md`** (Appendix AO), not in A8.8's prose — A8.8 says the two dead fields are "filed" and carries no reference, deliberately, because the amendment's job is the finding and the ledger's is the number. File one issue covering both fields, against `D10Scot/Dispatcharr` with an explicit `--repo`, and put its number in the two slots.

- [ ] **Step 6: Re-capture the three hunks and check them against a clean tree**

The hunks in this plan are the record of what this PR did to three documents, and a successor plan will seed from them. Re-capture whatever you changed by hand:

```bash
cd <your worktree>
git diff -- docs/relay-parity-matrix.md > /tmp/doc-matrix.diff
git diff -- docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md > /tmp/doc-spec.diff
git diff -- CLAUDE.md > /tmp/doc-claudemd.diff
# Each must reverse-apply against the edited tree, which is the round trip.
for f in /tmp/doc-*.diff; do git apply --check --reverse "$f" || echo "BROKEN: $f"; done
```

Paste the re-captured hunks back into Appendices AM, AN and AO in this plan document and commit them with the change. A plan whose document appendices no longer describe what landed is worse than one with none.

- [ ] **Step 7: Commit.**

---

## Task 10: final verification and the PR description

- [ ] **Step 1: The four checks under three GOOS**

```bash
cd <your worktree>/relay
go build ./... && go vet ./... && GOOS=linux go vet ./... && GOOS=darwin go vet ./...
gofmt -l .
golangci-lint run ./... && GOOS=linux golangci-lint run ./... && GOOS=darwin golangci-lint run ./...
```

Expected: `0 issues.` three times, `gofmt -l` silent.

- [ ] **Step 2: The whole module three times under `-race`, and three times without**

Expected: 3/3 and 3/3. Measured on the re-seeded tree at ~90s per round. **Both, and the second is the one that found this PR's only flake** — Constraint 55.

- [ ] **Step 3: The two Go guards**

```bash
cd <your worktree>
scripts/check_go_credential_logging.sh relay
scripts/check_go_stdlib_only.sh relay
```

Expected: `credlint: 12 package(s) clean` and `OK: relay depends on the standard library only.` **Twelve, not eleven**: `relay/drain` is new.

- [ ] **Step 4: GATE 2, run rather than reasoned about**

Constraint 54. Five of the Python files this PR edits are in `scripts/coverage_live_path.coveragerc`'s module list, and the floor's `missing` is a maximum: one uncovered new statement fails `backend-tests.yml`'s `Coverage gate` with every Django label green.

```bash
cd <your worktree>
for s in proxy liveproxy channels; do
  DISPATCHARR_TEST_CONTAINER=<yourname>-$s DISPATCHARR_TEST_DB_VOLUME=<yourname>-$s-db \
    .claude/hooks/start-test-container.sh
done
COVERAGE_ISOLATED_PREFIX=<yourname> COVERAGE_ISOLATED_OUT=/tmp/cov \
  bash scripts/coverage_live_path_isolated.sh --gate
```

Expected, measured on the re-seeded tree:

```
coverage_live_path: floor missing=1525  this run missing=1491  coverage 81.82%
coverage_live_path: 34 FEWER missed than the floor.
```

**Expect a RANGE, not that number.** Measured on this tree across separate local rounds: **1491-1504**, i.e. 21-34 under the floor. The floor's own header documents a local spread of 1484-1512 on the tree that set it, so a draw anywhere in that band is the measurement working, not a regression — what would be a regression is a draw ABOVE 1525, or any added-and-missing line in the attribution below.

**And know that a CI draw can exceed a local one** ([#312](https://github.com/D10Scot/Dispatcharr/issues/312)): the floor is the worst of twelve CI rounds, one CI draw can sit above a local census's maximum, and re-measuring means re-running the whole workflow, not one job.

**A regression is attributed per file and then per line** from `live-path.json` (Constraint 54 carries the command) **and covered with a real test in one of the gate's three labels**. **The floor is never raised** — "27 fewer missed" is not an invitation to run `--write-floor` either; that belongs to a PR that earned it with a census.

**And a local pass is not a CI pass.** The floor was set from the worst of twelve CI rounds and the last campaign's local-to-CI delta was +13 at the maximum. 34 of margin absorbs that; 3 would not.

- [ ] **Step 5: All sixteen backend labels**

`dispatcharr/urls.py` is in `_SHARED_PATH_PREFIXES`, so the commit gate derives the full set. Run them:

```bash
for label in apps.accounts.tests apps.backups.tests apps.channels.tests apps.connect.tests \
             apps.dashboard.tests apps.epg.tests apps.m3u.tests apps.output.tests \
             apps.plugins.tests apps.proxy.live_proxy.tests apps.proxy.tests \
             apps.proxy.vod_proxy.tests apps.timeshift.tests apps.vod.tests core.tests tests; do
  printf '%-34s ' "$label"
  docker exec ... <yourname> /dispatcharrpy/bin/python /repo/manage.py test $label --keepdb 2>&1 \
    | grep -E '^(OK|FAILED|Ran )' | tr '\n' ' '; echo
done
```

Expected: every label `OK`. Measured here: 16/16, with `apps.proxy.tests` at **403** and `apps.proxy.live_proxy.tests` at 428. **`apps.proxy.live_proxy.tests` carries a pre-existing flake** — `test_manager_stderr_failover`'s liveness guard, which fails roughly one run in two in isolation on `main` and is unrelated to this PR. Re-run the label; do not weaken the assertion.

- [ ] **Step 6: The three one-mechanism counts, again**

Task 0 Step 2's three greps. Expected **after** this PR: two registry writes and no map literal; **five** defers in `run` (the four plus `emitStop`); two writers of `StateActive`. Name the lines in the report.

- [ ] **Step 7: The un-Go'd row count**

```bash
cd <your worktree>
awk -F'|' '/^\| [0-9]+ \|/ {pin=$5; if (pin ~ /relay\//) g++; else n++} END {print g" with, "n" without"}' \
  docs/relay-parity-matrix.md
```

Expected: `27 with, 3 without` on a tree where 2c-7 has landed row 11 — no: **28 with, 2 without**, the two being `white-box-only`. On a tree where row 11 is still open it is `27 with, 3 without` and row 11 is 2c-7's, not this PR's.

- [ ] **Step 8: Write the PR description**

In this order: what this PR does; **Ruling R1** and how the XC live roots were found to have no owner; **Ruling R2** and the three-field contract extension, with the bare-url branch's own answer; **the four break-checks that did not redden on a first attempt** (rows 2, 3, 9, 10) and what closed each — the golden fixture that supplied both values the builder computes, the fMP4 read that stopped at the init segment, and the denial table that had no body-less row; **the one break-check that deleted code** (3b, the unreachable index filter); **the four defects this PR found** — three in code it did not write (`RequireInternal` verifying against an empty body, R3; `publish` bypassing `addClient`, R4; `Emitter` panicking on a drain, R10) and one in its own first draft, the hyphenated header that never arrived because `source=` is the wrong half of DRF's input mapping (R13), found by a coverage test rather than by review; **the credlint census** — two markers added, three `redact.Error` calls, twelve packages clean; **zero suppressions**; **the two lint findings fixed rather than suppressed**; **the measurements** — 8/8 on the subset, 3/3 on the module, 16/16 on the backend labels, and Gate 2 at missing=1491-1504 against the floor's 1525 with zero added-and-missing lines in all five in-scope files; **the stated divergences**, as a list: the drain itself, which D6 makes an improvement on `die-on-term` rather than parity; `channel_stop` from one place where Python has several (R9); the per-client counters live where Python's are 1-second-throttled (R8); `last_active` the true last write rather than the last flush (R8); row 18's names absent where Python falls back to the ORM (R7, Constraint 44); `client_connect`'s `user_agent` carrying the registry's `"unknown"` where Python's event carries null; `round1`'s half-away-from-zero where Python rounds half-to-even; `worker_id` and `owner` the literal `"unknown"` because there is no worker to name; `event_published` always false and `stop_key_set` meaning the signal rather than a Redis `SETEX` (R6); **the edits no test pins**, stated: `writeJSONStatus`'s encode-failure arm, `Authorize`'s 3xx arm, `readInternalBody`'s read-error arm, and `drain.Run`'s nil-dependency arms; **what this PR does not do**: no Go coverage ratchet and no CodeQL Go pack (2c-9), no nginx route (2d), no HLS (Phase 4), no `metrics/curated` update — milestones are per stage and the 2c goal milestone lands with 2c-9.

- [ ] **Step 9: Commit and open the PR.**

---

## Break-check × what each can redden

Every row was run. The **message** column is the actual output, not a prediction. Rows 23-25 were added in the fix round; 23 runs in a container, as its own row says.

| # | The defect patched in | Test | Red? | The message that appeared |
|---|---|---|---|---|
| 1 | `Owner: OwnerUnknown` → `""` | `TestTheDetailEndpointRendersARunningChannel` | yes | `owner is , want the literal "unknown" (channel_status.py:45; row 14)` |
| 2 | `pythonFloat` drops the `.0` | `TestPythonFloatRendersWhatPythonsStrRoundRenders` | yes, **after the test was added** | `pythonFloat(25) = "25", want "25.0" (Python's str(round(...)))` |
| 3 | `keys_missing` is not assigned | `TestDescribeBufferStatsWalksTheRing` | yes, **after the test was added** | `keys_missing is absent on a fully resident sample: channel_status.py:275 assigns it inside the same arm as keys_found` |
| 3b | the buffer walk's index filter is disabled | `TestDescribeBufferStatsWalksTheRing` | **no** | — the guard is unreachable, because `Ring.Sample(n)` already returns at most n and always the newest. **Deleted rather than kept.** |
| 4 | `publish` seeds the client map literal again | `TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming` | yes | `the client DELETE answered {…"locally_processed":false…}, want success with locally_processed true` |
| 5 | `RequireInternal` verifies against `nil` | `TestAnAdvanceSwitchesTheChannelAndKeepsTheClientFed` | yes | `the advance answered 403: forbidden` |
| 6 | `reset_tried` does not clear the set | `TestResetTriedClearsTheExclusionListAndOmittingItDoesNot` | yes | `after reset_tried the relay would exclude [1 2], want just [2]` |
| 7 | the unchanged-URL check is disabled | `TestAnAdvanceToTheURLAlreadyPlayingSucceedsAndSwitchesNothing` | yes | `the upstream saw 2 requests after an unchanged-URL advance, want the 1 it had` |
| 8 | `client_disconnect` is raised for fMP4 too | `TestBothClientTypesConnectAndOnlyTheTSOneDisconnects` | yes | `the control plane saw 2 client_disconnect events, want exactly 1` |
| 9 | an fMP4 client records byte counters | `TestOnlyATSClientsDetailRowCarriesTheByteCounters` | yes, **after the read was widened** | `the fMP4 client's row carries "bytes_sent" as 2` |
| 10 | a body-less denial is collapsed to 403 | `TestADenialReachesTheViewerWithItsOwnStatus` | yes, **after body-less rows were added** | `a 401 denial (bodyless=true) reached the viewer as 403` |
| 11 | a JSON denial is collapsed to 403 | `TestADenialReachesTheViewerWithItsOwnStatus` | yes | `a 401 denial (bodyless=false) reached the viewer as 403` |
| 12 | the credential headers are dropped from the body | `TestAnUntrustedTuneAsksDjangoAndSendsTheQuestionInTheBody` | yes | `the relay sent no "authorization" in the body: …` |
| 13 | the drain gate is removed from the tune path | `TestATuneArrivingDuringTheDrainIsRefusedBeforeAnythingIsReserved` | yes | `a tune during the drain answered 200, want 503` |
| 14 | the drain flushes the events first | `TestTheDrainStopsTheChannelEndsTheClientAndFlushesTheEvents` | yes | `the control plane saw 0 channel_stop events, want 1: the flush runs AFTER the teardown for exactly this reason` |
| 15 | the XC root uses the numeric path id — **the injected edit must SET it**, `r.Header.Del("X-Relay-Channel")` in `XCHandler` before it calls the inner handler, so `identify` falls back to the path value | `TestAnXCTuneServesTheHopsChannelAndAuthorizesOnce` | yes | `the relay is running [12345], not the uuid the hop resolved`. **There is no omission that produces this defect**: `XCHandler` never reads the channel, so deleting a line from it is a no-op and an implementer who patches one records a false green. The edit has to make the handler discard the hop's answer |
| 16 | the XC extension does not override the format | `TestTheXCExtensionOverridesTheHopsOutputFormat` | yes | `the client's output_format is "mpegts", want "fmp4"` |
| 17 | `/readyz` ignores the drain flag | `TestReadyzReportsTheChannelCountAndTheDrain` | yes | `a draining relay answered 200 {Status:ready Channels:1 Clients:1}, want 503 draining` |
| 18 | `Emit`'s closed guard is removed | `TestTheEmitterDropsEventsRaisedAfterCloseAndCloseIsIdempotent` | yes, **after the pin moved off the drain test** | `panic: send on closed channel` |
| 18b | `Close` is not idempotent | same | yes | `panic: close of closed channel` |
| 19 | the detail endpoint's nil-channel guard is removed | `TestFieldsStateAnswersTwoFieldsAndA404ForAnUnknownChannel` | yes | `panic: runtime error: invalid memory address or nil pointer dereference` |
| 20 | `DELETE` reports success without stopping | `TestDeletingAChannelStopsItAndReportsItsPreviousState` | yes | `the channel is still in the manager after a DELETE` |
| 21 | `StopClient` signals nothing | `TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming` | yes | `timed out after 15s waiting for the stopped client to leave the registry` |
| 22 | the events budget is not clamped | `TestADependencyThatHangsDoesNotOverrunTheBudget` | yes, **after the test was restructured** | `the drain has not returned after 5s against a 300ms budget` |
| 23 | `chmod -x docker/healthcheck.sh` **and** revert the `CMD` to the bare `["/app/docker/healthcheck.sh"]` | a real container: `docker build`, `docker run -d`, then `docker inspect --format '{{range .State.Health.Log}}{{.ExitCode}} {{.Output}}{{end}}'` | yes | exit **−1**, `OCI runtime exec failed: … exec: "/app/docker/healthcheck.sh"`. **Assert the EXIT CODE, not the status**: `unhealthy` is the same word for "the probe ran and the relay is down" (exit 7, `curl: (7) Failed to connect to 127.0.0.1:5658`) and "the probe could not run at all" (−1), and a row that checked the status alone would be hollow. With the interpreter form and the same 0644 file, the probe runs and answers 7 |
| 24 | one of the six new routes escapes the dev flag (move `GET /{username}/{password}/{channelID}` outside the `if cfg.DevRoutes` block) | `TestStreamRouteIsUnregisteredWithoutTheDevFlag` | yes, **on a different clause than predicted** | a `nil pointer dereference` panic rather than a status mismatch: a `DevRoutes: false` Config carries no `Channels` or `Control`, so the handler panics on the first dereference. The panic IS the evidence — a 404 would mean the route was never registered, and reaching the handler at all is what the row tests. Recorded per Constraint 30 rather than tidied into a nicer failure |
| 25 | a channel announces its ending twice (`c.emitStop()` added to `Manager.Stop`) | `TestStoppingAChannelRaisesChannelStop` | yes, **after the assertion was made exact** | `the control plane saw 2 channel_stop events, want exactly 1: a channel announces its ending from ONE place, run's deferred emitStop (Ruling R9)`. **It stayed green 6/6 in the at-least-one shape**: `eventsOf` returns as soon as the first event lands, so a second raise arriving a moment later was invisible to the `len()` check immediately after. Closing the emitter before counting is what makes "exactly one" mean it — Constraint 55's latch hazard, relocated from a wait into an assertion |

### The nine statements Gate 2 found uncovered, and what closed each

`missing` is a maximum, so an uncovered new statement is a gate failure however green the label is. The first measurement of this PR's tree named nine, all in `apps/proxy/authorize_views.py`, and five tests close all nine. **One of them was not a coverage gap at all.**

| Line | What it is | What closed it |
|---|---|---|
| 475, 476 | `except UnicodeError: pass` — a `uri` whose path cannot be latin-1 encoded | `test_a_uri_whose_path_is_not_latin_1_is_resolved_as_it_arrived`, a path with a character above U+00FF. The same arm in `authorize_view` (327-328) stays uncovered, and this one need not have |
| 497 | `HTTP_AUTHORIZATION` set from the body | `test_every_credential_header_reaches_the_authenticator_union`, the `Authorization: ApiKey …` row |
| 501 | `HTTP_X_API_KEY` set from the body | **The same test, and it failed 200 where it must give 401 — Ruling R13.** `source=` does not rename an INPUT field in DRF, so the hyphenated key never arrived. Three lines of `to_internal_value` |
| 553, 554 | `Resolver404` → 404 | `test_a_uri_with_no_path_at_all_is_404`. An ordinary unmatched path cannot reach it — the SPA catch-all resolves almost everything, which is why `authorize_view`'s own arm is uncovered — so the reachable case is an empty path |
| 558 | `surface is None` → 403 | `test_a_uri_that_resolves_to_a_non_streaming_view_is_403`, against `/_dispatcharr/authorize` itself |
| 560, 566 | the XC catch-up identity, and the native catch-up `session_id` | `test_the_two_catch_up_surfaces_take_their_identity_from_the_query` |

After: **zero added-and-missing lines in all three in-scope files**, and `missing` 1497-1498 against the floor's 1525.

**Five rows stayed green on a first attempt and each produced a better test or less code.** 2 and 3: the golden pins the encoder and its fixture supplied both values the builder computes — `detail_builder_test.go` exists because of them. 9: the fMP4 read stopped at the init segment, before the fragment loop had run once. 10: every denial row carried a body, so the branch that handles a body-less one was never entered. 3b deleted an unreachable guard. **25 was green in its at-least-one shape** until the assertion stopped racing the second raise. **18 was green against the test that originally produced its panic**, because `net/http` recovers a panic in a request goroutine — the pin moved to the mechanism.

---

## What to report back

In the order of Task 10 Step 8, plus: the merged 2c-7 SHA you seeded from and whether Task 0 found any drift; the three one-mechanism counts before and after; the un-Go'd row count before and after with the two `white-box-only` rows named; the two `[#NNN]` slots and the issue number you filed; and any of this plan's twenty-four break-checks that behaved differently on your tree, with the clause that fired.

---
## Appendix — the files, in full

### Appendix A — `relay/buffer/sample.go`

The diagnostic shape of the n newest resident chunks. Three scalars per chunk and no slice, so the borrowed-slice contract (Constraint 19) does not reach it.

**`relay/buffer/sample.go`**

```go
package buffer

// SampleChunk is one resident chunk's diagnostic shape: what
// get_detailed_channel_info's buffer-health walk reads out of Redis for each
// of the last few chunk keys (channel_status.py:235-266) without handing the
// caller the chunk's bytes.
//
// FirstByte is the `first_byte` diagnostic (:265), which for a whole TS
// packet is always 0x47. Reported rather than asserted, exactly as there:
// the diagnostic exists so an operator can see a ring that is NOT aligned.
type SampleChunk struct {
	Index     uint64
	Size      int
	FirstByte byte
}

// Sample is the n highest-indexed resident chunks, oldest first.
//
// The Redis walk it replaces iterates the index range [head-n+1, head] and
// splits it into keys_found and keys_missing (channel_status.py:243-268),
// because a chunk key can expire out from under the index. This returns only
// what is resident and lets the caller derive the missing half from head and
// n, which is the same split from the same two facts -- and the reason a
// chunk can be missing here is eviction rather than a TTL, the one
// difference spec D2 makes to this diagnostic.
func (r *Ring) Sample(n int) []SampleChunk {
	if n <= 0 {
		return nil
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	if len(r.chunks) == 0 {
		return nil
	}
	from := 0
	if len(r.chunks) > n {
		from = len(r.chunks) - n
	}
	out := make([]SampleChunk, 0, len(r.chunks)-from)
	for _, c := range r.chunks[from:] {
		sample := SampleChunk{Index: c.Index, Size: len(c.Data)}
		if len(c.Data) > 0 {
			sample.FirstByte = c.Data[0]
		}
		out = append(out, sample)
	}
	return out
}
```

### Appendix B — `relay/channel/clientstats.go`

The per-client meter. Read `ClientStats`'s doc comment first: which fields exist is a property of the OUTPUT FORMAT, and `Sends` is what makes that a mechanism rather than a check in the renderer (Ruling R8).

**`relay/channel/clientstats.go`**

```go
package channel

import (
	"math"
	"sync"
	"time"
)

// ClientStats is one client's transfer counters, the in-memory form of the
// four fields output/ts/generator.py:508-519 writes into the client's Redis
// hash and get_detailed_channel_info reads back out of it
// (channel_status.py:196-213).
//
// WHICH FIELDS EXIST IS A PROPERTY OF THE OUTPUT FORMAT, not of this type,
// and that asymmetry is Python's. The TS generator writes chunks_sent,
// bytes_sent, avg_rate_KBps, current_rate_KBps and last_active
// (output/ts/generator.py:511-519). The fMP4 generator writes last_active
// and NOTHING ELSE (output/fmp4/generator.py:288-295), so an fMP4 client's
// hash never carries a byte counter and the detail endpoint's three
// `if ... in client_data` guards all miss. Sent is what a TS client calls
// and Touch is what an fMP4 client calls, so the absence has a mechanism
// here rather than a format check in the renderer.
type ClientStats struct {
	// Sends is how many times Sent has been called. Zero means no byte
	// counter was ever recorded, which is what makes BytesSent, AvgRateKBps
	// and CurrentRateKBps absent from the wire rather than zero.
	Sends int64

	// ChunksSent and BytesSent are the TS generator's own counters
	// (:480-481). A keepalive packet counts toward BytesSent there (:392)
	// and here.
	ChunksSent int64
	BytesSent  int64

	// AvgRateKBps is bytes_sent / (now - stream_start) / 1024 (:488), and
	// CurrentRateKBps is the same arithmetic over the gap since the previous
	// Sent call (:491-495). Both are rounded to one decimal place where
	// Python rounds them on the way into Redis (:515-516).
	AvgRateKBps     float64
	CurrentRateKBps float64

	// LastActive is when this client last received bytes, or ConnectedAt
	// when it has received none: client_manager.py:239 seeds the hash field
	// with connected_at at registration.
	LastActive time.Time
}

// clientMeter is the live counter behind ClientStats. One per registered
// client, installed by addClient, shared by the serving goroutine that writes
// it and the status handler that reads it -- hence the mutex, which -race
// would otherwise report on every detail request against a running channel.
type clientMeter struct {
	mu sync.Mutex

	startedAt  time.Time
	lastActive time.Time

	sends      int64
	chunks     int64
	bytes      int64
	currentKBs float64

	// lastStatsAt and lastStatsBytes are output/ts/generator.py:498-499's
	// last_stats_time and last_stats_bytes: updated on EVERY yielded chunk,
	// so current_rate is the rate over one chunk's interval rather than over
	// a sampling window.
	lastStatsAt    time.Time
	lastStatsBytes int64
}

func newClientMeter(at time.Time) *clientMeter {
	return &clientMeter{startedAt: at, lastActive: at, lastStatsAt: at}
}

// Sent records one write to a TS client's socket: n bytes, at `at`.
//
// Called once per chunk rather than once per Read, because the Python
// counter increments inside the `for chunk in chunks` loop (:477-481) and
// current_rate is derived from the gap between consecutive chunks.
func (c Client) Sent(n int, at time.Time) {
	if c.meter == nil {
		return
	}
	m := c.meter
	m.mu.Lock()
	defer m.mu.Unlock()
	m.sends++
	m.chunks++
	m.bytes += int64(n)
	m.lastActive = at
	if elapsed := at.Sub(m.lastStatsAt); elapsed > 0 {
		m.currentKBs = float64(m.bytes-m.lastStatsBytes) / elapsed.Seconds() / 1024
	}
	m.lastStatsAt = at
	m.lastStatsBytes = m.bytes
}

// Touch records that an fMP4 client received bytes, and nothing else:
// output/fmp4/generator.py:288-295 writes last_active and no counter.
func (c Client) Touch(at time.Time) {
	if c.meter == nil {
		return
	}
	m := c.meter
	m.mu.Lock()
	defer m.mu.Unlock()
	m.lastActive = at
}

// Stats is this client's counters as of `at`.
//
// AvgRateKBps is computed at read time from the elapsed wall clock, where
// Python computes it when it writes the hash; the value is the same
// arithmetic over a slightly later `now`. CurrentRateKBps is the stored
// per-chunk rate, because it is a measurement over an interval that has
// already passed and recomputing it here would divide by the gap since the
// last chunk instead.
func (c Client) Stats(at time.Time) ClientStats {
	if c.meter == nil {
		return ClientStats{LastActive: c.ConnectedAt}
	}
	m := c.meter
	m.mu.Lock()
	defer m.mu.Unlock()
	out := ClientStats{
		Sends:           m.sends,
		ChunksSent:      m.chunks,
		BytesSent:       m.bytes,
		CurrentRateKBps: round1(m.currentKBs),
		LastActive:      m.lastActive,
	}
	if elapsed := at.Sub(m.startedAt).Seconds(); elapsed > 0 {
		out.AvgRateKBps = round1(float64(m.bytes) / elapsed / 1024)
	}
	return out
}

// round1 is Python's round(x, 1) at output/ts/generator.py:515-516. Go's
// math.Round is half-away-from-zero and Python's round() is banker's, which
// differ only on an exact .x5 of a rate computed from a byte count over a
// wall-clock interval. Recorded as a stated divergence rather than emulated:
// banker's rounding to one place would need a decimal library and this
// module is stdlib-only (Global Constraint 3).
func round1(v float64) float64 {
	return math.Round(v*10) / 10
}
```

### Appendix C — `relay/channel/client.go`

Two unexported fields and one exported accessor. Unexported so nothing outside this package can build a `Client` that reports counters nobody is writing.

**`relay/channel/client.go`**

```diff
--- a/channel/client.go
+++ b/channel/client.go
@@ -63,4 +63,23 @@
 
 	// ConnectedAt is when the client attached.
 	ConnectedAt time.Time
+
+	// meter is this client's transfer counters (clientstats.go), installed
+	// by addClient and shared with every value copy ClientSnapshot hands
+	// out. Unexported so nothing outside this package can build a Client
+	// that reports counters nobody is writing.
+	meter *clientMeter
+
+	// stop is closed by StopClient: the in-memory form of
+	// live:channel:{id}:clients:{cid}:stop, the key
+	// ChannelService.stop_client SETEXes and the generator's loop polls
+	// (services/channel_service.py:665-673). Installed by addClient, so a
+	// Client that was never registered has a nil channel and Stopped()
+	// blocks for ever -- which is the correct answer for a client nothing
+	// can stop.
+	stop chan struct{}
 }
+
+// Stopped is closed when an admin has asked for this client to go away.
+// serveClient and serveFMP4 derive their context from it.
+func (c Client) Stopped() <-chan struct{} { return c.stop }
```

### Appendix D — `relay/channel/channel.go`

Five changes: `addClient` installs the meter and the stop signal; `StopClient`; `setState` records `stateChangedAt`; the three accessors the detail endpoint needs; and `emitStop` with its deferred position (Ruling R9 -- BEFORE `close(c.done)`).

**`relay/channel/channel.go`**

```diff
--- a/channel/channel.go
+++ b/channel/channel.go
@@ -27,6 +27,7 @@
 	"errors"
 	"io"
 	"log/slog"
+	"math"
 	"sort"
 	"sync"
 	"time"
@@ -118,6 +119,9 @@
 	mu      sync.RWMutex
 	state   State
 	lastErr error
+	// stateChangedAt is ChannelMetadataField.STATE_CHANGED_AT, set by
+	// setState on every transition.
+	stateChangedAt time.Time
 	// source is what the channel is playing NOW. Guarded by mu since 2c-5,
 	// because a failover rewrites it (input/manager.py:2160-2171's hset).
 	source SourceInfo
@@ -214,10 +218,49 @@
 	if _, taken := c.clients[cl.ID]; taken {
 		return false
 	}
+	// The counters and the stop signal are installed HERE rather than by the
+	// caller, so a Client that reached the registry always has both and one
+	// that did not has neither: Sent, Touch and Stats are no-ops on a nil
+	// meter, and Stopped() on a nil channel blocks for ever, which is the
+	// right answer for a client nothing can stop.
+	cl.meter = newClientMeter(cl.ConnectedAt)
+	cl.stop = make(chan struct{})
 	c.clients[cl.ID] = cl
 	return true
 }
 
+// StopClient signals one client to disconnect: ChannelService.stop_client's
+// stop key (services/channel_service.py:665-673), which the generator's loop
+// polls and answers by returning.
+//
+// IT DOES NOT REMOVE THE CLIENT FROM THE REGISTRY, deliberately. The serving
+// goroutine's deferred release is the one mechanism by which a client leaves
+// (Global Constraint 18), and removing it here would be a second one --
+// which matters more than it sounds, because release is also what decides
+// whether the channel was left idle. Python removes it here AND lets the
+// generator's own cleanup remove it again (`if self.client_id in
+// client_manager.clients`, output/ts/generator.py:643), so the registry is
+// the same shape either way; only the number of mechanisms differs.
+//
+// Reports whether a client of that id was registered, which is
+// stop_client's locally_processed.
+func (c *Channel) StopClient(id string) bool {
+	c.mu.Lock()
+	defer c.mu.Unlock()
+	cl, registered := c.clients[id]
+	if !registered || cl.stop == nil {
+		return false
+	}
+	select {
+	case <-cl.stop:
+		// Already signalled. Closing twice panics, and a second DELETE for
+		// the same client is an ordinary thing for an admin to do.
+	default:
+		close(cl.stop)
+	}
+	return true
+}
+
 // dropClient removes one client and reports how many remain.
 func (c *Channel) dropClient(id string) int {
 	c.mu.Lock()
@@ -289,6 +332,16 @@
 	}
 }
 
+// Resolver is the channel's own resolver, the one its tune built. Exported
+// so the operator-switch handler can reuse the SAME source builder the tune
+// and every failover use, rather than assembling a second one out of the
+// request: Python's update_url keeps the manager's own transcode flag and
+// stream profile across a switch (input/manager.py:1462-1540), so a second
+// builder here would be free to disagree with it.
+//
+// Nil for a channel with no failover, which is a test shape.
+func (c *Channel) Resolver() Resolver { return c.resolver }
+
 // Source is what the next-source answer said about this channel's stream --
 // the CURRENT one, after any failover.
 func (c *Channel) Source() SourceInfo {
@@ -303,12 +356,48 @@
 func (c *Channel) setState(state State, err error) {
 	c.mu.Lock()
 	defer c.mu.Unlock()
+	if state != c.state {
+		// state_changed_at (ChannelMetadataField.STATE_CHANGED_AT), written
+		// beside every state hset and read by the detail endpoint
+		// (channel_status.py:124-127). On a CHANGE only: Python writes the
+		// pair together, so a re-assertion of the same state moves it there
+		// too -- but every Python writer asserts a state it is entering,
+		// never one it is already in, so the two agree on every reachable
+		// path and this guard makes the field mean what its name says.
+		c.stateChangedAt = c.now()
+	}
 	c.state = state
 	if err != nil {
 		c.lastErr = err
 	}
 }
 
+// StateChangedAt is when State last changed, for the detail endpoint's
+// state_changed_at and state_duration (channel_status.py:124-127).
+func (c *Channel) StateChangedAt() time.Time {
+	c.mu.RLock()
+	defer c.mu.RUnlock()
+	return c.stateChangedAt
+}
+
+// Local is the detail endpoint's local_manager block
+// (channel_status.py:315-322): the four StreamManager fields the answering
+// process can only report because it holds the manager. This relay always
+// holds it for a channel in its map, so the block is never absent here where
+// Python omits it on a non-owning worker.
+type Local struct {
+	Healthy   bool
+	Connected bool
+	LastData  time.Time
+}
+
+// Local is a snapshot of those four fields.
+func (c *Channel) Local() Local {
+	c.mu.RLock()
+	defer c.mu.RUnlock()
+	return Local{Healthy: c.healthy, Connected: c.connected, LastData: c.lastData}
+}
+
 // attachable is the optional interface a Source implements to be handed the
 // channel it runs on, for stats and state. TranscodeSource does; ProxySource
 // has nothing to report and does not. Checked once, in run, so a source is
@@ -346,6 +435,11 @@
 func (c *Channel) run(ctx context.Context, first Source) {
 	defer c.releaseSlot()
 	defer close(c.done)
+	// BEFORE close(c.done), and that ordering is load-bearing: stop() returns
+	// the moment done closes, so an emit after it would race the SIGTERM
+	// drain's own emitter flush and lose the last channel_stop of a
+	// shutdown -- the one it most matters to keep.
+	defer c.emitStop()
 	defer c.ring.Close()
 	// stop_all_output_formats (server.py:1771), in the one place a channel
 	// ends. Deferred calls run last-in first-out, so this runs BEFORE the ring
@@ -531,6 +625,38 @@
 	}
 }
 
+// emitStop is channel_stop (live_proxy/server.py:1568-1601): the runtime and
+// the byte total, snapshotted as the channel ends.
+//
+// RAISED FROM THE ONE PLACE A CHANNEL ENDS, where Python raises it from
+// ProxyServer.stop_channel's owner branch (:1827, :1842) -- which the admin
+// stop, the last-client disconnect sweep and the orphan sweep all reach, and
+// which a channel whose sources are exhausted reaches through the cleanup
+// thread. One mechanism here, several there, and the set of endings that
+// announce themselves is the same or slightly larger: a stated divergence in
+// the safe direction, since an ending that raised nothing would be a missing
+// event rather than a spurious one.
+//
+// channel_name falls back to the channel's id exactly as
+// _collect_channel_stop_event_data's `or str(channel_id)` does (:1570).
+func (c *Channel) emitStop() {
+	name := c.channelName
+	if name == "" {
+		name = c.id
+	}
+	// round(time.time() - init_time, 2) at :1577.
+	runtime := math.Round(c.now().Sub(c.startedAt).Seconds()*100) / 100
+	c.events.Emit(Event{
+		Type:        "channel_stop",
+		ChannelID:   c.id,
+		ChannelName: name,
+		Details: map[string]any{
+			"runtime":     runtime,
+			"total_bytes": c.ring.TotalBytes(),
+		},
+	})
+}
+
 // releaseSlot gives the provider slot back once the source goroutine has
 // returned: the one place this relay releases, where the Python relay
 // releases from the stop path's _release_stream_resources
```

### Appendix E — `relay/channel/manager.go`

Four changes: `publish` seeds an empty client map and calls `addClient` (Ruling R4); it seeds `stateChangedAt`; it raises `channel_start`; and `StopAll` becomes concurrent (Ruling R11's arithmetic).

**`relay/channel/manager.go`**

```diff
--- a/channel/manager.go
+++ b/channel/manager.go
@@ -260,13 +260,19 @@
 		outputRegistry: outputRegistry{outputs: map[string]*outputEntry{}},
 		outputProfiles: started.OutputProfiles,
 		startedAt:      now(),
+		// Seeded here, not left zero, because state is assigned in this
+		// literal rather than through setState: Python writes state and
+		// state_changed_at together in initialize_channel
+		// (services/channel_service.py:276-380), so a channel has always had
+		// one by the time any status read can see it.
+		stateChangedAt: now(),
 		now:            now,
 		resolver:       started.Resolver,
 		events:         events,
 		release:        m.cfg.Release,
 		ctx:            ctx,
 		state:          StateInitializing,
-		clients:        map[string]*Client{client.ID: client},
+		clients:        map[string]*Client{},
 		// StreamManager.__init__ (input/manager.py:76-78, :93-96): healthy
 		// until the monitor says otherwise, the initial stream already in
 		// the tried set, and the failure window from the tune's settings.
@@ -281,11 +287,31 @@
 	if started.Info.StreamID != 0 {
 		c.tried[started.Info.StreamID] = true
 	}
+	// THROUGH addClient, not by seeding the map literal above with
+	// {client.ID: client}. addClient is where a registered client gets its
+	// transfer counters and its stop signal (clientstats.go, client.go), and
+	// the literal skipped both -- so the FIRST client of every channel had a
+	// nil meter and could not be stopped by id, while the second and every
+	// later one could. Found by
+	// TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming, whose
+	// DELETE reported locally_processed false for a client the registry was
+	// listing. One mechanism (Global Constraint 18).
+	c.addClient(client)
 
 	m.mu.Lock()
 	m.channels[id] = c
 	m.mu.Unlock()
 
+	// channel_start (live_proxy/server.py:832-842), raised where Python
+	// raises it: right after the StreamManager is constructed and installed,
+	// and before its goroutine starts. stream_name and stream_id are the two
+	// details it carries; emit lifts stream_id to the top level and leaves it
+	// in details, as emit_event does.
+	c.emit("channel_start", map[string]any{
+		"stream_name": started.Info.StreamName,
+		"stream_id":   started.Info.StreamID,
+	})
+
 	go c.run(ctx, started.Source)
 	return c
 }
@@ -320,13 +346,30 @@
 	return c
 }
 
-// StopAll tears every channel down. The SIGTERM drain that calls it in
-// anger is 2c-8's; this exists so a test and a shutdown path have one way to
-// do it.
+// StopAll tears every channel down, CONCURRENTLY, and returns once every one
+// of them has stopped or timed out.
+//
+// Concurrent since 2c-8, and the drain is why. Stop waits up to
+// cfg.StopWait (5s) for one channel's source goroutine, so a sequential walk
+// costs N x StopWait in the worst case -- ten channels is fifty seconds
+// against a supervisord stopwaitsecs of twenty, which SIGKILLs the process
+// mid-teardown and loses every release and every channel_stop. Concurrent,
+// the whole sweep costs StopWait however many channels there are, because
+// the waits overlap.
+//
+// Nothing here is shared between the goroutines: each takes its own channel
+// out of the map under m.mu (take) and then works on an object nobody else
+// holds.
 func (m *Manager) StopAll() {
+	var wg sync.WaitGroup
 	for _, id := range m.ids() {
-		m.Stop(id)
+		wg.Add(1)
+		go func() {
+			defer wg.Done()
+			m.Stop(id)
+		}()
 	}
+	wg.Wait()
 }
 
 func (m *Manager) ids() []string {
```

### Appendix F — `relay/channel/failover.go`

`applySwitch` factored out, byte for byte and in the same order, so `failover`'s behaviour is unchanged and `Advance` becomes its second caller. The tried-set bookkeeping deliberately stays with each caller: `failover` records the candidate BEFORE the URL check and `update_url` records it AFTER.

**`relay/channel/failover.go`**

```diff
--- a/channel/failover.go
+++ b/channel/failover.go
@@ -225,6 +225,36 @@
 	}
 
 	c.log.Info("switching stream", "channel", c.id, "trigger", why, "stream", resolved.Info.StreamID, "m3u_profile", resolved.Info.M3UProfileID)
+	c.applySwitch(resolved)
+
+	c.mu.Lock()
+	degradedBefore := c.failoverDegraded
+	c.failoverDegraded = resolved.Degraded
+	c.mu.Unlock()
+	if !resolved.Degraded && degradedBefore {
+		// Django is answering again: say, once, that an earlier failover ran
+		// blind on the cached list and may have exceeded max_streams
+		// (:2191-2202).
+		c.emit("channel_error", map[string]any{"reason": "degraded_failover"})
+	}
+	return resolved, true
+}
+
+// applySwitch is update_url's success path (input/manager.py:1479-1530)
+// minus the connection teardown, which a Source's own cancellation does:
+// the packetiser is reset, the source info and the current stream id are
+// swapped, the failure history is cleared and stream_switch is raised.
+//
+// ONE MECHANISM FOR TWO CALLERS (Global Constraint 18). An automatic
+// failover reaches it through failover() above and an operator's switch
+// reaches it through Advance (advance.go), which is exactly the sharing
+// Python has -- _try_next_stream calls update_url (:2139) and
+// ChannelService.change_stream_url calls the same method (:493). What the
+// two do NOT share is the tried-set bookkeeping, which is why that stays
+// with each caller: failover records the candidate BEFORE it checks the URL
+// so a rejected candidate is still excluded next time, and update_url
+// records it AFTER, inside the success path.
+func (c *Channel) applySwitch(resolved Resolved) {
 	c.mu.Lock()
 	c.ring.ResetPosition()
 	c.source = resolved.Info
@@ -248,18 +278,6 @@
 		"new_url":   truncate(redact.Line(resolved.Info.URL), 100),
 		"stream_id": resolved.Info.StreamID,
 	})
-
-	c.mu.Lock()
-	degradedBefore := c.failoverDegraded
-	c.failoverDegraded = resolved.Degraded
-	c.mu.Unlock()
-	if !resolved.Degraded && degradedBefore {
-		// Django is answering again: say, once, that an earlier failover ran
-		// blind on the cached list and may have exceeded max_streams
-		// (:2191-2202).
-		c.emit("channel_error", map[string]any{"reason": "degraded_failover"})
-	}
-	return resolved, true
 }
 
 // failoverFromBuffering is the stderr reader's entry: _parse_ffmpeg_stats'
```

### Appendix G — `relay/httpapi/detail.go`

`get_detailed_channel_info`, field for field and in `RelayChannelDetailSerializer`'s declaration order. Ruling R7 is in the type's own doc comment: the two fields nothing writes, the four Redis-only diagnostics, and why `keys_missing` alone is a pointer.

**`relay/httpapi/detail.go`**

```go
package httpapi

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
)

// OwnerUnknown is the detail endpoint's owner default: the literal string
// channel_status.py:45 substitutes when the metadata hash carries no owner
// field, where the LIST endpoint's builder passes None through
// (channel_status.py:474). That asymmetry is parity-matrix row 14 and it is
// carried, not fixed -- spec D5, and CLAUDE.md § Observing a channel records
// it as a field that misleads.
//
// With one relay process and no election there is never an owner to name, so
// this is what every channel reports here, exactly as `owner: null` is what
// every channel reports on the list.
const OwnerUnknown = "unknown"

// WorkerUnknown is the same default one level down: a detail client row's
// worker_id, which channel_status.py:181 fills with 'unknown' when the client
// hash has none. D2 deletes the worker concept outright, so it is what every
// client reports here.
const WorkerUnknown = "unknown"

// detailBufferSample is how many recent chunks the buffer-health walk looks
// at: `min(5, buffer_index)` at channel_status.py:237.
const detailBufferSample = 5

// detailClientPayload is one row of get_detailed_channel_info's clients list,
// field for field and IN DECLARATION ORDER with
// apps/proxy/relay_serializers.py's RelayDetailClientSerializer.
//
// THE FIRST SEVEN ARE ALWAYS PRESENT because channel_status.py:178-191
// assigns each with a fallback default; the last six are conditional on a key
// being in the client's hash, and WHICH of them can be is a property of the
// output format (clientstats.go). connected_at and last_active are always
// present here because client_manager.py:237-239 seeds both at registration,
// so their `if ... in client_data` guards cannot miss in a real deployment.
type detailClientPayload struct {
	ClientID        string   `json:"client_id"`
	UserAgent       string   `json:"user_agent"`
	WorkerID        string   `json:"worker_id"`
	IPAddress       string   `json:"ip_address"`
	UserID          string   `json:"user_id"`
	OutputFormat    string   `json:"output_format"`
	OutputProfileID *int     `json:"output_profile_id"`
	ConnectedAt     float64  `json:"connected_at"`
	LastActive      float64  `json:"last_active"`
	LastActiveAgo   float64  `json:"last_active_ago"`
	BytesSent       *int64   `json:"bytes_sent,omitempty"`
	AvgRateKBps     *float64 `json:"avg_rate_KBps,omitempty"`
	CurrentRateKBps *float64 `json:"current_rate_KBps,omitempty"`
}

// bufferStatsPayload is get_detailed_channel_info's buffer_stats
// (channel_status.py:229-312), which the serializer declares as a free-form
// DictField "because buffer_stats carries a diagnostics sub-dict whose keys
// depend on which Redis probe found something, and pinning it would turn a
// diagnostic into a contract".
//
// FOUR KEYS PYTHON EMITS ARE NOT HERE, and each is a Redis fact rather than a
// buffer fact, so emitting one would mean inventing a number:
//
//	latest_chunk_ttl              a TTL on a chunk key (:308-310). This ring
//	                              bounds itself by byte budget AND age (D2),
//	                              and reporting the age bound as a TTL would
//	                              name a mechanism that is not the one doing
//	                              the work.
//	diagnostics.all_buffer_keys   a SCAN of live:channel:*:input:buffer:chunk:*
//	diagnostics.total_buffer_keys (:286-300), reached only when no sampled
//	                              chunk was found -- a debugging aid for keys
//	                              that have expired out from under the index,
//	                              which cannot happen to a slice.
//	error / diagnostics.exception the Redis walk's own except arm (:302-305).
//
// keys_missing keeps its meaning and changes its cause: there, a chunk key
// that expired; here, one evicted by the byte budget or the retention bound.
type bufferStatsPayload struct {
	Chunks           uint64         `json:"chunks"`
	Diagnostics      map[string]any `json:"diagnostics"`
	AvgChunkSize     *float64       `json:"avg_chunk_size,omitempty"`
	RecentChunkSizes []int          `json:"recent_chunk_sizes,omitempty"`
	KeysFound        []uint64       `json:"keys_found,omitempty"`
	// A POINTER, alone among the four slice fields, because it is the only
	// one that can legitimately be EMPTY: channel_status.py:275 assigns
	// keys_missing inside the same `if chunk_sizes:` arm as keys_found, so a
	// fully resident sample renders "keys_missing": [] rather than omitting
	// the key. `[]uint64` with omitempty would drop it, and without
	// omitempty a nil would render null in the arm where Python omits it
	// entirely.
	KeysMissing      *[]uint64 `json:"keys_missing,omitempty"`
	TotalSampleBytes *int      `json:"total_sample_bytes,omitempty"`
	EstimatedPackets *int      `json:"estimated_ts_packets,omitempty"`
	IsTSAligned      *bool     `json:"is_ts_aligned,omitempty"`
}

// localManagerPayload is channel_status.py:315-322's local_manager: the four
// StreamManager fields only the process holding the manager can answer.
// Always present here, where Python omits the block on a worker that is not
// the owner -- with one process there is no non-owning worker to be.
type localManagerPayload struct {
	Healthy      bool    `json:"healthy"`
	Connected    bool    `json:"connected"`
	LastDataTime float64 `json:"last_data_time"`
	LastDataAge  float64 `json:"last_data_age"`
}

// detailPayload is get_detailed_channel_info, field for field and in
// RelayChannelDetailSerializer's declaration order.
//
// TWO FIELDS THE SERIALIZER DECLARES ARE ABSENT HERE AND UNREACHABLE THERE,
// which is exact parity by doing nothing -- the same shape as logo_id on the
// list endpoint (channels.go):
//
//	source_bitrate  ChannelMetadataField.SOURCE_BITRATE has NO WRITER in the
//	                tree. channel_status.py:359 is its only reference beside
//	                the constant itself.
//	ffmpeg_bitrate  channel_status.py:404 reads ChannelMetadataField
//	                .FFMPEG_BITRATE ("ffmpeg_bitrate"), and the writer at
//	                input/manager.py:1269 writes FFMPEG_OUTPUT_BITRATE
//	                ("ffmpeg_output_bitrate"), which nothing reads. The two
//	                constants are different strings (constants.py:90-91), so
//	                the operator's output-bitrate reading never reaches this
//	                payload in either relay.
//
// Both are reproduced as absences per D5 and filed rather than fixed.
type detailPayload struct {
	ChannelID      string                `json:"channel_id"`
	State          *string               `json:"state"`
	URL            string                `json:"url"`
	StreamProfile  string                `json:"stream_profile"`
	StartedAt      float64               `json:"started_at"`
	Owner          string                `json:"owner"`
	BufferIndex    uint64                `json:"buffer_index"`
	ChannelName    string                `json:"channel_name,omitempty"`
	StreamID       *int                  `json:"stream_id,omitempty"`
	StreamName     string                `json:"stream_name,omitempty"`
	M3UProfileID   *int                  `json:"m3u_profile_id,omitempty"`
	M3UProfileName string                `json:"m3u_profile_name,omitempty"`
	StateChangedAt float64               `json:"state_changed_at"`
	StateDuration  float64               `json:"state_duration"`
	Uptime         float64               `json:"uptime"`
	TotalBytes     *uint64               `json:"total_bytes,omitempty"`
	TotalData      string                `json:"total_data,omitempty"`
	AvgBitrateKbps *float64              `json:"avg_bitrate_kbps,omitempty"`
	AvgBitrate     string                `json:"avg_bitrate,omitempty"`
	ClientCount    int                   `json:"client_count"`
	BufferStats    bufferStatsPayload    `json:"buffer_stats"`
	LocalManager   localManagerPayload   `json:"local_manager"`
	VideoCodec     string                `json:"video_codec,omitempty"`
	Resolution     string                `json:"resolution,omitempty"`
	Width          string                `json:"width,omitempty"`
	Height         string                `json:"height,omitempty"`
	VideoBitrate   string                `json:"video_bitrate,omitempty"`
	SourceFPS      string                `json:"source_fps,omitempty"`
	PixelFormat    string                `json:"pixel_format,omitempty"`
	AudioCodec     string                `json:"audio_codec,omitempty"`
	SampleRate     string                `json:"sample_rate,omitempty"`
	AudioChannels  string                `json:"audio_channels,omitempty"`
	AudioBitrate   string                `json:"audio_bitrate,omitempty"`
	FFmpegSpeed    *float64              `json:"ffmpeg_speed,omitempty"`
	FFmpegFPS      string                `json:"ffmpeg_fps,omitempty"`
	ActualFPS      string                `json:"actual_fps,omitempty"`
	StreamType     string                `json:"stream_type,omitempty"`
	Clients        []detailClientPayload `json:"clients"`
}

// statePayload is RelayChannelStateSerializer: the two-field answer to
// ?fields=state, and the body of every 404 from this route.
//
// Its own type rather than a partial detailPayload, for the reason that
// serializer's own docstring gives: DRF renders a missing key as null on a
// field that is allow_null, so a partial render of the detail shape would put
// "url": null, "stream_profile": null and "owner": null into an answer that
// knows none of them.
type statePayload struct {
	ChannelID string  `json:"channel_id"`
	State     *string `json:"state"`
}

// ChannelHandler serves GET and DELETE on /proxy/relay/channels/{channelID}.
//
// GET is what relay_client.get_channel calls, and through it
// /proxy/ts/status/<id>, next_stream's "what is playing now" read, the DVR's
// recording-metadata capture and its client sweep. With ?fields=state it is
// the tune path's own read (relay_client.channel_snapshot), under a two-second
// budget, which is why that branch answers from two in-memory fields rather
// than building the whole payload.
//
// DELETE is relay_client.stop_channel, wrapped by /proxy/ts/stop/<id>.
func ChannelHandler(deps ControlDeps) http.HandlerFunc {
	log := controlLog(deps)
	now := controlClock(deps)

	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("channelID")
		if r.Method == http.MethodDelete {
			writeJSON(w, log, stopResponse(deps.Channels, id))
			return
		}

		ch := deps.Channels.Get(id)
		if r.URL.Query().Get("fields") == "state" {
			if ch == nil {
				writeJSONStatus(w, log, http.StatusNotFound, statePayload{ChannelID: id})
				return
			}
			state := string(ch.State())
			writeJSON(w, log, statePayload{ChannelID: id, State: &state})
			return
		}
		if ch == nil {
			// get_detailed_channel_info returns None for a channel this relay
			// holds no metadata hash for, and relay_views.py:180-194 answers
			// 404 with the narrow serializer's shape. A 404 here is an
			// ANSWER -- "this channel is not running" -- which
			// relay_client.get_channel maps to None; every other refusal
			// propagates.
			writeJSONStatus(w, log, http.StatusNotFound, statePayload{ChannelID: id})
			return
		}
		writeJSON(w, log, describeChannelDetail(ch, now()))
	}
}

// describeChannelDetail renders one channel the way get_detailed_channel_info
// does.
func describeChannelDetail(c *channel.Channel, at time.Time) detailPayload {
	state := string(c.State())
	info := c.Source()
	uptime := at.Sub(c.StartedAt()).Seconds()

	out := detailPayload{
		ChannelID:     c.ID(),
		State:         &state,
		URL:           info.URL,
		StreamProfile: strconv.Itoa(info.StreamProfileID),
		StartedAt:     unixFloat(c.StartedAt()),
		// :45's literal default, and row 14's asymmetry with the list
		// endpoint's null.
		Owner:       OwnerUnknown,
		BufferIndex: c.Ring().Head(),
		ChannelName: info.ChannelName,
		StreamName:  info.StreamName,
		// :126-127 and :133, both unconditional here: Python guards each on
		// its metadata key being present, and both keys are written at
		// channel init, so neither guard can miss on a running channel.
		StateChangedAt: unixFloat(c.StateChangedAt()),
		StateDuration:  at.Sub(c.StateChangedAt()).Seconds(),
		Uptime:         uptime,
	}
	if info.M3UProfileID != 0 {
		id := info.M3UProfileID
		out.M3UProfileID = &id
		out.M3UProfileName = info.M3UProfileName
	}
	if info.StreamID != 0 {
		id := info.StreamID
		out.StreamID = &id
	}

	// :138-160: the byte total, its human-readable form, and the average
	// bitrate only once uptime is positive.
	if total := c.Ring().TotalBytes(); total > 0 {
		out.TotalBytes = &total
		out.TotalData = humanBytes(total)
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

	clients := c.ClientSnapshot()
	out.ClientCount = len(clients)
	out.Clients = make([]detailClientPayload, 0, len(clients))
	for _, cl := range clients {
		out.Clients = append(out.Clients, describeDetailClient(cl, at))
	}

	out.BufferStats = describeBufferStats(c.Ring())
	local := c.Local()
	out.LocalManager = localManagerPayload{
		Healthy:      local.Healthy,
		Connected:    local.Connected,
		LastDataTime: unixFloat(local.LastData),
		LastDataAge:  at.Sub(local.LastData).Seconds(),
	}

	// The stream-info and ffmpeg-performance fields, each only when the
	// reader set it (:325-410), and each spelled the way Python spells it in
	// the hash: str(round(x, n)) for a float, str(x) for an int.
	stats := c.Stats()
	if stats.VideoCodec != nil {
		out.VideoCodec = *stats.VideoCodec
	}
	if stats.Resolution != nil {
		out.Resolution = *stats.Resolution
	}
	if stats.Width != nil {
		out.Width = strconv.Itoa(*stats.Width)
	}
	if stats.Height != nil {
		out.Height = strconv.Itoa(*stats.Height)
	}
	if stats.VideoBitrate != nil {
		out.VideoBitrate = pythonFloat(*stats.VideoBitrate)
	}
	if stats.SourceFPS != nil {
		// A STRING here and a float on the list endpoint: row 14's third
		// clause, carried rather than fixed.
		out.SourceFPS = pythonFloat(*stats.SourceFPS)
	}
	if stats.PixelFormat != nil {
		out.PixelFormat = *stats.PixelFormat
	}
	if stats.AudioCodec != nil {
		out.AudioCodec = *stats.AudioCodec
	}
	if stats.SampleRate != nil {
		out.SampleRate = strconv.Itoa(*stats.SampleRate)
	}
	if stats.AudioChannels != nil {
		out.AudioChannels = *stats.AudioChannels
	}
	if stats.AudioBitrate != nil {
		out.AudioBitrate = pythonFloat(*stats.AudioBitrate)
	}
	// ffmpeg_speed is the one performance field the detail endpoint renders
	// as a FLOAT (:387-394's float() with its own except arm), and it agrees
	// with the list endpoint -- row 14's second clause, fixed by Phase 1 PR 7
	// and held fixed here.
	out.FFmpegSpeed = stats.FFmpegSpeed
	if stats.FFmpegFPS != nil {
		out.FFmpegFPS = pythonFloat(*stats.FFmpegFPS)
	}
	if stats.ActualFPS != nil {
		out.ActualFPS = pythonFloat(*stats.ActualFPS)
	}
	if stats.StreamType != nil {
		out.StreamType = *stats.StreamType
	}
	return out
}

// describeDetailClient renders one client row.
func describeDetailClient(cl channel.Client, at time.Time) detailClientPayload {
	stats := cl.Stats(at)
	row := detailClientPayload{
		ClientID:        cl.ID,
		UserAgent:       cl.UserAgent,
		WorkerID:        WorkerUnknown,
		IPAddress:       cl.IPAddress,
		UserID:          cl.UserID,
		OutputFormat:    cl.OutputFormat,
		OutputProfileID: cl.OutputProfileID,
		ConnectedAt:     unixFloat(cl.ConnectedAt),
		LastActive:      unixFloat(stats.LastActive),
		LastActiveAgo:   at.Sub(stats.LastActive).Seconds(),
	}
	// :202-213's three guards, all on a key the TS generator writes and the
	// fMP4 generator does not. Sends is what makes the absence a mechanism:
	// a client that has received no chunk has no counter, and an fMP4 client
	// never gets one however much it receives.
	if stats.Sends > 0 {
		bytesSent := stats.BytesSent
		avg := stats.AvgRateKBps
		current := stats.CurrentRateKBps
		row.BytesSent = &bytesSent
		row.AvgRateKBps = &avg
		row.CurrentRateKBps = &current
	}
	return row
}

// describeBufferStats is the buffer-health walk (channel_status.py:228-312)
// over the in-memory ring.
func describeBufferStats(ring *buffer.Ring) bufferStatsPayload {
	head := ring.Head()
	out := bufferStatsPayload{Chunks: head, Diagnostics: map[string]any{}}
	if head == 0 {
		// :235's `if info['buffer_index'] > 0`: nothing sampled, and the
		// diagnostics stay the empty dict :231 seeded.
		return out
	}

	sample := ring.Sample(detailBufferSample)
	// The index range Python walks: [head-min(5,head)+1, head] (:237, :243).
	want := uint64(detailBufferSample)
	if head < want {
		want = head
	}
	resident := map[uint64]bool{}
	sizes := make([]int, 0, len(sample))
	found := make([]uint64, 0, len(sample))
	total := 0
	aligned := true
	// NO INDEX FILTER HERE, and its absence is deliberate rather than an
	// omission: Ring.Sample(n) already returns at most n chunks and always
	// the newest ones, so every chunk it hands back is inside the window
	// [head-want+1, head] by construction. A guard for the other case was
	// written first and break-check 3b showed it could not be reached --
	// dead code a test cannot pin, so it is gone rather than kept.
	for _, chunk := range sample {
		resident[chunk.Index] = true
		sizes = append(sizes, chunk.Size)
		found = append(found, chunk.Index)
		total += chunk.Size
		if chunk.Size%buffer.TSPacketSize != 0 {
			aligned = false
		}
		if len(found) == 1 {
			// :258-266's first_chunk block, for the first chunk FOUND rather
			// than the first walked -- `if len(chunk_keys_found) == 1`.
			out.Diagnostics["first_chunk"] = map[string]any{
				"index":      chunk.Index,
				"size":       chunk.Size,
				"ts_packets": chunk.Size / buffer.TSPacketSize,
				"aligned":    chunk.Size%buffer.TSPacketSize == 0,
				"first_byte": chunk.FirstByte,
			}
		}
	}
	missing := make([]uint64, 0, want)
	for i := head - want + 1; i <= head; i++ {
		if !resident[i] {
			missing = append(missing, i)
		}
	}
	if len(sizes) == 0 {
		// :285-300's else arm is a Redis key scan with no analogue, and it
		// sets NEITHER keys_found NOR keys_missing -- both live inside the
		// `if chunk_sizes:` arm above it -- so the walk reports what it
		// found: nothing.
		return out
	}
	avg := float64(total) / float64(len(sizes))
	packets := total / buffer.TSPacketSize
	out.AvgChunkSize = &avg
	out.RecentChunkSizes = sizes
	out.KeysFound = found
	out.KeysMissing = &missing
	out.TotalSampleBytes = &total
	out.EstimatedPackets = &packets
	out.IsTSAligned = &aligned
	return out
}

// humanBytes is channel_status.py:141-149's total_data: bytes below 1 KiB,
// then KB, MB and GB to two decimal places, each over the 1024 boundary and
// each with Python's own unit spelling.
func humanBytes(total uint64) string {
	switch {
	case total < 1024:
		return fmt.Sprintf("%d B", total)
	case total < 1024*1024:
		return fmt.Sprintf("%.2f KB", float64(total)/1024)
	case total < 1024*1024*1024:
		return fmt.Sprintf("%.2f MB", float64(total)/(1024*1024))
	default:
		return fmt.Sprintf("%.2f GB", float64(total)/(1024*1024*1024))
	}
}

// unixFloat is the seconds-since-epoch float every timestamp on these
// payloads is: Python stores str(time.time()) and reads it back with float().
func unixFloat(t time.Time) float64 {
	if t.IsZero() {
		return 0
	}
	return float64(t.UnixNano()) / float64(time.Second)
}

// pythonFloat is str(round(x, n)) for the fields the detail endpoint renders
// as STRINGS because Python passes the hash's raw bytes through.
//
// The rounding is already done -- channel.Stats stores each value rounded the
// way its writer rounds it -- so this is only the str() half, and the one
// thing it has to get right is that PYTHON'S FLOAT REPR ALWAYS CARRIES A
// DECIMAL POINT: str(25.0) is "25.0", where Go's shortest form is "25". A
// status payload reporting a source_fps of "25" where the Python relay
// reports "25.0" is a wire difference on a field parity-matrix row 14 is
// about.
//
// The exponent forms Python switches to (1e+16 and below 1e-4) are out of
// range for every field here -- a frame rate, a sample rate and three
// bitrates in kbps -- and are not reproduced.
func pythonFloat(v float64) string {
	s := strconv.FormatFloat(v, 'f', -1, 64)
	if strings.ContainsRune(s, '.') {
		return s
	}
	return s + ".0"
}
```

### Appendix H — `relay/httpapi/control.go`

The two `DELETE`s, the `advance`, and the shared JSON writers. Three of `stopPayload`'s booleans mean something different here and each is answered honestly rather than faked (Ruling R6); three of `advancePayload`'s fields cannot be set by this relay and are absent rather than invented.

**`relay/httpapi/control.go`**

```go
package httpapi

import (
	"encoding/json"
	"log/slog"
	"net/http"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// controlLog and controlClock are the two nil-defaults every control handler
// applies, in one place rather than four.
func controlLog(deps ControlDeps) *slog.Logger {
	if deps.Log == nil {
		return slog.Default()
	}
	return deps.Log
}

func controlClock(deps ControlDeps) func() time.Time {
	if deps.Now == nil {
		return time.Now
	}
	return deps.Now
}

// writeJSON writes a 200 with body as JSON.
func writeJSON(w http.ResponseWriter, log *slog.Logger, body any) {
	writeJSONStatus(w, log, http.StatusOK, body)
}

// writeJSONStatus writes status with body as JSON.
//
// The encode happens BEFORE the header is written, so an encoding failure --
// unreachable, every field is a plain type -- answers 500 rather than a
// half-written 200 with a status already committed.
func writeJSONStatus(w http.ResponseWriter, log *slog.Logger, status int, body any) {
	encoded, err := json.Marshal(body)
	if err != nil {
		log.Error("encoding a control response failed", "error", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(encoded)
}

// stopPayload is RelayStopResponseSerializer, field for field and in its
// declaration order. Both DELETE routes answer with it.
//
// `status` is the service layer's own 'success' or 'error' travelling in the
// BODY rather than as an HTTP status, and the serializer's docstring says
// why: the relay answered, and "this channel is not running here" is an
// answer, not a refusal. The Django-side wrapper turns it into the 404 the
// admin API has always returned (live_proxy/views.py:1126-1129, :1179-1180).
type stopPayload struct {
	Status         string         `json:"status"`
	Message        string         `json:"message,omitempty"`
	ChannelID      string         `json:"channel_id,omitempty"`
	ClientID       string         `json:"client_id,omitempty"`
	PreviousState  *previousState `json:"previous_state,omitempty"`
	ModelReleased  *bool          `json:"model_released,omitempty"`
	LocallyHandled *bool          `json:"locally_processed,omitempty"`
	StopKeySet     *bool          `json:"stop_key_set,omitempty"`
	EventPublished *bool          `json:"event_published,omitempty"`
}

// previousState is the one-key dict ChannelService.stop_channel snapshots
// before the teardown (services/channel_service.py:606-615), which
// /proxy/ts/stop/<id> passes straight back to its caller.
type previousState struct {
	State string `json:"state"`
}

// stopResponse is ChannelService.stop_channel (services/channel_service.py:
// 588-630) over the in-memory map.
//
// The Redis half of that function -- the stopping key, the broadcast to
// other workers, the key sweep and the ownership release -- is deleted by
// D2 rather than ported: there is no second worker to tell and no key to
// delete. What remains is the part an admin can observe: the previous
// state, and the teardown itself.
func stopResponse(channels *channel.Manager, id string) stopPayload {
	ch := channels.Get(id)
	if ch == nil {
		// :603-604, verbatim. The two keys the success shape carries are
		// absent here exactly as they are there.
		return stopPayload{Status: "error", Message: "Channel not found"}
	}
	state := string(ch.State())
	released := channels.Stop(id)
	return stopPayload{
		Status:        "success",
		Message:       "Channel stop request sent",
		ChannelID:     id,
		PreviousState: &previousState{State: state},
		// bool(local_result) at :628. Manager.Stop reports whether it still
		// held the channel when it took the map entry, which is the same
		// question ProxyServer.stop_channel's return answers.
		ModelReleased: &released,
	}
}

// ClientHandler serves DELETE /proxy/relay/channels/{channelID}/clients/
// {clientID}: ChannelService.stop_client (services/channel_service.py:
// 653-714), which relay_client.stop_client calls and /proxy/ts/stop_client/
// wraps.
//
// THREE OF THE FOUR BOOLEANS MEAN SOMETHING DIFFERENT HERE, and each is
// answered honestly rather than faked:
//
//	stop_key_set     there, whether the SETEX of the client's stop key
//	                 succeeded -- attempted BEFORE the channel is looked up,
//	                 so it is true even for a channel that does not exist.
//	                 Here, whether a client of that id was signalled, because
//	                 the signal lives ON the client and cannot exist without
//	                 one.
//	locally_processed there, whether the client was on THIS worker. Here,
//	                 whether it was registered at all -- with one process the
//	                 two questions are the same question.
//	event_published  there, whether the stop was published over live:events
//	                 for another worker to act on. Always FALSE here: D2
//	                 deletes the pub/sub, and there is no other worker.
func ClientHandler(deps ControlDeps) http.HandlerFunc {
	log := controlLog(deps)
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("channelID")
		clientID := r.PathValue("clientID")
		ch := deps.Channels.Get(id)
		if ch == nil {
			// :679-684, including the stop_key_set the caller gets back.
			never := false
			writeJSON(w, log, stopPayload{
				Status:     "error",
				Message:    "Channel not found",
				StopKeySet: &never,
			})
			return
		}
		signalled := ch.StopClient(clientID)
		published := false
		writeJSON(w, log, stopPayload{
			Status:         "success",
			Message:        "Client stop request processed",
			ChannelID:      id,
			ClientID:       clientID,
			LocallyHandled: &signalled,
			StopKeySet:     &signalled,
			EventPublished: &published,
		})
	}
}

// advanceRequest is RelayAdvanceRequestSerializer plus the three fields 2c-8
// adds to it, which are what make this route servable by a relay that builds
// no command line (Amendment A4.1).
//
// url is required there (`serializers.CharField()` with no required=False)
// and so is stream_profile here: without it the relay has no argv to spawn
// and no way to tell a Proxy switch from a transcode one. Django holds both
// at every producer -- change_stream and next_stream each resolve the source
// in the API process before they call this route (ruling 11).
type advanceRequest struct {
	URL            string                    `json:"url"`
	UserAgent      string                    `json:"user_agent"`
	StreamID       *int                      `json:"stream_id"`
	M3UProfileID   *int                      `json:"m3u_profile_id"`
	StreamName     string                    `json:"stream_name"`
	ChannelName    string                    `json:"channel_name"`
	M3UProfileName string                    `json:"m3u_profile_name"`
	ResetTried     bool                      `json:"reset_tried"`
	Transcode      bool                      `json:"transcode"`
	StreamProfile  *control.StreamProfileRef `json:"stream_profile"`
	FFmpegProfile  *control.StreamProfileRef `json:"ffmpeg_stream_profile"`
}

// advancePayload is RelayAdvanceResponseSerializer, field for field and in
// its declaration order.
//
// THREE OF ITS FIELDS CANNOT BE SET BY THIS RELAY, and each is absent rather
// than invented:
//
//	confirmed   present only when the owner never answered within
//	            STREAM_SWITCH_CONFIRM_TIMEOUT (:566-570) -- a wait for a
//	            worker that no longer exists. The Django wrapper maps its
//	            absence to 502 and its presence to 504, so never setting it
//	            means a failed switch answers 502, which is the shape a
//	            direct (owner) update already has there.
//	event_published the pub/sub branch, deleted with the followers.
//	worker_id   proxy_server.worker_id. There is no worker to name, and
//	            change_stream reads its OWN process's worker id into the
//	            response it builds (views.py:1000, :1010) rather than this
//	            one, so nothing consumes it.
type advancePayload struct {
	Status          string         `json:"status"`
	Success         *bool          `json:"success,omitempty"`
	Message         string         `json:"message,omitempty"`
	DirectUpdate    *bool          `json:"direct_update,omitempty"`
	MetadataUpdated *bool          `json:"metadata_updated,omitempty"`
	Diagnostics     map[string]any `json:"diagnostics,omitempty"`
}

// AdvanceHandler serves POST /proxy/relay/channels/{channelID}/advance.
func AdvanceHandler(deps ControlDeps) http.HandlerFunc {
	log := controlLog(deps)
	return func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("channelID")

		var req advanceRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			// DRF's own answer to a body that does not parse, and
			// relay_client maps a 4xx to RelayRefused, which change_stream
			// answers 502 for -- "the relay refused the request", which is
			// what happened.
			log.Error("the advance body did not decode", "channel", id, "error", redact.Error(err))
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}
		if req.URL == "" || req.StreamProfile == nil {
			// payload.is_valid(raise_exception=True) at relay_views.py:234
			// for a missing required field. stream_profile joins url as
			// required in 2c-8: see advanceRequest.
			log.Error("the advance body is missing a required field", "channel", id,
				"url_present", req.URL != "", "stream_profile_present", req.StreamProfile != nil)
			http.Error(w, "invalid request body", http.StatusBadRequest)
			return
		}

		ch := deps.Channels.Get(id)
		if ch == nil {
			// :477-482's not-found branch. Its diagnostics carry
			// in_local_managers, in_local_buffers and a Redis key list; the
			// first two are false here for the same reason they are false
			// there, and the third names a scan there is no Redis for.
			writeJSON(w, log, advancePayload{
				Status:  "error",
				Message: "Channel not found",
				Diagnostics: map[string]any{
					"in_local_managers": false,
					"in_local_buffers":  false,
				},
			})
			return
		}

		candidate := advanceSource(&req)
		build, ok := builderFor(ch)
		if !ok {
			log.Error("the channel has no resolver, so an operator switch cannot be built", "channel", id)
			failed, direct := false, true
			writeJSON(w, log, advancePayload{
				Status:       "success",
				Success:      &failed,
				DirectUpdate: &direct,
				Message:      "Stream switch failed",
			})
			return
		}
		source, err := build.source(candidate)
		if err != nil {
			// An unbuildable profile -- a null argv, Amendment A4.3 -- is
			// terminal for this switch and never a retry, because no retry
			// against the same profile can change what Django could not
			// split. Reported as a failed switch, which change_stream turns
			// into its 502.
			log.Error("the advance named a profile this relay cannot spawn", "channel", id, "error", redact.Error(err))
			failed, direct := false, true
			writeJSON(w, log, advancePayload{
				Status:       "success",
				Success:      &failed,
				DirectUpdate: &direct,
				Message:      "Stream switch failed",
			})
			return
		}

		applied := ch.Advance(channel.Resolved{Source: source, Info: infoFrom(candidate)}, req.ResetTried)
		// change_stream_url reports SUCCESS for an unchanged URL even though
		// update_url returned False: ":487-490 -- update_url() returns False
		// for same URL; still success so metadata refreshes". The relay has
		// no metadata to refresh, and the answer is the one that matters.
		success := true
		direct, updated := true, true
		if !applied {
			log.Info("the operator switch changed nothing", "channel", id)
		}
		writeJSON(w, log, advancePayload{
			Status:          "success",
			Success:         &success,
			DirectUpdate:    &direct,
			MetadataUpdated: &updated,
		})
	}
}

// advanceSource rebuilds the control.Source shape the tune path already knows
// how to turn into a running source, out of the advance body's own fields.
//
// One shape, not two: sourceBuilder.source and infoFrom are the same two
// functions the tune and the failover use, so an operator's switch cannot
// diverge from an automatic one in what it spawns.
func advanceSource(req *advanceRequest) *control.Source {
	source := &control.Source{
		URL:            req.URL,
		UserAgent:      req.UserAgent,
		Transcode:      req.Transcode,
		StreamProfile:  *req.StreamProfile,
		ChannelName:    req.ChannelName,
		StreamName:     req.StreamName,
		M3UProfileName: req.M3UProfileName,
		// SlotReserved is FALSE and that is deliberate: Django moved the
		// provider slot when it resolved this candidate (Phase 1 PR 6), and
		// the relay releases only what it reserved. Marking it reserved here
		// would make the channel's own release double-release.
		FFmpegStreamProfile: req.FFmpegProfile,
	}
	if req.StreamID != nil {
		source.StreamID = *req.StreamID
	}
	if req.M3UProfileID != nil {
		source.M3UProfileID = *req.M3UProfileID
	}
	return source
}

// builderFor is the source builder the channel's own tune created, reached
// through its resolver.
//
// The tune's builder rather than one assembled from the advance body,
// because it holds three tune-time facts an advance does not carry: which of
// the three Stream Profile architectures this channel plays (the answer's
// stream_profile is the CHANNEL's, apps/proxy/next_source.py:609-622), the
// defaulted user agent (input/manager.py:73), and the upstream read size
// (CHUNK_SIZE). Python keeps all three on the StreamManager across a switch
// for the same reason.
func builderFor(ch *channel.Channel) (sourceBuilder, bool) {
	r, ok := ch.Resolver().(*resolver)
	if !ok {
		return sourceBuilder{}, false
	}
	return r.build, true
}
```

### Appendix I — `relay/httpapi/channels.go`

Ruling R3: `RequireInternal` buffers the body, verifies the bound signature against it, and hands the handler a reader over the same bytes. Bounded at `MaxInternalBody` with a 413 beyond it.

**`relay/httpapi/channels.go`**

```diff
--- a/httpapi/channels.go
+++ b/httpapi/channels.go
@@ -1,8 +1,10 @@
 package httpapi
 
 import (
+	"bytes"
 	"encoding/json"
 	"fmt"
+	"io"
 	"log/slog"
 	"net/http"
 	"strconv"
@@ -293,6 +295,23 @@
 			http.Error(w, "forbidden", http.StatusForbidden)
 			return
 		}
+		// THE BODY IS PART OF WHAT THE TOKEN SIGNS, and reading it here is
+		// what 2c-8 adds: internal_auth.py's message is
+		// [context, METHOD, FULL_PATH, timestamp, sha256(BODY)], and every
+		// route this gate protected until now was a GET or a bodyless
+		// DELETE, so verifying against an empty body was right by accident.
+		// POST .../advance carries one, and a gate that verified nil against
+		// a token signed over the real body 403s every call -- measured, on
+		// the first run of TestAnAdvanceSwitchesTheChannelAndKeepsTheClientFed.
+		//
+		// Bounded and buffered: the handler is given a reader over the same
+		// bytes, because the body cannot be read twice and the signature
+		// must be checked before the handler sees any of it.
+		body, tooLarge := readInternalBody(r)
+		if tooLarge {
+			http.Error(w, "request body too large", http.StatusRequestEntityTooLarge)
+			return
+		}
 		// The bound token signs r.URL.RequestURI(), which is Django's
 		// get_full_path(): the escaped path plus the query string. This route
 		// is reached WITH a query string (?clients=all) and without, and the
@@ -300,11 +319,41 @@
 		// records, and the reason it is not cosmetic.
 		if !control.VerifyInternalRequest(
 			secret, r.Header.Get(control.HeaderInternalRequest),
-			r.Method, r.URL.RequestURI(), nil, now(),
+			r.Method, r.URL.RequestURI(), body, now(),
 		) {
 			http.Error(w, "forbidden", http.StatusForbidden)
 			return
 		}
+		if len(body) > 0 {
+			r.Body = io.NopCloser(bytes.NewReader(body))
+		}
 		next(w, r)
 	}
 }
+
+// MaxInternalBody bounds what RequireInternal will buffer to verify a
+// signature. The largest body any of these five routes carries is the
+// advance's resolved source -- a URL, a user agent, three names and a
+// built argv -- so a mebibyte is three orders of magnitude of headroom and
+// small enough that an unauthenticated caller cannot make this process
+// buffer a large one before the signature is checked.
+const MaxInternalBody = 1 << 20
+
+// readInternalBody buffers the request body, reporting whether it exceeded
+// the bound. A nil body reads as empty, which is the shape every GET and
+// DELETE here has and the shape sha256(b"") covers.
+func readInternalBody(r *http.Request) (body []byte, tooLarge bool) {
+	if r.Body == nil {
+		return nil, false
+	}
+	raw, err := io.ReadAll(io.LimitReader(r.Body, MaxInternalBody+1))
+	if err != nil {
+		// A truncated body cannot match the signature, so it fails the check
+		// below rather than being reported separately.
+		return raw, false
+	}
+	if len(raw) > MaxInternalBody {
+		return nil, true
+	}
+	return raw, false
+}
```

### Appendix J — `relay/httpapi/server.go`

The routing table. **One diff, referenced by Tasks 3, 7 and 8**: the four control routes, the two XC roots and `/readyz`'s handler all land here. One gate per route rather than a wrapper around the mux -- the health endpoints must stay ungated.

**`relay/httpapi/server.go`**

```diff
--- a/httpapi/server.go
+++ b/httpapi/server.go
@@ -21,6 +21,11 @@
 	// set.
 	Stream StreamDeps
 
+	// Health is what /readyz needs. Read in every shape: the operational
+	// endpoints are not behind the dev flag, because a probe must work in
+	// the deployment the drain runs in.
+	Health HealthDeps
+
 	// Control is what the internal control routes need. Only read when
 	// DevRoutes is set.
 	Control ControlDeps
@@ -51,17 +56,40 @@
 	// something to report -- and that is also why this PR adds no Docker
 	// HEALTHCHECK: a probe wired to a static 200 reports healthy through
 	// every failure it exists to catch.
+	//
+	// /healthz stays a static 200 -- LIVENESS: the process is up. /readyz
+	// became real in 2c-8 and reports the drain plus the channel and client
+	// counts (health.go).
 	s.mux.HandleFunc("GET /healthz", ok)
-	s.mux.HandleFunc("GET /readyz", ok)
+	s.mux.Handle("GET /readyz", ReadyHandler(cfg.Health))
 
 	if cfg.DevRoutes {
 		// The dev-only route flag spec line 1795 names.
 		s.mux.Handle("GET /proxy/ts/stream/{channelID}", StreamHandler(cfg.Stream))
+		// The XC live roots, spec D1's other half of this relay's scope.
+		// Both shapes dispatcharr/urls.py:69-78 registers, and the bare
+		// three-segment one does NOT shadow /proxy/relay/channels: net/http's
+		// mux prefers the more specific pattern, and three literal segments
+		// beat three wildcards.
+		s.mux.Handle("GET /live/{username}/{password}/{channelID}", XCHandler(cfg.Stream))
+		s.mux.Handle("GET /{username}/{password}/{channelID}", XCHandler(cfg.Stream))
 		// Gated with the rest: nginx routes nothing to this process until
-		// stage 2d, and Django still calls the Python relay's copy of this
-		// route. 2c-8 brings the other four.
-		s.mux.Handle("GET /proxy/relay/channels",
-			RequireInternal(cfg.Control.Secret, cfg.Control.Now, ChannelsHandler(cfg.Control)))
+		// stage 2d, and Django still calls the Python relay's copy of these
+		// routes. All five of § The contract's Django-to-relay table are here
+		// as of 2c-8; the collection GET landed in 2c-3.
+		//
+		// ONE GATE PER ROUTE rather than a wrapper around the mux: the two
+		// health endpoints must stay ungated (a probe holds no SECRET_KEY),
+		// and a middleware with an exception list is one edit away from
+		// exempting a route it should not.
+		internal := func(h http.HandlerFunc) http.Handler {
+			return RequireInternal(cfg.Control.Secret, cfg.Control.Now, h)
+		}
+		s.mux.Handle("GET /proxy/relay/channels", internal(ChannelsHandler(cfg.Control)))
+		s.mux.Handle("GET /proxy/relay/channels/{channelID}", internal(ChannelHandler(cfg.Control)))
+		s.mux.Handle("DELETE /proxy/relay/channels/{channelID}", internal(ChannelHandler(cfg.Control)))
+		s.mux.Handle("DELETE /proxy/relay/channels/{channelID}/clients/{clientID}", internal(ClientHandler(cfg.Control)))
+		s.mux.Handle("POST /proxy/relay/channels/{channelID}/advance", internal(AdvanceHandler(cfg.Control)))
 	}
 
 	return s
```

### Appendix K — `relay/httpapi/clientevents.go`

`client_connect` for both client types (Amendment A6.5) and `client_disconnect` for the TS one only. The asymmetry is Python's: `emit_event` appears once in `output/fmp4/generator.py`, at `:114`.

**`relay/httpapi/clientevents.go`**

```go
package httpapi

import (
	"math"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/channel"
)

// userAgentEventLimit is the cut both generators apply before the user agent
// reaches an event: `self.client_user_agent[:100]`, at
// output/ts/generator.py:138 (client_connect) and :658 (client_disconnect),
// and output/fmp4/generator.py:120 (client_connect, the only event that file
// raises).
const userAgentEventLimit = 100

// clientEventDetails is the four details both client transitions carry
// (output/ts/generator.py:132-144, output/fmp4/generator.py:114-127):
// client_ip, client_id, a user agent cut at 100 characters, and the user id
// with an empty one sent as null.
//
// TWO STATED DIVERGENCES, both in the value rather than the shape:
//
//   - user_agent is the CLIENT REGISTRY's value, which identify() already
//     defaults to "unknown" (client_manager.py:236). Python's generators read
//     the raw request header instead, so a client that sent none puts null on
//     this event there and "unknown" here -- while both registries carry
//     "unknown", which is the value every status surface renders.
//   - user_id is `self.user_id or None` there over a value the view resolved;
//     here it is the registry's, which identify() defaults to the string "0"
//     (client_manager.py:241). "0" is falsy in neither language's sense the
//     same way, so it is mapped to null explicitly rather than left to a
//     truthiness rule that does not exist in Go.
func clientEventDetails(client *channel.Client) map[string]any {
	details := map[string]any{
		"client_ip": client.IPAddress,
		"client_id": client.ID,
	}
	agent := client.UserAgent
	if len(agent) > userAgentEventLimit {
		agent = agent[:userAgentEventLimit]
	}
	if agent != "" {
		details["user_agent"] = agent
	} else {
		details["user_agent"] = nil
	}
	if client.UserID != "" && client.UserID != "0" {
		details["user_id"] = client.UserID
	} else {
		details["user_id"] = nil
	}
	return details
}

// emitClientConnect is client_connect, raised for BOTH client types
// (Amendment A6.5): output/ts/generator.py:132-143 for a TS client and
// output/fmp4/generator.py:114-126 for an fMP4 one, each at the point its
// setup has succeeded and before its first byte of media.
func emitClientConnect(ch *channel.Channel, client *channel.Client) {
	ch.Emit("client_connect", clientEventDetails(client))
}

// emitClientDisconnect is client_disconnect, raised for a TS client ONLY.
//
// THE ASYMMETRY IS PYTHON'S AND IS REPRODUCED RATHER THAN EVENED OUT:
// output/ts/generator.py:652-666 raises it in the generator's cleanup, and
// output/fmp4/generator.py raises no disconnect at all -- `emit_event`
// appears once in that file, at :114. An fMP4 viewer's departure is therefore
// invisible to Connect and to the SystemEvent log in both relays.
//
// duration is round(elapsed, 2) over the client's own connection
// (generator.py:610, :659) and bytes_sent is the counter clientstats.go
// keeps.
func emitClientDisconnect(ch *channel.Channel, client *channel.Client, at time.Time) {
	details := clientEventDetails(client)
	details["duration"] = math.Round(at.Sub(client.ConnectedAt).Seconds()*100) / 100
	details["bytes_sent"] = client.Stats(at).BytesSent
	ch.Emit("client_disconnect", details)
}
```

### Appendix L — `relay/channel/events.go`

`client_id` is the OTHER key `emit_event` lifts (`control_plane.py:331-333`'s two-name loop), and it is left in `Details` as well. Plus `Emit`, the exported name `httpapi` raises the two client transitions through -- the same function, not a second path.

**`relay/channel/events.go`**

```diff
--- a/channel/events.go
+++ b/channel/events.go
@@ -39,5 +39,21 @@
 	if id, ok := details["stream_id"].(int); ok {
 		event.StreamID = &id
 	}
+	// client_id is the OTHER key emit_event lifts (control_plane.py:331-333's
+	// own two-name loop), and it is left in Details as well. 2c-8's two
+	// client transitions are the first events that carry one.
+	if id, ok := details["client_id"].(string); ok {
+		event.ClientID = id
+	}
 	c.events.Emit(event)
 }
+
+// Emit raises one event for this channel from outside this package.
+//
+// The two client transitions -- client_connect and client_disconnect -- are
+// raised by the handler that serves the client, not by the channel, because
+// the channel never learns that a particular client started or finished
+// reading it. Everything else in this package calls the unexported emit;
+// this is the same function under an exported name rather than a second
+// path, so the stream_id/client_id lifting above applies to all of them.
+func (c *Channel) Emit(typ string, details map[string]any) { c.emit(typ, details) }
```

### Appendix M — `relay/internal/relaytest/controlplane.go`

Three additions in one diff: `Nameless` (Task 2, row 18), `ClientID` on `RecordedEvent` (Task 4), and the authorize route with `AuthorizeDecision`, `SetAuthorize`, `AuthorizeRequests` and `NonJSONBody` (Task 6). The default decision is deliberately minimal -- see its doc comment.

**`relay/internal/relaytest/controlplane.go`**

```diff
--- a/internal/relaytest/controlplane.go
+++ b/internal/relaytest/controlplane.go
@@ -78,6 +78,19 @@
 	// of the error table.
 	Body string
 
+	// Nameless sends the three name fields as empty strings, which is what
+	// an answer looks like when Django resolved a Source whose rows carry no
+	// name -- the state parity-matrix row 18 is about. Every producer in
+	// next_source.py reads them off a loaded row, so the real shape is
+	// "always present, possibly empty"; the Go relay's payload omits an
+	// empty one, where Python would fall back to an ORM lookup it has no
+	// way to make.
+	Nameless bool
+
+	// Authorize is what POST /_dispatcharr/authorize-internal answers with.
+	// Nil means the minimal default below.
+	Authorize *AuthorizeDecision
+
 	// Delay holds every answer for this long before writing it. Zero is the
 	// ordinary immediate answer. 2c-3's R11 test needs a next-source call
 	// still in flight when a client disconnects, and there is no other way
@@ -169,16 +182,84 @@
 type ControlPlane struct {
 	server *httptest.Server
 
-	mu       sync.Mutex
-	requests []RecordedRequest
-	events   []RecordedEvent
-	settings map[string]any
-	status   int
-	delay    time.Duration
-	profiles map[string]OutputProfileConfig
-	hasProfs bool
+	mu        sync.Mutex
+	requests  []RecordedRequest
+	events    []RecordedEvent
+	settings  map[string]any
+	status    int
+	delay     time.Duration
+	profiles  map[string]OutputProfileConfig
+	hasProfs  bool
+	authorize *AuthorizeDecision
 }
 
+// AuthorizeDecision is what the fake answers POST
+// /_dispatcharr/authorize-internal with: the seven X-Relay-* headers on a
+// 200, or a status and a body on a denial.
+//
+// THE DEFAULT IS DELIBERATELY MINIMAL -- the channel out of the URI, and
+// nothing else. Django resolves more than that on every live tune (it always
+// mints a client id), and filling those in here by default would silently
+// change what every untrusted rig from 2c-2 onward observes. A test that is
+// ABOUT the authorize hop sets the fields it is about, which is what keeps
+// the default from pinning anything.
+type AuthorizeDecision struct {
+	Channel      string
+	Output       string
+	Client       string
+	User         string
+	Name         string
+	OutputFormat string
+	ClientIP     string
+
+	// Status, when non-zero, is answered instead of 200. Body is the JSON
+	// denial that goes with it.
+	Status int
+	Body   string
+
+	// NonJSONBody answers the denial with a text/html body instead, which
+	// is what a proxy's own error document or a Django 500 page looks like.
+	// The relay must NOT forward such a body to a viewer, and a test that
+	// only ever configured a JSON one could not tell the two branches apart.
+	NonJSONBody bool
+}
+
+// SetAuthorize replaces what every LATER authorize call is answered with.
+func (c *ControlPlane) SetAuthorize(decision *AuthorizeDecision) {
+	c.mu.Lock()
+	defer c.mu.Unlock()
+	c.authorize = decision
+}
+
+// AuthorizeRequest is one decoded POST to the authorize route.
+type AuthorizeRequest struct {
+	URI      string `json:"uri"`
+	ClientIP string `json:"client_ip"`
+	Internal bool   `json:"internal"`
+	Headers  struct {
+		Authorization *string `json:"authorization"`
+		Cookie        *string `json:"cookie"`
+		APIKey        *string `json:"x-api-key"`
+	} `json:"headers"`
+}
+
+// AuthorizeRequests is every authorize call the fake has been sent, decoded,
+// in order.
+func (c *ControlPlane) AuthorizeRequests() []AuthorizeRequest {
+	var out []AuthorizeRequest
+	for _, r := range c.RequestsTo(AuthorizePath) {
+		var decoded AuthorizeRequest
+		if err := json.Unmarshal(r.Body, &decoded); err == nil {
+			out = append(out, decoded)
+		}
+	}
+	return out
+}
+
+// AuthorizePath is the route the Go relay's dev fallback calls, spelled here
+// so a test naming it cannot drift from control.AuthorizePath.
+const AuthorizePath = "/_dispatcharr/authorize-internal"
+
 // SetSettings replaces the proxy_settings every LATER answer carries. It is
 // how a test changes a setting between two tunes, the way an operator's
 // save does, to show that a channel already running does not pick it up
@@ -238,8 +319,12 @@
 	Type        string
 	ChannelID   string
 	ChannelName string
-	StreamID    *int
-	Details     map[string]any
+	// ClientID is the second key emit_event lifts out of details to the top
+	// level (control_plane.py:331-333's two-name loop). Added in 2c-8, with
+	// the first events that carry one.
+	ClientID string
+	StreamID *int
+	Details  map[string]any
 }
 
 // NewControlPlane starts a fake control plane. Register Close with t.Cleanup.
@@ -301,6 +386,15 @@
 			return
 		}
 
+		// The authorize route is answered AFTER the three forced-failure arms
+		// above, deliberately: a test that forces a 503 on the control plane
+		// is testing an outage, and an outage takes the authorize call down
+		// with everything else.
+		if strings.HasSuffix(r.URL.Path, AuthorizePath) {
+			c.writeAuthorize(w, cfg)
+			return
+		}
+
 		w.Header().Set("Content-Type", "application/json")
 		switch {
 		case strings.HasSuffix(r.URL.Path, "/release"):
@@ -326,6 +420,7 @@
 			Type        string         `json:"type"`
 			ChannelID   string         `json:"channel_id"`
 			ChannelName string         `json:"channel_name"`
+			ClientID    string         `json:"client_id"`
 			StreamID    *int           `json:"stream_id"`
 			Details     map[string]any `json:"details"`
 		} `json:"events"`
@@ -336,7 +431,10 @@
 	c.mu.Lock()
 	defer c.mu.Unlock()
 	for _, e := range batch.Events {
-		c.events = append(c.events, RecordedEvent{Type: e.Type, ChannelID: e.ChannelID, ChannelName: e.ChannelName, StreamID: e.StreamID, Details: e.Details})
+		c.events = append(c.events, RecordedEvent{
+			Type: e.Type, ChannelID: e.ChannelID, ChannelName: e.ChannelName,
+			ClientID: e.ClientID, StreamID: e.StreamID, Details: e.Details,
+		})
 	}
 }
 
@@ -415,6 +513,12 @@
 			ua = userAgent
 		}
 		candidates = append(candidates, candidate{alt.StreamID, alt.URL, ua, alt.Argv})
+	}
+	names := func(value string) string {
+		if cfg.Nameless {
+			return ""
+		}
+		return value
 	}
 	render := func(cand candidate) map[string]any {
 		return map[string]any{
@@ -424,9 +528,9 @@
 			"transcode":             kind == "transcode",
 			"m3u_profile_id":        1,
 			"slot_reserved":         slotReserved,
-			"channel_name":          "Test Channel",
-			"stream_name":           "Test Stream",
-			"m3u_profile_name":      "Test Profile",
+			"channel_name":          names("Test Channel"),
+			"stream_name":           names("Test Stream"),
+			"m3u_profile_name":      names("Test Profile"),
 			"stream_profile":        profile(1, cfg.Command, cand.argv),
 			"ffmpeg_stream_profile": ffmpegProfile,
 		}
@@ -533,3 +637,64 @@
 // transport failure on its next call, which is the other shape of
 // control.Unavailable beside SetStatus's 5xx.
 func (c *ControlPlane) Close() { c.server.Close() }
+
+// writeAuthorize answers the dev fallback.
+func (c *ControlPlane) writeAuthorize(w http.ResponseWriter, cfg ControlPlaneConfig) {
+	c.mu.Lock()
+	decision := c.authorize
+	c.mu.Unlock()
+	if decision == nil {
+		decision = cfg.Authorize
+	}
+	if decision == nil {
+		// The minimal default: the channel the URI named, so a relay that
+		// believed an unverified X-Relay-Channel is still caught, and
+		// nothing else.
+		decision = &AuthorizeDecision{Channel: channelFromURI(c.lastAuthorizedURI())}
+	}
+	if decision.Status != 0 && decision.Status != http.StatusOK {
+		if decision.NonJSONBody {
+			w.Header().Set("Content-Type", "text/html; charset=utf-8")
+			w.WriteHeader(decision.Status)
+			_, _ = w.Write([]byte("<html>relaytest: a non-JSON denial</html>"))
+			return
+		}
+		w.Header().Set("Content-Type", "application/json")
+		w.WriteHeader(decision.Status)
+		body := decision.Body
+		if body == "" {
+			body = `{"error":"relaytest: configured denial"}`
+		}
+		_, _ = w.Write([]byte(body))
+		return
+	}
+	w.Header().Set("X-Relay-Channel", decision.Channel)
+	w.Header().Set("X-Relay-Output", decision.Output)
+	w.Header().Set("X-Relay-Client", decision.Client)
+	w.Header().Set("X-Relay-User", decision.User)
+	w.Header().Set("X-Relay-Name", decision.Name)
+	w.Header().Set("X-Relay-Output-Format", decision.OutputFormat)
+	w.Header().Set("X-Relay-Client-IP", decision.ClientIP)
+	w.WriteHeader(http.StatusOK)
+}
+
+// lastAuthorizedURI is the uri field of the most recent authorize call.
+func (c *ControlPlane) lastAuthorizedURI() string {
+	seen := c.AuthorizeRequests()
+	if len(seen) == 0 {
+		return ""
+	}
+	return seen[len(seen)-1].URI
+}
+
+// channelFromURI is the last path segment of a tune URI, which for
+// /proxy/ts/stream/<uuid> is the channel -- the same thing Django's resolver
+// pulls out of the URL pattern.
+func channelFromURI(uri string) string {
+	path := strings.SplitN(uri, "?", 2)[0]
+	idx := strings.LastIndex(path, "/")
+	if idx < 0 {
+		return path
+	}
+	return path[idx+1:]
+}
```

### Appendix N — `relay/httpapi/stream.go`

**One diff, referenced by Tasks 4, 6 and 8**: the drain gate at the top, the authorize call before `identify`, `identify`'s fourth parameter, `stopContext`, the two client emits, and the per-chunk `client.Sent`. `StreamDeps` gains `Lifecycle`.

**`relay/httpapi/stream.go`**

```diff
--- a/httpapi/stream.go
+++ b/httpapi/stream.go
@@ -42,6 +42,11 @@
 	// follows redirects, as requests does there.
 	Probe *http.Client
 
+	// Lifecycle is the drain flag. A tune that arrives after SIGTERM is
+	// refused rather than started: D6's "stops accepting tunes". Nil is
+	// never draining, which is every test that is not about the drain.
+	Lifecycle *Lifecycle
+
 	// Remux is the process an fMP4 tune spawns. Its zero value is the
 	// production remux (output.RemuxCommand and output.RemuxArgv), which is
 	// what main.go leaves it as; a test substitutes a stand-in. It is on
@@ -186,7 +191,29 @@
 	}
 
 	return func(w http.ResponseWriter, r *http.Request) {
-		id, client, err := identify(r, deps.Secret, now)
+		if deps.Lifecycle.Draining() {
+			// FIRST, before the channel is even identified: a tune started
+			// now would be torn down seconds later by the drain that is
+			// already running, after reserving a provider slot Django would
+			// then have to see released. 503 rather than 500 because the
+			// condition is temporary and naming it that way is what lets a
+			// client retry into the replacement process.
+			w.Header().Set("Retry-After", "1")
+			http.Error(w, "the relay is shutting down", http.StatusServiceUnavailable)
+			return
+		}
+		// D5, exception 2: with no nginx there is no auth_request, and a Go
+		// process cannot import authorize_stream, so the decision is asked
+		// for over HTTP. On every ordinary nginx-fronted tune this returns
+		// (nil, nil) without a round trip, matching the frequency of the
+		// Python relay's own inline fallback -- which is to say never, in
+		// production.
+		decision, err := authorizeTune(r, deps, log)
+		if err != nil {
+			writeAuthorizeFailure(w, log, err)
+			return
+		}
+		id, client, err := identify(r, deps.Secret, now, decision)
 		if err != nil {
 			writeTuneFailure(w, log, id, err)
 			return
@@ -221,6 +248,18 @@
 		}
 		defer release()
 
+		// From here down the request's context also ends when an admin
+		// stops THIS client: DELETE /proxy/relay/channels/<id>/clients/<cid>
+		// closes the signal Channel.StopClient owns, which is the in-memory
+		// form of the stop key ChannelService.stop_client SETEXes and the
+		// generator's loop polls (output/ts/generator.py:307-318). Applied
+		// to the request rather than to one call so both output formats
+		// inherit it -- one mechanism, and neither loop can be the one that
+		// forgot.
+		stopCtx, stopCancel := stopContext(r.Context(), client)
+		defer stopCancel()
+		r = r.WithContext(stopCtx)
+
 		// views.py:765-776, BEFORE the format branch and in that order: the
 		// Output Profile transcode is started (or joined) first, and the
 		// buffer everything below reads is get_buffer(channel, profile) --
@@ -250,7 +289,15 @@
 			return
 		}
 
+		// client_connect, at _setup_streaming's own success point
+		// (output/ts/generator.py:129-143): after the channel is up and the
+		// response has begun, before the streaming loop.
+		emitClientConnect(ch, client)
 		serveClient(r.Context(), w, rc, ch, source, client, log)
+		// client_disconnect, from the generator's cleanup (:651-667). TS
+		// only -- the fMP4 generator raises none, and that asymmetry is
+		// reproduced (clientevents.go).
+		emitClientDisconnect(ch, client, now())
 	}
 }
 
@@ -291,10 +338,19 @@
 //
 // One closure rather than five `if trusted` blocks: five is five chances to
 // omit one, and the one omitted is the one that matters.
-func identify(r *http.Request, secret string, now func() time.Time) (string, *channel.Client, error) {
+func identify(r *http.Request, secret string, now func() time.Time, decision *control.Decision) (string, *channel.Client, error) {
 	trusted := control.IsRelayTrusted(secret, r.Header.Get(control.HeaderAuthorized))
 
 	header := func(name string) string {
+		// A decision from the dev fallback answers in the hop's place: the
+		// same seven values, resolved by the same authorize_stream() call,
+		// arriving as a response rather than as request headers. Checked
+		// FIRST, so a request that carried no valid marker can never fall
+		// back to reading its own headers -- the two sources are exclusive
+		// by construction and never merged.
+		if decision != nil {
+			return decisionHeader(decision, name)
+		}
 		if !trusted {
 			return ""
 		}
@@ -371,6 +427,29 @@
 		OutputProfileID: outputProfileID,
 		ConnectedAt:     now(),
 	}, nil
+}
+
+// stopContext ends when the request ends OR when an admin stops this client.
+//
+// A goroutine rather than context.AfterFunc because the trigger is a channel
+// close, not a parent context; it returns as soon as either side fires, and
+// the caller's deferred cancel guarantees the second one always does.
+func stopContext(parent context.Context, client *channel.Client) (context.Context, context.CancelFunc) {
+	stop := client.Stopped()
+	if stop == nil {
+		// A client that never reached the registry cannot be stopped by id,
+		// so there is nothing to watch and no goroutine to start.
+		return parent, func() {}
+	}
+	ctx, cancel := context.WithCancel(parent)
+	go func() {
+		select {
+		case <-stop:
+			cancel()
+		case <-ctx.Done():
+		}
+	}()
+	return ctx, cancel
 }
 
 // ErrOutputProfileMalformed is an X-Relay-Output that is not a positive
@@ -803,6 +882,15 @@
 	var keepaliveStart time.Time
 	empties := 0
 	for {
+		if ctx.Err() != nil {
+			// The admin stop and the client hang-up both land here. Checked
+			// at the top of every pass rather than only inside the wait,
+			// because a ring that always has data never reaches the wait --
+			// which is exactly the busy channel an admin is most likely to
+			// be stopping a client on. Python polls its stop key here
+			// (output/ts/generator.py:307-318).
+			return
+		}
 		chunks, next, skipped := ring.Read(cursor)
 		if skipped > 0 {
 			// The jump find_oldest_available_chunk performs
@@ -819,10 +907,17 @@
 			if !writeChunks(w, rc, chunks) {
 				return
 			}
+			at := time.Now()
 			for _, c := range chunks {
 				sent += len(c)
+				// ONE CALL PER CHUNK, not one per Read: current_rate_KBps is
+				// the rate over the gap between consecutive chunks
+				// (output/ts/generator.py:477-499 increments inside its own
+				// `for chunk in chunks` loop), so batching them here would
+				// report a rate over a window Python never measures.
+				client.Sent(len(c), at)
 			}
-			lastYield = time.Now()
+			lastYield = at
 			keepaliveStart = time.Time{}
 			empties = 0
 			continue
@@ -843,7 +938,10 @@
 				return
 			}
 			sent += buffer.TSPacketSize
+			// A keepalive counts toward bytes_sent (:392) and refreshes
+			// last_active (:395-397), both of which Sent does.
 			lastYield = time.Now()
+			client.Sent(buffer.TSPacketSize, lastYield)
 			wait = tuning.KeepaliveInterval
 		} else if time.Since(lastYield) > tuning.ClientTimeout && !ch.Healthy() {
 			// _is_timeout (:583-604) minus its url_switching exemption
@@ -872,6 +970,7 @@
 			if final, _, _ := ring.Read(cursor); len(final) > 0 {
 				writeChunks(w, rc, final)
 				sent += len(final[0])
+				client.Sent(len(final[0]), time.Now())
 			}
 			if sent == 0 {
 				if message := errorPacketMessage(ch); message != "" {
```

### Appendix O — `relay/httpapi/fmp4.go`

`client_connect` at `generator.py:113-127`'s own point -- after `_wait_for_fmp4_ready` and `_setup_streaming`, before the init segment is yielded -- plus `client.Touch` per fragment batch and the context check at the top of the loop.

**`relay/httpapi/fmp4.go`**

```diff
--- a/httpapi/fmp4.go
+++ b/httpapi/fmp4.go
@@ -96,6 +96,12 @@
 		log.Error("the fMP4 init segment disappeared", "channel", ch.ID(), "client", client.ID)
 		return
 	}
+	// client_connect, at generator.py:113-127's own point: after
+	// _wait_for_fmp4_ready and _setup_streaming have both succeeded and
+	// BEFORE the init segment is yielded (:129-134). Amendment A6.5 owes
+	// this to both client types and this is the fMP4 half.
+	emitClientConnect(ch, client)
+
 	if !writeChunks(w, rc, [][]byte{init}) {
 		return
 	}
@@ -175,6 +181,12 @@
 
 	lastYield := time.Now()
 	for {
+		if ctx.Err() != nil {
+			// serveClient's reason: the admin stop and the hang-up both
+			// land here, and a buffer that always has a fragment never
+			// reaches the wait below.
+			return
+		}
 		frags, next, skipped := fragments.Read(cursor)
 		if skipped > 0 {
 			log.Warn("fMP4 client fell behind the fragment buffer",
@@ -187,6 +199,12 @@
 				return
 			}
 			lastYield = time.Now()
+			// Touch, not Sent: the fMP4 generator writes last_active and no
+			// byte counter (output/fmp4/generator.py:288-295), so an fMP4
+			// client's detail row carries no bytes_sent, avg_rate_KBps or
+			// current_rate_KBps -- reproduced as an absence with a
+			// mechanism rather than a format check in the renderer.
+			client.Touch(lastYield)
 			continue
 		}
 
```

### Appendix P — `relay/httpapi/detail_golden_test.go`

The golden, compared as PARSED JSON for Amendment A3.7's reason. Read the note on break-checks 2 and 3 in § Break-check before trusting this file on its own: it pins the ENCODER, and Appendix Q pins the builder.

**`relay/httpapi/detail_golden_test.go`**

```go
package httpapi

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

// detailGoldenPath holds a payload rendered by DJANGO'S OWN SERIALIZER --
// apps/proxy/relay_serializers.py's RelayChannelDetailSerializer -- from the
// fixture apps/proxy/tests/test_relay_detail_payload_golden.py builds.
//
// The sibling of goldenPath, and for the same reason: the oracle is produced
// by the OTHER implementation, which is the only thing that makes it able to
// fail (hollow shape 1).
//
// Regenerate it with the command in this PR's Task 2, never by running the Go.
const detailGoldenPath = "testdata/channel_detail.json"

// detailGoldenPayload is the Go value the golden file must describe: one
// channel with every conditional field set, a TS client carrying the three
// byte counters and an fMP4 client carrying none of them.
func detailGoldenPayload() detailPayload {
	state := "active"
	streamID := 41
	m3uProfileID := 3
	total := uint64(9_999_888)
	kbps := 2_665.3034666666666
	speed := 1.02
	profileID := 7
	bytesSent := int64(9_999_888)
	avgRate := 341.2
	currentRate := 348.9

	return detailPayload{
		ChannelID:      "11111111-1111-4111-8111-111111111111",
		State:          &state,
		URL:            "http://provider.invalid/live/sub/pw/41.ts",
		StreamProfile:  "1",
		StartedAt:      1_789_000_000.5,
		Owner:          OwnerUnknown,
		BufferIndex:    120,
		ChannelName:    "BBC One HD",
		StreamID:       &streamID,
		StreamName:     "BBC One HD (UK)",
		M3UProfileID:   &m3uProfileID,
		M3UProfileName: "Premium",
		StateChangedAt: 1_789_000_005.0,
		StateDuration:  25.5,
		Uptime:         30.0,
		TotalBytes:     &total,
		TotalData:      "9.54 MB",
		AvgBitrateKbps: &kbps,
		AvgBitrate:     "2.67 Mbps",
		ClientCount:    2,
		BufferStats: bufferStatsPayload{
			Chunks: 120,
			Diagnostics: map[string]any{
				"first_chunk": map[string]any{
					"index":      uint64(116),
					"size":       255868,
					"ts_packets": 1361,
					"aligned":    true,
					"first_byte": byte(0x47),
				},
			},
			AvgChunkSize:     ptr(255868.0),
			RecentChunkSizes: []int{255868, 255868, 255868, 255868, 255868},
			KeysFound:        []uint64{116, 117, 118, 119, 120},
			KeysMissing:      ptr([]uint64{}),
			TotalSampleBytes: ptr(1_279_340),
			EstimatedPackets: ptr(6805),
			IsTSAligned:      ptr(true),
		},
		LocalManager: localManagerPayload{
			Healthy:      true,
			Connected:    true,
			LastDataTime: 1_789_000_029.5,
			LastDataAge:  0.5,
		},
		VideoCodec:    "h264",
		Resolution:    "1920x1080",
		Width:         "1920",
		Height:        "1080",
		VideoBitrate:  "4500.0",
		SourceFPS:     "25.0",
		PixelFormat:   "yuv420p",
		AudioCodec:    "aac",
		SampleRate:    "48000",
		AudioChannels: "stereo",
		AudioBitrate:  "128.0",
		FFmpegSpeed:   &speed,
		FFmpegFPS:     "25.0",
		ActualFPS:     "24.5",
		StreamType:    "mpegts",
		Clients: []detailClientPayload{
			{
				ClientID:        "client_1789000000000_1234",
				UserAgent:       "VLC/3.0.20",
				WorkerID:        WorkerUnknown,
				IPAddress:       "198.51.100.4",
				UserID:          "7",
				OutputFormat:    "mpegts",
				OutputProfileID: &profileID,
				ConnectedAt:     1_789_000_001.25,
				LastActive:      1_789_000_029.5,
				LastActiveAgo:   0.5,
				BytesSent:       &bytesSent,
				AvgRateKBps:     &avgRate,
				CurrentRateKBps: &currentRate,
			},
			{
				ClientID:        "client_1789000000000_5678",
				UserAgent:       "unknown",
				WorkerID:        WorkerUnknown,
				IPAddress:       "198.51.100.9",
				UserID:          "0",
				OutputFormat:    "fmp4",
				OutputProfileID: nil,
				ConnectedAt:     1_789_000_010.0,
				LastActive:      1_789_000_029.0,
				LastActiveAgo:   1.0,
			},
		},
	}
}

func ptr[T any](v T) *T { return &v }

func decodeDetailGolden(t *testing.T) any {
	t.Helper()
	raw, err := os.ReadFile(detailGoldenPath)
	if err != nil {
		t.Fatalf("reading %s: %v -- regenerate it with "+
			"DISPATCHARR_WRITE_GOLDEN=1 python manage.py test "+
			"apps.proxy.tests.test_relay_detail_payload_golden", detailGoldenPath, err)
	}
	var want any
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatalf("decoding %s: %v", detailGoldenPath, err)
	}
	return want
}

// Compared as PARSED JSON, not bytes, for the list golden's reason (Amendment
// A3.7): DRF renders a Python float as "5.0" where encoding/json renders
// float64(5) as "5", every consumer parses, and nothing compares bytes. What
// the decode does not lose is the part that matters -- an absent key stays
// absent, a null stays nil, a string stays a string.
func TestTheDetailPayloadMatchesDjangosSerializer(t *testing.T) {
	want := decodeDetailGolden(t)

	encoded, err := json.Marshal(detailGoldenPayload())
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var got any
	if err := json.Unmarshal(encoded, &got); err != nil {
		t.Fatalf("decoding this relay's own payload: %v", err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("this relay's detail payload differs from the one Django's "+
			"RelayChannelDetailSerializer renders from the same fixture.\n got: %s\nwant: %s",
			encoded, mustMarshal(t, want))
	}
}

// Row 14, both clauses that differ BETWEEN the two endpoints, asserted
// against the two goldens together.
//
// A test that checked the string against only one endpoint proves nothing
// about the other -- the row's own Notes say exactly that -- so this reads
// both payloads in one test and would fail if either moved.
func TestOwnerAndSourceFPSDifferBetweenTheTwoEndpoints(t *testing.T) {
	detail, ok := decodeDetailGolden(t).(map[string]any)
	if !ok {
		t.Fatalf("the detail golden is not an object")
	}
	list, ok := decodeGolden(t).(map[string]any)
	if !ok {
		t.Fatalf("the list golden is not an object")
	}
	first, ok := list["channels"].([]any)[0].(map[string]any)
	if !ok {
		t.Fatalf("the list golden's first channel is not an object")
	}

	if detail["owner"] != OwnerUnknown {
		t.Errorf("owner on the detail endpoint is %v, want the literal %q "+
			"(channel_status.py:45's default; parity-matrix row 14)", detail["owner"], OwnerUnknown)
	}
	if first["owner"] != nil {
		t.Errorf("owner on the list endpoint is %v, want null (channel_status.py:474)", first["owner"])
	}

	if _, isString := detail["source_fps"].(string); !isString {
		t.Errorf("source_fps on the detail endpoint is %T, want a string: row 14's "+
			"third clause, which Phase 1 PR 7 did NOT unify", detail["source_fps"])
	}
	if _, isFloat := first["source_fps"].(float64); !isFloat {
		t.Errorf("source_fps on the list endpoint is %T, want a number", first["source_fps"])
	}

	// And the clause that IS unified, so "the two endpoints simply disagree
	// about everything" cannot be what makes this pass.
	if _, isFloat := detail["ffmpeg_speed"].(float64); !isFloat {
		t.Errorf("ffmpeg_speed on the detail endpoint is %T, want a number: PR 7 unified "+
			"it and parity holds it unified", detail["ffmpeg_speed"])
	}
	if _, isFloat := first["ffmpeg_speed"].(float64); !isFloat {
		t.Errorf("ffmpeg_speed on the list endpoint is %T, want a number", first["ffmpeg_speed"])
	}
}

// The two fields NEITHER relay can emit, asserted as absences on the golden.
//
// source_bitrate has no writer anywhere in the tree, and ffmpeg_bitrate is
// read under one constant and written under another (constants.py:90-91).
// Reproduced rather than fixed per D5, and asserted here so a later PR that
// "helpfully" starts emitting one has to change this test and say why.
func TestTheDetailPayloadOmitsTheTwoFieldsNothingWrites(t *testing.T) {
	encoded, err := json.Marshal(detailGoldenPayload())
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var payload map[string]any
	if err := json.Unmarshal(encoded, &payload); err != nil {
		t.Fatalf("decoding: %v", err)
	}
	for _, key := range []string{"source_bitrate", "ffmpeg_bitrate"} {
		if _, present := payload[key]; present {
			t.Errorf("the detail payload carries %q, which the Python relay never "+
				"emits either -- see NEVER_WRITTEN in "+
				"apps/proxy/tests/test_relay_detail_payload_golden.py", key)
		}
	}
	// The near neighbours that ARE emitted, so "every bitrate vanished"
	// cannot be what makes this pass.
	for _, key := range []string{"video_bitrate", "audio_bitrate", "avg_bitrate"} {
		if _, present := payload[key]; !present {
			t.Errorf("the detail payload is missing %q, which the hash does carry", key)
		}
	}
}
```

### Appendix Q — `relay/httpapi/detail_builder_test.go`

The four functions the golden cannot pin. `pythonFloat`'s expected values were printed by a `python3` in the repo's own test container and pasted in; the command is in the test's doc comment.

**`relay/httpapi/detail_builder_test.go`**

```go
package httpapi

import (
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
)

// pythonFloat renders what Python's str(round(x, n)) renders.
//
// THE EXPECTED VALUES ARE PYTHON'S OWN OUTPUT, printed by a python3 in the
// repo's test container and pasted here, not computed by Go -- an expected
// value the code under test computes cannot fail (hollow shape 1). The
// command:
//
//	docker exec <container> python3 -c "
//	for v, n in [(25.0,2),(29.97,2),(4500.0,1),(128.0,1),(24.456,1),
//	             (1.02,3),(0.0,1),(23.976,2),(1000000.0,1),(0.5,1)]:
//	    print(repr(str(round(v, n))))"
//
// THE ROWS THAT MATTER ARE THE WHOLE NUMBERS. Python's float repr always
// carries a decimal point -- str(25.0) is "25.0" -- where Go's shortest form
// is "25", so a status payload reporting source_fps "25" where the Python
// relay reports "25.0" is a wire difference on a field parity-matrix row 14
// is about. The rounding itself is already done by channel.Stats, which
// stores each value rounded the way its writer rounds it; this is the str()
// half alone, which is why the inputs below are the ROUNDED values.
func TestPythonFloatRendersWhatPythonsStrRoundRenders(t *testing.T) {
	for _, tc := range []struct {
		in   float64
		want string
	}{
		{25.0, "25.0"},
		{29.97, "29.97"},
		{4500.0, "4500.0"},
		{128.0, "128.0"},
		{24.5, "24.5"},
		{1.02, "1.02"},
		{0.0, "0.0"},
		{23.98, "23.98"},
		{1000000.0, "1000000.0"},
		{0.5, "0.5"},
	} {
		if got := pythonFloat(tc.in); got != tc.want {
			t.Errorf("pythonFloat(%v) = %q, want %q (Python's str(round(...)))", tc.in, got, tc.want)
		}
	}
}

// describeBufferStats over a REAL ring, because the golden pins the encoder
// and not this walk: break-checks 2 and 3 of this PR removed the decimal
// point and the keys_missing assignment and the golden test stayed GREEN,
// since its fixture is a struct literal that supplies both.
//
// THREE SHAPES: an empty ring, a fully resident sample, and one whose oldest
// sampled indices have been evicted.
func TestDescribeBufferStatsWalksTheRing(t *testing.T) {
	// 1. An empty ring: chunks 0, an empty diagnostics object, and none of
	// the sample keys -- channel_status.py:235's `if buffer_index > 0`.
	empty := buffer.New(buffer.Config{BudgetBytes: 10 * buffer.ChunkBytes, ChunkBytes: buffer.TSPacketSize * 2})
	stats := describeBufferStats(empty)
	if stats.Chunks != 0 || stats.KeysFound != nil || stats.KeysMissing != nil || stats.AvgChunkSize != nil {
		t.Fatalf("an empty ring produced %+v, want chunks 0 and no sample", stats)
	}
	if stats.Diagnostics == nil {
		t.Errorf("diagnostics is nil, where channel_status.py:231 seeds an empty dict")
	}

	// 2. A ring holding more than the sample: every sampled index is
	// resident, so keys_missing is PRESENT AND EMPTY -- the state the
	// serializer renders as [] and the Go encoder would drop with omitempty
	// on a plain slice.
	full := buffer.New(buffer.Config{BudgetBytes: 100 * buffer.TSPacketSize * 2, ChunkBytes: buffer.TSPacketSize * 2})
	for range 10 {
		if _, err := full.Write(make([]byte, buffer.TSPacketSize*2)); err != nil {
			t.Fatalf("writing to the ring: %v", err)
		}
	}
	stats = describeBufferStats(full)
	if stats.Chunks != full.Head() {
		t.Errorf("chunks is %d, want the head %d", stats.Chunks, full.Head())
	}
	if len(stats.KeysFound) != detailBufferSample {
		t.Errorf("keys_found holds %d indices, want the %d channel_status.py:237 samples",
			len(stats.KeysFound), detailBufferSample)
	}
	if stats.KeysMissing == nil {
		t.Fatalf("keys_missing is absent on a fully resident sample: channel_status.py:275 " +
			"assigns it inside the same arm as keys_found, so it renders as [] there")
	}
	if len(*stats.KeysMissing) != 0 {
		t.Errorf("keys_missing is %v on a fully resident sample", *stats.KeysMissing)
	}
	if stats.IsTSAligned == nil || !*stats.IsTSAligned {
		t.Errorf("is_ts_aligned is %v for chunks that are whole TS packets", stats.IsTSAligned)
	}
	first, ok := stats.Diagnostics["first_chunk"].(map[string]any)
	if !ok {
		t.Fatalf("diagnostics has no first_chunk: %v", stats.Diagnostics)
	}
	if first["first_byte"] != byte(0x00) {
		// The synthetic writes above are zero bytes, so this asserts the
		// field is the chunk's own first byte rather than a hard-coded 0x47.
		t.Errorf("first_byte is %v, want the chunk's own first byte", first["first_byte"])
	}

	// 3. A ring whose capacity is smaller than the sample window: the
	// oldest sampled indices have been evicted, so keys_missing NAMES THEM.
	// The cause differs from Python's -- eviction here, an expired key there
	// -- and the field's meaning does not.
	small := buffer.New(buffer.Config{BudgetBytes: 3 * buffer.TSPacketSize * 2, ChunkBytes: buffer.TSPacketSize * 2})
	for range 10 {
		if _, err := small.Write(make([]byte, buffer.TSPacketSize*2)); err != nil {
			t.Fatalf("writing to the small ring: %v", err)
		}
	}
	stats = describeBufferStats(small)
	if stats.KeysMissing == nil || len(*stats.KeysMissing) == 0 {
		t.Fatalf("keys_missing is %v on a ring that has evicted part of the sample window",
			stats.KeysMissing)
	}
	if len(stats.KeysFound)+len(*stats.KeysMissing) != detailBufferSample {
		t.Errorf("keys_found (%d) and keys_missing (%d) do not cover the %d-index window",
			len(stats.KeysFound), len(*stats.KeysMissing), detailBufferSample)
	}
}

// humanBytes is channel_status.py:141-149's total_data, across all four
// arms and at both sides of one boundary.
func TestHumanBytesMatchesTheFourArms(t *testing.T) {
	for _, tc := range []struct {
		in   uint64
		want string
	}{
		{0, "0 B"},
		{1023, "1023 B"},
		{1024, "1.00 KB"},
		{1024*1024 - 1, "1024.00 KB"},
		{1024 * 1024, "1.00 MB"},
		{9_999_888, "9.54 MB"},
		{1024 * 1024 * 1024, "1.00 GB"},
	} {
		if got := humanBytes(tc.in); got != tc.want {
			t.Errorf("humanBytes(%d) = %q, want %q", tc.in, got, tc.want)
		}
	}
}

// unixFloat is the seconds-since-epoch float every timestamp on these
// payloads is, and a zero time reports 0 rather than the year-1 epoch.
func TestUnixFloatReportsZeroForAZeroTime(t *testing.T) {
	if got := unixFloat(time.Time{}); got != 0 {
		t.Errorf("unixFloat(zero) = %v, want 0", got)
	}
	at := time.Unix(1_789_000_000, 500_000_000)
	if got := unixFloat(at); got != 1_789_000_000.5 {
		t.Errorf("unixFloat(%v) = %v, want 1789000000.5", at, got)
	}
}
```

### Appendix R — `relay/httpapi/control_test.go`

Five tests, and `internalCall`, which signs the way the real Django client signs -- a test that bypassed `RequireInternal` would be testing a handler no caller can reach.

**`relay/httpapi/control_test.go`**

```go
package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// internalCall makes one signed call to a /proxy/relay/... route and returns
// the status and the body.
//
// Signed the way the real Django client signs -- the static principal token
// plus the bound per-request one over the FULL path and the body -- because
// every one of these routes is behind RequireInternal and a test that
// bypassed the gate would be testing a handler no caller can reach.
func (r *rig) internalCall(t *testing.T, method, path string, body []byte) (int, []byte) {
	t.Helper()
	var reader io.Reader
	if body != nil {
		reader = bytes.NewReader(body)
	}
	request, err := http.NewRequestWithContext(t.Context(), method, r.Relay.URL+path, reader)
	if err != nil {
		t.Fatalf("building the %s %s request: %v", method, path, err)
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
	request.Header.Set(control.HeaderInternalRequest,
		control.InternalRequestHeader(testSecret, method, path, body, time.Now().Unix()))
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	defer func() { _ = response.Body.Close() }()
	raw, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the %s %s body: %v", method, path, err)
	}
	return response.StatusCode, raw
}

func decodeObject(t *testing.T, raw []byte) map[string]any {
	t.Helper()
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatalf("decoding %q: %v", raw, err)
	}
	return out
}

// The detail endpoint over a RUNNING channel, not a struct literal: the
// golden pins the wire shape and this pins that the builder fills it from a
// real tune. Row 14's owner and row 17's ip_address are the two clauses this
// half can assert, and both are asserted against the LIST endpoint in the
// same test, because half a row is not a row (2c-3's own words).
func TestTheDetailEndpointRendersARunningChannel(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-detail", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)
	waitForHead(t, r, "c-detail", 1)

	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-detail", nil)
	if status != http.StatusOK {
		t.Fatalf("GET the detail endpoint answered %d, want 200: %s", status, raw)
	}
	detail := decodeObject(t, raw)

	if detail["owner"] != OwnerUnknown {
		t.Errorf("owner is %v, want the literal %q (channel_status.py:45; row 14)", detail["owner"], OwnerUnknown)
	}
	if detail["channel_id"] != "c-detail" {
		t.Errorf("channel_id is %v", detail["channel_id"])
	}
	if detail["state"] == nil {
		t.Errorf("state is null on a channel that has recorded one")
	}

	clients, ok := detail["clients"].([]any)
	if !ok || len(clients) != 1 {
		t.Fatalf("the detail endpoint lists %v clients, want 1", detail["clients"])
	}
	client, ok := clients[0].(map[string]any)
	if !ok {
		t.Fatalf("the client row is not an object")
	}
	// ROW 17, on the detail endpoint: the address the authorize hop resolved
	// and carried on X-Relay-Client-IP, not the socket's peer -- which for a
	// loopback httptest server would be 127.0.0.1, so the assertion can fail.
	if client["ip_address"] != "198.51.100.4" {
		t.Errorf("ip_address is %v, want the hop's X-Relay-Client-IP", client["ip_address"])
	}
	if client["worker_id"] != WorkerUnknown {
		t.Errorf("worker_id is %v, want %q (channel_status.py:181's default; D2 deletes the worker)",
			client["worker_id"], WorkerUnknown)
	}

	// ROW 17's other half and row 14's other half, on the LIST endpoint, in
	// the same test and from the same running channel.
	listStatus, listRaw := r.listChannels(t, "?clients=all")
	if listStatus != http.StatusOK {
		t.Fatalf("the list endpoint answered %d", listStatus)
	}
	list := decodeObject(t, listRaw)
	listed, ok := list["channels"].([]any)[0].(map[string]any)
	if !ok {
		t.Fatalf("the list endpoint's first channel is not an object")
	}
	if listed["owner"] != nil {
		t.Errorf("owner on the list endpoint is %v, want null -- row 14 is an ASYMMETRY and "+
			"a test that checked one endpoint would prove nothing about the other", listed["owner"])
	}
	listedClient, ok := listed["clients"].([]any)[0].(map[string]any)
	if !ok {
		t.Fatalf("the list endpoint's first client is not an object")
	}
	if listedClient["ip_address"] != "198.51.100.4" {
		t.Errorf("ip_address on the list endpoint is %v, want the hop's", listedClient["ip_address"])
	}
}

// ?fields=state is the tune path's own read: two fields and nothing else,
// and a 404 with the SAME two-field shape for a channel this relay does not
// hold.
//
// Both halves in one test, because the 404 body is the thing that makes
// relay_client.get_channel able to map "not running" to None rather than to
// an outage, and a test that only checked the 200 would pass with a 404 that
// answered an HTML error page.
func TestFieldsStateAnswersTwoFieldsAndA404ForAnUnknownChannel(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-state", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-state?fields=state", nil)
	if status != http.StatusOK {
		t.Fatalf("?fields=state answered %d: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if len(body) != 2 {
		t.Errorf("?fields=state rendered %d keys, want exactly 2 (channel_id and state): %s", len(body), raw)
	}
	if body["channel_id"] != "c-state" || body["state"] == nil {
		t.Errorf("?fields=state answered %s", raw)
	}

	status, raw = r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-missing?fields=state", nil)
	if status != http.StatusNotFound {
		t.Fatalf("?fields=state for an unknown channel answered %d, want 404: %s", status, raw)
	}
	body = decodeObject(t, raw)
	if body["channel_id"] != "c-missing" {
		t.Errorf("the 404 body names %v, want the identifier asked about", body["channel_id"])
	}
	if state, present := body["state"]; !present || state != nil {
		t.Errorf("the 404 body's state is %v (present=%v), want an explicit null", state, present)
	}

	// And the FULL detail endpoint 404s with the same shape, which is what
	// relay_client.get_channel maps to None.
	status, raw = r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-missing", nil)
	if status != http.StatusNotFound {
		t.Fatalf("the detail endpoint for an unknown channel answered %d, want 404: %s", status, raw)
	}
	if body := decodeObject(t, raw); body["channel_id"] != "c-missing" || body["state"] != nil {
		t.Errorf("the detail 404 body is %s", raw)
	}
}

// DELETE stops the channel, and the body carries the state it was in.
//
// The stop is asserted through the MANAGER, not through the response: a
// handler that answered the right JSON and stopped nothing would pass a
// body-only check, and "the channel is gone from the map" is the thing
// /proxy/ts/stop/<id> exists to cause.
func TestDeletingAChannelStopsItAndReportsItsPreviousState(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-stop", "client-a")
	packetRun(t, "the client", response.Body, 1)
	waitForHead(t, r, "c-stop", 1)

	status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-stop", nil)
	_ = response.Body.Close()
	if status != http.StatusOK {
		t.Fatalf("DELETE answered %d: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if body["status"] != "success" {
		t.Fatalf("DELETE answered %s, want status success", raw)
	}
	previous, ok := body["previous_state"].(map[string]any)
	if !ok || previous["state"] == nil {
		t.Errorf("previous_state is %v, want the one-key dict channel_service.py:611 builds", body["previous_state"])
	}
	if body["model_released"] != true {
		t.Errorf("model_released is %v, want true", body["model_released"])
	}
	if r.Manager.Get("c-stop") != nil {
		t.Fatalf("the channel is still in the manager after a DELETE")
	}

	// A second DELETE is the not-found shape, which the Django wrapper turns
	// into its 404. Asserted as well, because a handler that answered
	// "success" unconditionally would pass everything above.
	status, raw = r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-stop", nil)
	if status != http.StatusOK {
		t.Fatalf("the second DELETE answered %d, want 200 with an error body: %s", status, raw)
	}
	body = decodeObject(t, raw)
	if body["status"] != "error" || body["message"] != "Channel not found" {
		t.Errorf("the second DELETE answered %s, want channel_service.py:604's error shape", raw)
	}
}

// DELETE on one client disconnects that client and leaves the other one
// streaming.
//
// BOTH HALVES, because a handler that tore the whole channel down would
// satisfy "the stopped client stopped" on its own.
func TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	first := r.tuneAs(t, "c-client", "client-a")
	defer func() { _ = first.Body.Close() }()
	second := r.tuneAs(t, "c-client", "client-b")
	defer func() { _ = second.Body.Close() }()
	packetRun(t, "client-a", first.Body, 1)
	packetRun(t, "client-b", second.Body, 1)
	waitFor(t, "both clients to register", 15*time.Second, func() bool {
		ch := r.Manager.Get("c-client")
		return ch != nil && ch.Clients() == 2
	})

	status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-client/clients/client-a", nil)
	if status != http.StatusOK {
		t.Fatalf("the client DELETE answered %d: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if body["status"] != "success" || body["locally_processed"] != true {
		t.Errorf("the client DELETE answered %s, want success with locally_processed true", raw)
	}
	if body["event_published"] != false {
		t.Errorf("event_published is %v, want false: D2 deletes the pub/sub and there is "+
			"no other worker to tell", body["event_published"])
	}

	waitFor(t, "the stopped client to leave the registry", 15*time.Second, func() bool {
		ch := r.Manager.Get("c-client")
		return ch != nil && ch.Clients() == 1
	})

	// The OTHER client is still being served. Read after the stop, so this
	// cannot pass on bytes that were already buffered before it.
	packetRun(t, "client-b", second.Body, 1)

	// An unknown client id on a running channel is still `success` with
	// locally_processed false -- channel_service.py 404s only on the
	// CHANNEL, and the Django wrapper maps only status=error to 404.
	status, raw = r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-client/clients/nobody", nil)
	if status != http.StatusOK {
		t.Fatalf("the unknown-client DELETE answered %d: %s", status, raw)
	}
	body = decodeObject(t, raw)
	if body["status"] != "success" || body["locally_processed"] != false {
		t.Errorf("an unknown client id answered %s, want success with locally_processed false", raw)
	}

	// An unknown CHANNEL is the error shape.
	status, raw = r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-nothing/clients/client-a", nil)
	if status != http.StatusOK {
		t.Fatalf("the unknown-channel client DELETE answered %d: %s", status, raw)
	}
	if body := decodeObject(t, raw); body["status"] != "error" {
		t.Errorf("an unknown channel answered %s, want the error shape", raw)
	}
}

// ROW 18, answered for the Go relay: the names come OFF THE WIRE, and when
// the answer carried none the keys are absent rather than filled.
//
// Python's get_detailed_channel_info has two ORM fallbacks here -- it looks
// the Stream and the M3UAccountProfile up by primary key when the metadata
// hash has no name (channel_status.py:71-79, :97-114) -- and 2b-1 put both
// names on the next-source answer so the hash always has them. The Go relay
// has NO fallback and can have none: those two queries are exactly what D2's
// "no Postgres driver" forbids. So the answer to row 18 here is "absent",
// and it is a stated divergence rather than parity: Python would fill the
// key from the row if the hash somehow lacked it.
//
// The populated case is asserted in the same test, so "every optional key is
// always absent" cannot be what makes this pass.
func TestTheNamesComeOffTheWireAndAreAbsentWhenTheAnswerCarriedNone(t *testing.T) {
	r := fanRigWith(t, relaytest.ControlPlaneConfig{Nameless: true}, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-nameless", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-nameless", nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d: %s", status, raw)
	}
	detail := decodeObject(t, raw)
	for _, key := range []string{"stream_name", "m3u_profile_name", "channel_name"} {
		if value, present := detail[key]; present {
			t.Errorf("the detail payload carries %q as %v for an answer that named none: the "+
				"Go relay has no ORM fallback and must not invent one", key, value)
		}
	}
	// stream_id IS present, so "the whole answer was empty" cannot be the
	// reason the three keys above vanished.
	if _, present := detail["stream_id"]; !present {
		t.Errorf("stream_id is absent too, so the three absences above prove nothing")
	}

	// And a named answer fills all three.
	named := fanRig(t, relaytest.Config{}, nil)
	namedResponse := named.tuneAs(t, "c-named", "client-a")
	defer func() { _ = namedResponse.Body.Close() }()
	packetRun(t, "the client", namedResponse.Body, 1)
	status, raw = named.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-named", nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d: %s", status, raw)
	}
	detail = decodeObject(t, raw)
	for _, key := range []string{"stream_name", "m3u_profile_name", "channel_name"} {
		if _, present := detail[key]; !present {
			t.Errorf("the detail payload is missing %q for an answer that carried it", key)
		}
	}
}
```

### Appendix S — `relay/httpapi/advance_test.go`

Four tests. `excludedStreamIDs` reads the tried set the only way it is observable -- the `exclude_stream_ids` a failover would send -- which is also the only thing it is for.

**`relay/httpapi/advance_test.go`**

```go
package httpapi

import (
	"encoding/json"
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// advanceBody is what change_stream and next_stream send: the fully-resolved
// source, plus the stream_profile 2c-8 adds so the relay has an argv to
// spawn (it builds no command line, Amendment A4.1).
func advanceBody(t *testing.T, url string, streamID int, resetTried bool) []byte {
	t.Helper()
	body, err := json.Marshal(map[string]any{
		"url":              url,
		"user_agent":       "Dispatcharr/1.0",
		"stream_id":        streamID,
		"m3u_profile_id":   3,
		"stream_name":      "The Alternate",
		"channel_name":     "BBC One HD",
		"m3u_profile_name": "Premium",
		"reset_tried":      resetTried,
		"transcode":        false,
		"stream_profile": map[string]any{
			"id":      1,
			"command": "",
			"args":    "",
			"kind":    "proxy",
			"argv":    []string{},
		},
	})
	if err != nil {
		t.Fatalf("encoding the advance body: %v", err)
	}
	return body
}

// An operator's switch moves the channel to the named URL, keeps the client
// attached and raises the stream_switch event update_url raises.
//
// FOUR THINGS TOGETHER, because any three are satisfiable without the
// switch: the alternate upstream is contacted, the listed stream_id moves,
// the client is still attached and still fed, and the event names the new
// stream.
func TestAnAdvanceSwitchesTheChannelAndKeepsTheClientFed(t *testing.T) {
	r, alternate := failoverRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-advance", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client before the switch", response.Body, 100)
	if got := listedStreamID(t, r); got != 1 {
		t.Fatalf("stream_id = %d before the advance, want 1", got)
	}

	status, raw := r.internalCall(t, http.MethodPost,
		"/proxy/relay/channels/c-advance/advance", advanceBody(t, alternate.URL(), 2, true))
	if status != http.StatusOK {
		t.Fatalf("the advance answered %d: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if body["status"] != "success" || body["success"] != true {
		t.Fatalf("the advance answered %s, want status success and success true", raw)
	}
	if body["direct_update"] != true {
		t.Errorf("direct_update is %v, want true: one process is always the owner", body["direct_update"])
	}

	// WAIT ON THE ALTERNATE, NOT ON THE LISTED STREAM ID. `applySwitch` sets
	// the channel's SourceInfo on the handler's own goroutine, so
	// listedStreamID flips the instant the advance returns -- before the run
	// loop has picked up the parked source and dialled anything. Waiting on
	// that and then asserting the upstream was contacted is a race the
	// assertion loses about half the time without `-race` to slow it down
	// (measured: 8/8 green under -race, 2/3 without). The alternate being
	// contacted is what this test is about, so it is what the wait is on;
	// the listed id is asserted afterwards, when it is no longer a latch
	// that fires early.
	waitFor(t, "the alternate to be contacted", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
	if n := alternate.Requests(); n != 1 {
		t.Fatalf("the alternate saw %d requests, want 1", n)
	}
	if got := listedStreamID(t, r); got != 2 {
		t.Fatalf("stream_id = %d after the advance, want 2", got)
	}
	// The client is still attached and still receiving whole packets from
	// the NEW upstream: readAligned rather than packetRun, because the two
	// upstreams' packet indices do not continue one another.
	readAligned(t, response.Body, 100)
	if ch := listedChannel(t, r); ch["client_count"] != 1.0 {
		t.Fatalf("client_count = %v after the advance, want 1", ch["client_count"])
	}

	var switches []relaytest.RecordedEvent
	waitFor(t, "the stream_switch event", 10*time.Second, func() bool {
		switches = r.Control.EventsOfType("stream_switch")
		return len(switches) == 1
	})
	if switches[0].StreamID == nil || *switches[0].StreamID != 2 {
		t.Fatalf("stream_switch = %+v, want stream 2", switches[0])
	}
}

// The three refusals, each with its own answer.
//
// A body with no url and a body with no stream_profile are both 400 -- what
// DRF's own payload.is_valid(raise_exception=True) answers -- and an unknown
// channel is the 200-with-an-error-body shape the Django wrapper turns into
// its 404. Asserting all three together is what stops a handler that
// answered one status for everything from passing.
func TestAnAdvanceRefusesAMalformedBodyAndAnUnknownChannel(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-refuse", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	noURL := []byte(`{"user_agent":"x","stream_profile":{"id":1,"command":"","args":"","kind":"proxy","argv":[]}}`)
	if status, raw := r.internalCall(t, http.MethodPost, "/proxy/relay/channels/c-refuse/advance", noURL); status != http.StatusBadRequest {
		t.Errorf("an advance with no url answered %d, want 400: %s", status, raw)
	}

	noProfile := []byte(`{"url":"http://provider.invalid/x.ts"}`)
	if status, raw := r.internalCall(t, http.MethodPost, "/proxy/relay/channels/c-refuse/advance", noProfile); status != http.StatusBadRequest {
		t.Errorf("an advance with no stream_profile answered %d, want 400 -- the relay "+
			"builds no command line and cannot spawn without one: %s", status, raw)
	}

	status, raw := r.internalCall(t, http.MethodPost,
		"/proxy/relay/channels/c-nothing/advance", advanceBody(t, "http://provider.invalid/x.ts", 2, false))
	if status != http.StatusOK {
		t.Fatalf("an advance for an unknown channel answered %d, want 200 with an error body: %s", status, raw)
	}
	body := decodeObject(t, raw)
	if body["status"] != "error" || body["message"] != "Channel not found" {
		t.Errorf("an unknown channel answered %s, want channel_service.py:478-482's shape", raw)
	}
	diagnostics, ok := body["diagnostics"].(map[string]any)
	if !ok || diagnostics["in_local_managers"] != false {
		t.Errorf("diagnostics is %v, want in_local_managers false", body["diagnostics"])
	}
}

// An advance naming the URL already playing is reported as SUCCESS and
// switches nothing.
//
// update_url returns False for an unchanged URL (input/manager.py:1463-1465)
// and change_stream_url still reports success, because that layer treats it
// as a metadata refresh -- ":487-490 -- update_url() returns False for same
// URL; still success so metadata refreshes". Both halves are asserted: the
// answer AND the absence of a second upstream connection.
func TestAnAdvanceToTheURLAlreadyPlayingSucceedsAndSwitchesNothing(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-same", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 100)
	before := r.Upstream.Requests()

	current := r.Manager.Get("c-same").Source().URL
	if current == "" {
		t.Fatalf("the channel has no source URL to repeat")
	}
	status, raw := r.internalCall(t, http.MethodPost,
		"/proxy/relay/channels/c-same/advance", advanceBody(t, current, 1, false))
	if status != http.StatusOK {
		t.Fatalf("the advance answered %d: %s", status, raw)
	}
	if body := decodeObject(t, raw); body["success"] != true {
		t.Errorf("an advance to the URL already playing answered %s, want success true", raw)
	}

	// Nothing switched: the upstream was not reconnected, and no
	// stream_switch was raised. Both, because either alone could be true for
	// the wrong reason.
	time.Sleep(500 * time.Millisecond)
	if after := r.Upstream.Requests(); after != before {
		t.Errorf("the upstream saw %d requests after an unchanged-URL advance, want the %d it had", after, before)
	}
	if got := r.Control.EventsOfType("stream_switch"); len(got) != 0 {
		t.Errorf("an unchanged-URL advance raised %d stream_switch events, want 0", len(got))
	}
}

// reset_tried clears the exclusion list an automatic failover built, which is
// what /proxy/ts/change_stream/ asks for and /proxy/ts/next_stream/ does not.
//
// Asserted through the NEXT-SOURCE REQUEST that follows, not through an
// internal field: the tried set is only observable as the exclude_stream_ids
// the relay sends, which is also the only thing it is for.
func TestResetTriedClearsTheExclusionListAndOmittingItDoesNot(t *testing.T) {
	for _, tc := range []struct {
		name       string
		resetTried bool
		wantStream int
	}{
		// With reset_tried, stream 1 is excluded again only because the
		// advance itself records stream 2 -- so the list the relay sends
		// next holds exactly the one stream the advance named.
		{"reset_tried clears it", true, 2},
		// Without it, stream 1 stays in the set the tune put it in.
		{"without reset_tried", false, 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r, alternate := failoverRig(t, relaytest.Config{}, nil)
			response := r.tuneAs(t, "c-tried", "client-a")
			defer func() { _ = response.Body.Close() }()
			packetRun(t, "the client", response.Body, 10)

			status, raw := r.internalCall(t, http.MethodPost,
				"/proxy/relay/channels/c-tried/advance", advanceBody(t, alternate.URL(), 2, tc.resetTried))
			if status != http.StatusOK {
				t.Fatalf("the advance answered %d: %s", status, raw)
			}
			// The alternate again, for the reason above: the listed id flips
			// on the handler's goroutine and the dial happens later.
			waitFor(t, "the alternate to be contacted", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
			if got := listedStreamID(t, r); got != 2 {
				t.Fatalf("stream_id = %d after the advance, want 2", got)
			}

			excluded := excludedStreamIDs(t, r)
			if tc.resetTried {
				if len(excluded) != 1 || excluded[0] != tc.wantStream {
					t.Fatalf("after reset_tried the relay would exclude %v, want just [%d]", excluded, tc.wantStream)
				}
				return
			}
			if !containsInt(excluded, tc.wantStream) {
				t.Fatalf("without reset_tried the relay would exclude %v, which has lost stream %d", excluded, tc.wantStream)
			}
		})
	}
}

// excludedStreamIDs is the tried set, read the only way it is observable:
// the exclude_stream_ids a failover would send.
func excludedStreamIDs(t *testing.T, r *rig) []int {
	t.Helper()
	ch := r.Manager.Get("c-tried")
	if ch == nil {
		t.Fatalf("the channel is not running")
	}
	return ch.ExcludedStreamIDs()
}

func containsInt(haystack []int, needle int) bool {
	for _, v := range haystack {
		if v == needle {
			return true
		}
	}
	return false
}
```

### Appendix T — `relay/httpapi/events_test.go`

Four tests. Two of them assert an asymmetry with both halves in one test, which is what makes them able to fail.

**`relay/httpapi/events_test.go`**

```go
package httpapi

import (
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// eventsOf waits for at least n events of a type and returns them.
func eventsOf(t *testing.T, r *rig, typ string, n int) []relaytest.RecordedEvent {
	t.Helper()
	var got []relaytest.RecordedEvent
	waitFor(t, "the "+typ+" event", 10*time.Second, func() bool {
		got = r.Control.EventsOfType(typ)
		return len(got) >= n
	})
	return got
}

// channel_start, raised where server.py:832-842 raises it, with the two
// details it carries.
//
// stream_id is asserted BOTH at the top level and inside details, because
// emit_event lifts it and LEAVES it (control_plane.py:331-333), and
// core/relay_events.py's _apply_stream_stats is written around that shape --
// a relay that lifted without leaving would be a silent loss there.
func TestATuneRaisesChannelStart(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-start", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	starts := eventsOf(t, r, "channel_start", 1)
	if len(starts) != 1 {
		t.Fatalf("the control plane saw %d channel_start events, want 1", len(starts))
	}
	if starts[0].ChannelID != "c-start" {
		t.Errorf("channel_start named channel %q", starts[0].ChannelID)
	}
	if starts[0].StreamID == nil || *starts[0].StreamID != 1 {
		t.Errorf("channel_start's top-level stream_id is %v, want 1", starts[0].StreamID)
	}
	if got, ok := starts[0].Details["stream_id"].(float64); !ok || int(got) != 1 {
		t.Errorf("channel_start's details lost stream_id (%v): emit_event LEAVES it there "+
			"as well as lifting it", starts[0].Details["stream_id"])
	}
	if _, ok := starts[0].Details["stream_name"]; !ok {
		t.Errorf("channel_start carries no stream_name")
	}
}

// client_connect is raised for BOTH client types (Amendment A6.5), and
// client_disconnect for the TS one ONLY.
//
// ONE TEST FOR BOTH HALVES, and that is what makes it able to fail: a relay
// that raised client_connect for TS alone, or client_disconnect for both,
// would pass a test that looked at one client type. The fMP4 asymmetry is
// Python's -- emit_event appears exactly once in output/fmp4/generator.py,
// at :114 -- and it is reproduced, not evened out.
func TestBothClientTypesConnectAndOnlyTheTSOneDisconnects(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))

	ts := r.tuneAs(t, "c-events", "client-ts")
	packetRun(t, "the TS client", ts.Body, 1)
	fmp4 := r.tuneFMP4(t, "c-events", "client-fmp4")
	if got := readAtLeast(fmp4.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second); len(got) == 0 {
		t.Fatalf("the fMP4 client received nothing")
	}

	connects := eventsOf(t, r, "client_connect", 2)
	seen := map[string]bool{}
	for _, e := range connects {
		seen[e.ClientID] = true
		if e.ChannelID != "c-events" {
			t.Errorf("client_connect named channel %q", e.ChannelID)
		}
		// client_id is lifted to the top level AND left in details, the same
		// two-name rule stream_id follows (control_plane.py:331-333).
		if got, _ := e.Details["client_id"].(string); got != e.ClientID {
			t.Errorf("client_connect's details carry client_id %q where the top level carries %q", got, e.ClientID)
		}
		if e.Details["client_ip"] != "198.51.100.4" {
			t.Errorf("client_connect carries client_ip %v, want the hop's address", e.Details["client_ip"])
		}
	}
	for _, want := range []string{"client-ts", "client-fmp4"} {
		if !seen[want] {
			t.Errorf("no client_connect for %s: Amendment A6.5 owes it for BOTH client types", want)
		}
	}

	// Both clients leave. Only the TS one announces it.
	_ = ts.Body.Close()
	_ = fmp4.Body.Close()
	disconnects := eventsOf(t, r, "client_disconnect", 1)
	if len(disconnects) != 1 {
		t.Fatalf("the control plane saw %d client_disconnect events, want exactly 1 -- the "+
			"fMP4 generator raises none (emit_event appears once in that file, at :114)", len(disconnects))
	}
	if disconnects[0].ClientID != "client-ts" {
		t.Errorf("client_disconnect named %q, want the TS client", disconnects[0].ClientID)
	}
	if _, ok := disconnects[0].Details["duration"].(float64); !ok {
		t.Errorf("client_disconnect carries duration %v, want a number (round(elapsed, 2))",
			disconnects[0].Details["duration"])
	}
	if _, ok := disconnects[0].Details["bytes_sent"].(float64); !ok {
		t.Errorf("client_disconnect carries bytes_sent %v, want a number",
			disconnects[0].Details["bytes_sent"])
	}
}

// Stopping a channel through the control route raises channel_stop, with the
// runtime and the byte total _collect_channel_stop_event_data snapshots.
func TestStoppingAChannelRaisesChannelStop(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-stopevent", "client-a")
	packetRun(t, "the client", response.Body, 10)
	waitForHead(t, r, "c-stopevent", 1)

	if status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-stopevent", nil); status != http.StatusOK {
		t.Fatalf("DELETE answered %d: %s", status, raw)
	}
	_ = response.Body.Close()

	// CLOSE THE EMITTER BEFORE COUNTING, and that is the whole difference
	// between "at least one" and "exactly one". eventsOf returns as soon as
	// the first event lands, so a second raise arriving a moment later is
	// invisible to a len() check that runs immediately after it -- the same
	// latch-that-fires-early hazard Constraint 55 names, relocated from a
	// wait into an assertion. Close drains the queue and waits for the
	// worker, so after it there is nothing in flight to arrive late.
	// Demonstrated: with a second c.emitStop() injected into Manager.Stop,
	// the at-least-one shape passed 6/6 and this one reddens.
	eventsOf(t, r, "channel_stop", 1)
	r.Emitter.Close()
	stops := r.Control.EventsOfType("channel_stop")
	if len(stops) != 1 {
		t.Fatalf("the control plane saw %d channel_stop events, want exactly 1: a channel "+
			"announces its ending from ONE place, run's deferred emitStop (Ruling R9)", len(stops))
	}
	if stops[0].ChannelID != "c-stopevent" {
		t.Errorf("channel_stop named %q", stops[0].ChannelID)
	}
	total, ok := stops[0].Details["total_bytes"].(float64)
	if !ok || total <= 0 {
		t.Errorf("channel_stop carries total_bytes %v, want the bytes the ring took",
			stops[0].Details["total_bytes"])
	}
}

// A TS client's detail row carries the three byte counters and an fMP4
// client's does not.
//
// THE ASYMMETRY IS THE ASSERTION, and both halves are in one test: a relay
// that recorded bytes for every client would satisfy "the TS client has
// counters" on its own, and one that recorded none would satisfy "the fMP4
// client has none".
func TestOnlyATSClientsDetailRowCarriesTheByteCounters(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))

	ts := r.tuneAs(t, "c-counters", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	packetRun(t, "the TS client", ts.Body, 100)
	fmp4 := r.tuneFMP4(t, "c-counters", "client-fmp4")
	defer func() { _ = fmp4.Body.Close() }()
	// PAST THE INIT SEGMENT, deliberately: serveFMP4 writes the init BEFORE
	// the fragment loop starts, so a read that stopped there would query the
	// detail endpoint before the loop had run once -- and an fMP4 row with
	// no counters would then prove nothing, since a client that had sent
	// nothing would have none either way. Break-check 9 stayed GREEN until
	// this read was widened.
	want := len(relaytest.SyntheticFMP4Init()) + 2*len(relaytest.SyntheticFMP4Fragment(0))
	if got := readAtLeast(fmp4.Body, want, 15*time.Second); len(got) < want {
		t.Fatalf("the fMP4 client received %d bytes, want at least %d -- past the init "+
			"segment and into the fragment loop", len(got), want)
	}

	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-counters", nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d: %s", status, raw)
	}
	rows, ok := decodeObject(t, raw)["clients"].([]any)
	if !ok || len(rows) != 2 {
		t.Fatalf("the detail endpoint lists %v clients, want 2", len(rows))
	}
	byID := map[string]map[string]any{}
	for _, row := range rows {
		client, ok := row.(map[string]any)
		if !ok {
			t.Fatalf("a client row is not an object")
		}
		id, _ := client["client_id"].(string)
		byID[id] = client
	}

	tsRow, fmp4Row := byID["client-ts"], byID["client-fmp4"]
	if tsRow == nil || fmp4Row == nil {
		t.Fatalf("the detail endpoint listed %v, want both clients", byID)
	}
	for _, key := range []string{"bytes_sent", "avg_rate_KBps", "current_rate_KBps"} {
		if _, present := tsRow[key]; !present {
			t.Errorf("the TS client's row has no %q: output/ts/generator.py:511-519 writes it", key)
		}
		if _, present := fmp4Row[key]; present {
			t.Errorf("the fMP4 client's row carries %q as %v: output/fmp4/generator.py writes "+
				"last_active and nothing else (:288-295)", key, fmp4Row[key])
		}
	}
	if sent, _ := tsRow["bytes_sent"].(float64); sent <= 0 {
		t.Errorf("the TS client's bytes_sent is %v after 100 packets", tsRow["bytes_sent"])
	}
	// Both rows DO carry last_active, so "the fMP4 row is empty" cannot be
	// what makes the absences above pass.
	for id, row := range map[string]map[string]any{"client-ts": tsRow, "client-fmp4": fmp4Row} {
		if _, present := row["last_active"]; !present {
			t.Errorf("%s has no last_active, which both generators write", id)
		}
	}
}
```

### Appendix U — `relay/httpapi/fanout_test.go` and `transcode_test.go`

Two of the five narrowed request-count assertions. The other three are in `stream_test.go`, Appendix AJ. Constraint 33, become load-bearing.

**`relay/httpapi/fanout_test.go`**

```diff
--- a/httpapi/fanout_test.go
+++ b/httpapi/fanout_test.go
@@ -382,9 +382,13 @@
 			"shape and still streams", response.StatusCode)
 	}
 
-	calls := r.Control.Requests()
+	// NAMED BY ROUTE, not counted across the whole fake (Global Constraint
+	// 33): since 2c-8 every published channel also posts channel_start to
+	// /api/relay/events, so a bare Requests() count here would be 2 and would
+	// say nothing about the tune.
+	calls := r.Control.RequestsTo("/next-source")
 	if len(calls) != 1 {
-		t.Fatalf("the relay made %d control-plane calls, want 1", len(calls))
+		t.Fatalf("the relay made %d next-source calls, want 1", len(calls))
 	}
 	if got := calls[0].Path; got != "/api/relay/channels/c-untrusted/next-source" {
 		t.Fatalf("the tune asked about %s: an unverified X-Relay-Channel was believed", got)
@@ -682,7 +686,7 @@
 		t.Fatal("the second client neither started nor failed within twenty seconds")
 	}
 
-	if got := r.Control.Requests(); len(got) != 1 {
+	if got := r.Control.RequestsTo("/next-source"); len(got) != 1 {
 		t.Fatalf("the relay made %d next-source calls, want 1 -- the first client's disconnect "+
 			"cancelled next-source for the client waiting behind it, which then had to call again", len(got))
 	}
```

**`relay/httpapi/transcode_test.go`**

```diff
--- a/httpapi/transcode_test.go
+++ b/httpapi/transcode_test.go
@@ -105,9 +105,9 @@
 	if n := r.Upstream.Requests(); n != 1 {
 		t.Fatalf("the provider saw %d requests, want exactly 1 -- from the child, not the relay", n)
 	}
-	seen := r.Control.Requests()
+	seen := r.Control.RequestsTo("/next-source")
 	if len(seen) != 1 || !strings.HasSuffix(seen[0].Path, "/c-transcode/next-source") {
-		t.Fatalf("the control plane saw %d calls: %+v", len(seen), seen)
+		t.Fatalf("the control plane saw %d next-source calls: %+v", len(seen), seen)
 	}
 }
 
```

### Appendix V — `relay/control/authorize.go`

The dev fallback's client. One attempt and no retry, and the doc comment says why. The four denial statuses are a DECISION; every other 4xx is the contract being wrong.

**`relay/control/authorize.go`**

```go
package control

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// AuthorizePath is the dev fallback's route, spec D5 exception 2.
//
// ITS OWN PATH, not /_dispatcharr/authorize, and § The contract says why at
// length: that one is an `internal;` exact-match nginx location, so a POST to
// it is 404'd before Django sees it in every nginx-fronted deployment --
// which would turn a SECRET_KEY mismatch between the api and relay roles from
// today's silent-but-working degrade into every live tune failing.
const AuthorizePath = "/_dispatcharr/authorize-internal"

// The seven response headers a 200 carries: the five Phase 1 PR 5 defined
// plus 2b-2's two. The same seven any relay-bound nginx location sets, which
// is what makes the nginx shape and this one answer with the same material.
const (
	HeaderRelayChannel      = "X-Relay-Channel"
	HeaderRelayOutput       = "X-Relay-Output"
	HeaderRelayClient       = "X-Relay-Client"
	HeaderRelayUser         = "X-Relay-User"
	HeaderRelayName         = "X-Relay-Name"
	HeaderRelayOutputFormat = "X-Relay-Output-Format"
	HeaderRelayClientIP     = "X-Relay-Client-IP"
)

// AuthorizeHeaders is the three credential-bearing headers the authenticator
// union can consume, each null when the client sent none.
//
// THREE, NOT TWO. ApiKeyAuthentication (apps/accounts/authentication.py:
// 46-85) checks X-API-Key BEFORE falling back to an `Authorization: ApiKey
// ...` header, so a client authenticating that way would resolve to anonymous
// in this shape and to its real user in production -- the cross-shape
// divergence D5 exists to prevent.
//
// A sub-object rather than three flat fields, deliberately: a fourth
// credential header discovered later is a field, not a body-shape redesign.
type AuthorizeHeaders struct {
	Authorization *string `json:"authorization"`
	Cookie        *string `json:"cookie"`
	APIKey        *string `json:"x-api-key"`
}

// AuthorizeRequest is the question, in full, so that sha256(body) binds it.
//
// NO IDENTITY-BEARING MATERIAL TRAVELS AS A HEADER ON THIS ROUTE. The bound
// token signs exactly five fields -- the context, the method, the full path,
// the timestamp and sha256(body) -- and headers are not among them, so a
// captured X-Dispatcharr-Internal-Request for this path would otherwise stay
// valid for 120 seconds against ANY combination of forwarded headers.
type AuthorizeRequest struct {
	// URI is the full path and query string being authorized, the equivalent
	// of nginx's X-Original-URI.
	URI string `json:"uri"`

	// ClientIP is the viewer's address, which Django evaluates the STREAMS
	// ACL against (apps/proxy/authorize.py:425). Without it Django would
	// judge THIS RELAY'S address -- wrong in exactly the nginx-less
	// deployments this call exists for.
	ClientIP string `json:"client_ip"`

	// Internal is whether the CLIENT's request was internal -- the DVR's own
	// fetch, which carries the static X-Dispatcharr-Internal with no bound
	// counterpart. NEVER the transport's own header, which IsInternalRelay
	// requires this call to send and which therefore answers only "the
	// caller is part of the deployment". Django reads request_is_internal off
	// the request it is handed and returns INTERNAL_PRINCIPAL before any
	// channel flag, adult filter, profile membership or XC credential is
	// looked at, so collapsing the two questions authorizes every tune in
	// every nginx-less deployment, unconditionally.
	Internal bool `json:"internal"`

	Headers AuthorizeHeaders `json:"headers"`
}

// Decision is what a 200 carries: the seven X-Relay-* values, which are
// exactly what the trusted path reads off the request instead.
type Decision struct {
	ChannelUUID     string
	OutputProfileID string
	ClientID        string
	UserID          string
	RelayName       string
	OutputFormat    string
	ClientIP        string
}

// Denied is a refusal, carrying THE TRUE STATUS.
//
// Django's authorize_internal_view answers with authorize_error_response,
// never subrequest_error_response's 403 collapse: that shape exists only
// because ngx_http_auth_request_module can transport a 2xx, a 401 and a 403
// and nothing else, and a direct POST has no such constraint. So a 404 for an
// unknown channel and a 429 for a user over their stream limit arrive as
// themselves and reach the viewer as themselves, which is what the Python
// relay's own inline fallback already does.
type Denied struct {
	Status int

	// Body is the JSON denial AuthorizeDenialSerializer rendered --
	// {"error": "..."} -- forwarded to the viewer verbatim because that is
	// what the Python relay's inline path already returns to them
	// (resolve_authorization lets AuthorizeDenied propagate and the stream
	// view answers authorize_error_response). Nil unless the answer was
	// application/json and inside DeniedBodyLimit, so a 500 HTML page or a
	// proxy's error document can never be echoed.
	Body []byte
}

func (e *Denied) Error() string {
	return fmt.Sprintf("control: the control plane denied the tune with %d", e.Status)
}

// DeniedBodyLimit bounds how much of a denial body is forwarded. Four
// kibibytes is three orders of magnitude more than {"error": "Stream limit
// exceeded (3 concurrent streams allowed)"} needs and small enough that a
// misconfigured upstream cannot make this relay buffer a page per tune.
const DeniedBodyLimit = 4 << 10

// Authorize asks Django to authorize one tune.
//
// ONE ATTEMPT, NO RETRY, and that is a decision rather than an oversight:
// this call is the in-process authorize_stream() call's successor, and the
// Python relay's inline path cannot fail with a 5xx because there is no wire
// between it and the decision. A retry here would add up to a second
// (ConnectTimeout + ReadTimeout) to the tune's critical path for a fault that
// a second attempt against the same misconfigured or overloaded Django will
// meet again.
func (c *Client) Authorize(ctx context.Context, req AuthorizeRequest) (*Decision, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("encoding the authorize request: %w", err) // credential-logging: ok - encoding/json reports a TYPE it cannot encode, never a field's value
	}

	base := c.BaseURL
	if base == "" {
		resolved, baseErr := BaseURL()
		if baseErr != nil {
			return nil, baseErr
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

	request, err := http.NewRequestWithContext(ctx, http.MethodPost, base+AuthorizePath, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("building the request for %s: %w", AuthorizePath, redact.Error(err))
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set(HeaderInternal, InternalPrincipalToken(c.Secret))
	request.Header.Set(HeaderInternalRequest,
		InternalRequestHeader(c.Secret, http.MethodPost, AuthorizePath, body, now().Unix()))

	response, err := httpClient.Do(request)
	if err != nil {
		return nil, &Unavailable{Path: AuthorizePath, Reason: "transport failure", Err: err}
	}
	defer func() { _ = response.Body.Close() }()

	status := response.StatusCode
	switch {
	case status >= 200 && status < 300:
	case status >= 300 && status < 400:
		return nil, &Unavailable{Path: AuthorizePath, Reason: fmt.Sprintf("answered %d; a redirect is never followed", status)}
	case status == http.StatusUnauthorized, status == http.StatusForbidden,
		status == http.StatusNotFound, status == http.StatusTooManyRequests:
		// A DECISION, not an outage: these are the four statuses
		// AuthorizeDenied is raised with (apps/proxy/authorize.py), and each
		// must reach the viewer as itself.
		return nil, &Denied{Status: status, Body: deniedBody(response)}
	case status >= 400 && status < 500:
		// Every other 4xx is the contract being wrong -- a 400 from the
		// serializer, a 403 from IsInternalRelay on a SECRET_KEY mismatch
		// between roles -- and must fail loudly rather than be reported to
		// the viewer as a refusal of their tune.
		return nil, &Refused{Path: AuthorizePath, Status: status}
	default:
		return nil, &Unavailable{Path: AuthorizePath, Reason: fmt.Sprintf("answered %d", status)}
	}

	// The decision is entirely in the headers; an undrained body keeps the
	// connection out of the pool.
	_, _ = io.Copy(io.Discard, response.Body)

	return &Decision{
		ChannelUUID:     response.Header.Get(HeaderRelayChannel),
		OutputProfileID: response.Header.Get(HeaderRelayOutput),
		ClientID:        response.Header.Get(HeaderRelayClient),
		UserID:          response.Header.Get(HeaderRelayUser),
		RelayName:       response.Header.Get(HeaderRelayName),
		OutputFormat:    response.Header.Get(HeaderRelayOutputFormat),
		ClientIP:        response.Header.Get(HeaderRelayClientIP),
	}, nil
}

// deniedBody reads the denial's JSON body, or nil.
func deniedBody(response *http.Response) []byte {
	if ct := response.Header.Get("Content-Type"); !strings.HasPrefix(ct, "application/json") {
		return nil
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, DeniedBodyLimit))
	if err != nil || len(raw) == 0 {
		return nil
	}
	return raw
}
```

### Appendix W — `relay/httpapi/authorize.go`

`authorizeTune`, the header-to-decision map `identify` reads through, and the failure writer. Constraints 47, 48 and 50 are all in this file's comments.

**`relay/httpapi/authorize.go`**

```go
package httpapi

import (
	"context"
	"errors"
	"log/slog"
	"net/http"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// authorizeTune is the dev fallback (spec D5, exception 2): when nginx did
// not authorize this request, ask Django to, over HTTP.
//
// Returns (nil, nil) on a trusted request, which is every tune in every
// nginx-fronted deployment -- the same frequency at which the Python relay
// takes its own inline path (resolve_authorization's non-trusted branch,
// apps/proxy/authorize_views.py:183-196).
//
// WHAT TRAVELS AND WHAT DOES NOT. Everything identity-bearing goes in the
// BODY, because the bound token signs sha256(body) and signs no header: a
// captured X-Dispatcharr-Internal-Request for this path would otherwise stay
// valid for 120 seconds against any combination of forwarded headers. In
// particular `internal` is a body field read off the CLIENT's own static
// marker, never the transport's own X-Dispatcharr-Internal, which this call
// must send to satisfy IsInternalRelay and which answers a different question
// ("the caller is part of the deployment", not "this request is internal").
func authorizeTune(r *http.Request, deps StreamDeps, log *slog.Logger) (*control.Decision, error) {
	if control.IsRelayTrusted(deps.Secret, r.Header.Get(control.HeaderAuthorized)) {
		return nil, nil
	}
	if deps.Control == nil {
		// A rig with no control plane. Nothing to ask, so nothing is
		// asserted about the request: the caller falls through to the path
		// value and to values resolved locally, which is what 2c-2 through
		// 2c-7 did on every untrusted tune.
		return nil, nil
	}

	ctx, cancel := context.WithTimeout(r.Context(), control.ConnectTimeout+control.ReadTimeout)
	defer cancel()

	decision, err := deps.Control.Authorize(ctx, control.AuthorizeRequest{
		// RequestURI(), not Path: the query string carries ?token=,
		// ?session_id= and ?output_format=, and Django's own hop resolves
		// the surface from X-Original-URI with its query attached.
		URI:      r.URL.RequestURI(),
		ClientIP: peerAddress(r),
		Internal: control.IsInternalPrincipal(deps.Secret, r.Header.Get(control.HeaderInternal)),
		Headers: control.AuthorizeHeaders{
			Authorization: headerOrNil(r, "Authorization"),
			Cookie:        headerOrNil(r, "Cookie"),
			APIKey:        headerOrNil(r, "X-API-Key"),
		},
	})
	if err != nil {
		return nil, err
	}
	log.Debug("the control plane authorized an untrusted tune", "channel", decision.ChannelUUID)
	return decision, nil
}

// headerOrNil is the header's value, or nil when the client sent none.
//
// nil rather than "": Django's serializer declares each of the three
// allow_null, and "this client sent no Authorization header" and "this
// client sent an empty one" are different facts to an authenticator union
// that rejects a malformed credential with a 401 and declines a missing one
// (parity-matrix row 30).
func headerOrNil(r *http.Request, name string) *string {
	value, present := r.Header[http.CanonicalHeaderKey(name)]
	if !present || len(value) == 0 {
		return nil
	}
	v := value[0]
	return &v
}

// decisionHeader maps one X-Relay-* name to the decision's own field, so
// identify() reads its five values through ONE closure whichever source
// answered. A name this map does not know returns "", which is what an
// absent header does.
func decisionHeader(decision *control.Decision, name string) string {
	switch name {
	case control.HeaderRelayChannel:
		return decision.ChannelUUID
	case control.HeaderRelayOutput:
		return decision.OutputProfileID
	case control.HeaderRelayClient:
		return decision.ClientID
	case control.HeaderRelayUser:
		return decision.UserID
	case control.HeaderRelayOutputFormat:
		return decision.OutputFormat
	case control.HeaderRelayClientIP:
		return decision.ClientIP
	}
	return ""
}

// writeAuthorizeFailure turns an authorize error into the viewer's answer.
//
// A DENIAL REACHES THE VIEWER AS ITSELF -- 401, 403, 404 or 429 -- because
// that is what the Python relay's inline path does: resolve_authorization
// lets AuthorizeDenied propagate and the stream view answers
// authorize_error_response, whose status is the exception's own. The 403
// collapse belongs to the nginx subrequest form and to nothing else.
//
// Everything else is 502: the control plane could not be reached, refused
// this relay's own credentials, or is misconfigured. Never the error's text,
// which can name a variable or a URL.
func writeAuthorizeFailure(w http.ResponseWriter, log *slog.Logger, err error) {
	var denied *control.Denied
	if errors.As(err, &denied) {
		if len(denied.Body) > 0 {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(denied.Status)
			_, _ = w.Write(denied.Body)
			return
		}
		http.Error(w, http.StatusText(denied.Status), denied.Status)
		return
	}
	log.Error("the tune could not be authorized", "error", redact.Error(err))
	http.Error(w, "the tune could not be authorized", http.StatusBadGateway)
}
```

### Appendix X — `apps/proxy/tests/test_relay_detail_payload_golden.py`

The sibling of `test_relay_list_payload_golden.py`, with `NEVER_WRITTEN` in place of `NOT_SERVED_YET` and three extra tests that assert row 14 across BOTH serializers -- a test that checked one endpoint would prove nothing about the other, which is the row's own Notes.

**`apps/proxy/tests/test_relay_detail_payload_golden.py`**

```python
"""The golden fixture for the Go relay's GET /proxy/relay/channels/<id>.

Phase 2 PR 2c-8, and the sibling of test_relay_list_payload_golden.py. This
file renders a payload through Django's own RelayChannelDetailSerializer and
pins the result to relay/httpapi/testdata/channel_detail.json, which a Go test
reads back. The Go encoder is compared against the OTHER implementation, not
against a Go struct literal the same PR also wrote.

WHAT THIS PINS AND WHAT IT DOES NOT, unchanged from the list golden's own
statement of it: it pins the SERIALIZER -- which keys survive, which render as
null, which vanish. It does not drive
ChannelStatus.get_detailed_channel_info, so the mapping from "the source dict
set this key inside an if" to "this key is optional" is 2c-8's reading of
apps/proxy/live_proxy/channel_status.py:25-413, and the completeness assertion
below is what stops that reading from silently narrowing.

Regenerate the golden with:

    DISPATCHARR_WRITE_GOLDEN=1 python manage.py test \\
        apps.proxy.tests.test_relay_detail_payload_golden
"""

import json
import os
from pathlib import Path

from django.test import SimpleTestCase
from rest_framework.renderers import JSONRenderer

from apps.proxy.relay_serializers import (
    RelayChannelDetailSerializer,
    RelayDetailClientSerializer,
)

GOLDEN = (
    Path(__file__).resolve().parents[3]
    / "relay"
    / "httpapi"
    / "testdata"
    / "channel_detail.json"
)

# Two RelayChannelDetailSerializer fields the Go relay never emits, because
# NEITHER RELAY CAN: each is read by channel_status.py and written by nothing
# in the tree. Kept as a mapping with a reason for the list golden's reason --
# a field in neither this mapping nor the fully-populated fixture fails
# test_the_fixture_covers_every_serializer_field, which is what stops the
# golden from narrowing as the endpoint grows.
NEVER_WRITTEN = {
    "source_bitrate": (
        "ChannelMetadataField.SOURCE_BITRATE has no writer anywhere in the "
        "tree: apps/proxy/live_proxy/channel_status.py:359 is its only "
        "reference beside the constant declaration itself, so the key is "
        "never in the metadata hash and the `if source_bitrate:` never fires"
    ),
    "ffmpeg_bitrate": (
        "channel_status.py:404 reads ChannelMetadataField.FFMPEG_BITRATE "
        "('ffmpeg_bitrate') and the only writer, input/manager.py:1269, "
        "writes FFMPEG_OUTPUT_BITRATE ('ffmpeg_output_bitrate'), which "
        "nothing reads -- two different strings at constants.py:90-91, so "
        "the operator's output bitrate never reaches this payload in either "
        "relay"
    ),
}


def fixture():
    """One channel with every conditional field set and two clients: a TS
    client carrying the three byte counters the TS generator writes, and an
    fMP4 client carrying none of them, which is the per-format asymmetry
    output/fmp4/generator.py:288-295 creates by writing only last_active."""
    return {
        "channel_id": "11111111-1111-4111-8111-111111111111",
        "state": "active",
        "url": "http://provider.invalid/live/sub/pw/41.ts",
        "stream_profile": "1",
        "started_at": 1789000000.5,
        # The literal string, not null: channel_status.py:45's default, and
        # parity-matrix row 14's asymmetry with the list endpoint.
        "owner": "unknown",
        "buffer_index": 120,
        "channel_name": "BBC One HD",
        "stream_id": 41,
        "stream_name": "BBC One HD (UK)",
        "m3u_profile_id": 3,
        "m3u_profile_name": "Premium",
        "state_changed_at": 1789000005.0,
        "state_duration": 25.5,
        "uptime": 30.0,
        "total_bytes": 9999888,
        "total_data": "9.54 MB",
        "avg_bitrate_kbps": 2665.3034666666666,
        "avg_bitrate": "2.67 Mbps",
        "client_count": 2,
        "buffer_stats": {
            "chunks": 120,
            "diagnostics": {
                "first_chunk": {
                    "index": 116,
                    "size": 255868,
                    "ts_packets": 1361,
                    "aligned": True,
                    "first_byte": 71,
                }
            },
            "avg_chunk_size": 255868.0,
            "recent_chunk_sizes": [255868, 255868, 255868, 255868, 255868],
            "keys_found": [116, 117, 118, 119, 120],
            "keys_missing": [],
            "total_sample_bytes": 1279340,
            "estimated_ts_packets": 6805,
            "is_ts_aligned": True,
        },
        "local_manager": {
            "healthy": True,
            "connected": True,
            "last_data_time": 1789000029.5,
            "last_data_age": 0.5,
        },
        # The stream-info fields, raw strings exactly as the hash stores them
        # (str(round(x, n)) at services/channel_service.py:844-880).
        "video_codec": "h264",
        "resolution": "1920x1080",
        "width": "1920",
        "height": "1080",
        "video_bitrate": "4500.0",
        # A STRING here and a float on the list endpoint: row 14.
        "source_fps": "25.0",
        "pixel_format": "yuv420p",
        "audio_codec": "aac",
        "sample_rate": "48000",
        "audio_channels": "stereo",
        "audio_bitrate": "128.0",
        # A FLOAT on both endpoints (Phase 1 PR 7 unified it); row 14 again.
        "ffmpeg_speed": 1.02,
        "ffmpeg_fps": "25.0",
        "actual_fps": "24.5",
        "stream_type": "mpegts",
        "clients": [
            {
                "client_id": "client_1789000000000_1234",
                "user_agent": "VLC/3.0.20",
                # 'unknown' with one relay process and no election -- the
                # same default channel_status.py:181 applies when the client
                # hash carries no worker_id.
                "worker_id": "unknown",
                "ip_address": "198.51.100.4",
                "user_id": "7",
                "output_format": "mpegts",
                "output_profile_id": 7,
                "connected_at": 1789000001.25,
                "last_active": 1789000029.5,
                "last_active_ago": 0.5,
                "bytes_sent": 9999888,
                "avg_rate_KBps": 341.2,
                "current_rate_KBps": 348.9,
            },
            {
                # An fMP4 client: the three byte counters are ABSENT, because
                # output/fmp4/generator.py writes only last_active.
                "client_id": "client_1789000000000_5678",
                "user_agent": "unknown",
                "worker_id": "unknown",
                "ip_address": "198.51.100.9",
                "user_id": "0",
                "output_format": "fmp4",
                "output_profile_id": None,
                "connected_at": 1789000010.0,
                "last_active": 1789000029.0,
                "last_active_ago": 1.0,
            },
        ],
    }


def rendered():
    return JSONRenderer().render(RelayChannelDetailSerializer(fixture()).data)


class RelayDetailPayloadGoldenTests(SimpleTestCase):
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
        self.assertEqual(
            json.loads(GOLDEN.read_bytes()),
            json.loads(payload),
            "relay/httpapi/testdata/channel_detail.json has drifted from what "
            "RelayChannelDetailSerializer renders; regenerate it with "
            "DISPATCHARR_WRITE_GOLDEN=1 and read the diff before committing",
        )

    def test_the_fixture_covers_every_serializer_field(self):
        declared = set(RelayChannelDetailSerializer().fields)
        populated = set(fixture())
        excused = set(NEVER_WRITTEN)

        missing = declared - populated - excused
        self.assertEqual(
            missing,
            set(),
            "these RelayChannelDetailSerializer fields are neither in the "
            f"fixture nor in NEVER_WRITTEN with a reason: {sorted(missing)}",
        )
        stale = excused - declared
        self.assertEqual(
            stale,
            set(),
            f"NEVER_WRITTEN names fields the serializer does not declare: {sorted(stale)}",
        )

    def test_the_client_fixture_covers_every_detail_client_field(self):
        """The same completeness check one level down.

        The TS client carries every field; the fMP4 one is where the
        conditional half is exercised, so the union is what has to be
        complete and the TS row alone is what has to cover it.
        """
        declared = set(RelayDetailClientSerializer().fields)
        populated = set(fixture()["clients"][0])
        self.assertEqual(
            declared - populated,
            set(),
            "these RelayDetailClientSerializer fields are not in the fully "
            f"populated client row: {sorted(declared - populated)}",
        )

    def test_the_fmp4_client_row_omits_the_three_byte_counters(self):
        """The per-format asymmetry, asserted on the RENDERED payload.

        A test that only checked the TS row would pass with an fMP4 row that
        carried counters too -- which is the shape a Go relay gets by
        recording bytes for every client and letting the renderer decide.
        """
        client = json.loads(rendered())["clients"][1]
        for key in ("bytes_sent", "avg_rate_KBps", "current_rate_KBps"):
            self.assertNotIn(
                key,
                client,
                f"{key} rendered for an fMP4 client, whose generator never writes it",
            )
        # And the fields it DOES carry, so "everything vanished" cannot be
        # what makes this pass.
        for key in ("client_id", "worker_id", "connected_at", "last_active"):
            self.assertIn(key, client, f"{key} is missing from the fMP4 client row")

    def test_owner_is_the_string_unknown_here_and_null_on_the_list(self):
        """Parity-matrix row 14's first clause, across BOTH serializers.

        Asserted here as well as on the list golden because a test that
        checks the string against only one of the two endpoints proves
        nothing about the other -- the row's own Notes say so.
        """
        from apps.proxy.tests.test_relay_list_payload_golden import (
            fixture as list_fixture,
            rendered as list_rendered,
        )

        self.assertEqual(json.loads(rendered())["owner"], "unknown")
        self.assertIsNone(json.loads(list_rendered())["channels"][0]["owner"])
        self.assertIsNone(list_fixture()["channels"][0]["owner"])

    def test_source_fps_is_a_string_here_and_a_float_on_the_list(self):
        """Row 14's third clause, the one Phase 1 PR 7 did NOT unify."""
        from apps.proxy.tests.test_relay_list_payload_golden import (
            rendered as list_rendered,
        )

        self.assertIsInstance(json.loads(rendered())["source_fps"], str)
        self.assertIsInstance(
            json.loads(list_rendered())["channels"][0]["source_fps"], float
        )

    def test_ffmpeg_speed_is_a_float_on_both_endpoints(self):
        """Row 14's second clause, which PR 7 DID unify. Held unified."""
        from apps.proxy.tests.test_relay_list_payload_golden import (
            rendered as list_rendered,
        )

        self.assertIsInstance(json.loads(rendered())["ffmpeg_speed"], float)
        self.assertIsInstance(
            json.loads(list_rendered())["channels"][0]["ffmpeg_speed"], float
        )
```

### Appendix Y — the Python and Docker edits

One diff across nine files: the authorize-internal view and its two serializers (including Ruling R13's `to_internal_value`, without which the `x-api-key` field is dead), the route, the three advance serializer fields, `relay_client.advance`'s three parameters, `next_source.channel_stream_profile_ref`, `change_stream`'s and `next_stream`'s forwarding (and `change_stream`'s bare-url branch), the zero-ORM allowlist entry, the one existing test whose expected payload grew, the `HEALTHCHECK`, and the role file `entrypoint.sh` writes.

**Five of these files are inside Gate 2's module list** — `authorize_views.py`, `next_source.py`, `relay_client.py`, `relay_serializers.py` and `live_proxy/views.py` — so Constraint 54 applies to every statement in this diff. Measured on this tree: zero added-and-missing lines in all three files that gained any, and `missing` 1497-1498 against the floor's 1525.

```diff
diff --git a/apps/proxy/authorize_views.py b/apps/proxy/authorize_views.py
index adab2ec6..c1199d32 100644
--- a/apps/proxy/authorize_views.py
+++ b/apps/proxy/authorize_views.py
@@ -18,7 +18,10 @@
 """
 
 import logging
-from django.http import JsonResponse
+from importlib import import_module
+
+from django.conf import settings as django_settings
+from django.http import HttpRequest, JsonResponse, parse_cookie
 from django.urls import Resolver404, resolve
 from drf_spectacular.utils import OpenApiResponse, extend_schema
 from rest_framework import serializers
@@ -41,6 +44,7 @@ from apps.proxy.authorize import (
 )
 from apps.proxy.internal_auth import (
     HEADER_AUTHORIZE_STATUS,
+    META_INTERNAL,
     HEADER_RELAY_CHANNEL,
     HEADER_RELAY_CLIENT,
     HEADER_RELAY_CLIENT_IP,
@@ -56,9 +60,11 @@ from apps.proxy.internal_auth import (
     META_RELAY_OUTPUT,
     META_RELAY_OUTPUT_FORMAT,
     META_RELAY_USER,
+    internal_principal_token,
     request_is_internal,
     request_is_relay_trusted,
 )
+from apps.proxy.permissions import IsInternalRelay
 
 logger = logging.getLogger(__name__)
 
@@ -355,6 +361,248 @@ def authorize_view(request):
     return response
 
 
+# --- The Go relay's dev fallback (spec D5, exception 2) -----------------
+#
+# POST /_dispatcharr/authorize-internal. ITS OWN PATH, not the nginx-facing
+# `= /_dispatcharr/authorize` above, and the distinct path is the whole
+# point: that location is declared `internal;` in docker/nginx.conf:120, an
+# EXACT-match location that wins over every prefix and regex one, so a POST
+# to it is 404'd by nginx before Django sees it in every nginx-fronted
+# deployment. Harmless for the fallback's intended use (a shape with no
+# nginx has no nginx to 404 it) and NOT harmless for the failure mode Phase
+# 1 deliberately made safe: when nginx's rendered RELAY_TRUST_TOKEN and a
+# relay's own derived token disagree, request_is_relay_trusted() returns
+# False and the Python relay falls through to an inline authorize_stream
+# call, warning once per process (_TRUST_MISMATCH_WARNED above). Reusing
+# the shielded path here would turn that degraded-but-working mode into
+# every live tune failing outright post-cutover.
+#
+# THE VIEW BUILDS THE REQUEST IT AUTHORIZES ENTIRELY FROM THE BODY AND
+# INHERITS NOTHING FROM THE TRANSPORT REQUEST. Every field below is
+# load-bearing and each has its own failure signature, all of them silent:
+#
+#   uri        the full path and query string, X-Original-URI's equivalent.
+#              _surface_for resolves the surface from it, and
+#              authorize_view:299 reads session_id off its query for the
+#              catch-up surface.
+#   client_ip  REMOTE_ADDR. authorize.py:425 evaluates the STREAMS ACL
+#              against the request's own address, so a view that passed its
+#              own transport request through would judge the RELAY's address
+#              -- wrong in exactly the nginx-less deployments this exists
+#              for, where there is no auth_request subrequest inheriting the
+#              client's.
+#   internal   whether the CLIENT's request was internal. Never the
+#              transport's own X-Dispatcharr-Internal header, which
+#              IsInternalRelay requires the relay to send and which
+#              therefore says only "this caller is part of the deployment".
+#              authorize_stream:417-419 reads request_is_internal off the
+#              request it is handed, and _resolve_principal:309-310 returns
+#              INTERNAL_PRINCIPAL before any channel flag, adult filter,
+#              profile membership or XC credential is looked at -- so
+#              passing the transport request through would authorize every
+#              tune in every nginx-less deployment, unconditionally.
+#   headers    the three credential-bearing headers the authenticator union
+#              can consume: authorization, cookie and x-api-key.
+#              ApiKeyAuthentication (apps/accounts/authentication.py:46-85)
+#              checks X-API-Key BEFORE falling back to an
+#              `Authorization: ApiKey ...` header, so omitting the third
+#              would resolve such a client to anonymous here and to its real
+#              user in production -- the cross-shape divergence D5 exists to
+#              prevent.
+#
+# They travel in the BODY rather than as headers because the bound token
+# (internal_auth.internal_request_token) signs exactly five fields -- the
+# context, the method, the full path, the timestamp and sha256(BODY) -- and
+# headers are not among them. A captured X-Dispatcharr-Internal-Request for
+# this path would otherwise stay valid for 120 seconds against ANY
+# combination of forwarded headers.
+
+
+class AuthorizeInternalHeadersSerializer(serializers.Serializer):
+    """The three credential-bearing headers, each null when the client sent
+    none. A `headers` sub-object rather than three flat fields so a fourth
+    credential header discovered later is a field, not a body-shape
+    redesign."""
+
+    authorization = serializers.CharField(
+        required=False, allow_null=True, allow_blank=True, default=None
+    )
+    cookie = serializers.CharField(
+        required=False, allow_null=True, allow_blank=True, default=None
+    )
+    # The wire name is the lowercased header, hyphen and all, which is not a
+    # Python identifier. `source=` alone is NOT enough and getting that wrong
+    # is silent: DRF reads INPUT by a field's NAME (`x_api_key`) and uses
+    # `source` only for where the value lands in validated_data, so a body
+    # carrying `"x-api-key"` would deserialize to None and an API-key client
+    # would resolve to ANONYMOUS here and to its real user in production --
+    # the exact cross-shape divergence D5 exists to prevent, and the one
+    # § The contract added this third field to close. Found by a coverage
+    # test, not by review. to_internal_value below is what makes the wire
+    # name the wire name.
+    x_api_key = serializers.CharField(
+        source="x-api-key",
+        required=False,
+        allow_null=True,
+        allow_blank=True,
+        default=None,
+    )
+
+    def to_internal_value(self, data):
+        if isinstance(data, dict) and "x-api-key" in data:
+            data = {**data, "x_api_key": data["x-api-key"]}
+        return super().to_internal_value(data)
+
+
+class AuthorizeInternalRequestSerializer(serializers.Serializer):
+    """The question this route answers, in full, so sha256(body) binds it."""
+
+    uri = serializers.CharField()
+    client_ip = serializers.CharField(allow_blank=True)
+    internal = serializers.BooleanField()
+    headers = AuthorizeInternalHeadersSerializer(required=False)
+
+
+def _synthetic_request(data) -> HttpRequest:
+    """The request authorize_stream is handed, built from the body alone.
+
+    Nothing here reads the incoming POST. The session is loaded the way
+    django.contrib.sessions.middleware.SessionMiddleware.process_request
+    loads it, from the body's cookie, because _session_user
+    (authorize.py:268-287) calls django.contrib.auth.get_user(request) --
+    which reads the SESSION, not request.user -- and a view that forwarded
+    the cookie but resolved the principal from request.user would downgrade
+    a session viewer to anonymous with NO ERROR: a hidden channel would
+    still 403, so the visible half of authorization would look correct,
+    while an ordinary channel streamed a 200 with real bytes and
+    user_level, Channel Profile membership, adult filtering and the
+    per-user stream limit had all quietly stopped applying.
+    """
+    split = urlsplit(data["uri"])
+    # authorize_view's own two decode steps, for its own reasons: a
+    # percent-encoded XC credential segment, and a raw-UTF-8 one that
+    # arrived latin-1 decoded.
+    path = split.path
+    try:
+        path = path.encode("latin-1").decode("utf-8")
+    except UnicodeError:
+        pass
+    path = unquote(path)
+
+    headers = data.get("headers") or {}
+    cookie = headers.get("cookie") or ""
+
+    request = HttpRequest()
+    request.method = "GET"
+    request.path = path
+    request.path_info = path
+    request.META = {
+        "REQUEST_METHOD": "GET",
+        "PATH_INFO": path,
+        "QUERY_STRING": split.query,
+        # get_client_ip reads REMOTE_ADDR and honours X-Real-IP /
+        # X-Forwarded-For only when REMOTE_ADDR is a trusted proxy. Neither
+        # forwarded header is set here -- the body carries no such field --
+        # so the address the relay observed is the address judged.
+        "REMOTE_ADDR": data["client_ip"],
+    }
+    if headers.get("authorization"):
+        request.META["HTTP_AUTHORIZATION"] = headers["authorization"]
+    if cookie:
+        request.META["HTTP_COOKIE"] = cookie
+    if headers.get("x-api-key"):
+        request.META["HTTP_X_API_KEY"] = headers["x-api-key"]
+    if data["internal"]:
+        # From the BODY's flag, minted here -- never copied from the
+        # transport request's own header. Absent entirely when the body
+        # says false, so request_is_internal answers False.
+        request.META[META_INTERNAL] = internal_principal_token()
+
+    request.GET = _query_dict(split.query)
+    request.COOKIES = parse_cookie(cookie)
+    engine = import_module(django_settings.SESSION_ENGINE)
+    request.session = engine.SessionStore(
+        request.COOKIES.get(django_settings.SESSION_COOKIE_NAME)
+    )
+    return request
+
+
+@extend_schema(
+    operation_id="internal_authorize_stream_post",
+    description=(
+        "Internal. The Go relay's fallback when no nginx auth_request "
+        "authorized the tune: the same authorize_stream() decision, reached "
+        "over HTTP because a Go process cannot import Python. Registered in "
+        "every deployment shape and never called in one that runs nginx. "
+        "Not part of the client API."
+    ),
+    request=AuthorizeInternalRequestSerializer,
+    responses={
+        200: OpenApiResponse(
+            description=(
+                "Authorized; the decision is in the seven X-Relay-* headers, "
+                "the same set a relay-bound nginx location carries."
+            )
+        ),
+        401: AuthorizeDenialSerializer,
+        403: AuthorizeDenialSerializer,
+        404: AuthorizeDenialSerializer,
+        429: AuthorizeDenialSerializer,
+    },
+    tags=["internal"],
+)
+@api_view(["POST"])
+@authentication_classes([])
+@permission_classes([IsInternalRelay])
+def authorize_internal_view(request):
+    payload = AuthorizeInternalRequestSerializer(data=request.data)
+    payload.is_valid(raise_exception=True)
+    data = payload.validated_data
+
+    http_request = _synthetic_request(data)
+
+    try:
+        match = resolve(http_request.path)
+    except Resolver404:
+        return authorize_error_response(AuthorizeDenied(404, "Not found"))
+
+    surface, identity = _surface_for(match)
+    if surface is None:
+        return authorize_error_response(AuthorizeDenied(403, "Forbidden"))
+    if surface == SURFACE_CATCHUP_XC and not identity:
+        identity = {
+            "identifier": (http_request.GET.get("stream") or "").removesuffix(".ts"),
+            "username": http_request.GET.get("username"),
+            "password": http_request.GET.get("password"),
+        }
+    if surface == SURFACE_CATCHUP:
+        identity["session_id"] = http_request.GET.get("session_id")
+
+    try:
+        result = authorize_stream(http_request, surface, **identity)
+    except AuthorizeDenied as exc:
+        # THE TRUE STATUS, never subrequest_error_response's 403 collapse.
+        # That shape exists only because ngx_http_auth_request_module can
+        # transport a 2xx, a 401 or a 403 and nothing else; a direct POST
+        # has no such constraint, and collapsing here would hand the Go
+        # relay a 403 where production answers 404 for an unknown channel
+        # or 429 for a user over their stream limit.
+        return authorize_error_response(exc)
+
+    response = Response(status=200)
+    response[HEADER_RELAY_CHANNEL] = result.channel_uuid
+    response[HEADER_RELAY_OUTPUT] = result.output_profile_id
+    response[HEADER_RELAY_CLIENT] = result.client_id
+    response[HEADER_RELAY_USER] = result.user_id
+    response[HEADER_RELAY_NAME] = result.relay_name
+    response[HEADER_RELAY_OUTPUT_FORMAT] = result.output_format
+    # In the nginx-less shape this response is the ONLY source of
+    # ip_address -- there is no hop-set header to read -- which is what
+    # closes parity-matrix row 17's stated gap for the Go relay.
+    response[HEADER_RELAY_CLIENT_IP] = result.client_ip
+    return response
+
+
 def _query_dict(query: str):
     from django.http import QueryDict
 
diff --git a/apps/proxy/live_proxy/tests/zero_orm_allowlist.py b/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
index fe2b9da8..cde6c037 100644
--- a/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
+++ b/apps/proxy/live_proxy/tests/zero_orm_allowlist.py
@@ -277,6 +277,47 @@ SITES = (
 )
 
 EDGES = (
+    EdgeEntry(
+        importer="apps/proxy/live_proxy/views.py",
+        module="apps.proxy.next_source",
+        name="channel_stream_profile_ref",
+        hits=7,
+        pr="2c-8",
+        reason=(
+            "Phase 2 PR 2c-8. change_stream can be called with a bare url and "
+            "no stream_id -- reachable only by a hand-crafted admin call, "
+            "never by the UI, whose switchStream always sends stream_id "
+            "(frontend/src/api.js:3314-3322) -- and that path resolves no "
+            "Stream row, so there is no source dict to take a stream_profile "
+            "out of. The Go relay builds no command line (Amendment A4.1), so "
+            "without one it has nothing to spawn. This helper asks the "
+            "CHANNEL for its own effective profile and builds the argv "
+            "against the supplied url, which is the same profile the Python "
+            "relay uses on that path: StreamManager keeps its own across "
+            "update_url (input/manager.py:1462-1540) and rebuilds the command "
+            "from it. "
+            "SEVEN FLAGGED SITES in the reachable subtree, measured rather "
+            "than asserted: Channel.get_stream_profile's "
+            "effective_stream_profile_obj and its CoreSettings default "
+            "lookup, is_proxy() and is_redirect() (which compare self.locked "
+            "and self.name on a loaded instance, core/models.py:127-135 -- "
+            "flagged CALL SITES, not queries), _stream_profile_ref's "
+            "build_command (pure, core/models.py:137-160), and "
+            "_LockedFfmpegProfile.ref reaching _locked_ffmpeg_profile's "
+            "StreamProfile.objects.filter, which IS a query. "
+            "IN THE API PROCESS EITHER WAY: PR 4's routing put change_stream "
+            "on the api role, so this import is not executed in the relay "
+            "process at all -- the same structural reason the six inline "
+            "authorize edges carry."
+        ),
+        closed_by=(
+            "POST /proxy/relay/channels/<id>/advance carrying stream_profile, "
+            "ffmpeg_stream_profile and transcode -- the three fields 2c-8 "
+            "adds to RelayAdvanceRequestSerializer. Django resolves the "
+            "profile in the API process, where the ORM is, and the relay "
+            "spawns the argv it is handed."
+        ),
+    ),
     EdgeEntry(
         importer="apps/proxy/live_proxy/views.py",
         module="apps.proxy.next_source",
diff --git a/apps/proxy/live_proxy/views.py b/apps/proxy/live_proxy/views.py
index 30054e5a..0fe22095 100644
--- a/apps/proxy/live_proxy/views.py
+++ b/apps/proxy/live_proxy/views.py
@@ -912,6 +912,9 @@ def change_stream(request, channel_id):
         stream_name = None
         channel_name = None
         m3u_profile_name = None
+        transcode = False
+        stream_profile = None
+        ffmpeg_stream_profile = None
 
         # Coerce at the boundary: the Stats card's Select yields a string id
         # and, in the split deployment, this travels to the relay as JSON
@@ -958,11 +961,41 @@ def change_stream(request, channel_id):
             stream_name = stream_info.get("stream_name")
             channel_name = stream_info.get("channel_name")
             m3u_profile_name = stream_info.get("m3u_profile_name")
+            # Phase 2 PR 2c-8: the Go relay builds no command line, so the
+            # profile Django resolved travels with the source.
+            transcode = stream_info.get("transcode", False)
+            stream_profile = stream_info.get("stream_profile")
+            ffmpeg_stream_profile = stream_info.get("ffmpeg_stream_profile")
         elif not new_url:
             return JsonResponse(
                 {"error": "Either url or stream_id must be provided"}, status=400
             )
 
+        if not stream_id:
+            # A bare url with no stream_id: nothing resolved a Stream row, so
+            # the profile is the CHANNEL's own -- which is what the Python
+            # relay uses on this path too, since StreamManager keeps its own
+            # across update_url. Built here because the Go relay builds no
+            # command line (Phase 2 PR 2c-8, Amendment A4.1).
+            from apps.proxy.next_source import channel_stream_profile_ref
+
+            try:
+                channel = get_stream_object(channel_id)
+            except Http404:
+                # Best-effort enrichment of a call that did no DB lookup at
+                # all before 2c-8. An identifier that names no row leaves the
+                # three fields unset, exactly as they were, and the Go relay
+                # answers 400 because it genuinely cannot spawn without an
+                # argv -- honest, and not a new 404 on a path that never had
+                # one.
+                channel = None
+            if channel is not None:
+                transcode, stream_profile, ffmpeg_stream_profile = (
+                    channel_stream_profile_ref(
+                        channel, url=new_url, user_agent=user_agent
+                    )
+                )
+
         logger.info(
             f"Attempting to change stream for channel {channel_id} to {redact_url(new_url)}"
         )
@@ -983,6 +1016,9 @@ def change_stream(request, channel_id):
             channel_name=channel_name,
             m3u_profile_name=m3u_profile_name,
             reset_tried=True,
+            transcode=transcode,
+            stream_profile=stream_profile,
+            ffmpeg_stream_profile=ffmpeg_stream_profile,
         )
 
         if result.get("status") == "error":
@@ -1317,6 +1353,11 @@ def next_stream(request, channel_id):
             stream_name=stream_info.get("stream_name"),
             channel_name=stream_info.get("channel_name"),
             m3u_profile_name=stream_info.get("m3u_profile_name"),
+            # Phase 2 PR 2c-8: the Go relay builds no command line, so the
+            # profile Django resolved travels with the source.
+            transcode=stream_info.get("transcode", False),
+            stream_profile=stream_info.get("stream_profile"),
+            ffmpeg_stream_profile=stream_info.get("ffmpeg_stream_profile"),
         )
 
         if result.get("status") == "error":
diff --git a/apps/proxy/next_source.py b/apps/proxy/next_source.py
index f35b5c43..0cf12f12 100644
--- a/apps/proxy/next_source.py
+++ b/apps/proxy/next_source.py
@@ -155,6 +155,31 @@ def _stream_profile_ref(profile, *, url, user_agent, pk):
     }
 
 
+def channel_stream_profile_ref(channel, *, url, user_agent):
+    """The CHANNEL's own effective stream profile, built for `url`.
+
+    Phase 2 PR 2c-8. /proxy/ts/change_stream/ can be called with a bare url
+    and no stream_id -- reachable only by a hand-crafted admin call, never by
+    the UI, which always sends stream_id -- and that path resolves no Stream
+    row, so there is no source dict to take a stream_profile out of. The Go
+    relay builds no command line (Amendment A4.1), so without one it has
+    nothing to spawn.
+
+    The profile is the channel's, which is also what the Python relay uses
+    on that path: StreamManager keeps its own stream_profile and transcode
+    flag across update_url (input/manager.py:1462-1540) and rebuilds the
+    command from them. Same profile, built here instead of there.
+
+    Returns (transcode, stream_profile_ref, ffmpeg_stream_profile_ref), the
+    three fields relay_client.advance carries.
+    """
+    profile = channel.get_stream_profile()
+    transcode = not (profile.is_proxy() or profile.is_redirect())
+    ref = _stream_profile_ref(profile, url=url, user_agent=user_agent, pk=channel.id)
+    locked = _LockedFfmpegProfile().ref(url=url, user_agent=user_agent, pk=channel.id)
+    return transcode, ref, locked
+
+
 def _locked_ffmpeg_profile():
     """The locked 'ffmpeg' StreamProfile ROW, or None.
 
diff --git a/apps/proxy/relay_client.py b/apps/proxy/relay_client.py
index 5257fe80..44b5805c 100644
--- a/apps/proxy/relay_client.py
+++ b/apps/proxy/relay_client.py
@@ -457,6 +457,9 @@ def advance(
     channel_name=None,
     m3u_profile_name=None,
     reset_tried=False,
+    transcode=False,
+    stream_profile=None,
+    ffmpeg_stream_profile=None,
 ):
     """Switch a running channel to an already-resolved source.
 
@@ -480,5 +483,12 @@ def advance(
             "channel_name": channel_name,
             "m3u_profile_name": m3u_profile_name,
             "reset_tried": reset_tried,
+            # Phase 2 PR 2c-8: the Go relay spawns the argv Django built and
+            # splits no words of its own (Amendment A4.1), so the profile
+            # travels with the source rather than being looked up again on
+            # the relay. The Python relay's handler ignores all three.
+            "transcode": transcode,
+            "stream_profile": stream_profile,
+            "ffmpeg_stream_profile": ffmpeg_stream_profile,
         },
     )
diff --git a/apps/proxy/relay_serializers.py b/apps/proxy/relay_serializers.py
index f2c2bbed..b234b05c 100644
--- a/apps/proxy/relay_serializers.py
+++ b/apps/proxy/relay_serializers.py
@@ -18,6 +18,8 @@ this PR must leave alone.
 
 from rest_framework import serializers
 
+from apps.proxy.serializers import StreamProfileRefSerializer
+
 
 class RelayChannelClientSerializer(serializers.Serializer):
     """One row of get_basic_channel_info's `clients` list."""
@@ -211,6 +213,24 @@ class RelayAdvanceRequestSerializer(serializers.Serializer):
     m3u_profile_name = serializers.CharField(
         required=False, allow_blank=True, allow_null=True, default=None
     )
+    # Phase 2 PR 2c-8. THE GO RELAY BUILDS NO COMMAND LINE (Amendment A4.1:
+    # Django sends the argv it built for this source's own URL, user agent
+    # and object), so an advance carrying only a url has nothing the relay
+    # can spawn. These three carry the rest of what the tune path's own
+    # answer carries, in the same shapes: they are the fields of
+    # apps/proxy/serializers.py's SourceSerializer that the flat fields
+    # above do not already duplicate.
+    #
+    # required=False because the PYTHON relay's own handler ignores them and
+    # both relays run through the whole of stage 2c (spec D3); the Go relay
+    # refuses an advance with no stream_profile with a 400, which is what
+    # DRF answers here for a missing required field anyway. Every producer
+    # sends all three.
+    transcode = serializers.BooleanField(required=False, default=False)
+    stream_profile = StreamProfileRefSerializer(required=False, allow_null=True, default=None)
+    ffmpeg_stream_profile = StreamProfileRefSerializer(
+        required=False, allow_null=True, default=None
+    )
     # /proxy/ts/change_stream/ has always cleared the running manager's
     # tried_stream_ids so an operator's manual switch does not inherit a
     # failover's exclusion list. That reset used to run in the same
diff --git a/apps/proxy/tests/test_relay_client.py b/apps/proxy/tests/test_relay_client.py
index 6c7cff22..490a7774 100644
--- a/apps/proxy/tests/test_relay_client.py
+++ b/apps/proxy/tests/test_relay_client.py
@@ -456,6 +456,13 @@ class RelayClientCallTests(SimpleTestCase):
                 "channel_name": None,
                 "m3u_profile_name": None,
                 "reset_tried": True,
+                # Phase 2 PR 2c-8: three fields the Go relay needs because it
+                # builds no command line (Amendment A4.1). Defaulted here
+                # because this test calls advance() without them, which is
+                # the shape a caller that has not resolved a profile sends.
+                "transcode": False,
+                "stream_profile": None,
+                "ffmpeg_stream_profile": None,
             },
         )
         self.assertEqual(
diff --git a/dispatcharr/urls.py b/dispatcharr/urls.py
index 10a6ad18..b9c42e41 100644
--- a/dispatcharr/urls.py
+++ b/dispatcharr/urls.py
@@ -5,7 +5,7 @@ from django.conf.urls.static import static
 from django.views.generic import TemplateView, RedirectView
 from .routing import websocket_urlpatterns
 from apps.output.views import xc_player_api, xc_panel_api, xc_get, xc_xmltv
-from apps.proxy.authorize_views import authorize_view
+from apps.proxy.authorize_views import authorize_internal_view, authorize_view
 from apps.proxy.live_proxy.views import stream_xc
 from apps.proxy.vod_proxy.views import stream_xc_movie, stream_xc_episode
 from apps.timeshift.views import timeshift_proxy, timeshift_proxy_query
@@ -34,6 +34,21 @@ urlpatterns = [
     # the container in every shape that runs nginx; in dev, where nothing
     # runs nginx, the stream views authorize inline and never call it.
     path("_dispatcharr/authorize", authorize_view, name="authorize"),
+    # Internal: the Go relay's dev fallback (Phase 2 spec D5, exception 2).
+    # ITS OWN PATH, deliberately not the one above: `= /_dispatcharr/authorize`
+    # is an `internal;` exact-match location in docker/nginx.conf, so a POST
+    # to it is 404'd by nginx before Django sees it in every nginx-fronted
+    # shape -- which would turn a SECRET_KEY mismatch between roles from
+    # today's silent-but-working degrade into every live tune failing.
+    # Registered unconditionally, because Django cannot know at boot whether
+    # the relay it will talk to has nginx in front of it; gated by
+    # IsInternalRelay, which is the only protection it has since it sits
+    # outside nginx's shield by design.
+    path(
+        "_dispatcharr/authorize-internal",
+        authorize_internal_view,
+        name="authorize-internal",
+    ),
     # xc
     re_path("player_api.php", xc_player_api, name="xc_player_api"),
     re_path("panel_api.php", xc_panel_api, name="xc_panel_api"),
diff --git a/docker/Dockerfile b/docker/Dockerfile
index 8173d6d1..6f2a3465 100644
--- a/docker/Dockerfile
+++ b/docker/Dockerfile
@@ -88,6 +88,30 @@ RUN if [ -n "$TIMESTAMP" ]; then \
     cat /app/version.py; \
     fi
 
+# The container health probe (spec D6). Role-aware, because this image runs
+# four different program sets and only three of the rungs start relay-go;
+# docker/healthcheck.sh exits 0 for the roles that do not have one.
+#
+# interval/timeout/retries are sized against relay-go's own supervisord
+# settings: startsecs=5 and startretries=20, so start-period=30s covers a
+# cold start plus a couple of restarts, and 3 retries at 15s means a genuinely
+# dead relay is reported unhealthy inside a minute.
+# Exec form, not shell form: hadolint's DL3025 warns on the latter, and the
+# repo's Dockerfiles are at zero hadolint findings.
+#
+# AND IT NAMES THE INTERPRETER RATHER THAN RELYING ON THE SCRIPT'S MODE BIT.
+# Exec form does not go through a shell, so `CMD ["/app/docker/healthcheck.sh"]`
+# needs the file to be executable: at 0644 every probe fails with
+# `permission denied` and the container reports `unhealthy` for ever, with
+# nothing in the build or the test suite saying so -- hadolint is clean either
+# way and no Go or Python test reads this file. The script IS committed 0755
+# (`git ls-files -s docker/healthcheck.sh`), and this form means a mode bit
+# lost to a patch that does not carry modes, an editor, or a file written by
+# hand cannot silently disable the probe. Belt and braces, deliberately: the
+# mode is the intent and the interpreter is the guarantee.
+HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
+    CMD ["/bin/sh", "/app/docker/healthcheck.sh"]
+
 # No static `USER` here: the container starts as root by design so
 # entrypoint.sh can create a user at the PUID/PGID the operator supplies (NAS
 # self-hosting convention, same as linuxserver.io images) and chown bind
diff --git a/docker/entrypoint.sh b/docker/entrypoint.sh
index 81269dbc..4bf5d8b6 100755
--- a/docker/entrypoint.sh
+++ b/docker/entrypoint.sh
@@ -493,5 +493,12 @@ else
     SUPERVISORD_CONF="/app/docker/supervisord/${DISPATCHARR_ROLE}.conf"
 fi
 
+# The resolved role, for docker/healthcheck.sh. HEALTHCHECK runs as a fresh
+# process with the CONTAINER's environment, which carries DISPATCHARR_ROLE
+# only when the operator set it explicitly -- the default this script applied
+# above is invisible to it otherwise. /run is tmpfs-or-container-writable and
+# already holds supervisord's own socket and pidfile.
+printf '%s' "$DISPATCHARR_ROLE" > /run/dispatcharr-role || true
+
 echo "🚀 Starting supervisord ($DISPATCHARR_ROLE) with $SUPERVISORD_CONF"
 exec supervisord -n -c "$SUPERVISORD_CONF"
```

### Appendix Z — `apps/proxy/tests/test_authorize_internal_view.py`

Seventeen tests. The module docstring names the three silent failure modes; four of the tests assert an identity or a status vocabulary rather than "it worked", because a status-only assertion cannot see any of the three.

**The last five exist for Gate 2 and one of them found Ruling R13.** They are the arms a live-surface test does not reach — the latin-1 decode, both credential-header slots, `Resolver404`, the `surface is None` refusal, and the two catch-up identities — and § Break-check's own last section maps each to the statement it closed. The credential test asserts a **401 for a rejected credential** rather than a 200 for a valid one, because a rejected credential must be refused where a merely declined one falls through to anonymous (parity-matrix row 30), which makes the 401 positive evidence the header arrived; the anonymous 200 in the same test is what stops "this view 401s everything" being the reason.

```python
"""POST /_dispatcharr/authorize-internal -- the Go relay's dev fallback.

Phase 2 PR 2c-8, spec D5 exception 2. Every assertion here is on the view's
own wire: a status code or an X-Relay-* response header. That is deliberate
and it is what makes these tests port: the Go relay consumes this route's
answer verbatim, so an assertion about one Python function calling another
would say nothing about the shape it consumes.

THE THREE FAILURE MODES THIS FILE EXISTS FOR ARE ALL SILENT, and each one
returns a 200 with real bytes rather than an error:

  1. Reusing the transport's own X-Dispatcharr-Internal to answer "is this an
     internal principal". IsInternalRelay REQUIRES the relay to send that
     header, so a view that passed its incoming request through would make
     _resolve_principal return INTERNAL_PRINCIPAL for every tune in every
     nginx-less deployment, before any channel flag, adult filter, profile
     membership or credential check ran.
  2. Resolving the session principal from request.user. @api_view's dispatch
     sets it to AnonymousUser before authorize_stream is called, so a view
     that forwarded the cookie and read request.user would downgrade a
     session viewer to anonymous -- a hidden channel would still 403, and an
     ordinary one would stream with user_level, profile membership, adult
     filtering and the stream limit quietly not applying.
  3. Evaluating the network ACL against the relay's own address instead of
     the client's.

A STATUS-ONLY ASSERTION CANNOT SEE ANY OF THE THREE. X-Relay-User is what
says which principal the decision was made for, and it is what these tests
assert.
"""

import json

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)

PATH = "/_dispatcharr/authorize-internal"


class AuthorizeInternalViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.plain = Channel.objects.create(name="ai-plain", channel_number=9801)
        self.hidden = Channel.objects.create(
            name="ai-hidden", channel_number=9802, hidden_from_output=True
        )

    def post(self, body, *, internal_headers=True):
        """One call, signed the way the Go relay signs it."""
        raw = json.dumps(body).encode()
        headers = {}
        if internal_headers:
            headers["HTTP_X_DISPATCHARR_INTERNAL"] = internal_principal_token()
            headers["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = (
                build_internal_request_header("POST", PATH, raw)
            )
        return self.client.post(
            PATH, data=raw, content_type="application/json", **headers
        )

    def question(self, uri, **overrides):
        body = {
            "uri": uri,
            "client_ip": "198.51.100.4",
            "internal": False,
            "headers": {"authorization": None, "cookie": None, "x-api-key": None},
        }
        body.update(overrides)
        return body

    # -- registration and gating ----------------------------------------

    def test_the_route_is_registered_in_every_shape(self):
        """Unconditional registration, not dev-gated.

        Django cannot know at boot whether the relay it will talk to has
        nginx in front of it, so the route exists everywhere and is simply
        never called where nginx is.
        """
        self.assertEqual(reverse("authorize-internal"), PATH)

    def test_without_the_two_internal_headers_it_is_403(self):
        """Gating is the ONLY protection this route has.

        The nginx-facing view is AllowAny and is reachable only through an
        `internal;` location; this one sits outside that shield by design,
        so a missing permission class would be an authorization oracle --
        anyone reaching Django could enumerate which channel UUIDs exist and
        which are hidden by probing it.
        """
        response = self.post(
            self.question(f"/proxy/ts/stream/{self.plain.uuid}"),
            internal_headers=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_the_bound_token_must_cover_the_body(self):
        """A token signed over a DIFFERENT body is refused.

        This is what makes putting the question in the body worth anything:
        sha256(body) is inside what the token signs, so a captured token
        cannot be replayed against another question.
        """
        real = self.question(f"/proxy/ts/stream/{self.plain.uuid}")
        other = json.dumps(self.question("/proxy/ts/stream/something-else")).encode()
        response = self.client.post(
            PATH,
            data=json.dumps(real).encode(),
            content_type="application/json",
            HTTP_X_DISPATCHARR_INTERNAL=internal_principal_token(),
            HTTP_X_DISPATCHARR_INTERNAL_REQUEST=build_internal_request_header(
                "POST", PATH, other
            ),
        )
        self.assertEqual(response.status_code, 403)

    # -- the decision ----------------------------------------------------

    def test_an_ordinary_channel_authorizes_anonymously_with_seven_headers(self):
        response = self.post(self.question(f"/proxy/ts/stream/{self.plain.uuid}"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Channel"], str(self.plain.uuid))
        # Anonymous: no user resolved, which is a real answer and not a
        # failure -- a bare channel UUID still streams (parity-matrix row 24).
        self.assertEqual(response.headers["X-Relay-User"], "")
        # The seven the hop sets, named individually so a missing one says
        # which.
        for header in (
            "X-Relay-Channel",
            "X-Relay-Output",
            "X-Relay-Client",
            "X-Relay-User",
            "X-Relay-Name",
            "X-Relay-Output-Format",
            "X-Relay-Client-IP",
        ):
            self.assertIn(header, response.headers, f"{header} is missing")
        # X-Relay-Client-IP is the dev shape's ONLY source for ip_address:
        # there is no hop-set header to read (parity-matrix row 17).
        self.assertEqual(response.headers["X-Relay-Client-IP"], "198.51.100.4")
        self.assertNotEqual(response.headers["X-Relay-Client"], "")

    def test_a_hidden_channel_is_refused_403(self):
        response = self.post(self.question(f"/proxy/ts/stream/{self.hidden.uuid}"))
        self.assertEqual(response.status_code, 403)

    def test_an_unknown_channel_is_404_and_not_a_collapsed_403(self):
        """THE TRUE STATUS, which is the whole reason this route uses
        authorize_error_response rather than subrequest_error_response.

        The 403 collapse exists only because ngx_http_auth_request_module can
        transport a 2xx, a 401 and a 403 and nothing else. A direct POST has
        no such constraint, so collapsing here would invent a limitation and
        hand the Go relay a 403 where production answers 404.
        """
        response = self.post(
            self.question("/proxy/ts/stream/11111111-1111-4111-8111-111111111111")
        )
        self.assertEqual(response.status_code, 404)
        # And NOT the subrequest shape's marker, which would mean the wrong
        # helper was called and the status merely happened to survive.
        self.assertNotIn("X-Authorize-Status", response.headers)

    # -- the three silent failure modes ---------------------------------

    def test_the_transport_header_does_not_make_the_request_internal(self):
        """The BLOCKING finding § The contract names, asserted directly.

        Every call here carries X-Dispatcharr-Internal, because
        IsInternalRelay requires it. A view that let that header answer
        authorize_stream's own is_internal question would authorize this
        hidden channel -- _apply_channel_checks returns immediately for an
        internal principal (authorize.py:376-377).
        """
        response = self.post(
            self.question(f"/proxy/ts/stream/{self.hidden.uuid}", internal=False)
        )
        self.assertEqual(
            response.status_code,
            403,
            "a hidden channel authorized with internal=false: the transport's own "
            "X-Dispatcharr-Internal reached authorize_stream and every check was skipped",
        )

    def test_the_body_flag_does_make_the_request_internal(self):
        """The other half, so "nothing is ever internal" cannot be what
        makes the test above pass.

        internal=true is the DVR's own fetch, which carries the static
        marker with no bound counterpart (ADR 0005).
        """
        response = self.post(
            self.question(f"/proxy/ts/stream/{self.hidden.uuid}", internal=True)
        )
        self.assertEqual(response.status_code, 200)
        # The internal principal is not a user, so the header is empty --
        # which is also how a consumer tells it from an authenticated one.
        self.assertEqual(response.headers["X-Relay-User"], "")

    def test_a_session_cookie_resolves_the_real_user_and_not_anonymous(self):
        """THE ASSERTION IS THE RESOLVED IDENTITY, never a status code.

        A view that forwarded the cookie but read request.user would answer
        200 here as well, with the viewer silently downgraded to anonymous.
        X-Relay-User is the field that says which principal the decision was
        made for.
        """
        user = User.objects.create_user(
            username="ai-session", password="pw", user_level=User.UserLevel.STANDARD
        )
        session_client = Client()
        self.assertTrue(session_client.login(username="ai-session", password="pw"))
        cookie = session_client.cookies["sessionid"].value

        response = self.post(
            self.question(
                f"/proxy/ts/stream/{self.plain.uuid}",
                headers={
                    "authorization": None,
                    "cookie": f"sessionid={cookie}",
                    "x-api-key": None,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["X-Relay-User"],
            str(user.id),
            "the session cookie resolved to anonymous: the principal was read from "
            "request.user rather than from the session store, and every user-scoped "
            "check has quietly stopped applying",
        )

    def test_the_client_address_comes_from_the_body_and_not_the_transport(self):
        """The ACL is evaluated against the CLIENT's address.

        Asserted through X-Relay-Client-IP, which authorize_stream fills from
        get_client_ip(request) -- so a synthesised request carrying the
        relay's own REMOTE_ADDR would echo that instead.
        """
        response = self.post(
            self.question(
                f"/proxy/ts/stream/{self.plain.uuid}", client_ip="203.0.113.99"
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Client-IP"], "203.0.113.99")

    def test_the_query_string_reaches_the_decision(self):
        """?output_format= is resolved from the uri, so the uri must carry
        its query string -- the same correction § The contract records for
        the bound token's own second field."""
        response = self.post(
            self.question(f"/proxy/ts/stream/{self.plain.uuid}?output_format=fmp4")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Output-Format"], "fmp4")

    def test_a_body_that_does_not_validate_is_400(self):
        """DRF's own answer, which relay_client maps to RelayRefused."""
        response = self.post({"client_ip": "198.51.100.4", "internal": False})
        self.assertEqual(response.status_code, 400)

    # -- the arms a live-surface test does not reach --------------------
    #
    # Nine statements of this view are outside the live tune's own path,
    # and Gate 2's floor is a MAXIMUM: an uncovered new statement in a
    # module `scripts/coverage_live_path.coveragerc` includes raises
    # `missing` and fails `backend-tests.yml`'s Coverage gate however
    # green `apps.proxy.tests` is. 2c-7's CI found that the expensive way.
    # These five tests close all nine.

    def test_a_uri_whose_path_is_not_latin_1_is_resolved_as_it_arrived(self):
        """The decode arm `authorize_view` carries for the same reason.

        A client that sends a non-ASCII credential as raw UTF-8 bytes in the
        request line arrives latin-1 decoded, so the view re-encodes and
        decodes as UTF-8. A character above U+00FF cannot be latin-1 encoded
        at all -- UnicodeEncodeError, a UnicodeError subclass -- and the raw
        path is then resolved as it stands rather than raising here.
        """
        response = self.post(self.question("/proxy/ts/stream/日"))
        # 404, because no channel is named by that path -- and NOT a 500,
        # which is what an unguarded encode would produce.
        self.assertEqual(response.status_code, 404)

    def test_every_credential_header_reaches_the_authenticator_union(self):
        """All three, and the proof is that a REJECTED one is refused 401.

        Parity-matrix row 30's own distinction is the lever: a credential an
        authenticator explicitly rejects (an unknown API key) raises
        AuthenticationFailed and comes out 401, while a credential merely
        DECLINED -- no header at all -- falls through to the anonymous
        principal and streams. So a 401 here is positive evidence the header
        arrived at `_drf_user`'s union, and the anonymous 200 in the same
        test is what stops "everything 401s" being the reason.

        Both header slots are exercised, because ApiKeyAuthentication checks
        X-API-Key BEFORE falling back to an `Authorization: ApiKey …` header
        (apps/accounts/authentication.py:54-69) and § The contract calls that
        ordering out as the reason there are three fields and not two.
        """
        uri = f"/proxy/ts/stream/{self.plain.uuid}"

        for label, headers in (
            (
                "X-API-Key",
                {"authorization": None, "cookie": None, "x-api-key": "no-such-key"},
            ),
            (
                "Authorization: ApiKey",
                {
                    "authorization": "ApiKey no-such-key",
                    "cookie": None,
                    "x-api-key": None,
                },
            ),
        ):
            response = self.post(self.question(uri, headers=headers))
            self.assertEqual(
                response.status_code,
                401,
                f"a rejected credential in {label} did not reach the authenticator "
                "union: the header was dropped on the way into the synthesised request",
            )

        # And with no credential at all the same URI streams as anonymous,
        # so "this view 401s everything" cannot be what makes the two rows
        # above pass.
        anonymous = self.post(self.question(uri))
        self.assertEqual(anonymous.status_code, 200)
        self.assertEqual(anonymous.headers["X-Relay-User"], "")

    def test_a_uri_with_no_path_at_all_is_404(self):
        """Resolver404, which is a different 404 from an unknown channel.

        An ORDINARY unmatched path cannot reach it: `dispatcharr/urls.py`
        mounts the SPA catch-all, so almost everything resolves and comes out
        as the `surface is None` 403 above instead — which is why
        `authorize_view`'s own Resolver404 arm is uncovered too. An empty
        path is the reachable case, and a relay sending one is a malformed
        request rather than a client's.
        """
        response = self.post(self.question("?nothing=here"))
        self.assertEqual(response.status_code, 404)

    def test_a_uri_that_resolves_to_a_non_streaming_view_is_403(self):
        """`_surface_for` returns None for a route that is not a streaming
        surface, and the view fails closed rather than guessing."""
        response = self.post(self.question("/_dispatcharr/authorize"))
        self.assertEqual(response.status_code, 403)

    def test_the_two_catch_up_surfaces_take_their_identity_from_the_query(self):
        """The XC catch-up root reads username/password/stream out of the
        query string, and the native catch-up root reads session_id.

        Both are D1's Python-relay surfaces, and this view authorizes them
        too: it is registered unconditionally and the relay it answers is
        not the only caller a deployment can have. The assertion is the
        status vocabulary, not a decision -- these are refused for want of
        credentials, which is the point: the identity was built from the
        query rather than being absent.
        """
        xc = self.post(
            self.question("/streaming/timeshift.php?username=u&password=p&stream=1.ts")
        )
        self.assertIn(xc.status_code, (401, 403, 404))
        native = self.post(
            self.question(f"/proxy/catchup/{self.plain.uuid}?session_id=abc")
        )
        self.assertIn(native.status_code, (200, 401, 403, 404))
```

### Appendix AA — `relay/httpapi/authorize_test.go`

Six tests. The header assertions in the first are the point: the bound token signs no header, so identity-bearing material reaching Django as one is the oracle the body-signing fix exists to close.

**`relay/httpapi/authorize_test.go`**

```go
package httpapi

import (
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// An untrusted tune asks Django to authorize it, and the QUESTION travels in
// the body -- every field of it.
//
// THE HEADER ASSERTIONS ARE THE POINT, not decoration. The bound token signs
// the context, the method, the full path, the timestamp and sha256(body), and
// headers are not among them: a captured X-Dispatcharr-Internal-Request for
// this path would stay valid for 120 seconds against any combination of
// forwarded headers, so identity-bearing material reaching Django as a header
// is the authorization oracle § The contract's M-R3-1 fix exists to close.
func TestAnUntrustedTuneAsksDjangoAndSendsTheQuestionInTheBody(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)

	header := http.Header{}
	header.Set("Authorization", "Bearer a-jwt")
	header.Set("Cookie", "sessionid=abc123")
	header.Set("X-API-Key", "an-api-key")
	response := r.tune(t, "/proxy/ts/stream/c-untrusted?token=t", header)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the untrusted tune answered %d, want 200", response.StatusCode)
	}

	asked := r.Control.AuthorizeRequests()
	if len(asked) != 1 {
		t.Fatalf("the relay made %d authorize calls, want 1", len(asked))
	}
	// THE FULL PATH INCLUDING THE QUERY STRING: ?token=, ?session_id= and
	// ?output_format= are all resolved from it, and Django's own hop reads
	// X-Original-URI with its query attached.
	if asked[0].URI != "/proxy/ts/stream/c-untrusted?token=t" {
		t.Errorf("the relay asked about %q, want the full request URI with its query string", asked[0].URI)
	}
	if asked[0].ClientIP == "" {
		t.Errorf("the relay sent no client_ip: Django would evaluate the STREAMS ACL against " +
			"the RELAY's address (apps/proxy/authorize.py:425)")
	}
	if asked[0].Internal {
		t.Errorf("the relay reported internal=true for an ordinary client tune, which makes " +
			"_resolve_principal return INTERNAL_PRINCIPAL before any check runs")
	}
	for name, got := range map[string]*string{
		"authorization": asked[0].Headers.Authorization,
		"cookie":        asked[0].Headers.Cookie,
		"x-api-key":     asked[0].Headers.APIKey,
	} {
		if got == nil {
			t.Errorf("the relay sent no %q in the body: ApiKeyAuthentication checks X-API-Key "+
				"BEFORE falling back to an Authorization header, so a client authenticating "+
				"that way resolves to anonymous in this shape and to its real user in "+
				"production -- the cross-shape divergence D5 exists to prevent", name)
		}
	}

	// And NONE of the three reached Django as a header on the POST.
	calls := r.Control.RequestsTo(relaytest.AuthorizePath)
	if len(calls) != 1 {
		t.Fatalf("the fake recorded %d authorize requests", len(calls))
	}
	for _, name := range []string{"Authorization", "Cookie", "X-Api-Key"} {
		if got := calls[0].Header.Get(name); got != "" {
			t.Errorf("the authorize POST carried %s as a header (%q): the bound token signs "+
				"no header, so a captured token would be replayable against any value", name, got)
		}
	}
	// The two headers it MUST carry, because IsInternalRelay requires both.
	if calls[0].Header.Get(control.HeaderInternal) == "" || calls[0].Header.Get(control.HeaderInternalRequest) == "" {
		t.Errorf("the authorize POST is missing an internal header: it would 403 against a real Django")
	}
}

// A trusted tune asks NOTHING: the hop already decided, and the relay reads
// its seven values off the request.
//
// The counterpart of the test above, and the pair is what shows the fallback
// is a fallback rather than a second hop on every tune.
func TestATrustedTuneMakesNoAuthorizeCall(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-trusted", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	if got := r.Control.AuthorizeRequests(); len(got) != 0 {
		t.Fatalf("a trusted tune made %d authorize calls, want 0 -- this route exists for the "+
			"shape with no nginx, and calling it per tune in production would double the "+
			"control-plane load the hop already carries", len(got))
	}
}

// internal=true travels only when the CLIENT's own request carries the static
// marker -- the DVR's fetch -- and never because this call has to send one to
// satisfy IsInternalRelay.
//
// BOTH ROWS, because a relay that hard-coded either value would pass a test
// that checked one.
func TestInternalTravelsFromTheClientsMarkerAndNotTheTransports(t *testing.T) {
	for _, tc := range []struct {
		name     string
		marker   string
		internal bool
	}{
		{"an ordinary client", "", false},
		{"the DVR's own fetch", control.InternalPrincipalToken(testSecret), true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := fanRig(t, relaytest.Config{}, nil)
			header := http.Header{}
			if tc.marker != "" {
				header.Set(control.HeaderInternal, tc.marker)
			}
			response := r.tune(t, "/proxy/ts/stream/c-internal", header)
			defer func() { _ = response.Body.Close() }()

			asked := r.Control.AuthorizeRequests()
			if len(asked) != 1 {
				t.Fatalf("the relay made %d authorize calls, want 1", len(asked))
			}
			if asked[0].Internal != tc.internal {
				t.Fatalf("the relay reported internal=%v for %s, want %v", asked[0].Internal, tc.name, tc.internal)
			}
		})
	}
}

// A denial reaches the viewer as ITSELF, with its own status and its own
// body.
//
// FOUR STATUSES, because the whole reason this route answers with
// authorize_error_response rather than subrequest_error_response is that a
// direct POST has no auth_request module to collapse them for: a 404 for an
// unknown channel and a 429 for a user over their stream limit would
// otherwise reach a viewer as 403. A test that checked only 403 would pass
// against the collapsed shape.
func TestADenialReachesTheViewerWithItsOwnStatus(t *testing.T) {
	// BOTH BRANCHES OF writeAuthorizeFailure, because they are two different
	// lines: a denial that carried a JSON body is forwarded verbatim, and one
	// that carried none answers with the status text. Break-check 10 patched
	// the second branch and stayed GREEN until the body-less rows were added
	// -- every row had a body.
	for _, tc := range []struct {
		status   int
		body     string
		bodyless bool
	}{
		{status: http.StatusUnauthorized, body: `{"error":"Invalid credentials"}`},
		{status: http.StatusForbidden, body: `{"error":"Forbidden"}`},
		{status: http.StatusNotFound, body: `{"error":"Not found"}`},
		{status: http.StatusTooManyRequests, body: `{"error":"Stream limit exceeded (3 concurrent streams allowed)"}`},
		{status: http.StatusUnauthorized, bodyless: true},
		{status: http.StatusNotFound, bodyless: true},
		{status: http.StatusTooManyRequests, bodyless: true},
	} {
		r := fanRig(t, relaytest.Config{}, nil)
		r.Control.SetAuthorize(&relaytest.AuthorizeDecision{
			Status: tc.status, Body: tc.body, NonJSONBody: tc.bodyless,
		})
		response := r.tune(t, "/proxy/ts/stream/c-denied", http.Header{})
		body := readAtLeast(response.Body, 1, 5*time.Second)
		_ = response.Body.Close()

		if response.StatusCode != tc.status {
			t.Errorf("a %d denial (bodyless=%v) reached the viewer as %d",
				tc.status, tc.bodyless, response.StatusCode)
		}
		if !tc.bodyless && string(body) != tc.body {
			t.Errorf("a %d denial's body reached the viewer as %q, want %q", tc.status, body, tc.body)
		}
		if tc.bodyless && strings.Contains(string(body), "relaytest") {
			t.Errorf("a %d denial echoed the control plane's own non-JSON body to the viewer: %q",
				tc.status, body)
		}
		// And nothing was tuned.
		if got := len(r.Control.RequestsTo("/next-source")); got != 0 {
			t.Errorf("a %d denial still made %d next-source calls", tc.status, got)
		}
	}
}

// A control plane that cannot answer is a 502, and never a denial.
//
// The distinction matters operationally: a viewer told 403 stops retrying and
// an operator looks for a permissions problem, where the real fault is that
// Django is down. 502 is what the relay says about itself.
func TestAnUnreachableControlPlaneIsA502AndNotADenial(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	r.Control.SetAuthorize(&relaytest.AuthorizeDecision{Status: http.StatusInternalServerError})

	response := r.tune(t, "/proxy/ts/stream/c-broken", http.Header{})
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("a 500 from the control plane reached the viewer as %d, want 502", response.StatusCode)
	}
}

// The decision's values are what the tune uses -- all six of them -- where a
// trusted tune uses the headers.
//
// The channel is the one that can fail loudest: a relay that used the PATH
// would stream a channel Django did not authorize, which is exactly what
// X-Relay-Channel exists to prevent on the trusted path.
func TestTheDecisionsValuesAreUsedRatherThanThePathAndTheSocket(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	r.Control.SetAuthorize(&relaytest.AuthorizeDecision{
		Channel:  "c-from-django",
		Client:   "client-from-django",
		User:     "42",
		ClientIP: "203.0.113.7",
	})

	response := r.tune(t, "/proxy/ts/stream/c-from-the-path", http.Header{})
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the tune answered %d", response.StatusCode)
	}
	packetRun(t, "the client", response.Body, 1)

	if got := r.Control.RequestsTo("/next-source"); len(got) != 1 ||
		!containsString(got[0].Path, "c-from-django") {
		t.Fatalf("the tune asked next-source about %v, want the channel Django resolved", got)
	}
	ch := r.Manager.Get("c-from-django")
	if ch == nil {
		t.Fatalf("the relay is running %v, not the channel Django named", runningIDs(r))
	}
	clients := ch.ClientSnapshot()
	if len(clients) != 1 {
		t.Fatalf("the channel has %d clients", len(clients))
	}
	if clients[0].ID != "client-from-django" {
		t.Errorf("the client id is %q, want the one Django minted -- a relay that minted its "+
			"own would give an admin a handle Django never issued", clients[0].ID)
	}
	if clients[0].UserID != "42" {
		t.Errorf("the client's user_id is %q, want 42", clients[0].UserID)
	}
	if clients[0].IPAddress != "203.0.113.7" {
		t.Errorf("the client's ip_address is %q, want the address Django resolved -- this "+
			"response is the dev shape's ONLY source for it (parity-matrix row 17)", clients[0].IPAddress)
	}
}

func containsString(haystack, needle string) bool {
	return len(haystack) >= len(needle) && (func() bool {
		for i := 0; i+len(needle) <= len(haystack); i++ {
			if haystack[i:i+len(needle)] == needle {
				return true
			}
		}
		return false
	})()
}
```

### Appendix AB — `relay/httpapi/xc.go`

Ruling R1. A wrapper, not a second handler: the channel an XC root serves is the one the hop resolved, and the extension contributes only the output format.

**`relay/httpapi/xc.go`**

```go
package httpapi

import (
	"net/http"
	"path"
	"regexp"
	"strings"

	"github.com/D10Scot/Dispatcharr/relay/output"
)

// XCStreamIDPattern is dispatcharr/utils.py:115's XC_STREAM_ID_PATTERN,
// anchored: digits with an optional extension, and nothing else.
//
// Django's URL resolver applies it, so a path that does not match reaches
// stream_xc never -- it falls through to the SPA catch-all. This relay has no
// catch-all, so the handler applies the pattern itself and answers 404, which
// is the same outcome from the client's side.
var XCStreamIDPattern = regexp.MustCompile(`\A\d+(?:\.[A-Za-z0-9]+)?\z`)

// XCHandler serves the two XC live roots: /live/<user>/<pass>/<id> and the
// bare /<user>/<pass>/<id>.
//
// WHY THIS IS A WRAPPER AND NOT A SECOND HANDLER. stream_xc authorizes ONCE
// and passes its decision into stream_ts (views.py:862-889), so an XC tune is
// not authorized twice and does not mint a second client id for one
// connection -- parity-matrix row 15. The Go shape is the same: the channel
// this serves is the one the authorize hop resolved (X-Relay-Channel) or the
// one the dev fallback's decision named, NEVER the numeric id in the path,
// which this relay cannot map to a uuid because that mapping is an ORM query.
//
// The extension is the ONE thing the path contributes, and it contributes it
// to the output format rather than to the channel: `.mp4` forces fMP4 and
// `.ts` forces MPEG-TS (:873-878), overriding whatever the hop resolved.
// authorize_stream's resolve_output_format takes a `force` parameter and the
// hop never passes it, "because the hop authorizes a URI and the override is
// a property of the view's call" (apps/proxy/authorize.py:236-246) -- so the
// override has to be applied here, on both relays, for the same reason.
func XCHandler(deps StreamDeps) http.Handler {
	inner := StreamHandler(deps)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw := r.PathValue("channelID")
		if !XCStreamIDPattern.MatchString(raw) {
			// Django's resolver would not have matched this path at all.
			http.NotFound(w, r)
			return
		}
		if force := xcForcedFormat(raw); force != "" {
			// Applied by REWRITING THE HEADER the hop set, so identify()
			// keeps one source for the client's format and this stays the
			// only place the extension is read. Set on the request the
			// inner handler sees, never on the client's own: a rewrite is
			// only legitimate because the extension is part of the URI the
			// hop already authorized.
			r.Header.Set("X-Relay-Output-Format", force)
		}
		inner(w, r)
	})
}

// xcForcedFormat is views.py:872-878's extension override, lowercased as it
// lowercases. An extension that is neither returns "", which leaves the hop's
// own X-Relay-Output-Format standing.
func xcForcedFormat(id string) string {
	switch strings.ToLower(path.Ext(id)) {
	case ".mp4":
		return output.FormatFMP4
	case ".ts":
		return OutputFormatMPEGTS
	}
	return ""
}
```

### Appendix AC — `relay/httpapi/xc_test.go`

Four tests, one of which asserts that the bare three-segment root does not shadow `/proxy/relay/channels` -- trusting `net/http`'s specificity rule there would cost a 404 on every stats poll.

**`relay/httpapi/xc_test.go`**

```go
package httpapi

import (
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/output"
)

// tuneXC opens an XC live root over the trusted path: the hop has resolved
// the numeric id to a uuid and put it on X-Relay-Channel, exactly as
// stream_xc hands decision.channel_uuid to stream_ts.
func (r *rig) tuneXC(t *testing.T, root, channelUUID, clientID string) *http.Response {
	t.Helper()
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", channelUUID)
	header.Set("X-Relay-Client", clientID)
	header.Set("X-Relay-Client-IP", "198.51.100.4")
	header.Set("X-Relay-User", "7")
	return r.tune(t, root, header)
}

// ROW 15: an XC tune serves the channel the hop resolved, is authorized
// once, and mints no second client id.
//
// THE CHANNEL ASSERTION IS THE ONE THAT CAN FAIL LOUDEST: the path carries
// the numeric Xtream id and the header carries the uuid, and a relay that
// used the path would tune a channel nobody authorized -- and could not, in
// fact, tune anything, since the numeric id maps to a uuid only through an
// ORM query this process cannot make.
func TestAnXCTuneServesTheHopsChannelAndAuthorizesOnce(t *testing.T) {
	for _, root := range []string{
		"/live/xcuser/xcpass/12345",
		"/xcuser/xcpass/12345",
	} {
		t.Run(root, func(t *testing.T) {
			r := fanRig(t, relaytest.Config{}, nil)
			response := r.tuneXC(t, root, "c-xc-uuid", "client-from-the-hop")
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != http.StatusOK {
				t.Fatalf("the XC tune answered %d, want 200", response.StatusCode)
			}
			packetRun(t, "the XC client", response.Body, 1)

			if r.Manager.Get("c-xc-uuid") == nil {
				t.Fatalf("the relay is running %v, not the uuid the hop resolved", runningIDs(r))
			}
			if r.Manager.Get("12345") != nil {
				t.Fatalf("the relay tuned the numeric path id, which it cannot map to a uuid")
			}
			// AUTHORIZED ONCE: a trusted XC tune asks the control plane
			// nothing, exactly as a trusted native tune does. A relay that
			// re-authorized here would make every XC tune cost a hop Django
			// already paid for.
			if got := r.Control.AuthorizeRequests(); len(got) != 0 {
				t.Errorf("a trusted XC tune made %d authorize calls, want 0", len(got))
			}
			// AND NO SECOND CLIENT ID: the id the hop minted is the id the
			// registry holds.
			clients := r.Manager.Get("c-xc-uuid").ClientSnapshot()
			if len(clients) != 1 || clients[0].ID != "client-from-the-hop" {
				t.Errorf("the registry holds %v, want exactly the hop's client id", clients)
			}
		})
	}
}

// The extension overrides the output format the hop resolved, and only the
// two extensions views.py:872-878 names do.
//
// FOUR ROWS, and the third and fourth are what make it able to fail: a
// relay that ignored the extension would pass a test that only checked
// ".mp4 is fmp4" if the hop had already said fmp4.
func TestTheXCExtensionOverridesTheHopsOutputFormat(t *testing.T) {
	for _, tc := range []struct {
		id       string
		hopSaid  string
		wantFmt  string
		wantCode int
	}{
		{"12345.mp4", OutputFormatMPEGTS, output.FormatFMP4, http.StatusOK},
		{"12345.ts", output.FormatFMP4, OutputFormatMPEGTS, http.StatusOK},
		// No extension: the hop's own answer stands.
		{"12345", output.FormatFMP4, output.FormatFMP4, http.StatusOK},
		// An extension that is neither leaves it standing too.
		{"12345.m3u8", OutputFormatMPEGTS, OutputFormatMPEGTS, http.StatusOK},
	} {
		t.Run(tc.id, func(t *testing.T) {
			r := fanRig(t, relaytest.Config{Rate: 4}, nil,
				withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))
			header := http.Header{}
			header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
			header.Set("X-Relay-Channel", "c-xc-fmt")
			header.Set("X-Relay-Client", "client-a")
			header.Set("X-Relay-Output-Format", tc.hopSaid)
			response := r.tune(t, "/live/u/p/"+tc.id, header)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != tc.wantCode {
				t.Fatalf("the XC tune answered %d, want %d", response.StatusCode, tc.wantCode)
			}

			// The format is read off the CLIENT REGISTRY, which is what the
			// status surfaces render -- not off the Content-Type, which is a
			// second derivation of the same fact.
			waitFor(t, "the client to register", 15*time.Second, func() bool {
				ch := r.Manager.Get("c-xc-fmt")
				return ch != nil && ch.Clients() == 1
			})
			got := r.Manager.Get("c-xc-fmt").ClientSnapshot()[0].OutputFormat
			if got != tc.wantFmt {
				t.Fatalf("the client's output_format is %q, want %q", got, tc.wantFmt)
			}
		})
	}
}

// A path Django's own resolver would not match is a 404 here.
//
// XC_STREAM_ID_PATTERN is digits with an optional extension; anything else
// falls through to the SPA catch-all there and has nowhere to fall through
// to here, so the handler applies the pattern itself.
func TestAnXCPathDjangoWouldNotResolveIs404(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	for _, id := range []string{"not-a-number", "12345.", "12345.mp4.extra", ""} {
		response := r.tuneXC(t, "/live/u/p/"+id, "c-xc-uuid", "client-a")
		status := response.StatusCode
		_ = response.Body.Close()
		if status != http.StatusNotFound {
			t.Errorf("the XC root with id %q answered %d, want 404", id, status)
		}
	}
	// And nothing was tuned by any of them.
	if got := len(r.Manager.Snapshot()); got != 0 {
		t.Errorf("the relay is running %d channels after four refused XC paths", got)
	}
}

// The bare three-segment XC root does NOT shadow the internal control
// collection route, which has exactly three segments too.
//
// net/http's mux prefers the more specific pattern, and this asserts that
// rather than trusting it: /proxy/relay/channels reaching XCHandler would
// answer 404 for every stats poll in the deployment.
func TestTheBareXCRootDoesNotShadowTheControlRoutes(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	status, raw := r.listChannels(t, "")
	if status != http.StatusOK {
		t.Fatalf("GET /proxy/relay/channels answered %d, want 200: the bare XC root shadowed "+
			"it -- %s", status, raw)
	}
	if _, present := decodeObject(t, raw)["channels"]; !present {
		t.Fatalf("GET /proxy/relay/channels answered %s, which is not the list payload", raw)
	}
}

// runningIDs names the channels the manager holds, for a failure message: a
// []*channel.Channel prints as pointers and says nothing.
func runningIDs(r *rig) []string {
	var out []string
	for _, c := range r.Manager.Snapshot() {
		out = append(out, c.ID())
	}
	return out
}
```

### Appendix AD — `relay/drain/drain.go`

The package doc carries the whole budget derivation from `relay-go.conf`'s `stopwaitsecs=20`. `Run`'s doc carries Ruling R11's five steps and why each is where it is.

**`relay/drain/drain.go`**

```go
// Package drain is the relay's SIGTERM shutdown: spec D6's "drain-on-SIGTERM,
// /healthz, /readyz, wired to supervisord stopwaitsecs and a Docker
// HEALTHCHECK".
//
// WHAT IT IMPROVES ON, DELIBERATELY. The Python relay runs uWSGI's
// `die-on-term` with no drain at all, so "every deploy still drops every
// viewer" (CLAUDE.md § Operationally). D6 names that as a real gap this phase
// closes in a language where a drain loop is a few dozen lines, so this is a
// STATED DIVERGENCE FROM PARITY rather than a port -- the one place in stage
// 2c where the Go relay is meant to behave differently from the Python one,
// and D5's parity rule does not cover it because D6 supersedes it here.
//
// THE BUDGET, DERIVED RATHER THAN CHOSEN. docker/supervisord.d/relay-go.conf
// carries stopwaitsecs=20 at priority=205, the SAME priority group as
// relay-uwsgi (whose stopwaitsecs is also 20). supervisord signals one
// priority group at a time and waits out that group's longest stopwaitsecs
// before moving on, so this group costs max(20, 20) = 20s and the container's
// whole stop budget is 155s against docker-compose's 160s
// stop_grace_period. Twenty seconds is therefore the hard ceiling on
// everything below, and DefaultBudget leaves five of them as margin for
// supervisord's own signalling and the process's exit.
package drain

import (
	"context"
	"log/slog"
	"time"
)

// The budget and its two sub-budgets. Every one of them is a Go-side
// constant rather than a setting on the wire, and that is the one place
// Global Constraint 13 does not apply: these describe THIS PROCESS'S
// shutdown against THIS DEPLOYMENT'S supervisord configuration, which is in
// the image beside the binary, not a value an operator changes in the UI.
const (
	// DefaultBudget bounds the whole sequence. 15s against
	// stopwaitsecs=20, leaving 5s of margin.
	DefaultBudget = 15 * time.Second

	// DefaultClientGrace is how long connected viewers keep being served
	// after the signal, while no new tune is accepted. This is D6's "lets
	// running clients finish or cuts them at a bound" -- a live stream never
	// finishes, so the bound is the operative half, and what the grace buys
	// is five more seconds of a player's buffer across a rolling restart
	// rather than an instant cut.
	DefaultClientGrace = 5 * time.Second

	// DefaultEventsBudget bounds the emitter flush. Deliberately SHORTER
	// than control.Client's own worst case for one batch (two attempts of
	// (2s, 5s) plus the retry delay, ~14.1s): exiting inside the supervisord
	// window matters more than the last batch of events, and an event lost
	// to a shutdown is the behaviour control_plane.py already has ("an event
	// raised while the control plane is down is LOST, not queued").
	DefaultEventsBudget = 3 * time.Second
)

// Server is the http.Server half: everything this package needs of it.
type Server interface {
	Shutdown(ctx context.Context) error
}

// Channels is the manager half.
type Channels interface {
	// StopAll tears every channel down and returns when they are all done.
	StopAll()
}

// Events is the emitter half.
type Events interface {
	// Close stops the worker once the queue has drained.
	Close()
}

// Gate is the lifecycle flag: what makes new tunes stop being accepted and
// /readyz start answering 503.
type Gate interface {
	BeginDrain()
}

// Deps is everything Run needs. Every field except Log and Now is required;
// a nil one is skipped rather than panicked on, so a partially-wired process
// still exits.
type Deps struct {
	Gate     Gate
	Channels Channels
	Server   Server
	Events   Events

	Log *slog.Logger
	Now func() time.Time

	// Budget, ClientGrace and EventsBudget default to the three constants
	// above when zero.
	Budget       time.Duration
	ClientGrace  time.Duration
	EventsBudget time.Duration
}

// Run performs the drain and reports how long it took.
//
// THE ORDER IS THE WHOLE DESIGN, and every step is there because the step
// after it would be wrong without it:
//
//  1. Raise the gate. New tunes answer 503 and /readyz answers 503, so
//     nothing new is started and, at stage 2d, nginx stops routing here.
//  2. Serve the connected viewers for ClientGrace. The upstream is still
//     running and the ring is still filling, so this is the only step that
//     is FOR the viewer rather than for the deployment.
//  3. Stop every channel, concurrently. This is what ends the client
//     goroutines: each channel's ring closes, every serveClient loop sees
//     ErrClosed and returns, each output pipeline is stopped by run's own
//     defers, and each provider slot is released through the control plane
//     by Channel.releaseSlot. WITHOUT THIS STEP Shutdown BELOW WOULD BLOCK
//     FOR EVER -- a live stream is one request that never finishes, and
//     http.Server.Shutdown waits for in-flight requests.
//  4. Shut the server down. By now the handlers have returned, so this
//     closes the listener and the idle connections and returns at once.
//  5. Flush the emitter. LAST, because steps 3 and 4 are what RAISE the
//     events this flush exists to deliver -- one channel_stop per channel
//     and one client_disconnect per TS viewer.
//
// Steps 2 to 4 share one deadline -- each gets what the ones before it left --
// and step 5's budget is RESERVED out of the total rather than being whatever
// is left, so a slow teardown costs the shutdown its wait and never costs the
// events their delivery.
func Run(d Deps) time.Duration {
	log := d.Log
	if log == nil {
		log = slog.Default()
	}
	now := d.Now
	if now == nil {
		now = time.Now
	}
	budget, grace, eventsBudget := d.Budget, d.ClientGrace, d.EventsBudget
	if budget <= 0 {
		budget = DefaultBudget
	}
	if grace <= 0 {
		grace = DefaultClientGrace
	}
	if eventsBudget <= 0 {
		eventsBudget = DefaultEventsBudget
	}

	// THE EVENTS FLUSH IS RESERVED, not left whatever the earlier steps
	// happen to leave. A channel teardown that used the whole budget would
	// otherwise reach the flush with nothing left and exit having raised a
	// channel_stop per channel and delivered none of them -- which is the
	// one thing the flush is for. Clamped to a third of the budget so a
	// caller cannot reserve more than it has.
	if eventsBudget > budget/3 {
		eventsBudget = budget / 3
	}
	started := now()
	deadline := started.Add(budget)
	// What the gate, the grace, the teardown and the shutdown share.
	teardownDeadline := deadline.Add(-eventsBudget)

	if d.Gate != nil {
		d.Gate.BeginDrain()
	}
	log.Info("draining", "budget", budget, "client_grace", grace)

	// 2. The grace, bounded by the teardown deadline as everything before
	// the flush is.
	if remaining := teardownDeadline.Sub(now()); remaining > 0 {
		wait := min(grace, remaining)
		timer := time.NewTimer(wait)
		<-timer.C
		timer.Stop()
	}

	// 3. Stop every channel. Bounded by the manager's own per-channel
	// StopWait, which the concurrent sweep makes a single wait rather than
	// N of them; the select is the backstop for a channel whose source
	// goroutine ignores its context entirely.
	if d.Channels != nil {
		waitFor(log, "the channels to stop", teardownDeadline.Sub(now()), d.Channels.StopAll)
	}

	// 4. Close the listener and the idle connections.
	if d.Server != nil {
		ctx, cancel := context.WithDeadline(context.Background(), teardownDeadline)
		if err := d.Server.Shutdown(ctx); err != nil {
			// A deadline here means a request is still in flight after every
			// channel was stopped -- worth a line, and never a reason not to
			// flush the events below.
			log.Warn("the HTTP server did not shut down inside the drain budget", "error", err) // credential-logging: ok - http.Server.Shutdown returns the context's own error
		}
		cancel()
	}

	// 5. Flush the events raised by steps 3 and 4.
	if d.Events != nil {
		waitFor(log, "the relay events to flush", eventsBudget, d.Events.Close)
	}

	elapsed := now().Sub(started)
	log.Info("drained", "elapsed", elapsed)
	return elapsed
}

// waitFor runs fn on its own goroutine and waits at most `within` for it.
//
// A goroutine rather than a direct call because every step here has to be
// bounded by the shared deadline, and none of the three underlying calls
// takes a context: Manager.StopAll waits on its own per-channel timers and
// Emitter.Close waits on a worker that may be inside a control-plane call.
// A goroutine that outlives the wait is deliberate and costs nothing -- the
// process is about to exit, and the alternative is blocking past the
// supervisord window and being SIGKILLed with the rest of the drain undone.
func waitFor(log *slog.Logger, what string, within time.Duration, fn func()) {
	done := make(chan struct{})
	go func() {
		defer close(done)
		fn()
	}()
	if within <= 0 {
		log.Warn("no time left in the drain budget", "for", what)
		return
	}
	timer := time.NewTimer(within)
	defer timer.Stop()
	select {
	case <-done:
	case <-timer.C:
		log.Warn("the drain budget ran out", "waiting_for", what, "waited", within)
	}
}
```

### Appendix AE — `relay/drain/drain_test.go`

Four tests. The first pins the ARITHMETIC against supervisord rather than the three numbers; the third takes its clock before `Run` and bounds itself with a select, so an overrun fails in seconds and names the mechanism.

**`relay/drain/drain_test.go`**

```go
package drain

import (
	"context"
	"sync"
	"testing"
	"time"
)

// The three budgets are Go-side constants that answer to ONE external number:
// docker/supervisord.d/relay-go.conf's stopwaitsecs=20, after which
// supervisord SIGKILLs this process. Pinned as an arithmetic relationship
// rather than as three literals, so a later change to any of them has to keep
// the sum inside the window it exists to fit.
func TestTheBudgetFitsInsideSupervisordsStopWindow(t *testing.T) {
	// docker/supervisord.d/relay-go.conf:34. Written here as a literal
	// because it lives in a file this package cannot read, and the plan's
	// docker/supervisord.d/relay-go.conf:34, which the plan's Task 8 changes
	// together with this constant when either moves.
	const supervisordStopWait = 20 * time.Second

	if DefaultBudget >= supervisordStopWait {
		t.Fatalf("DefaultBudget is %s against a stopwaitsecs of %s: the drain would be "+
			"SIGKILLed partway through, losing every release and every channel_stop",
			DefaultBudget, supervisordStopWait)
	}
	if margin := supervisordStopWait - DefaultBudget; margin < 3*time.Second {
		t.Errorf("only %s of margin between the drain budget and stopwaitsecs; supervisord's "+
			"own signalling and the process exit need room", margin)
	}
	if DefaultClientGrace+DefaultEventsBudget >= DefaultBudget {
		t.Errorf("the client grace (%s) and the events flush (%s) already exceed the whole "+
			"budget (%s), leaving nothing for the channel teardown between them",
			DefaultClientGrace, DefaultEventsBudget, DefaultBudget)
	}
}

type fakeGate struct {
	mu    sync.Mutex
	began bool
}

func (f *fakeGate) BeginDrain() {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.began = true
}

func (f *fakeGate) Began() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.began
}

// recorder records the order the drain calls its dependencies in, which is
// the whole design: the gate first, the channels before the server, the
// events last.
type recorder struct {
	mu    sync.Mutex
	order []string

	stopFor  time.Duration
	closeFor time.Duration

	// gateSeenAt is what the gate had been set to when StopAll ran, which is
	// how "no new tune is accepted before anything is torn down" is asserted
	// rather than assumed.
	gate       *fakeGate
	gateAtStop bool
}

func (r *recorder) note(what string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.order = append(r.order, what)
}

func (r *recorder) Order() []string {
	r.mu.Lock()
	defer r.mu.Unlock()
	return append([]string(nil), r.order...)
}

func (r *recorder) StopAll() {
	r.note("channels")
	r.mu.Lock()
	if r.gate != nil {
		r.gateAtStop = r.gate.Began()
	}
	r.mu.Unlock()
	time.Sleep(r.stopFor)
}

func (r *recorder) Shutdown(ctx context.Context) error {
	r.note("server")
	return ctx.Err()
}

func (r *recorder) Close() {
	r.note("events")
	time.Sleep(r.closeFor)
}

// The order, and the gate being up before anything is torn down.
//
// THE CLOCK STARTS BEFORE Run IS CALLED, which is the one property a timing
// assertion here has to have: a measurement taken inside the thing being
// measured cannot see the time its own setup spent.
func TestTheDrainRaisesTheGateFirstAndFlushesTheEventsLast(t *testing.T) {
	gate := &fakeGate{}
	rec := &recorder{gate: gate}

	started := time.Now()
	elapsed := Run(Deps{
		Gate:        gate,
		Channels:    rec,
		Server:      rec,
		Events:      rec,
		ClientGrace: 20 * time.Millisecond,
		Budget:      2 * time.Second,
	})
	measured := time.Since(started)

	if !gate.Began() {
		t.Errorf("the gate was never raised: new tunes would have been accepted throughout")
	}
	if !rec.gateAtStop {
		t.Errorf("the channels were torn down before the gate went up: a tune arriving in " +
			"that window starts a channel the drain has already walked past")
	}
	want := []string{"channels", "server", "events"}
	got := rec.Order()
	if len(got) != len(want) {
		t.Fatalf("the drain called %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("the drain called %v, want %v -- the order is the design: the channels "+
				"must stop before Shutdown (a live stream is a request that never finishes) "+
				"and the events must flush last (the teardown is what raises them)", got, want)
		}
	}
	if elapsed > measured {
		t.Errorf("Run reported %s but the wall clock outside it saw only %s", elapsed, measured)
	}
}

// A dependency that never returns does not push the drain past its budget.
//
// The failure this exists to catch is the one that matters operationally: a
// channel whose source goroutine ignores its context, or a control plane that
// black-holes the events POST, must cost the deployment a warning line and
// not a SIGKILL partway through the teardown.
func TestADependencyThatHangsDoesNotOverrunTheBudget(t *testing.T) {
	rec := &recorder{stopFor: time.Hour, closeFor: time.Hour}

	// RUN ON ITS OWN GOROUTINE with a select, so an overrun fails in seconds
	// and NAMES THE MECHANISM rather than hanging until the package's
	// ten-minute test timeout -- which is what break-check 22 produced
	// before this was restructured, and a ten-minute break-check is an
	// obstacle to whoever runs it next. THE CLOCK STILL STARTS BEFORE Run.
	started := time.Now()
	type result struct{ elapsed time.Duration }
	done := make(chan result, 1)
	go func() {
		done <- result{Run(Deps{
			Gate:         &fakeGate{},
			Channels:     rec,
			Server:       rec,
			Events:       rec,
			ClientGrace:  10 * time.Millisecond,
			Budget:       300 * time.Millisecond,
			EventsBudget: time.Hour,
		})}
	}()
	var elapsed time.Duration
	select {
	case r := <-done:
		elapsed = r.elapsed
	case <-time.After(5 * time.Second):
		t.Fatalf("the drain has not returned after 5s against a 300ms budget: a hung " +
			"dependency is exactly what the shared deadline and the events-budget clamp " +
			"exist to bound, and supervisord SIGKILLs at stopwaitsecs either way")
	}
	measured := time.Since(started)

	if measured > time.Second {
		t.Fatalf("the drain took %s against a 300ms budget: a hung channel teardown is "+
			"exactly what the shared deadline exists to bound", measured)
	}
	if elapsed > 500*time.Millisecond {
		t.Errorf("Run reported %s, want something close to its 300ms budget", elapsed)
	}
	// And it still ran every step: a drain that bailed out on the first
	// timeout would leave the events unflushed, which is the case the
	// ordering above exists for.
	if got := rec.Order(); len(got) != 3 {
		t.Errorf("the drain called %v, want all three steps even when the first one hangs", got)
	}
}

// Every dependency is optional, and a partially-wired process still exits.
func TestRunWithNoDependenciesReturns(t *testing.T) {
	if elapsed := Run(Deps{ClientGrace: time.Millisecond, Budget: time.Second}); elapsed > time.Second {
		t.Fatalf("an empty drain took %s", elapsed)
	}
}
```

### Appendix AF — `relay/httpapi/health.go`

Ruling R12 is this file. `/readyz` reports the drain and the counts and deliberately does not probe the control plane.

**`relay/httpapi/health.go`**

```go
package httpapi

import (
	"log/slog"
	"net/http"
	"sync/atomic"

	"github.com/D10Scot/Dispatcharr/relay/channel"
)

// Lifecycle is the one bit of process state the health endpoints and the
// tune path share: whether this relay is draining.
//
// One flag, read from three places -- /readyz, the tune handler and the
// drain's own sequence -- rather than a flag per reader, because the whole
// point of D6's drain is that "stop accepting tunes" and "tell the load
// balancer to stop sending them" are the same decision made once.
type Lifecycle struct{ draining atomic.Bool }

// BeginDrain marks the process as draining. Idempotent.
func (l *Lifecycle) BeginDrain() { l.draining.Store(true) }

// Draining reports whether the drain has begun.
func (l *Lifecycle) Draining() bool { return l != nil && l.draining.Load() }

// HealthDeps is what the two operational endpoints need.
//
// Both were static 200s from 2c-1 through 2c-7, and 2c-1's own comment said
// why: "/readyz becomes meaningful in 2c-8, when the SIGTERM drain gives it
// something to report -- and that is also why this PR adds no Docker
// HEALTHCHECK: a probe wired to a static 200 reports healthy through every
// failure it exists to catch."
type HealthDeps struct {
	// Channels is what the readiness body counts. Nil reports zero, which is
	// what a process with no manager honestly has.
	Channels *channel.Manager

	// Lifecycle is the drain flag. Nil is never draining.
	Lifecycle *Lifecycle

	// Log is the logger. Nil means slog.Default().
	Log *slog.Logger
}

// readyPayload is what /readyz answers with.
//
// The counts are what makes it a real report rather than a second liveness
// probe: an operator watching a rolling restart can see the channel count
// fall to zero, and a readiness probe that only ever says "ok" cannot tell a
// relay that is serving from one that is about to stop.
type readyPayload struct {
	Status   string `json:"status"`
	Channels int    `json:"channels"`
	Clients  int    `json:"clients"`
}

// StatusReady and StatusDraining are readyPayload's two values.
const (
	StatusReady    = "ready"
	StatusDraining = "draining"
)

// ReadyHandler serves GET /readyz.
//
// WHAT "READY" MEANS HERE IS DELIBERATELY NARROW: this process is serving and
// is not draining. It does NOT probe the control plane, and that is a
// decision rather than an omission. A relay that marked itself unready during
// a Django outage would be taken out of nginx's rotation at stage 2d -- and
// a running stream needs nothing from Django at all once it is running
// (CLAUDE.md § Operationally: stopping api-uwsgi "does not disturb a running
// stream"), so deregistering would turn a degraded new-tune path into a total
// outage for viewers who were fine. The control plane's reachability is
// reported where it belongs, in the emitter's one-line-per-transition log.
//
// /healthz stays a static 200 and stays LIVENESS: it answers 200 throughout
// the drain, because a supervisor that restarted the process mid-drain would
// defeat the drain.
func ReadyHandler(deps HealthDeps) http.HandlerFunc {
	log := deps.Log
	if log == nil {
		log = slog.Default()
	}
	return func(w http.ResponseWriter, _ *http.Request) {
		body := readyPayload{Status: StatusReady}
		if deps.Channels != nil {
			for _, c := range deps.Channels.Snapshot() {
				body.Channels++
				body.Clients += c.Clients()
			}
		}
		status := http.StatusOK
		if deps.Lifecycle.Draining() {
			body.Status = StatusDraining
			status = http.StatusServiceUnavailable
		}
		writeJSONStatus(w, log, status, body)
	}
}
```

### Appendix AG — `relay/httpapi/drain_test.go`

Three tests over a real manager, a real client and a real emitter. Each takes its clock before `drain.Run`.

**`relay/httpapi/drain_test.go`**

```go
package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/drain"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// readyz answers what the drain flag says, and counts what the manager holds.
//
// Three states in one test -- empty, serving, draining -- because a body that
// always said "ready, 0, 0" would pass a test that only checked the first,
// and a probe that always said "ready" is the static 200 under a new name.
func TestReadyzReportsTheChannelCountAndTheDrain(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)

	status, body := r.readyz(t)
	if status != http.StatusOK || body.Status != StatusReady || body.Channels != 0 {
		t.Fatalf("an idle relay answered %d %+v, want 200 ready with no channels", status, body)
	}

	response := r.tuneAs(t, "c-ready", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 1)

	status, body = r.readyz(t)
	if status != http.StatusOK || body.Channels != 1 || body.Clients != 1 {
		t.Fatalf("a serving relay answered %d %+v, want 200 with one channel and one client", status, body)
	}

	r.Lifecycle.BeginDrain()
	status, body = r.readyz(t)
	if status != http.StatusServiceUnavailable || body.Status != StatusDraining {
		t.Fatalf("a draining relay answered %d %+v, want 503 draining", status, body)
	}
	// The counts are still real while draining -- an operator watching a
	// rolling restart reads them to see the channels fall to zero.
	if body.Channels != 1 {
		t.Errorf("a draining relay reported %d channels, want the 1 it still holds", body.Channels)
	}

	// /healthz stays 200 THROUGHOUT, and that is the distinction: liveness
	// must not fail during a drain, or a supervisor restarts the process
	// mid-teardown and defeats it.
	if code := r.healthz(t); code != http.StatusOK {
		t.Errorf("/healthz answered %d while draining, want 200", code)
	}
}

// A tune that arrives after the gate is up is refused 503, before any
// control-plane call.
//
// BOTH halves: the status AND the absence of a next-source call, because a
// relay that reserved a provider slot and then refused the viewer would leave
// Django holding a slot nothing will release.
func TestATuneArrivingDuringTheDrainIsRefusedBeforeAnythingIsReserved(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	r.Lifecycle.BeginDrain()

	before := len(r.Control.RequestsTo("/next-source"))
	header := http.Header{}
	response := r.tune(t, "/proxy/ts/stream/c-late", header)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("a tune during the drain answered %d, want 503", response.StatusCode)
	}
	if got := response.Header.Get("Retry-After"); got == "" {
		t.Errorf("the refusal carries no Retry-After: a client has nothing to tell it to retry")
	}
	if after := len(r.Control.RequestsTo("/next-source")); after != before {
		t.Errorf("the refused tune still made %d next-source calls", after-before)
	}
}

// The whole sequence over a real manager, a real client and a real emitter.
//
// THE CLOCK STARTS BEFORE THE DRAIN DOES, which is the property this
// assertion needs: `started` is taken before Run is called, not inside it,
// so the measurement cannot miss time the drain's own setup spent.
func TestTheDrainStopsTheChannelEndsTheClientAndFlushesTheEvents(t *testing.T) {
	r := fanRig(t, relaytest.Config{}, nil)
	response := r.tuneAs(t, "c-drain", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 10)
	waitForHead(t, r, "c-drain", 1)

	started := time.Now()
	elapsed := drain.Run(drain.Deps{
		Gate:     r.Lifecycle,
		Channels: r.Manager,
		Events:   r.Emitter,
		// No Server: the rig's httptest server is torn down by its own
		// cleanup, and Shutdown on it would race that.
		ClientGrace: 100 * time.Millisecond,
		Budget:      6 * time.Second,
	})
	measured := time.Since(started)

	if measured > 6*time.Second {
		t.Fatalf("the drain took %s against a 6s budget", measured)
	}
	if elapsed < 100*time.Millisecond {
		t.Errorf("the drain reported %s, which is less than the client grace it was given: "+
			"the grace was skipped", elapsed)
	}
	if r.Manager.Get("c-drain") != nil {
		t.Fatalf("the channel is still running after the drain")
	}

	// The client's response body ENDS rather than hanging: the ring closed,
	// serveClient returned, and the chunked response was terminated.
	done := make(chan error, 1)
	go func() {
		_, err := io.Copy(io.Discard, response.Body)
		done <- err
	}()
	select {
	case <-done:
	case <-time.After(10 * time.Second):
		t.Fatalf("the client's response never ended after the drain")
	}

	// channel_stop reached the control plane, which is what the flush is
	// for: it is raised by the teardown the drain performs, so an emitter
	// closed before the teardown would lose it.
	stops := r.Control.EventsOfType("channel_stop")
	if len(stops) != 1 {
		t.Fatalf("the control plane saw %d channel_stop events, want 1: the flush runs AFTER "+
			"the teardown for exactly this reason", len(stops))
	}
	if stops[0].ChannelID != "c-drain" {
		t.Errorf("channel_stop named %q", stops[0].ChannelID)
	}
	runtime, ok := stops[0].Details["runtime"].(float64)
	if !ok || runtime < 0 {
		t.Errorf("channel_stop carries runtime %v, want the rounded seconds "+
			"_collect_channel_stop_event_data computes", stops[0].Details["runtime"])
	}
	if _, ok := stops[0].Details["total_bytes"]; !ok {
		t.Errorf("channel_stop carries no total_bytes")
	}
}

// readyz calls GET /readyz and decodes the body.
func (r *rig) readyz(t *testing.T) (int, readyPayload) {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+"/readyz", nil)
	if err != nil {
		t.Fatalf("building the readyz request: %v", err)
	}
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("GET /readyz: %v", err)
	}
	defer func() { _ = response.Body.Close() }()
	var body readyPayload
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("decoding the readyz body: %v", err)
	}
	return response.StatusCode, body
}

func (r *rig) healthz(t *testing.T) int {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+"/healthz", nil)
	if err != nil {
		t.Fatalf("building the healthz request: %v", err)
	}
	response, err := r.Relay.Client().Do(request)
	if err != nil {
		t.Fatalf("GET /healthz: %v", err)
	}
	defer func() { _ = response.Body.Close() }()
	_, _ = io.Copy(io.Discard, response.Body)
	return response.StatusCode
}
```

### Appendix AH — `docker/healthcheck.sh` (committed mode **100755**)

Constraint 52. Role-aware, reading the role `entrypoint.sh` writes, and exiting 0 for a role with no `relay-go` to probe.

**THE MODE IS PART OF THE FILE.** `git ls-files -s docker/healthcheck.sh` must print `100755`; a plan appendix is text and carries no mode, so Task 8 Step 9 runs `chmod +x` before staging. The `HEALTHCHECK` also names the interpreter (`["/bin/sh", …]`) so that a lost mode bit cannot silently disable the probe — measured in a container: bare exec form at 0644 gives exit −1 and `OCI runtime exec failed`, the interpreter form at the same 0644 runs and gives exit 7. Break-check 23.

**`docker/healthcheck.sh`**

```bash
#!/bin/sh
# The container HEALTHCHECK. Spec D6 pairs the Go relay's /healthz with one,
# and 2c-1 deliberately did not add it -- "a probe wired to a /readyz that is
# a static 200 would report healthy through every real failure the probe
# exists to catch."
#
# ROLE-AWARE, because the image runs four different program sets. relay-go is
# started by the `all`, `all-dev` and `relay` rungs only (see
# docker/supervisord/*.conf); an `api` or `worker` container has no relay-go
# to probe, and probing one anyway would mark every such container unhealthy
# for ever.
#
# The role is read from the file entrypoint.sh writes AFTER it resolves the
# default, not from the environment: HEALTHCHECK runs as a fresh process with
# the container's env, which carries DISPATCHARR_ROLE only when the operator
# set it explicitly. The env var is the fallback, and an unreadable role is
# treated as "not a relay" -- a healthcheck must never fail because it could
# not work out what to check.
set -eu

ROLE_FILE=/run/dispatcharr-role
if [ -r "$ROLE_FILE" ]; then
    ROLE="$(cat "$ROLE_FILE")"
else
    ROLE="${DISPATCHARR_ROLE:-}"
fi

case "$ROLE" in
    all | relay) ;;
    *) exit 0 ;;
esac

PORT="${DISPATCHARR_RELAY_GO_PORT:-5658}"
exec curl -fsS --max-time 3 -o /dev/null "http://127.0.0.1:${PORT}/healthz"
```

### Appendix AI — `relay/main.go`

One `Lifecycle` shared three ways, the signal handler installed before `ListenAndServe`, and the wait after it -- which is what keeps the last `channel_stop` of a shutdown.

**`relay/main.go`**

```diff
--- a/main.go
+++ b/main.go
@@ -11,12 +11,15 @@
 	"net"
 	"net/http"
 	"os"
+	"os/signal"
 	"strconv"
+	"syscall"
 	"time"
 
 	"github.com/D10Scot/Dispatcharr/relay/channel"
 	"github.com/D10Scot/Dispatcharr/relay/config"
 	"github.com/D10Scot/Dispatcharr/relay/control"
+	"github.com/D10Scot/Dispatcharr/relay/drain"
 	"github.com/D10Scot/Dispatcharr/relay/httpapi"
 )
 
@@ -53,16 +56,21 @@
 		Events:  httpapi.EventSink(emitter),
 		Release: httpapi.ReleaseVia(client, slog.Default()),
 	})
+	// ONE Lifecycle, shared by the tune path, /readyz and the drain. Two
+	// would let the probe say "ready" while the handler refused every tune.
+	lifecycle := &httpapi.Lifecycle{}
 	srv := &http.Server{
 		Addr: net.JoinHostPort("0.0.0.0", strconv.Itoa(cfg.Port)),
 		Handler: httpapi.New(httpapi.Config{
 			DevRoutes: cfg.DevRoutes,
 			Stream: httpapi.StreamDeps{
-				Secret:   cfg.Secret,
-				Channels: channels,
-				Control:  client,
+				Secret:    cfg.Secret,
+				Channels:  channels,
+				Control:   client,
+				Lifecycle: lifecycle,
 			},
 			Control: httpapi.ControlDeps{Secret: cfg.Secret, Channels: channels},
+			Health:  httpapi.HealthDeps{Channels: channels, Lifecycle: lifecycle},
 		}).Handler(),
 
 		// ReadHeaderTimeout only. A read or write deadline on the whole
@@ -83,13 +91,33 @@
 		IdleTimeout: 120 * time.Second,
 	}
 
-	// No graceful shutdown here. D6's SIGTERM drain is 2c-8's, and a
-	// half-implemented drain -- one that stops accepting but does not wait for
-	// anything, because there is nothing to wait for yet -- would look like
-	// the feature while being the default. supervisord's stopwaitsecs=20
-	// bounds the stop either way.
+	// D6's drain. The handler is installed BEFORE ListenAndServe, so a
+	// SIGTERM that arrives during startup is still drained rather than
+	// killing the process with channels running -- supervisord sends one the
+	// moment a `docker stop` lands, which can be inside startsecs=5.
+	signals := make(chan os.Signal, 1)
+	signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
+	drained := make(chan struct{})
+	go func() {
+		defer close(drained)
+		sig := <-signals
+		log.Printf("received %s, draining", sig)
+		drain.Run(drain.Deps{
+			Gate:     lifecycle,
+			Channels: channels,
+			Server:   srv,
+			Events:   emitter,
+			Log:      slog.Default(),
+		})
+	}()
+
 	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
 		log.Printf("server stopped: %v", err) // credential-logging: ok - a net.Listen or Serve error naming the bind address
 		os.Exit(1)
 	}
+	// ErrServerClosed means Shutdown was called, which only the drain does,
+	// so wait for the rest of its sequence -- the emitter flush in
+	// particular, which runs AFTER Shutdown returns. Exiting here would drop
+	// every channel_stop of the shutdown.
+	<-drained
 }
```

### Appendix AJ — `relay/httpapi/server_test.go` and `stream_test.go`

2c-1's health test, rewritten for the split, and the rig's `Lifecycle` field. `stream_test.go` also carries three of the five narrowed request-count assertions (Task 4 Step 5).

**`relay/httpapi/server_test.go`**

```diff
--- a/httpapi/server_test.go
+++ b/httpapi/server_test.go
@@ -1,6 +1,7 @@
 package httpapi
 
 import (
+	"encoding/json"
 	"net/http"
 	"net/http/httptest"
 	"testing"
@@ -9,18 +10,43 @@
 // Drives the real mux and asserts what a client would see. A test that built
 // its own http.HandlerFunc and asserted it was called would pass with this
 // whole package deleted.
+// The two endpoints answer 200 and they answer DIFFERENTLY, which is 2c-8's
+// change to 2c-1's shape: /healthz is still liveness and still the literal
+// "ok", and /readyz now reports something real (spec D6).
 func TestHealthEndpointsAnswer200(t *testing.T) {
 	srv := New(Config{DevRoutes: false})
-	for _, path := range []string{"/healthz", "/readyz"} {
-		rec := httptest.NewRecorder()
-		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, path, nil))
-		if rec.Code != http.StatusOK {
-			t.Errorf("GET %s = %d, want 200", path, rec.Code)
-		}
-		if got := rec.Body.String(); got != "ok\n" {
-			t.Errorf("GET %s body = %q, want %q", path, got, "ok\n")
-		}
+
+	rec := httptest.NewRecorder()
+	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/healthz", nil))
+	if rec.Code != http.StatusOK {
+		t.Errorf("GET /healthz = %d, want 200", rec.Code)
 	}
+	if got := rec.Body.String(); got != "ok\n" {
+		t.Errorf("GET /healthz body = %q, want %q", got, "ok\n")
+	}
+
+	rec = httptest.NewRecorder()
+	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/readyz", nil))
+	if rec.Code != http.StatusOK {
+		t.Errorf("GET /readyz = %d, want 200", rec.Code)
+	}
+	var body struct {
+		Status   string `json:"status"`
+		Channels int    `json:"channels"`
+		Clients  int    `json:"clients"`
+	}
+	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
+		t.Fatalf("GET /readyz body %q is not JSON: %v", rec.Body.String(), err)
+	}
+	if body.Status != StatusReady {
+		t.Errorf("GET /readyz status = %q, want %q", body.Status, StatusReady)
+	}
+	// Asserted as well as the status, because a body that reported only
+	// "ready" would be the static 200 under a new name -- which is exactly
+	// what 2c-1 refused to wire a HEALTHCHECK to.
+	if body.Channels != 0 || body.Clients != 0 {
+		t.Errorf("GET /readyz counted %d channels and %d clients on an empty relay", body.Channels, body.Clients)
+	}
 }
 
 // The health endpoints must not depend on the dev flag: a deployment with the
@@ -43,11 +69,41 @@
 // pass with the route registered and the handler erroring.
 func TestStreamRouteIsUnregisteredWithoutTheDevFlag(t *testing.T) {
 	srv := New(Config{DevRoutes: false})
-	rec := httptest.NewRecorder()
-	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/proxy/ts/stream/abc", nil))
-	if rec.Code != http.StatusNotFound {
-		t.Fatalf("GET /proxy/ts/stream/abc with DevRoutes=false = %d, want 404 (the route must not be registered at all)", rec.Code)
+
+	// EVERY GATED ROUTE, not just the first one. 2c-8 adds six -- the two XC
+	// live roots and the four control routes -- and one of them,
+	// GET /{username}/{password}/{channelID}, is the broadest pattern this
+	// relay has ever registered: three bare wildcards at the site root. The
+	// plan's opening claim is that this PR is inert in every deployment, and
+	// a test that checks one path of seven cannot carry it.
+	for _, tc := range []struct {
+		method, path string
+	}{
+		{http.MethodGet, "/proxy/ts/stream/abc"},
+		{http.MethodGet, "/live/user/pass/12345"},
+		{http.MethodGet, "/user/pass/12345"},
+		{http.MethodGet, "/proxy/relay/channels"},
+		{http.MethodGet, "/proxy/relay/channels/abc"},
+		{http.MethodDelete, "/proxy/relay/channels/abc/clients/client-a"},
+		{http.MethodPost, "/proxy/relay/channels/abc/advance"},
+	} {
+		rec := httptest.NewRecorder()
+		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), tc.method, tc.path, nil))
+		if rec.Code != http.StatusNotFound {
+			t.Errorf("%s %s with DevRoutes=false = %d, want 404 (the route must not be registered at all)",
+				tc.method, tc.path, rec.Code)
+		}
 	}
+
+	// And the two operational endpoints are still served, so "the mux is
+	// empty" cannot be what makes the seven above pass.
+	for _, path := range []string{"/healthz", "/readyz"} {
+		rec := httptest.NewRecorder()
+		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, path, nil))
+		if rec.Code != http.StatusOK {
+			t.Errorf("GET %s with DevRoutes=false = %d, want 200", path, rec.Code)
+		}
+	}
 }
 
 // ServeMux's method matching, asserted because it is doing real work here:
```

**`relay/httpapi/stream_test.go`**

```diff
--- a/httpapi/stream_test.go
+++ b/httpapi/stream_test.go
@@ -51,6 +51,10 @@
 	Control  *relaytest.ControlPlane
 	Manager  *channel.Manager
 	Emitter  *control.Emitter
+
+	// Lifecycle is the drain flag the tune path and /readyz share, so a test
+	// can raise it the way the SIGTERM handler does (2c-8).
+	Lifecycle *Lifecycle
 }
 
 // rigOption adjusts the StreamDeps the rig is built with, for the one thing a
@@ -106,10 +110,12 @@
 	t.Cleanup(emitter.Close)
 	t.Cleanup(manager.StopAll)
 
+	lifecycle := &Lifecycle{}
 	stream := StreamDeps{
-		Secret:   testSecret,
-		Channels: manager,
-		Control:  client,
+		Secret:    testSecret,
+		Channels:  manager,
+		Control:   client,
+		Lifecycle: lifecycle,
 	}
 	for _, opt := range opts {
 		opt(&stream)
@@ -121,11 +127,15 @@
 		// an empty map while the tune path filled another, and every assertion
 		// about what the list shows would be about the wrong object.
 		Control: ControlDeps{Secret: testSecret, Channels: manager},
+		Health:  HealthDeps{Channels: manager, Lifecycle: lifecycle},
 	})
 	relay := httptest.NewServer(server.Handler())
 	t.Cleanup(relay.Close)
 
-	return &rig{Relay: relay, Upstream: upstream, Control: controlPlane, Manager: manager, Emitter: emitter}
+	return &rig{
+		Relay: relay, Upstream: upstream, Control: controlPlane,
+		Manager: manager, Emitter: emitter, Lifecycle: lifecycle,
+	}
 }
 
 func (r *rig) tune(t *testing.T, path string, header http.Header) *http.Response {
@@ -242,9 +252,9 @@
 		t.Fatalf("reading the stream: %v", err)
 	}
 
-	seen := rig.Control.Requests()
+	seen := rig.Control.RequestsTo("/next-source")
 	if len(seen) != 1 {
-		t.Fatalf("the control plane saw %d calls, want 1", len(seen))
+		t.Fatalf("the control plane saw %d next-source calls, want 1", len(seen))
 	}
 	if !strings.HasSuffix(seen[0].Path, "/a-channel-uuid/next-source") {
 		t.Fatalf("the call went to %s", seen[0].Path)
@@ -347,9 +357,9 @@
 	})
 	defer func() { _ = response.Body.Close() }()
 
-	seen := rig.Control.Requests()
+	seen := rig.Control.RequestsTo("/next-source")
 	if len(seen) != 1 {
-		t.Fatalf("the control plane saw %d calls, want 1", len(seen))
+		t.Fatalf("the control plane saw %d next-source calls, want 1", len(seen))
 	}
 	if !strings.Contains(seen[0].Path, "from-the-path") {
 		t.Fatalf("the tune asked about %s: an unverified X-Relay-Channel was believed", seen[0].Path)
@@ -364,9 +374,9 @@
 	})
 	defer func() { _ = response.Body.Close() }()
 
-	seen := rig.Control.Requests()
+	seen := rig.Control.RequestsTo("/next-source")
 	if len(seen) != 1 {
-		t.Fatalf("the control plane saw %d calls, want 1", len(seen))
+		t.Fatalf("the control plane saw %d next-source calls, want 1", len(seen))
 	}
 	if !strings.Contains(seen[0].Path, "from-the-header") {
 		t.Fatalf("the tune asked about %s: the authorize hop's resolved channel was ignored", seen[0].Path)
```

### Appendix AK — `relay/control/events.go`

Ruling R10. `Emit` drops an event raised after `Close`; `Close` is idempotent.

**`relay/control/events.go`**

```diff
--- a/control/events.go
+++ b/control/events.go
@@ -89,8 +89,9 @@
 	queue chan Event
 	done  chan struct{}
 
-	mu   sync.Mutex
-	down bool
+	mu     sync.Mutex
+	down   bool
+	closed bool
 }
 
 // EmitterQueueDepth is how many events may wait for the worker. At one
@@ -115,8 +116,24 @@
 }
 
 // Emit queues one event. It never blocks and never fails: a full queue is
-// logged and the event dropped.
+// logged and the event dropped, and so is an event raised after Close.
+//
+// THE CLOSED CHECK IS 2c-8'S AND IT CLOSES A PANIC, not a tidiness gap. The
+// SIGTERM drain calls Close, and a client goroutine that is still unwinding
+// raises client_disconnect as it returns -- a send on a closed channel, which
+// panics the goroutine serving that client. Found by
+// TestTheDrainStopsTheChannelEndsTheClientAndFlushesTheEvents, which panicked
+// with "send on closed channel" on its first run. Dropping such an event is
+// the right answer and the one this type already gives for a full queue:
+// control_plane.py's own contract is that an event raised during an outage is
+// lost, not queued.
 func (e *Emitter) Emit(event Event) {
+	e.mu.Lock()
+	defer e.mu.Unlock()
+	if e.closed {
+		e.log.Debug("relay event dropped: the emitter is closed", "type", event.Type, "channel", event.ChannelID)
+		return
+	}
 	select {
 	case e.queue <- event:
 	default:
@@ -125,10 +142,23 @@
 }
 
 // Close stops the worker once the queue has drained. It is what the SIGTERM
-// drain (2c-8) will call; tests call it to know every posted batch has been
-// recorded by the fake.
+// drain calls (relay/drain), and what tests call to know every posted batch
+// has been recorded by the fake.
+//
+// IDEMPOTENT, also 2c-8's: the drain closes the emitter and so does a test's
+// own cleanup, and a second close(e.queue) panics. A second call waits for
+// the worker exactly as the first does, so a caller cannot return before the
+// flush either way.
 func (e *Emitter) Close() {
+	e.mu.Lock()
+	if e.closed {
+		e.mu.Unlock()
+		<-e.done
+		return
+	}
+	e.closed = true
 	close(e.queue)
+	e.mu.Unlock()
 	<-e.done
 }
 
```

### Appendix AL — `relay/control/events_test.go`

The mechanism pin, which the drain test could not carry because `net/http` recovers a panic in a request goroutine.

**`relay/control/events_test.go`**

```diff
--- a/control/events_test.go
+++ b/control/events_test.go
@@ -196,3 +196,41 @@
 }
 
 var _ = errors.Is
+
+// An event raised after Close is DROPPED, and Close twice is a no-op.
+//
+// BOTH ARE PANICS WITHOUT THE GUARD, and both are reachable from the SIGTERM
+// drain: it closes the emitter while a client goroutine is still unwinding
+// and raising client_disconnect (a send on a closed channel), and a test's
+// own cleanup closes an emitter the drain already closed (a second close).
+//
+// PINNED HERE RATHER THAN THROUGH THE DRAIN, deliberately: the drain test
+// that first produced the panic no longer reproduces it, because net/http
+// RECOVERS a panic in the goroutine serving a request -- the test saw
+// "http: panic serving" in the log and still passed. A recovered panic that
+// kills one viewer's connection and nothing else is exactly the failure a
+// test asserting an outcome cannot see, so this asserts the mechanism.
+func TestTheEmitterDropsEventsRaisedAfterCloseAndCloseIsIdempotent(t *testing.T) {
+	fake := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{})
+	t.Cleanup(fake.Close)
+	emitter := NewEmitter(&Client{Secret: testSecret, BaseURL: fake.URL()}, nil)
+
+	emitter.Emit(Event{Type: "channel_start", ChannelID: "c-1"})
+	emitter.Close()
+
+	// The drain's own shape: the queue is closed and a goroutine still
+	// unwinding raises one more.
+	emitter.Emit(Event{Type: "client_disconnect", ChannelID: "c-1"})
+	// And the second Close a test's cleanup makes.
+	emitter.Close()
+
+	// The event raised BEFORE the close was delivered, so "nothing is ever
+	// delivered" cannot be what makes this pass.
+	if got := fake.EventsOfType("channel_start"); len(got) != 1 {
+		t.Fatalf("the control plane saw %d channel_start events, want 1", len(got))
+	}
+	if got := fake.EventsOfType("client_disconnect"); len(got) != 0 {
+		t.Errorf("an event raised after Close was delivered (%d): the queue is closed and "+
+			"control_plane.py's own contract is that such an event is LOST", len(got))
+	}
+}
```

### Appendix AM — `docs/relay-parity-matrix.md`

**A `git diff` hunk, not an instruction.** Twenty-three lines change and nothing is added or removed: thirteen rows' `Pin` cells grow (Amendment A2.2: a Go pin is a reference appended to the existing cell, not a new column), and **ten of those thirteen also get a clause in their `Notes` cell**. It is a hunk rather than prose because prose was tried on this exact file and failed: a reviewer applying "append one reference inside the same cell" produced a **six-cell row**, which the guard rejects. Read the HTML comment at the top of that file before touching it — one row is one line, cells are never padded, and no Markdown formatter may be run over it — and then let `git apply` do the edit.

**THE NOTES CLAUSE IS NOT DECORATION.** Ten of the thirteen rows are authorize-matrix rows whose decisions are Django's and stay Django's; the relay's whole share is to ask the complete question and obey the answer exactly, which is what the named Go test pins. `Notes` is where a reader learns what a pin covers, so leaving that to the PR description would let the next reader conclude that a Go test now decides who may watch what. Rows 15 and 21 take a different clause from the other eight, because on the XC path the relay's share is larger — one authorization per tune, and the hop's resolved channel served rather than the numeric path id.

**Captured against `d6d71f97`, and it WAS re-captured**: the first version of this hunk was taken on `eb7fac07`, and row 11 has gained a Go pin and Notes of its own since, which moved the context around row 11's block. The prediction that it "probably survives" was wrong, which is why Task 9 Step 0 checks rather than assumes.

```diff
diff --git a/docs/relay-parity-matrix.md b/docs/relay-parity-matrix.md
index 79f10bbb..884a54af 100644
--- a/docs/relay-parity-matrix.md
+++ b/docs/relay-parity-matrix.md
@@ -169,25 +169,25 @@ PR's first, which is the distance git needs to merge them cleanly.
 <!-- block: owed by 2a-6 -->
 | 12 | The fMP4 generator's `_is_timeout()` disconnects a client on elapsed time since its last fragment alone — no stream-health check, no `url_switching` exemption and no keepalive — so an fMP4 viewer is dropped `stream_timeout + failover_grace_period` (40s by default) into a stall that leaves a TS viewer on the same channel connected | `apps/proxy/live_proxy/output/fmp4/generator.py:339-346`, `apps/proxy/live_proxy/output/ts/generator.py:574-595`, `apps/proxy/live_proxy/output/ts/generator.py:311-312`, `apps/proxy/live_proxy/output/ts/generator.py:366-389` | `apps/proxy/live_proxy/tests/test_fmp4_client_timeout.py::FMP4ClientTimeoutTests::test_a_stalled_fmp4_client_is_dropped_while_a_ts_client_is_not`, `relay/httpapi/fmp4_test.go::TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot` | Filed as [#222](https://github.com/D10Scot/Dispatcharr/issues/222) and reproduced, not fixed, per spec D5 (preserve known defects rather than silently fix during the port); also recorded in CLAUDE.md's Known defects. The row's original wording named only the `url_switching` clause; 2a-6 found the TS generator's `_is_timeout()` needs BOTH 40s of no yielded data AND the stream manager unhealthy before it even reaches that clause, and that the keepalive path (below) refreshes `last_yield_time` on every packet it sends whenever a client sits at the buffer head on an unhealthy stream — exactly the condition that would otherwise reach it — so the `url_switching` exemption is practically shadowed by the keepalive mechanism regardless of how long that window itself runs. The reachable divergence is larger: the TS generator disconnects only an unhealthy stream and, before that, sends keepalives that refresh `last_yield_time` for up to `MAX_KEEPALIVE_DURATION` (300s), which the fMP4 generator has no equivalent of. The pin drives the reachable form; the `url_switching` clause is carried in the citations, not tested. This widens the row rather than narrowing it — the original wording described a race a viewer would almost never lose, and the reality is a disconnect on every sustained stall — and it changes the description only: `_is_timeout()` is untouched, D5 still says reproduce rather than fix, and 2c-6 is held to the drop. |
 <!-- block: owed by 2a-5 -->
-| 14 | Status payload field types differ by endpoint: `owner` is `null` on the list endpoint and the literal string `unknown` on the detail endpoint, `ffmpeg_speed` is a float on both, and `source_fps` is a float on list but a string on detail | `apps/proxy/live_proxy/channel_status.py:45`, `apps/proxy/live_proxy/channel_status.py:460`, `apps/proxy/live_proxy/channel_status.py:339`, `apps/proxy/live_proxy/channel_status.py:595`, `apps/proxy/live_proxy/channel_status.py:376`, `apps/proxy/live_proxy/channel_status.py:599`, `apps/proxy/relay_serializers.py:59`, `apps/proxy/relay_serializers.py:129`, `apps/proxy/relay_serializers.py:60`, `apps/proxy/relay_serializers.py:136` | `apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_owner_is_the_string_unknown_on_detail_and_null_on_list`, `apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_source_fps_is_a_string_on_detail_and_a_float_on_list`, `apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_ffmpeg_speed_is_a_float_on_both_endpoints` | Neither serializer supplies a `default=`, so the builder's value reaches the wire unchanged. A test that checks the string against only one of the two endpoints proves nothing about the other |
-| 15 | `stream_xc` authorizes once and passes its `decision` into `stream_ts`, so an XC tune is not authorized twice and does not mint a second client id for one connection | `apps/proxy/live_proxy/views.py:162-166`, `apps/proxy/live_proxy/views.py:825`, `apps/proxy/live_proxy/views.py:845-851` | `apps/proxy/live_proxy/tests/test_xc_decision_handoff.py::test_an_xc_tune_is_not_re_authorized_as_an_anonymous_live_tune` | `stream_ts`'s `if decision is None:` guard only re-runs `resolve_authorization` when called directly, not via `stream_xc`; `stream_xc` calls `resolve_authorization` itself and passes the result straight through. The second clause -- no second client id -- has no externally observable consequence and is recorded, not pinned; the pin is the anonymous-re-authorization case, which 403s without the hand-off |
-| 16 | `/proxy/ts/stream/<stream_hash>` — the admin single-stream preview, with no channel at all — applies the STREAMS ACL and the per-user stream limit when a principal resolved, and no channel check of any kind, because there is no channel to check | `apps/proxy/next_source.py:69-79`, `apps/proxy/authorize.py:340-349`, `apps/proxy/authorize.py:425-442` | `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_a_stream_hash_tune_applies_no_channel_check` | `_resolve_channel` returns `(None, True)` for the hash case, since `get_stream_object` returns a `Stream`, not a `Channel`; the caller only runs `_apply_channel_checks` when `channel is not None`, so the hash case skips it entirely while the ACL check and stream-limit check above it still run unconditionally |
-| 17 | `ip_address` on both status endpoints is the real client address — resolved once by the authorize hop via `get_client_ip()` and carried on `X-Relay-Client-IP` when nginx authorized the tune, resolved inline otherwise | `dispatcharr/utils.py:342-370`, `apps/proxy/authorize.py:486-503`, `apps/proxy/live_proxy/views.py:195-206`, `apps/proxy/live_proxy/client_manager.py:215-243`, `apps/proxy/relay_serializers.py:29`, `apps/proxy/relay_serializers.py:79` | `apps/proxy/live_proxy/tests/test_client_ip_provenance.py::test_ip_address_is_the_real_client_address_on_both_status_endpoints` | 2b-2 made the hop the source; the invariant this row pins is that `ip_address` stays the real client address across that change, which is why the pin asserts a value and never a mechanism. Two tests in the pinned file: the untrusted path honours `X-Forwarded-For`, the trusted path prefers the hop's header over a different forwarded address |
-| 19 | Authorize matrix — **Internal** principal (DVR, any caller with a valid `X-Dispatcharr-Internal`): the STREAMS ACL applies; `user_level`, profile membership, `hidden_from_output`, adult filtering and the stream limit are all bypassed | `apps/proxy/authorize.py:309-310`, `apps/proxy/authorize.py:376-377`, `apps/proxy/authorize.py:425-426`, `apps/proxy/authorize.py:436-442` | `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_the_internal_principal_streams_a_channel_hidden_from_output`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_the_internal_principal_is_still_subject_to_the_streams_acl` | No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13 |
-| 20 | Authorize matrix — **Admin** (`user_level >= 10`, any authenticator): ACL applies, every channel check bypassed, the stream limit still enforced | `apps/proxy/authorize.py:379-385`, `apps/proxy/authorize.py:425-426`, `apps/proxy/authorize.py:436-442` | `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_admin_streams_a_channel_hidden_from_output`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_admin_streams_an_adult_channel_despite_hide_adult_content`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_terminates_the_held_client_and_admits_the_new_tune` | No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13 |
-| 23 | Authorize matrix — **Session**, non-admin: every check enforced | `apps/proxy/authorize.py:268-276`, `apps/proxy/authorize.py:420-442` | `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_a_session_principal_streams_an_ordinary_channel`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_a_session_principal_is_refused_a_hidden_channel` | No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13. `_session_user` reads the session directly rather than `http_request.user`, for the reason its own docstring gives |
-| 25 | Authorize matrix — **Stream-by-hash** (`/proxy/ts/stream/<stream_hash>`), any principal: the ACL applies and the stream limit is enforced when a principal resolved; no channel check applies | `apps/proxy/next_source.py:69-79`, `apps/proxy/authorize.py:420-442` | `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_a_stream_hash_tune_applies_no_channel_check`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_terminates_the_held_client_and_admits_the_new_tune`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_refuses_when_termination_is_disabled` | No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13 |
+| 14 | Status payload field types differ by endpoint: `owner` is `null` on the list endpoint and the literal string `unknown` on the detail endpoint, `ffmpeg_speed` is a float on both, and `source_fps` is a float on list but a string on detail | `apps/proxy/live_proxy/channel_status.py:45`, `apps/proxy/live_proxy/channel_status.py:460`, `apps/proxy/live_proxy/channel_status.py:339`, `apps/proxy/live_proxy/channel_status.py:595`, `apps/proxy/live_proxy/channel_status.py:376`, `apps/proxy/live_proxy/channel_status.py:599`, `apps/proxy/relay_serializers.py:59`, `apps/proxy/relay_serializers.py:129`, `apps/proxy/relay_serializers.py:60`, `apps/proxy/relay_serializers.py:136` | `apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_owner_is_the_string_unknown_on_detail_and_null_on_list`, `apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_source_fps_is_a_string_on_detail_and_a_float_on_list`, `apps/proxy/live_proxy/tests/test_relay_status_wire.py::test_ffmpeg_speed_is_a_float_on_both_endpoints`, `relay/httpapi/detail_golden_test.go::TestOwnerAndSourceFPSDifferBetweenTheTwoEndpoints` | Neither serializer supplies a `default=`, so the builder's value reaches the wire unchanged. A test that checks the string against only one of the two endpoints proves nothing about the other |
+| 15 | `stream_xc` authorizes once and passes its `decision` into `stream_ts`, so an XC tune is not authorized twice and does not mint a second client id for one connection | `apps/proxy/live_proxy/views.py:162-166`, `apps/proxy/live_proxy/views.py:825`, `apps/proxy/live_proxy/views.py:845-851` | `apps/proxy/live_proxy/tests/test_xc_decision_handoff.py::test_an_xc_tune_is_not_re_authorized_as_an_anonymous_live_tune`, `relay/httpapi/xc_test.go::TestAnXCTuneServesTheHopsChannelAndAuthorizesOnce` | `stream_ts`'s `if decision is None:` guard only re-runs `resolve_authorization` when called directly, not via `stream_xc`; `stream_xc` calls `resolve_authorization` itself and passes the result straight through. The second clause -- no second client id -- has no externally observable consequence and is recorded, not pinned; the pin is the anonymous-re-authorization case, which 403s without the hand-off The Go pin covers the RELAY's share of this row and not the decision: one authorization per XC tune, and the channel the hop resolved served rather than the numeric path id, which the relay cannot map to a uuid without the ORM query spec D2 forbids. The decision itself is Django's. |
+| 16 | `/proxy/ts/stream/<stream_hash>` — the admin single-stream preview, with no channel at all — applies the STREAMS ACL and the per-user stream limit when a principal resolved, and no channel check of any kind, because there is no channel to check | `apps/proxy/next_source.py:69-79`, `apps/proxy/authorize.py:340-349`, `apps/proxy/authorize.py:425-442` | `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_a_stream_hash_tune_applies_no_channel_check`, `relay/httpapi/authorize_test.go::TestAnUntrustedTuneAsksDjangoAndSendsTheQuestionInTheBody` | `_resolve_channel` returns `(None, True)` for the hash case, since `get_stream_object` returns a `Stream`, not a `Channel`; the caller only runs `_apply_channel_checks` when `channel is not None`, so the hash case skips it entirely while the ACL check and stream-limit check above it still run unconditionally The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
+| 17 | `ip_address` on both status endpoints is the real client address — resolved once by the authorize hop via `get_client_ip()` and carried on `X-Relay-Client-IP` when nginx authorized the tune, resolved inline otherwise | `dispatcharr/utils.py:342-370`, `apps/proxy/authorize.py:486-503`, `apps/proxy/live_proxy/views.py:195-206`, `apps/proxy/live_proxy/client_manager.py:215-243`, `apps/proxy/relay_serializers.py:29`, `apps/proxy/relay_serializers.py:79` | `apps/proxy/live_proxy/tests/test_client_ip_provenance.py::test_ip_address_is_the_real_client_address_on_both_status_endpoints`, `relay/httpapi/control_test.go::TestTheDetailEndpointRendersARunningChannel` | 2b-2 made the hop the source; the invariant this row pins is that `ip_address` stays the real client address across that change, which is why the pin asserts a value and never a mechanism. Two tests in the pinned file: the untrusted path honours `X-Forwarded-For`, the trusted path prefers the hop's header over a different forwarded address |
+| 19 | Authorize matrix — **Internal** principal (DVR, any caller with a valid `X-Dispatcharr-Internal`): the STREAMS ACL applies; `user_level`, profile membership, `hidden_from_output`, adult filtering and the stream limit are all bypassed | `apps/proxy/authorize.py:309-310`, `apps/proxy/authorize.py:376-377`, `apps/proxy/authorize.py:425-426`, `apps/proxy/authorize.py:436-442` | `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_the_internal_principal_streams_a_channel_hidden_from_output`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_the_internal_principal_is_still_subject_to_the_streams_acl`, `relay/httpapi/authorize_test.go::TestInternalTravelsFromTheClientsMarkerAndNotTheTransports` | No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13 The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
+| 20 | Authorize matrix — **Admin** (`user_level >= 10`, any authenticator): ACL applies, every channel check bypassed, the stream limit still enforced | `apps/proxy/authorize.py:379-385`, `apps/proxy/authorize.py:425-426`, `apps/proxy/authorize.py:436-442` | `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_admin_streams_a_channel_hidden_from_output`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_admin_streams_an_adult_channel_despite_hide_adult_content`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_terminates_the_held_client_and_admits_the_new_tune`, `relay/httpapi/authorize_test.go::TestAnUntrustedTuneAsksDjangoAndSendsTheQuestionInTheBody` | No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13 The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
+| 23 | Authorize matrix — **Session**, non-admin: every check enforced | `apps/proxy/authorize.py:268-276`, `apps/proxy/authorize.py:420-442` | `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_a_session_principal_streams_an_ordinary_channel`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_a_session_principal_is_refused_a_hidden_channel`, `relay/httpapi/authorize_test.go::TestAnUntrustedTuneAsksDjangoAndSendsTheQuestionInTheBody` | No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13. `_session_user` reads the session directly rather than `http_request.user`, for the reason its own docstring gives The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
+| 25 | Authorize matrix — **Stream-by-hash** (`/proxy/ts/stream/<stream_hash>`), any principal: the ACL applies and the stream limit is enforced when a principal resolved; no channel check applies | `apps/proxy/next_source.py:69-79`, `apps/proxy/authorize.py:420-442` | `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_a_stream_hash_tune_applies_no_channel_check`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_terminates_the_held_client_and_admits_the_new_tune`, `apps/proxy/live_proxy/tests/test_stream_by_hash_authorization.py::test_the_stream_limit_refuses_when_termination_is_disabled`, `relay/httpapi/authorize_test.go::TestADenialReachesTheViewerWithItsOwnStatus` | No test that PORTS pinned this principal before 2a-5: apps/proxy/tests/test_authorize.py's row classes call authorize_stream() directly through a RequestFactory and patch network_access_allowed, _drf_user and check_user_stream_limits, so they assert one Python function calling another — see ruling 13 The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
 <!-- block: closed by 2b-3 -->
-| 18 | What the status payload's `stream_name` and `m3u_profile_name` contain when the channel metadata hash was never written one | `apps/proxy/live_proxy/channel_status.py:74`, `apps/proxy/live_proxy/channel_status.py:106` | `apps/proxy/live_proxy/tests/test_zero_orm_reads.py::StatusNameFallbackTests::test_the_key_is_absent_when_redis_has_no_name_and_no_row_exists`, `apps/proxy/live_proxy/tests/test_zero_orm_reads.py::StatusNameFallbackTests::test_the_orm_fills_the_name_when_redis_has_none_and_the_row_exists` | 2b-3's answer: **absence is the contract.** The key is absent from the payload entirely — not null, not `''`, not the id — because `channel_status.py` only assigns it inside a truthy branch and `RelayChannelDetailSerializer` declares both `required=False`. Python's ORM fallback is best-effort enrichment on top of that: it fills the key when the row still exists and leaves it absent when the row is gone. The Go relay has no database and always omits it, which is inside the contract rather than a divergence from it. 2c: omit the key; never substitute null, `''` or the numeric id. The reads are NOT deleted — every name write in the tree guards the name on a value `url_utils.py:31-42`'s `tune_extras` degrades to `None` for a control plane that predates 2b-1, and the relay and control plane are separately deployable, so both fallbacks are reachable under version skew (`views.py:553-566` records it). They are allowlisted in `zero_orm_allowlist.py` and deleted wholesale in 2d. One production path defeats the repair rather than needing it — a degraded failover writes the new id and leaves the old name standing, so the key is present and wrong ([#265](https://github.com/D10Scot/Dispatcharr/issues/265)); that is a distinct defect from this row, cited not fixed. Coverage reads the two fallbacks as asymmetric (`:72-78` missing in 13/13, `:103-110` covered in 13/13) but that is one fixture's shape — `test_live_db_cleanup.py:322-344` supplies a `stream_name` and not an `m3u_profile_name`, mocks the query, and asserts nothing about either fallback. The spec and this row previously cited `:92`; 2b-1 moved it to `:106` |
+| 18 | What the status payload's `stream_name` and `m3u_profile_name` contain when the channel metadata hash was never written one | `apps/proxy/live_proxy/channel_status.py:74`, `apps/proxy/live_proxy/channel_status.py:106` | `apps/proxy/live_proxy/tests/test_zero_orm_reads.py::StatusNameFallbackTests::test_the_key_is_absent_when_redis_has_no_name_and_no_row_exists`, `apps/proxy/live_proxy/tests/test_zero_orm_reads.py::StatusNameFallbackTests::test_the_orm_fills_the_name_when_redis_has_none_and_the_row_exists`, `relay/httpapi/control_test.go::TestTheNamesComeOffTheWireAndAreAbsentWhenTheAnswerCarriedNone` | 2b-3's answer: **absence is the contract.** The key is absent from the payload entirely — not null, not `''`, not the id — because `channel_status.py` only assigns it inside a truthy branch and `RelayChannelDetailSerializer` declares both `required=False`. Python's ORM fallback is best-effort enrichment on top of that: it fills the key when the row still exists and leaves it absent when the row is gone. The Go relay has no database and always omits it, which is inside the contract rather than a divergence from it. 2c: omit the key; never substitute null, `''` or the numeric id. The reads are NOT deleted — every name write in the tree guards the name on a value `url_utils.py:31-42`'s `tune_extras` degrades to `None` for a control plane that predates 2b-1, and the relay and control plane are separately deployable, so both fallbacks are reachable under version skew (`views.py:553-566` records it). They are allowlisted in `zero_orm_allowlist.py` and deleted wholesale in 2d. One production path defeats the repair rather than needing it — a degraded failover writes the new id and leaves the old name standing, so the key is present and wrong ([#265](https://github.com/D10Scot/Dispatcharr/issues/265)); that is a distinct defect from this row, cited not fixed. Coverage reads the two fallbacks as asymmetric (`:72-78` missing in 13/13, `:103-110` covered in 13/13) but that is one fixture's shape — `test_live_db_cleanup.py:322-344` supplies a `stream_name` and not an `m3u_profile_name`, mocks the query, and asserts nothing about either fallback. The spec and this row previously cited `:92`; 2b-1 moved it to `:106` |
 <!-- block: already pinned -->
 | 10 | Multi-client upstream sharing: three clients on one channel share exactly one upstream connection, and closing every client releases it | `apps/proxy/live_proxy/server.py:629-648`, `apps/proxy/live_proxy/server.py:2017-2052` | `e2e/tests/streaming/shared-upstream.spec.ts::three clients share exactly one upstream connection`, `e2e/tests/streaming/shared-upstream.spec.ts::closing every client releases the upstream`, `apps/proxy/live_proxy/tests/test_relay_client_stream.py::ClientSetTests::test_the_client_set_from_three_sharing_clients_to_an_empty_channel`, `relay/httpapi/fanout_test.go::TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint`, `relay/channel/fanout_test.go::TestNClientsShareOneSourceAndTheChannelOutlivesAllButTheLast` | The row asserts two things, so it cites both tests in the same file: the first proves the sharing, the second proves the release. `initialize_channel` reuses the buffer/client manager when the channel is already active (`:629-648`); the cleanup loop's `last_client_disconnect`/`channel_shutdown_delay` timer stops it once every client has gone (`:2017-2052`). The harness test does not exercise either citation directly: it never closes its own clients (it stops the channel by operator command instead), so `:2017-2052`'s disconnect-driven teardown is not reached, and with `:637`'s reuse check patched out the test still passed, because `views.py:619-622` already short-circuits `initialize_channel` within one process. What it actually proves: three clients share one upstream request; an operator-issued stop ends every stream with the upstream's request count still 1, and no reconnect happens. Release-on-client-disconnect stays e2e-only, carried by the two `shared-upstream.spec.ts` references, which stand |
 | 11 | One transcode process runs per active `(channel, profile)` pair across the cluster: a second client on the same Output Profile attaches to the existing process's buffer instead of spawning its own | `apps/proxy/live_proxy/output/profile/manager.py:67-122`, `apps/proxy/live_proxy/output/profile/manager.py:312-321` | `e2e/tests/streaming-greybox/output-profile-sharing.spec.ts::two clients on one output profile share a single transcode`, `apps/proxy/live_proxy/tests/test_output_profile_sharing.py::OutputProfileSharingTests::test_two_clients_on_one_output_profile_share_a_single_transcode`, `relay/httpapi/profile_test.go::TestTwoClientsOnOneOutputProfileShareOneTranscode` | Ten AC3 clients cost one ffmpeg. 2a-6 added the second pin, an in-process harness test that counts SPAWNS of the profile's own command rather than surviving processes: the channel runs the locked Proxy stream profile, which spawns nothing, so every line in the spawn log is an Output Profile transcode. Both stand — the e2e spec proves the same claim through nginx in a container. Go column added in Phase 2 stage 2c-7, counting SPAWNS as the two Python pins do: with `Channel.AttachOutput`'s reuse branch disabled the registry assertion and both PID assertions stay green and only the count reddens. The Go relay reaches the same claim with one process and no owner lock — spec D2 deletes `output_owner`/`output_state`, so "across the cluster" becomes "in the one relay process" and the sharing is the registry's refcount. |
-| 21 | Authorize matrix — **XC credentials** (`<user>/<pass>` path segments, compared with `hmac.compare_digest`): every check enforced; `hidden_from_output` and adult filtering answer 403 | `apps/proxy/authorize.py:148-174`, `apps/proxy/authorize.py:420-442` | `e2e/tests/streaming/authorize-matrix.spec.ts::a hidden channel is refused on the XC live root to an ordinary XC user`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_xc_user_with_hide_adult_content_is_refused_on_the_live_root` | `resolve_xc_user` is the constant-time comparison CLAUDE.md's Known defects section already names. `hidden_from_output` is pinned on-path by the cited e2e test; the adult-filter half for this principal is now also pinned on-path by the cited Python test, a live-root equivalent to the catch-up-root test that used to be this row's only proof of it (drives `/timeshift/...`, off the matrix's live-path scope) |
-| 22 | Authorize matrix — **JWT / API key / query-param JWT**, non-admin: every check enforced | `apps/proxy/authorize.py:227-265`, `apps/proxy/authorize.py:420-442` | `e2e/tests/streaming/authorize-matrix.spec.ts::an adult channel is refused on the native stream route to a hide_adult_content viewer` | `_drf_user` runs the DRF authenticator set explicitly rather than relying on the calling view's own `authentication_classes`. Drives `/proxy/ts/stream/<uuid>` with an `X-API-Key` principal, in scope; the plan's first draft pinned this row to a catch-up test, which the matrix's own scope paragraph excludes |
-| 24 | Authorize matrix — **Anonymous** (a bare channel UUID): the ACL applies, `hidden_from_output` answers 403, and every user-scoped check is inapplicable — an anonymous request with a valid UUID still streams an ordinary channel | `apps/proxy/authorize.py:316`, `apps/proxy/authorize.py:325-327`, `apps/proxy/authorize.py:386-389` | `e2e/tests/streaming/authorize-matrix.spec.ts::a channel hidden from output is refused even to an anonymous request`, `e2e/tests/streaming/authorize-matrix.spec.ts::an ordinary channel still streams with no credential at all` | `hidden_from_output` is checked with no principal at all, which is why it is the one check anonymous also fails |
+| 21 | Authorize matrix — **XC credentials** (`<user>/<pass>` path segments, compared with `hmac.compare_digest`): every check enforced; `hidden_from_output` and adult filtering answer 403 | `apps/proxy/authorize.py:148-174`, `apps/proxy/authorize.py:420-442` | `e2e/tests/streaming/authorize-matrix.spec.ts::a hidden channel is refused on the XC live root to an ordinary XC user`, `apps/proxy/live_proxy/tests/test_authorize_matrix_over_http.py::test_an_xc_user_with_hide_adult_content_is_refused_on_the_live_root`, `relay/httpapi/xc_test.go::TestAnXCTuneServesTheHopsChannelAndAuthorizesOnce` | `resolve_xc_user` is the constant-time comparison CLAUDE.md's Known defects section already names. `hidden_from_output` is pinned on-path by the cited e2e test; the adult-filter half for this principal is now also pinned on-path by the cited Python test, a live-root equivalent to the catch-up-root test that used to be this row's only proof of it (drives `/timeshift/...`, off the matrix's live-path scope) The Go pin covers the RELAY's share of this row and not the decision: one authorization per XC tune, and the channel the hop resolved served rather than the numeric path id, which the relay cannot map to a uuid without the ORM query spec D2 forbids. The decision itself is Django's. |
+| 22 | Authorize matrix — **JWT / API key / query-param JWT**, non-admin: every check enforced | `apps/proxy/authorize.py:227-265`, `apps/proxy/authorize.py:420-442` | `e2e/tests/streaming/authorize-matrix.spec.ts::an adult channel is refused on the native stream route to a hide_adult_content viewer`, `relay/httpapi/authorize_test.go::TestAnUntrustedTuneAsksDjangoAndSendsTheQuestionInTheBody` | `_drf_user` runs the DRF authenticator set explicitly rather than relying on the calling view's own `authentication_classes`. Drives `/proxy/ts/stream/<uuid>` with an `X-API-Key` principal, in scope; the plan's first draft pinned this row to a catch-up test, which the matrix's own scope paragraph excludes The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
+| 24 | Authorize matrix — **Anonymous** (a bare channel UUID): the ACL applies, `hidden_from_output` answers 403, and every user-scoped check is inapplicable — an anonymous request with a valid UUID still streams an ordinary channel | `apps/proxy/authorize.py:316`, `apps/proxy/authorize.py:325-327`, `apps/proxy/authorize.py:386-389` | `e2e/tests/streaming/authorize-matrix.spec.ts::a channel hidden from output is refused even to an anonymous request`, `e2e/tests/streaming/authorize-matrix.spec.ts::an ordinary channel still streams with no credential at all`, `relay/httpapi/authorize_test.go::TestTheDecisionsValuesAreUsedRatherThanThePathAndTheSocket` | `hidden_from_output` is checked with no principal at all, which is why it is the one check anonymous also fails The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
 <!-- block: white-box-only -->
 | 26 | Not held to: the greenlet and OS-thread topology inside `server.py` — two module-level `threading.Thread(daemon=True)` supervisors plus a per-channel stream-manager thread, all sharing one OS thread with the request greenlets, and `_spawn_on_hub`'s cross-thread scheduling onto the gevent hub | `apps/proxy/live_proxy/server.py:161-171`, `apps/proxy/live_proxy/server.py:467`, `apps/proxy/live_proxy/server.py:851`, `apps/proxy/live_proxy/server.py:2192` | `white-box-only` | Deleted, not ported: the Go relay's concurrency model is goroutines and a `sync.RWMutex` (spec D2), and no client can observe which greenlet did what. `:467` and `:2192` are the two module-level supervisors (event listener, cleanup loop); `:851` starts one stream-manager thread per active channel, not a third supervisor — the actual third module-level supervisor is `client_manager.py`'s heartbeat thread, outside this row's `server.py` framing |
 | 27 | Not held to: `_execute_redis_command` swallows every Redis exception to `None` after one reconnect attempt, so a caller cannot distinguish "key absent" from "Redis unreachable" | `apps/proxy/live_proxy/server.py:138-159` | `white-box-only` | Deleted, not ported: spec D2 removes Redis from the live path entirely, so there is no analogous call in the Go relay to swallow anything. One of the three fail-open paths `CLAUDE.md` records as a live defect |
 | 29 | The buffering failover detector is ffmpeg-exclusive: on the Proxy and Redirect Stream Profiles `buffering_speed` and `buffering_timeout` are read and then never consulted — no `ffmpeg_speed` is ever written, `state` never becomes `buffering`, and no `channel_buffering` event is raised, however far below the threshold the upstream runs | `apps/proxy/live_proxy/input/manager.py:1092` (`_update_ffmpeg_stats_in_redis` is called only from `_parse_ffmpeg_stats`), `apps/proxy/live_proxy/input/manager.py:1122` (the buffering comparison, in the same function), reached only from the stderr reader a transcode profile has | `apps/proxy/live_proxy/tests/test_manager_connection_failover.py::ConnectionFailoverTests::test_the_proxy_profile_streams_with_no_ffmpeg_and_no_stats`, `relay/httpapi/transcode_test.go::TestTheProxyProfileStreamsWithNoFfmpegAndNoStats` | Found by 2a-4, which wrote the test and recorded that the row was 2a-7's to add; inherited here rather than absorbed. Externally observable — an operator who raises `buffering_speed` on a Proxy channel gets no failover and no indication the setting did nothing, and nothing in the UI says so. D5 is strict parity, so the Go relay reproduces the inertness. The Go pin is 2c-4's, the first PR in which both architectures exist and the row can fail: buffering_speed at the API maximum on a Proxy tune, no speed reported, state never buffering, none of the seven ffmpeg-derived keys on the payload. |
-| 30 | A credential an authenticator explicitly REJECTS (a malformed Bearer JWT, an unknown API key) is refused 401; a credential merely DECLINED — no header presented at all — falls through to the anonymous principal, which still streams an ordinary channel by UUID | `apps/proxy/authorize.py:258-259` (`except AuthenticationFailed: raise AuthorizeDenied(401, ...)`) vs `apps/proxy/authorize.py:260-265` (`except APIException: return None`, and the no-match fall-through), over the authenticator set at `apps/proxy/authorize.py:93-97` | `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py::CredentialDispositionTests::test_a_rejected_bearer_token_is_refused_with_401`, `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py::CredentialDispositionTests::test_no_credential_at_all_streams_as_anonymous` | Found by 2a-5, recorded as a porting hazard in a docstring only; inherited by 2a-7 and pinned here. A port that flattens both exits to "anonymous" fails no other test in the suite, and the failure it introduces is silent — a request carrying a credential the control plane rejected streams anyway. **The pin is driven at `GET /_dispatcharr/authorize`, not at `/proxy/ts/stream/<uuid>` directly** — `stream_ts` is `@api_view` with no `authentication_classes` override, so DRF's own `dispatch()` runs the project `DEFAULT_AUTHENTICATION_CLASSES` (`JWTAuthentication`, `ApiKeyAuthentication`) and refuses a rejected Bearer token or API key with DRF's own body shape *before* `resolve_authorization()`/`_drf_user()` ever runs — verified for both credential types by driving each directly at the stream URL and reading the response body, not assumed. A Go relay that faithfully ports this module and is then driven at a bare streaming URL with no `auth_request` in front of it would diverge from Python's behaviour there not because the port got `authorize.py` wrong, but because Python itself never runs `_drf_user`'s disposition logic on that path for these two credential types — a D5 parity fact about which surface makes this decision, not a footnote. Filed as [#247](https://github.com/D10Scot/Dispatcharr/issues/247), a 2c carry-forward in the same shape as #235, for the implementer who is not reading this table row by row. |
+| 30 | A credential an authenticator explicitly REJECTS (a malformed Bearer JWT, an unknown API key) is refused 401; a credential merely DECLINED — no header presented at all — falls through to the anonymous principal, which still streams an ordinary channel by UUID | `apps/proxy/authorize.py:258-259` (`except AuthenticationFailed: raise AuthorizeDenied(401, ...)`) vs `apps/proxy/authorize.py:260-265` (`except APIException: return None`, and the no-match fall-through), over the authenticator set at `apps/proxy/authorize.py:93-97` | `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py::CredentialDispositionTests::test_a_rejected_bearer_token_is_refused_with_401`, `apps/proxy/live_proxy/tests/test_authorize_credential_disposition.py::CredentialDispositionTests::test_no_credential_at_all_streams_as_anonymous`, `relay/httpapi/authorize_test.go::TestADenialReachesTheViewerWithItsOwnStatus` | Found by 2a-5, recorded as a porting hazard in a docstring only; inherited by 2a-7 and pinned here. A port that flattens both exits to "anonymous" fails no other test in the suite, and the failure it introduces is silent — a request carrying a credential the control plane rejected streams anyway. **The pin is driven at `GET /_dispatcharr/authorize`, not at `/proxy/ts/stream/<uuid>` directly** — `stream_ts` is `@api_view` with no `authentication_classes` override, so DRF's own `dispatch()` runs the project `DEFAULT_AUTHENTICATION_CLASSES` (`JWTAuthentication`, `ApiKeyAuthentication`) and refuses a rejected Bearer token or API key with DRF's own body shape *before* `resolve_authorization()`/`_drf_user()` ever runs — verified for both credential types by driving each directly at the stream URL and reading the response body, not assumed. A Go relay that faithfully ports this module and is then driven at a bare streaming URL with no `auth_request` in front of it would diverge from Python's behaviour there not because the port got `authorize.py` wrong, but because Python itself never runs `_drf_user`'s disposition logic on that path for these two credential types — a D5 parity fact about which surface makes this decision, not a footnote. Filed as [#247](https://github.com/D10Scot/Dispatcharr/issues/247), a 2c carry-forward in the same shape as #235, for the implementer who is not reading this table row by row. The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
 <!-- end of matrix -->
```

### Appendix AN — the spec: Amendment A8 and two Done-log rows

**A `git diff` hunk, not a "paste this after A6".** One hunk carries both edits: A8's eight items, inserted between the end of A6 and `## Stage 2d`, and the two Done-log rows appended after 2c-6's.

**Captured against `d6d71f97`, and it WAS re-captured.** The first version was anchored between the end of A6 and `## Stage 2d`, and 2c-7 inserted A7 exactly there; its Done-log context moved the same way. The placeholder 2c-7 Done-log row the earlier version carried — whose own text said it would go stale — is gone, replaced by the real row 2c-7 merged, and A8 now sits after A7 where it belongs.

```diff
diff --git a/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md b/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
index f2f07da2..bf787c6e 100644
--- a/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
+++ b/docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
@@ -2462,6 +2462,157 @@ disambiguated only by the logger's `format=` field, not by the message
 itself — a one-line rename that belongs with Ruling R1's recommended
 `fmp4.go` split, for 2c-9.
 
+#### Amendment A8 (2c-8) — nine corrections and inputs from the control routes and the drain
+
+**A8.1 — the XC live roots had no owning PR, and 2c-8 builds them.**
+§ Stage 2c's "It serves" names `GET /proxy/ts/stream/<id>` and *the XC
+live roots*; the nine-PR table names the roots in no row. Walked: 2c-2
+is the Proxy architecture, 2c-3 fan-out, 2c-4 ffmpeg, 2c-5 failover and
+Redirect, 2c-6 fMP4, 2c-7 Output Profiles, 2c-9 the coverage ratchet.
+The same shape as 2c-1's Finding F2 about Redirect, and the parity
+matrix does not compensate either: row 15 is the roots' only row and no
+PR owed it. **2c-8 adds both**, as a wrapper around the TS handler
+rather than a second one — the channel a root serves is the one the hop
+resolved (`X-Relay-Channel`) or the one the dev fallback's decision
+named, never the numeric path id, which this relay cannot map to a uuid
+without an ORM query. The extension is the one thing the path
+contributes and it contributes it to the *output format*: `.mp4` forces
+fMP4 and `.ts` forces MPEG-TS (`views.py:872-878`), overriding the hop,
+because `resolve_output_format`'s `force` parameter is one the hop
+deliberately never passes.
+
+**The split was considered and not taken.** The roots are real scope the
+2c-8 row does not name, and lifting them into a PR of their own would
+have kept this one to its written brief. It was rejected on Gate 1:
+row 15 is a parity-matrix row, D7 requires every externally-observable
+live-path behaviour to carry a Go column before 2d, and a row whose
+owning PR does not exist is how it came to be open in the first place —
+splitting would have left it open past 2c-8 with no owner again, which
+is the same failure one stage later. A spec that names a deliverable in
+its prose and omits it from its table is factually wrong at that step,
+and an in-PR amendment is what this phase does with those, rather than
+carrying the error forward.
+
+**A8.2 — the advance route needs the stream profile, and Django sends
+it.** `RelayAdvanceRequestSerializer` carries a url and no profile,
+which was sufficient while the relay rebuilt the command from the
+`StreamManager`'s own `stream_profile` (`input/manager.py:1462-1540`).
+Amendment A4.1 took that away: Django builds the argv for each Source's
+own URL, so a Go relay handed a url alone has nothing to spawn. The
+serializer gains **`stream_profile`, `ffmpeg_stream_profile` and
+`transcode`** — the three fields of `SourceSerializer` the flat fields
+do not already duplicate — and `relay_client.advance()` forwards them
+from the resolved source both producers already hold. The **bare-url**
+branch of `change_stream` (a `url` with no `stream_id`, reachable only
+by a hand-crafted admin call; the UI always sends `stream_id`) resolves
+no Stream row, so it asks the **channel** for its own effective profile
+through a new `next_source.channel_stream_profile_ref()` — the same
+profile the Python relay uses there, built in the process that has the
+ORM. A channel identifier that names no row leaves the three fields
+unset and the Go relay answers 400, which is the truth.
+
+**A8.3 — `RequireInternal` was verifying the signature against an empty
+body.** The bound token signs `sha256(BODY)`
+(`internal_auth.py:126-152`), and every route 2c-3 put behind that gate
+was a GET or a bodyless DELETE — so verifying `nil` was right by
+accident. `POST .../advance` carries a body, and the gate 403'd every
+call. Fixed by buffering the body (bounded at `MaxInternalBody`, 1 MiB,
+with a 413 beyond it) and handing the handler a reader over the same
+bytes. Found by the first run of
+`TestAnAdvanceSwitchesTheChannelAndKeepsTheClientFed`.
+
+**A8.4 — the first client of every channel bypassed `addClient`.**
+`Manager.publish` seeded its registry as
+`map[string]*Client{client.ID: client}`, so the first client of a
+channel never ran the code that installs its transfer counters and its
+stop signal — while the second and every later one, arriving through
+`claim`, did. A `DELETE .../clients/<id>` for that client reported
+`locally_processed: false` about a client the registry was listing, and
+its detail row carried no byte counters. One mechanism now: `publish`
+builds an empty map and calls `addClient`. Found by
+`TestDeletingOneClientDisconnectsItAndLeavesTheOtherStreaming`, not by
+review.
+
+**A8.5 — `control.Emitter` could panic on a drain, and `Close` was not
+idempotent.** The drain closes the emitter, and a client goroutine
+still unwinding raises `client_disconnect` as it returns — a send on a
+closed channel, which panics the goroutine serving that client. `Emit`
+now drops an event raised after `Close`, which is the disposition this
+type already has for a full queue and which `control_plane.py`'s own
+contract states ("an event raised while the control plane is down is
+LOST, not queued"); `Close` is idempotent, because the drain and a
+test's own cleanup both call it. Found by
+`TestTheDrainStopsTheChannelEndsTheClientAndFlushesTheEvents`.
+
+**A8.6 — the drain's budget is derived from supervisord, and the events
+flush is RESERVED.** `docker/supervisord.d/relay-go.conf` carries
+`stopwaitsecs=20` at `priority=205`, shared with `relay-uwsgi`, so that
+group costs `max(20, 20)` and the container's stop budget is 155s
+against a 160s `stop_grace_period`. Twenty seconds is the ceiling;
+`DefaultBudget` is **15s**, leaving five. Inside it: a **5s** client
+grace (D6's "lets running clients finish", which for a live stream means
+the bound), the channel teardown and the server shutdown sharing what is
+left, and a **3s** events flush **reserved out of the total** rather
+than taking what remains — a teardown that used the whole budget would
+otherwise raise one `channel_stop` per channel and deliver none of them,
+which is the one thing the flush is for. `Manager.StopAll` became
+concurrent for the same arithmetic: sequential, ten channels at
+`StopWait` is fifty seconds against a twenty-second window.
+
+**A8.7 — `/readyz` reports the drain and the counts, and deliberately
+does NOT probe the control plane.** A relay that marked itself unready
+during a Django outage would be taken out of nginx's rotation at stage
+2d — and a running stream needs nothing from Django once it is running
+(`CLAUDE.md` § Operationally: stopping `api-uwsgi` "does not disturb a
+running stream"), so deregistering would turn a degraded new-tune path
+into a total outage for viewers who were fine. `/healthz` stays a static
+200 and stays liveness: it answers 200 throughout the drain, because a
+supervisor that restarted the process mid-drain would defeat it. The
+Docker `HEALTHCHECK` is role-aware through `docker/healthcheck.sh`,
+which reads the role `entrypoint.sh` now writes to `/run/dispatcharr-role`
+— `HEALTHCHECK` runs as a fresh process with the container's own
+environment, which carries `DISPATCHARR_ROLE` only when the operator set
+it explicitly.
+
+**A8.8 — two detail-endpoint fields are unreachable in BOTH relays, and
+one Go divergence is stated.** `source_bitrate` has no writer anywhere
+in the tree (`channel_status.py:359` is its only reference beside the
+constant), and `ffmpeg_bitrate` is read under
+`ChannelMetadataField.FFMPEG_BITRATE` while the only writer
+(`input/manager.py:1269`) writes `FFMPEG_OUTPUT_BITRATE` — two different
+strings at `constants.py:90-91` — so the operator's output bitrate never
+reaches the payload in either relay. Reproduced as absences per D5 and
+filed, the same shape as `logo_id` on the list endpoint. Separately, row
+18's Go answer is **absent**, not filled: `get_detailed_channel_info`
+falls back to an ORM lookup for `stream_name` and `m3u_profile_name`
+when the hash has none, and the Go relay has no fallback and can have
+none — those two queries are exactly what D2 forbids. 2b-1 put both
+names on the wire so the case is unreachable in practice; the
+divergence is stated rather than hidden.
+
+**A8.9 — `source=` does not rename an INPUT field in DRF, and the
+hyphenated header never arrived.** `AuthorizeInternalHeadersSerializer`
+declares the third credential header as `x_api_key =
+serializers.CharField(source="x-api-key", ...)`, because `x-api-key` is
+not a Python identifier. **That is the wrong half of the mapping.** DRF
+reads INPUT by a field's NAME and uses `source` only to decide where the
+value lands in `validated_data`, so a body carrying `"x-api-key"` — what
+§ The contract specifies and what the Go relay sends — deserialized to
+`None`, `HTTP_X_API_KEY` was never set on the synthesised request, and an
+API-key client would have resolved to **anonymous** in the nginx-less
+shape and to its real user in production. That is the exact cross-shape
+divergence D5 exists to prevent, and the one this third field was added
+to close. Fixed with three lines of `to_internal_value`. **Found by a
+Gate 2 coverage test, not by review**: the first measurement listed the
+`HTTP_X_API_KEY` assignment among nine uncovered new statements, and
+writing a test for it produced a 200 where a rejected key must give 401.
+Every earlier reading had looked past a declaration that names the wire
+key on the line above the comment explaining why the wire key matters.
+Recorded here because the shape generalises: any `source=` on a field
+whose wire name is not a Python identifier is silently input-blind, and
+this contract has one more such field waiting to be added the moment a
+fourth credential header is discovered.
+
 ## Stage 2d — cutover, and its trap
 
 **The historical bug this stage exists to not repeat.** Every live-bound nginx location today carries
@@ -2788,6 +2939,7 @@ Filled in as PRs merge; this spec lands as its own PR 0.
 | 2c-5 -- the Go relay's failover: the three triggers (rows 1, 2, 3) as one port of `StreamManager.run`'s two loops, a clean EOF ported as a retried connection failure (R1); the control-plane client's `release` and `events` routes and an emitter that batches and logs an outage once (R12); the degraded fallback to the candidate list cached at channel start, never on a refusal (R2); the Redirect Stream Profile architecture -- the 302, the provider probe, the fall-through to the cached alternates, the internal-principal override, publishing no channel (R7, R8); the health flag, the keepalives, the client timeout and the error packet closing Amendment A2.5 (R14, R15); the five events the failover machinery raises (R11). Parity matrix rows 1, 2, 3 and 6 get a Go column; row 7 gains a pin across a switch. A pre-existing Python defect (one `next-source` call per buffering progress record when no alternate exists) reproduced per D5 and filed as [#302](https://github.com/D10Scot/Dispatcharr/issues/302) (R6). | `migration/phase2c-failover` | pending |
 | 2c-6 -- the Go relay's fMP4 output format (`migration/phase2c-fmp4`). One remux per channel reading the shared ring on `pipe:0`, the init segment replayed to every client, a refcounted lifecycle with no shutdown delay, and parity-matrix row 12 ([#222](https://github.com/D10Scot/Dispatcharr/issues/222)) reproduced, pinned and filed rather than fixed. Row 12 gets its Go pin. Amendment A6. [#304](https://github.com/D10Scot/Dispatcharr/issues/304) (a pre-existing 2c-4 defect, the stderr pipe truncated by a reap racing its drain) fixed in `relay/ffmpeg/spawn.go`, repairing `relay/channel/source_transcode.go` without editing it. Two Python-side findings from the port, reproduced and filed rather than fixed: the fMP4 scanner's resynchronisation arm discarding the whole working buffer ([#306](https://github.com/D10Scot/Dispatcharr/issues/306)) and the dead stop-during-restart guard in `_handle_bsf_error` ([#307](https://github.com/D10Scot/Dispatcharr/issues/307)). Three plan corrections found and fixed in the plan document as committed, run rather than read: Task 4 Step 7's break-check rows 16-18 name tests defined in `relay/httpapi/fmp4_test.go`, Task 6's file, and had to run there rather than in Task 4; Task 1 Step 2's expected result for `TestEveryStderrLineSurvivesTheWaitThatPrecedesTheJoin` describes a runtime failure the package cannot yet produce, since the two `StartPiped` tests appended in the same step leave it uncompilable until Step 3's implementation lands; and the issue-number-placeholder slot count was corrected from six to five (an instruction about the slots had been counted as one) with Task 8 Step 5's own verification grep narrowed to the paths that can carry a real slot, since run unscoped over all of `docs/` it could never return empty. | `migration/phase2c-fmp4` | pending |
 | 2c-7 -- the Go relay's Output Profiles (`migration/phase2c-output-profile`). One transcode per active `(channel, profile)` pair reading the channel's shared ring on `pipe:0` and writing a second in-process MPEG-TS ring, shared by every client on that profile; an fMP4 client on a profile runs it and 2c-6's remux chained, under `mpegts:p<id>` and `fmp4:p<id>`. Parity-matrix row 11 gets its Go pin, counted in spawns. The contract gained a null `argv` so a broken Output Profile can be told from a deactivated one. Amendment A7. Three plan corrections found, disclosed and **fixed in the plan document as committed**, run rather than read: Task 4 Step 5 and Task 7 Step 5 misassigned which break-check rows belong to which task -- rows 3-7 name `httpapi`-package tests Task 7 creates (Appendix P) and rows 8 and 11 name `output`-package tests Task 4 creates (Appendix I), so Task 4's Step 5 now reads "rows 8 and 11" and Task 7's now reads "rows 2, 3, 4, 5, 6, 7, 9, 10, 12, 13, 16, 17, 18", the amended lists this PR actually ran each row against; rows 16, 17 and 18 were re-checked against the same test rather than assumed correct, and confirmed already in Task 7's list -- `TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint` and `TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot` (both arms) are in `relay/httpapi/profile_test.go`, and no channel-package location for either exists. Task 5 Step 3's "Expected: green" for the whole-module `go build ./...` did not hold and is amended to name what actually goes green at that step: `go build`/`vet`/`golangci-lint` scoped to `./channel/... ./output/... ./control/... ./buffer/... ./ffmpeg/... ./internal/...` (every package but `httpapi`), `go test -race ./channel/...`, and `gofmt -l .` over the whole tree -- **commit `38669dba` (Task 5) does not build alone**, because `httpapi/fmp4.go` and `stream.go` still call `AttachOutput` with the pre-2c-7 signature; the whole-module build, vet, test and lint first go green at Task 6 Step 4 once `httpapi`'s own edits land, so a `go build ./...` bisect on this branch lands on Task 6's commit for a defect that is Task 5's incompleteness, not Task 6's own. No commit was ever made against a genuinely broken working tree regardless, since Task 6 was written and verified before either commit. Third, Task 9 Step 3's `ffmpeg.StartPiped`/`.Start` call-site breakdown named the wrong two files ("two in spawn.go, one in output/fmp4.go, one in output/profile.go"); the actual four are one in `output/profile.go`, two in `output/fmp4.go` (the initial spawn and the bitstream-filter retry) and one in `channel/source_transcode.go` -- the total of 4 was already right. | `migration/phase2c-output-profile` | pending |
+| 2c-8 -- the Go relay's control routes and drain (`migration/phase2c-control-drain`). The four remaining `/proxy/relay/…` routes (the single-channel `GET` with its `?fields=state` form, the channel `DELETE`, the client `DELETE` and `advance`), the detail endpoint with its five extra client fields and row 14's `owner` asymmetry, the XC live roots (Ruling R1: spec D1 scopes them and no PR owned them), the four events the tune and stop paths raise, the dev-only `POST /_dispatcharr/authorize-internal` fallback and the Go half that calls it, and D6's SIGTERM drain with a real `/readyz` and a role-aware Docker `HEALTHCHECK`. Thirteen parity-matrix rows get a Go pin, taking the matrix to 28 of 28 pinnable rows, and the ten authorize-matrix rows among them gain a Notes clause saying the Go pin covers the relay's ask-and-obey share and not the decision, which stays Django's. Amendment A8. Four defects found and fixed, three in code this PR did not write: `RequireInternal` verifying the bound signature against an empty body (A8.3), `Manager.publish` bypassing `addClient` for the first client of every channel (A8.4), `control.Emitter` panicking on a send after `Close` and on a second `Close` (A8.5), and -- in this PR's own first draft, found by a Gate 2 coverage test -- the `x-api-key` body field that never arrived, because DRF reads input by a field's NAME and `source=` maps only the output (A8.9). Two Python-side findings reproduced and filed rather than fixed: `source_bitrate` and `ffmpeg_bitrate` are read by `channel_status.py` and written by nothing, the second because the reader and the writer name two different constants ([#NNN](https://github.com/D10Scot/Dispatcharr/issues/NNN)). Four break-checks stayed green on a first attempt and each produced a better test or deleted unreachable code. | `migration/phase2c-control-drain` | pending |
 
 ## Risks
 
```

### Appendix AO — `CLAUDE.md`

**A `git diff` hunk, and this is the appendix the rule was written for.** The first draft of this appendix was prose — "replace that sentence with…" — quoting the § Architecture `relay-go` paragraph as it stood. That shape has already cost this programme once: 2c-7's equivalent would have silently dropped a sentence 2c-6 had added to the same paragraph, because the quoted "after" text was written against an older copy and nothing compares the two. A hunk cannot do that: it carries three lines of context on each side and `git apply` refuses when they have moved.

Two edits, one hunk: the § Architecture sentence that still says "At 2c-1 it serves `/healthz` and `/readyz` and nothing else", and one bullet appended to § Known defects' Correctness list.

**Captured against `d6d71f97`.** Re-captured on the re-seed and its content is unchanged: 2c-7 appended to the Output Profile parenthetical, which is far enough from both anchors that this hunk still applied — checked, not assumed.

```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index 31609244..7f18ce9b 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -70,7 +70,7 @@ scripts/check_go_stdlib_only.sh relay           # the module must stay stdlib-on
 
 Django 6 + DRF, React 19 SPA same-origin, Celery, Redis for broker/cache/channel-layer **and the video path**, PostgreSQL for durable state. A third of the backend is `apps/proxy` (22.3k LOC) and `apps/channels` (20.8k); then `epg`, `timeshift` (Xtream catch-up), `m3u`, `core` (settings registry, profiles, events), `output`, `vod`, `plugins`, `hdhr`.
 
-**Two uWSGI processes**, running the same Django app under the same urlconf and differing only in listener, worker count and concurrency: the **API** process (`docker/uwsgi.ini` / `uwsgi.modular.ini`, unix socket plus `http = 0.0.0.0:5656`, 4 workers × `gevent = 400`, `harakiri = $(DISPATCHARR_API_HARAKIRI)` default 120s, `max-requests = $(DISPATCHARR_API_MAX_REQUESTS)` default 5000) serves everything except long-lived streams, and the **relay** process (`docker/uwsgi.relay.ini`, `socket = 0.0.0.0:5657`, `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)` default 1600, **no `harakiri`**) serves `/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php`, `/proxy/relay/…` and the XC streaming roots — `docker/nginx.conf`'s location table is the authority on exactly which. Both carry `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`, and each is one `supervisord` program among several (`docker/supervisord/` holds one conf per rung, `docker/supervisord.d/` one `[program:x]` per file), alongside: Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image. **`DISPATCHARR_ROLE`** (`all`/`api`/`relay`/`worker`, defaulted from `DISPATCHARR_ENV`) picks which subset a container runs; `DISPATCHARR_ENV=dev` picks the `all-dev` rung instead, which runs vite and no nginx. `priority=` orders start and stop *signals*, so each program waits for its own stores through `docker/supervisord.d/wait-for-stores.sh`, and shutdown walks one priority group at a time rather than signalling everything at once. (`docker/entrypoint.aio.sh` and `docker/entrypoint.celery.sh` are deleted, not legacy.) Since Phase 2 stage 2c there is a **third** server process, `relay-go` (`docker/supervisord.d/relay-go.conf`, roles `all` and `relay`, port 5658 from `DISPATCHARR_RELAY_GO_PORT`), a Go binary built in the Dockerfile's own `relay-builder` stage. At 2c-1 it serves `/healthz` and `/readyz` and nothing else: no nginx location routes to it until stage 2d, and every other route is behind a dev-only flag. It shares supervisord `priority=205` with `relay-uwsgi` deliberately — a priority of its own would add its `stopwaitsecs` to the container's stop budget as a separate group and take the sum past the 160s `stop_grace_period`. It opens no Postgres connection and no Redis connection, and links no driver for either; `scripts/check_go_stdlib_only.sh` is the mechanical backstop, run by `go-tests.yml`. Consequences constraining nearly every `apps/proxy` change:
+**Two uWSGI processes**, running the same Django app under the same urlconf and differing only in listener, worker count and concurrency: the **API** process (`docker/uwsgi.ini` / `uwsgi.modular.ini`, unix socket plus `http = 0.0.0.0:5656`, 4 workers × `gevent = 400`, `harakiri = $(DISPATCHARR_API_HARAKIRI)` default 120s, `max-requests = $(DISPATCHARR_API_MAX_REQUESTS)` default 5000) serves everything except long-lived streams, and the **relay** process (`docker/uwsgi.relay.ini`, `socket = 0.0.0.0:5657`, `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)` default 1600, **no `harakiri`**) serves `/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php`, `/proxy/relay/…` and the XC streaming roots — `docker/nginx.conf`'s location table is the authority on exactly which. Both carry `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`, and each is one `supervisord` program among several (`docker/supervisord/` holds one conf per rung, `docker/supervisord.d/` one `[program:x]` per file), alongside: Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image. **`DISPATCHARR_ROLE`** (`all`/`api`/`relay`/`worker`, defaulted from `DISPATCHARR_ENV`) picks which subset a container runs; `DISPATCHARR_ENV=dev` picks the `all-dev` rung instead, which runs vite and no nginx. `priority=` orders start and stop *signals*, so each program waits for its own stores through `docker/supervisord.d/wait-for-stores.sh`, and shutdown walks one priority group at a time rather than signalling everything at once. (`docker/entrypoint.aio.sh` and `docker/entrypoint.celery.sh` are deleted, not legacy.) Since Phase 2 stage 2c there is a **third** server process, `relay-go` (`docker/supervisord.d/relay-go.conf`, roles `all` and `relay`, port 5658 from `DISPATCHARR_RELAY_GO_PORT`), a Go binary built in the Dockerfile's own `relay-builder` stage. As of Phase 2 stage 2c-8 it serves the whole live surface behind that dev flag — `GET /proxy/ts/stream/<id>`, both XC live roots, all five `/proxy/relay/…` control routes — plus, unflagged, `/healthz` (liveness: a static 200 even while draining, because a supervisor that restarted the process mid-drain would defeat the drain) and `/readyz` (readiness: 503 from the moment a SIGTERM raises the drain gate, with the channel and client counts in its body, and deliberately no probe of the control plane — a relay that deregistered during a Django outage would drop viewers whose streams need nothing from Django). Still no nginx location routes to it until stage 2d. Its shutdown is D6's drain: fifteen seconds against `relay-go.conf`'s `stopwaitsecs=20`, spent as a five-second client grace, a concurrent channel teardown that releases every provider slot, an `http.Server.Shutdown` that is only immediate because the channels stopped first, and a three-second events flush **reserved** out of the total rather than taking what is left — so a slow teardown costs the shutdown its wait and never costs the events their delivery. It shares supervisord `priority=205` with `relay-uwsgi` deliberately — a priority of its own would add its `stopwaitsecs` to the container's stop budget as a separate group and take the sum past the 160s `stop_grace_period`. It opens no Postgres connection and no Redis connection, and links no driver for either; `scripts/check_go_stdlib_only.sh` is the mechanical backstop, run by `go-tests.yml`. Consequences constraining nearly every `apps/proxy` change:
 
 - Four API worker processes plus the relay's one ⇒ **no channel state may live in Python memory**. The relay running a single worker does not relax this: an API worker, a Celery task and the relay all read the same channel through Redis, and PR 8's bounded restart replaces the relay process itself.
 - Early monkey-patching ⇒ the proxy's 27 `threading.Thread`s are greenlets sharing one OS thread with 400 request greenlets. **One blocking call stalls the hub.**
@@ -133,6 +133,7 @@ Correctness:
 - **`get_user_active_connections` has four callers, and one of them still triggers a relay side effect on every call.** Three timeshift helpers (`_session_has_active_timeshift_stream`, `_preempt_playback_streams`, `_terminate_previous_timeshift_sessions`) pass `include_live=False` (`apps/proxy/utils.py`), added by a whole-branch-review fix after one of them — reached from `_serve_catchup`, a relay-served view — was making the relay call itself over HTTP per catch-up tune for a live client list it always discarded. The fourth caller, `apps/output/views.py`'s `xc_get_info` (the Xtream `player_api.php` handshake, every XC session), is deliberately left asking for the live count — `active_cons` needs it — so that call still reaches `GET /proxy/relay/channels?clients=all` on every handshake, and `get_basic_channel_info` there runs `ClientManager.remove_ghost_clients`, an `SREM` write across every running channel that the old direct Redis scan never performed. That side effect has no Go analogue: the Go relay's client registry is a map in process memory (Phase 2 stage 2c-3), where a client entry cannot outlive the goroutine that made it, so it disappears at the 2d cutover rather than being fixed.
 - **The UDP user-agent filter leaves dangling flags** (`apps/proxy/live_proxy/input/manager.py:808-812`): on a `udp://` upstream every argument containing the user agent or `user-agent`/`user_agent` is dropped, and the flag that introduced it is kept, so `-headers 'User-Agent: X'` spawns as a bare `-headers` whose value becomes the next argument, `-i`. The filter also runs over `cmd[0]`, the command itself. The Go relay reproduces the dangling flag per D5 and not the `cmd[0]` case. Filed as [#296](https://github.com/D10Scot/Dispatcharr/issues/296).
 - **Both relays' buffering-progress gate is structurally blind on ffmpeg 6.x, not merely quantitatively different.** `input/manager.py:1017` and the Go port at `relay/ffmpeg/progress.go:40` both key `IsProgressLine`/progress parsing on the literal `frame=`, but a stream-copy (`-c copy`) progress line's leading token on ffmpeg 6.x is `size=`, never `frame=` — so neither relay ever records a `speed=` reading against ffmpeg 6.x, and the buffering detector can never arm. Found when go-tests.yml's `build` job briefly ran on ubuntu-latest's own apt ffmpeg (6.1.1) and parity-matrix row 4's real-ffmpeg pin failed; fixed for CI by running that job against the production ffmpeg (8.1.2) instead (below), not by widening the parser or the test. Filed as [#299](https://github.com/D10Scot/Dispatcharr/issues/299).
+- **Two fields on `GET /proxy/ts/status/<uuid>` are read by `channel_status.py` and written by nothing**, so neither relay has ever emitted them ([#NNN](https://github.com/D10Scot/Dispatcharr/issues/NNN)). `source_bitrate`: `ChannelMetadataField.SOURCE_BITRATE` has no writer anywhere in the tree, and `channel_status.py:359` is its only reference beside the constant. `ffmpeg_bitrate`: `channel_status.py:404` reads `ChannelMetadataField.FFMPEG_BITRATE` (`"ffmpeg_bitrate"`) while the only writer, `input/manager.py:1269`, writes `FFMPEG_OUTPUT_BITRATE` (`"ffmpeg_output_bitrate"`) — two different strings at `constants.py:90-91` — so the operator's ffmpeg output bitrate never reaches the status payload at all. The same shape as `logo_id` on the collection endpoint. Found by Phase 2 stage 2c-8 walking the detail endpoint field by field; reproduced as absences in the Go relay per spec D5, not fixed.
 
 Dead or unwired: `apps/proxy/hls_proxy/`; `dispatcharr/persistent_lock.py` (no callers; `refresh()` sets `has_lock = False` on success, and an attribute shadows the `has_lock` method); `_attempt_health_recovery()`; `head_vod()` (no route); `MAX_HEALTH_RECOVERY_ATTEMPTS` / `MAX_RECONNECT_ATTEMPTS` / `MIN_STABLE_TIME_BEFORE_RECONNECT` (`config.py` — real values are bare literals in the health-monitor body); `M3UAccount.stream_profile`; `HDHRDevice.tuner_count`.
 
```

### Appendix AQ — `relay/channel/advance.go`

`change_stream_url`'s owner branch over a source Django has already resolved (Ruling R2), plus `ExcludedStreamIDs` — the tried set read the one way it is observable, which is also the only thing it is for.

**`relay/channel/advance.go`**

```go
package channel

import "sort"

// Advance is an operator's switch: ChannelService.change_stream_url's owner
// branch (services/channel_service.py:483-520) over a source Django has
// already resolved, which is what POST /proxy/relay/channels/<id>/advance
// carries (apps/proxy/relay_serializers.py:187-222, "a fully-resolved
// source (ruling 11)").
//
// resetTried is the flag relay_views.py:236-239 applies before the switch:
// /proxy/ts/change_stream/ clears the running manager's tried_stream_ids so
// an operator's manual switch does not inherit a failover's exclusion list,
// and /proxy/ts/next_stream/ does not.
//
// The return is update_url's own (input/manager.py:1462-1540): false when
// the URL is the one already playing, true when the switch was applied. The
// caller -- not this method -- is what turns a false into change_stream_url's
// `success: true`, because that layer treats an unchanged URL as a metadata
// refresh rather than a failure (channel_service.py:487-490's own comment).
//
// Serialised by switchMu with failover(), so an operator's switch and a
// buffering-triggered one cannot interleave and leave the tried set
// describing neither.
func (c *Channel) Advance(resolved Resolved, resetTried bool) bool {
	c.switchMu.Lock()
	defer c.switchMu.Unlock()

	c.mu.Lock()
	if resetTried {
		c.tried = map[int]bool{}
	}
	current := c.source
	c.mu.Unlock()

	if resolved.Info.URL == current.URL {
		// update_url's first check (:1463-1465). Logged at INFO there, and
		// the URL is a credential, so only the channel is named here.
		c.log.Info("the operator switch named the URL already playing", "channel", c.id)
		return false
	}

	c.log.Info("switching stream", "channel", c.id, "trigger", "operator", "stream", resolved.Info.StreamID, "m3u_profile", resolved.Info.M3UProfileID)

	c.mu.Lock()
	if resolved.Info.StreamID != 0 {
		// update_url:1506-1510, inside the success path and after the URL
		// check -- the one place its bookkeeping differs from failover's.
		c.tried[resolved.Info.StreamID] = true
	}
	c.mu.Unlock()

	c.applySwitch(resolved)

	// The run loop adopts the parked source when the running attempt
	// returns, exactly as a buffering-triggered switch does
	// (failoverFromBuffering). Cancelling the attempt is what makes it
	// return: update_url closes the socket or the transcode process at the
	// same point (:1481-1486).
	c.mu.Lock()
	c.pending = &resolved
	cancel := c.cancelAttempt
	c.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	return true
}

// ExcludedStreamIDs is the tried set, sorted: exactly what a failover would
// send as exclude_stream_ids (failover's own NextRequest, input/manager.py:
// 2081-2087).
//
// Exported for one reason, stated so it is not mistaken for general-purpose
// state: the tried set is only externally observable as that list, so a test
// asserting that reset_tried cleared it has nothing else to read. Reading it
// through the same derivation the failover uses is what stops the assertion
// from being about a field nobody sends.
func (c *Channel) ExcludedStreamIDs() []int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	out := make([]int, 0, len(c.tried))
	for id := range c.tried {
		out = append(out, id)
	}
	sort.Ints(out)
	return out
}
```

### Appendix AP — `relay/httpapi/testdata/channel_detail.json`

**Do not paste this file.** It is generated by Task 2 Step 3 from Django's own serializer, and a hand-copied golden is an expected value the code under test computed -- the hazard the golden exists to avoid. It is reproduced here only so a reviewer can see its shape, and the fenced copy carries a trailing newline the rendered file does not.

**`relay/httpapi/testdata/channel_detail.json`**

```json
{"channel_id":"11111111-1111-4111-8111-111111111111","state":"active","url":"http://provider.invalid/live/sub/pw/41.ts","stream_profile":"1","started_at":1789000000.5,"owner":"unknown","buffer_index":120,"channel_name":"BBC One HD","stream_id":41,"stream_name":"BBC One HD (UK)","m3u_profile_id":3,"m3u_profile_name":"Premium","state_changed_at":1789000005.0,"state_duration":25.5,"uptime":30.0,"total_bytes":9999888,"total_data":"9.54 MB","avg_bitrate_kbps":2665.3034666666667,"avg_bitrate":"2.67 Mbps","client_count":2,"buffer_stats":{"chunks":120,"diagnostics":{"first_chunk":{"index":116,"size":255868,"ts_packets":1361,"aligned":true,"first_byte":71}},"avg_chunk_size":255868.0,"recent_chunk_sizes":[255868,255868,255868,255868,255868],"keys_found":[116,117,118,119,120],"keys_missing":[],"total_sample_bytes":1279340,"estimated_ts_packets":6805,"is_ts_aligned":true},"local_manager":{"healthy":true,"connected":true,"last_data_time":1789000029.5,"last_data_age":0.5},"video_codec":"h264","resolution":"1920x1080","width":"1920","height":"1080","video_bitrate":"4500.0","source_fps":"25.0","pixel_format":"yuv420p","audio_codec":"aac","sample_rate":"48000","audio_channels":"stereo","audio_bitrate":"128.0","ffmpeg_speed":1.02,"ffmpeg_fps":"25.0","actual_fps":"24.5","stream_type":"mpegts","clients":[{"client_id":"client_1789000000000_1234","user_agent":"VLC/3.0.20","worker_id":"unknown","ip_address":"198.51.100.4","user_id":"7","output_format":"mpegts","output_profile_id":7,"connected_at":1789000001.25,"last_active":1789000029.5,"last_active_ago":0.5,"bytes_sent":9999888,"avg_rate_KBps":341.2,"current_rate_KBps":348.9},{"client_id":"client_1789000000000_5678","user_agent":"unknown","worker_id":"unknown","ip_address":"198.51.100.9","user_id":"0","output_format":"fmp4","output_profile_id":null,"connected_at":1789000010.0,"last_active":1789000029.0,"last_active_ago":1.0}]}
```

