# Phase 2 PR 2c-1 — the Go relay skeleton Implementation Plan

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a Go module at `relay/`, start it as a supervisord program in the `all` and `relay` roles, build it in the Docker image, and gate it in CI — with `/healthz` and `/readyz` answering 200 and nothing else reachable outside `dev`. Plus one Python contract field, `stream_profile.kind`, without which the PR cannot honestly claim the spec's own precondition met. This is the first PR of Stage 2c and the first line of Go in the repository. It ships no streaming behaviour at all.

**Architecture:** Five packages the spec names (`httpapi`, `control`, `channel`, `buffer`, `ffmpeg`) plus one this plan adds and justifies (`config`). Three of the six are documented stubs; three carry real, tested code, because a stub that compiles and asserts nothing gives `go-tests.yml` nothing to prove and gives `go test -race` no reason to exist. The three that carry code are the three whose correctness cannot be deferred: `control` holds the HMAC token layout (get one byte wrong and every internal call 403s), `config` holds the `/data/jwt` read that feeds it (get the whitespace handling wrong and the same thing happens, silently), and `buffer` holds the per-channel memory bound this PR is required to settle as a number rather than a comment.

**Tech Stack:** Go 1.27.1, standard library only — `net/http`, `crypto/hmac`, `crypto/sha256`, `encoding/hex`, `os`, `strconv`, `testing`. No third-party module, now or through 2c-9; `go.sum` stays absent. `golangci-lint` 2.13.2 for lint, `go vet` for vet, `go test -race` for tests. Build inside Docker from a digest-pinned `golang` builder stage, cross-compiled to both published architectures. Task 0 alone is Python: DRF serializers and a Django `TestCase` in the `dispatcharr-testrunner` container, across three backend labels.

**Spec:** `docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md` — the `2c-1` row of § Stage 2c › The nine PRs (line 1795), § Stage 2c's `**Process.**` paragraph (line 1690), `**Concurrency.**` (line 1702), `**Buffer depth — an explicit open item**` (line 1709), `**Repo layout.**` (line 1723), `**Third-party Go dependencies: none.**` (line 1731), `**The two invariants**` (line 1738), § The contract (line 517, and the exact byte layout at lines 540-548), D5 (dev fallback), D6 (health/readiness), D7 (both gates, now met), § Testing's `go test -race` bullet (line 2086). Supporting: `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` (this PR's precondition), `apps/proxy/internal_auth.py`, `docker/entrypoint.sh`, `.github/workflows/frontend-tests.yml` (the four-part requireable shape), `.claude/hooks/run-affected-tests.sh` and `pre-commit-tests.sh` (the hook idiom).

**Branch:** `migration/phase2c-skeleton`, cut from `main` **after this plan has merged and after issue #258's hook fix has merged**. The `migration/**` prefix is load-bearing — it makes `e2e-tests.yml` run every Playwright project (CLAUDE.md § Full E2E runs).

---

## Global Constraints

Every task's requirements implicitly include this section.

1. **Anchor every command with an absolute path, or open it with a `cd` into your own worktree.** The shell's working directory has been observed in this programme drifting into another agent's worktree with no `cd` issued. A relative path that resolves somewhere else does not error; it writes a plausible file in the wrong tree. Every command in this plan is written to be run from the worktree root and every path in it is repo-relative from there — prefix each Bash call with `cd <your worktree> && `.

2. **`go test -race` is mandatory on every Go test run, everywhere: locally, in the hook, in the commit gate, in CI.** Spec § Testing (line 2086) states the reason and it is not stylistic: the concurrency model changes from gevent-cooperative (27 "threads" sharing one OS thread under a monkey-patch) to OS-thread-parallel goroutines, so a data race the Python implementation's execution model made *structurally impossible* becomes possible for the first time in this phase. `go test ./...` without `-race` is not a run; it is a compile check with extra steps. There is no "this package has no concurrency yet" exemption — the flag costs nothing on a small suite and the exemption is how it stops being habitual.

3. **Standard library only. No `require` line, no `go.sum`, ever.** Spec line 1731 calls this "a rule to defend, not an accident". Task 2 builds the mechanical check and Task 11 wires it into CI. If a task appears to need a dependency, stop and report — the answer is either that the task is out of 2c-1's scope or that the stdlib does it and the reach for a library was reflex.

4. **Exactly one Python *change* is in scope, and it is Task 0's `stream_profile.kind`.** The contract gap this plan found (Finding F1) is closed here — because the spec's own precondition is "a contract field for each allowlisted site, or a documented reason it needs none, **before** its first line of Go", and a `GAP` row in the reconciliation table is neither. Deferring the field would mean 2c-1 claiming a precondition it had not met. **Six files, named in Task 0 and nowhere else:**

   | File | Why |
   |---|---|
   | `apps/proxy/next_source.py` | the two helpers and the four call sites |
   | `apps/proxy/serializers.py` | the `kind` field on `StreamProfileRefSerializer` |
   | `apps/proxy/tests/test_redirect_transcode_flag.py` | the new tests |
   | `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` | two edge counts, two `closed_by` |
   | `apps/proxy/tests/test_next_source_api.py` | **fallout** — asserts exact dict equality on `ffmpeg_stream_profile` |
   | `apps/proxy/tests/test_next_source_resolution.py` | **fallout** — the same assertion at the resolver level |

   The last two are not optional and not discretionary. Both assert `assertEqual(source["ffmpeg_stream_profile"], {"id": …, "command": …, "args": …})` — **exact dict equality on three keys** — so a fourth key reddens them, and both live in `apps.proxy.tests`, which Task 0 Step 8 requires green. Step 6b updates them. **Any Python edit beyond these six is out of scope** — Task 14 Step 2 checks both directions mechanically.

5. **Every pin is tool-resolved on the day the PR is opened, never copied from this plan.** The values in Task 11 and Task 10 were resolved on 2026-09-13 and are recorded so the implementer can tell whether anything moved, not so they can be pasted. The spec's own `2c-1` gate (line 1795) makes re-resolution part of the gate: `go.dev/dl`, `docker buildx imagetools inspect` against the current `golang` tag, and fresh `gh api repos/<owner>/<repo>/commits/<tag> --jq .sha` lookups. **Confirm the publisher before trusting a SHA** — a plausible SHA on a same-named fork is worse than a floating tag, because it looks pinned (CLAUDE.md § Supply chain security).

6. **zizmor blocks on every finding in `go-tests.yml`, from its first commit.** The workflows are at zero findings and that is a ratchet. The edit hook runs zizmor on any `.github/workflows/*.yml` write; do not commit a workflow the hook has not passed. `persist-credentials: false` on every `actions/checkout`, top-level `permissions: contents: read`, every `uses:` a 40-character SHA with a trailing version comment.

7. **Do not add a Docker `HEALTHCHECK` in this PR.** D6 pairs the health endpoints with a `HEALTHCHECK` and a supervisord drain, and spec line 1802 assigns the drain to `2c-8`. A `HEALTHCHECK` wired to a `/readyz` that is a static 200 (which is what `2c-1`'s own row specifies) would report healthy through every real failure the probe exists to catch — a green light with nothing behind it, which is worse than no light.

8. **`relay-go` must share supervisord `priority=205` with `relay-uwsgi`, not take a priority of its own.** This is arithmetic, not taste. Supervisord stops one priority group at a time and waits out each group's `stopwaitsecs` before moving to the next, so the container's stop budget is the **sum** across groups. Today's `all` rung sums to 155s (postgres 30 + redis 5 + api-uwsgi 10 + relay-uwsgi 20 + daphne 10 + celery-default 30 + celery-dvr 30 + celery-beat 10 + nginx 10) against a `stop_grace_period: 160s` (`docker/docker-compose.yml:23`, `:157`, `:215`, `docker/docker-compose.aio.yml:13`). A `relay-go` at its own `priority=206` with `stopwaitsecs=20` would take that sum to **175s** and start every deploy exceeding its grace period by 15 seconds — a `SIGKILL` mid-shutdown, appearing as unexplained data loss long after this PR. At the same priority the two programs stop concurrently and the group contributes `max(20, 20) = 20`, leaving the sum at 155.

9. **Nothing in `relay/` may open a Postgres connection or a Redis connection, in any task, including a test.** These are the phase's two checkable success criteria (spec line 1738). At 2c-1 they hold trivially, because constraint 3 means there is no driver to link. Task 2's check is what keeps them holding when the module stops being trivial.

10. **Prefer `t.Setenv` over manual environment save/restore in tests, and never run an environment-mutating test with `t.Parallel()`.** `t.Setenv` restores on cleanup and, deliberately, panics if the test has called `t.Parallel()` — which is the language telling you the test is not safe to parallelise. Do not work around it by saving and restoring by hand; that reintroduces exactly the race `-race` is here to find.

11. **Task 0 runs Django tests, so it needs the shared `dispatcharr-testrunner` container, and the container is shared across agents.** Its bind mount points at exactly one worktree, and the `PostToolUse` hooks run in the harness's environment where `DISPATCHARR_TEST_CONTAINER` never reaches them — so an edit-triggered run always uses the container named `dispatcharr-testrunner`, whatever you intended, and tests whichever tree it is mounted at. Before Task 0's first edit:

    ```bash
    docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
    ```

    If it is not your worktree, re-point it with `.claude/hooks/start-test-container.sh` — **after** checking nobody else is mid-task in the tree it currently holds (`docker ps`, and `stat -f '%Sm %N'` on that tree's recently-touched files; a modification younger than a few minutes means occupied). Task 0's three backend labels take a few minutes; Tasks 1 onward need no container at all.

### The six ways a Go test can be green and meaningless

All six shapes below were found in real PRs in this repository in the four days before this plan was written. Every test this PR adds is bound by all six, and every task that adds an assertion ends with a **break-check**: patch the defect in, watch the test go red *for the right reason*, revert. A break-check that does not go red is a finding, not a formality — stop and fix the assertion.

1. **The tautological oracle — a test whose expected value is computed by the code under test cannot fail.** In this PR it has a sharper form than usual, because the subject is a *cross-implementation* contract. An HMAC test that calls the Go function to produce its own expectation proves the function is deterministic and nothing else. The expected digest must be a **literal, produced by the Python side**, so the test pins parity with `apps/proxy/internal_auth.py` rather than self-consistency. Task 4 ships such literals, generated from Django's own module; Task 4 Step 1 re-generates them rather than trusting this plan.

   **Wrong:**

   ```go
   func TestInternalRequestHeader(t *testing.T) {
       want := InternalRequestHeader(secret, "POST", "/api/relay/events", nil, 1789000000)
       got := InternalRequestHeader(secret, "POST", "/api/relay/events", nil, 1789000000)
       if got != want {
           t.Fatalf("header = %s, want %s", got, want)
       }
   }
   ```

   This passes with the context string spelled `internal_request`, with the field separator `|` instead of `\n`, with the body digest omitted entirely, and with SHA-512 in place of SHA-256. Every one of those 403s in production.

   **Right:**

   ```go
   func TestInternalRequestHeaderMatchesPython(t *testing.T) {
       // Produced by apps/proxy/internal_auth.internal_request_token() under
       // Django with SECRET_KEY="phase2c1-test-secret". Regenerate with the
       // script in Task 4 Step 1; never by calling the Go code above.
       const want = "v1.1789000000.5ce39464af1f52fac92ab6dd8101b289c2b9acce93d392216ac0dbcfa53a1fae"
       got := InternalRequestHeader(
           "phase2c1-test-secret",
           "POST",
           "/api/relay/channels/abc/next-source",
           []byte(`{"reason":"init"}`),
           1789000000,
       )
       if got != want {
           t.Fatalf("header = %s, want %s", got, want)
       }
   }
   ```

2. **A pin that supplies the default pins nothing.** A test must supply a value that could not arise by accident. `t.Setenv("DISPATCHARR_RELAY_GO_PORT", "5658")` and then asserting the port is 5658 passes with the whole environment-parsing branch deleted, because 5658 *is* the fallback. Assert the default and the override in two tests, and make the override's value one the default could never produce (`5999`).

3. **A test can go hollow without changing.** Ask of every assertion: *what edit to production code would make this fail?* If the answer is "none", it is not a test. A changed return value silently disarms an untouched test, and a diff-scoped review cannot see it — which is why every break-check in this plan names the edit it expects to redden the assertion.

4. **A fixture that patches away the subject its docstring names.** The rule: *patching the sink you assert against is how you observe; patching the logic that decides what reaches the sink is how you blind yourself.* In Go this arrives as an interface seam rather than a monkey-patch. A handler test that injects a fake router is observing; a handler test that injects a fake *handler* and asserts the fake was called has replaced the subject with a mirror.

   **Wrong — replaces the subject:**

   ```go
   func TestHealthz(t *testing.T) {
       called := false
       h := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called = true })
       h.ServeHTTP(httptest.NewRecorder(), httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/healthz", nil))
       if !called {
           t.Fatal("handler not called")
       }
   }
   ```

   This asserts that `http.HandlerFunc` calls the function you handed it. It passes with `httpapi` deleted.

   **Right — drives the real mux and asserts what a client would see:**

   ```go
   func TestHealthzReturns200(t *testing.T) {
       srv := New(Config{DevRoutes: false})
       rec := httptest.NewRecorder()
       srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/healthz", nil))
       if rec.Code != http.StatusOK {
           t.Fatalf("GET /healthz = %d, want 200", rec.Code)
       }
       if got := rec.Body.String(); got != "ok\n" {
           t.Fatalf("body = %q, want %q", got, "ok\n")
       }
   }
   ```

5. **A substring assertion pins nothing when the string has more than one source.** Before asserting on any log line or error message, grep for a second emitter of the same text. If there is one, pin the **value** the arm formats into the message, or pin the **record count** against the one entry point the test drives, or both. In Go this bites hardest on `err.Error()` checks: `strings.Contains(err.Error(), "secret")` passes for four different failures in Task 3's secret loader. Use `errors.Is`/`errors.As` against a named sentinel, or assert the full message.

6. **A true positive for a false reason.** A break-check can redden from a side effect of the edit rather than from the defect — a line number shifting, a doc comment going stale, a neighbouring test's fixture moving. **When a break-check reddens, read the failure message and confirm it names the mechanism.** "expected 5658, got 0" is the mechanism; "build failed" is not.

### Working rules

- **Run the four checks after every task, from the module root**, and treat any of the four failing as a stop:

  ```bash
  cd <your worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
  ```

- **`gofmt` is not optional and is enforced by the linter's formatter section.** Run `gofmt -w .` before committing; `golangci-lint run` fails on unformatted files.
- **Stage and commit in separate Bash calls.** The `PreToolUse` gate runs before the command, so a single call that does both is blocked outright.
- **Write commit messages to a file and commit with `-F`.** The gate matches on command text, so a heredoc containing the two words trips it (CLAUDE.md § Test hooks).
- **Every commit message ends with the attribution lines this session was given.**

---

## Rulings

Decisions this plan makes that the spec leaves open, or that the tree contradicts. Each is binding on the implementer; each names what it was decided against.

### R1 — `go-tests.yml` carries a `Go result` aggregate in the four-part shape **from this PR**, not from 2c-9.

The spec's `2c-9` row (line 1803) makes the gate "A new `go-tests.yml` **`Go result`** aggregate green, built in the four-part shape `CLAUDE.md` § Testing prescribes for every requireable check", and the `2c-1` row (line 1795) names only "`go build ./...`, `golangci-lint run`, `go vet ./...` all green; zizmor clean on `go-tests.yml` from its first commit". The rows are compatible either way — 2c-9 requires the aggregate to be **green**, which a workflow authored in the shape on day one satisfies without a rewrite.

Built here, for three reasons. **The shape is a repo-wide invariant, not a per-workflow choice**: CLAUDE.md § Testing states "Every test workflow now has that shape and a result aggregate — `E2E result`, `Lifecycle result`, `Backend result`, `Frontend result` — so each is requireable", and a fifth test workflow without one is the exception that erodes it. **Retrofitting it at 2c-9 leaves 2c-2 through 2c-8 — seven PRs and the entire Go implementation — running Go jobs that no aggregate covers**, so the shape's own failure mode (a skipped heavy job on a required run) goes unexercised for the whole stage and first gets tested on the PR that can least afford a surprise. **And it costs about thirty lines**, copied from `frontend-tests.yml`, which is the smallest existing instance of the shape.

What 2c-9 still owns is unchanged: the coverage job, the `scripts/coverage_live_path_go.floor` ratchet, and making `Go result` an *actually required* check on the Main ruleset — a repo-settings action, which the spec's own `2c-9` row already flags as not something a commit accomplishes.

### R2 — Buffer depth: **300 chunks, 76,760,400 bytes per channel**, derived below, shipped as a config default in this PR.

Spec line 1709 makes this "an explicit open item, not inherited... 2c's first PR must resolve with a real number, not carry forward unresolved". The user's decision is: derive it from Python's observable behaviour, cap per channel, no host constraint. The derivation, and every input with its `file:line`:

| Input | Value | Source |
|---|---|---|
| Chunk size | 255,868 bytes (`188 × 1361`) | `apps/proxy/config.py:15`, `BaseConfig.BUFFER_CHUNK_SIZE` |
| Retention | 60 seconds | `apps/proxy/config.py:71`, `settings.get("redis_chunk_ttl", 60)`, reached through `apps/proxy/live_proxy/config_helper.py:64-66` and applied at `apps/proxy/live_proxy/input/buffer.py:110` |
| Join point | 5 seconds behind live | `apps/proxy/config.py:57`, `new_client_behind_seconds`, read at `apps/proxy/live_proxy/config_helper.py:51`, used at `apps/proxy/live_proxy/output/ts/generator.py:268-272` |
| Reference bitrate | **10 Mbit/s** | Stated, not measured — see below |

**The reference bitrate is a stated assumption and must be labelled as one.** Nothing in the tree records a measured channel bitrate; `avg_bitrate_kbps` is displayed and never thresholded (CLAUDE.md § Failover: "No quality measurement exists"). 10 Mbit/s is the spec's own figure (line 1713) and is a realistic ceiling for a 1080p broadcast MPEG-TS remux, which is what the default FFmpeg profile produces. It is the number the cap is *sized* from; it is not a limit the relay enforces.

```
10,000,000 bit/s ÷ 8            = 1,250,000 byte/s
1,250,000 byte/s × 60 s         = 75,000,000 bytes of video per channel
75,000,000 ÷ 255,868            = 293.12 chunks
round up to a round number      = 300 chunks
300 × 255,868                   = 76,760,400 bytes  ≈ 73.2 MiB per channel
```

**Why a chunk count and a byte budget together, and not a duration.** Redis's TTL bounded *time* and let Redis's own eviction absorb the memory consequence. D2 deletes that absorber, so a time bound is no longer a bound at all — at twice the reference bitrate the same 60 seconds costs twice the memory, and nothing notices until the process is OOM-killed and every channel dies at once (spec § Risks, "Memory profile changes shape, not just size"). The cap is therefore expressed in **bytes**, which is the thing that must not grow, and converted to a chunk count by integer division at startup, because the chunk is the ring's eviction unit.

**Both bounds are enforced, whichever binds first**, and this is what preserves parity. Retention stays 60 seconds so a client's view of how far back the buffer reaches matches Python's; the byte cap sits behind it so memory is bounded regardless of bitrate. The two cross at `76,760,400 ÷ 60 = 1,279,340 byte/s = 10.23 Mbit/s`: below that the 60-second bound binds and behaviour is Python's exactly; above it the byte cap binds first and retention shortens. **That is a deliberate, stated divergence** and it is in the safe direction — a channel at 20 Mbit/s keeps 30 seconds instead of 60 and stays inside its memory budget, rather than keeping 60 seconds and taking the process down.

**The check that matters is the join point, not the retention.** A new client starts 5 seconds behind live, so the cap is only safe while 5 seconds of video is still resident. Five seconds at the reference bitrate is 6,250,000 bytes — 24.4 chunks of 300. The cap stops covering the join point only above `76,760,400 ÷ 5 = 15,352,080 byte/s = 122.8 Mbit/s`, an order of magnitude beyond anything this deployment serves. Task 5 pins both crossover figures as tests, because they are the two numbers that decide whether the cap is safe and neither is obvious from reading the constant.

**Aggregate, stated but not enforced:** ten concurrently-owned channels at the cap is 767,604,000 bytes ≈ 732 MiB resident in one process. That matches the spec's own ~750 MB estimate. **No host-memory check is implemented** — per the user's decision, the cap is per channel, full stop. Sizing the relay against real channel counts is spec § Risks' explicit pre-deployment item, not this PR's.

### R3 — One package beyond the spec's five: `config`.

Spec line 1723 names `channel`, `buffer`, `ffmpeg`, `control`, `httpapi` and says the split is "by concern". `config` is not a sixth concern; it is the wiring inputs — the environment and `/data/jwt`. It gets its own package rather than living in `package main` for one reason: the `/data/jwt` read has a whitespace rule that is easy to get subtly wrong and impossible to test from outside `main` (Task 3 Finding). Everything else about the layout follows the spec exactly, including the instruction *not* to mirror `apps/proxy/live_proxy/`'s file layout.

### R4 — Both Go hooks anchor on the **edited or staged file's own path**, following `_hook_common.sh`'s precedent, and walk up for `go.mod` rather than calling its helper.

**The precedent, as merged.** Issue #258 (PR #280, on `main` at `b1cab647`) moved both Python hooks off deriving their root from their own script path. `.claude/hooks/run-affected-tests.sh` now sources `_hook_common.sh` and sets `REPO_ROOT="$(hook_repo_root "$(dirname "$FILE")")"` — anchored on the edited file, with `CLAUDE_HOOK_REPO_ROOT` as the documented override. The helper's own header states the failure it closes: `CLAUDE_PROJECT_DIR` is pinned to the main checkout for every agent session regardless of which worktree it works in, so a label computed relative to it came out as nonsense like `.worktrees.fix-258.apps.proxy.tests` and the hook reported FAILED regardless of the real outcome.

**The Go hooks follow that rule and cannot use that function.** `hook_repo_root` returns the **repo** root; a Go hook needs the **module** root, which is `<repo>/relay` today and is defined by where `go.mod` sits, not by where `.git` does. Running `go build ./...` from the repo root would find no module at all. So the Go hook walks up from the edited file for `go.mod` — the same anchor, resolving a different thing.

That is the whole justification. **Do not repeat this plan's earlier reasoning**, which described the pre-#280 `run-affected-tests.sh` in the present tense and cited a `case` fallthrough at `:39-43` that is now unreachable, because `REPO_ROOT` is derived correctly before it. The conclusion was right and the evidence for it is gone; citing a defect that has been fixed is how a plan teaches an implementer something false.

**What the Go hook still borrows from the helper:** `hook_canon_path` for the walk's starting directory (`pwd -P`, so a symlinked spelling of the same path compares equal — a plain `cd … && pwd` does not), and `CLAUDE_HOOK_REPO_ROOT` honoured the same way, so a manual or test run can pin the tree. `settings.json` still locates the *script* through `${CLAUDE_PROJECT_DIR:-.}`, unchanged by #280 and irrelevant here: what the script does once it runs is what R4 governs.

### R5 — `relay-go` runs in `all`, `relay` **and** `all-dev`.

The spec says roles `all` and `relay` (line 1690). `docker/supervisord/relay.conf`'s include is a glob — `files = /app/docker/supervisord.d/relay-*.conf` — so the `relay` role picks up `relay-go.conf` with no edit. `all.conf` and `all-dev.conf` carry explicit file lists and each needs one path appended. `all-dev` is the rung `DISPATCHARR_ENV=dev` selects for role `all` (`docker/entrypoint.sh:491`), so including it is what "role `all`" means in dev — and it is the only shape where this PR's dev-gated route is reachable at all, which makes leaving it out equivalent to shipping the flag dead.

### R6 — CodeQL gets no `go` language pack in this PR, and the gap is recorded in the spec, not in a report.

`codeql.yml:54` analyses `[actions, python, javascript-typescript]`. Go is a real gap and it should close, but not here: at 2c-1 the module is three tested packages and three stubs, so a Go pack would analyse almost nothing while adding a build-mode configuration to debug. **Owner: 2c-9**, alongside the coverage ratchet, when there is a relay to analyse. Task 1 Step 4 writes it into Amendment A1 as a 2c-9 input — a PR description is read once and a spec amendment is read by whoever plans 2c-9, which is the person who needs it.

### R7 — The Docker builder stage cross-compiles; it does not emulate.

`docker-build.yml:88` builds `linux/amd64,linux/arm64` in one buildx invocation. A builder stage written as a plain `FROM golang:...` runs the arm64 leg under QEMU emulation — minutes of emulated compilation per build, for a binary Go can cross-compile natively in about a second. The stage is therefore `FROM --platform=$BUILDPLATFORM` with `ARG TARGETOS`/`TARGETARCH`, verified working for both targets in Task 10.

### R8 — `kind` is derived in **one** helper, not copied into four dicts, and doing so moves an allowlist number.

The lead's ruling names three construction sites plus the serializer. There is a fourth dict of the same shape — `_locked_ffmpeg_profile()` (`apps/proxy/next_source.py:97-100`), which is rendered by the *same* `StreamProfileRefSerializer` — so a required `kind` on that serializer obliges all four. Rather than write the derivation out four times, Task 0 adds two small private helpers and routes all four through them.

**The evidence for the helper is in the tree, not a preference.** `apps/proxy/tests/test_redirect_transcode_flag.py`'s own docstring records a production defect caused by exactly this duplication: the `transcode` derivation existed at two points, they disagreed about Redirect, and "every reconnect spawned an empty executable" during a recording. A second per-profile fact derived independently in four places is that defect's shape, pre-built.

**The consequence, which is easy to miss:** `is_redirect` and `is_proxy` are methods on `StreamProfile`, a Django model, so `zero_orm_scan.py`'s `model_method_names()` includes them (`zero_orm_scan.py:60-82`) and `_hits_in` flags every `x.is_redirect()` call site (`:97`). The helper adds two flagged lines inside `resolve_source`'s reachable subtree, so **both `resolve_source` EDGE entries' `hits` counts move** and the allowlist's ratchet fires until they are updated. Measured at `0c1654d8`, the current counts are `resolve_source` **36** and `get_stream_object` **3**, matching the allowlist exactly:

```bash
cd <your worktree> && python3 -c "
import sys; sys.path.insert(0, '.')
from apps.proxy.live_proxy.tests.zero_orm_scan import scan_edge, Edge
for name in ('resolve_source', 'get_stream_object'):
    print(name, len(scan_edge(Edge('x', 'apps.proxy.next_source', name))))
"
```

The scanner is pure AST and needs no Django, so this runs anywhere. **Prediction: 36 becomes 38, and `get_stream_object` stays 3.** It is a prediction and Task 0 Step 5 replaces it with a measurement — do not write 38 into the allowlist without running the command.

**This is a ratchet moving for a real reason, which is the only kind of move that is allowed.** Two new ORM-shaped call sites genuinely exist; they issue no query (both compare `self.locked` and `self.name` on an already-loaded instance, `core/models.py:127-135`), which is why they are allowlisted rather than removed, and the count moving is the ratchet doing its job rather than a number being tuned to fit.

---

## The allowlist reconciliation — this PR's precondition

**This is Task 1's deliverable and it is written here, in full, so the implementer transcribes rather than researches.** Spec line 1795 states the precondition: if `zero_orm_allowlist.py` is non-empty, this PR's description names, for every entry, **either** the contract field that closes it **or** the written reason the Go relay never asks that question. Line 1738 explains why it matters: the "no Postgres driver" invariant falls out of 2b *conditionally*, and both coverage gates can be green with this punch list untouched.

The spec is explicit that this precondition is enforced by the PR description and its reviewer, not by CI (line 1795: "deciding whether a written reason for skipping a contract field is a *good* reason is not a grep"). The reasoning quality is the whole gate.

**Counts, measured at `0c1654d8`:** 12 `SITES`, 11 `EDGES`, 7 `SQL_SIGNATURES`, 6 `INLINE_AUTHORIZE_SIGNATURES` — **36 entries**. Verified with an AST count rather than by eye:

```bash
cd <your worktree> && python3 -c "
import ast
t = ast.parse(open('apps/proxy/live_proxy/tests/zero_orm_allowlist.py').read())
for n in t.body:
    if isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple):
        print(n.targets[0].id, len(n.value.elts))
"
```

The contract fields cited below were each read in the tree, not taken from the allowlist's own `closed_by` prose. Every `file:line` here was verified at `0c1654d8`.

### SITES — 12 entries

| # | Site | ORM read | Closed by | Evidence | Verdict |
|---|---|---|---|---|---|
| S1 | `channel_status.py:74` | `Stream.objects.filter(id=…).first()` — the `stream_name` fallback | **No field, and none is needed: absence is the contract.** `stream_name` is declared `required=False` with no `default=`, so DRF's `Field.get_attribute` raises `SkipField` and the key is **absent** from the JSON, not `null`. A relay with no database always omits it, which is inside the contract rather than a divergence from it. | `apps/proxy/relay_serializers.py:111`; parity matrix row 18 | Reason, verified |
| S2 | `channel_status.py:106` | `M3UAccountProfile.objects.filter(id=…).first()` — the `m3u_profile_name` fallback | As S1, same mechanism, same row. | `apps/proxy/relay_serializers.py:113`; row 18 | Reason, verified |
| S3 | `config_helper.py:50` | `TSConfig.get_proxy_settings()` → `CoreSettings.get_proxy_settings` | **`proxy_settings` on the next-source response.** Attached by `_with_proxy_settings` on all four of `resolve_source`'s return paths. | `apps/proxy/next_source.py:699`, wrapper at `:679-701`, applied at `:869`, `:874`, `:877`, `:897` | Field, verified — **see F4** |
| S4 | `views.py:132` | `CoreSettings.get_default_output_format()` on the trusted branch | **`X-Relay-Output-Format`**, the sixth relay header 2b-2 added; the hop resolves it on every live tune. | Set at `apps/proxy/authorize_views.py:353`; name at `apps/proxy/internal_auth.py`'s `HEADER_RELAY_OUTPUT_FORMAT` | Field, verified |
| S5 | `views.py:152` | `OutputProfile.objects.filter(id=…, is_active=True)` | **`output_profiles` on the next-source response** — the whole active set, each as `{id, argv}`, so the relay caches the map per channel and serves every later client from memory. | `apps/proxy/next_source.py:748`, built at `:726-747` | Field, verified |
| S6 | `views.py:444` | `channel.get_stream_profile()` (an FK accessor plus `StreamProfile.objects.get`) | **`stream_profile` on the next-source `source` dict**, as `{id, command, args}`. | `apps/proxy/next_source.py:512-518`, `:574-580`, `:621-627` | Field, verified |
| S7 | `input/manager.py:785` | `channel.get_stream_profile()` | As S6, same field. | as S6 | Field, verified |
| S8 | `input/manager.py:788` | `channel.get_stream_profile()` | As S6, same field. | as S6 | Field, verified |
| S9 | `views.py:766` | `OutputProfile.build_command()` — a model **method**, no query | **Nothing to close, and the Go equivalent exists**: `OutputProfile.build_command` is `[self.command] + shlex_split(self.parameters)`, and Django already runs it when it builds `output_profiles[*].argv`. Go reads the finished argv. | `core/models.py:200-203`; `apps/proxy/next_source.py:747` | Reason, verified |
| S10 | `input/manager.py:791` | `StreamProfile.build_command(url, ua, channel_id)` — a model method, no query | **Nothing to close as an ORM matter**, and the Go relay reproduces it from `stream_profile.command` + `stream_profile.args`. Its `is_proxy()/is_redirect()` early return is unreachable in Go because the relay only reaches this path when `transcode` is true. | `core/models.py:137-166`; `transcode` at `apps/proxy/next_source.py:511`, computed `:504` | Reason, verified — **see F3** |
| S11 | `views.py:462` | `stream_profile.is_redirect()` — a model method, no query | **`stream_profile.kind`, the one contract field this PR adds** (Task 0). "No query" is true as an ORM statement and does not answer this precondition: the Go relay *must* ask whether the profile is Redirect, because `:462` decides between a 302 and the Proxy path and applies the internal-principal override that forces Redirect through Proxy. Before Task 0 nothing on the wire could answer — see Finding **F1** for the analysis and why the field lands here rather than in 2c-5. | `core/models.py:132-135`; call site `apps/proxy/live_proxy/views.py:462-467`; field added at `apps/proxy/serializers.py`'s `StreamProfileRefSerializer` | Field, added by this PR |
| S12 | `views.py:468` | `stream_profile.is_redirect()` | As S11, the `elif` arm that performs the redirect URL validation. Same field. | `apps/proxy/live_proxy/views.py:468-480` | Field, added by this PR |

**Zero gap rows.** Every one of the thirty-six entries closes on a named contract field or a written reason, which is what the spec's precondition asks for. The two rows above were gaps when this plan was first drafted and are closed by Task 0 rather than deferred; the analysis that found them is kept as Finding F1 rather than deleted, because the reasoning is what a reviewer audits.

### EDGES — 11 entries

| # | Importer ← symbol | Hits | Closed by | Evidence | Verdict |
|---|---|---|---|---|---|
| E1 | `views.py` ← `apps.proxy.next_source.resolve_source` | 36 | **`POST /api/relay/channels/<id>/next-source` carrying `target_stream_id`.** The operator switch becomes a control-plane round trip instead of an import; 2c-8 owns the route. | Payload key at `apps/proxy/control_plane.py:179-180` (parameter `:152`); server side `apps/proxy/next_source.py:871-872`, switch resolution `:192-214` | Field, verified |
| E2 | `services/channel_service.py` ← `resolve_source` | 36 | As E1 — a separate allowlist entry only because the allowlist is per `(importer, module, symbol)`; the same route closes it. | as E1 | Field, verified |
| E3 | `url_utils.py` ← `next_source.get_stream_object` | 3 | **next-source's own identifier resolution.** `get_stream_object` accepts a channel UUID and falls back to a `stream_hash`, so the Go relay forwards whatever identifier arrived in the URL and Django resolves it. | `apps/proxy/next_source.py:103-113`; parity matrix row 16 | Field, verified |
| E4 | `client_manager.py` ← `apps.proxy.config.TSConfig` | 5 | **`proxy_settings` on next-source**, as S3. The five flagged classmethods (`get_channel_shutdown_delay`, `get_buffering_timeout`, `get_buffering_speed`, `get_channel_init_grace_period`, `get_channel_client_wait_period`) all read that one group. | `apps/proxy/next_source.py:699` | Field, verified — **see F4** |
| E5 | `config_helper.py` ← `TSConfig` | 5 | As E4. | as E4 | Field, verified |
| E6 | `input/manager.py` ← `TSConfig` | 5 | As E4. | as E4 | Field, verified |
| E7 | `output/ts/generator.py` ← `TSConfig` | 5 | As E4. | as E4 | Field, verified |
| E8 | `server.py` ← `TSConfig` | 5 | As E4. | as E4 | Field, verified |
| E9 | `views.py` ← `apps.proxy.authorize.resolve_output_format` | 1 | **`X-Relay-Output-Format` on a trusted tune** (S4's header). On the nginx-less path the same resolution happens in Django behind `POST /_dispatcharr/authorize-internal` and comes back as a response header — the Go relay never runs `resolve_output_format` in either shape. | `apps/proxy/authorize_views.py:353`; spec § The contract's dev-fallback response, 200 shape | Field, verified |
| E10 | `views.py` ← `apps.proxy.authorize.resolve_output_profile` | 2 | **`X-Relay-Output` on a trusted tune**; the hop resolves `?output_profile=` and the user's `custom_properties` once and puts the id on the header. Dev shape as E9. | `apps/proxy/authorize_views.py:346` | Field, verified |
| E11 | `views.py` ← `apps.proxy.authorize_views.resolve_authorization` | 1 | **A written reason, and it is D1.** The `User.objects.filter(id=…).first()` sits in the `else` arm of `if surface in (SURFACE_LIVE, SURFACE_LIVE_XC)`. The Go relay serves **only** live surfaces — `/proxy/ts/stream/` and the XC live roots — so it can never enter that arm. VOD, catch-up and `timeshift.php` keep the code verbatim in the Python relay, which is exactly what D1 scopes. `X-Relay-User` carries the identity the live arm needs. | Surface split per the allowlist's own entry; `X-Relay-User` at `apps/proxy/authorize_views.py:348`; D1 at spec line 440 | Reason, verified |

### SQL_SIGNATURES — 7 entries

These are the runtime half of the guard: SQL text observed executing under a relay stack frame. Each maps onto a SITE or EDGE already reconciled above, so each inherits that row's closure rather than getting a new one.

| # | Signature | Produced by | Closed by |
|---|---|---|---|
| G1 | `channel_by_uuid` | E3 (`get_stream_object`) | Identifier passthrough — Django resolves it on next-source |
| G2 | `channel_override_fk_accessor` | S6 / S8 (`get_stream_profile`'s FK touch) | `stream_profile` on next-source |
| G3 | `stream_profile_by_id` | S6 / S7 / S8 | `stream_profile` on next-source |
| G4 | `output_profile_for_this_client` | S5 | `output_profiles` on next-source |
| G5 | `stream_name_fallback` | S1 | Absence is the contract (row 18) |
| G6 | `m3u_profile_name_fallback` | S2 | Absence is the contract (row 18) |
| G7 | `proxy_settings_group` (params `'proxy_settings'`) | S3, E4–E8 | `proxy_settings` on next-source — **see F4** |

### INLINE_AUTHORIZE_SIGNATURES — 6 entries

**One written reason covers all six, and it is structural.** These record what the *inline, untrusted* authorize path executes — the path taken when nginx did not authorize the tune. The Go relay never executes `authorize_stream` in any shape: with nginx it reads the seven `X-Relay-*` headers the hop set; without nginx it asks Django over `POST /_dispatcharr/authorize-internal` (D5 exception 2, spec § The contract's dev-fallback section, owned by 2c-8). Every query below therefore runs **in the Django process** in both shapes, and in neither shape does a Go process issue it.

| # | Signature | Runs in Django because | Relay-side equivalent |
|---|---|---|---|
| I1 | `inline_proxy_settings_group` | `TSConfig.get_proxy_settings()` reached from the untrusted tune's own channel setup | `proxy_settings` on next-source (G7) |
| I2 | `inline_network_access_settings` | `network_access_allowed()` runs on **every** `authorize_stream` call, before the ACL check and regardless of principal | Nothing — the ACL decision arrives as the hop's 2xx/4xx, or as the authorize-internal response |
| I3 | `inline_channel_by_uuid` | `get_stream_object` twice: once inside `resolve_authorization`'s inline branch, once at `stream_ts`'s own call | Identifier passthrough (G1) |
| I4 | `inline_channel_override_fk_accessor` | `channel.get_stream_profile()`'s FK accessor on the inline path | `stream_profile` on next-source (G2) |
| I5 | `inline_stream_profile_by_id` | `StreamProfile.objects.get` inside the same call | `stream_profile` on next-source (G3) |
| I6 | `inline_default_output_format` (params `'stream_settings'`) | `resolve_output_format`'s last-resort `CoreSettings.get_default_output_format()`, reached because `decision.trusted` is False | `X-Relay-Output-Format` on a trusted tune; the authorize-internal 200's own header in the dev shape (E9) |

### Findings — four, with their rulings

These are reported, not smoothed over. F1 was a real gap in the contract and is **closed by this PR** (Task 0); F2 is a gap in the spec's PR table, assigned to 2c-5; F3 and F4 need an owner, and F4 turns out to be fixable on the Python side rather than merely documented. All four are written into Amendment A1 by Task 1 Step 4, because a spec amendment reaches whoever plans the owning PR and a PR description does not.

#### F1 — **the contract cannot tell the Go relay that a Stream Profile is Redirect.** (S11, S12)

`StreamProfile.is_redirect()` is `self.locked and self.name == REDIRECT_PROFILE_NAME` (`core/models.py:132-135`) — a name comparison. The next-source `source` dict carries `stream_profile` as `{id, command, args}` (`apps/proxy/next_source.py:512-518`) and a boolean `transcode` computed as `not (is_proxy() or is_redirect())` (`:504`, sent at `:511`). **`transcode` collapses Proxy and Redirect onto the same `False`**, and both locked profiles carry empty `command` and `parameters` (stated in `core/models.py:139-144`'s own comment), so there is no field on the wire — and no inference from the fields that are — by which a Go relay can distinguish the two.

It has to. `apps/proxy/live_proxy/views.py:462-467` serves a 302 for Redirect, except for an internal principal (the DVR), where it forces the Proxy path so the `X-Dispatcharr-Internal` header is never re-sent to a third-party provider — a deliberate Phase 1 PR 5 fix against handing a provider a deployment credential. `:468-480` then validates the redirect URL over HTTP. Neither behaviour is reachable without the answer.

**Proposed fix, minimal and additive:** one key on the existing `stream_profile` object,

```python
"kind": "redirect" if stream_profile.is_redirect() else ("proxy" if stream_profile.is_proxy() else "transcode"),
```

at the three construction sites (`next_source.py:512-518`, `:574-580`, `:621-627`) plus the corresponding serializer field — and at the fourth dict of the same shape the lead's ruling did not name, `_locked_ffmpeg_profile()` (`:97-100`), which the *same* serializer renders. Task 0 routes all four through one helper rather than writing the derivation out four times; Ruling R8 has the reasoning and the allowlist consequence. `transcode` stays exactly as it is — D5 forbids changing what already exists.

**Implemented in this PR, by Task 0.** The first draft of this plan deferred it to 2c-5 on the grounds that 2c-1 edits no Python; that was overruled, correctly, on two points from the spec's own text. The precondition is "a contract field for each allowlisted site, or a documented reason it needs none, **before** its first line of Go" — a deferred field leaves a `GAP` row, which is neither, so 2c-1 could not honestly claim the precondition met. And the **first consumer is 2c-2, not 2c-5**: 2c-2 is the *Proxy* vertical slice, and Go cannot know a profile is Proxy rather than Redirect without this field. A contract field must exist before its first consumer, and 2c-2 is the PR immediately after this one.

What stays with 2c-5 is the Go **behaviour** the field enables — the 302, the URL validation, the internal-principal override. That is F2.

#### F2 — **no PR in the nine owns the Redirect Stream Profile architecture.**

Walking the table at spec line 1783: 2c-2 is "the Proxy stream-profile architecture only (no ffmpeg spawn yet)"; 2c-3 is fan-out; 2c-4 is ffmpeg; 2c-5 is failover and the control-plane client; 2c-6 is fMP4; 2c-7 is Output Profiles; 2c-8 is the remaining control routes, the drain and the dev fallback; 2c-9 is the coverage ratchet. **Redirect — one of the three architectures D5 names explicitly — appears in none of them.** The parity matrix does not compensate: Redirect is mentioned in exactly one row (row 29, and only as a surface on which the buffering detector is inert), so there is no `owed:` marker that would have caught the omission either.

**Assigned to 2c-5**, ruled. Redirect's work is a 302, an HTTP probe of the provider URL (`validate_stream_url`), and a fallback across the channel-start-cached alternates when the probe fails — the same cached candidate list 2c-5 already owns for the degraded next-source fallback. The internal-principal override rides along with it.

**The ownership must be written into the spec's PR table row itself, not into prose beside it, and the reason is mechanical.** The usual way to record an unclosed behaviour in this phase is an `owed:` marker on a parity-matrix row, and that route is shut. Gate 1 closed in 2b-3 precisely because no row is owed any more, and the guard asserts it stays that way: with `GATE_1_CLOSED` true, `e2e/tests/guards/parity-matrix.spec.ts:308-314` requires the owed-row list to be **empty**, failing with "Gate 1 … cannot silently reopen" on any row that carries one. Adding an `owed:` row for Redirect would therefore redden a closed gate to record a note. So the spec's `2c-5` row is the only place this ownership can live, and a sentence near the table is not the table. Task 1 Step 4 edits the row itself.

#### F3 — **`shlex.split` has no standard-library equivalent in Go, and the contract is asymmetric about it.**

`output_profiles[*].argv` arrives **pre-split**: Django runs `OutputProfile.build_command()` (`core/models.py:200-203`, a `shlex_split`) and puts the finished list on the wire (`next_source.py:747`). `stream_profile.args` arrives **raw** — the `parameters` text field, unsplit (`next_source.py:515`). So the Go relay must implement POSIX shell word-splitting itself, plus the three placeholder substitutions `{streamUrl}`, `{userAgent}`, `{channelId}` (`core/models.py:147-160`), for the one argv that spawns ffmpeg.

Constraint 3 forbids a library, so this is roughly sixty lines of Go plus a differential test against Python's `shlex.split` over a corpus of real `parameters` values. **Owner: 2c-4**, ruled, and carried into Amendment A1 as a named *input* to 2c-4's plan rather than a note in this PR's description — 2c-4 is planned by a `fable` agent that will not have read this document, and the two `next_source.py` line cites are what stop it rediscovering the asymmetry from scratch. The alternative it should weigh there — extending the contract with a pre-split `stream_profile.argv_template`, the way `output_profiles` already is — is recorded with it; this plan does not decide it.

#### F4 — **`proxy_settings` carries the stored group, and every default lives in Python class attributes the wire never carries.**

`CoreSettings.get_proxy_settings()` returns the settings group as stored. When a key is absent, Python falls through to `ConfigHelper.get(name, default)`, which is `getattr(Config, name, default)` — so the effective value comes from `BaseConfig`'s class attributes (`apps/proxy/config.py:6-19`), which are never serialised. A Go relay receiving `proxy_settings` therefore needs its own copy of every default, and the two copies can drift silently: a default changed in `apps/proxy/config.py` reaches the Python relay immediately and the Go relay never.

This is exactly the trap CLAUDE.md already records for `BUFFER_CHUNK_SIZE`, where an unreachable `5644` literal in `buffer.py` makes the effective chunk a quarter of what the call site looks like.

**Owner: 2c-2, and the fix is on the Python side, not the Go one** — ruled, and it is the better answer than the mitigation this plan first proposed. Django should send **effective** `proxy_settings`: the stored group merged over `BaseConfig`'s class-attribute defaults (`apps/proxy/config.py:6-19`), so every key the relay reads is present with a real value and Go holds no second copy to drift. That is additive on the wire — keys that were absent become present carrying the default they already had in effect — so no existing consumer moves. 2c-2 is the first Go consumer of settings, so it lands there; Amendment A1 records it with the `file:line`.

**Not folded into this PR**, even though it is Python and Task 0 is already Python. Task 0 exists because the precondition cannot be met without it; F4's fix has no such forcing argument, its first consumer is 2c-2, and widening 2c-1's Python footprint past the one field it must add is how a skeleton PR becomes a contract PR. This PR still sets the *pattern* in Task 5 — every Go constant mirroring a Python literal carries its source `file:line` in a comment and is pinned by a test naming the same location — because the buffer constants are the one place 2c-1 unavoidably holds such a copy.

---

## File Structure

```
relay/                                     NEW — the Go module
├── go.mod                                 module github.com/D10Scot/Dispatcharr/relay, go 1.27.1
├── main.go                                wiring only: config → server → ListenAndServe
├── config/
│   ├── config.go                          env + /data/jwt, the port, the dev flag
│   └── config_test.go
├── control/
│   ├── token.go                           the three HMAC primitives (§ The contract)
│   └── token_test.go                      Python-produced vectors
├── httpapi/
│   ├── server.go                          the mux, /healthz, /readyz, the dev-gated stub
│   └── server_test.go
├── buffer/
│   ├── buffer.go                          the depth constants and their derivation (R2)
│   └── buffer_test.go
├── channel/
│   └── channel.go                         documented stub — 2c-2 fills it
└── ffmpeg/
    └── ffmpeg.go                          documented stub — 2c-4 fills it

.golangci.yml                              NEW — linter config, v2 schema
.github/workflows/go-tests.yml             NEW — changes / build / lint / Go result
scripts/check_go_stdlib_only.sh            NEW — the go.sum-empty backstop
docker/supervisord.d/relay-go.conf         NEW — priority 205, shared with relay-uwsgi (R2/GC8)
.claude/hooks/run-go-checks.sh             NEW — PostToolUse on relay/**/*.go

docker/Dockerfile                          EDIT — a cross-compiling relay-builder stage
docker/supervisord/all.conf                EDIT — one path on the include list
docker/supervisord/all-dev.conf            EDIT — one path on the include list
.gitattributes                             EDIT — one line, *.go text
.gitleaks.toml                             EDIT — allowlist the five HMAC parity vectors, by value
.claude/settings.json                      EDIT — a second PostToolUse hook entry
.claude/hooks/pre-commit-tests.sh          EDIT — a Go section in the commit gate
CLAUDE.md                                  EDIT — § Commands, § Architecture, § Test hooks, § Testing
docs/superpowers/specs/2026-09-09-…-design.md   EDIT — Amendment A1, the 2c-5 row, a Done log row

                                           --- Task 0, the only Python ---
apps/proxy/next_source.py                  EDIT — _profile_kind + _stream_profile_ref, four call sites
apps/proxy/serializers.py                  EDIT — StreamProfileRefSerializer.kind
apps/proxy/tests/test_redirect_transcode_flag.py        EDIT — five tests, two fixtures
apps/proxy/live_proxy/tests/zero_orm_allowlist.py       EDIT — two EDGE hits counts, two closed_by
apps/proxy/tests/test_next_source_api.py                EDIT — fallout: exact-dict assertion gains "kind"
apps/proxy/tests/test_next_source_resolution.py         EDIT — fallout: the same, at the resolver level
```

Nothing under `core/`, `dispatcharr/`, `frontend/`, `e2e/` or `metrics/` is touched, and nothing under `apps/` beyond Task 0's six files.

---

## Task 0: `stream_profile.kind` — the one contract field this PR adds

**The only Python in this PR** (Global Constraint 4), and it comes first for two reasons: the spec puts the precondition "before its first line of Go", and Task 1's reconciliation table cites this field as the closer for `views.py:462` and `:468`, so the field should exist in the tree when that table is written rather than name something the implementer intends to add later.

Read Ruling R8 before starting. It explains why four dicts are involved rather than three, and why this task moves a number in `zero_orm_allowlist.py`.

- [ ] **Step 1: Read the four construction sites and the serializer**

  ```bash
  cd <your worktree>
  sed -n '75,101p'   apps/proxy/next_source.py   # _locked_ffmpeg_profile, the fourth dict
  sed -n '495,525p'  apps/proxy/next_source.py   # resolve_initial_source's stream branch
  sed -n '556,590p'  apps/proxy/next_source.py   # the channel branch
  sed -n '600,635p'  apps/proxy/next_source.py   # _source_from_info
  sed -n '12,40p'    apps/proxy/serializers.py   # StreamProfileRefSerializer
  sed -n '127,136p'  core/models.py              # is_proxy / is_redirect
  ```

  All four dicts are `{"id": …, "command": …, "args": …}` and all four are rendered by `StreamProfileRefSerializer` — the three inside `source["stream_profile"]`, the fourth as `source["ffmpeg_stream_profile"]`. Line numbers drift; find them by shape.

- [ ] **Step 2: Add the two helpers in `apps/proxy/next_source.py`**

  Place them immediately above `_locked_ffmpeg_profile()`, since that is now the first caller in file order.

  ```python
  def _profile_kind(profile):
      """Which of the three Stream Profile architectures this profile is.

      Phase 2 PR 2c-1. The wire already carries `transcode`, which is
      `not (is_proxy() or is_redirect())` -- one boolean collapsing Proxy
      and Redirect onto the same value, because from the relay's old
      point of view they agreed on the only question it was asking
      ("do I spawn a subprocess?"). A Go relay asks a second question
      the boolean cannot answer: Redirect means answer 302 and validate
      the provider URL, Proxy means read the bytes into the ring buffer.
      Both locked profiles carry empty command/parameters
      (core/models.py:139-144), so nothing else on the wire separates
      them either.

      `transcode` is deliberately NOT changed or derived from this --
      D5's strict parity forbids altering what already exists, and every
      current consumer keeps reading exactly the boolean it reads today.

      No query: is_redirect()/is_proxy() compare self.locked and
      self.name on an already-loaded instance (core/models.py:127-135).
      They are model METHODS, so zero_orm_scan.py flags the two calls
      below by name -- see the EDGE entries in zero_orm_allowlist.py.
      """
      if profile.is_redirect():
          return "redirect"
      if profile.is_proxy():
          return "proxy"
      return "transcode"


  def _stream_profile_ref(profile):
      """A StreamProfile flattened to the wire shape StreamProfileRefSerializer renders.

      One construction site for what used to be four near-identical dict
      literals. That duplication has already cost this module a
      production defect once: the `transcode` derivation lived at two
      points, they disagreed about Redirect, and every reconnect during
      a recording spawned an empty executable
      (apps/proxy/tests/test_redirect_transcode_flag.py's own docstring).
      A second per-profile fact derived independently in four places is
      that defect pre-built.
      """
      return {
          "id": profile.id,
          "command": profile.command,
          "args": profile.parameters,
          "kind": _profile_kind(profile),
      }
  ```

- [ ] **Step 3: Route all four dicts through the helper**

  `_locked_ffmpeg_profile()`'s return becomes:

  ```python
      return _stream_profile_ref(profile)
  ```

  and each of the three `"stream_profile": {...}` literals becomes:

  ```python
                      "stream_profile": _stream_profile_ref(stream_profile),
  ```

  In `_source_from_info` the local is also named `stream_profile` (from `StreamProfile.objects.get(id=info["stream_profile"])`), so the same line works there. **Do not touch the `transcode` computations** at `:295`, `:504` and `:563`.

  Then confirm the wire result by eye — four dicts, one helper, no literal `"args":` left in the module except inside the helper:

  ```bash
  cd <your worktree> && grep -n '"args"' apps/proxy/next_source.py
  ```

  Expect exactly one hit, inside `_stream_profile_ref`.

- [ ] **Step 4: Add the serializer field**

  In `apps/proxy/serializers.py`'s `StreamProfileRefSerializer`, after `args`:

  ```python
      # Phase 2 PR 2c-1. Which of the three Stream Profile architectures
      # this is: "redirect", "proxy" or "transcode". Required, not
      # optional -- every producer goes through next_source.py's
      # _stream_profile_ref(), so there is no shape that can omit it, and
      # a Go relay that has to guess is the gap this field closes
      # (spec § Stage 2c, Amendment A1.1).
      #
      # NOT a ChoiceField: the three values are a closed set today, and a
      # ChoiceField would make adding a fourth architecture a wire-schema
      # change that 400s a relay one version behind. A relay reading an
      # unrecognised kind should degrade, not be told the payload is
      # invalid by its own control plane.
      kind = serializers.CharField()
  ```

- [ ] **Step 5: Re-measure the two allowlist edge counts and update them**

  Ruling R8 predicts 36 → 38. **Measure it; do not write the prediction.**

  ```bash
  cd <your worktree> && python3 -c "
  import sys; sys.path.insert(0, '.')
  from apps.proxy.live_proxy.tests.zero_orm_scan import scan_edge, Edge
  for name in ('resolve_source', 'get_stream_object'):
      print(name, len(scan_edge(Edge('x', 'apps.proxy.next_source', name))))
  "
  ```

  Set both `resolve_source` `EdgeEntry` `hits` values in `apps/proxy/live_proxy/tests/zero_orm_allowlist.py` to what it prints — both, because the count is identical by construction (`scan_edge` depends only on the target module and symbol, never on who imports it). `get_stream_object` must still print 3; **if it moved, stop and report** — nothing in this task should have touched that subtree.

  Append to each of the two `resolve_source` entries' `reason`:

  ```
  "2c-1 raised this from 36 to <measured>: next_source.py's new "
  "_profile_kind() helper calls is_redirect() and is_proxy(), two "
  "model-method names the scanner flags, inside resolve_source's "
  "reachable subtree. Neither issues a query (core/models.py:127-135 "
  "compares self.locked and self.name on a loaded instance); the count "
  "moved because two flagged CALL SITES exist, which is the ratchet "
  "working rather than a number tuned to fit."
  ```

  And replace `views.py:462`'s and `:468`'s `closed_by` — currently `"Nothing to close -- no query."` — with:

  ```
  closed_by=(
      "stream_profile.kind on next-source's response, added by 2c-1. "
      "True that this line issues no query, and that was never the "
      "question 2c-1's precondition asks: the Go relay MUST know "
      "whether the profile is Redirect (302 and URL validation) or "
      "Proxy (read into the ring buffer), and before 2c-1 nothing on "
      "the wire said -- transcode collapses both to false and both "
      "locked profiles carry empty command/parameters. Spec "
      "Amendment A1.1."
  ),
  ```

  **Be careful which two entries you edit.** There are four `is_redirect()`/`build_command()` SITES whose `closed_by` currently reads "Nothing to close — no query", and only the two `is_redirect()` ones (`views.py:462`, `:468`) change. `views.py:766` and `input/manager.py:791` are `build_command()` and their reason is unchanged and still correct.

- [ ] **Step 6: Add the tests, in the file whose premise this is**

  `apps/proxy/tests/test_redirect_transcode_flag.py` already builds a locked Redirect profile, an M3U account, a stream and a channel, and already drives **both** derivation points — `resolve_initial_source` (the initial tune) and `get_stream_info_for_switch` (every later switch). Its docstring is literally "Redirect is treated like Proxy wherever the transcode flag is derived", which is the ambiguity `kind` resolves. Extend it rather than starting a new file.

  Add a locked Proxy profile and an unlocked transcoding profile to `setUp`:

  ```python
          self.proxy_profile = StreamProfile.objects.create(
              name="Proxy", command="", parameters="", locked=True, is_active=True,
          )
          # Not locked, and not one of the two reserved names: the ordinary
          # case, which must report "transcode" however it is spelled.
          self.ffmpeg_profile = StreamProfile.objects.create(
              name="custom-remux",
              command="ffmpeg",
              parameters="-i {streamUrl} -c copy -f mpegts pipe:1",
              locked=False,
              is_active=True,
          )
  ```

  Then, in the same class:

  ```python
      def test_profile_kind_names_all_three_architectures(self):
          """The one derivation, over the three shapes it must separate.

          The literals are typed here, not read back from the module: a
          test comparing _profile_kind(x) against a constant the module
          also defines would pass with every name spelled wrong
          together.
          """
          from apps.proxy.next_source import _profile_kind

          self.assertEqual(_profile_kind(self.redirect_profile), "redirect")
          self.assertEqual(_profile_kind(self.proxy_profile), "proxy")
          self.assertEqual(_profile_kind(self.ffmpeg_profile), "transcode")

      def test_an_unlocked_profile_named_redirect_is_not_redirect(self):
          """is_redirect() is `locked AND name == "Redirect"`, both halves.

          A user may name their own profile "Redirect"; it is an
          ordinary transcoding profile and must not make the relay
          answer 302 to a provider URL it never validated.
          """
          from apps.proxy.next_source import _profile_kind

          impostor = StreamProfile.objects.create(
              name="Redirect", command="ffmpeg", parameters="-i {streamUrl}",
              locked=False, is_active=True,
          )
          self.assertEqual(_profile_kind(impostor), "transcode")
  ```

  And the two wire-level tests, which are the ones that matter — they assert the field survives the *producers*, not just the helper. Model them on the two existing tests' decorator stacks exactly, including the `close_old_connections` patch and the comment above it explaining why:

  ```python
      @patch("apps.proxy.next_source.close_old_connections")
      @patch("apps.channels.models.reserve_profile_slot", return_value=(True, 1, None))
      @patch("apps.channels.models.RedisClient.get_client")
      def test_initial_tune_reports_kind_redirect_and_leaves_transcode_alone(
          self, mock_get_client, _mock_reserve, _mock_close_old_connections
      ):
          mock_get_client.return_value = FakeRedirectRedis()

          answer = resolve_initial_source(str(self.channel.uuid))

          self.assertIsNone(answer["error"])
          self.assertEqual(answer["source"]["stream_profile"]["kind"], "redirect")
          # transcode is unchanged by this PR. Asserted beside kind, in the
          # same payload, because "the new field is right" and "the old
          # field did not move" are two claims and D5 requires both.
          self.assertFalse(answer["source"]["transcode"])

      @patch("apps.proxy.next_source.close_old_connections")
      @patch("apps.channels.models.reserve_profile_slot", return_value=(True, 1, None))
      @patch("apps.channels.models.RedisClient.get_client")
      def test_the_locked_ffmpeg_profile_carries_a_kind_too(
          self, mock_get_client, _mock_reserve, _mock_close_old_connections
      ):
          """ffmpeg_stream_profile is rendered by the SAME serializer.

          The fourth dict the ruling did not name. Without it, a
          required `kind` on StreamProfileRefSerializer makes every
          next-source answer that carries a locked ffmpeg profile fail
          serialization -- a 500 on every tune, and one no test touching
          only the three `source` sites would catch.
          """
          StreamProfile.objects.create(
              name="ffmpeg", command="ffmpeg", parameters="-i {streamUrl}",
              locked=True, is_active=True,
          )
          mock_get_client.return_value = FakeRedirectRedis()

          answer = resolve_initial_source(str(self.channel.uuid))

          self.assertEqual(answer["source"]["ffmpeg_stream_profile"]["kind"], "transcode")
  ```

  Finally, one serializer-level test, because a producer emitting the key and a serializer declaring it are separate failures:

  ```python
      def test_the_serializer_renders_kind(self):
          """A required field DRF does not declare is silently dropped."""
          from apps.proxy.serializers import StreamProfileRefSerializer

          rendered = StreamProfileRefSerializer(
              {"id": 7, "command": "", "args": "", "kind": "redirect"}
          ).data
          self.assertEqual(rendered["kind"], "redirect")
  ```

- [ ] **Step 6b: Update the two existing tests the new key breaks**

  **This is fallout, not scope creep, and skipping it leaves Step 8 red.** Two tests assert *exact dict equality* on `ffmpeg_stream_profile` against a three-key literal, so the fourth key fails them. Both are in `apps.proxy.tests`, the label Step 8 requires green.

  ```bash
  cd <your worktree> && grep -n 'ffmpeg_stream_profile' apps/proxy/tests/test_next_source_api.py apps/proxy/tests/test_next_source_resolution.py
  ```

  In `apps/proxy/tests/test_next_source_api.py` (the assertion at `:316-323` at `b1cab647`, immediately below a comment block explaining that this is the *wire* layer a Go client meets), add the fourth key:

  ```python
          self.assertEqual(
              source["ffmpeg_stream_profile"],
              {
                  "id": ffmpeg_profile.id,
                  "command": ffmpeg_profile.command,
                  "args": ffmpeg_profile.parameters,
                  # Phase 2 PR 2c-1. The locked ffmpeg profile is neither the
                  # locked Proxy nor the locked Redirect one, so its kind is
                  # "transcode" — asserted as a literal here rather than
                  # computed, because this test's whole premise is that it
                  # pins the bytes a Go client reads.
                  "kind": "transcode",
              },
          )
  ```

  And in `apps/proxy/tests/test_next_source_resolution.py` (`:605-608`), the one-line form:

  ```python
          self.assertEqual(
              source["ffmpeg_stream_profile"],
              {
                  "id": ffmpeg.id,
                  "command": ffmpeg.command,
                  "args": ffmpeg.parameters,
                  "kind": "transcode",  # Phase 2 PR 2c-1
              },
          )
  ```

  **Do not weaken either assertion to a subset check.** Exact equality is what makes them catch a dropped or wrongly-serialized key, and the first one's own comment says so in as many words. Changing `assertEqual` to `assertIn`-style checks would close this PR's red and silently disarm both tests for every future key — hollow shape 3, applied by hand.

  **Both are also a control on Task 0's own work, and the direction matters.** Steps 2–3 have already wired `kind`, so *before* this step's edit both tests compare a three-key literal against a four-key dict and must go **red**. A **green** run here is the finding: it means `_locked_ffmpeg_profile()` is still emitting three keys, so Step 3 missed the fourth call site — the one the ruling did not name. Run them once before editing and confirm they fail, then once after and confirm they pass.

  ```bash
  cd <your worktree> && docker exec dispatcharr-testrunner /dispatcharrpy/bin/python \
    manage.py test --keepdb apps.proxy.tests.test_next_source_resolution -v1
  ```

  The failure names `'kind': 'transcode'` as the unexpected key, so it names the mechanism rather than just a shape mismatch.

- [ ] **Step 7: Break-check, four checks across three edits**

  Three numbered edits below, but the first is run in two stages — a control that must stay green, then the real defect — so the break-check table counts four (`T0.7-1a` … `T0.7-3`) and so does Task 14 Step 3. Report all four.

  1. Change `_profile_kind` to check `is_proxy()` **before** `is_redirect()`. The locked Redirect profile has `name="Redirect"` so `is_proxy()` is false and this alone does **not** redden — which is the point: run it, watch everything stay green, and understand that the ordering is not what the tests pin. Then make the real defect: delete the `is_redirect()` branch entirely. Expect `test_profile_kind_names_all_three_architectures` to fail with `'transcode' != 'redirect'` and `test_initial_tune_reports_kind_redirect_and_leaves_transcode_alone` to fail on the wire. Revert. **Record both halves** — the first is a true-positive-for-a-false-reason check in reverse, and knowing which edits your tests do *not* catch is worth as much as knowing which they do.
  2. Drop the `locked` half: change `is_redirect()` in the helper to `profile.name == "Redirect"`. Expect `test_an_unlocked_profile_named_redirect_is_not_redirect` to fail with `'redirect' != 'transcode'`. Revert.
  3. Revert `_locked_ffmpeg_profile()` to its old literal dict without `kind`. Expect `test_the_locked_ffmpeg_profile_carries_a_kind_too` to fail — and note whether it fails on a `KeyError` or on a DRF validation error, because that tells you whether the serializer is enforcing the field or merely declaring it. Revert.

- [ ] **Step 8: Run the three affected labels**

  `scripts/ci_backend_test_labels.py` maps this task's six files to three labels — verify rather than assume, since the mapping is the same function CI uses:

  ```bash
  cd <your worktree> && printf 'apps/proxy/next_source.py\napps/proxy/serializers.py\napps/proxy/tests/test_redirect_transcode_flag.py\napps/proxy/live_proxy/tests/zero_orm_allowlist.py\napps/proxy/tests/test_next_source_api.py\napps/proxy/tests/test_next_source_resolution.py\n' | python3 scripts/ci_backend_test_labels.py
  ```

  Expected: `["apps.channels.tests", "apps.proxy.live_proxy.tests", "apps.proxy.tests"]`. All three must pass. `apps.proxy.live_proxy.tests` is the one that carries the zero-ORM guard, so it is the label that proves Step 5's count is right; `apps.channels.tests` is there because the `apps/proxy/live_proxy/` alias routes to it, and it builds a real `ProxyServer` ten times, so it is slow and not optional.

  The edit hook runs the whole package for `test_redirect_transcode_flag.py` automatically. **If the container is down the hook says so and exits 0 — then say the tests did not run, and do not describe the work as verified.**

- [ ] **Step 9: Commit**

  Stage and commit in separate Bash calls; the gate will run the three labels again against what is staged.

---

## Task 1: The allowlist reconciliation and the spec amendment

**No Go in this task either.** Spec line 1795 puts this "**before** its first line of Go", and line 1738 says why: the no-Postgres-driver invariant is conditional on it. Task 0 ran first so the field this table cites already exists in the tree.

- [ ] **Step 1: Re-measure the allowlist against the branch tip**

  The table above was measured at `0c1654d8`. If anything landed on `main` between then and your branch point, the counts move. Run this **after** Task 0, so the two `resolve_source` `hits` values are the ones Task 0 Step 5 wrote.

  ```bash
  cd <your worktree> && python3 -c "
  import ast
  t = ast.parse(open('apps/proxy/live_proxy/tests/zero_orm_allowlist.py').read())
  for n in t.body:
      if isinstance(n, ast.Assign) and isinstance(n.value, ast.Tuple):
          print(n.targets[0].id, len(n.value.elts))
  "
  ```

  Expected: `SITES 12`, `EDGES 11`, `SQL_SIGNATURES 7`, `INLINE_AUTHORIZE_SIGNATURES 6`. **If any count differs, stop and report** — a new entry has no row in the table above and reconciling it is analysis, not transcription.

- [ ] **Step 2: Spot-check four contract citations against the tree**

  Not all thirty-six — four, chosen because they are the ones whose drift would be silent:

  ```bash
  cd <your worktree>
  sed -n '699p'     apps/proxy/next_source.py       # proxy_settings
  sed -n '748p'     apps/proxy/next_source.py       # output_profiles
  sed -n '111,113p' apps/proxy/relay_serializers.py # stream_name / m3u_profile_name, required=False
  sed -n '353p'     apps/proxy/authorize_views.py   # X-Relay-Output-Format
  ```

  Each must show the assignment the table cites. A line that has moved is fine — update the table's line number. A line that says something *else* is a finding: stop and report.

- [ ] **Step 3: Write the reconciliation into the PR description**

  Copy the four tables above — SITES, EDGES, SQL_SIGNATURES, INLINE_AUTHORIZE_SIGNATURES — and the Findings section verbatim into the PR description under a heading `## Allowlist reconciliation (spec line 1795 precondition)`. Do not summarise them. The spec makes the reviewer the gate, and a reviewer cannot audit a summary.

- [ ] **Step 4: Amend the spec — the prose block**

  Per the standing decision that a spec found wrong at a step is amended in the same PR. Append to § Stage 2c, immediately after the `The nine PRs` table:

  ```markdown
  #### Amendment A1 (2c-1) — Redirect had no contract field and has no owning PR

  Found while clearing 2c-1's allowlist precondition, which is what that
  precondition exists to surface. Two defects in this section — one in the
  contract, one in the table above — plus three inputs later PRs need.

  **A1.1 — the contract could not express "this profile is Redirect." CLOSED
  in 2c-1.** `StreamProfile.is_redirect()` is a name comparison
  (`core/models.py:132-135`). The next-source `source` dict carried
  `stream_profile` as `{id, command, args}` (`apps/proxy/next_source.py:512-518`)
  and `transcode`, which is `not (is_proxy() or is_redirect())` (`:504`, sent at
  `:511`) — so Proxy and Redirect were both `transcode: false` and both carry
  empty `command`/`parameters` (`core/models.py:139-144`). A Go relay therefore
  could not decide between a 302 and the Proxy path, nor apply the
  internal-principal override that forces a Redirect channel through Proxy so
  `X-Dispatcharr-Internal` is never re-sent to a provider
  (`apps/proxy/live_proxy/views.py:462-467`, a deliberate Phase 1 PR 5 fix).

  Closed by one additive key on the existing `stream_profile` object,
  `"kind": "redirect" | "proxy" | "transcode"`, derived once in
  `next_source.py`'s `_profile_kind()` and applied through `_stream_profile_ref()`
  at all **four** dicts of that shape — the three `source["stream_profile"]`
  construction sites and `_locked_ffmpeg_profile()` (`:97-100`), which the same
  `StreamProfileRefSerializer` renders. `transcode` is unchanged: D5 forbids
  altering what exists.

  **It lands in 2c-1 rather than in the PR that first serves Redirect**, for two
  reasons from this spec's own text. The precondition on the `2c-1` row is "a
  contract field for each allowlisted site, or a documented reason it needs
  none, **before** its first line of Go" — a deferred field leaves the two
  `views.py:462`/`:468` allowlist entries closed by neither, so 2c-1 could not
  honestly claim the precondition met. And the first *consumer* is **2c-2**, not
  2c-5: 2c-2 is the Proxy vertical slice, and Go cannot know a profile is Proxy
  rather than Redirect without this field. A contract field must exist before
  its first consumer.

  Note for whoever reads the allowlist next: this raised both `resolve_source`
  EDGE `hits` counts, because `_profile_kind()`'s two `is_redirect()`/`is_proxy()`
  calls are model-method names `zero_orm_scan.py` flags. Neither issues a query.
  The entries' own `reason` fields record the move and why.

  **A1.2 — no PR owned the Redirect architecture.** 2c-2 is Proxy-only; 2c-4
  through 2c-8 name ffmpeg, failover, fMP4, Output Profiles, and control/drain.
  Redirect appeared in no row. The parity matrix does not compensate: Redirect
  appears only in row 29, and only as a surface the buffering detector ignores.
  Nor can an `owed:` marker record it — Gate 1 closed in 2b-3 and the guard
  requires the owed list to stay empty (`e2e/tests/guards/parity-matrix.spec.ts:308-314`),
  so an `owed:` row would redden a closed gate. **The `2c-5` row in the table
  above is therefore amended to name it**, which is the only durable place it
  can live.

  **A1.3 — an input for 2c-4: `shlex.split` has no Go stdlib equivalent, and the
  contract is asymmetric about it.** `output_profiles[*].argv` arrives pre-split,
  because Django ran `shlex_split` on it (`apps/proxy/next_source.py:747`,
  `core/models.py:200-203`); `stream_profile.args` arrives as the raw
  `parameters` text (`apps/proxy/next_source.py:515`). So 2c-4 must implement
  POSIX word splitting plus the three `{streamUrl}`/`{userAgent}`/`{channelId}`
  substitutions (`core/models.py:147-160`) under this stage's
  no-third-party-dependencies rule, with a differential test against Python's
  own `shlex.split`. The alternative worth weighing there: extend the contract
  with a pre-split `stream_profile.argv_template`, as `output_profiles` already is.

  **A1.4 — an input for 2c-2: `proxy_settings` carries only the STORED settings
  group.** When a key is absent, Python falls through to
  `ConfigHelper.get(name, default)` → `getattr(Config, name, default)`, so the
  effective value comes from `BaseConfig`'s class attributes
  (`apps/proxy/config.py:6-19`), which never reach the wire. A Go relay would
  hold a second copy of every default, drifting silently whenever the Python one
  changes. Fix, on the Python side and owned by 2c-2 as the first Go consumer of
  settings: send **effective** `proxy_settings` — the stored group merged over
  those defaults — so there is nothing for Go to duplicate. Additive on the wire:
  keys that were absent become present carrying the default they already had in
  effect.

  **A1.5 — an input for 2c-9: CodeQL analyses no Go.** `codeql.yml:54` runs
  `[actions, python, javascript-typescript]`. 2c-1 deliberately did not add a
  `go` pack — at three tested packages and three stubs it would analyse almost
  nothing while adding a build-mode configuration to debug. 2c-9 adds it,
  alongside the coverage ratchet, when there is a relay to analyse.
  ```

- [ ] **Step 4b: Amend the spec — the `2c-5` table row itself**

  A1.2's ownership is worthless in prose beside the table; it has to be *in* the row, because the row is what someone planning 2c-5 reads. Edit the `2c-5` row's "What it does" cell — **spec line 1799** at `0c1654d8`; find it by content, since Step 4's own insertion does not move it but anything else landing on `main` might — to append, after the existing degraded-fallback clause:

  ```
  , and the Redirect Stream Profile architecture — the 302, `validate_stream_url`'s provider probe, the fall-through to the cached alternates, and the internal-principal override that serves a Redirect channel through Proxy instead (`apps/proxy/live_proxy/views.py:462-480`). Added by Amendment A1.2: no row named Redirect, and Gate 1 being closed means an `owed:` marker cannot carry it.
  ```

  Verify the table still renders — a stray `|` inside a cell splits it into two columns and the parity-matrix guard does not police this file:

  ```bash
  cd <your worktree> && awk -F'|' '/^\| 2c-[0-9] \|/ {print NF, $2}' docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
  ```

  All nine rows must report the same field count.

- [ ] **Step 4c: Add a Done log row**

  Append a row to the spec's § Done log table for this PR.

- [ ] **Step 5: Commit**

  ```bash
  cd <your worktree> && git add docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md
  ```

  Then, as a separate Bash call, commit with `-F` and a message file.

---

## Task 2: The module, the linter config, and the stdlib-only guard

- [ ] **Step 1: Create the module**

  `relay/go.mod`:

  ```
  module github.com/D10Scot/Dispatcharr/relay

  go 1.27.1
  ```

  **Re-resolve the version first** and use whatever is current:

  ```bash
  curl -sS --max-time 20 'https://go.dev/dl/?mode=json' \
    | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['version'])"
  go version
  ```

  On 2026-09-13 both reported `go1.27.1`, and `golangci-lint` 2.13.2 (built with go1.27.0) is installed. If the toolchain on the host is older than `go.mod`'s directive, `go build` refuses with a clear message — that is the right failure, not a reason to lower the directive.

- [ ] **Step 2: The linter config**

  `.golangci.yml` at the **repo root** (not inside `relay/`), so the same file governs any future Go anywhere in the tree:

  ```yaml
  # golangci-lint configuration, v2 schema. Zero findings is a ratchet, the
  # same rule as zizmor's: touching a Go file means leaving it clean. The
  # PostToolUse hook (.claude/hooks/run-go-checks.sh) and go-tests.yml's lint
  # job run the same version against the same config, so local and CI cannot
  # disagree about what passes.
  version: "2"

  run:
    timeout: 5m

  linters:
    default: standard
    enable:
      - bodyclose      # a leaked response body is a leaked fd; the relay is long-lived
      - copyloopvar
      - errorlint      # %w and errors.Is/As, which Global Constraint 5's rule needs
      - gosec
      - misspell
      - nilerr
      - noctx          # every outbound request carries a deadline (§ The contract's timeouts)
      - revive
      - unconvert
    exclusions:
      generated: lax
      rules:
        # gosec only. `noctx` is deliberately NOT excluded in tests — see
        # the note below the block.
        - path: _test\.go
          linters:
            - gosec

  formatters:
    enable:
      - gofmt
      - goimports
  ```

  **Two decisions inside that block, both made here rather than left to the implementer.**

  `gosec` is excluded in `_test.go` because test fixtures legitimately do things gosec flags — writing a temp file with a permissive mode, embedding a fixed secret — and every such finding in a test is noise.

  **`noctx` is deliberately not excluded**, which costs one argument per request in test code: `httptest.NewRequestWithContext(t.Context(), …)` rather than `httptest.NewRequest(…)`. The exclusion was the cheaper fix and is the wrong one. `noctx` exists to catch an outbound request with no deadline, and from 2c-5 the tests make real outbound calls to a control-plane stand-in — exactly the calls whose missing deadlines this phase's timeout table makes load-bearing. An exclusion added now for a purely inbound `httptest.NewRequest` would be silently covering those too by the time they exist. `t.Context()` is also strictly better in a `-race` suite: the request's context is cancelled when the test ends, rather than living until the process does.

  **Verify the config parses before committing it** — this is the one file whose syntax errors stay silent until CI:

  ```bash
  cd <your worktree> && golangci-lint config verify --config .golangci.yml
  ```

  Exit 0 and no output means it validated.

  Verify the schema before committing — this is the one file whose syntax errors are silent until CI:

  ```bash
  cd <your worktree> && golangci-lint config verify --config .golangci.yml
  ```

  Exit 0 and no output means it validated.

- [ ] **Step 3: The stdlib-only guard**

  `scripts/check_go_stdlib_only.sh`:

  ```bash
  #!/usr/bin/env bash
  # The mechanical half of the phase's "no third-party Go dependencies" rule
  # (spec § Stage 2c, "Third-party Go dependencies: none", line 1731).
  #
  # Two checks, because either alone has a hole. `go list -m all` prints the
  # module graph, which is exactly one line in a zero-dependency module -- it
  # catches a `require` that `go mod tidy` has resolved. The go.sum check
  # catches the state between adding an import and tidying, where go.sum
  # exists and the graph has not been rewritten yet.
  #
  # Also the backstop the spec names for 2c-1's un-mechanised PR-description
  # precondition: a Postgres driver or a Redis client is a third-party module,
  # so it fails here regardless of whether anyone read the punch list.
  set -euo pipefail

  MODULE_ROOT="${1:-relay}"
  cd "$MODULE_ROOT"

  EXPECTED="github.com/D10Scot/Dispatcharr/relay"

  if [ -s go.sum ]; then
    echo "FAILED: ${MODULE_ROOT}/go.sum is non-empty. This module is stdlib-only;" >&2
    echo "        a go.sum means a third-party dependency was added." >&2
    echo "        Spec § Stage 2c: 'This is a rule to defend, not an accident.'" >&2
    exit 1
  fi

  GRAPH="$(go list -m all)"
  if [ "$GRAPH" != "$EXPECTED" ]; then
    echo "FAILED: the module graph is not stdlib-only." >&2
    echo "        expected exactly: ${EXPECTED}" >&2
    echo "        got:" >&2
    printf '%s\n' "$GRAPH" | sed 's/^/          /' >&2
    exit 1
  fi

  echo "OK: ${MODULE_ROOT} depends on the standard library only."
  ```

  `chmod +x scripts/check_go_stdlib_only.sh`.

- [ ] **Step 4: Line endings**

  Append to `.gitattributes`, beside the existing `*.py text` group:

  ```
  *.go text
  ```

- [ ] **Step 5: Break-check the guard, both halves**

  Both must redden, and the message must name the mechanism (shape 6):

  ```bash
  cd <your worktree>
  # Half 1: a go.sum appears.
  echo "example.com/x v1.0.0 h1:deadbeef=" > relay/go.sum
  scripts/check_go_stdlib_only.sh relay    # expect: exit 1, "go.sum is non-empty"
  rm relay/go.sum

  # Half 2: a require line that tidy has resolved. Do this by hand rather than
  # with `go get`, which would reach the network and write a real go.sum.
  printf '\nrequire example.com/x v1.0.0\n' >> relay/go.mod
  scripts/check_go_stdlib_only.sh relay    # expect: exit 1, "module graph is not stdlib-only"
  git checkout relay/go.mod
  scripts/check_go_stdlib_only.sh relay    # expect: exit 0, "OK: ..."
  ```

  **Half 2 is the one that can fool you.** With an unresolvable `require` and no network, `go list -m all` may fail rather than print a second module — the script still exits non-zero, so the check still blocks, but for the wrong reason. Read the message: if it is a Go resolution error rather than this script's "module graph is not stdlib-only", note it in the PR description as a known weakness of the second half and rely on the first. Do not silently accept a red as a pass.

- [ ] **Step 6: Commit**

---

## Task 3: `relay/config` — the environment and `/data/jwt`

**The finding this package exists for.** `docker/entrypoint.sh:138` reads the secret as `export DJANGO_SECRET_KEY="$(tr -d '\r\n' < "$SECRET_FILE")"`. `tr -d` **deletes every occurrence** of `\r` and `\n` anywhere in the file, not just trailing whitespace, and it deletes nothing else. `strings.TrimSpace` — the obvious Go reflex — strips spaces and tabs as well, and only at the ends. On a file written by a Windows editor, or one with any interior newline, the two produce **different strings**, hence different HMACs, hence a 403 on every internal call with no error anywhere that names the cause. The exact semantics are worth a package and a test.

- [ ] **Step 1: Write `relay/config/config.go`**

  ```go
  // Package config turns the deployment's environment into the handful of
  // values the relay needs at startup. It is deliberately small and has no
  // dependencies on the rest of the module: everything here is read once, in
  // main, before anything else exists.
  package config

  import (
  	"errors"
  	"fmt"
  	"os"
  	"strconv"
  	"strings"
  )

  const (
  	// DefaultPort is the port the Go relay binds. Spec § Stage 2c: 5658,
  	// confirmed free against the tree (nothing else in the repo names it).
  	DefaultPort = 5658

  	// DefaultSecretFile is where docker/entrypoint.sh puts the deployment's
  	// Django SECRET_KEY (entrypoint.sh:103, SECRET_FILE="/data/jwt"). Every
  	// role reads the same file from the same mounted volume; the api/all role
  	// is the only one that creates it (entrypoint.sh:105-137), and the
  	// entrypoint blocks until it exists before exec'ing supervisord, so by
  	// the time this process starts the file is there.
  	//
  	// #nosec G101 -- a filesystem path, not a credential. gosec matches on
  	// the IDENTIFIER containing "Secret"; the value is "/data/jwt".
  	DefaultSecretFile = "/data/jwt"
  )

  // ErrEmptySecret is returned when the secret file exists but holds nothing
  // usable. A named error rather than a message, so callers can test for the
  // condition instead of matching a substring.
  var ErrEmptySecret = errors.New("secret file is empty")

  // Config is everything main needs. Every field is resolved before any
  // goroutine starts, so nothing here is read concurrently.
  type Config struct {
  	// Port is the TCP port to bind, from DISPATCHARR_RELAY_GO_PORT.
  	Port int

  	// Secret is the deployment's Django SECRET_KEY, the HMAC key for every
  	// token in package control.
  	Secret string

  	// DevRoutes gates every route that is not /healthz or /readyz. This PR
  	// ships no such route beyond a stub, and nginx does not route to this
  	// process until stage 2d, so the flag is the second of two reasons this
  	// PR is inert in a production deployment.
  	DevRoutes bool
  }

  // Load reads the environment and the secret file. It returns an error rather
  // than falling back to a generated secret: a relay running on a secret no
  // other role shares would answer every internal call with a 403 and nothing
  // would say why.
  func Load() (Config, error) {
  	port, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort)
  	if err != nil {
  		return Config{}, err
  	}

  	path := os.Getenv("DISPATCHARR_SECRET_FILE")
  	if path == "" {
  		path = DefaultSecretFile
  	}
  	secret, err := ReadSecretFile(path)
  	if err != nil {
  		return Config{}, err
  	}

  	return Config{Port: port, Secret: secret, DevRoutes: devRoutes()}, nil
  }

  // ReadSecretFile reads path and strips exactly what docker/entrypoint.sh:138
  // strips: `tr -d '\r\n'` deletes every CR and every LF anywhere in the file
  // and nothing else. strings.TrimSpace is NOT equivalent -- it also removes
  // spaces and tabs, and only at the ends -- and the difference is a different
  // HMAC key, which surfaces as a 403 on every internal call with no error
  // naming the cause.
  func ReadSecretFile(path string) (string, error) {
  	// #nosec G304,G703 -- `path` is deployment configuration
  	// (DISPATCHARR_SECRET_FILE, or the /data/jwt default), never client
  	// input; reading an operator-named file is this function's whole job.
  	// BOTH rule ids are needed: silencing G304 alone leaves gosec's
  	// taint-analysis rule G703 firing on the same line, and G703 only
  	// becomes visible once G304 is suppressed — found by running the
  	// linter, not by reading it.
  	raw, err := os.ReadFile(path)
  	if err != nil {
  		return "", fmt.Errorf("reading secret file %s: %w", path, err)
  	}
  	secret := strings.NewReplacer("\r", "", "\n", "").Replace(string(raw))
  	if secret == "" {
  		return "", fmt.Errorf("%s: %w", path, ErrEmptySecret)
  	}
  	return secret, nil
  }

  // devRoutes reports whether routes beyond the health endpoints are served.
  // DISPATCHARR_RELAY_GO_DEV_ROUTES wins when set, so an operator can turn the
  // routes off in a dev container as well as on elsewhere; otherwise it follows
  // DISPATCHARR_ENV, which is how the rest of the deployment decides dev-ness
  // (docker/entrypoint.sh:491 selects the all-dev supervisord rung from it).
  func devRoutes() bool {
  	if raw := os.Getenv("DISPATCHARR_RELAY_GO_DEV_ROUTES"); raw != "" {
  		enabled, err := strconv.ParseBool(raw)
  		if err != nil {
  			return false
  		}
  		return enabled
  	}
  	return os.Getenv("DISPATCHARR_ENV") == "dev"
  }

  func intFromEnv(name string, fallback int) (int, error) {
  	raw := os.Getenv(name)
  	if raw == "" {
  		return fallback, nil
  	}
  	value, err := strconv.Atoi(raw)
  	if err != nil {
  		return 0, fmt.Errorf("%s=%q is not an integer", name, raw)
  	}
  	if value < 1 || value > 65535 {
  		return 0, fmt.Errorf("%s=%d is not a TCP port", name, value)
  	}
  	return value, nil
  }
  ```

- [ ] **Step 2: Write `relay/config/config_test.go`**

  Note what each test supplies: the override tests use values the default could never produce (shape 2), and the secret test uses a file the naive implementation would read differently (shape 3 — it is what makes the test capable of failing at all).

  ```go
  package config

  import (
  	"errors"
  	"os"
  	"path/filepath"
  	"testing"
  )

  func TestPortDefaultsTo5658(t *testing.T) {
  	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "")
  	got, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort)
  	if err != nil {
  		t.Fatalf("unexpected error: %v", err)
  	}
  	if got != 5658 {
  		t.Fatalf("default port = %d, want 5658", got)
  	}
  }

  func TestPortReadsTheEnvironment(t *testing.T) {
  	// 5999 rather than 5658: a value the default cannot produce, so this
  	// test fails if the environment read is deleted.
  	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "5999")
  	got, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort)
  	if err != nil {
  		t.Fatalf("unexpected error: %v", err)
  	}
  	if got != 5999 {
  		t.Fatalf("port = %d, want 5999", got)
  	}
  }

  func TestPortRejectsGarbageRatherThanFallingBack(t *testing.T) {
  	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "not-a-port")
  	if _, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort); err == nil {
  		t.Fatal("a non-numeric port was accepted; it must fail loudly, not fall back")
  	}
  }

  func TestPortRejectsOutOfRange(t *testing.T) {
  	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "70000")
  	if _, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort); err == nil {
  		t.Fatal("70000 was accepted as a TCP port")
  	}
  }

  // The reason package config exists. docker/entrypoint.sh:138 uses
  // `tr -d '\r\n'`, which DELETES every CR and LF anywhere in the file --
  // it does not replace them with anything, and it touches nothing else.
  // This fixture has an interior CRLF and surrounding spaces, so:
  //
  //	tr -d '\r\n'        -> "  abcdef  "    (what Django's SECRET_KEY becomes)
  //	strings.TrimSpace   -> "abc\r\ndef"    (a different HMAC key)
  //	strings.TrimRight   -> "  abc\r\ndef"  (a third one)
  //
  // Only the first is correct, and the three differ on this fixture, which
  // is what makes this test able to fail. Confirm the expected value against
  // the shell rather than reasoning about it -- an earlier draft of this
  // plan wrote "  abc def  ", with a space where the deleted CRLF had been,
  // and it is exactly the kind of error a test can encode permanently:
  //
  //	printf '  abc\r\ndef  \n' | tr -d '\r\n' | od -c
  func TestReadSecretFileMatchesEntrypointStripping(t *testing.T) {
  	dir := t.TempDir()
  	path := filepath.Join(dir, "jwt")
  	if err := os.WriteFile(path, []byte("  abc\r\ndef  \n"), 0o600); err != nil {
  		t.Fatalf("writing fixture: %v", err)
  	}

  	got, err := ReadSecretFile(path)
  	if err != nil {
  		t.Fatalf("unexpected error: %v", err)
  	}
  	const want = "  abcdef  "
  	if got != want {
  		t.Fatalf("secret = %q, want %q", got, want)
  	}
  }

  func TestReadSecretFileRejectsAnEmptyFile(t *testing.T) {
  	dir := t.TempDir()
  	path := filepath.Join(dir, "jwt")
  	if err := os.WriteFile(path, []byte("\n\r\n"), 0o600); err != nil {
  		t.Fatalf("writing fixture: %v", err)
  	}
  	_, err := ReadSecretFile(path)
  	if !errors.Is(err, ErrEmptySecret) {
  		t.Fatalf("error = %v, want ErrEmptySecret", err)
  	}
  }

  func TestReadSecretFileReportsAMissingFile(t *testing.T) {
  	_, err := ReadSecretFile(filepath.Join(t.TempDir(), "absent"))
  	if !errors.Is(err, os.ErrNotExist) {
  		t.Fatalf("error = %v, want os.ErrNotExist", err)
  	}
  }

  func TestDevRoutesFollowDispatcharrEnv(t *testing.T) {
  	t.Setenv("DISPATCHARR_RELAY_GO_DEV_ROUTES", "")
  	t.Setenv("DISPATCHARR_ENV", "dev")
  	if !devRoutes() {
  		t.Fatal("DISPATCHARR_ENV=dev must enable the dev routes")
  	}
  	t.Setenv("DISPATCHARR_ENV", "aio")
  	if devRoutes() {
  		t.Fatal("DISPATCHARR_ENV=aio must leave the dev routes off")
  	}
  }

  func TestDevRoutesOverrideWinsBothWays(t *testing.T) {
  	t.Setenv("DISPATCHARR_ENV", "aio")
  	t.Setenv("DISPATCHARR_RELAY_GO_DEV_ROUTES", "1")
  	if !devRoutes() {
  		t.Fatal("an explicit 1 must enable the routes outside dev")
  	}
  	t.Setenv("DISPATCHARR_ENV", "dev")
  	t.Setenv("DISPATCHARR_RELAY_GO_DEV_ROUTES", "0")
  	if devRoutes() {
  		t.Fatal("an explicit 0 must disable the routes inside dev")
  	}
  }

  // Everything above tests intFromEnv, ReadSecretFile and devRoutes directly,
  // which leaves Load() -- the only function main actually calls -- entirely
  // unpinned. Three defects would redden nothing without this test: a wrong
  // environment variable name in Load's own call, reading the path from the
  // wrong variable, and dropping DevRoutes from the returned struct. That is
  // hollow shape 3 aimed at the wiring rather than the logic: each part is
  // proven and the assembly is not.
  //
  // Asserts all three fields in one call, so it fails on any of them, and
  // supplies values the defaults cannot produce (shape 2): 5999 is not 5658,
  // the secret is a literal no fallback generates, and DevRoutes is forced on
  // while DISPATCHARR_ENV is unset.
  func TestLoadWiresAllThreeFields(t *testing.T) {
  	dir := t.TempDir()
  	path := filepath.Join(dir, "jwt")
  	if err := os.WriteFile(path, []byte("wired-secret\n"), 0o600); err != nil {
  		t.Fatalf("writing fixture: %v", err)
  	}
  	t.Setenv("DISPATCHARR_SECRET_FILE", path)
  	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "5999")
  	t.Setenv("DISPATCHARR_RELAY_GO_DEV_ROUTES", "1")

  	cfg, err := Load()
  	if err != nil {
  		t.Fatalf("Load() failed: %v", err)
  	}
  	if cfg.Port != 5999 {
  		t.Errorf("Port = %d, want 5999", cfg.Port)
  	}
  	if cfg.Secret != "wired-secret" {
  		t.Errorf("Secret = %q, want %q", cfg.Secret, "wired-secret")
  	}
  	if !cfg.DevRoutes {
  		t.Error("DevRoutes = false, want true")
  	}
  }
  ```

  Note the three environment-mutating tests do not call `t.Parallel()` and must not: `t.Setenv` panics if they do, which is the toolchain refusing an unsafe test rather than a limitation to work around (Global Constraint 10).

- [ ] **Step 3: Break-check, four edits**

  Each must redden, and each failure message must name the mechanism (shape 6):

  1. Replace `strings.NewReplacer(...).Replace(...)` with `strings.TrimSpace(string(raw))`. Expect `TestReadSecretFileMatchesEntrypointStripping` to fail with exactly `secret = "abc\r\ndef", want "  abcdef  "` — verified by running it. Revert.
  2. Change `intFromEnv`'s `if raw == ""` branch to `return fallback, nil` unconditionally (i.e. ignore the environment). Expect `TestPortReadsTheEnvironment` to fail with `port = 5658, want 5999`. Revert.
  3. Delete the `DISPATCHARR_RELAY_GO_DEV_ROUTES` branch from `devRoutes`. Expect `TestDevRoutesOverrideWinsBothWays` to fail on its first assertion. Revert.
  4. In `Load`, drop `DevRoutes` from the returned struct literal (`return Config{Port: port, Secret: secret}`). Expect **only** `TestLoadWiresAllThreeFields` to fail, with `DevRoutes = false, want true` — every other test in the package stays green, because none of them calls `Load`. That asymmetry is the point of the test and the reason it exists: the three unit-level tests prove the parts and say nothing about the assembly.

- [ ] **Step 4: Run the four checks and commit**

---

## Task 4: `relay/control` — the HMAC contract

Spec § The contract (lines 540-548) gives the exact byte layout, and states the consequence of getting it wrong: every internal call 403s. This is the highest-consequence forty lines in the PR, which is why it is here and not deferred to 2c-5 with the HTTP client that uses it.

- [ ] **Step 1: Generate the parity vectors from Python, on your own tree**

  Do not trust this plan's literals — regenerate them, because they are the test's entire oracle. The generator imports Django's own `internal_auth` with a fixed key and prints what it produces. It needs Django, so it runs inside the test container.

  Write `/tmp/vectors.py` (outside the repo — this file is not committed):

  ```python
  import django, sys
  from django.conf import settings
  settings.configure(SECRET_KEY="phase2c1-test-secret", INSTALLED_APPS=[], DATABASES={})
  django.setup()
  sys.path.insert(0, "/repo")
  from apps.proxy import internal_auth as ia
  print("relay_trust_token  =", ia.relay_trust_token())
  print("internal_principal =", ia.internal_principal_token())
  for method, path, body, ts in [
      ("POST", "/api/relay/channels/abc/next-source", b'{"reason":"init"}', 1789000000),
      ("GET",  "/proxy/relay/channels?clients=all", b"", 1789000000),
      ("POST", "/api/relay/events", b"", 1789000000),
  ]:
      tok = ia.internal_request_token(method, path, body, ts)
      print(f"{method} {path} body={body!r}")
      print(f"    header = v1.{ts}.{tok}")
  ```

  ```bash
  cd <your worktree>
  docker inspect dispatcharr-testrunner --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}'
  ```

  **The mount must be your worktree.** The container is shared across agents and is bind-mounted at exactly one tree; if it points somewhere else, re-point it with `.claude/hooks/start-test-container.sh` before going further, and confirm nobody else is using it (`docker ps`, and check file mtimes in the tree it currently holds). Then:

  ```bash
  docker cp /tmp/vectors.py dispatcharr-testrunner:/tmp/vectors.py
  docker exec dispatcharr-testrunner /dispatcharrpy/bin/python /tmp/vectors.py
  docker exec dispatcharr-testrunner rm -f /tmp/vectors.py
  ```

  On 2026-09-13 against `0c1654d8` this printed:

  ```
  relay_trust_token  = 2bb01b0c4f053b1787d3356fb836282b162002848523b130103c33f9cf7d901c
  internal_principal = 19d4b08667108eb1a38fa11d1bbe7646cb90bc017aad605b302add137818ae7a
  POST /api/relay/channels/abc/next-source body=b'{"reason":"init"}'
      header = v1.1789000000.5ce39464af1f52fac92ab6dd8101b289c2b9acce93d392216ac0dbcfa53a1fae
  GET /proxy/relay/channels?clients=all body=b''
      header = v1.1789000000.16c32b6499ba30786464bfb130d785fbc3a8b817c7cc5a0e0d73316a60fd702c
  POST /api/relay/events body=b''
      header = v1.1789000000.6d24abde774fa01f0c94981f04c77f0b714398dffc379a09c580ac5e00c816d1
  ```

  **If your output differs, your output governs** — and report it, because `internal_auth.py` changing shape between `0c1654d8` and your branch point would be news.

  **These five digests are allowlisted in `.gitleaks.toml`, individually and by exact value.** `gitleaks` scans full history in `lint.yml`, and `relay_trust_token = <64 hex>` matches its `generic-api-key` rule — a false positive, since every value here is an HMAC under the fixed, public key `phase2c1-test-secret` and authenticates nothing in any deployment. The entry is scoped to `regexTarget = "secret"` with one anchored regex per digest (each allowing the optional `v1.<unix_ts>.` prefix the header format adds), and to that one rule, so a real secret landing in this plan or in `relay/control/token_test.go` is still caught by every rule including `generic-api-key` itself. Verified: with the entry in place a probe file carrying all five in a firing context reports no leaks, and an unrelated 64-hex `api_token` in the same file is still found.

  **So regenerating the vectors means editing `.gitleaks.toml` in the same commit.** They are allowlisted one value at a time, deliberately never by path — a path exemption on this plan or on the Go test file would silence a genuine leak dropped there later. If Step 1's output differs from the literals above, update both the plan and the allowlist together, and re-run:

  ```bash
  cd <your worktree> && docker run --rm -v "$PWD:/repo" \
    zricethezav/gitleaks:v8.30.1 detect --source=/repo \
    --config=/repo/.gitleaks.toml --no-git -v --redact
  ```

  `--no-git` scans the working tree, which is what matters: this branch squash-merges, so its intermediate commits never reach `main` and the tree is what full-history scans will see from then on. Expect `no leaks found`.

- [ ] **Step 2: Write `relay/control/token.go`**

  ```go
  // Package control speaks the two internal HTTP contracts: the /api/relay/...
  // calls the relay makes to Django, and the /proxy/relay/... calls Django
  // makes to the relay. At 2c-1 it holds only the tokens both directions
  // authenticate with; the HTTP client and server arrive in 2c-5 and 2c-8.
  //
  // The wire contract is apps/proxy/internal_auth.py, read in full. Three
  // context-separated HMACs of the deployment's Django SECRET_KEY:
  //
  //	X-Dispatcharr-Authorized       HMAC(key, "relay-trust")
  //	    nginx sets it on every relay-bound location. The relay only ever
  //	    VERIFIES it; nginx is the producer.
  //	X-Dispatcharr-Internal         HMAC(key, "internal-principal")
  //	    "this caller is part of this deployment". Long-lived and shared.
  //	X-Dispatcharr-Internal-Request v1.<unix_ts>.<hex>
  //	    binds one request -- method, full path, body, timestamp.
  package control

  import (
  	"crypto/hmac"
  	"crypto/sha256"
  	"encoding/hex"
  	"strconv"
  	"strings"
  	"time"
  )

  // Header names, spelled exactly as apps/proxy/internal_auth.py spells them.
  const (
  	HeaderAuthorized      = "X-Dispatcharr-Authorized"
  	HeaderInternal        = "X-Dispatcharr-Internal"
  	HeaderInternalRequest = "X-Dispatcharr-Internal-Request"
  )

  // RequestWindow is how far a bound token's timestamp may sit from now, in
  // EITHER direction: internal_auth.py's check is `abs(now - ts) > 120`, so a
  // token up to 120s in the future is accepted too. Reproduced, not narrowed --
  // narrowing it would reject calls a correctly-clocked peer makes.
  const RequestWindow = 120 * time.Second

  var (
  	contextRelayTrust        = []byte("relay-trust")
  	contextInternalPrincipal = []byte("internal-principal")
  	contextInternalRequest   = []byte("internal-request")
  )

  func staticToken(secret string, context []byte) string {
  	mac := hmac.New(sha256.New, []byte(secret))
  	mac.Write(context)
  	return hex.EncodeToString(mac.Sum(nil))
  }

  // RelayTrustToken is the value nginx puts in X-Dispatcharr-Authorized. The
  // relay derives it only so it can compare, never to send.
  func RelayTrustToken(secret string) string {
  	return staticToken(secret, contextRelayTrust)
  }

  // InternalPrincipalToken is the value this process puts in
  // X-Dispatcharr-Internal on every call it makes to Django.
  func InternalPrincipalToken(secret string) string {
  	return staticToken(secret, contextInternalPrincipal)
  }

  // IsRelayTrusted reports whether value is this deployment's relay-trust
  // marker. Constant-time, and it treats an empty or non-ASCII value as a
  // mismatch rather than an error, matching internal_auth._matches.
  func IsRelayTrusted(secret, value string) bool {
  	return matches(value, RelayTrustToken(secret))
  }

  // IsInternalPrincipal reports whether value is this deployment's static
  // internal-principal marker.
  func IsInternalPrincipal(secret, value string) bool {
  	return matches(value, InternalPrincipalToken(secret))
  }

  func matches(value, expected string) bool {
  	if value == "" || expected == "" {
  		return false
  	}
  	// internal_auth._matches rejects non-ASCII before comparing, because
  	// hmac.compare_digest raises on it. Go's subtle.ConstantTimeCompare does
  	// not raise, but the two sides must agree on what they reject or a
  	// malformed header is accepted here and refused there.
  	for i := 0; i < len(value); i++ {
  		if value[i] >= 0x80 {
  			return false
  		}
  	}
  	return hmac.Equal([]byte(value), []byte(expected))
  }

  // InternalRequestToken is the hex digest half of X-Dispatcharr-Internal-Request.
  //
  // The message is five fields joined on a literal '\n' byte
  // (internal_auth.internal_request_token):
  //
  //	"internal-request" \n METHOD \n FULL_PATH \n TIMESTAMP \n hex(sha256(BODY))
  //
  // fullPath is the path WITH its query string -- Django verifies against
  // request.get_full_path(), not request.path, and internal_auth.py's own
  // comment says why: "the query string is part of what a caller is asking
  // for, so it has to be part of what the token binds". A client built against
  // the bare path 403s every call that carries a query.
  //
  // An empty body hashes as sha256 of zero bytes, not as an omitted field.
  func InternalRequestToken(secret, method, fullPath string, body []byte, timestamp int64) string {
  	bodyDigest := sha256.Sum256(body)

  	var message []byte
  	message = append(message, contextInternalRequest...)
  	message = append(message, '\n')
  	message = append(message, strings.ToUpper(method)...)
  	message = append(message, '\n')
  	message = append(message, fullPath...)
  	message = append(message, '\n')
  	message = append(message, strconv.FormatInt(timestamp, 10)...)
  	message = append(message, '\n')
  	message = append(message, hex.EncodeToString(bodyDigest[:])...)

  	mac := hmac.New(sha256.New, []byte(secret))
  	mac.Write(message)
  	return hex.EncodeToString(mac.Sum(nil))
  }

  // InternalRequestHeader is the full X-Dispatcharr-Internal-Request value:
  // the literal version prefix "v1", the timestamp, and the digest, joined on
  // ASCII '.'. The verifier splits on '.' into EXACTLY three parts and rejects
  // anything else, so no field here may contain one.
  func InternalRequestHeader(secret, method, fullPath string, body []byte, timestamp int64) string {
  	return "v1." + strconv.FormatInt(timestamp, 10) + "." +
  		InternalRequestToken(secret, method, fullPath, body, timestamp)
  }

  // VerifyInternalRequest checks a header this process received. The four rules
  // are internal_auth.request_is_internal_request's, in its order: exactly
  // three dot-separated parts, a literal "v1" first part, a parsable integer
  // timestamp within RequestWindow in either direction, and a constant-time
  // digest match.
  func VerifyInternalRequest(secret, header, method, fullPath string, body []byte, now time.Time) bool {
  	parts := strings.Split(header, ".")
  	if len(parts) != 3 || parts[0] != "v1" {
  		return false
  	}
  	timestamp, err := strconv.ParseInt(parts[1], 10, 64)
  	if err != nil {
  		return false
  	}
  	skew := now.Unix() - timestamp
  	if skew < 0 {
  		skew = -skew
  	}
  	if skew > int64(RequestWindow/time.Second) {
  		return false
  	}
  	return matches(parts[2], InternalRequestToken(secret, method, fullPath, body, timestamp))
  }
  ```

- [ ] **Step 3: Write `relay/control/token_test.go`**

  ```go
  package control

  import (
  	"testing"
  	"time"
  )

  // Every expected value below was produced by Django, by running
  // apps/proxy/internal_auth.py under SECRET_KEY="phase2c1-test-secret"
  // (Task 4 Step 1's generator). They are literals on purpose: a test that
  // re-derives its expectation by calling the code under test passes with the
  // context string, the separator, the digest algorithm and the body hash all
  // wrong, and each of those 403s every internal call in production.
  const pySecret = "phase2c1-test-secret"

  func TestRelayTrustTokenMatchesPython(t *testing.T) {
  	const want = "2bb01b0c4f053b1787d3356fb836282b162002848523b130103c33f9cf7d901c"
  	if got := RelayTrustToken(pySecret); got != want {
  		t.Fatalf("relay-trust token = %s, want %s", got, want)
  	}
  }

  func TestInternalPrincipalTokenMatchesPython(t *testing.T) {
  	const want = "19d4b08667108eb1a38fa11d1bbe7646cb90bc017aad605b302add137818ae7a"
  	if got := InternalPrincipalToken(pySecret); got != want {
  		t.Fatalf("internal-principal token = %s, want %s", got, want)
  	}
  }

  // The two contexts must produce different digests. Without this, both
  // functions could share one context string and every test above still pass
  // individually -- and a marker leaked through a config file nginx reads
  // would be replayable as an internal principal, which is the exact reason
  // internal_auth.py separates them.
  func TestTheTwoStaticContextsDiffer(t *testing.T) {
  	if RelayTrustToken(pySecret) == InternalPrincipalToken(pySecret) {
  		t.Fatal("relay-trust and internal-principal produced the same digest")
  	}
  }

  func TestInternalRequestHeaderWithBodyMatchesPython(t *testing.T) {
  	const want = "v1.1789000000.5ce39464af1f52fac92ab6dd8101b289c2b9acce93d392216ac0dbcfa53a1fae"
  	got := InternalRequestHeader(pySecret, "POST",
  		"/api/relay/channels/abc/next-source", []byte(`{"reason":"init"}`), 1789000000)
  	if got != want {
  		t.Fatalf("header = %s, want %s", got, want)
  	}
  }

  // The query string is inside what the token binds. A Go client built against
  // the bare path produces a different digest here and 403s every
  // ?clients=all call -- which is every call apps/proxy/utils.py's
  // _live_connections makes on every XC handshake.
  func TestInternalRequestTokenBindsTheQueryString(t *testing.T) {
  	const want = "16c32b6499ba30786464bfb130d785fbc3a8b817c7cc5a0e0d73316a60fd702c"
  	got := InternalRequestToken(pySecret, "GET",
  		"/proxy/relay/channels?clients=all", nil, 1789000000)
  	if got != want {
  		t.Fatalf("token = %s, want %s", got, want)
  	}

  	bare := InternalRequestToken(pySecret, "GET", "/proxy/relay/channels", nil, 1789000000)
  	if bare == got {
  		t.Fatal("the query string did not change the digest; it is not being bound")
  	}
  }

  // An empty body hashes as sha256 of zero bytes, not as an omitted field.
  func TestInternalRequestTokenWithEmptyBodyMatchesPython(t *testing.T) {
  	const want = "6d24abde774fa01f0c94981f04c77f0b714398dffc379a09c580ac5e00c816d1"
  	got := InternalRequestToken(pySecret, "POST", "/api/relay/events", nil, 1789000000)
  	if got != want {
  		t.Fatalf("token = %s, want %s", got, want)
  	}
  	if InternalRequestToken(pySecret, "POST", "/api/relay/events", []byte{}, 1789000000) != want {
  		t.Fatal("nil and empty-slice bodies produced different digests")
  	}
  }

  func TestVerifyAcceptsWhatWeProduce(t *testing.T) {
  	now := time.Unix(1789000000, 0)
  	header := InternalRequestHeader(pySecret, "POST", "/api/relay/events", []byte("{}"), now.Unix())
  	if !VerifyInternalRequest(pySecret, header, "POST", "/api/relay/events", []byte("{}"), now) {
  		t.Fatal("a header this package produced did not verify")
  	}
  }

  // The window is symmetric: internal_auth.py checks abs(now - ts) > 120, so a
  // token 60s in the FUTURE is valid. A one-sided check would reject a peer
  // whose clock runs slightly fast, intermittently and unreproducibly.
  func TestVerifyWindowIsSymmetric(t *testing.T) {
  	issued := int64(1789000000)
  	header := InternalRequestHeader(pySecret, "GET", "/proxy/relay/channels", nil, issued)

  	for _, tc := range []struct {
  		name   string
  		now    int64
  		accept bool
  	}{
  		{"60s in the past", issued + 60, true},
  		{"60s in the future", issued - 60, true},
  		{"exactly 120s old", issued + 120, true},
  		{"121s old", issued + 121, false},
  		{"121s in the future", issued - 121, false},
  	} {
  		got := VerifyInternalRequest(pySecret, header, "GET", "/proxy/relay/channels", nil, time.Unix(tc.now, 0))
  		if got != tc.accept {
  			t.Errorf("%s: verify = %v, want %v", tc.name, got, tc.accept)
  		}
  	}
  }

  func TestVerifyRejectsMalformedHeaders(t *testing.T) {
  	now := time.Unix(1789000000, 0)
  	valid := InternalRequestHeader(pySecret, "GET", "/x", nil, now.Unix())

  	for _, tc := range []struct{ name, header string }{
  		{"empty", ""},
  		{"two parts", "v1.1789000000"},
  		{"four parts", valid + ".extra"},
  		{"wrong version", "v2" + valid[2:]},
  		{"non-numeric timestamp", "v1.abc.deadbeef"},
  	} {
  		if VerifyInternalRequest(pySecret, tc.header, "GET", "/x", nil, now) {
  			t.Errorf("%s: %q verified and must not have", tc.name, tc.header)
  		}
  	}
  }

  func TestVerifyRejectsAnotherDeploymentsSecret(t *testing.T) {
  	now := time.Unix(1789000000, 0)
  	header := InternalRequestHeader("some-other-deployment", "GET", "/x", nil, now.Unix())
  	if VerifyInternalRequest(pySecret, header, "GET", "/x", nil, now) {
  		t.Fatal("a token signed with a different SECRET_KEY verified")
  	}
  }
  ```

- [ ] **Step 4: Break-check, five edits, each naming its own mechanism**

  This is the most important break-check in the PR; every one of these five is a defect that ships silently and 403s in production.

  | # | Edit | Expected failure |
  |---|---|---|
  | 1 | Change `contextInternalRequest` to `[]byte("internal_request")` (underscore) | `TestInternalRequestHeaderWithBodyMatchesPython`: `header = v1.1789000000.<other>, want v1.…5ce39464…` |
  | 2 | Change the message separator from `'\n'` to `'|'` | the same three vector tests, with three different digests |
  | 3 | Drop the body digest field from the message entirely | `TestInternalRequestHeaderWithBodyMatchesPython` fails; the two empty-body tests **still pass**, which is exactly why a with-body vector exists |
  | 4 | Use `fullPath` with the query stripped (`strings.Split(fullPath, "?")[0]`) | `TestInternalRequestTokenBindsTheQueryString` fails on **both** assertions |
  | 5 | Make the window one-sided: `if now.Unix()-timestamp > 120 \|\| timestamp > now.Unix()` | `TestVerifyWindowIsSymmetric` fails on `60s in the future: verify = false, want true` |

  Run each, read the message, confirm it names the mechanism rather than a build error, revert.

- [ ] **Step 5: Run the four checks and commit**

---

## Task 5: `relay/buffer` — the depth constants

Ruling R2 is the derivation; this task is the code and the tests that keep it honest.

- [ ] **Step 1: Write `relay/buffer/buffer.go`**

  ```go
  // Package buffer holds the in-memory ring buffer and its chunk fan-out.
  //
  // At 2c-1 it holds only the sizing constants, because spec § Stage 2c's
  // "Buffer depth -- an explicit open item" makes settling them this PR's job:
  // "2c's first PR must resolve with a real number, not carry forward
  // unresolved". The ring itself arrives in 2c-2.
  //
  // WHY A BOUND AT ALL. The Python relay keeps chunks in Redis under a 60
  // second TTL and lets Redis's own eviction absorb the memory consequence. D2
  // deletes that absorber: every live channel's buffered window becomes
  // resident in this process. A time bound is then not a bound -- at twice the
  // reference bitrate the same 60 seconds costs twice the memory, and nothing
  // notices until the process is OOM-killed and every channel dies at once.
  //
  // THE DERIVATION, with every input's source:
  //
  //	chunk size      255,868 bytes (188 x 1361)  apps/proxy/config.py:15
  //	retention       60 seconds                  apps/proxy/config.py:71
  //	join point      5 seconds behind live       apps/proxy/config.py:57
  //	reference rate  10 Mbit/s                   STATED, not measured -- see below
  //
  //	10,000,000 bit/s / 8        = 1,250,000 byte/s
  //	x 60 s                      = 75,000,000 bytes per channel
  //	/ 255,868                   = 293.12 chunks
  //	round up                    = 300 chunks
  //	x 255,868                   = 76,760,400 bytes ~= 73.2 MiB per channel
  //
  // The reference bitrate is an assumption, not a measurement: nothing in the
  // tree records real channel bitrates (avg_bitrate_kbps is displayed and never
  // thresholded). 10 Mbit/s is a realistic ceiling for the 1080p MPEG-TS remux
  // the default FFmpeg profile produces. It sizes the cap; it is not a limit
  // anything enforces.
  //
  // BOTH BOUNDS ARE ENFORCED, whichever binds first, and that is what preserves
  // parity. Retention stays 60 seconds so a client's view of how far back the
  // buffer reaches matches Python's. The byte cap sits behind it so memory is
  // bounded regardless of bitrate. They cross at 10.23 Mbit/s: below it
  // behaviour is Python's exactly, above it retention shortens and memory does
  // not grow -- a deliberate divergence, in the safe direction.
  //
  // Aggregate, stated and not enforced: ten concurrently-owned channels at the
  // cap is ~732 MiB in one process. Per the user's decision the cap is per
  // channel with no host-memory check; sizing against real channel counts is
  // spec § Risks' pre-deployment item, not this package's.
  package buffer

  const (
  	// TSPacketSize is the MPEG-TS packet size every chunk is realigned to.
  	// apps/proxy/live_proxy/constants.py's TS_PACKET_SIZE.
  	TSPacketSize = 188

  	// ChunkBytes is the ring's write unit: 188 * 1361, from
  	// apps/proxy/config.py:15's BaseConfig.BUFFER_CHUNK_SIZE. Note that
  	// apps/proxy/live_proxy/input/buffer.py:42 reads it with a fallback of
  	// TS_PACKET_SIZE * 5644, which is an UNREACHABLE default because the
  	// class attribute always exists -- the effective Python chunk is this
  	// number, a quarter of what that call site looks like.
  	ChunkBytes = TSPacketSize * 1361

  	// RetentionSeconds is the parity half of the bound: the Redis chunk TTL
  	// the Python relay applies, apps/proxy/config.py:71's default of 60.
  	RetentionSeconds = 60

  	// JoinBehindSeconds is how far behind live a new client starts,
  	// apps/proxy/config.py:57's new_client_behind_seconds. Not a bound --
  	// it is the figure the bound must stay above, asserted in the tests.
  	JoinBehindSeconds = 5

  	// ReferenceBitrateBitsPerSecond sizes the cap. An assumption; see above.
  	ReferenceBitrateBitsPerSecond = 10_000_000

  	// MaxChunksPerChannel is 293.12 rounded up to a round number.
  	MaxChunksPerChannel = 300

  	// MaxBytesPerChannel is the memory bound. This, not the chunk count, is
  	// the thing that must not grow; the count is how it is enforced, because
  	// the chunk is the ring's eviction unit.
  	MaxBytesPerChannel = MaxChunksPerChannel * ChunkBytes
  )

  // ChunksForBytes converts a byte budget to a whole number of chunks, which is
  // what a ring bounded by an eviction unit can actually hold. Used by 2c-2 to
  // turn an operator's DISPATCHARR_RELAY_GO_CHANNEL_BUFFER_BYTES into a ring
  // length; exported here so the conversion has exactly one implementation.
  func ChunksForBytes(budget int) int {
  	if budget < ChunkBytes {
  		return 1
  	}
  	return budget / ChunkBytes
  }
  ```

- [ ] **Step 2: Write `relay/buffer/buffer_test.go`**

  These tests are not arithmetic checks of constants against themselves — that would be shape 1. Each pins either a Python-sourced literal or one of the two crossover bitrates, which are the numbers that decide whether the cap is safe and which nothing in the constant block makes obvious.

  ```go
  package buffer

  import "testing"

  // The Python literals this package mirrors. Typed by hand from the source
  // named in each comment, never computed from the constants above -- these are
  // the oracle, and a test that derived them from the subject would pass with
  // every constant wrong together.
  func TestConstantsMatchThePythonSource(t *testing.T) {
  	// apps/proxy/config.py:15 -- BUFFER_CHUNK_SIZE = 188 * 1361
  	if ChunkBytes != 255868 {
  		t.Errorf("ChunkBytes = %d, want 255868 (apps/proxy/config.py:15)", ChunkBytes)
  	}
  	// apps/proxy/config.py:71 -- settings.get("redis_chunk_ttl", 60)
  	if RetentionSeconds != 60 {
  		t.Errorf("RetentionSeconds = %d, want 60 (apps/proxy/config.py:71)", RetentionSeconds)
  	}
  	// apps/proxy/config.py:57 -- "new_client_behind_seconds": 5
  	if JoinBehindSeconds != 5 {
  		t.Errorf("JoinBehindSeconds = %d, want 5 (apps/proxy/config.py:57)", JoinBehindSeconds)
  	}
  	// The cap, as Ruling R2 derives it.
  	if MaxBytesPerChannel != 76760400 {
  		t.Errorf("MaxBytesPerChannel = %d, want 76760400", MaxBytesPerChannel)
  	}
  }

  // The cap must hold at least the full retention window at the bitrate it was
  // sized for. If it does not, the cap is silently shorter than Python's
  // buffer at the reference rate and every client's rewind window shrinks.
  func TestCapCoversFullRetentionAtTheReferenceBitrate(t *testing.T) {
  	needed := ReferenceBitrateBitsPerSecond / 8 * RetentionSeconds // 75,000,000
  	if MaxBytesPerChannel < needed {
  		t.Fatalf("cap %d < %d bytes needed for %ds at %d bit/s",
  			MaxBytesPerChannel, needed, RetentionSeconds, ReferenceBitrateBitsPerSecond)
  	}
  }

  // The bitrate above which the byte cap binds before the 60-second retention.
  // Below it, behaviour is Python's exactly; above it, retention shortens and
  // memory does not grow. 10.23 Mbit/s -- close enough to the reference rate
  // that it is worth stating out loud rather than discovering in production.
  func TestRetentionAndCapCrossAtTheStatedBitrate(t *testing.T) {
  	const wantBitsPerSecond = 10_234_720 // 76,760,400 / 60 * 8
  	got := MaxBytesPerChannel / RetentionSeconds * 8
  	if got != wantBitsPerSecond {
  		t.Fatalf("crossover = %d bit/s, want %d -- the plan's Ruling R2 arithmetic has moved",
  			got, wantBitsPerSecond)
  	}
  }

  // The check that actually matters. A new client starts JoinBehindSeconds
  // behind live, so the cap is only safe while that much video is resident.
  // The margin is an order of magnitude and this test says by how much.
  func TestCapCoversTheJoinPointWithAnOrderOfMagnitudeToSpare(t *testing.T) {
  	const wantCeilingBitsPerSecond = 122_816_640 // 76,760,400 / 5 * 8
  	got := MaxBytesPerChannel / JoinBehindSeconds * 8
  	if got != wantCeilingBitsPerSecond {
  		t.Fatalf("join-point ceiling = %d bit/s, want %d", got, wantCeilingBitsPerSecond)
  	}
  	if got < 10*ReferenceBitrateBitsPerSecond {
  		t.Fatalf("join-point ceiling %d bit/s is under 10x the reference rate; the cap is too tight", got)
  	}
  }

  func TestChunksForBytes(t *testing.T) {
  	for _, tc := range []struct {
  		name   string
  		budget int
  		want   int
  	}{
  		{"the default cap", MaxBytesPerChannel, 300},
  		{"one chunk exactly", ChunkBytes, 1},
  		{"a partial chunk rounds down to one", ChunkBytes + 1, 1},
  		{"below one chunk still yields one", 1, 1},
  		{"two and a half chunks", ChunkBytes*2 + ChunkBytes/2, 2},
  	} {
  		if got := ChunksForBytes(tc.budget); got != tc.want {
  			t.Errorf("%s: ChunksForBytes(%d) = %d, want %d", tc.name, tc.budget, got, tc.want)
  		}
  	}
  }
  ```

- [ ] **Step 3: Break-check, three edits**

  1. Change `MaxChunksPerChannel` to `200`. Expect `TestConstantsMatchThePythonSource` (`MaxBytesPerChannel = 51173600, want 76760400`) **and** `TestCapCoversFullRetentionAtTheReferenceBitrate` (`cap 51173600 < 75000000`) to fail. Two failures, not one, and the second is the one that says *why* 200 is wrong. Revert.
  2. Change `ChunkBytes` to `TSPacketSize * 5644` — the unreachable Python default, which is the mistake this comment exists to prevent. Expect `TestConstantsMatchThePythonSource` to fail naming `apps/proxy/config.py:15`. Revert.
  3. Change `ChunksForBytes`'s guard to `if budget < 1`. Expect `TestChunksForBytes` to fail on `below one chunk still yields one: ChunksForBytes(1) = 0, want 1` — a zero-length ring, which would deadlock 2c-2's writer. Revert.

- [ ] **Step 4: Run the four checks and commit**

---

## Task 6: `relay/channel` and `relay/ffmpeg` — documented stubs

Two files, no tests, because there is nothing yet to assert. What they must not be is empty: a package with a name and no contract is an invitation for the next PR to put the wrong thing in it.

- [ ] **Step 1: `relay/channel/channel.go`**

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
  ```

- [ ] **Step 2: `relay/ffmpeg/ffmpeg.go`**

  ```go
  // Package ffmpeg spawns and supervises the upstream subprocess and parses its
  // stderr.
  //
  // Empty at 2c-1. 2c-4 brings the spawn path and the port of
  // apps/proxy/live_proxy/input/log_parsers.py.
  //
  // TWO THINGS FIXED IN ADVANCE, so 2c-4 does not have to re-decide them.
  //
  // Spawning uses os/exec with SysProcAttr{Setpgid: true, Pdeathsig: SIGKILL}.
  // That is D5's first named exception to strict parity: the Python relay
  // spawns with os.posix_spawn and no setsid or PDEATHSIG, so an ffmpeg blocked
  // on a stalled upstream survives its worker and holds a provider slot
  // (CLAUDE.md, § Operationally). No test asserts the current behaviour and it
  // is process hygiene rather than streaming behaviour a client can observe,
  // which is why this one gets fixed in transit and the rest do not.
  //
  // Building the argv needs a shell word splitter this module has to write
  // itself. The contract is asymmetric about this: output_profiles[*].argv
  // arrives pre-split, because Django ran shlex.split on it
  // (apps/proxy/next_source.py:747, core/models.py:200-203), while
  // stream_profile.args arrives as the raw `parameters` text
  // (apps/proxy/next_source.py:515) and still needs splitting plus the three
  // {streamUrl} / {userAgent} / {channelId} substitutions
  // (core/models.py:147-160). The standard library has no shlex, and the
  // no-third-party-dependencies rule stands, so 2c-4 writes one with a
  // differential test against Python's. Recorded in the 2c-1 plan as Finding F3.
  package ffmpeg
  ```

- [ ] **Step 3: Run the four checks and commit**

  `go vet` is content with a package that declares no symbols; `golangci-lint` may warn about an unused package under some linter sets. If it does, the fix is to report it, not to add a placeholder symbol to quiet it — a `var _ = 0` in a stub is exactly the noise these comments exist instead of.

---

## Task 7: `relay/httpapi` — the mux and the health endpoints

- [ ] **Step 1: Write `relay/httpapi/server.go`**

  ```go
  // Package httpapi serves the relay's public HTTP surface: the live TS stream
  // routes, the XC live roots, and the operational endpoints.
  //
  // At 2c-1 it serves the two operational endpoints and one gated stub. Nothing
  // routes to this process from nginx until stage 2d, and the stub is behind
  // the dev flag as well, so this PR is inert in every deployment shape twice
  // over.
  package httpapi

  import (
  	"fmt"
  	"net/http"
  )

  // Config is what the server needs to build its routing table.
  type Config struct {
  	// DevRoutes gates every route that is not an operational endpoint.
  	DevRoutes bool
  }

  // Server owns the routing table. One per process.
  //
  // Deliberately holds no copy of its Config: `New` reads cfg.DevRoutes to
  // decide the table and nothing reads it afterwards, so storing it would be
  // a field with no reader. 2c-2 adds whatever state it actually needs;
  // keeping an unread field here in anticipation is how `unused` findings
  // and stale duplicates of the truth both start.
  type Server struct {
  	mux *http.ServeMux
  }

  // New builds the routing table from cfg. The table is fixed at construction:
  // no route is added or removed after this returns, so the mux is read-only
  // for the life of the process and needs no lock.
  func New(cfg Config) *Server {
  	s := &Server{mux: http.NewServeMux()}

  	// Always served, in every shape. D6: the Python relay has neither a
  	// health endpoint nor a readiness probe, and both are a few lines here.
  	//
  	// Both are a static 200 at 2c-1, which is what this PR's row specifies.
  	// /readyz becomes meaningful in 2c-8, when the SIGTERM drain gives it
  	// something to report -- and that is also why this PR adds no Docker
  	// HEALTHCHECK: a probe wired to a static 200 reports healthy through
  	// every failure it exists to catch.
  	s.mux.HandleFunc("GET /healthz", ok)
  	s.mux.HandleFunc("GET /readyz", ok)

  	if cfg.DevRoutes {
  		// The dev-only route flag spec line 1795 names. The live routes
  		// arrive in 2c-2; until then this stub is what makes the flag a
  		// thing with an observable effect rather than a comment.
  		s.mux.HandleFunc("GET /proxy/ts/stream/{channelID}", notImplemented)
  	}

  	return s
  }

  // Handler returns the routing table as an http.Handler, for ListenAndServe
  // and for tests. Tests drive this, never a hand-built handler: a test that
  // builds its own handler asserts that net/http calls functions.
  func (s *Server) Handler() http.Handler { return s.mux }

  func ok(w http.ResponseWriter, _ *http.Request) {
  	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
  	w.WriteHeader(http.StatusOK)
  	// The error is discarded deliberately, and `_, _ =` rather than a bare
  	// call so errcheck can see that it was a decision: a failed write to a
  	// health probe means the prober hung up mid-response. There is nothing
  	// to recover and nobody to tell, and logging it would turn a flapping
  	// probe into log spam. Every other write path in this module handles
  	// its error.
  	_, _ = fmt.Fprintln(w, "ok")
  }

  func notImplemented(w http.ResponseWriter, _ *http.Request) {
  	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
  	w.WriteHeader(http.StatusNotImplemented)
  	_, _ = fmt.Fprintln(w, "the Go relay does not serve streams yet")
  }
  ```

  Note the `GET /healthz` method-and-path pattern: Go 1.22 added method matching to `http.ServeMux`, so a `POST /healthz` falls through to a 405 without a hand-written method check.

- [ ] **Step 2: Write `relay/httpapi/server_test.go`**

  ```go
  package httpapi

  import (
  	"net/http"
  	"net/http/httptest"
  	"testing"
  )

  // Drives the real mux and asserts what a client would see. A test that built
  // its own http.HandlerFunc and asserted it was called would pass with this
  // whole package deleted.
  func TestHealthEndpointsAnswer200(t *testing.T) {
  	srv := New(Config{DevRoutes: false})
  	for _, path := range []string{"/healthz", "/readyz"} {
  		rec := httptest.NewRecorder()
  		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, path, nil))
  		if rec.Code != http.StatusOK {
  			t.Errorf("GET %s = %d, want 200", path, rec.Code)
  		}
  		if got := rec.Body.String(); got != "ok\n" {
  			t.Errorf("GET %s body = %q, want %q", path, got, "ok\n")
  		}
  	}
  }

  // The health endpoints must not depend on the dev flag: a deployment with the
  // flag off still needs to be probeable, and that is the shape stage 2d relies
  // on.
  func TestHealthEndpointsIgnoreTheDevFlag(t *testing.T) {
  	for _, dev := range []bool{true, false} {
  		srv := New(Config{DevRoutes: dev})
  		rec := httptest.NewRecorder()
  		srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/healthz", nil))
  		if rec.Code != http.StatusOK {
  			t.Errorf("DevRoutes=%v: GET /healthz = %d, want 200", dev, rec.Code)
  		}
  	}
  }

  // The flag's whole purpose: with it off, a stream URL is a 404 from the mux,
  // not a 501 from a registered handler. 404 and 501 are different answers and
  // the difference is the assertion -- a test that only checked "not 200" would
  // pass with the route registered and the handler erroring.
  func TestStreamRouteIsUnregisteredWithoutTheDevFlag(t *testing.T) {
  	srv := New(Config{DevRoutes: false})
  	rec := httptest.NewRecorder()
  	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/proxy/ts/stream/abc", nil))
  	if rec.Code != http.StatusNotFound {
  		t.Fatalf("GET /proxy/ts/stream/abc with DevRoutes=false = %d, want 404 (the route must not be registered at all)", rec.Code)
  	}
  }

  func TestStreamRouteIsRegisteredWithTheDevFlag(t *testing.T) {
  	srv := New(Config{DevRoutes: true})
  	rec := httptest.NewRecorder()
  	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/proxy/ts/stream/abc", nil))
  	if rec.Code != http.StatusNotImplemented {
  		t.Fatalf("GET /proxy/ts/stream/abc with DevRoutes=true = %d, want 501", rec.Code)
  	}
  }

  // ServeMux's method matching, asserted because it is doing real work here:
  // without the "GET " prefix on the pattern, this is a 200 and any client can
  // POST to the health endpoints.
  func TestHealthEndpointsRejectNonGET(t *testing.T) {
  	srv := New(Config{DevRoutes: false})
  	rec := httptest.NewRecorder()
  	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodPost, "/healthz", nil))
  	if rec.Code != http.StatusMethodNotAllowed {
  		t.Fatalf("POST /healthz = %d, want 405", rec.Code)
  	}
  }

  func TestUnknownPathIs404(t *testing.T) {
  	srv := New(Config{DevRoutes: true})
  	rec := httptest.NewRecorder()
  	srv.Handler().ServeHTTP(rec, httptest.NewRequestWithContext(t.Context(), http.MethodGet, "/anything-else", nil))
  	if rec.Code != http.StatusNotFound {
  		t.Fatalf("GET /anything-else = %d, want 404", rec.Code)
  	}
  }
  ```

- [ ] **Step 3: Break-check, three edits**

  1. Move the stream-route registration outside the `if cfg.DevRoutes` block. Expect `TestStreamRouteIsUnregisteredWithoutTheDevFlag` to fail with `= 501, want 404 (the route must not be registered at all)`. Revert.
  2. Change the two health patterns from `"GET /healthz"` to `"/healthz"`. Expect `TestHealthEndpointsRejectNonGET` to fail with `POST /healthz = 200, want 405`. Revert.
  3. Change `ok` to write `http.StatusNoContent`. Expect `TestHealthEndpointsAnswer200` to fail on both paths. Revert.

- [ ] **Step 4: Run the four checks and commit**

---

## Task 8: `relay/main.go`

- [ ] **Step 1: Write it**

  ```go
  // Command relay-go is the Go relay. At stage 2c-1 it binds its port, answers
  // /healthz and /readyz, and does nothing else: nginx routes no location to
  // this process until stage 2d, and every route beyond the two health
  // endpoints is behind the dev flag.
  package main

  import (
  	"errors"
  	"log"
  	"net"
  	"net/http"
  	"os"
  	"strconv"
  	"time"

  	"github.com/D10Scot/Dispatcharr/relay/config"
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
  		log.Printf("startup failed: %v", err)
  		os.Exit(1)
  	}

  	// The secret is never logged, in any form, at any level -- not its value,
  	// not its length, not a prefix. scripts/check_credential_logging.py polices
  	// the Python side of this rule; there is no Go equivalent yet, so it is
  	// held by hand here.
  	log.Printf("starting on port %d (dev routes: %t)", cfg.Port, cfg.DevRoutes)

  	srv := &http.Server{
  		Addr:    net.JoinHostPort("0.0.0.0", strconv.Itoa(cfg.Port)),
  		Handler: httpapi.New(httpapi.Config{DevRoutes: cfg.DevRoutes}).Handler(),

  		// ReadHeaderTimeout only. A read or write deadline on the whole
  		// request would be wrong for this process by construction: serving
  		// long-lived responses is the reason it exists, and it is why
  		// docker/uwsgi.relay.ini carries no harakiri either. Bounding just
  		// the header read closes the slow-header class without touching the
  		// body, which is the stream.
  		ReadHeaderTimeout: 10 * time.Second,
  	}

  	// No graceful shutdown here. D6's SIGTERM drain is 2c-8's, and a
  	// half-implemented drain -- one that stops accepting but does not wait for
  	// anything, because there is nothing to wait for yet -- would look like
  	// the feature while being the default. supervisord's stopwaitsecs=20
  	// bounds the stop either way.
  	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
  		log.Printf("server stopped: %v", err)
  		os.Exit(1)
  	}
  }
  ```

- [ ] **Step 2: Verify it runs**

  **No job control and no bare `sleep`.** `%1` needs an interactive shell, and a foreground `sleep` is blocked in this harness; both fail in ways that look like the binary being broken. Capture the PID with `$!` and poll the endpoint instead — polling is also the honest wait, since a fixed sleep either wastes time or races the listener.

  ```bash
  cd <your worktree>/relay
  printf 'test-secret-for-a-local-run\n' > /tmp/jwt-probe

  probe() {   # $1 = the value of DISPATCHARR_RELAY_GO_DEV_ROUTES
    DISPATCHARR_SECRET_FILE=/tmp/jwt-probe \
    DISPATCHARR_RELAY_GO_PORT=5999 \
    DISPATCHARR_RELAY_GO_DEV_ROUTES="$1" \
      go run . & local pid=$!
    local i
    for i in $(seq 1 50); do
      # stderr silenced here and NOWHERE else in this block: this curl's
      # failure is the loop condition, not an answer being interpreted, and
      # its "connection refused" lines while the listener comes up would
      # otherwise bury the three status codes below. `perl select` rather
      # than `sleep 0.2` — a foreground sleep is blocked in this harness.
      curl -fsS -o /dev/null http://127.0.0.1:5999/healthz 2>/dev/null && break
      perl -e 'select(undef,undef,undef,0.2)'
    done
    echo "dev_routes=$1"
    for p in /healthz /readyz /proxy/ts/stream/abc; do
      printf '  %-26s %s\n' "$p" "$(curl -sS -o /dev/null -w '%{http_code}' "http://127.0.0.1:5999$p")"
    done
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
  }

  probe 0                                        # expect 200, 200, 404
  pkill -f 'exe/relay'; perl -e 'select(undef,undef,undef,0.5)'
  probe 1                                        # expect 200, 200, 501
  pkill -f 'exe/relay'
  rm -f /tmp/jwt-probe
  ```

  The `pkill` between runs is not belt-and-braces: `go run` compiles to a temp binary and execs it as a *child*, so `kill "$pid"` reaps `go run` and can leave the listener holding `:5999`. Without it the second `probe` fails with "address already in use", which reads like the binary being broken rather than the previous run still running.

  **This block was run against the plan's own code at plan time and produced exactly the expected nine values**, plus `starting on port 5999 (dev routes: false)` and `… true)` on the two runs. Record your own output in the PR description — this is the only end-to-end evidence in the PR that the binary serves anything.

- [ ] **Step 3: Verify it fails loudly on a missing secret**

  ```bash
  cd <your worktree>/relay && DISPATCHARR_SECRET_FILE=/tmp/definitely-absent go run . ; echo "exit=$?"
  ```

  Expect exit 1 and `startup failed: reading secret file /tmp/definitely-absent: open /tmp/definitely-absent: no such file or directory` — verified at plan time. **A zero exit here is a finding** — it means the deployment can start a relay that will 403 every internal call silently.

- [ ] **Step 4: Run the four checks and commit**

---

## Task 9: supervisord

- [ ] **Step 1: Write `docker/supervisord.d/relay-go.conf`**

  Modelled on `relay-uwsgi.conf`, with three deliberate differences called out in its own comments.

  ```ini
  # The Go relay (Phase 2 stage 2c). Started by roles `all` and `relay`; the
  # relay rung picks it up through its existing relay-*.conf glob, the two
  # `all` rungs name it explicitly.
  #
  # THREE DIFFERENCES FROM relay-uwsgi.conf, each deliberate:
  #
  # 1. priority=205, the SAME as relay-uwsgi, not 206. supervisord stops one
  #    priority group at a time and waits out each group's stopwaitsecs before
  #    moving on, so the container's stop budget is the SUM across groups --
  #    155s today, against a 160s stop_grace_period. A separate priority with
  #    stopwaitsecs=20 would take it to 175s and start SIGKILLing every deploy
  #    mid-shutdown. Sharing the group makes the two stop concurrently and the
  #    group cost max(20, 20).
  #
  # 2. No wait-for-stores.sh wrapper. The Go relay opens no Postgres connection
  #    and no Redis connection -- those are the phase's two checkable invariants
  #    (spec § Stage 2c) -- so it has no store to wait for. It does need
  #    /data/jwt, and docker/entrypoint.sh blocks on that file for every role
  #    before it execs supervisord, so it is present by the time this starts.
  #
  # 3. No `nice`. UWSGI_NICE_LEVEL exists to keep the streaming path ahead of
  #    Celery; at 2c-1 this process serves two health endpoints. It joins the
  #    uWSGI nice level in 2c-2, when it starts carrying bytes.
  [program:relay-go]
  command=setpriv --reuid=%(ENV_POSTGRES_USER)s --regid=%(ENV_POSTGRES_USER)s --init-groups /usr/local/bin/relay-go
  directory=/app
  environment=HOME="%(ENV_DISPATCHARR_HOME)s",USER="%(ENV_POSTGRES_USER)s"
  priority=205
  autostart=true
  autorestart=true
  startretries=20
  startsecs=5
  stopsignal=TERM
  stopwaitsecs=20
  killasgroup=true
  redirect_stderr=true
  stdout_logfile=/dev/stdout
  stdout_logfile_maxbytes=0
  ```

- [ ] **Step 2: Add it to the two explicit rungs**

  `docker/supervisord/all.conf` and `docker/supervisord/all-dev.conf` each carry one `files = ...` line listing every program. Append ` /app/docker/supervisord.d/relay-go.conf` to each, immediately after the existing `relay-uwsgi.conf` entry so the file reads in start order.

  `docker/supervisord/relay.conf` needs **no edit** — its include is the glob `files = /app/docker/supervisord.d/relay-*.conf`, which already matches. Verify that rather than assume it:

  ```bash
  cd <your worktree> && grep -n 'files =' docker/supervisord/relay.conf
  ```

  `docker/supervisord/api.conf` and `worker.conf` must **not** list it: those roles do not serve streams.

- [ ] **Step 3: Verify the stop budget by hand**

  ```bash
  cd <your worktree> && grep -H 'priority\|stopwaitsecs' docker/supervisord.d/*.conf | sort
  ```

  Read off the `all` rung's programs, group them by priority, sum the maximum `stopwaitsecs` per group, and confirm the total is still **155** against the `stop_grace_period: 160s` in `docker/docker-compose.yml:23`. **Write the arithmetic into the PR description.** If it exceeds 160, a program's priority is wrong — do not raise the grace period to fit.

- [ ] **Step 4: Commit**

---

## Task 10: The Dockerfile builder stage

- [ ] **Step 1: Re-resolve the builder image digest**

  ```bash
  docker buildx imagetools inspect golang:<current>-trixie --format '{{.Manifest.Digest}}'
  ```

  On 2026-09-13, `golang:1.27.1-trixie` resolved to `sha256:9baa6b4187bbb98d240372a8a235ac0bb6b5ddd52bba1431dc2f7c0705862728`. Use the explicit OS variant rather than the bare tag, so a patch bump cannot silently change the builder's base distribution underneath a pinned digest.

- [ ] **Step 2: Add the stage**

  In `docker/Dockerfile`, after the `frontend-builder` stage and **before** the `ARG BASE_IMAGE` redeclaration:

  ```dockerfile
  # --- Build the Go relay ---

  # --platform=$BUILDPLATFORM with an explicit GOARCH, not a plain FROM.
  # docker-build.yml builds linux/amd64 and linux/arm64 in one buildx
  # invocation; a plain FROM would run the arm64 leg's compilation under QEMU
  # emulation, minutes per build, for a binary Go cross-compiles natively in
  # about a second.
  FROM --platform=$BUILDPLATFORM golang:1.27.1-trixie@sha256:9baa6b4187bbb98d240372a8a235ac0bb6b5ddd52bba1431dc2f7c0705862728 AS relay-builder

  ARG TARGETOS
  ARG TARGETARCH

  WORKDIR /src
  # One COPY, deliberately. The usual "copy go.mod first, download, then copy
  # the source" split exists to cache `go mod download` across source changes;
  # a stdlib-only module downloads nothing, so the split would add a layer
  # that caches an empty step and a comment claiming a benefit it does not
  # deliver. Reinstate it in the same commit as the first dependency, if there
  # ever is one.
  COPY ./relay ./

  # CGO_ENABLED=0 makes the binary static, so it runs on the final image
  # whatever its libc. -trimpath keeps build paths out of the binary;
  # -s -w drop the symbol and DWARF tables.
  RUN CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
      go build -trimpath -ldflags="-s -w" -o /out/relay-go .
  ```

  And in the `final` stage, after the frontend `COPY --from=`:

  ```dockerfile
  # The Go relay binary. /usr/local/bin so docker/supervisord.d/relay-go.conf
  # can name it without a path prefix.
  COPY --from=relay-builder /out/relay-go /usr/local/bin/relay-go
  ```

- [ ] **Step 3: Confirm `.dockerignore` does not exclude the module**

  ```bash
  cd <your worktree> && grep -n 'bin\|relay\|go' .dockerignore
  ```

  `**/bin` is present and would exclude any directory named `bin` under `relay/`. The layout in this plan has none — **do not create one**, and if a later PR needs a `cmd/` layout, check this first. Nothing else in `.dockerignore` matches `relay/`.

- [ ] **Step 4: Verify the cross-compile works, both architectures**

  Cheaper than a full image build and it tests the only thing this stage does:

  ```bash
  cd <your worktree>/relay
  for arch in amd64 arm64; do
    CGO_ENABLED=0 GOOS=linux GOARCH=$arch go build -trimpath -ldflags="-s -w" -o /tmp/relay-go-$arch . \
      && echo "linux/$arch ok: $(wc -c < /tmp/relay-go-$arch) bytes"
  done
  rm -f /tmp/relay-go-amd64 /tmp/relay-go-arm64
  ```

  Both must succeed. On 2026-09-13 they produced ~1.5 MB each. Record the output in the PR description.

- [ ] **Step 5: Commit**

---

## Task 11: `go-tests.yml`

Built in the four-part requireable shape per Ruling R1. `frontend-tests.yml` is the template — read it in full before writing, and keep its comment discipline.

- [ ] **Step 1: Re-resolve all three action pins**

  ```bash
  for r in actions/checkout actions/setup-go golangci/golangci-lint-action; do
    tag=$(gh api "repos/${r}/releases/latest" --jq .tag_name)
    sha=$(gh api "repos/${r}/commits/${tag}" --jq .sha)
    owner=$(gh api "repos/${r}" --jq '.full_name + "  fork=" + (.fork|tostring)')
    printf '%s@%s  # %s   [%s]\n' "$r" "$sha" "$tag" "$owner"
  done
  ```

  **Confirm `fork=false` and that the owner is the real publisher before using a SHA.** On 2026-09-13 this returned:

  ```
  actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1                # v7.0.1
  actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e                # v7.0.0
  golangci/golangci-lint-action@ba0d7d2ec06a0ea1cb5fa41b2e4a3ab91d21278a   # v9.3.0
  ```

  Note `actions/checkout@v7.0.1` here while the ten existing workflows pin `v6.1.0`. That is correct and deliberate: spec line 1783 declines the workflow-drift maintenance work as "scope creep wearing a phase-2 branch name" and states that "`go-tests.yml` pinning current versions on its own first commit is correct regardless of what the ten pre-existing workflows pin."

- [ ] **Step 2: Write the workflow**

  ```yaml
  name: Go Tests

  # Always triggers, and gates internally — the same shape as
  # frontend-tests.yml, backend-tests.yml, e2e-tests.yml and
  # lifecycle-tests.yml, and for the same reason. `Go result` at the bottom is
  # the aggregate that can be required on every PR; `build` and `lint` cannot
  # be, because a gated job that skips still reports, but a path-filtered
  # workflow that never triggers reports nothing at all, leaving a required
  # check "Expected" forever and blocking the merge.
  #
  # The coverage ratchet is NOT here. It arrives in 2c-9, which adds a job to
  # this workflow and a floor file beside it; the aggregate below already has
  # the shape to take it.
  on:
    push:
      branches: [main]
    pull_request:
      branches: [main]
    workflow_dispatch:

  permissions:
    contents: read

  concurrency:
    group: go-tests-${{ github.workflow }}-${{ github.ref }}
    cancel-in-progress: true

  jobs:
    changes:
      name: Detect relevant changes
      runs-on: ubuntu-latest
      timeout-minutes: 5
      outputs:
        go: ${{ steps.filter.outputs.go }}
      steps:
        # The `if:` is always true under this workflow's three triggers, and it
        # is copied deliberately rather than simplified: frontend-tests.yml,
        # e2e-tests.yml and lifecycle-tests.yml all carry the identical line,
        # so it is the house spelling of this job, and a fourth workflow that
        # differs invites the reader to wonder which one is wrong. If the
        # triggers ever grow a `schedule:`, it starts doing work.
        - name: Checkout code
          if: github.event_name == 'pull_request' || github.event_name == 'push'
          uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
          with:
            persist-credentials: false
            # pull_request checks out the merge commit, whose first parent is
            # the base branch tip — depth 2 is enough to diff the whole PR. A
            # push diffs github.event.before against the new head instead, and
            # that commit is at an unknown depth, so it needs full history.
            fetch-depth: ${{ github.event_name == 'pull_request' && 2 || 0 }}

        - name: Decide whether the Go jobs need to run
          id: filter
          env:
            EVENT_NAME: ${{ github.event_name }}
            EVENT_BEFORE: ${{ github.event.before }}
            HEAD_SHA: ${{ github.sha }}
          run: |
            if [ "$EVENT_NAME" = "workflow_dispatch" ]; then
              echo "go=true" >> "$GITHUB_OUTPUT"
              exit 0
            fi
            if [ "$EVENT_NAME" = "pull_request" ]; then
              changed=$(git diff --name-only HEAD^1 HEAD)
            else
              if [ "$EVENT_BEFORE" = "0000000000000000000000000000000000000000" ]; then
                echo "No previous commit to diff against; running the Go jobs."
                echo "go=true" >> "$GITHUB_OUTPUT"
                exit 0
              fi
              if ! changed=$(git diff --name-only "$EVENT_BEFORE" "$HEAD_SHA"); then
                echo "Could not diff the pushed range; running the Go jobs."
                echo "go=true" >> "$GITHUB_OUTPUT"
                exit 0
              fi
            fi
            printf 'Changed files:\n%s\n' "$changed"
            pattern='^(relay/|\.golangci\.yml$|scripts/check_go_stdlib_only\.sh$|\.github/workflows/go-tests\.yml$)'
            if printf '%s\n' "$changed" | grep -qE "$pattern"; then
              echo "go=true" >> "$GITHUB_OUTPUT"
            else
              echo "go=false" >> "$GITHUB_OUTPUT"
            fi

    build:
      name: Build, vet and test
      runs-on: ubuntu-latest
      needs: changes
      if: needs.changes.outputs.go == 'true'
      timeout-minutes: 15
      defaults:
        run:
          working-directory: ./relay
      steps:
        - name: Checkout code
          uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
          with:
            persist-credentials: false

        - name: Set up Go
          uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0
          with:
            # Read from go.mod rather than pinned here, so the toolchain has
            # exactly one source of truth and CI cannot drift from the
            # Dockerfile's builder stage without go.mod moving too.
            go-version-file: relay/go.mod

        - name: Build
          run: go build ./...

        - name: Vet
          run: go vet ./...

        # -race is not optional: the concurrency model changes from
        # gevent-cooperative to OS-thread-parallel goroutines in this phase, so
        # a data race the Python implementation made structurally impossible
        # becomes possible for the first time (spec § Testing).
        - name: Test with the race detector
          run: go test -race ./...

        - name: Assert the module is standard-library only
          working-directory: .
          run: scripts/check_go_stdlib_only.sh relay

    lint:
      name: golangci-lint
      runs-on: ubuntu-latest
      needs: changes
      if: needs.changes.outputs.go == 'true'
      timeout-minutes: 15
      steps:
        - name: Checkout code
          uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
          with:
            persist-credentials: false

        - name: Set up Go
          uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0
          with:
            go-version-file: relay/go.mod

        - name: Run golangci-lint
          uses: golangci/golangci-lint-action@ba0d7d2ec06a0ea1cb5fa41b2e4a3ab91d21278a # v9.3.0
          with:
            # Pinned deliberately, the same rule as zizmor's version in
            # actions-lint.yml: a new release adding a linter must not fail an
            # unrelated PR. Keep in sync with the version the PostToolUse hook
            # checks for (.claude/hooks/run-go-checks.sh).
            version: v2.13.2
            working-directory: relay

    # The one check in this workflow that may be required. It always reports,
    # because it is not gated on anything — see the comment on the triggers.
    go-result:
      name: Go result
      runs-on: ubuntu-latest
      needs: [changes, build, lint]
      if: always()
      timeout-minutes: 5
      steps:
        - name: Verify the Go outcome
          env:
            CHANGES_RESULT: ${{ needs.changes.result }}
            BUILD_RESULT: ${{ needs.build.result }}
            LINT_RESULT: ${{ needs.lint.result }}
            GO_REQUIRED: ${{ needs.changes.outputs.go }}
          run: |
            echo "changes=$CHANGES_RESULT build=$BUILD_RESULT lint=$LINT_RESULT go-required=$GO_REQUIRED"
            if [ "$CHANGES_RESULT" != "success" ]; then
              echo "Change detection itself failed — cannot prove the Go jobs were unnecessary."
              exit 1
            fi
            if [ "$GO_REQUIRED" != "true" ]; then
              echo "No Go-relevant paths changed; the Go jobs were deliberately skipped."
              exit 0
            fi
            # `skipped` here means a gated job never ran on a run that needed
            # it, so only an exact `success` may report green.
            for pair in "build:$BUILD_RESULT" "lint:$LINT_RESULT"; do
              if [ "${pair#*:}" != "success" ]; then
                echo "The Go jobs were required and ${pair%%:*} did not succeed."
                exit 1
              fi
            done
            echo "Go build, vet, tests and lint passed."
  ```

- [ ] **Step 3: zizmor must pass before this is committed**

  The edit hook runs it automatically on the write. If it is unavailable, run it by hand and do not commit on a skip:

  ```bash
  cd <your worktree> && zizmor --no-progress .github/workflows/go-tests.yml
  ```

  Zero findings, online audits on. **A "zizmor not installed" note is not a pass** — say the workflow was not linted rather than describing it as clean.

- [ ] **Step 4: Break-check the aggregate**

  The shape's own failure mode is a skipped heavy job on a required run, and it must fail. Temporarily add `if: false` to the `build` job **in addition to** its existing condition, push to the branch, and confirm `Go result` goes **red** with "The Go jobs were required and build did not succeed." Revert and confirm it goes green. Without this, the aggregate is a green light nobody has tested.

- [ ] **Step 5: Commit**

---

## Task 12: The two Claude hooks

Ruling R4 governs both: the module root comes from the edited or staged file's own path, never from `CLAUDE_PROJECT_DIR`, `BASH_SOURCE` or the working directory.

- [ ] **Step 1: Write `.claude/hooks/run-go-checks.sh`**

  ```bash
  #!/usr/bin/env bash
  # Claude Code PostToolUse hook — verify the Go module a just-edited .go file
  # belongs to.
  #
  # Four checks, all blocking, all scoped to that module:
  #
  #   build        go build ./...          the whole module
  #   vet          go vet ./...            the whole module
  #   lint         golangci-lint run       the whole module, zero findings
  #   tests        go test -race ./<pkg>   the edited file's package only
  #
  # Zero lint findings is a ratchet, the same rule as zizmor's: the module
  # starts clean and touching a file means leaving it clean. -race is not
  # optional (spec § Testing): this phase moves the relay from gevent's single
  # OS thread to parallel goroutines, so a data race becomes possible for the
  # first time, and -race is the cheapest check for exactly that class.
  #
  # THE MODULE ROOT COMES FROM THE EDITED FILE'S OWN PATH, by walking up for
  # go.mod — the same anchor _hook_common.sh's hook_repo_root() uses, resolving
  # a different thing. That helper returns the REPO root; `go build ./...` needs
  # the MODULE root, which is <repo>/relay and is defined by where go.mod sits,
  # not by where .git does. Hence the walk rather than a call.
  #
  # CLAUDE_HOOK_REPO_ROOT is honoured the same way the helper honours it, so a
  # manual or test run can pin the tree; the walk then starts from there.
  #
  # hook_container_mismatch() is deliberately NOT used: these checks run on the
  # host, with no container and no bind mount, so there is nothing for it to
  # judge. Its absence here is a decision, not an omission.
  #
  # Blocking failures exit 2, which feeds the output back to Claude. "Could not
  # run" exits 0 but is stated loudly — a silent skip is indistinguishable from
  # a pass.
  set -uo pipefail

  # shellcheck source=_hook_common.sh
  source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_hook_common.sh"

  GOLANGCI_EXPECTED_VERSION="2.13.2"

  INPUT="$(cat)"
  FILE="$(printf '%s' "$INPUT" | jq -r '.tool_response.filePath // .tool_input.file_path // empty')"
  [ -n "$FILE" ] || exit 0
  case "$FILE" in *.go) ;; *) exit 0 ;; esac
  [ -f "$FILE" ] || exit 0

  # Claude Code hands the hook an absolute path, exactly as the merged
  # run-affected-tests.sh assumes when it does `dirname "$FILE"`. No
  # relative-path branch: it would be dead code, and if it ever fired it would
  # resolve against the working directory this repo documents as unreliable
  # across concurrent sessions — the one input a hook must never trust.
  #
  # hook_canon_path resolves symlinks (pwd -P), so a /private-prefixed macOS
  # spelling and a plain one compare equal in the prefix strip below. PKG_DIR
  # is always the edited file's own directory; CLAUDE_HOOK_REPO_ROOT only moves
  # where the WALK starts, which is what a manual or test run needs to pin.
  PKG_DIR="$(hook_canon_path "$(dirname "$FILE")")"
  [ -n "$PKG_DIR" ] || exit 0
  START="$PKG_DIR"
  if [ -n "${CLAUDE_HOOK_REPO_ROOT:-}" ]; then
    START="$(hook_canon_path "$CLAUDE_HOOK_REPO_ROOT")"
    [ -n "$START" ] || exit 0
  fi

  # Walk up for go.mod. The module root is a property of the file, not of the
  # session.
  MODULE_ROOT="$START"
  while [ ! -f "$MODULE_ROOT/go.mod" ]; do
    [ "$MODULE_ROOT" = "/" ] && { MODULE_ROOT=""; break; }
    MODULE_ROOT="$(dirname "$MODULE_ROOT")"
  done
  if [ -z "$MODULE_ROOT" ]; then
    exit 0   # a .go file outside any module; nothing to check
  fi

  NOTES=()
  BLOCK_TITLE=""
  BLOCK_BODY=""
  note()  { NOTES+=("$1"); }
  block() { [ -n "$BLOCK_TITLE" ] || { BLOCK_TITLE="$1"; BLOCK_BODY="$2"; }; }

  if ! command -v go >/dev/null 2>&1; then
    note "Did NOT check ${FILE##*/} — go is not on PATH. The Go module was NOT verified; say so rather than describing the work as done."
  else
    OUT="$(cd "$MODULE_ROOT" && go build ./... 2>&1)"
    if [ $? -ne 0 ]; then
      block "go build failed in ${MODULE_ROOT}" "$(printf '%s' "$OUT" | head -30)"
    else
      OUT="$(cd "$MODULE_ROOT" && go vet ./... 2>&1)"
      if [ $? -ne 0 ]; then
        block "go vet failed in ${MODULE_ROOT}" "$(printf '%s' "$OUT" | head -30)"
      else
        # The edited file's own package, relative to the module root. The whole
        # module runs on commit; per-edit this is the fast, scoped check.
        # Both sides went through hook_canon_path, so the prefix strip is
        # comparing like with like. A file at the module root strips to "",
        # and "./" is a valid package spec for it.
        PKG="./${PKG_DIR#"$MODULE_ROOT"/}"
        [ "$PKG" = "./$PKG_DIR" ] && PKG="./..."
        OUT="$(cd "$MODULE_ROOT" && go test -race "$PKG" 2>&1)"
        if [ $? -ne 0 ]; then
          block "go test -race ${PKG} failed" "$(printf '%s' "$OUT" | grep -Ev '^(ok|\?)' | head -40)"
        else
          printf '%s\n' "$OUT" | grep -E '^(ok|---|PASS|FAIL)' | head -3
        fi
      fi
    fi
  fi

  if [ -z "$BLOCK_TITLE" ]; then
    if command -v golangci-lint >/dev/null 2>&1; then
      # Keep in sync with the pinned `version:` in go-tests.yml — that is the
      # whole point of this check. A silent version mismatch is worse than no
      # check: it lets local and CI disagree about what is clean.
      ACTUAL="$(golangci-lint --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
      if [ -n "$ACTUAL" ] && [ "$ACTUAL" != "$GOLANGCI_EXPECTED_VERSION" ]; then
        note "golangci-lint on PATH is ${ACTUAL}, but go-tests.yml pins ${GOLANGCI_EXPECTED_VERSION} — local and CI findings can disagree. Bump both together."
      fi
      OUT="$(cd "$MODULE_ROOT" && golangci-lint run ./... 2>&1)"
      if [ $? -ne 0 ]; then
        block "golangci-lint findings in ${MODULE_ROOT}" \
              "$(printf '%s' "$OUT" | head -30)"$'\n\n'"Zero findings is a ratchet here, the same rule as zizmor's for workflows."
      fi
    else
      note "Did NOT lint ${MODULE_ROOT} — golangci-lint is not installed. Install it with 'brew install golangci-lint'."
    fi
  fi

  if [ ${#NOTES[@]} -gt 0 ]; then
    MSG="$(printf '%s\n\n' "${NOTES[@]}")"
    jq -cn --arg m "$MSG" '{systemMessage:$m,hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$m}}'
  fi
  if [ -n "$BLOCK_TITLE" ]; then
    printf 'FAILED: %s\nFix this before continuing; do not describe the work as done.\n\n%s\n' \
      "$BLOCK_TITLE" "$BLOCK_BODY" >&2
    exit 2
  fi
  exit 0
  ```

  `chmod +x .claude/hooks/run-go-checks.sh`.

- [ ] **Step 2: Wire it into `.claude/settings.json`**

  Add a second entry to the existing `PostToolUse` `Write|Edit` matcher's `hooks` array, beside `run-affected-tests.sh`:

  ```json
  {
    "type": "command",
    "command": "\"${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/run-go-checks.sh\"",
    "timeout": 300,
    "statusMessage": "Running Go checks for the edited file"
  }
  ```

  Note this uses `CLAUDE_PROJECT_DIR` to **locate the script**, exactly as the existing entry does — that is issue #258's surface and is not this PR's to change. What R4 governs is what the script does once it runs, which is entirely independent of how it was found.

- [ ] **Step 3: Extend the commit gate**

  In `.claude/hooks/pre-commit-tests.sh`, after the `# ---------- frontend ----------` block and before `# ---------- metrics`:

  ```bash
  # ---------- go ----------
  # The whole module on commit, not just the edited package: this mirrors what
  # go-tests.yml runs, and the same rule the backend gate follows (CI runs the
  # whole package, so the gate does too).
  #
  # The module root is derived from the STAGED PATH by walking up for go.mod,
  # not assumed to be "$REPO_ROOT/relay" — Ruling R4, same reasoning as
  # run-go-checks.sh. $REPO_ROOT here is already correct as of #280 (the gate
  # anchors on its cwd, or on a parsed `cd <dir> &&` prefix), so this is not
  # compensating for a bad root; it is declining the separate assumption that
  # the module sits at a fixed place under it.
  GO_ROOTS="$(printf '%s\n' "$PATHS" | grep '\.go$' | while read -r p; do
    d="$(dirname "$REPO_ROOT/$p")"
    while [ "$d" != "/" ] && [ ! -f "$d/go.mod" ]; do d="$(dirname "$d")"; done
    [ -f "$d/go.mod" ] && printf '%s\n' "$d"
  done | sort -u)"
  if [ -n "$GO_ROOTS" ]; then
    if ! command -v go >/dev/null 2>&1; then
      note "Commit gate: Go files are staged but go is not on PATH — the Go tests were NOT run. The commit was NOT verified."
    else
      while read -r GR; do
        [ -n "$GR" ] || continue
        OUT="$(cd "$GR" && go build ./... 2>&1 && go vet ./... 2>&1 && go test -race ./... 2>&1)"
        if [ $? -ne 0 ]; then
          FAILED+=("go:${GR##*/}")
          REPORT+="$(printf '\n--- go %s ---\n%s\n' "$GR" "$(printf '%s' "$OUT" | grep -Ev '^(ok|\?)' | head -30)")"
        fi
      done <<< "$GO_ROOTS"
    fi
  fi
  ```

- [ ] **Step 4: Prove both hooks fire, and prove they fire for the right reason**

  This step is the whole value of the task. A hook that is wired but inert is the exact failure #258 describes, and it is invisible.

  1. **PostToolUse, failing:** use the Edit tool to add `func broken() { return 1 }` to `relay/buffer/buffer.go`. Expect the hook to block with "go build failed" and the compiler's own message. Revert with the Edit tool and confirm the hook passes.
  2. **PostToolUse, test failure rather than build failure:** use the Edit tool to change `MaxChunksPerChannel` to `200`. Expect a block naming `go test -race ./buffer` and the two failing assertions from Task 5 — **not** a build failure. Confirm the message names the mechanism (shape 6). Revert.
  3. **PostToolUse, lint:** use the Edit tool to add an unused import to `relay/httpapi/server.go`. Expect either the build or the lint arm to block; note which, because a build failure here means the lint arm was never exercised — if so, use an unused *variable* inside a function instead, which builds and lints red. Revert.
  4. **Commit gate:** stage a `relay/**.go` change with a failing test and attempt a commit. Expect "COMMIT BLOCKED — tests failing for: go:relay". Fix and confirm the commit proceeds.

  **Record all four outcomes in the PR description.** If any hook does not fire, that is a finding — report it rather than describing the hooks as wired.

  **The script was run at plan time** against a scratch module, with these results — match them, and treat a difference as a finding rather than a variation:

  | Payload | Result |
  |---|---|
  | a clean `.go` file | exit 0, prints `ok  github.com/…/relay/buffer  1.331s` |
  | a type error added | exit 2, `FAILED: go build failed in …` plus the compiler's own line |
  | a constant changed so a test fails | exit 2, `FAILED: go test -race ./buffer failed` plus `ChunkBytes = 1061072, want 255868` — a *test* failure, not a build one |
  | a non-`.go` path (`go.mod`) | exit 0, silent |
  | a `.go` file outside any module | exit 0, silent |
  | the same file spelled through a symlink (`/tmp/…` vs `/private/tmp/…`) | exit 0, package still resolved — this is what `hook_canon_path` buys |

  `shellcheck -x` reports only `SC2181` (checking `$?` rather than the command directly) on the four `OUT="$(…)"; if [ $? -ne 0 ]` pairs. That is the idiom the merged `run-affected-tests.sh` uses throughout, so it is house style here; do not "fix" it into a different shape from its sibling.

- [ ] **Step 5: Commit**

---

## Task 13: `CLAUDE.md`

Per the standing convention: a PR that changes a fact CLAUDE.md states corrects it in the same PR.

- [ ] **Step 1: § Commands** — add, after the frontend block:

  ```bash
  cd relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./...
  scripts/check_go_stdlib_only.sh relay           # the module must stay stdlib-only
  ```

- [ ] **Step 2: § Architecture** — the "Two uWSGI processes" paragraph now undercounts the container's processes. Add, after the supervisord sentence:

  > Since Phase 2 stage 2c there is a **third** server process, `relay-go` (`docker/supervisord.d/relay-go.conf`, roles `all` and `relay`, port 5658 from `DISPATCHARR_RELAY_GO_PORT`), a Go binary built in the Dockerfile's own `relay-builder` stage. At 2c-1 it serves `/healthz` and `/readyz` and nothing else: no nginx location routes to it until stage 2d, and every other route is behind a dev-only flag. It shares supervisord `priority=205` with `relay-uwsgi` deliberately — a priority of its own would add its `stopwaitsecs` to the container's stop budget as a separate group and take the sum past the 160s `stop_grace_period`. It opens no Postgres connection and no Redis connection, and links no driver for either; `scripts/check_go_stdlib_only.sh` is the mechanical backstop, run by `go-tests.yml`.

- [ ] **Step 3: § Test hooks** — add, in the existing register, after the zizmor bullet:

  > Go gets its own `PostToolUse` hook, `.claude/hooks/run-go-checks.sh`, on any `*.go` file: `go build ./...`, `go vet ./...` and `golangci-lint run` over the whole module plus `go test -race` for the edited file's package, all blocking, with zero lint findings as a ratchet in zizmor's idiom (the pinned version is checked against `go-tests.yml`'s, and a mismatch warns). `-race` is not optional and has no per-package exemption: this phase moves the relay off gevent's single OS thread, so a data race becomes possible for the first time. The commit gate runs `go build`, `go vet` and `go test -race ./...` over the whole module for any staged `*.go`. **Both anchor on the edited or staged file's own path, following #258's rule, and both then walk up for a `go.mod` rather than calling `hook_repo_root`** — that helper returns the *repo* root, and `go build ./...` needs the *module* root, which is `relay/` and is defined by where `go.mod` sits, not `.git`. They do borrow `hook_canon_path`, so a symlinked spelling of the same tree compares equal, and they honour `CLAUDE_HOOK_REPO_ROOT` the same way. `hook_container_mismatch` is deliberately unused: the Go checks run on the host with no container, so it has nothing to judge. Note that `relay/` paths map to **no** backend test label (`scripts/ci_backend_test_labels.py` returns `[]` for them), so for a Go-only commit the Go section of the gate is the only thing that runs.

  **Read `CLAUDE.md` § Test hooks as it stands on your branch before writing this in.** PR #280 rewrote that section's container paragraph, and the sentence above has to sit beside the merged text rather than contradict it — the merged paragraph already describes both hooks deriving their root from the edit and comparing it against the container's mount by destination.

- [ ] **Step 4: § Testing** — add after the E2E paragraph:

  > `go-tests.yml` is the fifth test workflow and carries the same four-part requireable shape as the others, with a **`Go result`** aggregate from its first commit. It runs `go build`, `go vet`, `go test -race` and `golangci-lint`, plus the stdlib-only assertion. It carries **no coverage gate yet** — 2c-9 adds the ratchet and the floor file. Making `Go result` an actually-required check on the Main ruleset is a repo-settings action, not something a commit accomplishes.

- [ ] **Step 5: § Supply chain security** — note the new pins in the existing register: `go-tests.yml` pins `actions/checkout` v7.0.1 while the other ten workflows pin v6.1.0, deliberately, per spec line 1783's refusal to fold workflow-drift maintenance into this phase. Record that CodeQL analyses `actions`, `python` and `javascript-typescript` and **not** `go` (Ruling R6, recommended owner 2c-9).

- [ ] **Step 6: Commit**

---

## Task 14: Final verification and the PR description

- [ ] **Step 1: Run everything, from a clean tree**

  ```bash
  cd <your worktree>
  gofmt -l relay/                                  # must print nothing
  (cd relay && go build ./...)
  (cd relay && go vet ./...)
  (cd relay && go test -race ./...)
  (cd relay && golangci-lint run ./...)
  scripts/check_go_stdlib_only.sh relay
  zizmor --no-progress .github/workflows/go-tests.yml
  docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.30.1 \
    detect --source=/repo --config=/repo/.gitleaks.toml --no-git -v --redact
  git status --porcelain                           # must print nothing
  ```

  Every one must be clean. **`gofmt -l` printing a filename is a failure**, even though nothing else catches it locally in this list.

  **This plan's Go was assembled into a scratch module and run through all four checks at plan time**: `go build ./...`, `go vet ./...`, `go test -race ./...` and `golangci-lint run ./...` with this plan's own `.golangci.yml`, returning `0 issues.` and passing tests, with `go.sum` absent and `go list -m all` printing the main module alone. So a lint finding on your run is a difference between your code and the plan's, not a gap in the plan — read it as one. Three fixes in the plan's code exist only because that run found them: `_, _ =` on the two `fmt.Fprintln` calls, `#nosec G101` on `DefaultSecretFile`, and `#nosec G304,G703` on `os.ReadFile`. The last of those is worth remembering as a habit rather than a fact: **silencing one gosec rule can reveal a second on the same line** — G703 was invisible until G304 was suppressed, so re-run the linter after every `#nosec` rather than assuming the line is now clean.

- [ ] **Step 2: Confirm the Python footprint is exactly Task 0's six files**

  Global Constraint 4 allows six Python paths and no others. Check the allowed set and the forbidden set separately, because one command answering "clean" for both hides which half it checked:

  ```bash
  cd <your worktree>
  echo "--- Python/app files this PR touches (expect exactly 6) ---"
  git diff --name-only main...HEAD | grep -E '^(apps/|core/|dispatcharr/|frontend/|e2e/|e2e-upstream/|metrics/)'
  echo "--- anything outside Task 0's six (expect nothing) ---"
  git diff --name-only main...HEAD \
    | grep -E '^(apps/|core/|dispatcharr/|frontend/|e2e/|e2e-upstream/|metrics/)' \
    | grep -vxE 'apps/proxy/next_source\.py|apps/proxy/serializers\.py|apps/proxy/tests/test_redirect_transcode_flag\.py|apps/proxy/live_proxy/tests/zero_orm_allowlist\.py|apps/proxy/tests/test_next_source_api\.py|apps/proxy/tests/test_next_source_resolution\.py' \
    && echo "VIOLATION" || echo "clean"
  ```

  The first block must list exactly those six paths; the second must print `clean`. **A first block with fewer than six entries is also a failure** — it means a Task 0 edit was lost, most likely in a rebase, and either the reconciliation table cites a field that is not in the tree or two existing tests are about to go red in CI.

- [ ] **Step 3: Write the PR description**

  It must contain, in this order:

  1. **The allowlist reconciliation** — all four tables and the Findings section, verbatim from Task 1. This is the spec's own precondition and its only enforcement is this description and its reviewer.
  2. **The four findings**, each with its recommended owner: F1 (Redirect has no contract field → 2c-5), F2 (no PR owns Redirect → 2c-5), F3 (`shlex` asymmetry → 2c-4), F4 (`proxy_settings` defaults are a second source of truth → 2c-2/2c-4).
  3. **The buffer-depth derivation and its number**: 300 chunks, 76,760,400 bytes per channel, the stated 10 Mbit/s reference bitrate, both crossover bitrates (10.23 Mbit/s where the cap starts binding before retention, 122.8 Mbit/s where it stops covering the join point), and the ~732 MiB ten-channel aggregate. Say plainly that the reference bitrate is an assumption and that no host-memory check exists.
  4. **Every pin, with the command that resolved it and the date.** Go toolchain, three action SHAs with their publishers confirmed, the `golang` image digest.
  5. **The stop-budget arithmetic** from Task 9 Step 3, and the sentence that `relay-go` shares `priority=205` for that reason.
  6. **Every break-check and its failure text.** Task 0 Step 7 (4, one of them expected green), Task 2 Step 5 (2), Task 3 Step 3 (4), Task 4 Step 4 (5), Task 5 Step 3 (3), Task 7 Step 3 (3), Task 11 Step 4 (1), Task 12 Step 4 (4) — **twenty-six** (4+2+4+5+3+3+1+4; the arithmetic is written out because this total has already drifted twice). A break-check that did not go red is a finding; report it as one, **except T0.7-1a, which is expected to stay green and whose report is what that tells you about branch-order coverage**. Say for each that the failure message named the mechanism rather than a build error (shape 6).
  7. **The measured allowlist edge count** from Task 0 Step 5 — the number `scan_edge` actually printed for `resolve_source`, whether it matched Ruling R8's predicted 38, and confirmation that `get_stream_object` is still 3.
  8. **The two runtime probes** from Task 8 Steps 2 and 3: the three status codes with the dev flag off, the 501 with it on, and the non-zero exit on a missing secret.
  9. **The cross-compile output** from Task 10 Step 4, both architectures.
  10. **What this PR does not do**, stated rather than implied: no coverage gate (2c-9), no drain and no `HEALTHCHECK` (2c-8), no nginx route (2d), no CodeQL Go pack (R6 and Amendment A1.5, owned by 2c-9), no parity-matrix Go column (2c-2 opens it), no Go consumer of `stream_profile.kind` (2c-2 is the first), no effective-`proxy_settings` fix (A1.4, owned by 2c-2), and no metrics/curated update — milestones are per stage, `phase2` already has its 2b entry, and the 2c goal milestone lands with 2c-9.

- [ ] **Step 4: Push and open the PR**

  Branch `migration/phase2c-skeleton`. The `migration/**` prefix makes `e2e-tests.yml` run every Playwright project — expect a long first CI run and do not interpret its length as a fault.

---

## Break-check × what each can redden

Twenty-six break-checks across eight tasks. Five green checks are not five proofs, and a reader not told which is which will assume they are. Each break-check must redden the column named here and leave the rest alone; a column going red that this table says cannot is a finding about the check, not a pass.

| Break-check | Python `kind` | `config` | `control` | `buffer` | `httpapi` | hook | CI aggregate |
|---|---|---|---|---|---|---|---|
| T0.7-1a reorder the kind branches | **— (deliberately)** | — | — | — | — | — | — |
| T0.7-1b delete the redirect branch | ✔ (helper + wire) | — | — | — | — | — | — |
| T0.7-2 drop the `locked` half | ✔ (the impostor test only) | — | — | — | — | — | — |
| T0.7-3 revert `_locked_ffmpeg_profile` | ✔ (the fourth-dict test only) | — | — | — | — | — | — |
| T2.5 go.sum / require | — | — | — | — | — | — | ✔ (the stdlib step) |
| T3.3-1 TrimSpace for the secret | — | ✔ | — | — | — | — | — |
| T3.3-2 ignore the port env | — | ✔ | — | — | — | — | — |
| T3.3-3 drop the dev override | — | ✔ | — | — | — | — | — |
| T3.3-4 drop DevRoutes from `Load`'s return | — | ✔ (the `Load` test **only**) | — | — | — | — | — |
| T4.4-1 wrong context string | — | — | ✔ | — | — | — | — |
| T4.4-2 wrong separator | — | — | ✔ | — | — | — | — |
| T4.4-3 drop the body digest | — | — | ✔ (with-body vector **only**) | — | — | — | — |
| T4.4-4 strip the query string | — | — | ✔ (both assertions) | — | — | — | — |
| T4.4-5 one-sided window | — | — | ✔ | — | — | — | — |
| T5.3-1 cap 200 chunks | — | — | — | ✔ (two tests) | — | — | — |
| T5.3-2 chunk = 188×5644 | — | — | — | ✔ | — | — | — |
| T5.3-3 ChunksForBytes guard | — | — | — | ✔ | — | — | — |
| T7.3-1 ungate the stream route | — | — | — | — | ✔ | — | — |
| T7.3-2 drop method matching | — | — | — | — | ✔ | — | — |
| T7.3-3 204 for health | — | — | — | — | ✔ | — | — |
| T11.4 skip the build job | — | — | — | — | — | — | ✔ |
| T12.4-1..4 hook firing | — | ✔ | — | ✔ | ✔ | ✔ | — |

Four notes on what this table is saying:

- **T0.7-1a is the one row in this table that must stay green, and it is there on purpose.** Swapping the order of `_profile_kind`'s two branches is a plausible-looking edit that changes nothing, because a locked Redirect profile is not a Proxy profile and vice versa. Running it and watching everything pass tells you what these tests do *not* pin — branch order — which is worth knowing before you rely on them. A break-check that stays green is normally a finding; this one is labelled, expected, and the label is what stops it being read as a failure of the suite.

- **T4.4-3 is the one that justifies having three vectors rather than one.** Dropping the body digest from the signed message leaves both empty-body tests **green** — `sha256(b"")` contributes the same constant either way only if you also drop it from Python, which you have not. Only the with-body vector fails. A single empty-body vector would have made this defect invisible, and it is a total replay-binding failure.
- **T5.3-1 must produce two failures, not one.** `TestConstantsMatchThePythonSource` says the number moved; `TestCapCoversFullRetentionAtTheReferenceBitrate` says *why the new number is wrong*. If only the first fires, the second test is not doing its job and the cap has no safety assertion behind it.
- **No break-check in this PR can redden `channel` or `ffmpeg`**, and that is structural, not an oversight: they are documented stubs with no assertions. Do not read their green as evidence of anything.
- **Task 0's column is the only one a Django test can redden, and none of the Go checks can touch it.** The two halves of this PR share no code path: a Go test cannot observe `stream_profile.kind` at all, because 2c-1 ships no control-plane client to read it with. That client arrives in 2c-5, and the field's first Go *consumer* is 2c-2. So Task 0's tests are the field's only guard for the next two PRs — which is why there are five of them for one string, and why three of the four T0 break-checks target a different one.

---

## What to report back

1. **The plan path, the branch and the commit SHA.**
2. **The allowlist reconciliation as executed** — the four counts you measured, whether they matched, any citation whose line had moved, and the `resolve_source` edge count Task 0 Step 5 measured against Ruling R8's predicted 38.
3. **Any finding beyond F1–F4.** The tables above were built by reading; the implementer reads again with a compiler.
4. **The buffer number, restated from your own arithmetic**, not copied from R2.
5. **Every pin you resolved, with the command and the date**, and whether any moved from this plan's values.
6. **Twenty-six break-check outcomes**, each with its failure text and a word on whether that text named the mechanism. T0.7-1a is expected green; say so rather than omitting it.
7. **The four hook-firing outcomes** from Task 12 Step 4, stated either way.
8. **Whether the `Go result` aggregate was proven to fail on a skipped required job** (Task 11 Step 4). Without that, R1's whole argument is untested.
9. **Anything you could not verify**, said plainly. A skipped check reported as a pass is the failure mode this repository's own CI history is built around avoiding.
