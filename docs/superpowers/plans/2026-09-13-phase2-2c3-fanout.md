# Phase 2 PR 2c-3 — the Go relay's multi-client fan-out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Go relay serve **N clients on one channel**. Three clients tune the same uuid, one upstream connection is opened, each of them reads an unbroken run of that upstream's bytes from its own join point roughly five seconds behind live, the relay knows who is attached, and `GET /proxy/relay/channels?clients=all` tells Django exactly what the Python relay tells it today. The last client leaving stops the channel; a client arriving as the last one leaves does not lose it.

**Architecture:** 2c-2's ring, manager and tune path gain the reader dimension. `buffer` gets a bounded `Read` so a lagging reader cannot pin a whole ring's worth of evicted chunks. `channel` gets the client registry that replaces `live:channel:{id}:clients`, its metadata hash, its TTL and its heartbeat thread, plus the last-client rule made atomic with the arrival path. `httpapi` gets the four trust-gated `X-Relay-*` values a client is registered from, and one new internal route. One Python change: a golden fixture rendered by Django's own serializer, so the Go payload is pinned against the other implementation rather than against a hand-typed guess.

**This is the PR where the relay stops being a single-reader proof and starts being a relay.** It stays inert in every deployment: both routes are behind 2c-1's dev flag, and nginx routes nothing to port 5658 until stage 2d.

---

## Sequencing: this plan sits on 2c-2's fix commits, verified at `87dca88d`

2c-2's own review confirmed all three defects this plan found by reading its code, and 2c-2 fixed them itself. **Everything below was rebuilt and re-verified against `migration/phase2c-vertical-slice` at `87dca88d`** (`b5e62fcf` through `87dca88d`, eight commits, **review-2c2 CLEAR and out of draft**), including every `_test.go`. The three shapes, pinned with `git show "87dca88d:relay/…"` rather than read off a working tree:

| Fix | Shape as landed | What 2c-3 does with it |
|---|---|---|
| `relay/channel/manager.go` | `release()` calls `stopIfStillIdle(c)`, which takes `m.mu`, **re-reads `c.Clients()`**, checks `m.channels[c.id] == c`, deletes only then and stops outside the lock. `dropClient` stays **outside** the lock. | **Preserve it exactly.** 2c-3 changes two things: the drop names a client, and the delay comes off `Tuning` rather than `ManagerConfig`. The one-lock decision, the re-check and the identity check are not reintroduced and not restructured. |
| `relay/channel/source_proxy.go` | `Run` does `defer client.CloseIdleConnections()` on the `*http.Client`; `transport()` still builds a fresh transport per Run. | **Nothing.** This plan's Task 4 is deleted — 2c-2's fix is better than the one this plan proposed (it is a no-op when `s.Transport` is an injected `RoundTripper` that does not implement the method, where returning a closer from `transport()` needed a branch for that case). Task 4 becomes a verification step inside Task 0. |
| `relay/buffer/ring.go` | `Read`'s `next` is the index of the last chunk **actually appended**, tracked in the loop, with the contract in the doc comment. `TestNextIsTheLastChunkActuallyReturnedNotTheRingsTail` asserts `next == cursor + len(out)`. | **Keep the invariant and cite the test.** Task 1's cap must set `next` from the appended chunk, which it does; that test starts discriminating the moment a cap exists, so 2c-3 writes **no second test for it**. |

**Why `stopIfStillIdle`'s shape is still correct with a registry**, since this plan's own earlier draft put the drop inside the lock instead: `claim`'s `addClient` and `stopIfStillIdle`'s re-check are both under `m.mu`, so whichever runs first is the one acted on and the other sees the consequence — either the entry is already gone and the arrival starts fresh, or `Clients()` is back above zero and the stop is a no-op. Swapping a counter for a map does not touch that argument. **Do not "improve" it.**

**`markActive` is gone and `promoteOnFirstChunk` replaces it**, and this plan's appendices are built on that. `run()` now starts `promoteOnFirstChunk(ctx)`, one goroutine per channel waiting on `Ring.Wait(ctx, 0)`, which sets `StateActive` on the first published chunk; `Attach`'s reuse path calls nothing. **This is the only place `state` moves to `active`**, and 2c-2's own comment records why: the old `markActive` fired on a *second* client's arrival, never the first, and reached `active` in 0 of 300 measured rounds.

**Ruled, and binding on every task below: 2c-3 adds no second first-chunk watcher.** Anything in this PR that needs to know a channel has started reads `Channel.State()` or extends `promoteOnFirstChunk`; it does not start its own `Ring.Wait(ctx, 0)`. A second mechanism makes `TestAChannelWithFlowingBytesBecomesActive` hollow — 2c-2's reviewer proved it by injection — because deleting either one leaves the other setting the state and the test green.

**What is NOT a second watcher, stated because it looks like one:** `serveClient`'s per-client `ring.Wait(ctx, cursor)`. That is the fan-out's ordinary reader wake-up on a cursor the client owns (Ruling R1), it never reads cursor 0 as a start signal, and it sets no state. As it happens 2c-3 needs no first-chunk signal at all — the client registry keys on attach, not on bytes — so the rule costs this PR nothing and exists to stop the next person adding one.
- **Do NOT add pins for the five constants 2c-2 pinned** in `TestTheTimeoutsMatchPython`, `TestProxySourceDefaultsMatchPython` and `TestNominalByteRateAndWriteChunkMatchThePythonHarness`. This plan pins exactly two, `httpapi.DefaultClientLimit` and `buffer.MaxChunksPerRead`. **Checked: neither name appears in any of those three tests**, and neither constant exists in 2c-2 at all — both are introduced by this PR, so there is no duplication.

**And seed your scratch module from the branch INCLUDING its `_test.go` files**, never from a plan's appendices. Both blocking findings against this plan's first draft — symbol collisions and broken call sites — came from building against a plan rather than a branch, and neither is visible until `go vet` runs over the merged package.

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

Compare the two costs **per publish**, which is the only way they are comparable: one publish wakes 1,600 goroutines — each a list-traversal entry off a closed channel — and hands those same 1,600 readers 255,868 bytes each, **409 MB written to sockets**. That is about **256 KB of socket write per wakeup**. The wakeup is not the cost; the bytes are. **There are also no spurious wakeups**: a waiter blocks only when it is caught up, and a publish is exactly the event it is waiting for, so every wakeup does work. Per-client notification would add cost and remove nothing.

**What is NOT ruled here**, because it is not the wakeup: a slow reader's *hold* on evicted chunks. That is R2.

### R2 — `Read` is capped at twenty chunks, and the cap is ported from Python for a reason 2c-2 only half-had.

2c-2 declined to port `get_optimized_client_data`'s batching (`input/buffer.py:325-372`) on the grounds that its four constants exist to amortise a Redis round trip per chunk, and an in-memory ring has no round trip to amortise. **That is right about three of the four constants and wrong about `MAX_CHUNKS`.**

`MAX_CHUNKS` (`input/buffer.py:329`) bounds how much a lagging reader **holds at one instant**, and a held chunk's backing array stays alive after the ring has evicted it — the garbage collector keeps it exactly as long as someone holds it, which is `Chunk.Data`'s own documented contract. Uncapped, one reader behind the head takes `[cursor+1, head]` in a single `Read`, so it can pin a whole ring's worth of evicted chunks on top of the resident ring: **2 × `MaxBytesPerChannel`, about 146 MiB**, where `relay/buffer/buffer.go`'s own sizing note states 73 MiB per channel. Capped, the extra is at most twenty chunks — about 5 MiB — per *distinct* lagging cursor, and readers at the same cursor share one set of arrays.

**Ruled: `MaxChunksPerRead = 20`, `input/buffer.py:329`, and only that one.** `MIN_CHUNKS`, `TARGET_SIZE` and `MAX_SIZE` stay unported with 2c-2's reason intact. Note what reading the Python actually says about the cap's worth: Python's initial count is a **three-branch** on how far behind the client is (`input/buffer.py:336-345`, whose first arm is `max(1, chunks_behind)`) and `MAX_CHUNKS` is only its largest arm; `MAX_SIZE` (2 MiB) then gates the **second, top-up** fetch alone (`:361-371`), never that initial one. So twenty chunks at the effective chunk size — 5,117,360 bytes — is what Python's cap is worth too. An earlier draft of this ruling wrote the initial count as `min(chunks_behind, MAX_CHUNKS)`, which is the right ceiling and the wrong expression.

**`Read`'s `next` moves with the cap**, and that is the half of this ruling most easily got wrong. 2c-2 returned `r.chunks[len-1].Index`, the ring's newest resident; with a cap those stopped being the same thing, and a `next` that ran ahead of the bytes actually handed over would make a lagging client skip everything it did not receive — silently, with no `skipped` to log.

**Python has that defect and Go does not, which is a divergence rather than a port.** `get_optimized_client_data` returns `client_index + chunk_count` (`input/buffer.py:373`) — the count it *asked* for, not the count it got — so a short read there skips undelivered chunks. Returning the last index **actually returned** is strictly better and is recorded in the PR description's divergence list rather than quietly improved.

**`skipped` is an addition too.** Python computes the same number only inside a log string (`output/ts/generator.py:354-358`) and no caller ever sees it; returning it is new. Both are safe-direction additions on a path where Python loses information, and both are stated rather than presented as parity.

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

**2c-2 fixed this itself, and the shape it shipped is the one to preserve.** `release` drops the client outside `m.mu` and then calls `stopIfStillIdle(c)`, which under `m.mu` **re-reads `c.Clients()`**, checks `m.channels[c.id] == c`, deletes only then, and stops with the lock released. The drop staying outside the lock is fine because the *decision* is inside it: `claim`'s `addClient` and this re-check are both under `m.mu`, so whichever runs first is the one acted on and the other sees the consequence — the entry is already gone and the arrival starts fresh, or `Clients()` is back above zero and the stop is a no-op.

**Swapping a counter for a registry does not touch that argument**, which is why 2c-3 changes two lines of `release` and none of `stopIfStillIdle`. An earlier draft of this plan proposed pulling the drop inside the lock as well; that is also correct and it is not what landed, and reintroducing it would be a rewrite of a function whose current shape is pinned by 2c-2's own race test.

**The identity check (`existing == c`) guards a narrower case than the race**: by the time a delayed stop fires, the map may hold a *different* `*Channel` under the same id — the first finished, `claim` dropped it, a later tune published a replacement. Deleting by id alone evicts a live successor and strands its clients on a channel nothing can stop.

### R6 — A test whose oracle wraps is not a test. The join-point assertion needs an asset longer than the run.

The first draft of `TestASecondClientJoinsBehindLiveAndNotAtTheHead` compared the second client's first `PacketIndex` against the ring's head converted to packets. **Deleting the `Ring.Join` call from `serveClient` entirely left it green.**

The reason: `PacketIndex` is the packet's position **in the asset**, and a looping upstream restarts it at zero. With a 4,096-packet asset — 3.1 seconds at the nominal rate — the index wrapped several times inside the test while the head kept counting up, so "how far behind live did this client start" compared a number in `[0, 4096)` against one that grows without bound. It is large and positive whatever the relay does.

**Ruled: `rigAssetPackets = 65536`** — 12.3 MB, 49 seconds at the nominal rate, longer than any test here runs — **and the fix is recorded in the constant's own comment**, because the next person to shrink the asset for speed will reintroduce it. With it, the same break-check reddens: `the second client started at packet 8400 with the live head at packet 8400: it joined AT live, not behind it -- new_client_behind_seconds was ignored`.

### R7 — The list endpoint carries the provider URL, and that is parity rather than a credential leak.

`channel_status.py:472` puts `ChannelMetadataField.URL` — the provider URL, credentials in its path or query — into `get_basic_channel_info`'s payload, and `/proxy/stats/` and the Stats page show it. Global Constraint 12 forbids a provider URL in a log, an error message or an HTTP response body.

**Ruled: emit it, exactly as Python does, and state the distinction rather than leaving a reviewer to infer it.** The constraint's target is a **log** (a broad, long-lived, unauthenticated-by-default audience) and a **public error body**. `GET /proxy/relay/channels` is neither: it is an internal route gated on the static `X-Dispatcharr-Internal` **and** a per-request bound token, reachable only by a caller holding `SECRET_KEY`, and it carries this URL today. Omitting it would blank the Stats page's URL column for every Go-served channel — a behaviour change D5 forbids — and would not remove the exposure, because the detail endpoint 2c-8 builds carries it too.

What does **not** change: `writeTuneFailure` answers with a fixed string per class of failure, `channel.withoutURL` strips `*url.Error`'s copy before it reaches a log, and no log line in this PR names a URL.

### R8 — The client registry carries seven fields, not the spec's eight, and `worker_id` and `last_active` wait for 2c-8.

The Redis client hash carries eight fields — `user_id`, `output_format`, `output_profile_id`, `ip_address`, `user_agent`, `connected_at`, `last_active`, `worker_id` (`client_manager.py:235-244`). **That is the hash, not this endpoint's payload.** `RelayChannelClientSerializer` (`apps/proxy/relay_serializers.py:22-31`) declares seven, and neither `last_active` nor `worker_id` is among them; both appear only on `RelayDetailClientSerializer` (`:72-88`), which renders the **detail** endpoint 2c-8 builds. (An earlier draft attributed the eight-field list to spec § The contract, which in fact enumerates the six *serializers*, not the hash's fields. The conclusion is unchanged.)

**Ruled: `channel.Client` carries exactly the seven the list endpoint renders.** Adding two fields nothing reads is the stale-duplicate-of-the-truth shape 2c-2's R5 refused, and the per-client byte counters (`bytes_sent`, `avg_rate_KBps`, `current_rate_KBps`) go with them for the same reason. **2c-8 owns all five**, together with the detail endpoint and `owner`'s asymmetric `'unknown'` default that parity-matrix row 14 pins.

### R9 — `owner` is `null` on the list endpoint, and the assertion for it has to be on the handler's output.

`get_basic_channel_info` sets `'owner': metadata.get(OWNER)` unconditionally — always present, null when no worker holds the lease. Spec D2 deletes the election outright, so a Go relay has no worker to name. The alternative — synthesising a process identity — invents a value with no Python source.

**Ruled: `owner` is always present and always `null`.** No consumer reads it: grepped across `frontend/src` (**zero** hits for the word) and across `relay_client`'s two readers of this payload, `list_channels` and `live_connections`, which take `channel_id` and `clients`. The **asymmetry** parity-matrix row 14 pins — the detail endpoint defaulting to the literal string `'unknown'` — is 2c-8's to carry.

**And the assertion goes on the LIVE payload, not on the golden fixture.** The break-check that made `describeChannel` name a process identity left the golden tests green, because they compare a struct literal that hard-codes a nil owner against a file that says `null`; neither runs the handler. One line in `TestTheLiveEndpointProducesTheGoldensKeySet` closed it. **That is this plan's second break-check that did not redden**, and it is the reason the live key-set test exists at all.

### R11 — `startProxyTune` detaches from the calling client's request context.

`Manager.Attach` runs `start()` behind a per-channel gate: the first client in makes the next-source call and every later client for that channel waits on the gate. 2c-2 passed `r.Context()` into that call, which is correct at one client and wrong the moment a second can be waiting — that client's tab closing cancels next-source for everyone parked behind it.

**Python detaches, by construction rather than by choice.** Its tune calls `generate_stream_url` → `control_plane.next_source` from inside the client's own request greenlet (`apps/proxy/live_proxy/views.py:340` and `:390`), and uWSGI does not cancel a greenlet when its client hangs up — the greenlet runs to completion and only discovers the disconnect on a later write. So the channel starts, and the clients polling `_channel_setup_needed` attach to it. **A Go relay that propagated cancellation would be strictly less available than the Python one it replaces**, which is the opposite of what D5 asks for.

**Ruled: `context.WithTimeout(context.WithoutCancel(parent), tuneBudget)`.** `WithoutCancel` keeps any values on the request context while dropping its cancellation, and the timeout puts back a bound of the right shape — the control client's own worst case rather than the viewer's patience:

```go
// control.Client's own worst case: two attempts of (ConnectTimeout,
// ReadTimeout) plus the retry delay between them. `attempts` is unexported, so
// the 2 is written here; if control ever changes it this over- or undershoots,
// which costs a longer or shorter gate wait and never correctness, because each
// attempt is still bounded by the client's own http.Client.Timeout.
const tuneBudget = 2*(control.ConnectTimeout+control.ReadTimeout) + control.RetryDelay
```

**The test sets `channel_shutdown_delay` to 2s, and that is what makes it deterministic.** Two independent things can make the waiting client cause a second next-source call: the context (what this test is about) and a **teardown race** (the call completes and the channel publishes, but the first client's release runs before the waiter re-claims, sees zero clients, and stops the channel underneath it). The second is real behaviour, not an artefact, and with the default zero delay it reddened this test at roughly **one run in three** — measured, and caught only because the suite was run eight times rather than three. A non-zero grace window closes it: the release schedules a stop, the waiter re-claims inside the window, and `stopIfStillIdle` then sees a client. Measured afterwards: **8/8 green with the fix and 5/5 red without it.**

**The damage from getting this wrong is smaller than it first looks, and the plan says so rather than overstating it.** Measured against the attached-context version: the second client still gets its 200 and its bytes, because the cancelled start returns an error, `Attach`'s deferred `releaseGate` opens the gate, and the waiter re-claims and makes its own call. What is lost is **a wasted control-plane round trip per departing tuner**, a failed response for the client that left, and a real failure for the waiter whenever that retry also fails. So the assertion that discriminates in `TestTheTuningClientLeavingDoesNotFailTheTuneForEveryoneElse` is **the next-source request count**, not the status — and the test says which, because a break-check that reddens on the wrong assertion teaches the next reader the wrong mechanism.

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
| `channel.Channel` with `ID`, `Ring`, `Tuning`, `State`, `Err`, `Clients`, `Done`, `run`, `stop`, `setState`, `addClient`, `dropClient` | **as landed**; `markActive` is deliberately NOT in this list — see Task 0 Step 2 | Task 2 replaces the client counter with a registry |
| `channel.Manager` with `NewManager`, `Attach(id, start)`, `claim`, `publish`, `releaseGate`, `Get`, `Stop`, `StopAll`, `ids`, `release`, `take` | **as planned in 2c-2** | Task 3 changes `Attach`'s signature and rewrites `release` |
| `control.Settings` with `Int`, `Float`, `Seconds`, `String` and `ErrSettingAbsent`; `control.Client.NextSource`; `Unavailable`, `Refused`, `ErrNotConfigured`; `KindProxy` | **as planned in 2c-2** | Task 5 calls all of these |
| `httpapi.StreamDeps`, `StreamHandler`, `channelIDFor`, `startProxyTune`, `writeTuneFailure`, `serveClient`, `writeChunks`, `tuningFrom`, `ErrNotProxyKind`, `ErrNoSource` | **as planned in 2c-2** | Task 5 rewrites `channelIDFor` into `identify` and adds two arms to `writeTuneFailure` |
| `relaytest.SyntheticTS`, `PacketIndex`, `AlignmentProblem`, `PacketSize`, `NominalByteRate`, `NewUpstream`, `Config`, `Upstream.Requests`/`Headers`, `NewControlPlane`, `ControlPlaneConfig`, `EffectiveProxySettings` | **as planned in 2c-2** | every test here builds on them |
| `relaytest.EffectiveProxySettings()` carries `channel_shutdown_delay` | **as planned in 2c-2** (value 0) | Task 5's per-key subtest needs it; add it if absent |
| Amendment **A2** in the spec, and rows 7 and 9 of the parity matrix carrying Go references | **as planned in 2c-2** | Task 11 appends **A3** after it; Task 9 appends to rows 8, 10 and 13 |
| `scripts/check_go_stdlib_only.sh` with 2c-2's Redis `go list -deps` check | **as planned in 2c-2** | Task 12 extends nothing; it re-runs it |

**Verified in this tree, not inherited:** everything with a `file:line` in this plan — `apps/proxy/live_proxy/client_manager.py` in full, `output/ts/generator.py`'s positioning, keepalive, timeout, ghost and per-client-stats paths, `input/buffer.py`'s `get_optimized_client_data` and `find_chunk_index_by_time`, `channel_status.py`'s `get_basic_channel_info` and `build_live_channel_stats_data`, `relay_serializers.py` in full, `relay_views.py`'s `channels_view`, `relay_client.py`'s `list_channels` and `live_connections`, `apps/proxy/authorize.py:145-147` and `:483-503`, `apps/proxy/config.py:110-114`, `docker/supervisord/all.conf`, `docker/tests/test-puid-pgid.sh:482` and `:1318`, `docker/supervisord/relay.conf`, and the fact that `ChannelMetadataField.LOGO_ID` is written **only into the timeshift key family** (`apps/timeshift/views.py:2984`) and never into the live metadata hash `channel_status.py:486` reads.

---

## File Structure

```
relay/buffer/ring.go                    EDIT — MaxChunksPerRead, Read's cap and cursor, the byte counter
relay/buffer/fanout_test.go             NEW  — the cap, the N-reader immutability rule, N readers under -race
relay/channel/client.go                 NEW  — the registry's row type
relay/channel/tuning.go                 EDIT — ShutdownDelay joins the snapshot
relay/channel/channel.go                EDIT — clients map, SourceInfo, startedAt, ClientSnapshot, ErrDuplicateClient
relay/channel/manager.go                EDIT — Started, Attach takes a client, release's two lines, Snapshot
relay/channel/fanout_test.go            NEW  — six tests, three of them concurrent
relay/channel/manager_test.go           EDIT — asStarted + testClient, and fourteen Attach call sites
relay/channel/concurrent_test.go        EDIT — the fifteenth Attach call site, plus an fmt import
relay/httpapi/stream.go                 EDIT — identify(), ErrUnsupportedOutput, mintClientID, Started, the detached tune context
relay/httpapi/channels.go               NEW  — GET /proxy/relay/channels and its internal-auth gate
relay/httpapi/server.go                 EDIT — ControlDeps and the second dev route
relay/httpapi/stream_test.go            EDIT — newRig wires ControlDeps against the SAME manager
relay/internal/relaytest/controlplane.go EDIT — ControlPlaneConfig.Delay, so a test can act mid-tune
relay/httpapi/fanout_test.go            NEW  — extends 2c-2's rig; the fan-out test, row 8, row 10, the cap, the auth gate
relay/httpapi/golden_test.go            NEW  — the cross-implementation payload pin
relay/httpapi/testdata/channels_clients_all.json   NEW — rendered by Django's serializer
relay/main.go                           EDIT — wire ControlDeps

                                        --- the Python half ---
apps/proxy/tests/test_relay_list_payload_golden.py  NEW — renders and pins the golden from both sides

                                        --- infrastructure ---
docker/tests/test-puid-pgid.sh          EDIT — the 'all' roster gains relay-uwsgi and relay-go; the 'relay' roster gains relay-go
docker/supervisord/relay.conf           EDIT — one comment: its glob no longer picks up a single program

                                        --- documents ---
docs/relay-parity-matrix.md             EDIT — rows 8, 10 and 13 gain a Go reference
docs/superpowers/specs/2026-09-09-…-design.md   EDIT — Amendment A3, a Done log row
CLAUDE.md                               EDIT — § Architecture, § Known defects
```

Nothing under `core/`, `dispatcharr/`, `frontend/`, `e2e/` or `metrics/` is touched, and nothing under `apps/` beyond the one new test file.

**Four of those are edits to 2c-2's own committed test files**, and they are listed here rather than discovered at `go vet`: two absorb the `Attach` signature change, one wires the list endpoint's dependencies to the manager the tune path already uses, and one adds a delay knob to the fake Django. **`relay/channel/source_proxy.go` is NOT edited** — 2c-2's fix commit closed the transport leak itself.

---
## Task 0: Diff the merged 2c-2 tree against this plan's expectations

**Nothing else is written until this task is done and reported.** The ledger above was written against the 2c-2 *plan*, which at the time of writing was not implemented. Every "as planned in 2c-2" row is a prediction; this task turns each into a fact or a finding.

- [ ] **Step 0: Seed from the MERGED SHA, not from the branch**

  ```bash
  cd <your worktree> && git log --oneline -1 <2C2_MERGED_SHA>
  git diff --stat <2C2_MERGED_SHA> HEAD -- relay/
  ```

  **`<2C2_MERGED_SHA>` is filled in by the orchestrator before this plan is dispatched.** A branch name is not a seed: `migration/phase2c-vertical-slice` moved three times while this plan was being written, and each move changed a shape the appendices depend on. The appendices below were built and verified against **`87dca88d` plus 2c-2's `markActive` removal**; anything later is a diff against that, and **Step 2's table is the diff**.

  If any symbol in Step 2 differs from what that table expects, **stop and report before writing a line**. Reconciling a moved shape mid-task is how an appendix quietly stops matching the tree it was verified against.

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
  | `(*Manager).release` | **as landed at `87dca88d`**: `dropClient` outside the lock, then `stopIfStillIdle(c)` which re-reads `Clients()` and checks `m.channels[c.id] == c` under `m.mu` | if you find the two-step `m.Stop(c.id)` shape, the tree is older than `87dca88d` — stop and report rather than applying this plan to it |
  | `ProxySource.Run` | **as landed**: `defer client.CloseIdleConnections()` right after the client is built | if absent, same answer: wrong base |
  | `(*Ring).Read`'s `next` | **as landed**: the index of the last chunk appended, tracked in the loop | if it returns `r.chunks[len-1].Index`, same answer |
  | `(*Channel).markActive` | **expected ABSENT.** 2c-2's next fix commit makes `run()` set `StateActive` on the first chunk and removes or repurposes this method; the appendices here carry neither the method nor `Attach`'s call to it | **if it is still present**, the tree is older than that fix: a channel this PR serves will report `waiting_for_clients` for its whole life on the list endpoint. Measured — see Step 2a. Stop and report rather than re-adding the call |
  | `(*Channel).run` sets `StateActive` | **expected present**, on the first published chunk | if neither this nor `markActive` exists, no channel ever reaches `active` and the list endpoint says so. That is the one thing in this PR that cannot be fixed from inside it |
  | `(*Channel).clients` | an `int` | Task 2 replaces it with a map |
  | `Tuning` | three fields | Task 2 adds a fourth |
  | `control.VerifyInternalRequest` | present and exported | Task 6 cannot gate the route without it |

- [ ] **Step 2a: Probe what `state` a serving channel reports**

  The one check in Task 0 that is a behaviour, not a signature, and it is here because the appendices depend on a fix that had not landed when they were written:

  ```bash
  cd <your worktree>/relay && grep -n "StateActive" channel/channel.go
  ```

  **Expect `run()` to set it on the first published chunk.** Measured on a tree with `markActive` removed and no replacement: a channel with a client reading it reports `waiting_for_clients` on `GET /proxy/relay/channels` for its whole life, because nothing else ever moves it. That is 2c-2's to fix and this PR cannot fix it from inside — but this PR's list endpoint is the first thing that *renders* it, so it is this PR's job to notice.

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

  In `relay/buffer/ring.go`, **above `ErrClosed`'s own doc comment** — not between that comment and the `var`. Placing it literally "above `ErrClosed`" splits the sentinel from its documentation and `revive` reports it twice: *comment on exported const MaxChunksPerRead should be of the form "MaxChunksPerRead ..."* and *exported var ErrClosed should have comment or be unexported*. Measured; the Go edit hook blocked on exactly this while this plan was being verified.

  ```go
  // MaxChunksPerRead bounds how many chunks one Read hands back.
  //
  // The port of get_optimized_client_data's MAX_CHUNKS
  // (apps/proxy/live_proxy/input/buffer.py:329), and the ONLY one of that
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

  Then add the cap to `Read`'s existing selection loop. **Two lines and a `continue`, on the shape `87dca88d` already has:**

  ```go
  	for _, c := range r.chunks {
  		if c.Index < want {
  			continue
  		}
  		// The cap. next keeps tracking the last chunk APPENDED, which is
  		// 2c-2's contract and is what makes a capped read correct rather than
  		// a silent gap: a next that ran ahead to the ring's tail would make a
  		// lagging client skip everything this call did not hand it.
  		if len(out) == MaxChunksPerRead {
  			break
  		}
  		out = append(out, c.Data)
  		next = c.Index
  	}
  	return out, next, skipped
  ```

  And give `out` a bounded capacity: `make([][]byte, 0, min(len(r.chunks), MaxChunksPerRead))`.

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
  | 2 | `next = c.Index` inside the loop becomes `next = r.chunks[len(r.chunks)-1].Index` after it | **2c-2's `TestNextIsTheLastChunkActuallyReturnedNotTheRingsTail`**, not a test of this PR's | `next = 40, want 20 (cursor 0 + 20 chunks actually returned) -- next must track what was handed back, not the ring's own head` |
  | 3 | a `scratch []byte` **field** on `Ring`, allocated once and reused for every chunk | `TestAChunkIsUnchangedAfterEveryClientHasServedIt` | `byte N of a chunk reader M still holds changed from …: a published chunk's backing array was reused` |
  | 4 | drop the `RLock` from `TotalBytes` | `TestManyConcurrentReadersAndOneWriter` | `WARNING: DATA RACE`, with both stacks |

  **Number 2 is 2c-2's check, run here because this PR is what arms it.** Before the cap, `next` and the ring's tail were the same value and that test could not fail; after it, they diverge. Running it is how you confirm the cap and the cursor agree — and it is why this PR adds no `next` assertion of its own.

  **Numbers 11 and 12 in Task 5 need a keep-alive line** (`_ = tuning.JoinBehind`, `_ = trusted`): deleting the branch outright leaves a variable unused and the package fails to COMPILE, which tells you nothing about the test. Both were first written without it.

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

  0. **`markActive` and its one caller are gone** (see § Sequencing). If your seed still has them, stop: the tree predates 2c-2's `StateActive` fix.
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
  | 2 | `ClientSnapshot` returns the map in range order | **expected not to redden.** Report the gap rather than forcing it |

  **Number 2 is listed precisely because it is expected not to redden, and its reason has to be the true one.** It is NOT that the fixture has one client per channel — the golden's first channel has two. It is that **neither golden test runs the handler**: both compare a Go struct literal against the file, and the literal spells its clients out in order. The live key-set test does run the handler but compares key *sets*, which order does not change.

  So the gap is real and it is accepted: ordering is not a parity property — `channel_status.py:533` reads a Redis SET — determinism here is a testing convenience, and an assertion for it would pin this plan's own choice rather than a behaviour. **An earlier draft of this row gave the wrong reason for the right prediction**, which is this plan's own instance of hollow shape six: a correct outcome read off a mechanism that was not the one operating.

- [ ] **Step 5: Run the four checks and commit**

---
## Task 3: `relay/channel` — the manager's arrival and departure, under one lock

Ruling R5. This is the task the ordering tests exist for, and the one where `-race` is no help at all.

- [ ] **Step 1: Edit `relay/channel/manager.go` — a delta, not a rewrite**

  **The complete file is Appendix D**, and the part of it that matters most is what is **unchanged**: `release`'s drop stays outside `m.mu`, and `stopIfStillIdle` keeps its re-check, its identity check and its stop-outside-the-lock. That is 2c-2's fix commit `87dca88d`, demonstrated by its own `TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined` at roughly one race in several thousand rounds against the pre-fix code. **Preserve it.**

  Five changes to it:

  1. **`Started`**, a struct the start function returns, replacing the three-value `(Source, Tuning, error)`. It carries `Info SourceInfo` as well, which the list endpoint needs and which a fourth return value would have made unreadable.
  2. **`Attach(id string, client *Client, start func() (Started, error))`**. The client is registered inside `claim`, under `m.mu`, which is what makes the arrival path and the departure path mutually exclusive.
  3. **`claim` returns a fourth value, an error**, so a duplicate client id is refused at the point the map is inspected rather than in a second, unsynchronised step.
  4. **`release(c, clientID)`** — two lines different from 2c-2's: `c.dropClient(clientID)` instead of `c.dropClient()`, and `c.tuning.ShutdownDelay` instead of `m.cfg.ShutdownDelay` (twice). `stopIfStillIdle` is **not touched at all**. `ManagerConfig.ShutdownDelay` is deleted in the same edit, so no caller can supply the old one by accident.
  5. **`Snapshot()`**, every channel in id order, which Task 6's list endpoint reads.

  The whole of `release` afterwards, which is the whole of the delta:

  ```go
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
  ```

  **`Channel.Clients()` must never take `m.mu`**, and its doc comment now says so: `stopIfStillIdle` calls it *while holding* the manager lock, so a channel method that reached back for the manager's lock would deadlock the process on the first release. The lock order is manager then channel, one way only.

  **Everything 2c-2 ruled about `Attach` is preserved and must stay preserved.** `start()` runs outside the manager lock; the per-channel gate is closed from a **deferred** call registered in `Attach` **before** `start()` runs, so it fires at `Attach`'s return, after `publish` has installed the channel; `claim` drops a channel whose ring has closed, and that is the only place it happens. Moving the gate's close into a helper around `start()` wakes a waiter that then races the map insertion, claims a fresh gate and opens a **second** upstream — 2c-2 measured it going wrong within three rounds at eight concurrent clients.

- [ ] **Step 2: Rewrite the fifteen `Attach` call sites this package inherits**

  `Attach(id, start func() (Source, Tuning, error))` becomes `Attach(id, *Client, start func() (Started, error))`, and **sixteen call sites in 2c-2's own committed tests break** — measured at `87dca88d`, up from fifteen at `9f744890` because `b05cc401`'s state test adds one. Naming them, because a signature change that lists no call sites is a signature change somebody discovers at `go vet`:

  | File | Lines (at `87dca88d`) |
  |---|---|
  | `relay/channel/concurrent_test.go` | one |
  | `relay/channel/manager_test.go` | fifteen of them |

  **Three of them are 2c-2's own fix-commit tests** — `TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined` (twice, to `shared`, so two distinct ids) and `TestAChannelWithFlowingBytesBecomesActive`. Line numbers are deliberately not listed: they moved between `9f744890` and `87dca88d` and will move again.

  **Count them, do not trust this table.** Line numbers move with every fix commit and the total can too:

  ```bash
  cd <your worktree>/relay && grep -c '\.Attach(' channel/manager_test.go channel/concurrent_test.go
  ```

  Measured at `87dca88d`: **15 + 1 = 16**. A different total is a finding for the report, not something to reconcile silently.

  **Two adapters in `manager_test.go` absorb all sixteen**, rather than sixteen closure rewrites. None of those tests is about `SourceInfo` or about client identity — they are about one source per channel, the gate, the panic guarantee and the finished-channel drop — so the change should not touch what they say:

  ```go
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
  func testClient(id string) *Client { ... }
  ```

  **Every call site gets its own client id.** `TestTwoClientsShareOneSource` attaches twice to `chan-1`; under one id the second attach would now be refused, and the test would fail for a reason that has nothing to do with what it asserts. Two clients are two ids.

  `concurrent_test.go:93` is inside a per-client goroutine, so its id is `fmt.Sprintf("client-%d", i)` and the file gains a `fmt` import.

  **Verified: all of 2c-2's channel and httpapi tests pass unchanged against this PR's tree** once the sixteen sites are rewritten — the cap, the byte counter, the registry and `release`'s two lines regress none of them, `TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined` included.

- [ ] **Step 3: Write `relay/channel/fanout_test.go`**

  **The complete file is Appendix E**, and it is deliberately short on fixtures, because **one package gets one of each**. These five symbols are 2c-2's and are NOT redeclared:

  | Symbol | Where 2c-2 defines it |
  |---|---|
  | `sourceCounter` (+ `enter`, `leave`, `snapshot`) | `channel/concurrent_test.go:39-61` |
  | `countingSource` (+ `Run`) | `channel/concurrent_test.go:31-37` |
  | `waitForStart(t, c, round)` | `channel/concurrent_test.go:16-28` — note the **third argument**, a round number; pass `0` where there is no loop |
  | `testTuning()` | `channel/manager_test.go:15` — two fields, no `JoinBehind`; **leave it alone**, this PR's channel tests do not read it and the grace-window test builds its own `Tuning` |
  | `testClient(id)` | added by Step 2 above |

  `startCounting` is this file's one addition.

  This file adds exactly one fixture of its own, `startCounting`, which is `Started` wrapped around `countingSource`.

  Six tests, three of them concurrent:

  | Test | What it pins |
  |---|---|
  | `TestNClientsShareOneSourceAndTheChannelOutlivesAllButTheLast` | six clients, **one** source, and the channel surviving every release but the last |
  | `TestASecondAttachUnderAnAttachedClientIDIsRefused` | **row 13's first half** — registration is idempotent per client id |
  | `TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel` | **R5's ordering**, 400 rounds |
  | `TestTheShutdownDelayKeepsAChannelForAReconnectingClient` | **R4** — the grace window, supplied non-default at 400 ms |
  | `TestADelayedStopNeverEvictsAReplacementChannel` | `stopIfStillIdle`'s identity check, at the delayed path 2c-2's own test does not reach |
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

- [ ] **Step 4: Break-check, three edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | `stopIfStillIdle`'s `c.Clients() != 0` moves **outside** the `m.mu` closure — 2c-2's own pre-fix shape | `TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel` **and** 2c-2's `TestAReleaseCannotStopAChannelAConcurrentAttachJustJoined` | `round 0: the arriving client holds a channel the manager does not (channel one state=stopped clients=1 head=0 vs <nil>): it was stopped underneath a live client`, alongside `round 6: the second client was handed a stopped channel` |
  | 2 | `stopIfStillIdle`'s `ok && existing == c` becomes a bare presence check | `TestADelayedStopNeverEvictsAReplacementChannel` **only** | `the first channel's delayed stop evicted the replacement: the map holds <nil>, want the channel the live client is watching` |
  | 3 | `if remaining == 0 && c.tuning.ShutdownDelay <= 0` becomes `if remaining == 0` | `TestTheShutdownDelayKeepsAChannelForAReconnectingClient` | `the channel was stopped immediately: the shutdown delay did not apply` |

  **Number 1 reddens BOTH tests, and that is the point of running it.** 2c-2's own race test covers the immediate path; this PR's covers it at 400 rounds with a registry in place. Measured on round 0 and round 6 respectively, but it is a race — what must not differ is that both redden within a few hundred rounds. **Number 2 reddens only this PR's test**, because 2c-2's does not exercise the *delayed* path where a replacement channel can exist.

- [ ] **Step 5: Run the four checks and commit**

---
## Task 4: (deleted — 2c-2 fixed the transport leak itself)

`ProxySource.Run` now does `defer client.CloseIdleConnections()` on the `*http.Client` it builds (`relay/channel/source_proxy.go` at `87dca88d`). **No edit here.** Two things survive from what this task used to be:

- **`TestConcurrentAttachAndReleaseLeaksNoGoroutine` still lands**, in Task 3's `fanout_test.go`. A fix whose absence no test reddens is a fix nobody can keep, and 2c-2's own fix commit carries no goroutine-count test.
- **Task 0 Step 2 verifies the `defer` is there.** If it is not, the tree is older than `87dca88d` and everything below is being applied to the wrong base.

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

- [ ] **Step 4: Detach the next-source call from the calling client**

  Ruling R11. `startProxyTune`'s first parameter is renamed `parent`, and its first two statements become:

  ```go
  	ctx, cancel := context.WithTimeout(context.WithoutCancel(parent), tuneBudget)
  	defer cancel()
  ```

  with `tuneBudget` declared beside `OutputFormatMPEGTS` and the doc comment R11 gives, including the two paragraphs naming Python's own behaviour and its `file:line`. **`StreamHandler` still passes `r.Context()`** — the detaching happens one level down, where the reason for it lives.

- [ ] **Step 5: Thread the client through the tune path**

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

- [ ] **Step 6: Break-check, four edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 0 | `context.WithoutCancel(parent)` becomes `parent` | `TestTheTuningClientLeavingDoesNotFailTheTuneForEveryoneElse` (Task 8), **on the request count** | `the relay made 2 next-source calls, want 1 -- the gate did not hold the second client while the first was calling` |
  | 1 | the `if tuning.JoinBehind > 0 { cursor = ring.Join(...) }` branch becomes `_ = tuning.JoinBehind` | `TestASecondClientJoinsBehindLiveAndNotAtTheHead` (Task 8) | `the second client started at packet 8400 with the live head at packet 8400: it joined AT live, not behind it -- new_client_behind_seconds was ignored` |
  | 2 | `_ = trusted`, then `header` returns `r.Header.Get(name)` unconditionally | `TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader` (Task 8), and 2c-2's `TestXRelayChannelIsIgnoredWithoutTheTrustMarker` | `the tune asked about /api/relay/channels/somebody-elses-channel/next-source: an unverified X-Relay-Channel was believed` |
  | 3 | `tuningFrom` falls back to a literal for `channel_shutdown_delay` | 2c-2's `TestEveryProxySettingThisRelayReadsIsRequired/channel_shutdown_delay` **only**, once its key list grows by one | `an answer missing only "channel_shutdown_delay" tuned with 200, want 502 -- the relay substituted a default of its own` |

  **Numbers 1 and 2 need the keep-alive line.** Deleting the branch outright leaves `tuning` unused and deleting the guard leaves `trusted` unused, and in both cases the package fails to COMPILE — which tells you nothing about the test. Both were first written without it, and neither reddened until the variable was kept live.

  **Number 3 carries 2c-2's own caveat**: running it against a fixture missing several keys at once leaves the test green, because any one of them still fails the tune. The per-key subtest is the one with the property.

- [ ] **Step 7: Run the four checks and commit**

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
  logo_id        NEVER EMITTED BY PYTHON EITHER, but not for the reason an
                 earlier draft of this plan gave. LOGO_ID is declared
                 (constants.py:59) and read (channel_status.py:486) and IS
                 written -- at apps/timeshift/views.py:2984, into
                 timeshift:channel:<id>:metadata, a DIFFERENT KEY FAMILY from
                 the live:channel:<uuid>:metadata hash channel_status.py reads.
                 Nothing writes it into the live family, so the
                 `if not raw: continue` always continues on this endpoint.
                 Exact parity by doing nothing; "written nowhere in the tree"
                 was wrong and the conclusion survives it.
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

  **The complete file is Appendix J**, and its module docstring carries the caveat that makes it honest:

  > It pins the SERIALIZER — which keys survive, which render as null, which vanish. It does NOT drive `ChannelStatus.get_basic_channel_info`, so the mapping from "the source dict set this key inside an `if`" to "this key is optional" is 2c-3's reading of `channel_status.py:469-587`, not a measurement of Python's execution.

  Driving the real builder would need a Redis with a channel in it — a much heavier fixture for one more link in the chain — and the completeness assertion below is what stops the reading from silently narrowing instead. **Say this in the PR description too**: a golden that looks like a measurement and is a transcription is worse than one that says which it is.

  1. Builds a `payload` dict by hand, exercising every present/absent/null case: two channels, one with every conditional field set and two clients (one fully populated, one with nothing optional), one minimal with no conditional fields and no clients.
  2. Renders it through `RelayChannelListSerializer` and DRF's `JSONRenderer`, and asserts the result equals the committed `relay/httpapi/testdata/channels_clients_all.json` — **compared as parsed JSON, not as bytes**, for the reason Step 3 states.
  3. Asserts the fixture's **completeness**: every field `RelayChannelSerializer` declares is either present on the fully-populated channel, or named in an explicit `NOT_SERVED_BY_2C3` set with a one-line reason. A hand-written fixture that quietly omitted a field would otherwise pin a payload narrower than the contract.

  ```python
  # Every RelayChannelSerializer field 2c-3 does not produce, and why. A field
  # in neither this set nor the fixture fails the completeness test, which is
  # what stops the golden from silently narrowing as the endpoint grows.
  NOT_SERVED_BY_2C3 = {
      "logo_id": (
          "ChannelMetadataField.LOGO_ID is written only into the TIMESHIFT key "
          "family (apps/timeshift/views.py:2984, timeshift:channel:<id>:metadata), "
          "never into the live:channel:<uuid>:metadata hash channel_status.py:486 "
          "reads, so the live list endpoint never emits it in Python either"
      ),
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

- [ ] **Step 1: EXTEND 2c-2's rig; do not build a second one**

  `httpapi/stream_test.go` already defines `testSecret`, `rigChunkBytes` (`188 * 700` — **already a non-default value**, so the note an earlier draft of this plan carried about 2c-2 "shipping the rig with 255868" is stale and must not be repeated), `rigBudgetBytes`, the `rig` struct, `newRig(t, relaytest.ControlPlaneConfig, relaytest.Config)` and `rig.tune(t, path, http.Header)`. **One package gets one rig.** Redeclaring any of them fails `go vet` before a single test runs.

  **One edit to `newRig`**, and it is the one that matters:

  ```go
  		// THE SAME manager, not a second one. Two would give the list endpoint
  		// an empty map while the tune path filled another, and every assertion
  		// about what the list shows would be about the wrong object.
  		Control: ControlDeps{Secret: testSecret, Channels: manager},
  ```

  Everything else this PR needs goes in `fanout_test.go` under names that do not collide (**the complete file is Appendix I**):

  | New symbol | What it is |
  |---|---|
  | `rigAssetPackets = 65536` | Ruling R6's long asset, with the wrap explained in its own comment |
  | `rigSettings(overrides)` | the full effective settings with the rig's chunk size, plus per-test overrides |
  | `fanRig(t, up, overrides)` | `newRig` with the long asset and those settings |
  | `(*rig).tuneAs(t, channelID, clientID)` | the trusted-path shorthand, **built on** `rig.tune` rather than replacing it — `tune` stays the right primitive for the untrusted and malformed cases |
  | `(*rig).listChannels(t, query)` | the internal call, signing the **full path including the query string** |
  | `fanRigWith(t, cp, up, overrides)` | `fanRig` with control over the fake Django too, for the test that needs it slow |
  | `waitForHead(t, r, id, n)` | polls the ring rather than sleeping |
  | `packetRun(t, who, body, n)` | the shared oracle |

  **One field is added to `relaytest.ControlPlaneConfig`: `Delay time.Duration`**, which holds every answer for that long before writing it. R11's test needs a next-source call still in flight when a client disconnects, and there is no other way to arrange that; it is four lines in `internal/relaytest/controlplane.go` and zero is the ordinary immediate answer.

  `packetRun` reads N whole packets, checks alignment, and checks that **every packet follows the one before it** by the index the fixture embedded, returning the first. A helper that checked only alignment would pass on a stream with gaps.

- [ ] **Step 2: Write the six tests**

  | Test | What it pins |
  |---|---|
  | `TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint` | **the fan-out**: six concurrent clients, **one** provider request, six unbroken runs, join points inside one ring |
  | `TestASecondClientJoinsBehindLiveAndNotAtTheHead` | **row 8**, at the case the row is about |
  | `TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked` | **D4** — the cap, `?clients=all` lifting it, and `client_count` never capped |
  | `TestTheListEndpointRefusesAnUnsignedOrMissignedCall` | the internal gate, four ways |
  | `TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader` | the trust marker gates **every** `X-Relay-*` value, not just the channel |
  | `TestAnOutputThisRelayDoesNotServeIsRefused` | **R10** — 501 for an fMP4 format and for an Output Profile, with **zero** control-plane and provider calls |
  | `TestADuplicateClientIDIsRefusedAtTheTuneSurface` | **row 13's first half at the HTTP layer** — 503, and the first client keeps its registration |
  | `TestTheTuningClientLeavingDoesNotFailTheTuneForEveryoneElse` | **R11** — the first client drops mid-next-source and the second still gets bytes, off **one** control-plane call |
  | `TestTheTwoPortedConstantsMatchTheirPythonLiterals` | the two constants Global Constraint 8 names, against their Python literals |
  | `TestTheLiveEndpointProducesTheGoldensKeySet` (Task 7) | the handler builds the shape |

  **`TestTheTwoPortedConstantsMatchTheirPythonLiterals` is a VALUE test and both halves are needed.** Neither constant was pinned by anything in this plan's first draft, and both survived a break-check: `DefaultClientLimit` 10 → 13 left the cap test green, and `MaxChunksPerRead` 20 → 40 left the buffer cap test green. Both for the same reason — **their expected value IS the constant**, which is the tautological oracle in its purest form. Only a literal written down from the Python side can fail:

  ```go
  	if DefaultClientLimit != 10 {
  		t.Errorf("DefaultClientLimit is %d, want 10 -- apps/proxy/relay_views.py:57's "+
  			"DEFAULT_CLIENT_LIMIT, what the Stats page and /proxy/stats/ have always shown",
  			DefaultClientLimit)
  	}
  	if buffer.MaxChunksPerRead != 20 {
  		t.Errorf("buffer.MaxChunksPerRead is %d, want 20 -- "+
  			"apps/proxy/live_proxy/input/buffer.py:329's MAX_CHUNKS, the bound on how much "+
  			"a lagging reader holds at one instant", buffer.MaxChunksPerRead)
  	}
  ```

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
  **There is deliberately no break-check for the provider's request count**, and saying why is more useful than inventing one. "One upstream per channel" is not guarded by a line that can be removed: `start()` only asks the control plane, and the provider connection is opened by `publish`'s `go c.run(...)`, so making `Attach` call `start()` eagerly changes nothing a provider can see. The nearest real edit — deleting `claim`'s reuse branch so every caller claims a fresh gate — **hangs rather than fails**: measured, the test ran out its 90-second budget with goroutines parked in `netFD.Read`. The property is structural. The assertion earns its place anyway, as a regression net for 2c-5, whose failover re-tunes through this same manager; the gate itself is guarded by 2c-2's `TestConcurrentFirstClientsStartExactlyOneSource`.

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

  > The Go pin covers the idempotence half only. Row 13's second half has **two** mechanisms and neither has a Go analogue: the heartbeat thread's own staleness check against `last_active` (`client_manager.py:100-126`) and the `remove_ghost_clients` SET sweep (`:434-469`). Spec D2 puts the registry in process memory, where a client entry cannot outlive the goroutine that made it, so the TTL and the heartbeat both mechanisms backstop are deleted rather than ported (2c-3). Note that `refresh_client_ttl` (`:429-444`) has **no production callers** — only tests reach it — so "deleted" overstates its surface: what goes is a method the running system already did not use, alongside two that it did.

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

  **Say in the PR description that this asserts a SUPERSET, not the roster.** The loop checks that each named program is RUNNING; it does not check that nothing else is. A program added to `all.conf` and not added here still passes. Closing that would mean parsing `[include] files =` from the test, which is a different and larger change than this one.

  **`relay-go` is the reason this matters now rather than as tidying.** 2c-1's own fix round found, through this very script, that `relay-go` could not read `/data/jwt` once it dropped privilege under a non-root PUID/PGID — and the script did not assert `relay-go` was running, so it caught that by a different route. The assertion is what makes the next such failure fail here rather than in production.

- [ ] **Step 3: Close the second stale rung — the `relay` role**

  `docker/tests/test-puid-pgid.sh:1318` asserts only `relay-uwsgi` for the relay container:

  ```bash
      if echo "$relay_ctl" | grep -q "relay-uwsgi.*RUNNING" && ! echo "$relay_ctl" | grep -qE "FATAL|BACKOFF"; then
  ```

  `docker/supervisord/relay.conf`'s glob is `relay-*.conf`, which has picked up `relay-go.conf` since 2c-1 — so the relay role runs two programs and the test checks one. Add the second condition and update the `log_pass` text.

  **And fix that file's own comment while you are there.** `relay.conf` still says *"relay-uwsgi.conf (Phase 1 PR 4) is the only program this glob picks up"*, which stopped being true when 2c-1 added `relay-go.conf` to the same directory. A glob whose comment names its one member is how a second member arrives unnoticed.

- [ ] **Step 4: Note what is NOT changed**

  The other `RUNNING` checks in the file — the startup wait at `:193` and the fallback at `:313` — poll `api-uwsgi` specifically and are correct as they are: they are waiting for the container to be up, not asserting the roster.

- [ ] **Step 5: Commit**

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
  `MAX_SIZE`; not true of `MAX_CHUNKS` (`input/buffer.py:329`), which bounds
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

  **A3.5a — two more stated divergences, both where Python loses
  information.** `get_optimized_client_data` returns `client_index +
  chunk_count` (`input/buffer.py:373`) — the count it ASKED for, not the count
  it got — so a short read there skips undelivered chunks; Go returns the index
  of the last chunk actually handed over. And `skipped` has no Python
  counterpart as a returned value at all: `output/ts/generator.py:354-358`
  computes the same number only inside a log string and no caller sees it.
  Both are additions in the safe direction, recorded rather than presented as
  parity.

  **A3.6 — the tune's control-plane call is detached from the calling
  client.** `Manager.Attach` runs `start()` behind a per-channel gate, so with
  the first client's `r.Context()` that client disconnecting cancels
  next-source for every client waiting behind it. Python detaches by
  construction -- it calls next_source from inside the client's own request
  greenlet (`views.py:340`, `:390`) and uWSGI does not cancel a greenlet when
  its client hangs up -- so a Go relay that propagated cancellation would be
  strictly less available than the one it replaces. 2c-3 uses
  `context.WithTimeout(context.WithoutCancel(parent), tuneBudget)`, where the
  budget is `control.Client`'s own two-attempt worst case. **Measured cost of
  getting it wrong**: not a failed tune for the waiter, which recovers by
  re-claiming the gate, but a wasted control-plane round trip per departing
  tuner plus a failure whenever that retry also fails.

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
| 2 | 1 | `next = c.Index` moves out of the loop and becomes the ring's tail | **2c-2's** `TestNextIsTheLastChunkActuallyReturnedNotTheRingsTail` | ✓ |
| 3 | 1 | one backing array reused for every chunk (**a field, not a local**) | `TestAChunkIsUnchangedAfterEveryClientHasServedIt` | — (2c-2 verified the same shape) |
| 4 | 1 | drop the `RLock` from `TotalBytes` | `TestManyConcurrentReadersAndOneWriter`, as `WARNING: DATA RACE` | — |
| 5 | 2 | `addClient` overwrites instead of refusing | `TestASecondAttachUnderAnAttachedClientIDIsRefused` | ✓ |
| 6 | 2 | `ClientSnapshot` returns map-range order | **expected not to redden**; report the gap | — |
| 7 | 3 | `stopIfStillIdle` re-reads `Clients()` outside `m.mu` (2c-2's pre-fix shape) | `TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel` **and** 2c-2's `TestAReleaseCannotStop…`, rounds 0 and 6 | ✓ |
| 8 | 3 | `stopIfStillIdle` checks presence, not identity | `TestADelayedStopNeverEvictsAReplacementChannel` **only** | ✓ |
| 9 | 3 | the shutdown delay is ignored | `TestTheShutdownDelayKeepsAChannelForAReconnectingClient` | ✓ |
| 10 | 3 | remove `defer client.CloseIdleConnections()` from `ProxySource.Run` (2c-2's fix) | `TestConcurrentAttachAndReleaseLeaksNoGoroutine`, 3 → ~94 goroutines | ✓ (measured against this plan's own equivalent fix) |
| 11 | 5 | `_ = tuning.JoinBehind`, replacing `serveClient`'s `ring.Join` branch | `TestASecondClientJoinsBehindLiveAndNotAtTheHead` | ✓ (see 16) |
| 12 | 5 | `_ = trusted`, then `identify`'s `header` closure ignores it | `TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader` | ✓ |
| 13 | 5 | one setting falls back to a literal | 2c-2's `TestEveryProxySettingThisRelayReadsIsRequired/<key>` **only** | — (2c-2 verified the shape) |
| 14 | 6 | the client limit is ignored | `TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked` | ✓ |
| 15 | 6 | `RequireInternal` skips the bound token | `TestTheListEndpointRefusesAnUnsignedOrMissignedCall`, **3 of 4** subtests | ✓ |
| 16 | 6 | `describeChannel` names a process identity in `owner` | `TestTheLiveEndpointProducesTheGoldensKeySet` **only** | ✓ (did not redden until R9's line went in) |
| 17 | 7 | `json:"url"` gains `,omitempty` | both golden tests | ✓ |
| 18 | 7 | `OutputProfileID` loses its pointer | `TestEveryOptionalFieldIsAbsentRatherThanNull` | — |
| 19 | 8 | `DefaultClientLimit` 10 → 13 | `TestTheTwoPortedConstantsMatchTheirPythonLiterals` **only** — the cap test stays green | ✓ |
| 20 | 8 | `buffer.MaxChunksPerRead` 20 → 40 | the same test **only** — the buffer cap test stays green | ✓ |
| 21 | 1 | `MaxChunksPerRead`'s const placed between `ErrClosed`'s doc comment and its `var` | `golangci-lint`, two `revive` findings | ✓ |
| 22 | 5 | `context.WithoutCancel(parent)` becomes `parent` | `TestTheTuningClientLeavingDoesNotFailTheTuneForEveryoneElse`, **on the request count only** | ✓ |

**Three rows guard a property with no injectable defect at all, and none of them has an entry above:** the provider's request count (Task 8 Step 3 explains why an eager `start()` changes nothing and the nearest real edit hangs), `ClientSnapshot`'s ordering (row 6), and the borrowed-slice contract against a *consumer* that mutates (Ruling R3). Each is stated rather than given a check that would pass either way.

**Four rows deserve a second look before you trust them, and three of the four come from a break-check that did not redden.**

- **6** is listed *because* it is expected to stay green, and its stated reason had to be corrected: not "one client per channel" (the golden's first channel has two) but **neither golden test runs the handler**. Ordering is not a parity property — `channel_status.py:533` reads a Redis SET — so determinism here is a testing convenience.
- **11** did not redden in this plan's first draft, because the test compared a **wrapped** `PacketIndex` against an unwrapped chunk count. Ruling R6 has the diagnosis; `rigAssetPackets = 65536` is the fix. If it stays green on your tree, check that constant first.
- **16** did not redden at all until one line was added to the live key-set test. The two golden tests compare a struct literal against a file; **neither runs the handler**. This is the plan's clearest instance of two tests that look like they cover a third thing and do not.
- **7** is a race and its round numbers will differ. 2c-2's own reviewer measured this defect at **12% of 3,000 rounds** in the shipped code, plus a deterministic successor-teardown variant; 2c-2's fix commit closed both, and this row is what keeps them closed.
- **22** reddens on the request count and **not** on the status or the bytes: the waiter recovers by re-claiming the gate and making its own call. That is the true cost of the attached context — a wasted round trip per departing tuner — and the test says so, because a check that reddened on the wrong assertion would teach the next reader the wrong mechanism.
- **19, 20 and 21** exist because a first draft of this plan had none of them: neither constant Global Constraint 8 names was pinned by anything, and the placement of one const comment cost two `revive` findings. Three checks, each catching something that had been invisible.

**A break-check that stays green is the most useful result this table produces.** Five of this plan's own did: rows 6 and 16, both constants before rows 19 and 20 existed, and the provider-count check that was dropped. Every one of the five changed the plan.

---

## What to report back

1. **Task 0's diff** — every row of the 2c-2 ledger that did not match the merged tree, and which task absorbed it. In particular, the three fix-round rows: did `Manager.release` already take one lock with an identity check, did `ProxySource.transport` already return a closer, and did `Read` already return the last index appended? Plus: did `EffectiveProxySettings()` already carry `channel_shutdown_delay`?
1a. **The collision reconciliation** — the measured call-site count, and that all of them were rewritten, that none of the five shared fixtures was redeclared, and that **2c-2's own channel and httpapi tests still pass unchanged**. A regression in one of those is a finding about this PR, not about 2c-2.
2. **Every break-check's actual failure message**, and specifically: did **6**, **11** and **16** behave as this plan predicts?
3. **The three concurrency pins** — `TestAClientArrivingAsTheLastOneLeavesKeepsItsChannel`, `TestADelayedStopNeverEvictsAReplacementChannel` and `TestConcurrentAttachAndReleaseLeaksNoGoroutine` — green, and their break-checks red on the named test only. For the first, **the round number it reddened on**.
3a. **R11's break-check** — which assertion reddened. If the status or the bytes failed rather than the request count, the gate is behaving differently from what this plan measured and that is a finding.
4. **The goroutine numbers** — `before` and `after` from `TestConcurrentAttachAndReleaseLeaksNoGoroutine`, on a clean tree and with break-check 10 applied. If `after` on a clean tree is anywhere near `before + 20`, say so: the tolerance may be hiding a smaller leak.
5. **The golden file** — whether your regeneration from Django matched the committed one, and if not, every field that differed. This is the single most likely place this plan is wrong, because it encodes a reading of `RelayChannelSerializer` rather than a measurement.
6. **The Redis key-family walk** — the family this PR closes, the one it closes partially, and `client_stop`, which it does not.
7. **The lint ledger** — zero new `#nosec`, and anything the linter found that this plan does not name. The one placement finding this plan predicts (break-check 21) should not appear at all if Task 1 Step 1 is followed.
8. **The hand-run evidence** — `/healthz`, and a failed tune's body confirmed to name no URL and no variable value.
9. **The stated divergences**, as a list, because they are the part a reviewer cannot infer from a green suite. Task 12 Step 6 has them.
10. **Anything in the spec, `CLAUDE.md`, the 2c-2 plan or this plan you found wrong or stale.** The two most likely places: the 2c-2 ledger rows, and this plan's reading of `get_basic_channel_info`'s presence rules.

---

## Appendix — the files, in full

Every file below was written, built, vetted, run under `go test -race` three times and linted at **0 issues** in a scratch module seeded from **`migration/phase2c-vertical-slice` at `87dca88d`, including every `_test.go`**. 2c-2's own tests — all of them, its three fix commits' included — pass unchanged alongside these.

**Two literals in here are oracles and must be regenerated rather than trusted:** the golden JSON fixture (Task 7 Step 2 has the command), and — carried from 2c-2 — the synthetic asset's SHA-256.

**Appendix E is the one to read first if you change `Manager.Attach` or `Manager.release`.** Three of its six tests guard orderings rather than values, and every defect they guard against is invisible to `-race`.

**Appendices D, F and I are deltas on files 2c-2 owns.** D preserves `stopIfStillIdle` untouched; F changes `startProxyTune`'s context and nothing else about the control call; I declares no rig, extending `httpapi/stream_test.go`'s.

### Appendix A — `relay/buffer/fanout_test.go`

**No `next` assertion.** The cap ARMS 2c-2's `TestNextIsTheLastChunkActuallyReturnedNotTheRingsTail`, which `87dca88d` ships labelled un-armed with 2c-3 named as its owner; arming it is the job, not writing a second one.

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
	if skipped != 0 {
		t.Fatalf("skipped = %d with nothing evicted", skipped)
	}
	// next's contract -- the index of the last chunk actually returned, never
	// the ring's tail -- is 2c-2's and is asserted by
	// TestNextIsTheLastChunkActuallyReturnedNotTheRingsTail, which starts
	// discriminating the moment this cap exists. Not re-asserted here: one
	// mechanism per invariant.

	// The rest arrives on the following calls, in order and with no gap.
	rest, _, _ := r.Read(next)
	if len(rest) != 40-MaxChunksPerRead {
		t.Fatalf("the second Read returned %d chunks, want %d", len(rest), 40-MaxChunksPerRead)
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

The whole file. The diff against `87dca88d` is the registry, `ErrDuplicateClient`, `SourceInfo`, `startedAt` and `ClientSnapshot`. **`promoteOnFirstChunk` is 2c-2's and is untouched** — it is the only thing that sets `StateActive`.

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
		// The error is logged as-is. Every error this package builds is
		// written to carry no URL, because a provider URL carries provider
		// credentials (CLAUDE.md, § Known defects).
		c.log.Error("upstream failed", "channel", c.id, "error", err)
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

### Appendix D — `relay/channel/manager.go`

The whole file. **`stopIfStillIdle` is 2c-2's, verbatim** — read it before changing `release`. `Attach`'s reuse path calls nothing on the existing channel, which is `87dca88d`'s shape.

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
// the channel runs on, and what the control plane said about the stream.
//
// A struct rather than a fourth return value: (Source, Tuning, SourceInfo,
// error) is where a signature stops being readable, and 2c-4's ffmpeg source
// adds a fifth.
type Started struct {
	Source Source
	Tuning Tuning
	Info   SourceInfo
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

### Appendix E — `relay/channel/fanout_test.go`

**Declares only `startCounting`.** `sourceCounter`, `countingSource`, `waitForStart`, `testTuning` and `testClient` are 2c-2's and Task 3 Step 2's.

```go
package channel

import (
	"errors"
	"runtime"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// startCounting is the start function the tests below hand to Attach: 2c-3's
// Started shape around concurrent_test.go's countingSource.
//
// sourceCounter, countingSource, waitForStart, testTuning and testClient are
// NOT redeclared here -- they are concurrent_test.go's and manager_test.go's,
// and one package gets one of each.
func startCounting(c *sourceCounter, tuning Tuning) func() (Started, error) {
	return func() (Started, error) {
		return Started{Source: countingSource{c: c}, Tuning: tuning}, nil
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

	if started := waitForStart(t, counter, 0); started != 1 {
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
	waitForStart(t, counter, 0)
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
	settingChunkBytes    = "BUFFER_CHUNK_SIZE"
	settingRetention     = "redis_chunk_ttl"
	settingJoinBehind    = "new_client_behind_seconds"
	settingReadSize      = "CHUNK_SIZE"
	settingShutdownDelay = "channel_shutdown_delay"
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
// it replaces.
//
// context.WithoutCancel keeps any values on the request context while dropping
// its cancellation, and the timeout puts back a bound of the right shape: the
// control client's own worst case rather than the viewer's patience.
func startProxyTune(parent context.Context, client *control.Client, id string) (channel.Started, error) {
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

	// KIND, NEVER TRANSCODE. `transcode` is false for Proxy AND for Redirect
	// (apps/proxy/next_source.py:504), and both locked profiles carry an empty
	// command, so a relay that branched on `transcode` would treat a Redirect
	// channel as Proxy and stream a provider URL that should have been a 302 --
	// silently, and to the wrong architecture. `kind` is the field 2c-1 Task 0
	// added for exactly this, and this is its first consumer.
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
// text to the client: a control-plane message can name a variable, and a
// source URL carries provider credentials.
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
		log.Error("the tune failed", "channel", id, "error", err)
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
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)
	response := r.tuneAs(t, "c-keys", "client-a")
	defer func() { _ = response.Body.Close() }()

	// The channel must have published at least one chunk, so total_bytes and
	// the two bitrate fields are present -- they are exactly the conditional
	// fields the golden's populated channel carries.
	waitForHead(t, r, "c-keys", 1)

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

**Extends 2c-2's rig; declares no `rig`, `newRig`, `tune`, `testSecret`, `rigChunkBytes` or `rigBudgetBytes`.**

```go
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// rigAssetPackets is how many packets the fan-out tests' upstream loops.
//
// LONG ENOUGH THAT PacketIndex NEVER WRAPS inside a test, and that is what
// makes the join-point assertion able to fail at all. The embedded index is the
// packet's position in the ASSET, so a looping upstream restarts it at zero; an
// earlier 4,096-packet asset (3.1 seconds at the nominal rate) made "how far
// behind live did this client start" compare a wrapped index against an
// unwrapped chunk count, which is large and positive whatever the relay does.
// The break-check that removed the join call entirely left the test GREEN,
// which is how this was found.
//
// 65,536 packets is 12.3 MB, 49 seconds at the nominal rate -- longer than any
// test here runs. Do not shrink it for speed.
const rigAssetPackets = 65536

// rigSettings is the full effective settings object with the rig's non-default
// chunk size, plus whatever a test overrides.
//
// Built from relaytest.EffectiveProxySettings() rather than from a literal, so
// a key a later PR starts reading appears here automatically instead of
// failing one test with an ErrSettingAbsent nobody expected.
func rigSettings(overrides map[string]any) map[string]any {
	s := relaytest.EffectiveProxySettings()
	s["BUFFER_CHUNK_SIZE"] = rigChunkBytes
	for k, v := range overrides {
		s[k] = v
	}
	return s
}

// fanRig is newRig with the long asset and the rig's settings, which is what
// every test in this file wants.
func fanRig(t *testing.T, up relaytest.Config, overrides map[string]any) *rig {
	t.Helper()
	return fanRigWith(t, relaytest.ControlPlaneConfig{}, up, overrides)
}

// fanRigWith is fanRig with control over the fake Django as well, for the
// tests that need it slow.
func fanRigWith(t *testing.T, cp relaytest.ControlPlaneConfig, up relaytest.Config, overrides map[string]any) *rig {
	t.Helper()
	if up.Payload == nil {
		up.Payload = relaytest.SyntheticTS(rigAssetPackets, 0x100)
	}
	cp.Settings = rigSettings(overrides)
	return newRig(t, cp, up)
}

// tuneAs opens a stream for channelID as clientID, over the trusted path.
//
// Built on 2c-2's rig.tune rather than replacing it: that one takes a path and
// a header set and is the right primitive for the untrusted and malformed
// cases, and this is the shorthand for the common one.
func (r *rig) tuneAs(t *testing.T, channelID, clientID string) *http.Response {
	t.Helper()
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", channelID)
	header.Set("X-Relay-Client", clientID)
	header.Set("X-Relay-Client-IP", "198.51.100.4")
	header.Set("X-Relay-User", "7")
	response := r.tune(t, "/proxy/ts/stream/"+channelID, header)
	if response.StatusCode != http.StatusOK {
		_ = response.Body.Close()
		t.Fatalf("tune for %s answered %d, want 200", clientID, response.StatusCode)
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
	request.Header.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
	request.Header.Set(control.HeaderInternalRequest,
		control.InternalRequestHeader(testSecret, http.MethodGet, path, nil, time.Now().Unix()))
	response, err := r.Relay.Client().Do(request)
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

// waitForHead blocks until the channel's ring has published at least n chunks.
func waitForHead(t *testing.T, r *rig, id string, n uint64) uint64 {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for {
		if ch := r.Manager.Get(id); ch != nil {
			if head := ch.Ring().Head(); head >= n {
				return head
			}
		}
		if time.Now().After(deadline) {
			t.Fatalf("channel %s never published %d chunks within fifteen seconds", id, n)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

// packetRun reads n whole packets and reports the index of the first, after
// checking that every packet follows the one before it.
//
// The oracle is relaytest.PacketIndex, an index the fixture embeds and no code
// under test reads or produces. A helper that checked only alignment would pass
// on a stream with gaps.
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
// packets from wherever it joined.
//
// Every client tunes FIRST, synchronously, so all six are attached before any
// reads. Tuning inside the goroutines would let one client attach after another
// had already released, which is a different property.
func TestEveryClientGetsAnUnbrokenRunFromItsOwnJoinPoint(t *testing.T) {
	const clients = 6
	const packets = 900

	r := fanRig(t, relaytest.Config{Rate: 6}, nil)

	bodies := make([]io.ReadCloser, clients)
	for i := range clients {
		response := r.tuneAs(t, "c-fanout", fmt.Sprintf("client-%d", i))
		defer func() { _ = response.Body.Close() }()
		bodies[i] = response.Body
	}

	var wg sync.WaitGroup
	firsts := make([]int, clients)
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
	// Deliberately loose about WHERE each joined: a tighter bound would pin the
	// scheduler. What is strict is the provider's request count above and each
	// run being unbroken, which packetRun checks packet by packet.
	lowest, highest := firsts[0], firsts[0]
	for _, f := range firsts {
		lowest = min(lowest, f)
		highest = max(highest, f)
	}
	if span, maxSpan := highest-lowest, rigBudgetBytes/buffer.TSPacketSize; span > maxSpan {
		t.Fatalf("the clients' join points span %d packets, more than the %d-packet ring: "+
			"they are not reading one writer's stream", span, maxSpan)
	}
}

// Parity-matrix row 8, at the case the row is actually about: a client joining
// a channel ALREADY RUNNING for somebody else starts roughly
// new_client_behind_seconds behind live, not at the newest chunk.
//
// new_client_behind_seconds is sent as 3, not the default 5, so a relay
// ignoring the wire value is visible (hollow shape 2).
func TestASecondClientJoinsBehindLiveAndNotAtTheHead(t *testing.T) {
	const behindSeconds = 3
	// 1.0x nominal is 250,000 byte/s, so three seconds is 750,000 bytes --
	// about 5.7 chunks at rigChunkBytes, comfortably more than one and
	// comfortably less than the sixty-four-chunk ring.
	r := fanRig(t, relaytest.Config{Rate: 1},
		map[string]any{"new_client_behind_seconds": behindSeconds})

	first := r.tuneAs(t, "c-join", "client-a")
	defer func() { _ = first.Body.Close() }()
	packetRun(t, "the first client", first.Body, 200)

	head := waitForHead(t, r, "c-join", 12)

	second := r.tuneAs(t, "c-join", "client-b")
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
	// Three seconds at the nominal rate is 750,000 bytes, 3,989 packets. A
	// generous window either side, because the claim is "behind by about the
	// configured window", not a stopwatch: the ring's 700-packet chunk
	// granularity and the scheduler both move the true figure. What is strict
	// is the check above -- a client that joined AT live fails outright.
	const wantPackets = behindSeconds * relaytest.NominalByteRate / buffer.TSPacketSize
	if behindPackets < wantPackets/4 || behindPackets > wantPackets*4 {
		t.Fatalf("the second client started %d packets behind live, want roughly %d "+
			"(%ds at the nominal rate) -- the join point is not the configured window",
			behindPackets, wantPackets, behindSeconds)
	}
}

// The list endpoint: every attached client, with ?clients=all lifting the
// ten-client cap that relay_client.live_connections would otherwise under-count
// behind (spec D4).
func TestTheClientListIsCappedAtTenUnlessClientsAllIsAsked(t *testing.T) {
	const clients = 13
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)

	for i := range clients {
		response := r.tuneAs(t, "c-list", fmt.Sprintf("client-%02d", i))
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

// An unsigned or missigned call is refused, and the refusal names nothing. The
// bound token signs the FULL path, so a token minted for the bare path does not
// authorise ?clients=all -- which is the exact route spec D4's whole argument
// rests on, and the correction the spec's section The contract records.
func TestTheListEndpointRefusesAnUnsignedOrMissignedCall(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)
	response := r.tuneAs(t, "c-auth", "client-a")
	defer func() { _ = response.Body.Close() }()

	for _, tc := range []struct {
		name   string
		path   string
		header func(http.Header)
	}{
		{"no headers at all", "/proxy/relay/channels", func(http.Header) {}},
		{"the principal header only", "/proxy/relay/channels", func(h http.Header) {
			h.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
		}},
		{"a token signed for the bare path, sent with a query string", "/proxy/relay/channels?clients=all", func(h http.Header) {
			h.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
			h.Set(control.HeaderInternalRequest, control.InternalRequestHeader(
				testSecret, http.MethodGet, "/proxy/relay/channels", nil, time.Now().Unix()))
		}},
		{"a token signed with the wrong secret", "/proxy/relay/channels", func(h http.Header) {
			h.Set(control.HeaderInternal, control.InternalPrincipalToken(testSecret))
			h.Set(control.HeaderInternalRequest, control.InternalRequestHeader(
				"not-the-deployment-secret", http.MethodGet, "/proxy/relay/channels", nil, time.Now().Unix()))
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+tc.path, nil)
			if err != nil {
				t.Fatalf("building the request: %v", err)
			}
			tc.header(request.Header)
			answer, err := r.Relay.Client().Do(request)
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
// Read off the LIST ENDPOINT rather than off the tune, because what a believed
// header would corrupt is the registry -- the client id an admin stops by, the
// address row 17 pins, and the user id the stream limit counts.
func TestAnUntrustedRequestIsNotBelievedForAnyRelayHeader(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)

	// Every X-Relay-* value a trusted request carries, and NO trust marker.
	header := http.Header{}
	header.Set("X-Relay-Channel", "somebody-elses-channel")
	header.Set("X-Relay-Client", "an-id-i-chose")
	header.Set("X-Relay-Client-IP", "192.0.2.200")
	header.Set("X-Relay-User", "10")
	header.Set("User-Agent", "curl/8.0")

	response := r.tune(t, "/proxy/ts/stream/c-untrusted", header)
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

	waitForHead(t, r, "c-untrusted", 1)

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

// An output this relay does not serve is refused 501 rather than served as
// MPEG-TS under a label that is not true, and the refusal happens BEFORE the
// control plane is asked.
func TestAnOutputThisRelayDoesNotServeIsRefused(t *testing.T) {
	for _, tc := range []struct {
		name   string
		header string
		value  string
	}{
		{"an output format it does not serve", "X-Relay-Output-Format", "fmp4"},
		{"an Output Profile", "X-Relay-Output", "7"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := fanRig(t, relaytest.Config{Rate: 4}, nil)
			header := http.Header{}
			header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
			header.Set("X-Relay-Channel", "c-output")
			header.Set(tc.header, tc.value)

			response := r.tune(t, "/proxy/ts/stream/c-output", header)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != http.StatusNotImplemented {
				t.Fatalf("a tune asking for %s=%s answered %d, want 501",
					tc.header, tc.value, response.StatusCode)
			}
			if got := len(r.Control.Requests()); got != 0 {
				t.Fatalf("the relay made %d control-plane calls for a tune it cannot serve, "+
					"want 0 -- the refusal must happen before anything is reserved", got)
			}
			if got := r.Upstream.Requests(); got != 0 {
				t.Fatalf("the provider saw %d requests for a tune the relay refused", got)
			}
		})
	}
}

// A second tune under a client id already attached to the channel is refused
// 503, not silently allowed to overwrite the first. Parity-matrix row 13's
// first half, at the HTTP layer: client_manager.py:218-221 returns False and
// views.py:748-753 turns that into this status.
func TestADuplicateClientIDIsRefusedAtTheTuneSurface(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)

	first := r.tuneAs(t, "c-dup", "the-same-id")
	defer func() { _ = first.Body.Close() }()
	waitForHead(t, r, "c-dup", 1)

	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", "c-dup")
	header.Set("X-Relay-Client", "the-same-id")
	second := r.tune(t, "/proxy/ts/stream/c-dup", header)
	defer func() { _ = second.Body.Close() }()

	if second.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("a second tune under an attached client id answered %d, want 503",
			second.StatusCode)
	}
	if got := r.Manager.Get("c-dup").Clients(); got != 1 {
		t.Fatalf("the channel holds %d clients after a refused duplicate, want 1 -- "+
			"the registry is not keyed by id", got)
	}
}

// The two constants Global Constraint 8 names, pinned to the Python literals
// they mirror.
//
// A VALUE TEST, not a behaviour test, and both are needed. Changing
// DefaultClientLimit from 10 to 13 leaves the cap test green -- its expected
// value IS the constant, which is the tautological oracle -- and changing
// MaxChunksPerRead from 20 to 40 leaves the buffer cap test green for the same
// reason. Only a literal written down from the Python side can fail.
func TestTheTwoPortedConstantsMatchTheirPythonLiterals(t *testing.T) {
	if DefaultClientLimit != 10 {
		t.Errorf("DefaultClientLimit is %d, want 10 -- apps/proxy/relay_views.py:57's "+
			"DEFAULT_CLIENT_LIMIT, what the Stats page and /proxy/stats/ have always shown",
			DefaultClientLimit)
	}
	if buffer.MaxChunksPerRead != 20 {
		t.Errorf("buffer.MaxChunksPerRead is %d, want 20 -- "+
			"apps/proxy/live_proxy/input/buffer.py:329's MAX_CHUNKS, the bound on how much "+
			"a lagging reader holds at one instant", buffer.MaxChunksPerRead)
	}
}

// THE TUNING CLIENT MAY LEAVE AND THE TUNE MUST SURVIVE IT.
//
// Manager.Attach runs start() behind a per-channel gate: the first client in
// makes the next-source call and every later client for that channel waits on
// the gate. If that call used the first client's r.Context(), the first client
// closing its tab would cancel next-source for everyone waiting -- they wake,
// find no channel, and each retries into the same failure.
//
// Python detaches by construction: its tune calls next_source from inside the
// client's own request greenlet (views.py:340, :390) and uWSGI does not cancel
// a greenlet when its client hangs up, so the channel starts and the followers
// attach to it. This asserts the Go relay does the same.
//
// The control plane is held for 1.5s so the disconnect lands squarely inside
// the call. The second client tunes 250ms in -- while the first is still
// waiting -- so it is genuinely on the gate rather than arriving afterwards.
//
// WHICH ASSERTION DISCRIMINATES, measured rather than assumed. Against the
// attached-context version the SECOND client still gets its 200 and its bytes:
// the cancelled start returns an error, Attach's deferred releaseGate opens the
// gate, and the waiter re-claims and makes its own call, which succeeds. The
// damage is therefore a WASTED control-plane round trip per departing tuner --
// plus a failed response for the client that left, and a real failure for the
// waiter whenever that retry also fails -- and the request-count assertion at
// the end is the one that sees it. The status and bytes assertions are kept
// because a 200 with an empty body is the same failure wearing a better number,
// but they are not what fails first.
func TestTheTuningClientLeavingDoesNotFailTheTuneForEveryoneElse(t *testing.T) {
	// channel_shutdown_delay is 2s, NOT the default 0, and that is what makes
	// this test deterministic rather than a coin flip. Two independent things
	// can make the second client cause a second next-source call, and only one
	// of them is what this test is about:
	//
	//   1. the context -- the first client's cancellation aborts the call, so
	//      no channel is ever published and the waiter must tune afresh; and
	//   2. the TEARDOWN RACE -- the call completes and the channel publishes,
	//      but the first client's release runs before the waiter has re-claimed,
	//      sees zero clients, and stops the channel underneath it.
	//
	// The second is real behaviour, not a test artefact, and with the default
	// zero delay it fires often enough to redden this test at roughly one run
	// in three -- measured. A non-zero grace window closes it: the first
	// client's release schedules a stop instead of taking one, the waiter
	// re-claims inside the window, and stopIfStillIdle then sees a client and
	// no-ops. What is left varying is exactly the property under test.
	r := fanRigWith(t,
		relaytest.ControlPlaneConfig{Delay: 1500 * time.Millisecond},
		relaytest.Config{Rate: 4},
		map[string]any{"channel_shutdown_delay": 2})

	// The first client, on a context this test cancels mid-call.
	firstCtx, dropFirst := context.WithCancel(t.Context())
	firstDone := make(chan struct{})
	go func() {
		defer close(firstDone)
		request, err := http.NewRequestWithContext(firstCtx, http.MethodGet,
			r.Relay.URL+"/proxy/ts/stream/c-detach", nil)
		if err != nil {
			return
		}
		request.Header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
		request.Header.Set("X-Relay-Channel", "c-detach")
		request.Header.Set("X-Relay-Client", "client-leaving")
		response, err := r.Relay.Client().Do(request)
		if err == nil {
			_ = response.Body.Close()
		}
	}()

	// The second client joins while the first is still inside next-source, so
	// it is parked on the gate when the first goes away. It reads its own bytes
	// in its own goroutine and reports an outcome, rather than handing the
	// response back over a channel: a *http.Response that crosses a channel is
	// a body bodyclose cannot follow, and reading here is also what makes the
	// assertion "it got a working stream" rather than "it got a status".
	type outcome struct {
		status int
		err    error
	}
	second := make(chan outcome, 1)
	go func() {
		time.Sleep(250 * time.Millisecond)
		request, err := http.NewRequestWithContext(t.Context(), http.MethodGet,
			r.Relay.URL+"/proxy/ts/stream/c-detach", nil)
		if err != nil {
			second <- outcome{err: err}
			return
		}
		request.Header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
		request.Header.Set("X-Relay-Channel", "c-detach")
		request.Header.Set("X-Relay-Client", "client-staying")
		response, err := r.Relay.Client().Do(request)
		if err != nil {
			second <- outcome{err: err}
			return
		}
		defer func() { _ = response.Body.Close() }()
		if response.StatusCode != http.StatusOK {
			second <- outcome{status: response.StatusCode}
			return
		}
		// Bytes, not just a status: a 200 with an empty body would be the same
		// failure wearing a better number.
		got := make([]byte, 40*buffer.TSPacketSize)
		if _, err := io.ReadFull(response.Body, got); err != nil {
			second <- outcome{status: response.StatusCode, err: err}
			return
		}
		if problem := relaytest.AlignmentProblem(got); problem != "" {
			second <- outcome{status: response.StatusCode, err: errors.New(problem)}
			return
		}
		second <- outcome{status: response.StatusCode}
	}()

	time.Sleep(600 * time.Millisecond)
	dropFirst()
	<-firstDone

	select {
	case got := <-second:
		if got.err != nil {
			t.Fatalf("the second client's tune failed after the first left: %v -- the "+
				"next-source call was cancelled by a client that is not the only one waiting",
				got.err)
		}
		if got.status != http.StatusOK {
			t.Fatalf("the second client got %d after the first client left mid-tune, want 200 -- "+
				"startProxyTune is still bound to the first client's request context", got.status)
		}
	case <-time.After(20 * time.Second):
		t.Fatal("the second client neither started nor failed within twenty seconds")
	}

	if got := r.Control.Requests(); len(got) != 1 {
		t.Fatalf("the relay made %d next-source calls, want 1 -- the gate did not hold the "+
			"second client while the first was calling", len(got))
	}
}
```

### Appendix J — `apps/proxy/tests/test_relay_list_payload_golden.py`

**Written but NOT executed while this plan was prepared** — it needs the shared test container, which Global Constraint 10 keeps out of a planning session. Task 7 Step 1 runs it; if it does not pass on your tree, your tree governs.

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

# Every RelayChannelSerializer field 2c-3's Go relay does not produce, and why.
# A field in neither this mapping nor the fully-populated fixture channel fails
# test_the_fixture_covers_every_serializer_field, which is what stops the
# golden from silently narrowing as the endpoint grows.
NOT_SERVED_BY_2C3 = {
    "logo_id": (
        "ChannelMetadataField.LOGO_ID is written only into the TIMESHIFT key "
        "family (apps/timeshift/views.py:2984, timeshift:channel:<id>:metadata), "
        "never into the live:channel:<uuid>:metadata hash channel_status.py:486 "
        "reads, so the live list endpoint never emits it in Python either"
    ),
    "healthy": "needs StreamManager.healthy, which arrives in 2c-5",
    "video_codec": "ffmpeg-derived, 2c-4",
    "resolution": "ffmpeg-derived, 2c-4",
    "source_fps": "ffmpeg-derived, 2c-4",
    "ffmpeg_speed": "ffmpeg-derived, 2c-4",
    "audio_codec": "ffmpeg-derived, 2c-4",
    "audio_channels": "ffmpeg-derived, 2c-4",
    "stream_type": "set by channel_service from the probed input format, 2c-5",
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
        excused = set(NOT_SERVED_BY_2C3)

        missing = declared - populated - excused
        self.assertEqual(
            missing,
            set(),
            "these RelayChannelSerializer fields are neither in the fixture nor "
            f"in NOT_SERVED_BY_2C3 with a reason: {sorted(missing)}",
        )
        stale = excused - declared
        self.assertEqual(
            stale,
            set(),
            f"NOT_SERVED_BY_2C3 names fields the serializer does not declare: {sorted(stale)}",
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

### Appendix K — `relay/httpapi/testdata/channels_clients_all.json`

**Regenerate this from Django** (Task 7 Step 2). Deliberately spelled the way DRF spells it — `30.0` where Go writes `30` — so the golden test exercises the decoded comparison rather than accidentally agreeing byte for byte. **Yours governs.**

```json
{"channels": [{"channel_id": "11111111-1111-4111-8111-111111111111", "state": "active", "url": "http://provider.invalid/live/sub/pw/41.ts", "stream_profile": "1", "owner": null, "buffer_index": 120, "client_count": 2, "uptime": 30.0, "started_at": 1789000000.5, "channel_name": "BBC One HD", "m3u_profile_id": 3, "stream_id": 41, "stream_name": "BBC One HD (UK)", "total_bytes": 9999888, "avg_bitrate_kbps": 2665.3034666666666, "avg_bitrate": "2.67 Mbps", "clients": [{"client_id": "client_1789000000000_1234", "user_agent": "VLC/3.0.20", "output_format": "mpegts", "output_profile_id": 7, "ip_address": "198.51.100.4", "connected_at": 1789000001.25, "user_id": "7"}, {"client_id": "client_1789000000000_5678", "user_agent": null, "output_format": "mpegts", "output_profile_id": null}]}, {"channel_id": "22222222-2222-4222-8222-222222222222", "state": "stopped", "url": "", "stream_profile": "0", "owner": null, "buffer_index": 0, "client_count": 0, "uptime": 0.0, "started_at": 1789000100.0, "clients": []}], "count": 2}
```

