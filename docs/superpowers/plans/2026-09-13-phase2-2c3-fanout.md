# Phase 2 PR 2c-3 — the Go relay's multi-client fan-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Go relay serve **N clients on one channel**. Three clients tune the same uuid, one upstream connection is opened, each of them reads an unbroken run of that upstream's bytes from its own join point roughly five seconds behind live, the relay knows who is attached, and `GET /proxy/relay/channels?clients=all` tells Django exactly what the Python relay tells it today. The last client leaving stops the channel; a client arriving as the last one leaves does not lose it.

**Architecture:** 2c-2's ring, manager and tune path gain the reader dimension. `buffer` gets a bounded `Read` so a lagging reader cannot pin a whole ring's worth of evicted chunks. `channel` gets the client registry that replaces `live:channel:{id}:clients`, its metadata hash, its TTL and its heartbeat thread, plus the last-client rule made atomic with the arrival path. `httpapi` gets the four trust-gated `X-Relay-*` values a client is registered from, and one new internal route. One Python change: a golden fixture rendered by Django's own serializer, so the Go payload is pinned against the other implementation rather than against a hand-typed guess.

**This is the PR where the relay stops being a single-reader proof and starts being a relay.** It stays inert in every deployment: both routes are behind 2c-1's dev flag, and nginx routes nothing to port 5658 until stage 2d.

---

## Global Constraints

Every task's requirements implicitly include this section. Constraints 1–16 are 2c-1's and 2c-2's, restated because this plan is executed by an agent who has not read them; 17–20 are new.

1. **Anchor every command with an absolute path, or open it with a `cd` into your own worktree.** The shell's working directory has been observed in this programme drifting into another agent's worktree with no `cd` issued — it happened to this plan's own author mid-task, which is why this is first. A relative path that resolves somewhere else does not error; it writes a plausible file in the wrong tree.

2. **`go test -race` is mandatory on every Go test run: locally, in the hook, in the commit gate, in CI.** This PR adds the readers that make the ring's lock discipline load-bearing.

3. **Standard library only. No `require` line, no `go.sum`, ever.** `scripts/check_go_stdlib_only.sh` is the mechanical check. Everything here is in `net/http`, `net/http/httptest`, `encoding/json`, `crypto/rand`, `math/big`, `sync`, `sort`, `context`, `time`, `runtime`, `reflect`, `os` and `log/slog`.

4. **Nothing in `relay/` may open a Postgres connection or a Redis connection, in any task, including a test.** 2c-2 made "no Redis on the live video path" a break-check; **this PR closes the spec's `Client registry` key-family row**, which is the largest single family left. Task 12 records the walk in the spec's own units.

5. **Every pin is tool-resolved on the day the PR is opened, never copied from this plan.** This PR adds no new action pin and no new base image.

6. **zizmor blocks on every finding in any workflow file you touch.** This PR touches none. Verify in Task 0 rather than assuming it.

7. **Do not add a Docker `HEALTHCHECK`, a SIGTERM drain, or a `/readyz` that reports anything real.** Those are 2c-8's.

8. **Every Go constant that mirrors a Python literal carries its source `file:line` in a comment and is pinned by a test naming the same location.** This PR adds exactly two: `buffer.MaxChunksPerRead` and `httpapi.DefaultClientLimit`. Both are named in their tasks with the reason a wire field would have been wrong.

9. **Prefer `t.Setenv` over manual environment save/restore, and never run an environment-mutating test with `t.Parallel()`.** No test in this PR mutates the environment; none takes `t.Parallel()` either, because every one of them holds a real HTTP server and a real channel.

10. **No task in this PR needs the shared `dispatcharr-testrunner` container except Task 7**, which runs one Django management command to render the golden fixture. `.claude/hooks/run-go-checks.sh` derives its module root by walking up from the edited file's own path, so it runs on the host with no container and the shared-container trap cannot reach a Go edit. Before Task 7's Python edit:

    ```bash
    docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
    ```

    If it is not your worktree, re-point it with `.claude/hooks/start-test-container.sh` — **after** checking nobody else is mid-task in the tree it currently holds (`docker ps`, and `stat -f '%Sm %N'` on that tree's recently-touched files; a modification younger than a few minutes means occupied).

11. **Stage and commit in separate Bash calls, and write commit messages to a file and use `-F`.** The `PreToolUse` gate runs before the command, so one call that does both is blocked, and it matches on command text, so a heredoc containing the two words trips it.

12. **A provider URL is a credential and never reaches a log or an error message.** The Go-side enforcement is `channel.withoutURL` and the fixed strings `writeTuneFailure` answers with. **There is one deliberate exception in this PR and it must not be read as a violation:** `GET /proxy/relay/channels` renders the provider URL in its `url` field, because `channel_status.py:472` does and the Stats page shows it. That surface is internal, HMAC-authenticated and already carries the URL today; changing it is a behaviour change D5 forbids. A response body to a verified internal caller is not a log. See Ruling R7.

13. **A control-plane setting is read from the wire or the tune fails. Never from a Go-side default.** This PR adds one more required key, `channel_shutdown_delay`, and Task 5's per-key test grows a subtest for it.

14. **Parity is against the code, not against the summary.** Every behavioural claim here carries a `file:line`. Where this plan says Python does something, read the line before writing the Go. Three places where reading the source changed this plan's own design are called out in the Rulings.

15. **Decide every lint finding in this plan, and re-lint after every `#nosec`.** This PR adds **no new `#nosec`** — 2c-2's single `G705` on the video write path is carried unchanged — and **two lint findings were fixed rather than suppressed** while this plan was written: a `bodyclose` at a `rig.tune` call site and an `S1025` `fmt.Sprintf("%s", []byte)`. Run `golangci-lint run ./...` from the repo root after every task and treat any finding as a stop.

16. **Run the four checks after every task, from the module root**, and treat any of the four failing as a stop:

    ```bash
    cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
    ```

    `gofmt` is not optional and is enforced by the linter's formatter section. Run `gofmt -w .` before staging.

17. **An ordering bug is not a data race, and `-race` is silent on every one of them.** This PR's three hardest defects — the last-client stop racing a new arrival, a delayed stop evicting a replacement channel, and a source goroutine started per attach and never stopped — were all found by tests that assert *outcomes* and *counts*, with `-race` green throughout. **Every goroutine hand-off this PR designs gets a concurrent test and a post-release goroutine count.**

18. **One mechanism per invariant.** 2c-2's review found that two mechanisms for one property made a break-check green because the other silently covered. Every break-check in the table at the end has exactly one thing to detect, and two of this plan's own break-checks did not redden on the first attempt — both are recorded, with what closed them.

19. **The borrowed-slice contract is asserted, not enforced, and this PR adds its consumers.** See Ruling R3. `Read` returns slice headers into the ring's own arrays; a consumer that writes into one corrupts every other reader at that position, and no tool in this repo can see it. Do not add such a consumer. 2c-6 and 2c-7 are the PRs most likely to want one.

20. **Do not widen the endpoint.** `GET /proxy/relay/channels` is the only `/proxy/relay/…` route this PR serves. The single-channel `GET`/`DELETE`, the client `DELETE` and `advance` are 2c-8's, and building them here would be the scope creep `CLAUDE.md` names as the main way this programme fails.

### The six ways a Go test can be green and meaningless

Every test this PR adds is bound by all six, and every task that adds an assertion ends with a **break-check**: patch the defect in, watch the test go red *for the right reason*, revert. **A break-check that does not go red is a finding, not a formality** — two of this plan's own failed to redden and both revealed a real hole, recorded in Rulings R6 and R9.

1. **The tautological oracle — a test whose expected value is computed by the code under test cannot fail.** Two sharp forms here. Every packet-position assertion is against `relaytest.PacketIndex`, an index the fixture embeds and no code under test reads. And the `?clients=all` payload is pinned against **a file Django's own serializer rendered**, not against a Go struct literal this PR also wrote.

2. **A pin that supplies the default pins nothing.** The rig sends `BUFFER_CHUNK_SIZE = 188 * 700`, a value the constant cannot produce (2c-2's own fix, carried); the join-point test sends `new_client_behind_seconds: 3`, not the default 5; the grace-window test sends `channel_shutdown_delay: 400ms`, not the default 0. **A test that supplied any of those defaults could not tell a working implementation from one that ignored the wire.**

3. **A test can go hollow without changing.** Ask of every assertion: *what edit to production code would make this fail?* Every break-check below names the edit and the expected failure text.

4. **A fixture that patches away the subject its docstring names.** `relaytest.NewUpstream` and `relaytest.NewControlPlane` are **sinks and sources**, not subjects: real HTTP servers the real client code really talks to. The rig never injects a fake ring or a fake manager.

5. **A substring assertion pins nothing when the string has more than one source.** Every error this PR defines is a named type or sentinel: `channel.ErrDuplicateClient`, `httpapi.ErrUnsupportedOutput`.

6. **A true positive for a false reason.** **When a break-check reddens, read the failure message and confirm it names the mechanism.** This PR's worked instance is in Ruling R6: a join-point test that stayed green when the join call was deleted, because it compared a wrapped packet index against an unwrapped chunk count.

### Working rules

- Run the four checks after every task (Global Constraint 16).
- Stage and commit in separate Bash calls; write commit messages to a file and use `-F`.
- Every commit message ends with the attribution lines this session was given.
- **Every Go file in this plan has been built, vetted, race-tested three times and linted at zero findings before this plan was written**, in a scratch module seeded from `main`'s `relay/` plus the 2c-2 plan's own appendices. Where you find a discrepancy, **your tree governs** — and report it, because it means 2c-2 merged differently from its plan.

---

## Rulings

Decisions this plan makes that the spec leaves open, that 2c-2 left to its successor, or that the tree contradicts. Each is binding; each names what it was decided against.

### R1 — The fan-out is one broadcast per publish, not per-client notification, and the number says why.

2c-2's `Ring.Wait` blocks on a channel that `Write` closes and replaces, so **every publish wakes every waiter**. The alternative is a registry of per-client notification channels with a non-blocking send to each, which trades one `close` for N sends plus registration and deregistration bookkeeping under a lock.

**Ruled: keep the broadcast.** The arithmetic, with every input's source:

| Input | Value | Source |
|---|---|---|
| Chunk size | 255,868 bytes | `apps/proxy/config.py:15` |
| Reference bitrate | 10 Mbit/s = 1,250,000 byte/s | `relay/buffer/buffer.go`'s sizing note (stated, not measured) |
| Publishes per second per channel | 1,250,000 / 255,868 = **4.9** | derived |
| Concurrency target | **1,600** | `docker/uwsgi.relay.ini`'s `gevent = $(DISPATCHARR_RELAY_GEVENT)`, default 1600 — what the Python relay is sized for and therefore what the Go relay must match |

Worst case is every one of those 1,600 clients on one channel: 4.9 × 1,600 ≈ **7,800 goroutine wakeups per second**, each a list-traversal entry off a closed channel. That is noise next to what the same publish costs in bytes — 255,868 × 1,600 = **409 MB written to sockets per chunk**, which is bandwidth-bound by four orders of magnitude. **There are also no spurious wakeups**: a waiter blocks only when it is caught up, and a publish is exactly the event it is waiting for, so every wakeup does work. Per-client notification would add cost and remove nothing.

**What is NOT ruled here**, because it is not the wakeup: a slow reader's *hold* on evicted chunks. That is R2.

### R2 — `Read` is capped at twenty chunks, and the cap is ported from Python for a reason 2c-2 only half-had.

2c-2 declined to port `get_optimized_client_data`'s batching (`input/buffer.py:325-372`) on the grounds that its four constants exist to amortise a Redis round trip per chunk, and an in-memory ring has no round trip to amortise. **That is right about three of the four constants and wrong about `MAX_CHUNKS`.**

`MAX_CHUNKS` bounds how much a lagging reader **holds at one instant**, and a held chunk's backing array stays alive after the ring has evicted it — the garbage collector keeps it exactly as long as someone holds it, which is `Chunk.Data`'s own documented contract. Uncapped, one reader behind the head takes `[cursor+1, head]` in a single `Read`, so it can pin a whole ring's worth of evicted chunks on top of the resident ring: **2 × `MaxBytesPerChannel`, about 146 MiB**, where `relay/buffer/buffer.go`'s own sizing note states 73 MiB per channel. Capped, the extra is at most twenty chunks — about 5 MiB — per *distinct* lagging cursor, and readers at the same cursor share one set of arrays.

**Ruled: `MaxChunksPerRead = 20`, `input/buffer.py:333`, and only that one.** `MIN_CHUNKS`, `TARGET_SIZE` and `MAX_SIZE` stay unported with 2c-2's reason intact. Note what reading the Python actually says about the cap's worth: `MAX_SIZE` (2 MiB) gates only the **second, top-up** fetch and never the initial `min(chunks_behind, MAX_CHUNKS)` one (`input/buffer.py:348-371`, read in full), so twenty chunks at the effective chunk size — 5,117,360 bytes — is what Python's cap is worth too.

**`Read`'s `next` moves with the cap**, and that is the half of this ruling most easily got wrong. 2c-2 returned `r.chunks[len-1].Index`, the ring's newest resident; with a cap those stopped being the same thing, and a `next` that ran ahead of the bytes actually handed over would make a lagging client skip everything it did not receive — silently, with no `skipped` to log. `next` is now the index of the **last chunk returned**.

### R3 — The borrowed-slice contract stays asserted rather than enforced, and N readers do not change that.

2c-2's R7 left this as an explicit input for 2c-3: `Read` returns slices into the ring's own arrays, Go has no read-only slice, and `-race` cannot see a violation — two goroutines writing different bytes of one array is not a race on any address, and one goroutine writing a chunk nobody is reading at that instant is not a race at all.

Two enforcement options were weighed. **A copy-out API** (`Read` returns fresh buffers) makes the contract unbreakable and deletes spec D2's entire fan-out argument: 1,600 clients × 255,868 bytes per chunk is 409 MB of copying per chunk where the design specifies "N slice headers over one backing array, no refcounting and no copy per client". **An ownership token** — a handle a consumer must return before the next `Read` — is expressible but enforces nothing at compile time and only detects misuse a consumer already committed.

**Ruled: the contract stays in `Read`'s doc comment and in a content assertion, strengthened to the N-reader case.** `TestAChunkIsUnchangedAfterEveryClientHasServedIt` has eight readers take the same chunk, checks they were handed **the same backing array** (so the test would be checking nothing if the fan-out had quietly started copying), forces forty evicting writes, and compares every reader's held bytes against a snapshot.

**And the gap is stated rather than papered over**, because it is the one thing in this package the tooling will not catch: the assertion covers the **writer** reusing an array, not a **consumer** mutating one. Nothing in this PR mutates a chunk — `writeChunks` passes each slice to `w.Write`, which the standard library does not modify — but nothing would catch it if a later one did. **2c-6 (fMP4 muxing) and 2c-7 (Output Profile piping) are the PRs most likely to want to**, and `Read`'s doc comment is aimed at them.

### R4 — 2c-3 takes `channel_shutdown_delay` off the wire, which 2c-2 deferred to 2c-8.

2c-2 wired `ManagerConfig.ShutdownDelay` and left it unsupplied, reasoning that reading it "belongs with the teardown 2c-8 owns, where the re-check window can actually be tested against a reconnecting client". **That condition is met here and not in 2c-8**: a reconnecting client is a second client, and second clients arrive in this PR.

**Ruled: `channel_shutdown_delay` joins the four keys `tuningFrom` already requires, and the field moves from `ManagerConfig` to `Tuning`.** The move matters: the delay is a channel-start-time setting like the other three, snapshotted at `publish` (parity-matrix row 5), and leaving it on the manager would make it the one setting a running channel picks up late. `TestTheShutdownDelayKeepsAChannelForAReconnectingClient` supplies 400 ms, not the default 0, because a test supplying the default cannot tell a working grace window from no grace window at all.

### R5 — The last-client rule and the arrival path are one decision under one lock. This is a defect in the 2c-2 plan, demonstrated.

2c-2's `release` reads:

```go
func (m *Manager) release(c *Channel) {
	if remaining := c.dropClient(); remaining > 0 {
		return
	}
	if m.cfg.ShutdownDelay <= 0 {
		m.Stop(c.id)
		return
	}
	...
}
```

`dropClient` takes the channel's lock; `m.Stop` takes the manager's. **Between them a new client can call `claim`, be handed the channel, and have it torn down underneath them** — a 200 with a few bytes, no re-tune and no error, for as long as clients keep churning. With the default `ShutdownDelay` of 0 that window is every release. `-race` reports nothing: it is an ordering bug.

Measured against this plan's own code with the two statements separated: **round 16 of 400**, `the arriving client holds a channel the manager does not (channel one state=stopped clients=1 head=0 vs <nil>): it was stopped underneath a live client`.

**Ruled: `release` takes `m.mu`, drops the client, and decides whether to detach in the same critical section.** `claim` registers its client under the same lock, so the two are mutually exclusive by construction rather than by timing. The delayed half, `stopIfIdle`, takes the count and removes the entry under one lock for the same reason.

**And `detachLocked` checks identity, not just the id.** By the time a delayed stop fires the map may hold a *different* `*Channel` under the same id — the first finished, `claim` dropped it, a later tune published a replacement. Deleting by id alone evicts a live successor and strands its clients on a channel nothing can stop. Break-check BC2 below reddens on exactly that.

### R6 — A test whose oracle wraps is not a test. The join-point assertion needs an asset longer than the run.

The first draft of `TestASecondClientJoinsBehindLiveAndNotAtTheHead` compared the second client's first `PacketIndex` against the ring's head converted to packets. **Deleting the `Ring.Join` call from `serveClient` entirely left it green.**

The reason: `PacketIndex` is the packet's position **in the asset**, and a looping upstream restarts it at zero. With a 4,096-packet asset — 3.1 seconds at the nominal rate — the index wrapped several times inside the test while the head kept counting up, so "how far behind live did this client start" compared a number in `[0, 4096)` against one that grows without bound. It is large and positive whatever the relay does.

**Ruled: `rigAssetPackets = 65536`** — 12.3 MB, 49 seconds at the nominal rate, longer than any test here runs — **and the fix is recorded in the constant's own comment**, because the next person to shrink the asset for speed will reintroduce it. With it, the same break-check reddens: `the second client started at packet 8400 with the live head at packet 8400: it joined AT live, not behind it -- new_client_behind_seconds was ignored`.

### R7 — The list endpoint carries the provider URL, and that is parity rather than a credential leak.

`channel_status.py:472` puts `ChannelMetadataField.URL` — the provider URL, credentials in its path or query — into `get_basic_channel_info`'s payload, and `/proxy/stats/` and the Stats page show it. Global Constraint 12 forbids a provider URL in a log, an error message or an HTTP response body.

**Ruled: emit it, exactly as Python does, and state the distinction rather than leaving a reviewer to infer it.** The constraint's target is a **log** (a broad, long-lived, unauthenticated-by-default audience) and a **public error body**. `GET /proxy/relay/channels` is neither: it is an internal route gated on the static `X-Dispatcharr-Internal` **and** a per-request bound token, reachable only by a caller holding `SECRET_KEY`, and it carries this URL today. Omitting it would blank the Stats page's URL column for every Go-served channel — a behaviour change D5 forbids — and would not remove the exposure, because the detail endpoint 2c-8 builds carries it too.

What does **not** change: `writeTuneFailure` answers with a fixed string per class of failure, `channel.withoutURL` strips `*url.Error`'s copy before it reaches a log, and no log line in this PR names a URL.

### R8 — The client registry carries seven fields, not the spec's eight, and `worker_id` and `last_active` wait for 2c-8.

Spec § The contract lists the Redis client hash's fields as `user_id`, `output_format`, `output_profile_id`, `ip_address`, `user_agent`, `connected_at`, `last_active`, `worker_id`. **That is the hash, not this endpoint's payload.** `RelayChannelClientSerializer` (`apps/proxy/relay_serializers.py:22-31`) declares seven, and neither `last_active` nor `worker_id` is among them; both appear only on `RelayDetailClientSerializer`, which renders the **detail** endpoint 2c-8 builds.

**Ruled: `channel.Client` carries exactly the seven the list endpoint renders.** Adding two fields nothing reads is the stale-duplicate-of-the-truth shape 2c-2's R5 refused, and the per-client byte counters (`bytes_sent`, `avg_rate_KBps`, `current_rate_KBps`) go with them for the same reason. **2c-8 owns all five**, together with the detail endpoint and `owner`'s asymmetric `'unknown'` default that parity-matrix row 14 pins.

### R9 — `owner` is `null` on the list endpoint, and the assertion for it has to be on the handler's output.

`get_basic_channel_info` sets `'owner': metadata.get(OWNER)` unconditionally — always present, null when no worker holds the lease. Spec D2 deletes the election outright, so a Go relay has no worker to name. The alternative — synthesising a process identity — invents a value with no Python source.

**Ruled: `owner` is always present and always `null`.** No consumer reads it: grepped across `frontend/src` (**zero** hits for the word) and across `relay_client`'s two readers of this payload, `list_channels` and `live_connections`, which take `channel_id` and `clients`. The **asymmetry** parity-matrix row 14 pins — the detail endpoint defaulting to the literal string `'unknown'` — is 2c-8's to carry.

**And the assertion goes on the LIVE payload, not on the golden fixture.** The break-check that made `describeChannel` name a process identity left the golden tests green, because they compare a struct literal that hard-codes a nil owner against a file that says `null`; neither runs the handler. One line in `TestTheLiveEndpointProducesTheGoldensKeySet` closed it. **That is this plan's second break-check that did not redden**, and it is the reason the live key-set test exists at all.

### R10 — An unsupported output format or Output Profile is refused 501, not served as MPEG-TS under the wrong label.

The authorize hop sets `X-Relay-Output-Format` on **every** tune — `apps/proxy/authorize.py:501` computes it unconditionally, falling back to `CoreSettings.get_default_output_format()` — and `X-Relay-Output` when an Output Profile resolved. 2c-3 serves MPEG-TS passthrough only; fMP4 is 2c-6's and Output Profiles are 2c-7's.

**Ruled: a non-empty `X-Relay-Output`, or an `X-Relay-Output-Format` that is neither empty nor `mpegts`, is refused with 501**, the same shape and the same reasoning as 2c-2's `ErrNotProxyKind`. Recording `"fmp4"` in the registry and then writing MPEG-TS would be wrong in a way nothing on the wire says; serving it under the label `"mpegts"` would be a lie in the payload `/proxy/stats/` renders. The registry records what the relay actually served.

---

## The 2c-2 dependency ledger

**2c-2 is planned but NOT implemented** (`docs/phase2c2-plan`, PR #284, ready). Every row below is "as planned in 2c-2" unless it says otherwise, and **Task 0 re-derives every one of them against the merged tree** — a plan that assumed an unmerged plan would land unchanged is the same mistake as assuming a draft branch would not move. Rows marked **verified against `main`** were checked with `git show "f2714383:<path>"` and are 2c-1 as built.

| What this PR depends on | Status | If it differs |
|---|---|---|
| Module `github.com/D10Scot/Dispatcharr/relay` at `relay/`, Go 1.27.1 | **verified against `main` `f2714383`** | every import path below moves |
| `buffer.TSPacketSize`, `ChunkBytes`, `RetentionSeconds`, `JoinBehindSeconds`, `MaxChunksPerChannel`, `MaxBytesPerChannel`, `ChunksForBytes` | **verified against `main`** | Task 1's edits need re-deriving |
| `control.HeaderAuthorized`, `HeaderInternal`, `HeaderInternalRequest`, `RelayTrustToken`, `InternalPrincipalToken`, `IsRelayTrusted`, `InternalRequestHeader` | **verified against `main`** | Tasks 5 and 6 call these by name |
| `control.IsInternalPrincipal(secret, value)` and `VerifyInternalRequest(secret, header, method, fullPath, body, now)` | **verified against `main`** — 2c-1 built them and 2c-2's ledger deliberately did not use them; **this PR is their first consumer** | Task 6 cannot gate the list route; stop and report |
| `httpapi.Config{DevRoutes bool}`, `New(Config) *Server`, `(*Server).Handler()` | **verified against `main`** | Task 6's wiring moves |
| `.golangci.yml` at the repo root, v2 schema, `gosec` excluded in `_test.go` only, `noctx` **not** excluded | **verified against `main`** | every lint outcome here is re-derived |
| `go-tests.yml` running build, vet, `-race`, lint, the stdlib check, with a `Go result` aggregate and a change detector matching `^relay/` | **verified against `main`** | Task 0 reports it; this PR adds no workflow change |
| `buffer.Ring` with `New`, `Write`, `Read(cursor)`, `Join(behind)`, `Wait(ctx, cursor)`, `Head`, `Oldest`, `Closed`, `Close`, `ResetPosition`, and `chunksFor` | **as planned in 2c-2; re-derive against the merged tree** | Task 1 edits `Read` and adds a counter; a different `Read` signature changes Task 1 wholesale |
| `channel.Source`, `ProxySource`, `ErrUpstreamIdle`, `ErrUpstreamStatus`, `withoutURL`, `State` and its eight constants, `Tuning{ChunkBytes, Retention, JoinBehind}` | **as planned in 2c-2** | Tasks 2 and 4 edit these files |
| `channel.Channel` with `ID`, `Ring`, `Tuning`, `State`, `Err`, `Clients`, `Done`, `run`, `markActive`, `stop`, `setState`, `addClient`, `dropClient` | **as planned in 2c-2** | Task 2 replaces the client counter with a registry |
| `channel.Manager` with `NewManager`, `Attach(id, start)`, `claim`, `publish`, `releaseGate`, `Get`, `Stop`, `StopAll`, `ids`, `release`, `take` | **as planned in 2c-2** | Task 3 changes `Attach`'s signature and rewrites `release` |
| `control.Settings` with `Int`, `Float`, `Seconds`, `String` and `ErrSettingAbsent`; `control.Client.NextSource`; `Unavailable`, `Refused`, `ErrNotConfigured`; `KindProxy` | **as planned in 2c-2** | Task 5 calls all of these |
| `httpapi.StreamDeps`, `StreamHandler`, `channelIDFor`, `startProxyTune`, `writeTuneFailure`, `serveClient`, `writeChunks`, `tuningFrom`, `ErrNotProxyKind`, `ErrNoSource` | **as planned in 2c-2** | Task 5 rewrites `channelIDFor` into `identify` and adds two arms to `writeTuneFailure` |
| `relaytest.SyntheticTS`, `PacketIndex`, `AlignmentProblem`, `PacketSize`, `NominalByteRate`, `NewUpstream`, `Config`, `Upstream.Requests`/`Headers`, `NewControlPlane`, `ControlPlaneConfig`, `EffectiveProxySettings` | **as planned in 2c-2** | every test here builds on them |
| `relaytest.EffectiveProxySettings()` carries `channel_shutdown_delay` | **as planned in 2c-2** (value 0) | Task 5's per-key subtest needs it; add it if absent |
| Amendment **A2** in the spec, and rows 7 and 9 of the parity matrix carrying Go references | **as planned in 2c-2** | Task 11 appends **A3** after it; Task 9 appends to rows 8, 10 and 13 |
| `scripts/check_go_stdlib_only.sh` with 2c-2's Redis `go list -deps` check | **as planned in 2c-2** | Task 12 extends nothing; it re-runs it |

**Verified in this tree, not inherited:** everything with a `file:line` in this plan — `apps/proxy/live_proxy/client_manager.py` in full, `output/ts/generator.py`'s positioning, keepalive, timeout, ghost and per-client-stats paths, `input/buffer.py`'s `get_optimized_client_data` and `find_chunk_index_by_time`, `channel_status.py`'s `get_basic_channel_info` and `build_live_channel_stats_data`, `relay_serializers.py` in full, `relay_views.py`'s `channels_view`, `relay_client.py`'s `list_channels` and `live_connections`, `apps/proxy/authorize.py:145-147` and `:483-503`, `apps/proxy/config.py:110-114`, `docker/supervisord/all.conf`, `docker/tests/test-puid-pgid.sh:482`, and the fact that `ChannelMetadataField.LOGO_ID` is **written nowhere in the tree**.

---

## File Structure

```
relay/buffer/ring.go                    EDIT — MaxChunksPerRead, Read's cap and cursor, the byte counter
relay/buffer/fanout_test.go             NEW  — the cap, the N-reader immutability rule, N readers under -race
relay/channel/client.go                 NEW  — the registry's row type
relay/channel/tuning.go                 EDIT — ShutdownDelay joins the snapshot
relay/channel/channel.go                EDIT — clients map, SourceInfo, startedAt, ClientSnapshot, ErrDuplicateClient
relay/channel/manager.go                EDIT — Started, Attach takes a client, release/stopIfIdle/detachLocked, Snapshot
relay/channel/source_proxy.go           EDIT — the built transport releases its idle connections
relay/channel/fanout_test.go            NEW  — six tests, three of them concurrent
relay/httpapi/stream.go                 EDIT — identify(), ErrUnsupportedOutput, mintClientID, the Started shape
relay/httpapi/channels.go               NEW  — GET /proxy/relay/channels and its internal-auth gate
relay/httpapi/server.go                 EDIT — ControlDeps and the second dev route
relay/httpapi/fanout_test.go            NEW  — the rig, the fan-out test, row 8, row 10, the cap, the auth gate
relay/httpapi/golden_test.go            NEW  — the cross-implementation payload pin
relay/httpapi/testdata/channels_clients_all.json   NEW — rendered by Django's serializer
relay/main.go                           EDIT — wire ControlDeps

                                        --- the Python half ---
apps/proxy/tests/test_relay_list_payload_golden.py  NEW — renders and pins the golden from both sides

                                        --- infrastructure ---
docker/tests/test-puid-pgid.sh          EDIT — the role-'all' program list gains relay-uwsgi and relay-go

                                        --- documents ---
docs/relay-parity-matrix.md             EDIT — rows 8, 10 and 13 gain a Go reference
docs/superpowers/specs/2026-09-09-…-design.md   EDIT — Amendment A3, a Done log row
CLAUDE.md                               EDIT — § Architecture, § Known defects
```

Nothing under `core/`, `dispatcharr/`, `frontend/`, `e2e/` or `metrics/` is touched, and nothing under `apps/` beyond the one new test file.

---
## Task 0: Diff the merged 2c-2 tree against this plan's expectations

**Nothing else is written until this task is done and reported.** The ledger above was written against the 2c-2 *plan*, which at the time of writing was not implemented. Every "as planned in 2c-2" row is a prediction; this task turns each into a fact or a finding.

- [ ] **Step 1: Confirm the module, the toolchain and the tree**

  ```bash
  cd <your worktree>/relay && cat go.mod && go version && golangci-lint version
  ```

  Expect module `github.com/D10Scot/Dispatcharr/relay`, `go 1.27.1`, golangci-lint 2.13.2. **A `require` line or a non-empty `go.sum` is a stop**, not something to work around.

- [ ] **Step 2: Confirm every symbol this PR calls by name**

  ```bash
  cd <your worktree>/relay && grep -rn "^func \|^type \|^const \|^var " \
    buffer/ring.go channel/channel.go channel/manager.go channel/source_proxy.go \
    channel/tuning.go channel/state.go control/settings.go control/nextsource.go \
    httpapi/stream.go internal/relaytest/*.go | sed 's/{$//'
  ```

  Against the ledger, check in particular:

  | Symbol | Expected shape | If it differs |
  |---|---|---|
  | `(*Ring).Read` | `func (r *Ring) Read(cursor uint64) (chunks [][]byte, next uint64, skipped uint64)` | Task 1 rewrites its body; a different signature makes Task 1 a redesign — stop and report |
  | `(*Ring).Join` | `func (r *Ring) Join(behind time.Duration) uint64` | Task 5's `serveClient` calls it |
  | `(*Manager).Attach` | `func (m *Manager) Attach(id string, start func() (Source, Tuning, error)) (*Channel, func(), error)` | Task 3 changes it to take a `*Client` and return a `Started`; if 2c-2 already changed it, reconcile and report |
  | `(*Manager).release` | drops the client, then calls `Stop` | if it already takes `m.mu` across both, Ruling R5's defect was fixed in 2c-2's own review — say so and keep the tests |
  | `(*Channel).clients` | an `int` | Task 2 replaces it with a map |
  | `Tuning` | three fields | Task 2 adds a fourth |
  | `control.VerifyInternalRequest` | present and exported | Task 6 cannot gate the route without it |

- [ ] **Step 3: Confirm the settings the rig sends**

  ```bash
  cd <your worktree>/relay && grep -n "channel_shutdown_delay\|BUFFER_CHUNK_SIZE\|new_client_behind_seconds" internal/relaytest/controlplane.go
  ```

  `EffectiveProxySettings()` must carry `channel_shutdown_delay`. If it does not, add it with value `0` and the source `core/models.py:726` — Task 5 requires the key and the per-key test needs it present in the complete answer it removes one key from.

- [ ] **Step 4: Confirm CI already covers what this PR adds**

  ```bash
  cd <your worktree> && grep -n "relay/\|check_go_stdlib_only\|Go result" .github/workflows/go-tests.yml
  ```

  This PR adds no workflow change. If the change detector does not fire on `^relay/`, that is a finding for the PR description, not something to fix here.

- [ ] **Step 5: Run the four checks on the tree as merged**

  ```bash
  cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
  ```

  **A red tree here is a stop.** Everything below assumes a green baseline, and a failure you inherit will look like one you caused.

- [ ] **Step 6: Report**

  Every ledger row that did not match, and which task absorbs it. Do not start Task 1 until this is reported.

---
## Task 1: `relay/buffer` — the bounded read and the byte counter

Ruling R2 caps the read. The byte counter is what lets Task 6's payload carry `total_bytes` and the two bitrate fields rather than omitting them and leaving a reviewer unable to tell "absent because the channel never had it" from "absent because this PR did not do it".

- [ ] **Step 1: Add `MaxChunksPerRead` and rewrite `Read`'s selection loop**

  In `relay/buffer/ring.go`, above `ErrClosed`:

  ```go
  // MaxChunksPerRead bounds how many chunks one Read hands back.
  //
  // The port of get_optimized_client_data's MAX_CHUNKS
  // (apps/proxy/live_proxy/input/buffer.py:333), and the ONLY one of that
  // function's four constants 2c-3 ports. MIN_CHUNKS, TARGET_SIZE and MAX_SIZE
  // exist to amortise a Redis round trip per chunk, and an in-memory ring has
  // no round trip to amortise -- 2c-2's reasoning, unchanged. MAX_CHUNKS is
  // different in kind: it bounds how much a lagging reader HOLDS at one
  // instant, and a held chunk's backing array stays alive after the ring has
  // evicted it. Uncapped, one reader behind the head can pin a whole ring's
  // worth of evicted chunks on top of the resident ring -- 2 x
  // MaxBytesPerChannel, about 146 MiB, where 2c-1's sizing note states 73 MiB.
  // Capped, the extra is at most 20 chunks, about 5 MiB, per DISTINCT lagging
  // cursor; readers at the same cursor share one set of arrays.
  //
  // 20 chunks at the default chunk size is 5,117,360 bytes, which is what the
  // Python cap is worth too: MAX_SIZE (2 MiB) gates only the SECOND, top-up
  // fetch, never the initial min(chunks_behind, MAX_CHUNKS) one
  // (input/buffer.py:348-371, read in full).
  const MaxChunksPerRead = 20
  ```

  Then replace `Read`'s doc comment and its selection loop. **The whole method, as it must read afterwards:**

  ```go
  // Read returns up to MaxChunksPerRead resident chunks after cursor.
  //
  // cursor is the LAST CONSUMED index, Python's local_index convention. next is
  // the cursor to pass to the following call -- the index of the LAST CHUNK
  // ACTUALLY RETURNED, not the ring's head, because the batch cap means those
  // are no longer the same thing. skipped is how many indices were lost to
  // eviction before the first chunk returned.
  //
  // THE RETURNED SLICES ARE BORROWED. They alias the ring's own backing arrays
  // and a caller must never write into one: a published chunk is shared by
  // every reader at that position, so one consumer mutating it corrupts every
  // other. Go has no read-only slice and -race cannot see this (two goroutines
  // writing different bytes of one array is not a race on any address), so the
  // contract lives here and in TestAChunkIsUnchangedAfterEveryClientHasServedIt.
  func (r *Ring) Read(cursor uint64) (chunks [][]byte, next uint64, skipped uint64) {
  	r.mu.RLock()
  	defer r.mu.RUnlock()

  	if len(r.chunks) == 0 {
  		return nil, cursor, 0
  	}
  	oldest := r.chunks[0].Index
  	want := cursor + 1
  	if want < oldest {
  		skipped = oldest - want
  		want = oldest
  	}
  	if want > r.head {
  		return nil, cursor, skipped
  	}

  	out := make([][]byte, 0, min(len(r.chunks), MaxChunksPerRead))
  	last := cursor
  	for _, c := range r.chunks {
  		if c.Index < want {
  			continue
  		}
  		if len(out) == MaxChunksPerRead {
  			break
  		}
  		out = append(out, c.Data)
  		last = c.Index
  	}
  	return out, last, skipped
  }
  ```

  **`last` starts at `cursor`, not at zero.** A read that returns nothing must hand back the caller's own cursor unchanged; returning zero would rewind every caught-up client to the start of the channel on every empty poll.

  2c-2's `TestReadReportsWhatEvictionSkipped` writes twelve chunks into an eight-chunk ring, so it returns eight — inside the cap — and must still pass unchanged. **If it fails, the refactor is wrong, not the test.**

- [ ] **Step 2: Add the byte counter**

  On the `Ring` struct, after `closed bool`:

  ```go
  	// total is every byte the upstream has handed this ring, including the
  	// partial packet not yet published. The in-memory equivalent of the
  	// metadata hash's total_bytes (apps/proxy/live_proxy/channel_status.py:510),
  	// which the status endpoints render and derive avg_bitrate_kbps from.
  	total uint64
  ```

  In `Write`, increment it on **both** paths — the early return where nothing completes a packet, and the main path:

  ```go
  	if complete == 0 {
  		r.total += uint64(len(p))
  		r.partial = combined
  		return len(p), nil
  	}
  	r.total += uint64(len(p))
  	r.pending = append(r.pending, combined[:complete]...)
  ```

  **Both, not one.** Counting only the completing path would under-report a trickling upstream by everything still sitting in the partial packet, which is exactly the case `total_bytes` is read on.

  And the accessor, above `Oldest`:

  ```go
  // TotalBytes is every byte the upstream has written to this ring.
  func (r *Ring) TotalBytes() uint64 {
  	r.mu.RLock()
  	defer r.mu.RUnlock()
  	return r.total
  }
  ```

  `uint64(len(p))` draws no `gosec` finding: verified, `golangci-lint run ./...` stays at 0 issues. `len` cannot be negative and `G115` does not fire on this shape.

- [ ] **Step 3: Write `relay/buffer/fanout_test.go`**

  **The complete file is Appendix A.** Three tests:

  | Test | What it pins | Oracle |
  |---|---|---|
  | `TestReadIsCappedAndItsCursorFollowsTheBytes` | the cap **and** that `next` follows the bytes handed over | `relaytest.PacketIndex`, over the two reads concatenated |
  | `TestAChunkIsUnchangedAfterEveryClientHasServedIt` | **R3** — D2's immutability rule at the fan-out that makes it matter | a byte-for-byte snapshot per reader, after forty evicting writes |
  | `TestManyConcurrentReadersAndOneWriter` | the lock discipline across all six reader methods | **`-race` is the oracle** |

  Two things in the first test are load-bearing. It writes **40 chunks into a 64-chunk ring**, so the cap is the only thing that can bound the read — a fixture that overflowed the ring would be testing eviction. And it asserts on **position** via the embedded index, over the two reads concatenated, so a cap that dropped or reordered a chunk fails where a length check would not.

  The second test's first assertion is the one that keeps it honest:

  ```go
  	// Every reader holds a slice of the SAME array -- that is the design, and
  	// if it were not, this test would be checking nothing.
  	if &held[0][0][0] != &held[readers-1][0][0] {
  		t.Fatal("two readers were handed different backing arrays for one chunk: " +
  			"the fan-out is copying, which is not what spec D2 specifies")
  	}
  ```

- [ ] **Step 4: Break-check, four edits**

  Every one was run against this plan's own code. The expected message is what you must see.

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | delete `if len(out) == MaxChunksPerRead { break }` | `TestReadIsCappedAndItsCursorFollowsTheBytes` | `one Read returned 40 chunks with 40 resident, want 20 -- a lagging reader can pin a whole ring's worth of evicted chunks` |
  | 2 | `return out, last, skipped` becomes `return out, r.chunks[len(r.chunks)-1].Index, skipped` | the same test | `next = 40 after a capped read, want 20 -- the cursor ran past the bytes the caller was actually given and the rest of the stream is lost` |
  | 3 | a `scratch []byte` **field** on `Ring`, allocated once and reused for every chunk | `TestAChunkIsUnchangedAfterEveryClientHasServedIt` | `byte N of a chunk reader M still holds changed from …: a published chunk's backing array was reused` |
  | 4 | drop the `RLock` from `TotalBytes` | `TestManyConcurrentReadersAndOneWriter` | `WARNING: DATA RACE`, with both stacks |

  **Number 3 carries 2c-2's own caveat forward**: allocating the reused buffer as a **local** inside `Write` does not redden it, because a test that writes one chunk per call never exercises reuse within a call. The defect shape that matters is a field.

  **There is no break-check here for the total-bytes counter**, and that is deliberate rather than an omission: it is asserted end to end in Task 6's payload tests, where `total_bytes` being absent or zero is what a reader of `/proxy/stats/` would actually notice. A unit test here would assert that a counter counts.

- [ ] **Step 5: Run the four checks and commit**

---
## Task 2: `relay/channel` — the client registry

Spec D2's `Client registry` key-family row: `live:channel:{id}:clients` (a SET with a TTL), `live:channel:{id}:clients:{cid}` (a hash with the same TTL), the per-channel heartbeat thread that refreshed both, and `ClientManager.remove_ghost_clients`, replaced by a map.

- [ ] **Step 1: Write `relay/channel/client.go`**

  **The complete file is Appendix B.** Read its doc comment before writing it: it is the argument for why the TTL, the heartbeat and the ghost sweep dissolve rather than port, and a reviewer will reasonably expect a port of all three.

  The argument in one paragraph, because it is the task's whole justification. Those three mechanisms exist for one failure: a uWSGI worker dies holding clients and its Redis keys outlive it, so a SET entry with no live reader has to be swept (`client_manager.py:446-482`) and a hash with no heartbeat has to expire (`CLIENT_RECORD_TTL`, `apps/proxy/config.py:110`). With one process and the registry in its own memory, a client entry **cannot** outlive the goroutine that made it — `serveClient`'s deferred release runs on every return path including a panic, and if the process dies there is no registry left to sweep. A TTL here would be a timer with nothing to catch.

  **What does NOT dissolve, and belongs in the PR description's divergence list:** a client whose TCP peer vanished with no FIN is held until its socket write fails or the kernel gives up. **Python holds such a client just as long**, and reading the guards is what establishes that rather than assuming it: the heartbeat thread refreshes the TTL for every id in `self.clients` regardless of progress ("Only refresh TTL - do NOT update last_active", `client_manager.py:143`), `last_active` is refreshed by the client's own yield path (`output/ts/generator.py:517`), and `_is_timeout` is gated on a health flag only 2c-5 lowers. The behaviours match.

  Seven fields, per Ruling R8 — `ID`, `UserID`, `IPAddress`, `UserAgent`, `OutputFormat`, `OutputProfileID`, `ConnectedAt`. **`last_active`, `worker_id` and the three per-client byte counters are 2c-8's**, with the detail endpoint that renders them.

- [ ] **Step 2: `ShutdownDelay` joins `Tuning`**

  In `relay/channel/tuning.go`, a fourth field. Ruling R4 is the reason it lives here rather than on `ManagerConfig`: it is a channel-start-time setting like the other three, snapshotted at `publish` (parity-matrix row 5), and leaving it on the manager would make it the one setting a running channel picks up late.

  ```go
  	// ShutdownDelay is how long a channel with no clients stays up, from
  	// channel_shutdown_delay. 2c-3 supplies it; see the plan's Ruling R4.
  	ShutdownDelay time.Duration
  ```

  **Delete `ShutdownDelay` from `ManagerConfig`** in the same edit. Leaving both is the stale-duplicate shape, and the compiler will not tell you which one a caller meant.

- [ ] **Step 3: Rewrite `relay/channel/channel.go`**

  **The complete file is Appendix C.** Four changes to 2c-2's version:

  1. `clients int` becomes `clients map[string]*Client`. `Clients()` returns `len`, `addClient` takes a `*Client` and **reports whether the id was free**, `dropClient` takes an id.
  2. `ErrDuplicateClient`, a package-level sentinel. The port of `client_manager.py:218-221`, whose `add_client` returns `False` for an id already in `_registered_clients`; `views.py:748-753` turns that `False` into a 503.
  3. `SourceInfo` and the `source` field: what the next-source answer said about the stream, kept so the status endpoints render it without a second control-plane call. Exactly the fields `get_basic_channel_info` reads out of the metadata hash. **`StreamProfileID` is an `int` here and renders as a STRING** on the wire, because the metadata hash stores `str(source["stream_profile"]["id"])` (`input/manager.py:2165`) and the serializer declares `CharField`.
  4. `startedAt` and `ClientSnapshot()`.

  `ClientSnapshot`'s ordering is a decision with a reason, and the comment carries it:

  ```go
  // DETERMINISTIC ORDER, where Python's is arbitrary: channel_status.py:533
  // reads a Redis SET with SMEMBERS and slices the first ten of whatever order
  // that returned, so no order is the contract and any deterministic one is
  // parity. It is deterministic here because a golden-file comparison against
  // the Python serializer needs it to be, and because "the ten clients the list
  // shows" being a stable set is strictly better than a set that reshuffles
  // between polls.
  ```

  And `Clients()` carries the cap's other half:

  ```go
  // Never capped, matching channel_status.py:461's SCARD: the LIST is capped at
  // ten without ?clients=all, the COUNT never is.
  ```

- [ ] **Step 4: Break-check, two edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | delete `addClient`'s `if _, taken := c.clients[cl.ID]; taken { return false }` | `TestASecondAttachUnderAnAttachedClientIDIsRefused` (Task 3) | `a second attach under the id "dup" returned <nil>, want ErrDuplicateClient` |
  | 2 | `ClientSnapshot` returns the map in range order | `TestTheListPayloadMatchesDjangosSerializer` **may stay green** — the golden fixture has one client per ordering-sensitive channel. Report the gap rather than adding a second client to force it; the ordering is for the test's determinism, not a contract, and a test that asserted it would be asserting this plan's own choice |

  **Number 2 is listed precisely because it is expected not to redden**, and saying so is the point. Ordering is not a parity property; determinism is a testing convenience, and inventing an assertion for it would pin a decision rather than a behaviour.

- [ ] **Step 5: Run the four checks and commit**

---
## Task 3: `relay/channel` — the manager's arrival and departure, under one lock

Ruling R5. This is the task the ordering tests exist for, and the one where `-race` is no help at all.

- [ ] **Step 1: Rewrite `relay/channel/manager.go`**

  **The complete file is Appendix D.** Five changes to 2c-2's version:

  1. **`Started`**, a struct the start function returns, replacing the three-value `(Source, Tuning, error)`. It carries `Info SourceInfo` as well, which the list endpoint needs and which a fourth return value would have made unreadable.
  2. **`Attach(id string, client *Client, start func() (Started, error))`**. The client is registered inside `claim`, under `m.mu`, which is what makes the arrival path and the departure path mutually exclusive.
  3. **`claim` returns a fourth value, an error**, so a duplicate client id is refused at the point the map is inspected rather than in a second, unsynchronised step.
  4. **`release`, `stopIfIdle` and `detachLocked`**, replacing 2c-2's `release` and `take`.
  5. **`Snapshot()`**, every channel in id order, which Task 6's list endpoint reads.

  The three-function departure path, in full, because it is the whole ruling:

  ```go
  // release drops one client and, when it was the last, stops the channel --
  // immediately, or after the shutdown delay.
  //
  // THE DROP AND THE DECISION HAPPEN UNDER ONE LOCK, and that is the whole of
  // this function. An earlier shape dropped the client, saw zero remaining, and
  // then called Stop: between those two statements a new client could claim the
  // same channel, be handed it, and have it torn down underneath them -- an
  // empty 200 with no re-tune. claim registers its client under m.mu too, so
  // taking the count and removing the map entry in the same critical section is
  // what makes the two mutually exclusive. -race sees none of this; it is an
  // ordering bug, which is why TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel
  // exists.
  func (m *Manager) release(c *Channel, clientID string) {
  	m.mu.Lock()
  	remaining := c.dropClient(clientID)
  	stop := false
  	if remaining == 0 && c.tuning.ShutdownDelay <= 0 {
  		stop = m.detachLocked(c)
  	}
  	m.mu.Unlock()

  	if stop {
  		c.setState(StateStopping, nil)
  		c.stop(m.cfg.StopWait)
  		return
  	}
  	if remaining == 0 && c.tuning.ShutdownDelay > 0 {
  		time.AfterFunc(c.tuning.ShutdownDelay, func() { m.stopIfIdle(c) })
  	}
  }

  // stopIfIdle is the delayed half of release: the grace window expired, so stop
  // the channel unless somebody reconnected inside it.
  //
  // The port of ChannelService.cancel_pending_shutdown
  // (services/channel_service.py:103-127), which Python spells as a Redis
  // timestamp a reconnecting client deletes. Here the reconnect simply registers
  // a client, and this check sees it -- under the same lock that registered it,
  // so there is no window between "nobody is watching" and "the entry is gone".
  func (m *Manager) stopIfIdle(c *Channel) {
  	m.mu.Lock()
  	stop := c.Clients() == 0 && m.detachLocked(c)
  	m.mu.Unlock()
  	if !stop {
  		return
  	}
  	c.setState(StateStopping, nil)
  	c.stop(m.cfg.StopWait)
  }

  // detachLocked removes c from the map if the map still holds THIS channel, and
  // reports whether it did. Callers hold m.mu.
  //
  // The identity check is load-bearing. By the time a delayed stop fires, the
  // map may hold a DIFFERENT channel under the same id: the first one finished,
  // claim dropped it, and a later tune published a replacement. Deleting by id
  // alone would evict a live successor and leave its clients attached to a
  // channel nothing can stop.
  func (m *Manager) detachLocked(c *Channel) bool {
  	if m.channels[c.id] != c {
  		return false
  	}
  	delete(m.channels, c.id)
  	return true
  }
  ```

  **The lock order is always manager then channel**, and nothing takes them the other way round: `release` calls `c.dropClient` (channel lock) while holding `m.mu`, `stopIfIdle` calls `c.Clients()` the same way, and `claim` calls `c.addClient`. `c.stop` is called with `m.mu` **released**, because it waits up to `StopWait` for a goroutine.

  **Everything 2c-2 ruled about `Attach` is preserved and must stay preserved.** `start()` runs outside the manager lock; the per-channel gate is closed from a **deferred** call registered in `Attach` **before** `start()` runs, so it fires at `Attach`'s return, after `publish` has installed the channel; `claim` drops a channel whose ring has closed, and that is the only place it happens. Moving the gate's close into a helper around `start()` wakes a waiter that then races the map insertion, claims a fresh gate and opens a **second** upstream — 2c-2 measured it going wrong within three rounds at eight concurrent clients.

- [ ] **Step 2: Write `relay/channel/fanout_test.go`**

  **The complete file is Appendix E.** Six tests, three of them concurrent:

  | Test | What it pins |
  |---|---|
  | `TestNClientsShareOneSourceAndTheChannelOutlivesAllButTheLast` | six clients, **one** source, and the channel surviving every release but the last |
  | `TestASecondAttachUnderAnAttachedClientIDIsRefused` | **row 13's first half** — registration is idempotent per client id |
  | `TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel` | **R5's ordering**, 400 rounds |
  | `TestTheShutdownDelayKeepsAChannelForAReconnectingClient` | **R4** — the grace window, supplied non-default at 400 ms |
  | `TestADelayedStopNeverEvictsAReplacementChannel` | `detachLocked`'s identity check |
  | `TestConcurrentAttachAndReleaseLeaksNoGoroutine` | **Constraint 17** — 50 rounds × 8 clients, with a goroutine count after every release |

  Two fixtures are load-bearing and both were arrived at by a test failing first.

  **`waitForStart` polls; it does not read immediately.** `publish` starts the source goroutine and returns without waiting for the scheduler, so asserting the count straight after `Attach` races Go's runtime rather than the code — and it reports **zero** where the defect being hunted reports two, which is a failure message pointing at the wrong thing. Measured: three runs out of three failed this way before the poll went in.

  **The goroutine count polls DOWN to a target, not to two equal samples.** A winding-down goroutine set is briefly stable at any value, so an equal-samples settle reports whatever it happened to catch — it reported "5 then 113" in 0.06 s on a tree that was genuinely leaking, and would have reported a clean number on a tree that was not. `settleTo` returns the lowest count reached inside its deadline.

  The ordering test's central assertion is worth reading before you write it, because what it does **not** assert is as considered as what it does:

  ```go
  		// Either the arrival won the race and holds the ORIGINAL channel, or
  		// it lost and started a fresh one. Both are correct. What is never
  		// correct is holding a channel the manager has dropped: nothing could
  		// stop it, and its ring is already closing under the reader.
  		if got := m.Get("one"); got != second {
  			t.Fatalf("round %d: the arriving client holds a channel the manager does not (%v vs %v): "+
  				"it was stopped underneath a live client",
  				round, second.Describe(), got)
  		}
  ```

- [ ] **Step 3: Break-check, three edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | `release` drops the client **before** taking `m.mu`, and takes the lock only around `detachLocked` | `TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel` | `round 16: the arriving client holds a channel the manager does not (channel one state=stopped clients=1 head=0 vs <nil>): it was stopped underneath a live client` |
  | 2 | `detachLocked`'s `m.channels[c.id] != c` becomes a bare presence check | `TestADelayedStopNeverEvictsAReplacementChannel` | `the first channel's delayed stop evicted the replacement: the map holds <nil>, want the channel the live client is watching` |
  | 3 | `if remaining == 0 && c.tuning.ShutdownDelay <= 0` becomes `if remaining == 0` | `TestTheShutdownDelayKeepsAChannelForAReconnectingClient` | `the channel was stopped immediately: the shutdown delay did not apply` |

  **Number 1 reddened on round 16 of 400 on the machine this plan was written on.** It is a race, so the round number will differ; what must not differ is that it reddens within a few hundred rounds and that the message names a channel the manager does not hold. If it survives 400 rounds, say so rather than raising the count — and check first that `release` really is doing the two steps separately, because the edit is easy to apply in a way that keeps them adjacent.

- [ ] **Step 4: Run the four checks and commit**

---
## Task 4: `relay/channel` — the transport that was never closed

A defect in the 2c-2 plan's `ProxySource`, found by Task 3's goroutine test and fixed here because it is a two-line change in the file that caused it.

- [ ] **Step 1: Make `transport()` hand back a closer**

  `ProxySource.transport()` builds a fresh `http.Transport` on every `Run` and nothing ever closes it. A fresh transport per `Run` is **right** — one channel's upstream is one connection and must not share a pool with another channel's — but an unclosed one keeps its idle connection and that connection's `readLoop` and `writeLoop` goroutines alive until Go's own idle timeout, which is not set here. Two goroutines and a socket per finished channel.

  **Measured**: `TestConcurrentAttachAndReleaseLeaksNoGoroutine` went from 3 goroutines to **89** across 50 rounds without the fix and settles back to the baseline with it. Invisible with one channel, which is why 2c-2 could not have seen it.

  ```go
  // transport returns the round tripper to use and, when this call BUILT one,
  // the closer that releases its idle connections.
  //
  // A fresh http.Transport per Run is right -- one channel's upstream is one
  // connection and must not share a pool with another channel's -- but an
  // unclosed one keeps its idle connection and that connection's readLoop and
  // writeLoop goroutines alive until Go's own idle timeout, which is not set
  // here. That is two goroutines and a socket per finished channel, invisible
  // with one channel and measurable at fifty: TestConcurrentAttachAndRelease-
  // LeaksNoGoroutine went from 3 goroutines to 89 across 50 rounds without this
  // and settles back to the baseline with it.
  //
  // An injected Transport is NOT closed: the test that supplied it owns it.
  func (s ProxySource) transport() (http.RoundTripper, func()) {
  	if s.Transport != nil {
  		return s.Transport, func() {}
  	}
  	built := &http.Transport{
  		DialContext:           (&net.Dialer{Timeout: s.connectTimeout()}).DialContext,
  		ResponseHeaderTimeout: s.connectTimeout(),
  		MaxIdleConns:          1,
  		MaxConnsPerHost:       1,
  		DisableCompression:    true,
  	}
  	return built, built.CloseIdleConnections
  }
  ```

  And in `Run`, replacing the single line that built the client:

  ```go
  	roundTripper, closeIdle := s.transport()
  	defer closeIdle()

  	client := &http.Client{Transport: roundTripper}
  	response, err := client.Do(request)
  ```

  **`defer`, not a call at the end.** `Run` has eight return points and a `defer` covers all of them, including the one a `sink.Write` failure takes.

- [ ] **Step 2: Break-check, one edit**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | `return built, built.CloseIdleConnections` becomes `return built, func() {}` | `TestConcurrentAttachAndReleaseLeaksNoGoroutine` | `goroutines went from 3 to 94 across 50 rounds of 8 clients -- something started per attach is never stopped` |

  The numbers will differ; what must not is the shape — tens of goroutines, not a handful. **If it reddens at a number close to the tolerance, say so**: the test allows `before + 20` for `net/http`'s own idle connections, and a leak that only just clears that bar is a leak the tolerance is hiding.

- [ ] **Step 3: Run the four checks and commit**

---
## Task 5: `relay/httpapi` — who is asking, and what they may have

2c-2's `channelIDFor` read one trusted header. This task reads four, and refuses two things it cannot serve.

- [ ] **Step 1: Replace `channelIDFor` with `identify`**

  **The complete file is Appendix F.** `identify` resolves the channel id **and** builds the `*channel.Client` from the same trust decision, in one place, so there is no path on which a channel id is trusted and a client id is not.

  ```go
  // identify resolves which channel this request is for and who is asking.
  //
  // The four X-Relay-* values are read ONLY when X-Dispatcharr-Authorized proves
  // nginx put them there. Without that check any client could name any channel,
  // any client id, any address and any user by hand and bypass whatever the
  // authorize hop decided -- that marker is the entire reason
  // apps/proxy/authorize.py can be the only place the decision is made. An
  // untrusted request falls back to the path value and to values resolved here,
  // which is the dev shape; 2c-8 brings POST /_dispatcharr/authorize-internal.
  func identify(r *http.Request, secret string, now func() time.Time) (string, *channel.Client, error) {
  	trusted := control.IsRelayTrusted(secret, r.Header.Get(control.HeaderAuthorized))

  	header := func(name string) string {
  		if !trusted {
  			return ""
  		}
  		return r.Header.Get(name)
  	}
  	...
  ```

  **The `header` closure is the shape to keep.** Six call sites each writing their own `if trusted` is six chances to omit one, and the one omitted is the one that matters.

  The fallbacks, each with its Python source:

  | Value | Trusted source | Fallback | Source |
  |---|---|---|---|
  | channel id | `X-Relay-Channel` | the path value | `views.py`'s `<str:channel_id>` |
  | client id | `X-Relay-Client` | `mintClientID(now())` | `authorize.py:145-147` |
  | address | `X-Relay-Client-IP` | the socket's peer | parity-matrix row 17 |
  | user id | `X-Relay-User` | `"0"` | `client_manager.py:241` |
  | user agent | the request's own `User-Agent` (**not** trust-gated: it is the client's own header on every path) | `"unknown"` | `client_manager.py:236` |

  `mintClientID` matches `mint_client_id`'s **format** — `client_<unix millis>_<four digits>` — and uses `crypto/rand` rather than `math/rand`:

  ```go
  // crypto/rand rather than math/rand: gosec reports G404 on math/rand, and the
  // id is a handle an admin can stop a client by (DELETE
  // /proxy/relay/channels/<id>/clients/<client_id>, 2c-8), so guessability is
  // not nothing. Python's random.randint is what it is; matching the FORMAT is
  // the parity requirement, matching the generator is not.
  ```

- [ ] **Step 2: Refuse an output this relay does not serve**

  Ruling R10. A new error type and a new arm in `writeTuneFailure`:

  ```go
  // ErrUnsupportedOutput is returned when the authorize hop asked for an output
  // format or an Output Profile this relay does not serve.
  //
  // Refused rather than served, for 2c-2's reason on stream_profile.kind: a
  // relay that logged "fmp4" in its registry and then wrote MPEG-TS would be
  // wrong in a way nothing on the wire says. 2c-6 brings fMP4 and 2c-7 the
  // Output Profiles.
  type ErrUnsupportedOutput struct {
  	Format    string
  	ProfileID string
  }
  ```

  Answered **501**, alongside `ErrNotProxyKind`. `ErrDuplicateClient` gets its own arm answering **503**, matching `views.py:748-753`.

- [ ] **Step 3: `channel_shutdown_delay` joins the required keys**

  In `tuningFrom`, a fifth required read. The constant block gains `settingShutdownDelay = "channel_shutdown_delay"`. Global Constraint 13: **no Go-side default**, and `Seconds` fails on an absent key like the other four.

- [ ] **Step 4: Thread the client through the tune path**

  `StreamHandler` calls `identify`, passes the client to `Attach`, and passes it to `serveClient` so the fall-behind log names it. `startProxyTune` returns a `channel.Started` carrying the `SourceInfo` Task 6 renders. `StreamDeps` gains a `Now func() time.Time`, nil meaning `time.Now`.

  `serveClient`'s positioning comment gains the sentence that makes it row 8's call site:

  ```go
  	// POSITIONED ONCE, at setup, exactly as output/ts/generator.py:264-302
  	// positions a client -- and this is the call parity-matrix row 8 is
  	// about, because from 2c-3 onward the ring the client joins is usually
  	// one ANOTHER client has been filling. A JoinBehind of zero means the
  	// live head, which is what new_client_behind_seconds = 0 means there.
  ```

  And its doc comment gains the third omission, which is neither parity-deferred nor scope-cut but **unreachable**:

  ```go
  // AND NO GHOST-CLIENT DISCONNECT. output/ts/generator.py:579-581's
  // _is_ghost_client needs consecutive_empty > 100 AND the buffer 50 chunks
  // ahead of the client at the same instant -- a client 50 chunks behind whose
  // chunks exist is fed on its next read, which resets consecutive_empty, so the
  // two conditions are mutually exclusive outside the expiry window
  // find_oldest_available_chunk already recovers from. Not ported, and the
  // reason is that it is unreachable rather than that it is 2c-5's.
  ```

  The `skipped > 0` branch gains its Python citation: it is the jump `find_oldest_available_chunk` performs (`input/buffer.py:407-452`), logged and never a disconnect, because **Python does not disconnect such a client either**.

- [ ] **Step 5: Break-check, three edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | delete the `if tuning.JoinBehind > 0 { cursor = ring.Join(...) }` branch | `TestASecondClientJoinsBehindLiveAndNotAtTheHead` (Task 8) | `the second client started at packet 8400 with the live head at packet 8400: it joined AT live, not behind it -- new_client_behind_seconds was ignored` |
  | 2 | `header` returns `r.Header.Get(name)` unconditionally | `TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader` (Task 8), and 2c-2's `TestXRelayChannelIsIgnoredWithoutTheTrustMarker` | `the tune asked about /api/relay/channels/somebody-elses-channel/next-source: an unverified X-Relay-Channel was believed` |
  | 3 | `tuningFrom` falls back to a literal for `channel_shutdown_delay` | 2c-2's `TestEveryProxySettingThisRelayReadsIsRequired/channel_shutdown_delay` **only**, once its key list grows by one | `an answer missing only "channel_shutdown_delay" tuned with 200, want 502 -- the relay substituted a default of its own` |

  **Number 3 carries 2c-2's own caveat**: running it against a fixture missing several keys at once leaves the test green, because any one of them still fails the tune. The per-key subtest is the one with the property.

- [ ] **Step 6: Run the four checks and commit**

---
## Task 6: `relay/httpapi` — `GET /proxy/relay/channels`

The route `relay_client.list_channels` calls, and through it `relay_client.live_connections` — which `authorize_stream` reaches on **every** tune for a stream-limited user. Spec D4's whole argument rests on this one endpoint existing and answering like Python's.

- [ ] **Step 1: Write `relay/httpapi/channels.go`**

  **The complete file is Appendix G.** Three parts: the payload types, the handler, and `RequireInternal`.

  **The payload types are declared in the SERIALIZER's order, not the source dict's.** DRF renders in declaration order and so does `encoding/json`, so a struct laid out like `apps/proxy/relay_serializers.py` produces the same key order — which is not a contract, but makes a byte diff between the two readable when one is needed.

  **Presence is per field and is the part that is easy to get wrong.** DRF declares each optional field `required=False` with **no** `default=`, so `Field.get_attribute` raises `SkipField` for a key the source dict never set and the key vanishes from the JSON entirely rather than rendering as null. Which keys `get_basic_channel_info` sets unconditionally and which it sets inside an `if` is therefore the contract:

  | Field | Presence | Source |
  |---|---|---|
  | `channel_id`, `state`, `url`, `stream_profile`, `owner`, `buffer_index`, `client_count`, `uptime`, `started_at` | **always**; `state`, `owner`, `started_at` nullable | `channel_status.py:469-479` |
  | `clients` | **always**, `[]` when empty — never absent, never null | `:587` |
  | `channel_name`, `m3u_profile_id`, `stream_id`, `stream_name`, `total_bytes`, `avg_bitrate_kbps`, `avg_bitrate` | only when set | `:481-524` |
  | `client_id`, `user_agent` (nullable), `output_format`, `output_profile_id` (nullable) | **always**, per client | `:564-582` |
  | `ip_address`, `connected_at`, `user_id` | only when truthy, per client | `:570-577` |

  **Seventeen conditional fields are absent in 2c-3, and each absence has a reason rather than a gap.** The one worth knowing:

  ```
  logo_id        NEVER EMITTED BY PYTHON EITHER. ChannelMetadataField.LOGO_ID
                 is declared (constants.py:59) and read (channel_status.py:486)
                 and written NOWHERE in the tree, so the `if not raw: continue`
                 always continues. Exact parity by doing nothing.
  ```

  `healthy` needs `StreamManager.healthy` (2c-5's); `video_codec`, `resolution`, `source_fps`, `ffmpeg_speed`, `audio_codec`, `audio_channels` and `stream_type` are ffmpeg- or probe-derived (2c-4 and 2c-5).

  `total_bytes` and the two bitrate fields are derived exactly as `channel_status.py:510-524` derives them — the counter first, `avg_bitrate_kbps` only when uptime is positive, then the display string in Mbps above 1000 Kbps and Kbps at or below it, both to two decimal places.

  `owner` is `null`, per Ruling R9, with the grep that justifies it in the comment.

  **`RequireInternal` verifies both headers**, the same pair `apps/proxy/permissions.py`'s `IsInternalRelay` checks, and the bound token signs `r.URL.RequestURI()`:

  ```go
  		// The bound token signs r.URL.RequestURI(), which is Django's
  		// get_full_path(): the escaped path plus the query string. This route
  		// is reached WITH a query string (?clients=all) and without, and the
  		// two sign differently -- the correction spec section The contract
  		// records, and the reason it is not cosmetic.
  ```

  A refusal answers **403 with a fixed body** and names nothing.

- [ ] **Step 2: Wire it into `server.go` and `main.go`**

  `Config` gains `Control ControlDeps`, and the dev branch gains one route:

  ```go
  	if cfg.DevRoutes {
  		s.mux.Handle("GET /proxy/ts/stream/{channelID}", StreamHandler(cfg.Stream))
  		// Gated with the rest: nginx routes nothing to this process until
  		// stage 2d, and Django still calls the Python relay's copy of this
  		// route. 2c-8 brings the other four.
  		s.mux.Handle("GET /proxy/relay/channels",
  			RequireInternal(cfg.Control.Secret, cfg.Control.Now, ChannelsHandler(cfg.Control)))
  	}
  ```

  In `main.go`, build the manager **once** and hand the same pointer to both `StreamDeps` and `ControlDeps`. Two managers would give the list endpoint an empty map and no test in this PR would notice, because every test builds its own rig:

  ```go
  	channels := channel.NewManager(channel.ManagerConfig{})
  	srv := &http.Server{
  		Addr: net.JoinHostPort("0.0.0.0", strconv.Itoa(cfg.Port)),
  		Handler: httpapi.New(httpapi.Config{
  			DevRoutes: cfg.DevRoutes,
  			Stream: httpapi.StreamDeps{
  				Secret:   cfg.Secret,
  				Channels: channels,
  				Control:  &control.Client{Secret: cfg.Secret},
  			},
  			Control: httpapi.ControlDeps{Secret: cfg.Secret, Channels: channels},
  		}).Handler(),
  		ReadHeaderTimeout: 10 * time.Second,
  		IdleTimeout:       120 * time.Second,
  	}
  ```

  **Keep 2c-2's `ReadHeaderTimeout` and `IdleTimeout` and their comments.** Neither touches a stream in flight; a stream is one request that has not finished.

- [ ] **Step 3: Run the four checks and commit**

---
## Task 7: the golden payload — rendered by Django, asserted by both

The oracle for Task 6. Hollow shape 1 in its sharpest form: a Go test comparing a Go encoder against a Go struct literal proves the encoder is deterministic and nothing else.

- [ ] **Step 1: Write `apps/proxy/tests/test_relay_list_payload_golden.py`**

  The Python half does three things, and the third is what stops the fixture going stale:

  1. Builds a `payload` dict by hand, exercising every present/absent/null case: two channels, one with every conditional field set and two clients (one fully populated, one with nothing optional), one minimal with no conditional fields and no clients.
  2. Renders it through `RelayChannelListSerializer` and DRF's `JSONRenderer`, and asserts the result equals the committed `relay/httpapi/testdata/channels_clients_all.json` — **compared as parsed JSON, not as bytes**, for the reason Step 3 states.
  3. Asserts the fixture's **completeness**: every field `RelayChannelSerializer` declares is either present on the fully-populated channel, or named in an explicit `NOT_SERVED_BY_2C3` set with a one-line reason. A hand-written fixture that quietly omitted a field would otherwise pin a payload narrower than the contract.

  ```python
  # Every RelayChannelSerializer field 2c-3 does not produce, and why. A field
  # in neither this set nor the fixture fails the completeness test, which is
  # what stops the golden from silently narrowing as the endpoint grows.
  NOT_SERVED_BY_2C3 = {
      "logo_id": "ChannelMetadataField.LOGO_ID is written nowhere in the tree, "
                 "so Python never emits it either (constants.py:59, "
                 "channel_status.py:486)",
      "healthy": "needs StreamManager.healthy, which arrives in 2c-5",
      "video_codec": "ffmpeg-derived, 2c-4",
      "resolution": "ffmpeg-derived, 2c-4",
      "source_fps": "ffmpeg-derived, 2c-4",
      "ffmpeg_speed": "ffmpeg-derived, 2c-4",
      "audio_codec": "ffmpeg-derived, 2c-4",
      "audio_channels": "ffmpeg-derived, 2c-4",
      "stream_type": "set by channel_service from the probed input format, 2c-5",
  }
  ```

  Run it with the label the router picks for `apps/proxy/`:

  ```bash
  cd <your worktree> && python manage.py test apps.proxy.tests.test_relay_list_payload_golden
  ```

  **This is the only task that needs the shared test container.** Re-read Global Constraint 10 before the first edit.

- [ ] **Step 2: Regenerate the golden file from Django, on your own tree**

  Do not trust this plan's committed file — regenerate it, because it is the oracle and the whole point is that it comes from the *other* implementation. The test in Step 1 writes it when `DISPATCHARR_WRITE_GOLDEN=1` is set and asserts against it otherwise:

  ```bash
  cd <your worktree> && DISPATCHARR_WRITE_GOLDEN=1 python manage.py test \
      apps.proxy.tests.test_relay_list_payload_golden
  git diff --stat relay/httpapi/testdata/channels_clients_all.json
  ```

  **If the regenerated file differs from the committed one, yours governs** — and report it, because it means this plan's reading of `RelayChannelSerializer` was wrong somewhere, which is exactly what the exercise is for.

- [ ] **Step 3: Write `relay/httpapi/golden_test.go`**

  **The complete file is Appendix H.** Three tests:

  | Test | What it pins |
  |---|---|
  | `TestTheListPayloadMatchesDjangosSerializer` | the whole payload against the file Django rendered |
  | `TestEveryOptionalFieldIsAbsentRatherThanNull` | the presence contract, **field by field**, so a failure says which key moved |
  | `TestTheLiveEndpointProducesTheGoldensKeySet` | that the **handler** builds the shape, not just a struct literal |

  **The comparison is decoded, not byte-for-byte, and that is a decision with one known consequence:**

  ```go
  // Decoded rather than byte-compared, and that is a decision with one known
  // consequence: DRF renders a Python float as "5.0" where encoding/json
  // renders float64(5) as "5". Decoding both sides into map[string]any makes
  // each a float64 and the spellings equal, which is right, because every
  // consumer parses -- relay_client._request calls .json() and api.js parses --
  // and none compares bytes. What the decode does NOT lose is the part that
  // matters: an absent key stays absent, a null stays nil, and a string stays
  // a string, so the presence contract is still fully pinned.
  ```

  **Record the float spelling in the PR description as a stated wire divergence.** It is textual, no consumer can observe it, and forcing `5.0` out of `encoding/json` would need a custom marshaller on every float field — machinery with no reader.

  The three tests are three mechanisms for three different things, which is why none of them subsumes another: the first catches a value or a key changing, the second says *which*, and the third catches the handler and the shape diverging. Ruling R9 records what happened when only the first two existed.

- [ ] **Step 4: Break-check, three edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | `json:"url"` gains `,omitempty` | `TestTheListPayloadMatchesDjangosSerializer` **and** `TestEveryOptionalFieldIsAbsentRatherThanNull` | `channel 1 has no "url": get_basic_channel_info sets it on every path, so it must never be omitted` |
  | 2 | `describeChannel` sets `owner` to a process identity | `TestTheLiveEndpointProducesTheGoldensKeySet` **only** | `the handler reported owner relay-go, want null -- spec D2 deletes the ownership election, so there is no worker to name` |
  | 3 | `OutputProfileID` loses its pointer and becomes an `int` | `TestEveryOptionalFieldIsAbsentRatherThanNull` | `a client with no Output Profile reports 0, want null` |

  **Number 2 is this plan's second break-check that did not redden**, and the reason is worth carrying. The two golden tests compare a struct literal that hard-codes a nil owner against a file that says `null`; **neither runs the handler**. Ruling R9's one-line assertion on the live payload is what closed it, and it is why the live key-set test is not redundant with the other two.

- [ ] **Step 5: Run the four checks and the three backend labels this touches, then commit**

---
## Task 8: `relay/httpapi` — the fan-out, end to end

The tests a reviewer reads first. Everything before this task is machinery; this is where N clients on one channel becomes an assertion.

- [ ] **Step 1: Write the rig**

  **The complete file is Appendix I.** `newRig` stands up a whole fake deployment — a provider, a Django, this process's mux, and a **real** `httptest.Server` in front of it. Not `httptest.NewRecorder`: the subject is a long-lived streaming response, and a recorder buffers the whole body and returns only once the handler has finished, so every assertion about a client reading while the upstream still runs would be impossible.

  Three constants carry decisions:

  ```go
  	// A chunk size the constant cannot produce, so a relay ignoring the wire
  	// value is detectable. 2c-2 shipped this rig sending 255868 -- the
  	// constant itself -- which disarmed the whole end-to-end layer against the
  	// one property Amendment A1.4 exists to prove.
  	rigChunkBytes = buffer.TSPacketSize * 700
  	// LONG ENOUGH THAT PacketIndex NEVER WRAPS inside a test, and that is
  	// what makes the join-point assertion able to fail at all. [Ruling R6]
  	rigAssetPackets = 65536
  ```

  `rig.tune` sends the trust marker and all four `X-Relay-*` values when given a client id, and none of them when given `""` — which is how the untrusted path is driven. `rig.listChannels` mints both internal headers, signing the **full path including the query string**.

  `packetRun` is the shared oracle: it reads N whole packets, checks alignment, and checks that **every packet follows the one before it** by the index the fixture embedded, returning the first. A helper that checked only alignment would pass on a stream with gaps.

- [ ] **Step 2: Write the six tests**

  | Test | What it pins |
  |---|---|
  | `TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint` | **the fan-out**: six concurrent clients, **one** provider request, six unbroken runs, join points inside one ring |
  | `TestASecondClientJoinsBehindLiveAndNotAtTheHead` | **row 8**, at the case the row is about |
  | `TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked` | **D4** — the cap, `?clients=all` lifting it, and `client_count` never capped |
  | `TestTheListEndpointRefusesAnUnsignedOrMissignedCall` | the internal gate, four ways |
  | `TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader` | the trust marker gates **every** `X-Relay-*` value, not just the channel |
  | `TestTheLiveEndpointProducesTheGoldensKeySet` (Task 7) | the handler builds the shape |

  **The fan-out test's structure is the part to get right.** Every client tunes first, synchronously, so all six are attached before any reads; then six goroutines read concurrently. Tuning inside the goroutines would let a client attach after another had already released, which is a different property.

  Its closing assertion is deliberately loose about *where* each client joined and strict about the one thing that matters:

  ```go
  	// Every client's run came from the same writer, so their join points are
  	// all inside the window the ring held -- at most the ring's capacity apart.
  ```

  A tighter assertion would pin scheduling. **What is strict is `r.Upstream.Requests() != 1`**, which is parity-matrix row 10's actual claim measured at the provider, and each client's run being unbroken, which `packetRun` checks packet by packet.

  **The row-8 test's arithmetic, stated because its tolerance looks generous and is not arbitrary.** The upstream is paced at 1.0 × nominal, 250,000 byte/s. `new_client_behind_seconds` is sent as **3**, not the default 5. Three seconds is 750,000 bytes, 3,989 packets. The assertion is that the second client started between a quarter and four times that far behind live — "behind by about the configured window", not a stopwatch, because the ring's chunk granularity (700 packets) and the scheduler both move the true figure. **What it is strict about is `behindPackets <= 0`**, which is the whole claim: a client that joined *at* live fails outright.

  The auth test drives four cases and the third is the one that earns its place: **a token signed for the bare path, sent with a query string**. `?clients=all` is the exact route spec D4's argument rests on, and a client that signed the bare path would 403 on every call — the correction § The contract records, verified here rather than assumed.

- [ ] **Step 3: Break-check, five edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | `ChannelsHandler`'s `limit` is always `-1` | `TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked` | `"" listed 13 clients, want 10 -- the cap is 10 and ?clients=all lifts it` |
  | 2 | `RequireInternal` skips `VerifyInternalRequest` | `TestTheListEndpointRefusesAnUnsignedOrMissignedCall`, **three of four subtests** | `answered 200, want 403 -- the internal surface authorised a call that did not carry a valid bound token` |
  | 3 | `identify`'s `header` closure ignores `trusted` | `TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader` | `the tune asked about /api/relay/channels/somebody-elses-channel/next-source: an unverified X-Relay-Channel was believed` |
  | 4 | delete `serveClient`'s `ring.Join` branch | `TestASecondClientJoinsBehindLiveAndNotAtTheHead` | `the second client started at packet 8400 with the live head at packet 8400: it joined AT live, not behind it -- new_client_behind_seconds was ignored` |
  | 5 | `Attach` calls `start()` unconditionally before consulting the map | `TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint` | `the provider saw N requests for one channel, want 1 -- parity-matrix row 10` |

  **Number 2 reddens three subtests and not the fourth.** "No headers at all" still fails on `IsInternalPrincipal`, which the edit leaves in place. That is correct and worth confirming rather than reading as a partial break: two mechanisms, each with its own subtest, and the edit removes exactly one.

  **Number 4 is the one that did not redden in this plan's first draft** (Ruling R6). If it stays green on your tree, check `rigAssetPackets` before touching anything else.

- [ ] **Step 4: Run the four checks, then the whole suite three times**

  ```bash
  cd <your worktree>/relay
  for i in 1 2 3; do go test -race -count=1 ./... || echo "RUN $i FAILED"; done
  ```

  Three clean runs. This PR is the first with real concurrency at N, so a test that passes once and not three times is a flake to fix now. **Verified clean three times against this plan's own code**, at roughly 1.2 s (`buffer`), 3.0 s (`channel`) and 8.5 s (`httpapi`).

- [ ] **Step 5: Commit**

---
## Task 9: the parity matrix — rows 8, 10 and 13 get their Go pin

Amendment A2.2 makes this a one-line edit per row, in the existing `Pin` cell, with no guard change and no sixth column.

**Tasks 1 through 8 must be committed before this task.** `testRefProblem` resolves each `.go` reference by opening the named file and looking for `^func\s+…<name>\s*\(`, so a matrix edit landing before the test files exist fails the guard naming a file that is not there.

- [ ] **Step 1: Read the three rows before editing them**

  ```bash
  cd <your worktree> && grep -n '^| 8 \|^| 10 \|^| 13 ' docs/relay-parity-matrix.md
  ```

  Re-read the editing rules in the file's own HTML comment first: **one row is one line**, cells are **never padded**, no stored counts, and **do not run a Markdown formatter over this file**.

- [ ] **Step 2: Append the Go reference to each**

  | Row | Claim | Append to its `Pin` cell |
  |---|---|---|
  | 8 | a new client joins roughly 5 s behind live | `` `relay/httpapi/fanout_test.go::TestASecondClientJoinsBehindLiveAndNotAtTheHead` ``, and alongside it 2c-2's two `Ring.Join` unit tests, which Amendment A2.3 says this row should cite: `` `relay/buffer/ring_test.go::TestJoinStartsRoughlyBehindLive` ``, `` `relay/buffer/ring_test.go::TestJoinFallsBackToTheOldestChunkWhenTheBufferIsShort` `` |
  | 10 | three clients share exactly one upstream connection, and closing every client releases it | `` `relay/httpapi/fanout_test.go::TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint` `` **and** `` `relay/channel/fanout_test.go::TestNClientsShareOneSourceAndTheChannelOutlivesAllButTheLast` `` |
  | 13 | client registration is idempotent per client id, and a ghost is removed | `` `relay/channel/fanout_test.go::TestASecondAttachUnderAnAttachedClientIDIsRefused` `` |

  **Row 10 needs two references because it asserts two things** — the sharing and the release — and the matrix's own Notes cell already says so. The first test measures the sharing at the provider; the second measures the release, by asserting the channel survives every departure but the last and that no source is left running.

  **Row 13's second half — the ghost sweep — has no Go pin and must not be given a fake one.** Ruling R8 and Task 2's doc comment establish that the TTL, the heartbeat and the sweep have no analogue in a one-process registry, so there is nothing for a Go test to assert. **Append a sentence to row 13's Notes cell** saying so, naming spec D2's `Client registry` row:

  > The Go pin covers the idempotence half only. The ghost sweep has no Go analogue: spec D2 puts the registry in process memory, where a client entry cannot outlive the goroutine that made it, so the TTL and the heartbeat that the sweep exists to backstop are deleted rather than ported (2c-3).

- [ ] **Step 3: Do not touch rows 14 or 17**

  Both are tempting and both are 2c-8's. Row 14 pins the **asymmetry** between the list and detail endpoints (`owner` null on one and `'unknown'` on the other, `source_fps` a float on one and a string on the other), and a PR that ships only the list endpoint cannot pin an asymmetry. Row 17 pins `ip_address` on **both** status endpoints. Half a row is not a row.

- [ ] **Step 4: Run the guard**

  ```bash
  cd <your worktree>/e2e && npx playwright test --project=guards parity-matrix
  ```

  It needs no container. It prints the pinned / owed / white-box counts on every run; **the owed list must stay empty**, because Gate 1 closed in 2b-3 and an `owed:` row would redden a closed gate.

- [ ] **Step 5: Commit**

---
## Task 10: the `all` role's program list, which has been wrong since Phase 1

2c-1's review said 2c-2 or 2c-3 owns this. 2c-2 did not take it, so it is here.

- [ ] **Step 1: Read what the rung actually runs**

  ```bash
  cd <your worktree> && cat docker/supervisord/all.conf && sed -n '480,490p' docker/tests/test-puid-pgid.sh
  ```

  `all.conf`'s `[include] files =` names **ten** programs: `postgres redis api-uwsgi relay-uwsgi relay-go daphne celery-default celery-dvr celery-beat nginx`. `docker/tests/test-puid-pgid.sh:482` asserts **eight**, and the two it omits are `relay-uwsgi` — **stale since Phase 1 PR 4 gave the relay its own process** — and `relay-go`, which 2c-1 added.

- [ ] **Step 2: Add both, and fix the message**

  ```bash
  for prog in postgres redis api-uwsgi relay-uwsgi relay-go daphne celery-default celery-dvr celery-beat nginx; do
  ```

  and

  ```bash
                  log_pass "supervisorctl status: all ten programs of role 'all' RUNNING"
  ```

  **The count in the message is part of the assertion, not decoration.** A list that grows while the message still says "eight" is how the omission survived a whole phase.

  **`relay-go` is the reason this matters now rather than as tidying.** 2c-1's own fix round found, through this very script, that `relay-go` could not read `/data/jwt` once it dropped privilege under a non-root PUID/PGID — and the script did not assert `relay-go` was running, so it caught that by a different route. The assertion is what makes the next such failure fail here rather than in production.

- [ ] **Step 3: Note what is NOT changed**

  The other `RUNNING` checks in the file — the startup wait at `:193` and the fallback at `:313` — poll `api-uwsgi` specifically and are correct as they are: they are waiting for the container to be up, not asserting the roster.

- [ ] **Step 4: Commit**

  This file is exercised by `lifecycle-tests.yml`'s `suites` job in full mode, which a `migration/**` branch triggers. **Do not run it locally unless you have the time**: it builds and boots containers.

---
## Task 11: the spec amendment, `CLAUDE.md`, and the Done log

- [ ] **Step 1: Write Amendment A3 into the spec**

  In `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, after Amendment A2 (which 2c-2 added):

  ```markdown
  #### Amendment A3 (2c-3) — five corrections and inputs from the fan-out

  **A3.1 — the client registry's TTL, heartbeat and ghost sweep are DELETED,
  not ported, and the key-family table's "Becomes" cell understates it.** The
  table gives `clients`, `client_metadata` and `client_stop` as "the control
  API's in-memory client map". What it does not say is that
  `CLIENT_RECORD_TTL`, `CLIENT_HEARTBEAT_INTERVAL`, `GHOST_CLIENT_MULTIPLIER`
  and `ClientManager.remove_ghost_clients` go with them. Those exist for one
  failure — a uWSGI worker dies holding clients and its Redis keys outlive it
  (`client_manager.py:446-482`, `apps/proxy/config.py:110-113`) — and with one
  process and the registry in its own memory a client entry cannot outlive the
  goroutine that made it. **A consequence for `CLAUDE.md` § Known defects**:
  `xc_get_info`'s per-handshake `?clients=all` call no longer triggers an
  `SREM` write across every running channel, because there are no ghosts to
  sweep. The defect closes as a side effect of D2 rather than being fixed.

  **A3.2 — `get_optimized_client_data`'s MAX_CHUNKS IS ported, and the other
  three constants are not.** 2c-2 declined the batching on the grounds that it
  amortises a Redis round trip. True of `MIN_CHUNKS`, `TARGET_SIZE` and
  `MAX_SIZE`; not true of `MAX_CHUNKS` (`input/buffer.py:333`), which bounds
  how much a lagging reader HOLDS at one instant. Uncapped, one reader can pin
  a whole ring's worth of evicted chunks on top of the resident ring — 2 x
  `MaxBytesPerChannel`, about 146 MiB per channel, where the sizing note in
  `relay/buffer/buffer.go` states 73 MiB. `buffer.MaxChunksPerRead = 20`.

  **A3.3 — `channel_shutdown_delay` lands in 2c-3, not 2c-8.** 2c-2 wired the
  field and deferred reading it to "where the re-check window can actually be
  tested against a reconnecting client". A reconnecting client is a second
  client, and second clients arrive in 2c-3. The field moves from
  `ManagerConfig` to `channel.Tuning`, because it is a channel-start-time
  setting like the other three (parity-matrix row 5).

  **A3.4 — an input for 2c-8: five client fields and the detail endpoint's
  asymmetries.** 2c-3 ships `GET /proxy/relay/channels` only. The client
  registry carries the seven fields `RelayChannelClientSerializer` renders and
  NOT `last_active`, `worker_id`, `bytes_sent`, `avg_rate_KBps` or
  `current_rate_KBps`, all five of which appear only on
  `RelayDetailClientSerializer`. 2c-8 adds them with the detail endpoint, and
  with them parity-matrix row 14's asymmetric `owner` default (`null` on the
  list endpoint, the literal string `'unknown'` on the detail one) and row 17's
  `ip_address` on both. 2c-3 pins neither row: half a row is not a row.

  **A3.5 — a stated wire divergence: float spelling.** DRF renders a Python
  float as `5.0`; Go's `encoding/json` renders `float64(5)` as `5`. The
  difference is textual and no consumer can observe it —
  `relay_client._request` calls `.json()` and `api.js` parses — so the golden
  fixture is compared as parsed JSON rather than as bytes, and forcing `5.0`
  out of `encoding/json` would need a custom marshaller on every float field.
  Recorded so a reviewer of a byte diff between the two relays is not
  surprised by it.
  ```

  **Then edit the 2c-5 and 2c-8 rows of the nine-PR table itself**, not prose beside them — 2c-1's Finding F2 established why. The 2c-8 row's "Remaining control routes (single-channel `GET`/`DELETE`, `advance`)" becomes "Remaining control routes (single-channel `GET`/`DELETE`, `advance`; the collection `GET` landed in 2c-3), the detail endpoint's five extra client fields and row 14's `owner` asymmetry (Amendment A3.4)".

  And add a Done log row for 2c-3.

- [ ] **Step 2: `CLAUDE.md`**

  Two edits, both short.

  In **§ Architecture**, after the sentence 2c-2 added about the Go ring: the Go relay's client registry is a map in process memory with no TTL, no heartbeat and no ghost sweep, because with one process a client entry cannot outlive the goroutine that made it; `GET /proxy/relay/channels[?clients=all]` is served from it and performs no write.

  In **§ Known defects**, on the `get_user_active_connections` bullet: note that the `SREM` side effect `xc_get_info` triggers per XC handshake has no Go analogue, so it disappears at the 2d cutover rather than being fixed.

  **Do not restate the design here.** `CLAUDE.md` is a map; the spec and this plan are the territory.

- [ ] **Step 3: Commit**

---
## Task 12: final verification and the PR description

- [ ] **Step 1: Confirm the scope of the diff, both directions**

  ```bash
  cd <your worktree> && git diff --stat main...HEAD
  ```

  Against the File Structure above. **Anything outside it is a finding** — in particular anything under `e2e/`, `frontend/`, `metrics/` or `.github/workflows/`.

- [ ] **Step 2: The stdlib and Redis guards**

  ```bash
  cd <your worktree> && scripts/check_go_stdlib_only.sh relay
  ```

  Must pass unchanged. This PR adds no dependency and no package named for Redis. **Confirm `go.sum` is still absent**, not merely empty.

- [ ] **Step 3: The full verification pass**

  ```bash
  cd <your worktree>/relay && gofmt -l . && go build ./... && go vet ./... && golangci-lint run ./...
  for i in 1 2 3; do go test -race -count=1 ./... || echo "RUN $i FAILED"; done
  ```

  `gofmt -l .` must print nothing. `golangci-lint` must report **0 issues**.

- [ ] **Step 4: Run the relay by hand once**

  ```bash
  cd <your worktree>/relay && DISPATCHARR_RELAY_GO_DEV_ROUTES=1 \
    DISPATCHARR_RELAY_GO_PORT=5658 DJANGO_SECRET_KEY=hand-run-secret go run .
  ```

  In another shell, confirm `/healthz` answers 200 and that a tune against a channel the control plane cannot answer for fails with a body that names **no URL and no variable value**. A hand run is what catches a wiring mistake every unit test's own rig papers over — 2c-2 found its two managers-instead-of-one class of bug exactly this way.

- [ ] **Step 5: The Redis key-family walk, in the spec's own units**

  Spec § Stage 2c: *"If any family is found, during implementation, not to fit this walk cleanly, the implementing PR says so honestly rather than asserting the invariant met."*

  | Spec family row | Python keys | Becomes, in this PR |
  |---|---|---|
  | **Client registry** | `clients` (a SET with a TTL), `client_metadata` (a hash with a TTL), and the heartbeat thread that refreshed both | `map[string]*Client` on the `Channel`, under its own mutex; the TTL, the heartbeat and `remove_ghost_clients` **deleted** (Amendment A3.1) |
  | **Timing/telemetry, partially** | `last_client_disconnect` | `Tuning.ShutdownDelay` plus `time.AfterFunc`; the other three (`connection_attempt`, `last_data`, `transcode_active`) are untouched and are 2c-4/2c-5's |

  `client_stop` is **not** closed here: it is what `DELETE /proxy/relay/channels/<id>/clients/<client_id>` writes, and that route is 2c-8's. Say so rather than counting the family closed.

- [ ] **Step 6: Write the PR description**

  It must carry, in this order:

  1. **What this PR does**, in one paragraph.
  2. **The three defects found in the 2c-2 plan's own code**, each with the measurement: the release-then-stop ordering bug (round 16 of 400), the unclosed `http.Transport` (3 goroutines to 89 across 50 rounds), and `Read`'s cursor running ahead of a capped batch.
  3. **The two break-checks that did not redden**, and what closed each.
  4. **The stated divergences**, as a list: the float spelling (A3.5); `owner` always null (R9); no `healthy` and seven ffmpeg-derived fields absent (2c-4/2c-5); no ghost sweep, which removes the `SREM` side effect `CLAUDE.md` records (A3.1); `Read`'s borrowed-slice contract still asserted and not enforced (R3); and a client whose TCP peer vanished with no FIN held until the write fails, which matches Python.
  5. **The Redis key-family walk** from Step 5, including what is NOT closed.
  6. **What this PR does not do**: no ffmpeg and no `shlex` port (2c-4); no failover, no `release`, no `events`, no degraded fallback, no Redirect (2c-5); no fMP4 (2c-6); no Output Profile (2c-7); no single-channel `GET`/`DELETE`, no client `DELETE`, no `advance`, no drain, no `HEALTHCHECK`, no `authorize-internal` fallback, no detail endpoint (2c-8); no coverage ratchet and no CodeQL Go pack (2c-9); no nginx route (2d); no rows 14 or 17; no `metrics/curated` update — milestones are per stage and the 2c goal milestone lands with 2c-9.

- [ ] **Step 7: Commit, and do not push or open a PR unless told to**

---

## Break-check × what each can redden

Every break-check in this plan, and the task it belongs to. A `✓` means it was run against this plan's own verified implementation and the message in the task table is the one that appeared.

| # | Task | The injected defect | What reddens | Verified |
|---|---|---|---|---|
| 1 | 1 | `Read` loses its `MaxChunksPerRead` break | `TestReadIsCappedAndItsCursorFollowsTheBytes`, on the chunk count | ✓ |
| 2 | 1 | `Read` returns the ring's head as `next` | the same test, on the cursor | ✓ |
| 3 | 1 | one backing array reused for every chunk (**a field, not a local**) | `TestAChunkIsUnchangedAfterEveryClientHasServedIt` | — (2c-2 verified the same shape) |
| 4 | 1 | `TotalBytes` drops its `RLock` | `TestManyConcurrentReadersAndOneWriter`, as `WARNING: DATA RACE` | — |
| 5 | 2 | `addClient` overwrites instead of refusing | `TestASecondAttachUnderAnAttachedClientIDIsRefused` | ✓ |
| 6 | 2 | `ClientSnapshot` returns map-range order | **expected not to redden**; report the gap | — |
| 7 | 3 | `release` drops the client outside `m.mu` and locks only around `detachLocked` | `TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel`, round 16 of 400 | ✓ |
| 8 | 3 | `detachLocked` checks presence, not identity | `TestADelayedStopNeverEvictsAReplacementChannel` | ✓ |
| 9 | 3 | the shutdown delay is ignored | `TestTheShutdownDelayKeepsAChannelForAReconnectingClient` | ✓ |
| 10 | 4 | the built `http.Transport` is never closed | `TestConcurrentAttachAndReleaseLeaksNoGoroutine`, 3 → 94 goroutines | ✓ |
| 11 | 5 | `serveClient` positions at the head | `TestASecondClientJoinsBehindLiveAndNotAtTheHead` | ✓ (see 16) |
| 12 | 5 | `identify`'s `header` closure ignores `trusted` | `TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader` | ✓ |
| 13 | 5 | one setting falls back to a literal | 2c-2's `TestEveryProxySettingThisRelayReadsIsRequired/<key>` **only** | — (2c-2 verified the shape) |
| 14 | 6 | the client limit is ignored | `TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked` | ✓ |
| 15 | 6 | `RequireInternal` skips the bound token | `TestTheListEndpointRefusesAnUnsignedOrMissignedCall`, **3 of 4** subtests | ✓ |
| 16 | 6 | `describeChannel` names a process identity in `owner` | `TestTheLiveEndpointProducesTheGoldensKeySet` **only** | ✓ (did not redden until R9's line went in) |
| 17 | 7 | `json:"url"` gains `,omitempty` | both golden tests | ✓ |
| 18 | 7 | `OutputProfileID` loses its pointer | `TestEveryOptionalFieldIsAbsentRatherThanNull` | — |
| 19 | 8 | `Attach` calls `start()` unconditionally | `TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint`, on the provider's request count | — (2c-2 verified the same shape) |

**Four rows deserve a second look before you trust them, and three of the four come from a break-check that did not redden.**

- **6** is listed *because* it is expected to stay green. Ordering is not a parity property — `channel_status.py:533` reads a Redis SET — so determinism here is a testing convenience and an assertion for it would pin this plan's own choice rather than a behaviour.
- **11** did not redden in this plan's first draft, because the test compared a **wrapped** `PacketIndex` against an unwrapped chunk count. Ruling R6 has the diagnosis; `rigAssetPackets = 65536` is the fix. If it stays green on your tree, check that constant first.
- **16** did not redden at all until one line was added to the live key-set test. The two golden tests compare a struct literal against a file; **neither runs the handler**. This is the plan's clearest instance of two tests that look like they cover a third thing and do not.
- **7** is a race and its round number will differ. What must not differ is that it reddens within a few hundred rounds with a message naming a channel the manager does not hold.

**A break-check that stays green is the most useful result this table produces**, and three of the four caveats above exist because one did.

---

## What to report back

1. **Task 0's diff** — every row of the 2c-2 ledger that did not match the merged tree, and which task absorbed it. In particular: did `Manager.release` already take one lock, and did `EffectiveProxySettings()` already carry `channel_shutdown_delay`?
2. **Every break-check's actual failure message**, and specifically: did **6**, **11** and **16** behave as this plan predicts?
3. **The three concurrency pins** — `TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel`, `TestADelayedStopNeverEvictsAReplacementChannel` and `TestConcurrentAttachAndReleaseLeaksNoGoroutine` — green, and their break-checks red on the named test only. For the first, **the round number it reddened on**.
4. **The goroutine numbers** — `before` and `after` from `TestConcurrentAttachAndReleaseLeaksNoGoroutine`, on a clean tree and with break-check 10 applied. If `after` on a clean tree is anywhere near `before + 20`, say so: the tolerance may be hiding a smaller leak.
5. **The golden file** — whether your regeneration from Django matched the committed one, and if not, every field that differed. This is the single most likely place this plan is wrong, because it encodes a reading of `RelayChannelSerializer` rather than a measurement.
6. **The Redis key-family walk** — the family this PR closes, the one it closes partially, and `client_stop`, which it does not.
7. **The lint ledger** — zero new `#nosec`, and anything the linter found that this plan does not name.
8. **The hand-run evidence** — `/healthz`, and a failed tune's body confirmed to name no URL and no variable value.
9. **The stated divergences**, as a list, because they are the part a reviewer cannot infer from a green suite. Task 12 Step 6 has them.
10. **Anything in the spec, `CLAUDE.md`, the 2c-2 plan or this plan you found wrong or stale.** The two most likely places: the 2c-2 ledger rows, and this plan's reading of `get_basic_channel_info`'s presence rules.

---

## Appendix — the files, in full

Every file below was written, built, vetted, run under `go test -race` three times and linted at **0 issues** before this plan was written, in a scratch module seeded from `main`'s `relay/` plus the 2c-2 plan's own appendices. The task tables above say what each pins and why; these are the bodies, so nothing has to be improvised against the six hollow shapes.

**Two literals in here are oracles and must be regenerated rather than trusted:** the golden JSON fixture (Task 7 Step 2 has the command), and — carried from 2c-2 — the synthetic asset's SHA-256.

**Appendix E is the one to read first if you change `Manager.Attach` or `Manager.release`.** Three of its six tests guard orderings rather than values, and every defect they guard against is invisible to `-race`.

### Appendix A — `relay/buffer/fanout_test.go`

```go
package buffer

import (
	"bytes"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

const (
	fanChunk  = TSPacketSize * 4 // 752 bytes
	fanBudget = fanChunk * 64    // sixty-four chunks, well past the read cap
)

func fanRing() *Ring {
	return New(Config{BudgetBytes: fanBudget, ChunkBytes: fanChunk})
}

// One Read hands back at most MaxChunksPerRead chunks, and `next` is the last
// chunk RETURNED rather than the ring's head -- the two stopped being the same
// thing when the cap went in, and a `next` that ran ahead of the delivered
// bytes would make a lagging client skip everything it did not receive.
func TestReadIsCappedAndItsCursorFollowsTheBytes(t *testing.T) {
	r := fanRing()
	// Forty chunks: twice the cap, inside the sixty-four-chunk ring so
	// nothing is evicted and the arithmetic below is about the cap alone.
	source := relaytest.SyntheticTS(40*4, 0x100)
	if _, err := r.Write(source); err != nil {
		t.Fatalf("Write: %v", err)
	}
	if got := r.Head(); got != 40 {
		t.Fatalf("the ring published %d chunks, want 40 -- the fixture is wrong, not the cap", got)
	}

	chunks, next, skipped := r.Read(0)
	if len(chunks) != MaxChunksPerRead {
		t.Fatalf("one Read returned %d chunks with 40 resident, want %d -- a lagging reader "+
			"can pin a whole ring's worth of evicted chunks", len(chunks), MaxChunksPerRead)
	}
	if next != uint64(MaxChunksPerRead) {
		t.Fatalf("next = %d after a capped read, want %d -- the cursor ran past the bytes the "+
			"caller was actually given and the rest of the stream is lost", next, MaxChunksPerRead)
	}
	if skipped != 0 {
		t.Fatalf("skipped = %d with nothing evicted", skipped)
	}

	// The rest arrives on the following calls, in order and with no gap.
	rest, next2, _ := r.Read(next)
	if len(rest) != 40-MaxChunksPerRead {
		t.Fatalf("the second Read returned %d chunks, want %d", len(rest), 40-MaxChunksPerRead)
	}
	if next2 != 40 {
		t.Fatalf("next = %d after the second read, want 40", next2)
	}
	// Position, not shape: the two reads concatenated must be the source from
	// packet zero.
	got := append(flatten(chunks), flatten(rest)...)
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("the two reads do not concatenate into whole TS packets: %s", problem)
	}
	for i := 0; i < len(got); i += TSPacketSize {
		want := i / TSPacketSize
		if idx := relaytest.PacketIndex(got[i : i+TSPacketSize]); idx != want {
			t.Fatalf("packet at byte %d carries index %d, want %d -- the cap dropped, "+
				"duplicated or reordered a chunk", i, idx, want)
		}
	}
}

// D2's immutability rule, at the fan-out that makes it matter. 2c-2 asserted it
// with one reader; 2c-3 adds the readers that share the array, and the
// assertion is still on CONTENT because -race cannot see it: two goroutines
// writing different bytes of one array is not a race on any address, and one
// goroutine writing a chunk nobody is reading at that instant is not a race at
// all.
func TestAChunkIsUnchangedAfterEveryClientHasServedIt(t *testing.T) {
	const readers = 8
	r := fanRing()
	source := relaytest.SyntheticTS(8, 0x100) // two chunks

	if _, err := r.Write(source); err != nil {
		t.Fatalf("Write: %v", err)
	}
	held := make([][][]byte, readers)
	snapshots := make([][]byte, readers)
	for i := range readers {
		chunks, _, _ := r.Read(0)
		if len(chunks) == 0 {
			t.Fatalf("reader %d read nothing", i)
		}
		held[i] = chunks
		snapshots[i] = bytes.Clone(chunks[0])
	}

	// Every reader holds a slice of the SAME array -- that is the design, and
	// if it were not, this test would be checking nothing.
	if &held[0][0][0] != &held[readers-1][0][0] {
		t.Fatal("two readers were handed different backing arrays for one chunk: " +
			"the fan-out is copying, which is not what spec D2 specifies")
	}

	// Force the ring well past what the readers hold.
	for range 40 {
		if _, err := r.Write(relaytest.SyntheticTS(4, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}

	for i := range readers {
		for at := range snapshots[i] {
			if held[i][0][at] != snapshots[i][at] {
				t.Fatalf("byte %d of a chunk reader %d still holds changed from %#02x to %#02x "+
					"after later writes: a published chunk's backing array was reused, and every "+
					"other reader of that chunk saw it change too",
					at, i, snapshots[i][at], held[i][0][at])
			}
		}
	}
}

// N readers and one writer, with -race as the oracle for the lock discipline.
// 2c-2 drove four readers; the shape here is the same and the point is that
// every reader path 2c-3 adds -- ClientSnapshot's callers included -- goes
// through these five methods.
func TestManyConcurrentReadersAndOneWriter(t *testing.T) {
	const readers = 16
	r := fanRing()
	stop := make(chan struct{})

	var wg sync.WaitGroup
	for range readers {
		wg.Add(1)
		go func() {
			defer wg.Done()
			var cursor uint64
			for {
				select {
				case <-stop:
					return
				default:
				}
				chunks, next, _ := r.Read(cursor)
				cursor = next
				_ = len(chunks)
				_ = r.Head()
				_, _ = r.Oldest()
				_ = r.Join(2 * time.Second)
				_ = r.TotalBytes()
			}
		}()
	}

	for range 200 {
		if _, err := r.Write(relaytest.SyntheticTS(4, 0x100)); err != nil {
			t.Fatalf("Write: %v", err)
		}
	}
	close(stop)
	wg.Wait()
}

func flatten(chunks [][]byte) []byte {
	var out []byte
	for _, c := range chunks {
		out = append(out, c...)
	}
	return out
}
```

### Appendix B — `relay/channel/client.go`

```go
package channel

import "time"

// Client is one reader attached to a channel.
//
// IN PROCESS MEMORY, which is the whole of what spec D2's "Client registry"
// key-family row buys: live:channel:{id}:clients (a SET with a TTL),
// live:channel:{id}:clients:{cid} (a hash with the same TTL), the per-channel
// heartbeat thread that refreshed both, and ClientManager.remove_ghost_clients
// are DELETED rather than ported.
//
// WHY THE TTL AND THE GHOST SWEEP DISSOLVE, stated because it is the one place
// a reviewer could reasonably expect a port. Those three mechanisms exist for
// one failure: a uWSGI worker dies holding clients, and its Redis keys outlive
// it, so a SET entry with no live reader has to be swept
// (client_manager.py:446-482) and a hash with no heartbeat has to expire
// (CLIENT_RECORD_TTL, apps/proxy/config.py:110). With one relay process and
// the registry in its own memory, a client entry cannot outlive the goroutine
// that made it: serveClient's deferred release runs on every return path
// including a panic, and if the process dies there is no registry left to
// sweep. A TTL here would be a timer with nothing to catch.
//
// WHAT DOES NOT DISSOLVE and is 2c-5's: a client whose TCP peer vanished with
// no FIN is held until its socket write fails or the kernel gives up. Python
// holds such a client just as long -- its heartbeat thread refreshes the TTL
// for every id in self.clients regardless of whether that client is making
// progress ("Only refresh TTL - do NOT update last_active",
// client_manager.py:143), and last_active is refreshed by the client's own
// yield path (output/ts/generator.py:517), so the ghost sweep never fires for
// a locally-attached client either. The behaviours match; neither disconnects
// such a client, and _is_timeout is gated on a health flag only 2c-5 lowers.
type Client struct {
	// ID is the client id, from X-Relay-Client when the authorize hop set
	// it, minted here otherwise. Unique per channel: a second attach with an
	// id already registered is refused, which is client_manager.py:218-221's
	// _registered_clients guard (parity-matrix row 13, first half).
	ID string

	// UserID is the X-Relay-User string, or "0". A STRING on the wire, not
	// an int: RelayChannelClientSerializer declares CharField
	// (apps/proxy/relay_serializers.py:31) and relay_client.live_connections
	// int()s it itself (apps/proxy/relay_client.py:274).
	UserID string

	// IPAddress is the viewer's address, from X-Relay-Client-IP when the hop
	// resolved it (parity-matrix row 17), the peer address otherwise.
	IPAddress string

	// UserAgent is the viewer's User-Agent, or "unknown"
	// (client_manager.py:236).
	UserAgent string

	// OutputFormat is what this relay is actually serving. Always "mpegts"
	// in 2c-3: a tune asking for anything else is refused 501 rather than
	// served MPEG-TS under a format label that is not true.
	OutputFormat string

	// OutputProfileID is nil in 2c-3. Always PRESENT on the wire, as null --
	// channel_status.py:579-582 sets the key on both branches, so it is the
	// one client field that is never absent.
	OutputProfileID *int

	// ConnectedAt is when the client attached.
	ConnectedAt time.Time
}
```

### Appendix C — `relay/channel/channel.go`

```go
// Package channel owns a channel's lifecycle: ownership, the state machine,
// the switch coordination between the HTTP handlers and the channel's own
// goroutine, and the client registry.
//
// WHAT THIS PACKAGE DELIBERATELY DOES NOT CONTAIN, because the Python relay's
// equivalents are deleted rather than ported (spec D2):
//
//   - No ownership lease. See Channel's own comment.
//   - No follower path and no live:events:{id} pub/sub.
//   - No client TTL, no heartbeat thread and no ghost sweep. See Client.
//   - No Redis client, and no Postgres driver.
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
)

// ErrDuplicateClient is returned by Attach when the channel already has a
// client registered under this id.
//
// The port of client_manager.py:218-221, whose add_client returns False for an
// id already in _registered_clients; views.py:748-753 turns that False into a
// 503. One process means one registry, so what Python enforces per worker is
// enforced outright here.
var ErrDuplicateClient = errors.New("channel: a client with this id is already attached")

// Channel is one running channel: its ring buffer, its source goroutine, its
// client registry and its state.
//
// There is NO OWNERSHIP LEASE here, and that is spec D2 rather than an
// omission. One relay process per host by construction means there is never a
// second writer to fence against, so live:channel:{id}:owner,
// _ensure_owner_or_stop, release_ownership's non-atomic GET-compare-DELETE and
// extend_ownership's non-atomic GET-EXPIRE are deleted rather than ported.
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
	// clients is the registry. Guarded by mu, and every mutation happens
	// while the MANAGER's lock is also held, which is what makes "the last
	// client left" and "the channel leaves the map" one decision rather than
	// two (Manager.release).
	clients map[string]*Client

	cancel context.CancelFunc
	done   chan struct{}
}

// SourceInfo is what the next-source answer said about the stream this channel
// is playing, kept so the status endpoints can render it without a second
// control-plane call. The fields are exactly the ones
// ChannelStatus.get_basic_channel_info reads out of the metadata hash.
type SourceInfo struct {
	// URL is the provider URL. It reaches the /proxy/relay/channels payload
	// because channel_status.py:472 puts it there and the Stats page shows
	// it; that surface is internal and HMAC-authenticated. It must never
	// reach a log line or a public response body.
	URL string

	// StreamProfileID is rendered as a STRING, because the metadata hash
	// stores str(source["stream_profile"]["id"]) (input/manager.py:2165) and
	// the serializer declares CharField.
	StreamProfileID int

	StreamID       int
	StreamName     string
	ChannelName    string
	M3UProfileID   int
	M3UProfileName string
}

// ID is the channel uuid the control plane and every client address it by.
func (c *Channel) ID() string { return c.id }

// Ring is the channel's buffer. Readers take chunks from it directly.
func (c *Channel) Ring() *buffer.Ring { return c.ring }

// Tuning is the channel-start-time settings this channel was started with.
func (c *Channel) Tuning() Tuning { return c.tuning }

// Source is what the next-source answer said about this channel's stream.
func (c *Channel) Source() SourceInfo { return c.source }

// StartedAt is when the channel was published.
func (c *Channel) StartedAt() time.Time { return c.startedAt }

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
// ten without ?clients=all, the COUNT never is.
func (c *Channel) Clients() int {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return len(c.clients)
}

// ClientSnapshot is every attached client, oldest connection first and ties
// broken by id.
//
// DETERMINISTIC ORDER, where Python's is arbitrary: channel_status.py:533
// reads a Redis SET with SMEMBERS and slices the first ten of whatever order
// that returned, so no order is the contract and any deterministic one is
// parity. It is deterministic here because a golden-file comparison against
// the Python serializer needs it to be, and because "the ten clients the list
// shows" being a stable set is strictly better than a set that reshuffles
// between polls.
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

// Done is closed once the source goroutine has returned and the ring is shut.
func (c *Channel) Done() <-chan struct{} { return c.done }

// addClient registers cl, or reports that its id is already taken.
//
// Called only with the manager's lock held, so a caller that then acts on the
// result cannot race a concurrent drop. The lock order is always manager then
// channel and nothing takes them the other way round.
func (c *Channel) addClient(cl *Client) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, taken := c.clients[cl.ID]; taken {
		return false
	}
	c.clients[cl.ID] = cl
	return true
}

// dropClient removes one client and reports how many remain. Manager lock held.
func (c *Channel) dropClient(id string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.clients, id)
	return len(c.clients)
}

func (c *Channel) setState(state State, err error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.state = state
	if err != nil {
		c.lastErr = err
	}
}

// run is the source goroutine. Exactly one per channel, started by the manager.
//
// It does NOT remove itself from the manager's map. Manager.claim drops a
// channel whose ring has closed, and that is the only place it happens.
func (c *Channel) run(ctx context.Context, source Source) {
	defer close(c.done)
	defer c.ring.Close()

	c.setState(StateWaitingForClients, nil)
	err := source.Run(ctx, c.ring)

	switch {
	case err == nil:
		c.log.Info("upstream ended", "channel", c.id)
		c.setState(StateStopped, nil)
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		c.log.Info("channel stopped", "channel", c.id)
		c.setState(StateStopped, nil)
	default:
		c.log.Error("upstream failed", "channel", c.id, "error", err)
		c.setState(StateError, err)
	}
}

// markActive moves a channel out of waiting_for_clients.
func (c *Channel) markActive() {
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

### Appendix D — `relay/channel/manager.go`

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

	// Now is the clock handed to every ring. Nil means time.Now.
	Now func() time.Time
}

// Manager owns every running channel.
type Manager struct {
	cfg ManagerConfig
	log *slog.Logger

	mu       sync.Mutex
	channels map[string]*Channel
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
// the channel runs on, and what the control plane said about the stream.
type Started struct {
	Source Source
	Tuning Tuning
	Info   SourceInfo
}

// Attach returns the channel for id, starting it from start() if it is not
// already running, and registers client against it.
//
// The returned release function must be called exactly once, and a deferred
// call is the only correct shape.
//
// START RUNS OUTSIDE THE MANAGER LOCK, behind a per-channel gate closed from a
// deferred call registered BEFORE start() runs, so it fires at Attach's return
// -- after publish has installed the channel. Moving that close inside a
// helper around start() wakes a waiter that then races the map insertion,
// claims a fresh gate and opens a SECOND upstream; -race reports none of it,
// because an ordering bug is not a data race.
func (m *Manager) Attach(id string, client *Client, start func() (Started, error)) (*Channel, func(), error) {
	var gate chan struct{}
	for {
		existing, wait, own, err := m.claim(id, client)
		if err != nil {
			return nil, nil, err
		}
		if existing != nil {
			existing.markActive()
			return existing, func() { m.release(existing, client.ID) }, nil
		}
		if own != nil {
			gate = own
			break
		}
		<-wait
	}

	defer m.releaseGate(id, gate)

	started, err := start()
	if err != nil {
		return nil, nil, err
	}

	c := m.publish(id, client, started)
	return c, func() { m.release(c, client.ID) }, nil
}

// releaseGate clears the start claim and wakes everyone waiting on it.
func (m *Manager) releaseGate(id string, gate chan struct{}) {
	m.mu.Lock()
	delete(m.starting, id)
	m.mu.Unlock()
	close(gate)
}

// claim inspects the map once, under the lock. It returns exactly one of: a
// running channel with this client registered against it; a gate to wait on
// because someone else is starting; a gate this caller now owns; or
// ErrDuplicateClient.
func (m *Manager) claim(id string, client *Client) (existing *Channel, wait, own chan struct{}, err error) {
	m.mu.Lock()
	defer m.mu.Unlock()

	if c, running := m.channels[id]; running {
		// A FINISHED CHANNEL IS NOT A RUNNING ONE, and this is the ONLY
		// place one is dropped. Keyed on the ring rather than on c.done
		// because the ring closes first among run's deferred calls.
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
	c := &Channel{
		id: id,
		ring: buffer.New(buffer.Config{
			BudgetBytes: m.cfg.BudgetBytes,
			ChunkBytes:  started.Tuning.ChunkBytes,
			Retention:   started.Tuning.Retention,
			Now:         m.cfg.Now,
		}),
		log:       m.log,
		tuning:    started.Tuning,
		source:    started.Info,
		startedAt: now(),
		state:     StateInitializing,
		clients:   map[string]*Client{client.ID: client},
		cancel:    cancel,
		done:      make(chan struct{}),
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

// Stop tears a channel down immediately, whatever its client count.
func (m *Manager) Stop(id string) bool {
	m.mu.Lock()
	c, running := m.channels[id]
	if running {
		delete(m.channels, id)
	}
	m.mu.Unlock()
	if !running {
		return false
	}
	c.setState(StateStopping, nil)
	c.stop(m.cfg.StopWait)
	return true
}

// StopAll tears every channel down.
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

// release drops one client and, when it was the last, stops the channel --
// immediately, or after the shutdown delay.
//
// THE DROP AND THE DECISION HAPPEN UNDER ONE LOCK, and that is the whole of
// this function. An earlier shape dropped the client, saw zero remaining, and
// then called Stop: between those two statements a new client could claim the
// same channel, be handed it, and have it torn down underneath them -- an
// empty 200 with no re-tune. claim registers its client under m.mu too, so
// taking the count and removing the map entry in the same critical section is
// what makes the two mutually exclusive. -race sees none of this; it is an
// ordering bug, which is why TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel
// exists.
func (m *Manager) release(c *Channel, clientID string) {
	m.mu.Lock()
	remaining := c.dropClient(clientID)
	stop := false
	if remaining == 0 && c.tuning.ShutdownDelay <= 0 {
		stop = m.detachLocked(c)
	}
	m.mu.Unlock()

	if stop {
		c.setState(StateStopping, nil)
		c.stop(m.cfg.StopWait)
		return
	}
	if remaining == 0 && c.tuning.ShutdownDelay > 0 {
		time.AfterFunc(c.tuning.ShutdownDelay, func() { m.stopIfIdle(c) })
	}
}

// stopIfIdle is the delayed half of release: the grace window expired, so stop
// the channel unless somebody reconnected inside it.
//
// The port of ChannelService.cancel_pending_shutdown
// (services/channel_service.py:103-127), which Python spells as a Redis
// timestamp a reconnecting client deletes. Here the reconnect simply registers
// a client, and this check sees it -- under the same lock that registered it,
// so there is no window between "nobody is watching" and "the entry is gone".
func (m *Manager) stopIfIdle(c *Channel) {
	m.mu.Lock()
	stop := c.Clients() == 0 && m.detachLocked(c)
	m.mu.Unlock()
	if !stop {
		return
	}
	c.setState(StateStopping, nil)
	c.stop(m.cfg.StopWait)
}

// detachLocked removes c from the map if the map still holds THIS channel, and
// reports whether it did. Callers hold m.mu.
//
// The identity check is load-bearing. By the time a delayed stop fires, the
// map may hold a DIFFERENT channel under the same id: the first one finished,
// claim dropped it, and a later tune published a replacement. Deleting by id
// alone would evict a live successor and leave its clients attached to a
// channel nothing can stop.
func (m *Manager) detachLocked(c *Channel) bool {
	if m.channels[c.id] != c {
		return false
	}
	delete(m.channels, c.id)
	return true
}

// Describe is a one-line state summary, for logs.
func (c *Channel) Describe() string {
	return fmt.Sprintf("channel %s state=%s clients=%d head=%d", c.id, c.State(), c.Clients(), c.ring.Head())
}
```

### Appendix E — `relay/channel/fanout_test.go`

```go
package channel

import (
	"context"
	"errors"
	"io"
	"runtime"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

func testTuning() Tuning {
	return Tuning{
		ChunkBytes: buffer.TSPacketSize * 4,
		Retention:  60 * time.Second,
		JoinBehind: 5 * time.Second,
	}
}

func testClient(id string) *Client {
	return &Client{
		ID:           id,
		UserID:       "7",
		IPAddress:    "203.0.113.9",
		UserAgent:    "relaytest/1.0",
		OutputFormat: "mpegts",
		ConnectedAt:  time.Now(),
	}
}

// A source that counts how many are running now and how many ever ran.
type sourceCounter struct {
	mu      sync.Mutex
	running int
	started int
}

func (c *sourceCounter) enter() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.running++
	c.started++
}

func (c *sourceCounter) leave() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.running--
}

func (c *sourceCounter) snapshot() (running, started int) {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.running, c.started
}

type countingSource struct{ c *sourceCounter }

func (s countingSource) Run(ctx context.Context, _ io.Writer) error {
	s.c.enter()
	defer s.c.leave()
	<-ctx.Done()
	return ctx.Err()
}

// waitForStart blocks until at least one source has entered Run and returns
// how many had by then.
//
// A DEADLINE, NOT AN IMMEDIATE READ. publish starts the source goroutine and
// returns without waiting for the scheduler, so asserting the count straight
// after Attach races Go's runtime rather than the code -- and it reports ZERO
// where the defect being hunted reports two, which is a failure message
// pointing at the wrong thing. Measured: three runs out of three failed this
// way before the poll went in.
func waitForStart(t *testing.T, c *sourceCounter) int {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		if _, started := c.snapshot(); started > 0 {
			return started
		}
		if time.Now().After(deadline) {
			t.Fatal("no source started within five seconds")
		}
		time.Sleep(100 * time.Microsecond)
	}
}

func startCounting(c *sourceCounter, t Tuning) func() (Started, error) {
	return func() (Started, error) {
		return Started{Source: countingSource{c: c}, Tuning: t}, nil
	}
}

// N clients on one channel start exactly one source, and the channel survives
// until the LAST of them releases. The count is read from inside the source,
// so it fails whatever route a second reader took to get started.
func TestNClientsShareOneSourceAndTheChannelOutlivesAllButTheLast(t *testing.T) {
	const clients = 6
	counter := &sourceCounter{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

	releases := make([]func(), 0, clients)
	var first *Channel
	for i := range clients {
		ch, release, err := m.Attach("one", testClient(string(rune('a'+i))), startCounting(counter, testTuning()))
		if err != nil {
			t.Fatalf("client %d: Attach: %v", i, err)
		}
		if first == nil {
			first = ch
		} else if ch != first {
			t.Fatalf("client %d got a different *Channel: the clients of one channel are watching two upstreams", i)
		}
		releases = append(releases, release)
	}

	if started := waitForStart(t, counter); started != 1 {
		t.Fatalf("%d sources were started for one channel, want 1 -- a second provider connection was opened", started)
	}
	if got := first.Clients(); got != clients {
		t.Fatalf("the channel reports %d clients, want %d", got, clients)
	}

	for i := range clients - 1 {
		releases[i]()
		if m.Get("one") != first {
			t.Fatalf("the channel was stopped after client %d of %d released -- only the LAST client leaving stops it", i, clients)
		}
	}
	releases[clients-1]()
	if got := m.Get("one"); got != nil {
		t.Fatalf("the channel is still running after every client released: %v", got.Describe())
	}
	if running, _ := counter.snapshot(); running != 0 {
		t.Fatalf("%d source goroutines still running -- a leaked provider connection holding a slot", running)
	}
}

// Row 13's first half: registration is idempotent per client id, and a second
// attach under an id already attached is refused rather than silently
// overwriting the first (client_manager.py:218-221, whose False becomes a 503).
func TestASecondAttachUnderAnAttachedClientIDIsRefused(t *testing.T) {
	counter := &sourceCounter{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

	ch, release, err := m.Attach("one", testClient("dup"), startCounting(counter, testTuning()))
	if err != nil {
		t.Fatalf("first Attach: %v", err)
	}
	defer release()

	second, _, err := m.Attach("one", testClient("dup"), startCounting(counter, testTuning()))
	if !errors.Is(err, ErrDuplicateClient) {
		t.Fatalf("a second attach under the id \"dup\" returned %v, want ErrDuplicateClient", err)
	}
	if second != nil {
		t.Fatal("the refused attach still handed back a channel")
	}
	if got := ch.Clients(); got != 1 {
		t.Fatalf("the channel holds %d clients after a refused duplicate, want 1 -- the registry is not keyed by id", got)
	}
}

// THE ORDERING TEST FOR THE LAST-CLIENT RULE. A client arriving at the instant
// the last one leaves must keep its channel. Neither property is a data race,
// so -race is silent on both: the drop and the stop have to happen under ONE
// lock, and the arrival registers under the same one.
//
// The defect this guards against: release drops the client, sees zero
// remaining, and THEN calls Stop. A claim landing in that window is handed the
// channel and has it torn down underneath it -- a 200 with a few bytes and no
// re-tune, for as long as clients keep churning.
func TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel(t *testing.T) {
	const rounds = 400

	for round := range rounds {
		counter := &sourceCounter{}
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

		first, releaseFirst, err := m.Attach("one", testClient("a"), startCounting(counter, testTuning()))
		if err != nil {
			t.Fatalf("round %d: first Attach: %v", round, err)
		}

		var wg sync.WaitGroup
		var second *Channel
		var releaseSecond func()
		var secondErr error

		wg.Add(2)
		go func() { defer wg.Done(); releaseFirst() }()
		go func() {
			defer wg.Done()
			second, releaseSecond, secondErr = m.Attach("one", testClient("b"), startCounting(counter, testTuning()))
		}()
		wg.Wait()

		if secondErr != nil {
			t.Fatalf("round %d: the arriving client failed to attach: %v", round, secondErr)
		}
		// Either the arrival won the race and holds the ORIGINAL channel, or
		// it lost and started a fresh one. Both are correct. What is never
		// correct is holding a channel the manager has dropped: nothing could
		// stop it, and its ring is already closing under the reader.
		if got := m.Get("one"); got != second {
			t.Fatalf("round %d: the arriving client holds a channel the manager does not (%v vs %v): "+
				"it was stopped underneath a live client",
				round, second.Describe(), got)
		}
		if second == first {
			if second.Ring().Closed() {
				t.Fatalf("round %d: the arriving client was handed the leaving client's channel "+
					"after its ring closed -- it will read an empty 200 and never re-tune", round)
			}
		}
		releaseSecond()
		m.StopAll()
	}
}

// The grace window: channel_shutdown_delay > 0 keeps a channel alive for a
// reconnecting client, and the reconnect cancels the stop
// (ChannelService.cancel_pending_shutdown, channel_service.py:103-127).
func TestTheShutdownDelayKeepsAChannelForAReconnectingClient(t *testing.T) {
	counter := &sourceCounter{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

	tuning := testTuning()
	// 400ms, not the default 0: a test that supplied the default could not
	// tell a working grace window from no grace window at all.
	tuning.ShutdownDelay = 400 * time.Millisecond

	ch, release, err := m.Attach("one", testClient("a"), startCounting(counter, tuning))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	release()

	if got := m.Get("one"); got != ch {
		t.Fatal("the channel was stopped immediately: the shutdown delay did not apply")
	}

	back, releaseBack, err := m.Attach("one", testClient("b"), startCounting(counter, tuning))
	if err != nil {
		t.Fatalf("reconnect: %v", err)
	}
	if back != ch {
		t.Fatal("the reconnecting client got a fresh channel: the grace window was not honoured")
	}

	// Past the window the original stop would have fired. It must not, because
	// a client is attached.
	time.Sleep(700 * time.Millisecond)
	if m.Get("one") != ch {
		t.Fatal("the delayed stop fired with a client attached: the reconnect did not cancel it")
	}
	waitForStart(t, counter)
	if running, started := counter.snapshot(); running != 1 || started != 1 {
		t.Fatalf("%d sources running and %d ever started, want 1 and 1", running, started)
	}

	releaseBack()
	deadline := time.Now().Add(3 * time.Second)
	for m.Get("one") != nil {
		if time.Now().After(deadline) {
			t.Fatal("the channel outlived its last client by more than the grace window")
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// A delayed stop must never evict a REPLACEMENT channel. By the time the timer
// fires the map can hold a different *Channel under the same id -- the first
// finished, claim dropped it, a later tune published a successor. Deleting by
// id alone strands the successor's clients on a channel nothing can stop.
func TestADelayedStopNeverEvictsAReplacementChannel(t *testing.T) {
	counter := &sourceCounter{}
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})

	tuning := testTuning()
	tuning.ShutdownDelay = 300 * time.Millisecond

	first, releaseFirst, err := m.Attach("one", testClient("a"), startCounting(counter, tuning))
	if err != nil {
		t.Fatalf("Attach: %v", err)
	}
	releaseFirst() // arms the delayed stop for `first`

	// Finish the first channel and take it out of the map the way claim does.
	m.Stop("one")

	second, releaseSecond, err := m.Attach("one", testClient("b"), startCounting(counter, tuning))
	if err != nil {
		t.Fatalf("re-tune: %v", err)
	}
	defer releaseSecond()
	if second == first {
		t.Fatal("the re-tune reused the stopped channel")
	}

	time.Sleep(600 * time.Millisecond)
	if got := m.Get("one"); got != second {
		t.Fatalf("the first channel's delayed stop evicted the replacement: the map holds %v, want the "+
			"channel the live client is watching", got)
	}
}

// Attach and release under concurrency leak no goroutine. An ordering bug in
// the gate or the release path shows up here as a source goroutine nothing can
// stop, which -race never reports.
func TestConcurrentAttachAndReleaseLeaksNoGoroutine(t *testing.T) {
	const clients = 8
	const rounds = 50

	upstream := relaytest.NewUpstream(relaytest.Config{Rate: 0.05})
	t.Cleanup(upstream.Close)

	// Poll DOWN to a target rather than waiting for two equal samples: a
	// winding-down goroutine set is briefly stable at any value, so an
	// equal-samples settle reports whatever it happened to catch. This one
	// reports the lowest count reached inside the deadline.
	settleTo := func(target int) int {
		deadline := time.Now().Add(8 * time.Second)
		best := runtime.NumGoroutine()
		for {
			now := runtime.NumGoroutine()
			best = min(best, now)
			if best <= target || time.Now().After(deadline) {
				return best
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
	// Read once, before any round: the test process is quiet here, and a
	// settle loop with no reachable target would only burn its own deadline.
	before := runtime.NumGoroutine()

	for round := range rounds {
		m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 64})
		var wg sync.WaitGroup
		for i := range clients {
			wg.Add(1)
			go func() {
				defer wg.Done()
				_, release, err := m.Attach("one", testClient(string(rune('a'+i))), func() (Started, error) {
					return Started{
						Source: ProxySource{URL: upstream.URL(), ReadTimeout: time.Second},
						Tuning: testTuning(),
					}, nil
				})
				if err != nil {
					return
				}
				release()
			}()
		}
		wg.Wait()
		m.StopAll()
		if n := len(m.ids()); n != 0 {
			t.Fatalf("round %d: the manager still holds %d channels", round, n)
		}
	}

	after := settleTo(before + 20)
	// A tolerance, not a bare equality: net/http keeps idle connections and
	// their readers alive across the test. What this catches is a LEAK PER
	// ROUND -- 50 rounds x 8 clients, so anything structural is hundreds.
	if after > before+20 {
		t.Fatalf("goroutines went from %d to %d across %d rounds of %d clients -- "+
			"something started per attach is never stopped", before, after, rounds, clients)
	}
}
```

### Appendix F — `relay/httpapi/stream.go`

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
)

// StreamDeps is everything the live TS handler needs.
type StreamDeps struct {
	Secret   string
	Channels *channel.Manager
	Control  *control.Client
	Log      *slog.Logger

	// Now is the clock a client's ConnectedAt comes from. Nil means time.Now.
	Now func() time.Time
}

// The proxy_settings keys this PR reads.
const (
	settingChunkBytes    = "BUFFER_CHUNK_SIZE"
	settingRetention     = "redis_chunk_ttl"
	settingJoinBehind    = "new_client_behind_seconds"
	settingReadSize      = "CHUNK_SIZE"
	settingShutdownDelay = "channel_shutdown_delay"
)

// OutputFormatMPEGTS is the only output format this relay serves.
//
// The value apps/proxy/live_proxy/views.py records when no format was chosen
// (channel_status.py:567's `output_format or 'mpegts'`), and the one 2c-3
// serves. fMP4 is 2c-6's.
const OutputFormatMPEGTS = "mpegts"

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
	readSize, err := s.Int(settingReadSize)
	if err != nil {
		return t, 0, err
	}
	return t, readSize, nil
}

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
			return startProxyTune(r.Context(), deps.Control, id)
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
// wrong in a way nothing on the wire says. 2c-6 brings fMP4 and 2c-7 the
// Output Profiles.
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
// The four X-Relay-* values are read ONLY when X-Dispatcharr-Authorized proves
// nginx put them there. Without that check any client could name any channel,
// any client id, any address and any user by hand and bypass whatever the
// authorize hop decided -- that marker is the entire reason
// apps/proxy/authorize.py can be the only place the decision is made. An
// untrusted request falls back to the path value and to values resolved here,
// which is the dev shape; 2c-8 brings POST /_dispatcharr/authorize-internal.
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

	format := header("X-Relay-Output-Format")
	profileID := header("X-Relay-Output")
	if profileID != "" {
		return id, nil, &ErrUnsupportedOutput{ProfileID: profileID}
	}
	if format != "" && format != OutputFormatMPEGTS {
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

	userAgent := r.Header.Get("User-Agent")
	if userAgent == "" {
		// client_manager.py:236's own fallback.
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

// mintClientID is apps/proxy/authorize.py:145-147's mint_client_id, spelled
// the same way on the wire: client_<unix millis>_<four digits>.
//
// crypto/rand rather than math/rand: gosec reports G404 on math/rand, and the
// id is a handle an admin can stop a client by (DELETE
// /proxy/relay/channels/<id>/clients/<client_id>, 2c-8), so guessability is
// not nothing. Python's random.randint is what it is; matching the FORMAT is
// the parity requirement, matching the generator is not.
func mintClientID(at time.Time) string {
	n, err := rand.Int(rand.Reader, big.NewInt(9000))
	if err != nil {
		// crypto/rand.Reader does not fail on any platform this runs on;
		// if it somehow did, a tune must still get an id rather than 500.
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

// ErrNotProxyKind is returned when the channel's Stream Profile is not Proxy.
type ErrNotProxyKind struct{ Kind string }

func (e *ErrNotProxyKind) Error() string {
	return fmt.Sprintf("the Go relay serves only the %q stream profile so far, not %q",
		control.KindProxy, e.Kind)
}

// ErrNoSource is returned when next-source had no candidate.
var ErrNoSource = errors.New("the control plane has no source for this channel")

// startProxyTune makes the one control-plane call a tune needs and builds the
// source from its answer.
func startProxyTune(ctx context.Context, client *control.Client, id string) (channel.Started, error) {
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

	// KIND, NEVER TRANSCODE.
	if kind := answer.Source.StreamProfile.Kind; kind != control.KindProxy {
		return channel.Started{}, &ErrNotProxyKind{Kind: kind}
	}

	tuning, readSize, err := tuningFrom(answer.ProxySettings)
	if err != nil {
		return channel.Started{}, err
	}

	return channel.Started{
		Source: channel.ProxySource{
			URL:       answer.Source.URL,
			UserAgent: answer.Source.UserAgent,
			ChunkSize: readSize,
		},
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

// writeTuneFailure turns a tune error into a status. It never echoes the error
// text to the client.
func writeTuneFailure(w http.ResponseWriter, log *slog.Logger, id string, err error) {
	var notProxy *ErrNotProxyKind
	var unsupported *ErrUnsupportedOutput
	var refused *control.Refused
	var unavailable *control.Unavailable
	var misconfigured *control.ErrNotConfigured
	var absent *control.ErrSettingAbsent

	switch {
	case errors.As(err, &notProxy):
		log.Warn("refusing a tune for an unsupported stream profile", "channel", id, "kind", notProxy.Kind)
		http.Error(w, "this stream profile is not served yet", http.StatusNotImplemented)
	case errors.As(err, &unsupported):
		log.Warn("refusing a tune for an unsupported output",
			"channel", id, "format", unsupported.Format, "output_profile", unsupported.ProfileID)
		http.Error(w, "this output is not served yet", http.StatusNotImplemented)
	case errors.Is(err, channel.ErrDuplicateClient):
		// views.py:748-753's 503: a client id already attached to this
		// channel is a client that never released, not a new viewer.
		log.Warn("refusing a duplicate client id", "channel", id)
		http.Error(w, "failed to register client", http.StatusServiceUnavailable)
	case errors.Is(err, ErrNoSource):
		log.Info("no source available", "channel", id)
		http.Error(w, "no source available", http.StatusServiceUnavailable)
	case errors.As(err, &absent):
		log.Error("the control plane sent incomplete proxy_settings", "channel", id, "key", absent.Key)
		http.Error(w, "control plane contract mismatch", http.StatusBadGateway)
	case errors.As(err, &misconfigured):
		log.Error("the control-plane address is misconfigured", "variable", misconfigured.Variable)
		http.Error(w, "control plane misconfigured", http.StatusInternalServerError)
	case errors.As(err, &refused):
		log.Error("the control plane refused the tune", "channel", id, "status", refused.Status)
		http.Error(w, "control plane refused", http.StatusBadGateway)
	case errors.As(err, &unavailable):
		log.Error("the control plane is unreachable", "channel", id, "reason", unavailable.Reason)
		http.Error(w, "control plane unreachable", http.StatusBadGateway)
	default:
		log.Error("the tune failed", "channel", id, "error", err)
		http.Error(w, "tune failed", http.StatusInternalServerError)
	}
}

// serveClient is the client loop: position once, then read, write, wait.
//
// NO KEEPALIVE PACKETS AND NO CLIENT TIMEOUT, both parity: Python's are gated
// on stream_manager.healthy being FALSE (output/ts/generator.py:546-551 and
// :592), and nothing lowers that flag except the failover machinery, which is
// 2c-5's.
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

	for {
		chunks, next, skipped := ring.Read(cursor)
		if skipped > 0 {
			// The jump find_oldest_available_chunk performs
			// (input/buffer.py:407-452): the client fell behind past
			// retention, so it resumes at the oldest resident chunk with a
			// gap in its stream. Logged, never a disconnect -- Python does
			// not disconnect such a client either.
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
			// above and Close.
			if final, _, _ := ring.Read(cursor); len(final) > 0 {
				writeChunks(w, rc, final)
			}
		}
		return
	}
}

// writeChunks writes and flushes, reporting whether the client is still there.
//
// IT NEVER WRITES INTO A CHUNK. The slices are borrowed from the ring and
// shared by every client at this position; mutating one corrupts all of them,
// and -race cannot see it. Pinned by
// TestAChunkIsUnchangedAfterEveryClientHasServedIt.
func writeChunks(w http.ResponseWriter, rc *http.ResponseController, chunks [][]byte) bool {
	for _, data := range chunks {
		// #nosec G705 -- this is the video path. gosec's taint analysis sees
		// bytes from an outbound HTTP response reaching w.Write and reports a
		// cross-site-scripting risk; the bytes are an MPEG-TS stream served as
		// video/mp2t, the response carries no HTML context, and copying
		// provider bytes to a viewer is the only thing this process exists to
		// do.
		if _, err := w.Write(data); err != nil {
			return false
		}
	}
	return rc.Flush() == nil
}
```

### Appendix G — `relay/httpapi/channels.go`

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
// SEVENTEEN OF THE CONDITIONAL FIELDS ARE ABSENT IN 2c-3, and each absence has
// a reason rather than a gap:
//
//	logo_id        NEVER EMITTED BY PYTHON EITHER. ChannelMetadataField.LOGO_ID
//	               is declared (constants.py:59) and read (channel_status.py:486)
//	               and written NOWHERE in the tree, so the `if not raw: continue`
//	               always continues. Exact parity by doing nothing.
//	healthy        needs StreamManager.healthy, which is 2c-5's.
//	video_codec, resolution, source_fps, ffmpeg_speed, audio_codec,
//	audio_channels, stream_type
//	               all ffmpeg- or probe-derived, written by the stderr reader
//	               and channel_service; 2c-4 and 2c-5.
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
			log.Error("encoding the channel list failed", "error", err)
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

### Appendix H — `relay/httpapi/golden_test.go`

```go
package httpapi

import (
	"encoding/json"
	"net/http"
	"os"
	"reflect"
	"sort"
	"testing"
	"time"

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
	r := newRig(t, relaytest.Config{Rate: 4}, rigSettings(nil))
	response := r.tune(t, "c-keys", "client-a")
	defer func() { _ = response.Body.Close() }()

	// The channel must have published at least one chunk, so total_bytes and
	// the two bitrate fields are present -- they are exactly the conditional
	// fields the golden's populated channel carries.
	deadline := time.Now().Add(15 * time.Second)
	for {
		ch := r.Manager.Get("c-keys")
		if ch != nil && ch.Ring().Head() > 0 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the channel published no chunk within fifteen seconds")
		}
		time.Sleep(20 * time.Millisecond)
	}

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

### Appendix I — `relay/httpapi/fanout_test.go`

```go
package httpapi

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

const (
	rigSecret = "phase2c3-test-secret"
	// A chunk size the constant cannot produce, so a relay ignoring the wire
	// value is detectable. 2c-2 shipped this rig sending 255868 -- the
	// constant itself -- which disarmed the whole end-to-end layer against the
	// one property Amendment A1.4 exists to prove.
	rigChunkBytes = buffer.TSPacketSize * 700
	// LONG ENOUGH THAT PacketIndex NEVER WRAPS inside a test, and that is
	// what makes the join-point assertion able to fail at all. The embedded
	// index is the packet's position in the ASSET, so a looping upstream
	// restarts it at zero; an earlier 4,096-packet asset (3.1 seconds at the
	// nominal rate) made "how far behind live did this client start" compare a
	// wrapped index against an unwrapped chunk count, which is large and
	// positive whatever the relay does. The break-check that removed the join
	// call entirely left the test GREEN, which is how this was found.
	//
	// 65,536 packets is 12.3 MB, 49 seconds at the nominal rate -- longer than
	// any test here runs.
	rigAssetPackets = 65536
)

type rig struct {
	Relay    *httptest.Server
	Upstream *relaytest.Upstream
	Control  *relaytest.ControlPlane
	Manager  *channel.Manager
}

func rigSettings(overrides map[string]any) map[string]any {
	s := relaytest.EffectiveProxySettings()
	s["BUFFER_CHUNK_SIZE"] = rigChunkBytes
	for k, v := range overrides {
		s[k] = v
	}
	return s
}

// newRig stands up a whole fake deployment: a provider, a Django, this
// process's mux, and a REAL server in front of it. Not httptest.NewRecorder:
// the subject is a long-lived streaming response, and a recorder buffers the
// whole body and returns only once the handler has finished.
func newRig(t *testing.T, upstream relaytest.Config, settings map[string]any) *rig {
	t.Helper()
	if upstream.Payload == nil {
		upstream.Payload = relaytest.SyntheticTS(rigAssetPackets, 0x100)
	}
	up := relaytest.NewUpstream(upstream)
	t.Cleanup(up.Close)

	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{
		SourceURL: up.URL(),
		Settings:  settings,
	})
	t.Cleanup(cp.Close)

	m := channel.NewManager(channel.ManagerConfig{BudgetBytes: rigChunkBytes * 64})
	server := httptest.NewServer(New(Config{
		DevRoutes: true,
		Stream: StreamDeps{
			Secret:   rigSecret,
			Channels: m,
			Control:  &control.Client{Secret: rigSecret, BaseURL: cp.URL()},
		},
		Control: ControlDeps{Secret: rigSecret, Channels: m},
	}).Handler())
	t.Cleanup(server.Close)
	t.Cleanup(m.StopAll)

	return &rig{Relay: server, Upstream: up, Control: cp, Manager: m}
}

// tune opens a stream for channelID as clientID. The caller closes the body.
func (r *rig) tune(t *testing.T, channelID, clientID string) *http.Response {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet,
		r.Relay.URL+"/proxy/ts/stream/"+channelID, nil)
	if err != nil {
		t.Fatalf("building the tune request: %v", err)
	}
	if clientID != "" {
		request.Header.Set(control.HeaderAuthorized, control.RelayTrustToken(rigSecret))
		request.Header.Set("X-Relay-Channel", channelID)
		request.Header.Set("X-Relay-Client", clientID)
		request.Header.Set("X-Relay-Client-IP", "198.51.100.4")
		request.Header.Set("X-Relay-User", "7")
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("tuning: %v", err)
	}
	if response.StatusCode != http.StatusOK {
		_ = response.Body.Close()
		t.Fatalf("tune answered %d, want 200", response.StatusCode)
	}
	return response
}

// listChannels calls GET /proxy/relay/channels with both internal headers.
func (r *rig) listChannels(t *testing.T, query string) (int, []byte) {
	t.Helper()
	path := "/proxy/relay/channels" + query
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+path, nil)
	if err != nil {
		t.Fatalf("building the list request: %v", err)
	}
	request.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(rigSecret))
	request.Header.Set(control.HeaderInternalRequest,
		control.InternalRequestHeader(rigSecret, http.MethodGet, path, nil, time.Now().Unix()))
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("listing channels: %v", err)
	}
	defer func() { _ = response.Body.Close() }()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the list body: %v", err)
	}
	return response.StatusCode, body
}

// packetRun reads n whole packets and reports the index of the first, after
// checking that every packet follows the one before it.
func packetRun(t *testing.T, who string, body io.Reader, packets int) int {
	t.Helper()
	got := make([]byte, packets*buffer.TSPacketSize)
	if _, err := io.ReadFull(body, got); err != nil {
		t.Fatalf("%s: reading %d packets: %v", who, packets, err)
	}
	if problem := relaytest.AlignmentProblem(got); problem != "" {
		t.Fatalf("%s received bytes that are not whole TS packets: %s", who, problem)
	}
	first := relaytest.PacketIndex(got[:buffer.TSPacketSize])
	for i := 0; i < len(got); i += buffer.TSPacketSize {
		want := (first + i/buffer.TSPacketSize) % rigAssetPackets
		if idx := relaytest.PacketIndex(got[i : i+buffer.TSPacketSize]); idx != want {
			t.Fatalf("%s: packet at byte %d carries index %d, want %d -- its stream has a gap, "+
				"a duplicate or a reordering", who, i, idx, want)
		}
	}
	return first
}

// THE FAN-OUT TEST. N clients on one channel: one upstream connection, one
// *Channel, and every client's byte stream is an unbroken run of the writer's
// packets from wherever it joined. Then every client releases and nothing is
// left running.
func TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint(t *testing.T) {
	const clients = 6
	const packets = 900

	r := newRig(t, relaytest.Config{Rate: 6}, rigSettings(nil))

	var wg sync.WaitGroup
	firsts := make([]int, clients)
	bodies := make([]io.ReadCloser, clients)
	for i := range clients {
		response := r.tune(t, "c-fanout", fmt.Sprintf("client-%d", i))
		defer func() { _ = response.Body.Close() }()
		bodies[i] = response.Body
	}
	for i := range clients {
		wg.Add(1)
		go func() {
			defer wg.Done()
			firsts[i] = packetRun(t, fmt.Sprintf("client %d", i), bodies[i], packets)
		}()
	}
	wg.Wait()

	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests for one channel, want 1 -- parity-matrix row 10: "+
			"every client on a channel shares one upstream connection", got)
	}
	ch := r.Manager.Get("c-fanout")
	if ch == nil {
		t.Fatal("the manager holds no channel while six clients are reading it")
	}
	if got := ch.Clients(); got != clients {
		t.Fatalf("the channel reports %d clients, want %d", got, clients)
	}
	// Every client's run came from the same writer, so their join points are
	// all inside the window the ring held -- at most the ring's capacity apart.
	lowest, highest := firsts[0], firsts[0]
	for _, f := range firsts {
		lowest = min(lowest, f)
		highest = max(highest, f)
	}
	span := highest - lowest
	maxSpan := 64 * rigChunkBytes / buffer.TSPacketSize
	if span > maxSpan {
		t.Fatalf("the clients' join points span %d packets, more than the %d-packet ring: "+
			"they are not reading one writer's stream", span, maxSpan)
	}
}

// Parity-matrix row 8, at the case the row is actually about: a client joining
// a channel ALREADY RUNNING for somebody else starts roughly
// new_client_behind_seconds behind live, not at the newest chunk.
//
// The oracle is the SECOND client's first packet index against the FIRST
// client's position, both read off relaytest's embedded indices, which no code
// under test produces. new_client_behind_seconds is sent as 3 rather than the
// default 5 so a relay ignoring the wire value is visible.
func TestASecondClientJoinsBehindLiveAndNotAtTheHead(t *testing.T) {
	const behindSeconds = 3
	// 1.0x nominal is 250,000 byte/s, so three seconds is 750,000 bytes --
	// about 5.7 chunks at rigChunkBytes, comfortably more than one and
	// comfortably less than the sixty-four-chunk ring.
	r := newRig(t, relaytest.Config{Rate: 1},
		rigSettings(map[string]any{"new_client_behind_seconds": behindSeconds}))

	first := r.tune(t, "c-join", "client-a")
	defer func() { _ = first.Body.Close() }()
	// Let the first client pull the channel well past the join window.
	firstStart := packetRun(t, "the first client", first.Body, 200)

	deadline := time.Now().Add(15 * time.Second)
	for {
		ch := r.Manager.Get("c-join")
		if ch != nil && ch.Ring().Head() >= 12 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the channel never filled enough of its ring to have a join window")
		}
		time.Sleep(20 * time.Millisecond)
	}

	head := r.Manager.Get("c-join").Ring().Head()
	second := r.tune(t, "c-join", "client-b")
	defer func() { _ = second.Body.Close() }()
	secondStart := packetRun(t, "the second client", second.Body, 100)

	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1", got)
	}
	// The live head at the moment the second client joined, in packets.
	livePackets := int(head) * rigChunkBytes / buffer.TSPacketSize
	behindPackets := livePackets - secondStart
	if behindPackets <= 0 {
		t.Fatalf("the second client started at packet %d with the live head at packet %d: "+
			"it joined AT live, not behind it -- new_client_behind_seconds was ignored",
			secondStart, livePackets)
	}
	// Three seconds at the nominal rate is 750,000 bytes, 3989 packets. A
	// generous window either side, because the assertion is "behind by about
	// the configured window", not a stopwatch.
	const wantPackets = behindSeconds * relaytest.NominalByteRate / buffer.TSPacketSize
	if behindPackets < wantPackets/4 || behindPackets > wantPackets*4 {
		t.Fatalf("the second client started %d packets behind live, want roughly %d "+
			"(%ds at the nominal rate) -- the join point is not the configured window",
			behindPackets, wantPackets, behindSeconds)
	}
	if secondStart <= firstStart {
		t.Logf("note: the second client started at packet %d, at or behind the first client's "+
			"start of %d -- legitimate when the ring is shorter than the window", secondStart, firstStart)
	}
}

// The list endpoint: every attached client, with ?clients=all lifting the
// ten-client cap that relay_client.live_connections would otherwise under-count
// behind (spec D4).
func TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked(t *testing.T) {
	const clients = 13
	r := newRig(t, relaytest.Config{Rate: 4}, rigSettings(nil))

	for i := range clients {
		response := r.tune(t, "c-list", fmt.Sprintf("client-%02d", i))
		defer func() { _ = response.Body.Close() }()
	}

	for _, tc := range []struct {
		query string
		want  int
	}{
		{"", DefaultClientLimit},
		{"?clients=all", clients},
	} {
		status, body := r.listChannels(t, tc.query)
		if status != http.StatusOK {
			t.Fatalf("%q answered %d, want 200", tc.query, status)
		}
		var payload struct {
			Channels []struct {
				ChannelID   string           `json:"channel_id"`
				ClientCount int              `json:"client_count"`
				Clients     []map[string]any `json:"clients"`
			} `json:"channels"`
			Count int `json:"count"`
		}
		if err := json.Unmarshal(body, &payload); err != nil {
			t.Fatalf("%q: decoding the list body: %v", tc.query, err)
		}
		if payload.Count != 1 || len(payload.Channels) != 1 {
			t.Fatalf("%q: the relay listed %d channels, want 1", tc.query, payload.Count)
		}
		if got := len(payload.Channels[0].Clients); got != tc.want {
			t.Fatalf("%q listed %d clients, want %d -- the cap is %d and ?clients=all lifts it",
				tc.query, got, tc.want, DefaultClientLimit)
		}
		// client_count is a SCARD in Python and is NEVER capped.
		if got := payload.Channels[0].ClientCount; got != clients {
			t.Fatalf("%q reported client_count %d, want %d -- the COUNT is never capped, "+
				"only the list is", tc.query, got, clients)
		}
	}
}

// An unsigned call is refused, and the refusal names nothing. The bound token
// signs the FULL path, so a token minted for the bare path does not authorise
// ?clients=all -- which is the exact route spec D4's whole argument rests on.
func TestTheListEndpointRefusesAnUnsignedOrMissignedCall(t *testing.T) {
	r := newRig(t, relaytest.Config{Rate: 4}, rigSettings(nil))
	response := r.tune(t, "c-auth", "client-a")
	defer func() { _ = response.Body.Close() }()

	for _, tc := range []struct {
		name    string
		request func() *http.Request
	}{
		{"no headers at all", func() *http.Request {
			req, _ := http.NewRequestWithContext(t.Context(), http.MethodGet,
				r.Relay.URL+"/proxy/relay/channels", nil)
			return req
		}},
		{"the principal header only", func() *http.Request {
			req, _ := http.NewRequestWithContext(t.Context(), http.MethodGet,
				r.Relay.URL+"/proxy/relay/channels", nil)
			req.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(rigSecret))
			return req
		}},
		{"a token signed for the bare path, sent with a query string", func() *http.Request {
			req, _ := http.NewRequestWithContext(t.Context(), http.MethodGet,
				r.Relay.URL+"/proxy/relay/channels?clients=all", nil)
			req.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(rigSecret))
			req.Header.Set(control.HeaderInternalRequest, control.InternalRequestHeader(
				rigSecret, http.MethodGet, "/proxy/relay/channels", nil, time.Now().Unix()))
			return req
		}},
		{"a token signed with the wrong secret", func() *http.Request {
			req, _ := http.NewRequestWithContext(t.Context(), http.MethodGet,
				r.Relay.URL+"/proxy/relay/channels", nil)
			req.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(rigSecret))
			req.Header.Set(control.HeaderInternalRequest, control.InternalRequestHeader(
				"not-the-deployment-secret", http.MethodGet, "/proxy/relay/channels", nil, time.Now().Unix()))
			return req
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			answer, err := http.DefaultClient.Do(tc.request())
			if err != nil {
				t.Fatalf("calling the list endpoint: %v", err)
			}
			defer func() { _ = answer.Body.Close() }()
			if answer.StatusCode != http.StatusForbidden {
				t.Fatalf("answered %d, want 403 -- the internal surface authorised a call "+
					"that did not carry a valid bound token", answer.StatusCode)
			}
		})
	}
}

// The trust marker gates EVERY X-Relay-* value, not just the channel. An
// untrusted request naming a client id, an address and a user must have all
// three ignored: nginx is the only thing that may assert who is asking, and
// apps/proxy/authorize.py is the only place that decision is made.
//
// Read off the LIST ENDPOINT rather than off the tune's status, because what a
// believed header would corrupt is the registry -- the client id an admin
// stops by, the address row 17 pins, and the user id the stream limit counts.
func TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader(t *testing.T) {
	r := newRig(t, relaytest.Config{Rate: 4}, rigSettings(nil))

	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet,
		r.Relay.URL+"/proxy/ts/stream/c-untrusted", nil)
	if err != nil {
		t.Fatalf("building the tune request: %v", err)
	}
	// Every X-Relay-* value a trusted request carries, and NO trust marker.
	request.Header.Set("X-Relay-Channel", "somebody-elses-channel")
	request.Header.Set("X-Relay-Client", "an-id-i-chose")
	request.Header.Set("X-Relay-Client-IP", "192.0.2.200")
	request.Header.Set("X-Relay-User", "10")
	request.Header.Set("User-Agent", "curl/8.0")

	response, err := http.DefaultClient.Do(request)
	if err != nil {
		t.Fatalf("tuning: %v", err)
	}
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the untrusted tune answered %d, want 200 -- an unmarked request is the dev "+
			"shape and still streams", response.StatusCode)
	}

	calls := r.Control.Requests()
	if len(calls) != 1 {
		t.Fatalf("the relay made %d control-plane calls, want 1", len(calls))
	}
	if got := calls[0].Path; got != "/api/relay/channels/c-untrusted/next-source" {
		t.Fatalf("the tune asked about %s: an unverified X-Relay-Channel was believed", got)
	}

	deadline := time.Now().Add(15 * time.Second)
	for {
		if ch := r.Manager.Get("c-untrusted"); ch != nil && ch.Clients() == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("the channel never registered its client")
		}
		time.Sleep(20 * time.Millisecond)
	}

	_, body := r.listChannels(t, "?clients=all")
	var payload struct {
		Channels []struct {
			Clients []map[string]any `json:"clients"`
		} `json:"channels"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatalf("decoding the list body: %v", err)
	}
	if len(payload.Channels) != 1 || len(payload.Channels[0].Clients) != 1 {
		t.Fatalf("the list shows %d channels", len(payload.Channels))
	}
	client := payload.Channels[0].Clients[0]

	if client["client_id"] == "an-id-i-chose" {
		t.Fatal("an unverified X-Relay-Client was believed: the client registered under an id " +
			"it chose, which is the handle an admin stops a client by")
	}
	if client["ip_address"] == "192.0.2.200" {
		t.Fatal("an unverified X-Relay-Client-IP was believed: parity-matrix row 17's address " +
			"is whatever the client claimed")
	}
	if client["user_id"] != nil && client["user_id"] != "0" {
		t.Fatalf("an unverified X-Relay-User was believed: the client counts against user %v "+
			"for the stream limit", client["user_id"])
	}
	// The User-Agent is the client's OWN header on every path and is believed
	// deliberately -- it is not an authorize-hop assertion.
	if client["user_agent"] != "curl/8.0" {
		t.Fatalf("user_agent is %v, want \"curl/8.0\": the request's own header is not an "+
			"X-Relay-* assertion and is read on both paths", client["user_agent"])
	}
}
```

### Appendix J — `relay/httpapi/testdata/channels_clients_all.json`

**Regenerate this from Django** (Task 7 Step 2). The copy below is this plan's transcription of what `RelayChannelListSerializer` renders from the fixture, written by hand from a full read of `apps/proxy/relay_serializers.py` and `channel_status.py`. It is deliberately spelled the way DRF spells it — `30.0` and `0.0` where Go writes `30` and `0` — so that a run of the golden test exercises the decoded comparison rather than accidentally agreeing byte for byte. **Yours governs.**

```json
{"channels": [{"channel_id": "11111111-1111-4111-8111-111111111111", "state": "active", "url": "http://provider.invalid/live/sub/pw/41.ts", "stream_profile": "1", "owner": null, "buffer_index": 120, "client_count": 2, "uptime": 30.0, "started_at": 1789000000.5, "channel_name": "BBC One HD", "m3u_profile_id": 3, "stream_id": 41, "stream_name": "BBC One HD (UK)", "total_bytes": 9999888, "avg_bitrate_kbps": 2665.3034666666666, "avg_bitrate": "2.67 Mbps", "clients": [{"client_id": "client_1789000000000_1234", "user_agent": "VLC/3.0.20", "output_format": "mpegts", "output_profile_id": 7, "ip_address": "198.51.100.4", "connected_at": 1789000001.25, "user_id": "7"}, {"client_id": "client_1789000000000_5678", "user_agent": null, "output_format": "mpegts", "output_profile_id": null}]}, {"channel_id": "22222222-2222-4222-8222-222222222222", "state": "stopped", "url": "", "stream_profile": "0", "owner": null, "buffer_index": 0, "client_count": 0, "uptime": 0.0, "started_at": 1789000100.0, "clients": []}], "count": 2}
```
