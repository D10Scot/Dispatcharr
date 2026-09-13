# Phase 2 PR 2c-2 — the Go relay's vertical slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Go relay serve one live channel end to end on the **Proxy** stream-profile architecture only — a request arrives on the dev-gated route, the relay asks Django for a source, Django names a Proxy profile, the relay opens a raw HTTP read of the provider into an in-memory ring buffer, and one client reads MPEG-TS out of it from roughly five seconds behind live. No ffmpeg, no fan-out beyond what the type already supports, no failover, no Redis. Plus one Python change, Amendment **A1.4**, without which the relay would have to hold its own copy of every `apps/proxy/config.py` default.

**Architecture:** 2c-1's six packages, four of which gain real code. `buffer` gets the ring itself: the 188-byte packetiser, the monotonic chunk index, per-chunk timestamps and two eviction bounds. `control` gets the settings object, the control-plane address resolver and the `next-source` client with the full per-hop disposition table. `channel` gets the Proxy source reader, the `Channel` and the `map[uuid]*Channel` manager that replaces the ownership lease. `httpapi` gets the live TS handler. One new package, `internal/relaytest`, holds the Go counterpart of the Python subprocess harness's fake upstream — a synthetic MPEG-TS asset that is **byte-identical** to `harness/asset.py`'s, an HTTP server that loops it, and a fake Django.

**This is the first PR in which the Go relay does anything a client can observe.** It stays inert in every deployment: the route is behind 2c-1's dev flag, and nginx routes nothing to port 5658 until stage 2d.

---

## Global Constraints

Every task's requirements implicitly include this section. Constraints 1–11 are 2c-1's, restated because this plan is executed by an agent who has not read it; 12–16 are new.

1. **Anchor every command with an absolute path, or open it with a `cd` into your own worktree.** The shell's working directory has been observed in this programme drifting into another agent's worktree with no `cd` issued. A relative path that resolves somewhere else does not error; it writes a plausible file in the wrong tree.

2. **`go test -race` is mandatory on every Go test run: locally, in the hook, in the commit gate, in CI.** The concurrency model changes from gevent-cooperative to OS-thread-parallel goroutines in this phase, so a data race the Python implementation's execution model made *structurally impossible* becomes possible for the first time. This PR is where that starts being true in earnest: it is the first with a writer goroutine and reader goroutines touching the same structure.

3. **Standard library only. No `require` line, no `go.sum`, ever.** `scripts/check_go_stdlib_only.sh` is the mechanical check. Everything this PR needs is in `net/http`, `net/http/httptest`, `encoding/json`, `crypto/*`, `sync`, `sync/atomic`, `context`, `time`, `log/slog` and `regexp`. If a task appears to need a dependency, stop and report.

4. **Nothing in `relay/` may open a Postgres connection or a Redis connection, in any task, including a test.** These are the phase's two checkable success criteria (spec § Stage 2c, "The two invariants"). **This PR is the first where "no Redis on the live video path" is a claim about running code rather than about an empty module** — see Ruling R4, which makes it a break-check rather than an assurance.

5. **Every pin is tool-resolved on the day the PR is opened, never copied from this plan.** This PR adds no new action pin and no new base image, so in practice there is nothing to re-resolve; if you find yourself adding one, the rule applies.

6. **zizmor blocks on every finding in any workflow file you touch.** This PR should touch none: 2c-1's `go-tests.yml` already runs `go build ./...`, `go vet ./...`, `go test -race ./...` and `golangci-lint run` over the whole module, and its change detector already fires on `^relay/`. Verify that in Task 0 rather than assuming it.

7. **Do not add a Docker `HEALTHCHECK`, a SIGTERM drain, or a `/readyz` that reports anything real.** Those are 2c-8's (spec line 1802). `/readyz` stays the static 200 2c-1 shipped.

8. **Every Go constant that mirrors a Python literal carries its source `file:line` in a comment and is pinned by a test naming the same location.** This is 2c-1's Task 5 pattern. **This PR reduces the number of such constants rather than adding to them** — that is A1.4's whole purpose — so a new one needs a written reason.

9. **Prefer `t.Setenv` over manual environment save/restore, and never run an environment-mutating test with `t.Parallel()`.** `t.Setenv` panics if the test has called `t.Parallel()`, which is the toolchain refusing an unsafe test rather than a limitation to work around.

10. **Task 1 runs Django tests, so it needs the shared `dispatcharr-testrunner` container, and the container is shared across agents.** Its bind mount points at exactly one worktree, and the `PostToolUse` hooks run in the harness's environment where `DISPATCHARR_TEST_CONTAINER` never reaches them — so an edit-triggered run always uses the container named `dispatcharr-testrunner`, whatever you intended, and tests whichever tree it is mounted at. Before Task 1's first edit:

    ```bash
    docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
    ```

    If it is not your worktree, re-point it with `.claude/hooks/start-test-container.sh` — **after** checking nobody else is mid-task in the tree it currently holds (`docker ps`, and `stat -f '%Sm %N'` on that tree's recently-touched files; a modification younger than a few minutes means occupied). Tasks 2 onward need no container.

11. **Stage and commit in separate Bash calls, and write commit messages to a file and use `-F`.** The `PreToolUse` gate runs before the command, so one call that does both is blocked outright, and it matches on command text, so a heredoc containing the two words trips it. Every commit message ends with the attribution lines this session was given.

12. **A provider URL is a credential and never reaches a log, an error message or an HTTP response body.** `CLAUDE.md` § Known defects records five sites that logged provider credentials at INFO as an incident, and `scripts/check_credential_logging.py` polices the Python side in the edit hook and in `lint.yml`. **There is no Go equivalent of that script, and this PR is the first Go code that handles a provider URL at all.** Two specific traps, both found while verifying this plan's own code:
    - `net/http` wraps every client failure in a `*url.Error` whose `Error()` prints the whole URL and redacts **only the userinfo** — `http://user:***@host` — leaving the path and the query string intact. A Dispatcharr provider URL puts the credential in exactly those two places (`/live/<user>/<pass>/<id>.ts`, or a `?username=&password=` the M3U transform builds). `%w`-wrapping such an error as it comes puts a working credential in the container log on every failed connect. Task 6 ships `withoutURL` and the test that fails without it.
    - An HTTP error body is a log with a wider audience. `writeTuneFailure` (Task 8) answers with a fixed string per class of failure and never the exception text, for the same reason `apps/proxy/live_proxy/views.py`'s five admin views do.

13. **A control-plane setting is read from the wire or the tune fails. Never from a Go-side default.** Amendment A1.4 (Task 1) exists so the relay holds no second copy of `apps/proxy/config.py`'s defaults. A `cfg.Thing` that silently becomes zero when the key is absent reintroduces exactly the drift A1.4 removes, and it is worse than the Python original because nothing on the Go side would ever say so. `control.Settings`'s accessors fail on an absent key, every caller propagates, and Task 8's per-key test proves each one individually.

14. **Parity is against the code, not against the summary.** Every behavioural claim in this plan carries a `file:line`. Where this plan says Python does something, read the line before writing the Go. Two places where reading the source changed this plan's own design:
    - The packetiser is a **188-byte stride, not a sync-byte search** (`input/buffer.py:79-91`). A Go implementation that scanned for `0x47` would resynchronise a stream Python passes through unchanged.
    - **Keepalive packets and the client timeout are both gated on an unhealthy stream** (`output/ts/generator.py:546-551` and `:592`), and the error packets are all inside `_wait_for_initialization` (`:209-250`). None of the three is reachable in this PR's shape, so none is ported — see Ruling R5.

15. **Decide every lint finding in this plan, and re-lint after every `#nosec`.** 2c-1 found that silencing `G304` on its secret reader exposed `G703` on the same line, which was invisible until the linter was re-run. This PR has exactly one `#nosec` (`G705` on the video write path, Task 8) and **two findings that were fixed rather than suppressed** (`G115` twice, Tasks 2 and 4) — the suppression was the smaller diff and the worse answer in both cases. Run `golangci-lint run ./...` from the repo root after every task and treat any finding as a stop.

16. **Run the four checks after every task, from the module root**, and treat any of the four failing as a stop:

    ```bash
    cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
    ```

    `gofmt` is not optional and is enforced by the linter's formatter section. Run `gofmt -w .` before staging.

### The six ways a Go test can be green and meaningless

Every test this PR adds is bound by all six, and every task that adds an assertion ends with a **break-check**: patch the defect in, watch the test go red *for the right reason*, revert. **A break-check that does not go red is a finding, not a formality** — two of this plan's own break-checks failed to redden on the first attempt and both revealed a real hole in the test, recorded below as R7 and in Task 8 Step 5.

1. **The tautological oracle — a test whose expected value is computed by the code under test cannot fail.** In this PR it has two sharp forms. The ring's packet boundaries must be checked against `relaytest.PacketIndex`'s embedded indices, which the ring never sees and cannot compute; asking the ring where its own boundaries were would pass with the packetiser deleted. And the bound-token header must be pinned against a **literal produced by Django**, not recomputed with the Go function.

   **Worked example, the ring-buffer realignment test.**

   **Wrong:**

   ```go
   func TestWriteRealigns(t *testing.T) {
       r := New(Config{BudgetBytes: testBudget, ChunkBytes: testChunk})
       _, _ = r.Write(someBytes)
       chunks, _, _ := r.Read(0)
       for _, c := range chunks {
           if len(c)%TSPacketSize != 0 {
               t.Fatal("not whole packets")
           }
       }
   }
   ```

   This asserts that a chunk is a multiple of 188. The chunk size **is** a multiple of 188 by construction (`ChunkBytes = 188 * 1361`), so it passes with the packetiser deleted entirely, with the carried partial packet dropped on every write, with the bytes reordered, and with every chunk replaced by zeros. It is four assertions short of testing anything.

   **Right:**

   ```go
   func TestWritePublishesWholePacketsInUnbrokenOrder(t *testing.T) {
       r := newTestRing(t, nil)
       source := relaytest.SyntheticTS(28, 0x100)

       for offset := 0; offset < len(source); {
           for _, size := range []int{1, 187, 189, 63, 401} {
               if offset >= len(source) {
                   break
               }
               end := min(offset+size, len(source))
               if _, err := r.Write(source[offset:end]); err != nil {
                   t.Fatalf("Write: %v", err)
               }
               offset = end
           }
       }

       got, _ := drain(r, 0)
       if problem := relaytest.AlignmentProblem(got); problem != "" {
           t.Fatalf("the delivered stream is not whole TS packets: %s", problem)
       }
       for i := 0; i < len(got); i += TSPacketSize {
           want := i / TSPacketSize
           if idx := relaytest.PacketIndex(got[i : i+TSPacketSize]); idx != want {
               t.Fatalf("packet at byte %d carries index %d, want %d -- the packetiser "+
                   "lost, duplicated or reordered bytes", i, idx, want)
           }
       }
   }
   ```

   Three properties make this one able to fail. The write sizes are coprime with 188 and with each other, so **every** write ends mid-packet and the carry is exercised on every one. The oracle is the index `relaytest.SyntheticTS` embedded in each packet's payload, which no code under test produces or reads. And the assertion is on **position**, not on shape: a packet that arrives out of order, twice, or not at all fails it, where a length-modulo check would not. Verified: with the carry deleted it fails with `the delivered stream is not whole TS packets: byte 376 is 0x01, not the sync byte 0x47`.

2. **A pin that supplies the default pins nothing.** A test must supply a value that could not arise by accident. In this PR: the dev-branch base-URL test sets `DISPATCHARR_PORT=8888` **and** asserts `5656`, because the branch is required to ignore that variable; the ring-capacity test uses a chunk size a quarter of the default so the resulting count (16) is one the default could not produce; the override tests use `5999` and `http://control.invalid:7777`.

3. **A test can go hollow without changing.** Ask of every assertion: *what edit to production code would make this fail?* If the answer is "none", it is not a test. Every break-check in this plan names the edit it expects to redden the assertion, and the expected failure text.

4. **A fixture that patches away the subject its docstring names.** The rule: *patching the sink you assert against is how you observe; patching the logic that decides what reaches the sink is how you blind yourself.* In Go this arrives as an injected seam. `relaytest.NewUpstream` and `relaytest.NewControlPlane` are **sinks and sources**, not subjects: they are real HTTP servers that the real client code really talks to. Injecting a fake `Source` into `Manager.Attach` is observing the manager; injecting a fake `*buffer.Ring` and asserting it was written to would be replacing the subject with a mirror.

5. **A substring assertion pins nothing when the string has more than one source.** Before asserting on any log line or error message, grep for a second emitter of the same text. In Go this bites hardest on `err.Error()`: use `errors.Is`/`errors.As` against a named sentinel or a named type. Every error this PR defines is a named type or a sentinel for that reason — `buffer.ErrClosed`, `control.Unavailable`, `control.Refused`, `control.ErrNotConfigured`, `control.ErrSettingAbsent`, `channel.ErrUpstreamIdle`, `channel.ErrUpstreamStatus`, `httpapi.ErrNotProxyKind`, `httpapi.ErrNoSource`. The two places this plan **does** assert on message text are both about what must **not** be in it (a provider credential, a rejected configuration value), where a substring check is exactly the right instrument.

6. **A true positive for a false reason.** A break-check can redden from a side effect of the edit rather than from the defect. **When a break-check reddens, read the failure message and confirm it names the mechanism.** This PR has a documented instance: forcing the ring to ignore its configured chunk size reddens five tests, four of them with "no bytes at all", which names a symptom. The one that names the mechanism is `TestCapacityUsesTheConfiguredChunkSize` — `the ring holds 4 chunks, want 16 (a 1023472-byte budget at 63967 bytes a chunk)` — and that is the message to confirm.

### Working rules

- Run the four checks after every task (Global Constraint 16).
- Stage and commit in separate Bash calls; write commit messages to a file and use `-F`.
- Every commit message ends with the attribution lines this session was given.
- **Every Go file in this plan has been built, vetted, race-tested and linted at zero findings before this plan was written.** Where you find a discrepancy, your tree governs — and report it, because it means 2c-1 merged differently from its plan.

---

## Rulings

Decisions this plan makes that the spec leaves open, that 2c-1 left to its successor, or that the tree contradicts. Each is binding; each names what it was decided against.

### R1 — 2c-2 implements the `next-source` client in full, not a stub, and the spec's 2c-5 row is amended to say so.

The spec's PR table (line 1799) gives 2c-5 "control-plane client (`next-source`/`release`/`events`, both HMAC headers, the exact timeout table)". The spec's 2c-2 row gives 2c-2 "the Proxy stream-profile architecture only… one client, in-memory ring buffer, MPEG-TS passthrough for a single upstream". **Those two are not compatible**: the Proxy architecture begins with Django telling the relay that the profile *is* Proxy, which is the `next-source` answer's `stream_profile.kind` field 2c-1 added for exactly this purpose (its Finding F1: "the **first consumer is 2c-2, not 2c-5**"). A vertical slice that took its source URL from a flag would not be a vertical slice.

The seam is drawn at the **route**, not at the layer. 2c-2 implements `POST /api/relay/channels/<id>/next-source` — both HMAC headers, the (2s, 5s) budget, the one retry at 0.1s, the 404 mapping, and the **complete** 4xx/5xx/3xx/non-JSON/non-object disposition table from spec § Error handling per hop. 2c-5 adds `release` and `events`, and the degraded fallback to the channel-start-cached candidate list.

**The table is implemented in full rather than partly**, and that is the point of the ruling. A client that handled only the success path and left "the rest" to 2c-5 would be the half-implemented drain 2c-1's Global Constraint 7 refused: it would look like the feature while treating a 403 from a `SECRET_KEY` mismatch as a retryable outage — the exact failure the spec says "must fail the switch loudly instead of making every failover on the deployment degrade silently forever". Implementing one route's disposition completely costs about fifty lines and leaves 2c-5 with two routes to add and no table to retrofit.

Task 10 writes the amendment into the spec's 2c-5 row. A sentence beside the table is not the table (2c-1's Finding F2 established this).

### R2 — The parity matrix gains Go **references in the existing `Pin` cell**, not a sixth column.

The spec says rows "get a Go column" (line 1797 and following). Taken literally that is a structural change to `docs/relay-parity-matrix.md`: `e2e/tests/guards/parity-matrix.ts` finds the table by an exact five-name `COLUMNS` match, checks the delimiter's column count, rejects any row that is not five cells, and rejects a second five-column header. A sixth column means editing the guard, its spec's documentation block, and **every one of the thirty rows** — which is precisely the whole-file rewrite the matrix's own header exists to prevent, and it would land on the same lines every later 2c PR needs.

The guard was built for the other reading and says so. `testRefProblem` already handles `.go` files — `^func\s+(?:\([^)]*\)\s*)?<name>\s*\(` — with the comment *"2c-9 re-points this matrix at Go tests, which is why `.go` is already here"*. `parsePin`'s `TEST_REF_RE` is global and a `Pin` cell already holds a **list** of references; several rows carry two today. So a Go pin is one more backticked `path::symbol` in the cell a row already has, and closing a row stays a one-line diff that no two PRs contend on.

**Ruled: rows 7 and 9 gain a Go reference appended to their existing `Pin` cell.** No guard edit, no column, no `HIGHEST_ROW_ID` change. The spec's wording is recorded as loose prose in Task 10's amendment, not followed literally.

### R3 — Row 8's *mechanism* ships here; row 8's *pin* stays 2c-3's.

The user's brief for this PR names "one client reads from ~5 s behind live" as 2c-2 scope, and the join point needs per-chunk timestamps in the ring, which is unarguably this PR's. The spec's 2c-2 row names only rows 7 and 9, and gives row 8 to 2c-3 (line 1798).

Both are right, because they are about different things. The `Ring.Join` mechanism and its unit tests land here — they have to, the ring is built here. Row 8's claim is *"a new client joins roughly 5 seconds behind live"*, and "a new client" means a client joining a channel **that is already running for somebody else**, which is fan-out and does not exist until 2c-3. Pinning row 8 from a test where the joining client is also the only client would be pinning it against a degenerate case.

**Ruled: `Ring.Join` and four Go tests for it land in Task 4; row 8's `Pin` cell is not touched.** Task 10's amendment records that 2c-3 closes it and names the Go tests already available to cite.

### R4 — "No Redis on the live video path" becomes a break-check in this PR, because this is the PR where it stops being trivially true.

Spec § Stage 2c's two invariants held at 2c-1 by construction: constraint 3 forbids a third-party module, so there was no Redis client to link and nothing to check. This PR writes the code that in Python reaches Redis on **every one** of the families the spec's key-family walk lists — the ring buffer, the chunk index, the chunk timestamps, the channel metadata hash, the lifecycle flag, and the degraded-fallback source cache. That walk is the spec's own reasoning, and it says so: *"If any family is found, during implementation, not to fit this walk cleanly, the implementing PR says so honestly rather than asserting the invariant met."*

**This PR touches six of the eleven families and all six fit.** Task 11 records the walk with what each became:

| Key family | Python | Becomes, in this PR |
|---|---|---|
| `buffer_index` | `INCR` per chunk (`input/buffer.py:103`) | `Ring.head`, a `uint64` under the ring's mutex |
| `buffer_chunk:<n>` | `SETEX` per chunk, 60s TTL (`:107`) | a `Chunk` in the ring's bounded slice |
| `chunk_timestamps` | a sorted set, `ZADD` + `ZREMRANGEBYSCORE` (`:109-111`) | `Chunk.At`, one `time.Time` per chunk |
| `channel_owner` | the lease | **deleted** — `map[string]*Channel` under `Manager.mu` (D2) |
| `channel_stopping` | `SETEX` on two different TTLs, a documented race generator | `Channel.state`, one field |
| `channel_source_cache` | the degraded fallback's candidate list | not yet needed; 2c-5's, and a field on `Channel` when it is |

The five families this PR does not touch — the client registry, switch coordination, the follower pub/sub, the timing counters and the fMP4 output state — belong to 2c-3, 2c-5, 2c-6 and 2c-8, and each is named in the spec's own table.

**And the mechanical half.** `scripts/check_go_stdlib_only.sh` already fails on a non-empty `go.sum` or a module graph longer than one line, so a Redis client cannot be linked. Task 11 adds one more check the script cannot make: a grep for `redis` in `relay/` that must find nothing. It is cheap, it names the invariant in its failure message, and it catches the shape the module-graph check cannot — somebody hand-rolling a RESP client in the standard library, which is entirely possible and would satisfy every existing gate.

### R5 — No keepalive packets, no error packets, no client timeout. All three are parity, not scope-cutting.

The obvious reading of `output/ts/generator.py` is that a client at the buffer head gets keepalive packets and is disconnected after `STREAM_TIMEOUT + FAILOVER_GRACE_PERIOD`. Reading the guards changes the answer.

- `_should_send_keepalive` (`:542-551`) returns `False` unless the client is at the head **and** `consecutive_empty >= 5` **and**, on the owner, `not self.stream_manager.healthy`.
- `_is_timeout` (`:583-604`) returns `False` unless no data for the total timeout **and**, on the owner, `not self.stream_manager.healthy`.
- Every `create_ts_packet('error', …)` in the tree is at `:209-250`, inside `_wait_for_initialization`.

Nothing lowers `healthy` except the health monitor and the failover machinery, which are 2c-5's, and `_wait_for_initialization` is the path a follower takes while **another worker** elects itself owner — deleted outright by D2, not ported, because there is one process and `Manager.Attach` starts the source synchronously before the 200 is written.

So in this PR's shape all three gates are permanently shut, and reproducing the code behind them would produce behaviour Python does not have. **Ruled: `channel.Tuning` carries three fields, not six**; `ClientTimeout`, `KeepaliveInterval` and `MaxKeepalive` arrive in 2c-5 with the health flag that opens their gates. A field with no reader is the stale duplicate of the truth 2c-1's own `httpapi.Server` comment refused to keep.

### R6 — The raw-HTTP reader lives in `channel`, behind a one-method `Source` interface, and the ring is its `io.Writer`.

The spec names five packages and says the split is by concern; 2c-1 added `config` and justified it. An eighth package whose only member is one ninety-line type is not a concern, it is a file. `channel` owns "a channel's lifecycle" (2c-1's own stub comment), and where a channel's bytes come from is lifecycle.

The seam that matters is between the *source* and the *sink*, and it is already the narrowest one available: `Ring` implements `io.Writer`, so a source never learns what a chunk is, and `Source` has one method, so 2c-4's ffmpeg source drops in beside `ProxySource` with neither knowing about the other. Decided against defining `Source` in a package of its own for 2c-4's benefit: an interface with one implementation and one caller belongs with the caller until there are two.

**What the Python apparatus around this becomes.** `input/http_streamer.py` reads the response on an OS thread and writes it down an `O_NONBLOCK` pipe, which the main loop reads with `select`, so the Proxy and transcode paths share one `fetch_chunk()`. All of that — the pipe, the `fcntl`, the `select`, the second thread — exists to keep a blocking read off the gevent hub. Go's scheduler multiplexes blocking I/O onto OS threads itself, so what is left is the copy they existed to perform. That is a deletion with a stated reason, not a simplification.

### R7 — The immutability of a published chunk is asserted by **content**, not by the race detector.

Spec D2's fan-out design is "N slice headers over one backing array, no refcounting and no copy per client", which is only safe if a published chunk's array is never written again. The tempting test is to run readers and a writer under `-race` and let the detector find it.

It does not work reliably, and this plan found that out by trying. `-race` only reports an overlap that **actually happens**, so whether a reused array is caught depends on scheduling; and the first version of the break-check — hoisting the scratch buffer to a local inside `Write` — did not redden at all, because a test that writes one chunk per `Write` call never exercises reuse *within* a call. **Ruled: `TestAPublishedChunkIsNeverRewritten` reads a chunk, forces twenty writes past it, and compares the held bytes against a snapshot.** It reddens deterministically, with `byte 2 of a chunk a reader still holds changed from 0x00 to 0x01 after later writes: a published chunk's backing array was reused`.

`-race` still earns its place, on the other property: `TestConcurrentReadersAndOneWriter` drives four readers and one writer through `Read`, `Head`, `Oldest` and `Join` while the writer publishes two hundred chunks, and the detector **is** the oracle for the lock discipline. Verified: removing the `RLock` from `Head` produces `WARNING: DATA RACE` with both stacks.

### R8 — `control.Settings` is a map with erroring accessors, not a struct.

A1.4 puts thirty-eight keys on the wire. The natural Go shape is a struct, and it is the wrong one. An absent key unmarshals into a struct field as the zero value, silently — a chunk size of 0 deadlocks the ring, a retention of 0 empties it — and only fields somebody remembered to make a pointer would say so. That is the same silent-default failure A1.4 exists to remove, reintroduced one layer down.

**Ruled: `type Settings map[string]json.RawMessage`, with `Int`, `Float`, `Seconds` and `String` accessors that return `*ErrSettingAbsent` for a key the control plane did not send.** Every key fails loudly, including keys a later PR starts reading, with no struct edit. The schema argument for the Python side is unaffected and is honoured there: `RelayProxySettingsSerializer` declares all thirty-eight fields explicitly so drf-spectacular carries the shape, exactly as its own docstring argues.

One consequence worth stating: `Int` reads through `float64`, because the serializer declares several of these as `FloatField` and `15` arrives as `15.0`, which `json.Unmarshal` refuses into an `int`.

### R9 — The base-URL resolver is called on every tune, not at startup.

Python resolves inside `next_source()` and lets `ImproperlyConfigured` propagate, so a misconfigured deployment fails visibly on the first tune (`CLAUDE.md` § Commands). The Go alternative — resolve in `config.Load()` and refuse to start — is louder but wrong twice over: it refuses to boot a relay nobody has tuned yet, and it takes `/healthz` down with it, which is the probe 2c-8 wires a real drain to.

**Ruled: `control.BaseURL()` resolves per call.** It is string parsing on values already in hand and costs nothing. The four branches and the host check are ported from `apps/proxy/internal_base_url.py`, including the rule that userinfo is stripped **before** the host is validated, because what goes on the wire as the `Host` header is the netloc minus userinfo — validating the raw netloc would reject a URL Django would accept.

**The Django host regex is transcribed from the image, not from this plan.** Task 5 Step 2 has the command. `host_validation_re` is what `HttpRequest.get_host()` applies before `ALLOWED_HOSTS` is even consulted, so a host it rejects (an underscore anywhere in it) reaches Django as an opaque 400 with nothing naming the cause.

---

## The 2c-1 dependency ledger

**2c-1 is implemented and pushed at `e3eee458` (PR #282, draft, under review) but has not merged.** This table was first written against the 2c-1 *plan*; every row has since been **checked against the built tree** with `git show "e3eee458:<path>"` and the ledger below records what is actually there. **Task 0 still runs first** — 2c-1 is under review, so a fix round can move any of this before it merges, and a plan that assumed a draft branch would not change is the same mistake as assuming a plan would not.

Verified at `e3eee458`: the module path and the `go 1.27.1` directive; `buffer`'s seven constants and `ChunksForBytes(budget int) int`; `control`'s three header constants, `RelayTrustToken`, `InternalPrincipalToken`, `IsRelayTrusted` and `InternalRequestHeader(secret, method, fullPath string, body []byte, timestamp int64) string` — the exact signature Task 5 calls; `httpapi.Config{DevRoutes bool}`, `New(Config) *Server`, `(*Server).Handler()` and the dev-gated `GET /proxy/ts/stream/{channelID}` serving `notImplemented`; `.golangci.yml` with `noctx` enabled and `gosec` excluded in `_test.go` only; `go-tests.yml` running `go test -race ./...`, the stdlib check and a `Go result` aggregate, with a change detector whose pattern already covers `scripts/check_go_stdlib_only.sh`; and `stream_profile.kind` on the wire from one `_profile_kind` helper returning exactly `"redirect"`, `"proxy"` and `"transcode"`.

**Three `control` symbols 2c-1 built that this plan did not anticipate and does not use:** `IsInternalPrincipal`, `InternalRequestToken` (the bare digest, without the `v1.<ts>.` envelope) and `VerifyInternalRequest`. They are the *verifying* half of the contract, which 2c-8's `/proxy/relay/…` server needs and 2c-2 does not. Do not reach for them here; a tune verifies only `X-Dispatcharr-Authorized`, through `IsRelayTrusted`.

**And the HMAC vector agrees.** `relay/control/token_test.go:42` at `e3eee458` carries `v1.1789000000.5ce39464af1f52fac92ab6dd8101b289c2b9acce93d392216ac0dbcfa53a1fae` under `SECRET_KEY="phase2c1-test-secret"` — byte for byte the literal Task 5's own test uses, which this plan independently reproduced from a separate implementation before seeing 2c-1's. Two implementations and Django agree on the layout.

| What this PR depends on | Status | If it differs |
|---|---|---|
| Module `github.com/D10Scot/Dispatcharr/relay` at `relay/`, Go 1.27.1 | **as built at `e3eee458`** | the import paths in every file below move |
| `relay/buffer` with `TSPacketSize`, `ChunkBytes`, `RetentionSeconds`, `JoinBehindSeconds`, `MaxChunksPerChannel`, `MaxBytesPerChannel`, `ChunksForBytes` | **as built at `e3eee458`** | Task 4 Step 1's patch to `ChunksForBytes` needs re-deriving |
| `relay/control` with `HeaderAuthorized`, `HeaderInternal`, `HeaderInternalRequest`, `RelayTrustToken`, `InternalPrincipalToken`, `IsRelayTrusted`, `InternalRequestHeader(secret, method, fullPath, body, ts)` | **as built at `e3eee458`** | Task 5 and Task 8 call these by name |
| `relay/httpapi` with `Config{DevRoutes bool}`, `New(Config) *Server`, `(*Server).Handler()`, a dev-gated `GET /proxy/ts/stream/{channelID}` returning 501 | **as built at `e3eee458`** | Task 8 replaces the 501 stub with the real handler |
| `relay/channel` and `relay/ffmpeg` as documented stubs | **as built at `e3eee458`** | Task 6 adds files beside `channel.go`; the doc comment stays |
| `relay/config` with `Load()`, `Config{Port, Secret, DevRoutes}` | **as built at `e3eee458`** | Task 8's wiring in `main.go` moves |
| `.golangci.yml` at the repo root, v2 schema, `gosec` excluded in `_test.go` only, `noctx` **not** excluded | **as built at `e3eee458`** | every lint outcome in this plan is re-derived |
| `go-tests.yml` running `go build`, `go vet`, `go test -race ./...`, `golangci-lint`, `scripts/check_go_stdlib_only.sh`, with a `Go result` aggregate and a change detector matching `^relay/` | **as built at `e3eee458`**, and its pattern already covers `scripts/check_go_stdlib_only.sh` | Task 0 reports it; this PR adds no workflow change if it is there |
| `.claude/hooks/run-go-checks.sh` on `relay/**/*.go` | not checked — confirm in Task 0 | Go edits will not be checked by the hook; run the four checks by hand |
| `stream_profile.kind` on the next-source contract, values `proxy` / `redirect` / `transcode` | **as built at `e3eee458`**, from one `_profile_kind` helper | **this PR cannot proceed**; `kind` is what the Proxy branch tests. Stop and report. |
| `zero_orm_allowlist.py` `resolve_source` hits = 38, `get_stream_object` = 3 | 2c-1's R8 *predicts* 38; measured 36 at `315b02a4` before 2c-1 | Task 1 Step 6 re-measures and expects **no further change** from A1.4 |

**Verified in this tree, not inherited:** everything with a `file:line` in this plan — `apps/proxy/config.py`'s thirty-one class attributes and their values, `core/models.py:719-730`'s seven stored keys, `apps/proxy/serializers.py:107-135`'s serializer, `apps/proxy/next_source.py:679-700`'s `_with_proxy_settings`, `input/buffer.py`'s packetiser and its two Lua scripts, `output/ts/generator.py`'s positioning, keepalive and timeout guards, `input/http_streamer.py` in full, `apps/proxy/internal_base_url.py`'s four branches, `apps/proxy/control_plane.py:73-146`'s retry loop, `e2e/tests/guards/parity-matrix.ts` in full, and `harness/asset.py`'s `synthetic_ts`.

---

## File Structure

```
relay/buffer/ring.go                       NEW — the ring: packetiser, index, timestamps, bounds
relay/buffer/ring_test.go                  NEW
relay/buffer/buffer.go                     EDIT — ChunksForBytes gains a shared implementation
relay/control/settings.go                  NEW — the proxy_settings map and its accessors
relay/control/baseurl.go                   NEW — the D9 four-branch resolver and the host check
relay/control/nextsource.go                NEW — the next-source client and the disposition table
relay/control/nextsource_test.go           NEW
relay/control/baseurl_test.go              NEW
relay/channel/state.go                     NEW — the eight ChannelState strings
relay/channel/tuning.go                    NEW — channel-start-time settings, resolved
relay/channel/source_proxy.go              NEW — the Source interface and ProxySource
relay/channel/source_proxy_test.go         NEW
relay/channel/channel.go                   EDIT — the stub's doc comment stays; the type arrives
relay/channel/manager.go                   NEW — map[string]*Channel, Attach/Stop/StopAll
relay/channel/manager_test.go              NEW
relay/httpapi/stream.go                    NEW — the live TS handler
relay/httpapi/stream_test.go               NEW
relay/httpapi/server.go                    EDIT — the dev route gains the real handler
relay/main.go                              EDIT — wire the manager and the control client
relay/internal/relaytest/asset.go          NEW — synthetic MPEG-TS, byte-identical to Python's
relay/internal/relaytest/asset_test.go     NEW
relay/internal/relaytest/upstream.go       NEW — the looping provider
relay/internal/relaytest/controlplane.go   NEW — the fake Django
scripts/check_go_stdlib_only.sh            EDIT — one more check: no Redis anywhere in relay/

                                           --- the Python half, Amendment A1.4 ---
apps/proxy/config.py                       EDIT — class_attribute_defaults()
apps/proxy/serializers.py                  EDIT — 31 fields on RelayProxySettingsSerializer
apps/proxy/next_source.py                  EDIT — _with_proxy_settings merges the defaults
apps/proxy/tests/test_effective_proxy_settings.py   NEW — the enumeration and value tests

                                           --- documents ---
docs/relay-parity-matrix.md                EDIT — rows 7 and 9 gain a Go reference
docs/superpowers/specs/2026-09-09-…-design.md  EDIT — Amendment A2, the 2c-5 row, a Done log row
CLAUDE.md                                  EDIT — § Architecture, § Testing
```

Nothing under `core/`, `dispatcharr/`, `frontend/`, `e2e/` or `metrics/` is touched, and nothing under `apps/` beyond A1.4's four files.

---
## Task 0: Diff the merged 2c-1 tree against this plan's expectations

**Nothing else is written until this task is done and reported.** The ledger above was checked against `e3eee458`, but 2c-1 is a draft under review: a fix round can move any of it before it merges, so this task re-checks against **the tree you actually have** rather than against that SHA.

- [ ] **Step 1: Confirm the module and the toolchain**

  ```bash
  cd <your worktree>
  cat relay/go.mod
  go version
  golangci-lint --version
  ls -1 relay/*/ relay/*.go
  ```

  Expected: module `github.com/D10Scot/Dispatcharr/relay`; a `go` directive; `buffer/`, `channel/`, `config/`, `control/`, `ffmpeg/`, `httpapi/` and `main.go`. If the toolchain on this host is older than `go.mod`'s directive, `go build` refuses with a clear message — that is the right failure, not a reason to lower the directive.

- [ ] **Step 2: Confirm the exported symbols this PR calls by name**

  ```bash
  cd <your worktree>/relay && go doc ./buffer && go doc ./control && go doc ./httpapi && go doc ./config
  ```

  Check each against the ledger table above. The three that matter most:
  - `control.InternalRequestHeader` must take `(secret, method, fullPath string, body []byte, ts int64)` and return the `v1.<ts>.<hex>` string. Task 5's client calls it with exactly that.
  - `control.IsRelayTrusted(secret, value string) bool` must exist. Task 8's header check is the only thing standing between a hand-crafted `X-Relay-Channel` and the authorize hop being bypassed.
  - `buffer.ChunksForBytes(budget int) int` must exist with that signature. Task 4 Step 1 refactors it without changing it.

- [ ] **Step 3: Confirm `stream_profile.kind` landed, and read its values off the code**

  ```bash
  cd <your worktree>
  grep -n 'kind' apps/proxy/serializers.py | head
  grep -n '_profile_kind\|"kind"' apps/proxy/next_source.py
  ```

  Expected: a `kind` field on `StreamProfileRefSerializer`, and one helper in `next_source.py` deriving `"redirect"` / `"proxy"` / `"transcode"`, routed to from four construction sites. **If `kind` is absent, stop and report.** This PR's whole Proxy branch is a comparison against it, and 2c-1's own Finding F1 establishes that `transcode` cannot substitute: it is `False` for Redirect as well as Proxy, and both locked profiles carry an empty command, so nothing else on the wire separates them.

- [ ] **Step 4: Confirm CI already covers what this PR adds**

  ```bash
  cd <your worktree>
  grep -n 'go test\|golangci\|check_go_stdlib_only\|Go result\|relay/' .github/workflows/go-tests.yml
  ```

  Expected: `go test -race ./...` over the whole module, `golangci-lint`, the stdlib check, a `Go result` aggregate, and a change detector whose pattern matches `^relay/`. **If the detector's pattern does not also match `scripts/check_go_stdlib_only.sh`, note it** — Task 11 edits that script, and a change to it that runs no Go job is a gate that cannot see its own edit. (2c-1's plan has it in the pattern; confirm rather than assume.)

- [ ] **Step 5: Run the four checks on the tree as merged**

  ```bash
  cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
  ```

  All four green before you write a line. If any is red on the merged tree, that is 2c-1's problem, not yours — report it and stop.

- [ ] **Step 6: Report**

  Write the diff between the ledger table and what you found, as a short list, into the PR description draft. Every later task assumes this step found no surprises; if it did, say which task each surprise lands in.

---

## Task 1: Amendment A1.4 — Django sends **effective** `proxy_settings`

**The finding this closes (2c-1's F4).** `CoreSettings.get_proxy_settings()` returns seven keys, and they are on the wire already. But the relay does not read its configuration through those seven: it reads it through `ConfigHelper.get(name, default)`, which is `getattr(Config, name, default)` where `Config` is `apps.proxy.config.TSConfig` (`apps/proxy/live_proxy/config_helper.py:5`, `:16`). Those are **class attributes**, a disjoint set of thirty-one names, and **not one of them is serialised anywhere**. A Go relay therefore needs its own copy of every default, and the two copies drift silently: a default changed in `apps/proxy/config.py` reaches the Python relay immediately and the Go relay never.

This is the trap `CLAUDE.md` already records for `BUFFER_CHUNK_SIZE`, where an unreachable `5644` literal in `input/buffer.py:42` makes the effective chunk a quarter of what the call site looks like.

**The fix, in one sentence:** `proxy_settings` on the wire becomes the stored `CoreSettings` group merged over every `TSConfig` class-attribute default, so every value the relay reads is present with a real value and Go holds no second copy.

**Two corrections to the brief's own framing, both load-bearing.**

- **The two key spaces are disjoint, so "merged over" is not an overlay.** The stored group's seven keys are `snake_case`; the class attributes are thirty-one `SCREAMING_CASE` names. Only three pairs are even semantically related (`buffering_timeout`/`BUFFERING_TIMEOUT`, `buffering_speed`/`BUFFER_SPEED`, `new_client_behind_seconds`/`NEW_CLIENT_BEHIND_SECONDS`), and in each case the relay reads the two through **different functions** — `Config.get_buffering_timeout()` goes to `CoreSettings`, `ConfigHelper.get('BUFFER_CHUNK_SIZE')` goes to the class. Overlaying them would make the wire claim a value the Python relay does not use. The merge is written defaults-first-stored-second anyway, so that the stored value would win if the spaces ever met.

- **The resolver must consult `TSConfig`, not `BaseConfig`, and the difference is visible.** `TSConfig` shadows `BaseConfig.BUFFERING_TIMEOUT = 15` with a `@property` (`apps/proxy/config.py:162-164`), so `getattr` on the class returns a property object, not 15 — which is correct, because the live value comes from the `buffering_timeout` stored key. Reading `BaseConfig` would put a stale `BUFFERING_TIMEOUT: 15` on the wire beside a `buffering_timeout` that disagreed with it. The same shadowing removes `REDIS_CHUNK_TTL`, `CHANNEL_SHUTDOWN_DELAY`, `BUFFERING_SPEED`, `CHANNEL_INIT_GRACE_PERIOD` and `CHANNEL_CLIENT_WAIT_PERIOD`. (This is the same shadowing mechanism issue #232 records for the settings *cache*: `CoreSettings.invalidate_group_cache` clears `BaseConfig`'s while every proxy read goes through `TSConfig`, whose own attribute shadows the parent's.)

- [ ] **Step 1: Add the enumeration to `apps/proxy/config.py`**

  At the end of the file, after `TSConfig`:

  ```python
  # Types a class-attribute default may have and still go on the wire. bool is
  # excluded explicitly because it is a subclass of int and would otherwise be
  # serialised as a number; there is none today, and this is what keeps that
  # from becoming a silent wire change if one is added.
  _WIRE_SCALARS = (int, float, str)


  def class_attribute_defaults():
      """Every TSConfig class-attribute default, by its own name.

      This is the half of the effective proxy settings that has never been on
      the wire. The relay reads these through ConfigHelper.get(name, default),
      which is getattr(TSConfig, name, default) -- apps/proxy/live_proxy/
      config_helper.py:16 -- so they are the real defaults, and a Go relay that
      did not receive them would have to hold its own copy of every one.
      Phase 2 spec Amendment A1.4.

      TSConfig, not BaseConfig, because that is what ConfigHelper consults.
      The difference is not cosmetic: TSConfig shadows BaseConfig's plain
      BUFFERING_TIMEOUT with a @property, so walking BaseConfig would put a
      stale 15 on the wire beside the buffering_timeout stored key that
      actually supplies the live value.

      The MRO is walked base-first so a derived class wins, and a name whose
      derived binding is NOT a plain scalar -- a property, a classmethod -- is
      REMOVED rather than skipped. That pop is the whole shadowing rule: it is
      what excludes BUFFERING_TIMEOUT, BUFFERING_SPEED, REDIS_CHUNK_TTL,
      CHANNEL_SHUTDOWN_DELAY, CHANNEL_INIT_GRACE_PERIOD and
      CHANNEL_CLIENT_WAIT_PERIOD, all six of which are database-backed and
      already on the wire under their snake_case names.

      vars(), not dir(): dir() on a class also reports the metaclass's
      attributes, and this walk should see exactly what is written in this
      file.
      """
      defaults = {}
      for klass in reversed(TSConfig.__mro__):
          for name, value in vars(klass).items():
              if name.startswith("_"):
                  continue
              if isinstance(value, _WIRE_SCALARS) and not isinstance(value, bool):
                  defaults[name] = value
              else:
                  defaults.pop(name, None)
      return defaults
  ```

  **Verify it produces exactly thirty-one names before going further.** Measured against this tree at `315b02a4`:

  ```bash
  cd <your worktree>
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python -c "
  import django, os, sys
  os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings_test')
  sys.path.insert(0, '/repo')
  django.setup()
  from apps.proxy.config import class_attribute_defaults
  d = class_attribute_defaults()
  print(len(d))
  for k in sorted(d): print(k, '=', repr(d[k]))
  "
  ```

  Expected: **31**, and the names and values in Step 2's field block. `BUFFERING_TIMEOUT` and `REDIS_CHUNK_TTL` must both be **absent**. If the count differs, `apps/proxy/config.py` has moved since this plan was written — report the difference and use what you measured.

- [ ] **Step 2: Declare the thirty-one fields on `RelayProxySettingsSerializer`**

  In `apps/proxy/serializers.py`, append to `RelayProxySettingsSerializer` (which today carries the seven stored keys, `:129-135`), and extend its docstring:

  ```python
      # Phase 2 spec Amendment A1.4: TSConfig's class-attribute defaults, the
      # half of the effective settings that had never been on the wire. Each
      # is declared explicitly rather than through a DictField for this
      # class's existing reason -- the contract belongs in the
      # drf-spectacular schema so a Go client can generate against it -- and
      # the field TYPE mirrors the Python literal's own type, so a Go client
      # is not handed 15.0 where the schema promised an integer.
      #
      # The list is not maintained by hand: test_effective_proxy_settings.py
      # enumerates apps/proxy/config.py and fails if a default is added there
      # without appearing here. The file:line and value in each comment are
      # provenance for a reader, not the source of truth.
      #
      # No `required=False`: this serializer only ever renders, and the one
      # producer (_with_proxy_settings) always supplies every key, so a
      # missing key is a contract bug and should be a loud 500 rather than a
      # silently dropped field -- which is the failure mode A1.4 exists to
      # remove.
      BUFFER_CHUNK_SIZE = serializers.IntegerField()  # config.py:15 = 255868
      BUFFER_SPEED = serializers.IntegerField()  # config.py:17 = 1
      CHUNK_BATCH_SIZE = serializers.IntegerField()  # config.py:95 = 5
      CHUNK_SIZE = serializers.IntegerField()  # config.py:7 = 8192
      CHUNK_TIMEOUT = serializers.IntegerField()  # config.py:99 = 5
      CLEANUP_CHECK_INTERVAL = serializers.IntegerField()  # config.py:111 = 1
      CLEANUP_INTERVAL = serializers.IntegerField()  # config.py:107 = 60
      CLIENT_HEARTBEAT_INTERVAL = serializers.IntegerField()  # config.py:112 = 5
      CLIENT_POLL_INTERVAL = serializers.FloatField()  # config.py:8 = 0.1
      CLIENT_RECORD_TTL = serializers.IntegerField()  # config.py:110 = 60
      CLIENT_WAIT_TIMEOUT = serializers.IntegerField()  # config.py:114 = 60
      CONNECTION_TIMEOUT = serializers.IntegerField()  # config.py:13 = 10
      DEFAULT_USER_AGENT = serializers.CharField()  # config.py:6 = 'VLC/3.0.20 LibVLC/3.0.20'
      FAILOVER_GRACE_PERIOD = serializers.IntegerField()  # config.py:120 = 20
      GHOST_CLIENT_MULTIPLIER = serializers.FloatField()  # config.py:113 = 10.0
      HEALTH_CHECK_INTERVAL = serializers.IntegerField()  # config.py:104 = 5
      INITIAL_BEHIND_CHUNKS = serializers.IntegerField()  # config.py:94 = 4
      KEEPALIVE_INTERVAL = serializers.FloatField()  # config.py:97 = 0.5
      MAX_HEALTH_RECOVERY_ATTEMPTS = serializers.IntegerField()  # config.py:117 = 2
      MAX_KEEPALIVE_DURATION = serializers.IntegerField()  # config.py:122 = 300
      MAX_RECONNECT_ATTEMPTS = serializers.IntegerField()  # config.py:118 = 3
      MAX_RETRIES = serializers.IntegerField()  # config.py:9 = 3
      MAX_STREAM_SWITCHES = serializers.IntegerField()  # config.py:14 = 10
      MIN_STABLE_TIME_BEFORE_RECONNECT = serializers.IntegerField()  # config.py:119 = 30
      NEW_CLIENT_BEHIND_SECONDS = serializers.IntegerField()  # config.py:96 = 5
      RETRY_WAIT_INTERVAL = serializers.FloatField()  # config.py:12 = 0.5
      RETRY_WINDOW_SECONDS = serializers.IntegerField()  # config.py:10 = 1800
      STABLE_CONNECTION_THRESHOLD = serializers.IntegerField()  # config.py:11 = 30
      STREAM_TIMEOUT = serializers.IntegerField()  # config.py:103 = 20
      TARGET_BITRATE = serializers.IntegerField()  # config.py:102 = 8000000
      URL_SWITCH_TIMEOUT = serializers.IntegerField()  # config.py:121 = 20
  ```

  **Three of these are dead in the Python relay and are sent anyway** — `MAX_HEALTH_RECOVERY_ATTEMPTS`, `MAX_RECONNECT_ATTEMPTS` and `MIN_STABLE_TIME_BEFORE_RECONNECT` are in `CLAUDE.md`'s "dead or unwired" list, the real values being bare literals in the health-monitor body. So is `BUFFER_SPEED`, which nothing reads (the live threshold is the `buffering_speed` stored key). Sending them is deliberate: the rule is "every class-attribute default", not "every one somebody currently reads", because a curated list is a second thing to maintain and would go stale the moment 2c-5 starts reading one. Thirty-one integers cost nothing on the wire, and D5 says carry a defect rather than fix it in transit.

- [ ] **Step 3: Merge them in `_with_proxy_settings`**

  In `apps/proxy/next_source.py`, in `_with_proxy_settings` (`:679-700`), replace the single assignment and extend the docstring:

  ```python
      from core.models import CoreSettings

      from apps.proxy.config import class_attribute_defaults

      # Defaults first, stored second. The two key spaces are disjoint --
      # thirty-one SCREAMING_CASE class attributes and seven snake_case stored
      # keys -- so the order cannot matter today, and it is written this way so
      # that a stored value would win if they ever met. Spec Amendment A1.4.
      answer["proxy_settings"] = {
          **class_attribute_defaults(),
          **CoreSettings.get_proxy_settings(),
      }
      return answer
  ```

  Add to the docstring, after the existing paragraph about the process-local cache:

  ```
      The class-attribute half needs no such care: those are module constants
      with no cache and no database behind them. What they DO need is to be
      read off TSConfig rather than BaseConfig -- see class_attribute_defaults'
      own docstring for why the difference is visible on the wire.
  ```

  **The import is function-local, matching the module's existing idiom** (`from core.models import CoreSettings` on the line above is too). `apps/proxy/config.py` imports `django.db.connection` at module level, and `apps/channels/models.py:6-7` already makes this package's import graph load-bearing for every migration and management command (`CLAUDE.md` § Structural constraints); a new module-level import into `next_source.py` is not worth the risk for a function called once per tune.

- [ ] **Step 4: Write `apps/proxy/tests/test_effective_proxy_settings.py`**

  Two tests, and **both are needed**. The first proves the wire carries every default; the second proves it carries the right *values*. Neither substitutes for the other, and the reason is stated in the file.

  ```python
  """Amendment A1.4: Django sends EFFECTIVE proxy settings.

  The stored CoreSettings group, merged over every TSConfig class-attribute
  default, so the Go relay holds no second copy of apps/proxy/config.py and
  the two cannot drift.
  """

  from django.test import TestCase

  from apps.proxy.config import TSConfig, class_attribute_defaults
  from apps.proxy.next_source import _with_proxy_settings
  from apps.proxy.serializers import RelayProxySettingsSerializer

  # The seven keys CoreSettings.get_proxy_settings() stores (core/models.py:
  # 719-730). Typed here rather than imported so that a key silently
  # disappearing from that dict fails this module rather than agreeing with it.
  STORED_KEYS = {
      "buffering_timeout",
      "buffering_speed",
      "redis_chunk_ttl",
      "channel_shutdown_delay",
      "channel_init_grace_period",
      "channel_client_wait_period",
      "new_client_behind_seconds",
  }


  class EnumerationTests(TestCase):
      """A default cannot be added to config.py without appearing on the wire."""

      def test_every_class_attribute_default_is_a_declared_field(self):
          declared = set(RelayProxySettingsSerializer().fields) - STORED_KEYS
          expected = set(class_attribute_defaults())
          missing = expected - declared
          extra = declared - expected
          self.assertEqual(
              declared,
              expected,
              "RelayProxySettingsSerializer and apps/proxy/config.py disagree about "
              "which defaults reach the relay.\n"
              f"  declared but not a TSConfig default: {sorted(extra)}\n"
              f"  a TSConfig default but not declared: {sorted(missing)}\n"
              "Adding a class attribute to TSConfig or BaseConfig means adding a "
              "field here, or the Go relay never learns the value changed.",
          )

      def test_the_seven_stored_keys_are_still_declared(self):
          # The other half of the same field list. Without this, deleting a
          # stored key's field would leave the test above perfectly happy.
          self.assertTrue(
              STORED_KEYS.issubset(set(RelayProxySettingsSerializer().fields)),
              "RelayProxySettingsSerializer dropped one of the stored keys: "
              f"{sorted(STORED_KEYS - set(RelayProxySettingsSerializer().fields))}",
          )

      def test_a_shadowed_class_attribute_does_not_reach_the_wire(self):
          # TSConfig shadows BaseConfig.BUFFERING_TIMEOUT = 15 with a @property
          # (config.py:162), so the live value comes from the buffering_timeout
          # stored key. Walking BaseConfig instead of TSConfig would put a
          # stale 15 on the wire beside it. Asserted by name because it is the
          # one case where the two halves of this contract could contradict
          # each other.
          defaults = class_attribute_defaults()
          for shadowed in (
              "BUFFERING_TIMEOUT",
              "BUFFERING_SPEED",
              "REDIS_CHUNK_TTL",
              "CHANNEL_SHUTDOWN_DELAY",
              "CHANNEL_INIT_GRACE_PERIOD",
              "CHANNEL_CLIENT_WAIT_PERIOD",
          ):
              self.assertNotIn(
                  shadowed,
                  defaults,
                  f"{shadowed} is a property on TSConfig, not a plain default; its "
                  "live value is a stored CoreSettings key. Sending the shadowed "
                  "class attribute would put a stale number on the wire beside it.",
              )

      def test_a_field_type_matches_its_python_literal(self):
          # A Go client generated against the schema unmarshals by type. A
          # FloatField where the value is an int is harmless; an IntegerField
          # where the value is 0.5 truncates in the schema and lies to the
          # generator.
          fields = RelayProxySettingsSerializer().fields
          for name, value in class_attribute_defaults().items():
              with self.subTest(name=name):
                  field = type(fields[name]).__name__
                  want = {int: "IntegerField", float: "FloatField", str: "CharField"}[
                      type(value)
                  ]
                  self.assertEqual(field, want, f"{name} is {value!r}")


  class ValueTests(TestCase):
      """The wire carries the effective value, not a placeholder."""

      def setUp(self):
          self.settings = _with_proxy_settings({})["proxy_settings"]

      def test_the_answer_carries_both_halves(self):
          self.assertTrue(STORED_KEYS.issubset(self.settings))
          self.assertTrue(set(class_attribute_defaults()).issubset(self.settings))

      def test_every_default_reaches_the_wire_with_its_class_value(self):
          # This half proves the WIRING -- that the merge did not drop or
          # rename anything -- and nothing more. It cannot prove the VALUES,
          # because it reads TSConfig exactly as the producer does: it would
          # pass if both read the wrong class. The literals below are what
          # carry that, which is why both tests exist.
          for name, value in class_attribute_defaults().items():
              with self.subTest(name=name):
                  self.assertEqual(self.settings[name], value)

      def test_three_values_pinned_against_the_source(self):
          # Typed by hand from apps/proxy/config.py, one per Python type, so
          # this test fails if the producer starts reading a different class
          # or a different attribute set. BUFFER_CHUNK_SIZE especially: the
          # Go ring buffer sizes itself from it, and CLAUDE.md records that
          # input/buffer.py:42's fallback of TS_PACKET_SIZE * 5644 is an
          # UNREACHABLE default four times too large -- so the number a
          # careless reader would copy is the wrong one.
          self.assertEqual(self.settings["BUFFER_CHUNK_SIZE"], 255868)  # config.py:15, 188 * 1361
          self.assertEqual(self.settings["STREAM_TIMEOUT"], 20)  # config.py:103
          self.assertEqual(self.settings["GHOST_CLIENT_MULTIPLIER"], 10.0)  # config.py:113

      def test_the_serializer_renders_every_key(self):
          # The producer and the serializer are two lists that must agree.
          # _with_proxy_settings builds the dict and DRF drops anything the
          # serializer does not declare, so a key present in the dict and
          # absent from the fields vanishes between them in silence.
          rendered = RelayProxySettingsSerializer(self.settings).data
          self.assertEqual(set(rendered), set(self.settings))
  ```

- [ ] **Step 5: Break-check, four edits**

  Each must redden, and each failure message must name the mechanism.

  1. Add `FOO_BAR = 7` to `TSConfig` without a serializer field. Expect `test_every_class_attribute_default_is_a_declared_field` to fail with `a TSConfig default but not declared: ['FOO_BAR']`. Revert. **This is the test's whole reason to exist** — it is what makes a new default impossible to add silently.
  2. Change `class_attribute_defaults` to walk `BaseConfig.__mro__` instead of `TSConfig.__mro__`. Expect `test_every_class_attribute_default_is_a_declared_field` to fail listing the twenty TSConfig-only names as missing, **and** `test_a_shadowed_class_attribute_does_not_reach_the_wire` to fail naming `BUFFERING_TIMEOUT`. The second is the one that names the mechanism; confirm you see it.
  3. Delete the `defaults.pop(name, None)` line (skip a non-scalar rather than removing it). Expect `test_a_shadowed_class_attribute_does_not_reach_the_wire` to fail naming `BUFFERING_TIMEOUT` — the property would not be *added*, but `BaseConfig`'s plain 15 would survive the derived class's shadow.
  4. Change `BUFFER_CHUNK_SIZE` in `config.py` to `188 * 5644` — the unreachable Python default `CLAUDE.md` warns about. Expect `test_three_values_pinned_against_the_source` to fail with `1060672 != 255868`, and `test_every_default_reaches_the_wire_with_its_class_value` to **pass**, because it reads the same wrong value from the same place. That asymmetry is the point of having both, and it is worth watching happen once.

- [ ] **Step 6: Re-measure the zero-ORM allowlist**

  `_with_proxy_settings` sits inside `resolve_source`'s reachable subtree, so a new ORM-shaped call site there moves a ratchet number. `class_attribute_defaults()` calls no Django model method, so **the prediction is no change** — but 2c-1's R8 moved these numbers, so measure rather than assume:

  ```bash
  cd <your worktree> && set -o pipefail && python3 -c "
  import sys; sys.path.insert(0, '.')
  from apps.proxy.live_proxy.tests.zero_orm_scan import scan_edge, Edge
  for name in ('resolve_source', 'get_stream_object'):
      print(name, len(scan_edge(Edge('x', 'apps.proxy.next_source', name))))
  "
  ```

  The scanner is pure AST and needs no Django. Measured **36 and 3** at `315b02a4` (before 2c-1); 2c-1's R8 predicts `resolve_source` becomes **38**. Whatever the merged tree reports, this task must not change it. If it does, find out why before editing `zero_orm_allowlist.py`.

- [ ] **Step 7: Run the three backend labels this touches**

  ```bash
  cd <your worktree>
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python /repo/manage.py test apps.proxy.tests --keepdb
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python /repo/manage.py test apps.proxy.live_proxy.tests --keepdb
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python /repo/manage.py test apps.channels.tests --keepdb
  ```

  `apps/proxy/next_source.py` and `apps/proxy/serializers.py` route to `apps.proxy` through `labels_for_changed_paths`'s prefix match; the other two are the neighbours a next-source change has historically broken. **`apps/proxy/tests/test_next_source_api.py` and `test_next_source_resolution.py` assert exact dict equality on parts of the answer** — 2c-1's Global Constraint 4 records that they reddened for `stream_profile.kind` and had to be updated. Check whether either asserts on `proxy_settings`; if one does, this task updates it in the same commit.

- [ ] **Step 8: Commit**

---

## Task 2: `relay/internal/relaytest` — the synthetic MPEG-TS asset

The Go counterpart of `apps/proxy/live_proxy/tests/harness/asset.py`. The spec's § Testing says the subprocess-harness tests are what a Go implementer reads first; this is what makes that reading actionable, because the two assets are byte-identical and a test can therefore compare what the two relays deliver from the same bytes.

**A normal package, not a `_test.go` file**, because 2c-2 through 2c-7 all drive it from different packages and Go test files are not importable. Under `internal/` so nothing outside this module can depend on it, and `main` never imports it, so it is not linked into the binary. It **is** linted in full — `.golangci.yml` excludes `gosec` in `_test.go` only — so it must be written clean.

- [ ] **Step 1: Write `relay/internal/relaytest/asset.go`**

  ```go
  // Package relaytest is the Go relay's test upstream: a synthetic MPEG-TS
  // asset, an HTTP server that loops it, and a fake control plane.
  //
  // It is a normal package rather than a _test.go file because 2c-2 through
  // 2c-7 all drive it from different packages, and Go test files are not
  // importable. It sits under internal/ so nothing outside this module can
  // depend on it, and main never imports it, so it is not linked into the
  // binary.
  //
  // It is the Go counterpart of apps/proxy/live_proxy/tests/harness/asset.py
  // and harness/upstream.py, and the packet layout below is byte-identical to
  // synthetic_ts() so a test can compare what the two relays deliver from the
  // same bytes.
  //
  // SYNTHETIC RATHER THAN ENCODED, for the Python harness's reason: nothing on
  // the live path decodes video. The ring buffer packetises at a 188-byte
  // stride and carries whatever it is given, so a structurally valid transport
  // stream is exactly as useful here as a real encode, costs no ffmpeg, and is
  // byte-for-byte deterministic. The Proxy stream-profile architecture 2c-2
  // implements spawns no subprocess at all, so no test in this PR needs a real
  // remuxer -- harness/asset.py's build_real_ts_asset() has no counterpart
  // here until 2c-4.
  package relaytest

  import "fmt"

  const (
  	// PacketSize is the MPEG-TS packet size.
  	PacketSize = 188

  	// SyncByte starts every transport-stream packet.
  	SyncByte = 0x47

  	// NominalByteRate is what a pacing Rate of 1.0 means, in bytes per
  	// second: 2 Mbit/s, the bitrate e2e-upstream/scripts/make-asset.sh builds
  	// its own asset at, and the figure harness/upstream.py uses.
  	NominalByteRate = 2_000_000 / 8
  )

  // SyntheticTS returns n transport-stream packets on pid, with a real
  // continuity counter and each packet's absolute index embedded in its
  // payload.
  //
  // The layout is synthetic_ts()'s, byte for byte: the sync byte, the 13-bit
  // PID split across two bytes with the payload-unit-start flag clear, then
  // 0x10 | (i % 16) -- adaptation field control 01, payload only, in the high
  // nibble and the continuity counter in the low one -- then a 184-byte
  // payload whose first four bytes are i big-endian and whose remaining 180
  // are the repeating filler (i + j) % 256.
  //
  // THE EMBEDDED INDEX IS WHY A POSITION TEST CAN WORK AT ALL. The continuity
  // counter only cycles mod 16 and the filler repeats too, so "have I seen
  // this content before" is true of every packet at some distance. PacketIndex
  // makes a packet's absolute position observable at any distance, which is
  // what the join-point test asserts on. harness/README.md's third trap has
  // the history: an elapsed-time assertion passed against a genuine mechanism
  // break, because a client's read is never throttled to production pacing.
  func SyntheticTS(n, pid int) []byte {
  	if n < 1 {
  		panic(fmt.Sprintf("relaytest: packets must be >= 1, got %d", n))
  	}
  	if pid < 0 || pid > 0x1FFF {
  		panic(fmt.Sprintf("relaytest: pid must fit in 13 bits, got %d", pid))
  	}
  	out := make([]byte, 0, n*PacketSize)
  	for i := range n {
  		out = append(out,
  			SyncByte,
  			byte((pid>>8)&0x1F),
  			byte(pid&0xFF),
  			// 0x10|byte(i%16), not byte(0x10|(i%16)). The second form is
  			// gosec G115, "integer overflow conversion int -> byte": the
  			// value is provably 16..31 and gosec cannot see the proof, but
  			// it DOES understand that byte(i%16) is bounded by the modulus.
  			// Fixed rather than suppressed -- a #nosec here would have been
  			// the smaller diff and the worse answer (Global Constraint 15).
  			0x10|byte(i%16),
  			byte(i>>24), byte(i>>16), byte(i>>8), byte(i),
  		)
  		for j := range PacketSize - 8 {
  			out = append(out, byte((i+j)%256))
  		}
  	}
  	return out
  }

  // PacketIndex reads back the index SyntheticTS embedded in one packet.
  func PacketIndex(packet []byte) int {
  	if len(packet) < 8 {
  		panic(fmt.Sprintf("relaytest: a packet is %d bytes, got %d", PacketSize, len(packet)))
  	}
  	return int(packet[4])<<24 | int(packet[5])<<16 | int(packet[6])<<8 | int(packet[7])
  }

  // AlignmentProblem reports why data is not a whole number of TS packets each
  // starting with the sync byte, or the empty string when it is.
  //
  // It returns a reason rather than calling t.Fatalf so the caller's failure
  // message names its own subject. A helper that fails on the caller's behalf
  // produces messages that all read the same, and shape 6 -- a break-check
  // must name the mechanism -- is what that costs.
  func AlignmentProblem(data []byte) string {
  	if len(data) == 0 {
  		return "no bytes at all"
  	}
  	if len(data)%PacketSize != 0 {
  		return fmt.Sprintf("%d bytes is not a whole number of %d-byte packets", len(data), PacketSize)
  	}
  	for offset := 0; offset < len(data); offset += PacketSize {
  		if data[offset] != SyncByte {
  			// %#02x, not %#04x: Go counts the "0x" prefix OUTSIDE the width
  			// where Python counts it inside, so %#04x prints 0x0000 here and
  			// the Python harness's own %#04x prints 0x00. Matching the Python
  			// message matters because both suites' failures are read together.
  			return fmt.Sprintf("byte %d is %#02x, not the sync byte %#02x", offset, data[offset], SyncByte)
  		}
  	}
  	return ""
  }
  ```

- [ ] **Step 2: Regenerate the cross-implementation digest from Python, on your own tree**

  Do not trust this plan's literal — regenerate it, because it is the test's entire oracle and the whole point is that it comes from the *other* implementation.

  ```bash
  cd <your worktree> && python3 -c "
  import hashlib, sys
  sys.path.insert(0, '.')
  from apps.proxy.live_proxy.tests.harness.asset import synthetic_ts
  d = synthetic_ts(packets=512, pid=0x100)
  print(len(d), hashlib.sha256(d).hexdigest())
  "
  ```

  `harness/asset.py` imports nothing outside the standard library at module scope, so this runs without Django and without the container. On 2026-09-13 against `315b02a4` it printed:

  ```
  96256 e565411f3bbe6d0ab88a4dcd45d9e2a9ca1f65e049846dc5f61a2ec162f57f89
  ```

  **If your output differs, your output governs** — and report it, because `synthetic_ts` changing shape would mean the Python harness's own tests moved.

  This digest is a SHA-256 of public synthetic data and is **not** a gitleaks concern (2c-1's five HMAC vectors needed `.gitleaks.toml` entries because they match `generic-api-key`; a hex digest in a `const want = ...` next to the word `hash` does not match that rule — confirm with the command in 2c-1 Task 4 Step 1 if you want certainty, but do not add an allowlist entry pre-emptively).

- [ ] **Step 3: Write `relay/internal/relaytest/asset_test.go`**

  ```go
  package relaytest

  import (
  	"crypto/sha256"
  	"encoding/hex"
  	"testing"
  )

  // THE CROSS-IMPLEMENTATION PIN. This digest was produced by the PYTHON
  // harness's synthetic_ts() -- apps/proxy/live_proxy/tests/harness/asset.py --
  // not by the Go above it, so it proves the two implementations agree rather
  // than that this one is deterministic (hollow shape 1). Regenerate it with
  // the command in this PR's Task 2 Step 2, never by running the Go.
  //
  // It is what makes a differential test possible at all: drive the Python
  // relay and the Go relay from the same bytes and compare what each client
  // receives.
  func TestSyntheticTSMatchesThePythonHarness(t *testing.T) {
  	const want = "e565411f3bbe6d0ab88a4dcd45d9e2a9ca1f65e049846dc5f61a2ec162f57f89"
  	data := SyntheticTS(512, 0x100)
  	if len(data) != 96256 {
  		t.Fatalf("SyntheticTS(512, 0x100) is %d bytes, want 96256", len(data))
  	}
  	sum := sha256.Sum256(data)
  	if got := hex.EncodeToString(sum[:]); got != want {
  		t.Fatalf("SyntheticTS(512, 0x100) hashes to %s, want %s -- the Go asset has "+
  			"diverged from harness/asset.py's synthetic_ts()", got, want)
  	}
  }

  func TestPacketIndexReadsBackEveryPosition(t *testing.T) {
  	data := SyntheticTS(40, 0x100)
  	for i := range 40 {
  		packet := data[i*PacketSize : (i+1)*PacketSize]
  		if got := PacketIndex(packet); got != i {
  			t.Fatalf("packet %d reports index %d", i, got)
  		}
  	}
  }

  func TestAlignmentProblemNamesWhatIsWrong(t *testing.T) {
  	for _, tc := range []struct {
  		name string
  		data []byte
  		want string
  	}{
  		{"a whole asset", SyntheticTS(3, 0x100), ""},
  		{"nothing at all", nil, "no bytes at all"},
  		{
  			"a truncated packet",
  			SyntheticTS(2, 0x100)[:300],
  			"300 bytes is not a whole number of 188-byte packets",
  		},
  		{
  			"a lost sync byte",
  			append(append([]byte{}, SyntheticTS(1, 0x100)...), corrupted(SyntheticTS(1, 0x100))...),
  			"byte 188 is 0x00, not the sync byte 0x47",
  		},
  	} {
  		if got := AlignmentProblem(tc.data); got != tc.want {
  			t.Errorf("%s: AlignmentProblem = %q, want %q", tc.name, got, tc.want)
  		}
  	}
  }

  func corrupted(packet []byte) []byte {
  	out := append([]byte(nil), packet...)
  	out[0] = 0x00
  	return out
  }
  ```

- [ ] **Step 4: Break-check, two edits**

  1. Change the continuity-counter byte from `0x10|byte(i%16)` to `byte(i%16)` — the adaptation-field-control nibble lost. Expect `TestSyntheticTSMatchesThePythonHarness` to fail with a different digest. This is the check that proves the pin is doing work: nothing else in this package would notice.
  2. Change `%#02x` back to `%#04x` in `AlignmentProblem`. Expect `TestAlignmentProblemNamesWhatIsWrong` to fail with `AlignmentProblem = "byte 188 is 0x0000, ..."`. **This break-check is a real defect caught while writing this plan**, not a hypothetical: the first draft used `%#04x` by analogy with the Python and produced a message four characters wrong.

- [ ] **Step 5: Run the four checks and commit**

---
## Task 3: `relay/internal/relaytest` — the fake provider and the fake Django

Two HTTP servers a test drives real client code against. Neither is a *subject*: they are the sink and the source the subject sits between, which is what makes injecting them observing rather than blinding (hollow shape 4).

- [ ] **Step 1: Write `relay/internal/relaytest/upstream.go`**

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
  // packets, harness/upstream.py's _WRITE_CHUNK.
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
  	// 0 -- shared with the Celery broker and the Django cache -- to 2.17 GB
  	// in 50 seconds, taking the test process down. Spec D2 deletes that
  	// failure mode: the Go ring is bounded at MaxBytesPerChannel per channel
  	// by construction, so an unpaced upstream costs a bounded 73 MiB and a
  	// much faster test. Set Rate when the test's subject is throughput.
  	Rate float64

  	// StopAfterBytes ends the response after this many bytes. Zero means the
  	// loop runs until the client goes away.
  	StopAfterBytes int

  	// Abrupt makes StopAfterBytes abort the response rather than end it
  	// cleanly, so the reader sees a broken connection instead of EOF.
  	Abrupt bool

  	// DeadAir sends the 200 and the headers, then nothing at all for this
  	// long -- exactly what a provider that stops producing looks like from
  	// the relay's side. The failover trigger that acts on it is 2c-5's; this
  	// PR only needs to not hang forever on one.
  	DeadAir time.Duration
  }

  // Upstream is a looping TS provider on 127.0.0.1.
  type Upstream struct {
  	server *httptest.Server

  	mu       sync.Mutex
  	requests int
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
  		u.mu.Unlock()
  		u.serve(w, r, cfg, payload)
  	}))
  	return u
  }

  // URL is the upstream's stream URL.
  func (u *Upstream) URL() string { return u.server.URL + "/live.ts" }

  // Requests is how many HTTP requests the upstream has answered -- the count
  // a "N clients share exactly one upstream connection" assertion reads
  // (parity-matrix row 10, 2c-3's).
  func (u *Upstream) Requests() int {
  	u.mu.Lock()
  	defer u.mu.Unlock()
  	return u.requests
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

  		want := WriteChunk
  		if cfg.StopAfterBytes > 0 && cfg.StopAfterBytes-sent < want {
  			want = cfg.StopAfterBytes - sent
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
  			if wait := time.Until(due); wait > 0 {
  				time.Sleep(min(wait, 250*time.Millisecond))
  			}
  		}
  	}
  }
  ```

  **What this deliberately does not have.** `harness/faults.py` ports twelve injectable faults from the e2e provider image; five of them are here (`Status`, `StopAfterBytes`, `Abrupt`, `DeadAir`, `Rate`). The rest — the redirect chain, the non-TS body, the auth failure, the connection limit — belong with 2c-5's failover triggers and 2c-8's Redirect work, and each is a field on this struct when its PR needs it. A fault with no test is a fault nobody has checked behaves like the provider.

- [ ] **Step 2: Write `relay/internal/relaytest/controlplane.go`**

  ```go
  package relaytest

  import (
  	"encoding/json"
  	"net/http"
  	"net/http/httptest"
  	"sync"
  )

  // EffectiveProxySettings is what Amendment A1.4 makes Django send on every
  // next-source answer: the seven stored CoreSettings keys, plus TSConfig's
  // class-attribute defaults under their own SCREAMING_CASE names.
  //
  // The values here are typed from apps/proxy/config.py BY HAND, and the
  // Python side asserts the same literals independently (A1.4's value test).
  // Deriving them from anything would make this fixture agree with a wrong
  // wire format.
  //
  // ONLY THE KEYS A GO TEST NEEDS ARE PRESENT, and that is deliberate: a
  // fixture carrying all thirty-eight would make an "every key is required"
  // assertion pass for the wrong reason, because with everything present a
  // test cannot show that an ABSENT key fails. Add a key here when a Go
  // consumer starts reading it.
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
  		"BUFFER_CHUNK_SIZE":      255868, // apps/proxy/config.py:15, 188 * 1361
  		"CHUNK_SIZE":             8192,   // :7
  		"STREAM_TIMEOUT":         20,     // :103
  		"FAILOVER_GRACE_PERIOD":  20,     // :120
  		"KEEPALIVE_INTERVAL":     0.5,    // :97
  		"MAX_KEEPALIVE_DURATION": 300,    // :122
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
  }

  // ControlPlane is a fake Django answering POST /api/relay/... .
  type ControlPlane struct {
  	server *httptest.Server

  	mu       sync.Mutex
  	requests []RecordedRequest
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

  		settings := cfg.Settings
  		if settings == nil {
  			settings = EffectiveProxySettings()
  		}
  		kind := cfg.Kind
  		if kind == "" {
  			kind = "proxy"
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
  				"stream_id":        1,
  				"url":              cfg.SourceURL,
  				"user_agent":       "relaytest/1.0",
  				"transcode":        false,
  				"m3u_profile_id":   1,
  				"slot_reserved":    true,
  				"channel_name":     "Test Channel",
  				"stream_name":      "Test Stream",
  				"m3u_profile_name": "Test Profile",
  				"stream_profile": map[string]any{
  					"id": 1, "command": "", "args": "", "kind": kind,
  				},
  				"ffmpeg_stream_profile": nil,
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

  **`transcode` is hard-wired to `false` on every generated source, including when `Kind` is `"transcode"`.** That is not an oversight, it is the fixture's most useful property: it makes a relay that branched on `transcode` instead of `kind` serve a Redirect or transcode channel through the Proxy path, which is exactly the defect 2c-1's Finding F1 added `kind` to prevent, and it is what Task 8's `TestATuneRefusesAKindItDoesNotServe` detects.

- [ ] **Step 3: Run the four checks and commit**

  These two files have no tests of their own beyond Task 2's asset tests. They are exercised by every later task, which is the right place for their coverage: a test of a fake is a test of a fake.

---

## Task 4: `relay/buffer` — the ring

The core of the PR. Parity-matrix rows **7** and **9** are pinned here, and row **8**'s mechanism ships here with its pin deferred to 2c-3 (Ruling R3).

- [ ] **Step 1: Give `ChunksForBytes` a shared implementation**

  In `relay/buffer/buffer.go`, replace the body of 2c-1's `ChunksForBytes` and add the helper the ring uses:

  ```go
  // ChunksForBytes converts a byte budget to a whole number of chunks at the
  // default chunk size.
  func ChunksForBytes(budget int) int {
  	return chunksFor(budget, ChunkBytes)
  }

  // chunksFor is the one implementation, so a ring sized from a chunk size the
  // control plane sent and one sized from the constant can never round
  // differently. A budget below one chunk still yields one, because a
  // zero-length ring would deadlock the writer.
  func chunksFor(budget, chunkBytes int) int {
  	if chunkBytes <= 0 || budget < chunkBytes {
  		return 1
  	}
  	return budget / chunkBytes
  }
  ```

  2c-1's `TestChunksForBytes` table must still pass unchanged. If it does not, the refactor is wrong, not the test.

- [ ] **Step 2: Write `relay/buffer/ring.go`**

  ```go
  package buffer

  import (
  	"context"
  	"errors"
  	"sync"
  	"time"
  )

  // ErrClosed is returned by Write and Wait once the ring has been closed. A
  // named sentinel rather than a message: callers test the condition with
  // errors.Is, and a substring check on an error string pins nothing when more
  // than one site can produce the text (hollow shape 5).
  var ErrClosed = errors.New("buffer: ring is closed")

  // Chunk is one published unit of the ring.
  //
  // Data is IMMUTABLE once a Chunk is published and its backing array is never
  // reused for a later chunk. That is what makes fan-out to N clients N slice
  // headers over one backing array with no refcounting and no copy per client
  // (spec D2). A reader may hold Data after the chunk has been evicted; the
  // garbage collector keeps the array alive exactly as long as someone holds
  // it.
  type Chunk struct {
  	// Index is the chunk's position in the channel's monotonic sequence. The
  	// first chunk a channel ever publishes is 1, matching Redis INCR on a
  	// missing key (apps/proxy/live_proxy/input/buffer.py:103).
  	Index uint64

  	// At is when the chunk was published, the Go equivalent of the
  	// chunk_timestamps sorted set (input/buffer.py:109).
  	At time.Time

  	// Data is a whole number of 188-byte TS packets.
  	Data []byte
  }

  // Config is what New needs. Every field has a working zero value except
  // BudgetBytes, which is required, because a ring sized by accident is a ring
  // nobody chose the memory profile of.
  type Config struct {
  	// BudgetBytes is the per-channel memory bound, converted to a chunk count
  	// by chunksFor. MaxBytesPerChannel is the deployment default.
  	BudgetBytes int

  	// ChunkBytes is the ring's write unit. Zero means the ChunkBytes
  	// constant.
  	//
  	// Configurable from 2c-2 onwards because Amendment A1.4 puts
  	// BUFFER_CHUNK_SIZE on the wire: the control plane sends the effective
  	// value and the relay uses it, so the constant stops being an operative
  	// copy of a Python literal and becomes only the derivation input
  	// MaxChunksPerChannel is computed from. The two are pinned to the same
  	// number from both sides -- 2c-1's TestConstantsMatchThePythonSource
  	// asserts the constant is 255868, and A1.4's value test asserts the wire
  	// carries 188 * 1361.
  	ChunkBytes int

  	// Retention is the age bound. Zero means RetentionSeconds.
  	Retention time.Duration

  	// Now is the clock, injectable so the join-point and retention tests do
  	// not sleep. Nil means time.Now.
  	Now func() time.Time
  }

  // Ring is one channel's in-memory buffer: the packetiser, the monotonic
  // chunk index, the bounded chunk store and the reader wake-up.
  //
  // CONCURRENCY. One writer goroutine calls Write, ResetPosition and Close; any
  // number of reader goroutines call Read, Head, Join, Oldest and Wait. Every
  // field below is guarded by mu -- writers take Lock, readers take RLock. The
  // only thing that leaves the lock is a Chunk's Data slice header, which is
  // safe precisely because of the immutability rule on Chunk.
  //
  // WHAT -race SHOULD CATCH IF THIS IS WRONG. Reading head, chunks or notify
  // without the lock is an unsynchronised access the detector reports directly,
  // with both stacks. It does NOT catch the immutability rule on its own -- a
  // writer reusing a published backing array only races when a reader happens
  // to be reading that array at that instant -- which is why
  // TestAPublishedChunkIsNeverRewritten asserts content rather than relying on
  // the detector (Ruling R7).
  type Ring struct {
  	capacity   int
  	chunkBytes int
  	retention  time.Duration
  	now        func() time.Time

  	mu sync.RWMutex
  	// chunks is the store, oldest first. Its length never exceeds capacity.
  	chunks []Chunk
  	// head is the highest index ever published. It is MONOTONIC FOR THE
  	// CHANNEL'S LIFE and ResetPosition deliberately does not touch it
  	// (parity-matrix row 7).
  	head uint64
  	// partial is the tail of the byte stream that is not yet a whole
  	// 188-byte packet, carried into the next Write (row 9).
  	partial []byte
  	// pending is whole packets accumulated but not yet a full chunk.
  	pending []byte
  	// notify is closed and replaced on every publish, so a reader can wait
  	// on it inside a select alongside its own context. A sync.Cond cannot be
  	// selected on, so a reader blocked in Cond.Wait could not be woken by a
  	// client disconnecting -- a goroutine leak per abandoned tune.
  	notify chan struct{}
  	closed bool
  }

  // New builds a ring. BudgetBytes below one chunk still yields a one-chunk
  // ring, because a zero-length ring would deadlock the writer.
  func New(cfg Config) *Ring {
  	retention := cfg.Retention
  	if retention <= 0 {
  		retention = RetentionSeconds * time.Second
  	}
  	now := cfg.Now
  	if now == nil {
  		now = time.Now
  	}
  	chunkBytes := cfg.ChunkBytes
  	if chunkBytes <= 0 {
  		chunkBytes = ChunkBytes
  	}
  	capacity := chunksFor(cfg.BudgetBytes, chunkBytes)
  	return &Ring{
  		capacity:   capacity,
  		chunkBytes: chunkBytes,
  		retention:  retention,
  		now:        now,
  		chunks:     make([]Chunk, 0, capacity),
  		notify:     make(chan struct{}),
  	}
  }

  // Write packetises p and publishes whole chunks. It implements io.Writer so
  // the upstream reader is a copy into the ring.
  //
  // THE PACKETISATION IS A STRIDE, NOT A SYNC-BYTE SEARCH, and that is parity,
  // not an oversight. input/buffer.py:79-91 takes the largest multiple of 188
  // in (carried partial + new data) and carries the remainder forward; it never
  // scans for 0x47. A Go implementation that searched for the sync byte would
  // resynchronise a stream Python passes through unchanged, which is a
  // divergence a client can see. Do not "improve" this.
  func (r *Ring) Write(p []byte) (int, error) {
  	if len(p) == 0 {
  		return 0, nil
  	}

  	r.mu.Lock()
  	defer r.mu.Unlock()
  	if r.closed {
  		return 0, ErrClosed
  	}

  	// The carry is the accumulator: r.partial's own array is extended, then
  	// immediately replaced below, so no reader ever sees an intermediate
  	// state.
  	combined := append(r.partial, p...)
  	complete := (len(combined) / TSPacketSize) * TSPacketSize
  	if complete == 0 {
  		r.partial = combined
  		return len(p), nil
  	}
  	r.pending = append(r.pending, combined[:complete]...)
  	// Copy rather than reslice: combined's backing array is r.partial's, and
  	// holding a tail of it would pin the whole accumulated buffer alive for
  	// as long as the partial packet lives.
  	r.partial = append(make([]byte, 0, TSPacketSize), combined[complete:]...)

  	published := false
  	for len(r.pending) >= r.chunkBytes {
  		// A fresh allocation per chunk. Reusing one array across chunks would
  		// corrupt every reader already holding the previous chunk, silently.
  		data := make([]byte, r.chunkBytes)
  		copy(data, r.pending[:r.chunkBytes])
  		r.pending = append(r.pending[:0], r.pending[r.chunkBytes:]...)

  		r.head++
  		r.evictLocked()
  		r.chunks = append(r.chunks, Chunk{Index: r.head, At: r.now(), Data: data})
  		published = true
  	}

  	if published {
  		close(r.notify)
  		r.notify = make(chan struct{})
  	}
  	return len(p), nil
  }

  // evictLocked drops chunks until there is room for one more, under BOTH
  // bounds, whichever binds first (2c-1's Ruling R2). Callers hold mu.
  //
  // The age bound runs only here, on a write. A channel with no writer for
  // longer than Retention therefore keeps its last chunks where Redis's TTL
  // would have expired them -- a stated divergence, and an unreachable one: a
  // channel with no writer is a channel being torn down, its ring is closed
  // with it, and nothing joins one.
  func (r *Ring) evictLocked() {
  	cutoff := r.now().Add(-r.retention)
  	for len(r.chunks) > 0 && r.chunks[0].At.Before(cutoff) {
  		r.chunks = append(r.chunks[:0], r.chunks[1:]...)
  	}
  	for len(r.chunks) >= r.capacity {
  		r.chunks = append(r.chunks[:0], r.chunks[1:]...)
  	}
  }

  // ResetPosition clears the packetiser for a clean stream transition, exactly
  // as input/buffer.py:136-168 does on a failover: the carried partial packet
  // and the not-yet-published bytes go, so the old upstream's trailing bytes
  // are never concatenated with the new upstream's first ones into a corrupt
  // packet that breaks audio decoder sync in the client.
  //
  // It does NOT touch head, and that omission is the behaviour parity-matrix
  // row 7 pins: the chunk index is monotonic for the channel's life, which is
  // why a stream switch does not disturb a connected client.
  //
  // Nothing in this PR calls it -- the switch that does is 2c-5's -- and it
  // ships here anyway because row 7 is 2c-2's to close and the row is about
  // this function's omission.
  func (r *Ring) ResetPosition() {
  	r.mu.Lock()
  	defer r.mu.Unlock()
  	r.partial = nil
  	r.pending = nil
  }

  // Head is the highest index published so far, 0 before the first chunk.
  func (r *Ring) Head() uint64 {
  	r.mu.RLock()
  	defer r.mu.RUnlock()
  	return r.head
  }

  // Oldest is the lowest index still resident, and false when the ring is
  // empty.
  func (r *Ring) Oldest() (uint64, bool) {
  	r.mu.RLock()
  	defer r.mu.RUnlock()
  	if len(r.chunks) == 0 {
  		return 0, false
  	}
  	return r.chunks[0].Index, true
  }

  // Read returns every resident chunk after cursor.
  //
  // cursor is the LAST CONSUMED index, Python's local_index convention
  // (output/ts/generator.py), so the first chunk returned is cursor+1 when it
  // is still resident. next is the cursor to pass to the following call, and
  // skipped is how many indices were lost to eviction before the first chunk
  // returned -- the in-memory equivalent of find_oldest_available_chunk's jump
  // (input/buffer.py:407-452), reported rather than silently absorbed so a
  // caller can log a real gap.
  //
  // Python's get_optimized_client_data batching (3..20 chunks, a 1 MB target
  // and a 2 MB cap, input/buffer.py:302-372) is deliberately NOT ported: it
  // amortises a Redis round trip per chunk, and an in-memory ring has no round
  // trip to amortise. What a client receives is identical; only the size of
  // each write to its socket differs, which no parity row covers.
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

  	// Selected by comparing indices rather than by converting (want - oldest)
  	// to an int offset. The offset form is provably in range -- want is at
  	// least oldest and at most head -- but gosec cannot see the proof and
  	// reports G115, integer overflow conversion uint64 -> int. Suppressing it
  	// would have been the smaller diff and the worse answer: this form needs
  	// no #nosec, costs one pass over at most `capacity` slice headers, and is
  	// correct without relying on the chunks being contiguous.
  	out := make([][]byte, 0, len(r.chunks))
  	for _, c := range r.chunks {
  		if c.Index >= want {
  			out = append(out, c.Data)
  		}
  	}
  	return out, r.chunks[len(r.chunks)-1].Index, skipped
  }

  // Join returns the cursor a new client starts from, so that its first read
  // begins roughly `behind` behind live.
  //
  // It collapses three Python call sites into one function, and the collapse is
  // exact rather than approximate:
  //
  //   - find_chunk_index_by_time (input/buffer.py:479-512) asks the
  //     chunk_timestamps sorted set for the NEWEST chunk at least `behind` old
  //     and returns its index minus one.
  //   - the same function's own fallback takes the oldest chunk in the set
  //     when nothing is that old -- "the buffer is shorter than the window".
  //   - _setup_streaming (output/ts/generator.py:264-302) falls back to the
  //     live head when there is no timestamp data at all, i.e. when the ring is
  //     empty.
  //
  // The Redis version also has a branch for "the timestamps key exists but the
  // chunks have expired out from under it". A ring evicts the timestamp and the
  // chunk together, by construction, so that state cannot arise here.
  func (r *Ring) Join(behind time.Duration) uint64 {
  	r.mu.RLock()
  	defer r.mu.RUnlock()

  	if len(r.chunks) == 0 {
  		return r.head
  	}
  	cutoff := r.now().Add(-behind)
  	for i := len(r.chunks) - 1; i >= 0; i-- {
  		if !r.chunks[i].At.After(cutoff) {
  			return r.chunks[i].Index - 1
  		}
  	}
  	return r.chunks[0].Index - 1
  }

  // Wait blocks until a chunk is published, the ring closes, or ctx is done. It
  // returns ctx.Err() on cancellation, ErrClosed once the ring is closed, and
  // nil when there may be new data.
  func (r *Ring) Wait(ctx context.Context) error {
  	r.mu.RLock()
  	ch := r.notify
  	closed := r.closed
  	r.mu.RUnlock()

  	if closed {
  		return ErrClosed
  	}
  	select {
  	case <-ctx.Done():
  		return ctx.Err()
  	case <-ch:
  		return nil
  	}
  }

  // Close wakes every waiter and refuses further writes. It is idempotent.
  func (r *Ring) Close() {
  	r.mu.Lock()
  	defer r.mu.Unlock()
  	if r.closed {
  		return
  	}
  	r.closed = true
  	close(r.notify)
  }
  ```

  **Two design notes worth reading before changing anything here.**

  *Why `notify` is a closed-and-replaced channel and not a `sync.Cond`.* A reader has to wait on "new data **or** my client went away", and `sync.Cond.Wait` cannot appear in a `select`. A reader blocked in `Cond.Wait` when its viewer closes the tab would stay blocked until the next chunk — on a stalled channel, forever — which is one leaked goroutine per abandoned tune. Closing a channel is the idiomatic broadcast that composes with `context`.

  *Why `Read` returns slice headers and never copies.* That is spec D2's whole fan-out argument. It is only sound because `Chunk.Data` is never written again, which is the single invariant this package has and the one `TestAPublishedChunkIsNeverRewritten` exists for.

- [ ] **Step 3: Write `relay/buffer/ring_test.go`**

  **The complete file is Appendix A.** The table below says what each test pins and where its oracle comes from; write the bodies from the appendix rather than from the table.

  Sixteen tests, in this order:

  | Test | What it pins | Oracle |
  |---|---|---|
  | `TestWritePublishesWholePacketsInUnbrokenOrder` | **row 9** — the 188-byte stride and the carry | `relaytest.PacketIndex`, written by the fixture, read by nothing under test |
  | `TestAPartialPacketIsCarriedIntoTheNextWrite` | the carry at its exact boundary: 187 bytes publishes nothing, the 188th completes it | `Head()` and `AlignmentProblem` |
  | `TestAPublishedChunkIsNeverRewritten` | D2's immutability rule (Ruling R7) | a byte-for-byte snapshot taken before twenty evicting writes |
  | `TestResetPositionDoesNotRewindTheChunkIndex` | **row 7** — monotonic for the channel's life | `Head()` before and after, and one more write |
  | `TestResetPositionDropsTheCarriedPartialPacket` | the other half of `reset_buffer_position` | the PID of the first delivered packet |
  | `TestJoinStartsRoughlyBehindLive` | **row 8's mechanism** (pin deferred, R3) | an injected clock, six chunks one second apart |
  | `TestJoinFallsBackToTheOldestChunkWhenTheBufferIsShort` | `find_chunk_index_by_time`'s own fallback | an injected clock, a 0.3s buffer, a 30s request |
  | `TestJoinOnAnEmptyRingStartsAtTheHead` | `_setup_streaming`'s last resort | — |
  | `TestReadReportsWhatEvictionSkipped` | the jump `find_oldest_available_chunk` performs, reported not absorbed | `Oldest()` |
  | `TestTheRingNeverExceedsItsCapacity` | the byte cap binds | fifty writes into an eight-chunk ring |
  | `TestRetentionEvictsBeforeTheRingIsFull` | the age bound binds **independently** | an injected clock, one chunk, ten seconds, one more chunk |
  | `TestCapacityUsesTheConfiguredChunkSize` | A1.4's payoff: the wire value sizes the ring, not the constant | a chunk size a quarter of the default, so 16 is a count the default could not produce |
  | `TestWaitWakesOnAPublish` / `OnClose` / `WhenTheClientGoesAway` | the wake-up, in all three directions | a goroutine and a two-second deadline |
  | `TestConcurrentReadersAndOneWriter` | the lock discipline | **`-race` is the oracle**: four readers, 200 writes |

  The file's own fixtures:

  ```go
  // A small ring, so a test reaches eviction in a few kilobytes instead of 73
  // megabytes. The chunk size is a whole number of packets, as the real one is.
  const (
  	testChunk  = TSPacketSize * 4 // 752 bytes
  	testBudget = testChunk * 8    // eight chunks
  )

  func newTestRing(t *testing.T, now func() time.Time) *Ring {
  	t.Helper()
  	return New(Config{BudgetBytes: testBudget, ChunkBytes: testChunk, Now: now})
  }

  // A clock a test drives by hand, so the join-point and retention tests assert
  // on time without spending any. Guarded because the concurrency test reads it
  // from four goroutines at once.
  type fakeClock struct {
  	mu sync.Mutex
  	at time.Time
  }

  func (c *fakeClock) now() time.Time {
  	c.mu.Lock()
  	defer c.mu.Unlock()
  	return c.at
  }

  func (c *fakeClock) advance(d time.Duration) {
  	c.mu.Lock()
  	defer c.mu.Unlock()
  	c.at = c.at.Add(d)
  }

  // drain reads everything resident from cursor and concatenates it.
  func drain(r *Ring, cursor uint64) ([]byte, uint64) {
  	chunks, next, _ := r.Read(cursor)
  	var out []byte
  	for _, c := range chunks {
  		out = append(out, c...)
  	}
  	return out, next
  }
  ```

  Two arithmetic facts every test in this file depends on, both verified:
  - Twenty-eight packets is seven chunks at `testChunk`, **inside** the eight-chunk ring, so nothing is evicted and the delivered stream can be compared against the source from packet zero. A first draft of the alignment test used two hundred packets and failed with `packet at byte 0 carries index 168` — the ring had evicted forty-two chunks. **If a test asserts against packet zero, it must fit in the ring.**
  - `TestReadReportsWhatEvictionSkipped` writes twelve chunks into an eight-chunk ring, so residents are 5..12, `Oldest()` is 5, `skipped` is 4 and `next` is 12.

  And the join-point arithmetic, which the test states in its own message: six chunks published at t+0..t+5 with the clock then at t+6; three seconds back is t+3; the newest chunk at or before t+3 is chunk 4; `Join` returns one before it, so **3**.

- [ ] **Step 4: Break-check, seven edits**

  Every one of these was run against this plan's own code. The expected message is what you must see.

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | `r.partial = append(...)` becomes `r.partial = nil` | `TestWritePublishesWholePacketsInUnbrokenOrder` | `the delivered stream is not whole TS packets: byte 376 is 0x01, not the sync byte 0x47` |
  | 2 | `ResetPosition` also sets `r.head = 0` | `TestResetPositionDoesNotRewindTheChunkIndex` | `head = 0 after a stream switch, want 3 -- the chunk index is monotonic for the channel's life and a switch never resets it` |
  | 3 | a `scratch []byte` field on `Ring`, allocated once and reused for every chunk | `TestAPublishedChunkIsNeverRewritten` | `byte 2 of a chunk a reader still holds changed from 0x00 to 0x01 after later writes: a published chunk's backing array was reused` |
  | 4 | `Join`'s body becomes `return r.head` | `TestJoinStartsRoughlyBehindLive` **and** `TestJoinFallsBackToTheOldestChunkWhenTheBufferIsShort` | `Join(3s) = 6, want 3 so the next read starts at chunk 4; head is 6` |
  | 5 | delete the age loop from `evictLocked` | `TestRetentionEvictsBeforeTheRingIsFull` | `oldest resident chunk is 1, want 2 -- a chunk older than the retention window survived in a ring with seven free slots` |
  | 6 | `New` ignores `cfg.ChunkBytes` | **five tests**, four of them with `no bytes at all` | the one to read is `TestCapacityUsesTheConfiguredChunkSize`: `the ring holds 4 chunks, want 16 (a 1023472-byte budget at 63967 bytes a chunk)` |
  | 7 | `Head()` drops its `RLock`/`RUnlock` | `TestConcurrentReadersAndOneWriter` | `WARNING: DATA RACE`, with both stacks |

  **Number 6 is this PR's worked instance of hollow shape 6.** The break-check reddens broadly and four of the five messages name a *symptom*, not the mechanism. Confirm you see the capacity test's message; if you only see "no bytes at all", you have not confirmed anything about the configured chunk size.

  **Number 3 is the one that will mislead you if you take a shortcut.** Allocating the scratch buffer as a local inside `Write` rather than as a field on `Ring` does **not** redden the test, because a test that writes one chunk per `Write` call never exercises reuse within a call. That happened while writing this plan. The defect shape that matters is a field, and that is what to inject.

- [ ] **Step 5: Run the four checks and commit**

---
## Task 5: `relay/control` — settings, the address, and `next-source`

Ruling R1 puts the whole of one route's disposition table here. Ruling R8 makes the settings a map. Ruling R9 makes the address resolve per call.

- [ ] **Step 1: Write `relay/control/settings.go`**

  ```go
  package control

  import (
  	"encoding/json"
  	"fmt"
  	"time"
  )

  // Settings is the next-source answer's proxy_settings object, held as raw
  // JSON keyed by name rather than as a struct.
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
  // absent key instead, for every key, including ones a later PR starts
  // reading.
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
  		return 0, fmt.Errorf("proxy_settings[%q] is not a number: %w", key, err)
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
  		return 0, fmt.Errorf("proxy_settings[%q] is not a number: %w", key, err)
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
  		return "", fmt.Errorf("proxy_settings[%q] is not a string: %w", key, err)
  	}
  	return value, nil
  }
  ```

  `String` has no caller in this PR. It ships anyway, and that is the one exception to "a field with no reader is a stale duplicate": it is a symmetric accessor on a four-method set, `DEFAULT_USER_AGENT` is the string key on the wire, and 2c-4 reads it. An unused *accessor* is not a duplicated *value*.

- [ ] **Step 2: Transcribe Django's host regex, then write `relay/control/baseurl.go`**

  The regex is the one thing here that must not be copied from this plan:

  ```bash
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python -c "
  import django.http.request as r, inspect
  print(r.host_validation_re.pattern if hasattr(r.host_validation_re, 'pattern') else r.host_validation_re)
  print(inspect.getsource(r.split_domain_port))
  "
  ```

  On 2026-09-13 the pattern this plan was written against is `^([a-z0-9.-]+|\[[a-f0-9]*:[a-f0-9.:]+\])(?::[0-9]+)?$`, applied to a lower-cased host. **Use what the command prints.** If it differs, use the printed one and say so in the PR description: this is a check against Django's own behaviour, and a regex from memory is exactly the sort of thing that is right until a Django upgrade.

  ```go
  package control

  import (
  	"fmt"
  	"net/url"
  	"os"
  	"regexp"
  	"strings"
  )

  // ErrNotConfigured is the Go counterpart of Django's ImproperlyConfigured on
  // this path. A tune that cannot resolve where Django answers fails loudly;
  // nothing falls back to a guess, because a relay talking to the wrong address
  // answers every internal call with a 403 and nothing says why.
  type ErrNotConfigured struct {
  	// Variable is the environment variable responsible, or the empty string
  	// when the deployment shape supplied the address with no variable.
  	Variable string
  	Reason   string
  }

  func (e *ErrNotConfigured) Error() string {
  	subject := e.Variable
  	if subject == "" {
  		subject = "the control-plane URL"
  	}
  	return subject + " " + e.Reason
  }

  // asError exists so every failure path reads the same and none of them
  // accidentally returns a nil *ErrNotConfigured inside a non-nil error
  // interface -- the typed-nil trap, which would make errors.As succeed on a
  // success path.
  func asError(e *ErrNotConfigured) error { return e }

  // hostValidationRe is django.http.request.host_validation_re, transcribed
  // from the Django in this deployment's own image (see this Task's Step 2 for
  // the command). It is what HttpRequest.get_host() applies BEFORE
  // ALLOWED_HOSTS, so a host it rejects -- an underscore anywhere in it,
  // notably -- reaches Django as an opaque 400 with nothing naming the cause.
  // Checking it here blames the variable instead.
  var hostValidationRe = regexp.MustCompile(`^([a-z0-9.-]+|\[[a-f0-9]*:[a-f0-9.:]+\])(?::[0-9]+)?$`)

  // BaseURL resolves where Django answers for this deployment shape: the D9
  // four-branch formula, in the order apps/proxy/internal_base_url.py's
  // resolve_base_url applies it -- explicit override, then modular by service
  // name, then dev, then AIO through nginx on DISPATCHARR_PORT.
  //
  // Resolved on every call rather than at startup, which is parity and not
  // laziness: Python resolves inside next_source() and lets ImproperlyConfigured
  // propagate, so a misconfigured deployment fails visibly on the first tune
  // while /healthz keeps answering honestly. Resolving at startup would refuse
  // to boot a relay nobody has tuned yet and take the probe down with it.
  func BaseURL() (string, error) {
  	if explicit := os.Getenv("DISPATCHARR_INTERNAL_API_BASE_URL"); explicit != "" {
  		return validate(strings.TrimRight(explicit, "/"), "DISPATCHARR_INTERNAL_API_BASE_URL")
  	}
  	switch strings.ToLower(envOr("DISPATCHARR_ENV", "aio")) {
  	case "modular":
  		host := envOr("DISPATCHARR_WEB_HOST", "web")
  		port := envOr("DISPATCHARR_PORT", "9191")
  		return validate(fmt.Sprintf("http://%s:%s", host, port), "DISPATCHARR_WEB_HOST")
  	case "dev":
  		// Hardcoded, not read from DISPATCHARR_PORT: in dev the port that
  		// answers is uWSGI's or runserver's own, and DISPATCHARR_PORT names
  		// vite's (CLAUDE.md, Commands).
  		return validate("http://127.0.0.1:5656", "")
  	default:
  		return validate("http://127.0.0.1:"+envOr("DISPATCHARR_PORT", "9191"), "")
  	}
  }

  func envOr(name, fallback string) string {
  	if value := os.Getenv(name); value != "" {
  		return value
  	}
  	return fallback
  }

  func validate(raw, variable string) (string, error) {
  	parsed, err := url.Parse(raw)
  	if err != nil {
  		return "", asError(&ErrNotConfigured{Variable: variable, Reason: "could not be parsed as a URL."})
  	}
  	if parsed.Scheme != "http" && parsed.Scheme != "https" {
  		return "", asError(&ErrNotConfigured{
  			Variable: variable,
  			Reason: "is not an http(s) URL: a scheme-less or malformed value " +
  				"has no host this client can send.",
  		})
  	}
  	// Userinfo is stripped first: what goes on the wire as the Host header is
  	// the netloc minus userinfo, so validating the raw netloc would reject a
  	// URL Django would accept.
  	host := parsed.Host
  	if at := strings.LastIndex(host, "@"); at >= 0 {
  		host = host[at+1:]
  	}
  	if !hostValidationRe.MatchString(strings.ToLower(host)) {
  		return "", asError(&ErrNotConfigured{
  			Variable: variable,
  			Reason:   "must be an http(s) URL whose host is letters, digits, dots and hyphens.",
  		})
  	}
  	return raw, nil
  }
  ```

  **The value is never in the message, even redacted.** `apps/proxy/internal_base_url.py` makes the same call and states the reason: a scheme-less string can misparse in a way that defeats redaction, so naming the variable is the only safe option. Task 5's `TestAMisconfigurationMessageNeverEchoesTheValue` asserts it.

- [ ] **Step 3: Write `relay/control/nextsource.go`**

  The types, the timeouts, the two error kinds, the client, and `post` — the disposition table in full.

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
  )

  // The three stream-profile architectures, as StreamProfileRef.Kind spells
  // them. Added to the contract by 2c-1 Task 0 (its Finding F1): `transcode`
  // alone collapses Proxy and Redirect onto the same false, and both locked
  // profiles carry an empty command, so nothing else on the wire separates
  // them.
  const (
  	KindProxy     = "proxy"
  	KindRedirect  = "redirect"
  	KindTranscode = "transcode"
  )

  // Timeouts for next-source, from spec § The contract: connect 2s, read 5s,
  // one retry at 0.1s.
  const (
  	ConnectTimeout = 2 * time.Second
  	ReadTimeout    = 5 * time.Second
  	RetryDelay     = 100 * time.Millisecond
  	attempts       = 2
  )

  // StreamProfileRef is the next-source answer's stream_profile object.
  type StreamProfileRef struct {
  	ID      int    `json:"id"`
  	Command string `json:"command"`
  	Args    string `json:"args"`
  	Kind    string `json:"kind"`
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
  // declared: 2c-7 owns Output Profiles and json.Unmarshal ignores what no
  // field names, so leaving it out now costs nothing and claims nothing.
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
  	// attempt -- a transport failure and a 5xx. It is unexported because it is
  	// this package's retry bookkeeping, not something a caller decides. Spec
  	// § Error handling per hop is explicit that the non-JSON, non-object and
  	// 3xx outcomes raise on the FIRST pass: a client built to that spec's
  	// uncorrected first draft would burn a second full (2s, 5s) budget -- up
  	// to seven extra seconds of dead air -- on a misconfigured deployment.
  	retryable bool
  }

  func (e *Unavailable) Error() string {
  	if e.Err != nil {
  		return fmt.Sprintf("control plane unavailable at %s: %s: %v", e.Path, e.Reason, e.Err)
  	}
  	return fmt.Sprintf("control plane unavailable at %s: %s", e.Path, e.Reason)
  }

  func (e *Unavailable) Unwrap() error { return e.Err }

  // Refused is a 4xx other than next-source's own 404. Deliberately NOT a
  // subclass of Unavailable: a 403 from a SECRET_KEY mismatch between the api
  // and relay roles must fail the tune loudly rather than make every failover
  // on the deployment degrade silently forever.
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
  	// HTTP is the transport. Nil means NewHTTPClient().
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
  		return nil, fmt.Errorf("encoding the next-source request: %w", err)
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
  		return nil, 0, fmt.Errorf("building the request for %s: %w", path, err)
  	}
  	request.Header.Set("Content-Type", "application/json")
  	request.Header.Set(HeaderInternal, InternalPrincipalToken(c.Secret))
  	// The bound token signs the FULL path, query string included. There is no
  	// query string on this route today; passing `path` rather than a bare
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

  **A note on the transport's timeout.** `http.Client.Timeout` is the whole-request budget, `ConnectTimeout + ReadTimeout` = 7s, which is what requests' `(2, 5)` pair costs in the worst case. It is not a per-phase split, and it does not need to be: this route's body is a few kilobytes, and the phase distinction only matters where a response is long-lived — which is the streaming path, not this one. 2c-5 inherits this client unchanged.

- [ ] **Step 4: Write `relay/control/nextsource_test.go` and `baseurl_test.go`**

  **The complete files are Appendix B (`nextsource_test.go`) and Appendix C (`baseurl_test.go`).**

  | Test | What it pins |
  |---|---|
  | `TestNextSourceReadsTheAnswer` | the happy path, including `kind` and a settings read |
  | `TestNextSourceSignsTheRequestTheWayDjangoVerifiesIt` | **the bound token, against a Python-produced literal** |
  | `TestNextSourceMapsA404ToANullSource` | the 404 is an answer, not an error |
  | `TestA403IsRefusedAndIsNotUnavailable` | `Refused` does not satisfy `errors.As(*Unavailable)`, and is not retried |
  | `TestOnlyA5xxConsumesTheRetry` | one 503 then success = **2** requests, and a source |
  | `TestA5xxOnBothAttemptsIsUnavailable` | **2** requests, then `Unavailable` |
  | `TestARedirectIsNeitherFollowedNorRetried` | **1** request at the fake, **0** at the redirect target |
  | `TestA2xxThatIsNotAJSONObjectIsUnavailableAndNotRetried` | three bodies: HTML, a list, `null`; **1** request each |
  | `TestSettingsFailLoudlyOnAnAbsentKey` | `*ErrSettingAbsent` naming the key |
  | `TestAnIntegerSettingSurvivesArrivingAsAFloat` | `20.0` reads as `20` |
  | `TestSecondsHonoursAFractionalValue` | `0.5` is 500ms |
  | `TestBaseURLFollowsTheFourBranches` | six cases, each supplying a value the branch could not produce by accident |
  | `TestBaseURLRejectsWhatDjangoWouldRefuseAsAHost` | underscore, no scheme, wrong scheme — each naming the variable |
  | `TestUserinfoIsStrippedBeforeTheHostIsChecked` | `http://user:pw@web:9191` is accepted |
  | `TestAMisconfigurationMessageNeverEchoesTheValue` | neither the password nor the rejected host is in the text |

  The bound-token test is the one to write with care, because it is the only defence against a wrong byte layout:

  ```go
  // THE BOUND TOKEN, PINNED AGAINST A PYTHON-PRODUCED LITERAL. A test that
  // recomputed the expectation with InternalRequestHeader would prove the
  // function deterministic and nothing else: it would pass with the context
  // string misspelled, the separator wrong, the body digest omitted, or
  // SHA-512 in place of SHA-256 -- every one of which 403s in production.
  //
  // The clock is injected so the timestamp is the one the literal was
  // generated at. Regenerate the literal from Django, never from the Go: the
  // generator is in the 2c-1 plan's Task 4 Step 1, and this value is one of
  // the five it prints.
  func TestNextSourceSignsTheRequestTheWayDjangoVerifiesIt(t *testing.T) {
  	const wantHeader = "v1.1789000000.5ce39464af1f52fac92ab6dd8101b289c2b9acce93d392216ac0dbcfa53a1fae"
  	const wantBody = `{"reason":"init"}`

  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
  	client := testClient(t, cp)
  	client.Now = func() time.Time { return time.Unix(1789000000, 0) }

  	// The body has to be exactly the seventeen bytes the literal was signed
  	// over, so this drives post directly rather than NextSource, whose body is
  	// a marshalled request struct.
  	if _, _, err := client.post(t.Context(), "/api/relay/channels/abc/next-source", []byte(wantBody)); err != nil {
  		t.Fatalf("post: %v", err)
  	}

  	seen := cp.Requests()
  	if len(seen) != 1 {
  		t.Fatalf("the control plane saw %d requests, want 1", len(seen))
  	}
  	if got := seen[0].Header.Get(HeaderInternalRequest); got != wantHeader {
  		t.Fatalf("%s = %s\nwant %s\n(the literal comes from apps/proxy/internal_auth.py's own "+
  			"internal_request_token under SECRET_KEY=%q)", HeaderInternalRequest, got, wantHeader, testSecret)
  	}
  	if got := seen[0].Header.Get(HeaderInternal); got != InternalPrincipalToken(testSecret) {
  		t.Fatalf("%s was not the internal-principal token", HeaderInternal)
  	}
  }
  ```

  **The literal above is 2c-1's, and it was independently reproduced by this plan's own verified `control` implementation** — `v1.1789000000.5ce39464…a1fae` for `POST /api/relay/channels/abc/next-source` with body `{"reason":"init"}` at timestamp 1789000000 under `SECRET_KEY="phase2c1-test-secret"`, alongside `relay_trust_token = 2bb01b0c…d901c` and `internal_principal = 19d4b086…ae7a`. If 2c-1's own `control/token_test.go` carries a different value, **that** value governs and you should stop and report, because the two implementations would disagree.

  Note this test reaches `client.post`, an unexported method, which is legal from a test in the same package and is deliberate: `NextSource` marshals its own body, so there is no way to make it produce exactly the seventeen signed bytes.

- [ ] **Step 5: Break-check, five edits**

  1. In `InternalRequestHeader`'s message, change the separator from `"\n"` to `"|"`. Expect `TestNextSourceSignsTheRequestTheWayDjangoVerifiesIt` to fail with a different digest. (If 2c-1's own test already covers this, run both and confirm both redden — two tests on one property is not waste when the property is "every internal call 403s".)
  2. Make `Refused` embed `*Unavailable`. Expect `TestA403IsRefusedAndIsNotUnavailable` to fail with `a 403 satisfied errors.As(*Unavailable): the degraded fallback would swallow it`.
  3. Set `retryable: true` on the 3xx branch. Expect `TestARedirectIsNeitherFollowedNorRetried` to fail with `the control plane saw 2 requests, want 1 -- a 3xx raises on the first pass`.
  4. Drop `CheckRedirect` from `NewHTTPClient`. Expect `TestARedirectIsNeitherFollowedNorRetried` to fail with `the redirect target saw 1 requests: the signed internal headers were forwarded`. **This is the security-relevant one**; confirm the message you get is that one and not the request-count one.
  5. Change `BaseURL`'s dev branch to read `DISPATCHARR_PORT`. Expect `TestBaseURLFollowsTheFourBranches/dev names the application port and ignores DISPATCHARR_PORT` to fail with `BaseURL = "http://127.0.0.1:8888", want "http://127.0.0.1:5656"`. The subtest sets that variable to 8888 precisely so this edit is visible (hollow shape 2).

- [ ] **Step 6: Run the four checks and commit**

---

## Task 6: `relay/channel` — the state vocabulary, the tuning, and the Proxy source

- [ ] **Step 1: Write `relay/channel/state.go`**

  ```go
  package channel

  // State is a channel's lifecycle state, spelled exactly as
  // apps/proxy/live_proxy/constants.py's ChannelState spells it, because these
  // strings reach a client through the status endpoints' `state` field and a
  // rename is a wire change.
  //
  // The full Python vocabulary is eight values. Four of them belong to
  // behaviour later PRs bring: Connecting is set by the transcode path (2c-4),
  // Buffering only ever by the ffmpeg stderr reader (2c-4, and parity-matrix
  // row 29 pins that the Proxy architecture never enters it), and Stopping by
  // the coordinated teardown (2c-8). They are declared here anyway, so the
  // vocabulary has one home and a later PR adds a transition rather than a
  // constant.
  type State string

  // The eight states. Only Initializing, WaitingForClients, Active, Error,
  // Stopping and Stopped are reachable in 2c-2.
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

- [ ] **Step 2: Write `relay/channel/tuning.go`**

  ```go
  package channel

  import "time"

  // Tuning is the channel-start-time settings a channel runs on, already
  // resolved from the control plane's proxy_settings into Go types.
  //
  // A plain struct of durations and ints rather than the wire object, so this
  // package never imports the wire package: httpapi resolves proxy_settings
  // once per tune and hands the result down, and 2c-4's ffmpeg source is handed
  // the same struct. Every field names its source, because a value with no
  // named source is the second copy Amendment A1.4 exists to stop.
  //
  // THREE FIELDS, NOT SIX (Ruling R5). An earlier draft also carried a client
  // timeout, a keepalive interval and a keepalive cap. All three are 2c-5's,
  // because in Python all three are gated on a health flag only the failover
  // machinery lowers: _should_send_keepalive returns False unless
  // stream_manager.healthy is false (output/ts/generator.py:546-551) and
  // _is_timeout returns False unless the same flag is false (:592). A channel
  // this PR serves is either running or finished, so neither gate ever opens,
  // and a field with no reader is a stale duplicate of the truth waiting to
  // happen.
  type Tuning struct {
  	// ChunkBytes is the ring's write unit, from BUFFER_CHUNK_SIZE.
  	ChunkBytes int

  	// Retention is how far back the ring reaches, from redis_chunk_ttl. The
  	// key keeps its Redis-era name on the wire because D5 is strict parity and
  	// renaming a settings key is a change the settings UI can see.
  	Retention time.Duration

  	// JoinBehind is how far behind live a new client starts, from
  	// new_client_behind_seconds. Zero means start at the live head, which is
  	// what the setting's own 0 means (output/ts/generator.py:296-302).
  	JoinBehind time.Duration
  }
  ```

- [ ] **Step 3: Write `relay/channel/source_proxy.go`**

  ```go
  package channel

  import (
  	"context"
  	"errors"
  	"fmt"
  	"io"
  	"net"
  	"net/http"
  	"net/url"
  	"sync/atomic"
  	"time"
  )

  // Source produces one channel's upstream bytes.
  //
  // One method, so 2c-4's ffmpeg source drops in beside this one without either
  // knowing about the other. The ring buffer is the sink and is an io.Writer,
  // so a source never learns what a chunk is.
  type Source interface {
  	// Run copies upstream bytes into sink. It returns nil on a clean upstream
  	// EOF, ctx.Err() when the caller cancels, and a named error otherwise.
  	Run(ctx context.Context, sink io.Writer) error
  }

  // ErrUpstreamIdle is returned when the upstream sent nothing for ReadTimeout.
  //
  // 2c-2 ENDS THE TUNE ON THIS. That is not the dead-air failover trigger,
  // which is parity-matrix row 2 and 2c-5's: Python's fetch_chunk returns False
  // on a CHUNK_TIMEOUT read timeout and the main loop keeps going, and only the
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
  // parity-matrix row 29 -- therefore no ffmpeg_speed, no buffering state and
  // no buffering failover, however far below the threshold the upstream runs.
  //
  // The Python original (input/http_streamer.py) reads the response on an OS
  // thread and writes it down an O_NONBLOCK pipe, which the main loop then
  // reads with select, so that the Proxy and transcode paths share one
  // fetch_chunk(). That whole apparatus exists to keep a blocking read off the
  // gevent hub. Go's scheduler multiplexes blocking I/O onto OS threads itself,
  // so the pipe, the fcntl, the select and the second thread all go, and what
  // is left is the copy they existed to perform.
  type ProxySource struct {
  	// URL is the provider URL Django's next-source answer named.
  	URL string

  	// UserAgent goes on the request when non-empty.
  	UserAgent string

  	// ChunkSize is the read size. Zero means 8192, apps/proxy/config.py's
  	// CHUNK_SIZE, which is also HTTPStreamReader's own default.
  	ChunkSize int

  	// ConnectTimeout bounds the dial and the response headers. Zero means 5
  	// seconds, the first half of http_streamer.py:70's timeout=(5, 30).
  	ConnectTimeout time.Duration

  	// ReadTimeout bounds the gap between bytes, which is what requests' read
  	// timeout means. Zero means 30 seconds, the second half of the same pair.
  	ReadTimeout time.Duration

  	// Transport overrides the HTTP transport, for tests. Nil means one built
  	// from ConnectTimeout with no retries and a single connection, matching
  	// HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1).
  	Transport http.RoundTripper
  }

  // withoutURL strips the URL out of a *url.Error before it reaches a log.
  //
  // net/http wraps every client failure in a *url.Error whose Error() prints
  // the whole URL, and its redaction covers ONLY userinfo -- it turns
  // http://user:pw@host into http://user:***@host and leaves the path and query
  // string untouched. Provider credentials in this deployment routinely live in
  // the QUERY STRING and the PATH (a provider URL is commonly
  // .../live/<user>/<pass>/<id>.ts, and the M3U transform builds others with
  // ?username=&password=), so %w-wrapping the error as it comes would put a
  // working credential in the container log on every failed connect. What is
  // left after the strip is the transport's own message -- "dial tcp
  // 127.0.0.1:1: connect: connection refused" -- which names a host and a port
  // and no secret.
  //
  // This is the Go-side instance of the rule scripts/check_credential_logging.py
  // enforces on the Python side. There is no Go equivalent of that script yet;
  // until there is, this function and the test around it are the enforcement.
  func withoutURL(err error) error {
  	var urlErr *url.Error
  	if errors.As(err, &urlErr) && urlErr.Err != nil {
  		return urlErr.Err
  	}
  	return err
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
  // parent is done.
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
  		// answer this relay cannot use. The URL itself is NEVER in the
  		// message: it carries provider credentials.
  		return fmt.Errorf("channel: the source URL is not usable: %w", withoutURL(err))
  	}
  	if s.UserAgent != "" {
  		request.Header.Set("User-Agent", s.UserAgent)
  	}

  	client := &http.Client{Transport: s.transport()}
  	response, err := client.Do(request)
  	if err != nil {
  		return fmt.Errorf("channel: connecting to the upstream: %w", withoutURL(err))
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
  				return fmt.Errorf("channel: writing upstream bytes to the buffer: %w", writeErr)
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
  		return fmt.Errorf("channel: reading the upstream: %w", readErr)
  	}
  }
  ```

  **The `n > 0` before the error check is not optional.** `io.Reader` may return bytes *and* an error in the same call, and a loop that checked the error first would silently drop the last read of every stream that ends without a clean `Content-Length` boundary — which, given `Connection: close` on the provider side, is most of them.

- [ ] **Step 4: Write `relay/channel/source_proxy_test.go`**

  **The complete file is Appendix D.**

  | Test | What it pins |
  |---|---|
  | `TestProxySourceCopiesTheUpstreamVerbatim` | `bytes.Equal` against the whole payload, not a length |
  | `TestProxySourceSendsTheUserAgent` | the request succeeds with the header set |
  | `TestProxySourceReportsANon200` | `*ErrUpstreamStatus` carrying 403 |
  | `TestProxySourceEndsOnAnIdleUpstream` | `ErrUpstreamIdle` within 5s on a 200ms timeout against `DeadAir` |
  | `TestProxySourceAttributesACancellationToTheCaller` | `context.Canceled`, **not** `ErrUpstreamIdle` |
  | `TestAConnectFailureNeverEchoesTheProviderURL` | no credential from the path or the query in the message, and `connection refused` still present |

  The last one in full, because the choice of secret is what makes it able to fail:

  ```go
  // A provider URL is never in an error message: it carries provider
  // credentials (CLAUDE.md's credential-logging rule, enforced on the Python
  // side by scripts/check_credential_logging.py, which has no Go equivalent).
  //
  // THE CREDENTIAL IS IN THE QUERY STRING AND THE PATH, not in the userinfo,
  // and that is what makes this test able to fail. net/http redacts userinfo by
  // itself -- it prints http://user:***@host -- so a test that only checked a
  // password in the userinfo would pass against a %w-wrapped *url.Error and
  // prove nothing. The path and the query are NOT redacted, and a Dispatcharr
  // provider URL puts the credential in exactly those two places.
  func TestAConnectFailureNeverEchoesTheProviderURL(t *testing.T) {
  	const secretURL = "http://127.0.0.1:1/live/subscriber/hunter2/9.ts?token=s3cr3t"
  	err := ProxySource{URL: secretURL, ConnectTimeout: 200 * time.Millisecond}.
  		Run(t.Context(), &recordingSink{})
  	if err == nil {
  		t.Fatal("connecting to a closed port succeeded")
  	}
  	for _, secret := range []string{"hunter2", "s3cr3t", "/live/subscriber"} {
  		if strings.Contains(err.Error(), secret) {
  			t.Fatalf("the error echoes %q from the provider URL: %s", secret, err)
  		}
  	}
  	// Still useful: the transport's own reason survives the strip.
  	if !strings.Contains(err.Error(), "connection refused") {
  		t.Fatalf("the error lost the transport's reason: %s", err)
  	}
  }
  ```

  `recordingSink` is a `bytes.Buffer` behind a mutex, because the concurrent tests read it while the source writes.

- [ ] **Step 5: Break-check, three edits**

  1. `fmt.Errorf("…: %w", withoutURL(err))` becomes `%w, err`. Expect `TestAConnectFailureNeverEchoesTheProviderURL` to fail with `the error echoes "hunter2" from the provider URL: channel: connecting to the upstream: Get "http://127.0.0.1:1/live/subscriber/hunter2/9.ts?token=s3cr3t": dial tcp 127.0.0.1:1: connect: connection refused`. Verified exactly.
  2. Move the `parent.Err()` check below `idled.Load()`. Expect `TestProxySourceAttributesACancellationToTheCaller` to fail with `error = channel: upstream sent nothing within the read timeout, want context.Canceled`. (If it passes, the test's `ReadTimeout` is too long to race the cancel; that is fine and the ordering is still correct — note it and move on rather than tightening the timeout until it flakes.)
  3. Check `readErr` before writing `buf[:n]`. Expect `TestProxySourceCopiesTheUpstreamVerbatim` to fail with a short delivered length.

- [ ] **Step 6: Run the four checks and commit**

---
## Task 7: `relay/channel` — the Channel and the Manager

This is where the ownership lease is replaced rather than ported (spec D2).

- [ ] **Step 1: Write `relay/channel/channel.go`**

  2c-1's stub file already holds the package doc comment listing what this package deliberately does not contain. **Keep that comment**, move it to a `doc.go` if the type crowds it, and add:

  ```go
  // Channel is one running channel: its ring buffer, its source goroutine, its
  // client count and its state.
  //
  // There is NO OWNERSHIP LEASE here, and that is spec D2 rather than an
  // omission. One relay process per host by construction means there is never a
  // second writer to fence against, so live:channel:{id}:owner,
  // _ensure_owner_or_stop, release_ownership's non-atomic GET-compare-DELETE
  // and extend_ownership's non-atomic GET-EXPIRE are deleted rather than ported
  // -- together with the follower path and live:events:{id}, which existed only
  // to let a non-owning worker ask the owner to act.
  type Channel struct {
  	id     string
  	ring   *buffer.Ring
  	log    *slog.Logger
  	tuning Tuning

  	mu      sync.RWMutex
  	state   State
  	lastErr error
  	clients int

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
  func (c *Channel) Clients() int {
  	c.mu.RLock()
  	defer c.mu.RUnlock()
  	return c.clients
  }

  // Done is closed once the source goroutine has returned and the ring is shut.
  func (c *Channel) Done() <-chan struct{} { return c.done }

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
  func (c *Channel) run(ctx context.Context, source Source) {
  	defer close(c.done)
  	defer c.ring.Close()

  	c.setState(StateWaitingForClients, nil)
  	err := source.Run(ctx, c.ring)

  	switch {
  	case err == nil:
  		// A clean upstream EOF. Python treats this as the stream ending and
  		// the channel stopping; the failover that would try the next candidate
  		// instead is parity-matrix rows 1-3 and 2c-5's.
  		c.log.Info("upstream ended", "channel", c.id)
  		c.setState(StateStopped, nil)
  	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
  		c.log.Info("channel stopped", "channel", c.id)
  		c.setState(StateStopped, nil)
  	default:
  		// The error is logged as-is. Every error this package builds is
  		// written to carry no URL -- see withoutURL in source_proxy.go.
  		c.log.Error("upstream failed", "channel", c.id, "error", err)
  		c.setState(StateError, err)
  	}
  }

  // markActive moves a channel out of waiting_for_clients on attach. Called by
  // the manager rather than by the writer, because the writer is an io.Writer
  // and knows nothing about clients.
  func (c *Channel) markActive() {
  	c.mu.Lock()
  	defer c.mu.Unlock()
  	if c.state == StateWaitingForClients {
  		c.state = StateActive
  	}
  }

  // ensure the ring satisfies io.Writer where it is used as the sink. A
  // compile-time assertion, because the alternative failure is a confusing
  // error inside run().
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

  // Describe is a one-line state summary, for logs and for 2c-8's status routes
  // to build on.
  func (c *Channel) Describe() string {
  	return fmt.Sprintf("channel %s state=%s clients=%d head=%d",
  		c.id, c.State(), c.Clients(), c.ring.Head())
  }
  ```

- [ ] **Step 2: Write `relay/channel/manager.go`**

  ```go
  package channel

  // ErrStopping is returned by Attach when the named channel is being torn
  // down.
  var ErrStopping = errors.New("channel: the channel is stopping")

  // ManagerConfig is what a Manager needs.
  type ManagerConfig struct {
  	// BudgetBytes is each channel's ring size. Zero means
  	// buffer.MaxBytesPerChannel.
  	BudgetBytes int

  	// ShutdownDelay is how long a channel with no clients stays up, the
  	// channel_shutdown_delay setting, which defaults to 0.
  	ShutdownDelay time.Duration

  	// StopWait bounds how long Stop waits for a source goroutine.
  	StopWait time.Duration

  	// Log is the logger. Nil means slog.Default().
  	Log *slog.Logger

  	// Now is the clock handed to every ring, injectable so tests do not sleep.
  	// Nil means time.Now.
  	Now func() time.Time
  }

  // Manager owns every running channel.
  //
  // map[string]*Channel behind a mutex is the whole of what the ownership lease
  // used to buy (spec D2). Nothing here is in Redis, so nothing here can fail
  // open the three ways server.py's lease does -- _execute_redis_command
  // swallowing to None, release_ownership's non-atomic GET-compare-DELETE,
  // extend_ownership's non-atomic GET-EXPIRE.
  type Manager struct {
  	cfg ManagerConfig
  	log *slog.Logger

  	mu       sync.Mutex
  	channels map[string]*Channel
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
  	return &Manager{cfg: cfg, log: log, channels: map[string]*Channel{}}
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
  func (m *Manager) Attach(id string, start func() (Source, Tuning, error)) (*Channel, func(), error) {
  	m.mu.Lock()
  	existing, running := m.channels[id]
  	if running {
  		if existing.State() == StateStopping {
  			m.mu.Unlock()
  			return nil, nil, ErrStopping
  		}
  		existing.mu.Lock()
  		existing.clients++
  		existing.mu.Unlock()
  		m.mu.Unlock()
  		existing.markActive()
  		return existing, func() { m.release(existing) }, nil
  	}

  	// Built while the manager lock is held so two simultaneous first clients
  	// cannot both start a source. The control-plane call inside `start` runs
  	// under this lock, which is deliberate: it is bounded by next-source's own
  	// (2s, 5s) budget, and it is what makes "one upstream per channel" a
  	// property of the code rather than of the timing. Python needs a
  	// per-channel init lock plus an ownership lease plus a _channels_setting_up
  	// set to get the same guarantee across four worker processes; one process
  	// needs one mutex.
  	built, tuning, err := start()
  	if err != nil {
  		m.mu.Unlock()
  		return nil, nil, err
  	}

  	ctx, cancel := context.WithCancel(context.Background())
  	c := &Channel{
  		id: id,
  		ring: buffer.New(buffer.Config{
  			BudgetBytes: m.cfg.BudgetBytes,
  			ChunkBytes:  tuning.ChunkBytes,
  			Retention:   tuning.Retention,
  			Now:         m.cfg.Now,
  		}),
  		log:     m.log,
  		tuning:  tuning,
  		state:   StateInitializing,
  		clients: 1,
  		cancel:  cancel,
  		done:    make(chan struct{}),
  	}
  	m.channels[id] = c
  	m.mu.Unlock()

  	go c.run(ctx, built)
  	return c, func() { m.release(c) }, nil
  }

  // Get returns a running channel, or nil.
  func (m *Manager) Get(id string) *Channel {
  	m.mu.Lock()
  	defer m.mu.Unlock()
  	return m.channels[id]
  }

  // Stop tears a channel down immediately, whatever its client count.
  func (m *Manager) Stop(id string) bool {
  	m.mu.Lock()
  	c, running := m.channels[id]
  	if !running {
  		m.mu.Unlock()
  		return false
  	}
  	delete(m.channels, id)
  	m.mu.Unlock()

  	c.setState(StateStopping, nil)
  	c.stop(m.cfg.StopWait)
  	return true
  }

  // StopAll tears every channel down. The SIGTERM drain that calls it in anger
  // is 2c-8's; this exists so a test and a shutdown path have one way to do it.
  func (m *Manager) StopAll() {
  	m.mu.Lock()
  	ids := make([]string, 0, len(m.channels))
  	for id := range m.channels {
  		ids = append(ids, id)
  	}
  	m.mu.Unlock()
  	for _, id := range ids {
  		m.Stop(id)
  	}
  }

  func (m *Manager) release(c *Channel) {
  	c.mu.Lock()
  	c.clients--
  	remaining := c.clients
  	c.mu.Unlock()
  	if remaining > 0 {
  		return
  	}
  	if m.cfg.ShutdownDelay <= 0 {
  		m.Stop(c.id)
  		return
  	}
  	// The channel_shutdown_delay timer, which Python runs in the cleanup loop
  	// off last_client_disconnect (server.py:2017-2052). The re-check inside
  	// the callback is what makes a client returning within the window keep the
  	// channel, which is the setting's whole purpose.
  	time.AfterFunc(m.cfg.ShutdownDelay, func() {
  		if c.Clients() == 0 {
  			m.Stop(c.id)
  		}
  	})
  }
  ```

  **`ShutdownDelay` is wired but not supplied from the wire in this PR**, and that is deliberate: `channel_shutdown_delay` is one of the seven stored keys and reading it belongs with the teardown 2c-8 owns, where the re-check window can actually be tested against a reconnecting client. Its zero value is the deployment default (`core/models.py:726`), so the behaviour is correct today and the field is not a stale duplicate — it is a parameter with one caller supplying its documented default.

- [ ] **Step 3: Write `relay/channel/manager_test.go`**

  **The complete file is Appendix E.**

  | Test | What it pins |
  |---|---|
  | `TestTwoClientsShareOneSource` | the start function runs **once**, `Clients()` is 2, releasing the first of two keeps the channel, releasing the last stops it |
  | `TestTwoClientsMakeOneUpstreamRequest` | the same claim **as the provider sees it**: `Upstream.Requests()` is 1 |
  | `TestACleanUpstreamEndClosesTheRing` | `Done()` fires, state is `stopped`, and `Ring.Wait` no longer blocks |
  | `TestAnUpstreamFailurePutsTheChannelInError` | state is `error` and `Err()` is an `*ErrUpstreamStatus` carrying 404 |

  The first two are the same property measured at two places, and both are needed. The first counts *starts inside this process*, so it fails if `Attach` starts a second reader however it managed to; the second counts *HTTP requests at the provider*, which is what parity-matrix row 10 is actually about and what a shared-`http.Transport` bug would show up in. **Row 10 is not claimed by this PR** — it says "three clients" and that is 2c-3's — but the test belongs here with the code it exercises.

  `TestTwoClientsMakeOneUpstreamRequest` polls `ch.Ring().Head()` with a five-second deadline rather than sleeping a fixed interval, because a fixed sleep either wastes time or races the first chunk. Note the upstream is built with `Rate: 0.05` so the ring does not fill before the assertion runs.

- [ ] **Step 4: Break-check, three edits**

  1. Move the `start()` call outside the manager lock (take the lock, check, release, call `start`, re-take). Expect `TestTwoClientsShareOneSource` to stay green — the test is not concurrent — and note it. **Then** make `Attach` unconditionally call `start()` before the map lookup. Expect `the start function ran 2 times, want 1 -- the second client must not call the control plane`, and `TestTwoClientsMakeOneUpstreamRequest` to fail with `the provider saw 2 requests`. The first half of this check is worth doing: it shows you which property the test actually has (one source per channel) and which it does not (one source under concurrency), and the second is 2c-3's to add with the fan-out it needs.
  2. Delete `defer c.ring.Close()` from `run`. Expect `TestACleanUpstreamEndClosesTheRing` to fail with `the ring is still open after the source returned; every reader would block forever`.
  3. In `run`'s switch, make the `default` arm set `StateStopped`. Expect `TestAnUpstreamFailurePutsTheChannelInError` to fail with `state = "stopped" after an upstream 404, want "error"`.

- [ ] **Step 5: Run the four checks and commit**

---

## Task 8: `relay/httpapi` — the live TS handler

The tune path, end to end.

- [ ] **Step 1: Write `relay/httpapi/stream.go`**

  ```go
  package httpapi

  import (
  	"context"
  	"errors"
  	"fmt"
  	"log/slog"
  	"net/http"

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
  }

  // The proxy_settings keys this PR reads. Named constants rather than literals
  // at the call site, so a rename on the wire is one edit and a typo is a
  // compile error rather than a runtime ErrSettingAbsent.
  const (
  	settingChunkBytes = "BUFFER_CHUNK_SIZE"
  	settingRetention  = "redis_chunk_ttl"
  	settingJoinBehind = "new_client_behind_seconds"
  	settingReadSize   = "CHUNK_SIZE"
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

  	return func(w http.ResponseWriter, r *http.Request) {
  		id := channelIDFor(r, deps.Secret)
  		if id == "" {
  			http.Error(w, "no channel in the request", http.StatusBadRequest)
  			return
  		}

  		ch, release, err := deps.Channels.Attach(id, func() (channel.Source, channel.Tuning, error) {
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

  		serveClient(r.Context(), w, rc, ch, log)
  	}
  }

  // channelIDFor resolves which channel this request is for.
  //
  // X-Relay-Channel is the uuid the authorize hop resolved, and it is read ONLY
  // when X-Dispatcharr-Authorized proves nginx put it there. Without that check
  // any client could name any channel by hand and bypass whatever the hop
  // decided -- that marker is the entire reason apps/proxy/authorize.py can be
  // the only place the decision is made. An untrusted request falls back to the
  // path value, which is the dev shape: this route is dev-gated, and 2c-8
  // brings the POST /_dispatcharr/authorize-internal fallback that authorizes
  // it.
  //
  // The four other X-Relay-* headers are deliberately not read. X-Relay-Output
  // and X-Relay-Output-Format select an Output Profile and an output format,
  // and this PR serves MPEG-TS passthrough only (2c-6, 2c-7). X-Relay-Client
  // and X-Relay-Client-IP identify a client in the registry, and this PR has no
  // registry (2c-3).
  func channelIDFor(r *http.Request, secret string) string {
  	if control.IsRelayTrusted(secret, r.Header.Get(control.HeaderAuthorized)) {
  		if resolved := r.Header.Get("X-Relay-Channel"); resolved != "" {
  			return resolved
  		}
  	}
  	return r.PathValue("channelID")
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
  func startProxyTune(ctx context.Context, client *control.Client, id string) (channel.Source, channel.Tuning, error) {
  	answer, err := client.NextSource(ctx, id, control.NextSourceRequest{
  		ExcludeStreamIDs: []int{},
  		Reason:           "initial",
  	})
  	if err != nil {
  		return nil, channel.Tuning{}, err
  	}
  	if answer.Source == nil {
  		return nil, channel.Tuning{}, ErrNoSource
  	}

  	// KIND, NEVER TRANSCODE. `transcode` is false for Proxy AND for Redirect
  	// (apps/proxy/next_source.py:504), and both locked profiles carry an empty
  	// command, so a relay that branched on `transcode` would treat a Redirect
  	// channel as Proxy and stream a provider URL that should have been a 302
  	// -- silently, and to the wrong architecture. `kind` is the field 2c-1
  	// Task 0 added for exactly this, and this is its first consumer.
  	if kind := answer.Source.StreamProfile.Kind; kind != control.KindProxy {
  		return nil, channel.Tuning{}, &ErrNotProxyKind{Kind: kind}
  	}

  	tuning, readSize, err := tuningFrom(answer.ProxySettings)
  	if err != nil {
  		return nil, channel.Tuning{}, err
  	}

  	return channel.ProxySource{
  		URL:       answer.Source.URL,
  		UserAgent: answer.Source.UserAgent,
  		ChunkSize: readSize,
  	}, tuning, nil
  }

  // writeTuneFailure turns a tune error into a status. It never echoes the
  // error text to the client: a control-plane message can name a variable, and
  // a source URL carries provider credentials.
  func writeTuneFailure(w http.ResponseWriter, log *slog.Logger, id string, err error) {
  	var notProxy *ErrNotProxyKind
  	var refused *control.Refused
  	var unavailable *control.Unavailable
  	var misconfigured *control.ErrNotConfigured
  	var absent *control.ErrSettingAbsent

  	switch {
  	case errors.As(err, &notProxy):
  		log.Warn("refusing a tune for an unsupported stream profile", "channel", id, "kind", notProxy.Kind)
  		http.Error(w, "this stream profile is not served yet", http.StatusNotImplemented)
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
  // rather than scope-cutting (Ruling R5). Python sends a keepalive only when
  // _should_send_keepalive says so, and that requires the owner's
  // stream_manager.healthy to be FALSE (output/ts/generator.py:546-551);
  // _is_timeout likewise disconnects only when the same flag is false (:592).
  // Nothing lowers that flag except the health monitor and the failover
  // machinery, which are 2c-5's. The error packets at :209-250 are the other
  // half of the same story: every one of them is inside
  // _wait_for_initialization, the path a follower takes while another worker
  // elects itself owner -- deleted outright by D2, not ported, because
  // Manager.Attach starts the source before the 200 is written.
  func serveClient(
  	ctx context.Context,
  	w http.ResponseWriter,
  	rc *http.ResponseController,
  	ch *channel.Channel,
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
  			log.Warn("client fell behind the ring",
  				"channel", ch.ID(), "skipped", skipped, "head", ring.Head())
  		}
  		if len(chunks) > 0 {
  			cursor = next
  			if !writeChunks(w, rc, chunks) {
  				return
  			}
  			continue
  		}

  		err := ring.Wait(ctx)
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

  // writeChunks writes and flushes, reporting whether the client is still
  // there. A write error is an ordinary client disconnect and is not logged:
  // one line per viewer leaving would bury everything else.
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

  **The one `#nosec` in this PR.** `G705` fires on both `w.Write(data)` sites. Global Constraint 15 requires re-linting after adding it; verified, nothing else appears. Do not widen the suppression to the file or the package.

- [ ] **Step 2: Wire the real handler into `relay/httpapi/server.go` and `relay/main.go`**

  In `server.go`, `Config` gains a `Stream StreamDeps` field and the dev branch registers the handler instead of 2c-1's 501 stub:

  ```go
  	if cfg.DevRoutes {
  		s.mux.Handle("GET /proxy/ts/stream/{channelID}", StreamHandler(cfg.Stream))
  	}
  ```

  2c-1's `notImplemented` stub and its test go with it; `TestStreamRouteIsRegisteredWithTheDevFlag` is replaced by this PR's tests, and `TestStreamRouteIsUnregisteredWithoutTheDevFlag` is **kept unchanged** — it is the flag's own property and it is still true.

  In `main.go`, build the manager and the control client and hand them over:

  ```go
  	srv := &http.Server{
  		Addr: net.JoinHostPort("0.0.0.0", strconv.Itoa(cfg.Port)),
  		Handler: httpapi.New(httpapi.Config{
  			DevRoutes: cfg.DevRoutes,
  			Stream: httpapi.StreamDeps{
  				Secret:   cfg.Secret,
  				Channels: channel.NewManager(channel.ManagerConfig{}),
  				Control:  &control.Client{Secret: cfg.Secret},
  			},
  		}).Handler(),
  		ReadHeaderTimeout: 10 * time.Second,
  	}
  ```

  `ManagerConfig{}`'s zero value takes `buffer.MaxBytesPerChannel` and a 5-second stop wait; `control.Client` with no `BaseURL` resolves per call. **Keep 2c-1's `ReadHeaderTimeout` and its comment** — a read or write deadline on the whole request would be wrong for this process by construction, and that is now literally true rather than anticipatory.

- [ ] **Step 3: Write `relay/httpapi/stream_test.go`**

  A `rig` fixture stands up a whole fake deployment: a fake provider, a fake Django, this process's mux, and a real `httptest.Server` in front of it.

  ```go
  // rig is a whole relay in front of a whole fake deployment.
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
  ```

  **The complete file is Appendix F.**

  | Test | What it pins |
  |---|---|
  | `TestATuneDeliversTheProvidersBytes` | **the vertical slice**: 200, `video/mp2t`, two chunks of whole in-order TS packets, and one upstream request |
  | `TestATuneMakesOneSignedControlPlaneCall` | one call, to `.../<uuid>/next-source`, carrying both internal headers |
  | `TestATuneRefusesAKindItDoesNotServe` | `redirect` and `transcode` each get **501**, and the provider is contacted **zero** times |
  | `TestATuneRefusesIncompleteProxySettings` | a pre-A1.4 control plane gets **502** and no provider contact |
  | `TestEveryProxySettingThisRelayReadsIsRequired` | **one subtest per key**, each removing exactly that key from a complete answer |
  | `TestXRelayChannelIsIgnoredWithoutTheTrustMarker` | the tune asks about the **path** value |
  | `TestXRelayChannelIsUsedWithTheTrustMarker` | with the marker, it asks about the **header** value |
  | `TestTheStreamRouteIsUnregisteredWithoutTheDevFlag` | 404, not 501 — the route is not registered at all |
  | `TestAStreamThatEndsClosesTheClientsResponse` | the body ends rather than hanging, and every delivered byte is whole packets |

  The ordering assertion in the first test is the one to get right:

  ```go
  	// Two chunks' worth. The client is positioned five seconds behind live and
  	// the buffer is younger than that, so it starts at the oldest chunk --
  	// meaning what arrives is the head of the provider's own payload.
  	want := buffer.ChunkBytes * 2
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
  ```

  The `% 4096` is the payload looping: the upstream serves 4,096 packets on repeat, so the index sequence wraps, and an assertion that did not account for that would fail on a long read. The first packet's index is read rather than assumed, because where the client lands depends on the join point.

  **Every call to `rig.tune` needs its own `defer func() { _ = response.Body.Close() }()` at the call site.** `bodyclose` follows the helper's return value and reports at the call site; registering the close in the helper's `t.Cleanup` does not satisfy it. Found by running the linter; the alternative — excluding `bodyclose` in `_test.go` — would have been a config change with no reason behind it, and 2c-1's config deliberately excludes only `gosec` there.

- [ ] **Step 4: Break-check, four edits**

  | # | The edit | Expected red | Message |
  |---|---|---|---|
  | 1 | branch on `answer.Source.Transcode` instead of `.StreamProfile.Kind` | `TestATuneRefusesAKindItDoesNotServe`, both subtests | `a "redirect" channel tuned with 200, want 501` |
  | 2 | drop the `IsRelayTrusted` guard from `channelIDFor` | `TestXRelayChannelIsIgnoredWithoutTheTrustMarker` | `the tune asked about /api/relay/channels/from-the-header/next-source: an unverified X-Relay-Channel was believed` |
  | 3 | make one `tuningFrom` key fall back to a literal instead of returning the error | `TestEveryProxySettingThisRelayReadsIsRequired/<that key>` only | `an answer missing only "BUFFER_CHUNK_SIZE" tuned with 200, want 502 -- the relay substituted a default of its own` |
  | 4 | delete the `ErrClosed` final-read branch from `serveClient` | `TestAStreamThatEndsClosesTheClientsResponse` may stay green | see below |

  **Number 3 is this PR's second worked instance of a break-check that did not redden.** Running it against `TestATuneRefusesIncompleteProxySettings` alone — the seven-stored-keys fixture — leaves the test green, because six other keys are also missing and any one of them still fails the tune. That test proves only that *some* key is required. `TestEveryProxySettingThisRelayReadsIsRequired` exists because of it, and it is the one to run for this check.

  **Number 4 is expected to be unreliable and is listed anyway.** The final read only matters when the writer publishes between a reader's `Read` and the ring's `Close`, which is a race the test cannot force. If it stays green, say so in the PR description rather than deleting the branch: the branch is correct and the test does not cover it, which is an honest gap and not a passing test.

- [ ] **Step 5: Run the four checks, then run the whole suite three times**

  ```bash
  cd <your worktree>/relay
  for i in 1 2 3; do go test -race -count=1 ./... || echo "RUN $i FAILED"; done
  ```

  Three clean runs. This PR is the first with real concurrency and real sockets, so a test that passes once and not three times is a flake to fix now, not later. Verified clean three times against this plan's own code.

- [ ] **Step 6: Commit**

---
## Task 9: The parity matrix — rows 7 and 9 get their Go pin

Ruling R2 makes this a one-line edit per row, in the existing `Pin` cell, with no guard change.

- [ ] **Step 1: Read the two rows before editing them**

  ```bash
  cd <your worktree> && grep -n '^| 7 \|^| 9 \|^| 8 ' docs/relay-parity-matrix.md
  ```

  Row 7's `Pin` today is one Python reference, `apps/proxy/live_proxy/tests/test_relay_stream_switch.py::SwitchTests::test_a_stream_switch_never_rewinds_the_chunk_index`; row 9's is `apps/proxy/live_proxy/tests/test_relay_client_stream.py::PacketStreamTests::test_the_delivered_stream_is_whole_packets_in_unbroken_order`.

- [ ] **Step 2: Append the Go reference to each**

  Row 7's `Pin` cell becomes the existing reference, then `, ` then:

  ```
  `relay/buffer/ring_test.go::TestResetPositionDoesNotRewindTheChunkIndex`
  ```

  Row 9's becomes the existing reference, then `, ` then:

  ```
  `relay/buffer/ring_test.go::TestWritePublishesWholePacketsInUnbrokenOrder`
  ```

  **Nothing else on either line changes**, and no other line in the file changes. The guard's `parsePin` accepts a list, its `TEST_REF_RE` is global, and the only text permitted between references is a separator matching `[\s,;·—-]+` — so `, ` is fine and a word like "and" is not. `testRefProblem` then resolves each `.go` reference by looking for `^func\s+(?:\([^)]*\)\s*)?<name>\s*\(` in the named file, which means **Task 4 must be committed before this one** or the guard fails naming a file that does not exist.

  Add to each row's `Notes` cell, after the existing text: ` The Go pin is 2c-2's.`

- [ ] **Step 3: Do not touch row 8**

  Ruling R3: `Ring.Join` and its four tests ship in Task 4, and row 8's claim is about *a new client joining a channel already running for somebody else*, which is fan-out and arrives in 2c-3. Pinning it from a test where the joining client is the only client would pin a degenerate case.

  The Go tests 2c-3 should cite when it closes row 8 are `relay/buffer/ring_test.go::TestJoinStartsRoughlyBehindLive` and `::TestJoinFallsBackToTheOldestChunkWhenTheBufferIsShort`, plus whatever multi-client test 2c-3 adds. Task 10 writes that into the spec amendment so 2c-3's planner finds it.

- [ ] **Step 4: Run the guard**

  ```bash
  cd <your worktree>/e2e && npm install && npx playwright test --project=guards parity-matrix
  ```

  The `guards` project is static analysis over the repo's own source and needs no container. `npm install` may be needed in a fresh worktree. Expect seven passing checks and the summary line `parity matrix: 30 rows — N pinned, 0 owed, 2 white-box-only`.

  **`GATE_1_CLOSED` is `true`, so the guard requires the owed-row list to be empty.** Do not add an `owed:` marker for anything in this PR — it would redden a closed gate to record a note, which is exactly the trap 2c-1's Finding F2 documented. Anything this PR owes goes in the spec's PR table (Task 10).

- [ ] **Step 5: Commit**

### Design note: the cross-implementation differential test

**The question: can one test drive the Python relay and the Go relay against the same fake upstream and compare the bytes each client receives?**

**Yes, and this PR lays the whole foundation for it without building it.** The foundation is Task 2's asset: `relaytest.SyntheticTS(512, 0x100)` and `harness/asset.py`'s `synthetic_ts(packets=512, pid=0x100)` produce **byte-identical** output, 96,256 bytes hashing to `e565411f…f57f89`, and `TestSyntheticTSMatchesThePythonHarness` is what keeps that true. So the two relays can be driven from the same bytes, and `PacketIndex` makes each delivered packet's absolute position comparable on both sides.

**It is not built here, and the reason is that the comparison would be meaningless in this PR's shape, not that it is hard.** What a differential test compares is *what each client receives after the join point*, and after the join point is the only place the two can be expected to agree:

- **Before it they cannot.** The join point is time-based on both sides, so which packet a client starts at depends on how much backlog existed when it connected, which depends on the writer's pacing. Neither implementation is deterministic about that, which is exactly why `harness/README.md`'s third trap exists and why the Python row-8 test asserts a *quantity* of backlog rather than a position.
- **After it they still cannot, in this PR.** Both must deliver the same packets in the same order from the same starting index, and the Go relay's chunk size comes from the wire while the Python relay's comes from `ConfigHelper` — the same number today, by A1.4's construction, which is fine. What is not fine is that **the Go relay has one client and the Python relay has four workers**: the Python side's delivery is shaped by `get_optimized_client_data`'s 3-to-20-chunk batching and by which worker owns the channel, and the Go side's by neither. Comparing byte streams would compare those, not the behaviour.

**Where it belongs: 2c-9, as a harness test, not a Go test.** 2c-9 already owns "the parity matrix's Python test-reference column gains its Go counterpart on every row", which is the PR that has to demonstrate the two agree. By then the Go relay has fan-out (2c-3), ffmpeg (2c-4), failover (2c-5) and the full control surface (2c-8), so a differential run compares two complete implementations rather than one complete and one partial. The shape it should take, recorded in Task 10's amendment so 2c-9's planner does not have to rediscover it:

- Drive it from the **Python** side, as a `RelayHarnessTestCase` in `apps/proxy/live_proxy/tests/`, because that side already has a container, a real Redis, a real Django and `harness/relay.py`. The Go relay is a subprocess the harness starts on a spare port, exactly as `harness/standin.py` starts a scripted ffmpeg stand-in today.
- Use **one** `FakeUpstream` with `rate` set, serving `synthetic_ts()` to both, so the pacing is identical and neither relay is racing the other for bytes.
- Assert on **`packet_index()` sequences**, not on a digest of the body: "the Go client's packets are a contiguous run of the same indices the Python client's are, starting within N of each other", where N is the join-point tolerance. A digest comparison would fail on the join point alone and teach nothing.
- Keep it out of the `-race` Go suite. It needs Postgres, Redis and a compiled Go binary; it belongs in `backend-tests.yml`'s matrix, not `go-tests.yml`'s.

---

## Task 10: `CLAUDE.md`, the spec amendment, and the Done log

- [ ] **Step 1: Write Amendment A2 into the spec**

  In `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`, after Amendment A1 (which 2c-1 added), add:

  ```markdown
  #### Amendment A2 (2c-2) — four scope corrections to the nine-PR table

  **A2.1 — the `next-source` client lands in 2c-2, not 2c-5.** The 2c-5 row
  reads "control-plane client (`next-source`/`release`/`events`, both HMAC
  headers, the exact timeout table)". 2c-2's own row is the Proxy
  stream-profile architecture, and a Proxy tune begins with Django saying the
  profile *is* Proxy — the `stream_profile.kind` field Amendment A1.1 added,
  whose first consumer A1.1 itself names as 2c-2. So 2c-2 implements
  `POST /api/relay/channels/<id>/next-source` in full: both HMAC headers, the
  (2s, 5s) budget, the one retry at 0.1s, the 404 mapping, and the **complete**
  4xx/5xx/3xx/non-JSON/non-object disposition table from § Error handling per
  hop. **2c-5's row is narrowed to `release` and `events`, plus the degraded
  fallback to the channel-start-cached candidate list.** The table is
  implemented whole rather than partly on purpose: a client that treated a 403
  from a SECRET_KEY mismatch as a retryable outage is the silent-degradation
  failure that section exists to prevent.

  **A2.2 — "gets a Go column" means a Go reference in the existing `Pin` cell,
  not a sixth table column.** `e2e/tests/guards/parity-matrix.ts` finds the
  table by an exact five-name `COLUMNS` match and rejects any row that is not
  five cells; a sixth column means editing the guard and rewriting all thirty
  rows, which is the whole-file diff the matrix's own header exists to prevent.
  The guard was built for the other reading and says so — `testRefProblem`
  already resolves `.go` references, with the comment "2c-9 re-points this
  matrix at Go tests, which is why `.go` is already here" — and `parsePin`
  already accepts a list of references in one cell. **Closing a row in Go stays
  a one-line diff.** 2c-2 does this for rows 7 and 9.

  **A2.3 — row 8's mechanism ships in 2c-2; row 8's pin stays 2c-3's.**
  `Ring.Join` and its timestamps are in the ring buffer and therefore in 2c-2,
  pinned by `relay/buffer/ring_test.go::TestJoinStartsRoughlyBehindLive` and
  `::TestJoinFallsBackToTheOldestChunkWhenTheBufferIsShort`. Row 8's claim is
  about a client joining a channel **already running for somebody else**, which
  is fan-out; 2c-3 closes it and should cite those two tests alongside its own
  multi-client one.

  **A2.4 — an input for 2c-9: the cross-implementation differential test.**
  `relay/internal/relaytest.SyntheticTS(512, 0x100)` and
  `apps/proxy/live_proxy/tests/harness/asset.py`'s `synthetic_ts(packets=512,
  pid=0x100)` produce byte-identical output — 96,256 bytes hashing to
  `e565411f3bbe6d0ab88a4dcd45d9e2a9ca1f65e049846dc5f61a2ec162f57f89`, pinned
  from the Go side by `TestSyntheticTSMatchesThePythonHarness` — so the two
  relays can be driven from the same bytes and their deliveries compared by
  `packet_index()`. 2c-2 deliberately does not build the comparison: with one
  client and no fan-out on the Go side and four workers and
  `get_optimized_client_data` batching on the Python side, it would compare
  those rather than the behaviour. **Owner: 2c-9**, as a `RelayHarnessTestCase`
  on the Python side that starts the Go binary as a subprocess (the shape
  `harness/standin.py` already uses), drives both from one paced
  `FakeUpstream`, and asserts contiguous `packet_index()` runs rather than a
  body digest — a digest fails on the join point alone.

  **A2.5 — an input for 2c-5: three behaviours 2c-2 deliberately did not
  port, each because its Python guard is permanently shut in 2c-2's shape.**
  Keepalive packets (`output/ts/generator.py:387`, gated on
  `_should_send_keepalive` at `:546-551`, which needs
  `not stream_manager.healthy`), the client timeout (`_is_timeout` at
  `:583-604`, same flag), and the error TS packets (`:209-250`, all inside
  `_wait_for_initialization`, the follower path D2 deletes). 2c-5 brings the
  health flag that opens the first two gates and should add
  `ClientTimeout`, `KeepaliveInterval` and `MaxKeepalive` to
  `relay/channel.Tuning` with it; `MAX_KEEPALIVE_DURATION`,
  `KEEPALIVE_INTERVAL`, `STREAM_TIMEOUT` and `FAILOVER_GRACE_PERIOD` are all
  already on the wire after A1.4.
  ```

  Then **edit the 2c-5 row of the nine-PR table itself** (not prose beside it — 2c-1's Finding F2 established why): change "control-plane client (`next-source`/`release`/`events`, both HMAC headers, the exact timeout table)" to "the control-plane client's remaining routes (`release`, `events`; `next-source` landed in 2c-2, Amendment A2.1)".

  And add a Done log row for 2c-2.

- [ ] **Step 2: `CLAUDE.md`**

  Two edits, both short.

  In § Architecture, after the paragraph on the ring buffer's chunk size, add a sentence: the Go relay's ring is in process memory with a 300-chunk / 76,760,400-byte per-channel cap and the same 60-second retention, whichever binds first, and it takes its chunk size from the `next-source` answer rather than from a constant.

  In § Testing, after the paragraph on the subprocess harness, add: `relay/internal/relaytest` is the Go suite's counterpart, its synthetic TS asset byte-identical to `harness/asset.py`'s and pinned to it by a digest, so the two implementations can be driven from the same bytes.

  **Do not restate the whole design here.** `CLAUDE.md` is a map, and the spec and this plan are the territory.

- [ ] **Step 3: Commit**

---

## Task 11: The Redis guard, final verification and the PR description

- [ ] **Step 1: Extend `scripts/check_go_stdlib_only.sh` with the Redis check**

  Ruling R4: this is the PR where "no Redis on the live video path" stops being trivially true. Append to the script, before its final `echo`:

  ```bash
  # Spec § Stage 2c's second invariant: "The Go binary links no Redis client."
  #
  # The module-graph check above catches an IMPORTED one and nothing else. This
  # catches the shape it cannot: a Redis client written inside this module, in
  # the standard library, which is entirely possible and would satisfy every
  # other gate in this repo.
  #
  # `go list -deps` and not a text scan, and the difference is not style. The
  # invariant is about what the BINARY LINKS, and a text scan cannot tell that
  # from a comment: several files in relay/ legitimately name Redis while
  # explaining what D2 deleted, and `redis_chunk_ttl` is a settings key that is
  # on the wire and CANNOT be renamed, because D5 is strict parity and a
  # settings key is visible in the UI. A grep would need an exclusion list, and
  # an exclusion that names one string is an exclusion somebody widens.
  if go list -deps ./... | grep -qiE '(^|/)redis'; then
    echo "FAILED: ${MODULE_ROOT} links a package named for Redis." >&2
    echo "        Spec § Stage 2c: 'The Go binary links no Redis client.'" >&2
    echo "        D2 puts the ring buffer in process memory; the live path" >&2
    echo "        reaches no Redis at all, in any form." >&2
    go list -deps ./... | grep -iE '(^|/)redis' | sed 's/^/          /' >&2
    exit 1
  fi
  ```

  **The `if ...; then` form is load-bearing.** The script runs under `set -euo pipefail`, and `grep` exits 1 when it matches nothing — which is the success case here. Assigning the result to a variable instead would abort the script on success, reading as a pass in a script whose whole job is to fail loudly. An `if` condition is exempt from `set -e`, which is why the check is written as one.

  **Break-check.** A real Redis import cannot be added without a `go.sum`, which the first check already catches, so the shape to inject is a local package:

  ```bash
  cd <your worktree>/relay
  mkdir -p redisclient
  printf 'package redisclient\n\n// Dial is a stand-in.\nfunc Dial() {}\n' > redisclient/redisclient.go
  # import it from main.go with a blank identifier, then:
  cd <your worktree> && scripts/check_go_stdlib_only.sh relay
  ```

  Expect exit 1 and `github.com/D10Scot/Dispatcharr/relay/redisclient` in the listing. Verified: `go list -deps ./...` reports 219 packages on a clean tree and none matches, and reports the fake the moment it is imported. Revert both the package and the import.

- [ ] **Step 2: Confirm the scope of the diff, both directions**

  ```bash
  cd <your worktree> && git diff --stat main...HEAD
  ```

  Every file must be in the File Structure table and every table row must be in the diff. **Anything under `apps/` beyond A1.4's four files is out of scope** — if a fifth appeared, find out why before going further. Task 1 Step 7 may legitimately have touched `test_next_source_api.py` or `test_next_source_resolution.py`; that is the one allowed addition and it needs a sentence in the PR description.

- [ ] **Step 3: The full verification pass**

  ```bash
  cd <your worktree>/relay
  gofmt -l .                       # must print nothing
  go build ./...
  go vet ./...
  golangci-lint run ./...          # must print "0 issues."
  for i in 1 2 3; do go test -race -count=1 ./... || echo "RUN $i FAILED"; done
  cd <your worktree> && scripts/check_go_stdlib_only.sh relay
  ```

  Then the Python half and the guard:

  ```bash
  cd <your worktree>
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python /repo/manage.py test apps.proxy.tests --keepdb
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python /repo/manage.py test apps.proxy.live_proxy.tests --keepdb
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python /repo/manage.py test apps.channels.tests --keepdb
  cd e2e && npx playwright test --project=guards
  ```

  **If Docker or the container is down, the edit hook says so loudly and exits 0. Then say the tests did not run — do not describe the work as verified.**

- [ ] **Step 4: Run the relay by hand once**

  The only end-to-end evidence in the PR that the binary serves a stream to a client that is not a Go test. It needs no Django and no container: `relaytest` already has both fakes.

  Write `relay/cmd/deployprobe/main.go` — **and delete it before staging**, because it is a development probe and the Docker builder stage would otherwise compile it:

  ```go
  // Command deployprobe stands up a fake provider and a fake control plane so
  // the relay binary can be run by hand against something. A development
  // probe: it is not committed and the Docker builder stage does not see it.
  package main

  import (
  	"fmt"
  	"os"
  	"os/signal"
  	"syscall"

  	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
  )

  func main() {
  	up := relaytest.NewUpstream(relaytest.Config{Rate: 1.0})
  	defer up.Close()
  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: up.URL()})
  	defer cp.Close()

  	fmt.Printf("upstream:      %s\n", up.URL())
  	fmt.Printf("control plane: %s\n\n", cp.URL())
  	fmt.Printf("DISPATCHARR_SECRET_FILE=/tmp/jwt-probe \\\n")
  	fmt.Printf("DISPATCHARR_RELAY_GO_PORT=5999 \\\n")
  	fmt.Printf("DISPATCHARR_RELAY_GO_DEV_ROUTES=1 \\\n")
  	fmt.Printf("DISPATCHARR_INTERNAL_API_BASE_URL=%s \\\n", cp.URL())
  	fmt.Printf("  go run .\n")

  	sig := make(chan os.Signal, 1)
  	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
  	<-sig
  }
  ```

  `httptest` binds a random port, which is why the probe prints the command rather than the plan hard-coding one.

  ```bash
  cd <your worktree>/relay
  printf 'probe-secret\n' > /tmp/jwt-probe
  (go run ./cmd/deployprobe > /tmp/probe.out 2>&1 &)
  for i in $(seq 1 60); do
    grep -q 'control plane' /tmp/probe.out 2>/dev/null && break
    perl -e 'select(undef,undef,undef,0.2)'
  done
  cat /tmp/probe.out

  CP=$(grep 'control plane' /tmp/probe.out | awk '{print $3}')
  (DISPATCHARR_SECRET_FILE=/tmp/jwt-probe \
   DISPATCHARR_RELAY_GO_PORT=5999 \
   DISPATCHARR_RELAY_GO_DEV_ROUTES=1 \
   DISPATCHARR_INTERNAL_API_BASE_URL="$CP" \
     go run . > /tmp/relay.out 2>&1 &)
  for i in $(seq 1 80); do
    curl -fsS -o /dev/null http://127.0.0.1:5999/healthz 2>/dev/null && break
    perl -e 'select(undef,undef,undef,0.2)'
  done

  curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5999/healthz
  curl -sS -D /tmp/hdr.txt --max-time 6 http://127.0.0.1:5999/proxy/ts/stream/a-uuid -o /tmp/body.bin
  head -3 /tmp/hdr.txt
  echo "bytes: $(wc -c < /tmp/body.bin)"
  xxd /tmp/body.bin | head -2
  cat /tmp/relay.out

  pkill -f 'exe/relay'; pkill -f 'exe/deployprobe'
  rm -f /tmp/jwt-probe
  ```

  **Run against this plan's own implementation, this produced:**

  ```
  200
  HTTP/1.1 200 OK
  Cache-Control: no-cache
  Content-Type: video/mp2t
  bytes:  1279340
  00000000: 4701 0010 0000 0000 0001 0203 0405 0607  G...............
  relay-go: starting on port 5999 (dev routes: true)
  relay-go: INFO channel stopped channel=a-uuid
  ```

  Four things to read in that, and record all four in the PR description. The status is 200 and the type is `video/mp2t`. The first byte is `0x47`, the TS sync byte, and the next three are `01 00 10` — PID 0x100 with the continuity counter at zero, which is `SyntheticTS`'s very first packet, so the client landed at the start of the buffer exactly as the join-point fallback says it should on a young buffer. **1,279,340 bytes is exactly five chunks of 255,868**, which is `BUFFER_CHUNK_SIZE` — so A1.4's wire value reached the ring, which nothing else in the run would have shown. And the relay logged the channel stopping when the client left, which is the manager's last-client teardown.

  **No job control and no bare `sleep`.** `%1` needs an interactive shell and a foreground `sleep` is blocked in this harness; `perl -e 'select(...)'` is the sub-second wait 2c-1 used. `go run` compiles to a temp binary and execs it as a child, so `kill` on the `go run` PID can leave the listener holding `:5999` — hence `pkill -f 'exe/relay'`.

  **Delete `relay/cmd/` before staging** and confirm with `git status`. A committed probe is a second `main` package in the module, which the Dockerfile's builder stage would try to build.

- [ ] **Step 5: Write the PR description**

  It must carry, in this order:

  1. **What this PR does**, in three sentences.
  2. **Task 0's findings** — the diff between the 2c-1 ledger and the merged tree, and which task each surprise landed in.
  3. **Amendment A1.4**, with the number: thirty-one class-attribute defaults now on the wire, the six property-shadowed names deliberately excluded, and the enumeration test that makes a new default impossible to add silently.
  4. **The Redis walk**, from Ruling R4: the six key families this PR touches and what each became, stated as the spec requires ("if any family is found not to fit this walk cleanly, the implementing PR says so honestly rather than asserting the invariant met"). If one did not fit, say so here.
  5. **Every break-check**, with the message you saw — not "reddened", the actual text. Flag the two that are known not to redden as written (Task 8's number 4, and Task 7's number 1 first half) and say what you did instead.
  6. **The hand-run evidence** from Step 4.
  7. **The three lint decisions**: the one `#nosec G705` and why, and the two `G115` findings fixed rather than suppressed.
  8. **What this PR does not do**, stated rather than implied: no fan-out beyond what the type supports and no client registry (2c-3), no ffmpeg and no `shlex` port (2c-4), no failover, no `release`, no `events`, no degraded fallback (2c-5), no fMP4 (2c-6), no Output Profile (2c-7), no `/proxy/relay/…` routes, no drain, no `HEALTHCHECK`, no `authorize-internal` fallback (2c-8), no coverage ratchet and no CodeQL Go pack (2c-9), no nginx route (2d), no keepalive or client timeout (A2.5), no row-8 pin (A2.3), no differential test (A2.4), and no `metrics/curated` update — milestones are per stage and the 2c goal milestone lands with 2c-9.

- [ ] **Step 6: Commit, and do not push or open a PR unless told to**

---

## Break-check × what each can redden

Every break-check in this plan, and the phase it belongs to. A `✓` means the break-check was run against this plan's own verified implementation and the message in the task table is the one that appeared.

| # | Task | The injected defect | What reddens | Verified |
|---|---|---|---|---|
| 1 | 1 | a new `TSConfig` attribute with no serializer field | `test_every_class_attribute_default_is_a_declared_field` | — |
| 2 | 1 | walk `BaseConfig.__mro__` instead of `TSConfig`'s | the enumeration test **and** the shadowing test | — |
| 3 | 1 | drop the `defaults.pop` shadowing rule | `test_a_shadowed_class_attribute_does_not_reach_the_wire` | — |
| 4 | 1 | `BUFFER_CHUNK_SIZE` becomes `188 * 5644` | the three-literal test only; the set-wide test stays green | — |
| 5 | 2 | drop the `0x10\|` adaptation-field nibble | `TestSyntheticTSMatchesThePythonHarness` | ✓ |
| 6 | 2 | `%#02x` back to `%#04x` | `TestAlignmentProblemNamesWhatIsWrong` | ✓ |
| 7 | 4 | the carried partial packet is dropped | `TestWritePublishesWholePacketsInUnbrokenOrder` | ✓ |
| 8 | 4 | `ResetPosition` also resets `head` | `TestResetPositionDoesNotRewindTheChunkIndex` | ✓ |
| 9 | 4 | one backing array reused for every chunk (**a field, not a local**) | `TestAPublishedChunkIsNeverRewritten` | ✓ |
| 10 | 4 | `Join` returns the head | both `Join` positioning tests | ✓ |
| 11 | 4 | no age-based eviction | `TestRetentionEvictsBeforeTheRingIsFull` | ✓ |
| 12 | 4 | `New` ignores `cfg.ChunkBytes` | five tests; **read `TestCapacityUsesTheConfiguredChunkSize`'s message** | ✓ |
| 13 | 4 | `Head()` without `RLock` | `TestConcurrentReadersAndOneWriter`, as `WARNING: DATA RACE` | ✓ |
| 14 | 5 | the token's field separator becomes `\|` | `TestNextSourceSignsTheRequestTheWayDjangoVerifiesIt` | — |
| 15 | 5 | `Refused` embeds `*Unavailable` | `TestA403IsRefusedAndIsNotUnavailable` | — |
| 16 | 5 | the 3xx branch becomes retryable | `TestARedirectIsNeitherFollowedNorRetried`, on the request count | — |
| 17 | 5 | `CheckRedirect` dropped | the same test, on the **redirect target's** count | — |
| 18 | 5 | the dev branch reads `DISPATCHARR_PORT` | `TestBaseURLFollowsTheFourBranches/dev…` | — |
| 19 | 6 | the `*url.Error` is wrapped as it comes | `TestAConnectFailureNeverEchoesTheProviderURL` | ✓ |
| 20 | 6 | `parent.Err()` checked after `idled` | `TestProxySourceAttributesACancellationToTheCaller` | — |
| 21 | 6 | the read error is checked before `buf[:n]` is written | `TestProxySourceCopiesTheUpstreamVerbatim` | — |
| 22 | 7 | `start()` called unconditionally | `TestTwoClientsShareOneSource` and `TestTwoClientsMakeOneUpstreamRequest` | — |
| 23 | 7 | `c.ring.Close()` dropped from `run` | `TestACleanUpstreamEndClosesTheRing` | — |
| 24 | 7 | the failure arm sets `StateStopped` | `TestAnUpstreamFailurePutsTheChannelInError` | — |
| 25 | 8 | branch on `transcode` instead of `kind` | `TestATuneRefusesAKindItDoesNotServe` | ✓ |
| 26 | 8 | the trust-marker guard dropped | `TestXRelayChannelIsIgnoredWithoutTheTrustMarker` | ✓ |
| 27 | 8 | one setting falls back to a literal | `TestEveryProxySettingThisRelayReadsIsRequired/<key>` **only** | ✓ |
| 28 | 8 | the `ErrClosed` final read deleted | **expected not to redden**; report the gap | ✓ (did not redden) |
| 29 | 11 | a local package named `redisclient` imported from `main.go` | `scripts/check_go_stdlib_only.sh` | — |

**Three rows deserve a second look before you trust them.**

- **9** does not redden if the reused array is a local inside `Write` rather than a field on `Ring`. That is the shape to inject.
- **12** reddens five tests and four of the messages name a symptom. Confirm the capacity test's message.
- **27** does not redden against `TestATuneRefusesIncompleteProxySettings`, because that fixture is missing seven keys at once and any one of them still fails the tune. The per-key test is the one that has the property.

---

## What to report back

1. **Task 0's diff** — every row of the 2c-1 ledger that did not match the merged tree, and which task absorbed it.
2. **The A1.4 numbers** — how many class-attribute defaults your tree produced (expected 31), and whether the six property-shadowed exclusions were the six named here.
3. **The zero-ORM measurement** from Task 1 Step 6, before and after, with the expectation that it did not move.
4. **Every break-check's actual failure message**, and specifically: did 9, 12, 27 and 28 behave as this plan predicts?
5. **The Redis key-family walk** — all six families, and whether any did not fit.
6. **The lint ledger** — the one `#nosec`, the two `G115` fixes, and anything new the linter found that this plan does not name.
7. **The hand-run evidence** — status, content type, first byte.
8. **Anything in the spec, `CLAUDE.md`, the 2c-1 plan or this plan you found wrong or stale.** The two most likely places: 2c-1's ledger rows, and the Django host regex in Task 5 Step 2.

---

## Appendix — the six test files, in full

Every file below was written, built, vetted, run under `go test -race` three times and linted at **0 issues** before this plan was written. The task tables above say what each test pins and why; these are the bodies, so nothing has to be improvised against the six hollow shapes.

Two literals in here are oracles produced by the **other** implementation and must be regenerated rather than trusted (Task 2 Step 2 and Task 5 Step 4 have the commands): the SHA-256 of the synthetic asset, and the bound-token header.


### Appendix A — `relay/buffer/ring_test.go` (Task 4 Step 3)

  ```go
  package buffer

  import (
  	"context"
  	"errors"
  	"sync"
  	"testing"
  	"time"

  	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
  )

  // A small ring, so a test reaches eviction in a few kilobytes instead of 73
  // megabytes. The chunk size is a whole number of packets, as the real one is.
  const (
  	testChunk  = TSPacketSize * 4 // 752 bytes
  	testBudget = testChunk * 8    // eight chunks
  )

  func newTestRing(t *testing.T, now func() time.Time) *Ring {
  	t.Helper()
  	return New(Config{BudgetBytes: testBudget, ChunkBytes: testChunk, Now: now})
  }

  // A clock a test drives by hand, so the join-point and retention tests assert
  // on time without spending any.
  type fakeClock struct {
  	mu sync.Mutex
  	at time.Time
  }

  func (c *fakeClock) now() time.Time {
  	c.mu.Lock()
  	defer c.mu.Unlock()
  	return c.at
  }

  func (c *fakeClock) advance(d time.Duration) {
  	c.mu.Lock()
  	defer c.mu.Unlock()
  	c.at = c.at.Add(d)
  }

  // drain reads everything resident from cursor and concatenates it.
  func drain(r *Ring, cursor uint64) ([]byte, uint64) {
  	chunks, next, _ := r.Read(cursor)
  	var out []byte
  	for _, c := range chunks {
  		out = append(out, c...)
  	}
  	return out, next
  }

  // Parity-matrix row 9. The oracle is relaytest.SyntheticTS's embedded packet
  // indices, which the ring never sees and cannot compute -- a test that asked
  // the ring where its own packet boundaries were would pass with the
  // packetiser deleted.
  //
  // The write sizes are deliberately coprime with 188 and with each other, so
  // every write ends mid-packet and the carry is exercised on every one of them.
  func TestWritePublishesWholePacketsInUnbrokenOrder(t *testing.T) {
  	r := newTestRing(t, nil)
  	// Twenty-eight packets is seven chunks, inside the eight-chunk ring, so
  	// nothing is evicted and the delivered stream can be compared against the
  	// source from packet zero.
  	source := relaytest.SyntheticTS(28, 0x100)

  	for offset := 0; offset < len(source); {
  		for _, size := range []int{1, 187, 189, 63, 401} {
  			if offset >= len(source) {
  				break
  			}
  			end := min(offset+size, len(source))
  			if _, err := r.Write(source[offset:end]); err != nil {
  				t.Fatalf("Write: %v", err)
  			}
  			offset = end
  		}
  	}

  	got, _ := drain(r, 0)
  	if problem := relaytest.AlignmentProblem(got); problem != "" {
  		t.Fatalf("the delivered stream is not whole TS packets: %s", problem)
  	}
  	for i := 0; i < len(got); i += TSPacketSize {
  		want := i / TSPacketSize
  		if idx := relaytest.PacketIndex(got[i : i+TSPacketSize]); idx != want {
  			t.Fatalf("packet at byte %d carries index %d, want %d -- the packetiser "+
  				"lost, duplicated or reordered bytes", i, idx, want)
  		}
  	}
  	if len(got)%testChunk != 0 {
  		t.Fatalf("delivered %d bytes, which is not a whole number of %d-byte chunks", len(got), testChunk)
  	}
  }

  // The carry itself, in isolation and at its boundary: 187 bytes is one short
  // of a packet and must publish nothing; the 188th byte must complete it.
  func TestAPartialPacketIsCarriedIntoTheNextWrite(t *testing.T) {
  	r := newTestRing(t, nil)
  	packet := relaytest.SyntheticTS(1, 0x100)

  	if _, err := r.Write(packet[:187]); err != nil {
  		t.Fatalf("Write: %v", err)
  	}
  	if head := r.Head(); head != 0 {
  		t.Fatalf("head = %d after 187 bytes, want 0 -- a partial packet must not be published", head)
  	}

  	// Complete the first packet and supply enough to fill exactly one chunk.
  	rest := relaytest.SyntheticTS(testChunk/TSPacketSize, 0x100)[187:]
  	if _, err := r.Write(rest); err != nil {
  		t.Fatalf("Write: %v", err)
  	}
  	if head := r.Head(); head != 1 {
  		t.Fatalf("head = %d, want 1", head)
  	}
  	got, _ := drain(r, 0)
  	if problem := relaytest.AlignmentProblem(got); problem != "" {
  		t.Fatalf("the carried byte was lost or misplaced: %s", problem)
  	}
  	if relaytest.PacketIndex(got[:TSPacketSize]) != 0 {
  		t.Fatal("the first delivered packet is not the first packet written")
  	}
  }

  // Spec D2's immutability rule. A reader holds a chunk's slice for as long as
  // it takes to write it to a socket, which can outlast the chunk's residency;
  // reusing a backing array would corrupt that reader silently.
  //
  // ASSERTS CONTENT, NOT THE RACE DETECTOR, and the distinction is the point.
  // -race only reports an overlap that actually happens, so a test relying on it
  // would pass or fail depending on scheduling. This one reddens deterministically.
  func TestAPublishedChunkIsNeverRewritten(t *testing.T) {
  	r := newTestRing(t, nil)
  	// One chunk's worth, then enough more to evict it twice over.
  	perChunk := testChunk / TSPacketSize
  	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  		t.Fatalf("Write: %v", err)
  	}

  	chunks, _, _ := r.Read(0)
  	if len(chunks) != 1 {
  		t.Fatalf("read %d chunks, want 1", len(chunks))
  	}
  	held := chunks[0]
  	snapshot := append([]byte(nil), held...)

  	for range 20 {
  		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x101)); err != nil {
  			t.Fatalf("Write: %v", err)
  		}
  	}

  	for i := range snapshot {
  		if held[i] != snapshot[i] {
  			t.Fatalf("byte %d of a chunk a reader still holds changed from %#02x to %#02x "+
  				"after later writes: a published chunk's backing array was reused",
  				i, snapshot[i], held[i])
  		}
  	}
  }

  // Parity-matrix row 7. reset_buffer_position clears _write_buffer and
  // _partial_packet and never touches self.index, which is why a stream switch
  // does not disturb a connected client.
  func TestResetPositionDoesNotRewindTheChunkIndex(t *testing.T) {
  	r := newTestRing(t, nil)
  	perChunk := testChunk / TSPacketSize
  	for range 3 {
  		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  			t.Fatalf("Write: %v", err)
  		}
  	}
  	before := r.Head()
  	if before != 3 {
  		t.Fatalf("head = %d before the switch, want 3", before)
  	}

  	r.ResetPosition()

  	if after := r.Head(); after != before {
  		t.Fatalf("head = %d after a stream switch, want %d -- the chunk index is "+
  			"monotonic for the channel's life and a switch never resets it", after, before)
  	}
  	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x101)); err != nil {
  		t.Fatalf("Write: %v", err)
  	}
  	if after := r.Head(); after != before+1 {
  		t.Fatalf("head = %d after the next chunk, want %d", after, before+1)
  	}
  }

  // The other half of reset_buffer_position: the old upstream's trailing bytes
  // must NOT be concatenated with the new upstream's first ones, because the
  // spliced packet breaks audio decoder sync in the client.
  func TestResetPositionDropsTheCarriedPartialPacket(t *testing.T) {
  	r := newTestRing(t, nil)
  	perChunk := testChunk / TSPacketSize

  	old := relaytest.SyntheticTS(1, 0x100)
  	if _, err := r.Write(old[:100]); err != nil { // 100 bytes of a packet, carried
  		t.Fatalf("Write: %v", err)
  	}
  	r.ResetPosition()
  	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x101)); err != nil {
  		t.Fatalf("Write: %v", err)
  	}

  	got, _ := drain(r, 0)
  	if problem := relaytest.AlignmentProblem(got); problem != "" {
  		t.Fatalf("the switch spliced the old stream's partial packet onto the new one: %s", problem)
  	}
  	if got[1] != 0x01 || got[2] != 0x01 {
  		t.Fatalf("the first delivered packet is on PID %#04x, not the new stream's 0x101 -- "+
  			"the carried partial packet survived the switch",
  			int(got[1]&0x1F)<<8|int(got[2]))
  	}
  }

  // Parity-matrix row 8's mechanism. find_chunk_index_by_time asks for the
  // NEWEST chunk at least `behind` old and positions one before it, so the
  // client's first read starts at that chunk.
  func TestJoinStartsRoughlyBehindLive(t *testing.T) {
  	clock := &fakeClock{at: time.Unix(1_700_000_000, 0)}
  	r := newTestRing(t, clock.now)
  	perChunk := testChunk / TSPacketSize

  	// Six chunks, one per second. The ring holds eight, so none is evicted.
  	for range 6 {
  		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  			t.Fatalf("Write: %v", err)
  		}
  		clock.advance(time.Second)
  	}

  	// Head is 6, published at t+0..t+5, and "now" is t+6. Three seconds back
  	// is t+3, whose newest chunk at or before it is chunk 4 (published t+3).
  	cursor := r.Join(3 * time.Second)
  	if cursor != 3 {
  		t.Fatalf("Join(3s) = %d, want 3 so the next read starts at chunk 4; head is %d",
  			cursor, r.Head())
  	}
  	if cursor >= r.Head() {
  		t.Fatalf("Join(3s) positioned at or past the live head (%d) -- a joining client "+
  			"would get no backlog at all", r.Head())
  	}
  }

  // The fallback inside find_chunk_index_by_time: nothing is old enough, so the
  // oldest chunk in the buffer is where the client starts.
  func TestJoinFallsBackToTheOldestChunkWhenTheBufferIsShort(t *testing.T) {
  	clock := &fakeClock{at: time.Unix(1_700_000_000, 0)}
  	r := newTestRing(t, clock.now)
  	perChunk := testChunk / TSPacketSize

  	for range 3 {
  		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  			t.Fatalf("Write: %v", err)
  		}
  		clock.advance(100 * time.Millisecond)
  	}

  	if cursor := r.Join(30 * time.Second); cursor != 0 {
  		t.Fatalf("Join(30s) on a 0.3s buffer = %d, want 0 (one before the oldest chunk)", cursor)
  	}
  }

  // _setup_streaming's last resort: no timestamp data at all, start at live.
  func TestJoinOnAnEmptyRingStartsAtTheHead(t *testing.T) {
  	r := newTestRing(t, nil)
  	if cursor := r.Join(5 * time.Second); cursor != 0 {
  		t.Fatalf("Join on an empty ring = %d, want 0 (the head)", cursor)
  	}
  }

  // A client the writer outran. Python discovers this through a failed read and
  // jumps to find_oldest_available_chunk; the ring reports the jump instead of
  // absorbing it, so the caller can log a real gap.
  func TestReadReportsWhatEvictionSkipped(t *testing.T) {
  	r := newTestRing(t, nil)
  	perChunk := testChunk / TSPacketSize
  	for range 12 { // twelve chunks into an eight-chunk ring
  		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  			t.Fatalf("Write: %v", err)
  		}
  	}

  	chunks, next, skipped := r.Read(0)
  	if skipped == 0 {
  		t.Fatal("Read from a cursor the ring has evicted past reported no skip")
  	}
  	oldest, ok := r.Oldest()
  	if !ok {
  		t.Fatal("the ring is empty after twelve writes")
  	}
  	if want := oldest - 1; skipped != want {
  		t.Fatalf("skipped = %d, want %d (oldest resident is %d)", skipped, want, oldest)
  	}
  	if len(chunks) != 8 {
  		t.Fatalf("read %d chunks, want the ring's whole capacity of 8", len(chunks))
  	}
  	if next != 12 {
  		t.Fatalf("next = %d, want 12", next)
  	}
  }

  // The byte cap binds: the ring never holds more than its capacity.
  func TestTheRingNeverExceedsItsCapacity(t *testing.T) {
  	r := newTestRing(t, nil)
  	perChunk := testChunk / TSPacketSize
  	for range 50 {
  		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  			t.Fatalf("Write: %v", err)
  		}
  	}
  	chunks, _, _ := r.Read(0)
  	if len(chunks) > 8 {
  		t.Fatalf("the ring holds %d chunks, above its capacity of 8 -- the byte cap is not enforced", len(chunks))
  	}
  }

  // The retention bound binds independently of the byte cap: a chunk older than
  // Retention goes even when the ring is nowhere near full.
  func TestRetentionEvictsBeforeTheRingIsFull(t *testing.T) {
  	clock := &fakeClock{at: time.Unix(1_700_000_000, 0)}
  	r := New(Config{
  		BudgetBytes: testBudget,
  		ChunkBytes:  testChunk,
  		Retention:   2 * time.Second,
  		Now:         clock.now,
  	})
  	perChunk := testChunk / TSPacketSize

  	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  		t.Fatalf("Write: %v", err)
  	}
  	clock.advance(10 * time.Second)
  	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  		t.Fatalf("Write: %v", err)
  	}

  	oldest, ok := r.Oldest()
  	if !ok {
  		t.Fatal("the ring is empty")
  	}
  	if oldest != 2 {
  		t.Fatalf("oldest resident chunk is %d, want 2 -- a chunk older than the "+
  			"retention window survived in a ring with seven free slots", oldest)
  	}
  }

  // Capacity comes from the CONFIGURED chunk size, not the package constant.
  // Amendment A1.4 puts BUFFER_CHUNK_SIZE on the wire, and a ring that divided
  // the budget by the constant would size itself from a value the control plane
  // may have changed.
  func TestCapacityUsesTheConfiguredChunkSize(t *testing.T) {
  	// A chunk size a quarter of the default gives four times the chunks. The
  	// default could not produce this count, so the test fails if the config
  	// field is ignored (hollow shape 2).
  	r := New(Config{BudgetBytes: ChunkBytes * 4, ChunkBytes: ChunkBytes / 4})
  	perChunk := (ChunkBytes / 4) / TSPacketSize
  	for range 40 {
  		if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  			t.Fatalf("Write: %v", err)
  		}
  	}
  	chunks, _, _ := r.Read(0)
  	if len(chunks) != 16 {
  		t.Fatalf("the ring holds %d chunks, want 16 (a %d-byte budget at %d bytes a chunk)",
  			len(chunks), ChunkBytes*4, ChunkBytes/4)
  	}
  }

  func TestWaitWakesOnAPublish(t *testing.T) {
  	r := newTestRing(t, nil)
  	perChunk := testChunk / TSPacketSize

  	woke := make(chan error, 1)
  	go func() { woke <- r.Wait(t.Context()) }()

  	// Give the waiter a moment to block, then publish.
  	time.Sleep(20 * time.Millisecond)
  	if _, err := r.Write(relaytest.SyntheticTS(perChunk, 0x100)); err != nil {
  		t.Fatalf("Write: %v", err)
  	}

  	select {
  	case err := <-woke:
  		if err != nil {
  			t.Fatalf("Wait returned %v, want nil", err)
  		}
  	case <-time.After(2 * time.Second):
  		t.Fatal("Wait did not return after a chunk was published")
  	}
  }

  func TestWaitWakesOnClose(t *testing.T) {
  	r := newTestRing(t, nil)
  	woke := make(chan error, 1)
  	go func() { woke <- r.Wait(t.Context()) }()
  	time.Sleep(20 * time.Millisecond)
  	r.Close()

  	select {
  	case err := <-woke:
  		// Either outcome is correct: a waiter already blocked sees the closed
  		// channel and returns nil, and one that arrives afterwards sees the
  		// flag and returns ErrClosed. What must NOT happen is blocking.
  		if err != nil && !errors.Is(err, ErrClosed) {
  			t.Fatalf("Wait returned %v, want nil or ErrClosed", err)
  		}
  	case <-time.After(2 * time.Second):
  		t.Fatal("Wait did not return after Close -- every reader would leak")
  	}
  	if err := r.Wait(t.Context()); !errors.Is(err, ErrClosed) {
  		t.Fatalf("Wait after Close returned %v, want ErrClosed", err)
  	}
  	r.Close() // idempotent; a second close must not panic
  }

  func TestWaitReturnsWhenTheClientGoesAway(t *testing.T) {
  	r := newTestRing(t, nil)
  	ctx, cancel := context.WithCancel(t.Context())
  	woke := make(chan error, 1)
  	go func() { woke <- r.Wait(ctx) }()
  	time.Sleep(20 * time.Millisecond)
  	cancel()

  	select {
  	case err := <-woke:
  		if !errors.Is(err, context.Canceled) {
  			t.Fatalf("Wait returned %v, want context.Canceled", err)
  		}
  	case <-time.After(2 * time.Second):
  		t.Fatal("Wait ignored its context -- a disconnected viewer would leak a goroutine")
  	}
  }

  // The lock discipline, under -race. One writer and several readers, all
  // touching head, chunks and notify at once. This is the test the race detector
  // IS the oracle for: an unguarded read of any of those three is reported
  // directly, with both stacks.
  func TestConcurrentReadersAndOneWriter(t *testing.T) {
  	r := newTestRing(t, nil)
  	perChunk := testChunk / TSPacketSize
  	payload := relaytest.SyntheticTS(perChunk, 0x100)

  	var wg sync.WaitGroup
  	stop := make(chan struct{})
  	for range 4 {
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
  				for _, c := range chunks {
  					if len(c) != testChunk {
  						t.Errorf("a reader saw a %d-byte chunk, want %d", len(c), testChunk)
  						return
  					}
  				}
  				_ = r.Head()
  				_, _ = r.Oldest()
  				_ = r.Join(time.Second)
  			}
  		}()
  	}

  	for range 200 {
  		if _, err := r.Write(payload); err != nil {
  			t.Fatalf("Write: %v", err)
  		}
  	}
  	close(stop)
  	wg.Wait()
  }
  ```


### Appendix B — `relay/control/nextsource_test.go` (Task 5 Step 4)

  ```go
  package control

  import (
  	"errors"
  	"net/http"
  	"strings"
  	"testing"
  	"time"

  	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
  )

  const testSecret = "phase2c1-test-secret"

  func testClient(t *testing.T, cp *relaytest.ControlPlane) *Client {
  	t.Helper()
  	t.Cleanup(cp.Close)
  	return &Client{Secret: testSecret, BaseURL: cp.URL(), HTTP: NewHTTPClient()}
  }

  func TestNextSourceReadsTheAnswer(t *testing.T) {
  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
  	answer, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{Reason: "initial"})
  	if err != nil {
  		t.Fatalf("NextSource: %v", err)
  	}
  	if answer.Source == nil {
  		t.Fatal("the answer carried no source")
  	}
  	if answer.Source.StreamProfile.Kind != KindProxy {
  		t.Fatalf("kind = %q, want %q", answer.Source.StreamProfile.Kind, KindProxy)
  	}
  	if got, err := answer.ProxySettings.Int("BUFFER_CHUNK_SIZE"); err != nil || got != 255868 {
  		t.Fatalf("BUFFER_CHUNK_SIZE = %d, %v; want 255868, nil", got, err)
  	}
  }

  // THE BOUND TOKEN, PINNED AGAINST A PYTHON-PRODUCED LITERAL. A test that
  // recomputed the expectation with InternalRequestHeader would prove the
  // function deterministic and nothing else: it would pass with the context
  // string misspelled, the separator wrong, the body digest omitted, or SHA-512
  // in place of SHA-256 -- every one of which 403s in production.
  //
  // The clock is injected so the timestamp is the one the literal was generated
  // at. Regenerate the literal from Django, never from the Go.
  func TestNextSourceSignsTheRequestTheWayDjangoVerifiesIt(t *testing.T) {
  	const wantHeader = "v1.1789000000.5ce39464af1f52fac92ab6dd8101b289c2b9acce93d392216ac0dbcfa53a1fae"
  	const wantBody = `{"reason":"init"}`

  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
  	client := testClient(t, cp)
  	client.Now = func() time.Time { return time.Unix(1789000000, 0) }

  	// The body has to be exactly the seventeen bytes the literal was signed
  	// over, so this drives post directly rather than NextSource, whose body is
  	// a marshalled request struct.
  	if _, _, err := client.post(t.Context(), "/api/relay/channels/abc/next-source", []byte(wantBody)); err != nil {
  		t.Fatalf("post: %v", err)
  	}

  	seen := cp.Requests()
  	if len(seen) != 1 {
  		t.Fatalf("the control plane saw %d requests, want 1", len(seen))
  	}
  	if got := seen[0].Header.Get(HeaderInternalRequest); got != wantHeader {
  		t.Fatalf("%s = %s\nwant %s\n(the literal comes from apps/proxy/internal_auth.py's own "+
  			"internal_request_token under SECRET_KEY=%q)", HeaderInternalRequest, got, wantHeader, testSecret)
  	}
  	if got := seen[0].Header.Get(HeaderInternal); got != InternalPrincipalToken(testSecret) {
  		t.Fatalf("%s was not the internal-principal token", HeaderInternal)
  	}
  }

  // A 404 is an ANSWER, not an error: the channel was deleted mid playback.
  func TestNextSourceMapsA404ToANullSource(t *testing.T) {
  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusNotFound})
  	answer, err := testClient(t, cp).NextSource(t.Context(), "gone", NextSourceRequest{})
  	if err != nil {
  		t.Fatalf("a 404 became an error: %v", err)
  	}
  	if answer.Source != nil {
  		t.Fatal("a 404 answer carried a source")
  	}
  	if answer.Error != "identifier not found" {
  		t.Fatalf("error = %q, want %q", answer.Error, "identifier not found")
  	}
  }

  // Every other 4xx is Refused, and Refused is deliberately NOT an Unavailable:
  // a 403 from a SECRET_KEY mismatch between the api and relay roles must fail
  // the tune loudly rather than make every failover degrade silently forever.
  func TestA403IsRefusedAndIsNotUnavailable(t *testing.T) {
  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusForbidden})
  	_, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})

  	var refused *Refused
  	if !errors.As(err, &refused) {
  		t.Fatalf("error = %v, want a *Refused", err)
  	}
  	if refused.Status != http.StatusForbidden {
  		t.Fatalf("Refused.Status = %d, want 403", refused.Status)
  	}
  	var unavailable *Unavailable
  	if errors.As(err, &unavailable) {
  		t.Fatal("a 403 satisfied errors.As(*Unavailable): the degraded fallback would swallow it")
  	}
  	if n := len(cp.Requests()); n != 1 {
  		t.Fatalf("the control plane saw %d requests, want 1 -- a 4xx is not retried", n)
  	}
  }

  // The retry budget, in both directions. Two tests would each pass with the
  // loop hard-wired the wrong way, so both halves are asserted: a 5xx is
  // retried and recovers, and a 3xx is not.
  func TestOnlyA5xxConsumesTheRetry(t *testing.T) {
  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{
  		SourceURL: "http://provider.invalid/a.ts",
  		FailFirst: 1,
  	})
  	answer, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})
  	if err != nil {
  		t.Fatalf("a single 503 was not retried: %v", err)
  	}
  	if answer.Source == nil {
  		t.Fatal("the retried call produced no source")
  	}
  	if n := len(cp.Requests()); n != 2 {
  		t.Fatalf("the control plane saw %d requests, want 2", n)
  	}
  }

  func TestA5xxOnBothAttemptsIsUnavailable(t *testing.T) {
  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Status: http.StatusBadGateway})
  	_, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})
  	var unavailable *Unavailable
  	if !errors.As(err, &unavailable) {
  		t.Fatalf("error = %v, want an *Unavailable", err)
  	}
  	if n := len(cp.Requests()); n != 2 {
  		t.Fatalf("the control plane saw %d requests, want 2 (the first try plus one retry)", n)
  	}
  }

  // A redirect is never followed: following one re-sends the signed internal
  // headers to whatever a stray `return 301` names. And it is not retried --
  // a client built to this spec's uncorrected first draft would burn a second
  // full (2s, 5s) budget, up to seven extra seconds of dead air, on a
  // misconfigured deployment.
  func TestARedirectIsNeitherFollowedNorRetried(t *testing.T) {
  	elsewhere := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{SourceURL: "http://provider.invalid/a.ts"})
  	t.Cleanup(elsewhere.Close)
  	cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{RedirectTo: elsewhere.URL() + "/api/relay/x"})

  	_, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})
  	var unavailable *Unavailable
  	if !errors.As(err, &unavailable) {
  		t.Fatalf("error = %v, want an *Unavailable", err)
  	}
  	if n := len(cp.Requests()); n != 1 {
  		t.Fatalf("the control plane saw %d requests, want 1 -- a 3xx raises on the first pass", n)
  	}
  	if n := len(elsewhere.Requests()); n != 0 {
  		t.Fatalf("the redirect target saw %d requests: the signed internal headers were forwarded", n)
  	}
  }

  func TestA2xxThatIsNotAJSONObjectIsUnavailableAndNotRetried(t *testing.T) {
  	for _, body := range []string{"<html>nginx</html>", `["a","list"]`, `null`} {
  		cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{Body: body})
  		_, err := testClient(t, cp).NextSource(t.Context(), "abc", NextSourceRequest{})
  		var unavailable *Unavailable
  		if !errors.As(err, &unavailable) {
  			t.Errorf("body %q: error = %v, want an *Unavailable", body, err)
  			continue
  		}
  		if n := len(cp.Requests()); n != 1 {
  			t.Errorf("body %q: the control plane saw %d requests, want 1", body, n)
  		}
  	}
  }

  func TestSettingsFailLoudlyOnAnAbsentKey(t *testing.T) {
  	s := Settings{"present": []byte("5")}
  	if _, err := s.Int("present"); err != nil {
  		t.Fatalf("a present key failed: %v", err)
  	}
  	var absent *ErrSettingAbsent
  	if _, err := s.Int("BUFFER_CHUNK_SIZE"); !errors.As(err, &absent) {
  		t.Fatalf("error = %v, want an *ErrSettingAbsent", err)
  	} else if absent.Key != "BUFFER_CHUNK_SIZE" {
  		t.Fatalf("ErrSettingAbsent names %q", absent.Key)
  	}
  	if !strings.Contains(absent.Error(), "BUFFER_CHUNK_SIZE") {
  		t.Fatalf("the message does not name the key: %s", absent.Error())
  	}
  }

  // A FloatField renders 15 as 15.0, so an integer setting has to survive
  // arriving as a JSON float. Reading it straight into an int refuses it.
  func TestAnIntegerSettingSurvivesArrivingAsAFloat(t *testing.T) {
  	s := Settings{"STREAM_TIMEOUT": []byte("20.0")}
  	got, err := s.Int("STREAM_TIMEOUT")
  	if err != nil {
  		t.Fatalf("Int on a JSON float failed: %v", err)
  	}
  	if got != 20 {
  		t.Fatalf("STREAM_TIMEOUT = %d, want 20", got)
  	}
  }

  func TestSecondsHonoursAFractionalValue(t *testing.T) {
  	s := Settings{"KEEPALIVE_INTERVAL": []byte("0.5")}
  	got, err := s.Seconds("KEEPALIVE_INTERVAL")
  	if err != nil {
  		t.Fatalf("Seconds: %v", err)
  	}
  	if got != 500*time.Millisecond {
  		t.Fatalf("KEEPALIVE_INTERVAL = %s, want 500ms", got)
  	}
  }
  ```


### Appendix C — `relay/control/baseurl_test.go` (Task 5 Step 4)

  ```go
  package control

  import (
  	"errors"
  	"strings"
  	"testing"
  )

  func TestBaseURLFollowsTheFourBranches(t *testing.T) {
  	for _, tc := range []struct {
  		name string
  		env  map[string]string
  		want string
  	}{
  		{
  			// A value no branch could produce by accident: not 5656, not
  			// 9191, not the default host (hollow shape 2).
  			"the explicit override wins, trailing slash stripped",
  			map[string]string{
  				"DISPATCHARR_INTERNAL_API_BASE_URL": "http://control.invalid:7777/",
  				"DISPATCHARR_ENV":                   "dev",
  			},
  			"http://control.invalid:7777",
  		},
  		{
  			"modular names the service and DISPATCHARR_PORT",
  			map[string]string{"DISPATCHARR_ENV": "modular", "DISPATCHARR_PORT": "8888"},
  			"http://web:8888",
  		},
  		{
  			"modular honours DISPATCHARR_WEB_HOST",
  			map[string]string{"DISPATCHARR_ENV": "modular", "DISPATCHARR_WEB_HOST": "api-host"},
  			"http://api-host:9191",
  		},
  		{
  			// Hardcoded, not read from DISPATCHARR_PORT, which names vite's
  			// port in dev. Setting it to something else is what shows the
  			// branch really ignores it.
  			"dev names the application port and ignores DISPATCHARR_PORT",
  			map[string]string{"DISPATCHARR_ENV": "dev", "DISPATCHARR_PORT": "8888"},
  			"http://127.0.0.1:5656",
  		},
  		{
  			"aio goes through nginx on DISPATCHARR_PORT",
  			map[string]string{"DISPATCHARR_ENV": "aio", "DISPATCHARR_PORT": "8888"},
  			"http://127.0.0.1:8888",
  		},
  		{
  			"an unset environment is aio",
  			map[string]string{},
  			"http://127.0.0.1:9191",
  		},
  	} {
  		t.Run(tc.name, func(t *testing.T) {
  			for _, name := range []string{
  				"DISPATCHARR_INTERNAL_API_BASE_URL", "DISPATCHARR_ENV",
  				"DISPATCHARR_WEB_HOST", "DISPATCHARR_PORT",
  			} {
  				t.Setenv(name, tc.env[name])
  			}
  			got, err := BaseURL()
  			if err != nil {
  				t.Fatalf("BaseURL: %v", err)
  			}
  			if got != tc.want {
  				t.Fatalf("BaseURL = %q, want %q", got, tc.want)
  			}
  		})
  	}
  }

  // An underscore in a host is what Django's own host_validation_re rejects,
  // BEFORE ALLOWED_HOSTS is consulted, so such a URL reaches Django as an opaque
  // 400 with nothing naming the cause. Failing here blames the variable instead.
  func TestBaseURLRejectsWhatDjangoWouldRefuseAsAHost(t *testing.T) {
  	for _, tc := range []struct{ name, value string }{
  		{"an underscore in the host", "http://web_host:9191"},
  		{"no scheme at all", "web:9191"},
  		{"an unsupported scheme", "ftp://web:9191"},
  	} {
  		t.Run(tc.name, func(t *testing.T) {
  			t.Setenv("DISPATCHARR_INTERNAL_API_BASE_URL", tc.value)
  			_, err := BaseURL()
  			var misconfigured *ErrNotConfigured
  			if !errors.As(err, &misconfigured) {
  				t.Fatalf("BaseURL(%q) error = %v, want an *ErrNotConfigured", tc.value, err)
  			}
  			if misconfigured.Variable != "DISPATCHARR_INTERNAL_API_BASE_URL" {
  				t.Fatalf("the error names %q, not the responsible variable", misconfigured.Variable)
  			}
  		})
  	}
  }

  // Userinfo is stripped before the host is validated, because what goes on the
  // wire as the Host header is the netloc minus userinfo. Validating the raw
  // netloc would reject a URL Django would accept. The message must not echo
  // the value either: it carries a password.
  func TestUserinfoIsStrippedBeforeTheHostIsChecked(t *testing.T) {
  	t.Setenv("DISPATCHARR_INTERNAL_API_BASE_URL", "http://user:pw@web:9191")
  	got, err := BaseURL()
  	if err != nil {
  		t.Fatalf("a URL with userinfo was rejected: %v", err)
  	}
  	if got != "http://user:pw@web:9191" {
  		t.Fatalf("BaseURL = %q", got)
  	}
  }

  func TestAMisconfigurationMessageNeverEchoesTheValue(t *testing.T) {
  	t.Setenv("DISPATCHARR_INTERNAL_API_BASE_URL", "http://user:hunter2@bad_host:9191")
  	_, err := BaseURL()
  	if err == nil {
  		t.Fatal("a bad host was accepted")
  	}
  	if got := err.Error(); strings.Contains(got, "hunter2") || strings.Contains(got, "bad_host") {
  		t.Fatalf("the error echoes the rejected value: %s", got)
  	}
  }
  ```


### Appendix D — `relay/channel/source_proxy_test.go` (Task 6 Step 4)

  ```go
  package channel

  import (
  	"bytes"
  	"context"
  	"errors"
  	"strings"
  	"sync"
  	"testing"
  	"time"

  	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
  )

  // A sink that records what the source gave it, safely under -race.
  type recordingSink struct {
  	mu  sync.Mutex
  	buf bytes.Buffer
  }

  func (s *recordingSink) Write(p []byte) (int, error) {
  	s.mu.Lock()
  	defer s.mu.Unlock()
  	return s.buf.Write(p)
  }

  func (s *recordingSink) Bytes() []byte {
  	s.mu.Lock()
  	defer s.mu.Unlock()
  	return append([]byte(nil), s.buf.Bytes()...)
  }

  func TestProxySourceCopiesTheUpstreamVerbatim(t *testing.T) {
  	payload := relaytest.SyntheticTS(64, 0x100)
  	up := relaytest.NewUpstream(relaytest.Config{
  		Payload:        payload,
  		StopAfterBytes: len(payload),
  	})
  	t.Cleanup(up.Close)

  	sink := &recordingSink{}
  	if err := (ProxySource{URL: up.URL()}).Run(t.Context(), sink); err != nil {
  		t.Fatalf("Run: %v", err)
  	}

  	got := sink.Bytes()
  	if !bytes.Equal(got, payload) {
  		t.Fatalf("the source delivered %d bytes, want the upstream's %d, byte for byte",
  			len(got), len(payload))
  	}
  }

  func TestProxySourceSendsTheUserAgent(t *testing.T) {
  	up := relaytest.NewUpstream(relaytest.Config{StopAfterBytes: 188})
  	t.Cleanup(up.Close)
  	// The upstream records nothing about headers, so this asserts the request
  	// succeeded with the header set rather than that the header arrived --
  	// which is why it is paired with the handler test below, where the whole
  	// tune is observed. A header-echoing upstream is 2c-5's, with the
  	// provider-side assertions that need one.
  	if err := (ProxySource{URL: up.URL(), UserAgent: "VLC/3.0.20"}).Run(t.Context(), &recordingSink{}); err != nil {
  		t.Fatalf("Run: %v", err)
  	}
  }

  func TestProxySourceReportsANon200(t *testing.T) {
  	up := relaytest.NewUpstream(relaytest.Config{Status: 403})
  	t.Cleanup(up.Close)

  	err := (ProxySource{URL: up.URL()}).Run(t.Context(), &recordingSink{})
  	var status *ErrUpstreamStatus
  	if !errors.As(err, &status) {
  		t.Fatalf("error = %v, want an *ErrUpstreamStatus", err)
  	}
  	if status.Status != 403 {
  		t.Fatalf("ErrUpstreamStatus.Status = %d, want 403", status.Status)
  	}
  }

  func TestProxySourceEndsOnAnIdleUpstream(t *testing.T) {
  	up := relaytest.NewUpstream(relaytest.Config{DeadAir: 30 * time.Second})
  	t.Cleanup(up.Close)

  	start := time.Now()
  	err := (ProxySource{URL: up.URL(), ReadTimeout: 200 * time.Millisecond}).Run(t.Context(), &recordingSink{})
  	if !errors.Is(err, ErrUpstreamIdle) {
  		t.Fatalf("error = %v, want ErrUpstreamIdle", err)
  	}
  	if elapsed := time.Since(start); elapsed > 5*time.Second {
  		t.Fatalf("the idle watchdog took %s to fire on a 200ms timeout", elapsed)
  	}
  }

  // A client going away must be reported as a cancellation, NOT as an idle
  // upstream: 2c-5 turns the idle signal into a failover, and failing a healthy
  // stream over because a viewer closed a tab is the wrong diagnosis.
  func TestProxySourceAttributesACancellationToTheCaller(t *testing.T) {
  	up := relaytest.NewUpstream(relaytest.Config{DeadAir: 30 * time.Second})
  	t.Cleanup(up.Close)

  	ctx, cancel := context.WithCancel(t.Context())
  	done := make(chan error, 1)
  	go func() {
  		done <- ProxySource{URL: up.URL(), ReadTimeout: 30 * time.Second}.Run(ctx, &recordingSink{})
  	}()
  	time.Sleep(100 * time.Millisecond)
  	cancel()

  	select {
  	case err := <-done:
  		if !errors.Is(err, context.Canceled) {
  			t.Fatalf("error = %v, want context.Canceled", err)
  		}
  	case <-time.After(5 * time.Second):
  		t.Fatal("Run ignored its context")
  	}
  }

  // A provider URL is never in an error message: it carries provider
  // credentials (CLAUDE.md's credential-logging rule, enforced on the Python
  // side by scripts/check_credential_logging.py, which has no Go equivalent).
  //
  // THE CREDENTIAL IS IN THE QUERY STRING AND THE PATH, not in the userinfo, and
  // that is what makes this test able to fail. net/http redacts userinfo by
  // itself -- it prints http://user:***@host -- so a test that only checked a
  // password in the userinfo would pass against a %w-wrapped *url.Error and
  // prove nothing. The path and the query are NOT redacted, and a Dispatcharr
  // provider URL puts the credential in exactly those two places.
  func TestAConnectFailureNeverEchoesTheProviderURL(t *testing.T) {
  	const secretURL = "http://127.0.0.1:1/live/subscriber/hunter2/9.ts?token=s3cr3t"
  	err := ProxySource{URL: secretURL, ConnectTimeout: 200 * time.Millisecond}.
  		Run(t.Context(), &recordingSink{})
  	if err == nil {
  		t.Fatal("connecting to a closed port succeeded")
  	}
  	for _, secret := range []string{"hunter2", "s3cr3t", "/live/subscriber"} {
  		if strings.Contains(err.Error(), secret) {
  			t.Fatalf("the error echoes %q from the provider URL: %s", secret, err)
  		}
  	}
  	// Still useful: the transport's own reason survives the strip.
  	if !strings.Contains(err.Error(), "connection refused") {
  		t.Fatalf("the error lost the transport's reason: %s", err)
  	}
  }
  ```


### Appendix E — `relay/channel/manager_test.go` (Task 7 Step 3)

  ```go
  package channel

  import (
  	"context"
  	"errors"
  	"io"
  	"sync"
  	"testing"
  	"time"

  	"github.com/D10Scot/Dispatcharr/relay/buffer"
  	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
  )

  func testTuning() Tuning {
  	return Tuning{ChunkBytes: buffer.TSPacketSize * 4, Retention: time.Minute}
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

  	first, releaseFirst, err := m.Attach("chan-1", start)
  	if err != nil {
  		t.Fatalf("first Attach: %v", err)
  	}
  	second, releaseSecond, err := m.Attach("chan-1", start)
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
  	ch, releaseFirst, err := m.Attach("chan-2", start)
  	if err != nil {
  		t.Fatalf("Attach: %v", err)
  	}
  	_, releaseSecond, err := m.Attach("chan-2", start)
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

  // A channel whose source ends cleanly stops on its own: the ring closes and
  // every reader is woken.
  func TestACleanUpstreamEndClosesTheRing(t *testing.T) {
  	payload := relaytest.SyntheticTS(8, 0x100)
  	up := relaytest.NewUpstream(relaytest.Config{Payload: payload, StopAfterBytes: len(payload)})
  	t.Cleanup(up.Close)

  	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
  	t.Cleanup(m.StopAll)

  	ch, release, err := m.Attach("chan-3", func() (Source, Tuning, error) {
  		return ProxySource{URL: up.URL()}, testTuning(), nil
  	})
  	if err != nil {
  		t.Fatalf("Attach: %v", err)
  	}
  	defer release()

  	select {
  	case <-ch.Done():
  	case <-time.After(5 * time.Second):
  		t.Fatal("the source goroutine did not return after the upstream ended")
  	}
  	if state := ch.State(); state != StateStopped {
  		t.Fatalf("state = %q after a clean upstream end, want %q", state, StateStopped)
  	}
  	if err := ch.Ring().Wait(t.Context()); err == nil {
  		t.Fatal("the ring is still open after the source returned; every reader would block forever")
  	}
  }

  // A source that fails to start leaves the channel in error, and the failure
  // reaches the caller rather than becoming a channel that streams nothing.
  func TestAnUpstreamFailurePutsTheChannelInError(t *testing.T) {
  	up := relaytest.NewUpstream(relaytest.Config{Status: 404})
  	t.Cleanup(up.Close)

  	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 32})
  	t.Cleanup(m.StopAll)

  	ch, release, err := m.Attach("chan-4", func() (Source, Tuning, error) {
  		return ProxySource{URL: up.URL()}, testTuning(), nil
  	})
  	if err != nil {
  		t.Fatalf("Attach: %v", err)
  	}
  	defer release()

  	select {
  	case <-ch.Done():
  	case <-time.After(5 * time.Second):
  		t.Fatal("the source goroutine did not return after a 404")
  	}
  	if state := ch.State(); state != StateError {
  		t.Fatalf("state = %q after an upstream 404, want %q", state, StateError)
  	}
  	var status *ErrUpstreamStatus
  	if !errors.As(ch.Err(), &status) || status.Status != 404 {
  		t.Fatalf("Err() = %v, want an *ErrUpstreamStatus carrying 404", ch.Err())
  	}
  }
  ```


### Appendix F — `relay/httpapi/stream_test.go` (Task 8 Step 3)

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
  	controlPlane := relaytest.NewControlPlane(cp)
  	t.Cleanup(controlPlane.Close)

  	manager := channel.NewManager(channel.ManagerConfig{BudgetBytes: buffer.TSPacketSize * 4000})
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
  	want := buffer.ChunkBytes * 2
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
  	if _, err := io.ReadFull(response.Body, make([]byte, buffer.ChunkBytes)); err != nil {
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

  // 2c-2 serves the Proxy architecture ONLY, and refuses anything else loudly
  // rather than falling through. `kind` is what it branches on: `transcode` is
  // false for Redirect as well as Proxy, so a relay that read that field would
  // serve a Redirect channel's provider URL through the Proxy path silently.
  func TestATuneRefusesAKindItDoesNotServe(t *testing.T) {
  	for _, kind := range []string{control.KindRedirect, control.KindTranscode} {
  		t.Run(kind, func(t *testing.T) {
  			rig := newRig(t, relaytest.ControlPlaneConfig{Kind: kind}, relaytest.Config{})
  			response := rig.tune(t, "/proxy/ts/stream/a-channel-uuid", nil)
  			defer func() { _ = response.Body.Close() }()
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
